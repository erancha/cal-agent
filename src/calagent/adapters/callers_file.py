"""Reads the registry of A2A callers that register-caller.sh writes.

The file holds a callers list of {name, shared_secret, client_id} entries; callers are looked up
by the secret they present. Names are unique because task ownership is keyed on them.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

FIELDS = ("name", "shared_secret", "client_id")


@dataclass(frozen=True)
class Caller:
    name: str
    shared_secret: str
    client_id: str


def load_callers(path: Path) -> dict[str, Caller]:
    if not path.is_file():
        raise FileNotFoundError(
            f"the callers file {path} does not exist; register a caller with "
            "./scripts/register-caller.sh"
        )
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, dict) or "callers" not in document:
        raise ValueError(f"the callers file {path} has no 'callers' list")
    entries = document["callers"]
    if not entries:
        raise ValueError(f"the callers file {path} registers no caller")
    callers: dict[str, Caller] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise TypeError(f"caller {position} in {path} is not a mapping of its fields")
        for field in FIELDS:
            if field not in entry:
                raise ValueError(f"caller {position} in {path} has no {field}")
            value = entry[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"caller {position} in {path} has a blank {field}")
        caller = Caller(entry["name"], entry["shared_secret"], entry["client_id"])
        if any(known.name == caller.name for known in callers.values()):
            raise ValueError(f"two callers in {path} share the name {caller.name}")
        if caller.shared_secret in callers:
            other = callers[caller.shared_secret].name
            raise ValueError(f"callers {other} and {caller.name} in {path} share a secret")
        callers[caller.shared_secret] = caller
    return callers
