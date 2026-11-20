"""Strongly typed immutable data contracts for `pierre-voice-engine`."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True, frozen=True)
class BilingualScript:
    """Validated English narration script paired with French subtitle text."""

    slide_id: str
    source_path: str
    en_text: str
    fr_text: str
    en_word_count: int
    estimated_duration_sec: float
    fr_auto_translated: bool


@dataclass(slots=True, frozen=True)
class SubtitleChunk:
    """Time-aligned French lower-third subtitle card segment."""

    index: int
    text: str
    start_sec: float
    end_sec: float


@dataclass(slots=True, frozen=True)
class AudioMasterResult:
    """Broadcast-mastered audio telemetry produced by FFmpeg EBU R128 + atempo."""

    slide_id: str
    raw_wav_path: str
    master_wav_path: str
    master_mp3_path: str
    raw_duration_sec: float
    mastered_duration_sec: float
    atempo_factor: float
    mean_volume_db: float
    max_volume_db: float
    target_lufs: float


@dataclass(slots=True, frozen=True)
class SlideVideoManifest:
    """Immutable per-slide render telemetry emitted by `narrator_cli.py`."""

    generated_at_utc: str
    slide_id: str
    script_path: str
    slide_png_path: str
    en_word_count: int
    fr_subtitle_chunks: int
    audio_wav_path: str
    audio_mp3_path: str
    video_mp4_path: str | None
    duration_sec: float
    atempo_factor: float
    target_lufs: float
    mean_volume_db: float
    max_volume_db: float
    resolution: str
    fps: int
    zoom_start: float
    zoom_end: float

    def to_dict(self) -> dict[str, object]:
        """Serializes manifest dataclass fields to a JSON-ready dictionary."""
        return asdict(self)

