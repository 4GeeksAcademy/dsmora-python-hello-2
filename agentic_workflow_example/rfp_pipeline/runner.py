"""Generic runner that drives Parts 1-3 of the RFP workflow.

Each part is a *phase* that advances a ``Ticket`` to the next recognisable
status, persisting with a checkpointer after every node. State survives a
crash and can resume exactly where it left off (Part 3 requires `resume`).

Phase contract: ``fn(ticket, context) -> None``. The runner snapshots state
before/after each phase and records a ``TraceEntry`` per node for the
observability chain.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Optional

from .models import (ActionType, Status, Ticket, TraceEntry)
from .store import Store


@dataclasses.dataclass
class PhaseResult:
    phase: str
    ticket_id: str
    from_status: str
    to_status: str
    ok: bool = True
    error: str = ""


PhaseFn = Callable[[Ticket, Store], None]


class RfpRunner:
    """Drives the pipeline. ``store`` acts as the checkpointer."""

    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    # ------------------------------------------------------------------
    # low-level checkpoint helpers
    # ------------------------------------------------------------------
    def checkpoint(self, ticket: Ticket, node: str, agent: str,
                   action_type: str = ActionType.DRAFT_START.value,
                   inp: object = None, out: object = None) -> None:
        ticket.trace.append(TraceEntry(
            agent=agent, action_type=action_type, node=node,
            ticket_id=ticket.ticket_id, input_snapshot=inp,
            output_snapshot=out, timestamp=__import__("time").strftime(
                "%Y-%m-%dT%H:%M:%S", __import__("time").gmtime()),
        ))
        self.store.save(ticket)  # durable after every node

    def transition(self, ticket: Ticket, status: str) -> None:
        ticket.status = status
        self.store.save(ticket)

    # ------------------------------------------------------------------
    # phase drivers
    # ------------------------------------------------------------------
    def run_phase(self, phase: str, ticket: Ticket,
                  fn: PhaseFn, expected: Optional[str] = None) -> PhaseResult:
        if expected and ticket.status != expected:
            return PhaseResult(phase, ticket.ticket_id, ticket.status, ticket.status,
                               ok=False, error=f"expected '{expected}', got '{ticket.status}'")
        from_status = ticket.status
        try:
            fn(ticket, self.store)
            self.store.save(ticket)
        except Exception as e:  # noqa: BLE001 - teaching runner surfaces any failure
            return PhaseResult(phase, ticket.ticket_id, from_status, ticket.status,
                               ok=False, error=str(e))
        return PhaseResult(phase, ticket.ticket_id, from_status, ticket.status, ok=True)

    # ------------------------------------------------------------------
    # the three public entry points (one per milestone part)
    # ------------------------------------------------------------------
    def run_part1_intake(self, ticket: Ticket) -> PhaseResult:
        from .part1_intake import intake_phase
        return self.run_phase("intake", ticket, intake_phase,
                              expected=Status.ANALYZING.value)

    def run_part2_evaluation(self, ticket: Ticket) -> PhaseResult:
        from .part2_evaluation import evaluation_phase
        return self.run_phase("evaluation", ticket, evaluation_phase,
                              expected=Status.INTAKE_COMPLETE.value)

    def run_part3_approval(self, ticket: Ticket) -> PhaseResult:
        from .part3_approval import approval_phase
        # Part 3 accepts tickets that exhausted Part 2 iterations
        # (needs_human_review) as well as clean under_evaluation ones.
        allowed = (Status.UNDER_EVALUATION.value, Status.NEEDS_HUMAN_REVIEW.value)
        if ticket.status not in allowed:
            return PhaseResult("approval", ticket.ticket_id, ticket.status, ticket.status,
                               ok=False,
                               error=f"expected one of {allowed}, got '{ticket.status}'")
        return self.run_phase("approval", ticket, approval_phase, expected=None)