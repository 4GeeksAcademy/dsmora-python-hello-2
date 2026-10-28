# Agentic RFP Workflow — ejemplo de clase (rama `agentic-workflow`)

> Esta rama implementa un **ejemplo docente** que mapea los 3 proyectos del
> temario (**orchestrate → evaluate → produce**) más el proyecto de
> **observability** (SSE en tiempo real) en un flujo RFP → documento final,
> con **solo la librería estándar de Python** y gestionado con **uv**.

Todo (instalación con `uv`, tests, E2E, servidor SSE y Docker) está explicado
en **`README.md`** (en inglés). Los comandos esenciales:

```bash
uv sync
uv run python -m unittest discover -s tests -p 'test_*.py'   # 29 tests
uv run rfp-e2e                                               # E2E 3 seeds
uv run observability-server                                  # dashboard + SSE en :8000
docker compose up -d                                         # todo con docker
```

El base `main.py` del starter 4Geeks se conserva tal cual; esta rama añade
`agentic_workflow_example/`, `services/`, `tests/`, `run_rfp_e2e.py` y la
configuración de `uv` (`pyproject.toml` + `uv.lock`) + Docker.

### Novedades de esta rama

- **Dashboard con 2 modos pedagógicos:** PARTE 1 (REST con recarga manual) y
  PARTE 2 (SSE en vivo sin recarga) — para ver la diferencia entre polling y
  streaming.
- **Subida de RFP** desde el dashboard (`POST /api/upload` multipart).
- **Control humano (HITL):** cada RFP subido se detiene en `waiting_for_approval`
  para que un humano apruebe/rechace/solicite cambios por departamento.
- **LLM opcional:** si existe `.env` con claves de 4Geeks y `RFP_USE_LLM=1`,
  los borradores los genera el modelo (fallback deterministico si falla la red).

### ¿Cómo subir un nuevo RFP?

1. **Dashboard** — arrastra o selecciona archivo en `http://localhost:8000/`.
2. **CLI:** `uv run rfp-e2e <ruta/al/archivo.md>`.
3. **Añadir seed:** en `run_rfp_e2e.py`, agrega entrada a `SEEDS`.
4. **Docker:** suelta el archivo en `./data/raw/` (bind-mounted en el contenedor).

### Contribuidores

Esta plantilla fue creada como parte de los [Recursos de Python de 4Geeks](https://4geeks.com/es/technology/python) para el aprendizaje en [4Geeks.com](https://4geeks.com) por [Alejandro Sanchez](https://twitter.com/alesanchezr) y [muchos otros contribuyentes](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
