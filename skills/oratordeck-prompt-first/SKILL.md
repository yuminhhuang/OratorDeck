---
name: oratordeck-prompt-first
description: Create end-to-end prompt-first OratorDeck presentations by helping users define self-contained Markdown slide prompts, generating one aligned slide image per prompt, deriving synchronized speaker notes with timed visual anchors, auditing the resulting deck, and running OratorDeck's existing TTS, subtitle, annotation, and video workflow. Use when a user wants to design slides from prompts, turn prepared slide prompts into images or narration, keep slide visuals and speech aligned, revise a prompt-defined deck, or produce a narrated presentation video from prompt sources.
---

# OratorDeck Prompt-First

Treat each Markdown slide prompt as source code. Treat slide images, speaker
notes, audio, subtitles, and video as derivatives of those prompt sources.

## Locate OratorDeck

Find the repository root by locating both
`scripts/generate-keynote-workflow.sh` and
`scripts/format-speaker-notes-chunks.py`. Run repository commands from that
root. Do not assume the skill is installed inside the repository.

Inspect `README.md`, `docs/installation.md`, the workflow script, and any
existing `resources/slide-*.md` before changing files. Preserve unrelated and
ignored user materials.

## Select The Requested Scope

- **Design only:** create or revise prompt sources and audit them.
- **Generate assets:** create slide images and synchronized speaker notes from
  existing prompts, then audit both.
- **Produce video:** complete the assets and run the full OratorDeck workflow.
- **Revise:** edit authoritative prompts first, then regenerate every affected
  derivative and adjacent narration transition.

Continue through all phases implied by the request. Do not run TTS or render a
video when the user asked only for design.

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

Create one `resources/slide-NN_slug.md` file per slide, with contiguous
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
./.venv/bin/python \
  <skill-dir>/scripts/audit_prompt_first_deck.py \
  --prompts-dir resources \
  --strict
```

Repair errors before continuing. Review warnings rather than weakening the
contract merely to silence them.

Build an ordered generation manifest:

```bash
./.venv/bin/python \
  <skill-dir>/scripts/build_prompt_manifest.py \
  resources \
  --output .tmp/prompt-first/PROMPT_MANIFEST.json \
  --overwrite
```

Use this manifest to keep each fenced image prompt, intended output path,
visible-text manifest, and source hash together.

## Phase 3: Generate And Inspect Slide Images

Use the available image-generation capability for every slide prompt. When
Codex provides the `imagegen` skill, read and follow it. Submit only the
self-contained `image_prompt` from the generation manifest, without silently
adding factual content.

Save each result as
`resources/generated-images/slide-NN_slug.png`, matching the prompt stem.
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
./.venv/bin/python \
  <skill-dir>/scripts/audit_prompt_first_deck.py \
  --prompts-dir resources \
  --images-dir resources/generated-images \
  --strict
```

## Phase 4: Derive Synchronized Speaker Notes

Read [speaker-note-patterns.md](references/speaker-note-patterns.md). Generate
`resources/SPEAKER_NOTES.md` from the ordered prompt sources, not from memory
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
./.venv/bin/python \
  <skill-dir>/scripts/audit_prompt_first_deck.py \
  --prompts-dir resources \
  --notes resources/SPEAKER_NOTES.md \
  --images-dir resources/generated-images \
  --min-anchors 5 \
  --max-gap-words 40 \
  --wpm-min 110 \
  --wpm-max 150 \
  --strict
```

Perform a final human pass with bold formatting mentally removed. The speech
must remain coherent and confident.

## Phase 5: Hand Off To OratorDeck

Read [oratordeck-handoff.md](references/oratordeck-handoff.md) before running
the media pipeline.

Validate slide-atomic chunking first:

```bash
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  resources/SPEAKER_NOTES.md \
  --output .tmp/prompt-first/SPEAKER_NOTES_CHUNKS.json \
  --tts-output .tmp/prompt-first/SPEAKER_NOTES_TTS.txt
```

Inspect `scripts/generate-keynote-workflow.sh`, then set its transparent
playground values for the user's run: run name, Voicebox profile, GPU, batch
size, timing tolerance, and any input paths. Keep generated artifacts under
the timestamped `data/runs/` directory.

For a full production request, ensure Voicebox is healthy and the requested
profile exists, then run:

```bash
scripts/generate-keynote-workflow.sh
```

Monitor it through TTS, transcription, OCR, all per-slide renders, and final
concatenation. Do not treat a partial run or a merely existing MP4 as success.

## Phase 6: Verify The Delivery

Verify:

- prompt, note, image, per-slide WAV, and per-slide clip counts agree;
- the timing report and anchor report both say `completed`;
- the final WAV, subtitles, and MP4 have nearly equal end times;
- the MP4 contains H.264 video and AAC audio;
- unresolved OCR anchors are reported rather than concealed;
- the workflow log has no traceback, out-of-memory failure, or aborted stage.

Report the final MP4, WAV, subtitles, timing report, anchor report, and workflow
log. Also report target-versus-actual duration and anchor resolution counts.

## Preserve Source Integrity

Keep private presentation sources and generated media out of commits unless
the user explicitly wants them published. Never rewrite evidence solely to
improve visual symmetry, timing, or anchor density. Revise the authoritative
prompt before regenerating a changed slide or its narration.
