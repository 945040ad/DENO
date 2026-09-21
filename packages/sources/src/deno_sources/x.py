"""X (Twitter): discovery by web search, hydration by known status id only.

Hydration tiers:
  1. ``cdn.syndication.twimg.com/tweet-result`` — text + like/reply counts. Its
     robots.txt disallows bots, so it runs only when the operator opts that host in.
  2. ``publish.x.com/oembed`` — the official embed API: text, author, date (no counts).
"""

from __future__ import annotations

import re
from datetime import datetime

from selectolax.parser import HTMLParser

from deno_sources.base import SearxngClient, SourceClient
from deno_sources.models import AccessDenied, Engagement, Post, SourceName, SourceUnavailable
from deno_sources.net import Fetcher
from deno_sources.normalize import canonical_url, clean_text

STATUS_URL = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d{5,25})")


def syndication_token(tweet_id: str) -> str:
    """Token the embed widget sends with syndication requests."""
    num = (int(tweet_id) / 1e15) * 3.141592653589793
    digits, whole, out = "0123456789abcdefghijklmnopqrstuvwxyz", int(num), ""
    while whole:
        whole, r = divmod(whole, 36)
        out = digits[r] + out
    return (out or "0").replace("0", "")


def parse_syndication(data: dict[str, object], handle: str, tweet_id: str) -> Post | None:
    text = clean_text(str(data.get("text") or ""))
    if not text:
        return None
    raw_user = data.get("user")
    user: dict[str, object] = raw_user if isinstance(raw_user, dict) else {}
    screen_name = str(user.get("screen_name") or handle)
    url = f"https://x.com/{screen_name}/status/{tweet_id}"
    created = data.get("created_at")
    published = None
    if isinstance(created, str):
        try:
            published = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            published = None
    return Post(
        source=SourceName.X,
        url=url,
        canonical_url=canonical_url(url),
        text=text,
        author_handle=screen_name,
        published_at=published,
        engagement=Engagement(
            likes=_int(data.get("favorite_count")),
            comments=_int(data.get("conversation_count")),
        ),
        tier="syndication",
    )


def parse_oembed(data: dict[str, object], tweet_id: str) -> Post | None:
    html = str(data.get("html") or "")
    tree = HTMLParser(html)
    paragraph = tree.css_first("blockquote p")
    if paragraph is None:
        return None
    text = clean_text(paragraph.html or "")
    author_url = str(data.get("author_url") or "")
    handle = author_url.rstrip("/").rsplit("/", 1)[-1] if author_url else None
    date_link = tree.css("blockquote > a")
    published = None
    if date_link:
        try:
            published = datetime.strptime(date_link[-1].text(strip=True), "%B %d, %Y")
        except ValueError:
            published = None
    url = f"https://x.com/{handle}/status/{tweet_id}" if handle else str(data.get("url") or "")
    if not text or not url:
        return None
    return Post(
        source=SourceName.X,
        url=url,
        canonical_url=canonical_url(url),
        text=text,
        author_handle=handle,
        published_at=published,
        tier="oembed",
    )


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


class XClient(SourceClient):
    name = SourceName.X

    def __init__(self, fetcher: Fetcher, searxng: SearxngClient) -> None:
        super().__init__(fetcher)
        self.searxng = searxng

    async def discover(self, query: str, *, time_range: str | None = None) -> list[tuple[str, str]]:
        """(handle, tweet id) pairs found by `site:x.com` search."""
        results = await self.searxng.search(f'site:x.com "{query}"', time_range=time_range)
        found: dict[str, tuple[str, str]] = {}
        for r in results:
            if m := STATUS_URL.search(r["url"]):
                found.setdefault(m.group(2), (m.group(1), m.group(2)))
        return list(found.values())

    async def search(self, query: str, *, since: datetime | None = None, limit: int = 25) -> list[Post]:
        posts: list[Post] = []
        for handle, tweet_id in (await self.discover(query))[:limit]:
            post = await self.hydrate(f"https://x.com/{handle}/status/{tweet_id}")
            if post and (since is None or post.published_at is None or post.published_at >= since):
                posts.append(post)
        return posts

    async def hydrate(self, url: str) -> Post | None:
        match = STATUS_URL.search(url)
        if not match:
            return None
        handle, tweet_id = match.groups()
        try:
            res = await self.fetcher.get(
                "https://cdn.syndication.twimg.com/tweet-result",
                source=self.name,
                params={"id": tweet_id, "token": syndication_token(tweet_id)},
                cache_ttl_s=24 * 3600,
                browser_ua=True,
            )
            if res.status == 200 and res.text.lstrip().startswith("{"):
                data = res.json()
                if isinstance(data, dict) and (post := parse_syndication(data, handle, tweet_id)):
                    return post
        except AccessDenied:
            pass  # host not opted in: fall through to the official embed API
        except SourceUnavailable:
            pass
        res = await self.fetcher.get(
            "https://publish.x.com/oembed",
            source=self.name,
            params={"url": f"https://x.com/{handle}/status/{tweet_id}", "omit_script": "1", "dnt": "true"},
            cache_ttl_s=24 * 3600,
        )
        if res.status != 200:
            return None
        data = res.json()
        return parse_oembed(data, tweet_id) if isinstance(data, dict) else None
