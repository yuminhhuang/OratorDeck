from __future__ import annotations

from tests.helpers import load_script

keynote = load_script("generate-english-keynote.py")


def test_timing_instruction_is_generic_and_explicit() -> None:
    instruction = keynote.build_instruct(
        keynote.DEFAULT_INSTRUCT,
        target_seconds=45,
        instructed_wpm=132,
    )

    assert "45 seconds" in instruction
    assert "132 words per minute" in instruction
    assert "do not omit, add, or repeat words" in instruction
    assert "defense" not in instruction.lower()
    assert "male" not in instruction.lower()


def test_timing_helpers() -> None:
    assert keynote.clamp(70, 85, 190) == 85
    assert keynote.clamp(130, 85, 190) == 130
    assert keynote.clamp(220, 85, 190) == 190
    assert keynote.signed_timing_error(54, 50) == 0.08
    assert keynote.format_clock(125.4) == "2:05"
