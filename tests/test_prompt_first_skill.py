from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from tests.helpers import PROJECT_DIR

AUDITOR = (
    PROJECT_DIR / "skills" / "oratordeck-prompt-first" / "scripts" / "audit_prompt_first_deck.py"
)
MANIFEST_BUILDER = (
    PROJECT_DIR / "skills" / "oratordeck-prompt-first" / "scripts" / "build_prompt_manifest.py"
)


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
    Image.new("RGB", (1600, 900), "white").save(images / "slide-01_opening.png")

    result = run_audit(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
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
    Image.new("RGB", (1600, 900), "white").save(images / "slide-01_opening.png")

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
