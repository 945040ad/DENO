"""The normalised shape every source client returns."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SourceName(StrEnum):
    REDDIT = "reddit"
    X = "x"
    LINKEDIN_POSTS = "linkedin_posts"
    LINKEDIN_JOBS = "linkedin_jobs"
    HN = "hn"
    PRODUCTHUNT = "producthunt"
    TRENDS = "trends"
    APIFY = "apify"


class Engagement(BaseModel):
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    score: int | None = None  # platform-native score (Reddit/HN points)
    views: int | None = None


class Post(BaseModel):
    """One public post, comment, job listing or launch.

    `text` is untrusted third-party content: store it as data, never interpret it
    as instructions, and sanitise before rendering as HTML.
    """

    source: SourceName
    url: str
    canonical_url: str
    text: str
    author_handle: str | None = None
    title: str | None = None
    community: str | None = None  # subreddit, hashtag, company…
    published_at: datetime | None = None
    engagement: Engagement = Field(default_factory=Engagement)
    kind: str = "post"  # post | comment | story | job | launch | trend
    tier: str  # which access path produced it (e.g. "arctic_shift", "syndication", "oembed", "jsonld")
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("published_at", "fetched_at")
    @classmethod
    def _aware_utc(cls, value: datetime | None) -> datetime | None:
        """Naive datetimes (e.g. X oEmbed dates) are taken as UTC so `since` comparisons never mix kinds."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SourceUnavailable(Exception):
    """The source can't be used right now (circuit open, blocked, policy). Not retried by callers."""


class AccessDenied(SourceUnavailable):
    """robots.txt / policy forbids this fetch and the operator hasn't opted in."""
