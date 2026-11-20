# `src/` — Training Voiceover & Slide Sync Architecture (Phase 2 Blueprint)

## Planned Modules

1. **Script & Slide Manifest Parser:**
   - Parses per-slide Markdown/JSON narration scripts under `../scripts_input/` and pairs them deterministically with presentation slide PNGs in `../slides_input/`.
2. **Read-Only Shared Voice Synthesis Client:**
   - Connects strictly as a consumer to the existing Qwen3-TTS server (`C:\Anti-Gravity-Core\pierre-training-video\voice_studio\tts_server.py` on `http://127.0.0.1:7861`, pinned to `cuda:1`) using read-only voice references (`pierre_ref.wav` / `pierre_ref_master.wav`).
   - Enforces automatic `tts_server.py` teardown immediately after synthesis so `GPU 0` (`cuda:0`) and `GPU 1` (`cuda:1`) return to `0 MiB` studio allocation.
3. **EBU R128 + `atempo=1.04x` Mastering Pipeline:**
   - Normalizes raw voice tracks to broadcast loudness (`-14.0 LUFS`, `-1.5 dB TP`) with natural `atempo=1.04x` tempo scaling into `../audio_out/` (`.wav` / `.mp3`).
4. **Slide-to-Video Composer:**
   - Synchronizes slide transitions to mastered per-slide audio durations and encodes crisp H.264/AAC MP4 training modules into `../video_out/`.
