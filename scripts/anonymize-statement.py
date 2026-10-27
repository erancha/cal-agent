#!/usr/bin/env python3
"""Writes a copy of a Cal statement PDF with private text replaced, for use as a test fixture.

The statement's one subset font draws two-byte codes that are glyph indices; the font's ToUnicode
map gives each glyph its character. Text is drawn sometimes a whole string per text-showing
operation, in visual order (Hebrew reversed), and sometimes one glyph per operation, in drawing
order: right to left on a Hebrew line, so a number there comes out reversed. A page's drawn text,
concatenated across operations, is searched for each key's visual form and its reverse, bounded by
non-letters, a word break (a new line, or a gap between glyphs on one line) or the edge of a
whole-string operation. Each matched character is redrawn as the stand-in's character at the same
position, encoded through the inverse of the ToUnicode map, with the character spacing of its
operation adjusted so the operation spans the same width and text extraction still sees the
original columns and word gaps. Any signature field is dropped, since a rewritten file no longer
matches it.

The replacements file maps private words to stand-ins in logical order, e.g. {"1258": "1234"}; a
stand-in has the key's length and spaces. It holds the private values, so it stays outside the
repo. The run fails when a key is never found, when a stand-in needs a character the embedded
font subset lacks, or when any key still appears in the written file.

Usage: scripts/anonymize-statement.py <in.pdf> <out.pdf> <replacements.json>
Requires pypdf.
"""

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ByteStringObject, ContentStream, FloatObject, NameObject

# The text state a string is drawn with; q/Q save and restore it with the graphics state.
DEFAULT_STATE = {"font": None, "size": 0.0, "tc": 0.0, "tz": 100.0}

HEX = r"<([0-9A-Fa-f]+)>"
BFRANGE = re.compile(rf"{HEX}\s*{HEX}\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)")
BFCHAR = re.compile(rf"{HEX}\s*{HEX}")

# A left-to-right run inside Hebrew text: digits and Latin letters, joined by separators that
# keep the run together (12-345-0001234567, 02/10/26).
LTR_RUN = re.compile(r"[0-9A-Za-z]+(?:[-/.,:_][0-9A-Za-z]+)*")

# Stands between two words of a page's drawn text, so no key matches across them.
WORD_BREAK = "\n"

# A gap between two glyphs on one line, as a fraction of the font size, that separates words.
WORD_GAP = 0.2


def utf16(hex_text: str) -> str:
    return bytes.fromhex(hex_text).decode("utf-16-be")


class Glyphs:
    """A Type0 font's glyph codes, the characters its ToUnicode map gives them, and their widths.

    The subset merges one subset per face, so one character may have several codes, of different
    widths. A stand-in character takes the code whose width is closest to the glyph it replaces,
    so a glyph placed on its own still fits its slot and extraction keeps the word together."""

    def __init__(self, font):
        cmap = font["/ToUnicode"].get_object().get_data().decode("latin-1")
        self.chars: dict[int, str] = {}
        for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.DOTALL):
            for lo, hi, target in BFRANGE.findall(block):
                first, last = int(lo, 16), int(hi, 16)
                if target.startswith("["):
                    for offset, char in enumerate(re.findall(HEX, target)):
                        self.chars[first + offset] = utf16(char)
                else:
                    start = int(target.strip("<>"), 16)
                    for code in range(first, last + 1):
                        self.chars[code] = chr(start + code - first)
        for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.DOTALL):
            for code, char in BFCHAR.findall(block):
                self.chars[int(code, 16)] = utf16(char)
        self.codes: dict[str, list[int]] = {}
        for code in sorted(self.chars):
            self.codes.setdefault(self.chars[code], []).append(code)
        self.widths, self.default_width = widths(font)

    def decode(self, data: bytes) -> str:
        return "".join(self.chars[int.from_bytes(data[i : i + 2])] for i in range(0, len(data), 2))

    def width(self, code: int) -> float:
        return self.widths.get(code, self.default_width)

    def encode(self, text: str, replacing: bytes) -> bytes:
        """Codes drawing text in place of the same-length codes in replacing."""
        missing = sorted({ch for ch in text if ch not in self.codes})
        if missing:
            sys.exit(f"stand-in text {text!r} needs characters the font subset lacks: {missing}")
        old = [int.from_bytes(replacing[i : i + 2]) for i in range(0, len(replacing), 2)]
        return b"".join(
            min(
                self.codes[ch],
                key=lambda code: (abs(self.width(code) - self.width(was)), abs(code - was)),
            ).to_bytes(2)
            for ch, was in zip(text, old, strict=True)
        )

    def span(self, data: bytes, size: float) -> float:
        """The drawn width of the codes in data at the font size, before spacing and scaling."""
        return (
            sum(self.width(int.from_bytes(data[i : i + 2])) for i in range(0, len(data), 2))
            / 1000
            * size
        )


def widths(font) -> tuple[dict[int, float], float]:
    """Glyph index to width in 1/1000 text-space units, from the descendant font's W array."""
    cid_font = font["/DescendantFonts"][0].get_object()
    table: dict[int, float] = {}
    w = cid_font["/W"].get_object()
    i = 0
    while i < len(w):
        first = int(w[i])
        if isinstance(w[i + 1].get_object(), list):
            for offset, width in enumerate(w[i + 1].get_object()):
                table[first + offset] = float(width)
            i += 2
        else:
            for cid in range(first, int(w[i + 1]) + 1):
                table[cid] = float(w[i + 2])
            i += 3
    return table, float(cid_font.get("/DW", 1000))


def visual(logical: str) -> str:
    """The left-to-right order a Hebrew line shows text in; text without Hebrew is unchanged."""
    if not any("\u0590" <= ch <= "\u05ff" for ch in logical):
        return logical
    return LTR_RUN.sub(lambda run: run.group()[::-1], logical[::-1])


def drawn_forms(old: str, new: str) -> list[tuple[str, str]]:
    """Each order a key may be drawn in, paired with the stand-in in the same order."""
    shown_old, shown_new = visual(old), visual(new)
    return list({shown_old: shown_new, shown_old[::-1]: shown_new[::-1]}.items())


@dataclass
class Shown:
    """One text-showing operation: where it sits, what it draws and the state it draws with."""

    op: int
    start: int
    data: bytes
    text: str
    font: Glyphs
    size: float
    tc: float


class PageText:
    """A page's drawn text, concatenated in drawing order, with the operation of every character.

    owners maps a position in text to an index into shows, or None at a word break: a new line or
    text object, or a gap wider than WORD_GAP between two consecutive glyphs on one line, as
    between table cells drawn one glyph at a time."""

    def __init__(self, page, pdf):
        fonts = {
            name: Glyphs(ref.get_object()) for name, ref in page["/Resources"]["/Font"].items()
        }
        self.content = ContentStream(page.get_contents(), pdf)
        self.shows: list[Shown] = []
        self.owners: list[int | None] = []
        parts: list[str] = []
        state, saved = dict(DEFAULT_STATE), []
        # Horizontal text-space positions on the current line: where it starts, where the next
        # glyph is drawn, and the extent of the last string drawn on it.
        line_x = pen = 0.0
        last: tuple[float, float] | None = None

        def word_break() -> None:
            nonlocal last
            self.owners.append(None)
            parts.append(WORD_BREAK)
            last = None

        for index, (operands, op) in enumerate(self.content.operations):
            if op == b"q":
                saved.append(dict(state))
            elif op == b"Q":
                state = saved.pop()
            elif op == b"Tf":
                state["font"], state["size"] = fonts[operands[0]], float(operands[1])
            elif op == b"Tc":
                state["tc"] = float(operands[0])
            elif op == b"Tz":
                state["tz"] = float(operands[0])
            elif op in (b"BT", b"ET", b"Tm"):
                word_break()
                line_x = pen = 0.0
            elif op == b"T*":
                word_break()
                pen = line_x
            elif op in (b"Td", b"TD"):
                if float(operands[1]):
                    word_break()
                line_x += float(operands[0])
                pen = line_x
            elif op == b"Tj":
                data = bytes(operands[0].original_bytes)
                font, size = state["font"], state["size"]
                text = font.decode(data)
                advance = (font.span(data, size) + len(text) * state["tc"]) * state["tz"] / 100
                x0, x1 = sorted((pen, pen + advance))
                if last is not None and max(x0 - last[1], last[0] - x1) > WORD_GAP * size:
                    word_break()
                last = (x0, x1)
                pen += advance
                self.shows.append(
                    Shown(index, len(self.owners), data, text, font, size, state["tc"])
                )
                self.owners.extend([len(self.shows) - 1] * len(text))
                parts.append(text)
        self.text = "".join(parts)

    def bounded(self, inner: int, outer: int) -> bool:
        """Whether the character at outer may sit next to a key's edge character at inner."""
        if outer < 0 or outer >= len(self.text) or not self.text[outer].isalnum():
            return True
        a, b = self.owners[inner], self.owners[outer]
        return a != b and (len(self.shows[a].text) > 1 or len(self.shows[b].text) > 1)

    def matches(self, replacements: dict[str, str]):
        """Yields each key found, with the position of every character and its stand-in."""
        for old, new in replacements.items():
            for form_old, form_new in drawn_forms(old, new):
                pattern = " +".join(re.escape(word) for word in form_old.split())
                for found in re.finditer(pattern, self.text):
                    start, end = found.span()
                    if self.bounded(start, start - 1) and self.bounded(end - 1, end):
                        positions = [i for i in range(start, end) if self.text[i] != " "]
                        yield old, zip(positions, form_new.replace(" ", ""), strict=True)


def check_shapes(replacements: dict[str, str]) -> None:
    for old, new in replacements.items():
        if [len(word) for word in old.split(" ")] != [len(word) for word in new.split(" ")]:
            sys.exit(f"stand-in {new!r} does not have the length and spaces of its key")


def redraw(show: Shown, edits: dict[int, str]) -> list:
    """The operations drawing show's text with edits applied, spanning the original width."""
    new = "".join(edits.get(show.start + i, ch) for i, ch in enumerate(show.text))
    encoded = show.font.encode(new, show.data)
    old_span = show.font.span(show.data, show.size) + len(show.text) * show.tc
    tc = (old_span - show.font.span(encoded, show.size)) / len(new)
    return [
        ([FloatObject(round(tc, 4))], b"Tc"),
        ([ByteStringObject(encoded)], b"Tj"),
        ([FloatObject(show.tc)], b"Tc"),
    ]


def rewrite_page(page, writer, replacements: dict[str, str], found: Counter) -> None:
    drawn = PageText(page, writer)
    edits: dict[int, str] = {}
    for old, chars in drawn.matches(replacements):
        found[old] += 1
        for position, char in chars:
            if edits.setdefault(position, char) != char:
                sys.exit(f"two keys overlap at {drawn.text[position - 5 : position + 5]!r}")
    redrawn = {
        drawn.shows[owner].op: redraw(drawn.shows[owner], edits)
        for owner in {drawn.owners[position] for position in edits}
    }
    operations = []
    for index, operation in enumerate(drawn.content.operations):
        operations.extend(redrawn.get(index, [operation]))
    drawn.content.operations = operations
    page[NameObject("/Contents")] = writer._add_object(drawn.content)
    page.compress_content_streams()


def drop_signature(writer):
    root = writer._root_object
    if "/AcroForm" in root:
        del root["/AcroForm"]
    for page in writer.pages:
        annots = page.get("/Annots")
        if annots is not None:
            kept = [a for a in annots if a.get_object().get("/FT") != "/Sig"]
            page[NameObject("/Annots")] = type(annots)(kept)


def remaining(path: str, replacements: dict[str, str]) -> set[str]:
    """Keys the written file still draws, or still holds in any object other than page content.

    Drawn text is searched twice: by the matcher, and, for keys of four characters or more, as
    plain substrings of each page's drawn text with whitespace removed, in logical, visual and
    reversed form, so a key the matcher's word boundaries miss still fails the run. Shorter keys
    would match unrelated numbers. The outside-text search looks for the logical and visual forms
    only, since no object outside page content draws in reverse; it skips page content, whose
    text is glyph codes and whose hex strings and numbers would match digits."""
    reader = PdfReader(path)
    pages = [PageText(page, reader) for page in reader.pages]
    left = {old for page in pages for old, _ in page.matches(replacements)}
    long_keys = [key for key in replacements if len(key) >= 4]
    for page in pages:
        compact = re.sub(r"\s", "", page.text)
        for old in long_keys:
            forms = {re.sub(r"\s", "", form) for form in (old, visual(old), visual(old)[::-1])}
            if any(form in compact for form in forms):
                left.add(old)
    contents = {page.raw_get("/Contents").idnum for page in reader.pages}
    numbers = {num for entries in reader.xref.values() for num in entries} | set(reader.xref_objStm)
    other = b"".join(
        obj.get_data() if hasattr(obj, "get_data") else repr(obj).encode("utf-8")
        for num in sorted(numbers - contents)
        if (obj := reader.get_object(num)) is not None
    )
    for old in long_keys:
        for form in {old, visual(old)}:
            if any(form.encode(enc) in other for enc in ("utf-16-be", "utf-8")):
                left.add(old)
    return left


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__.strip().splitlines()[-2], file=sys.stderr)
        return 2
    source, target, mapping = sys.argv[1:]
    with open(mapping, encoding="utf-8") as f:
        replacements: dict[str, str] = json.load(f)
    check_shapes(replacements)
    writer = PdfWriter(clone_from=PdfReader(source))
    found: Counter = Counter()
    for page in writer.pages:
        rewrite_page(page, writer, replacements, found)
    drop_signature(writer)
    writer.add_metadata({"/Producer": "anonymize-statement.py"})
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    # A fresh file identifier, so the fixture does not carry the original statement's.
    writer._ID = None
    writer.generate_file_identifiers()
    with open(target, "wb") as f:
        writer.write(f)
    missing = set(replacements) - set(found)
    if missing:
        sys.exit(f"never found: {sorted(missing)}")
    left = remaining(target, replacements)
    if left:
        sys.exit(f"still present in {target}: {sorted(left)}")
    print(f"wrote {target}; replaced {found.total()} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
