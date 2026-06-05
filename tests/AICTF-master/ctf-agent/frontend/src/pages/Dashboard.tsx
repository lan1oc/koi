import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Flag, Trophy, Cpu, Clock, Zap, TrendingUp, LayoutDashboard } from 'lucide-react'
import { useChallengeStore, getCategoryStats, getStatusCounts } from '../stores/challengeStore'
import ChallengeCard from '../components/ChallengeCard'
const categoryColors: Record<string, string> = {
  web: 'bg-blue-500',
  pwn: 'bg-red-500',
  reverse: 'bg-purple-500',
  crypto: 'bg-yellow-500',
  misc: 'bg-gray-500',
  forensics: 'bg-teal-500',
  blockchain: 'bg-orange-500',
  osint: 'bg-cyan-500',
  ppc: 'bg-pink-500',
  mobile: 'bg-indigo-500',
  stego: 'bg-emerald-500',
  ai: 'bg-violet-500',
}

function getCategoryColor(cat: string): string {
  return categoryColors[cat] || 'bg-gray-400'
}

export default function Dashboard() {
  const { challenges, loading } = useChallengeStore()
  const navigate = useNavigate()

  useEffect(() => {
    // Fetch all challenges (no filter) for dashboard stats
    const store = useChallengeStore.getState()
    store.fetchChallenges()
  }, [])

  const statusCounts = useMemo(() => getStatusCounts(challenges), [challenges])
  const catStats = useMemo(() => getCategoryStats(challenges), [challenges])
  const recentChallenges = useMemo(() => challenges.slice(0, 5), [challenges])

  const solved = statusCounts.solved
  const total = challenges.length
  const successRate = total > 0 ? Math.round((solved / total) * 100) : 0

  return (
  <div className="relative flex flex-col h-full">
    {/* Floating header */}
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
      <div className="flex items-center justify-between px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
        <div className="flex items-center gap-2">
          <LayoutDashboard className="w-4 h-4 text-primary-500" />
          <h1 className="text-base font-bold text-gray-900">仪表盘</h1>
        </div>
        <button
          onClick={() => navigate('/competitions')}
          className="btn-primary flex items-center gap-2"
        >
          <Flag className="w-4 h-4" />
          新建比赛
        </button>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto pt-20 px-6 pb-6 space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Flag}
          label="总题目数"
          value={total}
          color="text-blue-600"
        />
        <StatCard
          icon={Trophy}
          label="已解决"
          value={solved}
          color="text-green-600"
        />
        <StatCard
          icon={Zap}
          label="进行中"
          value={statusCounts.in_progress}
          color="text-amber-600"
        />
        <StatCard
          icon={TrendingUp}
          label="成功率"
          value={`${successRate}%`}
          color="text-primary-600"
        />
      </div>

      {/* Category Breakdown */}
      <div className="panel">
        <div className="panel-header">
          <Cpu className="w-4 h-4 text-primary-500" />
          分类统计
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {Object.entries(catStats).map(
            ([cat, stats]) => (
              <div key={cat} className="text-center p-3 rounded-lg bg-surface-50">
                <div className={`w-3 h-3 rounded-full mx-auto mb-2 ${getCategoryColor(cat)}`} />
                <div className="text-sm font-medium text-gray-500 capitalize">{cat}</div>
                <div className="text-lg font-bold text-gray-900">
                  {stats.solved}/{stats.total}
                </div>
                <div className="text-xs text-gray-500">已解决</div>
              </div>
            )
          )}
        </div>
      </div>

      {/* Recent Challenges */}
      <div className="panel">
        <div className="panel-header">
          <Clock className="w-4 h-4 text-primary-500" />
          最近题目
        </div>
        <div className="p-4">
          {loading ? (
            <div className="text-center text-gray-500 py-8">加载中...</div>
          ) : recentChallenges.length === 0 ? (
            <div className="text-center text-gray-500 py-8">
              暂无题目，添加一个开始吧！
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {recentChallenges.map((c) => (
                <ChallengeCard key={c.id} challenge={c} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  color: string
}) {
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
