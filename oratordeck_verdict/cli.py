"""Command-line interface for the standalone OratorDeck Verdict module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .apply import apply_review
from .prepare import prepare_deck
from .state_server import serve_editor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oratordeck-verdict",
        description=(
            "Prepare, edit, and apply OratorDeck's browser-based review "
            "workbench without an Agent or GPU."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Build a self-contained Deck Verdict HTML file.",
    )
    prepare_parser.add_argument("speaker_notes", type=Path)
    prepare_parser.add_argument("images_dir", type=Path)
    prepare_parser.add_argument(
        "--output",
        type=Path,
        default=Path("deck-verdict.html"),
    )
    prepare_parser.add_argument(
        "--review-json",
        type=Path,
        default=Path("deck-review.json"),
        help="Suggested path and filename for Save deck review",
    )
    prepare_parser.add_argument(
        "--ocr-output",
        type=Path,
        default=Path("deck-ocr.json"),
        help="Reusable image-bound OCR results for the video stage",
    )
    prepare_parser.add_argument(
        "--ocr-confidence",
        type=float,
        default=0.55,
    )
    prepare_parser.add_argument(
        "--ocr-match-threshold",
        type=float,
        default=0.64,
    )
    prepare_parser.add_argument("--overwrite", action="store_true")

    apply_parser = subparsers.add_parser(
        "apply",
        help="Validate and apply a saved deck review.",
    )
    apply_parser.add_argument("review_json", type=Path)
    apply_parser.add_argument("speaker_notes", type=Path)
    apply_parser.add_argument("images_dir", type=Path)
    apply_parser.add_argument(
        "--ocr-results",
        type=Path,
        help="Image-bound OCR results emitted by the prepare command",
    )
    apply_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reviewed"),
    )
    apply_parser.add_argument("--overwrite", action="store_true")

    edit_parser = subparsers.add_parser(
        "edit",
        help="Open a Verdict panel or unified pre/post-TTS workbench.",
    )
    edit_parser.add_argument("html", type=Path)
    edit_parser.add_argument("state_json", type=Path)
    edit_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Loopback TCP port; zero selects an available port",
    )
    edit_parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the editor URL without opening a browser",
    )
    edit_parser.add_argument(
        "--post-html",
        type=Path,
        help=(
            "Future or existing post-TTS Verdict HTML; when it becomes valid, "
            "the same workbench reveals phase switching and opens it"
        ),
    )
    edit_parser.add_argument(
        "--post-state",
        type=Path,
        help="Persistent box-override JSON paired with --post-html",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    if args.command == "prepare":
        prepare_deck(
            args.speaker_notes,
            args.images_dir,
            args.output,
            args.review_json,
            args.ocr_output,
            ocr_confidence=args.ocr_confidence,
            ocr_match_threshold=args.ocr_match_threshold,
            overwrite=args.overwrite,
        )
        return
    if args.command == "apply":
        output_dir = args.output_dir
        apply_review(
            args.review_json,
            args.speaker_notes,
            args.images_dir,
            [
                output_dir / "SPEAKER_NOTES.md",
                output_dir / "SPEAKER_NOTES_CHUNKS.json",
                output_dir / "SPEAKER_NOTES_TTS.txt",
                output_dir / "anchor-overrides.json",
            ],
            ocr_results_path=args.ocr_results,
            ocr_output=(
                output_dir / "deck-ocr.json"
                if args.ocr_results
                else None
            ),
            overwrite=args.overwrite,
        )
        return
    if args.command == "edit":
        serve_editor(
            args.html,
            args.state_json,
            port=args.port,
            open_browser=not args.no_open,
            post_html_path=args.post_html,
            post_state_path=args.post_state,
        )
        return
    raise RuntimeError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        run(build_parser().parse_args(argv))
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0
