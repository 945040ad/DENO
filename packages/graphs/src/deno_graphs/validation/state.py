"""Graph state. Large data (documents, chunks, claims) lives in Postgres; state keeps ids and summaries."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class CollectResult(TypedDict):
    source: str
    queries: list[str]
    posts: list[dict[str, Any]]  # serialised deno_sources.Post
    error: str | None
    seconds: float


class AnalystResult(TypedDict):
    analyst: str
    claim_ids: list[str]  # persisted claims (DB ids)


class ValidationState(TypedDict, total=False):
    idea: str
    brief: dict[str, Any]
    rejected: str | None
    perspectives: list[dict[str, Any]]
    plan: dict[str, Any]
    collected: Annotated[list[CollectResult], operator.add]
    ingest: dict[str, Any]
    coverage: dict[str, Any]
    analysts: Annotated[list[AnalystResult], operator.add]
    validation: dict[str, Any]
    signals: dict[str, Any]
    critic_round: int
    critique: list[dict[str, Any]]
    verdict: dict[str, Any]
    review: dict[str, Any]
