"""Explicit operational smoke checks; does not call the paid LLM or external weather API."""

import os
import sys
import time
import uuid

import httpx
import jwt

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

        def run(name, arguments, accept):
            job_id = client.post("/api/tools", headers=headers, json={
                "name": name, "arguments": arguments,
            }).raise_for_status().json()["job_id"]
            deadline, answered = time.monotonic() + 35, set()
            while time.monotonic() < deadline:
                state = client.get(f"/api/jobs/{job_id}").raise_for_status().json()
                pending = state.get("pending")
                if pending and pending["id"] not in answered:
                    payload = {"confirmation_id": pending["id"], "accept": accept}
                    client.post(f"/api/jobs/{job_id}/confirm", headers=headers, json=payload).raise_for_status()
                    replay = client.post(f"/api/jobs/{job_id}/confirm", headers=headers, json=payload)
                    require(replay.status_code == 409, "Se acepto una confirmacion repetida.")
                    answered.add(pending["id"])
                if state["status"] != "running":
                    require(state["status"] == "done", f"Fallo en {name}: {state.get('error')}")
                    return state["result"], bool(answered)
                time.sleep(0.25)
            raise RuntimeError(f"Timeout al ejecutar {name}.")

        result, confirmed = run("save_trip_plan", {"title": "Smoke cancelled", "content": "Plan de Puebla."}, False)
        require(confirmed and result["status"] == "cancelled", "Guardar sin consentimiento no fue cancelado.")
        title = f"Smoke {uuid.uuid4().hex}"
        result, confirmed = run("save_trip_plan", {"title": title, "content": "Plan de prueba por Puebla, Mexico."}, True)
        require(confirmed and result["status"] == "saved", "No se pudo guardar el plan confirmado.")
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
        weather, confirmed = run("get_weather", {"city": "Puebla"}, False)
        require(confirmed and "consentimiento" in weather, "No se respeto el rechazo del clima.")
        deleted, confirmed = run("delete_trip_plan", {"plan_id": plan["id"]}, True)
        require(confirmed and deleted["status"] == "deleted", "No se elimino el plan confirmado.")
        client.post("/api/auth/logout", headers=headers, json={}).raise_for_status()
    print("EXTENDED OK: consentimiento, planes privados, scopes, replay, sesiones MCP y claims JWT.")


if __name__ == "__main__":
    try:
        extended() if "--extended" in sys.argv else main()
    except (RuntimeError, httpx.HTTPError) as error:
        print(f"SMOKE FAILED: {error}", file=sys.stderr)
        sys.exit(1)
