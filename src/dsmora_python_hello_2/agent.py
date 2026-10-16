import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .model import Message, Model, ToolCall
from .tools import API_ERROR_TEXT, Tool

SYSTEM_PROMPT = (
    "Eres un asistente que responde en español. Cuando el usuario solicite el tiempo "
    "e indique una ciudad, llama a get_weather sin pedir confirmación previa; "
    "la herramienta MCP solicitará el consentimiento justo antes de consultar."
)


class AgentState(TypedDict):
    messages: Annotated[list[Message], operator.add]
    steps: int


class Agent:
    def __init__(
        self,
        model: Model,
        tools: list[Tool],
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 5,
    ) -> None:
        self.model = model
        self.tools = {tool.name: tool for tool in tools}
        self.schemas = [tool.schema() for tool in tools]
        self.system_message = Message(role="system", content=system_prompt)
        self.max_steps = max_steps
        self.history: list[Message] = []
        self.graph = self._build_graph()

    def run(self, user_input: str) -> str:
        """Ejecuta el grafo con el historial acumulado y devuelve la respuesta final."""
        state = self.graph.invoke(
            {
                "messages": [*self.history, Message(role="user", content=user_input)],
                "steps": 0,
            },
            {"recursion_limit": 2 * self.max_steps + 4},
        )
        self.history = state["messages"]
        return state["messages"][-1].content

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("llm", self._call_model)
        builder.add_node("tools", self._run_tool)
        builder.add_node("limit", self._limit_reached)
        builder.add_edge(START, "llm")
        builder.add_conditional_edges("llm", self._route_after_llm, {"tools": "tools", "end": END})
        builder.add_conditional_edges("tools", self._route_after_tools, {"llm": "llm", "limit": "limit"})
        builder.add_edge("limit", END)
        return builder.compile()

    def _call_model(self, state: AgentState) -> dict[str, Any]:
        response = self.model.generate([self.system_message, *state["messages"]], self.schemas)
        if response.tool_call is None:
            message = Message(role="assistant", content=response.text or "")
        else:
            message = Message(role="assistant", content="", tool_call=response.tool_call)
        return {"messages": [message], "steps": state["steps"] + 1}

    def _run_tool(self, state: AgentState) -> dict[str, Any]:
        call = state["messages"][-1].tool_call
        result = self._execute(call)
        return {"messages": [Message(role="tool", content=result, tool_call_id=call.id)]}

    @staticmethod
    def _limit_reached(state: AgentState) -> dict[str, Any]:
        text = "No se obtuvo una respuesta final dentro del límite de pasos."
        return {"messages": [Message(role="assistant", content=text)]}

    @staticmethod
    def _route_after_llm(state: AgentState) -> str:
        return "end" if state["messages"][-1].tool_call is None else "tools"

    def _route_after_tools(self, state: AgentState) -> str:
        return "limit" if state["steps"] >= self.max_steps else "llm"

    def _execute(self, call: ToolCall) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Error: la herramienta '{call.name}' no existe."
        try:
            return tool.run(call.arguments)
        except TypeError as error:
            return f"Error en los argumentos de '{call.name}': {error}"
        except Exception:
            return API_ERROR_TEXT
