import { useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { callBackend } from '../../lib/backend';
import {
  RETEST_RUNTIME_SESSION_KEY,
  RETEST_RERUN_REQUEST_KEY,
  RETEST_RESUME_REQUEST_KEY,
  RETEST_SESSION_CHANGED_EVENT,
  appendRetestSessionEvent,
  appendRetestSessionEvents,
  compactAllRetestSessions,
  commitCompactRetestSession,
  createRetestSession,
  deleteRetestSession,
  makeRetestSessionEvent,
  patchRetestSession,
  previewCompactRetestSession,
  readRetestSessionStore,
  repairRetestText,
  sanitizeRetestSessionEvent,
  sanitizeRetestSessionPatch,
  setActiveRetestSession,
  type RetestSessionCompactAllResult,
  type RetestSessionCompactResult,
  type RetestResumeState,
  type RetestSessionDraft,
  type RetestSessionEvent,
  type RetestSessionStore,
  type RetestToolTrace,
} from './retestSessionStore';

type RetestAgentResponse = {
  success: boolean;
  message: string;
  final_message?: string;
  session_id?: string;
  running?: boolean;
  blocked?: boolean;
  approval_id?: string;
  operation_id?: string;
  auto_approved?: boolean;
  agent_session?: Record<string, unknown>;
  blocked_reason?: string;
  blocked_stage?: string;
  blocked_title?: string;
  source_files?: string[];
  next_index?: number;
  summaries?: string[];
  reports?: string[];
  completion_items?: Array<Record<string, unknown>>;
  logs?: string[];
  latest_result_data?: Record<string, unknown> | null;
  resume_state?: RetestResumeState | null;
  progress?: number;
  status?: string;
  generate_reports?: boolean;
};

type RetestSessionCompactAiResponse = {
  success: boolean;
  message: string;
  ai_compacted?: boolean;
  memory_markdown?: string;
  brief?: string;
  warning?: string;
  confidence?: string;
  provider?: string;
  model?: string;
  blocked_by_ai_config?: boolean;
  blocked_stage?: string;
  blocked_title?: string;
  failure_stage?: string;
  model_call_started?: boolean;
};

type HybridAgentStatusResponse = {
  success: boolean;
  session_id?: string;
  auto_approve?: boolean;
  workspace_root?: string;
  agent_session?: {
    auto_approve?: boolean;
    workspace_root?: string;
    events?: unknown[];
    operations?: Record<string, HybridOperationRow>;
  };
  operations?: HybridOperationRow[];
  running_operations?: HybridOperationRow[];
};

type HybridAutoApprovalResponse = {
  success: boolean;
  session_id?: string;
  auto_approve?: boolean;
  workspace_root?: string;
  agent_session?: {
    auto_approve?: boolean;
    workspace_root?: string;
  };
};

type HybridOperationRow = {
  id?: string;
  operation_id?: string;
  approval_id?: string;
  tool_name?: string;
  status?: string;
  cwd?: string;
  risk?: string;
  detail?: string;
  result_preview?: string;
  raw_output?: string;
  error?: string;
  exit_code?: number | null;
  duration_ms?: number;
  artifact_ids?: string[];
  preview_artifact_id?: string;
  sandbox_summary?: string;
  started_at?: string;
  finished_at?: string;
  command?: string;
};

type RetestEventStreamInfoResponse = {
  success: boolean;
  message?: string;
  ws_url?: string;
};

type RetestTraceWebSocketMessage = {
  type?: string;
  session_id?: string;
  task_id?: string;
  event?: RetestSessionEvent;
};

type RetestListFilesResponse = {
  success: boolean;
  message: string;
  total?: number;
  source_files?: string[];
  completed_source_files?: string[];
  completed_source_file_names?: string[];
  completed_count_hint?: number;
  next_index_hint?: number;
  next_source_file?: string;
  next_source_file_name?: string;
  logs?: string[];
};

type RetestRunOneResponse = {
  success: boolean;
  message: string;
  stopped?: boolean;
  source_file?: string;
  manual_test_required?: boolean;
  blocked_by_ai_config?: boolean;
  blocked_stage?: string;
  blocked_title?: string;
  summary?: string;
  result_data?: Record<string, unknown>;
  trace_events?: RetestSessionEvent[];
  trace_event_count?: number;
  logs?: string[];
  log_count?: number;
};

type RetestRunOneStartResponse = RetestRunOneResponse & {
  task_id?: string;
  running?: boolean;
  done?: boolean;
  progress?: number;
};

type RetestRunOneStatusResponse = RetestRunOneResponse & {
  task_id: string;
  running: boolean;
  done: boolean;
  progress?: number;
  error?: string;
  result?: RetestRunOneResponse;
};

type RetestGenerateReportsResponse = {
  success: boolean;
  message: string;
  reports?: string[];
  screenshot_path?: string;
  failures?: Array<{ file: string; name?: string; reason: string }>;
  logs?: string[];
};

type RetestCompletionStatus = 'risk' | 'clean' | 'manual' | 'failed';

type RetestCompletionItem = {
  sourceFile: string;
  sourceFileName: string;
  status: RetestCompletionStatus;
  statusLabel: string;
  evidence: string;
  reason?: string;
  reportPaths: string[];
  tools: string[];
  riskCount: number;
  manualCount: number;
  failedCount: number;
};

type WorkbenchTab = 'conversation' | 'activity' | 'operations' | 'logs';
type ActivityFilter = 'all' | 'thought' | 'system' | 'tool' | 'error' | 'artifact';
type AgentMode = 'auto' | 'hybrid' | 'retest';
type RetestSlashCommandId = 'compact' | 'compact_all' | 'compact_help';

type RetestSlashCommand = {
  id: RetestSlashCommandId;
  command: string;
  title: string;
  description: string;
  completion: string;
};

type ConversationTool = {
  key: string;
  title: string;
  timestamp: string;
  sourceFile?: string;
  tone?: RetestSessionEvent['tone'];
  tool: RetestToolTrace;
  content?: string;
};

type RetestConversationTurn = {
  id: string;
  role: 'system' | 'user' | 'agent';
  title: string;
  timestamp: string;
  sourceFile?: string;
  items: RetestConversationItem[];
  contents: string[];
  thoughts: RetestSessionEvent[];
  tools: ConversationTool[];
  artifacts: RetestSessionEvent[];
  errors: RetestSessionEvent[];
};

type RetestConversationItem =
  | { kind: 'content'; key: string; content: string }
  | { kind: 'thought'; key: string; event: RetestSessionEvent }
  | { kind: 'tool'; key: string; tool: ConversationTool }
  | { kind: 'artifact'; key: string; event: RetestSessionEvent }
  | { kind: 'error'; key: string; event: RetestSessionEvent };

type RetestActivityEntry = {
  id: string;
  kind: ActivityFilter;
  eventType: RetestSessionEvent['type'];
  title: string;
  timestamp: string;
  sourceFile?: string;
  tone?: RetestSessionEvent['tone'];
  content?: string;
  tool?: RetestToolTrace;
  metadata?: Record<string, unknown>;
};

type RetestFrontendProgressEvidence = {
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

const ACTIVITY_FILTERS: Array<{ id: ActivityFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'thought', label: '思考' },
  { id: 'system', label: '系统' },
  { id: 'tool', label: '工具' },
  { id: 'error', label: '错误' },
  { id: 'artifact', label: '产物' },
];
const RETEST_SLASH_COMMANDS: RetestSlashCommand[] = [
  {
    id: 'compact',
    command: '/compact',
    title: '压缩当前会话',
    description: '先提取本地断点和证据，再调用模型生成可继续的语义记忆。',
    completion: '/compact',
  },
  {
    id: 'compact_all',
    command: '/compact all',
    title: '批量压缩会话',
    description: '批量瘦身所有本地会话，并对当前会话执行 AI 语义压缩。',
    completion: '/compact all',
  },
  {
    id: 'compact_help',
    command: '/compact help',
    title: '查看压缩说明',
    description: '说明 /compact 的本地事实压缩、AI 语义压缩和旧会话限制。',
    completion: '/compact help',
  },
];
const AUTO_START_MANUAL_SUPPRESS_MS = 1500;
const RETEST_COMPACTION_TIMEOUT_MS = 5 * 60 * 1000;
const AGENT_MODE_OPTIONS: Array<{ id: AgentMode; label: string; description: string }> = [
  { id: 'auto', label: '自动', description: '按会话内容自动选择 Hybrid 或复测 Agent' },
  { id: 'hybrid', label: '工程 Agent', description: '普通工程分析、读写审批和命令执行' },
  { id: 'retest', label: '复测 Agent', description: '固定走原复测队列和报告流程' },
];
const TERMINAL_OPERATION_STATUSES = new Set(['completed', 'failed', 'rejected', 'cancelled', 'stale']);

function formatSessionDate(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatBytes(bytes: number) {
  const value = Math.max(0, Number(bytes || 0));
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${Math.round(value)} B`;
}

function isSlashCommandInput(value: string) {
  return value.trimStart().startsWith('/');
}

function slashQuery(value: string) {
  return value.trimStart().toLowerCase();
}

function filterSlashCommands(value: string) {
  const query = slashQuery(value);
  if (!query.startsWith('/')) return [];
  return RETEST_SLASH_COMMANDS.filter((item) => (
    item.command.toLowerCase().startsWith(query)
    || item.title.toLowerCase().includes(query.slice(1))
    || item.description.toLowerCase().includes(query.slice(1))
  ));
}

function exactSlashCommand(value: string) {
  const query = slashQuery(value).replace(/\s+/g, ' ').trim();
  return RETEST_SLASH_COMMANDS.find((item) => item.command.toLowerCase() === query) ?? null;
}

function compactResultSummary(result: RetestSessionCompactResult) {
  return [
    `会话: ${result.sessionTitle || result.sessionId}`,
    `大小: ${formatBytes(result.beforeBytes)} -> ${formatBytes(result.afterBytes)}`,
    `事件: ${result.beforeEvents} -> ${result.afterEvents}`,
    `记忆: ${result.memoryUpdated ? '已重建' : '已保留/刷新'} (${formatBytes(result.memoryBytes)})`,
  ].join('\n');
}

function compactAllResultSummary(result: RetestSessionCompactAllResult) {
  return [
    `处理会话: ${result.sessionCount} 个，失败 ${result.failedCount} 个`,
    `总大小: ${formatBytes(result.beforeBytes)} -> ${formatBytes(result.afterBytes)}`,
    `当前会话: ${result.activeSessionId || '未选择'}`,
  ].join('\n');
}

function splitLogLines(log?: string) {
  return repairRetestText(log || '').split('\n').map((line) => line.trim()).filter(Boolean);
}

function getFileName(path: string) {
  const fixed = repairRetestText(path);
  return fixed.split(/[\\/]/).filter(Boolean).pop() || fixed;
}

function normalizePathForCompare(value?: string) {
  return repairRetestText(value || '').trim().replace(/[\\/]+$/, '').replace(/\\/g, '/').replace(/\/+/g, '/').toLowerCase();
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function errorMessage(error: unknown) {
  return repairRetestText(error instanceof Error ? error.message : String(error));
}

function operationId(operation: HybridOperationRow) {
  return String(operation.id || operation.operation_id || '').trim();
}

function normalizeHybridOperations(result: HybridAgentStatusResponse): HybridOperationRow[] {
  const byId = new Map<string, HybridOperationRow>();
  const push = (item: unknown) => {
    if (!item || typeof item !== 'object') return;
    const row = item as HybridOperationRow;
    const id = operationId(row);
    if (!id) return;
    const normalized = { ...row, id, operation_id: id };
    byId.set(id, normalized);
  };
  (result.operations || []).forEach(push);
  Object.values(result.agent_session?.operations || {}).forEach(push);
  (result.running_operations || []).forEach((item) => {
    const id = operationId(item);
    if (!id) return;
    const previous = byId.get(id) || { id, operation_id: id };
    byId.set(id, { ...previous, ...item, id, operation_id: id, status: item.status || previous.status || 'running' });
  });
  return Array.from(byId.values()).sort((a, b) => String(b.started_at || b.finished_at || '').localeCompare(String(a.started_at || a.finished_at || '')));
}

function operationIsRunning(operation: HybridOperationRow) {
  const status = String(operation.status || '').toLowerCase();
  return Boolean(status && !TERMINAL_OPERATION_STATUSES.has(status));
}

function isAiRuntimeFailureMessage(value: string) {
  const fixed = repairRetestText(value);
  const text = fixed.toLowerCase();
  return fixed.includes('模型调用失败')
    || fixed.includes('模型响应超时')
    || fixed.includes('模型并发')
    || fixed.includes('模型接口')
    || fixed.includes('模型额度')
    || fixed.includes('AI Agent')
    || text.includes('ai agent')
    || text.includes('llm')
    || text.includes('chat/completions')
    || text.includes('/v1/chat/completions')
    || text.includes('openai')
    || text.includes('openrouter')
    || text.includes('anthropic');
}

function clearRuntimeSessionIfMatches(sessionId: string) {
  const currentRuntimeSession = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
  if (currentRuntimeSession === sessionId) {
    window.sessionStorage.removeItem(RETEST_RUNTIME_SESSION_KEY);
  }
}

async function callBackendWithTimeout<T>(command: string, payload: Record<string, unknown>, timeoutMs = 30000, label = 'Agent 调用') {
  let timer: ReturnType<typeof window.setTimeout> | undefined;
  try {
    return await Promise.race([
      callBackend<T>(command, payload),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => reject(new Error(`${label}超过 ${Math.round(timeoutMs / 1000)} 秒未返回，请稍后再继续。`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
  }
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function joinLogs(logs?: string[]) {
  return (logs ?? []).map((line) => repairRetestText(line)).filter(Boolean).join('\n');
}

function formatPathList(paths?: string[]) {
  return (paths ?? []).map((path, index) => `${index + 1}. ${repairRetestText(path)}`).join('\n');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is Record<string, unknown> => Boolean(item)) : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => repairRetestText(String(item || '').trim())).filter(Boolean) : [];
}

function asFiniteNumber(value: unknown, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

const MODEL_REPRODUCED_VALUES = new Set(['reproduced', 'reproducible', 'unfixed', 'not_fixed', 'risk', 'vulnerable', '可复现', '未修复']);
const MODEL_CLEAN_VALUES = new Set(['not_reproduced', 'not reproducible', 'fixed', 'clean', 'pass', 'passed', '已修复', '复测通过', '不可复现']);

function normalizeModelVerdict(value: unknown): '' | 'reproduced' | 'not_reproduced' {
  const raw = repairRetestText(value || '').trim().toLowerCase();
  if (MODEL_REPRODUCED_VALUES.has(raw)) return 'reproduced';
  if (MODEL_CLEAN_VALUES.has(raw)) return 'not_reproduced';
  return '';
}

function modelVerdictFromResultData(resultData: Record<string, unknown> | null): '' | 'reproduced' | 'not_reproduced' {
  const aiJudgement = asRecord(resultData?.ai_judgement);
  const verdict = normalizeModelVerdict(
    aiJudgement?.verdict
      || aiJudgement?.reproduction_status
      || aiJudgement?.fix_status
      || resultData?.final_verdict,
  );
  if (verdict) return verdict;
  return typeof aiJudgement?.reproduced === 'boolean'
    ? (aiJudgement.reproduced ? 'reproduced' : 'not_reproduced')
    : '';
}

function isRiskVulnerability(value: unknown) {
  const item = asRecord(value);
  if (!item) return false;
  const severity = String(item.severity || '').toLowerCase();
  return ['low', 'medium', 'high', 'critical'].includes(severity) && !item.tool_unavailable && !item.tool_failed;
}

function completionStatusLabel(status: RetestCompletionStatus) {
  switch (status) {
    case 'risk': return '漏洞未修复/可复现';
    case 'clean': return '复测通过/未复现';
    case 'manual': return '复测通过/未复现';
    case 'failed': return '执行失败';
    default: return '复测通过/未复现';
  }
}

function extractCompletionEvidence(resultData: Record<string, unknown> | null) {
  const retestResults = asRecordArray(resultData?.retest_results);
  const riskLines: string[] = [];
  const infoLines: string[] = [];
  const tools = new Set<string>();

  retestResults.forEach((result) => {
    asStringArray(result.context_checks).forEach((tool) => tools.add(tool));
    asRecordArray(result.vulnerabilities).forEach((vuln) => {
      const type = repairRetestText(vuln.type || '证据');
      const severity = repairRetestText(vuln.severity || 'info');
      const detail = repairRetestText(vuln.detail || vuln.evidence || '').trim();
      if (vuln.tool_unavailable || type.includes('不可用')) return;
      const line = `[${severity}] ${type}${detail ? `：${detail}` : ''}`;
      if (isRiskVulnerability(vuln)) riskLines.push(line);
      else if (severity.toLowerCase() !== 'info' || type.includes('未复现') || type.includes('不可达') || type.includes('已受限')) infoLines.push(line);
    });
    if (!asRecordArray(result.vulnerabilities).length && result.note) {
      infoLines.push(repairRetestText(result.note));
    }
    const meta = asRecord(result.request_meta);
    if (meta?.status_code) {
      infoLines.push(`主请求：HTTP ${meta.status_code}${meta.final_url ? `，final=${repairRetestText(meta.final_url)}` : ''}`);
    } else if (meta?.error || result.target_unreachable) {
      infoLines.push(`目标不可达：${repairRetestText(meta?.error || result.error || '当前无法访问')}`);
    }
  });

  const scanResult = asRecord(resultData?.scan_result);
  const context = asRecord(scanResult?.retest_context);
  asStringArray(context?.agent_recommended_checks).forEach((tool) => tools.add(tool));

  return {
    evidence: repairRetestText((riskLines.length ? riskLines : infoLines).slice(0, 6).join('\n') || String(resultData?.reason || '暂无可展示证据')),
    tools: Array.from(tools).slice(0, 20),
  };
}

function buildCompletionItem(
  sourceFile: string,
  runResult?: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse,
  reportResult?: RetestGenerateReportsResponse,
  failureReason?: string,
): RetestCompletionItem {
  const resultData = asRecord(runResult?.result_data);
  const retestResults = asRecordArray(resultData?.retest_results);
  const urls = asStringArray(resultData?.urls);
  const manualCount = asFiniteNumber(resultData?.manual_count, 0);
  const failedCount = asFiniteNumber(resultData?.failed_count, retestResults.reduce((sum, item) => sum + asRecordArray(item.vulnerabilities).filter((vuln) => Boolean(vuln.tool_failed)).length, 0));
  const reportFailed = Boolean(reportResult && !reportResult.success);
  const runFailed = Boolean(failureReason || (runResult && !runResult.success));
  const extracted = extractCompletionEvidence(resultData);
  const aiJudgement = asRecord(resultData?.ai_judgement);
  const finalVerdict = modelVerdictFromResultData(resultData);
  const aiReproduced = finalVerdict === 'reproduced';
  const missingModelVerdict = !runFailed && !reportFailed && !finalVerdict;
  const riskCount = aiReproduced ? 1 : 0;

  let status: RetestCompletionStatus = 'clean';
  if (runFailed || reportFailed || missingModelVerdict) status = 'failed';
  else if (aiReproduced) status = 'risk';

  const reason = repairRetestText(failureReason
    || (reportFailed ? reportResult?.message : '')
    || String(aiJudgement?.reason || '')
    || String(resultData?.reason || '')
    || (missingModelVerdict ? '模型未给出 reproduced/not_reproduced 判定，未由工具结果兜底。' : '')
    || (!urls.length ? '未提取到可用 URL' : '')
    || (!retestResults.length ? '未形成可复测结果' : ''));

  return {
    sourceFile: repairRetestText(sourceFile),
    sourceFileName: getFileName(sourceFile),
    status,
    statusLabel: missingModelVerdict ? '模型未给出判定' : completionStatusLabel(status),
    evidence: extracted.evidence,
    reason,
    reportPaths: asStringArray(reportResult?.reports),
    tools: extracted.tools,
    riskCount,
    manualCount,
    failedCount: (runFailed || reportFailed || missingModelVerdict) ? Math.max(1, failedCount) : failedCount,
  };
}

function formatRetestResultMessage(
  fileLabel: string,
  runResult: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse,
  completionItem: RetestCompletionItem,
  reportResult?: RetestGenerateReportsResponse,
) {
  const resultData = asRecord(runResult.result_data);
  const aiJudgement = asRecord(resultData?.ai_judgement);
  const finalVerdict = modelVerdictFromResultData(resultData);
  const modelConclusion = repairRetestText(String(aiJudgement?.conclusion || '').trim());
  const urls = asStringArray(resultData?.urls);
  const lines = [
    `文件: ${repairRetestText(fileLabel)}`,
    `复测结果: ${completionItem.statusLabel}`,
    `模型判定: ${finalVerdict || '模型未给出判定'}${modelConclusion ? ` / ${modelConclusion}` : ''}`,
  ];
  if (aiJudgement?.reason || completionItem.reason) {
    lines.push(`理由: ${repairRetestText(String(aiJudgement?.reason || completionItem.reason))}`);
  }
  if (urls.length) {
    lines.push(`目标: ${urls.slice(0, 4).join('；')}`);
  }
  if (completionItem.tools.length) {
    lines.push(`工具: ${completionItem.tools.slice(0, 10).join(', ')}`);
  }
  if (completionItem.evidence) {
    lines.push(`关键证据:\n${completionItem.evidence.split('\n').slice(0, 6).join('\n')}`);
  }
  const reports = reportResult?.reports ?? completionItem.reportPaths;
  if (reports.length) {
    lines.push(`报告:\n${formatPathList(reports)}`);
  }
  return lines.join('\n');
}

function formatCompletionOverview(items: RetestCompletionItem[]) {
  if (!items.length) return '复测结论总览\n暂无文件级结论。';
  const order: RetestCompletionStatus[] = ['risk', 'clean', 'failed'];
  const lines = ['复测结论总览'];
  order.forEach((status) => {
    const group = items.filter((item) => item.status === status);
    lines.push('', `【${completionStatusLabel(status)}】${group.length} 项`);
    if (!group.length) {
      lines.push('- 无');
      return;
    }
    group.forEach((item) => {
      lines.push(`- ${item.sourceFileName}`);
      lines.push(`  证据: ${item.evidence.split('\n').slice(0, 3).join(' / ') || '暂无'}`);
      if (item.reason) lines.push(`  原因: ${item.reason}`);
      if (item.tools.length) lines.push(`  工具: ${item.tools.join(', ')}`);
      if (item.reportPaths.length) lines.push(`  报告: ${item.reportPaths.join('；')}`);
    });
  });
  return lines.join('\n');
}

function describeAiPause(blocked?: Pick<RetestRunOneResponse, 'message' | 'blocked_stage' | 'blocked_title'>) {
  const reason = repairRetestText(blocked?.message || 'Agent 会话待继续，请处理后继续。');
  const title = repairRetestText(blocked?.blocked_title || '');
  const stage = repairRetestText(blocked?.blocked_stage || '');
  if (title.includes('超时') || reason.includes('超时')) {
    return { title: '模型响应超时', status: `模型响应超时: ${reason}`, instruction: '网络或模型恢复后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  if (title.includes('限流') || reason.includes('HTTP 429') || reason.includes('限流') || reason.includes('并发')) {
    return { title: '模型并发/限流', status: `模型并发/限流: ${reason}`, instruction: '稍后在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  if (stage === 'config' || title.includes('配置') || reason.includes('配置') || reason.includes('未启用')) {
    return { title: '待配置 AI', status: `待配置 AI: ${reason}`, instruction: '配置完成后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  return { title: title || 'Agent 会话待继续', status: `${title || 'Agent 会话待继续'}: ${reason}`, instruction: '处理暂停原因后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
}

function asCompletionItems(value: unknown): RetestCompletionItem[] {
  return asRecordArray(value).map((item) => {
    const statusValue = String(item.status || 'clean');
    const status: RetestCompletionStatus = statusValue === 'risk' || statusValue === 'failed' || statusValue === 'manual' ? statusValue : 'clean';
    return {
      sourceFile: repairRetestText(String(item.sourceFile || '')),
      sourceFileName: repairRetestText(String(item.sourceFileName || getFileName(String(item.sourceFile || '')))),
      status,
      statusLabel: repairRetestText(String(item.statusLabel || completionStatusLabel(status))),
      evidence: repairRetestText(String(item.evidence || '')),
      reason: item.reason ? repairRetestText(String(item.reason)) : undefined,
      reportPaths: asStringArray(item.reportPaths),
      tools: asStringArray(item.tools),
      riskCount: asFiniteNumber(item.riskCount, 0),
      manualCount: asFiniteNumber(item.manualCount, 0),
      failedCount: asFiniteNumber(item.failedCount, 0),
    };
  }).filter((item) => item.sourceFile);
}

function getSessionSummary(session: RetestSessionDraft | null) {
  if (!session) return { filesText: '暂无', resultText: '暂无复测结果', logText: '暂无日志' };
  const logLines = splitLogLines(session.log);
  return {
    filesText: repairRetestText(session.targetDir || '未选择目录'),
    resultText: repairRetestText(session.resultText || '暂无复测结果'),
    logText: logLines.length ? logLines.slice(-120).join('\n') : '暂无日志',
  };
}

function truncateAgentContextText(value: unknown, limit = 1200) {
  const text = repairRetestText(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}\n...[已截断 ${text.length - limit} 字]`;
}

function compactAgentContextTool(tool?: RetestToolTrace) {
  if (!tool) return null;
  return {
    toolId: repairRetestText(tool.toolId || ''),
    label: repairRetestText(tool.label || ''),
    status: tool.status || '',
    target: truncateAgentContextText(tool.target, 220),
    argsPreview: truncateAgentContextText(tool.argsPreview, 300),
    resultPreview: truncateAgentContextText(tool.resultPreview || tool.failureReason || tool.evidence, 500),
    statusCode: tool.statusCode,
    finalUrl: truncateAgentContextText(tool.finalUrl, 300),
    rawCount: tool.rawCount,
    observationCount: tool.observationCount ?? tool.findingCount,
  };
}

function buildFrontendProgressEvidence(events: RetestSessionEvent[]): RetestFrontendProgressEvidence {
  const completedFileNames = new Set<string>();
  let latestSourceFileName = '';
  let hasCompletionSummary = false;

  events.forEach((event) => {
    const metadata = asMetadata(event);
    const eventSourceName = sourceLabel(event);
    if (eventSourceName) latestSourceFileName = eventSourceName;

    const completionItems = Array.isArray(metadata.completionItems) ? metadata.completionItems : [];
    completionItems.forEach((item) => {
      const record = asRecord(item);
      const name = repairRetestText(String(record?.sourceFileName || getFileName(String(record?.sourceFile || '')))).trim();
      if (name) completedFileNames.add(name);
    });

    const eventTitle = repairRetestText(event.title || '');
    const hasFileVerdict = eventTitle.includes('复测结果') || typeof metadata.fixStatus === 'string';
    if (hasFileVerdict && eventSourceName) completedFileNames.add(eventSourceName);
    if (metadata.phase === 'completion_summary' || eventTitle.includes('复测结论总览')) hasCompletionSummary = true;
  });

  return {
    targetDir: '',
    completedFileNames: Array.from(completedFileNames).slice(-200),
    latestSourceFileName,
    hasCompletionSummary,
    toolCalls: events.filter((event) => event.type === 'tool_call' || event.type === 'tool_result').length,
    errors: events.filter((event) => event.type === 'error').length,
  };
}

function mergeFrontendProgressEvidence(
  saved: RetestSessionDraft['progressEvidence'],
  current: RetestFrontendProgressEvidence,
): RetestFrontendProgressEvidence {
  const completed = new Map<string, string>();
  [...(saved?.completedFileNames ?? []), ...current.completedFileNames].forEach((name) => {
    const fileName = getFileName(String(name || '').trim());
    if (fileName) completed.set(fileName.toLowerCase(), fileName);
  });
  return {
    targetDir: current.targetDir || saved?.targetDir || '',
    completedFileNames: Array.from(completed.values()).slice(-1000),
    latestSourceFileName: current.latestSourceFileName || saved?.latestSourceFileName || '',
    hasCompletionSummary: Boolean(saved?.hasCompletionSummary || current.hasCompletionSummary),
    toolCalls: Math.max(Number(saved?.toolCalls ?? 0), current.toolCalls),
    errors: Math.max(Number(saved?.errors ?? 0), current.errors),
    completedCountHint: Math.max(0, completed.size, Number(saved?.completedCountHint ?? 0), Number(current.completedCountHint ?? 0)) || undefined,
    nextIndexHint: Math.max(0, completed.size, Number(saved?.nextIndexHint ?? 0), Number(current.nextIndexHint ?? 0)) || undefined,
    nextSourceFileName: current.nextSourceFileName || saved?.nextSourceFileName || '',
  };
}

function buildAgentFrontendContext(session: RetestSessionDraft) {
  const events = session.events ?? [];
  const targetDir = session.targetDir || session.resumeState?.targetDir || '';
  const eventEvidence = { ...buildFrontendProgressEvidence(events), targetDir };
  const savedTargetKey = normalizePathForCompare(session.progressEvidence?.targetDir);
  const currentTargetKey = normalizePathForCompare(targetDir);
  const savedEvidence = session.progressEvidence && (!savedTargetKey || !currentTargetKey || savedTargetKey === currentTargetKey)
    ? session.progressEvidence
    : undefined;
  const progressEvidence = { ...mergeFrontendProgressEvidence(savedEvidence, eventEvidence), targetDir };
  const recentEvents = events.slice(-20).map((event) => {
    const metadata = asMetadata(event);
    return {
      type: event.type,
      title: repairRetestText(event.title),
      role: typeof metadata.role === 'string' ? repairRetestText(metadata.role) : '',
      timestamp: event.timestamp,
      tone: event.tone,
      sourceFile: repairRetestText(event.sourceFile || ''),
      content: truncateAgentContextText(event.content, 600),
      metadata: {
        phase: typeof metadata.phase === 'string' ? metadata.phase : '',
        generateReports: metadata.generateReports === true,
        generate_reports: metadata.generate_reports === true,
      },
      tool: compactAgentContextTool(event.tool) || undefined,
    };
  });
  const conversation = buildConversationTurns(events).slice(-10).map((turn) => ({
    role: turn.role,
    title: repairRetestText(turn.title),
    timestamp: turn.timestamp,
    sourceFile: repairRetestText(turn.sourceFile || ''),
    content: truncateAgentContextText(turn.contents.join('\n'), 1600),
    tools: turn.tools.slice(-4).map((item) => ({
      title: repairRetestText(item.title),
      content: truncateAgentContextText(item.content, 500),
      tool: compactAgentContextTool(item.tool),
    })),
    artifacts: turn.artifacts.slice(-3).map((item) => truncateAgentContextText(`${item.title}: ${item.content || ''}`, 800)),
    errors: turn.errors.slice(-3).map((item) => truncateAgentContextText(`${item.title}: ${item.content || ''}`, 700)),
  }));
  return {
    session: {
      sessionId: session.sessionId,
      title: repairRetestText(session.sessionTitle),
      targetDir: repairRetestText(targetDir),
      status: repairRetestText(session.status || ''),
      progress: session.progress ?? 0,
      isRunning: Boolean(session.isRunning),
      generateReports: Boolean(session.generateReports),
      resumeState: session.resumeState ?? null,
      lastReportPath: repairRetestText(session.lastReportPath || ''),
      resultText: truncateAgentContextText(session.resultText, 2500),
      logTail: splitLogLines(session.log).slice(-30).map((line) => truncateAgentContextText(line, 500)),
      latestResultDataText: session.latestResultData ? truncateAgentContextText(JSON.stringify(session.latestResultData), 1800) : '',
      memoryMarkdown: truncateAgentContextText(session.memoryMarkdown, 12000),
    },
    conversation,
    recentEvents,
    progressEvidence,
  };
}

function agentWorkspaceTargetDir(session: RetestSessionDraft | null | undefined) {
  return repairRetestText(
    session?.targetDir
    || session?.resumeState?.targetDir
    || session?.progressEvidence?.targetDir
    || '',
  ).trim();
}

function buildSessionCompactAiPayload(session: RetestSessionDraft, result: RetestSessionCompactResult) {
  return {
    session_id: session.sessionId,
    local_memory: truncateAgentContextText(session.memoryMarkdown, 16000),
    frontend_context: buildAgentFrontendContext(session),
    compact_stats: result,
    recent_events: (session.events ?? []).slice(-80).map((event) => ({
      type: event.type,
      title: repairRetestText(event.title),
      timestamp: event.timestamp,
      tone: event.tone,
      sourceFile: repairRetestText(event.sourceFile || ''),
      content: truncateAgentContextText(event.content, 900),
      metadata: event.metadata ? {
        phase: typeof event.metadata.phase === 'string' ? repairRetestText(event.metadata.phase) : event.metadata.phase,
        role: typeof event.metadata.role === 'string' ? repairRetestText(event.metadata.role) : event.metadata.role,
        generateReports: event.metadata.generateReports,
        generate_reports: event.metadata.generate_reports,
        sourceFileName: typeof event.metadata.sourceFileName === 'string' ? repairRetestText(event.metadata.sourceFileName) : event.metadata.sourceFileName,
        fixStatus: typeof event.metadata.fixStatus === 'string' ? repairRetestText(event.metadata.fixStatus) : event.metadata.fixStatus,
        progressEvidence: event.metadata.progressEvidence,
        resumeState: event.metadata.resumeState,
      } : undefined,
      tool: event.tool ? compactAgentContextTool(event.tool) : undefined,
    })),
    logs: splitLogLines(session.log).slice(-80).map((line) => truncateAgentContextText(line, 800)),
  };
}

function resumeBannerCopy(session: RetestSessionDraft | null) {
  const state = session?.resumeState;
  const reason = repairRetestText(state?.blockedReason || session?.status || '处理暂停原因后可从当前上下文继续。');
  const title = repairRetestText(state?.blockedTitle || '');
  const stage = repairRetestText(state?.blockedStage || '');
  const reportSuffix = sessionWantsGeneratedReports(session, state) ? ' 本轮会继续生成报告。' : '';
  const completedFileEvidence = session?.progressEvidence?.completedFileNames?.length ?? 0;
  const evidenceCount = Math.max(
    completedFileEvidence,
    Number(session?.progressEvidence?.completedCountHint ?? 0),
    Number(session?.progressEvidence?.nextIndexHint ?? 0),
  );
  if (!state?.canContinue && evidenceCount > completedFileEvidence) {
    return { title: '可从压缩记忆恢复', reason: `已从 AI 语义压缩记忆识别到 ${evidenceCount} 份已完成/断点证据，继续时会先恢复进度再执行。${reportSuffix}` };
  }
  if (!state?.canContinue && (session?.progressEvidence?.completedFileNames?.length ?? 0) > 0) {
    return { title: '可从旧会话上下文恢复', reason: `已保存 ${session?.progressEvidence?.completedFileNames.length ?? 0} 个已完成文件证据，继续时会先恢复进度再执行。${reportSuffix}` };
  }
  const reasonWithReportIntent = reportSuffix && !reason.includes('生成报告') ? `${reason}${reportSuffix}` : reason;
  if (title.includes('超时') || reason.includes('超时')) {
    return { title: '模型响应超时，待继续', reason: reasonWithReportIntent };
  }
  if (title.includes('限流') || reason.includes('HTTP 429') || reason.includes('限流') || reason.includes('并发')) {
    return { title: '模型并发/限流，待继续', reason: reasonWithReportIntent };
  }
  if (stage === 'config' || title.includes('配置') || reason.includes('配置') || reason.includes('未启用')) {
    return { title: '待配置 AI 后继续', reason: reasonWithReportIntent };
  }
  return { title: title ? `${title}，待继续` : 'Agent 会话待继续', reason: reasonWithReportIntent };
}

function resumeButtonLabel(_session: RetestSessionDraft | null) {
  return '继续';
}

function isContinueInstruction(message: string) {
  const text = repairRetestText(message).trim().toLowerCase();
  return text === '继续' || text === '继续测试' || text === '继续执行' || text === 'resume' || text === 'continue'
    || text.includes('继续复测') || text.includes('从断点继续');
}

function hasContinueCue(session: RetestSessionDraft | null) {
  if (!session) return false;
  if (session.resumeState?.canContinue) return true;
  const targetDir = repairRetestText(session.resumeState?.targetDir || session.targetDir || '').trim();
  if (!targetDir) return false;
  const evidenceCount = Math.max(
    session.progressEvidence?.completedFileNames?.length ?? 0,
    Number(session.progressEvidence?.completedCountHint ?? 0),
    Number(session.progressEvidence?.nextIndexHint ?? 0),
  );
  if (!session.isRunning && evidenceCount > 0 && Number(session.progress ?? 0) < 100) return true;
  if (!session.isRunning && Boolean(session.memoryMarkdown?.trim()) && Number(session.progress ?? 0) < 100) return true;
  if (!session.isRunning && (session.progressEvidence?.completedFileNames?.length ?? 0) > 0 && Number(session.progress ?? 0) < 100) return true;
  const text = repairRetestText(`${session.status || ''}\n${session.resumeState?.blockedReason || ''}\n${session.log || ''}`).toLowerCase();
  return text.includes('可继续')
    || text.includes('待继续')
    || text.includes('已停止')
    || text.includes('已暂停')
    || text.includes('stop')
    || text.includes('pause')
    || text.includes('resume');
}

function sessionWantsGeneratedReports(session: RetestSessionDraft | null, resumeState?: RetestResumeState | null) {
  if (!session) return false;
  if (session.generateReports) return true;
  if (resumeState?.generateReports || session.resumeState?.generateReports) return true;
  if ((resumeState?.reports?.length ?? 0) > 0 || (session.resumeState?.reports?.length ?? 0) > 0) return true;
  if (session.lastReportPath) {
    const reportKey = normalizePathForCompare(session.lastReportPath);
    const targetKey = normalizePathForCompare(session.targetDir || session.resumeState?.targetDir || '');
    if (reportKey && reportKey !== targetKey) return true;
  }
  const text = repairRetestText([
    session.status,
    session.resultText,
    session.log,
    session.memoryMarkdown,
    ...(session.events ?? []).slice(-80).flatMap((event) => [
      event.title,
      event.content,
      event.tool?.resultPreview,
      event.tool?.failureReason,
      typeof event.metadata?.generateReports === 'boolean' ? String(event.metadata.generateReports) : '',
      typeof event.metadata?.generate_reports === 'boolean' ? String(event.metadata.generate_reports) : '',
    ]),
  ].filter(Boolean).join('\n'));
  if ((session.events ?? []).some((event) => event.metadata?.generateReports === true || event.metadata?.generate_reports === true)) return true;
  return text.includes('一键复测')
    || text.includes('继续测试并生成报告')
    || text.includes('生成报告:')
    || text.includes('生成报告：')
    || text.includes('报告已生成')
    || text.includes('报告生成完成');
}

function isRetestIntent(message: string) {
  const text = repairRetestText(message).toLowerCase();
  return text.includes('复测')
    || text.includes('通报')
    || text.includes('报告')
    || text.includes('漏洞')
    || text.includes('retest')
    || text.includes('notice')
    || text.includes('report');
}

function shouldUseHybridAgentMessage(message: string, session: RetestSessionDraft | null) {
  if (!session) return true;
  if (isContinueInstruction(message) || hasContinueCue(session)) return false;
  if (sessionWantsGeneratedReports(session, session.resumeState)) return false;
  if (repairRetestText(session.targetDir || session.resumeState?.targetDir || '').trim()) return false;
  return !isRetestIntent(message);
}

function completedFileNameSetForResume(
  session: RetestSessionDraft | null,
  completionItems: RetestCompletionItem[] = [],
) {
  const completed = new Set<string>();
  const addName = (value?: string) => {
    const fileName = getFileName(String(value || '').trim()).toLowerCase();
    if (fileName && !fileName.includes('复测报告') && !fileName.includes('retest report')) completed.add(fileName);
  };
  session?.progressEvidence?.completedFileNames?.forEach(addName);
  session?.resumeState?.completionItems?.forEach((item) => {
    if (!item || typeof item !== 'object') return;
    addName(String(item.sourceFileName || item.sourceFile || ''));
  });
  completionItems.forEach((item) => addName(item.sourceFileName || item.sourceFile));
  return completed;
}

function mergeCompletedFileNamesForResume(target: Set<string>, names?: string[]) {
  (names ?? []).forEach((name) => {
    const fileName = getFileName(String(name || '').trim()).toLowerCase();
    if (fileName && !fileName.includes('复测报告') && !fileName.includes('retest report')) target.add(fileName);
  });
}

function advanceIndexPastCompletedFiles(sourceFiles: string[], startIndex: number, completed: Set<string>) {
  let index = Math.max(0, Math.min(sourceFiles.length, startIndex));
  while (index < sourceFiles.length && completed.has(getFileName(sourceFiles[index]).toLowerCase())) {
    index += 1;
  }
  return index;
}

function resumeStartIndexFromEvidence(session: RetestSessionDraft | null, sourceFiles: string[], fallbackIndex = 0) {
  const evidence = session?.progressEvidence;
  const nextName = getFileName(evidence?.nextSourceFileName || '');
  if (nextName) {
    const namedIndex = sourceFiles.findIndex((item) => getFileName(item).toLowerCase() === nextName.toLowerCase());
    if (namedIndex >= 0) return Math.max(fallbackIndex, namedIndex);
  }
  const hinted = Math.max(
    0,
    Number(evidence?.nextIndexHint ?? 0),
    Number(evidence?.completedCountHint ?? 0),
    evidence?.completedFileNames?.length ?? 0,
    session?.resumeState?.completionItems?.length ?? 0,
    fallbackIndex,
  );
  return Math.max(0, Math.min(sourceFiles.length, hinted));
}

function asMetadata(event: RetestSessionEvent) {
  return event.metadata && typeof event.metadata === 'object' ? event.metadata : {};
}

function metadataString(event: RetestSessionEvent, key: string) {
  const value = asMetadata(event)[key];
  return typeof value === 'string' ? repairRetestText(value) : '';
}

function eventRole(event: RetestSessionEvent): RetestConversationTurn['role'] | '' {
  const role = metadataString(event, 'role');
  if (role === 'user' || role === 'system' || role === 'agent') return role;
  return '';
}

function sourceLabel(event: RetestSessionEvent) {
  return metadataString(event, 'sourceFileName') || getFileName(repairRetestText(event.sourceFile || ''));
}

function roundKey(event: RetestSessionEvent) {
  return metadataString(event, 'roundId') || metadataString(event, 'turnId') || sourceLabel(event) || repairRetestText(event.sourceFile || '') || 'session';
}

function explicitRoundKey(event: RetestSessionEvent) {
  return metadataString(event, 'roundId') || metadataString(event, 'turnId');
}

function conversationTurnKey(event: RetestSessionEvent) {
  return metadataString(event, 'turnId') || roundKey(event);
}

function modelOutputMergeKey(event: RetestSessionEvent) {
  const metadata = asMetadata(event);
  if (!metadata.modelOutput) return '';
  const explicitKey = metadata.streamKey;
  if (typeof explicitKey === 'string' && explicitKey.trim()) return explicitKey.trim();
  const phase = typeof metadata.phase === 'string' ? repairRetestText(metadata.phase) : '';
  return ['model-output', roundKey(event), repairRetestText(event.sourceFile || ''), phase].join(':');
}

function toolMergeKey(event: RetestSessionEvent) {
  const metadata = asMetadata(event);
  const toolCallId = metadata.toolCallId || metadata.tool_call_id;
  if (typeof toolCallId === 'string' && toolCallId.trim()) return `tool-call:${toolCallId.trim()}`;
  const tool = event.tool;
  return [
    roundKey(event),
    repairRetestText(tool?.toolId || event.title || ''),
    repairRetestText(tool?.target || ''),
    sourceLabel(event),
  ].join('|');
}

function normalizeToolTarget(value?: string) {
  return normalizePathForCompare(value);
}

function toolIdentityFromEvent(event: RetestSessionEvent) {
  return repairRetestText(event.tool?.toolId || event.title || event.tool?.label || '');
}

function toolIdentityFromItem(item: ConversationTool | RetestActivityEntry) {
  return repairRetestText(item.tool?.toolId || item.title || item.tool?.label || '');
}

function defaultToolStatus(event: RetestSessionEvent): RetestToolTrace['status'] | undefined {
  if (event.tool?.status) return event.tool.status;
  if (event.type === 'tool_result') return 'completed';
  if (event.type === 'tool_call') return 'running';
  return undefined;
}

function isCompactionTool(tool?: RetestToolTrace, title = '') {
  return tool?.toolId === 'doc.retest.session.compact'
    || tool?.label?.includes('AI 语义压缩')
    || title.includes('AI 语义压缩');
}

function mergeToolTrace(existing: RetestToolTrace | undefined, event: RetestSessionEvent): RetestToolTrace {
  return {
    ...(existing ?? {}),
    ...(event.tool ?? {}),
    status: defaultToolStatus(event) ?? existing?.status,
  };
}

function resolveConversationToolKey(toolMap: Map<string, ConversationTool>, event: RetestSessionEvent, exactKey: string) {
  if (toolMap.has(exactKey) || event.type !== 'tool_result') return exactKey;
  const eventIdentity = toolIdentityFromEvent(event);
  if (!eventIdentity) return exactKey;
  const eventTarget = normalizeToolTarget(event.tool?.target);
  const candidates = Array.from(toolMap.entries()).filter(([, item]) => {
    if (toolIdentityFromItem(item) !== eventIdentity) return false;
    if (item.tool.status && item.tool.status !== 'running' && item.tool.status !== 'skipped') return false;
    const itemTarget = normalizeToolTarget(item.tool.target);
    return !eventTarget || !itemTarget || eventTarget === itemTarget;
  });
  return candidates.length === 1 ? candidates[0][0] : exactKey;
}

function resolveActivityToolIndex(entries: RetestActivityEntry[], toolIndexes: Map<string, number>, event: RetestSessionEvent, exactKey: string) {
  const exactIndex = toolIndexes.get(exactKey);
  if (exactIndex !== undefined || event.type !== 'tool_result') return exactIndex;
  const eventIdentity = toolIdentityFromEvent(event);
  if (!eventIdentity) return undefined;
  const eventTarget = normalizeToolTarget(event.tool?.target);
  const candidates = entries
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => {
      if (entry.kind !== 'tool') return false;
      if (toolIdentityFromItem(entry) !== eventIdentity) return false;
      if (entry.tool?.status && entry.tool.status !== 'running' && entry.tool.status !== 'skipped') return false;
      const entryTarget = normalizeToolTarget(entry.tool?.target);
      return !eventTarget || !entryTarget || eventTarget === entryTarget;
    });
  return candidates.length === 1 ? candidates[0].index : undefined;
}

function statusText(status?: RetestToolTrace['status'], tool?: RetestToolTrace) {
  if (isCompactionTool(tool)) {
    if (status === 'completed') return '完成';
    if (status === 'failed' || status === 'skipped' || status === 'incomplete') return '未完成';
    if (status === 'cancelled') return '已取消';
    if (status === 'blocked') return '等待中';
    return '运行中';
  }
  if (status === 'completed') return '完成';
  if (status === 'failed') return '失败';
  if (status === 'skipped') return '跳过';
  if (status === 'cancelled') return '已取消';
  if (status === 'blocked') return '待继续';
  if (status === 'incomplete') return '未完成';
  return '运行中';
}

function toolRunPrefix(status?: RetestToolTrace['status'], tool?: RetestToolTrace, title = '') {
  if (isCompactionTool(tool, title)) {
    if (status === 'completed') return '已运行';
    if (status === 'failed' || status === 'skipped' || status === 'incomplete') return 'AI 语义压缩未完成';
    if (status === 'cancelled') return 'AI 语义压缩已取消';
    if (status === 'blocked') return '等待 AI 语义压缩';
    return '正在自动压缩上下文';
  }
  if (status === 'failed') return '运行失败';
  if (status === 'cancelled') return '已取消';
  if (status === 'blocked') return '待继续';
  if (status === 'skipped') return '已跳过';
  if (status === 'running' || !status) return '正在运行';
  return '已运行';
}

function toolObservationCount(tool: RetestToolTrace) {
  return Math.max(0, tool.observationCount ?? tool.findingCount ?? 0);
}

function sessionStateLabel(session: RetestSessionDraft) {
  const status = repairRetestText(session.status || '');
  if (session.isRunning || status.includes('正在') || status.includes('压缩中') || status.includes('自动压缩') || status.includes('运行中')) return status.includes('压缩') ? '压缩中' : '处理中';
  if (session.resumeState?.canContinue) {
    const resumeStatus = repairRetestText(session.status || session.resumeState.blockedReason || '');
    if (resumeStatus.includes('停止')) return '已停止';
    return '待继续';
  }
  if (status.includes('失败') || status.includes('未完成')) return '待处理';
  if (status.includes('完成')) return '完成';
  if (status.includes('停止')) return '已停止';
  return '空闲';
}

function compactToolMeta(tool: RetestToolTrace) {
  const observationCount = toolObservationCount(tool);
  const parts = [
    statusText(tool.status, tool),
    typeof tool.durationMs === 'number' ? `${tool.durationMs}ms` : '',
    tool.statusCode ? `HTTP ${tool.statusCode}` : '',
    observationCount > 0 ? `观察 ${observationCount}` : '',
    typeof tool.failedCount === 'number' && tool.failedCount > 0 ? `失败 ${tool.failedCount}` : '',
    typeof tool.rawCount === 'number' ? `输出 ${tool.rawCount}` : '',
  ].filter(Boolean);
  return parts.join(' · ');
}

function prettyJson(value?: Record<string, unknown>) {
  if (!value || !Object.keys(value).length) return '';
  try {
    return repairRetestText(JSON.stringify(value, null, 2));
  } catch {
    return repairRetestText(String(value));
  }
}

function eventKind(event: RetestSessionEvent): ActivityFilter {
  if (event.type === 'thought_summary') return 'thought';
  if (event.type === 'tool_call' || event.type === 'tool_result') return 'tool';
  if (event.type === 'error') return 'error';
  if (event.type === 'artifact') return 'artifact';
  return 'system';
}

function eventBadge(eventType: RetestSessionEvent['type']) {
  switch (eventType) {
    case 'thought_summary': return '思考';
    case 'tool_call': return '调用';
    case 'tool_result': return '结果';
    case 'artifact': return '产物';
    case 'approval_request': return '审批';
    case 'error': return '错误';
    case 'chat': return '对话';
    default: return '状态';
  }
}

function buildConversationTurns(events: RetestSessionEvent[]): RetestConversationTurn[] {
  const turns: RetestConversationTurn[] = [];
  const grouped = new Map<string, RetestConversationTurn>();
  const toolMaps = new Map<string, Map<string, ConversationTool>>();

  const getGroupedTurn = (event: RetestSessionEvent) => {
    const key = conversationTurnKey(event);
    let turn = grouped.get(key);
    if (!turn) {
      turn = {
        id: `round-${key}`,
        role: 'agent',
        title: sourceLabel(event) ? `复测执行 / ${sourceLabel(event)}` : 'Agent 执行',
        timestamp: event.timestamp,
        sourceFile: sourceLabel(event),
        items: [],
        contents: [],
        thoughts: [],
        tools: [],
        artifacts: [],
        errors: [],
      };
      grouped.set(key, turn);
      toolMaps.set(key, new Map());
      turns.push(turn);
    }
    return turn;
  };

  events.forEach((event) => {
    const role = eventRole(event);
    const eventTitle = repairRetestText(event.title || '');
    const eventContent = repairRetestText(event.content || '');
    const groupedChatKey = explicitRoundKey(event);
    if (event.type === 'chat' && role !== 'user' && role !== 'system' && groupedChatKey) {
      const turn = getGroupedTurn(event);
      turn.role = 'agent';
      if (turn.title === 'Agent 执行' && eventTitle) turn.title = eventTitle;
      if (event.timestamp) turn.timestamp = event.timestamp;
      if (sourceLabel(event)) turn.sourceFile = sourceLabel(event);
      if (eventContent) {
        turn.contents.push(eventContent);
        turn.items.push({ kind: 'content', key: event.id, content: eventContent });
      }
      return;
    }

    if (event.type === 'chat' || role) {
      turns.push({
        id: event.id,
        role: role || 'agent',
        title: eventTitle || (role === 'user' ? '你' : 'Agent'),
        timestamp: event.timestamp,
        items: eventContent ? [{ kind: 'content', key: event.id, content: eventContent }] : [],
        contents: eventContent ? [eventContent] : [],
        thoughts: [],
        tools: [],
        artifacts: [],
        errors: event.type === 'error' ? [event] : [],
      });
      return;
    }

    const turn = getGroupedTurn(event);
    if (event.timestamp) turn.timestamp = event.timestamp;
    if (sourceLabel(event)) turn.sourceFile = sourceLabel(event);

    if (event.type === 'thought_summary') {
      const mergeKey = modelOutputMergeKey(event);
      if (mergeKey) {
        const existingIndex = turn.thoughts.findIndex((thought) => modelOutputMergeKey(thought) === mergeKey);
        if (existingIndex >= 0) {
          turn.thoughts[existingIndex] = event;
          const itemIndex = turn.items.findIndex((item) => item.kind === 'thought' && modelOutputMergeKey(item.event) === mergeKey);
          if (itemIndex >= 0) turn.items[itemIndex] = { kind: 'thought', key: turn.items[itemIndex].key, event };
          return;
        }
      }
      turn.thoughts.push(event);
      turn.items.push({ kind: 'thought', key: event.id, event });
      return;
    }
    if (event.type === 'tool_call' || event.type === 'tool_result') {
      const exactKey = toolMergeKey(event);
      const toolMap = toolMaps.get(conversationTurnKey(event));
      if (!toolMap) return;
      const key = resolveConversationToolKey(toolMap, event, exactKey);
      const existing = toolMap.get(key);
      const nextTool = mergeToolTrace(existing?.tool, event);
      const item: ConversationTool = {
        key,
        title: repairRetestText(event.tool?.label || eventTitle || event.tool?.toolId || '工具调用'),
        timestamp: event.timestamp,
        sourceFile: sourceLabel(event),
        tone: event.tone || existing?.tone,
        tool: nextTool,
        content: repairRetestText(event.tool?.resultPreview || eventContent || existing?.content || ''),
      };
      if (!existing) {
        turn.tools.push(item);
        turn.items.push({ kind: 'tool', key, tool: item });
      }
      toolMap.set(key, item);
      const index = turn.tools.findIndex((tool) => tool.key === key);
      if (index >= 0) turn.tools[index] = item;
      const itemIndex = turn.items.findIndex((entry) => entry.kind === 'tool' && entry.key === key);
      if (itemIndex >= 0) turn.items[itemIndex] = { kind: 'tool', key, tool: item };
      return;
    }
    if (event.type === 'artifact') {
      turn.artifacts.push(event);
      turn.items.push({ kind: 'artifact', key: event.id, event });
      return;
    }
    if (event.type === 'error') {
      turn.errors.push(event);
      turn.items.push({ kind: 'error', key: event.id, event });
      return;
    }
    if (eventContent) {
      const content = `${eventTitle ? `${eventTitle}: ` : ''}${eventContent}`;
      turn.contents.push(content);
      turn.items.push({ kind: 'content', key: event.id, content });
    } else if (eventTitle) {
      turn.contents.push(eventTitle);
      turn.items.push({ kind: 'content', key: event.id, content: eventTitle });
    }
  });

  return turns;
}

function buildActivityEntries(events: RetestSessionEvent[]): RetestActivityEntry[] {
  const entries: RetestActivityEntry[] = [];
  const toolIndexes = new Map<string, number>();

  events.forEach((event) => {
    const kind = eventKind(event);
    const eventTitle = repairRetestText(event.title || '');
    const eventContent = repairRetestText(event.content || '');
    if (kind === 'tool') {
      const key = toolMergeKey(event);
      const existingIndex = resolveActivityToolIndex(entries, toolIndexes, event, key);
      const entry: RetestActivityEntry = {
        id: key,
        kind: 'tool',
        eventType: event.type,
        title: repairRetestText(event.tool?.label || eventTitle || event.tool?.toolId || '工具调用'),
        timestamp: event.timestamp,
        sourceFile: sourceLabel(event),
        tone: event.tone,
        content: repairRetestText(event.tool?.resultPreview || eventContent || ''),
        tool: mergeToolTrace(existingIndex !== undefined ? entries[existingIndex]?.tool : undefined, event),
        metadata: asMetadata(event),
      };
      if (existingIndex === undefined) {
        toolIndexes.set(key, entries.length);
        entries.push(entry);
      } else {
        const previousKey = entries[existingIndex]?.id;
        entries[existingIndex] = { ...entries[existingIndex], ...entry, id: previousKey || entry.id };
        if (previousKey && previousKey !== key) toolIndexes.set(key, existingIndex);
      }
      return;
    }
    if (kind === 'thought') {
      const mergeKey = modelOutputMergeKey(event);
      if (mergeKey) {
        const existingIndex = entries.findIndex((entry) => entry.kind === 'thought' && typeof entry.metadata?.streamKey === 'string' && entry.metadata.streamKey === mergeKey);
        if (existingIndex >= 0) {
          entries[existingIndex] = {
            id: entries[existingIndex].id,
            kind,
            eventType: event.type,
            title: eventTitle,
            timestamp: event.timestamp,
            sourceFile: sourceLabel(event),
            tone: event.tone,
            content: eventContent,
            metadata: { ...asMetadata(event), streamKey: mergeKey },
          };
          return;
        }
        const metadata = { ...asMetadata(event), streamKey: mergeKey };
        entries.push({
          id: event.id,
          kind,
          eventType: event.type,
          title: eventTitle,
          timestamp: event.timestamp,
          sourceFile: sourceLabel(event),
          tone: event.tone,
          content: eventContent,
          metadata,
        });
        return;
      }
    }
    entries.push({
      id: event.id,
      kind,
      eventType: event.type,
      title: eventTitle,
      timestamp: event.timestamp,
      sourceFile: sourceLabel(event),
      tone: event.tone,
      content: eventContent,
      metadata: asMetadata(event),
    });
  });

  return entries;
}

function ChatText({ content }: { content: string }) {
  return <div className="retest-chat-text">{repairRetestText(content)}</div>;
}

const markdownComponents: Components = {
  p: ({ node: _node, ...props }) => <p className="retest-md-p" {...props} />,
  h1: ({ node: _node, ...props }) => <h1 className="retest-md-h retest-md-h1" {...props} />,
  h2: ({ node: _node, ...props }) => <h2 className="retest-md-h retest-md-h2" {...props} />,
  h3: ({ node: _node, ...props }) => <h3 className="retest-md-h retest-md-h3" {...props} />,
  h4: ({ node: _node, ...props }) => <h4 className="retest-md-h retest-md-h4" {...props} />,
  h5: ({ node: _node, ...props }) => <h5 className="retest-md-h retest-md-h5" {...props} />,
  h6: ({ node: _node, ...props }) => <h6 className="retest-md-h retest-md-h6" {...props} />,
  ul: ({ node: _node, className, ...props }) => (
    <ul className={`retest-md-list${className ? ` ${className}` : ''}`} {...props} />
  ),
  ol: ({ node: _node, className, ...props }) => (
    <ol className={`retest-md-list${className ? ` ${className}` : ''}`} {...props} />
  ),
  li: ({ node: _node, className, ...props }) => (
    <li className={className ? `retest-md-li ${className}` : 'retest-md-li'} {...props} />
  ),
  blockquote: ({ node: _node, ...props }) => <blockquote className="retest-md-quote" {...props} />,
  hr: ({ node: _node, ...props }) => <hr className="retest-md-hr" {...props} />,
  pre: ({ node: _node, ...props }) => <pre className="retest-md-pre" {...props} />,
  code: ({ node: _node, className, ...props }) => (
    <code className={`retest-md-code${className ? ` ${className}` : ''}`} {...props} />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="retest-md-table-wrap">
      <table className="retest-md-table" {...props} />
    </div>
  ),
  thead: ({ node: _node, ...props }) => <thead {...props} />,
  tbody: ({ node: _node, ...props }) => <tbody {...props} />,
  tr: ({ node: _node, ...props }) => <tr {...props} />,
  th: ({ node: _node, style, ...props }) => <th style={style} {...props} />,
  td: ({ node: _node, style, ...props }) => <td style={style} {...props} />,
  a: ({ node: _node, href, ...props }) => (
    <a href={href} target="_blank" rel="noreferrer noopener" {...props} />
  ),
  img: ({ node: _node, ...props }) => <img className="retest-md-image" loading="lazy" {...props} />,
  input: ({ node: _node, ...props }) => <input className="retest-md-task-box" readOnly tabIndex={-1} {...props} />,
};

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {repairRetestText(content)}
    </ReactMarkdown>
  );
}

function Markdown({ content }: { content: string }) {
  const text = repairRetestText(content || '').trim();
  if (!text) return null;
  return <div className="retest-chat-text retest-markdown"><MarkdownContent content={text} /></div>;
}

// 模型思考：默认折叠的小字块，summary 显示一行预览，可展开看全文。
function ThoughtBlock({ event }: { event: RetestSessionEvent }) {
  const text = repairRetestText(event.content || '').trim();
  const preview = text.replace(/\s+/g, ' ').slice(0, 56);
  return (
    <details className="retest-thought-fold">
      <summary>
        <span className="retest-thought-fold-icon" />
        <span className="retest-thought-fold-label">模型思考</span>
        <span className="retest-thought-fold-preview">{preview || '展开查看思考过程'}{text.length > 56 ? '…' : ''}</span>
        {event.timestamp ? <span className="retest-thought-fold-time">{event.timestamp}</span> : null}
      </summary>
      <div className="retest-thought-fold-body retest-markdown"><MarkdownContent content={text || '暂无思考内容。'} /></div>
    </details>
  );
}

// ---- 线性时间线：直接消费 store 已去重/排序的事件，严格按时间顺序逐条平铺 ----
// 不再做 turn 聚合或 ProcessGroup 折叠，确保像 Claude / Codex / Cursor 那样按序输出。
type TimelineRow =
  | { kind: 'message'; key: string; role: 'user' | 'agent' | 'system'; event: RetestSessionEvent; live: boolean }
  | { kind: 'thought'; key: string; event: RetestSessionEvent }
  | { kind: 'tool'; key: string; tool: ConversationTool }
  | { kind: 'artifact'; key: string; event: RetestSessionEvent }
  | { kind: 'error'; key: string; event: RetestSessionEvent }
  | { kind: 'status'; key: string; event: RetestSessionEvent };

function frontStreamKey(event: RetestSessionEvent): string {
  const k = asMetadata(event).streamKey;
  return typeof k === 'string' && k.trim() ? repairRetestText(k).trim() : '';
}

function buildTimelineRows(events: RetestSessionEvent[]): TimelineRow[] {
  // 第一遍：收集已有「权威收尾」的 streamKey。权威 = 真正的 chat 事件，
  // 或带 completeModelOutput 标记的事件。后端会把流式预览和收尾 chat 用同一
  // streamKey 原地升级；万一旧数据没升级成功，这里再兜底跳过残留的 streaming 预览。
  const authoritativeKeys = new Set<string>();
  events.forEach((event) => {
    const k = frontStreamKey(event);
    if (!k) return;
    if (event.type === 'chat' || asMetadata(event).completeModelOutput) authoritativeKeys.add(k);
  });

  const rows: TimelineRow[] = [];
  events.forEach((event) => {
    const meta = asMetadata(event);
    const eventTitle = repairRetestText(event.title || '');
    const eventContent = repairRetestText(event.content || '');
    if (event.type === 'chat') {
      if (!eventContent.trim()) return; // 跳过空对话气泡
      const role = eventRole(event) || 'agent';
      rows.push({ kind: 'message', key: event.id, role, event, live: false });
      return;
    }
    if (event.type === 'thought_summary') {
      const streaming = Boolean(meta.streaming);
      const isModelOutput = Boolean(meta.modelOutput) || Boolean(meta.dialogueOutput);
      const isReasoning = String(meta.phase || '') === 'session_reasoning';
      // 模型思考（reasoning）→ 始终折叠小字块，无论是否流式/modelOutput。
      // 后端现在实时流式推送思考，且用 reason streamKey 原地升级成完整思考；
      // 这里同 streamKey 已有完整思考时跳过残留流式块，避免重复。
      if (isReasoning) {
        const k = frontStreamKey(event);
        if (k && authoritativeKeys.has(k) && !meta.completeModelOutput) return;
        if (!eventContent.trim()) return; // 空内容不渲染，避免空折叠条
        rows.push({ kind: 'thought', key: event.id, event });
        return;
      }
      // 流式预览 / 模型可见正文 → Agent 正在生成的正文气泡。
      if (streaming || isModelOutput) {
        const k = frontStreamKey(event);
        // 同 streamKey 已有权威 chat（被收尾升级过）→ 跳过残留的流式预览，避免重复。
        if (k && authoritativeKeys.has(k)) return;
        if (!eventContent.trim() && !streaming) return;
        rows.push({ kind: 'message', key: event.id, role: 'agent', event, live: streaming });
        return;
      }
      // 其它无标记的思考 → 折叠小字；空内容不渲染，避免出现空折叠条。
      if (!eventContent.trim()) return;
      rows.push({ kind: 'thought', key: event.id, event });
      return;
    }
    if (event.type === 'tool_call' || event.type === 'tool_result') {
      rows.push({
        kind: 'tool',
        key: event.id,
        tool: {
          key: event.id,
          title: repairRetestText(event.tool?.label || eventTitle || event.tool?.toolId || '工具调用'),
          timestamp: event.timestamp,
          sourceFile: sourceLabel(event),
          tone: event.tone,
          tool: mergeToolTrace(undefined, event),
          content: repairRetestText(event.tool?.resultPreview || eventContent || ''),
        },
      });
      return;
    }
    if (event.type === 'artifact') {
      rows.push({ kind: 'artifact', key: event.id, event });
      return;
    }
    if (event.type === 'error') {
      rows.push({ kind: 'error', key: event.id, event });
      return;
    }
    // status 小字 narration：标题和内容都为空就不渲染，避免空行。
    if (!eventContent.trim() && !eventTitle.trim()) return;
    rows.push({ kind: 'status', key: event.id, event });
  });
  return rows;
}

function TimelineMessageRow({ row }: { row: Extract<TimelineRow, { kind: 'message' }> }) {
  const role = row.role;
  const label = role === 'user' ? '你' : role === 'system' ? '系统' : 'Agent';
  const content = repairRetestText(row.event.content || '');
  return (
    <article className={`retest-chat-row ${role}`}>
      <div className="retest-chat-edge">{label}</div>
      <div className="retest-chat-body">
        <div className="retest-chat-head">
          <strong>{role === 'user' ? '你' : 'Agent'}</strong>
          <span>{row.event.timestamp}</span>
        </div>
        {role === 'user'
          ? <ChatText content={content} />
          : <Markdown content={content || (row.live ? '正在生成…' : '')} />}
      </div>
    </article>
  );
}

function TimelineRowView({ row }: { row: TimelineRow }) {
  if (row.kind === 'message') return <TimelineMessageRow row={row} />;
  if (row.kind === 'thought') return <ThoughtBlock event={row.event} />;
  if (row.kind === 'tool') return <ToolCard item={row.tool} />;
  if (row.kind === 'artifact') {
    return repairRetestText(row.event.title) === '复测结论总览'
      ? <CompletionOverviewCard event={row.event} />
      : (
        <details className="retest-timeline-card artifact">
          <summary>
            <span className="retest-timeline-card-arrow" />
            <strong>{repairRetestText(row.event.title)}</strong>
            <em>{row.event.timestamp}</em>
          </summary>
          <pre className="retest-timeline-card-body">{artifactContent(row.event)}</pre>
        </details>
      );
  }
  if (row.kind === 'error') {
    return (
      <div className={`retest-chat-error ${row.event.tone || 'error'}`}>
        <strong>{repairRetestText(row.event.title)}</strong>
        {row.event.content ? <pre>{repairRetestText(row.event.content)}</pre> : null}
      </div>
    );
  }
  // status 过程行：无标题无内容则不渲染。
  return <TimelineStatusRow event={row.event} />;
}

function TimelineStatusRow({ event }: { event: RetestSessionEvent }) {
  const title = repairRetestText(event.title || '').trim();
  const content = repairRetestText(event.content || '').trim();
  if (!title && !content) return null;
  // 仅有标题（无正文）→ 单行小字 narration。
  if (!content) {
    return (
      <div className="retest-timeline-status">
        <span className="retest-timeline-status-dot" />
        <span className="retest-timeline-status-title">{title}</span>
        {event.timestamp ? <span className="retest-timeline-status-time">{event.timestamp}</span> : null}
      </div>
    );
  }
  // 内容简短且单行 → 直接平铺；否则做成可展开折叠卡，避免长文本被裁剪、无处点击。
  const isShort = content.length <= 80 && !content.includes('\n');
  if (isShort) {
    return (
      <div className="retest-timeline-status">
        <span className="retest-timeline-status-dot" />
        {title ? <span className="retest-timeline-status-title">{title}</span> : null}
        <span className="retest-timeline-status-text">{content}</span>
        {event.timestamp ? <span className="retest-timeline-status-time">{event.timestamp}</span> : null}
      </div>
    );
  }
  const firstLine = content.split('\n')[0];
  return (
    <details className={`retest-status-card ${event.tone || 'info'}`}>
      <summary>
        <span className="retest-status-card-caret" />
        <span className="retest-timeline-status-dot" />
        <strong>{title || '执行过程'}</strong>
        <span className="retest-status-card-peek">{firstLine}</span>
        {event.timestamp ? <em>{event.timestamp}</em> : null}
      </summary>
      <pre className="retest-status-card-body">{content}</pre>
    </details>
  );
}

function ToolCard({ item }: { item: ConversationTool }) {
  const tool = item.tool;
  const title = repairRetestText(item.title);
  const responseMeta = prettyJson(tool.responseMeta);
  const responseHeaders = prettyJson(tool.responseHeadersSafe);
  const toolMeta = compactToolMeta(tool);
  const observationCount = toolObservationCount(tool);
  return (
    <details className={`retest-tool-card ${tool.status || 'running'} ${item.tone || 'info'}`}>
      <summary>
        <span className="retest-tool-card-caret" />
        <span className="retest-tool-card-status" />
        <strong>{toolRunPrefix(tool.status, tool, title)} {title}</strong>
        <em>{repairRetestText(toolMeta)}</em>
      </summary>
      <div className="retest-tool-call-body">
        {tool.toolId ? <div><b>工具 ID</b><code>{repairRetestText(tool.toolId)}</code></div> : null}
        <div><b>运行状态</b><span>{statusText(tool.status, tool)}{typeof tool.durationMs === 'number' ? ` · ${tool.durationMs}ms` : ''}</span></div>
        {tool.target ? <div><b>目标</b><span>{repairRetestText(tool.target)}</span></div> : null}
        {tool.statusCode ? <div><b>HTTP</b><span>{tool.statusCode}{tool.finalUrl ? ` · ${repairRetestText(tool.finalUrl)}` : ''}</span></div> : null}
        {tool.argsPreview ? <div><b>参数摘要</b><pre>{repairRetestText(tool.argsPreview)}</pre></div> : null}
        {tool.requestSafe || tool.requestRaw ? <div><b>重放请求包</b><pre>{repairRetestText(tool.requestSafe || tool.requestRaw)}</pre></div> : null}
        {responseMeta ? <div><b>响应元信息</b><pre>{responseMeta}</pre></div> : null}
        {responseHeaders ? <div><b>响应头</b><pre>{responseHeaders}</pre></div> : null}
        {tool.responseRawExcerpt || tool.responseBodyPreview ? <div><b>响应数据</b><pre>{repairRetestText(tool.responseRawExcerpt || tool.responseBodyPreview)}</pre></div> : null}
        {tool.resultPreview || item.content ? <div><b>输出摘要</b><pre>{repairRetestText(tool.resultPreview || item.content)}</pre></div> : null}
        {tool.rawOutput ? <div><b>完整输出</b><pre>{repairRetestText(tool.rawOutput)}</pre></div> : null}
        {tool.evidence ? <div><b>证据摘要</b><pre>{repairRetestText(tool.evidence)}</pre></div> : null}
        {tool.failureReason ? <div><b>失败原因</b><pre>{repairRetestText(tool.failureReason)}</pre></div> : null}
        {tool.pythonProbeScript ? (
          <details className="retest-tool-script">
            <summary>Python 探针脚本</summary>
            <pre>{repairRetestText(tool.pythonProbeScript)}</pre>
          </details>
        ) : null}
        <div><b>计数</b><span>观察 {observationCount} / 原始 {tool.rawCount ?? 0}{typeof tool.failedCount === 'number' && tool.failedCount > 0 ? ` / 失败 ${tool.failedCount}` : ''}</span></div>
      </div>
    </details>
  );
}

function ToolGroup({ tools }: { tools: ConversationTool[] }) {
  const runningCount = tools.filter((item) => !item.tool.status || item.tool.status === 'running').length;
  const failedCount = tools.filter((item) => item.tool.status === 'failed' || item.tone === 'error').length;
  const blockedCount = tools.filter((item) => item.tool.status === 'blocked' && !isCompactionTool(item.tool, item.title)).length;
  const incompleteCount = tools.filter((item) => item.tool.status === 'incomplete' || (isCompactionTool(item.tool, item.title) && (item.tool.status === 'failed' || item.tool.status === 'skipped'))).length;
  const observationCount = tools.reduce((sum, item) => sum + toolObservationCount(item.tool), 0);
  const summaryParts = [
    runningCount ? `运行中 ${runningCount}` : '',
    failedCount ? `失败 ${failedCount}` : '',
    blockedCount ? `待继续 ${blockedCount}` : '',
    incompleteCount ? `未完成 ${incompleteCount}` : '',
    observationCount ? `观察 ${observationCount}` : '',
    `${tools.length} 条`,
  ].filter(Boolean);
  return (
    <details className={`retest-tool-group retest-process-line${runningCount ? ' running' : ''}${observationCount ? ' has-observation' : ''}`}>
      <summary>
        <span className="retest-process-icon" />
        <strong>{runningCount ? '正在运行' : '已运行'} {tools.length} 条工具</strong>
        <em>{summaryParts.join(' · ')}</em>
      </summary>
      <div className="retest-tool-group-body">
        {tools.map((tool) => <ToolCard key={tool.key} item={tool} />)}
      </div>
    </details>
  );
}

function CompletionOverviewCard({ event }: { event: RetestSessionEvent }) {
  return (
    <details className="retest-completion-overview retest-process-line">
      <summary><span className="retest-process-icon" /><strong>{repairRetestText(event.title)}</strong><em>{event.timestamp}</em></summary>
      <pre>{repairRetestText(event.content || '')}</pre>
    </details>
  );
}

function artifactContent(event: RetestSessionEvent) {
  const content = repairRetestText(String(event.content || '')).trim();
  if (content) return content;
  const metadata = asRecord(event.metadata);
  const reports = asStringArray(metadata?.reports);
  if (reports.length) return formatPathList(reports);
  return '暂无可展示产物。';
}

function isDialogueThought(event: RetestSessionEvent) {
  return Boolean(asMetadata(event).dialogueOutput);
}

function isProcessConversationItem(item: RetestConversationItem) {
  if (item.kind === 'tool' || item.kind === 'artifact') return true;
  if (item.kind === 'thought') return !isDialogueThought(item.event);
  return false;
}

function processGroupSummary(items: RetestConversationItem[]) {
  const toolCount = items.filter((item) => item.kind === 'tool').length;
  const thoughtCount = items.filter((item) => item.kind === 'thought').length;
  const artifactCount = items.filter((item) => item.kind === 'artifact').length;
  const runningCount = items.filter((item) => item.kind === 'tool' && (!item.tool.tool.status || item.tool.tool.status === 'running')).length;
  const failedCount = items.filter((item) => item.kind === 'tool' && (item.tool.tool.status === 'failed' || item.tool.tone === 'error')).length;
  const observationCount = items.reduce((sum, item) => item.kind === 'tool' ? sum + toolObservationCount(item.tool.tool) : sum, 0);
  const parts = [
    `${items.length} 条步骤`,
    toolCount ? `工具 ${toolCount}` : '',
    thoughtCount ? `思考 ${thoughtCount}` : '',
    artifactCount ? `产物 ${artifactCount}` : '',
    runningCount ? `运行中 ${runningCount}` : '',
    failedCount ? `失败 ${failedCount}` : '',
    observationCount ? `观察 ${observationCount}` : '',
  ].filter(Boolean);
  return {
    title: runningCount ? 'Agent 执行过程进行中' : 'Agent 执行过程',
    meta: parts.join(' · '),
    running: runningCount > 0,
    failed: failedCount > 0,
  };
}

function renderProcessItem(item: RetestConversationItem, key: string) {
  if (item.kind === 'tool') {
    return <ToolCard key={key} item={item.tool} />;
  }
  if (item.kind === 'thought') {
    return <ThoughtBlock key={key} event={item.event} />;
  }
  if (item.kind === 'artifact') {
    return repairRetestText(item.event.title) === '复测结论总览'
      ? <CompletionOverviewCard key={key} event={item.event} />
      : <details key={key} className="retest-chat-artifact retest-process-line"><summary><span className="retest-process-icon" /><strong>{repairRetestText(item.event.title)}</strong><em>{item.event.timestamp}</em></summary><pre>{artifactContent(item.event)}</pre></details>;
  }
  return null;
}

function ProcessGroup({ items, groupKey }: { items: RetestConversationItem[]; groupKey: string }) {
  const summary = processGroupSummary(items);
  return (
    <details className={`retest-process-group retest-process-line${summary.running ? ' running' : ''}${summary.failed ? ' failed' : ''}`}>
      <summary>
        <span className="retest-process-icon" />
        <strong>{repairRetestText(summary.title)}</strong>
        <em>{repairRetestText(summary.meta)}</em>
      </summary>
      <div className="retest-process-group-body">
        {items.map((item, index) => renderProcessItem(item, `${groupKey}-step-${item.key}-${index}`))}
      </div>
    </details>
  );
}

function renderOrderedConversationItems(turn: RetestConversationTurn) {
  const rendered: ReactNode[] = [];
  let pendingProcess: RetestConversationItem[] = [];

  const flushProcess = () => {
    if (!pendingProcess.length) return;
    const key = pendingProcess.map((item) => item.key).join('|');
    rendered.push(<ProcessGroup key={`process-group-${key}`} groupKey={key} items={pendingProcess} />);
    pendingProcess = [];
  };

  turn.items.forEach((item) => {
    if (isProcessConversationItem(item)) {
      pendingProcess.push(item);
      return;
    }
    flushProcess();
    if (item.kind === 'content') {
      rendered.push(<ChatText key={`content-${item.key}`} content={item.content} />);
      return;
    }
    if (item.kind === 'thought') {
      rendered.push(<ThoughtBlock key={item.key} event={item.event} />);
      return;
    }
    if (item.kind === 'artifact') {
      rendered.push(renderProcessItem(item, item.key));
      return;
    }
    if (item.kind === 'error') {
      rendered.push(<div key={item.key} className="retest-chat-error"><strong>{repairRetestText(item.event.title)}</strong><pre>{repairRetestText(item.event.content || '')}</pre></div>);
    }
  });
  flushProcess();
  return rendered;
}

function ConversationTurnRow({ turn }: { turn: RetestConversationTurn }) {
  const roleLabel = turn.role === 'user' ? '你' : turn.role === 'system' ? '系统' : 'Agent';
  return (
    <article className={`retest-chat-row ${turn.role}`}>
      <div className="retest-chat-edge">{roleLabel}</div>
      <div className="retest-chat-body">
        <div className="retest-chat-head">
          <strong>{repairRetestText(turn.title)}</strong>
          <span>{turn.sourceFile ? `${repairRetestText(turn.sourceFile)} · ` : ''}{turn.timestamp}</span>
        </div>
        {turn.items.length ? renderOrderedConversationItems(turn) : turn.contents.map((content, index) => <ChatText key={`content-${index}`} content={content} />)}
      </div>
    </article>
  );
}

function ActivityEntryRow({ entry }: { entry: RetestActivityEntry }) {
  if (entry.kind === 'tool') {
    return (
      <div className={`retest-activity-row tool ${entry.tool?.status || 'running'}`}>
        <div className="retest-activity-dot" />
        <div className="retest-activity-body">
          <div className="retest-activity-head"><strong>{repairRetestText(entry.title)}</strong><span>{entry.timestamp}</span></div>
          <div className="retest-activity-meta">
            {entry.sourceFile ? <span>{repairRetestText(entry.sourceFile)}</span> : null}
            {entry.tool?.toolId ? <span>{repairRetestText(entry.tool.toolId)}</span> : null}
            <span>{statusText(entry.tool?.status, entry.tool)}</span>
            {typeof entry.tool?.durationMs === 'number' ? <span>{entry.tool.durationMs}ms</span> : null}
          </div>
          <ToolCard item={{ key: entry.id, title: entry.title, timestamp: entry.timestamp, sourceFile: entry.sourceFile, tone: entry.tone, tool: entry.tool ?? {}, content: entry.content }} />
        </div>
      </div>
    );
  }
  return (
    <div className={`retest-activity-row ${entry.kind} ${entry.tone || 'info'}`}>
      <div className="retest-activity-dot" />
      <div className="retest-activity-body">
        <div className="retest-activity-head"><strong><span className="retest-event-badge">{eventBadge(entry.eventType)}</span>{repairRetestText(entry.title)}</strong><span>{entry.timestamp}</span></div>
        <div className="retest-activity-meta">
          {entry.sourceFile ? <span>{repairRetestText(entry.sourceFile)}</span> : null}
          {typeof entry.metadata?.phase === 'string' ? <span>{repairRetestText(entry.metadata.phase)}</span> : null}
        </div>
        {entry.content ? <pre>{repairRetestText(entry.content)}</pre> : null}
      </div>
    </div>
  );
}

export function TestWorkbenchPage() {
  const [store, setStore] = useState<RetestSessionStore>(() => readRetestSessionStore());
  const [agentInput, setAgentInput] = useState('');
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashSelection, setSlashSelection] = useState(0);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentRunBusy, setAgentRunBusy] = useState(false);
  const [agentBusySessionIds, setAgentBusySessionIds] = useState<string[]>([]);
  const [agentRunBusySessionIds, setAgentRunBusySessionIds] = useState<string[]>([]);
  const [stopBusy, setStopBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkbenchTab>('conversation');
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>('all');
  const [agentMode, setAgentMode] = useState<AgentMode>('auto');
  const [hybridOperationsBySession, setHybridOperationsBySession] = useState<Record<string, HybridOperationRow[]>>({});
  const [autoApproveBySession, setAutoApproveBySession] = useState<Record<string, boolean>>({});
  const [operationBusyIds, setOperationBusyIds] = useState<string[]>([]);
  const [confirmRequest, setConfirmRequest] = useState<{
    confirmationId: string;
    isAgentApproval?: boolean;
    sessionId?: string;
    operationId?: string;
    cwd?: string;
    risk?: string;
    sandboxPolicySummary?: string;
    previewArtifactId?: string;
    operation: string;
    matched: string;
    detail: string;
    script: string;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const stopRequestedRef = useRef(false);
  const runTokenRef = useRef(0);
  const currentRunOneTaskRef = useRef<string | null>(null);
  const resumeAutoStartRef = useRef(false);
  const manualInteractionUntilRef = useRef(0);
  const agentBusySessionIdsRef = useRef<Set<string>>(new Set());
  const agentRunBusySessionIdsRef = useRef<Set<string>>(new Set());
  const lastHybridStatusSyncRef = useRef<Record<string, number>>({});

  const sessions = store.sessions;
  const activeSession = sessions.find((session) => session.sessionId === store.activeSessionId) ?? null;
  const activeEvents = activeSession?.events ?? [];
  const sessionSummary = getSessionSummary(activeSession);
  const resumeCopy = resumeBannerCopy(activeSession);
  const activeCanContinue = hasContinueCue(activeSession);
  const activeStatusText = repairRetestText(activeSession?.status || '');
  const activeStatusRunning = activeStatusText.includes('正在') || activeStatusText.includes('压缩中') || activeStatusText.includes('自动压缩') || activeStatusText.includes('运行中');
  const activeStaleBusyCanBeReleased = Boolean(activeSession && activeCanContinue && !activeSession.isRunning && !activeStatusRunning);
  const activeAgentBusy = Boolean(activeSession?.sessionId && agentBusySessionIds.includes(activeSession.sessionId) && !activeStaleBusyCanBeReleased);
  const activeAgentRunBusy = Boolean(activeSession?.sessionId && agentRunBusySessionIds.includes(activeSession.sessionId) && !activeStaleBusyCanBeReleased);
  const activeSessionBusy = activeAgentBusy || activeAgentRunBusy;
  const activeSessionRuntimeRunning = Boolean(activeSession && (activeStatusRunning || (activeSession.isRunning && !activeCanContinue)));
  const activeSessionLocked = activeSessionRuntimeRunning || activeSessionBusy;
  const showResumeBanner = Boolean(activeSession && activeCanContinue && !activeSessionLocked && !activeSession.isRunning);
  const slashCommandOptions = useMemo(() => filterSlashCommands(agentInput), [agentInput]);
  const slashMenuVisible = slashMenuOpen && isSlashCommandInput(agentInput) && slashCommandOptions.length > 0;
  const timelineRows = useMemo(() => buildTimelineRows(activeEvents), [activeEvents]);
  const activityEntries = useMemo(() => buildActivityEntries(activeEvents), [activeEvents]);
  const activeOperations = useMemo(
    () => activeSession?.sessionId ? (hybridOperationsBySession[activeSession.sessionId] || []) : [],
    [activeSession?.sessionId, hybridOperationsBySession],
  );
  const activeAutoApprove = activeSession?.sessionId ? (autoApproveBySession[activeSession.sessionId] ?? true) : true;
  const filteredActivityEntries = useMemo(
    () => activityFilter === 'all' ? activityEntries : activityEntries.filter((entry) => entry.kind === activityFilter),
    [activityEntries, activityFilter],
  );
  const eventStats = useMemo(() => ({
    tools: activityEntries.filter((event) => event.kind === 'tool').length,
    thoughts: activeEvents.filter((event) => event.type === 'thought_summary').length,
    errors: activeEvents.filter((event) => event.type === 'error').length,
  }), [activeEvents, activityEntries]);

  useEffect(() => {
    setSlashSelection((value) => Math.max(0, Math.min(value, Math.max(0, slashCommandOptions.length - 1))));
  }, [slashCommandOptions.length]);

  const refreshStore = () => setStore(readRetestSessionStore());

  const syncHybridAgentSessionStatus = async (sessionId: string) => {
    if (!sessionId) return;
    const now = Date.now();
    if (now - (lastHybridStatusSyncRef.current[sessionId] ?? 0) < 5000) return;
    lastHybridStatusSyncRef.current[sessionId] = now;
    try {
      const statusSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId)
        ?? sessions.find((item) => item.sessionId === sessionId)
        ?? null;
      const result = await callBackend<HybridAgentStatusResponse>('doc.agent.status', {
        session_id: sessionId,
        target_dir: agentWorkspaceTargetDir(statusSession),
      });
      const events = Array.isArray(result.agent_session?.events)
        ? result.agent_session.events.map(sanitizeRetestSessionEvent).filter((item): item is RetestSessionEvent => Boolean(item))
        : [];
      if (events.length) appendRetestSessionEvents(sessionId, events);
      const operationRows = normalizeHybridOperations(result);
      setHybridOperationsBySession((current) => ({ ...current, [sessionId]: operationRows }));
      const restoredAutoApprove = Boolean(result.auto_approve ?? result.agent_session?.auto_approve ?? true);
      setAutoApproveBySession((current) => (
        current[sessionId] === restoredAutoApprove ? current : { ...current, [sessionId]: restoredAutoApprove }
      ));
      const running = operationRows.some(operationIsRunning);
      if (running) {
        const label = operationRows.find(operationIsRunning)?.tool_name || 'operation';
        patchRetestSession(sessionId, { status: `Agent operation running: ${label}`, isRunning: true });
      }
      refreshStore();
    } catch {
      // Backend status is a restore aid; local cache remains usable if it is unavailable.
    }
  };

  const markBusySet = (
    ref: MutableRefObject<Set<string>>,
    setIds: (value: string[]) => void,
    setAnyBusy: (value: boolean) => void,
    sessionId: string,
    busy: boolean,
  ) => {
    const next = new Set(ref.current);
    if (busy) next.add(sessionId);
    else next.delete(sessionId);
    ref.current = next;
    setIds(Array.from(next));
    setAnyBusy(next.size > 0);
  };

  const markAgentBusy = (sessionId: string, busy: boolean) => {
    markBusySet(agentBusySessionIdsRef, setAgentBusySessionIds, setAgentBusy, sessionId, busy);
  };

  const markAgentRunBusy = (sessionId: string, busy: boolean) => {
    markBusySet(agentRunBusySessionIdsRef, setAgentRunBusySessionIds, setAgentRunBusy, sessionId, busy);
  };

  const releaseSessionRuntimeBusy = (sessionId: string) => {
    const hadBusy = agentBusySessionIdsRef.current.has(sessionId) || agentRunBusySessionIdsRef.current.has(sessionId);
    if (agentBusySessionIdsRef.current.has(sessionId)) markAgentBusy(sessionId, false);
    if (agentRunBusySessionIdsRef.current.has(sessionId)) markAgentRunBusy(sessionId, false);
    clearRuntimeSessionIfMatches(sessionId);
    return hadBusy;
  };

  const isAnyRuntimeBusy = () => agentBusySessionIdsRef.current.size > 0 || agentRunBusySessionIdsRef.current.size > 0;

  const isSessionRuntimeBusy = (sessionId: string) => (
    agentBusySessionIdsRef.current.has(sessionId) || agentRunBusySessionIdsRef.current.has(sessionId)
  );

  const suppressAutoStartAfterManualAction = () => {
    manualInteractionUntilRef.current = Date.now() + AUTO_START_MANUAL_SUPPRESS_MS;
  };

  const isAutoStartSuppressed = () => Date.now() < manualInteractionUntilRef.current;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      try {
        const result = await callBackend<RetestEventStreamInfoResponse>('doc.retest.event_stream.info', {});
        if (stopped || !result.ws_url) return;
        socket = new WebSocket(result.ws_url);
        socket.onmessage = (message) => {
          try {
            const data = JSON.parse(String(message.data || '{}')) as RetestTraceWebSocketMessage;
            if (data.type !== 'retest_trace_event' || !data.session_id || !data.event?.id) return;
            const rawMetadata = data.event.metadata && typeof data.event.metadata === 'object'
              ? data.event.metadata as Record<string, unknown>
              : {};
            const rawSessionPatch = rawMetadata.sessionPatch;
            const incomingEvent = sanitizeRetestSessionEvent(data.event);
            if (!incomingEvent) return;
            // 本机破坏性操作 / Agent 审批请求：弹出确认卡片，等用户批准/拒绝。
            const eventType = String(data.event?.type || '');
            if (eventType === 'confirmation_request' || eventType === 'approval_request') {
              const meta = rawMetadata;
              const cid = typeof meta.confirmationId === 'string'
                ? meta.confirmationId
                : (typeof meta.approvalId === 'string' ? meta.approvalId : '');
              const requiresDecision = meta.requiresUserDecision !== false && meta.autoApproved !== true && meta.autoApprove !== true;
              if (cid && requiresDecision) {
                setConfirmRequest({
                  confirmationId: cid,
                  isAgentApproval: eventType === 'approval_request' || Boolean(meta.agentRuntime) || cid.startsWith('approval-'),
                  sessionId: data.session_id,
                  operationId: typeof meta.operationId === 'string' ? meta.operationId : '',
                  cwd: typeof meta.cwd === 'string' ? repairRetestText(meta.cwd) : '',
                  risk: typeof meta.risk === 'string' ? repairRetestText(meta.risk) : '',
                  sandboxPolicySummary: typeof meta.sandboxPolicySummary === 'string' ? repairRetestText(meta.sandboxPolicySummary) : '',
                  previewArtifactId: typeof meta.previewArtifactId === 'string' ? meta.previewArtifactId : '',
                  operation: typeof meta.operation === 'string' ? repairRetestText(meta.operation) : '本机敏感操作',
                  matched: typeof meta.matched === 'string' ? repairRetestText(meta.matched) : '',
                  detail: repairRetestText(data.event.content || ''),
                  script: typeof meta.script === 'string' ? repairRetestText(meta.script) : '',
                });
              }
            }
            const snapshot = readRetestSessionStore();
            const session = snapshot.sessions.find((item) => item.sessionId === data.session_id);
            const duplicate = Boolean(session?.events?.some((event) => event.id === incomingEvent.id));
            // 事件重复（WebSocket 重连/补发同一条）时跳过追加，避免列表里出现两条；
            // 但 sessionPatch 必须照常应用——它是幂等的状态快照，收尾的
            // isRunning:false 若因事件去重被一起丢掉，会导致跑完仍卡在「运行中」。
            if (!duplicate) {
              appendRetestSessionEvent(data.session_id, incomingEvent);
            }
            const patch = rawSessionPatch;
            if (patch && typeof patch === 'object' && !Array.isArray(patch)) {
              const sessionPatch = sanitizeRetestSessionPatch(patch);
              const currentSession = readRetestSessionStore().sessions.find((item) => item.sessionId === data.session_id);
              const stoppedByUser = stopRequestedRef.current && Boolean(
                repairRetestText(currentSession?.status || '').includes('停止')
                || currentSession?.events?.slice(-8).some((event) => repairRetestText(event.title).includes('停止') || Boolean(event.metadata?.stopped)),
              );
              if (stoppedByUser && sessionPatch.isRunning === false) {
                const currentProgress = Math.max(0, Math.min(99, Number(currentSession?.progress ?? sessionPatch.progress ?? 0)));
                sessionPatch.status = '复测已停止，可继续';
                sessionPatch.progress = currentProgress;
                sessionPatch.resumeState = sessionPatch.resumeState
                  ? {
                      ...sessionPatch.resumeState,
                      canContinue: true,
                      blockedReason: '复测已停止，可继续',
                      blockedStage: 'stop',
                      blockedTitle: '复测已停止',
                    }
                  : sessionPatch.resumeState;
              }
              patchRetestSession(data.session_id, sessionPatch);
              if (sessionPatch.isRunning === false) {
                clearRuntimeSessionIfMatches(data.session_id);
                markAgentBusy(data.session_id, false);
                markAgentRunBusy(data.session_id, false);
              }
            }
            if (!duplicate) refreshStore();
          } catch {
            // Ignore malformed local event frames.
          }
        };
        socket.onclose = () => {
          if (stopped) return;
          retryTimer = setTimeout(() => { void connect(); }, 1500);
        };
      } catch {
        if (!stopped) {
          retryTimer = setTimeout(() => { void connect(); }, 2500);
        }
      }
    };

    void connect();
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (socket) socket.close();
    };
  }, []);

  useEffect(() => {
    const handleChange = () => refreshStore();
    window.addEventListener(RETEST_SESSION_CHANGED_EVENT, handleChange);
    window.addEventListener('storage', handleChange);
    return () => {
      window.removeEventListener(RETEST_SESSION_CHANGED_EVENT, handleChange);
      window.removeEventListener('storage', handleChange);
    };
  }, []);

  useEffect(() => {
    if (activeSession?.sessionId) void syncHybridAgentSessionStatus(activeSession.sessionId);
  }, [activeSession?.sessionId]);

  useEffect(() => {
    if (!activeSession?.sessionId) return undefined;
    const sessionId = activeSession.sessionId;
    const timer = window.setInterval(() => {
      void syncHybridAgentSessionStatus(sessionId);
    }, 7000);
    return () => window.clearInterval(timer);
  }, [activeSession?.sessionId]);

  // 流式更新是原地替换同一条事件，activeEvents.length 不变，所以用「内容指纹」
  // （事件数 + 末条内容长度）做依赖，保证每次增量吐字都会触发滚动检查。
  const lastEvent = activeEvents[activeEvents.length - 1];
  const streamFingerprint = `${activeEvents.length}:${(lastEvent?.content || '').length}:${lastEvent?.id || ''}`;

  // 记录用户是否贴在底部：贴底才自动滚到最新；用户向上翻看历史时不强拽回去。
  const stickToBottomRef = useRef(true);
  useEffect(() => {
    const target = threadRef.current;
    if (!target) return;
    const onScroll = () => {
      const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
      stickToBottomRef.current = distanceFromBottom < 80;
    };
    target.addEventListener('scroll', onScroll, { passive: true });
    return () => target.removeEventListener('scroll', onScroll);
  }, [activeTab]);

  useEffect(() => {
    const target = threadRef.current;
    if (!target) return;
    if (stickToBottomRef.current) target.scrollTop = target.scrollHeight;
  }, [activeSession?.sessionId, streamFingerprint, activeSessionBusy, activeTab]);

  // 切换会话 / 切到对话或动态 tab 时，重置为贴底并滚到最新。
  useEffect(() => {
    stickToBottomRef.current = true;
    const target = threadRef.current;
    if (target) target.scrollTop = target.scrollHeight;
  }, [activeSession?.sessionId, activeTab]);

  useEffect(() => {
    const requestedSessionId = window.sessionStorage.getItem(RETEST_RESUME_REQUEST_KEY);
    if (!requestedSessionId) return;
    if (isAutoStartSuppressed()) {
      window.sessionStorage.removeItem(RETEST_RESUME_REQUEST_KEY);
      return;
    }
    if (resumeAutoStartRef.current || isAnyRuntimeBusy()) return;
    window.sessionStorage.removeItem(RETEST_RESUME_REQUEST_KEY);
    const session = sessions.find((item) => item.sessionId === requestedSessionId);
    if (!session || (!session.resumeState?.canContinue && !hasContinueCue(session))) return;
    resumeAutoStartRef.current = true;
    setActiveRetestSession(session.sessionId);
    void resumeSessionThroughAgent(session).finally(() => {
      resumeAutoStartRef.current = false;
    });
  }, [agentRunBusy, agentBusy, sessions]);

  useEffect(() => {
    const requestedTargetDir = window.sessionStorage.getItem(RETEST_RERUN_REQUEST_KEY);
    if (!requestedTargetDir) return;
    if (isAutoStartSuppressed()) {
      window.sessionStorage.removeItem(RETEST_RERUN_REQUEST_KEY);
      return;
    }
    if (resumeAutoStartRef.current || isAnyRuntimeBusy()) return;
    window.sessionStorage.removeItem(RETEST_RERUN_REQUEST_KEY);
    resumeAutoStartRef.current = true;
    const session = createRetestSession(requestedTargetDir);
    setActiveRetestSession(session.sessionId);
    patchRetestSession(session.sessionId, { targetDir: requestedTargetDir, status: '准备重新复测...' });
    refreshStore();
    void runRetestInCurrentSession({ ...session, targetDir: requestedTargetDir }, 'rerun', { generateReports: true }).finally(() => {
      resumeAutoStartRef.current = false;
    });
  }, [agentRunBusy, agentBusy]);

  const selectSession = (sessionId: string) => {
    suppressAutoStartAfterManualAction();
    setActiveRetestSession(sessionId);
    refreshStore();
    setActiveTab('conversation');
  };

  const createBlankSession = () => {
    suppressAutoStartAfterManualAction();
    const session = createRetestSession('');
    refreshStore();
    setActiveTab('conversation');
    return session;
  };

  const pushAgentEvent = (
    sessionId: string,
    title: string,
    content: string,
    tone: RetestSessionEvent['tone'] = 'info',
    metadata: Record<string, unknown> = {},
  ) => appendRetestSessionEvent(sessionId, makeRetestSessionEvent('chat', title, content, tone, { metadata: { role: 'agent', ...metadata } }));

  const stopActiveSession = async () => {
    const session = activeSession;
    if (!session?.sessionId || stopBusy) return;
    const sessionId = session.sessionId;
    const latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? session;
    stopRequestedRef.current = true;
    setStopBusy(true);
    markAgentBusy(sessionId, false);
    markAgentRunBusy(sessionId, false);
    patchRetestSession(sessionId, {
      isRunning: false,
      status: '复测已停止，可继续',
      resumeState: latestSession.resumeState
        ? {
            ...latestSession.resumeState,
            canContinue: true,
            blockedReason: '复测已停止，可继续',
            blockedStage: 'stop',
            blockedTitle: '复测已停止',
          }
        : latestSession.resumeState,
    });
    pushAgentEvent(sessionId, '复测已停止', '已发送停止指令，当前会话会保留可继续断点。', 'warn', { stopped: true });
    refreshStore();
    const taskId = currentRunOneTaskRef.current;
    try {
      if (taskId) {
        await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.stop', { task_id: taskId });
      }
    } catch (error) {
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '停止单份通报任务失败', errorMessage(error), 'warn', { metadata: { phase: 'stop' } }));
    }
    try {
      await callBackend<RetestAgentResponse>('doc.retest.agent.stop', { session_id: sessionId });
    } catch (error) {
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '停止 Agent 会话失败', errorMessage(error), 'warn', { metadata: { phase: 'stop' } }));
    } finally {
      const afterStopSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? latestSession;
      const stoppedProgress = Math.max(0, Math.min(99, Number(latestSession.progress ?? afterStopSession.progress ?? 0)));
      patchRetestSession(sessionId, {
        isRunning: false,
        status: '复测已停止，可继续',
        progress: stoppedProgress,
        resumeState: afterStopSession.resumeState
          ? {
              ...afterStopSession.resumeState,
              canContinue: true,
              blockedReason: '复测已停止，可继续',
              blockedStage: 'stop',
              blockedTitle: '复测已停止',
            }
          : afterStopSession.resumeState,
      });
      clearRuntimeSessionIfMatches(sessionId);
      setStopBusy(false);
      refreshStore();
    }
  };

  const respondConfirmation = async (decision: 'approve' | 'reject') => {
    const request = confirmRequest;
    if (!request || confirmBusy) return;
    setConfirmBusy(true);
    try {
      const requestSessionId = request.sessionId || activeSession?.sessionId || '';
      const requestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === requestSessionId)
        ?? activeSession;
      const payload = {
        confirmation_id: request.confirmationId,
        approval_id: request.confirmationId,
        session_id: requestSessionId,
        target_dir: agentWorkspaceTargetDir(requestSession),
        decision,
        note: decision === 'approve' ? '用户已批准执行' : '用户拒绝执行',
      };
      await callBackend(request.isAgentApproval ? 'doc.agent.approval.respond' : 'doc.retest.confirmation.respond', payload);
      if (request.isAgentApproval && payload.session_id) {
        lastHybridStatusSyncRef.current[payload.session_id] = 0;
        void syncHybridAgentSessionStatus(payload.session_id);
      }
    } catch (error) {
      const sessionId = activeSession?.sessionId;
      if (sessionId) {
        appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '提交确认失败', errorMessage(error), 'warn', { metadata: { phase: 'confirm' } }));
      }
    } finally {
      setConfirmBusy(false);
      setConfirmRequest(null);
    }
  };

  const stopHybridOperation = async (operationIdValue: string) => {
    const sessionId = activeSession?.sessionId || '';
    const operationIdText = operationIdValue.trim();
    if (!sessionId || !operationIdText || operationBusyIds.includes(operationIdText)) return;
    setOperationBusyIds((current) => [...current, operationIdText]);
    try {
      const requestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId)
        ?? activeSession;
      await callBackend('doc.agent.operation.stop', {
        session_id: sessionId,
        operation_id: operationIdText,
        target_dir: agentWorkspaceTargetDir(requestSession),
      });
      lastHybridStatusSyncRef.current[sessionId] = 0;
      await syncHybridAgentSessionStatus(sessionId);
    } catch (error) {
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', 'Agent operation stop failed', errorMessage(error), 'warn', { metadata: { phase: 'operation_stop', operationId: operationIdText } }));
      refreshStore();
    } finally {
      setOperationBusyIds((current) => current.filter((item) => item !== operationIdText));
    }
  };

  const setHybridAutoApproval = async (enabled: boolean) => {
    const sessionId = activeSession?.sessionId || '';
    if (!sessionId) return;
    setAutoApproveBySession((current) => ({ ...current, [sessionId]: enabled }));
    try {
      const result = await callBackend<HybridAutoApprovalResponse>('doc.agent.auto_approval.set', {
        session_id: sessionId,
        target_dir: agentWorkspaceTargetDir(activeSession),
        enabled,
        note: enabled ? 'Enabled from workbench.' : 'Disabled from workbench.',
      });
      const confirmed = Boolean(result.auto_approve ?? result.agent_session?.auto_approve ?? enabled);
      setAutoApproveBySession((current) => ({ ...current, [sessionId]: confirmed }));
      lastHybridStatusSyncRef.current[sessionId] = 0;
      void syncHybridAgentSessionStatus(sessionId);
    } catch (error) {
      setAutoApproveBySession((current) => ({ ...current, [sessionId]: !enabled }));
      appendRetestSessionEvent(
        sessionId,
        makeRetestSessionEvent('error', 'Auto approval update failed', errorMessage(error), 'warn', {
          metadata: { phase: 'auto_approval' },
        }),
      );
      refreshStore();
    }
  };

  const captureWorkbenchResultScreenshot = async (fallbackText: string) => {
    await wait(80);
    const { default: html2canvas } = await import('html2canvas');
    const temporaryTarget = document.createElement('div');
    temporaryTarget.className = 'retest-result-capture retest-result-capture-clone';
    const fixedFallbackText = repairRetestText(fallbackText || '复测结果将在这里展示。');
    temporaryTarget.innerHTML = `<div class="retest-capture-title">复测结果预览</div><pre>${escapeHtml(fixedFallbackText)}</pre>`;
    document.body.appendChild(temporaryTarget);
    try {
      await wait(30);
      const canvas = await html2canvas(temporaryTarget, {
        backgroundColor: '#ffffff',
        logging: false,
        scale: Math.min(window.devicePixelRatio || 1, 2),
        useCORS: true,
      });
      return canvas.toDataURL('image/png');
    } finally {
      temporaryTarget.remove();
    }
  };

  const continueLegacySessionWithAgent = async (
    session: RetestSessionDraft,
    trimmedTargetDir: string,
    shouldGenerateReports: boolean,
  ) => {
    const sessionId = session.sessionId;
    const contextSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? session;
    if (isSessionRuntimeBusy(sessionId)) {
      if (!contextSession.isRunning && hasContinueCue(contextSession)) {
        releaseSessionRuntimeBusy(sessionId);
      } else {
        return false;
      }
    }
    const frontendContext = buildAgentFrontendContext(contextSession);
    const completedCount = frontendContext.progressEvidence.completedFileNames.length;
    const roundId = `agent-legacy-continue-${Date.now().toString(36)}`;
    const progress = Math.max(0, Math.min(100, Number(contextSession.progress ?? 0)));

    markAgentBusy(sessionId, true);
    setActiveTab('conversation');
    setActiveRetestSession(sessionId);
    window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, sessionId);
    appendRetestSessionEvent(sessionId, makeRetestSessionEvent('chat', '你', '继续', 'info', { metadata: { role: 'user', roundId } }));
    patchRetestSession(sessionId, {
      targetDir: trimmedTargetDir,
      status: 'Agent 正在恢复旧会话上下文...',
      progress,
      isRunning: true,
      resumeState: null,
    });
    pushAgentEvent(
      sessionId,
      '恢复旧会话上下文',
      `我会先读取本地保存的会话动态、日志和结果，恢复已完成进度，再从未完成部分继续。${completedCount ? `\n已从旧会话识别到 ${completedCount} 个已完成文件。` : '\n旧会话没有完整断点，我会先核对旧会话事件再决定下一步。'}`,
      'info',
      { action: 'continue', roundId, phase: 'frontend_context_restore', generateReports: shouldGenerateReports },
    );
    refreshStore();

    const instruction = [
      '继续。',
      '请先根据前端持久化会话上下文恢复当前进度，先概括已完成部分，再决定下一步。',
      '不要重复已经完成复测的通报；如果需要重新扫描目录，请先用旧会话里的已完成文件名校准断点，然后从下一份未完成通报继续。',
      shouldGenerateReports ? '本轮来自一键复测流程；如果继续复测，请在需要时继续生成报告。' : '没有检测到报告生成意图；如需报告请明确说明。',
    ].join('\n');

    try {
      const result = await callBackendWithTimeout<RetestAgentResponse>('doc.retest.agent.message', {
        session_id: sessionId,
        message: instruction,
        target_dir: trimmedTargetDir,
        generate_reports: shouldGenerateReports,
        frontend_context: frontendContext,
        force_resume: true,
      }, 45000);
      applyAgentMessageResult(sessionId, result, contextSession, progress);
      return Boolean(result.success);
    } catch (error) {
      const reason = errorMessage(error);
      patchRetestSession(sessionId, { isRunning: false, status: `Agent 恢复旧会话失败: ${reason}` });
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', 'Agent 恢复旧会话失败', reason, 'error', { metadata: { phase: 'frontend_context_restore', roundId } }));
      clearRuntimeSessionIfMatches(sessionId);
      return false;
    } finally {
      markAgentBusy(sessionId, false);
      refreshStore();
    }
  };

  const applyAgentMessageResult = (
    sessionId: string,
    result: RetestAgentResponse,
    contextSession: RetestSessionDraft,
    fallbackProgress = Number(contextSession.progress ?? 0),
  ) => {
    if (result.agent_session) {
      const agentSession = result.agent_session as HybridAgentStatusResponse['agent_session'];
      const operationRows = normalizeHybridOperations({ success: true, agent_session: agentSession });
      if (operationRows.length) {
        setHybridOperationsBySession((current) => ({ ...current, [sessionId]: operationRows }));
      }
      if (typeof agentSession?.auto_approve === 'boolean') {
        setAutoApproveBySession((current) => ({ ...current, [sessionId]: Boolean(agentSession.auto_approve) }));
      }
    }
    const latestContext = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? contextSession;
    const currentProgress = Math.max(0, Math.min(100, Number(latestContext.progress ?? fallbackProgress)));
    const returnedProgress = typeof result.progress === 'number' ? result.progress : currentProgress;
    const nextProgress = result.running ? Math.max(currentProgress, returnedProgress) : returnedProgress;
    const resultResumeState = result.resume_state ?? null;
    patchRetestSession(sessionId, {
      isRunning: Boolean(result.running),
      status: result.status || result.message || latestContext.status || contextSession.status,
      progress: nextProgress,
      log: result.logs?.length ? joinLogs(result.logs) : latestContext.log,
      latestResultData: result.latest_result_data ?? latestContext.latestResultData,
      generateReports: Boolean(result.generate_reports || latestContext.generateReports || sessionWantsGeneratedReports(latestContext, resultResumeState)),
      resumeState: result.blocked
        ? resultResumeState ?? latestContext.resumeState ?? null
        : result.running
          ? null
          : (latestContext.resumeState?.canContinue ? latestContext.resumeState : null),
    });
    if (!result.running) clearRuntimeSessionIfMatches(sessionId);
    if (!result.success || result.blocked) {
      appendRetestSessionEvent(
        sessionId,
        makeRetestSessionEvent('status', result.blocked_title || 'Agent 会话待继续', result.blocked_reason || result.message || 'Agent 会话待继续', 'warn', {
          metadata: { phase: result.blocked_stage || 'agent', blockedByAiConfig: Boolean(result.blocked) },
        }),
      );
    }
  };

  const resumeSessionThroughAgent = async (session: RetestSessionDraft | null) => {
    if (!session) return false;
    const latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === session.sessionId) ?? session;
    const sessionId = latestSession.sessionId;
    if (!hasContinueCue(latestSession)) return false;
    if (isSessionRuntimeBusy(sessionId)) {
      if (!latestSession.isRunning) {
        releaseSessionRuntimeBusy(sessionId);
      } else {
        return false;
      }
    }
    const frontendContext = buildAgentFrontendContext(latestSession);
    const targetDir = latestSession.resumeState?.targetDir || latestSession.targetDir || '';
    const shouldGenerateReports = sessionWantsGeneratedReports(latestSession, latestSession.resumeState);
    const completedCount = frontendContext.progressEvidence.completedFileNames.length;
    const progress = Math.max(0, Math.min(100, Number(latestSession.progress ?? 0)));
    const roundId = `agent-resume-${Date.now().toString(36)}`;

    markAgentBusy(sessionId, true);
    setActiveTab('conversation');
    setActiveRetestSession(sessionId);
    window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, sessionId);
    appendRetestSessionEvent(sessionId, makeRetestSessionEvent('chat', '你', '继续', 'info', { metadata: { role: 'user', roundId } }));
    patchRetestSession(sessionId, {
      targetDir,
      status: 'Agent 正在结合上下文继续...',
      progress,
      isRunning: true,
      generateReports: shouldGenerateReports,
      resumeState: latestSession.resumeState ? { ...latestSession.resumeState, canContinue: false, generateReports: shouldGenerateReports } : null,
    });
    appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
      'status',
      'Agent 正在恢复上下文',
      `已携带前端持久化上下文、压缩记忆和断点证据进入模型对话。${completedCount ? `\n已识别 ${completedCount} 个已完成文件证据。` : ''}`,
      'info',
      { metadata: { phase: 'frontend_context_restore', roundId, generateReports: shouldGenerateReports } },
    ));
    refreshStore();

    const instruction = [
      '继续。',
      '请把这当作同一段对话的延续：先读取前端持久化上下文和 AI 语义压缩记忆，再决定是直接回复还是调用工具。',
      '如果继续复测，请先根据 completedFileNames / nextIndex / 磁盘报告证据校准断点，不要重复已完成通报。',
      shouldGenerateReports ? '本会话来自一键复测或用户要求报告；如果继续复测，完成后继续生成报告。' : '如果只是普通对话，可以直接回复；如果需要工具，再调用工具。',
    ].join('\n');

    try {
      const result = await callBackendWithTimeout<RetestAgentResponse>('doc.retest.agent.message', {
        session_id: sessionId,
        message: instruction,
        target_dir: targetDir,
        generate_reports: shouldGenerateReports,
        frontend_context: frontendContext,
        force_resume: true,
      }, 45000);
      applyAgentMessageResult(sessionId, result, latestSession, progress);
      return Boolean(result.success);
    } catch (error) {
      const reason = errorMessage(error);
      patchRetestSession(sessionId, { isRunning: false, status: `Agent 继续失败: ${reason}` });
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('status', 'Agent 继续失败', reason, 'warn', { metadata: { phase: 'frontend_context_restore', roundId } }));
      clearRuntimeSessionIfMatches(sessionId);
      return false;
    } finally {
      markAgentBusy(sessionId, false);
      refreshStore();
    }
  };

  const runRetestInCurrentSession = async (
    session: RetestSessionDraft | null,
    mode: 'continue' | 'rerun',
    options: { generateReports?: boolean } = {},
  ) => {
    if (!session) return false;
    const latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === session.sessionId) ?? session;
    const resumeState = mode === 'continue' && latestSession.resumeState?.canContinue ? latestSession.resumeState : null;
    const legacyContinue = mode === 'continue' && !resumeState && hasContinueCue(latestSession);
    const sessionId = latestSession.sessionId;
    const trimmedTargetDir = (resumeState?.targetDir || latestSession.targetDir || '').trim();
    const shouldGenerateReports = options.generateReports !== undefined
      ? Boolean(options.generateReports)
      : sessionWantsGeneratedReports(latestSession, resumeState);
    if (!trimmedTargetDir) {
      pushAgentEvent(sessionId, 'Agent 执行', '当前会话没有可用于复测的通报目录。', 'warn', { action: mode });
      refreshStore();
      return false;
    }
    if (mode === 'continue' && !resumeState && !legacyContinue) {
      pushAgentEvent(sessionId, 'Agent 执行', '当前会话没有可继续的断点。', 'warn', { action: mode });
      refreshStore();
      return false;
    }

    if (mode === 'continue' && !latestSession.isRunning && hasContinueCue(latestSession)) {
      releaseSessionRuntimeBusy(sessionId);
    }

    if (legacyContinue) {
      return await continueLegacySessionWithAgent(latestSession, trimmedTargetDir, shouldGenerateReports);
    }
    if (agentRunBusySessionIdsRef.current.size > 0 || isSessionRuntimeBusy(sessionId)) return false;
    if (latestSession.isRunning && !resumeState) return false;

    const runToken = runTokenRef.current + 1;
    runTokenRef.current = runToken;
    const isCurrentRun = () => runTokenRef.current === runToken;
    const shouldStopCurrentRun = () => isCurrentRun() && stopRequestedRef.current;
    stopRequestedRef.current = false;
    currentRunOneTaskRef.current = null;

    markAgentRunBusy(sessionId, true);
    setActiveTab('conversation');
    setActiveRetestSession(sessionId);
    window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, sessionId);

    const roundPrefix = `agent-${mode}-${Date.now().toString(36)}`;
    patchRetestSession(sessionId, {
      targetDir: trimmedTargetDir,
      status: mode === 'continue' ? (resumeState ? 'Agent 正在从断点继续复测...' : 'Agent 正在恢复旧会话并继续复测...') : 'Agent 正在重新复测当前通报目录...',
      progress: mode === 'continue' ? Math.max(0, Math.min(100, Number(latestSession.progress ?? 0))) : 5,
      isRunning: true,
      resumeState: resumeState ? { ...resumeState, canContinue: false, generateReports: shouldGenerateReports } : null,
    });
    pushAgentEvent(
      sessionId,
      'Agent 执行',
      mode === 'continue'
        ? `我会在当前会话从断点继续复测：${trimmedTargetDir}${shouldGenerateReports ? '\n本轮来自一键复测流程，会继续生成报告。' : '\n没有检测到报告生成意图；如需报告请明确说明。'}`
        : `我会在当前会话重新复测：${trimmedTargetDir}${shouldGenerateReports ? '\n你要求生成报告，本轮复测完成后会写报告。' : '\n没有检测到报告生成意图；如需报告请明确说明。'}`,
      'ok',
      { action: mode, roundId: roundPrefix, generateReports: shouldGenerateReports },
    );
    refreshStore();

    let sourceFiles = resumeState?.sourceFiles ?? [];
    let startIndex = resumeState ? Math.min(Math.max(0, resumeState.nextIndex), sourceFiles.length) : 0;
    const summaries: string[] = resumeState ? [...resumeState.summaries] : [];
    const reports: string[] = resumeState ? [...resumeState.reports] : [];
    const completionItems: RetestCompletionItem[] = resumeState ? asCompletionItems(resumeState.completionItems) : [];
    const allLogs: string[] = resumeState ? [...resumeState.allLogs] : splitLogLines(latestSession.log);
    if (!resumeState) allLogs.push(`${mode === 'continue' ? 'Agent 恢复旧会话并继续复测开始' : 'Agent 重新复测开始'}: ${trimmedTargetDir}`);
    let failedCount = resumeState ? Number(resumeState.failedCount || 0) : 0;
    const resumeCompletedFileNames = mode === 'continue'
      ? completedFileNameSetForResume(latestSession, completionItems)
      : new Set<string>();
    if (mode === 'continue' && sourceFiles.length) {
      startIndex = resumeStartIndexFromEvidence(latestSession, sourceFiles, startIndex);
    }
    startIndex = advanceIndexPastCompletedFiles(sourceFiles, startIndex, resumeCompletedFileNames);

    const syncSession = (partial: Partial<RetestSessionDraft>) => {
      patchRetestSession(sessionId, partial);
      refreshStore();
    };

    const buildResumeState = (
      nextIndex: number,
      canContinue: boolean,
      blocked?: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse,
    ): RetestResumeState => ({
      canContinue,
      targetDir: trimmedTargetDir,
      sourceFiles,
      nextIndex: Math.max(0, Math.min(sourceFiles.length, nextIndex)),
      summaries,
      reports,
      completionItems: completionItems.map((item) => ({ ...item })),
      allLogs,
      failedCount,
      generateReports: shouldGenerateReports,
      blockedReason: blocked?.message,
      blockedStage: blocked?.blocked_stage,
      blockedTitle: blocked?.blocked_title,
    });

    const stopForUser = async (index: number, taskId?: string | null) => {
      const message = '复测已停止，可继续';
      if (taskId) {
        try {
          const stopResult = await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.stop', { task_id: taskId });
          allLogs.push(...(stopResult.logs ?? []));
          if (stopResult.trace_events?.length) appendRetestSessionEvents(sessionId, stopResult.trace_events);
        } catch (error) {
          allLogs.push(`停止任务失败: ${errorMessage(error)}`);
        }
      }
      if (!allLogs[allLogs.length - 1]?.includes(message)) {
        allLogs.push(message);
      }
      const stoppedPayload = {
        success: false,
        message,
        blocked_title: '复测已停止',
        blocked_stage: 'stop',
      } as RetestRunOneResponse;
      const resumePayload = buildResumeState(index, true, stoppedPayload);
      const progress = Math.round((index / Math.max(1, sourceFiles.length)) * 100);
      syncSession({
        status: message,
        log: joinLogs(allLogs),
        progress,
        isRunning: false,
        resumeState: resumePayload,
      });
      pushAgentEvent(
        sessionId,
        '复测已停止',
        `已保留断点：${getFileName(sourceFiles[index] || '') || '下一份通报'}。点击继续测试会从这里恢复。`,
        'warn',
        { action: mode, roundId: roundPrefix, stopped: true },
      );
      refreshStore();
      return false;
    };

    const stopForAiConfig = (index: number, blocked: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse) => {
      const pause = describeAiPause(blocked);
      const reason = blocked.message || pause.status;
      allLogs.push(reason);
      const resumePayload = buildResumeState(index, true, blocked);
      const progress = Math.round((index / Math.max(1, sourceFiles.length)) * 100);
      syncSession({
        status: pause.status,
        log: joinLogs(allLogs),
        progress,
        isRunning: false,
        resumeState: resumePayload,
      });
      pushAgentEvent(
        sessionId,
        pause.title,
        `${reason}\n${pause.instruction}\n断点位置：${getFileName(sourceFiles[index] || '') || '下一份通报'}，不会重复已完成通报。`,
        'warn',
        { action: mode, roundId: roundPrefix, blockedByAiConfig: true },
      );
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', pause.title, reason, 'warn', {
        metadata: { phase: blocked.blocked_stage || 'config', blockedByAiConfig: true, resumeState: resumePayload, roundId: roundPrefix },
      }));
      refreshStore();
    };

    try {
      if (!resumeState) {
        syncSession({ progress: 3, status: 'Agent 正在扫描通报目录...', log: joinLogs(allLogs), isRunning: true });
        const listResult = await callBackend<RetestListFilesResponse>('doc.retest.list_files', { target_dir: trimmedTargetDir });
        if (!isCurrentRun()) return false;
        sourceFiles = listResult.source_files ?? [];
        mergeCompletedFileNamesForResume(resumeCompletedFileNames, listResult.completed_source_file_names);
        allLogs.push(...(listResult.logs ?? []));
        const listedCompletedCount = listResult.completed_source_file_names?.length ?? 0;
        const listedNextName = listResult.next_source_file_name || getFileName(sourceFiles[Math.max(0, Number(listResult.next_index_hint ?? 0))] || '');
        pushAgentEvent(
          sessionId,
          '文档扫描',
          sourceFiles.length
            ? [
              `发现 ${sourceFiles.length} 份原始通报文档。`,
              listedCompletedCount ? `已从磁盘复测报告识别 ${listedCompletedCount} 份已完成通报。` : '',
              listedNextName ? `下一份未完成通报：${listedNextName}` : '未发现未完成通报。',
            ].filter(Boolean).join('\n')
            : (listResult.message || '未找到通报文档。'),
          sourceFiles.length ? 'ok' : 'warn',
          {
            action: mode,
            roundId: roundPrefix,
            progressEvidence: {
              targetDir: trimmedTargetDir,
              completedFileNames: listResult.completed_source_file_names ?? [],
              completedCountHint: listResult.completed_count_hint,
              nextIndexHint: listResult.next_index_hint,
              nextSourceFileName: listResult.next_source_file_name,
            },
          },
        );
        if (!sourceFiles.length) {
          syncSession({
            progress: 0,
            status: listResult.message || '未找到通报文档。',
            log: joinLogs(allLogs),
            isRunning: false,
            resumeState: null,
          });
          return false;
        }
        if (!isCurrentRun()) return false;
        if (mode === 'continue') {
          startIndex = Math.max(
            resumeStartIndexFromEvidence(latestSession, sourceFiles, startIndex),
            Math.max(0, Number(listResult.next_index_hint ?? 0)),
            listedCompletedCount,
          );
          startIndex = advanceIndexPastCompletedFiles(sourceFiles, startIndex, resumeCompletedFileNames);
        }
        if (shouldStopCurrentRun()) {
          return await stopForUser(0, currentRunOneTaskRef.current);
        }
      } else {
        startIndex = advanceIndexPastCompletedFiles(sourceFiles, startIndex, resumeCompletedFileNames);
        pushAgentEvent(sessionId, '断点恢复', `恢复原队列：共 ${sourceFiles.length} 份通报，已完成 ${startIndex} 份。`, 'ok', { action: mode, roundId: roundPrefix });
      }

      syncSession({ log: joinLogs(allLogs), resumeState: buildResumeState(startIndex, false) });

      for (let index = startIndex; index < sourceFiles.length; index += 1) {
        if (!isCurrentRun()) return false;
        if (shouldStopCurrentRun()) {
          return await stopForUser(index, currentRunOneTaskRef.current);
        }
        const sourceFile = sourceFiles[index];
        const fileLabel = getFileName(sourceFile);
        const fileRoundId = `${roundPrefix}-file-${index + 1}`;
        const nextProgress = Math.max(5, Math.round((index / Math.max(1, sourceFiles.length)) * 100));
        const nextStatus = `Agent 正在复测 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
        syncSession({ progress: nextProgress, status: nextStatus, isRunning: true });
        pushAgentEvent(sessionId, `通报 ${index + 1}/${sourceFiles.length}`, `开始解析通报并执行复测：${fileLabel}`, 'info', { action: mode, roundId: fileRoundId });

        try {
          const seenTraceEventIds = new Set<string>();
          let fileLogCount = 0;
          let fileTraceEventCount = 0;
          const appendNewTraceEvents = (events?: RetestSessionEvent[], traceEventCount?: number) => {
            const nextEvents = (events ?? []).filter((event) => {
              if (!event?.id || seenTraceEventIds.has(event.id)) return false;
              seenTraceEventIds.add(event.id);
              return true;
            });
            fileTraceEventCount = Math.max(fileTraceEventCount, typeof traceEventCount === 'number' ? traceEventCount : fileTraceEventCount + (events?.length ?? 0));
            if (nextEvents.length) appendRetestSessionEvents(sessionId, nextEvents);
          };
          const mergeFileLogs = (logs?: string[], logCount?: number) => {
            const nextLogs = logs ?? [];
            if (!nextLogs.length) {
              fileLogCount = Math.max(fileLogCount, typeof logCount === 'number' ? logCount : fileLogCount);
              return;
            }
            allLogs.push(...nextLogs);
            fileLogCount = Math.max(fileLogCount + nextLogs.length, typeof logCount === 'number' ? logCount : fileLogCount + nextLogs.length);
            syncSession({ log: joinLogs(allLogs) });
          };

          const runOneContextSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? latestSession;
          const startResult = await callBackend<RetestRunOneStartResponse>('doc.retest.run_one.start', {
            source_file: sourceFile,
            session_id: sessionId,
            round_id: fileRoundId,
            source_file_name: fileLabel,
            frontend_context: buildAgentFrontendContext(runOneContextSession),
          });
          if (!isCurrentRun()) return false;
          currentRunOneTaskRef.current = startResult.task_id || null;
          mergeFileLogs(startResult.logs, startResult.log_count);
          appendNewTraceEvents(startResult.trace_events, startResult.trace_event_count);
          if (!isCurrentRun()) return false;
          if (shouldStopCurrentRun() || startResult.stopped) {
            return await stopForUser(index, startResult.task_id);
          }
          if (startResult.blocked_by_ai_config) {
            stopForAiConfig(index, startResult);
            return false;
          }
          if (!startResult.success || !startResult.task_id) {
            throw new Error(startResult.message || '单个通报复测任务启动失败');
          }

          let runResult: RetestRunOneStatusResponse | RetestRunOneStartResponse = startResult;
          while (true) {
            await wait(650);
            if (!isCurrentRun()) return false;
            if (shouldStopCurrentRun()) {
              return await stopForUser(index, startResult.task_id);
            }
            const statusResult = await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.status', {
              task_id: startResult.task_id,
              log_offset: fileLogCount,
              trace_event_offset: fileTraceEventCount,
            });
            if (!isCurrentRun()) return false;
            runResult = statusResult;
            mergeFileLogs(statusResult.logs, statusResult.log_count);
            appendNewTraceEvents(statusResult.trace_events, statusResult.trace_event_count);
            const streamedProgress = Math.min(98, Math.round(((index + ((statusResult.progress ?? 0) / 100)) / Math.max(1, sourceFiles.length)) * 100));
            syncSession({ progress: streamedProgress, status: statusResult.message || nextStatus, isRunning: true });
            if (statusResult.stopped) {
              return await stopForUser(index, startResult.task_id);
            }
            if (statusResult.done) break;
          }
          currentRunOneTaskRef.current = null;
          if (!isCurrentRun()) return false;
          if (shouldStopCurrentRun() || runResult.stopped) {
            return await stopForUser(index, startResult.task_id);
          }
          if (runResult.blocked_by_ai_config) {
            stopForAiConfig(index, runResult);
            return false;
          }
          if (!runResult.success) {
            throw new Error(runResult.message || '单个通报复测失败');
          }

          const summary = repairRetestText(runResult.summary || `${fileLabel}\n复测结果为空`);
          summaries.push(summary);
          syncSession({ resultText: summary, latestResultData: runResult.result_data ?? null, log: joinLogs(allLogs) });

          let reportResult: RetestGenerateReportsResponse | undefined;
          if (shouldGenerateReports) {
            const reportStatus = `正在截图并写入报告 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
            syncSession({ status: reportStatus });
            pushAgentEvent(sessionId, '报告生成', '复测结果已生成，正在整理说明文字和证据截图并写入报告模板。', 'info', { action: mode, roundId: fileRoundId });
            reportResult = await callBackend<RetestGenerateReportsResponse>('doc.retest.generate_reports_with_screenshot', {
              target_dir: trimmedTargetDir,
              source_files: [sourceFile],
              summary,
              result_data: runResult.result_data ?? null,
            });
            if (!isCurrentRun()) return false;
            allLogs.push(...(reportResult.logs ?? []));
            reports.push(...(reportResult.reports ?? []));
            if (!reportResult.success) {
              failedCount += Math.max(1, reportResult.failures?.length ?? 0);
              const reportFailureText = repairRetestText(reportResult.message || `${fileLabel} 报告生成失败`);
              allLogs.push(reportFailureText);
              appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '报告生成失败', reportFailureText, 'error', { metadata: { roundId: fileRoundId } }));
            } else {
              const reportArtifactText = reportResult.reports?.length ? formatPathList(reportResult.reports) : '报告生成命令已完成。';
              appendRetestSessionEvent(sessionId, makeRetestSessionEvent('artifact', '报告生成完成', reportArtifactText, 'ok', { metadata: { roundId: fileRoundId, reports: reportResult.reports ?? [] } }));
            }
          }
          if (!isCurrentRun()) return false;
          if (shouldStopCurrentRun()) {
            return await stopForUser(index, null);
          }

          const completionItem = buildCompletionItem(sourceFile, runResult, reportResult);
          completionItems.push(completionItem);
          pushAgentEvent(
            sessionId,
            '复测结果',
            formatRetestResultMessage(fileLabel, runResult, completionItem, reportResult),
            completionItem.status === 'risk' ? 'warn' : completionItem.status === 'failed' ? 'error' : 'ok',
            { action: mode, roundId: fileRoundId, fixStatus: completionItem.status === 'risk' ? 'risk' : completionItem.status === 'failed' ? 'failed' : 'clean' },
          );
          syncSession({
            resultText: reportResult?.reports?.length ? `${summary}\n\n生成报告:\n${formatPathList(reportResult.reports)}` : summary,
            lastReportPath: reports[0] ?? latestSession.lastReportPath ?? trimmedTargetDir,
            log: joinLogs(allLogs),
            latestResultData: runResult.result_data ?? null,
            resumeState: buildResumeState(index + 1, false),
          });
        } catch (itemError) {
          currentRunOneTaskRef.current = null;
          if (!isCurrentRun()) return false;
          if (shouldStopCurrentRun()) {
            return await stopForUser(index, null);
          }
          const reason = repairRetestText(itemError instanceof Error ? itemError.message : String(itemError));
          if (isAiRuntimeFailureMessage(reason)) {
            stopForAiConfig(index, {
              success: false,
              message: reason,
              blocked_stage: 'execution',
              blocked_title: '模型调用失败',
            } as RetestRunOneResponse);
            return false;
          }
          failedCount += 1;
          allLogs.push(`${fileLabel} 处理失败: ${reason}`);
          completionItems.push(buildCompletionItem(sourceFile, undefined, undefined, reason));
          appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '复测错误', `${fileLabel} 处理失败：${reason}`, 'error', { metadata: { action: mode, roundId: fileRoundId } }));
          syncSession({ log: joinLogs(allLogs) });
        }

        const completedProgress = Math.round(((index + 1) / Math.max(1, sourceFiles.length)) * 100);
        syncSession({ progress: completedProgress, resumeState: buildResumeState(index + 1, false) });
      }

      const finalStatus = shouldGenerateReports
        ? `复测完成：处理 ${sourceFiles.length} 份文档，生成 ${reports.length} 份报告${failedCount ? `，失败 ${failedCount} 份` : ''}`
        : `复测完成：处理 ${sourceFiles.length} 份文档，未生成报告${failedCount ? `，失败 ${failedCount} 份` : ''}`;
      const completionOverview = formatCompletionOverview(completionItems);
      const finalResultText = [
        completionOverview,
        summaries.length ? '\n详细复测摘要:' : '',
        summaries.join('\n\n'),
        shouldGenerateReports && reports.length ? `\n生成报告:\n${formatPathList(reports)}` : '',
      ].filter(Boolean).join('\n');
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('artifact', '复测结论总览', completionOverview, failedCount ? 'warn' : 'ok', {
        metadata: {
          phase: 'completion_summary',
          summaryTitle: '复测结论总览',
          completionItems,
          fixStatus: completionItems.some((item) => item.status === 'risk') ? 'risk' : (failedCount ? 'failed' : 'clean'),
          evidenceLevel: 'summary',
          roundId: roundPrefix,
          generateReports: shouldGenerateReports,
        },
      }));
      syncSession({
        status: finalStatus,
        lastReportPath: reports[0] ?? latestSession.lastReportPath ?? trimmedTargetDir,
        resultText: finalResultText,
        log: joinLogs(allLogs),
        progress: 100,
        isRunning: false,
        resumeState: null,
      });
      pushAgentEvent(sessionId, '会话完成', finalStatus, failedCount ? 'warn' : 'ok', { action: mode, roundId: roundPrefix });
      return true;
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      const failedStatus = `复测失败: ${reason}`;
      allLogs.push(failedStatus);
      syncSession({ progress: 0, status: failedStatus, log: joinLogs(allLogs), isRunning: false });
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '会话错误', `复测失败：${reason}`, 'error', { metadata: { action: mode, roundId: roundPrefix } }));
      refreshStore();
      return false;
    } finally {
      if (!isCurrentRun()) return false;
      clearRuntimeSessionIfMatches(sessionId);
      currentRunOneTaskRef.current = null;
      patchRetestSession(sessionId, { isRunning: false });
      markAgentRunBusy(sessionId, false);
      refreshStore();
    }
  };

  const removeSession = (session: RetestSessionDraft) => {
    const title = session.sessionTitle || '会话';
    if (!window.confirm(`删除会话“${title}”？`)) return;
    deleteRetestSession(session.sessionId);
    refreshStore();
  };

  const slashCommandDisabledReason = (command: RetestSlashCommand) => {
    if (activeSessionLocked) return '请先停止或等待当前任务结束';
    if (!activeSession && command.id !== 'compact_help') return '当前没有会话';
    if (!sessions.length && command.id === 'compact_all') return '当前没有会话';
    return '';
  };

  const completeSlashCommand = (command: RetestSlashCommand | undefined) => {
    if (!command) return;
    setAgentInput(command.completion);
    setSlashMenuOpen(false);
    setSlashSelection(0);
  };

  const appendCompactHelp = (sessionId: string) => {
    appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
      'status',
      '/compact 命令说明',
      [
        '`/compact`：压缩当前会话。先用本地结构化事实保住断点、已完成文件和报告路径，再调用模型整理语义记忆。',
        '`/compact all`：批量瘦身所有本地会话，并对当前会话做 AI 语义压缩。',
        '如果旧会话原始动态已经丢失，模型也只能根据现存事件、日志、结果和断点重建记忆，不能凭空还原不存在的证据。',
      ].join('\n'),
      'info',
      { metadata: { phase: 'slash_command_help', command: '/compact help' } },
    ));
    refreshStore();
  };

  const applyAiCompactMemory = async (sessionId: string, previewResult: RetestSessionCompactResult, commandLabel = '/compact') => {
    const initialSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId);
    if (!initialSession) return null;
    const toolCallId = `slash-compact-ai:${sessionId}:${Date.now().toString(36)}`;
    const startedAt = Date.now();
    const initialFrontendContext = buildAgentFrontendContext(initialSession);
    const compactionFactMetadata = {
      progressEvidence: initialFrontendContext.progressEvidence,
      resumeState: initialFrontendContext.session.resumeState,
      targetDir: initialFrontendContext.session.targetDir,
    };
    appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
      'tool_call',
      '正在自动压缩上下文',
      [
        '正在把当前完整会话交给模型生成语义记忆。',
        'AI 语义压缩成功前不会裁剪原会话；断点、已完成文件和报告路径仍以本地结构化事实为准。',
      ].join('\n'),
      'info',
      {
        tool: {
          toolId: 'doc.retest.session.compact',
          label: 'AI 语义压缩',
          status: 'running',
          target: initialSession.sessionTitle || initialSession.targetDir || sessionId,
          argsPreview: compactResultSummary(previewResult),
        },
        metadata: {
          phase: 'slash_command_compact_ai',
          command: commandLabel,
          toolCallId,
          ...compactionFactMetadata,
        },
      },
    ));
    patchRetestSession(sessionId, { status: '正在自动压缩上下文...', isRunning: true });
    refreshStore();
    try {
      const fullSessionForAi = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? initialSession;
      const aiResult = await callBackendWithTimeout<RetestSessionCompactAiResponse>(
        'doc.retest.session.compact',
        buildSessionCompactAiPayload(fullSessionForAi, previewResult),
        RETEST_COMPACTION_TIMEOUT_MS,
        '自动压缩上下文',
      );
      if (aiResult.success && aiResult.memory_markdown) {
        appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
          'tool_result',
          'AI 语义压缩完成',
          [
            compactResultSummary(previewResult),
            aiResult.brief ? `摘要: ${aiResult.brief}` : '',
            aiResult.warning ? `提示: ${aiResult.warning}` : '',
            aiResult.model ? `模型: ${aiResult.provider || 'AI'} / ${aiResult.model}` : '',
            `置信度: ${aiResult.confidence || 'medium'}`,
          ].filter(Boolean).join('\n'),
          aiResult.warning ? 'warn' : 'ok',
          {
            tool: {
              toolId: 'doc.retest.session.compact',
              label: 'AI 语义压缩',
              status: 'completed',
              target: fullSessionForAi.sessionTitle || fullSessionForAi.targetDir || sessionId,
              durationMs: Date.now() - startedAt,
              resultPreview: aiResult.brief || 'AI 语义记忆已生成。',
            },
            metadata: { phase: 'slash_command_compact_ai', command: commandLabel, aiCompacted: true, toolCallId, ...compactionFactMetadata },
          },
        ));
        const committedResult = commitCompactRetestSession(sessionId, aiResult.memory_markdown);
        patchRetestSession(sessionId, {
          status: '会话已压缩，AI 语义记忆已更新',
          isRunning: false,
        });
        refreshStore();
        return { ...aiResult, compactResult: committedResult ?? previewResult };
      }
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
        'tool_result',
        'AI 语义压缩未完成',
        [
          compactResultSummary(previewResult),
          `原因: ${aiResult.blocked_title || aiResult.message || '模型未返回有效记忆'}`,
          aiResult.failure_stage ? `阶段: ${aiResult.failure_stage}${aiResult.model_call_started === false ? '（尚未进入模型请求）' : aiResult.model_call_started ? '（已进入模型请求）' : ''}` : '',
          '原会话未裁剪，仍保留完整上下文；配置或网络恢复后可再次输入 /compact 重试。',
        ].filter(Boolean).join('\n'),
        'warn',
        {
          tool: {
            toolId: 'doc.retest.session.compact',
            label: 'AI 语义压缩',
            status: 'incomplete',
            target: fullSessionForAi.sessionTitle || fullSessionForAi.targetDir || sessionId,
            durationMs: Date.now() - startedAt,
            failureReason: [
              aiResult.blocked_title || aiResult.message || '模型未返回有效记忆',
              aiResult.failure_stage ? `阶段: ${aiResult.failure_stage}` : '',
            ].filter(Boolean).join('；'),
          },
          metadata: { phase: 'slash_command_compact_ai', command: commandLabel, aiCompacted: false, toolCallId, ...compactionFactMetadata },
        },
      ));
      patchRetestSession(sessionId, { status: 'AI 语义压缩未完成，原会话未裁剪', isRunning: false });
      refreshStore();
      return aiResult;
    } catch (error) {
      const latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? initialSession;
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
        'tool_result',
        'AI 语义压缩未完成',
        [
          compactResultSummary(previewResult),
          `原因: ${errorMessage(error)}`,
          '原会话未裁剪，仍保留完整上下文；稍后可再次输入 /compact。',
        ].join('\n'),
        'warn',
        {
          tool: {
            toolId: 'doc.retest.session.compact',
            label: 'AI 语义压缩',
            status: 'incomplete',
            target: latestSession.sessionTitle || latestSession.targetDir || sessionId,
            durationMs: Date.now() - startedAt,
            failureReason: errorMessage(error),
          },
          metadata: { phase: 'slash_command_compact_ai', command: commandLabel, aiCompacted: false, toolCallId, ...compactionFactMetadata },
        },
      ));
      patchRetestSession(sessionId, { status: 'AI 语义压缩未完成，原会话未裁剪', isRunning: false });
      refreshStore();
      return null;
    }
  };

  const executeSlashCommand = async (command: RetestSlashCommand) => {
    const disabledReason = slashCommandDisabledReason(command);
    if (disabledReason) {
      const session = activeSession ?? createBlankSession();
      appendRetestSessionEvent(session.sessionId, makeRetestSessionEvent(
        'status',
        `${command.command} 暂不可用`,
        disabledReason,
        'warn',
        { metadata: { phase: 'slash_command_disabled', command: command.command } },
      ));
      refreshStore();
      return true;
    }

    if (command.id === 'compact_help') {
      const session = activeSession ?? createBlankSession();
      appendCompactHelp(session.sessionId);
      return true;
    }

    const session = activeSession;
    if (!session) return true;
    const sessionId = session.sessionId;
    setActiveRetestSession(sessionId);
    setActiveTab('conversation');
    markAgentBusy(sessionId, true);
    try {
      if (command.id === 'compact_all') {
        const allResult = compactAllRetestSessions(sessionId);
        appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
          'status',
          '其他会话本地压缩完成',
          [
            compactAllResultSummary(allResult),
            '当前会话会先完成 AI 语义压缩，成功后再提交裁剪。',
          ].join('\n'),
          'ok',
          { metadata: { phase: 'slash_command_compact_all', command: command.command } },
        ));
        refreshStore();
        const currentResult = previewCompactRetestSession(sessionId);
        if (currentResult) await applyAiCompactMemory(sessionId, currentResult, command.command);
        return true;
      }

      const result = previewCompactRetestSession(sessionId);
      if (!result) {
        appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
          'error',
          '会话压缩失败',
          '没有找到当前会话，无法执行 /compact。',
          'error',
          { metadata: { phase: 'slash_command_compact', command: command.command } },
        ));
        refreshStore();
        return true;
      }
      appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
        'status',
        '本地事实压缩预览完成',
        [
          compactResultSummary(result),
          '正在自动压缩上下文；成功前不会裁剪原会话。',
        ].join('\n'),
        'info',
        { metadata: { phase: 'slash_command_compact_local', command: command.command } },
      ));
      refreshStore();
      await applyAiCompactMemory(sessionId, result, command.command);
      return true;
    } finally {
      markAgentBusy(sessionId, false);
      refreshStore();
    }
  };

  const sendAgentMessage = async (message: string, clearInput = false) => {
    const question = message.trim();
    if (!question) return;

    const slashCommand = exactSlashCommand(question);
    if (slashCommand) {
      if (clearInput) setAgentInput('');
      setSlashMenuOpen(false);
      await executeSlashCommand(slashCommand);
      return;
    }

    const initialSession = activeSession ?? createBlankSession();
    const session = readRetestSessionStore().sessions.find((item) => item.sessionId === initialSession.sessionId) ?? initialSession;
    const sessionId = session.sessionId;
    if (isSessionRuntimeBusy(sessionId)) {
      if (!session.isRunning && hasContinueCue(session)) {
        releaseSessionRuntimeBusy(sessionId);
      } else {
        return;
      }
    }
    if (session.isRunning && !hasContinueCue(session)) return;
    const userEvent = makeRetestSessionEvent('chat', '你', question, 'info', { metadata: { role: 'user' } });
    appendRetestSessionEvent(sessionId, userEvent);
    const sessionWithUser = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? session;
    if (clearInput) setAgentInput('');
    markAgentBusy(sessionId, true);
    // 用户主动发消息：无论之前是否在向上翻看历史，都强制贴底并滚到最新，
    // 这样自己发出的消息和 Agent 的回复一定可见。
    stickToBottomRef.current = true;
    requestAnimationFrame(() => {
      const target = threadRef.current;
      if (target) target.scrollTop = target.scrollHeight;
    });
    setActiveRetestSession(sessionId);
    setActiveTab('conversation');
    window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, sessionId);
    patchRetestSession(sessionId, {
      isRunning: true,
      status: isContinueInstruction(question) ? 'Agent 正在结合上下文继续...' : 'Agent 正在处理你的消息...',
      generateReports: sessionWantsGeneratedReports(sessionWithUser, sessionWithUser.resumeState),
      resumeState: session.resumeState ? { ...session.resumeState, canContinue: false, generateReports: sessionWantsGeneratedReports(sessionWithUser, sessionWithUser.resumeState) } : null,
    });
    refreshStore();

    try {
      const contextSession = sessionWithUser;
      const useHybridAgent = agentMode === 'hybrid'
        ? true
        : agentMode === 'retest'
          ? false
          : shouldUseHybridAgentMessage(question, contextSession);
      const messagePayload: Record<string, unknown> = {
        session_id: sessionId,
        message: question,
        target_dir: agentWorkspaceTargetDir(contextSession),
        generate_reports: sessionWantsGeneratedReports(contextSession, contextSession.resumeState),
        frontend_context: buildAgentFrontendContext(contextSession),
        force_resume: isContinueInstruction(question) && hasContinueCue(contextSession),
      };
      if (useHybridAgent) messagePayload.auto_approve = autoApproveBySession[sessionId] ?? true;
      const result = await callBackendWithTimeout<RetestAgentResponse>(useHybridAgent ? 'doc.agent.message' : 'doc.retest.agent.message', messagePayload, 45000);
      if (useHybridAgent && result.final_message && !result.message) result.message = result.final_message;
      applyAgentMessageResult(sessionId, result, contextSession);
      if (useHybridAgent && (result.operation_id || result.auto_approved)) {
        lastHybridStatusSyncRef.current[sessionId] = 0;
        void syncHybridAgentSessionStatus(sessionId);
      }
    } catch (error) {
      patchRetestSession(sessionId, { isRunning: false, status: `Agent 会话调用失败: ${errorMessage(error)}` });
      clearRuntimeSessionIfMatches(sessionId);
      appendRetestSessionEvent(
        sessionId,
        makeRetestSessionEvent('error', 'Agent 错误', `Agent 会话调用失败：${errorMessage(error)}`, 'error'),
      );
    } finally {
      markAgentBusy(sessionId, false);
      refreshStore();
    }
  };

  const askRetestAgent = async () => {
    if (slashMenuVisible) {
      completeSlashCommand(slashCommandOptions[slashSelection]);
      return;
    }
    await sendAgentMessage(agentInput, true);
  };

  const sendAgentInstruction = async (message: string) => {
    await sendAgentMessage(message);
  };

  return (
    <div className="retest-session-page">
      <aside className="retest-session-sidebar">
        <div className="retest-session-sidebar-head">
          <strong>会话</strong>
          <button type="button" className="retest-session-new" onClick={createBlankSession}>新建</button>
        </div>
        <div className="retest-session-list">
          {sessions.length ? sessions.map((session) => (
            <div
              key={session.sessionId}
              className={`retest-session-list-item${session.sessionId === activeSession?.sessionId ? ' active' : ''}`}
            >
              <button type="button" className="retest-session-select" onClick={() => selectSession(session.sessionId)}>
                <span className="retest-session-title">{session.sessionTitle || '会话'}</span>
                <span className="retest-session-meta">{sessionStateLabel(session)} · {formatSessionDate(session.updatedAt)}</span>
                <span className="retest-session-status">{session.status || '等待开始测试...'}</span>
              </button>
              <button type="button" className="retest-session-delete" onClick={() => removeSession(session)} title="删除会话">删除</button>
            </div>
          )) : <div className="retest-session-empty">还没有会话。可以点“新建”，也可以直接在右侧输入框发送消息自动创建。</div>}
        </div>
      </aside>

      <main className="retest-session-main">
        <div className="retest-session-main-head">
          <div>
            <h3>{activeSession?.sessionTitle || '会话'}</h3>
            <p>{activeSession?.status || '新建会话或直接发送消息，Agent 会在当前会话里回复，并在需要时调用工具。'}</p>
          </div>
          <div className="retest-session-head-actions">
            <div className={`retest-session-run-state${activeSessionLocked ? ' running' : ''}`}>
              <span />{activeSession ? sessionStateLabel(activeSession) : '空闲'}
            </div>
            {activeSession && activeSessionLocked ? (
              <button type="button" className="koi-button danger compact-button" onClick={() => void stopActiveSession()} disabled={stopBusy}>
                {stopBusy ? '停止中...' : '停止'}
              </button>
            ) : null}
          </div>
        </div>
        {showResumeBanner ? (
          <div className="retest-session-resume-banner">
            <div>
              <strong>{resumeCopy.title}</strong>
              <span>{resumeCopy.reason}</span>
            </div>
            <button type="button" className="koi-button primary compact-button" onClick={() => void resumeSessionThroughAgent(activeSession)} disabled={activeSessionBusy}>{resumeButtonLabel(activeSession)}</button>
          </div>
        ) : null}

        <div className="retest-session-context-row">
          <div><b>目标目录</b><span>{sessionSummary.filesText}</span></div>
          <div><b>工具调用</b><span>{eventStats.tools} 个</span></div>
          <div><b>思考 / 错误</b><span>{eventStats.thoughts} / {eventStats.errors}</span></div>
        </div>

        <div className="retest-agent-mode-switch" aria-label="Agent mode">
          {AGENT_MODE_OPTIONS.map((mode) => (
            <button
              key={mode.id}
              type="button"
              className={agentMode === mode.id ? 'active' : ''}
              onClick={() => setAgentMode(mode.id)}
              title={mode.description}
            >
              {mode.label}
            </button>
          ))}
          <label
            className={`retest-auto-approval-toggle${activeAutoApprove ? ' active' : ''}`}
            title="Auto-approve Hybrid Agent side-effect operations after sandbox checks. Retest confirmations are not affected."
          >
            <input
              type="checkbox"
              checked={activeAutoApprove}
              disabled={!activeSession}
              onChange={(event) => void setHybridAutoApproval(event.currentTarget.checked)}
            />
            <span>自动审批</span>
          </label>
          <span className="retest-operation-count">{activeOperations.length} operations</span>
        </div>

        <div className="retest-workbench-tabs">
          <button type="button" className={activeTab === 'conversation' ? 'active' : ''} onClick={() => setActiveTab('conversation')}>对话流</button>
          <button type="button" className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}>AI 动态</button>
          <button type="button" className={activeTab === 'logs' ? 'active' : ''} onClick={() => setActiveTab('logs')}>结果日志</button>
          <button type="button" className={activeTab === 'operations' ? 'active' : ''} onClick={() => setActiveTab('operations')}>Operations</button>
        </div>

        <section className="retest-workbench-panel">
          {activeTab === 'conversation' ? (
            <div className="retest-chat-flow" ref={threadRef}>
              {timelineRows.length ? timelineRows.map((row) => <TimelineRowView key={row.key} row={row} />) : (
                <div className="modal-message">会话启动后，这里会按时间顺序逐条显示你的消息、Agent 回复、思考、工具调用与产物。</div>
              )}
            </div>
          ) : null}

          {activeTab === 'activity' ? (
            <div className="retest-activity-panel">
              <div className="retest-activity-toolbar">
                {ACTIVITY_FILTERS.map((filter) => (
                  <button key={filter.id} type="button" className={activityFilter === filter.id ? 'active' : ''} onClick={() => setActivityFilter(filter.id)}>{filter.label}</button>
                ))}
              </div>
              <div className="retest-activity-list" ref={threadRef}>
                {filteredActivityEntries.length ? filteredActivityEntries.map((entry) => <ActivityEntryRow key={entry.id} entry={entry} />) : (
                  <div className="modal-message">暂无匹配的执行事件。</div>
                )}
              </div>
            </div>
          ) : null}

          {activeTab === 'operations' ? (
            <div className="retest-operation-list">
              {activeOperations.length ? activeOperations.map((operation) => {
                const id = operationId(operation);
                const running = operationIsRunning(operation);
                const rawOutput = repairRetestText(operation.raw_output || operation.result_preview || operation.error || '');
                return (
                  <details key={id} className={`retest-operation-card ${repairRetestText(operation.status || 'pending')}`} open={running}>
                    <summary>
                      <span className={`retest-operation-dot${running ? ' running' : ''}`} />
                      <strong>{repairRetestText(operation.tool_name || 'operation')}</strong>
                      <em>{repairRetestText(operation.status || 'pending')}</em>
                      {running ? (
                        <button
                          type="button"
                          className="koi-button danger compact-button"
                          onClick={(event) => {
                            event.preventDefault();
                            void stopHybridOperation(id);
                          }}
                          disabled={operationBusyIds.includes(id)}
                        >
                          {operationBusyIds.includes(id) ? 'Stopping' : 'Stop'}
                        </button>
                      ) : null}
                    </summary>
                    <div className="retest-operation-body">
                      <div><b>Operation</b><code>{id}</code></div>
                      {operation.approval_id ? <div><b>Approval</b><code>{operation.approval_id}</code></div> : null}
                      {operation.cwd ? <div><b>CWD</b><code>{repairRetestText(operation.cwd)}</code></div> : null}
                      {operation.risk ? <div><b>Risk</b><span>{repairRetestText(operation.risk)}</span></div> : null}
                      {operation.sandbox_summary ? <div><b>Sandbox</b><span>{repairRetestText(operation.sandbox_summary)}</span></div> : null}
                      {operation.preview_artifact_id ? <div><b>Preview</b><code>{operation.preview_artifact_id}</code></div> : null}
                      {operation.artifact_ids?.length ? <div><b>Artifacts</b><code>{operation.artifact_ids.join(', ')}</code></div> : null}
                      {operation.exit_code !== undefined && operation.exit_code !== null ? <div><b>Exit</b><span>{operation.exit_code}</span></div> : null}
                      {operation.duration_ms ? <div><b>Duration</b><span>{operation.duration_ms} ms</span></div> : null}
                      {operation.detail ? <pre>{repairRetestText(operation.detail)}</pre> : null}
                      {rawOutput ? <pre>{rawOutput}</pre> : null}
                    </div>
                  </details>
                );
              }) : (
                <div className="modal-message">No Hybrid Agent operations yet.</div>
              )}
            </div>
          ) : null}

          {activeTab === 'logs' ? (
            <div className="retest-logs-grid">
              <div className="retest-agent-side-panel">
                <div className="retest-panel-title"><strong>复测结果</strong><span>同步自一键复测页</span></div>
                <pre className="retest-session-result-preview">{sessionSummary.resultText}</pre>
              </div>
              <div className="retest-agent-side-panel">
                <div className="retest-panel-title"><strong>详细日志</strong><span>最近 120 行</span></div>
                <pre className="retest-session-log-preview">{sessionSummary.logText}</pre>
              </div>
            </div>
          ) : null}
        </section>

        <div className="retest-agent-chat-row">
          <div className="retest-agent-chat-input-wrap">
            {slashMenuVisible ? (
              <div className="retest-command-menu" role="listbox" aria-label="AI 测试命令">
                {slashCommandOptions.map((command, index) => {
                  const disabledReason = slashCommandDisabledReason(command);
                  const active = index === slashSelection;
                  return (
                    <button
                      key={command.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      className={`retest-command-item${active ? ' active' : ''}${disabledReason ? ' disabled' : ''}`}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        completeSlashCommand(command);
                      }}
                      onMouseEnter={() => setSlashSelection(index)}
                    >
                      <span className="retest-command-name">{command.command}</span>
                      <span className="retest-command-copy">
                        <strong>{command.title}</strong>
                        <em>{disabledReason || command.description}</em>
                      </span>
                      {disabledReason ? <span className="retest-command-state">不可用</span> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
            <textarea
              className="koi-input retest-agent-chat-input"
              placeholder="直接告诉 Agent：继续、重新测一遍、下载工具、生成报告，或输入 / 查看命令。"
              value={agentInput}
              onFocus={() => {
                if (isSlashCommandInput(agentInput)) setSlashMenuOpen(true);
              }}
              onChange={(event) => {
                const value = event.target.value;
                setAgentInput(value);
                setSlashMenuOpen(isSlashCommandInput(value));
                setSlashSelection(0);
              }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (slashMenuVisible) {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    setSlashSelection((value) => (value + 1) % slashCommandOptions.length);
                    return;
                  }
                  if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    setSlashSelection((value) => (value - 1 + slashCommandOptions.length) % slashCommandOptions.length);
                    return;
                  }
                  if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
                    event.preventDefault();
                    completeSlashCommand(slashCommandOptions[slashSelection]);
                    return;
                  }
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    setSlashMenuOpen(false);
                    return;
                  }
                }
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void askRetestAgent();
                }
              }}
            />
          </div>
          <button type="button" className="koi-button primary compact-button" onClick={() => void askRetestAgent()} disabled={activeSessionBusy || !agentInput.trim()}>{activeAgentBusy ? '发送中' : '发送'}</button>
        </div>
      </main>

      {confirmRequest ? (
        <div className="retest-confirm-overlay" role="dialog" aria-modal="true">
          <div className="retest-confirm-card">
            <div className="retest-confirm-head">
              <span className="retest-confirm-icon">⚠️</span>
              <strong>需要你确认执行</strong>
            </div>
            <p className="retest-confirm-op">{confirmRequest.operation}</p>
            <p className="retest-confirm-detail">{confirmRequest.detail}</p>
            {confirmRequest.isAgentApproval ? (
              <div className="retest-confirm-meta-grid">
                {confirmRequest.operationId ? <div><b>Operation</b><code>{confirmRequest.operationId}</code></div> : null}
                {confirmRequest.cwd ? <div><b>CWD</b><code>{confirmRequest.cwd}</code></div> : null}
                {confirmRequest.risk ? <div><b>Risk</b><span>{confirmRequest.risk}</span></div> : null}
                {confirmRequest.sandboxPolicySummary ? <div><b>Sandbox</b><span>{confirmRequest.sandboxPolicySummary}</span></div> : null}
                {confirmRequest.previewArtifactId ? <div><b>Preview</b><code>{confirmRequest.previewArtifactId}</code></div> : null}
              </div>
            ) : null}
            {confirmRequest.matched ? (
              <div className="retest-confirm-matched">
                <span>命中代码：</span>
                <code>{confirmRequest.matched}</code>
              </div>
            ) : null}
            {confirmRequest.script ? (
              <pre className="retest-confirm-script">{confirmRequest.script}</pre>
            ) : null}
            <p className="retest-confirm-note">
              批准：允许 Agent 继续该动作。拒绝：不执行该动作，并让 Agent 改写方案继续。
            </p>
            <div className="retest-confirm-actions">
              <button
                type="button"
                className="koi-button danger compact-button"
                onClick={() => void respondConfirmation('approve')}
                disabled={confirmBusy}
              >
                {confirmBusy ? '提交中...' : '批准执行'}
              </button>
              <button
                type="button"
                className="koi-button primary compact-button"
                onClick={() => void respondConfirmation('reject')}
                disabled={confirmBusy}
              >
                拒绝执行
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
