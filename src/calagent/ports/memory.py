"""The port holding each person's remembered merchant decisions."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from calagent.domain.merchants import Decision


class MerchantMemory(Protocol):
    async def get(self, person: str, keys: Sequence[str]) -> dict[str, Decision]:
        """The decisions remembered under these keys; keys never seen are absent."""
        ...

    async def put(self, person: str, decisions: Mapping[str, Decision]) -> None: ...
