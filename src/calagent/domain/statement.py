"""A parsed card statement: its charges and the total the statement itself prints."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Installment:
    number: int
    total: int


@dataclass(frozen=True)
class Charge:
    transaction_date: date
    raw_merchant: str
    sector: str
    amount: Decimal
    installment: Installment | None
    standing_order: bool
    abroad: bool


@dataclass(frozen=True)
class Statement:
    billing_month: str
    charge_date: date
    charges: tuple[Charge, ...]
    printed_total: Decimal
