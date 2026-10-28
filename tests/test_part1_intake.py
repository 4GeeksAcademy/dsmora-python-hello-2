"""Tests for Part 1 — Intake & Routing (orchestrate).

Teaching spine (from the class example "Maple Street Library"):
  1. Valid grant PDF  -> `analyzing` -> `intake_complete`; synthesizer, 3 depts
  2. Non-grant PDF    -> classifier -> `discarded`; no worker calls
  3. Grant missing Finance -> worker returns "not mentioned" (present=False)
  4. Orchestrator emits >= 2 parallel work items
  5. Classifier + one worker unit-tested in isolation (no live LLM)

Runs with the standard library: `python -m unittest tests/test_part1_intake.py`
(or pytest if installed).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_workflow_example.rfp_pipeline.models import Status, Ticket, new_id
from agentic_workflow_example.rfp_pipeline.part1_intake import (
    classify_rfp, compute_readability, extract_metadata, orchestrate,
    worker_aspects,
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

MENU_MD = (
    "# La Cantina Menu — Specials\n\n"
    "Appetizers: $6.99 | Mains: $12.99 | Desserts: $4.99\n"
    "Happy hour 5-7 PM daily.\n"
    "This is a restaurant menu."
)

NO_FINANCE_MD = VALID_MD.replace(
    "## Finance\n60% upfront, 40% on attendance report.\n\n", "")


class Part1IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(Path(self.tmp) / "state")
        self.runner = RfpRunner(self.store)

    def _seed(self, name: str, content: str) -> str:
        dest = Path(self.tmp) / "raw" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return str(dest)

    # -- 1. valid grant -> intake_complete (3 departments) -------------------
    def test_valid_grant_intake_complete(self):
        pdf = self._seed("valid.md", VALID_MD)
        ticket = Ticket(ticket_id=new_id("ticket_"), status=Status.ANALYZING.value,
                        raw_pdf_path=pdf)
        res = self.runner.run_part1_intake(ticket)
        self.assertTrue(res.ok, res.error)
        ticket = self.store.load(ticket.ticket_id)
        self.assertEqual(ticket.status, Status.INTAKE_COMPLETE.value)
        self.assertTrue(ticket.classifier.get("is_rfp"))
        self.assertEqual(len(ticket.key_aspects), 3)
        self.assertIn("handoff", ticket.classifier)
        self.assertEqual(len(ticket.classifier["handoff"]["routing_table"]), 3)

    # -- 2. non-grant -> discarded; no workers -------------------------------
    def test_menu_discarded(self):
        before = len(self.store.list_ticket_ids())
        pdf = self._seed("menu.md", MENU_MD)
        ticket = Ticket(ticket_id=new_id("ticket_"), status=Status.ANALYZING.value,
                        raw_pdf_path=pdf)
        res = self.runner.run_part1_intake(ticket)
        self.assertTrue(res.ok)
        ticket = self.store.load(ticket.ticket_id)
        self.assertEqual(ticket.status, Status.DISCARDED.value)
        self.assertFalse(ticket.classifier.get("is_rfp"))
        self.assertEqual(ticket.key_aspects, [])          # no workers ran
        self.assertEqual(ticket.work_items, [])           # orchestrator not invoked

    # -- 3. missing Finance -> worker returns "not mentioned" ----------------
    def test_missing_finance_worker(self):
        pdf = self._seed("no_finance.md", NO_FINANCE_MD)
        ticket = Ticket(ticket_id=new_id("ticket_"), status=Status.ANALYZING.value,
                        raw_pdf_path=pdf)
        self.runner.run_part1_intake(ticket)
        ticket = self.store.load(ticket.ticket_id)
        finance = ticket.key_aspects_for("finance")
        self.assertIsNotNone(finance)
        self.assertFalse(finance.present)
        self.assertEqual(finance.aspects, ["not mentioned"])

    # -- 4. orchestrator emits >= 2 parallel work items ----------------------
    def test_orchestrator_parallel_work_items(self):
        meta = extract_metadata(VALID_MD)
        items = orchestrate(VALID_MD, meta)
        self.assertGreaterEqual(len(items), 2)

    # -- 5. classifier + one worker unit-tested in isolation -----------------
    def test_classifier_unit(self):
        self.assertTrue(classify_rfp(VALID_MD)["is_rfp"])
        self.assertFalse(classify_rfp(MENU_MD)["is_rfp"])

    def test_worker_unit(self):
        items = orchestrate(VALID_MD, extract_metadata(VALID_MD))
        programs = next(i for i in items if i.department == "programs")
        ka = worker_aspects(programs, VALID_MD)
        self.assertTrue(ka.present)
        self.assertIn("programs", ka.contact_hint.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)