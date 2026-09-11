from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task
from prefect.context import get_run_context
from prefect.tasks import task_input_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTING_DIR = PROJECT_ROOT / "data" / "reporting"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
VALID_ACTIONS = {"page_view", "signup", "add_to_cart", "purchase", "error"}


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _sample_events() -> list[dict[str, Any]]:
    return [
        {"event_id": "evt-001", "user_id": 101, "timestamp": "2026-09-01T09:00:00Z", "action": " PAGE_VIEW ", "amount": None},
        {"event_id": "evt-002", "user_id": "101", "timestamp": "2026-09-01 09:04:00", "action": "Signup", "amount": None},
        {"event_id": "evt-003", "user_id": 202, "timestamp": "09/01/2026 09:08:00", "action": " ADD_TO_CART ", "amount": None},
        {"event_id": "evt-004", "user_id": "202", "timestamp": "2026/09/01 09:12:00", "action": "PURCHASE", "amount": "49.90"},
        {"event_id": "evt-004", "user_id": "202", "timestamp": "2026/09/01 09:12:00", "action": "PURCHASE", "amount": "49.90"},
        {"event_id": "evt-005", "user_id": 303, "timestamp": "2026-09-01T09:15:00+00:00", "action": "error", "amount": None},
        {"event_id": "evt-006", "user_id": " 303 ", "timestamp": "2026-09-01T09:20:00Z", "action": "page_view", "amount": None},
        {"event_id": "evt-007", "user_id": 404, "timestamp": "2026-09-01T09:24:00Z", "action": "purchase", "amount": "not-a-number"},
        {"event_id": "evt-008", "user_id": None, "timestamp": "2026-09-01T09:28:00Z", "action": "page_view", "amount": None},
        {"event_id": "evt-009", "user_id": 505, "timestamp": "not-a-date", "action": "signup", "amount": None},
        {"event_id": "evt-010", "user_id": 505, "timestamp": "2026-09-01T09:32:00Z", "action": " purchase ", "amount": 20},
        {"event_id": "evt-011", "user_id": 606, "timestamp": "2026-09-01T09:35:00Z", "action": None, "amount": None},
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp ausente")

    raw_value = value.strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        for date_format in ("%m/%d/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw_value, date_format)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"timestamp invalido: {value}") from None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Los reintentos representan fallos transitorios al leer almacenamiento externo.
@task(retries=3, retry_delay_seconds=2)
def extract_events(source_path: str) -> list[dict[str, Any]]:
    logger = get_run_logger()
    path = _resolve_path(source_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as destination:
            for event in _sample_events():
                destination.write(json.dumps(event) + "\n")
        logger.warning("Fuente ausente; se generaron datos reproducibles en %s", path)

    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError(f"La linea {line_number} no contiene un objeto JSON")
                events.append(event)
    logger.info("Ingestados %s eventos crudos sin modificarlos", len(events))
    return events


# La clave depende de las entradas; el resultado transformado es valido por una hora.
@task(cache_key_fn=task_input_hash, cache_expiration=timedelta(hours=1))
def transform_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger = get_run_logger()
    clean_events: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    invalid_count = 0
    duplicate_count = 0

    for raw_event in raw_events:
        try:
            user_value = raw_event.get("user_id")
            if user_value is None or not str(user_value).strip():
                raise ValueError("user_id ausente")
            user_id = str(user_value).strip()

            action_value = raw_event.get("action")
            if not isinstance(action_value, str):
                raise ValueError("action ausente")
            action = "_".join(action_value.strip().lower().split())
            if action not in VALID_ACTIONS:
                raise ValueError(f"action desconocida: {action}")

            timestamp = _parse_timestamp(raw_event.get("timestamp"))
            amount: float | None = None
            if action == "purchase":
                amount = float(raw_event.get("amount"))
                if amount < 0:
                    raise ValueError("amount negativo")

            event_id_value = raw_event.get("event_id")
            event_id = str(event_id_value).strip() if event_id_value is not None else ""
            deduplication_key = event_id or json.dumps(
                [user_id, timestamp.isoformat(), action, amount], separators=(",", ":")
            )
            if deduplication_key in seen_events:
                duplicate_count += 1
                continue

            seen_events.add(deduplication_key)
            clean_events.append(
                {
                    "event_id": event_id or None,
                    "user_id": user_id,
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "action": action,
                    "amount": amount,
                }
            )
        except (TypeError, ValueError):
            invalid_count += 1

    logger.info(
        "Transformados %s eventos; descartados %s invalidos y %s duplicados",
        len(clean_events), invalid_count, duplicate_count,
    )
    return clean_events


@task(cache_key_fn=task_input_hash, cache_expiration=timedelta(hours=1))
def transform_product_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapta el contrato del origen producto al esquema canonico."""
    logger = get_run_logger()
    clean_events: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    invalid_count = 0
    duplicate_count = 0
    action_mapping = {
        "VIEW": "page_view",
        "CART_ADD": "add_to_cart",
        "ORDER": "purchase",
        "FAIL": "error",
        "SIGNUP": "signup",
    }

    for raw_event in raw_events:
        try:
            customer = raw_event.get("customer")
            if customer is None or not str(customer).strip():
                raise ValueError("customer ausente")
            user_id = str(customer).strip()
            event_type = raw_event.get("event_type")
            if not isinstance(event_type, str) or event_type.strip().upper() not in action_mapping:
                raise ValueError("event_type desconocido")
            action = action_mapping[event_type.strip().upper()]
            timestamp = _parse_timestamp(raw_event.get("occurred_at"))
            amount: float | None = None
            if action == "purchase":
                amount = float(raw_event.get("price"))
                if amount < 0:
                    raise ValueError("price negativo")
            event_id = str(raw_event.get("product_event_id", "")).strip()
            deduplication_key = event_id or json.dumps(
                [user_id, timestamp.isoformat(), action, amount], separators=(",", ":")
            )
            if deduplication_key in seen_events:
                duplicate_count += 1
                continue
            seen_events.add(deduplication_key)
            clean_events.append(
                {
                    "event_id": event_id or None,
                    "user_id": user_id,
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "action": action,
                    "amount": amount,
                }
            )
        except (TypeError, ValueError):
            invalid_count += 1

    logger.info(
        "Transformados %s eventos de producto; descartados %s invalidos y %s duplicados",
        len(clean_events), invalid_count, duplicate_count,
    )
    return clean_events

@task
def calculate_kpis(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        raise ValueError("No hay eventos validos para calcular KPIs")

    users = {event["user_id"] for event in events}
    purchase_events = [event for event in events if event["action"] == "purchase"]
    purchasing_users = {event["user_id"] for event in purchase_events}
    error_count = sum(event["action"] == "error" for event in events)
    timestamps = [event["timestamp"] for event in events]
    return {
        "total_events": len(events),
        "unique_users": len(users),
        "purchases": len(purchase_events),
        "revenue": round(sum(event["amount"] for event in purchase_events), 2),
        "conversion_rate": round(len(purchasing_users) / len(users), 4),
        "error_rate": round(error_count / len(events), 4),
        "window_start": min(timestamps),
        "window_end": max(timestamps),
    }


# Los reintentos representan fallos transitorios al escribir almacenamiento externo.
@task(retries=3, retry_delay_seconds=2)
def load_kpis(kpis: dict[str, Any]) -> dict[str, Any]:
    logger = get_run_logger()
    REPORTING_DIR.mkdir(parents=True, exist_ok=True)
    database_path = REPORTING_DIR / "business_kpis.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reporting_kpis (
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                total_events INTEGER NOT NULL,
                unique_users INTEGER NOT NULL,
                purchases INTEGER NOT NULL,
                revenue REAL NOT NULL,
                conversion_rate REAL NOT NULL,
                error_rate REAL NOT NULL,
                loaded_at TEXT NOT NULL,
                PRIMARY KEY (window_start, window_end)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reporting_kpis (
                window_start, window_end, total_events, unique_users, purchases,
                revenue, conversion_rate, error_rate, loaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(window_start, window_end) DO UPDATE SET
                total_events = excluded.total_events,
                unique_users = excluded.unique_users,
                purchases = excluded.purchases,
                revenue = excluded.revenue,
                conversion_rate = excluded.conversion_rate,
                error_rate = excluded.error_rate,
                loaded_at = excluded.loaded_at
            """,
            (
                kpis["window_start"], kpis["window_end"], kpis["total_events"],
                kpis["unique_users"], kpis["purchases"], kpis["revenue"],
                kpis["conversion_rate"], kpis["error_rate"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        rows_for_window = connection.execute(
            "SELECT COUNT(*) FROM reporting_kpis WHERE window_start = ? AND window_end = ?",
            (kpis["window_start"], kpis["window_end"]),
        ).fetchone()[0]

    _write_json(REPORTING_DIR / "latest_kpis.json", kpis)
    logger.info("KPIs cargados con UPSERT; filas para la ventana: %s", rows_for_window)
    return {"database_path": str(database_path), "rows_for_window": rows_for_window}


@task
def export_eval_snapshot(
    events: list[dict[str, Any]],
    kpis: dict[str, Any],
    fail_intentionally: bool = False,
) -> str:
    if fail_intentionally:
        raise RuntimeError("Fallo intencional del snapshot opcional")
    snapshot_path = PROCESSED_DIR / "eval_snapshot.json"
    _write_json(
        snapshot_path,
        {"generated_at": datetime.now(timezone.utc).isoformat(), "sample": events[:3], "kpis": kpis},
    )
    return str(snapshot_path)


@flow(name="web-telemetry-subflow")
def web_telemetry_subflow(
    source_path: str = "data/raw/telemetry_events.jsonl",
) -> dict[str, Any]:
    """Extrae y transforma el origen de telemetria web."""
    raw_events = extract_events(source_path)
    clean_events = transform_events(raw_events)
    return {"events": clean_events, "records_extracted": len(raw_events)}


@flow(name="product-telemetry-subflow")
def product_telemetry_subflow(
    source_path: str = "data/raw/product_events.jsonl",
) -> dict[str, Any]:
    """Extrae y transforma el origen de telemetria de producto."""
    raw_events = extract_events(source_path)
    clean_events = transform_product_events(raw_events)
    return {"events": clean_events, "records_extracted": len(raw_events)}


def _record_pipeline_run(metadata: dict[str, Any]) -> None:
    REPORTING_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORTING_DIR / "pipeline_runs.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(metadata) + "\n")


@flow(name="business-performance-pipeline", log_prints=True)
def business_performance_pipeline(
    source_path: str = "data/raw/telemetry_events.jsonl",
    product_source_path: str = "data/raw/product_events.jsonl",
    fail_optional_snapshot: bool = False,
) -> dict[str, Any]:
    logger = get_run_logger()
    started_at = datetime.now(timezone.utc)
    run_id = str(get_run_context().flow_run.id)
    records_extracted = 0
    records_transformed = 0
    pipeline_status = "failed"
    error: str | None = None

    try:
        web_result = web_telemetry_subflow(source_path)
        product_result = product_telemetry_subflow(product_source_path)
        web_events = web_result["events"]
        product_events = product_result["events"]
        clean_events = web_events + product_events
        records_extracted = web_result["records_extracted"] + product_result["records_extracted"]
        records_transformed = len(clean_events)
        kpis = calculate_kpis(clean_events)
        load_result = load_kpis(kpis)
        snapshot_state = export_eval_snapshot(
            clean_events, kpis,
            fail_intentionally=fail_optional_snapshot,
            return_state=True,
        )
        snapshot_status = snapshot_state.name
        if snapshot_state.is_failed():
            pipeline_status = "completed_with_optional_failure"
            logger.warning(
                "El snapshot opcional fallo, pero el flow continua: %s",
                snapshot_state.message,
            )
        else:
            pipeline_status = "completed"

        logger.info(
            "Resumen: extraidos=%s, transformados=%s, kpis=%s, carga=%s, snapshot=%s",
            records_extracted, records_transformed, kpis, load_result, snapshot_status,
        )
        return kpis
    except Exception as caught_error:
        error = f"{type(caught_error).__name__}: {caught_error}"
        logger.error("Fallo critico; el flow se detiene: %s", error)
        raise
    finally:
        _record_pipeline_run(
            {
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": pipeline_status,
                "records_extracted": records_extracted,
                "records_transformed": records_transformed,
                "error": error,
            }
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo de una canalizacion resiliente con Prefect 3")
    parser.add_argument(
        "--source-path", default="data/raw/telemetry_events.jsonl",
        help="Ruta al archivo JSONL de eventos crudos",
    )
    parser.add_argument(
        "--fail-optional-snapshot", action="store_true",
        help="Provoca un fallo controlado en la task opcional",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    business_performance_pipeline.serve(
        name="business-performance-report-deployment",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        parameters={
            "source_path": arguments.source_path,
            "fail_optional_snapshot": arguments.fail_optional_snapshot,
        },
    )
