import { useState } from 'react';
import type { RetestSessionDraft } from './retestSessionStore';

type PlanStep = { id?: string; title?: string; purpose?: string; tools?: string[]; status?: string; evidence_ids?: string[] };
const labels: Record<string, string> = {pending:'待执行',running:'执行中',completed:'已执行',failed:'执行失败',inconclusive:'待核验'};

export function RetestPlanCard({session}: {session: RetestSessionDraft}) {
  const [expanded,setExpanded] = useState(false);
  const checkpoint = session.resumeState?.currentFile?.resumeSnapshot;
  const activeFile=session.retestProgress?.file as Record<string,unknown>|undefined;
  const storedPlan=session.retestPlan ?? checkpoint?.agent_plan as Record<string,unknown> | undefined;
  const key=(value:unknown)=>String(value || '').replace(/^\\\\\?\\/,'').replace(/\\/g,'/').toLowerCase();
  const plan=activeFile?.sourceFile && key(activeFile.sourceFile)!==key(storedPlan?.sourceFile)?undefined:storedPlan;
  const steps = (Array.isArray(plan?.steps) ? plan.steps : []) as PlanStep[];
  const model = plan?.modelRequest as {model?:string; transport?:string; attempt?:number; detail?:string} | undefined;
  const file = String(activeFile?.sourceFileName || plan?.sourceFileName || session.resumeState?.currentFile?.sourceFileName || '当前通报');
  const done = steps.filter(step=>step.status==='completed').length;
  const current = steps.find(step=>step.status==='running');
  const action = String(plan?.action || '正在读取原通报，等待模型返回具体复测步骤。');
  const reportPaths = session.resumeState?.completionItems.filter(item=>item.sourceFile===plan?.sourceFile).flatMap(item=>Array.isArray(item.reportPaths)?item.reportPaths:[]) ?? [];
  return <details className="retest-plan-card" open={expanded} onToggle={event=>setExpanded(event.currentTarget.open)}>
    <summary>
      <strong>当前通报复测计划</strong>
      <span className="retest-plan-current">{current?.title || action}</span>
      <span className="retest-plan-count">{steps.length ? `${done}/${steps.length} 步已执行` : '规划中'}</span>
      <span className="retest-plan-toggle">{expanded?'收起':'展开'}</span>
    </summary>
    <div className="retest-plan-body">
      <div className="retest-plan-file" title={String(plan?.sourceFile || '')}>{file}</div>
      {model?.model ? <div className="retest-plan-model">当前模型：{model.model} · {model.transport==='json'?'完整响应':'流式响应'}{Number(model.attempt)>1?' · 正在重试':''}</div> : null}
      <p className="retest-plan-action">{action}</p>
      {steps.length ? <ol>{steps.map((step,index)=><li key={step.id || index} data-status={step.status || 'pending'}>
        <div><b>{step.title}</b><span>{labels[step.status || 'pending'] || '待执行'}</span></div>
        {step.purpose ? <p>{step.purpose}</p> : null}
        {step.tools?.length ? <small>工具：{step.tools.join('、')}{step.evidence_ids?.length?` · 已保存证据 ${step.evidence_ids.join('、')}`:''}</small> : null}
      </li>)}</ol> : <p>模型返回的步骤会显示在这里，执行情况随实际工具结果更新。</p>}
      {session.generateReports ? <div className="retest-plan-report">复测报告：{reportPaths.length?'已生成':plan?.finished?'正在准备报告':'完成取证和判定后生成'}</div> : null}
    </div>
  </details>;
}
