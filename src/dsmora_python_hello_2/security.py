import json
import secrets
import time
from functools import lru_cache
from typing import Any

import jwt
import redis
from cryptography.hazmat.primitives import serialization
from jwt import PyJWKClient

from .web_config import settings

SCOPES = "weather:read plans:read plans:write"


@lru_cache
def database() -> redis.Redis:
    return redis.Redis.from_url(
        settings.redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
    )


@lru_cache
def signing_key() -> bytes:
    return settings.private_key.read_bytes()


@lru_cache
def key_client() -> PyJWKClient:
    return PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=300, timeout=5)


def jwks() -> dict[str, Any]:
    key = serialization.load_pem_private_key(signing_key(), password=None).public_key()
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key))
    return {"keys": [{**public, "kid": "local-1", "use": "sig", "alg": "RS256"}]}


def issue(subject: str, sid: str, audience: str, scopes: str = "") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": settings.issuer,
            "sub": subject,
            "sid": sid,
            "aud": audience,
            "iat": now,
            "exp": now + (settings.session_ttl if audience == "backend" else settings.delegated_ttl),
            "jti": secrets.token_urlsafe(24),
            "scope": scopes,
        },
        signing_key(),
        algorithm="RS256",
        headers={"kid": "local-1"},
    )


def verify(token: str, audience: str) -> dict[str, Any]:
    key = key_client().get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token, key, algorithms=["RS256"], issuer=settings.issuer, audience=audience,
        options={"require": ["iss", "sub", "sid", "aud", "iat", "exp", "jti"]},
    )
    session = active_session(claims["sid"])
    if session["sub"] != claims["sub"]:
        raise jwt.InvalidTokenError("La identidad no coincide con la sesion.")
    if audience == "mcp" and not session["authenticated"]:
        raise jwt.InvalidTokenError("MCP requiere una cuenta autenticada.")
    return claims


def active_session(sid: str) -> dict[str, Any]:
    if not isinstance(sid, str) or len(sid) > 100:
        raise jwt.InvalidTokenError("Sesion invalida.")
    raw = database().get(f"session:{sid}")
    if raw is None:
        raise jwt.InvalidTokenError("La sesion ha caducado o se ha cerrado.")
    return json.loads(raw)


def new_session(subject: str, email: str | None = None) -> tuple[str, dict[str, Any]]:
    sid = secrets.token_urlsafe(32)
    session = {
        "sub": subject, "email": email, "authenticated": email is not None,
        "csrf": secrets.token_urlsafe(32),
    }
    database().setex(f"session:{sid}", settings.session_ttl, json.dumps(session))
    return sid, session


def rate_limit(key: str, maximum: int, seconds: int) -> bool:
    count = database().eval(
        "local n=redis.call('INCR',KEYS[1]); "
        "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
        1, f"rate:{key}", seconds,
    )
    return int(count) <= maximum
