import asyncio
import json
import logging
import os
from typing import Any, Callable

from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import FastMCPError

from .config import MCP_ENDPOINT


def terminal_consent(message: str) -> bool:
    print(message)
    try:
        return input("Respuesta (si/no): ").strip().casefold() in {"s", "si", "sí", "yes"}
    except EOFError:
        return False


async def invoke(
    name: str, arguments: dict[str, Any], token: str, consent: Callable[[str], bool]
) -> Any:
    async def handle_elicitation(message, response_type, params, context):
        accepted = await asyncio.to_thread(consent, message)
        return ElicitResult(action="accept", content={"value": True}) if accepted else ElicitResult(action="decline")

    async with Client(
        StreamableHttpTransport(MCP_ENDPOINT, headers={"Authorization": f"Bearer {token}"}),
        mode="legacy", elicitation_handler=handle_elicitation, timeout=150,
    ) as client:
        result = await client.call_tool(name, arguments)
        if result.is_error:
            raise RuntimeError("La herramienta MCP rechazo la operacion.")
        if result.data is not None:
            return result.data
        return "\n".join(block.text for block in result.content if hasattr(block, "text"))


def call_tool(
    name: str, arguments: dict[str, Any], token: str, consent: Callable[[str], bool]
) -> Any:
    if not token:
        raise RuntimeError("Inicia sesion para usar herramientas MCP.")
    return asyncio.run(invoke(name, arguments, token, consent))


def get_weather(city: str) -> str:
    """CLI callers must provide a delegated token; there is no unauthenticated bypass."""
    try:
        result = call_tool("get_weather", {"city": city}, os.getenv("MCP_ACCESS_TOKEN", ""), terminal_consent)
    except (FastMCPError, RuntimeError, OSError, ValueError) as error:
        logging.getLogger(__name__).warning("Fallo MCP en CLI: %s", type(error).__name__)
        return "No se pudo consultar el clima. Comprueba tu sesion MCP y el servidor."
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
