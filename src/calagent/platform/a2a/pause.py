"""The pauses a task can enter and how a continue reads one back from the task.

A pause is a status message of two parts: a text for the human and a data part naming the
reason, the month and the person the task is for ("" while nobody has been verified). A continue
needs no memory beyond the task: the month and the person are read back from that data part.
"""

from dataclasses import dataclass
from typing import Any

from a2a.helpers import get_data_parts, new_data_part, new_text_part
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Role, Task, TaskState

# The statements page a statement-missing pause names, served at the root of the agent's URL.
PAGE_FILE = "statements.html"
PAGE_PATH = f"/{PAGE_FILE}"

STATEMENT_MISSING = "statement-missing"
SIGN_IN_REQUIRED = "sign-in-required"
REASONS = frozenset({STATEMENT_MISSING, SIGN_IN_REQUIRED})
PAUSED_STATES = frozenset({TaskState.TASK_STATE_INPUT_REQUIRED, TaskState.TASK_STATE_AUTH_REQUIRED})


@dataclass(frozen=True)
class Pause:
    reason: str
    month: str
    user: str


def read_pause(task: Task) -> Pause | None:
    """The newest pause of the task: the status message first, then the history newest first,
    since the SDK moves the status message into the history when a follow-up message arrives."""
    candidates = [task.status.message] if task.status.HasField("message") else []
    candidates.extend(reversed(task.history))
    for message in candidates:
        if message.role != Role.ROLE_AGENT:
            continue
        for data in get_data_parts(message.parts):
            if isinstance(data, dict) and data.get("reason") in REASONS:
                return Pause(data["reason"], data["month"], data["user"])
    return None


def pause_message(updater: TaskUpdater, text: str, data: dict[str, Any]) -> Message:
    return updater.new_agent_message([new_text_part(text), new_data_part(data)])
