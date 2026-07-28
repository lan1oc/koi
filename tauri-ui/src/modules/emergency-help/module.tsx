import { useEffect, useRef, useState } from 'react';
import { useProjectFileDialog } from '../../components/common/ProjectFileDialog';
import { callBackend } from '../../lib/backend';
import type { KoiModule } from '../../lib/types';

type WeeklyReportResponse = {
  report: string;
  status: 'success' | 'failed';
  vulnerability_notice_dir?: string;
  event_notice_dir?: string;
  exclude_monday_next_notice?: boolean;
  report_date?: string;
  summary?: {
    records?: {
      vulnerability?: number;
      event?: number;
    };
    windows?: {
      current_week_start?: string;
      current_week_end?: string;
      next_week_start?: string;
      next_week_end?: string;
      current_closure_start?: string;
      current_closure_end?: string;
      current_notice_start?: string;
      current_notice_end?: string;
      next_notice_start?: string;
      next_notice_end?: string;
      event_completed_start?: string;
      event_completed_end?: string;
    };
  };
};

type WeeklyReportConfigResponse = {
  vulnerability_notice_dir: string;
  event_notice_dir: string;
  exclude_monday_next_notice?: boolean;
  last_updated?: string;
};

type StatusState = 'waiting' | 'processing' | 'success' | 'error' | 'info';

function formatDateInput(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseDateInput(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return new Date();
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  return new Date(year, month - 1, day);
}

function shiftDateInput(value: string, days: number) {
  const date = parseDateInput(value);
  date.setDate(date.getDate() + days);
  return formatDateInput(date);
}

function WeeklyReportPage() {
  const [vulnerabilityNoticeDir, setVulnerabilityNoticeDir] = useState('');
  const [eventNoticeDir, setEventNoticeDir] = useState('');
  const [excludeMondayNextNotice, setExcludeMondayNextNotice] = useState(false);
  const [reportDate, setReportDate] = useState(() => formatDateInput(new Date()));
  const [statusText, setStatusText] = useState('等待生成...');
  const [statusState, setStatusState] = useState<StatusState>('waiting');
  const [report, setReport] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const configEditRevisionRef = useRef(0);
  const { dialog: fileDialog, openDirectoryPath } = useProjectFileDialog();

  useEffect(() => {
    let cancelled = false;
    const expectedRevision = configEditRevisionRef.current;
    callBackend<WeeklyReportConfigResponse>('weekly_report.config.get', {})
      .then((config) => {
        if (cancelled || configEditRevisionRef.current !== expectedRevision) return;
        setVulnerabilityNoticeDir(config.vulnerability_notice_dir || '');
        setEventNoticeDir(config.event_notice_dir || '');
        setExcludeMondayNextNotice(Boolean(config.exclude_monday_next_notice));
      })
      .catch(() => {
        if (cancelled) return;
        setStatusText('等待生成...');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const invalidateReport = () => {
    setReport('');
    setStatusText('生成参数已更新，等待重新生成...');
    setStatusState('info');
  };

  const updateVulnerabilityNoticeDir = (value: string) => {
    configEditRevisionRef.current += 1;
    setVulnerabilityNoticeDir(value);
    invalidateReport();
  };

  const updateEventNoticeDir = (value: string) => {
    configEditRevisionRef.current += 1;
    setEventNoticeDir(value);
    invalidateReport();
  };

  const updateReportDate = (value: string) => {
    if (value === reportDate) return;
    setReportDate(value);
    invalidateReport();
  };

  const saveConfig = async (vulnerabilityDir: string, eventDir: string, excludeMonday: boolean) => {
    try {
      await callBackend<WeeklyReportConfigResponse>('weekly_report.config.set', {
        vulnerability_notice_dir: vulnerabilityDir,
        event_notice_dir: eventDir,
        exclude_monday_next_notice: excludeMonday,
      });
    } catch {
      // 生成时还会再保存一次；这里不打断路径选择。
    }
  };

  const chooseDirectory = async (target: 'vulnerability' | 'event') => {
    const title = target === 'vulnerability' ? '选择漏洞通报路径' : '选择事件通报路径';
    const selected = await openDirectoryPath({ title });
    if (selected) {
      if (target === 'vulnerability') {
        updateVulnerabilityNoticeDir(selected);
      } else {
        updateEventNoticeDir(selected);
      }
      const nextVulnerabilityDir = target === 'vulnerability' ? selected : vulnerabilityNoticeDir;
      const nextEventDir = target === 'event' ? selected : eventNoticeDir;
      await saveConfig(nextVulnerabilityDir, nextEventDir, excludeMondayNextNotice);
    }
  };

  const handleExcludeMondayChange = (checked: boolean) => {
    configEditRevisionRef.current += 1;
    setExcludeMondayNextNotice(checked);
    invalidateReport();
    void saveConfig(vulnerabilityNoticeDir, eventNoticeDir, checked);
  };

  const handleGenerate = async () => {
    if (!vulnerabilityNoticeDir.trim() && !eventNoticeDir.trim()) {
      setStatusText('请先设置漏洞通报路径或事件通报路径');
      setStatusState('error');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(reportDate)) {
      setStatusText('请选择周报基准日期');
      setStatusState('error');
      return;
    }

    setIsGenerating(true);
    setReport('');
    setStatusText('正在读取通报路径并生成闭环周报...');
    setStatusState('processing');

    try {
      const result = await callBackend<WeeklyReportResponse>('weekly_report.generate', {
        vulnerability_notice_dir: vulnerabilityNoticeDir,
        event_notice_dir: eventNoticeDir,
        exclude_monday_next_notice: excludeMondayNextNotice,
        report_date: reportDate,
      });

      setReport(result.report);
      if (result.vulnerability_notice_dir !== undefined) setVulnerabilityNoticeDir(result.vulnerability_notice_dir);
      if (result.event_notice_dir !== undefined) setEventNoticeDir(result.event_notice_dir);
      if (result.exclude_monday_next_notice !== undefined) setExcludeMondayNextNotice(Boolean(result.exclude_monday_next_notice));
      if (result.report_date) setReportDate(result.report_date);
      if (result.status === 'failed') {
        setStatusText('生成失败');
        setStatusState('error');
      } else {
        const vulnerabilityCount = result.summary?.records?.vulnerability ?? 0;
        const eventCount = result.summary?.records?.event ?? 0;
        const weekStart = result.summary?.windows?.current_week_start;
        const weekEnd = result.summary?.windows?.current_week_end;
        const currentNoticeStart = result.summary?.windows?.current_notice_start;
        const currentNoticeEnd = result.summary?.windows?.current_notice_end;
        const nextNoticeStart = result.summary?.windows?.next_notice_start;
        const nextNoticeEnd = result.summary?.windows?.next_notice_end;
        const currentNoticeLabel = currentNoticeStart && currentNoticeEnd ? `${currentNoticeStart} 至 ${currentNoticeEnd}` : '';
        const nextNoticeLabel = nextNoticeStart && nextNoticeEnd ? `${nextNoticeStart} 至 ${nextNoticeEnd}` : '';
        setStatusText(weekStart && weekEnd
          ? `生成完成：有效漏洞通报 ${vulnerabilityCount} 条，事件处置 ${eventCount} 条；周报 ${weekStart} 至 ${weekEnd}，已整改通报 ${currentNoticeLabel}，待处置通报 ${nextNoticeLabel}`
          : '生成完成');
        setStatusState('success');
      }
    } catch (error) {
      setReport(`生成报告时出错: ${error instanceof Error ? error.message : String(error)}`);
      setStatusText('生成失败');
      setStatusState('error');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleClear = () => {
    setReport('');
    setStatusText('等待生成...');
    setStatusState('waiting');
  };

  return (
    <div className="weekly-report-layout scroll-page-layout">
      <section className="weekly-control-panel">
        <div className="weekly-control-scroll">
          <h2 className="weekly-section-title">📝 周报生成器</h2>

          <fieldset className="koi-group weekly-config-group">
            <legend>⚙️ 生成配置</legend>
            <label className="field-row weekly-field-label">
              <span>漏洞通报路径:</span>
              <div className="weekly-path-row">
                <input className="koi-input" value={vulnerabilityNoticeDir} onChange={(event) => updateVulnerabilityNoticeDir(event.target.value)} placeholder="选择漏洞通报目录" disabled={isGenerating} />
                <button type="button" className="koi-button secondary compact-button" onClick={() => void chooseDirectory('vulnerability')} disabled={isGenerating}>📂</button>
              </div>
            </label>
            <label className="field-row weekly-field-label">
              <span>事件通报路径:</span>
              <div className="weekly-path-row">
                <input className="koi-input" value={eventNoticeDir} onChange={(event) => updateEventNoticeDir(event.target.value)} placeholder="选择事件通报目录" disabled={isGenerating} />
                <button type="button" className="koi-button secondary compact-button" onClick={() => void chooseDirectory('event')} disabled={isGenerating}>📂</button>
              </div>
            </label>
            <label className="checkbox-row weekly-option-row">
              <input type="checkbox" checked={excludeMondayNextNotice} onChange={(event) => handleExcludeMondayChange(event.target.checked)} disabled={isGenerating} />
              下周待处置不统计本周周一通报
            </label>
            <label className="field-row weekly-field-label">
              <span>周报基准日期:</span>
              <div className="weekly-date-row">
                <input className="koi-input" type="date" value={reportDate} onChange={(event) => updateReportDate(event.target.value)} disabled={isGenerating} />
                <button type="button" className="koi-button secondary compact-button" onClick={() => updateReportDate(formatDateInput(new Date()))} disabled={isGenerating}>本周</button>
                <button type="button" className="koi-button secondary compact-button" onClick={() => updateReportDate(shiftDateInput(reportDate, -7))} disabled={isGenerating}>上一周</button>
              </div>
            </label>
          </fieldset>

          <fieldset className="koi-group weekly-config-group">
            <legend>🎯 操作</legend>
            <button type="button" className="koi-button primary full-width-button" onClick={handleGenerate} disabled={isGenerating}>🚀 生成周报</button>
            <button type="button" className="koi-button secondary full-width-button" onClick={handleClear} disabled={isGenerating}>🗑️ 清空结果</button>
          </fieldset>

          <fieldset className="koi-group weekly-config-group">
            <legend>📊 状态</legend>
            <div className={`weekly-status-label ${statusState}`}>{statusText}</div>
          </fieldset>
        </div>
      </section>

      <section className="weekly-result-panel">
        <h2 className="weekly-section-title">📄 周报结果</h2>
        <textarea className="result-textarea weekly-result-text" placeholder="周报内容将在这里显示..." value={report} onChange={(event) => setReport(event.target.value)} />
      </section>
      {fileDialog}
    </div>
  );
}

export const emergencyHelpModule: KoiModule = {
  id: 'emergency-help',
  title: '江湖救急',
  functions: [
    {
      id: 'weekly-report',
      title: '📝 周报生成',
      component: WeeklyReportPage,
    },
  ],
};
