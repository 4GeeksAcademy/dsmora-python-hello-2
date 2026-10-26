import json
import logging
import operator
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from .approval import candidate_digest
from .guardrails import GUARD_ERROR, PARTIAL_SCOPE_NOTICE, SAFE_FALLBACK, Guardrails, parse_json
from .memory import UserMemory
from .model import Message, Model
from .subagents import SubAgent, SubAgentResult, SubAgentTask

MAX_ROUTES = 4
PLAN_CONSISTENCY_PROMPT = (
    "Valida un candidato a plan de viaje. Devuelve exclusivamente JSON con "
    '{"valid": boolean, "violations": [string]}. Valida que sea una propuesta concreta para Mexico, '
    "no una negativa, error ni evaluacion fallida; que no incluya compras, reservas, marcas comerciales "
    "ni informacion interna; y que, si se presenta como itinerario, incluya dias/cronologia, actividades, "
    "traslados y presupuesto con moneda e indicacion de estimaciones. No afirmes que horarios, "
    "disponibilidad o clima actual estan verificados sin evidencia explicita. Ante duda, valida=false."
)

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
    candidate: dict[str, Any] | None
    direct_candidate: dict[str, Any] | None
    direct_tool: bool
    execution: dict[str, str] | None
    envelope: dict[str, Any] | None
    approval: dict[str, Any] | None
    save_result: Any
    error: dict[str, Any] | None
    guard_report: dict[str, Any] | None


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
        checkpointer: Any = None,
        register_prepared: Callable[[dict[str, Any]], None] | None = None,
        save_candidate: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.model = model
        self.memory = memory
        self.guardrails = Guardrails(model)
        self.subagents = {agent.name: agent for agent in subagents}
        self.history_window = history_window
        self.on_event = on_event
        self.capability_notice = capability_notice
        self.checkpointer = checkpointer
        self.register_prepared = register_prepared
        self.save_candidate = save_candidate
        self.history: list[Message] = []
        self.graph = self._build_graph()

    def run(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        owner_id: str = "",
        conversation_id: str = "",
        initial_candidate: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        if initial_candidate is not None and self.checkpointer is None:
            raise RuntimeError("El guardado requiere un checkpoint durable.")
        state = self.graph.invoke(
            {
                "messages": [*self.history, Message(role="user", content=user_input)],
                "sanitized_input": None,
                "tasks": [],
                "results": [],
                "draft": None,
                "candidate": None,
                "direct_candidate": initial_candidate,
                "direct_tool": initial_candidate is not None,
                "execution": (
                    {
                        "thread_id": thread_id,
                        "owner_id": owner_id,
                        "conversation_id": conversation_id,
                        "job_id": thread_id,
                    }
                    if thread_id
                    else None
                ),
                "envelope": None,
                "approval": None,
                "save_result": None,
                "error": None,
                "guard_report": None,
            },
            {"configurable": {"thread_id": thread_id}} if thread_id else None,
        )
        if (state.get("approval") or {}).get("status") == "pending":
            return {
                "status": "awaiting_approval",
                "pending": state["approval"],
            }
        if state.get("error"):
            return {"status": "failed", "error": state["error"]}
        return self._finish_run(state)

    def resume(self, thread_id: str, decision: dict[str, Any]) -> str | dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.graph.get_state(config)
        if not snapshot.next:
            return self._finish_run(snapshot.values)
        interrupted = any(task.interrupts for task in snapshot.tasks)
        state = self.graph.invoke(Command(resume=decision) if interrupted else None, config)
        if state.get("error"):
            return {"status": "failed", "error": state["error"]}
        return self._finish_run(state)

    def _finish_run(self, state: OrchestratorState) -> str | dict[str, Any]:
        reply = state["messages"][-1]
        latest_user = next(
            message for message in reversed(state["messages"]) if message.role == "user"
        )
        user_message = Message(
            role="user", content=state["sanitized_input"] or latest_user.content
        )
        self.history = [*self.history, user_message, reply]
        if state["save_result"] is not None:
            if state["direct_tool"]:
                return {"status": "done", "result": state["save_result"]}
            return "Plan guardado. Puedes verlo en tus planes."
        return reply.content

    def _build_graph(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("input_guard", self._input_guard)
        builder.add_node("router", self._route)
        for name, agent in self.subagents.items():
            builder.add_node(name, self._make_worker(agent))
            builder.add_edge(name, "subagent_output_guard")
        builder.add_node("subagent_output_guard", self._subagent_output_guard)
        builder.add_node("aggregate", self._aggregate)
        builder.add_node("output_guard", self._output_guard)
        builder.add_node("plan_consistency_guard", self._plan_consistency_guard)
        builder.add_node("prepare_save", self._prepare_save)
        builder.add_node("approval_gate", self._approval_gate)
        builder.add_node("save_plan", self._save_plan)
        builder.add_node("controlled_error", self._controlled_error)

        builder.add_edge(START, "input_guard")
        builder.add_conditional_edges(
            "input_guard",
            self._after_input_guard,
            {"router": "router", "guard": "plan_consistency_guard", "end": END},
        )
        builder.add_conditional_edges("router", self._dispatch, [*self.subagents, "output_guard"])
        builder.add_edge("aggregate", "output_guard")
        builder.add_conditional_edges(
            "subagent_output_guard",
            self._after_subagent_output_guard,
            {"aggregate": "aggregate", "error": "controlled_error"},
        )
        builder.add_edge("output_guard", "plan_consistency_guard")
        builder.add_conditional_edges(
            "plan_consistency_guard",
            self._after_plan_consistency_guard,
            {"prepare_save": "prepare_save", "end": END, "error": "controlled_error"},
        )
        builder.add_edge("prepare_save", "approval_gate")
        builder.add_conditional_edges(
            "approval_gate",
            self._after_approval_gate,
            {"save": "save_plan", "error": "controlled_error"},
        )
        builder.add_edge("save_plan", END)
        builder.add_edge("controlled_error", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _input_guard(self, state: OrchestratorState) -> dict[str, Any]:
        if state["direct_candidate"] is not None:
            return {
                "candidate": state["direct_candidate"],
                "direct_candidate": None,
            }
        check = self.guardrails.check_input(state["messages"])
        if check.error is not None:
            return {"messages": [Message(role="assistant", content=check.error)]}
        return {"sanitized_input": check.sanitized_request}

    @staticmethod
    def _after_input_guard(state: OrchestratorState) -> str:
        if state["direct_tool"]:
            return "guard"
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

    def _subagent_output_guard(self, state: OrchestratorState) -> dict[str, Any]:
        expected = {task.task_id: task.agent for task in state["tasks"]}
        observed: dict[str, SubAgentResult] = {}
        violations: list[str] = []
        failed_result = False
        for result in state["results"]:
            if not isinstance(result, SubAgentResult) or type(result.ok) is not bool:
                violations.append("Resultado de subagente con contrato invalido.")
                continue
            if (
                not isinstance(result.task_id, str)
                or result.task_id not in expected
                or result.task_id in observed
            ):
                violations.append("Resultado de tarea ausente, inesperado o duplicado.")
                continue
            if expected[result.task_id] != result.agent:
                violations.append("El resultado no corresponde al subagente delegado.")
                continue
            if not isinstance(result.content, str) or not result.content.strip():
                violations.append("El resultado del subagente esta vacio.")
                continue
            output_limit = 310000 if result.agent == "saved_plans" else 1500
            if len(result.content) > output_limit:
                violations.append("El resultado del subagente excede el limite de longitud.")
            if not result.ok:
                failed_result = True
            if result.proposal is not None:
                if (
                    not isinstance(result.proposal, dict)
                    or set(result.proposal) != {"title", "content"}
                ):
                    violations.append("La propuesta de guardado tiene un contrato invalido.")
                    observed[result.task_id] = result
                    continue
                title, content = result.proposal.get("title"), result.proposal.get("content")
                if not (
                    isinstance(title, str)
                    and 1 <= len(title.strip()) <= 120
                    and isinstance(content, str)
                    and 1 <= len(content.strip()) <= 6000
                ):
                    violations.append("La propuesta de guardado no cumple sus limites.")
            observed[result.task_id] = result
        if set(observed) != set(expected):
            violations.append("Faltan resultados de tareas delegadas.")
        proposal_count = sum(result.proposal is not None for result in observed.values())
        if failed_result and proposal_count:
            violations.append("Un subagente informo un fallo durante una solicitud de guardado.")
        if proposal_count > 1:
            violations.append("La solicitud produjo mas de una propuesta de guardado.")
        if violations:
            return {
                "guard_report": {"status": "failed", "violations": violations},
                "error": {
                    "code": "SUBAGENT_OUTPUT_INVALID",
                    "message": "No se pudo validar la salida del agente; no se guardo ningun plan.",
                    "node": "subagent_output_guard",
                    "retryable": False,
                },
            }
        return {"guard_report": {"status": "passed", "violations": []}}

    @staticmethod
    def _after_subagent_output_guard(state: OrchestratorState) -> str:
        return "error" if state["error"] else "aggregate"

    def _aggregate(self, state: OrchestratorState) -> dict[str, Any]:
        results = state["results"]
        proposals = [result.proposal for result in results if result.proposal is not None]
        candidate = proposals[0] if proposals else None
        if len(results) == 1:
            return {"draft": results[0].content, "candidate": candidate}
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
        return {
            "draft": text or "\n\n".join(result.content for result in results),
            "candidate": candidate,
        }

    def _output_guard(self, state: OrchestratorState) -> dict[str, Any]:
        safe_text = self.guardrails.check_output(state["draft"] or "")
        if state["sanitized_input"]:
            safe_text = f"{safe_text}\n\n{PARTIAL_SCOPE_NOTICE}"
        return {"messages": [Message(role="assistant", content=safe_text)]}

    def _plan_consistency_guard(self, state: OrchestratorState) -> dict[str, Any]:
        candidate = state["candidate"]
        if candidate is None:
            return {"guard_report": {"status": "not_applicable", "violations": []}}
        title = candidate.get("title")
        content = candidate.get("content")
        if not isinstance(title, str) or not isinstance(content, str):
            return self._validation_failure("Candidato de guardado malformado.")
        title, content = title.strip(), content.strip()
        if not 1 <= len(title) <= 120 or not 1 <= len(content) <= 6000:
            return self._validation_failure("El titulo o contenido excede los limites permitidos.")
        safe_content = self.guardrails.check_output(content)
        if safe_content == SAFE_FALLBACK or not safe_content.strip():
            return self._validation_failure("El candidato no supero la validacion de salida.")
        safe_content = safe_content.strip()
        try:
            response = self.model.generate(
                [
                    Message(role="system", content=PLAN_CONSISTENCY_PROMPT),
                    Message(
                        role="user",
                        content=f"Titulo: {title}\n\nCandidato final:\n{safe_content}",
                    ),
                ],
                [],
            )
            review = json.loads(response.text or "")
        except Exception:
            logging.getLogger(__name__).exception("Fallo la evaluacion del candidato de guardado.")
            return self._validation_failure("No se pudo evaluar el candidato; no se guardo.")
        if (
            not isinstance(review, dict)
            or review.get("valid") is not True
            or not isinstance(review.get("violations"), list)
            or review["violations"]
        ):
            return self._validation_failure("El candidato no cumple las reglas del plan.")
        return {
            "candidate": {**candidate, "title": title, "content": safe_content},
            "guard_report": {"status": "passed", "violations": []},
        }

    @staticmethod
    def _validation_failure(message: str) -> dict[str, Any]:
        return {
            "guard_report": {"status": "failed", "violations": [message]},
            "error": {
                "code": "PLAN_VALIDATION_FAILED",
                "message": message,
                "node": "plan_consistency_guard",
                "retryable": False,
            },
        }

    @staticmethod
    def _after_plan_consistency_guard(state: OrchestratorState) -> str:
        if state["error"]:
            return "error"
        if state["candidate"] is None:
            return "end"
        return "prepare_save"

    def _prepare_save(self, state: OrchestratorState) -> dict[str, Any]:
        execution = state["execution"]
        if (
            self.checkpointer is None
            or execution is None
            or self.register_prepared is None
        ):
            raise RuntimeError("No se puede publicar una aprobacion sin persistencia durable.")
        candidate = state["candidate"]
        request_id, operation_id = uuid.uuid4().hex, uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        candidate = {
            "operation": "save_trip_plan",
            "operation_id": operation_id,
            "version": 1,
            "title": candidate["title"],
            "content": candidate["content"],
        }
        candidate["digest"] = candidate_digest(
            execution["owner_id"], candidate["version"], candidate["title"], candidate["content"]
        )
        envelope = {
            "schema_version": 1,
            "execution": {
                **execution,
                "phase": "awaiting_approval",
                "created_at": created_at,
                "updated_at": created_at,
            },
            "candidate": candidate,
            "integrity": {
                "algorithm": "sha256",
                "canonicalization": "save-plan-v1",
            },
            "validation": {
                "subagent_outputs": {
                    "status": "passed",
                    "policy_version": 1,
                    "checked_task_ids": [task.task_id for task in state["tasks"]],
                    "violations": [],
                } if state["tasks"] else {
                    "status": "not_applicable",
                    "policy_version": 1,
                    "checked_task_ids": [],
                    "violations": [],
                },
                "plan_consistency": {
                    **state["guard_report"],
                    "policy_version": 1,
                },
            },
            "approval": {
                "request_id": request_id,
                "status": "pending",
                "candidate_version": candidate["version"],
                "candidate_digest": candidate["digest"],
                "requested_at": created_at,
                "expires_at": None,
            },
            "effect": {
                "status": "not_started",
                "operation_id": operation_id,
                "plan_id": None,
                "receipt_id": None,
            },
            "error": None,
        }
        self.register_prepared(envelope)
        return {
            "candidate": None,
            "envelope": envelope,
            "approval": {
                **envelope["approval"],
                "operation_id": operation_id,
            },
        }

    def _approval_gate(self, state: OrchestratorState) -> dict[str, Any]:
        approval = state["approval"]
        candidate = state["envelope"]["candidate"]
        decision = interrupt(
            {
                "request_id": approval["request_id"],
                "operation_id": approval["operation_id"],
                "version": approval["candidate_version"],
                "digest": approval["candidate_digest"],
                "title": candidate["title"],
                "content": candidate["content"],
            }
        )
        if (
            not isinstance(decision, dict)
            or decision.get("request_id") != approval["request_id"]
            or decision.get("version") != approval["candidate_version"]
            or decision.get("digest") != approval["candidate_digest"]
            or decision.get("action") not in {"approve", "deny"}
        ):
            return {
                "error": {
                    "code": "APPROVAL_INVALID",
                    "message": "La decision de aprobacion no coincide con la solicitud pendiente.",
                    "node": "approval_gate",
                    "retryable": False,
                },
            }
        envelope = {
            **state["envelope"],
            "execution": {
                **state["envelope"]["execution"],
                "phase": "approved" if decision["action"] == "approve" else "rejected",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "approval": {
                **state["envelope"]["approval"],
                "status": "approved" if decision["action"] == "approve" else "rejected",
                "decision": decision,
            },
        }
        return {
            "approval": {**approval, "status": decision["action"], "decision": decision},
            "envelope": envelope,
        }

    @staticmethod
    def _after_approval_gate(state: OrchestratorState) -> str:
        if state["error"]:
            return "error"
        return "save" if state["approval"]["status"] == "approve" else "error"

    def _save_plan(self, state: OrchestratorState) -> dict[str, Any]:
        if self.save_candidate is None:
            raise RuntimeError("No hay un guardado MCP autorizado para esta ejecucion.")
        candidate = state["envelope"]["candidate"]
        result = self.save_candidate(candidate, state["approval"]["decision"])
        plan_id = result.get("plan", {}).get("id") if isinstance(result, dict) else None
        envelope = {
            **state["envelope"],
            "execution": {
                **state["envelope"]["execution"],
                "phase": "completed",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "effect": {
                "status": "completed",
                "operation_id": candidate["operation_id"],
                "plan_id": plan_id,
                "receipt_id": candidate["operation_id"],
            },
        }
        return {
            "save_result": result,
            "envelope": envelope,
            "messages": [Message(role="assistant", content="Plan guardado. Puedes verlo en tus planes.")],
        }

    @staticmethod
    def _controlled_error(state: OrchestratorState) -> dict[str, Any]:
        error = state["error"]
        if error is None:
            error = {
                "code": "APPROVAL_DENIED",
                "message": "Aprobacion rechazada. El plan no se guardo.",
                "node": "approval_gate",
                "retryable": False,
            }
        return {
            "error": error,
            "envelope": (
                {**state["envelope"], "error": error}
                if state["envelope"] is not None
                else None
            ),
            "messages": [Message(role="assistant", content=error["message"])],
        }
