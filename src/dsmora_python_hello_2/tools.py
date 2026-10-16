from dataclasses import dataclass
from typing import Any, Callable

# Texto neutro que sustituye cualquier fallo de una API externa; no expone detalles técnicos.
API_ERROR_TEXT = "No se pudo obtener la información en este momento."

from .mcp_weather.client import get_weather


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., str]

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def run(self, arguments: dict[str, Any]) -> str:
        return self.function(**arguments)


WEATHER_TOOL = Tool(
    name="get_weather",
    description="Solicita consentimiento explícito y, si se autoriza, obtiene el tiempo actual de una ciudad.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Nombre de la ciudad, por ejemplo Madrid"},
        },
        "required": ["city"],
    },
    function=get_weather,
)
