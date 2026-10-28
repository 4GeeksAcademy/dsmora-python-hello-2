"""Optional LLM backend for Part 2 (stdlib-only, OpenAI-compatible).

This lets the RFP pipeline call a real model while keeping the teaching
example dependency-free — no `openai` SDK, just `urllib` from the standard
library.

Configuration (read from environment variables OR a root-level `.env`):

    LLM_API_URL   (default https://llm.4geeks.ai/v1)
    LLM_MODEL     (default madrid-spain/opnerouter/openai/gpt-6-luna)
    LLM_API_KEY   (required; loaded from `.env` if not set)
    RFP_USE_LLM   (set to "1"/"true" to enable the LLM path)

Design rules so the observable contract is preserved:

    * When the LLM is disabled (no key OR RFP_USE_LLM != 1) the pipeline
      behaves exactly as before: deterministic generator, no network calls.
      -> the 29 unit tests stay green and offline.
    * When enabled, `Generator.draft()` asks the model; if the call fails
      (timeout, HTTP error, bad JSON) it transparently falls back to the
      deterministic generator — the loop never breaks because of the network.
    * Keys are never logged nor included in any event payload.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://llm.4geeks.ai/v1"
DEFAULT_MODEL = "madrid-spain/opnerouter/openai/gpt-6-luna"
TIMEOUT_S = 30

# Cache so we read the .env only once per process.
_ENV_LOADED = False


def _load_dotenv() -> None:
    """Tiny .env loader (KEY=VALUE lines). Never logs values."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    root = Path(__file__).resolve().parent.parent.parent  # repo root
    env_file = root / ".env"
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            # Real environment variables win over .env entries.
            if key and os.environ.get(key) is None:
                os.environ[key] = value
    except OSError:
        return


def api_key() -> str:
    _load_dotenv()
    return os.environ.get("LLM_API_KEY", "").strip()


def api_url() -> str:
    _load_dotenv()
    return os.environ.get("LLM_API_URL", DEFAULT_URL).strip() or DEFAULT_URL


def model_name() -> str:
    _load_dotenv()
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def enabled() -> bool:
    """LLM path is on only when EXPLICITLY requested AND a key exists.

    Keeping it opt-in preserves deterministic offline tests and demos; the
    flag can be set to 1 in the environment (or .env / docker-compose).
    """
    if not api_key():
        return False
    flag = os.environ.get("RFP_USE_LLM", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


SYSTEM_PROMPT = (
    "You are the [{department}] department of a company writing a proposal "
    "response to a Request For Proposals (RFP). Write ONLY the [{department}] "
    "section of the proposal, in English, as a short plain-text paragraph of "
    "3-6 sentences.\n"
    "An automated reviewer checks your text for the following EXACT anchors. "
    "You MUST include them literally so the review passes on the first try:\n"
    "  G1: include the phrase \"guarantee\" and \"90 days\".\n"
    "  G2: include the phrase \"respond within 24 hours\" (or \"24 hours\").\n"
    "  G3: never print real client names (say \"the client\" instead).\n"
    "  G4: mention the budget amount, e.g. \"$12,400\".\n"
    "Keep sentences short and simple so it is easy to read."
)


def call_llm(department: str, user_prompt: str) -> str | None:
    """POST /chat/completions (OpenAI-compatible). Returns text or None.

    `None` means "could not use the LLM right now" — callers MUST fall back
    to their deterministic generator. No keys are logged.
    """
    if not enabled():
        return None
    key = api_key()
    payload = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(department=department)},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        f"{api_url().rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (urllib.error.HTTPError, urllib.error.URLError,
            OSError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return None