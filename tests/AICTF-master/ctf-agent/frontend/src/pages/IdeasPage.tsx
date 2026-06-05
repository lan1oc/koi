import { useState, useEffect, useMemo } from 'react'
import { ideasApi } from '../services/api'
import { useChallengeStore } from '../stores/challengeStore'
import { Lightbulb, RefreshCw, Search, Plus, CheckCircle, XCircle, Clock, Trash2, ChevronRight } from 'lucide-react'
import type { Idea, Challenge } from '../types'

const statusConfig: Record<string, { label: string; icon: React.ElementType; cls: string }> = {
  pending: { label: '待验证', icon: Clock, cls: 'text-gray-500 bg-gray-100' },
  tried: { label: '已尝试', icon: RefreshCw, cls: 'text-amber-600 bg-amber-100' },
  success: { label: '成功', icon: CheckCircle, cls: 'text-green-600 bg-green-100' },
  failed: { label: '失败', icon: XCircle, cls: 'text-red-600 bg-red-100' },
}

export default function IdeasPage() {
  const { challenges } = useChallengeStore()
  const [selectedChallenge, setSelectedChallenge] = useState<string>('')
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [newIdea, setNewIdea] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    const store = useChallengeStore.getState()
    store.fetchChallenges()
  }, [])

  useEffect(() => {
    if (selectedChallenge) loadIdeas(selectedChallenge)
  }, [selectedChallenge])

  const loadIdeas = async (challengeId: string) => {
    setLoading(true)
    try {
      const data = await ideasApi.list(challengeId)
      setIdeas(Array.isArray(data) ? data : [])
    } catch {
      setIdeas([])
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!selectedChallenge || !newIdea.trim()) return
    setCreating(true)
    try {
      await ideasApi.create(selectedChallenge, newIdea.trim())
      setNewIdea('')
      await loadIdeas(selectedChallenge)
    } catch (e) {
      console.error('Failed to create idea:', e)
    } finally {
      setCreating(false)
    }
  }

  const handleStatusChange = async (id: string, status: string) => {
    try {
      await ideasApi.update(id, status)
      await loadIdeas(selectedChallenge)
    } catch (e) {
      console.error('Failed to update idea:', e)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await ideasApi.delete(id)
      await loadIdeas(selectedChallenge)
    } catch (e) {
      console.error('Failed to delete idea:', e)
    }
  }

  const filteredChallenges = useMemo(() => {
    if (!search) return challenges
    const q = search.toLowerCase()
    return challenges.filter(
      (c) => c.title.toLowerCase().includes(q) || c.category?.toLowerCase().includes(q)
    )
  }, [challenges, search])

  return (
    <div className="flex h-full">
      {/* Left panel: challenge selector */}
      <div className="w-72 flex-shrink-0 border-r border-surface-border flex flex-col bg-white">
        <div className="px-4 py-3 border-b border-surface-border">
          <h1 className="text-sm font-bold text-gray-900 flex items-center gap-2 mb-3">
            <Lightbulb className="w-4 h-4 text-amber-500" />
            点子管理
          </h1>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="搜索题目..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {filteredChallenges.length === 0 ? (
            <div className="text-center py-12 text-gray-400 text-sm">暂无题目</div>
          ) : (
            filteredChallenges.map((c: Challenge) => (
              <button
                key={c.id}
                onClick={() => setSelectedChallenge(c.id)}
                className={`w-full text-left px-4 py-2.5 border-b border-surface-border transition-colors ${
                  selectedChallenge === c.id
                    ? 'bg-primary-50 border-l-2 border-l-primary-500'
                    : 'hover:bg-surface-hover'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-800 truncate">{c.title}</span>
                  <ChevronRight className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" />
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] text-gray-400">{c.category}</span>
                  <span className={`text-[10px] px-1.5 rounded-full ${
                    c.status === 'solved' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {c.status}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right panel: ideas */}
      <div className="flex-1 flex flex-col bg-white">
        {selectedChallenge ? (
          <>
            <div className="px-6 py-3 border-b border-surface-border">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-gray-900">
                  {challenges.find((c) => c.id === selectedChallenge)?.title || '点子'}
                </h2>
                <span className="text-xs text-gray-400">{ideas.length} 个点子</span>
              </div>
              {/* New idea input */}
              <div className="flex items-center gap-2 mt-3">
                <input
                  type="text"
                  placeholder="输入新的解题思路..."
                  value={newIdea}
                  onChange={(e) => setNewIdea(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  className="flex-1 px-3 py-2 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
                <button
                  onClick={handleCreate}
                  disabled={creating || !newIdea.trim()}
                  className="flex items-center gap-1 px-3 py-2 bg-amber-500 text-white rounded-lg text-sm hover:bg-amber-600 disabled:opacity-50 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  添加
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {loading ? (
                <div className="text-center text-gray-400 py-8">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                  加载中...
                </div>
              ) : ideas.length === 0 ? (
                <div className="text-center text-gray-400 py-12">
                  <Lightbulb className="w-10 h-10 mx-auto mb-2 text-gray-300" />
                  <p className="text-sm">暂无点子，添加一个解题思路吧</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {ideas.map((idea) => {
                    const st = statusConfig[idea.status] || statusConfig.pending
                    const StIcon = st.icon
                    return (
                      <div key={idea.id} className="group flex items-start gap-3 p-3 rounded-lg bg-surface-50 hover:bg-surface-100 transition-colors">
                        <div className={`p-1.5 rounded-lg ${st.cls} flex-shrink-0 mt-0.5`}>
                          <StIcon className="w-3.5 h-3.5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-800">{idea.content}</p>
                          {idea.result && (
                            <p className="text-xs text-gray-500 mt-1 bg-white rounded px-2 py-1">{idea.result}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                          <select
                            value={idea.status}
                            onChange={(e) => handleStatusChange(idea.id, e.target.value)}
                            className="text-xs border border-surface-border rounded px-1.5 py-1 bg-white"
                          >
                            <option value="pending">待验证</option>
                            <option value="tried">已尝试</option>
                            <option value="success">成功</option>
                            <option value="failed">失败</option>
                          </select>
                          <button
                            onClick={() => handleDelete(idea.id)}
                            className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-500"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <Lightbulb className="w-12 h-12 mx-auto mb-3 text-gray-300" />
              <p className="text-sm">选择一个题目/项目查看和管理点子</p>
              <p className="text-xs mt-1 text-gray-300">
                点子系统帮助 AI 和你记录、跟踪解题思路
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
