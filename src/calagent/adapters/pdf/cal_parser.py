"""Reads a Cal monthly statement PDF into a Statement whose charges add up to its printed total.

- the title's charge date fixes the billing month
- each page's charges table is read line by line from its header to the total line: a dated line
  starts a charge, an undated line continues the previous charge's cells
- every line between the header and the total must be one of those, or the parse fails
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page
from pdfplumber.utils.exceptions import PdfminerException

from calagent.adapters.pdf.words import (
    BENEFIT,
    Column,
    Word,
    column_of,
    columns_from_header,
    is_header,
    logical_text,
)
from calagent.domain.errors import StatementError
from calagent.domain.statement import Charge, Installment, Statement

_TITLE_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})-ל$")
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
_INSTALLMENT = re.compile(r"תשלום (\d+) מ - (\d+)")
_HEADER_SECOND_LINE = "העסקה הוצג העסקה חיוב"
_TOTAL_WORD = 'סה"כ'
_STANDING_ORDER = "הוראת קבע"
_CELLS = ("merchant", "sector", "details")
# Words whose tops lie this close to a line's first word sit on that line; table lines are about
# 10 pt apart, and a cell can be drawn a point or two off its row.
_LINE_TOLERANCE = 3.0

Line = list[Word]


@dataclass
class _Row:
    transaction_date: date
    charged: str
    # Key: cell name; value: the cell's words on each line it spans, top to bottom
    cells: dict[str, list[list[Word]]] = field(default_factory=lambda: defaultdict(list))

    def text(self, name: str) -> str:
        return " ".join(logical_text(words) for words in self.cells[name])


class CalStatementParser:
    def parse(self, path: Path) -> Statement:
        try:
            with pdfplumber.open(path) as pdf:
                pages = [_lines(_words(page)) for page in pdf.pages]
        except PdfminerException as failure:
            raise StatementError(f"it is not a readable PDF: {failure}") from failure
        if not pages:
            raise StatementError("it has no pages")
        charge_date = _charge_date(pages[0])
        rows, printed_total = _read_table(pages)
        charges = tuple(_charge(row) for row in rows)
        charged = sum((charge.amount for charge in charges), Decimal(0))
        if charged != printed_total:
            raise StatementError(
                f"its charges add up to {charged} but it prints a total of {printed_total}"
            )
        return Statement(
            billing_month=f"{charge_date.year:04d}-{charge_date.month:02d}",
            charge_date=charge_date,
            charges=charges,
            printed_total=printed_total,
        )


def _words(page: Page) -> list[Word]:
    return [Word(w["text"], w["x0"], w["x1"], w["top"]) for w in page.extract_words()]


def _lines(words: Iterable[Word]) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words, key=lambda word: word.top):
        if lines and word.top - lines[-1][0].top <= _LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _charge_date(lines: Sequence[Line]) -> date:
    found = [match for line in lines for word in line if (match := _TITLE_DATE.match(word.text))]
    if len(found) != 1:
        raise StatementError(f"it has {len(found)} charge dates in its title; expected one")
    day, month, year = (int(part) for part in found[0].groups())
    return date(2000 + year, month, day)


def _read_table(pages: Sequence[Sequence[Line]]) -> tuple[list[_Row], Decimal]:
    rows: list[_Row] = []
    for number, lines in enumerate(pages, start=1):
        columns, table = _table(lines, number)
        for line in table:
            if any(_logical(word) == _TOTAL_WORD for word in line):
                return rows, _printed_total(line)
            if cells := _cells(line, columns):
                _read_line(cells, rows)
    raise StatementError("it has no total line after its charges")


def _table(lines: Sequence[Line], page: int) -> tuple[list[Column], Iterator[Line]]:
    """The columns of the page's charges table and the lines after its two header lines."""
    starts = [index for index, line in enumerate(lines) if is_header(line)]
    if not starts:
        raise StatementError(f"it has no charges table header on page {page}")
    columns = columns_from_header(lines[starts[0]])
    table = iter(lines[starts[0] + 1 :])
    for line in table:
        if cells := _cells(line, columns):
            if _text(cells) != _HEADER_SECOND_LINE:
                raise StatementError(f"it has an unexpected charges table header: {_text(cells)!r}")
            return columns, table
    raise StatementError(f"it has no charges table under its header on page {page}")


def _cells(line: Line, columns: Sequence[Column]) -> dict[str, list[Word]]:
    """The line's words by column, without the benefit column's. An amount there was drawn out of
    its column, so it fails the parse rather than vanish from the month. Words of the page's side
    panel, drawn beside the table and some holding digits ("4U"), are dropped."""
    cells: dict[str, list[Word]] = defaultdict(list)
    for word in line:
        cells[column_of(word, columns).name].append(word)
    for word in cells.pop(BENEFIT, []):
        if _AMOUNT.match(word.text):
            raise StatementError(f"it has an amount in the benefit column: {word.text!r}")
    return cells


def _text(cells: dict[str, list[Word]]) -> str:
    return logical_text([word for words in cells.values() for word in words])


def _read_line(cells: dict[str, list[Word]], rows: list[_Row]) -> None:
    if "date" in cells:
        date_text = logical_text(cells["date"])
        if not _DATE.match(date_text) or "charged_amount" not in cells:
            raise StatementError(f"it has an unreadable charge line: {_text(cells)!r}")
        transaction_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        row = _Row(transaction_date, logical_text(cells["charged_amount"]))
        for name in _CELLS:
            if name in cells:
                row.cells[name].append(cells[name])
        rows.append(row)
        return
    if set(cells) - set(_CELLS):
        raise StatementError(f"it has a line with amounts but no date: {_text(cells)!r}")
    if not rows:
        raise StatementError(f"it has a continuation line before any charge: {_text(cells)!r}")
    for name, words in cells.items():
        rows[-1].cells[name].append(words)


def _printed_total(line: Line) -> Decimal:
    amounts = [word.text for word in line if _AMOUNT.match(word.text)]
    if len(amounts) != 1:
        raise StatementError(f"it has an unreadable total line: {logical_text(line)!r}")
    return Decimal(amounts[0].replace(",", ""))


def _amount(text: str) -> Decimal:
    number = text.replace("₪", "").strip()
    if not _AMOUNT.match(number):
        raise StatementError(f"it has an unreadable amount: {text!r}")
    return Decimal(number.replace(",", ""))


def _charge(row: _Row) -> Charge:
    details = row.text("details")
    installment = _INSTALLMENT.search(details)
    return Charge(
        transaction_date=row.transaction_date,
        raw_merchant=row.text("merchant"),
        sector=row.text("sector"),
        amount=_amount(row.charged),
        installment=Installment(int(installment[1]), int(installment[2])) if installment else None,
        standing_order=_STANDING_ORDER in details,
        abroad=details.split(" ", 1)[0].endswith("."),
    )


def _logical(word: Word) -> str:
    return logical_text([word])
