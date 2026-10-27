"""The monthly-transactions use case: a person's statement month as categorized rows."""

import asyncio

from calagent.application.categorizer import Categorizer
from calagent.domain.errors import StatementMissing
from calagent.domain.rows import TransactionRow, row_id
from calagent.ports.statements import StatementSource


class MonthlyTransactions:
    def __init__(self, source: StatementSource, categorizer: Categorizer) -> None:
        self._source = source
        self._categorizer = categorizer

    async def fetch(self, person: str, month: str) -> list[TransactionRow]:
        # A lookup can parse a PDF, so it runs on a worker thread to keep the event loop serving.
        statement = await asyncio.to_thread(self._source.find, person, month)
        if statement is None:
            raise StatementMissing(month)
        decisions = await self._categorizer.categorize(person, statement.charges)
        return [
            TransactionRow(
                id=row_id(statement.charge_date, position),
                transaction_date=charge.transaction_date,
                charge_date=statement.charge_date,
                merchant=decision.merchant,
                raw_merchant=charge.raw_merchant,
                amount=charge.amount,
                original_amount=None,
                original_currency=None,
                standing_order=charge.standing_order,
                abroad=charge.abroad,
                installment=charge.installment,
                category=decision.category,
                confidence=decision.confidence,
            )
            for position, (charge, decision) in enumerate(
                zip(statement.charges, decisions, strict=True), start=1
            )
        ]
