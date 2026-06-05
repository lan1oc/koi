import { useEffect, useState } from 'react'
import {
  FileText,
  Save,
  RotateCcw,
  Loader2,
  Check,
  Shield,
  User,
  Zap,
  FileCode,
  ChevronRight,
  BookOpen,
} from 'lucide-react'
import { promptApi } from '../services/api'
import type { PromptEntry } from '../types'

// Prompt categories and labels
const promptGroups: { label: string; icon: React.ReactNode; ids: string[] }[] = [
  {
    label: '角色身份',
    icon: <User className="w-4 h-4" />,
    ids: [
      'identity:coordinator',
      'identity:parser',
      'identity:web',
      'identity:pwn',
      'identity:reverse',
      'identity:crypto',
      'identity:misc',
    ],
  },
  {
    label: '代码审计 · 身份',
    icon: <User className="w-4 h-4" />,
    ids: [
      'identity:audit_coordinator',
      'identity:sast',
      'identity:dependency',
      'identity:config_review',
      'identity:logic',
    ],
  },
  {
    label: '黑盒渗透 · 身份',
    icon: <User className="w-4 h-4" />,
    ids: [
      'identity:pentest_coordinator',
      'identity:recon',
      'identity:vuln_scan',
      'identity:exploit',
      'identity:post_exploit',
    ],
  },
  {
    label: '安全规则',
    icon: <Shield className="w-4 h-4" />,
    ids: ['safety'],
  },
  {
    label: '解题协议',
    icon: <Zap className="w-4 h-4" />,
    ids: ['protocol:default', 'protocol:coordinator', 'protocol:parser'],
  },
  {
    label: '代码审计 · 协议',
    icon: <Zap className="w-4 h-4" />,
    ids: [
      'protocol:audit_coordinator',
      'protocol:sast',
      'protocol:dependency',
      'protocol:config_review',
      'protocol:logic',
    ],
  },
  {
    label: '黑盒渗透 · 协议',
    icon: <Zap className="w-4 h-4" />,
    ids: [
      'protocol:pentest_coordinator',
      'protocol:recon',
      'protocol:vuln_scan',
      'protocol:exploit',
      'protocol:post_exploit',
    ],
  },
  {
    label: '后处理',
    icon: <BookOpen className="w-4 h-4" />,
    ids: ['writeup', 'flag_review', 'compaction', 'lessons', 'auto_tag'],
  },
  {
    label: '模板',
    icon: <FileCode className="w-4 h-4" />,
    ids: ['parser_user'],
  },
]

const promptLabels: Record<string, string> = {
  'identity:coordinator': '协调器',
  'identity:parser': '解析器',
  'identity:web': 'Web 专家',
  'identity:pwn': 'Pwn 专家',
  'identity:reverse': '逆向专家',
  'identity:crypto': '密码学专家',
  'identity:misc': '综合专家',
  // Audit mode identities
  'identity:audit_coordinator': '代码审计协调器',
  'identity:sast': '静态分析专家',
  'identity:dependency': '依赖分析专家',
  'identity:config_review': '配置审查专家',
  'identity:logic': '逻辑漏洞专家',
  // Pentest mode identities
  'identity:pentest_coordinator': '渗透测试协调器',
  'identity:recon': '信息收集专家',
  'identity:vuln_scan': '漏洞扫描专家',
  'identity:exploit': '漏洞利用专家',
  'identity:post_exploit': '后渗透专家',
  safety: '安全规则',
  'protocol:default': '默认协议',
  'protocol:coordinator': '协调器协议',
  'protocol:parser': '解析器协议',
  // Audit mode protocols
  'protocol:audit_coordinator': '代码审计协调器协议',
  'protocol:sast': '静态分析协议',
  'protocol:dependency': '依赖分析协议',
  'protocol:config_review': '配置审查协议',
  'protocol:logic': '逻辑漏洞协议',
  // Pentest mode protocols
  'protocol:pentest_coordinator': '渗透测试协调器协议',
  'protocol:recon': '信息收集协议',
  'protocol:vuln_scan': '漏洞扫描协议',
  'protocol:exploit': '漏洞利用协议',
  'protocol:post_exploit': '后渗透协议',
  parser_user: '解析器用户消息模板',
  writeup: 'Writeup 生成',
  flag_review: 'Flag 提取审查',
  compaction: '上下文压缩摘要',
  lessons: '经验提取提示词',
  auto_tag: '自动标签提示词',
}

export default function PromptManager() {
  const [prompts, setPrompts] = useState<PromptEntry[]>([])
  const [loading, setLoading] = useState(true)

  const [selectedId, setSelectedId] = useState<string>('')

  const [editContent, setEditContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [saved, setSaved] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    loadAll()
  }, [])

  const loadAll = async () => {
    setLoading(true)
    try {
      const promptData = await promptApi.list()
      setPrompts(promptData || [])
      // Auto-select first prompt if nothing selected
      if (!selectedId && promptData && promptData.length > 0) {
        setSelectedId(promptData[0].id)
        setEditContent(promptData[0].content)
        setOriginalContent(promptData[0].content)
      }
    } catch (err) {
      console.error('Failed to load data:', err)
    } finally {
      setLoading(false)
    }
  }

  const selectedPrompt = prompts.find((p) => p.id === selectedId)

  const handleSelectPrompt = (id: string) => {
    if (dirty && !confirm('当前修改未保存，确定切换吗？')) return
    setSelectedId(id)
    const prompt = prompts.find((p) => p.id === id)
    if (prompt) {
      setEditContent(prompt.content)
      setOriginalContent(prompt.content)
    }
    setDirty(false)
    setSaved(false)
  }

  const handleSave = async () => {
    if (!editContent.trim() || !selectedId) return
    setSaving(true)
    try {
      await promptApi.update(selectedId, editContent)
      const data = await promptApi.list()
      setPrompts(data || [])
      setOriginalContent(editContent)
      setSaved(true)
      setDirty(false)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save:', err)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!selectedId) return
    if (!confirm('确定重置为默认内容？自定义修改将丢失。')) return
    setResetting(true)
    try {
      await promptApi.reset(selectedId)
      const data = await promptApi.list()
      setPrompts(data || [])
      const updated = data?.find((p: PromptEntry) => p.id === selectedId)
      if (updated) {
        setEditContent(updated.content)
        setOriginalContent(updated.content)
      }
      setDirty(false)
    } catch (err) {
      console.error('Failed to reset prompt:', err)
    } finally {
      setResetting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )
  }

  const editorTitle = promptLabels[selectedId] || selectedId
  const editorSubtitle = selectedId
  const hasSelection = !!selectedPrompt

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-64 flex-shrink-0 border-r border-surface-border bg-white overflow-y-auto">
        <div className="px-4 py-3 border-b border-surface-border">
          <h2 className="text-sm font-bold text-gray-900 flex items-center gap-2">
            <FileText className="w-4 h-4 text-primary-500" />
            提示词管理
          </h2>
        </div>
        <div className="py-2">
          {/* Prompt groups */}
          {promptGroups.map((group) => (
            <div key={group.label} className="mb-1">
              <div className="px-4 py-1.5 text-xs font-medium text-gray-400 uppercase flex items-center gap-1.5">
                {group.icon}
                {group.label}
              </div>
              {group.ids.map((id) => {
                const prompt = prompts.find((p) => p.id === id)
                const isSelected = selectedId === id
                return (
                  <button
                    key={id}
                    onClick={() => handleSelectPrompt(id)}
                    className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 transition-colors ${
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
                    <span className="flex-1 truncate">{promptLabels[id] || id}</span>
                    {prompt?.is_customized && (
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" title="已自定义" />
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Main: editor */}
      <div className="flex-1 flex flex-col min-w-0">
        {hasSelection ? (
          <>
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-surface-border bg-white">
              <div>
                <h3 className="text-sm font-bold text-gray-900">{editorTitle}</h3>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-gray-400 font-mono">{editorSubtitle}</span>
                  {selectedPrompt && (
                    selectedPrompt.is_customized ? (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">已自定义</span>
                    ) : (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">默认</span>
                    )
                  )}
                  {dirty && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-500">未保存</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {selectedPrompt?.is_customized && (
                  <button
                    onClick={handleReset}
                    disabled={resetting}
                    className="btn-secondary flex items-center gap-1.5 text-xs"
                  >
                    {resetting ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="w-3.5 h-3.5" />
                    )}
                    重置为默认
                  </button>
                )}
                <button
                  onClick={handleSave}
                  disabled={saving || !dirty}
                  className="btn-primary flex items-center gap-1.5 text-xs"
                >
                  {saving ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : saved ? (
                    <Check className="w-3.5 h-3.5" />
                  ) : (
                    <Save className="w-3.5 h-3.5" />
                  )}
                  {saved ? '已保存' : '保存'}
                </button>
              </div>
            </div>

            {/* Editor */}
            <div className="flex-1 p-4 overflow-hidden">
              <textarea
                value={editContent}
                onChange={(e) => {
                  setEditContent(e.target.value)
                  setDirty(e.target.value !== originalContent)
                }}
                className="w-full h-full resize-none rounded-lg border border-surface-border bg-surface-50 p-4 text-sm font-mono text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                spellCheck={false}
              />
            </div>

            {/* Variable hints for parser_user */}
            {selectedId === 'parser_user' && (
              <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                可用变量：
                <code className="text-primary-500 ml-1">{'{{platform_url}}'}</code>
                <code className="text-primary-500 ml-2">{'{{platform_type}}'}</code>
                <code className="text-primary-500 ml-2">{'{{credentials}}'}</code>
              </div>
            )}

            {/* Hints for post-processing prompts */}
            {selectedId === 'writeup' && (
              <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                此提示词作为 system 消息发送给 LLM，用于在解题完成后生成结构化 Writeup。用户消息会自动附带题目标题、分类和对话历史。
              </div>
            )}
            {selectedId === 'flag_review' && (
              <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                此提示词用于在 Agent 未主动提交 Flag 时，让 LLM 从对话历史中提取可能的 Flag。LLM 应只返回 Flag 值或 "NONE"。
              </div>
            )}
            {selectedId === 'compaction' && (
              <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                当对话上下文接近 Token 上限时，此提示词用于将旧对话压缩为摘要。务必保留关键数据（Flag、地址、密钥等）。
              </div>
            )}
            {selectedId === 'lessons' && (
              <div className="px-6 py-2 border-t border-surface-border bg-surface-50 text-xs text-gray-400">
                解题完成后，此提示词用于从对话中提取分类经验。LLM 会返回 JSON 格式的分类经验，自动写入对应的经验库分类中。支持{' '}
                {'{{existing_tips}}'} {'{{challenge_category}}'} {'{{challenge_platform}}'} 变量。
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            从左侧选择一个提示词进行编辑
          </div>
        )}
      </div>
    </div>
  )
}
