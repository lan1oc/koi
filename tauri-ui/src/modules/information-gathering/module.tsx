import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend, isTauriRuntime } from '../../lib/backend';
import { openBackendPath } from '../../lib/open-path';
import type { KoiModule } from '../../lib/types';

type Row = Record<string, unknown>;

type QueryResponse = {
  success: boolean;
  message: string;
  rows?: Row[];
  formatted?: string;
  raw?: unknown;
  logs?: string[];
  result?: unknown;
  results?: unknown;
  errors?: string[];
};

type ConfigResponse = {
  fofa?: { email?: string; api_key?: string };
  hunter?: { api_key?: string };
  quake?: { api_key?: string };
  tyc?: { cookie?: string };
  aiqicha?: { cookie?: string; xunkebao_cookie?: string };
  threatbook_api_key?: string;
};

type ClassificationGroup = {
  name: string;
  companies: string[];
  company_count?: number;
};

type ClassificationResponse = {
  success: boolean;
  message: string;
  groups?: ClassificationGroup[];
  total_groups?: number;
  total_companies?: number;
};

type ExportTextResponse = {
  success: boolean;
  message: string;
  output_file?: string;
  bytes?: number;
};

type OpenUrlResponse = {
  success: boolean;
  message: string;
  url?: string;
};

type SyntaxDocResponse = {
  success: boolean;
  message: string;
  platform: string;
  title: string;
  text: string;
  common_fields?: unknown;
  examples?: unknown;
};

type Column = {
  title: string;
  key?: string;
  render?: (row: Row, index: number) => ReactNode;
};

type TabItem = {
  id: string;
  title: string;
  content: ReactNode;
};

const PLATFORM_OPTIONS = ['fofa', 'hunter', 'quake'] as const;
type AssetPlatform = typeof PLATFORM_OPTIONS[number] | 'unified';
type ThreatMode = 'ip' | 'ip_batch' | 'dns' | 'file_report' | 'file_multiengines' | 'file_upload';
const ALL_THREAT_MODES: ThreatMode[] = ['ip', 'ip_batch', 'dns', 'file_report', 'file_multiengines', 'file_upload'];
const THREAT_IP_MODES: ThreatMode[] = ['ip', 'ip_batch'];
const THREAT_DNS_MODES: ThreatMode[] = ['dns'];
const THREAT_FILE_MODES: ThreatMode[] = ['file_report', 'file_multiengines', 'file_upload'];

function text(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join(', ');
  return JSON.stringify(value);
}

function toPrettyText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function rowsToText(rows?: Row[]) {
  if (!rows?.length) return '';
  return rows.map((row, index) => {
    const parts = Object.entries(row)
      .filter(([key]) => key !== 'raw')
      .map(([key, value]) => `${key}: ${text(value)}`);
    return `[${index + 1}] ${parts.join(' | ')}`;
  }).join('\n');
}

function getFileName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function statusClass(success: unknown) {
  return success === true || String(success).toLowerCase() === 'true' ? 'ok' : 'warn';
}

function boolLabel(success: unknown) {
  return success === true || String(success).toLowerCase() === 'true' ? '成功' : '失败';
}

function modeLabel(mode: ThreatMode) {
  const labels: Record<ThreatMode, string> = {
    ip: 'IP 信誉查询',
    ip_batch: '批量 IP 查询',
    dns: '域名失陷检测',
    file_report: '文件报告查询',
    file_multiengines: '多引擎检测',
    file_upload: '文件上传分析',
  };
  return labels[mode];
}

function platformLabel(platform: AssetPlatform | string) {
  const labels: Record<string, string> = {
    unified: '统一资产查询',
    fofa: 'FOFA',
    hunter: 'Hunter',
    quake: 'Quake',
  };
  return labels[platform] ?? String(platform).toUpperCase();
}

function FilePicker({
  value,
  title,
  buttonText = '浏览...',
  filters,
  onChange,
}: {
  value: string;
  title: string;
  buttonText?: string;
  filters?: Array<{ name: string; extensions: string[] }>;
  onChange: (value: string) => void;
}) {
  const { dialog, openFilePath } = useProjectFileDialog();
  const pick = async () => {
    const selected = await openFilePath({ title, defaultPath: value, filters: filters ?? [{ name: '所有文件', extensions: ['*'] }] });
    if (selected) onChange(selected);
  };
  return (
    <div className="file-selector-row wide-file-row">
      <input className="koi-input" value={value} onChange={(event) => onChange(event.target.value)} placeholder={title} />
      <button type="button" className="koi-button secondary compact-button" onClick={pick}>{buttonText}</button>
      {dialog}
    </div>
  );
}

function ModalShell({
  title,
  width = 'normal',
  onClose,
  children,
}: {
  title: string;
  width?: 'normal' | 'wide';
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="modal-backdrop">
      <section className={`koi-modal ${width === 'wide' ? 'wide' : ''}`}>
        <div className="modal-title-row">
          <h3>{title}</h3>
          <button type="button" className="modal-close-button" aria-label="关闭" onClick={onClose}>X</button>
        </div>
        <div className="modal-separator" />
        {children}
      </section>
    </div>
  );
}

function TabWidget({ tabs }: { tabs: TabItem[] }) {
  const [activeTab, setActiveTab] = useState(tabs[0]?.id ?? '');

  useEffect(() => {
    if (!tabs.length || tabs.some((tab) => tab.id === activeTab)) return;
    setActiveTab(tabs[0].id);
  }, [tabs, activeTab]);

  return (
    <div className="koi-tab-widget nested-tab-widget info-nested-tab-widget">
      <div className="tab-bar">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab-button${tab.id === activeTab ? ' active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.title}
          </button>
        ))}
      </div>
      <div className="tab-content tab-panels">
        {tabs.map((tab) => (
          <div key={tab.id} className={`tab-panel${tab.id === activeTab ? ' active' : ' inactive'}`} aria-hidden={tab.id !== activeTab}>
            {tab.content}
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultTable({
  rows,
  columns,
  selectedIndex,
  onSelect,
}: {
  rows: Row[];
  columns: Column[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}) {
  return (
    <div className="result-table-scroll">
      <table className="result-table">
        <thead>
          <tr>{columns.map((column) => <th key={column.title}>{column.title}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length ? rows.map((row, index) => (
            <tr key={index} className={`clickable-row${selectedIndex === index ? ' selected-row' : ''}`} onClick={() => onSelect(index)}>
              {columns.map((column) => <td key={column.title}>{column.render ? column.render(row, index) : text(row[column.key ?? ''])}</td>)}
            </tr>
          )) : <tr><td colSpan={columns.length}>暂无结果</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function ResultPanel({
  title,
  status,
  rows,
  columns,
  detailText,
  summary,
  renderDetail,
}: {
  title: string;
  status: string;
  rows: Row[];
  columns: Column[];
  detailText: string;
  summary?: ReactNode;
  renderDetail?: (row: Row | undefined, fallbackText: string) => ReactNode;
}) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(rows.length ? 0 : null);
  const selected = selectedIndex === null ? undefined : rows[selectedIndex];

  useEffect(() => {
    setSelectedIndex(rows.length ? 0 : null);
  }, [rows]);

  return (
    <section className="result-panel table-result-panel asset-results-panel">
      <div className="status-strip visible-status">{status}</div>
      <h3>{title}</h3>
      {summary}
      <ResultTable rows={rows} columns={columns} selectedIndex={selectedIndex} onSelect={setSelectedIndex} />
      {renderDetail ? renderDetail(selected, detailText) : (
        <textarea className="result-textarea asset-detail-text" readOnly value={selected ? toPrettyText(selected.raw ?? selected) : detailText} />
      )}
    </section>
  );
}

function ExportTextButton({ content, defaultFileName, onStatus }: { content: string; defaultFileName: string; onStatus: (message: string) => void }) {
  const { dialog, saveFilePath } = useProjectFileDialog();
  const [lastExportPath, setLastExportPath] = useState('');

  const run = async () => {
    if (!content.trim()) {
      onStatus('没有可导出的内容');
      return;
    }
    const selected = await saveFilePath({
      title: '导出结果',
      defaultPath: defaultFileName.replace(/[\\/:*?"<>|]+/g, '_'),
      filters: [
        { name: '文本文件', extensions: ['txt'] },
        { name: 'JSON 文件', extensions: ['json'] },
        { name: 'CSV 文件', extensions: ['csv'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (!selected) {
      onStatus('已取消导出');
      return;
    }
    try {
      const result = await callBackend<ExportTextResponse>('info.export_text', { output_file: selected, content });
      setLastExportPath(result.output_file ?? selected);
      onStatus(result.message || '导出完成');
    } catch (error) {
      onStatus(`导出失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <>
      <button type="button" className="koi-button secondary" onClick={run}>导出结果</button>
      <button type="button" className="koi-button secondary" onClick={() => openBackendPath(lastExportPath, onStatus)} disabled={!lastExportPath}>打开导出</button>
      {dialog}
    </>
  );
}

function useInfoConfig() {
  const [config, setConfig] = useState<ConfigResponse>({});
  const load = async () => {
    const result = await callBackend<ConfigResponse>('info.config.get', {});
    setConfig(result);
    return result;
  };
  const save = async (payload: Record<string, string>) => {
    const result = await callBackend<ConfigResponse>('info.config.set', payload);
    setConfig(result);
    return result;
  };
  return { config, load, save };
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(text).filter(Boolean);
  const valueText = text(value);
  return valueText ? [valueText] : [];
}

function exampleGroups(value: unknown): Array<{ title: string; queries: string[] }> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>)
    .map(([title, queries]) => ({ title, queries: stringArray(queries) }))
    .filter((group) => group.queries.length > 0);
}

function syntaxSections(value: string): Array<{ title: string; lines: string[] }> {
  const sections: Array<{ title: string; lines: string[] }> = [];
  let current: { title: string; lines: string[] } | null = null;
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const isTitle = !line.includes(' | ') && (
      line.endsWith('语法') ||
      line.endsWith('类') ||
      line.endsWith('符') ||
      line.endsWith('查询') ||
      line.includes('语法文档') ||
      line.includes('示例查询') ||
      line.includes('逻辑运算') ||
      line.includes('范围查询')
    );
    if (isTitle) {
      current = { title: line, lines: [] };
      sections.push(current);
    } else {
      if (!current) {
        current = { title: '文档内容', lines: [] };
        sections.push(current);
      }
      current.lines.push(line);
    }
  }
  return sections;
}

function SyntaxDocLine({ line }: { line: string }) {
  const tableCells = line.split(' | ').map((cell) => cell.trim()).filter(Boolean);
  if (tableCells.length >= 2) {
    return (
      <div className="syntax-line-table">
        {tableCells.map((cell, index) => <span key={`${cell}-${index}`}>{cell}</span>)}
      </div>
    );
  }

  const dashIndex = line.indexOf(' - ');
  if (dashIndex > 0) {
    return (
      <p className="syntax-line-text">
        <code>{line.slice(0, dashIndex)}</code>
        <span>{line.slice(dashIndex + 3)}</span>
      </p>
    );
  }

  return <p>{line}</p>;
}

function SyntaxDocBody({ doc }: { doc: SyntaxDocResponse | null }) {
  const fields = stringArray(doc?.common_fields);
  const groups = exampleGroups(doc?.examples);
  const sections = syntaxSections(doc?.text ?? '');

  return (
    <div className="syntax-doc-body">
      <section className="syntax-card syntax-fields-card">
        <h4>常用字段</h4>
        <div className="syntax-field-cloud">
          {fields.length ? fields.map((field) => <code key={field}>{field}</code>) : <span>暂无字段信息</span>}
        </div>
      </section>

      <section className="syntax-card syntax-examples-card">
        <h4>查询示例</h4>
        <div className="syntax-example-grid">
          {groups.length ? groups.map((group) => (
            <div key={group.title} className="syntax-example-group">
              <h5>{group.title}</h5>
              {group.queries.map((query) => <code key={query}>{query}</code>)}
            </div>
          )) : <span>暂无示例</span>}
        </div>
      </section>

      <section className="syntax-card syntax-sections-card">
        <h4>完整语法</h4>
        <div className="syntax-section-list">
          {sections.length ? sections.map((section, sectionIndex) => (
            <details key={`${section.title}-${sectionIndex}`} className="syntax-section" open={sections.length <= 4 || section.title.includes('基础')}>
              <summary>{section.title}</summary>
              <div className="syntax-section-lines">
                {section.lines.map((line, index) => <SyntaxDocLine key={`${section.title}-${index}`} line={line} />)}
              </div>
            </details>
          )) : <p>暂无文档内容</p>}
        </div>
      </section>
    </div>
  );
}

function SyntaxDialog({ platform, onClose }: { platform: Exclude<AssetPlatform, 'unified'>; onClose: () => void }) {
  const [status, setStatus] = useState('正在加载语法文档...');
  const [doc, setDoc] = useState<SyntaxDocResponse | null>(null);

  useEffect(() => {
    let alive = true;
    callBackend<SyntaxDocResponse>('info.asset.syntax_doc', { platform })
      .then((result) => {
        if (!alive) return;
        setDoc(result);
        setStatus(result.message || '语法文档已加载');
      })
      .catch((error) => {
        if (!alive) return;
        setStatus(`加载失败: ${error instanceof Error ? error.message : String(error)}`);
      });
    return () => {
      alive = false;
    };
  }, [platform]);

  return (
    <ModalShell title={`${platformLabel(platform)} 查询语法`} width="wide" onClose={onClose}>
      <div className="status-strip visible-status">{status}</div>
      <SyntaxDocBody doc={doc} />
      <div className="modal-actions">
        <button type="button" className="koi-button primary" onClick={onClose}>关闭</button>
      </div>
    </ModalShell>
  );
}

const enterpriseColumns: Column[] = [
  { title: '#', render: (row, index) => text(row.index) || String(index + 1) },
  { title: '来源', key: 'source' },
  { title: '查询词', key: 'query' },
  { title: '企业名称', key: 'company_name' },
  { title: '法定代表人', key: 'legal_person' },
  { title: '注册资本', key: 'reg_capital' },
  { title: '统一信用代码', key: 'credit_code' },
  { title: '电话', key: 'phone' },
  { title: '状态', render: (row) => <span className={`cookie-status-detail ${statusClass(row.success)}`}>{boolLabel(row.success)}</span> },
];

type DetailField = {
  label: string;
  value: unknown;
};

type DetailTable = {
  title: string;
  rows: Row[];
  columns: Array<{ title: string; key: string }>;
};

function firstRecord(value: unknown): Row {
  if (Array.isArray(value)) {
    return asRecord(value.find((item) => item && typeof item === 'object'));
  }
  return asRecord(value);
}

function listRecords(value: unknown): Row[] {
  if (!Array.isArray(value)) return [];
  return value.map(asRecord).filter((item) => Object.keys(item).length > 0);
}

function pickValue(record: Row, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    const valueText = Array.isArray(value) ? value.map(text).filter(Boolean).join(', ') : text(value);
    if (valueText) return valueText;
  }
  return '';
}

function fieldValue(value: unknown): string {
  const valueText = Array.isArray(value) ? value.map(text).filter(Boolean).join(', ') : text(value);
  return valueText || '-';
}

function DetailFieldsSection({ title, fields }: { title: string; fields: DetailField[] }) {
  const visibleFields = fields.filter((field) => fieldValue(field.value) !== '-');
  if (!visibleFields.length) return null;
  return (
    <section className="enterprise-detail-section">
      <h4>{title}</h4>
      <div className="enterprise-detail-grid">
        {visibleFields.map((field) => (
          <div key={field.label} className="enterprise-detail-field">
            <span>{field.label}</span>
            <strong>{fieldValue(field.value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function EnterpriseDetailSection({ title, fields }: { title: string; fields: DetailField[] }) {
  return <DetailFieldsSection title={title} fields={fields} />;
}

function EnterpriseDetailTable({ table }: { table: DetailTable }) {
  if (!table.rows.length) return null;
  return (
    <section className="enterprise-detail-section">
      <h4>{table.title} ({table.rows.length})</h4>
      <div className="result-table-scroll enterprise-mini-table-scroll">
        <table className="result-table enterprise-mini-table">
          <thead>
            <tr>{table.columns.map((column) => <th key={column.key}>{column.title}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={index}>
                {table.columns.map((column) => <td key={column.key}>{fieldValue(row[column.key])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function extractEnterpriseRaw(row: Row | undefined): Row {
  const raw = asRecord(row?.raw ?? row);
  const rawCompanies = raw.companies ?? asRecord(raw.data).companies;
  const firstCompany = firstRecord(rawCompanies);
  if (Object.keys(firstCompany).length) return firstCompany;
  if (Object.keys(asRecord(raw.data)).length) return asRecord(raw.data);
  return raw;
}

function enterpriseBasicFields(source: 'tyc' | 'aiqicha', row: Row | undefined): DetailField[] {
  const raw = extractEnterpriseRaw(row);
  if (source === 'tyc') {
    const categories = ['categoryNameLv1', 'categoryNameLv2', 'categoryNameLv3', 'categoryNameLv4']
      .map((key) => text(raw[key]))
      .filter(Boolean)
      .join(' > ');
    return [
      { label: '企业名称', value: pickValue(raw, ['name', 'company_name']) || row?.company_name },
      { label: '法定代表人', value: pickValue(raw, ['legalPersonName', 'legal_person']) || row?.legal_person },
      { label: '注册资本', value: pickValue(raw, ['regCapital', 'reg_capital']) || row?.reg_capital },
      { label: '成立日期', value: pickValue(raw, ['estiblishTime', 'establishTime', 'openTime']) },
      { label: '统一社会信用代码', value: pickValue(raw, ['creditCode', 'credit_code']) || row?.credit_code },
      { label: '企业状态', value: pickValue(raw, ['regStatus', 'status']) },
      { label: '注册地址', value: pickValue(raw, ['regLocation', 'address']) || row?.address },
      { label: '联系电话', value: pickValue(raw, ['phoneList', 'phone', 'telephone']) || row?.phone },
      { label: '邮箱', value: pickValue(raw, ['emailList', 'email']) || row?.email },
      { label: '网址', value: pickValue(raw, ['websites', 'website']) || row?.website },
      { label: '行业分类', value: categories || pickValue(raw, ['industryCategory', 'industry']) },
    ];
  }

  const basic = asRecord(raw.basic_info);
  const industry = asRecord(raw.industry_info);
  const industryPath = ['industryCode1', 'industryCode2', 'industryCode3', 'industryCode4']
    .map((key) => text(industry[key]))
    .filter(Boolean)
    .join(' > ');
  return [
    { label: '企业名称', value: pickValue(raw, ['company_name']) || row?.company_name },
    { label: '法定代表人', value: pickValue(basic, ['legalPerson']) || row?.legal_person },
    { label: '注册资本', value: pickValue(basic, ['regCap']) || row?.reg_capital },
    { label: '成立日期', value: pickValue(basic, ['openTime', 'startDate']) },
    { label: '统一社会信用代码', value: pickValue(basic, ['regNo']) || row?.credit_code },
    { label: '企业地址', value: pickValue(basic, ['titleDomicile']) || row?.address },
    { label: '联系电话', value: pickValue(basic, ['telephone']) || row?.phone },
    { label: '更多电话', value: raw.contact_info },
    { label: '邮箱', value: pickValue(basic, ['email']) || row?.email },
    { label: '员工邮箱', value: industry.employee_emails },
    { label: '网址', value: pickValue(basic, ['website']) || row?.website },
    { label: '行业分类', value: industryPath || pickValue(industry, ['industryNum']) },
  ];
}

function enterpriseDetailTables(source: 'tyc' | 'aiqicha', row: Row | undefined): DetailTable[] {
  const raw = extractEnterpriseRaw(row);
  if (source === 'tyc') {
    return [
      {
        title: 'ICP备案信息',
        rows: listRecords(raw.icp_records),
        columns: [
          { title: '网站名称', key: 'webName' },
          { title: '域名', key: 'ym' },
          { title: '许可证号', key: 'liscense' },
          { title: '审核日期', key: 'examineDate' },
        ],
      },
      {
        title: 'APP信息',
        rows: listRecords(raw.app_records),
        columns: [
          { title: 'APP名称', key: 'name' },
          { title: '产品分类', key: 'type' },
          { title: '领域', key: 'classes' },
        ],
      },
      {
        title: '微信公众号',
        rows: listRecords(raw.wechat_records),
        columns: [
          { title: '公众号名称', key: 'title' },
          { title: '微信号', key: 'publicNum' },
        ],
      },
    ];
  }

  return [
    {
      title: 'ICP备案信息',
      rows: listRecords(raw.icp_info),
      columns: [
        { title: '网站名称', key: 'siteName' },
        { title: '域名', key: 'domain' },
        { title: '备案号', key: 'icpNo' },
      ],
    },
    {
      title: 'APP信息',
      rows: listRecords(raw.app_info),
      columns: [
        { title: 'APP名称', key: 'name' },
        { title: '包名', key: 'packageName' },
      ],
    },
    {
      title: '微信公众号',
      rows: listRecords(raw.wechat_info),
      columns: [
        { title: '公众号名称', key: 'wechatName' },
        { title: '微信号', key: 'wechatId' },
      ],
    },
  ];
}

function EnterpriseDetailPane({
  source,
  row,
  fallbackText,
}: {
  source: 'tyc' | 'aiqicha';
  row: Row | undefined;
  fallbackText: string;
}) {
  if (!row) {
    return <textarea className="result-textarea asset-detail-text" readOnly value={fallbackText} />;
  }

  const rawDetail = toPrettyText(row.raw ?? row);
  const tables = enterpriseDetailTables(source, row);
  return (
    <div className="enterprise-detail-pane">
      <EnterpriseDetailSection title="基本信息" fields={enterpriseBasicFields(source, row)} />
      {tables.map((table) => <EnterpriseDetailTable key={table.title} table={table} />)}
      <details className="enterprise-raw-detail">
        <summary>原始返回</summary>
        <textarea className="result-textarea asset-detail-text" readOnly value={rawDetail} />
      </details>
    </div>
  );
}

function EnterpriseQueryPage({ source }: { source: 'tyc' | 'aiqicha' }) {
  const { config, load, save } = useInfoConfig();
  const [loaded, setLoaded] = useState(false);
  const [company, setCompany] = useState('');
  const [batchFile, setBatchFile] = useState('');
  const [batchMode, setBatchMode] = useState(false);
  const [cookie, setCookie] = useState('');
  const [xunkebaoCookie, setXunkebaoCookie] = useState('');
  const [cookieConfigured, setCookieConfigured] = useState(false);
  const [xunkebaoCookieConfigured, setXunkebaoCookieConfigured] = useState(false);
  const [status, setStatus] = useState('等待查询');
  const [rows, setRows] = useState<Row[]>([]);
  const [resultText, setResultText] = useState('');
  const [busy, setBusy] = useState(false);

  const displayName = source === 'tyc' ? '天眼查' : '爱企查';
  const backendName = source === 'tyc' ? 'tyc' : 'aiqicha';

  const ensureConfig = async () => {
    if (loaded) return;
    const next = await load();
    setCookie('');
    setXunkebaoCookie('');
    setCookieConfigured(Boolean(source === 'tyc' ? next.tyc?.cookie : next.aiqicha?.cookie));
    setXunkebaoCookieConfigured(Boolean(next.aiqicha?.xunkebao_cookie));
    setLoaded(true);
  };

  useEffect(() => {
    void ensureConfig();
  }, []);

  const saveCookie = async () => {
    try {
      if (source === 'tyc') {
        if (!cookie.trim()) {
          setStatus('未输入新的 Cookie，配置未变更');
          return;
        }
        await save({ tyc_cookie: cookie });
      } else {
        const payload: Record<string, string> = {};
        if (cookie.trim()) payload.aiqicha_cookie = cookie;
        if (xunkebaoCookie.trim()) payload.xunkebao_cookie = xunkebaoCookie;
        if (!Object.keys(payload).length) {
          setStatus('未输入新的 Cookie，配置未变更');
          return;
        }
        await save(payload);
      }
      setCookieConfigured((current) => current || Boolean(cookie.trim()));
      setXunkebaoCookieConfigured((current) => current || Boolean(xunkebaoCookie.trim()));
      setCookie('');
      setXunkebaoCookie('');
      setStatus(`${displayName} Cookie 已保存`);
    } catch (error) {
      setStatus(`保存 Cookie 失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const runQuery = async () => {
    await ensureConfig();
    if (!batchMode && !company.trim()) {
      setStatus('请输入企业名称');
      return;
    }
    if (batchMode && !batchFile.trim()) {
      setStatus('请选择企业名单文件');
      return;
    }
    setBusy(true);
    setStatus(`正在查询 ${displayName}...`);
    try {
      const command = source === 'tyc' ? 'info.enterprise.tyc.query' : 'info.enterprise.aiqicha.query';
      const result = await callBackend<QueryResponse>(command, batchMode ? { batch_file: batchFile } : { company });
      const nextRows = result.rows ?? [];
      const nextText = [
        result.formatted,
        nextRows.length ? rowsToText(nextRows) : '',
        result.logs?.length ? `日志:\n${result.logs.join('\n')}` : '',
        result.raw ? `原始返回:\n${toPrettyText(result.raw)}` : '',
      ].filter(Boolean).join('\n\n');
      setRows(nextRows);
      setResultText(nextText);
      setStatus(result.message || (result.success ? '查询完成' : '查询失败'));
    } catch (error) {
      setRows([]);
      setResultText('');
      setStatus(`查询失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const summary = (
    <div className="result-summary-grid">
      <span>结果数: {rows.length}</span>
      <span>Cookie: {cookieConfigured ? '已配置' : '未配置'}</span>
      <span>模式: {batchMode ? '批量查询' : '单个查询'}</span>
    </div>
  );

  return (
    <div className="enterprise-source-page vertical-detail scroll-page-layout">
      <div className="control-stack">
        <fieldset className="koi-group">
          <legend>{displayName} Cookie</legend>
          <textarea className="koi-input modal-textarea" value={cookie} onChange={(event) => setCookie(event.target.value)} placeholder={`已配置时不会回显；需要更新时粘贴新的 ${displayName} Cookie`} />
          {source === 'aiqicha' ? <textarea className="koi-input modal-textarea short-textarea" value={xunkebaoCookie} onChange={(event) => setXunkebaoCookie(event.target.value)} placeholder="已配置时不会回显；需要更新时粘贴新的寻客宝 Cookie（可选）" /> : null}
          <div className="action-row">
            <button type="button" className="koi-button secondary" onClick={saveCookie}>保存 Cookie</button>
            <span className={`cookie-status-detail ${cookieConfigured ? 'ok' : 'warn'}`}>{cookieConfigured ? '已配置' : '未配置'}</span>
            {source === 'aiqicha' ? <span className={`cookie-status-detail ${xunkebaoCookieConfigured ? 'ok' : 'empty'}`}>寻客宝{xunkebaoCookieConfigured ? '已配置' : '未配置'}</span> : null}
          </div>
        </fieldset>

        <fieldset className="koi-group">
          <legend>查询输入</legend>
          <div className="radio-row">
            <label><input type="radio" checked={!batchMode} onChange={() => setBatchMode(false)} /> 单个企业</label>
            <label><input type="radio" checked={batchMode} onChange={() => setBatchMode(true)} /> 批量文件</label>
          </div>
          <label className="field-row horizontal-field">
            <span>企业名称</span>
            <input className="koi-input" value={company} onChange={(event) => setCompany(event.target.value)} disabled={batchMode} placeholder="请输入公司名称" />
          </label>
          <FilePicker
            value={batchFile}
            title="选择企业名单文件"
            filters={[
              { name: '数据文件', extensions: ['xlsx', 'xls', 'csv', 'txt', 'tsv'] },
              { name: '所有文件', extensions: ['*'] },
            ]}
            onChange={(value) => {
              setBatchFile(value);
              setBatchMode(true);
            }}
          />
        </fieldset>

        <div className="action-row two-buttons">
          <button type="button" className="koi-button primary" onClick={runQuery} disabled={busy}>开始查询</button>
          <ExportTextButton content={resultText} defaultFileName={`${backendName}_enterprise_results.txt`} onStatus={setStatus} />
          <button type="button" className="koi-button danger" onClick={() => { setRows([]); setResultText(''); setStatus('结果已清空'); }}>清空结果</button>
        </div>
      </div>

      <ResultPanel
        title={`${displayName} 查询结果`}
        status={status}
        rows={rows}
        columns={enterpriseColumns}
        detailText={resultText}
        summary={summary}
        renderDetail={(selected, fallbackText) => <EnterpriseDetailPane source={source} row={selected} fallbackText={fallbackText} />}
      />
    </div>
  );
}

const assetColumns: Column[] = [
  { title: '#', render: (row, index) => text(row.index) || String(index + 1) },
  { title: '平台', render: (row) => platformLabel(text(row.platform)) },
  { title: '查询语句', key: 'query' },
  { title: '目标', render: (row) => text(row.host) || text(row.url) || text(row.hostname) || text(row.domain) || text(row.ip) },
  { title: 'IP', key: 'ip' },
  { title: '端口', key: 'port' },
  { title: '标题', key: 'title' },
  { title: '位置/组织', render: (row) => text(row.country) || text(row.location) || text(row.org) || text(row.company) },
];

function AssetQueryPage({ platform }: { platform: AssetPlatform }) {
  const { config, load, save } = useInfoConfig();
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState('');
  const [batchFile, setBatchFile] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [email, setEmail] = useState('');
  const [page, setPage] = useState('1');
  const [size, setSize] = useState('100');
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['fofa', 'hunter', 'quake']);
  const [status, setStatus] = useState('等待查询');
  const [rows, setRows] = useState<Row[]>([]);
  const [resultText, setResultText] = useState('');
  const [busy, setBusy] = useState(false);
  const [syntaxOpen, setSyntaxOpen] = useState(false);

  const label = platformLabel(platform);

  const ensureConfig = async () => {
    if (loaded) return;
    const next = await load();
    setEmail(next.fofa?.email ?? '');
    if (platform === 'fofa') setApiKey(next.fofa?.api_key ?? '');
    if (platform === 'hunter') setApiKey(next.hunter?.api_key ?? '');
    if (platform === 'quake') setApiKey(next.quake?.api_key ?? '');
    setLoaded(true);
  };

  useEffect(() => {
    void ensureConfig();
  }, []);

  const saveConfig = async () => {
    try {
      if (platform === 'fofa') await save({ fofa_email: email, fofa_api_key: apiKey });
      if (platform === 'hunter') await save({ hunter_api_key: apiKey });
      if (platform === 'quake') await save({ quake_api_key: apiKey });
      setStatus(`${label} 配置已保存`);
    } catch (error) {
      setStatus(`保存配置失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const togglePlatform = (name: string) => {
    setSelectedPlatforms((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]);
  };

  const run = async () => {
    await ensureConfig();
    if (!query.trim() && !batchFile.trim()) {
      setStatus('请输入查询语句或选择批量文件');
      return;
    }
    if (platform === 'unified' && selectedPlatforms.length === 0) {
      setStatus('请至少选择一个查询平台');
      return;
    }
    setBusy(true);
    setStatus(`正在执行 ${label}...`);
    try {
      const command = platform === 'unified' ? 'info.asset.unified.query' : `info.asset.${platform}.query`;
      const payload = platform === 'unified'
        ? { query, batch_file: batchFile, platforms: selectedPlatforms, size: Number(size) || 100, page: Number(page) || 1 }
        : { query, size: Number(size) || 100, page: Number(page) || 1 };
      const result = await callBackend<QueryResponse>(command, payload);
      const nextRows = result.rows ?? [];
      const nextText = [
        rowsToText(nextRows),
        result.errors?.length ? `错误:\n${result.errors.join('\n')}` : '',
        result.logs?.length ? `日志:\n${result.logs.join('\n')}` : '',
        result.raw ? `原始返回:\n${toPrettyText(result.raw)}` : '',
      ].filter(Boolean).join('\n\n');
      setRows(nextRows);
      setResultText(nextText);
      setStatus(result.message || (result.success ? '查询完成' : '查询失败'));
    } catch (error) {
      setRows([]);
      setResultText('');
      setStatus(`查询失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const summary = (
    <div className="result-summary-grid">
      <span>结果数: {rows.length}</span>
      <span>平台: {platform === 'unified' ? selectedPlatforms.map(platformLabel).join(', ') : label}</span>
      <span>分页: 第 {page || '1'} 页 / {size || '100'} 条</span>
    </div>
  );

  return (
    <div className="vertical-detail scroll-page-layout">
      <fieldset className="koi-group">
        <legend>{label} 配置</legend>
        {platform === 'fofa' ? <input className="koi-input" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="FOFA 邮箱" /> : null}
        {platform !== 'unified' ? <input className="koi-input" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="API Key" /> : null}
        {platform === 'unified' ? (
          <div className="checkbox-grid">
            {PLATFORM_OPTIONS.map((name) => <label key={name}><input type="checkbox" checked={selectedPlatforms.includes(name)} onChange={() => togglePlatform(name)} /> {platformLabel(name)}</label>)}
          </div>
        ) : null}
        <div className="action-row">
          {platform !== 'unified' ? <button type="button" className="koi-button secondary" onClick={saveConfig}>保存配置</button> : null}
          {platform !== 'unified' ? <button type="button" className="koi-button secondary" onClick={() => setSyntaxOpen(true)}>查看语法</button> : null}
        </div>
      </fieldset>

      <fieldset className="koi-group">
        <legend>查询条件</legend>
        <textarea className="koi-input modal-textarea" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="请输入查询语句" />
        {platform === 'unified' ? (
          <FilePicker
            value={batchFile}
            title="选择批量查询文件"
            filters={[{ name: '文本/表格文件', extensions: ['txt', 'csv', 'tsv', 'xlsx', 'xls'] }, { name: '所有文件', extensions: ['*'] }]}
            onChange={setBatchFile}
          />
        ) : null}
        <div className="template-select-row">
          <label className="field-row inline-field"><span>页码:</span><input className="koi-input" value={page} onChange={(event) => setPage(event.target.value)} /></label>
          <label className="field-row inline-field"><span>数量:</span><input className="koi-input" value={size} onChange={(event) => setSize(event.target.value)} /></label>
        </div>
      </fieldset>

      <div className="action-row">
        <button type="button" className="koi-button primary" onClick={run} disabled={busy}>开始查询</button>
        <ExportTextButton content={resultText} defaultFileName={`${platform}_asset_results.txt`} onStatus={setStatus} />
        <button type="button" className="koi-button danger" onClick={() => { setRows([]); setResultText(''); setStatus('结果已清空'); }}>清空结果</button>
      </div>

      <ResultPanel title={`${label} 结果`} status={status} rows={rows} columns={assetColumns} detailText={resultText} summary={summary} />
      {syntaxOpen && platform !== 'unified' ? <SyntaxDialog platform={platform} onClose={() => setSyntaxOpen(false)} /> : null}
    </div>
  );
}

function ClassificationPage() {
  const [groups, setGroups] = useState<ClassificationGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [selectedCompany, setSelectedCompany] = useState('');
  const [targetGroup, setTargetGroup] = useState('');
  const [newGroup, setNewGroup] = useState('');
  const [renameGroupName, setRenameGroupName] = useState('');
  const [renameCompanyName, setRenameCompanyName] = useState('');
  const [newCompanies, setNewCompanies] = useState('');
  const [status, setStatus] = useState('正在加载分类...');
  const [busy, setBusy] = useState(false);

  const selected = groups.find((group) => group.name === selectedGroup);

  const load = async (preferredGroup?: string) => {
    let nextGroups: ClassificationGroup[] = [];
    let nextMessage = '';
    const isLocalPreview = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
    const forcePreview = isLocalPreview && new URLSearchParams(window.location.search).get('preview') === 'classification';
    if (forcePreview) {
      nextGroups = classificationPreviewGroups;
      nextMessage = '浏览器预览数据：已加载 37 个分组，1062 家企业';
    } else {
    try {
      const result = await callBackend<ClassificationResponse>('info.enterprise.classification.get', {});
      nextGroups = result.groups ?? [];
      nextMessage = result.message || `已加载 ${result.total_groups ?? 0} 个分组`;
    } catch (error) {
      if (!isLocalPreview || isTauriRuntime()) {
        throw error;
      }
      nextGroups = classificationPreviewGroups;
      nextMessage = '浏览器预览数据：已加载 37 个分组，1062 家企业';
    }
    }
    setGroups(nextGroups);
    setStatus(nextMessage);
    const nextSelected = preferredGroup || selectedGroup;
    const validSelected = nextGroups.find((group) => group.name === nextSelected)?.name ?? nextGroups[0]?.name ?? '';
    setSelectedGroup(validSelected);
    setTargetGroup((current) => nextGroups.find((group) => group.name === current)?.name ?? nextGroups.find((group) => group.name !== validSelected)?.name ?? '');
    setSelectedCompany('');
  };

  useEffect(() => {
    void load();
  }, []);

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setStatus(`操作失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const addGroup = () => runAction(async () => {
    if (!newGroup.trim()) {
      setStatus('请输入分组名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.add', { group_name: newGroup.trim() });
    setStatus(result.message || '分组已添加');
    const added = newGroup.trim();
    setNewGroup('');
    await load(added);
  });

  const renameGroup = () => runAction(async () => {
    if (!selectedGroup || !renameGroupName.trim()) {
      setStatus('请选择分组并输入新名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.rename', { old_name: selectedGroup, new_name: renameGroupName.trim() });
    setStatus(result.message || '分组已重命名');
    const renamed = renameGroupName.trim();
    setRenameGroupName('');
    await load(renamed);
  });

  const deleteGroup = () => runAction(async () => {
    if (!selectedGroup) {
      setStatus('请先选择分组');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.delete', { group_name: selectedGroup });
    setStatus(result.message || '分组已删除');
    await load();
  });

  const addCompanies = () => runAction(async () => {
    if (!selectedGroup || !newCompanies.trim()) {
      setStatus('请选择分组并输入企业名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.add', {
      group_name: selectedGroup,
      companies_text: newCompanies,
    });
    setStatus(result.message || '企业已添加');
    setNewCompanies('');
    await load(selectedGroup);
  });

  const renameCompany = () => runAction(async () => {
    if (!selectedGroup || !selectedCompany || !renameCompanyName.trim()) {
      setStatus('请选择企业并输入新名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.rename', {
      group_name: selectedGroup,
      old_name: selectedCompany,
      new_name: renameCompanyName.trim(),
    });
    setStatus(result.message || '企业已重命名');
    setRenameCompanyName('');
    await load(selectedGroup);
  });

  const deleteCompany = () => runAction(async () => {
    if (!selectedGroup || !selectedCompany) {
      setStatus('请先选择企业');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.delete', {
      group_name: selectedGroup,
      company_name: selectedCompany,
    });
    setStatus(result.message || '企业已删除');
    await load(selectedGroup);
  });

  const moveCompany = () => runAction(async () => {
    if (!selectedGroup || !targetGroup || !selectedCompany) {
      setStatus('请选择源分组、目标分组和企业');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.move', {
      source_group: selectedGroup,
      target_group: targetGroup,
      company_name: selectedCompany,
    });
    setStatus(result.message || '企业已移动');
    await load(selectedGroup);
  });

  return (
    <div className="classification-page scroll-page-layout">
      <div className="status-strip visible-status">{status}</div>
      <div className="classification-splitter">
        <section className="classification-pane">
          <fieldset className="koi-group">
            <legend>分组管理</legend>
            <select className="koi-input" value={selectedGroup} onChange={(event) => { setSelectedGroup(event.target.value); setSelectedCompany(''); }}>
              {groups.map((group) => <option key={group.name} value={group.name}>{group.name} ({group.company_count ?? group.companies.length})</option>)}
            </select>
            <input className="koi-input" value={newGroup} onChange={(event) => setNewGroup(event.target.value)} placeholder="新分组名称" />
            <button type="button" className="koi-button secondary" onClick={addGroup} disabled={busy}>添加分组</button>
            <input className="koi-input" value={renameGroupName} onChange={(event) => setRenameGroupName(event.target.value)} placeholder="分组新名称" />
            <div className="action-row">
              <button type="button" className="koi-button secondary" onClick={renameGroup} disabled={busy}>重命名</button>
              <button type="button" className="koi-button danger" onClick={deleteGroup} disabled={busy || !selectedGroup}>删除分组</button>
            </div>
          </fieldset>
        </section>

        <section className="classification-pane">
          <fieldset className="koi-group classification-enterprise-panel">
            <legend>企业列表</legend>
            <div className="classification-company-tools">
              <textarea className="koi-input modal-textarea short-textarea" value={newCompanies} onChange={(event) => setNewCompanies(event.target.value)} placeholder="新增企业，每行一个" />
              <button type="button" className="koi-button secondary" onClick={addCompanies} disabled={busy || !selectedGroup}>添加企业</button>
              <input className="koi-input" value={renameCompanyName} onChange={(event) => setRenameCompanyName(event.target.value)} placeholder="选中企业的新名称" />
              <div className="template-select-row">
                <select className="koi-input" value={targetGroup} onChange={(event) => setTargetGroup(event.target.value)}>
                  {groups.filter((group) => group.name !== selectedGroup).map((group) => <option key={group.name} value={group.name}>{group.name}</option>)}
                </select>
                <button type="button" className="koi-button secondary" onClick={moveCompany} disabled={busy || !selectedCompany || !targetGroup}>移动企业</button>
              </div>
              <div className="action-row">
                <button type="button" className="koi-button secondary" onClick={renameCompany} disabled={busy || !selectedCompany}>重命名企业</button>
                <button type="button" className="koi-button danger" onClick={deleteCompany} disabled={busy || !selectedCompany}>删除企业</button>
              </div>
            </div>
            <div className="qt-list-widget doc-file-list classification-company-list">
              {(selected?.companies ?? []).map((company) => (
                <button key={company} type="button" className={`qt-list-item selectable-list-item${selectedCompany === company ? ' selected' : ''}`} onClick={() => setSelectedCompany(company)}>
                  {company}
                </button>
              ))}
              {selected?.companies.length ? null : <div className="qt-list-item">当前分组暂无企业</div>}
            </div>
          </fieldset>
        </section>
      </div>
    </div>
  );
}

const classificationPreviewGroups: ClassificationGroup[] = [
  {
    name: '模糊镇',
    company_count: 16,
    companies: [
      '宁波力泰机械设备有限公司',
      '宁波市臻创网络科技有限公司',
      '宁波市鑫和混凝土有限公司',
      '宁波义浦工具有限公司',
      '宁波寰豪金属制品有限公司',
      '宁波东海智造科技有限公司',
      '宁波蓝海信息技术有限公司',
      '宁波恒跃安全设备有限公司',
      '宁波智联检测有限公司',
      '宁波星桥供应链有限公司',
      '宁波云栖网络有限公司',
      '宁波启明电子商务有限公司',
      '宁波甬安科技有限公司',
      '宁波海曙工程服务有限公司',
      '宁波北仑自动化有限公司',
      '宁波博远咨询有限公司',
    ],
  },
  { name: '高新区', company_count: 8, companies: ['宁波高新云智科技有限公司', '宁波数安网络科技有限公司', '宁波赛维信息技术有限公司'] },
  { name: '鄞州区', company_count: 12, companies: ['宁波鄞州网安服务有限公司', '宁波东钱湖文旅有限公司'] },
  { name: '未分类', company_count: 4, companies: ['宁波临时企业一', '宁波临时企业二'] },
  { name: '重点复测', company_count: 7, companies: ['宁波重点资产运营有限公司'] },
];

function ClassificationManagerPage() {
  const [groups, setGroups] = useState<ClassificationGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [selectedCompany, setSelectedCompany] = useState('');
  const [newGroup, setNewGroup] = useState('');
  const [renameGroupName, setRenameGroupName] = useState('');
  const [renameCompanyName, setRenameCompanyName] = useState('');
  const [newCompanies, setNewCompanies] = useState('');
  const [groupSearch, setGroupSearch] = useState('');
  const [companySearch, setCompanySearch] = useState('');
  const [contextMenu, setContextMenu] = useState<{ company: string; x: number; y: number } | null>(null);
  const [status, setStatus] = useState('正在加载分类...');
  const [busy, setBusy] = useState(false);

  const selected = groups.find((group) => group.name === selectedGroup);
  const selectedCompanies = selected?.companies ?? [];
  const moveTargets = groups.filter((group) => group.name !== selectedGroup);

  const filteredGroups = useMemo(() => {
    const keyword = groupSearch.trim().toLowerCase();
    if (!keyword) {
      return groups;
    }
    return groups.filter((group) => group.name.toLowerCase().includes(keyword));
  }, [groupSearch, groups]);

  const filteredCompanies = useMemo(() => {
    const keyword = companySearch.trim().toLowerCase();
    if (!keyword) {
      return selectedCompanies;
    }
    return selectedCompanies.filter((company) => company.toLowerCase().includes(keyword));
  }, [companySearch, selectedCompanies]);

  const load = async (preferredGroup?: string) => {
    const isLocalPreview = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
    const forcePreview = isLocalPreview && new URLSearchParams(window.location.search).get('preview') === 'classification';
    if (forcePreview) {
      const nextGroups = classificationPreviewGroups;
      setGroups(nextGroups);
      setStatus('浏览器预览数据：已加载 37 个分组，1062 家企业');
      const nextSelected = preferredGroup || selectedGroup;
      const validSelected = nextGroups.find((group) => group.name === nextSelected)?.name ?? nextGroups[0]?.name ?? '';
      setSelectedGroup(validSelected);
      setSelectedCompany('');
      setRenameCompanyName('');
      setContextMenu(null);
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.get', {});
    const nextGroups = result.groups ?? [];
    setGroups(nextGroups);
    setStatus(result.message || `已加载 ${result.total_groups ?? 0} 个分组`);
    const nextSelected = preferredGroup || selectedGroup;
    const validSelected = nextGroups.find((group) => group.name === nextSelected)?.name ?? nextGroups[0]?.name ?? '';
    setSelectedGroup(validSelected);
    setSelectedCompany('');
    setRenameCompanyName('');
    setContextMenu(null);
  };

  useEffect(() => {
    void load();
  }, []);

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setStatus(`操作失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const selectGroup = (groupName: string) => {
    setSelectedGroup(groupName);
    setSelectedCompany('');
    setRenameCompanyName('');
    setContextMenu(null);
  };

  const addGroup = () => runAction(async () => {
    const groupName = newGroup.trim();
    if (!groupName) {
      setStatus('请输入分组名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.add', { group_name: groupName });
    setStatus(result.message || '分组已添加');
    setNewGroup('');
    await load(groupName);
  });

  const renameGroup = () => runAction(async () => {
    const nextName = renameGroupName.trim();
    if (!selectedGroup || !nextName) {
      setStatus('请选择分组并输入新名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.rename', { old_name: selectedGroup, new_name: nextName });
    setStatus(result.message || '分组已重命名');
    setRenameGroupName('');
    await load(nextName);
  });

  const deleteGroup = () => runAction(async () => {
    if (!selectedGroup) {
      setStatus('请先选择分组');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.group.delete', { group_name: selectedGroup });
    setStatus(result.message || '分组已删除');
    await load();
  });

  const addCompanies = () => runAction(async () => {
    if (!selectedGroup || !newCompanies.trim()) {
      setStatus('请选择分组并输入企业名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.add', {
      group_name: selectedGroup,
      companies_text: newCompanies,
    });
    setStatus(result.message || '企业已添加');
    setNewCompanies('');
    await load(selectedGroup);
  });

  const renameCompany = () => runAction(async () => {
    const nextName = renameCompanyName.trim();
    if (!selectedGroup || !selectedCompany || !nextName) {
      setStatus('请选择企业并输入新名称');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.rename', {
      group_name: selectedGroup,
      old_name: selectedCompany,
      new_name: nextName,
    });
    setStatus(result.message || '企业已重命名');
    setRenameCompanyName('');
    await load(selectedGroup);
  });

  const deleteCompany = () => runAction(async () => {
    if (!selectedGroup || !selectedCompany) {
      setStatus('请先选择企业');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.delete', {
      group_name: selectedGroup,
      company_name: selectedCompany,
    });
    setStatus(result.message || '企业已删除');
    await load(selectedGroup);
  });

  const moveCompanyTo = (targetGroup: string) => runAction(async () => {
    const companyName = contextMenu?.company || selectedCompany;
    if (!selectedGroup || !targetGroup || !companyName) {
      setStatus('请选择要移动的企业和目标分组');
      return;
    }
    const result = await callBackend<ClassificationResponse>('info.enterprise.classification.company.move', {
      source_group: selectedGroup,
      target_group: targetGroup,
      company_name: companyName,
    });
    setStatus(result.message || '企业已移动');
    await load(selectedGroup);
  });

  const openCompanyMenu = (event: MouseEvent<HTMLButtonElement>, company: string) => {
    event.preventDefault();
    event.stopPropagation();
    setSelectedCompany(company);
    setRenameCompanyName(company);
    setContextMenu({
      company,
      x: Math.max(12, Math.min(event.clientX, window.innerWidth - 260)),
      y: Math.max(12, Math.min(event.clientY, window.innerHeight - 220)),
    });
  };

  const totalCompanies = groups.reduce((sum, group) => sum + (group.company_count ?? group.companies.length), 0);

  return (
    <div className="classification-page scroll-page-layout" onClick={() => setContextMenu(null)}>
      <div className="classification-status-row">
        <div className="status-strip visible-status">{status}</div>
        <div className="classification-counts">{groups.length} 个分组 / {totalCompanies} 家企业</div>
      </div>

      <div className="classification-splitter refined">
        <section className="classification-pane classification-group-pane">
          <div className="classification-pane-title">
            <strong>分组</strong>
            <span>{filteredGroups.length}/{groups.length}</span>
          </div>
          <input className="koi-input classification-search-input" value={groupSearch} onChange={(event) => setGroupSearch(event.target.value)} placeholder="搜索分组" />
          <div className="classification-group-list qt-list-widget">
            {filteredGroups.map((group) => (
              <button key={group.name} type="button" className={`classification-group-item${selectedGroup === group.name ? ' selected' : ''}`} onClick={() => selectGroup(group.name)}>
                <span>{group.name}</span>
                <strong>{group.company_count ?? group.companies.length}</strong>
              </button>
            ))}
            {filteredGroups.length ? null : <div className="classification-empty">没有匹配的分组</div>}
          </div>

          <div className="classification-editor-block">
            <div className="classification-editor-title">新增分组</div>
            <div className="classification-inline-action">
              <input className="koi-input" value={newGroup} onChange={(event) => setNewGroup(event.target.value)} placeholder="分组名称" />
              <button type="button" className="koi-button secondary compact-button" onClick={addGroup} disabled={busy}>添加</button>
            </div>
          </div>

          <div className="classification-editor-block">
            <div className="classification-editor-title">当前分组</div>
            <div className="classification-inline-action">
              <input className="koi-input" value={renameGroupName} onChange={(event) => setRenameGroupName(event.target.value)} placeholder={selectedGroup ? `重命名 ${selectedGroup}` : '先选择分组'} />
              <button type="button" className="koi-button secondary compact-button" onClick={renameGroup} disabled={busy || !selectedGroup}>重命名</button>
            </div>
            <button type="button" className="koi-button danger wide-action" onClick={deleteGroup} disabled={busy || !selectedGroup}>删除当前分组</button>
          </div>
        </section>

        <section className="classification-pane classification-company-pane">
          <div className="classification-company-header">
            <div>
              <span>企业</span>
              <strong>{selectedGroup || '未选择分组'}</strong>
            </div>
            <input className="koi-input classification-search-input" value={companySearch} onChange={(event) => setCompanySearch(event.target.value)} placeholder="搜索企业" />
          </div>

          <div className="classification-company-body">
            <div className="classification-company-list qt-list-widget">
              {filteredCompanies.map((company) => (
                <button
                  key={company}
                  type="button"
                  className={`qt-list-item selectable-list-item classification-company-item${selectedCompany === company ? ' selected' : ''}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedCompany(company);
                    setRenameCompanyName(company);
                    setContextMenu(null);
                  }}
                  onContextMenu={(event) => openCompanyMenu(event, company)}
                  title="右键移动到其它分组"
                >
                  {company}
                </button>
              ))}
              {selectedCompanies.length && !filteredCompanies.length ? <div className="classification-empty">没有匹配的企业</div> : null}
              {selectedCompanies.length ? null : <div className="classification-empty">当前分组暂无企业</div>}
            </div>

            <aside className="classification-company-side">
              <div className="classification-editor-block">
                <div className="classification-editor-title">新增企业</div>
                <textarea className="koi-input modal-textarea short-textarea" value={newCompanies} onChange={(event) => setNewCompanies(event.target.value)} placeholder="每行一个企业名称" />
                <button type="button" className="koi-button secondary wide-action" onClick={addCompanies} disabled={busy || !selectedGroup}>添加到当前分组</button>
              </div>

              <div className="classification-editor-block">
                <div className="classification-editor-title">选中企业</div>
                <div className="classification-selected-name">{selectedCompany || '未选择企业'}</div>
                <input className="koi-input" value={renameCompanyName} onChange={(event) => setRenameCompanyName(event.target.value)} placeholder="企业新名称" />
                <div className="classification-action-pair">
                  <button type="button" className="koi-button secondary compact-button" onClick={renameCompany} disabled={busy || !selectedCompany}>重命名</button>
                  <button type="button" className="koi-button danger compact-button" onClick={deleteCompany} disabled={busy || !selectedCompany}>删除</button>
                </div>
              </div>
            </aside>
          </div>
        </section>
      </div>

      {contextMenu ? (
        <div className="classification-menu-backdrop" onClick={() => setContextMenu(null)}>
          <div className="classification-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
            <div className="classification-context-title">移动企业</div>
            <div className="classification-context-company">{contextMenu.company}</div>
            {moveTargets.map((group) => (
              <button key={group.name} type="button" onClick={() => moveCompanyTo(group.name)} disabled={busy}>
                {group.name}
              </button>
            ))}
            {moveTargets.length ? null : <span>暂无其它分组</span>}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const threatIpColumns: Column[] = [
  { title: '#', render: (row, index) => text(row.index) || String(index + 1) },
  { title: 'IP地址', key: 'ip' },
  { title: '信誉等级', key: 'reputation_level' },
  { title: '威胁评分', key: 'threat_score' },
  { title: '威胁类型', key: 'threat_types' },
  { title: '恶意软件家族', key: 'malware_families' },
  { title: '攻击活动', key: 'campaigns' },
  { title: '位置', key: 'location' },
  { title: '首次发现', key: 'first_seen' },
  { title: '详情链接', key: 'permalink_label' },
  { title: '状态', render: (row) => <span className={`cookie-status-detail ${statusClass(row.success)}`}>{boolLabel(row.success)}</span> },
];

const threatDnsColumns: Column[] = [
  { title: '#', render: (row, index) => text(row.index) || String(index + 1) },
  { title: '域名', key: 'domain' },
  { title: '失陷状态', key: 'compromise_status' },
  { title: '研判标签', key: 'judgments' },
  { title: '攻击手法', key: 'attack_methods' },
  { title: '置信度', key: 'confidence_level' },
  { title: '恶意软件家族', key: 'malware_families' },
  { title: '威胁等级', key: 'severity' },
  { title: '详情链接', key: 'permalink_label' },
  { title: '状态', render: (row) => <span className={`cookie-status-detail ${statusClass(row.success)}`}>{boolLabel(row.success)}</span> },
];

const threatFileColumns: Column[] = [
  { title: '#', render: (row, index) => text(row.index) || String(index + 1) },
  { title: '文件名/资源', key: 'file_name' },
  { title: 'SHA256', key: 'sha256' },
  { title: '文件大小', key: 'file_size' },
  { title: '威胁等级/状态', key: 'threat_level' },
  { title: '木马/病毒家族', key: 'malware_family' },
  { title: '威胁分类', key: 'malware_type' },
  { title: '多引擎检出', key: 'detect_rate' },
  { title: '提交/查询时间', key: 'query_time' },
  { title: '详情链接', key: 'permalink_label' },
  { title: '状态', render: (row) => <span className={`cookie-status-detail ${statusClass(row.success)}`}>{boolLabel(row.success)}</span> },
];

function threatColumnsForMode(mode: ThreatMode): Column[] {
  if (mode === 'dns') return threatDnsColumns;
  if (mode === 'file_report' || mode === 'file_multiengines' || mode === 'file_upload') return threatFileColumns;
  return threatIpColumns;
}

function asRecord(value: unknown): Row {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
}

function namesFromList(value: unknown): string {
  if (!Array.isArray(value)) return text(value) || '无';
  const values = value
    .map((item) => {
      if (item && typeof item === 'object') {
        const record = item as Row;
        return text(record.name) || text(record.label) || text(record.value);
      }
      return text(item);
    })
    .filter(Boolean);
  return values.length ? Array.from(new Set(values)).join(', ') : '无';
}

function valuesFromTagClasses(value: unknown, tagsType: string): string {
  if (!Array.isArray(value)) return '无';
  const values: string[] = [];
  value.forEach((item) => {
    const record = asRecord(item);
    if (text(record.tags_type) !== tagsType || !Array.isArray(record.tags)) return;
    record.tags.forEach((tag) => {
      const tagText = text(tag);
      if (tagText && !values.includes(tagText)) values.push(tagText);
    });
  });
  return values.length ? values.join(', ') : '无';
}

function formatLocation(value: unknown): string {
  const location = asRecord(value);
  const parts = [location.country, location.province, location.city].map(text).filter(Boolean);
  return parts.length ? parts.join(' ') : text(value) || '未知';
}

function formatFileSize(value: unknown): string {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return '未知';
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(2)} KB`;
  return `${size} B`;
}

function shortHash(value: unknown): string {
  const hash = text(value);
  return hash.length > 18 ? `${hash.slice(0, 18)}...` : hash;
}

function threatLevelLabel(value: unknown): string {
  const level = text(value) || 'unknown';
  const labels: Record<string, string> = {
    malicious: '恶意',
    suspicious: '可疑',
    clean: '安全',
    unknown: '未知',
  };
  return labels[level] ?? level;
}

function permalinkLabel(value: unknown): string {
  return text(value) ? '查看详情' : '无链接';
}

function getPermalink(row: Row | undefined): string {
  if (!row) return '';
  const raw = asRecord(row.raw ?? row);
  const rawData = asRecord(raw.raw_data);
  return text(raw.permalink) || text(row.permalink) || text(rawData.permalink);
}

function rawThreatFields(mode: ThreatMode, raw: Row, row: Row): DetailField[] {
  if (mode === 'dns') {
    return [
      { label: '域名', value: raw.domain || row.domain },
      { label: '失陷状态', value: raw.is_malicious === true ? '已失陷' : row.compromise_status },
      { label: '威胁等级', value: raw.severity || row.severity },
      { label: '置信度', value: raw.confidence_level || row.confidence_level },
      { label: '研判标签', value: namesFromList(raw.judgments || row.judgments) },
      { label: '攻击手法', value: valuesFromTagClasses(raw.tags_classes, 'attack_method') || row.attack_methods },
      { label: '恶意软件家族', value: namesFromList(raw.malware_families || row.malware_families) },
      { label: '分类', value: raw.categories },
      { label: 'Alexa 排名', value: raw.alexa_rank },
      { label: 'Umbrella 排名', value: raw.umbrella_rank },
      { label: '查询时间', value: raw.query_time || row.query_time },
    ];
  }

  if (mode === 'file_report' || mode === 'file_multiengines' || mode === 'file_upload') {
    const rawData = asRecord(raw.raw_data);
    const data = asRecord(rawData.data);
    const summary = asRecord(data.summary);
    return [
      { label: '文件名/资源', value: raw.file_name || raw.resource || row.file_name },
      { label: 'SHA256', value: raw.sha256 || row.sha256 },
      { label: 'MD5', value: raw.md5 },
      { label: 'SHA1', value: raw.sha1 },
      { label: '文件类型', value: raw.file_type },
      { label: '文件大小', value: formatFileSize(raw.file_size) },
      { label: '威胁等级/状态', value: row.threat_level || raw.threat_level || raw.reputation_level || summary.threat_level },
      { label: '木马/病毒家族', value: raw.malware_family || summary.malware_family },
      { label: '威胁分类', value: raw.malware_type || summary.malware_type || namesFromList(raw.threat_types) },
      { label: '多引擎检出', value: row.detect_rate },
      { label: '沙箱环境', value: raw.sandbox_type },
      { label: '运行时间', value: raw.run_time ? `${text(raw.run_time)} 秒` : '' },
      { label: '提交/查询时间', value: raw.query_time || raw.upload_time || raw.scan_date || row.query_time },
    ];
  }

  return [
    { label: 'IP 地址', value: raw.ip || row.ip },
    { label: '信誉等级', value: raw.reputation_level || row.reputation_level },
    { label: '威胁评分', value: raw.threat_score || row.threat_score },
    { label: '威胁等级', value: raw.severity },
    { label: '置信度', value: raw.confidence || raw.confidence_level },
    { label: '威胁类型', value: namesFromList(raw.judgments) !== '无' ? namesFromList(raw.judgments) : namesFromList(raw.threat_types || row.threat_types) },
    { label: '恶意软件家族', value: namesFromList(raw.malware_families || row.malware_families) },
    { label: '攻击活动', value: namesFromList(raw.campaigns || row.campaigns) },
    { label: '位置', value: formatLocation(raw.location || row.location) },
    { label: 'ASN', value: text(asRecord(raw.asn).number) || text(raw.asn) },
    { label: '首次发现', value: raw.first_seen || row.first_seen },
    { label: '最近发现', value: raw.last_seen },
    { label: '更新时间', value: raw.update_time },
    { label: '查询时间', value: raw.query_time || row.query_time },
  ];
}

function threatEngineRows(row: Row | undefined): Row[] {
  const raw = asRecord(row?.raw ?? row);
  const rawData = asRecord(raw.raw_data);
  const data = asRecord(rawData.data);
  const multiengines = asRecord(data.multiengines);
  const engines = asRecord(raw.engines_detail || raw.engines || multiengines.scans || asRecord(raw.engines).scans);
  return Object.entries(engines).map(([engine, value]) => {
    const record = asRecord(value);
    return {
      engine,
      detected: text(record.detected) || text(record.result) || text(value),
      category: record.category || record.malware_type || record.threat_type,
      result: record.result || record.virus_name || record.scan_result || value,
    };
  });
}

function ThreatDetailPane({
  mode,
  row,
  fallbackText,
  onStatus,
}: {
  mode: ThreatMode;
  row: Row | undefined;
  fallbackText: string;
  onStatus: (message: string) => void;
}) {
  if (!row) {
    return <textarea className="result-textarea asset-detail-text" readOnly value={fallbackText} />;
  }

  const raw = asRecord(row.raw ?? row);
  const permalink = getPermalink(row);
  const engineRows = threatEngineRows(row).slice(0, 40);
  const rawDetail = toPrettyText(row.raw ?? row);

  const openPermalink = async () => {
    if (!permalink) {
      onStatus('当前结果没有详情链接');
      return;
    }
    try {
      const result = await callBackend<OpenUrlResponse>('fs.open_url', { url: permalink });
      onStatus(result.message || (result.success ? '详情链接已打开' : '详情链接打开失败'));
    } catch (error) {
      onStatus(`打开详情链接失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div className="enterprise-detail-pane threat-detail-pane">
      <DetailFieldsSection title={`${modeLabel(mode)}详情`} fields={rawThreatFields(mode, raw, row)} />
      {permalink ? (
        <section className="enterprise-detail-section threat-link-section">
          <h4>微步详情链接</h4>
          <div className="threat-link-row">
            <a href={permalink} target="_blank" rel="noreferrer">{permalink}</a>
            <button type="button" className="koi-button secondary compact-button" onClick={openPermalink}>打开链接</button>
          </div>
        </section>
      ) : null}
      {engineRows.length ? (
        <section className="enterprise-detail-section">
          <h4>多引擎检测 ({engineRows.length})</h4>
          <div className="result-table-scroll enterprise-mini-table-scroll">
            <table className="result-table enterprise-mini-table">
              <thead>
                <tr><th>引擎</th><th>状态/命中</th><th>分类</th><th>结果</th></tr>
              </thead>
              <tbody>
                {engineRows.map((engine, index) => (
                  <tr key={`${text(engine.engine)}-${index}`}>
                    <td>{fieldValue(engine.engine)}</td>
                    <td>{fieldValue(engine.detected)}</td>
                    <td>{fieldValue(engine.category)}</td>
                    <td>{fieldValue(engine.result)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      <details className="enterprise-raw-detail">
        <summary>原始返回</summary>
        <textarea className="result-textarea asset-detail-text" readOnly value={rawDetail} />
      </details>
    </div>
  );
}

function normalizeIpThreatRow(rawValue: unknown, index: number, target: string, success: boolean): Row {
  const raw = asRecord(rawValue);
  const rowIp = text(raw.ip) || target;
  return {
    index,
    ip: rowIp,
    reputation_level: text(raw.reputation_level) || (text(raw.error) ? '查询失败' : '未知'),
    threat_score: text(raw.threat_score) || '0',
    threat_types: namesFromList(raw.judgments) !== '无' ? namesFromList(raw.judgments) : namesFromList(raw.threat_types),
    malware_families: namesFromList(raw.malware_families),
    campaigns: namesFromList(raw.campaigns),
    location: formatLocation(raw.location),
    first_seen: text(raw.first_seen) || '未知',
    query_time: text(raw.query_time),
    permalink_label: permalinkLabel(raw.permalink),
    success: success && !text(raw.error),
    raw: rawValue,
  };
}

function normalizeDnsThreatRow(rawValue: unknown, index: number, target: string, success: boolean): Row {
  const raw = asRecord(rawValue);
  const tagClasses = raw.tags_classes;
  const judgments = namesFromList(raw.judgments);
  return {
    index,
    domain: text(raw.domain) || target,
    compromise_status: raw.is_malicious === true ? '已失陷' : text(raw.error) ? '查询失败' : '正常',
    judgments,
    attack_methods: valuesFromTagClasses(tagClasses, 'attack_method'),
    confidence_level: text(raw.confidence_level) || '未知',
    malware_families: namesFromList(raw.malware_families),
    severity: text(raw.severity) || '无威胁',
    permalink_label: permalinkLabel(raw.permalink),
    success: success && !text(raw.error),
    raw: rawValue,
  };
}

function normalizeFileThreatRow(rawValue: unknown, index: number, target: string, mode: ThreatMode, success: boolean): Row {
  const raw = asRecord(rawValue);
  const rawData = asRecord(raw.raw_data);
  const data = asRecord(rawData.data);
  const staticBasic = asRecord(asRecord(data.static).basic);
  const summary = asRecord(data.summary);
  const multiengines = asRecord(data.multiengines);
  const total = Number(raw.total_engines ?? multiengines.total ?? multiengines.total2 ?? 0);
  const positives = Number(raw.positive_engines ?? multiengines.positives ?? 0);
  const detectRate = text(asRecord(data.multiengines).detect_rate) || (total > 0 ? `${positives}/${total}` : '0/0');
  const isUpload = mode === 'file_upload';
  return {
    index,
    file_name: text(raw.file_name) || text(staticBasic.file_name) || text(raw.resource) || target || '未知',
    sha256: shortHash(raw.sha256 || staticBasic.sha256),
    file_size: formatFileSize(raw.file_size),
    threat_level: isUpload
      ? (text(raw.permalink) ? '上传成功' : text(raw.reputation_level) || '处理中')
      : threatLevelLabel(raw.threat_level || summary.threat_level || raw.reputation_level),
    malware_family: text(raw.malware_family) || text(summary.malware_family) || '未知',
    malware_type: text(raw.malware_type) || text(summary.malware_type) || namesFromList(raw.threat_types),
    detect_rate: detectRate,
    query_time: text(raw.query_time) || text(raw.upload_time) || text(raw.scan_date),
    permalink_label: permalinkLabel(raw.permalink),
    success: success && !text(raw.error),
    raw: rawValue,
  };
}

function threatRowsFromResult(mode: ThreatMode, target: string, response: QueryResponse): Row[] {
  const normalize = (rawValue: unknown, index: number, rowSuccess = response.success): Row => {
    if (mode === 'dns') return normalizeDnsThreatRow(rawValue, index, target, rowSuccess);
    if (mode === 'file_report' || mode === 'file_multiengines' || mode === 'file_upload') {
      return normalizeFileThreatRow(rawValue, index, target, mode, rowSuccess);
    }
    return normalizeIpThreatRow(rawValue, index, target, rowSuccess);
  };

  if (response.rows?.length) {
    return response.rows.map((row, index) => normalize(row.raw ?? row, index + 1, statusClass(row.success) === 'ok'));
  }

  const raw = response.result ?? response.results ?? response.raw ?? response;
  if (Array.isArray(raw)) {
    return raw.map((item, index) => normalize(item, index + 1));
  }
  return [normalize(raw, 1)];
}

function ThreatBookPage({
  allowedModes = ALL_THREAT_MODES,
  showConfigPanel = true,
}: {
  allowedModes?: ThreatMode[];
  showConfigPanel?: boolean;
}) {
  const [apiKey, setApiKey] = useState('');
  const [target, setTarget] = useState('');
  const [batchFile, setBatchFile] = useState('');
  const [uploadFile, setUploadFile] = useState('');
  const [mode, setMode] = useState<ThreatMode>(allowedModes[0] ?? 'ip');
  const [resourceType, setResourceType] = useState('sha256');
  const [sandboxType, setSandboxType] = useState('win7_sp1_enx86_office2013');
  const [runTime, setRunTime] = useState('60');
  const [status, setStatus] = useState('等待查询');
  const [rows, setRows] = useState<Row[]>([]);
  const [resultText, setResultText] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const result = await callBackend<{ api_key?: string }>('info.threatbook.config.get', {});
    setApiKey(result.api_key ?? '');
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!allowedModes.includes(mode)) {
      setMode(allowedModes[0] ?? 'ip');
    }
  }, [allowedModes, mode]);

  const save = async () => {
    try {
      const result = await callBackend<QueryResponse>('info.threatbook.config.set', { api_key: apiKey });
      setStatus(result.message || '配置已保存');
    } catch (error) {
      setStatus(`保存配置失败: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const testConnection = async () => {
    setBusy(true);
    setStatus('正在测试 ThreatBook 连接...');
    try {
      const result = await callBackend<QueryResponse>('info.threatbook.test_connection', {});
      const nextRows = threatRowsFromResult('ip', 'connection', result);
      setRows(nextRows);
      setResultText(toPrettyText(result.result ?? result.raw ?? result));
      setStatus(result.message || (result.success ? '连接测试完成' : '连接测试失败'));
    } catch (error) {
      setStatus(`连接测试失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (mode === 'file_upload' && !uploadFile.trim()) {
      setStatus('请选择要上传分析的文件');
      return;
    }
    if (mode === 'ip_batch' && !target.trim() && !batchFile.trim()) {
      setStatus('请输入 IP 列表或选择批量文件');
      return;
    }
    if (mode !== 'file_upload' && mode !== 'ip_batch' && !target.trim()) {
      setStatus('请输入查询目标');
      return;
    }

    const command = mode === 'ip'
      ? 'info.threatbook.ip'
      : mode === 'ip_batch'
        ? 'info.threatbook.ip.batch'
        : mode === 'dns'
          ? 'info.threatbook.dns'
          : `info.threatbook.${mode}`;
    const payload = mode === 'ip'
      ? { ip: target }
      : mode === 'ip_batch'
        ? { ip_text: target, batch_file: batchFile }
        : mode === 'dns'
          ? { domain: target }
          : mode === 'file_upload'
            ? { file_path: uploadFile, sandbox_type: sandboxType, run_time: Number(runTime) || 60 }
            : { resource: target, resource_type: resourceType };

    setBusy(true);
    setStatus(`正在执行 ${modeLabel(mode)}...`);
    try {
      const result = await callBackend<QueryResponse>(command, payload);
      const displayTarget = mode === 'file_upload' ? getFileName(uploadFile) : target || getFileName(batchFile);
      const nextRows = threatRowsFromResult(mode, displayTarget, result);
      const nextText = [
        rowsToText(nextRows),
        result.logs?.length ? `日志:\n${result.logs.join('\n')}` : '',
        toPrettyText(result.result ?? result.results ?? result.raw ?? result),
      ].filter(Boolean).join('\n\n');
      setRows(nextRows);
      setResultText(nextText);
      setStatus(result.message || (result.success ? '查询完成' : '查询失败'));
    } catch (error) {
      setRows([]);
      setResultText('');
      setStatus(`查询失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const targetPlaceholder = mode === 'ip'
    ? '请输入 IP 地址'
    : mode === 'ip_batch'
      ? '请输入 IP 列表，每行一个'
      : mode === 'dns'
        ? '请输入域名'
        : '请输入文件哈希或 scan_id';

  const summary = (
    <div className="result-summary-grid">
      <span>结果项: {rows.length}</span>
      <span>模式: {modeLabel(mode)}</span>
      <span>API Key: {apiKey ? '已配置' : '未配置'}</span>
    </div>
  );
  const columns = threatColumnsForMode(mode);

  return (
    <div className="vertical-detail scroll-page-layout">
      {showConfigPanel ? <fieldset className="koi-group">
        <legend>ThreatBook 配置</legend>
        <input className="koi-input" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="ThreatBook API Key" />
        <div className="action-row">
          <button type="button" className="koi-button secondary" onClick={save} disabled={busy}>保存配置</button>
          <button type="button" className="koi-button secondary" onClick={testConnection} disabled={busy}>测试连接</button>
        </div>
      </fieldset> : null}

      <fieldset className="koi-group">
        <legend>查询条件</legend>
        <select className="koi-input" value={mode} onChange={(event) => setMode(event.target.value as ThreatMode)}>
          {allowedModes.map((item) => <option key={item} value={item}>{modeLabel(item)}</option>)}
        </select>
        {mode === 'file_upload' ? (
          <>
            <FilePicker value={uploadFile} title="选择要上传分析的文件" onChange={setUploadFile} />
            <div className="template-select-row">
              <input className="koi-input" value={sandboxType} onChange={(event) => setSandboxType(event.target.value)} placeholder="沙箱类型" />
              <input className="koi-input" value={runTime} onChange={(event) => setRunTime(event.target.value)} placeholder="运行时间（秒）" />
            </div>
          </>
        ) : (
          <>
            <textarea className="koi-input modal-textarea short-textarea" value={target} onChange={(event) => setTarget(event.target.value)} placeholder={targetPlaceholder} />
            {mode === 'ip_batch' ? (
              <FilePicker
                value={batchFile}
                title="选择 IP 列表文件"
                filters={[{ name: '文本/表格文件', extensions: ['txt', 'csv', 'tsv', 'xlsx', 'xls'] }, { name: '所有文件', extensions: ['*'] }]}
                onChange={setBatchFile}
              />
            ) : null}
            {mode === 'file_report' || mode === 'file_multiengines' ? (
              <select className="koi-input" value={resourceType} onChange={(event) => setResourceType(event.target.value)}>
                <option value="sha256">SHA256</option>
                <option value="sha1">SHA1</option>
                <option value="md5">MD5</option>
                <option value="scan_id">scan_id</option>
              </select>
            ) : null}
          </>
        )}
      </fieldset>

      <div className="action-row">
        <button type="button" className="koi-button primary" onClick={run} disabled={busy}>开始查询</button>
        <ExportTextButton content={resultText} defaultFileName="threatbook_result.txt" onStatus={setStatus} />
        <button type="button" className="koi-button danger" onClick={() => { setRows([]); setResultText(''); setStatus('结果已清空'); }}>清空结果</button>
      </div>

      <ResultPanel
        title="ThreatBook 结果"
        status={status}
        rows={rows}
        columns={columns}
        detailText={resultText}
        summary={summary}
        renderDetail={(selected, fallbackText) => (
          <ThreatDetailPane mode={mode} row={selected} fallbackText={fallbackText} onStatus={setStatus} />
        )}
      />
    </div>
  );
}

function EnterpriseSectionPage() {
  return (
    <TabWidget
      tabs={[
        { id: 'tyc', title: '天眼查', content: <EnterpriseQueryPage source="tyc" /> },
        { id: 'aiqicha', title: '爱企查', content: <EnterpriseQueryPage source="aiqicha" /> },
        { id: 'classification', title: '分类管理', content: <ClassificationManagerPage /> },
      ]}
    />
  );
}

function AssetSectionPage() {
  return (
    <TabWidget
      tabs={[
        { id: 'unified', title: '统一查询', content: <AssetQueryPage platform="unified" /> },
        { id: 'fofa', title: 'FOFA', content: <AssetQueryPage platform="fofa" /> },
        { id: 'hunter', title: 'Hunter', content: <AssetQueryPage platform="hunter" /> },
        { id: 'quake', title: 'Quake', content: <AssetQueryPage platform="quake" /> },
      ]}
    />
  );
}

function ThreatIntelSectionPage() {
  return (
    <TabWidget
      tabs={[
        { id: 'ip-reputation', title: 'IP信誉查询', content: <ThreatBookPage allowedModes={THREAT_IP_MODES} showConfigPanel={false} /> },
        { id: 'dns-compromise', title: '域名失陷检测', content: <ThreatBookPage allowedModes={THREAT_DNS_MODES} showConfigPanel={false} /> },
        { id: 'file-analysis', title: '文件分析', content: <ThreatBookPage allowedModes={THREAT_FILE_MODES} showConfigPanel={false} /> },
        { id: 'config-help', title: '配置与帮助', content: <ThreatBookPage allowedModes={ALL_THREAT_MODES} /> },
      ]}
    />
  );
}

export const informationGatheringModule: KoiModule = {
  id: 'information-gathering',
  title: '信息收集',
  functions: [
    { id: 'enterprise-query', title: '企业查询', component: EnterpriseSectionPage },
    { id: 'asset-query', title: '资产查询', component: AssetSectionPage },
    { id: 'threat-intelligence', title: '威胁情报', component: ThreatIntelSectionPage },
  ],
};
