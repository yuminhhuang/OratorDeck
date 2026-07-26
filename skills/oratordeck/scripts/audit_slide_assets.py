#!/usr/bin/env python3
"""Audit prompt-defined slide sources, generated images, and synchronized notes."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SLIDE_FILE_RE = re.compile(r"^slide-(?P<number>\d+)(?:[_-].*)?\.md$", re.IGNORECASE)
IMAGE_FILE_RE = re.compile(
    r"^slide-(?P<number>\d+)(?:[_-].*)?\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)
SLIDE_TITLE_RE = re.compile(r"(?m)^#\s+Slide\s+(?P<number>\d+)\s*[-:]\s*(?P<title>\S.*)$")
ROLE_RE = re.compile(r"(?mi)^\*\*(?:presentation|defense|deck)\s+role:\*\*\s*\S")
TAKEAWAY_RE = re.compile(r"(?mi)^\*\*Audience\s+takeaway:\*\*\s*\S")
PROMPT_HEADING_RE = re.compile(
    r"(?mi)^##[ \t]+"
    r"(?:(?:chatgpt|llm)[- ]*)?"
    r"image(?:[- ]generation)?[ \t]+prompt[ \t]*$"
)
NEXT_H2_RE = re.compile(r"(?m)^##[ \t]+\S")
FENCED_BLOCK_RE = re.compile(
    r"(?ms)^[ \t]*```(?:text|markdown|md)?[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^[ \t]*```[ \t]*$"
)
QUOTED_RE = re.compile(r'"(?P<label>[^"]+)"', re.DOTALL)
NOTE_SECTION_RE = re.compile(
    r"(?ms)^##\s+Slide\s+(?P<number>\d+)\b(?P<header>[^\r\n]*)"
    r"(?P<body>.*?)(?=^##\s+Slide\s+\d+\b|\Z)"
)
TIME_RE = re.compile(r"\*\*Target time:\*\*\s*(?P<minutes>\d+):(?P<seconds>\d{2})")
BOLD_RE = re.compile(r"\*\*(?P<anchor>.+?)\*\*", re.DOTALL)
WORD_RE = re.compile(r"\b[\w][\w'-]*\b", re.UNICODE)
STAGE_DIRECTION_PATTERNS = {
    "the slide shows": re.compile(r"\bthe slide shows\b", re.IGNORECASE),
    "the label is": re.compile(r"\bthe label is\b", re.IGNORECASE),
    "the exact question is": re.compile(r"\bthe exact question is\b", re.IGNORECASE),
    "as shown on the slide": re.compile(r"\bas shown on the slide\b", re.IGNORECASE),
    "look at the slide": re.compile(r"\blook at the slide\b", re.IGNORECASE),
}
JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


@dataclass
class SlideReport:
    number: int
    prompt: str
    title: str | None
    visible_labels: int
    image: str | None
    image_size: list[int] | None
    anchors: int | None
    anchor_mismatches: list[str]
    max_gap_words: int | None
    words: int | None
    target_seconds: int | None
    wpm: float | None
    warnings: list[str]
    errors: list[str]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def numbered_files(
    directory: Path,
    glob_pattern: str,
    pattern: re.Pattern[str],
    kind: str,
) -> tuple[dict[int, Path], list[str]]:
    files: dict[int, Path] = {}
    errors: list[str] = []
    for path in sorted(directory.glob(glob_pattern)):
        match = pattern.match(path.name)
        if not match:
            continue
        number = int(match.group("number"))
        if number in files:
            errors.append(f"duplicate {kind} number {number}: {files[number].name}, {path.name}")
        else:
            files[number] = path
    return files, errors


def contiguous_number_errors(numbers: set[int], kind: str) -> list[str]:
    if not numbers:
        return []
    expected = set(range(1, max(numbers) + 1))
    missing = sorted(expected - numbers)
    errors: list[str] = []
    if min(numbers) != 1:
        errors.append(f"{kind} numbering must start at 1")
    if missing:
        errors.append(f"{kind} numbering is not contiguous; missing {missing}")
    return errors


def extract_prompt_block(prompt_text: str) -> tuple[str | None, str | None]:
    heading = PROMPT_HEADING_RE.search(prompt_text)
    if heading is None:
        return None, None
    remainder = prompt_text[heading.end() :]
    next_heading = NEXT_H2_RE.search(remainder)
    section = remainder[: next_heading.start()] if next_heading else remainder
    fence = FENCED_BLOCK_RE.search(section)
    if fence is None:
        return heading.group(0).strip(), None
    return heading.group(0).strip(), fence.group("body").strip()


def visible_labels(prompt_block: str) -> list[str]:
    return [normalize(match.group("label")) for match in QUOTED_RE.finditer(prompt_block)]


def parse_notes(notes_text: str) -> tuple[dict[int, tuple[str, str]], list[str]]:
    sections: dict[int, tuple[str, str]] = {}
    errors: list[str] = []
    for match in NOTE_SECTION_RE.finditer(notes_text):
        number = int(match.group("number"))
        if number in sections:
            errors.append(f"duplicate speaker-note section for slide {number}")
        else:
            sections[number] = (match.group("header").strip(), match.group("body"))
    return sections, errors


def anchor_matches(
    anchor: str,
    labels: Iterable[str],
    full_prompt: str,
    allow_full_prompt_fallback: bool,
) -> tuple[bool, bool]:
    normalized = normalize(anchor)
    if any(normalized in label for label in labels):
        return True, False
    if allow_full_prompt_fallback and normalized in normalize(full_prompt):
        return True, True
    return False, False


def compute_gaps(body: str, anchors: list[re.Match[str]]) -> list[int]:
    gaps: list[int] = []
    cursor = 0
    for match in anchors:
        gaps.append(count_words(body[cursor : match.start()].replace("**", "")))
        cursor = match.end()
    gaps.append(count_words(body[cursor:].replace("**", "")))
    return gaps


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG signature")
    cursor = 2
    while cursor < len(data):
        while cursor < len(data) and data[cursor] != 0xFF:
            cursor += 1
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(data):
            break
        segment_length = int.from_bytes(data[cursor : cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > len(data):
            raise ValueError("invalid JPEG segment")
        if marker in JPEG_SOF_MARKERS:
            if segment_length < 7:
                raise ValueError("invalid JPEG frame header")
            height = int.from_bytes(data[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(data[cursor + 5 : cursor + 7], "big")
            return width, height
        if marker == 0xDA:
            break
        cursor += segment_length
    raise ValueError("JPEG dimensions not found")


def webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("invalid WebP signature")
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_type = data[cursor : cursor + 4]
        chunk_size = int.from_bytes(data[cursor + 4 : cursor + 8], "little")
        payload_start = cursor + 8
        payload_end = payload_start + chunk_size
        if payload_end > len(data):
            raise ValueError("truncated WebP chunk")
        payload = data[payload_start:payload_end]
        if chunk_type == b"VP8X" and len(payload) >= 10:
            width = int.from_bytes(payload[4:7], "little") + 1
            height = int.from_bytes(payload[7:10], "little") + 1
            return width, height
        if chunk_type == b"VP8 " and len(payload) >= 10:
            if payload[3:6] != b"\x9d\x01\x2a":
                raise ValueError("invalid VP8 frame header")
            width = int.from_bytes(payload[6:8], "little") & 0x3FFF
            height = int.from_bytes(payload[8:10], "little") & 0x3FFF
            return width, height
        if chunk_type == b"VP8L" and len(payload) >= 5:
            if payload[0] != 0x2F:
                raise ValueError("invalid VP8L frame header")
            dimensions = int.from_bytes(payload[1:5], "little")
            width = (dimensions & 0x3FFF) + 1
            height = ((dimensions >> 14) & 0x3FFF) + 1
            return width, height
        cursor = payload_end + (chunk_size % 2)
    raise ValueError("WebP dimensions not found")


def image_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ValueError("invalid PNG header")
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        return jpeg_dimensions(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return webp_dimensions(data)
    raise ValueError("unsupported or invalid image header")


def inspect_image(
    path: Path,
    expected_ratio: float,
    ratio_tolerance: float,
) -> tuple[list[int] | None, list[str]]:
    errors: list[str] = []
    try:
        width, height = image_dimensions(path)
    except (OSError, ValueError) as exc:
        return None, [f"image metadata cannot be read: {exc}"]

    if width <= 0 or height <= 0:
        errors.append("image has invalid dimensions")
    elif abs((width / height) - expected_ratio) > ratio_tolerance:
        errors.append(
            f"image aspect ratio {width / height:.4f} is not approximately {expected_ratio:.4f}"
        )
    return [width, height], errors


def audit(args: argparse.Namespace) -> dict:
    prompt_dir = args.prompts_dir.resolve()
    global_errors: list[str] = []
    global_warnings: list[str] = []

    if not prompt_dir.is_dir():
        global_errors.append(f"prompts directory not found: {prompt_dir}")
        prompt_map: dict[int, Path] = {}
    else:
        prompt_map, errors = numbered_files(
            prompt_dir,
            args.slide_glob,
            SLIDE_FILE_RE,
            "prompt",
        )
        global_errors.extend(errors)
    if not prompt_map:
        global_errors.append(f"no prompt files found in {prompt_dir}")
    global_errors.extend(contiguous_number_errors(set(prompt_map), "prompt"))

    if args.expected_slides is not None and len(prompt_map) != args.expected_slides:
        global_errors.append(f"expected {args.expected_slides} prompts, found {len(prompt_map)}")

    notes_path = args.notes.resolve() if args.notes is not None else None
    note_sections: dict[int, tuple[str, str]] = {}
    if notes_path is not None:
        if not notes_path.is_file():
            global_errors.append(f"speaker notes not found: {notes_path}")
            notes_text = ""
        else:
            notes_text = notes_path.read_text(encoding="utf-8")
        if notes_text.count("**") % 2:
            global_errors.append("speaker notes contain unbalanced ** markers")
        note_sections, errors = parse_notes(notes_text)
        global_errors.extend(errors)
        prompt_numbers = set(prompt_map)
        note_numbers = set(note_sections)
        for number in sorted(prompt_numbers - note_numbers):
            global_errors.append(f"missing speaker-note section for slide {number}")
        for number in sorted(note_numbers - prompt_numbers):
            global_errors.append(f"missing prompt source for speaker-note slide {number}")

    images_dir = args.images_dir.resolve() if args.images_dir is not None else None
    image_map: dict[int, Path] = {}
    if images_dir is not None:
        if not images_dir.is_dir():
            global_errors.append(f"images directory not found: {images_dir}")
        else:
            image_map, errors = numbered_files(
                images_dir,
                "slide-*",
                IMAGE_FILE_RE,
                "image",
            )
            global_errors.extend(errors)
            prompt_numbers = set(prompt_map)
            image_numbers = set(image_map)
            for number in sorted(prompt_numbers - image_numbers):
                global_errors.append(f"missing image for prompt slide {number}")
            for number in sorted(image_numbers - prompt_numbers):
                global_errors.append(f"missing prompt source for image slide {number}")

    reports: list[SlideReport] = []
    fallback_matches = 0
    total_seconds = 0
    total_words = 0
    total_anchors = 0
    image_sizes: list[tuple[int, int]] = []

    for number, prompt_path in sorted(prompt_map.items()):
        prompt_text = prompt_path.read_text(encoding="utf-8")
        warnings: list[str] = []
        errors: list[str] = []

        title_match = SLIDE_TITLE_RE.search(prompt_text)
        title: str | None = None
        if title_match is None:
            errors.append("missing '# Slide NN - Title' heading")
        else:
            heading_number = int(title_match.group("number"))
            title = title_match.group("title").strip()
            if heading_number != number:
                errors.append(
                    f"heading slide number {heading_number} does not match filename {number}"
                )

        if ROLE_RE.search(prompt_text) is None:
            errors.append("missing presentation/defense role")
        if TAKEAWAY_RE.search(prompt_text) is None:
            errors.append("missing audience takeaway")

        prompt_heading, prompt_block = extract_prompt_block(prompt_text)
        labels: list[str] = []
        if prompt_heading is None:
            errors.append("missing image-generation prompt heading")
        elif prompt_block is None:
            errors.append("image-generation prompt has no fenced body")
        else:
            labels = visible_labels(prompt_block)
            if prompt_block.count('"') % 2:
                errors.append("image-generation prompt has unbalanced double quotes")
            if len(labels) < args.min_visible_labels:
                warnings.append(
                    f"{len(labels)} quoted visible labels is below {args.min_visible_labels}"
                )
            if "16:9" not in prompt_block and "16 / 9" not in prompt_block:
                warnings.append("image-generation prompt does not explicitly request 16:9")
            if (
                re.search(
                    r"(?i)\b(?:accuracy|claim[- ]discipline) rules?\b",
                    prompt_block,
                )
                is None
            ):
                warnings.append(
                    "image-generation prompt has no accuracy or claim-discipline rules section"
                )

        image_path = image_map.get(number)
        image_size: list[int] | None = None
        if image_path is not None:
            if image_path.stem != prompt_path.stem:
                warnings.append(
                    f"image stem {image_path.stem!r} differs from prompt stem {prompt_path.stem!r}"
                )
            image_size, image_errors = inspect_image(
                image_path,
                args.aspect_ratio,
                args.aspect_tolerance,
            )
            errors.extend(image_errors)
            if image_size is not None:
                image_sizes.append((image_size[0], image_size[1]))

        anchors: int | None = None
        mismatches: list[str] = []
        max_gap_words: int | None = None
        words: int | None = None
        target_seconds: int | None = None
        wpm: float | None = None

        if notes_path is not None and number in note_sections:
            _, body = note_sections[number]
            time_matches = list(TIME_RE.finditer(body))
            if len(time_matches) != 1:
                errors.append(
                    f"expected exactly one **Target time:** M:SS field, found {len(time_matches)}"
                )
            else:
                time_match = time_matches[0]
                seconds_field = int(time_match.group("seconds"))
                if seconds_field > 59:
                    errors.append("target time seconds must be between 00 and 59")
                else:
                    target_seconds = int(time_match.group("minutes")) * 60 + seconds_field

            body_without_time = TIME_RE.sub("", body)
            anchor_spans = list(BOLD_RE.finditer(body_without_time))
            anchors = len(anchor_spans)
            for match in anchor_spans:
                anchor = match.group("anchor").strip()
                matched, used_fallback = anchor_matches(
                    anchor,
                    labels,
                    prompt_text,
                    args.allow_full_prompt_fallback,
                )
                if not matched:
                    mismatches.append(normalize(anchor))
                elif used_fallback:
                    fallback_matches += 1

            gaps = compute_gaps(body_without_time, anchor_spans)
            max_gap_words = max(gaps, default=count_words(body_without_time))
            plain_body = body_without_time.replace("**", "")
            words = count_words(plain_body)
            wpm = (
                round(words / (target_seconds / 60.0), 1)
                if target_seconds and target_seconds > 0
                else None
            )

            if anchors < args.min_anchors:
                warnings.append(f"{anchors} anchors is below minimum {args.min_anchors}")
            if max_gap_words > args.max_gap_words:
                warnings.append(
                    f"maximum unanchored gap {max_gap_words} exceeds {args.max_gap_words} words"
                )
            if mismatches:
                errors.append(f"{len(mismatches)} anchors do not match quoted visible text")
            if wpm is not None and wpm < args.wpm_min:
                warnings.append(f"{wpm:.1f} WPM is below {args.wpm_min:.1f}")
            if wpm is not None and wpm > args.wpm_max:
                warnings.append(f"{wpm:.1f} WPM exceeds {args.wpm_max:.1f}")

            plain_normalized = normalize(plain_body)
            for label, pattern in STAGE_DIRECTION_PATTERNS.items():
                if pattern.search(plain_normalized):
                    warnings.append(f"mechanical stage direction detected: {label!r}")

        reports.append(
            SlideReport(
                number=number,
                prompt=prompt_path.name,
                title=title,
                visible_labels=len(labels),
                image=image_path.name if image_path else None,
                image_size=image_size,
                anchors=anchors,
                anchor_mismatches=mismatches,
                max_gap_words=max_gap_words,
                words=words,
                target_seconds=target_seconds,
                wpm=wpm,
                warnings=warnings,
                errors=errors,
            )
        )
        total_anchors += anchors or 0
        total_words += words or 0
        total_seconds += target_seconds or 0

    if image_sizes:
        size_counts = Counter(image_sizes)
        if len(size_counts) > 1:
            detail = ", ".join(
                f"{width}x{height} ({count})"
                for (width, height), count in size_counts.most_common()
            )
            global_warnings.append(f"slide image dimensions are inconsistent: {detail}")

    warning_count = len(global_warnings) + sum(len(report.warnings) for report in reports)
    error_count = len(global_errors) + sum(len(report.errors) for report in reports)
    average_wpm = round(total_words / (total_seconds / 60.0), 1) if total_seconds else None

    return {
        "format": "oratordeck-slide-assets-audit-v1",
        "prompts_dir": str(prompt_dir),
        "notes": str(notes_path) if notes_path else None,
        "images_dir": str(images_dir) if images_dir else None,
        "global_errors": global_errors,
        "global_warnings": global_warnings,
        "slides": [asdict(report) for report in reports],
        "summary": {
            "prompt_count": len(prompt_map),
            "note_section_count": len(note_sections) if notes_path else None,
            "image_count": len(image_map) if images_dir else None,
            "anchors": total_anchors if notes_path else None,
            "fallback_anchor_matches": fallback_matches if notes_path else None,
            "words": total_words if notes_path else None,
            "target_seconds": total_seconds if notes_path else None,
            "target_duration": (
                f"{total_seconds // 60}:{total_seconds % 60:02d}" if notes_path else None
            ),
            "average_wpm": average_wpm,
            "warnings": warning_count,
            "errors": error_count,
        },
    }


def print_human(report: dict) -> None:
    notes_enabled = report["notes"] is not None
    images_enabled = report["images_dir"] is not None

    columns = ["Slide", "Labels"]
    if images_enabled:
        columns.append("Image")
    if notes_enabled:
        columns.extend(["Anchors", "MaxGap", "Words", "Time", "WPM"])
    columns.append("Status")
    print("  ".join(columns))
    print("  ".join("-" * len(column) for column in columns))

    for slide in report["slides"]:
        row = [f"{slide['number']:>5}", f"{slide['visible_labels']:>6}"]
        if images_enabled:
            row.append("yes" if slide["image"] else "no")
        if notes_enabled:
            seconds = slide["target_seconds"]
            time_text = f"{seconds // 60}:{seconds % 60:02d}" if seconds is not None else "-"
            wpm = slide["wpm"]
            row.extend(
                [
                    str(slide["anchors"] if slide["anchors"] is not None else "-"),
                    str(slide["max_gap_words"] if slide["max_gap_words"] is not None else "-"),
                    str(slide["words"] if slide["words"] is not None else "-"),
                    time_text,
                    f"{wpm:.1f}" if wpm is not None else "-",
                ]
            )
        status = "ERROR" if slide["errors"] else ("WARN" if slide["warnings"] else "OK")
        row.append(status)
        print("  ".join(row))
        for error in slide["errors"]:
            print(f"       ERROR: {error}")
        for mismatch in slide["anchor_mismatches"]:
            print(f"       MISMATCH: {mismatch}")
        for warning in slide["warnings"]:
            print(f"       WARN: {warning}")

    for error in report["global_errors"]:
        print(f"GLOBAL ERROR: {error}")
    for warning in report["global_warnings"]:
        print(f"GLOBAL WARN: {warning}")

    summary = report["summary"]
    fields = [f"prompts={summary['prompt_count']}"]
    if summary["note_section_count"] is not None:
        fields.extend(
            [
                f"note_sections={summary['note_section_count']}",
                f"anchors={summary['anchors']}",
                f"duration={summary['target_duration']}",
                f"words={summary['words']}",
                f"average_wpm={summary['average_wpm']}",
            ]
        )
    if summary["image_count"] is not None:
        fields.append(f"images={summary['image_count']}")
    fields.extend(
        [
            f"warnings={summary['warnings']}",
            f"errors={summary['errors']}",
        ]
    )
    print("\nSummary: " + " ".join(fields))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit prompt-defined Markdown sources and optional speaker notes/images."
        )
    )
    parser.add_argument("--prompts-dir", type=Path, required=True)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--images-dir", type=Path)
    parser.add_argument("--slide-glob", default="slide-*.md")
    parser.add_argument("--expected-slides", type=int)
    parser.add_argument("--min-visible-labels", type=int, default=3)
    parser.add_argument("--min-anchors", type=int, default=4)
    parser.add_argument("--max-gap-words", type=int, default=40)
    parser.add_argument("--wpm-min", type=float, default=110.0)
    parser.add_argument("--wpm-max", type=float, default=150.0)
    parser.add_argument("--aspect-ratio", type=float, default=16 / 9)
    parser.add_argument("--aspect-tolerance", type=float, default=0.03)
    parser.add_argument(
        "--allow-full-prompt-fallback",
        action="store_true",
        help="Allow anchors to match unquoted prompt text for legacy sources.",
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = audit(args)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human(report)

    errors = report["summary"]["errors"]
    warnings = report["summary"]["warnings"]
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
