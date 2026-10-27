from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from calagent.adapters.memory.in_memory import InMemoryMerchantMemory
from calagent.application.categorizer import Categorizer, Thresholds, memory_key
from calagent.domain.errors import CategorizerError
from calagent.domain.rows import Confidence
from calagent.domain.statement import Charge
from calagent.ports.classifier import MerchantAnswer, MerchantClassifier, MerchantQuery

PERSON = "person-1"


class ScriptedClassifier:
    def __init__(self, answers: dict[str, tuple[str, float]] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[list[MerchantQuery]] = []

    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        self.calls.append(list(queries))
        return [self._answer(q) for q in queries]

    def _answer(self, query: MerchantQuery) -> MerchantAnswer:
        category, score = self.answers.get(query.raw, ("groceries", 0.9))
        return MerchantAnswer(query.raw, f"shown {query.raw}", category, score)


def charge(raw: str, sector: str = "food") -> Charge:
    return Charge(date(2026, 10, 1), raw, sector, Decimal(10), None, False, False)


def categorizer(classifier: MerchantClassifier, batch_size: int = 40) -> Categorizer:
    return Categorizer(
        classifier,
        InMemoryMerchantMemory(),
        Thresholds(high=0.85, medium=0.6),
        batch_size,
    )


async def test_asks_the_model_once_per_unseen_merchant_and_remembers() -> None:
    classifier = ScriptedClassifier()
    sut = categorizer(classifier)
    charges = [charge("shop"), charge("shop")]

    first = await sut.categorize(PERSON, charges)
    second = await sut.categorize(PERSON, charges)

    assert [len(call) for call in classifier.calls] == [1]
    assert first == second
    assert first[0] == first[1]
    assert first[0].merchant == "shown shop"


async def test_batches_by_batch_size() -> None:
    classifier = ScriptedClassifier()

    await categorizer(classifier, 40).categorize(PERSON, [charge(f"m{i}") for i in range(45)])

    assert [len(call) for call in classifier.calls] == [40, 5]
    assert [q.raw for call in classifier.calls for q in call] == [f"m{i}" for i in range(45)]


@pytest.mark.parametrize(
    ("score", "confidence"),
    [(0.9, Confidence.HIGH), (0.7, Confidence.MEDIUM), (0.3, Confidence.LOW)],
)
async def test_thresholds_map_scores_to_confidence(score: float, confidence: Confidence) -> None:
    sut = categorizer(ScriptedClassifier({"shop": ("dining", score)}))

    [decision] = await sut.categorize(PERSON, [charge("shop")])

    assert (decision.category, decision.confidence) == ("dining", confidence)


async def test_an_answer_outside_the_taxonomy_is_uncategorized_low() -> None:
    sut = categorizer(ScriptedClassifier({"shop": ("pets", 0.95)}))

    [decision] = await sut.categorize(PERSON, [charge("shop")])

    assert (decision.category, decision.confidence) == ("uncategorized", Confidence.LOW)


@pytest.mark.parametrize("score", [1.5, -0.1])
async def test_a_score_outside_the_range_is_uncategorized_low(score: float) -> None:
    sut = categorizer(ScriptedClassifier({"shop": ("dining", score)}))

    [decision] = await sut.categorize(PERSON, [charge("shop")])

    assert (decision.category, decision.confidence) == ("uncategorized", Confidence.LOW)


async def test_wrong_answer_count_fails() -> None:
    class Short:
        async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
            return []

    with pytest.raises(CategorizerError, match="0 answers.*1 merchants"):
        await categorizer(Short()).categorize(PERSON, [charge("shop")])


def test_memory_key_changes_with_the_sector() -> None:
    assert memory_key("shop", "food") != memory_key("shop", "fuel")
    assert memory_key("Shop Ltd", "food") == memory_key("shop", "food")


@pytest.mark.parametrize("answer", [("pets", 0.95), ("dining", 1.5)])
async def test_an_unusable_answer_is_not_remembered(answer: tuple[str, float]) -> None:
    classifier = ScriptedClassifier({"shop": answer})
    sut = categorizer(classifier)

    first = await sut.categorize(PERSON, [charge("shop")])
    second = await sut.categorize(PERSON, [charge("shop")])

    assert len(classifier.calls) == 2
    assert first == second
    assert first[0].category == "uncategorized"


async def test_a_usable_answer_is_remembered() -> None:
    classifier = ScriptedClassifier({"shop": ("dining", 0.9)})
    sut = categorizer(classifier)

    await sut.categorize(PERSON, [charge("shop")])
    await sut.categorize(PERSON, [charge("shop")])

    assert len(classifier.calls) == 1


async def test_a_changed_taxonomy_asks_the_model_again(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = ScriptedClassifier()
    sut = categorizer(classifier)
    await sut.categorize(PERSON, [charge("shop")])

    monkeypatch.setattr("calagent.application.categorizer.taxonomy_digest", lambda: "changed")
    await sut.categorize(PERSON, [charge("shop")])

    assert len(classifier.calls) == 2


ANSWERS = {"A": ("groceries", 0.9), "B": ("dining", 0.7), "C": ("transport", 0.3)}


async def test_repeated_merchants_keep_their_own_answers_in_order() -> None:
    classifier = ScriptedClassifier(ANSWERS)

    result = await categorizer(classifier).categorize(
        PERSON, [charge("A"), charge("B"), charge("A"), charge("C")]
    )

    assert [d.merchant for d in result] == ["shown A", "shown B", "shown A", "shown C"]
    assert [d.category for d in result] == ["groceries", "dining", "groceries", "transport"]
    assert [[q.raw for q in call] for call in classifier.calls] == [["A", "B", "C"]]


async def test_a_repeat_in_another_batch_is_queried_once_and_aligned() -> None:
    classifier = ScriptedClassifier(ANSWERS)

    result = await categorizer(classifier, 2).categorize(
        PERSON, [charge("A"), charge("B"), charge("C"), charge("A")]
    )

    assert [[q.raw for q in call] for call in classifier.calls] == [["A", "B"], ["C"]]
    assert [d.merchant for d in result] == ["shown A", "shown B", "shown C", "shown A"]
