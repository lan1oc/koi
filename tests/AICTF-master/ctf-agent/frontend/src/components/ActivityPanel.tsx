import { memo, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ChevronDown,
  ChevronUp,
  Brain,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Cpu,
  Zap,
  Square,
  Flag,
  AlertCircle,
  MessageSquare,
} from 'lucide-react'
import type { Challenge } from '../types'
import { useActivityStore, type ActivityEntry } from '../stores/activityStore'
import { getToolIcon } from './ToolCallCard'

interface ActivityPanelProps {
  challengeIds: string[]
  challenges: Challenge[]
  competitionId?: string
  parseAgentId?: string | null
}

export default function ActivityPanel({ challengeIds, challenges, competitionId, parseAgentId }: ActivityPanelProps) {
  const [expanded, setExpanded] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const entries = useActivityStore((s) => s.entries)
  const displayEntries = useMemo(() => buildDisplayEntries(entries), [entries])
  const agents = useActivityStore((s) => s.agents)
  const setChallenges = useActivityStore((s) => s.setChallenges)
  const setParseAgentId = useActivityStore((s) => s.setParseAgentId)
  const connect = useActivityStore((s) => s.connect)
  const disconnect = useActivityStore((s) => s.disconnect)
  const stopAgent = useActivityStore((s) => s.stopAgent)
  const historyPromptTokens = useActivityStore((s) => s.historyPromptTokens)
  const historyCompletionTokens = useActivityStore((s) => s.historyCompletionTokens)
  const historyTotalTokens = useActivityStore((s) => s.historyTotalTokens)

  // Sync challenge data into the store
  useEffect(() => {
    setChallenges(challenges, competitionId || '')
  }, [challengeIds, challenges, competitionId, setChallenges])

  // Sync parseAgentId into the store
  useEffect(() => {
    setParseAgentId(parseAgentId || null)
  }, [parseAgentId, setParseAgentId])

  // Connect/disconnect WS via the store
  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  // Auto-scroll (debounced to avoid thrashing during rapid updates)
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => {
    if (scrollRef.current && expanded) {
      clearTimeout(scrollTimerRef.current)
      scrollTimerRef.current = setTimeout(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      }, 200)
    }
  }, [displayEntries, expanded])

  const activeCount = agents.filter((a) => a.running).length

  if (agents.length === 0 && entries.length === 0) {
    return null
  }

  return (
    <div className="panel border-primary-200 h-full flex flex-col">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="panel-header justify-between w-full cursor-pointer hover:bg-surface-hover transition-colors flex-shrink-0"
      >
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-primary-500" />
          <span>AI 实时动态</span>
          {activeCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-amber-600">
              <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
              {activeCount} 个 Agent 运行中
            </span>
          )}
          {historyTotalTokens > 0 && (
            <span className="flex items-center gap-1 text-xs text-blue-500" title={`Prompt: ${historyPromptTokens.toLocaleString()} | Completion: ${historyCompletionTokens.toLocaleString()}`}>
              <Zap className="w-3 h-3" />
              {historyTotalTokens >= 100000000
                ? `${(historyTotalTokens / 100000000).toFixed(1)} 亿`
                : historyTotalTokens >= 10000
                  ? `${(historyTotalTokens / 10000).toFixed(1)} 万`
                  : historyTotalTokens} tokens
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="flex flex-col flex-1 min-h-0">
          {/* Active Agents Bar */}
          {agents.length > 0 && (
            <div className="px-3 py-2 border-b border-surface-border bg-surface-50 flex flex-wrap gap-2 flex-shrink-0">
              {agents.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center gap-1.5 text-xs"
                >
                  <div
                    className={`w-2 h-2 rounded-full ${
                      a.running ? 'bg-amber-500 animate-pulse' : 'bg-gray-300'
                    }`}
                  />
                  <span className="font-medium text-gray-700 max-w-[100px] truncate">
                    {a.challengeTitle || 'Unknown'}
                  </span>
                  <span className="text-gray-400 flex items-center gap-0.5">
                    <Cpu className="w-3 h-3" />
                    {a.model}
                  </span>
                  {a.currentTool && (
                    <span className="text-amber-600 flex items-center gap-0.5">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      {a.currentTool}
                    </span>
                  )}
                  {a.rounds > 0 && (
                    <span className="text-gray-400 flex items-center gap-0.5">
                      <Zap className="w-3 h-3" />
                      {a.rounds}
                    </span>
                  )}
                  {a.totalTokens > 0 && (
                    <span className="text-blue-500" title={`Prompt: ${a.promptTokens.toLocaleString()} | Completion: ${a.completionTokens.toLocaleString()}`}>
                      {a.totalTokens >= 10000 ? `${(a.totalTokens / 10000).toFixed(1)}万` : a.totalTokens} tokens
                    </span>
                  )}
                  {a.running && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        stopAgent(a.id)
                      }}
                      className="ml-0.5 p-0.5 rounded hover:bg-red-100 text-gray-400 hover:text-red-500 transition-colors"
                      title="停止 Agent"
                    >
                      <Square className="w-3 h-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Activity Feed - fills remaining height */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto divide-y divide-surface-border/50"
          >
            {displayEntries.length === 0 ? (
              <div className="px-4 py-6 text-center text-gray-400 text-sm">
                暂无 AI 活动记录
              </div>
            ) : (
              displayEntries.map((entry) => (
                <ActivityEntryRow key={entry.id} entry={entry} />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const ActivityEntryRow = memo(function ActivityEntryRow({ entry }: { entry: ActivityEntry }) {
  const [showDetail, setShowDetail] = useState(true)
  const timeStr = new Date(entry.timestamp).toLocaleTimeString()

  if (entry.type === 'tool_call') {
    const icon = getToolIcon(entry.toolName || '')
    const statusIcon =
      entry.toolStatus === 'running' ? (
        <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
      ) : entry.toolStatus === 'completed' ? (
        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
      ) : entry.toolStatus === 'failed' ? (
        <XCircle className="w-3.5 h-3.5 text-red-400" />
      ) : null

    return (
      <div className="px-4 py-2">
        <button
          onClick={() => setShowDetail(!showDetail)}
          className="flex items-center gap-2 w-full text-left hover:bg-surface-hover rounded px-1 -mx-1 transition-colors"
        >
          <span className="text-xs text-gray-400 w-16 flex-shrink-0">{timeStr}</span>
          <span className="text-xs text-primary-500 max-w-[80px] truncate flex-shrink-0">
            {entry.challengeTitle}
          </span>
          <span className="text-primary-500 flex-shrink-0">{icon}</span>
          <span className="font-mono text-sm text-primary-600">{entry.toolName}</span>
          {entry.duration != null && (
            <span className="flex items-center gap-0.5 text-xs text-gray-400">
              <Clock className="w-3 h-3" />
              {(entry.duration / 1000).toFixed(1)}s
            </span>
          )}
          <span className="flex-1" />
          {statusIcon}
        </button>
        {showDetail && (
          <div className="mt-1 ml-[4.5rem] space-y-1">
            {entry.toolArgs && (
              <pre className="text-xs text-gray-500 bg-surface-50 rounded p-2 max-h-24 overflow-auto whitespace-pre-wrap">
                {formatArgs(entry.toolArgs)}
              </pre>
            )}
            {entry.toolOutput && (
              <pre className="text-xs text-gray-400 bg-surface-50 rounded p-2 max-h-32 overflow-auto whitespace-pre-wrap font-mono">
                {formatStructuredText(entry.toolOutput, 2000)}
              </pre>
            )}
          </div>
        )}
      </div>
    )
  }

  if (entry.type === 'content') {
    const text = normalizeActivityText(entry.content || '')
    const preview = text.length > 120 ? text.slice(0, 120) + '...' : text
    return (
      <div className="px-4 py-2 flex items-start gap-2">
        <span className="text-xs text-gray-400 w-16 flex-shrink-0 pt-0.5">{timeStr}</span>
        <span className="text-xs text-primary-500 max-w-[80px] truncate flex-shrink-0 pt-0.5">
          {entry.challengeTitle}
        </span>
        <div className="text-sm text-gray-600 min-w-0 flex-1 flex items-start gap-1">
          <MessageSquare className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-0.5" />
          <span>{preview}</span>
        </div>
      </div>
    )
  }

  if (entry.type === 'thinking') {
    const text = entry.content || ''
    const isTruncated = text.length > 200
    const preview = isTruncated ? text.slice(0, 200) + '...' : text
    return (
      <div className="px-4 py-2">
        <div className="flex items-start gap-2">
          <span className="text-xs text-gray-400 w-16 flex-shrink-0 pt-0.5">{timeStr}</span>
          <span className="text-xs text-primary-500 max-w-[80px] truncate flex-shrink-0 pt-0.5">
            {entry.challengeTitle}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs text-purple-500 italic flex items-start gap-1">
              <Brain className="w-3 h-3 flex-shrink-0 mt-0.5" />
              <span className="flex-1">{showDetail ? text : preview}</span>
            </div>
            {isTruncated && (
              <button
                onClick={() => setShowDetail(!showDetail)}
                className="mt-1 text-xs text-gray-400 hover:text-gray-600"
              >
                {showDetail ? '收起' : '展开完整思考过程'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // status
  const isError = entry.content?.startsWith('Error')
  const isFlag = entry.content?.includes('Flag')
  return (
    <div className="px-4 py-2 flex items-center gap-2">
      <span className="text-xs text-gray-400 w-16 flex-shrink-0">{timeStr}</span>
      <span className="text-xs text-primary-500 max-w-[80px] truncate flex-shrink-0">
        {entry.challengeTitle}
      </span>
      <span
        className={`text-xs flex items-center gap-1 ${
          isError ? 'text-red-500' : isFlag ? 'text-green-600 font-medium' : 'text-gray-500'
        }`}
      >
        {isFlag ? <Flag className="w-3 h-3" /> : isError ? <AlertCircle className="w-3 h-3" /> : <Zap className="w-3 h-3" />}
        {entry.content}
      </span>
    </div>
  )
})

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
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    return args
  }
}

