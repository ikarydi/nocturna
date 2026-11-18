# Music generation (Stage 3)

Generation is **off by default**. Turn it on in three steps: try the whole flow with a
fake generator, install ACE-Step, then run a short real test.

```
Nocturna (:8000) ──► adapter (:8002) ──► ACE-Step 1.5 API (:8001)
   ACE_STEP_URL        nocturna.adapter      uv run acestep-api
```

The **adapter** (`nocturna/adapter/`) converts Nocturna's simple `POST /generate` into
ACE-Step's asynchronous API (`/release_task` → `/query_result` → `/v1/audio`). It saves the
audio into Nocturna's `AUDIO_DIR/generated/` and reports the seed, model, ACE-Step commit and
license. Nocturna stores those on the take's provenance record.

What the adapter always sends to ACE-Step:

- `lyrics: "[Instrumental]"`: Nocturna releases are instrumental.
- `use_cot_caption: false`, `use_format: false`: ACE-Step's language model is **not**
  allowed to rewrite the prompt, so what was reviewed is what was generated.
- `batch_size: 1`, a fixed `seed`, and `audio_format: flac`.

## Step 1: try the flow with the fake generator (no download)

The fake server answers like ACE-Step but returns a synthetic drone made with ffmpeg. It
checks the plumbing only; it is **not** music generation.

```bash
# terminal 1
bash scripts/start-generation.sh --fake

# terminal 2
source .venv/bin/activate
ACE_STEP_ENABLED=true uvicorn nocturna.api:app --reload
```

The dashboard header should say `generation ok`. Create a concept and click **Run workflow**.
The release goes to review with a generated take whose provenance shows
`model: fake-acestep-drone`. Export, checklist and approval work as before.

## Step 2: install ACE-Step 1.5

```bash
bash scripts/setup-acestep.sh                  # code + Python env only
bash scripts/setup-acestep.sh --download-model # also fetch the default model
```

- Installs into `~/ACE-Step-1.5` (set `ACESTEP_DIR` to change), pinned to commit `ca1e85fe`
  (2026-08-29), the version the adapter was written against.
- Uses ACE-Step's own `uv` environment (Python 3.11–3.12), separate from Nocturna's.
- **Downloads:** `uv sync` pulls PyTorch (a few GB). The default model is several GB more and
  is fetched only with `--download-model` or on the first API start.
- **License:** code and weights are MIT, and the model card states generated music may be
  used commercially. Re-check https://huggingface.co/ACE-Step/Ace-Step1.5 before releasing.

## Step 3: run a real test

```bash
# terminal 1 (starts ACE-Step on :8001 and the adapter on :8002)
bash scripts/start-generation.sh

# terminal 2
ACE_STEP_ENABLED=true uvicorn nocturna.api:app --reload
```

Without an NVIDIA GPU the script runs ACE-Step on **CPU with its language model off**
(`ACESTEP_INIT_LLM=false`). Expect minutes per clip. Start with a **30-second** concept,
note how long it takes, and listen before trying longer ones. Logs go to `data/logs/`.

On an NVIDIA GPU with less than 8 GB (common in laptops) the script switches to low-VRAM mode:
`ACESTEP_OFFLOAD_TO_CPU=true`, `ACESTEP_OFFLOAD_DIT_TO_CPU=true`, `ACESTEP_INIT_LLM=false`.
Without it the model stays in VRAM, the final audio decode falls back to a single CPU core,
and a 15-second clip can take hours. Set any of these yourself to override.

With a GPU later: install the NVIDIA Windows driver with WSL support (no Linux driver inside
WSL), check `nvidia-smi` works in Ubuntu, then run the same script. Setting
`ADAPTER_THINKING=true` enables ACE-Step's language-model planning for better structure.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `ACE_STEP_ENABLED` | `false` | Nocturna calls the adapter when running the workflow |
| `ACE_STEP_URL` | `http://127.0.0.1:8002` | The **adapter**, not ACE-Step itself |
| `ACE_STEP_TIMEOUT_S` | `3600` | How long Nocturna waits for one generation |
| `ADAPTER_ACESTEP_URL` | `http://127.0.0.1:8001` | ACE-Step's API server |
| `ADAPTER_MEDIA_DIR` | `./data/audio` | Must equal Nocturna's `AUDIO_DIR` |
| `ADAPTER_MODEL` | ACE-Step default | DiT model, e.g. `acestep-v15-turbo` |
| `ADAPTER_INFERENCE_STEPS` | `8` | Turbo: 8 recommended |
| `ADAPTER_THINKING` | `false` | Use the 5Hz LM (slow on CPU) |
| `ADAPTER_ACESTEP_REPO_DIR` | set by start script | Used to record the ACE-Step commit |
| `ADAPTER_LICENSE` | `MIT` | Recorded on every generated take |
| `ADAPTER_CHECK_OUTPUT` | `true` | Refuse broken (NaN) output instead of saving it as a take |

**Upgrading from Stage 1/2:** if your `.env` still has `ACE_STEP_URL=http://127.0.0.1:8001`,
change it to `:8002`. Port 8001 is ACE-Step itself, which Nocturna cannot talk to directly.

## Older GPUs: broken, near-empty clips

GPUs older than NVIDIA's Ampere generation (for example the T1200, GTX 16xx and RTX 20xx)
have no bfloat16, so ACE-Step falls back to float16. On these cards the numbers can
overflow. You can spot it in `data/logs/acestep.log`:

```
[Normalization] Audio 0 BEFORE: Peak=nan
```

The saved file is then near-silence with full-scale clicks: about −23 LUFS with a 0 dBFS
peak. The adapter now checks every file. If it finds NaN samples, or a peak above ACE-Step's
own −1 dBFS normalization, it deletes the file and fails the run with a clear message, so the
broken clip never shows up as a take.

What to try:

1. Decode on the processor: `ACESTEP_VAE_ON_CPU=true bash scripts/start-generation.sh`.
   This only helps if the overflow happens in the decoder.
2. If the log still says `Peak=nan`, the card can't run the model. Use a cloud GPU for
   generation, or an Ampere or newer card (RTX 30xx and up).

## Limits

- **Run workflow** waits until the clip is finished. On CPU the page can sit on
  "Generating…" for several minutes; that is expected.
- One clip per run. To try another seed, reject or reopen, change the seed, and run again.
- The real ACE-Step path is covered by tests against a fake server built from ACE-Step's API
  docs, not by a live model run in CI.
