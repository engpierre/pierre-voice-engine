"""Isolated MuseTalk v1.5 lip-sync avatar renderer pinned to GPU 1 (`cuda:1`)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[1]
MUSETALK_DIR = STUDIO_ROOT / "vendor" / "MuseTalk"
MUSETALK_PYTHON = STUDIO_ROOT / ".venv_musetalk" / "Scripts" / "python.exe"
AVATAR_BASE_MP4 = STUDIO_ROOT / "assets" / "avatar" / "avatar_base_9s.mp4"
AVATAR_MATTE_MP4 = STUDIO_ROOT / "assets" / "avatar" / "avatar_base_9s_matte.mp4"
AVATAR_CACHE_DIR = STUDIO_ROOT / "assets" / "avatar" / "cache"
MUSETALK_AVATAR_DIR = MUSETALK_DIR / "results" / "v15" / "avatars" / "pierre_avatar"

MIN_GPU1_FREE_MIB = 6000
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL_NAME = "qwen3.8-hardened:27b"
AVATAR_FPS = 25
AVATAR_BATCH_SIZE = 16


def _query_gpu1_free_mib() -> int | None:
    """Queries free VRAM in MiB on physical GPU 1 via `nvidia-smi`."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[0] == "1":
                return int(parts[1])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return None


def _unload_ollama_model() -> None:
    """Gracefully unloads idle Ollama weights from VRAM via `keep_alive: 0`."""
    payload = json.dumps({"model": OLLAMA_MODEL_NAME, "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def ensure_gpu1_vram_headroom(min_free_mib: int = MIN_GPU1_FREE_MIB) -> None:
    """Verifies GPU 1 (`cuda:1`) has >= `min_free_mib` free before MuseTalk launch."""
    free_mib = _query_gpu1_free_mib()
    if free_mib is None or free_mib >= min_free_mib:
        return

    _unload_ollama_model()
    time.sleep(2.0)
    post_free_mib = _query_gpu1_free_mib()
    if post_free_mib is not None and post_free_mib < min_free_mib:
        raise RuntimeError(
            f"Insufficient GPU 1 VRAM for MuseTalk v1.5: {post_free_mib} MiB free "
            f"(required >= {min_free_mib} MiB)."
        )


def _ensure_musetalk_cache_synced() -> None:
    """Ensures `vendor/MuseTalk/results/v15/avatars/pierre_avatar` has cached base assets."""
    required = ["coords.pkl", "latents.pt", "mask_coords.pkl", "avator_info.json"]
    if all((MUSETALK_AVATAR_DIR / f).exists() for f in required):
        return
    if not AVATAR_CACHE_DIR.exists():
        raise FileNotFoundError(
            f"Pre-computed avatar cache missing at {AVATAR_CACHE_DIR}. "
            "Run MuseTalk preparation=True first."
        )
    MUSETALK_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for fname in required:
        src = AVATAR_CACHE_DIR / fname
        if not src.exists():
            raise FileNotFoundError(f"Missing cached avatar artifact: {src}")
        shutil.copy2(src, MUSETALK_AVATAR_DIR / fname)
    for sub in ("full_imgs", "mask"):
        src_sub = AVATAR_CACHE_DIR / sub
        dst_sub = MUSETALK_AVATAR_DIR / sub
        if src_sub.exists() and not dst_sub.exists():
            shutil.copytree(src_sub, dst_sub)


def render_synced_avatar(
    slide_id: str,
    master_wav_path: Path,
    output_mp4_path: Path,
    fps: int = AVATAR_FPS,
    batch_size: int = AVATAR_BATCH_SIZE,
) -> tuple[Path, float]:
    """Renders cached MuseTalk v1.5 lip-synced avatar clip on `cuda:1` with `finally` teardown.

    Returns:
        `(rendered_mp4_path, render_elapsed_sec)`
    """
    if not MUSETALK_PYTHON.exists():
        raise FileNotFoundError(f"MuseTalk venv Python missing: {MUSETALK_PYTHON}")
    if not MUSETALK_DIR.exists():
        raise FileNotFoundError(f"MuseTalk repository missing: {MUSETALK_DIR}")
    if not master_wav_path.exists():
        raise FileNotFoundError(f"Mastered audio WAV missing: {master_wav_path}")
    if not AVATAR_BASE_MP4.exists():
        raise FileNotFoundError(f"Base avatar video missing: {AVATAR_BASE_MP4}")

    _ensure_musetalk_cache_synced()
    ensure_gpu1_vram_headroom(MIN_GPU1_FREE_MIB)

    output_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_yaml = output_mp4_path.parent / f"_tmp_{slide_id}_avatar.yaml"
    clip_key = f"{slide_id}_avatar_raw"
    tmp_yaml.write_text(
        "\n".join(
            [
                "pierre_avatar:",
                "  preparation: False",
                "  bbox_shift: 0",
                f'  video_path: "{AVATAR_BASE_MP4.resolve().as_posix()}"',
                "  audio_clips:",
                f'    {clip_key}: "{master_wav_path.resolve().as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    runner_code = (
        "import sys, runpy, torch\n"
        "_orig_load = torch.load\n"
        "def _patched_load(*args, **kwargs):\n"
        "    if 'weights_only' not in kwargs:\n"
        "        kwargs['weights_only'] = False\n"
        "    return _orig_load(*args, **kwargs)\n"
        "torch.load = _patched_load\n"
        "import mmcv.utils.ext_loader as ext_loader\n"
        "class _DummyExt:\n"
        "    def __getattr__(self, name):\n"
        "        raise NotImplementedError(f'mmcv._ext.{name} unavailable in mmcv-lite')\n"
        "ext_loader.load_ext = lambda name, funcs=None: _DummyExt()\n"
        "sys.argv = [\n"
        "    'scripts/realtime_inference.py',\n"
        "    '--version', 'v15',\n"
        "    '--gpu_id', '0',\n"
        "    '--unet_config', './models/musetalkV15/musetalk.json',\n"
        "    '--unet_model_path', './models/musetalkV15/unet.pth',\n"
        "    '--vae_type', 'sd-vae',\n"
        "    '--whisper_dir', './models/whisper',\n"
        f"    '--inference_config', '{tmp_yaml.resolve().as_posix()}',\n"
        f"    '--batch_size', '{int(batch_size)}',\n"
        f"    '--fps', '{int(fps)}',\n"
        "]\n"
        "runpy.run_path('scripts/realtime_inference.py', run_name='__main__')\n"
    )

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "1"

    proc: subprocess.Popen[bytes] | None = None
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(
            [str(MUSETALK_PYTHON), "-c", runner_code],
            cwd=str(MUSETALK_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out_bytes, _ = proc.communicate(timeout=300)
        if proc.returncode != 0:
            tail = out_bytes.decode("utf-8", errors="replace")[-1500:]
            raise RuntimeError(
                f"MuseTalk avatar render failed for '{slide_id}' (rc={proc.returncode}):\n{tail}"
            )
        elapsed_sec = round(time.perf_counter() - t0, 2)

        raw_vid = MUSETALK_AVATAR_DIR / "vid_output" / f"{clip_key}.mp4"
        if not raw_vid.exists() or raw_vid.stat().st_size == 0:
            raise RuntimeError(f"MuseTalk output video missing or empty: {raw_vid}")
        shutil.move(str(raw_vid), str(output_mp4_path))
        return output_mp4_path, elapsed_sec
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        if tmp_yaml.exists():
            try:
                tmp_yaml.unlink()
            except OSError:
                pass

