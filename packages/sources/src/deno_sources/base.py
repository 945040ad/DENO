"""Source client contract and SearXNG discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from deno_sources.models import Post, SourceName
from deno_sources.net import Fetcher


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

    def __init__(self, fetcher: Fetcher, base_url: str) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, *, time_range: str | None = None, pages: int = 1) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for page in range(1, pages + 1):
            params: dict[str, str | int] = {"q": query, "format": "json", "pageno": page}
            if time_range:
                params["time_range"] = time_range  # day | week | month | year
            res = await self.fetcher.get(
                f"{self.base_url}/search", source="searxng", params=params, cache_ttl_s=24 * 3600
            )
            if res.status != 200:
                break
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
