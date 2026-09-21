"""Feed-based sources: Product Hunt launches (Atom) and Google Trends daily trends (RSS)."""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from deno_sources.base import SearxngClient, SourceClient
from deno_sources.models import Engagement, Post, SourceName
from deno_sources.net import Fetcher
from deno_sources.normalize import canonical_url, clean_text

ATOM = "{http://www.w3.org/2005/Atom}"
HT = "{https://trends.google.com/trending/rss}"


def _text(el: Element | None) -> str:
    return (el.text or "") if el is not None else ""


def parse_producthunt_atom(xml: str) -> list[Post]:
    root = SafeET.fromstring(xml)
    posts: list[Post] = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.find(f"{ATOM}link[@rel='alternate']")
        url = link.get("href") if link is not None else None
        title = clean_text(_text(entry.find(f"{ATOM}title")))
        if not url or not title:
            continue
        summary = clean_text(_text(entry.find(f"{ATOM}content")) or _text(entry.find(f"{ATOM}summary")))
        published = None
        if raw := _text(entry.find(f"{ATOM}published")):
            try:
                published = datetime.fromisoformat(raw)
            except ValueError:
                published = None
        posts.append(
            Post(
                source=SourceName.PRODUCTHUNT,
                url=url,
                canonical_url=canonical_url(url),
                title=title,
                text=f"{title}\n\n{summary}".strip(),
                author_handle=clean_text(_text(entry.find(f"{ATOM}author/{ATOM}name"))) or None,
                published_at=published,
                kind="launch",
                tier="atom_feed",
            )
        )
    return posts


def parse_trends_rss(xml: str) -> list[Post]:
    root = SafeET.fromstring(xml)
    posts: list[Post] = []
    for item in root.iter("item"):
        title = clean_text(_text(item.find("title")))
        if not title:
            continue
        published = None
        if raw := _text(item.find("pubDate")):
            try:
                published = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                published = None
        traffic = _text(item.find(f"{HT}approx_traffic")).replace("+", "").replace(",", "")
        url = f"https://trends.google.com/trends/explore?q={title.replace(' ', '+')}"
        posts.append(
            Post(
                source=SourceName.TRENDS,
                url=url,
                canonical_url=canonical_url(url),
                title=title,
                text=title,
                published_at=published,
                engagement=Engagement(views=int(traffic) if traffic.isdigit() else None),
                kind="trend",
                tier="rss",
            )
        )
    return posts


class ProductHuntClient(SourceClient):
    """Competitor launches: recent feed plus `site:producthunt.com/products` discovery."""

    name = SourceName.PRODUCTHUNT

    def __init__(self, fetcher: Fetcher, searxng: SearxngClient) -> None:
        super().__init__(fetcher)
        self.searxng = searxng

    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        results = await self.searxng.search(f'site:producthunt.com/products "{query}"', time_range="year")
        posts: list[Post] = []
        seen: set[str] = set()
        for r in results:
            if "/products/" not in r["url"]:
                continue
            url = canonical_url(r["url"].split("?")[0])
            base = "/".join(url.split("/")[:5])  # https://www.producthunt.com/products/<slug>
            if base in seen:
                continue
            seen.add(base)
            title = clean_text(r["title"]).removesuffix(" | Product Hunt")
            posts.append(
                Post(
                    source=SourceName.PRODUCTHUNT,
                    url=base,
                    canonical_url=base,
                    title=title,
                    text=f"{title}\n\n{clean_text(r['content'])}".strip(),
                    kind="launch",
                    tier="search_snippet",
                )
            )
        return posts[:limit]

    async def recent_launches(self, category: str | None = None) -> list[Post]:
        params = {"category": category} if category else None
        res = await self.fetcher.get(
            "https://www.producthunt.com/feed", source=self.name, params=params, cache_ttl_s=6 * 3600
        )
        return parse_producthunt_atom(res.text) if res.status == 200 else []


class TrendsClient(SourceClient):
    """Google Trends daily trending searches (context only; never evidence for a claim)."""

    name = SourceName.TRENDS

    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        words = {w.lower() for w in query.split() if len(w) > 3}
        return [p for p in await self.daily() if words & set(p.text.lower().split())][:limit]

    async def daily(self, geo: str = "US") -> list[Post]:
        res = await self.fetcher.get(
            "https://trends.google.com/trending/rss", source=self.name, params={"geo": geo}, cache_ttl_s=3 * 3600
        )
        return parse_trends_rss(res.text) if res.status == 200 else []
