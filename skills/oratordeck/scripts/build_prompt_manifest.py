#!/usr/bin/env python3
"""Build an ordered image-generation manifest from Prompt-as-Slide sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from audit_slide_assets import (
    QUOTED_RE,
    SLIDE_FILE_RE,
    SLIDE_TITLE_RE,
    contiguous_number_errors,
    extract_prompt_block,
    numbered_files,
)

ROLE_FIELD_RE = re.compile(
    r"(?ims)^\*\*(?:presentation|defense|deck)\s+role:\*\*\s*"
    r"(?P<value>.*?)(?=^\s*$)"
)
TAKEAWAY_FIELD_RE = re.compile(
    r"(?ims)^\*\*Audience\s+takeaway:\*\*\s*"
    r"(?P<value>.*?)(?=^\s*$)"
)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    prompts_dir: Path,
    images_dir: Path,
    slide_glob: str,
) -> dict:
    prompt_map, errors = numbered_files(
        prompts_dir,
        slide_glob,
        SLIDE_FILE_RE,
        "prompt",
    )
    errors.extend(contiguous_number_errors(set(prompt_map), "prompt"))
    if not prompt_map:
        errors.append(f"no prompt files found in {prompts_dir}")
    if errors:
        raise RuntimeError("; ".join(errors))

    slides: list[dict] = []
    for number, path in sorted(prompt_map.items()):
        text = path.read_text(encoding="utf-8")
        title_match = SLIDE_TITLE_RE.search(text)
        role_match = ROLE_FIELD_RE.search(text)
        takeaway_match = TAKEAWAY_FIELD_RE.search(text)
        _, prompt_block = extract_prompt_block(text)

        missing: list[str] = []
        if title_match is None:
            missing.append("slide title")
        elif int(title_match.group("number")) != number:
            missing.append("matching slide number in title")
        if role_match is None:
            missing.append("presentation/defense role")
        if takeaway_match is None:
            missing.append("audience takeaway")
        if prompt_block is None:
            missing.append("fenced image-generation prompt")
        if missing:
            raise RuntimeError(f"{path.name}: missing {', '.join(missing)}")

        assert title_match is not None
        assert role_match is not None
        assert takeaway_match is not None
        assert prompt_block is not None

        visible_strings = [
            collapse(match.group("label")) for match in QUOTED_RE.finditer(prompt_block)
        ]
        slides.append(
            {
                "id": f"slide-{number:02d}",
                "number": number,
                "slug": path.stem.removeprefix(f"slide-{number:02d}").lstrip("_-"),
                "title": title_match.group("title").strip(),
                "role": collapse(role_match.group("value")),
                "audience_takeaway": collapse(takeaway_match.group("value")),
                "source": str(path),
                "source_sha256": source_hash(path),
                "image_output": str(images_dir / f"{path.stem}.png"),
                "image_prompt": prompt_block,
                "visible_strings": visible_strings,
            }
        )

    return {
        "format": "oratordeck.prompt-manifest.v1",
        "prompts_dir": str(prompts_dir),
        "images_dir": str(images_dir),
        "slide_count": len(slides),
        "slides": slides,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract ordered, self-contained image prompts from Prompt-as-Slide Markdown."
        )
    )
    parser.add_argument("prompts_dir", type=Path)
    parser.add_argument("--images-dir", type=Path)
    parser.add_argument("--slide-glob", default="slide-*.md")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    prompts_dir = args.prompts_dir.resolve()
    if not prompts_dir.is_dir():
        raise RuntimeError(f"prompts directory not found: {prompts_dir}")
    images_dir = (
        args.images_dir.resolve()
        if args.images_dir is not None
        else (prompts_dir / "generated-images").resolve()
    )

    manifest = build_manifest(prompts_dir, images_dir, args.slide_glob)
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    if args.output is None:
        print(payload, end="")
    else:
        output = args.output.resolve()
        if output.exists() and not args.overwrite:
            raise RuntimeError(f"output already exists: {output}; pass --overwrite")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"Manifest: {output}")
        print(f"Slides: {manifest['slide_count']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
