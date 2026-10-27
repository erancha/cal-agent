from pathlib import Path

import pytest
import yaml

from calagent.adapters.callers_file import Caller, load_callers


def write(tmp_path: Path, callers: object) -> Path:
    path = tmp_path / "allowed-callers.yaml"
    path.write_text(yaml.safe_dump({"callers": callers}))
    return path


def entry(name: str = "hfm", secret: str = "s1", client_id: str = "c1") -> dict[str, str]:
    return {"name": name, "shared_secret": secret, "client_id": client_id}


def test_callers_are_keyed_by_their_secret(tmp_path: Path) -> None:
    path = write(tmp_path, [entry(), entry("other", "s2", "c2")])
    assert load_callers(path) == {
        "s1": Caller("hfm", "s1", "c1"),
        "s2": Caller("other", "s2", "c2"),
    }


def test_a_missing_file_names_the_script_that_writes_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="register-caller.sh"):
        load_callers(tmp_path / "absent.yaml")


def test_an_empty_list_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="registers no caller"):
        load_callers(write(tmp_path, []))


@pytest.mark.parametrize("field", ["name", "shared_secret", "client_id"])
def test_a_blank_field_is_refused(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValueError, match=f"blank {field}"):
        load_callers(write(tmp_path, [entry() | {field: "  "}]))


def test_two_callers_sharing_a_secret_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="hfm and other .* share a secret"):
        load_callers(write(tmp_path, [entry(), entry("other", client_id="c2")]))


def test_two_callers_sharing_a_name_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="share the name hfm"):
        load_callers(write(tmp_path, [entry(), entry(secret="s2", client_id="c2")]))


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"other": []}, "has no 'callers' list"),
        ({"callers": ["hfm"]}, "caller 1 in .* is not a mapping"),
        ({"callers": [{"name": "hfm", "client_id": "c"}]}, "caller 1 in .* has no shared_secret"),
    ],
)
def test_a_malformed_file_is_refused_naming_it(
    tmp_path: Path, document: object, message: str
) -> None:
    path = tmp_path / "allowed-callers.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises((ValueError, TypeError), match=message) as raised:
        load_callers(path)
    assert str(path) in str(raised.value)
