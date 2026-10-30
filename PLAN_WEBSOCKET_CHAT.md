# 🎯 Plan didáctico — Streaming de Chat por WebSocket (Parte 2 de 2)

> **Rama:** `feature/websocket-chat`
> **Base:** estado actual con streaming de tokens por **SSE** (rama `feat/langchain-streaming-bridge`, commit `2f82165`).
> **Lección:** *Sistemas en Tiempo Real: Streaming de Chat por WebSocket* — convierte ese chat SSE de una vía en un canal **bidireccional** (WebSocket) con streaming de tokens + interrupción/abort + reconexión.

---

## 0. ¿Por qué WebSocket y no lo que ya tienes (SSE)?

Antes de escribir código, entiende el **porqué**:

| | SSE (lo que tienes hoy) | WebSocket (lo que vas a construir) |
|---|---|---|
| Dirección | Servidor → cliente (una vía) | Bidireccional |
| Browsers | `EventSource` (no manda datos; se conecta con GET) | `WebSocket` API (manda y recibe) |
| Headers HTTP | Puede usar `Authorization` si haces proxy | Los navegadores **no** permiten `Authorization` en el handshake → token por **query string** o primer frame |
| Interrupción | El cliente no puede hablar mientras el servidor responde | El cliente envía `interrupt` en mitad del stream |

**El requisito que obliga a WebSocket** es la interrupción a mitad de respuesta:
el usuario manda `new_input` mientras el agente sigue generando → el servidor debe
leer del socket **mientras** escribe tokens. Eso es un canal bidireccional.

El frontend de hoy (`frontend/src/routes/index.tsx`) usa `EventSource` y el flujo
sigue siendo petición/respuesta con un `job_id` (patrón de la Parte 1). No lo
tires: vas a **reemplazar el transporte** (POST `/api/chat` + `EventSource`
→ WebSocket persistente) reutilizando TODO el pipeline del agente.

---

## 1. Mapa del código actual (antes de tocar nada)

```text
frontend/src/routes/index.tsx   →  EventSource /api/jobs/{id}/events  (recibe token+status)
frontend/src/api.ts             →  fetch wrapper (POST /chat, GET /jobs…)
frontend/src/routes/api/$.ts    →  proxy de backend 8000 (no entiende WS aún)
────────────────────────────────────────────────────────────────────
backend   src/…/api/app.py      →  /api/chat (202→job), /api/jobs/{id}/events (relay SSE)
agent     src/…/agent_service/app.py
             ├─ execute()       →  aísla el LLM en un hilo (ThreadPoolExecutor) con JobContext
             ├─ publish_token() →  escribe cada token en Redis Stream: events:{job_id}
             ├─ job_events()    →  SSE que lee el Stream y emite `token` / `status`
             └─ start()         →  crea job_id, lanza executor.submit(execute,…)
orchestrator src/…/orchestrator.py
             └─ Orchestrator._stream() → graph.stream(…, stream_mode=["messages","values"])
                                          llama self.on_token(chunk_id, text) por token
llm         src/…/llm.py        →  ChatBridge(BaseChatModel)._stream() emite tokens SSE del proveedor
```

**La producción de tokens ya está desacoplada** (Redis Stream). Tu trabajo es
añadir el **consumidor WebSocket** sin romper eso — ese es el patrón productor/consumidor que se evalúa.

---

## 2. Arquitectura objetivo

```text
browser (React)
   │  WebSocket  ws://…/chat?token=…&session_id=…        (una sola conexión persistente)
   ▼
backend /api/ws/chat  (FastAPI WebSocket)
   │  ├─ autentica el token JWT (query string) y exige session_id
   │  ├─ registra un consumidor = {socket, thread_id} en un "hub" por sesión
   │  └─ bucle: while WS abierto:
   │        │
   │        ├─ <─ recibe {type:"message", content}          (turno nuevo)
   │        ├─ <─ recibe {type:"interrupt"}                 (abort del stream en curso)
   │        │
   │        └─ >─ envía eventos tipados:
   │              {type:"token_chunk", message_id, text}
   │              {type:"generation_interrupted", message_id, partial}
   │              {type:"generation_completed"}
   │
   ▼
agent (interno)
   │  └─ /start, /interrupt  (HTTP interno con JWT de servicio, igual que hoy agent_request)
   ▼
LangGraph (thread_id = session_id)
   │  └─ Orchestrator._stream() → on_token() → hub publica al/los sockets de la sesión
```

**Clave didáctica:** el **agente no sabe que existe un WebSocket**. `execute()`
sigue siendo productor (lo que ya produce), y el hub de WebSocket es un **consumidor
más**. El interrupt es una señal que **cancela la tarea** del `ThreadPoolExecutor`
(no un `interrupt()` de LangGraph).

---

## 3. Contrato de eventos WebSocket (nombres ARMONIZADOS con el README)

> ⚠️ La lección insiste: los nombres deben coincidir con tu BRIEFING. Como este
> repo es el stack didáctico "Mexico Lindo", usamos una disciplina **análoga** a la
> del README (token_chunk / generation_interrupted / generation_completed).

**Cliente → Servidor:**
| type | payload | significado |
|---|---|---|
| `message` | `{ content }` | nuevo mensaje del usuario (si hay stream → aborta implícito? NO: primero manda interrupt) |
| `interrupt` | `{ message_id }` | aborta la generación en curso |
| `ack` | `{}`  | respuesta al primer frame de auth (opcional si usas query string) |

**Servidor → Cliente:**
| type | payload | significado |
|---|---|---|
| `ready` | `{ session_id, thread_id }` | conexión autenticada y ligada al hilo |
| `history` | `{ messages: [...] }` | rehidratación del hilo desde checkpoint |
| `token_chunk` | `{ message_id, text }` | un chunk de token (partial) |
| `generation_started` | `{ message_id }` | arranca una generación nueva |
| `generation_interrupted` | `{ message_id, partial }` | abort: no habrá más tokens de esta generación |
| `generation_completed` | `{ message_id }` | generación terminó sin interrupciones |
| `error` | `{ code, message }` | error legible |

---

## 4. Puesta en marcha (ramas / commits)

> Repite este patrón de **micro-commits con mensaje pedagógico**; cada paso deja la app funcionando (o falla de forma controlada).

| Paso | Resultado | Checkpoint (sí es estable, marca la casilla en el README) |
|---|---|---|
| 1. Rama base | `feature/websocket-chat` lista | — |
| 2. Hub en memoria + endpoint WT | un cliente se conecta y recibe `ready` | ✅ |
| 3. Auth JWT del WebSocket | rechaza sin token / sesión | ✅ |
| 4. Bridge productor→hub | tokens llegan por WS | ✅ (parcial) |
| 5. Interrumpir (abort de tarea) | `generation_interrupted` y no más tokens | ✅ |
| 6. Marcar partial + turno nuevo | historial `interrupted` conservado | ✅ |
| 7. Reconexión + rehidratación | mismo thread, historial restaurado | ✅ |
| 8. Frontend | chat WS con escritura en vivo y botón detener | ✅ |
| 9. Tests y documentación | contrato + verificación manual | ✅ |

---

## 5. Guía paso a paso (con archivos reales)

### Paso 1 — Rama base
```sh
git checkout -b feature/websocket-chat     # (ya está hecha en este repo)
```

### Paso 2 — Hub de WebSocket (backend) + endpoint
**Nuevo archivo:** `services/` no existe como carpeta de código en este repo
(el servicio vive en `src/dsmora_python_hello_2/api` + `agent_service`). Respeta
el layout existente: crea el hub junto al backend.

**Nuevo:** `src/dsmora_python_hello_2/api/ws_hub.py`
```python
"""Hub de WebSocket: mapa session_id -> {set de websockets}.
Producción y consumo quedan desacoplados: los productores publican, el hub fan-out.
PATRÓN productor/consumidor (lo que se evalúa)."""
import asyncio
from collections import defaultdict
from typing import Any

class ChatHub:
    def __init__(self) -> None:
        self._sessions: dict[str, set[Any]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str, websocket: Any) -> None:
        async with self._lock:
            self._sessions[session_id].add(websocket)

    async def unsubscribe(self, session_id: str, websocket: Any) -> None:
        async with self._lock:
            self._sessions[session_id].discard(websocket)
            if not self._sessions[session_id]:
                self._sessions.pop(session_id, None)

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        """Fan-out: TODOS los clientes suscritos a la sesión reciben el mismo evento.
        (respuesta a la pregunta de diseño: sin duplicar llamadas al agente)."""
        async with self._lock:
            sockets = list(self._sessions.get(session_id, ()))
        for socket in sockets:
            await socket.send_json(event)

# Singleton a nivel de app (se registra en el lifespan)
hub = ChatHub()
```

**En `api/app.py`** — nuevo endpoint:
```python
from fastapi import WebSocket, WebSocketDisconnect
from .ws_hub import hub

@app.websocket("/api/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    # Paso 3 (abajo): autenticar aquí ANTES de aceptar eventos de chat.
    session_id = websocket.query_params.get("session_id")
    if not session_id:
        await websocket.send_json({"type": "error", "code": "MISSING_SESSION", "message": "Falta session_id."})
        await websocket.close(code=4400)
        return
    await hub.subscribe(session_id, websocket)
    try:
        await websocket.send_json({"type": "ready", "session_id": session_id, "thread_id": session_id})
        while True:
            frame = await websocket.receive_json()
            if frame.get("type") == "message":
                # lanzar tarea del agente (compilar y enviar: ver siguiente paso)
                pass
            elif frame.get("type") == "interrupt":
                # abort del stream (ver Paso 5)
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(session_id, websocket)
```

### Paso 3 — Proteger el socket con el MISMO JWT (query string)
Los navegadores no permiten `Authorization` en el handshake WebSocket. Tú ya tienes
toda la maquinaria JWT en `src/dsmora_python_hello_2/security.py` (`verify(token, "backend")`,
`active_session(sid)`). Úsala igual que `api/app.py:identity()`:

```python
from ..security import verify  # ya existe
import jwt as pyjwt

async def _authorize(websocket: WebSocket) -> tuple[str, dict]:
    token = websocket.query_params.get("token", "")
    session_id = websocket.query_params.get("session_id", "")
    if not token:
        raise RuntimeError("Missing token")
    try:
        claims = verify(token, "backend")          # MISMO issuer/claves que el backoffice
    except pyjwt.PyJWTError:
        raise RuntimeError("Invalid token")
    if claims.get("sid") != session_id:            # el socket queda ligado a un hilo existente
        raise RuntimeError("session_id mismatch")
    return claims["sid"], active_session(claims["sid"])
```

Rechaza con `websocket.close(code=4401)` **antes** de cualquier evento de chat.

### Paso 4 — Bridge productor → hub (tokens por WS)
Ya tienes el productor. Ahora conecta el **consumidor**:

1. En `agent_service/app.py`, `execute()` ya llama `on_token=lambda …: publish_token(...)`.
   Mantén esa publicación en Redis (¡productor!). Añade además fan-out al hub:
   ```python
   async def handle_message(session_id: str, websocket: Any, content: str) -> None:
       # 1. pedir al agent que arranque la generación (HTTP interno, como hoy job/chat)
       # 2. el agente publica token por token
       # 3. un worker de eventos lee Redis Stream (events:{job_id}) y lo reenvía:
       while True:
           entries, _ = redis.xread({f"events:{job_id}": last_id}, block=1000)
           for eid, fields in entries:
               await ws.send_json({"type": "token_chunk", "message_id": fields["id"], "text": fields["text"]})
   ```
2. Alternativa aún más limpia y sin Redis en medio: pasa al hub el `on_token`:
   ```python
   on_token=lambda mid, text: hub.publish(session_id, {"type":"token_chunk","message_id":mid,"text":text})
   ```
   (ágil para clase; Redis Stream se conserva como productor durable para el resto.)

### Paso 5 — Interrumpir = abortar la tarea (NO interrupt() de LangGraph)
El README es taxativo: **no uses LangGraph `interrupt()` HITL como sustituto del abort**.

Planteamiento con tu `ThreadPoolExecutor` + `JobContext`:
- Añade un `threading.Event` de cancelación en `JobContext` (o un `Future` por ende).
- `execute()` (y `CheckedModel.generate` / `Orchestrator._stream`) comprueban
  `context.cancelled.is_set()` en cada vuelta del bucle de tokens y **cortan**.
- El handler `interrupt` del WS:
  ```python
  async def on_interrupt(job_id: str, session_id: str, message_id: str) -> None:
      cancel(job_id)                       # marca el Event → execute() deja de generar
      partial = read_partial(session_id)   # tokens ya emitidos del mensaje X
      await hub.publish(session_id, {"type":"generation_interrupted",
                                     "message_id": message_id, "partial": partial})
  ```
- `execute()` marca el mensaje parcial como `interrupted` y **conserva** los tokens
  ya mostrados (no borra ni sobrescribe el mensaje).
- El siguiente `message` del usuario arranca un **turno nuevo** con su `new_input`.

**Diseño (respuesta a la pregunta 3):** abort = cancelación de la tarea del LLM
(corta el stream físico). `interrupt()` = pausa de grafo para HITL durable (la que
ya usas en `approval_gate`). Son cosas distintas y esta parte NO necesita la segunda.

### Paso 6 — Marcar partial `interrupted` + turno nuevo
- Persistencia: `orchestrator.history` + historial Redis (`history:{sid}:{conversation_id}`).
- Cuando se aborte: guarda el mensaje con `content = partial` (lo que ya llegó) y
  una marca `interrupted: True` en el historial que el frontend renderiza como tal.
- El turno nuevo se guarda después, sin tocar el mensaje interrumpido.

### Paso 7 — Reconexión con backoff y rehidratación
Frontend (`frontend/src/routes/index.tsx` → nuevo hook `useChatSocket`):
```ts
function connect(sessionId: string, token: string) {
  const ws = new WebSocket(`ws://${location.host}/api/ws/chat?token=${encodeURIComponent(token)}&session_id=${sessionId}`)
  // backoff progresivo: 1s, 2s, 4s, 8s… al onclose, reintentar con el mismo session_id
}
```
Al conectar: el servidor responde `ready` + `{type:"history", messages}` rehidratado
desde checkpointer / historial — **no un chat vacío**. Recién después acepta tokens.

> Nota proxy: `frontend/src/routes/api/$.ts` solo proxya HTTP. Añade un proxy WS en
> TanStack Start (nitro) o apunta el navegador directo al backend en dev — documenta
> la decisión en el PR.

### Paso 8 — Frontend: escritura en vivo + botón detener
- Reemplaza el bloque `EventSource` por el socket (misma UI de `draft`).
- `token_chunk` → `setDraft(...)` igual que hoy.
- `generation_interrupted` → marca el mensaje con clase CSS `interrupted` y añade
  etiqueta "(interrumpido)"; conserva el texto.
- Añade botón **■ Detener** (o enviar texto estando ocupado ⇒ manda `interrupt`).
- `generation_completed` → vuelca el draft como mensaje final y habilita el input.

### Paso 9 — Pruebas (tests/)
Crea `tests/test_ws_chat.py` (pytest + `fastapi.testclient.TestClient(websocket=...)`):
1. **Contrato de eventos:** conecta, envía `message`, espera `token_chunk` (mocks de
   LLM que devuelvan tokens), `generation_completed`. Envía `interrupt` y espera
   `generation_interrupted` con el partial, y **cero** `token_chunk` posteriores de esa generación.
2. **Sin token / session inválida → close 4401**.
3. **Reconexión:** cierra y reconecta con el mismo `session_id` → `history` restaurado,
   siguiente token pertenece al nuevo turno y refleja el `new_input`.

Run: `uv run pytest tests/test_ws_chat.py -q` (o tu equivalente de Docker).

---

## 6. Preguntas de Diseño (para la descripción del PR)

1. **¿Por qué WebSocket y no el SSE de la Parte 1?**
   El interrupt debe viajar del cliente al servidor **mientras** el servidor emite
   tokens. SSE es una vía única (el cliente no habla de vuelta). WebSocket es el único
   canal nativo bidireccional que da `onmessage` simultáneo al flujo saliente.

2. **¿Varios clientes en la misma sesión (supervisor)?**
   Todos se suscriben a la misma `session_id` en el `ChatHub`; el agente se invoca
   **una sola vez** y el hub hace fan-out del mismo stream de eventos a todos los
   sockets (patrón productor/consumidor; productor único, consumidores múltiples).

3. **¿Abort del stream vs LangGraph `interrupt()`?**
   El abort **cancela la tarea** del LLM (Event de cancelación en `JobContext` que
   corta el `on_token`). `interrupt()` HITL ya lo usas para la aprobación durable de
   planes (otra parte). Aquí NO se usa `interrupt()`: el mensaje parcial se marca
   `interrupted` y el siguiente mensaje es un turno nuevo.

---

## 7. Checkboxes de la lección → entregables

| Requisito de la lección | Dónde se resuelve |
|---|---|
| Endpoint WS con conexión persistente por sesión | Paso 2 (`/api/ws/chat` + `ChatHub`) |
| Mismo JWT que backoffice (query string), rechazar sin auth | Paso 3 (`security.verify` + close 4401) |
| `session_id`/`thread_id` en handshake/URL | Paso 2 y 3 |
| Tokens por stream_mode de LangGraph | ya está (Paso 4, `Orchestrator._stream`) |
| Interrupción aborta de verdad el stream | Paso 5 (cancelar tarea, no `interrupt()`) |
| Marcar partial `interrupted`, nuevo turno | Paso 6 |
| Productor/consumidor desacoplado (pub/sub) | Paso 4 (`ChatHub` + Redis Stream) |
| Frontend por WS con escritura en vivo | Paso 8 |
| Control de interrupción + mensaje interrumpido visible | Paso 8 |
| Reconexión con backoff + rehidratación del hilo | Paso 7 |
| Tests del contrato | Paso 9 |

---

## 8. Convenciones de este repo (respétalas)

- Nombres/errores en **español sin acentos** (ver `api/app.py`, `agent_service/app.py`).
- Nunca mezcléis los payloads de notificación RFP de la Parte 1 con este contrato WS.
- El agente NO se toca en su lógica interna: solo se añade el transporte bidireccional.
- No crear una app paralela: extender la ruta/endpoint existente que hoy invoca al agente.
- PR aprobado → **merge a `main`** (la lección lo exige para no partir de código desactualizado).