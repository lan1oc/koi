/**
 * GlobalFlagModal — 全局 flag 人工确认弹窗
 *
 * 监听所有 flag_manual 事件（无论当前在哪个页面），弹出确认框让用户：
 *   1. 复制 flag 到剪贴板
 *   2. 确认"正确"→ 标记题目为已解出
 *   3. 确认"错误"→ 让 Agent 继续解题
 *
 * 支持同时缓存多个待确认 flag（逐个弹出）。
 */
import { useEffect, useState, useCallback } from 'react'
import { Flag, X, Copy, Check, RefreshCw } from 'lucide-react'
import { wsService } from '../services/websocket'
import { challengeApi, agentApi } from '../services/api'
import { useActivityStore } from '../stores/activityStore'
import { useSettingsStore } from '../stores/settingsStore'
import type { WSEvent } from '../types'

interface PendingFlag {
  id: string
  flag: string
  agentId: string
  sessionId: string
  challengeTitle?: string
}

export default function GlobalFlagModal() {
  const [queue, setQueue] = useState<PendingFlag[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [copied, setCopied] = useState(false)
  const [hidden, setHidden] = useState(false)

  // Enqueue incoming flag_manual events
  useEffect(() => {
    const unsub = wsService.onAll((event: WSEvent) => {
      if (event.type !== 'flag_manual') return
      const flag = (event.flag_found || '').trim()
      if (!flag) return

      // Resolve title from activity store agent list
      const agents = useActivityStore.getState().agents
      const agent = agents.find((a) => a.id === event.agent_id)

      setQueue((prev) => {
        // Avoid duplicate entries for same flag+session
        const key = `${event.session_id}-${flag}`
        if (prev.some((p) => `${p.sessionId}-${p.flag}` === key)) return prev
        return [
          ...prev,
          {
            id: `flag-${Date.now()}-${Math.random()}`,
            flag,
            agentId: event.agent_id || '',
            sessionId: event.session_id || '',
            challengeTitle: agent?.challengeTitle || event.challenge_title,
          },
        ]
      })
    })
    return () => unsub()
  }, [])

  const current = queue[0]

  // Remove current item from queue (called after correct/wrong confirmation)
  const dequeue = useCallback(() => {
    setQueue((prev) => prev.slice(1))
    setCopied(false)
    setSubmitting(false)
    setHidden(false)
  }, [])

  // Temporarily hide the modal without sending any signal to the agent.
  // The flag stays in the queue so it will reappear when the user navigates back.
  const handleDefer = useCallback(() => {
    setHidden(true)
    setCopied(false)
  }, [])

  const handleCopy = useCallback(async () => {
    if (!current) return
    try {
      await navigator.clipboard.writeText(current.flag)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }, [current])

  const handleCorrect = useCallback(async () => {
    if (!current) return
    setSubmitting(true)
    try {
      // Signal the agent that the flag is confirmed correct (unblocks the paused agent)
      await agentApi.confirmFlag(current.sessionId, 'correct', current.flag)
      // Also update challenge status via activity store
      const { _agentChallengeMap } = useActivityStore.getState()
      const challengeId = _agentChallengeMap[current.agentId]
      if (challengeId) {
        await challengeApi.updateStatus(challengeId, 'solved', current.flag)
      }
      dequeue()
    } catch (e) {
      // Fallback: if confirmFlag fails (e.g. agent already stopped), still update challenge
      console.error('Failed to confirm flag:', e)
      try {
        const { _agentChallengeMap } = useActivityStore.getState()
        const challengeId = _agentChallengeMap[current.agentId]
        if (challengeId) {
          await challengeApi.updateStatus(challengeId, 'solved', current.flag)
        }
      } catch { /* ignore */ }
      dequeue()
    } finally {
      setSubmitting(false)
    }
  }, [current, dequeue])

  const handleWrongContinue = useCallback(async () => {
    if (!current) return
    setSubmitting(true)
    try {
      // Signal the agent that the flag is wrong (unblocks the paused agent to continue solving)
      await agentApi.confirmFlag(current.sessionId, 'wrong', current.flag)
      dequeue()
    } catch (e) {
      // Fallback: if confirmFlag fails (e.g. agent already stopped), use continue to restart
      console.error('Failed to signal flag wrong:', e)
      try {
        const { selectedModel, utilityModel } = useSettingsStore.getState()
        const msg =
          '用户已手动提交 flag，但平台反馈不正确（或用户判断错误）。请继续解题，寻找真正的 flag，并在找到后再次调用 flag_submit 触发人工确认。'
        await agentApi.continue(current.sessionId, selectedModel, msg, utilityModel)
      } catch { /* ignore */ }
      dequeue()
    } finally {
      setSubmitting(false)
    }
  }, [current, dequeue])

  // Re-show the modal when a new flag arrives (reset hidden state)
  useEffect(() => {
    if (current) setHidden(false)
  }, [current?.id])

  if (!current) return null

  if (hidden) {
    return (
      <button
        onClick={() => setHidden(false)}
        className="fixed bottom-4 right-4 z-[9998] flex items-center gap-2 rounded-full border border-amber-200 bg-white px-4 py-2 text-sm text-amber-700 shadow-lg transition-colors hover:bg-amber-50 [html.theme-dark_&]:border-amber-800 [html.theme-dark_&]:bg-[#1a1d27] [html.theme-dark_&]:text-amber-300"
      >
        <Flag className="w-4 h-4" />
        <span>有待确认 Flag</span>
        {queue.length > 1 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs [html.theme-dark_&]:bg-amber-900/40">
            {queue.length}
          </span>
        )}
      </button>
    )
  }

  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={() => (!submitting ? handleDefer() : undefined)}
    >
      <div
        className="relative bg-white [html.theme-dark_&]:bg-[#1a1d27] rounded-2xl shadow-2xl w-[560px] max-w-[92vw] border border-surface-border flex flex-col"
        onClick={(e) => e.stopPropagation()}
        style={{ animation: 'flagModalIn 0.28s cubic-bezier(0.34,1.56,0.64,1) both' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br from-yellow-300 to-amber-400 shadow-md shadow-yellow-200">
              <Flag className="w-4 h-4 text-white" />
            </div>
            <div>
              <div className="font-bold text-sm text-gray-900 [html.theme-dark_&]:text-gray-100">
                已获取 Flag — 请手动提交并确认
              </div>
              {current.challengeTitle && (
                <div className="text-xs text-gray-400 mt-0.5 truncate max-w-[360px]">
                  {current.challengeTitle}
                </div>
              )}
            </div>
          </div>
          <button
            onClick={handleDefer}
            disabled={submitting}
            className="text-gray-400 hover:text-gray-600 [html.theme-dark_&]:hover:text-gray-200 transition-colors disabled:opacity-40"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-gray-600 [html.theme-dark_&]:text-gray-300">
            复制下面的 flag 到题目平台提交，提交后在此选择结果。
          </p>

          {/* Flag display */}
          <div className="flex items-stretch gap-2">
            <code className="flex-1 text-sm font-mono text-green-700 [html.theme-dark_&]:text-green-400 bg-green-50 [html.theme-dark_&]:bg-green-950/40 border border-green-200 [html.theme-dark_&]:border-green-800 rounded-xl px-3 py-2.5 break-all leading-relaxed">
              {current.flag}
            </code>
            <button
              onClick={handleCopy}
              title="复制 Flag"
              className={`flex-shrink-0 px-3 py-2 rounded-xl border transition-colors flex items-center gap-1.5 text-sm font-medium ${
                copied
                  ? 'bg-green-100 border-green-300 text-green-700'
                  : 'bg-gray-100 hover:bg-gray-200 [html.theme-dark_&]:bg-[#232634] [html.theme-dark_&]:hover:bg-[#2a2f40] border-surface-border text-gray-700 [html.theme-dark_&]:text-gray-200'
              }`}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              {copied ? '已复制' : '复制'}
            </button>
          </div>

          {/* Notice that agent is paused */}
          <div className="text-xs text-blue-600 bg-blue-50 [html.theme-dark_&]:bg-blue-950/30 border border-blue-200 [html.theme-dark_&]:border-blue-800 rounded-lg px-3 py-1.5">
            ⏸️ Agent 已暂停，正在等待你确认 flag 是否正确
          </div>

          {queue.length > 1 && (
            <div className="text-xs text-amber-600 bg-amber-50 [html.theme-dark_&]:bg-amber-950/30 border border-amber-200 [html.theme-dark_&]:border-amber-800 rounded-lg px-3 py-1.5">
              还有 {queue.length - 1} 个待确认的 flag
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-surface-border flex items-center justify-between gap-2">
          <button
            onClick={handleDefer}
            disabled={submitting}
            className="px-3 py-2 rounded-lg text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 [html.theme-dark_&]:hover:bg-[#232634] transition-colors disabled:opacity-40"
          >
            稍后处理
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={handleWrongContinue}
              disabled={submitting}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm bg-gray-100 hover:bg-gray-200 [html.theme-dark_&]:bg-[#232634] [html.theme-dark_&]:hover:bg-[#2a2f40] text-gray-800 [html.theme-dark_&]:text-gray-100 border border-surface-border transition-colors disabled:opacity-40"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              错误，继续解题
            </button>
            <button
              onClick={handleCorrect}
              disabled={submitting}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm bg-amber-500 hover:bg-amber-400 text-white font-medium shadow-sm transition-colors disabled:opacity-40"
            >
              <Check className="w-3.5 h-3.5" />
              {submitting ? '处理中...' : '正确，标记已解出'}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes flagModalIn {
          from { opacity: 0; transform: translateY(-24px) scale(0.94); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  )
}
