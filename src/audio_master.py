"""FFmpeg 9.0 EBU R128 two-pass loudness normalization and `atempo=1.04x` mastering."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from src.models import AudioMasterResult

WINGET_FFMPEG_BIN_DIR = (
    Path.home()
    / "AppData"
    / "Local"
    / "Microsoft"
    / "WinGet"
    / "Packages"
    / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "ffmpeg-9.0-full_build"
    / "bin"
)

TARGET_LUFS = -14.0
TARGET_TP_DB = -1.5
TARGET_LRA = 11.0
ATEMPO_FACTOR = 1.04
MAX_DURATION_SEC = 45.0
SAMPLE_RATE_HZ = 44100
CHANNELS = 2

SILENCEREMOVE_FILTER = (
    "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB:"
    "stop_periods=-1:stop_duration=0.18:stop_threshold=-45dB"
)


def resolve_ffmpeg_tool(tool_name: str) -> str:
    """Finds `ffmpeg` or `ffprobe` on PATH or inside the WinGet FFmpeg 9.0 directory."""
    found = shutil.which(tool_name)
    if found:
        return found
    candidate = WINGET_FFMPEG_BIN_DIR / f"{tool_name}.exe"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        f"Required binary '{tool_name}' not found on PATH or at {candidate}"
    )


def _run_cmd(cmd: list[str], timeout_sec: int = 120) -> subprocess.CompletedProcess[str]:
    """Runs subprocess command with UTF-8 decoding and detailed error reporting."""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (rc={proc.returncode}): {' '.join(cmd)}\n"
            f"STDERR:\n{proc.stderr.strip()}"
        )
    return proc


def probe_duration_sec(media_path: Path) -> float:
    """Returns exact media duration in seconds using `ffprobe`."""
    if not media_path.exists():
        raise FileNotFoundError(f"Cannot probe missing media file: {media_path}")
    ffprobe_bin = resolve_ffmpeg_tool("ffprobe")
    proc = _run_cmd(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        timeout_sec=30,
    )
    return round(float(proc.stdout.strip()), 3)


def probe_volume_db(media_path: Path) -> tuple[float, float]:
    """Measures `(mean_volume_db, max_volume_db)` via FFmpeg `volumedetect`."""
    if not media_path.exists():
        raise FileNotFoundError(f"Cannot measure volume of missing file: {media_path}")
    ffmpeg_bin = resolve_ffmpeg_tool("ffmpeg")
    proc = _run_cmd(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-i",
            str(media_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "NUL",
        ],
        timeout_sec=30,
    )
    mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", proc.stderr)
    max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", proc.stderr)
    if not mean_match or not max_match:
        raise RuntimeError(
            f"Could not parse volumedetect telemetry for {media_path}:\n{proc.stderr}"
        )
    return float(mean_match.group(1)), float(max_match.group(1))


def _measure_loudnorm_pass1(ffmpeg_bin: str, raw_wav_path: Path) -> dict[str, str]:
    """Runs pass-1 EBU R128 analysis on trimmed + tempo-scaled speech and parses JSON stats."""
    analysis_chain = (
        f"{SILENCEREMOVE_FILTER},"
        f"atempo={ATEMPO_FACTOR:.2f},"
        f"aresample={SAMPLE_RATE_HZ},"
        "aformat=sample_fmts=s16:channel_layouts=stereo,"
        f"loudnorm=I={TARGET_LUFS:.1f}:TP={TARGET_TP_DB:.1f}:LRA={TARGET_LRA:.1f}:print_format=json"
    )
    proc = _run_cmd(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-i",
            str(raw_wav_path),
            "-af",
            analysis_chain,
            "-f",
            "null",
            "NUL",
        ],
        timeout_sec=60,
    )
    json_match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.DOTALL)
    if not json_match:
        raise RuntimeError(
            f"Could not parse FFmpeg loudnorm pass-1 JSON telemetry:\n{proc.stderr}"
        )
    parsed: dict[str, object] = json.loads(json_match.group(0))
    return {
        "input_i": str(parsed["input_i"]),
        "input_tp": str(parsed["input_tp"]),
        "input_lra": str(parsed["input_lra"]),
        "input_thresh": str(parsed["input_thresh"]),
        "target_offset": str(parsed["target_offset"]),
    }


def master_slide_audio(
    slide_id: str,
    raw_wav_path: Path,
    audio_out_dir: Path,
    remove_raw: bool = True,
) -> AudioMasterResult:
    """Applies two-pass linear EBU R128 + `1.04x` tempo mastering to `.wav` and `.mp3`."""
    if not raw_wav_path.exists():
        raise FileNotFoundError(f"Raw TTS WAV missing: {raw_wav_path}")

    ffmpeg_bin = resolve_ffmpeg_tool("ffmpeg")
    audio_out_dir.mkdir(parents=True, exist_ok=True)

    master_wav_path = audio_out_dir / f"{slide_id}.wav"
    master_mp3_path = audio_out_dir / f"{slide_id}.mp3"

    raw_duration_sec = probe_duration_sec(raw_wav_path)
    stats = _measure_loudnorm_pass1(ffmpeg_bin, raw_wav_path)

    pass2_chain = (
        f"{SILENCEREMOVE_FILTER},"
        f"atempo={ATEMPO_FACTOR:.2f},"
        f"aresample={SAMPLE_RATE_HZ},"
        "aformat=sample_fmts=s16:channel_layouts=stereo,"
        f"loudnorm=I={TARGET_LUFS:.1f}:TP={TARGET_TP_DB:.1f}:LRA={TARGET_LRA:.1f}:"
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true:print_format=none,"
        f"aresample={SAMPLE_RATE_HZ},"
        "alimiter=limit=0.84:level=false:asc=false,"
        "aformat=sample_fmts=s16:channel_layouts=stereo"
    )

    _run_cmd(
        [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(raw_wav_path),
            "-af",
            pass2_chain,
            "-ar",
            str(SAMPLE_RATE_HZ),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(master_wav_path),
        ],
        timeout_sec=120,
    )

    _run_cmd(
        [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(master_wav_path),
            "-ar",
            str(SAMPLE_RATE_HZ),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(master_mp3_path),
        ],
        timeout_sec=120,
    )

    if remove_raw and raw_wav_path.resolve() != master_wav_path.resolve() and raw_wav_path.exists():
        raw_wav_path.unlink()

    mastered_duration_sec = probe_duration_sec(master_wav_path)
    if mastered_duration_sec > MAX_DURATION_SEC:
        raise ValueError(
            f"Mastered audio for '{slide_id}' is {mastered_duration_sec:.3f}s, "
            f"exceeding hard ceiling {MAX_DURATION_SEC:.1f}s."
        )

    mean_volume_db, max_volume_db = probe_volume_db(master_wav_path)
    return AudioMasterResult(
        slide_id=slide_id,
        raw_wav_path=str(raw_wav_path.resolve()),
        master_wav_path=str(master_wav_path.resolve()),
        master_mp3_path=str(master_mp3_path.resolve()),
        raw_duration_sec=raw_duration_sec,
        mastered_duration_sec=mastered_duration_sec,
        atempo_factor=ATEMPO_FACTOR,
        mean_volume_db=mean_volume_db,
        max_volume_db=max_volume_db,
        target_lufs=TARGET_LUFS,
    )
