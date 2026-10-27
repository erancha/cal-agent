"""Task events shared across replicas through one Redis stream per task, cal:events:<id>.

Each entry holds the task version the event produced, the event's kind (the field it takes in the
SDK's StreamResponse) and the event as proto JSON. A subscriber reads the stream from its start,
skipping versions it already has, so it can replay from the version of the snapshot it was served.
"""

from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import cast

from a2a.server.agent_execution.active_task import INTERRUPTED_TASK_STATES, TERMINAL_TASK_STATES
from a2a.server.cluster import TaskEventStream, TaskVersion, VersionedEvent
from a2a.server.events import Event
from a2a.types import Message, StreamResponse, Task, TaskStatusUpdateEvent
from a2a.utils.proto_utils import to_stream_response
from google.protobuf import json_format
from redis.asyncio import Redis

from calagent.adapters.tasks.versions import version_number

_ENDING_STATES = TERMINAL_TASK_STATES | INTERRUPTED_TASK_STATES


def events_key(task_id: str) -> str:
    return f"cal:events:{task_id}"


class RedisTaskEventStream(TaskEventStream):
    def __init__(self, redis: Redis, ttl: timedelta, block_ms: int = 2000) -> None:
        """block_ms bounds each wait for a new entry and must stay below the client's socket
        timeout (5 s by default); after a wait that brought nothing the subscriber checks that the
        stream still exists."""
        self._redis = redis
        self._ttl = ttl
        self._block_ms = block_ms

    async def publish(self, task_id: str, event: VersionedEvent) -> None:
        key = events_key(task_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(
                key,
                {
                    "version": version_number(event.version),
                    "kind": to_stream_response(event.event).WhichOneof("payload"),
                    "event": json_format.MessageToJson(event.event),
                },
            )
            pipe.pexpire(key, self._ttl)
            await pipe.execute()

    async def subscribe(
        self, task_id: str, *, after: TaskVersion
    ) -> AsyncGenerator[VersionedEvent]:
        """Yields until a message or a status that ends the stream: a terminal state, or a pause
        for input or sign-in."""
        key = events_key(task_id)
        last_id = "0-0"
        while True:
            # One element per stream read: [key, [(entry id, fields), ...]].
            reply = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await self._redis.xread({key: last_id}, block=self._block_ms),
            )
            if not reply:
                if not await self._redis.exists(key):
                    raise RuntimeError(f"the events of task {task_id} ended before its last one")
                continue
            [[_, entries]] = reply
            for last_id, fields in entries:
                versioned = VersionedEvent(
                    event=_parse(fields["kind"], fields["event"]),
                    version=TaskVersion(int(fields["version"])),
                )
                if not versioned.version.is_after(after):
                    continue
                yield versioned
                if _ends(versioned.event):
                    return

    async def destroy(self, task_id: str) -> None:
        await self._redis.delete(events_key(task_id))


def _parse(kind: str, event_json: str) -> Event:
    response = StreamResponse()
    event: Event = getattr(response, kind)
    json_format.Parse(event_json, event)
    return event


def _ends(event: Event) -> bool:
    return isinstance(event, Message) or (
        isinstance(event, TaskStatusUpdateEvent | Task) and event.status.state in _ENDING_STATES
    )
