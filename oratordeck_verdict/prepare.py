"""Prepare the pre-TTS OratorDeck slide/manuscript verdict editor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

from . import anchoring, notes
from .editor import (
    build_deck_review_html,
    script_with_bold_anchors,
    slide_data_uri,
)


def review_verdict(candidate, assignment: dict) -> tuple[str, list[str]]:
    if candidate is None:
        return "unresolved", [
            assignment["unresolved_reason"] or "no_candidate_above_threshold"
        ]
    reasons = []
    if candidate.score < 0.78:
        reasons.append("low_ocr_confidence")
    if candidate.anchor_coverage < 0.65:
        reasons.append("low_anchor_coverage")
    if assignment["assignment_changed"]:
        reasons.append("global_reassignment")
    return ("review" if reasons else "pass"), reasons


def validate_slide_image_set(
    chunks_document: dict,
    images: dict[int, Path],
) -> None:
    expected = {chunk["slide"] for chunk in chunks_document["chunks"]}
    actual = set(images)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(
                "missing " + ", ".join(f"slide-{slide:02d}" for slide in missing)
            )
        if extra:
            details.append(
                "extra " + ", ".join(f"slide-{slide:02d}" for slide in extra)
            )
        raise RuntimeError(
            "Speaker notes and slide-image set do not match: "
            + "; ".join(details)
        )


def build_review_artifacts(
    speaker_notes: Path,
    images_dir: Path,
    verdict_output: Path,
    review_json: Path,
    ocr_output: Path,
    ocr_confidence: float,
    ocr_match_threshold: float,
) -> tuple[dict, dict]:
    from rapidocr import RapidOCR

    python_executable = Path(sys.executable).resolve()
    chunks_document = notes.format_speaker_notes(speaker_notes)
    images = anchoring.discover_images(images_dir)
    validate_slide_image_set(chunks_document, images)
    source_text = speaker_notes.read_text(encoding="utf-8")
    first_heading = notes.SLIDE_HEADING_RE.search(source_text)
    preamble = (
        source_text[: first_heading.start()].rstrip() + "\n"
        if first_heading
        else ""
    )
    ocr_engine = RapidOCR()
    slides = []
    image_sizes = {}
    raw_ocr_lines_by_slide = {}
    for index, chunk in enumerate(chunks_document["chunks"], start=1):
        slide = chunk["slide"]
        image_path = images.get(slide)
        if image_path is None:
            raise RuntimeError(f"No image found for slide {slide}")
        with Image.open(image_path) as image:
            image_width, image_height = image.size
        image_sizes[slide] = (image_width, image_height)
        raw_ocr_lines = anchoring.run_ocr(
            ocr_engine,
            image_path,
            0.0,
        )
        raw_ocr_lines_by_slide[slide] = raw_ocr_lines
        ocr_lines = anchoring.filter_ocr_lines(
            raw_ocr_lines,
            ocr_confidence,
        )
        assignments = anchoring.assign_ocr_anchors(
            chunk["anchors"],
            ocr_lines,
            ocr_match_threshold,
        )
        anchors = []
        for anchor, assignment in zip(
            chunk["anchors"],
            assignments,
            strict=True,
        ):
            candidate = assignment["candidate"]
            if candidate is None:
                box = None
            else:
                text_boxes = anchoring.anchor_text_boxes(
                    anchor["text"],
                    list(candidate.lines),
                    image_width,
                    image_height,
                )
                box, _ = anchoring.normalized_anchor_geometry(
                    text_boxes,
                    image_width,
                    image_height,
                )
            verdict, reasons = review_verdict(candidate, assignment)
            anchors.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "box": box,
                    "automatic_box": box,
                    "box_source": "auto" if box else "unresolved",
                    "verdict": verdict,
                    "review_reasons": reasons,
                    "diagnostics": {
                        "ocr_score": (
                            round(candidate.score, 6) if candidate else None
                        ),
                        "anchor_coverage": (
                            round(candidate.anchor_coverage, 6)
                            if candidate
                            else None
                        ),
                        "candidate_count": assignment["candidate_count"],
                        "selected_candidate_rank": assignment["selected_rank"],
                    },
                }
            )
        slides.append(
            {
                "id": chunk["id"],
                "slide": slide,
                "title": chunk["title"],
                "target_time": chunk["target_time"],
                "script_markdown": script_with_bold_anchors(
                    chunk["text"],
                    chunk["anchors"],
                ),
                "original_title": chunk["title"],
                "original_target_time": chunk["target_time"],
                "original_script_markdown": script_with_bold_anchors(
                    chunk["text"],
                    chunk["anchors"],
                ),
                "image_path": str(image_path),
                "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "image_data_uri": slide_data_uri(image_path),
                "anchors": anchors,
            }
        )
        resolved = sum(anchor["box"] is not None for anchor in anchors)
        print(
            f"[{index:02d}/{len(chunks_document['chunks']):02d}] "
            f"{chunk['id']}: OCR {resolved}/{len(anchors)} anchors",
            flush=True,
        )

    source = {
        "speaker_notes_name": speaker_notes.name,
        "speaker_notes_sha256": hashlib.sha256(
            speaker_notes.read_bytes()
        ).hexdigest(),
        "images": [
            {
                "slide": slide["slide"],
                "sha256": slide["image_sha256"],
            }
            for slide in slides
        ],
    }
    reviewed_dir = review_json.parent / "reviewed"
    apply_command = (
        f'"{python_executable}" -m oratordeck_verdict apply '
        f'"{review_json}" "{speaker_notes}" "{images_dir}" '
        f'--ocr-results "{ocr_output}" '
        f'--output-dir "{reviewed_dir}" --overwrite'
    )
    edit_command = (
        f'"{python_executable}" -m oratordeck_verdict edit '
        f'"{verdict_output}" "{review_json}"'
    )
    commands = [
        ("Open the state-bound editor", edit_command),
        ("Apply the review directly", apply_command),
    ]
    workflow = Path.cwd() / "scripts" / "generate-keynote-workflow.sh"
    if workflow.is_file():
        commands.append(
            (
                "Or run the complete media workflow",
                str(workflow),
            )
        )
    payload = {
        "title": "OratorDeck Pre-TTS Deck Verdict",
        "source": source,
        "preamble": preamble,
        "slides": slides,
        "config": {
            "mode": "deck-review",
            "review_filename": review_json.name,
            "override_filename": "anchor-overrides.json",
            "allow_override_export": False,
            "override_source": None,
        },
        "commands": commands,
    }
    ocr_results = anchoring.build_ocr_results(
        images,
        image_sizes,
        raw_ocr_lines_by_slide,
        stored_line_min_score=0.0,
    )
    return payload, ocr_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "speaker_notes",
        nargs="?",
        type=Path,
        default=Path("resources/SPEAKER_NOTES.md"),
    )
    parser.add_argument(
        "images_dir",
        nargs="?",
        type=Path,
        default=Path("resources/generated-images"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("resources/.oratordeck/deck-verdict.html"),
    )
    parser.add_argument(
        "--review-json",
        type=Path,
        default=Path("resources/.oratordeck/deck-review.json"),
        help="Where the browser should save its review JSON",
    )
    parser.add_argument(
        "--ocr-output",
        type=Path,
        default=Path("resources/.oratordeck/deck-ocr.json"),
        help="Reusable image-bound OCR results for the video stage",
    )
    parser.add_argument("--ocr-confidence", type=float, default=0.55)
    parser.add_argument("--ocr-match-threshold", type=float, default=0.64)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def prepare_deck(
    speaker_notes: Path,
    images_dir: Path,
    output: Path,
    review_json: Path,
    ocr_output: Path,
    *,
    ocr_confidence: float = 0.55,
    ocr_match_threshold: float = 0.64,
    overwrite: bool = False,
) -> None:
    speaker_notes = speaker_notes.resolve()
    images_dir = images_dir.resolve()
    output = output.resolve()
    review_json = review_json.resolve()
    ocr_output = ocr_output.resolve()
    for option, value in (
        ("ocr-confidence", ocr_confidence),
        ("ocr-match-threshold", ocr_match_threshold),
    ):
        if not 0 <= value <= 1:
            raise RuntimeError(f"--{option} must be between 0 and 1")
    if output == ocr_output:
        raise RuntimeError("Deck Verdict HTML and OCR results must be distinct")
    existing = [
        path
        for path in (output, ocr_output)
        if path.exists()
    ]
    if existing and not overwrite:
        raise RuntimeError(
            f"Output already exists: {', '.join(str(path) for path in existing)}; "
            "pass --overwrite"
        )
    payload, ocr_results = build_review_artifacts(
        speaker_notes,
        images_dir,
        output,
        review_json,
        ocr_output,
        ocr_confidence,
        ocr_match_threshold,
    )
    contents = (
        build_deck_review_html(payload),
        json.dumps(ocr_results, ensure_ascii=False, indent=2) + "\n",
    )
    output_paths = (output, ocr_output)
    temporary_paths = []
    for path, content in zip(output_paths, contents, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary_paths.append(temporary)
    for temporary, path in zip(
        temporary_paths,
        output_paths,
        strict=True,
    ):
        temporary.replace(path)
    print(f"Deck verdict: {output}")
    print(f"Reusable OCR results: {ocr_output}")
    python_executable = Path(sys.executable).resolve()
    print(
        "Open the state-bound editor:\n"
        f'  "{python_executable}" -m oratordeck_verdict edit '
        f'"{output}" "{review_json}"'
    )


def main() -> int:
    args = parse_args()
    prepare_deck(
        args.speaker_notes,
        args.images_dir,
        args.output,
        args.review_json,
        args.ocr_output,
        ocr_confidence=args.ocr_confidence,
        ocr_match_threshold=args.ocr_match_threshold,
        overwrite=args.overwrite,
    )
    return 0
