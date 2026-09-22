"""Wires the LLM layer from settings: one shared limiter for chat, embeddings and rerank."""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from deno_core.settings import Settings
from deno_llm.limiter import Limiter, LocalLimiter, ValkeyLimiter
from deno_llm.retrieval_models import NimEmbedder, NimReranker
from deno_llm.router import LLMRouter
from deno_llm.tracing import tracing_callbacks
from deno_llm.usage import UsageTracker


@dataclass
class LLMStack:
    router: LLMRouter
    embedder: NimEmbedder
    reranker: NimReranker
    usage: UsageTracker
    limiter: Limiter


def build_stack(settings: Settings, redis: Redis | None = None) -> LLMStack:
    """A fresh stack per run (its own ``UsageTracker`` budget); the limiter budget is shared via Valkey."""
    rpm = settings.llm_requests_per_minute
    limiter: Limiter = ValkeyLimiter(redis, rpm) if redis is not None else LocalLimiter(rpm)
    usage = UsageTracker(
        token_budget=settings.llm_run_token_budget,
        usd_per_mtok_input=settings.llm_usd_per_mtok_input,
        usd_per_mtok_output=settings.llm_usd_per_mtok_output,
    )
    key = settings.nvidia_nim_api_key.get_secret_value()
    base = settings.nvidia_nim_base_url
    return LLMStack(
        router=LLMRouter(settings, limiter=limiter, callbacks=[usage, *tracing_callbacks(settings)]),
        embedder=NimEmbedder(api_key=key, model=settings.embed_model, base_url=base, limiter=limiter),
        reranker=NimReranker(api_key=key, model=settings.rerank_model, base_url=base, limiter=limiter),
        usage=usage,
        limiter=limiter,
    )
