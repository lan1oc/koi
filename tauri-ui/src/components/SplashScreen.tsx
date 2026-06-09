import { useEffect, useState, type CSSProperties } from 'react';

type SplashScreenProps = {
  version: string;
  durationMs?: number;
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
  { className: 'wave-pink', percent: '98%', points: '0,22 8,24 16,22 24,25 32,20 40,21 48,14 56,20 64,18 72,27 80,26 88,22 96,20 104,24 112,19 120,17 128,20 136,25 144,18 152,19 160,22 168,20 176,17' },
  { className: 'wave-lime', percent: '83%', points: '0,25 8,23 16,26 24,20 32,22 40,17 48,24 56,21 64,26 72,16 80,21 88,19 96,17 104,25 112,20 120,22 128,18 136,24 144,18 152,16 160,22 168,19 176,23' },
  { className: 'wave-cyan', percent: '88%', points: '0,24 8,18 16,25 24,20 32,28 40,16 48,23 56,18 64,22 72,25 80,18 88,20 96,24 104,19 112,28 120,21 128,24 136,20 144,22 152,17 160,25 168,20 176,18' },
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

export function SplashScreen({ version, durationMs = 4500, onComplete }: SplashScreenProps) {
  const [progress, setProgress] = useState(0);
  const [canvasScale, setCanvasScale] = useState({ x: 1, y: 1 });
  const clampedProgress = Math.min(100, Math.max(0, progress));
  const roundedProgress = Math.round(clampedProgress);
  const progressStyle = {
    '--splash-progress-scale': `${clampedProgress / 100}`,
  } as CSSProperties;

  useEffect(() => {
    let frame = 0;
    const start = performance.now();

    const updateProgress = (now: number) => {
      const nextProgress = Math.min(100, ((now - start) / durationMs) * 100);
      setProgress(nextProgress);
      if (nextProgress < 100) {
        frame = window.requestAnimationFrame(updateProgress);
      } else {
        frame = window.requestAnimationFrame(() => onComplete?.());
      }
    };

    frame = window.requestAnimationFrame(updateProgress);
    return () => window.cancelAnimationFrame(frame);
  }, [durationMs, onComplete]);

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
            {waveLines.map((line) => (
              <div key={line.className} className="wave-row">
                <svg className={`wave-line ${line.className}`} viewBox="0 0 176 42" preserveAspectRatio="none">
                  <polyline points={line.points} />
                </svg>
                <span>{line.percent}</span>
              </div>
            ))}
          </div>
          <div className="stream-bars">
            {streamBars.map((bar) => (
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
          {bootLogs.map((log) => <span key={log}>{log}</span>)}
        </div>
      </section>
      </div>
      <div className="splash-scanline" />
    </main>
  );
}
