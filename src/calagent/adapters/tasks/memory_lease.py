"""Task leases held in this process, for a single replica; nothing survives a restart."""

import time


class InMemoryLease:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        # Key: task id. Value: (owner, monotonic time the lease expires).
        self._leases: dict[str, tuple[str, float]] = {}

    async def acquire(self, task_id: str, owner: str) -> bool:
        if await self.owner_of(task_id) is not None:
            return False
        self._leases[task_id] = (owner, time.monotonic() + self._ttl_seconds)
        return True

    async def renew(self, task_id: str, owner: str) -> bool:
        if await self.owner_of(task_id) != owner:
            return False
        self._leases[task_id] = (owner, time.monotonic() + self._ttl_seconds)
        return True

    async def release(self, task_id: str, owner: str) -> None:
        if await self.owner_of(task_id) == owner:
            del self._leases[task_id]

    async def owner_of(self, task_id: str) -> str | None:
        if task_id not in self._leases:
            return None
        owner, expires = self._leases[task_id]
        if time.monotonic() >= expires:
            del self._leases[task_id]
            return None
        return owner
