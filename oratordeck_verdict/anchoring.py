"""CPU OCR matching and normalized anchor geometry for Deck Verdict."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

IMAGE_RE = re.compile(
    r"^slide-(\d+)(?:[_-].*)?\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
OCR_RESULTS_FORMAT = "oratordeck.ocr-results.v1"
OCR_MATCHING_METHOD = "global_beam_assignment_v1"


@dataclass(frozen=True)
class TextToken:
    value: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class OCRLine:
    text: str
    score: float
    box: tuple[float, float, float, float]
    tokens: tuple[TextToken, ...]


@dataclass(frozen=True)
class OCRCandidate:
    start_line: int
    end_line: int
    score: float
    anchor_coverage: float
    token_keys: frozenset[tuple[int, int]]
    lines: tuple[OCRLine, ...]
    reading_position: float

    @property
    def assignment_quality(self) -> float:
        return 0.70 * self.score + 0.30 * self.anchor_coverage


def normalize_word(word: str) -> str:
    return word.lower().replace("’", "'").strip("'")


def text_tokens(text: str) -> list[TextToken]:
    return [
        TextToken(normalize_word(match.group()), match.start(), match.end())
        for match in WORD_RE.finditer(text)
    ]


def discover_images(images_dir: Path) -> dict[int, Path]:
    result = {}
    for path in images_dir.iterdir():
        match = IMAGE_RE.match(path.name)
        if not match:
            continue
        slide = int(match.group(1))
        if slide in result:
            raise RuntimeError(
                f"Multiple images found for slide {slide}: "
                f"{result[slide]} and {path}"
            )
        result[slide] = path.resolve()
    if not result:
        raise RuntimeError(f"No slide-NN images found in {images_dir}")
    return result


def run_ocr(engine, image_path: Path, threshold: float) -> list[OCRLine]:
    result = engine(str(image_path))
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    lines = []
    for quadrilateral, text, score in zip(
        boxes,
        texts,
        scores,
        strict=False,
    ):
        score = float(score)
        if score < threshold or not str(text).strip():
            continue
        xs = [float(point[0]) for point in quadrilateral]
        ys = [float(point[1]) for point in quadrilateral]
        clean_text = str(text).strip()
        lines.append(
            OCRLine(
                text=clean_text,
                score=score,
                box=(min(xs), min(ys), max(xs), max(ys)),
                tokens=tuple(text_tokens(clean_text)),
            )
        )
    return lines


def filter_ocr_lines(
    lines: list[OCRLine],
    threshold: float,
) -> list[OCRLine]:
    """Apply a consumer threshold to reusable OCR output."""
    if not 0 <= threshold <= 1:
        raise RuntimeError("OCR confidence threshold must be between 0 and 1")
    return [line for line in lines if line.score >= threshold]


def build_ocr_results(
    images: dict[int, Path],
    image_sizes: dict[int, tuple[int, int]],
    lines_by_slide: dict[int, list[OCRLine]],
    *,
    stored_line_min_score: float = 0.0,
    engine_name: str = "RapidOCR",
) -> dict:
    """Serialize raw OCR lines for reuse after the pre-TTS review."""
    if not isinstance(engine_name, str) or not engine_name.strip():
        raise RuntimeError("OCR engine name must be a non-empty string")
    if not 0 <= stored_line_min_score <= 1:
        raise RuntimeError("stored_line_min_score must be between 0 and 1")
    if set(images) != set(image_sizes) or set(images) != set(lines_by_slide):
        raise RuntimeError(
            "OCR result images, dimensions, and line sets must match exactly"
        )
    slides = []
    for slide, image_path in sorted(images.items()):
        width, height = image_sizes[slide]
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Slide {slide} has invalid image dimensions")
        slides.append(
            {
                "slide": slide,
                "image_sha256": hashlib.sha256(
                    image_path.read_bytes()
                ).hexdigest(),
                "image_width": width,
                "image_height": height,
                "lines": [
                    {
                        "text": line.text,
                        "score": round(float(line.score), 8),
                        "box": [
                            round(float(coordinate), 6)
                            for coordinate in line.box
                        ],
                    }
                    for line in lines_by_slide[slide]
                    if line.score >= stored_line_min_score
                ],
            }
        )
    return {
        "format": OCR_RESULTS_FORMAT,
        "engine": engine_name,
        "stored_line_min_score": stored_line_min_score,
        "slides": slides,
    }


def load_ocr_results(
    document: object,
    images: dict[int, Path],
    requested_confidence: float,
) -> dict[int, list[OCRLine]]:
    """Validate image-bound OCR JSON and return thresholded OCR lines."""
    if not isinstance(document, dict):
        raise RuntimeError("OCR results must be a JSON object")
    if document.get("format") != OCR_RESULTS_FORMAT:
        raise RuntimeError(
            f"OCR results must use format {OCR_RESULTS_FORMAT}"
        )
    engine_name = document.get("engine")
    if not isinstance(engine_name, str) or not engine_name.strip():
        raise RuntimeError("OCR results have no valid engine name")
    floor = document.get("stored_line_min_score")
    if (
        isinstance(floor, bool)
        or not isinstance(floor, (int, float))
        or not math.isfinite(float(floor))
        or not 0 <= float(floor) <= 1
    ):
        raise RuntimeError("OCR results have an invalid stored-line score")
    if requested_confidence + 1e-12 < float(floor):
        raise RuntimeError(
            "OCR results discarded lines below "
            f"{float(floor):.3f}, but video requested "
            f"{requested_confidence:.3f}"
        )
    records = document.get("slides")
    if not isinstance(records, list):
        raise RuntimeError("OCR results must contain a slides list")
    expected_slides = set(images)
    actual_slides = set()
    loaded: dict[int, list[OCRLine]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RuntimeError(f"OCR slide record {index} must be an object")
        slide = record.get("slide")
        if (
            isinstance(slide, bool)
            or not isinstance(slide, int)
            or slide <= 0
            or slide in actual_slides
        ):
            raise RuntimeError(f"OCR slide record {index} has invalid identity")
        actual_slides.add(slide)
        image_path = images.get(slide)
        if image_path is None:
            raise RuntimeError(f"OCR results contain unexpected slide {slide}")
        actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if record.get("image_sha256") != actual_hash:
            raise RuntimeError(
                f"OCR results belong to a different image for slide {slide}"
            )
        width = record.get("image_width")
        height = record.get("image_height")
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
        ):
            raise RuntimeError(
                f"OCR results have invalid dimensions for slide {slide}"
            )
        line_records = record.get("lines")
        if not isinstance(line_records, list):
            raise RuntimeError(
                f"OCR results have no line list for slide {slide}"
            )
        lines = []
        for line_index, line_record in enumerate(line_records):
            label = f"OCR slide {slide} line {line_index}"
            if not isinstance(line_record, dict):
                raise RuntimeError(f"{label} must be an object")
            text = line_record.get("text")
            score = line_record.get("score")
            box = line_record.get("box")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError(f"{label} has invalid text")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not 0 <= float(score) <= 1
            ):
                raise RuntimeError(f"{label} has invalid confidence")
            if not isinstance(box, list) or len(box) != 4:
                raise RuntimeError(f"{label} has invalid geometry")
            coordinates = []
            for coordinate in box:
                if (
                    isinstance(coordinate, bool)
                    or not isinstance(coordinate, (int, float))
                    or not math.isfinite(float(coordinate))
                ):
                    raise RuntimeError(f"{label} has non-finite geometry")
                coordinates.append(float(coordinate))
            x1, y1, x2, y2 = coordinates
            if x2 <= x1 or y2 <= y1:
                raise RuntimeError(f"{label} has an empty bounding box")
            lines.append(
                OCRLine(
                    text=text.strip(),
                    score=float(score),
                    box=(x1, y1, x2, y2),
                    tokens=tuple(text_tokens(text.strip())),
                )
            )
        loaded[slide] = filter_ocr_lines(lines, requested_confidence)
    if actual_slides != expected_slides:
        missing = sorted(expected_slides - actual_slides)
        raise RuntimeError(
            "OCR results do not cover the current slide-image set"
            + (f"; missing slides {missing}" if missing else "")
        )
    return loaded


def score_ocr_window(
    anchor_words: list[str],
    lines: list[OCRLine] | tuple[OCRLine, ...],
) -> float:
    candidate_words = [token.value for line in lines for token in line.tokens]
    if not candidate_words:
        return 0.0
    word_score = SequenceMatcher(
        None,
        anchor_words,
        candidate_words,
        autojunk=False,
    ).ratio()
    anchor_text = " ".join(anchor_words)
    candidate_text = " ".join(candidate_words)
    character_score = SequenceMatcher(
        None,
        anchor_text,
        candidate_text,
        autojunk=False,
    ).ratio()
    score = 0.65 * word_score + 0.35 * character_score
    shorter, longer = sorted((len(anchor_words), len(candidate_words)))
    if shorter and (
        anchor_text in candidate_text or candidate_text in anchor_text
    ):
        coverage = shorter / longer
        score = max(score, 0.80 + 0.20 * coverage)
    length_penalty = (
        0.02
        * abs(len(anchor_words) - len(candidate_words))
        / max(1, len(anchor_words))
    )
    return max(0.0, score - length_penalty)


def selected_ocr_token_indexes(
    anchor_words: list[str],
    lines: list[OCRLine] | tuple[OCRLine, ...],
) -> tuple[dict[int, list[int]], int]:
    flattened = [
        (line_index, token_index, token.value)
        for line_index, line in enumerate(lines)
        for token_index, token in enumerate(line.tokens)
    ]
    candidate_words = [item[2] for item in flattened]
    matcher = SequenceMatcher(
        None,
        anchor_words,
        candidate_words,
        autojunk=False,
    )
    selected_by_line: dict[int, list[int]] = {}
    matched_count = 0
    for block in matcher.get_matching_blocks():
        matched_count += block.size
        for offset in range(block.size):
            line_index, token_index, _ = flattened[block.b + offset]
            selected_by_line.setdefault(line_index, []).append(token_index)
    return selected_by_line, matched_count


def candidate_token_overlap(
    first: OCRCandidate,
    second: OCRCandidate,
) -> float:
    if not first.token_keys or not second.token_keys:
        return 0.0
    overlap = len(first.token_keys & second.token_keys)
    return overlap / min(len(first.token_keys), len(second.token_keys))


def ocr_anchor_candidates(
    anchor_text: str,
    lines: list[OCRLine],
    threshold: float,
    limit: int = 8,
) -> list[OCRCandidate]:
    anchor_words = [token.value for token in text_tokens(anchor_text)]
    if not anchor_words or not lines:
        return []
    maximum_lines = min(8, max(2, len(anchor_words) // 2 + 2))
    candidates_by_tokens: dict[
        frozenset[tuple[int, int]],
        OCRCandidate,
    ] = {}
    for start in range(len(lines)):
        for end in range(
            start + 1,
            min(len(lines), start + maximum_lines) + 1,
        ):
            window = tuple(lines[start:end])
            score = score_ocr_window(anchor_words, window)
            if score < threshold:
                continue
            selected_by_line, matched_count = selected_ocr_token_indexes(
                anchor_words,
                window,
            )
            token_keys = frozenset(
                (start + line_index, token_index)
                for line_index, token_indexes in selected_by_line.items()
                for token_index in token_indexes
            )
            if not token_keys:
                token_keys = frozenset(
                    (start + line_index, token_index)
                    for line_index, line in enumerate(window)
                    for token_index, _ in enumerate(line.tokens)
                )
            candidate = OCRCandidate(
                start_line=start,
                end_line=end,
                score=score,
                anchor_coverage=min(
                    1.0,
                    matched_count / len(anchor_words),
                ),
                token_keys=token_keys,
                lines=window,
                reading_position=(start + end) / (2 * len(lines)),
            )
            existing = candidates_by_tokens.get(token_keys)
            candidate_rank = (
                candidate.assignment_quality,
                candidate.score,
                -(candidate.end_line - candidate.start_line),
            )
            existing_rank = (
                (
                    existing.assignment_quality,
                    existing.score,
                    -(existing.end_line - existing.start_line),
                )
                if existing
                else None
            )
            if existing_rank is None or candidate_rank > existing_rank:
                candidates_by_tokens[token_keys] = candidate
    candidates = sorted(
        candidates_by_tokens.values(),
        key=lambda candidate: (
            candidate.assignment_quality,
            candidate.score,
            -(candidate.end_line - candidate.start_line),
            -candidate.start_line,
        ),
        reverse=True,
    )
    spatially_distinct = []
    for candidate in candidates:
        if any(
            candidate_token_overlap(candidate, existing) >= 0.5
            for existing in spatially_distinct
        ):
            continue
        spatially_distinct.append(candidate)
        if len(spatially_distinct) == limit:
            break
    return spatially_distinct


def normalized_words(text: str) -> tuple[str, ...]:
    return tuple(token.value for token in text_tokens(text))


def contains_word_sequence(
    container: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    if not sequence or len(sequence) > len(container):
        return False
    return any(
        container[index : index + len(sequence)] == sequence
        for index in range(len(container) - len(sequence) + 1)
    )


def anchors_can_share_tokens(first_text: str, second_text: str) -> bool:
    first = normalized_words(first_text)
    second = normalized_words(second_text)
    return contains_word_sequence(first, second) or contains_word_sequence(
        second,
        first,
    )


def select_global_anchor_candidates(
    anchor_texts: list[str],
    candidate_lists: list[list[OCRCandidate]],
    beam_width: int = 256,
) -> list[OCRCandidate | None]:
    states: list[
        tuple[float, int, tuple[OCRCandidate | None, ...]]
    ] = [(0.0, 0, ())]
    for anchor_index, candidates in enumerate(candidate_lists):
        expanded: list[
            tuple[float, int, tuple[OCRCandidate | None, ...]]
        ] = []
        for state_score, resolved_count, assignments in states:
            for candidate in [*candidates, None]:
                if candidate is None:
                    expanded.append(
                        (state_score, resolved_count, (*assignments, None))
                    )
                    continue
                adjustment = 0.0
                compatible = True
                previous_candidate = None
                for previous_index, assigned in enumerate(assignments):
                    if assigned is None:
                        continue
                    previous_candidate = assigned
                    overlap = candidate_token_overlap(candidate, assigned)
                    if overlap < 0.5:
                        continue
                    if not anchors_can_share_tokens(
                        anchor_texts[anchor_index],
                        anchor_texts[previous_index],
                    ):
                        compatible = False
                        break
                    if normalized_words(
                        anchor_texts[anchor_index]
                    ) == normalized_words(anchor_texts[previous_index]):
                        adjustment -= 0.025 * overlap
                if not compatible:
                    continue
                if previous_candidate is not None:
                    reading_delta = (
                        candidate.reading_position
                        - previous_candidate.reading_position
                    )
                    if reading_delta >= -0.02:
                        adjustment += 0.012
                    else:
                        adjustment -= min(
                            0.035,
                            abs(reading_delta) * 0.05,
                        )
                expanded.append(
                    (
                        state_score
                        + candidate.assignment_quality
                        + adjustment,
                        resolved_count + 1,
                        (*assignments, candidate),
                    )
                )
        expanded.sort(
            key=lambda state: (state[0], state[1]),
            reverse=True,
        )
        states = expanded[:beam_width]
    return list(states[0][2])


def assign_ocr_anchors(
    anchors: list[dict],
    lines: list[OCRLine],
    threshold: float,
) -> list[dict]:
    anchor_texts = [anchor["text"] for anchor in anchors]
    candidate_lists = [
        ocr_anchor_candidates(anchor_text, lines, threshold)
        for anchor_text in anchor_texts
    ]
    selected = select_global_anchor_candidates(
        anchor_texts,
        candidate_lists,
    )
    shared_with: list[list[str]] = [[] for _ in anchors]
    for first_index, first_candidate in enumerate(selected):
        if first_candidate is None:
            continue
        for second_index in range(first_index + 1, len(selected)):
            second_candidate = selected[second_index]
            if second_candidate is None:
                continue
            if (
                candidate_token_overlap(
                    first_candidate,
                    second_candidate,
                )
                < 0.5
            ):
                continue
            shared_with[first_index].append(anchors[second_index]["id"])
            shared_with[second_index].append(anchors[first_index]["id"])

    assignments = []
    for index, (candidates, candidate) in enumerate(
        zip(candidate_lists, selected, strict=True)
    ):
        selected_rank = (
            candidates.index(candidate) + 1
            if candidate is not None
            else None
        )
        candidate_margin = (
            candidates[0].assignment_quality
            - candidates[1].assignment_quality
            if len(candidates) > 1
            else None
        )
        assignments.append(
            {
                "candidate": candidate,
                "candidates": candidates,
                "candidate_count": len(candidates),
                "candidate_margin": candidate_margin,
                "selected_rank": selected_rank,
                "assignment_changed": (
                    selected_rank is not None and selected_rank != 1
                ),
                "shared_with": shared_with[index],
                "unresolved_reason": (
                    None
                    if candidate is not None
                    else (
                        "global_conflict"
                        if candidates
                        else "no_candidate_above_threshold"
                    )
                ),
            }
        )
    return assignments


def match_ocr_anchor(
    anchor_text: str,
    lines: list[OCRLine],
    threshold: float,
) -> dict | None:
    """Return the best compatible OCR window for legacy callers."""
    candidates = ocr_anchor_candidates(
        anchor_text,
        lines,
        threshold,
        limit=1,
    )
    if not candidates:
        return None
    best = candidates[0]
    return {
        "start_line": best.start_line,
        "end_line": best.end_line,
        "score": best.score,
        "anchor_coverage": best.anchor_coverage,
        "lines": list(best.lines),
    }


def anchor_text_boxes(
    anchor_text: str,
    matched_lines: list[OCRLine],
    image_width: int,
    image_height: int,
) -> list[dict]:
    anchor_words = [token.value for token in text_tokens(anchor_text)]
    selected_by_line, _ = selected_ocr_token_indexes(
        anchor_words,
        matched_lines,
    )
    boxes = []
    for line_index, line in enumerate(matched_lines):
        x1, y1, x2, y2 = line.box
        token_indexes = selected_by_line.get(line_index)
        if token_indexes and line.tokens and line.text:
            first_token = line.tokens[min(token_indexes)]
            last_token = line.tokens[max(token_indexes)]
            line_length = max(1, len(line.text))
            selected_x1 = (
                x1
                + (x2 - x1) * first_token.start_char / line_length
            )
            selected_x2 = (
                x1
                + (x2 - x1) * last_token.end_char / line_length
            )
        else:
            selected_x1, selected_x2 = x1, x2
        left = min(max(0, round(selected_x1)), image_width - 1)
        right = min(image_width, max(left + 1, round(selected_x2)))
        top = min(max(0, round(y1)), image_height - 1)
        bottom = min(image_height, max(top + 1, round(y2)))
        boxes.append(
            {
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
                "ocr_text": line.text,
            }
        )
    return boxes


def normalized_box(
    box: dict,
    image_width: int,
    image_height: int,
) -> dict[str, float]:
    left = min(image_width, max(0.0, float(box["x"])))
    top = min(image_height, max(0.0, float(box["y"])))
    right = min(
        image_width,
        max(left, float(box["x"]) + float(box["width"])),
    )
    bottom = min(
        image_height,
        max(top, float(box["y"]) + float(box["height"])),
    )
    return {
        "x": round(left / image_width, 6),
        "y": round(top / image_height, 6),
        "width": round((right - left) / image_width, 6),
        "height": round((bottom - top) / image_height, 6),
        "center_x": round((left + right) / (2 * image_width), 6),
        "center_y": round((top + bottom) / (2 * image_height), 6),
    }


def normalized_anchor_geometry(
    text_boxes: list[dict],
    image_width: int,
    image_height: int,
) -> tuple[dict[str, float] | None, list[dict[str, float]]]:
    if not text_boxes:
        return None, []
    left = min(box["x"] for box in text_boxes)
    top = min(box["y"] for box in text_boxes)
    right = max(box["x"] + box["width"] for box in text_boxes)
    bottom = max(box["y"] + box["height"] for box in text_boxes)
    position = normalized_box(
        {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        },
        image_width,
        image_height,
    )
    fragments = [
        normalized_box(box, image_width, image_height)
        for box in text_boxes
    ]
    return position, fragments
