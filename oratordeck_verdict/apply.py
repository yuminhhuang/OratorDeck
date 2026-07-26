"""Apply a deck review before TTS and emit all downstream text/anchor inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from . import anchoring, notes

DECK_REVIEW_FORMAT = "oratordeck.deck-review.v1"
ANCHOR_OVERRIDES_FORMAT = "oratordeck.anchor-overrides.v1"
IMAGE_RE = re.compile(
    r"^slide-(\d+)(?:[_-].*)?\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)


def discover_image_hashes(images_dir: Path) -> dict[int, str]:
    hashes = {}
    for path in images_dir.iterdir():
        match = IMAGE_RE.match(path.name)
        if not match:
            continue
        slide = int(match.group(1))
        if slide in hashes:
            raise RuntimeError(f"Multiple images found for slide {slide}")
        hashes[slide] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hashes:
        raise RuntimeError(f"No slide-NN images found in {images_dir}")
    return hashes


def validate_box(box: object, label: str) -> dict[str, float]:
    if not isinstance(box, dict):
        raise RuntimeError(f"{label} must be a bounding-box object")
    values = {}
    for field in ("x", "y", "width", "height"):
        value = box.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise RuntimeError(f"{label}.{field} must be a finite number")
        values[field] = float(value)
    if (
        values["x"] < 0
        or values["y"] < 0
        or values["width"] <= 0
        or values["height"] <= 0
        or values["x"] + values["width"] > 1.000001
        or values["y"] + values["height"] > 1.000001
    ):
        raise RuntimeError(f"{label} is outside normalized slide bounds")
    return {
        field: round(values[field], 6)
        for field in ("x", "y", "width", "height")
    }


def review_markdown(review: dict) -> str:
    preamble = review.get("preamble", "")
    if not isinstance(preamble, str):
        raise RuntimeError("Review preamble must be a string")
    slides = review.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RuntimeError("Deck review contains no slides")
    parts = [preamble.rstrip()] if preamble.strip() else ["# Reviewed Speaker Notes"]
    expected_slide = None
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise RuntimeError(f"Review slide {index} must be an object")
        slide_number = slide.get("slide")
        slide_id = slide.get("id")
        title = slide.get("title")
        target_time = slide.get("target_time")
        script = slide.get("script_markdown")
        if (
            isinstance(slide_number, bool)
            or not isinstance(slide_number, int)
            or slide_id != f"slide-{slide_number:02d}"
        ):
            raise RuntimeError(f"Review slide {index} has invalid identity")
        if expected_slide is None:
            expected_slide = slide_number
        if slide_number != expected_slide:
            raise RuntimeError("Reviewed slides must remain contiguous and ordered")
        expected_slide += 1
        if not isinstance(title, str) or not title.strip() or "\n" in title:
            raise RuntimeError(f"{slide_id} has an invalid title")
        if not isinstance(target_time, str) or not re.fullmatch(
            r"\d+:\d{2}",
            target_time,
        ):
            raise RuntimeError(f"{slide_id} target_time must be M:SS")
        minutes, seconds = map(int, target_time.split(":"))
        if seconds >= 60 or minutes * 60 + seconds <= 0:
            raise RuntimeError(f"{slide_id} target_time is invalid")
        if not isinstance(script, str) or not script.strip():
            raise RuntimeError(f"{slide_id} has an empty manuscript")
        parts.extend(
            [
                f"## Slide {slide_number:02d} - {title.strip()}",
                f"**Target time:** {target_time}",
                script.strip(),
            ]
        )
    return "\n\n".join(parts).rstrip() + "\n"


def validate_source(
    review: dict,
    speaker_notes: Path,
    images_dir: Path,
) -> dict[int, str]:
    source = review.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Deck review has no source fingerprints")
    actual_notes_hash = hashlib.sha256(speaker_notes.read_bytes()).hexdigest()
    if source.get("speaker_notes_sha256") != actual_notes_hash:
        raise RuntimeError("Deck review belongs to a different speaker-notes file")
    source_images = source.get("images")
    if not isinstance(source_images, list):
        raise RuntimeError("Deck review source.images must be a list")
    expected_hashes = {}
    for index, item in enumerate(source_images):
        if not isinstance(item, dict):
            raise RuntimeError(f"source.images[{index}] must be an object")
        slide = item.get("slide")
        digest = item.get("sha256")
        if (
            isinstance(slide, bool)
            or not isinstance(slide, int)
            or not isinstance(digest, str)
            or slide in expected_hashes
        ):
            raise RuntimeError(f"source.images[{index}] is invalid")
        expected_hashes[slide] = digest
    actual_hashes = discover_image_hashes(images_dir)
    if actual_hashes != expected_hashes:
        raise RuntimeError(
            "Deck review belongs to a different slide-image set"
        )
    return actual_hashes


def build_outputs(
    review: dict,
    speaker_notes: Path,
    images_dir: Path,
    speaker_notes_output: Path,
) -> tuple[str, str, str, str]:
    if review.get("format") != DECK_REVIEW_FORMAT:
        raise RuntimeError(
            f"Deck review must use format {DECK_REVIEW_FORMAT}"
        )
    image_hashes = validate_source(review, speaker_notes, images_dir)
    markdown = review_markdown(review)
    chunks_document = notes.format_speaker_notes_text(
        markdown,
        speaker_notes_output.name,
    )
    reviewed_slides = review["slides"]
    overrides = []
    for chunk, reviewed_slide in zip(
        chunks_document["chunks"],
        reviewed_slides,
        strict=True,
    ):
        reviewed_anchors = reviewed_slide.get("anchors")
        if not isinstance(reviewed_anchors, list):
            raise RuntimeError(f"{chunk['id']} has no reviewed anchors")
        if len(reviewed_anchors) != len(chunk["anchors"]):
            raise RuntimeError(
                f"{chunk['id']} anchor list does not match its manuscript"
            )
        for anchor, reviewed_anchor in zip(
            chunk["anchors"],
            reviewed_anchors,
            strict=True,
        ):
            if (
                not isinstance(reviewed_anchor, dict)
                or reviewed_anchor.get("id") != anchor["id"]
                or reviewed_anchor.get("text") != anchor["text"]
            ):
                raise RuntimeError(
                    f"{chunk['id']}/{anchor['id']} does not match the reviewed manuscript"
                )
            box_source = reviewed_anchor.get("box_source")
            if box_source not in {
                "auto",
                "manual",
                "suppress",
                "unresolved",
            }:
                raise RuntimeError(
                    f"{chunk['id']}/{anchor['id']} has invalid box_source"
                )
            if box_source == "manual":
                box = validate_box(
                    reviewed_anchor.get("box"),
                    f"{chunk['id']}/{anchor['id']}.box",
                )
                overrides.append(
                    {
                        "slide": chunk["slide"],
                        "anchor_id": anchor["id"],
                        "anchor_text": anchor["text"],
                        "action": "set",
                        "fragments": [box],
                        "selection": {
                            "kind": "pre_tts_bounding_box_editor"
                        },
                    }
                )
            elif box_source == "auto":
                validate_box(
                    reviewed_anchor.get("box"),
                    f"{chunk['id']}/{anchor['id']}.box",
                )
            elif box_source == "suppress":
                if reviewed_anchor.get("box") is not None:
                    raise RuntimeError(
                        f"{chunk['id']}/{anchor['id']} suppress must have no box"
                    )
                overrides.append(
                    {
                        "slide": chunk["slide"],
                        "anchor_id": anchor["id"],
                        "anchor_text": anchor["text"],
                        "action": "suppress",
                        "fragments": [],
                        "selection": {
                            "kind": "pre_tts_bounding_box_editor"
                        },
                    }
                )
            elif reviewed_anchor.get("box") is not None:
                raise RuntimeError(
                    f"{chunk['id']}/{anchor['id']} unresolved must have no box"
                )

    chunks_json = (
        json.dumps(chunks_document, ensure_ascii=False, indent=2) + "\n"
    )
    chunks_sha256 = hashlib.sha256(chunks_json.encode("utf-8")).hexdigest()
    override_document = {
        "format": ANCHOR_OVERRIDES_FORMAT,
        "source": {
            "chunks_sha256": chunks_sha256,
            "images": [
                {"slide": slide, "sha256": digest}
                for slide, digest in sorted(image_hashes.items())
            ],
        },
        "overrides": overrides,
    }
    tts_text = (
        "\n\n".join(chunk["text"] for chunk in chunks_document["chunks"])
        + "\n"
    )
    overrides_json = (
        json.dumps(override_document, ensure_ascii=False, indent=2) + "\n"
    )
    return markdown, chunks_json, tts_text, overrides_json


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_json", type=Path)
    parser.add_argument("speaker_notes", type=Path)
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("--speaker-notes-output", type=Path, required=True)
    parser.add_argument("--chunks-output", type=Path, required=True)
    parser.add_argument("--tts-output", type=Path, required=True)
    parser.add_argument("--anchor-overrides-output", type=Path, required=True)
    parser.add_argument(
        "--ocr-results",
        type=Path,
        help="Image-bound OCR results emitted by the prepare command",
    )
    parser.add_argument(
        "--ocr-output",
        type=Path,
        help="Validated copy of --ocr-results for the downstream video stage",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def apply_review(
    review_path: Path,
    speaker_notes: Path,
    images_dir: Path,
    output_paths: list[Path],
    *,
    ocr_results_path: Path | None = None,
    ocr_output: Path | None = None,
    overwrite: bool = False,
) -> None:
    review_path = review_path.resolve()
    speaker_notes = speaker_notes.resolve()
    images_dir = images_dir.resolve()
    output_paths = [
        path.resolve()
        for path in output_paths
    ]
    if (ocr_results_path is None) != (ocr_output is None):
        raise RuntimeError(
            "--ocr-results and --ocr-output must be provided together"
        )
    ocr_results_path = (
        ocr_results_path.resolve() if ocr_results_path else None
    )
    ocr_output = ocr_output.resolve() if ocr_output else None
    if len(output_paths) != 4:
        raise RuntimeError("Deck review must produce exactly four outputs")
    all_output_paths = [
        *output_paths,
        *([ocr_output] if ocr_output else []),
    ]
    if len(set(all_output_paths)) != len(all_output_paths):
        raise RuntimeError("Deck-review outputs must be distinct")
    existing = [path for path in all_output_paths if path.exists()]
    if existing and not overwrite:
        raise RuntimeError(
            f"Output already exists: {', '.join(str(path) for path in existing)}; "
            "pass --overwrite"
        )
    ocr_contents = None
    if ocr_results_path:
        ocr_contents = ocr_results_path.read_text(encoding="utf-8")
        anchoring.load_ocr_results(
            json.loads(ocr_contents),
            anchoring.discover_images(images_dir),
            requested_confidence=1.0,
        )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    outputs = build_outputs(
        review,
        speaker_notes,
        images_dir,
        output_paths[0],
    )
    for path, content in zip(output_paths, outputs, strict=True):
        atomic_write(path, content)
    if ocr_output and ocr_contents is not None:
        atomic_write(ocr_output, ocr_contents)
    print(f"Reviewed speaker notes: {output_paths[0]}")
    print(f"TTS chunks: {output_paths[1]}")
    print(f"Subtitle reference: {output_paths[2]}")
    print(f"Anchor overrides: {output_paths[3]}")
    if ocr_output:
        print(f"OCR results: {ocr_output}")


def main() -> int:
    args = parse_args()
    apply_review(
        args.review_json,
        args.speaker_notes,
        args.images_dir,
        [
            args.speaker_notes_output,
            args.chunks_output,
            args.tts_output,
            args.anchor_overrides_output,
        ],
        ocr_results_path=args.ocr_results,
        ocr_output=args.ocr_output,
        overwrite=args.overwrite,
    )
    return 0
