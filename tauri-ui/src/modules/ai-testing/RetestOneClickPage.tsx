import { useEffect, useRef, useState } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend } from '../../lib/backend';
import type { DialogFilter, FileOrDirectoryMode } from '../../lib/file-dialog';
import { navigateToFunction } from '../../lib/navigation-events';
import { openBackendPath } from '../../lib/open-path';
import {
  RETEST_RUNTIME_SESSION_KEY,
  appendRetestAgentMessage,
  appendRetestSessionEvent,
  clearRetestAgentStarting,
  consumeRetestRerunRequest,
  consumeRetestResumeRequest,
  createRetestSession,
  getActiveRetestSession,
  isFastRetestSession,
  isRetestSessionTerminal,
  makeRetestAgentMessage,
  makeRetestSessionEvent,
  markRetestAgentStarting,
  patchRetestSession,
  readRetestSessionStore,
  repairRetestText,
  type RetestSessionDraft,
  type RetestSessionEvent,
} from './retestSessionStore';
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
  source_file?: string;
  manual_test_required?: boolean;
  blocked_by_ai_config?: boolean;
  blocked_stage?: string;
  blocked_title?: string;
  resume_snapshot?: Record<string, unknown>;
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

type RetestAgentStartResponse = {
  success: boolean;
  message: string;
  session_id?: string;
  running?: boolean;
  progress?: number;
  status?: string;
  logs?: string[];
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

function TextInput({ placeholder, readOnly = false, value, onChange }: { placeholder: string; readOnly?: boolean; value?: string; onChange?: (value: string) => void }) {
  return <input className="koi-input" placeholder={placeholder} readOnly={readOnly} value={value} onChange={(event) => onChange?.(event.target.value)} />;
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

function getFileName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function normalizePathForCompare(value?: string) {
  return String(value || '').trim().replace(/[\\/]+$/, '').replace(/\\/g, '/').replace(/\/+/g, '/').toLowerCase();
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function truncateAgentContextText(value: unknown, limit = 1200) {
  const text = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}\n...[已截断 ${text.length - limit} 字]`;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function joinLogs(logs?: string[]) {
  return (logs ?? []).filter(Boolean).join('\n');
}

function splitLogLines(log?: string) {
  return (log || '').split('\n').map((line) => line.trim()).filter(Boolean);
}

function eventSourceLabel(event: RetestSessionEvent) {
  const metadata = asRecord(event.metadata);
  return String(metadata?.sourceFileName || getFileName(event.sourceFile || '') || '').trim();
}

function isCompletedRetestStatus(value: unknown) {
  const status = String(value || '').trim().toLowerCase();
  return status === 'clean' || status === 'risk';
}

function eventHasCompletedRetestVerdict(event: RetestSessionEvent, metadata: Record<string, unknown>) {
  if (typeof metadata.fixStatus === 'string') return isCompletedRetestStatus(metadata.fixStatus);
  const content = repairRetestText(event.content || '').toLowerCase();
  return event.title.includes('复测结果')
    && event.tone !== 'error'
    && !content.includes('失败')
    && !content.includes('未完成')
    && !content.includes('manual')
    && !content.includes('incomplete')
    && !content.includes('failed');
}

function buildFrontendProgressEvidence(session: RetestSessionDraft, targetDir: string): RetestFrontendProgressEvidence {
  const completed = new Map<string, string>();
  let latestSourceFileName = '';
  let hasCompletionSummary = false;
  let toolCalls = 0;
  let errors = 0;
  let completedCountHint = 0;
  let nextIndexHint = 0;
  let nextSourceFileName = '';
  const saved = session.progressEvidence;
  const savedTargetKey = normalizePathForCompare(saved?.targetDir);
  const currentTargetKey = normalizePathForCompare(targetDir);
  if (saved && (!savedTargetKey || !currentTargetKey || savedTargetKey === currentTargetKey)) {
    for (const name of saved.completedFileNames ?? []) {
      const fileName = getFileName(String(name || ''));
      if (fileName) completed.set(fileName.toLowerCase(), fileName);
    }
    latestSourceFileName = saved.latestSourceFileName || latestSourceFileName;
    hasCompletionSummary = hasCompletionSummary || Boolean(saved.hasCompletionSummary);
    toolCalls = Math.max(toolCalls, Number(saved.toolCalls ?? 0));
    errors = Math.max(errors, Number(saved.errors ?? 0));
    completedCountHint = Math.max(completedCountHint, Number(saved.completedCountHint ?? 0));
    nextIndexHint = Math.max(nextIndexHint, Number(saved.nextIndexHint ?? 0));
    nextSourceFileName = saved.nextSourceFileName || nextSourceFileName;
  }
  for (const event of session.events ?? []) {
    const metadata = asRecord(event.metadata) ?? {};
    const sourceName = eventSourceLabel(event);
    if (sourceName) latestSourceFileName = sourceName;
    for (const item of asRecordArray(metadata.completionItems)) {
      if (!isCompletedRetestStatus(item.status || item.fixStatus)) continue;
      const name = getFileName(String(item.sourceFileName || item.sourceFile || ''));
      if (name) completed.set(name.toLowerCase(), name);
    }
    const hasFileVerdict = eventHasCompletedRetestVerdict(event, metadata);
    if (hasFileVerdict && sourceName) completed.set(sourceName.toLowerCase(), sourceName);
    if (metadata.phase === 'completion_summary' || event.title.includes('复测结论总览')) hasCompletionSummary = true;
    if (event.type === 'tool_call' || event.type === 'tool_result') toolCalls += 1;
    if (event.type === 'error') errors += 1;
  }
  return {
    targetDir,
    completedFileNames: Array.from(completed.values()).slice(-1000),
    latestSourceFileName,
    hasCompletionSummary,
    toolCalls,
    errors,
    completedCountHint: Math.max(0, completed.size, completedCountHint) || undefined,
    nextIndexHint: Math.max(0, completed.size, nextIndexHint) || undefined,
    nextSourceFileName,
  };
}

function sessionTimestamp(session: RetestSessionDraft) {
  const updated = Date.parse(session.updatedAt || '');
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(session.createdAt || '');
  return Number.isFinite(created) ? created : 0;
}

function sessionTargetDir(session: RetestSessionDraft) {
  return String(session.resumeState?.targetDir || session.targetDir || session.progressEvidence?.targetDir || '').trim();
}

function isSameTargetSession(session: RetestSessionDraft, targetDir: string) {
  const sessionTarget = normalizePathForCompare(sessionTargetDir(session));
  const currentTarget = normalizePathForCompare(targetDir);
  return Boolean(sessionTarget && currentTarget && sessionTarget === currentTarget);
}

function sameTargetAgentContextSessions(targetDir: string, currentSessionId?: string) {
  const currentTarget = normalizePathForCompare(targetDir);
  if (!currentTarget) return [];
  return readRetestSessionStore().sessions
    .filter((session) => session.sessionId !== currentSessionId)
    .filter((session) => !isFastRetestSession(session))
    .filter((session) => isSameTargetSession(session, targetDir))
    .sort((a, b) => sessionTimestamp(b) - sessionTimestamp(a))
    .slice(0, 6)
    .sort((a, b) => sessionTimestamp(a) - sessionTimestamp(b));
}

function mergeFrontendProgressEvidence(sessions: RetestSessionDraft[], targetDir: string): RetestFrontendProgressEvidence {
  const outcomes = new Map<string, { name: string; completed: boolean }>();
  let latestSourceFileName = '';
  let hasCompletionSummary = false;
  let toolCalls = 0;
  let errors = 0;
  let nextSourceFileName = '';
  const recordOutcome = (source: unknown, status: unknown) => {
    const name = getFileName(String(source || ''));
    const normalizedStatus = String(status || '').trim().toLowerCase();
    if (!name || !normalizedStatus) return;
    const key = name.toLowerCase();
    outcomes.delete(key);
    outcomes.set(key, { name, completed: isCompletedRetestStatus(normalizedStatus) });
  };
  sessions.forEach((item) => {
    const evidence = buildFrontendProgressEvidence(item, targetDir);
    evidence.completedFileNames.forEach((name) => {
      const fileName = getFileName(name);
      if (fileName) outcomes.set(fileName.toLowerCase(), { name: fileName, completed: true });
    });
    for (const event of item.events ?? []) {
      const metadata = asRecord(event.metadata) ?? {};
      for (const completion of asRecordArray(metadata.completionItems)) {
        recordOutcome(completion.sourceFileName || completion.sourceFile, completion.status || completion.fixStatus);
      }
      const sourceName = eventSourceLabel(event);
      if (sourceName && typeof metadata.fixStatus === 'string') {
        recordOutcome(sourceName, metadata.fixStatus);
      } else if (sourceName && event.type === 'error') {
        recordOutcome(sourceName, 'failed');
      }
    }
    for (const completion of asRecordArray(item.resumeState?.completionItems)) {
      recordOutcome(completion.sourceFileName || completion.sourceFile, completion.status || completion.fixStatus);
    }
    latestSourceFileName = evidence.latestSourceFileName || latestSourceFileName;
    hasCompletionSummary = evidence.hasCompletionSummary;
    toolCalls += evidence.toolCalls;
    errors += evidence.errors;
    nextSourceFileName = evidence.nextSourceFileName || nextSourceFileName;
  });
  const completedFileNames = Array.from(outcomes.values())
    .filter((outcome) => outcome.completed)
    .map((outcome) => outcome.name)
    .slice(-1000);
  const hasUnresolved = Array.from(outcomes.values()).some((outcome) => !outcome.completed);
  return {
    targetDir,
    completedFileNames,
    latestSourceFileName,
    hasCompletionSummary: hasCompletionSummary && !hasUnresolved,
    toolCalls,
    errors,
    completedCountHint: completedFileNames.length || undefined,
    nextIndexHint: completedFileNames.length || undefined,
    nextSourceFileName,
  };
}

function latestTextFromSessions(sessions: RetestSessionDraft[], picker: (session: RetestSessionDraft) => unknown, limit = 2500) {
  for (const session of [...sessions].sort((a, b) => sessionTimestamp(b) - sessionTimestamp(a))) {
    const text = repairRetestText(picker(session) || '').trim();
    if (text) return truncateAgentContextText(text, limit);
  }
  return '';
}

function mergedMemoryMarkdown(sessions: RetestSessionDraft[], progressEvidence: RetestFrontendProgressEvidence) {
  const memoryBlocks = sessions
    .map((session) => repairRetestText(session.memoryMarkdown || '').trim())
    .filter(Boolean)
    .slice(-4);
  const evidenceLine = [
    `同目录历史进度证据：已完成 ${progressEvidence.completedFileNames.length} 份通报。`,
    progressEvidence.nextIndexHint !== undefined ? `nextIndexHint=${progressEvidence.nextIndexHint}` : '',
    progressEvidence.nextSourceFileName ? `下一份未完成: ${progressEvidence.nextSourceFileName}` : '',
  ].filter(Boolean).join(' ');
  return truncateAgentContextText([evidenceLine, ...memoryBlocks].filter(Boolean).join('\n\n---\n\n'), 12000);
}

function buildAgentFrontendContext(session: RetestSessionDraft, targetDir: string, relatedSessions: RetestSessionDraft[] = []) {
  const sessions = [...relatedSessions.filter((item) => item.sessionId !== session.sessionId), session]
    .filter((item, index, array) => array.findIndex((candidate) => candidate.sessionId === item.sessionId) === index)
    .filter((item) => item.sessionId === session.sessionId || (!isFastRetestSession(item) && isSameTargetSession(item, targetDir)))
    .sort((a, b) => sessionTimestamp(a) - sessionTimestamp(b));
  const progressEvidence = mergeFrontendProgressEvidence(sessions, targetDir);
  const resumeState = session.resumeState ?? [...sessions].reverse().find((item) => item.resumeState?.canContinue)?.resumeState ?? null;
  const latestSession = [...sessions].sort((a, b) => sessionTimestamp(b) - sessionTimestamp(a))[0] ?? session;
  const recentEvents = sessions.flatMap((item) => item.events ?? []).sort((a, b) => {
    const left = Date.parse(a.timestamp || '');
    const right = Date.parse(b.timestamp || '');
    return (Number.isFinite(left) ? left : 0) - (Number.isFinite(right) ? right : 0);
  }).slice(-30).map((event) => {
    const metadata = asRecord(event.metadata) ?? {};
    return {
      type: event.type,
      title: event.title,
      role: typeof metadata.role === 'string' ? metadata.role : '',
      timestamp: event.timestamp,
      tone: event.tone,
      sourceFile: event.sourceFile || '',
      content: truncateAgentContextText(event.content, 600),
      metadata: {
        phase: typeof metadata.phase === 'string' ? metadata.phase : '',
        generateReports: metadata.generateReports === true,
        generate_reports: metadata.generate_reports === true,
      },
      tool: event.tool ? {
        toolId: event.tool.toolId || '',
        label: event.tool.label || '',
        status: event.tool.status || '',
        target: truncateAgentContextText(event.tool.target, 220),
        resultPreview: truncateAgentContextText(event.tool.resultPreview || event.tool.failureReason || event.tool.evidence, 500),
      } : undefined,
    };
  });
  return {
    session: {
      sessionId: session.sessionId,
      title: session.sessionTitle,
      targetDir,
      status: session.status || latestSession.status || '',
      progress: session.progress ?? latestSession.progress ?? 0,
      isRunning: Boolean(session.isRunning),
      generateReports: Boolean(session.generateReports || latestSession.generateReports),
      resumeState,
      lastReportPath: latestTextFromSessions(sessions, (item) => item.lastReportPath, 1200),
      resultText: latestTextFromSessions(sessions, (item) => item.resultText, 2500),
      logTail: sessions.flatMap((item) => splitLogLines(item.log)).slice(-40).map((line) => truncateAgentContextText(line, 500)),
      latestResultDataText: latestSession.latestResultData ? truncateAgentContextText(JSON.stringify(latestSession.latestResultData), 1800) : '',
      memoryMarkdown: mergedMemoryMarkdown(sessions, progressEvidence),
    },
    conversation: [],
    recentEvents,
    progressEvidence,
  };
}

function canResumeFromSessionContext(session: RetestSessionDraft | null | undefined) {
  if (!session) return false;
  if (isFastRetestSession(session)) return false;
  if (isRetestSessionTerminal(session)) return false;
  if (session.resumeState?.canContinue) return true;
  const targetDir = (session.resumeState?.targetDir || session.targetDir || '').trim();
  if (!targetDir) return false;
  const evidenceCount = session.progressEvidence?.completedFileNames?.length ?? 0;
  return Boolean(
    session.memoryMarkdown?.trim()
      || evidenceCount > 0
      || session.resultText?.trim()
      || session.log?.trim(),
  );
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

const MODEL_REPRODUCED_VALUES = new Set(['reproduced', 'reproducible', 'unfixed', 'not_fixed', 'notfixed', 'risk', 'vulnerable', '可复现', '未修复']);
const MODEL_CLEAN_VALUES = new Set(['not_reproduced', 'notreproduced', 'not_reproducible', 'notreproducible', 'fixed', 'clean', 'pass', 'passed', '已修复', '复测通过', '不可复现']);
const MODEL_CLEAN_TEXT_PATTERNS = [
  /\bnot[\s_-]?reproduced\b/i,
  /\bnot[\s_-]?reproducible\b/i,
  /不可复现/,
  /未能?复现/,
  /未见复现/,
  /未发现复现/,
  /无从复现/,
  /无法复现/,
  /未形成可复现证据/,
  /未形成.*复现证据/,
  /没有.*复现证据/,
  /缺乏.*复现证据/,
  /目标.*不可达/,
  /未能验证/,
  /复测通过/,
  /已修复/,
];
const MODEL_REPRODUCED_TEXT_PATTERNS = [
  /(?<!not[\s_-])\breproduced\b/i,
  /\breproducible\b/i,
  /仍可复现/,
  /可以复现/,
  /可复现/,
  /未修复/,
  /漏洞仍然成立/,
  /风险仍然存在/,
];

function normalizeModelVerdict(value: unknown): '' | 'reproduced' | 'not_reproduced' {
  const raw = repairRetestText(value || '').trim().toLowerCase();
  const canonical = raw.replace(/[\s-]+/g, '_');
  if (MODEL_REPRODUCED_VALUES.has(canonical)) return 'reproduced';
  if (MODEL_CLEAN_VALUES.has(canonical)) return 'not_reproduced';
  return '';
}

function normalizeModelVerdictFromTexts(values: unknown[]): '' | 'reproduced' | 'not_reproduced' {
  for (const value of values) {
    const verdict = normalizeModelVerdict(value);
    if (verdict) return verdict;
  }
  const text = values.map((value) => repairRetestText(value || '').trim()).filter(Boolean).join('\n');
  if (!text) return '';
  if (MODEL_CLEAN_TEXT_PATTERNS.some((pattern) => pattern.test(text))) return 'not_reproduced';
  if (MODEL_REPRODUCED_TEXT_PATTERNS.some((pattern) => pattern.test(text))) return 'reproduced';
  return '';
}

function modelVerdictFromResultData(resultData: Record<string, unknown> | null): '' | 'reproduced' | 'not_reproduced' {
  const aiJudgement = asRecord(resultData?.ai_judgement);
  const verdict = normalizeModelVerdictFromTexts([
    aiJudgement?.verdict
      || resultData?.final_verdict,
    aiJudgement?.reproduction_status,
    aiJudgement?.fix_status,
    aiJudgement?.status,
  ]);
  if (verdict) return verdict;
  if (typeof aiJudgement?.reproduced === 'boolean') {
    return aiJudgement.reproduced ? 'reproduced' : 'not_reproduced';
  }
  return normalizeModelVerdictFromTexts([
    aiJudgement?.conclusion,
    aiJudgement?.result,
    aiJudgement?.message,
    aiJudgement?.reason,
    aiJudgement?.notes,
  ]);
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
    sourceFile,
    sourceFileName: repairRetestText(getFileName(sourceFile)),
    status,
    statusLabel: missingModelVerdict ? '模型未给出判定' : completionStatusLabel(status),
    evidence: extracted.evidence,
    reason,
    reportPaths: (reportResult?.reports ?? []).map((path) => repairRetestText(path)),
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
  const modelConclusion = repairRetestText(aiJudgement?.conclusion || '').trim();
  const judgementLabel = resultData?.fast_mode || aiJudgement?.source === 'fast_rules' ? '快速判定' : '模型判定';
  const missingJudgementLabel = judgementLabel === '快速判定' ? '快速规则未给出判定' : '模型未给出判定';
  const urls = asStringArray(resultData?.urls);
  const lines = [
    `文件: ${repairRetestText(fileLabel)}`,
    `复测结果: ${repairRetestText(completionItem.statusLabel)}`,
    `${judgementLabel}: ${finalVerdict || missingJudgementLabel}${modelConclusion ? ` / ${modelConclusion}` : ''}`,
  ];
  if (aiJudgement?.reason || completionItem.reason) {
    lines.push(`理由: ${repairRetestText(aiJudgement?.reason || completionItem.reason)}`);
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
      lines.push(`- ${repairRetestText(item.sourceFileName)}`);
      lines.push(`  证据: ${repairRetestText(item.evidence).split('\n').slice(0, 3).join(' / ') || '暂无'}`);
      if (item.reason) lines.push(`  原因: ${repairRetestText(item.reason)}`);
      if (item.tools.length) lines.push(`  工具: ${item.tools.map((tool) => repairRetestText(tool)).join(', ')}`);
      if (item.reportPaths.length) lines.push(`  报告: ${item.reportPaths.map((path) => repairRetestText(path)).join('；')}`);
    });
  });
  return lines.join('\n');
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

export function RetestOneClickPage() {
  const [targetDir, setTargetDir] = useState('');
  const [status, setStatus] = useState('等待开始复测...');
  const [progress, setProgress] = useState(0);
  const [resultText, setResultText] = useState('');
  const [log, setLog] = useState('');
  const [lastReportPath, setLastReportPath] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [latestResultData, setLatestResultData] = useState<Record<string, unknown> | null>(null);
  const activeSessionIdRef = useRef<string | undefined>(undefined);
  const resumeAutoStartRef = useRef(false);
  const resultPreviewRef = useRef<HTMLFieldSetElement | null>(null);

  useEffect(() => {
    const activeSession = getActiveRetestSession();
    if (!activeSession) return;
    activeSessionIdRef.current = activeSession.sessionId;
    const runtimeSessionId = window.sessionStorage.getItem(RETEST_RUNTIME_SESSION_KEY);
    if (runtimeSessionId !== activeSession.sessionId) return;
    setTargetDir(activeSession.targetDir || '');
    setStatus(repairRetestText(activeSession.status || '等待开始复测...'));
    setProgress(Number(activeSession.progress ?? 0));
    setResultText(repairRetestText(activeSession.resultText || ''));
    setLog(repairRetestText(activeSession.log || ''));
    setLastReportPath(repairRetestText(activeSession.lastReportPath || ''));
    setLatestResultData(activeSession.latestResultData && typeof activeSession.latestResultData === 'object' ? activeSession.latestResultData : null);
  }, []);

  const syncSession = (partial: Parameters<typeof patchRetestSession>[1]) => {
    patchRetestSession(activeSessionIdRef.current, partial);
  };

  const pushAgentMessage = (role: Parameters<typeof makeRetestAgentMessage>[0], content: string, title?: string, tone: Parameters<typeof makeRetestAgentMessage>[3] = 'info') => {
    const message = makeRetestAgentMessage(role, content, title, tone);
    appendRetestAgentMessage(activeSessionIdRef.current, message);
    return message;
  };

  const captureRetestResultScreenshot = async (fallbackText: string) => {
    await wait(80);
    const { default: html2canvas } = await import('html2canvas');
    let captureTarget: HTMLElement | null = null;
    let temporaryTarget: HTMLElement | null = null;
    const fixedFallbackText = repairRetestText(fallbackText || resultText || '复测结果将在这里展示，并作为证明截图写入复测报告。');

    temporaryTarget = document.createElement('div');
    temporaryTarget.className = 'retest-result-capture retest-result-capture-clone';
    temporaryTarget.innerHTML = `<div class="retest-capture-title">复测结果预览</div><pre>${escapeHtml(fixedFallbackText)}</pre>`;
    document.body.appendChild(temporaryTarget);
    captureTarget = temporaryTarget;
    await wait(30);

    try {
      const canvas = await html2canvas(captureTarget, {
        backgroundColor: '#ffffff',
        logging: false,
        scale: Math.min(window.devicePixelRatio || 1, 2),
        useCORS: true,
      });
      return canvas.toDataURL('image/png');
    } finally {
      temporaryTarget?.remove();
    }
  };

  const resetRetestSession = () => {
    setProgress(0);
    setResultText('');
    setLog('');
    setLastReportPath('');
    setLatestResultData(null);
    setStatus('等待开始复测...');
    syncSession({
      progress: 0,
      resultText: '',
      log: '',
      lastReportPath: '',
      latestResultData: null,
      status: '等待开始复测...',
      isRunning: false,
      resumeState: null,
    });
  };

  const startAgentRetest = async (resumeSession?: RetestSessionDraft | null, overrideTargetDir = '') => {
    const resumeState = resumeSession?.resumeState?.canContinue ? resumeSession.resumeState : null;
    const isContextResume = Boolean(resumeSession && canResumeFromSessionContext(resumeSession));
    const isResume = Boolean(resumeSession && (resumeState || isContextResume));
    const trimmedTargetDir = (resumeState?.targetDir || resumeSession?.targetDir || overrideTargetDir || targetDir).trim();
    if (!trimmedTargetDir) {
      setStatus('请先选择通报目录');
      return;
    }

    if (isResume && resumeSession) {
      activeSessionIdRef.current = resumeSession.sessionId;
      window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, resumeSession.sessionId);
      const completedCount = resumeSession.progressEvidence?.completedFileNames?.length ?? 0;
      pushAgentMessage(
        'system',
        resumeState
          ? `从断点继续测试：${trimmedTargetDir}\n下一份通报序号：${(resumeState.nextIndex ?? 0) + 1}`
          : `从压缩会话上下文继续测试：${trimmedTargetDir}\n已保存 ${completedCount} 个已完成文件证据。`,
        '继续测试',
      );
      appendRetestSessionEvent(resumeSession.sessionId, makeRetestSessionEvent(
        'status',
        '一键复测继续请求',
        '本会话从一键复测入口继续，后续恢复/继续时默认继续生成报告。',
        'info',
        { metadata: { phase: 'one_click_resume', generateReports: true } },
      ));
    } else {
      const openingMessage = makeRetestAgentMessage('system', `目标目录：${trimmedTargetDir}\n已创建测试会话，开始读取通报并规划复测。`, '会话启动');
      const reportIntentEvent = makeRetestSessionEvent(
        'status',
        '一键复测启动',
        '本会话从一键复测入口创建，后续恢复/继续时默认继续生成报告。',
        'info',
        { metadata: { phase: 'one_click_start', generateReports: true } },
      );
      const session = createRetestSession(trimmedTargetDir, [openingMessage, reportIntentEvent]);
      activeSessionIdRef.current = session.sessionId;
      window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, session.sessionId);
    }

    const sessionId = activeSessionIdRef.current;
    if (!sessionId) {
      setStatus('缺少测试会话 ID');
      return;
    }
    markRetestAgentStarting(sessionId);

    setIsBusy(true);
    setTargetDir(trimmedTargetDir);
    setProgress(isResume ? Math.max(0, Math.min(100, Number(resumeSession?.progress ?? 0))) : 5);
    setStatus(isResume ? '正在从断点继续复测...' : '正在扫描通报目录...');
    setResultText(isResume ? repairRetestText(resumeSession?.resultText || '') : '');
    setLog(isResume ? repairRetestText(resumeSession?.log || '') : '');
    setLastReportPath(isResume ? repairRetestText(resumeSession?.lastReportPath || '') : '');
    setLatestResultData(isResume && resumeSession?.latestResultData ? resumeSession.latestResultData : null);
      syncSession({
        targetDir: trimmedTargetDir,
        status: isResume ? '正在从断点继续复测...' : '正在扫描通报目录...',
        progress: isResume ? Math.max(0, Math.min(100, Number(resumeSession?.progress ?? 0))) : 5,
      resultText: isResume ? repairRetestText(resumeSession?.resultText || '') : '',
      log: isResume ? repairRetestText(resumeSession?.log || '') : '',
      lastReportPath: isResume ? repairRetestText(resumeSession?.lastReportPath || '') : '',
        latestResultData: isResume && resumeSession?.latestResultData ? resumeSession.latestResultData : null,
        isRunning: true,
        generateReports: true,
        resumeState: resumeState ? { ...resumeState, canContinue: false, generateReports: true } : null,
      });
    navigateToFunction('ai-testing', 'test-workbench');

    try {
      const message = isResume
        ? '继续测试并生成报告；请优先使用前端断点、压缩记忆和磁盘旧复测报告证据，跳过已完成通报。'
        : '一键复测并生成报告；如果当前目录已有前端断点、压缩记忆或磁盘旧复测报告证据，请按续跑处理并跳过已完成通报。只有用户明确要求重新复测、从头重跑或不要接旧进度时才完整重跑。';
      let latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? getActiveRetestSession();
      const relatedSessions = sameTargetAgentContextSessions(trimmedTargetDir, sessionId);
      if (!isResume && latestSession && relatedSessions.length) {
        const progressEvidence = mergeFrontendProgressEvidence([...relatedSessions, latestSession], trimmedTargetDir);
        appendRetestSessionEvent(sessionId, makeRetestSessionEvent(
          'status',
          '继承同目录历史进度',
          `已合并 ${relatedSessions.length} 个同目录 Agent 历史会话的进度证据；已完成通报 ${progressEvidence.completedFileNames.length} 份。`,
          'ok',
          { metadata: { phase: 'one_click_history_context', progressEvidence } },
        ));
        latestSession = readRetestSessionStore().sessions.find((item) => item.sessionId === sessionId) ?? latestSession;
      }
      const result = await callBackend<RetestAgentStartResponse>('doc.retest.agent.start', {
        session_id: sessionId,
        target_dir: trimmedTargetDir,
        message,
        generate_reports: true,
        one_click_queue: true,
        use_progress_evidence: true,
        frontend_context: latestSession ? buildAgentFrontendContext(latestSession, trimmedTargetDir, relatedSessions) : undefined,
        force_resume: isResume,
      });
      const nextStatus = result.status || result.message || 'Agent 已启动';
      const currentProgress = isResume ? Math.max(0, Math.min(100, Number(resumeSession?.progress ?? 0))) : 5;
      const returnedProgress = typeof result.progress === 'number' ? result.progress : currentProgress;
      const nextProgress = result.running ? Math.max(currentProgress, returnedProgress) : returnedProgress;
      const nextLog = result.logs?.length ? joinLogs(result.logs) : (isResume ? resumeSession?.log || '' : '');
      setStatus(nextStatus);
      setProgress(nextProgress);
      setLog(nextLog);
      syncSession({
        status: nextStatus,
        progress: nextProgress,
        log: nextLog,
        isRunning: Boolean(result.running),
      });
      return;
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      const failedStatus = `Agent 启动失败: ${reason}`;
      setStatus(failedStatus);
      syncSession({ status: failedStatus, isRunning: false });
      return;
    } finally {
      clearRetestAgentStarting(sessionId);
      setIsBusy(false);
    }
  };

  const startFastRetest = async (_resumeSession?: RetestSessionDraft | null, overrideTargetDir = '') => {
    const trimmedTargetDir = (overrideTargetDir || targetDir).trim();
    if (!trimmedTargetDir) {
      setStatus('请先选择通报目录');
      return;
    }

    activeSessionIdRef.current = undefined;
    setIsBusy(true);
    setTargetDir(trimmedTargetDir);
    setProgress(5);
    setStatus('正在扫描通报目录...');
    setResultText('');
    setLog('');
    setLastReportPath('');
    setLatestResultData(null);

    try {
      const listResult = await callBackend<RetestListFilesResponse>('doc.retest.list_files', { target_dir: trimmedTargetDir });
      const sourceFiles = listResult.source_files ?? [];
      const allLogs = [...(listResult.logs ?? [])];
      const summaries: string[] = [];
      const reports: string[] = [];
      const completionItems: RetestCompletionItem[] = [];
      let failedCount = 0;
      let firstFailedIndex: number | null = null;
      const flushFastLog = () => setLog(joinLogs(allLogs));
      const appendFastLog = (message: string) => {
        const text = repairRetestText(message || '').trim();
        if (!text) return;
        allLogs.push(text);
        flushFastLog();
      };

      flushFastLog();
      if (!listResult.success || !sourceFiles.length) {
        setProgress(0);
        setStatus(listResult.message || '未找到通报文档。');
        return;
      }

      appendFastLog(`快速复测发现 ${sourceFiles.length} 份通报文档；本轮不创建 Agent 会话，不调用 AI 模型。`);

      for (let index = 0; index < sourceFiles.length; index += 1) {
        const sourceFile = sourceFiles[index];
        const fileLabel = getFileName(sourceFile);
        const nextProgress = Math.max(5, Math.round((index / sourceFiles.length) * 100));
        const nextStatus = `正在复测 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
        setProgress(nextProgress);
        setStatus(nextStatus);
        appendFastLog(`[${index + 1}/${sourceFiles.length}] 开始快速复测: ${fileLabel}`);

        try {
          let fileLogCount = 0;
          let fileTraceEventCount = 0;
          const mergeFileLogs = (logs?: string[], logCount?: number) => {
            const nextLogs = logs ?? [];
            if (!nextLogs.length) {
              fileLogCount = Math.max(fileLogCount, typeof logCount === 'number' ? logCount : fileLogCount);
              return;
            }
            allLogs.push(...nextLogs);
            fileLogCount = Math.max(fileLogCount + nextLogs.length, typeof logCount === 'number' ? logCount : fileLogCount + nextLogs.length);
            flushFastLog();
          };

          const startResult = await callBackend<RetestRunOneStartResponse>('doc.retest.run_one.start', {
            source_file: sourceFile,
            round_id: `fast-file-${index + 1}`,
            source_file_name: fileLabel,
            mode: 'fast',
            use_ai: false,
          });
          mergeFileLogs(startResult.logs, startResult.log_count);
          if (startResult.blocked_by_ai_config) {
            throw new Error(`快速复测被 AI 配置拦截: ${startResult.message || 'unknown'}`);
          }
          if (!startResult.success || !startResult.task_id) {
            throw new Error(startResult.message || '单个通报复测任务启动失败');
          }

          let runResult: RetestRunOneStatusResponse | RetestRunOneStartResponse = startResult;
          while (true) {
            await wait(650);
            const statusResult = await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.status', {
              task_id: startResult.task_id,
              log_offset: fileLogCount,
              trace_event_offset: fileTraceEventCount,
            });
            runResult = statusResult;
            mergeFileLogs(statusResult.logs, statusResult.log_count);
            fileTraceEventCount = Math.max(fileTraceEventCount, typeof statusResult.trace_event_count === 'number' ? statusResult.trace_event_count : fileTraceEventCount);
            const streamedProgress = Math.min(98, Math.round(((index + ((statusResult.progress ?? 0) / 100)) / sourceFiles.length) * 100));
            const streamedStatus = statusResult.message || nextStatus;
            setProgress(streamedProgress);
            setStatus(streamedStatus);
            if (statusResult.done) break;
          }
          if (runResult.blocked_by_ai_config) {
            throw new Error(`快速复测被 AI 配置拦截: ${runResult.message || 'unknown'}`);
          }
          if (!runResult.success) {
            throw new Error(runResult.message || '单个通报复测失败');
          }

          const summary = repairRetestText(runResult.summary || `${fileLabel}\n复测结果为空`);
          summaries.push(summary);
          setResultText(summary);
          setLatestResultData(runResult.result_data ?? null);

          await wait(120);
          const reportStatus = `正在截图并写入报告 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
          setStatus(reportStatus);
          appendFastLog(`[${index + 1}/${sourceFiles.length}] 复测完成，开始生成报告: ${fileLabel}`);
          const reportResult = await callBackend<RetestGenerateReportsResponse>('doc.retest.generate_reports_with_screenshot', {
            target_dir: trimmedTargetDir,
            source_files: [sourceFile],
            summary,
            result_data: runResult.result_data ?? null,
          });
          allLogs.push(...(reportResult.logs ?? []));
          reports.push(...(reportResult.reports ?? []));
          if (!reportResult.success) {
            failedCount += Math.max(1, reportResult.failures?.length ?? 0);
            const reportFailureText = repairRetestText(reportResult.message || `${fileLabel} 报告生成失败`);
            allLogs.push(reportFailureText);
            flushFastLog();
          } else {
            appendFastLog(reportResult.reports?.length ? `报告已生成：\n${formatPathList(reportResult.reports)}` : '报告生成命令已完成。');
          }
          const resultWithReport = [
            summary,
            reportResult.reports?.length ? `\n生成报告:\n${formatPathList(reportResult.reports)}` : '',
          ].filter(Boolean).join('\n');
          const completionItem = buildCompletionItem(sourceFile, runResult, reportResult);
          completionItems.push(completionItem);
          if (completionItem.status === 'failed') {
            firstFailedIndex = firstFailedIndex === null ? index : Math.min(firstFailedIndex, index);
          }
          appendFastLog(formatRetestResultMessage(fileLabel, runResult, completionItem, reportResult));
          const reportLog = joinLogs(allLogs);
          setLastReportPath(reports[0] ?? trimmedTargetDir);
          setResultText(resultWithReport);
          setLog(reportLog);
        } catch (itemError: unknown) {
          const reason = repairRetestText(errorMessage(itemError));
          failedCount += 1;
          allLogs.push(`${fileLabel} 处理失败: ${reason}`);
          const failedLog = joinLogs(allLogs);
          setLog(failedLog);
          completionItems.push(buildCompletionItem(sourceFile, undefined, undefined, reason));
          firstFailedIndex = firstFailedIndex === null ? index : Math.min(firstFailedIndex, index);
        }

        const completedProgress = Math.round(((index + 1) / sourceFiles.length) * 100);
        setProgress(completedProgress);
      }

      const hasRetryableFailures = firstFailedIndex !== null || completionItems.some((item) => item.status === 'failed');
      const retryIndex = firstFailedIndex ?? Math.max(0, completionItems.findIndex((item) => item.status === 'failed'));
      const finalStatus = `${hasRetryableFailures ? '快速复测暂停' : '复测完成'}：处理 ${sourceFiles.length} 份文档，生成 ${reports.length} 份报告${failedCount ? `，失败 ${failedCount} 份待重试` : ''}`;
      const completionOverview = formatCompletionOverview(completionItems);
      const finalResultText = [
        completionOverview,
        summaries.length ? '\n详细复测摘要:' : '',
        summaries.join('\n\n'),
        reports.length ? `\n生成报告:\n${formatPathList(reports)}` : '',
      ].filter(Boolean).join('\n');
      setStatus(finalStatus);
      setLastReportPath(reports[0] ?? trimmedTargetDir);
      setResultText(finalResultText);
      setProgress(hasRetryableFailures ? Math.min(99, Math.round((retryIndex / Math.max(1, sourceFiles.length)) * 100)) : 100);
      if (hasRetryableFailures && activeSessionIdRef.current) {
        patchRetestSession(activeSessionIdRef.current, {
          status: finalStatus,
          progress: Math.min(99, Math.round((retryIndex / Math.max(1, sourceFiles.length)) * 100)),
          isRunning: false,
          resumeState: {
            canContinue: true,
            targetDir: trimmedTargetDir,
            sourceFiles,
            nextIndex: retryIndex,
            summaries,
            reports,
            completionItems: completionItems.map((item) => ({ ...item })),
            allLogs,
            failedCount,
            generateReports: true,
            blockedReason: '存在未完成的失败通报，继续时会从最早失败项重试。',
            blockedStage: 'retry_failed',
            blockedTitle: '失败项待重试',
          },
        });
      }
      appendFastLog(`${finalStatus}${reports.length ? `\n${formatPathList(reports)}` : ''}`);
    } catch (error: unknown) {
      setProgress(0);
      const reason = errorMessage(error);
      const failedStatus = `复测失败: ${reason}`;
      setStatus(failedStatus);
      setLog((current) => [current, failedStatus].filter(Boolean).join('\n'));
    } finally {
      setIsBusy(false);
    }
  };

  useEffect(() => {
    if (resumeAutoStartRef.current || isBusy) return;
    const requestedSessionId = consumeRetestResumeRequest();
    if (!requestedSessionId) return;
    const activeSession = readRetestSessionStore().sessions.find((item) => item.sessionId === requestedSessionId) ?? getActiveRetestSession();
    if (!activeSession || activeSession.sessionId !== requestedSessionId || !canResumeFromSessionContext(activeSession)) return;
    resumeAutoStartRef.current = true;
    void startAgentRetest(activeSession);
  }, [isBusy]);

  useEffect(() => {
    if (resumeAutoStartRef.current || isBusy) return;
    const requestedTargetDir = consumeRetestRerunRequest();
    if (!requestedTargetDir) return;
    resumeAutoStartRef.current = true;
    setTargetDir(requestedTargetDir);
    void startAgentRetest(null, requestedTargetDir);
  }, [isBusy]);

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
      <div className="doc-info-card" dangerouslySetInnerHTML={{ __html: '🛡️ <b>复测一键出</b><br>1. 选择包含【通报文档】的目录<br>2. AI Agent 复测会进入测试工作台，可对话追问并由模型判定<br>3. 快速复测不调用 AI 模型，会直接批量复测并生成报告<br>4. API 并发受限或想快速出结果时，优先使用快速复测' }} />
      <fieldset className="koi-group"><legend>📁 通报目录</legend><FileRow placeholder="选择包含通报Word文档的目录..." buttonText="📂 选择目录" title="选择通报目录" mode="directory" value={targetDir} onChange={setTargetDir} /></fieldset>
      <div className="action-row">
        <button type="button" className="koi-button primary" onClick={() => void startAgentRetest()} disabled={isBusy}>AI Agent 复测</button>
        <button type="button" className="koi-button secondary" onClick={() => void startFastRetest()} disabled={isBusy}>快速复测</button>
        <button type="button" className="koi-button secondary" onClick={openOutput}>📂 打开报告目录</button>
        <button type="button" className="koi-button secondary" onClick={resetRetestSession} disabled={isBusy}>清空结果</button>
      </div>
      <fieldset className="koi-group"><legend>复测状态</legend><div className="doc-status-label">{status}</div></fieldset>
      <fieldset className="koi-group" ref={resultPreviewRef}><legend>📜 复测结果预览（将对该区域自动截图写入复测报告）</legend><pre className="result-textarea retest-result-text retest-result-capture">{resultText || '复测结果将在这里展示，并作为证明截图写入复测报告。'}</pre></fieldset>
      <fieldset className="koi-group"><legend>📝 详细日志</legend><textarea className="result-textarea doc-log-text" readOnly value={log} /></fieldset>
    </div>
  );
}

