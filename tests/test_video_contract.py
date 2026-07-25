from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import load_script

video = load_script("generate-keynote-video.py")


def test_proportional_anchor_interval_uses_spoken_position() -> None:
    text = "First establish context, then align the anchors, and finally render."
    start = text.index("align the anchors")
    anchor = {
        "text": "align the anchors",
        "start_char": start,
        "end_char": start + len("align the anchors"),
    }

    interval = video.proportional_anchor_interval(anchor, text, duration=20.0)

    assert 0 < interval[0] < interval[1] < 20.0


def test_image_discovery_requires_one_image_per_slide(tmp_path: Path) -> None:
    first = tmp_path / "slide-01-opening.png"
    second = tmp_path / "slide-02_result.webp"
    first.touch()
    second.touch()

    discovered = video.discover_images(tmp_path)

    assert discovered == {1: first.resolve(), 2: second.resolve()}

    (tmp_path / "slide-01-duplicate.jpg").touch()
    with pytest.raises(RuntimeError, match="Multiple images"):
        video.discover_images(tmp_path)
