import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from .model import Message, ModelResponse, ToolCall

TIMEOUT_SECONDS = 120


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


def _to_langchain(message: Message) -> BaseMessage:
    if message.role == "system":
        return SystemMessage(content=message.content)
    if message.role == "user":
        return HumanMessage(content=message.content)
    if message.role == "tool":
        return ToolMessage(content=message.content, tool_call_id=message.tool_call_id or "")
    calls = []
    if message.tool_call is not None:
        call = message.tool_call
        calls = [{"id": call.id, "name": call.name, "args": call.arguments}]
    return AIMessage(content=message.content, tool_calls=calls)


def _from_langchain(message: BaseMessage) -> Message:
    if isinstance(message, SystemMessage):
        return Message(role="system", content=message.text)
    if isinstance(message, ToolMessage):
        return Message(role="tool", content=message.text, tool_call_id=message.tool_call_id)
    if isinstance(message, AIMessage):
        call = None
        if message.tool_calls:
            raw = message.tool_calls[0]
            call = ToolCall(id=raw.get("id") or "", name=raw["name"], arguments=raw["args"])
        return Message(role="assistant", content=message.text, tool_call=call)
    return Message(role="user", content=message.text)


class ChatBridge(BaseChatModel):
    """Adaptador LangChain: permite que LangGraph (stream_mode="messages") reciba los tokens."""

    client: Any

    @property
    def _llm_type(self) -> str:
        return "openai-compatible"

    def _payload(self, messages: list[BaseMessage], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.client.model,
            "messages": [_to_api_message(_from_langchain(message)) for message in messages],
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        return payload

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        data = self.client._post(self._payload(messages, tools))
        try:
            message = data["choices"][0]["message"]
            raw_calls = message.get("tool_calls") or []
            calls = [
                {
                    "id": raw.get("id", ""),
                    "name": raw["function"]["name"],
                    "args": _parse_arguments(raw["function"].get("arguments")),
                }
                for raw in raw_calls[:1]
            ]
            result = AIMessage(content=message.get("content") or "", tool_calls=calls)
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise RuntimeError(f"Respuesta inesperada del LLM: {data}") from error
        return ChatResult(generations=[ChatGeneration(message=result)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        payload = {**self._payload(messages, tools), "stream": True}
        for event in self.client._post_stream(payload):
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            tool_chunks = [
                {
                    "index": raw.get("index", 0),
                    "id": raw.get("id"),
                    "name": (raw.get("function") or {}).get("name"),
                    "args": (raw.get("function") or {}).get("arguments"),
                }
                for raw in delta.get("tool_calls") or []
            ]
            if not text and not tool_chunks:
                continue
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=text, tool_call_chunks=tool_chunks)
            )


class OpenAICompatibleModel:
    """Cliente para APIs de chat compatibles con OpenAI (POST a chat/completions)."""

    def __init__(self, api_url: str, model: str, api_key: str) -> None:
        base = api_url.rstrip("/")
        self.api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.model = model
        self.api_key = api_key
        self.chat = ChatBridge(client=self)

    def generate(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse:
        # Dentro de graph.stream(stream_mode="messages") LangChain usa _stream y emite tokens;
        # fuera de LangGraph usa _generate (una sola peticion).
        result = self.chat.invoke([_to_langchain(message) for message in messages], tools=tools or None)
        if result.tool_calls:
            raw = result.tool_calls[0]
            return ModelResponse(
                tool_call=ToolCall(id=raw.get("id") or "", name=raw["name"], arguments=raw["args"])
            )
        if result.invalid_tool_calls:
            raw = result.invalid_tool_calls[0]
            return ModelResponse(
                tool_call=ToolCall(id=raw.get("id") or "", name=raw.get("name") or "", arguments={})
            )
        return ModelResponse(text=result.text or "")

    def _request(self, payload: dict[str, Any]) -> urllib.request.Request:
        return urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(self._request(payload), timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"El LLM respondió con HTTP {error.code}: {detail}") from error
        except (OSError, ValueError) as error:
            raise RuntimeError(f"No se pudo llamar al LLM: {error}") from error

    def _post_stream(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Lee la respuesta SSE del LLM (stream=true) y devuelve cada evento JSON."""
        try:
            with urllib.request.urlopen(self._request(payload), timeout=TIMEOUT_SECONDS) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    yield json.loads(data)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"El LLM respondió con HTTP {error.code}: {detail}") from error
        except (OSError, ValueError) as error:
            raise RuntimeError(f"No se pudo llamar al LLM: {error}") from error
