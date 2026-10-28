"""Durable JSON-backed store for the teaching example.

The real monorepo uses PostgreSQL (Supabase) via SQLModel — the BRIEFING
explicitly forbids TinyDB/JSON-only as the source of truth *in the graded
project*. In this *classroom example* we use a thread-safe JSON store so the
whole thing runs with zero dependencies; the README documents how to swap this
for Postgres when following the graded path.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import Ticket


class Store:
    """Thread-safe JSON store. One file per ticket under ``data/state/``.

    Every write is atomic (temp file + replace) so a crash never corrupts the
    current state — the same resiliency goal as a checkpointer, minus the DB.
    """

    def __init__(self, state_dir: str | Path = "data/state"):
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, ticket_id: str) -> Path:
        return self._dir / f"ticket_{ticket_id}.json"

    def save(self, ticket: Ticket) -> None:
        with self._lock:
            ticket.touch()
            tmp = self._path(ticket.ticket_id).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(ticket.to_dict(), indent=2, ensure_ascii=False))
            tmp.replace(self._path(ticket.ticket_id))

    def load(self, ticket_id: str) -> Ticket | None:
        with self._lock:
            p = self._path(ticket_id)
            if not p.exists():
                return None
            return Ticket.from_dict(json.loads(p.read_text()))

    def exists(self, ticket_id: str) -> bool:
        return self._path(ticket_id).exists()

    def delete(self, ticket_id: str) -> None:
        with self._lock:
            p = self._path(ticket_id)
            if p.exists():
                p.unlink()

    def list_ticket_ids(self) -> list[str]:
        with self._lock:
            return sorted(fp.name.replace("ticket_", "").replace(".json", "")
                          for fp in self._dir.glob("ticket_*.json"))


DEFAULT_STORE = Store()