import { useState, useEffect } from 'react'
import { BookOpen, Brain, Search } from 'lucide-react'
import { skillApi, knowledgeApi } from '../../services/api'
import type { Skill, Writeup } from '../../types'

type Tab = 'skills' | 'writeups'

export default function ReverseKnowledge() {
  const [tab, setTab] = useState<Tab>('skills')
  const [skills, setSkills] = useState<Skill[]>([])
  const [writeups, setWriteups] = useState<Writeup[]>([])
  const [selectedContent, setSelectedContent] = useState<string>('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    skillApi.list().then((all) => {
      setSkills(all.filter((s) => s.category === 'reverse' || s.category === '逆向'))
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab === 'writeups') {
      setLoading(true)
      knowledgeApi.list('reverse').then(setWriteups).catch(() => {}).finally(() => setLoading(false))
    }
  }, [tab])

  const handleSearch = async () => {
    if (!search.trim()) return
    setLoading(true)
    try {
      const results = await knowledgeApi.search(search)
      setWriteups(results)
      setTab('writeups')
    } catch { /* ignore */ }
    setLoading(false)
  }

  const loadSkillContent = async (name: string) => {
    try {
      const { content } = await skillApi.content(name)
      setSelectedContent(content)
    } catch {
      setSelectedContent('加载失败')
    }
  }

  const loadWriteupContent = async (id: string) => {
    try {
      const w = await knowledgeApi.get(id)
      setSelectedContent(w.content || '')
    } catch {
      setSelectedContent('加载失败')
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="relative mb-3">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="搜索逆向知识..."
          className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
            text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-3">
        <button
          onClick={() => { setTab('skills'); setSelectedContent('') }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs transition-colors ${
            tab === 'skills' ? 'bg-purple-50 text-purple-600 border border-purple-200' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          }`}
        >
          <Brain className="w-3 h-3" />
          技能文档
        </button>
        <button
          onClick={() => { setTab('writeups'); setSelectedContent('') }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs transition-colors ${
            tab === 'writeups' ? 'bg-purple-50 text-purple-600 border border-purple-200' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          }`}
        >
          <BookOpen className="w-3 h-3" />
          Writeup
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {selectedContent ? (
          <div className="space-y-2">
            <button
              onClick={() => setSelectedContent('')}
              className="text-xs text-purple-500 hover:text-purple-600 transition-colors"
            >
              ← 返回列表
            </button>
            <div className="prose prose-sm max-w-none">
              <pre className="text-xs whitespace-pre-wrap text-gray-700 bg-gray-50 p-3 rounded-xl border border-gray-200">
                {selectedContent}
              </pre>
            </div>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-24">
            <div className="animate-spin rounded-full h-5 w-5 border-2 border-purple-500 border-t-transparent" />
          </div>
        ) : tab === 'skills' ? (
          <div className="space-y-1.5">
            {skills.length === 0 && (
              <p className="text-xs text-gray-500 text-center py-8">暂无逆向技能文档</p>
            )}
            {skills.map((s) => (
              <button
                key={s.name}
                onClick={() => loadSkillContent(s.name)}
                className="w-full text-left p-2.5 rounded-xl bg-white border border-gray-200
                  hover:border-purple-200 hover:bg-purple-50/50 transition-colors shadow-sm"
              >
                <p className="text-sm text-gray-800 font-medium">{s.name}</p>
                {s.description && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{s.description}</p>}
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            {writeups.length === 0 && (
              <p className="text-xs text-gray-500 text-center py-8">暂无逆向 Writeup</p>
            )}
            {writeups.map((w) => (
              <button
                key={w.id}
                onClick={() => loadWriteupContent(w.id)}
                className="w-full text-left p-2.5 rounded-xl bg-white border border-gray-200
                  hover:border-purple-200 hover:bg-purple-50/50 transition-colors shadow-sm"
              >
                <p className="text-sm text-gray-800 font-medium">{w.title}</p>
                {w.tags && w.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {w.tags.slice(0, 5).map((t) => (
                      <span key={t} className="px-1.5 py-0.5 text-[10px] bg-gray-100 text-gray-500 rounded-md border border-gray-200">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
