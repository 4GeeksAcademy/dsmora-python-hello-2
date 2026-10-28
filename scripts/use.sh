#!/usr/bin/env bash
# --- Agentic RFP Workflow — comandos rápidos con uv -------------------------
# Uso:  ./scripts/use.sh [test|e2e|server|docker|help]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "${1:-help}" in
  test)
    uv run python -m unittest discover -s tests -p 'test_*.py' -v ;;
  e2e)
    uv run rfp-e2e ;;
  server)
    uv run observability-server ;;
  docker)
    docker compose up --build ;;
  lock)
    uv lock ;;
  help|*)
    echo "Uso: ./scripts/use.sh [test|e2e|server|docker|lock|help]"
    ;;
esac