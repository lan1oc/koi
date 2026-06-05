import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderSearch,
  Plus,
  Play,
  Trash2,
  GitBranch,
  FolderOpen,
  Upload,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  X,
  Search,
} from 'lucide-react'
import type { AuditProject, AuditStatus } from '../types'

const statusConfig: Record<AuditStatus, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  pending:   { label: '待审计', color: 'text-gray-500 bg-gray-50',     icon: Clock },
  auditing:  { label: '审计中', color: 'text-blue-600 bg-blue-50',     icon: Loader2 },
  completed: { label: '已完成', color: 'text-green-600 bg-green-50',   icon: CheckCircle2 },
  failed:    { label: '失败',   color: 'text-red-600 bg-red-50',       icon: AlertTriangle },
}

export default function AuditProjects() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<AuditProject[]>([])
  const [loading, setLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Create form state
  const [form, setForm] = useState({
    name: '',
    source_type: 'local' as 'local' | 'git' | 'upload',
    source_path: '',
    git_url: '',
    language: '',
    framework: '',
    description: '',
  })

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/audit/projects')
      if (res.ok) {
        const data = await res.json()
        setProjects(data || [])
      }
    } catch (e) {
      console.error('Failed to fetch audit projects:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const handleCreate = async () => {
    try {
      const body = {
        name: form.name,
        source_type: form.source_type,
        source_path: form.source_type === 'local' ? form.source_path : undefined,
        git_url: form.source_type === 'git' ? form.git_url : undefined,
        language: form.language || undefined,
        framework: form.framework || undefined,
        description: form.description || undefined,
      }
      const res = await fetch('/api/audit/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        setShowCreate(false)
        setForm({ name: '', source_type: 'local', source_path: '', git_url: '', language: '', framework: '', description: '' })
        fetchProjects()
      }
    } catch (e) {
      console.error('Failed to create project:', e)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个审计项目吗？')) return
    try {
      await fetch(`/api/audit/projects/${id}`, { method: 'DELETE' })
      fetchProjects()
    } catch (e) {
      console.error('Failed to delete project:', e)
    }
  }

  const handleStartAudit = async (id: string) => {
    try {
      await fetch(`/api/audit/projects/${id}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      fetchProjects()
    } catch (e) {
      console.error('Failed to start audit:', e)
    }
  }

  const filtered = projects.filter(p =>
    !searchQuery || p.name.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <FolderSearch className="w-7 h-7 text-amber-600" />
          <h1 className="text-2xl font-bold text-gray-900">代码审计项目</h1>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors font-medium text-sm"
        >
          <Plus className="w-4 h-4" />
          新建审计
        </button>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索项目..."
          className="w-full pl-10 pr-4 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
        />
      </div>

      {/* Project list */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          加载中...
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <FolderSearch className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>暂无审计项目</p>
          <p className="text-sm mt-1">点击"新建审计"开始创建</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {filtered.map((project) => {
            const st = statusConfig[project.status]
            const StIcon = st.icon
            return (
              <div
                key={project.id}
                className="bg-white border border-surface-border rounded-xl p-5 hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => navigate(`/audit/task/${project.id}`)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-semibold text-gray-900 truncate">{project.name}</h3>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${st.color}`}>
                        <StIcon className={`w-3 h-3 ${project.status === 'auditing' ? 'animate-spin' : ''}`} />
                        {st.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      <span className="flex items-center gap-1">
                        {project.source_type === 'git' ? <GitBranch className="w-3.5 h-3.5" /> : <FolderOpen className="w-3.5 h-3.5" />}
                        {project.source_type === 'git' ? project.git_url : project.source_path}
                      </span>
                      {project.language && <span className="px-1.5 py-0.5 bg-gray-100 rounded text-xs">{project.language}</span>}
                      {project.framework && <span className="px-1.5 py-0.5 bg-gray-100 rounded text-xs">{project.framework}</span>}
                      {project.finding_count != null && project.finding_count > 0 && (
                        <span className="text-red-600 font-medium">{project.finding_count} 个发现</span>
                      )}
                    </div>
                    {project.description && (
                      <p className="text-sm text-gray-400 mt-1 truncate">{project.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 ml-4" onClick={(e) => e.stopPropagation()}>
                    {project.status === 'pending' && (
                      <button
                        onClick={() => handleStartAudit(project.id)}
                        className="p-2 text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                        title="开始审计"
                      >
                        <Play className="w-4 h-4" />
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(project.id)}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-gray-900">新建审计项目</h2>
              <button onClick={() => setShowCreate(false)} className="p-1 text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">项目名称 *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                  placeholder="例如：my-web-app"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">代码来源</label>
                <div className="flex gap-2">
                  {[
                    { value: 'local', label: '本地路径', icon: FolderOpen },
                    { value: 'git', label: 'Git 仓库', icon: GitBranch },
                    { value: 'upload', label: '上传文件', icon: Upload },
                  ].map(({ value, label, icon: Ic }) => (
                    <button
                      key={value}
                      onClick={() => setForm({ ...form, source_type: value as 'local' | 'git' | 'upload' })}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                        form.source_type === value
                          ? 'border-amber-500 bg-amber-50 text-amber-700'
                          : 'border-surface-border text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      <Ic className="w-3.5 h-3.5" />
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {form.source_type === 'local' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">本地路径 *</label>
                  <input
                    type="text"
                    value={form.source_path}
                    onChange={(e) => setForm({ ...form, source_path: e.target.value })}
                    className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                    placeholder="/path/to/source/code"
                  />
                </div>
              )}

              {form.source_type === 'git' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Git URL *</label>
                  <input
                    type="text"
                    value={form.git_url}
                    onChange={(e) => setForm({ ...form, git_url: e.target.value })}
                    className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                    placeholder="https://github.com/user/repo.git"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">编程语言</label>
                  <select
                    value={form.language}
                    onChange={(e) => setForm({ ...form, language: e.target.value })}
                    className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                  >
                    <option value="">自动识别</option>
                    <option value="python">Python</option>
                    <option value="javascript">JavaScript</option>
                    <option value="typescript">TypeScript</option>
                    <option value="go">Go</option>
                    <option value="java">Java</option>
                    <option value="php">PHP</option>
                    <option value="csharp">C#</option>
                    <option value="cpp">C/C++</option>
                    <option value="rust">Rust</option>
                    <option value="ruby">Ruby</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">框架</label>
                  <input
                    type="text"
                    value={form.framework}
                    onChange={(e) => setForm({ ...form, framework: e.target.value })}
                    className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                    placeholder="例如：Django, Spring, Gin"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">描述</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 border border-surface-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none"
                  placeholder="可选：项目描述、特别关注点等"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!form.name || (form.source_type === 'local' && !form.source_path) || (form.source_type === 'git' && !form.git_url)}
                className="px-4 py-2 bg-amber-600 text-white rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                创建项目
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
