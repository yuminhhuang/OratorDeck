#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_dir"

# This file is intentionally a playground. Edit the name, paths, and command
# arguments below directly for each run.
run_name="my-talk"
run_dir="$repo_dir/data/runs/${run_name}-$(date +%Y%m%d-%H%M%S)"

input_dir="$run_dir/input"
images_dir="$input_dir/generated-images"
audio_dir="$run_dir/audio"
subtitles_dir="$run_dir/subtitles"
video_dir="$run_dir/video"

mkdir -p "$input_dir" "$images_dir" "$audio_dir" "$subtitles_dir" "$video_dir"
cp resources/SPEAKER_NOTES.md "$input_dir/SPEAKER_NOTES.md"
cp -a resources/generated-images/. "$images_dir/"

# Keep the whole console trace with the other artifacts from this run.
exec > >(tee "$run_dir/workflow.log") 2>&1

# 1. Format the current manuscript into slide-atomic chunks.
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  "$input_dir/SPEAKER_NOTES.md" \
  --output "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
  --tts-output "$input_dir/SPEAKER_NOTES_TTS.txt"

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

# 4. Render each slide clip and concatenate the final annotated video.
./.venv/bin/python scripts/generate-keynote-video.py \
  "$input_dir/SPEAKER_NOTES_CHUNKS.json" \
  "$audio_dir/$run_name.timing.json" \
  "$images_dir" \
  --subtitles "$subtitles_dir/$run_name.srt" \
  --work-dir "$video_dir" \
  --output "$video_dir/$run_name.mp4" \
  --overwrite

echo "Completed: $run_dir"
