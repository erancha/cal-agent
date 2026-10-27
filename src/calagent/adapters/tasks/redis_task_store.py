"""The A2A tasks of every replica, kept in Redis with a version that refuses stale writes.

Each task is a hash cal:task:<id> holding the task as proto JSON, the caller that owns it, its
state name and its version (1 on the first write, one more on each later write); the set cal:tasks
holds every id. Every save resets the hash's time to live. The id of a task whose hash expired
stays in the set until a listing or a scan finds it gone.

Core building blocks:
- the save script, which checks owner and version and writes in one step
- list, which hands the owner's tasks to the SDK's in-memory store for its filters and paging
- working_tasks, the scan across every owner that the lease sweep reads
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from a2a.server.agent_execution.active_task import TERMINAL_TASK_STATES
from a2a.server.cluster import (
    ConcurrentTaskModificationError,
    StoredTask,
    TaskVersion,
    VersionedTaskStore,
)
from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState
from google.protobuf import json_format
from redis.asyncio import Redis

from calagent.adapters.tasks.versions import version_number

TASK_IDS_KEY = "cal:tasks"
_FIELDS = ("task", "owner", "version")
_REFUSED = -1

# KEYS: the task hash, the id set. ARGV: owner, previous version (0 for a first write), task JSON,
# state name, time to live in ms, task id, "1" for a cancel, then the terminal state names.
# Returns the new version, or -1 when the write is refused.
_SAVE = """
local stored = redis.call('HMGET', KEYS[1], 'owner', 'version', 'state')
local owner, version, state = stored[1], stored[2], stored[3]
if owner and owner ~= ARGV[1] then return -1 end
local new
if ARGV[7] == '1' then
  if not owner then return -1 end
  for i = 8, #ARGV do
    if state == ARGV[i] then return -1 end
  end
  new = tonumber(version) + 1
elseif ARGV[2] == '0' then
  if owner then return -1 end
  new = 1
else
  if not owner or version ~= ARGV[2] then return -1 end
  new = tonumber(version) + 1
end
redis.call('HSET', KEYS[1], 'task', ARGV[3], 'owner', ARGV[1], 'version', new, 'state', ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[5])
redis.call('SADD', KEYS[2], ARGV[6])
return new
"""
_TERMINAL_NAMES = [TaskState.Name(state) for state in TERMINAL_TASK_STATES]


@dataclass(frozen=True)
class OwnedTask:
    task: Task
    owner: str
    version: TaskVersion


def task_key(task_id: str) -> str:
    return f"cal:task:{task_id}"


class RedisTaskStore(VersionedTaskStore):
    def __init__(
        self,
        redis: Redis,
        ttl: timedelta,
        owner_resolver: OwnerResolver = resolve_user_scope,
    ) -> None:
        self._redis = redis
        self._ttl_ms = int(ttl.total_seconds() * 1000)
        self._owner_resolver = owner_resolver
        self._save = redis.register_script(_SAVE)

    async def save(
        self,
        task: Task,
        *,
        event: Event | None,
        prev: Task | None,
        prev_version: TaskVersion,
        context: ServerCallContext,
    ) -> TaskVersion:
        """A save by another owner is refused like a stale one: it never overwrites."""
        canceling = task.status.state == TaskState.TASK_STATE_CANCELED
        new_version = await self._save(
            keys=[task_key(task.id), TASK_IDS_KEY],
            args=[
                self._owner_resolver(context),
                version_number(prev_version),
                json_format.MessageToJson(task),
                TaskState.Name(task.status.state),
                self._ttl_ms,
                task.id,
                "1" if canceling else "0",
                *_TERMINAL_NAMES,
            ],
        )
        if new_version == _REFUSED:
            raise ConcurrentTaskModificationError(task.id)
        return TaskVersion(int(new_version))

    async def get(self, task_id: str, context: ServerCallContext) -> StoredTask | None:
        """None for an absent task and for another owner's task alike."""
        owned = await self._read(task_id)
        if owned is None or owned.owner != self._owner_resolver(context):
            return None
        return StoredTask(owned.task, owned.version)

    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        owner = self._owner_resolver(context)
        page = InMemoryTaskStore(self._owner_resolver, use_copying=False)
        for owned in await self._read_all():
            if owned.owner == owner:
                await page.save(owned.task, context)
        return await page.list(params, context)

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        owned = await self._read(task_id)
        if owned is not None and owned.owner == self._owner_resolver(context):
            await self._redis.delete(task_key(task_id))
            await self._redis.srem(TASK_IDS_KEY, task_id)

    async def working_tasks(self) -> Sequence[OwnedTask]:
        """Every owner's tasks in the working state."""
        return [
            owned
            for owned in await self._read_all()
            if owned.task.status.state == TaskState.TASK_STATE_WORKING
        ]

    async def _read(self, task_id: str) -> OwnedTask | None:
        fields = cast(list[str | None], await self._redis.hmget(task_key(task_id), _FIELDS))
        task_json, owner, version = fields
        if task_json is None:
            return None
        assert owner is not None and version is not None, "every save writes all three fields"
        return OwnedTask(json_format.Parse(task_json, Task()), owner, TaskVersion(int(version)))

    async def _read_all(self) -> Sequence[OwnedTask]:
        task_ids = sorted(cast(set[str], await self._redis.smembers(TASK_IDS_KEY)))
        found = [await self._read(task_id) for task_id in task_ids]
        expired = [task_id for task_id, owned in zip(task_ids, found, strict=True) if owned is None]
        if expired:
            await self._redis.srem(TASK_IDS_KEY, *expired)
        return [owned for owned in found if owned is not None]
