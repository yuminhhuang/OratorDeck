# Synthetic demo

This two-slide demo contains no real presentation material or personal voice
data. The verified end-to-end run lasts about 28 seconds and resolves all seven
visible anchors using corrected subtitle timing.

[Watch or download the narrated result](https://github.com/yuminhhuang/OratorDeck/releases/download/v0.1.0/oratordeck-demo.mp4).

Generate its two slide images:

```bash
./.venv/bin/python scripts/create-demo-slides.py
```

Validate and format the notes:

```bash
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  examples/demo/SPEAKER_NOTES.md \
  --output examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --tts-output examples/demo/SPEAKER_NOTES_TTS.txt

./.venv/bin/python scripts/generate-english-keynote.py \
  examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --dry-run
```

For full synthesis, configure Voicebox, choose a Qwen CustomVoice profile, and
run the four commands shown in `scripts/generate-keynote-workflow.sh` with the
demo paths.
