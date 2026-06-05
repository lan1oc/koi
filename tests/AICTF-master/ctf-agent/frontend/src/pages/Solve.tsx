import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Play, Square, GitBranch, Terminal, MessageSquare, ArrowLeft, Info, FileText, RotateCcw, FastForward, FileEdit, Skull, Lightbulb, BrainCircuit, ScrollText, X, FileDown, Swords, Trash2, MessageCircleQuestion, ChevronDown, ExternalLink, Clock, Tag, Paperclip, Flag, Shield, Award, AlertCircle, Target, Layers, FileBarChart, Key } from 'lucide-react'
import { useChallengeStore } from '../stores/challengeStore'
import { useAgentStore } from '../stores/agentStore'
import { useSettingsStore } from '../stores/settingsStore'
import { useArenaStore } from '../stores/arenaStore'
import { useTopologyStore } from '../stores/topologyStore'
import { agentApi, sessionApi, challengeApi } from '../services/api'
import { wsService } from '../services/websocket'
import ChatPanel from '../components/ChatPanel'
import TerminalView from '../components/TerminalView'
import AgentStatusBar from '../components/AgentStatusBar'
import TodoListPanel from '../components/TodoListPanel'
import IdeasPanel from '../components/IdeasPanel'
import ProgressReportPanel from '../components/ProgressReportPanel'
import MarkdownRenderer from '../components/MarkdownRenderer'
import AgentTopologyPanel from '../components/AgentTopologyPanel'
import KeyFindingsPanel from '../components/KeyFindingsPanel'
import type { Challenge } from '../types'

type Panel = 'chat' | 'terminal' | 'info' | 'writeup' | 'ideas' | 'reflection' | 'progress' | 'topology' | 'findings'

export default function Solve() {
  const { challengeId } = useParams<{ challengeId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedSessionId = searchParams.get('session')
  const { getChallenge } = useChallengeStore()
  const { session, hasHydrated, setSession, isRunning, agentId, setAgentId, connectWS, disconnectWS, loadHistory, checkRunning, reset } = useAgentStore()
  const { selectedModel, utilityModel, providers, fetchProviders, setModel } = useSettingsStore()
  const { startArena, stopArena, getArenaForChallenge, initWS: initArenaWS } = useArenaStore()
  const connectTopology = useTopologyStore((s) => s.connect)
  const disconnectTopology = useTopologyStore((s) => s.disconnect)
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [activePanel, setActivePanel] = useState<Panel>('chat')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [terminalId, setTerminalId] = useState<string | null>(null)
  const [writeup, setWriteup] = useState<string | null>(null)
  const [writeupLoading, setWriteupLoading] = useState(false)
  const [persistentRunning, setPersistentRunning] = useState(false)
  const [reflection, setReflection] = useState<Record<string, unknown> | null>(null)
  const [reflectionLoading, setReflectionLoading] = useState(false)
  const [showPromptModal, setShowPromptModal] = useState(false)
  const [promptContent, setPromptContent] = useState('')
  const [promptLoading, setPromptLoading] = useState(false)
  const [showArenaModal, setShowArenaModal] = useState(false)
  const [arenaModelB, setArenaModelB] = useState('')

  // Get current arena for this challenge
  const arenaEntry = challengeId ? getArenaForChallenge(challengeId) : null

  // Initialize arena WS listeners and restore state from backend
  const restoreArena = useArenaStore((s) => s.restoreFromBackend)
  useEffect(() => {
    const cleanup = initArenaWS()
    restoreArena()
    return cleanup
  }, [])

  useEffect(() => {
    connectTopology()
    return () => disconnectTopology()
  }, [connectTopology, disconnectTopology])

  // Load available providers so the 解题模型 dropdown is populated
  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  // Load challenge and restore session if available
  useEffect(() => {
    if (!challengeId) return

    // Wait until zustand-persist rehydration completes to avoid racing against session restoration.
    if (!hasHydrated) return

    let cancelled = false
    setChallenge(null)
    setWriteup(null)
    setWriteupLoading(false)
    setReflection(null)
    setReflectionLoading(false)
    setTerminalId(null)
    setPersistentRunning(false)
    setError(null)

    getChallenge(challengeId).then((ch) => {
      if (cancelled) return
      setChallenge(ch)
      setWriteup(ch.writeup || null)
    }).catch(console.error)

    // Check for a specific session_id in URL params (e.g. from pipeline badge click)
    if (requestedSessionId) {
      // Load the specific session requested via URL param
      sessionApi.get(requestedSessionId).then((sess) => {
        if (cancelled) return
        setSession(sess)
        connectWS(sess.id)
        loadHistory(sess.id)
        checkRunning(sess.id)
      }).catch(() => {
        // Fallback: load latest session for this challenge
        sessionApi.getByChallenge(challengeId).then((sess) => {
          if (cancelled) return
          setSession(sess)
          connectWS(sess.id)
          loadHistory(sess.id)
          checkRunning(sess.id)
        }).catch(() => {
          if (!cancelled) reset()
        })
      })
    } else if (session && session.challenge_id === challengeId) {
      // If we have a persisted session for this challenge, reconnect
      connectWS(session.id)
      loadHistory(session.id)
      checkRunning(session.id)
    } else {
      // Try to recover session from backend (e.g. after page refresh / new tab)
      sessionApi.getByChallenge(challengeId).then((sess) => {
        if (cancelled) return
        setSession(sess)
        connectWS(sess.id)
        loadHistory(sess.id)
        checkRunning(sess.id)
      }).catch(() => {
        // No existing session — clear stale state
        if (!cancelled) reset()
      })
    }

    return () => {
      cancelled = true
      disconnectWS()
    }
  }, [challengeId, hasHydrated, requestedSessionId])

  // Listen for writeup generation, persistent solve, and reflection events via WebSocket
  useEffect(() => {
    const currentSessionId = session?.id
    const unsubGenerating = wsService.on('writeup_generating', (event) => {
      if (currentSessionId && event.session_id && event.session_id !== currentSessionId) return
      setWriteupLoading(true)
    })
    const unsubGenerated = wsService.on('writeup_generated', (event) => {
      if (currentSessionId && event.session_id && event.session_id !== currentSessionId) return
      setWriteupLoading(false)
      if (event.content) {
        setWriteup(event.content)
      }
    })
    const unsubComplete = wsService.on('persistent_complete', (event) => {
      if (event.challenge_id === challengeId) {
        setPersistentRunning(false)
      }
    })
    const unsubReflectionGenerating = wsService.on('reflection_generating', (event) => {
      if (currentSessionId && event.session_id && event.session_id !== currentSessionId) return
      if (event.content === 'generate_failed') {
        setReflectionLoading(false)
      } else {
        setReflectionLoading(true)
      }
    })
    const unsubReflection = wsService.on('post_solve_reflection', (event) => {
      if (currentSessionId && event.session_id && event.session_id !== currentSessionId) return
      setReflectionLoading(false)
      if (event.content) {
        try {
          const parsed = typeof event.content === 'string' ? JSON.parse(event.content) : event.content
          setReflection(parsed)
          // Auto-switch to reflection tab when result arrives
          setActivePanel('reflection')
        } catch {
          // If not JSON, store as raw string in an object
          setReflection({ raw: event.content })
        }
      }
    })
    return () => {
      unsubGenerating()
      unsubGenerated()
      unsubComplete()
      unsubReflectionGenerating()
      unsubReflection()
    }
  }, [challengeId, session?.id])

  const startFreshSession = useCallback(async (interactive = false) => {
    if (!challengeId) return
    setLoading(true)
    setError(null)
    reset()
    setTerminalId(null)
    setWriteup(null)
    setReflection(null)
    setPersistentRunning(false)
    try {
      const sess = await sessionApi.create(challengeId, selectedModel)
      setSession(sess)
      connectWS(sess.id)
      sessionApi.createTerminal(sess.id)
        .then(r => setTerminalId(r.terminal_id))
        .catch(e => console.warn('Terminal creation failed:', e))
      const result = await agentApi.solve(challengeId, sess.id, selectedModel, utilityModel, interactive)
      setAgentId(result.agent_id || null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [challengeId, selectedModel, utilityModel])

  const handleStart = useCallback(async () => {
    await startFreshSession(false)
  }, [startFreshSession])

  const handleStartInteractive = useCallback(async () => {
    await startFreshSession(true)
  }, [startFreshSession])

  const handleStop = useCallback(async () => {
    // Read agentId fresh from the store to avoid stale closure
    const currentAgentId = useAgentStore.getState().agentId
    if (!currentAgentId) return
    try {
      await agentApi.stop(currentAgentId)
    } catch (e) {
      console.error('Failed to stop:', e)
    }
  }, [])

  const handleContinue = useCallback(async () => {
    if (!session) return
    setLoading(true)
    setError(null)
    try {
      connectWS(session.id)
      const result = await agentApi.continue(session.id, selectedModel, undefined, utilityModel)
      setAgentId(result.agent_id || null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [session, selectedModel, utilityModel])

  const handleRedo = useCallback(async () => {
    if (!challengeId) return
    // Stop current agent if running
    const currentAgentId = useAgentStore.getState().agentId
    if (currentAgentId) {
      try { await agentApi.stop(currentAgentId) } catch { /* ignore */ }
    }
    await startFreshSession(false)
  }, [challengeId, startFreshSession])

  const handleBranch = useCallback(async () => {
    if (!session) return
    try {
      const messages = await sessionApi.messages(session.id)
      const branchSess = await sessionApi.branch(session.id, messages.length)
      setSession(branchSess)
      connectWS(branchSess.id)
      await loadHistory(branchSess.id)
    } catch (e) {
      console.error('Branch failed:', e)
    }
  }, [session])

  const handlePersistentSolve = useCallback(async () => {
    if (!challengeId) return
    setError(null)
    try {
      await agentApi.persistentSolve(challengeId, selectedModel, utilityModel)
      setPersistentRunning(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [challengeId, selectedModel, utilityModel])

  const handlePersistentStop = useCallback(async () => {
    if (!challengeId) return
    try {
      await agentApi.persistentStop(challengeId)
      setPersistentRunning(false)
    } catch (e) {
      console.error('Failed to stop persistent solve:', e)
    }
  }, [challengeId])

  const handleStartArena = useCallback(async () => {
    if (!challengeId || !arenaModelB) return
    setError(null)
    setShowArenaModal(false)
    try {
      await startArena(challengeId, selectedModel, arenaModelB, utilityModel)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [challengeId, selectedModel, arenaModelB, utilityModel, startArena])

  const handleStopArena = useCallback(async () => {
    if (!arenaEntry) return
    try {
      await stopArena(arenaEntry.arenaId)
    } catch (e) {
      console.error('Failed to stop arena:', e)
    }
  }, [arenaEntry, stopArena])

  const handleGenerateWriteup = useCallback(async () => {
    if (!challengeId) return
    setWriteupLoading(true)
    try {
      await challengeApi.generateWriteup(challengeId, selectedModel)
    } catch (e) {
      console.error('Failed to generate writeup:', e)
      setWriteupLoading(false)
    }
  }, [challengeId, selectedModel])

  const handleGenerateReflection = useCallback(async () => {
    if (!challengeId) return
    setReflectionLoading(true)
    try {
      await challengeApi.generateReflection(challengeId)
    } catch (e) {
      console.error('Failed to generate reflection:', e)
      setReflectionLoading(false)
    }
  }, [challengeId])

  if (!challenge) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        加载题目中...
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-surface-50">
      {/* ── Header ── */}
      <div className="flex-shrink-0 bg-white/80 backdrop-blur-xl border-b border-gray-200 shadow-sm">
        {/* Row 1: Navigation + Title + Meta */}
        <div className="flex items-center gap-3 px-4 py-2.5">
          <button
            onClick={() => {
              if (challenge?.competition_id) {
                navigate(`/competitions/${challenge.competition_id}`)
              } else {
                navigate('/competitions')
              }
            }}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5">
              <h1 className="text-sm font-semibold text-gray-900 truncate">{challenge.title}</h1>
              <span className={`badge-${challenge.category}`}>{challenge.category}</span>
              {challenge.status === 'solved' && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-50 text-green-600 border border-green-200">
                  <Flag className="w-2.5 h-2.5" />
                  已解决
                </span>
              )}
              {challenge.platform && (
                <span className="text-[10px] text-gray-400">{challenge.platform}</span>
              )}
            </div>
          </div>

          {/* Utility buttons (right) */}
          <div className="flex items-center gap-1">
            {session && !isRunning && (
              <>
                <button onClick={handleBranch} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors" title="分支会话">
                  <GitBranch className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={async () => {
                    if (!session || !confirm('确定要清除当前会话的所有历史记录吗？此操作不可撤销。')) return
                    try {
                      await sessionApi.delete(session.id)
                      disconnectWS()
                      reset()
                    } catch (err) {
                      console.error('Failed to delete session:', err)
                    }
                  }}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  title="清除历史记录"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
            <button
              onClick={async () => {
                setPromptLoading(true)
                setShowPromptModal(true)
                try {
                  if (session) {
                    const msgs = await sessionApi.messages(session.id)
                    const sys = msgs?.find((m: { role: string; content: string }) => m.role === 'system')
                    setPromptContent(sys?.content || '（未找到系统提示词）')
                  } else if (challengeId) {
                    const result = await challengeApi.getPromptPreview(challengeId)
                    setPromptContent(result?.prompt || '（无法生成提示词预览）')
                  }
                } catch {
                  setPromptContent('加载失败，请重试')
                } finally {
                  setPromptLoading(false)
                }
              }}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              title={session ? '查看系统提示词' : '预览系统提示词'}
            >
              <ScrollText className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Row 2: Action buttons */}
        <div className="flex items-center gap-2 px-4 pb-2.5">
          {/* 解题模型选择 */}
          <div className="flex items-center gap-1.5">
            <BrainCircuit className="w-3.5 h-3.5 text-gray-400" />
            <select
              value={selectedModel}
              onChange={(e) => setModel(e.target.value)}
              disabled={loading || isRunning || persistentRunning || !!arenaEntry?.running}
              title="选择解题使用的模型"
              className="text-xs rounded-lg border border-gray-200 bg-white text-gray-700
                px-2 py-1.5 max-w-[180px] truncate
                hover:border-gray-300 focus:outline-none focus:ring-1 focus:ring-blue-300
                disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {providers.length === 0 && (
                <option value={selectedModel}>{selectedModel || '默认模型'}</option>
              )}
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.model})
                </option>
              ))}
            </select>
          </div>

          <div className="w-px h-5 bg-gray-200" />

          {arenaEntry?.running ? (
            <button onClick={handleStopArena} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 transition-colors font-medium">
              <Square className="w-3 h-3" />
              停止竞技场
            </button>
          ) : persistentRunning ? (
            <button onClick={handlePersistentStop} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 transition-colors font-medium">
              <Square className="w-3 h-3" />
              停止死磕
            </button>
          ) : isRunning ? (
            <button onClick={handleStop} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 transition-colors font-medium">
              <Square className="w-3 h-3" />
              停止
            </button>
          ) : session && challenge.status !== 'solved' ? (
            <>
              <button
                onClick={handleContinue}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-gradient-to-r from-blue-500 to-indigo-500 text-white
                  hover:from-blue-600 hover:to-indigo-600
                  disabled:opacity-50 transition-all shadow-sm font-medium"
              >
                <FastForward className="w-3 h-3" />
                {loading ? '启动中...' : '继续'}
              </button>
              <button
                onClick={handleRedo}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-gray-50 border border-gray-200 text-gray-600
                  hover:bg-gray-100 transition-colors font-medium"
              >
                <RotateCcw className="w-3 h-3" />
                重做
              </button>
              <button
                onClick={handleStartInteractive}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-emerald-50 border border-emerald-200 text-emerald-600
                  hover:bg-emerald-100 transition-colors font-medium"
                title="AI 遇到不确定的地方会主动向你提问"
              >
                <MessageCircleQuestion className="w-3 h-3" />
                可交互
              </button>

              <div className="w-px h-5 bg-gray-200" />

              <button
                onClick={handlePersistentSolve}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-red-50 border border-red-200 text-red-500
                  hover:bg-red-100 transition-colors font-medium"
                title="不找到 flag 绝不停止"
              >
                <Skull className="w-3 h-3" />
                死磕
              </button>
              <button
                onClick={() => { fetchProviders(); setShowArenaModal(true) }}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-amber-50 border border-amber-200 text-amber-600
                  hover:bg-amber-100 transition-colors font-medium"
                title="两个模型同时做题，谁先拿到 flag 谁赢"
              >
                <Swords className="w-3 h-3" />
                竞技场
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleStart}
                disabled={loading}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs rounded-lg
                  bg-gradient-to-r from-blue-500 to-indigo-500 text-white
                  hover:from-blue-600 hover:to-indigo-600
                  disabled:opacity-50 transition-all shadow-sm font-medium"
              >
                <Play className="w-3 h-3" />
                {loading ? '启动中...' : session ? '重做' : '开始解题'}
              </button>
              <button
                onClick={handleStartInteractive}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-emerald-50 border border-emerald-200 text-emerald-600
                  hover:bg-emerald-100 transition-colors font-medium"
                title="AI 遇到不确定的地方会主动向你提问"
              >
                <MessageCircleQuestion className="w-3 h-3" />
                可交互
              </button>

              <div className="w-px h-5 bg-gray-200" />

              <button
                onClick={handlePersistentSolve}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-red-50 border border-red-200 text-red-500
                  hover:bg-red-100 transition-colors font-medium"
                title="不找到 flag 绝不停止"
              >
                <Skull className="w-3 h-3" />
                死磕
              </button>
              <button
                onClick={() => { fetchProviders(); setShowArenaModal(true) }}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                  bg-amber-50 border border-amber-200 text-amber-600
                  hover:bg-amber-100 transition-colors font-medium"
                title="两个模型同时做题，谁先拿到 flag 谁赢"
              >
                <Swords className="w-3 h-3" />
                竞技场
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-4 mt-2 flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
          <Shield className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Panel Tabs */}
      <div className="flex items-center gap-0.5 px-4 py-1.5 border-b border-gray-200 bg-white/60 backdrop-blur-sm">
        {[
          { key: 'chat' as Panel, icon: MessageSquare, label: '对话' },
          { key: 'terminal' as Panel, icon: Terminal, label: '终端' },
          { key: 'ideas' as Panel, icon: Lightbulb, label: '点子' },
          { key: 'findings' as Panel, icon: Key, label: '发现' },
          { key: 'progress' as Panel, icon: FileBarChart, label: '进度' },
          { key: 'topology' as Panel, icon: GitBranch, label: '拓扑' },
          { key: 'writeup' as Panel, icon: FileText, label: 'Writeup' },
          { key: 'reflection' as Panel, icon: BrainCircuit, label: '反思', badge: reflection != null },
          { key: 'info' as Panel, icon: Info, label: '详情' },
        ].map(({ key, icon: Icon, label, badge }) => (
          <button
            key={key}
            onClick={() => setActivePanel(key)}
            className={`relative flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
              activePanel === key
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
            }`}
          >
            <Icon className={`w-3.5 h-3.5 ${activePanel === key ? '' : 'group-hover:scale-110'} transition-transform`} />
            {label}
            {badge && activePanel !== key && (
              <span className="absolute top-1 right-1 w-1.5 h-1.5 bg-blue-500 rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {/* Keep ChatPanel always mounted to preserve state; hide with CSS */}
        <div className={activePanel === 'chat' ? 'h-full' : 'hidden'}>
          <ChatPanel />
        </div>
        {activePanel === 'terminal' && session && (
          <TerminalView sessionId={session.id} terminalId={terminalId} />
        )}
        {activePanel === 'terminal' && !session && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
            <Terminal className="w-8 h-8 opacity-30" />
            <span className="text-sm">开始解题后可使用终端</span>
          </div>
        )}
        {activePanel === 'ideas' && challengeId && (
          <IdeasPanel challengeId={challengeId} />
        )}
        {activePanel === 'findings' && challengeId && (
          <KeyFindingsPanel challengeId={challengeId} />
        )}
        {activePanel === 'progress' && challengeId && (
          <ProgressReportPanel challengeId={challengeId} isRunning={isRunning} />
        )}
        {activePanel === 'topology' && (
          <AgentTopologyPanel
            sessionId={session?.id}
            challengeId={challengeId}
            onOpenSession={(nextSessionId) => {
              navigate(`/solve/${challengeId}?session=${encodeURIComponent(nextSessionId)}`)
              setActivePanel('chat')
            }}
          />
        )}
        {activePanel === 'info' && <ChallengeInfo challenge={challenge} />}
        {activePanel === 'writeup' && (
          <WriteupPanel
            writeup={writeup}
            loading={writeupLoading}
            challengeId={challengeId || ''}
            title={challenge?.title || 'Writeup'}
            onGenerate={handleGenerateWriteup}
          />
        )}
        {activePanel === 'reflection' && (
          <ReflectionPanel reflection={reflection} loading={reflectionLoading} onGenerate={handleGenerateReflection} />
        )}
      </div>

      {/* TodoList + Status Bar */}
      <TodoListPanel />
      <AgentStatusBar />

      {/* System Prompt Modal */}
      {showPromptModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setShowPromptModal(false)}
        >
          <div
            className="relative bg-white rounded-2xl shadow-2xl w-[820px] max-w-[92vw] max-h-[82vh] flex flex-col border border-gray-200 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-indigo-50 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-lg bg-blue-100">
                  <ScrollText className="w-3.5 h-3.5 text-blue-600" />
                </div>
                <div>
                  <span className="text-sm font-semibold text-gray-900">
                    {session ? '系统提示词' : '系统提示词预览'}
                  </span>
                  {session ? (
                    <span className="text-[10px] text-gray-400 ml-2">
                      session: {session.id.slice(0, 8)}...
                    </span>
                  ) : (
                    <span className="text-[10px] text-amber-500 ml-2">
                      题目尚未开始，按当前配置生成
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => setShowPromptModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-5">
              {promptLoading ? (
                <div className="flex items-center justify-center h-32 text-gray-400 text-sm gap-2">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  加载中...
                </div>
              ) : (
                <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap leading-relaxed break-words">
                  {promptContent}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Arena Modal - Select second model */}
      {showArenaModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setShowArenaModal(false)}
        >
          <div
            className="relative bg-white rounded-2xl shadow-2xl w-[480px] max-w-[92vw] flex flex-col border border-gray-200 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-amber-50 to-orange-50 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-lg bg-amber-100">
                  <Swords className="w-3.5 h-3.5 text-amber-600" />
                </div>
                <span className="text-sm font-semibold text-gray-900">模型竞技场</span>
              </div>
              <button
                onClick={() => setShowArenaModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {/* Modal Body */}
            <div className="p-5 space-y-4">
              <p className="text-xs text-gray-500">
                两个模型同时解题，谁先拿到 flag 谁赢，另一个自动停止。
              </p>

              {/* Model A (current) */}
              <div>
                <label className="block text-[11px] font-medium text-gray-400 mb-1.5">主模型 (Model A)</label>
                <div className="flex items-center gap-2 px-3 py-2.5 bg-blue-50 border border-blue-200 rounded-xl text-xs font-mono text-blue-700">
                  <Shield className="w-3 h-3" />
                  {selectedModel || '默认模型'}
                </div>
              </div>

              {/* Model B selection */}
              <div>
                <label className="block text-[11px] font-medium text-gray-400 mb-1.5">挑战者模型 (Model B)</label>
                <select
                  value={arenaModelB}
                  onChange={(e) => setArenaModelB(e.target.value)}
                  className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-xl text-xs
                    focus:ring-2 focus:ring-amber-100 focus:border-amber-300 outline-none transition-all"
                >
                  <option value="">选择模型...</option>
                  {providers
                    .filter((p) => p.name !== selectedModel)
                    .map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name} ({p.model})
                      </option>
                    ))}
                </select>
              </div>

              {/* Launch button */}
              <button
                onClick={handleStartArena}
                disabled={!arenaModelB}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-medium
                  bg-gradient-to-r from-amber-500 to-orange-500 text-white
                  hover:from-amber-600 hover:to-orange-600
                  disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
              >
                <Swords className="w-3.5 h-3.5" />
                开始竞技
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Arena Status Banner */}
      {arenaEntry && (
        <div className={`mx-4 mt-2 px-4 py-3 rounded-lg border text-sm ${
          arenaEntry.running
            ? 'bg-amber-50 border-amber-200 [html.theme-dark_&]:bg-amber-900/20 [html.theme-dark_&]:border-amber-700'
            : arenaEntry.flag
              ? 'bg-green-50 border-green-200 [html.theme-dark_&]:bg-green-900/20 [html.theme-dark_&]:border-green-700'
              : 'bg-gray-50 border-gray-200 [html.theme-dark_&]:bg-gray-800 [html.theme-dark_&]:border-gray-700'
        }`}>
          <div className="flex items-center gap-2 mb-2">
            <Swords className={`w-4 h-4 ${arenaEntry.running ? 'text-amber-600 animate-pulse' : arenaEntry.flag ? 'text-green-600' : 'text-gray-500'}`} />
            <span className="font-medium">
              {arenaEntry.running ? '竞技场进行中...' : arenaEntry.flag ? '竞技场结束 — 找到 Flag!' : '竞技场结束'}
            </span>
            {arenaEntry.winner && (
              <span className="ml-auto text-xs font-medium px-2 py-0.5 rounded bg-amber-100 text-amber-700 [html.theme-dark_&]:bg-amber-800 [html.theme-dark_&]:text-amber-300">
                🏆 {arenaEntry.winner}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            {arenaEntry.results.map((slot, i) => (
              <div key={i} className={`px-3 py-2 rounded-lg border ${
                slot.status === 'won'
                  ? 'border-green-300 bg-green-50 [html.theme-dark_&]:bg-green-900/20 [html.theme-dark_&]:border-green-700'
                  : slot.status === 'running'
                    ? 'border-amber-200 bg-amber-50/50 [html.theme-dark_&]:bg-amber-900/10 [html.theme-dark_&]:border-amber-800'
                    : 'border-gray-200 bg-gray-50/50 [html.theme-dark_&]:bg-gray-800 [html.theme-dark_&]:border-gray-700'
              }`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs">{slot.model}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    slot.status === 'won' ? 'bg-green-100 text-green-700' :
                    slot.status === 'running' ? 'bg-amber-100 text-amber-700' :
                    slot.status === 'lost' ? 'bg-gray-100 text-gray-500' :
                    'bg-red-100 text-red-700'
                  }`}>
                    {slot.status === 'won' ? '✓ 获胜' :
                     slot.status === 'running' ? '运行中' :
                     slot.status === 'lost' ? '落败' :
                     slot.status === 'stopped' ? '已停止' : '失败'}
                  </span>
                </div>
                {slot.session_id && (
                  <button
                    onClick={() => {
                      if (slot.session_id) {
                        navigate(`/solve/${challengeId}?session=${slot.session_id}`)
                      }
                    }}
                    className="mt-1 text-xs text-primary-600 hover:text-primary-700 underline"
                  >
                    查看会话
                  </button>
                )}
              </div>
            ))}
          </div>
          {arenaEntry.durationMs > 0 && (
            <div className="mt-2 text-xs text-gray-500">
              总耗时: {Math.round(arenaEntry.durationMs / 1000)}s
            </div>
          )}
        </div>
      )}

    </div>
  )
}

function ChallengeInfo({ challenge }: { challenge: Challenge }) {
  return (
    <div className="p-6 space-y-5 overflow-y-auto max-h-full">
      {/* Meta grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetaCard icon={Tag} label="分类" value={challenge.category} color="purple" />
        <MetaCard icon={Shield} label="平台" value={challenge.platform || '—'} color="blue" />
        <MetaCard icon={Award} label="状态" value={
          challenge.status === 'solved' ? '已解决' :
          challenge.status === 'in_progress' ? '进行中' : '未开始'
        } color={challenge.status === 'solved' ? 'green' : challenge.status === 'in_progress' ? 'amber' : 'gray'} />
        {challenge.url && (
          <div className="col-span-2 md:col-span-3 flex items-center gap-2 px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200">
            <ExternalLink className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            <a
              href={challenge.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:text-blue-700 underline truncate"
            >
              {challenge.url}
            </a>
          </div>
        )}
        <MetaCard icon={Clock} label="创建时间" value={new Date(challenge.created_at).toLocaleString()} color="gray" />
        {challenge.solved_at && (
          <MetaCard icon={Flag} label="解决时间" value={new Date(challenge.solved_at).toLocaleString()} color="green" />
        )}
      </div>

      {challenge.description && (
        <div className="rounded-xl bg-white border border-gray-200 overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100">
            <h3 className="text-xs font-semibold text-gray-500">题目描述</h3>
          </div>
          <div className="px-4 py-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
            {challenge.description}
          </div>
        </div>
      )}

      {challenge.attachments?.length > 0 && (
        <div className="rounded-xl bg-white border border-gray-200 overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100">
            <h3 className="text-xs font-semibold text-gray-500 flex items-center gap-1.5">
              <Paperclip className="w-3 h-3" />
              附件 ({challenge.attachments.length})
            </h3>
          </div>
          <div className="p-3 space-y-1.5">
            {challenge.attachments.map((a, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-gray-600 font-mono bg-gray-50 rounded-lg px-3 py-2 border border-gray-100">
                <FileText className="w-3 h-3 text-gray-400 shrink-0" />
                {a}
              </div>
            ))}
          </div>
        </div>
      )}

      {challenge.flag && (
        <div className="rounded-xl bg-green-50 border border-green-200 overflow-hidden">
          <div className="px-4 py-2.5 bg-green-100/50 border-b border-green-200">
            <h3 className="text-xs font-semibold text-green-600 flex items-center gap-1.5">
              <Flag className="w-3 h-3" />
              Flag
            </h3>
          </div>
          <div className="px-4 py-3 text-sm text-green-700 font-mono">
            {challenge.flag}
          </div>
        </div>
      )}
    </div>
  )
}

function MetaCard({ icon: Icon, label, value, color }: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  color: 'purple' | 'blue' | 'green' | 'amber' | 'gray' | 'red'
}) {
  const colorMap = {
    purple: 'bg-purple-50 border-purple-100 text-purple-600',
    blue: 'bg-blue-50 border-blue-100 text-blue-600',
    green: 'bg-green-50 border-green-100 text-green-600',
    amber: 'bg-amber-50 border-amber-100 text-amber-600',
    gray: 'bg-gray-50 border-gray-100 text-gray-500',
    red: 'bg-red-50 border-red-100 text-red-600',
  }
  const iconColorMap = {
    purple: 'text-purple-400', blue: 'text-blue-400', green: 'text-green-400',
    amber: 'text-amber-400', gray: 'text-gray-400', red: 'text-red-400',
  }
  return (
    <div className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border ${colorMap[color]}`}>
      <Icon className={`w-3.5 h-3.5 ${iconColorMap[color]} shrink-0`} />
      <div className="min-w-0">
        <p className="text-[10px] text-gray-400 leading-none mb-0.5">{label}</p>
        <p className="text-xs font-medium truncate">{value}</p>
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-xs text-gray-400 w-20 flex-shrink-0">{label}</span>
      <span className="text-sm text-gray-700">{value}</span>
    </div>
  )
}

function WriteupPanel({ writeup, loading, challengeId, title, onGenerate }: { writeup: string | null; loading: boolean; challengeId: string; title: string; onGenerate: () => void }) {
  const contentRef = useRef<HTMLDivElement>(null)

  const exportPDF = () => {
    if (!contentRef.current) return
    const html = contentRef.current.innerHTML
    const safeTitle = title.replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const win = window.open('', '_blank', 'width=960,height=800')
    if (!win) { alert('请允许弹出窗口以导出 PDF'); return }
    win.document.write(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${safeTitle} — Writeup</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #1f2937; padding: 40px 56px; max-width: 960px; margin: 0 auto; }
    .pdf-header { display: flex; align-items: center; gap: 12px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 28px; }
    .pdf-header-badge { background: #4f46e5; color: #fff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 99px; letter-spacing: 0.05em; }
    .pdf-header-title { font-size: 1.25rem; font-weight: 700; color: #111827; flex: 1; }
    .pdf-header-date { font-size: 11px; color: #9ca3af; }
    h1 { font-size: 1.65rem; font-weight: 700; margin: 1.2rem 0 0.6rem; color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
    h2 { font-size: 1.3rem; font-weight: 700; margin: 1.1rem 0 0.5rem; color: #1f2937; }
    h3 { font-size: 1.1rem; font-weight: 600; margin: 0.9rem 0 0.4rem; color: #374151; }
    h4 { font-size: 1rem; font-weight: 600; margin: 0.8rem 0 0.3rem; color: #4b5563; }
    p { margin: 0 0 0.75rem; }
    ul, ol { padding-left: 1.6rem; margin: 0 0 0.75rem; }
    li { margin-bottom: 0.25rem; }
    code { background: #f3f4f6; padding: 0.12em 0.4em; border-radius: 4px; font-family: 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace; font-size: 0.83em; color: #4338ca; }
    pre { background: #1e1e2e; border-radius: 8px; padding: 1rem 1.2rem; margin: 0.75rem 0 1rem; overflow-x: auto; border: 1px solid #2d2d3f; }
    pre code { background: transparent; color: #cdd6f4; padding: 0; font-size: 0.8em; white-space: pre; }
    blockquote { border-left: 4px solid #6366f1; margin: 0.75rem 0; padding: 0.5rem 1rem; background: #f5f3ff; color: #4b5563; border-radius: 0 6px 6px 0; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: 0.9em; }
    th { background: #f9fafb; border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; text-align: left; font-weight: 600; color: #374151; }
    td { border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; }
    tr:nth-child(even) td { background: #f9fafb; }
    a { color: #4f46e5; text-decoration: underline; }
    img { max-width: 100%; border-radius: 6px; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0; }
    /* highlight.js dracula-inspired */
    .hljs-keyword,.hljs-selector-tag,.hljs-tag { color: #ff79c6; }
    .hljs-string,.hljs-attr { color: #f1fa8c; }
    .hljs-comment,.hljs-quote { color: #6272a4; font-style: italic; }
    .hljs-number,.hljs-literal { color: #bd93f9; }
    .hljs-title,.hljs-name,.hljs-function { color: #50fa7b; }
    .hljs-built_in,.hljs-type { color: #8be9fd; }
    .hljs-variable,.hljs-params { color: #f8f8f2; }
    .hljs-operator,.hljs-punctuation { color: #ff79c6; }
    @media print {
      body { padding: 0; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      pre { white-space: pre-wrap; break-inside: avoid; }
      h1,h2,h3 { break-after: avoid; }
    }
  </style>
</head>
<body>
  <div class="pdf-header">
    <span class="pdf-header-badge">CTF WRITEUP</span>
    <span class="pdf-header-title">${safeTitle}</span>
    <span class="pdf-header-date">${new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</span>
  </div>
  ${html}
  <script>window.onload = () => { window.focus(); window.print(); }<\/script>
</body>
</html>`)
    win.document.close()
  }
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-3">
        <div className="relative w-10 h-10">
          <div className="absolute inset-0 rounded-full border-2 border-blue-100" />
          <div className="absolute inset-0 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
        </div>
        <span className="text-xs">正在生成 Writeup...</span>
      </div>
    )
  }

  if (!writeup) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-3">
        <div className="p-3 rounded-2xl bg-gray-50">
          <FileEdit className="w-7 h-7 text-gray-300" />
        </div>
        <span className="text-xs">解题完成后将自动生成 Writeup</span>
        <button
          onClick={onGenerate}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-medium
            bg-gradient-to-r from-blue-500 to-indigo-500 text-white
            hover:from-blue-600 hover:to-indigo-600 transition-all shadow-sm"
        >
          <FileEdit className="w-3.5 h-3.5" />
          手动生成 Writeup
        </button>
      </div>
    )
  }

  return (
    <div className="p-5 overflow-y-auto max-h-full">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded-lg bg-indigo-50">
            <FileEdit className="w-3.5 h-3.5 text-indigo-500" />
          </div>
          <span className="text-xs font-semibold text-gray-700">Writeup</span>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={exportPDF}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium
              text-gray-500 bg-gray-50 hover:bg-gray-100 border border-gray-200 transition-colors"
            title="导出为 PDF"
          >
            <FileDown className="w-3 h-3" />
            导出 PDF
          </button>
          <button
            onClick={onGenerate}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium
              text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 transition-colors"
            title="重新生成 Writeup"
          >
            <RotateCcw className="w-3 h-3" />
            重新生成
          </button>
        </div>
      </div>
      <div ref={contentRef} className="prose prose-sm max-w-none">
        <MarkdownRenderer content={writeup} />
      </div>
    </div>
  )
}

function ReflectionPanel({ reflection, loading, onGenerate }: { reflection: Record<string, unknown> | null; loading?: boolean; onGenerate?: () => void }) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-3">
        <div className="relative w-10 h-10">
          <div className="absolute inset-0 rounded-full border-2 border-purple-100" />
          <div className="absolute inset-0 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
        </div>
        <span className="text-xs">正在生成反思报告...</span>
      </div>
    )
  }

  if (!reflection) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-3 text-sm">
        <div className="p-3 rounded-2xl bg-gray-50">
          <BrainCircuit className="w-7 h-7 text-gray-300" />
        </div>
        <span className="text-xs">解题结束后将自动生成反思报告</span>
        {onGenerate && (
          <button onClick={onGenerate} className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-medium
            bg-gradient-to-r from-purple-500 to-violet-500 text-white
            hover:from-purple-600 hover:to-violet-600 transition-all shadow-sm">
            <RotateCcw className="w-3.5 h-3.5" />
            手动生成反思
          </button>
        )}
      </div>
    )
  }

  // Render raw string fallback
  if (reflection.raw) {
    return (
      <div className="p-5 overflow-y-auto max-h-full">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1 rounded-lg bg-purple-50">
              <BrainCircuit className="w-3.5 h-3.5 text-purple-500" />
            </div>
            <span className="text-xs font-semibold text-gray-700">反思报告</span>
          </div>
          {onGenerate && (
            <button onClick={onGenerate} className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium
              text-purple-600 bg-purple-50 hover:bg-purple-100 border border-purple-200 transition-colors">
              <RotateCcw className="w-3 h-3" />
              重新生成
            </button>
          )}
        </div>
        <MarkdownRenderer content={String(reflection.raw)} />
      </div>
    )
  }

  const mistakes = reflection.key_mistakes as string[] | undefined
  const checklist = reflection.next_time_checklist as string[] | undefined
  const wastedRounds = reflection.wasted_rounds as string | undefined
  const correctApproach = reflection.correct_approach as string | undefined
  const categoryInsight = reflection.category_insight as string | undefined
  const solved = reflection.solved as boolean | undefined

  return (
    <div className="p-5 overflow-y-auto max-h-full space-y-3.5">
      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div className="p-1.5 rounded-lg bg-purple-50">
          <BrainCircuit className="w-4 h-4 text-purple-500" />
        </div>
        <h2 className="text-sm font-semibold text-gray-800">解题反思</h2>
        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${solved
          ? 'bg-gradient-to-r from-green-50 to-emerald-50 text-green-600 border border-green-200'
          : 'bg-gradient-to-r from-red-50 to-rose-50 text-red-600 border border-red-200'
        }`}>
          {solved ? '✓ 已解出' : '✗ 未解出'}
        </span>
        {onGenerate && (
          <button onClick={onGenerate} className="ml-auto flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium
            text-purple-600 bg-purple-50 hover:bg-purple-100 border border-purple-200 transition-colors">
            <RotateCcw className="w-3 h-3" />
            重新生成
          </button>
        )}
      </div>

      {mistakes && mistakes.length > 0 && (
        <div className="rounded-xl p-3.5 bg-gradient-to-br from-orange-50 to-amber-50 border border-orange-200">
          <h3 className="text-xs font-semibold text-orange-700 mb-2 flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5" />
            关键失误
          </h3>
          <ul className="space-y-1">
            {mistakes.map((m, i) => (
              <li key={i} className="text-xs text-orange-600 flex gap-2 leading-relaxed">
                <span className="text-orange-300 flex-shrink-0 mt-0.5">•</span>
                {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {wastedRounds && (
        <div className="rounded-xl p-3.5 bg-gradient-to-br from-gray-50 to-slate-50 border border-gray-200">
          <h3 className="text-xs font-semibold text-gray-600 mb-1.5 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            无效轮次分析
          </h3>
          <p className="text-xs text-gray-500 leading-relaxed">{wastedRounds}</p>
        </div>
      )}

      {correctApproach && (
        <div className="rounded-xl p-3.5 bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200">
          <h3 className="text-xs font-semibold text-blue-700 mb-1.5 flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5" />
            正确思路
          </h3>
          <p className="text-xs text-blue-600 leading-relaxed">{correctApproach}</p>
        </div>
      )}

      {checklist && checklist.length > 0 && (
        <div className="rounded-xl p-3.5 bg-gradient-to-br from-green-50 to-emerald-50 border border-green-200">
          <h3 className="text-xs font-semibold text-green-700 mb-2 flex items-center gap-1.5">
            <Award className="w-3.5 h-3.5" />
            下次清单
          </h3>
          <ul className="space-y-1">
            {checklist.map((c, i) => (
              <li key={i} className="text-xs text-green-600 flex gap-2 leading-relaxed">
                <span className="text-green-400 flex-shrink-0 mt-0.5">✓</span>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {categoryInsight && (
        <div className="rounded-xl p-3.5 bg-gradient-to-br from-purple-50 to-violet-50 border border-purple-200">
          <h3 className="text-xs font-semibold text-purple-700 mb-1.5 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5" />
            类别经验沉淀
          </h3>
          <p className="text-xs text-purple-600 leading-relaxed">{categoryInsight}</p>
        </div>
      )}
    </div>
  )
}
