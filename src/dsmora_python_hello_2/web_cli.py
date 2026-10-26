import getpass
import time

import httpx

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
        import uuid

        conversation_id = uuid.uuid4().hex
        print("Chat web. Escribe 'salir' para terminar.")
        try:
            while True:
                message = input("> ").strip()
                if message.casefold() in {"salir", "exit"}:
                    break
                if not message:
                    continue
                job = client.post(
                    "/api/chat", headers=headers,
                    json={"message": message, "conversation_id": conversation_id},
                ).raise_for_status().json()
                answered = set()
                while True:
                    state = client.get(f"/api/jobs/{job['job_id']}").raise_for_status().json()
                    if state["status"] != "running":
                        print(state.get("error") or state.get("result"))
                        break
                    pending = state.get("pending")
                    if pending and pending["id"] not in answered:
                        print(pending["message"])
                        accept = input("Autorizar (si/no): ").strip().casefold() in {"si", "sí", "s", "yes"}
                        client.post(
                            f"/api/jobs/{job['job_id']}/confirm", headers=headers,
                            json={"confirmation_id": pending["id"], "accept": accept},
                        ).raise_for_status()
                        answered.add(pending["id"])
                    time.sleep(0.8)
        finally:
            client.post("/api/auth/logout", headers=headers, json={}).raise_for_status()
