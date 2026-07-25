from __future__ import annotations

from pathlib import Path

from tests.helpers import load_script

subtitles = load_script("generate-english-subtitles.py")


def test_reference_correction_keeps_times_and_restores_spelling() -> None:
    raw = [
        subtitles.Caption(0.0, 2.5, "Today Orator Deck keeps every aligned asset."),
        subtitles.Caption(2.5, 5.0, "It stays in sync for the final video."),
    ]
    reference = (
        "Today OratorDeck keeps every aligned asset. "
        "It stays in sync for the final video."
    )

    corrected, matched, total, applied = subtitles.correct_with_reference(raw, reference)

    assert applied
    assert matched / total >= 0.60
    assert [(cue.start, cue.end) for cue in corrected] == [(0.0, 2.5), (2.5, 5.0)]
    assert " ".join(cue.text for cue in corrected) == reference


def test_writers_emit_standard_headers(tmp_path: Path) -> None:
    cues = [subtitles.Caption(1.25, 3.5, "A short caption.")]
    srt = tmp_path / "demo.srt"
    vtt = tmp_path / "demo.vtt"
    lrc = tmp_path / "demo.lrc"

    subtitles.write_srt(srt, cues)
    subtitles.write_vtt(vtt, cues)
    subtitles.write_lrc(lrc, cues)

    assert "00:00:01,250 --> 00:00:03,500" in srt.read_text(encoding="utf-8")
    assert vtt.read_text(encoding="utf-8").startswith("WEBVTT\n")
    assert lrc.read_text(encoding="utf-8") == "[00:01.25]A short caption.\n"
