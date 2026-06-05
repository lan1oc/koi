import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePipelineStore, type PipelineEntry } from '../stores/pipelineStore'
import {
  Loader2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Square,
  X,
  Flag,
  AlertCircle,
  Timer,
  PlayCircle,
  Minus,
  GitBranch,
} from 'lucide-react'

function formatDuration(ms: number): string {
  if (ms <= 0) return '0s'
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h${m}m${s}s`
  if (m > 0) return `${m}m${s}s`
  return `${s}s`
}

/** Single pipeline card */
function PipelineCard({ entry, onNavigate }: { entry: PipelineEntry; onNavigate: (challengeId: string, sessionId?: string) => void }) {
  const stopPipeline = usePipelineStore((s) => s.stopPipeline)
  const dismiss = usePipelineStore((s) => s.dismiss)
  const getElapsedMs = usePipelineStore((s) => s.getElapsedMs)

  const [expanded, setExpanded] = useState(false)
  const [elapsedMs, setElapsedMs] = useState(0)

  useEffect(() => {
    const tick = () => setElapsedMs(getElapsedMs(entry.pipelineId))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [entry.pipelineId, entry.running, getElapsedMs])

  const { running, current, total, results } = entry
  const solvedCount = results.filter((r) => r.status === 'solved').length
  const failedCount = results.filter((r) => r.status === 'failed').length
  const solvingCount = results.filter((r) => r.status === 'solving').length
  const pct = total > 0 ? (current / total) * 100 : 0

  return (
    <div className="border-b border-surface-border last:border-0">
      {/* Header row */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-surface-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {running ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary-500 flex-shrink-0" />
        ) : (
          <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-gray-800 truncate">
              {entry.label || (running ? '解题中' : '已完成')}
            </span>
            <span className="text-[10px] text-gray-400 flex-shrink-0">{current}/{total}</span>
          </div>
          <div className="w-full h-1 bg-gray-200 rounded-full mt-1 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${running ? 'bg-primary-500' : 'bg-green-500'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0 ml-1">
          <span className="flex items-center gap-0.5 text-[10px] text-gray-400">
            <Timer className="w-2.5 h-2.5" />
            {formatDuration(elapsedMs)}
          </span>
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronUp className="w-3.5 h-3.5 text-gray-400" />}
        </div>
      </div>

      {/* Stats + actions */}
      <div className="flex items-center gap-2 px-3 pb-1.5 text-[10px]">
        {solvedCount > 0 && (
          <span className="flex items-center gap-0.5 text-green-600">
            <Flag className="w-2.5 h-2.5" /> {solvedCount}
          </span>
        )}
        {failedCount > 0 && (
          <span className="flex items-center gap-0.5 text-red-500">
            <AlertCircle className="w-2.5 h-2.5" /> {failedCount}
          </span>
        )}
        {solvingCount > 0 && (
          <span className="flex items-center gap-0.5 text-amber-600">
            <Loader2 className="w-2.5 h-2.5 animate-spin" /> {solvingCount}
          </span>
        )}
        <div className="flex-1" />
        {running && (
          <button
            onClick={(e) => { e.stopPropagation(); stopPipeline(entry.pipelineId) }}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-red-50 text-red-600 hover:bg-red-100 font-medium transition-colors"
          >
            <Square className="w-2.5 h-2.5" />
            停止
          </button>
        )}
        {!running && (
          <button
            onClick={(e) => { e.stopPropagation(); dismiss(entry.pipelineId) }}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title="关闭"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Expanded challenge list */}
      {expanded && (
        <div className="border-t border-surface-border max-h-48 overflow-y-auto bg-surface-50">
          {results.map((r) => (
            <div
              key={r.challenge_id}
              className="flex items-center gap-2 px-3 py-1 text-[10px] border-b border-surface-border last:border-0 hover:bg-white cursor-pointer"
              onClick={() => onNavigate(r.challenge_id, r.session_id)}
            >
              {r.status === 'solving' && <Loader2 className="w-2.5 h-2.5 animate-spin text-amber-500 flex-shrink-0" />}
              {r.status === 'solved' && <Flag className="w-2.5 h-2.5 text-green-600 flex-shrink-0" />}
              {r.status === 'failed' && <AlertCircle className="w-2.5 h-2.5 text-red-500 flex-shrink-0" />}
              {r.status === 'timeout' && <Timer className="w-2.5 h-2.5 text-orange-500 flex-shrink-0" />}
              {r.status === 'skipped' && <PlayCircle className="w-2.5 h-2.5 text-gray-400 flex-shrink-0" />}
              {r.status === 'pending' && <div className="w-2.5 h-2.5 rounded-full border border-gray-300 flex-shrink-0" />}
              <span className={`truncate flex-1 ${
                r.status === 'solved' ? 'text-green-700 font-medium' :
                r.status === 'failed' ? 'text-red-600' :
                r.status === 'solving' ? 'text-amber-700 font-medium' : 'text-gray-500'
              }`}>
                {r.challenge_title}
              </span>
              {r.duration_ms != null && r.duration_ms > 0 && (
                <span className="text-gray-400 flex-shrink-0">{formatDuration(r.duration_ms)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PipelineFloater() {
  const pipelines = usePipelineStore((s) => s.pipelines)
  const minimized = usePipelineStore((s) => s.minimized)
  const setMinimized = usePipelineStore((s) => s.setMinimized)
  const dismissAll = usePipelineStore((s) => s.dismissAll)
  const navigate = useNavigate()

  // Don't render if no pipeline activity
  if (pipelines.length === 0) return null

  const runningCount = pipelines.filter((p) => p.running).length
  const totalSolved = pipelines.reduce((acc, p) => acc + p.results.filter((r) => r.status === 'solved').length, 0)
  const totalChallenges = pipelines.reduce((acc, p) => acc + p.total, 0)

  const handleNavigate = (challengeId: string, sessionId?: string) => {
    const params = sessionId ? `?session=${sessionId}` : ''
    navigate(`/solve/${challengeId}${params}`)
  }

  if (minimized) {
    // Minimized: compact pill
    return (
      <div
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 shadow-xl rounded-full border border-surface-border bg-white [html.theme-dark_&]:bg-[#1a1d27] cursor-pointer hover:bg-surface-50 transition-colors select-none"
        onClick={() => setMinimized(false)}
        title="点击展开流水线"
      >
        {runningCount > 0 ? (
          <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
        ) : (
          <CheckCircle2 className="w-4 h-4 text-green-500" />
        )}
        <GitBranch className="w-3.5 h-3.5 text-gray-500" />
        <span className="text-xs font-medium text-gray-700">
          {pipelines.length} 个流水线
        </span>
        {runningCount > 0 && (
          <span className="text-xs text-primary-600 font-medium">{runningCount} 运行中</span>
        )}
        {totalSolved > 0 && (
          <span className="flex items-center gap-0.5 text-xs text-green-600">
            <Flag className="w-3 h-3" />{totalSolved}/{totalChallenges}
          </span>
        )}
        <ChevronUp className="w-3.5 h-3.5 text-gray-400" />
      </div>
    )
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-72 shadow-2xl rounded-xl border border-surface-border bg-white [html.theme-dark_&]:bg-[#1a1d27] overflow-hidden transition-all duration-200">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-50 border-b border-surface-border select-none">
        <GitBranch className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        <span className="text-xs font-medium text-gray-700 flex-1">
          流水线 ({pipelines.length})
          {runningCount > 0 && <span className="text-primary-600 ml-1">· {runningCount} 运行中</span>}
        </span>
        <button
          onClick={() => setMinimized(true)}
          className="text-gray-400 hover:text-gray-600 transition-colors p-0.5 rounded"
          title="最小化"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        {pipelines.every((p) => !p.running) && (
          <button
            onClick={dismissAll}
            className="text-gray-400 hover:text-gray-600 transition-colors p-0.5 rounded"
            title="全部关闭"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Pipeline list */}
      <div className="max-h-[70vh] overflow-y-auto">
        {pipelines.map((entry) => (
          <PipelineCard key={entry.pipelineId} entry={entry} onNavigate={handleNavigate} />
        ))}
      </div>
    </div>
  )
}
