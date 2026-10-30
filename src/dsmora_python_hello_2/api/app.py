import logging
import secrets
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
import jwt
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
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


@app.post("/api/auth/ws-ticket")
def websocket_ticket(auth: Mutation):
    return {
        "token": issue(auth[1]["sub"], auth[0], "websocket", ttl_seconds=60),
    }


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class ToolRequest(BaseModel):
    name: Literal["get_weather", "save_trip_plan", "list_trip_plans", "delete_trip_plan"]
    arguments: dict[str, str] = Field(default_factory=dict, max_length=3)


class Confirmation(BaseModel):
    confirmation_id: str = Field(min_length=16, max_length=100)
    accept: bool


class PlanApproval(BaseModel):
    request_id: str = Field(min_length=16, max_length=100)
    version: int = Field(ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "deny"]


def agent_headers(auth: tuple[str, dict[str, Any]]) -> dict[str, str]:
    sid, session = auth
    headers = {"Authorization": f"Bearer {issue(session['sub'], sid, 'agent')}"}
    if session["authenticated"]:
        headers["X-MCP-Token"] = issue(session["sub"], sid, "mcp", SCOPES)
    return headers


def agent_request(method: str, path: str, auth: tuple[str, dict[str, Any]], body=None):
    headers = agent_headers(auth)
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


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, auth: Identity):
    if not job_id.isalnum() or len(job_id) != 32:
        raise HTTPException(404, "Trabajo no encontrado.")
    headers = agent_headers(auth)
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id[:64]
    client = httpx.AsyncClient(timeout=httpx.Timeout(10, read=60), trust_env=False)
    try:
        upstream = await client.send(
            client.build_request("GET", f"{settings.agent_url}/jobs/{job_id}/events", headers=headers),
            stream=True,
        )
    except httpx.HTTPError as error:
        await client.aclose()
        logger.error("Agente no disponible: %s", type(error).__name__)
        raise HTTPException(503, "El agente no esta disponible.") from error
    if upstream.is_error:
        await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        if upstream.status_code in {401, 403, 404}:
            raise HTTPException(upstream.status_code, upstream.json().get("detail", "Solicitud rechazada."))
        raise HTTPException(502, "No se pudo completar la solicitud al agente.")

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        except httpx.HTTPError as error:
            logger.error("Stream del agente interrumpido: %s", type(error).__name__)
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )

@app.websocket("/api/ws/chat")
async def websocket_chat(websocket: WebSocket):
    origin = websocket.headers.get("origin") or websocket.query_params.get("origin")
    codespaces_proxy = (
        settings.environment == "development"
        and settings.codespaces
        and origin in {"http://localhost:3000", "https://localhost:3000"}
    )
    if origin != settings.origin and not codespaces_proxy:
        await websocket.close(code=4403, reason="Origen no permitido.")
        return

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    def authenticate_ticket(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        claims = verify(token, "websocket")
        if not database().set(
            f"websocket-ticket:{claims['jti']}", "1", ex=60, nx=True
        ):
            raise jwt.InvalidTokenError("El ticket WebSocket ya fue utilizado.")
        return claims, active_session(claims["sid"])

    active_job_id: str | None = None
    try:
        try:
            raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            if len(raw_auth) > 20000:
                raise jwt.InvalidTokenError("Credencial WebSocket invalida.")
            first = json.loads(raw_auth)
            if not isinstance(first, dict) or first.get("type") != "auth":
                raise jwt.InvalidTokenError("Falta la credencial WebSocket.")
            claims, session = await asyncio.to_thread(
                authenticate_ticket, first.get("token", "")
            )
            auth = (claims["sid"], session)
        except asyncio.TimeoutError:
            await send({"type": "error", "code": "AUTH_TIMEOUT", "message": "La autenticacion del socket ha caducado."})
            await websocket.close(code=4401)
            return
        except (jwt.PyJWTError, jwt.PyJWKClientError, TypeError, KeyError, json.JSONDecodeError) as error:
            await send({"type": "error", "code": "UNAUTHORIZED", "message": "La sesion no es valida."})
            await websocket.close(code=4401)
            return
        await send({"type": "ready", "session_id": auth[0]})

        while True:
            raw_frame = await websocket.receive_text()
            if len(raw_frame) > 20000:
                await send({"type": "error", "code": "MESSAGE_TOO_LARGE", "message": "El mensaje excede el limite permitido."})
                continue
            try:
                frame = json.loads(raw_frame)
            except json.JSONDecodeError:
                await send({"type": "error", "code": "INVALID_MESSAGE", "message": "Mensaje WebSocket invalido."})
                continue
            if not isinstance(frame, dict):
                await send({"type": "error", "code": "INVALID_MESSAGE", "message": "Mensaje WebSocket invalido."})
                continue
            kind = frame.get("type")
            if kind == "attach_job":
                job_id = frame.get("job_id", "")
                if not isinstance(job_id, str) or not job_id.isalnum() or len(job_id) != 32:
                    await send({"type": "error", "code": "INVALID_JOB", "message": "Trabajo no encontrado."})
                    continue
                try:
                    state = await asyncio.to_thread(agent_request, "GET", f"/jobs/{job_id}", auth)
                except HTTPException as error:
                    await send({"type": "error", "code": "JOB_NOT_FOUND", "message": str(error.detail)})
                    continue
                if active_job_id and active_job_id != job_id:
                    try:
                        active_state = await asyncio.to_thread(
                            agent_request, "GET", f"/jobs/{active_job_id}", auth,
                        )
                    except HTTPException:
                        active_state = {"status": "failed"}
                    if active_state["status"] not in {"done", "failed", "interrupted"}:
                        await send({"type": "error", "code": "JOB_ACTIVE", "message": "Espera a que termine el trabajo actual."})
                        continue
                active_job_id = (
                    None if state["status"] in {"done", "failed", "interrupted"} else job_id
                )
                await send({"type": "control_ready", "job_id": job_id, "status": state["status"]})
            elif kind == "release_job":
                job_id = frame.get("job_id")
                if job_id == active_job_id:
                    active_job_id = None
                await send({"type": "control_released", "job_id": job_id})
            elif kind == "interrupt":
                job_id = frame.get("job_id")
                if not active_job_id or job_id != active_job_id:
                    await send({"type": "error", "code": "NO_ACTIVE_JOB", "message": "No hay una generacion activa."})
                    continue
                try:
                    result = await asyncio.to_thread(
                        agent_request, "POST", f"/jobs/{job_id}/interrupt", auth, {},
                    )
                except HTTPException as error:
                    await send({"type": "error", "code": "INTERRUPT_REJECTED", "message": str(error.detail)})
                    continue
                await send({"type": "interrupt_ack", "job_id": job_id, **result})
            elif kind in {"confirm", "approve"}:
                job_id = frame.get("job_id")
                if not active_job_id or job_id != active_job_id:
                    await send({"type": "error", "code": "NO_ACTIVE_JOB", "message": "La aprobacion ya no esta pendiente."})
                    continue
                try:
                    if kind == "confirm":
                        body = Confirmation.model_validate({
                            "confirmation_id": frame.get("confirmation_id"),
                            "accept": frame.get("accept"),
                        })
                        await asyncio.to_thread(
                            agent_request, "POST", f"/jobs/{job_id}/confirm", auth, body.model_dump(),
                        )
                    else:
                        body = PlanApproval.model_validate({
                            "request_id": frame.get("request_id"),
                            "version": frame.get("version"),
                            "digest": frame.get("digest"),
                            "action": frame.get("action"),
                        })
                        expected_status = "approved" if body.action == "approve" else "denied"
                        try:
                            await asyncio.to_thread(
                                agent_request, "POST", f"/jobs/{job_id}/approve", auth, body.model_dump(),
                            )
                            decision_state = expected_status
                        except HTTPException as error:
                            if error.status_code != 409:
                                raise
                            current = await asyncio.to_thread(
                                agent_request, "GET", f"/jobs/{job_id}", auth,
                            )
                            decision_state = expected_status
                            if current["status"] not in {decision_state, "running"} and not (
                                body.action == "approve" and current["status"] == "done"
                            ) and not (
                                body.action == "deny"
                                and current["status"] == "failed"
                                and current.get("error_code") == "APPROVAL_DENIED"
                            ):
                                raise
                            if current["status"] in {"done", "failed"}:
                                active_job_id = None
                                await send({"type": "approval_received", "job_id": job_id, "status": current["status"]})
                                continue
                            if current["status"] == "running":
                                decision_state = "running"
                        if decision_state in {"approved", "denied"}:
                            await asyncio.to_thread(
                                agent_request, "POST", f"/jobs/{job_id}/resume", auth, {},
                            )
                except (HTTPException, ValueError) as error:
                    detail = str(error.detail) if isinstance(error, HTTPException) else "La decision no es valida."
                    await send({"type": "error", "code": "APPROVAL_REJECTED", "message": detail})
                    continue
                await send({"type": "approval_received", "job_id": job_id, "status": "running"})
            else:
                await send({"type": "error", "code": "UNKNOWN_MESSAGE", "message": "Tipo de mensaje desconocido."})
    except WebSocketDisconnect:
        pass
    except redis.RedisError as error:
        logger.error("Redis no disponible durante el WebSocket: %s", type(error).__name__)
        await send({"type": "error", "code": "DATA_UNAVAILABLE", "message": "El servicio de datos no esta disponible."})
        await websocket.close(code=1013)
