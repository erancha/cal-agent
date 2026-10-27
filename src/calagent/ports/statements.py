"""The port that turns a statement file into a Statement."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from calagent.domain.statement import Statement


class StatementParser(Protocol):
    def parse(self, path: Path) -> Statement: ...


@dataclass(frozen=True)
class StoredFile:
    file_name: str
    size_bytes: int
    modified: datetime


class StatementSource(Protocol):
    """Each person's uploaded statements, indexed by the billing month their content declares."""

    def find(self, person: str, month: str) -> Statement | None: ...

    def list(self, person: str) -> list[StoredFile]: ...

    def store(self, person: str, data: bytes) -> StoredFile: ...

    def delete(self, person: str, file_name: str) -> None: ...
