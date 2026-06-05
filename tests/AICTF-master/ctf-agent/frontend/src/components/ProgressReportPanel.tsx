import { useEffect, useState, useCallback, useRef } from 'react'
import { RefreshCw, FileBarChart, Loader2 } from 'lucide-react'
import { challengeApi } from '../services/api'
import { wsService } from '../services/websocket'
import MarkdownRenderer from './MarkdownRenderer'

interface ProgressReportPanelProps {
  challengeId: string
  isRunning: boolean
}

export default function ProgressReportPanel({ challengeId, isRunning }: ProgressReportPanelProps) {
  const [content, setContent] = useState<string>('')
  const [exists, setExists] = useState(false)
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchReport = useCallback(async () => {
    if (!challengeId) return
    setLoading(true)
    try {
      const res = await challengeApi.getProgressReport(challengeId)
      setContent(res.content || '')
      setExists(res.exists)
      if (res.exists) {
        setLastUpdate(new Date())
      }
    } catch (e) {
      console.warn('Failed to fetch progress report:', e)
    } finally {
      setLoading(false)
    }
  }, [challengeId])

  // Initial fetch
  useEffect(() => {
    fetchReport()
  }, [fetchReport])

  // Listen for WebSocket progress_report_updated events for instant refresh
  useEffect(() => {
    const unsub = wsService.on('progress_report_updated', () => {
      fetchReport()
    })
    return () => unsub()
  }, [fetchReport])

  // Auto-refresh while agent is running
  useEffect(() => {
    if (autoRefresh && isRunning) {
      timerRef.current = setInterval(fetchReport, 15000) // every 15 seconds
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [autoRefresh, isRunning, fetchReport])

  if (!exists && !loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
        <FileBarChart className="w-8 h-8 opacity-30" />
        <span className="text-sm">暂无进度报告</span>
        <span className="text-xs text-gray-300">Agent 开始运行后将自动生成 PROGRESS.md</span>
        <button
          onClick={fetchReport}
          className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-gray-50 border border-gray-200 text-gray-500 hover:bg-gray-100 transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          刷新
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white/60 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <FileBarChart className="w-3.5 h-3.5 text-blue-500" />
          <span className="text-xs font-medium text-gray-700">进度报告</span>
          {loading && <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />}
        </div>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-[10px] text-gray-400">
              更新于 {lastUpdate.toLocaleTimeString('zh-CN')}
            </span>
          )}
          <label className="flex items-center gap-1 text-[10px] text-gray-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="w-3 h-3 rounded border-gray-300 text-blue-500 focus:ring-blue-300"
            />
            自动刷新
          </label>
          <button
            onClick={fetchReport}
            disabled={loading}
            className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-50"
            title="手动刷新"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {content ? (
          <MarkdownRenderer content={content} className="progress-report-content" />
        ) : loading ? (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            加载中...
          </div>
        ) : null}
      </div>
    </div>
  )
}
