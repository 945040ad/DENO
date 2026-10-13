from typing import Any

import pytest

from deno_core.errors import RateLimited, UpstreamUnavailable
from deno_llm import retrieval_models
from deno_llm.retrieval_models import NimEmbedder, NimReranker, _raise_nim


class _FailingClient:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def model_copy(self, update: dict[str, Any]) -> "_FailingClient":
        return self

    async def acompress_documents(self, documents: Any, query: str) -> Any:
        self.calls += 1
        raise Exception(self.message)  # bare Exception, like langchain_nvidia_ai_endpoints

    async def aembed_query(self, text: str) -> Any:
        raise Exception(self.message)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(retrieval_models.asyncio, "sleep", instant)


async def test_rerank_outage_keeps_fused_order() -> None:
    reranker = NimReranker(api_key="k", model="m", base_url="http://nim.invalid/v1")
    client = _FailingClient("[502] Bad Gateway\nUpstream request failed.")
    reranker._client = client  # type: ignore[assignment]
    ranked = await reranker.rerank("q", ["a", "b", "c", "d"], top_n=3)
    assert [i for i, _ in ranked] == [0, 1, 2]
    assert [s for _, s in ranked] == sorted((s for _, s in ranked), reverse=True)
    assert client.calls == retrieval_models.RERANK_ATTEMPTS


@pytest.mark.parametrize(
    ("message", "expected"),
    [("[502] Bad Gateway", UpstreamUnavailable), ("[503] busy", UpstreamUnavailable), ("[429] Too Many", RateLimited)],
)
async def test_embed_transient_errors_become_retryable(message: str, expected: type[Exception]) -> None:
    embedder = NimEmbedder(api_key="k", model="m", base_url="http://nim.invalid/v1")
    embedder._client = _FailingClient(message)  # type: ignore[assignment]
    with pytest.raises(expected):
        await embedder.embed_query("x")


def test_client_errors_pass_through() -> None:
    err = Exception("[400] Bad Request")
    with pytest.raises(Exception, match=r"\[400\]") as info:
        _raise_nim(err)
    assert info.value is err
