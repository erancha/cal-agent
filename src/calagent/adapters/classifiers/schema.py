"""The JSON schema both model adapters ask the provider to answer in, and its mapping to answers."""

from collections.abc import Mapping

from calagent.domain.errors import ClassifierError
from calagent.domain.taxonomy import TAXONOMY
from calagent.ports.classifier import MerchantAnswer

ANSWERS_SCHEMA: dict[str, object] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "rawMerchant": {"type": "string"},
            "merchant": {"type": "string"},
            "category": {"type": "string", "enum": list(TAXONOMY)},
            "confidence": {"type": "number"},
        },
        "required": ["rawMerchant", "merchant", "category", "confidence"],
        "additionalProperties": False,
    },
}

REPLY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"answers": ANSWERS_SCHEMA},
    "required": ["answers"],
    "additionalProperties": False,
}


def answers_from(reply: object) -> list[MerchantAnswer]:
    """Map a provider's parsed reply to answers; any other shape is a classifier failure."""
    try:
        return [
            MerchantAnswer(
                raw_merchant=_text(item["rawMerchant"]),
                merchant=_text(item["merchant"]),
                category=_text(item["category"]),
                score=_number(item["confidence"]),
            )
            for item in _items(reply)
        ]
    except (KeyError, TypeError) as error:
        raise ClassifierError(f"returned categories in an unexpected shape: {error!r}") from error


def _items(reply: object) -> list[Mapping[str, object]]:
    if not isinstance(reply, Mapping) or not isinstance(reply["answers"], list):
        raise TypeError("expected an object with an answers list")
    return reply["answers"]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected text, got {value!r}")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"expected a number, got {value!r}")
    return float(value)
