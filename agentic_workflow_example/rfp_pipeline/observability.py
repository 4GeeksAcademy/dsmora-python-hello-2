"""Observability contracts for the "Real-Time Systems: Agent Observability"
milestone (Part 1 of 2).

This is the *teacher skeleton*: the event vocabulary, the durable per-task
event log, and the SSE stream shape that students must consume/persist in
class. On the graded path the real agents emit these events; here the RFP
example emits them too, so the panel (built in class) has real data to show.

Entities (exactly what the brief requires, minimal defaulting):
  * Agent  — identifier, name, flows it can participate in, status, needs_intervention
  * Flow   — identifier, flow_type, status, triggered_by, participating agents
  * Task   — identifier, flow+agent, action_type, trigger, derived tasks,
             prev/next step (traceability chain)
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import ActionType, AgentEvent, EventName, new_id


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# Registry of observed agents
# ---------------------------------------------------------------------------

@dataclass
class ObservedAgent:
    agent_id: str
    name: str
    flow_types: list = field(default_factory=list)
    status: str = "idle"
    needs_intervention: bool = False
    available_actions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.agent_id, "name": self.name,
                "flows": self.flow_types, "status": self.status,
                "needs_intervention": self.needs_intervention,
                "available_actions": self.available_actions}


@dataclass
class FlowRecord:
    flow_id: str
    flow_type: str
    status: str = "running"
    triggered_by: str = ""
    agents: list = field(default_factory=list)   # agent_ids
    tasks: list = field(default_factory=list)    # task_ids
    started_at: str = ""

    def to_dict(self) -> dict:
        return {"id": self.flow_id, "flow_type": self.flow_type, "status": self.status,
                "triggered_by": self.triggered_by, "agents": self.agents,
                "tasks": self.tasks, "started_at": self.started_at}


@dataclass
class TaskRecord:
    task_id: str
    flow_id: str
    flow_type: str
    agent_id: str
    action_type: str
    status: str = "completed"
    trigger: str = ""              # a prior task_id or an external event
    derived: list = field(default_factory=list)   # task_ids
    prev_step: Optional[str] = None
    next_step: Optional[str] = None
    payload: dict = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {"id": self.task_id, "flow_id": self.flow_id, "flow_type": self.flow_type,
                "agent_id": self.agent_id, "action_type": self.action_type,
                "status": self.status, "trigger": self.trigger,
                "derived": self.derived, "prev_step": self.prev_step,
                "next_step": self.next_step, "payload": self.payload,
                "timestamp": self.timestamp}


# ---------------------------------------------------------------------------
# In-memory observability store + SSE broadcast
# ---------------------------------------------------------------------------

class ObservabilityHub:
    """Single hub where the RFP example publishes events and tasks.

    In class, students persist these to Postgres and expose them via an SSE
    endpoint under ``services/`` — this hub is the contract and a reference
    implementation.
    """

    def __init__(self, max_history: int = 10_000):
        self._agents: dict[str, ObservedAgent] = {}
        self._flows: dict[str, FlowRecord] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._log: list[AgentEvent] = []
        self._max_history = max_history
        self._lock = threading.RLock()
        self._subscribers: list = []   # list of (queue, agent_filter)

    # -- registration -------------------------------------------------------
    def register_agent(self, agent: ObservedAgent) -> None:
        with self._lock:
            self._agents[agent.agent_id] = agent

    # -- mutation helpers ----------------------------------------------------
    def start_flow(self, flow_id: str, flow_type: str, triggered_by: str = "",
                   agents: Optional[list] = None) -> FlowRecord:
        with self._lock:
            flow = FlowRecord(flow_id=flow_id, flow_type=flow_type,
                              triggered_by=triggered_by, agents=agents or [],
                              started_at=_now())
            self._flows[flow_id] = flow
            return flow

    def ensure_flow(self, flow_id: str, flow_type: str,
                    triggered_by: str = "") -> FlowRecord:
        """Idempotent ``start_flow`` — reuses an existing record if present."""
        with self._lock:
            flow = self._flows.get(flow_id)
            if flow is None:
                flow = FlowRecord(flow_id=flow_id, flow_type=flow_type,
                                  triggered_by=triggered_by, started_at=_now())
                self._flows[flow_id] = flow
            return flow

    def add_task(self, task: TaskRecord) -> TaskRecord:
        with self._lock:
            # keep /api/flows in sync even if callers never explicitly start_flow
            self.ensure_flow(task.flow_id, task.flow_type)
            flow = self._flows[task.flow_id]
            if task.agent_id not in flow.agents:
                flow.agents.append(task.agent_id)
            if task.task_id not in flow.tasks:
                flow.tasks.append(task.task_id)
            if not flow.triggered_by and task.payload.get("ticket_id"):
                flow.triggered_by = task.payload["ticket_id"]
            self._tasks[task.task_id] = task
            # join chain
            if task.prev_step:
                prev = self._tasks.get(task.prev_step)
                if prev:
                    prev.next_step = task.task_id
            event = AgentEvent(
                event_name=EventName.AGENT_STEP.value,
                agent_id=task.agent_id,
                flow_id=task.flow_id,
                flow_type=task.flow_type,
                task_id=task.task_id,
                status=task.status,
                action_type=task.action_type,
                payload=task.payload,
                timestamp=task.timestamp or _now(),
            )
            self._log.append(event)
            if len(self._log) > self._max_history:
                self._log = self._log[-self._max_history:]
            self._broadcast(event)
            return task

    def set_agent_status(self, agent_id: str, status: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return
            agent.status = status
            event = AgentEvent(
                event_name=EventName.AGENT_STATUS_CHANGED.value,
                agent_id=agent_id,
                status=status,
                timestamp=_now(),
            )
            self._log.append(event)
            self._broadcast(event)

    # -- reads ---------------------------------------------------------------
    def list_agents(self) -> list[ObservedAgent]:
        with self._lock:
            return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Optional[ObservedAgent]:
        with self._lock:
            return self._agents.get(agent_id)

    def agent_detail(self, agent_id: str, last_n_flows: int = 5,
                     last_n_tasks: int = 10) -> dict:
        with self._lock:
            flows = [f for f in self._flows.values() if agent_id in f.agents]
            flows = flows[-last_n_flows:]
            flow_payload = []
            for f in flows:
                flow_tasks = [t.to_dict() for t in self._tasks.values()
                              if t.flow_id == f.flow_id and t.agent_id == agent_id]
                flow_payload.append({**f.to_dict(), "tasks_by_agent": flow_tasks})
            tasks = [t.to_dict() for t in self._tasks.values()
                     if t.agent_id == agent_id][-last_n_tasks:]
            agent = self._agents.get(agent_id)
            return {
                "agent": agent.to_dict() if agent else None,
                "last_flows": flow_payload,
                "last_tasks": tasks,
            }

    def flow_detail(self, flow_id: str) -> Optional[dict]:
        with self._lock:
            flow = self._flows.get(flow_id)
            if not flow:
                return None
            tasks = [t.to_dict() for t in self._tasks.values() if t.flow_id == flow_id]
            return {"flow": flow.to_dict(), "tasks": tasks}

    def full_log(self, page: int = 1, per_page: int = 100,
                 agent_id: Optional[str] = None,
                 flow_type: Optional[str] = None) -> dict:
        with self._lock:
            items = list(self._log)
        if agent_id:
            items = [e for e in items if e.agent_id == agent_id]
        if flow_type:
            items = [e for e in items if e.flow_type == flow_type]
        total = len(items)
        start = (page - 1) * per_page
        page_items = items[start:start + per_page]
        return {"page": page, "per_page": per_page, "total": total,
                "items": [e.to_dict() for e in page_items]}

    def task_chain(self, task_id: str) -> Optional[dict]:
        """Traceability: trigger -> task -> derived tasks -> prev/next."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            result = task.to_dict()
            result["trigger_task"] = self._tasks.get(task.trigger).to_dict() \
                if task.trigger and task.trigger in self._tasks else None
            result["derived_tasks"] = [self._tasks.get(d).to_dict()
                                       for d in task.derived if d in self._tasks]
            result["prev_task"] = self._tasks.get(task.prev_step).to_dict() \
                if task.prev_step and task.prev_step in self._tasks else None
            result["next_task"] = self._tasks.get(task.next_step).to_dict() \
                if task.next_step and task.next_step in self._tasks else None
            return result

    # -- SSE ----------------------------------------------------------------
    def subscribe(self, queue, agent_filter: Optional[str] = None) -> None:
        with self._lock:
            self._subscribers.append((queue, agent_filter))

    def unsubscribe(self, queue) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s[0] is not queue]

    def _broadcast(self, event: AgentEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue, agent_filter in subscribers:
            if agent_filter and event.agent_id != agent_filter:
                continue
            try:
                queue.put_nowait(event.to_sse())
            except Exception:  # noqa: BLE001 - a slow subscriber must not break others
                pass

    def iter_events(self, agent_filter: Optional[str] = None, since: Optional[str] = None):
        """Yield events (for a CLI SSE demo). `since` = a task_id watermark."""
        import queue
        q: queue.Queue = queue.Queue()
        self.subscribe(q, agent_filter)
        try:
            history = list(self._log)
            start = None
            if since:
                for i, e in enumerate(history):
                    if e.task_id == since:
                        start = i + 1
                        break
            for e in (history if start is None else history[start:]):
                if agent_filter and e.agent_id != agent_filter:
                    continue
                yield e.to_sse()
            while True:
                try:
                    yield q.get(timeout=0.5)
                except queue.Empty:
                    continue
        finally:
            self.unsubscribe(q)


HUB = ObservabilityHub()

# pre-register the agents that the RFP example + chat assistant will observe
def _seed_agents() -> None:
    HUB.register_agent(ObservedAgent(
        agent_id="rfp_workflow.orchestrator",
        name="RFP Orchestrator",
        flow_types=["rfp_workflow"], status="idle"))
    HUB.register_agent(ObservedAgent(
        agent_id="first_line_support",
        name="First Line Support Assistant",
        flow_types=["chat_session"], status="idle"))


_seed_agents()