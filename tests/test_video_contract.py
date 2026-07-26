from __future__ import annotations

from pathlib import Path

import pytest

from oratordeck_verdict import anchoring
from tests.helpers import load_script

video = load_script("generate-keynote-video.py")


def test_video_reexports_the_shared_ocr_and_anchor_implementation() -> None:
    assert video.OCRLine is anchoring.OCRLine
    assert video.OCRCandidate is anchoring.OCRCandidate
    assert video.run_ocr is anchoring.run_ocr
    assert video.assign_ocr_anchors is anchoring.assign_ocr_anchors
    assert video.select_global_anchor_candidates is (
        anchoring.select_global_anchor_candidates
    )
    assert video.anchor_text_boxes is anchoring.anchor_text_boxes
    assert video.normalized_anchor_geometry is (
        anchoring.normalized_anchor_geometry
    )


def test_image_bound_ocr_results_round_trip_and_filter_confidence(
    tmp_path: Path,
) -> None:
    image = tmp_path / "slide-01.png"
    image.write_bytes(b"first image revision")
    line = anchoring.OCRLine(
        text="Reusable anchor",
        score=0.82,
        box=(10.0, 20.0, 150.0, 50.0),
        tokens=tuple(anchoring.text_tokens("Reusable anchor")),
    )
    low_line = anchoring.OCRLine(
        text="Low confidence",
        score=0.40,
        box=(10.0, 60.0, 120.0, 90.0),
        tokens=tuple(anchoring.text_tokens("Low confidence")),
    )
    images = {1: image}
    document = anchoring.build_ocr_results(
        images,
        {1: (400, 200)},
        {1: [line, low_line]},
    )

    loaded = anchoring.load_ocr_results(
        document,
        images,
        requested_confidence=0.55,
    )

    assert document["format"] == "oratordeck.ocr-results.v1"
    assert document["slides"][0]["image_sha256"] == (
        "ea848bef778838ffece5915c3c16eaccba3dc2c2d889df66cc93fba253acf9a5"
    )
    assert loaded == {1: [line]}


def test_ocr_results_reject_a_changed_slide_image(tmp_path: Path) -> None:
    image = tmp_path / "slide-01.png"
    image.write_bytes(b"first image revision")
    document = anchoring.build_ocr_results(
        {1: image},
        {1: (400, 200)},
        {1: []},
    )
    image.write_bytes(b"second image revision")

    with pytest.raises(RuntimeError, match="different image for slide 1"):
        anchoring.load_ocr_results(
            document,
            {1: image},
            requested_confidence=0.55,
        )


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
                    "ocr_status": "resolved",
                    "ocr_match_score": 0.95,
                    "ocr_anchor_coverage": 1.0,
                    "ocr_assignment_quality": 0.965,
                    "ocr_candidate_count": 1,
                    "ocr_candidate_margin": None,
                    "ocr_selected_candidate_rank": 1,
                    "ocr_assignment_changed": False,
                    "ocr_shared_with": [],
                    "ocr_unresolved_reason": None,
                    "timing_source": "subtitles",
                    "timing_match_score": 0.91,
                    "text_boxes": [
                        {"x": 100, "y": 50, "width": 80, "height": 50},
                        {"x": 20, "y": 110, "width": 200, "height": 40},
                    ],
                },
                {
                    "id": "anchor-02",
                    "text": "Missing anchor",
                    "ocr_status": "unresolved",
                    "ocr_match_score": None,
                    "ocr_anchor_coverage": None,
                    "ocr_assignment_quality": None,
                    "ocr_candidate_count": 0,
                    "ocr_candidate_margin": None,
                    "ocr_selected_candidate_rank": None,
                    "ocr_assignment_changed": False,
                    "ocr_shared_with": [],
                    "ocr_unresolved_reason": "no_candidate_above_threshold",
                    "timing_source": "proportional_text",
                    "timing_match_score": None,
                    "text_boxes": [],
                },
            ],
        }
    ]

    video.apply_anchor_verdicts(
        slide_plans,
        confidence_threshold=0.78,
        coverage_threshold=0.65,
        ambiguity_margin=0.04,
    )
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


def make_candidate(
    score: float,
    token_keys: set[tuple[int, int]],
    reading_position: float,
    coverage: float = 1.0,
) -> video.OCRCandidate:
    return video.OCRCandidate(
        start_line=0,
        end_line=1,
        score=score,
        anchor_coverage=coverage,
        token_keys=frozenset(token_keys),
        lines=(),
        reading_position=reading_position,
    )


def test_global_assignment_prevents_unrelated_anchors_reusing_tokens() -> None:
    shared_for_first = make_candidate(0.96, {(0, 0), (0, 1)}, 0.2)
    first_alternative = make_candidate(0.70, {(2, 0), (2, 1)}, 0.8)
    shared_for_second = make_candidate(0.95, {(0, 0), (0, 1)}, 0.2)
    second_alternative = make_candidate(0.90, {(1, 0), (1, 1)}, 0.5)

    selected = video.select_global_anchor_candidates(
        ["first concept", "different conclusion"],
        [
            [shared_for_first, first_alternative],
            [shared_for_second, second_alternative],
        ],
    )

    assert selected == [shared_for_first, second_alternative]


def test_global_assignment_allows_explicitly_nested_anchor_text() -> None:
    compact = make_candidate(0.98, {(0, 1), (0, 2)}, 0.3)
    containing = make_candidate(
        0.97,
        {(0, 0), (0, 1), (0, 2), (0, 3)},
        0.3,
    )

    selected = video.select_global_anchor_candidates(
        ["compact priors", "how compact priors work"],
        [[compact], [containing]],
    )

    assert selected == [compact, containing]


def test_global_assignment_prefers_anchor_coverage_over_partial_high_score() -> None:
    partial = make_candidate(
        0.96,
        {(0, 0)},
        0.2,
        coverage=0.2,
    )
    complete = make_candidate(
        0.86,
        {(1, 0), (1, 1), (1, 2)},
        0.6,
        coverage=1.0,
    )

    selected = video.select_global_anchor_candidates(
        ["complete visual phrase"],
        [[partial, complete]],
    )

    assert selected == [complete]


def test_anchor_verdict_html_is_a_self_contained_restricted_slide_editor(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "slide-01.png"
    video.Image.new("RGB", (400, 200), "white").save(image_path)
    slide_plans = [
        {
            "id": "slide-01",
            "slide": 1,
            "title": "Review & decide",
            "image_path": str(image_path),
            "image_size": [400, 200],
            "anchors": [
                {
                    "id": "anchor-01",
                    "text": "Clear anchor",
                    "ocr_status": "resolved",
                    "ocr_match_score": 0.95,
                    "ocr_anchor_coverage": 1.0,
                    "ocr_assignment_quality": 0.965,
                    "ocr_candidate_count": 1,
                    "ocr_candidate_margin": None,
                    "ocr_selected_candidate_rank": 1,
                    "ocr_assignment_changed": False,
                    "ocr_unresolved_reason": None,
                    "timing_source": "subtitles",
                    "timing_match_score": 0.92,
                    "text_boxes": [
                        {"x": 40, "y": 50, "width": 100, "height": 30}
                    ],
                },
                {
                    "id": "anchor-02",
                    "text": "Ambiguous anchor",
                    "ocr_status": "resolved",
                    "ocr_match_score": 0.72,
                    "ocr_anchor_coverage": 0.50,
                    "ocr_assignment_quality": 0.654,
                    "ocr_candidate_count": 2,
                    "ocr_candidate_margin": 0.01,
                    "ocr_selected_candidate_rank": 2,
                    "ocr_assignment_changed": True,
                    "ocr_unresolved_reason": None,
                    "timing_source": "proportional_text",
                    "timing_match_score": None,
                    "text_boxes": [
                        {"x": 180, "y": 90, "width": 120, "height": 30}
                    ],
                },
                {
                    "id": "anchor-03",
                    "text": "Missing anchor",
                    "ocr_status": "unresolved",
                    "ocr_match_score": None,
                    "ocr_anchor_coverage": None,
                    "ocr_assignment_quality": None,
                    "ocr_candidate_count": 0,
                    "ocr_candidate_margin": None,
                    "ocr_selected_candidate_rank": None,
                    "ocr_assignment_changed": False,
                    "ocr_unresolved_reason": "no_candidate_above_threshold",
                    "timing_source": "subtitles",
                    "timing_match_score": 0.88,
                    "text_boxes": [],
                },
            ],
        }
    ]

    summary = video.apply_anchor_verdicts(
        slide_plans,
        confidence_threshold=0.78,
        coverage_threshold=0.65,
        ambiguity_margin=0.04,
    )
    report = video.build_anchor_verdict_html(
        slide_plans,
        summary,
        confidence_threshold=0.78,
        coverage_threshold=0.65,
        ambiguity_margin=0.04,
        chunks_sha256="a" * 64,
        rerender_report_path=tmp_path / "anchor-video-report.json",
        python_executable=Path("/opt/oratordeck/python"),
        script_path=Path("/opt/oratordeck/generate-keynote-video.py"),
    )

    assert summary == {
        "pass": 1,
        "corrected": 0,
        "review": 1,
        "unresolved": 1,
        "slides_with_review_items": 1,
    }
    assert "data:image/jpeg;base64," in report
    assert "OratorDeck Deck Verdict" in report
    assert 'id="filmstrip"' in report
    assert "← Previous" in report
    assert "Next →" in report
    assert "Manuscript and anchors" in report
    assert "Drag inside the selected box to move it" in report
    assert "Selected rank" in report
    assert "Timing score" in report
    assert "Restore OCR box" in report
    assert "Post-TTS box-only mode." in report
    assert "saveReviewButton.hidden = true" in report
    assert "scriptInput.readOnly = true" in report
    assert 'id="reset-editor">Reset</button>' in report
    assert "Import review" not in report
    assert "Import box overrides" not in report
    assert "localStorage" not in report
    assert 'className = `handle ${edge}`' in report
    assert '["top","right","bottom","left"]' in report
    assert "Save box overrides" in report
    assert "showSaveFilePicker" not in report
    assert "new Blob" not in report
    assert "writeBoundState" in report
    assert "loadBoundState" in report
    assert "-m oratordeck_verdict edit" in report
    assert "Review \\u0026 decide" in report
    assert "Ambiguous anchor" in report
    assert "low_anchor_coverage" in report
    assert "global_reassignment" in report
    assert "no_candidate_above_threshold" in report
    assert "--rerender-from-report" in report
    assert "If manuscript or anchors changed" not in report
    assert '"format":"oratordeck.deck-review.v1"' in report
    assert '"mode":"anchor-overrides"' in report


def override_source(slide_plans: list[dict], chunks_sha256: str) -> dict:
    return video.anchor_override_source(slide_plans, chunks_sha256)


def make_override_slide(tmp_path: Path) -> tuple[Path, list[dict]]:
    image_path = tmp_path / "slide-01.png"
    video.Image.new("RGB", (400, 200), "white").save(image_path)
    return image_path, [
        {
            "id": "slide-01",
            "slide": 1,
            "title": "Correction",
            "image_path": str(image_path),
            "image_size": [400, 200],
            "anchors": [
                {
                    "id": "anchor-01",
                    "text": "Correct me",
                    "ocr_status": "resolved",
                    "ocr_match_score": 0.7,
                    "ocr_anchor_coverage": 0.5,
                    "ocr_assignment_quality": 0.64,
                    "ocr_candidate_count": 2,
                    "ocr_candidate_margin": 0.01,
                    "ocr_selected_candidate_rank": 1,
                    "ocr_assignment_changed": False,
                    "ocr_shared_with": [],
                    "ocr_unresolved_reason": None,
                    "timing_source": "subtitles",
                    "timing_match_score": 0.9,
                    "manual_override": None,
                    "source_geometry_out_of_bounds": False,
                    "auto_text_boxes": [
                        {"x": 20, "y": 20, "width": 80, "height": 20}
                    ],
                    "text_boxes": [
                        {"x": 20, "y": 20, "width": 80, "height": 20}
                    ],
                    "underline_boxes": [],
                    "ocr_candidates": [],
                }
            ],
        }
    ]


def test_anchor_override_replaces_geometry_and_becomes_renderable(
    tmp_path: Path,
) -> None:
    _, slide_plans = make_override_slide(tmp_path)
    chunks_sha256 = "b" * 64
    document = {
        "format": video.ANCHOR_OVERRIDES_FORMAT,
        "source": override_source(slide_plans, chunks_sha256),
        "overrides": [
            {
                "slide": 1,
                "anchor_id": "anchor-01",
                "anchor_text": "Correct me",
                "action": "set",
                "fragments": [
                    {"x": 0.5, "y": 0.25, "width": 0.25, "height": 0.2}
                ],
                "selection": {"kind": "candidate", "rank": 2},
            }
        ],
    }

    result = video.apply_anchor_overrides(
        slide_plans,
        document,
        chunks_sha256,
        underline_thickness=7,
    )
    video.annotate_anchor_geometry(slide_plans)
    verdict = video.apply_anchor_verdicts(
        slide_plans,
        confidence_threshold=0.78,
        coverage_threshold=0.65,
        ambiguity_margin=0.04,
    )

    anchor = slide_plans[0]["anchors"][0]
    assert result == {"total": 1, "set": 1, "suppress": 0}
    assert anchor["text_boxes"] == [
        {
            "x": 200,
            "y": 50,
            "width": 100,
            "height": 40,
            "ocr_text": "Manual override for Correct me",
        }
    ]
    assert anchor["underline_boxes"] == [
        {
            "x": 200,
            "y": 95,
            "width": 100,
            "height": 7,
            "ocr_text": "Manual override for Correct me",
        }
    ]
    assert anchor["manual_override"]["selection"] == {
        "kind": "candidate",
        "rank": 2,
    }
    assert anchor["verdict"] == "corrected"
    assert verdict["corrected"] == 1


def test_anchor_override_can_suppress_an_underline(tmp_path: Path) -> None:
    _, slide_plans = make_override_slide(tmp_path)
    chunks_sha256 = "c" * 64
    document = {
        "format": video.ANCHOR_OVERRIDES_FORMAT,
        "source": override_source(slide_plans, chunks_sha256),
        "overrides": [
            {
                "slide": 1,
                "anchor_id": "anchor-01",
                "action": "suppress",
                "fragments": [],
            }
        ],
    }

    result = video.apply_anchor_overrides(
        slide_plans,
        document,
        chunks_sha256,
        underline_thickness=7,
    )

    anchor = slide_plans[0]["anchors"][0]
    assert result == {"total": 1, "set": 0, "suppress": 1}
    assert anchor["ocr_status"] == "suppressed"
    assert anchor["text_boxes"] == []
    assert anchor["underline_boxes"] == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"chunks_sha256": "wrong"}, "different speaker-note"),
        (
            {
                "fragments": [
                    {"x": 0.9, "y": 0.2, "width": 0.2, "height": 0.1}
                ]
            },
            "outside normalized slide bounds",
        ),
    ],
)
def test_anchor_override_rejects_stale_or_out_of_bounds_data(
    tmp_path: Path,
    change: dict,
    message: str,
) -> None:
    _, slide_plans = make_override_slide(tmp_path)
    chunks_sha256 = "d" * 64
    document = {
        "format": video.ANCHOR_OVERRIDES_FORMAT,
        "source": override_source(slide_plans, chunks_sha256),
        "overrides": [
            {
                "slide": 1,
                "anchor_id": "anchor-01",
                "action": "set",
                "fragments": [
                    {"x": 0.2, "y": 0.2, "width": 0.2, "height": 0.1}
                ],
            }
        ],
    }
    if "chunks_sha256" in change:
        document["source"]["chunks_sha256"] = change["chunks_sha256"]
    if "fragments" in change:
        document["overrides"][0]["fragments"] = change["fragments"]

    with pytest.raises(RuntimeError, match=message):
        video.apply_anchor_overrides(
            slide_plans,
            document,
            chunks_sha256,
            underline_thickness=7,
        )


def test_verdict_flags_unexpected_overlap_and_out_of_bounds_geometry(
    tmp_path: Path,
) -> None:
    _, slide_plans = make_override_slide(tmp_path)
    first = slide_plans[0]["anchors"][0]
    second = {
        **first,
        "id": "anchor-02",
        "text": "A different concept",
        "text_boxes": [{"x": 30, "y": 20, "width": 80, "height": 20}],
        "auto_text_boxes": [{"x": 30, "y": 20, "width": 80, "height": 20}],
    }
    first["text_boxes"] = [{"x": 390, "y": 20, "width": 20, "height": 20}]
    first["auto_text_boxes"] = list(first["text_boxes"])
    second["text_boxes"] = [{"x": 385, "y": 20, "width": 20, "height": 20}]
    second["auto_text_boxes"] = list(second["text_boxes"])
    slide_plans[0]["anchors"].append(second)

    video.annotate_anchor_geometry(slide_plans, overlap_threshold=0.2)
    video.apply_anchor_verdicts(
        slide_plans,
        confidence_threshold=0.6,
        coverage_threshold=0.4,
        ambiguity_margin=0.0,
    )

    assert first["geometry_out_of_bounds"] is True
    assert first["geometry_overlaps_with"] == ["anchor-02"]
    assert "out_of_bounds_geometry" in first["review_reasons"]
    assert "overlapping_anchor_geometry" in first["review_reasons"]
    assert second["geometry_overlaps_with"] == ["anchor-01"]


def test_rerender_report_restores_inputs_outputs_and_render_settings(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "video" / "anchor-video-report.json"
    report_path.parent.mkdir()
    report = {
        "format": video.REPORT_FORMAT,
        "chunks_file": str(tmp_path / "chunks.json"),
        "timing_report": str(tmp_path / "timing.json"),
        "images_dir": str(tmp_path / "images"),
        "subtitles": str(tmp_path / "talk.srt"),
        "ocr_results": str(tmp_path / "deck-ocr.json"),
        "output_video": str(report_path.parent / "talk.mp4"),
        "anchor_animation_cues": str(
            report_path.parent / "anchor-animation-cues.json"
        ),
        "anchor_verdict": str(report_path.parent / "anchor-verdict.html"),
        "fps": 24,
        "underline_thickness": 9,
        "limit": 3,
    }
    video.write_json(report_path, report)
    args = video.argparse.Namespace(
        rerender_from_report=report_path,
        chunks_file=None,
        timing_report=None,
        images_dir=None,
    )

    video.hydrate_rerender_args(args)

    assert args.chunks_file == tmp_path / "chunks.json"
    assert args.timing_report == tmp_path / "timing.json"
    assert args.images_dir == tmp_path / "images"
    assert args.subtitles == tmp_path / "talk.srt"
    assert args.ocr_results == tmp_path / "deck-ocr.json"
    assert args.output == report_path.parent / "talk.mp4"
    assert args.work_dir == report_path.parent
    assert args.fps == 24
    assert args.underline_thickness == 9
    assert args.limit == 3
