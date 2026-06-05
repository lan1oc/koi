import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Swords,
  Play,
  Square,
  RefreshCw,
  Trophy,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronRight,
  KeyRound,
  Cpu,
} from 'lucide-react'
import { nssArenaApi } from '../services/api'
import { wsService } from '../services/websocket'
import { useSettingsStore } from '../stores/settingsStore'
import { useNotificationStore } from '../stores/notificationStore'
import type { NSSArenaState, WSEvent } from '../types'

const TOKEN_STORAGE_KEY = 'nssctf_agent_token'

const CATEGORY_BADGE: Record<string, string> = {
  web: 'bg-blue-100 text-blue-700 border-blue-200',
  pwn: 'bg-red-100 text-red-700 border-red-200',
  reverse: 'bg-purple-100 text-purple-700 border-purple-200',
  crypto: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  misc: 'bg-gray-100 text-gray-700 border-gray-200',
  forensics: 'bg-teal-100 text-teal-700 border-teal-200',
}
const catBadge = (c: string) => CATEGORY_BADGE[c?.toLowerCase()] || 'bg-gray-100 text-gray-600 border-gray-200'

const STATE_STYLE: Record<string, { label: string; cls: string }> = {
  solved: { label: '✓ 解出', cls: 'text-green-600' },
  failed: { label: '✗ 失败', cls: 'text-red-500' },
  abandoned: { label: '⏹ 放弃', cls: 'text-gray-500' },
  expired: { label: '⏱ 超时', cls: 'text-orange-500' },
  invalid: { label: '⚠ 不支持', cls: 'text-amber-600' },
}
const stateStyle = (s: string) => STATE_STYLE[s] || { label: s, cls: 'text-gray-500' }

function fmtDuration(ms: number): string {
  const secs = Math.round(ms / 1000)
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  return `${m}m${secs % 60}s`
}

export default function AgentArena() {
  const navigate = useNavigate()
  const { selectedModel, utilityModel } = useSettingsStore()
  const addNotification = useNotificationStore((s) => s.addNotification)
  const notify = (type: 'success' | 'error' | 'info', message: string) =>
    addNotification({ type, title: 'Agent CTF', message })

  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) || '')
  const [rememberToken, setRememberToken] = useState(() => !!localStorage.getItem(TOKEN_STORAGE_KEY))
  const [model, setModel] = useState('')
  const [maxProblems, setMaxProblems] = useState(0)
  const [baseUrl, setBaseUrl] = useState('')

  const [arena, setArena] = useState<NSSArenaState | null>(null)
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<{ ts: number; text: string }[]>([])
  const [busy, setBusy] = useState(false)
  const logRef = useRef<HTMLDivElement | null>(null)

  const effectiveModel = model || selectedModel || '(默认模型)'

  const refresh = async () => {
    try {
      const res = await nssArenaApi.status()
      setArena(res.arena)
      setRunning(res.running)
    } catch {
      /* noop */
    }
  }

  // Initial load + poll while running.
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [])

  // Live event log via WebSocket.
  useEffect(() => {
    const types = ['nss_arena_start', 'nss_arena_attempt_start', 'nss_arena_attempt_end', 'nss_arena_end', 'nss_arena_error']
    const unsubs = types.map((t) =>
      wsService.on(t, (e: WSEvent) => {
        if (e.content) setLog((prev) => [{ ts: Date.now(), text: e.content as string }, ...prev].slice(0, 200))
        refresh()
      }),
    )
    return () => unsubs.forEach((u) => u())
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = 0
  }, [log])

  const start = async () => {
    if (!token.trim()) {
      notify('error', '请填写 NSSCTF Agent Token')
      return
    }
    setBusy(true)
    try {
      if (rememberToken) localStorage.setItem(TOKEN_STORAGE_KEY, token.trim())
      else localStorage.removeItem(TOKEN_STORAGE_KEY)
      await nssArenaApi.start({
        token: token.trim(),
        model: model || undefined,
        utilityModel: utilityModel || undefined,
        baseUrl: baseUrl || undefined,
        maxProblems,
      })
      notify('success', 'Agent CTF 模式已启动')
      await refresh()
    } catch (e) {
      notify('error', `启动失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const stop = async () => {
    setBusy(true)
    try {
      await nssArenaApi.stop()
      notify('info', '正在停止 Agent CTF 模式...')
      await refresh()
    } catch (e) {
      notify('error', `停止失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const successRate = arena && arena.processed > 0 ? Math.round((arena.solved_count / Math.max(arena.processed, 1)) * 100) : 0

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-xl bg-indigo-50 border border-indigo-200">
          <Swords className="w-6 h-6 text-indigo-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Agent CTF 模式 · NSSCTF Arena</h1>
          <p className="text-sm text-gray-500">自动领取 NSSCTF 竞技场题目，由 AI Agent 解题、提交 flag 并刷新 rating</p>
        </div>
        <button onClick={refresh} className="ml-auto p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100" title="刷新">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Control panel */}
      <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="text-xs font-semibold text-gray-600 flex items-center gap-1.5 mb-1">
              <KeyRound className="w-3.5 h-3.5" /> NSSCTF Agent Token
            </label>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              disabled={running}
              placeholder="nss_agent_xxx（留空则使用后端配置 / 环境变量）"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none disabled:bg-gray-50"
            />
            <label className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-gray-500">
              <input type="checkbox" checked={rememberToken} onChange={(e) => setRememberToken(e.target.checked)} disabled={running} />
              在本机记住 Token
            </label>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-600 flex items-center gap-1.5 mb-1">
              <Cpu className="w-3.5 h-3.5" /> 解题模型
            </label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={running}
              placeholder={selectedModel || '默认模型'}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none disabled:bg-gray-50"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-600 mb-1 block">最多题数（0 = 不限）</label>
            <input
              type="number"
              min={0}
              value={maxProblems}
              onChange={(e) => setMaxProblems(Math.max(0, parseInt(e.target.value) || 0))}
              disabled={running}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none disabled:bg-gray-50"
            />
          </div>

          <div className="md:col-span-2">
            <label className="text-xs font-semibold text-gray-600 mb-1 block">API 地址（可选）</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              disabled={running}
              placeholder="https://www.nssctf.cn/api"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none disabled:bg-gray-50"
            />
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          {!running ? (
            <button
              onClick={start}
              disabled={busy}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              <Play className="w-4 h-4" /> 启动 Agent CTF 模式
            </button>
          ) : (
            <button
              onClick={stop}
              disabled={busy}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500 text-white text-sm font-medium hover:bg-red-600 disabled:opacity-50"
            >
              <Square className="w-4 h-4" /> 停止
            </button>
          )}
          <span className="text-xs text-gray-400">解题模型：{effectiveModel}</span>
          {running && <span className="inline-flex items-center gap-1.5 text-xs text-green-600"><span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" /> 运行中</span>}
        </div>
      </div>

      {/* Stats */}
      {arena && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard icon={<Trophy className="w-4 h-4 text-amber-500" />} label="Rating" value={arena.rating || '—'} />
          <StatCard icon={<ChevronRight className="w-4 h-4 text-indigo-500" />} label="已处理" value={arena.processed} />
          <StatCard icon={<CheckCircle2 className="w-4 h-4 text-green-500" />} label="解出" value={arena.solved_count} />
          <StatCard icon={<XCircle className="w-4 h-4 text-red-400" />} label="未解出" value={arena.failed_count} />
          <StatCard icon={<Trophy className="w-4 h-4 text-blue-500" />} label="成功率" value={`${successRate}%`} />
        </div>
      )}

      {/* Current problem */}
      {arena?.current && (
        <div className="bg-white rounded-2xl border border-indigo-200 p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
            <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">正在解题</span>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <span className={`px-2 py-0.5 rounded text-xs font-medium border ${catBadge(arena.current.category)}`}>{arena.current.category}</span>
            <span className="font-medium text-gray-900">{arena.current.title}</span>
            <span className="text-xs text-gray-400">rating {arena.current.rating}</span>
            <span className="inline-flex items-center gap-1 text-xs text-gray-400"><Clock className="w-3 h-3" /> 剩余 {arena.current.remaining_seconds}s</span>
            {arena.current.challenge_id && (
              <button
                onClick={() => navigate(`/solve/${arena.current!.challenge_id}`)}
                className="ml-auto text-xs px-2.5 py-1 rounded-lg border border-indigo-200 text-indigo-600 hover:bg-indigo-50"
              >
                查看解题过程
              </button>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* History */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 text-sm font-semibold text-gray-700">解题历史</div>
          <div className="max-h-[420px] overflow-auto">
            {arena && arena.history.length > 0 ? (
              <table className="w-full text-sm">
                <tbody>
                  {arena.history.map((r) => {
                    const st = stateStyle(r.state)
                    return (
                      <tr
                        key={r.attempt_id + r.finished_at}
                        className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
                        onClick={() => r.challenge_id && navigate(`/solve/${r.challenge_id}`)}
                      >
                        <td className="px-4 py-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[11px] border ${catBadge(r.category)}`}>{r.category}</span>
                        </td>
                        <td className="px-2 py-2.5 text-gray-800 truncate max-w-[180px]">{r.title}</td>
                        <td className={`px-2 py-2.5 font-medium whitespace-nowrap ${st.cls}`}>{st.label}</td>
                        <td className="px-2 py-2.5 text-xs text-gray-400 whitespace-nowrap">
                          {r.rating_delta >= 0 ? `+${r.rating_delta}` : r.rating_delta}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-gray-400 whitespace-nowrap">{fmtDuration(r.duration_ms)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-sm text-gray-400">暂无解题记录</div>
            )}
          </div>
        </div>

        {/* Event log */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 text-sm font-semibold text-gray-700">实时日志</div>
          <div ref={logRef} className="max-h-[420px] overflow-auto p-3 space-y-1.5">
            {log.length > 0 ? (
              log.map((l, i) => (
                <div key={i} className="text-xs text-gray-600 flex gap-2">
                  <span className="text-gray-300 tabular-nums">{new Date(l.ts).toLocaleTimeString()}</span>
                  <span className="flex-1">{l.text}</span>
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-sm text-gray-400">等待事件...</div>
            )}
          </div>
        </div>
      </div>

      {arena?.error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">错误：{arena.error}</div>
      )}
    </div>
  )
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 shadow-sm">
      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
        {icon}
        {label}
      </div>
      <div className="text-lg font-bold text-gray-900">{value}</div>
    </div>
  )
}
