# Nocturna release desk

A local, approval-first production desk for a dark instrumental music label. Stage 1 is
CPU-only: it runs the API, LangGraph workflow, database and dashboard, downloads no model
weights, and never publishes anywhere. Every release stops at a human decision.

## Quick start (WSL2 Ubuntu)

```bash
bash scripts/setup-wsl.sh        # apt: python3-venv, ffmpeg; pip install; migrate; pytest
source .venv/bin/activate
uvicorn nocturna.api:app --reload
```

Open http://localhost:8000 in your Windows browser. WSL2 forwards localhost automatically.

### With PostgreSQL (Docker Compose)

```bash
docker compose up --build
```

This starts Postgres 17 and the API on http://localhost:8000 (bound to 127.0.0.1 only).
The API applies Alembic migrations on startup, so there is no separate `init.sql`.
Install Docker Desktop with the WSL2 backend, or Docker Engine inside Ubuntu.

To run the venv app against that Postgres instead of SQLite, set in `.env`:

```
DATABASE_URL=postgresql+psycopg://nocturna:nocturna@localhost:5432/nocturna
```

and expose the db port (add `ports: ["127.0.0.1:5432:5432"]` to the `db` service).

## How it works

```
draft ──run──► review ──approve──► approved
  ▲              │
  │              └──reject (note required)──► rejected
  └────────reopen──────────────────────────────┘   (also from failed / approved)

with ACE_STEP_ENABLED=true:  draft ──► generating ──► review | failed
```

- `nocturna/workflow.py`: LangGraph graph `prepare_prompt → [generate] → human_review`. The
  graph is pure; the API applies its result through the state machine, so no node can approve.
- `nocturna/prompting.py`: builds an instrumental-only prompt. It strips phrases asking for
  vocals and phrases that imitate an artist ("in the style of…", "sounds like…") and
  records a warning for each.
- `nocturna/transitions.py`: the only place statuses change. Every change writes a
  `release_events` row, so decision history is kept from day one.
- `nocturna/generator.py`: the client for the normalized generation adapter (below).
- `nocturna/static/`: the dashboard (no build step).

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB dialect, version, generator status |
| GET | `/api/releases?status=review` | list, optional filter |
| POST | `/api/releases` | create a draft |
| GET / PATCH | `/api/releases/{id}` | detail with history / edit (draft, rejected, failed only) |
| POST | `/api/releases/{id}/run` | run the workflow (draft only) |
| POST | `/api/releases/{id}/decision` | `{"action": "approve" \| "reject" \| "reopen", "note": "..."}` |
| GET | `/api/releases/{id}/audio` | stream audio, only from inside `AUDIO_DIR` |

Interactive docs at http://localhost:8000/docs.

### Generation adapter contract (Stage 3)

Nocturna does not call ACE-Step directly. Deploy a small adapter next to the GPU that offers:

```
GET  /health    -> {"status": "ok", "model": "...", "model_revision": "..."}
POST /generate  {"prompt": str, "duration_s": int, "seed": int|null}
                -> {"audio_path": "relative/to/AUDIO_DIR.wav"} or {"audio_url": "http://..."}
                   plus optional seed, model, model_revision, license
```

ACE-Step 1.5's own REST server (`acestep-api`, port 8001) is asynchronous (submit, then
poll), so the adapter's job is to submit, wait, write the file into the shared audio
folder, and return its path. Set `ACE_STEP_ENABLED=true` only after `/health` returns ok.

## Configuration

See `.env.example`. Key settings: `DATABASE_URL`, `AUDIO_DIR`, `AUTO_MIGRATE` (default
true), `ACE_STEP_ENABLED` (default false), `ACE_STEP_URL`.

Migrations: `alembic upgrade head` / `alembic revision --autogenerate -m "..."`.

## Tests

```bash
pytest
```

35 tests cover prompt constraints, every transition (including invalid ones and "reject
needs a note"), persistence across restart, generator response parsing and HTTP errors,
the enabled-generation path with a fake generator, and refusal to serve audio outside
`AUDIO_DIR`.
