import { useEffect, useState, useCallback } from 'react'
import {
  Plug,
  Plus,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  Terminal,
  Globe,
  ChevronDown,
  ChevronRight,
  Wrench,
  AlertCircle,
  FileJson,
  Power,
  PowerOff,
} from 'lucide-react'
import { mcpApi } from '../services/api'
import type { MCPServer, MCPTransport, MCPServerStatus, MCPImportResult } from '../types'

export default function McpManager() {
  const [servers, setServers] = useState<MCPServer[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [showJson, setShowJson] = useState(false)
  const [testingServer, setTestingServer] = useState<string | null>(null)
  const [actionServer, setActionServer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadServers = useCallback(async () => {
    try {
      setError(null)
      const data = await mcpApi.list()
      setServers(data || [])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadServers()
  }, [loadServers])

  const handleRemove = async (name: string) => {
    if (!confirm(`确定移除 MCP 服务器 "${name}" 吗？`)) return
    try {
      await mcpApi.remove(name)
      setServers((prev) => prev.filter((s) => s.name !== name))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleTest = async (name: string) => {
    setTestingServer(name)
    try {
      const result = await mcpApi.test(name)
      setServers((prev) =>
        prev.map((s) =>
          s.name === name
            ? {
                ...s,
                status: result.status as MCPServerStatus,
                tools: result.tools || s.tools,
                error: result.error,
              }
            : s
        )
      )
    } catch (e) {
      setServers((prev) =>
        prev.map((s) =>
          s.name === name ? { ...s, status: 'error', error: (e as Error).message } : s
        )
      )
    } finally {
      setTestingServer(null)
    }
  }

  const handleConnect = async (name: string) => {
    setActionServer(name)
    try {
      const result = await mcpApi.connect(name)
      setServers((prev) =>
        prev.map((s) =>
          s.name === name
            ? { ...s, status: result.status as MCPServerStatus, tools: result.tools || s.tools, error: result.error }
            : s
        )
      )
      // If status is "connecting", poll until it changes
      if (result.status === 'connecting') {
        const maxAttempts = 30 // 60s max
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise((r) => setTimeout(r, 2000))
          try {
            const list = await mcpApi.list()
            const srv = list?.find((s: MCPServer) => s.name === name)
            if (srv && srv.status !== 'connecting') {
              setServers((prev) =>
                prev.map((s) =>
                  s.name === name
                    ? { ...s, status: srv.status as MCPServerStatus, tools: srv.tools || [], error: srv.error }
                    : s
                )
              )
              break
            }
          } catch {
            // ignore polling errors
          }
        }
      }
    } catch (e) {
      setServers((prev) =>
        prev.map((s) =>
          s.name === name ? { ...s, status: 'error', error: (e as Error).message } : s
        )
      )
    } finally {
      setActionServer(null)
    }
  }

  const handleDisconnect = async (name: string) => {
    setActionServer(name)
    try {
      await mcpApi.disconnect(name)
      setServers((prev) =>
        prev.map((s) =>
          s.name === name ? { ...s, status: 'disconnected', tools: [] } : s
        )
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setActionServer(null)
    }
  }

  const handleAdded = (server: MCPServer) => {
    setServers((prev) => [...prev, server])
    setShowAdd(false)
  }

  const handleJsonImported = (results: MCPImportResult[]) => {
    setShowJson(false)
    setLoading(true)
    loadServers()
  }

  return (
    <div className="relative flex flex-col h-full">
      {/* Floating header */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
        <div className="flex items-center justify-between px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
        <div className="flex items-center gap-2">
          <Plug className="w-4 h-4 text-primary-500" />
          <h1 className="text-base font-bold text-gray-900">MCP 服务器</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setLoading(true); loadServers() }}
            className="btn-secondary flex items-center gap-2"
            disabled={loading}
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            onClick={() => setShowJson(true)}
            className="btn-secondary flex items-center gap-2"
          >
            <FileJson className="w-4 h-4" />
            JSON 导入
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="btn-primary flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            添加服务器
          </button>
        </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto pt-20 pb-6 max-w-4xl mx-auto w-full space-y-6">

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Server List */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          加载服务器中...
        </div>
      ) : servers.length === 0 ? (
        <div className="panel p-12 text-center">
          <Plug className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500 mb-1">未配置 MCP 服务器</p>
          <p className="text-sm text-gray-400">
            添加 MCP 服务器以扩展智能体的外部工具能力
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {servers.map((server) => (
            <ServerCard
              key={server.name}
              server={server}
              testing={testingServer === server.name}
              acting={actionServer === server.name}
              onTest={() => handleTest(server.name)}
              onRemove={() => handleRemove(server.name)}
              onConnect={() => handleConnect(server.name)}
              onDisconnect={() => handleDisconnect(server.name)}
            />
          ))}
        </div>
      )}

      {/* Add Modal */}
      {showAdd && (
        <AddServerModal onClose={() => setShowAdd(false)} onAdded={handleAdded} />
      )}

      {/* JSON Import Modal */}
      {showJson && (
        <JsonImportModal onClose={() => setShowJson(false)} onImported={handleJsonImported} />
      )}
      </div>
    </div>
  )
}

// ─── Server Card ───

function ServerCard({
  server,
  testing,
  acting,
  onTest,
  onRemove,
  onConnect,
  onDisconnect,
}: {
  server: MCPServer
  testing: boolean
  acting: boolean
  onTest: () => void
  onRemove: () => void
  onConnect: () => void
  onDisconnect: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const isConnected = server.status === 'connected'

  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center gap-3 p-4">
        {/* Icon */}
        <div className="p-2 rounded-lg bg-surface-50">
          {server.transport === 'stdio' ? (
            <Terminal className="w-5 h-5 text-gray-500" />
          ) : (
            <Globe className="w-5 h-5 text-gray-500" />
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900">{server.name}</span>
            <StatusBadge status={server.status} />
            {server.tools && server.tools.length > 0 && (
              <span className="text-xs text-gray-400 flex items-center gap-0.5">
                <Wrench className="w-3 h-3" />
                {server.tools.length}
              </span>
            )}
          </div>
          <div className="text-xs text-gray-400 mt-0.5 truncate">
            {server.transport === 'stdio'
              ? `${server.command} ${(server.args || []).join(' ')}`
              : server.url}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <button
              onClick={onDisconnect}
              disabled={acting}
              className="btn-secondary px-2.5 py-1.5 text-xs flex items-center gap-1.5 text-amber-600 hover:text-amber-700"
              title="断开连接"
            >
              {acting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PowerOff className="w-3.5 h-3.5" />}
              断开
            </button>
          ) : (
            <button
              onClick={onConnect}
              disabled={acting}
              className="btn-secondary px-2.5 py-1.5 text-xs flex items-center gap-1.5 text-green-600 hover:text-green-700"
              title="连接"
            >
              {acting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
              连接
            </button>
          )}
          <button
            onClick={onTest}
            disabled={testing}
            className="btn-secondary px-2.5 py-1.5 text-xs flex items-center gap-1.5"
            title="测试连接"
          >
            {testing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            测试
          </button>
          <button
            onClick={onRemove}
            className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="移除服务器"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-surface-hover transition-colors"
          >
            {expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Error */}
      {server.error && (
        <div className="mx-4 mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded text-xs text-red-600">
          {server.error}
        </div>
      )}

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-surface-border px-4 py-3 space-y-3 bg-surface-50">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <label className="text-xs font-medium text-gray-400">传输方式</label>
              <p className="text-gray-700">{server.transport}</p>
            </div>
            {server.command && (
              <div>
                <label className="text-xs font-medium text-gray-400">命令</label>
                <p className="text-gray-700 font-mono text-xs">{server.command}</p>
              </div>
            )}
            {server.args && server.args.length > 0 && (
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-400">参数</label>
                <p className="text-gray-700 font-mono text-xs">{server.args.join(' ')}</p>
              </div>
            )}
            {server.url && (
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-400">URL</label>
                <p className="text-gray-700 font-mono text-xs">{server.url}</p>
              </div>
            )}
          </div>

          {/* Environment Variables */}
          {server.env && Object.keys(server.env).length > 0 && (
            <div>
                <label className="text-xs font-medium text-gray-400">环境变量</label>
              <div className="mt-1 space-y-1">
                {Object.entries(server.env).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2 text-xs font-mono">
                    <span className="text-gray-500">{k}</span>
                    <span className="text-gray-300">=</span>
                    <span className="text-gray-700">••••••</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tools */}
          {server.tools && server.tools.length > 0 && (
            <div>
              <label className="text-xs font-medium text-gray-400 flex items-center gap-1">
                <Wrench className="w-3 h-3" />
                可用工具 ({server.tools.length})
              </label>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {server.tools.map((tool) => (
                  <span
                    key={tool}
                    className="px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 text-xs font-mono"
                  >
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Status Badge ───

function StatusBadge({ status }: { status?: MCPServerStatus }) {
  switch (status) {
    case 'connected':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-50 text-green-700 text-xs">
          <CheckCircle2 className="w-3 h-3" /> 已连接
        </span>
      )
    case 'error':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 text-red-600 text-xs">
          <XCircle className="w-3 h-3" /> 错误
        </span>
      )
    case 'connecting':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 text-xs">
          <Loader2 className="w-3 h-3 animate-spin" /> 连接中
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs">
          未连接
        </span>
      )
  }
}

// ─── Add Server Modal ───

function AddServerModal({
  onClose,
  onAdded,
}: {
  onClose: () => void
  onAdded: (s: MCPServer) => void
}) {
  const [form, setForm] = useState<{
    name: string
    transport: MCPTransport
    command: string
    args: string
    url: string
    envPairs: { key: string; value: string }[]
  }>({
    name: '',
    transport: 'stdio',
    command: '',
    args: '',
    url: '',
    envPairs: [],
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addEnvPair = () => {
    setForm((f) => ({ ...f, envPairs: [...f.envPairs, { key: '', value: '' }] }))
  }

  const removeEnvPair = (idx: number) => {
    setForm((f) => ({ ...f, envPairs: f.envPairs.filter((_, i) => i !== idx) }))
  }

  const updateEnvPair = (idx: number, field: 'key' | 'value', val: string) => {
    setForm((f) => ({
      ...f,
      envPairs: f.envPairs.map((p, i) => (i === idx ? { ...p, [field]: val } : p)),
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) return
    if (form.transport === 'stdio' && !form.command.trim()) return
    if (form.transport === 'sse' && !form.url.trim()) return

    setSaving(true)
    setError(null)

    const env: Record<string, string> = {}
    form.envPairs.forEach((p) => {
      if (p.key.trim()) env[p.key.trim()] = p.value
    })

    const server: MCPServer = {
      name: form.name.trim(),
      transport: form.transport,
      command: form.transport === 'stdio' ? form.command.trim() : undefined,
      args: form.transport === 'stdio' && form.args.trim()
        ? form.args.split(/\s+/)
        : undefined,
      url: form.transport === 'sse' ? form.url.trim() : undefined,
      env: Object.keys(env).length > 0 ? env : undefined,
    }

    try {
      const added = await mcpApi.add(server)
      onAdded(added)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg">
        <div className="panel-header justify-between">
          <span className="flex items-center gap-2">
            <Plug className="w-4 h-4" />
            添加 MCP 服务器
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {error && (
            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-600">
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">服务器名称 *</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="input-field w-full"
              placeholder="my-mcp-server"
              autoFocus
            />
          </div>

          {/* Transport */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">传输方式</label>
            <div className="flex gap-2">
              {(['stdio', 'sse'] as MCPTransport[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setForm({ ...form, transport: t })}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm transition-colors ${
                    form.transport === t
                      ? 'bg-primary-50 border-primary-300 text-primary-700'
                      : 'border-surface-border text-gray-500 hover:bg-surface-hover'
                  }`}
                >
                  {t === 'stdio' ? (
                    <Terminal className="w-4 h-4" />
                  ) : (
                    <Globe className="w-4 h-4" />
                  )}
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Stdio fields */}
          {form.transport === 'stdio' && (
            <>
              <div>
                <label className="block text-xs text-gray-500 mb-1">命令 *</label>
                <input
                  type="text"
                  value={form.command}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  className="input-field w-full font-mono text-sm"
                  placeholder="npx -y @modelcontextprotocol/server-filesystem"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">参数（空格分隔）</label>
                <input
                  type="text"
                  value={form.args}
                  onChange={(e) => setForm({ ...form, args: e.target.value })}
                  className="input-field w-full font-mono text-sm"
                  placeholder="/path/to/allowed/dir"
                />
              </div>
            </>
          )}

          {/* SSE fields */}
          {form.transport === 'sse' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">服务器地址 *</label>
              <input
                type="url"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                className="input-field w-full font-mono text-sm"
                placeholder="http://localhost:3001/sse"
              />
            </div>
          )}

          {/* Env */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-gray-500">环境变量</label>
              <button
                type="button"
                onClick={addEnvPair}
                className="text-xs text-primary-600 hover:text-primary-500"
              >
                + 添加变量
              </button>
            </div>
            {form.envPairs.map((pair, idx) => (
              <div key={idx} className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={pair.key}
                  onChange={(e) => updateEnvPair(idx, 'key', e.target.value)}
                  className="input-field flex-1 font-mono text-sm"
                  placeholder="KEY"
                />
                <span className="text-gray-300">=</span>
                <input
                  type="password"
                  value={pair.value}
                  onChange={(e) => updateEnvPair(idx, 'value', e.target.value)}
                  className="input-field flex-1 font-mono text-sm"
                  placeholder="value"
                />
                <button
                  type="button"
                  onClick={() => removeEnvPair(idx)}
                  className="text-gray-400 hover:text-red-500"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              取消
            </button>
            <button
              type="submit"
              disabled={saving || !form.name.trim()}
              className="btn-primary flex items-center gap-2"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              {saving ? '添加中...' : '添加服务器'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── JSON Import Modal ───

const JSON_PLACEHOLDER = `{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {}
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-key"
      }
    }
  }
}`

function JsonImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void
  onImported: (results: MCPImportResult[]) => void
}) {
  const [jsonText, setJsonText] = useState('')
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<MCPImportResult[] | null>(null)

  const handleImport = async () => {
    if (!jsonText.trim()) return
    // Validate JSON locally first
    try {
      JSON.parse(jsonText)
    } catch {
      setError('JSON 格式无效，请检查语法')
      return
    }

    setImporting(true)
    setError(null)
    setResults(null)

    try {
      const res = await mcpApi.import(jsonText)
      setResults(res)
      onImported(res)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="panel-header justify-between">
          <span className="flex items-center gap-2">
            <FileJson className="w-4 h-4" />
            JSON 导入 MCP 服务器
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>
        <div className="p-4 space-y-4 flex-1 overflow-auto">
          <p className="text-xs text-gray-500">
            支持 Claude Desktop 格式 (<code className="bg-gray-100 px-1 rounded">{'{"mcpServers":{...}}'}</code>)
            或直接 map 格式 (<code className="bg-gray-100 px-1 rounded">{'{"name":{...}}'}</code>)
          </p>

          {error && (
            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-600 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <textarea
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            className="input-field w-full font-mono text-sm h-64 resize-y"
            placeholder={JSON_PLACEHOLDER}
            spellCheck={false}
          />

          {/* Import Results */}
          {results && (
            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500">导入结果</label>
              {results.map((r) => (
                <div
                  key={r.name}
                  className={`flex items-center justify-between px-3 py-2 rounded text-sm ${
                    r.status === 'connected'
                      ? 'bg-green-50 text-green-700'
                      : 'bg-red-50 text-red-600'
                  }`}
                >
                  <span className="font-mono">{r.name}</span>
                  <span className="flex items-center gap-1">
                    {r.status === 'connected' ? (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        已连接
                        {r.tools && r.tools.length > 0 && (
                          <span className="text-xs ml-1">({r.tools.length} 工具)</span>
                        )}
                      </>
                    ) : (
                      <>
                        <XCircle className="w-3.5 h-3.5" />
                        {r.error || '失败'}
                      </>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={onClose} className="btn-secondary">
              {results ? '关闭' : '取消'}
            </button>
            {!results && (
              <button
                onClick={handleImport}
                disabled={importing || !jsonText.trim()}
                className="btn-primary flex items-center gap-2"
              >
                {importing && <Loader2 className="w-4 h-4 animate-spin" />}
                {importing ? '导入中...' : '导入'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
