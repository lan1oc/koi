import { useEffect, useState, useCallback, useRef } from 'react'
import { Search, BookOpen, FolderOpen, Sparkles, Tag, RefreshCw, FileDown } from 'lucide-react'
import { knowledgeApi, tagsApi, type AutoTagProgress } from '../services/api'
import MarkdownRenderer from '../components/MarkdownRenderer'
import type { Writeup } from '../types'
import { useSettingsStore } from '../stores/settingsStore'
import { exportWriteupPDF } from '../utils/exportPdf'

export default function Knowledge() {
  const [writeups, setWriteups] = useState<Writeup[]>([])
  const [selected, setSelected] = useState<Writeup | null>(null)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [contentLoading, setContentLoading] = useState(false)
  const [tagging, setTagging] = useState(false)
  const [tagProgress, setTagProgress] = useState<AutoTagProgress | null>(null)

  useEffect(() => {
    loadWriteups()
  }, [])

  // Poll progress while tagging
  useEffect(() => {
    if (!tagging) return
    const interval = setInterval(async () => {
      try {
        const p = await tagsApi.progress('knowledge')
        setTagProgress(p)
        if (!p.running) {
          setTagging(false)
          loadWriteups()
        }
      } catch { /* ignore */ }
    }, 2000)
    return () => clearInterval(interval)
  }, [tagging])

  const loadWriteups = async () => {
    setLoading(true)
    try {
      const data = await knowledgeApi.list()
      setWriteups(data || [])
    } catch (e) {
      console.error('Failed to load writeups:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async () => {
    if (!search.trim()) {
      loadWriteups()
      return
    }
    setLoading(true)
    try {
      const data = await knowledgeApi.search(search)
      setWriteups(data || [])
    } catch (e) {
      console.error('Search failed:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleSelect = async (w: Writeup) => {
    setSelected(w)
    if (!w.content && w.id) {
      setContentLoading(true)
      try {
        const full = await knowledgeApi.get(w.id)
        setSelected(full)
      } catch (e) {
        console.error('Failed to load writeup content:', e)
      } finally {
        setContentLoading(false)
      }
    }
  }

  const handleAutoTag = useCallback(async () => {
    try {
      const { utilityModel, selectedModel } = useSettingsStore.getState()
      const effectiveModel = utilityModel || selectedModel || undefined
      setTagging(true)
      setTagProgress({ total: 0, done: 0, failed: 0, running: true, message: '启动中...' })
      await tagsApi.autoTagKnowledge(true, effectiveModel)
    } catch (e) {
      console.error('Auto-tag failed:', e)
      setTagging(false)
    }
  }, [])

  const contentRef = useRef<HTMLDivElement>(null)
  const exportPDF = () => {
    if (!contentRef.current || !selected) return
    exportWriteupPDF(contentRef.current, selected.title)
  }

  // Group by category
  const grouped = writeups.reduce((acc, w) => {
    const cat = w.category || 'uncategorized'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(w)
    return acc
  }, {} as Record<string, Writeup[]>)

  const taggedCount = writeups.filter(w => w.tags && w.tags.length > 0).length

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-80 border-r border-surface-border flex flex-col bg-white">
        <div className="px-4 py-3 border-b border-surface-border space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-gray-900 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-primary-500" />
              知识库
            </h2>
            <div className="flex items-center gap-1">
              <button
                onClick={handleAutoTag}
                disabled={tagging}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-50 transition-colors"
                title="使用 AI 自动为所有未打标文章生成标签"
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
                onClick={loadWriteups}
                disabled={loading}
                className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
                title="刷新"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>
          {taggedCount > 0 && (
            <div className="text-[10px] text-gray-400">
              已标注 {taggedCount}/{writeups.length} 篇
            </div>
          )}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="搜索文章..."
                className="input-field w-full pl-9"
              />
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-4">
          {loading ? (
            <div className="text-center text-gray-500 py-8 text-sm">加载中...</div>
          ) : Object.keys(grouped).length === 0 ? (
            <div className="text-center text-gray-500 py-8 text-sm">未找到文章</div>
          ) : (
            Object.entries(grouped).map(([category, items]) => (
              <div key={category} className="mb-3">
                <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-gray-500 uppercase tracking-wider font-semibold">
                  <FolderOpen className="w-3.5 h-3.5" />
                  {category}
                  <span className="text-gray-400">({items.length})</span>
                </div>
                {items.map((w) => (
                  <button
                    key={w.id || `${category}-${w.title}`}
                    onClick={() => handleSelect(w)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                      selected?.id === w.id
                        ? 'bg-primary-50 text-primary-700'
                        : 'text-gray-600 hover:bg-surface-hover'
                    }`}
                  >
                    <span className="block truncate">{w.title}</span>
                    {w.tags && w.tags.length > 0 && (
                      <span className="flex flex-wrap gap-1 mt-0.5">
                        {w.tags.slice(0, 4).map(t => (
                          <span key={t} className="inline-block px-1 py-0 text-[10px] rounded bg-primary-50 text-primary-600">
                            {t}
                          </span>
                        ))}
                        {w.tags.length > 4 && (
                          <span className="text-[10px] text-gray-400">+{w.tags.length - 4}</span>
                        )}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {selected ? (
          <div className="p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <h1 className="text-2xl font-bold text-gray-900">{selected.title}</h1>
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-500 flex-wrap">
                  <span className="badge-misc">{selected.category}</span>
                  {selected.created_at && (
                    <span>{new Date(selected.created_at).toLocaleDateString()}</span>
                  )}
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
              </div>
              <button
                onClick={exportPDF}
                className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-surface-100 hover:bg-surface-200 text-gray-600 transition-colors"
                title="导出为 PDF"
              >
                <FileDown className="w-3.5 h-3.5" />
                导出 PDF
              </button>
            </div>
            {contentLoading ? (
              <div className="text-center text-gray-500 py-8 text-sm">加载内容中...</div>
            ) : (
              <div ref={contentRef}>
                <MarkdownRenderer content={selected.content} />
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-600">
            <div className="text-center">
              <BookOpen className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">选择一篇文章查看</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
