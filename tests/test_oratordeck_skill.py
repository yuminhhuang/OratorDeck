from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from tests.helpers import PROJECT_DIR

AUDITOR = PROJECT_DIR / "skills" / "oratordeck" / "scripts" / "audit_slide_assets.py"
MANIFEST_BUILDER = (
    PROJECT_DIR / "skills" / "oratordeck" / "scripts" / "build_prompt_manifest.py"
)
SKILL_DIR = PROJECT_DIR / "skills" / "oratordeck"


def load_auditor_module():
    module_name = "oratordeck_test_slide_assets_auditor"
    spec = importlib.util.spec_from_file_location(module_name, AUDITOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {AUDITOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


auditor = load_auditor_module()


def write_prompt(path: Path) -> None:
    path.write_text(
        """# Slide 01 - A bounded answer

**Defense role:** Establish the deck's governing question.

**Audience takeaway:** Evidence leads to one bounded answer.

## ChatGPT-Image Prompt

```text
Create a restrained 16:9 presentation slide.

TITLE - USE EXACTLY
"Central question"

MECHANISM - USE EXACTLY
"Evidence bridge"

TAKEAWAY - USE EXACTLY
"Bounded answer"

ACCURACY RULES
- Render every visible label exactly.
- Do not invent facts.
```
""",
        encoding="utf-8",
    )


def write_notes(path: Path, final_anchor: str = "Bounded answer") -> None:
    path.write_text(
        f"""# Speaker Notes

## Slide 01 - A bounded answer

**Target time:** 0:20

Begin with the **Central question**, cross the evidence bridge, and reach the
**{final_anchor}**.
""",
        encoding="utf-8",
    )


def write_png(path: Path, width: int, height: int) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    scanline = b"\x00" + b"\xff\xff\xff" * width
    payload = b"".join(scanline for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(payload))
        + chunk(b"IEND", b"")
    )


def write_jpeg_header(path: Path, width: int, height: int) -> None:
    frame = (
        b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x01"
        + b"\x01\x11\x00"
    )
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(frame) + 2)
        + frame
        + b"\xff\xd9"
    )


def write_webp_vp8x_header(path: Path, width: int, height: int) -> None:
    payload = (
        b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    webp = b"WEBP" + b"VP8X" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(webp)) + webp)


def run_audit(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "--prompts-dir",
            str(tmp_path),
            "--notes",
            str(tmp_path / "SPEAKER_NOTES.md"),
            "--images-dir",
            str(tmp_path / "generated-images"),
            "--min-anchors",
            "2",
            "--wpm-min",
            "1",
            "--wpm-max",
            "300",
            "--strict",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_audits_provider_specific_prompt_notes_and_image(tmp_path: Path) -> None:
    write_prompt(tmp_path / "slide-01_opening.md")
    write_notes(tmp_path / "SPEAKER_NOTES.md")
    images = tmp_path / "generated-images"
    images.mkdir()
    write_png(images / "slide-01_opening.png", 1600, 900)

    result = run_audit(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["format"] == "oratordeck-slide-assets-audit-v1"
    assert report["summary"] == {
        "prompt_count": 1,
        "note_section_count": 1,
        "image_count": 1,
        "anchors": 2,
        "fallback_anchor_matches": 0,
        "words": 14,
        "target_seconds": 20,
        "target_duration": "0:20",
        "average_wpm": 42.0,
        "warnings": 0,
        "errors": 0,
    }


def test_rejects_anchor_missing_from_visible_text_manifest(tmp_path: Path) -> None:
    write_prompt(tmp_path / "slide-01_opening.md")
    write_notes(tmp_path / "SPEAKER_NOTES.md", final_anchor="Invented claim")
    images = tmp_path / "generated-images"
    images.mkdir()
    write_png(images / "slide-01_opening.png", 1600, 900)

    result = run_audit(tmp_path)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["summary"]["errors"] == 1
    assert report["slides"][0]["anchor_mismatches"] == ["invented claim"]


def test_builds_ordered_generation_manifest(tmp_path: Path) -> None:
    source = tmp_path / "slide-01_opening.md"
    output = tmp_path / "PROMPT_MANIFEST.json"
    write_prompt(source)

    result = subprocess.run(
        [
            sys.executable,
            str(MANIFEST_BUILDER),
            str(tmp_path),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["format"] == "oratordeck.prompt-manifest.v1"
    assert manifest["slide_count"] == 1
    slide = manifest["slides"][0]
    assert slide["id"] == "slide-01"
    assert slide["slug"] == "opening"
    assert slide["source"] == str(source.resolve())
    assert slide["image_output"].endswith("generated-images/slide-01_opening.png")
    assert slide["visible_strings"] == [
        "Central question",
        "Evidence bridge",
        "Bounded answer",
    ]
    assert slide["image_prompt"].startswith("Create a restrained 16:9")


def test_skill_scope_stops_at_images_and_speaker_notes() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    handoff = (SKILL_DIR / "references" / "oratordeck-handoff.md").read_text(encoding="utf-8")
    interface = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    bundled_markdown = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SKILL_DIR.rglob("*.md"))
    )
    normalized_handoff = " ".join(handoff.split())

    assert "name: oratordeck" in skill
    assert "This skill ends after it has produced and audited" in skill
    assert "outside this skill" in skill
    assert "Do not produce" in skill
    assert "does not need the skill at runtime" in normalized_handoff
    assert "Create aligned slide images and speaker notes" in interface
    assert "Use $oratordeck " in interface
    assert "OratorDeck video" not in interface
    assert "./.venv/bin/python" not in bundled_markdown
    assert "--profile-name" not in bundled_markdown
    assert "CUDA_VISIBLE_DEVICES" not in bundled_markdown


def test_image_audit_has_no_pillow_dependency() -> None:
    auditor_source = AUDITOR.read_text(encoding="utf-8")

    assert "from PIL" not in auditor_source
    assert "import PIL" not in auditor_source


def test_reads_supported_image_dimensions_with_standard_library(tmp_path: Path) -> None:
    png = tmp_path / "slide.png"
    jpeg = tmp_path / "slide.jpg"
    webp = tmp_path / "slide.webp"
    write_png(png, 1600, 900)
    write_jpeg_header(jpeg, 1280, 720)
    write_webp_vp8x_header(webp, 1920, 1080)

    assert auditor.image_dimensions(png) == (1600, 900)
    assert auditor.image_dimensions(jpeg) == (1280, 720)
    assert auditor.image_dimensions(webp) == (1920, 1080)


def test_readmes_present_two_composable_halves_with_language_switching() -> None:
    readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_DIR / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "[English](README.md) · [简体中文](README.zh-CN.md)" in readme
    assert "[English](README.md) · [简体中文](README.zh-CN.md)" in readme_zh
    assert "docs/assets/oratordeck-final-effect.png" in readme
    assert "docs/assets/oratordeck-final-effect.png" in readme_zh
    assert "two independent, composable parts" in readme
    assert "[`oratordeck`](skills/oratordeck)" in readme
    assert "Use $oratordeck with my per-slide prompts" in readme
    assert "The skill stops after preparing and auditing" in readme
    assert "Neither the skill nor an Agent" in readme
    assert "## OratorDeck 能做什么？" not in readme
    assert "两个相互独立、又可组合使用的部分" in readme_zh
    assert "skill 会停在图片和讲稿" in readme_zh
    assert "## What does OratorDeck do?" not in readme_zh
    assert "oratordeck-prompt-first" not in readme
    assert "oratordeck-prompt-first" not in readme_zh
    assert "images, synchronized English speaker notes, and final annotated video" not in readme
