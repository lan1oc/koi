import { useState } from 'react';
import { callBackend } from '../../lib/backend';
import { repairRetestText, type RetestSessionEvent } from './retestSessionStore';

export function displayArtifactPath(value: string) {
  return repairRetestText(value).replace(/^\\\\\?\\UNC\\/i,'\\\\').replace(/^\\\\\?\\/,'');
}

export function artifactFiles(event: RetestSessionEvent): string[] {
  const paths=Array.isArray(event.metadata?.reports)?event.metadata.reports.filter((item):item is string=>typeof item==='string'):[];
  if(paths.length)return [...new Set(paths)];
  return (event.content || '').split(/\r?\n/).map(line=>line.trim()).filter(line=>/^(?:\\\\\?\\|[A-Za-z]:[\\/]|\\\\)/.test(line)&&/\.(?:docx?|pdf|xlsx?|csv|png|txt)$/i.test(line));
}

export function RetestArtifactCard({event}: {event: RetestSessionEvent}) {
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const files=artifactFiles(event);
  const title=repairRetestText(event.title);
  const source=displayArtifactPath(event.sourceFile || '').split(/[\\/]/).pop();
  const open=async(path: string,exact: boolean)=>{
    setBusy(path+(exact?'-file':'-folder'));setError('');
    try {
      const result=await callBackend<{success:boolean;message:string}>('fs.open_path',{path:displayArtifactPath(path),open_file:exact});
      if(!result.success)throw new Error(result.message);
    }catch(error){setError(error instanceof Error?error.message:String(error));}
    finally{setBusy('');}
  };
  return <details className="retest-report-artifact" open>
    <summary><span className="retest-report-mark">文档</span><strong>{title}</strong><time>{event.timestamp}</time></summary>
    {source?<div className="retest-report-source" title={displayArtifactPath(event.sourceFile || '')}>对应通报：{source}</div>:null}
    <div className="retest-report-files">{files.length?files.map(path=>{
      const display=displayArtifactPath(path);const name=display.split(/[\\/]/).pop() || display;
      return <div className="retest-report-file" key={path}>
        <div className="retest-report-file-info"><b title={display}>{name}</b><details className="retest-report-path"><summary>查看保存位置</summary><p>{display}</p></details></div>
        <div className="retest-report-actions"><button type="button" disabled={Boolean(busy)} onClick={()=>void open(path,true)}>打开报告</button><button type="button" disabled={Boolean(busy)} onClick={()=>void open(path,false)}>打开文件夹</button></div>
      </div>;
    }):<p>{repairRetestText(event.content || '暂无文件路径。')}</p>}</div>
    {error?<div role="alert" className="retest-report-error">{error}</div>:null}
  </details>;
}
