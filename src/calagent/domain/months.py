"""Billing months as YYYY-MM strings."""

import re

from calagent.domain.errors import InvalidMonthError

_MONTH = r"[0-9]{4}-(?:0[1-9]|1[0-2])"
_WHOLE = re.compile(_MONTH)
_EMBEDDED = re.compile(rf"(?<![0-9]){_MONTH}(?![0-9])")


def parse_billing_month(text: str) -> str:
    if _WHOLE.fullmatch(text) is None:
        raise InvalidMonthError(text)
    return text


def find_month(text: str) -> str | None:
    found = _EMBEDDED.search(text)
    return found.group() if found is not None else None
