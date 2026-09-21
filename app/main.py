import json
import os

from fastapi import FastAPI
from redis import Redis

from .celery_app import DLQ_KEY, add
## PRODUCER 

app = FastAPI(title="Cola Redis + Celery")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "API activa"}


@app.post("/tasks/add")
def enqueue_add(x: int, y: int) -> dict[str, str]:
    """Encola una suma y devuelve el identificador de la tarea."""
    task = add.delay(x, y)
    return {"task_id": task.id, "status": "queued"}


@app.get("/tasks/{task_id}")
def task_status(task_id: str) -> dict[str, str | int]:
    task = add.AsyncResult(task_id)
    response: dict[str, str | int] = {"task_id": task_id, "status": task.status}
    if task.successful():
        response["result"] = task.result
    elif task.failed():
        response["error"] = str(task.result)
    return response


def dlq_redis() -> Redis:
    return Redis.from_url(
        os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )


@app.get("/dlq")
def list_dlq() -> dict[str, object]:
    """Lista fallos pendientes, separados por criticidad."""
    client = dlq_redis()
    try:
        entries = [json.loads(item) for item in client.hvals(f"{DLQ_KEY}:items")]
    finally:
        client.close()
    return {
        "count": len(entries),
        "hard_errors": [entry for entry in entries if entry["severity"] == "hard"],
        "soft_errors": [entry for entry in entries if entry["severity"] == "soft"],
    }


@app.post("/dlq/{task_id}/reprocess")
def reprocess_dlq_task(task_id: str) -> dict[str, str]:
    """Reencola una tarea de la DLQ y la elimina de pendientes."""
    client = dlq_redis()
    try:
        raw_entry = client.hget(f"{DLQ_KEY}:items", task_id)
        if raw_entry is None:
            return {"task_id": task_id, "status": "not_found"}
        entry = json.loads(raw_entry)
        new_task = add.delay(*entry.get("args", []), **entry.get("kwargs", {}))
        client.hdel(f"{DLQ_KEY}:items", task_id)
        client.lrem(DLQ_KEY, 0, task_id)
        return {"task_id": new_task.id, "status": "requeued"}
    finally:
        client.close()
