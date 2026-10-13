import type { RetestSessionDraft } from './retestSessionStore';

const phases: Record<string,string> = {reading:'读取原通报',planning:'制定复测计划',investigating:'工具核验',judging:'逐项判定',reporting:'生成报告',completed:'本份处理完成'};
const stages=['reading','planning','investigating','judging','reporting','completed'];

export function RetestProgressPanel({session}: {session: RetestSessionDraft}) {
  const queue=session.retestProgress;
  const file=queue?.file as Record<string,unknown>|undefined;
  const total=Number(queue?.total || session.resumeState?.sourceFiles.length || 0);
  const completed=Number(queue?.completed ?? session.resumeState?.completionItems.length ?? 0);
  const totalPercent=total?Math.min(100,Math.floor(completed*100/total)):0;
  const phase=String(file?.phase || session.retestPlan?.phase || 'reading');
  const filePercent=Number(file?.percent ?? ({reading:10,planning:25,investigating:55,judging:80,reporting:90,completed:100} as Record<string,number>)[phase] ?? 0);
  const source=String(file?.sourceFile || session.retestPlan?.sourceFile || session.resumeState?.currentFile?.sourceFile || '');
  const name=String(file?.sourceFileName || source.split(/[\\/]/).pop() || '等待选择通报');
  const paused=!session.isRunning && phase!=='completed';
  return <section className="retest-progress-panel" aria-label="复测进度">
    <div className="retest-progress-total">
      <div className="retest-progress-label"><strong>总进度</strong><span>已完成 {completed} / {total || '—'} 份</span><b>{totalPercent}%</b></div>
      <progress aria-label="通报总进度" value={totalPercent} max={100} />
      <small>{total?`剩余 ${Math.max(0,total-completed)} 份通报`: '等待后台同步通报清单'}</small>
    </div>
    <div className={`retest-progress-file${paused?' paused':''}`} data-source-file={source}>
      <div className="retest-progress-label"><strong>本份进度</strong><span>{phases[phase] || '等待执行'}{paused?' · 已暂停':''}</span><b>{Math.min(100,filePercent)}%</b></div>
      <progress aria-label="当前通报进度" value={filePercent} max={100} />
      <div className="retest-progress-name" title={source}>{name}</div>
      <div className="retest-progress-stages">{stages.map((stage,index)=><span key={stage} className={index<stages.indexOf(phase)?'done':phase===stage?'current':''}>{phases[stage]}</span>)}</div>
    </div>
  </section>;
}
