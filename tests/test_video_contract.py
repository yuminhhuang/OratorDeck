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


def test_anchor_text_boxes_locate_the_matched_words_not_the_underline() -> None:
    line = video.OCRLine(
        text="Alpha Beta",
        score=0.98,
        box=(100.0, 50.0, 300.0, 100.0),
        tokens=tuple(video.text_tokens("Alpha Beta")),
    )

    text_boxes = video.anchor_text_boxes(
        "Beta",
        [line],
        image_width=400,
        image_height=200,
    )
    underlines = video.underline_boxes(
        text_boxes,
        image_width=400,
        image_height=200,
        thickness=7,
    )

    assert text_boxes == [
        {
            "x": 220,
            "y": 50,
            "width": 80,
            "height": 50,
            "ocr_text": "Alpha Beta",
        }
    ]
    assert underlines == [
        {
            "x": 220,
            "y": 106,
            "width": 80,
            "height": 7,
            "ocr_text": "Alpha Beta",
        }
    ]


def test_animation_cues_preserve_order_and_normalize_multiline_geometry(
    tmp_path: Path,
) -> None:
    chunks_path = tmp_path / "chunks.json"
    chunks_path.write_text("{}\n", encoding="utf-8")
    image_path = tmp_path / "slide-01.png"
    image_path.write_bytes(b"synthetic slide")
    slide_plans = [
        {
            "id": "slide-01",
            "slide": 1,
            "title": "Opening",
            "image_path": str(image_path),
            "image_size": [400, 200],
            "anchors": [
                {
                    "id": "anchor-01",
                    "text": "First anchor",
                    "text_boxes": [
                        {"x": 100, "y": 50, "width": 80, "height": 50},
                        {"x": 20, "y": 110, "width": 200, "height": 40},
                    ],
                },
                {
                    "id": "anchor-02",
                    "text": "Missing anchor",
                    "text_boxes": [],
                },
            ],
        }
    ]

    cues = video.build_animation_cues(slide_plans, chunks_path, tmp_path)

    assert cues["format"] == "oratordeck.anchor-animation-cues.v1"
    assert cues["resolved_anchor_count"] == 1
    assert cues["unresolved_anchor_count"] == 1
    assert cues["slides"][0]["image_sha256"] == (
        "97b721553923ca0a1ada7d243f7ef4a2c9cf43214e3ab7c5e47207ad1bdd3d46"
    )
    anchors = cues["slides"][0]["anchors"]
    assert [anchor["appearance_order"] for anchor in anchors] == [1, 2]
    assert anchors[0]["position"] == {
        "x": 0.05,
        "y": 0.25,
        "width": 0.5,
        "height": 0.5,
        "center_x": 0.3,
        "center_y": 0.5,
    }
    assert anchors[0]["fragments"] == [
        {
            "x": 0.25,
            "y": 0.25,
            "width": 0.2,
            "height": 0.25,
            "center_x": 0.35,
            "center_y": 0.375,
        },
        {
            "x": 0.05,
            "y": 0.55,
            "width": 0.5,
            "height": 0.2,
            "center_x": 0.3,
            "center_y": 0.65,
        },
    ]
    assert anchors[1]["status"] == "unresolved"
    assert anchors[1]["position"] is None
    assert anchors[1]["fragments"] == []
