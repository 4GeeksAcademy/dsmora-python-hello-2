#!/usr/bin/env python3
"""E2E runner for the Agentic RFP Workflow teaching example.

Usage:
    python run_rfp_e2e.py [pdf_path_or_seed]

    If no path is given, runs the built-in E2E test with the three seed
    documents (valid, informal-but-valid, invalid). State is saved under
    data/state/ and the final document is written to data/documents/.

    The script can resume a partially completed ticket (ID provided via
    --resume <ticket_id>) to demonstrate the checkpointer / Part 3
    interruption point.

Example:
    python run_rfp_e2e.py --seed valid  # only the valid grant
    python run_rfp_e2e.py               # quick E2E (3 RFPs)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# ensure the package is importable
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from agentic_workflow_example.rfp_pipeline.models import (
    ApprovalDecision, Status, Ticket, new_id,
)
from agentic_workflow_example.rfp_pipeline.runner import RfpRunner
from agentic_workflow_example.rfp_pipeline.part3_approval import (
    all_approved, resume_approval, run_approval_until_done,
)
from agentic_workflow_example.rfp_pipeline.store import Store

# ---------------------------------------------------------------------------
# Seed documents (deterministic — no external PDF needed)
# ---------------------------------------------------------------------------

SEEDS = {
    "valid": {
        "filename": "seed-grant-riverside.md",
        "content": (
            "# Neighborhood Reading Circle — Grant Application 2026\n\n"
            "Applicant: Riverside Community Association\n"
            "Date: 2026-11-15\n"
            "Requested amount: $12,400\n\n"
            "## Programs\n"
            "Weekly story hours for ages 6–10, summer reading kickoff. "
            "We expect 80 children per session. Saturday mornings preferred.\n\n"
            "## Facilities\n"
            "Needs Meeting Room B Saturday mornings; wheelchair ramp noted. "
            "Capacity: 40 people. After-hours key access required.\n\n"
            "## Finance\n"
            "60% upfront, 40% on attendance report. "
            "Requires 501(c)(3) letter. Budget line items attached.\n\n"
            "GRANT APPLICATION"
        ),
    },
    "informal": {
        "filename": "seed-grant-harbor.md",
        "content": (
            "# Harbor Youth Club — Quick Request\n\n"
            "Hi, we need $5,000 for art supplies. We have a small room at "
            "the community centre. Please let us know.\n\n"
            "Applicant: Harbor Youth Club\n"
            "Requested amount: $5,000\n\n"
            "GRANT APPLICATION"
        ),
    },
    "invalid": {
        "filename": "seed-menu.md",
        "content": (
            "# La Cantina Menu — Specials\n\n"
            "Appetizers: $6.99 | Mains: $12.99 | Desserts: $4.99\n"
            "Happy hour 5-7 PM daily.\n"
            "This is a restaurant menu. Ignore this — it is not a funding request.\n"
        ),
    },
}


def write_seed(key: str, target_dir: str = "data/raw") -> str:
    """Write a seed document to data/raw/ and return the path."""
    seed = SEEDS[key]
    dest = Path(target_dir) / seed["filename"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(seed["content"], encoding="utf-8")
    return str(dest)


def run_one(pdf_path: str, store: Store, runner: RfpRunner,
            auto_approve: bool = True) -> Ticket:
    """Run the full Parts 1→2→3 pipeline on one document.

    ``auto_approve=True`` reproduces the deterministic E2E (every department
    is approved automatically) — used by the CLI, the tests and the demo seed.
    ``auto_approve=False`` stops Part 3 at ``waiting_for_approval`` so a
    *human* can approve/reject each department from the dashboard (HITL).
    """
    ticket = Ticket(
        ticket_id=new_id("ticket_"),
        rfp_id=Path(pdf_path).stem,
        status=Status.ANALYZING.value,
        raw_pdf_path=pdf_path,
        submitter="E2E runner",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    )
    runner.store.save(ticket)

    # Part 1 — Intake
    print(f"  Part 1 (intake)...", end="", flush=True)
    r1 = runner.run_part1_intake(ticket)
    ticket = runner.store.load(ticket.ticket_id) or ticket
    if not r1.ok:
        print(f" FAIL: {r1.error}")
        return ticket
    print(f" {ticket.status}")
    if ticket.status == Status.DISCARDED.value:
        print("  -> stopped by classifier (expected for non-RFP).")
        return ticket

    # Part 2 — Evaluation
    print(f"  Part 2 (evaluation)...", end="", flush=True)
    r2 = runner.run_part2_evaluation(ticket)
    ticket = runner.store.load(ticket.ticket_id) or ticket
    if not r2.ok:
        print(f" FAIL: {r2.error}")
        return ticket
    print(f" {ticket.status}")

    # Part 3 — Approval
    print(f"  Part 3 (approval)...", end="", flush=True)
    if auto_approve:
        # deterministic E2E: every department auto-approved -> done
        _run_approval_with_resumes(ticket.ticket_id, store)
    else:
        # HITL: open the per-department approvals and pause for a human.
        runner.run_part3_approval(ticket)
    ticket = runner.store.load(ticket.ticket_id) or ticket
    print(f" {ticket.status}")
    if ticket.status == Status.DONE.value:
        doc = ticket.final_document
        print(f"  -> Final document: {doc.doc_id} ({doc.currency})")
    return ticket


def _resume_wrapper(store: Store, ticket_id: str):
    def _inner(dept: str, decision: str, comment: str = "") -> None:
        t = store.load(ticket_id)
        if t:
            resume_approval(t, dept, decision, comment)
            store.save(t)
    return _inner


def e2e_simulated(ticket: Ticket, store: Store) -> None:
    """Reproducible E2E with simulated approvals — used by the tests too."""
    runner = RfpRunner(store)
    runner.run_part1_intake(ticket)
    ticket = store.load(ticket.ticket_id) or ticket
    if ticket.status == Status.DISCARDED.value:
        return
    runner.run_part2_evaluation(ticket)
    ticket = store.load(ticket.ticket_id) or ticket
    _run_approval_with_resumes(ticket.ticket_id, store)


def _run_approval_with_resumes(ticket_id: str, store: Store) -> None:
    """Approve every pending department sequentially (deterministic E2E),
    then finalize the document once all departments have signed off.

    Mirrors Part 3 requirements: approvals recorded per department, then the
    ultimate synthesizer produces the final document -> ticket `done`.
    """
    from agentic_workflow_example.rfp_pipeline.part3_approval import _finalize
    ticket = store.load(ticket_id)
    if not ticket:
        return
    runner = RfpRunner(store)
    runner.run_part3_approval(ticket)
    for guard in range(20):
        ticket = store.load(ticket_id)
        if not ticket:
            return
        if all_approved(ticket):
            break
        for dept in ticket.drafting_order:
            rec = ticket.approvals.get(dept)
            if rec and rec.status == "waiting_for_approval":
                resume_approval(ticket, dept, ApprovalDecision.APPROVE.value,
                                "E2E auto-approved")
                store.save(ticket)
    ticket = store.load(ticket_id)
    if ticket and all_approved(ticket) and ticket.status != Status.DONE.value:
        _finalize(ticket, store)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    store = Store()
    runner = RfpRunner(store)

    if "--resume" in args:
        idx = args.index("--resume")
        ticket_id = args[idx + 1]
        ticket = store.load(ticket_id)
        if not ticket:
            print(f"Ticket '{ticket_id}' not found. Available: {store.list_ticket_ids()}")
            return
        print(f"Resuming ticket {ticket_id} (status={ticket.status})")
        _run_approval_with_resumes(ticket_id, store)
        ticket = store.load(ticket_id)
        print(f"Ticket status after resume: {ticket.status}")
        if ticket.status == Status.DONE.value:
            print(f"Final doc: {ticket.final_document.to_text()}")
        return

    if "--seed" in args:
        idx = args.index("--seed")
        seed_key = args[idx + 1]
        pdf = write_seed(seed_key)
        print(f"\nProcessing: {pdf}")
        run_one(pdf, store, runner)
        return

    # Default: full E2E across the three seeds
    print("=" * 60)
    print("Agentic RFP Workflow — E2E Teaching Example")
    print("=" * 60)
    for key in ("valid", "informal", "invalid"):
        pdf = write_seed(key)
        print(f"\n[{key.upper()}] Document: {pdf}")
        run_one(pdf, store, runner)

    print("\nAll E2E runs complete. State files in data/state/")
    print(f"Tickets: {store.list_ticket_ids()}")


if __name__ == "__main__":
    main()