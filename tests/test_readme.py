"""Checks that the README and the docs link only to headings and files that exist.

GitHub builds a heading's in-page anchor from its text (lowercase, no punctuation, spaces to
hyphens); these tests apply the same rule and fail on a link no heading produces.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES_WITH_CONTENTS = ["README.md", "docs/a2a-contract.md", "docs/testing.md"]

_CONTENTS_LINK = re.compile(r"\[[^\]]+\]\(#([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
# A relative link: a path that is neither a URL nor an in-page anchor, with an optional anchor.
_RELATIVE_LINK = re.compile(r"\]\((?!https?://|#)([^)#\s]+)(?:#([^)\s]+))?\)")


def _heading_target(heading_text: str) -> str:
    target = heading_text.strip().lower()
    target = re.sub(r"[^\w\s-]", "", target)
    return target.replace(" ", "-")


def _targets(page: Path) -> set[str]:
    return {_heading_target(h) for h in _HEADING.findall(page.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("page", PAGES_WITH_CONTENTS)
def test_every_contents_link_reaches_a_heading(page: str) -> None:
    path = ROOT / page
    linked = _CONTENTS_LINK.findall(path.read_text(encoding="utf-8"))

    assert linked, f"expected {page} to have a Contents list with in-page links"
    missing = sorted(target for target in linked if target not in _targets(path))
    assert not missing, f"{page} links to headings that do not exist: {missing}"


def test_every_relative_link_reaches_a_file_and_its_heading() -> None:
    pages = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    broken = []
    for page in pages:
        for link, anchor in _RELATIVE_LINK.findall(page.read_text(encoding="utf-8")):
            target = (page.parent / link).resolve()
            if not target.exists():
                broken.append(f"{page.relative_to(ROOT)} -> {link}")
            elif anchor and anchor not in _targets(target):
                broken.append(f"{page.relative_to(ROOT)} -> {link}#{anchor}")
    assert not broken, f"links to missing files or headings: {broken}"
