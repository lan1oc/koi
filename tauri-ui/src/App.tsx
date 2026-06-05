import { useEffect, useMemo, useState } from 'react';
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

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [version, setVersion] = useState('3.1.0');
  const [showSplash, setShowSplash] = useState(true);

  const modules = useMemo(
    () => [informationGatheringModule, dataProcessingModule, documentProcessingModule, aiTestingModule, emergencyHelpModule],
    [],
  );

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
    const timer = window.setTimeout(() => setShowSplash(false), SPLASH_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, []);

  const handleThemeToggle = () => {
    setDarkMode((current) => {
      const next = !current;
      saveDarkMode(next);
      return next;
    });
  };

  if (showSplash) {
    return <SplashScreen version={version} durationMs={SPLASH_DURATION_MS} />;
  }

  return (
    <div className="app-shell-enter">
      <AppShell
        darkMode={darkMode}
        modules={modules}
        version={version}
        onToggleTheme={handleThemeToggle}
      />
    </div>
  );
}
