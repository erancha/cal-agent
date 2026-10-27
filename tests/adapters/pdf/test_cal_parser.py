import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter

from calagent.adapters.pdf import cal_parser
from calagent.adapters.pdf.cal_parser import CalStatementParser
from calagent.adapters.pdf.words import Word, columns_from_header
from calagent.domain.errors import StatementError
from calagent.domain.statement import Installment, Statement
from tests.adapters.pdf.test_words import HEADER

FIXTURE = Path(__file__).parents[2] / "statements" / "2026-10.pdf"


@pytest.fixture(scope="module")
def statement() -> Statement:
    return CalStatementParser().parse(FIXTURE)


def test_month_and_charge_date_come_from_the_title(statement: Statement) -> None:
    assert statement.billing_month == "2026-10"
    assert statement.charge_date == date(2026, 10, 2)


def test_reads_19_rows_adding_up_to_the_printed_total(statement: Statement) -> None:
    assert len(statement.charges) == 19
    assert statement.printed_total == Decimal("13986.22")
    assert sum(c.amount for c in statement.charges) == statement.printed_total


def test_rows_in_statement_order_with_their_fields(statement: Statement) -> None:
    rows = {position: charge for position, charge in enumerate(statement.charges, start=1)}

    first = rows[1]
    assert first.transaction_date == date(2026, 7, 23)
    assert first.raw_merchant == 'ספלש בריכות שחיה בע"מ'
    assert first.sector == "ריהוט ובית"
    assert first.amount == Decimal("796.00")
    assert first.installment == Installment(3, 3)

    pizza = rows[4]
    assert pizza.transaction_date == date(2026, 9, 3)
    assert (pizza.raw_merchant, pizza.sector, pizza.amount) == (
        "דומינוס פיצה",
        "מסעדות",
        Decimal("131.30"),
    )
    assert pizza.installment is None
    assert pizza.standing_order is False

    details_wrapped = rows[10]
    assert details_wrapped.transaction_date == date(2026, 9, 14)
    assert (details_wrapped.raw_merchant, details_wrapped.sector, details_wrapped.amount) == (
        "היבואן ראשון לציון-צמרת",
        "מזון ומשקא",
        Decimal("77.00"),
    )

    butcher = rows[11]
    assert butcher.transaction_date == date(2026, 9, 16)
    assert (butcher.raw_merchant, butcher.amount) == (
        "1 - אטליז גבריאלוב - אלון",
        Decimal("1891.10"),
    )

    merchant_wrapped = rows[14]
    assert merchant_wrapped.transaction_date == date(2026, 9, 24)
    assert (merchant_wrapped.raw_merchant, merchant_wrapped.amount) == (
        "התמרים של שרית-עמוס עמירה",
        Decimal("250.00"),
    )

    temu = rows[15]
    assert temu.transaction_date == date(2026, 9, 26)
    assert (temu.raw_merchant, temu.sector, temu.amount) == (
        "Temu.com",
        "בתי כלבו",
        Decimal("183.85"),
    )
    assert temu.abroad is True

    standing = rows[17]
    assert standing.transaction_date == date(2026, 9, 30)
    assert (standing.raw_merchant, standing.sector, standing.amount) == (
        'מוקד אמון - הו"ק',
        "מערכות ביט",
        Decimal("152.58"),
    )
    assert standing.standing_order is True

    fee = rows[19]
    assert fee.transaction_date == date(2026, 9, 6)
    assert (fee.raw_merchant, fee.sector, fee.amount) == ("דמי כרטיס", "שונות", Decimal("12.90"))

    for position, charge in rows.items():
        assert charge.abroad is (position == 15)
        assert charge.standing_order is (position == 17)
        if position != 1:
            assert charge.installment is None


def test_a_misread_total_fails_with_both_sums(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cal_parser, "_printed_total", lambda line: Decimal("5.00"))
    with pytest.raises(StatementError) as raised:
        CalStatementParser().parse(FIXTURE)
    assert str(raised.value) == ("its charges add up to 13986.22 but it prints a total of 5.00")


@pytest.mark.skipif(
    "CAL_REAL_STATEMENTS_DIR" not in os.environ, reason="CAL_REAL_STATEMENTS_DIR is not set"
)
def test_real_statements_when_present() -> None:
    folder = Path(os.environ["CAL_REAL_STATEMENTS_DIR"]).expanduser()
    october = CalStatementParser().parse(folder / "2026-10.pdf")
    assert (len(october.charges), october.printed_total) == (19, Decimal("13986.22"))

    september = CalStatementParser().parse(folder / "2026-09.pdf")
    assert september.billing_month == "2026-09"
    assert (len(september.charges), september.printed_total) == (17, Decimal("7333.36"))
    assert september.charges[0].installment == Installment(2, 3)


def test_a_pdf_without_pages_fails_readably(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    with empty.open("wb") as handle:
        PdfWriter().write(handle)
    with pytest.raises(StatementError, match="^it has no pages$"):
        CalStatementParser().parse(empty)


COLUMNS = columns_from_header(HEADER)


def row_words(top: float, day: str, merchant: str) -> list[Word]:
    return [
        Word(f"{day}/09/2026", 505.0, 538.3, top),
        Word(merchant, 440.0, 499.6, top),
        Word("77.00", 160.0, 181.9, top),
    ]


def read_rows(words: list[Word]) -> list[str]:
    """Each row's merchant and details cells, as the table reader builds them from the words."""
    rows: list[cal_parser._Row] = []
    for line in cal_parser._lines(words):
        if cells := cal_parser._cells(line, COLUMNS):
            cal_parser._read_line(cells, rows)
    return [f"{row.text('merchant')} | {row.text('details')}" for row in rows]


@pytest.mark.parametrize("offset", [1.3, -1.3])
def test_a_cell_drawn_slightly_off_its_row_stays_on_the_row(offset: float) -> None:
    words = [
        *row_words(100.0, "13", "ןושאר"),
        *row_words(109.7, "14", "ינש"),
        Word("טוריפ", 340.0, 380.3, 109.7 + offset),
    ]
    assert len(cal_parser._lines(words)) == 2
    assert read_rows(words) == ["ראשון | ", "שני | פירוט"]


def test_a_line_a_row_height_below_continues_the_row() -> None:
    words = [
        *row_words(100.0, "13", "ןושאר"),
        Word("טוריפ", 340.0, 380.3, 100.0),
        Word("ךשמה", 350.0, 380.3, 109.7),
    ]
    assert len(cal_parser._lines(words)) == 2
    assert read_rows(words) == ["ראשון | פירוט המשך"]


def test_an_amount_in_the_benefit_column_fails_naming_it() -> None:
    line = [*row_words(100.0, "13", "ןושאר"), Word("1,012.50", 80.0, 110.0, 100.0)]
    with pytest.raises(
        StatementError, match=r"^it has an amount in the benefit column: '1,012\.50'$"
    ):
        cal_parser._cells(line, COLUMNS)


@pytest.mark.parametrize("text", ["לסרפוש", "4U"])
def test_a_benefit_mark_or_side_panel_word_is_dropped(text: str) -> None:
    line = [*row_words(100.0, "13", "ןושאר"), Word(text, 64.0, 76.0, 100.0)]
    assert set(cal_parser._cells(line, COLUMNS)) == {"date", "merchant", "charged_amount"}
