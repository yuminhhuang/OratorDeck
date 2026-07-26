#!/usr/bin/env python3
# ruff: noqa: E402,F403,I001
"""Compatibility entry point for preparing an OratorDeck Deck Verdict."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from oratordeck_verdict.prepare import *


if __name__ == "__main__":
    try:
        raise SystemExit(main())  # noqa: F405
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
