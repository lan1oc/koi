import { useEffect, useRef, useState, useMemo, memo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  Brain,
  Clock,
  Cpu,
  Zap,
  Square,
  Trash2,
  ChevronDown,
  ChevronRight,
  Flag,
  AlertCircle,
  Terminal,
  Globe,
  FileText,
  Search,
  Bug,
  Lock,
  Eye,
  Wrench,
  Bot,
  MessageSquare,
  Timer,
  TrendingUp,
  Lightbulb,
  Copy,
  RefreshCw,
  Radio,
  Target,
} from 'lucide-react'
import { useActivityStore, type ActivityEntry, type ActiveAgent } from '../stores/activityStore'
import { challengeApi } from '../services/api'
import { renderArguments } from '../components/ToolCallCard'

// ─── Tool category config ──────────────────────────────────────────────────
const toolConfig: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string; label: string }> = {
  exec:             { icon: Terminal, color: 'text-gray-600',   label: '执行命令' },
  read_file:        { icon: FileText, color: 'text-blue-500',   label: '读取文件' },
  write_file:       { icon: FileText, color: 'text-indigo-500', label: '写入文件' },
  grep:             { icon: Search,   color: 'text-cyan-500',   label: '文本搜索' },
  find:             { icon: Search,   color: 'text-cyan-500',   label: '查找文件' },
  web_fetch:        { icon: Globe,    color: 'text-blue-500',   label: 'HTTP 请求' },
  python_exec:      { icon: Terminal, color: 'text-yellow-600', label: 'Python 执行' },
  nmap_scan:        { icon: Eye,      color: 'text-teal-500',   label: 'Nmap 扫描' },
  sqlmap:           { icon: Bug,      color: 'text-red-500',    label: 'SQL 注入' },
  burp_request:     { icon: Globe,    color: 'text-orange-500', label: 'Burp 请求' },
  gdb_debug:        { icon: Bug,      color: 'text-red-500',    label: 'GDB 调试' },
  pwntools_script:  { icon: Zap,      color: 'text-amber-500',  label: 'Pwntools' },
  checksec:         { icon: Lock,     color: 'text-green-500',  label: 'Checksec' },
  ghidra_decompile: { icon: Eye,      color: 'text-purple-500', label: 'Ghidra 反编译' },
  radare2:          { icon: Eye,      color: 'text-purple-500', label: 'Radare2' },
  strings_analyze:  { icon: Search,   color: 'text-teal-500',   label: '字符串分析' },
  crypto_toolkit:   { icon: Lock,     color: 'text-yellow-500', label: '密码工具' },
  sage_math:        { icon: TrendingUp, color: 'text-green-600', label: 'SageMath' },
  steg_detect:      { icon: Eye,      color: 'text-pink-500',   label: '隐写检测' },
  forensics:        { icon: Search,   color: 'text-teal-500',   label: '取证分析' },
  flag_submit:      { icon: Flag,     color: 'text-green-600',  label: '提交 flag' },
  spawn_agent:      { icon: Bot,      color: 'text-violet-500', label: '生成子 Agent' },
  send_to_agent:    { icon: MessageSquare, color: 'text-violet-500', label: '发送到 Agent' },
  get_agent_history:{ icon: Clock,    color: 'text-gray-500',   label: '获取历史' },
  ask_user:         { icon: MessageSquare, color: 'text-amber-500', label: '询问用户' },
}

function getToolConfig(name: string) {
  return toolConfig[name] || { icon: Wrench, color: 'text-gray-500', label: name }
}

// ─── Duration formatter ────────────────────────────────────────────────────
function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTokens(n: number): string {
  if (n >= 100_000_000) return `${(n / 100_000_000).toFixed(1)}亿`
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`
  return String(n)
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ─── Single tool call row ──────────────────────────────────────────────────
const ToolCallRow = memo(function ToolCallRow({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = useState(false)
  const cfg = getToolConfig(entry.toolName || '')
  const Icon = cfg.icon
  const isRunning = entry.toolStatus === 'running'
  const isFailed = entry.toolStatus === 'failed'

  const hasDetail = entry.toolArgs || entry.toolOutput

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch (err) {
      console.error('copy failed', err)
    }
  }

  return (
    <div className={`group relative pl-4 ${hasDetail ? 'cursor-pointer' : ''}`} onClick={() => hasDetail && setOpen(!open)}>
      {/* Left accent bar */}
      <div className={`absolute left-0 top-1 bottom-1 w-0.5 rounded-full transition-colors ${
        isRunning ? 'bg-amber-400' : isFailed ? 'bg-red-400' : 'bg-gray-200 group-hover:bg-primary-300'
      }`} />

      <div className="flex items-center gap-2 py-1.5 pr-2 rounded-lg transition-colors hover:bg-surface-50">
        {/* Status dot */}
        <span className={`flex-shrink-0 ${
          isRunning ? 'cc-status-dot cc-status-dot--active' : isFailed ? 'cc-status-dot cc-status-dot--error' : 'cc-status-dot cc-status-dot--success opacity-40 group-hover:opacity-100'
        }`} style={{ transition: 'opacity 0.15s' }} />

        {/* Tool icon + name */}
        <Icon className={`w-3 h-3 flex-shrink-0 ${cfg.color}`} />
        <span className={`text-xs font-mono font-medium ${isRunning ? 'text-amber-600' : isFailed ? 'text-red-500' : 'text-[var(--text-primary)]'}`}>
          {entry.toolName}
        </span>

        {/* Args preview */}
        {entry.toolArgs && !open && (
          <span className="text-[11px] text-[var(--text-muted)] truncate max-w-[280px]">
            {getArgsPreview(entry.toolArgs)}
          </span>
        )}

        <div className="flex-1" />

        {entry.duration != null && (
          <span className="cc-tool-duration flex-shrink-0">
            <Timer className="w-2.5 h-2.5" />
            {fmtDuration(entry.duration)}
          </span>
        )}

        {hasDetail && (
          <span className="text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="ml-5 mb-1 space-y-1.5 animate-fade-in">
          {entry.toolArgs && (
            <div className="rounded-lg overflow-hidden border border-[var(--border-color)]">
              <div className="flex items-center justify-between gap-2 cc-tool-section-label bg-[var(--bg-base)] px-2 py-1 border-b border-[var(--border-color)]">
                <span>参数</span>
                <button
                  className="p-1 rounded hover:bg-surface-100 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                  title="复制输入"
                  onClick={(e) => {
                    e.stopPropagation()
                    copyText(formatArgs(entry.toolArgs!))
                  }}
                >
                  <Copy className="w-3 h-3" />
                </button>
              </div>
              <div className="p-2.5 bg-[var(--bg-panel)]">
                {(() => {
                  const parsed = parseToolArgs(entry.toolArgs)
                  const rendered = (Object.keys(parsed).length > 0)
                    ? renderArguments(entry.toolName || '', parsed)
                    : null
                  if (rendered) return rendered
                  const raw = formatArgs(entry.toolArgs!)
                  return raw && raw !== '{}' ? (
                    <pre className="text-xs text-[var(--text-muted)] bg-[var(--bg-base)] rounded-md px-2.5 py-2 whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto font-mono leading-relaxed border border-[var(--border-color)]">
                      {raw}
                    </pre>
                  ) : (
                    <span className="text-xs text-[var(--text-muted)] italic">无参数</span>
                  )
                })()}
              </div>
            </div>
          )}
          {entry.toolOutput && (
            <div className="rounded-lg overflow-hidden border border-[var(--border-color)]">
              <div className={`flex items-center justify-between gap-2 cc-tool-section-label px-2 py-1 border-b border-[var(--border-color)] ${
                isFailed ? 'text-red-400 bg-red-50' : 'bg-[var(--bg-base)]'
              }`}>
                <span>输出</span>
                <button
                  className={`p-1 rounded transition-colors ${
                    isFailed
                      ? 'hover:bg-red-100 text-red-400 hover:text-red-600'
                      : 'hover:bg-surface-100 text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                  }`}
                  title="复制输出"
                  onClick={(e) => {
                    e.stopPropagation()
                    copyText(entry.toolOutput || '')
                  }}
                >
                  <Copy className="w-3 h-3" />
                </button>
              </div>
              <pre className={`text-xs p-2.5 max-h-40 overflow-auto whitespace-pre-wrap font-mono leading-relaxed ${
                isFailed ? 'text-red-600 bg-red-50/30' : 'text-[var(--text-muted)] bg-[var(--bg-panel)]'
              }`}>
                {formatStructuredText(entry.toolOutput, 3000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
})

// ─── Content / thinking / status rows ─────────────────────────────────────
const ContentRow = memo(function ContentRow({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = useState(false)
  const text = normalizeActivityText(entry.content || '')
  const isLong = text.length > 200
  const preview = isLong ? text.slice(0, 200) + '…' : text

  if (entry.type === 'thinking') {
    return (
      <div className="pl-4 border-l-2 border-purple-200 py-1.5 group">
        <div
          className={`flex items-start gap-1.5 cursor-pointer ${isLong ? 'cursor-pointer' : ''}`}
          onClick={() => isLong && setOpen(!open)}
        >
          <div className="flex-shrink-0 w-4 flex justify-center mt-0.5">
            <Brain className="w-3 h-3 text-purple-400" />
          </div>
          <p className="text-xs text-purple-500 italic leading-relaxed min-w-0 whitespace-pre-wrap break-words">
            {isLong && !open ? preview : text}
          </p>
          {isLong && (
            <span className="text-purple-300 flex-shrink-0 mt-0.5">
              {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </span>
          )}
        </div>
      </div>
    )
  }

  if (entry.type === 'content') {
    return (
      <div className="pl-4 border-l-2 border-blue-100 py-1.5">
        <div
          className={`flex items-start gap-1.5 ${isLong ? 'cursor-pointer' : ''}`}
          onClick={() => isLong && setOpen(!open)}
        >
          <div className="flex-shrink-0 w-4 flex justify-center mt-0.5">
            <MessageSquare className="w-3 h-3 text-blue-400" />
          </div>
          <p className="text-xs text-gray-600 leading-relaxed min-w-0 whitespace-pre-wrap break-words">
            {isLong && !open ? preview : text}
          </p>
          {isLong && (
            <span className="text-gray-300 flex-shrink-0 mt-0.5">
              {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </span>
          )}
        </div>
      </div>
    )
  }

  // status
  const normalizedText = normalizeActivityText(text)
  const isFlag = normalizedText.includes('Flag') || normalizedText.includes('flag')
  const isError = normalizedText.startsWith('Error') || normalizedText.startsWith('error')
  return (
    <div className={`pl-4 py-1.5 border-l-2 ${isFlag ? 'border-green-400' : isError ? 'border-red-300' : 'border-gray-200'}`}>
      <div className="flex items-center gap-1.5">
        <div className="flex-shrink-0 w-4 flex justify-center">
          {isFlag ? <Flag className="w-3 h-3 text-green-500" /> :
           isError ? <AlertCircle className="w-3 h-3 text-red-400" /> :
           <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />}
        </div>
        <span className={`text-xs min-w-0 whitespace-pre-wrap break-words ${isFlag ? 'text-green-600 font-medium' : isError ? 'text-red-500' : 'text-gray-500'}`}>
          {normalizedText}
        </span>
      </div>
    </div>
  )
})

// ─── System-inject row ─────────────────────────────────────────────────────
const systemInjectConfig: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string; bg: string; border: string; label: string }> = {
  planning:       { icon: Lightbulb,    color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200',   label: '规划阶段' },
  reflection:     { icon: RefreshCw,    color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200',  label: '策略反思' },
  checkpoint:     { icon: Radio,        color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200', label: '进度检查' },
  repetition:     { icon: AlertCircle,  color: 'text-orange-600',  bg: 'bg-orange-50',  border: 'border-orange-200', label: '重复警告' },
  flag_candidate: { icon: Target,       color: 'text-green-600',   bg: 'bg-green-50',   border: 'border-green-200',  label: 'Flag 检测' },
  thinking_hint:  { icon: Brain,        color: 'text-purple-600',  bg: 'bg-purple-50',  border: 'border-purple-200', label: '系统提示' },
  system:         { icon: Radio,        color: 'text-gray-600',    bg: 'bg-gray-50',    border: 'border-gray-200',   label: '系统注入' },
}

const SystemInjectRow = memo(function SystemInjectRow({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = useState(false)
  const text = normalizeActivityText(entry.content || '')
  const cfg = systemInjectConfig[entry.systemInjectType || 'system'] || systemInjectConfig.system
  const Icon = cfg.icon
  const lines = text.split('\n')
  const preview = lines[0]
  const hasMore = lines.length > 1 || text.length > 200

  return (
    <div
      className={`pl-3 py-1.5 border-l-2 ${cfg.border} rounded-r ${cfg.bg} ${hasMore ? 'cursor-pointer' : ''}`}
      onClick={() => hasMore && setOpen(!open)}
    >
      <div className={`flex items-center gap-1.5 ${cfg.color}`}>
        <Icon className="w-3 h-3 flex-shrink-0" />
        <span className="text-[10px] font-semibold uppercase tracking-wide">{cfg.label}</span>
        {hasMore && (
          <span className="ml-auto flex-shrink-0">
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>
      <p className={`text-xs ${cfg.color} opacity-80 mt-0.5 whitespace-pre-wrap break-words leading-relaxed`}>
        {open ? text : (preview.length > 200 ? preview.slice(0, 200) + '…' : preview)}
        {!open && hasMore && <span className="opacity-50"> ...</span>}
      </p>
    </div>
  )
})

// ─── Ask User interactive row ──────────────────────────────────────────────
const AskUserRow = memo(function AskUserRow({ entry, agentId }: { entry: ActivityEntry; agentId: string }) {
  const pendingQuestion = useActivityStore((s) => s.pendingQuestions[agentId])
  const respondToAgentQuestion = useActivityStore((s) => s.respondToAgentQuestion)
  const agent = useActivityStore((s) => s.agents.find((a) => a.id === agentId))

  // If there's a pending question for this agent, show a waiting indicator
  // (the actual interactive modal is handled by GlobalAskUserModal at the app level)
  if (pendingQuestion && agent) {
    return (
      <div className="py-1.5">
        <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2.5 text-xs">
          <span className="flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          <span className="text-amber-300 font-medium">等待回答中...</span>
          <span className="text-zinc-500 truncate flex-1">{pendingQuestion.question}</span>
        </div>
      </div>
    )
  }

  // Otherwise show a static summary of the answered question
  return (
    <div className="flex items-start gap-2 rounded-lg bg-amber-500/5 border border-amber-500/10 px-3 py-2 text-xs">
      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
      <div className="min-w-0 flex-1">
        <span className="text-amber-400 font-medium">已回答: </span>
        <span className="text-zinc-400">{entry.content}</span>
      </div>
      <span className="shrink-0 text-[10px] text-zinc-600">{fmtTime(entry.timestamp)}</span>
    </div>
  )
})

// ─── Agent column (one per concurrent agent, independently scrollable) ─────
const AgentColumn = memo(function AgentColumn({
  agentId,
  agent,
  entries,
  autoScroll,
  onStop,
  onNavigate,
}: {
  agentId: string
  agent: ActiveAgent | null
  entries: ActivityEntry[]
  autoScroll: boolean
  onStop: (id: string) => void
  onNavigate: (challengeId: string) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  const toolCalls = entries.filter((e) => e.type === 'tool_call')
  const solvedEntry = entries.find((e) => e.type === 'status' && (e.content?.includes('Flag') || e.content?.includes('flag')))
  const failedEntry = entries.find((e) => e.type === 'status' && e.content?.startsWith('Error'))

  const isRunning = agent?.running ?? false
  const isGeneratingWriteup = (agent?.generatingWriteup ?? false) && !isRunning
  const challengeTitle = agent?.challengeTitle || entries[0]?.challengeTitle || 'Unknown'
  const challengeId = agent?.challengeId || entries[0]?.challengeId

  const displayEntries = useMemo(() => {
    return buildDisplayEntries(entries)
  }, [entries])

  const completedTools = toolCalls.filter((e) => e.toolStatus === 'completed').length
  const startTime = entries[0]?.timestamp
  const lastTime = entries[entries.length - 1]?.timestamp
  const elapsed = startTime && lastTime ? lastTime - startTime : 0

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [displayEntries, autoScroll])

  const borderCls = isRunning
    ? 'border-amber-200 shadow-amber-50'
    : isGeneratingWriteup
    ? 'border-blue-200 shadow-blue-50'
    : solvedEntry
    ? 'border-green-200 shadow-green-50'
    : 'border-surface-border'

  return (
    <div className={`flex flex-col rounded-xl border shadow-sm ${borderCls} bg-white overflow-hidden h-full`}>
      {/* Sticky column header */}
      <div className={`flex-shrink-0 px-3 py-2.5 border-b border-surface-border/60 ${
        isRunning ? 'bg-amber-50/60' : isGeneratingWriteup ? 'bg-blue-50/60' : solvedEntry ? 'bg-green-50/60' : 'bg-surface-50/80'
      }`}>
        {/* Title row */}
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
            isRunning ? 'bg-amber-400 animate-pulse' : isGeneratingWriteup ? 'bg-blue-400 animate-pulse' : solvedEntry ? 'bg-green-400' : failedEntry ? 'bg-red-400' : 'bg-gray-300'
          }`} />
          <button
            className="flex-1 min-w-0 text-left text-sm font-semibold text-gray-800 hover:text-primary-600 transition-colors truncate"
            onClick={() => challengeId && onNavigate(challengeId)}
            title={challengeTitle}
          >
            {challengeTitle}
          </button>
          {solvedEntry && (
            <span className="flex-shrink-0 flex items-center gap-0.5 text-[10px] text-green-600 bg-green-100 px-1.5 py-0.5 rounded-full font-medium">
              <Flag className="w-2.5 h-2.5" /> 已解决
            </span>
          )}
          {isRunning && agent?.currentTool && (
            <span className="flex-shrink-0 flex items-center gap-1 text-[10px] text-amber-600 bg-amber-100 px-1.5 py-0.5 rounded-full">
              <span className="cc-status-dot cc-status-dot--active" />
              {agent.currentTool}
            </span>
          )}
          {isGeneratingWriteup && (
            <span className="flex-shrink-0 flex items-center gap-1 text-[10px] text-blue-600 bg-blue-100 px-1.5 py-0.5 rounded-full">
              <span className="cc-status-dot cc-status-dot--active" />
              Writeup
            </span>
          )}
          {isRunning && (
            <button
              onClick={() => onStop(agentId)}
              className="flex-shrink-0 p-1 rounded-md bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600 transition-colors"
              title="停止"
            >
              <Square className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-2.5 mt-1 text-[10px] text-gray-400 flex-wrap">
          {agent?.model && <span className="flex items-center gap-0.5"><Cpu className="w-2.5 h-2.5" />{agent.model}</span>}
          {(agent?.rounds ?? 0) > 0 && <span className="flex items-center gap-0.5"><Zap className="w-2.5 h-2.5" />{agent!.rounds} 轮</span>}
          {completedTools > 0 && <span className="flex items-center gap-0.5"><Wrench className="w-2.5 h-2.5" />{completedTools} 工具</span>}
          {(() => { const n = entries.filter((e) => e.type === 'thinking').length; return n > 0 ? <span className="flex items-center gap-0.5"><Lightbulb className="w-2.5 h-2.5" />{n} 想法</span> : null })()}
          {elapsed > 0 && <span className="flex items-center gap-0.5"><Clock className="w-2.5 h-2.5" />{fmtDuration(elapsed)}</span>}
          {agent && agent.totalTokens > 0 && (
            <span className="flex items-center gap-0.5 text-blue-400"
              title={`Prompt: ${agent.promptTokens.toLocaleString()} | Completion: ${agent.completionTokens.toLocaleString()}`}>
              <Brain className="w-2.5 h-2.5" />{fmtTokens(agent.totalTokens)} tokens
            </span>
          )}
        </div>
      </div>

      {/* Scrollable entry list — limit to last 200 visible entries for performance */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
        {displayEntries.slice(-200).map((e) => {
          const key = e.toolCallId || e.id
          if (e.type === 'tool_call') return <ToolCallRow key={key} entry={e} />
          if (e.type === 'system_inject') return <SystemInjectRow key={key} entry={e} />
          if (e.type === 'ask_user') return <AskUserRow key={key} entry={e} agentId={agentId} />
          return <ContentRow key={key} entry={e} />
        })}
        {displayEntries.length === 0 && (
          <p className="text-xs text-gray-400 py-4 text-center">等待 Agent 输出…</p>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
})

// ─── Agent task card ───────────────────────────────────────────────────────
const AgentTaskCard = memo(function AgentTaskCard({
  agentId,
  agent,
  entries,
  onStop,
  onNavigate,
}: {
  agentId: string
  agent: ActiveAgent | null
  entries: ActivityEntry[]
  onStop: (id: string) => void
  onNavigate: (challengeId: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)

  const toolCalls = entries.filter((e) => e.type === 'tool_call')
  const solvedEntry = entries.find((e) => e.type === 'status' && (e.content?.includes('Flag') || e.content?.includes('flag')))
  const failedEntry = entries.find((e) => e.type === 'status' && e.content?.startsWith('Error'))

  const isRunning = agent?.running ?? false
  const challengeTitle = agent?.challengeTitle || entries[0]?.challengeTitle || 'Unknown'
  const challengeId = agent?.challengeId || entries[0]?.challengeId

  // Group entries chronologically, de-duplicate tool_call pairs (keep last update per callId)
  const displayEntries = useMemo(() => {
    return buildDisplayEntries(entries)
  }, [entries])

  const completedTools = toolCalls.filter((e) => e.toolStatus === 'completed').length
  const startTime = entries[0]?.timestamp
  const lastTime = entries[entries.length - 1]?.timestamp
  const elapsed = startTime && lastTime ? lastTime - startTime : 0

  return (
    <div className={`rounded-xl border transition-all ${
      isRunning ? 'border-amber-200 shadow-md shadow-amber-50' :
      solvedEntry ? 'border-green-200 shadow-sm shadow-green-50' :
      'border-surface-border shadow-sm'
    } bg-white overflow-hidden`}>
      {/* Card header */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:bg-surface-50 transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        {/* Status dot */}
        <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
          isRunning ? 'bg-amber-400 animate-pulse' :
          solvedEntry ? 'bg-green-400' :
          failedEntry ? 'bg-red-400' : 'bg-gray-300'
        }`} />

        {/* Title */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              className="text-sm font-semibold text-gray-800 hover:text-primary-600 transition-colors truncate max-w-[300px]"
              onClick={(e) => { e.stopPropagation(); if (challengeId) onNavigate(challengeId) }}
            >
              {challengeTitle}
            </button>
            {solvedEntry && (
              <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full font-medium flex-shrink-0">
                <Flag className="w-3 h-3" /> 已解决
              </span>
            )}
            {isRunning && agent?.currentTool && (
              <span className="flex items-center gap-1 text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full flex-shrink-0">
                <span className="cc-status-dot cc-status-dot--active" />
                {agent.currentTool}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-[10px] text-gray-400 flex-wrap">
            {agent?.model && (
              <span className="flex items-center gap-0.5">
                <Cpu className="w-2.5 h-2.5" /> {agent.model}
              </span>
            )}
            {agent?.rounds != null && agent.rounds > 0 && (
              <span className="flex items-center gap-0.5">
                <Zap className="w-2.5 h-2.5" /> {agent.rounds} 轮
              </span>
            )}
            {completedTools > 0 && (
              <span className="flex items-center gap-0.5">
                <Wrench className="w-2.5 h-2.5" /> {completedTools} 工具
              </span>
            )}
            {elapsed > 0 && (
              <span className="flex items-center gap-0.5">
                <Clock className="w-2.5 h-2.5" /> {fmtDuration(elapsed)}
              </span>
            )}
            {agent && agent.totalTokens > 0 && (
              <span
                className="flex items-center gap-0.5 text-blue-400"
                title={`Prompt: ${agent.promptTokens.toLocaleString()} | Completion: ${agent.completionTokens.toLocaleString()}`}
              >
                <Brain className="w-2.5 h-2.5" /> {fmtTokens(agent.totalTokens)} tokens
              </span>
            )}
            {startTime && (
              <span className="flex items-center gap-0.5">
                <Timer className="w-2.5 h-2.5" /> {fmtTime(startTime)}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          {isRunning && (
            <button
              onClick={() => onStop(agentId)}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-red-50 text-red-500 hover:bg-red-100 transition-colors font-medium"
            >
              <Square className="w-3 h-3" />
              停止
            </button>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded text-gray-400 hover:text-gray-600 transition-colors"
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Entry list */}
      {!collapsed && (
        <div className="px-4 pb-3 space-y-0.5 border-t border-surface-border/50 pt-2">
          {displayEntries.map((e) => {
            const key = e.toolCallId || e.id
            if (e.type === 'tool_call') return <ToolCallRow key={key} entry={e} />
            if (e.type === 'ask_user') return <AskUserRow key={key} entry={e} agentId={agentId} />
            return <ContentRow key={key} entry={e} />
          })}
          {entries.length === 0 && (
            <p className="text-xs text-gray-400 py-2 text-center">暂无记录</p>
          )}
        </div>
      )}
    </div>
  )
})

// ─── Main page ─────────────────────────────────────────────────────────────
export default function ActivityPage() {
  const [autoScroll, setAutoScroll] = useState(true)
  const [columns, setColumns] = useState<1 | 2 | 3 | 'auto'>('auto')
  const navigate = useNavigate()
  const handleNavigate = useCallback((cid: string) => {
    const agentList = useActivityStore.getState().agents
    const agent = agentList.find((a) => a.challengeId === cid)
    const mode = agent?.mode
    if (mode === 'pentest') {
      navigate(`/pentest/task/${cid}`)
    } else if (mode === 'audit') {
      navigate(`/audit/task/${cid}`)
    } else if (mode === 'inspection') {
      navigate(`/inspection/results/${cid}`)
    } else {
      navigate(`/solve/${cid}`)
    }
  }, [navigate])

  // Stable insertion-order tracking — prevents columns reordering on every update
  const agentOrderRef = useRef<string[]>([])

  const entries = useActivityStore((s) => s.entries)
  const agents = useActivityStore((s) => s.agents)
  const challengeMap = useActivityStore((s) => s._challengeMap)
  const connect = useActivityStore((s) => s.connect)
  const disconnect = useActivityStore((s) => s.disconnect)
  const clearEntries = useActivityStore((s) => s.clearEntries)
  const stopAgent = useActivityStore((s) => s.stopAgent)
  const setChallenges = useActivityStore((s) => s.setChallenges)
  const historyPromptTokens = useActivityStore((s) => s.historyPromptTokens)
  const historyCompletionTokens = useActivityStore((s) => s.historyCompletionTokens)
  const historyTotalTokens = useActivityStore((s) => s.historyTotalTokens)

  useEffect(() => {
    challengeApi.list().then((cs) => setChallenges(cs, '')).catch(console.error)
  }, [setChallenges])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  // Group entries by agentId
  const groupedByAgent = useMemo(() => {
    const map = new Map<string, ActivityEntry[]>()
    for (const e of entries) {
      if (!map.has(e.agentId)) map.set(e.agentId, [])
      map.get(e.agentId)!.push(e)
    }
    return map
  }, [entries])

  // Challenge titles for filter
  const challengeTitles = useMemo(() => {
    const titles = new Map<string, string>()
    for (const e of entries) {
      if (e.challengeId && e.challengeTitle) titles.set(e.challengeId, e.challengeTitle)
    }
    for (const [id, title] of Object.entries(challengeMap)) {
      if (!titles.has(id)) titles.set(id, title)
    }
    return Array.from(titles.entries())
  }, [entries, challengeMap])

  const activeCount = agents.filter((a) => a.running || a.generatingWriteup).length
  const totalRounds = agents.reduce((sum, a) => sum + (a.rounds ?? 0), 0)
  const agentMap = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents])

  // Maintain stable insertion order — includes running agents AND those generating writeups
  const filteredAgentIds = useMemo(() => {
    const activeIds = new Set(agents.filter((a) => a.running || a.generatingWriteup).map((a) => a.id))
    // Remove agents that are no longer active
    agentOrderRef.current = agentOrderRef.current.filter((id) => activeIds.has(id))
    // Append newly seen active agents preserving first-seen order
    for (const id of activeIds) {
      if (!agentOrderRef.current.includes(id)) {
        agentOrderRef.current.push(id)
      }
    }
    return [...agentOrderRef.current]
  }, [agents])

  return (
    <div className="relative flex flex-col h-full bg-surface-50 overflow-hidden">

      {/* ── Floating top bar ────────────────────────────────────────── */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
        <div className="flex items-center justify-between px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-gray-800">
              <Activity className="w-4 h-4 text-primary-500" />
              <h1 className="text-sm font-bold">AI 动态</h1>
            </div>
            {activeCount > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full font-medium">
                <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
                {activeCount} 个运行中
              </span>
            )}
            {historyTotalTokens > 0 && (
              <span
                className="flex items-center gap-1 text-xs text-blue-600 bg-blue-50 border border-blue-100 px-2 py-1 rounded-full"
                title={`Prompt: ${historyPromptTokens.toLocaleString()} | Completion: ${historyCompletionTokens.toLocaleString()}`}
              >
                <Brain className="w-3 h-3" />
                {fmtTokens(historyTotalTokens)}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {/* Rounds counter */}
            {totalRounds > 0 && (
              <span className="flex items-center gap-1 text-xs text-violet-600 bg-violet-50 border border-violet-100 px-2.5 py-1 rounded-full" title="所有 Agent 累计轮次">
                <Zap className="w-3 h-3" />
                {totalRounds} rounds
              </span>
            )}

            {/* Column layout picker */}
            <div className="flex items-center gap-0.5 bg-white/60 border border-white/60 rounded-xl p-0.5">
              {([1, 2, 3, 'auto'] as const).map((c) => (
                <button
                  key={c}
                  onClick={() => setColumns(c)}
                  title={c === 'auto' ? '自动列数' : `${c} 列`}
                  className={`text-xs px-2 py-1 rounded-lg transition-all ${
                    columns === c
                      ? 'bg-white shadow-sm text-gray-800 font-medium'
                      : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {c === 1 ? (
                    <span className="flex gap-0.5"><span className="w-1.5 h-3 bg-current rounded-[2px]" /></span>
                  ) : c === 2 ? (
                    <span className="flex gap-0.5"><span className="w-1.5 h-3 bg-current rounded-[2px]" /><span className="w-1.5 h-3 bg-current rounded-[2px]" /></span>
                  ) : c === 3 ? (
                    <span className="flex gap-0.5"><span className="w-1.5 h-3 bg-current rounded-[2px]" /><span className="w-1.5 h-3 bg-current rounded-[2px]" /><span className="w-1.5 h-3 bg-current rounded-[2px]" /></span>
                  ) : (
                    <span className="text-[10px] font-bold leading-none">A</span>
                  )}
                </button>
              ))}
            </div>

            {/* Auto scroll */}
            <button
              onClick={() => setAutoScroll(!autoScroll)}
              className={`text-xs px-2.5 py-1.5 rounded-xl border transition-all ${
                autoScroll
                  ? 'bg-primary-50 border-primary-200 text-primary-600 font-medium'
                  : 'bg-white/60 border-white/60 text-gray-400 hover:text-gray-600'
              }`}
              title={autoScroll ? '关闭自动滚动' : '开启自动滚动'}
            >
              ↓ 自动
            </button>

            {entries.length > 0 && (
              <button
                onClick={clearEntries}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors px-2.5 py-1.5 rounded-xl border border-white/60 hover:border-red-200 hover:bg-red-50/80"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Floating stats bar ──────────────────────────────────────── */}
      {agents.length > 0 && (
        <div className="absolute top-[4.5rem] left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
          <div className="flex items-center gap-2 px-3 py-2 rounded-2xl bg-white/70 backdrop-blur-xl border border-white/60 shadow-[0_4px_20px_rgba(0,0,0,0.06)] overflow-x-auto">
            {agents.filter(a => a.running || a.generatingWriteup).map((a) => (
              <div
                key={a.id}
                className={`flex items-center gap-2 text-xs rounded-xl px-3 py-1.5 border flex-shrink-0 ${
                  a.generatingWriteup && !a.running
                    ? 'bg-blue-50/80 border-blue-200/80 text-blue-700'
                    : 'bg-amber-50/80 border-amber-200/80 text-amber-700'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse ${
                  a.generatingWriteup && !a.running ? 'bg-blue-500' : 'bg-amber-500'
                }`} />
                <span className="font-medium truncate max-w-[140px]">{a.challengeTitle || 'Unknown'}</span>
                <span className="text-gray-400 flex items-center gap-0.5 flex-shrink-0">
                  <Cpu className="w-3 h-3" />{a.model}
                </span>
                {a.generatingWriteup && !a.running ? (
                  <span className="flex items-center gap-1 font-medium flex-shrink-0">
                    <span className="cc-status-dot cc-status-dot--active" />Writeup
                  </span>
                ) : a.currentTool ? (
                  <span className="flex items-center gap-1 font-medium flex-shrink-0">
                    <span className="cc-status-dot cc-status-dot--active" />{a.currentTool}
                  </span>
                ) : null}
                {a.rounds > 0 && <span className="flex items-center gap-0.5 flex-shrink-0"><Zap className="w-2.5 h-2.5" />{a.rounds}</span>}
                {a.totalTokens > 0 && (
                  <span className="text-blue-500 flex-shrink-0" title={`Prompt: ${a.promptTokens.toLocaleString()} | Completion: ${a.completionTokens.toLocaleString()}`}>
                    {fmtTokens(a.totalTokens)}tok
                  </span>
                )}
                <button
                  onClick={() => stopAgent(a.id)}
                  className="ml-0.5 p-0.5 rounded-lg hover:bg-red-100 text-current hover:text-red-500 transition-colors"
                  title="停止"
                >
                  <Square className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Content area ────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden" style={{ paddingTop: agents.length > 0 ? '8.5rem' : '5rem' }}>
        {filteredAgentIds.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-3 select-none">
            <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
              <Activity className="w-8 h-8 text-gray-300" />
            </div>
            <p className="text-sm font-medium">暂无 AI 活动记录</p>
            <p className="text-xs text-gray-300">开始解题或解析题目，这里将实时显示 AI 的思考过程</p>
          </div>
        ) : (
          /* Multi-column: each agent gets its own scrollable column */
          <div
            className="h-full grid gap-3 p-4"
            style={{ gridTemplateColumns: `repeat(${columns === 'auto' ? Math.min(filteredAgentIds.length, 3) : columns}, minmax(0, 1fr))` }}
          >
            {filteredAgentIds.map((agentId) => {
              const agentEntries = groupedByAgent.get(agentId) || []
              const agent = agentMap.get(agentId) ?? null
              return (
                <AgentColumn
                  key={agentId}
                  agentId={agentId}
                  agent={agent}
                  entries={agentEntries}
                  autoScroll={autoScroll}
                  onStop={stopAgent}
                  onNavigate={handleNavigate}
                />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function parseToolArgs(args: string | object | undefined): Record<string, unknown> {
  if (!args) return {}
  if (typeof args === 'object') return args as Record<string, unknown>
  try { return JSON.parse(args) as Record<string, unknown> } catch { return {} }
}

function buildDisplayEntries(entries: ActivityEntry[]): ActivityEntry[] {
  const merged: ActivityEntry[] = []
  const toolEntryIndex = new Map<string, number>()

  for (const entry of entries) {
    if (entry.type === 'tool_call') {
      const key = entry.toolCallId || entry.id
      const existingIndex = toolEntryIndex.get(key)
      if (existingIndex != null) {
        merged[existingIndex] = entry
      } else {
        toolEntryIndex.set(key, merged.length)
        merged.push(entry)
      }
      continue
    }

    const previous = merged[merged.length - 1]
    if (canMergeTextEntry(previous, entry)) {
      merged[merged.length - 1] = {
        ...previous,
        id: entry.id,
        timestamp: entry.timestamp,
        content: normalizeActivityText((previous.content || '') + (entry.content || '')),
      }
      continue
    }

    merged.push({
      ...entry,
      content: entry.content ? normalizeActivityText(entry.content) : entry.content,
    })
  }

  return merged
}

function canMergeTextEntry(previous: ActivityEntry | undefined, current: ActivityEntry): boolean {
  if (!previous) return false
  if (previous.agentId !== current.agentId || previous.challengeId !== current.challengeId) return false
  if (previous.type !== current.type) return false
  if (current.type !== 'content' && current.type !== 'thinking') return false
  if (!previous.content || !current.content) return false
  return current.timestamp - previous.timestamp <= 2500
}

function normalizeActivityText(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/\u0000/g, '')
    .replace(/\n{3,}/g, '\n\n')
}

function formatStructuredText(text: string, maxLength: number): string {
  const normalized = normalizeActivityText(text)
  const trimmed = normalized.trim()

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed)
      const pretty = JSON.stringify(parsed, null, 2)
      if (pretty.length > maxLength) return pretty.slice(0, maxLength) + '\n... (已截断)'
      return pretty
    } catch {
      // keep raw text when output is not valid JSON
    }
  }

  if (normalized.length > maxLength) return normalized.slice(0, maxLength) + '\n... (已截断)'
  return normalized
}

function formatArgs(args: string | object): string {
  if (typeof args === 'object') {
    try { return JSON.stringify(args, null, 2) } catch { return String(args) }
  }
  try { return JSON.stringify(JSON.parse(args), null, 2) } catch { return args as string }
}

function getArgsPreview(args: string | object): string {
  let s: string
  if (typeof args === 'object') {
    try { s = JSON.stringify(args) } catch { return '' }
  } else {
    s = args
  }
  // Try to extract first meaningful value
  try {
    const obj = JSON.parse(s)
    const vals = Object.values(obj)
    const first = vals.find((v) => typeof v === 'string' && v.length > 0)
    if (typeof first === 'string') return first.length > 80 ? first.slice(0, 80) + '…' : first
  } catch {}
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}
