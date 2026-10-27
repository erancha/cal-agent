from pathlib import Path

import pytest
from pydantic import ValidationError

from calagent.platform.config import Settings

KEYS = [name.upper() for name in Settings.model_fields]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No setting from the shell, and a working directory holding the folders the tests name."""
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    for folder in ("statements", "s", "data"):
        (tmp_path / folder).mkdir()


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "statements_dir": Path("statements"),
        "llm_model": "keyword",
        "auth_client_id": "agent-client",
    }
    return Settings(**(values | overrides))  # type: ignore[arg-type]


def test_defaults_match_the_spec() -> None:
    sut = settings()
    assert sut.server_port == 8030
    assert sut.a2a_auth_required is True
    assert sut.a2a_callers_file == Path("allowed-callers.yaml")
    assert sut.categorizer_high_confidence == 0.85
    assert sut.categorizer_medium_confidence == 0.6
    assert sut.categorizer_batch_size == 40
    assert sut.tasks_ttl.days == 30
    assert sut.task_lease_seconds == 60
    assert sut.a2a_executor == "card"
    assert sut.advertised_url == "http://localhost:8030"


def test_the_advertised_url_is_the_agent_url_when_set() -> None:
    assert settings(agent_url="http://cal:9").advertised_url == "http://cal:9"


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATEMENTS_DIR", "data")
    monkeypatch.setenv("LLM_MODEL", "openai:gpt-5-mini")
    monkeypatch.setenv("AUTH_CLIENT_ID", "agent-client")
    monkeypatch.setenv("TASKS_TTL", "P2D")
    sut = Settings()  # type: ignore[call-arg]
    assert (sut.statements_dir, sut.llm_model, sut.tasks_ttl.days) == (
        Path("data"),
        "openai:gpt-5-mini",
        2,
    )


@pytest.mark.parametrize("missing", ["statements_dir", "llm_model"])
def test_a_missing_required_setting_is_named(missing: str) -> None:
    values = {"statements_dir": Path("s"), "llm_model": "keyword", "auth_client_id": "c"}
    del values[missing]
    with pytest.raises(ValidationError, match=missing):
        Settings(**values)  # type: ignore[arg-type]


def test_a_missing_client_id_is_refused_while_auth_is_on() -> None:
    with pytest.raises(ValidationError, match="AUTH_CLIENT_ID"):
        settings(auth_client_id=None)


def test_a_blank_client_id_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_CLIENT_ID", "")
    with pytest.raises(ValidationError, match="AUTH_CLIENT_ID"):
        Settings(statements_dir=Path("s"), llm_model="keyword")


def test_the_client_id_is_not_needed_while_auth_is_off() -> None:
    assert settings(auth_client_id=None, a2a_auth_required=False).auth_client_id is None


def test_the_tck_executor_forces_auth_off() -> None:
    sut = settings(auth_client_id=None, a2a_executor="tck")
    assert sut.a2a_auth_required is False


@pytest.mark.parametrize("missing", ["statements_dir", "auth_client_id"])
def test_a_startup_error_does_not_print_the_model_key(missing: str) -> None:
    values: dict[str, object] = {
        "statements_dir": Path("s"),
        "llm_model": "keyword",
        "auth_client_id": "c",
        "llm_api_key": "sk-SECRET123",
    }
    del values[missing]
    with pytest.raises(ValidationError) as raised:
        Settings(**values)  # type: ignore[arg-type]
    assert "sk-SECRET123" not in str(raised.value)


def test_the_tck_executor_refuses_a_shared_redis() -> None:
    with pytest.raises(ValidationError, match="A2A_EXECUTOR=tck.*TASKS_REDIS_URL"):
        settings(a2a_executor="tck", tasks_redis_url="redis://x", a2a_callers_file=Path("none"))


def test_the_tck_executor_refuses_an_existing_callers_file(tmp_path: Path) -> None:
    callers = tmp_path / "callers.yaml"
    callers.write_text("callers: []")
    with pytest.raises(ValidationError, match="A2A_EXECUTOR=tck.*A2A_CALLERS_FILE"):
        settings(a2a_executor="tck", a2a_callers_file=callers)


def test_a_negative_classifier_delay_is_refused() -> None:
    with pytest.raises(ValidationError, match="cal_test_slow_ms"):
        settings(cal_test_slow_ms=-1)


@pytest.mark.parametrize("folder", ["absent", "a-file"])
def test_a_statements_dir_that_is_not_a_directory_is_refused(folder: str) -> None:
    Path("a-file").write_text("")
    with pytest.raises(
        ValidationError, match=f"STATEMENTS_DIR={folder} is not an existing directory"
    ):
        settings(statements_dir=Path(folder))


@pytest.mark.parametrize("name", ["task_lease_seconds", "categorizer_batch_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_count_that_is_not_positive_is_refused(name: str, value: int) -> None:
    with pytest.raises(ValidationError, match=name):
        settings(**{name: value})


@pytest.mark.parametrize(("medium", "high"), [(-0.1, 0.85), (0.9, 0.85), (0.6, 1.1), (1.2, 1.3)])
def test_confidence_thresholds_out_of_order_or_range_are_refused(
    medium: float, high: float
) -> None:
    with pytest.raises(
        ValidationError,
        match="CATEGORIZER_MEDIUM_CONFIDENCE <= CATEGORIZER_HIGH_CONFIDENCE",
    ):
        settings(categorizer_medium_confidence=medium, categorizer_high_confidence=high)


def test_equal_confidence_thresholds_are_accepted() -> None:
    sut = settings(categorizer_medium_confidence=0.7, categorizer_high_confidence=0.7)
    assert (sut.categorizer_medium_confidence, sut.categorizer_high_confidence) == (0.7, 0.7)
