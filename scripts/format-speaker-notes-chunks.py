#!/usr/bin/env python3
"""Convert Markdown speaker notes into one indivisible TTS chunk per slide."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

FORMAT_VERSION = "oratordeck.speaker-notes-chunks.v1"
VOICEBOX_MAX_TEXT_CHARS = 5_000
SLIDE_HEADING_RE = re.compile(
    r"^##\s+Slide\s+(\d+)\s*-\s*(.+?)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
TARGET_TIME_RE = re.compile(
    r"^\s*\*\*Target time:\*\*\s*(\d+):(\d{2})\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
WORD_RE = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b", flags=re.UNICODE)
ANCHOR_RE = re.compile(r"\*\*(.+?)\*\*", flags=re.DOTALL)
ANCHOR_MARKER_RE = re.compile("\ue000A(\\d+)([SE])\ue001")


def clean_inline_markdown(text: str) -> str:
    """Remove visual Markdown syntax while retaining its spoken content."""
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<https?://[^>]+>", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<=\w)\*(?=[\s,.;:)])", " star", text)
    text = text.replace(" -> ", " to ")
    return re.sub(r"\s+", " ", text).strip()


def extract_marked_anchors(text: str) -> tuple[str, int]:
    """Replace bold spans with private markers while preserving their content."""
    anchor_count = 0

    def replace(match: re.Match) -> str:
        nonlocal anchor_count
        index = anchor_count
        anchor_count += 1
        return (
            f"\ue000A{index}S\ue001"
            f"{match.group(1)}"
            f"\ue000A{index}E\ue001"
        )

    return ANCHOR_RE.sub(replace, text), anchor_count


def resolve_anchor_markers(marked_text: str, anchor_count: int) -> tuple[str, list[dict]]:
    """Remove private markers and return final text offsets for every anchor."""
    output_parts: list[str] = []
    output_length = 0
    cursor = 0
    spans: dict[int, dict[str, int]] = {}
    for marker in ANCHOR_MARKER_RE.finditer(marked_text):
        segment = marked_text[cursor : marker.start()]
        output_parts.append(segment)
        output_length += len(segment)
        anchor_index = int(marker.group(1))
        boundary = marker.group(2)
        spans.setdefault(anchor_index, {})["start" if boundary == "S" else "end"] = output_length
        cursor = marker.end()
    output_parts.append(marked_text[cursor:])
    text = "".join(output_parts)

    anchors: list[dict] = []
    for anchor_index in range(anchor_count):
        span = spans.get(anchor_index, {})
        start = span.get("start")
        end = span.get("end")
        if start is None or end is None or end <= start:
            raise RuntimeError(f"Could not resolve bold anchor {anchor_index + 1}")
        anchor_text = text[start:end].strip()
        leading_space = len(text[start:end]) - len(text[start:end].lstrip())
        trailing_space = len(text[start:end]) - len(text[start:end].rstrip())
        start += leading_space
        end -= trailing_space
        anchors.append(
            {
                "id": f"anchor-{anchor_index + 1:02d}",
                "text": anchor_text,
                "start_char": start,
                "end_char": end,
            }
        )
    return text, anchors


def clean_slide_body(block: str) -> tuple[str, list[dict]]:
    """Turn one slide's Markdown body into spoken text and bold-anchor offsets."""
    block = TARGET_TIME_RE.sub("", block, count=1)
    block, anchor_count = extract_marked_anchors(block)
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        paragraph = clean_inline_markdown(" ".join(current))
        if paragraph:
            paragraphs.append(paragraph)
        current.clear()

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("<!--"):
            flush()
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", line)
        current.append(line)
    flush()
    return resolve_anchor_markers("\n\n".join(paragraphs), anchor_count)


def format_speaker_notes(source_path: Path) -> dict:
    source = source_path.read_text(encoding="utf-8")
    headings = list(SLIDE_HEADING_RE.finditer(source))
    if not headings:
        raise RuntimeError(f"No '## Slide NN - Title' headings found in {source_path}")

    chunks: list[dict] = []
    for index, heading in enumerate(headings):
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        block = source[heading.end() : block_end]
        time_matches = list(TARGET_TIME_RE.finditer(block))
        if len(time_matches) != 1:
            raise RuntimeError(
                f"Slide {heading.group(1)} must contain exactly one "
                f"'**Target time:** M:SS' line; found {len(time_matches)}"
            )

        minutes = int(time_matches[0].group(1))
        seconds_component = int(time_matches[0].group(2))
        if seconds_component >= 60:
            raise RuntimeError(
                f"Slide {heading.group(1)} has invalid target seconds: {seconds_component}"
            )
        target_seconds = minutes * 60 + seconds_component
        if target_seconds <= 0:
            raise RuntimeError(f"Slide {heading.group(1)} has a non-positive target time")

        text, anchors = clean_slide_body(block)
        if not text:
            raise RuntimeError(f"Slide {heading.group(1)} has no read-aloud content")
        if len(text) > VOICEBOX_MAX_TEXT_CHARS:
            raise RuntimeError(
                f"Slide {heading.group(1)} has {len(text):,} characters, exceeding "
                f"Voicebox's {VOICEBOX_MAX_TEXT_CHARS:,}-character indivisible limit"
            )

        slide_number = int(heading.group(1))
        word_count = len(WORD_RE.findall(text))
        chunks.append(
            {
                "id": f"slide-{slide_number:02d}",
                "slide": slide_number,
                "title": clean_inline_markdown(heading.group(2)),
                "target_time": f"{minutes}:{seconds_component:02d}",
                "target_seconds": target_seconds,
                "characters": len(text),
                "words": word_count,
                "target_wpm": round(word_count * 60 / target_seconds, 2),
                "text": text,
                "anchors": anchors,
            }
        )

    slide_numbers = [chunk["slide"] for chunk in chunks]
    expected_numbers = list(range(slide_numbers[0], slide_numbers[0] + len(chunks)))
    if slide_numbers != expected_numbers:
        raise RuntimeError(
            f"Slide numbers must be contiguous and ordered; found {slide_numbers}"
        )

    return {
        "format": FORMAT_VERSION,
        "source": source_path.name,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "chunk_count": len(chunks),
        "total_target_seconds": sum(chunk["target_seconds"] for chunk in chunks),
        "chunks": chunks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "speaker_notes",
        nargs="?",
        type=Path,
        default=Path("resources/SPEAKER_NOTES.md"),
        help="Markdown speaker notes (default: resources/SPEAKER_NOTES.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path (default: <speaker-notes-stem>_CHUNKS.json)",
    )
    parser.add_argument(
        "--tts-output",
        type=Path,
        help="Also write cleaned slides as a legacy plain-text subtitle reference",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = args.speaker_notes.resolve()
    output_path = (
        args.output.resolve()
        if args.output
        else source_path.with_name(f"{source_path.stem}_CHUNKS.json")
    )
    document = format_speaker_notes(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.tts_output:
        tts_output_path = args.tts_output.resolve()
        tts_output_path.parent.mkdir(parents=True, exist_ok=True)
        tts_output_path.write_text(
            "\n\n".join(chunk["text"] for chunk in document["chunks"]) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote subtitle reference: {tts_output_path}")

    total_seconds = document["total_target_seconds"]
    print(
        f"Wrote {document['chunk_count']} slide chunks to {output_path} "
        f"(target {total_seconds // 60}:{total_seconds % 60:02d})."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        raise SystemExit(1) from None
