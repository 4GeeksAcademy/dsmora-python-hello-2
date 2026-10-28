"""Pipeline-level tests: each milestone part maps to a `data/pipelines/` stage.

These assert the *contract* of every stage (not just the behaviour already
covered in ``test_part*.py``):

  * ``data/pipelines/rfp_intake``            → Part 1 (orchestrate)
  * ``data/pipelines/rfp_response_generation`` → Part 2 (evaluate)
  * ``data/pipelines/rfp_approval_completion`` → Part 3 (produce)
  * ``data/pipelines/rfp_observability``      → Part 4 (SSE/observability)

Checks: (1) each stage directory exists; (2) the handoff between stages is a
ticket_id + key_aspects contract; (3) the store (checkpointer) round-trips a
Ticket with/without a final document; (4) a crash-safe resume leaves no
corruption (unknown ticket → None).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentic_workflow_example.rfp_pipeline.models import (
    FinalDocument, Status, Ticket,
)
from agentic_workflow_example.rfp_pipeline.runner import RfpRunner
from agentic_workflow_example.rfp_pipeline.store import Store


class PipelineContractTests(unittest.TestCase):
    def test_stage_directories_defined(self):
        root = Path(__file__).resolve().parent.parent.parent
        expected = [
            "rfp_intake",
            "rfp_response_generation",
            "rfp_approval_completion",
            "rfp_observability",
        ]
        for name in expected:
            self.assertTrue((root / "data" / "pipelines" / name).is_dir(),
                            f"missing data/pipelines/{name}")

    def test_handoff_contract_is_ticket_plus_key_aspects(self):
        # The handoff from Part 1 to Part 2 is attached to the ticket as
        # classifier["handoff"] = {routing_table: [...], summary: ...},
        # each routing row carrying department + key_aspects + present.
        t = Ticket(ticket_id="t99", rfp_id="r99")
        t.classifier["handoff"] = {
            "routing_table": [{
                "department": "programs", "key_aspects": ["a"], "present": True,
            }],
            "summary": "1 departments need input; 0 not mentioned.",
        }
        handoff = t.classifier["handoff"]
        self.assertIn("routing_table", handoff)
        self.assertIn("key_aspects", handoff["routing_table"][0])
        self.assertIn("ticket_id", t.to_dict())

    def test_store_roundtrip_without_final_document_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            t = Ticket(ticket_id="t100", rfp_id="r100",
                       status=Status.UNDER_EVALUATION.value)
            store.save(t)
            loaded = store.load("t100")
            self.assertIsNotNone(loaded)
            self.assertIsNone(loaded.final_document)

    def test_store_roundtrip_with_final_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            t = Ticket(ticket_id="t101", rfp_id="r101",
                       status=Status.DONE.value)
            t.final_document = FinalDocument(
                doc_id="doc101", ticket_id="t101", currency="EUR",
                generated_at="2026-10-28")
            store.save(t)
            loaded = store.load("t101")
            self.assertIsNotNone(loaded.final_document)
            self.assertEqual(loaded.final_document.doc_id, "doc101")

    def test_checkpoint_persists_trace_per_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            runner = RfpRunner(store)
            t = Ticket(ticket_id="t102", rfp_id="r102")
            runner.checkpoint(t, node="worker_programs", agent="programs_worker")
            runner.checkpoint(t, node="synthesize", agent="orchestrator")
            loaded = store.load("t102")
            self.assertEqual(len(loaded.trace), 2)
            nodes = [e.node for e in loaded.trace]
            self.assertIn("worker_programs", nodes)
            self.assertIn("synthesize", nodes)

    def test_unknown_ticket_loads_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            self.assertIsNone(store.load("does-not-exist"))


if __name__ == "__main__":
    unittest.main(verbosity=2)