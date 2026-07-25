# Installation

The reference environment is Linux, Python 3.11, and an NVIDIA CUDA GPU.
CPU execution is possible for some stages but is not a practical target for a
long presentation.

## 1. Install OratorDeck

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

## 2. Prepare the Voicebox TTS service

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

## 3. Start Voicebox

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

## 4. Add presentation inputs

```bash
cp resources/SPEAKER_NOTES.example.md resources/SPEAKER_NOTES.md
```

Replace the example text, then place exactly one corresponding image per slide
under `resources/generated-images/`. See `resources/README.md` for the naming
and anchor contract.

## 5. Run the workflow

Open `scripts/generate-keynote-workflow.sh` and edit:

- `run_name`
- the Voicebox `--profile-name`
- GPU selection
- batch size and timing settings

Then run:

```bash
scripts/generate-keynote-workflow.sh
```

The final line prints the timestamped run directory. The MP4 and all
intermediate artifacts are stored together below `data/runs/`.

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
