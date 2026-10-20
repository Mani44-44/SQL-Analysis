"""Typed application settings, loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "AskData"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- storage ---
    database_url: str = f"sqlite:///{(REPO_DIR / 'data' / 'app.sqlite').as_posix()}"
    data_dir: Path = REPO_DIR / "data"

    # --- auth ---
    jwt_secret: SecretStr = SecretStr("dev-insecure-placeholder-change-me-before-deploying")
    jwt_ttl_hours: int = 24 * 7
    cookie_secure: bool = False
    # "none" (with cookie_secure) when the frontend and API are on different sites.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # --- llm ---
    llm_provider: Literal["auto", "anthropic", "mock"] = "auto"
    anthropic_api_key: SecretStr | None = None
    llm_model_strong: str = "claude-opus-5-5"
    llm_model_fast: str = "claude-haiku-5-5"
    llm_effort_strong: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_effort_fast: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_max_tokens: int = 16000
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 2

    # --- ingestion ---
    max_upload_mb: int = 50
    max_upload_rows: int = 1_000_000
    date_parse_threshold: float = 0.95

    # --- query safety / execution ---
    query_timeout_s: float = 10.0
    query_row_cap: int = 1000
    export_row_cap: int = 100_000
    duckdb_memory_limit: str = "512MB"
    duckdb_threads: int = 2
    max_cross_product_rows: int = 10_000_000

    # --- pipeline ---
    max_correction_attempts: int = 2
    schema_link_threshold: int = 40
    followup_history_turns: int = 4
    answer_cache_ttl_s: int = 3600

    # --- limits ---
    rate_limit_per_min: int = 30
    daily_cost_cap_usd: float = 1.0

    # --- observability ---
    sentry_dsn: str | None = None

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _empty_secret_means_default(cls, v: object) -> object:
        # An empty JWT_SECRET= line (e.g. copied from .env.example) must never mean "no key".
        if v is None or (isinstance(v, str) and not v.strip()):
            return "dev-insecure-placeholder-change-me-before-deploying"
        return v

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def use_mock_llm(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "anthropic":
            return False
        return self.anthropic_api_key is None


@lru_cache
def get_settings() -> Settings:
    return Settings()
