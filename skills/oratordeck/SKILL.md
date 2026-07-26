---
name: oratordeck
description: Create the authoring half of an OratorDeck presentation by helping users define self-contained Markdown slide prompts, generating one aligned slide image per prompt with an available image-generation capability, deriving synchronized speaker notes with target durations and bold visual anchors, and auditing the resulting assets. Use when a user wants to design slides from prompts, turn prepared slide prompts into images and speaker notes, keep slide visuals and speech aligned, or revise a prompt-defined presentation. The outputs are ready for OratorDeck's separate media workflow, but this skill does not require or run local TTS, transcription, OCR video rendering, CUDA, or the OratorDeck runtime.
---

# OratorDeck

Treat each Markdown slide prompt as source code. Treat slide images, speaker
notes, and their alignment as derivatives of those prompt sources.

## Establish The Workspace And Boundary

Work in the directory chosen by the user. When the user is working in an
OratorDeck checkout, use `resources/` by default. Otherwise, use an existing
prompt directory or create a clearly named asset directory in the user's
workspace. Do not require an OratorDeck checkout.

Inspect existing `slide-*.md`, `SPEAKER_NOTES.md`, and `generated-images/`
before changing files. Preserve unrelated user materials.

Use any available Python 3 launcher for bundled deterministic scripts:
`python`, `python3`, or `py -3`. Replace `python` in examples as appropriate.
Replace `SKILL_DIR` and `ASSET_DIR` with their actual paths. Do not create or
depend on OratorDeck's `.venv`.

This skill ends after it has produced and audited:

```text
ASSET_DIR/
├── slide-01_slug.md
├── slide-02_slug.md
├── ...
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_slug.png
    ├── slide-02_slug.png
    └── ...
```

It requires no local GPU, Voicebox service, TTS model, Whisper model, OCR
runtime, or FFmpeg installation. Image creation still requires an
image-generation capability available to the agent.

If the same user request explicitly asks for a final OratorDeck video, complete
and verify the assets first. Then, only as a separate follow-on operation
outside this skill, use the repository's standalone media workflow when its
runtime is available. If that runtime or a suitable GPU is unavailable, deliver
the completed assets without treating the missing media step as a skill
failure. Read [oratordeck-handoff.md](references/oratordeck-handoff.md) for this
boundary.

## Select The Requested Scope

- **Design only:** create or revise prompt sources and audit them.
- **Generate assets:** create slide images and synchronized speaker notes from
  existing prompts, then audit both.
- **Revise:** edit authoritative prompts first, then regenerate every affected
  derivative and adjacent narration transition.

Continue through the authoring phases implied by the request. Do not install or
run the media pipeline as part of this skill.

## Phase 1: Establish The Deck Contract

Resolve the audience, purpose, language, target duration, approximate slide
count, visual character, evidence sources, and required claims. Infer
low-risk presentation choices when possible, but never invent factual claims,
metrics, citations, identities, or institutional details.

Build a one-line argumentative role and one audience takeaway for every slide
before expanding image instructions. Ensure the ordered slide roles form one
coherent argument rather than a list of topics.

Read [prompt-contract.md](references/prompt-contract.md) before creating or
substantially restructuring prompt files.

## Phase 2: Author Prompt Sources

Create one `ASSET_DIR/slide-NN_slug.md` file per slide, with contiguous
one-based numbers and stable descriptive slugs. Use the same stem later for
the image.

For every prompt:

1. State its presentation role and audience takeaway.
2. Include one self-contained fenced image-generation prompt.
3. Specify a 16:9 canvas, composition, reading order, hierarchy, and style.
4. Put every intended visible string in straight double quotes.
5. Use conclusion-style titles and bounded claims.
6. Include explicit accuracy rules and prohibit invented content.

Prefer the heading `## Image-Generation Prompt`. Accept provider-specific
headings such as `## ChatGPT-Image Prompt` in existing decks; the source
contract must not otherwise depend on one image provider.

Run a prompt-only audit before rendering:

```bash
python "SKILL_DIR/scripts/audit_slide_assets.py" --prompts-dir "ASSET_DIR" --strict
```

Repair errors before continuing. Review warnings rather than weakening the
contract merely to silence them.

Build an ordered generation manifest:

```bash
python "SKILL_DIR/scripts/build_prompt_manifest.py" "ASSET_DIR" --output "ASSET_DIR/.oratordeck/PROMPT_MANIFEST.json" --overwrite
```

Use this manifest to keep each fenced image prompt, intended output path,
visible-text manifest, and source hash together.

## Phase 3: Generate And Inspect Slide Images

Use the available image-generation capability for every slide prompt. When
Codex provides the `imagegen` skill, read and follow it. Submit only the
self-contained `image_prompt` from the generation manifest, without silently
adding factual content.

Save each result as
`ASSET_DIR/generated-images/slide-NN_slug.png`, matching the prompt stem.
Generate one image per prompt. Do not reuse a stale image after its prompt
changes.

Inspect each image at original detail:

1. Confirm 16:9 composition and readable text.
2. Check title, labels, numbers, formulas, and citations against the quoted
   visible-text manifest.
3. Reject invented or omitted claims and visibly corrupted text.
4. Regenerate the individual slide when repair is needed.

If image generation is unavailable, finish and audit the prompt sources, state
the capability gap, and do not create placeholders that could be mistaken for
final slides.

Audit prompt/image coverage:

```bash
python "SKILL_DIR/scripts/audit_slide_assets.py" --prompts-dir "ASSET_DIR" --images-dir "ASSET_DIR/generated-images" --strict
```

## Phase 4: Derive Synchronized Speaker Notes

Read [speaker-note-patterns.md](references/speaker-note-patterns.md). Generate
`ASSET_DIR/SPEAKER_NOTES.md` from the ordered prompt sources, not from memory
and not only from the rendered images.

For each slide:

1. Create one `## Slide NN - Title` section.
2. Add exactly one `**Target time:** M:SS` field.
3. Write natural, directly speakable prose in visual reading order.
4. Reuse distinctive quoted visible wording as bold anchors.
5. Keep each bold anchor an exact substring of a visible label.
6. Explain relationships rather than mechanically announcing labels.
7. Balance per-slide times to the requested total duration.

At a normal presentation pace, reconnect to a visible anchor roughly every
10–15 seconds and avoid unanchored spans longer than about 40 words.

Run the full source audit:

```bash
python "SKILL_DIR/scripts/audit_slide_assets.py" --prompts-dir "ASSET_DIR" --notes "ASSET_DIR/SPEAKER_NOTES.md" --images-dir "ASSET_DIR/generated-images" --min-anchors 1 --max-gap-words 40 --wpm-min 110 --wpm-max 150 --strict
```

Perform a final human pass with bold formatting mentally removed. The speech
must remain coherent and confident.

## Phase 5: Verify And Deliver The Assets

Verify:

- prompt, note-section, and image counts agree;
- numbering is contiguous and filenames use matching stems;
- every generated image has been inspected at original detail;
- visible labels, numbers, formulas, and citations match the prompt manifest;
- every bold anchor is visible and legible in its corresponding image;
- the total target duration and per-slide speaking pace fit the user's request;
- the notes remain natural when bold formatting is removed;
- the final audit has no hidden errors or unreviewed warnings.

Report the asset directory, prompt count, image count, note-section count,
target duration, audit result, and any remaining review items. Do not produce
`SPEAKER_NOTES_TTS.txt`, audio, subtitles, or video as skill outputs.

## Preserve Source Integrity

Keep private presentation sources and generated media out of commits unless
the user explicitly wants them published. Never rewrite evidence solely to
improve visual symmetry, timing, or anchor density. Revise the authoritative
prompt before regenerating a changed slide or its narration. When downstream
media already exists, identify it as stale after an upstream asset changes.
