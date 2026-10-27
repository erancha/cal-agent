"""Categorized transaction rows and their wire form for the monthly-transactions contract."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from calagent.domain.statement import Installment

BATCH_SIZE = 25
CURRENCY = "ILS"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class TransactionRow:
    id: str
    transaction_date: date
    charge_date: date
    merchant: str
    raw_merchant: str
    amount: Decimal
    original_amount: Decimal | None
    original_currency: str | None
    standing_order: bool
    abroad: bool
    installment: Installment | None
    category: str
    confidence: Confidence


def row_id(charge_date: date, position: int) -> str:
    return f"{charge_date:%Y%m%d}-{position:02d}"


def to_wire(row: TransactionRow) -> dict[str, Any]:
    installment = row.installment
    return {
        "id": row.id,
        "transactionDate": row.transaction_date.isoformat(),
        "chargeDate": row.charge_date.isoformat(),
        "merchant": row.merchant,
        "rawMerchant": row.raw_merchant,
        "amount": float(row.amount),
        "originalAmount": None if row.original_amount is None else float(row.original_amount),
        "originalCurrency": row.original_currency,
        "standingOrder": row.standing_order,
        "abroad": row.abroad,
        "installment": (
            None
            if installment is None
            else {"number": installment.number, "total": installment.total}
        ),
        "category": row.category,
        "confidence": row.confidence.value,
    }


def batch_wire(month: str, rows: Sequence[TransactionRow]) -> dict[str, Any]:
    return {"month": month, "currency": CURRENCY, "transactions": [to_wire(r) for r in rows]}


def batches(rows: Sequence[TransactionRow]) -> list[list[TransactionRow]]:
    if not rows:
        return [[]]
    return [list(rows[i : i + BATCH_SIZE]) for i in range(0, len(rows), BATCH_SIZE)]
