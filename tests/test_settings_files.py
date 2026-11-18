"""Checks that the settings files document exactly the keys the agent and its compose stack read.

The settings live in three files under scripts/lib/: the committed stack-params.sh, and
params.example.sh and secrets.example.sh, which init-env.sh copies to the gitignored params.sh
and secrets.sh. A key counts as documented when a line of one of them assigns it, commented out
or not (export KEY="value" or # export KEY="value"). Unfilled copies of the examples must not
start the agent, and init-env.sh must create the gitignored files readable by their owner only.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from calagent.platform.config import SETTINGS_FILES, Settings

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "scripts" / "lib"
STACK_PARAMS = LIB / "stack-params.sh"
EXAMPLES = (LIB / "params.example.sh", LIB / "secrets.example.sh")
SCRIPTS = REPO / "scripts"

# Read by scripts/lib/ec2.sh only, for deploy.sh --ec2.
EC2_KEYS = {"EC2_STACK", "EC2_HOST_STACK", "EC2_ORIGIN_PORT", "EC2_INSTANCE_TYPE"}
# Read by docker-compose.yml only.
COMPOSE_ONLY_KEYS = {"EDGE_HOST_PORT"}
# Read by scripts/lib/settings-guard.sh only: the address tracked files may show.
GUARD_ONLY_KEYS = {"LICENSE_CONTACT"}
# The keys whose values are secrets, which only secrets.example.sh may document.
SECRET_KEYS = {"LLM_API_KEY"}

_ASSIGNMENT = re.compile(r"^(?:#\s*)?export ([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _keys_of(*paths: Path) -> set[str]:
    return set(_ASSIGNMENT.findall("".join(path.read_text(encoding="utf-8") for path in paths)))


def _settings_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _exported_by(*files: Path) -> dict[str, str]:
    """The variables a shell holds after sourcing the files in order, as the scripts do."""
    sources = "; ".join(f'source "{path}"' for path in files)
    output = subprocess.run(
        ["bash", "-c", f"{sources}; env -0"], check=True, capture_output=True, env={}
    ).stdout.decode()
    return dict(entry.split("=", 1) for entry in output.split("\0") if "=" in entry)


def test_the_settings_files_are_the_ones_the_agent_reads() -> None:
    assert [REPO / name for name in SETTINGS_FILES] == [
        STACK_PARAMS,
        LIB / "params.sh",
        LIB / "secrets.sh",
    ]


def test_every_setting_is_documented() -> None:
    missing = sorted(_settings_keys() - _keys_of(STACK_PARAMS, *EXAMPLES))
    assert not missing, f"Settings fields missing from the settings files: {missing}"


def test_no_documented_key_is_unknown() -> None:
    unknown = sorted(
        _keys_of(STACK_PARAMS, *EXAMPLES)
        - _settings_keys()
        - EC2_KEYS
        - GUARD_ONLY_KEYS
        - COMPOSE_ONLY_KEYS
    )
    assert not unknown, f"The settings files document keys nothing reads: {unknown}"


def test_secrets_are_documented_only_in_the_secrets_example() -> None:
    assert _keys_of(LIB / "secrets.example.sh") == SECRET_KEYS
    assert not _keys_of(STACK_PARAMS, LIB / "params.example.sh") & SECRET_KEYS


def test_unfilled_copies_do_not_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "statements").mkdir()
    for key, value in _exported_by(STACK_PARAMS, *EXAMPLES).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError, match="AUTH_CLIENT_ID is required"):
        Settings()  # type: ignore[call-arg]


def test_init_env_creates_owner_only_copies_of_the_examples(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    for script in ("common.sh", "init-env.sh"):
        shutil.copy(SCRIPTS / script, root / "scripts" / script)
    for path in (STACK_PARAMS, LIB / "settings-guard.sh", LIB / "ec2.sh"):
        shutil.copy(path, root / "scripts" / "lib" / path.name)
    examples = (*EXAMPLES, LIB / "aws-config.example.sh")
    for path in examples:
        shutil.copy(path, root / "scripts" / "lib" / path.name)
    subprocess.run([str(root / "scripts" / "init-env.sh")], check=True, capture_output=True)
    for example in examples:
        created = root / "scripts" / "lib" / example.name.replace(".example.sh", ".sh")
        assert created.read_bytes() == example.read_bytes(), created.name
        assert created.stat().st_mode & 0o077 == 0, created.name
