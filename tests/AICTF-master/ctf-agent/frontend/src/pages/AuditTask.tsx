import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Play,
  Square,
  ArrowLeft,
  Terminal,
  MessageSquare,
  FileText,
  Info,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Shield,
  Download,
  FileDown,
  X,
} from 'lucide-react'
import { exportReportPDF } from '../utils/exportPdf'
import { useAgentStore } from '../stores/agentStore'
import { useSettingsStore } from '../stores/settingsStore'
import { sessionApi } from '../services/api'
import { wsService } from '../services/websocket'
import ChatPanel from '../components/ChatPanel'
import TerminalView from '../components/TerminalView'
import AgentStatusBar from '../components/AgentStatusBar'
import TodoListPanel from '../components/TodoListPanel'
import type { AuditProject, AuditFinding, FindingSeverity } from '../types'

type Panel = 'chat' | 'terminal' | 'info' | 'findings'

const severityColors: Record<FindingSeverity, string> = {
  critical: 'bg-red-600 text-white',
  high:     'bg-orange-500 text-white',
  medium:   'bg-yellow-500 text-white',
  low:      'bg-blue-500 text-white',
  info:     'bg-gray-400 text-white',
}

export default function AuditTask() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { session, setSession, isRunning, agentId, setAgentId, connectWS, disconnectWS, loadHistory, checkRunning, reset } = useAgentStore()
  const { selectedModel, utilityModel } = useSettingsStore()
  const [project, setProject] = useState<AuditProject | null>(null)
  const [findings, setFindings] = useState<AuditFinding[]>([])
  const [activePanel, setActivePanel] = useState<Panel>('chat')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [terminalId, setTerminalId] = useState<string | null>(null)

  // ─── PDF export ───
  const [showPdfModal, setShowPdfModal] = useState(false)
  const [pdfTitle, setPdfTitle] = useState('')
  const [pdfExporting, setPdfExporting] = useState(false)

  const handleExportPDF = useCallback(async () => {
    if (!projectId) return
    setPdfExporting(true)
    try {
      const res = await fetch(`/api/audit/projects/${projectId}/export`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const markdown = await res.text()
      exportReportPDF(markdown, pdfTitle || `代码审计报告 - ${project?.name || ''}`, '代码审计报告')
    } catch (e) {
      console.error('Export PDF failed:', e)
      alert('导出 PDF 失败: ' + (e as Error).message)
    } finally {
      setPdfExporting(false)
      setShowPdfModal(false)
    }
  }, [projectId, pdfTitle, project?.name])

  // Load project info
  useEffect(() => {
    if (!projectId) return
    fetch(`/api/audit/projects/${projectId}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => data && setProject(data))
      .catch(console.error)

    // Load findings
    fetch(`/api/audit/projects/${projectId}/findings`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setFindings(data || []))
      .catch(console.error)

    // Try to restore session
    if (session && session.challenge_id === projectId) {
      connectWS(session.id)
      loadHistory(session.id)
      checkRunning(session.id)
    } else {
      sessionApi.getByChallenge(projectId).then((sess) => {
        setSession(sess)
        connectWS(sess.id)
        loadHistory(sess.id)
        checkRunning(sess.id)
      }).catch(() => reset())
    }

    return () => { disconnectWS() }
  }, [projectId])

  // Listen for findings updates
  useEffect(() => {
    const unsub = wsService.on('tool_call_end', () => {
      // Refresh findings when tools complete
      if (projectId) {
        fetch(`/api/audit/projects/${projectId}/findings`)
          .then(r => r.ok ? r.json() : [])
          .then(data => setFindings(data || []))
          .catch(() => {})
      }
    })
    return () => unsub()
  }, [projectId])

  const handleStart = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    reset()
    setTerminalId(null)
    try {
      const res = await fetch(`/api/audit/projects/${projectId}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selectedModel, utility_model: utilityModel }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const result = await res.json()
      if (result.session_id) {
        const sess = { id: result.session_id, challenge_id: projectId, agent_id: result.agent_id || '', status: 'active' as const, model: selectedModel, created_at: new Date().toISOString() }
        setSession(sess)
        connectWS(sess.id)
        setAgentId(result.agent_id || null)
        // Create terminal
        sessionApi.createTerminal(sess.id)
          .then(r => setTerminalId(r.terminal_id))
          .catch(e => console.warn('Terminal creation failed:', e))
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [projectId, selectedModel, utilityModel])

  const handleStop = useCallback(async () => {
    const currentAgentId = useAgentStore.getState().agentId
    if (!currentAgentId) return
    try {
      await fetch(`/api/agent/stop/${encodeURIComponent(currentAgentId)}`, { method: 'POST' })
    } catch (e) {
      console.error('Failed to stop:', e)
    }
  }, [])

  const panels: { key: Panel; icon: React.ComponentType<{ className?: string }>; label: string }[] = [
    { key: 'chat', icon: MessageSquare, label: '对话' },
    { key: 'terminal', icon: Terminal, label: '终端' },
    { key: 'findings', icon: Shield, label: `发现 (${findings.length})` },
    { key: 'info', icon: Info, label: '项目信息' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border bg-white">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/audit/projects')} className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-lg font-bold text-gray-900">{project?.name || '审计任务'}</h1>
            {project && (
              <p className="text-xs text-gray-400">
                {project.language && `${project.language} `}
                {project.framework && `/ ${project.framework} `}
                · {project.source_type === 'git' ? project.git_url : project.source_path}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!isRunning ? (
            <button
              onClick={handleStart}
              disabled={loading}
              className="flex items-center gap-1.5 px-4 py-2 bg-amber-600 text-white rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-50 transition-colors"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              开始审计
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="flex items-center gap-1.5 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
            >
              <Square className="w-4 h-4" />
              停止
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mx-5 mt-2 p-2 bg-red-50 text-red-600 text-sm rounded-lg flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Agent status */}
      {isRunning && <AgentStatusBar />}

      {/* Panel tabs */}
      <div className="flex items-center gap-1 px-5 pt-2 bg-white border-b border-surface-border">
        {panels.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => setActivePanel(key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-lg transition-colors ${
              activePanel === key
                ? 'bg-surface-50 text-primary-700 font-medium border-b-2 border-primary-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-hidden">
        {activePanel === 'chat' && <ChatPanel />}
        {activePanel === 'terminal' && (
          <div className="h-full p-4">
            {session ? <TerminalView sessionId={session.id} /> : <div className="text-gray-400 text-center py-20">启动审计后可使用终端</div>}
          </div>
        )}
        {activePanel === 'findings' && (
          <div className="h-full overflow-auto p-5">
            {findings.length > 0 && (
              <div className="flex justify-end items-center mb-3 gap-2">
                <a
                  href={`/api/audit/projects/${projectId}/export`}
                  download
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  导出报告
                </a>
                <button
                  onClick={() => { setPdfTitle(`代码审计报告 - ${project?.name || ''}`); setShowPdfModal(true) }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
                >
                  <FileDown className="w-4 h-4" />
                  导出 PDF
                </button>
              </div>
            )}
            {findings.length === 0 ? (
              <div className="text-center py-20 text-gray-400">
                <Shield className="w-10 h-10 mx-auto mb-3 opacity-50" />
                <p>暂无发现</p>
                <p className="text-sm mt-1">审计完成后将在此展示漏洞发现</p>
              </div>
            ) : (
              <div className="space-y-3">
                {findings.map((f) => (
                  <div key={f.id} className="bg-white border border-surface-border rounded-xl p-4">
                    <div className="flex items-start gap-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${severityColors[f.severity]}`}>
                        {f.severity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <h4 className="font-semibold text-gray-900">{f.title}</h4>
                        <p className="text-sm text-gray-500 mt-1">{f.location}</p>
                        {f.cwe_id && <span className="text-xs text-gray-400">{f.cwe_id}</span>}
                        <p className="text-sm text-gray-600 mt-2">{f.description}</p>
                        {f.poc && (
                          <details className="mt-2">
                            <summary className="text-xs text-amber-600 cursor-pointer font-medium">PoC</summary>
                            <pre className="mt-1 p-2 bg-gray-50 rounded text-xs overflow-auto">{f.poc}</pre>
                          </details>
                        )}
                        {f.remediation && (
                          <details className="mt-2">
                            <summary className="text-xs text-green-600 cursor-pointer font-medium">修复建议</summary>
                            <p className="mt-1 text-sm text-gray-600">{f.remediation}</p>
                          </details>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {activePanel === 'info' && project && (
          <div className="h-full overflow-auto p-5">
            <div className="bg-white border border-surface-border rounded-xl p-5 max-w-2xl">
              <h3 className="font-semibold text-gray-900 mb-4">项目信息</h3>
              <dl className="space-y-3 text-sm">
                <div className="flex"><dt className="w-24 text-gray-500">名称</dt><dd className="text-gray-900">{project.name}</dd></div>
                <div className="flex"><dt className="w-24 text-gray-500">来源类型</dt><dd className="text-gray-900">{project.source_type}</dd></div>
                <div className="flex"><dt className="w-24 text-gray-500">路径</dt><dd className="text-gray-900 break-all">{project.source_path || project.git_url}</dd></div>
                {project.language && <div className="flex"><dt className="w-24 text-gray-500">语言</dt><dd className="text-gray-900">{project.language}</dd></div>}
                {project.framework && <div className="flex"><dt className="w-24 text-gray-500">框架</dt><dd className="text-gray-900">{project.framework}</dd></div>}
                {project.description && <div className="flex"><dt className="w-24 text-gray-500">描述</dt><dd className="text-gray-900">{project.description}</dd></div>}
                <div className="flex"><dt className="w-24 text-gray-500">状态</dt><dd className="text-gray-900">{project.status}</dd></div>
                <div className="flex"><dt className="w-24 text-gray-500">创建时间</dt><dd className="text-gray-900">{new Date(project.created_at).toLocaleString()}</dd></div>
              </dl>
            </div>
            {/* TodoList for audit */}
            <div className="mt-4">
              <TodoListPanel />
            </div>
          </div>
        )}
      </div>

      {/* PDF export modal */}
      {showPdfModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <FileDown className="w-5 h-5 text-indigo-600" />
                <h3 className="text-lg font-bold text-gray-900">导出 PDF 报告</h3>
              </div>
              <button onClick={() => setShowPdfModal(false)} className="p-1 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">报告标题</label>
                <input
                  type="text"
                  value={pdfTitle}
                  onChange={e => setPdfTitle(e.target.value)}
                  placeholder="请输入 PDF 报告标题"
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 placeholder-gray-400"
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && handleExportPDF()}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 px-6 py-4 bg-gray-50 border-t border-gray-200">
              <button
                onClick={() => setShowPdfModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleExportPDF}
                disabled={pdfExporting}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {pdfExporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileDown className="w-4 h-4" />}
                导出
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
