import os
import random
import time
import json
from datetime import datetime, timezone

import requests
from celery import Celery
from celery.signals import task_failure
from redis import Redis
## Workers

# La DLQ se mantiene separada del backend de resultados para que el usuario
# pueda inspeccionar y reprocesar los mensajes fallidos.
DLQ_KEY = "celery:dlq"

celery_app = Celery(
    "tasks",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)

# Evita que un worker reserve muchas tareas por adelantado. Así las tareas
# permanecen encoladas hasta que haya un worker disponible para procesarlas.
celery_app.conf.update(
    task_default_retry_delay=2, ## tiempo de espera antes de reintentar una tarea fallida (en segundos)
    worker_prefetch_multiplier=2,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_soft_time_limit=25,
    task_time_limit=30,
)


class SimulatedQueueError(Exception):
    """Error controlado para probar los reintentos y el estado FAILURE."""


class SoftQueueError(SimulatedQueueError):
    """Fallo transitorio: se reintenta antes de enviarlo a la DLQ."""


class HardQueueError(SimulatedQueueError):
    """Fallo permanente: se envía directamente a la DLQ."""


@celery_app.task(
    name="tasks.add",
    bind=True,
    autoretry_for=(requests.Timeout, ConnectionError, SoftQueueError),
    max_retries=3,
    retry_backoff=True, ## activar el retroceso exponencial 
)
def add(self, x: int, y: int) -> int:
    """Tarea de ejemplo ejecutada por un worker Celery."""
    # Fallo intencional: permite comprobar que Celery detecta el error y
    # reintenta la tarea sin depender de un servicio externo defectuoso.
    time.sleep(5)
    randomError = random.random()
    if randomError < 0.15:
        raise HardQueueError("Fallo simulado de la cola (probabilidad 15%): hard error")
    if randomError < 0.5:
        raise SoftQueueError("Fallo simulado de la cola (probabilidad 50%): soft error")

    # Simula un procesamiento que podría tardar un poco.
    return x + y


@task_failure.connect
def add_to_dlq(sender=None, task_id=None, exception=None, args=None, kwargs=None,
                traceback=None, einfo=None, **_):
    """Acumula en Redis las tareas que agotaron reintentos o tuvieron hard error."""
    if task_id is None or exception is None:
        return

    severity = "hard" if isinstance(exception, HardQueueError) else "soft"
    message = {
        "task_id": task_id,
        "task": sender.name if sender else "tasks.add",
        "args": list(args or []),
        "kwargs": kwargs or {},
        "severity": severity,
        "error_type": type(exception).__name__,
        "error": str(exception),
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "traceback": str(einfo or traceback or ""),
    }
    redis_client = Redis.from_url(
        os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    serialized = json.dumps(message, ensure_ascii=False)
    redis_client.hset(f"{DLQ_KEY}:items", task_id, serialized)
    redis_client.rpush(DLQ_KEY, task_id)
    redis_client.close()
