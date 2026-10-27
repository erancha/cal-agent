import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from calagent.adapters.tasks.redis_task_store import RedisTaskStore
from calagent.platform.a2a.sweep import LeaseSweep
from calagent.platform.app import build_app, default_parts
from tests.platform.support import http_client, make_settings, place_fixture


def test_without_redis_nothing_is_shared_and_nothing_is_swept(tmp_path: Path) -> None:
    parts = default_parts(make_settings(tmp_path))

    assert (parts.event_stream, parts.sweep, parts.redis) == (None, None, None)


@pytest.mark.integration
async def test_a_redis_url_shares_tasks_events_and_leases_and_sweeps(
    tmp_path: Path, redis_url: str
) -> None:
    parts = default_parts(make_settings(tmp_path, tasks_redis_url=redis_url))

    assert isinstance(parts.task_store, RedisTaskStore)
    assert parts.event_stream is not None
    assert parts.sweep is not None
    assert parts.redis is not None
    await parts.redis.aclose()


class BrokenSweep(LeaseSweep):
    def __init__(self) -> None:
        super().__init__(None, None, None, 60)  # type: ignore[arg-type]

    async def run(self) -> None:
        raise ValueError("unexpected")


async def test_health_is_down_once_the_sweep_has_stopped(tmp_path: Path) -> None:
    place_fixture(tmp_path)
    settings = make_settings(tmp_path)
    app = build_app(settings, replace(default_parts(settings), sweep=BrokenSweep()))

    async with app.router.lifespan_context(app), http_client(app, None) as http:
        await asyncio.sleep(0)
        response = await http.get("/health")

    assert (response.status_code, response.json()) == (503, {"status": "DOWN"})
