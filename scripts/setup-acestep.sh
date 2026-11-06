#!/usr/bin/env bash
# Install ACE-Step 1.5 next to Nocturna, pinned to a tested commit, in its own uv environment.
# Nothing large is downloaded unless you pass --download-model.
#
#   bash scripts/setup-acestep.sh                    # clone + install code only
#   bash scripts/setup-acestep.sh --download-model   # also fetch the default model (several GB)
set -euo pipefail

ACESTEP_DIR=${ACESTEP_DIR:-$HOME/ACE-Step-1.5}
# Commit the Nocturna adapter was written against (2026-08-29). Override to try newer code.
ACESTEP_COMMIT=${ACESTEP_COMMIT:-ca1e85fe9430179831e6bc6be790c332190a3866}
DOWNLOAD=false
[ "${1:-}" = "--download-model" ] && DOWNLOAD=true

if ! command -v uv >/dev/null; then
  echo "==> Installing uv (Python package manager used by ACE-Step)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$ACESTEP_DIR/.git" ]; then
  echo "==> Cloning ACE-Step 1.5 into $ACESTEP_DIR"
  git clone https://github.com/ace-step/ACE-Step-1.5.git "$ACESTEP_DIR"
fi
cd "$ACESTEP_DIR"
git fetch --quiet origin
git checkout --quiet "$ACESTEP_COMMIT"
echo "==> ACE-Step at $(git rev-parse --short HEAD)"

echo "==> Installing ACE-Step's Python environment (uv sync; PyTorch is a large download)"
uv sync

if $DOWNLOAD; then
  echo "==> Downloading the default model (several GB)"
  uv run acestep-download
else
  echo "==> Skipping model download. Run again with --download-model when you are ready,"
  echo "    or ACE-Step will download it the first time its API server starts."
fi

cat <<DONE

ACE-Step is installed at $ACESTEP_DIR (commit $(git rev-parse --short HEAD)).
Model license: MIT (https://huggingface.co/ACE-Step/Ace-Step1.5). Re-check it before release.

Next: from the Nocturna folder run
  bash scripts/start-generation.sh
DONE
