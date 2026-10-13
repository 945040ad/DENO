"""Supabase access-token verification and per-user project isolation.

All keys are generated locally; no network access.
"""

import hashlib
import hmac
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from deno_api.auth import AuthUser, InvalidToken, TokenVerifier, get_verifier
from deno_api.main import app
from tests.helpers.tokens import (
    AUDIENCE,
    EC_KEY,
    ISSUER,
    ROGUE_KEY,
    RSA_KEY,
    FakeJWKS,
    bearer,
    default_jwks,
    make_token,
)

LEGACY_SECRET = "legacy-hs256-secret-at-least-32-bytes!!"


@pytest.fixture
def jwks() -> FakeJWKS:
    return default_jwks()


@pytest.fixture
def verifier(jwks: FakeJWKS) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_client=jwks)


# ---- TokenVerifier ---------------------------------------------------------


def test_valid_es256_token_yields_user(verifier: TokenVerifier) -> None:
    sub = str(uuid.uuid4())
    user = verifier.verify(make_token(sub=sub))
    assert user == AuthUser(id=sub, email="founder@example.com", role="authenticated")


def test_valid_rs256_token_yields_user(verifier: TokenVerifier) -> None:
    user = verifier.verify(make_token(key=RSA_KEY, alg="RS256", kid="rsa-1"))
    assert user.role == "authenticated"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 120},  # beyond the 30 s leeway
        {"iss": "https://evil.supabase.co/auth/v1"},
        {"aud": "anon"},
        {"sub": None},
        {"exp": None},
    ],
    ids=["expired", "wrong-issuer", "wrong-audience", "missing-sub", "missing-exp"],
)
def test_rejects_bad_claims(verifier: TokenVerifier, overrides: dict) -> None:
    with pytest.raises(InvalidToken):
        verifier.verify(make_token(**overrides))


def test_rejects_token_signed_by_unknown_key(verifier: TokenVerifier) -> None:
    # Right kid, wrong private key.
    with pytest.raises(InvalidToken):
        verifier.verify(make_token(key=ROGUE_KEY))


def test_rejects_tampered_payload(verifier: TokenVerifier) -> None:
    header, _payload, signature = make_token().split(".")
    forged_payload = jwt.utils.base64url_encode(
        b'{"sub":"someone-else","iss":"%s","aud":"authenticated","exp":9999999999}' % ISSUER.encode()
    ).decode()
    with pytest.raises(InvalidToken):
        verifier.verify(f"{header}.{forged_payload}.{signature}")


def test_rejects_alg_none(verifier: TokenVerifier) -> None:
    token = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60},
        None,
        algorithm="none",
        headers={"kid": "ec-1"},
    )
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_rejects_hs256_when_no_legacy_secret(verifier: TokenVerifier) -> None:
    with pytest.raises(InvalidToken):
        verifier.verify(make_token(key=LEGACY_SECRET, alg="HS256", kid="legacy"))


def test_rejects_hs256_signed_with_public_key_bytes(jwks: FakeJWKS) -> None:
    # Algorithm-confusion attack: HMAC keyed with the public key PEM.
    verifier = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_client=jwks, legacy_secret=LEGACY_SECRET)
    public_pem = EC_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    # PyJWT refuses to sign with a PEM as an HMAC key, so forge the token by hand.

    def b64(raw: bytes) -> str:
        return jwt.utils.base64url_encode(raw).decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "ec-1"}).encode())
    payload = b64(json.dumps({"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60}).encode())
    signature = b64(hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    token = f"{header}.{payload}.{signature}"
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_accepts_hs256_with_legacy_secret(jwks: FakeJWKS) -> None:
    verifier = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_client=jwks, legacy_secret=LEGACY_SECRET)
    user = verifier.verify(make_token(key=LEGACY_SECRET, alg="HS256", kid="legacy"))
    assert user.email == "founder@example.com"


def test_rejects_garbage(verifier: TokenVerifier) -> None:
    with pytest.raises(InvalidToken):
        verifier.verify("not-a-jwt")


# ---- API integration ---------------------------------------------------------


@pytest.fixture
def api(verifier: TokenVerifier):
    app.dependency_overrides[get_verifier] = lambda: verifier
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_verifier, None)


def test_v1_routes_require_a_token(api: TestClient) -> None:
    res = api.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_401_without_details(api: TestClient) -> None:
    res = api.get("/api/v1/projects", headers=bearer(make_token(key=ROGUE_KEY)))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"
    assert res.json()["error"]["message"] == "Invalid or expired session"


# ---- two-factor enforcement --------------------------------------------------


def test_verifier_reads_assurance_level(verifier: TokenVerifier) -> None:
    assert verifier.verify(make_token()).aal == "aal1"
    assert verifier.verify(make_token(aal="aal2")).aal == "aal2"


class _FakeRequest:
    def __init__(self, sessionmaker: object | None) -> None:
        self.app = type("App", (), {"state": type("State", (), {"sessionmaker": sessionmaker})()})()


@pytest.mark.parametrize(
    ("aal", "enrolled", "blocked"),
    [("aal1", True, True), ("aal2", True, False), ("aal1", False, False)],
    ids=["password-only-with-2fa", "second-factor-verified", "no-2fa-enrolled"],
)
async def test_password_only_session_is_blocked_once_2fa_is_enrolled(
    monkeypatch: pytest.MonkeyPatch, aal: str, enrolled: bool, blocked: bool
) -> None:
    from deno_api import deps
    from deno_core.errors import MfaRequired

    async def has_factor(_maker: object, _uid: uuid.UUID) -> bool:
        return enrolled

    monkeypatch.setattr(deps, "_has_verified_factor", has_factor)
    sub = uuid.uuid4()
    user = AuthUser(id=str(sub), email=None, role="authenticated", aal=aal)
    request = _FakeRequest(sessionmaker=object())
    if blocked:
        with pytest.raises(MfaRequired):
            await deps.user_uuid(request, user)  # type: ignore[arg-type]
    else:
        assert await deps.user_uuid(request, user) == sub  # type: ignore[arg-type]


async def test_dev_user_and_missing_database_skip_the_2fa_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from deno_api import deps
    from deno_api.auth import DEV_USER

    async def boom(_maker: object, _uid: uuid.UUID) -> bool:
        raise AssertionError("should not query")

    monkeypatch.setattr(deps, "_has_verified_factor", boom)
    await deps.user_uuid(_FakeRequest(sessionmaker=object()), DEV_USER)  # type: ignore[arg-type]
    user = AuthUser(id=str(uuid.uuid4()), email=None, role="authenticated")
    await deps.user_uuid(_FakeRequest(sessionmaker=None), user)  # type: ignore[arg-type]
