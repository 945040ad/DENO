"""Hacker News via the official Algolia search API."""

from __future__ import annotations

from datetime import UTC, datetime

from deno_sources.base import SourceClient
from deno_sources.models import Engagement, Post, SourceName
from deno_sources.normalize import canonical_url, clean_text, mentions_near, query_stems

API = "https://hn.algolia.com/api/v1"


def parse_hit(hit: dict[str, object]) -> Post | None:
    object_id = str(hit.get("objectID") or "")
    if not object_id:
        return None
    url = f"https://news.ycombinator.com/item?id={object_id}"
    title = clean_text(str(hit.get("title") or hit.get("story_title") or ""))
    body = clean_text(str(hit.get("comment_text") or hit.get("story_text") or ""))
    text = body or title
    if not text:
        return None
    tags = hit.get("_tags")
    is_comment = isinstance(tags, list) and "comment" in tags
    created = hit.get("created_at_i")
    return Post(
        source=SourceName.HN,
        url=url,
        canonical_url=canonical_url(url),
        title=title or None,
        text=text if is_comment or not body else f"{title}\n\n{body}",
        author_handle=str(hit.get("author") or "") or None,
        published_at=datetime.fromtimestamp(int(created), tz=UTC) if isinstance(created, int) else None,
        engagement=Engagement(
            score=int(p) if isinstance(p := hit.get("points"), int) else 0,
            comments=int(c) if isinstance(c := hit.get("num_comments"), int) else 0,
        ),
        kind="comment" if is_comment else "story",
        tier="algolia",
    )


class HackerNewsClient(SourceClient):
    name = SourceName.HN

    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        # Over-fetch, then keep hits where the query words sit close together (see ``mentions_near``).
        params: dict[str, str | int] = {"query": query, "tags": "(story,comment)", "hitsPerPage": min(limit * 3, 100)}
        if since:
            params["numericFilters"] = f"created_at_i>{int(since.timestamp())}"
        res = await self.fetcher.get(f"{API}/search", source=self.name, params=params, cache_ttl_s=6 * 3600)
        if res.status != 200:
            return []
        data = res.json()
        hits = data.get("hits", []) if isinstance(data, dict) else []
        stems = query_stems(query)
        posts = [p for h in hits if isinstance(h, dict) and (p := parse_hit(h))]
        return [p for p in posts if mentions_near(f"{p.title or ''} {p.text}", stems)][:limit]

    async def total_mentions(self, query: str, *, since: datetime | None = None) -> int:
        params: dict[str, str | int] = {"query": query, "hitsPerPage": 0}
        if since:
            params["numericFilters"] = f"created_at_i>{int(since.timestamp())}"
        res = await self.fetcher.get(f"{API}/search", source=self.name, params=params, cache_ttl_s=6 * 3600)
        data = res.json() if res.status == 200 else {}
        return int(data.get("nbHits", 0)) if isinstance(data, dict) else 0
