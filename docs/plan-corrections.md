# PLAN.md corrections and research notes (checked 2026-11-06)

## Corrections applied in the Stage 1 build

1. **One schema source, not two.** The plan initialises Postgres from `db/init.sql` *and*
   ships Alembic migrations. Those drift apart. The build drops `init.sql`; the API runs
   `alembic upgrade head` on startup (`AUTO_MIGRATE=true`) for both SQLite and Postgres.
2. **Decision history moved into Stage 1.** Every status change writes a `release_events`
   row (who/what/when/note). It was cheap now and painful to backfill later (plan Stage 2.5).
3. **Rejections require a note**, so the history explains every "no".
4. **Postgres port is not published by default** and the API binds to 127.0.0.1, so
   nothing is reachable from your LAN.

## ACE-Step (Stage 3) — the plan is more pessimistic than it needs to be

- **ACE-Step 1.5** is the current line. Code is MIT, weights are MIT on Hugging Face, and the
  model card says generated music can be used commercially. Still record the exact checkpoint
  and revision per track, as the plan says.
  Sources: [GitHub](https://github.com/ace-step/ACE-Step-1.5),
  [model card](https://huggingface.co/ACE-Step/Ace-Step1.5).
- **VRAM:** the base/turbo models run in **under 4 GB VRAM** (2B turbo ≤6 GB with INT8 +
  CPU offload). The **XL (4B DiT, April 2026)** variants need ≥12 GB with offload, 20 GB
  recommended. So a 12–16 GB NVIDIA card covers everything except comfortable XL use, and
  fits well inside €1,000 *for the card alone*. The plan's advice to check PSU, case and
  motherboard first still holds.
- **CPU, AMD and Apple** are supported upstream (CPU, ROCm, MPS/MLX, Intel XPU). CPU will be
  slow, but you could run a short test generation before buying anything. Nothing in setup
  does this automatically.
- **Python 3.11–3.12 only** for ACE-Step, while Nocturna runs on 3.11+ (tested on 3.13).
  Keep ACE-Step in its own environment (`uv`), as the plan already suggests.
- ACE-Step ships its own REST server (`uv run acestep-api`, port 8001, async submit/poll)
  and a Gradio UI on 7860. The Nocturna adapter wraps that; the contract is in README.md.

## YouTube (Stage 4) — disclosure is required, not "where required"

- YouTube's altered/synthetic content rules list **"AI generated music"** among things
  creators **must disclose** when the music is the main focus of the video. Set "AI use"
  under Attributes in YouTube Studio on every upload. Disclosure itself does not reduce
  reach or monetization eligibility; not disclosing can get labels applied, content removed,
  or YPP suspension. YouTube may also auto-detect and label AI content.
  Source: [answer/14328491](https://support.google.com/youtube/answer/14328491).
- The YPP **"inauthentic content"** policy (renamed from "repetitious content" on
  2025-07-15) bars "AI-generated content made with generic or unoriginal templates giving the
  impression of mass production". Reviewers judge the whole channel, so one templated batch
  can demonetize everything. This strengthens the plan's "no repetitive mass uploads" point
  into a hard rule: vary artwork, titles, descriptions and track structure, and show
  curation. Source: [answer/1311392](https://support.google.com/youtube/answer/1311392).
- Suggested Stage 2 addition: an "AI disclosure set" checkbox in the release checklist.

## Versions used (PyPI, 2026-11-06)

FastAPI 0.162, LangGraph 1.2.20, SQLAlchemy 2.1.8, Alembic 1.20.1, Uvicorn 0.54,
Pydantic 2.14, psycopg 3.3.8, pytest 9.2. Postgres 17 in Compose.
