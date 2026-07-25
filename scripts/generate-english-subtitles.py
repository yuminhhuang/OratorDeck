#!/usr/bin/env python3
"""Create English SRT, WebVTT, and LRC subtitles from a local WAV with Whisper.

The script is deliberately idle until invoked.  At runtime it downloads the
selected Whisper model to this checkout's ``models/`` directory, transcribes
the WAV locally, and writes subtitle files beside the input audio.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

MODEL_IDS = {
    "base": "openai/whisper-base",
    "small": "openai/whisper-small",
    "medium": "openai/whisper-medium",
    "large": "openai/whisper-large-v3",
    "turbo": "openai/whisper-large-v3-turbo",
}
TARGET_SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str


TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")


def tokenise(text: str) -> list[tuple[str, int, int]]:
    """Return lowercase comparison tokens with their original character spans."""
    return [(match.group(0).lower(), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def configure_local_cache() -> Path:
    project_dir = Path(__file__).resolve().parents[1]
    os.environ.setdefault("HF_HOME", str(project_dir / "models" / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("XDG_CACHE_HOME", str(project_dir / ".cache" / "xdg"))
    selected_gpu = os.environ.get("ORATORDECK_GPU")
    if selected_gpu:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", selected_gpu)
    return project_dir


def format_timestamp(seconds: float, *, srt: bool) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def wrap_text(text: str, line_limit: int = 42) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > line_limit:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def split_caption(caption: Caption, max_chars: int = 84) -> list[Caption]:
    """Keep each subtitle readable, apportioning a segment's time by text size."""
    words = caption.text.split()
    groups: list[str] = []
    group = ""
    for word in words:
        candidate = f"{group} {word}".strip()
        if group and len(candidate) > max_chars:
            groups.append(group)
            group = word
        else:
            group = candidate
    if group:
        groups.append(group)
    if len(groups) <= 1:
        return [Caption(caption.start, caption.end, wrap_text(caption.text))]

    duration = max(0.01, caption.end - caption.start)
    total_weight = sum(max(1, len(group)) for group in groups)
    cursor = caption.start
    result: list[Caption] = []
    for index, group in enumerate(groups):
        if index == len(groups) - 1:
            end = caption.end
        else:
            end = cursor + duration * max(1, len(group)) / total_weight
        result.append(Caption(cursor, end, wrap_text(group)))
        cursor = end
    return result


def make_readable(captions: list[Caption]) -> list[Caption]:
    return [part for caption in captions for part in split_caption(caption)]


def correct_with_reference(
    captions: list[Caption], reference_text: str
) -> tuple[list[Caption], int, int, bool]:
    """Replace Whisper wording with the source manuscript while retaining timing.

    The generated audio was synthesized from the source manuscript, so a high
    word-order match lets us safely retain Whisper's timing and use the exact
    source spelling for names, acronyms, numbers, and technical vocabulary.
    """
    reference_tokens = tokenise(reference_text)
    asr_tokens: list[str] = []
    asr_caption_indexes: list[int] = []
    for caption_index, caption in enumerate(captions):
        for token, _, _ in tokenise(caption.text):
            asr_tokens.append(token)
            asr_caption_indexes.append(caption_index)
    if not reference_tokens or not asr_tokens:
        return captions, 0, len(asr_tokens), False

    matcher = SequenceMatcher(None, asr_tokens, [token[0] for token in reference_tokens], autojunk=False)
    token_matches: dict[int, int] = {}
    exact_match_count = 0
    for tag, asr_start, asr_end, reference_start, reference_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(asr_end - asr_start):
                token_matches[asr_start + offset] = reference_start + offset
                exact_match_count += 1
        # Preserve subtitle timing for small, localized recognition errors. The
        # exact-match threshold below still guards against an unrelated script.
        elif tag == "replace" and asr_end - asr_start <= 4 and reference_end - reference_start <= 4:
            asr_length = asr_end - asr_start
            reference_length = reference_end - reference_start
            for offset in range(asr_length):
                relative_reference = min(reference_length - 1, offset * reference_length // asr_length)
                token_matches[asr_start + offset] = reference_start + relative_reference
    # If this is not recognizably the same speech, retaining the ASR text is
    # safer than forcing an unrelated manuscript onto its timestamps.
    if exact_match_count / len(asr_tokens) < 0.60:
        return captions, exact_match_count, len(asr_tokens), False

    first_reference_token: list[int | None] = [None] * len(captions)
    for asr_index, reference_index in token_matches.items():
        caption_index = asr_caption_indexes[asr_index]
        if first_reference_token[caption_index] is None:
            first_reference_token[caption_index] = reference_index

    corrected: list[Caption] = []
    reference_cursor = 0
    for caption_index, caption in enumerate(captions):
        next_reference_start = None
        for future_start in first_reference_token[caption_index + 1 :]:
            if future_start is not None and future_start >= reference_cursor:
                next_reference_start = future_start
                break
        reference_end = (
            next_reference_start - 1 if next_reference_start is not None else len(reference_tokens) - 1
        )
        if reference_end < reference_cursor:
            return captions, exact_match_count, len(asr_tokens), False
        start_char = reference_tokens[reference_cursor][1]
        end_char = (
            reference_tokens[reference_end + 1][1]
            if reference_end + 1 < len(reference_tokens)
            else len(reference_text)
        )
        corrected.append(Caption(caption.start, caption.end, reference_text[start_char:end_char].strip()))
        reference_cursor = reference_end + 1

    if reference_cursor != len(reference_tokens):
        return captions, exact_match_count, len(asr_tokens), False
    return corrected, exact_match_count, len(asr_tokens), True


def write_srt(path: Path, captions: list[Caption]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, caption in enumerate(captions, start=1):
            handle.write(f"{index}\n")
            handle.write(
                f"{format_timestamp(caption.start, srt=True)} --> "
                f"{format_timestamp(caption.end, srt=True)}\n"
            )
            handle.write(f"{caption.text}\n\n")


def write_vtt(path: Path, captions: list[Caption]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("WEBVTT\n\n")
        for caption in captions:
            handle.write(
                f"{format_timestamp(caption.start, srt=False)} --> "
                f"{format_timestamp(caption.end, srt=False)}\n"
            )
            handle.write(f"{caption.text}\n\n")


def format_lrc_timestamp(seconds: float) -> str:
    """Return a standard centisecond LRC timestamp such as ``[03:07.42]``."""
    centiseconds = max(0, round(seconds * 100))
    minutes, centiseconds = divmod(centiseconds, 6_000)
    whole_seconds, centiseconds = divmod(centiseconds, 100)
    return f"[{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}]"


def write_lrc(path: Path, captions: list[Caption]) -> None:
    """Write one timestamped lyric line per subtitle caption.

    LRC has one timestamp per line, so a caption's start time is used.  Fold
    wrapped subtitle lines back into one readable LRC line.
    """
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for caption in captions:
            text = " ".join(caption.text.split())
            if text:
                handle.write(f"{format_lrc_timestamp(caption.start)}{text}\n")


def output_path(prefix: Path, extension: str) -> Path:
    """Append a subtitle extension without discarding dots in the prefix."""
    return prefix.parent / f"{prefix.name}.{extension.lstrip('.')}"


def read_audio(path: Path):
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) == 2:
        audio = audio.mean(axis=1)
    if sample_rate != TARGET_SAMPLE_RATE:
        divisor = math.gcd(sample_rate, TARGET_SAMPLE_RATE)
        audio = resample_poly(audio, TARGET_SAMPLE_RATE // divisor, sample_rate // divisor)
        sample_rate = TARGET_SAMPLE_RATE
    return audio, sample_rate


def make_transcriber(model_name: str, device: str):
    import torch
    from transformers import pipeline

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    pipeline_device = 0 if device == "cuda" else -1
    dtype = torch.float16 if pipeline_device >= 0 else torch.float32
    return pipeline(
        "automatic-speech-recognition",
        model=MODEL_IDS[model_name],
        device=pipeline_device,
        dtype=dtype,
    )


def transcribe(audio, sample_rate: int, transcriber, chunk_seconds: float) -> list[Caption]:
    total_seconds = len(audio) / sample_rate
    total_chunks = math.ceil(total_seconds / chunk_seconds)
    captions: list[Caption] = []
    for index in range(total_chunks):
        start_sample = round(index * chunk_seconds * sample_rate)
        end_sample = min(len(audio), round((index + 1) * chunk_seconds * sample_rate))
        chunk_start = start_sample / sample_rate
        result = transcriber(
            {"array": audio[start_sample:end_sample], "sampling_rate": sample_rate},
            return_timestamps=True,
            generate_kwargs={"language": "english", "task": "transcribe"},
        )
        entries = result.get("chunks") or []
        if not entries and result.get("text", "").strip():
            entries = [{"text": result["text"], "timestamp": (0.0, (end_sample - start_sample) / sample_rate)}]
        for entry in entries:
            timestamp = entry.get("timestamp") or (None, None)
            relative_start, relative_end = timestamp
            if relative_start is None:
                relative_start = 0.0
            if relative_end is None:
                relative_end = (end_sample - start_sample) / sample_rate
            text = entry.get("text", "").strip()
            if text:
                captions.append(Caption(chunk_start + float(relative_start), chunk_start + float(relative_end), text))
        width = 28
        filled = round((index + 1) / total_chunks * width)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\rTranscribing [{bar}] {index + 1}/{total_chunks} chunks", end="", flush=True)
    print()
    return captions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Input WAV audio")
    parser.add_argument("--model", choices=MODEL_IDS, default="turbo")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--chunk-seconds", type=float, default=30.0)
    parser.add_argument(
        "--format",
        choices=("srt", "vtt", "lrc", "both"),
        default="both",
        help="Output format; 'both' writes SRT, WebVTT, and LRC",
    )
    parser.add_argument("--output-prefix", type=Path, help="Path without .srt/.vtt/.lrc suffix")
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "resources" / "SPEAKER_NOTES_TTS.txt",
        help="Manuscript used to correct subtitle wording and technical terminology",
    )
    parser.add_argument(
        "--no-reference-correction",
        action="store_true",
        help="Keep raw Whisper wording instead of replacing it with the reference manuscript",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_local_cache()
    if not args.audio.is_file():
        raise RuntimeError(f"Audio file not found: {args.audio}")
    if not 5 <= args.chunk_seconds <= 60:
        raise RuntimeError("--chunk-seconds must be between 5 and 60")

    print(
        f"Loading Whisper {args.model} on {args.device}; "
        "model downloads stay under OratorDeck/models/."
    )
    transcriber = make_transcriber(args.model, args.device)
    audio, sample_rate = read_audio(args.audio)
    print(f"Transcribing {len(audio) / sample_rate / 60:.1f} minutes of English audio.")
    raw_captions = transcribe(audio, sample_rate, transcriber, args.chunk_seconds)
    if not raw_captions:
        raise RuntimeError("Whisper returned no subtitle segments")

    prefix = args.output_prefix or args.audio.with_suffix("")
    raw_readable = make_readable(raw_captions)
    captions = raw_readable
    corrected = False
    if not args.no_reference_correction:
        if not args.reference.is_file():
            raise RuntimeError(f"Reference manuscript not found: {args.reference}")
        reference_text = args.reference.read_text(encoding="utf-8")
        reference_captions, matched, total, corrected = correct_with_reference(raw_captions, reference_text)
        if corrected:
            captions = make_readable(reference_captions)
            percentage = 100 * matched / total
            print(f"Reference correction applied ({matched}/{total} Whisper words aligned; {percentage:.1f}%).")
        else:
            print("Reference alignment was too weak; keeping raw Whisper wording.", file=sys.stderr)

    if corrected:
        raw_prefix = prefix.with_name(f"{prefix.name}.raw")
        if args.format in {"srt", "both"}:
            write_srt(output_path(raw_prefix, "srt"), raw_readable)
        if args.format in {"vtt", "both"}:
            write_vtt(output_path(raw_prefix, "vtt"), raw_readable)
        if args.format in {"lrc", "both"}:
            write_lrc(output_path(raw_prefix, "lrc"), raw_readable)
    if args.format in {"srt", "both"}:
        path = output_path(prefix, "srt")
        write_srt(path, captions)
        print(f"SRT: {path}")
    if args.format in {"vtt", "both"}:
        path = output_path(prefix, "vtt")
        write_vtt(path, captions)
        print(f"WebVTT: {path}")
    if args.format in {"lrc", "both"}:
        path = output_path(prefix, "lrc")
        write_lrc(path, captions)
        print(f"LRC: {path}")
    if corrected:
        print("Standard subtitles use the reference manuscript; .raw files retain Whisper's original wording.")
    else:
        print("Review technical names against SPEAKER_NOTES_TTS.txt before publishing.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
