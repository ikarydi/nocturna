# Nocturna release desk

A local, approval-first production desk for a dark instrumental music label. It runs on
CPU: the API, LangGraph workflow, database, dashboard and ffmpeg audio tools. It downloads no
model weights and never publishes anywhere. Every release stops at a human decision.

- **Stage 1:** release queue, workflow, approve/reject with history.
- **Stage 2:** lane templates, provenance for every file, audio QC, lossless master and
  loudness-normalized delivery export, metadata, a release checklist that gates approval,
  reviewer comments, and a downloadable delivery package.

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

## Release flow (Stage 2)

1. Optional: add a **lane template** (shared tags, BPM range, default key).
2. Create a concept and **Run workflow**. The prompt is built and the release enters review.
3. **Upload a take** (audio made elsewhere, with model/license/seed if you have them) or let
   the generator produce one. Every file gets a SHA-256, measurements and a provenance record.
4. **Export master + delivery**: 24-bit FLAC master at the source rate, plus a two-pass
   EBU R128 normalized 48 kHz / 24-bit WAV (default -14 LUFS, -1 dBTP; see `.env.example`).
5. Upload **artwork**, fill in **metadata**, and tick the **release checklist**.
6. **Approve.** This is refused until a master and delivery exist and every checklist item is
   ticked. Approved releases are frozen; reopen to change them.
7. **Download package**: master, delivery, artwork, `provenance.json`, `metadata.json` and an
   upload checklist that includes YouTube's AI disclosure step.

Set your name in the "Reviewer" box; it is recorded on every action in the history.

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
| GET | `/api/releases/{id}/audio` | stream the best available audio (delivery > master > take) |
| POST | `/api/releases/{id}/assets` | multipart upload: `file`, `kind` (take, artwork), provenance fields |
| POST | `/api/releases/{id}/export` | make master FLAC + delivery WAV from the latest take |
| PUT | `/api/releases/{id}/checklist` | `{"items": {"rights": true}, "actor": "J"}` |
| POST | `/api/releases/{id}/comments` | reviewer note without a status change |
| GET | `/api/releases/{id}/provenance` | full provenance record (JSON) |
| GET | `/api/releases/{id}/package` | zip delivery package (approved only) |
| GET/POST/PATCH | `/api/templates` | lane templates |
| GET | `/api/checklist` | checklist items and labels |
| GET | `/api/assets/{id}/file` | download one file |

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

See `.env.example`. Key settings: `DATABASE_URL`, `AUDIO_DIR` (all media lives here),
`AUTO_MIGRATE` (default true), `ACE_STEP_ENABLED` (default false), `ACE_STEP_URL`,
`DELIVERY_LUFS` (-14), `DELIVERY_TRUE_PEAK_DBTP` (-1), `MAX_UPLOAD_MB` (1024).

The adapter should also return `model`, `model_revision` and `license`; the desk flags any
generated take that arrives without them.

Migrations: `alembic upgrade head` / `alembic revision --autogenerate -m "..."`.

## Tests

```bash
pytest
```

49 tests cover prompt constraints and templates, every transition and the approval gate,
persistence across restart, generator parsing and errors, provenance on generated and
uploaded files, ffmpeg loudness parsing, real master/delivery exports (delivery lands within
0.5 LU of target), artwork checks, and the contents of the delivery package. ffmpeg tests
skip automatically if ffmpeg is missing.
