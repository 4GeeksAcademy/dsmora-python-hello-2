import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

import jwt
import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ..api.app import Chat, Confirmation, PlanApproval, ToolRequest
from ..approval import ApprovalRegistry
from ..config import LLMConfig
from ..factory import build_orchestrator
from ..guardrails import GUARD_ERROR
from ..llm import OpenAICompatibleModel
from ..mcp_weather.client import call_tool, call_tool_with_headers
from ..memory import UserMemory
from ..model import Message, ToolCall
from ..security import active_session, database, verify
from ..subagents import SubAgentResult, SubAgentTask
from ..tools import API_ERROR_TEXT
from ..web_config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.approval_db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(settings.approval_db.parent, 0o700)
    previous_umask = os.umask(0o077)
    try:
        connection = sqlite3.connect(
            settings.approval_db, timeout=30, check_same_thread=False
        )
        os.chmod(settings.approval_db, 0o600)
        serializer = JsonPlusSerializer(
            allowed_msgpack_modules=[
                ("dsmora_python_hello_2.model", "Message"),
                ("dsmora_python_hello_2.model", "ToolCall"),
                ("dsmora_python_hello_2.subagents", "SubAgentResult"),
                ("dsmora_python_hello_2.subagents", "SubAgentTask"),
            ]
        )
        checkpointer = SqliteSaver(connection, serde=serializer)
        checkpointer.setup()
        registry = ApprovalRegistry(settings.approval_db)
    finally:
        os.umask(previous_umask)
    app.state.checkpointer = checkpointer
    app.state.approvals = registry
    try:
        yield
    finally:
        registry.close()
        connection.close()


app = FastAPI(title="Mexico Lindo Agent", lifespan=lifespan)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat")
slots = threading.BoundedSemaphore(4)
instance_id = uuid.uuid4().hex


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, error: redis.RedisError):
    logger.error("Redis del agente no disponible: %s", type(error).__name__)
    return JSONResponse({"detail": "Datos del agente no disponibles."}, status_code=503)


def auth(request: Request) -> dict[str, Any]:
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        raise HTTPException(401, "Credencial interna requerida.")
    try:
        return verify(value[7:], "agent")
    except jwt.PyJWTError as error:
        raise HTTPException(401, "Credencial interna invalida.") from error


Auth = Annotated[dict[str, Any], Depends(auth)]


def owned(job_id: str, claims: dict[str, Any]) -> dict[str, str]:
    if len(job_id) != 32 or not job_id.isalnum():
        raise HTTPException(404, "Trabajo no encontrado.")
    job = database().hgetall(f"job:{job_id}")
    approval = app.state.approvals.get(job_id)
    if approval is not None:
        if approval["owner_id"] != claims["sub"]:
            raise HTTPException(404, "Trabajo no encontrado.")
        return job
    if not job or job["sid"] != claims["sid"]:
        raise HTTPException(404, "Trabajo no encontrado.")
    return job


def update(job_id: str, **values) -> None:
    database().hset(f"job:{job_id}", mapping=values)


def events_key(job_id: str) -> str:
    return f"events:{job_id}"


def publish_token(job_id: str, message_id: str, text: str) -> None:
    pipe = database().pipeline()
    pipe.xadd(events_key(job_id), {"id": message_id, "text": text}, maxlen=20000, approximate=True)
    pipe.expire(events_key(job_id), settings.history_ttl)
    pipe.execute()


class JobInterrupted(Exception):
    pass


class JobContext:
    def __init__(self, job_id: str, claims: dict[str, Any], token: str | None):
        self.job_id, self.claims, self.token = job_id, claims, token
        self.deadline = time.monotonic() + settings.job_timeout
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.save_result: Any = None

    def check(self) -> None:
        if self.cancelled.is_set():
            raise JobInterrupted()
        active_session(self.claims["sid"])
        if time.monotonic() >= self.deadline:
            raise RuntimeError("Tiempo maximo del trabajo agotado.")

    def consent(self, message: str) -> bool:
        with self.lock:
            confirmation_id = secrets.token_urlsafe(24)
            expires = int(time.time()) + settings.consent_timeout
            pending = json.dumps({"id": confirmation_id, "message": message, "expires": expires})
            try:
                self.check()
                update(self.job_id, pending=pending, progress="Esperando tu confirmacion.")
                while time.time() < expires:
                    self.check()
                    response = database().get(f"consent:{self.job_id}:{confirmation_id}")
                    if response is not None:
                        return response == "accept"
                    time.sleep(0.25)
                return False
            except (jwt.InvalidTokenError, RuntimeError):
                update(
                    self.job_id, status="failed",
                    error="La sesion se ha cerrado o el trabajo ha caducado. No se autorizo la accion.",
                )
                return False
            finally:
                update(self.job_id, pending="")

    def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        self.check()
        if not self.token:
            raise RuntimeError("Inicia sesion para usar herramientas MCP.")
        if name == "save_trip_plan":
            raise RuntimeError("El guardado debe pasar por la aprobacion durable.")
        verify(self.token, "mcp")
        result = call_tool(name, arguments, self.token, self.consent)
        self.check()
        return result

    def save_candidate(
        self, candidate: dict[str, Any], decision: dict[str, Any]
    ) -> Any:
        self.check()
        if (
            not self.token
            or decision.get("action") != "approve"
            or decision.get("actor_id") != self.claims["sub"]
        ):
            raise RuntimeError("La autorizacion para guardar no es valida.")
        verify(self.token, "mcp")
        auth_ref = secrets.token_urlsafe(32)
        grant = {
            "owner_id": self.claims["sub"],
            "request_id": decision["request_id"],
            "operation_id": candidate["operation_id"],
            "version": candidate["version"],
            "digest": candidate["digest"],
        }
        if not database().set(
            f"plan-authorization:{auth_ref}",
            json.dumps(grant, ensure_ascii=False),
            ex=900,
            nx=True,
        ):
            raise RuntimeError("No se pudo registrar la autorizacion del plan.")
        headers = {
            "X-Plan-Authorization": auth_ref,
            "X-Plan-Operation-ID": candidate["operation_id"],
            "X-Plan-Request-ID": decision["request_id"],
            "X-Plan-Version": str(candidate["version"]),
            "X-Plan-Digest": candidate["digest"],
        }
        result = call_tool_with_headers(
            "save_trip_plan",
            {"title": candidate["title"], "content": candidate["content"]},
            self.token,
            headers,
        )
        if not isinstance(result, dict) or result.get("status") not in {
            "saved", "already_saved"
        }:
            raise RuntimeError("MCP no devolvio un recibo valido del plan.")
        self.save_result = result
        return result

    def event(self, event: str) -> None:
        self.check()
        progress = "Revisando y ajustando el itinerario." if event.startswith("[planner]") else "Preparando tu respuesta."
        update(self.job_id, progress=progress)


active_jobs: dict[str, JobContext] = {}
active_jobs_lock = threading.Lock()


class CheckedModel:
    def __init__(self, model: OpenAICompatibleModel, context: JobContext):
        self.model, self.context = model, context

    def generate(self, messages, tools):
        self.context.check()
        response = self.model.generate(messages, tools)
        self.context.check()
        return response


def execute(
    context: JobContext,
    chat: Chat | None,
    tool: ToolRequest | None,
    conversation_lock: str,
    resume_decision: dict[str, Any] | None = None,
) -> None:
    try:
        context.check()
        if tool is not None and tool.name != "save_trip_plan":
            result = context.invoke(tool.name, tool.arguments)
        else:
            config = LLMConfig.from_env()
            model = CheckedModel(OpenAICompatibleModel(config.api_url, config.model, config.api_key), context)
            session = active_session(context.claims["sid"])
            memory = UserMemory(database(), context.claims["sub"]) if session["authenticated"] else None

            def register_prepared(envelope: dict[str, Any]) -> None:
                execution_data = envelope["execution"]
                approval = envelope["approval"]
                app.state.approvals.prepare(
                    thread_id=execution_data["thread_id"],
                    owner_id=execution_data["owner_id"],
                    conversation_id=execution_data["conversation_id"],
                    job_id=execution_data["job_id"],
                    request_id=approval["request_id"],
                    operation_id=envelope["effect"]["operation_id"],
                    candidate=envelope["candidate"],
                )

            def publish_checked_token(message_id: str, text: str) -> None:
                context.check()
                publish_token(context.job_id, message_id, text)

            agent = build_orchestrator(
                model,
                context.invoke if session["authenticated"] else None,
                memory,
                context.event,
                checkpointer=app.state.checkpointer,
                register_prepared=register_prepared,
                save_candidate=context.save_candidate if session["authenticated"] else None,
                on_token=publish_checked_token,
            )
            conversation_id = chat.conversation_id if chat else "tools"
            if chat is not None:
                history_key = f"history:{context.claims['sid']}:{conversation_id}"
                history = database().get(history_key)
                if history:
                    agent.history = [Message(**message) for message in json.loads(history)]
            if resume_decision is not None:
                result = agent.resume(context.job_id, resume_decision)
            elif tool is not None:
                result = agent.run(
                    "Guardar el plan propuesto.",
                    thread_id=context.job_id,
                    owner_id=context.claims["sub"],
                    conversation_id=conversation_id,
                    initial_candidate=tool.arguments,
                )
            else:
                result = agent.run(
                    chat.message,
                    thread_id=context.job_id,
                    owner_id=context.claims["sub"],
                    conversation_id=conversation_id,
                )
            if isinstance(result, dict) and result.get("status") == "awaiting_approval":
                pending = result["pending"]
                app.state.approvals.update(context.job_id, "awaiting_approval")
                update(
                    context.job_id,
                    status="awaiting_approval",
                    pending=json.dumps(pending, ensure_ascii=False),
                    progress="Esperando tu aprobacion.",
                )
                database().persist(f"job:{context.job_id}")
                return
            if isinstance(result, dict) and result.get("status") == "failed":
                failure = result["error"]
                terminal = "rejected" if failure["code"] == "APPROVAL_DENIED" else "failed"
                app.state.approvals.update(
                    context.job_id, terminal, error=failure["code"]
                )
                update(
                    context.job_id,
                    status="failed",
                    error=failure["message"],
                    error_code=failure["code"],
                    pending="",
                )
                return
            if isinstance(result, dict) and result.get("status") == "done":
                result = result["result"]
            if isinstance(result, str) and result in {API_ERROR_TEXT, GUARD_ERROR}:
                raise RuntimeError("El agente no pudo generar una respuesta.")
            if context.save_result is None:
                context.check()
            if chat is not None:
                database().setex(
                    history_key,
                    settings.history_ttl,
                    json.dumps(
                        [{"role": item.role, "content": item.content} for item in agent.history[-12:]]
                    ),
                )
        app.state.approvals.update(
            context.job_id, "completed", result=result
        )
        update(
            context.job_id,
            status="done",
            result=json.dumps(result, ensure_ascii=False),
            pending="",
            progress="Completado.",
        )
    except JobInterrupted:
        if context.save_result is not None:
            result = (
                context.save_result
                if tool is not None
                else "Plan guardado. Puedes verlo en tus planes."
            )
            app.state.approvals.update(context.job_id, "completed", result=result)
            update(
                context.job_id,
                status="done",
                result=json.dumps(result, ensure_ascii=False),
                pending="",
                progress="Completado.",
            )
        else:
            approval = app.state.approvals.get(context.job_id)
            if approval is not None and approval["status"] == "resuming":
                app.state.approvals.release_resume(context.job_id)
            update(
                context.job_id,
                status="interrupted",
                pending="",
                progress="Generacion detenida por el usuario.",
            )
    except Exception as error:
        logger.error("Trabajo %s fallo: %s: %.200s", context.job_id, type(error).__name__, error, exc_info=True)
        try:
            if context.save_result is not None:
                result = (
                    context.save_result
                    if tool is not None
                    else "Plan guardado. Puedes verlo en tus planes."
                )
                app.state.approvals.update(
                    context.job_id, "completed", result=result
                )
                update(
                    context.job_id,
                    status="done",
                    result=json.dumps(result, ensure_ascii=False),
                    pending="",
                    progress="Completado.",
                )
                return
            app.state.approvals.update(context.job_id, "failed", error=type(error).__name__)
            update(
                context.job_id, status="failed", pending="",
                error="No se pudo completar la solicitud. Comprueba tu sesion y los servicios; vuelve a intentarlo.",
            )
        except redis.RedisError:
            logger.error("No se pudo registrar el fallo del trabajo %s.", context.job_id)
    finally:
        with active_jobs_lock:
            active_jobs.pop(context.job_id, None)
        try:
            database().eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0",
                1, conversation_lock, context.job_id,
            )
        except redis.RedisError:
            logger.error("No se pudo liberar el bloqueo del trabajo %s; caducara por TTL.", context.job_id)
        finally:
            slots.release()


def start(request: Request, claims: dict[str, Any], chat=None, tool=None):
    session = active_session(claims["sid"])
    token = request.headers.get("x-mcp-token")
    if session["authenticated"]:
        try:
            mcp_claims = verify(token or "", "mcp")
        except jwt.PyJWTError as error:
            raise HTTPException(401, "Credencial MCP invalida.") from error
        if mcp_claims["sid"] != claims["sid"] or mcp_claims["sub"] != claims["sub"]:
            raise HTTPException(403, "Identidades incompatibles.")
    elif tool is not None or token:
        raise HTTPException(403, "Los invitados solo pueden planificar.")
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "El agente esta ocupado; intentalo mas tarde.")
    job_id = uuid.uuid4().hex
    conversation = chat.conversation_id if chat else "tools"
    lock_key = f"busy:{claims['sid']}:{conversation}"
    submitted = False
    try:
        if not database().set(lock_key, job_id, ex=settings.job_timeout + 150, nx=True):
            raise HTTPException(409, "Ya hay una solicitud activa en esta conversacion.")
        pipe = database().pipeline()
        pipe.hset(f"job:{job_id}", mapping={
            "sid": claims["sid"], "owner_id": claims["sub"], "instance": instance_id, "status": "running",
            "created": int(time.time()), "pending": "", "progress": "Iniciando.", "lock_key": lock_key,
        })
        pipe.expire(f"job:{job_id}", settings.history_ttl)
        pipe.execute()
        context = JobContext(job_id, claims, token)
        with active_jobs_lock:
            active_jobs[job_id] = context
        executor.submit(execute, context, chat, tool, lock_key)
        submitted = True
    finally:
        if not submitted:
            with active_jobs_lock:
                active_jobs.pop(job_id, None)
            slots.release()
            try:
                database().eval(
                    "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0",
                    1, lock_key, job_id,
                )
            except redis.RedisError:
                logger.error("No se pudo limpiar el bloqueo de un trabajo no iniciado.")
    return {"job_id": job_id}


@app.get("/health/ready")
def health():
    settings.validate()
    database().ping()
    app.state.approvals.connection.execute("SELECT 1").fetchone()
    LLMConfig.from_env()
    return {"status": "ready"}


@app.post("/jobs/chat", status_code=202)
def chat_job(body: Chat, request: Request, claims: Auth):
    return start(request, claims, chat=body)


@app.post("/jobs/tool", status_code=202)
def tool_job(body: ToolRequest, request: Request, claims: Auth):
    return start(request, claims, tool=body)


@app.get("/jobs/{job_id}")
def status(job_id: str, claims: Auth):
    job = owned(job_id, claims)
    approval = app.state.approvals.get(job_id)
    if approval is not None:
        state = approval["status"]
        if state == "awaiting_approval":
            candidate = approval["candidate"]
            return {
                "status": "awaiting_approval",
                "progress": "Esperando tu aprobacion.",
                "pending": {
                    "id": approval["request_id"],
                    "message": "Revisa el plan y decide si quieres guardarlo.",
                    "title": candidate["title"],
                    "content": candidate["content"],
                    "version": candidate["version"],
                    "digest": approval["digest"],
                    "operation_id": approval["operation_id"],
                },
                "result": None,
                "error": None,
            }
        if state in {"approved", "denied"}:
            return {"status": state, "progress": "Decision registrada.", "pending": None}
        if state == "resuming":
            return {"status": "running", "progress": "Procesando tu decision.", "pending": None}
        if state == "completed":
            return {
                "status": "done",
                "progress": "Completado.",
                "pending": None,
                "result": approval["result"],
                "error": None,
            }
        if state == "rejected":
            return {
                "status": "failed",
                "pending": None,
                "error": "Aprobacion rechazada. El plan no se guardo.",
                "error_code": "APPROVAL_DENIED",
            }
        if state in {"prepared", "failed"}:
            return {
                "status": "failed",
                "pending": None,
                "error": "No se pudo completar la aprobacion durable. Vuelve a intentarlo.",
                "error_code": approval["error"] or "APPROVAL_FAILED",
            }
    if job["status"] == "running" and (
        job["instance"] != instance_id or time.time() - int(job["created"]) > settings.job_timeout + 120
    ):
        update(job_id, status="failed", error="Trabajo interrumpido; vuelve a intentarlo.", pending="")
        if job.get("lock_key"):
            database().eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0",
                1, job["lock_key"], job_id,
            )
        return {"status": "failed", "error": "Trabajo interrumpido; vuelve a intentarlo."}
    return {
        "status": job["status"], "progress": job.get("progress", ""),
        "pending": json.loads(job["pending"]) if job.get("pending") else None,
        "result": json.loads(job["result"]) if job.get("result") else None,
        "error": job.get("error"),
    }


def sse(event: str, data: Any, event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/jobs/{job_id}/events")
def job_events(job_id: str, request: Request, claims: Auth):
    """SSE: eventos `token` (texto parcial del agente) y `status` (estado del trabajo)."""
    owned(job_id, claims)
    last_event_id = request.headers.get("last-event-id", "")
    cursor = last_event_id if re.fullmatch(r"\d+-\d+", last_event_id) else "0"

    def stream():
        nonlocal cursor
        previous = None
        keepalive = time.monotonic()
        while True:
            entries = database().xread({events_key(job_id): cursor}, count=500, block=500)
            for _, items in entries or []:
                for entry_id, fields in items:
                    cursor = entry_id
                    yield sse("token", fields, entry_id)
            current = status(job_id, claims)
            if current != previous:
                previous = current
                keepalive = time.monotonic()
                yield sse("status", current)
            if current["status"] != "running":
                return
            if time.monotonic() - keepalive > 15:
                keepalive = time.monotonic()
                yield ": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/confirm")
def confirm(job_id: str, body: Confirmation, claims: Auth):
    job = owned(job_id, claims)
    pending = json.loads(job["pending"]) if job.get("pending") else None
    if (
        job.get("status") != "running"
        or not pending
        or pending["id"] != body.confirmation_id
        or time.time() >= pending["expires"]
    ):
        raise HTTPException(409, "La confirmacion ha caducado o ya no esta disponible.")
    if not database().set(
        f"consent:{job_id}:{body.confirmation_id}",
        "accept" if body.accept else "decline",
        ex=settings.consent_timeout,
        nx=True,
    ):
        raise HTTPException(409, "Esta confirmacion ya tiene respuesta.")
    return {"status": "received"}


@app.post("/jobs/{job_id}/interrupt")
def interrupt_job(job_id: str, claims: Auth):
    job = owned(job_id, claims)
    if job.get("status") != "running":
        raise HTTPException(409, "No hay una generacion activa que detener.")
    with active_jobs_lock:
        context = active_jobs.get(job_id)
        if context is None:
            raise HTTPException(409, "La generacion ya termino.")
        context.cancelled.set()
    return {"status": "interrupting"}


@app.post("/jobs/{job_id}/approve")
def approve(job_id: str, body: PlanApproval, claims: Auth):
    owned(job_id, claims)
    record = app.state.approvals.get(job_id)
    if record is None or not app.state.approvals.record_decision(
        thread_id=job_id,
        owner_id=claims["sub"],
        request_id=body.request_id,
        version=body.version,
        digest=body.digest,
        action=body.action,
        actor_id=claims["sub"],
    ):
        raise HTTPException(409, "La solicitud ya no esta pendiente o no coincide con el plan.")
    update(
        job_id,
        status="approved" if body.action == "approve" else "denied",
        pending="",
        progress="Decision registrada.",
    )
    database().persist(f"job:{job_id}")
    return {"status": "approved" if body.action == "approve" else "denied"}


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, request: Request, claims: Auth):
    owned(job_id, claims)
    record = app.state.approvals.get(job_id)
    if record is None:
        raise HTTPException(404, "Trabajo no encontrado.")
    if record["status"] == "resuming":
        return {"status": "running"}
    if record["status"] not in {"approved", "denied"} or record["decision"] is None:
        raise HTTPException(409, "No hay una decision guardada para reanudar.")
    try:
        token = request.headers.get("x-mcp-token", "")
        mcp_claims = verify(token, "mcp")
    except jwt.PyJWTError as error:
        raise HTTPException(401, "Credencial MCP invalida.") from error
    if mcp_claims["sid"] != claims["sid"] or mcp_claims["sub"] != claims["sub"]:
        raise HTTPException(403, "Identidades incompatibles.")
    claimed = app.state.approvals.claim_resume(job_id)
    if claimed is None:
        raise HTTPException(409, "La decision ya se esta procesando.")
    if not slots.acquire(blocking=False):
        app.state.approvals.release_resume(job_id)
        raise HTTPException(429, "El agente esta ocupado; intentalo mas tarde.")
    lock_key = f"busy:{claims['sid']}:{record['conversation_id']}"
    if not database().set(lock_key, job_id, ex=settings.job_timeout + 150, nx=True):
        slots.release()
        app.state.approvals.release_resume(job_id)
        raise HTTPException(409, "Ya hay una solicitud activa en esta conversacion.")
    database().delete(events_key(job_id))
    update(
        job_id,
        sid=claims["sid"],
        owner_id=claims["sub"],
        instance=instance_id,
        status="running",
        pending="",
        created=int(time.time()),
        lock_key=lock_key,
        progress="Procesando tu decision.",
    )
    decision = {
        **claimed["decision"],
        "request_id": claimed["request_id"],
        "version": claimed["candidate"]["version"],
        "digest": claimed["digest"],
    }
    context = JobContext(job_id, claims, token)
    try:
        with active_jobs_lock:
            active_jobs[job_id] = context
        executor.submit(
            execute,
            context,
            None,
            None,
            lock_key,
            decision,
        )
    except RuntimeError as error:
        with active_jobs_lock:
            active_jobs.pop(job_id, None)
        database().delete(lock_key)
        slots.release()
        app.state.approvals.release_resume(job_id)
        raise HTTPException(503, "No se pudo reanudar la aprobacion.") from error
    return {"status": "running"}
