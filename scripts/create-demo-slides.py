#!/usr/bin/env python3
"""Render two synthetic slide images for the public OratorDeck demo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1600
HEIGHT = 900
BACKGROUND = "#F7F4EC"
INK = "#17212B"
ACCENT = "#E25A2C"
MUTED = "#66717E"


def font(size: int, *, bold: bool = False):
    names = (
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "DejaVuSans-Bold.ttf",
        )
        if bold
        else (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans.ttf",
        )
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE = font(76, bold=True)
HEADING = font(46, bold=True)
BODY = font(34)
LABEL = font(30, bold=True)
SMALL = font(24)


def canvas(number: int, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 26, HEIGHT), fill=ACCENT)
    draw.text((92, 76), title, fill=INK, font=TITLE)
    draw.text((92, 820), f"ORATORDECK DEMO  ·  {number:02d}", fill=MUTED, font=SMALL)
    return image, draw


def rounded_label(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
) -> None:
    draw.rounded_rectangle(box, radius=26, fill="#FFFFFF", outline="#D9D4C8", width=3)
    left, top, _, _ = box
    draw.text((left + 34, top + 32), text, fill=INK, font=LABEL)


def slide_one(path: Path) -> None:
    image, draw = canvas(1, "Aligned Inputs")
    draw.text((100, 235), "Speaker notes", fill=MUTED, font=HEADING)
    draw.text((1030, 235), "Slide image", fill=MUTED, font=HEADING)
    draw.line((380, 420, 1220, 420), fill=ACCENT, width=12)
    draw.polygon(((1190, 390), (1245, 420), (1190, 450)), fill=ACCENT)
    draw.rounded_rectangle((100, 330, 575, 600), radius=28, fill="#FFFFFF", outline="#D9D4C8", width=3)
    draw.rounded_rectangle((1025, 330, 1500, 600), radius=28, fill="#FFFFFF", outline="#D9D4C8", width=3)
    draw.text((150, 390), "Narration", fill=INK, font=HEADING)
    draw.text((150, 475), "Timing + anchors", fill=MUTED, font=BODY)
    draw.text((1075, 390), "Visual content", fill=INK, font=HEADING)
    draw.text((1075, 475), "Matching labels", fill=MUTED, font=BODY)
    draw.text((555, 690), "ALIGNED ASSETS", fill=ACCENT, font=TITLE)
    image.save(path)


def slide_two(path: Path) -> None:
    image, draw = canvas(2, "Four Stages")
    labels = ("CHUNK NOTES", "GENERATE SPEECH", "ALIGN THE ANCHORS", "RENDER VIDEO")
    for index, text in enumerate(labels):
        left = 95 + index * 375
        rounded_label(draw, (left, 335, left + 330, 475), text)
        if index < len(labels) - 1:
            draw.line((left + 332, 405, left + 368, 405), fill=ACCENT, width=8)
            draw.polygon(
                ((left + 355, 388), (left + 378, 405), (left + 355, 422)),
                fill=ACCENT,
            )
    draw.text(
        (390, 625),
        "ONE INDIVISIBLE UNIT PER SLIDE",
        fill=INK,
        font=HEADING,
    )
    image.save(path)


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    output_dir = project_dir / "examples" / "demo" / "generated-images"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = (
        output_dir / "slide-01-aligned-inputs.png",
        output_dir / "slide-02-four-stages.png",
    )
    slide_one(outputs[0])
    slide_two(outputs[1])
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
