import pytest

from calagent.domain.errors import InvalidMonthError
from calagent.domain.months import find_month, parse_billing_month


def test_parse_accepts_year_month() -> None:
    assert parse_billing_month("2026-10") == "2026-10"


@pytest.mark.parametrize("text", ["2026-9", "09/2026", "2026-13", "2026-10-02"])
def test_parse_refuses_other_shapes(text: str) -> None:
    with pytest.raises(InvalidMonthError):
        parse_billing_month(text)


def test_find_month_in_free_text() -> None:
    assert find_month("transactions for 2026-10") == "2026-10"


def test_find_month_absent() -> None:
    assert find_month("nothing") is None
