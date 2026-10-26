# Mexico Lindo: authenticated travel agent

TanStack Start (React/TypeScript) frontend, FastAPI backend, the existing LangGraph
planner, a FastMCP server protected with MCPAuth, and Redis. Python dependencies
are locked with uv; frontend dependencies use npm's lockfile.

## Run everything

Requirements: Docker with Compose v2 and a reachable OpenAI-compatible LLM API.
Configure these variables in your local, ignored `.env` file or export them:

```dotenv
LLM_API_URL='https://your-provider.example/v1'
LLM_MODEL='your-model'
LLM_API_KEY='your-private-key'
APP_ORIGIN='http://localhost:3000'
```

Single quotes preserve literal `$` characters in Compose's dotenv parser.
Never commit real credentials. Then run:

```sh
./scripts/up.sh
```

This builds and starts **five services in the background**, waits for health
checks, and runs an HTTP/MCP smoke check. Open <http://localhost:3000>.
Only the frontend is published, bound to loopback. Backend, agent, MCP and Redis
are accessible on the Docker network, not on host ports.
There is no need to forward ports 8000 or 8002. In Codespaces, the script detects
the HTTPS origin for port 3000 automatically and prints it when ready. To use a
different origin, export `APP_ORIGIN` before running the script; in Codespaces,
this detection takes precedence over `.env`. Mutations from other origins are rejected.
Only in development with `CODESPACES=true`, `http://localhost:3000` and
`https://localhost:3000` are also accepted because the Codespaces proxy rewrites
the Origin header to those variants.
CSRF token validation remains mandatory.

**Development demo:** `test@test.com` / `test1234$`.
The startup script supplies this known development password; set the
`DEMO_USER_PASSWORD` shell environment variable before startup to override it.
The account is seeded idempotently and only an Argon2id hash is stored in TinyDB.
Existing accounts/passwords are never reset on restart. The included Compose
file is explicitly a **local development** deployment, not a production template.

```sh
docker compose ps
docker compose logs --tail=50 backend agent mcp
docker compose down
```

Normal shutdown keeps data. Do not use `down -v` unless you intend to erase all
users, signing keys, preferences and saved plans.

## Capabilities and architecture

```text
browser -> TanStack Start /api proxy -> FastAPI -> LangGraph agent -> FastMCP
                                         |             |              |
                                       TinyDB        Redis       Open-Meteo
```

- Guests can only plan trips within Mexico. Their agent has no MCP tools.
- Logged-in users can query weather and save/list/delete **their own** trip plans.
- Weather queries and writes require an explicit, one-use confirmation in the
  agent interface. Rejection or timeout causes no action. Logging in is not consent.
- Plans are proposals, not reservations; no purchases, bookings or availability
  guarantees. Public registration and password recovery are out of scope.
- The planner retains its evaluator/optimizer, up to 15 evaluations and a
  1,500-character itinerary limit. Progress is shown while the job is running.

TinyDB in the private `backend-data` volume stores users. Only one backend
process writes it; do not increase its worker count. Redis AOF stores preferences
and saved plans plus expiring sessions, histories, jobs and confirmations.
Guests do not receive persistent personal memory. Conversations are isolated
by session and conversation ID; login does not merge histories.
The web page starts a new conversation after reload; saved plans remain available.

### Application authentication vs MCP authorization

The backend issues RS256 JWTs and stores the application JWT in an HttpOnly,
SameSite=Strict cookie (`Secure` outside development). CSRF tokens and exact
Origin checks protect mutations. No JWT is stored in localStorage.

Application (`aud=backend`), internal agent (`aud=agent`) and delegated MCP
(`aud=mcp`, tool-specific scopes) tokens are different credentials. The MCP
token never reaches browser JavaScript or the LLM. Redis session revocation is
checked by each service and again before executing confirmed tools.

MCPAuth 0.1.1's `create_bearer_auth` middleware is used with a strict RS256/JWKS
verifier, not its OAuth-provider discovery constructor: that constructor requires
a full authorization-code/PKCE provider. This internal integration deliberately
does **not** advertise fictitious OAuth endpoints or claim OAuth 2.1 interoperability.
Per-tool scopes and ownership checks use MCPAuth's verified context.
MCP's handshake transport is stateful to support elicitation; every MCP session
is bound to the authenticated application session to prevent identity switching.

The private signing key is generated only on first development startup, with
mode 0600 in the backend volume. Other containers receive public keys over JWKS,
not the private key. LLM credentials are passed only to the agent.
Outside development, demo seeding is rejected, HTTPS is required and a signing
key must be provisioned explicitly. Public production hosting and external MCP
clients need a separate OAuth/OIDC/TLS deployment design.

Limits: 1-hour sessions/history, 10-minute jobs, 90-second confirmations,
4 concurrent agent jobs, rate-limited login/chat/tool calls and 50 saved plans
per user. Interrupted jobs are not replayed automatically; retry explicitly.

## Verification and CLI

Startup smoke checks do not call paid LLM or weather APIs:

```sh
docker compose exec -T backend python /app/scripts/smoke.py
docker compose exec -T backend python /app/scripts/smoke.py --extended
```

The extended smoke temporarily creates and deletes a plan and checks consent,
isolation, scopes, JWT claims and MCP session binding. It uses the configured
development account. These are operational checks, not a new test suite.
To check the LLM separately, submit a Mexico itinerary in the chat. Health checks
verify configuration/processes, not external LLM availability or quota.
Frontend build/type check: `cd frontend && npm ci && npm run build`.

The original CLI remains available with `uv run python main.py` (planning-only
unless given a valid delegated `MCP_ACCESS_TOKEN`). Prefer the web-session CLI:

```sh
uv run python main.py --web
uv run python main.py --web --login
```

It prompts for credentials and consent without exporting tokens, and logs out
when it closes. The old Flask template `server.py` is not part of this deployment.

## Original Python template

The most basic boilerplate to start a Python project at 4Geeks is to start your very first Python project from scratch.

## What to do next?

Open the `main.py` file and start writing your code.

Execute your code by typing the following command on your terminal:

```bash
$ python main.py
```

You can create and include as many python files (a.k.a. modules) as you want using the import statements.

## Requirements

Make sure you have Python installed in your computer. We strongly recommend [installing Python through Pyenv ](https://4geeks.com/how-to/what-is-pyenv-and-how-to-install-pyenv) to avoid version conflicts in the future.

### Contributors

This template was built as part of the [4Geeks Python Resources](https://4geeks.com/technology/python) for learning at [4Geeks.com](https://4geeks.com) by [Alejandro Sanchez](https://twitter.com/alesanchezr) and [many other contributors](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
