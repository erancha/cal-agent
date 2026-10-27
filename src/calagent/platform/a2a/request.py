"""Reads what a caller's message asks for: a billing month, or to continue a paused task.

A request is one data part, {"month": "YYYY-MM"} or {"action": "continue"}; a message with no
data part may instead hold the month in its text. Anything else is refused with
InvalidParamsError, which reaches the caller as a plain JSON-RPC error.
"""

from dataclasses import dataclass

from a2a.helpers import get_data_parts, get_text_parts
from a2a.types import Message
from a2a.utils.errors import InvalidParamsError

from calagent.domain.errors import InvalidMonthError
from calagent.domain.months import find_month, parse_billing_month

_SHAPES = '{"month": "YYYY-MM"} or {"action": "continue"}'


@dataclass(frozen=True)
class MonthRequest:
    month: str


@dataclass(frozen=True)
class ContinueRequest:
    pass


def read_request(message: Message) -> MonthRequest | ContinueRequest:
    data_parts = get_data_parts(message.parts)
    if not data_parts:
        month = find_month(" ".join(get_text_parts(message.parts)))
        if month is None:
            raise InvalidParamsError(message=f"send one data part {_SHAPES}")
        return MonthRequest(month)
    if len(data_parts) != 1:
        raise InvalidParamsError(message=f"send one data part, not {len(data_parts)}")
    [data] = data_parts
    if data == {"action": "continue"}:
        return ContinueRequest()
    if not isinstance(data, dict) or set(data) != {"month"} or not isinstance(data["month"], str):
        raise InvalidParamsError(message=f"the data part must be {_SHAPES}")
    try:
        return MonthRequest(parse_billing_month(data["month"]))
    except InvalidMonthError as error:
        raise InvalidParamsError(message=str(error)) from error
