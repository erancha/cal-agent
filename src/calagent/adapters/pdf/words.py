"""Words of a right-to-left PDF table: their logical reading order and the column each sits under.

- Word: one extracted word with its position on the page
- logical_text: reads words extracted in visual order back into logical Hebrew
- is_header, columns_from_header, column_of: right-aligned columns fixed by the header line's
  words
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from calagent.domain.errors import StatementError

_HEBREW = re.compile("[֐-׿]")
_LATIN = re.compile("[A-Za-z]")
# A number or Latin token inside a Hebrew word, such as the date in "ל-02/10/2026".
_LEFT_TO_RIGHT_RUN = re.compile(r"[0-9A-Za-z]+(?:[./,:-][0-9A-Za-z]+)*")

# The far-left column of Shufersal-benefit marks, read and dropped.
BENEFIT = "benefit"

# Words sit up to this far past their column's right edge.
_EDGE_TOLERANCE = 2.0

# Logical header words of each column, right to left.
_HEADER = (
    ("date", ("תאריך",)),
    ("merchant", ("שם", "בית", "העסק")),
    ("sector", ("ענף",)),
    ("details", ("פירוט",)),
    ("presented", ("כרטיס",)),
    ("transaction_amount", ("סכום",)),
    ("charged_amount", ("סכום",)),
)
_HEADER_WORDS = [text for _, texts in _HEADER for text in texts]


@dataclass(frozen=True)
class Word:
    """Text as extracted (Hebrew letters in visual order) and its box on the page."""

    text: str
    x0: float
    x1: float
    top: float


@dataclass(frozen=True)
class Column:
    """A right-aligned column: it holds the words ending at or left of its right edge and right of
    the right edge of the column to its left."""

    name: str
    right: float


def _logical_word(text: str) -> str:
    if not _HEBREW.search(text):
        return text
    return _LEFT_TO_RIGHT_RUN.sub(lambda run: run[0][::-1], text[::-1])


def _is_latin(text: str) -> bool:
    return bool(_LATIN.search(text)) and not _HEBREW.search(text)


def logical_text(words: Sequence[Word]) -> str:
    """Words taken right to left, Hebrew words reversed; a run of Latin-letter words keeps its
    left-to-right order, as in "Google Pay"."""
    ordered = sorted(words, key=lambda word: word.x0, reverse=True)
    texts: list[str] = []
    latin_run: list[str] = []
    for word in ordered:
        if _is_latin(word.text):
            latin_run.insert(0, word.text)
            continue
        texts.extend(latin_run)
        latin_run = []
        texts.append(_logical_word(word.text))
    texts.extend(latin_run)
    return " ".join(texts)


def _split_header(line: Sequence[Word]) -> tuple[list[Word], list[Word]]:
    """The line's rightmost words, as many as the header has, and the words left of them."""
    ordered = sorted(line, key=lambda word: word.x1, reverse=True)
    return ordered[: len(_HEADER_WORDS)], ordered[len(_HEADER_WORDS) :]


def _logical_words(words: Sequence[Word]) -> list[str]:
    return [_logical_word(word.text) for word in words]


def is_header(line: Sequence[Word]) -> bool:
    """Whether the line opens with the charges table's header words, read from the right."""
    return _logical_words(_split_header(line)[0]) == _HEADER_WORDS


def columns_from_header(line: Sequence[Word]) -> list[Column]:
    """The table's columns, right to left, each at the right edge of its rightmost header word.

    The last column, benefit, holds the far-left Shufersal-benefit marks; it is taken as wide as
    the transaction-amount column, so the charged-amount column ends where it begins. The page
    has a side panel drawn beside the header line, so words left of the header's own must fall in
    the benefit column.
    """
    header, beside = _split_header(line)
    found = _logical_words(header)
    if found != _HEADER_WORDS:
        raise StatementError(f"it has an unexpected charges table header: {' '.join(found)!r}")
    columns: list[Column] = []
    position = 0
    for name, texts in _HEADER:
        columns.append(Column(name, header[position].x1))
        position += len(texts)
    amount_width = columns[-2].right - columns[-1].right
    columns.append(Column(BENEFIT, columns[-1].right - amount_width))
    if any(column_of(word, columns).name != BENEFIT for word in beside):
        raise StatementError(f"it has an unexpected charges table header: {logical_text(line)!r}")
    return columns


def _column_at(x: float, columns: Sequence[Column]) -> Column:
    reach = x - _EDGE_TOLERANCE
    under = [column for column in columns if column.right >= reach]
    if not under:
        raise StatementError(f"it has a word right of the charges table at x={x:.1f}")
    return min(under, key=lambda column: column.right)


def column_of(word: Word, columns: Sequence[Column]) -> Column:
    column = _column_at(word.x1, columns)
    if _column_at(word.x0, columns) != column:
        raise StatementError(
            f"it has a word reaching across two columns: {_logical_word(word.text)!r}"
        )
    return column
