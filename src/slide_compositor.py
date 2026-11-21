"""16:9 1920x1080 slide compositor for Veo `.mp4` animations, static `.png` zooms, and French subtitles."""

from __future__ import annotations

import math
from pathlib import Path
import subprocess
from typing import IO

from PIL import Image, ImageDraw, ImageFont

from src.audio_master import resolve_ffmpeg_tool
from src.models import SubtitleChunk

CANVAS_W = 1920
CANVAS_H = 1080
FPS = 30
STATIC_ZOOM_START = 1.00
STATIC_ZOOM_END = 1.03
FRAME_BYTE_SIZE = CANVAS_W * CANVAS_H * 3

ANIMATED_EXTENSIONS = {".mp4", ".mov", ".webm"}

FONT_DIR = Path(r"C:\Anti-Gravity-Core\pierre-training-video\video_studio\resource\fonts")
FONT_BOLD = FONT_DIR / "BeVietnamPro-Bold.ttf"
FONT_MEDIUM = FONT_DIR / "BeVietnamPro-Medium.ttf"

SLATE_BG_RGB = (5, 10, 18)
PILL_BG_RGBA = (8, 16, 28, 230)
PILL_BORDER_RGBA = (56, 189, 248, 180)
CYAN_ACCENT_RGB = (0, 229, 255)
TRACK_BG_RGB = (22, 34, 52)
TEXT_WHITE_RGBA = (255, 255, 255, 255)

DEFAULT_SUBTITLE_Y = 0.91
DEFAULT_SUBTITLE_FONT_SIZE = 46
AVATAR_OVERLAY_W = 170
AVATAR_OVERLAY_H = 170
AVATAR_RIGHT_INSET_PCT = 0.10
AVATAR_TOP_INSET_PCT = 0.11


def resolve_slide_media_path(slides_dir: Path, slide_id: str) -> tuple[Path, str]:
    """Prefers animated `.mp4` slide clips (e.g., Gemini Veo) with `.png` static fallback."""
    mp4_candidate = slides_dir / f"{slide_id}.mp4"
    if mp4_candidate.exists():
        return mp4_candidate, "animated_mp4"

    png_candidate = slides_dir / f"{slide_id}.png"
    if png_candidate.exists():
        return png_candidate, "static_png"

    raise FileNotFoundError(
        f"Missing slide media for '{slide_id}': place an animated clip at "
        f"{mp4_candidate} or a static slide at {png_candidate}"
    )


def _load_font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads BeVietnamPro (read-only) with clean Windows/Pillow fallbacks."""
    candidates = (
        [FONT_BOLD, Path(r"C:\Windows\Fonts\arialbd.ttf")]
        if bold
        else [FONT_MEDIUM, Path(r"C:\Windows\Fonts\arial.ttf")]
    )
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _compute_slide_canvas_rect(media_path: Path, is_animated: bool) -> tuple[int, int, int, int]:
    """Computes the active `(slide_x, slide_y, slide_w, slide_h)` fitted inside 1920x1080."""
    src_w, src_h = CANVAS_W, CANVAS_H
    if is_animated:
        ffprobe_bin = resolve_ffmpeg_tool("ffprobe")
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and "x" in proc.stdout:
            try:
                w_str, h_str = proc.stdout.strip().splitlines()[0].split("x", 1)
                src_w, src_h = max(1, int(w_str)), max(1, int(h_str))
            except ValueError:
                pass
    else:
        with Image.open(media_path) as src:
            src_w, src_h = src.size

    scale = min(CANVAS_W / src_w, CANVAS_H / src_h)
    slide_w = max(1, int(round(src_w * scale)))
    slide_h = max(1, int(round(src_h * scale)))
    slide_x = (CANVAS_W - slide_w) // 2
    slide_y = (CANVAS_H - slide_h) // 2
    return slide_x, slide_y, slide_w, slide_h


def _prepare_base_slide(slide_png_path: Path) -> Image.Image:
    """Loads source static slide PNG and fits/pads proportionally into 1920x1080 canvas."""
    if not slide_png_path.exists():
        raise FileNotFoundError(f"Slide image missing: {slide_png_path}")

    with Image.open(slide_png_path) as src:
        rgba = src.convert("RGBA")

    scale = min(CANVAS_W / rgba.width, CANVAS_H / rgba.height)
    new_w = max(1, int(round(rgba.width * scale)))
    new_h = max(1, int(round(rgba.height * scale)))
    resized = rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), SLATE_BG_RGB)
    offset_x = (CANVAS_W - new_w) // 2
    offset_y = (CANVAS_H - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y), resized)
    return canvas


def _wrap_text_to_width(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width_px: int = 1600,
    max_chars_per_line: int = 52,
    max_lines: int = 2,
) -> list[str]:
    """Wraps subtitle text cleanly into balanced lines constrained by pixel width and char count."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip() if current else word
        if current and (font.getlength(trial) > max_width_px or len(trial) > max_chars_per_line):
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return lines

    kept = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :])
    while (font.getlength(f"{tail}...") > max_width_px or len(tail) > max_chars_per_line) and " " in tail:
        tail = tail.rsplit(" ", 1)[0]
    if (font.getlength(tail) > max_width_px or len(tail) > max_chars_per_line) and len(tail) > 4:
        safe_cut = min(len(tail), max_chars_per_line - 4)
        tail = f"{tail[:safe_cut].rstrip()}..."
    kept.append(tail)
    return kept


def _build_subtitle_pill(
    chunk: SubtitleChunk,
    text_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    subtitle_y: float = DEFAULT_SUBTITLE_Y,
    font_size: int = DEFAULT_SUBTITLE_FONT_SIZE,
) -> tuple[Image.Image, int, int]:
    """Renders a raised high-contrast French subtitle pill without FR badge."""
    pad_x = 42
    pad_y = 16
    max_text_w = 1600
    max_chars_per_line = 52

    lines = _wrap_text_to_width(
        chunk.text,
        text_font,
        max_width_px=max_text_w,
        max_chars_per_line=max_chars_per_line,
        max_lines=2,
    )
    if not lines:
        lines = [chunk.text]

    line_widths = [int(math.ceil(text_font.getlength(line))) for line in lines]
    content_text_w = max(line_widths, default=200)
    line_height = int(round(font_size * 1.25))
    total_text_h = len(lines) * line_height

    pill_w = min(1760, max(560, pad_x * 2 + content_text_w))
    pill_h = max(60, pad_y * 2 + total_text_h)

    pill = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pill)

    draw.rounded_rectangle(
        (0, 0, pill_w - 1, pill_h - 1),
        radius=16,
        fill=PILL_BG_RGBA,
        outline=PILL_BORDER_RGBA,
        width=2,
    )

    text_start_y = (pill_h - total_text_h) / 2.0 - 2
    for idx, line in enumerate(lines):
        line_w = text_font.getlength(line)
        line_x = (pill_w - line_w) / 2.0
        draw.text(
            (line_x, text_start_y + idx * line_height),
            line,
            font=text_font,
            fill=TEXT_WHITE_RGBA,
        )

    pos_x = (CANVAS_W - pill_w) // 2
    if 0.0 < subtitle_y <= 1.0:
        pos_y = int(round(CANVAS_H * subtitle_y - pill_h / 2.0))
    else:
        pos_y = int(round(subtitle_y))
    pos_y = max(10, min(CANVAS_H - pill_h - 10, pos_y))
    return pill, pos_x, pos_y


def _find_active_chunk(chunks: list[SubtitleChunk], timestamp_sec: float) -> SubtitleChunk | None:
    """Returns the subtitle card covering `timestamp_sec`, or None if outside intervals."""
    if not chunks:
        return None
    for chunk in chunks:
        if chunk.start_sec <= timestamp_sec < chunk.end_sec:
            return chunk
    return None


def _read_exact_frame(stream: IO[bytes], byte_count: int) -> bytes:
    """Reads an exact raw RGB frame from a pipe across partial Windows pipe chunks."""
    chunks: list[bytes] = []
    remaining = byte_count
    while remaining > 0:
        part = stream.read(remaining)
        if not part:
            break
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


def _overlay_subtitles_and_bar(
    frame: Image.Image,
    frame_idx: int,
    total_frames: int,
    subtitle_chunks: list[SubtitleChunk],
    pill_cache: dict[int, tuple[Image.Image, int, int]],
) -> Image.Image:
    """Composites active French subtitle strip and thin 4px progress bar onto a 1080p frame."""
    timestamp_sec = frame_idx / FPS
    active_chunk = _find_active_chunk(subtitle_chunks, timestamp_sec)
    if active_chunk is not None:
        pill_img, px, py = pill_cache[active_chunk.index]
        frame.paste(pill_img, (px, py), pill_img)

    progress = frame_idx / max(1, total_frames - 1)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, CANVAS_H - 4, CANVAS_W, CANVAS_H), fill=TRACK_BG_RGB)
    bar_w = max(1, int(round(CANVAS_W * progress)))
    draw.rectangle((0, CANVAS_H - 4, bar_w, CANVAS_H), fill=CYAN_ACCENT_RGB)
    return frame


def render_slide_video(
    slide_id: str,
    master_wav_path: Path,
    duration_sec: float,
    subtitle_chunks: list[SubtitleChunk],
    video_out_dir: Path,
    slide_media_path: Path | None = None,
    slide_png_path: Path | None = None,
    subtitle_y: float = DEFAULT_SUBTITLE_Y,
    subtitle_font_size: int = DEFAULT_SUBTITLE_FONT_SIZE,
    avatar_mp4_path: Path | None = None,
    avatar_matte_path: Path | None = None,
    lead_in_sec: float = 1.5,
    tail_out_sec: float = 1.5,
) -> Path:
    """Renders 1920x1080 30fps H.264/AAC MP4 with optional speech-windowed avatar overlay."""
    resolved_media = slide_media_path or slide_png_path
    if resolved_media is None:
        raise ValueError("Either `slide_media_path` or `slide_png_path` must be supplied.")
    if not resolved_media.exists():
        raise FileNotFoundError(f"Slide media missing: {resolved_media}")
    if duration_sec <= 0.0:
        raise ValueError(f"Invalid video duration {duration_sec}s for slide '{slide_id}'")
    if not master_wav_path.exists():
        raise FileNotFoundError(f"Mastered audio WAV missing: {master_wav_path}")

    ffmpeg_bin = resolve_ffmpeg_tool("ffmpeg")
    video_out_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = video_out_dir / f"{slide_id}.mp4"

    text_font = _load_font(bold=True, size=subtitle_font_size)
    pill_cache: dict[int, tuple[Image.Image, int, int]] = {
        chunk.index: _build_subtitle_pill(
            chunk,
            text_font,
            subtitle_y=subtitle_y,
            font_size=subtitle_font_size,
        )
        for chunk in subtitle_chunks
    }

    total_frames = max(1, int(math.ceil(duration_sec * FPS)))
    is_animated = resolved_media.suffix.lower() in ANIMATED_EXTENSIONS

    use_avatar = (
        avatar_mp4_path is not None
        and avatar_matte_path is not None
        and avatar_mp4_path.exists()
        and avatar_matte_path.exists()
    )

    enc_cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{CANVAS_W}x{CANVAS_H}",
        "-pix_fmt",
        "rgb24",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-i",
        str(master_wav_path),
    ]

    if use_avatar:
        assert avatar_mp4_path is not None and avatar_matte_path is not None
        slide_x, slide_y, slide_w, slide_h = _compute_slide_canvas_rect(resolved_media, is_animated)
        overlay_w, overlay_h = AVATAR_OVERLAY_W, AVATAR_OVERLAY_H
        right_inset = int(round(slide_w * AVATAR_RIGHT_INSET_PCT))
        top_inset = int(round(slide_h * AVATAR_TOP_INSET_PCT))
        avatar_x = slide_x + slide_w - overlay_w - right_inset
        avatar_y = slide_y + top_inset
        print(
            f"[SlideCompositor] slide_canvas=({slide_x}, {slide_y}, {slide_w}, {slide_h}) "
            f"avatar_overlay=(x={avatar_x}, y={avatar_y}) size=({overlay_w}, {overlay_h})",
            flush=True,
        )

        speech_end_sec = max(lead_in_sec + 0.5, duration_sec - max(0.0, tail_out_sec))
        fade_out_st = max(lead_in_sec, speech_end_sec - 0.20)
        filter_complex = (
            f"[2:v]crop=ih:ih:(iw-ih)/2:0,scale={overlay_w}:{overlay_h},fps={FPS},format=rgba[av];"
            f"[3:v]crop=ih:ih:(iw-ih)/2:0,scale={overlay_w}:{overlay_h},fps={FPS},format=gray[mt];"
            f"[av][mt]alphamerge,format=yuva420p,"
            f"fade=t=in:st={lead_in_sec:.3f}:d=0.20:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d=0.20:alpha=1[fg];"
            f"[0:v][fg]overlay=x={avatar_x}:y={avatar_y}:shortest=1:format=auto[vout]"
        )
        enc_cmd.extend(
            [
                "-i",
                str(avatar_mp4_path),
                "-stream_loop",
                "-1",
                "-i",
                str(avatar_matte_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "1:a",
            ]
        )

    enc_cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_mp4),
        ]
    )

    enc_proc = subprocess.Popen(
        enc_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert enc_proc.stdin is not None

    dec_proc: subprocess.Popen[bytes] | None = None
    try:
        if is_animated:
            dec_vf = (
                f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,"
                f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:color=#050a12,"
                f"fps={FPS}"
            )
            dec_cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-stream_loop",
                "-1",
                "-i",
                str(resolved_media),
                "-t",
                f"{duration_sec + 0.5:.3f}",
                "-vf",
                dec_vf,
                "-an",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ]
            dec_proc = subprocess.Popen(
                dec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert dec_proc.stdout is not None

            last_frame: Image.Image | None = None
            for frame_idx in range(total_frames):
                raw_bytes = _read_exact_frame(dec_proc.stdout, FRAME_BYTE_SIZE)
                if len(raw_bytes) == FRAME_BYTE_SIZE:
                    frame = Image.frombytes("RGB", (CANVAS_W, CANVAS_H), raw_bytes)
                    last_frame = frame.copy()
                elif last_frame is not None:
                    frame = last_frame.copy()
                else:
                    dec_err = (
                        dec_proc.stderr.read().decode("utf-8", errors="replace").strip()
                        if dec_proc.stderr is not None
                        else ""
                    )
                    raise RuntimeError(
                        f"Failed to decode frames from animated slide {resolved_media}: {dec_err}"
                    )

                composed = _overlay_subtitles_and_bar(
                    frame, frame_idx, total_frames, subtitle_chunks, pill_cache
                )
                enc_proc.stdin.write(composed.tobytes())
        else:
            base_slide = _prepare_base_slide(resolved_media)
            for frame_idx in range(total_frames):
                progress = frame_idx / max(1, total_frames - 1)
                zoom = STATIC_ZOOM_START + (STATIC_ZOOM_END - STATIC_ZOOM_START) * progress

                crop_w = CANVAS_W / zoom
                crop_h = CANVAS_H / zoom
                left = (CANVAS_W - crop_w) / 2.0
                top = (CANVAS_H - crop_h) / 2.0
                right = left + crop_w
                bottom = top + crop_h

                viewport = base_slide.resize(
                    (CANVAS_W, CANVAS_H),
                    resample=Image.Resampling.BILINEAR,
                    box=(left, top, right, bottom),
                )
                composed = _overlay_subtitles_and_bar(
                    viewport, frame_idx, total_frames, subtitle_chunks, pill_cache
                )
                enc_proc.stdin.write(composed.tobytes())
    finally:
        if dec_proc is not None:
            for stream_obj in (dec_proc.stdout, dec_proc.stderr):
                if stream_obj is not None:
                    try:
                        stream_obj.close()
                    except OSError:
                        pass
            if dec_proc.poll() is None:
                try:
                    dec_proc.terminate()
                    dec_proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        dec_proc.kill()
                    except OSError:
                        pass
        try:
            enc_proc.stdin.close()
        except OSError:
            pass

    stderr_bytes = enc_proc.stderr.read() if enc_proc.stderr is not None else b""
    rc = enc_proc.wait(timeout=180)
    if rc != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg video encode failed (rc={rc}):\n{stderr_text}")

    if not output_mp4.exists() or output_mp4.stat().st_size == 0:
        raise RuntimeError(f"Rendered MP4 missing or empty: {output_mp4}")

    return output_mp4
