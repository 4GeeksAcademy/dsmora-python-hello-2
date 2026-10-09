import json
import urllib.error
import urllib.request
from typing import Any

from .model import Message, ModelResponse, ToolCall

TIMEOUT_SECONDS = 60


def _to_api_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}

    if message.tool_call is not None:
        call = message.tool_call
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
            ],
        }

    return {"role": message.role, "content": message.content}


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OpenAICompatibleModel:
    """Cliente para APIs de chat compatibles con OpenAI (POST a chat/completions)."""

    def __init__(self, api_url: str, model: str, api_key: str) -> None:
        base = api_url.rstrip("/")
        self.api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.model = model
        self.api_key = api_key

    def generate(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]

        data = self._post(payload)

        try:
            message = data["choices"][0]["message"]
            raw_calls = message.get("tool_calls") or []
            if raw_calls:
                raw = raw_calls[0]
                return ModelResponse(
                    tool_call=ToolCall(
                        id=raw.get("id", ""),
                        name=raw["function"]["name"],
                        arguments=_parse_arguments(raw["function"].get("arguments")),
                    )
                )
            return ModelResponse(text=message.get("content") or "")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise RuntimeError(f"Respuesta inesperada del LLM: {data}") from error

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"El LLM respondió con HTTP {error.code}: {detail}") from error
        except (OSError, ValueError) as error:
            raise RuntimeError(f"No se pudo llamar al LLM: {error}") from error
