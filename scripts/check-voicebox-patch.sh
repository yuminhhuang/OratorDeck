#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
voicebox_commit="52f8d8dd387e4049c81ee97079d5f54e2e399b94"
patch_file="$repo_dir/patches/voicebox-qwen-batching.patch"
check_dir="$(mktemp -d)"

cleanup() {
  rm -rf -- "$check_dir"
}
trap cleanup EXIT

git clone --quiet --filter=blob:none --no-checkout \
  https://github.com/jamiepine/voicebox.git \
  "$check_dir/voicebox"
git -C "$check_dir/voicebox" checkout --quiet --detach "$voicebox_commit"
git -C "$check_dir/voicebox" apply --check "$patch_file"

echo "Patch applies cleanly to Voicebox $voicebox_commit"
