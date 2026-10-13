"""Maintenance endpoints for Cloud Scheduler on the free-tier deploy (docs/09 §4.2).

Each call carries a Google-signed OIDC token for our scheduler service account.
The token is checked against Google's JWKS, the expected audience and that exact
service account, so a leaked URL alone can't trigger anything. With the cron
settings empty the endpoints answer 404 and the taskiq scheduler does this work.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deno_api.auth import SigningKeyResolver
from deno_api.deps import get_sessionmaker
from deno_core import maintenance
from deno_core.settings import Settings, get_settings

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})

router = APIRouter(prefix="/internal/cron", tags=["ops"], include_in_schema=False)


@lru_cache(maxsize=1)
def google_jwks() -> SigningKeyResolver:
    return jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)


def verify_scheduler_token(token: str, audience: str, service_account: str, jwks: SigningKeyResolver) -> None:
    """Raises jwt.PyJWTError / ValueError unless this is the scheduler's token for us."""
    signing_key = jwks.get_signing_key_from_jwt(token)
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        leeway=30,
        options={"require": ["exp", "iat", "iss", "aud", "email"]},
    )
    if claims["iss"] not in GOOGLE_ISSUERS:
        raise ValueError("issuer is not Google")
    if claims["email"] != service_account or claims.get("email_verified") is not True:
        raise ValueError("token is not from the scheduler service account")


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


async def require_scheduler(request: Request) -> None:
    settings = _settings(request)
    if not (settings.cron_oidc_audience and settings.cron_service_account):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing scheduler token.")
    try:
        # PyJWKClient fetches Google's keys with blocking urllib on a cache miss.
        await run_in_threadpool(
            verify_scheduler_token,
            token.strip(),
            settings.cron_oidc_audience,
            settings.cron_service_account,
            google_jwks(),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid scheduler token.") from None


Maker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]


@router.post("/purge", dependencies=[Depends(require_scheduler)])
async def purge(maker: Maker) -> dict[str, int]:
    return {"purged": await maintenance.purge_old_scraped_text(maker)}


@router.post("/requeue", dependencies=[Depends(require_scheduler)])
async def requeue(maker: Maker) -> dict[str, int]:
    return {"requeued": await maintenance.requeue_stale_runs(maker)}
