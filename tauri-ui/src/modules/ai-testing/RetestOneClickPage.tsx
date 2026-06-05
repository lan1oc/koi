import { useEffect, useRef, useState } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend } from '../../lib/backend';
import type { DialogFilter, FileOrDirectoryMode } from '../../lib/file-dialog';
import { navigateToFunction } from '../../lib/navigation-events';
import { openBackendPath } from '../../lib/open-path';
import {
  RETEST_RERUN_REQUEST_KEY,
  RETEST_RESUME_REQUEST_KEY,
  RETEST_RUNTIME_SESSION_KEY,
  appendRetestAgentMessage,
  appendRetestSessionEvent,
  appendRetestSessionEvents,
  createRetestSession,
  getActiveRetestSession,
  makeRetestAgentMessage,
  makeRetestSessionEvent,
  patchRetestSession,
  type RetestResumeState,
  type RetestSessionDraft,
  type RetestSessionEvent,
} from './retestSessionStore';
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

type RetestAgentStartResponse = {
  success: boolean;
  message: string;
  session_id?: string;
  running?: boolean;
  progress?: number;
  status?: string;
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
    .replace(/'/g, '&#39;');
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
    return {
      title: '模型响应超时',
      status: `模型响应超时: ${reason}`,
      instruction: '网络或模型恢复后，在测试工作台输入“继续”或点击“继续测试”，我会从当前通报继续。',
    };
  }
  if (title.includes('限流') || reason.includes('HTTP 429') || reason.includes('限流') || reason.includes('并发')) {
    return {
      title: '模型并发/限流',
      status: `模型并发/限流: ${reason}`,
      instruction: '稍后在测试工作台输入“继续”或点击“继续测试”，我会从当前通报继续。',
    };
  }
  if (stage === 'config' || title.includes('配置') || reason.includes('配置') || reason.includes('未启用')) {
    return {
      title: '待配置 AI',
      status: `待配置 AI: ${reason}`,
      instruction: '配置完成后，在测试工作台输入“继续”或点击“继续测试”，我会从当前通报继续。',
    };
  }
  return {
    title: title || 'AI 测试暂停',
    status: `${title || 'AI 测试暂停'}: ${reason}`,
    instruction: '处理暂停原因后，在测试工作台输入“继续”或点击“继续测试”，我会从当前通报继续。',
  };
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
    setStatus(activeSession.status || '等待开始复测...');
    setProgress(Number(activeSession.progress ?? 0));
    setResultText(activeSession.resultText || '');
    setLog(activeSession.log || '');
    setLastReportPath(activeSession.lastReportPath || '');
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
    const target = resultPreviewRef.current;
    const targetVisible = Boolean(target && target.getClientRects().length && target.offsetWidth > 0 && target.offsetHeight > 0);
    let captureTarget: HTMLElement | HTMLFieldSetElement | null = targetVisible ? target : null;
    let temporaryTarget: HTMLElement | null = null;

    if (!captureTarget) {
      temporaryTarget = document.createElement('div');
      temporaryTarget.className = 'retest-result-capture retest-result-capture-clone';
      temporaryTarget.innerHTML = `<div class="retest-capture-title">复测结果预览</div><pre>${escapeHtml(fallbackText || resultText || '复测结果将在这里展示，并作为证明截图写入复测报告。')}</pre>`;
      document.body.appendChild(temporaryTarget);
      captureTarget = temporaryTarget;
      await wait(30);
    }

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

  const startRetest = async (resumeSession?: RetestSessionDraft | null, overrideTargetDir = '') => {
    const resumeState = resumeSession?.resumeState?.canContinue ? resumeSession.resumeState : null;
    const isResume = Boolean(resumeSession && resumeState);
    const legacyResumeState = resumeState;
    const trimmedTargetDir = (resumeState?.targetDir || resumeSession?.targetDir || overrideTargetDir || targetDir).trim();
    if (!trimmedTargetDir) {
      setStatus('请先选择通报目录');
      return;
    }

    if (isResume && resumeSession) {
      activeSessionIdRef.current = resumeSession.sessionId;
      window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, resumeSession.sessionId);
      pushAgentMessage('system', `从断点继续测试：${trimmedTargetDir}\n下一份通报序号：${(resumeState?.nextIndex ?? 0) + 1}`, '继续测试');
      navigateToFunction('ai-testing', 'test-workbench');
    } else {
      const openingMessage = makeRetestAgentMessage('system', `目标目录：${trimmedTargetDir}\n已创建测试会话，开始读取通报并规划复测。`, '会话启动');
      const session = createRetestSession(trimmedTargetDir, [openingMessage]);
      activeSessionIdRef.current = session.sessionId;
      window.sessionStorage.setItem(RETEST_RUNTIME_SESSION_KEY, session.sessionId);
      navigateToFunction('ai-testing', 'test-workbench');
    }

    setIsBusy(true);
    setTargetDir(trimmedTargetDir);
    setProgress(isResume ? Math.max(0, Math.min(100, Number(resumeSession?.progress ?? 0))) : 5);
    setStatus(isResume ? '正在从断点继续复测...' : '正在扫描通报目录...');
    setResultText(isResume ? resumeSession?.resultText || '' : '');
    setLog(isResume ? resumeSession?.log || '' : '');
    setLastReportPath(isResume ? resumeSession?.lastReportPath || '' : '');
    setLatestResultData(isResume && resumeSession?.latestResultData ? resumeSession.latestResultData : null);
    syncSession({
      targetDir: trimmedTargetDir,
      status: isResume ? '正在从断点继续复测...' : '正在扫描通报目录...',
      progress: isResume ? Math.max(0, Math.min(100, Number(resumeSession?.progress ?? 0))) : 5,
      resultText: isResume ? resumeSession?.resultText || '' : '',
      log: isResume ? resumeSession?.log || '' : '',
      lastReportPath: isResume ? resumeSession?.lastReportPath || '' : '',
      latestResultData: isResume && resumeSession?.latestResultData ? resumeSession.latestResultData : null,
      isRunning: true,
      resumeState: resumeState ? { ...resumeState, canContinue: false } : null,
    });

    try {
      const sessionId = activeSessionIdRef.current;
      if (!sessionId) throw new Error('缺少测试会话 ID');
      const message = isResume ? '继续测试并生成报告' : '一键复测并生成报告';
      const result = await callBackend<RetestAgentStartResponse>('doc.retest.agent.start', {
        session_id: sessionId,
        target_dir: trimmedTargetDir,
        message,
        generate_reports: true,
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
      setIsBusy(false);
    }

    try {
      let sourceFiles = legacyResumeState?.sourceFiles ?? [];
      let listLogs: string[] = [];
      let startIndex = Math.min(Math.max(0, legacyResumeState?.nextIndex ?? 0), sourceFiles.length);

      if (!legacyResumeState) {
        const listResult = await callBackend<RetestListFilesResponse>('doc.retest.list_files', { target_dir: trimmedTargetDir });
        sourceFiles = listResult.source_files ?? [];
        listLogs = listResult.logs ?? [];
        pushAgentMessage('agent', `发现 ${sourceFiles.length} 份通报文档。${listLogs.length ? `\n${listLogs.slice(-4).join('\n')}` : ''}`, '文档扫描', sourceFiles.length ? 'ok' : 'warn');
        if (!sourceFiles.length) {
          const nextLog = joinLogs(listResult.logs);
          setProgress(0);
          setStatus(listResult.message || '未找到通报文档。');
          setLog(nextLog);
          syncSession({ progress: 0, status: listResult.message || '未找到通报文档。', log: nextLog, isRunning: false, resumeState: null });
          return;
        }
      } else {
        pushAgentMessage('agent', `恢复原队列：共 ${sourceFiles.length} 份通报，已完成 ${startIndex} 份。`, '断点恢复', 'ok');
      }

      const allLogs = [...(legacyResumeState?.allLogs ?? listLogs)];
      const summaries: string[] = [...(legacyResumeState?.summaries ?? [])];
      const reports: string[] = [...(legacyResumeState?.reports ?? [])];
      const completionItems: RetestCompletionItem[] = asCompletionItems(legacyResumeState?.completionItems);
      let failedCount = Number(legacyResumeState?.failedCount || 0);
      setLog(joinLogs(allLogs));
      syncSession({ log: joinLogs(allLogs) });

      const buildResumeState = (nextIndex: number, canContinue: boolean, blocked?: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse): RetestResumeState => ({
        canContinue,
        targetDir: trimmedTargetDir,
        sourceFiles,
        nextIndex: Math.max(0, Math.min(sourceFiles.length, nextIndex)),
        summaries,
        reports,
        completionItems: completionItems.map((item) => ({ ...item })),
        allLogs,
        failedCount,
        generateReports: true,
        blockedReason: blocked?.message,
        blockedStage: blocked?.blocked_stage,
        blockedTitle: blocked?.blocked_title,
      });

      const stopForAiConfig = (index: number, blocked: RetestRunOneResponse | RetestRunOneStatusResponse | RetestRunOneStartResponse) => {
        const pause = describeAiPause(blocked);
        const reason = blocked.message || pause.status;
        const blockedStatus = pause.status;
        allLogs.push(reason);
        const resumePayload = buildResumeState(index, true, blocked);
        const nextLog = joinLogs(allLogs);
        setStatus(blockedStatus);
        setLog(nextLog);
        setProgress(Math.round((index / sourceFiles.length) * 100));
        syncSession({
          status: blockedStatus,
          log: nextLog,
          progress: Math.round((index / sourceFiles.length) * 100),
          isRunning: false,
          resumeState: resumePayload,
        });
        pushAgentMessage('agent', `${reason}\n${pause.instruction}\n断点位置：${getFileName(sourceFiles[index] || '') || '下一份通报'}，不会重复已完成通报。`, pause.title, 'warn');
        appendRetestSessionEvent(
          activeSessionIdRef.current,
          makeRetestSessionEvent('error', pause.title, reason, 'warn', {
            metadata: {
              phase: blocked.blocked_stage || 'config',
              blockedByAiConfig: true,
              resumeState: resumePayload,
            },
          }),
        );
      };

      for (let index = startIndex; index < sourceFiles.length; index += 1) {
        const sourceFile = sourceFiles[index];
        const fileLabel = getFileName(sourceFile);
        const nextProgress = Math.max(5, Math.round((index / sourceFiles.length) * 100));
        const nextStatus = `正在复测 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
        setProgress(nextProgress);
        setStatus(nextStatus);
        syncSession({ progress: nextProgress, status: nextStatus, isRunning: true });
        pushAgentMessage('agent', `开始解析通报并规划复测：${fileLabel}`, `通报 ${index + 1}/${sourceFiles.length}`);

        try {
          const seenTraceEventIds = new Set<string>();
          let fileLogCount = 0;
          const appendNewTraceEvents = (events?: RetestSessionEvent[]) => {
            const nextEvents = (events ?? []).filter((event) => {
              if (!event?.id || seenTraceEventIds.has(event.id)) return false;
              seenTraceEventIds.add(event.id);
              return true;
            });
            if (nextEvents.length) {
              appendRetestSessionEvents(activeSessionIdRef.current, nextEvents);
            }
          };
          const mergeFileLogs = (logs?: string[]) => {
            const nextLogs = logs ?? [];
            if (nextLogs.length <= fileLogCount) return;
            allLogs.push(...nextLogs.slice(fileLogCount));
            fileLogCount = nextLogs.length;
            const nextLog = joinLogs(allLogs);
            setLog(nextLog);
            syncSession({ log: nextLog });
          };

          const startResult = await callBackend<RetestRunOneStartResponse>('doc.retest.run_one.start', {
            source_file: sourceFile,
            session_id: activeSessionIdRef.current,
            round_id: `file-${index + 1}`,
            source_file_name: fileLabel,
          });
          mergeFileLogs(startResult.logs);
          appendNewTraceEvents(startResult.trace_events);
          if (startResult.blocked_by_ai_config) {
            stopForAiConfig(index, startResult);
            return;
          }
          if (!startResult.success || !startResult.task_id) {
            throw new Error(startResult.message || '单个通报复测任务启动失败');
          }

          let runResult: RetestRunOneStatusResponse | RetestRunOneStartResponse = startResult;
          while (true) {
            await wait(650);
            const statusResult = await callBackend<RetestRunOneStatusResponse>('doc.retest.run_one.status', { task_id: startResult.task_id });
            runResult = statusResult;
            mergeFileLogs(statusResult.logs);
            appendNewTraceEvents(statusResult.trace_events);
            const streamedProgress = Math.min(98, Math.round(((index + ((statusResult.progress ?? 0) / 100)) / sourceFiles.length) * 100));
            const streamedStatus = statusResult.message || nextStatus;
            setProgress(streamedProgress);
            setStatus(streamedStatus);
            syncSession({ progress: streamedProgress, status: streamedStatus, isRunning: true });
            if (statusResult.done) break;
          }
          if (runResult.blocked_by_ai_config) {
            stopForAiConfig(index, runResult);
            return;
          }
          if (!runResult.success) {
            throw new Error(runResult.message || '单个通报复测失败');
          }

          const summary = runResult.summary || `${fileLabel}\n复测结果为空`;
          summaries.push(summary);
          setResultText(summary);
          setLatestResultData(runResult.result_data ?? null);
          syncSession({ resultText: summary, latestResultData: runResult.result_data ?? null, log: joinLogs(allLogs) });

          await wait(120);
          const reportStatus = `正在截图并写入报告 (${index + 1}/${sourceFiles.length}): ${fileLabel}`;
          setStatus(reportStatus);
          syncSession({ status: reportStatus });
          pushAgentMessage('agent', '复测结果已生成，正在截取结果预览并写入报告模板。', '报告生成');
          const screenshotDataUrl = await captureRetestResultScreenshot(summary);
          const reportResult = await callBackend<RetestGenerateReportsResponse>('doc.retest.generate_reports_with_screenshot', {
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
            pushAgentMessage('agent', reportFailureText, '报告生成失败', 'error');
            appendRetestSessionEvent(activeSessionIdRef.current, makeRetestSessionEvent('error', '报告生成失败', reportFailureText, 'error'));
          } else {
            const reportArtifactText = reportResult.reports?.length ? `报告已生成：\n${formatPathList(reportResult.reports)}` : '报告生成命令已完成。';
            pushAgentMessage('agent', reportArtifactText, '报告完成', 'ok');
            appendRetestSessionEvent(
              activeSessionIdRef.current,
              makeRetestSessionEvent('artifact', '报告生成完成', reportArtifactText, 'ok', { metadata: { reports: reportResult.reports ?? [] } }),
            );
          }
          const resultWithReport = [
            summary,
            reportResult.reports?.length ? `\n生成报告:\n${formatPathList(reportResult.reports)}` : '',
          ].filter(Boolean).join('\n');
          const completionItem = buildCompletionItem(sourceFile, runResult, reportResult);
          completionItems.push(completionItem);
          pushAgentMessage(
            'agent',
            formatRetestResultMessage(fileLabel, runResult, completionItem, reportResult),
            '复测结果',
            completionItem.status === 'risk' ? 'warn' : completionItem.status === 'failed' ? 'error' : 'ok',
          );
          const reportLog = joinLogs(allLogs);
          setLastReportPath(reports[0] ?? trimmedTargetDir);
          setResultText(resultWithReport);
          setLog(reportLog);
          syncSession({
            lastReportPath: reports[0] ?? trimmedTargetDir,
            resultText: resultWithReport,
            log: reportLog,
            resumeState: buildResumeState(index + 1, false),
          });
        } catch (itemError: unknown) {
          failedCount += 1;
          const reason = errorMessage(itemError);
          allLogs.push(`${fileLabel} 处理失败: ${reason}`);
          const failedLog = joinLogs(allLogs);
          setLog(failedLog);
          syncSession({ log: failedLog });
          pushAgentMessage('agent', `${fileLabel} 处理失败：${reason}`, '复测错误', 'error');
          completionItems.push(buildCompletionItem(sourceFile, undefined, undefined, reason));
        }

        const completedProgress = Math.round(((index + 1) / sourceFiles.length) * 100);
        setProgress(completedProgress);
        syncSession({ progress: completedProgress, resumeState: buildResumeState(index + 1, false) });
      }

      const finalStatus = `复测完成：处理 ${sourceFiles.length} 份文档，生成 ${reports.length} 份报告${failedCount ? `，失败 ${failedCount} 份` : ''}`;
      const completionOverview = formatCompletionOverview(completionItems);
      const finalResultText = [
        completionOverview,
        summaries.length ? '\n详细复测摘要:' : '',
        summaries.join('\n\n'),
        reports.length ? `\n生成报告:\n${formatPathList(reports)}` : '',
      ].filter(Boolean).join('\n');
      appendRetestSessionEvent(
        activeSessionIdRef.current,
        makeRetestSessionEvent('artifact', '复测结论总览', completionOverview, failedCount ? 'warn' : 'ok', {
          metadata: {
            phase: 'completion_summary',
            summaryTitle: '复测结论总览',
            completionItems,
            fixStatus: completionItems.some((item) => item.status === 'risk') ? 'risk' : (failedCount ? 'failed' : 'clean'),
            evidenceLevel: 'summary',
          },
        }),
      );
      setStatus(finalStatus);
      setLastReportPath(reports[0] ?? trimmedTargetDir);
      setResultText(finalResultText);
      setProgress(100);
      syncSession({ status: finalStatus, lastReportPath: reports[0] ?? trimmedTargetDir, resultText: finalResultText, progress: 100, isRunning: false, resumeState: null });
      pushAgentMessage('agent', `${finalStatus}${reports.length ? `\n${formatPathList(reports)}` : ''}`, '会话完成', failedCount ? 'warn' : 'ok');
    } catch (error: unknown) {
      setProgress(0);
      const reason = errorMessage(error);
      const failedStatus = `复测失败: ${reason}`;
      setStatus(failedStatus);
      syncSession({ progress: 0, status: failedStatus, isRunning: false });
      pushAgentMessage('agent', `复测失败：${reason}`, '会话错误', 'error');
    } finally {
      setIsBusy(false);
      window.sessionStorage.removeItem(RETEST_RESUME_REQUEST_KEY);
      resumeAutoStartRef.current = false;
      syncSession({ isRunning: false });
    }
  };

  useEffect(() => {
    if (resumeAutoStartRef.current || isBusy) return;
    const requestedSessionId = window.sessionStorage.getItem(RETEST_RESUME_REQUEST_KEY);
    if (!requestedSessionId) return;
    const activeSession = getActiveRetestSession();
    if (!activeSession || activeSession.sessionId !== requestedSessionId || !activeSession.resumeState?.canContinue) return;
    resumeAutoStartRef.current = true;
    void startRetest(activeSession);
  }, [isBusy]);

  useEffect(() => {
    if (resumeAutoStartRef.current || isBusy) return;
    const requestedTargetDir = window.sessionStorage.getItem(RETEST_RERUN_REQUEST_KEY);
    if (!requestedTargetDir) return;
    window.sessionStorage.removeItem(RETEST_RERUN_REQUEST_KEY);
    resumeAutoStartRef.current = true;
    setTargetDir(requestedTargetDir);
    void startRetest(null, requestedTargetDir);
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
      <div className="doc-info-card" dangerouslySetInnerHTML={{ __html: '🛡️ <b>复测一键出</b><br>1. 选择包含【通报文档】的目录<br>2. 自动扫描Word获取漏洞类型和URL<br>3. 自动对URL进行批量复测并在下方展示结果<br>4. 点击一键复测后会进入 AI测试 / 测试工作台，可查看 Agent 执行流并追问' }} />
      <fieldset className="koi-group"><legend>📁 通报目录</legend><FileRow placeholder="选择包含通报Word文档的目录..." buttonText="📂 选择目录" title="选择通报目录" mode="directory" value={targetDir} onChange={setTargetDir} /></fieldset>
      <div className="action-row"><button type="button" className="koi-button primary" onClick={() => void startRetest()} disabled={isBusy}>🚀 一键复测</button><button type="button" className="koi-button secondary" onClick={openOutput}>📂 打开报告目录</button><button type="button" className="koi-button secondary" onClick={resetRetestSession} disabled={isBusy}>清空结果</button></div>
      <fieldset className="koi-group"><legend>复测状态</legend><div className="doc-status-label">{status}</div></fieldset>
      <fieldset className="koi-group" ref={resultPreviewRef}><legend>📜 复测结果预览（将对该区域自动截图写入复测报告）</legend><pre className="result-textarea retest-result-text retest-result-capture">{resultText || '复测结果将在这里展示，并作为证明截图写入复测报告。'}</pre></fieldset>
      <fieldset className="koi-group"><legend>📝 详细日志</legend><textarea className="result-textarea doc-log-text" readOnly value={log} /></fieldset>
    </div>
  );
}

