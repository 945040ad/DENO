"""Builds the fetcher (host allow-list + access policy) and every client."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from deno_sources.base import SearxngClient, SourceClient
from deno_sources.feeds import ProductHuntClient, TrendsClient
from deno_sources.hn import HackerNewsClient
from deno_sources.linkedin import LinkedInJobsClient, LinkedInPostsClient
from deno_sources.models import SourceName
from deno_sources.net import Cache, Fetcher, HostPolicy, Resolver, system_resolver
from deno_sources.reddit import RedditClient
from deno_sources.x import XClient

# Access basis per host. "api" = a documented programmatic endpoint (or robots.txt allows
# us); "robots" = robots.txt is checked and enforced unless the operator opts the host in.
HOSTS: dict[str, HostPolicy] = {
    "arctic-shift.photon-reddit.com": HostPolicy(rate_per_s=1.0, burst=2, access="api"),
    "hn.algolia.com": HostPolicy(rate_per_s=2.0, burst=4, access="api"),
    "publish.x.com": HostPolicy(rate_per_s=2.0, burst=4, access="api"),
    "cdn.syndication.twimg.com": HostPolicy(rate_per_s=2.0, burst=4, access="robots"),
    "www.linkedin.com": HostPolicy(rate_per_s=0.4, burst=1, access="robots"),
    "www.producthunt.com": HostPolicy(rate_per_s=0.5, burst=1, access="robots"),
    "trends.google.com": HostPolicy(rate_per_s=0.5, burst=1, access="robots"),
    "www.reddit.com": HostPolicy(rate_per_s=0.5, burst=1, access="robots"),
}

# Global per-source request caps per UTC day (cache hits don't count). Keeps us a
# low-volume, user-initiated visitor even if usage spikes.
DAILY_CAPS: dict[str, int] = {
    SourceName.REDDIT: 5000,
    SourceName.HN: 5000,
    SourceName.X: 3000,
    SourceName.LINKEDIN_POSTS: 300,
    SourceName.LINKEDIN_JOBS: 300,
    SourceName.PRODUCTHUNT: 500,
    SourceName.TRENDS: 200,
    "searxng": 3000,
}


@dataclass
class SourceConfig:
    searxng_url: str
    robots_opt_in: set[str] = field(default_factory=set)
    subreddits: list[str] = field(default_factory=list)
    user_agent: str | None = None
    daily_caps: dict[str, int] = field(default_factory=lambda: dict(DAILY_CAPS))


def build_fetcher(
    config: SourceConfig, *, cache: Cache | None = None, resolver: Resolver = system_resolver, **kw: object
) -> Fetcher:
    searx_host = (urlsplit(config.searxng_url).hostname or "").lower()
    options: dict[str, object] = {"cache": cache, "resolver": resolver, **kw}
    if config.user_agent:
        options["user_agent"] = config.user_agent
    return Fetcher(
        HOSTS,
        internal_hosts={searx_host: HostPolicy(rate_per_s=0.5, burst=2, access="api")},
        robots_opt_in=config.robots_opt_in,
        daily_caps=config.daily_caps,
        **options,  # type: ignore[arg-type]
    )


def build_clients(config: SourceConfig, fetcher: Fetcher) -> dict[SourceName, SourceClient]:
    searx = SearxngClient(fetcher, config.searxng_url)
    return {
        SourceName.REDDIT: RedditClient(fetcher, config.subreddits),
        SourceName.X: XClient(fetcher, searx),
        SourceName.LINKEDIN_POSTS: LinkedInPostsClient(fetcher, searx),
        SourceName.LINKEDIN_JOBS: LinkedInJobsClient(fetcher),
        SourceName.HN: HackerNewsClient(fetcher),
        SourceName.PRODUCTHUNT: ProductHuntClient(fetcher, searx),
        SourceName.TRENDS: TrendsClient(fetcher),
    }
