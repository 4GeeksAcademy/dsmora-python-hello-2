import logging
from contextvars import ContextVar

import jwt
import redis
from fastmcp.exceptions import ToolError
from mcpauth.exceptions import MCPAuthTokenVerificationException, MCPAuthTokenVerificationExceptionCode
from mcpauth.middleware.create_bearer_auth import BearerAuthConfig, create_bearer_auth
from mcpauth.types import AuthInfo
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..security import database, verify
from ..web_config import settings

auth_context: ContextVar[AuthInfo | None] = ContextVar("trip_mcp_auth", default=None)
logger = logging.getLogger(__name__)


def verify_access_token(token: str) -> AuthInfo:
    try:
        claims = verify(token, "mcp")
    except (jwt.PyJWTError, redis.RedisError) as error:
        logger.warning("Credencial MCP rechazada: %s", type(error).__name__)
        raise MCPAuthTokenVerificationException(
            MCPAuthTokenVerificationExceptionCode.INVALID_TOKEN
        ) from error
    return AuthInfo(
        token=token, issuer=claims["iss"], subject=claims["sub"],
        audience=claims["aud"], scopes=claims["scope"].split(), claims=claims,
    )


bearer_middleware = create_bearer_auth(
    verify_access_token,
    config=BearerAuthConfig(issuer=settings.issuer, audience="mcp"),
    context_var=auth_context,
)


class SessionBindingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        info = auth_context.get()
        if info is None:
            return JSONResponse({"detail": "Credencial MCP requerida."}, status_code=401)
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            if len(session_id) > 200 or database().get(f"mcp-session:{session_id}") != info.claims["sid"]:
                return JSONResponse({"detail": "La sesion MCP pertenece a otra identidad o ha caducado."}, status_code=403)
        response = await call_next(request)
        created_id = response.headers.get("mcp-session-id")
        if created_id:
            database().setex(f"mcp-session:{created_id}", settings.delegated_ttl, info.claims["sid"])
        if session_id and request.method == "DELETE":
            database().delete(f"mcp-session:{session_id}")
        return response


def principal(scope: str) -> AuthInfo:
    info = auth_context.get()
    if info is None or scope not in info.scopes:
        raise ToolError("No tienes permiso para esta herramienta.")
    verify_access_token(info.token)
    return info
