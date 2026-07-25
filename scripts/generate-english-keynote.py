#!/usr/bin/env python3
"""Generate an English keynote from slide-atomic speaker-note chunks.

Each input chunk remains one indivisible Qwen item. Several complete chunks
are submitted in one GPU batch for throughput, and the server returns one WAV
per item. The slide's target time determines the requested speaking pace. If
an attempt misses the configured tolerance, the next timing round calibrates
the pace from the measured WAV duration. The closest attempt is retained.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

FORMAT_VERSION = "oratordeck.speaker-notes-chunks.v1"
MAX_TEXT_CHARS = 5_000
DEFAULT_INSTRUCT = (
    "Speak in clear, confident, natural English for a live professional presentation. "
    "Sound focused and conversational, with controlled energy, precise articulation, "
    "modest emphasis, and brief natural pauses. Avoid whispering, theatrical suspense, "
    "or exaggerated emotion."
)
WORD_RE = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b", flags=re.UNICODE)


@dataclass(frozen=True)
class Attempt:
    number: int
    instructed_wpm: float
    duration_seconds: float
    wav_bytes: bytes
    seed: int | None


def api_json(url: str):
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Voicebox returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach Voicebox at {url}: {error.reason}") from error


def request_atomic_wavs(url: str, payload: dict) -> tuple[dict[str, bytes], dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/zip", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=60 * 60) as response:
            archive_bytes = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Voicebox returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach Voicebox at {url}: {error.reason}") from error

    expected_ids = [item["id"] for item in payload["chunks"]]
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "voicebox.atomic-tts-batch.v1":
                raise RuntimeError(
                    f"Voicebox returned unsupported atomic batch format "
                    f"{manifest.get('format')!r}"
                )
            manifest_items = manifest.get("items")
            if not isinstance(manifest_items, list):
                raise RuntimeError("Voicebox atomic batch manifest has no item list")
            returned_ids = [item.get("id") for item in manifest_items]
            if returned_ids != expected_ids:
                raise RuntimeError(
                    f"Voicebox changed atomic batch order: expected {expected_ids}, "
                    f"received {returned_ids}"
                )
            wavs = {
                item["id"]: archive.read(item["filename"])
                for item in manifest_items
            }
    except (KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise RuntimeError(f"Voicebox returned an invalid atomic batch ZIP: {error}") from error

    for item_id, wav_bytes in wavs.items():
        if len(wav_bytes) < 44:
            raise RuntimeError(
                f"Voicebox returned an invalid WAV for {item_id} ({len(wav_bytes)} bytes)"
            )
    return wavs, manifest


def find_profile_id(base_url: str, profile_name: str) -> str:
    profiles = api_json(f"{base_url}/profiles")
    for profile in profiles:
        if profile.get("name") == profile_name:
            return profile["id"]
    raise RuntimeError(
        f"No profile named {profile_name!r}. Create it in Voicebox first, "
        "or pass --profile-id."
    )


def wav_info(wav_bytes: bytes) -> tuple[float, int, int]:
    with sf.SoundFile(io.BytesIO(wav_bytes)) as wav_file:
        if wav_file.frames <= 0 or wav_file.samplerate <= 0:
            raise RuntimeError("Voicebox returned an empty WAV")
        return (
            wav_file.frames / wav_file.samplerate,
            wav_file.samplerate,
            wav_file.channels,
        )


def load_chunk_document(path: Path) -> tuple[dict, list[dict]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{path} is not valid JSON: {error}") from error

    if document.get("format") != FORMAT_VERSION:
        raise RuntimeError(
            f"{path} has format {document.get('format')!r}; expected {FORMAT_VERSION!r}. "
            "Regenerate it with format-speaker-notes-chunks.py."
        )
    source_name = document.get("source")
    source_sha256 = document.get("source_sha256")
    if isinstance(source_name, str) and Path(source_name).name == source_name:
        source_path = path.parent / source_name
        if source_path.exists():
            actual_source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual_source_sha256 != source_sha256:
                raise RuntimeError(
                    f"{path} is stale: {source_path.name} no longer matches its "
                    "source_sha256. Run format-speaker-notes-chunks.py again."
                )
    raw_chunks = document.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise RuntimeError(f"{path} contains no chunks")
    if document.get("chunk_count") != len(raw_chunks):
        raise RuntimeError(
            f"{path} declares {document.get('chunk_count')} chunks but contains "
            f"{len(raw_chunks)}"
        )

    chunks: list[dict] = []
    seen_ids: set[str] = set()
    for index, raw_chunk in enumerate(raw_chunks, start=1):
        if not isinstance(raw_chunk, dict):
            raise RuntimeError(f"Chunk {index} is not an object")
        chunk_id = raw_chunk.get("id")
        title = raw_chunk.get("title")
        text = raw_chunk.get("text")
        target_seconds = raw_chunk.get("target_seconds")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise RuntimeError(f"Chunk {index} has no valid id")
        if chunk_id in seen_ids:
            raise RuntimeError(f"Duplicate chunk id: {chunk_id}")
        seen_ids.add(chunk_id)
        if not isinstance(title, str) or not title:
            raise RuntimeError(f"Chunk {chunk_id} has no title")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"Chunk {chunk_id} has no text")
        text = text.strip()
        if len(text) > MAX_TEXT_CHARS:
            raise RuntimeError(
                f"Chunk {chunk_id} has {len(text):,} characters; indivisible Voicebox "
                f"requests are limited to {MAX_TEXT_CHARS:,}"
            )
        if not isinstance(target_seconds, (int, float)) or target_seconds <= 0:
            raise RuntimeError(f"Chunk {chunk_id} has invalid target_seconds")

        chunk = dict(raw_chunk)
        chunk["text"] = text
        chunk["target_seconds"] = float(target_seconds)
        chunk["words"] = len(WORD_RE.findall(text))
        chunk["target_wpm"] = chunk["words"] * 60 / chunk["target_seconds"]
        chunks.append(chunk)

    declared_total = document.get("total_target_seconds")
    calculated_total = sum(chunk["target_seconds"] for chunk in chunks)
    if declared_total is None or abs(float(declared_total) - calculated_total) > 0.001:
        raise RuntimeError(
            f"{path} has inconsistent total_target_seconds: "
            f"declared {declared_total}, calculated {calculated_total}"
        )
    return document, chunks


def build_instruct(
    base_instruct: str,
    *,
    target_seconds: float,
    instructed_wpm: float,
) -> str:
    timing = (
        f" Timing takes priority: deliver this slide in about {target_seconds:.0f} seconds "
        f"at approximately {instructed_wpm:.0f} words per minute. Read all content exactly "
        "once; do not omit, add, or repeat words, and avoid long dramatic pauses."
    )
    instruct = base_instruct.strip() + timing
    if len(instruct) > 500:
        raise RuntimeError(
            f"The combined style and timing instruction is {len(instruct)} characters; "
            "Voicebox accepts at most 500. Shorten --instruct."
        )
    return instruct


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def signed_timing_error(duration_seconds: float, target_seconds: float) -> float:
    return (duration_seconds - target_seconds) / target_seconds


def format_clock(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    return f"{rounded // 60}:{rounded % 60:02d}"


def render_progress(
    completed: int,
    total: int,
    chunk_id: str,
    attempt: int,
    attempts: int,
) -> None:
    width = 28
    filled = int(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    print(
        f"[{bar}] {completed}/{total} selected | {chunk_id} "
        f"attempt {attempt}/{attempts}",
        flush=True,
    )


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def merge_wavs(
    chunk_paths: list[Path],
    output_path: Path,
    silence_ms: int,
) -> float:
    if not chunk_paths:
        raise RuntimeError("No chunk WAV files were selected")

    first = sf.info(chunk_paths[0])
    sample_rate = first.samplerate
    channels = first.channels
    silence_frames = round(sample_rate * silence_ms / 1000)
    silence = np.zeros((silence_frames, channels), dtype=np.float32)
    frames_written = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(
        output_path,
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        subtype="PCM_16",
        format="WAV",
    ) as output:
        for index, chunk_path in enumerate(chunk_paths):
            with sf.SoundFile(chunk_path) as chunk_file:
                if chunk_file.samplerate != sample_rate or chunk_file.channels != channels:
                    raise RuntimeError(
                        f"{chunk_path} is {chunk_file.samplerate} Hz/"
                        f"{chunk_file.channels} ch; expected {sample_rate} Hz/{channels} ch"
                    )
                while True:
                    audio = chunk_file.read(65_536, dtype="float32", always_2d=True)
                    if len(audio) == 0:
                        break
                    output.write(audio)
                    frames_written += len(audio)
            if silence_frames and index + 1 < len(chunk_paths):
                output.write(silence)
                frames_written += silence_frames
    return frames_written / sample_rate


def default_output_path(repo_root: Path, chunks_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return repo_root / "data" / "generations" / f"{chunks_path.stem}-{timestamp}.wav"


def print_plan(chunks: list[dict]) -> None:
    print("Slide timing plan:")
    for chunk in chunks:
        print(
            f"  {chunk['id']:>8}  target={format_clock(chunk['target_seconds'])}  "
            f"words={chunk['words']:>3}  chars={len(chunk['text']):>4}  "
            f"pace={chunk['target_wpm']:>6.1f} wpm  {chunk['title']}"
        )
    total = sum(chunk["target_seconds"] for chunk in chunks)
    print(f"Total: {len(chunks)} chunks, target {format_clock(total)}")


def timing_report_entry(state: dict, timing_tolerance: float, repo_root: Path) -> dict:
    chunk = state["chunk"]
    target_seconds = chunk["target_seconds"]
    attempts = state["attempts"]
    selected = min(
        attempts,
        key=lambda candidate: abs(
            signed_timing_error(candidate.duration_seconds, target_seconds)
        ),
    )
    selected_error = signed_timing_error(selected.duration_seconds, target_seconds)
    return {
        "id": chunk["id"],
        "slide": chunk.get("slide"),
        "title": chunk["title"],
        "target_seconds": target_seconds,
        "actual_seconds": round(selected.duration_seconds, 6),
        "error_seconds": round(selected.duration_seconds - target_seconds, 6),
        "error_ratio": round(selected_error, 8),
        "within_tolerance": abs(selected_error) <= timing_tolerance,
        "selected_attempt": selected.number,
        "selected_instructed_wpm": round(selected.instructed_wpm, 3),
        "audio_path": relative_to_repo(state["chunk_path"], repo_root),
        "timing_complete": state["complete"],
        "attempts": [
            {
                "number": attempt.number,
                "instructed_wpm": round(attempt.instructed_wpm, 3),
                "duration_seconds": round(attempt.duration_seconds, 6),
                "error_ratio": round(
                    signed_timing_error(attempt.duration_seconds, target_seconds),
                    8,
                ),
                "seed": attempt.seed,
            }
            for attempt in attempts
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_file", type=Path, help="JSON chunk file from the formatter")
    parser.add_argument("--url", default="http://127.0.0.1:17493", help="Voicebox URL")
    parser.add_argument("--profile-id", help="Use a specific Voicebox profile ID")
    parser.add_argument(
        "--profile-name",
        help="Exact name of a Voicebox Qwen CustomVoice profile",
    )
    parser.add_argument("--instruct", default=DEFAULT_INSTRUCT)
    parser.add_argument("--output", type=Path, help="Final WAV path")
    parser.add_argument(
        "--timing-attempts",
        type=int,
        default=2,
        help="Maximum syntheses per slide (default: 2)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Complete slides submitted per Qwen GPU batch (default: 4, maximum: 8)",
    )
    parser.add_argument(
        "--timing-tolerance",
        type=float,
        default=0.08,
        help="Acceptable relative duration error, e.g. 0.08 = 8%% (default: 0.08)",
    )
    parser.add_argument("--min-wpm", type=float, default=85.0)
    parser.add_argument("--max-wpm", type=float, default=190.0)
    parser.add_argument(
        "--join-silence-ms",
        type=int,
        default=0,
        help="Silence inserted between selected slide WAVs (default: 0)",
    )
    parser.add_argument("--seed", type=int, help="Optional base seed")
    parser.add_argument(
        "--limit",
        type=int,
        help="Generate only the first N chunks (useful for a diagnostic smoke run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the timing plan without contacting Voicebox",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output WAV/report/chunk WAVs",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.dry_run and not args.profile_id and not args.profile_name:
        raise RuntimeError(
            "Pass either --profile-id or --profile-name for Voicebox synthesis"
        )
    if args.profile_id and args.profile_name:
        raise RuntimeError("--profile-id and --profile-name are mutually exclusive")
    if not 1 <= args.timing_attempts <= 5:
        raise RuntimeError("--timing-attempts must be between 1 and 5")
    if not 1 <= args.batch_size <= 8:
        raise RuntimeError("--batch-size must be between 1 and 8")
    if not 0 <= args.timing_tolerance <= 0.5:
        raise RuntimeError("--timing-tolerance must be between 0 and 0.5")
    if args.min_wpm <= 0 or args.max_wpm <= args.min_wpm:
        raise RuntimeError("--min-wpm must be positive and lower than --max-wpm")
    if not 0 <= args.join_silence_ms <= 5_000:
        raise RuntimeError("--join-silence-ms must be between 0 and 5000")
    if args.seed is not None and args.seed < 0:
        raise RuntimeError("--seed must be non-negative")
    if args.limit is not None and args.limit < 1:
        raise RuntimeError("--limit must be at least 1")


def main() -> int:
    args = parse_args()
    validate_args(args)
    repo_root = Path(__file__).resolve().parents[1]
    chunks_path = args.chunks_file.resolve()
    document, chunks = load_chunk_document(chunks_path)
    if args.limit is not None:
        chunks = chunks[: args.limit]
    print_plan(chunks)
    if args.dry_run:
        return 0

    output_path = (
        args.output.resolve()
        if args.output
        else default_output_path(repo_root, chunks_path)
    )
    if output_path.suffix.lower() != ".wav":
        raise RuntimeError("--output must use a .wav filename")
    chunks_dir = output_path.parent / f"{output_path.stem}.chunks"
    report_path = output_path.with_suffix(".timing.json")
    existing_paths = [path for path in (output_path, report_path) if path.exists()]
    if chunks_dir.exists() and any(chunks_dir.iterdir()):
        existing_paths.append(chunks_dir)
    if existing_paths and not args.overwrite:
        rendered = ", ".join(str(path) for path in existing_paths)
        raise RuntimeError(f"Output artifacts already exist: {rendered}; pass --overwrite")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    base_url = args.url.rstrip("/")
    profile_id = args.profile_id or find_profile_id(base_url, args.profile_name)
    input_sha256 = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    started_at = datetime.now(UTC)
    report = {
        "format": "oratordeck.keynote-timing-report.v1",
        "status": "generating",
        "input": relative_to_repo(chunks_path, repo_root),
        "input_sha256": input_sha256,
        "source_sha256": document.get("source_sha256"),
        "started_at": started_at.isoformat(),
        "profile_id": profile_id,
        "profile_name": args.profile_name,
        "engine": "qwen_custom_voice",
        "model_size": "1.7B",
        "timing_attempts": args.timing_attempts,
        "timing_tolerance": args.timing_tolerance,
        "batch_size": args.batch_size,
        "join_silence_ms": args.join_silence_ms,
        "output_wav": relative_to_repo(output_path, repo_root),
        "chunks": [],
    }
    write_report(report_path, report)

    states = []
    for chunk_index, chunk in enumerate(chunks):
        states.append(
            {
                "index": chunk_index,
                "chunk": chunk,
                "instructed_wpm": clamp(
                    chunk["target_wpm"],
                    args.min_wpm,
                    args.max_wpm,
                ),
                "attempts": [],
                "complete": False,
                "chunk_path": chunks_dir / f"{chunk_index + 1:03d}-{chunk['id']}.wav",
            }
        )

    request_number = 0
    try:
        for attempt_number in range(1, args.timing_attempts + 1):
            pending = [state for state in states if not state["complete"]]
            if not pending:
                break
            for group_start in range(0, len(pending), args.batch_size):
                group = pending[group_start : group_start + args.batch_size]
                completed_count = sum(1 for state in states if state["complete"])
                group_ids = ",".join(state["chunk"]["id"] for state in group)
                render_progress(
                    completed_count,
                    len(chunks),
                    group_ids,
                    attempt_number,
                    args.timing_attempts,
                )
                request_seed = None if args.seed is None else args.seed + request_number
                request_number += 1
                payload = {
                    "profile_id": profile_id,
                    "chunks": [
                        {
                            "id": state["chunk"]["id"],
                            "text": state["chunk"]["text"],
                            "instruct": build_instruct(
                                args.instruct,
                                target_seconds=state["chunk"]["target_seconds"],
                                instructed_wpm=state["instructed_wpm"],
                            ),
                        }
                        for state in group
                    ],
                    "language": "en",
                    "model_size": "1.7B",
                    "engine": "qwen_custom_voice",
                    "normalize": True,
                    "seed": request_seed,
                }
                wavs, _ = request_atomic_wavs(
                    f"{base_url}/generate/atomic-batch",
                    payload,
                )
                for state in group:
                    chunk = state["chunk"]
                    chunk_id = chunk["id"]
                    target_seconds = chunk["target_seconds"]
                    instructed_wpm = state["instructed_wpm"]
                    wav_bytes = wavs[chunk_id]
                    duration_seconds, _, _ = wav_info(wav_bytes)
                    attempt = Attempt(
                        number=attempt_number,
                        instructed_wpm=instructed_wpm,
                        duration_seconds=duration_seconds,
                        wav_bytes=wav_bytes,
                        seed=request_seed,
                    )
                    state["attempts"].append(attempt)
                    error = signed_timing_error(duration_seconds, target_seconds)
                    print(
                        f"  {chunk_id} attempt {attempt_number}: "
                        f"target={target_seconds:.1f}s actual={duration_seconds:.2f}s "
                        f"error={error:+.1%} instructed={instructed_wpm:.1f} wpm",
                        flush=True,
                    )
                    state["complete"] = (
                        abs(error) <= args.timing_tolerance
                        or attempt_number == args.timing_attempts
                    )
                    if not state["complete"]:
                        state["instructed_wpm"] = clamp(
                            instructed_wpm * duration_seconds / target_seconds,
                            args.min_wpm,
                            args.max_wpm,
                        )

                    selected = min(
                        state["attempts"],
                        key=lambda candidate: abs(
                            signed_timing_error(
                                candidate.duration_seconds,
                                target_seconds,
                            )
                        ),
                    )
                    state["chunk_path"].write_bytes(selected.wav_bytes)

                report["chunks"] = [
                    timing_report_entry(state, args.timing_tolerance, repo_root)
                    for state in states
                    if state["attempts"]
                ]
                report["chunks_completed"] = sum(
                    1 for state in states if state["complete"]
                )
                write_report(report_path, report)

        selected_paths = [state["chunk_path"] for state in states]
        for state in states:
            entry = timing_report_entry(state, args.timing_tolerance, repo_root)
            print(
                f"Selected {entry['id']} attempt {entry['selected_attempt']}: "
                f"{entry['actual_seconds']:.2f}s ({entry['error_ratio']:+.1%}).",
                flush=True,
            )

        final_duration = merge_wavs(
            selected_paths,
            output_path,
            args.join_silence_ms,
        )
        completed_at = datetime.now(UTC)
        target_total = sum(chunk["target_seconds"] for chunk in chunks)
        selected_total = sum(item["actual_seconds"] for item in report["chunks"])
        within_tolerance = sum(
            1 for item in report["chunks"] if item["within_tolerance"]
        )
        report.update(
            {
                "status": "completed",
                "completed_at": completed_at.isoformat(),
                "wall_seconds": round(
                    (completed_at - started_at).total_seconds(),
                    3,
                ),
                "target_seconds": target_total,
                "selected_audio_seconds": round(selected_total, 6),
                "final_wav_seconds": round(final_duration, 6),
                "total_error_seconds": round(selected_total - target_total, 6),
                "chunks_within_tolerance": within_tolerance,
                "chunk_count": len(chunks),
            }
        )
        write_report(report_path, report)
    except Exception as error:
        report["status"] = "failed"
        report["failed_at"] = datetime.now(UTC).isoformat()
        report["error"] = str(error)
        write_report(report_path, report)
        raise

    print(f"Completed {len(chunks)} indivisible chunks.")
    print(
        f"Timing: target={format_clock(report['target_seconds'])} "
        f"selected={format_clock(report['selected_audio_seconds'])} "
        f"within_tolerance={report['chunks_within_tolerance']}/{len(chunks)}"
    )
    print(f"WAV: {output_path}")
    print(f"Timing report: {report_path}")
    print(f"Per-slide WAVs: {chunks_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
