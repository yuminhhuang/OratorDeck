# Installation

OratorDeck's three modules have different requirements. The authoring skill
needs an Agent with image-generation access, Deck Verdict needs only Python,
CPU OCR, and a browser, while long-form local media generation is designed for
Linux, Python 3.11, and an NVIDIA CUDA GPU.

## Install only Deck Verdict

Use this path to review prepared slide images, narration, bold anchors, target
times, and anchor rectangles without installing an Agent or GPU stack:

```bash
python3.11 -m venv .verdict-venv
.verdict-venv/bin/python -m pip install --upgrade pip
.verdict-venv/bin/python -m pip install \
  "oratordeck-verdict @ git+https://github.com/yuminhhuang/OratorDeck.git"
```

Prepare the self-contained browser editor:

```bash
oratordeck-verdict prepare SPEAKER_NOTES.md generated-images \
  --output deck-verdict.html \
  --review-json deck-review.json \
  --ocr-output deck-ocr.json
```

Open the panel bound to its one authoritative state file:

```bash
oratordeck-verdict edit deck-verdict.html deck-review.json
```

Keep the command running while editing. **Save deck review** atomically
overwrites `deck-review.json`; **Reset** overwrites the same file with the
generated initial state. Refresh reloads the JSON, retaining saved changes and
discarding unsaved ones. The panel has no import, browser autosave, or
download-based save path. Stop the editor with Ctrl+C when finished.

Apply the saved review into one portable handoff directory:

```bash
oratordeck-verdict apply \
  deck-review.json SPEAKER_NOTES.md generated-images \
  --ocr-results deck-ocr.json \
  --output-dir reviewed
```

This produces reviewed `SPEAKER_NOTES.md`, `SPEAKER_NOTES_CHUNKS.json`,
`SPEAKER_NOTES_TTS.txt`, `anchor-overrides.json`, and the reusable
`deck-ocr.json`. The OCR artifact contains raw OCR lines bound to each source
image by SHA-256. A later video run can reuse it without loading RapidOCR, while
a changed image causes a hard validation error instead of silently reusing
stale coordinates.

The package installs Pillow, RapidOCR, and its CPU ONNX Runtime only; it does
not install the OratorDeck skill, Voicebox, PyTorch, Whisper, FFmpeg, or a CUDA
runtime.

## Install the full media runtime

### 1. Install OratorDeck

```bash
git clone https://github.com/yuminhhuang/OratorDeck.git
cd OratorDeck

python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

If the default PyTorch wheel does not match your GPU runtime, install the
appropriate build from the [official PyTorch selector](https://pytorch.org/get-started/locally/)
before installing `requirements.txt`.

All OratorDeck model downloads, caches, temporary files, and outputs default to
directories inside the checkout.

### 2. Prepare the Voicebox TTS service

OratorDeck pins a compatible Voicebox revision and applies the required
slide-atomic Qwen batch API:

```bash
scripts/setup-voicebox.sh
```

Install the Voicebox Python backend:

```bash
cd vendor/voicebox
just setup-python
cd ../..
```

`just setup-python` follows the upstream Voicebox installation path. It installs
more engines than OratorDeck itself requires; the OratorDeck production path
uses Qwen CustomVoice 1.7B.

FlashAttention 2 is optional. If a compatible build is installed in the
Voicebox backend environment, the patch enables it automatically and falls back
to PyTorch attention if loading fails.

### 3. Start Voicebox

```bash
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

The launcher binds to `127.0.0.1:17493` and keeps models and mutable caches
inside OratorDeck. Leave it running while generating speech.

Create an English Qwen CustomVoice preset profile using the Voicebox app, or
through its local API:

```bash
curl -X POST http://127.0.0.1:17493/profiles \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Presentation Voice",
    "language": "en",
    "voice_type": "preset",
    "preset_engine": "qwen_custom_voice",
    "preset_voice_id": "Aiden",
    "default_engine": "qwen_custom_voice"
  }'
```

The first synthesis may require downloading the selected Qwen model through
Voicebox. Model files remain subject to their model-card license.

### 4. Add presentation inputs

```bash
cp resources/SPEAKER_NOTES.example.md resources/SPEAKER_NOTES.md
```

Replace the example text, then place exactly one corresponding image per slide
under `resources/generated-images/`. See `resources/README.md` for the naming
and anchor contract.

### 5. Run the workflow

Open `scripts/generate-keynote-workflow.sh` and edit:

- `run_name`
- the Voicebox `--profile-name`
- GPU selection
- batch size and timing settings

Then run:

```bash
scripts/generate-keynote-workflow.sh
```

On the first run, the default `review_before_tts=true` setting creates
`resources/.oratordeck/deck-verdict.html` and the reusable
`resources/.oratordeck/deck-ocr.json`, then exits before calling TTS. Run the
printed state-bound editor command:

```bash
.venv/bin/python -m oratordeck_verdict edit \
  resources/.oratordeck/deck-verdict.html \
  resources/.oratordeck/deck-review.json
```

Keep it running while you flip through the deck, edit the manuscript and bold
anchors, and correct anchor rectangles. Save overwrites the fixed review JSON;
Reset overwrites it with the generated initial state; refresh reloads it. Stop
the editor with Ctrl+C when finished.

Run the workflow again. It validates the review and OCR intermediate against
the exact note and image hashes before TTS, snapshots the reviewed inputs, and
starts media generation. The final line prints the timestamped run directory;
the MP4 and all intermediate artifacts are stored together below `data/runs/`.

The media pass also writes a strictly box-only `video/anchor-verdict.html` with
subtitle timing diagnostics. Narration and anchors are read-only. Open it with
the printed `oratordeck-verdict edit` command bound to
`video/anchor-overrides.json`. **Save box overrides** overwrites that file,
while **Reset** writes the generated initial box state. Apply it with the exact
`--rerender-from-report ... --anchor-overrides ... --overwrite` command shown
in the page without repeating TTS or subtitle generation. Manuscript or anchor
text changes must return to the pre-TTS verdict and start a new media pass.

## Synthetic smoke test

The repository includes a two-slide synthetic demo:

```bash
./.venv/bin/python scripts/create-demo-slides.py
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  examples/demo/SPEAKER_NOTES.md \
  --output examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --tts-output examples/demo/SPEAKER_NOTES_TTS.txt
./.venv/bin/python scripts/generate-english-keynote.py \
  examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --dry-run
```

This validates the public input without contacting Voicebox or downloading a
speech model.
