import { useEffect, useState } from 'react';
import type { RetestFollowUp } from './retestSessionStore';

export function AgentFollowUpCard({ question, disabled, canEnd, onAnswer, onEnd }: { question: RetestFollowUp; disabled: boolean; canEnd: boolean; onAnswer: (message: string) => Promise<void>; onEnd: () => Promise<void> }) {
  const [selected, setSelected] = useState(question.options[0]?.id || 'custom');
  const [custom, setCustom] = useState('');
  useEffect(() => { setSelected(question.options[0]?.id || 'custom'); setCustom(''); }, [question.id]);
  const value = selected === 'custom' ? custom.trim() : question.options.find(option => option.id === selected)?.value || '';
  return <form className="retest-follow-up" onSubmit={event => { event.preventDefault(); if (value && !disabled) void onAnswer(value); }}>
    <fieldset disabled={disabled}>
      <legend>{question.question}</legend>
      {question.options.map(option => <label key={option.id} className="retest-follow-up-option"><input type="radio" name={`answer-${question.id}`} value={option.id} checked={selected === option.id} onChange={() => setSelected(option.id)} /><span>{option.label}</span></label>)}
      <label className="retest-follow-up-option"><input type="radio" name={`answer-${question.id}`} value="custom" checked={selected === 'custom'} onChange={() => setSelected('custom')} /><span>自定义</span></label>
      {selected === 'custom' ? <textarea className="koi-input" aria-label="自定义选择" placeholder="输入你的要求" value={custom} onChange={event => setCustom(event.target.value)} /> : null}
      <div className="retest-follow-up-actions"><button type="submit" className="koi-button primary" disabled={!value}>发送选择</button>{canEnd ? <button type="button" className="koi-button" onClick={() => { void onEnd(); }}>结束</button> : null}</div>
    </fieldset>
  </form>;
}
