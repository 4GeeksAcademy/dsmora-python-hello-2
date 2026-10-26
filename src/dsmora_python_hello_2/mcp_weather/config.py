import os

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8002"))
MCP_ENDPOINT = os.getenv("MCP_ENDPOINT", f"http://{MCP_HOST}:{MCP_PORT}/mcp")