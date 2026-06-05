import { useRef, useEffect, useState, useCallback, memo } from 'react'
import { Send, ChevronDown, ChevronRight, Brain, Eye, EyeOff, Flag, AlertTriangle, Lightbulb, Radio, Target, RefreshCw, History, Download, Loader2, Sparkles, ArrowDown } from 'lucide-react'
import type { StreamingMessage } from '../types'
import { useAgentStore } from '../stores/agentStore'
import { useSettingsStore } from '../stores/settingsStore'
import { sessionApi } from '../services/api'
import ToolCallCard from './ToolCallCard'
import MarkdownRenderer from './MarkdownRenderer'

export default function ChatPanel() {
  const { messages, currentMessage, isRunning, isGeneratingWriteup, flagFound, sendInput, session, loadingHistory, isFullHistory, loadHistory, loadFullHistory, pendingQuestion } = useAgentStore()
  const { showThinking, toggleThinking, showSystemInject, toggleSystemInject, autoScroll } = useSettingsStore()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  // Track whether user is near bottom for smart auto-scroll
  const isNearBottomRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)

  const allMessages = currentMessage ? [...messages, currentMessage] : messages

  // Update isNearBottom on scroll events
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const handleScroll = () => {
      const threshold = 150 // pixels from bottom
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
      isNearBottomRef.current = nearBottom
      setShowScrollBtn(!nearBottom)
    }
    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [])

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
      isNearBottomRef.current = true
      setShowScrollBtn(false)
    }
  }, [])

  // Smart auto-scroll: only scroll to bottom if user hasn't scrolled up
  useEffect(() => {
    if (autoScroll && isNearBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [allMessages, autoScroll])

  const handleSend = useCallback(() => {
    if (!input.trim()) return
    sendInput(input.trim())
    setInput('')
  }, [input, sendInput])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="flex flex-col h-full bg-[var(--bg-base)]">
      {/* Header — minimal, Claude Code style */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-panel)] flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-xs font-semibold text-[var(--text-primary)] tracking-tight">Agent</span>
          {(isRunning || isGeneratingWriteup) && (
            <span className="flex items-center gap-1.5 text-[10px] font-medium text-amber-600">
              <span className="cc-status-dot cc-status-dot--active" />
              {isGeneratingWriteup && !isRunning ? 'Writeup 生成中' : '运行中'}
            </span>
          )}
          {!isRunning && !isGeneratingWriteup && flagFound && (
            <span className="flex items-center gap-1.5 text-[10px] font-medium text-emerald-600">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              已解决
            </span>
          )}
          {!isRunning && !isGeneratingWriteup && !flagFound && session && (
            <span className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
              空闲
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <HeaderToggle active={showThinking} onClick={toggleThinking} label="思考" activeColor="purple" />
          <HeaderToggle active={showSystemInject} onClick={toggleSystemInject} label="系统" activeColor="indigo" />
          {session && (
            <button
              onClick={() => isFullHistory ? loadHistory(session.id) : loadFullHistory(session.id)}
              disabled={loadingHistory}
              className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md transition-colors ${
                isFullHistory ? 'text-blue-600 bg-blue-50' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-surface-50'
              }`}
              title={isFullHistory ? '当前显示完整对话，点击切回最新' : '加载完整对话历史（含归档）'}
            >
              {loadingHistory ? <Loader2 className="w-3 h-3 animate-spin" /> : <History className="w-3 h-3" />}
              {isFullHistory ? '完整' : '全部'}
            </button>
          )}
          {session && (
            <a
              href={sessionApi.exportChatUrl(session.id)}
              download
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-surface-50 transition-colors"
              title="导出完整对话记录"
            >
              <Download className="w-3 h-3" />
            </a>
          )}
        </div>
      </div>

      {/* Flag Banner — compact */}
      {flagFound && (
        <div className="mx-3 mt-2 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center gap-2">
          <Flag className="w-3 h-3 text-emerald-600 flex-shrink-0" />
          <code className="text-xs font-semibold font-mono text-emerald-700 truncate">{flagFound}</code>
        </div>
      )}

      {/* Messages — Claude Code style flow */}
      <div className="flex-1 relative overflow-hidden">
      <div ref={scrollRef} className="absolute inset-0 overflow-y-auto px-2 py-3 cc-message-stream">
        {allMessages.length === 0 && loadingHistory && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <span className="cc-status-dot cc-status-dot--active inline-block mb-3" style={{ width: 8, height: 8 }} />
              <p className="text-xs text-[var(--text-muted)]">加载历史记录...</p>
            </div>
          </div>
        )}
        {allMessages.length === 0 && !loadingHistory && !session && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Sparkles className="w-6 h-6 text-gray-300 mx-auto mb-2" />
              <p className="text-xs text-[var(--text-muted)]">开始解题后可查看智能体活动</p>
            </div>
          </div>
        )}
        {allMessages.length === 0 && !loadingHistory && session && isRunning && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <span className="cc-status-dot cc-status-dot--active inline-block mb-3" style={{ width: 8, height: 8 }} />
              <p className="text-xs text-[var(--text-muted)]">智能体运行中，等待响应...</p>
            </div>
          </div>
        )}

        {allMessages.map((msg) => (
          <MessageRow key={msg.id} message={msg} showThinking={showThinking} showSystemInject={showSystemInject} />
        ))}

        {/* Pending question indicator */}
        {pendingQuestion && (
          <div className="cc-msg-row py-2">
            <div className="cc-msg-edge text-amber-500">●</div>
            <div className="cc-msg-body">
              <div className="inline-flex items-center gap-2 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
                <span className="cc-status-dot cc-status-dot--active" />
                AI 正等待你的回答，请在弹窗中选择
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Scroll to bottom button — appears when user scrolls up */}
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-16 right-4 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full
            bg-blue-600 text-white text-[11px] font-medium shadow-lg shadow-blue-500/25
            hover:bg-blue-700 transition-all animate-in fade-in slide-in-from-bottom-2 duration-200"
          title="滚动到最新消息"
        >
          <ArrowDown className="w-3 h-3" />
          最新
        </button>
      )}
      </div>

      {/* Input — clean, minimal */}
      <div className="border-t border-[var(--border-color)] px-3 py-2.5 bg-[var(--bg-panel)]">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="发送消息..."
              className="w-full resize-none min-h-[36px] max-h-[120px] px-3 py-2 text-xs rounded-lg
                bg-[var(--bg-base)] border border-[var(--border-color)]
                focus:border-blue-400 focus:ring-1 focus:ring-blue-400/30
                outline-none transition-all placeholder:text-gray-400 text-[var(--text-primary)]"
              rows={1}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() || !session}
            className="p-2 rounded-lg bg-blue-600 text-white
              hover:bg-blue-700
              disabled:opacity-20 disabled:cursor-not-allowed
              transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}

/** Reusable header toggle button */
function HeaderToggle({ active, onClick, label, activeColor }: {
  active: boolean; onClick: () => void; label: string; activeColor: string
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md transition-colors ${
        active ? `text-${activeColor}-600 bg-${activeColor}-50` : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-surface-50'
      }`}
    >
      {active ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
      {label}
    </button>
  )
}

/** Config for system-inject badge rendering */
const SYSTEM_INJECT_CONFIG: Record<string, { label: string; icon: typeof Brain; color: string; dotColor: string }> = {
  planning:       { label: '规划',   icon: Lightbulb,      color: 'text-blue-600',   dotColor: 'bg-blue-500' },
  reflection:     { label: '反思',   icon: RefreshCw,      color: 'text-amber-600',  dotColor: 'bg-amber-500' },
  checkpoint:     { label: '检查点', icon: Radio,          color: 'text-indigo-600', dotColor: 'bg-indigo-500' },
  repetition:     { label: '重复',   icon: AlertTriangle,  color: 'text-orange-600', dotColor: 'bg-orange-500' },
  flag_candidate: { label: 'Flag',   icon: Target,         color: 'text-green-600',  dotColor: 'bg-green-500' },
  thinking_hint:  { label: '提示',   icon: Brain,          color: 'text-purple-600', dotColor: 'bg-purple-500' },
  system:         { label: '系统',   icon: Radio,          color: 'text-gray-500',   dotColor: 'bg-gray-400' },
}

/** Single message row — Claude Code inspired layout */
const MessageRow = memo(function MessageRow({
  message,
  showThinking,
  showSystemInject,
}: {
  message: StreamingMessage
  showThinking: boolean
  showSystemInject: boolean
}) {
  const isAssistant = message.role === 'assistant'
  const isUser = message.role === 'user'
  const isSystemInject = message.isSystemInject
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const [sysInjectExpanded, setSysInjectExpanded] = useState(false)

  // ── System inject messages ──
  if (isSystemInject && isUser) {
    if (!showSystemInject) return null

    const config = SYSTEM_INJECT_CONFIG[message.systemInjectType || 'system'] || SYSTEM_INJECT_CONFIG.system
    const Icon = config.icon
    const lines = message.content.split('\n')
    const preview = lines[0]
    const hasMore = lines.length > 1

    return (
      <div className="cc-msg-row cc-msg-row--system group">
        <div className={`cc-msg-edge ${config.color}`}>
          <Icon className="w-3 h-3" />
        </div>
        <div
          className="cc-msg-body cursor-pointer select-none"
          onClick={() => hasMore && setSysInjectExpanded(!sysInjectExpanded)}
        >
          <div className={`flex items-center gap-1.5 text-[11px] font-medium ${config.color}`}>
            <span>{config.label}</span>
            {hasMore && (
              <ChevronRight className={`w-3 h-3 opacity-40 transition-transform duration-150 ${sysInjectExpanded ? 'rotate-90' : ''}`} />
            )}
          </div>
          <div className={`text-[11px] ${config.color} opacity-60 whitespace-pre-wrap break-words leading-relaxed mt-0.5`}>
            {sysInjectExpanded ? message.content : preview}
            {!sysInjectExpanded && hasMore && <span className="opacity-30"> …</span>}
          </div>
        </div>
      </div>
    )
  }

  // ── User messages ──
  if (isUser) {
    return (
      <div className="cc-msg-row cc-msg-row--user">
        <div className="cc-msg-edge text-blue-500 font-bold">❯</div>
        <div className="cc-msg-body">
          <div className="text-xs text-[var(--text-primary)] whitespace-pre-wrap break-words leading-relaxed">
            {message.content}
          </div>
        </div>
      </div>
    )
  }

  // ── Assistant messages ──
  return (
    <div className="cc-msg-row cc-msg-row--assistant">
      <div className="cc-msg-edge text-[var(--text-muted)]">⎿</div>
      <div className="cc-msg-body space-y-1.5">
        {/* Thinking — collapsible, Claude Code style */}
        {showThinking && message.thinking && (
          <div
            className="cursor-pointer select-none group/think"
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
          >
            <div className="flex items-center gap-1.5 text-[11px] text-purple-500 italic opacity-70">
              <span>∴ 思考</span>
              {!thinkingExpanded && (
                <span className="text-[10px] opacity-50 group-hover/think:opacity-80 transition-opacity">
                  点击展开
                </span>
              )}
              {thinkingExpanded && (
                <ChevronDown className="w-3 h-3 opacity-50" />
              )}
            </div>
            {thinkingExpanded && (
              <div className="mt-1 pl-3 text-[11px] text-purple-400 whitespace-pre-wrap break-words leading-relaxed opacity-60 border-l border-purple-200">
                {message.thinking}
              </div>
            )}
          </div>
        )}

        {/* Main content */}
        {message.content && (
          <div className="cc-assistant-content text-sm">
            <MarkdownRenderer content={message.content} />
          </div>
        )}

        {/* Tool calls */}
        {message.toolCalls.map((tc) => (
          <ToolCallCard key={tc.id} execution={tc} />
        ))}

        {/* Streaming indicator — pulsing dot */}
        {message.isStreaming && !message.content && message.toolCalls.length === 0 && (
          <div className="flex items-center gap-2 text-[var(--text-muted)] text-xs py-1">
            <span className="cc-status-dot cc-status-dot--active" />
            <span className="opacity-60">思考中…</span>
          </div>
        )}
      </div>
    </div>
  )
})
