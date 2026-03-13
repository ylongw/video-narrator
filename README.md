---
name: video-narrator
description: "Generate narrated videos with TTS voiceover and aligned subtitles. 3-step pipeline: Remotion (React video) → Qwen3-TTS (local Apple Silicon) → ffmpeg (merge + subtitle burn). Supports horizontal (1920×1080, YouTube) and vertical (1080×1920, Douyin/TikTok/Reels). 9 speaker presets with emotion control. Use when: creating presentation videos, explainer videos, demo videos, product showcases, tutorial walkthroughs, or any video needing voiceover narration with synchronized Chinese/English subtitles. Triggers: narrated video, video with voiceover, TTS video, presentation video, add narration, video narrator, 视频旁白, 配音视频, 解说视频."
---

# Video Narrator

**Audio-first pipeline:** write narration text → TTS generates audio + timing → Remotion renders visuals to match → ffmpeg merges everything.

```
scenes.json → [TTS] → audio.wav + subtitles.srt + scene_timing.json
                                                        ↓
                                              [Remotion] → video.mp4
                                                        ↓
                                              [ffmpeg]  → final.mp4
```

## Scene Script Format

```json
[
  {"id": "intro", "text": "从文案到视频的三步工作流。"},
  {"id": "main",  "text": "第一步渲染画面，第二步生成语音。"},
  {"id": "outro", "text": "三步搞定。"}
]
```

- Omit `start`/`end` → video duration follows audio (recommended)
- With `start`/`end` (seconds) → audio stretched via atempo to fit
- Pacing guide: **~3 chars/s** for fast Chinese; ~180 chars = ~30s video

## Step 1: Generate TTS

Run `scripts/generate_tts.py` (requires `~/.openclaw/venvs/mlx-audio/` with mlx-audio, soundfile, numpy):

```bash
# Fast-paced Chinese (recommended for short videos)
python3 scripts/generate_tts.py --scenes-json scenes.json \
  --speaker Serena --instruct "快节奏科技讲解，语速偏快，节奏紧凑" \
  --no-align --output-dir out/tts

# English narration
python3 scripts/generate_tts.py --scenes-json scenes.json \
  --speaker Ryan --output-dir out/tts
```

**Outputs:** `full_narration.wav`, `subtitles.srt`, `scene_timing.json`, per-scene `scene_N.wav`

### Speakers & Instruct

| Speaker | Lang | Style | | Speaker | Lang | Style |
|---------|------|-------|-|---------|------|-------|
| **Serena** ⭐ | zh | Warm female | | **Ryan** ⭐ | en | Professional male |
| Vivian | zh | Standard | | Aiden | en | Natural |
| Uncle_Fu | zh | Beijing | | ono_anna | ja | — |
| Dylan | zh | Beijing dialect | | sohee | ko | — |
| Eric | zh | Sichuan | | | | |

`--instruct` controls delivery: `快节奏科技讲解` / `轻松活泼聊天` / `沉稳专业娓娓道来` / `有感染力充满热情`

### Flags

| Flag | Effect |
|------|--------|
| `--no-align` | Skip Paraformer ASR, use proportional timing (faster, recommended for mixed zh/en) |
| `--backend edge-tts` | Online Microsoft TTS fallback (needs internet) |
| `--speaker X` | See table above |
| `--instruct "..."` | Emotion/style/pace control |

## Step 2: Render Remotion

Read [references/remotion-setup.md](references/remotion-setup.md) for project boilerplate (package.json, tsconfig, shared components).

1. Set scene durations in Remotion from `scene_timing.json`
2. Use `TransitionSeries` + `fade()` for scene transitions

**Horizontal** (1920×1080): standard layout
**Vertical** (1080×1920): stack steps vertically, 2-col max, larger fonts (+15%), padding 50-60px sides

```bash
BROWSER=none npx remotion render src/index.ts <CompositionId> out/video.mp4 \
  --codec h264 --concurrency 4 \
  --browser-executable "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

## Step 3: FFmpeg Merge

See [references/ffmpeg-merge.md](references/ffmpeg-merge.md) for exact commands per orientation.

```bash
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y \
  -i out/video.mp4 -i out/tts/full_narration.wav \
  -map 0:v:0 -map 1:a:0 \
  -vf "subtitles=out/tts/subtitles.srt:force_style='...'" \
  -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k \
  -shortest -movflags +faststart out/final.mp4
```

## Constraints

- ffmpeg-full is **keg-only**: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
- Qwen3-TTS max ~120 chars/call (script auto-chunks by scene)
- Qwen3-TTS RTF ≈ 0.5x on Apple Silicon; first run downloads ~2.4GB model
- atempo range 0.5–2.0x; chain two filters outside range
- HuggingFace downloads need proxy: `HTTPS_PROXY=http://127.0.0.1:7897`
