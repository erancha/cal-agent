from pathlib import Path

import pytest

from calagent.adapters.classifiers.keyword import KeywordClassifier
from calagent.adapters.pdf.cal_parser import CalStatementParser
from calagent.ports.classifier import MerchantQuery

UNKNOWN = "גפניקה"
FIXTURE = Path("tests/statements/2026-10.pdf")


async def test_every_fixture_merchant_but_one_is_known() -> None:
    charges = CalStatementParser().parse(FIXTURE).charges
    queries = [MerchantQuery(c.raw_merchant, c.sector) for c in charges]

    answers = await KeywordClassifier().classify(queries)

    for query, answer in zip(queries, answers, strict=True):
        if query.raw == UNKNOWN:
            assert (answer.category, answer.score) == ("uncategorized", 0.0)
        else:
            assert answer.category != "uncategorized"
            assert answer.score == 1.0


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        ("שופרסל און ליין", "groceries"),
        ("דומינוס פיצה", "dining"),
        ("פז אפליקציית יילו", "transport"),
        ("Temu.com", "shopping"),
        ('מוקד אמון - הו"ק', "other"),
        ("דמי כרטיס", "other"),
        ("דמי חבר שופרסל", "other"),
    ],
)
async def test_known_merchants_land_in_their_category(raw: str, category: str) -> None:
    [answer] = await KeywordClassifier().classify([MerchantQuery(raw, "")])

    assert answer.category == category
