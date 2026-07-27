# Optional OratorDeck Handoff

Read this reference when the user wants OratorDeck-ready assets or explicitly
asks the agent to continue from those assets to a final video.

## Asset Contract

Place completed assets in an OratorDeck checkout as:

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

The Prompt-as-Slide (PasS) files remain the authoritative sources. The
OratorDeck skill produces and audits all files above. OratorDeck's standalone
media workflow consumes `SPEAKER_NOTES.md` and `generated-images/`; it does not
need the skill at runtime.

## Boundary

End the skill successfully when the prompt, image, and note counts agree, the
asset audit passes, and remaining review items have been reported. Do not make
skill completion depend on:

- an OratorDeck checkout;
- a particular operating system;
- a local GPU or CUDA;
- Voicebox, TTS, Whisper, OCR, or FFmpeg;
- generated audio, subtitles, clips, reports, or MP4 files.

This separation is intentional:

- A device with an Agent and image-generation capability can create the
  authoring assets without a local media GPU.
- A device without an Agent can consume manually prepared images and notes with
  OratorDeck's standalone media workflow.
- A device with both capabilities can compose the two halves.

## Explicit Follow-On

If the user explicitly requested final media and the current workspace is an
OratorDeck checkout with its media runtime already prepared:

1. finish and report the skill's asset audit;
2. read the repository `README.md` and `docs/installation.md`;
3. treat `scripts/generate-keynote-workflow.sh` as a separate follow-on
   operation outside this skill;
4. preserve the repository's timestamped run layout and validation rules.

If the runtime is absent or unsuitable, stop after the assets and tell the
user exactly what remains. Do not install GPU software, substitute a different
voice, or silently skip media stages merely to make the follow-on appear
complete.
