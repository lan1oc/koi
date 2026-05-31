import { useEffect, useState } from 'react';
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
  const [status, setStatus] = useState('就绪');

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light';
    setStatus(darkMode ? '已切换到暗黑模式' : '已切换到亮色模式');
  }, [darkMode]);

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
              setStatus(`已切换到${modules[index].title}`);
            }}
          />
          <div className="vertical-line" />
          <section className="content-stack">
            <ModuleContainer key={modules[activeModule].id} module={modules[activeModule]} darkMode={darkMode} />
          </section>
        </div>
        <div className="status-label">{status}</div>
      </section>
    </main>
  );
}
