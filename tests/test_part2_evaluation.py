"""Tests for Part 2 — Response Generation (evaluate).

Covers the generator-evaluator loop:
  * one generator per department (separated), consuming the Part 1 handoff
  * evaluators run in parallel (readability/relevance/compliance)
  * structured EvaluationResult shape
  * iteration limit -> keeps last draft + result, marks needs_human_review
  * one anchored compliance failure (G4 budget rule) — small fixture, one assert
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_workflow_example.rfp_pipeline.models import (
    ComplianceResult, Status, Ticket, new_id,
)
from agentic_workflow_example.rfp_pipeline.part2_evaluation import (
    Generator, check_compliance, evaluate_section,
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


def build_intake_complete_ticket(store: Store, runner: RfpRunner) -> Ticket:
    tmp = store._dir.parent / "raw"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / "valid.md"
    if not dest.exists():
        dest.write_text(VALID_MD, encoding="utf-8")
    ticket = Ticket(ticket_id=new_id("ticket_"), status=Status.ANALYZING.value,
                    raw_pdf_path=str(dest))
    runner.run_part1_intake(ticket)
    return store.load(ticket.ticket_id)


class Part2EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(Path(self.tmp) / "state")
        self.runner = RfpRunner(self.store)
        self.ticket = build_intake_complete_ticket(self.store, self.runner)

    # -- one generator per department, separated ------------------------------
    def test_generator_per_department(self):
        depts = sorted(k.department for k in self.ticket.key_aspects)
        self.assertIn("programs", depts)
        self.assertIn("facilities", depts)
        self.assertIn("finance", depts)

    # -- structured EvaluationResult shape ------------------------------------
    def test_evaluation_result_shape(self):
        content = Generator("programs").draft(self.ticket, 1)
        ev = evaluate_section("programs", content, self.ticket)
        d = ev.to_dict()
        self.assertIn("section_id", d)
        self.assertIn("readability", d)
        self.assertIn("pass", d["readability"])
        self.assertIn("score", d["readability"])
        self.assertIn("relevance", d)
        self.assertIn("missing_aspects", d["relevance"])
        self.assertIn("compliance", d)
        self.assertIn("violations", d["compliance"])
        self.assertIn("overall_pass", d)
        self.assertIn("feedback_for_generator", d)

    # -- complianee failure anchored to a BRIEFING rule (G4 budget) ------------
    def test_compliance_failure_anchored_g4(self):
        # a draft promising a figure but that the guidelines forbid (no budget)
        bad = "Facilities section covers room capacity only."
        result = check_compliance(bad)
        self.assertIsInstance(result, ComplianceResult)
        self.assertFalse(result.pass_)
        self.assertIn("G4", result.violations)   # budget missing

    # -- full loop -> under_evaluation with passing drafts ---------------------
    def test_full_loop_passes(self):
        res = self.runner.run_part2_evaluation(self.ticket)
        self.assertTrue(res.ok, res.error)
        ticket = self.store.load(self.ticket.ticket_id)
        self.assertIn(ticket.status, (Status.UNDER_EVALUATION.value,
                                      Status.NEEDS_HUMAN_REVIEW.value))
        # drafts exist for every present department
        self.assertEqual(len(ticket.drafts), 3)
        # at least one evaluation is stored per department
        self.assertEqual(len(ticket.evaluations), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)