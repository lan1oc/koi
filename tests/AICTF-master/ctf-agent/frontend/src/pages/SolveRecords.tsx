import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  BarChart2,
  Cpu,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Filter,
  Trophy,
  TrendingUp,
} from 'lucide-react'
import type { SolveRecord } from '../types'
import { solveStatsApi } from '../services/api'
import { challengeApi } from '../services/api'
import type { Challenge } from '../types'

const PAGE_SIZE = 50

// ─── Category color helpers ────────────────────────────────────────────────
const CATEGORY_BADGE: Record<string, string> = {
  web:        'bg-blue-100 text-blue-700 border-blue-200',
  pwn:        'bg-red-100 text-red-700 border-red-200',
  reverse:    'bg-purple-100 text-purple-700 border-purple-200',
  re:         'bg-purple-100 text-purple-700 border-purple-200',
  crypto:     'bg-yellow-100 text-yellow-700 border-yellow-200',
  misc:       'bg-gray-100 text-gray-700 border-gray-200',
  forensics:  'bg-teal-100 text-teal-700 border-teal-200',
  blockchain: 'bg-orange-100 text-orange-700 border-orange-200',
  osint:      'bg-cyan-100 text-cyan-700 border-cyan-200',
}

function getCategoryBadge(cat: string) {
  return CATEGORY_BADGE[cat.toLowerCase()] || 'bg-gray-100 text-gray-600 border-gray-200'
}

// ─── Helpers ────────────────────────────────────────────────────────────────
function formatDuration(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = Date.now()
  const diff = now - d.getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}小时前`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}天前`
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

// ─── Main Page ─────────────────────────────────────────────────────────────
export default function SolveRecords() {
  const navigate = useNavigate()
  const [records, setRecords] = useState<SolveRecord[]>([])
  const [challenges, setChallenges] = useState<Record<string, Challenge>>({})
  const [loading, setLoading] = useState(true)
  const [filterStatus, setFilterStatus] = useState<'all' | 'success' | 'failed'>('all')
  const [filterCategory, setFilterCategory] = useState<string>('all')
  const [page, setPage] = useState(1)

  const load = async () => {
    setLoading(true)
    try {
      const [statsRes, chalRes] = await Promise.all([
        solveStatsApi.list(0),
        challengeApi.list(),
      ])
      setRecords(statsRes.items)
      const map: Record<string, Challenge> = {}
      for (const c of chalRes) map[c.id] = c
      setChallenges(map)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  // Reset to page 1 when filters change
  useEffect(() => { setPage(1) }, [filterStatus, filterCategory])

  // Only show CTF-related records (those that match an existing CTF challenge)
  const ctfRecords = useMemo(() => {
    const ids = new Set(Object.keys(challenges))
    if (ids.size > 0) {
      return records.filter((r) => ids.has(r.challenge_id))
    }

    // Fallback: if challenge list isn't available, keep records that look like CTF categories.
    const ctfCats = new Set([
      'web', 'pwn', 'reverse', 're', 'crypto', 'misc', 'forensics', 'blockchain', 'osint',
    ])
    return records.filter((r) => ctfCats.has((r.category || '').toLowerCase()))
  }, [records, challenges])

  // ─── summary stats ────────────────────────────────────────────────────────
  const summary = useMemo(() => {
    if (!ctfRecords.length) return null
    const successes = ctfRecords.filter((r) => r.success).length
    const totalTokens = ctfRecords.reduce((acc, r) => acc + r.total_tokens, 0)
    const totalDuration = ctfRecords.reduce((acc, r) => acc + r.duration_secs, 0)
    return {
      total: ctfRecords.length,
      successes,
      rate: Math.round((successes / ctfRecords.length) * 100),
      totalTokens,
      avgDuration: totalDuration / ctfRecords.length,
    }
  }, [ctfRecords])

  // ─── categories for filter ────────────────────────────────────────────────
  const categories = useMemo(() => {
    const s = new Set<string>()
    ctfRecords.forEach((r) => r.category && s.add(r.category.toLowerCase()))
    return Array.from(s).sort()
  }, [ctfRecords])

  // ─── filtered list ─────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return ctfRecords.filter((r) => {
      if (filterStatus === 'success' && !r.success) return false
      if (filterStatus === 'failed' && r.success) return false
      if (filterCategory !== 'all' && r.category?.toLowerCase() !== filterCategory) return false
      return true
    })
  }, [ctfRecords, filterStatus, filterCategory])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page]
  )

  return (
    <div className="flex flex-col h-full overflow-hidden bg-surface-50">
      {/* ─── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-surface-border bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Trophy className="w-5 h-5 text-primary-500" />
            <h1 className="text-lg font-bold text-gray-800">解题记录</h1>
            {!loading && (
              <span className="text-xs text-gray-400 ml-1">共 {ctfRecords.length} 条</span>
            )}
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-surface-100 hover:bg-surface-200 text-gray-600 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>

        {/* ─── Summary cards ─────────────────────────────────────────────── */}
        {summary && (
          <div className="grid grid-cols-4 gap-3 mt-4">
            <div className="bg-surface-50 rounded-xl border border-surface-border p-3">
              <div className="text-xs text-gray-400 mb-1">总次数</div>
              <div className="text-2xl font-bold text-gray-800">{summary.total}</div>
            </div>
            <div className="bg-green-50 rounded-xl border border-green-100 p-3">
              <div className="flex items-center gap-1 text-xs text-green-600 mb-1">
                <TrendingUp className="w-3 h-3" /> 成功率
              </div>
              <div className="text-2xl font-bold text-green-700">
                {summary.rate}%
                <span className="text-xs font-normal text-green-500 ml-1">{summary.successes}/{summary.total}</span>
              </div>
            </div>
            <div className="bg-violet-50 rounded-xl border border-violet-100 p-3">
              <div className="flex items-center gap-1 text-xs text-violet-600 mb-1">
                <Zap className="w-3 h-3" /> 累计 Token
              </div>
              <div className="text-2xl font-bold text-violet-700">{formatTokens(summary.totalTokens)}</div>
            </div>
            <div className="bg-amber-50 rounded-xl border border-amber-100 p-3">
              <div className="flex items-center gap-1 text-xs text-amber-600 mb-1">
                <Clock className="w-3 h-3" /> 平均耗时
              </div>
              <div className="text-2xl font-bold text-amber-700">{formatDuration(summary.avgDuration)}</div>
            </div>
          </div>
        )}
      </div>

      {/* ─── Filters ─────────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-6 py-2.5 border-b border-surface-border bg-white flex items-center gap-3 flex-wrap">
        <Filter className="w-3.5 h-3.5 text-gray-400" />
        {/* Status filter */}
        <div className="flex items-center rounded-lg bg-surface-100 p-0.5 gap-0.5">
          {(['all', 'success', 'failed'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setFilterStatus(s)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                filterStatus === s
                  ? 'bg-white shadow text-gray-800 font-medium'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {s === 'all' ? '全部' : s === 'success' ? '✓ 成功' : '✗ 失败'}
            </button>
          ))}
        </div>
        {/* Category filter */}
        {categories.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => setFilterCategory('all')}
              className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                filterCategory === 'all'
                  ? 'bg-gray-800 text-white border-gray-800'
                  : 'border-surface-border text-gray-500 hover:border-gray-400'
              }`}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setFilterCategory(cat === filterCategory ? 'all' : cat)}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                  filterCategory === cat
                    ? getCategoryBadge(cat) + ' font-semibold'
                    : 'border-surface-border text-gray-500 hover:border-gray-400'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
        {filtered.length !== ctfRecords.length && (
          <span className="text-xs text-gray-400 ml-auto">{filtered.length} 条结果</span>
        )}
      </div>

      {/* ─── Record list ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center h-48 text-gray-400">
            <RefreshCw className="w-5 h-5 animate-spin mr-2" />
            加载中…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400">
            <BarChart2 className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm">暂无解题记录</p>
          </div>
        ) : (
          <div className="space-y-2">
            {paginated.map((rec, idx) => {
              const challenge = challenges[rec.challenge_id]
              const title = challenge?.title || rec.challenge_id.slice(0, 8) + '…'
              const topTools = Object.entries(rec.tool_usage || {})
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([t]) => t)

              return (
                <div
                  key={`${rec.session_id}-${idx}`}
                  onClick={() => navigate(`/solve/${rec.challenge_id}`)}
                  className={`
                    group bg-white rounded-xl border transition-all duration-150 cursor-pointer
                    hover:shadow-md hover:-translate-y-px
                    ${rec.success
                      ? 'border-green-100 hover:border-green-200 hover:shadow-green-50'
                      : 'border-surface-border hover:border-gray-200'}
                  `}
                >
                  <div className="flex items-center gap-3 px-4 py-3">
                    {/* Success/Fail icon */}
                    <div className="flex-shrink-0">
                      {rec.success ? (
                        <CheckCircle2 className="w-5 h-5 text-green-500" />
                      ) : (
                        <XCircle className="w-5 h-5 text-gray-300" />
                      )}
                    </div>

                    {/* Title + category */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-medium text-sm text-gray-800 truncate" title={title}>
                          {title}
                        </span>
                        {rec.category && (
                          <span className={`flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${getCategoryBadge(rec.category)}`}>
                            {rec.category.toLowerCase()}
                          </span>
                        )}
                      </div>
                      {/* Sub-info row */}
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] text-gray-400 flex-wrap">
                        {rec.model && (
                          <span className="flex items-center gap-0.5">
                            <Cpu className="w-3 h-3" />
                            {rec.model.length > 20 ? rec.model.slice(0, 20) + '…' : rec.model}
                          </span>
                        )}
                        <span>{rec.rounds} 轮</span>
                        <span>{rec.tool_calls} 工具调用</span>
                        {topTools.length > 0 && (
                          <span className="text-gray-300">{topTools.join('·')}</span>
                        )}
                      </div>
                    </div>

                    {/* Stats group */}
                    <div className="flex items-center gap-4 flex-shrink-0">
                      {/* Token */}
                      <div className="text-center">
                        <div className="flex items-center gap-0.5 text-xs text-violet-600 font-semibold">
                          <Zap className="w-3 h-3" />
                          {formatTokens(rec.total_tokens)}
                        </div>
                        <div className="text-[10px] text-gray-400 text-center">tokens</div>
                      </div>

                      {/* Duration */}
                      <div className="text-center">
                        <div className="flex items-center gap-0.5 text-xs text-amber-600 font-semibold">
                          <Clock className="w-3 h-3" />
                          {formatDuration(rec.duration_secs)}
                        </div>
                        <div className="text-[10px] text-gray-400 text-center">耗时</div>
                      </div>

                      {/* Time */}
                      <div className="text-right hidden sm:block">
                        <div className="text-xs text-gray-400">{formatTime(rec.finished_at)}</div>
                      </div>

                      <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-gray-400 transition-colors" />
                    </div>
                  </div>

                  {/* Flag row — full width, only when solved */}
                  {rec.success && rec.flag_found && (
                    <div className="px-4 pb-2.5 -mt-1">
                      <div className="flex items-center gap-1.5 bg-green-50 rounded-lg px-3 py-1.5 border border-green-100">
                        <span className="text-[10px] text-green-500 font-semibold flex-shrink-0">FLAG</span>
                        <span className="text-xs text-green-700 font-mono break-all select-all">
                          {rec.flag_found}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {/* ─── Pagination ─────────────────────────────────────────────────────── */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-4 mt-2 border-t border-surface-border">
            <span className="text-xs text-gray-400">
              第 {page} / {totalPages} 页，共 {filtered.length} 条
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-500 disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
                .reduce<(number | -1)[]>((acc, p, i, arr) => {
                  if (i > 0 && p - (arr[i - 1] as number) > 1) acc.push(-1)
                  acc.push(p)
                  return acc
                }, [])
                .map((p, i) =>
                  p === -1 ? (
                    <span key={`ell-${i}`} className="px-1 text-xs text-gray-400">…</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`min-w-[28px] h-7 text-xs rounded-lg transition-colors ${
                        page === p
                          ? 'bg-primary-500 text-white font-semibold'
                          : 'hover:bg-surface-hover text-gray-600'
                      }`}
                    >
                      {p}
                    </button>
                  )
                )}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-500 disabled:opacity-30 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}      </div>
    </div>
  )
}
