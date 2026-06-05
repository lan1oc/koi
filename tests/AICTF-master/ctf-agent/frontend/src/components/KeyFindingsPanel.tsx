/**
 * KeyFindingsPanel — real-time key findings display
 *
 * Shows key discoveries, flag candidates, and important milestones
 * found during the agent's solving process.
 */
import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, Key, Flag, Zap, AlertTriangle, CheckCircle, Search, Sparkles } from 'lucide-react'
import { challengeApi } from '../services/api'
import { wsService } from '../services/websocket'
import { useAgentStore } from '../stores/agentStore'

interface KeyFindingsData {
  key_findings: string[]
  flag_candidates: string[]
  milestones: Array<{
    round: number
    type: string
    action: string
    tool_name: string
    result: string
    time: string
  }>
}

const milestoneIcon: Record<string, typeof Zap> = {
  flag_candidate: Flag,
  discovery: Search,
  tool_success: CheckCircle,
  strategy_change: Sparkles,
  error_recovery: AlertTriangle,
}

export default function KeyFindingsPanel({ challengeId }: { challengeId: string }) {
  const isRunning = useAgentStore((s) => s.isRunning)
  const [data, setData] = useState<KeyFindingsData | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    if (!challengeId) return
    setLoading(true)
    try {
      const resp = await challengeApi.getKeyFindings(challengeId)
      setData(resp)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [challengeId])

  // Initial fetch
  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Listen for progress updates
  useEffect(() => {
    const unsub = wsService.on('progress_report_updated', () => {
      fetchData()
    })
    return () => unsub()
  }, [fetchData])

  // Auto-refresh while running
  useEffect(() => {
    if (!isRunning) return
    const timer = setInterval(fetchData, 10000)
    return () => clearInterval(timer)
  }, [isRunning, fetchData])

  const hasContent = data && (
    data.key_findings.length > 0 ||
    data.flag_candidates.length > 0 ||
    (data.milestones && data.milestones.filter((m) =>
      ['flag_candidate', 'discovery', 'strategy_change'].includes(m.type)
    ).length > 0)
  )

  return (
    <div className="h-full flex flex-col bg-[var(--bg-base)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border-color)] bg-[var(--bg-panel)] flex-shrink-0">
        <div className="flex items-center gap-2">
          <Key className="w-3.5 h-3.5 text-amber-500" />
          <span className="text-xs font-semibold text-[var(--text-primary)]">关键发现</span>
          {data && data.key_findings.length > 0 && (
            <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded-full font-medium">
              {data.key_findings.length}
            </span>
          )}
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-surface-50 transition-colors"
          title="刷新"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {!hasContent && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Search className="w-6 h-6 text-gray-300 mb-2" />
            <p className="text-xs text-[var(--text-muted)]">
              {isRunning ? 'Agent 运行中，关键发现将实时显示...' : '暂无关键发现'}
            </p>
          </div>
        )}

        {/* Flag Candidates */}
        {data && data.flag_candidates.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Flag className="w-3 h-3 text-emerald-500" />
              <span className="text-[11px] font-semibold text-emerald-600">Flag 候选</span>
            </div>
            <div className="space-y-1.5">
              {data.flag_candidates.map((flag, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200"
                >
                  <code className="text-xs font-mono text-emerald-700 break-all">{flag}</code>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Key Findings */}
        {data && data.key_findings.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Zap className="w-3 h-3 text-amber-500" />
              <span className="text-[11px] font-semibold text-amber-600">关键信息</span>
            </div>
            <div className="space-y-1.5">
              {data.key_findings.map((finding, i) => {
                // Parse "R5: finding text" format
                const match = finding.match(/^R(\d+):\s*(.+)$/)
                const round = match ? match[1] : null
                const text = match ? match[2] : finding
                return (
                  <div
                    key={i}
                    className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50/50 border border-amber-200/50"
                  >
                    {round && (
                      <span className="flex-shrink-0 text-[10px] font-mono text-amber-500 bg-amber-100 px-1.5 py-0.5 rounded mt-0.5">
                        R{round}
                      </span>
                    )}
                    <span className="text-xs text-[var(--text-primary)] leading-relaxed break-words">{text}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Key Milestones */}
        {data && data.milestones && (() => {
          const keyMilestones = data.milestones.filter((m) =>
            ['flag_candidate', 'discovery', 'strategy_change', 'error_recovery'].includes(m.type)
          )
          if (keyMilestones.length === 0) return null
          return (
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <Sparkles className="w-3 h-3 text-blue-500" />
                <span className="text-[11px] font-semibold text-blue-600">重要里程碑</span>
              </div>
              <div className="space-y-1">
                {keyMilestones.map((m, i) => {
                  const Icon = milestoneIcon[m.type] || Zap
                  return (
                    <div
                      key={i}
                      className="flex items-start gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--bg-panel)] transition-colors"
                    >
                      <Icon className="w-3 h-3 text-blue-400 flex-shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-[var(--text-primary)] leading-relaxed">{m.action}</div>
                        {m.result && (
                          <div className="text-[11px] text-[var(--text-muted)] mt-0.5 break-words">{m.result}</div>
                        )}
                      </div>
                      <span className="flex-shrink-0 text-[10px] text-[var(--text-muted)] font-mono">
                        R{m.round} {m.time}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
