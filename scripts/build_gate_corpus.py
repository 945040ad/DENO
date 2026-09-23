"""Build the gates golden corpus.

- human.jsonl: 50 real self-posts from founder subreddits written before ChatGPT existed (before 2022-06),
  via Arctic Shift. Kept: 60–400 words, no links-only posts.
- slop.jsonl: 50 posts written by the LLM with a plain "write a LinkedIn/Reddit post about X" prompt,
  i.e. the default AI voice the gates must catch.

    uv run python scripts/build_gate_corpus.py
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import httpx

from deno_core.settings import get_settings
from deno_llm import Role, build_stack

OUT = Path(__file__).resolve().parents[1] / "evals" / "gates"
SUBS = ["startups", "SaaS", "Entrepreneur", "smallbusiness", "marketing", "sales", "ProductManagement", "webdev"]
TOPICS = [
    "lessons from our first 100 customers",
    "why we switched pricing models",
    "hiring our first engineer",
    "what I learned from a failed launch",
    "cold email that worked",
    "burnout as a solo founder",
    "raising a pre-seed round",
    "churn and how we fixed onboarding",
    "building in public",
    "firing a client",
    "our biggest product mistake",
    "going from agency to SaaS",
    "customer interviews",
    "remote team rituals",
    "SEO for a B2B startup",
    "the day our server went down",
    "saying no to features",
    "pricing for developers",
    "quitting my job to build",
    "growing a newsletter",
    "partnerships that failed",
    "choosing a tech stack",
    "running out of runway",
    "our first enterprise deal",
    "writing documentation users read",
]


async def human() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "DenoResearchBot/0.1 (eval corpus)"}) as c:
        for sub in SUBS:
            r = await c.get(
                "https://arctic-shift.photon-reddit.com/api/posts/search",
                params={"subreddit": sub, "before": "2022-06-01", "after": "2019-01-01", "limit": 100, "sort": "desc"},
            )
            for item in r.json().get("data") or []:
                body = str(item.get("selftext") or "")
                n = len(body.split())
                if 60 <= n <= 400 and body not in {"[removed]", "[deleted]"} and "http" not in body:
                    out.append({"source": f"r/{sub}", "text": body.strip(), "label": "human"})
            await asyncio.sleep(1.5)
    random.Random(7).shuffle(out)
    return out[:50]


async def slop() -> list[dict[str, str]]:
    llm = build_stack(get_settings()).router.chat(Role.FAST, temperature=0.9)
    out = []
    for i in range(50):
        platform = "LinkedIn" if i % 2 == 0 else "Reddit (r/startups)"
        topic = TOPICS[i % len(TOPICS)]
        post = await llm.ainvoke(f"Write an engaging {platform} post about {topic} for founders. 120-250 words.")
        out.append({"source": platform, "text": str(post.content).strip(), "label": "slop"})
        print(i, flush=True)
    return out


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not (OUT / "human.jsonl").exists():
        (OUT / "human.jsonl").write_text("".join(json.dumps(x) + "\n" for x in await human()))
    h = (OUT / "human.jsonl").read_text().splitlines()
    s = await slop()
    (OUT / "slop.jsonl").write_text("".join(json.dumps(x) + "\n" for x in s))
    print(len(h), len(s))


if __name__ == "__main__":
    asyncio.run(main())
