import { useEffect, useState } from 'react'
import { Plus, Search, Trophy } from 'lucide-react'
import { useCompetitionStore } from '../stores/competitionStore'
import CompetitionCard from '../components/CompetitionCard'
import CompetitionFormModal from '../components/CompetitionFormModal'
import type { CompetitionStatus } from '../types'

const statuses: CompetitionStatus[] = ['active', 'archived']

export default function Competitions() {
  const { competitions, fetchCompetitions, loading } = useCompetitionStore()
  const [showCreate, setShowCreate] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  useEffect(() => {
    fetchCompetitions()
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      useCompetitionStore.getState().setFilter({
        search: search || undefined,
        status: (statusFilter || undefined) as CompetitionStatus | undefined,
      })
    }, 300)
    return () => clearTimeout(timer)
  }, [search, statusFilter])

  return (
  <div className="relative flex flex-col h-full">
    {/* Floating header */}
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
      <div className="flex items-center justify-between px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-primary-500" />
          <h1 className="text-base font-bold text-gray-900">比赛管理</h1>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" />
          添加比赛
        </button>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto pt-20 px-6 pb-6 space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索比赛..."
            className="input-field w-full pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input-field"
        >
          <option value="">全部状态</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s === 'active' ? '进行中' : '已归档'}
            </option>
          ))}
        </select>
      </div>

      {/* Competition Grid */}
      {loading ? (
        <div className="text-center text-gray-500 py-12">加载比赛中...</div>
      ) : competitions.length === 0 ? (
        <div className="text-center text-gray-500 py-12">
          <Trophy className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="text-lg mb-2">暂无比赛</p>
          <p className="text-sm">添加一个比赛开始吧！</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {competitions.map((c) => (
            <CompetitionCard key={c.id} competition={c} />
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && <CompetitionFormModal onClose={() => setShowCreate(false)} />}
      </div>
    </div>
  )
}
