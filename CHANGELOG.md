# Changelog

All notable changes to OratorDeck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses semantic versioning.

## [Unreleased]

## [0.1.0] - 2026-07-27

This is the first public OratorDeck release. It connects Prompt-as-Slide
authoring, an Agent- and GPU-independent review workbench, and a local media
pipeline that produces long-form narrated presentation videos with separate
subtitles and speech-timed visual-anchor underlines.

The three parts remain independently usable: an Agent can prepare aligned
images and notes without a media runtime, Deck Verdict can review prepared
material in a CPU/browser environment, and a GPU workstation can generate the
media without an Agent.

### Prompt-as-Slide Authoring

- Added the optional `oratordeck` skill and defined the Prompt-as-Slide (PasS)
  protocol: one authoritative Markdown source describes each slide's purpose,
  visible wording, composition, and evidence boundaries.
- Added prompt-manifest construction, asset auditing, speaker-note patterns,
  and an explicit handoff contract for aligned slide images and English
  speaker notes.
- Kept the skill independent of Voicebox, Whisper, FFmpeg, and GPU
  dependencies so authoring can run on another device.

### Deck Verdict

- Added the separately installable `oratordeck-verdict` package for reviewing
  slide images, narration, bold anchors, target times, OCR matches, and anchor
  boxes without an Agent or GPU.
- Added a state-bound browser editor whose Save and Reset actions update a
  persistent JSON review rather than an ephemeral HTML download.
- Unified pre-TTS semantic review and post-TTS box-only correction in one
  workbench. The post-TTS phase remains hidden until subtitle-aware anchor
  planning is available.
- Added move, resize, create, restore, and suppress operations for anchor
  boxes, plus issue colors for unresolved, low-confidence, overlapping, and
  out-of-bounds anchors.
- Reused image-hash-bound OCR results across pre-TTS review and video
  generation, and supported rerendering corrected boxes without repeating TTS
  or subtitle generation.

### Narration, Subtitles, and Video

- Added slide-atomic Markdown formatting with target durations and bold visual
  anchors.
- Added batched Qwen CustomVoice synthesis with per-slide timing calibration
  and a pinned Voicebox patch providing adaptive atomic batch synthesis.
- Added Whisper transcription with optional manuscript correction while
  retaining the raw SRT, WebVTT, and LRC results.
- Added OCR-located, subtitle-timed underlines on static-slide video clips,
  global anchor assignment, review verdicts, and manual box overrides.
- Added normalized `anchor-animation-cues.json` output for presentation
  animation integrations.
- Added timestamped, centralized run directories containing inputs, chunk
  audio, combined audio, subtitles, per-slide clips, diagnostics, review
  state, and the final MP4.
- Kept Deck Verdict review non-blocking during the one-command workflow and
  printed distinct rerun instructions for pre-TTS changes and post-TTS box
  corrections.

### Documentation and Verification

- Added English and Simplified Chinese user guides, technical architecture and
  installation documents, third-party notices, security guidance, and
  contribution instructions.
- Added a two-slide synthetic demo containing no real presentation material or
  personal voice data.
- Added CI coverage for linting, unit tests, the standalone Verdict package,
  shell syntax, the synthetic input contract, and the pinned Voicebox patch.

[Unreleased]: https://github.com/yuminhhuang/OratorDeck/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yuminhhuang/OratorDeck/releases/tag/v0.1.0
