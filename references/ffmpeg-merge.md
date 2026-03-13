# FFmpeg Merge Commands

## Horizontal (1920×1080)

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

## Vertical (1080×1920, Douyin/TikTok)

```bash
$FFMPEG -y -i out/video_v.mp4 -i out/tts/full_narration.wav \
  -map 0:v:0 -map 1:a:0 \
  -vf "subtitles=out/tts/subtitles.srt:force_style='FontName=PingFang SC,FontSize=16,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=30,MarginL=60,MarginR=60,Alignment=2'" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -movflags +faststart \
  out/final_v.mp4
```

## Subtitle Style Parameters

| Param | Horizontal | Vertical | Notes |
|-------|-----------|----------|-------|
| FontName | PingFang SC | PingFang SC | macOS CJK font |
| FontSize | 24 | 16 | Smaller for vertical to avoid blocking |
| PrimaryColour | &H00FFFFFF | &H00FFFFFF | White (ABGR) |
| BackColour | &H99000000 | &H80000000 | Vertical more transparent |
| BorderStyle | 4 | 4 | Opaque box behind text |
| MarginV | 60 | 30 | Bottom margin (px) |
| MarginL/R | — | 60 | Side margins for vertical |
| Alignment | 2 | 2 | Bottom-center |

## Key Flags

- `-map 0:v:0 -map 1:a:0` — explicit stream selection (avoids picking wrong audio track)
- `-shortest` — trim to shorter stream (audio may differ slightly from video)
- `-movflags +faststart` — web-friendly progressive download
