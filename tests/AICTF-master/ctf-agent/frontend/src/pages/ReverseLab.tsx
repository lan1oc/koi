import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Cpu, Upload, History, Bot, Trash2,
  FileText, Type, Code, BarChart3,
  BookOpen, ChevronDown, X, Target,
  Play, Square, Shield, Layers, Fingerprint,
  RotateCcw, Zap, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react'
import { useReverseStore } from '../stores/reverseStore'
import { useAgentStore } from '../stores/agentStore'
import { useSettingsStore } from '../stores/settingsStore'
import { agentApi, sessionApi } from '../services/api'
import ChatPanel from '../components/ChatPanel'
import AgentStatusBar from '../components/AgentStatusBar'
import TodoListPanel from '../components/TodoListPanel'
import BinaryUploader from '../components/reverse/BinaryUploader'
import BinaryInfoCard from '../components/reverse/BinaryInfoCard'
import StringsTable from '../components/reverse/StringsTable'
import DecompileView from '../components/reverse/DecompileView'
import AlgorithmTable from '../components/reverse/AlgorithmTable'
import ReverseKnowledge from '../components/reverse/ReverseKnowledge'

type ReferenceTab = 'info' | 'strings' | 'decompile' | 'knowledge' | 'algorithms'

export default function ReverseLab() {
  const {
    binaries, selectedBinary, stringsResult, decompileTasks, algorithms,
    aiSessionId,
    loading, analyzing, uploading, error,
    loadBinaries, uploadBinary, selectBinary, clearSelection, deleteBinary,
    runAnalysis, loadStrings, startDecompile, pollDecompile,
    startAIAnalysis, loadAlgorithms,
  } = useReverseStore()

  const {
    session, isRunning, agentId,
    setSession, setAgentId, connectWS, disconnectWS, loadHistory, checkRunning, reset,
  } = useAgentStore()

  const { selectedModel, utilityModel } = useSettingsStore()

  const [refTab, setRefTab] = useState<ReferenceTab>('info')
  const [showHistory, setShowHistory] = useState(false)
  const [showUploader, setShowUploader] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [startingAgent, setStartingAgent] = useState(false)
  const [agentError, setAgentError] = useState<string | null>(null)
  const [showGoalModal, setShowGoalModal] = useState(false)
  const [goalText, setGoalText] = useState('')
  const goalInputRef = useRef<HTMLTextAreaElement>(null)

  const sidebarWidth = 340

  useEffect(() => {
    loadBinaries()
    loadAlgorithms()
  }, [loadBinaries, loadAlgorithms])

  // When we have an aiSessionId, connect agentStore to it so ChatPanel works
  // Reconnect to AI session on mount / page refresh (fallback path).
  // The primary connection is done immediately in handleStartAgent.
  useEffect(() => {
    if (!aiSessionId) return
    // If session is already set (from handleStartAgent), skip redundant fetch
    if (session && session.id === aiSessionId) return

    sessionApi.get(aiSessionId).then((sess) => {
      setSession(sess)
      connectWS(sess.id)
      loadHistory(sess.id)
      checkRunning(sess.id)
    }).catch((e) => {
      console.warn('Failed to load reverse AI session:', e)
    })

    return () => {
      disconnectWS()
    }
  }, [aiSessionId])

  const handleUpload = useCallback(async (file: File) => {
    try {
      // Reset agent store first so old session data doesn't linger
      disconnectWS()
      reset()
      await uploadBinary(file)
      setShowUploader(false)
      // After upload, show goal modal
      setGoalText('')
      setShowGoalModal(true)
      setTimeout(() => goalInputRef.current?.focus(), 100)
    } catch { /* error is set in store */ }
  }, [uploadBinary, disconnectWS, reset])

  // Start AI agent analysis (optionally with a goal message)
  const handleStartAgent = useCallback(async (message?: string) => {
    if (!selectedBinary) return
    setStartingAgent(true)
    setAgentError(null)
    try {
      // Reset agent store to clear any stale session data
      disconnectWS()
      reset()

      const sessionId = await startAIAnalysis(selectedBinary.id, {
        model: selectedModel,
        message: message || undefined,
      })

      // Immediately set session and connect WS — no async useEffect delay.
      // This prevents the race condition where the agent emits events
      // before the frontend WS handler is subscribed to the correct session.
      const sess = await sessionApi.get(sessionId)
      setSession(sess)
      connectWS(sess.id)
      loadHistory(sess.id)
      checkRunning(sess.id)
    } catch (e: any) {
      setAgentError(e.message)
    } finally {
      setStartingAgent(false)
    }
  }, [selectedBinary, startAIAnalysis, selectedModel, disconnectWS, reset, setSession, connectWS, loadHistory, checkRunning])

  // Confirm goal and start agent
  const handleGoalConfirm = useCallback(() => {
    setShowGoalModal(false)
    const msg = goalText.trim()
    handleStartAgent(msg || undefined)
  }, [goalText, handleStartAgent])

  // Skip goal — start without extra context
  const handleGoalSkip = useCallback(() => {
    setShowGoalModal(false)
    handleStartAgent()
  }, [handleStartAgent])

  // Continue / send additional instructions to agent
  const handleContinueAgent = useCallback(async (message?: string) => {
    if (!session) return
    try {
      const result = await agentApi.continue(session.id, selectedModel, message, utilityModel)
      setAgentId(result.agent_id || null)
    } catch (e: any) {
      setAgentError(e.message)
    }
  }, [session, selectedModel, utilityModel, setAgentId])

  // Stop running agent
  const handleStopAgent = useCallback(async () => {
    if (!agentId) return
    try {
      await agentApi.stop(agentId)
    } catch { /* ignore */ }
  }, [agentId])

  // Reference tabs config
  const refTabs: { key: ReferenceTab; icon: typeof BarChart3; label: string }[] = [
    { key: 'info',       icon: BarChart3, label: '信息' },
    { key: 'strings',    icon: Type,      label: '字串' },
    { key: 'decompile',  icon: Code,      label: '反编' },
    { key: 'knowledge',  icon: BookOpen,  label: '知识' },
    { key: 'algorithms', icon: Layers,    label: '算法' },
  ]

  // ─── No binary selected: welcome & upload ───
  if (!selectedBinary) {
    return (
      <div className="flex flex-col h-full bg-surface-50">
        <div className="flex-1 flex flex-col items-center justify-center gap-6">
          <div className="relative">
            <div className="p-8 rounded-3xl bg-gradient-to-br from-purple-50 to-violet-50 border border-purple-100">
              <Cpu className="w-16 h-16 text-purple-400" />
            </div>
            <div className="absolute -bottom-2 -right-2 p-2 rounded-xl bg-green-50 border border-green-200">
              <Bot className="w-6 h-6 text-green-500" />
            </div>
          </div>
          <div className="text-center max-w-md">
            <h1 className="text-xl font-semibold text-gray-900">逆向工作台</h1>
            <p className="text-sm text-gray-500 mt-2">
              上传二进制文件，AI Agent 将自动完成分析、反编译、算法识别等全部逆向工作
            </p>
          </div>

          <div className="w-80">
            <BinaryUploader onUpload={handleUpload} uploading={uploading} />
          </div>

          {/* History quick access */}
          {binaries.length > 0 && (
            <div className="w-80">
              <p className="text-xs text-gray-400 mb-2">历史文件</p>
              <div className="flex flex-col gap-1.5 max-h-40 overflow-auto">
                {binaries.slice(0, 5).map((b) => (
                  <button
                    key={b.id}
                    onClick={() => selectBinary(b.id)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:border-purple-300 hover:bg-purple-50/50 transition-all text-left"
                  >
                    <FileText className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-gray-800 truncate">{b.name}</p>
                      <p className="text-[10px] text-gray-400">
                        {b.arch || '?'} · {b.packer_info?.packed ? `🔒 ${b.packer_info.type}` : '无壳'}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="px-4 py-2 bg-red-50 border-t border-red-200 text-xs text-red-700">{error}</div>
        )}
      </div>
    )
  }

  // ─── Binary selected: Agent workspace ───
  return (
    <div className="flex flex-col h-full bg-surface-50">
      {/* ── Top Toolbar ── */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-white/80 backdrop-blur-xl border-b border-gray-200 shadow-sm">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          title={sidebarOpen ? '收起参考面板' : '展开参考面板'}
        >
          {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
        </button>

        <div className="flex items-center gap-2 min-w-0">
          <Cpu className="w-4 h-4 text-purple-500 shrink-0" />
          <span className="text-sm font-medium text-gray-900 truncate max-w-[200px]" title={selectedBinary.name}>
            {selectedBinary.name}
          </span>
          <span className="text-[10px] text-gray-400 shrink-0">
            {selectedBinary.arch || '?'} · {selectedBinary.file_type || '?'}
          </span>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => setShowUploader(!showUploader)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg
              bg-gray-50 border border-gray-200 text-gray-500
              hover:bg-gray-100 transition-colors"
          >
            <Upload className="w-3 h-3" />
            上传
          </button>

          <div className="relative">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg
                bg-gray-50 border border-gray-200 text-gray-500 hover:bg-gray-100 transition-colors"
            >
              <History className="w-3 h-3" />
              历史
              <ChevronDown className="w-3 h-3" />
            </button>
            {showHistory && (
              <div className="absolute right-0 top-full mt-1 w-72 max-h-64 overflow-auto
                bg-white border border-gray-200 rounded-xl shadow-xl z-50">
                {binaries.length === 0 ? (
                  <p className="p-3 text-xs text-gray-400">暂无上传记录</p>
                ) : binaries.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => { selectBinary(b.id); setShowHistory(false) }}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors ${
                      selectedBinary?.id === b.id ? 'bg-purple-50' : ''
                    }`}
                  >
                    <FileText className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-gray-800 truncate">{b.name}</p>
                      <p className="text-[10px] text-gray-500">
                        {b.arch || '?'} · {b.packer_info?.packed ? `🔒 ${b.packer_info.type}` : '无壳'}
                      </p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteBinary(b.id) }}
                      className="p-1 text-gray-300 hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Agent control buttons */}
          {!aiSessionId ? (
            <button
              onClick={() => { setGoalText(''); setShowGoalModal(true); setTimeout(() => goalInputRef.current?.focus(), 100) }}
              disabled={startingAgent}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                bg-gradient-to-r from-purple-500 to-violet-500 text-white
                hover:from-purple-600 hover:to-violet-600
                disabled:opacity-50 transition-all shadow-sm"
            >
              {startingAgent ? (
                <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <Zap className="w-3.5 h-3.5" />
              )}
              AI 全自动分析
            </button>
          ) : (
            <>
              {isRunning ? (
                <button
                  onClick={handleStopAgent}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                    bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 transition-colors"
                >
                  <Square className="w-3 h-3" />
                  停止
                </button>
              ) : (
                <button
                  onClick={() => handleContinueAgent()}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                    bg-purple-50 border border-purple-200 text-purple-600 hover:bg-purple-100 transition-colors"
                >
                  <Play className="w-3 h-3" />
                  继续分析
                </button>
              )}
            </>
          )}

          <button
            onClick={() => { clearSelection(); reset() }}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg
              text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            换文件
          </button>
        </div>
      </div>

      {agentError && (
        <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-700">
          {agentError}
          <button onClick={() => setAgentError(null)} className="ml-2 underline">关闭</button>
        </div>
      )}
      {error && (
        <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-700">{error}</div>
      )}

      {showUploader && (
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
          <BinaryUploader onUpload={handleUpload} uploading={uploading} />
        </div>
      )}

      {/* ── Main workspace: Reference sidebar + AI Chat ── */}
      <div className="flex-1 flex min-h-0">

        {/* Left: Reference sidebar (collapsible) */}
        {sidebarOpen && (
          <div
            className="flex flex-col border-r border-gray-200 bg-gray-50/50 min-h-0"
            style={{ width: sidebarWidth, minWidth: sidebarWidth }}
          >
            {/* Reference tabs */}
            <div className="flex items-center gap-0.5 px-2 py-1.5 border-b border-gray-200 bg-white/60 overflow-x-auto scrollbar-none">
              {refTabs.map(({ key, icon: Icon, label }) => (
                <button
                  key={key}
                  onClick={() => setRefTab(key)}
                  className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded-md whitespace-nowrap transition-colors ${
                    refTab === key
                      ? 'bg-purple-50 text-purple-600 border border-purple-200'
                      : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <Icon className="w-3 h-3" />
                  {label}
                </button>
              ))}
            </div>

            {/* Reference content */}
            <div className="flex-1 overflow-auto p-3">
              {refTab === 'info' && (
                <BinaryInfoCard
                  binary={selectedBinary}
                  analyzing={analyzing}
                  onAnalyze={() => runAnalysis(selectedBinary.id)}
                />
              )}
              {refTab === 'strings' && (
                <StringsTable
                  result={stringsResult}
                  loading={loading}
                  onRefresh={(minLen) => loadStrings(selectedBinary.id, { min_len: minLen })}
                />
              )}
              {refTab === 'decompile' && (
                <DecompileView
                  tasks={decompileTasks}
                  binaryId={selectedBinary.id}
                  onDecompile={(f) => startDecompile(selectedBinary.id, f)}
                  onPoll={(taskId) => pollDecompile(selectedBinary.id, taskId)}
                />
              )}
              {refTab === 'knowledge' && <ReverseKnowledge />}
              {refTab === 'algorithms' && <AlgorithmTable algorithms={algorithms} loading={loading} />}
            </div>
          </div>
        )}

        {/* Right: AI Agent Chat (main area) */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Agent status bar */}
          <AgentStatusBar />

          {/* Chat or welcome prompt */}
          {aiSessionId && session ? (
            <div className="flex-1 min-h-0 flex flex-col">
              <ChatPanel />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center gap-5">
              <div className="p-5 rounded-2xl bg-gradient-to-br from-purple-50 to-violet-50 border border-purple-100">
                <Bot className="w-12 h-12 text-purple-400" />
              </div>
              <div className="text-center max-w-sm">
                <p className="text-sm font-medium text-gray-700">
                  点击「AI 全自动分析」开始逆向
                </p>
                <p className="text-xs text-gray-400 mt-1.5">
                  Agent 将自动执行：基础信息分析、字符串提取、反编译、算法识别、漏洞发现等全流程
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2 text-[10px] text-gray-400">
                {[
                  { icon: Shield, label: 'checksec 安全检查' },
                  { icon: Type, label: '字符串提取分析' },
                  { icon: Code, label: '反编译 & 伪代码' },
                  { icon: Fingerprint, label: '算法 & 加密识别' },
                  { icon: Layers, label: '控制流分析' },
                ].map(({ icon: Icon, label }) => (
                  <span key={label} className="flex items-center gap-1 px-2 py-1 rounded-md bg-gray-100 border border-gray-200">
                    <Icon className="w-3 h-3" />
                    {label}
                  </span>
                ))}
              </div>
              <button
                onClick={() => { setGoalText(''); setShowGoalModal(true); setTimeout(() => goalInputRef.current?.focus(), 100) }}
                disabled={startingAgent}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm
                  bg-gradient-to-r from-purple-500 to-violet-500 text-white
                  hover:from-purple-600 hover:to-violet-600
                  disabled:opacity-50 transition-all shadow-lg shadow-purple-200"
              >
                {startingAgent ? (
                  <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                ) : (
                  <Zap className="w-4 h-4" />
                )}
                开始 AI 全自动分析
              </button>
            </div>
          )}

          {/* Todo list panel if agent is working */}
          {aiSessionId && session && <TodoListPanel />}
        </div>
      </div>

      {showHistory && <div className="fixed inset-0 z-40" onClick={() => setShowHistory(false)} />}

      {/* ── Goal Modal ── */}
      {showGoalModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowGoalModal(false)} />

          {/* Modal */}
          <div className="relative w-full max-w-lg mx-4 bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-purple-50 to-violet-50">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-purple-100">
                  <Target className="w-4 h-4 text-purple-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">设定分析目标</h3>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {selectedBinary?.name || '二进制文件'} 已就绪
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowGoalModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="px-5 py-4">
              <label className="block text-xs font-medium text-gray-700 mb-2">
                这次逆向的目标是什么？
              </label>
              <textarea
                ref={goalInputRef}
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    handleGoalConfirm()
                  }
                }}
                placeholder="例：找到 flag、分析加密算法、定位漏洞点、还原程序逻辑..."
                rows={3}
                className="w-full px-3 py-2.5 text-sm rounded-xl border border-gray-200 bg-gray-50
                  focus:bg-white focus:border-purple-300 focus:ring-2 focus:ring-purple-100
                  placeholder:text-gray-400 resize-none outline-none transition-all"
              />
              <p className="text-[10px] text-gray-400 mt-1.5">
                提供明确目标可以让 AI 更高效地完成分析（也可跳过，由 AI 自行判断）
              </p>

              {/* Quick goal presets */}
              <div className="flex flex-wrap gap-1.5 mt-3">
                {[
                  '找到 Flag',
                  '分析加密算法',
                  '还原程序逻辑',
                  '定位漏洞 / 后门',
                  '脱壳并分析',
                  '提取关键字符串',
                ].map((preset) => (
                  <button
                    key={preset}
                    onClick={() => setGoalText(goalText ? `${goalText}\n${preset}` : preset)}
                    className="px-2.5 py-1 text-[11px] rounded-lg border border-gray-200
                      text-gray-500 hover:text-purple-600 hover:border-purple-200 hover:bg-purple-50
                      transition-colors"
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50/50">
              <button
                onClick={handleGoalSkip}
                className="px-4 py-1.5 text-xs rounded-lg text-gray-500 hover:text-gray-700
                  hover:bg-gray-100 transition-colors"
              >
                跳过，自动分析
              </button>
              <button
                onClick={handleGoalConfirm}
                disabled={startingAgent}
                className="flex items-center gap-1.5 px-4 py-1.5 text-xs rounded-lg
                  bg-gradient-to-r from-purple-500 to-violet-500 text-white
                  hover:from-purple-600 hover:to-violet-600
                  disabled:opacity-50 transition-all shadow-sm"
              >
                {startingAgent ? (
                  <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                ) : (
                  <Zap className="w-3.5 h-3.5" />
                )}
                开始分析
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
