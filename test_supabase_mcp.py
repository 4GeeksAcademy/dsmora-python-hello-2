"""Interactive smoke test: sign in to Supabase and call the protected weather MCP."""

import asyncio
import getpass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dsmora_python_hello_2.mcp_weather.client import _invoke_get_weather
from dsmora_python_hello_2.mcp_weather.config import MCP_AUTH_ISSUER


def main() -> int:
    issuer = MCP_AUTH_ISSUER.rstrip("/")
    if not issuer.endswith("/auth/v1"):
        print("MCP_AUTH_ISSUER debe terminar en /auth/v1.")
        return 1

    project_url = issuer.removesuffix("/auth/v1")
    email = input("Correo del usuario Supabase: ").strip()
    password = getpass.getpass("Contraseña: ")
    api_key = (
        os.environ.get("SUPABASE_ANON_KEY", "").strip()
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    )
    if not api_key:
        api_key = getpass.getpass(
            "Clave anon/publishable de Supabase (no service_role): "
        ).strip()

    request = Request(
        f"{project_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"apikey": api_key, "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            token_data = json.load(response)
    except HTTPError as error:
        print(f"Supabase rechazó el inicio de sesión (HTTP {error.code}).")
        print("Comprueba usuario, contraseña, confirmación del email y configuración de Auth.")
        return 1
    except (URLError, TimeoutError) as error:
        print(f"No se pudo conectar con Supabase ({type(error).__name__}).")
        return 1

    access_token = token_data.get("access_token")
    if not access_token:
        print("Supabase respondió, pero no devolvió un access token.")
        return 1

    # El token vive solo en este proceso y no se escribe en disco ni se muestra.
    os.environ["MCP_ACCESS_TOKEN"] = access_token
    city = input("Ciudad de México para consultar: ").strip()
    try:
        print(asyncio.run(_invoke_get_weather(city)))
    except Exception as error:
        print(f"Falló la llamada al MCP ({type(error).__name__}).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
