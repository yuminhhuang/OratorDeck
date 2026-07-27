#!/usr/bin/env python3
"""Build a slide video with timed underlines for bold speaker-note anchors.

The chunk document supplies the anchor text and character offsets. The timing
report supplies one indivisible WAV per slide. Optional SRT/VTT captions give
the preferred anchor timing; otherwise timing is estimated from each anchor's
position in the spoken slide text. Shared OCR evidence locates the corresponding
visual wording; it can come from the pre-TTS image-bound intermediate or a live
RapidOCR pass. The bundled imageio-ffmpeg executable renders one clip per slide
before concatenating the clips. The OCR plan also produces a slide-animation
cue file with narration order and normalized anchor text positions, plus a
self-contained HTML verdict for reviewing, correcting, and rerendering
uncertain assignments.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path

import soundfile as sf
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from oratordeck_verdict.anchoring import (  # noqa: E402,F401
    OCR_MATCHING_METHOD,
    OCRCandidate,
    OCRLine,
    TextToken,
    anchor_text_boxes,
    anchors_can_share_tokens,
    assign_ocr_anchors,
    candidate_token_overlap,
    contains_word_sequence,
    discover_images,
    filter_ocr_lines,
    load_ocr_results,
    match_ocr_anchor,
    normalize_word,
    normalized_anchor_geometry,
    normalized_box,
    normalized_words,
    ocr_anchor_candidates,
    run_ocr,
    score_ocr_window,
    select_global_anchor_candidates,
    selected_ocr_token_indexes,
    text_tokens,
)
from oratordeck_verdict.editor import (  # noqa: E402
    build_deck_review_html,
    script_with_bold_anchors,
    slide_data_uri,
)

CHUNK_FORMAT = "oratordeck.speaker-notes-chunks.v1"
TIMING_FORMAT = "oratordeck.keynote-timing-report.v1"
REPORT_FORMAT = "oratordeck.anchor-video-report.v1"
ANIMATION_CUES_FORMAT = "oratordeck.anchor-animation-cues.v1"
ANCHOR_OVERRIDES_FORMAT = "oratordeck.anchor-overrides.v1"
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TimedToken:
    value: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class Cue:
    start_seconds: float
    end_seconds: float
    text: str


def clock(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def parse_timestamp(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise RuntimeError(f"Invalid subtitle timestamp: {value!r}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_subtitles(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->")
        start_text = timing[0].strip()
        end_text = timing[1].strip().split()[0]
        caption = " ".join(lines[timing_index + 1 :])
        caption = html.unescape(TAG_RE.sub("", caption)).strip()
        if not caption:
            continue
        start = parse_timestamp(start_text)
        end = parse_timestamp(end_text)
        if end <= start:
            continue
        cues.append(Cue(start, end, caption))
    if not cues:
        raise RuntimeError(f"No timed cues found in {path}")
    return cues


def timed_tokens(cues: list[Cue]) -> list[TimedToken]:
    output = []
    for cue in cues:
        words = text_tokens(cue.text)
        if not words:
            continue
        duration = cue.end_seconds - cue.start_seconds
        for index, word in enumerate(words):
            output.append(
                TimedToken(
                    word.value,
                    cue.start_seconds + duration * index / len(words),
                    cue.start_seconds + duration * (index + 1) / len(words),
                )
            )
    return output


def proportional_anchor_interval(
    anchor: dict,
    slide_text: str,
    duration: float,
) -> tuple[float, float]:
    words = text_tokens(slide_text)
    if not words:
        return 0.0, duration
    overlapping = [
        index
        for index, word in enumerate(words)
        if word.end_char > anchor["start_char"] and word.start_char < anchor["end_char"]
    ]
    if not overlapping:
        start_fraction = anchor["start_char"] / max(1, len(slide_text))
        end_fraction = anchor["end_char"] / max(1, len(slide_text))
    else:
        start_fraction = overlapping[0] / len(words)
        end_fraction = (overlapping[-1] + 1) / len(words)
    return duration * start_fraction, duration * end_fraction


def subtitle_anchor_interval(
    anchor: dict,
    slide_text: str,
    slide_start: float,
    slide_duration: float,
    all_tokens: list[TimedToken],
    threshold: float,
) -> tuple[float, float, float] | None:
    anchor_words = [token.value for token in text_tokens(anchor["text"])]
    if not anchor_words:
        return None
    slide_end = slide_start + slide_duration
    candidates = [
        token
        for token in all_tokens
        if token.end_seconds > slide_start and token.start_seconds < slide_end
    ]
    if not candidates:
        return None

    expected_start, _ = proportional_anchor_interval(anchor, slide_text, slide_duration)
    anchor_length = len(anchor_words)
    minimum_length = max(1, anchor_length - max(2, anchor_length // 5))
    maximum_length = min(
        len(candidates),
        anchor_length + max(2, anchor_length // 5),
    )
    best = None
    for window_length in range(minimum_length, maximum_length + 1):
        for start_index in range(0, len(candidates) - window_length + 1):
            window = candidates[start_index : start_index + window_length]
            values = [token.value for token in window]
            score = SequenceMatcher(None, anchor_words, values, autojunk=False).ratio()
            local_start = max(0.0, window[0].start_seconds - slide_start)
            distance = abs(local_start - expected_start) / max(1.0, slide_duration)
            rank = (score, -distance, -abs(window_length - anchor_length))
            if best is None or rank > best[0]:
                best = (
                    rank,
                    local_start,
                    min(slide_duration, window[-1].end_seconds - slide_start),
                    score,
                )
    if best is None or best[3] < threshold:
        return None
    return best[1], best[2], best[3]


def load_chunks(path: Path) -> tuple[dict, dict[str, dict]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != CHUNK_FORMAT:
        raise RuntimeError(f"{path} is not a {CHUNK_FORMAT} document")
    chunks = document.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise RuntimeError(f"{path} contains no chunks")
    by_id = {}
    for chunk in chunks:
        chunk_id = chunk.get("id")
        anchors = chunk.get("anchors")
        if not isinstance(chunk_id, str) or chunk_id in by_id:
            raise RuntimeError(f"Invalid or duplicate chunk id: {chunk_id!r}")
        if not isinstance(anchors, list):
            raise RuntimeError(
                f"{chunk_id} has no anchors; regenerate chunks with the formatter"
            )
        for anchor in anchors:
            start = anchor.get("start_char")
            end = anchor.get("end_char")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or chunk["text"][start:end] != anchor.get("text")
            ):
                raise RuntimeError(f"{chunk_id}/{anchor.get('id')} has invalid offsets")
        by_id[chunk_id] = chunk
    return document, by_id


def resolve_repo_path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def load_timing_report(
    path: Path,
    chunks_path: Path,
    chunks_by_id: dict[str, dict],
    repo_root: Path,
) -> tuple[dict, list[dict]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("format") != TIMING_FORMAT:
        raise RuntimeError(f"{path} is not a {TIMING_FORMAT} document")
    if report.get("input_sha256") != hashlib.sha256(chunks_path.read_bytes()).hexdigest():
        raise RuntimeError(
            f"{path} was generated from a different chunk file; regenerate the audio"
        )
    items = report.get("chunks")
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"{path} contains no generated slide chunks")
    loaded = []
    seen = set()
    for item in items:
        chunk_id = item.get("id")
        if chunk_id in seen or chunk_id not in chunks_by_id:
            raise RuntimeError(f"Timing report has invalid chunk id: {chunk_id!r}")
        seen.add(chunk_id)
        audio_path = resolve_repo_path(item["audio_path"], repo_root)
        if not audio_path.is_file():
            raise RuntimeError(f"Missing slide audio: {audio_path}")
        audio_info = sf.info(audio_path)
        if audio_info.duration <= 0:
            raise RuntimeError(f"Empty slide audio: {audio_path}")
        declared_duration = float(item["actual_seconds"])
        if abs(audio_info.duration - declared_duration) > 0.05:
            raise RuntimeError(
                f"{chunk_id} WAV duration {audio_info.duration:.3f}s differs from "
                f"timing report {declared_duration:.3f}s"
            )
        loaded.append(
            {
                **item,
                "audio_path_resolved": audio_path,
                "actual_seconds": audio_info.duration,
            }
        )
    return report, loaded


def underline_boxes(
    text_boxes: list[dict],
    image_width: int,
    image_height: int,
    thickness: int,
) -> list[dict]:
    boxes = []
    for text_box in text_boxes:
        text_bottom = text_box["y"] + text_box["height"]
        underline_y = min(
            image_height - thickness,
            text_bottom + max(3, round(text_box["height"] * 0.12)),
        )
        boxes.append(
            {
                "x": text_box["x"],
                "y": max(0, underline_y),
                "width": max(
                    4,
                    min(image_width, text_box["x"] + text_box["width"])
                    - text_box["x"],
                ),
                "height": thickness,
                "ocr_text": text_box["ocr_text"],
            }
        )
    return boxes


def anchor_override_source(
    slide_plans: list[dict],
    chunks_sha256: str,
) -> dict:
    return {
        "chunks_sha256": chunks_sha256,
        "images": [
            {
                "slide": slide_plan["slide"],
                "sha256": hashlib.sha256(
                    Path(slide_plan["image_path"]).read_bytes()
                ).hexdigest(),
            }
            for slide_plan in slide_plans
        ],
    }


def normalized_override_fragment(fragment: object, label: str) -> dict[str, float]:
    if not isinstance(fragment, dict):
        raise RuntimeError(f"{label} must be an object")
    values = {}
    for field in ("x", "y", "width", "height"):
        value = fragment.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise RuntimeError(f"{label}.{field} must be a finite number")
        values[field] = float(value)
    if values["x"] < 0 or values["y"] < 0:
        raise RuntimeError(f"{label} starts outside normalized slide bounds")
    if values["width"] <= 0 or values["height"] <= 0:
        raise RuntimeError(f"{label} must have positive width and height")
    if (
        values["x"] + values["width"] > 1.000001
        or values["y"] + values["height"] > 1.000001
    ):
        raise RuntimeError(f"{label} extends outside normalized slide bounds")
    return {
        field: round(min(1.0, values[field]), 6)
        for field in ("x", "y", "width", "height")
    }


def override_text_boxes(
    fragments: list[dict[str, float]],
    image_width: int,
    image_height: int,
    anchor_text: str,
) -> list[dict]:
    boxes = []
    for fragment in fragments:
        left = min(image_width - 1, round(fragment["x"] * image_width))
        top = min(image_height - 1, round(fragment["y"] * image_height))
        right = min(
            image_width,
            max(left + 1, round((fragment["x"] + fragment["width"]) * image_width)),
        )
        bottom = min(
            image_height,
            max(top + 1, round((fragment["y"] + fragment["height"]) * image_height)),
        )
        boxes.append(
            {
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
                "ocr_text": f"Manual override for {anchor_text}",
            }
        )
    return boxes


def apply_anchor_overrides(
    slide_plans: list[dict],
    overrides: dict,
    chunks_sha256: str,
    underline_thickness: int,
) -> dict[str, int]:
    if not isinstance(overrides, dict):
        raise RuntimeError("Anchor overrides must be a JSON object")
    if overrides.get("format") != ANCHOR_OVERRIDES_FORMAT:
        raise RuntimeError(
            f"Anchor overrides must use format {ANCHOR_OVERRIDES_FORMAT}"
        )
    source = overrides.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Anchor overrides must contain a source object")
    if source.get("chunks_sha256") != chunks_sha256:
        raise RuntimeError(
            "Anchor overrides were exported for a different speaker-note chunk file"
        )
    source_images = source.get("images")
    if not isinstance(source_images, list):
        raise RuntimeError("Anchor override source.images must be a list")
    image_hashes = {}
    for index, item in enumerate(source_images):
        if not isinstance(item, dict):
            raise RuntimeError(f"source.images[{index}] must be an object")
        slide = item.get("slide")
        digest = item.get("sha256")
        if (
            isinstance(slide, bool)
            or not isinstance(slide, int)
            or not isinstance(digest, str)
        ):
            raise RuntimeError(
                f"source.images[{index}] requires integer slide and string sha256"
            )
        if slide in image_hashes:
            raise RuntimeError(f"Duplicate source image fingerprint for slide {slide}")
        image_hashes[slide] = digest

    targets = {}
    for slide_plan in slide_plans:
        slide = slide_plan["slide"]
        actual_digest = hashlib.sha256(
            Path(slide_plan["image_path"]).read_bytes()
        ).hexdigest()
        if image_hashes.get(slide) != actual_digest:
            raise RuntimeError(
                f"Anchor overrides were exported for a different image on slide {slide}"
            )
        for anchor in slide_plan["anchors"]:
            targets[(slide, anchor["id"])] = (slide_plan, anchor)

    records = overrides.get("overrides")
    if not isinstance(records, list):
        raise RuntimeError("Anchor overrides must contain an overrides list")
    seen = set()
    summary = {"total": 0, "set": 0, "suppress": 0}
    for index, record in enumerate(records):
        label = f"overrides[{index}]"
        if not isinstance(record, dict):
            raise RuntimeError(f"{label} must be an object")
        slide = record.get("slide")
        anchor_id = record.get("anchor_id")
        if (
            isinstance(slide, bool)
            or not isinstance(slide, int)
            or not isinstance(anchor_id, str)
        ):
            raise RuntimeError(f"{label} requires integer slide and string anchor_id")
        key = (slide, anchor_id)
        if key in seen:
            raise RuntimeError(
                f"Duplicate anchor override for slide {slide}, anchor {anchor_id}"
            )
        seen.add(key)
        target = targets.get(key)
        if target is None:
            raise RuntimeError(
                f"{label} targets unknown slide {slide}, anchor {anchor_id}"
            )
        slide_plan, anchor = target
        if (
            "anchor_text" in record
            and record["anchor_text"] != anchor["text"]
        ):
            raise RuntimeError(
                f"{label}.anchor_text does not match the current anchor text"
            )
        action = record.get("action")
        if action not in {"set", "suppress"}:
            raise RuntimeError(f"{label}.action must be 'set' or 'suppress'")

        fragments = record.get("fragments", [])
        if action == "set":
            if not isinstance(fragments, list) or not 1 <= len(fragments) <= 32:
                raise RuntimeError(
                    f"{label}.fragments must contain between 1 and 32 boxes"
                )
            normalized_fragments = [
                normalized_override_fragment(
                    fragment,
                    f"{label}.fragments[{fragment_index}]",
                )
                for fragment_index, fragment in enumerate(fragments)
            ]
            image_width, image_height = slide_plan["image_size"]
            text_boxes = override_text_boxes(
                normalized_fragments,
                image_width,
                image_height,
                anchor["text"],
            )
            anchor["text_boxes"] = text_boxes
            anchor["underline_boxes"] = underline_boxes(
                text_boxes,
                image_width,
                image_height,
                underline_thickness,
            )
            anchor["ocr_status"] = "resolved"
            anchor["ocr_unresolved_reason"] = None
            anchor["source_geometry_out_of_bounds"] = False
        else:
            if fragments not in (None, []):
                raise RuntimeError(
                    f"{label}.fragments must be empty when action is 'suppress'"
                )
            normalized_fragments = []
            anchor["text_boxes"] = []
            anchor["underline_boxes"] = []
            anchor["ocr_status"] = "suppressed"
            anchor["ocr_unresolved_reason"] = None
            anchor["source_geometry_out_of_bounds"] = False

        selection = record.get("selection")
        if selection is not None and not isinstance(selection, dict):
            raise RuntimeError(f"{label}.selection must be an object when present")
        anchor["manual_override"] = {
            "action": action,
            "fragments": normalized_fragments,
            "selection": selection,
        }
        summary["total"] += 1
        summary[action] += 1
    return summary


def box_out_of_bounds(box: dict, image_width: int, image_height: int) -> bool:
    return (
        box["x"] < 0
        or box["y"] < 0
        or box["width"] <= 0
        or box["height"] <= 0
        or box["x"] + box["width"] > image_width
        or box["y"] + box["height"] > image_height
    )


def ocr_lines_out_of_bounds(
    lines: tuple[OCRLine, ...],
    image_width: int,
    image_height: int,
) -> bool:
    return any(
        x1 < 0
        or y1 < 0
        or x2 > image_width
        or y2 > image_height
        or x2 <= x1
        or y2 <= y1
        for line in lines
        for x1, y1, x2, y2 in [line.box]
    )


def geometry_overlap_ratio(first_boxes: list[dict], second_boxes: list[dict]) -> float:
    maximum = 0.0
    for first in first_boxes:
        first_area = first["width"] * first["height"]
        if first_area <= 0:
            continue
        for second in second_boxes:
            second_area = second["width"] * second["height"]
            if second_area <= 0:
                continue
            left = max(first["x"], second["x"])
            top = max(first["y"], second["y"])
            right = min(
                first["x"] + first["width"],
                second["x"] + second["width"],
            )
            bottom = min(
                first["y"] + first["height"],
                second["y"] + second["height"],
            )
            if right <= left or bottom <= top:
                continue
            intersection = (right - left) * (bottom - top)
            maximum = max(maximum, intersection / min(first_area, second_area))
    return maximum


def annotate_anchor_geometry(
    slide_plans: list[dict],
    overlap_threshold: float = 0.35,
) -> None:
    for slide_plan in slide_plans:
        image_width, image_height = slide_plan["image_size"]
        anchors = slide_plan["anchors"]
        for anchor in anchors:
            anchor["geometry_out_of_bounds"] = (
                anchor.get("source_geometry_out_of_bounds", False)
                or any(
                    box_out_of_bounds(box, image_width, image_height)
                    for box in anchor["text_boxes"]
                )
            )
            anchor["geometry_overlaps_with"] = []
        for first_index, first in enumerate(anchors):
            if not first["text_boxes"]:
                continue
            for second in anchors[first_index + 1 :]:
                if (
                    not second["text_boxes"]
                    or anchors_can_share_tokens(first["text"], second["text"])
                ):
                    continue
                if (
                    geometry_overlap_ratio(
                        first["text_boxes"],
                        second["text_boxes"],
                    )
                    < overlap_threshold
                ):
                    continue
                first["geometry_overlaps_with"].append(second["id"])
                second["geometry_overlaps_with"].append(first["id"])


def build_animation_cues(
    slide_plans: list[dict],
    chunks_path: Path,
    images_dir: Path,
) -> dict:
    slides = []
    anchor_count = 0
    resolved_anchor_count = 0
    suppressed_anchor_count = 0
    for slide_plan in slide_plans:
        image_width, image_height = slide_plan["image_size"]
        anchors = []
        for appearance_order, anchor in enumerate(slide_plan["anchors"], start=1):
            anchor_count += 1
            position, fragments = normalized_anchor_geometry(
                anchor["text_boxes"],
                image_width,
                image_height,
            )
            manual_override = anchor.get("manual_override")
            if manual_override and manual_override["action"] == "suppress":
                status = "suppressed"
                suppressed_anchor_count += 1
            elif position is not None:
                status = "resolved"
                resolved_anchor_count += 1
            else:
                status = "unresolved"
            anchors.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "appearance_order": appearance_order,
                    "status": status,
                    "verdict": anchor["verdict"],
                    "review_reasons": anchor["review_reasons"],
                    "manual_override": manual_override,
                    "geometry_out_of_bounds": anchor.get(
                        "geometry_out_of_bounds",
                        False,
                    ),
                    "geometry_overlaps_with": anchor.get(
                        "geometry_overlaps_with",
                        [],
                    ),
                    "ocr_match_score": anchor["ocr_match_score"],
                    "ocr_anchor_coverage": anchor["ocr_anchor_coverage"],
                    "ocr_assignment_quality": anchor["ocr_assignment_quality"],
                    "ocr_candidate_count": anchor["ocr_candidate_count"],
                    "ocr_candidate_margin": anchor["ocr_candidate_margin"],
                    "ocr_selected_candidate_rank": anchor[
                        "ocr_selected_candidate_rank"
                    ],
                    "ocr_assignment_changed": anchor["ocr_assignment_changed"],
                    "ocr_shared_with": anchor["ocr_shared_with"],
                    "timing_source": anchor["timing_source"],
                    "timing_match_score": anchor["timing_match_score"],
                    "position": position,
                    "fragments": fragments,
                }
            )
        slides.append(
            {
                "slide_number": slide_plan["slide"],
                "chunk_id": slide_plan["id"],
                "title": slide_plan["title"],
                "image_path": slide_plan["image_path"],
                "image_sha256": hashlib.sha256(
                    Path(slide_plan["image_path"]).read_bytes()
                ).hexdigest(),
                "image_size_pixels": {
                    "width": image_width,
                    "height": image_height,
                },
                "anchors": anchors,
            }
        )
    return {
        "format": ANIMATION_CUES_FORMAT,
        "coordinate_space": {
            "reference": "source_slide_image",
            "origin": "top_left",
            "x_axis": "left_to_right",
            "y_axis": "top_to_bottom",
            "units": "normalized_0_to_1",
            "box_fields": ["x", "y", "width", "height", "center_x", "center_y"],
        },
        "chunks_file": str(chunks_path),
        "chunks_sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
        "images_dir": str(images_dir),
        "slide_count": len(slides),
        "anchor_count": anchor_count,
        "resolved_anchor_count": resolved_anchor_count,
        "suppressed_anchor_count": suppressed_anchor_count,
        "unresolved_anchor_count": (
            anchor_count - resolved_anchor_count - suppressed_anchor_count
        ),
        "slides": slides,
    }


def apply_anchor_verdicts(
    slide_plans: list[dict],
    confidence_threshold: float,
    coverage_threshold: float,
    ambiguity_margin: float,
) -> dict[str, int]:
    summary = {
        "pass": 0,
        "corrected": 0,
        "review": 0,
        "unresolved": 0,
        "slides_with_review_items": 0,
    }
    for slide_plan in slide_plans:
        slide_has_review_items = False
        for anchor in slide_plan["anchors"]:
            reasons = []
            manual_override = anchor.get("manual_override")
            if manual_override is not None:
                if anchor.get("geometry_out_of_bounds"):
                    reasons.append("out_of_bounds_geometry")
                if anchor.get("geometry_overlaps_with"):
                    reasons.append("overlapping_anchor_geometry")
                verdict = "review" if reasons else "corrected"
            elif anchor["ocr_status"] == "unresolved":
                verdict = "unresolved"
                reasons.append(
                    anchor["ocr_unresolved_reason"]
                    or "no_candidate_above_threshold"
                )
            else:
                if anchor["ocr_match_score"] < confidence_threshold:
                    reasons.append("low_ocr_confidence")
                if anchor["ocr_anchor_coverage"] < coverage_threshold:
                    reasons.append("low_anchor_coverage")
                candidate_margin = anchor["ocr_candidate_margin"]
                if (
                    anchor["ocr_candidate_count"] > 1
                    and candidate_margin is not None
                    and candidate_margin < ambiguity_margin
                ):
                    reasons.append("ambiguous_ocr_candidates")
                if anchor["ocr_assignment_changed"]:
                    reasons.append("global_reassignment")
                if anchor["timing_source"] == "proportional_text":
                    reasons.append("proportional_timing")
                if anchor.get("geometry_out_of_bounds"):
                    reasons.append("out_of_bounds_geometry")
                if anchor.get("geometry_overlaps_with"):
                    reasons.append("overlapping_anchor_geometry")
                verdict = "review" if reasons else "pass"
            anchor["verdict"] = verdict
            anchor["review_reasons"] = reasons
            summary[verdict] += 1
            if verdict in {"review", "unresolved"}:
                slide_has_review_items = True
        if slide_has_review_items:
            summary["slides_with_review_items"] += 1
    return summary


REVIEW_REASON_LABELS = {
    "no_candidate_above_threshold": "No OCR candidate met the match threshold",
    "global_conflict": "All candidates conflicted with a stronger anchor assignment",
    "low_ocr_confidence": "OCR match confidence is below the review threshold",
    "low_anchor_coverage": "Matched OCR tokens cover too little of the anchor text",
    "ambiguous_ocr_candidates": "Two or more spatial candidates scored similarly",
    "global_reassignment": "Global assignment selected a non-top local candidate",
    "proportional_timing": "Timing falls back to proportional narration position",
    "overlapping_anchor_geometry": "Anchor box unexpectedly overlaps another anchor",
    "out_of_bounds_geometry": "Anchor geometry extends outside the slide image",
}


def score_label(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def slide_thumbnail_data_uri(image_path: Path) -> str:
    with Image.open(image_path) as source:
        source.thumbnail((960, 720), Image.Resampling.LANCZOS)
        if source.mode in ("RGBA", "LA") or "transparency" in source.info:
            rgba = source.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = source.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def build_legacy_anchor_verdict_html(
    slide_plans: list[dict],
    summary: dict[str, int],
    confidence_threshold: float,
    coverage_threshold: float,
    ambiguity_margin: float,
    chunks_sha256: str,
    rerender_report_path: Path,
    python_executable: Path,
    script_path: Path,
) -> str:
    styles = """
    :root { color-scheme: light; --ink:#172033; --muted:#667085; --line:#d8dee9;
      --pass:#18794e; --corrected:#175cd3; --review:#b54708;
      --unresolved:#b42318; --paper:#f5f7fb; --active:#7f56d9; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--paper); color:var(--ink);
      font:14px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { max-width:1500px; margin:0 auto; padding:32px; }
    h1 { margin:0 0 8px; font-size:30px; }
    .lede { color:var(--muted); margin:0 0 22px; }
    .summary { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr));
      gap:12px; margin-bottom:28px; }
    .metric { background:white; border:1px solid var(--line); border-radius:10px;
      padding:14px 16px; }
    .metric strong { display:block; font-size:25px; }
    .metric span { color:var(--muted); }
    .slide { background:white; border:1px solid var(--line); border-radius:12px;
      margin:0 0 24px; overflow:hidden; }
    .slide-head { display:flex; align-items:center; justify-content:space-between;
      gap:16px; padding:14px 18px; border-bottom:1px solid var(--line); }
    .slide-head h2 { margin:0; font-size:18px; }
    .slide-head span { color:var(--muted); }
    .slide-body { display:grid; grid-template-columns:minmax(420px,1.05fr) minmax(520px,1fr);
      gap:18px; padding:18px; align-items:start; }
    .canvas { position:relative; line-height:0; border:1px solid var(--line);
      background:#eef1f6; touch-action:none; user-select:none; }
    .canvas img { width:100%; height:auto; display:block; }
    .anchor-box { position:absolute; border:2px solid currentColor;
      background:color-mix(in srgb,currentColor 10%,transparent); }
    .anchor-box.pass { color:var(--pass); }
    .anchor-box.corrected { color:var(--corrected); }
    .anchor-box.review { color:var(--review); }
    .anchor-box.unresolved { color:var(--unresolved); }
    .anchor-box > b { position:absolute; left:-2px; top:-22px; min-width:21px;
      padding:2px 5px; border-radius:4px 4px 0 0; color:white; background:currentColor;
      font-size:11px; line-height:16px; text-align:center; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th,td { padding:7px 6px; border-bottom:1px solid #eaecf0; text-align:left;
      vertical-align:top; }
    th { color:var(--muted); font-weight:600; }
    td.text { min-width:210px; }
    .badge { display:inline-block; border-radius:999px; padding:2px 7px;
      color:white; font-weight:700; font-size:10px; text-transform:uppercase; }
    .badge.pass { background:var(--pass); }
    .badge.corrected { background:var(--corrected); }
    .badge.review { background:var(--review); }
    .badge.unresolved { background:var(--unresolved); }
    .reasons { color:var(--muted); }
    .legend { margin:0 0 22px; padding:12px 15px; background:white;
      border:1px solid var(--line); border-radius:10px; color:var(--muted); }
    .editor { position:sticky; top:0; z-index:20; margin:0 0 24px;
      padding:14px 16px; background:#fff; border:2px solid #d6bbfb;
      border-radius:12px; box-shadow:0 8px 30px #10182818; }
    .editor-head { display:flex; justify-content:space-between; gap:16px;
      align-items:flex-start; margin-bottom:10px; }
    .editor-head strong { display:block; font-size:15px; }
    .editor-head span { color:var(--muted); font-size:12px; }
    .editor-controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    button,select,.file-label { border:1px solid #98a2b3; border-radius:7px;
      background:white; color:var(--ink); padding:7px 10px; font:inherit;
      line-height:1.2; cursor:pointer; }
    button.primary { background:#6941c6; border-color:#6941c6; color:white; }
    button.danger { border-color:#fda29b; color:#b42318; }
    button:disabled,select:disabled { cursor:not-allowed; opacity:.5; }
    .file-label input { display:none; }
    .edit-button { padding:4px 7px; font-size:11px; }
    tr.active-row { background:#f4f3ff; outline:2px solid #d6bbfb;
      outline-offset:-2px; }
    .editor-fragment,.draft-fragment { position:absolute; z-index:12;
      border:3px solid var(--active); background:#7f56d933; pointer-events:none; }
    .draft-fragment { border-style:dashed; }
    .canvas.drawing { cursor:crosshair; outline:3px solid #d6bbfb; }
    .status-note { min-height:18px; margin-top:8px; color:var(--muted);
      font-size:12px; }
    code { background:#f2f4f7; padding:2px 5px; border-radius:4px; }
    @media (max-width:1050px) {
      main { padding:18px; }
      .summary { grid-template-columns:repeat(2,1fr); }
      .slide-body { grid-template-columns:1fr; }
    }
    """
    editor_slides = []
    initial_overrides = []
    source = anchor_override_source(slide_plans, chunks_sha256)
    for slide_plan in slide_plans:
        image_width, image_height = slide_plan["image_size"]
        editor_anchors = []
        for appearance_order, anchor in enumerate(
            slide_plan["anchors"],
            start=1,
        ):
            _, automatic_fragments = normalized_anchor_geometry(
                anchor.get("auto_text_boxes", anchor["text_boxes"]),
                image_width,
                image_height,
            )
            editor_anchors.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "appearance_order": appearance_order,
                    "automatic_fragments": automatic_fragments,
                    "candidates": anchor.get("ocr_candidates", []),
                }
            )
            if anchor.get("manual_override") is not None:
                initial_overrides.append(
                    {
                        "slide": slide_plan["slide"],
                        "anchor_id": anchor["id"],
                        "anchor_text": anchor["text"],
                        **anchor["manual_override"],
                    }
                )
        editor_slides.append(
            {
                "slide": slide_plan["slide"],
                "title": slide_plan["title"],
                "anchors": editor_anchors,
            }
        )
    editor_payload = json.dumps(
        {
            "format": ANCHOR_OVERRIDES_FORMAT,
            "source": source,
            "slides": editor_slides,
            "initial_overrides": initial_overrides,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    editor_payload = (
        editor_payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    override_path = rerender_report_path.with_name("anchor-overrides.json")
    rerender_command = html.escape(
        f'"{python_executable}" "{script_path}" '
        f'--rerender-from-report "{rerender_report_path}" '
        f'--anchor-overrides "{override_path}" --overwrite'
    )
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>OratorDeck Anchor Verdict</title>",
        f"<style>{styles}</style></head><body><main>",
        "<h1>Anchor verdict</h1>",
        (
            "<p class=\"lede\">Review OCR anchoring and timing provenance, then "
            "correct an anchor by choosing another OCR candidate, drawing one or "
            "more replacement boxes, or suppressing its underline. Export the "
            "corrections and rerender with <code>--anchor-overrides</code>.</p>"
        ),
        "<section class=\"summary\">",
        (
            f"<div class=\"metric\"><strong>{len(slide_plans)}</strong>"
            "<span>slides</span></div>"
        ),
        (
            f"<div class=\"metric\"><strong>{summary['pass']}</strong>"
            "<span>pass</span></div>"
        ),
        (
            f"<div class=\"metric\"><strong>{summary['corrected']}</strong>"
            "<span>corrected</span></div>"
        ),
        (
            f"<div class=\"metric\"><strong>{summary['review']}</strong>"
            "<span>review</span></div>"
        ),
        (
            f"<div class=\"metric\"><strong>{summary['unresolved']}</strong>"
            "<span>unresolved</span></div>"
        ),
        "</section>",
        (
            "<section class=\"editor\" id=\"editor\"><div class=\"editor-head\">"
            "<div><strong id=\"editor-title\">Select an anchor to correct</strong>"
            "<span id=\"editor-subtitle\">Use an Edit button in the review queue "
            "or a slide table.</span></div><div><strong id=\"edit-count\">0</strong>"
            "<span> saved corrections</span></div></div>"
            "<div class=\"editor-controls\">"
            "<select id=\"candidate-select\" disabled>"
            "<option>Choose a candidate</option></select>"
            "<button id=\"draw-replace\" disabled>Draw replacement</button>"
            "<button id=\"draw-add\" disabled>Add fragment</button>"
            "<button id=\"undo-fragment\" disabled>Remove last fragment</button>"
            "<button id=\"suppress-anchor\" class=\"danger\" disabled>"
            "Suppress underline</button>"
            "<button id=\"reset-anchor\" disabled>Reset automatic</button>"
            "<label class=\"file-label\">Import corrections"
            "<input id=\"import-overrides\" type=\"file\" accept=\"application/json,.json\">"
            "</label><button id=\"export-overrides\" class=\"primary\">"
            "Save anchor-overrides.json</button></div>"
            "<div class=\"status-note\" id=\"editor-status\">"
            "Drawing boxes means drawing around the visible anchor text; the "
            "underline is placed immediately below each box during rendering. "
            "Then run "
            f"<code>{rerender_command}</code>."
            "</div></section>"
        ),
        (
            "<p class=\"legend\">Review thresholds: OCR confidence "
            f"&lt; {confidence_threshold:.2f}; anchor coverage "
            f"&lt; {coverage_threshold:.2f}; spatial candidate margin "
            f"&lt; {ambiguity_margin:.2f}. Proportional timing and global "
            "reassignments are also marked for review.</p>"
        ),
    ]
    review_items = [
        (slide_plan, appearance_order, anchor)
        for slide_plan in slide_plans
        for appearance_order, anchor in enumerate(
            slide_plan["anchors"],
            start=1,
        )
        if anchor["verdict"] in {"review", "unresolved"}
    ]
    review_items.sort(
        key=lambda item: (
            item[2]["verdict"] != "unresolved",
            item[0]["slide"],
            item[1],
        )
    )
    parts.extend(
        [
            "<section class=\"slide\"><div class=\"slide-head\">",
            (
                f"<h2>Review queue</h2><span>{len(review_items)} items across "
                f"{summary['slides_with_review_items']} slides</span></div>"
            ),
            "<div style=\"padding:18px\"><table><thead><tr>",
            (
                "<th>Slide</th><th>#</th><th>Verdict</th><th>Anchor</th>"
                "<th>Reasons</th><th>Correct</th>"
            ),
            "</tr></thead><tbody>",
        ]
    )
    for slide_plan, appearance_order, anchor in review_items:
        anchor_key = html.escape(
            f"{slide_plan['slide']}:{anchor['id']}",
            quote=True,
        )
        reasons = "; ".join(
            REVIEW_REASON_LABELS.get(reason, reason)
            for reason in anchor["review_reasons"]
        )
        parts.extend(
            [
                (
                    f"<tr><td><a href=\"#slide-{slide_plan['slide']:02d}\">"
                    f"{slide_plan['slide']:02d}</a></td>"
                ),
                f"<td>{appearance_order}</td>",
                (
                    f"<td><span class=\"badge {anchor['verdict']}\">"
                    f"{anchor['verdict']}</span></td>"
                ),
                f"<td class=\"text\">{html.escape(anchor['text'])}</td>",
                f"<td class=\"reasons\">{html.escape(reasons)}</td>",
                (
                    "<td><button class=\"edit-button\" data-edit=\""
                    f"{anchor_key}"
                    "\">Edit</button></td></tr>"
                ),
            ]
        )
    parts.append("</tbody></table></div></section>")
    for slide_plan in slide_plans:
        image_width, image_height = slide_plan["image_size"]
        thumbnail = slide_thumbnail_data_uri(Path(slide_plan["image_path"]))
        issue_count = sum(
            anchor["verdict"] in {"review", "unresolved"}
            for anchor in slide_plan["anchors"]
        )
        parts.extend(
            [
                f"<section class=\"slide\" id=\"slide-{slide_plan['slide']:02d}\">",
                "<div class=\"slide-head\">",
                (
                    f"<h2>Slide {slide_plan['slide']:02d} · "
                    f"{html.escape(slide_plan['title'])}</h2>"
                ),
                (
                    f"<span>{len(slide_plan['anchors'])} anchors · "
                    f"{issue_count} review items</span></div>"
                ),
                (
                    "<div class=\"slide-body\"><div class=\"canvas\" "
                    f"id=\"canvas-slide-{slide_plan['slide']:02d}\" "
                    f"data-slide=\"{slide_plan['slide']}\">"
                ),
                (
                    f"<img alt=\"Slide {slide_plan['slide']:02d}\" "
                    f"src=\"{thumbnail}\">"
                ),
            ]
        )
        for appearance_order, anchor in enumerate(
            slide_plan["anchors"],
            start=1,
        ):
            anchor_key = html.escape(
                f"{slide_plan['slide']}:{anchor['id']}",
                quote=True,
            )
            position, _ = normalized_anchor_geometry(
                anchor["text_boxes"],
                image_width,
                image_height,
            )
            if position is None:
                continue
            parts.append(
                f"<div class=\"anchor-box {anchor['verdict']}\" "
                f"data-anchor-box=\"{anchor_key}\" "
                f"style=\"left:{position['x'] * 100:.4f}%;"
                f"top:{position['y'] * 100:.4f}%;"
                f"width:{position['width'] * 100:.4f}%;"
                f"height:{position['height'] * 100:.4f}%\">"
                f"<b>{appearance_order}</b></div>"
            )
        parts.extend(
            [
                "</div><div><table><thead><tr>",
                (
                    "<th>#</th><th>Verdict</th><th>Anchor</th><th>OCR</th>"
                    "<th>Coverage</th><th>Quality</th><th>Margin</th><th>Choice</th>"
                    "<th>Timing</th><th>Reasons</th><th>Correct</th>"
                ),
                "</tr></thead><tbody>",
            ]
        )
        for appearance_order, anchor in enumerate(
            slide_plan["anchors"],
            start=1,
        ):
            anchor_key = html.escape(
                f"{slide_plan['slide']}:{anchor['id']}",
                quote=True,
            )
            reasons = "; ".join(
                REVIEW_REASON_LABELS.get(reason, reason)
                for reason in anchor["review_reasons"]
            ) or "—"
            if anchor.get("manual_override") is not None:
                reasons = (
                    f"Manual {anchor['manual_override']['action']} applied"
                    if reasons == "—"
                    else f"{reasons}; manual {anchor['manual_override']['action']} applied"
                )
            manual_override = anchor.get("manual_override")
            if manual_override is not None:
                selection = manual_override.get("selection") or {}
                if manual_override["action"] == "suppress":
                    choice = "manual suppress"
                elif selection.get("kind") == "candidate":
                    choice = f"manual candidate {selection.get('rank', '—')}"
                else:
                    choice = "manual custom"
            else:
                choice = (
                    f"{anchor['ocr_selected_candidate_rank']}/"
                    f"{anchor['ocr_candidate_count']}"
                    if anchor["ocr_selected_candidate_rank"] is not None
                    else f"—/{anchor['ocr_candidate_count']}"
                )
            timing = anchor["timing_source"]
            if anchor["timing_match_score"] is not None:
                timing += f" ({anchor['timing_match_score']:.3f})"
            parts.extend(
                [
                    f"<tr><td>{appearance_order}</td>",
                    (
                        f"<td><span class=\"badge {anchor['verdict']}\">"
                        f"{anchor['verdict']}</span></td>"
                    ),
                    f"<td class=\"text\">{html.escape(anchor['text'])}</td>",
                    f"<td>{score_label(anchor['ocr_match_score'])}</td>",
                    f"<td>{score_label(anchor['ocr_anchor_coverage'])}</td>",
                    f"<td>{score_label(anchor['ocr_assignment_quality'])}</td>",
                    f"<td>{score_label(anchor['ocr_candidate_margin'])}</td>",
                    f"<td>{choice}</td>",
                    f"<td>{html.escape(timing)}</td>",
                    f"<td class=\"reasons\">{html.escape(reasons)}</td>",
                    (
                        "<td><button class=\"edit-button\" data-edit=\""
                        f"{anchor_key}"
                        "\">Edit</button></td></tr>"
                    ),
                ]
            )
        parts.append("</tbody></table></div></div></section>")
    script = r"""
    (() => {
      "use strict";
      const payload = JSON.parse(document.getElementById("override-data").textContent);
      const anchors = new Map();
      for (const slide of payload.slides) {
        for (const anchor of slide.anchors) {
          const key = `${slide.slide}:${anchor.id}`;
          anchors.set(key, {...anchor, slide: slide.slide, title: slide.title, key});
        }
      }
      const edits = new Map();
      for (const record of payload.initial_overrides) {
        edits.set(`${record.slide}:${record.anchor_id}`, {
          action: record.action,
          fragments: cleanFragments(record.fragments || []),
          selection: record.selection || null
        });
      }
      let active = null;
      let drawMode = null;
      let drawStart = null;
      let draft = null;
      const title = document.getElementById("editor-title");
      const subtitle = document.getElementById("editor-subtitle");
      const status = document.getElementById("editor-status");
      const candidateSelect = document.getElementById("candidate-select");
      const controls = [
        candidateSelect,
        document.getElementById("draw-replace"),
        document.getElementById("draw-add"),
        document.getElementById("undo-fragment"),
        document.getElementById("suppress-anchor"),
        document.getElementById("reset-anchor")
      ];

      function cleanFragments(fragments) {
        return fragments.map(fragment => ({
          x: Number(fragment.x.toFixed(6)),
          y: Number(fragment.y.toFixed(6)),
          width: Number(fragment.width.toFixed(6)),
          height: Number(fragment.height.toFixed(6))
        }));
      }

      function currentFragments(anchor) {
        const edit = edits.get(anchor.key);
        if (edit) return edit.action === "set" ? edit.fragments : [];
        return cleanFragments(anchor.automatic_fragments || []);
      }

      function setEnabled(enabled) {
        for (const control of controls) control.disabled = !enabled;
      }

      function updateCount() {
        document.getElementById("edit-count").textContent = String(edits.size);
      }

      function clearEditorFragments() {
        document.querySelectorAll(".editor-fragment,.draft-fragment").forEach(node => node.remove());
        document.querySelectorAll("tr.active-row").forEach(node => node.classList.remove("active-row"));
      }

      function appendFragment(canvas, fragment, className = "editor-fragment") {
        const node = document.createElement("div");
        node.className = className;
        node.style.left = `${fragment.x * 100}%`;
        node.style.top = `${fragment.y * 100}%`;
        node.style.width = `${fragment.width * 100}%`;
        node.style.height = `${fragment.height * 100}%`;
        canvas.appendChild(node);
        return node;
      }

      function renderActive() {
        clearEditorFragments();
        if (!active) return;
        const canvas = document.getElementById(`canvas-slide-${String(active.slide).padStart(2, "0")}`);
        for (const fragment of currentFragments(active)) appendFragment(canvas, fragment);
        document.querySelectorAll(`[data-edit="${CSS.escape(active.key)}"]`).forEach(button => {
          button.closest("tr")?.classList.add("active-row");
        });
        const edit = edits.get(active.key);
        status.textContent = edit
          ? `Pending correction: ${edit.action}${edit.selection?.kind ? ` (${edit.selection.kind})` : ""}. Save the JSON when all corrections are ready.`
          : "Automatic assignment is active. Choose a candidate or draw around the correct visible text.";
        updateCount();
      }

      function selectAnchor(key, scroll = false) {
        const anchor = anchors.get(key);
        if (!anchor) return;
        active = anchor;
        drawMode = null;
        setEnabled(true);
        title.textContent = `Slide ${String(anchor.slide).padStart(2, "0")} · anchor ${anchor.appearance_order}`;
        subtitle.textContent = anchor.text;
        candidateSelect.replaceChildren();
        const automatic = document.createElement("option");
        automatic.value = "automatic";
        automatic.textContent = "Automatic assignment";
        candidateSelect.appendChild(automatic);
        for (const candidate of anchor.candidates || []) {
          const option = document.createElement("option");
          option.value = `candidate:${candidate.rank}`;
          option.textContent = `Candidate ${candidate.rank} · quality ${candidate.assignment_quality.toFixed(3)} · OCR ${candidate.ocr_text}`;
          candidateSelect.appendChild(option);
        }
        const custom = document.createElement("option");
        custom.value = "custom";
        custom.textContent = "Custom boxes (use Draw)";
        candidateSelect.appendChild(custom);
        const edit = edits.get(key);
        if (edit?.selection?.kind === "candidate") {
          candidateSelect.value = `candidate:${edit.selection.rank}`;
        } else if (edit?.action === "set") {
          candidateSelect.value = "custom";
        } else {
          candidateSelect.value = "automatic";
        }
        renderActive();
        if (scroll) {
          document.getElementById(`slide-${String(anchor.slide).padStart(2, "0")}`)
            ?.scrollIntoView({behavior: "smooth", block: "start"});
        }
      }

      function setEdit(action, fragments, selection = null) {
        if (!active) return;
        edits.set(active.key, {action, fragments: cleanFragments(fragments), selection});
        renderActive();
      }

      candidateSelect.addEventListener("change", () => {
        if (!active) return;
        if (candidateSelect.value === "automatic") {
          edits.delete(active.key);
          renderActive();
          return;
        }
        if (candidateSelect.value === "custom") {
          status.textContent = "Use Draw replacement or Add fragment to define custom boxes.";
          return;
        }
        const rank = Number(candidateSelect.value.split(":")[1]);
        const candidate = active.candidates.find(item => item.rank === rank);
        if (candidate) {
          setEdit("set", candidate.fragments, {kind: "candidate", rank});
        }
      });

      function beginDrawing(mode) {
        if (!active) return;
        drawMode = mode;
        const canvas = document.getElementById(`canvas-slide-${String(active.slide).padStart(2, "0")}`);
        canvas.classList.add("drawing");
        status.textContent = mode === "replace"
          ? "Drag one box around the visible anchor text. Add fragments afterward for multiline text."
          : "Drag an additional box around the next line or fragment.";
      }
      document.getElementById("draw-replace").addEventListener("click", () => beginDrawing("replace"));
      document.getElementById("draw-add").addEventListener("click", () => beginDrawing("append"));
      document.getElementById("undo-fragment").addEventListener("click", () => {
        if (!active) return;
        const edit = edits.get(active.key);
        if (!edit || edit.action !== "set" || edit.fragments.length === 0) return;
        const fragments = edit.fragments.slice(0, -1);
        if (fragments.length) {
          setEdit("set", fragments, {kind: "custom"});
          candidateSelect.value = "custom";
        } else {
          edits.delete(active.key);
          candidateSelect.value = "automatic";
          renderActive();
        }
      });
      document.getElementById("suppress-anchor").addEventListener("click", () => {
        if (!active) return;
        setEdit("suppress", [], {kind: "manual"});
        candidateSelect.value = "custom";
      });
      document.getElementById("reset-anchor").addEventListener("click", () => {
        if (!active) return;
        edits.delete(active.key);
        candidateSelect.value = "automatic";
        renderActive();
      });

      function pointerPosition(event, canvas) {
        const rect = canvas.getBoundingClientRect();
        return {
          x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
          y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
        };
      }
      document.querySelectorAll(".canvas").forEach(canvas => {
        canvas.addEventListener("pointerdown", event => {
          if (!active || Number(canvas.dataset.slide) !== active.slide || !drawMode) return;
          event.preventDefault();
          canvas.setPointerCapture(event.pointerId);
          drawStart = pointerPosition(event, canvas);
          draft = appendFragment(canvas, {...drawStart, width: 0, height: 0}, "draft-fragment");
        });
        canvas.addEventListener("pointermove", event => {
          if (!drawStart || !draft) return;
          const point = pointerPosition(event, canvas);
          const fragment = {
            x: Math.min(drawStart.x, point.x),
            y: Math.min(drawStart.y, point.y),
            width: Math.abs(point.x - drawStart.x),
            height: Math.abs(point.y - drawStart.y)
          };
          draft.style.left = `${fragment.x * 100}%`;
          draft.style.top = `${fragment.y * 100}%`;
          draft.style.width = `${fragment.width * 100}%`;
          draft.style.height = `${fragment.height * 100}%`;
        });
        canvas.addEventListener("pointerup", event => {
          if (!drawStart || !draft || !active) return;
          const point = pointerPosition(event, canvas);
          const fragment = {
            x: Math.min(drawStart.x, point.x),
            y: Math.min(drawStart.y, point.y),
            width: Math.abs(point.x - drawStart.x),
            height: Math.abs(point.y - drawStart.y)
          };
          draft.remove();
          draft = null;
          drawStart = null;
          canvas.classList.remove("drawing");
          const mode = drawMode;
          drawMode = null;
          if (fragment.width < 0.002 || fragment.height < 0.002) {
            status.textContent = "Box was too small; no correction was recorded.";
            return;
          }
          const existing = edits.get(active.key);
          const fragments = mode === "append" && existing?.action === "set"
            ? [...existing.fragments, fragment]
            : [fragment];
          setEdit("set", fragments, {kind: "custom"});
          candidateSelect.value = "custom";
        });
      });

      function exportDocument() {
        const records = [...edits.entries()].map(([key, edit]) => {
          const anchor = anchors.get(key);
          return {
            slide: anchor.slide,
            anchor_id: anchor.id,
            anchor_text: anchor.text,
            action: edit.action,
            fragments: edit.action === "set" ? cleanFragments(edit.fragments) : [],
            selection: edit.selection
          };
        }).sort((a, b) => a.slide - b.slide
          || anchors.get(`${a.slide}:${a.anchor_id}`).appearance_order
          - anchors.get(`${b.slide}:${b.anchor_id}`).appearance_order);
        return {
          format: payload.format,
          source: payload.source,
          overrides: records
        };
      }

      async function saveOverrides() {
        const contents = JSON.stringify(exportDocument(), null, 2) + "\n";
        if (window.showSaveFilePicker) {
          try {
            const handle = await window.showSaveFilePicker({
              suggestedName: "anchor-overrides.json",
              types: [{description: "JSON", accept: {"application/json": [".json"]}}]
            });
            const writable = await handle.createWritable();
            await writable.write(contents);
            await writable.close();
            status.textContent = "Corrections saved. Rerun video generation with --anchor-overrides and --overwrite.";
            return;
          } catch (error) {
            if (error.name === "AbortError") return;
          }
        }
        const blob = new Blob([contents], {type: "application/json"});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "anchor-overrides.json";
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        status.textContent = "Corrections downloaded. Rerun video generation with --anchor-overrides and --overwrite.";
      }
      document.getElementById("export-overrides").addEventListener("click", saveOverrides);

      function sourcesMatch(documentValue) {
        if (documentValue?.source?.chunks_sha256 !== payload.source.chunks_sha256) return false;
        const expected = new Map(payload.source.images.map(item => [item.slide, item.sha256]));
        return Array.isArray(documentValue.source.images)
          && documentValue.source.images.every(item => expected.get(item.slide) === item.sha256)
          && documentValue.source.images.length === expected.size;
      }
      document.getElementById("import-overrides").addEventListener("change", async event => {
        const file = event.target.files?.[0];
        if (!file) return;
        try {
          const documentValue = JSON.parse(await file.text());
          if (documentValue.format !== payload.format || !sourcesMatch(documentValue)) {
            throw new Error("The file belongs to a different chunk document or slide-image set.");
          }
          if (!Array.isArray(documentValue.overrides)) throw new Error("Missing overrides list.");
          const imported = new Map();
          for (const record of documentValue.overrides) {
            const key = `${record.slide}:${record.anchor_id}`;
            if (!anchors.has(key) || !["set", "suppress"].includes(record.action)) {
              throw new Error(`Invalid override target or action: ${key}`);
            }
            imported.set(key, {
              action: record.action,
              fragments: cleanFragments(record.fragments || []),
              selection: record.selection || null
            });
          }
          edits.clear();
          for (const [key, edit] of imported) edits.set(key, edit);
          if (active) selectAnchor(active.key);
          else updateCount();
          status.textContent = `Imported ${edits.size} corrections.`;
        } catch (error) {
          status.textContent = `Import failed: ${error.message}`;
        } finally {
          event.target.value = "";
        }
      });

      document.querySelectorAll("[data-edit]").forEach(button => {
        button.addEventListener("click", () => selectAnchor(button.dataset.edit, true));
      });
      setEnabled(false);
      updateCount();
    })();
    """
    parts.extend(
        [
            f"<script type=\"application/json\" id=\"override-data\">{editor_payload}</script>",
            f"<script>{script}</script>",
            "</main></body></html>\n",
        ]
    )
    return "".join(parts)


def build_anchor_verdict_html(
    slide_plans: list[dict],
    summary: dict[str, int],
    confidence_threshold: float,
    coverage_threshold: float,
    ambiguity_margin: float,
    chunks_sha256: str,
    rerender_report_path: Path,
    python_executable: Path,
    script_path: Path,
    chunks_document: dict | None = None,
    chunks_path: Path | None = None,
    images_dir: Path | None = None,
    verdict_path: Path | None = None,
    pre_verdict_path: Path | None = None,
    pre_state_path: Path | None = None,
) -> str:
    del (
        summary,
        confidence_threshold,
        coverage_threshold,
        ambiguity_margin,
        images_dir,
    )
    override_source = anchor_override_source(slide_plans, chunks_sha256)
    source_name = (
        chunks_document.get("source")
        if isinstance(chunks_document, dict)
        else None
    )
    source_sha256 = (
        chunks_document.get("source_sha256")
        if isinstance(chunks_document, dict)
        else None
    )
    if not isinstance(source_name, str):
        source_name = "SPEAKER_NOTES.md"
    if not isinstance(source_sha256, str):
        source_sha256 = chunks_sha256
    source = {
        "speaker_notes_name": Path(source_name).name,
        "speaker_notes_sha256": source_sha256,
        "images": override_source["images"],
    }
    speaker_notes_path = (
        chunks_path.parent / source_name
        if chunks_path is not None
        else Path(source_name)
    )
    preamble = "# Reviewed Speaker Notes\n"
    if speaker_notes_path.is_file():
        source_text = speaker_notes_path.read_text(encoding="utf-8")
        heading = re.search(
            r"^##\s+Slide\s+\d+\s*-\s*.+?$",
            source_text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if heading:
            preamble = source_text[: heading.start()].rstrip() + "\n"

    editor_slides = []
    for slide_plan in slide_plans:
        image_width, image_height = slide_plan["image_size"]
        editor_anchors = []
        for anchor in slide_plan["anchors"]:
            position, _ = normalized_anchor_geometry(
                anchor["text_boxes"],
                image_width,
                image_height,
            )
            automatic_position, _ = normalized_anchor_geometry(
                anchor.get("auto_text_boxes", anchor["text_boxes"]),
                image_width,
                image_height,
            )
            manual_override = anchor.get("manual_override")
            if manual_override is not None:
                box_source = (
                    "suppress"
                    if manual_override["action"] == "suppress"
                    else "manual"
                )
            else:
                box_source = "auto" if position else "unresolved"
            editor_anchors.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "start_char": anchor.get("start_char"),
                    "end_char": anchor.get("end_char"),
                    "box": position,
                    "automatic_box": automatic_position,
                    "box_source": box_source,
                    "verdict": anchor["verdict"],
                    "review_reasons": anchor["review_reasons"],
                    "diagnostics": {
                        "ocr_score": anchor["ocr_match_score"],
                        "anchor_coverage": anchor["ocr_anchor_coverage"],
                        "candidate_count": anchor["ocr_candidate_count"],
                        "selected_candidate_rank": anchor[
                            "ocr_selected_candidate_rank"
                        ],
                        "timing_source": anchor["timing_source"],
                        "timing_score": anchor["timing_match_score"],
                    },
                }
            )
        text = slide_plan.get("text")
        if (
            isinstance(text, str)
            and all(
                isinstance(anchor.get("start_char"), int)
                and isinstance(anchor.get("end_char"), int)
                for anchor in editor_anchors
            )
        ):
            script_markdown = script_with_bold_anchors(text, editor_anchors)
        else:
            script_markdown = " ".join(
                f"**{anchor['text']}**" for anchor in editor_anchors
            )
        target_time = slide_plan.get("target_time")
        if not isinstance(target_time, str):
            seconds = max(1, round(slide_plan.get("duration_seconds", 1)))
            target_time = f"{seconds // 60}:{seconds % 60:02d}"
        editor_slides.append(
            {
                "id": slide_plan["id"],
                "slide": slide_plan["slide"],
                "title": slide_plan["title"],
                "target_time": target_time,
                "script_markdown": script_markdown,
                "original_title": slide_plan["title"],
                "original_target_time": target_time,
                "original_script_markdown": script_markdown,
                "image_path": slide_plan["image_path"],
                "image_sha256": hashlib.sha256(
                    Path(slide_plan["image_path"]).read_bytes()
                ).hexdigest(),
                "image_data_uri": slide_data_uri(
                    Path(slide_plan["image_path"])
                ),
                "anchors": editor_anchors,
            }
        )

    override_path = rerender_report_path.with_name("anchor-overrides.json")
    verdict_path = (
        verdict_path
        if verdict_path is not None
        else rerender_report_path.with_name("anchor-verdict.html")
    )
    edit_command = verdict_editor_command(
        python_executable,
        verdict_path,
        override_path,
        pre_verdict_path=pre_verdict_path,
        pre_state_path=pre_state_path,
    )
    rerender_command = (
        f'"{python_executable}" "{script_path}" '
        f'--rerender-from-report "{rerender_report_path}" '
        f'--anchor-overrides "{override_path}" --overwrite'
    )
    return build_deck_review_html(
        {
            "title": "OratorDeck Deck Verdict",
            "source": source,
            "preamble": preamble,
            "slides": editor_slides,
            "config": {
                "mode": "anchor-overrides",
                "review_filename": "deck-review.json",
                "override_filename": override_path.name,
                "allow_override_export": True,
                "override_source": override_source,
            },
                "commands": [
                    (
                        "Open the state-bound editor",
                        edit_command,
                    ),
                    (
                        "Rerender after saving box overrides",
                        rerender_command,
                    ),
                ],
        }
    )


def verdict_editor_command(
    python_executable: Path,
    post_verdict_path: Path,
    post_state_path: Path,
    *,
    pre_verdict_path: Path | None = None,
    pre_state_path: Path | None = None,
) -> str:
    if (pre_verdict_path is None) != (pre_state_path is None):
        raise RuntimeError(
            "Pre-TTS Verdict HTML and state paths must be used together"
        )
    if pre_verdict_path is None:
        return (
            f'"{python_executable}" -m oratordeck_verdict edit '
            f'"{post_verdict_path}" "{post_state_path}"'
        )
    return (
        f'"{python_executable}" -m oratordeck_verdict edit '
        f'"{pre_verdict_path}" "{pre_state_path}" '
        f'--post-html "{post_verdict_path}" '
        f'--post-state "{post_state_path}"'
    )


def ffmpeg_color(value: str) -> str:
    match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", value)
    if not match:
        raise RuntimeError("--underline-color must be a six-digit RGB hex color")
    return f"0x{match.group(1)}"


def run_command(command: list[str]) -> None:
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.returncode:
        tail = "\n".join(process.stdout.splitlines()[-30:])
        raise RuntimeError(
            f"Command failed with exit code {process.returncode}: "
            f"{' '.join(command[:8])}\n{tail}"
        )


def render_slide_clip(
    ffmpeg: str,
    image_path: Path,
    audio_path: Path,
    clip_path: Path,
    duration: float,
    anchor_plans: list[dict],
    fps: int,
    color: str,
) -> None:
    filters = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    for anchor in anchor_plans:
        for box in anchor.get("underline_boxes", []):
            filters.append(
                "drawbox="
                f"x={box['x']}:y={box['y']}:w={box['width']}:h={box['height']}:"
                f"color={color}@0.95:t=fill:"
                f"enable='between(t,{anchor['start_seconds']:.3f},{anchor['end_seconds']:.3f})'"
            )
    filters.append("format=yuv420p")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(image_path),
            "-i",
            str(audio_path),
            "-vf",
            ",".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-tune",
            "stillimage",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{duration:.6f}",
            "-shortest",
            "-movflags",
            "+faststart",
            str(clip_path),
        ]
    )


def concatenate_clips(ffmpeg: str, clips: list[Path], output: Path, work_dir: Path) -> None:
    concat_path = work_dir / "concat.txt"
    lines = []
    for clip in clips:
        escaped = str(clip.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_file", type=Path, nargs="?")
    parser.add_argument("timing_report", type=Path, nargs="?")
    parser.add_argument("images_dir", type=Path, nargs="?")
    parser.add_argument(
        "--rerender-from-report",
        type=Path,
        help="Reuse all inputs and rendering settings from an anchor-video report",
    )
    parser.add_argument("--subtitles", type=Path, help="Optional matching SRT or VTT")
    parser.add_argument("--output", type=Path, help="Final MP4 path")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Per-slide clips, audit report, animation cues, and verdict",
    )
    parser.add_argument(
        "--animation-cues-output",
        type=Path,
        help="Normalized anchor positions for slide animation tooling",
    )
    parser.add_argument(
        "--anchor-verdict-output",
        type=Path,
        help="Self-contained post-TTS Verdict phase payload",
    )
    parser.add_argument(
        "--pre-verdict-html",
        type=Path,
        help=(
            "Pre-TTS Verdict HTML to host this post-TTS phase in one "
            "switchable workbench"
        ),
    )
    parser.add_argument(
        "--pre-verdict-state",
        type=Path,
        help="Pre-TTS review JSON paired with --pre-verdict-html",
    )
    parser.add_argument(
        "--anchor-overrides",
        type=Path,
        help="Corrections saved by the post-TTS Verdict phase",
    )
    parser.add_argument(
        "--ocr-results",
        type=Path,
        help=(
            "Image-bound OCR results produced by the pre-TTS Deck Verdict; "
            "skips repeated RapidOCR inference"
        ),
    )
    parser.add_argument("--limit", type=int, help="Process only the first N generated slides")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--ocr-confidence", type=float, default=0.55)
    parser.add_argument("--ocr-match-threshold", type=float, default=0.64)
    parser.add_argument("--subtitle-match-threshold", type=float, default=0.62)
    parser.add_argument("--review-confidence-threshold", type=float, default=0.78)
    parser.add_argument("--review-coverage-threshold", type=float, default=0.65)
    parser.add_argument("--review-ambiguity-margin", type=float, default=0.04)
    parser.add_argument("--underline-color", default="#FF6B00")
    parser.add_argument("--underline-thickness", type=int, default=7)
    parser.add_argument("--min-underline-seconds", type=float, default=0.65)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the OCR/timing plan without running FFmpeg",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def hydrate_rerender_args(args: argparse.Namespace) -> None:
    report_path = (
        args.rerender_from_report.resolve()
        if args.rerender_from_report
        else None
    )
    positionals = (args.chunks_file, args.timing_report, args.images_dir)
    if report_path is None:
        if any(value is None for value in positionals):
            raise RuntimeError(
                "chunks_file, timing_report, and images_dir are required unless "
                "--rerender-from-report is used"
            )
        return
    if any(value is not None for value in positionals):
        raise RuntimeError(
            "Do not pass positional inputs together with --rerender-from-report"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("format") != REPORT_FORMAT:
        raise RuntimeError(
            f"--rerender-from-report must use format {REPORT_FORMAT}"
        )
    required_paths = {
        "chunks_file": "chunks_file",
        "timing_report": "timing_report",
        "images_dir": "images_dir",
    }
    for argument, field in required_paths.items():
        value = report.get(field)
        if not isinstance(value, str):
            raise RuntimeError(f"Rerender report is missing {field}")
        setattr(args, argument, Path(value))
    optional_paths = {
        "subtitles": "subtitles",
        "ocr_results": "ocr_results",
        "output": "output_video",
        "animation_cues_output": "anchor_animation_cues",
        "anchor_verdict_output": "anchor_verdict",
        "pre_verdict_html": "pre_tts_verdict",
        "pre_verdict_state": "pre_tts_review",
    }
    for argument, field in optional_paths.items():
        if (
            argument == "ocr_results"
            and getattr(args, "ocr_results", None) is not None
        ):
            continue
        value = report.get(field)
        if value is not None and not isinstance(value, str):
            raise RuntimeError(f"Rerender report has invalid {field}")
        setattr(args, argument, Path(value) if value else None)
    args.work_dir = report_path.parent
    for argument in (
        "fps",
        "ocr_confidence",
        "ocr_match_threshold",
        "subtitle_match_threshold",
        "review_confidence_threshold",
        "review_coverage_threshold",
        "review_ambiguity_margin",
        "underline_color",
        "underline_thickness",
        "min_underline_seconds",
        "limit",
    ):
        if argument in report:
            setattr(args, argument, report[argument])


def validate_args(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise RuntimeError("--limit must be at least 1")
    if not 1 <= args.fps <= 60:
        raise RuntimeError("--fps must be between 1 and 60")
    for name in (
        "ocr_confidence",
        "ocr_match_threshold",
        "subtitle_match_threshold",
        "review_confidence_threshold",
        "review_coverage_threshold",
        "review_ambiguity_margin",
    ):
        if not 0 <= getattr(args, name) <= 1:
            raise RuntimeError(f"--{name.replace('_', '-')} must be between 0 and 1")
    if not 1 <= args.underline_thickness <= 30:
        raise RuntimeError("--underline-thickness must be between 1 and 30")
    if not 0.1 <= args.min_underline_seconds <= 10:
        raise RuntimeError("--min-underline-seconds must be between 0.1 and 10")
    if (args.pre_verdict_html is None) != (
        args.pre_verdict_state is None
    ):
        raise RuntimeError(
            "--pre-verdict-html and --pre-verdict-state must be used together"
        )
    ffmpeg_color(args.underline_color)


def main() -> int:
    args = parse_args()
    hydrate_rerender_args(args)
    validate_args(args)
    repo_root = Path(__file__).resolve().parents[1]
    chunks_path = args.chunks_file.resolve()
    timing_path = args.timing_report.resolve()
    images_dir = args.images_dir.resolve()
    chunks_sha256 = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    chunks_document, chunks_by_id = load_chunks(chunks_path)
    timing_report, timing_items = load_timing_report(
        timing_path,
        chunks_path,
        chunks_by_id,
        repo_root,
    )
    if args.limit is not None:
        timing_items = timing_items[: args.limit]
    images = discover_images(images_dir)

    default_work_dir = repo_root / "data" / "videos" / timing_path.stem
    work_dir = args.work_dir.resolve() if args.work_dir else default_work_dir
    output_path = (
        args.output.resolve()
        if args.output
        else work_dir / f"{timing_path.stem}.mp4"
    )
    report_path = work_dir / "anchor-video-report.json"
    animation_cues_path = (
        args.animation_cues_output.resolve()
        if args.animation_cues_output
        else work_dir / "anchor-animation-cues.json"
    )
    anchor_verdict_path = (
        args.anchor_verdict_output.resolve()
        if args.anchor_verdict_output
        else work_dir / "anchor-verdict.html"
    )
    all_output_paths = [
        output_path,
        report_path,
        animation_cues_path,
        anchor_verdict_path,
    ]
    if len(set(all_output_paths)) != len(all_output_paths):
        raise RuntimeError(
            "Output video, audit report, animation-cue, and verdict paths "
            "must be distinct"
        )
    output_paths = [report_path, animation_cues_path, anchor_verdict_path]
    if not args.dry_run:
        output_paths.append(output_path)
    existing = [
        path
        for path in output_paths
        if path.exists()
    ]
    if existing and not args.overwrite:
        raise RuntimeError(
            f"Output already exists: {', '.join(str(path) for path in existing)}; "
            "pass --overwrite"
        )

    subtitle_path = args.subtitles.resolve() if args.subtitles else None
    pre_verdict_path = (
        args.pre_verdict_html.resolve()
        if args.pre_verdict_html
        else None
    )
    pre_state_path = (
        args.pre_verdict_state.resolve()
        if args.pre_verdict_state
        else None
    )
    if pre_verdict_path is not None and not pre_verdict_path.is_file():
        raise RuntimeError(
            f"Pre-TTS Verdict HTML does not exist: {pre_verdict_path}"
        )
    anchor_overrides_path = (
        args.anchor_overrides.resolve() if args.anchor_overrides else None
    )
    ocr_results_path = (
        args.ocr_results.resolve() if args.ocr_results else None
    )
    for label, input_path in (
        ("Anchor overrides", anchor_overrides_path),
        ("OCR results", ocr_results_path),
        ("Pre-TTS Verdict", pre_verdict_path),
        ("Pre-TTS review", pre_state_path),
    ):
        if input_path in all_output_paths:
            raise RuntimeError(
                f"{label} input must be distinct from all outputs"
            )
    anchor_overrides_document = (
        json.loads(anchor_overrides_path.read_text(encoding="utf-8"))
        if anchor_overrides_path
        else None
    )
    subtitle_word_timing = (
        timed_tokens(parse_subtitles(subtitle_path))
        if subtitle_path
        else []
    )
    ocr_results_sha256 = None
    if ocr_results_path:
        ocr_results_bytes = ocr_results_path.read_bytes()
        ocr_results_sha256 = hashlib.sha256(ocr_results_bytes).hexdigest()
        ocr_lines_by_slide = load_ocr_results(
            json.loads(ocr_results_bytes.decode("utf-8")),
            images,
            args.ocr_confidence,
        )
        ocr_engine = None
        ocr_source = "pre_tts_intermediate"
        print(
            f"OCR: reusing image-bound results from {ocr_results_path}",
            flush=True,
        )
    else:
        from rapidocr import RapidOCR

        ocr_lines_by_slide = None
        ocr_engine = RapidOCR()
        ocr_source = "live_rapidocr"
        print("OCR: running RapidOCR during video planning", flush=True)
    join_silence = float(timing_report.get("join_silence_ms", 0)) / 1000
    global_start = 0.0
    slide_plans = []
    resolved_anchors = 0
    subtitle_timed_anchors = 0
    total_anchors = 0

    for item_index, timing_item in enumerate(timing_items, start=1):
        chunk = chunks_by_id[timing_item["id"]]
        slide = int(chunk["slide"])
        image_path = images.get(slide)
        if image_path is None:
            raise RuntimeError(f"No image found for slide {slide}")
        with Image.open(image_path) as image:
            image_width, image_height = image.size
        ocr_lines = (
            ocr_lines_by_slide[slide]
            if ocr_lines_by_slide is not None
            else run_ocr(ocr_engine, image_path, args.ocr_confidence)
        )
        duration = timing_item["actual_seconds"]
        anchor_plans = []
        anchor_assignments = assign_ocr_anchors(
            chunk["anchors"],
            ocr_lines,
            args.ocr_match_threshold,
        )
        for anchor, assignment in zip(
            chunk["anchors"],
            anchor_assignments,
            strict=True,
        ):
            total_anchors += 1
            proportional_start, proportional_end = proportional_anchor_interval(
                anchor,
                chunk["text"],
                duration,
            )
            subtitle_interval = (
                subtitle_anchor_interval(
                    anchor,
                    chunk["text"],
                    global_start,
                    duration,
                    subtitle_word_timing,
                    args.subtitle_match_threshold,
                )
                if subtitle_word_timing
                else None
            )
            if subtitle_interval:
                start_seconds, end_seconds, timing_score = subtitle_interval
                timing_source = "subtitles"
                subtitle_timed_anchors += 1
            else:
                start_seconds, end_seconds = proportional_start, proportional_end
                timing_score = None
                timing_source = "proportional_text"
            end_seconds = min(
                duration,
                max(end_seconds, start_seconds + args.min_underline_seconds),
            )

            ocr_candidate = assignment["candidate"]
            if ocr_candidate:
                resolved_anchors += 1
                text_boxes = anchor_text_boxes(
                    anchor["text"],
                    list(ocr_candidate.lines),
                    image_width,
                    image_height,
                )
                boxes = underline_boxes(
                    text_boxes,
                    image_width,
                    image_height,
                    args.underline_thickness,
                )
                ocr_score = ocr_candidate.score
                ocr_coverage = ocr_candidate.anchor_coverage
                ocr_assignment_quality = ocr_candidate.assignment_quality
                ocr_text = " ".join(line.text for line in ocr_candidate.lines)
            else:
                text_boxes = []
                boxes = []
                ocr_score = None
                ocr_coverage = None
                ocr_assignment_quality = None
                ocr_text = None
            candidate_options = []
            for candidate_rank, candidate in enumerate(
                assignment["candidates"],
                start=1,
            ):
                candidate_text_boxes = anchor_text_boxes(
                    anchor["text"],
                    list(candidate.lines),
                    image_width,
                    image_height,
                )
                candidate_position, candidate_fragments = (
                    normalized_anchor_geometry(
                        candidate_text_boxes,
                        image_width,
                        image_height,
                    )
                )
                candidate_options.append(
                    {
                        "rank": candidate_rank,
                        "score": round(candidate.score, 6),
                        "anchor_coverage": round(candidate.anchor_coverage, 6),
                        "assignment_quality": round(
                            candidate.assignment_quality,
                            6,
                        ),
                        "ocr_text": " ".join(
                            line.text for line in candidate.lines
                        ),
                        "position": candidate_position,
                        "fragments": candidate_fragments,
                    }
                )
            anchor_plans.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "start_char": anchor["start_char"],
                    "end_char": anchor["end_char"],
                    "start_seconds": round(start_seconds, 6),
                    "end_seconds": round(end_seconds, 6),
                    "global_start_seconds": round(global_start + start_seconds, 6),
                    "global_end_seconds": round(global_start + end_seconds, 6),
                    "timing_source": timing_source,
                    "timing_match_score": (
                        round(timing_score, 6) if timing_score is not None else None
                    ),
                    "ocr_status": "resolved" if boxes else "unresolved",
                    "ocr_match_score": (
                        round(ocr_score, 6) if ocr_score is not None else None
                    ),
                    "ocr_anchor_coverage": (
                        round(ocr_coverage, 6)
                        if ocr_coverage is not None
                        else None
                    ),
                    "ocr_assignment_quality": (
                        round(ocr_assignment_quality, 6)
                        if ocr_assignment_quality is not None
                        else None
                    ),
                    "ocr_candidate_count": assignment["candidate_count"],
                    "ocr_candidate_margin": (
                        round(assignment["candidate_margin"], 6)
                        if assignment["candidate_margin"] is not None
                        else None
                    ),
                    "ocr_selected_candidate_rank": assignment["selected_rank"],
                    "ocr_assignment_changed": assignment["assignment_changed"],
                    "ocr_shared_with": assignment["shared_with"],
                    "ocr_unresolved_reason": assignment["unresolved_reason"],
                    "ocr_text": ocr_text,
                    "ocr_candidates": candidate_options,
                    "manual_override": None,
                    "source_geometry_out_of_bounds": (
                        ocr_lines_out_of_bounds(
                            ocr_candidate.lines,
                            image_width,
                            image_height,
                        )
                        if ocr_candidate
                        else False
                    ),
                    "auto_text_boxes": text_boxes,
                    "text_boxes": text_boxes,
                    "underline_boxes": boxes,
                }
            )

        clip_path = work_dir / "clips" / f"{item_index:03d}-{chunk['id']}.mp4"
        slide_plans.append(
            {
                "id": chunk["id"],
                "slide": slide,
                "title": chunk["title"],
                "target_time": chunk["target_time"],
                "text": chunk["text"],
                "image_path": str(image_path),
                "image_size": [image_width, image_height],
                "audio_path": str(timing_item["audio_path_resolved"]),
                "clip_path": str(clip_path),
                "start_seconds": round(global_start, 6),
                "duration_seconds": round(duration, 6),
                "ocr_lines": [
                    {
                        "text": line.text,
                        "confidence": round(line.score, 6),
                        "box": [round(value, 2) for value in line.box],
                    }
                    for line in ocr_lines
                ],
                "anchors": anchor_plans,
            }
        )
        slide_resolved = sum(
            1 for anchor in anchor_plans if anchor["ocr_status"] == "resolved"
        )
        print(
            f"[{item_index:02d}/{len(timing_items):02d}] {chunk['id']}: "
            f"OCR {slide_resolved}/{len(anchor_plans)} anchors, "
            f"duration {clock(duration)}",
            flush=True,
        )
        global_start += duration
        if item_index < len(timing_items):
            global_start += join_silence

    override_summary = {"total": 0, "set": 0, "suppress": 0}
    if anchor_overrides_document is not None:
        override_summary = apply_anchor_overrides(
            slide_plans,
            anchor_overrides_document,
            chunks_sha256,
            args.underline_thickness,
        )
    annotate_anchor_geometry(slide_plans)
    resolved_anchors = sum(
        anchor["ocr_status"] == "resolved"
        for slide_plan in slide_plans
        for anchor in slide_plan["anchors"]
    )
    suppressed_anchors = sum(
        anchor["ocr_status"] == "suppressed"
        for slide_plan in slide_plans
        for anchor in slide_plan["anchors"]
    )
    verdict_summary = apply_anchor_verdicts(
        slide_plans,
        args.review_confidence_threshold,
        args.review_coverage_threshold,
        args.review_ambiguity_margin,
    )
    global_reassigned_anchors = sum(
        anchor["ocr_assignment_changed"]
        for slide_plan in slide_plans
        for anchor in slide_plan["anchors"]
    )
    shared_anchor_assignments = sum(
        bool(anchor["ocr_shared_with"])
        for slide_plan in slide_plans
        for anchor in slide_plan["anchors"]
    )
    audit_report = {
        "format": REPORT_FORMAT,
        "status": "planned" if args.dry_run else "rendering",
        "chunks_file": str(chunks_path),
        "chunks_sha256": chunks_sha256,
        "timing_report": str(timing_path),
        "images_dir": str(images_dir),
        "subtitles": str(subtitle_path) if subtitle_path else None,
        "ocr_results": (
            str(ocr_results_path) if ocr_results_path else None
        ),
        "ocr_results_sha256": ocr_results_sha256,
        "ocr_source": ocr_source,
        "anchor_overrides": (
            str(anchor_overrides_path) if anchor_overrides_path else None
        ),
        "anchor_overrides_sha256": (
            hashlib.sha256(anchor_overrides_path.read_bytes()).hexdigest()
            if anchor_overrides_path
            else None
        ),
        "anchor_override_summary": override_summary,
        "rerendered_from_report": (
            str(args.rerender_from_report.resolve())
            if args.rerender_from_report
            else None
        ),
        "rerendered_from_report_sha256": (
            hashlib.sha256(
                args.rerender_from_report.resolve().read_bytes()
            ).hexdigest()
            if args.rerender_from_report
            else None
        ),
        "subtitle_timing_available": bool(subtitle_word_timing),
        "output_video": str(output_path),
        "anchor_animation_cues": str(animation_cues_path),
        "anchor_verdict": str(anchor_verdict_path),
        "pre_tts_verdict": (
            str(pre_verdict_path) if pre_verdict_path else None
        ),
        "pre_tts_review": (
            str(pre_state_path) if pre_state_path else None
        ),
        "anchor_matching_method": OCR_MATCHING_METHOD,
        "python_executable": sys.executable,
        "video_script": str(Path(__file__).resolve()),
        "ocr_confidence": args.ocr_confidence,
        "ocr_match_threshold": args.ocr_match_threshold,
        "subtitle_match_threshold": args.subtitle_match_threshold,
        "review_confidence_threshold": args.review_confidence_threshold,
        "review_coverage_threshold": args.review_coverage_threshold,
        "review_ambiguity_margin": args.review_ambiguity_margin,
        "fps": args.fps,
        "limit": args.limit,
        "underline_color": args.underline_color,
        "underline_thickness": args.underline_thickness,
        "min_underline_seconds": args.min_underline_seconds,
        "total_duration_seconds": round(global_start, 6),
        "slide_count": len(slide_plans),
        "anchor_count": total_anchors,
        "resolved_anchor_count": resolved_anchors,
        "suppressed_anchor_count": suppressed_anchors,
        "unresolved_anchor_count": (
            total_anchors - resolved_anchors - suppressed_anchors
        ),
        "subtitle_timed_anchor_count": subtitle_timed_anchors,
        "proportional_timed_anchor_count": total_anchors - subtitle_timed_anchors,
        "global_reassigned_anchor_count": global_reassigned_anchors,
        "shared_anchor_assignment_count": shared_anchor_assignments,
        "anchor_verdict_summary": verdict_summary,
        "slides": slide_plans,
    }
    animation_cues = build_animation_cues(
        slide_plans,
        chunks_path,
        images_dir,
    )
    anchor_verdict_html = build_anchor_verdict_html(
        slide_plans,
        verdict_summary,
        args.review_confidence_threshold,
        args.review_coverage_threshold,
        args.review_ambiguity_margin,
        chunks_sha256,
        report_path,
        Path(sys.executable),
        Path(__file__).resolve(),
        chunks_document=chunks_document,
        chunks_path=chunks_path,
        images_dir=images_dir,
        verdict_path=anchor_verdict_path,
        pre_verdict_path=pre_verdict_path,
        pre_state_path=pre_state_path,
    )
    editor_command = verdict_editor_command(
        Path(sys.executable),
        anchor_verdict_path,
        anchor_verdict_path.with_name("anchor-overrides.json"),
        pre_verdict_path=pre_verdict_path,
        pre_state_path=pre_state_path,
    )
    print(
        f"Plan: {len(slide_plans)} slides, OCR resolved "
        f"{resolved_anchors}/{total_anchors} anchors; subtitle timing "
        f"{subtitle_timed_anchors}/{total_anchors}.",
        flush=True,
    )
    print(
        "Verdict: "
        f"{verdict_summary['pass']} pass, "
        f"{verdict_summary['corrected']} corrected, "
        f"{verdict_summary['review']} review, "
        f"{verdict_summary['unresolved']} unresolved.",
        flush=True,
    )
    work_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_path, audit_report)
    write_json(animation_cues_path, animation_cues)
    write_text(anchor_verdict_path, anchor_verdict_html)
    if args.dry_run:
        print(f"Audit report: {report_path}")
        print(f"Animation cues: {animation_cues_path}")
        print(f"Anchor verdict: {anchor_verdict_path}")
        print(
            "Open the state-bound editor:\n"
            f"  {editor_command}"
        )
        return 0

    ffmpeg = get_ffmpeg_exe()
    color = ffmpeg_color(args.underline_color)
    clip_paths = []
    try:
        for index, slide_plan in enumerate(slide_plans, start=1):
            clip_path = Path(slide_plan["clip_path"])
            print(
                f"Rendering clip {index}/{len(slide_plans)}: {slide_plan['id']}",
                flush=True,
            )
            render_slide_clip(
                ffmpeg,
                Path(slide_plan["image_path"]),
                Path(slide_plan["audio_path"]),
                clip_path,
                slide_plan["duration_seconds"],
                slide_plan["anchors"],
                args.fps,
                color,
            )
            clip_paths.append(clip_path)
        print(f"Concatenating {len(clip_paths)} clips...", flush=True)
        concatenate_clips(ffmpeg, clip_paths, output_path, work_dir)
        audit_report["status"] = "completed"
        write_json(report_path, audit_report)
    except Exception as error:
        audit_report["status"] = "failed"
        audit_report["error"] = str(error)
        write_json(report_path, audit_report)
        raise

    print(f"Video: {output_path}")
    print(f"Audit report: {report_path}")
    print(f"Animation cues: {animation_cues_path}")
    print(f"Anchor verdict: {anchor_verdict_path}")
    print(
        "Open the state-bound editor:\n"
        f"  {editor_command}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
