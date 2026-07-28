import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend } from '../../lib/backend';
import { openBackendPath } from '../../lib/open-path';
import type { KoiModule } from '../../lib/types';

type TemplateItem = {
  id?: string;
  name: string;
  description?: string;
  field_mapping?: Record<string, string>;
  source_format?: string;
  template_format?: string;
  target_template?: string;
  delimiter?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  version?: string;
  usage_count?: number;
};

type TemplateListResponse = {
  templates: TemplateItem[];
  count: number;
};

type FieldHeadersResponse = {
  success: boolean;
  message: string;
  fields: string[];
  detected_separator?: string;
};

type FieldExtractResponse = {
  success: boolean;
  message: string;
  extracted_data?: unknown[][] | null;
  selected_fields?: string[];
  output_file?: string | null;
  detected_separator?: string;
};

type MappingRow = {
  source_field: string;
  template_field: string;
  status: string;
  confidence?: number | null;
};

type TemplateGetResponse = {
  template: TemplateItem;
};

type BackendActionResponse = {
  success: boolean;
  message: string;
  template?: TemplateItem;
  template_id?: string;
  export_file?: string;
};

type AutoMapResponse = BackendActionResponse & {
  auto_mapping?: Record<string, string>;
  mapping_rows?: MappingRow[];
  source_fields?: string[];
  template_fields?: string[];
  unmapped_fields?: string[];
};

type CustomMapResponse = BackendActionResponse & {
  field_mapping?: Record<string, string>;
  mapping_rows?: MappingRow[];
  source_fields?: string[];
  template_fields?: string[];
  missing_sources?: string[];
  missing_templates?: string[];
};

type FillingPreviewResponse = BackendActionResponse & {
  preview_data?: Record<string, unknown>[];
  warnings?: string[];
};

type FillingRunResponse = BackendActionResponse & {
  output_file?: string | null;
  filled_count?: number;
  mapped_fields?: number;
  warnings?: string[];
  statistics?: {
    result_info?: { rows?: number; columns?: number };
    filling_ratio?: { mapped_columns?: number; total_columns?: number; percentage?: number };
    data_quality?: { filled_cells?: number; empty_cells?: number };
  };
};

function TextInput({ placeholder, className = '', value, disabled = false, onChange }: { placeholder: string; className?: string; value?: string; disabled?: boolean; onChange?: (value: string) => void }) {
  return <input className={`koi-input ${className}`} placeholder={placeholder} value={value} disabled={disabled} onChange={(event) => onChange?.(event.target.value)} />;
}

function FileRow({ buttonText, label = '未选择文件', disabled = false, onButtonClick }: { buttonText: string; label?: string; disabled?: boolean; onButtonClick?: () => void }) {
  return (
    <div className="file-selector-row">
      <button type="button" className="koi-button secondary" onClick={onButtonClick} disabled={disabled}>{buttonText}</button>
      <span className="file-label">{label}</span>
    </div>
  );
}

function EmptyList({ hint }: { hint: string }) {
  return <div className="qt-list-widget empty-data-list"><div className="empty-list-hint">{hint}</div></div>;
}

function getFileName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function formatExtractPreview(result: FieldExtractResponse) {
  if (!result.success) {
    return result.message;
  }

  const fields = result.selected_fields ?? [];
  const rows = result.extracted_data ?? [];
  const previewRows = rows.slice(0, 20).map((row) => row.map((value) => String(value ?? '')).join('\t'));
  return [
    result.message,
    fields.length ? `字段: ${fields.join(', ')}` : '',
    '',
    fields.join('\t'),
    ...previewRows,
    rows.length > 20 ? `... 共 ${rows.length} 行` : '',
  ].filter(Boolean).join('\n');
}

function FieldExtractionPage() {
  const [sourceFile, setSourceFile] = useState('');
  const [customSeparator, setCustomSeparator] = useState('');
  const [detectedSeparator, setDetectedSeparator] = useState('');
  const [fields, setFields] = useState<string[]>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [status, setStatus] = useState('等待提取...');
  const [preview, setPreview] = useState('');
  const [outputFile, setOutputFile] = useState('');
  const [lastOutputPath, setLastOutputPath] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const sourceRevisionRef = useRef(0);
  const { dialog: fileDialog, openFilePath, saveFilePath } = useProjectFileDialog();

  const invalidateExtractionResult = (statusText = '字段选择已更新，等待提取...') => {
    setPreview('');
    setLastOutputPath('');
    setStatus(statusText);
  };

  const invalidateSourceState = (nextSource: string, statusText = '源文件已更新，等待加载字段...') => {
    sourceRevisionRef.current += 1;
    setSourceFile(nextSource);
    setDetectedSeparator('');
    setFields([]);
    setSelectedFields([]);
    setPreview('');
    setOutputFile('');
    setLastOutputPath('');
    setStatus(statusText);
    return sourceRevisionRef.current;
  };

  const loadHeaders = async (filePath = sourceFile, revision = sourceRevisionRef.current) => {
    if (!filePath.trim()) {
      setStatus('请先输入或选择数据文件路径');
      return;
    }

    setIsBusy(true);
    setStatus('正在加载文件头信息...');
    try {
      const result = await callBackend<FieldHeadersResponse>('data.field_extract.headers', {
        source_file: filePath.trim(),
        custom_separator: customSeparator.trim(),
      });
      if (sourceRevisionRef.current !== revision) return;

      if (!result.success) {
        setStatus(result.message || '加载失败');
        setFields([]);
        setSelectedFields([]);
        return;
      }

      setFields(result.fields ?? []);
      setSelectedFields([]);
      setDetectedSeparator(result.detected_separator ?? '');
      setStatus(`已加载 ${result.fields?.length ?? 0} 个字段`);
    } catch (error) {
      if (sourceRevisionRef.current !== revision) return;
      setStatus(`加载失败: ${error instanceof Error ? error.message : String(error)}`);
      setFields([]);
      setSelectedFields([]);
    } finally {
      if (sourceRevisionRef.current === revision) {
        setIsBusy(false);
      }
    }
  };

  const runExtraction = async () => {
    if (!sourceFile.trim()) {
      setStatus('请先选择源文件');
      return;
    }
    if (!selectedFields.length) {
      setStatus('请选择要提取的字段');
      return;
    }

    setIsBusy(true);
    setPreview('');
    setLastOutputPath('');
    setStatus('正在提取字段...');
    const revision = sourceRevisionRef.current;
    try {
      const result = await callBackend<FieldExtractResponse>('data.field_extract.run', {
        source_file: sourceFile.trim(),
        selected_fields: selectedFields,
        output_file: outputFile.trim(),
        custom_separator: customSeparator.trim(),
      });
      if (sourceRevisionRef.current !== revision) return;

      setDetectedSeparator(result.detected_separator ?? detectedSeparator);
      setPreview(formatExtractPreview(result));
      setStatus(result.message || (result.success ? '提取完成' : '提取失败'));
      setLastOutputPath(result.success ? (result.output_file || outputFile.trim()) : '');
    } catch (error) {
      if (sourceRevisionRef.current !== revision) return;
      setStatus(`提取失败: ${error instanceof Error ? error.message : String(error)}`);
      setPreview('');
    } finally {
      if (sourceRevisionRef.current === revision) {
        setIsBusy(false);
      }
    }
  };

  const chooseSourceFile = async () => {
    const selected = await openFilePath({
      title: '选择数据文件',
      filters: [
        { name: '所有支持的文件', extensions: ['xlsx', 'xls', 'csv', 'txt'] },
        { name: 'Excel文件', extensions: ['xlsx', 'xls'] },
        { name: 'CSV文件', extensions: ['csv'] },
        { name: '文本文件', extensions: ['txt'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });

    if (!selected) {
      setStatus('未选择文件');
      return;
    }

    const revision = invalidateSourceState(selected, `已选择: ${getFileName(selected)}`);
    await loadHeaders(selected, revision);
  };

  const chooseOutputFile = async () => {
    const selected = await saveFilePath({
      title: '保存提取结果',
      filters: [
        { name: 'Excel文件', extensions: ['xlsx'] },
        { name: '文本文件', extensions: ['txt'] },
        { name: 'CSV文件', extensions: ['csv'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });

    if (selected) {
      setOutputFile(selected);
      setLastOutputPath('');
    }
  };

  const changeSourceFile = (value: string) => {
    if (value === sourceFile) return;
    invalidateSourceState(value);
  };

  const changeCustomSeparator = (value: string) => {
    if (value === customSeparator) return;
    sourceRevisionRef.current += 1;
    setCustomSeparator(value);
    setDetectedSeparator('');
    setFields([]);
    setSelectedFields([]);
    setPreview('');
    setLastOutputPath('');
    setStatus('分隔符已更新，请重新加载字段');
  };

  const toggleField = (field: string) => {
    invalidateExtractionResult();
    setSelectedFields((current) => current.includes(field) ? current.filter((item) => item !== field) : [...current, field]);
  };

  const selectFields = (nextFields: string[]) => {
    invalidateExtractionResult();
    setSelectedFields(nextFields);
  };

  return (
    <div className="data-scroll-page data-extraction-layout">
      <div className="data-left-panel">
        <fieldset className="koi-group">
          <legend>📁 文件选择</legend>
          <div className="file-selector-row wide-file-row">
            <button type="button" className="koi-button secondary" onClick={chooseSourceFile} disabled={isBusy}>🗂️ 选择数据文件</button>
            <input className="koi-input" placeholder="也可手动输入文件路径" value={sourceFile} disabled={isBusy} onChange={(event) => changeSourceFile(event.target.value)} onBlur={() => sourceFile.trim() && loadHeaders()} />
          </div>
          <div className="horizontal-field data-separator-row">
            <span>自定义分隔符:</span>
            <TextInput className="max-200" placeholder={'留空自动检测，或输入如: \\t, |, ;, \\s+'} value={customSeparator} onChange={changeCustomSeparator} disabled={isBusy} />
            <span className="success-hint">检测到: {detectedSeparator}</span>
          </div>
        </fieldset>

        <fieldset className="koi-group data-fill-group">
          <legend>📋 表头信息</legend>
          {fields.length ? (
            <div className="qt-list-widget empty-data-list">
              {fields.map((field) => (
                <button key={field} type="button" className={`qt-list-item selectable-list-item${selectedFields.includes(field) ? ' selected' : ''}`} onClick={() => toggleField(field)} disabled={isBusy}>
                  {field}
                </button>
              ))}
            </div>
          ) : <EmptyList hint="选择数据文件后显示字段列表" />}
          <div className="action-row">
            <button type="button" className="koi-button secondary compact-button" onClick={() => selectFields(fields)} disabled={isBusy || !fields.length}>全选</button>
            <button type="button" className="koi-button secondary compact-button" onClick={() => selectFields([])} disabled={isBusy || !selectedFields.length}>清空</button>
          </div>
        </fieldset>

        <button type="button" className="koi-button primary full-width-button" onClick={runExtraction} disabled={isBusy}>🚀 提取选中字段</button>
      </div>

      <div className="data-right-panel">
        <fieldset className="koi-group data-result-group">
          <legend>📊 提取结果</legend>
          <div className="italic-status">{status}</div>
          <textarea className="result-textarea extraction-preview" readOnly value={preview} />
          <div className="file-selector-row wide-file-row">
            <span className="italic-status">保存位置:</span>
            <input className="koi-input" placeholder="留空则只预览，不保存" value={outputFile} disabled={isBusy} onChange={(event) => { setOutputFile(event.target.value); setLastOutputPath(''); }} />
            <button type="button" className="koi-button secondary compact-button" onClick={chooseOutputFile} disabled={isBusy}>📁 浏览...</button>
          </div>
          <button type="button" className="koi-button secondary" onClick={() => openBackendPath(lastOutputPath, setStatus)} disabled={isBusy || !lastOutputPath}>📂 打开本次结果</button>
        </fieldset>
      </div>
      {fileDialog}
    </div>
  );
}

function templateIdentity(template: TemplateItem) {
  return template.id || template.name;
}

function inferSourceFormat(filePath: string) {
  const extension = filePath.split('.').pop()?.toLowerCase();
  if (extension === 'csv') return 'csv';
  if (extension === 'txt' || extension === 'tsv') return 'txt';
  return 'excel';
}

function buildMappingRows(sourceFields: string[], templateFields: string[], fieldMapping: Record<string, string>): MappingRow[] {
  const rows: MappingRow[] = [];
  const mappedSources = new Set<string>();

  sourceFields.forEach((sourceField) => {
    const templateField = Object.entries(fieldMapping).find(([, mappedSource]) => mappedSource === sourceField)?.[0] ?? '';
    if (templateField) {
      mappedSources.add(sourceField);
    }
    rows.push({
      source_field: sourceField,
      template_field: templateField,
      status: templateField ? '已映射' : '待映射',
    });
  });

  templateFields.forEach((templateField) => {
    if (!fieldMapping[templateField]) {
      rows.push({
        source_field: '',
        template_field: templateField,
        status: '待映射',
      });
    }
  });

  return rows;
}

function formatMappingSummary(fieldMapping: Record<string, string>) {
  const entries = Object.entries(fieldMapping);
  if (!entries.length) {
    return '当前没有字段映射';
  }
  return entries.map(([templateField, sourceField]) => `${templateField} <- ${sourceField}`).join('\n');
}

function formatPreviewRows(rows: Record<string, unknown>[] | undefined) {
  if (!rows?.length) {
    return '暂无预览数据';
  }
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return [
    headers.join('\t'),
    ...rows.slice(0, 20).map((row) => headers.map((header) => String(row[header] ?? '')).join('\t')),
    rows.length > 20 ? `... 共 ${rows.length} 行` : '',
  ].filter(Boolean).join('\n');
}

function ModalShell({ title, width = 'normal', onClose, children }: { title: string; width?: 'normal' | 'wide'; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className={`koi-modal ${width === 'wide' ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-title-row">
          <h3>{title}</h3>
          <button type="button" className="modal-close-button" aria-label="关闭" onClick={onClose}>✕</button>
        </div>
        <div className="modal-separator" />
        {children}
      </section>
    </div>
  );
}

function NoticeModal({ title = '提示', message, onClose }: { title?: string; message: string; onClose: () => void }) {
  return (
    <ModalShell title={title} onClose={onClose}>
      <div className="modal-message pre-line">{message}</div>
      <div className="modal-actions"><button type="button" className="koi-button primary" onClick={onClose}>确定</button></div>
    </ModalShell>
  );
}

function ConfirmModal({ title, message, onCancel, onConfirm, busy = false }: { title: string; message: string; onCancel: () => void; onConfirm: () => void; busy?: boolean }) {
  return (
    <ModalShell title={title} onClose={onCancel}>
      <div className="modal-message pre-line">{message}</div>
      <div className="modal-actions">
        <button type="button" className="koi-button danger" onClick={onConfirm} disabled={busy}>确定</button>
        <button type="button" className="koi-button secondary" onClick={onCancel} disabled={busy}>取消</button>
      </div>
    </ModalShell>
  );
}

function MappingTree({ rows }: { rows: MappingRow[] }) {
  return (
    <table className="result-table mapping-table">
      <thead><tr><th>源字段</th><th>目标字段</th><th>映射状态</th></tr></thead>
      <tbody>
        {rows.length ? rows.map((row, index) => (
          <tr key={`${row.source_field}-${row.template_field}-${index}`} className={row.status === '已映射' ? 'mapped-row' : ''}>
            <td>{row.source_field || '未选择'}</td>
            <td>{row.template_field || '未映射'}</td>
            <td>{row.confidence ? `${row.status} (${Math.round(row.confidence * 100)}%)` : row.status}</td>
          </tr>
        )) : <tr><td colSpan={3}>选择源文件和目标模板后显示字段映射</td></tr>}
      </tbody>
    </table>
  );
}

function CustomMappingModal({
  sourceFields,
  templateFields,
  fieldMapping,
  onClose,
  onApply,
  busy = false,
}: {
  sourceFields: string[];
  templateFields: string[];
  fieldMapping: Record<string, string>;
  onClose: () => void;
  onApply: (mapping: Record<string, string>) => void;
  busy?: boolean;
}) {
  const [rows, setRows] = useState(() => {
    const mappedRows = Object.entries(fieldMapping).map(([templateField, sourceField]) => ({ sourceField, templateField }));
    return mappedRows.length ? mappedRows : (sourceFields.length ? sourceFields.map((sourceField) => ({ sourceField, templateField: '' })) : [{ sourceField: '', templateField: '' }]);
  });
  const [error, setError] = useState('');

  const updateRow = (index: number, patch: Partial<{ sourceField: string; templateField: string }>) => {
    setRows((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));
  };

  const applyRows = () => {
    const nextMapping: Record<string, string> = {};
    rows.forEach((row) => {
      if (row.sourceField && row.templateField) {
        nextMapping[row.templateField] = row.sourceField;
      }
    });
    if (!Object.keys(nextMapping).length) {
      setError('请至少设置一个有效的字段映射');
      return;
    }
    onApply(nextMapping);
  };

  return (
    <ModalShell title="⚙️ 自定义字段映射" width="wide" onClose={onClose}>
      <div className="mapping-dialog-list">
        {rows.map((row, index) => (
          <div className="mapping-dialog-row" key={`mapping-row-${index}`}>
            <span>源字段:</span>
            <select className="koi-input" value={row.sourceField} onChange={(event) => updateRow(index, { sourceField: event.target.value })}>
              <option value="">请选择源字段</option>
              {sourceFields.map((field) => <option key={field} value={field}>{field}</option>)}
            </select>
            <span>→ 目标字段:</span>
            <select className="koi-input" value={row.templateField} onChange={(event) => updateRow(index, { templateField: event.target.value })}>
              <option value="">请选择目标字段</option>
              {templateFields.map((field) => <option key={field} value={field}>{field}</option>)}
            </select>
          </div>
        ))}
      </div>
      {error && <div className="modal-message">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="koi-button secondary" onClick={() => setRows((current) => [...current, { sourceField: '', templateField: '' }])}>➕ 添加映射</button>
        <button type="button" className="koi-button secondary" onClick={() => setRows((current) => current.length > 1 ? current.slice(0, -1) : current)}>➖ 删除最后一行</button>
        <button type="button" className="koi-button primary" onClick={applyRows} disabled={busy}>✅ 应用映射</button>
        <button type="button" className="koi-button secondary" onClick={onClose} disabled={busy}>取消</button>
      </div>
    </ModalShell>
  );
}

function TemplateEditorModal({
  mode,
  template,
  defaultMapping = {},
  defaultTargetTemplate = '',
  defaultDelimiter = '',
  defaultSourceFormat = 'excel',
  onClose,
  onSave,
  onChooseTarget,
}: {
  mode: 'create' | 'edit';
  template?: TemplateItem;
  defaultMapping?: Record<string, string>;
  defaultTargetTemplate?: string;
  defaultDelimiter?: string;
  defaultSourceFormat?: string;
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onChooseTarget: (defaultPath: string) => Promise<string | null>;
}) {
  const [name, setName] = useState(template?.name ?? '');
  const [description, setDescription] = useState(template?.description ?? '');
  const [targetTemplate, setTargetTemplate] = useState(template?.target_template ?? defaultTargetTemplate);
  const [sourceFormat, setSourceFormat] = useState(template?.source_format ?? defaultSourceFormat);
  const [delimiter, setDelimiter] = useState(template?.delimiter ?? defaultDelimiter);
  const [mappingText, setMappingText] = useState(JSON.stringify(template?.field_mapping ?? defaultMapping, null, 2));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setError('');
    if (!name.trim()) {
      setError('请输入模板名称');
      return;
    }

    let fieldMapping: Record<string, string>;
    try {
      const parsed = JSON.parse(mappingText || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('字段映射必须是 JSON 对象');
      }
      fieldMapping = Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, String(value)]));
    } catch (error) {
      setError(`字段映射 JSON 无效: ${error instanceof Error ? error.message : String(error)}`);
      return;
    }

    setSaving(true);
    try {
      await onSave({
        template_id: template ? templateIdentity(template) : undefined,
        name: name.trim(),
        description: description.trim(),
        target_template: targetTemplate.trim(),
        source_format: sourceFormat,
        template_format: 'excel',
        delimiter: delimiter.trim(),
        field_mapping: fieldMapping,
      });
    } finally {
      setSaving(false);
    }
  };

  const chooseTarget = async () => {
    const selected = await onChooseTarget(targetTemplate);
    if (selected) {
      setTargetTemplate(selected);
    }
  };

  return (
    <ModalShell title={mode === 'create' ? '➕ 创建模板' : `✏️ 编辑模板 - ${template?.name ?? ''}`} width="wide" onClose={onClose}>
      <div className="template-editor-grid">
        <label className="field-row modal-field"><span>模板名称:</span><input className="koi-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="请输入模板名称" /></label>
        <label className="field-row modal-field"><span>描述:</span><textarea className="koi-input modal-textarea short-textarea" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="请输入模板描述" /></label>
        <div className="field-row modal-field template-target-row">
          <span>目标模板文件:</span>
          <input className="koi-input" value={targetTemplate} onChange={(event) => setTargetTemplate(event.target.value)} placeholder="请选择目标模板文件" />
          <button type="button" className="koi-button secondary compact-button" onClick={chooseTarget}>浏览</button>
        </div>
        <label className="field-row modal-field"><span>源数据格式:</span><select className="koi-input" value={sourceFormat} onChange={(event) => setSourceFormat(event.target.value)}><option value="excel">excel</option><option value="txt">txt</option><option value="csv">csv</option></select></label>
        <label className="field-row modal-field"><span>分隔符:</span><input className="koi-input" value={delimiter} onChange={(event) => setDelimiter(event.target.value)} placeholder="文本模板可填 |、\\t、, 等" /></label>
        <label className="field-row modal-field"><span>字段映射 JSON:</span><textarea className="result-textarea template-json-area" value={mappingText} onChange={(event) => setMappingText(event.target.value)} /></label>
      </div>
      {error && <div className="modal-message">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="koi-button primary" onClick={save} disabled={saving}>💾 保存</button>
        <button type="button" className="koi-button secondary" onClick={onClose} disabled={saving}>取消</button>
      </div>
    </ModalShell>
  );
}

function TemplateDetailModal({ template, onClose }: { template: TemplateItem; onClose: () => void }) {
  return (
    <ModalShell title={`📋 ${template.name}`} width="wide" onClose={onClose}>
      <div className="template-detail-grid">
        <span>描述</span><strong>{template.description || '无描述'}</strong>
        <span>源数据格式</span><strong>{template.source_format || '未知'}{template.delimiter ? ` (分隔符: ${template.delimiter})` : ''}</strong>
        <span>目标模板文件</span><strong>{template.target_template || '未指定'}</strong>
        <span>使用次数</span><strong>{template.usage_count ?? 0}</strong>
        <span>更新时间</span><strong>{template.updated_at || template.created_at || '未知'}</strong>
      </div>
      <div className="detail-dialog-label">字段映射关系</div>
      <textarea className="detail-dialog-text" readOnly value={formatMappingSummary(template.field_mapping ?? {})} />
      <div className="modal-actions"><button type="button" className="koi-button primary" onClick={onClose}>关闭</button></div>
    </ModalShell>
  );
}

function DataFillingPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [sourceFile, setSourceFile] = useState('');
  const [targetTemplate, setTargetTemplate] = useState('');
  const [customSeparator, setCustomSeparator] = useState('');
  const [sourceFields, setSourceFields] = useState<string[]>([]);
  const [templateFields, setTemplateFields] = useState<string[]>([]);
  const [fieldMapping, setFieldMapping] = useState<Record<string, string>>({});
  const [status, setStatus] = useState('等待处理...');
  const [progress, setProgress] = useState(0);
  const [outputFile, setOutputFile] = useState('');
  const [preview, setPreview] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [customMappingOpen, setCustomMappingOpen] = useState(false);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const { dialog: fileDialog, openFilePath, saveFilePath } = useProjectFileDialog();

  const selectedTemplate = useMemo(() => templates.find((template) => templateIdentity(template) === selectedTemplateId), [templates, selectedTemplateId]);
  const mappingRows = useMemo(() => buildMappingRows(sourceFields, templateFields, fieldMapping), [sourceFields, templateFields, fieldMapping]);

  const invalidateGeneratedFillingResult = () => {
    setPreview('');
    setOutputFile('');
    setProgress(0);
    setNotice(null);
  };

  const invalidateFillingTaskState = () => {
    setFieldMapping({});
    invalidateGeneratedFillingResult();
    setCustomMappingOpen(false);
    setSaveTemplateOpen(false);
  };

  const changeFillingSeparator = (value: string) => {
    if (value === customSeparator) return;
    setCustomSeparator(value);
    setSourceFields([]);
    invalidateFillingTaskState();
    setStatus('分隔符已更新，请重新加载源文件或自动映射字段');
  };

  const loadTemplates = async () => {
    try {
      const result = await callBackend<TemplateListResponse>('data.templates.list');
      setTemplates(result.templates ?? []);
    } catch {
      setTemplates([]);
    }
  };

  useEffect(() => {
    void loadTemplates();
  }, []);

  const loadFields = async (filePath: string, target: 'source' | 'template', sourceSeparator = customSeparator) => {
    if (!filePath.trim()) {
      return [];
    }

    const result = await callBackend<FieldHeadersResponse>('data.field_extract.headers', {
      source_file: filePath.trim(),
      custom_separator: target === 'source' ? sourceSeparator.trim() : '',
    });
    if (!result.success) {
      throw new Error(result.message || '加载字段失败');
    }
    if (target === 'source') {
      setSourceFields(result.fields ?? []);
    } else {
      setTemplateFields(result.fields ?? []);
    }
    return result.fields ?? [];
  };

  const chooseSourceFile = async () => {
    const selected = await openFilePath({
      title: '选择源文件',
      defaultPath: sourceFile,
      filters: [
        { name: '表格和文本文件', extensions: ['xlsx', 'xls', 'csv', 'txt', 'tsv'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected) return;
    invalidateFillingTaskState();
    setSourceFile(selected);
    setSourceFields([]);
    setIsBusy(true);
    setStatus(`正在加载源字段: ${getFileName(selected)}`);
    try {
      const fields = await loadFields(selected, 'source');
      setStatus(`已加载源字段 ${fields.length} 个`);
    } catch (error) {
      setStatus(`加载源字段失败: ${error instanceof Error ? error.message : String(error)}`);
      setSourceFields([]);
    } finally {
      setIsBusy(false);
    }
  };

  const chooseTargetTemplate = async () => {
    const selected = await openFilePath({
      title: '选择目标模板',
      defaultPath: targetTemplate,
      filters: [
        { name: 'Excel模板', extensions: ['xlsx', 'xls'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected) return;
    invalidateFillingTaskState();
    setTargetTemplate(selected);
    setTemplateFields([]);
    setIsBusy(true);
    setStatus(`正在加载模板字段: ${getFileName(selected)}`);
    try {
      const fields = await loadFields(selected, 'template');
      setStatus(`已加载模板字段 ${fields.length} 个`);
    } catch (error) {
      setStatus(`加载模板字段失败: ${error instanceof Error ? error.message : String(error)}`);
      setTemplateFields([]);
    } finally {
      setIsBusy(false);
    }
  };

  const useTemplate = async () => {
    if (!selectedTemplateId) {
      setStatus('请选择一个有效的模板');
      return;
    }
    setIsBusy(true);
    try {
      const result = await callBackend<TemplateGetResponse>('data.templates.get', { template_id: selectedTemplateId, mark_used: true });
      const template = result.template;
      const nextSeparator = template.delimiter ?? customSeparator;
      const separatorChanged = nextSeparator !== customSeparator;
      invalidateGeneratedFillingResult();
      setFieldMapping(template.field_mapping ?? {});
      setCustomSeparator(nextSeparator);
      if (separatorChanged) {
        setSourceFields([]);
      }
      if (template.target_template) {
        setTemplateFields([]);
        setTargetTemplate(template.target_template);
      }
      setStatus(`已应用模板: ${template.name}`);
      if (template.target_template) {
        await loadFields(template.target_template, 'template');
      }
      if (separatorChanged && sourceFile.trim()) {
        await loadFields(sourceFile, 'source', nextSeparator);
      }
      await loadTemplates();
    } catch (error) {
      setStatus(`应用模板失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const validateReady = () => {
    if (!sourceFile.trim()) {
      setStatus('请先选择源文件');
      return false;
    }
    if (!targetTemplate.trim()) {
      setStatus('请先选择目标模板文件');
      return false;
    }
    if (!Object.keys(fieldMapping).length) {
      setStatus('请先设置字段映射');
      return false;
    }
    if (!sourceFields.length || !templateFields.length) {
      setStatus('源字段或模板字段尚未加载，请重新选择文件');
      return false;
    }
    const validSourceFields = new Set(sourceFields);
    const validTemplateFields = new Set(templateFields);
    const mappingIsCompatible = Object.entries(fieldMapping).every(([templateField, sourceField]) => validTemplateFields.has(templateField) && validSourceFields.has(sourceField));
    if (!mappingIsCompatible) {
      setStatus('字段映射与当前源文件或模板不匹配，请重新映射');
      return false;
    }
    return true;
  };

  const autoMapFields = async () => {
    if (!sourceFile.trim() || !targetTemplate.trim()) {
      setStatus('请先选择源文件和目标模板文件');
      return;
    }
    setIsBusy(true);
    invalidateGeneratedFillingResult();
    setProgress(35);
    setStatus('正在自动映射字段...');
    try {
      const result = await callBackend<AutoMapResponse>('data.filling.auto_map', {
        source_file: sourceFile.trim(),
        template_file: targetTemplate.trim(),
        custom_separator: customSeparator.trim(),
      });
      if (!result.success) {
        setStatus(result.message || '自动映射失败');
        return;
      }
      setFieldMapping(result.auto_mapping ?? {});
      if (result.source_fields) setSourceFields(result.source_fields);
      if (result.template_fields) setTemplateFields(result.template_fields);
      setStatus(result.message || '自动映射完成');
      setProgress(100);
    } catch (error) {
      setStatus(`自动映射失败: ${error instanceof Error ? error.message : String(error)}`);
      setProgress(0);
    } finally {
      setIsBusy(false);
    }
  };

  const applyCustomMapping = async (mapping: Record<string, string>) => {
    if (!sourceFile.trim() || !targetTemplate.trim()) {
      setStatus('请先选择源文件和目标模板文件');
      return;
    }
    setIsBusy(true);
    invalidateGeneratedFillingResult();
    try {
      const result = await callBackend<CustomMapResponse>('data.filling.custom_map', {
        source_file: sourceFile.trim(),
        template_file: targetTemplate.trim(),
        custom_separator: customSeparator.trim(),
        field_mapping: mapping,
      });
      if (!result.success) {
        setStatus(result.message || '自定义映射失败');
        return;
      }
      setFieldMapping(result.field_mapping ?? mapping);
      if (result.source_fields) setSourceFields(result.source_fields);
      if (result.template_fields) setTemplateFields(result.template_fields);
      setCustomMappingOpen(false);
      setStatus(result.message || '自定义映射已应用');
    } catch (error) {
      setStatus(`自定义映射失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const previewFilling = async () => {
    if (!validateReady()) return;
    setIsBusy(true);
    setStatus('正在生成填充预览...');
    try {
      const result = await callBackend<FillingPreviewResponse>('data.filling.preview', {
        source_file: sourceFile.trim(),
        template_file: targetTemplate.trim(),
        custom_separator: customSeparator.trim(),
        field_mapping: fieldMapping,
        preview_rows: 10,
      });
      setPreview(formatPreviewRows(result.preview_data));
      setStatus(result.message || (result.success ? '预览完成' : '预览失败'));
    } catch (error) {
      setPreview('');
      setStatus(`预览失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const startFilling = async () => {
    if (!validateReady()) return;
    const selectedOutput = await saveFilePath({
      title: '保存填充结果',
      filters: [
        { name: 'Excel文件', extensions: ['xlsx'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selectedOutput) {
      setStatus('已取消保存');
      return;
    }

    setIsBusy(true);
    setProgress(35);
    setStatus('正在填充数据，请稍候...');
    try {
      const result = await callBackend<FillingRunResponse>('data.filling.run', {
        source_file: sourceFile.trim(),
        template_file: targetTemplate.trim(),
        output_file: selectedOutput,
        custom_separator: customSeparator.trim(),
        field_mapping: fieldMapping,
      });
      setOutputFile(result.success ? (result.output_file ?? selectedOutput) : '');
      setProgress(result.success ? 100 : 0);
      const rows = result.filled_count ?? result.statistics?.result_info?.rows ?? 0;
      const mapped = result.mapped_fields ?? Object.keys(fieldMapping).length;
      setStatus(result.message || (result.success ? '填充完成' : '填充失败'));
      if (result.success) {
        setNotice(`数据填充完成\n\n填充行数: ${rows}\n映射字段: ${mapped}\n\n结果文件:\n${result.output_file ?? selectedOutput}`);
      } else {
        setNotice(null);
      }
    } catch (error) {
      setProgress(0);
      setStatus(`填充失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const saveTemplate = async (payload: Record<string, unknown>) => {
    const result = await callBackend<BackendActionResponse>('data.template.save', payload);
    if (!result.success) {
      throw new Error(result.message || '保存模板失败');
    }
    setSaveTemplateOpen(false);
    setStatus(result.message || '模板已保存');
    await loadTemplates();
  };

  return (
    <div className="data-scroll-page data-filling-layout">
      <fieldset className="koi-group">
        <legend>📄 源文件选择</legend>
        <FileRow buttonText="📂 选择源文件" label={sourceFile || '未选择文件'} onButtonClick={chooseSourceFile} disabled={isBusy} />
        <div className="horizontal-field data-separator-row">
          <span>分隔符:</span>
          <TextInput className="max-200" placeholder="文本/CSV 可填 |、\\t、, 等" value={customSeparator} onChange={changeFillingSeparator} disabled={isBusy} />
          <span className="italic-status">{sourceFields.length ? `源字段 ${sourceFields.length} 个` : '未加载源字段'}</span>
        </div>
      </fieldset>

      <fieldset className="koi-group">
        <legend>📋 目标模板选择</legend>
        <FileRow buttonText="📊 选择目标模板" label={targetTemplate || '未选择模板'} onButtonClick={chooseTargetTemplate} disabled={isBusy} />
        <div className="italic-status">{templateFields.length ? `模板字段 ${templateFields.length} 个` : '未加载模板字段'}</div>
      </fieldset>

      <fieldset className="koi-group">
        <legend>🎯 模板选择</legend>
        <div className="template-select-row">
          <span>选择模板:</span>
          <select className="koi-input" value={selectedTemplateId} disabled={isBusy} onChange={(event) => setSelectedTemplateId(event.target.value)}>
            <option value="">请选择模板</option>
            {templates.map((template) => <option key={templateIdentity(template)} value={templateIdentity(template)}>{template.name}</option>)}
          </select>
          <button type="button" className="koi-button secondary" onClick={useTemplate} disabled={isBusy}>✅ 使用模板</button>
          <span className="template-item-meta">{selectedTemplate?.description ?? ''}</span>
        </div>
      </fieldset>

      <fieldset className="koi-group data-fill-group">
        <legend>🔗 字段映射</legend>
        <MappingTree rows={mappingRows} />
        <div className="action-row">
          <button type="button" className="koi-button secondary min-120" onClick={() => setNotice(formatMappingSummary(fieldMapping))} disabled={isBusy}>👁️ 显示映射</button>
          <button type="button" className="koi-button secondary min-120" onClick={autoMapFields} disabled={isBusy}>🤖 自动映射</button>
          <button type="button" className="koi-button secondary min-120" onClick={() => setCustomMappingOpen(true)} disabled={isBusy}>⚙️ 自定义映射</button>
          <button type="button" className="koi-button secondary min-120" onClick={previewFilling} disabled={isBusy}>🔎 预览填充</button>
        </div>
      </fieldset>

      <fieldset className="koi-group">
        <legend>📊 处理进度</legend>
        <div className="progress-shell visible-progress"><div className="progress-fill" style={{ width: `${progress}%` }} /><span>{progress}%</span></div>
        <div className="status-strip visible-status">{status}</div>
        {outputFile && <div className="italic-status">结果文件: {outputFile}</div>}
        {preview && <textarea className="result-textarea filling-preview" readOnly value={preview} />}
      </fieldset>

      <div className="action-row">
        <button type="button" className="koi-button primary" onClick={startFilling} disabled={isBusy}>🚀 开始填充</button>
        <button type="button" className="koi-button secondary" onClick={() => setSaveTemplateOpen(true)} disabled={isBusy || !Object.keys(fieldMapping).length}>💾 保存为模板</button>
        <button type="button" className="koi-button secondary" onClick={() => openBackendPath(outputFile, setStatus)} disabled={isBusy || !outputFile}>📂 打开结果</button>
      </div>

      {notice && <NoticeModal title="提示" message={notice} onClose={() => setNotice(null)} />}
      {customMappingOpen && <CustomMappingModal sourceFields={sourceFields} templateFields={templateFields} fieldMapping={fieldMapping} onClose={() => setCustomMappingOpen(false)} onApply={applyCustomMapping} busy={isBusy} />}
      {saveTemplateOpen && (
        <TemplateEditorModal
          mode="create"
          defaultMapping={fieldMapping}
          defaultTargetTemplate={targetTemplate}
          defaultDelimiter={customSeparator}
          defaultSourceFormat={inferSourceFormat(sourceFile)}
          onClose={() => setSaveTemplateOpen(false)}
          onSave={saveTemplate}
          onChooseTarget={(defaultPath) => openFilePath({ title: '选择目标模板文件', defaultPath, filters: [{ name: 'Excel模板', extensions: ['xlsx', 'xls'] }, { name: '所有文件', extensions: ['*'] }] })}
        />
      )}
      {fileDialog}
    </div>
  );
}

function TemplateManagementPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [status, setStatus] = useState('');
  const [viewerTemplate, setViewerTemplate] = useState<TemplateItem | null>(null);
  const [editorState, setEditorState] = useState<{ mode: 'create' | 'edit'; template?: TemplateItem } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TemplateItem | null>(null);
  const [overwriteImport, setOverwriteImport] = useState(false);
  const [lastExportPath, setLastExportPath] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const { dialog: fileDialog, openFilePath, saveFilePath } = useProjectFileDialog();

  const selectedTemplate = useMemo(() => templates.find((template) => templateIdentity(template) === selectedTemplateId), [templates, selectedTemplateId]);

  const loadTemplates = async () => {
    try {
      const result = await callBackend<TemplateListResponse>('data.templates.list');
      setTemplates(result.templates ?? []);
      setStatus(`已加载 ${result.count ?? 0} 个模板`);
      if (selectedTemplateId && !(result.templates ?? []).some((template) => templateIdentity(template) === selectedTemplateId)) {
        setSelectedTemplateId('');
      }
    } catch (error) {
      setTemplates([]);
      setStatus(`加载模板失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  useEffect(() => {
    void loadTemplates();
  }, []);

  const requireSelection = () => {
    if (!selectedTemplate) {
      setStatus('请先选择模板');
      return null;
    }
    return selectedTemplate;
  };

  const saveTemplate = async (payload: Record<string, unknown>) => {
    setIsBusy(true);
    try {
      const command = payload.template_id ? 'data.templates.update' : 'data.templates.create';
      const result = await callBackend<BackendActionResponse>(command, payload);
      if (!result.success) {
        throw new Error(result.message || '保存模板失败');
      }
      setEditorState(null);
      setStatus(result.message || '模板已保存');
      await loadTemplates();
    } finally {
      setIsBusy(false);
    }
  };

  const importTemplate = async () => {
    const selected = await openFilePath({
      title: '导入模板',
      filters: [
        { name: 'JSON文件', extensions: ['json'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected) return;
    setIsBusy(true);
    try {
      const result = await callBackend<BackendActionResponse>('data.templates.import', { import_path: selected, overwrite: overwriteImport });
      setStatus(result.message || (result.success ? '导入完成' : '导入失败'));
      await loadTemplates();
    } catch (error) {
      setStatus(`导入模板失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const exportTemplate = async () => {
    const template = requireSelection();
    if (!template) return;
    const selected = await saveFilePath({
      title: '导出模板',
      defaultPath: `${template.name}.json`,
      filters: [
        { name: 'JSON文件', extensions: ['json'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected) return;
    setIsBusy(true);
    try {
      const result = await callBackend<BackendActionResponse>('data.templates.export', { template_id: templateIdentity(template), export_path: selected });
      const exportedPath = result.export_file ?? selected;
      setLastExportPath(exportedPath);
      setStatus(result.message || `模板已导出到: ${exportedPath}`);
    } catch (error) {
      setStatus(`导出模板失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const deleteTemplate = async () => {
    if (!deleteTarget) return;
    setIsBusy(true);
    try {
      const result = await callBackend<BackendActionResponse>('data.templates.delete', { template_id: templateIdentity(deleteTarget) });
      setStatus(result.message || (result.success ? '模板已删除' : '删除失败'));
      setDeleteTarget(null);
      await loadTemplates();
    } catch (error) {
      setStatus(`删除模板失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="data-scroll-page template-management-layout">
      <div className="template-list-column">
        <fieldset className="koi-group data-fill-group">
          <legend>📚 模板列表</legend>
          {templates.length ? (
            <div className="qt-list-widget empty-data-list">
              {templates.map((template) => {
                const id = templateIdentity(template);
                return (
                  <button key={id} type="button" className={`qt-list-item selectable-list-item${selectedTemplateId === id ? ' selected' : ''}`} onClick={() => setSelectedTemplateId(id)}>
                    <strong>{template.name}</strong>
                    <div className="template-item-meta">{template.description || '无描述'} · 使用次数 {template.usage_count ?? 0}</div>
                  </button>
                );
              })}
            </div>
          ) : <EmptyList hint="暂无模板" />}
          {status && <div className="italic-status">{status}</div>}
        </fieldset>
      </div>

      <div className="template-actions-column">
        <fieldset className="koi-group">
          <legend>⚙️ 模板操作</legend>
          <div className="template-operation-grid">
            <button type="button" className="koi-button secondary" onClick={() => { const template = requireSelection(); if (template) setViewerTemplate(template); }}>👁️ 查看模板</button>
            <button type="button" className="koi-button secondary" onClick={() => { const template = requireSelection(); if (template) setEditorState({ mode: 'edit', template }); }}>✏️ 编辑模板</button>
            <button type="button" className="koi-button danger" onClick={() => { const template = requireSelection(); if (template) setDeleteTarget(template); }}>🗑️ 删除模板</button>
            <button type="button" className="koi-button secondary" onClick={importTemplate} disabled={isBusy}>📥 导入模板</button>
            <button type="button" className="koi-button secondary" onClick={exportTemplate} disabled={isBusy}>📤 导出模板</button>
            <button type="button" className="koi-button secondary" onClick={() => openBackendPath(lastExportPath, setStatus)} disabled={isBusy || !lastExportPath}>📂 打开导出</button>
            <button type="button" className="koi-button primary" onClick={() => setEditorState({ mode: 'create' })}>➕ 创建模板</button>
          </div>
          <label className="checkbox-row template-import-option"><input type="checkbox" checked={overwriteImport} onChange={(event) => setOverwriteImport(event.target.checked)} /> 导入时覆盖同名模板</label>
          {selectedTemplate && <div className="modal-message template-selected-summary">当前模板: {selectedTemplate.name}</div>}
        </fieldset>
      </div>

      {viewerTemplate && <TemplateDetailModal template={viewerTemplate} onClose={() => setViewerTemplate(null)} />}
      {editorState && (
        <TemplateEditorModal
          mode={editorState.mode}
          template={editorState.template}
          onClose={() => setEditorState(null)}
          onSave={saveTemplate}
          onChooseTarget={(defaultPath) => openFilePath({ title: '选择目标模板文件', defaultPath, filters: [{ name: 'Excel模板', extensions: ['xlsx', 'xls'] }, { name: '所有文件', extensions: ['*'] }] })}
        />
      )}
      {deleteTarget && <ConfirmModal title="确认删除" message={`确定要删除模板 '${deleteTarget.name}' 吗？此操作不可撤销。`} onCancel={() => setDeleteTarget(null)} onConfirm={deleteTemplate} busy={isBusy} />}
      {fileDialog}
    </div>
  );
}

export const dataProcessingModule: KoiModule = {
  id: 'data-processing',
  title: '数据处理',
  functions: [
    {
      id: 'field-extraction',
      title: '📄 字段提取',
      component: FieldExtractionPage,
    },
    {
      id: 'data-filling',
      title: '📝 数据填充',
      component: DataFillingPage,
    },
    {
      id: 'template-management',
      title: '📋 模板管理',
      component: TemplateManagementPage,
    },
  ],
};
