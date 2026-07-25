# OratorDeck Handoff

Read this reference before running the TTS, subtitle, annotation, and video
pipeline.

## Repository Inputs

From the OratorDeck root, prepare:

```text
resources/
├── slide-01_slug.md
├── slide-02_slug.md
├── ...
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_slug.png
    ├── slide-02_slug.png
    └── ...
```

Prompt files are authoritative sources. OratorDeck's runtime currently consumes
the notes and images. The prompt audit bridges those two layers before media
generation.

Private prompt sources, `SPEAKER_NOTES.md`, generated images, models, caches,
and `data/runs/` should remain untracked unless the user explicitly chooses to
publish them.

## Environment Preflight

Read `docs/installation.md`. Confirm:

- Python 3.11 and all `requirements.txt` dependencies are available;
- the pinned Voicebox backend patch is applied;
- the selected CUDA GPU is visible outside any restricted sandbox;
- Voicebox responds at the URL used by the workflow;
- the exact Qwen CustomVoice profile exists;
- available disk space covers slide images, model caches, per-slide audio,
  clips, and the final video.

Do not substitute an arbitrary profile or CPU inference without telling the
user.

## Deterministic Source Checks

Run the skill audit first:

```bash
./.venv/bin/python \
  <skill-dir>/scripts/audit_prompt_first_deck.py \
  --prompts-dir resources \
  --notes resources/SPEAKER_NOTES.md \
  --images-dir resources/generated-images \
  --strict
```

The prompt manifest used for image generation should also be retained under
`.tmp/prompt-first/`:

```bash
./.venv/bin/python \
  <skill-dir>/scripts/build_prompt_manifest.py \
  resources \
  --output .tmp/prompt-first/PROMPT_MANIFEST.json \
  --overwrite
```

Then check OratorDeck's exact runtime parser:

```bash
mkdir -p .tmp/prompt-first

./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  resources/SPEAKER_NOTES.md \
  --output .tmp/prompt-first/SPEAKER_NOTES_CHUNKS.json \
  --tts-output .tmp/prompt-first/SPEAKER_NOTES_TTS.txt

./.venv/bin/python scripts/generate-english-keynote.py \
  .tmp/prompt-first/SPEAKER_NOTES_CHUNKS.json \
  --profile-name "<exact Voicebox profile>" \
  --output .tmp/prompt-first/preflight.wav \
  --dry-run
```

The formatter must report the expected slide count and total target duration.

## Workflow Playground

`scripts/generate-keynote-workflow.sh` is intentionally transparent. Inspect
and edit its values directly for the run:

- `run_name`;
- resource input paths when they differ from defaults;
- exact Voicebox profile;
- TTS batch size, attempts, and timing tolerance;
- CUDA device for Whisper and any environment-level GPU selection.

The script creates one timestamped directory below `data/runs/` and copies the
run inputs into it before generation. Preserve that centralized run layout.

Start Voicebox as described in `docs/installation.md`, then run the workflow.
Monitor every stage; batch TTS and video rendering may produce output only at
batch boundaries.

## Completion Checks

Require all of the following:

1. Timing report status is `completed`.
2. Its slide count equals the prompt, note, and image counts.
3. One selected WAV exists per slide.
4. SRT, VTT, and LRC subtitles exist.
5. Anchor report status is `completed`.
6. One video clip exists per slide.
7. Final MP4 contains H.264 video and AAC audio.
8. WAV, subtitle end, anchor-report duration, and MP4 duration agree within a
   small encoding tolerance.
9. The workflow log contains no traceback, out-of-memory failure, or aborted
   stage.

Report timing-tolerance misses and unresolved OCR anchors as quality metrics,
not hidden failures. A completed pipeline can still require content review.
