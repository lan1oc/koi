import { useEffect, useState, useCallback } from 'react'
import { Lightbulb, Search, Plus, Trash2, CheckCircle, XCircle, Clock, SkipForward, FlaskConical, Bot, Flag } from 'lucide-react'
import { ideasApi } from '../services/api'
import { wsService } from '../services/websocket'
import type { Idea, IdeaAgentResult } from '../types'

function isIdeaAgentResult(v: unknown): v is IdeaAgentResult {
  if (!v || typeof v !== 'object') return false
  const o = v as Record<string, unknown>
  return (
    typeof o.idea_id === 'string' &&
    typeof o.idea_content === 'string' &&
    (o.status === 'verified' || o.status === 'failed') &&
    typeof o.summary === 'string' &&
    typeof o.flag_found === 'string' &&
    typeof o.session_id === 'string' &&
    typeof o.elapsed === 'string'
  )
}

const STATUS_CONFIG: Record<string, { icon: typeof Clock; label: string; color: string }> = {
  pending:  { icon: Clock,       label: '待验证', color: 'text-gray-500 bg-gray-50' },
  testing:  { icon: FlaskConical, label: '测试中', color: 'text-blue-600 bg-blue-50' },
  verified: { icon: CheckCircle, label: '有效',   color: 'text-green-600 bg-green-50' },
  failed:   { icon: XCircle,     label: '无效',   color: 'text-red-500 bg-red-50' },
  skipped:  { icon: SkipForward, label: '跳过',   color: 'text-yellow-600 bg-yellow-50' },
}

export default function IdeasPanel({ challengeId }: { challengeId: string }) {
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [newContent, setNewContent] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastAgentResult, setLastAgentResult] = useState<IdeaAgentResult | null>(null)

  const loadIdeas = useCallback(async () => {
    try {
      const list = await ideasApi.list(challengeId)
      setIdeas(list || [])
    } catch { /* ignore */ }
  }, [challengeId])

  useEffect(() => {
    loadIdeas()
    const unsub = wsService.on('ideas_update', (event) => {
      if (event.challenge_id === challengeId && event.data) {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
          if (Array.isArray(parsed)) setIdeas(parsed)
        } catch {
          loadIdeas()
        }
      }
    })
    const unsubResult = wsService.on('idea_agent_result', (event) => {
      if (event.challenge_id === challengeId && event.data) {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
          if (isIdeaAgentResult(parsed)) {
            setLastAgentResult(parsed)
          }
        } catch { /* ignore */ }
      }
    })
    return () => { unsub(); unsubResult() }
  }, [challengeId, loadIdeas])

  const handleAdd = async () => {
    const content = newContent.trim()
    if (!content) return
    setError(null)
    try {
      await ideasApi.create(challengeId, content)
      setNewContent('')
      loadIdeas()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleUpdateStatus = async (id: string, status: string) => {
    try {
      await ideasApi.update(id, status)
      loadIdeas()
    } catch { /* ignore */ }
  }

  const handleDelete = async (id: string) => {
    try {
      await ideasApi.delete(id)
      loadIdeas()
    } catch { /* ignore */ }
  }

  const handleClearAll = async () => {
    if (ideas.length === 0) return
    if (!window.confirm(`确定要清除当前题目的全部 ${ideas.length} 条点子吗？此操作不可撤销。`)) return
    try {
      await ideasApi.clearAll(challengeId)
      setIdeas([])
    } catch { /* ignore */ }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadIdeas()
      return
    }
    try {
      const results = await ideasApi.search(challengeId, searchQuery)
      setIdeas(results || [])
    } catch { /* ignore */ }
  }

  const filteredIdeas = ideas

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-surface-border bg-white [html.theme-dark_&]:bg-[#1a1d27]">
        <div className="flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-yellow-500" />
          <span className="text-sm font-semibold text-gray-700">解题点子</span>
          <span className="text-xs text-gray-400">({ideas.length})</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowSearch(!showSearch)}
            className={`p-1 rounded hover:bg-gray-100 ${showSearch ? 'text-primary-600' : 'text-gray-400'}`}
            title="搜索"
          >
            <Search className="w-4 h-4" />
          </button>
          <button
            onClick={handleClearAll}
            disabled={ideas.length === 0}
            className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-500 disabled:opacity-30 disabled:cursor-not-allowed"
            title="清除全部点子"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Search bar */}
      {showSearch && (
        <div className="px-3 py-2 border-b border-surface-border bg-gray-50 [html.theme-dark_&]:bg-[#13151f] flex gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="搜索点子..."
            className="flex-1 text-sm px-2 py-1 border rounded focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <button onClick={handleSearch} className="text-xs text-primary-600 hover:text-primary-700 font-medium">
            搜索
          </button>
          {searchQuery && (
            <button onClick={() => { setSearchQuery(''); loadIdeas() }} className="text-xs text-gray-400 hover:text-gray-600">
              清除
            </button>
          )}
        </div>
      )}

      {/* Add new idea */}
      <div className="px-3 py-2 border-b border-surface-border bg-white [html.theme-dark_&]:bg-[#1a1d27] flex gap-2">
        <input
          type="text"
          value={newContent}
          onChange={(e) => setNewContent(e.target.value.slice(0, 100))}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder="记录一个新点子 (≤100字)..."
          className="flex-1 text-sm px-2 py-1.5 border rounded focus:outline-none focus:ring-1 focus:ring-primary-500"
          maxLength={100}
        />
        <button
          onClick={handleAdd}
          disabled={!newContent.trim()}
          className="px-2 py-1 rounded bg-yellow-500 text-white hover:bg-yellow-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {error && (
        <div className="px-3 py-1 text-xs text-red-500 bg-red-50">{error}</div>
      )}

      {/* Agent result banner */}
      {lastAgentResult && (
        <div className={`mx-2 mt-2 rounded-lg border p-2.5 text-xs ${
          lastAgentResult.status === 'verified'
            ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
        }`}>
          <div className="flex items-center justify-between gap-1 mb-1">
            <div className="flex items-center gap-1 font-semibold">
              <Bot className="w-3.5 h-3.5" />
              <span>子 Agent 结果</span>
              <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                lastAgentResult.status === 'verified' ? 'bg-green-200' : 'bg-red-200'
              }`}>
                {lastAgentResult.status === 'verified' ? '✅ 有效' : '❌ 无效'}
              </span>
            </div>
            <button
              onClick={() => setLastAgentResult(null)}
              className="text-gray-400 hover:text-gray-600 text-xs px-1"
            >✕</button>
          </div>
          <p className="text-xs text-gray-600 mb-1 truncate">«{lastAgentResult.idea_content}»</p>
          {lastAgentResult.flag_found && (
            <div className="flex items-center gap-1 font-mono font-semibold text-green-700 bg-green-100 px-2 py-0.5 rounded mb-1">
              <Flag className="w-3 h-3" />
              <span>{lastAgentResult.flag_found}</span>
            </div>
          )}
          <p className="text-gray-600 line-clamp-3">{lastAgentResult.summary}</p>
          <p className="text-gray-400 mt-1">耗时 {lastAgentResult.elapsed}</p>
        </div>
      )}

      {/* Ideas list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {filteredIdeas.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-gray-400 text-sm">
            <Lightbulb className="w-8 h-8 mb-2 text-gray-300" />
            <span>还没有点子</span>
            <span className="text-xs mt-1">AI 做题时会自动记录解题思路</span>
          </div>
        )}
        {filteredIdeas.map((idea) => {
          const cfg = STATUS_CONFIG[idea.status] || STATUS_CONFIG.pending
          const Icon = cfg.icon
          return (
            <div
              key={idea.id}
              className={`rounded-lg border px-3 py-2 ${cfg.color} border-gray-200`}
            >
              <div className="flex items-start gap-2">
                <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 break-words">{idea.content}</p>
                  {idea.result && (
                    <p className="text-xs text-gray-500 mt-0.5">→ {idea.result}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(idea.id)}
                  className="p-0.5 text-gray-300 hover:text-red-400 flex-shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              {/* Status buttons */}
              <div className="flex items-center gap-1 mt-1.5 ml-6">
                {(['pending', 'testing', 'verified', 'failed', 'skipped'] as const).map((s) => {
                  const sc = STATUS_CONFIG[s]
                  return (
                    <button
                      key={s}
                      onClick={() => handleUpdateStatus(idea.id, s)}
                      className={`text-xs px-1.5 py-0.5 rounded transition-colors ${
                        idea.status === s
                          ? 'bg-white shadow-sm font-medium border border-gray-300'
                          : 'hover:bg-white/60 text-gray-400'
                      }`}
                    >
                      {sc.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
