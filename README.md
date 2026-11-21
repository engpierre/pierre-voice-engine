# `pierre-voice-engine` (`training-video-studio`)

Isolated workspace for producing bilingual English voiceovers (with badge-free French lower-third subtitles), EBU R128 broadcast audio masters, and 16:9 `1920x1080` slide-synchronized training videos from externally authored animated slides (Google Gemini Veo `.mp4`) or static presentation `.png` exports without impacting the production TikTok quant pipeline (`pierre-training-video`).

---

## 1. Directory Layout

| Directory / File | Purpose |
| :--- | :--- |
| `slides_input/` | Externally authored `1920x1080` 16:9 presentation media placed directly here: animated `.mp4` clips (e.g., Google Gemini Veo exports) or static presentation `.png` exports (`<slide_id>.mp4` preferred, fallback `<slide_id>.png`). |
| `scripts_input/` | Per-slide bilingual scripts (`<slide_id>.txt` or `.md`) with `[EN]` narration (`25s–30s` target, `<= 115` word cap) and optional `[FR]` subtitle blocks. |
| `audio_out/` | EBU R128 (`I=-14.0 LUFS`, `TP=-1.5 dB`, `LRA=11.0`) + `atempo=1.04x` mastered voiceover `.wav` / `.mp3` outputs. |
| `video_out/` | Rendered `1920x1080` 30fps H.264/AAC `.mp4` training slides and `<slide_id>_manifest.json` telemetry. |
| `src/` | Decoupled narration & compositing engine (`models.py`, `script_parser.py`, `tts_client.py`, `audio_master.py`, `slide_compositor.py`, `avatar_sync.py`, `narrator_cli.py`). |
| `assets/avatar/` | Reusable base avatar loop (`avatar_base_9s.mp4`), alpha matte (`avatar_base_9s_matte.mp4`), and pre-computed MuseTalk cache (`coords.pkl`, `latents.pt`). |

---

## 2. CLI Usage

`pierre-voice-engine` never auto-generates or invents slide visuals during narration runs. Place your slide asset in `slides_input/<slide_id>.mp4` (or `.png`) and narration script in `scripts_input/<slide_id>.txt`, then run from `C:\Anti-Gravity-Core\training-video-studio`:

```powershell
# Single-sequence reusable run from existing slides_input/<id>.{mp4,png} and scripts_input/<id>.txt
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide hitl_autonomy_01

# One-command reusable run staging an external slide export (.mp4/.png/.jpg) and inline [EN] script (auto-translates [FR] via Ollama + immediate keep_alive=0 if --fr omitted)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide my_slide_01 --media-in C:\path\to\slide.mp4 --en "Your concise briefing script..."

# Render mastered WAV + MP3 audio only (skip MP4 composition)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide hitl_autonomy_01 --audio-only

# Standard single-slide run with bottom large subtitles (y=0.91, 46px), 1.5s lead-in + 1.5s tail-out airspace, and OneDrive MP4 export
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide agent_vs_skill_01

# Override parameters if desired (e.g. custom lead-in, tail-out, or export dir)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide agent_vs_skill_01 --lead-in-sec 1.5 --tail-out-sec 1.5 --subtitle-y 0.91 --subtitle-font-size 46 --export-dir "C:\Users\Pierre\OneDrive\Bureau\Google antigravity voice slide"

# Batch-process every script in scripts_input/
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --all --with-video
```

---

## 3. Subtitle Typography, Airspace Buffers & Vocal Cadence Spec

- **Bottom Large Subtitles (Badge-Free):** French subtitles sit anchored in the bottom lower-third margin (`y ~ 90%–93%` of 1080p, defaulting to `0.91` / `~983px`) using a large bold font (`44–48 px`, default `46px`) wrapped safely (`<= 52` chars/line, max 2 lines) over a dark translucent backdrop (`rgba(8, 16, 28, 230)`) with cyan border and **strictly NO `FR` badge box**.
- **1.5s Lead-In & 1.5s Tail-Out Airspace:** Mastered audio inserts `1.5s` of digital silence before speech (`--lead-in-sec 1.5`) and `1.5s` trailing buffer after the final word (`--tail-out-sec 1.5`) via FFmpeg `adelay` and `apad` so slide transitions never feel clipped or abrupt (`total duration <= 45.0s`). Subtitles appear synchronously at `t = 1.5s` and clear cleanly when speech resolves before the tail airspace.
- **Natural Vocal Ramp-In & Closing Cadence:** Applies smooth audio envelope shaping (`afade=t=in:st=0:d=0.20` at speech onset and `afade=t=out:st=speech_dur-0.25:d=0.25` at the tail of the final clause) with `atempo=1.04x` and two-pass linear EBU R128 (`-14.0 LUFS`, `-1.5 dBTP`) to eliminate onset pops and ensure clauses resolve naturally.
- **Final-Only MP4 OneDrive Export:** Upon completion, `narrator_cli.py` copies **strictly and exclusively** the final `<slide_id>.mp4` to `--export-dir` (`C:\Users\Pierre\OneDrive\Bureau\Google antigravity voice slide`), leaving intermediate `.wav`, `.mp3`, and `.json` files cleanly isolated in studio working directories.
- **Veo / Animated `.mp4` Preference:** When `slides_input/<slide_id>.mp4` exists, `slide_compositor.py` normalizes it to `1920x1080` at `30 fps` and loops/trims cleanly to the mastered audio duration without adding artificial zoom distortion. Static `.png` inputs retain the smooth `1.00x -> 1.03x` zoom/drift fallback.

---

## 4. Shared Read-Only Voice Assets & Hardware Hygiene

- **Zero Weight Duplication:** Consumes the existing Qwen3-TTS server (`C:\Anti-Gravity-Core\pierre-training-video\voice_studio\tts_server.py`, `http://localhost:7861`, pinned to `cuda:1`) and read-only reference audio (`pierre_ref.wav` / `pierre_ref_master.wav`) without copying model checkpoints.
- **GPU 1 VRAM Guard:** Pre-flight checks `GPU 1` free VRAM before TTS boot; if `< 6000 MiB` free due to idle `qwen3.8-hardened:27b` weights in Ollama, sends `keep_alive: 0` cleanly to `http://localhost:11434/api/generate` without restarting the Ollama daemon.
- **Strict Ephemeral Teardown:** `tts_server.py` runs inside `try...finally` and is terminated immediately after synthesis so `GPU 0` (`cuda:0`) and `GPU 1` (`cuda:1`) return to `0 MiB` studio allocation.
- **Subsystem Isolation:** Zero writes are performed against `pierre-training-video/pipeline/`, OpenClaw daemons, `app_eel.py`, `pierre_quant.db`, `chronos_intel_buffer.json`, or `pierres_power_scraper/`.

---

## 5. Speech-Windowed Avatar Lip-Sync Overlay (MuseTalk v1.5)

- **Isolated Runtime (`.venv_musetalk`):** Dedicated Python 3.10 virtual environment pinned to `cuda:1` (Blackwell RTX 5060 Ti compatible with PyTorch `2.11.0+cu128`), fully decoupled from the primary studio venv.
- **Deterministic Canvas Placement:** Dynamically computes active slide canvas boundaries (`_compute_slide_canvas_rect`) to ensure the `170x170` px avatar overlays squarely within the slide visual area (`AVATAR_RIGHT_INSET_PCT = 0.10`, `AVATAR_TOP_INSET_PCT = 0.11`) regardless of presentation aspect ratio or letterboxing.
- **Speech-Window Synchronization:** Transparent alpha-merged overlay with `0.20s` fade-in at speech onset (`t = 1.5s`) and `0.20s` fade-out at speech conclusion before the `1.5s` tail-out buffer. Pass `--no-avatar` to render audio and subtitles without the avatar overlay.
- **Alpha Matte Pipeline:** Pre-computed 450-frame grayscale matte video (`assets/avatar/avatar_base_9s_matte.mp4`) matching MuseTalk's 25 FPS ping-pong loop for zero-overhead realtime composite via FFmpeg `alphamerge`.
