# Presentation inputs

OratorDeck intentionally does not track real presentation materials.

Create:

- `resources/SPEAKER_NOTES.md`
- one image per narrated slide under `resources/generated-images/`

Start from `SPEAKER_NOTES.example.md`. Image names must match
`slide-NN.png`, `slide-NN-title.jpg`, or `slide-NN_title.webp`.

Bold phrases in the notes are spoken normally and used as visual anchors. If an
anchor should be underlined in the video, the same phrase must be legible in the
matching slide image.

Both private inputs are ignored by Git.

The default media workflow prepares
`resources/.oratordeck/deck-verdict.html` plus
`resources/.oratordeck/deck-ocr.json`, opens the optional state-bound editor in
the background, and continues into TTS without waiting. Review the slides,
manuscript, bold anchors, and bounding boxes while the GPU stages run—or ignore
the panel. Click Save to overwrite
`resources/.oratordeck/deck-review.json`; if its corrections matter, interrupt
and rerun. A run uses only the review snapshot that existed when it started, so
concurrent edits never change its inputs midway. The OCR file stores raw text
lines and coordinates bound to each source image by SHA-256; the video stage
validates and reuses it rather than running OCR a second time. Changed images
require regenerating the review artifacts. The entire `.oratordeck/` review
workspace is private and ignored by Git.
The panel deliberately has only **Save deck review** and **Reset**. It has no
browser autosave, import, or downloaded-copy state: Save writes the bound JSON,
Reset writes its generated initial state, and refresh reloads it.

The same pre-TTS quality checkpoint can be installed separately, without the skill,
TTS stack, FFmpeg, or a GPU:

```bash
python -m pip install \
  "oratordeck-verdict @ git+https://github.com/yuminhhuang/OratorDeck.git"
```

For skill-assisted authoring, install or invoke
[`oratordeck`](../skills/oratordeck). It uses one
private `resources/slide-NN_slug.md` source per slide, then derives the images
and `SPEAKER_NOTES.md` from those shared sources. Prompt sources matching
`resources/slide-*.md` are also ignored by Git.
