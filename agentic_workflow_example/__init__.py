"""Agentic RFP Workflow — teaching example.

A self-contained, dependency-free implementation of the 4Geeks
"Agentic RFP Workflow" milestone (Parts 1-3) plus the event contracts
needed by the "Real-Time Systems: Agent Observability" project.

Purpose
-------
This branch (`agentic-workflow`) adapts the milestone to this repository so
the resulting code can be used as a *valid classroom example*:

* Part 1 — Intake & Routing (orchestrate):  data/pipelines/rfp_intake
* Part 2 — Response Generation (evaluate):  data/pipelines/rfp_response_generation
* Part 3 — Approval & Completion (produce): data/pipelines/rfp_approval_completion
* Observability contracts:                  data/pipelines/rfp_observability

Everything runs on the Python standard library (`import json`, `dataclasses`,
`threading`, ...) so it can be demoed in a single session without installing
anything. The same files are referenced from the ``data/pipelines/*`` mirror
layout that the real monorepo expects.
"""

__version__ = "0.1.0"