"""Task leases in Redis, cal:lease:<id> holding the owner, so replicas never run a task twice."""

from typing import cast

from redis.asyncio import Redis

# KEYS: the lease. ARGV: owner, time to live in ms. 1 when the owner held the lease and renewed it.
_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
# KEYS: the lease. ARGV: owner.
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def lease_key(task_id: str) -> str:
    return f"cal:lease:{task_id}"


class RedisLease:
    def __init__(self, redis: Redis, ttl_seconds: float) -> None:
        self._redis = redis
        self._ttl_ms = int(ttl_seconds * 1000)
        self._renew = redis.register_script(_RENEW)
        self._release = redis.register_script(_RELEASE)

    async def acquire(self, task_id: str, owner: str) -> bool:
        return bool(await self._redis.set(lease_key(task_id), owner, nx=True, px=self._ttl_ms))

    async def renew(self, task_id: str, owner: str) -> bool:
        return bool(await self._renew(keys=[lease_key(task_id)], args=[owner, self._ttl_ms]))

    async def release(self, task_id: str, owner: str) -> None:
        await self._release(keys=[lease_key(task_id)], args=[owner])

    async def owner_of(self, task_id: str) -> str | None:
        return cast(str | None, await self._redis.get(lease_key(task_id)))
