"""Supabase Auth access-token verification.

Supabase owns sign-up, login, OAuth and sessions (ADR-003). The API only has
to answer "who is calling": it verifies the bearer access token against the
project's JWKS and uses the ``sub`` claim as the user id.

The signing algorithm is taken from the JWK the key id resolves to, never from
the token header, so a token can't downgrade itself to ``none`` or to HMAC
keyed with a public key. HS256 is accepted only when the legacy project secret
is explicitly configured (projects created before asymmetric keys).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from deno_core.settings import settings

ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256", "EdDSA"})


class InvalidToken(Exception):
    """The bearer token is missing, malformed, expired or not ours."""


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    role: str


class SigningKeyResolver(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class TokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_client: SigningKeyResolver,
        legacy_secret: str | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks_client
        self._legacy_secret = legacy_secret
        self._leeway = leeway_seconds

    def verify(self, token: str) -> AuthUser:
        try:
            header = jwt.get_unverified_header(token)
            key, algorithm = self._resolve_key(token, header)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except InvalidToken:
            raise
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise InvalidToken(str(exc)) from exc

        return AuthUser(
            id=str(claims["sub"]),
            email=claims.get("email"),
            role=str(claims.get("role", "authenticated")),
        )

    def _resolve_key(self, token: str, header: dict[str, Any]) -> tuple[Any, str]:
        if header.get("alg") == "HS256":
            if not self._legacy_secret:
                raise InvalidToken("HS256 tokens are not accepted")
            return self._legacy_secret, "HS256"

        signing_key = self._jwks.get_signing_key_from_jwt(token)
        algorithm = signing_key.algorithm_name
        if algorithm not in ASYMMETRIC_ALGORITHMS:
            raise InvalidToken(f"unsupported signing algorithm {algorithm}")
        return signing_key.key, algorithm


@lru_cache(maxsize=1)
def _build_verifier() -> TokenVerifier | None:
    if not settings.supabase_url:
        return None
    base = settings.supabase_url.rstrip("/")
    jwks_client = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=5)
    return TokenVerifier(
        issuer=f"{base}/auth/v1",
        audience=settings.supabase_jwt_audience,
        jwks_client=jwks_client,
        legacy_secret=settings.supabase_legacy_jwt_secret.get_secret_value() or None,
    )


def get_verifier() -> TokenVerifier | None:
    """None when Supabase isn't configured (local dev only; production refuses to start)."""
    return _build_verifier()


# Used when auth isn't configured, so the local prototype keeps working
# without a Supabase project. Never reachable in production (see config).
DEV_USER = AuthUser(id="00000000-0000-4000-8000-000000000001", email=None, role="authenticated")


def _bearer_token(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        return None
    return credentials.strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    request: Request,
    verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
) -> AuthUser:
    if verifier is None:
        return DEV_USER
    token = _bearer_token(request)
    if token is None:
        raise _unauthorized()
    try:
        # PyJWKClient fetches the JWKS with blocking urllib on a cache miss.
        return await run_in_threadpool(verifier.verify, token)
    except InvalidToken:
        raise _unauthorized() from None
