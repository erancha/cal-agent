from datetime import timedelta

import pytest
from a2a.server.cluster import ConcurrentTaskModificationError, TaskVersion
from a2a.server.context import ServerCallContext
from a2a.types import ListTasksRequest, Task, TaskState, TaskStatus
from redis.asyncio import Redis

from calagent.adapters.tasks.redis_task_store import RedisTaskStore
from calagent.platform.a2a.context import CallerUser

pytestmark = pytest.mark.integration

HFM = ServerCallContext(user=CallerUser("hfm"))
OTHER = ServerCallContext(user=CallerUser("other"))


def task(task_id: str, state: TaskState = TaskState.TASK_STATE_WORKING) -> Task:
    return Task(id=task_id, context_id="c1", status=TaskStatus(state=state))


async def first_save(store: RedisTaskStore, saved: Task) -> TaskVersion:
    return await store.save(
        saved, event=None, prev=None, prev_version=TaskVersion.MISSING, context=HFM
    )


async def test_a_first_save_is_read_back_at_version_1(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))

    version = await first_save(store, task("t1"))
    stored = await store.get("t1", HFM)

    assert version == TaskVersion(1)
    assert stored is not None
    assert stored.task == task("t1")
    assert stored.version == TaskVersion(1)


async def test_a_save_from_a_stale_version_is_refused(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    v1 = await first_save(store, task("t1"))
    await store.save(task("t1"), event=None, prev=None, prev_version=v1, context=HFM)

    with pytest.raises(ConcurrentTaskModificationError):
        await store.save(task("t1"), event=None, prev=None, prev_version=v1, context=HFM)
    with pytest.raises(ConcurrentTaskModificationError):
        await first_save(store, task("t1"))


async def test_a_cancel_overwrites_a_live_task_but_not_a_finished_or_absent_one(
    redis: Redis,
) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    await first_save(store, task("live"))
    await first_save(store, task("done", TaskState.TASK_STATE_COMPLETED))
    canceled = TaskState.TASK_STATE_CANCELED

    version = await store.save(
        task("live", canceled), event=None, prev=None, prev_version=TaskVersion(7), context=HFM
    )
    for task_id in ("done", "absent"):
        with pytest.raises(ConcurrentTaskModificationError):
            await store.save(
                task(task_id, canceled),
                event=None,
                prev=None,
                prev_version=TaskVersion(1),
                context=HFM,
            )

    assert version == TaskVersion(2)


async def test_another_owner_can_neither_read_nor_overwrite_a_task(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    v1 = await first_save(store, task("t1"))

    with pytest.raises(ConcurrentTaskModificationError):
        await store.save(task("t1"), event=None, prev=None, prev_version=v1, context=OTHER)
    with pytest.raises(ConcurrentTaskModificationError):
        await store.save(
            task("t1"), event=None, prev=None, prev_version=TaskVersion.MISSING, context=OTHER
        )
    await store.delete("t1", OTHER)

    assert await store.get("t1", OTHER) is None
    stored = await store.get("t1", HFM)
    assert stored is not None
    assert stored.version == v1


async def test_every_save_sets_the_time_to_live(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(seconds=100))
    await first_save(store, task("t1"))

    assert 0 < await redis.pttl("cal:task:t1") <= 100_000


async def test_delete_removes_the_task(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    await first_save(store, task("t1"))

    await store.delete("t1", HFM)

    assert await store.get("t1", HFM) is None
    assert not await redis.sismember("cal:tasks", "t1")


async def test_list_pages_through_the_owners_tasks_by_state(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    for n in range(5):
        await first_save(store, task(f"t{n}"))
    await first_save(store, task("paused", TaskState.TASK_STATE_INPUT_REQUIRED))
    await store.save(
        task("theirs"), event=None, prev=None, prev_version=TaskVersion.MISSING, context=OTHER
    )

    working = TaskState.TASK_STATE_WORKING
    first = await store.list(ListTasksRequest(status=working, page_size=3), HFM)
    second = await store.list(
        ListTasksRequest(status=working, page_size=3, page_token=first.next_page_token), HFM
    )

    assert first.total_size == 5
    assert [t.id for t in first.tasks] == ["t4", "t3", "t2"]
    assert [t.id for t in second.tasks] == ["t1", "t0"]
    assert second.next_page_token == ""


async def test_the_working_scan_crosses_owners_and_forgets_expired_tasks(redis: Redis) -> None:
    store = RedisTaskStore(redis, timedelta(days=30))
    await first_save(store, task("mine"))
    await first_save(store, task("paused", TaskState.TASK_STATE_INPUT_REQUIRED))
    await store.save(
        task("theirs"), event=None, prev=None, prev_version=TaskVersion.MISSING, context=OTHER
    )
    await first_save(store, task("expired"))
    await redis.delete("cal:task:expired")

    working = sorted(await store.working_tasks(), key=lambda owned: owned.task.id)

    assert [(w.task.id, w.owner, w.version) for w in working] == [
        ("mine", "hfm", TaskVersion(1)),
        ("theirs", "other", TaskVersion(1)),
    ]
    assert not await redis.sismember("cal:tasks", "expired")
