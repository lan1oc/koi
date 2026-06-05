import { useState, useEffect, useCallback } from 'react'
import { skillApi, tagsApi, type AutoTagProgress } from '../services/api'
import { Skill } from '../types'
import { BookOpen, RefreshCw, ChevronRight, Search, Tag, Wrench, X, ArrowDownToLine, Plus, Pencil, Trash2, Sparkles, Save } from 'lucide-react'
import { useSettingsStore } from '../stores/settingsStore'

const categoryColors: Record<string, string> = {
  web: 'bg-blue-100 text-blue-700',
  pwn: 'bg-red-100 text-red-700',
  reverse: 'bg-purple-100 text-purple-700',
  crypto: 'bg-green-100 text-green-700',
  misc: 'bg-yellow-100 text-yellow-700',
  forensics: 'bg-orange-100 text-orange-700',
  audit: 'bg-amber-100 text-amber-700',
  pentest: 'bg-rose-100 text-rose-700',
}

const SKILL_TEMPLATE = `---
name: 
description: 
category: web
tools_required: []
---

# Skill Title

## Overview


## Techniques


## Payloads / Examples

\`\`\`
\`\`\`

## Tools

`

export default function Skills() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [reloading, setReloading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<{ synced: number; skipped: number } | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState({ category: 'web', file_name: '', content: SKILL_TEMPLATE })
  const [saving, setSaving] = useState(false)
  const [tipTagging, setTipTagging] = useState(false)
  const [tipTagProgress, setTipTagProgress] = useState<AutoTagProgress | null>(null)

  useEffect(() => {
    loadSkills()
  }, [])

  // Poll tips auto-tag progress
  useEffect(() => {
    if (!tipTagging) return
    const interval = setInterval(async () => {
      try {
        const p = await tagsApi.progress('tips')
        setTipTagProgress(p)
        if (!p.running) {
          setTipTagging(false)
        }
      } catch { /* ignore */ }
    }, 2000)
    return () => clearInterval(interval)
  }, [tipTagging])

  const loadSkills = async () => {
    setLoading(true)
    try {
      const data = await skillApi.list()
      setSkills(data || [])
    } catch (e) {
      console.error('Failed to load skills:', e)
    } finally {
      setLoading(false)
    }
  }

  const loadContent = async (name: string) => {
    setSelectedSkill(name)
    setContentLoading(true)
    try {
      const data = await skillApi.content(name)
      setContent(data.content || '')
    } catch (e) {
      setContent(`Failed to load content for "${name}"`)
    } finally {
      setContentLoading(false)
    }
  }

  const handleReload = async () => {
    setReloading(true)
    try {
      await skillApi.reload()
      await loadSkills()
    } catch (e) {
      console.error('Failed to reload skills:', e)
    } finally {
      setReloading(false)
    }
  }

  const handleSyncFromTips = async () => {
    setSyncing(true)
    setSyncResult(null)
    try {
      const result = await skillApi.syncFromTips()
      setSyncResult({ synced: result.synced, skipped: result.skipped })
      await loadSkills()
      setTimeout(() => setSyncResult(null), 5000)
    } catch (e) {
      console.error('Failed to sync tips to skills:', e)
    } finally {
      setSyncing(false)
    }
  }

  const handleAutoTagTips = useCallback(async () => {
    try {
      const { utilityModel, selectedModel } = useSettingsStore.getState()
      const effectiveModel = utilityModel || selectedModel || undefined
      setTipTagging(true)
      setTipTagProgress({ total: 0, done: 0, failed: 0, running: true, message: '启动中...' })
      await tagsApi.autoTagTips(true, effectiveModel)
    } catch (e) {
      console.error('Auto-tag tips failed:', e)
      setTipTagging(false)
    }
  }, [])

  const handleEdit = () => {
    setEditMode(true)
    setEditContent(content)
  }

  const handleSaveEdit = async () => {
    if (!selectedSkill || !editContent) return
    setSaving(true)
    try {
      await skillApi.update(selectedSkill, editContent)
      setContent(editContent)
      setEditMode(false)
      await loadSkills()
    } catch (e) {
      console.error('Failed to update skill:', e)
    } finally {
      setSaving(false)
    }
  }

  const handleCreate = async () => {
    if (!createForm.file_name || !createForm.content) return
    setSaving(true)
    try {
      const meta = await skillApi.create(createForm)
      setCreating(false)
      setCreateForm({ category: 'web', file_name: '', content: SKILL_TEMPLATE })
      await loadSkills()
      if (meta.name) loadContent(meta.name)
    } catch (e) {
      console.error('Failed to create skill:', e)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`确定要删除技能「${name}」吗？此操作不可撤销。`)) return
    try {
      await skillApi.delete(name)
      if (selectedSkill === name) {
        setSelectedSkill(null)
        setContent('')
        setEditMode(false)
      }
      await loadSkills()
    } catch (e) {
      console.error('Failed to delete skill:', e)
    }
  }

  const categories = [...new Set(skills.map((s) => s.category))].sort()

  const filtered = skills.filter((s) => {
    const matchSearch =
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.description?.toLowerCase().includes(search.toLowerCase())
    const matchCategory = !filterCategory || s.category === filterCategory
    return matchSearch && matchCategory
  })

  const grouped = filtered.reduce<Record<string, Skill[]>>((acc, s) => {
    const cat = s.category || 'misc'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(s)
    return acc
  }, {})

  return (
    <div className="flex h-full">
      {/* Left panel: skill list */}
      <div className="w-80 flex-shrink-0 border-r border-surface-border flex flex-col bg-white">
        {/* Header */}
        <div className="px-4 py-3 border-b border-surface-border">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-sm font-bold text-gray-900 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-primary-600" />
              技能库
            </h1>
            <div className="flex items-center gap-1">
              <button
                onClick={handleAutoTagTips}
                disabled={tipTagging}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-50 transition-colors"
                title="使用 AI 自动为所有未打标经验项生成标签"
              >
                {tipTagging ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <Sparkles className="w-3 h-3" />
                )}
                {tipTagging
                  ? `${tipTagProgress?.done || 0}/${tipTagProgress?.total || '?'}`
                  : '一键打Tag'}
              </button>
              <button
                onClick={() => { setCreating(true); setSelectedSkill(null); setEditMode(false) }}
                className="p-1.5 rounded-lg hover:bg-green-50 text-gray-400 hover:text-green-600 transition-colors"
                title="新建技能"
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                onClick={handleSyncFromTips}
                disabled={syncing}
                className="p-1.5 rounded-lg hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition-colors"
                title="从经验库同步到技能文件"
              >
                <ArrowDownToLine className={`w-4 h-4 ${syncing ? 'animate-bounce' : ''}`} />
              </button>
              <button
                onClick={handleReload}
                disabled={reloading}
                className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600 transition-colors"
                title="重新加载技能文件"
              >
                <RefreshCw className={`w-4 h-4 ${reloading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {syncResult && (
            <div className="mb-2 text-xs text-green-600 bg-green-50 rounded-lg px-3 py-1.5">
              已同步 {syncResult.synced} 个分类，跳过 {syncResult.skipped} 个
            </div>
          )}

          {/* Search */}
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="搜索技能..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-surface-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>

          {/* Category filter */}
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setFilterCategory('')}
              className={`px-2 py-0.5 text-xs rounded-full transition-colors ${
                !filterCategory
                  ? 'bg-primary-100 text-primary-700 font-medium'
                  : 'bg-surface-100 text-gray-500 hover:bg-surface-200'
              }`}
            >
              全部 ({skills.length})
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setFilterCategory(filterCategory === cat ? '' : cat)}
                className={`px-2 py-0.5 text-xs rounded-full transition-colors ${
                  filterCategory === cat
                    ? (categoryColors[cat] || 'bg-gray-100 text-gray-700') + ' font-medium'
                    : 'bg-surface-100 text-gray-500 hover:bg-surface-200'
                }`}
              >
                {cat} ({skills.filter((s) => s.category === cat).length})
              </button>
            ))}
          </div>
        </div>

        {/* Skill list */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-gray-400">
              <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-gray-400 text-sm">
              {search ? '没有匹配的技能' : '暂无技能文件'}
            </div>
          ) : (
            Object.entries(grouped)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([category, catSkills]) => (
                <div key={category}>
                  <div className="px-4 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider bg-surface-50 border-b border-surface-border sticky top-0">
                    {category} ({catSkills.length})
                  </div>
                  {catSkills.map((sk) => (
                    <div
                      key={sk.name}
                      onClick={() => { loadContent(sk.name); setCreating(false); setEditMode(false) }}
                      className={`group w-full text-left px-4 py-2.5 border-b border-surface-border transition-colors cursor-pointer ${
                        selectedSkill === sk.name
                          ? 'bg-primary-50 border-l-2 border-l-primary-500'
                          : 'hover:bg-surface-hover'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-gray-800 truncate">{sk.name}</span>
                        <div className="flex items-center gap-0.5">
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDelete(sk.name) }}
                            className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-300 hover:text-red-500 transition-all"
                            title="删除"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                          <ChevronRight className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" />
                        </div>
                      </div>
                      {sk.description && (
                        <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{sk.description}</p>
                      )}
                      {sk.tools_required && sk.tools_required.length > 0 && (
                        <div className="flex items-center gap-1 mt-1">
                          <Wrench className="w-3 h-3 text-gray-300" />
                          <span className="text-[10px] text-gray-400 truncate">
                            {sk.tools_required.join(', ')}
                          </span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))
          )}
        </div>
      </div>

      {/* Right panel: skill content / create / edit */}
      <div className="flex-1 flex flex-col bg-white">
        {creating ? (
          <>
            {/* Create mode */}
            <div className="px-6 py-3 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Sparkles className="w-5 h-5 text-green-600" />
                <h2 className="text-lg font-semibold text-gray-900">新建技能</h2>
              </div>
              <button onClick={() => setCreating(false)} className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-3xl space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">文件名 *</label>
                    <input
                      type="text"
                      value={createForm.file_name}
                      onChange={(e) => setCreateForm({ ...createForm, file_name: e.target.value })}
                      className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                      placeholder="例如: jwt-attacks"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">分类</label>
                    <select
                      value={createForm.category}
                      onChange={(e) => setCreateForm({ ...createForm, category: e.target.value })}
                      className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                    >
                      {['web', 'pwn', 'reverse', 'crypto', 'misc', 'forensics', 'audit', 'pentest'].map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">内容 (Markdown + YAML frontmatter)</label>
                  <textarea
                    value={createForm.content}
                    onChange={(e) => setCreateForm({ ...createForm, content: e.target.value })}
                    rows={24}
                    className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
                  />
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleCreate}
                    disabled={saving || !createForm.file_name || !createForm.content}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? '保存中...' : '创建技能'}
                  </button>
                  <button onClick={() => setCreating(false)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
                    取消
                  </button>
                </div>
                <p className="text-xs text-gray-400">
                  <Sparkles className="w-3 h-3 inline mr-1" />
                  提示：AI 在解题过程中也会自动创建和迭代技能（通过 create_skill / update_skill 工具）
                </p>
              </div>
            </div>
          </>
        ) : selectedSkill ? (
          <>
            {/* View / Edit mode */}
            <div className="px-6 py-3 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold text-gray-900">{selectedSkill}</h2>
                {skills.find((s) => s.name === selectedSkill)?.category && (
                  <span
                    className={`px-2 py-0.5 text-xs rounded-full ${
                      categoryColors[skills.find((s) => s.name === selectedSkill)!.category] ||
                      'bg-gray-100 text-gray-600'
                    }`}
                  >
                    {skills.find((s) => s.name === selectedSkill)!.category}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                {editMode ? (
                  <>
                    <button
                      onClick={handleSaveEdit}
                      disabled={saving}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 text-white rounded-lg text-xs font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                    >
                      <Save className="w-3.5 h-3.5" />
                      {saving ? '保存中...' : '保存'}
                    </button>
                    <button
                      onClick={() => setEditMode(false)}
                      className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700"
                    >
                      取消
                    </button>
                  </>
                ) : (
                  <button
                    onClick={handleEdit}
                    className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400 hover:text-gray-600"
                    title="编辑"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={() => { setSelectedSkill(null); setContent(''); setEditMode(false) }}
                  className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-400"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              {contentLoading ? (
                <div className="flex items-center justify-center py-12 text-gray-400">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载内容...
                </div>
              ) : editMode ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-full min-h-[500px] px-3 py-2 border border-surface-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
                />
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
                  {content}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <BookOpen className="w-12 h-12 mx-auto mb-3 text-gray-300" />
              <p className="text-sm">选择一个技能查看详细内容</p>
              <p className="text-xs mt-1 text-gray-300">
                技能文件包含解题策略、攻击载荷和工具使用示例
              </p>
              <p className="text-xs mt-3 text-gray-300">
                <Sparkles className="w-3 h-3 inline mr-1" />
                AI 会在解题后自动创建和改进技能
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
