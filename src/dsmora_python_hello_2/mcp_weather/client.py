import asyncio
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StreamableHttpTransport

from .config import MCP_ENDPOINT

DENIAL_TEXT = "Consulta cancelada: no se otorgó el consentimiento solicitado."
ERROR_TEXT = "No se pudo obtener el clima en este momento."


async def _invoke_get_weather(city: str) -> str:
    access_token = os.environ.get("MCP_ACCESS_TOKEN", "").strip()
    if not access_token:
        return "No se pudo obtener el clima: configura MCP_ACCESS_TOKEN con un access token OAuth vigente."

    consent_denied = False

    async def handle_elicitation(
        message: str,
        response_type: type[Any] | None,
        params: Any,
        context: Any,
    ) -> ElicitResult[dict[str, bool]]:
        nonlocal consent_denied
        print(message)
        try:
            accepted = input("Respuesta (sí/no): ").strip().casefold() in {
                "s",
                "si",
                "sí",
                "yes",
            }
        except EOFError:
            accepted = False

        if accepted:
            return ElicitResult(action="accept", content={"value": True})

        consent_denied = True
        return ElicitResult(action="decline")

    transport = StreamableHttpTransport(
        MCP_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        async with Client(
            transport,
            mode="legacy",
            elicitation_handler=handle_elicitation,
        ) as client:
            result = await client.call_tool("get_weather", {"city": city})
    except Exception:
        return DENIAL_TEXT if consent_denied else ERROR_TEXT

    if consent_denied:
        return DENIAL_TEXT

    if isinstance(result.data, str):
        return result.data

    text = "\n".join(
        block_text
        for block in result.content
        if isinstance((block_text := getattr(block, "text", None)), str)
    )
    return text or ERROR_TEXT


def get_weather(city: str) -> str:
    """Invoke the weather MCP tool through the standalone HTTP server."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_invoke_get_weather(city))
        except Exception:
            return ERROR_TEXT
    return ERROR_TEXT