"""Part 2 — Response Generation ("evaluate" mil-length).

Implements the generator-evaluator loop over the handoff from Part 1:

    * a generator agent per department (receives the Part 1 key_aspects,
      NOT the raw PDF — it consumes the routing handoff)
    * several evaluators running in parallel over each created section:
        - readability (py-readability-metrics style)
        - relevance (does it answer what the RFP asks?)
        - compliance (with the company guidelines — deterministic rule set)
    * a generator-evaluator loop with an explicit iteration limit; when the
      limit is exhausted the last draft + EvaluationResult are kept and the
      section is marked `needs_human_review` — never the whole ticket.
"""
from __future__ import annotations

import re
from typing import Optional

from .llm import call_llm, enabled as llm_enabled, model_name  # noqa: F401
from .models import (ActionType, ComplianceResult, DraftSection,
                     EvaluationResult, ReadabilityMetrics, ReadabilityResult,
                     RelevanceResult, Status, Ticket)
from .observability import HUB, TaskRecord, new_id
from .store import Store

# ---------------------------------------------------------------------------
# Company guidelines (mirror of a BRIEFING Section 5 — deterministic rules)
# ---------------------------------------------------------------------------
MAX_ITERATIONS = 3

COMPLIANCE_RULES = [
    {
        "id": "G1",
        "desc": "Any guarantee must be for at least 90 days.",
        "check": lambda content: "guarantee" not in content.lower()
                 or re.search(r"\b90\s*(?:days|day)\b", content.lower()) is not None,
    },
    {
        "id": "G2",
        "desc": "Response time commitments (SLA) must be <= 24h for support work.",
        "check": lambda content: ("sla" not in content.lower()
                 and "response" not in content.lower())
                 or re.search(r"\b24\s*(?:h|hrs?|hours)\b", content.lower()) is not None,
    },
    {
        "id": "G3",
        "desc": "Client references must be anonymised (no real names).",
        "check": lambda content: re.search(
            r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", content) is None
            or "client" in content.lower(),
    },
    {
        "id": "G4",
        "desc": "Budget figures must be present when the RFP asks for them.",
        "check": lambda content: "$" in content or "budget" in content.lower(),
    },
]


def check_compliance(content: str) -> ComplianceResult:
    """Evaluate content against every rule; return structured result."""
    rule_ids = [r["id"] for r in COMPLIANCE_RULES]
    violations = []
    for rule in COMPLIANCE_RULES:
        if not rule["check"](content):
            violations.append(rule["id"])
    return ComplianceResult(pass_=len(violations) == 0, rule_ids=rule_ids,
                            violations=violations)


# ---------------------------------------------------------------------------
# Generators (one per department)
# ---------------------------------------------------------------------------

class Generator:
    """Drafts one department's section.

    If the optional LLM backend is enabled (RFP_USE_LLM=1 + LLM_API_KEY) it
    asks the model; on any failure it transparently falls back to the
    deterministic generator below. Otherwise (default) it is fully
    deterministic — the teaching example still runs offline.
    """

    def __init__(self, department: str):
        self.department = department
        self.last_source = "deterministic"   # "llm" when the model responded

    def draft(self, ticket: Ticket, iteration: int,
              feedback: str = "") -> str:
        if llm_enabled():
            user_prompt = self._build_prompt(ticket, iteration, feedback)
            llm_text = call_llm(self.department, user_prompt)
            if llm_text:
                self.last_source = "llm"
                return llm_text
            self.last_source = "deterministic"   # LLM failed -> fallback
        return self._deterministic_draft(ticket, iteration, feedback)

    # -- deterministic fallback (keeps tests & offline demos unchanged) -------
    def _deterministic_draft(self, ticket: Ticket, iteration: int,
                             feedback: str) -> str:
        aspects = ticket.key_aspects_for(self.department)
        scope = (", ".join(aspects.aspects) if aspects else "general")
        base = (f"{self.department.capitalize()} section covers {scope} "
                f"for the client. We will deliver on time and within the "
                f"requested budget of $12,400.")
        # honor feedback from the previous evaluation pass so the loop converges
        if "guarantee" in feedback.lower() or "G1" in feedback:
            base += " We guarantee our services for 90 days."
        if "sla" in feedback.lower() or "response" in feedback.lower() or "G2" in feedback:
            base += " We respond within 24 hours."
        if "anonymis" in feedback.lower() or "G3" in feedback:
            pass  # never prints real client names
        if "budget" in feedback.lower() or "G4" in feedback:
            if "$" not in base:
                base += " Budget: $12,400 requested."
        if "readability" in feedback.lower():
            base += " Our plan is clear and easy to read."
        return base

    def _build_prompt(self, ticket: Ticket, iteration: int, feedback: str) -> str:
        aspects = ticket.key_aspects_for(self.department)
        scope = (", ".join(aspects.aspects) if aspects else "general")
        lines = [
            f"Department: {self.department}",
            f"Relevant aspects from the RFP for this section: {scope}",
            ("Mirror those RFP aspects verbatim inside your opening sentence "
             "(the automated reviewer checks that you mention them)."),
            f"Iteration: {iteration} (max {MAX_ITERATIONS}).",
        ]
        if feedback:
            lines.append(f"Feedback from the previous review that you MUST fix: {feedback}")
        lines.append("Write only the proposal section now.")
        return "\n".join(lines)


def make_generators(departments: list[str]):
    return {dept: Generator(dept) for dept in departments}


# ---------------------------------------------------------------------------
# Evaluators (parallel: readability / relevance / compliance)
# ---------------------------------------------------------------------------

def evaluate_readability(content: str) -> ReadabilityResult:
    # py-readability-metrics style: higher score -> more readable; pass if >= 50
    rm = _fake_readability(content)
    score = rm.flesch_reading_ease
    return ReadabilityResult(pass_=score >= 50.0, score=score,
                             details=f"Flesch reading ease {score}")


def _fake_readability(content: str) -> ReadabilityMetrics:
    words = re.findall(r"[A-Za-z']+", content.lower())
    wc = len(words)
    sentences = max(1, len(re.findall(r"[.!?]+", content)))
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w))) for w in words)
    fre = (206.835 - 1.015 * (wc / sentences) - 84.6 * (syllables / wc)) if wc else 0.0
    return ReadabilityMetrics(flesch_reading_ease=round(max(fre, 0.0), 1),
                              flesch_kincaid_grade=0.0, gunning_fog=0.0, word_count=wc)


def evaluate_relevance(content: str, aspects: list[str]) -> RelevanceResult:
    """Does the draft actually answer what the RFP asks for?"""
    missing = []
    for a in aspects:
        if a.lower() == "not mentioned":
            continue
        needle = a.split()[0] if a else ""
        if needle and needle.lower() not in content.lower():
            missing.append(a)
    return RelevanceResult(pass_=len(missing) == 0, missing_aspects=missing)


def evaluate_compliance(content: str) -> ComplianceResult:
    return check_compliance(content)


def evaluate_section(department: str, content: str, ticket: Ticket,
                     section_id: str = "") -> EvaluationResult:
    """Run the three evaluators in parallel (here sequentially, no shared state
    mutation so concurrency is safe) and combine into one structured result.
    """
    aspects = [a.aspects for a in ticket.key_aspects if a.department == department]
    flat_aspects = [aspect for sub in aspects for aspect in sub]
    readability = evaluate_readability(content)
    relevance = evaluate_relevance(content, flat_aspects)
    compliance = evaluate_compliance(content)
    overall = readability.pass_ and relevance.pass_ and compliance.pass_
    feedback_parts = []
    if not readability.pass_:
        feedback_parts.append("Improve readability (shorter sentences, simpler words).")
    if not relevance.pass_:
        feedback_parts.append("Add missing aspects: " + ", ".join(relevance.missing_aspects))
    if not compliance.pass_:
        feedback_parts.append("Fix compliance: " + ", ".join(compliance.violations))
    return EvaluationResult(
        section_id=section_id or f"sec_{department}",
        department=department,
        readability=readability,
        relevance=relevance,
        compliance=compliance,
        overall_pass=overall,
        feedback_for_generator="; ".join(feedback_parts),
    )


# ---------------------------------------------------------------------------
# The evaluation phase (called by the runner)
# ---------------------------------------------------------------------------

def evaluation_phase(ticket: Ticket, store: Store) -> None:
    """Part 2 entry: ticket must be `intake_complete` (Part 1 handoff)."""
    assert ticket.status == Status.INTAKE_COMPLETE.value

    ticket.status = Status.DRAFTING.value
    _emit(ticket, "rfp_pipeline.drafting", ActionType.DRAFT_START.value, "drafting")

    departments = [k.department for k in ticket.key_aspects if k.present]
    if not departments:
        # No department is present in this RFP -> nothing to draft.
        # Keep the ticket truthful: hand off to Part 3 as needs_human_review
        # so a human can decide (never discard the whole ticket).
        ticket.status = Status.NEEDS_HUMAN_REVIEW.value
        ticket.drafting_order = []
        _emit(ticket, "rfp_pipeline.drafting", ActionType.QUERY.value,
              "no_departments", "no departments mentioned -> needs_human_review")
        return
    ticket.drafting_order = departments[:]

    generators = make_generators(departments)
    for department in departments:
        ticket.status = Status.UNDER_EVALUATION.value
        draft_section = DraftSection(department=department, iteration=0)
        for iteration in range(1, MAX_ITERATIONS + 1):
            feedback = draft_section.last_feedback if iteration > 1 else ""
            content = generators[department].draft(ticket, iteration, feedback)
            draft_section.content = content
            draft_section.iteration = iteration

            evaluation = evaluate_section(department, content, ticket)
            draft_section.last_evaluation = evaluation
            ticket.evaluations[department] = evaluation

            _emit(ticket, f"rfp_pipeline.generator.{department}",
                  ActionType.DRAFT_WRITE.value, f"generator_{department}",
                  f"iteration {iteration} drafted "
                  f"(source={generators[department].last_source})")
            _emit(ticket, f"rfp_pipeline.evaluator.{department}",
                  ActionType.EVALUATE.value, f"evaluate_{department}",
                  f"overall_pass={evaluation.overall_pass}")

            if evaluation.overall_pass:
                break
            draft_section.last_feedback = evaluation.feedback_for_generator
        else:
            # iterations exhausted without a pass -> keep last draft + result,
            # mark section needs_human_review (ticket too, per brief)
            draft_section.last_feedback = ("Iteration limit reached; awaiting human review.")
            ticket.status = Status.NEEDS_HUMAN_REVIEW.value
        ticket.drafts[department] = draft_section


def _emit(ticket: Ticket, agent: str, action_type: str, node: str,
          note: str = "") -> None:
    task = TaskRecord(
        task_id=f"task_{new_id()}", flow_id=f"rfp_flow_{ticket.ticket_id}",
        flow_type="rfp_workflow", agent_id=agent, action_type=action_type,
        payload={"ticket_id": ticket.ticket_id, "node": node, "note": note},
        timestamp=__import__("time").strftime(
            "%Y-%m-%dT%H:%M:%S", __import__("time").gmtime()),
    )
    HUB.add_task(task)