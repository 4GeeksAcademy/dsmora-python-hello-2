# Agentic RFP Workflow — teaching example (branch `agentic-workflow`)

> **Rama de ejemplo para clase.** Mapea los 3 proyectos del temario
> (**orchestrate → evaluate → produce**) + el proyecto de **observability**
> (SSE en tiempo real) en un único flujo autocontenido (RFP → documento final),
> con **solo librería estándar de Python** y gestionado con **uv**.
>
> Dominio neutro a propósito: el ejemplo usa *RFP de financiación*
> (departamentos `programs`/`facilities`/`finance`) para no filtrar
> respuestas del BRIEFING de Nexova; la arquitectura es idéntica a la
> del proyecto real. El base `main.py` del starter 4Geeks se conserva tal cual.

## Requisitos

- **Python ≥ 3.12**
- **[uv](https://docs.astral.sh/uv/)** (gestor de entornos/deps). Instalar:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

El **entorno se crea solo** con `uv` (lee `pyproject.toml` + `uv.lock`).
El proyecto **no tiene dependencias runtime** (stdlib pura), por lo que
`uv sync` es instantáneo.

---

## Uso con uv

```bash
# 1. Crear/actualizar entorno y lockfile
uv sync                       # crea .venv e instala el paquete (editable)
uv lock                       # regenera uv.lock (si cambias pyproject.toml)

# 2. Tests (unittest: 29 casos)
uv run python -m unittest discover -s tests -p 'test_*.py'

# 3. E2E completo (los 3 seeds: valid → done, informal → done, invalid → discarded)
uv run rfp-e2e
uv run rfp-e2e --seed valid   # solo un seed
uv run rfp-e2e --resume <ticket_id>   # demuestra el checkpointer/resume (P3)

# 4. Servidor SSE + dashboard
uv run observability-server
# abre http://localhost:8000  (dashboard con EventSource)
```

Entry points definidos en `[project.scripts]`:

| Script                    | Equivale a                     |
|---------------------------|--------------------------------|
| `uv run rfp-e2e`          | `python run_rfp_e2e.py`        |
| `uv run observability-server` | `python services/observability_server.py` |

---

## Qué construye esta rama

```
agentic_workflow_example/
  rfp_pipeline/
    models.py             # agregado Ticket + modelos/estados (JSON-safe)
    store.py              # checkpointer JSON (1 fichero por ticket, atomic)
    runner.py             # drivers de fase + checkpoint por nodo
    part1_intake.py       # PARTE 1 · ORCHESTRATE -> intake_complete
    part2_evaluation.py   # PARTE 2 · EVALUATE      -> under_evaluation / needs_human_review
    part3_approval.py     # PARTE 3 · PRODUCE       -> waiting_for_approval -> done
    observability.py      # PARTE 4 · OBSERVABILITY -> hub + SSE (agent_step / agent_status_changed)
services/
  observability_server.py # API REST + streaming SSE ("listo para el punto de SSE")
run_rfp_e2e.py            # CLI E2E (3 seeds: valid / informal / invalid)
tests/
  test_part1_intake.py  test_part2_evaluation.py  test_part3_approval.py
  test_observability.py
  pipelines/test_pipeline_contract.py
```

### Mapeo pedagógico (proyectos → artefactos)

| Proyecto del temario  | Dirección `data/pipelines/`        | Fase en el código                          | Estado de salida            |
|-----------------------|------------------------------------|--------------------------------------------|-----------------------------|
| **Orchestrate** (P1)  | `rfp_intake`                        | `part1_intake.py` (clasificador→routing)   | `intake_complete`/`discarded`|
| **Evaluate**   (P2)  | `rfp_response_generation`           | `part2_evaluation.py` (generador→evaluador)| `under_evaluation`          |
| **Produce**    (P3)  | `rfp_approval_completion`           | `part3_approval.py` (aprobación→finalizador)| `done` + documento final   |
| **Observability**    | `rfp_observability`                | `observability.py` + `services/` (SSE)     | eventos `agent_step`/`agent_status_changed` |

Vocabulario de estados (el mismo del BRIEFING):
`analyzing → intake_complete → under_evaluation → needs_human_review → waiting_for_approval → done`
(además de `discarded`).

---

## Probar el punto de SSE (en tiempo real)

Con el server arriba (`uv run observability-server`):

```bash
# stream SSE (reproduce histórico y emite en vivo)
curl -N http://localhost:8000/events

# API REST
curl http://localhost:8000/api/agents
curl http://localhost:8000/api/agents/rfp_workflow.orchestrator   # detalle + últimas flows/tasks
curl http://localhost:8000/api/flows
curl http://localhost:8000/api/flows/rfp_flow_<ticket_id>          # agents + tasks en orden
curl "http://localhost:8000/api/log?page=1&per_page=5&agent_id=rfp_pipeline.orchestrator"
curl http://localhost:8000/api/tasks/<task_id>                     # traza: trigger → task → derived → prev/next
```

El dashboard en `/` usa `EventSource('/events')` y pinta los eventos en vivo.
Para el frontend del curso (que usa `fetch` + `ReadableStream` con cabecera JWT)
puedes apuntarlo a `/events`; en `observability_server.py` se documenta cómo
añadir la verificación de `Authorization: Bearer …`.

---

## Dashboard con 2 fases pedagógicas (REST → SSE)

El dashboard (`services/dashboard.html`, en español) está pensado para enseñar
la diferencia entre **polling** y **streaming en tiempo real** en dos pasos:

1. **PARTE 1 — REST (con recarga manual).** El tablero NO se actualiza solo:
   pulsas `🔄 Recargar ahora (REST)` y hace `fetch` a `/api/agents`,
   `/api/flows`, `/api/log`, `/api/tickets`. No hay `setInterval`: se ve
   claramente cómo "refrescas a mano" el estado.

2. **PARTE 2 — SSE (en vivo, sin recarga).** Pulsas `📡 Conectar SSE (en vivo)`
   y se abre un `EventSource('/events')`. Cada `agent_step` /
   `agent_status_changed` se **prepend** al panel de eventos y dispara una
   recarga automática del resto del tablero — sin recargar la página.

Además el dashboard incluye:
- **Subir un RFP** (`POST /api/upload`, campo `file` multipart).
- **Tabla de tickets** con estado y aprobaciones; clic en una fila muestra
  drafts + evaluaciones + el punto de aprobación humana (HITL).
- **Aprobación humana** por departamento: `Aprobar` / `Solicitar cambios` /
  `Rechazar` (ver sección HITL abajo).

---

## Integración con un LLM real (opcional)

Por defecto el pipeline es **determinista** (sin red). Se puede conectar a un
LLM compatible con OpenAI (endpoint de 4Geeks) leyendo el `.env`:

```bash
# .env (NO se sube a git; .env.example documenta las claves)
LLM_API_URL=https://llm.4geeks.ai/v1
LLM_MODEL=madrid-spain/opnerouter/openai/gpt-6-luna
LLM_API_KEY=sk-...
RFP_USE_LLM=1          # activa el uso del LLM (0/ausente -> determinista)
```

Con `RFP_USE_LLM=1`, el **generador** (`part2_evaluation.py`) llama al modelo
para redactar los borradores por departamento (`source=llm` en la traza) y
**fallback deterministico** si la red/modelo no responde. La integración está
en `rfp_pipeline/llm.py` (cliente OpenAI-compatible con **solo stdlib**: `urllib`).

El servidor, `run_rfp_e2e.py` y `docker-compose.yml` leen estas variables.
En Docker, `docker-compose.yml` usa `env_file: .env`, así que el contenedor
activa el LLM automáticamente si las claves están presentes.

---

## Cargar un nuevo RFP (¿cómo se sube?)

Hay **cuatro** formas según el contexto:

1. **Dashboard (subida por navegador).** En el dashboard `POST /api/upload`
   con un campo `file` (o arrastra el archivo). El servidor guarda el RFP en
   `data/raw/` y lo procesa en segundo plano (no bloquea la UI).
   `curl -F "file=@data/raw/mi-rfp.md" http://localhost:8000/api/upload`
2. **CLI con ruta.** `uv run rfp-e2e <ruta/al/archivo.md>`
3. **Seed built-in.** Añade la entrada a `SEEDS` en `run_rfp_e2e.py` (clave
   `valid`/`informal`/`invalid`) — estos son los seeds del demo y de los tests.
4. **Docker.** Suelta el archivo en `./data/raw/` local (volumen bind-mounted
   `./data:/app/data:rw`) y el pipeline del contenedor lo verá.

## Control humano en el bucle (HITL)

El demo deja el seed **"informal"** en `waiting_for_approval` a propósito, y
cada RFP **subido por el dashboard** también — para que un humano apruebe.

- Endpoint: `POST /api/tickets/<ticket_id>/approve/<department>`
  con body `{"decision": "approve|reject|request_changes", "comment": "..."}`.
- Hasta que **todos** los departamentos estén `approved`, el ticket permanece
  en `waiting_for_approval` (sin documento final). Con todos aprobados → `done`
  y se genera el documento final.
- `request_changes` / `reject` bloquean la finalización (pedagogía: el rechazo
  requiere re-evaluación humana/arbitraje).

Nuevos endpoints REST de tickets:

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/tickets` | GET | Lista resumen de tickets |
| `/api/tickets/<id>` | GET | Detalle (drafts, evaluaciones, aprobaciones) |
| `/api/upload` | POST | Sube un RFP (multipart `file`), procesa en bg |
| `/api/tickets/<id>/approve/<dept>` | POST | Decisión humana (HITL) |

---

## Docker (todo se levanta con docker)

Construimos con la imagen oficial de **uv** y `uv sync --frozen`
(reproducible 100% por `uv.lock`).

```bash
docker compose build
docker compose up -d          # http://localhost:8000
curl -s http://localhost:8000/api/log | head                     # datos del demo
curl -sN http://localhost:8000/events | head                     # SSE
docker compose logs -f observability                             # pipeline E2E en vivo
docker compose down
```

Al arrancar, el contenedor ejecuta el pipeline E2E (valid/informal/invalid) y
publica sus eventos en el hub; los ficheros de tickets y documentos finales
quedan en el volumen `./data` (mismo layout que el monorepo).

> Nota: `data/` está en `.gitignore` (datos generados); el layout se mantiene
> con `.gitkeep` en `data/pipelines/*/`.

---

## Cómo funciona el pipeline (resumen para el aula)

1. **Part 1 — Orchestrate** (`part1_intake.py`)
   Convierte el PDF→MD, extrae metadatos + legibilidad (Flesch-Kincaid
   determinístico), el **clasificador** decide `is_rfp` (si no → `discarded`),
   el **orquestador** reparte `work_items` en paralelo, los **workers** extraen
   `key_aspects` por departamento y el **synthesizer** genera el `handoff`
   (`{routing_table, summary}`) → `intake_complete`.

2. **Part 2 — Evaluate** (`part2_evaluation.py`)
   Por departamento presente, un **generador** produce un borrador y un
   **evaluador** lo puntúa: *readability* (FRE≥50), *relevance*
   (`missing_aspects`, si el departamento no aparece → `present=False`),
   *compliance* (reglas G1–G4). Si algo falla se itera con feedback
   (máx. 3 iteraciones); si se agotan iteraciones o no hay departamentos
   → `needs_human_review`.

3. **Part 3 — Produce** (`part3_approval.py`)
   Abre registros de aprobación por departamento (`waiting_for_approval`),
   identifica **triggers de arbitraje** (p. ej. TTC vs training window →
   `Marcos (CEO)`), y si todo es `approved` el **finalizador** sintetiza el
   documento final (moneda EUR si HQ en España, si no USD) → `done`.
   El punto de interrupción `resume_approval(ticket, dept, decision, comment)`
   demuestra el checkpointer.

4. **Observability** (`observability.py` + `services/`)
   Cada fase emite `TaskRecord` al **hub** (agent/flow/task con cadena
   `trigger → task → derived → prev/next`); el hub mantiene el log y difunde
   SSE `agent_step`/`agent_status_changed` a los suscriptores. El servidor
   expone eso como REST + stream (ver arriba).

### Handoff entre fases (contracto)

- Parte 1 → 2: `ticket.classifier["handoff"]` = `{routing_table:[{department, key_aspects, contact_hint, present}], summary}`.
- Parte 2 → 3: el `Ticket` persiste `drafts`/`evaluations` por departamento.
- Parte 3 → 4: cada mutación está en `ticket.trace` y se refleja en el hub SSE.

---

## Tests

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'   # 29 tests, ~0.05s
```

- `tests/test_part1_intake.py` — 6 tests (intake/discarded/workers/orchestrator/clasificador).
- `tests/test_part2_evaluation.py` — 4 tests (generadores, forma del `EvaluationResult`, compliance G4, bucle completo).
- `tests/test_part3_approval.py` — 6 tests (interrupción, aprobación parcial, resume, finalización, traza, arbitraje).
- `tests/test_observability.py` — 6 tests (SSE shape, agentes, flows, traza, paginación).
- `tests/pipelines/test_pipeline_contract.py` — 6 tests (directorios, handoff, store round-trip, checkpoint).

---

## Estructura de datos (`data/`)

```
data/
  raw/         seeds escritos por run_rfp_e2e.py (valid/informal/invalid)
  state/       un JSON por ticket (checkpointer durable)
  documents/   markdown convertido + documento final
  pipelines/   directorios-eco de los 4 proyectos del temario (layout monorepo)
```

---

## Notas y decisiones de diseño

- **Cero dependencias runtime**: `json/dataclasses/enum/threading/unittest/http.server` — la demo y los tests corren en cualquier Python 3.12 sin `pip install`. `uv` solo gestiona el entorno (paquete editable + `uv.lock`).
- **Dominio neutro**: los seeds usan *Riverside Community Association / Harbor Youth Club* (grants) para que el ejemplo sea válido en clase sin revelar las respuestas del BRIEFING de Nexova.
- **Determinista**: clasificador, legibilidad, generador/evaluador y arbitraje son stubs deterministas (sin LLM) → el bucle de 3 partes converge y es reproducible E2E.
- **Migración al proyecto real**: swap `Store` por Postgres/SQLModel (el BRIEFING prohíbe TinyDB/JSON como fuente de verdad *en el proyecto final*; aquí es un aula) y el hub in-memory por una tabla de eventos + endpoint SSE en el backend del curso.

---

*Branch `agentic-workflow` · build: Python 3.12 + uv + Docker.*
