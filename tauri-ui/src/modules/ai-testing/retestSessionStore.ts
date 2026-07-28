export type RetestAgentMessage = {
  id: string;
  role: 'agent' | 'user' | 'system';
  title?: string;
  content: string;
  timestamp: string;
  tone?: 'info' | 'ok' | 'warn' | 'error';
};

export type RetestSessionEventType = 'status' | 'thought_summary' | 'tool_call' | 'tool_result' | 'artifact' | 'approval_request' | 'error' | 'chat';

export type RetestToolTrace = {
  toolId?: string;
  label?: string;
  status?: 'running' | 'completed' | 'failed' | 'skipped' | 'blocked' | 'incomplete' | 'cancelled';
  target?: string;
  argsPreview?: string;
  resultPreview?: string;
  rawOutput?: string;
  durationMs?: number;
  findingCount?: number;
  observationCount?: number;
  failedCount?: number;
  rawCount?: number;
  evidence?: string;
  pythonProbeScript?: string;
  requestRaw?: string;
  requestSafe?: string;
  responseMeta?: Record<string, unknown>;
  responseHeadersSafe?: Record<string, unknown>;
  responseBodyPreview?: string;
  responseRawExcerpt?: string;
  statusCode?: number;
  finalUrl?: string;
  matchedMarkers?: string[];
  failureReason?: string;
};

export type RetestSessionEvent = {
  id: string;
  type: RetestSessionEventType;
  title: string;
  content?: string;
  timestamp: string;
  tone?: 'info' | 'ok' | 'warn' | 'error';
  sourceFile?: string;
  tool?: RetestToolTrace;
  metadata?: Record<string, unknown>;
};

export type RetestResumeState = {
  canContinue: boolean;
  targetDir: string;
  sourceFiles: string[];
  nextIndex: number;
  summaries: string[];
  reports: string[];
  completionItems: Array<Record<string, unknown>>;
  diskCompletedFileNames?: string[];
  diskCompletedReportEvidence?: Array<Record<string, unknown>>;
  allLogs: string[];
  failedCount: number;
  generateReports?: boolean;
  blockedReason?: string;
  blockedStage?: string;
  blockedTitle?: string;
  currentFile?: {
    index: number;
    sourceFile: string;
    sourceFileName?: string;
    stage?: string;
    resumeSnapshot?: Record<string, unknown>;
  } | null;
};

export type RetestProgressEvidence = {
  targetDir: string;
  completedFileNames: string[];
  latestSourceFileName: string;
  hasCompletionSummary: boolean;
  toolCalls: number;
  errors: number;
  completedCountHint?: number;
  nextIndexHint?: number;
  nextSourceFileName?: string;
};

export type RetestSessionDraft = {
  sessionId: string;
  sessionTitle: string;
  targetDir?: string;
  workspaceRoot?: string;
  status?: string;
  progress?: number;
  resultText?: string;
  log?: string;
  lastReportPath?: string;
  events?: RetestSessionEvent[];
  agentMessages?: RetestAgentMessage[];
  latestResultData?: Record<string, unknown> | null;
  resumeState?: RetestResumeState | null;
  progressEvidence?: RetestProgressEvidence;
  memoryMarkdown?: string;
  generateReports?: boolean;
  createdAt: string;
  updatedAt: string;
  isRunning?: boolean;
};

export type RetestSessionStore = {
  activeSessionId?: string;
  sessions: RetestSessionDraft[];
};

export type RetestSessionCompactResult = {
  sessionId: string;
  sessionTitle: string;
  beforeBytes: number;
  afterBytes: number;
  beforeEvents: number;
  afterEvents: number;
  memoryBytes: number;
  memoryUpdated: boolean;
};

export type RetestSessionCompactAllResult = {
  activeSessionId?: string;
  sessionCount: number;
  failedCount: number;
  beforeBytes: number;
  afterBytes: number;
  results: RetestSessionCompactResult[];
};

export const RETEST_SESSION_STORAGE_KEY = 'koi.retest.sessions.v2';
export const RETEST_SESSION_CHANGED_EVENT = 'koi-retest-session-updated';
export const RETEST_RUNTIME_SESSION_KEY = 'koi.retest.runtime.active';
export const RETEST_ACTIVE_SESSION_KEY = 'koi.retest.ui.active';
export const RETEST_RESUME_REQUEST_KEY = 'koi.retest.resume.requested';
export const RETEST_RERUN_REQUEST_KEY = 'koi.retest.rerun.requested';

const LEGACY_RETEST_SESSION_STORAGE_KEYS = ['koi.retest.sessions.v1', 'koi.retest.session.v1'];
const RETEST_AUTO_START_BOOT_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const RETEST_AUTO_START_REQUEST_TTL_MS = 2 * 60 * 1000;
const MAX_RETEST_SESSIONS = 20;
const MAX_SESSION_EVENTS = 500;
const MAX_PROGRESS_FILE_NAMES = 1000;
const COMPACT_SESSION_EVENTS = 160;
const COMPACT_EVENT_TEXT_LIMIT = 2000;
const COMPACT_TOOL_TEXT_LIMIT = 1200;
const SESSION_MEMORY_TEXT_LIMIT = 24000;
const SESSION_MEMORY_SECTION_LIMIT = 7000;
const AUTO_COMPACT_STORE_LIMIT = 3000000;
const AUTO_COMPACT_SESSION_LIMIT = 850000;
const AUTO_COMPACT_EVENT_COUNT = 260;
const AUTO_COMPACT_FORCE_SESSION_LIMIT = 120000;
const STORAGE_FLUSH_DELAY_MS = 350;
const SESSION_CHANGE_BROADCAST_DELAY_MS = 80;

let memoryStore: RetestSessionStore | null = null;
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let broadcastTimer: ReturnType<typeof setTimeout> | null = null;
let flushHandlersInstalled = false;

function hasWindowStorage() {
  return typeof window !== 'undefined' && Boolean(window.localStorage);
}

function getRuntimeSessionId() {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY) || '' : '';
  } catch {
    return '';
  }
}

function getSessionStorageValue(key: string) {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage.getItem(key) || '' : '';
  } catch {
    return '';
  }
}

function setSessionStorageValue(key: string, value: string) {
  try {
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem(key, value);
    }
  } catch {
    // Ignore storage failures in static previews or restricted WebViews.
  }
}

function removeSessionStorageValue(key: string) {
  try {
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    // Ignore storage failures in static previews or restricted WebViews.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export type RetestAutoStartKind = 'resume' | 'rerun';

function retestAutoStartKey(kind: RetestAutoStartKind) {
  return kind === 'resume' ? RETEST_RESUME_REQUEST_KEY : RETEST_RERUN_REQUEST_KEY;
}

const UTF8_MOJIBAKE_SIGNAL_RE = /[\u0080-\u009f\u00c2\u00c3\u00e2\u00e4-\u00e9\u00ef\u00f0\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u2013-\u201d]/;
const UTF8_MOJIBAKE_REPAIRED_RESIDUE_RE = /[\u0080-\u009f\u00c2\u00c3\u00e2\u00e4-\u00e9\u00ef\u00f0\u0152\u0153\u0160\u0161\u017d\u017e]/;
const UTF8_MOJIBAKE_STORAGE_RE = /[\u0080-\u009f]|(?:[\u00c2\u00c3\u00e2\u00e4-\u00e9\u00ef\u00f0\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u2013-\u201d][\u0080-\u00ff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u20ac\u2013-\u201e\u2020-\u2022\u02c6\u02dc\u2030\u2039\u203a]?)/;
const UTF8_MOJIBAKE_RUN_RE = /[\u0009\u000a\u000d\u0020-\u007e\u0080-\u00ff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u20ac\u2013-\u201e\u2020-\u2022\u02c6\u02dc\u2030\u2039\u203a]+/g;
const CJK_TEXT_RE = /[\u3400-\u9fff]/;
const utf8RepairDecoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8', { fatal: true }) : null;

function cp1252ByteFromCodePoint(code: number) {
  if (code <= 0xff) return code;
  switch (code) {
    case 0x20ac: return 0x80;
    case 0x201a: return 0x82;
    case 0x0192: return 0x83;
    case 0x201e: return 0x84;
    case 0x2026: return 0x85;
    case 0x2020: return 0x86;
    case 0x2021: return 0x87;
    case 0x02c6: return 0x88;
    case 0x2030: return 0x89;
    case 0x0160: return 0x8a;
    case 0x2039: return 0x8b;
    case 0x0152: return 0x8c;
    case 0x017d: return 0x8e;
    case 0x2018: return 0x91;
    case 0x2019: return 0x92;
    case 0x201c: return 0x93;
    case 0x201d: return 0x94;
    case 0x2022: return 0x95;
    case 0x2013: return 0x96;
    case 0x2014: return 0x97;
    case 0x02dc: return 0x98;
    case 0x2122: return 0x99;
    case 0x0161: return 0x9a;
    case 0x203a: return 0x9b;
    case 0x0153: return 0x9c;
    case 0x017e: return 0x9e;
    case 0x0178: return 0x9f;
    default: return null;
  }
}

function decodeCp1252Utf8(value: string) {
  if (!utf8RepairDecoder || !UTF8_MOJIBAKE_SIGNAL_RE.test(value)) return null;
  const bytes: number[] = [];
  for (const char of value) {
    const byte = cp1252ByteFromCodePoint(char.codePointAt(0) ?? 0);
    if (byte === null) return null;
    bytes.push(byte);
  }
  try {
    return utf8RepairDecoder.decode(new Uint8Array(bytes));
  } catch {
    return null;
  }
}

function utf8SequenceLength(byte: number) {
  if (byte >= 0xc2 && byte <= 0xdf) return 2;
  if (byte >= 0xe0 && byte <= 0xef) return 3;
  if (byte >= 0xf0 && byte <= 0xf4) return 4;
  return 0;
}

function decodeCp1252Utf8Fragments(value: string) {
  if (!utf8RepairDecoder || !UTF8_MOJIBAKE_SIGNAL_RE.test(value)) return value;
  const chars = Array.from(value);
  let output = '';
  let changed = false;
  for (let index = 0; index < chars.length;) {
    const byte = cp1252ByteFromCodePoint(chars[index].codePointAt(0) ?? 0);
    const size = byte === null ? 0 : utf8SequenceLength(byte);
    if (size > 1 && index + size <= chars.length) {
      const seq = chars.slice(index, index + size);
      const seqBytes = seq.map((char) => cp1252ByteFromCodePoint(char.codePointAt(0) ?? 0));
      const validContinuation = seqBytes.slice(1).every((item) => item !== null && item >= 0x80 && item <= 0xbf);
      if (validContinuation) {
        const repaired = decodeCp1252Utf8(seq.join(''));
        if (repaired && repaired !== seq.join('') && !UTF8_MOJIBAKE_REPAIRED_RESIDUE_RE.test(repaired)) {
          output += repaired;
          changed = true;
          index += size;
          continue;
        }
      }
    }
    output += chars[index];
    index += 1;
  }
  return changed ? output : value;
}

function shouldUseMojibakeRepair(original: string, repaired: string | null) {
  return Boolean(
    repaired
    && repaired !== original
    && CJK_TEXT_RE.test(repaired)
    && !UTF8_MOJIBAKE_REPAIRED_RESIDUE_RE.test(repaired),
  );
}

function repairUtf8Mojibake(value: string) {
  if (!value || !UTF8_MOJIBAKE_SIGNAL_RE.test(value)) return value;
  const whole = decodeCp1252Utf8(value);
  if (shouldUseMojibakeRepair(value, whole)) return whole as string;
  const repaired = value.replace(UTF8_MOJIBAKE_RUN_RE, (chunk) => {
    const repaired = decodeCp1252Utf8(chunk);
    if (shouldUseMojibakeRepair(chunk, repaired)) return repaired as string;
    return decodeCp1252Utf8Fragments(chunk);
  });
  return repaired;
}

export function repairRetestText(value: unknown, fallback = '') {
  return repairUtf8Mojibake(typeof value === 'string' ? value : fallback);
}

function asString(value: unknown, fallback = '') {
  return repairRetestText(value, fallback);
}

export function isFastRetestSession(session: RetestSessionDraft | null | undefined) {
  if (!session) return false;
  const hasFastEvent = (session.events ?? []).some((event) => {
    const metadata = event.metadata ?? {};
    const mode = asString(metadata.mode).trim().toLowerCase();
    const phase = asString(metadata.phase).trim().toLowerCase();
    const text = asString([event.title, event.content].filter(Boolean).join('\n'));
    return mode === 'fast'
      || phase.startsWith('one_click_fast')
      || text.includes('快速复测启动')
      || text.includes('快速复测继续')
      || (text.includes('快速复测') && text.includes('不调用 AI 模型'));
  });
  if (hasFastEvent) return true;
  return (session.agentMessages ?? []).some((message) => {
    const text = asString([message.title, message.content].filter(Boolean).join('\n'));
    return text.includes('快速复测') && text.includes('不调用 AI 模型');
  });
}

function repairRetestStoredValue(value: unknown, depth = 0): unknown {
  if (typeof value === 'string') return asString(value);
  if (depth >= 8 || value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((item) => repairRetestStoredValue(item, depth + 1));
  if (!isRecord(value)) return value;
  const repaired: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    repaired[key] = repairRetestStoredValue(item, depth + 1);
  }
  return repaired;
}

function sanitizeLooseRecord(value: unknown): Record<string, unknown> | undefined {
  const repaired = repairRetestStoredValue(value);
  return isRecord(repaired) ? repaired : undefined;
}

function shouldPersistNormalizedRaw(raw: string, normalizedRaw: string, compacted: boolean) {
  if (compacted || raw.length > normalizedRaw.length + 4096) return true;
  return raw !== normalizedRaw && UTF8_MOJIBAKE_STORAGE_RE.test(raw);
}

function asNumber(value: unknown, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function parseRetestAutoStartRequest(kind: RetestAutoStartKind, raw: string) {
  const text = raw.trim();
  if (!text || !text.startsWith('{')) return '';
  try {
    const request = JSON.parse(text);
    if (!isRecord(request)) return '';
    if (asNumber(request.version) !== 1) return '';
    if (asString(request.kind) !== kind) return '';
    if (asString(request.source) !== 'user') return '';
    if (asString(request.bootId) !== RETEST_AUTO_START_BOOT_ID) return '';
    const createdAt = asNumber(request.createdAt);
    const ageMs = Date.now() - createdAt;
    if (!createdAt || ageMs < 0 || ageMs > RETEST_AUTO_START_REQUEST_TTL_MS) return '';
    const value = asString(kind === 'resume' ? request.sessionId || request.value : request.targetDir || request.value).trim();
    return value;
  } catch {
    return '';
  }
}

function makeRetestAutoStartRequest(kind: RetestAutoStartKind, value: string) {
  const trimmedValue = value.trim();
  return JSON.stringify({
    version: 1,
    kind,
    source: 'user',
    bootId: RETEST_AUTO_START_BOOT_ID,
    createdAt: Date.now(),
    nonce: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
    value: trimmedValue,
    ...(kind === 'resume' ? { sessionId: trimmedValue } : { targetDir: trimmedValue }),
  });
}

function consumeRetestAutoStartRequest(kind: RetestAutoStartKind) {
  const key = retestAutoStartKey(kind);
  const raw = getSessionStorageValue(key);
  if (!raw) return '';
  removeSessionStorageValue(key);
  return parseRetestAutoStartRequest(kind, raw);
}

export function hasFreshRetestAutoStartRequest(kind?: RetestAutoStartKind) {
  const kinds: RetestAutoStartKind[] = kind ? [kind] : ['resume', 'rerun'];
  return kinds.some((item) => {
    const key = retestAutoStartKey(item);
    const raw = getSessionStorageValue(key);
    if (!raw) return false;
    const value = parseRetestAutoStartRequest(item, raw);
    if (!value) removeSessionStorageValue(key);
    return Boolean(value);
  });
}

export function requestRetestSessionResume(sessionId: string) {
  const value = sessionId.trim();
  if (!value) return;
  setSessionStorageValue(RETEST_RESUME_REQUEST_KEY, makeRetestAutoStartRequest('resume', value));
}

export function requestRetestTargetRerun(targetDir: string) {
  const value = targetDir.trim();
  if (!value) return;
  setSessionStorageValue(RETEST_RERUN_REQUEST_KEY, makeRetestAutoStartRequest('rerun', value));
}

export function consumeRetestResumeRequest() {
  return consumeRetestAutoStartRequest('resume');
}

export function consumeRetestRerunRequest() {
  return consumeRetestAutoStartRequest('rerun');
}

function trimStorageText(value: unknown, limit: number) {
  const text = asString(value);
  if (!text || text.length <= limit) return text;
  return `${text.slice(0, limit)}\n\n[truncated for local session storage]`;
}

function trimMemoryText(value: unknown, limit = SESSION_MEMORY_SECTION_LIMIT) {
  const text = asString(value).replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!text || text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}\n...[记忆压缩截断 ${text.length - limit} 字]`;
}

function nowIso() {
  return new Date().toISOString();
}

function shortTime(iso = nowIso()) {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour12: false });
}

function makeId(prefix = 'event') {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getFolderName(pathValue?: string) {
  const cleaned = (pathValue || '').trim().replace(/[\\/]+$/, '');
  if (!cleaned) return '会话';
  return cleaned.split(/[\\/]/).filter(Boolean).pop() || cleaned;
}

function getFileName(pathValue?: string) {
  const cleaned = asString(pathValue).trim();
  return cleaned.split(/[\\/]/).filter(Boolean).pop() || cleaned;
}

function isGeneratedRetestReportName(value?: string) {
  const fileName = getFileName(value).toLowerCase();
  return Boolean(fileName && (fileName.includes('复测报告') || fileName.includes('retest report')));
}

function isGeneratedRetestReportPath(value?: string) {
  const text = asString(value).toLowerCase().replace(/\\/g, '/');
  if (!text) return false;
  return isGeneratedRetestReportName(text)
    || text.split('/').some((part) => part === 'retest_reports' || part === '.koi_retest_screenshots');
}

function getSourceNoticeFileName(pathValue?: string) {
  const fileName = getFileName(pathValue);
  return fileName && !isGeneratedRetestReportPath(pathValue) ? fileName : '';
}

function sanitizeSourceNoticePaths(value: unknown, limit = 1000) {
  return sanitizeStringArray(value, limit).filter((item) => !isGeneratedRetestReportPath(item));
}

function normalizeTargetDir(pathValue?: string) {
  return asString(pathValue)
    .trim()
    .replace(/[\\/]+$/, '')
    .replace(/\\/g, '/')
    .replace(/\/+/g, '/')
    .toLowerCase();
}

function positiveInt(value: unknown) {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? Math.floor(next) : 0;
}

function isAiCompactionToolEvent(title: string, tool?: RetestToolTrace, metadata?: Record<string, unknown>) {
  return tool?.toolId === 'doc.retest.session.compact'
    || tool?.label?.includes('AI 语义压缩')
    || title.includes('AI 语义压缩')
    || metadata?.phase === 'slash_command_compact_ai'
    || metadata?.phase === 'session_compaction';
}

function normalizeCompactionToolStatus(
  title: string,
  content: string,
  tool?: RetestToolTrace,
): RetestToolTrace | undefined {
  if (!tool) return undefined;
  const text = `${title}\n${content}\n${tool.resultPreview || ''}\n${tool.failureReason || ''}`;
  if (tool.status !== 'blocked' && tool.status !== 'failed' && tool.status !== 'skipped') return tool;
  const isIncomplete = text.includes('失败') || text.includes('未完成') || text.includes('未裁剪') || text.includes('调用失败') || text.includes('超时');
  const status: RetestToolTrace['status'] = text.includes('完成') && !isIncomplete
    ? 'completed'
    : isIncomplete
      ? 'incomplete'
      : text.includes('压缩中') || text.includes('正在')
        ? 'running'
        : 'incomplete';
  return {
    ...tool,
    status,
    failureReason: status === 'incomplete' ? tool.failureReason : undefined,
  };
}

function memoryNumberHints(memoryMarkdown?: string) {
  const text = asString(memoryMarkdown);
  if (!text.trim()) return {};
  const hints: Pick<RetestProgressEvidence, 'completedCountHint' | 'nextIndexHint' | 'nextSourceFileName'> = {};
  const completedPatterns = [
    /进度[：:\s]*(\d+)\s*\/\s*\d+[^。\n]{0,40}(?:已完成|完成复测|复测完成)/i,
    /共(?:复测|完成复测|已复测)?\s*(\d+)\s*份(?:通报|文档)?/i,
    /已完成(?:复测)?\s*(\d+)\s*份(?:通报|文档)?/i,
    /(\d+)\s*份(?:通报|文档)?[^。\n]{0,24}(?:已完成|完成复测|复测完成)/i,
    /(?:已完成|完成复测|复测完成)[^。\n%]{0,24}(\d+)\s*份/i,
  ];
  for (const pattern of completedPatterns) {
    const match = text.match(pattern);
    const value = positiveInt(match?.[1]);
    if (value) {
      hints.completedCountHint = value;
      break;
    }
  }

  const nextPatterns = [
    /nextIndex\s*[=:：]\s*(\d+)/i,
    /(?:当前断点|断点)[^\n]{0,40}#\s*(\d+)/i,
    /(?:当前断点|断点|下一份|继续|从)[^\n]{0,40}第\s*(\d+)\s*份/i,
    /(?:当前断点|断点|下一份|继续|从)[^\n]{0,40}序号\s*(\d+)/i,
  ];
  for (const pattern of nextPatterns) {
    const match = text.match(pattern);
    const value = positiveInt(match?.[1]);
    if (value) {
      hints.nextIndexHint = pattern.source.includes('nextIndex') ? value : Math.max(0, value - 1);
      break;
    }
  }

  const sourcePatterns = [
    /(?:当前断点|断点)[^\n]{0,80}(?:文件|通报)\s*[：:]\s*([^\r\n。；;]+?\.docx)/i,
    /下一份未完成通报(?:是|为)?[“"']?([^”"'\r\n]+?\.docx)[”"']?/i,
    /#\s*\d+[^\r\n]{0,60}?([^\r\n。；;]+?\.docx)/i,
  ];
  const sourceMatch = sourcePatterns.map((pattern) => text.match(pattern)).find(Boolean);
  if (sourceMatch?.[1]) {
    hints.nextSourceFileName = getFileName(sourceMatch[1].trim().replace(/^[`'"“”\s,，:：-]+|[`'"“”\s。；;]+$/g, ''));
  }
  return hints;
}

function sanitizeEventType(value: unknown): RetestSessionEventType {
  if (
    value === 'thought_summary' ||
    value === 'tool_call' ||
    value === 'tool_result' ||
    value === 'artifact' ||
    value === 'approval_request' ||
    value === 'error' ||
    value === 'chat'
  ) {
    return value;
  }
  return 'status';
}

function sanitizeTone(value: unknown): RetestSessionEvent['tone'] {
  return value === 'ok' || value === 'warn' || value === 'error' ? value : 'info';
}

function sanitizeToolTrace(value: unknown): RetestToolTrace | undefined {
  if (!isRecord(value)) return undefined;
  const status = value.status === 'running' || value.status === 'completed' || value.status === 'failed' || value.status === 'skipped' || value.status === 'blocked' || value.status === 'incomplete' || value.status === 'cancelled'
    ? value.status
    : undefined;
  const matchedMarkersValue = value.matchedMarkers ?? value.matched_markers;
  return {
    toolId: asString(value.toolId || value.tool_id) || undefined,
    label: asString(value.label) || undefined,
    status,
    target: asString(value.target) || undefined,
    argsPreview: asString(value.argsPreview || value.args_preview) || undefined,
    resultPreview: asString(value.resultPreview || value.result_preview) || undefined,
    rawOutput: asString(value.rawOutput || value.raw_output || value.outputRaw || value.output_raw) || undefined,
    durationMs: value.durationMs !== undefined || value.duration_ms !== undefined ? asNumber(value.durationMs ?? value.duration_ms) : undefined,
    findingCount: value.findingCount !== undefined || value.finding_count !== undefined ? asNumber(value.findingCount ?? value.finding_count) : undefined,
    observationCount: value.observationCount !== undefined || value.observation_count !== undefined
      ? asNumber(value.observationCount ?? value.observation_count)
      : value.findingCount !== undefined || value.finding_count !== undefined
        ? asNumber(value.findingCount ?? value.finding_count)
        : undefined,
    failedCount: value.failedCount !== undefined || value.failed_count !== undefined ? asNumber(value.failedCount ?? value.failed_count) : undefined,
    rawCount: value.rawCount !== undefined || value.raw_count !== undefined ? asNumber(value.rawCount ?? value.raw_count) : undefined,
    evidence: asString(value.evidence) || undefined,
    pythonProbeScript: asString(value.pythonProbeScript || value.python_probe_script) || undefined,
    requestRaw: asString(value.requestRaw || value.request_raw) || undefined,
    requestSafe: asString(value.requestSafe || value.request_safe) || undefined,
    responseMeta: sanitizeLooseRecord(value.responseMeta || value.response_meta),
    responseHeadersSafe: sanitizeLooseRecord(value.responseHeadersSafe || value.response_headers_safe),
    responseBodyPreview: asString(value.responseBodyPreview || value.response_body_preview) || undefined,
    responseRawExcerpt: asString(value.responseRawExcerpt || value.response_raw_excerpt) || undefined,
    statusCode: value.statusCode !== undefined || value.status_code !== undefined ? asNumber(value.statusCode ?? value.status_code) : undefined,
    finalUrl: asString(value.finalUrl || value.final_url) || undefined,
    matchedMarkers: Array.isArray(matchedMarkersValue) ? matchedMarkersValue.map((item) => asString(item)).filter(Boolean) : undefined,
    failureReason: asString(value.failureReason || value.failure_reason) || undefined,
  };
}

function sanitizeEventMetadata(value: unknown): Record<string, unknown> | undefined {
  if (!isRecord(value)) return undefined;
  const metadata: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === 'sessionPatch') continue;
    metadata[key] = repairRetestStoredValue(item);
  }
  return Object.keys(metadata).length ? metadata : undefined;
}

function progressEvidenceFromEventMetadata(event: RetestSessionEvent): RetestProgressEvidence {
  const metadata = isRecord(event.metadata) ? event.metadata : {};
  const raw = sanitizeProgressEvidence(metadata.progressEvidence);
  const targetDir = asString(metadata.targetDir) || raw.targetDir || '';
  return {
    ...raw,
    targetDir,
  };
}

function sanitizeEvent(value: unknown): RetestSessionEvent | null {
  if (!isRecord(value)) return null;
  const type = sanitizeEventType(value.type);
  let title = asString(value.title, type === 'tool_call' ? '工具调用' : '执行事件');
  let content = asString(value.content);
  const timestamp = asString(value.timestamp, shortTime());
  let tone = sanitizeTone(value.tone);
  const metadata = sanitizeEventMetadata(value.metadata);
  let tool = sanitizeToolTrace(value.tool);
  if (isAiCompactionToolEvent(title, tool, metadata)) {
    tool = normalizeCompactionToolStatus(title, content, tool);
    if (tool?.status === 'running') tone = 'info';
    if (tool?.status === 'completed') tone = 'ok';
  if (tool?.status === 'skipped' || tool?.status === 'incomplete' || tool?.status === 'cancelled') tone = 'warn';
  }
  const reports = sanitizeStringArray(metadata?.reports, 1000);
  if (type === 'artifact' && title.includes('报告生成完成') && !reports.length) {
    title = '报告未生成';
    if (!content.trim() || content.includes('报告生成命令已完成')) {
      content = '未发现真实报告路径，已按未生成报告处理。';
    }
    tone = 'warn';
  }
  return {
    id: asString(value.id, makeId('event')),
    type,
    title,
    content,
    timestamp,
    tone,
    sourceFile: asString(value.sourceFile || value.source_file) || undefined,
    tool,
    metadata,
  };
}

export function sanitizeRetestSessionEvent(value: unknown): RetestSessionEvent | null {
  return sanitizeEvent(value);
}

function eventStreamKey(event: RetestSessionEvent) {
  const metadata = event.metadata;
  if (!metadata || typeof metadata !== 'object' || !metadata.modelOutput) return '';
  const explicitKey = metadata.streamKey;
  if (typeof explicitKey === 'string' && explicitKey.trim()) return asString(explicitKey).trim();
  const phase = typeof metadata.phase === 'string' ? asString(metadata.phase) : '';
  const roundId = typeof metadata.roundId === 'string' ? asString(metadata.roundId) : (typeof metadata.turnId === 'string' ? asString(metadata.turnId) : '');
  if (!phase && !roundId && !event.sourceFile) return '';
  return ['model-output', roundId, asString(event.sourceFile), phase].join(':');
}

function eventToolKey(event: RetestSessionEvent) {
  if (event.type !== 'tool_call' && event.type !== 'tool_result') return '';
  const tool = event.tool;
  if (!tool) return '';
  const metadata = event.metadata ?? {};
  const toolCallId = metadata.toolCallId || metadata.tool_call_id;
  if (typeof toolCallId === 'string' && toolCallId.trim()) return `tool-call:${asString(toolCallId).trim()}`;
  const roundId = typeof metadata.roundId === 'string' ? asString(metadata.roundId) : (typeof metadata.turnId === 'string' ? asString(metadata.turnId) : '');
  const identity = asString(tool.toolId || tool.label || event.title);
  if (!identity) return '';
  return ['tool', roundId, asString(event.sourceFile), identity, asString(tool.target)].join(':');
}

function sanitizeAgentRole(value: unknown): RetestAgentMessage['role'] {
  return value === 'user' || value === 'system' ? value : 'agent';
}

function sanitizeAgentMessages(value: unknown): RetestAgentMessage[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((item): RetestAgentMessage => ({
      id: asString(item.id, makeId('message')),
      role: sanitizeAgentRole(item.role),
      title: asString(item.title) || undefined,
      content: asString(item.content),
      timestamp: asString(item.timestamp, shortTime()),
      tone: sanitizeTone(item.tone),
    }))
    .filter((item) => item.content.trim())
    .slice(-MAX_SESSION_EVENTS);
}

function agentMessageToEvent(message: RetestAgentMessage): RetestSessionEvent {
  const isError = message.tone === 'error';
  return {
    id: message.id || makeId('event'),
    type: isError ? 'error' : message.role === 'user' ? 'chat' : 'status',
    title: message.title || (message.role === 'user' ? '你' : message.role === 'system' ? '系统' : 'Agent'),
    content: message.content,
    timestamp: message.timestamp || shortTime(),
    tone: message.tone || 'info',
    metadata: { role: message.role },
  };
}

function sanitizeEvents(value: unknown, legacyMessages?: unknown): RetestSessionEvent[] {
  const events = Array.isArray(value) ? value.map(sanitizeEvent).filter((item): item is RetestSessionEvent => Boolean(item)) : [];
  if (events.length) return events.slice(-MAX_SESSION_EVENTS);
  return sanitizeAgentMessages(legacyMessages).map(agentMessageToEvent).slice(-MAX_SESSION_EVENTS);
}

function sanitizeStringArray(value: unknown, limit = 500): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asString(item)).filter(Boolean).slice(-limit);
}

function sanitizeRecordArray(value: unknown, limit = 500): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((item) => repairRetestStoredValue(item))
    .filter(isRecord)
    .slice(-limit);
}

function sanitizeResumeCurrentFile(value: unknown, sourceFiles: string[]): RetestResumeState['currentFile'] {
  if (!isRecord(value)) return null;
  const maxIndex = Math.max(0, sourceFiles.length - 1);
  const index = Math.max(0, Math.min(maxIndex, asNumber(value.index, 0)));
  const sourceFile = asString(value.sourceFile) || sourceFiles[index] || '';
  if (!sourceFile) return null;
  return {
    index,
    sourceFile,
    sourceFileName: getSourceNoticeFileName(asString(value.sourceFileName) || sourceFile) || undefined,
    stage: asString(value.stage) || undefined,
    resumeSnapshot: sanitizeLooseRecord(value.resumeSnapshot),
  };
}

function sanitizeResumeState(value: unknown): RetestResumeState | null {
  if (!isRecord(value)) return null;
  const sourceFiles = sanitizeSourceNoticePaths(value.sourceFiles, 1000);
  const nextIndex = Math.max(0, Math.min(sourceFiles.length, asNumber(value.nextIndex, 0)));
  return {
    canContinue: Boolean(value.canContinue),
    targetDir: asString(value.targetDir),
    sourceFiles,
    nextIndex,
    summaries: sanitizeStringArray(value.summaries, 1000),
    reports: sanitizeStringArray(value.reports, 1000),
    completionItems: sanitizeRecordArray(value.completionItems, 1000),
    diskCompletedFileNames: sanitizeStringArray(value.diskCompletedFileNames, MAX_PROGRESS_FILE_NAMES).map(getSourceNoticeFileName).filter(Boolean),
    diskCompletedReportEvidence: sanitizeRecordArray(value.diskCompletedReportEvidence, 1000),
    allLogs: sanitizeStringArray(value.allLogs, 3000),
    failedCount: Math.max(0, asNumber(value.failedCount, 0)),
    generateReports: Boolean(value.generateReports),
    blockedReason: asString(value.blockedReason) || undefined,
    blockedStage: asString(value.blockedStage) || undefined,
    blockedTitle: asString(value.blockedTitle) || undefined,
    currentFile: sanitizeResumeCurrentFile(value.currentFile, sourceFiles),
  };
}

function sanitizeProgressEvidence(value: unknown): RetestProgressEvidence {
  if (!isRecord(value)) {
    return { targetDir: '', completedFileNames: [], latestSourceFileName: '', hasCompletionSummary: false, toolCalls: 0, errors: 0 };
  }
  return {
    targetDir: asString(value.targetDir),
    completedFileNames: sanitizeStringArray(value.completedFileNames, MAX_PROGRESS_FILE_NAMES).map(getSourceNoticeFileName).filter(Boolean),
    latestSourceFileName: getSourceNoticeFileName(asString(value.latestSourceFileName)),
    hasCompletionSummary: Boolean(value.hasCompletionSummary),
    toolCalls: Math.max(0, asNumber(value.toolCalls, 0)),
    errors: Math.max(0, asNumber(value.errors, 0)),
    completedCountHint: positiveInt(value.completedCountHint),
    nextIndexHint: Math.max(0, asNumber(value.nextIndexHint, 0)),
    nextSourceFileName: getSourceNoticeFileName(asString(value.nextSourceFileName)),
  };
}

function mergeProgressEvidenceForTarget(targetDir: string, ...items: Array<RetestProgressEvidence | undefined | null>): RetestProgressEvidence {
  const completed = new Map<string, string>();
  let evidenceTargetDir = '';
  let latestSourceFileName = '';
  let hasCompletionSummary = false;
  let toolCalls = 0;
  let errors = 0;
  let completedCountHint = 0;
  let nextIndexHint = 0;
  let nextSourceFileName = '';
  const wantedTarget = asString(targetDir);
  const wantedTargetKey = normalizeTargetDir(wantedTarget);
  for (const item of items) {
    if (!item) continue;
    const itemTarget = asString(item.targetDir);
    const itemTargetKey = normalizeTargetDir(itemTarget);
    if (wantedTargetKey && itemTargetKey && itemTargetKey !== wantedTargetKey) continue;
    if (itemTarget) evidenceTargetDir = itemTarget;
    for (const name of item.completedFileNames ?? []) {
      const fileName = getSourceNoticeFileName(name);
      if (!fileName) continue;
      completed.set(fileName.toLowerCase(), fileName);
    }
    if (item.latestSourceFileName) latestSourceFileName = getSourceNoticeFileName(item.latestSourceFileName) || latestSourceFileName;
    hasCompletionSummary = hasCompletionSummary || Boolean(item.hasCompletionSummary);
    toolCalls = Math.max(toolCalls, Number(item.toolCalls ?? 0));
    errors = Math.max(errors, Number(item.errors ?? 0));
    completedCountHint = Math.max(completedCountHint, positiveInt(item.completedCountHint));
    nextIndexHint = Math.max(nextIndexHint, Math.max(0, asNumber(item.nextIndexHint, 0)));
    if (item.nextSourceFileName) nextSourceFileName = getSourceNoticeFileName(item.nextSourceFileName) || nextSourceFileName;
  }
  const completedCount = completed.size;
  completedCountHint = Math.max(completedCountHint, completedCount);
  nextIndexHint = Math.max(nextIndexHint, completedCount);
  return {
    targetDir: evidenceTargetDir || wantedTarget,
    completedFileNames: Array.from(completed.values()).slice(-MAX_PROGRESS_FILE_NAMES),
    latestSourceFileName,
    hasCompletionSummary,
    toolCalls,
    errors,
    completedCountHint: completedCountHint || undefined,
    nextIndexHint: nextIndexHint || undefined,
    nextSourceFileName: nextSourceFileName || undefined,
  };
}

function mergeProgressEvidence(...items: Array<RetestProgressEvidence | undefined | null>): RetestProgressEvidence {
  return mergeProgressEvidenceForTarget('', ...items);
}

function progressEvidenceFromResumeState(state: RetestResumeState | null | undefined): RetestProgressEvidence {
  const completedCandidates = [
    ...sanitizeRecordArray(state?.completionItems, MAX_PROGRESS_FILE_NAMES)
    .map((item) => getSourceNoticeFileName(asString(item.sourceFileName) || asString(item.sourceFile)))
    .filter(Boolean),
    ...sanitizeStringArray(state?.diskCompletedFileNames, MAX_PROGRESS_FILE_NAMES).map(getSourceNoticeFileName).filter(Boolean),
  ];
  const completedMap = new Map<string, string>();
  completedCandidates.forEach((name) => {
    if (name) completedMap.set(name.toLowerCase(), name);
  });
  const completedFileNames = Array.from(completedMap.values());
  const nextIndex = Math.max(0, asNumber(state?.nextIndex, 0), completedFileNames.length);
  return {
    targetDir: state?.targetDir || '',
    completedFileNames,
    latestSourceFileName: getSourceNoticeFileName(state?.sourceFiles?.[nextIndex] || state?.sourceFiles?.[Math.max(0, nextIndex - 1)] || ''),
    hasCompletionSummary: Boolean(completedFileNames.length && state?.nextIndex !== undefined && state.nextIndex >= (state.sourceFiles?.length ?? Number.POSITIVE_INFINITY)),
    toolCalls: 0,
    errors: 0,
    completedCountHint: completedFileNames.length || undefined,
    nextIndexHint: nextIndex || undefined,
  };
}

function progressEvidenceFromEvents(events: RetestSessionEvent[] | undefined): RetestProgressEvidence {
  const completed = new Map<string, string>();
  let latestSourceFileName = '';
  let hasCompletionSummary = false;
  let toolCalls = 0;
  let errors = 0;
  let completedCountHint = 0;
  let nextIndexHint = 0;
  let nextSourceFileName = '';
  for (const event of events ?? []) {
    const metadata = isRecord(event.metadata) ? event.metadata : {};
    const title = asString(event.title);
    const raw = sanitizeProgressEvidence(metadata.progressEvidence);
    for (const name of raw.completedFileNames ?? []) {
      const fileName = getSourceNoticeFileName(name);
      if (fileName) completed.set(fileName.toLowerCase(), fileName);
    }
    completedCountHint = Math.max(completedCountHint, positiveInt(raw.completedCountHint));
    nextIndexHint = Math.max(nextIndexHint, Math.max(0, asNumber(raw.nextIndexHint, 0)));
    if (raw.nextSourceFileName) nextSourceFileName = raw.nextSourceFileName;
    const sourceName = getSourceNoticeFileName(asString(metadata.sourceFileName) || asString(event.sourceFile));
    if (sourceName) latestSourceFileName = sourceName;
    const completionItems = sanitizeRecordArray(metadata.completionItems, MAX_PROGRESS_FILE_NAMES);
    for (const item of completionItems) {
      const name = getSourceNoticeFileName(asString(item.sourceFileName) || asString(item.sourceFile));
      if (name) completed.set(name.toLowerCase(), name);
    }
    const hasFileVerdict = title.includes('复测结果') || typeof metadata.fixStatus === 'string';
    if (hasFileVerdict && sourceName) completed.set(sourceName.toLowerCase(), sourceName);
    if (metadata.phase === 'completion_summary' || title.includes('复测结论总览')) hasCompletionSummary = true;
    if (metadata.phase === 'session_compaction' || isAiCompactionToolEvent(title, event.tool, metadata)) {
      const hints = memoryNumberHints(event.content);
      completedCountHint = Math.max(completedCountHint, positiveInt(hints.completedCountHint));
      nextIndexHint = Math.max(nextIndexHint, Math.max(0, asNumber(hints.nextIndexHint, 0)));
      if (hints.nextSourceFileName) nextSourceFileName = hints.nextSourceFileName;
    }
    if (event.type === 'tool_call' || event.type === 'tool_result') toolCalls += 1;
    if (event.type === 'error') errors += 1;
  }
  return {
    targetDir: '',
    completedFileNames: Array.from(completed.values()).slice(-MAX_PROGRESS_FILE_NAMES),
    latestSourceFileName,
    hasCompletionSummary,
    toolCalls,
    errors,
    completedCountHint: completedCountHint || undefined,
    nextIndexHint: nextIndexHint || undefined,
    nextSourceFileName: nextSourceFileName || undefined,
  };
}

function hasRetestCompletionSignal(events: RetestSessionEvent[] | undefined) {
  return Boolean(events?.some((event) => {
    const metadata = event.metadata ?? {};
    return event.title.includes('复测结论总览')
      || event.title.includes('会话完成')
      || metadata.phase === 'completion_summary';
  }));
}

function statusLooksRuntimeActive(value: string) {
  const status = asString(value);
  const text = status.toLowerCase();
  return Boolean(
    status.includes('正在')
    || status.includes('压缩中')
    || status.includes('自动压缩')
    || status.includes('运行中')
    || status.includes('处理中')
    || text.includes('running')
  );
}

function statusLooksWholeRetestComplete(value: string) {
  const status = asString(value);
  const text = status.toLowerCase();
  if (status.includes('未完成') || text.includes('incomplete')) return false;
  return Boolean(
    status.includes('复测完成')
    || status.includes('会话完成')
    || status.includes('报告生成完成')
    || text.includes('completed')
  );
}

export function isRetestSessionTerminal(session: RetestSessionDraft | null | undefined) {
  if (!session) return false;
  if (Number(session.progress ?? 0) >= 100) return true;
  if (statusLooksWholeRetestComplete(session.status || '')) return true;
  if (session.progressEvidence?.hasCompletionSummary) return true;
  return hasRetestCompletionSignal(session.events);
}

function eventReports(event: RetestSessionEvent) {
  const metadataReports = isRecord(event.metadata) ? sanitizeStringArray(event.metadata.reports, 1000) : [];
  return metadataReports;
}

function sessionHasReportEvidence(events: RetestSessionEvent[] | undefined) {
  return Boolean(events?.some((event) => eventReports(event).length > 0 || (event.tool?.toolId === 'generate_report' && (event.tool.rawCount ?? 0) > 0)));
}

function isGenerateReportTool(event: RetestSessionEvent) {
  const toolId = event.tool?.toolId || '';
  const label = event.tool?.label || event.title || '';
  return toolId === 'generate_report' || label.includes('生成报告') || label.includes('报告生成');
}

function sanitizeSession(value: unknown): RetestSessionDraft | null {
  if (!isRecord(value)) return null;
  const createdAt = asString(value.createdAt, nowIso());
  const updatedAt = asString(value.updatedAt, createdAt);
  const targetDir = asString(value.targetDir);
  const workspaceRoot = asString(value.workspaceRoot);
  const sessionId = asString(value.sessionId, makeId('session'));
  const runtimeSessionId = getRuntimeSessionId();
  const events = sanitizeEvents(value.events, value.agentMessages);
  const rawResumeState = sanitizeResumeState(value.resumeState);
  const memoryMarkdown = trimMemoryText(value.memoryMarkdown, SESSION_MEMORY_TEXT_LIMIT);
  const memoryHints = { ...sanitizeProgressEvidence(memoryNumberHints(memoryMarkdown)), targetDir };
  const rawProgressEvidence = sanitizeProgressEvidence(value.progressEvidence);
  const isRunning = Boolean(value.isRunning && runtimeSessionId && runtimeSessionId === sessionId);
  const resumeState = isRunning ? null : rawResumeState;
  const progressEvidence = mergeProgressEvidenceForTarget(
    targetDir || rawResumeState?.targetDir || '',
    { ...rawProgressEvidence, targetDir: rawProgressEvidence.targetDir || targetDir },
    progressEvidenceFromResumeState(resumeState),
    { ...progressEvidenceFromEvents(events), targetDir },
    memoryHints,
    ...events.map(progressEvidenceFromEventMetadata),
  );
  let status = asString(value.status, '等待开始测试...');
  let progress = Math.max(0, Math.min(100, asNumber(value.progress, 0)));
  const completedSession = progress >= 100 || statusLooksWholeRetestComplete(status) || hasRetestCompletionSignal(events);
  if (!isRunning && completedSession) {
    progress = 100;
    if (statusLooksRuntimeActive(status) || status.includes('等待') || !statusLooksWholeRetestComplete(status) || !status.trim()) {
      status = '复测完成';
    }
  } else if (!isRunning && statusLooksRuntimeActive(status)) {
    status = rawResumeState?.canContinue ? '等待继续' : '已停止';
  }
  const session: RetestSessionDraft = {
    sessionId,
    sessionTitle: asString(value.sessionTitle, getFolderName(targetDir)),
    targetDir,
    workspaceRoot,
    status,
    progress,
    resultText: asString(value.resultText),
    log: asString(value.log),
    lastReportPath: asString(value.lastReportPath),
    events,
    latestResultData: isRecord(value.latestResultData) ? value.latestResultData : null,
    resumeState,
    progressEvidence,
    memoryMarkdown,
    generateReports: Boolean(value.generateReports),
    createdAt,
    updatedAt,
    isRunning,
  };
  session.events = settleRunningToolEvents(session.events, session, {
    isRunning: session.isRunning,
    status: session.status,
    progress: session.progress,
    resumeState: session.resumeState,
  }) ?? [];
  const sessionEvents = session.events ?? [];
  session.progressEvidence = mergeProgressEvidenceForTarget(
    session.targetDir || session.resumeState?.targetDir || '',
    session.progressEvidence,
    { ...progressEvidenceFromEvents(sessionEvents), targetDir: session.targetDir || '' },
    progressEvidenceFromResumeState(session.resumeState),
    ...sessionEvents.map(progressEvidenceFromEventMetadata),
  );
  return session;
}

function settleRunningToolEvents(
  events: RetestSessionEvent[] | undefined,
  currentSession: RetestSessionDraft,
  partial: Partial<RetestSessionDraft>,
): RetestSessionEvent[] | undefined {
  if (partial.isRunning !== false || !events?.length) return events;
  const resumeState = partial.resumeState === undefined ? currentSession.resumeState : partial.resumeState;
  const statusText = asString(partial.status, currentSession.status || '');
  const progress = partial.progress === undefined ? Number(currentSession.progress ?? 0) : Number(partial.progress ?? 0);
  const isBlocked = Boolean(resumeState && resumeState.canContinue);
  const isStopped = statusText.includes('停止') || statusText.toLowerCase().includes('stop');
  const isFailed = statusText.includes('失败') || statusText.includes('错误') || statusText.toLowerCase().includes('fail') || statusText.toLowerCase().includes('error');
  const finished = progress >= 100 || statusText.includes('完成') || statusText.toLowerCase().includes('complete');
  if (!isBlocked && !isStopped && !isFailed && !finished) return events;

  const hasReportEvidence = sessionHasReportEvidence(events);
  const nextStatus: RetestToolTrace['status'] = isBlocked ? 'blocked' : isStopped ? 'skipped' : isFailed ? 'failed' : 'completed';
  const fallbackPreview = isBlocked
    ? '会话已暂停，工具等待继续后确认。'
    : isStopped
      ? '会话已停止，工具未返回单独完成事件。'
      : isFailed
        ? '会话已失败，工具未返回单独完成事件。'
        : '会话已结束，工具未返回单独完成事件，已按会话终态收敛。';

  const isCompactionTool = (event: RetestSessionEvent, tool: RetestToolTrace) => {
    const metadata = isRecord(event.metadata) ? event.metadata : {};
    return tool.toolId === 'doc.retest.session.compact'
      || tool.label?.includes('AI 语义压缩')
      || event.title.includes('AI 语义压缩')
      || metadata.phase === 'slash_command_compact_ai'
      || metadata.phase === 'session_compaction';
  };

  const compactionStatusFromSession = (event: RetestSessionEvent, tool: RetestToolTrace): RetestToolTrace['status'] => {
    const eventText = `${event.title}\n${event.content || ''}\n${tool.resultPreview || ''}\n${tool.failureReason || ''}`;
    if (eventText.includes('语义压缩完成') || eventText.includes('语义记忆已更新') || eventText.includes('已压缩')) return 'completed';
    if (statusText.includes('语义记忆已更新') || statusText.includes('已压缩')) return 'completed';
    if (eventText.includes('未完成') || eventText.includes('失败') || eventText.includes('调用失败') || eventText.includes('超时') || statusText.includes('未完成')) return 'incomplete';
    if (statusText.includes('压缩中') || statusText.includes('自动压缩') || eventText.includes('压缩中') || eventText.includes('正在')) return 'running';
    return 'running';
  };

  return events.map((event) => {
    if (event.type !== 'tool_call' && event.type !== 'tool_result') return event;
    const tool = event.tool;
    if (!tool) return event;
    if (isCompactionTool(event, tool) && (tool.status === 'running' || tool.status === 'blocked')) {
      const eventStatus = compactionStatusFromSession(event, tool);
      const eventTone: RetestSessionEvent['tone'] = eventStatus === 'completed' ? 'ok' : eventStatus === 'running' ? 'info' : 'warn';
      return {
        ...event,
        tone: eventTone,
        tool: {
          ...tool,
          status: eventStatus,
          resultPreview: tool.resultPreview || event.content || (eventStatus === 'running'
            ? 'AI 语义压缩正在进行，原会话会在成功前保持完整。'
            : 'AI 语义压缩未完成，原会话未裁剪。'),
          failureReason: eventStatus === 'incomplete' ? tool.failureReason : undefined,
        },
        metadata: {
          ...(event.metadata ?? {}),
          settledByCompactionState: true,
        },
      };
    }
    if (tool.status && tool.status !== 'running') return event;
    const reportToolWithoutFile = nextStatus === 'completed' && isGenerateReportTool(event) && !hasReportEvidence;
    const eventStatus: RetestToolTrace['status'] = reportToolWithoutFile ? 'failed' : nextStatus;
    const eventPreview = reportToolWithoutFile ? '报告工具没有返回任何真实报告路径，已按未生成报告处理。' : fallbackPreview;
    return {
      ...event,
      tone: eventStatus === 'failed' ? 'error' : eventStatus === 'blocked' || eventStatus === 'skipped' ? 'warn' : event.tone,
      tool: {
        ...tool,
        status: eventStatus,
        resultPreview: tool.resultPreview || event.content || eventPreview,
        failureReason: eventStatus === 'failed' ? tool.failureReason || eventPreview : tool.failureReason,
      },
      metadata: {
        ...(event.metadata ?? {}),
        settledBySessionEnd: true,
        reportMissing: reportToolWithoutFile || undefined,
      },
    };
  });
}

function sanitizeStore(value: unknown): RetestSessionStore {
  if (!isRecord(value)) return { sessions: [] };
  const sessions = Array.isArray(value.sessions) ? value.sessions.map(sanitizeSession).filter((item): item is RetestSessionDraft => Boolean(item)) : [];
  const sortedSessions = sessions
    .sort((left, right) => Date.parse(right.updatedAt || '') - Date.parse(left.updatedAt || ''))
    .slice(0, MAX_RETEST_SESSIONS);
  const sessionIds = new Set(sortedSessions.map((session) => session.sessionId));
  const selectedSessionId = getSessionStorageValue(RETEST_ACTIVE_SESSION_KEY);
  const storedSessionId = asString(value.activeSessionId);
  const activeSessionId = [selectedSessionId, storedSessionId].find((sessionId) => sessionId && sessionIds.has(sessionId));
  return { activeSessionId, sessions: sortedSessions };
}

function splitLogTail(log: string | undefined, limit: number) {
  const lines = asString(log).split('\n').filter(Boolean);
  return lines.slice(-limit).join('\n');
}

function compactToolTraceForStorage(tool: RetestToolTrace | undefined): RetestToolTrace | undefined {
  if (!tool) return undefined;
  return {
    ...tool,
    argsPreview: trimStorageText(tool.argsPreview, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    resultPreview: trimStorageText(tool.resultPreview, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    rawOutput: trimStorageText(tool.rawOutput, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    evidence: trimStorageText(tool.evidence, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    pythonProbeScript: trimStorageText(tool.pythonProbeScript, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    requestRaw: trimStorageText(tool.requestRaw, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    requestSafe: trimStorageText(tool.requestSafe, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    responseBodyPreview: trimStorageText(tool.responseBodyPreview, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    responseRawExcerpt: trimStorageText(tool.responseRawExcerpt, COMPACT_TOOL_TEXT_LIMIT) || undefined,
    failureReason: trimStorageText(tool.failureReason, COMPACT_TOOL_TEXT_LIMIT) || undefined,
  };
}

function compactEventForStorage(event: RetestSessionEvent): RetestSessionEvent {
  return {
    ...event,
    content: trimStorageText(event.content, COMPACT_EVENT_TEXT_LIMIT),
    tool: compactToolTraceForStorage(event.tool),
    metadata: sanitizeEventMetadata(event.metadata),
  };
}

function compactSessionForStorage(session: RetestSessionDraft): RetestSessionDraft {
  return {
    ...session,
    resultText: trimStorageText(session.resultText, COMPACT_EVENT_TEXT_LIMIT * 2),
    log: splitLogTail(session.log, 160),
    latestResultData: null,
    memoryMarkdown: trimMemoryText(session.memoryMarkdown, SESSION_MEMORY_TEXT_LIMIT),
    events: (session.events ?? []).slice(-COMPACT_SESSION_EVENTS).map(compactEventForStorage),
  };
}

function storageSize(value: unknown) {
  try {
    return JSON.stringify(value).length;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

function uniqueLines(lines: string[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const line of lines) {
    const cleaned = line.trim();
    if (!cleaned || seen.has(cleaned)) continue;
    seen.add(cleaned);
    result.push(cleaned);
  }
  return result;
}

function sessionMemoryLessons(session: RetestSessionDraft, originalEventCount: number, originalSize: number) {
  const evidence = session.progressEvidence;
  const resume = session.resumeState;
  const lessons = [
    '继续/恢复时必须优先使用已完成文件名和 nextIndex 恢复断点，避免重复复测已完成通报。',
    '压缩只应减少冗余原始事件，不应丢弃目标、断点、已完成证据、最近结论和报告路径。',
  ];
  if ((evidence?.completedFileNames?.length ?? 0) > 0) {
    lessons.push(`当前会话已有 ${evidence?.completedFileNames.length ?? 0} 个已完成文件证据，后续继续要从下一份未完成通报开始。`);
  }
  if (resume?.canContinue) {
    lessons.push(`当前会话存在可继续断点：nextIndex=${resume.nextIndex}，继续时不要重新从第 1 份开始。`);
  }
  const currentFile = resume?.currentFile ?? null;
  const currentStage = asString(currentFile?.stage).trim().toLowerCase();
  const currentSnapshot = isRecord(currentFile?.resumeSnapshot) ? currentFile.resumeSnapshot : null;
  const currentFileName = getSourceNoticeFileName(asString(currentFile?.sourceFileName) || asString(currentFile?.sourceFile));
  if (currentFileName) {
    lessons.push(`Resume checkpoint: currentFile=${currentFileName}, stage=${currentStage || 'unknown'}; continue must use resumeState.currentFile.resumeSnapshot before rerunning this file.`);
  }
  if (['result', 'completed', 'judgement_complete'].includes(currentStage)) {
    lessons.push('Result-stage checkpoint means final judgement is complete; continue must reuse resumeSnapshot.result_data and must not rerun probes or judgement.');
  }
  if (currentStage === 'report' || currentStage === 'report_generation') {
    lessons.push('Report-stage checkpoint means retest judgement is already complete; continue should generate the report only and must not rerun probes or judgement.');
  }
  if (['execution', 'verification', 'tool'].includes(currentStage)) {
    const completedUrls = asNumber(currentSnapshot?.completed_url_count, asNumber(currentSnapshot?.next_url_index, 0));
    const totalUrls = asNumber(currentSnapshot?.total_url_count, 0);
    lessons.push(`Execution-stage checkpoint stores scan_result, valid_urls, retest_results, and next_url_index=${asNumber(currentSnapshot?.next_url_index, 0)}; continue must skip ${completedUrls}/${totalUrls || '?'} completed URL result(s) and resume from the next URL.`);
  }
  if (session.lastReportPath) {
    lessons.push('报告路径是最终交付证据，压缩后仍要保留最近报告位置。');
  }
  if (originalEventCount > COMPACT_SESSION_EVENTS || originalSize > AUTO_COMPACT_SESSION_LIMIT) {
    lessons.push('会话动态过大时应自动压缩并继续运行，不能把压缩当作任务终止。');
  }
  return uniqueLines(lessons).map((line) => `- ${line}`).join('\n');
}

function eventMemoryLine(event: RetestSessionEvent) {
  const meta = isRecord(event.metadata) ? event.metadata : {};
  const source = getSourceNoticeFileName(asString(meta.sourceFileName) || asString(event.sourceFile));
  const prefix = [event.timestamp, event.type, event.title, source ? `文件: ${source}` : ''].filter(Boolean).join(' / ');
  const toolText = event.tool
    ? [
        event.tool.label || event.tool.toolId || '',
        event.tool.status || '',
        event.tool.target || '',
        event.tool.resultPreview || event.tool.failureReason || '',
      ].filter(Boolean).join(' | ')
    : '';
  const content = trimMemoryText(event.content || toolText, 420).replace(/\n+/g, ' / ');
  return `- ${prefix}${content ? `: ${content}` : ''}`;
}

function sessionMemoryNewContent(
  session: RetestSessionDraft,
  originalEventCount: number,
  keptEventCount: number,
  originalSize: number,
) {
  const evidence = session.progressEvidence;
  const resume = session.resumeState;
  const lines = [
    `状态: ${session.status || '等待开始测试...'}`,
    `进度: ${Math.round(Number(session.progress ?? 0))}%`,
    `原始动态: ${originalEventCount} 条，压缩后保留最近 ${keptEventCount} 条；压缩前大小约 ${Math.round(originalSize / 1024)} KB。`,
  ];
  const targetDir = session.targetDir || resume?.targetDir || evidence?.targetDir || '';
  if (targetDir) lines.push(`目标目录: ${targetDir}`);
  if (evidence?.completedFileNames?.length) {
    lines.push(`已完成文件证据: ${evidence.completedFileNames.length} 个。`);
    lines.push(`最近已完成: ${evidence.completedFileNames.slice(-12).join('；')}`);
  }
  if (evidence?.latestSourceFileName) lines.push(`最近处理文件: ${evidence.latestSourceFileName}`);
  if (resume) {
    lines.push(`断点: canContinue=${resume.canContinue ? 'true' : 'false'}，nextIndex=${resume.nextIndex}，总数=${resume.sourceFiles.length}。`);
    if (resume.blockedReason) lines.push(`暂停原因: ${resume.blockedReason}`);
  }
  if (session.resultText) lines.push(`最近结果摘要:\n${trimMemoryText(session.resultText, 2400)}`);
  if (session.lastReportPath) lines.push(`最近报告: ${session.lastReportPath}`);
  const currentFile = resume?.currentFile ?? null;
  const currentStage = asString(currentFile?.stage).trim().toLowerCase();
  const currentSnapshot = isRecord(currentFile?.resumeSnapshot) ? currentFile.resumeSnapshot : null;
  const currentFileName = getSourceNoticeFileName(asString(currentFile?.sourceFileName) || asString(currentFile?.sourceFile));
  if (currentFileName) {
    lines.push(`currentFileCheckpoint: stage=${currentStage || 'unknown'}, index=${Math.max(0, asNumber(currentFile?.index, 0))}, file=${currentFileName}`);
  }
  if (['result', 'completed', 'judgement_complete'].includes(currentStage)) {
    lines.push('currentFileCheckpointMeaning: final judgement complete; reuse resumeSnapshot.result_data and do not rerun retest probes or judgement.');
  }
  if (currentStage === 'report' || currentStage === 'report_generation') {
    lines.push('currentFileCheckpointMeaning: judgement complete; resume by generating report only, do not rerun retest probes or judgement.');
  }
  if (['execution', 'verification', 'tool'].includes(currentStage)) {
    const completedUrls = asNumber(currentSnapshot?.completed_url_count, asNumber(currentSnapshot?.next_url_index, 0));
    const totalUrls = asNumber(currentSnapshot?.total_url_count, 0);
    lines.push(`currentFileCheckpointMeaning: execution checkpoint; scan_result/valid_urls/retest_results are stored, next_url_index=${asNumber(currentSnapshot?.next_url_index, 0)}, completed_urls=${completedUrls}/${totalUrls || '?'}. Continue from the next URL without repeating completed URL results.`);
  }
  const recentImportantEvents = (session.events ?? [])
    .filter((event) => event.type === 'chat' || event.type === 'artifact' || event.type === 'error' || event.title.includes('复测结果') || event.title.includes('断点') || event.title.includes('自动继续'))
    .slice(-24)
    .map(eventMemoryLine);
  if (recentImportantEvents.length) {
    lines.push(`最近关键事件:\n${recentImportantEvents.join('\n')}`);
  }
  return lines.join('\n');
}

function makeSessionMemoryMarkdown(session: RetestSessionDraft, originalEventCount: number, keptEventCount: number, originalSize: number) {
  const target = session.targetDir || session.resumeState?.targetDir || session.progressEvidence?.targetDir || session.sessionTitle || '未命名会话';
  const previous = trimMemoryText(session.memoryMarkdown || '暂无上一段总结。', SESSION_MEMORY_SECTION_LIMIT);
  const lessons = sessionMemoryLessons(session, originalEventCount, originalSize);
  const newContent = sessionMemoryNewContent(session, originalEventCount, keptEventCount, originalSize);
  return trimMemoryText([
    `目标: ${target}`,
    '--------------',
    '值得总结的经验',
    '--------------',
    lessons || '- 暂无新增经验。',
    '--------------',
    '上一段总结',
    '--------------',
    previous,
    '--------------',
    '新的内容',
    '--------------',
    newContent || '暂无新增内容。',
  ].join('\n'), SESSION_MEMORY_TEXT_LIMIT);
}

function makeSessionCompactionEvent(
  session: RetestSessionDraft,
  originalEventCount: number,
  keptEventCount: number,
  originalSize: number,
  memoryMarkdown?: string,
): RetestSessionEvent {
  const content = trimMemoryText(memoryMarkdown || makeSessionMemoryMarkdown(session, originalEventCount, keptEventCount, originalSize), SESSION_MEMORY_TEXT_LIMIT);
  return makeRetestSessionEvent('status', '会话已压缩', content, 'ok', {
    metadata: {
      phase: 'session_compaction',
      originalEventCount,
      keptEventCount,
      originalSize,
      targetDir: session.targetDir || session.resumeState?.targetDir || session.progressEvidence?.targetDir || '',
      progressEvidence: session.progressEvidence,
      resumeState: session.resumeState,
    },
  });
}

function compactSessionWithSummary(session: RetestSessionDraft, updateTimestamp: boolean, semanticMemoryMarkdown?: string): RetestSessionDraft {
  const originalEvents = session.events ?? [];
  const keptEvents = originalEvents.slice(-COMPACT_SESSION_EVENTS).map(compactEventForStorage);
  const originalSize = storageSize(session);
  const memoryMarkdown = trimMemoryText(
    semanticMemoryMarkdown || makeSessionMemoryMarkdown(session, originalEvents.length, keptEvents.length, originalSize),
    SESSION_MEMORY_TEXT_LIMIT,
  );
  const summary = makeSessionCompactionEvent(session, originalEvents.length, keptEvents.length, originalSize, memoryMarkdown);
  return {
    ...compactSessionForStorage(session),
    memoryMarkdown,
    events: [summary, ...keptEvents].slice(-(COMPACT_SESSION_EVENTS + 1)),
    updatedAt: updateTimestamp ? nowIso() : session.updatedAt,
  };
}

function compactSessionForManualAction(session: RetestSessionDraft): RetestSessionDraft {
  return compactSessionWithSummary(session, true);
}

function shouldAutoCompactSession(session: RetestSessionDraft, forceByStoreSize: boolean) {
  const size = storageSize(session);
  const eventCount = session.events?.length ?? 0;
  return size > AUTO_COMPACT_SESSION_LIMIT
    || eventCount > AUTO_COMPACT_EVENT_COUNT
    || (forceByStoreSize && (size > AUTO_COMPACT_FORCE_SESSION_LIMIT || eventCount > COMPACT_SESSION_EVENTS));
}

function compactStoreForAutoStorage(store: RetestSessionStore, updateTimestamps = false): { store: RetestSessionStore; compacted: boolean } {
  const forceByStoreSize = storageSize(store) > AUTO_COMPACT_STORE_LIMIT;
  let compacted = false;
  const sessions = store.sessions.map((session) => {
    if (session.isRunning && !forceByStoreSize && (session.events?.length ?? 0) <= MAX_SESSION_EVENTS && storageSize(session) <= AUTO_COMPACT_SESSION_LIMIT) {
      return session;
    }
    if (!shouldAutoCompactSession(session, forceByStoreSize)) return session;
    compacted = true;
    return compactSessionWithSummary(session, updateTimestamps);
  });
  return { store: compacted ? { ...store, sessions } : store, compacted };
}

function compactStoreForStorage(store: RetestSessionStore): RetestSessionStore {
  return {
    ...store,
    sessions: store.sessions.map(compactSessionForStorage),
  };
}

function persistStoreNow(store: RetestSessionStore) {
  if (!hasWindowStorage()) return;
  const serialized = JSON.stringify(store);
  try {
    window.localStorage.setItem(RETEST_SESSION_STORAGE_KEY, serialized);
  } catch (error) {
    const compacted = compactStoreForStorage(store);
    memoryStore = compacted;
    try {
      window.localStorage.setItem(RETEST_SESSION_STORAGE_KEY, JSON.stringify(compacted));
      if (typeof console !== 'undefined') {
        console.warn('Retest session storage was compacted after a quota error.', error);
      }
    } catch (compactError) {
      if (typeof console !== 'undefined') {
        console.error('Retest session storage failed after compaction.', compactError);
      }
      throw compactError;
    }
  }
}

export function flushRetestSessionStoreNow() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (!memoryStore) return;
  persistStoreNow(memoryStore);
}

function ensureStorageFlushHandlers() {
  if (flushHandlersInstalled || typeof window === 'undefined') return;
  flushHandlersInstalled = true;
  window.addEventListener('beforeunload', flushRetestSessionStoreNow);
  window.addEventListener('pagehide', flushRetestSessionStoreNow);
}

function scheduleRetestSessionStoreFlush() {
  ensureStorageFlushHandlers();
  if (typeof window === 'undefined') {
    flushRetestSessionStoreNow();
    return;
  }
  if (flushTimer) return;
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    if (memoryStore) persistStoreNow(memoryStore);
  }, STORAGE_FLUSH_DELAY_MS);
}

function readLegacyStore(): RetestSessionStore {
  if (!hasWindowStorage()) return { sessions: [] };
  for (const key of LEGACY_RETEST_SESSION_STORAGE_KEYS) {
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      if (key === 'koi.retest.session.v1') {
        const session = sanitizeSession({
          ...parsed,
          sessionId: makeId('session'),
          sessionTitle: getFolderName(asString(parsed?.targetDir)) || '历史测试会话',
          createdAt: nowIso(),
          updatedAt: nowIso(),
        });
        return session ? { activeSessionId: session.sessionId, sessions: [session] } : { sessions: [] };
      }
      return sanitizeStore(parsed);
    } catch {
      window.localStorage.removeItem(key);
    }
  }
  return { sessions: [] };
}

export function broadcastRetestSessionChanged(immediate = false) {
  if (typeof window === 'undefined') return;
  if (!immediate) {
    if (broadcastTimer) return;
    broadcastTimer = window.setTimeout(() => {
      broadcastTimer = null;
      window.dispatchEvent(new CustomEvent(RETEST_SESSION_CHANGED_EVENT));
    }, SESSION_CHANGE_BROADCAST_DELAY_MS);
    return;
  }
  if (broadcastTimer) {
    clearTimeout(broadcastTimer);
    broadcastTimer = null;
  }
  window.dispatchEvent(new CustomEvent(RETEST_SESSION_CHANGED_EVENT));
}

export function readRetestSessionStore(): RetestSessionStore {
  if (memoryStore) return memoryStore;
  if (!hasWindowStorage()) return { sessions: [] };
  try {
    const raw = window.localStorage.getItem(RETEST_SESSION_STORAGE_KEY);
    if (raw) {
      const sanitized = sanitizeStore(JSON.parse(raw));
      const autoCompacted = compactStoreForAutoStorage(sanitized);
      const normalized = autoCompacted.store;
      const normalizedRaw = JSON.stringify(normalized);
      if (shouldPersistNormalizedRaw(raw, normalizedRaw, autoCompacted.compacted)) {
        try {
          window.localStorage.setItem(RETEST_SESSION_STORAGE_KEY, normalizedRaw);
        } catch (error) {
          if (typeof console !== 'undefined') {
            console.warn('Retest session auto compaction could not be persisted.', error);
          }
        }
      }
      memoryStore = normalized;
      return normalized;
    }
  } catch {
    window.localStorage.removeItem(RETEST_SESSION_STORAGE_KEY);
  }

  const migrated = readLegacyStore();
  if (migrated.sessions.length) {
    writeRetestSessionStore(migrated);
  }
  memoryStore = migrated;
  return migrated;
}

export function writeRetestSessionStore(store: RetestSessionStore) {
  const sanitized = compactStoreForAutoStorage(sanitizeStore(store)).store;
  memoryStore = sanitized;
  scheduleRetestSessionStoreFlush();
  broadcastRetestSessionChanged();
}

export function makeRetestSessionEvent(type: RetestSessionEventType, title: string, content = '', tone: RetestSessionEvent['tone'] = 'info', extra: Partial<RetestSessionEvent> = {}): RetestSessionEvent {
  return {
    id: makeId('event'),
    type,
    title,
    content,
    tone,
    timestamp: shortTime(),
    ...extra,
  };
}

export function makeRetestAgentMessage(role: RetestAgentMessage['role'], content: string, title?: string, tone: RetestAgentMessage['tone'] = 'info'): RetestAgentMessage {
  return {
    id: makeId('message'),
    role,
    title,
    content,
    tone,
    timestamp: shortTime(),
  };
}

export function sanitizeRetestSessionPatch(partial: unknown): Partial<RetestSessionDraft> {
  const repaired = repairRetestStoredValue(partial);
  return isRecord(repaired) ? repaired as Partial<RetestSessionDraft> : {};
}

export function createRetestSession(targetDir?: string, openingItems: Array<RetestSessionEvent | RetestAgentMessage> = []) {
  const store = readRetestSessionStore();
  const createdAt = nowIso();
  const events = openingItems
    .map((item) => ('role' in item ? agentMessageToEvent(item) : sanitizeEvent(item)))
    .filter((item): item is RetestSessionEvent => Boolean(item))
    .slice(-MAX_SESSION_EVENTS);
  const session: RetestSessionDraft = {
    sessionId: makeId('session'),
    sessionTitle: getFolderName(targetDir),
    targetDir: targetDir || '',
    workspaceRoot: '',
    status: '等待开始测试...',
    progress: 0,
    resultText: '',
    log: '',
    lastReportPath: '',
    latestResultData: null,
    resumeState: null,
    progressEvidence: { ...progressEvidenceFromEvents(events), targetDir: targetDir || '' },
    generateReports: events.some((event) => Boolean(event.metadata?.generateReports || event.metadata?.generate_reports)),
    events,
    createdAt,
    updatedAt: createdAt,
    isRunning: false,
  };
  setSessionStorageValue(RETEST_ACTIVE_SESSION_KEY, session.sessionId);
  writeRetestSessionStore({ activeSessionId: session.sessionId, sessions: [session, ...store.sessions] });
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
  return session;
}

export function patchRetestSession(sessionId: string | undefined, partial: Partial<RetestSessionDraft>) {
  if (!sessionId) return null;
  if (partial.isRunning === true) {
    setSessionStorageValue(RETEST_RUNTIME_SESSION_KEY, sessionId);
  } else if (partial.isRunning === false && getRuntimeSessionId() === sessionId) {
    removeSessionStorageValue(RETEST_RUNTIME_SESSION_KEY);
  }
  const normalizedPartial: Partial<RetestSessionDraft> = partial.isRunning === true
    ? { ...partial, resumeState: null }
    : partial;
  const store = readRetestSessionStore();
  let nextSession: RetestSessionDraft | null = null;
  const sessions = store.sessions.map((session) => {
    if (session.sessionId !== sessionId) return session;
    const settledEvents = settleRunningToolEvents(session.events, session, normalizedPartial);
    const nextTargetDir = normalizedPartial.targetDir || session.targetDir || normalizedPartial.resumeState?.targetDir || session.resumeState?.targetDir || '';
    const progressEvidence = mergeProgressEvidenceForTarget(
      nextTargetDir,
      session.progressEvidence,
      sanitizeProgressEvidence(normalizedPartial.progressEvidence),
      { ...progressEvidenceFromEvents(settledEvents), targetDir: nextTargetDir },
      progressEvidenceFromResumeState(normalizedPartial.resumeState === undefined ? session.resumeState : normalizedPartial.resumeState),
    );
    nextSession = sanitizeSession({
      ...session,
      ...normalizedPartial,
      events: settledEvents,
      progressEvidence,
      sessionId,
      updatedAt: nowIso(),
      sessionTitle: normalizedPartial.sessionTitle || session.sessionTitle || getFolderName(normalizedPartial.targetDir || session.targetDir),
    });
    return nextSession ?? session;
  });
  if (!nextSession) return null;
  writeRetestSessionStore({ activeSessionId: store.activeSessionId, sessions });
  return nextSession;
}

export function appendRetestSessionEvent(sessionId: string | undefined, event: RetestSessionEvent) {
  if (!sessionId) return null;
  return appendRetestSessionEvents(sessionId, [event])?.[0] ?? null;
}

export function appendRetestSessionEvents(sessionId: string | undefined, events: RetestSessionEvent[]) {
  if (!sessionId || !events.length) return null;
  const store = readRetestSessionStore();
  let appended: RetestSessionEvent[] | null = null;
  const sessions = store.sessions.map((session) => {
    if (session.sessionId !== sessionId) return session;
    const currentEvents = [...(session.events ?? [])];
    const existingIds = new Set(currentEvents.map((item) => item.id));
    const changedEvents: RetestSessionEvent[] = [];
    for (const rawEvent of events) {
      const item = sanitizeEvent(rawEvent);
      if (!item || existingIds.has(item.id)) continue;
      const upsertKey = eventStreamKey(item) || eventToolKey(item);
      const existingEventIndex = upsertKey ? currentEvents.findIndex((event) => (eventStreamKey(event) || eventToolKey(event)) === upsertKey) : -1;
      if (existingEventIndex >= 0) {
        const previous = currentEvents[existingEventIndex];
        const merged: RetestSessionEvent = {
          ...previous,
          ...item,
          id: previous.id,
          tool: {
            ...(previous.tool ?? {}),
            ...(item.tool ?? {}),
          },
          metadata: {
            ...(previous.metadata ?? {}),
            ...(item.metadata ?? {}),
          },
        };
        currentEvents[existingEventIndex] = merged;
        changedEvents.push(merged);
        continue;
      }
      currentEvents.push(item);
      existingIds.add(item.id);
      changedEvents.push(item);
    }
    appended = changedEvents;
    const targetDir = session.targetDir || session.resumeState?.targetDir || '';
    const progressEvidence = mergeProgressEvidenceForTarget(
      targetDir,
      session.progressEvidence,
      { ...progressEvidenceFromEvents(currentEvents), targetDir },
    );
    const eventRequestsReports = changedEvents.some((event) => Boolean(event.metadata?.generateReports || event.metadata?.generate_reports));
    return {
      ...session,
      events: currentEvents.slice(-MAX_SESSION_EVENTS),
      progressEvidence,
      generateReports: Boolean(session.generateReports || eventRequestsReports),
      updatedAt: nowIso(),
    };
  });
  if (!appended) return null;
  writeRetestSessionStore({ activeSessionId: store.activeSessionId, sessions });
  return appended;
}

export function appendRetestAgentMessage(sessionId: string | undefined, message: RetestAgentMessage) {
  return appendRetestSessionEvent(sessionId, agentMessageToEvent(message));
}

export function setActiveRetestSession(sessionId: string) {
  const store = readRetestSessionStore();
  if (!store.sessions.some((session) => session.sessionId === sessionId)) return;
  setSessionStorageValue(RETEST_ACTIVE_SESSION_KEY, sessionId);
  writeRetestSessionStore({ ...store, activeSessionId: sessionId });
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
}

export function deleteRetestSession(sessionId: string | undefined) {
  if (!sessionId) return null;
  const store = readRetestSessionStore();
  const sessions = store.sessions.filter((session) => session.sessionId !== sessionId);
  const activeSessionId = store.activeSessionId === sessionId ? sessions[0]?.sessionId : store.activeSessionId;
  if (activeSessionId) {
    setSessionStorageValue(RETEST_ACTIVE_SESSION_KEY, activeSessionId);
  } else {
    removeSessionStorageValue(RETEST_ACTIVE_SESSION_KEY);
  }
  writeRetestSessionStore({ activeSessionId, sessions });
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
  return activeSessionId ?? null;
}

function compactResultForSession(before: RetestSessionDraft, after: RetestSessionDraft): RetestSessionCompactResult {
  return {
    sessionId: after.sessionId,
    sessionTitle: after.sessionTitle || before.sessionTitle || getFolderName(after.targetDir || before.targetDir),
    beforeBytes: JSON.stringify(before).length,
    afterBytes: JSON.stringify(after).length,
    beforeEvents: before.events?.length ?? 0,
    afterEvents: after.events?.length ?? 0,
    memoryBytes: after.memoryMarkdown ? after.memoryMarkdown.length : 0,
    memoryUpdated: trimMemoryText(before.memoryMarkdown, SESSION_MEMORY_TEXT_LIMIT) !== trimMemoryText(after.memoryMarkdown, SESSION_MEMORY_TEXT_LIMIT),
  };
}

export function previewCompactRetestSession(sessionId: string | undefined): RetestSessionCompactResult | null {
  if (!sessionId) return null;
  const store = readRetestSessionStore();
  const session = store.sessions.find((item) => item.sessionId === sessionId);
  if (!session) return null;
  const compacted = compactSessionWithSummary(session, false);
  return compactResultForSession(session, compacted);
}

export function commitCompactRetestSession(sessionId: string | undefined, semanticMemoryMarkdown: string): RetestSessionCompactResult | null {
  if (!sessionId) return null;
  const memoryMarkdown = trimMemoryText(semanticMemoryMarkdown, SESSION_MEMORY_TEXT_LIMIT);
  if (!memoryMarkdown) return null;
  const store = readRetestSessionStore();
  let result: RetestSessionCompactResult | null = null;
  const sessions = store.sessions.map((session) => {
    if (session.sessionId !== sessionId) return session;
    const compacted = compactSessionWithSummary(session, true, memoryMarkdown);
    result = compactResultForSession(session, compacted);
    return compacted;
  });
  if (!result) return null;
  writeRetestSessionStore({ activeSessionId: store.activeSessionId, sessions });
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
  return result;
}

export function compactRetestSession(sessionId: string | undefined): RetestSessionCompactResult | null {
  if (!sessionId) return null;
  const store = readRetestSessionStore();
  let result: RetestSessionCompactResult | null = null;
  const sessions = store.sessions.map((session) => {
    if (session.sessionId !== sessionId) return session;
    const compacted = compactSessionForManualAction(session);
    result = compactResultForSession(session, compacted);
    return compacted;
  });
  if (!result) return null;
  writeRetestSessionStore({ activeSessionId: store.activeSessionId, sessions });
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
  return result;
}

export function compactAllRetestSessions(excludeSessionId?: string): RetestSessionCompactAllResult {
  const store = readRetestSessionStore();
  const beforeBytes = JSON.stringify(store).length;
  const results: RetestSessionCompactResult[] = [];
  const sessions = store.sessions.map((session) => {
    if (excludeSessionId && session.sessionId === excludeSessionId) return session;
    const compacted = compactSessionForManualAction(session);
    results.push(compactResultForSession(session, compacted));
    return compacted;
  });
  const nextStore = { activeSessionId: store.activeSessionId, sessions };
  writeRetestSessionStore(nextStore);
  flushRetestSessionStoreNow();
  broadcastRetestSessionChanged(true);
  return {
    activeSessionId: store.activeSessionId,
    sessionCount: results.length,
    failedCount: 0,
    beforeBytes,
    afterBytes: JSON.stringify(nextStore).length,
    results,
  };
}

export function getActiveRetestSession() {
  const store = readRetestSessionStore();
  return store.sessions.find((session) => session.sessionId === store.activeSessionId) ?? null;
}

export function resetRetestRuntimeSelection() {
  removeSessionStorageValue(RETEST_RUNTIME_SESSION_KEY);
  removeSessionStorageValue(RETEST_ACTIVE_SESSION_KEY);
  removeSessionStorageValue(RETEST_RESUME_REQUEST_KEY);
  removeSessionStorageValue(RETEST_RERUN_REQUEST_KEY);
  broadcastRetestSessionChanged();
}
