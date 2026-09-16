import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { getVersion } from '@tauri-apps/api/app';
import { listen } from '@tauri-apps/api/event';
import { AppShell } from './components/AppShell';
import { SplashScreen } from './components/SplashScreen';
import { loadAppConfig, saveDarkMode } from './lib/config';
import { callBackend, initializeRuntime, isTauriRuntime, type InitializationProgress } from './lib/backend';
import { resetRetestRuntimeSelection } from './modules/ai-testing/retestSessionStore';
import { aiTestingModule } from './modules/ai-testing/module';
import { dataProcessingModule } from './modules/data-processing/module';
import { documentProcessingModule } from './modules/document-processing/module';
import { emergencyHelpModule } from './modules/emergency-help/module';
import { informationGatheringModule } from './modules/information-gathering/module';

const SPLASH_EXIT_MS = 360;
const SPLASH_MIN_VISIBLE_MS = 2200;
const INITIALIZATION_PROGRESS_EVENT = 'koi-initialization-progress';

type SplashPhase = 'running' | 'exiting' | 'done';

function waitForMinimumSplash(startedAt: number) {
  const remaining = Math.max(0, SPLASH_MIN_VISIBLE_MS - (performance.now() - startedAt));
  return new Promise<void>((resolve) => window.setTimeout(resolve, remaining));
}

function syncDocumentTheme(darkMode: boolean) {
  const theme = darkMode ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  document.body.dataset.theme = theme;
  document.getElementById('root')?.setAttribute('data-theme', theme);
}

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [version, setVersion] = useState('4.0.0');
  const [bootProgress, setBootProgress] = useState(0);
  const [bootStatus, setBootStatus] = useState('Initializing runtime');
  const [bootError, setBootError] = useState<string | null>(null);
  const [splashPhase, setSplashPhase] = useState<SplashPhase>('running');
  const [shellPremounted, setShellPremounted] = useState(false);
  const splashCompleteRef = useRef(false);
  const splashStartedAtRef = useRef(performance.now());

  const modules = useMemo(
    () => [informationGatheringModule, dataProcessingModule, documentProcessingModule, aiTestingModule, emergencyHelpModule],
    [],
  );

  useLayoutEffect(() => {
    syncDocumentTheme(darkMode);
  }, [darkMode]);

  useEffect(() => {
    resetRetestRuntimeSelection();
    let cancelled = false;
    let stopListening: (() => void) | undefined;

    const boot = async () => {
      if (!isTauriRuntime()) {
        setBootStatus('Preview ready');
        setShellPremounted(true);
        setBootProgress(96);
        await waitForMinimumSplash(splashStartedAtRef.current);
        if (cancelled) return;
        setBootProgress(100);
        return;
      }

      try {
        stopListening = await listen<InitializationProgress>(INITIALIZATION_PROGRESS_EVENT, ({ payload }) => {
          if (cancelled) return;
          setBootProgress((current) => Math.max(current, Math.min(payload.percent, 96)));
          setBootStatus(payload.message);
          if (payload.error) setBootError(payload.error);
        });

        const runtime = await initializeRuntime();
        if (!runtime.ready) throw new Error('Runtime initialization did not reach ready state');

        const [config, nextVersion] = await Promise.all([
          loadAppConfig(),
          getVersion().catch(async () => (await callBackend<{ version?: string }>('app.version')).version ?? '4.0.0'),
        ]);
        if (cancelled) return;

        const savedDarkMode = config.ui_settings?.dark_mode ?? config.ui?.dark_mode;
        if (typeof savedDarkMode === 'boolean') setDarkMode(savedDarkMode);
        if (nextVersion) setVersion(nextVersion);
        setBootStatus('Finalizing interface');
        setShellPremounted(true);
        setBootProgress((current) => Math.max(current, 96));
        await waitForMinimumSplash(splashStartedAtRef.current);
        if (cancelled) return;
        setBootStatus('Runtime ready');
        setBootProgress(100);
      } catch (error) {
        if (!cancelled) {
          setBootError(error instanceof Error ? error.message : String(error));
          setBootStatus('Initialization failed');
        }
      }
    };

    void boot();
    return () => {
      cancelled = true;
      stopListening?.();
    };
  }, []);

  useEffect(() => {
    if (splashPhase !== 'exiting') {
      return;
    }

    const timer = window.setTimeout(() => setSplashPhase('done'), SPLASH_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [splashPhase]);

  const handleSplashComplete = useCallback(() => {
    if (splashCompleteRef.current) {
      return;
    }
    splashCompleteRef.current = true;
    setShellPremounted(true);
    setSplashPhase('exiting');
  }, []);

  const handleThemeToggle = () => {
    setDarkMode((current) => {
      const next = !current;
      saveDarkMode(next);
      return next;
    });
  };

  const showSplash = splashPhase !== 'done';
  const revealShell = splashPhase !== 'running';
  const mountShell = shellPremounted || revealShell;

  return (
    <div className='app-root-stage'>
      {mountShell ? (
        <div
          className={`app-shell-enter app-shell-preload${revealShell ? ' app-shell-revealed' : ''}${splashPhase === 'done' ? ' app-shell-interactive' : ''}`}
          aria-hidden={!revealShell}
          inert={splashPhase !== 'done'}
        >
          <AppShell
            backgroundActive={splashPhase === 'done'}
            darkMode={darkMode}
            modules={modules}
            version={version}
            onToggleTheme={handleThemeToggle}
          />
        </div>
      ) : null}
      {showSplash ? (
        <div className={`splash-overlay${splashPhase === 'exiting' ? ' splash-exiting' : ''}`}>
          <SplashScreen
            version={version}
            progress={bootProgress}
            status={bootStatus}
            error={bootError}
            minimumVisibleMs={SPLASH_MIN_VISIBLE_MS}
            onComplete={handleSplashComplete}
          />
        </div>
      ) : null}
    </div>
  );
}
