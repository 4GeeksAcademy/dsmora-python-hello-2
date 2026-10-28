"""Domain models for the Agentic RFP Workflow teaching example.

Mirrors — using a neutral domain — the entities required by the 4Geeks
"Agentic RFP Workflow" milestone (Parts 1-3) and the observability project
contracts.

* Ticket / RFP metadata / DepartmentSection.key_aspects (Part 1)
* DraftSection + EvaluationResult (Part 2)
* ApprovalRecord + FinalDocument (Part 3)
* Agent / Flow / Task events (Observability)

All models are JSON-serializable so the example persists its state as plain
JSON files with zero third-party dependencies.
"""
from __future__ import annotations

import dataclasses
import enum
import time
import uuid
from typing import Any, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def new_id(prefix: str = "") -> str:
    """Short unique id, e.g. `ticket_ab12cd34`."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Status(str, enum.Enum):
    """Ticket lifecycle across the three parts (exact BRIEFING vocabulary)."""

    ANALYZING = "analyzing"                       # Part 1 - upload accepted, agents running
    DISCARDED = "discarded"                       # Part 1 - classifier rejected the document
    INTAKE_COMPLETE = "intake_complete"           # Part 1 - synthesizer finished; handoff ready
    DRAFTING = "drafting"                         # Part 2 - generators writing sections
    UNDER_EVALUATION = "under_evaluation"         # Part 2 - parallel evaluators / gen-eval loop
    NEEDS_HUMAN_REVIEW = "needs_human_review"     # Part 2 - iteration limit exhausted
    WAITING_FOR_APPROVAL = "waiting_for_approval" # Part 3 - human-in-the-loop pause
    DONE = "done"                                 # Part 3 - final document stored


class ActionType(str, enum.Enum):
    """Observability `action_type` vocabulary (matches BRIEFING Nexova)."""

    QUERY = "query"
    TOOL_CALL = "tool_call"
    DRAFT_START = "draft_start"
    DRAFT_WRITE = "draft_write"
    EVALUATE = "evaluate"
    DELIVER = "deliver"


class EventName(str, enum.Enum):
    """SSE event names for the observability project."""

    AGENT_STEP = "agent_step"
    AGENT_STATUS_CHANGED = "agent_status_changed"


class ApprovalDecision(str, enum.Enum):
    """Valid human responses on resume (Part 3)."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class DeptApprovalStatus(str, enum.Enum):
    """Per-department approval state (Part 3)."""

    PENDING = "pending"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


# ---------------------------------------------------------------------------
# Value models
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ReadabilityMetrics:
    """Stored per processed document (Part 1) and used by the readability evaluator (Part 2)."""

    flesch_reading_ease: float = 0.0
    flesch_kincaid_grade: float = 0.0
    gunning_fog: float = 0.0
    word_count: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReadabilityMetrics":
        data = data or {}
        return cls(**{k: data.get(k, getattr(cls, k, 0)) for k in
                      ("flesch_reading_ease", "flesch_kincaid_grade", "gunning_fog", "word_count")})


@dataclasses.dataclass
class RfpMetadata:
    """Metadata extracted from the converted Markdown (Part 1)."""

    client_name: str = ""
    client_hq: str = ""
    services_requested: list = dataclasses.field(default_factory=list)
    scope: str = ""
    deadline: str = ""
    budget_range: str = ""
    departments_needed: list = dataclasses.field(default_factory=list)
    extracted_at: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RfpMetadata":
        data = data or {}
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: data.get(k) for k in known})


@dataclasses.dataclass
class KeyAspects:
    """Per-department extraction produced by a worker (Part 1). Fed to Part 2 generators."""

    department: str
    aspects: list = dataclasses.field(default_factory=list)
    contact_hint: str = ""
    source_sections: list = dataclasses.field(default_factory=list)
    present: bool = True          # False => department "not mentioned" in the RFP

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "KeyAspects":
        data = data or {}
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: data.get(k) for k in known})


@dataclasses.dataclass
class WorkItem:
    """A subtask the orchestrator decomposes the document into (Part 1)."""

    department: str
    sections: list = dataclasses.field(default_factory=list)
    relevant_extract: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        data = data or {}
        return cls(**{k: data.get(k) for k in ("department", "sections", "relevant_extract")})


# --- Part 2 -----------------------------------------------------------------

@dataclasses.dataclass
class ReadabilityResult:
    pass_: bool = False
    score: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["pass"] = d.pop("pass_")   # JSON shape matches the brief (pass/score/details)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ReadabilityResult":
        data = data or {}
        return cls(pass_=data.get("pass", False), score=data.get("score", 0.0),
                   details=data.get("details", ""))


@dataclasses.dataclass
class RelevanceResult:
    pass_: bool = False
    missing_aspects: list = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["pass"] = d.pop("pass_")
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RelevanceResult":
        data = data or {}
        return cls(pass_=data.get("pass", False), missing_aspects=data.get("missing_aspects", []))


@dataclasses.dataclass
class ComplianceResult:
    pass_: bool = False
    rule_ids: list = dataclasses.field(default_factory=list)
    violations: list = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["pass"] = d.pop("pass_")
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ComplianceResult":
        data = data or {}
        return cls(pass_=data.get("pass", False), rule_ids=data.get("rule_ids", []),
                   violations=data.get("violations", []))


@dataclasses.dataclass
class EvaluationResult:
    """Structured result of the three parallel evaluators (Part 2)."""

    section_id: str = ""
    department: str = ""
    readability: ReadabilityResult = dataclasses.field(default_factory=ReadabilityResult)
    relevance: RelevanceResult = dataclasses.field(default_factory=RelevanceResult)
    compliance: ComplianceResult = dataclasses.field(default_factory=ComplianceResult)
    overall_pass: bool = False
    feedback_for_generator: str = ""

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "department": self.department,
            "readability": self.readability.to_dict(),
            "relevance": self.relevance.to_dict(),
            "compliance": self.compliance.to_dict(),
            "overall_pass": self.overall_pass,
            "feedback_for_generator": self.feedback_for_generator,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationResult":
        data = data or {}
        return cls(
            section_id=data.get("section_id", ""),
            department=data.get("department", ""),
            readability=ReadabilityResult.from_dict(data.get("readability")),
            relevance=RelevanceResult.from_dict(data.get("relevance")),
            compliance=ComplianceResult.from_dict(data.get("compliance")),
            overall_pass=data.get("overall_pass", False),
            feedback_for_generator=data.get("feedback_for_generator", ""),
        )


@dataclasses.dataclass
class DraftSection:
    """A generated proposal section, with its latest evaluation (Part 2/3)."""

    department: str
    content: str = ""
    iteration: int = 0
    last_feedback: str = ""
    last_evaluation: Optional[EvaluationResult] = None
    approved: bool = False

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "content": self.content,
            "iteration": self.iteration,
            "last_feedback": self.last_feedback,
            "last_evaluation": self.last_evaluation.to_dict() if self.last_evaluation else None,
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DraftSection":
        data = data or {}
        ev = data.get("last_evaluation")
        return cls(
            department=data.get("department", ""),
            content=data.get("content", ""),
            iteration=data.get("iteration", 0),
            last_feedback=data.get("last_feedback", ""),
            last_evaluation=EvaluationResult.from_dict(ev) if ev else None,
            approved=data.get("approved", False),
        )


# --- Part 3 -----------------------------------------------------------------

@dataclasses.dataclass
class ApprovalRecord:
    """Per-department human sign-off (Part 3). `status` is a DeptApprovalStatus value."""

    department: str = ""
    status: str = DeptApprovalStatus.PENDING.value
    approver: str = ""
    decided_at: str = ""
    comment: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalRecord":
        data = data or {}
        return cls(**{k: data.get(k) for k in
                      ("department", "status", "approver", "decided_at", "comment")})


@dataclasses.dataclass
class ArbitrationRecord:
    """Result of the fixed-arbiter arbitration node (Part 3)."""

    trigger: str = ""
    arbiter: str = ""
    finding: str = ""
    acted_at: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArbitrationRecord":
        data = data or {}
        return cls(**{k: data.get(k) for k in ("trigger", "arbiter", "finding", "acted_at")})


@dataclasses.dataclass
class FinalDocument:
    """Generated only once every department has approved (Part 3)."""

    doc_id: str = ""
    ticket_id: str = ""
    sections: dict = dataclasses.field(default_factory=dict)   # dept -> approved content
    currency: str = ""
    generated_at: str = ""

    def to_text(self) -> str:
        lines = [f"PROPOSAL DOCUMENT {self.doc_id}", f"Ticket: {self.ticket_id}",
                 f"Currency: {self.currency}", ""]
        for dept in self.sections:
            lines.append(f"## {dept}")
            lines.append(self.sections[dept])
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FinalDocument":
        data = data or {}
        return cls(**{k: data.get(k) for k in
                      ("doc_id", "ticket_id", "sections", "currency", "generated_at")})


# --- Trace / observability --------------------------------------------------

@dataclasses.dataclass
class TraceEntry:
    """Every node execution: agent, input, output, timestamp (Part 3 traceability)."""

    agent: str = ""
    action_type: str = ""
    node: str = ""
    ticket_id: str = ""
    department: str = ""
    input_snapshot: Any = None
    output_snapshot: Any = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TraceEntry":
        data = data or {}
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: data.get(k) for k in known})


@dataclasses.dataclass
class AgentEvent:
    """Observability primitive: one step / status change to be streamed via SSE."""

    event_name: str = EventName.AGENT_STEP.value
    agent_id: str = ""
    flow_id: str = ""
    flow_type: str = ""
    task_id: str = ""
    status: str = ""
    action_type: str = ""
    payload: dict = dataclasses.field(default_factory=dict)
    timestamp: str = ""

    def to_sse(self) -> str:
        import json
        return f"event: {self.event_name}\ndata: {json.dumps(self.to_dict())}\n\n"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentEvent":
        data = data or {}
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: data.get(k) for k in known})


# --- Aggregate: the ticket --------------------------------------------------

@dataclasses.dataclass
class Ticket:
    """One RFP = one ticket, carried through all three parts.

    The same row that Part 1 opens travels through Part 2 and Part 3 — this is
    exactly the "one continuous experience" the milestone demands.
    """

    ticket_id: str = ""
    rfp_id: str = ""
    status: str = Status.ANALYZING.value
    raw_pdf_path: str = ""                # stored under data/raw/ (Part 1)
    md_path: str = ""                     # MarkItDown output (Part 1)
    metadata: Optional[RfpMetadata] = None
    readability: Optional[ReadabilityMetrics] = None
    classifier: dict = dataclasses.field(default_factory=dict)   # {is_rfp, confidence, reason}
    work_items: list = dataclasses.field(default_factory=list)   # list[WorkItem]
    key_aspects: list = dataclasses.field(default_factory=list)  # list[KeyAspects]
    drafting_order: list = dataclasses.field(default_factory=list)
    drafts: dict = dataclasses.field(default_factory=dict)       # dept -> DraftSection
    evaluations: dict = dataclasses.field(default_factory=dict)  # dept -> EvaluationResult
    approvals: dict = dataclasses.field(default_factory=dict)    # dept -> ApprovalRecord
    arbitrations: list = dataclasses.field(default_factory=list) # list[ArbitrationRecord]
    final_document: Optional[FinalDocument] = None
    trace: list = dataclasses.field(default_factory=list)        # list[TraceEntry]
    submitter: str = ""
    created_at: str = ""
    updated_at: str = ""

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "rfp_id": self.rfp_id,
            "status": self.status,
            "raw_pdf_path": self.raw_pdf_path,
            "md_path": self.md_path,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "readability": self.readability.to_dict() if self.readability else None,
            "classifier": self.classifier,
            "work_items": [w.to_dict() for w in self.work_items],
            "key_aspects": [k.to_dict() for k in self.key_aspects],
            "drafting_order": self.drafting_order,
            "drafts": {k: v.to_dict() for k, v in self.drafts.items()},
            "evaluations": {k: v.to_dict() for k, v in self.evaluations.items()},
            "approvals": {k: v.to_dict() for k, v in self.approvals.items()},
            "arbitrations": [a.to_dict() for a in self.arbitrations],
            "final_document": self.final_document.to_dict() if self.final_document else None,
            "trace": [t.to_dict() for t in self.trace],
            "submitter": self.submitter,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        data = data or {}
        o = cls(
            ticket_id=data.get("ticket_id", ""),
            rfp_id=data.get("rfp_id", ""),
            status=data.get("status", Status.ANALYZING.value),
            raw_pdf_path=data.get("raw_pdf_path", ""),
            md_path=data.get("md_path", ""),
            metadata=RfpMetadata.from_dict(data.get("metadata")),
            readability=ReadabilityMetrics.from_dict(data.get("readability")),
            classifier=data.get("classifier", {}),
            work_items=[WorkItem.from_dict(w) for w in (data.get("work_items") or [])],
            key_aspects=[KeyAspects.from_dict(k) for k in (data.get("key_aspects") or [])],
            drafting_order=data.get("drafting_order", []),
            drafts={k: DraftSection.from_dict(v) for k, v in (data.get("drafts") or {}).items()},
            evaluations={k: EvaluationResult.from_dict(v)
                         for k, v in (data.get("evaluations") or {}).items()},
            approvals={k: ApprovalRecord.from_dict(v)
                       for k, v in (data.get("approvals") or {}).items()},
            arbitrations=[ArbitrationRecord.from_dict(a) for a in (data.get("arbitrations") or [])],
            final_document=FinalDocument.from_dict(data.get("final_document"))
            if data.get("final_document") else None,
            trace=[TraceEntry.from_dict(t) for t in (data.get("trace") or [])],
            submitter=data.get("submitter", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", _now()),
        )
        return o

    # -- convenience helpers -------------------------------------------------

    def key_aspects_for(self, department: str) -> Optional[KeyAspects]:
        for k in self.key_aspects:
            if k.department == department:
                return k
        return None