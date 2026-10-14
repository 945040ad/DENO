"""Reddit via Arctic Shift (a public research archive API; robots.txt allows all).

Discovery is per candidate subreddit: comment bodies and post titles matching the
query. reddit.com itself disallows bots in robots.txt, so it is never fetched
unless an operator opts the host in.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from deno_sources.base import SourceClient
from deno_sources.models import Engagement, Post, SourceName
from deno_sources.net import Fetcher, FetchResult
from deno_sources.normalize import canonical_url, clean_text, mentions_near, query_stems

_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "your",
        "you",
        "are",
        "how",
        "what",
        "why",
        "who",
        "into",
        "about",
        "tool",
        "tools",
        "app",
        "software",
    ]
)
API = "https://arctic-shift.photon-reddit.com/api"


def _ts(value: object) -> datetime | None:
    if not isinstance(value, int | float | str):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (ValueError, OverflowError):
        return None


def _num(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _permalink(path: str | None) -> str | None:
    return f"https://www.reddit.com{path}" if path and path.startswith("/r/") else None


def parse_comment(item: dict[str, object]) -> Post | None:
    body = clean_text(str(item.get("body") or ""))
    url = _permalink(str(item.get("permalink") or ""))
    if not url or not body or body in {"[deleted]", "[removed]"}:
        return None
    author = str(item.get("author") or "")
    return Post(
        source=SourceName.REDDIT,
        url=url,
        canonical_url=canonical_url(url),
        text=body,
        author_handle=None if author in {"", "[deleted]"} else author,
        community=f"r/{item.get('subreddit')}" if item.get("subreddit") else None,
        published_at=_ts(item.get("created_utc")),
        engagement=Engagement(score=_num(item.get("score"))),
        kind="comment",
        tier="arctic_shift",
    )


def parse_post(item: dict[str, object]) -> Post | None:
    url = _permalink(str(item.get("permalink") or ""))
    title = clean_text(str(item.get("title") or ""))
    body = clean_text(str(item.get("selftext") or ""))
    if not url or not title or body in {"[deleted]", "[removed]"}:
        return None
    author = str(item.get("author") or "")
    return Post(
        source=SourceName.REDDIT,
        url=url,
        canonical_url=canonical_url(url),
        title=title,
        text=f"{title}\n\n{body}".strip(),
        author_handle=None if author in {"", "[deleted]"} else author,
        community=f"r/{item.get('subreddit')}" if item.get("subreddit") else None,
        published_at=_ts(item.get("created_utc")),
        engagement=Engagement(score=_num(item.get("score")), comments=_num(item.get("num_comments"))),
        kind="post",
        tier="arctic_shift",
    )


class RedditClient(SourceClient):
    name = SourceName.REDDIT

    def __init__(self, fetcher: Fetcher, subreddits: list[str] | None = None) -> None:
        super().__init__(fetcher)
        self.subreddits = [s.removeprefix("r/") for s in (subreddits or [])]

    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        """Arctic Shift full-text search times out on multi-word queries in large subreddits, so the API
        gets the most distinctive word and the other words are matched locally (by stem)."""
        terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in _STOP and len(t) > 2]
        if not terms:
            return []
        anchor = max(terms, key=len)
        stems = query_stems(query)
        posts: list[Post] = []
        for sub in self.subreddits:
            params: dict[str, str | int] = {"subreddit": sub, "limit": 100}
            if since:
                params["after"] = since.strftime("%Y-%m-%d")
            res = await self._get(f"{API}/comments/search", {**params, "body": anchor})
            if res.status == 200:
                posts += [p for item in _data(res.json()) if (p := parse_comment(item))]
            res = await self._get(f"{API}/posts/search", {**params, "query": anchor})
            if res.status == 200:
                posts += [p for item in _data(res.json()) if (p := parse_post(item))]
        # Every word, close together: a substring test let "ball" match every post in r/Softball.
        matched = [p for p in posts if mentions_near(p.text, stems, window=20)]
        matched.sort(key=lambda p: p.engagement.score or 0, reverse=True)
        return matched[: limit * max(1, len(self.subreddits))]

    async def _get(self, url: str, params: dict[str, str | int]) -> FetchResult:
        """Arctic Shift reports overload as 422 "Timeout. Maybe slow down a bit": back off and retry twice."""
        res = await self.fetcher.get(url, source=self.name, params=params, cache_ttl_s=6 * 3600)
        for delay in (2.0, 5.0):
            if res.status != 422 or "slow down" not in res.text.lower():
                break
            await asyncio.sleep(delay)
            res = await self.fetcher.get(url, source=self.name, params=params, cache_ttl_s=6 * 3600)
        return res

    async def top_posts(self, subreddit: str, *, since: datetime, limit: int = 50) -> list[Post]:
        """Highest-scoring posts in a community since a date (trend mining, Phase 10)."""
        res = await self.fetcher.get(
            f"{API}/posts/search",
            source=self.name,
            params={
                "subreddit": subreddit.removeprefix("r/"),
                "after": since.strftime("%Y-%m-%d"),
                "limit": 100,
                "sort": "desc",
            },
            cache_ttl_s=24 * 3600,
        )
        if res.status != 200:
            return []
        posts = [p for item in _data(res.json()) if (p := parse_post(item))]
        return sorted(posts, key=lambda p: p.engagement.score or 0, reverse=True)[:limit]


def _data(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [d for d in payload["data"] if isinstance(d, dict)]
    return []
