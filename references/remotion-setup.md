# Remotion Project Boilerplate

## Table of Contents

- [package.json dependencies](#packagejson-dependencies)
- [tsconfig.json](#tsconfigjson)
- [remotion.config.ts](#remotionconfigts)
- [src/index.ts](#srcindexts)
- [src/Root.tsx](#srcroottsx)
- [TransitionSeries Pattern](#transitionseries-pattern)
- [Shared Components (shared.tsx)](#shared-components-sharedtsx)
- [Render Command](#render-command)

## package.json dependencies

```json
{
  "dependencies": {
    "@remotion/cli": "4.0.435",
    "@remotion/transitions": "4.0.435",
    "react": "19.2.4",
    "react-dom": "19.2.4",
    "remotion": "4.0.435"
  }
}
```

## tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

## remotion.config.ts

```ts
import {Config} from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');
```

## src/index.ts

```ts
export {RemotionRoot} from './Root';
```

## src/Root.tsx

```tsx
import {Composition} from 'remotion';
import {MyVideo} from './MyVideo';

export const RemotionRoot = () => (
  <Composition
    id="MyVideo"
    component={MyVideo}
    durationInFrames={30 * 180}  // 180s at 30fps
    fps={30}
    width={1920}
    height={1080}
  />
);
```

## TransitionSeries Pattern

Remotion renders **video only** — no audio, no subtitles. Audio and subtitles are merged by ffmpeg in Step 3.

```tsx
import {AbsoluteFill, useVideoConfig} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';

export const MyVideo: React.FC = () => {
  const {fps} = useVideoConfig();
  const t = (s: number) => Math.round(s * fps);
  const FADE = t(1.2);

  return (
    <AbsoluteFill style={{backgroundColor: '#0D0D0D'}}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={t(15)}>
          <Scene1 />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({durationInFrames: FADE})}
        />
        <TransitionSeries.Sequence durationInFrames={t(22)}>
          <Scene2 />
        </TransitionSeries.Sequence>
        {/* ... more scenes */}
      </TransitionSeries>
    </AbsoluteFill>
  );
};
```

## Shared Components (shared.tsx)

```tsx
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const C = {
  bg: '#0D0D0D', card: '#1A1A1E', border: '#2C2C30',
  green: '#3EDC2F', blue: '#4178FF', yellow: '#FFD500',
  red: '#FF453A', text: '#F0F0F0', dim: '#8D8D93',
};

export const GridBg: React.FC = () => (
  <AbsoluteFill>
    <div style={{
      position: 'absolute', inset: 0,
      backgroundImage: `
        linear-gradient(rgba(65,120,255,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(65,120,255,0.04) 1px, transparent 1px)`,
      backgroundSize: '80px 80px',
    }} />
  </AbsoluteFill>
);

export const SceneTitle: React.FC<{text: string; num?: string; delay?: number}> = ({text, num, delay = 0}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const progress = spring({frame, fps, delay, config: {damping: 200}, durationInFrames: Math.round(fps * 1.2)});
  const y = interpolate(progress, [0, 1], [50, 0]);

  return (
    <div style={{opacity: progress, transform: `translateY(${y}px)`, marginBottom: 40}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
        {num && <div style={{width: 48, height: 48, borderRadius: 12, background: C.blue,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontSize: 22, fontWeight: 700}}>{num}</div>}
        <span style={{fontSize: 52, fontWeight: 700, color: C.text}}>{text}</span>
      </div>
      <div style={{height: 3, width: `${interpolate(progress, [0,1], [0,100])}%`,
        background: `linear-gradient(90deg, ${C.green}, ${C.blue})`,
        borderRadius: 2, marginTop: 8, maxWidth: 400}} />
    </div>
  );
};

export const Card: React.FC<{children: React.ReactNode; delay?: number; style?: React.CSSProperties}> = ({children, delay = 0, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame, fps, delay, config: {damping: 200}, durationInFrames: Math.round(fps * 1.2)});

  return (
    <div style={{background: C.card, border: `1px solid ${C.border}`, borderRadius: 20,
      padding: 28, opacity: p, transform: `scale(${interpolate(p, [0,1], [0.9,1])})`,
      boxShadow: '0 4px 20px rgba(0,0,0,0.3)', ...style}}>
      {children}
    </div>
  );
};
```

## Render Command

```bash
BROWSER=none npx remotion render src/index.ts MyVideo out/video.mp4 \
  --codec h264 --concurrency 4 \
  --browser-executable /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome
```

First render without `--browser-executable` downloads Chrome Headless Shell (~90MB).
