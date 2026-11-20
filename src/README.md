# `src/` — Decoupled Bilingual Training Slide Narrator

## Implemented Modules

1. [`models.py`](models.py) — Immutable `@dataclass(slots=True, frozen=True)` data contracts (`BilingualScript`, `SubtitleChunk`, `AudioMasterResult`, `SlideVideoManifest` with `slide_media_path` / `slide_media_type`).
2. [`script_parser.py`](script_parser.py) — Parses `[EN]` / `[FR]` sections (`<= 115` `[EN]` words ceiling), supports optional local Ollama (`keep_alive: 0`) translation fallback, and generates balanced French lower-third `SubtitleChunk` intervals.
3. [`tts_client.py`](tts_client.py) — Enforces `>= 6000 MiB` free VRAM on `GPU 1` (`cuda:1`), boots `voice_studio/tts_server.py` (`127.0.0.1:7861`) ephemerally, synthesizes `pierre-clone-en-Male` (`pierre_ref.wav`), and guarantees teardown inside `try...finally`.
4. [`audio_master.py`](audio_master.py) — Two-pass linear FFmpeg 9.0 EBU R128 loudness mastering (`I=-14.0 LUFS`, `TP=-1.5 dB`, `LRA=11.0`) + `atempo=1.04x` + peak limiter into `../audio_out/<slide_id>.wav` & `.mp3` (`<= 45.0s` cap) with `volumedetect` verification.
5. [`slide_compositor.py`](slide_compositor.py) — Consumes existing animated `.mp4` slides (e.g., Google Gemini Veo exports normalized to `1920x1080` `30 fps` and looped/trimmed cleanly) or `.png` presentation exports (`1.00x -> 1.03x` zoom), compositing clean badge-free French lower-third cards into `../video_out/<slide_id>.mp4`.
6. [`narrator_cli.py`](narrator_cli.py) — End-to-end CLI supporting `--slide <id>`, `--all`, `--audio-only`, and `--with-video`; validates that `slides_input/<id>.mp4` or `.png` exists before synthesis and emits `../video_out/<slide_id>_manifest.json`.
