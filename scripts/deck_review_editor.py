#!/usr/bin/env python3
"""Compatibility imports for the installable OratorDeck Verdict editor."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from oratordeck_verdict.editor import (  # noqa: E402,F401
    DECK_REVIEW_FORMAT,
    build_deck_review_html,
    safe_json,
    script_with_bold_anchors,
    slide_data_uri,
)

__all__ = [
    "DECK_REVIEW_FORMAT",
    "build_deck_review_html",
    "safe_json",
    "script_with_bold_anchors",
    "slide_data_uri",
]
