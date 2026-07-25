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
