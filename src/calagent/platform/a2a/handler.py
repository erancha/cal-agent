"""The SDK's request handler with this agent's admission rules applied before a task starts.

The SDK stores a FAILED task whenever the executor raises, so a request that must be refused is
refused here, before the SDK creates or resumes the task:
- a new message must ask for a billing month;
- a message naming a task must be a continue, on a task waiting for input or sign-in, and must
  take the task's lease, so of two continues at once only one runs. The held lease is handed to
  the executor on the call context's state; from the executor's start, releasing it is its job.

Each call holds leases under an owner of its own (the replica's identity and a call id), so a
call releasing its lease can never drop one that a later call on the same replica holds.

Only the streaming send is served: a continue's lease is handed over on the stream, and the
callers of this agent always stream.
"""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor
from a2a.server.cluster import VersionedTaskStore
from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.request_handlers import DefaultRequestHandler, validate_request_params
from a2a.server.tasks import TaskStore
from a2a.types import AgentCard, GetTaskRequest, Message, SendMessageRequest, Task, TaskState
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError

from calagent.platform.a2a.pause import PAUSED_STATES
from calagent.platform.a2a.request import ContinueRequest, read_request
from calagent.ports.lease import TaskLease

# State key: the owner under which this call takes and releases task leases.
LEASE_OWNER_KEY = "lease_owner"
# State key: the id of the task whose lease this call took before the executor started.
HELD_LEASE_KEY = "held_lease"


class CardRequestHandler(DefaultRequestHandler):
    def __init__(
        self,
        agent_executor: AgentExecutor,
        task_store: TaskStore | VersionedTaskStore,
        agent_card: AgentCard,
        lease: TaskLease,
        replica_id: str,
        **sdk_options: Any,
    ) -> None:
        """sdk_options go to the SDK's handler as they are, the task event stream among them."""
        super().__init__(agent_executor, task_store, agent_card, **sdk_options)
        self._lease = lease
        self._replica_id = replica_id

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Message | Task:
        raise UnsupportedOperationError(message="this agent only streams; use SendStreamingMessage")

    @validate_request_params
    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        owner = f"{self._replica_id}:{uuid4().hex}"
        context.state[LEASE_OWNER_KEY] = owner
        task_id = params.message.task_id
        if not task_id:
            if isinstance(read_request(params.message), ContinueRequest):
                raise InvalidParamsError(message="a continue must name the paused task's taskId")
            async with aclosing(super().on_message_send_stream(params, context)) as events:
                async for event in events:
                    yield event
            return
        await self._claim_continue(task_id, params.message, owner, context)
        started = False
        try:
            async with aclosing(super().on_message_send_stream(params, context)) as events:
                async for event in events:
                    started = True
                    yield event
        except Exception:
            # An error before any event is the SDK refusing the message, so no executor will
            # release the lease. A caller leaving cancels this generator without passing here:
            # the SDK may run the executor anyway, so the lease stays with that run, or expires
            # with its time to live.
            if not started:
                await self._lease.release(task_id, owner)
            raise

    async def _claim_continue(
        self, task_id: str, message: Message, owner: str, context: ServerCallContext
    ) -> None:
        task = await self.on_get_task(GetTaskRequest(id=task_id), context)
        assert task is not None, "on_get_task raises TaskNotFoundError for an unknown task"
        if task.status.state not in PAUSED_STATES:
            raise InvalidParamsError(
                message=f"task {task_id} is {TaskState.Name(task.status.state)}; only a task "
                "waiting for input or sign-in can continue"
            )
        if not isinstance(read_request(message), ContinueRequest):
            raise InvalidParamsError(
                message=f'a message on task {task_id} must be {{"action": "continue"}}'
            )
        if not await self._lease.acquire(task_id, owner):
            raise UnsupportedOperationError(message=f"task {task_id} is already running")
        context.state[HELD_LEASE_KEY] = task_id
