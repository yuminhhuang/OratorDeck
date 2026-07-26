#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_dir"

# This file is intentionally a playground. Edit the name, paths, and command
# arguments below directly for each run.
run_name="my-talk"
open_pre_tts_verdict=true
deck_verdict_file="$repo_dir/resources/.oratordeck/deck-verdict.html"
deck_review_file="$repo_dir/resources/.oratordeck/deck-review.json"
deck_ocr_file="$repo_dir/resources/.oratordeck/deck-ocr.json"

run_dir="$repo_dir/data/runs/${run_name}-$(date +%Y%m%d-%H%M%S)"
input_dir="$run_dir/input"
images_dir="$input_dir/generated-images"
audio_dir="$run_dir/audio"
subtitles_dir="$run_dir/subtitles"
video_dir="$run_dir/video"

mkdir -p "$input_dir" "$images_dir" "$audio_dir" "$subtitles_dir" "$video_dir"
cp resources/SPEAKER_NOTES.md "$input_dir/"
cp -a resources/generated-images/. "$images_dir/"

# Keep the whole console trace with the other artifacts from this run.
exec > >(tee "$run_dir/workflow.log") 2>&1

# Freeze the review decision at launch. Saving in the concurrently open editor
# never changes an in-flight run: interrupt and rerun to use the new review.
review_available_at_start=false
if [[ -f "$deck_review_file" ]]; then
  review_available_at_start=true
  cp "$deck_review_file" "$input_dir/deck-review.json"
fi

# Prepare the optional pre-TTS editor and reusable image-bound OCR results.
# Unlike the former gate, this never exits or waits for human review.
if [[ ! -f "$deck_verdict_file" || ! -f "$deck_ocr_file" ]]; then
  ./.venv/bin/python scripts/prepare-deck-review.py \
    resources/SPEAKER_NOTES.md \
    resources/generated-images \
    --output "$deck_verdict_file" \
    --review-json "$deck_review_file" \
    --ocr-output "$deck_ocr_file" \
    --overwrite
fi
verdict_server_pid=""
stop_verdict_server() {
  if [[ -n "$verdict_server_pid" ]]; then
    kill "$verdict_server_pid" 2>/dev/null || true
    wait "$verdict_server_pid" 2>/dev/null || true
  fi
}
trap stop_verdict_server EXIT

echo "Optional Deck Verdict: $deck_verdict_file"
echo "State-bound editor command:"
echo "  ./.venv/bin/python -m oratordeck_verdict edit \"$deck_verdict_file\" \"$deck_review_file\""
echo "Save overwrites $deck_review_file; Reset restores its initial JSON."
if [[ "$open_pre_tts_verdict" == true ]]; then
  ./.venv/bin/python -m oratordeck_verdict edit \
    "$deck_verdict_file" \
    "$deck_review_file" &
  verdict_server_pid=$!
  echo "The editor is starting in the background while media generation continues."
fi
if [[ "$review_available_at_start" == true ]]; then
  echo "This run uses the review snapshot that existed when it started."
  echo "New edits apply on the next run; interrupt and rerun if they are needed."
else
  echo "No saved review existed at launch, so this run continues from the source inputs."
  echo "Review is optional; Save, then interrupt and rerun only if corrections are needed."
fi

# 1. Apply the review snapshot captured at launch, or format the source directly.
if [[ "$review_available_at_start" == true ]]; then
  review_ocr_args=()
  if [[ -f "$deck_ocr_file" ]]; then
    review_ocr_args=(
      --ocr-results "$deck_ocr_file"
      --ocr-output "$input_dir/deck-ocr.json"
    )
  fi
  ./.venv/bin/python scripts/apply-deck-review.py \
    "$input_dir/deck-review.json" \
    "$input_dir/SPEAKER_NOTES.md" \
    "$images_dir" \
    --speaker-notes-output "$input_dir/SPEAKER_NOTES.md" \
    --chunks-output "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
    --tts-output "$input_dir/SPEAKER_NOTES_TTS.txt" \
    --anchor-overrides-output "$input_dir/anchor-overrides.json" \
    "${review_ocr_args[@]}" \
    --overwrite
else
  ./.venv/bin/python scripts/format-speaker-notes-chunks.py \
    "$input_dir/SPEAKER_NOTES.md" \
    --output "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
    --tts-output "$input_dir/SPEAKER_NOTES_TTS.txt"
  if [[ -f "$deck_ocr_file" ]]; then
    cp "$deck_ocr_file" "$input_dir/deck-ocr.json"
  fi
fi

# 2. Generate the final audio and one indivisible WAV per slide.
./.venv/bin/python scripts/generate-english-keynote.py \
  "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
  --url http://127.0.0.1:17493 \
  --profile-name "YOUR VOICEBOX PROFILE" \
  --batch-size 4 \
  --timing-attempts 2 \
  --timing-tolerance 0.08 \
  --output "$audio_dir/$run_name.wav" \
  --overwrite

# 3. Generate corrected subtitles while retaining Whisper's raw subtitles.
CUDA_VISIBLE_DEVICES=0 ./.venv/bin/python scripts/generate-english-subtitles.py \
  "$audio_dir/$run_name.wav" \
  --model turbo \
  --device cuda \
  --reference "$input_dir/SPEAKER_NOTES_TTS.txt" \
  --output-prefix "$subtitles_dir/$run_name"

# 4. Resolve remaining anchors, write the slide editor, render, and concatenate.
anchor_override_args=()
if [[ -f "$input_dir/anchor-overrides.json" ]]; then
  anchor_override_args=(--anchor-overrides "$input_dir/anchor-overrides.json")
fi
ocr_results_args=()
if [[ -f "$input_dir/deck-ocr.json" ]]; then
  ocr_results_args=(--ocr-results "$input_dir/deck-ocr.json")
fi
./.venv/bin/python scripts/generate-keynote-video.py \
  "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
  "$audio_dir/$run_name.timing.json" \
  "$images_dir" \
  --subtitles "$subtitles_dir/$run_name.srt" \
  "${anchor_override_args[@]}" \
  "${ocr_results_args[@]}" \
  --work-dir "$video_dir" \
  --animation-cues-output "$video_dir/anchor-animation-cues.json" \
  --anchor-verdict-output "$video_dir/anchor-verdict.html" \
  --review-confidence-threshold 0.78 \
  --review-coverage-threshold 0.65 \
  --review-ambiguity-margin 0.04 \
  --output "$video_dir/$run_name.mp4" \
  --overwrite

echo "Completed: $run_dir"
echo "Review and correct anchors with the state-bound editor:"
echo "  ./.venv/bin/python -m oratordeck_verdict edit \"$video_dir/anchor-verdict.html\" \"$video_dir/anchor-overrides.json\""
echo "After Save updates $video_dir/anchor-overrides.json, rerender with:"
echo "  .venv/bin/python scripts/generate-keynote-video.py --rerender-from-report \"$video_dir/anchor-video-report.json\" --anchor-overrides \"$video_dir/anchor-overrides.json\" --overwrite"
if [[ -n "$verdict_server_pid" ]]; then
  echo "The background pre-TTS editor closes now; use its printed command to reopen it."
fi
