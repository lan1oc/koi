export type RetestAgentMessage = {
  id: string;
  role: 'agent' | 'user' | 'system';
  title?: string;
  content: string;
  timestamp: string;
  tone?: 'info' | 'ok' | 'warn' | 'error';
};

export type RetestSessionEventType = 'status' | 'thought_summary' | 'tool_call' | 'tool_result' | 'artifact' | 'error' | 'chat';

export type RetestToolTrace = {
  toolId?: string;
  label?: string;
  status?: 'running' | 'completed' | 'failed' | 'skipped' | 'blocked';
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
  allLogs: string[];
  failedCount: number;
  generateReports?: boolean;
  blockedReason?: string;
  blockedStage?: string;
  blockedTitle?: string;
};

export type RetestSessionDraft = {
  sessionId: string;
  sessionTitle: string;
  targetDir?: string;
  status?: string;
  progress?: number;
  resultText?: string;
  log?: string;
  lastReportPath?: string;
  events?: RetestSessionEvent[];
  agentMessages?: RetestAgentMessage[];
  latestResultData?: Record<string, unknown> | null;
  resumeState?: RetestResumeState | null;
  createdAt: string;
  updatedAt: string;
  isRunning?: boolean;
};

export type RetestSessionStore = {
  activeSessionId?: string;
  sessions: RetestSessionDraft[];
};

export const RETEST_SESSION_STORAGE_KEY = 'koi.retest.sessions.v2';
export const RETEST_SESSION_CHANGED_EVENT = 'koi-retest-session-updated';
export const RETEST_RUNTIME_SESSION_KEY = 'koi.retest.runtime.active';
export const RETEST_ACTIVE_SESSION_KEY = 'koi.retest.ui.active';
export const RETEST_RESUME_REQUEST_KEY = 'koi.retest.resume.requested';
export const RETEST_RERUN_REQUEST_KEY = 'koi.retest.rerun.requested';

const LEGACY_RETEST_SESSION_STORAGE_KEYS = ['koi.retest.sessions.v1', 'koi.retest.session.v1'];
const MAX_RETEST_SESSIONS = 20;
const MAX_SESSION_EVENTS = 500;

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

function asString(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function asNumber(value: unknown, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
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

function sanitizeEventType(value: unknown): RetestSessionEventType {
  if (
    value === 'thought_summary' ||
    value === 'tool_call' ||
    value === 'tool_result' ||
    value === 'artifact' ||
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
  const status = value.status === 'running' || value.status === 'completed' || value.status === 'failed' || value.status === 'skipped' || value.status === 'blocked'
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
    responseMeta: isRecord(value.responseMeta || value.response_meta) ? (value.responseMeta || value.response_meta) as Record<string, unknown> : undefined,
    responseHeadersSafe: isRecord(value.responseHeadersSafe || value.response_headers_safe) ? (value.responseHeadersSafe || value.response_headers_safe) as Record<string, unknown> : undefined,
    responseBodyPreview: asString(value.responseBodyPreview || value.response_body_preview) || undefined,
    responseRawExcerpt: asString(value.responseRawExcerpt || value.response_raw_excerpt) || undefined,
    statusCode: value.statusCode !== undefined || value.status_code !== undefined ? asNumber(value.statusCode ?? value.status_code) : undefined,
    finalUrl: asString(value.finalUrl || value.final_url) || undefined,
    matchedMarkers: Array.isArray(matchedMarkersValue) ? matchedMarkersValue.map((item) => asString(item)).filter(Boolean) : undefined,
    failureReason: asString(value.failureReason || value.failure_reason) || undefined,
  };
}

function sanitizeEvent(value: unknown): RetestSessionEvent | null {
  if (!isRecord(value)) return null;
  const type = sanitizeEventType(value.type);
  let title = asString(value.title, type === 'tool_call' ? '工具调用' : '执行事件');
  let content = asString(value.content);
  const timestamp = asString(value.timestamp, shortTime());
  let tone = sanitizeTone(value.tone);
  const metadata = isRecord(value.metadata) ? value.metadata : undefined;
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
    tool: sanitizeToolTrace(value.tool),
    metadata,
  };
}

function eventStreamKey(event: RetestSessionEvent) {
  const metadata = event.metadata;
  if (!metadata || typeof metadata !== 'object' || !metadata.modelOutput) return '';
  const explicitKey = metadata.streamKey;
  if (typeof explicitKey === 'string' && explicitKey.trim()) return explicitKey.trim();
  const phase = typeof metadata.phase === 'string' ? metadata.phase : '';
  const roundId = typeof metadata.roundId === 'string' ? metadata.roundId : (typeof metadata.turnId === 'string' ? metadata.turnId : '');
  if (!phase && !roundId && !event.sourceFile) return '';
  return ['model-output', roundId, event.sourceFile || '', phase].join(':');
}

function eventToolKey(event: RetestSessionEvent) {
  if (event.type !== 'tool_call' && event.type !== 'tool_result') return '';
  const tool = event.tool;
  if (!tool) return '';
  const metadata = event.metadata ?? {};
  const toolCallId = metadata.toolCallId || metadata.tool_call_id;
  if (typeof toolCallId === 'string' && toolCallId.trim()) return `tool-call:${toolCallId.trim()}`;
  const roundId = typeof metadata.roundId === 'string' ? metadata.roundId : (typeof metadata.turnId === 'string' ? metadata.turnId : '');
  const identity = tool.toolId || tool.label || event.title;
  if (!identity) return '';
  return ['tool', roundId, event.sourceFile || '', identity, tool.target || ''].join(':');
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
  return value.filter(isRecord).slice(-limit);
}

function sanitizeResumeState(value: unknown): RetestResumeState | null {
  if (!isRecord(value)) return null;
  const sourceFiles = sanitizeStringArray(value.sourceFiles, 1000);
  const nextIndex = Math.max(0, Math.min(sourceFiles.length, asNumber(value.nextIndex, 0)));
  return {
    canContinue: Boolean(value.canContinue),
    targetDir: asString(value.targetDir),
    sourceFiles,
    nextIndex,
    summaries: sanitizeStringArray(value.summaries, 1000),
    reports: sanitizeStringArray(value.reports, 1000),
    completionItems: sanitizeRecordArray(value.completionItems, 1000),
    allLogs: sanitizeStringArray(value.allLogs, 3000),
    failedCount: Math.max(0, asNumber(value.failedCount, 0)),
    generateReports: Boolean(value.generateReports),
    blockedReason: asString(value.blockedReason) || undefined,
    blockedStage: asString(value.blockedStage) || undefined,
    blockedTitle: asString(value.blockedTitle) || undefined,
  };
}

function hasRetestCompletionSignal(events: RetestSessionEvent[] | undefined) {
  return Boolean(events?.some((event) => {
    const metadata = event.metadata ?? {};
    return event.title.includes('复测结果')
      || event.title.includes('复测结论')
      || event.title.includes('会话完成')
      || metadata.phase === 'completion_summary'
      || typeof metadata.fixStatus === 'string';
  }));
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
  const sessionId = asString(value.sessionId, makeId('session'));
  const runtimeSessionId = getRuntimeSessionId();
  const events = sanitizeEvents(value.events, value.agentMessages);
  const isRunning = Boolean(value.isRunning && runtimeSessionId && runtimeSessionId === sessionId);
  let status = asString(value.status, '等待开始测试...');
  let progress = Math.max(0, Math.min(100, asNumber(value.progress, 0)));
  if (!isRunning && progress === 0 && hasRetestCompletionSignal(events)) {
    progress = 100;
    if (status.includes('等待') || !status.trim()) {
      status = '复测完成';
    }
  }
  const session: RetestSessionDraft = {
    sessionId,
    sessionTitle: asString(value.sessionTitle, getFolderName(targetDir)),
    targetDir,
    status,
    progress,
    resultText: asString(value.resultText),
    log: asString(value.log),
    lastReportPath: asString(value.lastReportPath),
    events,
    latestResultData: isRecord(value.latestResultData) ? value.latestResultData : null,
    resumeState: sanitizeResumeState(value.resumeState),
    createdAt,
    updatedAt,
    isRunning,
  };
  session.events = settleRunningToolEvents(session.events, session, {
    isRunning: session.isRunning,
    status: session.status,
    progress: session.progress,
    resumeState: session.resumeState,
  });
  return session;
}

function settleRunningToolEvents(
  events: RetestSessionEvent[] | undefined,
  currentSession: RetestSessionDraft,
  partial: Partial<RetestSessionDraft>,
) {
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

  return events.map((event) => {
    if (event.type !== 'tool_call' && event.type !== 'tool_result') return event;
    const tool = event.tool;
    if (!tool || (tool.status && tool.status !== 'running')) return event;
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
  const runtimeSessionId = getRuntimeSessionId();
  const selectedSessionId = getSessionStorageValue(RETEST_ACTIVE_SESSION_KEY);
  const activeSessionId = [runtimeSessionId, selectedSessionId].find((sessionId) => sessionId && sessionIds.has(sessionId));
  return { activeSessionId, sessions: sortedSessions };
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

export function broadcastRetestSessionChanged() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(RETEST_SESSION_CHANGED_EVENT));
}

export function readRetestSessionStore(): RetestSessionStore {
  if (!hasWindowStorage()) return { sessions: [] };
  try {
    const raw = window.localStorage.getItem(RETEST_SESSION_STORAGE_KEY);
    if (raw) return sanitizeStore(JSON.parse(raw));
  } catch {
    window.localStorage.removeItem(RETEST_SESSION_STORAGE_KEY);
  }

  const migrated = readLegacyStore();
  if (migrated.sessions.length) {
    writeRetestSessionStore(migrated);
  }
  return migrated;
}

export function writeRetestSessionStore(store: RetestSessionStore) {
  if (!hasWindowStorage()) return;
  const sanitized = sanitizeStore(store);
  window.localStorage.setItem(RETEST_SESSION_STORAGE_KEY, JSON.stringify(sanitized));
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
    status: '等待开始测试...',
    progress: 0,
    resultText: '',
    log: '',
    lastReportPath: '',
    latestResultData: null,
    resumeState: null,
    events,
    createdAt,
    updatedAt: createdAt,
    isRunning: false,
  };
  setSessionStorageValue(RETEST_ACTIVE_SESSION_KEY, session.sessionId);
  writeRetestSessionStore({ activeSessionId: session.sessionId, sessions: [session, ...store.sessions] });
  return session;
}

export function patchRetestSession(sessionId: string | undefined, partial: Partial<RetestSessionDraft>) {
  if (!sessionId) return null;
  const store = readRetestSessionStore();
  let nextSession: RetestSessionDraft | null = null;
  const sessions = store.sessions.map((session) => {
    if (session.sessionId !== sessionId) return session;
    const settledEvents = settleRunningToolEvents(session.events, session, partial);
    nextSession = sanitizeSession({
      ...session,
      ...partial,
      events: settledEvents,
      sessionId,
      updatedAt: nowIso(),
      sessionTitle: partial.sessionTitle || session.sessionTitle || getFolderName(partial.targetDir || session.targetDir),
    });
    return nextSession ?? session;
  });
  if (!nextSession) return null;
  writeRetestSessionStore({ activeSessionId: sessionId, sessions });
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
    return {
      ...session,
      events: currentEvents.slice(-MAX_SESSION_EVENTS),
      updatedAt: nowIso(),
    };
  });
  if (!appended) return null;
  writeRetestSessionStore({ activeSessionId: sessionId, sessions });
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
  return activeSessionId ?? null;
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
