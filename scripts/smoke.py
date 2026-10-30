"""Explicit operational smoke checks; does not call the paid LLM or external weather API."""

import json
import os
import sys
import time
import uuid

import httpx
import jwt
from websockets.sync.client import connect

from dsmora_python_hello_2.security import SCOPES, database, issue, verify
from dsmora_python_hello_2.web_config import settings

BASE = os.getenv("SMOKE_BASE_URL", "http://frontend:3000")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=20, trust_env=False) as client:
        page = client.get("/")
        require(page.status_code == 200 and "MEXICO LINDO" in page.text, "Frontend no disponible.")
        for url in [
            "http://backend:8000/health/ready", "http://agent:8001/health/ready",
            "http://mcp:8002/health/ready",
        ]:
            require(httpx.get(url, timeout=10, trust_env=False).status_code == 200, f"Servicio no disponible: {url}")
        me = client.get("/api/auth/me").raise_for_status().json()
        headers = {"Origin": settings.origin, "X-CSRF-Token": me["csrf"]}
        require(not me["authenticated"], "La sesion inicial no es invitada.")
        require(
            client.post("/api/tools", json={"name": "list_trip_plans"}, headers=headers).status_code == 403,
            "Un invitado obtuvo acceso a MCP.",
        )
        require(
            client.post("/api/auth/login", json={"email": "test@test.com", "password": "incorrect"}, headers=headers).status_code == 401,
            "Se aceptaron credenciales incorrectas.",
        )
        result = client.post("/api/auth/login", json={
            "email": "test@test.com", "password": os.environ["DEMO_USER_PASSWORD"],
        }, headers=headers)
        result.raise_for_status()
        require("HttpOnly" in result.headers.get("set-cookie", ""), "La cookie no es HttpOnly.")
        identity = result.json()
        headers["X-CSRF-Token"] = identity["csrf"]
        require(identity["authenticated"], "No se completo el login demo.")
        require(
            client.post("/api/tools", json={"name": "list_trip_plans"}, headers={**headers, "Origin": "http://untrusted.invalid"}).status_code == 403,
            "No se protegio el origen.",
        )
        token = client.cookies.get("session")
        claims = verify(token, "backend")
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}},
        }
        with httpx.Client(timeout=10, trust_env=False) as mcp:
            for bearer in [None, token, issue(claims["sub"], claims["sid"], "agent")]:
                h = {"Accept": "application/json, text/event-stream"}
                if bearer:
                    h["Authorization"] = f"Bearer {bearer}"
                response = mcp.post("http://mcp:8002/mcp", headers=h, json=initialize)
                require(response.status_code == 401, "MCP acepto una credencial incorrecta.")
        job = client.post("/api/tools", headers=headers, json={"name": "list_trip_plans"}).raise_for_status().json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = client.get(f"/api/jobs/{job['job_id']}").raise_for_status().json()
            if state["status"] != "running":
                break
            time.sleep(0.25)
        require(state["status"] == "done" and "plans" in state["result"], "No se pudo invocar MCP autenticado.")
        client.post("/api/auth/logout", headers=headers, json={}).raise_for_status()
        try:
            verify(token, "backend")
        except jwt.InvalidTokenError:
            pass
        else:
            raise RuntimeError("Logout no revoco la sesion.")
    print("SMOKE OK: frontend, health, invitados, login, CSRF, MCP autenticado y logout.")


def extended() -> None:
    from fastmcp.exceptions import ToolError
    from dsmora_python_hello_2.mcp_weather.client import call_tool
    from dsmora_python_hello_2.security import new_session, signing_key

    with httpx.Client(base_url=BASE, timeout=20, trust_env=False) as client:
        identity = client.get("/api/auth/me").raise_for_status().json()
        headers = {"Origin": settings.origin, "X-CSRF-Token": identity["csrf"]}
        identity = client.post("/api/auth/login", headers=headers, json={
            "email": "test@test.com", "password": os.environ["DEMO_USER_PASSWORD"],
        }).raise_for_status().json()
        headers["X-CSRF-Token"] = identity["csrf"]

        websocket_url = BASE.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")

        def run(name, arguments, accept):
            job_id = client.post("/api/tools", headers=headers, json={
                "name": name, "arguments": arguments,
            }).raise_for_status().json()["job_id"]
            ticket = client.post(
                "/api/auth/ws-ticket", headers=headers, json={}
            ).raise_for_status().json()["token"]
            deadline, answered, replay_handled = time.monotonic() + 35, set(), False
            with connect(
                f"{websocket_url}/socket/chat",
                origin=settings.origin,
                open_timeout=10,
            ) as socket:
                socket.send(json.dumps({"type": "auth", "token": ticket}))
                require(json.loads(socket.recv()).get("type") == "ready", "No se autentico el WebSocket.")
                socket.send(json.dumps({"type": "attach_job", "job_id": job_id}))
                attached = json.loads(socket.recv())
                require(attached.get("type") == "control_ready", "No se adjunto el canal de control.")

                last_event_id = ""
                while time.monotonic() < deadline:
                    stream_headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
                    with client.stream(
                        "GET", f"/api/jobs/{job_id}/events", headers=stream_headers,
                    ) as response:
                        response.raise_for_status()
                        event_name, data_lines = "", []
                        for line in response.iter_lines():
                            if time.monotonic() >= deadline:
                                break
                            if line.startswith("id:"):
                                last_event_id = line[3:].strip()
                            elif line.startswith("event:"):
                                event_name = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].strip())
                            elif not line and data_lines:
                                event = json.loads("\n".join(data_lines))
                                if event_name == "status":
                                    pending = event.get("pending")
                                    if pending:
                                        if pending.get("version") is not None:
                                            decision = {
                                                "type": "approve",
                                                "job_id": job_id,
                                                "request_id": pending["id"],
                                                "version": pending["version"],
                                                "digest": pending["digest"],
                                                "action": "approve" if accept else "deny",
                                            }
                                        else:
                                            decision = {
                                                "type": "confirm",
                                                "job_id": job_id,
                                                "confirmation_id": pending["id"],
                                                "accept": accept,
                                            }
                                        socket.send(json.dumps(decision))
                                        acknowledgement = json.loads(socket.recv())
                                        require(
                                            acknowledgement.get("type") == "approval_received",
                                            acknowledgement.get("message", "No se registro la decision."),
                                        )
                                        answered.add(pending["id"])
                                        socket.send(json.dumps(decision))
                                        replay = json.loads(socket.recv())
                                        replay_handled = replay.get("type") in {"error", "approval_received"}
                                        require(replay_handled, "No se atendio la decision repetida.")
                                        if replay.get("type") == "error":
                                            require(
                                                replay.get("code") in {"APPROVAL_REJECTED", "NO_ACTIVE_JOB"},
                                                replay.get("message", "Error al repetir la decision."),
                                            )
                                    if event["status"] in {"done", "failed", "interrupted"}:
                                        result = event.get("result")
                                        if event["status"] != "done":
                                            result = {
                                                "status": event["status"],
                                                "error": event.get("error"),
                                            }
                                        return result, bool(answered), replay_handled
                                    if event["status"] == "awaiting_approval":
                                        break
                                event_name, data_lines = "", []
            raise RuntimeError(f"Timeout al ejecutar {name}.")

        result, confirmed, replay_handled = run(
            "save_trip_plan",
            {
                "title": "Tres dias en Puebla",
                "content": (
                    "Propuesta de tres dias en Puebla, Mexico. Dia 1: recorrido a pie por el centro "
                    "historico y visita a museos; traslado local en transporte publico. Dia 2: visita "
                    "a Cholula y caminata por sus espacios culturales; traslado en autobus regional. "
                    "Dia 3: mercados y gastronomia local, con regreso al centro en transporte publico. "
                    "Presupuesto estimado: 1,500 MXN por persona para comidas, entradas y traslados "
                    "locales. Horarios, precios y disponibilidad deben confirmarse."
                ),
            },
            False,
        )
        require(
            confirmed and result["status"] == "failed" and "no se guardo" in (result.get("error") or "").lower(),
            f"Guardar sin consentimiento no fue rechazado: {result!r}",
        )
        require(replay_handled, "No se atendio una aprobacion repetida por WebSocket.")
        title = f"Smoke {uuid.uuid4().hex}"
        result, confirmed, replay_handled = run(
            "save_trip_plan",
            {
                "title": title,
                "content": (
                    "Propuesta de tres dias en Puebla, Mexico. Dia 1: recorrido a pie por el centro "
                    "historico y visita a museos; traslado local en transporte publico. Dia 2: visita "
                    "a Cholula y caminata por sus espacios culturales; traslado en autobus regional. "
                    "Dia 3: mercados y gastronomia local, con regreso al centro en transporte publico. "
                    "Presupuesto estimado: 1,500 MXN por persona para comidas, entradas y traslados "
                    "locales. Horarios, precios y disponibilidad deben confirmarse."
                ),
            },
            True,
        )
        require(confirmed and result["status"] == "saved", f"No se pudo guardar el plan confirmado: {result!r}")
        require(replay_handled, "No se atendio una aprobacion repetida por WebSocket.")
        plan = result["plan"]
        token = client.cookies.get("session")
        claims = verify(token, "backend")
        sid, session = new_session(f"smoke:{uuid.uuid4().hex}", "smoke@example.invalid")
        try:
            other_token = issue(session["sub"], sid, "mcp", SCOPES)
            other_plans = call_tool("list_trip_plans", {}, other_token, lambda _: False)
            require(not any(item["id"] == plan["id"] for item in other_plans["plans"]), "Filtracion de planes.")
            try:
                call_tool("delete_trip_plan", {"plan_id": plan["id"]}, other_token, lambda _: True)
            except (ToolError, RuntimeError):
                pass
            else:
                raise RuntimeError("Se pudo eliminar un plan ajeno.")
            try:
                call_tool("list_trip_plans", {}, issue(session["sub"], sid, "mcp", "weather:read"), lambda _: False)
            except (ToolError, RuntimeError):
                pass
            else:
                raise RuntimeError("No se comprobaron los scopes.")
            initialize = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}},
            }
            good = issue(claims["sub"], claims["sid"], "mcp", SCOPES)
            h = {"Authorization": f"Bearer {good}", "Accept": "application/json, text/event-stream"}
            with httpx.Client(timeout=10, trust_env=False) as wire:
                initial = wire.post("http://mcp:8002/mcp", headers=h, json=initialize)
                initial.raise_for_status()
                mcp_sid = initial.headers["mcp-session-id"]
                crossed = wire.post(
                    "http://mcp:8002/mcp",
                    headers={**h, "Authorization": f"Bearer {other_token}", "Mcp-Session-Id": mcp_sid},
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                )
                require(crossed.status_code == 403, "La sesion MCP no esta ligada a su identidad.")
                wire.delete("http://mcp:8002/mcp", headers={**h, "Mcp-Session-Id": mcp_sid})
                payload = jwt.decode(good, options={"verify_signature": False})
                for replacement in [{"exp": int(time.time()) - 10}, {"iss": "http://invalid.example"}, {"aud": "backend"}]:
                    invalid = jwt.encode({**payload, **replacement}, signing_key(), algorithm="RS256", headers={"kid": "local-1"})
                    rejected = wire.post("http://mcp:8002/mcp", headers={**h, "Authorization": f"Bearer {invalid}"}, json=initialize)
                    require(rejected.status_code == 401, "Se aceptaron claims invalidos.")
        finally:
            database().delete(f"session:{sid}")
        weather, confirmed, replay_handled = run("get_weather", {"city": "Puebla"}, False)
        require(confirmed and "consentimiento" in weather, "No se respeto el rechazo del clima.")
        require(replay_handled, "No se atendio una confirmacion repetida por WebSocket.")
        deleted, confirmed, replay_handled = run("delete_trip_plan", {"plan_id": plan["id"]}, True)
        require(confirmed and deleted["status"] == "deleted", "No se elimino el plan confirmado.")
        require(replay_handled, "No se atendio una confirmacion repetida por WebSocket.")
        client.post("/api/auth/logout", headers=headers, json={}).raise_for_status()
    print("EXTENDED OK: consentimiento, planes privados, scopes, replay, sesiones MCP y claims JWT.")


if __name__ == "__main__":
    try:
        extended() if "--extended" in sys.argv else main()
    except (RuntimeError, httpx.HTTPError) as error:
        print(f"SMOKE FAILED: {error}", file=sys.stderr)
        sys.exit(1)
