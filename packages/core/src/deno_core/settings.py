"""Typed application settings (pydantic-settings).

Sources, highest priority first: environment variables, secret files in
``DENO_SECRETS_DIR`` (Docker/K8s secrets, one file per setting name), then the
``.env`` file in the working directory. Unknown variables are ignored.

``get_settings()`` validates once per process; in production it fails fast on
anything a real deployment can't run without.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("DENO_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        secrets_dir=os.getenv("DENO_SECRETS_DIR") or None,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_json: bool = Field(default=True, description="JSON logs; set false for human-readable dev output")

    # --- LLM provider (NVIDIA NIM, ADR-008) ---
    nvidia_nim_api_key: SecretStr = SecretStr("")
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_model_fast: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_model_strong: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_model_judge: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_model_fallback: str = "meta/llama-3.2-11b-vision-instruct"
    llm_requests_per_minute: int = Field(default=36, ge=1, le=40, description="NIM hard cap is 40/min per key")
    llm_timeout_seconds: float = 60.0
    # LangChain `init_chat_model` provider. "openai" = NIM's OpenAI-compatible endpoint (json_schema
    # structured output works there; ChatNVIDIA's guided_json is rejected by NIM since 2026-09).
    llm_provider: str = "openai"
    llm_structured_method: Literal["json_schema", "json_mode", "function_calling"] = "json_schema"
    # Nemotron 3 "thinking" costs ~10x latency (0.8 s vs 7.7 s for a short structured answer) and in batch
    # judging it ran past the length limit. Roles listed here keep it; the rest send enable_thinking=false.
    llm_thinking_roles: Annotated[set[str], NoDecode] = set()
    llm_run_token_budget: int = Field(default=400_000, ge=1000, description="Hard stop per validation run")
    llm_usd_per_mtok_input: float = 0.0  # NIM trial keys are free; set for paid endpoints
    llm_usd_per_mtok_output: float = 0.0
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"
    embed_model: str = "nvidia/nemotron-3-embed-1b"
    rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2"

    # --- Data ---
    database_url: str = Field(default="", description="postgresql+asyncpg://… (Supabase Postgres)")
    valkey_url: str = "redis://127.0.0.1:6379/0"
    searxng_url: str = "http://127.0.0.1:8890"
    # Send a Google ID token to SearXNG when it runs as a private Cloud Run service (docs/09 §5.3).
    searxng_gcp_auth: bool = False

    # --- Jobs (docs/09 §4) ---
    # taskiq: Valkey queue + worker process (compose / VPS). cloudrun_job: one Cloud Run Job
    # execution per graph run (free tier, no always-on worker).
    task_runner: Literal["taskiq", "cloudrun_job"] = "taskiq"
    cloudrun_job: str = ""  # projects/<project>/locations/<region>/jobs/<name>
    # Cloud Scheduler -> POST /internal/cron/*: the OIDC audience and the caller's service account.
    # Both empty = the cron endpoints answer 404 (the taskiq scheduler runs maintenance instead).
    cron_oidc_audience: str = ""
    cron_service_account: str = ""

    # --- Sources (Phase 5) ---
    # Hosts whose robots.txt disallows bots but the operator has decided (after legal review)
    # to fetch anyway, e.g. "www.linkedin.com,cdn.syndication.twimg.com". Empty = obey robots.txt.
    sources_robots_opt_in: Annotated[set[str], NoDecode] = set()
    sources_user_agent: str = ""
    takedown_rate_limit_per_hour: int = 5

    # --- Auth (Supabase, ADR-003) ---
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_legacy_jwt_secret: SecretStr = SecretStr("")
    # Server-side only (account deletion through the Auth admin API). Never in web/.
    supabase_secret_key: SecretStr = SecretStr("")

    # --- Billing (Stripe, ADR-012). Billing endpoints return 503 until these are set. ---
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secret: SecretStr = SecretStr("")
    stripe_price_pro: str = ""  # price_… for the Pro monthly subscription
    app_url: str = "http://localhost:3000"  # where Stripe sends people back after checkout / portal

    # --- Observability (ADR-013) ---
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = Field(default=0.05, ge=0, le=1)
    metrics_token: SecretStr = SecretStr("")  # bearer token for GET /metrics; empty = only from localhost
    worker_metrics_port: int = 9000

    # --- HTTP ---
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    web_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    request_max_bytes: int = 1_048_576
    api_rate_limit_per_minute: int = 60
    scraped_text_retention_days: int = 90

    @field_validator("web_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("sources_robots_opt_in", "llm_thinking_roles", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return {h.strip().lower() for h in value.split(",") if h.strip()}
        return value

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        if self.environment != "production":
            return self
        missing = [
            name
            for name, ok in {
                "SUPABASE_URL": bool(self.supabase_url),
                "NVIDIA_NIM_API_KEY": bool(self.nvidia_nim_api_key.get_secret_value()),
                "DATABASE_URL": self.database_url.startswith("postgresql"),
                "CLOUDRUN_JOB": self.task_runner != "cloudrun_job" or self.cloudrun_job.count("/") == 5,
            }.items()
            if not ok
        ]
        if missing:
            raise ValueError(f"production requires: {', '.join(missing)}")
        return self

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key.get_secret_value() and self.stripe_price_pro)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.supabase_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
