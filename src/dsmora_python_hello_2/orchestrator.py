import json
import logging
import operator
import time
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .guardrails import GUARD_ERROR, PARTIAL_SCOPE_NOTICE, Guardrails, parse_json
from .memory import UserMemory
from .model import Message, Model
from .subagents import SubAgent, SubAgentResult, SubAgentTask

MAX_ROUTES = 4

ROUTER_PROMPT = (
    "Eres el agente principal de 'MEXICO LINDO' (viajes por México). No resuelves tareas tú mismo: "
    "decides qué subagentes deben ejecutarlas. Subagentes disponibles:\n{agents}\n\n"
    "Analiza el ÚLTIMO mensaje del usuario (usa la conversación previa solo para resolver referencias) y "
    "responde ÚNICAMENTE con un JSON con este formato exacto:\n"
    '{{"routes": [{{"agent": str, "instruction": str, "context": {{str: str}}}}], "reply": str, '
    '"remember": {{str: str}}, "forget": [str]}}\n'
    "- routes: una entrada por cada tarea a delegar. Si el mensaje pide el tiempo Y un plan de viaje, "
    "incluye ambas rutas (se ejecutarán en paralelo). Lista vacía si no hay que delegar nada.\n"
    "- instruction: la tarea autocontenida para ese subagente, solo con lo que le corresponde.\n"
    "- context: SOLO los datos mínimos imprescindibles para esa tarea (p. ej. city para el tiempo; "
    "destino, duración, presupuesto o preferencias relevantes para el plan). No copies la conversación.\n"
    "- reply: respuesta breve directa al usuario solo cuando routes está vacía (saludos, pedir datos "
    "que faltan como la ciudad). Cadena vacía en otro caso.\n"
    "- remember: datos personales o preferencias nuevas que el usuario comparta (nombre, idioma, gustos...).\n"
    "- forget: claves de datos guardados que el usuario pida olvidar.\n\n"
    "{memory}"
)

AGGREGATE_PROMPT = (
    "Eres el agente principal de 'MEXICO LINDO'. Integra en una única respuesta clara y coherente para el "
    "usuario los resultados de tus subagentes, sin perder información relevante ni inventar datos. "
    "Responde en español salvo que el usuario prefiera otro idioma. No menciones a los subagentes."
)


class OrchestratorState(TypedDict):
    messages: Annotated[list[Message], operator.add]
    sanitized_input: str | None
    tasks: list[SubAgentTask]
    results: Annotated[list[SubAgentResult], operator.add]
    draft: str | None


class WorkerInput(TypedDict):
    task: SubAgentTask


class Orchestrator:
    """Agente principal: aplica guardrails, enruta a subagentes (en paralelo si procede) e integra."""

    def __init__(
        self,
        model: Model,
        subagents: list[SubAgent],
        memory: UserMemory | None = None,
        history_window: int = 6,
        on_event: Callable[[str], None] | None = None,
        capability_notice: str = "",
    ) -> None:
        self.model = model
        self.memory = memory
        self.guardrails = Guardrails(model)
        self.subagents = {agent.name: agent for agent in subagents}
        self.history_window = history_window
        self.on_event = on_event
        self.capability_notice = capability_notice
        self.history: list[Message] = []
        self.graph = self._build_graph()

    def run(self, user_input: str) -> str:
        state = self.graph.invoke(
            {
                "messages": [*self.history, Message(role="user", content=user_input)],
                "sanitized_input": None,
                "tasks": [],
                "results": [],
                "draft": None,
            }
        )
        reply = state["messages"][-1]
        user_message = Message(role="user", content=state["sanitized_input"] or user_input)
        self.history = [*self.history, user_message, reply]
        return reply.content

    def _build_graph(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("input_guard", self._input_guard)
        builder.add_node("router", self._route)
        for name, agent in self.subagents.items():
            builder.add_node(name, self._make_worker(agent))
            builder.add_edge(name, "aggregate")
        builder.add_node("aggregate", self._aggregate)
        builder.add_node("output_guard", self._output_guard)

        builder.add_edge(START, "input_guard")
        builder.add_conditional_edges("input_guard", self._after_input_guard, {"router": "router", "end": END})
        builder.add_conditional_edges("router", self._dispatch, [*self.subagents, "output_guard"])
        builder.add_edge("aggregate", "output_guard")
        builder.add_edge("output_guard", END)
        return builder.compile()

    def _input_guard(self, state: OrchestratorState) -> dict[str, Any]:
        check = self.guardrails.check_input(state["messages"])
        if check.error is not None:
            return {"messages": [Message(role="assistant", content=check.error)]}
        return {"sanitized_input": check.sanitized_request}

    @staticmethod
    def _after_input_guard(state: OrchestratorState) -> str:
        return "end" if state["messages"][-1].role == "assistant" else "router"

    def _route(self, state: OrchestratorState) -> dict[str, Any]:
        decision = parse_json(self.model.generate(self._router_messages(state), []).text)
        if decision is None:
            return {"draft": GUARD_ERROR}
        self._update_memory(decision)
        tasks = self._parse_tasks(decision.get("routes"))
        if tasks:
            return {"tasks": tasks}
        reply = decision.get("reply")
        return {"draft": reply.strip() if isinstance(reply, str) and reply.strip() else GUARD_ERROR}

    def _router_messages(self, state: OrchestratorState) -> list[Message]:
        agents = "\n".join(f"- {name}: {agent.description}" for name, agent in self.subagents.items())
        memory = self.memory.as_prompt() if self.memory is not None else ""
        system = Message(
            role="system",
            content=ROUTER_PROMPT.format(agents=agents, memory=memory) + "\n" + self.capability_notice,
        )
        messages = state["messages"][-self.history_window :]
        if state["sanitized_input"]:
            messages = [*messages[:-1], Message(role="user", content=state["sanitized_input"])]
        return [system, *messages]

    def _parse_tasks(self, routes: Any) -> list[SubAgentTask]:
        if not isinstance(routes, list):
            return []
        tasks = []
        for route in routes[:MAX_ROUTES]:
            if not isinstance(route, dict) or route.get("agent") not in self.subagents:
                continue
            instruction = str(route.get("instruction") or "").strip()
            if not instruction:
                continue
            raw_context = route.get("context") if isinstance(route.get("context"), dict) else {}
            context = {str(key): str(value) for key, value in raw_context.items() if value}
            tasks.append(SubAgentTask(agent=route["agent"], instruction=instruction, context=context))
        return tasks

    def _update_memory(self, decision: dict[str, Any]) -> None:
        if self.memory is None:
            return
        remember = decision.get("remember")
        forget = decision.get("forget")
        try:
            if isinstance(remember, dict):
                for key, value in remember.items():
                    self.memory.remember(str(key), str(value))
            if isinstance(forget, list):
                for key in forget:
                    self.memory.forget(str(key))
        except Exception:
            logging.getLogger(__name__).exception("No se pudo actualizar la memoria del usuario.")
            raise

    def _emit(self, text: str) -> None:
        if self.on_event is not None:
            self.on_event(text)

    def _dispatch(self, state: OrchestratorState) -> list[Send] | str:
        """Fan-out: cada tarea se envía a su subagente; las del mismo paso se ejecutan en paralelo."""
        tasks = state["tasks"]
        if not tasks:
            self._emit("[router] Sin subagentes: responde el agente principal.")
            return "output_guard"
        names = ", ".join(task.agent for task in tasks)
        mode = f"en PARALELO ({len(tasks)} subagentes)" if len(tasks) > 1 else "ÚNICA (1 subagente)"
        self._emit(f"[router] Subagentes seleccionados: {names} → ejecución {mode}")
        return [Send(task.agent, {"task": task}) for task in tasks]

    def _make_worker(self, agent: SubAgent):
        def worker(payload: WorkerInput) -> dict[str, Any]:
            self._emit(f"[{agent.name}] ▶ inicio")
            start = time.perf_counter()
            result = agent.run(payload["task"], on_event=self._emit)
            status = "ok" if result.ok else "error"
            self._emit(f"[{agent.name}] ■ fin ({status}, {time.perf_counter() - start:.1f}s)")
            return {"results": [result]}

        worker.__name__ = f"{agent.name}_worker"
        return worker

    def _aggregate(self, state: OrchestratorState) -> dict[str, Any]:
        results = state["results"]
        if len(results) == 1:
            return {"draft": results[0].content}
        summary = json.dumps(
            [{"agent": result.agent, "content": result.content} for result in results], ensure_ascii=False
        )
        request = state["sanitized_input"] or state["messages"][-1].content
        messages = [
            Message(role="system", content=AGGREGATE_PROMPT),
            Message(role="user", content=f"Petición del usuario: {request}\n\nResultados: {summary}"),
        ]
        try:
            text = self.model.generate(messages, []).text
        except RuntimeError:
            text = None
        return {"draft": text or "\n\n".join(result.content for result in results)}

    def _output_guard(self, state: OrchestratorState) -> dict[str, Any]:
        safe_text = self.guardrails.check_output(state["draft"] or "")
        if state["sanitized_input"]:
            safe_text = f"{safe_text}\n\n{PARTIAL_SCOPE_NOTICE}"
        return {"messages": [Message(role="assistant", content=safe_text)]}
