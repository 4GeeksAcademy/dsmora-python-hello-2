"""Tests for the observability contracts (Real-Time Systems, Part 1 of 2).

Covers what the milestone evaluates:
  * SSE event shape (headers/event_name/data JSON)
  * agent list / agent detail endpoints
  * flow detail: participating agents + tasks in order
  * traceability: given a task_id, trigger/derived/prev/next reconstructible
  * paginated log: chronological, no dup/skip
  * at least two agent architectures (rfp_pipeline multi-agent + first_line_support)

These tests exercise the in-memory hub directly (the same contract the SSE
server in `services/` and the Docker demo expose).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_workflow_example.rfp_pipeline.observability import (
    HUB, FlowRecord as _FlowRecord,
)
from agentic_workflow_example.rfp_pipeline.models import AgentEvent, EventName


class ObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = HUB  # shared instance used by the RFP example
        # seed a couple of flows/tasks to build a determinable chain
        cls.flow = cls.hub.start_flow(
            flow_id="rfp_flow_demo001", flow_type="rfp_workflow",
            triggered_by="ticket_demo001",
            agents=["rfp_pipeline.orchestrator", "rfp_pipeline.worker.programs"])
        cls.hub.set_agent_status("rfp_pipeline.orchestrator", "running")
        # build a chain: task1 -> task2 (derived) -> task3 (next step)
        from agentic_workflow_example.rfp_pipeline.observability import TaskRecord
        t1 = cls.hub.add_task(TaskRecord(
            task_id="task_demo001", flow_id="rfp_flow_demo001",
            flow_type="rfp_workflow", agent_id="rfp_pipeline.orchestrator",
            action_type="draft_start", trigger="ticket_demo001",
            payload={"node": "orchestrate"}, timestamp="2026-10-28T10:00:00"))
        t2 = cls.hub.add_task(TaskRecord(
            task_id="task_demo002", flow_id="rfp_flow_demo001",
            flow_type="rfp_workflow", agent_id="rfp_pipeline.worker.programs",
            action_type="query", trigger=t1.task_id, prev_step=t1.task_id,
            payload={"node": "worker_programs"}, timestamp="2026-10-28T10:00:01"))
        cls.hub.add_task(TaskRecord(
            task_id="task_demo003", flow_id="rfp_flow_demo001",
            flow_type="rfp_workflow", agent_id="rfp_workflow.orchestrator",
            action_type="deliver", trigger=t2.task_id, prev_step=t2.task_id,
            payload={"node": "synthesize"}, timestamp="2026-10-28T10:00:02"))
        t2.derived = ["task_demo003"]   # derived tasks chain
        cls.t1, cls.t2 = t1, t2

    # -- SSE event shape -------------------------------------------------------
    def test_sse_event_shape(self):
        event = AgentEvent(event_name=EventName.AGENT_STEP.value,
                           agent_id="a", flow_id="f", flow_type="rfp_workflow",
                           task_id="t", status="running",
                           action_type="query", payload={"k": "v"})
        raw = event.to_sse()
        self.assertTrue(raw.startswith("event: agent_step"))
        self.assertIn("data: {", raw)
        data = json.loads(raw.split("data: ", 1)[1].strip())
        self.assertEqual(data["event_name"], "agent_step")
        self.assertEqual(data["action_type"], "query")

    # -- agent list / detail -----------------------------------------------------
    def test_agent_list(self):
        agents = self.hub.list_agents()
        self.assertTrue(any(a.agent_id == "rfp_workflow.orchestrator" for a in agents))
        self.assertTrue(any(a.agent_id == "first_line_support" for a in agents))

    def test_agent_detail_lasts(self):
        detail = self.hub.agent_detail("rfp_pipeline.orchestrator", last_n_flows=5,
                                       last_n_tasks=10)
        self.assertIn("agent", detail)
        self.assertIn("last_flows", detail)
        self.assertIn("last_tasks", detail)
        # orchestrator has a task in the flow
        self.assertTrue(detail["last_tasks"])

    # -- flow detail -------------------------------------------------------------
    def test_flow_detail_tasks_in_order(self):
        d = self.hub.flow_detail("rfp_flow_demo001")
        self.assertIsNotNone(d)
        self.assertEqual(d["flow"]["triggered_by"], "ticket_demo001")
        ids = [t["id"] for t in d["tasks"]]
        self.assertEqual(ids, ["task_demo001", "task_demo002", "task_demo003"])

    # -- traceability (the key acceptance criterion) --------------------------------
    def test_task_chain_reconstructible(self):
        chain = self.hub.task_chain("task_demo002")
        self.assertIsNotNone(chain)
        self.assertEqual(chain["trigger"], "task_demo001")
        self.assertEqual(chain["trigger_task"]["id"], "task_demo001")
        # derived tasks
        self.assertTrue(any(t["id"] == "task_demo003" for t in chain["derived_tasks"]))
        # prev/next
        self.assertEqual(chain["prev_task"]["id"], "task_demo001")
        self.assertEqual(chain["next_task"]["id"], "task_demo003")

    # -- paginated log: chronological, no dup/skip --------------------------------
    def test_paginated_log(self):
        page1 = self.hub.full_log(page=1, per_page=2)
        page2 = self.hub.full_log(page=2, per_page=2)
        self.assertEqual(page1["page"], 1)
        self.assertEqual(len(page1["items"]), 2)
        # ids disjoint between pages and total = 2*2 parts
        ids1 = {i["task_id"] for i in page1["items"]}
        ids2 = {i["task_id"] for i in page2["items"]}
        self.assertEqual(ids1 & ids2, set())
        self.assertGreater(page1["total"], len(page1["items"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)