"""A classifier from a fixed substring table, for tests and keyless runs.

It knows every merchant of the fixture statement but one, so a test review always has a merchant
left for the person to categorize.
"""

from collections.abc import Sequence

from calagent.domain.taxonomy import UNCATEGORIZED
from calagent.ports.classifier import MerchantAnswer, MerchantQuery

# The first matching entry wins, so a more specific phrase precedes the word it contains.
_TABLE: tuple[tuple[str, str], ...] = (
    ("דמי חבר שופרסל", "other"),
    ("דמי כרטיס", "other"),
    ("מוקד אמון", "other"),
    ("שופרסל", "groceries"),
    ("סופר הנחלה", "groceries"),
    ("היבואן", "groceries"),
    ("אטליז", "groceries"),
    ("התמרים", "groceries"),
    ("דומינוס", "dining"),
    ("פז", "transport"),
    ("temu", "shopping"),
    ("מתנות", "gifts"),
    ("בריכות", "health"),
)


class KeywordClassifier:
    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        return [self._answer(query) for query in queries]

    @staticmethod
    def _answer(query: MerchantQuery) -> MerchantAnswer:
        lowered = query.raw.lower()
        for phrase, category in _TABLE:
            if phrase in lowered:
                return MerchantAnswer(query.raw, query.raw, category, 1.0)
        return MerchantAnswer(query.raw, query.raw, UNCATEGORIZED, 0.0)
