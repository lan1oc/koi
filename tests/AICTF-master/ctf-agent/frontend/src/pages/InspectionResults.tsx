import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Download,
  FileText,
  Code,
  Globe,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  Info,
  Shield,
  Clock,
  Monitor,
} from 'lucide-react'
import type { InspectionHost, InspectionRun, InspectionResult, InspectionSeverity } from '../types'
import { inspectionApi } from '../services/api'

const severityConfig: Record<InspectionSeverity, { label: string; color: string; bg: string; icon: React.ComponentType<{ className?: string }> }> = {
  critical: { label: '严重', color: 'text-red-600', bg: 'bg-red-50 border-red-200', icon: AlertTriangle },
  warning:  { label: '警告', color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200', icon: Shield },
  info:     { label: '信息', color: 'text-blue-600', bg: 'bg-blue-50 border-blue-200', icon: Info },
  pass:     { label: '正常', color: 'text-green-600', bg: 'bg-green-50 border-green-200', icon: CheckCircle2 },
}

const moduleLabels: Record<string, string> = {
  system_info: '系统信息', cpu: 'CPU', memory: '内存', disk: '磁盘',
  network: '网络', process: '进程', service: '服务', security: '安全',
  user: '用户', log: '日志', docker: 'Docker', cron: '定时任务',
  connection: '连接',
}

export default function InspectionResults() {
  const { hostId } = useParams<{ hostId: string }>()
  const navigate = useNavigate()
  const [host, setHost] = useState<InspectionHost | null>(null)
  const [runs, setRuns] = useState<InspectionRun[]>([])
  const [selectedRun, setSelectedRun] = useState<InspectionRun | null>(null)
  const [results, setResults] = useState<InspectionResult[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const [filterSeverity, setFilterSeverity] = useState<string>('all')
  const [filterModule, setFilterModule] = useState<string>('all')

  const fetchData = useCallback(async () => {
    if (!hostId) return
    setLoading(true)
    try {
      const [hostData, runsData] = await Promise.all([
        inspectionApi.getHost(hostId),
        inspectionApi.listRuns(hostId),
      ])
      setHost(hostData)
      setRuns(runsData || [])

      // Auto-select the latest run
      if (runsData && runsData.length > 0) {
        setSelectedRun(runsData[0])
        const resultsData = await inspectionApi.listResults(runsData[0].id)
        setResults(resultsData || [])
      }
    } catch (e) {
      console.error('Failed to fetch data:', e)
    } finally {
      setLoading(false)
    }
  }, [hostId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Auto-refresh when run is still running
  useEffect(() => {
    if (!selectedRun || selectedRun.status !== 'running') return
    const interval = setInterval(async () => {
      if (!hostId || !selectedRun) return
      try {
        const runsData = await inspectionApi.listRuns(hostId)
        setRuns(runsData || [])
        const updatedRun = runsData?.find((r) => r.id === selectedRun.id)
        if (updatedRun) {
          setSelectedRun(updatedRun)
          const resultsData = await inspectionApi.listResults(updatedRun.id)
          setResults(resultsData || [])
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [selectedRun, hostId])

  const handleSelectRun = async (run: InspectionRun) => {
    setSelectedRun(run)
    try {
      const data = await inspectionApi.listResults(run.id)
      setResults(data || [])
    } catch (e) {
      console.error('Failed to fetch results:', e)
    }
  }

  const toggleExpanded = (id: string) => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Group results by module
  const groupedResults = results.reduce<Record<string, InspectionResult[]>>((acc, r) => {
    if (!acc[r.module]) acc[r.module] = []
    acc[r.module].push(r)
    return acc
  }, {})

  // Apply filters
  const filteredGrouped = Object.entries(groupedResults).reduce<Record<string, InspectionResult[]>>((acc, [mod, items]) => {
    if (filterModule !== 'all' && mod !== filterModule) return acc
    const filtered = items.filter((r) => filterSeverity === 'all' || r.severity === filterSeverity)
    if (filtered.length > 0) acc[mod] = filtered
    return acc
  }, {})

  const score = selectedRun
    ? (() => {
        const total = selectedRun.issue_count + selectedRun.warn_count + selectedRun.pass_count
        return total > 0 ? Math.round((selectedRun.pass_count / total) * 100) : 0
      })()
    : 0

  const scoreColor = score >= 80 ? 'text-green-600' : score >= 60 ? 'text-amber-600' : 'text-red-600'

  if (loading) {
    return <div className="p-6 text-center text-gray-500">加载中...</div>
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/inspection/hosts')} className="p-2 rounded-lg hover:bg-gray-100 transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">{host?.name || '巡检结果'}</h1>
          <p className="text-sm text-gray-500">{host?.host}:{host?.port} ({host?.username})</p>
        </div>
        {selectedRun && (
          <div className="flex items-center gap-2">
            <a
              href={inspectionApi.exportReport(selectedRun.id, 'markdown')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 hover:bg-gray-50 transition-colors"
            >
              <FileText className="w-4 h-4" /> Markdown
            </a>
            <a
              href={inspectionApi.exportReport(selectedRun.id, 'html')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 hover:bg-gray-50 transition-colors"
            >
              <Globe className="w-4 h-4" /> HTML
            </a>
            <a
              href={inspectionApi.exportReport(selectedRun.id, 'json')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 hover:bg-gray-50 transition-colors"
            >
              <Code className="w-4 h-4" /> JSON
            </a>
          </div>
        )}
      </div>

      {/* Run selector & Score */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Score card */}
        {selectedRun && (
          <div className="panel p-6 text-center">
            <div className={`text-5xl font-bold ${scoreColor}`}>{score}</div>
            <div className="text-sm text-gray-500 mt-1">健康评分</div>
            <div className="flex justify-center gap-3 mt-3 text-xs">
              <span className="text-red-600">{selectedRun.issue_count} 严重</span>
              <span className="text-amber-600">{selectedRun.warn_count} 警告</span>
              <span className="text-green-600">{selectedRun.pass_count} 正常</span>
            </div>
            {selectedRun.status === 'running' && (
              <div className="mt-2 text-xs text-blue-600 animate-pulse">巡检进行中...</div>
            )}
          </div>
        )}

        {/* Run history */}
        <div className="panel p-4 lg:col-span-3">
          <div className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
            <Clock className="w-4 h-4" /> 巡检历史
          </div>
          {runs.length === 0 ? (
            <div className="text-sm text-gray-400">暂无巡检记录</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {runs.map((run) => (
                <button
                  key={run.id}
                  onClick={() => handleSelectRun(run)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    selectedRun?.id === run.id
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-600'
                  }`}
                >
                  {new Date(run.started_at).toLocaleString()}
                  <span className={`ml-2 ${
                    run.status === 'completed' ? 'text-green-500' :
                    run.status === 'running' ? 'text-blue-500' :
                    run.status === 'failed' ? 'text-red-500' : 'text-gray-400'
                  }`}>
                    ({run.status === 'completed' ? '完成' : run.status === 'running' ? '进行中' : run.status === 'failed' ? '失败' : run.status})
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Filters */}
      {results.length > 0 && (
        <div className="flex items-center gap-3">
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 focus:border-blue-300"
          >
            <option value="all">全部级别</option>
            <option value="critical">严重</option>
            <option value="warning">警告</option>
            <option value="info">信息</option>
            <option value="pass">正常</option>
          </select>
          <select
            value={filterModule}
            onChange={(e) => setFilterModule(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 focus:border-blue-300"
          >
            <option value="all">全部模块</option>
            {Object.keys(groupedResults).map((mod) => (
              <option key={mod} value={mod}>{moduleLabels[mod] || mod}</option>
            ))}
          </select>
          <span className="text-xs text-gray-400">
            共 {Object.values(filteredGrouped).reduce((s, arr) => s + arr.length, 0)} 条记录
          </span>
        </div>
      )}

      {/* Results by module */}
      {Object.entries(filteredGrouped).map(([module, items]) => (
        <div key={module} className="panel overflow-hidden">
          <div className="px-4 py-3 bg-gray-50/80 border-b border-gray-100 flex items-center gap-2">
            <Monitor className="w-4 h-4 text-gray-400" />
            <span className="font-semibold text-gray-800">{moduleLabels[module] || module}</span>
            <span className="text-xs text-gray-400 ml-2">{items.length} 项</span>
          </div>
          <div className="divide-y divide-gray-50">
            {items.map((r) => {
              const sev = severityConfig[r.severity] || severityConfig.info
              const SevIcon = sev.icon
              const expanded = expandedItems.has(r.id)
              return (
                <div key={r.id} className="px-4 py-3">
                  <div
                    className="flex items-start gap-3 cursor-pointer"
                    onClick={() => r.raw_output && toggleExpanded(r.id)}
                  >
                    <SevIcon className={`w-4 h-4 mt-0.5 ${sev.color} flex-shrink-0`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-900 text-sm">{r.check_name}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded-full ${sev.bg} ${sev.color} border`}>
                          {sev.label}
                        </span>
                      </div>
                      <div className="text-sm text-gray-600 mt-0.5">{r.summary}</div>
                      {r.detail && (
                        <div className="text-xs text-gray-400 mt-1">💡 {r.detail}</div>
                      )}
                    </div>
                    {r.raw_output && (
                      <div className="flex-shrink-0 text-gray-300">
                        {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                      </div>
                    )}
                  </div>
                  {expanded && r.raw_output && (
                    <div className="mt-2 ml-7 bg-gray-50 rounded-lg p-3 overflow-x-auto">
                      <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono">
                        {r.raw_output.length > 5000 ? r.raw_output.slice(0, 5000) + '\n... (输出已截断)' : r.raw_output}
                      </pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {results.length === 0 && selectedRun && selectedRun.status !== 'running' && (
        <div className="text-center text-gray-500 py-12">暂无巡检结果</div>
      )}

      {!selectedRun && (
        <div className="text-center text-gray-500 py-12">暂无巡检记录，请先执行巡检</div>
      )}
    </div>
  )
}
