"""The port through which a language model (or a stand-in) names the category of merchants."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from calagent.domain.merchants import MerchantQuery


@dataclass(frozen=True)
class MerchantAnswer:
    raw_merchant: str
    merchant: str
    category: str
    score: float


class MerchantClassifier(Protocol):
    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        """Answer once per query, in query order."""
        ...
