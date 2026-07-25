from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import load_script

formatter = load_script("format-speaker-notes-chunks.py")


def write_notes(path: Path, second_slide: int = 2) -> None:
    path.write_text(
        f"""# Synthetic notes

## Slide 01 - Opening

**Target time:** 0:20

Introduce the **central question** clearly.

## Slide {second_slide:02d} - Result

**Target time:** 0:30

Finish with the **practical result**.
""",
        encoding="utf-8",
    )


def test_formats_slide_atomic_chunks_and_anchor_offsets(tmp_path: Path) -> None:
    source = tmp_path / "SPEAKER_NOTES.md"
    write_notes(source)

    document = formatter.format_speaker_notes(source)

    assert document["format"] == "oratordeck.speaker-notes-chunks.v1"
    assert document["chunk_count"] == 2
    assert document["total_target_seconds"] == 50
    assert [chunk["id"] for chunk in document["chunks"]] == ["slide-01", "slide-02"]

    first = document["chunks"][0]
    anchor = first["anchors"][0]
    assert anchor["text"] == "central question"
    assert first["text"][anchor["start_char"] : anchor["end_char"]] == anchor["text"]
    assert "**" not in first["text"]


def test_rejects_noncontiguous_slide_numbers(tmp_path: Path) -> None:
    source = tmp_path / "SPEAKER_NOTES.md"
    write_notes(source, second_slide=3)

    with pytest.raises(RuntimeError, match="contiguous"):
        formatter.format_speaker_notes(source)
