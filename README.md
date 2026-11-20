# `pierre-voice-engine` (`training-video-studio`)

Isolated workspace for producing long-form training voiceovers, narration audio masters, and slide-synchronized educational videos without impacting the production TikTok quant pipeline (`pierre-training-video`).

---

## 1. Directory Layout

| Directory | Purpose |
| :--- | :--- |
| `slides_input/` | Source presentation slide PNGs and visual assets. |
| `scripts_input/` | Per-slide voiceover scripts, speaker notes, and narration manifests. |
| `audio_out/` | EBU R128 (`-14.0 LUFS`, `-1.5 dB TP`) + `atempo=1.04x` mastered voiceover `.wav` / `.mp3` outputs. |
| `video_out/` | Final rendered training and slide-synchronized H.264/AAC `.mp4` videos. |
| `src/` | Phase 2 narration engine, voice client, FFmpeg mastering, and slide/video sync modules. |

---

## 2. Shared Read-Only Voice Assets & Hardware Hygiene

- **Zero Weight Duplication:** This repository reuses the existing local voice studio runtime (`C:\Anti-Gravity-Core\pierre-training-video\voice_studio\tts_server.py`, `http://127.0.0.1:7861`, pinned to `cuda:1`) and read-only reference voice files (`voice_studio\reference_voices\pierre_ref.wav` and `pierre_ref_master.wav`) rather than duplicating heavy checkpoint weights.
- **Mastering Standard:** Every voiceover pass targets broadcast EBU R128 loudness (`I=-14.0`, `TP=-1.5`) paired with an unhurried `atempo=1.04x` tempo cadence.
- **GPU Isolation:** Studio/TTS worker processes are ephemeral only during synthesis runs and must terminate cleanly upon completion so `GPU 0` (`cuda:0`) and `GPU 1` (`cuda:1`) return to `0 MiB` studio allocation.

---

## 3. Subsystem Isolation Guarantee

Zero writes are ever performed against `pierre-training-video/pipeline/`, OpenClaw swarm daemons (`C:\Users\Pierre\.openclaw\`), Julie Core Spatial HUD (`app_eel.py`), `pierre_quant.db`, or `pierres_power_scraper/`.
