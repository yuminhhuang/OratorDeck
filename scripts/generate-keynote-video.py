#!/usr/bin/env python3
"""Build a slide video with timed underlines for bold speaker-note anchors.

The chunk document supplies the anchor text and character offsets. The timing
report supplies one indivisible WAV per slide. Optional SRT/VTT captions give
the preferred anchor timing; otherwise timing is estimated from each anchor's
position in the spoken slide text. RapidOCR locates the corresponding visual
wording, and the bundled imageio-ffmpeg executable renders one clip per slide
before concatenating the clips. The OCR plan also produces a slide-animation
cue file with narration order and normalized anchor text positions.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import soundfile as sf
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image

CHUNK_FORMAT = "oratordeck.speaker-notes-chunks.v1"
TIMING_FORMAT = "oratordeck.keynote-timing-report.v1"
REPORT_FORMAT = "oratordeck.anchor-video-report.v1"
ANIMATION_CUES_FORMAT = "oratordeck.anchor-animation-cues.v1"
IMAGE_RE = re.compile(r"^slide-(\d+)(?:[_-].*)?\.(?:png|jpe?g|webp)$", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TextToken:
    value: str
    start_char: int
    end_char: int


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


@dataclass(frozen=True)
class OCRLine:
    text: str
    score: float
    box: tuple[float, float, float, float]
    tokens: tuple[TextToken, ...]


def normalize_word(word: str) -> str:
    return word.lower().replace("’", "'").strip("'")


def text_tokens(text: str) -> list[TextToken]:
    return [
        TextToken(normalize_word(match.group()), match.start(), match.end())
        for match in WORD_RE.finditer(text)
    ]


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


def discover_images(images_dir: Path) -> dict[int, Path]:
    result = {}
    for path in images_dir.iterdir():
        match = IMAGE_RE.match(path.name)
        if not match:
            continue
        slide = int(match.group(1))
        if slide in result:
            raise RuntimeError(
                f"Multiple images found for slide {slide}: {result[slide]} and {path}"
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
    for quadrilateral, text, score in zip(boxes, texts, scores, strict=False):
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


def score_ocr_window(anchor_words: list[str], lines: list[OCRLine]) -> float:
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
        anchor_text in candidate_text
        or candidate_text in anchor_text
    ):
        coverage = shorter / longer
        score = max(score, 0.80 + 0.20 * coverage)
    return max(0.0, score - 0.02 * abs(len(anchor_words) - len(candidate_words)) / max(1, len(anchor_words)))


def match_ocr_anchor(
    anchor_text: str,
    lines: list[OCRLine],
    threshold: float,
) -> dict | None:
    anchor_words = [token.value for token in text_tokens(anchor_text)]
    if not anchor_words or not lines:
        return None
    maximum_lines = min(8, max(2, len(anchor_words) // 2 + 2))
    best = None
    for start in range(len(lines)):
        for end in range(start + 1, min(len(lines), start + maximum_lines) + 1):
            window = lines[start:end]
            score = score_ocr_window(anchor_words, window)
            rank = (score, -(end - start))
            if best is None or rank > best[0]:
                best = (rank, start, end, score)
    if best is None or best[3] < threshold:
        return None
    return {
        "start_line": best[1],
        "end_line": best[2],
        "score": best[3],
        "lines": lines[best[1] : best[2]],
    }


def anchor_text_boxes(
    anchor_text: str,
    matched_lines: list[OCRLine],
    image_width: int,
    image_height: int,
) -> list[dict]:
    anchor_words = [token.value for token in text_tokens(anchor_text)]
    flattened = [
        (line_index, token_index, token.value)
        for line_index, line in enumerate(matched_lines)
        for token_index, token in enumerate(line.tokens)
    ]
    candidate_words = [item[2] for item in flattened]
    matcher = SequenceMatcher(None, anchor_words, candidate_words, autojunk=False)
    selected_by_line: dict[int, list[int]] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            line_index, token_index, _ = flattened[block.b + offset]
            selected_by_line.setdefault(line_index, []).append(token_index)

    boxes = []
    for line_index, line in enumerate(matched_lines):
        x1, y1, x2, y2 = line.box
        token_indexes = selected_by_line.get(line_index)
        if token_indexes and line.tokens and line.text:
            first_token = line.tokens[min(token_indexes)]
            last_token = line.tokens[max(token_indexes)]
            line_length = max(1, len(line.text))
            selected_x1 = x1 + (x2 - x1) * first_token.start_char / line_length
            selected_x2 = x1 + (x2 - x1) * last_token.end_char / line_length
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


def build_animation_cues(
    slide_plans: list[dict],
    chunks_path: Path,
    images_dir: Path,
) -> dict:
    slides = []
    anchor_count = 0
    resolved_anchor_count = 0
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
            if position is not None:
                resolved_anchor_count += 1
            anchors.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
                    "appearance_order": appearance_order,
                    "status": "resolved" if position is not None else "unresolved",
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
        "unresolved_anchor_count": anchor_count - resolved_anchor_count,
        "slides": slides,
    }


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_file", type=Path)
    parser.add_argument("timing_report", type=Path)
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("--subtitles", type=Path, help="Optional matching SRT or VTT")
    parser.add_argument("--output", type=Path, help="Final MP4 path")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Per-slide clips, audit report, and animation cues",
    )
    parser.add_argument(
        "--animation-cues-output",
        type=Path,
        help="Normalized anchor positions for slide animation tooling",
    )
    parser.add_argument("--limit", type=int, help="Process only the first N generated slides")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--ocr-confidence", type=float, default=0.55)
    parser.add_argument("--ocr-match-threshold", type=float, default=0.64)
    parser.add_argument("--subtitle-match-threshold", type=float, default=0.62)
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


def validate_args(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise RuntimeError("--limit must be at least 1")
    if not 1 <= args.fps <= 60:
        raise RuntimeError("--fps must be between 1 and 60")
    for name in ("ocr_confidence", "ocr_match_threshold", "subtitle_match_threshold"):
        if not 0 <= getattr(args, name) <= 1:
            raise RuntimeError(f"--{name.replace('_', '-')} must be between 0 and 1")
    if not 1 <= args.underline_thickness <= 30:
        raise RuntimeError("--underline-thickness must be between 1 and 30")
    if not 0.1 <= args.min_underline_seconds <= 10:
        raise RuntimeError("--min-underline-seconds must be between 0.1 and 10")
    ffmpeg_color(args.underline_color)


def main() -> int:
    from rapidocr import RapidOCR

    args = parse_args()
    validate_args(args)
    repo_root = Path(__file__).resolve().parents[1]
    chunks_path = args.chunks_file.resolve()
    timing_path = args.timing_report.resolve()
    images_dir = args.images_dir.resolve()
    _, chunks_by_id = load_chunks(chunks_path)
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
    all_output_paths = [output_path, report_path, animation_cues_path]
    if len(set(all_output_paths)) != len(all_output_paths):
        raise RuntimeError(
            "Output video, audit report, and animation-cue paths must be distinct"
        )
    output_paths = [report_path, animation_cues_path]
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
    subtitle_word_timing = (
        timed_tokens(parse_subtitles(subtitle_path))
        if subtitle_path
        else []
    )
    ocr_engine = RapidOCR()
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
        ocr_lines = run_ocr(ocr_engine, image_path, args.ocr_confidence)
        duration = timing_item["actual_seconds"]
        anchor_plans = []
        for anchor in chunk["anchors"]:
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

            ocr_match = match_ocr_anchor(
                anchor["text"],
                ocr_lines,
                args.ocr_match_threshold,
            )
            if ocr_match:
                resolved_anchors += 1
                text_boxes = anchor_text_boxes(
                    anchor["text"],
                    ocr_match["lines"],
                    image_width,
                    image_height,
                )
                boxes = underline_boxes(
                    text_boxes,
                    image_width,
                    image_height,
                    args.underline_thickness,
                )
                ocr_score = ocr_match["score"]
                ocr_text = " ".join(line.text for line in ocr_match["lines"])
            else:
                text_boxes = []
                boxes = []
                ocr_score = None
                ocr_text = None
            anchor_plans.append(
                {
                    "id": anchor["id"],
                    "text": anchor["text"],
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
                    "ocr_text": ocr_text,
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

    audit_report = {
        "format": REPORT_FORMAT,
        "status": "planned" if args.dry_run else "rendering",
        "chunks_file": str(chunks_path),
        "chunks_sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
        "timing_report": str(timing_path),
        "images_dir": str(images_dir),
        "subtitles": str(subtitle_path) if subtitle_path else None,
        "subtitle_timing_available": bool(subtitle_word_timing),
        "output_video": str(output_path),
        "anchor_animation_cues": str(animation_cues_path),
        "fps": args.fps,
        "underline_color": args.underline_color,
        "underline_thickness": args.underline_thickness,
        "total_duration_seconds": round(global_start, 6),
        "slide_count": len(slide_plans),
        "anchor_count": total_anchors,
        "resolved_anchor_count": resolved_anchors,
        "unresolved_anchor_count": total_anchors - resolved_anchors,
        "subtitle_timed_anchor_count": subtitle_timed_anchors,
        "proportional_timed_anchor_count": total_anchors - subtitle_timed_anchors,
        "slides": slide_plans,
    }
    animation_cues = build_animation_cues(
        slide_plans,
        chunks_path,
        images_dir,
    )
    print(
        f"Plan: {len(slide_plans)} slides, OCR resolved "
        f"{resolved_anchors}/{total_anchors} anchors; subtitle timing "
        f"{subtitle_timed_anchors}/{total_anchors}.",
        flush=True,
    )
    work_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_path, audit_report)
    write_json(animation_cues_path, animation_cues)
    if args.dry_run:
        print(f"Audit report: {report_path}")
        print(f"Animation cues: {animation_cues_path}")
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
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
