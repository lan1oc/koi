import { useState } from 'react';
import { callBackend } from '../../lib/backend';
import type { KoiModule } from '../../lib/types';

type WeeklyReportResponse = {
  report: string;
  status: 'success' | 'failed';
  range: string;
  detail: string;
};

type StatusState = 'waiting' | 'processing' | 'success' | 'error' | 'info';

function SelectInput({ options, value, onChange, disabled = false }: { options: string[]; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <select className="koi-input" value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      {options.map((option) => <option key={option}>{option}</option>)}
    </select>
  );
}

function WeeklyReportPage() {
  const [range, setRange] = useState('本周工作日');
  const [detail, setDetail] = useState('简要报告');
  const [statusText, setStatusText] = useState('等待生成...');
  const [statusState, setStatusState] = useState<StatusState>('waiting');
  const [report, setReport] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  const handleGenerate = async () => {
    setIsGenerating(true);
    setStatusText('正在收集文件活动记录...');
    setStatusState('processing');

    try {
      const result = await callBackend<WeeklyReportResponse>('weekly_report.generate', {
        range,
        detail,
        detailed: detail.startsWith('详细'),
      });

      setReport(result.report);
      if (result.status === 'failed') {
        setStatusText('生成失败');
        setStatusState('error');
      } else {
        setStatusText('生成完成');
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
              <span>📅 统计时间范围:</span>
              <SelectInput options={['本周工作日', '最近3天', '最近7天', '最近14天', '最近30天']} value={range} onChange={setRange} disabled={isGenerating} />
            </label>
            <label className="field-row weekly-field-label">
              <span>📋 报告详细程度:</span>
              <SelectInput options={['简要报告', '详细报告']} value={detail} onChange={setDetail} disabled={isGenerating} />
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
