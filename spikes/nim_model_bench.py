"""Phase 0 spike: which NVIDIA NIM chat models are fast *and* usable today?

For each candidate model it measures, through LangChain's ChatNVIDIA (the
client the agents will use):
  1. streaming latency — time to first token and total, on a short analyst prompt
  2. structured output — `with_structured_output(PydanticModel)` success + latency

All requests share one rate limiter (default 36 req/min, under the 40 rpm cap).
Results go to docs/spikes/nim_models.json and a markdown table on stdout.

    .venv/bin/python spikes/nim_model_bench.py [model ...]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CANDIDATES = [
    # small / fast
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-nano-3-30b-a3b",
    "openai/gpt-oss-20b",
    "z-ai/glm-5.3-flash",
    "deepseek-ai/deepseek-v4.1-flash",
    "google/gemma-3-12b-it",
    "nv-mistralai/mistral-nemo-12b-instruct",
    "meta/llama-3.2-11b-vision-instruct",
    # strong
    "nvidia/nemotron-3-super-120b-a12b",
    "moonshotai/kimi-k2.6",
    "moonshotai/kimi-k3",
    "z-ai/glm-5.3",
    "google/gemma-4-31b-it",
    "mistralai/mistral-nemotron",
    "mistralai/mistral-large-2-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
]

PROMPT = (
    "You are a market analyst. In at most 3 short bullet points, what are the main risks of "
    "building a SaaS tool that scores social-media drafts for AI-sounding language?"
)


class Claim(BaseModel):
    text: str = Field(description="One falsifiable claim about the idea")
    stance: str = Field(description="supports | refutes | neutral")


class Claims(BaseModel):
    claims: list[Claim] = Field(description="Exactly 3 claims")


class RateLimiter:
    """Spaces request starts so at most `per_minute` begin in any minute."""

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / per_minute
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


def short_error(exc: BaseException) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    return msg.replace("\n", " ")[:140]


async def bench_stream(llm: ChatNVIDIA, limiter: RateLimiter, timeout: float) -> dict:
    await limiter.wait()
    start = time.monotonic()
    first = None
    text = ""

    async def run() -> None:
        nonlocal first, text
        async for chunk in llm.astream(PROMPT):
            if first is None and chunk.content:
                first = time.monotonic() - start
            text += chunk.content if isinstance(chunk.content, str) else ""

    try:
        await asyncio.wait_for(run(), timeout)
    except Exception as exc:  # noqa: BLE001 — recorded, not raised
        return {"ok": False, "error": short_error(exc), "elapsed": round(time.monotonic() - start, 1)}
    total = time.monotonic() - start
    return {"ok": bool(text.strip()), "ttft": round(first or total, 2), "total": round(total, 2), "chars": len(text)}


async def bench_structured(llm: ChatNVIDIA, limiter: RateLimiter, timeout: float) -> dict:
    await limiter.wait()
    start = time.monotonic()
    try:
        out = await asyncio.wait_for(
            llm.with_structured_output(Claims).ainvoke(f"{PROMPT}\nReturn exactly 3 claims."), timeout
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": short_error(exc), "elapsed": round(time.monotonic() - start, 1)}
    ok = isinstance(out, Claims) and len(out.claims) >= 1
    return {"ok": ok, "total": round(time.monotonic() - start, 2), "n": len(out.claims) if ok else 0}


async def bench_model(model: str, limiter: RateLimiter, timeout: float) -> dict:
    llm = ChatNVIDIA(model=model, api_key=os.environ["NVIDIA_NIM_API_KEY"], max_completion_tokens=400, temperature=0.2)
    stream = await bench_stream(llm, limiter, timeout)
    structured = await bench_structured(llm, limiter, timeout)
    return {"model": model, "stream": stream, "structured": structured}


async def main(models: list[str]) -> None:
    limiter = RateLimiter(int(os.getenv("NIM_RPM", "36")))
    timeout = float(os.getenv("BENCH_TIMEOUT", "90"))
    sem = asyncio.Semaphore(6)

    async def guarded(m: str) -> dict:
        async with sem:
            result = await bench_model(m, limiter, timeout)
            print(f"done {m}", file=sys.stderr, flush=True)
            return result

    results = await asyncio.gather(*(guarded(m) for m in models))

    out = ROOT / "docs" / "spikes" / "nim_models.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results}, indent=2))

    print("| model | stream ttft s | stream total s | structured | structured s | error |")
    print("|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: r["stream"].get("total", 999)):
        s, j = r["stream"], r["structured"]
        err = s.get("error") or j.get("error") or ""
        print(
            f"| {r['model']} | {s.get('ttft', '—')} | {s.get('total', '—')} | "
            f"{'yes' if j.get('ok') else 'NO'} | {j.get('total', '—')} | {err[:80]} |"
        )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or CANDIDATES))
