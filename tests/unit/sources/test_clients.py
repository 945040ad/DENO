"""Parsers on recorded (anonymised) payloads, and clients end to end with mocked HTTP."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from deno_sources import SourceConfig, SourceName, build_clients, build_fetcher
from deno_sources.feeds import parse_producthunt_atom, parse_trends_rss
from deno_sources.hn import parse_hit
from deno_sources.linkedin import parse_job_cards, parse_post_page
from deno_sources.normalize import canonical_url, clean_text, content_hash
from deno_sources.reddit import parse_comment, parse_post
from deno_sources.x import parse_oembed, parse_syndication, syndication_token

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "sources"


def fixture(name: str) -> str:
    return (FIX / name).read_text()


def jfixture(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads(fixture(name))


# ---- normalisation ----------------------------------------------------------------


def test_canonical_url_normalises_hosts_and_strips_tracking() -> None:
    assert canonical_url("http://twitter.com/Jane/status/1?s=20&t=abc") == "https://x.com/Jane/status/1"
    assert (
        canonical_url("https://in.linkedin.com/posts/a-b?utm_source=share&trk=x")
        == "https://www.linkedin.com/posts/a-b"
    )
    assert canonical_url("https://old.reddit.com/r/SaaS/comments/1/x/") == "https://www.reddit.com/r/SaaS/comments/1/x"
    assert canonical_url("https://news.ycombinator.com/item?id=1#c2") == "https://news.ycombinator.com/item?id=1"


def test_clean_text_strips_html_entities_and_controls() -> None:
    assert clean_text("<p>It&#x27;s   painful</p><br>line\x00two") == "It's painful\nlinetwo"


def test_content_hash_ignores_case_and_spacing() -> None:
    assert content_hash("Hello   World") == content_hash("hello world")
    assert content_hash("hello") != content_hash("goodbye")


# ---- parsers ------------------------------------------------------------------------


def test_reddit_parsers() -> None:
    comments = [parse_comment(c) for c in jfixture("arctic_comments.json")["data"]]
    assert all(comments)
    assert comments[0].url.startswith("https://www.reddit.com/r/SaaS/comments/")  # type: ignore[union-attr]
    assert comments[0].community == "r/SaaS"  # type: ignore[union-attr]
    assert comments[0].published_at is not None  # type: ignore[union-attr]
    posts = [parse_post(p) for p in jfixture("arctic_posts.json")["data"]]
    assert posts[-1] is None  # [removed] post dropped
    assert posts[0].title and posts[0].text.startswith(posts[0].title)  # type: ignore[union-attr]
    assert posts[0].engagement.comments is not None  # type: ignore[union-attr]


def test_hn_parser() -> None:
    posts = [p for h in jfixture("hn.json")["hits"] if (p := parse_hit(h))]
    assert posts
    assert all(p.url.startswith("https://news.ycombinator.com/item?id=") for p in posts)
    assert all("<p>" not in p.text for p in posts)


def test_x_parsers() -> None:
    post = parse_syndication(jfixture("x_syndication.json"), "janefounder", "2054197055476895995")
    assert post is not None
    assert post.canonical_url == "https://x.com/janefounder/status/2054197055476895995"
    assert post.engagement.likes and post.published_at
    assert post.tier == "syndication"
    embed = parse_oembed(jfixture("x_oembed.json"), "2054197055476895995")
    assert embed is not None
    assert embed.text.startswith("Our churn dropped 30%")
    assert embed.author_handle == "janefounder"
    assert embed.published_at == datetime(2026, 5, 12, tzinfo=UTC)
    assert syndication_token("2054197055476895995") == syndication_token("2054197055476895995") != ""


def test_linkedin_parsers() -> None:
    url = "https://www.linkedin.com/posts/samexample_customersuccess-churn-activity-7112009104717463552-2e3K"
    post = parse_post_page(fixture("linkedin_post.html"), url)
    assert post is not None
    assert post.tier == "jsonld"
    assert post.text.startswith("We don't learn")
    assert post.author_handle == "samexample"
    assert post.engagement.likes is not None
    assert post.published_at is not None
    og_only = parse_post_page('<meta property="og:description" content="' + "x" * 60 + '">', url)
    assert og_only is not None and og_only.tier == "opengraph"
    jobs = parse_job_cards(fixture("linkedin_jobs.html"))
    assert len(jobs) == 3
    assert all(j.kind == "job" and j.title and "?" not in j.url for j in jobs)


def test_feed_parsers() -> None:
    launches = parse_producthunt_atom(fixture("producthunt.atom"))
    assert len(launches) == 2
    assert launches[0].url.startswith("https://www.producthunt.com/")
    trends = parse_trends_rss(fixture("trends.rss"))
    assert [t.title for t in trends] == ["churn analytics", "ai writing tools"]


def test_feed_parser_rejects_xml_bombs() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><feed>&lol2;</feed>'
    with pytest.raises(Exception, match=r"(?i)entit"):
        parse_producthunt_atom(bomb)


# ---- clients end to end (mocked HTTP) ------------------------------------------------


async def public(_: str) -> list[str]:
    return ["93.184.216.34"]


def clients(opt_in: set[str] | None = None) -> dict:  # type: ignore[type-arg]
    config = SourceConfig(searxng_url="http://searxng:8080", robots_opt_in=opt_in or set(), subreddits=["SaaS"])

    async def no_sleep(_: float) -> None:
        return None

    f = build_fetcher(config, resolver=public, transport=httpx.AsyncHTTPTransport(), sleep=no_sleep)
    return build_clients(config, f)


@respx.mock
async def test_reddit_client_searches_comments_and_posts() -> None:
    respx.get("https://arctic-shift.photon-reddit.com/api/comments/search").respond(
        200, json=jfixture("arctic_comments.json")
    )
    respx.get("https://arctic-shift.photon-reddit.com/api/posts/search").respond(
        200, json=jfixture("arctic_posts.json")
    )
    posts = await clients()[SourceName.REDDIT].search("churn", since=datetime(2026, 1, 1, tzinfo=UTC))
    assert {p.kind for p in posts} == {"comment", "post"}
    assert len(posts) == 4


@respx.mock
async def test_x_client_uses_oembed_when_syndication_not_opted_in() -> None:
    respx.get("http://searxng:8080/search").respond(200, json=jfixture("searxng_x.json"))
    respx.get("https://cdn.syndication.twimg.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    synd = respx.get("https://cdn.syndication.twimg.com/tweet-result").respond(200, json=jfixture("x_syndication.json"))
    respx.get("https://publish.x.com/oembed").respond(200, json=jfixture("x_oembed.json"))
    posts = await clients()[SourceName.X].search("churn")
    assert len(posts) == 1  # the twitter.com duplicate and the profile URL are dropped
    assert posts[0].tier == "oembed"
    assert not synd.called


def test_post_dates_are_normalised_to_utc() -> None:
    from datetime import timedelta, timezone

    from deno_sources.models import Post

    naive = Post(
        source=SourceName.X, url="u", canonical_url="u", text="t", tier="oembed", published_at=datetime(2026, 5, 12)
    )
    assert naive.published_at == datetime(2026, 5, 12, tzinfo=UTC)
    ist = timezone(timedelta(hours=5, minutes=30))
    aware = Post(
        source=SourceName.X,
        url="u",
        canonical_url="u",
        text="t",
        tier="x",
        published_at=datetime(2026, 5, 12, 5, 30, tzinfo=ist),
    )
    assert aware.published_at == datetime(2026, 5, 12, tzinfo=UTC) and aware.published_at.tzinfo is UTC


@respx.mock
async def test_x_client_since_filter_handles_naive_oembed_dates() -> None:
    respx.get("http://searxng:8080/search").respond(200, json=jfixture("searxng_x.json"))
    respx.get("https://cdn.syndication.twimg.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    respx.get("https://publish.x.com/oembed").respond(200, json=jfixture("x_oembed.json"))
    x = clients()[SourceName.X]
    assert len(await x.search("churn", since=datetime(2026, 1, 1, tzinfo=UTC))) == 1
    assert await x.search("churn", since=datetime(2026, 6, 1, tzinfo=UTC)) == []


@respx.mock
async def test_x_client_uses_syndication_when_opted_in() -> None:
    respx.get("http://searxng:8080/search").respond(200, json=jfixture("searxng_x.json"))
    respx.get("https://cdn.syndication.twimg.com/tweet-result").respond(200, json=jfixture("x_syndication.json"))
    posts = await clients({"cdn.syndication.twimg.com"})[SourceName.X].search("churn")
    assert posts[0].tier == "syndication"
    assert posts[0].engagement.likes


@respx.mock
async def test_linkedin_client_blocked_by_robots_without_opt_in() -> None:
    respx.get("http://searxng:8080/search").respond(200, json=jfixture("searxng_linkedin.json"))
    respx.get("https://www.linkedin.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    from deno_sources import AccessDenied

    with pytest.raises(AccessDenied):
        await clients()[SourceName.LINKEDIN_POSTS].search("churn")


@respx.mock
async def test_linkedin_client_dedupes_and_hydrates_when_opted_in() -> None:
    respx.get("http://searxng:8080/search").respond(200, json=jfixture("searxng_linkedin.json"))
    page = respx.get(url__startswith="https://www.linkedin.com/posts/").respond(200, text=fixture("linkedin_post.html"))
    respx.get(url__startswith="https://www.linkedin.com/jobs-guest/").respond(200, text=fixture("linkedin_jobs.html"))
    c = clients({"www.linkedin.com"})
    posts = await c[SourceName.LINKEDIN_POSTS].search("churn")
    assert len(posts) == 1
    assert page.call_count == 1
    jobs = await c[SourceName.LINKEDIN_JOBS].search("customer success", since=datetime(2026, 9, 1, tzinfo=UTC))
    assert len(jobs) == 3


@respx.mock
async def test_hn_and_feed_clients() -> None:
    respx.get("https://hn.algolia.com/api/v1/search").respond(200, json=jfixture("hn.json"))
    respx.get("https://www.producthunt.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /search*")
    respx.get("https://www.producthunt.com/feed").respond(200, text=fixture("producthunt.atom"))
    respx.get("https://trends.google.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /explore?")
    respx.get("https://trends.google.com/trending/rss").respond(200, text=fixture("trends.rss"))
    c = clients()
    assert await c[SourceName.HN].search("churn")
    assert len(await c[SourceName.PRODUCTHUNT].recent_launches()) == 2  # type: ignore[attr-defined]
    assert [t.title for t in await c[SourceName.TRENDS].search("churn analytics platform")] == ["churn analytics"]
