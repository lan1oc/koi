import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Monitor,
  Plus,
  Play,
  Trash2,
  CheckCircle2,
  Clock,
  Loader2,
  X,
  Search,
  AlertTriangle,
  ShieldCheck,
  FileText,
  Wifi,
  WifiOff,
  Eye,
} from 'lucide-react'
import type { InspectionHost, InspectionStatus, InspectionModule } from '../types'
import { inspectionApi } from '../services/api'

const statusConfig: Record<InspectionStatus, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  idle:      { label: '待巡检', color: 'text-gray-500 bg-gray-50',     icon: Clock },
  running:   { label: '巡检中', color: 'text-blue-600 bg-blue-50',     icon: Loader2 },
  completed: { label: '已完成', color: 'text-green-600 bg-green-50',   icon: CheckCircle2 },
  failed:    { label: '失败',   color: 'text-red-600 bg-red-50',       icon: AlertTriangle },
}

export default function InspectionHosts() {
  const navigate = useNavigate()
  const [hosts, setHosts] = useState<InspectionHost[]>([])
  const [modules, setModules] = useState<InspectionModule[]>([])
  const [loading, setLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showInspect, setShowInspect] = useState<InspectionHost | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [testing, setTesting] = useState(false)

  const [form, setForm] = useState({
    name: '',
    host: '',
    port: '22',
    username: 'root',
    password: '',
  })

  const [inspectForm, setInspectForm] = useState({
    password: '',
    selectedModules: [] as string[],
  })

  const fetchHosts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await inspectionApi.listHosts()
      setHosts(data || [])
    } catch (e) {
      console.error('Failed to fetch inspection hosts:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchModules = useCallback(async () => {
    try {
      const data = await inspectionApi.listModules()
      setModules(data || [])
    } catch (e) {
      console.error('Failed to fetch modules:', e)
    }
  }, [])

  useEffect(() => {
    fetchHosts()
    fetchModules()
  }, [fetchHosts, fetchModules])

  // Auto-refresh running hosts
  useEffect(() => {
    const hasRunning = hosts.some((h) => h.status === 'running')
    if (!hasRunning) return
    const interval = setInterval(fetchHosts, 3000)
    return () => clearInterval(interval)
  }, [hosts, fetchHosts])

  const handleCreate = async () => {
    try {
      await inspectionApi.createHost({
        name: form.name,
        host: form.host,
        port: parseInt(form.port) || 22,
        username: form.username,
        password: form.password,
      })
      setShowCreate(false)
      setForm({ name: '', host: '', port: '22', username: 'root', password: '' })
      setTestResult(null)
      fetchHosts()
    } catch (e) {
      console.error('Failed to create host:', e)
    }
  }

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await inspectionApi.testConnection({
        host: form.host,
        port: parseInt(form.port) || 22,
        username: form.username,
        password: form.password,
      })
      setTestResult({
        success: result.success,
        message: result.success ? '连接成功' : (result.error || '连接失败'),
      })
    } catch (e: any) {
      setTestResult({ success: false, message: e.message || '连接测试失败' })
    } finally {
      setTesting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个巡检主机吗？')) return
    try {
      await inspectionApi.deleteHost(id)
      fetchHosts()
    } catch (e) {
      console.error('Failed to delete host:', e)
    }
  }

  const handleStartInspection = async (host: InspectionHost) => {
    if (!inspectForm.password) return
    try {
      await inspectionApi.startInspection(host.id, {
        password: inspectForm.password,
        modules: inspectForm.selectedModules.length > 0 ? inspectForm.selectedModules : undefined,
      })
      setShowInspect(null)
      setInspectForm({ password: '', selectedModules: [] })
      fetchHosts()
    } catch (e: any) {
      alert('启动巡检失败: ' + (e.message || '未知错误'))
    }
  }

  const toggleModule = (modName: string) => {
    setInspectForm((prev) => ({
      ...prev,
      selectedModules: prev.selectedModules.includes(modName)
        ? prev.selectedModules.filter((m) => m !== modName)
        : [...prev.selectedModules, modName],
    }))
  }

  const filteredHosts = hosts.filter(
    (h) =>
      !searchQuery ||
      h.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      h.host.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Linux 巡检主机</h1>
          <p className="text-sm text-gray-500 mt-1">管理服务器并执行自动化巡检</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> 添加主机
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="搜索主机..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 focus:border-blue-300 focus:ring-1 focus:ring-blue-200 text-sm"
        />
      </div>

      {/* Host List */}
      {loading ? (
        <div className="text-center text-gray-500 py-12">加载中...</div>
      ) : filteredHosts.length === 0 ? (
        <div className="text-center text-gray-500 py-12">
          {searchQuery ? '未找到匹配的主机' : '暂无巡检主机，点击"添加主机"开始'}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filteredHosts.map((host) => {
            const sc = statusConfig[host.status] || statusConfig.idle
            const StatusIcon = sc.icon
            return (
              <div key={host.id} className="panel p-4 space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center text-white">
                      <Monitor className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900">{host.name}</div>
                      <div className="text-xs text-gray-500">{host.host}:{host.port} • {host.username}</div>
                    </div>
                  </div>
                  <span className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-full ${sc.color}`}>
                    <StatusIcon className={`w-3 h-3 ${host.status === 'running' ? 'animate-spin' : ''}`} />
                    {sc.label}
                  </span>
                </div>

                {/* Stats */}
                {host.status !== 'idle' && (
                  <div className="flex gap-3 text-xs">
                    {host.issue_count > 0 && (
                      <span className="flex items-center gap-1 text-red-600">
                        <AlertTriangle className="w-3 h-3" /> {host.issue_count} 严重
                      </span>
                    )}
                    {host.warn_count > 0 && (
                      <span className="flex items-center gap-1 text-amber-600">
                        <ShieldCheck className="w-3 h-3" /> {host.warn_count} 警告
                      </span>
                    )}
                    {host.pass_count > 0 && (
                      <span className="flex items-center gap-1 text-green-600">
                        <CheckCircle2 className="w-3 h-3" /> {host.pass_count} 正常
                      </span>
                    )}
                  </div>
                )}

                {host.last_run_at && (
                  <div className="text-xs text-gray-400">
                    上次巡检: {new Date(host.last_run_at).toLocaleString()}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 pt-1 border-t border-gray-100">
                  <button
                    onClick={() => {
                      setShowInspect(host)
                      setInspectForm({ password: '', selectedModules: [] })
                    }}
                    disabled={host.status === 'running'}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-50 text-blue-600 hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    <Play className="w-3 h-3" /> 开始巡检
                  </button>
                  {host.status === 'completed' && (
                    <button
                      onClick={() => navigate(`/inspection/results/${host.id}`)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                    >
                      <Eye className="w-3 h-3" /> 查看结果
                    </button>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => handleDelete(host.id)}
                    disabled={host.status === 'running'}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create Host Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">添加巡检主机</h2>
              <button onClick={() => { setShowCreate(false); setTestResult(null) }} className="p-1 rounded-lg hover:bg-gray-100">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">主机名称 *</label>
                <input
                  type="text"
                  placeholder="例: 生产服务器01"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="text-xs font-medium text-gray-600 mb-1 block">主机地址 *</label>
                  <input
                    type="text"
                    placeholder="IP或域名"
                    value={form.host}
                    onChange={(e) => setForm({ ...form, host: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 mb-1 block">端口</label>
                  <input
                    type="number"
                    value={form.port}
                    onChange={(e) => setForm({ ...form, port: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">用户名 *</label>
                <input
                  type="text"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">密码 *</label>
                <input
                  type="password"
                  placeholder="SSH密码"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
                />
              </div>

              {/* Test connection result */}
              {testResult && (
                <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${
                  testResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                }`}>
                  {testResult.success ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
                  {testResult.message}
                </div>
              )}
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={handleTestConnection}
                disabled={!form.host || !form.username || !form.password || testing}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
                测试连接
              </button>
              <div className="flex-1" />
              <button onClick={() => { setShowCreate(false); setTestResult(null) }} className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100">
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!form.name || !form.host || !form.username}
                className="btn-primary px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Start Inspection Modal */}
      {showInspect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6 space-y-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">开始巡检: {showInspect.name}</h2>
              <button onClick={() => setShowInspect(null)} className="p-1 rounded-lg hover:bg-gray-100">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="text-sm text-gray-500">
              主机: {showInspect.host}:{showInspect.port} ({showInspect.username})
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1 block">SSH 密码 *</label>
              <input
                type="password"
                placeholder="输入SSH登录密码"
                value={inspectForm.password}
                onChange={(e) => setInspectForm({ ...inspectForm, password: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-blue-300 focus:ring-1 focus:ring-blue-200"
              />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-2 block">
                巡检模块 (留空则全选)
              </label>
              <div className="grid grid-cols-2 gap-2">
                {modules.map((mod) => (
                  <label
                    key={mod.name}
                    className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer text-sm transition-colors ${
                      inspectForm.selectedModules.includes(mod.name)
                        ? 'border-blue-300 bg-blue-50 text-blue-700'
                        : 'border-gray-200 hover:border-gray-300 text-gray-600'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={inspectForm.selectedModules.includes(mod.name)}
                      onChange={() => toggleModule(mod.name)}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border-2 flex items-center justify-center ${
                      inspectForm.selectedModules.includes(mod.name)
                        ? 'border-blue-500 bg-blue-500'
                        : 'border-gray-300'
                    }`}>
                      {inspectForm.selectedModules.includes(mod.name) && (
                        <CheckCircle2 className="w-3 h-3 text-white" />
                      )}
                    </div>
                    <div>
                      <div className="font-medium">{mod.label}</div>
                      <div className="text-xs text-gray-400">{mod.description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
              <strong>安全提示:</strong> 巡检仅执行只读命令收集系统信息，不会修改任何系统配置。敏感命令（如 rm、shutdown、reboot 等）已被禁用。
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button onClick={() => setShowInspect(null)} className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100">
                取消
              </button>
              <button
                onClick={() => handleStartInspection(showInspect)}
                disabled={!inspectForm.password}
                className="btn-primary px-4 py-2 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Play className="w-4 h-4" />
                开始巡检
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
