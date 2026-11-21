"""End-to-end CLI orchestrator for `pierre-voice-engine` bilingual slide narration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

from src.audio_master import master_slide_audio
from src.models import SlideVideoManifest
from src.script_parser import build_fr_subtitle_chunks, parse_bilingual_script
from src.slide_compositor import (
    CANVAS_H,
    CANVAS_W,
    DEFAULT_SUBTITLE_FONT_SIZE,
    DEFAULT_SUBTITLE_Y,
    FPS,
    STATIC_ZOOM_END,
    STATIC_ZOOM_START,
    render_slide_video,
    resolve_slide_media_path,
)
from src.tts_client import synthesize_en_voiceover

STUDIO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = STUDIO_ROOT / "scripts_input"
SLIDES_DIR = STUDIO_ROOT / "slides_input"
AUDIO_OUT_DIR = STUDIO_ROOT / "audio_out"
VIDEO_OUT_DIR = STUDIO_ROOT / "video_out"

DEFAULT_LEAD_IN_SEC = 1.5
DEFAULT_EXPORT_DIR = Path(r"C:\Users\Pierre\OneDrive\Bureau\Google antigravity voice slide")


def _resolve_script_path(slide_id: str) -> Path:
    """Locates `<slide_id>.txt` or `<slide_id>.md` inside `scripts_input/`."""
    for ext in (".txt", ".md"):
        candidate = SCRIPTS_DIR / f"{slide_id}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No narration script found for '{slide_id}' in {SCRIPTS_DIR} (.txt or .md)"
    )


def _discover_all_slide_ids() -> list[str]:
    """Discovers unique slide IDs from `scripts_input/*.txt` and `*.md`."""
    if not SCRIPTS_DIR.exists():
        return []
    stems: dict[str, Path] = {}
    for path in sorted(SCRIPTS_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}:
            stems.setdefault(path.stem, path)
    return sorted(stems.keys())


def stage_slide_inputs(
    slide_id: str,
    media_in: Path | None = None,
    en_text: str | None = None,
    fr_text: str | None = None,
) -> None:
    """Optionally copies provided slide media / scripts into `slides_input/` and `scripts_input/`."""
    if media_in is not None:
        src_path = media_in.resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Provided `--media-in` file does not exist: {src_path}")
        SLIDES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = src_path.suffix.lower()
        if suffix == ".mp4":
            dst = SLIDES_DIR / f"{slide_id}.mp4"
            if src_path != dst.resolve():
                shutil.copy2(src_path, dst)
        elif suffix == ".png":
            dst = SLIDES_DIR / f"{slide_id}.png"
            if src_path != dst.resolve():
                shutil.copy2(src_path, dst)
        elif suffix in {".jpg", ".jpeg", ".webp", ".bmp"}:
            dst = SLIDES_DIR / f"{slide_id}.png"
            with Image.open(src_path) as img:
                img.convert("RGB").save(dst, format="PNG")
        else:
            raise ValueError(
                f"Unsupported `--media-in` format '{src_path.suffix}'. Expected .mp4, .png, .jpg, or .webp."
            )

    if en_text is not None:
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        cleaned_en = " ".join(en_text.split())
        if not cleaned_en:
            raise ValueError("`--en` text cannot be empty.")
        lines = ["[EN]", cleaned_en]
        if fr_text is not None and fr_text.strip():
            lines.extend(["", "[FR]", " ".join(fr_text.split())])
        (SCRIPTS_DIR / f"{slide_id}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_slide(
    slide_id: str,
    with_video: bool = True,
    lead_in_sec: float = DEFAULT_LEAD_IN_SEC,
    export_dir: Path | None = DEFAULT_EXPORT_DIR,
    subtitle_y: float = DEFAULT_SUBTITLE_Y,
    subtitle_font_size: int = DEFAULT_SUBTITLE_FONT_SIZE,
) -> SlideVideoManifest:
    """Pairs an existing slide asset in `slides_input/` with narration audio & `[FR]` subtitles."""
    script_path = _resolve_script_path(slide_id)
    slide_png_candidate = SLIDES_DIR / f"{slide_id}.png"

    slide_media_path: Path | None = None
    slide_media_type = "none"
    if with_video:
        # Fail fast before TTS boot if no externally authored `.mp4` or `.png` slide exists.
        slide_media_path, slide_media_type = resolve_slide_media_path(SLIDES_DIR, slide_id)
    else:
        try:
            slide_media_path, slide_media_type = resolve_slide_media_path(SLIDES_DIR, slide_id)
        except FileNotFoundError:
            slide_media_path = None
            slide_media_type = "none"

    bilingual = parse_bilingual_script(script_path=script_path, slide_id=slide_id)

    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_wav_path = AUDIO_OUT_DIR / f"_tmp_{slide_id}_raw.wav"

    synthesize_en_voiceover(en_text=bilingual.en_text, raw_wav_out=raw_wav_path)
    master = master_slide_audio(
        slide_id=slide_id,
        raw_wav_path=raw_wav_path,
        audio_out_dir=AUDIO_OUT_DIR,
        remove_raw=True,
        lead_in_sec=lead_in_sec,
    )

    subtitle_chunks = build_fr_subtitle_chunks(
        fr_text=bilingual.fr_text,
        total_duration_sec=master.mastered_duration_sec,
        lead_in_sec=lead_in_sec,
    )

    rendered_mp4_path: str | None = None
    if with_video:
        assert slide_media_path is not None
        mp4_path = render_slide_video(
            slide_id=slide_id,
            slide_media_path=slide_media_path,
            master_wav_path=Path(master.master_wav_path),
            duration_sec=master.mastered_duration_sec,
            subtitle_chunks=subtitle_chunks,
            video_out_dir=VIDEO_OUT_DIR,
            subtitle_y=subtitle_y,
            subtitle_font_size=subtitle_font_size,
        )
        rendered_mp4_path = str(mp4_path.resolve())

    exported_mp4_path: str | None = None
    if with_video and rendered_mp4_path is not None and export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        target_mp4 = export_dir / f"{slide_id}.mp4"
        shutil.copy2(rendered_mp4_path, target_mp4)
        exported_mp4_path = str(target_mp4.resolve())

    zoom_start = STATIC_ZOOM_START if slide_media_type == "static_png" else 1.0
    zoom_end = STATIC_ZOOM_END if slide_media_type == "static_png" else 1.0

    manifest = SlideVideoManifest(
        generated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        slide_id=slide_id,
        script_path=bilingual.source_path,
        slide_png_path=str(slide_png_candidate.resolve()) if slide_png_candidate.exists() else "",
        en_word_count=bilingual.en_word_count,
        fr_subtitle_chunks=len(subtitle_chunks),
        audio_wav_path=master.master_wav_path,
        audio_mp3_path=master.master_mp3_path,
        video_mp4_path=rendered_mp4_path,
        duration_sec=master.mastered_duration_sec,
        atempo_factor=master.atempo_factor,
        target_lufs=master.target_lufs,
        mean_volume_db=master.mean_volume_db,
        max_volume_db=master.max_volume_db,
        resolution=f"{CANVAS_W}x{CANVAS_H}",
        fps=FPS,
        zoom_start=zoom_start,
        zoom_end=zoom_end,
        slide_media_path=str(slide_media_path.resolve()) if slide_media_path is not None else "",
        slide_media_type=slide_media_type,
        fr_auto_translated=bilingual.fr_auto_translated,
        lead_in_sec=lead_in_sec,
        exported_mp4_path=exported_mp4_path,
        subtitle_y=subtitle_y,
        subtitle_font_size=subtitle_font_size,
    )

    manifest_path = VIDEO_OUT_DIR / f"{slide_id}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI flags for single-slide or batch training narration runs."""
    parser = argparse.ArgumentParser(
        description="Bilingual English voiceover + French lower-third training slide narrator."
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--slide",
        type=str,
        help="Single slide identifier matching `scripts_input/<slide_id>.txt`.",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="Process every script present in `scripts_input/`.",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--with-video",
        action="store_true",
        help="Synthesize audio and render 1920x1080 MP4 video (default).",
    )
    mode_group.add_argument(
        "--audio-only",
        action="store_true",
        help="Synthesize EBU R128 mastered WAV + MP3 audio only without MP4 rendering.",
    )
    parser.add_argument(
        "--media-in",
        type=Path,
        default=None,
        help="Optional external slide asset (.mp4 or .png/.jpg) to stage into `slides_input/<slide_id>`.",
    )
    parser.add_argument(
        "--en",
        type=str,
        default=None,
        help="Optional inline `[EN]` narration script to write to `scripts_input/<slide_id>.txt`.",
    )
    parser.add_argument(
        "--fr",
        type=str,
        default=None,
        help="Optional inline `[FR]` subtitle text (when omitted alongside `--en`, Ollama auto-translates).",
    )
    parser.add_argument(
        "--lead-in-sec",
        type=float,
        default=DEFAULT_LEAD_IN_SEC,
        help="Silent voice pre-roll duration in seconds (default: 1.5s for PowerPoint playback).",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default=str(DEFAULT_EXPORT_DIR),
        help="Destination directory for final PowerPoint MP4 only (default: OneDrive folder). Pass 'none' to disable.",
    )
    parser.add_argument(
        "--subtitle-y",
        type=float,
        default=DEFAULT_SUBTITLE_Y,
        help="Vertical subtitle position (fraction 0.0-1.0 of 1080p height or pixel coordinate, default: 0.65).",
    )
    parser.add_argument(
        "--subtitle-font-size",
        type=int,
        default=DEFAULT_SUBTITLE_FONT_SIZE,
        help="French subtitle font size in pixels (default: 46 for briefing room readability).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `python -m src.narrator_cli`."""
    args = parse_args(argv)
    with_video = not args.audio_only

    export_dir_str = (args.export_dir or "").strip()
    export_dir = (
        None
        if export_dir_str.lower() in {"none", "false", "null", "no", ""}
        else Path(export_dir_str)
    )

    if args.all and (args.media_in is not None or args.en is not None or args.fr is not None):
        print("Error: `--media-in`, `--en`, and `--fr` require `--slide <slide_id>`.", file=sys.stderr)
        return 2
    if args.fr is not None and args.en is None:
        print("Error: `--fr` inline override requires `--en`.", file=sys.stderr)
        return 2

    if args.slide is not None:
        slide_id = args.slide.strip()
        stage_slide_inputs(
            slide_id=slide_id,
            media_in=args.media_in,
            en_text=args.en,
            fr_text=args.fr,
        )
        slide_ids = [slide_id]
    else:
        slide_ids = _discover_all_slide_ids()

    if not slide_ids:
        print(f"No narration scripts found in {SCRIPTS_DIR}", file=sys.stderr)
        return 1

    manifests: list[dict[str, object]] = []
    for slide_id in slide_ids:
        manifest = process_slide(
            slide_id=slide_id,
            with_video=with_video,
            lead_in_sec=args.lead_in_sec,
            export_dir=export_dir,
            subtitle_y=args.subtitle_y,
            subtitle_font_size=args.subtitle_font_size,
        )
        manifests.append(manifest.to_dict())

    print(json.dumps(manifests if len(manifests) > 1 else manifests[0], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

