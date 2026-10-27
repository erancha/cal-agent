"""The FastAPI app: the A2A JSON-RPC and agent-card routes, health, and what they run on.

Core building blocks:
- AgentParts: the task store and event stream, the lease, the month pipeline, the statements and
  the lease sweep the app is built over
- default_parts: those parts from the settings, shared through Redis when TASKS_REDIS_URL is set
  and otherwise kept in this process
- build_app: the card, the executor and request handler (the conformance suite's scenario
  executor on the SDK's plain handler when A2A_EXECUTOR=tck), the call-context builder, the
  routes, the statements page and API, and the caller-secret middleware (only while
  authentication is required)
- create_app: uvicorn's factory (`calagent.platform.app:create_app --factory`)
"""

import asyncio
import logging
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from a2a.server.cluster import TaskEventStream
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from calagent.adapters.callers_file import load_callers
from calagent.adapters.classifiers.factory import classifier_for
from calagent.adapters.classifiers.slow import SlowClassifier
from calagent.adapters.google_tokens import GoogleTokenVerifier, JwksKeys, KeySource, StaticKey
from calagent.adapters.memory.in_memory import InMemoryMerchantMemory
from calagent.adapters.memory.redis import RedisMerchantMemory
from calagent.adapters.pdf.cal_parser import CalStatementParser
from calagent.adapters.statements_folder import StatementsFolder
from calagent.adapters.tasks.memory_lease import InMemoryLease
from calagent.adapters.tasks.redis_event_stream import RedisTaskEventStream
from calagent.adapters.tasks.redis_lease import RedisLease
from calagent.adapters.tasks.redis_task_store import RedisTaskStore
from calagent.application.categorizer import Categorizer, Thresholds
from calagent.application.monthly import MonthlyTransactions
from calagent.platform.a2a.callers import CallerSecretMiddleware
from calagent.platform.a2a.card import build_agent_card
from calagent.platform.a2a.context import CalCallContextBuilder
from calagent.platform.a2a.executor import CardAgentExecutor
from calagent.platform.a2a.handler import CardRequestHandler
from calagent.platform.a2a.pause import PAGE_FILE
from calagent.platform.a2a.sweep import LeaseSweep
from calagent.platform.a2a.tck_executor import TckAgentExecutor
from calagent.platform.config import Settings
from calagent.platform.logging import configure_logging
from calagent.platform.statements_api import add_statements_routes
from calagent.ports.classifier import MerchantClassifier
from calagent.ports.lease import TaskLease
from calagent.ports.memory import MerchantMemory
from calagent.ports.statements import StatementSource
from calagent.ports.tokens import TokenVerifier

RPC_PATH = "/"
CARD_CACHE_CONTROL = "max-age=3600, public"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentParts:
    """event_stream, sweep and redis are set exactly when the replicas share Redis."""

    task_store: TaskStore | RedisTaskStore
    event_stream: TaskEventStream | None
    lease: TaskLease
    monthly: MonthlyTransactions
    statements: StatementSource
    sweep: LeaseSweep | None
    redis: Redis | None


def default_parts(settings: Settings) -> AgentParts:
    statements = StatementsFolder(settings.statements_dir, CalStatementParser())
    if settings.tasks_redis_url is None:
        return AgentParts(
            task_store=InMemoryTaskStore(),
            event_stream=None,
            lease=InMemoryLease(settings.task_lease_seconds),
            monthly=MonthlyTransactions(
                statements, _categorizer(settings, InMemoryMerchantMemory())
            ),
            statements=statements,
            sweep=None,
            redis=None,
        )
    redis = Redis.from_url(settings.tasks_redis_url, decode_responses=True)
    task_store = RedisTaskStore(redis, settings.tasks_ttl)
    event_stream = RedisTaskEventStream(redis, settings.tasks_ttl)
    lease = RedisLease(redis, settings.task_lease_seconds)
    return AgentParts(
        task_store=task_store,
        event_stream=event_stream,
        lease=lease,
        monthly=MonthlyTransactions(statements, _categorizer(settings, RedisMerchantMemory(redis))),
        statements=statements,
        sweep=LeaseSweep(task_store, event_stream, lease, settings.task_lease_seconds),
        redis=redis,
    )


def _categorizer(settings: Settings, memory: MerchantMemory) -> Categorizer:
    classifier: MerchantClassifier = classifier_for(settings.llm_model, settings.llm_api_key)
    if settings.cal_test_slow_ms > 0:
        classifier = SlowClassifier(classifier, settings.cal_test_slow_ms / 1000)
    return Categorizer(
        classifier,
        memory,
        Thresholds(
            high=settings.categorizer_high_confidence,
            medium=settings.categorizer_medium_confidence,
        ),
        settings.categorizer_batch_size,
    )


def build_app(settings: Settings, parts: AgentParts) -> FastAPI:
    card = build_agent_card(settings)
    replica_id = f"{socket.gethostname()}:{os.getpid()}"
    handler: DefaultRequestHandler
    if settings.a2a_executor == "tck":
        logger.warning(
            "A2A_EXECUTOR=tck: authentication is OFF and the conformance-suite executor "
            "serves every request"
        )
        handler = DefaultRequestHandler(
            TckAgentExecutor(), parts.task_store, card, event_stream=parts.event_stream
        )
    else:
        handler = CardRequestHandler(
            CardAgentExecutor(parts.monthly, parts.lease, settings.task_lease_seconds),
            parts.task_store,
            card,
            parts.lease,
            replica_id,
            event_stream=parts.event_stream,
        )

    # Set while the lease sweep runs (only with Redis); /health reads it.
    sweeping: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal sweeping
        if parts.sweep is not None:
            sweeping = asyncio.create_task(parts.sweep.run())
            sweeping.add_done_callback(_report_sweep_end)
        yield
        # A sweep that already ended has had its error logged by _report_sweep_end.
        if sweeping is not None and not sweeping.done():
            sweeping.cancel()
            with suppress(asyncio.CancelledError):
                await sweeping
        await handler.aclose()
        if parts.redis is not None:
            await parts.redis.aclose()

    app = FastAPI(title="cal-agent", lifespan=lifespan)

    @app.get("/health")
    async def health() -> JSONResponse:
        """DOWN once the lease sweep has stopped, which reports the replica unhealthy."""
        if sweeping is not None and sweeping.done():
            return JSONResponse({"status": "DOWN"}, status_code=503)
        return JSONResponse({"status": "UP"})

    verifier = _verifier(settings)
    add_statements_routes(
        app, parts.statements, verifier, settings.auth_client_id, _page_path(settings)
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card, cache_control=CARD_CACHE_CONTROL),
        jsonrpc_routes=create_jsonrpc_routes(
            handler, RPC_PATH, context_builder=CalCallContextBuilder(verifier)
        ),
    )
    if settings.a2a_auth_required:
        app.add_middleware(
            CallerSecretMiddleware,
            callers=load_callers(settings.a2a_callers_file),
            rpc_path=RPC_PATH,
        )
    return app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Without settings this is the production process: it reads the environment and
    configures logging."""
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]
        configure_logging(settings.log_level, settings.a2a_log_level)
    return build_app(settings, default_parts(settings))


def _report_sweep_end(sweeping: asyncio.Task[None]) -> None:
    if not sweeping.cancelled():
        logger.error(
            "the lease sweep stopped; /health now answers DOWN",
            exc_info=sweeping.exception(),
        )


def _page_path(settings: Settings) -> Path:
    page = settings.static_dir.resolve() / PAGE_FILE
    if not page.is_file():
        raise ValueError(f"STATIC_DIR={settings.static_dir} has no {PAGE_FILE}: expected {page}")
    return page


def _verifier(settings: Settings) -> TokenVerifier | None:
    if not settings.a2a_auth_required:
        return None
    keys: KeySource
    if settings.auth_public_key_file is not None:
        keys = StaticKey.from_file(settings.auth_public_key_file)
    else:
        keys = JwksKeys(settings.auth_jwks_url)
    return GoogleTokenVerifier(keys, settings.auth_issuer)
