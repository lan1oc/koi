import { useEffect, useState } from 'react'
import { Plus, Search, Filter, Upload, ChevronLeft, ChevronRight } from 'lucide-react'
import { useChallengeStore } from '../stores/challengeStore'
import ChallengeCard from '../components/ChallengeCard'
import type { ChallengeCategory, ChallengeStatus } from '../types'

const BASE_CATEGORIES = ['web', 'pwn', 'reverse', 'crypto', 'misc', 'forensics']
const statuses: ChallengeStatus[] = ['unsolved', 'in_progress', 'solved', 'failed']

/** Generate page number array with ellipsis for large page counts */
function generatePageNumbers(current: number, total: number): (number | '...')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '...')[] = []
  pages.push(1)
  if (current > 3) pages.push('...')
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
    pages.push(i)
  }
  if (current < total - 2) pages.push('...')
  pages.push(total)
  return pages
}

export default function Challenges() {
  const { challenges, totalCount, currentPage, pageSize, fetchChallengesPaginated, setPage, setPageSize, loading, createChallenge, filter } = useChallengeStore()
  const [showCreate, setShowCreate] = useState(false)
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  useEffect(() => {
    fetchChallengesPaginated(1)
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      // Update filter in store and refetch page 1
      useChallengeStore.setState({
        filter: {
          ...filter,
          search: search || undefined,
          category: (catFilter || undefined) as ChallengeCategory | undefined,
          status: (statusFilter || undefined) as ChallengeStatus | undefined,
        },
        currentPage: 1,
      })
      fetchChallengesPaginated(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search, catFilter, statusFilter])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">题目管理</h1>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" />
          添加题目
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索题目..."
            className="input-field w-full pl-9"
          />
        </div>
        <select
          value={catFilter}
          onChange={(e) => setCatFilter(e.target.value)}
          className="input-field"
        >
          <option value="">全部分类</option>
          {[...new Set([...BASE_CATEGORIES, ...challenges.map((c) => c.category).filter(Boolean)])].map((c) => (
            <option key={c} value={c}>
              {c.charAt(0).toUpperCase() + c.slice(1)}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input-field"
        >
          <option value="">全部状态</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s.replace('_', ' ').charAt(0).toUpperCase() + s.replace('_', ' ').slice(1)}
            </option>
          ))}
        </select>
      </div>

      {/* Challenge Grid */}
      {loading ? (
        <div className="text-center text-gray-500 py-12">加载题目中...</div>
      ) : challenges.length === 0 ? (
        <div className="text-center text-gray-500 py-12">
          <p className="text-lg mb-2">未找到题目</p>
          <p className="text-sm">添加一个题目开始解题吧！</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {challenges.map((c) => (
              <ChallengeCard key={c.id} challenge={c} />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t border-gray-200">
              <div className="text-sm text-gray-500">
                共 {totalCount} 道题目，第 {currentPage}/{totalPages} 页
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  className="btn-secondary px-2 py-1 disabled:opacity-40"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {generatePageNumbers(currentPage, totalPages).map((p, i) =>
                  p === '...' ? (
                    <span key={`ellipsis-${i}`} className="px-2 text-gray-400">…</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p as number)}
                      className={`px-3 py-1 rounded text-sm ${
                        currentPage === p
                          ? 'bg-indigo-600 text-white'
                          : 'btn-secondary'
                      }`}
                    >
                      {p}
                    </button>
                  )
                )}
                <button
                  onClick={() => setPage(currentPage + 1)}
                  disabled={currentPage >= totalPages}
                  className="btn-secondary px-2 py-1 disabled:opacity-40"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="input-field text-sm py-1 ml-2"
                >
                  {[12, 24, 48, 96].map((n) => (
                    <option key={n} value={n}>{n} / 页</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </>
      )}

      {/* Create Modal */}
      {showCreate && <CreateChallengeModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

function CreateChallengeModal({ onClose }: { onClose: () => void }) {
  const { createChallenge } = useChallengeStore()
  const [form, setForm] = useState({
    title: '',
    category: 'web',
    platform: '',
    url: '',
    description: '',
  })
  const [creating, setCreating] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setCreating(true)
    try {
      await createChallenge(form)
      onClose()
    } catch (err) {
      console.error('Failed to create challenge:', err)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg">
        <div className="panel-header justify-between">
          <span>添加题目</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">标题 *</label>
            <input
              type="text"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="input-field w-full"
              placeholder="题目名称"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">分类</label>
              <input
                type="text"
                list="challenges-create-category-list"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="input-field w-full"
                placeholder="输入或选择分类"
              />
              <datalist id="challenges-create-category-list">
                {BASE_CATEGORIES.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">平台</label>
              <input
                type="text"
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
                className="input-field w-full"
                placeholder="HTB, THM, CTFtime..."
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">URL</label>
            <input
              type="url"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              className="input-field w-full"
              placeholder="https://..."
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">描述</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="input-field w-full resize-none"
              rows={3}
              placeholder="题目描述、提示信息..."
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">取消</button>
            <button type="submit" disabled={creating || !form.title.trim()} className="btn-primary">
              {creating ? '创建中...' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
