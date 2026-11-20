"""Bilingual `[EN]` / `[FR]` narration parser and subtitle timing builder."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.request

from src.models import BilingualScript, SubtitleChunk

MAX_EN_WORDS = 115
WORDS_PER_SECOND_AT_104X = 2.65
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TRANSLATION_MODEL = "qwen3.8-hardened:27b"

_SECTION_TAG_RE = re.compile(r"\[(?P<lang>en|fr)\]", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _normalize_whitespace(text: str) -> str:
    """Collapses internal linebreaks and repeated spaces into clean single-line prose."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_sections(raw_text: str) -> tuple[str, str]:
    """Splits raw script text into normalized English and French blocks."""
    matches = list(_SECTION_TAG_RE.finditer(raw_text))
    if not matches:
        return _normalize_whitespace(raw_text), ""

    en_parts: list[str] = []
    fr_parts: list[str] = []

    leading = raw_text[: matches[0].start()].strip()
    if leading and not leading.startswith("#"):
        en_parts.append(leading)

    for idx, match in enumerate(matches):
        lang = match.group("lang").upper()
        start = match.end()
        end = matches[idx + 1].start() if (idx + 1) < len(matches) else len(raw_text)
        block = raw_text[start:end].strip()
        if not block:
            continue
        if lang == "EN":
            en_parts.append(block)
        elif lang == "FR":
            fr_parts.append(block)

    return _normalize_whitespace(" ".join(en_parts)), _normalize_whitespace(" ".join(fr_parts))


def _unload_ollama_translation_model() -> None:
    """Best-effort immediate VRAM unload after local Ollama translation."""
    unload_payload = json.dumps(
        {"model": OLLAMA_TRANSLATION_MODEL, "keep_alive": 0}
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=unload_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def _translate_en_to_fr_via_ollama(en_text: str, timeout_sec: float = 60.0) -> str | None:
    """Translates English narration to concise Canadian French and immediately unloads VRAM."""
    prompt = (
        "Translate the following technical training slide narration into concise, "
        "natural French suitable for lower-third presentation subtitles. "
        "Return ONLY the French translation with no quotes, tags, or preamble.\n\n"
        f"{en_text}"
    )
    payload = json.dumps(
        {
            "model": OLLAMA_TRANSLATION_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": 0,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    finally:
        _unload_ollama_translation_model()

    raw_response = str(body.get("response") or "")
    raw_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL | re.IGNORECASE)
    translated = _normalize_whitespace(raw_response).strip("\"'«» ")
    return translated if translated else None


def parse_bilingual_script(
    script_path: Path,
    slide_id: str | None = None,
    auto_translate_fr: bool = True,
) -> BilingualScript:
    """Parses a bilingual slide script, enforcing the 115-word `[EN]` ceiling."""
    if not script_path.exists():
        raise FileNotFoundError(f"Narration script not found: {script_path}")

    resolved_slide_id = (slide_id or script_path.stem).strip()
    if not resolved_slide_id:
        raise ValueError(f"Could not determine slide_id from {script_path}")

    raw_text = script_path.read_text(encoding="utf-8")
    en_text, fr_text = _extract_sections(raw_text)

    en_words = en_text.split()
    en_word_count = len(en_words)
    if en_word_count == 0:
        raise ValueError(f"English narration `[EN]` is empty in {script_path}")
    if en_word_count > MAX_EN_WORDS:
        raise ValueError(
            f"English narration in {script_path} exceeds MAX_EN_WORDS={MAX_EN_WORDS} "
            f"(got {en_word_count} words)."
        )

    fr_auto_translated = False
    if not fr_text:
        if auto_translate_fr:
            ollama_fr = _translate_en_to_fr_via_ollama(en_text)
            if ollama_fr:
                fr_text = ollama_fr
                fr_auto_translated = True
            else:
                fr_text = en_text
        else:
            fr_text = en_text

    estimated_duration_sec = round(en_word_count / WORDS_PER_SECOND_AT_104X, 3)
    return BilingualScript(
        slide_id=resolved_slide_id,
        source_path=str(script_path.resolve()),
        en_text=en_text,
        fr_text=fr_text,
        en_word_count=en_word_count,
        estimated_duration_sec=estimated_duration_sec,
        fr_auto_translated=fr_auto_translated,
    )


def _chunk_words_balanced(words: list[str], max_words: int, max_chars: int) -> list[str]:
    """Distributes words evenly across balanced lower-third cards with zero tiny orphans."""
    if not words:
        return []
    full_text = " ".join(words)
    if len(words) <= max_words and len(full_text) <= max_chars:
        return [full_text]

    n_chunks = max(
        math.ceil(len(words) / max_words),
        math.ceil(len(full_text) / max_chars),
    )
    chunks: list[str] = []
    start = 0
    for idx in range(n_chunks):
        remaining_words = len(words) - start
        remaining_slots = n_chunks - idx
        take = math.ceil(remaining_words / remaining_slots)
        part = " ".join(words[start : start + take])
        while len(part) > max_chars and take > 1:
            take -= 1
            part = " ".join(words[start : start + take])
        chunks.append(part)
        start += take

    if start < len(words):
        tail = " ".join(words[start:])
        if chunks and len(tail.split()) <= 3:
            merged = f"{chunks[-1]} {tail}"
            merged_words = merged.split()
            mid = math.ceil(len(merged_words) / 2)
            chunks[-1] = " ".join(merged_words[:mid])
            chunks.append(" ".join(merged_words[mid:]))
        else:
            chunks.append(tail)

    return [c for c in chunks if c]


def _split_long_segment(segment: str, max_words: int, max_chars: int = 112) -> list[str]:
    """Splits a sentence into balanced lower-third segments within word and character limits."""
    words = segment.split()
    if not words:
        return []
    if len(words) <= max_words and len(segment) <= max_chars:
        return [segment]

    # Prefer clause splits only when every clause is substantial (>= 4 words)
    clauses = [c.strip() for c in re.split(r"(?<=[,;:])\s+", segment) if c.strip()]
    if len(clauses) > 1:
        merged: list[str] = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip() if current else clause
            if len(candidate.split()) <= max_words and len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    merged.append(current)
                current = clause
        if current:
            merged.append(current)

        if all(len(item.split()) >= 4 for item in merged):
            final_parts: list[str] = []
            for item in merged:
                final_parts.extend(
                    _chunk_words_balanced(item.split(), max_words=max_words, max_chars=max_chars)
                )
            return final_parts

    return _chunk_words_balanced(words, max_words=max_words, max_chars=max_chars)


def build_fr_subtitle_chunks(
    fr_text: str,
    total_duration_sec: float,
    max_words_per_chunk: int = 12,
) -> list[SubtitleChunk]:
    """Splits `[FR]` text into 1-2 line lower-third cards aligned proportionally across duration."""
    if total_duration_sec <= 0.0:
        raise ValueError(f"total_duration_sec must be > 0 (got {total_duration_sec})")

    cleaned = _normalize_whitespace(fr_text)
    if not cleaned:
        return []

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
    segments: list[str] = []
    for sentence in sentences:
        segments.extend(_split_long_segment(sentence, max_words=max_words_per_chunk))

    if not segments:
        return []

    weights = [max(1, len(seg)) for seg in segments]
    total_weight = float(sum(weights))

    chunks: list[SubtitleChunk] = []
    cursor_sec = 0.0
    for idx, (seg_text, weight) in enumerate(zip(segments, weights), start=1):
        if idx == len(segments):
            end_sec = round(total_duration_sec, 3)
        else:
            seg_dur = total_duration_sec * (weight / total_weight)
            end_sec = round(min(total_duration_sec, cursor_sec + seg_dur), 3)
        chunks.append(
            SubtitleChunk(
                index=idx,
                text=seg_text,
                start_sec=round(cursor_sec, 3),
                end_sec=end_sec,
            )
        )
        cursor_sec = end_sec

    return chunks
