import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from a2a.helpers import new_data_part, new_message
from a2a.server.cluster import TaskVersion, VersionedEvent
from a2a.server.context import ServerCallContext
from a2a.types import Role, Task, TaskState, TaskStatus
from redis import exceptions as redis_errors
from redis.asyncio import Redis

from calagent.adapters.tasks.redis_event_stream import RedisTaskEventStream
from calagent.adapters.tasks.redis_lease import RedisLease
from calagent.adapters.tasks.redis_task_store import RedisTaskStore
from calagent.platform.a2a.context import CallerUser
from calagent.platform.a2a.sweep import LeaseSweep

HFM = ServerCallContext(user=CallerUser("hfm"))
RETRY_TEXT = "stopped while reading 2026-10; start the review again"


def working(task_id: str) -> Task:
    asked = new_message([new_data_part({"month": "2026-10"})], role=Role.ROLE_USER)
    return Task(
        id=task_id,
        context_id="c1",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        history=[asked],
    )


async def read_all(events: AsyncIterator[VersionedEvent]) -> list[VersionedEvent]:
    return [event async for event in events]


class Parts:
    def __init__(self, redis: Redis) -> None:
        self.store = RedisTaskStore(redis, timedelta(days=30))
        self.events = RedisTaskEventStream(redis, timedelta(days=30))
        self.lease = RedisLease(redis, 60)
        self.sweep = LeaseSweep(self.store, self.events, self.lease, 60)

    async def start(self, task: Task) -> TaskVersion:
        version = await self.store.save(
            task, event=None, prev=None, prev_version=TaskVersion.MISSING, context=HFM
        )
        await self.events.publish(task.id, VersionedEvent(event=task, version=version))
        return version

    async def state(self, task_id: str) -> str:
        stored = await self.store.get(task_id, HFM)
        assert stored is not None
        return TaskState.Name(stored.task.status.state)


@pytest.mark.integration
async def test_a_working_task_without_a_lease_on_two_passes_fails_with_the_retry_text(
    redis: Redis,
) -> None:
    parts = Parts(redis)
    await parts.start(working("orphan"))
    following = asyncio.create_task(
        read_all(parts.events.subscribe("orphan", after=TaskVersion(1)))
    )
    await asyncio.sleep(0.2)

    first = await parts.sweep.sweep({})
    after_first = await parts.state("orphan")
    await parts.sweep.sweep(first)
    [ending] = await asyncio.wait_for(following, 1)

    assert first == {"orphan": TaskVersion(1)}
    assert after_first == "TASK_STATE_WORKING"
    stored = await parts.store.get("orphan", HFM)
    assert stored is not None
    assert stored.task.status.state == TaskState.TASK_STATE_FAILED
    assert stored.task.status.message.parts[0].text == RETRY_TEXT
    assert ending.version == TaskVersion(2)
    assert ending.event.status.message.parts[0].text == RETRY_TEXT
    assert not await redis.exists("cal:events:orphan")


@pytest.mark.integration
async def test_a_leased_or_changed_task_is_left_working(redis: Redis) -> None:
    parts = Parts(redis)
    await parts.start(working("leased"))
    await parts.lease.acquire("leased", "replica-a:call-1")
    v1 = await parts.start(working("moving"))
    first = await parts.sweep.sweep({})
    await parts.store.save(working("moving"), event=None, prev=None, prev_version=v1, context=HFM)

    await parts.sweep.sweep(first)

    assert first == {"moving": TaskVersion(1)}
    assert await parts.state("leased") == "TASK_STATE_WORKING"
    assert await parts.state("moving") == "TASK_STATE_WORKING"


class FlakySweep(LeaseSweep):
    """Its first pass finds Redis unreachable; it records every later pass."""

    def __init__(self, failure: BaseException) -> None:
        super().__init__(None, None, None, 0.01)  # type: ignore[arg-type]
        self.failure = failure
        self.passes = 0

    async def sweep(self, unleased_before: Any) -> dict[str, TaskVersion]:
        self.passes += 1
        if self.passes == 1:
            raise self.failure
        return {}


async def test_a_pass_that_cannot_reach_redis_is_retried_on_the_next_interval() -> None:
    sweep = FlakySweep(redis_errors.ConnectionError("Connection refused"))

    running = asyncio.create_task(sweep.run())
    await asyncio.sleep(0.2)
    still_running = not running.done()
    running.cancel()

    assert still_running
    assert sweep.passes > 2


async def test_any_other_error_ends_the_sweep() -> None:
    sweep = FlakySweep(ValueError("unexpected"))

    with pytest.raises(ValueError):
        await asyncio.wait_for(sweep.run(), 1)
