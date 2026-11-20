"""Dark tactical CAF / MWO Rouleau presentation slide generator (`.png` + animated `.mp4`)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont

from src.audio_master import resolve_ffmpeg_tool

CANVAS_W = 1920
CANVAS_H = 1080
FPS = 30

STUDIO_ROOT = Path(__file__).resolve().parents[1]
SLIDES_DIR = STUDIO_ROOT / "slides_input"
FONT_DIR = Path(r"C:\Anti-Gravity-Core\pierre-training-video\video_studio\resource\fonts")

BACKDROP_RGB = (7, 14, 26)
GRID_RGB = (18, 34, 56)
CARD_BG_RGB = (13, 23, 39)
CARD_BORDER_RGB = (36, 58, 92)
TEXT_LIGHT = (241, 245, 249)
TEXT_MUTED = (148, 163, 184)
FOOTER_SLATE = (115, 134, 158)

CYAN = (0, 229, 255)
EMERALD = (34, 197, 94)
AMBER = (245, 158, 11)


@dataclass(slots=True, frozen=True)
class BranchPanelSpec:
    """Immutable CAF branch capability panel and diverse personnel badge definition."""

    card_x: int
    accent: tuple[int, int, int]
    branch_code: str
    branch_title: str
    personnel_label: str
    role_label: str
    skin_tone: tuple[int, int, int]
    hair_tone: tuple[int, int, int]
    beret_or_cap: tuple[int, int, int]
    readiness_label: str
    readiness_pct: float
    bullets: tuple[str, ...]


DEFAULT_CAF_PANELS: tuple[BranchPanelSpec, ...] = (
    BranchPanelSpec(
        card_x=88,
        accent=CYAN,
        branch_code="RCN // MARITIME",
        branch_title="Royal Canadian Navy",
        personnel_label="Lt(N) A. Chen",
        role_label="Maritime Surface Officer",
        skin_tone=(214, 173, 140),
        hair_tone=(28, 30, 38),
        beret_or_cap=(20, 36, 66),
        readiness_label="MARITIME C4ISR SYNC",
        readiness_pct=0.94,
        bullets=(
            "• Surface & subsurface acoustic sensor fusion",
            "• Fleet tactical datalink resiliency drills",
            "• Maritime interdiction & escort readiness",
        ),
    ),
    BranchPanelSpec(
        card_x=682,
        accent=EMERALD,
        branch_code="CA // LAND FORCES",
        branch_title="Canadian Army",
        personnel_label="MWO M. Jean-Baptiste",
        role_label="Joint Readiness NCO",
        skin_tone=(132, 86, 58),
        hair_tone=(22, 22, 26),
        beret_or_cap=(26, 76, 46),
        readiness_label="BRIGADE FIELD COMMS",
        readiness_pct=0.97,
        bullets=(
            "• Mechanized brigade austere logistics sync",
            "• Encrypted tactical VHF/SATCOM failover",
            "• Cold-weather joint engineering mobility",
        ),
    ),
    BranchPanelSpec(
        card_x=1276,
        accent=AMBER,
        branch_code="RCAF // AEROSPACE",
        branch_title="Royal Canadian Air Force",
        personnel_label="Capt S. Desjarlais",
        role_label="Aerospace Control Officer",
        skin_tone=(188, 138, 102),
        hair_tone=(38, 26, 20),
        beret_or_cap=(30, 56, 98),
        readiness_label="AEROSPACE C2 TELEMETRY",
        readiness_pct=0.96,
        bullets=(
            "• NORAD sector track correlation & intercept",
            "• Rapid tactical airlift & AAR scheduling",
            "• ISR multi-domain telemetry dissemination",
        ),
    ),
)


def _load_font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [FONT_DIR / "BeVietnamPro-Bold.ttf", Path(r"C:\Windows\Fonts\arialbd.ttf")]
        if bold
        else [FONT_DIR / "BeVietnamPro-Medium.ttf", Path(r"C:\Windows\Fonts\arial.ttf")]
    )
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_hud_brackets(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int, accent: tuple[int, int, int]) -> None:
    """Draws tactical corner brackets around panel bounds."""
    arm = 18
    for cx, cy, dx, dy in (
        (x1, y1, 1, 1),
        (x2, y1, -1, 1),
        (x1, y2, 1, -1),
        (x2, y2, -1, -1),
    ):
        draw.line([(cx, cy), (cx + arm * dx, cy)], fill=accent, width=3)
        draw.line([(cx, cy), (cx, cy + arm * dy)], fill=accent, width=3)


def _draw_personnel_medallion(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    panel: BranchPanelSpec,
) -> None:
    """Draws a crisp stylized uniform medallion representing diverse CAF personnel."""
    r = 34
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(18, 30, 50), outline=panel.accent, width=2)
    # Shoulders / uniform collar
    draw.chord((cx - 24, cy + 8, cx + 24, cy + 44), start=180, end=360, fill=panel.beret_or_cap)
    # Head silhouette
    draw.ellipse((cx - 12, cy - 18, cx + 12, cy + 6), fill=panel.skin_tone)
    # Hair & tactical service cap / beret arc
    draw.chord((cx - 13, cy - 22, cx + 13, cy - 4), start=175, end=5, fill=panel.beret_or_cap)


def generate_tactical_caf_png(
    out_png: Path,
    title: str = "Joint Command Telemetry & Force Synchronization",
    subtitle: str = "Integrated Navy, Army & Air Force Readiness  •  Bilingual Field Briefing",
) -> Path:
    """Generates a static 1920x1080 dark tactical CAF briefing slide PNG."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BACKDROP_RGB)
    draw = ImageDraw.Draw(img)

    for x in range(0, CANVAS_W, 64):
        draw.line([(x, 0), (x, CANVAS_H)], fill=GRID_RGB, width=1)
    for y in range(0, CANVAS_H, 64):
        draw.line([(0, y), (CANVAS_W, y)], fill=GRID_RGB, width=1)

    _draw_hud_brackets(draw, 44, 36, CANVAS_W - 44, CANVAS_H - 36, (30, 58, 92))

    f_tag = _load_font(bold=True, size=20)
    f_title = _load_font(bold=True, size=48)
    f_sub = _load_font(bold=False, size=24)
    f_branch = _load_font(bold=True, size=31)
    f_person = _load_font(bold=True, size=22)
    f_role = _load_font(bold=False, size=19)
    f_body = _load_font(bold=False, size=20)
    f_footer = _load_font(bold=False, size=21)

    header_badge = "CANADIAN ARMED FORCES  //  JOINT OPERATIONS BRIEFING"
    badge_right = int(88 + f_tag.getlength(header_badge) + 44)
    draw.rounded_rectangle(
        (88, 60, badge_right, 106),
        radius=10,
        fill=(12, 34, 56),
        outline=CYAN,
        width=2,
    )
    draw.text((110, 71), header_badge, font=f_tag, fill=CYAN)

    draw.text((88, 128), title, font=f_title, fill=TEXT_LIGHT)
    draw.text((88, 194), subtitle, font=f_sub, fill=TEXT_MUTED)

    card_w = 556
    card_y1 = 266
    card_y2 = 796

    for panel in DEFAULT_CAF_PANELS:
        x1 = panel.card_x
        x2 = x1 + card_w
        draw.rounded_rectangle(
            (x1, card_y1, x2, card_y2),
            radius=18,
            fill=CARD_BG_RGB,
            outline=CARD_BORDER_RGB,
            width=2,
        )
        draw.rounded_rectangle((x1, card_y1, x2, card_y1 + 7), radius=4, fill=panel.accent)
        _draw_hud_brackets(draw, x1, card_y1, x2, card_y2, panel.accent)

        draw.text((x1 + 32, card_y1 + 28), panel.branch_code, font=f_tag, fill=panel.accent)
        draw.text((x1 + 32, card_y1 + 62), panel.branch_title, font=f_branch, fill=TEXT_LIGHT)

        # Personnel medallion card strip
        med_y1 = card_y1 + 118
        med_y2 = card_y1 + 206
        draw.rounded_rectangle(
            (x1 + 28, med_y1, x2 - 28, med_y2),
            radius=12,
            fill=(16, 29, 49),
            outline=(38, 59, 88),
            width=1,
        )
        _draw_personnel_medallion(draw, x1 + 76, (med_y1 + med_y2) // 2, panel)
        draw.text((x1 + 126, med_y1 + 16), panel.personnel_label, font=f_person, fill=TEXT_LIGHT)
        draw.text((x1 + 126, med_y1 + 48), panel.role_label, font=f_role, fill=TEXT_MUTED)

        # Bullets
        by = card_y1 + 236
        for bullet in panel.bullets:
            draw.text((x1 + 32, by), bullet, font=f_body, fill=TEXT_MUTED)
            by += 54

        # Readiness metric baseline bar
        bar_x1 = x1 + 32
        bar_x2 = x2 - 32
        bar_y = card_y2 - 58
        draw.text((bar_x1, bar_y - 30), f"{panel.readiness_label}  {int(panel.readiness_pct * 100)}%", font=f_role, fill=panel.accent)
        draw.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + 14), radius=7, fill=(24, 38, 60))
        fill_w = int((bar_x2 - bar_x1) * panel.readiness_pct)
        draw.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + 14), radius=7, fill=panel.accent)

    draw.text(
        (88, 832),
        "Created by MWO Rouleau  |  CAF Joint Digital Readiness Training",
        font=f_footer,
        fill=FOOTER_SLATE,
    )

    img.save(out_png, format="PNG")
    return out_png


def generate_tactical_caf_animated_mp4(
    out_mp4: Path,
    base_png: Path,
    loop_duration_sec: float = 6.0,
) -> Path:
    """Renders a 1920x1080 30fps animated tactical motion clip suitable for compositor input."""
    if not base_png.exists():
        generate_tactical_caf_png(base_png)

    ffmpeg_bin = resolve_ffmpeg_tool("ffmpeg")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(base_png) as src:
        base_img = src.convert("RGB")
    if base_img.size != (CANVAS_W, CANVAS_H):
        base_img = base_img.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)

    total_frames = max(1, int(round(loop_duration_sec * FPS)))

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
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None

    try:
        card_w = 556
        card_y2 = 796
        for idx in range(total_frames):
            phase = (idx / total_frames) * 2.0 * math.pi
            frame = base_img.copy()
            draw = ImageDraw.Draw(frame, "RGBA")

            # Subtle horizontal radar/telemetry sweep across background band
            sweep_x = int((idx / total_frames) * CANVAS_W)
            draw.line([(sweep_x, 36), (sweep_x, CANVAS_H - 36)], fill=(0, 229, 255, 42), width=3)

            # Pulsing readiness indicator beacon on each branch panel
            pulse = 0.5 + 0.5 * math.sin(phase)
            beacon_alpha = int(120 + 135 * pulse)
            for p_idx, panel in enumerate(DEFAULT_CAF_PANELS):
                bx = panel.card_x + card_w - 44
                by = 266 + 40
                local_pulse = 0.5 + 0.5 * math.sin(phase + p_idx * 1.1)
                r_outer = 9 + int(4 * local_pulse)
                draw.ellipse(
                    (bx - r_outer, by - r_outer, bx + r_outer, by + r_outer),
                    outline=panel.accent + (int(80 + 90 * local_pulse),),
                    width=2,
                )
                draw.ellipse((bx - 5, by - 5, bx + 5, by + 5), fill=panel.accent + (beacon_alpha,))

                # Subtle animated shimmer along readiness meter bar
                bar_x1 = panel.card_x + 32
                bar_x2 = panel.card_x + card_w - 32
                bar_w = int((bar_x2 - bar_x1) * panel.readiness_pct)
                shimmer_x = bar_x1 + int(((idx / total_frames + p_idx * 0.25) % 1.0) * max(1, bar_w - 28))
                draw.rounded_rectangle(
                    (shimmer_x, card_y2 - 58, min(bar_x1 + bar_w, shimmer_x + 28), card_y2 - 44),
                    radius=4,
                    fill=(255, 255, 255, 95),
                )

            proc.stdin.write(frame.tobytes())
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass

    stderr_bytes = proc.stderr.read() if proc.stderr is not None else b""
    rc = proc.wait(timeout=120)
    if rc != 0:
        raise RuntimeError(
            f"FFmpeg animated slide encode failed (rc={rc}): {stderr_bytes.decode('utf-8', errors='replace')}"
        )

    return out_mp4


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generates dark tactical CAF presentation slides (.png and animated .mp4)."
    )
    parser.add_argument("--slide", required=True, help="Target slide ID under slides_input/.")
    parser.add_argument("--title", default="Joint Command Telemetry & Force Synchronization")
    parser.add_argument(
        "--subtitle",
        default="Integrated Navy, Army & Air Force Readiness  •  Bilingual Field Briefing",
    )
    parser.add_argument(
        "--png-only",
        action="store_true",
        help="Generate only the static 1920x1080 PNG slide without animated MP4.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    png_path = SLIDES_DIR / f"{args.slide}.png"
    generate_tactical_caf_png(png_path, title=args.title, subtitle=args.subtitle)
    print(f"Wrote static slide: {png_path}")
    if not args.png_only:
        mp4_path = SLIDES_DIR / f"{args.slide}.mp4"
        generate_tactical_caf_animated_mp4(mp4_path, base_png=png_path)
        print(f"Wrote animated slide: {mp4_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

