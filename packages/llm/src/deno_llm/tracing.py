"""Langfuse tracing (ADR-013). Enabled when LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set."""

from __future__ import annotations

from functools import cache

from langchain_core.callbacks import BaseCallbackHandler

from deno_core.logging import get_logger
from deno_core.settings import Settings

log = get_logger(__name__)


@cache
def _client(public_key: str, secret_key: str, host: str, environment: str) -> None:
    from langfuse import Langfuse

    Langfuse(public_key=public_key, secret_key=secret_key, host=host, environment=environment)


def tracing_callbacks(settings: Settings) -> list[BaseCallbackHandler]:
    secret = settings.langfuse_secret_key.get_secret_value()
    if not (settings.langfuse_public_key and secret):
        return []
    try:
        from langfuse.langchain import CallbackHandler

        _client(settings.langfuse_public_key, secret, settings.langfuse_host, settings.environment)
        return [CallbackHandler(public_key=settings.langfuse_public_key)]
    except Exception:  # tracing must never break a run
        log.warning("langfuse_unavailable", exc_info=True)
        return []
