import asyncio
import json
import threading
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from calagent.adapters.classifiers.keyword import KeywordClassifier
from calagent.adapters.memory.in_memory import InMemoryMerchantMemory
from calagent.adapters.pdf.cal_parser import CalStatementParser
from calagent.application.categorizer import Categorizer, Thresholds
from calagent.application.monthly import MonthlyTransactions
from calagent.domain.errors import StatementMissing
from calagent.domain.rows import batch_wire
from calagent.domain.statement import Statement
from calagent.ports.statements import StoredFile

PERSON = "1000"
SCHEMA = Path("tests/contract/rows.schema.json")


class InMemorySource:
    def __init__(self, statements: dict[tuple[str, str], Statement]) -> None:
        self._statements = statements

    def find(self, person: str, month: str) -> Statement | None:
        return self._statements.get((person, month))

    def list(self, person: str) -> list[StoredFile]:
        raise NotImplementedError

    def store(self, person: str, data: bytes) -> StoredFile:
        raise NotImplementedError

    def delete(self, person: str, file_name: str) -> None:
        raise NotImplementedError


@pytest.fixture
def statement() -> Statement:
    return CalStatementParser().parse(Path("tests/statements/2026-10.pdf"))


def monthly_on(source: InMemorySource) -> MonthlyTransactions:
    categorizer = Categorizer(
        KeywordClassifier(), InMemoryMerchantMemory(), Thresholds(high=0.85, medium=0.6), 40
    )
    return MonthlyTransactions(source, categorizer)


@pytest.fixture
def monthly(statement: Statement) -> MonthlyTransactions:
    return monthly_on(InMemorySource({(PERSON, "2026-10"): statement}))


async def test_fetch_returns_the_statement_in_order_as_categorized_rows(
    monthly: MonthlyTransactions, statement: Statement
) -> None:
    rows = await monthly.fetch(PERSON, "2026-10")

    assert [r.id for r in rows] == [f"20261002-{n:02d}" for n in range(1, 20)]
    assert [r.raw_merchant for r in rows] == [c.raw_merchant for c in statement.charges]
    assert all(r.charge_date == date(2026, 10, 2) for r in rows)
    assert all(r.original_amount is None and r.original_currency is None for r in rows)
    assert rows[0].merchant == statement.charges[0].raw_merchant
    assert {r.category for r in rows} > {"groceries", "uncategorized"}


async def test_fetch_rows_satisfy_the_contract_schema(monthly: MonthlyTransactions) -> None:
    rows = await monthly.fetch(PERSON, "2026-10")

    validator = Draft202012Validator(
        json.loads(SCHEMA.read_text()),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(batch_wire("2026-10", rows))


async def test_a_month_without_a_statement_is_missing(monthly: MonthlyTransactions) -> None:
    with pytest.raises(StatementMissing) as raised:
        await monthly.fetch(PERSON, "2026-09")
    assert str(raised.value) == "has no statement for 2026-09"


async def test_another_persons_month_is_missing(monthly: MonthlyTransactions) -> None:
    with pytest.raises(StatementMissing):
        await monthly.fetch("2000", "2026-10")


class GatedSource(InMemorySource):
    """Holds every lookup until the event loop, left free while the lookup waits, opens the gate."""

    def __init__(self, statements: dict[tuple[str, str], Statement]) -> None:
        super().__init__(statements)
        self.gate = threading.Event()

    def find(self, person: str, month: str) -> Statement | None:
        assert self.gate.wait(timeout=2), "the lookup ran on the event loop and blocked it"
        return super().find(person, month)


async def test_a_lookup_does_not_block_the_event_loop(statement: Statement) -> None:
    source = GatedSource({(PERSON, "2026-10"): statement})
    fetch = asyncio.create_task(monthly_on(source).fetch(PERSON, "2026-10"))
    await asyncio.sleep(0)
    source.gate.set()
    assert len(await fetch) == 19
