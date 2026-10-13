"""Google Cloud credentials and Cloud Run Jobs for the free-tier deploy (docs/09).

On Cloud Run the metadata server hands out tokens for the service's own service
account, so no key files or secrets are needed. Tokens are cached until shortly
before they expire.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import httpx

from deno_core.errors import UpstreamUnavailable
from deno_core.settings import Settings

METADATA_ACCOUNT = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
RUN_API = "https://run.googleapis.com/v2"
# Refresh this long before expiry so a token never expires mid-request.
REFRESH_MARGIN_S = 300
# Google ID tokens live one hour; the metadata endpoint doesn't say so explicitly.
ID_TOKEN_LIFETIME_S = 3600

_access: tuple[str, float] | None = None
_id_tokens: dict[str, tuple[str, float]] = {}


def _metadata_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"Metadata-Flavor": "Google"}, timeout=5)


async def access_token() -> str:
    """OAuth access token for Google APIs (here: the Cloud Run Admin API)."""
    global _access
    if _access and _access[1] > time.monotonic():
        return _access[0]
    async with _metadata_client() as client:
        res = await client.get(f"{METADATA_ACCOUNT}/token")
    if res.status_code != 200:
        raise UpstreamUnavailable("Google metadata server refused a token.")
    body = res.json()
    _access = (str(body["access_token"]), time.monotonic() + int(body["expires_in"]) - REFRESH_MARGIN_S)
    return _access[0]


async def id_token(audience: str) -> str:
    """ID token that a private Cloud Run service with this audience (its URL) accepts."""
    hit = _id_tokens.get(audience)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    async with _metadata_client() as client:
        res = await client.get(f"{METADATA_ACCOUNT}/identity", params={"audience": audience, "format": "full"})
    if res.status_code != 200:
        raise UpstreamUnavailable("Google metadata server refused an ID token.")
    token = res.text.strip()
    _id_tokens[audience] = (token, time.monotonic() + ID_TOKEN_LIFETIME_S - REFRESH_MARGIN_S)
    return token


def searxng_auth_headers(settings: Settings) -> Callable[[], Awaitable[dict[str, str]]] | None:
    """Header provider for a private SearXNG Cloud Run service, or None when it's not private."""
    if not settings.searxng_gcp_auth:
        return None
    audience = settings.searxng_url.rstrip("/")

    async def headers() -> dict[str, str]:
        return {"Authorization": f"Bearer {await id_token(audience)}"}

    return headers


async def run_cloud_run_job(job: str, args: list[str], *, client: httpx.AsyncClient | None = None) -> str:
    """Start one execution of `job` (projects/…/locations/…/jobs/…) with these container args.

    Returns the long-running operation name. The execution itself is retried by
    Cloud Run (the job's --max-retries) when the process exits non-zero.
    """
    headers = {"Authorization": f"Bearer {await access_token()}"}
    body = {"overrides": {"containerOverrides": [{"args": args}]}}
    own = client is None
    http = client or httpx.AsyncClient(timeout=15)
    try:
        res = await http.post(f"{RUN_API}/{job}:run", json=body, headers=headers)
    finally:
        if own:
            await http.aclose()
    if res.status_code >= 300:
        raise UpstreamUnavailable("Couldn't start the background job. Try again shortly.")
    return str(res.json().get("name", ""))
