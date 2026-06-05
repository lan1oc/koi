import { useState, useEffect, useCallback } from 'react'
import { tagsApi, type TagStats, type AutoTagProgress, type TipItem } from '../services/api'
import { Tag, Sparkles, RefreshCw, Search, BarChart3, BookOpen, History, Brain, Filter } from 'lucide-react'
import { useSettingsStore } from '../stores/settingsStore'

const sourceLabels: Record<string, { label: string; color: string }> = {
  knowledge: { label: '知识库', color: 'bg-blue-100 text-blue-700' },
  tips: { label: '经验项', color: 'bg-green-100 text-green-700' },
  memories: { label: '记忆库', color: 'bg-purple-100 text-purple-700' },
}


export default function TagManager() {
  const [stats, setStats] = useState<TagStats | null>(null)
  const [allTags, setAllTags] = useState<Record<string, { count: number; sources: string[] }>>({})
  const [tipItems, setTipItems] = useState<TipItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<'overview' | 'tips' | 'tags'>('overview')
  const [tagProgress, setTagProgress] = useState<Record<string, AutoTagProgress>>({})
  const [tagging, setTagging] = useState<Record<string, boolean>>({})
  const [filterSource, setFilterSource] = useState<string>('')

  // 页面挂载时自动恢复所有进度
  useEffect(() => {
    (async () => {
      const targets: ('knowledge' | 'tips' | 'memories')[] = ['knowledge', 'tips', 'memories']
      const progress: Record<string, AutoTagProgress> = {}
      const taggingState: Record<string, boolean> = {}
      await Promise.all(targets.map(async (target) => {
        try {
          const p = await tagsApi.progress(target)
          progress[target] = p
          if (p.running) taggingState[target] = true
        } catch {}
      }))
      setTagProgress(progress)
      setTagging(taggingState)
    })()
  }, [])

  useEffect(() => { loadAll() }, [])

  // Poll progress for active tagging jobs
  useEffect(() => {
    const activeTargets = Object.entries(tagging).filter(([, v]) => v).map(([k]) => k)
    if (activeTargets.length === 0) return
    const interval = setInterval(async () => {
      for (const target of activeTargets) {
        try {
          const p = await tagsApi.progress(target as 'knowledge' | 'tips' | 'memories')
          setTagProgress(prev => ({ ...prev, [target]: p }))
          if (!p.running) {
            setTagging(prev => ({ ...prev, [target]: false }))
            loadAll()
          }
        } catch { /* ignore */ }
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [tagging])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [s, t] = await Promise.all([
        tagsApi.stats(),
        tagsApi.listAll(),
      ])
      setStats(s)
      setAllTags(t || {})
    } catch (e) {
      console.error('Failed to load tag data:', e)
    } finally {
      setLoading(false)
    }
  }

  const loadTipItems = useCallback(async () => {
    try {
      const items = await tagsApi.listTipItems()
      setTipItems(items || [])
    } catch (e) {
      console.error('Failed to load tip items:', e)
    }
  }, [])

  useEffect(() => {
    if (tab === 'tips') loadTipItems()
  }, [tab, loadTipItems])

  const handleAutoTag = async (target: 'knowledge' | 'tips' | 'memories', forceAll = false) => {
    try {
      const { utilityModel, selectedModel } = useSettingsStore.getState()
      const effectiveModel = utilityModel || selectedModel || undefined
      setTagging(prev => ({ ...prev, [target]: true }))
      setTagProgress(prev => ({ ...prev, [target]: { total: 0, done: 0, failed: 0, running: true, message: forceAll ? '重打标签...' : '启动中...' } }))
      const onlyUntagged = !forceAll
      switch (target) {
        case 'knowledge': await tagsApi.autoTagKnowledge(onlyUntagged, effectiveModel); break
        case 'tips': await tagsApi.autoTagTips(onlyUntagged, effectiveModel); break
        case 'memories': await tagsApi.autoTagMemories(onlyUntagged, effectiveModel); break
      }
    } catch (e) {
      console.error(`Auto-tag ${target} failed:`, e)
      setTagging(prev => ({ ...prev, [target]: false }))
    }
  }

  const handleAutoTagAll = async (forceAll = false) => {
    await Promise.all([
      handleAutoTag('knowledge', forceAll),
      handleAutoTag('tips', forceAll),
      handleAutoTag('memories', forceAll),
    ])
  }

  // Sort tags by count descending
  const sortedTags = Object.entries(allTags)
    .filter(([tag]) => !search || tag.toLowerCase().includes(search.toLowerCase()))
    .filter(([, info]) => !filterSource || info.sources.includes(filterSource))
    .sort((a, b) => b[1].count - a[1].count)

  const filteredTipItems = tipItems.filter(
    it => !search || it.content.toLowerCase().includes(search.toLowerCase()) || it.tags.some(t => t.includes(search))
  )

  const renderProgressBadge = (target: string) => {
    const p = tagProgress[target]
    const active = tagging[target]
    if (!active || !p) return null
    return (
      <span className="ml-2 text-[10px] text-amber-600 animate-pulse">
        {p.done}/{p.total} {p.failed > 0 && `(失败${p.failed})`}
      </span>
    )
  }

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="px-6 py-4 border-b border-surface-border">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <Tag className="w-5 h-5 text-amber-600" />
            标签管理
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleAutoTagAll(false)}
              disabled={Object.values(tagging).some(Boolean)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 text-white rounded-lg text-xs font-medium hover:bg-amber-600 disabled:opacity-50 transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5" />
              全部打Tag
            </button>
            <button
              onClick={() => handleAutoTagAll(true)}
              disabled={Object.values(tagging).some(Boolean)}
              title="强制重打所有已有标签的条目"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-500 text-white rounded-lg text-xs font-medium hover:bg-orange-600 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              全部重打Tag
            </button>
            <button
              onClick={loadAll}
              disabled={loading}
              className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Tab */}
        <div className="flex gap-1 mt-3">
          {([
            { key: 'overview', label: '总览', icon: BarChart3 },
            { key: 'tags', label: '标签列表', icon: Tag },
            { key: 'tips', label: '经验项', icon: Brain },
          ] as const).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                tab === key
                  ? 'bg-primary-100 text-primary-700 font-medium'
                  : 'text-gray-500 hover:bg-surface-hover'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-gray-400">
            <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : tab === 'overview' ? (
          /* ── Overview ── */
          <div className="max-w-3xl mx-auto space-y-6">
            {/* Stats cards */}
            <div className="grid grid-cols-3 gap-4">
              {([
                { key: 'knowledge', label: '知识库', icon: BookOpen, color: 'blue' },
                { key: 'tips', label: '经验项', icon: Brain, color: 'green' },
                { key: 'memories', label: '记忆库', icon: History, color: 'purple' },
              ] as const).map(({ key, label, icon: Icon, color }) => {
                const s = stats?.[key]
                const pct = s && s.total > 0 ? Math.round(s.tagged / s.total * 100) : 0
                return (
                  <div key={key} className="panel p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Icon className={`w-4 h-4 text-${color}-600`} />
                        <span className="text-sm font-medium text-gray-700">{label}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleAutoTag(key, false)}
                          disabled={!!tagging[key]}
                          title="仅打未标注的条目"
                          className={`flex items-center gap-1 px-2 py-1 text-[10px] rounded-lg bg-${color}-50 text-${color}-700 hover:bg-${color}-100 disabled:opacity-50 transition-colors`}
                        >
                          {tagging[key] ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : (
                            <Sparkles className="w-3 h-3" />
                          )}
                          打Tag
                        </button>
                        <button
                          onClick={() => handleAutoTag(key, true)}
                          disabled={!!tagging[key]}
                          title="强制重打所有条目标签"
                          className="flex items-center gap-1 px-2 py-1 text-[10px] rounded-lg bg-orange-50 text-orange-600 hover:bg-orange-100 disabled:opacity-50 transition-colors"
                        >
                          <RefreshCw className="w-3 h-3" />
                          重打
                        </button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-gray-500">
                        <span>已标注 / 总计</span>
                        <span className="font-mono">{s?.tagged || 0} / {s?.total || 0}</span>
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full bg-${color}-500 rounded-full transition-all duration-500`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-[10px] text-gray-400">
                        <span>{pct}%</span>
                        <span>{s?.unique_tags || 0} 种标签</span>
                      </div>
                    </div>
                    {renderProgressBadge(key)}
                  </div>
                )
              })}
            </div>

            {/* Top tags */}
            <div className="panel p-4">
              <h3 className="text-sm font-medium text-gray-700 mb-3">热门标签 Top 30</h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(allTags)
                  .sort((a, b) => b[1].count - a[1].count)
                  .slice(0, 30)
                  .map(([tag, info]) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-full bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 cursor-default"
                    >
                      {tag}
                      <span className="text-[10px] text-amber-500">×{info.count}</span>
                    </span>
                  ))}
                {Object.keys(allTags).length === 0 && (
                  <span className="text-xs text-gray-400">暂无标签数据，点击"全部一键打Tag"开始</span>
                )}
              </div>
            </div>
          </div>
        ) : tab === 'tags' ? (
          /* ── Tags List ── */
          <div className="max-w-4xl mx-auto">
            <div className="flex items-center gap-3 mb-4">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索标签..."
                  className="w-full pl-9 pr-3 py-1.5 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>
              <div className="flex items-center gap-1">
                <Filter className="w-3.5 h-3.5 text-gray-400" />
                <button
                  onClick={() => setFilterSource('')}
                  className={`px-2 py-0.5 text-xs rounded-full ${!filterSource ? 'bg-primary-100 text-primary-700' : 'bg-surface-100 text-gray-500 hover:bg-surface-200'}`}
                >
                  全部
                </button>
                {Object.entries(sourceLabels).map(([key, { label, color }]) => (
                  <button
                    key={key}
                    onClick={() => setFilterSource(filterSource === key ? '' : key)}
                    className={`px-2 py-0.5 text-xs rounded-full ${filterSource === key ? color + ' font-medium' : 'bg-surface-100 text-gray-500 hover:bg-surface-200'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span className="text-xs text-gray-400">{sortedTags.length} 个标签</span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
              {sortedTags.map(([tag, info]) => (
                <div
                  key={tag}
                  className="flex items-center justify-between px-3 py-2 rounded-lg border border-surface-border hover:border-amber-300 hover:bg-amber-50/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Tag className="w-3 h-3 text-amber-500" />
                    <span className="text-sm font-medium text-gray-700">{tag}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono text-gray-400">×{info.count}</span>
                    {info.sources.map(s => (
                      <span key={s} className={`px-1 py-0 text-[9px] rounded ${sourceLabels[s]?.color || 'bg-gray-100 text-gray-500'}`}>
                        {sourceLabels[s]?.label?.charAt(0) || s}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {sortedTags.length === 0 && (
                <div className="col-span-full text-center py-12 text-gray-400 text-sm">
                  {search ? '未找到匹配标签' : '暂无标签数据'}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* ── Tip Items ── */
          <div className="max-w-4xl mx-auto">
            <div className="flex items-center gap-3 mb-4">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索经验项..."
                  className="w-full pl-9 pr-3 py-1.5 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>
              <span className="text-xs text-gray-400">
                {filteredTipItems.length} 条经验项 / {tipItems.filter(t => t.tags.length > 0).length} 已打标
              </span>
            </div>

            <div className="space-y-1">
              {filteredTipItems.map((item) => (
                <div
                  key={item.id}
                  className="flex items-start gap-3 px-3 py-2 rounded-lg border border-surface-border hover:border-primary-200 hover:bg-primary-50/30 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-gray-700 line-clamp-2">{item.content}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-gray-400 px-1.5 py-0.5 bg-surface-100 rounded">{item.category}</span>
                      {item.source && (
                        <span className="text-[10px] text-gray-400">{item.source}</span>
                      )}
                      <span className="text-[10px] text-gray-400">命中 {item.hit_count}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1 flex-shrink-0 max-w-[200px] justify-end">
                    {item.tags.length > 0 ? (
                      item.tags.map(t => (
                        <span key={t} className="px-1.5 py-0.5 text-[10px] rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                          {t}
                        </span>
                      ))
                    ) : (
                      <span className="text-[10px] text-gray-300 italic">未打标</span>
                    )}
                  </div>
                </div>
              ))}
              {filteredTipItems.length === 0 && (
                <div className="text-center py-12 text-gray-400 text-sm">
                  {search ? '未找到匹配经验项' : '暂无经验项数据'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
