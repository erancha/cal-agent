import pytest

from calagent.adapters.pdf.words import (
    Column,
    Word,
    column_of,
    columns_from_header,
    is_header,
    logical_text,
)
from calagent.domain.errors import StatementError

# The header line of a Cal charges table as extracted: visual order, word positions of the fixture.
HEADER = [
    Word("ךיראת", 518.3, 538.3, 341),
    Word("םש", 488.9, 499.6, 341),
    Word("תיב", 474.7, 486.7, 341),
    Word("קסעה", 453.6, 472.4, 341),
    Word("ףנע", 404.1, 416.2, 341),
    Word("טוריפ", 362.9, 380.3, 341),
    Word("סיטרכ", 255.4, 275.3, 341),
    Word("םוכס", 230.8, 246.5, 341),
    Word("םוכס", 166.2, 181.9, 341),
]


def test_hebrew_words_are_reversed_and_read_right_to_left() -> None:
    words = [Word("ןייל", 457, 466, 0), Word("ןוא", 468, 475, 0), Word("לסרפוש", 478, 500, 0)]
    assert logical_text(words) == "שופרסל און ליין"


def test_latin_words_keep_their_order() -> None:
    words = [
        Word("4321", 302, 316, 0),
        Word("Google", 318, 337, 0),
        Word("Pay", 339, 348, 0),
        Word("סיטרכ", 350, 365, 0),
        Word("ההזמ", 367, 380, 0),
    ]
    assert logical_text(words) == "מזהה כרטיס Google Pay 4321"


def test_header_gives_each_column_the_right_edge_of_its_rightmost_word() -> None:
    columns = columns_from_header(HEADER)
    assert [(c.name, c.right) for c in columns[:7]] == [
        ("date", 538.3),
        ("merchant", 499.6),
        ("sector", 416.2),
        ("details", 380.3),
        ("presented", 275.3),
        ("transaction_amount", 246.5),
        ("charged_amount", 181.9),
    ]
    assert columns[7].name == "benefit"


def test_a_word_belongs_to_the_column_whose_edge_it_ends_at() -> None:
    columns = columns_from_header(HEADER)
    assert column_of(Word("4321", 293.9, 307.3, 0), columns) == Column("details", 380.3)
    assert column_of(Word("לסרפוש", 28.7, 93.2, 0), columns).name == "benefit"


def test_a_word_reaching_across_two_columns_fails() -> None:
    with pytest.raises(StatementError, match="^it has a word reaching across two columns: "):
        column_of(Word("ןוזמ", 400.0, 430.0, 0), columns_from_header(HEADER))


def test_an_unexpected_header_fails() -> None:
    with pytest.raises(StatementError, match="header"):
        columns_from_header(HEADER[:-1])


def test_a_side_panel_word_beside_the_header_is_not_part_of_it() -> None:
    line = [*HEADER, Word("לסרפוש", 28.7, 93.2, 340)]
    assert is_header(line)
    assert columns_from_header(line) == columns_from_header(HEADER)


def test_a_word_beside_the_header_inside_the_table_fails() -> None:
    line = [*HEADER, Word("רחא", 150.0, 160.0, 341)]
    assert is_header(line)
    with pytest.raises(StatementError, match="^it has an unexpected charges table header: "):
        columns_from_header(line)
