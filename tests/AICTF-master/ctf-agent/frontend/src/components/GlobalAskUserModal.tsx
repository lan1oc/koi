/**
 * GlobalAskUserModal — 全局 ask_user 选择题弹窗
 *
 * 监听所有 ask_user 事件（无论当前在哪个页面），以全屏遮罩弹窗形式弹出，
 * 让用户以"选择题"方式回答 AI 提出的问题。
 *
 * 类似考试选择题 UI：
 *   A. 选项1
 *   B. 选项2
 *   C. 选项3
 *   ✏️ 自定义回答
 *
 * 支持队列：多个 ask_user 事件会排队逐个弹出。
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { MessageCircleQuestion, Send, CheckCircle, Clock, Sparkles, X } from 'lucide-react'
import { wsService } from '../services/websocket'
import { agentApi } from '../services/api'
import { useActivityStore } from '../stores/activityStore'
import { useAgentStore } from '../stores/agentStore'
import type { WSEvent, AskUserQuestion } from '../types'

interface PendingAskUser {
  question: AskUserQuestion
  agentId: string
  sessionId: string
  challengeTitle?: string
  arrivedAt: number
}

export default function GlobalAskUserModal() {
  const [queue, setQueue] = useState<PendingAskUser[]>([])
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [customInput, setCustomInput] = useState('')
  const [isCustomMode, setIsCustomMode] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submittedAnswer, setSubmittedAnswer] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // Listen for ask_user events globally
  useEffect(() => {
    const unsub = wsService.onAll((event: WSEvent) => {
      if (event.type !== 'ask_user') return

      try {
        const questionData: AskUserQuestion = typeof event.data === 'string'
          ? JSON.parse(event.data)
          : (event.data as unknown as AskUserQuestion)

        if (!questionData || !questionData.question) return

        // Resolve agent info
        const agents = useActivityStore.getState().agents
        const agent = agents.find((a) => a.id === event.agent_id)

        const pending: PendingAskUser = {
          question: questionData,
          agentId: event.agent_id || '',
          sessionId: event.session_id || '',
          challengeTitle: agent?.challengeTitle || event.challenge_title,
          arrivedAt: Date.now(),
        }

        setQueue((prev) => {
          // Deduplicate by question ID
          if (prev.some((p) => p.question.id === questionData.id)) return prev
          return [...prev, pending]
        })

        // Play notification sound
        playNotificationSound()
      } catch {
        // ignore parse errors
      }
    })
    return () => unsub()
  }, [])

  // Also listen for ask_user_responded to clear from queue
  useEffect(() => {
    const unsub = wsService.onAll((event: WSEvent) => {
      if (event.type !== 'ask_user_responded') return
      // Remove any matching item from queue
      setQueue((prev) => prev.filter((p) => p.agentId !== event.agent_id))
      setSubmitted(false)
      setSubmittedAnswer('')
    })
    return () => unsub()
  }, [])

  // Play a subtle notification sound
  const playNotificationSound = useCallback(() => {
    try {
      if (!audioRef.current) {
        // Create a simple beep using Web Audio API
        const audioCtx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)()
        const oscillator = audioCtx.createOscillator()
        const gainNode = audioCtx.createGain()
        oscillator.connect(gainNode)
        gainNode.connect(audioCtx.destination)
        oscillator.frequency.value = 800
        oscillator.type = 'sine'
        gainNode.gain.value = 0.15
        gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.3)
        oscillator.start(audioCtx.currentTime)
        oscillator.stop(audioCtx.currentTime + 0.3)
      }
    } catch {
      // Audio not available, ignore
    }
  }, [])

  const current = queue[0]

  // Reset state when current changes
  useEffect(() => {
    if (current) {
      setSelectedOption(null)
      setCustomInput('')
      setIsCustomMode(false)
      setSubmitting(false)
      setSubmitted(false)
      setSubmittedAnswer('')
      setSubmitError('')
    }
  }, [current?.question.id])

  // Auto-focus custom input
  useEffect(() => {
    if (isCustomMode && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isCustomMode])

  // Resolve sessionId from agentStore if not available
  const getSessionId = useCallback((pending: PendingAskUser) => {
    if (pending.sessionId) return pending.sessionId
    // Try to get from agentStore
    const agentSession = useAgentStore.getState().session
    return agentSession?.id || ''
  }, [])

  const [submitError, setSubmitError] = useState('')

  const handleSubmit = useCallback(async (answer: string) => {
    if (!answer.trim() || !current || submitting) return

    setSubmitting(true)
    setSubmittedAnswer(answer)
    setSubmitError('')

    try {
      const sessionId = getSessionId(current)
      if (!sessionId) {
        // Try harder: look for any active agent session
        const allAgents = useActivityStore.getState().agents
        const activeAgent = allAgents.find((a) => a.id === current.agentId || a.running)
        const fallbackSessionId = activeAgent?.sessionId || ''
        if (!fallbackSessionId) {
          setSubmitError('未找到会话 ID，请稍后重试')
          setSubmitting(false)
          setSelectedOption(null)
          return
        }
        await agentApi.respondToQuestion(fallbackSessionId, answer)
      } else {
        await agentApi.respondToQuestion(sessionId, answer)
      }

      // Also clear from agentStore
      useAgentStore.setState({ pendingQuestion: null })

      setSubmitted(true)

      // Auto-dequeue after brief animation
      setTimeout(() => {
        setQueue((prev) => prev.slice(1))
        setSubmitted(false)
        setSubmittedAnswer('')
        setSelectedOption(null)
        setCustomInput('')
        setIsCustomMode(false)
        setSubmitError('')
      }, 800)
    } catch (err) {
      console.error('Failed to respond to ask_user:', err)
      setSubmitError('提交失败，请重试')
      setSubmitting(false)
      setSelectedOption(null) // Allow re-selection
    }
  }, [current, submitting, getSessionId])

  const handleOptionClick = useCallback((idx: number, option: string) => {
    if (submitting) return // Prevent double-click
    setSelectedOption(idx)
    setIsCustomMode(false)
    setSubmitError('')
    handleSubmit(option)
  }, [handleSubmit, submitting])

  const handleCustomSubmit = useCallback(() => {
    if (customInput.trim()) {
      handleSubmit(customInput.trim())
    }
  }, [customInput, handleSubmit])

  const handleDismiss = useCallback(() => {
    // Dismiss current (send empty response so agent doesn't hang)
    if (current) {
      const sessionId = getSessionId(current)
      if (sessionId) {
        agentApi.respondToQuestion(sessionId, '(用户跳过了此问题)').catch(() => {})
      }
      useAgentStore.setState({ pendingQuestion: null })
    }
    setQueue((prev) => prev.slice(1))
  }, [current, getSessionId])

  // Keyboard shortcut: number keys for options
  useEffect(() => {
    if (!current || submitted || isCustomMode) return

    const handleKey = (e: KeyboardEvent) => {
      const num = parseInt(e.key)
      if (num >= 1 && num <= current.question.options.length) {
        e.preventDefault()
        handleOptionClick(num - 1, current.question.options[num - 1])
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [current, submitted, isCustomMode, handleOptionClick])

  if (!current) return null

  const elapsed = Math.floor((Date.now() - current.arrivedAt) / 1000)
  const optionLabels = 'ABCDEF'

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={(e) => e.stopPropagation()}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg mx-4 animate-in zoom-in-95 fade-in slide-in-from-bottom-4 duration-300">
        {submitted ? (
          /* ─── Success state ─── */
          <div className="rounded-2xl border border-green-500/30 bg-gradient-to-b from-gray-900 to-gray-950 p-6 shadow-2xl shadow-green-500/10">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-500/20 ring-2 ring-green-500/30">
                <CheckCircle className="h-6 w-6 text-green-400" />
              </div>
              <p className="text-sm font-medium text-green-300">已回答</p>
              <p className="text-xs text-zinc-400 max-w-xs truncate">{submittedAnswer}</p>
            </div>
          </div>
        ) : (
          /* ─── Question card ─── */
          <div className="rounded-2xl border border-amber-500/30 bg-gradient-to-b from-gray-900 via-gray-900 to-gray-950 shadow-2xl shadow-amber-500/10 overflow-hidden">

            {/* Header bar */}
            <div className="flex items-center justify-between px-5 py-3 bg-gradient-to-r from-amber-500/10 to-orange-500/10 border-b border-amber-500/20">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/20 ring-1 ring-amber-500/30">
                    <MessageCircleQuestion className="h-5 w-5 text-amber-400" />
                  </div>
                  {/* Pulse indicator */}
                  <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                    <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500" />
                  </span>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-amber-200 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5" />
                    AI 需要你的决策
                  </h3>
                  {current.challengeTitle && (
                    <p className="text-[11px] text-zinc-500 mt-0.5">{current.challengeTitle}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {queue.length > 1 && (
                  <span className="text-[10px] text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded-full">
                    +{queue.length - 1} 待回答
                  </span>
                )}
                <button
                  onClick={handleDismiss}
                  className="p-1 rounded-lg text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
                  title="跳过此问题"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Context (if provided) */}
            {current.question.context && (
              <div className="mx-5 mt-3 p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/50">
                <p className="text-[11px] text-zinc-400 leading-relaxed">{current.question.context}</p>
              </div>
            )}

            {/* Question */}
            <div className="px-5 py-4">
              <p className="text-[15px] leading-relaxed text-zinc-100 font-medium">{current.question.question}</p>
            </div>

            {/* Options — quiz style */}
            {current.question.options.length > 0 && (
              <div className="px-5 pb-3 space-y-2">
                {current.question.options.map((option, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleOptionClick(idx, option)}
                    disabled={submitting}
                    className={`group relative flex w-full items-center gap-3.5 rounded-xl border px-4 py-3 text-left text-sm transition-all duration-150
                      ${selectedOption === idx
                        ? 'border-amber-500 bg-amber-500/15 text-amber-100 shadow-md shadow-amber-500/10'
                        : 'border-zinc-700/80 bg-zinc-800/40 text-zinc-300 hover:border-amber-500/50 hover:bg-amber-500/5 hover:text-amber-200 hover:shadow-sm hover:shadow-amber-500/5'
                      }
                      disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    {/* Letter badge */}
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold transition-all
                      ${selectedOption === idx
                        ? 'bg-amber-500 text-gray-900 shadow-md shadow-amber-500/30'
                        : 'bg-zinc-700 text-zinc-400 group-hover:bg-amber-500/30 group-hover:text-amber-300'
                      }`}>
                      {optionLabels[idx]}
                    </span>
                    {/* Option text */}
                    <span className="flex-1 leading-snug">{option}</span>
                    {/* Keyboard hint */}
                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded transition-all
                      ${selectedOption === idx
                        ? 'bg-amber-500/20 text-amber-300'
                        : 'bg-zinc-700/50 text-zinc-600 group-hover:text-zinc-400'
                      }`}>
                      {idx + 1}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Custom input */}
            <div className="px-5 pb-4 pt-1">
              {!isCustomMode ? (
                <button
                  onClick={() => setIsCustomMode(true)}
                  disabled={submitting}
                  className="w-full rounded-xl border-2 border-dashed border-zinc-700 px-4 py-2.5 text-center text-xs text-zinc-500 transition-all hover:border-amber-500/50 hover:text-amber-400 hover:bg-amber-500/5 disabled:opacity-50"
                >
                  ✏️ 自定义回答...
                </button>
              ) : (
                <div className="flex gap-2 animate-in fade-in slide-in-from-bottom-2 duration-200">
                  <input
                    ref={inputRef}
                    type="text"
                    value={customInput}
                    onChange={(e) => setCustomInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleCustomSubmit()
                      if (e.key === 'Escape') {
                        setIsCustomMode(false)
                        setCustomInput('')
                      }
                    }}
                    placeholder="输入你的回答..."
                    disabled={submitting}
                    className="flex-1 rounded-xl border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-200 placeholder:text-zinc-500 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/20 disabled:opacity-50 transition-all"
                  />
                  <button
                    onClick={handleCustomSubmit}
                    disabled={!customInput.trim() || submitting}
                    className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:from-amber-500 hover:to-orange-500 disabled:cursor-not-allowed disabled:opacity-50 shadow-md shadow-amber-500/20"
                  >
                    <Send className="h-3.5 w-3.5" />
                    发送
                  </button>
                </div>
              )}
            </div>

            {/* Error display */}
            {submitError && (
              <div className="mx-5 mb-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30">
                <span className="text-xs text-red-400">{submitError}</span>
                <button
                  onClick={() => { setSubmitError(''); setSubmitting(false); setSelectedOption(null) }}
                  className="text-[10px] text-red-300 underline hover:text-red-200 ml-auto"
                >
                  重试
                </button>
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-2.5 border-t border-zinc-800 bg-zinc-900/50">
              <div className="flex items-center gap-1.5 text-[10px] text-zinc-600">
                <Clock className="w-3 h-3" />
                <TimerDisplay startTime={current.arrivedAt} />
              </div>
              <p className="text-[10px] text-zinc-600">
                按数字键 <span className="font-mono bg-zinc-800 px-1 rounded">1</span>-<span className="font-mono bg-zinc-800 px-1 rounded">{current.question.options.length}</span> 快速选择
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/** Live timer showing elapsed seconds */
function TimerDisplay({ startTime }: { startTime: number }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [startTime])

  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60

  return (
    <span>
      等待中 {mins > 0 ? `${mins}m ` : ''}{secs}s
    </span>
  )
}
