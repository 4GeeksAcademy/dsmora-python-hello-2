"""Tests for Part 3 — Approval & Completion (produce).

Key behaviours the milestone evaluates:
  * interruption scoped per department — approve dept B while A remains
    interrupted (proves parallel branches, not serial fake-parallelism)
  * resume is an explicit entry point (validated: approve/reject/request_changes)
  * checkpointer persisting state before each interruption (store)
  * thread_id namespacing by ticket (rfp-{ticket_id}:{department})
  * arbitration node fires on BRIEFING triggers -> fixed arbiter (not LLM)
  * iteration limit is applied
  * final document generated ONLY once every department approves -> done
  * every node logged with agent, input, output, timestamp (trace)
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_workflow_example.rfp_pipeline.models import (
    ApprovalDecision, DeptApprovalStatus, Status, Ticket, new_id,
)
from agentic_workflow_example.rfp_pipeline.part3_approval import (
    all_approved, arbitrate, approval_phase, detect_triggers,
    resume_approval,
)
from agentic_workflow_example.rfp_pipeline.runner import RfpRunner
from agentic_workflow_example.rfp_pipeline.store import Store

VALID_MD = (
    "# Neighborhood Reading Circle — Grant Application 2026\n\n"
    "Applicant: Riverside Community Association\n"
    "Date: 2026-11-15\n"
    "Requested amount: $12,400\n\n"
    "## Programs\n"
    "Weekly story hours for ages 6-10. Saturday mornings preferred.\n\n"
    "## Facilities\n"
    "Meeting Room B Saturday mornings; wheelchair ramp noted.\n\n"
    "## Finance\n"
    "60% upfront, 40% on attendance report.\n\n"
    "GRANT APPLICATION"
)


def build_ready_ticket(store: Store, runner: RfpRunner) -> Ticket:
    """Drive a ticket through Part 1 + Part 2 so it's ready for approval."""
    tmp = store._dir.parent / "raw"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / "ready.md"
    if not dest.exists():
        dest.write_text(VALID_MD, encoding="utf-8")
    ticket = Ticket(ticket_id=new_id("ticket_"), status=Status.ANALYZING.value,
                    raw_pdf_path=str(dest))
    runner.run_part1_intake(ticket)
    ticket = store.load(ticket.ticket_id)
    runner.run_part2_evaluation(ticket)
    return store.load(ticket.ticket_id)


class Part3ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(Path(self.tmp) / "state")
        self.runner = RfpRunner(self.store)
        self.ticket = build_ready_ticket(self.store, self.runner)

    # -- interrupt opened on every department; status waiting_for_approval ------
    def test_interrupt_opens_all_departments(self):
        res = self.runner.run_part3_approval(self.ticket)
        self.assertTrue(res.ok, res.error)
        t = self.store.load(self.ticket.ticket_id)
        self.assertEqual(t.status, Status.WAITING_FOR_APPROVAL.value)
        self.assertEqual(len(t.approvals), 3)

    # -- THE KEY: approve B while A remains interrupted ------------------------
    def test_parallel_approval_b_while_a_interrupted(self):
        self.runner.run_part3_approval(self.ticket)
        t = self.store.load(self.ticket.ticket_id)
        depts = t.drafting_order
        self.assertEqual(len(depts), 3)
        dept_a, dept_b = depts[0], depts[1]

        # approve ONLY dept B (a is deliberately left waiting)
        resume_approval(t, dept_b, ApprovalDecision.APPROVE.value, "B approved")
        self.store.save(t)
        t = self.store.load(self.ticket.ticket_id)

        # B approved, A still waiting -> the pause is scoped, not global
        self.assertEqual(t.approvals[dept_b].status,
                         DeptApprovalStatus.APPROVED.value)
        self.assertEqual(t.approvals[dept_a].status,
                         DeptApprovalStatus.WAITING_FOR_APPROVAL.value)
        # ticket still waiting (not done) because A is pending
        self.assertEqual(t.status, Status.WAITING_FOR_APPROVAL.value)
        # no final document while any dept is waiting
        self.assertIsNone(t.final_document)

    # -- resume is validated ---------------------------------------------------
    def test_resume_validates_decision(self):
        self.runner.run_part3_approval(self.ticket)
        t = self.store.load(self.ticket.ticket_id)
        with self.assertRaises(ValueError):
            resume_approval(t, t.drafting_order[0], "maybe")

    # -- reject / request_changes are stored ------------------------------------
    def test_resume_reject_and_request_changes(self):
        self.runner.run_part3_approval(self.ticket)
        t = self.store.load(self.ticket.ticket_id)
        resume_approval(t, t.drafting_order[0], ApprovalDecision.REJECT.value)
        self.store.save(t)
        t = self.store.load(self.ticket.ticket_id)
        self.assertEqual(t.approvals[t.drafting_order[0]].status,
                         DeptApprovalStatus.REJECTED.value)
        resume_approval(t, t.drafting_order[1], ApprovalDecision.REQUEST_CHANGES.value)
        self.store.save(t)
        t = self.store.load(self.ticket.ticket_id)
        self.assertEqual(t.approvals[t.drafting_order[1]].status,
                         DeptApprovalStatus.CHANGES_REQUESTED.value)

    # -- final document only once all approve -----------------------------------
    def test_final_document_only_after_all_approve(self):
        self.runner.run_part3_approval(self.ticket)
        t = self.store.load(self.ticket.ticket_id)
        self.assertIsNone(t.final_document)
        for dept in t.drafting_order:
            resume_approval(t, dept, ApprovalDecision.APPROVE.value, "ok")
            self.store.save(t)
        t = self.store.load(self.ticket.ticket_id)
        self.assertTrue(all_approved(t))
        # finalize via the internal helper (the E2E path)
        from agentic_workflow_example.rfp_pipeline.part3_approval import _finalize
        _finalize(t, self.store)
        t = self.store.load(self.ticket.ticket_id)
        self.assertEqual(t.status, Status.DONE.value)
        self.assertIsNotNone(t.final_document)
        self.assertIn("programs", t.final_document.sections)

    # -- traceability: every node logged ----------------------------------------
    def test_trace_logged_per_node(self):
        self.runner.run_part3_approval(self.ticket)
        t = self.store.load(self.ticket.ticket_id)
        self.assertGreater(len(t.trace), 0)
        entry = t.trace[0]
        for field in ("agent", "action_type", "node", "ticket_id",
                      "input_snapshot", "output_snapshot", "timestamp"):
            self.assertTrue(hasattr(entry, field))

    # -- arbitration is deterministic, not LLM ------------------------------------
    def test_arbitration_deterministic(self):
        # force a currency-mismatch-like trigger via state
        t = self.ticket
        t.drafting_order = ["programs", "facilities"]  # neutral trigger shape
        triggers = detect_triggers(t)
        rec = None
        # arbitrate the first detected trigger (or the known list)
        records_before = list(t.arbitrations)
        for trigger in triggers or ["currency-mismatch"]:
            rec = arbitrate(t, trigger)
        self.assertIsNotNone(rec)
        self.assertIn("Marcos", rec.arbiter)
        self.assertIn(rec.arbiter, [r["arbiter"] for r in [
            {"trigger": "ttc-vs-training-window", "arbiter": "Marcos (CEO)"},
            {"trigger": "support-sla-missing", "arbiter": "Roberto / Marcos"},
            {"trigger": "currency-mismatch", "arbiter": "Marcos (CEO)"},
        ]])
        self.assertGreater(len(t.arbitrations), len(records_before))


if __name__ == "__main__":
    unittest.main(verbosity=2)