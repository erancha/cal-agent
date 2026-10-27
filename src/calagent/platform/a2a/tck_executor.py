"""The scenario executor the A2A conformance suite (TCK) scripts against.

Each scenario is selected by the prefix of the messageId the suite sends. Branches are tested in
a fixed order, which decides how overlapping prefixes resolve (`tck-artifact-file-url` is tested
before `tck-artifact-file`). A message that matches none completes the task with a text naming
the unhandled prefix.
"""

import asyncio

from a2a.helpers import (
    new_data_part,
    new_raw_part,
    new_task_from_user_message,
    new_text_part,
    new_url_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part
from a2a.utils.errors import A2AError

TEXT_FILE_BYTES = b"tck"
RESUBSCRIBE_WORK_SECONDS = 4


class TckAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        assert message is not None, "the SDK passes the message that started the run"
        task_id, context_id = context.task_id, context.context_id
        assert task_id is not None and context_id is not None, "the SDK assigns both ids"
        message_id = message.message_id

        if message_id.startswith("tck-message-response"):
            await event_queue.enqueue_event(
                _agent_message(
                    TaskUpdater(event_queue, task_id, context_id), "Direct message response"
                )
            )
            return
        if context.current_task is None:
            await event_queue.enqueue_event(new_task_from_user_message(message))
        updater = TaskUpdater(event_queue, task_id, context_id)

        if message_id.startswith("tck-stream-artifact-chunked"):
            await updater.start_work()
            await updater.add_artifact([new_text_part("chunk-1 ")], append=True, last_chunk=False)
            await updater.add_artifact([new_text_part("chunk-2")], append=True, last_chunk=True)
            await updater.complete()
        elif message_id.startswith("test-resubscribe-message-id"):
            await updater.start_work()
            await asyncio.sleep(RESUBSCRIBE_WORK_SECONDS)
            await updater.complete()
        elif message_id.startswith("tck-stream-artifact-text"):
            await updater.start_work()
            await _artifact_then_complete(updater, new_text_part("Streamed text content"))
        elif message_id.startswith("tck-stream-artifact-file"):
            await updater.start_work()
            await _artifact_then_complete(updater, _text_file())
        elif message_id.startswith("tck-stream-ordering-001"):
            await updater.start_work()
            await _artifact_then_complete(updater, new_text_part("Ordered output"))
        elif message_id.startswith("tck-artifact-file-url"):
            await _artifact_then_complete(updater, _text_file_url())
        elif message_id.startswith("tck-input-required"):
            await updater.requires_input()
        elif message_id.startswith("tck-complete-task"):
            await updater.complete(_agent_message(updater, "Hello from TCK"))
        elif message_id.startswith("tck-artifact-text"):
            await _artifact_then_complete(updater, new_text_part("Generated text content"))
        elif message_id.startswith("tck-artifact-file"):
            await _artifact_then_complete(updater, _text_file())
        elif message_id.startswith("tck-artifact-data"):
            await _artifact_then_complete(updater, new_data_part({"key": "value", "count": 42}))
        elif message_id.startswith("tck-reject-task"):
            raise A2AError(message="rejected")
        elif message_id.startswith("tck-stream-001"):
            await updater.start_work()
            await _artifact_then_complete(updater, new_text_part("Stream hello from TCK"))
        elif message_id.startswith("tck-stream-002"):
            await updater.complete()
        elif message_id.startswith("tck-stream-003"):
            await updater.start_work()
            await _artifact_then_complete(updater, new_text_part("Stream task lifecycle"))
        else:
            await updater.complete(
                _agent_message(updater, f"Unhandled messageId prefix: {message_id}")
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        assert task_id is not None and context_id is not None, "the SDK assigns both ids"
        await TaskUpdater(event_queue, task_id, context_id).cancel()


async def _artifact_then_complete(updater: TaskUpdater, part: Part) -> None:
    await updater.add_artifact([part])
    await updater.complete()


def _agent_message(updater: TaskUpdater, text: str) -> Message:
    return updater.new_agent_message([new_text_part(text)])


def _text_file() -> Part:
    return new_raw_part(TEXT_FILE_BYTES, media_type="text/plain", filename="output.txt")


def _text_file_url() -> Part:
    return new_url_part(
        "https://example.com/output.txt", media_type="text/plain", filename="output.txt"
    )
