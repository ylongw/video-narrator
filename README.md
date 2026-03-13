---
name: video-narrator
description: "Generate narrated videos with TTS voiceover and aligned subtitles using Remotion + Qwen3-TTS (local) + ffmpeg. Supports horizontal (1920×1080) and vertical (1080×1920, Douyin/TikTok). Use when: creating presentation videos, explainer videos, demo videos, or any video needing voiceover narration with synchronized Chinese/English subtitles. Triggers: narrated video, video with voiceover, TTS video, presentation video with subtitles, add narration to video, video narrator."
---

# Video Narrator

Pipeline: **Scene script (JSON) → Remotion render → Qwen3-TTS audio + SRT → ffmpeg merge → final output**.

## Pipeline Overview

```
Scene Script (JSON)
    ↓
[1] Remotion → raw video (no audio)
    ↓
[2] Qwen3-TTS → per-scene audio + SRT subtitles + scene_timing.json
    ↓
[3] ffmpeg-full → merge video + audio + burn subtitles → final .mp4
```

TTS runs **100% local** on Apple Silicon via mlx-audio. No internet required, no rate limits.

## Orientation & Resolution

| Format | Resolution | Use Case | Subtitle Style |
|--------|-----------|----------|---------------|
| **Horizontal** | 1920×1080 | YouTube, presentations | FontSize=24, MarginV=60 |
| **Vertical** | 1080×1920 | Douyin, TikTok, Reels | FontSize=16, MarginV=30, MarginL/R=60 |

## Prerequisites

```bash
# ffmpeg-full (libass for subtitle burning) — keg-only
brew install ffmpeg-full
# Binary: /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg

# Qwen3-TTS via mlx-audio (local, Apple Silicon)
~/.openclaw/venvs/mlx-audio/bin/pip install mlx-audio soundfile numpy

# Model auto-downloads on first run (~2.4GB):
#   mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit

# Paraformer (optional, subtitle alignment)
~/.openclaw/venvs/sensevoice/bin/pip install funasr

# Remotion
npm i remotion@4 @remotion/cli@4 @remotion/transitions@4 react react-dom

# Optional: edge-tts fallback (online Microsoft TTS)
~/.openclaw/venvs/edge-tts/bin/pip install edge-tts
```

## Step 1: Scene Script

```json
[
  {"id": "intro", "text": "Video Narrator，从文案到视频的三步工作流。"},
  {"id": "pipeline", "text": "第一步Remotion渲染画面，第二步TTS生成语音。"},
  {"id": "outro", "text": "三步搞定。"}
]
```

**Key rules:**
- No `start`/`end` fields → video length follows audio (recommended for short videos)
- With `start`/`end` → audio is stretched/compressed via atempo to fit target duration
- **~3 chars/sec** is the sweet spot for fast-paced Chinese narration
- **~180 chars for 30s**, **~350 chars for 60s** — keep it concise

## Step 2: Remotion Render

Read [references/remotion-setup.md](references/remotion-setup.md) for boilerplate.

### Horizontal (1920×1080)
```tsx
<Composition id="MyVideo" component={MainVideo}
  durationInFrames={30 * 31} fps={30} width={1920} height={1080} />
```

### Vertical (1080×1920)
```tsx
<Composition id="MyVideoV" component={MainVideoV}
  durationInFrames={30 * 31} fps={30} width={1080} height={1920} />
```

**Vertical layout tips:**
- Pipeline steps: stack vertically (not side-by-side)
- Multi-column grids → 2-col max (not 3+)
- Font sizes: +10-20% larger than horizontal
- Padding: 50-60px horizontal, 120px+ top

**Render:**
```bash
BROWSER=none npx remotion render src/index.ts <CompositionId> out/video.mp4 \
  --codec h264 --concurrency 4 \
  --browser-executable /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome
```

**Scene durations** should match TTS output. After TTS generates `scene_timing.json`, update Remotion scene durations to match, then re-render.

## Step 3: TTS Audio + Subtitles

```bash
# Default: Serena, professional style
~/.openclaw/venvs/mlx-audio/bin/python3 scripts/generate_tts.py \
  --scenes-json scenes.json --output-dir out/tts

# Fast-paced style (recommended for short videos)
~/.openclaw/venvs/mlx-audio/bin/python3 scripts/generate_tts.py \
  --scenes-json scenes.json --speaker Serena \
  --instruct "快节奏科技讲解，语速偏快，节奏紧凑" --output-dir out/tts

# English narration
~/.openclaw/venvs/mlx-audio/bin/python3 scripts/generate_tts.py \
  --scenes-json scenes.json --speaker Ryan --output-dir out/tts

# Skip Paraformer alignment (faster, uses proportional subtitle timing)
~/.openclaw/venvs/mlx-audio/bin/python3 scripts/generate_tts.py \
  --scenes-json scenes.json --no-align --output-dir out/tts

# edge-tts fallback (online)
~/.openclaw/venvs/edge-tts/bin/python3 scripts/generate_tts.py \
  --backend edge-tts --voice zh-CN-XiaoxiaoNeural --scenes-json scenes.json
```

**Outputs:**
- `full_narration.wav` — concatenated audio (all scenes + 0.3s gaps)
- `subtitles.srt` — aligned subtitles (original text, not ASR)
- `scene_timing.json` — per-scene start/end/duration for Remotion
- `scene_N.wav` — individual scene audio files

### Speaker Presets

| Speaker | Gender | Language | Style |
|---------|--------|----------|-------|
| **Serena** ⭐ | Female | Chinese | Warm, gentle (default) |
| Vivian | Female | Chinese | Standard Mandarin |
| Uncle_Fu | Male | Chinese | Beijing accent |
| Dylan | Male | Chinese | Beijing dialect |
| Eric | Male | Chinese | Sichuan dialect |
| **Ryan** ⭐ | Male | English | Clear, professional |
| Aiden | Male | English | Natural |
| ono_anna | Female | Japanese | — |
| sohee | Female | Korean | — |

### Instruct Examples

| Style | Instruct |
|-------|----------|
| Professional (default) | `专业技术讲解，语速适中，清晰自然` |
| **Fast-paced** ⭐ | `快节奏科技讲解，语速偏快，节奏紧凑` |
| Casual | `轻松活泼，像在和朋友聊天` |
| Authoritative | `沉稳专业，娓娓道来` |
| Energetic | `有感染力，充满热情` |
| Soft | `温柔细语，舒缓放松` |

### Subtitle Alignment

Two modes:
- **`--no-align`** (recommended): Per-scene proportional distribution by character count. Fast, predictable, works well for all languages.
- **Paraformer alignment** (default): ASR-based timing. Better for pure Chinese text (85%+ coverage). For mixed Chinese/English content, coverage drops to 50-65% — use `--no-align` instead.

## Step 4: FFmpeg Merge

### Horizontal
```bash
FFMPEG=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg

$FFMPEG -y -i out/video.mp4 -i out/tts/full_narration.wav \
  -map 0:v:0 -map 1:a:0 \
  -vf "subtitles=out/tts/subtitles.srt:force_style='FontName=PingFang SC,FontSize=24,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=4,Outline=0,MarginV=60,Alignment=2'" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -movflags +faststart \
  out/final.mp4
```

### Vertical (Douyin/TikTok)
```bash
$FFMPEG -y -i out/video_v.mp4 -i out/tts/full_narration.wav \
  -map 0:v:0 -map 1:a:0 \
  -vf "subtitles=out/tts/subtitles.srt:force_style='FontName=PingFang SC,FontSize=16,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=30,MarginL=60,MarginR=60,Alignment=2'" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -movflags +faststart \
  out/final_v.mp4
```

**Vertical subtitle differences:**
- `FontSize=16` (vs 24) — smaller to avoid blocking content
- `BackColour=&H80000000` — more transparent background
- `MarginV=30` — near bottom edge
- `MarginL=60,MarginR=60` — side margins to avoid edge clipping

## Full Workflow (Quick Reference)

```bash
# 1. Write scenes.json (no start/end → audio-driven duration)
# 2. Generate TTS first (to get scene_timing.json)
~/.openclaw/venvs/mlx-audio/bin/python3 scripts/generate_tts.py \
  --scenes-json scenes.json --speaker Serena \
  --instruct "快节奏科技讲解，语速偏快，节奏紧凑" \
  --no-align --output-dir out/tts

# 3. Update Remotion scene durations from scene_timing.json
# 4. Render Remotion (horizontal and/or vertical)
BROWSER=none npx remotion render src/index.ts MyVideo out/video.mp4 ...
BROWSER=none npx remotion render src/index.ts MyVideoV out/video_v.mp4 ...

# 5. FFmpeg merge (see commands above)
# 6. Copy to Downloads
cp out/final.mp4 ~/Downloads/
```

## Constraints

- **ffmpeg-full is keg-only** — always use `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
- **Qwen3-TTS first load** downloads ~2.4GB model (cached after)
- **Qwen3-TTS performance:** RTF ≈ 0.5x on M-series (10s audio in ~5s)
- **Qwen3-TTS max per call:** ~120 Chinese chars. Script auto-chunks by scene to avoid truncation.
- **atempo range:** 0.5–2.0x. Chain filters for ratios outside range.
- **Subtitle chunking:** max ~20 chars, min ~8 chars; split on `。，；、！？：`
- **edge-tts requires internet** and may 503 — fallback only
- **Proxy for HuggingFace downloads:** `HTTPS_PROXY=http://127.0.0.1:7897`
