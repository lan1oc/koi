import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderSearch, ShieldAlert, Clock, AlertTriangle, CheckCircle } from 'lucide-react'
import type { AuditProject } from '../types'

const BASE = '/api'

export default function AuditDashboard() {
  const [projects, setProjects] = useState<AuditProject[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    fetch(`${BASE}/audit/projects`, { headers: { 'Content-Type': 'application/json' } })
      .then((r) => r.json())
      .then((data) => setProjects(Array.isArray(data) ? data : []))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false))
  }, [])

  const total = projects.length
  const completed = projects.filter((p) => p.status === 'completed').length
  const auditing = projects.filter((p) => p.status === 'auditing').length
  const totalFindings = projects.reduce((sum, p) => sum + (p.finding_count || 0), 0)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">审计仪表盘</h1>
        <button
          onClick={() => navigate('/audit/projects')}
          className="btn-primary flex items-center gap-2"
        >
          <FolderSearch className="w-4 h-4" />
          管理项目
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={FolderSearch} label="总项目数" value={total} color="text-blue-600" />
        <StatCard icon={CheckCircle} label="已完成" value={completed} color="text-green-600" />
        <StatCard icon={Clock} label="审计中" value={auditing} color="text-amber-600" />
        <StatCard icon={ShieldAlert} label="发现漏洞" value={totalFindings} color="text-red-600" />
      </div>

      {/* Recent Projects */}
      <div className="panel">
        <div className="panel-header">
          <Clock className="w-4 h-4 text-primary-500" />
          最近项目
        </div>
        <div className="p-4">
          {loading ? (
            <div className="text-center text-gray-500 py-8">加载中...</div>
          ) : projects.length === 0 ? (
            <div className="text-center text-gray-500 py-8">
              暂无审计项目，前往项目管理创建一个
            </div>
          ) : (
            <div className="space-y-2">
              {projects.slice(0, 8).map((p) => (
                <div
                  key={p.id}
                  onClick={() => navigate(`/audit/task/${p.id}`)}
                  className="flex items-center justify-between p-3 rounded-lg bg-surface-50 hover:bg-surface-100 cursor-pointer transition-colors"
                >
                  <div>
                    <div className="text-sm font-medium text-gray-800">{p.name}</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      {p.language && <span className="mr-2">{p.language}</span>}
                      {p.framework && <span>{p.framework}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {(p.finding_count ?? 0) > 0 && (
                      <span className="flex items-center gap-1 text-xs text-red-600">
                        <AlertTriangle className="w-3 h-3" />
                        {p.finding_count}
                      </span>
                    )}
                    <StatusBadge status={p.status} />
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

function StatCard({ icon: Icon, label, value, color }: { icon: React.ElementType; label: string; value: string | number; color: string }) {
  return (
    <div className="panel p-4">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg bg-surface-50 ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <div className="text-xs text-gray-500">{label}</div>
          <div className="text-xl font-bold text-gray-900">{value}</div>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { label: string; cls: string }> = {
    pending: { label: '待审计', cls: 'bg-gray-100 text-gray-600' },
    auditing: { label: '审计中', cls: 'bg-amber-100 text-amber-700' },
    completed: { label: '已完成', cls: 'bg-green-100 text-green-700' },
    failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
  }
  const c = cfg[status] || cfg.pending
  return <span className={`px-2 py-0.5 text-xs rounded-full ${c.cls}`}>{c.label}</span>
}
