"""Two agent processes sharing one Redis behave as one agent, whichever replica a call reaches.

Each replica is a real uvicorn process run as the image runs it; the SDK client talks to it over
HTTP, A at 18030 (the URL the card advertises) and B at 18031.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import GetTaskRequest, ListTasksRequest, SubscribeToTaskRequest, TaskState
from a2a.utils.errors import UnsupportedOperationError

from tests.auth_keys import sign
from tests.platform.support import (
    SECRET,
    artifact_updates,
    ask,
    collect,
    ids,
    make_settings,
    place_fixture,
    rows_of,
    states,
)

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
A_PORT, B_PORT = 18030, 18031
COVERED = {"month": "2026-10"}
CONTINUE = {"action": "continue"}
RETRY_TEXT = "stopped while reading 2026-10; start the review again"


def base_url(port: int) -> str:
    return f"http://localhost:{port}"


@contextmanager
def replica(
    tmp_path: Path, port: int, redis_url: str, **settings: Any
) -> Iterator[subprocess.Popen[bytes]]:
    """A uvicorn process of the agent on the shared folder and Redis, until the block ends."""
    values = make_settings(
        tmp_path, tasks_redis_url=redis_url, agent_url=base_url(A_PORT), **settings
    ).model_dump(mode="json")
    env = os.environ | {
        key.upper(): str(value) for key, value in values.items() if value is not None
    }
    command = [sys.executable, "-m", "uvicorn", "calagent.platform.app:create_app", "--factory"]
    process = subprocess.Popen(
        [*command, "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env
    )
    try:
        _wait_healthy(process, port)
        yield process
    finally:
        process.kill()
        process.wait()


def _wait_healthy(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert process.poll() is None, f"the replica on {port} exited with {process.returncode}"
        try:
            if httpx.get(f"{base_url(port)}/health").status_code == 200:
                return
        except httpx.ConnectError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"the replica on {port} did not become healthy")


@asynccontextmanager
async def client_of(port: int) -> AsyncIterator[Client]:
    """A client that calls this replica, whatever URL the card advertises."""
    headers = {"Authorization": f"Bearer {sign()}", "X-Caller-Secret": SECRET}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        card = await A2ACardResolver(http, base_url(port)).get_agent_card()
        card.supported_interfaces[0].url = base_url(port)
        async with ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(
            card
        ) as client:
            yield client


async def working_task(client: Client) -> str:
    while True:
        listed = await client.list_tasks(ListTasksRequest(status=TaskState.TASK_STATE_WORKING))
        if listed.tasks:
            return listed.tasks[0].id
        await asyncio.sleep(0.05)


@pytest.mark.usefixtures("redis")
async def test_pause_on_a_continue_on_b_completes(tmp_path: Path, redis_url: str) -> None:
    with replica(tmp_path, A_PORT, redis_url), replica(tmp_path, B_PORT, redis_url):
        async with client_of(A_PORT) as a, client_of(B_PORT) as b:
            paused = await ask(a, COVERED)
            place_fixture(tmp_path)
            continued = await ask(b, CONTINUE, **ids(paused))

    assert states(paused)[-1] == "TASK_STATE_INPUT_REQUIRED"
    assert states(continued)[-1] == "TASK_STATE_COMPLETED"
    assert len(rows_of(continued)) == 19


@pytest.mark.usefixtures("redis")
async def test_subscribe_on_b_streams_a_task_running_on_a(tmp_path: Path, redis_url: str) -> None:
    place_fixture(tmp_path)
    with (
        replica(tmp_path, A_PORT, redis_url, cal_test_slow_ms=2000),
        replica(tmp_path, B_PORT, redis_url),
    ):
        async with client_of(A_PORT) as a, client_of(B_PORT) as b:
            running = asyncio.create_task(ask(a, COVERED))
            task_id = await asyncio.wait_for(working_task(b), 10)
            followed = await asyncio.wait_for(
                collect(b.subscribe(SubscribeToTaskRequest(id=task_id))), 20
            )
            await running

    assert states(followed)[0] == "TASK_STATE_WORKING"
    assert states(followed)[-1] == "TASK_STATE_COMPLETED"
    assert len(rows_of(followed)) == 19


@pytest.mark.usefixtures("redis")
async def test_a_killed_replica_leaves_a_failed_task_and_the_month_is_fetchable_again(
    tmp_path: Path, redis_url: str
) -> None:
    place_fixture(tmp_path)
    lease = {"task_lease_seconds": 3}
    with replica(tmp_path, B_PORT, redis_url, **lease):
        async with client_of(B_PORT) as b:
            with replica(
                tmp_path, A_PORT, redis_url, cal_test_slow_ms=60_000, **lease
            ) as a_process:
                async with client_of(A_PORT) as a:
                    running = asyncio.create_task(ask(a, COVERED))
                    task_id = await asyncio.wait_for(working_task(b), 10)
                    a_process.send_signal(signal.SIGKILL)
                    with pytest.raises(A2AClientError):
                        await running
            failed = await asyncio.wait_for(_until_failed(b, task_id), 20)
            again = await ask(b, COVERED)

    assert failed.message.parts[0].text == RETRY_TEXT
    assert states(again)[-1] == "TASK_STATE_COMPLETED"
    assert len(rows_of(again)) == 19


@pytest.mark.usefixtures("redis")
async def test_two_continues_at_once_run_the_task_once(tmp_path: Path, redis_url: str) -> None:
    slow = {"cal_test_slow_ms": 1500}
    with replica(tmp_path, A_PORT, redis_url, **slow), replica(tmp_path, B_PORT, redis_url, **slow):
        async with client_of(A_PORT) as a, client_of(B_PORT) as b:
            paused = await ask(a, COVERED)
            place_fixture(tmp_path)
            outcomes = await asyncio.gather(
                ask(a, CONTINUE, **ids(paused)),
                ask(b, CONTINUE, **ids(paused)),
                return_exceptions=True,
            )
            task = await a.get_task(GetTaskRequest(id=ids(paused)["task_id"]))

    [streamed] = [outcome for outcome in outcomes if isinstance(outcome, list)]
    [refused] = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert isinstance(refused, UnsupportedOperationError)
    assert f"task {ids(paused)['task_id']} is already running" in str(refused)
    assert len(artifact_updates(streamed)) == 1
    assert len(rows_of(streamed)) == 19
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert len(task.artifacts) == 1


async def _until_failed(client: Client, task_id: str) -> Any:
    while True:
        task = await client.get_task(GetTaskRequest(id=task_id))
        if task.status.state == TaskState.TASK_STATE_FAILED:
            return task.status
        assert task.status.state == TaskState.TASK_STATE_WORKING
        await asyncio.sleep(0.2)
