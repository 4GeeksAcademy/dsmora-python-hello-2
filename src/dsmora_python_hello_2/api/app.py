import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
import jwt
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..security import SCOPES, active_session, database, issue, jwks, new_session, rate_limit, verify
from ..web_config import settings
from .users import Users
from .bootstrap import initialize_key

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    database().ping()
    initialize_key()
    jwks()
    app.state.users = Users()
    app.state.users.seed()
    yield
    app.state.users.db.close()


app = FastAPI(title="Mexico Lindo API", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, error: redis.RedisError):
    logger.error("Redis no disponible: %s", type(error).__name__)
    return JSONResponse({"detail": "El servicio de datos no esta disponible."}, status_code=503)


def identity(request: Request) -> tuple[str, dict[str, Any]]:
    token = request.cookies.get("session")
    if token:
        try:
            claims = verify(token, "backend")
            return claims["sid"], active_session(claims["sid"])
        except jwt.PyJWKClientConnectionError as error:
            logger.error("No se pudieron consultar las claves publicas de autenticacion.")
            raise HTTPException(503, "El servicio de autenticacion no esta disponible.") from error
        except jwt.PyJWTError as error:
            raise HTTPException(401, "La sesion ha caducado. Vuelve a entrar.") from error
    sid = request.cookies.get("guest")
    if sid:
        try:
            session = active_session(sid)
            if not session["authenticated"]:
                return sid, session
        except jwt.InvalidTokenError as error:
            raise HTTPException(401, "La sesion de invitado ha caducado.") from error
    raise HTTPException(401, "Inicia una sesion de chat.")


Identity = Annotated[tuple[str, dict[str, Any]], Depends(identity)]


def mutation(request: Request, auth: Identity) -> tuple[str, dict[str, Any]]:
    origin = request.headers.get("origin")
    codespaces_proxy = (
        settings.environment == "development"
        and settings.codespaces
        and origin in {"http://localhost:3000", "https://localhost:3000"}
    )
    if origin != settings.origin and not codespaces_proxy:
        logger.warning(
            "Mutacion rechazada: origen no permitido; path=%s origin=%r expected=%r",
            request.url.path, origin, settings.origin,
        )
        raise HTTPException(403, "Origen no permitido.")
    supplied = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(supplied, auth[1]["csrf"]):
        logger.warning(
            "Mutacion rechazada: CSRF invalido; path=%s token_present=%s",
            request.url.path, bool(supplied),
        )
        raise HTTPException(403, "Confirmacion de sesion invalida.")
    return auth


Mutation = Annotated[tuple[str, dict[str, Any]], Depends(mutation)]


def set_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name, value, max_age=settings.session_ttl, httponly=True,
        secure=settings.environment != "development", samesite="strict", path="/",
    )


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(request: Request):
    database().ping()
    jwks()
    with request.app.state.users.lock:
        len(request.app.state.users.db)
    return {"status": "ready"}


@app.get("/.well-known/jwks.json")
def public_keys():
    return jwks()


@app.get("/api/auth/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        sid, session = identity(request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        response.delete_cookie("session")
        sid, session = new_session(f"guest:{secrets.token_urlsafe(24)}")
        set_cookie(response, "guest", sid)
    return {"email": session["email"], "authenticated": session["authenticated"], "csrf": session["csrf"]}


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response, auth: Mutation):
    address = request.client.host if request.client else "unknown"
    if not rate_limit(f"login:{address}", 15, 300):
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
    user = request.app.state.users.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(401, "Email o contrasena incorrectos.")
    sid, session = new_session(user["id"], user["email"])
    database().delete(f"session:{auth[0]}")
    set_cookie(response, "session", issue(user["id"], sid, "backend"))
    response.delete_cookie("guest")
    response.headers["Cache-Control"] = "no-store"
    return {"email": session["email"], "authenticated": True, "csrf": session["csrf"]}


@app.post("/api/auth/logout")
def logout(response: Response, auth: Mutation):
    database().delete(f"session:{auth[0]}")
    response.delete_cookie("session")
    response.delete_cookie("guest")
    return {"status": "signed_out"}


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class ToolRequest(BaseModel):
    name: Literal["get_weather", "save_trip_plan", "list_trip_plans", "delete_trip_plan"]
    arguments: dict[str, str] = Field(default_factory=dict, max_length=3)


class Confirmation(BaseModel):
    confirmation_id: str = Field(min_length=16, max_length=100)
    accept: bool


def agent_request(method: str, path: str, auth: tuple[str, dict[str, Any]], body=None):
    sid, session = auth
    headers = {"Authorization": f"Bearer {issue(session['sub'], sid, 'agent')}"}
    if session["authenticated"]:
        headers["X-MCP-Token"] = issue(session["sub"], sid, "mcp", SCOPES)
    try:
        with httpx.Client(timeout=15, trust_env=False) as client:
            result = client.request(
                method, f"{settings.agent_url}{path}", headers=headers, json=body
            )
    except httpx.HTTPError as error:
        logger.error("Agente no disponible: %s", type(error).__name__)
        raise HTTPException(503, "El agente no esta disponible.") from error
    if result.is_error:
        if result.status_code in {400, 401, 403, 404, 409, 422, 429}:
            raise HTTPException(result.status_code, result.json().get("detail", "Solicitud rechazada."))
        logger.error("El agente respondio HTTP %s", result.status_code)
        raise HTTPException(502, "No se pudo completar la solicitud al agente.")
    return result.json()


@app.post("/api/chat", status_code=202)
def chat(body: Chat, auth: Mutation):
    if not body.message.strip():
        raise HTTPException(422, "El mensaje no puede estar vacio.")
    if not rate_limit(f"chat:{auth[0]}", 20, 300):
        raise HTTPException(429, "Limite de mensajes alcanzado.")
    return agent_request("POST", "/jobs/chat", auth, body.model_dump())


@app.post("/api/tools", status_code=202)
def tool(body: ToolRequest, auth: Mutation):
    if not auth[1]["authenticated"]:
        raise HTTPException(403, "Inicia sesion para usar herramientas.")
    if not rate_limit(f"tools:{auth[0]}", 30, 300):
        raise HTTPException(429, "Limite de herramientas alcanzado.")
    return agent_request("POST", "/jobs/tool", auth, body.model_dump())


@app.get("/api/jobs/{job_id}")
def job(job_id: str, response: Response, auth: Identity):
    response.headers["Cache-Control"] = "no-store"
    if not job_id.isalnum() or len(job_id) != 32:
        raise HTTPException(404, "Trabajo no encontrado.")
    return agent_request("GET", f"/jobs/{job_id}", auth)


@app.post("/api/jobs/{job_id}/confirm")
def confirm(job_id: str, body: Confirmation, auth: Mutation):
    if not job_id.isalnum() or len(job_id) != 32:
        raise HTTPException(404, "Trabajo no encontrado.")
    return agent_request("POST", f"/jobs/{job_id}/confirm", auth, body.model_dump())
