import getpass
import json
import uuid

import httpx
from websockets.sync.client import connect

from .web_config import settings


def main(login: bool = False) -> None:
    """Use the web session flow, including MCP consent, without exposing delegated tokens."""
    with httpx.Client(base_url=settings.origin, timeout=20, trust_env=False) as client:
        identity = client.get("/api/auth/me").raise_for_status().json()
        headers = {"Origin": settings.origin, "X-CSRF-Token": identity["csrf"]}
        if login:
            email = input("Email: ").strip()
            password = getpass.getpass("Contrasena: ")
            identity = client.post(
                "/api/auth/login", headers=headers, json={"email": email, "password": password}
            ).raise_for_status().json()
            headers["X-CSRF-Token"] = identity["csrf"]
        conversation_id = uuid.uuid4().hex
        token = client.post(
            "/api/auth/ws-ticket", headers=headers, json={}
        ).raise_for_status().json()["token"]
        websocket_url = settings.origin.replace("https://", "wss://").replace("http://", "ws://")
        print("Chat web. Escribe 'salir' para terminar.")
        try:
            with connect(
                f"{websocket_url}/socket/chat",
                origin=settings.origin,
                open_timeout=10,
            ) as socket:
                socket.send(json.dumps({"type": "auth", "token": token}))
                ready = json.loads(socket.recv())
                if ready.get("type") != "ready":
                    raise RuntimeError(ready.get("message", "No se pudo autenticar el chat."))
                while True:
                    message = input("> ").strip()
                    if message.casefold() in {"salir", "exit"}:
                        break
                    if not message:
                        continue
                    job_id = client.post(
                        "/api/chat",
                        headers=headers,
                        json={"message": message, "conversation_id": conversation_id},
                    ).raise_for_status().json()["job_id"]
                    socket.send(json.dumps({"type": "attach_job", "job_id": job_id}))
                    attached = json.loads(socket.recv())
                    if attached.get("type") != "control_ready":
                        raise RuntimeError(attached.get("message", "No se pudo conectar el canal de control."))

                    last_event_id = ""
                    streamed = False
                    completed = False
                    while not completed:
                        request_headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
                        with client.stream(
                            "GET", f"/api/jobs/{job_id}/events", headers=request_headers,
                        ) as response:
                            response.raise_for_status()
                            event_name = ""
                            data_lines: list[str] = []
                            for line in response.iter_lines():
                                if line.startswith("id:"):
                                    last_event_id = line[3:].strip()
                                elif line.startswith("event:"):
                                    event_name = line[6:].strip()
                                elif line.startswith("data:"):
                                    data_lines.append(line[5:].strip())
                                elif not line and data_lines:
                                    event = json.loads("\n".join(data_lines))
                                    if event_name == "token":
                                        print(event.get("text", ""), end="", flush=True)
                                        streamed = True
                                    elif event_name == "status":
                                        pending = event.get("pending")
                                        if pending:
                                            print(pending["message"])
                                            accept = input("Autorizar (si/no): ").strip().casefold() in {
                                                "si", "sí", "s", "yes"
                                            }
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
                                            if acknowledgement.get("type") != "approval_received":
                                                raise RuntimeError(
                                                    acknowledgement.get("message", "No se registro la decision.")
                                                )
                                        elif event["status"] in {"done", "failed", "interrupted"}:
                                            if event["status"] == "failed":
                                                print(event.get("error") or "El trabajo ha fallado.")
                                            elif event["status"] == "done" and not streamed:
                                                print(event.get("result"))
                                            completed = True
                                            break
                                        if event["status"] == "awaiting_approval":
                                            break
                                    event_name, data_lines = "", []
                            if completed:
                                if streamed:
                                    print()
                                break
        finally:
            client.post("/api/auth/logout", headers=headers, json={}).raise_for_status()
