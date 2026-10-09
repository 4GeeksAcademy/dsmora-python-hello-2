import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call: ToolCall | None = None
    tool_call_id: str | None = None


@dataclass
class ModelResponse:
    text: str | None = None
    tool_call: ToolCall | None = None


class Model(Protocol):
    def generate(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse: ...


CITY_PATTERN = re.compile(r"\b(?:en|de|para|in)\s+([^?!.,]+)", re.IGNORECASE)


class RuleBasedModel:
    """Modelo local sin red que decide las llamadas a herramientas con reglas simples."""

    def generate(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse:
        last = messages[-1]

        if last.role == "tool":
            return ModelResponse(text=f"Tiempo actual: {last.content}")

        city = self._extract_city(last.content)
        if city is None:
            return ModelResponse(text="¿De qué ciudad quieres saber el tiempo?")

        return ModelResponse(tool_call=ToolCall(name="get_wheater", arguments={"city": city}))

    @staticmethod
    def _extract_city(text: str) -> str | None:
        matches = CITY_PATTERN.findall(text)
        if not matches:
            return None
        return matches[-1].strip() or None
