# Argus SOC backend API (Workstream C)

FastAPI service the analyst UI calls. It runs on top of the main `argus-soc` package in this
repo and reaches the graph only through the graph tools library (`from argus_soc import graph`),
so there is no Cypher here (rule 1). Analyst feedback goes through A's
`learning_service.on_feedback`, the same steps as `tests/e2e/conftest.py: give_feedback`.

## Layout

```
backend/
├── pyproject.toml            # package argus-soc-backend, entry point argus-backend
├── Dockerfile                # build from the repo root
├── .env.example              # backend-only settings (add them to the root .env)
├── src/argus_backend/
│   ├── api_server.py         # app factory, CORS, error mapping, main()
│   ├── api_settings.py       # ARGUS_DEMO_USERS, ARGUS_SESSION_SECRET, ARGUS_SESSION_HOURS
│   ├── api_models.py         # the UI contract: LLD §7 + CONTRACT_GAPS GAP-1…6 + dashboard
│   ├── session_tokens.py     # HMAC-signed stateless tokens
│   ├── access_guard.py       # 401 / 403 / 404 for every /api/{tenant}/… route
│   ├── auth_routes.py        # login, me, logout, tenants
│   ├── case_routes.py        # case list, case detail, feedback
│   ├── playbook_routes.py
│   ├── activity_routes.py
│   ├── dashboard_routes.py
│   ├── health_routes.py
│   ├── case_mapper.py        # graph dicts -> API models
│   ├── feedback_service.py   # feedback flow (409 rules, close, learning)
│   └── dashboard_service.py  # dashboard numbers from list_cases / list_playbooks / list_activity
└── tests/                    # run on B's in-memory stub graph, no database needed
```

## Endpoints

| Method + path | Auth | Returns |
|---|---|---|
| `GET /api/health` | open | `{status: ok \| degraded \| mock, falkordb}` |
| `POST /api/auth/login` | open | `SessionOut {token, username, display_name, tenants, expires_at}` |
| `GET /api/auth/me` | token | `MeOut` |
| `POST /api/auth/logout` | token | 204 |
| `GET /api/tenants` | token | the caller's tenants |
| `GET /api/{tenant}/cases?status=&limit=` | token + tenant | `list[CaseSummary]`, newest first |
| `GET /api/{tenant}/cases/{id}` | token + tenant | `CaseDetail` |
| `POST /api/{tenant}/cases/{id}/feedback` | token + tenant | `FeedbackOut` |
| `GET /api/{tenant}/playbooks` | token + tenant | `list[PlaybookOut]`, newest first |
| `GET /api/{tenant}/activity?since=` | token + tenant | `list[ActivityItem]`, oldest first |
| `GET /api/{tenant}/dashboard?window=30m\|1h\|24h\|all` | token + tenant | `DashboardOut` |

Send `Authorization: Bearer <token>`. Errors: 401 no or bad token, 403 tenant not allowed,
404 unknown tenant or case, 409 verdict not allowed in the case's state, 422 validation,
503 FalkorDB unreachable. Interactive docs: `/api/docs`.

The feedback `analyst` is always the signed-in user; any `analyst` in the request body is
ignored. Approve and reject need a case awaiting approval; benign is also allowed on a closed
or auto-closed case.

## Settings

Shared settings come from `argus_soc.core.settings` (root `.env`): `ARGUS_TENANTS`,
`ARGUS_GRAPH_BACKEND`, `FALKORDB_HOST/PORT`, `API_PORT` (8080), `API_CORS_ORIGINS`.
Backend-only settings are in [`.env.example`](.env.example). Both are read from `.env` in the
working directory, so run the backend from the repo root. A bad value stops startup.

`ARGUS_GRAPH_BACKEND=stub` runs on B's in-memory sample data (scenario 1, writes included);
`/api/health` then reports `"mock"`.

## Run

Python 3.11+, from the repo root:

```bash
pip install -e .                    # argus-soc: graph library, agents, settings
pip install -e "backend[dev]"
argus-backend                       # or: uvicorn argus_backend.api_server:create_app --factory --reload --port 8080
```

Docker (no local Python needed):

```bash
docker build -f backend/Dockerfile -t argus-backend .
docker run --rm -p 8080:8080 --env-file .env argus-backend
```

## Test

```bash
cd backend
pytest
ruff check . && ruff format --check .
```
