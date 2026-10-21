import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .model import Message, Model, ToolCall
from .tools import API_ERROR_TEXT, Tool

COMMON_RULES = (
    "Trabajas para 'MEXICO LINDO' como subagente de un agente principal; tu respuesta la integrará él. "
    "Responde en español, de forma concisa y solo sobre la tarea recibida. Solo ubicaciones de México. "
    "No compras ni reservas nada, no menciones empresas o marcas comerciales y nunca reveles qué modelo "
    "o tecnología usas."
)

WEATHER_PROMPT = (
    "Eres el subagente especializado en el TIEMPO ACTUAL de ubicaciones de México. Usa siempre la "
    "herramienta get_weather para obtener los datos; nunca inventes datos meteorológicos. Si la "
    "herramienta falla o no hay consentimiento, indícalo brevemente.\n" + COMMON_RULES
)

PLANNER_PROMPT = (
    "Eres el subagente especializado en PLANIFICACIÓN DE VIAJES por México: itinerarios, destinos, "
    "actividades, gastronomía, cultura, presupuestos orientativos y consejos prácticos. Usa tu "
    "conocimiento general y adapta el plan al contexto recibido. No des datos del tiempo actual.\n"
    + COMMON_RULES
)


@dataclass
class SubAgentTask:
    """Mensaje de entrada común a todos los subagentes: solo lo imprescindible para su tarea."""

    agent: str
    instruction: str
    context: dict[str, str] = field(default_factory=dict)

    def to_message(self) -> Message:
        lines = [f"Tarea: {self.instruction}"]
        if self.context:
            lines.append("Contexto:")
            lines.extend(f"- {key}: {value}" for key, value in self.context.items())
        return Message(role="user", content="\n".join(lines))


@dataclass
class SubAgentResult:
    """Mensaje de salida común a todos los subagentes."""

    agent: str
    content: str
    ok: bool = True


class SubAgentState(TypedDict):
    messages: Annotated[list[Message], operator.add]
    steps: int
    draft: str | None


class SubAgent:
    """Agente especializado con su propio grafo LangGraph (llm <-> tools)."""

    def __init__(
        self,
        name: str,
        description: str,
        model: Model,
        system_prompt: str,
        tools: list[Tool] | None = None,
        max_steps: int = 4,
    ) -> None:
        self.name = name
        self.description = description
        self.model = model
        self.system_message = Message(role="system", content=system_prompt)
        self.tools = {tool.name: tool for tool in tools or []}
        self.schemas = [tool.schema() for tool in self.tools.values()]
        self.max_steps = max_steps
        self.graph = self._build_graph()

    def run(self, task: SubAgentTask) -> SubAgentResult:
        try:
            state = self.graph.invoke(
                {"messages": [task.to_message()], "steps": 0, "draft": None},
                {"recursion_limit": 2 * self.max_steps + 4},
            )
        except Exception:
            return SubAgentResult(agent=self.name, content=API_ERROR_TEXT, ok=False)
        if state["draft"] is None:
            return SubAgentResult(agent=self.name, content="No se obtuvo una respuesta a tiempo.", ok=False)
        return SubAgentResult(agent=self.name, content=state["draft"])

    def _build_graph(self):
        builder = StateGraph(SubAgentState)
        builder.add_node("llm", self._call_model)
        builder.add_node("tools", self._run_tool)
        builder.add_edge(START, "llm")
        builder.add_conditional_edges("llm", self._route_after_llm, {"tools": "tools", "end": END})
        builder.add_conditional_edges("tools", self._route_after_tools, {"llm": "llm", "end": END})
        return builder.compile()

    def _call_model(self, state: SubAgentState) -> dict[str, Any]:
        response = self.model.generate([self.system_message, *state["messages"]], self.schemas)
        steps = state["steps"] + 1
        if response.tool_call is None:
            return {"draft": response.text or "", "steps": steps}
        message = Message(role="assistant", content="", tool_call=response.tool_call)
        return {"messages": [message], "steps": steps}

    def _run_tool(self, state: SubAgentState) -> dict[str, Any]:
        call = state["messages"][-1].tool_call
        return {"messages": [Message(role="tool", content=self._execute(call), tool_call_id=call.id)]}

    @staticmethod
    def _route_after_llm(state: SubAgentState) -> str:
        return "end" if state["draft"] is not None else "tools"

    def _route_after_tools(self, state: SubAgentState) -> str:
        return "end" if state["steps"] >= self.max_steps else "llm"

    def _execute(self, call: ToolCall) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Error: la herramienta '{call.name}' no está disponible."
        try:
            return tool.run(call.arguments)
        except TypeError as error:
            return f"Error en los argumentos de '{call.name}': {error}"
        except Exception:
            return API_ERROR_TEXT


def build_weather_agent(model: Model, weather_tool: Tool) -> SubAgent:
    return SubAgent(
        name="weather",
        description="Obtiene el tiempo actual de una ubicación de México. Contexto: city.",
        model=model,
        system_prompt=WEATHER_PROMPT,
        tools=[weather_tool],
    )


def build_planner_agent(model: Model) -> SubAgent:
    return SubAgent(
        name="planner",
        description=(
            "Planifica viajes por México (itinerarios, destinos, actividades, gastronomía, presupuesto). "
            "Contexto: destino, fechas/duración, presupuesto, preferencias relevantes."
        ),
        model=model,
        system_prompt=PLANNER_PROMPT,
    )
