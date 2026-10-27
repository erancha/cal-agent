"""Builds the agent's app on a temporary statements folder and talks to it as a registered caller.

The app runs in-process behind httpx's ASGI transport, so no port is opened and the SDK client
calls the URL the card advertises.
"""

import json
import shutil
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, new_data_part, new_message
from a2a.types import Role, SendMessageRequest, StreamResponse, TaskState
from fastapi import FastAPI
from jsonschema import Draft202012Validator

from calagent.application.monthly import MonthlyTransactions
from calagent.domain.rows import Confidence, TransactionRow
from calagent.platform.app import build_app, default_parts
from calagent.platform.config import Settings
from calagent.ports.lease import TaskLease
from tests.auth_keys import CALLER_CLIENT_ID, OTHER_CALLER_CLIENT_ID, PAGE_CLIENT_ID, PUBLIC_PEM

PERSON = "1000"
CALLER = "hfm"
SECRET = "caller-secret-1"
# A second registered caller, with a Google client of its own.
OTHER_CALLER = "budget"
OTHER_SECRET = "caller-secret-2"
AGENT_URL = "http://localhost:8030"
FIXTURE = Path(__file__).parents[1] / "statements" / "2026-10.pdf"
CONTRACT = Path(__file__).parents[1] / "contract"


def statement_path(tmp_path: Path, name: str = "2026-10.pdf") -> Path:
    return tmp_path / "statements" / PERSON / name


def place_fixture(tmp_path: Path) -> None:
    target = statement_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, target)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    callers = tmp_path / "callers.yaml"
    callers.write_text(
        json.dumps(
            {
                "callers": [
                    {"name": CALLER, "shared_secret": SECRET, "client_id": CALLER_CLIENT_ID},
                    {
                        "name": OTHER_CALLER,
                        "shared_secret": OTHER_SECRET,
                        "client_id": OTHER_CALLER_CLIENT_ID,
                    },
                ]
            }
        )
    )
    key = tmp_path / "key.pem"
    key.write_bytes(PUBLIC_PEM)
    statements = tmp_path / "statements"
    statements.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "statements_dir": statements,
        "llm_model": "keyword",
        "auth_client_id": PAGE_CLIENT_ID,
        "a2a_callers_file": callers,
        "auth_public_key_file": key,
        "agent_url": AGENT_URL,
        "tasks_redis_url": None,
    }
    return Settings(**(values | overrides))


def make_app(
    tmp_path: Path,
    monthly: MonthlyTransactions | None = None,
    lease: TaskLease | None = None,
    **overrides: Any,
) -> FastAPI:
    """The agent on person 1000's folder holding the fixture month, with any part replaced."""
    place_fixture(tmp_path)
    settings = make_settings(tmp_path, **overrides)
    parts = default_parts(settings)
    if monthly is not None:
        parts = replace(parts, monthly=monthly)
    if lease is not None:
        parts = replace(parts, lease=lease)
    return build_app(settings, parts)


def http_client(app: FastAPI, token: str | None, secret: str | None = SECRET) -> httpx.AsyncClient:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if secret is not None:
        headers["X-Caller-Secret"] = secret
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=AGENT_URL, headers=headers
    )


async def a2a_client(app: FastAPI, token: str | None, secret: str | None = SECRET) -> Client:
    http = http_client(app, token, secret)
    card = await A2ACardResolver(http, AGENT_URL).get_agent_card()
    return ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)


async def collect(stream: AsyncIterator[StreamResponse]) -> list[StreamResponse]:
    return [event async for event in stream]


def request(data: dict[str, Any], task_id: str = "", context_id: str = "") -> SendMessageRequest:
    message = new_message(
        [new_data_part(data)], role=Role.ROLE_USER, task_id=task_id, context_id=context_id
    )
    return SendMessageRequest(message=message)


async def ask(client: Client, data: dict[str, Any], **ids: str) -> list[StreamResponse]:
    return await collect(client.send_message(request(data, **ids)))


def states(events: list[StreamResponse]) -> list[str]:
    found = []
    for event in events:
        if event.HasField("task"):
            found.append(TaskState.Name(event.task.status.state))
        elif event.HasField("status_update"):
            found.append(TaskState.Name(event.status_update.status.state))
    return found


def ids(events: list[StreamResponse]) -> dict[str, str]:
    """The task and context ids, from the task snapshot that opens a new task's stream."""
    task = events[0].task
    return {"task_id": task.id, "context_id": task.context_id}


def last_status(events: list[StreamResponse]) -> Any:
    updates = [e.status_update for e in events if e.HasField("status_update")]
    return updates[-1].status


def pause_parts(events: list[StreamResponse]) -> tuple[str, dict[str, Any]]:
    """The text and the data of the pause that ends the stream."""
    parts = last_status(events).message.parts
    [text] = [part.text for part in parts if part.HasField("text")]
    [data] = get_data_parts(parts)
    return text, data


def artifact_updates(events: list[StreamResponse]) -> list[Any]:
    return [e.artifact_update for e in events if e.HasField("artifact_update")]


def rows_of(events: list[StreamResponse]) -> list[dict[str, Any]]:
    return [
        row
        for update in artifact_updates(events)
        for batch in get_data_parts(update.artifact.parts)
        for row in batch["transactions"]
    ]


def validator(schema: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((CONTRACT / schema).read_text()),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def made_up_row(position: int) -> TransactionRow:
    return TransactionRow(
        id=f"20261002-{position:02d}",
        transaction_date=date(2026, 9, 1),
        charge_date=date(2026, 10, 2),
        merchant=f"merchant {position}",
        raw_merchant=f"merchant {position}",
        amount=Decimal("10.00"),
        original_amount=None,
        original_currency=None,
        standing_order=False,
        abroad=False,
        installment=None,
        category="other",
        confidence=Confidence.HIGH,
    )


class FixedMonth(MonthlyTransactions):
    """Any month of any person is the given rows."""

    def __init__(self, rows: list[TransactionRow]) -> None:
        self._rows = rows

    async def fetch(self, person: str, month: str) -> list[TransactionRow]:
        return self._rows
