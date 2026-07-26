# OratorDeck

> Generate a narrated video with underlined visual anchors—plus separate,
> matching timed subtitle files—so you can prepare a slide presentation faster.

![OratorDeck final output: a narrated slide with the spoken visual anchor underlined and separate timed subtitle files](docs/assets/oratordeck-final-effect.png)

[English](README.md) · [简体中文](README.zh-CN.md)

## What does OratorDeck do?

OratorDeck turns a slide presentation into a complete narrated video. Each
slide stays on screen while its narration plays, and successfully located
visible phrases are underlined at the moment they are spoken. Matching timed
subtitles are delivered as separate SRT, WebVTT, and LRC files.

The result is useful for rehearsing, reviewing, sharing, or publishing a
presentation without manually recording and editing every slide.

Each media run also produces a machine-readable anchor map with the slide
number, the anchor's 1-based appearance order on that slide, and its normalized
position. You can use this map to match anchors to elements in the original
editable slides and build appear/exit animations there.

Between authoring and media generation, a self-contained **Deck Verdict** opens
the presentation as a restricted slide editor. Flip through slides, inspect
OCR-selected anchors, edit the manuscript and its bold anchors, and correct
each anchor's bounding box by moving the rectangle or dragging its top, right,
bottom, or left edge. The slide image itself remains read-only. This review
gate catches problems before costly audio and video generation.

OratorDeck is intentionally split into three independently usable, composable
modules:

1. **Skill-assisted authoring:** the optional `$oratordeck` skill turns
   per-slide prompts into aligned slide images and synchronized speaker notes.
   It does not require the local media runtime or a local GPU.
2. **Standalone quality review:** the separately installable
   `oratordeck-verdict` package turns those images and notes into the browser
   review gate, then applies the saved decisions. It requires neither an Agent
   nor a GPU.
3. **Standalone media generation:** the repository workflow turns reviewed
   images and speaker notes into audio, subtitles, and the annotated video. It
   does not require the skill or an Agent once those inputs exist.

The handoffs are ordinary files, so use any module by itself or run all three
in sequence:

```text
per-slide prompts → images + speaker notes → Deck Verdict → narrated video
  optional Agent          CPU/browser only              GPU media runtime
```

## Is OratorDeck right for you?

Use this quick guide:

| Your main goal | Best starting point |
| --- | --- |
| Produce a long-form English presentation from aligned slide images and speaker notes, with visible phrases underlined as they are spoken | **OratorDeck** |
| Create prompt-defined slide images and synchronized notes now, then generate media later or on another device | The optional **OratorDeck skill** |
| Review slide–narration consistency, bold anchors, timing goals, and anchor boxes without an Agent or GPU | The standalone **OratorDeck Verdict** package |
| Build and manually refine a native, editable PPTX through a GUI or an Agent | [Presenton](https://github.com/presenton/presenton) or [PPT Master](https://github.com/hugohe3/ppt-master) |
| Turn a research-paper PDF directly into a short narrated research video with burned-in captions and region-based visual cues | [ResearchStudio Paper2Video](https://github.com/microsoft/ResearchStudio/tree/main/ResearchStudio-Reel/skills/paper2video) |
| Generate a presentation deck without needing narration or an annotated video | [Presenton](https://github.com/presenton/presenton), [PPT Master](https://github.com/hugohe3/ppt-master), or [PPTAgent](https://github.com/icip-cas/PPTAgent) |

OratorDeck is a focused command-line workflow, not a general-purpose
PowerPoint editor or one-click paper summarizer. It is a strong fit when you
want precise control over long-form narration, slide timing, subtitle files,
and exact text anchors. The full local media workflow is currently designed
for Python 3.11 and an NVIDIA CUDA GPU; it does not produce an editable PPTX,
and its subtitles are separate files rather than burned into the video.

These tools are not mutually exclusive. You can author a deck elsewhere, then
export its slide images and adapt its notes to OratorDeck's input contract. A
device without a local GPU can use the authoring skill and/or Deck Verdict; a
GPU workstation without an Agent can use Deck Verdict and media generation.

## Option 1: Start from per-slide prompts

This is the easiest option when you are still preparing the presentation.
Create one self-contained Markdown prompt per slide:

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

Each prompt should describe the slide's purpose, content, layout, and exact
visible wording. If you only have an outline, the skill can help write these
prompts first.

Install the
[`oratordeck`](skills/oratordeck) skill from:

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck
```

For images and speaker notes only—even on a device without a local GPU—ask
Codex:

```text
Use $oratordeck with my per-slide prompts to generate the slide images and
synchronized English speaker notes.
```

The skill stops after preparing and auditing the prompts, matching images, and
speaker notes. It does not install or run TTS, transcription, OCR video
rendering, or FFmpeg. You remain in control of facts, numbers, citations, and
other source material.

Image creation requires an image-generation capability available to the agent.
The skill does not require a GPU on the user's device. If image generation is
unavailable, the skill can still help author and audit the prompts. Its bundled
audits use only the Python 3 standard library and work on Linux, macOS, and
Windows.

When the OratorDeck media runtime and a suitable GPU are already available, you
can ask the Agent to continue after the skill finishes:

```text
After the slide images and speaker notes pass their audit, continue outside the
skill by running scripts/generate-keynote-workflow.sh to produce the final
media.
```

Without that extra request, the skill ends with the images and speaker notes.

## Option 2: Start from your own images and speaker notes

This is the manual-input path. Neither the skill nor an Agent is required once
you have prepared these two inputs:

```text
resources/
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_opening.png
    ├── slide-02_problem.png
    └── ...
```

You are responsible for ensuring that each image and its narration describe
the same content.

Write one section per slide in `SPEAKER_NOTES.md`:

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

The bold phrase is spoken normally. If the same phrase is visible and legible
in the slide image, OratorDeck tries to locate and underline it when it is
spoken. Any unresolved anchors are recorded in the run report.

Slide numbers must be contiguous and agree across the notes and images.
Supported image names include `slide-01.png`, `slide-01-opening.jpg`, and
`slide-01_opening.webp`.

## Review the deck before TTS

The default workflow deliberately stops before audio on its first run and
creates two self-contained pre-TTS artifacts:

```text
resources/.oratordeck/deck-verdict.html
resources/.oratordeck/deck-ocr.json
```

Start the printed state-bound editor command and keep it running while the
panel is open:

```bash
.venv/bin/python -m oratordeck_verdict edit \
  resources/.oratordeck/deck-verdict.html \
  resources/.oratordeck/deck-review.json
```

It opens a small, restricted presentation editor in your browser:

- use the filmstrip, Previous/Next buttons, or Page Up/Page Down to change
  slides;
- edit the slide title, target duration, and narration in the inspector;
- add, remove, or rewrite anchors by editing `**bold phrases**`;
- select an anchor box and drag inside it to move the whole rectangle;
- drag the top, right, bottom, or left handle to resize one edge;
- create a box for an unresolved anchor, reset a box to OCR, or suppress an
  underline that should not appear;
- inspect the OCR score, word coverage, candidate count, timing source, and
  reasons attached to the selected anchor.

The panel is always bound to the JSON path supplied to `edit`. Its top bar
deliberately has only two state-changing actions:

- **Save deck review** atomically overwrites the bound
  `resources/.oratordeck/deck-review.json`.
- **Reset** overwrites that same JSON with the HTML's generated initial state.

There is no browser autosave or import state. A refresh reloads the bound JSON,
so saved changes remain and unsaved changes are discarded. Opening the HTML
directly through `file://` is intentionally read-only because a normal web page
cannot safely overwrite a fixed local file. The lightweight editor service
listens only on `127.0.0.1` and uses a per-session capability URL.

The review is bound to the exact speaker-notes and slide-image hashes. On the
next workflow run, OratorDeck validates it and generates the reviewed
`SPEAKER_NOTES.md`, chunk document, TTS reference, and anchor overrides as one
consistent set before calling TTS. `deck-ocr.json` separately stores raw OCR
lines, confidence scores, coordinates, image dimensions, and each image's
SHA-256. The video stage validates those hashes and reuses the OCR lines while
rerunning anchor assignment against the final reviewed manuscript. Both stages
call the same OCR/anchoring module, so their matching behavior cannot drift.

This panel is a quality gate, not a slide-pixel editor. If a prompt-generated
or imported image is wrong, regenerate or replace that image, recreate the
verdict, and review it again. Manuscript, timing, bold anchors, and bounding
boxes can be corrected directly in the panel.

### Install only Deck Verdict

Deck Verdict is a lightweight Python package with CPU OCR and a self-contained
browser UI. It does not install the OratorDeck skill, Voicebox, PyTorch,
Whisper, FFmpeg, or any GPU runtime:

```bash
python3.11 -m venv .verdict-venv
.verdict-venv/bin/python -m pip install \
  "oratordeck-verdict @ git+https://github.com/yuminhhuang/OratorDeck.git"
```

Prepare the review from any matching notes/image pair:

```bash
oratordeck-verdict prepare SPEAKER_NOTES.md generated-images \
  --output deck-verdict.html \
  --review-json deck-review.json \
  --ocr-output deck-ocr.json
```

Open the panel with its fixed state file, review every page, and click
**Save deck review**:

```bash
oratordeck-verdict edit deck-verdict.html deck-review.json
```

Stop the editor with Ctrl+C when finished, then validate and apply the saved
decisions:

```bash
oratordeck-verdict apply \
  deck-review.json SPEAKER_NOTES.md generated-images \
  --ocr-results deck-ocr.json \
  --output-dir reviewed
```

The `reviewed/` directory contains consistent speaker notes, slide-atomic
chunks, a subtitle/TTS reference, anchor overrides, and reusable
`deck-ocr.json`. You can hand those files to another system, or place the
review and OCR files at `resources/.oratordeck/deck-review.json` and
`resources/.oratordeck/deck-ocr.json` before continuing with OratorDeck's media
workflow. See the
[installation guide](docs/installation.md#install-only-deck-verdict) for
details.

## Install the local media runtime

Skip this section if you only want the skill or standalone Deck Verdict. For
local audio and video generation, Python 3.11 and a CUDA-capable NVIDIA GPU are
recommended. Git and [`just`](https://github.com/casey/just) are also required
to prepare Voicebox.

```bash
git clone https://github.com/yuminhhuang/OratorDeck.git
cd OratorDeck

python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
```

Follow the command printed by `setup-voicebox.sh` to install the Voicebox
backend. Then start the local service:

```bash
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

With the service running, create a Qwen CustomVoice profile in Voicebox. See
the [installation guide](docs/installation.md) for the complete Voicebox and
voice-profile setup.

## Run the standalone media workflow

Whether the assets came from the skill or were prepared manually, edit
`scripts/generate-keynote-workflow.sh` and set the voice profile, GPU, output
name, and any timing preferences. Then run it once to prepare the Deck Verdict:

```bash
scripts/generate-keynote-workflow.sh
```

Run the printed `oratordeck_verdict edit` command. It opens
`resources/.oratordeck/deck-verdict.html` bound to
`resources/.oratordeck/deck-review.json`; complete the review and click Save.
Stop the editor with Ctrl+C, then run the workflow command again to generate
audio, subtitles, anchor cues, and video. Set `review_before_tts=false` in the
playground script only when you explicitly want to bypass this gate.

## What will the full media workflow produce?

Each run is saved in one timestamped directory:

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
│   ├── deck-review.json
│   ├── deck-ocr.json
│   ├── anchor-overrides.json
│   └── generated-images/
├── audio/
│   ├── my-talk.wav
│   ├── my-talk.timing.json
│   └── my-talk.chunks/
├── subtitles/
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── clips/
│   ├── anchor-animation-cues.json
│   ├── anchor-verdict.html
│   ├── anchor-overrides.json    # after manual correction
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

The main deliverable is `video/my-talk.mp4`. You also receive the complete
audio, separate subtitle files, one audio/video file per slide, a snapshot of
the inputs, timing information, anchor results, and the full generation log.
The copied `input/deck-ocr.json` prevents the video planner from running
RapidOCR over unchanged images a second time; a hash mismatch is a hard error
rather than a silent cache miss.
`video/anchor-animation-cues.json` is the compact intermediate artifact for
editable-slide animation: resolved anchors have normalized
`x`/`y`/`width`/`height` boxes and centers, while unresolved anchors remain in
sequence with a `null` position so later animation numbers do not shift.
The media pass writes `video/anchor-verdict.html` as the post-TTS, box-only
version of the slide editor, augmented with subtitle timing diagnostics.
Narration, target time, and anchor text are read-only because changing them
would invalidate the existing audio and subtitles. You may only move, resize,
create, restore, or suppress bounding boxes.

Open the post-TTS panel with the JSON it owns:

```bash
.venv/bin/python -m oratordeck_verdict edit \
  data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-verdict.html \
  data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json
```

Its top bar likewise contains only **Save box overrides** and **Reset**. Save
overwrites the bound `video/anchor-overrides.json`; Reset overwrites it with the
panel's initial box state, and refresh reloads it. After saving, rerender the
same run without repeating TTS or subtitle generation:

```bash
.venv/bin/python scripts/generate-keynote-video.py \
  --rerender-from-report data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-video-report.json \
  --anchor-overrides data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json \
  --overwrite
```

The override file is bound to the exact chunk document and slide-image hashes,
so stale corrections fail before FFmpeg starts. The regenerated verdict marks
accepted manual decisions as `corrected`. To change the manuscript, target
time, or bold anchors, return to the pre-TTS Deck Verdict and generate a new
audio/subtitle/video run.

## Current limitations

- The standalone media workflow currently targets English narration.
- Slide backgrounds are static images; underlined anchors provide the visual
  emphasis.
- Timed subtitles are separate SRT, WebVTT, and LRC files. They are not
  currently burned into or embedded in the MP4.
- An anchor can only be underlined when its text is visible and legible in the
  image.
- Deck Verdict can edit narration, anchors, timing, and bounding boxes, but not
  the pixels or layout of the slide image.
- Target durations are goals. The selected voice may speak faster or slower
  than requested.
- Generated slides, narration, subtitles, and anchors should be reviewed before
  publication.
- Model weights are downloaded separately and remain subject to their own
  licenses and terms.

## For developers

The implementation stages, data contracts, report formats, validation
strategy, repository layout, and roadmap are documented separately in the
[technical architecture](docs/architecture.md#english).

## Responsible use

Use only voices and source material that you own or have permission to use.
OratorDeck is intended to assist authorship, not to impersonate people or hide
the origin of synthetic media.

## Acknowledgements

OratorDeck is built on an excellent open-source ecosystem. Special thanks to:

- [Voicebox](https://github.com/jamiepine/voicebox) and its contributors for
  the local voice studio and inference API.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) for the speech models used
  by the current narration workflow.
- [OpenAI Whisper](https://github.com/openai/whisper) and
  [Hugging Face Transformers](https://github.com/huggingface/transformers) for
  speech recognition and model tooling.
- [RapidOCR](https://github.com/RapidAI/RapidOCR) for locating visible anchor
  text.
- [FFmpeg](https://ffmpeg.org/) and
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) for media
  encoding and assembly.
- [PyTorch](https://github.com/pytorch/pytorch),
  [FlashAttention](https://github.com/Dao-AILab/flash-attention),
  [NumPy](https://github.com/numpy/numpy),
  [python-soundfile](https://github.com/bastibe/python-soundfile), and
  [Pillow](https://github.com/python-pillow/Pillow) for local inference and
  media processing.

OratorDeck is an independent project and is not endorsed by or affiliated with
these upstream projects.

## License

OratorDeck is released under the [MIT License](LICENSE). Runtime libraries and
model weights retain their own licenses and terms. See
[Third-Party Notices](THIRD_PARTY_NOTICES.md).
