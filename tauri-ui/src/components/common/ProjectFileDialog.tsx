import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { callBackend } from '../../lib/backend';
import type { DialogFilter, FileOrDirectoryMode } from '../../lib/file-dialog';

type FileEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  extension: string;
  size: number | null;
  size_text: string;
  modified: number | null;
  matches_filter: boolean;
};

type SortKey = 'name' | 'type' | 'size' | 'modified';
type SortDirection = 'asc' | 'desc';

type FsRootsResponse = {
  cwd: string;
  home: string;
  roots: Array<{ path: string; name: string; type: string }>;
  shortcuts: Array<{ path: string; name: string; type: string }>;
};

type FsListResponse = {
  path: string;
  parent: string | null;
  entries: FileEntry[];
  separator: string;
};

type BaseDialogOptions = {
  title: string;
  defaultPath?: string;
  filters?: DialogFilter[];
};

type ProjectDialogOptions = BaseDialogOptions & {
  mode: 'open' | 'save';
  target: FileOrDirectoryMode;
  multiple?: boolean;
};

type DialogState = ProjectDialogOptions & {
  resolver: (value: string | string[] | null) => void;
};

type ProjectFileDialogProps = {
  state: DialogState;
  onClose: (value: string | string[] | null) => void;
};

function formatTime(timestamp: number | null) {
  if (!timestamp) return '';
  return new Date(timestamp * 1000).toLocaleString();
}

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? '';
}

function parentFromPath(path: string) {
  const normalized = path.replace(/[\\/]+$/, '');
  const slashIndex = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'));
  if (slashIndex < 0) return '';
  if (slashIndex === 0) return normalized.slice(0, 1);
  return normalized.slice(0, slashIndex);
}

function getFilterExtensions(filter?: DialogFilter) {
  if (!filter) return [];
  if (filter.extensions.includes('*')) return [];
  return filter.extensions;
}

function matchesFilter(entry: FileEntry, filter?: DialogFilter) {
  if (entry.is_dir || !filter || filter.extensions.includes('*')) return true;
  return filter.extensions.map((item) => item.toLowerCase().replace(/^\./, '')).includes(entry.extension.toLowerCase());
}

function entryTypeText(entry: FileEntry) {
  return entry.is_dir ? '文件夹' : (entry.extension || '文件');
}

function compareEntries(a: FileEntry, b: FileEntry, sortKey: SortKey, sortDirection: SortDirection) {
  const direction = sortDirection === 'asc' ? 1 : -1;
  let result = 0;

  if (sortKey === 'name') {
    if (a.is_dir !== b.is_dir) {
      result = a.is_dir ? -1 : 1;
    } else {
      result = a.name.localeCompare(b.name, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
    }
  } else if (sortKey === 'type') {
    result = entryTypeText(a).localeCompare(entryTypeText(b), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
  } else if (sortKey === 'size') {
    result = (a.size ?? -1) - (b.size ?? -1);
  } else if (sortKey === 'modified') {
    result = (a.modified ?? 0) - (b.modified ?? 0);
  }

  if (result === 0 && sortKey !== 'name') {
    result = a.name.localeCompare(b.name, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
  }
  return result * direction;
}

function ProjectFileDialog({ state, onClose }: ProjectFileDialogProps) {
  const [roots, setRoots] = useState<FsRootsResponse | null>(null);
  const [listing, setListing] = useState<FsListResponse | null>(null);
  const [pathInput, setPathInput] = useState(state.defaultPath || '');
  const [selected, setSelected] = useState<string[]>([]);
  const [fileName, setFileName] = useState(state.mode === 'save' && state.defaultPath ? fileNameFromPath(state.defaultPath) : '');
  const [filterIndex, setFilterIndex] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [status, setStatus] = useState('正在加载项目文件管理器...');
  const [loading, setLoading] = useState(false);

  const currentFilter = state.filters?.[filterIndex];

  const loadDirectory = useCallback(async (path?: string, clearSelection = true, filter: DialogFilter | undefined = currentFilter) => {
    setLoading(true);
    setStatus('正在读取目录...');
    try {
      const result = await callBackend<FsListResponse>('fs.list_dir', {
        path: path || state.defaultPath || undefined,
        extensions: getFilterExtensions(filter),
      });
      setListing(result);
      setPathInput(result.path);
      if (clearSelection) {
        setSelected([]);
      }
      setStatus(`已加载 ${result.entries.length} 个项目`);
    } catch (error) {
      setStatus(`无法打开目录: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setLoading(false);
    }
  }, [currentFilter, state.defaultPath]);

  const initialDirectory = state.mode === 'save' && state.defaultPath ? parentFromPath(state.defaultPath) : state.defaultPath;

  useEffect(() => {
    const initialFilter = state.filters?.[0];
    callBackend<FsRootsResponse>('fs.roots')
      .then((result) => {
        setRoots(result);
        return loadDirectory(initialDirectory || result.home || result.cwd, true, initialFilter);
      })
      .catch((error) => setStatus(`项目文件管理器初始化失败: ${error instanceof Error ? error.message : String(error)}`));
    // 初始化只跑一次；文件类型变化时保留当前目录，由 filterIndex effect 刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (listing) {
      loadDirectory(listing.path, false, currentFilter);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterIndex]);

  const visibleEntries = useMemo(() => {
    const entries = listing?.entries ?? [];
    return entries
      .filter((entry) => matchesFilter(entry, currentFilter))
      .slice()
      .sort((a, b) => compareEntries(a, b, sortKey, sortDirection));
  }, [currentFilter, listing, sortDirection, sortKey]);

  const changeSort = (nextKey: SortKey) => {
    setSortKey((currentKey) => {
      if (currentKey === nextKey) {
        setSortDirection((currentDirection) => (currentDirection === 'asc' ? 'desc' : 'asc'));
        return currentKey;
      }
      setSortDirection(nextKey === 'modified' ? 'desc' : 'asc');
      return nextKey;
    });
  };

  const sortMark = (key: SortKey) => (sortKey === key ? (sortDirection === 'asc' ? ' ↑' : ' ↓') : '');

  const toggleSelection = (entry: FileEntry) => {
    if (!entry.is_dir && !matchesFilter(entry, currentFilter)) {
      setStatus('该文件不符合当前文件类型过滤条件');
      return;
    }
    if (state.target === 'directory' && !entry.is_dir) {
      setStatus('当前模式只能选择目录');
      return;
    }
    if (entry.is_dir && state.target === 'file') {
      setStatus('双击文件夹进入目录；当前模式需要选择文件');
      return;
    }
    setSelected((current) => {
      if (!state.multiple) return [entry.path];
      return current.includes(entry.path) ? current.filter((item) => item !== entry.path) : [...current, entry.path];
    });
    if (!entry.is_dir) setFileName(entry.name);
  };

  const openEntry = (entry: FileEntry) => {
    if (entry.is_dir) {
      loadDirectory(entry.path);
      return;
    }
    if (state.mode === 'open' && state.target !== 'directory' && matchesFilter(entry, currentFilter)) {
      onClose(entry.path);
    }
  };

  const confirmSelection = () => {
    if (state.mode === 'save') {
      const base = listing?.path || parentFromPath(pathInput) || roots?.home || '';
      const name = fileName.trim();
      if (!name) {
        setStatus('请输入要保存的文件名');
        return;
      }
      const separator = listing?.separator || (base.includes('\\') ? '\\' : '/');
      onClose(base.replace(/[\\/]+$/, '') + separator + name);
      return;
    }

    if (state.target === 'directory' && !selected.length && listing?.path) {
      onClose(listing.path);
      return;
    }

    if (!selected.length) {
      setStatus(state.target === 'directory' ? '请选择目录，或直接确认当前目录' : '请选择文件');
      return;
    }

    onClose(state.multiple ? selected : selected[0]);
  };

  const navigateInput = () => {
    if (!pathInput.trim()) {
      setStatus('请输入路径');
      return;
    }
    loadDirectory(pathInput.trim());
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => onClose(null)}>
      <section className="koi-modal wide project-file-dialog" role="dialog" aria-modal="true" aria-label={state.title} onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-title-row">
          <h3>{state.title}</h3>
          <button type="button" className="modal-close-button" aria-label="关闭" onClick={() => onClose(null)}>✕</button>
        </div>
        <div className="modal-separator" />

        <div className="project-file-toolbar">
          <button type="button" className="koi-button secondary compact-button" onClick={() => listing?.parent && loadDirectory(listing.parent)} disabled={!listing?.parent || loading}>⬆ 上一级</button>
          <input
            className="koi-input project-path-input"
            value={pathInput}
            onChange={(event) => setPathInput(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') navigateInput(); }}
            placeholder="输入路径后按 Enter 跳转"
          />
          <button type="button" className="koi-button secondary compact-button" onClick={navigateInput} disabled={loading}>跳转</button>
          <button type="button" className="koi-button secondary compact-button" onClick={() => loadDirectory(listing?.path)} disabled={loading}>刷新</button>
        </div>

        <div className="project-file-body">
          <aside className="project-file-sidebar">
            <div className="project-file-sidebar-title">常用位置</div>
            {roots?.shortcuts.map((item) => <button key={item.path} type="button" className="project-file-place" onClick={() => loadDirectory(item.path)}>{item.name}</button>)}
            <div className="project-file-sidebar-title">磁盘</div>
            {roots?.roots.map((item) => <button key={item.path} type="button" className="project-file-place" onClick={() => loadDirectory(item.path)}>{item.name}</button>)}
          </aside>

          <div className="project-file-list-panel">
            <div className="project-file-list-header">
              <button type="button" onClick={() => changeSort('name')}>名称{sortMark('name')}</button>
              <button type="button" onClick={() => changeSort('type')}>类型{sortMark('type')}</button>
              <button type="button" onClick={() => changeSort('size')}>大小{sortMark('size')}</button>
              <button type="button" onClick={() => changeSort('modified')}>修改时间{sortMark('modified')}</button>
            </div>
            <div className="project-file-list" aria-busy={loading}>
              {visibleEntries.length ? visibleEntries.map((entry) => {
                const selectedEntry = selected.includes(entry.path);
                const disabledByFilter = !entry.is_dir && !matchesFilter(entry, currentFilter);
                return (
                  <button
                    key={entry.path}
                    type="button"
                    className={`project-file-entry${selectedEntry ? ' selected' : ''}${disabledByFilter ? ' muted' : ''}`}
                    onClick={() => toggleSelection(entry)}
                    onDoubleClick={() => openEntry(entry)}
                    title={entry.path}
                  >
                    <span>{entry.is_dir ? '📁' : '📄'} {entry.name}</span>
                    <span>{entryTypeText(entry)}</span>
                    <span>{entry.size_text}</span>
                    <span>{formatTime(entry.modified)}</span>
                  </button>
                );
              }) : <div className="project-file-empty">目录为空或无匹配文件</div>}
            </div>
          </div>
        </div>

        <div className="project-file-footer">
          <div className="project-file-footer-fields">
            {state.mode === 'save' ? (
              <label className="project-file-inline-field">文件名:<input className="koi-input" value={fileName} onChange={(event) => setFileName(event.target.value)} /></label>
            ) : <div className="project-file-selected">已选择: {selected.length ? selected.join('; ') : (state.target === 'directory' ? listing?.path : '未选择')}</div>}
            {state.filters?.length ? (
              <label className="project-file-inline-field">文件类型:<select className="koi-input" value={filterIndex} onChange={(event) => setFilterIndex(Number(event.target.value))}>{state.filters.map((filter, index) => <option key={`${filter.name}-${index}`} value={index}>{filter.name} ({filter.extensions.join('; ')})</option>)}</select></label>
            ) : null}
            <div className="project-file-status">{status}</div>
          </div>
          <div className="modal-actions">
            <button type="button" className="koi-button primary" onClick={confirmSelection} disabled={loading}>{state.mode === 'save' ? '保存' : '打开'}</button>
            <button type="button" className="koi-button secondary" onClick={() => onClose(null)}>取消</button>
          </div>
        </div>
      </section>
    </div>
  );
}

export function useProjectFileDialog(): {
  dialog: ReactNode;
  openFilePath: (options: BaseDialogOptions) => Promise<string | null>;
  openFilePaths: (options: BaseDialogOptions) => Promise<string[]>;
  openDirectoryPath: (options: BaseDialogOptions) => Promise<string | null>;
  saveFilePath: (options: BaseDialogOptions) => Promise<string | null>;
  chooseFileOrDirectoryPath: (options: BaseDialogOptions & { mode: FileOrDirectoryMode }) => Promise<string | null>;
} {
  const [state, setState] = useState<DialogState | null>(null);

  const openProjectDialog = useCallback((options: ProjectDialogOptions) => new Promise<string | string[] | null>((resolve) => {
    setState({ ...options, resolver: resolve });
  }), []);

  const closeDialog = useCallback((value: string | string[] | null) => {
    setState((current) => {
      current?.resolver(value);
      return null;
    });
  }, []);

  return {
    dialog: state ? <ProjectFileDialog state={state} onClose={closeDialog} /> : null,
    openFilePath: async (options) => {
      const result = await openProjectDialog({ ...options, mode: 'open', target: 'file', multiple: false });
      return typeof result === 'string' ? result : null;
    },
    openFilePaths: async (options) => {
      const result = await openProjectDialog({ ...options, mode: 'open', target: 'file', multiple: true });
      return Array.isArray(result) ? result : (typeof result === 'string' ? [result] : []);
    },
    openDirectoryPath: async (options) => {
      const result = await openProjectDialog({ ...options, mode: 'open', target: 'directory', multiple: false });
      return typeof result === 'string' ? result : null;
    },
    saveFilePath: async (options) => {
      const result = await openProjectDialog({ ...options, mode: 'save', target: 'file', multiple: false });
      return typeof result === 'string' ? result : null;
    },
    chooseFileOrDirectoryPath: async (options) => {
      const result = await openProjectDialog({ ...options, mode: 'open', target: options.mode, multiple: false });
      return typeof result === 'string' ? result : null;
    },
  };
}
