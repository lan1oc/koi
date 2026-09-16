import { useEffect, useState, type CSSProperties } from 'react';

type SplashScreenProps = {
  version: string;
  progress?: number;
  status?: string;
  error?: string | null;
  minimumVisibleMs?: number;
  onComplete?: () => void;
};

const hexRows = [
  '4B 4F 49 2F 43 4F 52 45',
  '40 4F 44 55 4C 45 2E 49',
  '4E 44 45 58 2F 53 59 4E',
  '43 2E 48 4F 4C 4F 43 52',
  '50 59 2F 54 52 45 41 4D',
  '4D 41 50 2E 4C 49 4E 4B',
  '43 4F 4E 4E 45 43 54 2E',
  '56 45 43 56 4F 52 2F 4C',
  '46 45 4B 2F 53 54 41 42',
  '4C 45 2F 50 52 4F 54 4F',
  '43 4F 4C 2E 4F 4E 4C 49',
  '4E 45 2F 53 59 53 54 4D',
];

const statusItems = [
  'CORE ONLINE',
  'BRIDGE LINK',
  'INDEX LOCK',
  'UI STREAM',
  'PROTOCOL',
  'MEMORY SYNC',
  'NEURAL MAP',
  'VECTOR AUTH',
];

const chips = [
  { label: 'SYNC', className: 'chip-top' },
  { label: 'NEXUS', className: 'chip-right' },
  { label: 'VAULT', className: 'chip-bottom' },
  { label: 'RADAR', className: 'chip-left' },
];

const rings = [
  'ring-outer',
  'ring-major',
  'ring-cyan',
  'ring-lime',
  'ring-magenta',
  'ring-inner',
];

const waveLines = [
  { className: 'wave-pink', percent: 94, points: [22, 24, 22, 25, 20, 21, 14, 20, 18, 27, 26, 22, 20, 24, 19, 17, 20, 25, 18, 19, 22, 20, 17] },
  { className: 'wave-lime', percent: 83, points: [25, 23, 26, 20, 22, 17, 24, 21, 26, 16, 21, 19, 17, 25, 20, 22, 18, 24, 18, 16, 22, 19, 23] },
  { className: 'wave-cyan', percent: 88, points: [24, 18, 25, 20, 28, 16, 23, 18, 22, 25, 18, 20, 24, 19, 28, 21, 24, 20, 22, 17, 25, 20, 18] },
];

const streamBars = [
  { value: 91, className: 'bar-long' },
  { value: 73, className: 'bar-cyan' },
  { value: 86, className: 'bar-lime' },
  { value: 64, className: 'bar-short' },
];

const bootLogs = ['> NEXUS.CORE [ONLINE]', '> VECTOR.INDEX [LOCKED]', '> BRIDGE.IO [STABLE]'];
const ticks = Array.from({ length: 96 }, (_, index) => index);
const particles = Array.from({ length: 34 }, (_, index) => index);
const PROGRESS_RATE_PER_SECOND = 48;
const PROGRESS_CATCHUP_RATE_PER_SECOND = 180;
const STREAM_REFRESH_MS = 100;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function animatedWave(line: (typeof waveLines)[number], lineIndex: number, time: number) {
  const points = line.points.map((baseY, pointIndex) => {
    const primary = Math.sin((time * 3.1) + (pointIndex * 0.82) + (lineIndex * 1.7)) * 2.8;
    const secondary = Math.sin((time * 1.7) - (pointIndex * 0.36) + lineIndex) * 1.4;
    return `${pointIndex * 8},${clamp(baseY + primary + secondary, 8, 34).toFixed(1)}`;
  }).join(' ');
  const percent = clamp(Math.round(
    line.percent
      + (Math.sin((time * 2.2) + (lineIndex * 1.4)) * 4)
      + (Math.sin((time * 0.9) - lineIndex) * 2),
  ), 58, 99);
  return { ...line, percent, points };
}

function animatedStreamBar(bar: (typeof streamBars)[number], barIndex: number, time: number) {
  const value = clamp(Math.round(
    bar.value
      + (Math.sin((time * 2.4) + (barIndex * 1.35)) * 7)
      + (Math.sin((time * 1.1) - barIndex) * 2),
  ), 48, 98);
  return { ...bar, value };
}

function tickStyle(index: number): CSSProperties {
  return { '--tick-angle': `${index * 3.75}deg` } as CSSProperties;
}

function particleStyle(index: number): CSSProperties {
  const x = 18 + ((index * 19) % 64);
  const y = 8 + ((index * 31) % 82);
  const delay = (index % 9) * 120;
  return {
    '--particle-x': `${x}%`,
    '--particle-y': `${y}%`,
    '--particle-delay': `${delay}ms`,
  } as CSSProperties;
}

export function SplashScreen({
  version,
  progress: requestedProgress = 0,
  status,
  error,
  minimumVisibleMs = 2200,
  onComplete,
}: SplashScreenProps) {
  const [progress, setProgress] = useState(requestedProgress);
  const [streamTime, setStreamTime] = useState(0);
  const [canvasScale, setCanvasScale] = useState({ x: 1, y: 1 });
  const [startedAt] = useState(() => performance.now());
  const clampedProgress = clamp(progress, 0, 100);
  const roundedProgress = clampedProgress >= 99.95 ? 100 : Math.floor(clampedProgress);
  const animatedWaveLines = waveLines.map((line, index) => animatedWave(line, index, streamTime));
  const animatedStreamBars = streamBars.map((bar, index) => animatedStreamBar(bar, index, streamTime));
  const progressStyle = {
    '--splash-progress-scale': `${clampedProgress / 100}`,
  } as CSSProperties;

  useEffect(() => {
    const target = clamp(requestedProgress, progress, 100);
    let previousTime = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsedSeconds = Math.max(0, now - previousTime) / 1000;
      previousTime = now;
      setProgress((current) => {
        if (current + 0.01 >= target) {
          window.clearInterval(timer);
          return target;
        }
        const rate = now - startedAt < minimumVisibleMs
          ? PROGRESS_RATE_PER_SECOND
          : PROGRESS_CATCHUP_RATE_PER_SECOND;
        const next = Math.min(target, current + (rate * elapsedSeconds));
        if (next + 0.01 >= target) window.clearInterval(timer);
        return next;
      });
    }, 16);
    return () => window.clearInterval(timer);
  }, [minimumVisibleMs, requestedProgress, startedAt]);

  useEffect(() => {
    if (!error && requestedProgress >= 100 && progress >= 99.95) {
      onComplete?.();
    }
  }, [error, onComplete, progress, requestedProgress]);

  useEffect(() => {
    const streamStartedAt = performance.now();
    const timer = window.setInterval(() => {
      setStreamTime((performance.now() - streamStartedAt) / 1000);
    }, STREAM_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const updateCanvasScale = () => {
      setCanvasScale({
        x: window.innerWidth / 1575,
        y: window.innerHeight / 998,
      });
    };

    updateCanvasScale();
    window.addEventListener('resize', updateCanvasScale);
    return () => window.removeEventListener('resize', updateCanvasScale);
  }, []);

  return (
    <main className="splash-window" aria-label="KOI loading">
      <div className="splash-grid" />
      <div className="splash-field" />
      <div className="splash-noise" />
      <div className="splash-canvas" style={{ transform: `translate(-50%, -50%) scale(${canvasScale.x}, ${canvasScale.y})` }}>
        <div className="splash-frame">
        <span className="corner top-left" />
        <span className="corner top-right" />
        <span className="corner bottom-left" />
        <span className="corner bottom-right" />
      </div>
      <div className="splash-topline"><span>NEURAL BOOT SEQUENCE</span><span>MODULE_SYNC: 100%</span></div>
      <div className="splash-bottomline" />
      <aside className="splash-hex-panel">
        {hexRows.map((row) => <span key={row}>{row}</span>)}
      </aside>
      <section className="splash-stage" aria-hidden="true">
        <div className="status-panel">
          {statusItems.map((item) => <span key={item}>{item}</span>)}
        </div>
        <div className="hud-center">
          <div className="hud-particles">
            {particles.map((particle) => <span key={particle} style={particleStyle(particle)} />)}
          </div>
          <div className="hud-lines">
            <span className="line-left" />
            <span className="line-right" />
            <span className="line-top" />
            <span className="line-bottom" />
          </div>
          <div className="hud-ticks">
            {ticks.map((tick) => <span key={tick} style={tickStyle(tick)} />)}
          </div>
          {rings.map((ring) => <span key={ring} className={`hud-ring ${ring}`} />)}
          {chips.map((chip) => <span key={chip.label} className={`hud-chip ${chip.className}`}>{chip.label}</span>)}
          <div className="koi-core">
            <div className="core-polygon" />
            <span className="core-orbit orbit-a" />
            <span className="core-orbit orbit-b" />
            <span className="logo-core">
              <img src="/icon.ico" alt="" draggable={false} />
            </span>
          </div>
        </div>
        <div className="stream-panel">
          <div className="stream-title"><span>STREAM ANALYSIS</span><span>_01</span></div>
          <div className="wave-stack">
            {animatedWaveLines.map((line) => (
              <div key={line.className} className="wave-row">
                <svg className={`wave-line ${line.className}`} viewBox="0 0 176 42" preserveAspectRatio="none">
                  <polyline points={line.points} />
                </svg>
                <span>{line.percent}%</span>
              </div>
            ))}
          </div>
          <div className="stream-bars">
            {animatedStreamBars.map((bar) => (
              <span key={bar.className} className={bar.className}>
                <i style={{ width: `${bar.value}%` }} />
                <em>{bar.value}%</em>
              </span>
            ))}
          </div>
        </div>
      </section>
      <section className="splash-loader">
        <h1>KOI</h1>
        <p>v{version}</p>
        <div className="splash-progress-row">
          <div className="splash-progress" style={progressStyle} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={roundedProgress}>
            <span className="splash-progress-fill" />
          </div>
          <strong className="splash-percent">{roundedProgress}%</strong>
        </div>
        <div className="splash-logs">
          {error ? <span>{error}</span> : bootLogs.map((log) => <span key={log}>{log}</span>)}
          {!error && status ? <span>{status}</span> : null}
        </div>
      </section>
      </div>
      <div className="splash-scanline" />
    </main>
  );
}
