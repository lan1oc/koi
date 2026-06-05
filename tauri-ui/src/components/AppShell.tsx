import { useEffect, useState } from 'react';
import { KOI_NAVIGATE_EVENT, type KoiNavigationDetail } from '../lib/navigation-events';
import type { KoiModule } from '../lib/types';
import { AnimatedBackground } from './AnimatedBackground';
import { ModuleContainer } from './ModuleContainer';
import { Sidebar } from './Sidebar';
import { TitleBar } from './TitleBar';

type AppShellProps = {
  darkMode: boolean;
  modules: KoiModule[];
  version: string;
  onToggleTheme: () => void;
};

export function AppShell({ darkMode, modules, version, onToggleTheme }: AppShellProps) {
  const [activeModule, setActiveModule] = useState(0);
  const [activeFunctionIds, setActiveFunctionIds] = useState<Record<string, string | null>>({});
  const [status, setStatus] = useState('就绪');

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light';
    setStatus(darkMode ? '已切换到暗黑模式' : '已切换到亮色模式');
  }, [darkMode]);

  useEffect(() => {
    const handleNavigate = (event: Event) => {
      const detail = (event as CustomEvent<KoiNavigationDetail>).detail;
      if (!detail?.moduleId) return;
      const moduleIndex = modules.findIndex((item) => item.id === detail.moduleId);
      if (moduleIndex < 0) return;
      const targetModule = modules[moduleIndex];
      const targetFunction = detail.functionId
        ? targetModule.functions.find((item) => item.id === detail.functionId)
        : null;
      setActiveModule(moduleIndex);
      setActiveFunctionIds((current) => ({ ...current, [targetModule.id]: targetFunction?.id ?? null }));
      setStatus(targetFunction ? `已打开${targetModule.title} / ${targetFunction.title}` : `已切换到${targetModule.title}`);
    };
    window.addEventListener(KOI_NAVIGATE_EVENT, handleNavigate);
    return () => window.removeEventListener(KOI_NAVIGATE_EVENT, handleNavigate);
  }, [modules]);

  return (
    <main className="app-window">
      <AnimatedBackground darkMode={darkMode} />
      <section className="app-surface">
        <TitleBar darkMode={darkMode} version={version} onToggleTheme={onToggleTheme} />
        <div className="app-body">
          <Sidebar
            activeIndex={activeModule}
            darkMode={darkMode}
            modules={modules}
            onSelect={(index) => {
              setActiveModule(index);
              setActiveFunctionIds((current) => ({ ...current, [modules[index].id]: null }));
              setStatus(`已切换到${modules[index].title}`);
            }}
          />
          <div className="vertical-line" />
          <section className="content-stack">
            <ModuleContainer
              key={modules[activeModule].id}
              activeFunctionId={activeFunctionIds[modules[activeModule].id] ?? null}
              module={modules[activeModule]}
              darkMode={darkMode}
              onActiveFunctionIdChange={(functionId) => {
                const targetModule = modules[activeModule];
                setActiveFunctionIds((current) => ({ ...current, [targetModule.id]: functionId }));
              }}
            />
          </section>
        </div>
        <div className="status-label">{status}</div>
      </section>
    </main>
  );
}
