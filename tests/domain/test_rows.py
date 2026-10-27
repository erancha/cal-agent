from datetime import date
from decimal import Decimal

from calagent.domain.rows import (
    BATCH_SIZE,
    Confidence,
    TransactionRow,
    batch_wire,
    batches,
    row_id,
    to_wire,
)
from calagent.domain.statement import Installment

WIRE_KEYS = {
    "id",
    "transactionDate",
    "chargeDate",
    "merchant",
    "rawMerchant",
    "amount",
    "originalAmount",
    "originalCurrency",
    "standingOrder",
    "abroad",
    "installment",
    "category",
    "confidence",
}


def make_row(position: int = 1, installment: Installment | None = None) -> TransactionRow:
    return TransactionRow(
        id=row_id(date(2026, 10, 2), position),
        transaction_date=date(2026, 9, 28),
        charge_date=date(2026, 10, 2),
        merchant="Netflix",
        raw_merchant="NETFLIX.COM",
        amount=Decimal("46.21"),
        original_amount=None,
        original_currency=None,
        standing_order=True,
        abroad=False,
        installment=installment,
        category="entertainment",
        confidence=Confidence.HIGH,
    )


def test_row_id_pads_position() -> None:
    assert row_id(date(2026, 10, 2), 9) == "20261002-09"


def test_to_wire_has_the_contract_keys() -> None:
    wire = to_wire(make_row(installment=Installment(3, 10)))
    assert set(wire) == WIRE_KEYS
    assert wire["amount"] == 46.21 and isinstance(wire["amount"], float)
    assert wire["installment"] == {"number": 3, "total": 10}
    assert wire["transactionDate"] == "2026-09-28"
    assert wire["confidence"] == "high"
    assert wire["originalAmount"] is None


def test_to_wire_without_installment() -> None:
    assert to_wire(make_row())["installment"] is None


def test_empty_input_gives_one_empty_batch() -> None:
    assert batches([]) == [[]]


def test_batches_split_at_batch_size() -> None:
    rows = [make_row(i) for i in range(1, BATCH_SIZE + 2)]
    assert [len(b) for b in batches(rows)] == [25, 1]


def test_batch_wire_carries_currency() -> None:
    wire = batch_wire("2026-10", [make_row()])
    assert wire["currency"] == "ILS" and wire["month"] == "2026-10"
    assert len(wire["transactions"]) == 1
