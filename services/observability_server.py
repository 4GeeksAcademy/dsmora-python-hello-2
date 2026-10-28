"""SSE / Observability HTTP server (stdlib-only) for the teaching example.

Exposes the ``ObservabilityHub`` from the RFP example over HTTP so that the
class can point any SSE client (EventSource, fetch + ReadableStream, curl) at
the running container and watch the agent chain in real time.

Endpoints
---------
* ``GET  /``                  -> HTML dashboard (minimal, live events via SSE)
* ``GET  /api/agents``        -> list of observed agents (id, name, flows, status)
* ``GET  /api/agents/{id}``   -> agent detail (last flows + last tasks)
* ``GET  /api/flows``         -> all flows with task counts
* ``GET  /api/flows/{id}``    -> flow detail (participating agents + tasks in order)
* ``GET  /api/log``           -> paginated event log (?page=&per_page=&agent_id=&flow_type=)
* ``GET  /api/tasks/{id}``    -> full traceability chain (trigger/derived/prev/next)
* ``GET  /events``            -> SSE stream: agent_step / agent_status_changed

Run:  python3 services/observability_server.py    (no dependencies, works in Docker)
Test: curl -N http://localhost:8000/events
      while true; do curl -s http://localhost:8000/api/log?page=1&per_page=5; sleep 2; done
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# make the repo root importable when run as `python3 services/...py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_workflow_example.rfp_pipeline.observability import HUB
from agentic_workflow_example.rfp_pipeline.runner import RfpRunner
from agentic_workflow_example.rfp_pipeline.store import DEFAULT_STORE

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

# Optional JWT gate so the graded frontend (fetch + ReadableStream with an
# `Authorization: Bearer …` header) can be pointed at /events.
# Set SSE_JWT_SECRET to enable; leave empty for the auth-free classroom demo.
SSE_JWT_SECRET = os.environ.get("SSE_JWT_SECRET", "").strip()


def _json_bytes(payload: dict, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return body.encode("utf-8"), status, "application/json; charset=utf-8"


class SseServer(BaseHTTPRequestHandler):
    server_version = "RFPExample/0.1"

    # -- helpers ---------------------------------------------------------------
    def _route(self) -> tuple[str, dict]:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        return path, query

    def _authorized(self) -> bool:
        """Accept if no secret is configured, else require `Bearer <secret>`."""
        if not SSE_JWT_SECRET:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {SSE_JWT_SECRET}"

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        body = b'{"error":"unauthorized"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body, status, ctype = _json_bytes(payload, status)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self, message: str = "not found") -> None:
        self._send_json({"error": message}, status=404)

    # -- GET dispatch ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path, query = self._route()
        try:
            if path in ("/", "/events") or path.startswith("/api/"):
                if not self._require_auth():
                    return
            if path == "/":
                self._serve_index()
            elif path == "/events":
                self._serve_sse(query)
            elif path == "/api/agents":
                self._send_json({"agents": [a.to_dict() for a in HUB.list_agents()]})
            elif path.startswith("/api/agents/"):
                agent_id = path.removeprefix("/api/agents/")
                detail = HUB.agent_detail(agent_id)
                if not detail.get("agent"):
                    return self._send_404(f"agent {agent_id!r} not found")
                self._send_json(detail)
            elif path == "/api/flows":
                flows = [f.to_dict() for f in HUB._flows.values()]
                for f in flows:
                    f["task_count"] = sum(
                        1 for t in HUB._tasks.values() if t.flow_id == f["id"])
                self._send_json({"flows": flows})
            elif path.startswith("/api/flows/"):
                flow_id = path.removeprefix("/api/flows/").split("?")[0]
                detail = HUB.flow_detail(flow_id)
                if detail is None:
                    return self._send_404(f"flow {flow_id!r} not found")
                self._send_json(detail)
            elif path == "/api/log":
                page = int(query.get("page", ["1"])[0])
                per_page = min(int(query.get("per_page", ["50"])[0]), 500)
                agent_id = query.get("agent_id", [None])[0]
                flow_type = query.get("flow_type", [None])[0]
                self._send_json(HUB.full_log(page, per_page, agent_id, flow_type))
            elif path == "/api/tickets":
                self._send_json({"tickets": _list_tickets()})
            elif path.startswith("/api/tickets/"):
                ticket_id = path.removeprefix("/api/tickets/").split("?")[0]
                t = DEFAULT_STORE.load(ticket_id)
                if t is None:
                    return self._send_404(f"ticket {ticket_id!r} not found")
                self._send_json({"ticket": t.to_dict()})
            elif path.startswith("/api/tasks/"):
                task_id = path.removeprefix("/api/tasks/").split("?")[0]
                chain = HUB.task_chain(task_id)
                if chain is None:
                    return self._send_404(f"task {task_id!r} not found")
                self._send_json({"task": chain})
            else:
                self._send_404()
        except (ValueError, KeyError) as e:
            self._send_json({"error": f"bad request: {e}"}, status=400)

    # -- POST dispatch ---------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path, query = self._route()
        if not self._require_auth():
            return
        try:
            if path == "/api/upload":
                self._handle_upload()
            elif path.startswith("/api/tickets/"):
                rest = path.removeprefix("/api/tickets/").split("?")[0]
                if "/approve" in rest:
                    ticket_id, dept = rest.split("/approve", 1)
                    dept = dept.strip("/")
                    self._handle_approve(ticket_id, dept)
                else:
                    self._send_404(f"unknown POST action for {path}")
            else:
                self._send_404()
        except (ValueError, KeyError) as e:
            self._send_json({"error": f"bad request: {e}"}, status=400)

    # -- HITL: approve/reject a department's draft (Part 3) --------------------
    def _handle_approve(self, ticket_id: str, department: str) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            return self._send_json({"error": "invalid JSON body"}, status=400)
        decision = str(body.get("decision", "")).strip()
        comment = str(body.get("comment", "")).strip()
        if decision not in ("approve", "reject", "request_changes"):
            return self._send_json(
                {"error": "decision must be approve|reject|request_changes"},
                status=400)
        from agentic_workflow_example.rfp_pipeline.part3_approval import (
            _finalize, resume_approval)
        ticket = DEFAULT_STORE.load(ticket_id)
        if ticket is None:
            return self._send_404(f"ticket {ticket_id!r} not found")
        if department not in ticket.approvals:
            return self._send_json(
                {"error": f"no approval record for department {department!r}"},
                status=400)
        resume_approval(ticket, department, decision, comment)
        DEFAULT_STORE.save(ticket)
        if _all_approved(ticket):
            _finalize(ticket, DEFAULT_STORE)
        HUB.add_task(_task_record(
            f"rfp_pipeline.human.{department}", "tool_call",
            {"ticket_id": ticket_id, "node": "resume_approval",
             "note": f"{decision} on {department} via dashboard"}))
        detail = DEFAULT_STORE.load(ticket_id)
        self._send_json({"ticket": detail.to_dict() if detail else None})

    # -- upload: save the file and run Parts 1→3 (HITL pauses at approvals) ----
    def _handle_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        filename = None
        filedata = b""
        if content_type.startswith("multipart/form-data"):
            boundary = content_type.split("boundary=", 1)[-1].strip().strip('"')
            marker = b"--" + boundary.encode("utf-8")
            parts = raw.split(marker)
            for part in parts:
                if b'name="file"' in part:
                    head, _, data = part.partition(b"\r\n\r\n")
                    filedata = data.rsplit(b"\r\n", 1)[0]
                    # Content-Disposition: form-data; name="file"; filename="x.pdf"
                    hdr = head.decode("utf-8", "replace")
                    if "filename=" in hdr:
                        filename = hdr.split('filename="', 1)[-1].split('"', 1)[0]
        else:
            # raw body fallback
            cd = self.headers.get("Content-Disposition", "")
            if 'filename="' in cd:
                filename = cd.split('filename="', 1)[-1].split('"', 1)[0]
            filedata = raw
        if not filename or not filedata:
            return self._send_json(
                {"error": "multipart field 'file' with a filename is required"},
                status=400)
        filename = os.path.basename(filename)  # no path traversal
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"upload_{int(time.time())}_{filename}"
        dest.write_bytes(filedata)
        print(f"[upload] saved {dest} ({len(filedata)} bytes)")
        # run the pipeline in a background thread (never block the dashboard)
        def _run():
            try:
                from run_rfp_e2e import run_one
                run_one(str(dest), DEFAULT_STORE, RfpRunner(DEFAULT_STORE),
                        auto_approve=False)
            except Exception as e:  # noqa: BLE001
                print(f"[upload] {dest} failed: {e}")
        threading.Thread(target=_run, daemon=True).start()
        self._send_json({"saved": str(dest), "filename": filename,
                         "size": len(filedata), "status": "processing"})

    # -- SSE ------------------------------------------------------------------
    def _serve_sse(self, query: dict) -> None:
        agent_filter = query.get("agent_id", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.flush()
        try:
            for sse in HUB.iter_events(agent_filter=agent_filter):
                self.wfile.write(sse.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- root dashboard --------------------------------------------------------
    def _serve_index(self) -> None:
        # Serve the real dashboard file (kept out of the source so it is easy
        # to edit). Falls back to the embedded INDEX_HTML if the file is gone.
        dashboard = Path(__file__).resolve().parent / "dashboard.html"
        if dashboard.exists():
            body = dashboard.read_text(encoding="utf-8")
        else:
            body = INDEX_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        pass


# ---------------------------------------------------------------------------
# Module-level helpers for the ticket / HITL API
# ---------------------------------------------------------------------------

def _all_approved(ticket) -> bool:
    from agentic_workflow_example.rfp_pipeline.models import DeptApprovalStatus
    return bool(ticket.approvals) and all(
        r.status == DeptApprovalStatus.APPROVED.value for r in ticket.approvals.values())


def _task_record(agent: str, action_type: str, payload: dict):
    from agentic_workflow_example.rfp_pipeline.observability import TaskRecord, new_id
    return TaskRecord(
        task_id=f"task_{new_id()}", flow_id="rfp_workflow", flow_type="rfp_workflow",
        agent_id=agent, action_type=action_type, payload=payload,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    )


def _list_tickets() -> list[dict]:
    out = []
    # Store.list_ticket_ids() returns ids *without* the "ticket_" prefix
    # (it strips it from the filename), but load() expects the full id.
    for tid in DEFAULT_STORE.list_ticket_ids():
        full_id = tid if tid.startswith("ticket_") else f"ticket_{tid}"
        t = DEFAULT_STORE.load(full_id)
        if not t:
            continue
        d = t.to_dict()
        # light summary (avoid shipping the whole trace in the table)
        d.pop("trace", None)
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Optional demo: run the RFP pipeline in the background, streaming its events
# ---------------------------------------------------------------------------

def run_live_demo(stop: threading.Event) -> None:
    """Run the 3-part RFP pipeline in the background, publishing SSE events.

    This is what makes ``docker compose up`` demonstrable: tickets flow
    through intake → evaluation → approval while the panel on `/` streams
    ``agent_step`` / ``agent_status_changed`` in real time.
    """
    from run_rfp_e2e import SEEDS, run_one, write_seed

    runner = RfpRunner(DEFAULT_STORE)
    demo_dir = Path("data/raw")
    demo_dir.mkdir(parents=True, exist_ok=True)
    for key in ("valid", "informal", "invalid"):
        if stop.is_set():
            break
        seed = SEEDS[key]
        pdf_path = demo_dir / seed["filename"]
        write_seed(key, demo_dir)
        try:
            # "informal" stops at waiting_for_approval so a human can approve
            # the departments from the dashboard (Part 3 HITL demo).
            auto = key != "informal"
            run_one(str(pdf_path), DEFAULT_STORE, runner, auto_approve=auto)
        except Exception as e:  # noqa: BLE001 - demo must not die
            print(f"[demo] {key} failed: {e}")


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>RFP Agent Observability — REST dashboard</title>
<style>
  body{font-family:system-ui,sans-serif;margin:2rem;background:#0f172a;color:#e2e8f0}
  h1{font-size:1.4rem}
  .dim{color:#94a3b8;font-size:.85rem}
  .cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1rem}
  .card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:1rem}
  .card h2{margin:0 0 .5rem;font-size:1rem;color:#7dd3fc}
  .card pre{background:#0f172a;padding:.6rem;border-radius:6px;overflow:auto;max-height:38vh;font-size:.8rem}
  .card table{width:100%;border-collapse:collapse;font-size:.8rem}
  .card td,.card th{padding:.25rem .4rem;border-bottom:1px solid #334155;text-align:left}
  .pill{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:.72rem}
  .ok{background:#14532d;color:#86efac}.warn{background:#78350f;color:#fcd34d}
  .idle{background:#334155;color:#e2e8f0}
  button{background:#0ea5e9;color:#fff;border:none;border-radius:6px;padding:.4rem .8rem;cursor:pointer}
  button.off{background:#64748b}
  .ev{color:#86efac}
  .sse-on .api-only{display:none}
</style></head>
<body>
<h1>RFP Agent Observability <span class="dim" id="status">(cargando API…)</span></h1>
<p class="dim">
  Data via REST (<code>/api/agents</code>, <code>/api/flows</code>, <code>/api/log</code>) — no requiere SSE.
  Refresh cada 2&nbsp;s. <button id="refresh">Refresh ahora</button>
  <button id="toggleSse" class="off">Conectar SSE /events</button>
</p>
<label class="dim">JWT (si el server tiene <code>SSE_JWT_SECRET</code>): <input id="token" placeholder="dejar vacío si es demo abierta" size="36"></label>

<div class="cols">
  <div class="card"><h2>Agents</h2>
    <table><thead><tr><th>id</th><th>status</th><th>flows</th></tr></thead>
    <tbody id="agents"><tr><td class="dim" colspan="3">—</td></tr></tbody></table>
  </div>
  <div class="card"><h2>Flows</h2>
    <table><thead><tr><th>flow</th><th>status</th><th>#tasks</th></tr></thead>
    <tbody id="flows"><tr><td class="dim" colspan="3">—</td></tr></tbody></table>
  </div>
  <div class="card"><h2>Log reciente (<code>/api/log</code>)</h2>
    <pre id="log" class="api-only">esperando…</pre>
  </div>
  <div class="card"><h2>Stream SSE (/events) <span class="dim" id="sseState">off</span></h2>
    <pre id="sse" class="dim">Pulsa "Conectar SSE" para ver eventos en vivo…
Esto es el punto de la clase (EventSource o fetch+ReadableStream con JWT).</pre>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const statusEl = $('status');
let es = null;

function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function pill(s){
  const c = s === 'done' ? 'ok' : (s === 'running' || s === 'under_evaluation' || s === 'needs_human_review' ? 'warn' : 'idle');
  return `<span class="pill ${c}">${esc(s)}</span>`;
}

async function loadAll(){
  try {
    const [agentsR, flowsR, logR] = await Promise.all([
      fetch('/api/agents'), fetch('/api/flows'), fetch('/api/log?per_page=20')
    ]);
    const agents = (await agentsR.json()).agents || [];
    const flows = (await flowsR.json()).flows || [];
    const log = (await logR.json()).items || [];

    $('agents').innerHTML = agents.map(a =>
      `<tr><td>${esc(a.id)}</td><td>${pill(a.status)}</td><td>${(a.flows||[]).join(', ')}</td></tr>`).join('');
    $('flows').innerHTML = flows.map(f =>
      `<tr><td>${esc(f.id)}</td><td>${pill(f.status)}</td><td>${f.task_count ?? ''}</td></tr>`).join('');
    $('log').textContent = log.map(e =>
      `[${e.event_name}] ${e.agent_id} :: ${e.action_type} :: ${e.status}${e.payload && e.payload.note ? ' :: ' + e.payload.note : ''}`)
      .join('\\n') || '(sin eventos todavía)';
    statusEl.textContent = `OK — ${agents.length} agents · ${flows.length} flows · ${log.length} eventos`;
  } catch(err){
    statusEl.textContent = 'ERROR: ' + err;
  }
}

function toggleSse(){
  if (es) { es.close(); es = null; $('sseState').textContent = 'off'; $('toggleSse').textContent = 'Conectar SSE /events'; $('toggleSse').className = 'off'; return; }
  const token = $('token').value.trim();
  const headers = token ? { 'Authorization': 'Bearer ' + token } : undefined;
  es = new EventSource('/events', headers ? { headers } : undefined);
  $('sseState').textContent = 'on'; $('toggleSse').textContent = 'Desconectar'; $('toggleSse').className = '';
  const sse = $('sse');
  es.addEventListener('agent_step', e => { sse.textContent = e.data + '\\n' + sse.textContent; sse.className = ''; });
  es.addEventListener('agent_status_changed', e => { sse.textContent = e.data + '\\n' + sse.textContent; sse.className = ''; });
  es.onerror = () => { sse.textContent = '[retrying…]\\n' + sse.textContent; };
}

$('refresh').onclick = loadAll;
$('toggleSse').onclick = toggleSse;
loadAll();
setInterval(loadAll, 2000);
</script></body></html>
"""


def main(serve: bool = True) -> int:
    stop = threading.Event()
    if serve:
        demo = threading.Thread(target=run_live_demo, args=(stop,), daemon=True)
        demo.start()
    print(f"Serving events on http://localhost:{PORT}/events")
    print(f"API root: http://localhost:{PORT}/api/agents")
    try:
        ThreadingHTTPServer((HOST, PORT), SseServer).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())