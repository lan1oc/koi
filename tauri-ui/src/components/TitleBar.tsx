import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';

type TitleBarProps = {
  darkMode: boolean;
  version: string;
  onToggleTheme: () => void;
};

const isTauri = '__TAURI_INTERNALS__' in window;

export function TitleBar({ darkMode, version, onToggleTheme }: TitleBarProps) {
  const appWindow = isTauri ? getCurrentWindow() : null;
  const [maximized, setMaximized] = useState(false);

  const syncNativeWindowRegion = async () => {
    if (!isTauri) return undefined;
    try {
      return await invoke<boolean>('sync_window_region');
    } catch {
      return undefined;
    }
  };

  useEffect(() => {
    document.documentElement.dataset.windowMaximized = maximized ? 'true' : 'false';
    return () => {
      delete document.documentElement.dataset.windowMaximized;
    };
  }, [maximized]);

  useEffect(() => {
    if (!appWindow) return;

    let disposed = false;
    let unlistenResize: (() => void) | undefined;

    const syncMaximized = async () => {
      try {
        const nativeMaximized = await syncNativeWindowRegion();
        const nextMaximized = nativeMaximized ?? (await appWindow.isMaximized());
        if (!disposed) {
          setMaximized(nextMaximized);
        }
      } catch {
        if (!disposed) {
          setMaximized(false);
        }
      }
    };

    void syncMaximized();
    void appWindow.onResized(syncMaximized).then((unlisten) => {
      unlistenResize = unlisten;
    });

    return () => {
      disposed = true;
      unlistenResize?.();
    };
  }, [appWindow]);

  const toggleMaximized = async () => {
    if (!isTauri) return;
    const nextMaximized = await invoke<boolean>('toggle_app_maximize');
    setMaximized(nextMaximized);
  };

  return (
    <header className="title-section" data-tauri-drag-region>
      <div className="brand" data-tauri-drag-region>
        <img src="/icon.ico" alt="koi" className="brand-logo" draggable={false} />
        <div className="brand-copy" data-tauri-drag-region>
          <div className="brand-row" data-tauri-drag-region>
            <span className="brand-title">koi</span>
            <span className="brand-version">v{version}</span>
          </div>
          <span className="brand-subtitle">网络安全工具箱 | by lan1oc</span>
        </div>
      </div>
      <div className="window-controls">
        <button
          className="window-button"
          title={darkMode ? '切换到亮色模式' : '切换到暗黑模式'}
          aria-label={darkMode ? '切换到亮色模式' : '切换到暗黑模式'}
          onClick={onToggleTheme}
        >
          <span className={`window-icon theme-${darkMode ? 'light' : 'dark'}`} aria-hidden="true" />
        </button>
        <button className="window-button" title="最小化窗口" aria-label="最小化窗口" onClick={() => appWindow?.minimize()}>
          <span className="window-icon minimize" aria-hidden="true" />
        </button>
        <button
          className="window-button"
          title={maximized ? '还原窗口' : '最大化窗口'}
          aria-label={maximized ? '还原窗口' : '最大化窗口'}
          onClick={toggleMaximized}
        >
          <span className={`window-icon ${maximized ? 'restore' : 'maximize'}`} aria-hidden="true" />
        </button>
        <button className="window-button close" title="关闭程序" aria-label="关闭程序" onClick={() => appWindow?.close()}>
          <span className="window-icon close" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
