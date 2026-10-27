import logging
from pathlib import Path
from typing import Any

import pytest
from a2a.helpers import get_text_parts, new_text_part
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import Message, Role, SendMessageRequest, TaskState
from a2a.utils.errors import A2AError

from calagent.platform.a2a.tck_executor import TckAgentExecutor
from tests.platform.support import a2a_client, ask, collect, make_app, states


class Recorder:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


async def run(message_id: str) -> list[Any]:
    message = Message(message_id=message_id, role=Role.ROLE_USER, parts=[new_text_part("hi")])
    context = RequestContext(
        ServerCallContext(),
        SendMessageRequest(message=message),
        task_id="t1",
        context_id="c1",
    )
    recorder = Recorder()
    await TckAgentExecutor().execute(context, recorder)  # type: ignore[arg-type]
    return recorder.events


async def test_a_chunked_artifact_appends_its_second_chunk() -> None:
    events = await run("tck-stream-artifact-chunked-1")

    chunks = [e for e in events if e.__class__.__name__ == "TaskArtifactUpdateEvent"]
    assert [get_text_parts(c.artifact.parts) for c in chunks] == [["chunk-1 "], ["chunk-2"]]
    assert [c.append for c in chunks] == [True, True]
    assert [c.last_chunk for c in chunks] == [False, True]


async def test_the_default_branch_completes_naming_the_unhandled_prefix() -> None:
    events = await run("something-else")

    final = events[-1].status
    assert final.state == TaskState.TASK_STATE_COMPLETED
    assert get_text_parts(final.message.parts) == ["Unhandled messageId prefix: something-else"]


async def test_input_required_branch_pauses_the_task() -> None:
    events = await run("tck-input-required-1")

    assert events[-1].status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_the_reject_branch_raises() -> None:
    with pytest.raises(A2AError, match="rejected"):
        await run("tck-reject-task-1")


async def test_the_tck_app_runs_a_default_branch_message_to_completion(tmp_path: Path) -> None:
    app = make_app(tmp_path, a2a_executor="tck", a2a_callers_file=tmp_path / "none.yaml")
    client = await a2a_client(app, token=None, secret=None)

    events = await ask(client, {"anything": 1})

    assert states(events)[-1] == "TASK_STATE_COMPLETED"


async def test_the_tck_app_answers_a_message_response_with_a_message(tmp_path: Path) -> None:
    app = make_app(tmp_path, a2a_executor="tck", a2a_callers_file=tmp_path / "none.yaml")
    client = await a2a_client(app, token=None, secret=None)
    message = Message(
        message_id="tck-message-response-1", role=Role.ROLE_USER, parts=[new_text_part("hi")]
    )

    events = await collect(client.send_message(SendMessageRequest(message=message)))

    [event] = events
    assert event.HasField("message")
    assert get_text_parts(event.message.parts) == ["Direct message response"]


async def test_the_tck_app_warns_that_authentication_is_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        make_app(tmp_path, a2a_executor="tck", a2a_callers_file=tmp_path / "none.yaml")

    [warning] = [r for r in caplog.records if "authentication is OFF" in r.getMessage()]
    assert warning.levelno == logging.WARNING
