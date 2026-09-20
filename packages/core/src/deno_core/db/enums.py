"""Enumerations stored as constrained varchar (not native PG enums, which are painful to migrate)."""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Source(StrEnum):
    REDDIT = "reddit"
    X = "x"
    LINKEDIN_POSTS = "linkedin_posts"
    LINKEDIN_JOBS = "linkedin_jobs"
    HN = "hn"
    PRODUCTHUNT = "producthunt"
    TRENDS = "trends"
    APIFY = "apify"


class Platform(StrEnum):
    REDDIT = "reddit"
    X = "x"
    LINKEDIN = "linkedin"
    HN = "hn"


class Stance(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


class VerdictKind(StrEnum):
    BUILD = "build"
    PIVOT = "pivot"
    KILL = "kill"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    GATED = "gated"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class StoryCategory(StrEnum):
    SCAR = "scar"
    METRIC = "metric"
    TURNING_POINT = "turning_point"
    DEFENDED_OPINION = "defended_opinion"
    CUSTOMER_QUOTE = "customer_quote"


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"


class UsageKind(StrEnum):
    VALIDATION_RUN = "validation_run"
    CONTENT_PLAN = "content_plan"
    LLM_TOKENS = "llm_tokens"
    AUDIT = "audit"


class TakedownStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    REJECTED = "rejected"
