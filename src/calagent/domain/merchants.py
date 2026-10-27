"""Merchant identity: the key under which a merchant's category is remembered."""

from dataclasses import dataclass

from calagent.domain.rows import Confidence

_COMPANY_FORMS = frozenset({'בע"מ', "בע״מ", "ltd", "ltd.", "inc"})


@dataclass(frozen=True)
class MerchantQuery:
    raw: str
    sector: str


@dataclass(frozen=True)
class Decision:
    merchant: str
    category: str
    confidence: Confidence


def merchant_key(raw: str) -> str:
    tokens = raw.lower().split()
    while tokens and (tokens[-1] in _COMPANY_FORMS or tokens[-1].isdigit()):
        tokens.pop()
    if not tokens:
        raise ValueError(f"merchant {raw!r} has no name left after dropping company forms")
    return " ".join(tokens)
