import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { getVersion } from '@tauri-apps/api/app';
import { AppShell } from './components/AppShell';
import { SplashScreen } from './components/SplashScreen';
import { loadAppConfig, saveDarkMode } from './lib/config';
import { callBackend, isTauriRuntime } from './lib/backend';
import { resetRetestRuntimeSelection } from './modules/ai-testing/retestSessionStore';
import { aiTestingModule } from './modules/ai-testing/module';
import { dataProcessingModule } from './modules/data-processing/module';
import { documentProcessingModule } from './modules/document-processing/module';
import { emergencyHelpModule } from './modules/emergency-help/module';
import { informationGatheringModule } from './modules/information-gathering/module';

const SPLASH_DURATION_MS = 4500;
const SPLASH_EXIT_MS = 360;
const SHELL_PREMOUNT_DELAY_MS = 700;

type SplashPhase = 'running' | 'exiting' | 'done';

function syncDocumentTheme(darkMode: boolean) {
  const theme = darkMode ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  document.body.dataset.theme = theme;
  document.getElementById('root')?.setAttribute('data-theme', theme);
}

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [version, setVersion] = useState('3.1.3');
  const [splashPhase, setSplashPhase] = useState<SplashPhase>('running');
  const [shellPremounted, setShellPremounted] = useState(false);
  const splashCompleteRef = useRef(false);

  const modules = useMemo(
    () => [informationGatheringModule, dataProcessingModule, documentProcessingModule, aiTestingModule, emergencyHelpModule],
    [],
  );

  useLayoutEffect(() => {
    syncDocumentTheme(darkMode);
  }, [darkMode]);

  useEffect(() => {
    resetRetestRuntimeSelection();
    loadAppConfig().then((config) => {
      const savedDarkMode = config?.ui_settings?.dark_mode ?? config?.ui?.dark_mode;
      if (typeof savedDarkMode === 'boolean') {
        setDarkMode(savedDarkMode);
      }
    });
  }, []);

  useEffect(() => {
    if (!isTauriRuntime()) {
      return;
    }

    getVersion()
      .then((nextVersion) => {
        if (nextVersion) {
          setVersion(nextVersion);
        }
      })
      .catch(async () => {
        try {
          const data = await callBackend<{ version?: string }>('app.version');
          if (data.version) {
            setVersion(data.version);
          }
        } catch {
          // Keep the static preview fallback version.
        }
      });
  }, []);

  useEffect(() => {
    let frame = 0;
    let timer = 0;

    frame = window.requestAnimationFrame(() => {
      timer = window.setTimeout(() => setShellPremounted(true), SHELL_PREMOUNT_DELAY_MS);
    });

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
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
          <SplashScreen version={version} durationMs={SPLASH_DURATION_MS} onComplete={handleSplashComplete} />
        </div>
      ) : null}
    </div>
  );
}
