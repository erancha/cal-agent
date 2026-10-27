import importlib.util
import json
import os
import re
from pathlib import Path
from types import ModuleType

import pdfplumber

FIXTURE = Path(__file__).parents[1] / "statements" / "2026-10.pdf"

# Stand-ins the anonymizer drew in place of the holder's details, in logical order.
STAND_INS = [
    "שקד",
    "גפנים",
    "ארזים",
    "טוב",
    "42",
    "4802130",
    "802130",
    "12-345-0001234567",
    "1234",
    "4321",
    "100200",
    "123456789",
    "SPGNRC000001234",
    "SPGNRD000001234",
    "SPGNRH000001234",
    "PRD-000001",
    "PRD-000002",
    "1000001",
    "0001000001",
    "VS_10_20_30",
]

AMOUNT = re.compile(r"₪ ?[\d,]+\.\d\d")


def fixture_text() -> str:
    """The fixture's text, each page followed by its upward-running margin text.

    Extraction scatters the upward-running print ids among other words, so their characters are
    read on their own, bottom to top."""
    pages = []
    with pdfplumber.open(FIXTURE) as pdf:
        for page in pdf.pages:
            upward = sorted(
                (char for char in page.chars if abs(char["matrix"][0]) < 0.01),
                key=lambda char: -char["top"],
            )
            pages.append(page.extract_text() + "\n" + "".join(char["text"] for char in upward))
    return "\n".join(pages)


def appears(word: str, text: str) -> bool:
    """Whether word is in text, in logical order or, for Hebrew, in visual order.

    A word of four characters or more counts anywhere in text; a shorter one only standing alone,
    since it would otherwise match inside unrelated numbers."""
    hebrew = any("\u0590" <= ch <= "\u05ff" for ch in word)
    forms = {word, word[::-1]} if hebrew else {word}
    if len(word) >= 4 and any(form in text for form in forms):
        return True
    return any(re.search(rf"(?<![\w.,/]){re.escape(form)}(?![\w.,/])", text) for form in forms)


def load_anonymizer() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "anonymize-statement.py"
    spec = importlib.util.spec_from_file_location("anonymize_statement", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_holds_the_stand_ins_and_no_real_value() -> None:
    text = fixture_text()
    assert [word for word in STAND_INS if not appears(word, text)] == []
    # The real keys exist only on the machine holding the user's statements.
    real_dir = os.environ.get("CAL_REAL_STATEMENTS_DIR")
    if real_dir is not None:
        mapping = json.loads(
            (Path(real_dir) / "anonymize-2026-10.json").read_text(encoding="utf-8")
        )
        assert [word for key in mapping for word in key.split() if appears(word, text)] == []


def test_fixture_still_extracts_19_rows_and_the_total() -> None:
    text = fixture_text()
    rows = [line for line in text.splitlines() if len(AMOUNT.findall(line)) == 2]
    assert len(rows) == 19
    assert "13,986.22" in text


def test_leftover_check_finds_keys_without_the_word_matcher(monkeypatch) -> None:
    anonymizer = load_anonymizer()
    monkeypatch.setattr(anonymizer.PageText, "matches", lambda self, replacements: iter(()))
    # Stand-ins drawn one glyph at a time, glued to the next cell or reversed on a Hebrew line.
    keys = {"4321": "0000", "ארזים טוב 42": "אאאאא אאא 00", "12-345-0001234567": "0" * 17}
    assert anonymizer.remaining(str(FIXTURE), keys) == set(keys)
