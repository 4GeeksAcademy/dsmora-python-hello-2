import json
import logging
import operator
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .model import Message, Model, ModelResponse, ToolCall
from .tools import API_ERROR_TEXT, Tool

MAX_PLANNER_EVALUATIONS = 15
PLANNER_CRITERIA = {
    "daily_plan": "Planificación diaria",
    "transport": "Desplazamientos",
    "activities": "Plan de actividades",
    "budget": "Presupuesto",
    "length": "Longitud",
}
PLANNER_TIMEOUT_RESULT = (
    "No se pudo completar la revisión del plan dentro del tiempo de espera. "
    "La propuesta no está validada; inténtalo de nuevo."
)

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
    "conocimiento general y adapta el plan al contexto recibido. Organiza la propuesta por día y en orden "
    "cronológico, incluye horarios y traslados necesarios, actividades concretas y presupuesto desglosado "
    "con moneda e indicación de estimados/persona. No afirmes haber "
    "verificado horarios, cierres, obras ni disponibilidad si no hay evidencia proporcionada; indica la "
    "incertidumbre. No des datos del tiempo actual.\n"
    + COMMON_RULES
)

PLANNER_EVALUATOR_PROMPT = (
    "Evalúa el plan de viaje frente a los criterios indicados. Devuelve únicamente JSON con las claves "
    '"passed" (lista de IDs aprobados) y "failed" (lista de objetos {"criterion": ID, "reason": motivo}). '
    "IDs: daily_plan, transport, activities, budget, length. Evalúa solo lo que demuestra el "
    "plan y el contexto, sin suponer ni inventar datos. La longitud máxima es 1.500 caracteres, contando "
    "espacios y saltos de línea."
)

PLANNER_OPTIMIZER_PROMPT = (
    "Revisa el borrador del plan de viaje para corregir todos los criterios fallidos indicados. Conserva "
    "la información útil, no inventes datos de disponibilidad y no afirmes verificaciones sin evidencia. "
    "Devuelve únicamente el plan revisado en español, con un máximo de 1.400 caracteres."
)


def _is_planner_refusal(text: str) -> bool:
    normalized = text.strip().casefold()
    if len(normalized) > 400:
        return False
    return normalized.startswith(
        (
            "lo siento, no puedo",
            "no puedo ayudarte",
            "no puedo darte esa respuesta",
        )
    )


@dataclass
class SubAgentTask:
    """Mensaje de entrada común a todos los subagentes: solo lo imprescindible para su tarea."""

    agent: str
    instruction: str
    context: dict[str, str] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)

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
    task_id: str = ""
    proposal: dict[str, str] | None = None


class SubAgentState(TypedDict):
    messages: Annotated[list[Message], operator.add]
    steps: int
    draft: str | None
    evaluation_count: int
    evaluation: dict[str, Any] | None
    on_event: Callable[[str], None] | None
    proposal: dict[str, str] | None


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

    def run(
        self, task: SubAgentTask, on_event: Callable[[str], None] | None = None
    ) -> SubAgentResult:
        try:
            state = self.graph.invoke(
                {
                    "messages": [task.to_message()],
                    "steps": 0,
                    "draft": None,
                    "evaluation_count": 0,
                    "evaluation": None,
                    "on_event": on_event,
                    "proposal": None,
                },
                {
                    "recursion_limit": (
                        2 * MAX_PLANNER_EVALUATIONS + 4
                        if self.name == "planner"
                        else 2 * self.max_steps + 4
                    )
                },
            )
        except Exception as error:
            logging.getLogger(__name__).error("Subagente %s fallo: %s: %.300s", self.name, type(error).__name__, error)
            if self.name == "planner" and on_event is not None:
                if self._is_timeout_error(error):
                    on_event(
                        "[planner] Flujo interrumpido por timeout; la propuesta no se considera validada."
                    )
                else:
                    on_event(
                        f"[planner] Flujo interrumpido ({type(error).__name__}); "
                        "se devuelve el error estándar."
                    )
            if self.name == "planner" and self._is_timeout_error(error):
                return SubAgentResult(
                    agent=self.name, content=PLANNER_TIMEOUT_RESULT, ok=False, task_id=task.task_id
                )
            return SubAgentResult(agent=self.name, content=API_ERROR_TEXT, ok=False, task_id=task.task_id)
        if state["draft"] is None:
            return SubAgentResult(
                agent=self.name,
                content="No se obtuvo una respuesta a tiempo.",
                ok=False,
                task_id=task.task_id,
            )
        return SubAgentResult(
            agent=self.name,
            content=state["draft"],
            task_id=task.task_id,
            proposal=state["proposal"],
        )

    def _build_graph(self):
        builder = StateGraph(SubAgentState)
        builder.add_node("llm", self._call_model)
        builder.add_node("tools", self._run_tool)
        if self.name == "planner":
            builder.add_node("evaluate", self._evaluate_plan)
            builder.add_node("optimize", self._optimize_plan)
        builder.add_edge(START, "llm")
        destinations = {"tools": "tools", "end": END}
        if self.name == "planner":
            destinations["evaluate"] = "evaluate"
        builder.add_conditional_edges("llm", self._route_after_llm, destinations)
        builder.add_conditional_edges("tools", self._route_after_tools, {"llm": "llm", "end": END})
        if self.name == "planner":
            builder.add_conditional_edges(
                "evaluate",
                self._route_after_evaluation,
                {"optimize": "optimize", "end": END},
            )
            builder.add_conditional_edges(
                "optimize",
                self._route_after_optimization,
                {"evaluate": "evaluate", "end": END},
            )
        return builder.compile(checkpointer=False)

    def _call_model(self, state: SubAgentState) -> dict[str, Any]:
        response = self._generate_with_trace(
            [self.system_message, *state["messages"]],
            self.schemas,
            state,
            "generación inicial",
        )
        steps = state["steps"] + 1
        if response.tool_call is None:
            return {"draft": response.text or "", "steps": steps}
        message = Message(role="assistant", content="", tool_call=response.tool_call)
        return {"messages": [message], "steps": steps}

    def _run_tool(self, state: SubAgentState) -> dict[str, Any]:
        call = state["messages"][-1].tool_call
        result = self._execute(call)
        updates: dict[str, Any] = {
            "messages": [Message(role="tool", content=result, tool_call_id=call.id)]
        }
        if call.name == "save_trip_plan":
            try:
                proposal = json.loads(result)
            except (TypeError, ValueError):
                proposal = None
            if (
                isinstance(proposal, dict)
                and proposal.get("status") == "proposal"
                and isinstance(proposal.get("title"), str)
                and isinstance(proposal.get("content"), str)
            ):
                updates["proposal"] = {
                    "title": proposal["title"],
                    "content": proposal["content"],
                }
        return updates

    def _route_after_llm(self, state: SubAgentState) -> str:
        if state["draft"] is None:
            return "tools"
        if self.name == "planner" and _is_planner_refusal(state["draft"]):
            if state["on_event"] is not None:
                state["on_event"]("[planner] Respuesta de rechazo detectada; se omite evaluación y optimización.")
            return "end"
        return "evaluate" if self.name == "planner" else "end"

    def _evaluate_plan(self, state: SubAgentState) -> dict[str, Any]:
        count = state["evaluation_count"] + 1
        draft = state["draft"] or ""
        messages = [
            Message(role="system", content=PLANNER_EVALUATOR_PROMPT),
            Message(
                role="user",
                content=(
                    f"Contexto de la tarea:\n{state['messages'][0].content}\n\n"
                    f"Plan a evaluar:\n{draft}"
                ),
            ),
        ]
        response = self._generate_with_trace(messages, [], state, f"evaluación {count}")
        evaluation = self._parse_evaluation(response.text)

        if len(draft) > 1500:
            evaluation["failed"]["length"] = (
                f"El plan tiene {len(draft)} caracteres; el máximo es 1.500."
            )
            evaluation["passed"].discard("length")
        passed = evaluation["passed"]
        failed = evaluation["failed"]
        approved = not failed and len(passed) == len(PLANNER_CRITERIA)
        state["on_event"] and state["on_event"](
            f"[planner] Iteración {count}/{MAX_PLANNER_EVALUATIONS}: "
            + ("aprobada; todos los criterios cumplen." if approved else
               "requiere optimización; " + "; ".join(
                   f"{PLANNER_CRITERIA[key]}: {reason}" for key, reason in failed.items()
               ))
        )
        if approved:
            state["on_event"] and state["on_event"](
                f"[planner] Proceso finalizado por aprobación en la iteración {count}."
            )
        elif count == MAX_PLANNER_EVALUATIONS:
            state["on_event"] and state["on_event"](
                f"[planner] Proceso finalizado al alcanzar el máximo de "
                f"{MAX_PLANNER_EVALUATIONS} iteraciones."
            )
            report = "; ".join(
                f"{PLANNER_CRITERIA[key]}: {reason}" for key, reason in failed.items()
            )
            draft = (
                "No se pudo validar el plan tras 15 iteraciones. Requisitos pendientes o no verificables: "
                f"{report}"
            )
        else:
            state["on_event"] and state["on_event"](
                f"[planner] Iteración {count}/{MAX_PLANNER_EVALUATIONS}: revisando la propuesta."
            )
        return {
            "draft": draft,
            "evaluation_count": count,
            "evaluation": {**evaluation, "approved": approved},
        }

    @staticmethod
    def _parse_evaluation(text: str | None) -> dict[str, Any]:
        try:
            result = json.loads(text or "")
        except (TypeError, ValueError):
            result = {}
        if not isinstance(result, dict):
            result = {}

        passed = result.get("passed")
        passed_ids = (
            {item for item in passed if isinstance(item, str) and item in PLANNER_CRITERIA}
            if isinstance(passed, list)
            else set()
        )
        failed: dict[str, str] = {}
        failures = result.get("failed")
        if isinstance(failures, list):
            for item in failures:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("criterion"), str)
                    and item["criterion"] in PLANNER_CRITERIA
                ):
                    key = item["criterion"]
                    failed[key] = str(item.get("reason") or "No cumple el criterio.")

        for key in PLANNER_CRITERIA:
            if key not in passed_ids and key not in failed:
                failed[key] = "El evaluador no confirmó que se cumpla este criterio."
        return {"passed": passed_ids - failed.keys(), "failed": failed}

    def _optimize_plan(self, state: SubAgentState) -> dict[str, Any]:
        evaluation = state["evaluation"] or {}
        failures = evaluation.get("failed", {})
        count = state["evaluation_count"]
        messages = [
            Message(role="system", content=PLANNER_OPTIMIZER_PROMPT),
            Message(
                role="user",
                content=(
                    f"Borrador:\n{state['draft'] or ''}\n\n"
                    f"Criterios fallidos:\n{json.dumps(failures, ensure_ascii=False)}"
                ),
            ),
        ]
        response = self._generate_with_trace(
            messages,
            [],
            state,
            f"optimización {count}",
        )
        return {"draft": response.text or ""}

    def _generate_with_trace(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        state: SubAgentState,
        phase: str,
    ) -> ModelResponse:
        emit = state.get("on_event") if self.name == "planner" else None
        if emit is not None:
            emit(f"[planner] Modelo: inicio de {phase}.")
        started_at = time.perf_counter()
        try:
            response = self.model.generate(messages, tools)
        except Exception as error:
            elapsed = time.perf_counter() - started_at
            is_timeout = self._is_timeout_error(error)
            if emit is not None:
                detail = "timeout probable" if is_timeout else f"error {type(error).__name__}"
                emit(f"[planner] Modelo: {phase} falló tras {elapsed:.1f}s ({detail}).")
            raise

        if emit is not None:
            output_length = len(response.text or "")
            emit(
                f"[planner] Modelo: {phase} completado en "
                f"{time.perf_counter() - started_at:.1f}s; respuesta de {output_length} caracteres."
            )
        return response

    @staticmethod
    def _route_after_evaluation(state: SubAgentState) -> str:
        evaluation = state["evaluation"] or {}
        if evaluation.get("approved") or state["evaluation_count"] >= MAX_PLANNER_EVALUATIONS:
            return "end"
        return "optimize"

    def _route_after_optimization(self, state: SubAgentState) -> str:
        if _is_planner_refusal(state["draft"] or ""):
            if state["on_event"] is not None:
                state["on_event"](
                    "[planner] El optimizador devolvió una respuesta de rechazo; "
                    "se omite la evaluación restante."
                )
            return "end"
        return "evaluate"

    @staticmethod
    def _is_timeout_error(error: Exception) -> bool:
        current: BaseException | None = error
        while current is not None:
            if isinstance(current, TimeoutError) or any(
                term in str(current).casefold()
                for term in ("timed out", "timeout", "tiempo de espera")
            ):
                return True
            current = current.__cause__ or current.__context__
        return False

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
