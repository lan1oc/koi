import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { repairRetestText } from './retestSessionStore';
import { FollowScroll } from './FollowScroll';

const statuses: Record<string, string> = { waiting: '等待模型', reasoning: '正在推理', receiving: '正在生成答复', completed: '本轮答复已完成', failed: '响应中断', cancelled: '已停止' };
const verdicts: Record<string, string> = { reproduced: '仍可复现', not_reproduced: '本次未复现', inconclusive: '证据不足，待核验', fixed: '已修复', risk: '仍有风险', clean: '本次未复现' };
const tools: Record<string, string> = { read_notice: '读取原通报', read_evidence: '检查已保存证据', http_request: '请求目标接口', run_python_probe: '运行 Python 验证脚本', run_preset_check: '执行验证工具', run_tls_probe: '检查 TLS 和证书' };
const text = (value: unknown) => typeof value === 'string' ? repairRetestText(value) : '';
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const records = (value: unknown) => Array.isArray(value) ? value.map(record).filter(item => Object.keys(item).length) : [];

function partialText(preview: string, key: string) {
  const match = preview.match(new RegExp(`"${key}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)`));
  if (!match) return '';
  try { return JSON.parse(`"${match[1]}"`) as string; }
  catch { return match[1].replace(/\\n/g, '\n').replace(/\\"/g, '"'); }
}

function readableDetail(value: unknown) {
  const detail = text(value);
  const start = detail.indexOf('{');
  if (start < 0) return detail;
  try {
    const data = record(JSON.parse(detail.slice(start)));
    const message = text(record(data.error).message || data.message || data.error);
    return `${detail.slice(0, start)}${message || '模型服务返回错误，当前证据已保留。'}`;
  } catch { return detail.slice(0, start) || '模型响应格式不完整，当前证据已保留。'; }
}

function FormattedText({ content, streaming = false }: { content: string; streaming?: boolean }) {
  const [limit, setLimit] = useState(20_000);
  return <div className="retest-model-prose retest-markdown">
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streaming ? content : content.slice(0, limit)}</ReactMarkdown>
    {!streaming && content.length > limit ? <button type="button" className="retest-model-read-more" onClick={() => setLimit(current => current + 20_000)}>继续展开正文</button> : null}
  </div>;
}

export function ModelResponseCard({ request, sourceFile, timestamp, round }: {
  request: Record<string, unknown>; sourceFile?: string; timestamp?: string; round?: unknown;
}) {
  const [loadError, setLoadError] = useState('');
  const [full, setFull] = useState<Record<string, unknown>>({});
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const status = text(request.status) || 'waiting';
  const path = text(request.response_path);
  useEffect(() => {
    if (!path || status !== 'completed') return;
    let active = true;
    setLoadError('');
    void invoke<string>('read_model_response', { path }).then(content => {
      if (active) setFull(record(JSON.parse(content)));
    }).catch(error => { if (active) setLoadError(error instanceof Error ? error.message : String(error)); });
    return () => { active = false; };
  }, [path, status]);
  useEffect(() => {
    if (status === 'reasoning') setReasoningOpen(true);
    if (status === 'completed') setReasoningOpen(false);
  }, [status]);
  const response = record(full.response || full);
  const preview = text(request.response_preview);
  const reply = text(response.reply || response.answer || response.message || response.summary || request.reply)
    || partialText(preview, 'reply') || partialText(preview, 'answer') || partialText(preview, 'summary');
  const plan = text(response.plan || request.summary) || partialText(preview, 'plan');
  const reasoning = text(full.reasoning || response.thinking || request.reasoning_text) || partialText(preview, 'thinking');
  const steps = records(response.steps || response.plan_steps || request.steps);
  const findings = records(response.findings || request.findings);
  const findingTitles = record(request.finding_titles);
  const findingName = (id: unknown) => text(findingTitles[text(id)]) || text(findings.find(item => item.id === id)?.title) || (text(id) ? `问题 ${text(id)}` : '当前问题');
  const actions = response.tool_calls ? records(response.tool_calls).map(call => ({ tool: call.tool || call.name, finding_id: call.finding_id, purpose: record(call.arguments || call.parameters).purpose })) : records(request.next_actions);
  const judgements = records(response.judgements || request.judgements);
  const elapsed = Math.round(Number(request.elapsed_ms || 0) / 1000);
  return <article className={`retest-model-response ${status}`} aria-label="模型响应">
    <div className="retest-model-response-head">
      <span className="retest-model-avatar" aria-hidden="true">AI</span>
      <div><strong>{statuses[status] || '模型响应'}</strong><span>{text(request.model) || '当前模型'}{round ? ` · 第 ${String(round)} 轮` : ''}</span></div>
      <time>{timestamp}</time>
    </div>
    {sourceFile ? <div className="retest-model-response-file">{sourceFile}</div> : null}
    <div className="retest-model-response-metrics"><span>用时 {elapsed} 秒</span>{reasoning ? <span>推理 {Number(request.reasoning_chars || reasoning.length).toLocaleString()} 字符</span> : null}<span>答复 {Number(request.received_chars || 0).toLocaleString()} 字符</span>{Number(request.attempt) > 1 ? <span>第 {String(request.attempt)} 次尝试</span> : null}</div>
    {reasoning ? <details className="retest-model-reasoning" open={reasoningOpen} onToggle={event => setReasoningOpen(event.currentTarget.open)}>
      <summary><span className="retest-model-section-badge reasoning">推理思考</span><span>{status === 'reasoning' ? '正在生成' : reasoningOpen ? '收起' : '展开查看'}</span></summary>
      <FollowScroll className="retest-model-reasoning-body" resetKey={`${path}:${request.profile_id || ''}:${request.attempt || 1}`} label="思考回到底部">
        <FormattedText content={reasoning} streaming={status === 'reasoning' || status === 'receiving'} />
      </FollowScroll>
    </details> : null}
    {reply ? <section className="retest-model-answer"><div className="retest-model-section-label"><span className="retest-model-section-badge answer">模型答复</span></div><FormattedText content={reply} /></section> : null}
    {plan || steps.length || actions.length ? <section className="retest-model-execution"><div className="retest-model-section-label"><span className="retest-model-section-badge execution">执行安排</span></div>
      {plan ? <FormattedText content={plan} /> : null}
      {steps.length ? <ol className="retest-model-steps">{steps.map((step, index) => <li key={text(step.id) || index}><strong>{text(step.title)}</strong>{text(step.purpose) ? <FormattedText content={text(step.purpose)} /> : null}</li>)}</ol> : null}
      {actions.length ? <div className="retest-model-next"><b>接下来</b><ul>{actions.map((action, index) => <li key={index}>{tools[text(action.tool)] || text(action.tool)} · {findingName(action.finding_id)}{text(action.purpose) ? `：${text(action.purpose)}` : ''}</li>)}</ul></div> : null}
    </section> : null}
    {judgements.length ? <section className="retest-model-response-judgements"><div className="retest-model-section-label"><span className="retest-model-section-badge verdict">证据判定</span></div>{judgements.map((judgement, index) => <div className={`retest-model-verdict ${text(judgement.verdict)}`} key={index}><strong>{findingName(judgement.finding_id)}</strong><span>{verdicts[text(judgement.verdict)] || text(judgement.verdict)}</span>{text(judgement.reason) ? <FormattedText content={text(judgement.reason)} /> : null}</div>)}</section> : null}
    {findings.length && !plan && !reply ? <section className="retest-model-findings"><div className="retest-model-section-label"><span className="retest-model-section-badge execution">待核验事项</span></div><ul>{findings.map((finding, index) => <li key={text(finding.id) || index}><strong>{text(finding.title)}</strong>{text(finding.validation_goal) ? <FormattedText content={text(finding.validation_goal)} /> : null}</li>)}</ul></section> : null}
    {['waiting','reasoning','receiving','failed','cancelled'].includes(status) ? <p className="retest-model-response-note">{readableDetail(request.detail) || '正在等待模型输出，可随时停止。'}</p> : null}
    {loadError ? <p className="retest-model-response-note error" role="status">{loadError}</p> : null}
  </article>;
}
