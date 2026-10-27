"""The agent's settings: environment variables read once at startup.

Nothing here reads a .env file; the scripts load it. A blank variable counts as unset. Every
key is explained once, in .env.example.
"""

from datetime import timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from calagent.adapters.google_tokens import GOOGLE_ISSUER, GOOGLE_JWKS_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    server_port: int = 8030
    agent_url: str | None = None
    statements_dir: Path
    static_dir: Path = Path("static")
    a2a_auth_required: bool = True
    auth_client_id: str | None = None
    a2a_callers_file: Path = Path("allowed-callers.yaml")
    auth_issuer: str = GOOGLE_ISSUER
    auth_jwks_url: str = GOOGLE_JWKS_URL
    auth_public_key_file: Path | None = None
    llm_model: str
    llm_api_key: str | None = None
    categorizer_high_confidence: float = 0.85
    categorizer_medium_confidence: float = 0.6
    categorizer_batch_size: int = Field(default=40, gt=0)
    tasks_redis_url: str | None = None
    tasks_ttl: timedelta = timedelta(days=30)
    task_lease_seconds: int = Field(default=60, gt=0)
    a2a_executor: Literal["card", "tck"] = "card"
    cal_test_slow_ms: int = Field(default=0, ge=0)
    log_level: str = "INFO"
    a2a_log_level: str = "WARNING"

    @property
    def advertised_url(self) -> str:
        if self.agent_url is not None:
            return self.agent_url
        return f"http://localhost:{self.server_port}"

    @model_validator(mode="after")
    def _require_statements_dir(self) -> Self:
        if not self.statements_dir.is_dir():
            raise ValueError(f"STATEMENTS_DIR={self.statements_dir} is not an existing directory")
        return self

    @model_validator(mode="after")
    def _order_confidence_thresholds(self) -> Self:
        medium, high = self.categorizer_medium_confidence, self.categorizer_high_confidence
        if not 0 <= medium <= high <= 1:
            raise ValueError(
                "expected 0 <= CATEGORIZER_MEDIUM_CONFIDENCE <= CATEGORIZER_HIGH_CONFIDENCE <= 1, "
                f"got {medium} and {high}"
            )
        return self

    @model_validator(mode="after")
    def _resolve_access(self) -> Self:
        if self.a2a_executor == "tck":
            self._refuse_tck_beside_real_callers()
            self.a2a_auth_required = False
        if self.a2a_auth_required and self.auth_client_id is None:
            raise ValueError("AUTH_CLIENT_ID is required while A2A_AUTH_REQUIRED is true")
        return self

    def _refuse_tck_beside_real_callers(self) -> None:
        """The conformance executor serves every request unauthenticated, so it only runs in a
        single in-memory process with no callers registered."""
        if self.tasks_redis_url is not None:
            raise ValueError(
                "A2A_EXECUTOR=tck cannot run with TASKS_REDIS_URL set: "
                "a conformance run is one in-memory process"
            )
        if self.a2a_callers_file.is_file():
            raise ValueError(
                f"A2A_EXECUTOR=tck cannot run while A2A_CALLERS_FILE={self.a2a_callers_file} "
                "exists: it would serve a registered agent's callers without authentication"
            )
