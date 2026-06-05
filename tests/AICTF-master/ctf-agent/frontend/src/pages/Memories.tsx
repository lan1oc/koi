import { useState, useEffect, useCallback } from 'react'
import { memoriesApi, tagsApi, tipsApi, type Memory, type AutoTagProgress } from '../services/api'
import type { TipCategory } from '../types'
import {
  History, RefreshCw, Search, Pencil, Save, Trash2, X, Sparkles, Tag,
  Cpu, Zap, CheckCircle2, Lightbulb, Plus, ChevronRight, Brain,
} from 'lucide-react'
import { useSettingsStore } from '../stores/settingsStore'

type ActiveTab = 'memories' | 'tips'

const tipCategoryLabels: Record<string, string> = {
  general: '通用经验',
  web: 'Web 安全',
  pwn: '二进制漏洞',
  reverse: '逆向工程',
  crypto: '密码学',
  misc: '杂项',
  forensics: '数字取证',
  tool_usage: '工具使用',
  platform_ctfd: 'CTFd 平台',
  platform_gzctf: 'GZCTF 平台',
}

export default function Memories() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('memories')

  // ── Memories state ──
  const [memories, setMemories] = useState<Memory[]>([])
  const [memLoading, setMemLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Memory | null>(null)
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [tagging, setTagging] = useState(false)
  const [tagProgress, setTagProgress] = useState<AutoTagProgress | null>(null)

  // Embedding state
  const [embStats, setEmbStats] = useState<{
    total: number; embedded: number; has_embedder: boolean; model: string; enabled: boolean
  } | null>(null)
  const [backfilling, setBackfilling] = useState(false)
  const [backfillResult, setBackfillResult] = useState<{ updated: number } | null>(null)

  // ── Tips state ──
  const [tipCategories, setTipCategories] = useState<TipCategory[]>([])
  const [tipsLoading, setTipsLoading] = useState(true)
  const [selectedTipCat, setSelectedTipCat] = useState<string>('')
  const [tipEditContent, setTipEditContent] = useState('')
  const [tipOriginalContent, setTipOriginalContent] = useState('')
  const [tipDirty, setTipDirty] = useState(false)
  const [tipSaving, setTipSaving] = useState(false)
  const [tipSaved, setTipSaved] = useState(false)
  const [showNewCategory, setShowNewCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')

  // Tips embedding state
  const [tipEmbStats, setTipEmbStats] = useState<{
    total: number; embedded: number; has_embedder: boolean; model: string; enabled: boolean
  } | null>(null)
  const [tipBackfilling, setTipBackfilling] = useState(false)
  const [tipBackfillResult, setTipBackfillResult] = useState<{ updated: number } | null>(null)

  useEffect(() => {
    loadMemories()
    loadEmbeddingStats()
    loadTips()
    loadTipEmbeddingStats()
  }, [])

  // Poll progress while tagging
  useEffect(() => {
    if (!tagging) return
    const interval = setInterval(async () => {
      try {
        const p = await tagsApi.progress('memories')
        setTagProgress(p)
        if (!p.running) {
          setTagging(false)
          loadMemories()
        }
      } catch { /* ignore */ }
    }, 2000)
    return () => clearInterval(interval)
  }, [tagging])

  // ── Memory loaders ──
  const loadMemories = async () => {
    setMemLoading(true)
    try {
      const data = await memoriesApi.list()
      setMemories(Array.isArray(data) ? data : [])
    } catch {
      setMemories([])
    } finally {
      setMemLoading(false)
    }
  }

  const loadEmbeddingStats = async () => {
    try {
      const stats = await memoriesApi.embeddingStats()
      setEmbStats(stats)
    } catch { /* embedding API not available */ }
  }

  const handleBackfill = async () => {
    setBackfilling(true)
    setBackfillResult(null)
    try {
      const result = await memoriesApi.backfillEmbeddings()
      setBackfillResult(result)
      await loadEmbeddingStats()
    } catch (e) {
      console.error('Backfill failed:', e)
    } finally {
      setBackfilling(false)
    }
  }

  const handleMemSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      await memoriesApi.update(selected.id, editContent)
      setSelected({ ...selected, content: editContent })
      setEditing(false)
      await loadMemories()
    } catch (e) {
      console.error('Failed to update memory:', e)
    } finally {
      setSaving(false)
    }
  }

  const handleMemDelete = async (id: string) => {
    if (!confirm('确定要删除这条经验吗？')) return
    try {
      await memoriesApi.delete(id)
      if (selected?.id === id) { setSelected(null); setEditing(false) }
      await loadMemories()
    } catch (e) {
      console.error('Failed to delete memory:', e)
    }
  }

  const handleAutoTag = useCallback(async () => {
    try {
      const { utilityModel, selectedModel } = useSettingsStore.getState()
      const effectiveModel = utilityModel || selectedModel || undefined
      setTagging(true)
      setTagProgress({ total: 0, done: 0, failed: 0, running: true, message: '启动中...' })
      await tagsApi.autoTagMemories(true, effectiveModel)
    } catch (e) {
      console.error('Auto-tag memories failed:', e)
      setTagging(false)
    }
  }, [])

  // ── Tips loaders ──
  const loadTips = async () => {
    setTipsLoading(true)
    try {
      const data = await tipsApi.list()
      setTipCategories(data || [])
    } catch {
      setTipCategories([])
    } finally {
      setTipsLoading(false)
    }
  }

  const handleSelectTip = (category: string) => {
    if (tipDirty && !confirm('当前修改未保存，确定切换吗？')) return
    setSelectedTipCat(category)
    const tip = tipCategories.find((t) => t.category === category)
    const content = tip?.content || ''
    setTipEditContent(content)
    setTipOriginalContent(content)
    setTipDirty(false)
    setTipSaved(false)
  }

  const handleTipSave = async () => {
    if (!selectedTipCat) return
    setTipSaving(true)
    try {
      await tipsApi.update(selectedTipCat, tipEditContent)
      const data = await tipsApi.list()
      setTipCategories(data || [])
      setTipOriginalContent(tipEditContent)
      setTipSaved(true)
      setTipDirty(false)
      setTimeout(() => setTipSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save tip:', err)
    } finally {
      setTipSaving(false)
    }
  }

  const handleCreateCategory = async () => {
    const name = newCategoryName.trim()
    if (!name) return
    try {
      await tipsApi.create(name, '')
      const data = await tipsApi.list()
      setTipCategories(data || [])
      setShowNewCategory(false)
      setNewCategoryName('')
      handleSelectTip(name)
    } catch (err) {
      console.error('Failed to create category:', err)
    }
  }

  const handleDeleteCategory = async (category: string) => {
    if (!confirm(`确定删除经验分类 "${tipCategoryLabels[category] || category}" 吗？其中的所有经验将丢失。`)) return
    try {
      await tipsApi.delete(category)
      const data = await tipsApi.list()
      setTipCategories(data || [])
      if (selectedTipCat === category) {
        setSelectedTipCat('')
        setTipEditContent('')
        setTipOriginalContent('')
        setTipDirty(false)
      }
    } catch (err) {
      console.error('Failed to delete category:', err)
    }
  }

  // ── Tips embedding functions ──
  const loadTipEmbeddingStats = async () => {
    try {
      const stats = await tipsApi.embeddingStats()
      setTipEmbStats(stats)
    } catch { /* tip embedding API not available */ }
  }

  const handleTipBackfill = async () => {
    setTipBackfilling(true)
    setTipBackfillResult(null)
    try {
      const result = await tipsApi.backfillEmbeddings()
      setTipBackfillResult(result)
      await loadTipEmbeddingStats()
    } catch (e) {
      console.error('Tip backfill failed:', e)
    } finally {
      setTipBackfilling(false)
    }
  }

  // ── Filtered/grouped memories ──
  const filtered = memories.filter(
    (m) =>
      !search ||
      m.content.toLowerCase().includes(search.toLowerCase()) ||
      m.category?.toLowerCase().includes(search.toLowerCase())
  )

  const grouped = filtered.reduce<Record<string, Memory[]>>((acc, m) => {
    const cat = m.category || 'general'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(m)
    return acc
  }, {})

  // ─────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* Top tab bar */}
      <div className="flex items-center gap-0 border-b border-surface-border bg-white px-4 flex-shrink-0">
        <button
          onClick={() => setActiveTab('memories')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'memories'
              ? 'border-primary-500 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Brain className="w-4 h-4" />
          自动总结
          {memories.length > 0 && (
            <span className="ml-1 px-1.5 py-0.5 text-[10px] rounded-full bg-primary-100 text-primary-600 font-medium">
              {memories.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab('tips')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'tips'
              ? 'border-primary-500 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Lightbulb className="w-4 h-4" />
          经验提示
          {tipCategories.length > 0 && (
            <span className="ml-1 px-1.5 py-0.5 text-[10px] rounded-full bg-amber-100 text-amber-600 font-medium">
              {tipCategories.length}
            </span>
          )}
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 flex min-h-0">
        {activeTab === 'memories' ? (
          /* ========== Tab: 自动总结 (Memories) ========== */
          <>
            {/* Left panel: memory list */}
            <div className="w-80 flex-shrink-0 border-r border-surface-border flex flex-col bg-white">
              <div className="px-4 py-3 border-b border-surface-border">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                    <History className="w-4 h-4 text-primary-600" />
                    自动总结
                  </h2>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={handleAutoTag}
                      disabled={tagging}
                      className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-50 transition-colors"
                      title="使用 AI 自动为所有未打标记忆生成标签"
                    >
                      {tagging ? (
                        <RefreshCw className="w-3 h-3 animate-spin" />
                      ) : (
                        <Sparkles className="w-3 h-3" />
                      )}
                      {tagging
                        ? `${tagProgress?.done || 0}/${tagProgress?.total || '?'}`
                        : '一键打Tag'}
                    </button>
                    <button
                      onClick={loadMemories}
                      disabled={memLoading}
                      className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
                      title="刷新"
                    >
                      <RefreshCw className={`w-4 h-4 ${memLoading ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                </div>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="搜索经验..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-8 pr-3 py-1.5 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
                  />
                </div>
              </div>

              <div className="flex-1 overflow-y-auto">
                {memLoading ? (
                  <div className="flex items-center justify-center py-12 text-gray-400">
                    <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="text-center py-12 text-gray-400 text-sm">
                    {search ? '没有匹配的经验' : '暂无经验记录'}
                  </div>
                ) : (
                  Object.entries(grouped)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([category, items]) => (
                      <div key={category}>
                        <div className="px-4 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider bg-surface-50 border-b border-surface-border sticky top-0">
                          {category} ({items.length})
                        </div>
                        {items.map((m) => (
                          <div
                            key={m.id}
                            onClick={() => { setSelected(m); setEditing(false) }}
                            className={`group w-full text-left px-4 py-2.5 border-b border-surface-border transition-colors cursor-pointer ${
                              selected?.id === m.id
                                ? 'bg-primary-50 border-l-2 border-l-primary-500'
                                : 'hover:bg-surface-hover'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-sm text-gray-800 line-clamp-2">{m.content.slice(0, 80)}...</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleMemDelete(m.id) }}
                                className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-300 hover:text-red-500 transition-all flex-shrink-0"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                            {m.source && (
                              <p className="text-[10px] text-gray-400 mt-0.5">{m.source}</p>
                            )}
                            {m.tags && m.tags.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-0.5">
                                {m.tags.slice(0, 3).map(t => (
                                  <span key={t} className="inline-block px-1 py-0 text-[10px] rounded bg-amber-50 text-amber-600">
                                    {t}
                                  </span>
                                ))}
                                {m.tags.length > 3 && (
                                  <span className="text-[10px] text-gray-400">+{m.tags.length - 3}</span>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ))
                )}
              </div>

              {/* Embedding Management — pinned at bottom of left panel */}
              {embStats && (
                <div className="flex-shrink-0 border-t border-surface-border bg-surface-50 p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Cpu className="w-3.5 h-3.5 text-indigo-500" />
                    <span className="text-xs font-semibold text-gray-700">向量化</span>
                    {embStats.enabled ? (
                      <span className="ml-auto px-1.5 py-0.5 text-[10px] rounded-full bg-green-100 text-green-700 font-medium">已启用</span>
                    ) : (
                      <span className="ml-auto px-1.5 py-0.5 text-[10px] rounded-full bg-gray-100 text-gray-500 font-medium">未启用</span>
                    )}
                  </div>

                  {embStats.enabled ? (
                    <>
                      <div className="space-y-1 text-[11px] text-gray-600 mb-2">
                        <div className="flex justify-between">
                          <span>模型</span>
                          <span className="font-mono text-gray-800 truncate ml-2 max-w-[160px]" title={embStats.model}>{embStats.model || '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>进度</span>
                          <span className="font-mono text-gray-800">{embStats.embedded}/{embStats.total}</span>
                        </div>
                        {embStats.total > 0 && (
                          <div className="pt-0.5">
                            <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                                style={{ width: `${Math.round((embStats.embedded / embStats.total) * 100)}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {embStats.total - embStats.embedded > 0 ? (
                        <button
                          onClick={handleBackfill}
                          disabled={backfilling}
                          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 transition-colors"
                        >
                          {backfilling ? (
                            <>
                              <RefreshCw className="w-3 h-3 animate-spin" />
                              转换中...
                            </>
                          ) : (
                            <>
                              <Zap className="w-3 h-3" />
                              一键向量化 ({embStats.total - embStats.embedded} 条)
                            </>
                          )}
                        </button>
                      ) : embStats.total > 0 ? (
                        <div className="flex items-center justify-center gap-1 text-[11px] text-green-600 bg-green-50 rounded-lg py-1.5">
                          <CheckCircle2 className="w-3 h-3" />
                          全部已向量化
                        </div>
                      ) : null}

                      {backfillResult && (
                        <div className="mt-1.5 text-[11px] text-center text-indigo-600 bg-indigo-50 rounded-lg py-1">
                          成功转换 {backfillResult.updated} 条
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-[11px] text-gray-400 leading-relaxed">
                      在 config.yaml 中设置 <code className="px-0.5 py-0.5 bg-gray-100 rounded text-[10px]">embedding.enabled: true</code> 启用
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Right panel: memory detail */}
            <div className="flex-1 flex flex-col bg-white">
              {selected ? (
                <>
                  <div className="px-6 py-3 border-b border-surface-border flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="px-2 py-0.5 text-xs rounded-full bg-primary-100 text-primary-700">
                        {selected.category || 'general'}
                      </span>
                      <span className="text-xs text-gray-400">
                        {new Date(selected.created_at).toLocaleDateString()}
                      </span>
                      {selected.tags && selected.tags.length > 0 && (
                        <>
                          <Tag className="w-3 h-3 text-gray-400" />
                          {selected.tags.map(t => (
                            <span key={t} className="px-1.5 py-0.5 text-[10px] rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                              {t}
                            </span>
                          ))}
                        </>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {editing ? (
                        <>
                          <button
                            onClick={handleMemSave}
                            disabled={saving}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 text-white rounded-lg text-xs font-medium hover:bg-primary-700 disabled:opacity-50"
                          >
                            <Save className="w-3.5 h-3.5" />
                            {saving ? '保存中...' : '保存'}
                          </button>
                          <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700">
                            取消
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => { setEditing(true); setEditContent(selected.content) }}
                          className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => { setSelected(null); setEditing(false) }}
                        className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto p-6">
                    {editing ? (
                      <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        className="w-full h-full min-h-[400px] px-3 py-2 border border-surface-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
                      />
                    ) : (
                      <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
                        {selected.content}
                      </pre>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-gray-400">
                  <div className="text-center">
                    <History className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                    <p className="text-sm">选择一条经验查看详情</p>
                    <p className="text-xs mt-1 text-gray-300">
                      经验来自 AI 解题过程中的自动总结，三大模式通用
                    </p>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          /* ========== Tab: 经验提示 (Tips) ========== */
          <>
            {/* Left panel: tip category list */}
            <div className="w-72 flex-shrink-0 border-r border-surface-border flex flex-col bg-white">
              <div className="px-4 py-3 border-b border-surface-border">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                    <Lightbulb className="w-4 h-4 text-amber-500" />
                    经验提示
                  </h2>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setShowNewCategory(true)}
                      className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
                      title="新建分类"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                    <button
                      onClick={loadTips}
                      disabled={tipsLoading}
                      className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
                      title="刷新"
                    >
                      <RefreshCw className={`w-4 h-4 ${tipsLoading ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto py-1">
                {/* New category input */}
                {showNewCategory && (
                  <div className="px-4 py-2 flex items-center gap-1.5">
                    <input
                      type="text"
                      value={newCategoryName}
                      onChange={(e) => setNewCategoryName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleCreateCategory()
                        if (e.key === 'Escape') { setShowNewCategory(false); setNewCategoryName('') }
                      }}
                      placeholder="分类名称"
                      className="flex-1 text-xs px-2 py-1.5 border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
                      autoFocus
                    />
                    <button
                      onClick={handleCreateCategory}
                      className="text-xs px-2 py-1.5 rounded-lg bg-primary-50 text-primary-600 hover:bg-primary-100 transition-colors"
                    >
                      确定
                    </button>
                  </div>
                )}

                {tipsLoading ? (
                  <div className="flex items-center justify-center py-12 text-gray-400">
                    <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                  </div>
                ) : tipCategories.length === 0 && !showNewCategory ? (
                  <div className="text-center py-12 text-gray-400 text-sm">
                    暂无经验，解题后自动积累
                  </div>
                ) : (
                  tipCategories.map((tc) => {
                    const isSelected = selectedTipCat === tc.category
                    return (
                      <div key={tc.category} className="group relative">
                        <button
                          onClick={() => handleSelectTip(tc.category)}
                          className={`w-full text-left px-4 py-2.5 text-sm flex items-center gap-2 transition-colors ${
                            isSelected
                              ? 'bg-primary-50 text-primary-700 font-medium'
                              : 'text-gray-600 hover:bg-surface-hover'
                          }`}
                        >
                          <ChevronRight
                            className={`w-3 h-3 flex-shrink-0 transition-transform ${
                              isSelected ? 'rotate-90 text-primary-500' : 'text-gray-300'
                            }`}
                          />
                          <span className="flex-1 truncate">
                            {tipCategoryLabels[tc.category] || tc.category}
                          </span>
                          {tc.content && (
                            <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" title="有内容" />
                          )}
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteCategory(tc.category) }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                          title="删除分类"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    )
                  })
                )}
              </div>

              {/* Tip Embedding Management — pinned at bottom of left panel */}
              {tipEmbStats && (
                <div className="flex-shrink-0 border-t border-surface-border bg-surface-50 p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Cpu className="w-3.5 h-3.5 text-indigo-500" />
                    <span className="text-xs font-semibold text-gray-700">向量化</span>
                    {tipEmbStats.enabled ? (
                      <span className="ml-auto px-1.5 py-0.5 text-[10px] rounded-full bg-green-100 text-green-700 font-medium">已启用</span>
                    ) : (
                      <span className="ml-auto px-1.5 py-0.5 text-[10px] rounded-full bg-gray-100 text-gray-500 font-medium">未启用</span>
                    )}
                  </div>

                  {tipEmbStats.enabled ? (
                    <>
                      <div className="space-y-1 text-[11px] text-gray-600 mb-2">
                        <div className="flex justify-between">
                          <span>模型</span>
                          <span className="font-mono text-gray-800 truncate ml-2 max-w-[160px]" title={tipEmbStats.model}>{tipEmbStats.model || '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>进度</span>
                          <span className="font-mono text-gray-800">{tipEmbStats.embedded}/{tipEmbStats.total}</span>
                        </div>
                        {tipEmbStats.total > 0 && (
                          <div className="pt-0.5">
                            <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                                style={{ width: `${Math.round((tipEmbStats.embedded / tipEmbStats.total) * 100)}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {tipEmbStats.total - tipEmbStats.embedded > 0 ? (
                        <button
                          onClick={handleTipBackfill}
                          disabled={tipBackfilling}
                          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 transition-colors"
                        >
                          {tipBackfilling ? (
                            <>
                              <RefreshCw className="w-3 h-3 animate-spin" />
                              转换中...
                            </>
                          ) : (
                            <>
                              <Zap className="w-3 h-3" />
                              一键向量化 ({tipEmbStats.total - tipEmbStats.embedded} 条)
                            </>
                          )}
                        </button>
                      ) : tipEmbStats.total > 0 ? (
                        <div className="flex items-center justify-center gap-1 text-[11px] text-green-600 bg-green-50 rounded-lg py-1.5">
                          <CheckCircle2 className="w-3 h-3" />
                          全部已向量化
                        </div>
                      ) : null}

                      {tipBackfillResult && (
                        <div className="mt-1.5 text-[11px] text-center text-indigo-600 bg-indigo-50 rounded-lg py-1">
                          成功转换 {tipBackfillResult.updated} 条
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-[11px] text-gray-400 leading-relaxed">
                      在 config.yaml 中设置 <code className="px-0.5 py-0.5 bg-gray-100 rounded text-[10px]">embedding.enabled: true</code> 启用
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Right panel: tip editor */}
            <div className="flex-1 flex flex-col bg-white">
              {selectedTipCat ? (
                <>
                  {/* Header */}
                  <div className="flex items-center justify-between px-6 py-3 border-b border-surface-border">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900">
                        {tipCategoryLabels[selectedTipCat] || selectedTipCat}
                      </h3>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs text-gray-400 font-mono">tips:{selectedTipCat}</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">经验提示</span>
                        {tipDirty && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-500">未保存</span>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={handleTipSave}
                      disabled={tipSaving || !tipDirty}
                      className="btn-primary flex items-center gap-1.5 text-xs"
                    >
                      {tipSaving ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : tipSaved ? (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      ) : (
                        <Save className="w-3.5 h-3.5" />
                      )}
                      {tipSaved ? '已保存' : '保存'}
                    </button>
                  </div>

                  {/* Editor */}
                  <div className="flex-1 p-4 overflow-hidden">
                    <textarea
                      value={tipEditContent}
                      onChange={(e) => {
                        setTipEditContent(e.target.value)
                        setTipDirty(e.target.value !== tipOriginalContent)
                      }}
                      className="w-full h-full resize-none rounded-lg border border-surface-border bg-surface-50 p-4 text-sm font-mono text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                      spellCheck={false}
                    />
                  </div>

                  {/* Hint */}
                  <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                    此分类的经验会在解题时自动注入到系统提示词中（仅注入与当前题目相关的分类）。解题后新经验会自动追加。你也可以手动编辑。
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-gray-400">
                  <div className="text-center">
                    <Lightbulb className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                    <p className="text-sm">选择一个经验分类进行查看和编辑</p>
                    <p className="text-xs mt-1 text-gray-300">
                      经验提示按分类组织，解题时自动注入相关分类到系统提示词中
                    </p>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
