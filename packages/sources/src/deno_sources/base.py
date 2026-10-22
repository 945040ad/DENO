"""Source client contract and SearXNG discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from deno_sources.models import Post, SourceName, SourceUnavailable
from deno_sources.net import Fetcher, FetchResult

# Extra request headers, fetched per request (e.g. a short-lived ID token for a private SearXNG).
HeaderProvider = Callable[[], Awaitable[Mapping[str, str]]]


class SourceClient(ABC):
    name: SourceName

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @abstractmethod
    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        """Discover posts for a query (may return partially hydrated posts)."""

    async def hydrate(self, url: str) -> Post | None:
        """Fetch one known URL in full. Default: not supported by this source."""
        return None


class SearxngClient:
    """Web search through a self-hosted SearXNG (JSON API). Used for `site:` discovery."""

    def __init__(self, fetcher: Fetcher, base_url: str, headers: HeaderProvider | None = None) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")
        self._headers = headers

    async def search(self, query: str, *, time_range: str | None = None, pages: int = 1) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for page in range(1, pages + 1):
            params: dict[str, str | int] = {"q": query, "format": "json", "pageno": page}
            if time_range:
                params["time_range"] = time_range  # day | week | month | year
            res = await self.fetcher.get(
                f"{self.base_url}/search",
                source="searxng",
                params=params,
                headers=await self._headers() if self._headers else None,
                cache_ttl_s=24 * 3600,
                cacheable=lambda r: blocked_engines(r) is None,
            )
            if res.status != 200:
                if page == 1:
                    raise SourceUnavailable(f"search answered HTTP {res.status}")
                break
            if page == 1 and (blocked := blocked_engines(res)):
                # Indistinguishable from "nobody talks about this" unless we say so.
                raise SourceUnavailable(f"search engines blocked: {blocked}")
            data = res.json()
            batch = data.get("results", []) if isinstance(data, dict) else []
            results.extend(
                {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
                for r in batch
                if isinstance(r, dict) and r.get("url")
            )
            if not batch:
                break
        return results


def blocked_engines(res: FetchResult) -> str | None:
    """Which upstream engines refused us, when SearXNG answered 200 with no results because of it.

    SearXNG reports CAPTCHAs and rate limits in ``unresponsive_engines`` (``[[name, reason], ...]``)
    while still returning HTTP 200 - so an empty result list on its own means nothing.
    """
    if res.status != 200:
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("results"):
        return None
    pairs = [e for e in data.get("unresponsive_engines") or [] if isinstance(e, list | tuple) and e]
    if not pairs:
        return None
    return ", ".join(f"{e[0]} ({e[1]})" if len(e) > 1 and e[1] else str(e[0]) for e in pairs)[:200]
