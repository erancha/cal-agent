import asyncio
from datetime import timedelta

import pytest
from a2a.server.cluster import TaskVersion, VersionedEvent
from a2a.types import Task, TaskArtifactUpdateEvent, TaskState, TaskStatus, TaskStatusUpdateEvent
from redis.asyncio import Redis

from calagent.adapters.tasks.redis_event_stream import RedisTaskEventStream

pytestmark = pytest.mark.integration


def status(state: TaskState, version: int) -> VersionedEvent:
    event = TaskStatusUpdateEvent(task_id="t1", context_id="c1", status=TaskStatus(state=state))
    return VersionedEvent(event=event, version=TaskVersion(version))


SUBMITTED = VersionedEvent(
    event=Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)),
    version=TaskVersion(1),
)
ARTIFACT = VersionedEvent(
    event=TaskArtifactUpdateEvent(task_id="t1", context_id="c1", last_chunk=True),
    version=TaskVersion(3),
)


async def read_all(stream: RedisTaskEventStream, after: TaskVersion) -> list[VersionedEvent]:
    return [event async for event in stream.subscribe("t1", after=after)]


async def test_a_subscriber_gets_the_events_after_its_version_up_to_the_end(
    redis: Redis,
) -> None:
    stream = RedisTaskEventStream(redis, timedelta(days=30))
    for event in (
        SUBMITTED,
        status(TaskState.TASK_STATE_WORKING, 2),
        ARTIFACT,
        status(TaskState.TASK_STATE_COMPLETED, 4),
    ):
        await stream.publish("t1", event)

    events = await asyncio.wait_for(read_all(stream, TaskVersion(2)), 1)

    assert events == [ARTIFACT, status(TaskState.TASK_STATE_COMPLETED, 4)]
    assert 0 < await redis.pttl("cal:events:t1")


async def test_a_waiting_subscriber_gets_a_later_event_within_a_second(redis: Redis) -> None:
    stream = RedisTaskEventStream(redis, timedelta(days=30))
    await stream.publish("t1", SUBMITTED)
    reading = asyncio.create_task(read_all(stream, TaskVersion(1)))
    await asyncio.sleep(0.2)

    await stream.publish("t1", status(TaskState.TASK_STATE_INPUT_REQUIRED, 2))

    assert await asyncio.wait_for(reading, 1) == [status(TaskState.TASK_STATE_INPUT_REQUIRED, 2)]


async def test_destroy_removes_the_stream(redis: Redis) -> None:
    stream = RedisTaskEventStream(redis, timedelta(days=30))
    await stream.publish("t1", SUBMITTED)

    await stream.destroy("t1")

    assert not await redis.exists("cal:events:t1")


async def test_a_subscriber_whose_stream_is_destroyed_unfinished_fails(redis: Redis) -> None:
    stream = RedisTaskEventStream(redis, timedelta(days=30), block_ms=100)
    await stream.publish("t1", SUBMITTED)
    reading = asyncio.create_task(read_all(stream, TaskVersion(1)))
    await asyncio.sleep(0.2)

    await stream.destroy("t1")

    with pytest.raises(RuntimeError, match="t1"):
        await asyncio.wait_for(reading, 1)
