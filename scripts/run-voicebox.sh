#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
voicebox_dir="${ORATORDECK_VOICEBOX_DIR:-$repo_dir/vendor/voicebox}"
uvicorn="$voicebox_dir/backend/venv/bin/uvicorn"

if [ ! -x "$uvicorn" ]; then
  echo "Voicebox backend environment not found: $uvicorn" >&2
  echo "Run scripts/setup-voicebox.sh and install the Voicebox backend first." >&2
  exit 1
fi

export CUDA_VISIBLE_DEVICES="${ORATORDECK_TTS_GPU:-0}"
export VOICEBOX_MODELS_DIR="$repo_dir/models/voicebox"
export HF_HOME="$repo_dir/models/huggingface"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export XDG_CACHE_HOME="$repo_dir/.cache/xdg"
export UV_CACHE_DIR="$repo_dir/.cache/uv"
export NUMBA_CACHE_DIR="$repo_dir/.cache/numba"
export TMPDIR="$repo_dir/.tmp"

mkdir -p \
  "$VOICEBOX_MODELS_DIR" \
  "$HF_HOME" \
  "$XDG_CACHE_HOME" \
  "$UV_CACHE_DIR" \
  "$NUMBA_CACHE_DIR" \
  "$TMPDIR" \
  "$repo_dir/data"

exec "$uvicorn" backend.main:app \
  --app-dir "$voicebox_dir" \
  --host 127.0.0.1 \
  --port "${ORATORDECK_VOICEBOX_PORT:-17493}"
