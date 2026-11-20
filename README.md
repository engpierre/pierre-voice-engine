# `pierre-voice-engine` (`training-video-studio`)

Isolated workspace for producing bilingual English voiceovers (with badge-free French lower-third subtitles), EBU R128 broadcast audio masters, and 16:9 `1920x1080` slide-synchronized training videos from either animated Gemini Veo `.mp4` clips or static `.png` slides without impacting the production TikTok quant pipeline (`pierre-training-video`).

---

## 1. Directory Layout

| Directory / File | Purpose |
| :--- | :--- |
| `slides_input/` | Source `1920x1080` 16:9 presentation media: animated `.mp4` clips (e.g., Gemini Veo) or fallback static `.png` slides (`<slide_id>.mp4` preferred, fallback `<slide_id>.png`). |
| `scripts_input/` | Per-slide bilingual scripts (`<slide_id>.txt` or `.md`) with `[EN]` narration (`25s–30s` target, `<= 115` word cap) and optional `[FR]` subtitle blocks. |
| `audio_out/` | EBU R128 (`I=-14.0 LUFS`, `TP=-1.5 dB`, `LRA=11.0`) + `atempo=1.04x` mastered voiceover `.wav` / `.mp3` outputs. |
| `video_out/` | Rendered `1920x1080` 30fps H.264/AAC `.mp4` training slides and `<slide_id>_manifest.json` telemetry. |
| `src/` | Phase 2–3 narration engine (`models.py`, `script_parser.py`, `tts_client.py`, `audio_master.py`, `slide_compositor.py`, `tactical_slide_builder.py`, `narrator_cli.py`). |

---

## 2. CLI Usage (Phase 3)

Run from `C:\Anti-Gravity-Core\training-video-studio` using the existing read-only `video_studio` Python environment (`Pillow` + stdlib):

```powershell
# Optional: generate dark tactical CAF briefing assets (.png + animated .mp4)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.tactical_slide_builder --slide phase3_sample

# Render audio masters + 1920x1080 MP4 video (auto-detects .mp4 animated or .png static slide)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide phase3_sample

# Render mastered WAV + MP3 audio only (skip MP4 render)
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --slide phase3_sample --audio-only

# Batch-process every script in scripts_input/
C:\Anti-Gravity-Core\pierre-training-video\video_studio\.venv\Scripts\python.exe -m src.narrator_cli --all --with-video
```

---

## 3. Animated Slide Input & Lower-Third Subtitle Spec

- **Veo / Animated `.mp4` Preference:** When `slides_input/<slide_id>.mp4` exists, `slide_compositor.py` normalizes it to `1920x1080` at `30 fps` and loops/trims cleanly to the mastered audio duration without adding artificial zoom distortion. Static `.png` inputs retain the smooth `1.00x -> 1.03x` zoom/drift fallback.
- **Clean French Subtitles:** Lower-third strips display crisp centered French text over a dark translucent pill (`rgba(8, 16, 28, 224)`) with zero `FR` badge boxes and safe 16:9 PowerPoint bottom margins.
- **Tactical CAF Preset (`tactical_slide_builder.py`):** Generates dark slate/navy CAF joint operations visuals featuring RCN, Canadian Army, and RCAF panels, diverse personnel medallions, clean headers, and the subtle `Created by MWO Rouleau` footer.

---

## 4. Shared Read-Only Voice Assets & Hardware Hygiene

- **Zero Weight Duplication:** Consumes the existing Qwen3-TTS server (`C:\Anti-Gravity-Core\pierre-training-video\voice_studio\tts_server.py`, `http://127.0.0.1:7861`, pinned to `cuda:1`) and read-only reference audio (`pierre_ref.wav` / `pierre_ref_master.wav`) without copying model checkpoints.
- **GPU 1 VRAM Guard:** Pre-flight checks `GPU 1` free VRAM before TTS boot; if `< 6000 MiB` free due to idle `qwen3.8-hardened:27b` weights in Ollama, sends `keep_alive: 0` cleanly to `http://127.0.0.1:11434/api/generate` without restarting the Ollama daemon.
- **Strict Ephemeral Teardown:** `tts_server.py` runs inside `try...finally` and is terminated immediately after synthesis so `GPU 0` (`cuda:0`) and `GPU 1` (`cuda:1`) return to `0 MiB` studio allocation.
- **Subsystem Isolation:** Zero writes are performed against `pierre-training-video/pipeline/`, OpenClaw daemons, `app_eel.py`, `pierre_quant.db`, `chronos_intel_buffer.json`, or `pierres_power_scraper/`.
