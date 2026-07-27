# Synchronized Speaker-Note Patterns

Read this reference before deriving or substantially revising
`resources/SPEAKER_NOTES.md`.

## Derivation Procedure

For each Prompt-as-Slide (PasS) source:

1. Extract the double-quoted visible strings from its fenced prompt.
2. Identify the visual reading order.
3. Group labels into opening, mechanism, evidence, and conclusion.
4. Write natural read-aloud prose that explains their relationships.
5. Bold only shared wording that should reconnect speech to the screen.
6. Assign a target time consistent with the whole-deck duration.
7. Audit, then listen mentally with bold formatting removed.

Do not draft a generic speech and insert labels afterward. Let the PasS
prompt's visible vocabulary shape the prose from the beginning.

## Required Speaker-Note Shape

```markdown
## Slide 01 - Opening proposition

**Target time:** 0:45

Begin with natural narration. Connect the problem to a visible
**decision boundary**, explain the mechanism, and close on the
**bounded conclusion**.
```

Use one section and exactly one target-time field per slide. Slide numbers must
be contiguous and agree with prompt and image filenames.

## Anchor Placement

Use anchors for:

- the conclusion-style title;
- the first major input, problem, or contrast;
- each branch or stage transition;
- the principal representation or mechanism;
- headline numbers and metric names;
- the bounded finding or transition.

For dense slides, several short anchors work better than one long verbatim
block. Sparse title slides may use fewer.

Every bold phrase intended for annotation must be an exact substring of one
double-quoted visible label. Prefer a short distinctive substring that OCR can
locate. Keep punctuation, articles, conjunctions, and inflections outside the
bold span when that improves the literal match.

## Natural Integration

Mechanical:

> The slide shows **Route-grounding ambiguity**.

Natural:

> The resulting **Route-grounding ambiguity** is which locally feasible
> structure realizes the coarse route.

Mechanical:

> The exact question is **Where do alternatives live?**

Natural:

> The central question is **Where do alternatives live?**

Mechanical:

> Under "Finding 2," omitted detail matters.

Natural:

> The second result is that **omitted detail matters through the decision**.

The speech must sound coherent if all bold formatting is removed.

## Density And Timing

At roughly 120–145 spoken words per minute:

- reconnect about every 10–15 seconds;
- avoid unanchored spans longer than about 40 words;
- include at least one anchor per major visual element;
- avoid consecutive decorative anchors that do not move visual attention.

Balance time by visual and argumentative density instead of assigning every
slide the same duration. Keep the whole-deck target explicit. Treat each target
as an authorial speaking-time estimate, not a guarantee about later speech
synthesis.

## OCR-Aware Wording

Avoid using an entire long sentence as one anchor. Prefer visible phrases with
clear alphanumeric words. For table-style labels, formulas, or punctuation-heavy
text, anchor a shorter stable substring. Do not bold a label that the image
generator failed to render.

After image generation, compare each planned anchor against the actual image.
Regenerate corrupted visible text or revise the prompt and all derivatives.

## Revision Propagation

When a prompt changes:

1. diff visible strings, order, claims, and metrics;
2. regenerate the corresponding image;
3. update its note section;
4. update adjacent transitions if the argumentative role changed;
5. rerun the whole-deck audit;
6. identify any existing downstream media as stale.

Do not keep a stale anchor merely because the old wording sounded good.
