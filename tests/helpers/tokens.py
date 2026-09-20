"""Locally minted Supabase-style access tokens (no network)."""

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from deno_api.auth import TokenVerifier

ISSUER = "https://proj.supabase.co/auth/v1"
AUDIENCE = "authenticated"

EC_KEY = ec.generate_private_key(ec.SECP256R1())
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ROGUE_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeJWKS:
    """Stands in for PyJWKClient: resolves the token's kid to a public key."""

    def __init__(self) -> None:
        self.keys: dict[str, jwt.PyJWK] = {}

    def add(self, kid: str, private_key: Any, alg: str) -> None:
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        algo = jwt.get_algorithm_by_name(alg)
        jwk = algo.to_jwk(algo.prepare_key(public_pem), as_dict=True)
        jwk.update({"kid": kid, "alg": alg, "use": "sig"})
        self.keys[kid] = jwt.PyJWK(jwk)

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in self.keys:
            raise jwt.PyJWKClientError("unknown kid")
        return self.keys[kid]


def default_jwks() -> FakeJWKS:
    fake = FakeJWKS()
    fake.add("ec-1", EC_KEY, "ES256")
    fake.add("rsa-1", RSA_KEY, "RS256")
    return fake


def make_verifier(**kw: Any) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_client=default_jwks(), **kw)


def make_token(key: Any = EC_KEY, alg: str = "ES256", kid: str = "ec-1", **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 3600,
        "email": "founder@example.com",
        "role": "authenticated",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def user_token() -> tuple[uuid.UUID, dict[str, str]]:
    user_id = uuid.uuid4()
    return user_id, bearer(make_token(sub=str(user_id)))
