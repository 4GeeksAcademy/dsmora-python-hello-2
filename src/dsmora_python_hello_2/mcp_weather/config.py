import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..config import load_env_file

load_env_file(Path(__file__).resolve().parents[3] / ".env")

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_ENDPOINT = os.getenv("MCP_ENDPOINT", f"http://{MCP_HOST}:{MCP_PORT}/mcp")


def _normalize_supabase_issuer(issuer: str) -> str:
	"""Accept either a Supabase project URL or its full Auth issuer URL."""
	issuer = issuer.strip().rstrip("/")
	if not issuer:
		return ""

	parsed = urlsplit(issuer)
	if parsed.hostname and parsed.hostname.endswith(".supabase.co") and parsed.path in {"", "/"}:
		return urlunsplit((parsed.scheme, parsed.netloc, "/auth/v1", parsed.query, parsed.fragment))
	return issuer


MCP_AUTH_ISSUER = _normalize_supabase_issuer(os.getenv("MCP_AUTH_ISSUER", ""))
MCP_AUTH_AUDIENCE = os.getenv("MCP_AUTH_AUDIENCE", "authenticated")
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", f"http://localhost:{MCP_PORT}/mcp")