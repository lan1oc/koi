import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Monitor, ShieldCheck, AlertTriangle, CheckCircle, Activity, Clock } from 'lucide-react'
import type { InspectionHost } from '../types'

const BASE = '/api'

export default function InspectionDashboard() {
  const [hosts, setHosts] = useState<InspectionHost[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    fetch(`${BASE}/inspection/hosts`, { headers: { 'Content-Type': 'application/json' } })
      .then((r) => r.json())
      .then((data) => setHosts(Array.isArray(data) ? data : []))
      .catch(() => setHosts([]))
      .finally(() => setLoading(false))
  }, [])

  const total = hosts.length
  const completed = hosts.filter((h) => h.status === 'completed').length
  const running = hosts.filter((h) => h.status === 'running').length
  const totalIssues = hosts.reduce((sum, h) => sum + (h.issue_count ?? 0), 0)
  const totalWarns = hosts.reduce((sum, h) => sum + (h.warn_count ?? 0), 0)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Linux 巡检仪表盘</h1>
        <button
          onClick={() => navigate('/inspection/hosts')}
          className="btn-primary flex items-center gap-2"
        >
          <Monitor className="w-4 h-4" />
          管理主机
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard icon={Monitor} label="总主机数" value={total} color="text-blue-600" />
        <StatCard icon={CheckCircle} label="已完成" value={completed} color="text-green-600" />
        <StatCard icon={Activity} label="巡检中" value={running} color="text-amber-600" />
        <StatCard icon={AlertTriangle} label="严重问题" value={totalIssues} color="text-red-600" />
        <StatCard icon={ShieldCheck} label="警告" value={totalWarns} color="text-orange-500" />
      </div>

      {/* Recent Hosts */}
      <div className="panel">
        <div className="panel-header">
          <Clock className="w-4 h-4 text-primary-500" />
          最近巡检主机
        </div>
        <div className="p-4">
          {loading ? (
            <div className="text-center text-gray-500 py-8">加载中...</div>
          ) : hosts.length === 0 ? (
            <div className="text-center text-gray-500 py-8">
              暂无巡检主机，前往主机管理添加一个
            </div>
          ) : (
            <div className="space-y-3">
              {hosts.slice(0, 10).map((h) => (
                <div
                  key={h.id}
                  onClick={() => navigate('/inspection/hosts')}
                  className="flex items-center justify-between p-3 rounded-lg border border-gray-100 hover:border-gray-200 hover:bg-gray-50/50 cursor-pointer transition-all"
                >
                  <div className="flex items-center gap-3">
                    <Monitor className="w-5 h-5 text-gray-400" />
                    <div>
                      <div className="font-medium text-gray-900">{h.name}</div>
                      <div className="text-xs text-gray-500">{h.host}:{h.port} ({h.username})</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    {h.issue_count > 0 && (
                      <span className="text-xs px-2 py-1 rounded-full bg-red-50 text-red-600">
                        {h.issue_count} 严重
                      </span>
                    )}
                    {h.warn_count > 0 && (
                      <span className="text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-600">
                        {h.warn_count} 警告
                      </span>
                    )}
                    {h.pass_count > 0 && (
                      <span className="text-xs px-2 py-1 rounded-full bg-green-50 text-green-600">
                        {h.pass_count} 正常
                      </span>
                    )}
                    <StatusBadge status={h.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color }: { icon: React.ComponentType<{ className?: string }>; label: string; value: number; color: string }) {
  return (
    <div className="panel p-4 flex items-center gap-3">
      <div className={`p-2 rounded-lg bg-gray-50 ${color}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <div className="text-2xl font-bold text-gray-900">{value}</div>
        <div className="text-xs text-gray-500">{label}</div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string }> = {
    idle: { label: '待巡检', color: 'text-gray-500 bg-gray-50' },
    running: { label: '巡检中', color: 'text-blue-600 bg-blue-50' },
    completed: { label: '已完成', color: 'text-green-600 bg-green-50' },
    failed: { label: '失败', color: 'text-red-600 bg-red-50' },
  }
  const c = config[status] || config.idle
  return (
    <span className={`text-xs px-2 py-1 rounded-full ${c.color}`}>{c.label}</span>
  )
}
