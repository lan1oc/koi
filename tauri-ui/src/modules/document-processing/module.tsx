import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend } from '../../lib/backend';
import type { FileOrDirectoryMode, DialogFilter } from '../../lib/file-dialog';
import { openBackendPath } from '../../lib/open-path';
import type { KoiModule } from '../../lib/types';

type TabItem = {
  id: string;
  title: string;
  content: ReactNode;
};

type SelectOption = string | { value: string; label: string };

type ConvertResponse = {
  success: boolean;
  message: string;
  converted?: number;
  skipped?: number;
  total?: number;
  failures?: Array<{ file: string; name?: string; reason: string }>;
  logs?: string[];
  output_files?: string[];
};

type PdfPreviewPage = {
  page_number: number;
  label: string;
  width?: number | null;
  height?: number | null;
  thumbnail?: string | null;
};

type PdfPreviewFile = {
  path: string;
  name: string;
  page_count: number;
  pages: PdfPreviewPage[];
};

type PdfPreviewResponse = {
  success: boolean;
  message: string;
  files: PdfPreviewFile[];
  failures?: Array<{ file: string; reason: string }>;
  total_pages?: number;
};

type PageSelection = {
  file_path: string;
  page_num: number;
  order: number;
};

type PdfExtractResponse = {
  success: boolean;
  message: string;
  output_file?: string;
  extracted?: number;
  total_pages?: number;
  merged_count?: number;
  file_count?: number;
  logs?: string[];
};

type NoticeProcessResponse = {
  success: boolean;
  message: string;
  progress?: number;
  running?: boolean;
  done?: boolean;
  task_id?: string;
  processed?: number;
  total_reports?: number;
  target_path?: string;
  generated_files?: string[];
  manual_files?: Array<{ file: string; reason?: string; output_file?: string; backup_file?: string }>;
  failures?: Array<{ file: string; reason: string }>;
  pdf_outputs?: string[];
  output_files?: string[];
  deleted_files?: string[];
  logs?: string[];
  error?: string;
  result?: NoticeProcessResponse;
};

type NoticeTaskStartResponse = Pick<NoticeProcessResponse, 'success' | 'message' | 'progress' | 'running' | 'done' | 'task_id' | 'processed' | 'total_reports' | 'logs'>;
type NoticeTaskStatusResponse = NoticeProcessResponse & { task_id: string; running: boolean; done: boolean };

type NoticeClassifyResponse = {
  success: boolean;
  message: string;
  logs?: string[];
  result?: {
    moved?: number;
    skipped_exist?: number;
    errors?: number;
    all_classified?: boolean;
    company_group_list?: Array<[string, string]>;
    unclassified?: string[];
  };
};

type RetestRunResponse = {
  success: boolean;
  message: string;
  processed?: number;
  manual_count?: number;
  reports?: string[];
  summary?: string;
  logs?: string[];
};

type AppConfigResponse = {
  report_counters?: {
    notification_number?: number | string;
    rectification_number?: number | string;
    unavailable_notification_numbers?: Array<number | string>;
    unavailable_rectification_numbers?: Array<number | string>;
  };
};

function TabWidget({ tabs }: { tabs: TabItem[] }) {
  const [activeTab, setActiveTab] = useState(tabs[0]?.id ?? '');
  const activeContent = tabs.find((tab) => tab.id === activeTab)?.content ?? tabs[0]?.content;

  return (
    <div className="koi-tab-widget nested-tab-widget">
      <div className="tab-bar">
        {tabs.map((tab) => (
          <button key={tab.id} type="button" className={`tab-button${tab.id === activeTab ? ' active' : ''}`} onClick={() => setActiveTab(tab.id)}>
            {tab.title}
          </button>
        ))}
      </div>
      <div className="tab-content">{activeContent}</div>
    </div>
  );
}

function TextInput({ placeholder, readOnly = false, value, onChange }: { placeholder: string; readOnly?: boolean; value?: string; onChange?: (value: string) => void }) {
  return <input className="koi-input" placeholder={placeholder} readOnly={readOnly} value={value} onChange={(event) => onChange?.(event.target.value)} />;
}

function SelectInput({ options, value, defaultValue, onChange }: { options: SelectOption[]; value?: string; defaultValue?: string; onChange?: (value: string) => void }) {
  return (
    <select className="koi-input" value={value} defaultValue={value === undefined ? defaultValue : undefined} onChange={(event) => onChange?.(event.target.value)}>
      {options.map((option) => {
        const item = typeof option === 'string' ? { value: option, label: option } : option;
        return <option key={item.value} value={item.value}>{item.label}</option>;
      })}
    </select>
  );
}

function FileRow({
  placeholder,
  buttonText,
  readOnly = true,
  title,
  mode = 'file',
  multiple = false,
  filters,
  value,
  onChange,
  onSelected,
}: {
  placeholder: string;
  buttonText: string;
  readOnly?: boolean;
  title?: string;
  mode?: FileOrDirectoryMode | 'save';
  multiple?: boolean;
  filters?: DialogFilter[];
  value?: string;
  onChange?: (value: string) => void;
  onSelected?: (selection: string | string[]) => void;
}) {
  const [internalPath, setInternalPath] = useState('');
  const path = value ?? internalPath;
  const { dialog: fileDialog, openFilePath, openFilePaths, openDirectoryPath, saveFilePath, chooseFileOrDirectoryPath } = useProjectFileDialog();

  const setPath = (nextPath: string) => {
    if (value === undefined) {
      setInternalPath(nextPath);
    }
    onChange?.(nextPath);
  };

  const choosePath = async () => {
    const options = {
      title: title ?? buttonText.replace(/^[^\s]+\s*/, ''),
      defaultPath: path,
      filters,
    };

    if (mode === 'save') {
      const selected = await saveFilePath(options);
      if (selected) {
        setPath(selected);
        onSelected?.(selected);
      }
      return;
    }

    if (multiple) {
      const selected = await openFilePaths(options);
      if (selected.length) {
        setPath(selected.join('; '));
        onSelected?.(selected);
      }
      return;
    }

    const selected = mode === 'directory'
      ? await openDirectoryPath(options)
      : mode === 'file-or-directory'
        ? await chooseFileOrDirectoryPath({ ...options, mode: 'file-or-directory' })
        : await openFilePath(options);
    if (selected) {
      setPath(selected);
      onSelected?.(selected);
    }
  };

  return (
    <div className="file-selector-row wide-file-row">
      <TextInput placeholder={placeholder} readOnly={readOnly} value={path} onChange={setPath} />
      <button type="button" className="koi-button secondary compact-button" onClick={choosePath}>{buttonText}</button>
      {fileDialog}
    </div>
  );
}

function ProgressBox({
  title,
  status = '等待开始...',
  progress = 0,
  log = '',
}: {
  title: string;
  status?: string;
  progress?: number;
  log?: string;
}) {
  const normalizedProgress = Math.max(0, Math.min(100, progress));
  return (
    <fieldset className="koi-group progress-group-box">
      <legend>{title}</legend>
      <div className="doc-status-label">{status}</div>
      <div className="progress-shell visible-progress"><div className="progress-fill" style={{ width: `${normalizedProgress}%` }} /><span>{normalizedProgress}%</span></div>
      <textarea className="result-textarea doc-log-text" readOnly placeholder="等待开始处理..." value={log} />
    </fieldset>
  );
}

function getFileName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function uniquePaths(paths: string[]) {
  return Array.from(new Set(paths.map((path) => path.trim()).filter(Boolean)));
}

function splitKeywords(text: string) {
  return text.split(',').map((item) => item.trim()).filter(Boolean);
}

function compactPageRanges(pageNumbers: number[]) {
  const pages = Array.from(new Set(pageNumbers)).sort((a, b) => a - b);
  if (!pages.length) return '';
  const ranges: string[] = [];
  let start = pages[0];
  let end = pages[0];

  pages.slice(1).forEach((page) => {
    if (page === end + 1) {
      end = page;
      return;
    }
    ranges.push(start === end ? String(start) : `${start}-${end}`);
    start = page;
    end = page;
  });
  ranges.push(start === end ? String(start) : `${start}-${end}`);
  return ranges.join(',');
}

function selectionRangeText(selections: PageSelection[], previewFiles: PdfPreviewFile[]) {
  if (!selections.length) return '';
  const fileNames = new Map(previewFiles.map((file) => [file.path, file.name]));
  const grouped = new Map<string, number[]>();
  selections.forEach((selection) => {
    grouped.set(selection.file_path, [...(grouped.get(selection.file_path) ?? []), selection.page_num]);
  });

  if (grouped.size === 1) {
    return compactPageRanges(Array.from(grouped.values())[0] ?? []);
  }

  return Array.from(grouped.entries()).map(([filePath, pages]) => `${fileNames.get(filePath) ?? getFileName(filePath)}: ${compactPageRanges(pages)}`).join(' | ');
}

function formatConversionLog(result: ConvertResponse) {
  return [
    ...(result.logs ?? []),
    ...(result.failures ?? []).map((failure) => `失败: ${failure.name ?? getFileName(failure.file)} -> ${failure.reason}`),
    result.output_files?.length ? '' : undefined,
    ...(result.output_files?.length ? ['输出文件:', ...result.output_files] : []),
  ].filter((line): line is string => typeof line === 'string').join('\n');
}

function formatPdfLog(result: PdfExtractResponse) {
  return [
    ...(result.logs ?? []),
    result.output_file ? '' : undefined,
    result.output_file ? `输出文件: ${result.output_file}` : undefined,
  ].filter((line): line is string => typeof line === 'string').join('\n');
}

function joinLogs(logs?: string[]) {
  return (logs ?? []).filter(Boolean).join('\n');
}

function numberListText(value?: Array<number | string>) {
  return (value ?? [])
    .map((item) => String(item).trim())
    .filter(Boolean)
    .join(',');
}

function formatNoticeManualFiles(files?: NoticeProcessResponse['manual_files']) {
  if (!files?.length) return '';
  return files.map((item, index) => {
    const file = item.output_file || item.file;
    return `${index + 1}. ${file}${item.reason ? `\n   原因: ${item.reason}` : ''}${item.backup_file ? `\n   备份: ${item.backup_file}` : ''}`;
  }).join('\n');
}

function formatPathList(paths?: string[]) {
  return (paths ?? []).map((path, index) => `${index + 1}. ${path}`).join('\n');
}

function NoticePathList({
  title,
  paths,
  emptyText,
  onOpen,
}: {
  title: string;
  paths: string[];
  emptyText: string;
  onOpen: (path: string) => void;
}) {
  return (
    <fieldset className="koi-group notice-list-card">
      <legend>{title}</legend>
      <div className="qt-list-widget notice-path-list">
        {paths.length ? paths.map((path, index) => (
          <div key={`${path}-${index}`} className="qt-list-item notice-path-item">
            <div>
              <strong>{getFileName(path)}</strong>
              <div className="template-item-meta">{path}</div>
            </div>
            <button type="button" className="koi-button secondary compact-button" onClick={() => onOpen(path)}>打开</button>
          </div>
        )) : <div className="empty-list-hint">{emptyText}</div>}
      </div>
    </fieldset>
  );
}

function NoticeManualList({
  files,
  onOpen,
  onRemove,
}: {
  files: NonNullable<NoticeProcessResponse['manual_files']>;
  onOpen: (path: string) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="qt-list-widget notice-path-list">
      {files.length ? files.map((item, index) => {
        const filePath = item.output_file || item.file;
        return (
          <div key={`${filePath}-${index}`} className="qt-list-item notice-path-item notice-manual-item">
            <div>
              <strong>{getFileName(filePath)}</strong>
              <div className="template-item-meta">{filePath}</div>
              {item.reason ? <div className="notice-item-reason">原因: {item.reason}</div> : null}
              {item.backup_file ? <div className="template-item-meta">备份: {item.backup_file}</div> : null}
            </div>
            <div className="notice-item-actions">
              <button type="button" className="koi-button secondary compact-button" onClick={() => onOpen(filePath)}>打开</button>
              {item.backup_file ? <button type="button" className="koi-button secondary compact-button" onClick={() => onOpen(item.backup_file ?? '')}>备份</button> : null}
              <button type="button" className="koi-button danger compact-button" onClick={() => onRemove(index)}>移除</button>
            </div>
          </div>
        );
      }) : <div className="empty-list-hint">暂无编辑失败的文档</div>}
    </div>
  );
}

function DocumentConversionPage() {
  const [conversionType, setConversionType] = useState('word_to_pdf');
  const [inputPath, setInputPath] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [lastOutputPath, setLastOutputPath] = useState('');
  const [recursive, setRecursive] = useState(true);
  const [overwrite, setOverwrite] = useState(true);
  const [skipTemplate, setSkipTemplate] = useState(true);
  const [skipKeywords, setSkipKeywords] = useState('');
  const [status, setStatus] = useState('等待开始转换...');
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const isWordToPdf = conversionType === 'word_to_pdf';

  const inputFilters = isWordToPdf
    ? [{ name: 'Word文件', extensions: ['doc', 'docx'] }, { name: '所有文件', extensions: ['*'] }]
    : [{ name: 'PDF文件', extensions: ['pdf'] }, { name: '所有文件', extensions: ['*'] }];

  const startConversion = async () => {
    if (!inputPath.trim()) {
      setStatus('请选择输入路径');
      return;
    }

    setIsBusy(true);
    setProgress(15);
    setStatus(`正在准备${isWordToPdf ? 'Word转PDF' : 'PDF转Word'}...`);
    setLog('');
    try {
      const result = await callBackend<ConvertResponse>('doc.convert.run', {
        conversion_type: conversionType,
        input_path: inputPath.trim(),
        output_dir: outputDir.trim(),
        recursive,
        overwrite,
        skip_template: skipTemplate,
        skip_keywords: splitKeywords(skipKeywords),
      });
      setProgress(100);
      setStatus(result.message || (result.success ? '转换完成' : '转换失败'));
      setLastOutputPath(result.output_files?.[0] ?? outputDir.trim() ?? inputPath.trim());
      setLog(formatConversionLog(result));
    } catch (error) {
      setProgress(0);
      setStatus(`转换失败: ${error instanceof Error ? error.message : String(error)}`);
      setLog('');
    } finally {
      setIsBusy(false);
    }
  };

  const changeConversionType = (nextType: string) => {
    setConversionType(nextType);
      setInputPath('');
      setLastOutputPath('');
    setProgress(0);
    setStatus(nextType === 'word_to_pdf' ? '等待开始Word转PDF...' : '等待开始PDF转Word...');
    setLog('');
  };

  return (
    <div className="vertical-detail scroll-page-layout document-conversion-page">
      <fieldset className="koi-group">
        <legend>🔄 转换类型</legend>
        <label className="field-row horizontal-field"><span>转换方向:</span><SelectInput options={[{ value: 'word_to_pdf', label: 'Word转PDF' }, { value: 'pdf_to_word', label: 'PDF转Word' }]} value={conversionType} onChange={changeConversionType} /></label>
      </fieldset>

      <fieldset className="koi-group">
        <legend>输入设置</legend>
        <label className="field-row"><span>输入路径:</span><FileRow placeholder={isWordToPdf ? '选择Word文件或文件夹' : '选择PDF文件或文件夹'} buttonText="📁 浏览..." title={isWordToPdf ? '选择Word文件或文件夹' : '选择PDF文件或文件夹'} mode="file-or-directory" filters={inputFilters} value={inputPath} onChange={setInputPath} /></label>
        <label className="field-row"><span>输出目录:</span><FileRow placeholder="输出目录（可选，默认与源文件同目录）" buttonText="📂 浏览..." title="选择输出目录" mode="directory" value={outputDir} onChange={setOutputDir} /></label>
      </fieldset>

      <fieldset className="koi-group">
        <legend>⚙️ 转换选项</legend>
        {isWordToPdf && <label className="checkbox-row"><input type="checkbox" checked={recursive} onChange={(event) => setRecursive(event.target.checked)} /> 递归搜索子目录</label>}
        <label className="checkbox-row"><input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} /> {isWordToPdf ? '覆盖已存在的PDF文件' : '覆盖已存在的Word文件'}</label>
        {isWordToPdf && <label className="checkbox-row"><input type="checkbox" checked={skipTemplate} onChange={(event) => setSkipTemplate(event.target.checked)} /> 跳过模板文件</label>}
        {isWordToPdf && <label className="field-row horizontal-field"><span>跳过关键词:</span><TextInput placeholder="用逗号分隔多个关键词" value={skipKeywords} onChange={setSkipKeywords} /></label>}
      </fieldset>

      <div className="action-row"><button type="button" className="koi-button primary full-width-button tall-action-button" onClick={startConversion} disabled={isBusy}>🚀 开始转换</button><button type="button" className="koi-button secondary compact-button" onClick={() => openBackendPath(lastOutputPath || outputDir || inputPath, setStatus)} disabled={isBusy || !(lastOutputPath || outputDir || inputPath)}>📂 打开输出</button></div>
      <ProgressBox title="📊 转换进度" status={status} progress={progress} log={log} />
    </div>
  );
}

function PdfExtractPage() {
  const [pdfFiles, setPdfFiles] = useState<string[]>([]);
  const [previewFiles, setPreviewFiles] = useState<PdfPreviewFile[]>([]);
  const [selectedPages, setSelectedPages] = useState<PageSelection[]>([]);
  const [pageRanges, setPageRanges] = useState('');
  const [outputFile, setOutputFile] = useState('');
  const [lastOutputPath, setLastOutputPath] = useState('');
  const [status, setStatus] = useState("请选择PDF文件并点击'加载预览'");
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const { dialog: fileDialog, openFilePaths, saveFilePath } = useProjectFileDialog();

  const pdfSummary = useMemo(() => {
    if (!pdfFiles.length) return '';
    const names = pdfFiles.map(getFileName);
    return `已选择 ${pdfFiles.length} 个文件: ${names.slice(0, 3).join(', ')}${names.length > 3 ? '...' : ''}`;
  }, [pdfFiles]);

  const totalPreviewPages = useMemo(() => previewFiles.reduce((sum, file) => sum + file.page_count, 0), [previewFiles]);

  const choosePdfFiles = async (mode: 'replace' | 'append') => {
    const selected = await openFilePaths({
      title: mode === 'replace' ? '选择PDF文件' : '添加PDF文件',
      filters: [
        { name: 'PDF文件', extensions: ['pdf'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected.length) return;

    const nextFiles = mode === 'replace' ? uniquePaths(selected) : uniquePaths([...pdfFiles, ...selected]);
    setPdfFiles(nextFiles);
    setPreviewFiles([]);
    setSelectedPages([]);
    setPageRanges('');
    setProgress(0);
    setStatus(`已选择 ${nextFiles.length} 个PDF文件`);
    setLog('');
  };

  const removePdfFile = (filePath: string) => {
    setPdfFiles((current) => current.filter((file) => file !== filePath));
    const nextPreview = previewFiles.filter((file) => file.path !== filePath);
    const nextSelected = selectedPages.filter((selection) => selection.file_path !== filePath);
    setPreviewFiles(nextPreview);
    setSelectedPages(nextSelected);
    setPageRanges(selectionRangeText(nextSelected, nextPreview));
    setStatus('已移除文件');
  };

  const loadPreview = async () => {
    if (!pdfFiles.length) {
      setStatus('请先选择PDF文件');
      return;
    }

    setIsBusy(true);
    setProgress(20);
    setStatus(`正在加载 ${pdfFiles.length} 个文件的预览...`);
    setLog('');
    try {
      const result = await callBackend<PdfPreviewResponse>('doc.pdf_extract.preview', {
        pdf_files: pdfFiles,
        include_thumbnails: true,
        thumbnail_limit: 120,
      });
      setPreviewFiles(result.files ?? []);
      setSelectedPages([]);
      setPageRanges('');
      setProgress(result.files?.length ? 100 : 0);
      setStatus(result.message || (result.success ? '预览加载完成' : '预览加载失败'));
      setLog([
        ...(result.failures ?? []).map((failure) => `失败: ${getFileName(failure.file)} -> ${failure.reason}`),
        result.total_pages ? `总页数: ${result.total_pages}` : undefined,
      ].filter((line): line is string => typeof line === 'string').join('\n'));
    } catch (error) {
      setProgress(0);
      setStatus(`预览加载失败: ${error instanceof Error ? error.message : String(error)}`);
      setPreviewFiles([]);
      setSelectedPages([]);
      setPageRanges('');
    } finally {
      setIsBusy(false);
    }
  };

  const clearPreview = () => {
    setPreviewFiles([]);
    setSelectedPages([]);
    setPageRanges('');
    setProgress(0);
    setStatus("请选择PDF文件并点击'加载预览'");
    setLog('');
  };

  const togglePageSelection = (filePath: string, pageNumber: number) => {
    setSelectedPages((current) => {
      const existingIndex = current.findIndex((selection) => selection.file_path === filePath && selection.page_num === pageNumber);
      const next = existingIndex >= 0
        ? current.filter((_, index) => index !== existingIndex)
        : [...current, { file_path: filePath, page_num: pageNumber, order: current.reduce((max, item) => Math.max(max, item.order), 0) + 1 }];
      setPageRanges(selectionRangeText(next, previewFiles));
      return next;
    });
  };

  const selectAllPages = () => {
    const selections = previewFiles.flatMap((file) => file.pages.map((page) => ({
      file_path: file.path,
      page_num: page.page_number,
      order: 0,
    }))).map((selection, index) => ({ ...selection, order: index + 1 }));
    setSelectedPages(selections);
    setPageRanges(selectionRangeText(selections, previewFiles));
  };

  const clearPageSelection = () => {
    setSelectedPages([]);
    setPageRanges('');
  };

  const chooseOutputFile = async () => {
    const selected = await saveFilePath({
      title: '保存输出PDF文件',
      defaultPath: outputFile,
      filters: [
        { name: 'PDF文件', extensions: ['pdf'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (selected) {
      setOutputFile(selected);
    }
  };

  const isPageSelected = (filePath: string, pageNumber: number) => selectedPages.some((selection) => selection.file_path === filePath && selection.page_num === pageNumber);

  const startExtraction = async () => {
    if (!pdfFiles.length) {
      setStatus('请先选择PDF文件');
      return;
    }

    let requestSelections = selectedPages;
    let requestRanges = pageRanges.trim();
    const singleFileSelection = selectedPages.length > 0 && pdfFiles.length === 1 && selectedPages.every((selection) => selection.file_path === pdfFiles[0]);
    if (singleFileSelection) {
      requestRanges = compactPageRanges(selectedPages.map((selection) => selection.page_num));
      requestSelections = [];
    }

    if (!requestSelections.length && !requestRanges) {
      setStatus('请输入页码范围，或加载预览后选择页面');
      return;
    }
    if (pdfFiles.length > 1 && !requestSelections.length) {
      setStatus('多文件提取请先加载预览并选择页面，或点击全选');
      return;
    }

    setIsBusy(true);
    setProgress(25);
    setStatus('正在提取PDF页面...');
    setLog('');
    try {
      const result = await callBackend<PdfExtractResponse>('doc.pdf_extract.run', {
        pdf_files: pdfFiles,
        page_ranges: requestRanges,
        output_file: outputFile.trim(),
        page_selections: requestSelections,
      });
      setProgress(100);
      setStatus(result.message || (result.success ? '提取完成' : '提取失败'));
      setOutputFile(result.output_file ?? outputFile);
      setLastOutputPath(result.output_file ?? outputFile);
      setLog(formatPdfLog(result));
    } catch (error) {
      setProgress(0);
      setStatus(`提取失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="pdf-extract-layout scroll-page-layout">
      <section className="pdf-control-panel">
        <div className="pdf-control-scroll">
          <div className="section-title-label">输入设置</div>
          <div className="field-row">
            <span className="bold-label">PDF文件:</span>
            <div className="file-selector-row wide-file-row">
              <TextInput placeholder="选择要提取的PDF文件（可多选）" readOnly value={pdfSummary} />
              <button type="button" className="koi-button secondary compact-button" onClick={() => choosePdfFiles('replace')} disabled={isBusy}>📄 浏览...</button>
            </div>
            <button type="button" className="koi-button secondary compact-button" onClick={() => choosePdfFiles('append')} disabled={isBusy}>➕ 添加文件</button>
          </div>
          <div className="field-row">
            <span>已选文件列表:</span>
            <div className="qt-list-widget doc-file-list">
              {pdfFiles.length ? pdfFiles.map((filePath) => (
                <button key={filePath} type="button" className="qt-list-item selectable-list-item" title="双击移除文件" onDoubleClick={() => removePdfFile(filePath)}>
                  📄 {getFileName(filePath)}
                  <div className="template-item-meta">{filePath}</div>
                </button>
              )) : <div className="empty-list-hint">双击移除文件</div>}
            </div>
          </div>
          <div className="action-row"><button type="button" className="koi-button secondary compact-button" onClick={loadPreview} disabled={isBusy || !pdfFiles.length}>👁️ 加载预览</button><button type="button" className="koi-button danger compact-button" onClick={clearPreview} disabled={isBusy || !previewFiles.length}>🗑️ 清除预览</button></div>
          <div className="horizontal-separator" />
          <label className="field-row"><span className="bold-label">页码范围:</span><TextInput placeholder="例如: 2-6,9,11-12 或点击预览页面选择" value={pageRanges} onChange={(value) => { setPageRanges(value); setSelectedPages([]); }} /></label>
          <div className="action-row"><button type="button" className="koi-button secondary compact-button" onClick={selectAllPages} disabled={!totalPreviewPages}>☑️ 全选</button><button type="button" className="koi-button secondary compact-button" onClick={clearPageSelection} disabled={!selectedPages.length}>⬜ 清除选择</button></div>
          <div className="horizontal-separator" />
          <label className="field-row">
            <span className="bold-label">输出文件:</span>
            <div className="file-selector-row wide-file-row">
              <TextInput placeholder="输出PDF文件路径（可选，默认保存到源文件目录）" value={outputFile} onChange={setOutputFile} />
              <button type="button" className="koi-button secondary compact-button" onClick={chooseOutputFile}>📁 浏览...</button>
            </div>
          </label>
        </div>
        <div className="action-row"><button type="button" className="koi-button primary full-width-button tall-action-button" onClick={startExtraction} disabled={isBusy}>开始提取</button><button type="button" className="koi-button secondary compact-button" onClick={() => openBackendPath(lastOutputPath || outputFile, setStatus)} disabled={isBusy || !(lastOutputPath || outputFile)}>📂 打开输出</button></div>
        <ProgressBox title="处理进度" status={status} progress={progress} log={log} />
        {fileDialog}
      </section>

      <section className="pdf-preview-panel">
        <h3>PDF预览</h3>
        <div className="preview-status">{previewFiles.length ? `预览已加载，共 ${totalPreviewPages} 页，已选择 ${selectedPages.length} 页` : status}</div>
        <div className="pdf-preview-area">
          {previewFiles.length ? (
            <div className="pdf-preview-grid">
              {previewFiles.map((file) => (
                <div key={file.path} className="pdf-preview-file-group">
                  <div className="pdf-preview-file-title">📄 {file.name} · {file.page_count} 页</div>
                  <div className="pdf-page-grid">
                    {file.pages.map((page) => (
                      <button key={`${file.path}-${page.page_number}`} type="button" className={`pdf-page-tile${isPageSelected(file.path, page.page_number) ? ' selected' : ''}`} onClick={() => togglePageSelection(file.path, page.page_number)}>
                        <div className="pdf-page-thumbnail-frame">
                          {page.thumbnail ? <img className="pdf-page-thumbnail" src={page.thumbnail} alt={`第 ${page.page_number} 页预览`} loading="lazy" /> : <span className="pdf-page-thumbnail-fallback">PDF</span>}
                        </div>
                        <strong>第 {page.page_number} 页</strong>
                        <span>{isPageSelected(file.path, page.page_number) ? '已选择' : '点击选择'}</span>
                        {page.width && page.height ? <small>{Math.round(page.width)} × {Math.round(page.height)}</small> : null}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="empty-list-hint">PDF 页面预览将在这里显示，可点击选择页面</div>}
        </div>
      </section>
    </div>
  );
}

function NoticeToolsPage() {
  const [targetPath, setTargetPath] = useState('');
  const [noticeNumber, setNoticeNumber] = useState('');
  const [rectificationNumber, setRectificationNumber] = useState('');
  const [unavailableType, setUnavailableType] = useState('通报');
  const [unavailableNumbers, setUnavailableNumbers] = useState('');
  const [autoGroup, setAutoGroup] = useState(true);
  const [status, setStatus] = useState('等待选择路径...');
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState('');
  const [manualFiles, setManualFiles] = useState<NoticeProcessResponse['manual_files']>([]);
  const [generatedFiles, setGeneratedFiles] = useState<string[]>([]);
  const [pdfOutputs, setPdfOutputs] = useState<string[]>([]);
  const [lastOutputPath, setLastOutputPath] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const loadReportCounters = async (showStatus = false) => {
    try {
      const config = await callBackend<AppConfigResponse>('config.load', {});
      const counters = config.report_counters ?? {};
      setNoticeNumber(String(counters.notification_number ?? 1));
      setRectificationNumber(String(counters.rectification_number ?? 1));
      setUnavailableNumbers(numberListText(
        unavailableType === '责令整改'
          ? counters.unavailable_rectification_numbers
          : counters.unavailable_notification_numbers,
      ));
      if (showStatus) {
        setStatus('编号配置已从配置文件刷新');
      }
    } catch (error) {
      if (showStatus) {
        setStatus(`读取编号配置失败: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  };

  useEffect(() => {
    void loadReportCounters();
  }, []);

  const openNoticePath = (path: string) => {
    void openBackendPath(path, setStatus);
  };

  const removeManualFile = (index: number) => {
    setManualFiles((current) => (current ?? []).filter((_, itemIndex) => itemIndex !== index));
  };

  const startProcess = async (useAutoGroup = autoGroup) => {
    if (!targetPath.trim()) {
      setStatus('请先选择文件夹或ZIP压缩包');
      return;
    }
    const payload = {
      target_path: targetPath.trim(),
      auto_group: useAutoGroup,
      notice_number: noticeNumber,
      rectification_number: rectificationNumber,
      unavailable_type: unavailableType,
      unavailable_numbers: unavailableNumbers,
    };
    setIsBusy(true);
    setProgress(1);
    setStatus('正在启动通报处理任务...');
    setLog('');
    try {
      const startResult = await callBackend<NoticeTaskStartResponse>('doc.notice.process.start', payload);
      if (!startResult.success || !startResult.task_id) {
        setProgress(0);
        setStatus(startResult.message || '任务启动失败');
        setLog(joinLogs(startResult.logs));
        return;
      }

      let latest: NoticeTaskStatusResponse | null = null;
      while (true) {
        const statusResult = await callBackend<NoticeTaskStatusResponse>('doc.notice.process.status', { task_id: startResult.task_id });
        latest = statusResult;
        setProgress(statusResult.progress ?? 0);
        const counter = statusResult.total_reports ? ` (${statusResult.processed ?? 0}/${statusResult.total_reports})` : '';
        setStatus(`${statusResult.message || (statusResult.done ? '处理完成' : '正在处理通报文档...')}${counter}`);
        setLog(joinLogs(statusResult.logs));
        if (statusResult.done) {
          break;
        }
        await wait(500);
      }

      const result = latest?.result ?? latest;
      if (!result) {
        setProgress(0);
        setStatus('处理状态丢失');
        return;
      }
      setProgress(result.success ? 100 : (latest?.progress ?? 0));
      setStatus(result.message || (result.success ? '处理完成' : '处理失败'));
      if (result.target_path) {
        setTargetPath(result.target_path);
      }
      setManualFiles(result.manual_files ?? []);
      setGeneratedFiles(result.generated_files ?? []);
      setPdfOutputs(result.pdf_outputs ?? []);
      setLastOutputPath(result.pdf_outputs?.[0] ?? result.generated_files?.[0] ?? result.target_path ?? targetPath.trim());
      setLog([
        joinLogs(result.logs),
        result.generated_files?.length ? `\n生成文件:\n${formatPathList(result.generated_files)}` : '',
        result.pdf_outputs?.length ? `\nPDF输出:\n${formatPathList(result.pdf_outputs)}` : '',
        result.failures?.length ? `\n失败项:\n${result.failures.map((item) => `${item.file} -> ${item.reason}`).join('\n')}` : '',
      ].filter(Boolean).join('\n'));
      await loadReportCounters();
    } catch (error) {
      setProgress(0);
      setStatus(`处理失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const classifyOnly = async () => {
    if (!targetPath.trim()) {
      setStatus('请先选择要分类的目录');
      return;
    }
    setIsBusy(true);
    setProgress(20);
    setStatus('正在执行一键分类...');
    try {
      const result = await callBackend<NoticeClassifyResponse>('doc.notice.classify', { target_path: targetPath.trim() });
      setProgress(100);
      setStatus(result.message || (result.success ? '分类完成' : '分类失败'));
      setLog([
        joinLogs(result.logs),
        result.result?.company_group_list?.length ? `\n分类结果:\n${result.result.company_group_list.map(([company, group]) => `${company}\t${group}`).join('\n')}` : '',
        result.result?.unclassified?.length ? `\n未分类:\n${result.result.unclassified.join('\n')}` : '',
      ].filter(Boolean).join('\n'));
    } catch (error) {
      setProgress(0);
      setStatus(`分类失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const convertFailedPdf = async () => {
    if (!targetPath.trim()) {
      setStatus('请先选择目标目录');
      return;
    }
    setIsBusy(true);
    setProgress(35);
    setStatus('正在转换PDF...');
    try {
      const result = await callBackend<NoticeProcessResponse>('doc.notice.convert_failed_pdf', {
        target_path: targetPath.trim(),
        failed_files: manualFiles ?? [],
      });
      setProgress(100);
      setStatus(result.message || (result.success ? 'PDF转换完成' : 'PDF转换失败'));
      setLastOutputPath(result.output_files?.[0] ?? targetPath.trim());
      setPdfOutputs((current) => uniquePaths([...current, ...(result.output_files ?? [])]));
      const deletedFiles = new Set(result.deleted_files ?? []);
      if (deletedFiles.size) {
        setManualFiles((current) => (current ?? []).filter((item) => ![item.output_file, item.backup_file, item.file].some((path) => path && deletedFiles.has(path))));
        setGeneratedFiles((current) => current.filter((path) => !deletedFiles.has(path)));
      }
      setLog([
        log,
        joinLogs(result.logs),
        result.output_files?.length ? `\n输出文件:\n${formatPathList(result.output_files)}` : '',
        result.deleted_files?.length ? `\n已删除Word:\n${formatPathList(result.deleted_files)}` : '',
      ].filter(Boolean).join('\n'));
    } catch (error) {
      setProgress(0);
      setStatus(`PDF转换失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="vertical-detail scroll-page-layout notice-tools-page">
      <div className="doc-info-card" dangerouslySetInnerHTML={{ __html: '📌 <b>网信办通报批量处理工具</b><br><br><b>功能说明：</b><br>• 自动处理文件夹或压缩包中的通报文档<br>• 支持ZIP压缩包自动解压<br>• 自动生成：通报改写、授权委托书、责令整改通知书<br>• 自动处理处置文件模板（复制/编辑）📋<br>• 自动转换为PDF格式（Word + PDF双份）📄<br>• 智能编号管理，支持年度自动重置<br><br><b>使用方法：</b><br>1. 选择包含通报文档的文件夹或ZIP压缩包<br>2. 勾选需要的功能（如自动分类）<br>3. 确认或修改起始编号配置<br>4. 点击「开始处理」按钮' }} />
      <fieldset className="koi-group"><legend>📁 目标选择</legend><FileRow placeholder="选择文件夹或压缩包..." buttonText="📂 选择路径" title="选择文件夹或压缩包" mode="file-or-directory" filters={[{ name: '压缩包', extensions: ['zip', 'rar', '7z'] }, { name: '所有文件', extensions: ['*'] }]} value={targetPath} onChange={setTargetPath} /></fieldset>
      <fieldset className="koi-group notice-number-grid"><legend>🔢 编号配置</legend><label>通报序号:<input className="koi-input compact-number" placeholder="1" value={noticeNumber} onChange={(event) => setNoticeNumber(event.target.value)} /></label><label>责令整改序号:<input className="koi-input compact-number" placeholder="1" value={rectificationNumber} onChange={(event) => setRectificationNumber(event.target.value)} /></label><label>不可用编号:<SelectInput options={['通报', '责令整改']} value={unavailableType} onChange={setUnavailableType} /></label><input className="koi-input unavailable-number-input" placeholder="如：170,172-175" value={unavailableNumbers} onChange={(event) => setUnavailableNumbers(event.target.value)} /><button type="button" className="koi-button secondary compact-button" onClick={() => setStatus('编号配置将在本次处理时传给后端')}>确认修改</button></fieldset>
      <fieldset className="koi-group notice-run-options"><legend>⚙️ 处理选项</legend><label className="checkbox-row"><input type="checkbox" checked={autoGroup} onChange={(event) => setAutoGroup(event.target.checked)} /> 开始处理前自动执行一键分类</label></fieldset>
      <div className="classification-status">分组数据: 本地数据库</div>
      <button type="button" className="koi-button primary full-width-button tall-action-button" onClick={() => startProcess()} disabled={isBusy}>🚀 开始处理</button>
      <button type="button" className="koi-button secondary full-width-button" onClick={classifyOnly} disabled={isBusy}>🗂️ 一键分类</button>
      <button type="button" className="koi-button secondary full-width-button" onClick={() => openBackendPath(lastOutputPath || targetPath, setStatus)} disabled={isBusy || !(lastOutputPath || targetPath)}>📂 打开输出目录</button>
      <ProgressBox title="📊 处理进度" status={status} progress={progress} log={log} />
      <div className="notice-output-grid">
        <NoticePathList title="📄 生成文件" paths={generatedFiles} emptyText="暂无生成文件" onOpen={openNoticePath} />
        <NoticePathList title="🧾 PDF输出" paths={pdfOutputs} emptyText="暂无PDF输出" onOpen={openNoticePath} />
      </div>
      <fieldset className="koi-group"><legend>❌ 编辑失败的文档</legend><div className="modal-message">以下文档在生成或编辑过程中出现错误（如模板生成失败、插入图片失败、格式调整失败等）：</div><NoticeManualList files={manualFiles ?? []} onOpen={openNoticePath} onRemove={removeManualFile} /><div className="action-row"><button type="button" className="koi-button secondary" onClick={convertFailedPdf} disabled={isBusy || !targetPath.trim()}>📄 转换PDF</button><button type="button" className="koi-button danger" onClick={() => setManualFiles([])}>🗑️ 清除列表</button></div></fieldset>
    </div>
  );
}

function RetestOneClickPage() {
  const [targetDir, setTargetDir] = useState('');
  const [status, setStatus] = useState('等待开始复测...');
  const [progress, setProgress] = useState(0);
  const [resultText, setResultText] = useState('');
  const [log, setLog] = useState('');
  const [lastReportPath, setLastReportPath] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const startRetest = async () => {
    if (!targetDir.trim()) {
      setStatus('请先选择通报目录');
      return;
    }
    setIsBusy(true);
    setProgress(10);
    setStatus('正在扫描并复测...');
    setResultText('');
    setLog('');
    try {
      const result = await callBackend<RetestRunResponse>('doc.retest.run', { target_dir: targetDir.trim() });
      setProgress(100);
      setStatus(result.message || (result.success ? '复测完成' : '复测失败'));
      setLastReportPath(result.reports?.[0] ?? targetDir.trim());
      setResultText([
        result.summary || '',
        result.reports?.length ? `\n生成报告:\n${formatPathList(result.reports)}` : '',
      ].filter(Boolean).join('\n'));
      setLog(joinLogs(result.logs));
    } catch (error) {
      setProgress(0);
      setStatus(`复测失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const openOutput = async () => {
    if (!targetDir.trim()) {
      setStatus('请先选择通报目录');
      return;
    }
    try {
      await openBackendPath(lastReportPath || targetDir.trim(), setStatus);
    } catch (error) {
      setStatus(`打开报告目录失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div className="vertical-detail scroll-page-layout retest-page">
      <div className="doc-info-card" dangerouslySetInnerHTML={{ __html: '🛰️ <b>复测一键出</b><br>1. 选择包含【通报文档】的目录<br>2. 自动扫描Word获取漏洞类型和URL<br>3. 自动对URL进行批量复测并在下方展示结果<br>4. 自动截图复测结果区域，写入复测模板正文中的“*”位置，批量生成复测报告' }} />
      <fieldset className="koi-group"><legend>📁 通报目录</legend><FileRow placeholder="选择包含通报Word文档的目录..." buttonText="📂 选择目录" title="选择通报目录" mode="directory" value={targetDir} onChange={setTargetDir} /></fieldset>
      <div className="action-row"><button type="button" className="koi-button primary" onClick={startRetest} disabled={isBusy}>🚀 一键复测</button><button type="button" className="koi-button secondary" onClick={openOutput}>📂 打开报告目录</button></div>
      <fieldset className="koi-group"><legend>📊 复测进度</legend><div className="doc-status-label">{status}</div><div className="progress-shell visible-progress"><div className="progress-fill" style={{ width: `${progress}%` }} /><span>{progress}%</span></div></fieldset>
      <div className="retest-splitter">
        <fieldset className="koi-group"><legend>📜 复测结果预览（将对该区域自动截图写入复测报告）</legend><textarea className="result-textarea retest-result-text" readOnly placeholder="复测结果将在这里展示，并作为证明截图写入复测报告。" value={resultText} /></fieldset>
        <fieldset className="koi-group"><legend>📝 详细日志</legend><textarea className="result-textarea doc-log-text" readOnly value={log} /></fieldset>
      </div>
    </div>
  );
}

function CyberspaceOfficePage() {
  return <TabWidget tabs={[{ id: 'notice-tools', title: '通报杂活', content: <NoticeToolsPage /> }, { id: 'retest-one-click', title: '复测一键出', content: <RetestOneClickPage /> }]} />;
}

export const documentProcessingModule: KoiModule = {
  id: 'document-processing',
  title: '文档处理',
  functions: [
    {
      id: 'document-conversion',
      title: '文档转换',
      component: DocumentConversionPage,
    },
    {
      id: 'pdf-page-extract',
      title: 'PDF页面提取',
      component: PdfExtractPage,
    },
    {
      id: 'cyberspace-office',
      title: '网信办',
      component: CyberspaceOfficePage,
    },
  ],
};
