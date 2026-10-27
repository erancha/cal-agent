"""Decides each charge's merchant name, category and confidence, asking the model only once.

Core responsibilities:
- Looks decisions up in the person's merchant memory by a key of merchant, sector and taxonomy
- Sends the merchants not yet remembered to the classifier in batches
- Validates answers (taxonomy, score range) and maps scores to confidence; remembers only usable
  answers, so a merchant whose answer fell back to uncategorized is asked again next time
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from calagent.domain.errors import CategorizerError
from calagent.domain.merchants import Decision, merchant_key
from calagent.domain.prompt import taxonomy_digest
from calagent.domain.rows import Confidence
from calagent.domain.statement import Charge
from calagent.domain.taxonomy import TAXONOMY, UNCATEGORIZED
from calagent.ports.classifier import MerchantAnswer, MerchantClassifier, MerchantQuery
from calagent.ports.memory import MerchantMemory


@dataclass(frozen=True)
class Thresholds:
    high: float
    medium: float


def memory_key(raw_merchant: str, sector: str) -> str:
    parts = (merchant_key(raw_merchant), sector, taxonomy_digest())
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class Categorizer:
    def __init__(
        self,
        classifier: MerchantClassifier,
        memory: MerchantMemory,
        thresholds: Thresholds,
        batch_size: int,
    ) -> None:
        self._classifier = classifier
        self._memory = memory
        self._thresholds = thresholds
        self._batch_size = batch_size

    async def categorize(self, person: str, charges: Sequence[Charge]) -> list[Decision]:
        keys = [memory_key(c.raw_merchant, c.sector) for c in charges]
        decisions = await self._memory.get(person, list(dict.fromkeys(keys)))
        unseen = {
            key: MerchantQuery(c.raw_merchant, c.sector)
            for key, c in zip(keys, charges, strict=True)
            if key not in decisions
        }
        learned: dict[str, Decision] = {}
        pending = list(unseen.items())
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            answers = await self._classifier.classify([query for _, query in batch])
            if len(answers) != len(batch):
                raise CategorizerError(
                    f"got {len(answers)} answers from the model for {len(batch)} merchants"
                )
            for (key, _), answer in zip(batch, answers, strict=True):
                decision, usable = self._decide(answer)
                decisions[key] = decision
                if usable:
                    learned[key] = decision
        if learned:
            await self._memory.put(person, learned)
        return [decisions[key] for key in keys]

    def _decide(self, answer: MerchantAnswer) -> tuple[Decision, bool]:
        """The decision and whether the answer was usable; only usable ones are remembered."""
        if answer.category not in TAXONOMY or not 0.0 <= answer.score <= 1.0:
            return Decision(answer.merchant, UNCATEGORIZED, Confidence.LOW), False
        return Decision(answer.merchant, answer.category, self._confidence(answer.score)), True

    def _confidence(self, score: float) -> Confidence:
        if score >= self._thresholds.high:
            return Confidence.HIGH
        if score >= self._thresholds.medium:
            return Confidence.MEDIUM
        return Confidence.LOW
