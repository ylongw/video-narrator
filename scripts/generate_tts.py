#!/usr/bin/env python3
"""Generate TTS audio with accurate subtitles using Qwen3-TTS + Paraformer alignment.

Pipeline (Audio-First):
    1. Generate TTS for ALL text as one continuous piece → natural prosody
    2. Run Paraformer ASR to get character-level timestamps → accurate SRT
    3. Output scene timing JSON for Remotion to match audio durations

Usage:
    # Default: Serena, professional style
    python3 generate_tts.py --scenes-json scenes.json --output-dir out/tts_parts

    # Ryan for English
    python3 generate_tts.py --scenes-json scenes.json --speaker Ryan

    # Custom style
    python3 generate_tts.py --scenes-json scenes.json --speaker Serena \
        --instruct "轻松活泼，像在和朋友聊天"

    # edge-tts fallback (online)
    python3 generate_tts.py --scenes-json scenes.json --backend edge-tts

scenes.json format (start/end are OPTIONAL with audio-first mode):
    [{"text": "第一段旁白..."}, {"text": "第二段旁白..."}]

    If start/end are provided, they are used as TARGET durations (pad/speed to fit).
    If omitted, durations are determined by natural TTS speech length.

Outputs:
    full_narration.wav  — complete audio (one continuous piece)
    subtitles.srt       — character-aligned SRT from Paraformer
    scene_timing.json   — actual scene durations for Remotion
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CHINESE_PUNCT = set("。，；、！？：,.!?;:")
MIN_CHUNK_CHARS = 8
MAX_CHUNK_CHARS = 20

FFMPEG = os.environ.get("FFMPEG", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe")

# Qwen3-TTS defaults
DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit"
DEFAULT_SPEAKER = "Serena"
DEFAULT_LANGUAGE = "Chinese"
DEFAULT_INSTRUCT = "专业技术讲解，语速适中，清晰自然"
SAMPLE_RATE = 24000

# Paraformer (for timestamp alignment)
SENSEVOICE_VENV = os.path.expanduser("~/.openclaw/venvs/sensevoice/bin/python3")

SPEAKER_PRESETS = {
    "serena":   {"speaker": "Serena",   "language": "Chinese",  "desc": "女 · 温柔标准"},
    "vivian":   {"speaker": "Vivian",   "language": "Chinese",  "desc": "女 · 标准普通话"},
    "uncle_fu": {"speaker": "Uncle_Fu", "language": "Chinese",  "desc": "男 · 北京腔"},
    "dylan":    {"speaker": "Dylan",    "language": "Chinese",  "desc": "男 · 北京方言"},
    "eric":     {"speaker": "Eric",     "language": "Chinese",  "desc": "男 · 四川方言"},
    "ryan":     {"speaker": "Ryan",     "language": "English",  "desc": "男 · English"},
    "aiden":    {"speaker": "Aiden",    "language": "English",  "desc": "男 · English"},
    "ono_anna": {"speaker": "ono_anna", "language": "Japanese", "desc": "女 · 日语"},
    "sohee":    {"speaker": "sohee",    "language": "Korean",   "desc": "女 · 韩语"},
}


def run_ff(cmd, label="ffmpeg"):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {label} failed (exit {result.returncode})", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result


def get_duration(path):
    result = run_ff(
        [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        label="ffprobe",
    )
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# Qwen3-TTS: generate ONE continuous audio for all scenes
# ---------------------------------------------------------------------------

_qwen3_model = None


def _load_qwen3(model_id):
    global _qwen3_model
    if _qwen3_model is not None:
        return _qwen3_model
    from mlx_audio.tts.utils import load_model
    print(f"Loading Qwen3-TTS: {model_id}")
    t0 = time.time()
    _qwen3_model = load_model(model_id)
    print(f"  Loaded in {time.time() - t0:.1f}s")
    return _qwen3_model


SILENCE_GAP_S = 0.3  # Gap between scenes in concatenated audio


def generate_continuous_audio(scenes, model_id, speaker, language, instruct, outdir):
    """Generate TTS per scene, save each as scene_N.wav, concatenate.

    Returns: (full_audio_path, scene_wav_paths, total_duration)
    """
    import numpy as np
    import soundfile as sf

    model = _load_qwen3(model_id)

    full_text = "".join(s["text"] for s in scenes)
    print(f"\n  Full text: {len(full_text)} chars, {len(scenes)} scenes")
    print(f"  Speaker: {speaker} | Language: {language}")
    print(f"  Instruct: {instruct}")

    all_audio = []
    scene_wav_paths = []
    scene_audio_durations = []
    total_gen_time = 0

    for i, scene in enumerate(scenes):
        text = scene["text"]
        if text and text[-1] not in CHINESE_PUNCT and text[-1] not in '.!?':
            text += "。"

        t0 = time.time()
        results = list(model.generate_custom_voice(
            text=text, speaker=speaker, language=language, instruct=instruct,
        ))
        elapsed = time.time() - t0
        total_gen_time += elapsed

        audio_np = np.array(results[0].audio)
        dur = len(audio_np) / SAMPLE_RATE
        scene_audio_durations.append(dur)

        # Save individual scene WAV for per-scene Paraformer
        scene_wav = outdir / f"scene_{i:02d}.wav"
        sf.write(str(scene_wav), audio_np, SAMPLE_RATE)
        scene_wav_paths.append(scene_wav)

        print(f"  Scene {i}: {elapsed:.1f}s gen → {dur:.1f}s audio | {len(scene['text'])} chars")

        all_audio.append(audio_np)
        if i < len(scenes) - 1:
            silence = np.zeros(int(SAMPLE_RATE * SILENCE_GAP_S), dtype=audio_np.dtype)
            all_audio.append(silence)

    combined = np.concatenate(all_audio)
    duration = len(combined) / SAMPLE_RATE
    out_path = outdir / "full_narration.wav"
    sf.write(str(out_path), combined, SAMPLE_RATE)

    # Save scene durations for scene timing
    with open(outdir / "scene_audio_durations.json", "w") as f:
        json.dump(scene_audio_durations, f)

    print(f"\n  Total: {total_gen_time:.1f}s gen → {duration:.1f}s audio (RTF {total_gen_time/duration:.2f}x)")

    return out_path, scene_wav_paths, duration


# ---------------------------------------------------------------------------
# Paraformer: get character-level timestamps
# ---------------------------------------------------------------------------

def run_paraformer_alignment(audio_path, outdir, prefix="", hotwords=None):
    """Run Paraformer ASR to get character-level timestamps.

    Uses separate sensevoice venv since mlx-audio and funasr may conflict.
    Returns list of {char, start_ms, end_ms}.
    prefix: optional filename prefix for temp files (e.g. "scene_01_")
    hotwords: list of English terms to boost recognition (e.g. ["Remotion", "FFmpeg"])
    """
    align_script = outdir / f"{prefix}align.py"
    align_out = outdir / f"{prefix}align_result.json"

    hotword_str = " ".join(hotwords) if hotwords else ""

    align_script.write_text(f'''
import json
from funasr import AutoModel
model = AutoModel(
    model="paraformer-zh", model_revision="v2.0.4",
    vad_model="fsmn-vad", vad_model_revision="v2.0.4",
    punc_model="ct-punc-c", punc_model_revision="v2.0.4",
    disable_update=True,
)
hotword = "{hotword_str}" or None
result = model.generate("{audio_path}", hotword=hotword)
# Extract char-level timestamps
chars = []
for item in result:
    text = item.get("text", "")
    timestamps = item.get("timestamp", [])
    # Each timestamp pair corresponds to one character
    for i, (start_ms, end_ms) in enumerate(timestamps):
        if i < len(text):
            chars.append({{"char": text[i], "start": start_ms, "end": end_ms}})
with open("{align_out}", "w") as f:
    json.dump(chars, f, ensure_ascii=False)
print(f"Aligned {{len(chars)}} characters")
''')

    t0 = time.time()
    result = subprocess.run(
        [SENSEVOICE_VENV, str(align_script)],
        capture_output=True, text=True, timeout=120,
    )
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  Paraformer failed: {result.stderr[-500:]}", file=sys.stderr)
        return None

    print(f"  Alignment done in {elapsed:.1f}s")
    with open(align_out) as f:
        chars = json.load(f)
    print(f"  {len(chars)} characters with timestamps")

    # Cleanup temp files
    align_script.unlink(missing_ok=True)

    return chars


def _align_original_to_asr(original_text, asr_chars, audio_duration_ms=None):
    """Align original text to ASR characters using sequence matching.

    Returns list of {char, start_ms, end_ms} for each original character,
    with timestamps inherited from the best-matching ASR character.
    Punctuation/spaces in original get interpolated timestamps.
    """
    from difflib import SequenceMatcher

    # Strip punctuation/spaces for alignment (keep indices)
    STRIP = set("。，；、！？：,.!?;: \n\t")

    orig_clean = []  # [(index_in_original, char)]
    for i, ch in enumerate(original_text):
        if ch not in STRIP:
            orig_clean.append((i, ch.lower()))

    asr_clean = []  # [(index_in_asr_chars, char)]
    for i, c in enumerate(asr_chars):
        ch = c["char"]
        if ch not in STRIP:
            asr_clean.append((i, ch.lower()))

    # Sequence match on cleaned characters
    orig_str = "".join(c for _, c in orig_clean)
    asr_str = "".join(c for _, c in asr_clean)
    matcher = SequenceMatcher(None, orig_str, asr_str, autojunk=False)

    # Build mapping: original_clean_idx → asr_chars_idx
    orig_to_asr = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            orig_ci = block.a + k
            asr_ci = block.b + k
            orig_idx = orig_clean[orig_ci][0]
            asr_idx = asr_clean[asr_ci][0]
            orig_to_asr[orig_idx] = asr_idx

    # Build result with interpolation for unmatched characters
    n = len(original_text)
    result = [None] * n

    # First: place all matched characters
    for i in range(n):
        if i in orig_to_asr:
            asr_idx = orig_to_asr[i]
            result[i] = {"char": original_text[i],
                         "start": asr_chars[asr_idx]["start"],
                         "end": asr_chars[asr_idx]["end"]}

    # Find matched indices for interpolation anchors
    matched_indices = sorted(orig_to_asr.keys())
    if not matched_indices:
        # No matches at all — distribute evenly
        total_ms = asr_chars[-1]["end"] - asr_chars[0]["start"]
        start_ms = asr_chars[0]["start"]
        for i in range(n):
            t = start_ms + total_ms * i / max(n - 1, 1)
            result[i] = {"char": original_text[i], "start": t, "end": t + total_ms / n}
        return result

    # Interpolate unmatched chars between matched anchors
    # Before first match
    first_m = matched_indices[0]
    if first_m > 0:
        anchor_start = result[first_m]["start"]
        for i in range(first_m):
            frac = i / first_m
            t = anchor_start * frac
            result[i] = {"char": original_text[i], "start": t, "end": t}

    # Between matched anchors
    for mi in range(len(matched_indices) - 1):
        left = matched_indices[mi]
        right = matched_indices[mi + 1]
        gap = right - left
        if gap <= 1:
            continue
        left_end = result[left]["end"]
        right_start = result[right]["start"]
        for i in range(left + 1, right):
            frac = (i - left) / gap
            t = left_end + (right_start - left_end) * frac
            result[i] = {"char": original_text[i], "start": t, "end": t}

    # After last match — use audio_duration_ms as end anchor if available
    last_m = matched_indices[-1]
    if last_m < n - 1:
        anchor_end = result[last_m]["end"]
        # Use actual audio end time so unrecognized suffix gets spread over remaining audio
        total_end = audio_duration_ms if audio_duration_ms else asr_chars[-1]["end"]
        # If ASR end == audio end, nudge to avoid zero-width subtitles
        if total_end <= anchor_end:
            total_end = anchor_end + 500  # 0.5s fallback stretch
        remaining = n - 1 - last_m
        for i in range(last_m + 1, n):
            frac = (i - last_m) / remaining
            t = anchor_end + (total_end - anchor_end) * frac
            result[i] = {"char": original_text[i], "start": t, "end": t}

    return result


def build_subtitles_from_alignment(asr_chars, scenes, outdir, min_chars=MIN_CHUNK_CHARS, max_chars=MAX_CHUNK_CHARS):
    """Build subtitles using ORIGINAL text + ASR-aligned timestamps.

    For scenes covered by ASR: use aligned character timestamps.
    For scenes NOT covered by ASR: use proportional distribution within
    the scene's known audio time span (from per-scene durations).
    """
    if not scenes:
        return []

    # Get per-scene timing (from actual audio durations)
    scene_timing = find_scene_boundaries(asr_chars, scenes, outdir)

    full_text = "".join(s["text"] for s in scenes)
    if not full_text:
        return []

    # Align original text to ASR timestamps
    aligned = None
    if asr_chars:
        aligned = _align_original_to_asr(full_text, asr_chars)

    ALL_PUNCT = CHINESE_PUNCT | set('.!? ')
    subtitles = []
    char_offset = 0

    for si, scene in enumerate(scenes):
        scene_text = scene["text"]
        scene_len = len(scene_text)
        if scene_len == 0:
            continue

        st = scene_timing[si] if si < len(scene_timing) else None
        scene_start_s = st["start"] if st else 0
        scene_end_s = st["end"] if st else 0
        scene_dur_s = scene_end_s - scene_start_s

        # Check if ASR alignment has meaningful timestamps for this scene
        use_asr = False
        if aligned:
            scene_aligned = aligned[char_offset:char_offset + scene_len]
            # Check if timestamps span a reasonable range (not all same value)
            starts = set(a["start"] for a in scene_aligned)
            if len(starts) > 2:  # at least 3 distinct timestamps
                use_asr = True

        if use_asr:
            # Use ASR-aligned timestamps
            chunk_start_idx = 0
            current = ""
            for j, item in enumerate(scene_aligned):
                ch = item["char"]
                current += ch
                is_punct = ch in CHINESE_PUNCT or ch in '.!?'
                display = current.rstrip("".join(ALL_PUNCT))
                clean_len = len(display.replace(" ", ""))
                should_break = (is_punct and clean_len >= min_chars) or clean_len >= max_chars

                if should_break and display:
                    subtitles.append({
                        "start": round(scene_aligned[chunk_start_idx]["start"] / 1000.0, 3),
                        "end": round(item["end"] / 1000.0, 3),
                        "text": display,
                    })
                    current = ""
                    chunk_start_idx = j + 1

            if current.strip("".join(ALL_PUNCT)):
                display = current.rstrip("".join(ALL_PUNCT))
                if display:
                    subtitles.append({
                        "start": round(scene_aligned[chunk_start_idx]["start"] / 1000.0, 3),
                        "end": round(scene_aligned[-1]["end"] / 1000.0, 3),
                        "text": display,
                    })
        else:
            # Proportional distribution within scene's audio span
            chunks = _chunk_text(scene_text, min_chars, max_chars)
            total_c = sum(len(c) for c in chunks) or 1
            t = scene_start_s
            for c in chunks:
                dur = scene_dur_s * len(c) / total_c
                subtitles.append({
                    "start": round(t, 3),
                    "end": round(t + dur, 3),
                    "text": c,
                })
                t += dur

        char_offset += scene_len

    return subtitles


def build_subtitles_per_scene(scenes, scene_wav_paths, outdir, min_chars, max_chars):
    """Run Paraformer per scene, build subtitles with accurate per-scene timestamps.

    For each scene:
      1. Run Paraformer on scene's WAV → char-level timestamps (scene-local)
      2. Align original text to ASR text via SequenceMatcher
      3. Chunk at punctuation → subtitle entries
      4. Shift timestamps by cumulative scene start offset
    Return: (subtitles, scene_timing)
    """
    import json as _json
    ALL_PUNCT = CHINESE_PUNCT | set('.!? ')
    subtitles = []
    scene_timing = []
    t_offset = 0.0  # cumulative start time

    for i, (scene, wav_path) in enumerate(zip(scenes, scene_wav_paths)):
        dur = get_duration(wav_path)
        scene_timing.append({
            "scene_idx": i,
            "start": round(t_offset, 3),
            "end": round(t_offset + dur, 3),
            "duration": round(dur, 3),
        })

        scene_text = scene["text"]
        # Extract English words as hotwords to boost Paraformer recognition
        import re as _re
        hotwords = list(set(_re.findall(r'[A-Za-z][A-Za-z0-9]+', scene_text)))
        chars = run_paraformer_alignment(wav_path, outdir, prefix=f"sc{i:02d}_", hotwords=hotwords or None)

        # Use ASR only when coverage is good enough; else fallback proportional
        # Always chunk the text first, then distribute time
        chunks = _chunk_text(scene_text, min_chars, max_chars)
        if not chunks:
            t_offset += dur + SILENCE_GAP_S
            continue

        asr_coverage = (len(chars) / max(len(scene_text), 1)) if chars else 0
        use_asr = chars and len(set(c["start"] for c in chars)) > 2 and asr_coverage >= 0.5
        print(f"  Scene {i} ASR coverage: {asr_coverage:.0%} ({len(chars) if chars else 0}/{len(scene_text)}) → {'ASR-weighted' if use_asr else 'proportional'}")

        if use_asr:
            # Get ASR-relative weights for each chunk (how much audio time each chunk occupies)
            aligned = _align_original_to_asr(scene_text, chars, audio_duration_ms=dur * 1000)
            chunk_weights = []
            char_pos = 0
            for c in chunks:
                # Find the chunk's position in original text
                chunk_idx = scene_text.find(c, char_pos)
                if chunk_idx < 0:
                    chunk_idx = char_pos
                end_idx = chunk_idx + len(c) - 1
                end_idx = min(end_idx, len(aligned) - 1)
                chunk_idx = min(chunk_idx, len(aligned) - 1)
                # Weight = ASR time span for this chunk
                t_start = aligned[chunk_idx]["start"]
                t_end = aligned[end_idx]["end"]
                weight = max(t_end - t_start, len(c) * 10)  # minimum weight by char count
                chunk_weights.append(weight)
                char_pos = end_idx + 1
        else:
            # Pure character-count weights
            chunk_weights = [len(c) for c in chunks]

        # Distribute scene duration across chunks proportionally to weights
        total_weight = sum(chunk_weights) or 1
        t = t_offset
        for ci, c in enumerate(chunks):
            chunk_dur = dur * chunk_weights[ci] / total_weight
            subtitles.append({
                "start": round(t, 3),
                "end": round(t + chunk_dur, 3),
                "text": c,
            })
            t += chunk_dur

        t_offset += dur + SILENCE_GAP_S

    return subtitles, scene_timing


def _chunk_text(text, min_chars=MIN_CHUNK_CHARS, max_chars=MAX_CHUNK_CHARS):
    """Split text into display chunks at punctuation boundaries."""
    ALL_PUNCT = CHINESE_PUNCT | set('.!? ')
    chunks = []
    current = ""
    for ch in text:
        current += ch
        is_punct = ch in CHINESE_PUNCT or ch in '.!?'
        display = current.rstrip("".join(ALL_PUNCT))
        clean_len = len(display.replace(" ", ""))
        if (is_punct and clean_len >= min_chars) or clean_len >= max_chars:
            if display:
                chunks.append(display)
            current = ""
    if current.strip("".join(ALL_PUNCT)):
        display = current.rstrip("".join(ALL_PUNCT))
        if display:
            chunks.append(display)
    return chunks


def find_scene_boundaries(asr_chars, scenes, outdir):
    """Determine scene boundaries from per-scene audio durations.

    Uses the actual audio durations saved during generation (most reliable),
    with 0.3s gaps between scenes factored in.
    """
    timing_path = outdir / "scene_audio_durations.json"
    if timing_path.exists():
        with open(timing_path) as f:
            scene_durations = json.load(f)

        timing = []
        t = 0.0
        for i, dur in enumerate(scene_durations):
            timing.append({
                "scene_idx": i,
                "start": round(t, 3),
                "end": round(t + dur, 3),
                "duration": round(dur, 3),
            })
            t += dur
            if i < len(scene_durations) - 1:
                t += 0.3  # silence gap
        return timing

    # Fallback: proportional from ASR if no duration file
    if not asr_chars:
        return []

    total_dur = asr_chars[-1]["end"] / 1000.0
    total_chars = sum(len(s["text"]) for s in scenes)
    timing = []
    t = 0.0
    for i, scene in enumerate(scenes):
        dur = total_dur * len(scene["text"]) / total_chars
        timing.append({"scene_idx": i, "start": round(t, 3), "end": round(t + dur, 3), "duration": round(dur, 3)})
        t += dur
    return timing


# ---------------------------------------------------------------------------
# Pad/speed audio to match target durations (if scenes have start/end)
# ---------------------------------------------------------------------------

def pad_or_speed_full(audio_path, scene_timing, scenes, outdir):
    """If scenes have fixed start/end, pad or speed the audio to match."""
    has_timing = all("start" in s and "end" in s for s in scenes)
    if not has_timing:
        return audio_path, scene_timing, 1.0

    target_total = scenes[-1]["end"] - scenes[0]["start"]
    actual_total = get_duration(audio_path)

    if abs(actual_total - target_total) < 1.0:
        return audio_path, scene_timing, 1.0

    ratio = actual_total / target_total
    print(f"\n=== Adjusting audio: {actual_total:.1f}s → {target_total:.1f}s (ratio {ratio:.2f}x) ===")

    adjusted_path = outdir / "full_narration_adjusted.wav"
    if ratio <= 2.0:
        run_ff([FFMPEG, "-y", "-i", str(audio_path),
                "-filter:a", f"atempo={ratio}", "-t", str(target_total),
                str(adjusted_path)], label="speed adjust")
    else:
        s2 = ratio / 2.0
        run_ff([FFMPEG, "-y", "-i", str(audio_path),
                "-filter:a", f"atempo=2.0,atempo={s2}", "-t", str(target_total),
                str(adjusted_path)], label="speed adjust")

    # Adjust all timestamps
    for st in scene_timing:
        st["start"] = round(st["start"] / ratio, 3)
        st["end"] = round(st["end"] / ratio, 3)
        st["duration"] = round(st["end"] - st["start"], 3)

    return adjusted_path, scene_timing, ratio


# ---------------------------------------------------------------------------
# edge-tts fallback (unchanged)
# ---------------------------------------------------------------------------

async def generate_edge_tts(scenes, voice, rate, outdir):
    """Generate per-scene audio with edge-tts + word boundaries."""
    import edge_tts

    all_subtitles = []
    padded_files = []

    for idx, scene in enumerate(scenes):
        audio_path = outdir / f"scene_{idx:02d}.mp3"
        communicate = edge_tts.Communicate(scene["text"], voice, rate=rate, boundary="WordBoundary")
        word_boundaries = []
        with open(audio_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    offset_s = chunk["offset"] / 10_000_000
                    duration_s = chunk["duration"] / 10_000_000
                    word_boundaries.append({"start": offset_s, "end": offset_s + duration_s, "text": chunk["text"]})

        target_dur = scene.get("end", 0) - scene.get("start", 0) if "end" in scene else None
        if target_dur and target_dur > 0:
            actual_dur = get_duration(audio_path)
            padded = outdir / f"padded_{idx:02d}.mp3"
            if actual_dur <= target_dur + 0.5:
                silence = max(0, target_dur - actual_dur)
                run_ff([FFMPEG, "-y", "-i", str(audio_path), "-f", "lavfi", "-i",
                        f"anullsrc=r=24000:cl=mono", "-filter_complex",
                        f"[1:a]atrim=0:{silence}[s];[0:a][s]concat=n=2:v=0:a=1[out]",
                        "-map", "[out]", "-t", str(target_dur), str(padded)])
            else:
                ratio = actual_dur / target_dur
                run_ff([FFMPEG, "-y", "-i", str(audio_path),
                        "-filter:a", f"atempo={min(ratio, 2.0)}", "-t", str(target_dur), str(padded)])
            padded_files.append(padded)
            scene_offset = scene.get("start", 0)
            speed_ratio = actual_dur / target_dur if actual_dur > target_dur else 1.0
        else:
            padded_files.append(audio_path)
            scene_offset = sum(get_duration(f) for f in padded_files[:-1])
            speed_ratio = 1.0

        for wb in word_boundaries:
            all_subtitles.append({
                "start": scene_offset + wb["start"] / speed_ratio,
                "end": scene_offset + wb["end"] / speed_ratio,
                "text": wb["text"],
            })

    # Concat
    concat_list = outdir / "concat.txt"
    with open(concat_list, "w") as f:
        for pf in padded_files:
            f.write(f"file '{pf.resolve()}'\n")
    full_audio = outdir / "full_narration.mp3"
    run_ff([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", str(full_audio)])

    return full_audio, all_subtitles


# ---------------------------------------------------------------------------
# SRT output
# ---------------------------------------------------------------------------

def format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def stabilize_subtitle_timing(subtitles, min_duration=0.45):
    """Enforce monotonic subtitle timings and avoid ultra-short flashes."""
    if not subtitles:
        return subtitles

    out = [dict(s) for s in subtitles]

    # Pass 1: monotonic starts/ends
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["start"]:
            out[i]["start"] = out[i - 1]["start"]
        if out[i]["end"] < out[i]["start"]:
            out[i]["end"] = out[i]["start"]

    # Pass 2: expand too-short entries when possible
    for i in range(len(out)):
        cur = out[i]
        dur = cur["end"] - cur["start"]
        if dur >= min_duration:
            continue

        target_end = cur["start"] + min_duration
        if i < len(out) - 1:
            next_start = out[i + 1]["start"]
            # Do not overlap next subtitle
            target_end = min(target_end, max(cur["start"], next_start - 0.02))

        # If still too short, borrow from previous by moving start backward
        if target_end - cur["start"] < min_duration and i > 0:
            prev_end = out[i - 1]["end"]
            new_start = max(prev_end + 0.02, target_end - min_duration)
            cur["start"] = min(cur["start"], new_start)

        cur["end"] = max(cur["end"], target_end)

    return out


def write_srt(subtitles, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, sub in enumerate(subtitles, 1):
            f.write(f"{idx}\n")
            f.write(f"{format_srt_time(sub['start'])} --> {format_srt_time(sub['end'])}\n")
            f.write(f"{sub['text']}\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio + aligned SRT subtitles")
    parser.add_argument("--scenes-json", required=True)
    parser.add_argument("--output-dir", default="out/tts_parts")
    parser.add_argument("--min-chars", type=int, default=MIN_CHUNK_CHARS)
    parser.add_argument("--max-chars", type=int, default=MAX_CHUNK_CHARS)
    parser.add_argument("--backend", choices=["qwen3", "edge-tts"], default="qwen3")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--speaker", default=DEFAULT_SPEAKER)
    parser.add_argument("--language", default=None)
    parser.add_argument("--instruct", default=DEFAULT_INSTRUCT)
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="-5%")
    parser.add_argument("--no-align", action="store_true", help="Skip Paraformer alignment (use proportional subtitles)")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    with open(args.scenes_json) as f:
        scenes = json.load(f)

    # Resolve speaker preset
    speaker_key = args.speaker.lower()
    if speaker_key in SPEAKER_PRESETS:
        preset = SPEAKER_PRESETS[speaker_key]
        speaker = preset["speaker"]
        language = args.language or preset["language"]
        print(f"Speaker: {speaker} ({preset['desc']})")
    else:
        speaker = args.speaker
        language = args.language or DEFAULT_LANGUAGE

    if args.backend == "qwen3":
        print(f"=== Qwen3-TTS (continuous) | {speaker} | {language} ===")
        print(f"  Instruct: {args.instruct}")

        # Step 1: Generate per-scene audio + full concatenated audio
        audio_path, scene_wav_paths, audio_dur = generate_continuous_audio(
            scenes, args.model, speaker, language, args.instruct, outdir
        )

        # Step 2: Per-scene Paraformer alignment → accurate subtitles + timing
        if not args.no_align:
            print(f"\n=== Paraformer alignment (per scene) ===")
            subtitles, scene_timing = build_subtitles_per_scene(
                scenes, scene_wav_paths, outdir, args.min_chars, args.max_chars
            )
        else:
            subtitles = _fallback_subtitles(scenes, audio_dur)
            scene_timing = find_scene_boundaries(None, scenes, outdir)

        print(f"\n=== Scene timing (from alignment) ===")
        for st in scene_timing:
            print(f"  Scene {st['scene_idx']}: {st['start']:.1f}s → {st['end']:.1f}s ({st['duration']:.1f}s)")

        # Step 3: Adjust audio/timestamps if target duration is fixed
        audio_path, scene_timing, ratio = pad_or_speed_full(audio_path, scene_timing, scenes, outdir)
        if ratio != 1.0:
            for sub in subtitles:
                sub["start"] = round(sub["start"] / ratio, 3)
                sub["end"] = round(sub["end"] / ratio, 3)

        subtitles = stabilize_subtitle_timing(subtitles)

    else:  # edge-tts
        print(f"=== edge-tts | {args.voice} | rate={args.rate} ===")
        audio_path, subtitles = await generate_edge_tts(scenes, args.voice, args.rate, outdir)
        scene_timing = None

    # Write outputs
    print(f"\n=== Output ===")
    srt_path = outdir / "subtitles.srt"
    write_srt(subtitles, srt_path)
    print(f"  {len(subtitles)} subtitle entries → {srt_path}")
    for s in subtitles[:5]:
        print(f"    [{format_srt_time(s['start'])} → {format_srt_time(s['end'])}] {s['text']}")
    if len(subtitles) > 5:
        print(f"    ... ({len(subtitles) - 5} more)")

    json_path = outdir / "subtitles.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(subtitles, f, ensure_ascii=False, indent=2)

    if scene_timing:
        timing_path = outdir / "scene_timing.json"
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(scene_timing, f, ensure_ascii=False, indent=2)
        print(f"  Scene timing → {timing_path}")
        total_dur = scene_timing[-1]["end"]
        print(f"  Total audio: {total_dur:.1f}s")

    dur = get_duration(audio_path)
    size = os.path.getsize(audio_path) / 1024
    print(f"  Audio: {audio_path} ({dur:.1f}s, {size:.0f}KB)")
    print(f"\n✅ Done | Backend: {args.backend}")


def _fallback_subtitles(scenes, total_dur):
    """Proportional subtitle fallback when alignment is unavailable."""
    total_chars = sum(len(s["text"]) for s in scenes)
    subs = []
    t = 0.0
    for scene in scenes:
        ratio = len(scene["text"]) / total_chars
        scene_dur = total_dur * ratio
        # Simple chunking
        text = scene["text"]
        chunks = []
        current = ""
        for ch in text:
            current += ch
            if (ch in CHINESE_PUNCT and len(current) >= MIN_CHUNK_CHARS) or len(current) >= MAX_CHUNK_CHARS:
                display = current.rstrip("".join(CHINESE_PUNCT) + " ")
                if display:
                    chunks.append(display)
                current = ""
        if current.strip("".join(CHINESE_PUNCT) + " "):
            chunks.append(current.rstrip("".join(CHINESE_PUNCT) + " "))

        chunk_total = sum(len(c) for c in chunks) or 1
        for c in chunks:
            dur = scene_dur * len(c) / chunk_total
            subs.append({"start": round(t, 3), "end": round(t + dur, 3), "text": c})
            t += dur
    return subs


def _fallback_timing(scenes, total_dur):
    """Proportional scene timing fallback."""
    total_chars = sum(len(s["text"]) for s in scenes)
    timing = []
    t = 0.0
    for i, scene in enumerate(scenes):
        dur = total_dur * len(scene["text"]) / total_chars
        timing.append({"scene_idx": i, "start": round(t, 3), "end": round(t + dur, 3), "duration": round(dur, 3)})
        t += dur
    return timing


if __name__ == "__main__":
    asyncio.run(main())
