"""Part 1 — Intake & Routing ("orchestrate" mil-length).

Implements the teaching spine from the milestone, using a *neutral domain*
("Cornerstone Community Grants") so it can be demoed without leaking the
company BRIEFING answers:

    1. Ticket mode: upload PDF -> ticket `analyzing`
    2. PDF -> Markdown (MarkItDown-style converter; stub-able)
    3. Classifier gate: real RFP? -> `discarded` stops the flow
    4. Metadata + readability (py-readability-metrics style)
    5. Orchestrator decomposes into per-department work items
    6. Workers run in parallel, return department key aspects + contact hint
    7. Synthesizer merges into a Sales-facing routing summary (handoff)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .models import (ActionType, KeyAspects, ReadabilityMetrics, RfpMetadata,
                     Status, Ticket, WorkItem)
from .observability import HUB, TaskRecord, new_id
from .store import Store

# ---------------------------------------------------------------------------
# Department configuration (the *shared context* — mirror of a BRIEFING)
# ---------------------------------------------------------------------------

DEPARTMENTS = [
    {
        "id": "programs",
        "label": "Programs",
        "contact": "A. Rivera (Programs)",
        "sections": ["programming", "audience", "schedule", "outcomes"],
    },
    {
        "id": "facilities",
        "label": "Facilities",
        "contact": "M. Chen (Facilities)",
        "sections": ["space", "access", "hours", "safety"],
    },
    {
        "id": "finance",
        "label": "Finance",
        "contact": "D. Okafor (Finance)",
        "sections": ["budget", "matching", "milestones", "compliance"],
    },
]

DEFAULT_SECTIONS = {d["id"]: d["sections"] for d in DEPARTMENTS}
DOC_MARKER = "GRANT APPLICATION"


# ---------------------------------------------------------------------------
# 1. Ingestion: PDF -> Markdown + metadata + readability (+ raw copy)
# ---------------------------------------------------------------------------

class PDFConverter:
    """PDF -> Markdown conversion.

    This teaching example ships with two modes:
      * ``text`` : a self-contained converter that parses the seeded `.md`-like
                   fixtures (keeps tests dependency-free and deterministic).
      * ``markitdown`` : uses the real ``markitdown`` CLI if installed, so you
                   can demonstrate the real path from an actual PDF in class.

    The converter is *stub-able*: the graded project must use MarkItDown or a
    documented equivalent.
    """

    def convert(self, pdf_path: str, out_md: str) -> str:
        p = Path(pdf_path)
        suffix = p.suffix.lower()
        if suffix in (".md", ".txt"):
            return self._from_text(p.read_text(encoding="utf-8", errors="replace"), out_md)
        if suffix == ".pdf":
            return self._from_pdf(p, out_md)
        raise ValueError(f"Unsupported document type: {suffix}")

    def _from_text(self, text: str, out_md: str) -> str:
        # store a copy under data/raw/ + the .md sidecar under its md_path
        Path(out_md).parent.mkdir(parents=True, exist_ok=True)
        md = text if text.startswith("#") else f"# Grant Application\n\n{text}"
        Path(out_md).write_text(md, encoding="utf-8")
        return md

    def _from_pdf(self, pdf: Path, out_md: str) -> str:
        # Real path: try markitdown (documented equivalent), else raise.
        import shutil
        import subprocess
        if shutil.which("markitdown"):
            res = subprocess.run(["markitdown", str(pdf)], capture_output=True, text=True)
            if res.returncode == 0:
                Path(out_md).parent.mkdir(parents=True, exist_ok=True)
                Path(out_md).write_text(res.stdout, encoding="utf-8")
                return res.stdout
        raise RuntimeError(
            "PDF conversion needs `markitdown` (uv add markitdown) or a .md/.txt seed. "
            "See README.md -> 'Part 1' for the stub-able converter contract.")


def copy_pdf_to_raw(pdf_path: str, raw_dir: str = "data/raw") -> str:
    """Store the PDF under data/raw/ as part of the intake process."""
    import shutil
    p = Path(pdf_path)
    raw_dir_p = Path(raw_dir)
    raw_dir_p.mkdir(parents=True, exist_ok=True)
    dest = raw_dir_p / p.name
    if p.resolve() != dest.resolve():
        shutil.copyfile(p, dest)
    return str(dest)


def extract_metadata(md: str) -> RfpMetadata:
    """Deterministic metadata extraction for the neutral seed format."""
    meta = RfpMetadata()
    m = re.search(r"Applicant: (.+)", md)
    meta.client_name = m.group(1).strip() if m else ""
    m = re.search(r"Requested amount: \$?([\d,]+)", md)
    if m:
        meta.budget_range = f"${m.group(1)}"
    meta.services_requested = ["grant request"]  # neutral domain
    m = re.search(r"Date: (.+)", md)
    meta.deadline = m.group(1).strip() if m else ""
    meta.scope = md[:160].replace("\n", " ")
    meta.extracted_at = _ts()
    # departments mentioned
    meta.departments_needed = [d["id"] for d in DEPARTMENTS
                               if re.search(rf"\b{d['id']}\b", md, re.I)]
    return meta


def compute_readability(md: str) -> ReadabilityMetrics:
    """Lightweight stand-in for `py-readability-metrics` (Flesch-Kincaid etc.).

    Uses real, deterministic counts (syllables ~ vowels heuristic) so scores
    are stable across runs/tests without external deps.
    """
    words = re.findall(r"[A-Za-z']+", md.lower())
    wc = len(words)
    sentences = max(1, len(re.findall(r"[.!?]+", md)))
    syllables = sum(_syllables(w) for w in words)
    if wc == 0:
        return ReadabilityMetrics(word_count=0)
    fre = 206.835 - 1.015 * (wc / sentences) - 84.6 * (syllables / wc)
    fk = 0.39 * (wc / sentences) + 11.8 * (syllables / wc) - 15.59
    return ReadabilityMetrics(
        flesch_reading_ease=round(fre, 1),
        flesch_kincaid_grade=round(max(fk, 0.0), 1),
        gunning_fog=0.0,
        word_count=wc,
    )


def _syllables(word: str) -> int:
    word = word.lower()
    if len(word) <= 3:
        return 1
    count = len(re.findall(r"[aeiouy]+", word))
    return max(1, count)


def _ts() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# 2. Classifier gate
# ---------------------------------------------------------------------------

def classify_rfp(md: str) -> dict:
    """Deterministic classifier: is this a legitimate grant application/RFP?

    Returns ``{is_rfp, confidence, reason}`` so the ticket can be marked
    ``discarded`` when False.
    """
    text = md.lower()
    is_rfp = DOC_MARKER.lower() in text
    strong = sum(x in text for x in ("applicant", "requested amount", "budget"))
    confidence = 0.55 if strong >= 2 else (0.9 if is_rfp else 0.2)
    reason = ("Grant application marker found and key grant fields present"
              if is_rfp and strong >= 2
              else ("Grant marker present, few grant fields" if is_rfp
                    else "No grant-application marker found"))
    return {"is_rfp": is_rfp, "confidence": round(confidence, 2), "reason": reason}


# ---------------------------------------------------------------------------
# 3. Orchestrator -> Workers -> Synthesizer
# ---------------------------------------------------------------------------

def orchestrate(md: str, metadata: RfpMetadata, departments: Optional[list] = None) -> list:
    """Decompose the document into parallel per-department work items."""
    deps = departments or [d["id"] for d in DEPARTMENTS]
    items = []
    for dept in deps:
        sections = DEFAULT_SECTIONS.get(dept, [])
        # scoped extract: the section of the document that mentions this dept
        extract = _department_extract(md, dept)
        items.append(WorkItem(department=dept, sections=sections,
                              relevant_extract=extract))
    return items


def _department_extract(md: str, dept: str) -> str:
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    hits = [ln for ln in lines if dept.lower() in ln.lower()]
    return " | ".join(hits[:4]) if hits else ""


def worker_aspects(item: WorkItem, md: str) -> KeyAspects:
    """One worker per department; structured output.

    If the department is not mentioned anywhere, the worker returns
    ``present=False`` ("not mentioned") instead of inventing facts — exactly
    the milestone's rule ("workers must not invent volumes/figures absent from
    the RFP").
    """
    dept = item.department
    relevant = _department_extract(md, dept)
    present = bool(relevant)
    if not present:
        return KeyAspects(department=dept, aspects=["not mentioned"],
                          contact_hint=_contact(dept), present=False)
    aspects = _derive_aspects(dept, relevant)
    return KeyAspects(department=dept, aspects=aspects,
                      contact_hint=_contact(dept),
                      source_sections=item.sections, present=True)


def _contact(dept: str) -> str:
    for d in DEPARTMENTS:
        if d["id"] == dept:
            return d["contact"]
    return ""


def _derive_aspects(dept: str, extract: str) -> list:
    """Deterministic aspect derivation so tests are stable (no LLM needed)."""
    aspects = []
    if "&#36;" in extract or "$" in extract or "amount" in extract.lower():
        aspects.append("budget figure available")
    if "week" in extract.lower() or "satur" in extract.lower() or "hour" in extract.lower():
        aspects.append("schedule/timing detail present")
    if "access" in extract.lower() or "ramp" in extract.lower() or "ada" in extract.lower():
        aspects.append("accessibility detail present")
    if not aspects:
        aspects.append("general requirements for " + dept)
    return aspects


def synthesize(key_aspects_list: list) -> dict:
    """Consolidate into a Sales-facing routing summary (the handoff payload).

    ``ticket_id`` is added by the intake phase; this returns the *synthesizer
    payload* ready for the handoff contract expected by Part 2.
    """
    table = []
    for k in key_aspects_list:
        table.append({
            "department": k.department,
            "key_aspects": k.aspects,
            "contact_hint": k.contact_hint,
            "present": k.present,
        })
    return {"routing_table": table, "summary":
            f"{len([t for t in table if t['present']])} departments need input; "
            f"{len([t for t in table if not t['present']])} not mentioned."}


# ---------------------------------------------------------------------------
# The intake phase (called by the runner)
# ---------------------------------------------------------------------------

def intake_phase(ticket: Ticket, store: Store) -> None:
    """Drive one ticket through Part 1 from `analyzing`."""
    assert ticket.status == Status.ANALYZING.value

    # --- 1. ingest: PDF -> Markdown (before any agent) ---------------------
    converter = PDFConverter()
    md = converter.convert(ticket.raw_pdf_path, ticket.md_path or _default_md(ticket))
    ticket.md_path = ticket.md_path or _default_md(ticket)
    _emit(ticket, "rfp_pipeline.converter", ActionType.TOOL_CALL.value,
          "pdf_to_markdown", "RFP converted")

    # --- 2. metadata + readability ------------------------------------------
    ticket.metadata = extract_metadata(md)
    ticket.readability = compute_readability(md)
    _emit(ticket, "rfp_pipeline.extractor", ActionType.QUERY.value,
          "metadata_extract", "metadta+readability stored")

    # --- 3. classifier gate --------------------------------------------------
    ticket.classifier = classify_rfp(md)
    if not ticket.classifier["is_rfp"]:
        ticket.status = Status.DISCARDED.value
        _emit(ticket, "rfp_pipeline.classifier", ActionType.QUERY.value,
              "classifier_gate", "NOT an RFP -> discarded", status=Status.DISCARDED.value)
        return

    # --- 4. orchestrate -------------------------------------------------------
    ticket.work_items = orchestrate(md, ticket.metadata)
    _emit(ticket, "rfp_pipeline.orchestrator", ActionType.DRAFT_START.value,
          "orchestrate", f"{len(ticket.work_items)} work items")

    # --- 5. workers (parallel) ------------------------------------------------
    ticket.key_aspects = [worker_aspects(item, md) for item in ticket.work_items]
    for k in ticket.key_aspects:
        _emit(ticket, f"rfp_pipeline.worker.{k.department}", ActionType.QUERY.value,
              f"worker_{k.department}", f"{len(k.aspects)} aspects, present={k.present}")

    # --- 6. synthesizer + handoff ---------------------------------------------
    ticket.classifier["handoff"] = synthesize(ticket.key_aspects)
    ticket.status = Status.INTAKE_COMPLETE.value
    _emit(ticket, "rfp_pipeline.synthesizer", ActionType.DELIVER.value,
          "synthesize", f"handoff ready ({len(ticket.key_aspects)} depts)",
          status=Status.INTAKE_COMPLETE.value)


def _default_md(ticket: Ticket) -> str:
    pdf = Path(ticket.raw_pdf_path)
    return str(Path("data/documents") / f"{pdf.stem}.md")


def _emit(ticket: Ticket, agent: str, action_type: str, node: str,
          note: str, status: Optional[str] = None) -> None:
    """Publish a TaskRecord to the observability hub (the SSE contract)."""
    flow_id = f"rfp_flow_{ticket.ticket_id}"
    task_id = f"task_{new_id()}"
    task = TaskRecord(
        task_id=task_id, flow_id=flow_id, flow_type="rfp_workflow",
        agent_id=agent, action_type=action_type, status=status or "completed",
        trigger=flow_id, payload={"ticket_id": ticket.ticket_id, "node": node, "note": note},
        timestamp=_ts(),
    )
    HUB.add_task(task)