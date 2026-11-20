"""16:9 1920x1080 slide compositor with slow zoom drift and French lower-third subtitles."""

from __future__ import annotations

import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont

from src.audio_master import resolve_ffmpeg_tool
from src.models import SubtitleChunk

CANVAS_W = 1920
CANVAS_H = 1080
FPS = 30
ZOOM_START = 1.00
ZOOM_END = 1.03

FONT_DIR = Path(r"C:\Anti-Gravity-Core\pierre-training-video\video_studio\resource\fonts")
FONT_BOLD = FONT_DIR / "BeVietnamPro-Bold.ttf"
FONT_MEDIUM = FONT_DIR / "BeVietnamPro-Medium.ttf"

SLATE_BG_RGB = (8, 16, 28)
PILL_BG_RGBA = (8, 16, 28, 232)
PILL_BORDER_RGBA = (0, 229, 255, 210)
BADGE_FILL_RGBA = (0, 229, 255, 38)
CYAN_ACCENT_RGB = (0, 229, 255)
TRACK_BG_RGB = (22, 34, 52)
TEXT_WHITE_RGBA = (248, 250, 252, 255)


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


def _prepare_base_slide(slide_png_path: Path) -> Image.Image:
    """Loads source slide PNG and fits/pads cleanly into 1920x1080 RGB canvas."""
    if not slide_png_path.exists():
        raise FileNotFoundError(f"Slide image missing: {slide_png_path}")

    with Image.open(slide_png_path) as src:
        rgba = src.convert("RGBA")

    if rgba.size == (CANVAS_W, CANVAS_H):
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), SLATE_BG_RGB)
        canvas.paste(rgba, (0, 0), rgba)
        return canvas

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
    max_width_px: int,
    max_lines: int = 2,
) -> list[str]:
    """Wraps subtitle text cleanly into balanced lines constrained by rendered pixel width."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip() if current else word
        if current and font.getlength(trial) > max_width_px:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return lines

    # Merge overflow into final line if needed while trimming cleanly with ellipsis
    kept = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :])
    while font.getlength(f"{tail}...") > max_width_px and " " in tail:
        tail = tail.rsplit(" ", 1)[0]
    if font.getlength(tail) > max_width_px and len(tail) > 4:
        tail = f"{tail[:48].rstrip()}..."
    kept.append(tail)
    return kept


def _build_subtitle_pill(
    chunk: SubtitleChunk,
    text_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    badge_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[Image.Image, int, int]:
    """Renders a compact RGBA rounded lower-third pill for one `SubtitleChunk`."""
    badge_w = 52
    badge_h = 34
    badge_gap = 20
    pad_x = 34
    pad_y = 20
    max_text_w = 1480

    lines = _wrap_text_to_width(chunk.text, text_font, max_width_px=max_text_w, max_lines=2)
    if not lines:
        lines = [chunk.text]

    line_widths = [int(math.ceil(text_font.getlength(line))) for line in lines]
    content_text_w = max(line_widths, default=200)
    line_height = 40
    total_text_h = len(lines) * line_height

    pill_w = min(1740, max(540, pad_x * 2 + badge_w + badge_gap + content_text_w))
    pill_h = max(78, pad_y * 2 + total_text_h)

    pill = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pill)

    draw.rounded_rectangle(
        (0, 0, pill_w - 1, pill_h - 1),
        radius=18,
        fill=PILL_BG_RGBA,
        outline=PILL_BORDER_RGBA,
        width=2,
    )

    badge_x = pad_x
    badge_y = (pill_h - badge_h) // 2
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=8,
        fill=BADGE_FILL_RGBA,
        outline=PILL_BORDER_RGBA,
        width=2,
    )
    fr_w = badge_font.getlength("FR")
    draw.text(
        (badge_x + (badge_w - fr_w) / 2.0, badge_y + 5),
        "FR",
        font=badge_font,
        fill=CYAN_ACCENT_RGB + (255,),
    )

    text_start_x = badge_x + badge_w + badge_gap
    text_start_y = (pill_h - total_text_h) / 2.0 - 2
    for idx, line in enumerate(lines):
        draw.text(
            (text_start_x, text_start_y + idx * line_height),
            line,
            font=text_font,
            fill=TEXT_WHITE_RGBA,
        )

    pos_x = (CANVAS_W - pill_w) // 2
    pos_y = CANVAS_H - 42 - pill_h
    return pill, pos_x, pos_y


def _find_active_chunk(chunks: list[SubtitleChunk], timestamp_sec: float) -> SubtitleChunk | None:
    """Returns the subtitle card covering `timestamp_sec`, or None if outside intervals."""
    if not chunks:
        return None
    for chunk in chunks:
        if chunk.start_sec <= timestamp_sec < chunk.end_sec:
            return chunk
    return chunks[-1] if timestamp_sec >= chunks[-1].start_sec else None


def render_slide_video(
    slide_id: str,
    slide_png_path: Path,
    master_wav_path: Path,
    duration_sec: float,
    subtitle_chunks: list[SubtitleChunk],
    video_out_dir: Path,
) -> Path:
    """Renders 1920x1080 30fps H.264/AAC MP4 with continuous zoom drift & `[FR]` lower-thirds."""
    if duration_sec <= 0.0:
        raise ValueError(f"Invalid video duration {duration_sec}s for slide '{slide_id}'")
    if not master_wav_path.exists():
        raise FileNotFoundError(f"Mastered audio WAV missing: {master_wav_path}")

    ffmpeg_bin = resolve_ffmpeg_tool("ffmpeg")
    video_out_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = video_out_dir / f"{slide_id}.mp4"

    base_slide = _prepare_base_slide(slide_png_path)
    text_font = _load_font(bold=True, size=28)
    badge_font = _load_font(bold=True, size=20)

    pill_cache: dict[int, tuple[Image.Image, int, int]] = {}
    for chunk in subtitle_chunks:
        pill_cache[chunk.index] = _build_subtitle_pill(chunk, text_font, badge_font)

    total_frames = max(1, int(math.ceil(duration_sec * FPS)))

    cmd = [
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
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
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

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None

    try:
        for frame_idx in range(total_frames):
            progress = frame_idx / max(1, total_frames - 1)
            zoom = ZOOM_START + (ZOOM_END - ZOOM_START) * progress

            crop_w = CANVAS_W / zoom
            crop_h = CANVAS_H / zoom
            left = (CANVAS_W - crop_w) / 2.0
            top = (CANVAS_H - crop_h) / 2.0
            right = left + crop_w
            bottom = top + crop_h

            frame = base_slide.resize(
                (CANVAS_W, CANVAS_H),
                resample=Image.Resampling.BILINEAR,
                box=(left, top, right, bottom),
            )

            timestamp_sec = frame_idx / FPS
            active_chunk = _find_active_chunk(subtitle_chunks, timestamp_sec)
            if active_chunk is not None:
                pill_img, px, py = pill_cache[active_chunk.index]
                frame.paste(pill_img, (px, py), pill_img)

            draw = ImageDraw.Draw(frame)
            draw.rectangle((0, CANVAS_H - 4, CANVAS_W, CANVAS_H), fill=TRACK_BG_RGB)
            bar_w = max(1, int(round(CANVAS_W * progress)))
            draw.rectangle((0, CANVAS_H - 4, bar_w, CANVAS_H), fill=CYAN_ACCENT_RGB)

            proc.stdin.write(frame.tobytes())
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass

    stderr_bytes = proc.stderr.read() if proc.stderr is not None else b""
    rc = proc.wait(timeout=180)
    if rc != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg video encode failed (rc={rc}):\n{stderr_text}")

    if not output_mp4.exists() or output_mp4.stat().st_size == 0:
        raise RuntimeError(f"Rendered MP4 missing or empty: {output_mp4}")

    return output_mp4

