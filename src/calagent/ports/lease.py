"""The port that records which replica runs a task, so a task never runs twice at once."""

from typing import Protocol


class TaskLease(Protocol):
    """A lease per task held by one owner until it is released or its time to live runs out.

    An owner is one call: the replica's identity plus an id for the call. Every method acts only
    when the owner matches, so a call can never extend or drop a lease another call holds, on
    another replica or on the same one.
    """

    async def acquire(self, task_id: str, owner: str) -> bool:
        """Takes the lease when nobody holds it; False when anyone, this owner included, does."""
        ...

    async def renew(self, task_id: str, owner: str) -> bool:
        """Restarts the time to live; False when the owner no longer holds the lease."""
        ...

    async def release(self, task_id: str, owner: str) -> None:
        """Drops the lease when the owner holds it; otherwise does nothing."""
        ...

    async def owner_of(self, task_id: str) -> str | None: ...
