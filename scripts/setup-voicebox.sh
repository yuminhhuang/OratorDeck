#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
voicebox_dir="${ORATORDECK_VOICEBOX_DIR:-$repo_dir/vendor/voicebox}"
voicebox_commit="52f8d8dd387e4049c81ee97079d5f54e2e399b94"
patch_file="$repo_dir/patches/voicebox-qwen-batching.patch"

if [ ! -d "$voicebox_dir/.git" ]; then
  mkdir -p "$(dirname -- "$voicebox_dir")"
  git clone https://github.com/jamiepine/voicebox.git "$voicebox_dir"
  git -C "$voicebox_dir" checkout --detach "$voicebox_commit"
fi

current_commit="$(git -C "$voicebox_dir" rev-parse HEAD)"
if [ "$current_commit" != "$voicebox_commit" ]; then
  echo "Refusing to modify an unexpected Voicebox checkout." >&2
  echo "Expected: $voicebox_commit" >&2
  echo "Found:    $current_commit" >&2
  exit 1
fi

if git -C "$voicebox_dir" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
  echo "OratorDeck Voicebox patch is already applied."
else
  git -C "$voicebox_dir" apply --check "$patch_file"
  git -C "$voicebox_dir" apply "$patch_file"
  echo "Applied: $patch_file"
fi

echo
echo "Voicebox source is ready at: $voicebox_dir"
echo "Next install its Python backend:"
echo "  cd \"$voicebox_dir\""
echo "  just setup-python"
