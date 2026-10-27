"""Runs one monthly-transactions task: submitted, working, the rows, completed; or a pause.

Core responsibilities:
- Asks the person to sign in (auth-required) when the call carries no verified person, or a
  continue comes from another Google account than the one the task was started for
- Holds the task's lease from before WORKING until it pauses, ends or fails, renewing it in the
  background, so no other replica runs the task meanwhile
- Pauses for input when no statement of the person covers the month, naming the upload page
- Streams the rows as chunks of one artifact and completes; a statement, categorizer or model
  failure is raised as the cause, and the SDK fails the task with it

The request handler has already admitted the message: a new task asks for a month, and a continue
names a paused task whose lease it took. A continue confirms it still holds that lease before it
works, since the SDK may start the run after the lease's time to live ran out; when another call
holds it by then, the continue ends without touching the task.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from a2a.helpers import new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.utils.errors import InternalError

from calagent.application.monthly import MonthlyTransactions
from calagent.domain.errors import (
    CategorizerError,
    ClassifierError,
    StatementError,
    StatementMissing,
)
from calagent.domain.rows import batch_wire, batches
from calagent.platform.a2a.context import AUTH_FAILURE_KEY, PERSON_KEY
from calagent.platform.a2a.handler import HELD_LEASE_KEY, LEASE_OWNER_KEY
from calagent.platform.a2a.pause import (
    PAGE_PATH,
    SIGN_IN_REQUIRED,
    STATEMENT_MISSING,
    pause_message,
    read_pause,
)
from calagent.platform.a2a.request import MonthRequest, read_request
from calagent.ports.lease import TaskLease

logger = logging.getLogger(__name__)

ANOTHER_ACCOUNT = "a different Google account signed in than the one this review was started for"


class CardAgentExecutor(AgentExecutor):
    def __init__(
        self,
        monthly: MonthlyTransactions,
        lease: TaskLease,
        lease_seconds: int,
    ) -> None:
        self._monthly = monthly
        self._lease = lease
        self._lease_seconds = lease_seconds

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        assert task_id is not None and context_id is not None, "the SDK assigns both ids"
        updater = TaskUpdater(event_queue, task_id, context_id)
        owner = context.call_context.state[LEASE_OWNER_KEY]
        try:
            await self._run(context, event_queue, updater, owner)
        finally:
            await self._lease.release(task_id, owner)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Nothing to stop beyond what the SDK does: it cancels a running execute, whose finally
        releases the lease, and writes CANCELED itself. A paused task holds no lease."""

    async def _run(
        self, context: RequestContext, event_queue: EventQueue, updater: TaskUpdater, owner: str
    ) -> None:
        state = context.call_context.state
        task = context.current_task
        if task is None:
            assert context.message is not None, "a new task starts from the caller's message"
            request = read_request(context.message)
            assert isinstance(request, MonthRequest), "the handler admits only a month"
            month, user = request.month, ""
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        else:
            assert state[HELD_LEASE_KEY] == task.id, "the handler takes a continue's lease"
            pause = read_pause(task)
            if pause is None:
                raise InternalError(message=f"task {task.id} is paused without a pause message")
            month, user = pause.month, pause.user
        person = state[PERSON_KEY]
        if person is None:
            await self._ask_sign_in(updater, month, user, state[AUTH_FAILURE_KEY])
            return
        if user and user != person.sub:
            await self._ask_sign_in(updater, month, user, ANOTHER_ACCOUNT)
            return
        if task is None:
            acquired = await self._lease.acquire(updater.task_id, owner)
            assert acquired, "the SDK gives a new task a fresh id, so no call holds its lease"
        elif not await self._hold_continue_lease(task.id, owner):
            logger.warning(
                "task %s is run by another call; this continue leaves it as it is", task.id
            )
            return
        await updater.start_work(
            updater.new_agent_message([new_text_part(f"Parsing statement for {month}")])
        )
        await self._while_renewing(updater.task_id, owner, self._serve(updater, month, person.sub))

    async def _hold_continue_lease(self, task_id: str, owner: str) -> bool:
        """The handler's lease may have run out before the SDK started this run: take it again
        if nobody holds it. False when another call holds it; raising would make the SDK fail the
        task that call runs, so _run returns without any event instead."""
        return await self._lease.renew(task_id, owner) or await self._lease.acquire(task_id, owner)

    async def _serve(self, updater: TaskUpdater, month: str, person: str) -> None:
        try:
            rows = await self._monthly.fetch(person, month)
        except StatementMissing:
            await updater.requires_input(
                pause_message(
                    updater,
                    f"No statement covers {month}.",
                    {
                        "reason": STATEMENT_MISSING,
                        "month": month,
                        "page": PAGE_PATH,
                        "user": person,
                    },
                )
            )
            return
        except (StatementError, CategorizerError, ClassifierError) as failure:
            raise InternalError(message=str(failure)) from failure
        chunks = batches(rows)
        for position, chunk in enumerate(chunks):
            await updater.add_artifact(
                [new_data_part(batch_wire(month, chunk))],
                artifact_id=f"transactions-{updater.task_id}",
                name="transactions",
                append=position > 0,
                last_chunk=position == len(chunks) - 1,
            )
        await updater.complete()

    async def _ask_sign_in(self, updater: TaskUpdater, month: str, user: str, cause: str) -> None:
        await updater.requires_auth(
            pause_message(
                updater,
                f"could not verify who you are ({cause}); sign in again and continue",
                {"reason": SIGN_IN_REQUIRED, "month": month, "user": user},
            )
        )

    async def _while_renewing(
        self, task_id: str, owner: str, work: Coroutine[Any, Any, None]
    ) -> None:
        """Runs the work while renewing the lease. Losing the lease stops the work and fails the
        task: no replica takes over a working task, and the lease sweep fails one that holds no
        lease."""
        worker = asyncio.create_task(work)
        renewer = asyncio.create_task(self._renew(task_id, owner))
        try:
            await asyncio.wait({worker, renewer}, return_when=asyncio.FIRST_COMPLETED)
            if not worker.done():
                renewer.result()
            worker.result()
        finally:
            worker.cancel()
            renewer.cancel()
            await asyncio.gather(worker, renewer, return_exceptions=True)

    async def _renew(self, task_id: str, owner: str) -> None:
        while True:
            await asyncio.sleep(self._lease_seconds / 3)
            if not await self._lease.renew(task_id, owner):
                raise InternalError(message=f"lost the lease on task {task_id} while reading it")
