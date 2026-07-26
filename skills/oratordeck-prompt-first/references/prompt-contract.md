# Prompt-First Slide Contract

Read this reference when creating or substantially revising prompt sources.

## Source Invariants

- Keep one authoritative Markdown file per slide.
- Name it `slide-NN_slug.md` with contiguous one-based numbers.
- Make the prompt self-contained so it can be submitted without another slide.
- Derive claims, metrics, citations, and boundaries from identified evidence.
- Put every intended visible string exactly inside straight double quotes.
- Treat rendered images and speaker notes as derivatives. They may later feed
  OratorDeck's independent media workflow, but that workflow is not part of
  prompt-first authoring.

## Recommended File Shape

~~~~markdown
# Slide NN - Argumentative Title

**Presentation role:** Explain why this slide exists in the deck argument.

**Audience takeaway:** State the one conclusion the audience should retain.

## Image-Generation Prompt

```text
Create one formal presentation slide about <topic>.

CANVAS AND STYLE
- Landscape 16:9.
- Use a consistent palette, typography, and safe margins.
- No logos, watermarks, or invented citations.

TITLE - USE EXACTLY
"One conclusion-style title"

SUBTITLE - USE EXACTLY
"Optional clarifying subtitle"

COMPOSITION
Describe one dominant visual structure in reading order.

LEFT OR FIRST STAGE
"Exact visible label"
"Exact supporting line"

CENTER OR MECHANISM
"Exact visible mechanism"

RIGHT OR OUTPUT
"Exact visible output"

BOTTOM TAKEAWAY - USE EXACTLY
"Exact bounded conclusion"

ACCURACY RULES
- Do not overstate the evidence.
- Do not invent numbers, references, modules, or integrations.
- Render every visible label exactly as specified.
```
~~~~

`**Defense role:**` is an acceptable domain-specific alternative to
`**Presentation role:**`. Existing provider-specific prompt headings such as
`## ChatGPT-Image Prompt` are also accepted, but prefer the provider-neutral
heading for new decks.

## Argument Design

Give each slide one primary proposition. Use subordinate panels only to
support it.

Prefer:

- a problem-to-mechanism chain;
- a before-and-after comparison;
- a representation-and-readout diagram;
- a method pipeline;
- a result plus bounded interpretation;
- a synthesis hierarchy;
- a demonstrated-versus-future boundary.

Avoid:

- generic topic titles;
- dense prose copied from a source;
- unexplained acronyms or modules;
- several equal-weight stories on one slide;
- decorative evidence without an argumentative role;
- repeated summaries outside their relevant section.

## Visible-Text Manifest

Double-quote every visible title, subtitle, node, arrow label, heading, metric,
value, status, finding, boundary, and closing takeaway. Keep non-visible
generation instructions unquoted.

The manifest serves three purposes:

1. it constrains the image generator;
2. it supplies exact vocabulary for speaker-note anchors;
3. it makes prompt/narration alignment machine-auditable.

Long prose is hard for image models to render accurately. Prefer concise labels
and let speaker notes explain relationships and nuance.

## Visual Reading Order

Specify an explicit order:

1. opening proposition;
2. input, prior state, or problem;
3. mechanism or transformation;
4. comparison or evidence;
5. output, finding, or boundary.

Speaker notes must follow the same route. If the intended speech cannot map to
the composition, revise the prompt before writing notes.

## Cross-Slide Consistency

Define palette, typography, margin, title position, and recurring visual
grammar at deck level, then repeat enough of them in every self-contained
prompt. Keep slide-specific composition flexible.

Keep terminology, symbols, capitalization, units, and claim boundaries stable
across prompts. When a slide changes, review neighboring transitions and every
later slide that reuses its terminology.

## Claim Discipline

State what the slide must not imply. Distinguish demonstrated evidence,
assumptions, limitations, and future work. Never invent citations or numeric
results to make a slide look complete.

Use positive main text and place a narrow qualification wherever omitting it
would change the factual meaning.
