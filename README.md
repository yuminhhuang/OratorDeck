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

OratorDeck is intentionally split into two independent, composable parts:

1. **Skill-assisted authoring:** the optional `$oratordeck` skill turns
   per-slide prompts into aligned slide images and synchronized speaker notes.
   It does not require the local media runtime or a local GPU.
2. **Standalone media generation:** the repository workflow turns prepared
   images and speaker notes into audio, subtitles, and the annotated video. It
   does not require the skill or an Agent once those inputs exist.

Use either part by itself, or run them in sequence.

## Is OratorDeck right for you?

Use this quick guide:

| Your main goal | Best starting point |
| --- | --- |
| Produce a long-form English presentation from aligned slide images and speaker notes, with visible phrases underlined as they are spoken | **OratorDeck** |
| Create prompt-defined slide images and synchronized notes now, then generate media later or on another device | The optional **OratorDeck skill** |
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
export its slide images and adapt its notes to OratorDeck's input contract.
Likewise, a device without a local GPU can use only OratorDeck's
skill-assisted authoring half.

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

This is the independent media-generation half. Neither the skill nor an Agent
is required once you have prepared these two inputs:

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

## Install the local media runtime

Skip this section if you only want the skill to create images and speaker
notes. For local audio and video generation, Python 3.11 and a CUDA-capable
NVIDIA GPU are recommended. Git and [`just`](https://github.com/casey/just)
are also required to prepare Voicebox.

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
name, and any timing preferences. Then run:

```bash
scripts/generate-keynote-workflow.sh
```

## What will the full media workflow produce?

Each run is saved in one timestamped directory:

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
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
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

The main deliverable is `video/my-talk.mp4`. You also receive the complete
audio, separate subtitle files, one audio/video file per slide, a snapshot of
the inputs, timing information, anchor results, and the full generation log.

## Current limitations

- The standalone media workflow currently targets English narration.
- Slide backgrounds are static images; underlined anchors provide the visual
  emphasis.
- Timed subtitles are separate SRT, WebVTT, and LRC files. They are not
  currently burned into or embedded in the MP4.
- An anchor can only be underlined when its text is visible and legible in the
  image.
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
