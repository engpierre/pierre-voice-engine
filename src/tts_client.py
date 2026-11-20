"""Read-only Qwen3-TTS client with strict GPU 1 VRAM headroom & teardown hygiene."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

VOICE_STUDIO_DIR = Path(r"C:\Anti-Gravity-Core\pierre-training-video\voice_studio")
VOICE_STUDIO_PYTHON = VOICE_STUDIO_DIR / ".venv" / "Scripts" / "python.exe"
VOICE_STUDIO_SERVER = VOICE_STUDIO_DIR / "tts_server.py"
PRIMARY_REF_WAV = VOICE_STUDIO_DIR / "reference_voices" / "pierre_ref.wav"
FALLBACK_REF_WAV = VOICE_STUDIO_DIR / "reference_voices" / "pierre_ref_master.wav"

WINGET_FFMPEG_BIN_DIR = (
    Path.home()
    / "AppData"
    / "Local"
    / "Microsoft"
    / "WinGet"
    / "Packages"
    / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "ffmpeg-9.0-full_build"
    / "bin"
)

TTS_HOST = "127.0.0.1"
TTS_PORT = 7861
TTS_BASE_URL = f"http://{TTS_HOST}:{TTS_PORT}"
PIERRE_VOICE_ID = "pierre-clone-en-Male"
MIN_GPU1_FREE_MIB = 6000
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL_NAME = "qwen3.8-hardened:27b"


def verify_reference_voice() -> Path:
    """Confirms the read-only Pierre reference voice WAV exists before synthesis."""
    if PRIMARY_REF_WAV.exists():
        return PRIMARY_REF_WAV
    if FALLBACK_REF_WAV.exists():
        return FALLBACK_REF_WAV
    raise FileNotFoundError(
        f"Missing read-only reference voice WAV: checked {PRIMARY_REF_WAV} and {FALLBACK_REF_WAV}"
    )


def get_gpu1_free_vram_mib() -> int:
    """Queries free VRAM in MiB on GPU 1 (`cuda:1`) via `nvidia-smi`."""
    proc = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"nvidia-smi query failed (rc={proc.returncode}): {proc.stderr.strip()}")

    for line in proc.stdout.splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) == 2 and parts[0] == "1":
            return int(parts[1])

    raise RuntimeError(f"GPU 1 not found in nvidia-smi output:\n{proc.stdout.strip()}")


def ensure_gpu1_vram_headroom(min_free_mib: int = MIN_GPU1_FREE_MIB) -> int:
    """Ensures >= 6000 MiB free on GPU 1, gracefully unloading idle Ollama weights if needed."""
    free_mib = get_gpu1_free_vram_mib()
    if free_mib >= min_free_mib:
        return free_mib

    payload = json.dumps({"model": OLLAMA_MODEL_NAME, "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    time.sleep(1.5)
    free_mib = get_gpu1_free_vram_mib()
    if free_mib < min_free_mib:
        raise RuntimeError(
            f"Insufficient GPU 1 free VRAM ({free_mib} MiB < {min_free_mib} MiB required) "
            f"even after requesting Ollama `{OLLAMA_MODEL_NAME}` keep_alive=0."
        )
    return free_mib


def check_tts_health(timeout_sec: float = 3.0) -> bool:
    """Returns True when the local Qwen3-TTS REST endpoint responds 200 OK."""
    req = urllib.request.Request(f"{TTS_BASE_URL}/health", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def _start_tts_server() -> subprocess.Popen[bytes] | None:
    """Starts `voice_studio/tts_server.py` pinned to `cuda:1` if `/health` is not live."""
    if check_tts_health():
        return None

    if not VOICE_STUDIO_PYTHON.exists() or not VOICE_STUDIO_SERVER.exists():
        raise FileNotFoundError(
            f"Voice Studio runtime missing: {VOICE_STUDIO_PYTHON} / {VOICE_STUDIO_SERVER}"
        )

    env = os.environ.copy()
    env.pop("CUDA_VISIBLE_DEVICES", None)
    env["QWEN_TTS_DEVICE"] = "cuda:1"
    ffmpeg_dir = str(WINGET_FFMPEG_BIN_DIR)
    if WINGET_FFMPEG_BIN_DIR.exists() and ffmpeg_dir not in env.get("PATH", ""):
        env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{env.get('PATH', '')}"

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(
        [str(VOICE_STUDIO_PYTHON), str(VOICE_STUDIO_SERVER)],
        cwd=str(VOICE_STUDIO_SERVER.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"tts_server.py exited prematurely during startup (rc={proc.returncode})."
            )
        if check_tts_health(timeout_sec=3.0):
            return proc
        time.sleep(1.5)

    raise TimeoutError(f"Timed out after 120s waiting for {TTS_BASE_URL}/health")


def stop_tts_server() -> list[int]:
    """Terminates any running studio `tts_server.py` worker so GPUs return to 0 MiB."""
    ps_script = "\n".join(
        [
            "$ErrorActionPreference = 'SilentlyContinue'",
            "$stopped = New-Object System.Collections.Generic.List[int]",
            "$conns = Get-NetTCPConnection -LocalPort 7860,7861 -State Listen -ErrorAction SilentlyContinue",
            "if ($conns) {",
            "  foreach ($p in ($conns.OwningProcess | Sort-Object -Unique)) {",
            "    if ($p -and $p -ne 0) {",
            "      Stop-Process -Id $p -Force -ErrorAction SilentlyContinue",
            "      [void]$stopped.Add([int]$p)",
            "    }",
            "  }",
            "}",
            "$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*tts_server.py*' }",
            "foreach ($pr in $procs) {",
            "  $pidVal = [int]$pr.ProcessId",
            "  if ($pidVal -gt 0) {",
            "    Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue",
            "    if (-not $stopped.Contains($pidVal)) { [void]$stopped.Add($pidVal) }",
            "  }",
            "}",
            "$stopped | ForEach-Object { Write-Output \"STOPPED_PID=$_\" }",
        ]
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    stopped_pids: list[int] = []
    for line in proc.stdout.splitlines():
        if line.startswith("STOPPED_PID="):
            try:
                stopped_pids.append(int(line.split("=", 1)[1].strip()))
            except ValueError:
                pass
    if stopped_pids:
        time.sleep(0.5)
    return stopped_pids


def synthesize_en_voiceover(en_text: str, raw_wav_out: Path) -> Path:
    """Synthesizes English narration via Qwen3-TTS (`cuda:1`) with strict `finally` teardown."""
    if not en_text.strip():
        raise ValueError("Cannot synthesize empty English narration text.")

    verify_reference_voice()
    ensure_gpu1_vram_headroom(MIN_GPU1_FREE_MIB)
    raw_wav_out.parent.mkdir(parents=True, exist_ok=True)

    spawned_proc: subprocess.Popen[bytes] | None = None
    try:
        spawned_proc = _start_tts_server()
        payload = json.dumps(
            {
                "model": "qwen-tts",
                "voice": PIERRE_VOICE_ID,
                "input": en_text,
                "response_format": "wav",
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{TTS_BASE_URL}/v1/audio/speech",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Qwen3-TTS server returned HTTP {resp.status}")
            audio_bytes = resp.read()

        if len(audio_bytes) <= 1024 or audio_bytes[:4] != b"RIFF":
            raise RuntimeError(
                f"Invalid WAV payload from {TTS_BASE_URL}: {len(audio_bytes)} bytes"
            )

        raw_wav_out.write_bytes(audio_bytes)
        return raw_wav_out
    finally:
        if spawned_proc is not None and spawned_proc.poll() is None:
            try:
                spawned_proc.terminate()
                spawned_proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    spawned_proc.kill()
                except OSError:
                    pass
        stop_tts_server()

