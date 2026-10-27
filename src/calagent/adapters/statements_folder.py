"""Each person's statements on disk: one folder per person, indexed by billing month.

- every lookup rescans the folder; a file is parsed again only when its size or mtime changed
- the month a file covers comes from its content; a download-style name must agree with it
- uploads are checked in a hidden temporary file, then linked under the month's own name, so an
  uploaded name never reaches the file system and a month is never overwritten
"""

import builtins
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from calagent.domain.errors import StatementError, UploadRefused
from calagent.domain.months import find_month
from calagent.domain.statement import Statement
from calagent.ports.statements import StatementParser, StoredFile

_PERSON = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PDF_MAGIC = b"%PDF-"
_SUFFIX = ".pdf"
_UPLOAD_PREFIX = ".upload-"

_Paths = builtins.list[Path]


class _UnusableFile(StatementError):
    def __init__(self, verb: str, file_name: str, reason: str) -> None:
        super().__init__(f"could not {verb} {file_name}: {reason}")
        self.file_name = file_name
        self.reason = reason


class StatementsFolder:
    def __init__(self, root: Path, parser: StatementParser) -> None:
        self.root = root
        self._parser = parser
        # Path -> (size, mtime_ns, statement) of the last parse
        self._parsed: dict[Path, tuple[int, int, Statement]] = {}

    def find(self, person: str, month: str) -> Statement | None:
        covering = self._covering(person, month)
        if len(covering) > 1:
            *others, last = (path.name for path, _ in covering)
            names = f"{', '.join(others)} and {last}"
            raise StatementError(f"has {len(covering)} statements for {month}, {names}; keep one")
        return covering[0][1] if covering else None

    def list(self, person: str) -> builtins.list[StoredFile]:
        return [self._stored(path) for path in self._pdfs(person)]

    def store(self, person: str, data: bytes) -> StoredFile:
        if not data.startswith(_PDF_MAGIC):
            raise UploadRefused("the file is not a PDF")
        directory = self._directory(person)
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=_UPLOAD_PREFIX, dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            try:
                month = self._parser.parse(temporary).billing_month
            except StatementError as failure:
                raise UploadRefused(f"the file could not be read as a Cal statement: {failure}")
            target = directory / f"{month}{_SUFFIX}"
            self._refuse_covered(person, month)
            try:
                os.link(temporary, target)
            except FileExistsError:
                raise UploadRefused(f"a statement for {month} is already stored")
        finally:
            temporary.unlink()
        return self._stored(target)

    def delete(self, person: str, file_name: str) -> None:
        for path in self._pdfs(person):
            if path.name == file_name:
                try:
                    path.unlink()
                except FileNotFoundError:
                    raise UploadRefused(f"there is no statement named {file_name}")
                self._parsed.pop(path, None)
                return
        raise UploadRefused(f"there is no statement named {file_name}")

    def _directory(self, person: str) -> Path:
        if _PERSON.fullmatch(person) is None:
            raise ValueError(f"person {person!r} is not a single safe path component")
        return self.root / person

    def _pdfs(self, person: str) -> _Paths:
        directory = self._directory(person)
        if not directory.is_dir():
            return []
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == _SUFFIX and not _is_upload(path)
        )

    def _statement(self, path: Path) -> Statement:
        stat = path.stat()
        cached = self._parsed.get(path)
        if cached is not None and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return cached[2]
        try:
            statement = self._parser.parse(path)
        except StatementError as failure:
            raise _UnusableFile("read", path.name, str(failure)) from failure
        self._parsed[path] = (stat.st_size, stat.st_mtime_ns, statement)
        return statement

    def _covering(self, person: str, month: str) -> builtins.list[tuple[Path, Statement]]:
        covering = []
        for path in self._pdfs(person):
            statement = self._statement(path)
            self._check_name(path, statement)
            if statement.billing_month == month:
                covering.append((path, statement))
        return covering

    def _refuse_covered(self, person: str, month: str) -> None:
        try:
            covering = self._covering(person, month)
        except _UnusableFile as failure:
            raise UploadRefused(
                f"{month} cannot be checked while {failure.file_name} is unusable: "
                f"{failure.reason}. Fix or delete that file first"
            ) from failure
        if covering:
            raise UploadRefused(f"{covering[0][0].name} already covers {month}")

    @staticmethod
    def _check_name(path: Path, statement: Statement) -> None:
        named = find_month(path.name)
        if named is not None and named != statement.billing_month:
            raise _UnusableFile(
                "use", path.name, f"it is named for {named} but holds {statement.billing_month}"
            )

    @staticmethod
    def _stored(path: Path) -> StoredFile:
        stat = path.stat()
        return StoredFile(
            path.name, stat.st_size, datetime.fromtimestamp(stat.st_mtime).astimezone()
        )


def _is_upload(path: Path) -> bool:
    return path.name.startswith(_UPLOAD_PREFIX)
