# Contributing

Thank you for helping improve OratorDeck.

## Development setup

Use Python 3.11 and install the development dependencies:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the local checks before opening a pull request:

```bash
./.venv/bin/python -m pytest
./.venv/bin/python -m ruff check scripts tests
bash -n scripts/*.sh
```

The Voicebox patch can be checked against its pinned upstream commit with:

```bash
scripts/check-voicebox-patch.sh
```

## Pull requests

- Keep slide narration indivisible throughout TTS generation.
- Preserve stable ordering and explicit hashes in generated manifests.
- Add or update tests for behavior changes.
- Keep model weights, caches, generated media, private speaker notes, slide
  images, local paths, voice-profile identifiers, and benchmark artifacts out
  of commits.
- Document new runtime dependencies in `THIRD_PARTY_NOTICES.md`.
- Never add a voice sample without documented consent and redistribution
  permission.

Bug reports should include the failing command, relevant tool versions, and a
minimal synthetic input. Do not attach confidential presentations or voices.
