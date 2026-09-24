"""Phase 0 spike: can we find and hydrate real posts per idea without platform keys?

For each test idea:
  discovery  SearXNG `site:x.com "<phrase>"` / `site:linkedin.com/posts "<phrase>"`,
             Arctic Shift comment search in candidate subreddits, HN Algolia,
             LinkedIn guest job search (demand signal)
  hydration  X status → cdn.syndication.twimg.com, fallback publish.twitter.com/oembed
             LinkedIn post → plain HTTP page, og:description (authwall/999 recorded)

Exit criterion (docs/08 Phase 0): >=60% of ideas yield >=10 hydrated X+LinkedIn posts
→ keyless only; otherwise the optional Apify tier is needed.

    SEARXNG_URL=http://127.0.0.1:8890 .venv/bin/python spikes/discovery_probe.py
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import statistics
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx

ROOT = Path(__file__).resolve().parents[1]
SEARXNG = os.getenv("SEARXNG_URL", "http://127.0.0.1:8890")
UA_BOT = "DenoResearchBot/0.1 (+https://deno.gtm; hello@deno.gtm)"
UA_BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
HYDRATE_PER_SOURCE = 10

IDEAS = [
    {"phrase": "linkedin ghostwriter", "subs": ["Entrepreneur", "LinkedInTips"]},
    {"phrase": "customer churn", "subs": ["SaaS", "startups"]},
    {"phrase": "cold email deliverability", "subs": ["coldemail", "sales"]},
    {"phrase": "invoice reminders", "subs": ["smallbusiness", "freelance"]},
    {"phrase": "meal prep app", "subs": ["MealPrepSunday", "EatCheapAndHealthy"]},
    {"phrase": "flaky tests", "subs": ["devops", "ExperiencedDevs"]},
    {"phrase": "rent tracking", "subs": ["Landlord", "realestateinvesting"]},
    {"phrase": "podcast editing", "subs": ["podcasting", "podcasts"]},
    {"phrase": "remote team onboarding", "subs": ["remotework", "humanresources"]},
    {"phrase": "Shopify returns", "subs": ["shopify", "ecommerce"]},
]

X_STATUS = re.compile(r"https?://(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")
LI_POST = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/posts/[^\s?#]+")


class Pacer:
    """Minimum spacing between requests to one host (politeness)."""

    def __init__(self, spacing: float) -> None:
        self.spacing = spacing
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.spacing
        if delay > 0:
            await asyncio.sleep(delay)


PACERS = {"searx": Pacer(2.0), "arctic": Pacer(1.0), "x": Pacer(0.5), "li": Pacer(2.5), "hn": Pacer(0.5)}


async def get(client: httpx.AsyncClient, pacer: str, url: str, **kw) -> tuple[httpx.Response | None, float]:
    await PACERS[pacer].wait()
    start = time.monotonic()
    try:
        res = await client.get(url, timeout=25, follow_redirects=True, **kw)
    except httpx.HTTPError:
        return None, time.monotonic() - start
    return res, time.monotonic() - start


async def searx(client: httpx.AsyncClient, query: str) -> list[str]:
    res, _ = await get(client, "searx", f"{SEARXNG}/search?q={quote_plus(query)}&format=json")
    if res is None or res.status_code != 200:
        return []
    return [r["url"] for r in res.json().get("results", [])]


def syndication_token(tweet_id: str) -> str:
    # Same derivation the embed widget uses; the endpoint rejects some ids without it.
    num = (int(tweet_id) / 1e15) * 3.141592653589793
    digits, whole = "0123456789abcdefghijklmnopqrstuvwxyz", int(num)
    out = ""
    while whole:
        whole, r = divmod(whole, 36)
        out = digits[r] + out
    return (out or "0").replace("0", "")


async def hydrate_x(client: httpx.AsyncClient, handle: str, tweet_id: str) -> dict:
    res, dt = await get(
        client, "x", f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token={syndication_token(tweet_id)}",
        headers={"User-Agent": UA_BROWSER},
    )
    if res is not None and res.status_code == 200 and res.text.strip().startswith("{"):
        data = res.json()
        if data.get("text"):
            return {"ok": True, "via": "syndication", "ms": int(dt * 1000), "likes": data.get("favorite_count")}
    res, dt2 = await get(client, "x", f"https://publish.twitter.com/oembed?url=https://x.com/{handle}/status/{tweet_id}")
    if res is not None and res.status_code == 200:
        return {"ok": True, "via": "oembed", "ms": int((dt + dt2) * 1000)}
    return {"ok": False, "status": res.status_code if res is not None else "err"}


async def hydrate_li(client: httpx.AsyncClient, url: str) -> dict:
    res, dt = await get(client, "li", url, headers={"User-Agent": UA_BROWSER, "Accept-Language": "en-US,en;q=0.9"})
    if res is None:
        return {"ok": False, "status": "err"}
    if res.status_code == 999 or "authwall" in str(res.url):
        return {"ok": False, "status": res.status_code, "authwall": True}
    m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', res.text)
    ok = res.status_code == 200 and bool(m and len(html.unescape(m.group(1))) > 40)
    return {"ok": ok, "status": res.status_code, "ms": int(dt * 1000)}


async def probe_idea(client: httpx.AsyncClient, idea: dict) -> dict:
    phrase = idea["phrase"]
    x_urls = [u for u in await searx(client, f'site:x.com "{phrase}"') if X_STATUS.search(u)]
    li_urls = [u for u in await searx(client, f'site:linkedin.com/posts "{phrase}"') if LI_POST.search(u)]
    x_ids = list(dict.fromkeys(X_STATUS.search(u).groups() for u in x_urls))
    li_posts = list(dict.fromkeys(LI_POST.search(u).group(0) for u in li_urls))

    x_hyd = await asyncio.gather(*(hydrate_x(client, h, i) for h, i in x_ids[:HYDRATE_PER_SOURCE]))
    li_hyd = await asyncio.gather(*(hydrate_li(client, u) for u in li_posts[:HYDRATE_PER_SOURCE]))

    reddit_hits = 0
    for sub in idea["subs"]:
        res, _ = await get(
            client, "arctic",
            f"https://arctic-shift.photon-reddit.com/api/comments/search?subreddit={sub}&body={quote_plus(phrase)}&limit=25",
            headers={"User-Agent": UA_BOT},
        )
        if res is not None and res.status_code == 200:
            reddit_hits += len(res.json().get("data") or [])

    res, _ = await get(client, "hn", f"https://hn.algolia.com/api/v1/search?query={quote_plus(phrase)}&hitsPerPage=50")
    hn_hits = res.json().get("nbHits", 0) if res is not None and res.status_code == 200 else 0

    res, _ = await get(
        client, "li",
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={quote_plus(phrase)}&start=0",
        headers={"User-Agent": UA_BROWSER},
    )
    jobs = len(re.findall(r'class="base-card', res.text)) if res is not None and res.status_code == 200 else 0

    return {
        "idea": phrase,
        "x_found": len(x_ids),
        "x_hydrated": sum(h["ok"] for h in x_hyd),
        "x_via": [h.get("via") for h in x_hyd if h["ok"]],
        "li_found": len(li_posts),
        "li_hydrated": sum(h["ok"] for h in li_hyd),
        "li_authwall": sum(bool(h.get("authwall")) for h in li_hyd),
        "li_status": [h.get("status") for h in li_hyd],
        "reddit_comments": reddit_hits,
        "hn_hits": hn_hits,
        "li_jobs_page1": jobs,
        "hydrate_ms": [h["ms"] for h in [*x_hyd, *li_hyd] if h.get("ms")],
    }


async def main() -> None:
    async with httpx.AsyncClient(headers={"User-Agent": UA_BOT}) as client:
        results = []
        for idea in IDEAS:
            r = await probe_idea(client, idea)
            print(json.dumps({k: v for k, v in r.items() if k != "hydrate_ms"}), flush=True)
            results.append(r)

    ok_ideas = sum((r["x_hydrated"] + r["li_hydrated"]) >= 10 for r in results)
    all_ms = [ms for r in results for ms in r["hydrate_ms"]]
    summary = {
        "ideas": len(results),
        "ideas_with_10_social_posts": ok_ideas,
        "share": round(ok_ideas / len(results), 2),
        "x_hydration_rate": round(sum(r["x_hydrated"] for r in results) / max(1, sum(min(r["x_found"], HYDRATE_PER_SOURCE) for r in results)), 2),
        "li_hydration_rate": round(sum(r["li_hydrated"] for r in results) / max(1, sum(min(r["li_found"], HYDRATE_PER_SOURCE) for r in results)), 2),
        "hydrate_p50_ms": int(statistics.median(all_ms)) if all_ms else None,
        "keyless_only": ok_ideas / len(results) >= 0.6,
    }
    print(json.dumps(summary))
    out = ROOT / "docs" / "spikes" / "discovery_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
