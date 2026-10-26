import json
import logging
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

import jwt
import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..api.app import Chat, Confirmation, ToolRequest
from ..config import LLMConfig
from ..factory import build_orchestrator
from ..guardrails import GUARD_ERROR
from ..llm import OpenAICompatibleModel
from ..mcp_weather.client import call_tool
from ..memory import UserMemory
from ..model import Message
from ..security import active_session, database, verify
from ..tools import API_ERROR_TEXT
from ..web_config import settings

logger = logging.getLogger(__name__)
app = FastAPI(title="Mexico Lindo Agent")
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
    if not job or job["sid"] != claims["sid"]:
        raise HTTPException(404, "Trabajo no encontrado.")
    return job


def update(job_id: str, **values) -> None:
    database().hset(f"job:{job_id}", mapping=values)


class JobContext:
    def __init__(self, job_id: str, claims: dict[str, Any], token: str | None):
        self.job_id, self.claims, self.token = job_id, claims, token
        self.deadline = time.monotonic() + settings.job_timeout
        self.lock = threading.Lock()

    def check(self) -> None:
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
        verify(self.token, "mcp")
        result = call_tool(name, arguments, self.token, self.consent)
        self.check()
        return result

    def event(self, event: str) -> None:
        self.check()
        progress = "Revisando y ajustando el itinerario." if event.startswith("[planner]") else "Preparando tu respuesta."
        update(self.job_id, progress=progress)


class CheckedModel:
    def __init__(self, model: OpenAICompatibleModel, context: JobContext):
        self.model, self.context = model, context

    def generate(self, messages, tools):
        self.context.check()
        response = self.model.generate(messages, tools)
        self.context.check()
        return response


def execute(
    context: JobContext, chat: Chat | None, tool: ToolRequest | None, conversation_lock: str
) -> None:
    try:
        context.check()
        if tool is not None:
            result = context.invoke(tool.name, tool.arguments)
        else:
            config = LLMConfig.from_env()
            model = CheckedModel(OpenAICompatibleModel(config.api_url, config.model, config.api_key), context)
            session = active_session(context.claims["sid"])
            memory = UserMemory(database(), context.claims["sub"]) if session["authenticated"] else None
            agent = build_orchestrator(
                model, context.invoke if session["authenticated"] else None, memory, context.event,
            )
            history_key = f"history:{context.claims['sid']}:{chat.conversation_id}"
            history = database().get(history_key)
            if history:
                agent.history = [Message(**message) for message in json.loads(history)]
            result = agent.run(chat.message)
            if result in {API_ERROR_TEXT, GUARD_ERROR}:
                raise RuntimeError("El agente no pudo generar una respuesta.")
            context.check()
            database().setex(
                history_key, settings.history_ttl,
                json.dumps([{"role": item.role, "content": item.content} for item in agent.history[-12:]]),
            )
        update(context.job_id, status="done", result=json.dumps(result, ensure_ascii=False), pending="", progress="Completado.")
    except Exception as error:
        logger.error("Trabajo %s fallo: %s", context.job_id, type(error).__name__)
        try:
            update(
                context.job_id, status="failed", pending="",
                error="No se pudo completar la solicitud. Comprueba tu sesion y los servicios; vuelve a intentarlo.",
            )
        except redis.RedisError:
            logger.error("No se pudo registrar el fallo del trabajo %s.", context.job_id)
    finally:
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
            "sid": claims["sid"], "instance": instance_id, "status": "running",
            "created": int(time.time()), "pending": "", "progress": "Iniciando.", "lock_key": lock_key,
        })
        pipe.expire(f"job:{job_id}", settings.history_ttl)
        pipe.execute()
        executor.submit(execute, JobContext(job_id, claims, token), chat, tool, lock_key)
        submitted = True
    finally:
        if not submitted:
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


@app.post("/jobs/{job_id}/confirm")
def confirm(job_id: str, body: Confirmation, claims: Auth):
    job = owned(job_id, claims)
    pending = json.loads(job["pending"]) if job.get("pending") else None
    if (
        job["status"] != "running" or not pending or pending["id"] != body.confirmation_id
        or time.time() >= pending["expires"]
    ):
        raise HTTPException(409, "La confirmacion ha caducado o ya no esta disponible.")
    if not database().set(
        f"consent:{job_id}:{body.confirmation_id}", "accept" if body.accept else "decline",
        ex=settings.consent_timeout, nx=True,
    ):
        raise HTTPException(409, "Esta confirmacion ya tiene respuesta.")
    return {"status": "received"}
