import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { callBackend } from '../../lib/backend';
import {
  RETEST_RUNTIME_SESSION_KEY,
  RETEST_RERUN_REQUEST_KEY,
  RETEST_RESUME_REQUEST_KEY,
  RETEST_SESSION_CHANGED_EVENT,
  appendRetestSessionEvent,
  appendRetestSessionEvents,
  createRetestSession,
  deleteRetestSession,
  makeRetestSessionEvent,
  patchRetestSession,
  readRetestSessionStore,
  setActiveRetestSession,
  type RetestResumeState,
  type RetestSessionDraft,
  type RetestSessionEvent,
  type RetestSessionStore,
  type RetestToolTrace,
} from './retestSessionStore';

type RetestAgentResponse = {
  success: boolean;
  message: string;
  session_id?: string;
  running?: boolean;
  blocked?: boolean;
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
  progress?: number;
  status?: string;
  generate_reports?: boolean;
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
  logs?: string[];
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

type WorkbenchTab = 'conversation' | 'activity' | 'logs';
type ActivityFilter = 'all' | 'thought' | 'system' | 'tool' | 'error' | 'artifact';

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

const ACTIVITY_FILTERS: Array<{ id: ActivityFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'thought', label: '思考' },
  { id: 'system', label: '系统' },
  { id: 'tool', label: '工具' },
  { id: 'error', label: '错误' },
  { id: 'artifact', label: '产物' },
];

function formatSessionDate(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function splitLogLines(log?: string) {
  return (log || '').split('\n').map((line) => line.trim()).filter(Boolean);
}

function getFileName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
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
  return (logs ?? []).filter(Boolean).join('\n');
}

function formatPathList(paths?: string[]) {
  return (paths ?? []).map((path, index) => `${index + 1}. ${path}`).join('\n');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is Record<string, unknown> => Boolean(item)) : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
}

function asFiniteNumber(value: unknown, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

const MODEL_REPRODUCED_VALUES = new Set(['reproduced', 'reproducible', 'unfixed', 'not_fixed', 'risk', 'vulnerable', '可复现', '未修复']);
const MODEL_CLEAN_VALUES = new Set(['not_reproduced', 'not reproducible', 'fixed', 'clean', 'pass', 'passed', '已修复', '复测通过', '不可复现']);

function normalizeModelVerdict(value: unknown): '' | 'reproduced' | 'not_reproduced' {
  const raw = String(value || '').trim().toLowerCase();
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
      const type = String(vuln.type || '证据');
      const severity = String(vuln.severity || 'info');
      const detail = String(vuln.detail || vuln.evidence || '').trim();
      if (vuln.tool_unavailable || type.includes('不可用')) return;
      const line = `[${severity}] ${type}${detail ? `：${detail}` : ''}`;
      if (isRiskVulnerability(vuln)) riskLines.push(line);
      else if (severity.toLowerCase() !== 'info' || type.includes('未复现') || type.includes('不可达') || type.includes('已受限')) infoLines.push(line);
    });
    if (!asRecordArray(result.vulnerabilities).length && result.note) {
      infoLines.push(String(result.note));
    }
    const meta = asRecord(result.request_meta);
    if (meta?.status_code) {
      infoLines.push(`主请求：HTTP ${meta.status_code}${meta.final_url ? `，final=${meta.final_url}` : ''}`);
    } else if (meta?.error || result.target_unreachable) {
      infoLines.push(`目标不可达：${String(meta?.error || result.error || '当前无法访问')}`);
    }
  });

  const scanResult = asRecord(resultData?.scan_result);
  const context = asRecord(scanResult?.retest_context);
  asStringArray(context?.agent_recommended_checks).forEach((tool) => tools.add(tool));

  return {
    evidence: (riskLines.length ? riskLines : infoLines).slice(0, 6).join('\n') || String(resultData?.reason || '暂无可展示证据'),
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

  const reason = failureReason
    || (reportFailed ? reportResult?.message : '')
    || String(aiJudgement?.reason || '')
    || String(resultData?.reason || '')
    || (missingModelVerdict ? '模型未给出 reproduced/not_reproduced 判定，未由工具结果兜底。' : '')
    || (!urls.length ? '未提取到可用 URL' : '')
    || (!retestResults.length ? '未形成可复测结果' : '');

  return {
    sourceFile,
    sourceFileName: getFileName(sourceFile),
    status,
    statusLabel: missingModelVerdict ? '模型未给出判定' : completionStatusLabel(status),
    evidence: extracted.evidence,
    reason,
    reportPaths: reportResult?.reports ?? [],
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
  const modelConclusion = String(aiJudgement?.conclusion || '').trim();
  const urls = asStringArray(resultData?.urls);
  const lines = [
    `文件: ${fileLabel}`,
    `复测结果: ${completionItem.statusLabel}`,
    `模型判定: ${finalVerdict || '模型未给出判定'}${modelConclusion ? ` / ${modelConclusion}` : ''}`,
  ];
  if (aiJudgement?.reason || completionItem.reason) {
    lines.push(`理由: ${String(aiJudgement?.reason || completionItem.reason)}`);
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
  const reason = blocked?.message || 'AI 测试已暂停，请处理后继续测试。';
  const title = blocked?.blocked_title || '';
  const stage = blocked?.blocked_stage || '';
  if (title.includes('超时') || reason.includes('超时')) {
    return { title: '模型响应超时', status: `模型响应超时: ${reason}`, instruction: '网络或模型恢复后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  if (title.includes('限流') || reason.includes('HTTP 429') || reason.includes('限流') || reason.includes('并发')) {
    return { title: '模型并发/限流', status: `模型并发/限流: ${reason}`, instruction: '稍后在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  if (stage === 'config' || title.includes('配置') || reason.includes('配置') || reason.includes('未启用')) {
    return { title: '待配置 AI', status: `待配置 AI: ${reason}`, instruction: '配置完成后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
  }
  return { title: title || 'AI 测试暂停', status: `${title || 'AI 测试暂停'}: ${reason}`, instruction: '处理暂停原因后，在当前测试工作台输入“继续”，我会从当前通报继续。' };
}

function asCompletionItems(value: unknown): RetestCompletionItem[] {
  return asRecordArray(value).map((item) => {
    const statusValue = String(item.status || 'clean');
    const status: RetestCompletionStatus = statusValue === 'risk' || statusValue === 'failed' || statusValue === 'manual' ? statusValue : 'clean';
    return {
      sourceFile: String(item.sourceFile || ''),
      sourceFileName: String(item.sourceFileName || getFileName(String(item.sourceFile || ''))),
      status,
      statusLabel: String(item.statusLabel || completionStatusLabel(status)),
      evidence: String(item.evidence || ''),
      reason: item.reason ? String(item.reason) : undefined,
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
    filesText: session.targetDir || '未选择目录',
    resultText: session.resultText || '暂无复测结果',
    logText: logLines.length ? logLines.slice(-120).join('\n') : '暂无日志',
  };
}

function resumeBannerCopy(session: RetestSessionDraft | null) {
  const state = session?.resumeState;
  const reason = state?.blockedReason || session?.status || '处理暂停原因后可从断点继续测试。';
  const title = state?.blockedTitle || '';
  const stage = state?.blockedStage || '';
  if (title.includes('超时') || reason.includes('超时')) {
    return { title: '模型响应超时，待继续', reason };
  }
  if (title.includes('限流') || reason.includes('HTTP 429') || reason.includes('限流') || reason.includes('并发')) {
    return { title: '模型并发/限流，待继续', reason };
  }
  if (stage === 'config' || title.includes('配置') || reason.includes('配置') || reason.includes('未启用')) {
    return { title: '待配置 AI 后继续', reason };
  }
  return { title: title ? `${title}，待继续` : 'AI 测试暂停，待继续', reason };
}

function isContinueInstruction(message: string) {
  const text = message.trim().toLowerCase();
  return text === '继续' || text === '继续测试' || text === '继续执行' || text === 'resume' || text === 'continue'
    || text.includes('继续复测') || text.includes('从断点继续');
}

function asMetadata(event: RetestSessionEvent) {
  return event.metadata && typeof event.metadata === 'object' ? event.metadata : {};
}

function metadataString(event: RetestSessionEvent, key: string) {
  const value = asMetadata(event)[key];
  return typeof value === 'string' ? value : '';
}

function eventRole(event: RetestSessionEvent): RetestConversationTurn['role'] | '' {
  const role = metadataString(event, 'role');
  if (role === 'user' || role === 'system' || role === 'agent') return role;
  return '';
}

function sourceLabel(event: RetestSessionEvent) {
  return metadataString(event, 'sourceFileName') || event.sourceFile?.split(/[\\/]/).filter(Boolean).pop() || '';
}

function roundKey(event: RetestSessionEvent) {
  return metadataString(event, 'roundId') || metadataString(event, 'turnId') || sourceLabel(event) || event.sourceFile || 'session';
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
  const phase = typeof metadata.phase === 'string' ? metadata.phase : '';
  return ['model-output', roundKey(event), event.sourceFile || '', phase].join(':');
}

function toolMergeKey(event: RetestSessionEvent) {
  const metadata = asMetadata(event);
  const toolCallId = metadata.toolCallId || metadata.tool_call_id;
  if (typeof toolCallId === 'string' && toolCallId.trim()) return `tool-call:${toolCallId.trim()}`;
  const tool = event.tool;
  return [
    roundKey(event),
    tool?.toolId || event.title,
    tool?.target || '',
    sourceLabel(event),
  ].join('|');
}

function normalizeToolTarget(value?: string) {
  return (value || '').trim().replace(/[\\/]+$/, '').toLowerCase();
}

function toolIdentityFromEvent(event: RetestSessionEvent) {
  return event.tool?.toolId || event.title || event.tool?.label || '';
}

function toolIdentityFromItem(item: ConversationTool | RetestActivityEntry) {
  return item.tool?.toolId || item.title || item.tool?.label || '';
}

function defaultToolStatus(event: RetestSessionEvent): RetestToolTrace['status'] | undefined {
  if (event.tool?.status) return event.tool.status;
  if (event.type === 'tool_result') return 'completed';
  if (event.type === 'tool_call') return 'running';
  return undefined;
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

function statusText(status?: RetestToolTrace['status']) {
  if (status === 'completed') return '完成';
  if (status === 'failed') return '失败';
  if (status === 'skipped') return '跳过';
  if (status === 'blocked') return '阻塞';
  return '运行中';
}

function toolRunPrefix(status?: RetestToolTrace['status']) {
  if (status === 'failed') return '运行失败';
  if (status === 'blocked') return '已暂停';
  if (status === 'skipped') return '已跳过';
  if (status === 'running' || !status) return '正在运行';
  return '已运行';
}

function toolObservationCount(tool: RetestToolTrace) {
  return Math.max(0, tool.observationCount ?? tool.findingCount ?? 0);
}

function sessionStateLabel(session: RetestSessionDraft) {
  if (session.isRunning) return '运行中';
  if (session.resumeState?.canContinue) {
    const status = String(session.status || session.resumeState.blockedReason || '');
    if (status.includes('停止')) return '已停止';
    return '已暂停';
  }
  const status = String(session.status || '');
  if (status.includes('完成')) return '完成';
  if (status.includes('停止')) return '已停止';
  return '空闲';
}

function compactToolMeta(tool: RetestToolTrace) {
  const observationCount = toolObservationCount(tool);
  const parts = [
    statusText(tool.status),
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
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
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
    const groupedChatKey = explicitRoundKey(event);
    if (event.type === 'chat' && role !== 'user' && role !== 'system' && groupedChatKey) {
      const turn = getGroupedTurn(event);
      turn.role = 'agent';
      if (turn.title === 'Agent 执行' && event.title) turn.title = event.title;
      if (event.timestamp) turn.timestamp = event.timestamp;
      if (sourceLabel(event)) turn.sourceFile = sourceLabel(event);
      if (event.content) {
        turn.contents.push(event.content);
        turn.items.push({ kind: 'content', key: event.id, content: event.content });
      }
      return;
    }

    if (event.type === 'chat' || role) {
      turns.push({
        id: event.id,
        role: role || 'agent',
        title: event.title || (role === 'user' ? '你' : 'Agent'),
        timestamp: event.timestamp,
        items: event.content ? [{ kind: 'content', key: event.id, content: event.content }] : [],
        contents: event.content ? [event.content] : [],
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
        title: event.tool?.label || event.title || event.tool?.toolId || '工具调用',
        timestamp: event.timestamp,
        sourceFile: sourceLabel(event),
        tone: event.tone || existing?.tone,
        tool: nextTool,
        content: event.tool?.resultPreview || event.content || existing?.content,
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
    if (event.content) {
      const content = `${event.title ? `${event.title}: ` : ''}${event.content}`;
      turn.contents.push(content);
      turn.items.push({ kind: 'content', key: event.id, content });
    } else if (event.title) {
      turn.contents.push(event.title);
      turn.items.push({ kind: 'content', key: event.id, content: event.title });
    }
  });

  return turns;
}

function buildActivityEntries(events: RetestSessionEvent[]): RetestActivityEntry[] {
  const entries: RetestActivityEntry[] = [];
  const toolIndexes = new Map<string, number>();

  events.forEach((event) => {
    const kind = eventKind(event);
    if (kind === 'tool') {
      const key = toolMergeKey(event);
      const existingIndex = resolveActivityToolIndex(entries, toolIndexes, event, key);
      const entry: RetestActivityEntry = {
        id: key,
        kind: 'tool',
        eventType: event.type,
        title: event.tool?.label || event.title || event.tool?.toolId || '工具调用',
        timestamp: event.timestamp,
        sourceFile: sourceLabel(event),
        tone: event.tone,
        content: event.tool?.resultPreview || event.content,
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
            title: event.title,
            timestamp: event.timestamp,
            sourceFile: sourceLabel(event),
            tone: event.tone,
            content: event.content,
            metadata: { ...asMetadata(event), streamKey: mergeKey },
          };
          return;
        }
        const metadata = { ...asMetadata(event), streamKey: mergeKey };
        entries.push({
          id: event.id,
          kind,
          eventType: event.type,
          title: event.title,
          timestamp: event.timestamp,
          sourceFile: sourceLabel(event),
          tone: event.tone,
          content: event.content,
          metadata,
        });
        return;
      }
    }
    entries.push({
      id: event.id,
      kind,
      eventType: event.type,
      title: event.title,
      timestamp: event.timestamp,
      sourceFile: sourceLabel(event),
      tone: event.tone,
      content: event.content,
      metadata: asMetadata(event),
    });
  });

  return entries;
}

function ChatText({ content }: { content: string }) {
  return <div className="retest-chat-text">{content}</div>;
}

// ---- 轻量 Markdown 渲染：零依赖、纯 React 元素、避免 dangerouslySetInnerHTML 的 XSS 风险 ----
function isSafeMarkdownUrl(url: string) {
  const trimmed = url.trim();
  return /^(https?:|mailto:)/i.test(trimmed) || trimmed.startsWith('/') || trimmed.startsWith('#');
}

const INLINE_MD_PATTERN = /(`[^`]+`)|(\*\*[^*]+\*\*|__[^_]+__)|(~~[^~]+~~)|(\*[^*\n]+\*|_[^_\n]+_)|(\[[^\]]+\]\([^)\s]+\))/;

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let remaining = text;
  let idx = 0;
  while (remaining) {
    const match = INLINE_MD_PATTERN.exec(remaining);
    if (!match) {
      nodes.push(remaining);
      break;
    }
    const start = match.index;
    if (start > 0) nodes.push(remaining.slice(0, start));
    const token = match[0];
    const key = `${keyPrefix}-i${idx++}`;
    if (token.startsWith('`')) {
      nodes.push(<code key={key} className="retest-md-code">{token.slice(1, -1)}</code>);
    } else if (token.startsWith('**') || token.startsWith('__')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('~~')) {
      nodes.push(<del key={key}>{token.slice(2, -2)}</del>);
    } else if (token.startsWith('[')) {
      const link = /\[([^\]]+)\]\(([^)\s]+)\)/.exec(token);
      if (link && isSafeMarkdownUrl(link[2])) {
        nodes.push(<a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">{link[1]}</a>);
      } else {
        nodes.push(token);
      }
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    remaining = remaining.slice(start + token.length);
  }
  return nodes;
}

function renderMarkdownBlocks(content: string): ReactNode[] {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let bk = 0;
  const isBlockStart = (line: string) =>
    /^```/.test(line) || /^(#{1,6})\s+/.test(line) || /^>\s?/.test(line) || /^\s*([-*+]|\d+\.)\s+/.test(line);
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^```(\w*)\s*$/.exec(line);
    if (fence) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { codeLines.push(lines[i]); i++; }
      i++;
      blocks.push(<pre key={`md-pre-${bk++}`} className="retest-md-pre"><code>{codeLines.join('\n')}</code></pre>);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(
        <div key={`md-h-${bk++}`} className={`retest-md-h retest-md-h${level}`}>
          {renderInlineMarkdown(heading[2], `md-h-${bk}`)}
        </div>,
      );
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(<hr key={`md-hr-${bk++}`} className="retest-md-hr" />);
      i++;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { quote.push(lines[i].replace(/^>\s?/, '')); i++; }
      blocks.push(
        <blockquote key={`md-bq-${bk++}`} className="retest-md-quote">
          {renderInlineMarkdown(quote.join(' '), `md-bq-${bk}`)}
        </blockquote>,
      );
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ''));
        i++;
      }
      const lis = items.map((it, liIdx) => <li key={`li-${liIdx}`}>{renderInlineMarkdown(it, `md-li-${bk}-${liIdx}`)}</li>);
      blocks.push(
        ordered
          ? <ol key={`md-ol-${bk++}`} className="retest-md-list">{lis}</ol>
          : <ul key={`md-ul-${bk++}`} className="retest-md-list">{lis}</ul>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) { para.push(lines[i]); i++; }
    const paraNodes: ReactNode[] = [];
    para.forEach((p, pIdx) => {
      if (pIdx > 0) paraNodes.push(<br key={`br-${bk}-${pIdx}`} />);
      renderInlineMarkdown(p, `md-p-${bk}-${pIdx}`).forEach((node) => paraNodes.push(node));
    });
    blocks.push(<p key={`md-p-${bk++}`} className="retest-md-p">{paraNodes}</p>);
  }
  return blocks;
}

function Markdown({ content }: { content: string }) {
  const text = String(content || '').trim();
  if (!text) return null;
  return <div className="retest-chat-text retest-markdown">{renderMarkdownBlocks(text)}</div>;
}

// 模型思考：默认折叠的小字块，summary 显示一行预览，可展开看全文。
function ThoughtBlock({ event }: { event: RetestSessionEvent }) {
  const text = (event.content || '').trim();
  const preview = text.replace(/\s+/g, ' ').slice(0, 56);
  return (
    <details className="retest-thought-fold">
      <summary>
        <span className="retest-thought-fold-icon" />
        <span className="retest-thought-fold-label">模型思考</span>
        <span className="retest-thought-fold-preview">{preview || '展开查看思考过程'}{text.length > 56 ? '…' : ''}</span>
        {event.timestamp ? <span className="retest-thought-fold-time">{event.timestamp}</span> : null}
      </summary>
      <div className="retest-thought-fold-body">{renderMarkdownBlocks(text || '暂无思考内容。')}</div>
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
  return typeof k === 'string' && k.trim() ? k.trim() : '';
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
    if (event.type === 'chat') {
      if (!(event.content || '').trim()) return; // 跳过空对话气泡
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
        if (!(event.content || '').trim()) return; // 空内容不渲染，避免空折叠条
        rows.push({ kind: 'thought', key: event.id, event });
        return;
      }
      // 流式预览 / 模型可见正文 → Agent 正在生成的正文气泡。
      if (streaming || isModelOutput) {
        const k = frontStreamKey(event);
        // 同 streamKey 已有权威 chat（被收尾升级过）→ 跳过残留的流式预览，避免重复。
        if (k && authoritativeKeys.has(k)) return;
        if (!(event.content || '').trim() && !streaming) return;
        rows.push({ kind: 'message', key: event.id, role: 'agent', event, live: streaming });
        return;
      }
      // 其它无标记的思考 → 折叠小字；空内容不渲染，避免出现空折叠条。
      if (!(event.content || '').trim()) return;
      rows.push({ kind: 'thought', key: event.id, event });
      return;
    }
    if (event.type === 'tool_call' || event.type === 'tool_result') {
      rows.push({
        kind: 'tool',
        key: event.id,
        tool: {
          key: event.id,
          title: event.tool?.label || event.title || event.tool?.toolId || '工具调用',
          timestamp: event.timestamp,
          sourceFile: sourceLabel(event),
          tone: event.tone,
          tool: mergeToolTrace(undefined, event),
          content: event.tool?.resultPreview || event.content,
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
    if (!(event.content || '').trim() && !(event.title || '').trim()) return;
    rows.push({ kind: 'status', key: event.id, event });
  });
  return rows;
}

function TimelineMessageRow({ row }: { row: Extract<TimelineRow, { kind: 'message' }> }) {
  const role = row.role;
  const label = role === 'user' ? '你' : role === 'system' ? '系统' : 'Agent';
  const content = row.event.content || '';
  return (
    <article className={`retest-chat-row ${role}`}>
      <div className="retest-chat-edge">{label}</div>
      <div className="retest-chat-body">
        <div className="retest-chat-head">
          <strong>{role === 'user' ? '你' : 'Agent'}{row.live ? ' · 生成中' : ''}</strong>
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
    return row.event.title === '复测结论总览'
      ? <CompletionOverviewCard event={row.event} />
      : (
        <details className="retest-timeline-card artifact">
          <summary>
            <span className="retest-timeline-card-arrow" />
            <strong>{row.event.title}</strong>
            <em>{row.event.timestamp}</em>
          </summary>
          <pre className="retest-timeline-card-body">{artifactContent(row.event)}</pre>
        </details>
      );
  }
  if (row.kind === 'error') {
    return (
      <div className={`retest-chat-error ${row.event.tone || 'error'}`}>
        <strong>{row.event.title}</strong>
        {row.event.content ? <pre>{row.event.content}</pre> : null}
      </div>
    );
  }
  // status 过程行：无标题无内容则不渲染。
  return <TimelineStatusRow event={row.event} />;
}

function TimelineStatusRow({ event }: { event: RetestSessionEvent }) {
  const title = (event.title || '').trim();
  const content = (event.content || '').trim();
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
  const responseMeta = prettyJson(tool.responseMeta);
  const responseHeaders = prettyJson(tool.responseHeadersSafe);
  const toolMeta = compactToolMeta(tool);
  const observationCount = toolObservationCount(tool);
  return (
    <details className={`retest-tool-card ${tool.status || 'running'} ${item.tone || 'info'}`}>
      <summary>
        <span className="retest-tool-card-caret" />
        <span className="retest-tool-card-status" />
        <strong>{toolRunPrefix(tool.status)} {item.title}</strong>
        <em>{toolMeta}</em>
      </summary>
      <div className="retest-tool-call-body">
        {tool.toolId ? <div><b>工具 ID</b><code>{tool.toolId}</code></div> : null}
        <div><b>运行状态</b><span>{statusText(tool.status)}{typeof tool.durationMs === 'number' ? ` · ${tool.durationMs}ms` : ''}</span></div>
        {tool.target ? <div><b>目标</b><span>{tool.target}</span></div> : null}
        {tool.statusCode ? <div><b>HTTP</b><span>{tool.statusCode}{tool.finalUrl ? ` · ${tool.finalUrl}` : ''}</span></div> : null}
        {tool.argsPreview ? <div><b>参数摘要</b><pre>{tool.argsPreview}</pre></div> : null}
        {tool.requestSafe || tool.requestRaw ? <div><b>重放请求包</b><pre>{tool.requestSafe || tool.requestRaw}</pre></div> : null}
        {responseMeta ? <div><b>响应元信息</b><pre>{responseMeta}</pre></div> : null}
        {responseHeaders ? <div><b>响应头</b><pre>{responseHeaders}</pre></div> : null}
        {tool.responseRawExcerpt || tool.responseBodyPreview ? <div><b>响应数据</b><pre>{tool.responseRawExcerpt || tool.responseBodyPreview}</pre></div> : null}
        {tool.resultPreview || item.content ? <div><b>输出摘要</b><pre>{tool.resultPreview || item.content}</pre></div> : null}
        {tool.rawOutput ? <div><b>完整输出</b><pre>{tool.rawOutput}</pre></div> : null}
        {tool.evidence ? <div><b>证据摘要</b><pre>{tool.evidence}</pre></div> : null}
        {tool.failureReason ? <div><b>失败原因</b><pre>{tool.failureReason}</pre></div> : null}
        {tool.pythonProbeScript ? (
          <details className="retest-tool-script">
            <summary>Python 探针脚本</summary>
            <pre>{tool.pythonProbeScript}</pre>
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
  const blockedCount = tools.filter((item) => item.tool.status === 'blocked').length;
  const observationCount = tools.reduce((sum, item) => sum + toolObservationCount(item.tool), 0);
  const summaryParts = [
    runningCount ? `运行中 ${runningCount}` : '',
    failedCount ? `失败 ${failedCount}` : '',
    blockedCount ? `阻塞 ${blockedCount}` : '',
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
      <summary><span className="retest-process-icon" /><strong>{event.title}</strong><em>{event.timestamp}</em></summary>
      <pre>{event.content}</pre>
    </details>
  );
}

function artifactContent(event: RetestSessionEvent) {
  const content = String(event.content || '').trim();
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
    return item.event.title === '复测结论总览'
      ? <CompletionOverviewCard key={key} event={item.event} />
      : <details key={key} className="retest-chat-artifact retest-process-line"><summary><span className="retest-process-icon" /><strong>{item.event.title}</strong><em>{item.event.timestamp}</em></summary><pre>{artifactContent(item.event)}</pre></details>;
  }
  return null;
}

function ProcessGroup({ items, groupKey }: { items: RetestConversationItem[]; groupKey: string }) {
  const summary = processGroupSummary(items);
  return (
    <details className={`retest-process-group retest-process-line${summary.running ? ' running' : ''}${summary.failed ? ' failed' : ''}`}>
      <summary>
        <span className="retest-process-icon" />
        <strong>{summary.title}</strong>
        <em>{summary.meta}</em>
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
      rendered.push(<div key={item.key} className="retest-chat-error"><strong>{item.event.title}</strong><pre>{item.event.content}</pre></div>);
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
          <strong>{turn.title}</strong>
          <span>{turn.sourceFile ? `${turn.sourceFile} · ` : ''}{turn.timestamp}</span>
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
          <div className="retest-activity-head"><strong>{entry.title}</strong><span>{entry.timestamp}</span></div>
          <div className="retest-activity-meta">
            {entry.sourceFile ? <span>{entry.sourceFile}</span> : null}
            {entry.tool?.toolId ? <span>{entry.tool.toolId}</span> : null}
            <span>{statusText(entry.tool?.status)}</span>
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
        <div className="retest-activity-head"><strong><span className="retest-event-badge">{eventBadge(entry.eventType)}</span>{entry.title}</strong><span>{entry.timestamp}</span></div>
        <div className="retest-activity-meta">
          {entry.sourceFile ? <span>{entry.sourceFile}</span> : null}
          {typeof entry.metadata?.phase === 'string' ? <span>{entry.metadata.phase}</span> : null}
        </div>
        {entry.content ? <pre>{entry.content}</pre> : null}
      </div>
    </div>
  );
}

export function TestWorkbenchPage() {
  const [store, setStore] = useState<RetestSessionStore>(() => readRetestSessionStore());
  const [agentInput, setAgentInput] = useState('');
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentRunBusy, setAgentRunBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkbenchTab>('conversation');
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>('all');
  const [confirmRequest, setConfirmRequest] = useState<{
    confirmationId: string;
    operation: string;
    matched: string;
    detail: string;
    script: string;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const stopRequestedRef = useRef(false);
  const currentRunOneTaskRef = useRef<string | null>(null);
  const resumeAutoStartRef = useRef(false);

  const sessions = store.sessions;
  const activeSession = sessions.find((session) => session.sessionId === store.activeSessionId) ?? null;
  const activeEvents = activeSession?.events ?? [];
  const sessionSummary = getSessionSummary(activeSession);
  const resumeCopy = resumeBannerCopy(activeSession);
  const timelineRows = useMemo(() => buildTimelineRows(activeEvents), [activeEvents]);
  const activityEntries = useMemo(() => buildActivityEntries(activeEvents), [activeEvents]);
  const filteredActivityEntries = useMemo(
    () => activityFilter === 'all' ? activityEntries : activityEntries.filter((entry) => entry.kind === activityFilter),
    [activityEntries, activityFilter],
  );
  const eventStats = useMemo(() => ({
    tools: activityEntries.filter((event) => event.kind === 'tool').length,
    thoughts: activeEvents.filter((event) => event.type === 'thought_summary').length,
    errors: activeEvents.filter((event) => event.type === 'error').length,
  }), [activeEvents, activityEntries]);

  const refreshStore = () => setStore(readRetestSessionStore());

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
            // 本机破坏性操作的人工确认请求：弹出确认卡片，等用户批准/拒绝。
            if (String(data.event?.type) === 'confirmation_request') {
              const meta = (data.event.metadata ?? {}) as Record<string, unknown>;
              const cid = typeof meta.confirmationId === 'string' ? meta.confirmationId : '';
              if (cid) {
                setConfirmRequest({
                  confirmationId: cid,
                  operation: typeof meta.operation === 'string' ? meta.operation : '本机敏感操作',
                  matched: typeof meta.matched === 'string' ? meta.matched : '',
                  detail: String(data.event.content || ''),
                  script: typeof meta.script === 'string' ? meta.script : '',
                });
              }
            }
            const snapshot = readRetestSessionStore();
            const session = snapshot.sessions.find((item) => item.sessionId === data.session_id);
            const duplicate = Boolean(session?.events?.some((event) => event.id === data.event?.id));
            // 事件重复（WebSocket 重连/补发同一条）时跳过追加，避免列表里出现两条；
            // 但 sessionPatch 必须照常应用——它是幂等的状态快照，收尾的
            // isRunning:false 若因事件去重被一起丢掉，会导致跑完仍卡在「运行中」。
            if (!duplicate) {
              appendRetestSessionEvent(data.session_id, data.event);
            }
            const patch = data.event?.metadata?.sessionPatch;
            if (patch && typeof patch === 'object' && !Array.isArray(patch)) {
              patchRetestSession(data.session_id, patch as Partial<RetestSessionDraft>);
              if ((patch as Partial<RetestSessionDraft>).isRunning === false) {
                const currentRuntimeSession = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
                if (currentRuntimeSession === data.session_id) {
                  window.sessionStorage.removeItem(RETEST_RUNTIME_SESSION_KEY);
                }
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
  }, [activeSession?.sessionId, streamFingerprint, agentBusy, agentRunBusy, activeTab]);

  // 切换会话 / 切到对话或动态 tab 时，重置为贴底并滚到最新。
  useEffect(() => {
    stickToBottomRef.current = true;
    const target = threadRef.current;
    if (target) target.scrollTop = target.scrollHeight;
  }, [activeSession?.sessionId, activeTab]);

  useEffect(() => {
    if (resumeAutoStartRef.current || agentRunBusy || agentBusy) return;
    const requestedSessionId = window.sessionStorage.getItem(RETEST_RESUME_REQUEST_KEY);
    if (!requestedSessionId) return;
    const session = sessions.find((item) => item.sessionId === requestedSessionId);
    if (!session?.resumeState?.canContinue) return;
    resumeAutoStartRef.current = true;
    window.sessionStorage.removeItem(RETEST_RESUME_REQUEST_KEY);
    setActiveRetestSession(session.sessionId);
    void runRetestInCurrentSession(session, 'continue').finally(() => {
      resumeAutoStartRef.current = false;
    });
  }, [agentRunBusy, agentBusy, sessions]);

  useEffect(() => {
    if (resumeAutoStartRef.current || agentRunBusy || agentBusy) return;
    const requestedTargetDir = window.sessionStorage.getItem(RETEST_RERUN_REQUEST_KEY);
    if (!requestedTargetDir) return;
    resumeAutoStartRef.current = true;
    window.sessionStorage.removeItem(RETEST_RERUN_REQUEST_KEY);
    const session = createRetestSession(requestedTargetDir);
    setActiveRetestSession(session.sessionId);
    patchRetestSession(session.sessionId, { targetDir: requestedTargetDir, status: '准备重新复测...' });
    refreshStore();
    void runRetestInCurrentSession({ ...session, targetDir: requestedTargetDir }, 'rerun', { generateReports: true }).finally(() => {
      resumeAutoStartRef.current = false;
    });
  }, [agentRunBusy, agentBusy]);

  const selectSession = (sessionId: string) => {
    setActiveRetestSession(sessionId);
    refreshStore();
    setActiveTab('conversation');
  };

  const createBlankSession = () => {
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
    stopRequestedRef.current = true;
    setStopBusy(true);
    patchRetestSession(sessionId, {
      isRunning: false,
      status: '复测已停止，可继续',
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
      const currentRuntimeSession = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
      if (currentRuntimeSession === sessionId) {
        window.sessionStorage.removeItem(RETEST_RUNTIME_SESSION_KEY);
      }
      setStopBusy(false);
      refreshStore();
    }
  };

  const respondConfirmation = async (decision: 'approve' | 'reject') => {
    const request = confirmRequest;
    if (!request || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await callBackend('doc.retest.confirmation.respond', {
        confirmation_id: request.confirmationId,
        decision,
        note: decision === 'approve' ? '用户已批准本机操作' : '用户拒绝本机操作',
      });
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

  const captureWorkbenchResultScreenshot = async (fallbackText: string) => {
    await wait(80);
    const { default: html2canvas } = await import('html2canvas');
    const temporaryTarget = document.createElement('div');
    temporaryTarget.className = 'retest-result-capture retest-result-capture-clone';
    temporaryTarget.innerHTML = `<div class="retest-capture-title">复测结果预览</div><pre>${escapeHtml(fallbackText || '复测结果将在这里展示。')}</pre>`;
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

  const runRetestInCurrentSession = async (
    session: RetestSessionDraft | null,
    mode: 'continue' | 'rerun',
    options: { generateReports?: boolean } = {},
  ) => {
    if (!session || session.isRunning || agentRunBusy) return false;
    stopRequestedRef.current = false;
    currentRunOneTaskRef.current = null;
    const sessionId = session.sessionId;
    const resumeState = mode === 'continue' && session.resumeState?.canContinue ? session.resumeState : null;
    const trimmedTargetDir = (resumeState?.targetDir || session.targetDir || '').trim();
    const shouldGenerateReports = Boolean(options.generateReports ?? resumeState?.generateReports);
    if (!trimmedTargetDir) {
      pushAgentEvent(sessionId, 'Agent 执行', '当前会话没有可用于复测的通报目录。', 'warn', { action: mode });
      refreshStore();
      return false;
    }
    if (mode === 'continue' && !resumeState) {
      pushAgentEvent(sessionId, 'Agent 执行', '当前会话没有可继续的断点。', 'warn', { action: mode });
      refreshStore();
      return false;
    }

    setAgentRunBusy(true);
    setActiveTab('conversation');
    setActiveRetestSession(sessionId);
    window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, sessionId);

    const roundPrefix = `agent-${mode}-${Date.now().toString(36)}`;
    patchRetestSession(sessionId, {
      targetDir: trimmedTargetDir,
      status: mode === 'continue' ? 'Agent 正在从断点继续复测...' : 'Agent 正在重新复测当前通报目录...',
      progress: mode === 'continue' ? Math.max(0, Math.min(100, Number(session.progress ?? 0))) : 5,
      isRunning: true,
      resumeState: resumeState ? { ...resumeState, canContinue: false, generateReports: shouldGenerateReports } : null,
    });
    pushAgentEvent(
      sessionId,
      'Agent 执行',
      mode === 'continue'
        ? `我会在当前会话从断点继续复测：${trimmedTargetDir}${shouldGenerateReports ? '\n本轮来自一键复测流程，会继续生成报告。' : '\n本轮只做复测，不生成报告。'}`
        : `我会在当前会话重新复测：${trimmedTargetDir}${shouldGenerateReports ? '\n你要求生成报告，本轮复测完成后会写报告。' : '\n你没有要求生成报告，本轮只做复测。'}`,
      'ok',
      { action: mode, roundId: roundPrefix, generateReports: shouldGenerateReports },
    );
    refreshStore();

    let sourceFiles = resumeState?.sourceFiles ?? [];
    let startIndex = resumeState ? Math.min(Math.max(0, resumeState.nextIndex), sourceFiles.length) : 0;
    const summaries: string[] = resumeState ? [...resumeState.summaries] : [];
    const reports: string[] = resumeState ? [...resumeState.reports] : [];
    const completionItems: RetestCompletionItem[] = resumeState ? asCompletionItems(resumeState.completionItems) : [];
    const allLogs: string[] = resumeState ? [...resumeState.allLogs] : splitLogLines(session.log);
    if (!resumeState) allLogs.push(`Agent 重新复测开始: ${trimmedTargetDir}`);
    let failedCount = resumeState ? Number(resumeState.failedCount || 0) : 0;

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
        sourceFiles = listResult.source_files ?? [];
        allLogs.push(...(listResult.logs ?? []));
        pushAgentEvent(
          sessionId,
          '文档扫描',
          sourceFiles.length ? `发现 ${sourceFiles.length} 份通报文档，开始按队列复测。` : (listResult.message || '未找到通报文档。'),
          sourceFiles.length ? 'ok' : 'warn',
          { action: mode, roundId: roundPrefix },
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
        if (stopRequestedRef.current) {
          return await stopForUser(0, currentRunOneTaskRef.current);
        }
      } else {
        pushAgentEvent(sessionId, '断点恢复', `恢复原队列：共 ${sourceFiles.length} 份通报，已完成 ${startIndex} 份。`, 'ok', { action: mode, roundId: roundPrefix });
      }

      syncSession({ log: joinLogs(allLogs), resumeState: buildResumeState(startIndex, false) });

      for (let index = startIndex; index < sourceFiles.length; index += 1) {
        if (stopRequestedRef.current) {
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
          const appendNewTraceEvents = (events?: RetestSessionEvent[]) => {
            const nextEvents = (events ?? []).filter((event) => {
              if (!event?.id || seenTraceEventIds.has(event.id)) return false;
              seenTraceEventIds.add(event.id);
              return true;
            });
            if (nextEvents.length) appendRetestSessionEvents(sessionId, nextEvents);
          };
          const mergeFileLogs = (logs?: string[]) => {
            const nextLogs = logs ?? [];
            if (nextLogs.length <= fileLogCount) return;
            allLogs.push(...nextLogs.slice(fileLogCount));
            fileLogCount = nextLogs.length;
            syncSession({ log: joinLogs(allLogs) });
          };

          const startResult = await callBackend<RetestRunOneStartResponse>('doc.retest.run_one.start', {
            source_file: sourceFile,
            session_id: sessionId,
            round_id: fileRoundId,
            source_file_name: fileLabel,
          });
          currentRunOneTaskRef.current = startResult.task_id || null;
          mergeFileLogs(startResult.logs);
          appendNewTraceEvents(startResult.trace_events);
          if (stopRequestedRef.current || startResult.stopped) {
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
            if (stopRequestedRef.current) {
              return await stopForUser(index, startResult.task_id);
            }
            const statusResult = await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.status', { task_id: startResult.task_id });
            runResult = statusResult;
            mergeFileLogs(statusResult.logs);
            appendNewTraceEvents(statusResult.trace_events);
            const streamedProgress = Math.min(98, Math.round(((index + ((statusResult.progress ?? 0) / 100)) / Math.max(1, sourceFiles.length)) * 100));
            syncSession({ progress: streamedProgress, status: statusResult.message || nextStatus, isRunning: true });
            if (statusResult.stopped) {
              return await stopForUser(index, startResult.task_id);
            }
            if (statusResult.done) break;
          }
          currentRunOneTaskRef.current = null;
          if (stopRequestedRef.current || runResult.stopped) {
            return await stopForUser(index, startResult.task_id);
          }
          if (runResult.blocked_by_ai_config) {
            stopForAiConfig(index, runResult);
            return false;
          }
          if (!runResult.success) {
            throw new Error(runResult.message || '单个通报复测失败');
          }

          const summary = runResult.summary || `${fileLabel}\n复测结果为空`;
          summaries.push(summary);
          syncSession({ resultText: summary, latestResultData: runResult.result_data ?? null, log: joinLogs(allLogs) });

          let reportResult: RetestGenerateReportsResponse | undefined;
          if (shouldGenerateReports) {
            const reportStatus = `正在截图并写入报告 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
            syncSession({ status: reportStatus });
            pushAgentEvent(sessionId, '报告生成', '复测结果已生成，正在截取结果预览并写入报告模板。', 'info', { action: mode, roundId: fileRoundId });
            const screenshotDataUrl = await captureWorkbenchResultScreenshot(summary);
            reportResult = await callBackend<RetestGenerateReportsResponse>('doc.retest.generate_reports_with_screenshot', {
              target_dir: trimmedTargetDir,
              source_files: [sourceFile],
              screenshot_data_url: screenshotDataUrl,
            });
            allLogs.push(...(reportResult.logs ?? []));
            reports.push(...(reportResult.reports ?? []));
            if (!reportResult.success) {
              failedCount += Math.max(1, reportResult.failures?.length ?? 0);
              const reportFailureText = reportResult.message || `${fileLabel} 报告生成失败`;
              allLogs.push(reportFailureText);
              appendRetestSessionEvent(sessionId, makeRetestSessionEvent('error', '报告生成失败', reportFailureText, 'error', { metadata: { roundId: fileRoundId } }));
            } else {
              const reportArtifactText = reportResult.reports?.length ? formatPathList(reportResult.reports) : '报告生成命令已完成。';
              appendRetestSessionEvent(sessionId, makeRetestSessionEvent('artifact', '报告生成完成', reportArtifactText, 'ok', { metadata: { roundId: fileRoundId, reports: reportResult.reports ?? [] } }));
            }
          }
          if (stopRequestedRef.current) {
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
            lastReportPath: reports[0] ?? session.lastReportPath ?? trimmedTargetDir,
            log: joinLogs(allLogs),
            latestResultData: runResult.result_data ?? null,
            resumeState: buildResumeState(index + 1, false),
          });
        } catch (itemError) {
          currentRunOneTaskRef.current = null;
          if (stopRequestedRef.current) {
            return await stopForUser(index, null);
          }
          failedCount += 1;
          const reason = itemError instanceof Error ? itemError.message : String(itemError);
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
        lastReportPath: reports[0] ?? session.lastReportPath ?? trimmedTargetDir,
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
      const currentRuntimeSession = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
      if (currentRuntimeSession === sessionId) {
        window.sessionStorage.removeItem(RETEST_RUNTIME_SESSION_KEY);
      }
      currentRunOneTaskRef.current = null;
      patchRetestSession(sessionId, { isRunning: false });
      setAgentRunBusy(false);
      refreshStore();
    }
  };

  const removeSession = (session: RetestSessionDraft) => {
    const title = session.sessionTitle || '会话';
    if (!window.confirm(`删除会话“${title}”？`)) return;
    deleteRetestSession(session.sessionId);
    refreshStore();
  };

  const sendAgentMessage = async (message: string, clearInput = false) => {
    const question = message.trim();
    if (!question || agentBusy) return;

    const session = activeSession ?? createBlankSession();
    const sessionId = session.sessionId;
    if (isContinueInstruction(question) && session.resumeState?.canContinue) {
      if (clearInput) setAgentInput('');
      await runRetestInCurrentSession(session, 'continue');
      return;
    }
    const userEvent = makeRetestSessionEvent('chat', '你', question, 'info', { metadata: { role: 'user' } });
    appendRetestSessionEvent(sessionId, userEvent);
    if (clearInput) setAgentInput('');
    setAgentBusy(true);
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
      status: isContinueInstruction(question) ? 'Agent 正在从断点继续...' : 'Agent 正在执行你的指令...',
      resumeState: session.resumeState ? { ...session.resumeState, canContinue: false } : null,
    });
    refreshStore();

    try {
      const result = await callBackend<RetestAgentResponse>('doc.retest.agent.message', {
        session_id: sessionId,
        message: question,
        target_dir: session.resumeState?.targetDir || session.targetDir || '',
      });
      const currentProgress = Math.max(0, Math.min(100, Number(session.progress ?? 0)));
      const returnedProgress = typeof result.progress === 'number' ? result.progress : currentProgress;
      const nextProgress = result.running ? Math.max(currentProgress, returnedProgress) : returnedProgress;
      patchRetestSession(sessionId, {
        isRunning: Boolean(result.running),
        status: result.status || result.message || session.status,
        progress: nextProgress,
        log: result.logs?.length ? joinLogs(result.logs) : session.log,
        latestResultData: result.latest_result_data ?? session.latestResultData,
        resumeState: result.blocked ? session.resumeState ?? null : null,
      });
      if (!result.running) {
        const currentRuntimeSession = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
        if (currentRuntimeSession === sessionId) {
          window.sessionStorage.removeItem(RETEST_RUNTIME_SESSION_KEY);
        }
      }
      if (!result.success || result.blocked) {
        appendRetestSessionEvent(
          sessionId,
          makeRetestSessionEvent('error', result.blocked_title || 'Agent 会话暂停', result.blocked_reason || result.message || 'Agent 已暂停', 'warn', {
            metadata: { phase: result.blocked_stage || 'agent', blockedByAiConfig: Boolean(result.blocked) },
          }),
        );
      }
    } catch (error) {
      appendRetestSessionEvent(
        sessionId,
        makeRetestSessionEvent('error', 'Agent 错误', `Agent 会话调用失败：${error instanceof Error ? error.message : String(error)}`, 'error'),
      );
    } finally {
      setAgentBusy(false);
      refreshStore();
    }
  };

  const askRetestAgent = async () => {
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
            <p>{activeSession?.status || '新建会话或直接发送消息，Agent 会在当前会话里执行。'}</p>
          </div>
          <div className="retest-session-head-actions">
            <div className={`retest-session-run-state${activeSession?.isRunning || agentRunBusy || agentBusy ? ' running' : ''}`}>
              <span />{activeSession ? sessionStateLabel(activeSession) : '空闲'}
            </div>
            {activeSession && (activeSession.isRunning || agentRunBusy || agentBusy) ? (
              <button type="button" className="koi-button danger compact-button" onClick={() => void stopActiveSession()} disabled={stopBusy}>
                {stopBusy ? '停止中...' : '停止'}
              </button>
            ) : null}
          </div>
        </div>
        {activeSession?.resumeState?.canContinue ? (
          <div className="retest-session-resume-banner">
            <div>
              <strong>{resumeCopy.title}</strong>
              <span>{resumeCopy.reason}</span>
            </div>
            <button type="button" className="koi-button primary compact-button" onClick={() => void runRetestInCurrentSession(activeSession, 'continue')} disabled={Boolean(activeSession.isRunning || agentRunBusy || agentBusy)}>继续测试</button>
          </div>
        ) : null}

        <div className="retest-session-context-row">
          <div><b>目标目录</b><span>{sessionSummary.filesText}</span></div>
          <div><b>工具调用</b><span>{eventStats.tools} 个</span></div>
          <div><b>思考 / 错误</b><span>{eventStats.thoughts} / {eventStats.errors}</span></div>
        </div>

        <div className="retest-workbench-tabs">
          <button type="button" className={activeTab === 'conversation' ? 'active' : ''} onClick={() => setActiveTab('conversation')}>对话流</button>
          <button type="button" className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}>AI 动态</button>
          <button type="button" className={activeTab === 'logs' ? 'active' : ''} onClick={() => setActiveTab('logs')}>结果日志</button>
        </div>

        <section className="retest-workbench-panel">
          {activeTab === 'conversation' ? (
            <div className="retest-chat-flow" ref={threadRef}>
              {timelineRows.length ? timelineRows.map((row) => <TimelineRowView key={row.key} row={row} />) : (
                <div className="modal-message">会话启动后，这里会按时间顺序逐条显示你的消息、Agent 回复、思考、工具调用与产物。</div>
              )}
              {agentBusy || agentRunBusy ? (
                <article className="retest-chat-row agent">
                  <div className="retest-chat-edge">Agent</div>
                  <div className="retest-chat-body">
                    <div className="retest-chat-head"><strong>Agent · 生成中</strong><span /></div>
                    <div className="retest-chat-text retest-chat-typing"><span /><span /><span /></div>
                  </div>
                </article>
              ) : null}
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
          <textarea
            className="koi-input retest-agent-chat-input"
            placeholder="直接告诉 Agent：继续、重新测一遍、下载工具、生成报告，或追问刚才的判断依据。"
            value={agentInput}
            onChange={(event) => setAgentInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void askRetestAgent();
              }
            }}
          />
          <button type="button" className="koi-button primary compact-button" onClick={() => void askRetestAgent()} disabled={agentBusy || !agentInput.trim()}>{agentBusy ? '发送中' : '发送'}</button>
        </div>
      </main>

      {confirmRequest ? (
        <div className="retest-confirm-overlay" role="dialog" aria-modal="true">
          <div className="retest-confirm-card">
            <div className="retest-confirm-head">
              <span className="retest-confirm-icon">⚠️</span>
              <strong>需要你确认本机操作</strong>
            </div>
            <p className="retest-confirm-op">{confirmRequest.operation}</p>
            <p className="retest-confirm-detail">{confirmRequest.detail}</p>
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
              批准：按原脚本在你本机执行该操作。拒绝：不在本机执行，模型会改写脚本继续复测（推荐）。
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
                拒绝（让模型改写脚本）
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
