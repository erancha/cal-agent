import os
import shutil
from pathlib import Path

import pytest
from pypdf import PdfWriter

from calagent.adapters.pdf.cal_parser import CalStatementParser
from calagent.adapters.statements_folder import StatementsFolder
from calagent.domain.errors import StatementError, UploadRefused
from calagent.domain.statement import Statement

FIXTURE = Path(__file__).parents[1] / "statements" / "2026-10.pdf"
PERSON = "108123456789"


def zero_page_pdf(path: Path) -> Path:
    writer = PdfWriter()
    with path.open("wb") as handle:
        writer.write(handle)
    return path


class CountingParser:
    def __init__(self) -> None:
        self.calls = 0
        self._parser = CalStatementParser()

    def parse(self, path: Path) -> Statement:
        self.calls += 1
        return self._parser.parse(path)


@pytest.fixture
def parser() -> CountingParser:
    return CountingParser()


@pytest.fixture
def folder(tmp_path: Path, parser: CountingParser) -> StatementsFolder:
    return StatementsFolder(tmp_path, parser)


def put(folder: StatementsFolder, name: str, content: bytes | None = None) -> Path:
    directory = folder.root / PERSON
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if content is None:
        shutil.copy(FIXTURE, target)
    else:
        target.write_bytes(content)
    return target


def test_find_returns_the_file_covering_the_month(folder: StatementsFolder) -> None:
    put(folder, "2026-10.pdf")
    statement = folder.find(PERSON, "2026-10")
    assert statement is not None
    assert statement.billing_month == "2026-10"


def test_find_is_none_for_an_uncovered_month(folder: StatementsFolder) -> None:
    put(folder, "2026-10.pdf")
    assert folder.find(PERSON, "2026-09") is None


def test_find_is_none_for_a_person_without_a_folder(folder: StatementsFolder) -> None:
    assert folder.find(PERSON, "2026-10") is None
    assert folder.list(PERSON) == []


def test_a_file_is_indexed_by_its_content_not_its_name(folder: StatementsFolder) -> None:
    put(folder, "whatever.pdf")
    assert folder.find(PERSON, "2026-10") is not None


def test_two_files_for_one_month_fail_naming_both(folder: StatementsFolder) -> None:
    put(folder, "a.pdf")
    put(folder, "b.pdf")
    with pytest.raises(StatementError) as failure:
        folder.find(PERSON, "2026-10")
    assert str(failure.value) == "has 2 statements for 2026-10, a.pdf and b.pdf; keep one"


def test_a_download_name_disagreeing_with_the_content_fails(folder: StatementsFolder) -> None:
    put(folder, "2026-09.pdf")
    with pytest.raises(StatementError) as failure:
        folder.find(PERSON, "2026-10")
    assert str(failure.value) == (
        "could not use 2026-09.pdf: it is named for 2026-09 but holds 2026-10"
    )


def test_a_pdf_that_does_not_parse_fails_naming_it(folder: StatementsFolder) -> None:
    put(folder, "broken.pdf", b"%PDF-1.4 nothing")
    with pytest.raises(StatementError) as failure:
        folder.find(PERSON, "2026-10")
    assert str(failure.value).startswith("could not read broken.pdf: it is not a readable PDF")


def test_a_non_pdf_is_ignored_by_find_and_refused_by_store(folder: StatementsFolder) -> None:
    put(folder, "notes.txt", b"hello")
    assert folder.find(PERSON, "2026-10") is None
    assert [f.file_name for f in folder.list(PERSON)] == []
    with pytest.raises(UploadRefused, match="PDF"):
        folder.store(PERSON, b"hello")


def test_store_refuses_a_pdf_that_is_not_a_cal_statement(folder: StatementsFolder) -> None:
    with pytest.raises(UploadRefused):
        folder.store(PERSON, b"%PDF-1.4 nothing")
    assert folder.list(PERSON) == []


def test_store_names_the_file_after_its_month_and_refuses_a_second(
    folder: StatementsFolder,
) -> None:
    stored = folder.store(PERSON, FIXTURE.read_bytes())
    assert stored.file_name == "2026-10.pdf"
    assert stored.size_bytes == FIXTURE.stat().st_size
    assert folder.list(PERSON) == [stored]
    with pytest.raises(UploadRefused, match="2026-10"):
        folder.store(PERSON, FIXTURE.read_bytes())
    assert sorted(p.name for p in (folder.root / PERSON).iterdir()) == ["2026-10.pdf"]


def test_store_refuses_a_month_covered_by_a_differently_named_file(
    folder: StatementsFolder,
) -> None:
    put(folder, "whatever.pdf")
    with pytest.raises(UploadRefused, match="2026-10"):
        folder.store(PERSON, FIXTURE.read_bytes())


def test_delete_removes_a_listed_file_and_refuses_an_unknown_name(
    folder: StatementsFolder,
) -> None:
    folder.store(PERSON, FIXTURE.read_bytes())
    with pytest.raises(UploadRefused, match="2026-09.pdf"):
        folder.delete(PERSON, "2026-09.pdf")
    with pytest.raises(UploadRefused):
        folder.delete(PERSON, "../../etc/passwd")
    folder.delete(PERSON, "2026-10.pdf")
    assert folder.list(PERSON) == []


def test_a_file_is_parsed_again_only_when_it_changes(
    folder: StatementsFolder, parser: CountingParser
) -> None:
    target = put(folder, "2026-10.pdf")
    folder.find(PERSON, "2026-10")
    folder.find(PERSON, "2026-10")
    assert parser.calls == 1
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    folder.find(PERSON, "2026-10")
    assert parser.calls == 2


@pytest.mark.parametrize("person", ["", ".", "..", "a/b", "../x", "/abs", "a\\b", "x\0y", "a b"])
def test_a_person_that_is_not_a_single_safe_component_is_refused(
    folder: StatementsFolder, person: str
) -> None:
    for call in (
        lambda: folder.find(person, "2026-10"),
        lambda: folder.list(person),
        lambda: folder.store(person, FIXTURE.read_bytes()),
        lambda: folder.delete(person, "2026-10.pdf"),
    ):
        with pytest.raises(ValueError):
            call()


def test_store_names_an_unreadable_neighbour_instead_of_failing(folder: StatementsFolder) -> None:
    put(folder, "broken.pdf", b"%PDF-1.4 nothing")
    with pytest.raises(UploadRefused) as refused:
        folder.store(PERSON, FIXTURE.read_bytes())
    assert str(refused.value).startswith(
        "2026-10 cannot be checked while broken.pdf is unusable: it is not a readable PDF"
    )
    assert str(refused.value).endswith(". Fix or delete that file first")
    assert str(refused.value).count("broken.pdf") == 1


def test_store_names_a_neighbour_whose_name_disagrees_with_its_content(
    folder: StatementsFolder,
) -> None:
    put(folder, "2026-09.pdf")
    with pytest.raises(UploadRefused) as refused:
        folder.store(PERSON, FIXTURE.read_bytes())
    assert str(refused.value) == (
        "2026-10 cannot be checked while 2026-09.pdf is unusable: it is named for 2026-09 but "
        "holds 2026-10. Fix or delete that file first"
    )


def test_store_refuses_a_pdf_without_pages(folder: StatementsFolder, tmp_path: Path) -> None:
    with pytest.raises(UploadRefused, match="no pages"):
        folder.store(PERSON, zero_page_pdf(tmp_path / "empty.pdf").read_bytes())


def test_delete_refuses_a_file_another_replica_removed(
    folder: StatementsFolder, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = put(folder, "2026-10.pdf")
    original = Path.unlink

    def racing_unlink(self: Path, missing_ok: bool = False) -> None:
        original(self)
        original(self)

    monkeypatch.setattr(Path, "unlink", racing_unlink)
    with pytest.raises(UploadRefused, match="2026-10.pdf"):
        folder.delete(PERSON, target.name)
