"""Validation graph nodes.

Rules every node follows:
- Evidence and findings are written to Postgres as they're produced; the report is rebuilt from the DB.
- Scraped text reaches a model only inside ``<untrusted_source>`` blocks; analysts have no tools.
- Claims may only cite source ids that were shown; numbers in a claim must appear in a cited source.
- Signals and the verdict band are computed in Python. The LLM only writes words around them.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import wraps
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send, interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deno_core.db import models as m
from deno_core.db.enums import Platform, ProjectStatus, Source, Stance, UsageKind, VerdictKind
from deno_core.db.repositories import UserScope, ensure_communities, record_source_health
from deno_core.gcp import searxng_auth_headers
from deno_core.logging import get_logger
from deno_core.observability import NODE_SECONDS, SOURCE_ERRORS, SOURCE_POSTS
from deno_core.runs import RunContext
from deno_core.settings import Settings
from deno_graphs.validation import schemas as sc
from deno_graphs.validation.signals import ClaimView, DocView, compute_signals
from deno_graphs.validation.state import AnalystResult, CollectResult, ValidationState
from deno_graphs.validation.verdict import coverage, decide
from deno_llm import (
    UNTRUSTED_RULE,
    BudgetExceeded,
    LLMStack,
    Role,
    SourceBlock,
    UngroundedOutput,
    assert_grounded,
    get_prompt,
)
from deno_llm import wrap_sources as wrap
from deno_rag import Analyst, Retriever, analyst_queries, ingest_posts
from deno_sources import AccessDenied, Fetcher, Post, SourceConfig, SourceName, SourceUnavailable, build_clients
from deno_sources.github import RepoUnavailable, fetch_repo, find_repo

log = get_logger(__name__)

EVIDENCE_WINDOW_DAYS = 730
PER_SOURCE_LIMIT = {  # results per query
    SourceName.REDDIT: 25,
    SourceName.HN: 20,
    SourceName.X: 10,
    SourceName.LINKEDIN_POSTS: 5,
    SourceName.LINKEDIN_JOBS: 25,
    SourceName.PRODUCTHUNT: 10,
}
MAX_POSTS_PER_SOURCE = 80
SOURCE_TIMEOUT_S = 90.0
ANALYST_FOCUS = {
    Analyst.PAIN: "is the problem real, frequent and painful for the people who have it?",
    Analyst.DEMAND: "are people actively looking for, asking for, or hacking together a solution?",
    Analyst.COMPETITORS: "which existing products or workarounds do people use, and what do they say about them?",
    Analyst.ICP: "who exactly has this problem (roles, company types, situations)?",
    Analyst.WTP: "is there evidence people pay, or would pay, to solve this? Budgets, prices, paid tools?",
    Analyst.RISKS: "evidence against the idea: people who don't care, are happy with what they have, or tried and quit",
    Analyst.COMMUNITIES: "where do these people gather and talk about this (communities, their tone and norms)?",
}
_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")


@dataclass
class GraphDeps:
    ctx: RunContext
    settings: Settings
    stack: LLMStack
    fetcher: Fetcher
    review_step: bool = True

    @property
    def run_id(self) -> uuid.UUID:
        return self.ctx.run_id

    def session(self) -> Any:
        return _Tx(self)


class _Tx:
    """``async with deps.session() as scope:`` — one committed transaction, tenant-scoped."""

    def __init__(self, deps: GraphDeps) -> None:
        self._deps = deps
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> UserScope:
        self._session = self._deps.ctx.sessionmaker()
        await self._session.__aenter__()
        await self._session.begin()
        return self._deps.ctx.scope(self._session)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session is None:
            return
        if exc_type is None:
            await self._session.commit()
        else:
            await self._session.rollback()
        await self._session.__aexit__(exc_type, exc, tb)


def deps_of(config: RunnableConfig) -> GraphDeps:
    return config["configurable"]["deps"]  # type: ignore[no-any-return]


Node = Callable[[Any, RunnableConfig], Awaitable[dict[str, Any]]]


def node(name: str) -> Callable[[Node], Any]:
    """Cancellation check + started/finished events + timing around every node."""

    def wrap_node(fn: Node) -> Node:
        @wraps(fn)
        async def inner(state: Any, config: RunnableConfig) -> dict[str, Any]:
            d = deps_of(config)
            await d.ctx.check_cancelled()
            label = name
            if isinstance(state, dict) and state.get("source"):
                label = f"{name}:{state['source']}"
            elif isinstance(state, dict) and state.get("analyst"):
                label = f"{name}:{state['analyst']}"
            await d.ctx.emit("node_started", node=label)
            started = time.monotonic()
            result = await fn(state, config)
            NODE_SECONDS.labels("validation", name).observe(time.monotonic() - started)
            await d.ctx.emit("node_finished", node=label, seconds=round(time.monotonic() - started, 1))
            return result

        return inner

    return wrap_node


# ---- planning ------------------------------------------------------------------------


@node("intake")
async def intake(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    idea = state["idea"].strip()
    if len(idea) < 5:
        return {"brief": {}, "rejected": "The idea is too short to research."}
    context, repo_problem = await _repo_context(d, idea)
    p = get_prompt("validation.intake")
    brief = await d.stack.router.structured(Role.FAST, sc.IdeaBrief, temperature=0).ainvoke(
        p.messages(idea=idea[:4000], context=context, untrusted_rule=UNTRUSTED_RULE), config=p.config()
    )
    if not brief.is_coherent or not brief.problem.strip() or not brief.keywords:
        reason = brief.reject_reason or "We couldn't find a clear problem and audience in this idea."
        if repo_problem:
            reason = f"{repo_problem}. Make it public, or describe the product in a few sentences. ({reason})"
        return {"brief": brief.model_dump(), "rejected": reason}
    return {"brief": brief.model_dump(), "rejected": None}


async def _repo_context(d: GraphDeps, idea: str) -> tuple[str, str | None]:
    """A linked GitHub repo's facts as an untrusted block (or "", plus why it couldn't be read)."""
    found = find_repo(idea)
    if not found:
        return "", None
    owner, name = found
    await d.ctx.emit("log", message=f"reading github.com/{owner}/{name} (README, description, topics)…")
    try:
        repo = await fetch_repo(owner, name, token=d.settings.github_token.get_secret_value())
    except RepoUnavailable as exc:
        log.info("repo_unavailable", repo=f"{owner}/{name}", reason=exc.reason)
        await d.ctx.emit("log", message=f"couldn't read the repo: {exc.reason}")
        return "", exc.reason
    log.info("repo_read", repo=repo.slug, readme_chars=len(repo.readme))
    await d.ctx.emit("log", message=f"read {repo.slug}: {len(repo.readme)} README characters")
    block = wrap([SourceBlock(id="repo", url=repo.url, source="github", text=repo.as_text())])
    return f"The founder's repository:\n{block}", None


@node("perspective_planner")
async def perspective_planner(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    b = state["brief"]
    p = get_prompt("validation.perspectives")
    out = await d.stack.router.structured(Role.FAST, sc.Perspectives).ainvoke(p.messages(**b), config=p.config())
    return {"perspectives": [x.model_dump() for x in out.perspectives[:6]]}


def _clean_queries(values: list[str], limit: int = 3) -> list[str]:
    out: list[str] = []
    for v in values:
        q = re.sub(r"[\"'“”#()]|\b(AND|OR|NOT)\b", " ", v)
        q = " ".join(q.split())[:80]
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[:limit]


@node("query_planner")
async def query_planner(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    b = state["brief"]
    questions = "\n".join(
        f"- ({pp['name']}) {q}" for pp in state.get("perspectives", []) for q in pp.get("questions", [])
    )
    p = get_prompt("validation.queries")
    plan = await d.stack.router.structured(Role.FAST, sc.QueryPlan, temperature=0).ainvoke(
        p.messages(
            problem=b["problem"],
            solution=b["solution"],
            audience=b["audience"],
            keywords=", ".join(b["keywords"]),
            questions=questions or "-",
        ),
        config=p.config(),
    )
    keywords = _clean_queries(b["keywords"], 3)

    def short(values: list[str], n: int = 3, words: int = 4) -> list[str]:
        """Keyword-style queries first: full-text search backends AND every word, so short wins."""
        pool = [q for q in _clean_queries(values, 10) if len(q.split()) <= words]
        return _clean_queries(pool, n)

    subs = [s.removeprefix("r/").strip() for s in plan.subreddits]
    return {
        "plan": {
            "subreddits": [s for s in dict.fromkeys(subs) if _SUBREDDIT.match(s)][:4],
            SourceName.REDDIT: short(keywords[:2] + plan.reddit, 2, 3),
            SourceName.HN: short(keywords[:2] + plan.hn, 3, 3),
            SourceName.X: short(plan.x + keywords, 2, 5),
            SourceName.LINKEDIN_POSTS: _clean_queries(plan.linkedin_posts, 2),
            SourceName.LINKEDIN_JOBS: _clean_queries(plan.linkedin_jobs, 2),
            SourceName.PRODUCTHUNT: _clean_queries([plan.competitors], 1),
        }
    }


def route_after_intake(state: ValidationState) -> str:
    return "insufficient" if state.get("rejected") else "perspective_planner"


def fan_out_collect(state: ValidationState) -> list[Send]:
    plan = state["plan"]
    return [
        Send("collect", {"source": str(source), "queries": plan.get(str(source), []), "subreddits": plan["subreddits"]})
        for source in PER_SOURCE_LIMIT
        if plan.get(str(source))
    ]


# ---- evidence ------------------------------------------------------------------------


@node("collect")
async def collect(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    source = SourceName(payload["source"])
    cfg = SourceConfig(
        searxng_url=d.settings.searxng_url,
        robots_opt_in=d.settings.sources_robots_opt_in,
        subreddits=payload.get("subreddits") or [],
        searxng_headers=searxng_auth_headers(d.settings),
    )
    since = datetime.now(UTC) - timedelta(days=EVIDENCE_WINDOW_DAYS)
    posts: list[Post] = []
    hits: list[tuple[Source, str, int]] = []
    error: str | None = None
    started = time.monotonic()
    budget = SOURCE_TIMEOUT_S * (2 if source == SourceName.REDDIT else 1)
    # Reddit discovery is per subreddit: one client per community so each call has its own timeout.
    if source == SourceName.REDDIT:
        subs = cfg.subreddits or ["SaaS", "startups"]
        targets = [
            (build_clients(SourceConfig(**{**vars(cfg), "subreddits": [sub]}), d.fetcher)[source], sub) for sub in subs
        ]
    else:
        targets = [(build_clients(cfg, d.fetcher)[source], "")]
    for query in payload["queries"]:
        for client, sub in targets:
            remaining = budget - (time.monotonic() - started)
            if remaining <= 5:
                error = error or "timeout"
                break
            try:
                found = await asyncio.wait_for(
                    client.search(query, since=since, limit=PER_SOURCE_LIMIT[source]), timeout=min(remaining, 30)
                )
            except AccessDenied:
                error = "blocked_by_policy"
                break
            except SourceUnavailable as exc:
                error = f"unavailable: {str(exc)[:80]}"
                continue
            except TimeoutError:
                error = "slow source (some queries timed out)"
                continue
            except Exception as exc:  # a broken source never aborts the run
                log.warning("collect_failed", source=source.value, error=type(exc).__name__)
                error = f"error: {type(exc).__name__}"
                continue
            hits.append((Source(source.value), f"{query} (r/{sub})" if sub else query, len(found)))
            posts.extend(found)
        if error == "blocked_by_policy":
            break
    unique = list({p.canonical_url: p for p in posts}.values())[:MAX_POSTS_PER_SOURCE]
    async with d.session() as scope:
        await scope.add_queries(d.run_id, hits)
    SOURCE_POSTS.labels(source.value).inc(len(unique))
    if error:
        SOURCE_ERRORS.labels(source.value, error.split(":")[0]).inc()
    await d.ctx.emit("source", source=source.value, count=len(unique), error=error)
    result: CollectResult = {
        "source": source.value,
        "queries": payload["queries"],
        "posts": [p.model_dump(mode="json") for p in unique],
        "error": error,
        "seconds": round(time.monotonic() - started, 1),
    }
    return {"collected": [result]}


@node("ingest")
async def ingest(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    posts = [Post.model_validate(p) for c in state.get("collected", []) for p in c["posts"]]
    async with d.session() as scope:
        report = await ingest_posts(scope, d.run_id, posts, d.stack.embedder)
        docs = await scope.list_documents(d.run_id)
        reddit = Counter(doc.community for doc in docs if doc.source == Source.REDDIT and doc.community)
        ids = await ensure_communities(scope.session, Platform.REDDIT, list(reddit))
        total = sum(reddit.values()) or 1
        await scope.set_run_communities(
            d.run_id, [(ids[name], round(n / total, 3), n) for name, n in reddit.most_common(15) if name in ids]
        )
        await record_source_health(scope.session, d.fetcher.drain_health())
    return {
        "ingest": {
            "received": report.received,
            "stored": report.stored,
            "chunks": report.chunks,
            "duplicates": report.duplicates,
            "skipped_language": report.skipped_language,
        }
    }


@node("coverage_check")
async def coverage_check(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    async with d.session() as scope:
        docs = await scope.list_documents(d.run_id)
    by_source = Counter(doc.source.value for doc in docs)
    recent_cut = datetime.now(UTC) - timedelta(days=365)
    recent = sum(1 for doc in docs if doc.published_at and doc.published_at >= recent_cut)
    cov = coverage(by_source, recent)
    errors = {c["source"]: c["error"] for c in state.get("collected", []) if c["error"]}
    return {"coverage": {**vars(cov), "source_errors": errors}}


def route_after_coverage(state: ValidationState) -> list[Send] | str:
    if not state["coverage"]["ok"]:
        return "insufficient"
    return [Send("analyst", {"analyst": a.value, "brief": state["brief"]}) for a in Analyst]


# ---- analysis ------------------------------------------------------------------------


def numbers_in(text: str) -> set[str]:
    return {n.strip("$%").replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def unsupported_numbers(claim: str, sources: list[str]) -> set[str]:
    """Numbers in a claim that don't appear in any cited source text (years and small ordinals included)."""
    available: set[str] = set()
    for s in sources:
        available |= numbers_in(s)
    return {n for n in numbers_in(claim) if n and n not in available}


@node("analyst")
async def analyst(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    who = Analyst(payload["analyst"])
    b = payload["brief"]
    queries = analyst_queries(who, problem=b["problem"], solution=b["solution"], audience=b["audience"])
    async with d.session() as scope:
        await scope.delete_claims(d.run_id, who.value)
        hits = await Retriever(scope, d.stack.embedder, d.stack.reranker).retrieve_many(queries, d.run_id, top_n=16)
    result: AnalystResult = {"analyst": who.value, "claim_ids": []}
    if not hits:
        return {"analysts": [result]}

    labelled = {f"S{i + 1}": h for i, h in enumerate(hits)}
    blocks = [
        SourceBlock(
            id=label,
            url=h.url,
            source=f"{h.source.value}{' ' + h.community if h.community else ''}",
            text=h.text[:1500],
        )
        for label, h in labelled.items()
    ]
    p = get_prompt("validation.analyst")
    try:
        out = await analyst_call(d, p, who, b, blocks)
    except BudgetExceeded:
        raise
    except Exception as exc:  # one analyst failing leaves a gap, not a failed run
        log.warning("analyst_failed", analyst=who.value, error=type(exc).__name__)
        await d.ctx.emit("log", message=f"The {who.value} analyst failed; its section will be empty.")
        return {"analysts": [result]}
    urls = {h.url for h in hits}
    return await _store_claims(d, who, out, labelled, urls, result)


async def analyst_call(
    d: GraphDeps, p: Any, who: Analyst, b: dict[str, Any], blocks: list[SourceBlock]
) -> sc.AnalystOutput:
    return await d.stack.router.structured(Role.STRONG, sc.AnalystOutput).ainvoke(
        p.messages(
            analyst=who.value,
            focus=ANALYST_FOCUS[who],
            untrusted_rule=UNTRUSTED_RULE,
            problem=b["problem"],
            solution=b["solution"],
            audience=b["audience"],
            sources=wrap(blocks),
        ),
        config=p.config(analyst=who.value),
    )


async def _store_claims(
    d: GraphDeps, who: Analyst, out: sc.AnalystOutput, labelled: dict[str, Any], urls: set[str], result: AnalystResult
) -> dict[str, Any]:
    async with d.session() as scope:
        for draft in out.claims[:5]:
            cited = [labelled[s] for s in dict.fromkeys(draft.source_ids) if s in labelled][:3]
            reason: str | None = None
            if not cited:
                reason = "no valid source ids"
            elif bad := unsupported_numbers(draft.claim, [c.text for c in cited]):
                reason = f"numbers not in sources: {sorted(bad)[:3]}"
            else:
                try:
                    assert_grounded(draft.claim, allowed_urls=urls)
                except UngroundedOutput as exc:
                    reason = str(exc)
            claim = await scope.add_claim(
                d.run_id,
                analyst=who.value,
                text=draft.claim.strip()[:600],
                stance=Stance(draft.stance),
                chunk_ids=[c.chunk_id for c in cited],
                dropped=reason is not None,
            )
            if reason:
                log.info("claim_dropped", analyst=who.value, reason=reason)
            else:
                result["claim_ids"].append(str(claim.id))
    return {"analysts": [result]}


_JUDGE_LINE = re.compile(r"^\W*(P\d+)\W*\|\s*(SUPPORTED|UNSUPPORTED)\s*\|\s*([01](?:\.\d+)?)", re.MULTILINE)


async def _judge(d: GraphDeps, pairs: list[tuple[str, str, str]]) -> dict[str, tuple[bool, float]]:
    """(pair_id, claim, source_text) → {pair_id: (entailed, score)}; batches of 8 judged concurrently.

    The judge answers in a strict line protocol ("P3 | SUPPORTED | 0.9") instead of guided JSON: with guided
    decoding Nemotron stalls at the true/false slot and emits whitespace until the token limit (seen live on
    most batches). A missing or malformed line leaves that pair unverified, which drops the claim.
    """
    p = get_prompt("validation.citation_judge")
    runnable = d.stack.router.chat(Role.JUDGE, temperature=0)

    async def batch(items: list[tuple[str, str, str]]) -> dict[str, tuple[bool, float]]:
        text = "\n\n".join(
            f"[{pid}]\nCLAIM: {claim}\n" + wrap([SourceBlock(id=pid, url="", source="", text=src[:1500])])
            for pid, claim, src in items
        )
        try:
            out = await runnable.ainvoke(p.messages(untrusted_rule=UNTRUSTED_RULE, pairs=text), config=p.config())
        except BudgetExceeded:
            raise
        except Exception as exc:  # unverifiable = unverified (conservative), never a crash
            log.warning("citation_judge_batch_failed", error=type(exc).__name__, pairs=len(items))
            return {}
        wanted = {pid for pid, _, _ in items}
        return {
            m.group(1): (m.group(2) == "SUPPORTED", min(1.0, float(m.group(3))))
            for m in _JUDGE_LINE.finditer(str(out.content))
            if m.group(1) in wanted
        }

    results = await asyncio.gather(*(batch(pairs[i : i + 8]) for i in range(0, len(pairs), 8)))
    return {k: v for r in results for k, v in r.items()}


async def _validate_claims(d: GraphDeps, claim_ids: list[uuid.UUID]) -> dict[str, int]:
    async with d.session() as scope:
        claims = {c.id: c for c in await scope.list_claims(d.run_id) if c.id in set(claim_ids)}
        citations = await scope.list_citations(list(claims))
        chunks = {c.id: c for c in await scope.get_chunks([c.chunk_id for c in citations])}
    pairs, index = [], {}
    for i, cit in enumerate(citations):
        pid = f"P{i + 1}"
        index[pid] = cit.id
        pairs.append((pid, claims[cit.claim_id].text, chunks[cit.chunk_id].text))
    verdicts = await _judge(d, pairs) if pairs else {}
    by_id = {index[pid]: v for pid, v in verdicts.items() if pid in index}
    kept = dropped = 0
    async with d.session() as scope:
        for cit in await scope.list_citations(list(claims)):
            entailed, score = by_id.get(cit.id, (False, 0.0))
            cit.verified = bool(entailed and score >= 0.5)
            cit.entailment_score = float(score)
        await scope.session.flush()
        verified_claims = {cit.claim_id for cit in await scope.list_citations(list(claims)) if cit.verified}
        for claim in await scope.list_claims(d.run_id):
            if claim.id in claims:
                if claim.id in verified_claims:
                    kept += 1
                else:
                    claim.dropped = True
                    dropped += 1
    return {"checked_pairs": len(pairs), "kept": kept, "dropped": dropped}


@node("citation_validator")
async def citation_validator(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    ids = [uuid.UUID(cid) for a in state.get("analysts", []) for cid in a["claim_ids"]]
    summary = await _validate_claims(d, ids)
    return {"validation": summary}


async def _views(scope: UserScope, run_id: uuid.UUID) -> tuple[list[DocView], list[ClaimView], list[m.Claim]]:
    docs = await scope.list_documents(run_id)
    claims = await scope.list_claims(run_id)
    citations = [c for c in await scope.list_citations([c.id for c in claims]) if c.verified]
    chunk_doc = {c.id: c.document_id for c in await scope.get_chunks([c.chunk_id for c in citations])}
    docs_by_claim: dict[uuid.UUID, set[str]] = {}
    for cit in citations:
        docs_by_claim.setdefault(cit.claim_id, set()).add(str(chunk_doc[cit.chunk_id]))
    doc_views = [
        DocView(
            id=str(doc.id),
            source=doc.source.value,
            community=doc.community,
            published_at=doc.published_at,
            engagement={k: int(v) for k, v in (doc.engagement or {}).items() if isinstance(v, int)},
            text=doc.raw_text or "",
        )
        for doc in docs
    ]
    claim_views = [
        ClaimView(
            id=str(c.id), analyst=c.analyst, stance=c.stance.value, document_ids=tuple(docs_by_claim.get(c.id, ()))
        )
        for c in claims
        if c.id in docs_by_claim
    ]
    return doc_views, claim_views, claims


@node("signal_scorer")
async def signal_scorer(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    async with d.session() as scope:
        docs, claims, _ = await _views(scope, d.run_id)
        values = compute_signals(docs, claims)
        await scope.replace_signals(d.run_id, [(s.name, s.value, s.method, s.inputs) for s in values])
    return {"signals": {s.name: s.value for s in values}}


def _claim_lines(claims: list[m.Claim]) -> tuple[str, dict[str, uuid.UUID]]:
    refs = {f"C{i + 1}": c.id for i, c in enumerate(claims)}
    lines = "\n".join(
        f"{label} [{c.analyst}, {c.stance.value}] {c.text}" for label, c in zip(refs, claims, strict=True)
    )
    return lines, refs


@node("critic")
async def critic(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    async with d.session() as scope:
        _, views, claims = await _views(scope, d.run_id)
    verified = {v.id for v in views}
    claims = [c for c in claims if str(c.id) in verified]
    if not claims:
        return {"critique": [], "critic_round": state.get("critic_round", 0) + 1}
    lines, refs = _claim_lines(claims)
    signals = "\n".join(f"{k}: {v}" for k, v in state.get("signals", {}).items())
    p = get_prompt("validation.critic")
    try:
        out = await d.stack.router.structured(Role.JUDGE, sc.Critique, temperature=0).ainvoke(
            p.messages(claims=lines, signals=signals), config=p.config()
        )
    except BudgetExceeded:
        raise
    except Exception as exc:  # the critic is an extra check; without it the claims stand as validated
        log.warning("critic_failed", error=type(exc).__name__)
        return {"critique": [], "critic_round": 99}
    issues = [{"claim_id": str(refs[i.claim_id]), "problem": i.problem} for i in out.issues if i.claim_id in refs]
    return {"critique": issues, "critic_round": state.get("critic_round", 0) + 1}


def route_after_critic(state: ValidationState) -> str:
    return "refiner" if state.get("critique") and state.get("critic_round", 0) <= 2 else "verdict"


@node("refiner")
async def refiner(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    flagged = {uuid.UUID(i["claim_id"]): i["problem"] for i in state.get("critique", [])}
    async with d.session() as scope:
        claims = [c for c in await scope.list_claims(d.run_id) if c.id in flagged]
        citations = await scope.list_citations([c.id for c in claims])
        chunks = {c.id: c.text for c in await scope.get_chunks([c.chunk_id for c in citations])}
    if not claims:
        return {"critique": []}
    sources_by_claim: dict[uuid.UUID, list[str]] = {}
    for cit in citations:
        sources_by_claim.setdefault(cit.claim_id, []).append(chunks[cit.chunk_id])
    refs = {f"C{i + 1}": c for i, c in enumerate(claims)}
    items = "\n\n".join(
        f"{label}: {c.text}\nPROBLEM: {flagged[c.id]}\n"
        + wrap(
            [
                SourceBlock(id=f"{label}-S{j + 1}", url="", source="", text=t[:1200])
                for j, t in enumerate(sources_by_claim.get(c.id, []))
            ]
        )
        for label, c in refs.items()
    )
    p = get_prompt("validation.refiner")
    try:
        out = await d.stack.router.structured(Role.STRONG, sc.Refinement, temperature=0).ainvoke(
            p.messages(untrusted_rule=UNTRUSTED_RULE, items=items), config=p.config()
        )
    except BudgetExceeded:
        raise
    except Exception as exc:  # over-reaching claims are dropped rather than kept unrefined
        log.warning("refiner_failed", error=type(exc).__name__)
        async with d.session() as scope:
            for c in claims:
                row = await scope.session.get(m.Claim, c.id)
                if row is not None and row.user_id == scope.user_id:
                    row.dropped = True
        return {"critique": []}
    changed: list[uuid.UUID] = []
    async with d.session() as scope:
        for rc in out.claims:
            original = refs.get(rc.claim_id)
            if original is None or unsupported_numbers(rc.claim, sources_by_claim.get(original.id, [])):
                continue
            row = await scope.session.get(m.Claim, original.id)
            if row is not None and row.user_id == scope.user_id:
                row.text, row.stance = rc.claim.strip()[:600], Stance(rc.stance)
                changed.append(row.id)
    if changed:
        await _validate_claims(d, changed)
    return {"critique": []}


# ---- verdict -------------------------------------------------------------------------

_SLOP = re.compile(
    r"\b(delve|tapestry|landscape|crucial|robust|seamless|game[- ]changer|leverage|in conclusion|"
    r"it'?s (important|worth) (to note|noting)|navigat(e|ing) the|ever[- ]evolving|unlock)\b|—",
    re.IGNORECASE,
)


def _fallback_rationale(band: Any, cov: dict[str, Any]) -> str:
    reasons = "; ".join(band.reasons)
    gap = cov["gaps"][0] if cov.get("gaps") else "more posts from the buyers themselves"
    return f"Verdict: {band.verdict.replace('_', ' ')}. Why: {reasons}. What would change it: {gap}."


@node("verdict")
async def verdict(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    b = state["brief"]
    async with d.session() as scope:
        _, views, claims = await _views(scope, d.run_id)
    verified = {v.id for v in views}
    claims = [c for c in claims if str(c.id) in verified]
    cov_raw = dict(state["coverage"])
    cov = coverage(cov_raw["by_source"], int(cov_raw["recent_share"] * cov_raw["documents"]))
    signals = state.get("signals", {})
    band = decide(cov, views, signals)
    lines, refs = _claim_lines(claims)
    rationale: str | None = None
    if band.verdict != "insufficient_evidence" and claims:
        p = get_prompt("validation.rationale")
        try:
            out = await d.stack.router.structured(Role.STRONG, sc.Rationale).ainvoke(
                p.messages(
                    problem=b["problem"],
                    solution=b["solution"],
                    audience=b["audience"],
                    verdict=band.verdict,
                    confidence=band.confidence,
                    reasons="; ".join(band.reasons),
                    signals="\n".join(f"{k}: {v}" for k, v in signals.items()),
                    claims=lines,
                ),
                config=p.config(),
            )
            rationale = re.sub(r"\s*[—–]\s*", ", ", out.rationale.strip())
        except Exception as exc:
            log.warning("rationale_failed", error=type(exc).__name__)
        if rationale:
            allowed = numbers_in(lines) | {n for v in signals.values() for n in numbers_in(str(v))}
            allowed |= numbers_in(str(band.confidence)) | numbers_in(" ".join(band.reasons))
            unknown_refs = set(re.findall(r"\[(C\d+)\]", rationale)) - set(refs)
            stray = numbers_in(rationale) - allowed - {str(i) for i in range(1, len(refs) + 1)}
            slop = _SLOP.search(rationale)
            if stray or unknown_refs or slop:
                log.info(
                    "rationale_rejected_using_fallback",
                    numbers=sorted(stray)[:5],
                    refs=sorted(unknown_refs)[:5],
                    slop=slop.group(0) if slop else None,
                )
                rationale = None
    rationale = rationale or _fallback_rationale(band, cov_raw)
    async with d.session() as scope:
        await scope.upsert_verdict(
            d.run_id,
            verdict=VerdictKind(band.verdict),
            confidence=band.confidence,
            coverage={**cov_raw, "claim_refs": {k: str(v) for k, v in refs.items()}},
            reasons=band.reasons,
            rationale=rationale,
        )
    return {"verdict": {"verdict": band.verdict, "confidence": band.confidence, "reasons": band.reasons}}


@node("insufficient")
async def insufficient(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    """Honest short-circuit: unclear idea, or not enough public evidence. No invented verdict."""
    d = deps_of(config)
    rejected = state.get("rejected")
    reasons: list[str]
    if rejected:
        cov: dict[str, Any] = {"gaps": [rejected], "ok": False}
        reasons = [rejected]
    else:
        cov = dict(state.get("coverage", {}))
        reasons = list(cov.get("gaps") or ["not enough public evidence"])
    text = "Not enough evidence to judge this idea. " + " ".join(
        r[:1].upper() + r[1:].rstrip(".") + "." for r in reasons[:3]
    )
    async with d.session() as scope:
        await scope.upsert_verdict(
            d.run_id,
            verdict=VerdictKind.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            coverage=cov,
            reasons=reasons,
            rationale=text,
        )
    return {"verdict": {"verdict": "insufficient_evidence", "confidence": 0.0, "reasons": reasons}}


@node("account")
async def account(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    """Token/cost ledger + source health, written before the review pause so nothing is lost."""
    d = deps_of(config)
    usage = d.stack.usage.summary()
    async with d.session() as scope:
        if usage["total_tokens"]:
            await scope.record_usage(
                UsageKind.LLM_TOKENS,
                units=int(usage["total_tokens"]),
                cost_usd=float(usage["cost_usd"]),
                run_id=d.run_id,
                by_model=usage["by_model"],
            )
        run = await scope.get_run(d.run_id)
        run.cost_usd = run.cost_usd + Decimal(str(usage["cost_usd"]))
        await record_source_health(scope.session, d.fetcher.drain_health())
    d.stack.usage.by_model.clear()
    return {}


def route_after_account(state: ValidationState) -> str:
    return "review" if state.get("verdict", {}).get("verdict") != "insufficient_evidence" else "finalize"


async def review(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    """Pause for the founder: they can flag claims as wrong (stored for evals), then the run finishes."""
    d = deps_of(config)
    if not d.review_step:
        return {"review": {"skipped": True}}
    answer = interrupt({"kind": "review", "message": "Flag any claim that is wrong, then continue."})
    return {"review": answer if isinstance(answer, dict) else {"answer": answer}}


@node("finalize")
async def finalize(state: ValidationState, config: RunnableConfig) -> dict[str, Any]:
    d = deps_of(config)
    async with d.session() as scope:
        run = await scope.get_run(d.run_id)
        project = await scope.get_project(run.project_id)
        if project.status != ProjectStatus.ARCHIVED:
            project.status = ProjectStatus.VALIDATED
        flagged = await scope.session.scalar(
            select(m.Claim.id).where(m.Claim.run_id == d.run_id, m.Claim.flagged_wrong.is_(True)).limit(1)
        )
    return {"review": {**state.get("review", {}), "flagged_any": flagged is not None}}
