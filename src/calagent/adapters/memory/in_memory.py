"""Merchant memory held in this process; nothing survives a restart."""

from collections.abc import Mapping, Sequence

from calagent.domain.merchants import Decision


class InMemoryMerchantMemory:
    def __init__(self) -> None:
        self._by_person: dict[str, dict[str, Decision]] = {}

    async def get(self, person: str, keys: Sequence[str]) -> dict[str, Decision]:
        remembered = self._by_person.get(person, {})
        return {key: remembered[key] for key in keys if key in remembered}

    async def put(self, person: str, decisions: Mapping[str, Decision]) -> None:
        self._by_person.setdefault(person, {}).update(decisions)
