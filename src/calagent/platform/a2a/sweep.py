"""Fails the tasks whose replica stopped while working on them, so the caller can start again.

A replica holds a task's lease for as long as it works on the task. A working task that has no
lease on two passes in a row, unchanged in between, was left behind by a replica that stopped: the
sweep saves it FAILED with a text asking to start the review again, publishes that status to the
task's subscribers on every replica, then deletes the task's event stream. Asking for two passes
keeps the sweep off a task whose replica released the lease a moment before its final state was
saved.

Every replica runs the sweep; of two replicas failing one task, the version check lets one win.
A pass that cannot reach Redis is logged and the next interval tries again, so a Redis restart
does not end the sweep; any other error ends it.
"""

import asyncio
import logging
from collections.abc import Mapping

from a2a.helpers import new_text_status_update_event
from a2a.server.cluster import (
    ConcurrentTaskModificationError,
    TaskEventStream,
    TaskVersion,
    VersionedEvent,
)
from a2a.server.context import ServerCallContext
from a2a.types import Task, TaskState
from redis import exceptions as redis_errors

from calagent.adapters.tasks.redis_task_store import OwnedTask, RedisTaskStore
from calagent.platform.a2a.context import CallerUser
from calagent.platform.a2a.pause import read_pause
from calagent.platform.a2a.request import MonthRequest, read_request
from calagent.ports.lease import TaskLease

logger = logging.getLogger(__name__)


class LeaseSweep:
    def __init__(
        self,
        store: RedisTaskStore,
        events: TaskEventStream,
        lease: TaskLease,
        interval_seconds: float,
    ) -> None:
        self._store = store
        self._events = events
        self._lease = lease
        self._interval_seconds = interval_seconds

    async def run(self) -> None:
        """Sweeps at start and then every interval, until cancelled."""
        unleased: dict[str, TaskVersion] = {}
        while True:
            try:
                unleased = await self.sweep(unleased)
            except redis_errors.ConnectionError, redis_errors.TimeoutError:
                logger.exception("the lease sweep could not reach Redis; it retries next interval")
            await asyncio.sleep(self._interval_seconds)

    async def sweep(self, unleased_before: Mapping[str, TaskVersion]) -> dict[str, TaskVersion]:
        """Fails the working tasks found without a lease on the previous pass at the same version,
        and returns those found without a lease now (task id to version)."""
        unleased: dict[str, TaskVersion] = {}
        for owned in await self._store.working_tasks():
            task_id = owned.task.id
            if await self._lease.owner_of(task_id) is not None:
                continue
            if unleased_before.get(task_id) == owned.version:
                await self._fail(owned)
            else:
                unleased[task_id] = owned.version
        return unleased

    async def _fail(self, owned: OwnedTask) -> None:
        task = owned.task
        event = new_text_status_update_event(
            task.id,
            task.context_id,
            TaskState.TASK_STATE_FAILED,
            f"stopped while reading {_month_of(task)}; start the review again",
        )
        event.status.timestamp.GetCurrentTime()
        failed = Task()
        failed.CopyFrom(task)
        if failed.status.HasField("message"):
            failed.history.append(failed.status.message)
        failed.status.CopyFrom(event.status)
        try:
            version = await self._store.save(
                failed,
                event=event,
                prev=task,
                prev_version=owned.version,
                context=ServerCallContext(user=CallerUser(owned.owner)),
            )
        except ConcurrentTaskModificationError:
            logger.info("task %s changed while being swept; left as it now is", task.id)
            return
        logger.warning("task %s had no replica working on it; marked failed", task.id)
        await self._events.publish(task.id, VersionedEvent(event=event, version=version))
        await self._events.destroy(task.id)


def _month_of(task: Task) -> str:
    """The month of a continued task is in its pause; a new task's is in its first message."""
    pause = read_pause(task)
    if pause is not None:
        return pause.month
    request = read_request(task.history[0])
    assert isinstance(request, MonthRequest), "a task starts from a message asking for a month"
    return request.month
