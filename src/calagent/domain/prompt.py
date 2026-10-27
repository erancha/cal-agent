"""The text a classifier reads: the category guides, the system prompt and the merchant lines.

Pure text and hashing, so every classifier adapter shares it. The taxonomy digest covers the
guides, so editing a guide makes remembered decisions stale.
"""

import hashlib
from collections.abc import Sequence

from calagent.domain.merchants import MerchantQuery
from calagent.domain.taxonomy import TAXONOMY

CATEGORY_GUIDES: dict[str, str] = {
    "groceries": "supermarkets, grocery stores, bakeries, butchers, greengrocers",
    "dining": "restaurants, cafes, bars, takeaway, food delivery",
    "transport": "fuel, public transport, taxis, tolls, parking, car repairs, car licensing",
    "utilities": "electricity, water, gas, phone, internet, water-filter rental",
    "housing": "rent, property tax (arnona), building committee, home repairs, hardware stores",
    "health": "clinics, doctors, dentists, pharmacies, gyms and fitness clubs",
    "insurance": "insurance premiums of any kind",
    "education": "schools, kindergartens, childcare, courses, children's activities",
    "shopping": "clothing, electronics, electrical appliances, furniture, online marketplaces",
    "entertainment": "streaming and TV, cinema, shows, games, hobbies, leisure clubs",
    "travel": "flights, hotels, car rental abroad, travel agencies",
    "gifts": "gift cards, flowers, presents, donations",
    "other": "bank and card fees, money transfers, anything that fits no other category",
    "uncategorized": "the business, or what it sells, cannot be told from the statement text",
}

_SYSTEM_TEMPLATE = """\
You categorize credit-card merchants for an Israeli household budget. Each input line is a
merchant string as the card statement prints it (Hebrew, English, truncated, or carrying
branch numbers), followed, when the statement prints one, by the issuer's own sector label
for that business in brackets: [sector: ...]. The sector is the issuer's hint about what the
business does; lean on it when the merchant string alone says little, as with a person's
name billed under a medical sector.
For each input return: rawMerchant (the merchant string echoed exactly, without the
bracketed sector), merchant (a readable display name in the language the statement prints
it in: a Hebrew string stays Hebrew and an English one English, never translated or
transliterated, even for a well-known Israeli brand; a self-explaining brand stays short,
"Netflix" or "סלקום", while a brand that alone does not say what the business does keeps
the words that do, "הראל ביטוח בריאות"), category (exactly one of the categories below),
confidence (0.0 to 1.0, your certainty in the category).

Categories:
%s

A category is what the money buys, not how it is paid: a membership, a standing order
(הוראת קבע) or an installment plan goes where its goods or service belong, so a gym is
health and a streaming service is entertainment. Judge the business, not a generic word in
its name: "סופר" or "מרכז" also start the names of shops that are not supermarkets. When
the business is unknown to you, answer "uncategorized" with a low confidence rather than a
guess. Answer through the schema: its answers list holds one element per input, in input order."""

SYSTEM_PROMPT = _SYSTEM_TEMPLATE.replace(
    "%s", "\n".join(f"- {name}: {CATEGORY_GUIDES[name]}" for name in TAXONOMY)
)


def taxonomy_digest() -> str:
    guides = "\n".join(f"{name}: {CATEGORY_GUIDES[name]}" for name in TAXONOMY)
    return hashlib.sha256(guides.encode()).hexdigest()


def merchant_lines(queries: Sequence[MerchantQuery]) -> str:
    return "\n".join(f"{q.raw} [sector: {q.sector}]" for q in queries)
