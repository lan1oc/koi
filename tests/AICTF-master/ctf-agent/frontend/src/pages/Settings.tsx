import { useEffect, useState } from 'react'
import {
  Settings as SettingsIcon,
  Cpu,
  Monitor,
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  Eye,
  EyeOff,
  KeyRound,
  FolderOpen,
  Save,
  Loader2,
  ScanEye,
  Play,
  Cog,
  Database,
  Layers,
  ChevronRight,
} from 'lucide-react'
import { useSettingsStore } from '../stores/settingsStore'
import type { ProviderType } from '../types'
import { bootstrapApi, configApi } from '../services/api'

const providerTypes: { value: ProviderType; label: string; desc: string }[] = [
  { value: 'openai', label: 'OpenAI', desc: 'GPT-4o, GPT-4o-mini 等' },
  { value: 'anthropic', label: 'Anthropic (Claude)', desc: 'Claude Opus, Sonnet 等' },
  { value: 'openai_compat', label: 'OpenAI 兼容', desc: 'DeepSeek, 通义千问, 本地模型等' },
  { value: 'ollama', label: 'Ollama', desc: '本地 Ollama 服务' },
]

const defaultBaseURLs: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  openai_compat: '',
  ollama: 'http://localhost:11434',
}

type SettingsTab = 'general' | 'models' | 'agent' | 'tools'

const tabs: { id: SettingsTab; label: string; icon: React.ReactNode }[] = [
  { id: 'general', label: '通用', icon: <SettingsIcon className="w-4 h-4" /> },
  { id: 'models', label: '模型', icon: <Cpu className="w-4 h-4" /> },
  { id: 'agent', label: 'Agent', icon: <Cog className="w-4 h-4" /> },
  { id: 'tools', label: '工具', icon: <Layers className="w-4 h-4" /> },
]

export default function Settings() {
  const {
    showThinking,
    autoScroll,
    selectedModel,
    utilityModel,
    providers,
    workDir,
    toolDir,
    agentConfig,
    embeddingConfig,
    visionConfig,
    toggleThinking,
    toggleAutoScroll,
    setModel,
    setUtilityModel,
    fetchProviders,
    removeProvider,
    fetchConfig,
    setWorkDir,
    setToolDir,
    fetchAgentConfig,
    updateAgentConfig,
    fetchEmbeddingConfig,
    updateEmbeddingConfig,
    fetchVisionConfig,
    updateVisionConfig,
  } = useSettingsStore()

  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [showAdd, setShowAdd] = useState(false)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [localWorkDir, setLocalWorkDir] = useState('')
  const [savingWorkDir, setSavingWorkDir] = useState(false)
  const [workDirSaved, setWorkDirSaved] = useState(false)
  const [localToolDir, setLocalToolDir] = useState('')
  const [savingToolDir, setSavingToolDir] = useState(false)
  const [toolDirSaved, setToolDirSaved] = useState(false)

  // Desktop: data root (restart required)
  const [isDesktop, setIsDesktop] = useState(false)
  const [dataRoot, setDataRoot] = useState('')
  const [savingDataRoot, setSavingDataRoot] = useState(false)
  const [dataRootSaved, setDataRootSaved] = useState(false)
  const [dataRootRestartHint, setDataRootRestartHint] = useState(false)

  // Vision config local state
  const [visionForm, setVisionForm] = useState({
    provider_type: '',
    base_url: '',
    api_key: '',
    model: '',
    max_tokens: 4096,
  })
  const [savingVision, setSavingVision] = useState(false)
  const [visionSaved, setVisionSaved] = useState(false)
  const [showVisionKey, setShowVisionKey] = useState(false)
  const [testingVision, setTestingVision] = useState(false)
  const [visionTestResult, setVisionTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  // Agent config local state
  const [agentForm, setAgentForm] = useState({
    max_tool_rounds: 200,
    compaction_threshold: 0.75,
    compaction_interval: 20,
    keep_recent_rounds: 10,
  })
  const [savingAgent, setSavingAgent] = useState(false)
  const [agentSaved, setAgentSaved] = useState(false)

  // Embedding config local state
  const [embeddingForm, setEmbeddingForm] = useState({
    enabled: false,
    base_url: '',
    model: '',
    api_key: '',
    dimensions: 0,
    timeout: 30,
    backfill: true,
  })
  const [savingEmbedding, setSavingEmbedding] = useState(false)
  const [embeddingSaved, setEmbeddingSaved] = useState(false)
  const [showEmbeddingKey, setShowEmbeddingKey] = useState(false)

  useEffect(() => {
    fetchProviders()
    fetchConfig()
    fetchVisionConfig()
    fetchEmbeddingConfig()

    ;(async () => {
      try {
        const bs = await bootstrapApi.get()
        if (bs?.bootstrap_path) {
          setIsDesktop(true)
          setDataRoot(bs.data_root || '')
        }
      } catch {
        // ignore
      }
    })()
  }, [])

  // Sync local forms from store
  useEffect(() => { setLocalWorkDir(workDir) }, [workDir])
  useEffect(() => { setLocalToolDir(toolDir) }, [toolDir])
  useEffect(() => {
    if (agentConfig) {
      setAgentForm({
        max_tool_rounds: agentConfig.max_tool_rounds,
        compaction_threshold: agentConfig.compaction_threshold,
        compaction_interval: agentConfig.compaction_interval,
        keep_recent_rounds: agentConfig.keep_recent_rounds,
      })
    }
  }, [agentConfig])
  useEffect(() => {
    if (embeddingConfig) {
      setEmbeddingForm((prev) => ({
        ...prev,
        enabled: embeddingConfig.enabled,
        base_url: embeddingConfig.base_url || '',
        model: embeddingConfig.model || '',
        dimensions: embeddingConfig.dimensions || 0,
        timeout: embeddingConfig.timeout || 30,
        backfill: embeddingConfig.backfill,
      }))
    }
  }, [embeddingConfig])
  useEffect(() => {
    if (visionConfig) {
      setVisionForm((prev) => ({
        ...prev,
        provider_type: visionConfig.provider_type || '',
        base_url: visionConfig.base_url || '',
        model: visionConfig.model || '',
        max_tokens: visionConfig.max_tokens || 4096,
      }))
    }
  }, [visionConfig])

  // Handlers
  const handleSaveDataRoot = async () => {
    if (!dataRoot.trim()) return
    setSavingDataRoot(true)
    try {
      const res = await bootstrapApi.update({ data_root: dataRoot.trim() })
      setDataRootSaved(true)
      setDataRootRestartHint(!!res.restart_required)
      setTimeout(() => setDataRootSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save data_root:', err)
    } finally {
      setSavingDataRoot(false)
    }
  }

  const handleSaveWorkDir = async () => {
    if (!localWorkDir.trim()) return
    setSavingWorkDir(true)
    try {
      await setWorkDir(localWorkDir.trim())
      setWorkDirSaved(true)
      setTimeout(() => setWorkDirSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save workdir:', err)
    } finally {
      setSavingWorkDir(false)
    }
  }

  const handleSaveToolDir = async () => {
    setSavingToolDir(true)
    try {
      await setToolDir(localToolDir.trim())
      setToolDirSaved(true)
      setTimeout(() => setToolDirSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save tooldir:', err)
    } finally {
      setSavingToolDir(false)
    }
  }

  const handleSaveVision = async () => {
    setSavingVision(true)
    try {
      await updateVisionConfig({
        provider_type: visionForm.provider_type,
        base_url: visionForm.base_url,
        model: visionForm.model,
        max_tokens: visionForm.max_tokens,
        ...(visionForm.api_key ? { api_key: visionForm.api_key } : {}),
      })
      setVisionForm((prev) => ({ ...prev, api_key: '' }))
      setVisionSaved(true)
      setTimeout(() => setVisionSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save vision config:', err)
    } finally {
      setSavingVision(false)
    }
  }

  const handleSaveAgentConfig = async () => {
    setSavingAgent(true)
    try {
      await updateAgentConfig(agentForm)
      setAgentSaved(true)
      setTimeout(() => setAgentSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save agent config:', err)
    } finally {
      setSavingAgent(false)
    }
  }

  const handleSaveEmbedding = async () => {
    setSavingEmbedding(true)
    try {
      await updateEmbeddingConfig({
        enabled: embeddingForm.enabled,
        base_url: embeddingForm.base_url,
        model: embeddingForm.model,
        dimensions: embeddingForm.dimensions,
        timeout: embeddingForm.timeout,
        backfill: embeddingForm.backfill,
        ...(embeddingForm.api_key ? { api_key: embeddingForm.api_key } : {}),
      })
      setEmbeddingForm((prev) => ({ ...prev, api_key: '' }))
      setEmbeddingSaved(true)
      setTimeout(() => setEmbeddingSaved(false), 2000)
    } catch (err) {
      console.error('Failed to save embedding config:', err)
    } finally {
      setSavingEmbedding(false)
    }
  }

  const providerList = providers || []

  return (
  <div className="relative flex flex-col h-full">
    {/* Floating header */}
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
        <SettingsIcon className="w-4 h-4 text-primary-500" />
        <h1 className="text-base font-bold text-gray-900">设置</h1>
        <ChevronRight className="w-3.5 h-3.5 text-gray-300" />
        <span className="text-sm text-gray-500">{tabs.find(t => t.id === activeTab)?.label}</span>
      </div>
    </div>

    <div className="flex-1 overflow-y-auto pt-20 pb-6">
      <div className="max-w-3xl mx-auto w-full px-4">
        {/* Tab Navigation */}
        <div className="flex gap-1 p-1 rounded-xl bg-surface-50 border border-surface-border mb-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all flex-1 justify-center ${
                activeTab === tab.id
                  ? 'bg-white text-primary-700 shadow-sm border border-white/80'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-white/50'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* ═══════════════ 通用 Tab ═══════════════ */}
        {activeTab === 'general' && (
          <div className="space-y-5">
            {/* Desktop Data Root */}
            {isDesktop && (
              <div className="panel">
                <div className="panel-header">
                  <FolderOpen className="w-4 h-4 text-emerald-500" />
                  数据存放目录
                </div>
                <div className="p-4 space-y-3">
                  <p className="text-xs text-gray-400">修改后需要重启应用生效（用于数据库/会话/上传/技能库等）。</p>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={dataRoot}
                      onChange={(e) => setDataRoot(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleSaveDataRoot() }}
                      className="input-field flex-1"
                      placeholder="例如：C:\\Users\\xxx\\AppData\\Roaming\\LovelyIrisAgent"
                    />
                    <SaveButton saving={savingDataRoot} saved={dataRootSaved} disabled={!dataRoot.trim()} onClick={handleSaveDataRoot} />
                  </div>
                  {dataRootRestartHint && (
                    <div className="text-sm text-amber-600">已保存：请关闭并重新打开应用以切换到新的数据目录。</div>
                  )}
                </div>
              </div>
            )}

            {/* Work Directory */}
            <div className="panel">
              <div className="panel-header">
                <FolderOpen className="w-4 h-4 text-primary-500" />
                Agent 工作目录
              </div>
              <div className="p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={localWorkDir}
                    onChange={(e) => setLocalWorkDir(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSaveWorkDir() }}
                    className="input-field flex-1"
                    placeholder="/path/to/workspace"
                  />
                  <SaveButton saving={savingWorkDir} saved={workDirSaved} disabled={!localWorkDir.trim() || localWorkDir.trim() === workDir} onClick={handleSaveWorkDir} />
                </div>
                <p className="text-xs text-gray-400">
                  AI 解题的工作根目录，文件将存储在 <code className="text-primary-500">{'{workdir}'}/比赛名称/题目名称/</code> 下
                </p>
              </div>
            </div>

            {/* Display Settings */}
            <div className="panel">
              <div className="panel-header">
                <Monitor className="w-4 h-4 text-primary-500" />
                显示设置
              </div>
              <div className="p-4 space-y-3">
                <ToggleRow label="显示思考过程" description="展示模型的思维链内容" enabled={showThinking} onToggle={toggleThinking} />
                <ToggleRow label="自动滚动" description="自动滚动到最新消息" enabled={autoScroll} onToggle={toggleAutoScroll} />
              </div>
            </div>

            {/* About */}
            <div className="panel">
              <div className="panel-header">
                <SettingsIcon className="w-4 h-4 text-primary-500" />
                关于
              </div>
              <div className="p-4 text-sm text-gray-500 space-y-1">
                <p><strong className="text-gray-700">LovelyIrisAgent</strong> — AI 驱动的 CTF 解题平台</p>
                <p className="text-xs text-gray-400 pt-2">Go 后端 + React 前端 + WebSocket 流式传输</p>
              </div>
            </div>
          </div>
        )}

        {/* ═══════════════ 模型 Tab ═══════════════ */}
        {activeTab === 'models' && (
          <div className="space-y-5">
            {/* Default Model */}
            <div className="panel">
              <div className="panel-header">
                <Cpu className="w-4 h-4 text-primary-500" />
                默认模型
              </div>
              <div className="p-4">
                <select
                  value={selectedModel}
                  onChange={(e) => setModel(e.target.value)}
                  className="input-field w-full"
                >
                  <option value="">自动选择（Failover）</option>
                  {providerList.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name} ({p.model} - {p.type})
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-400 mt-1.5">选择 Agent 解题时使用的默认模型</p>
              </div>
            </div>

            {/* Utility Model */}
            <div className="panel">
              <div className="panel-header">
                <Cpu className="w-4 h-4 text-amber-500" />
                辅助模型（压缩/总结）
              </div>
              <div className="p-4">
                <select
                  value={utilityModel}
                  onChange={(e) => setUtilityModel(e.target.value)}
                  className="input-field w-full"
                >
                  <option value="">与 Agent 模型相同</option>
                  {providerList.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name} ({p.model} - {p.type})
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-400 mt-1.5">用于上下文压缩、Writeup 生成、经验总结等辅助任务，可选择更便宜的模型以节省成本</p>
              </div>
            </div>

            {/* Provider Management */}
            <div className="panel">
              <div className="panel-header justify-between">
                <div className="flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-primary-500" />
                  LLM 提供商
                </div>
                <button
                  onClick={() => setShowAdd(true)}
                  className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-500"
                >
                  <Plus className="w-3.5 h-3.5" />
                  添加
                </button>
              </div>
              <div className="p-4 space-y-3">
                {providerList.length === 0 ? (
                  <div className="text-center text-gray-400 text-sm py-4">
                    暂无提供商，点击上方 "添加" 配置
                  </div>
                ) : (
                  providerList.map((p) =>
                    editingName === p.name ? (
                      <EditProviderRow key={p.name} provider={p} onClose={() => setEditingName(null)} />
                    ) : (
                      <div key={p.name} className="flex items-center justify-between bg-surface-50 rounded-lg px-3 py-2.5 group">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-gray-700">{p.name}</span>
                            <span className="text-xs px-1.5 py-0.5 rounded bg-primary-50 text-primary-600">{p.type}</span>
                            {p.websocket_mode && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">WS</span>
                            )}
                            {p.has_api_key ? (
                              <span className="text-xs text-green-500">Key 已配置</span>
                            ) : (
                              <span className="text-xs text-red-400">未配置 Key</span>
                            )}
                          </div>
                          <div className="text-xs text-gray-400 mt-0.5 truncate">
                            {p.model} &middot; {p.base_url || '默认地址'} &middot; {(p.max_context_len / 1000).toFixed(0)}k ctx
                          </div>
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => setEditingName(p.name)} className="p-1 rounded hover:bg-surface-hover text-gray-400 hover:text-gray-600" title="编辑">
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={async () => { if (confirm(`确定删除提供商 "${p.name}" 吗？`)) { await removeProvider(p.name) } }}
                            className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="删除"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    )
                  )
                )}
              </div>
            </div>

            {/* Embedding Model */}
            <div className="panel">
              <div className="panel-header justify-between">
                <div className="flex items-center gap-2">
                  <Database className="w-4 h-4 text-cyan-500" />
                  Embedding 模型
                </div>
                <div className={`text-xs px-2 py-0.5 rounded-full ${embeddingConfig.enabled ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400'}`}>
                  {embeddingConfig.enabled ? '已启用' : '未启用'}
                </div>
              </div>
              <div className="p-4 space-y-3">
                <p className="text-xs text-gray-400">
                  配置向量嵌入模型，用于知识库/记忆/经验的语义搜索。支持 OpenAI 兼容的 Embedding API。
                </p>
                <ToggleRow
                  label="启用向量搜索"
                  description="开启后将使用 Embedding 模型进行语义检索"
                  enabled={embeddingForm.enabled}
                  onToggle={() => setEmbeddingForm({ ...embeddingForm, enabled: !embeddingForm.enabled })}
                />
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">模型名称</label>
                    <input
                      type="text"
                      value={embeddingForm.model}
                      onChange={(e) => setEmbeddingForm({ ...embeddingForm, model: e.target.value })}
                      className="input-field w-full"
                      placeholder="text-embedding-3-small"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">向量维度</label>
                    <input
                      type="number"
                      value={embeddingForm.dimensions}
                      onChange={(e) => setEmbeddingForm({ ...embeddingForm, dimensions: parseInt(e.target.value) || 0 })}
                      className="input-field w-full"
                      placeholder="0 = 自动检测"
                      min={0}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">API Base URL</label>
                  <input
                    type="text"
                    value={embeddingForm.base_url}
                    onChange={(e) => setEmbeddingForm({ ...embeddingForm, base_url: e.target.value })}
                    className="input-field w-full"
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    API Key {embeddingConfig.has_api_key && <span className="text-green-500">(已配置)</span>}
                  </label>
                  <div className="relative">
                    <input
                      type={showEmbeddingKey ? 'text' : 'password'}
                      value={embeddingForm.api_key}
                      onChange={(e) => setEmbeddingForm({ ...embeddingForm, api_key: e.target.value })}
                      className="input-field w-full pr-10"
                      placeholder={embeddingConfig.has_api_key ? '留空保持不变' : 'sk-...'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowEmbeddingKey(!showEmbeddingKey)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showEmbeddingKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">超时时间 (秒)</label>
                    <input
                      type="number"
                      value={embeddingForm.timeout}
                      onChange={(e) => setEmbeddingForm({ ...embeddingForm, timeout: parseInt(e.target.value) || 30 })}
                      className="input-field w-full"
                      placeholder="30"
                      min={5}
                    />
                  </div>
                  <div className="flex items-end pb-1">
                    <ToggleRow
                      label="自动回填"
                      description="启动时自动嵌入已有记忆"
                      enabled={embeddingForm.backfill}
                      onToggle={() => setEmbeddingForm({ ...embeddingForm, backfill: !embeddingForm.backfill })}
                    />
                  </div>
                </div>
                <div className="flex justify-end pt-1">
                  <SaveButton saving={savingEmbedding} saved={embeddingSaved} disabled={!embeddingForm.model.trim()} onClick={handleSaveEmbedding} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════════════ Agent Tab ═══════════════ */}
        {activeTab === 'agent' && (
          <div className="space-y-5">
            {/* Agent Runtime Parameters */}
            <div className="panel">
              <div className="panel-header">
                <Cog className="w-4 h-4 text-orange-500" />
                运行参数
              </div>
              <div className="p-4 space-y-4">
                <p className="text-xs text-gray-400">
                  控制 Agent 解题过程中的工具调用轮次和上下文压缩策略。修改后立即对新启动的 Agent 生效。
                </p>

                {/* Max Tool Rounds */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm text-gray-700 font-medium">最大工具轮次</label>
                    <span className="text-xs text-primary-600 font-mono bg-primary-50 px-2 py-0.5 rounded">{agentForm.max_tool_rounds}</span>
                  </div>
                  <input
                    type="range"
                    value={agentForm.max_tool_rounds}
                    onChange={(e) => setAgentForm({ ...agentForm, max_tool_rounds: parseInt(e.target.value) })}
                    className="w-full accent-primary-500"
                    min={10}
                    max={500}
                    step={10}
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>10</span>
                    <span>Agent 每次解题最多执行的工具调用轮次</span>
                    <span>500</span>
                  </div>
                </div>

                {/* Compaction Threshold */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm text-gray-700 font-medium">压缩阈值</label>
                    <span className="text-xs text-amber-600 font-mono bg-amber-50 px-2 py-0.5 rounded">{(agentForm.compaction_threshold * 100).toFixed(0)}%</span>
                  </div>
                  <input
                    type="range"
                    value={agentForm.compaction_threshold * 100}
                    onChange={(e) => setAgentForm({ ...agentForm, compaction_threshold: parseInt(e.target.value) / 100 })}
                    className="w-full accent-amber-500"
                    min={30}
                    max={95}
                    step={5}
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>30%</span>
                    <span>当上下文占用达到此比例时触发压缩</span>
                    <span>95%</span>
                  </div>
                </div>

                {/* Compaction Interval */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm text-gray-700 font-medium">强制压缩间隔</label>
                    <span className="text-xs text-violet-600 font-mono bg-violet-50 px-2 py-0.5 rounded">{agentForm.compaction_interval} 轮</span>
                  </div>
                  <input
                    type="range"
                    value={agentForm.compaction_interval}
                    onChange={(e) => setAgentForm({ ...agentForm, compaction_interval: parseInt(e.target.value) })}
                    className="w-full accent-violet-500"
                    min={0}
                    max={100}
                    step={5}
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>0 (禁用)</span>
                    <span>每隔 N 轮强制执行一次软压缩（防止大上下文模型膨胀）</span>
                    <span>100</span>
                  </div>
                </div>

                {/* Keep Recent Rounds */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm text-gray-700 font-medium">保留最近轮次</label>
                    <span className="text-xs text-emerald-600 font-mono bg-emerald-50 px-2 py-0.5 rounded">{agentForm.keep_recent_rounds} 轮</span>
                  </div>
                  <input
                    type="range"
                    value={agentForm.keep_recent_rounds}
                    onChange={(e) => setAgentForm({ ...agentForm, keep_recent_rounds: parseInt(e.target.value) })}
                    className="w-full accent-emerald-500"
                    min={2}
                    max={50}
                    step={1}
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>2</span>
                    <span>压缩时保留最近 N 轮对话不被压缩</span>
                    <span>50</span>
                  </div>
                </div>

                {/* Quick Presets */}
                <div className="border-t border-surface-border pt-3">
                  <label className="block text-xs text-gray-500 mb-2">快速预设</label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setAgentForm({ max_tool_rounds: 100, compaction_threshold: 0.7, compaction_interval: 15, keep_recent_rounds: 8 })}
                      className="btn-secondary text-xs !px-3 !py-1.5"
                    >
                      保守模式
                    </button>
                    <button
                      onClick={() => setAgentForm({ max_tool_rounds: 200, compaction_threshold: 0.75, compaction_interval: 20, keep_recent_rounds: 10 })}
                      className="btn-secondary text-xs !px-3 !py-1.5"
                    >
                      默认
                    </button>
                    <button
                      onClick={() => setAgentForm({ max_tool_rounds: 500, compaction_threshold: 0.85, compaction_interval: 40, keep_recent_rounds: 20 })}
                      className="btn-secondary text-xs !px-3 !py-1.5"
                    >
                      大上下文
                    </button>
                  </div>
                </div>

                <div className="flex justify-end pt-1">
                  <SaveButton saving={savingAgent} saved={agentSaved} onClick={handleSaveAgentConfig} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════════════ 工具 Tab ═══════════════ */}
        {activeTab === 'tools' && (
          <div className="space-y-5">
            {/* Tool Directory */}
            <div className="panel">
              <div className="panel-header">
                <FolderOpen className="w-4 h-4 text-emerald-500" />
                工具目录（Tool Directory）
              </div>
              <div className="p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={localToolDir}
                    onChange={(e) => setLocalToolDir(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSaveToolDir() }}
                    className="input-field flex-1"
                    placeholder="/path/to/my-tools  (留空则不覆盖 PATH)"
                  />
                  <SaveButton saving={savingToolDir} saved={toolDirSaved} disabled={localToolDir.trim() === toolDir} onClick={handleSaveToolDir} />
                </div>
                <p className="text-xs text-gray-400">
                  该目录下的可执行文件会被 <strong>追加到 PATH 的最前面</strong>，让 AI 通过 exec 直接调用自定义工具。
                  例如将 <code className="text-emerald-600">my-decoder</code> 放入该目录，就可让 AI 执行 <code className="text-emerald-600">my-decoder flag.bin</code>。
                </p>
                {localToolDir.trim() && (
                  <div className="flex items-start gap-2 rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2">
                    <span className="text-xs text-emerald-700">当前已配置：<code className="font-mono">{localToolDir.trim()}</code></span>
                  </div>
                )}
              </div>
            </div>

            {/* Vision Tool */}
            <div className="panel">
              <div className="panel-header">
                <ScanEye className="w-4 h-4 text-violet-500" />
                识图工具（Vision）
              </div>
              <div className="p-4 space-y-3">
                <p className="text-xs text-gray-400">
                  配置图像识别工具所使用的视觉大模型。Agent 可通过 <code className="text-violet-500">vision</code> 工具分析截图、图表、二维码等图像内容。
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">提供商类型</label>
                    <select
                      value={visionForm.provider_type}
                      onChange={(e) => setVisionForm({ ...visionForm, provider_type: e.target.value })}
                      className="input-field w-full"
                    >
                      <option value="">请选择</option>
                      <option value="openai">OpenAI (GPT-4o 等)</option>
                      <option value="anthropic">Anthropic (Claude)</option>
                      <option value="openai_compat">OpenAI 兼容</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">模型名称</label>
                    <input
                      type="text"
                      value={visionForm.model}
                      onChange={(e) => setVisionForm({ ...visionForm, model: e.target.value })}
                      className="input-field w-full"
                      placeholder={visionForm.provider_type === 'anthropic' ? 'claude-sonnet-4-20250514' : 'gpt-4o'}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    API Key {visionConfig.has_api_key && <span className="text-green-500">(已配置)</span>}
                  </label>
                  <div className="relative">
                    <input
                      type={showVisionKey ? 'text' : 'password'}
                      value={visionForm.api_key}
                      onChange={(e) => setVisionForm({ ...visionForm, api_key: e.target.value })}
                      className="input-field w-full pr-10"
                      placeholder={visionConfig.has_api_key ? '留空保持不变' : 'sk-...'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowVisionKey(!showVisionKey)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showVisionKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">API Base URL</label>
                    <input
                      type="text"
                      value={visionForm.base_url}
                      onChange={(e) => setVisionForm({ ...visionForm, base_url: e.target.value })}
                      className="input-field w-full"
                      placeholder={
                        visionForm.provider_type === 'openai'
                          ? 'https://api.openai.com/v1'
                          : visionForm.provider_type === 'anthropic'
                          ? 'https://api.anthropic.com'
                          : 'https://api.example.com/v1'
                      }
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">最大输出 Tokens</label>
                    <input
                      type="number"
                      value={visionForm.max_tokens}
                      onChange={(e) => setVisionForm({ ...visionForm, max_tokens: parseInt(e.target.value) || 4096 })}
                      className="input-field w-full"
                      placeholder="4096"
                      min={256}
                      step={256}
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    onClick={async () => {
                      setTestingVision(true)
                      setVisionTestResult(null)
                      try {
                        const res = await configApi.testVisionConfig()
                        if (res.ok) {
                          setVisionTestResult({ ok: true, message: `模型回复: ${res.result}` })
                        } else {
                          setVisionTestResult({ ok: false, message: res.error || '测试失败' })
                        }
                      } catch (err: unknown) {
                        setVisionTestResult({ ok: false, message: err instanceof Error ? err.message : '请求失败' })
                      } finally {
                        setTestingVision(false)
                      }
                    }}
                    disabled={testingVision || !visionConfig.has_api_key}
                    className="btn-secondary flex items-center gap-1.5 !px-4"
                  >
                    {testingVision ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                    {testingVision ? '测试中...' : '测试'}
                  </button>
                  <SaveButton saving={savingVision} saved={visionSaved} disabled={!visionForm.model.trim() || !visionForm.provider_type} onClick={handleSaveVision} />
                </div>
                {visionTestResult && (
                  <div className={`rounded-lg px-3 py-2 text-xs ${
                    visionTestResult.ok
                      ? 'bg-green-50 border border-green-200 text-green-700'
                      : 'bg-red-50 border border-red-200 text-red-700'
                  }`}>
                    {visionTestResult.ok ? '✅ ' : '❌ '}{visionTestResult.message}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>

    {/* Add Provider Modal */}
    {showAdd && <AddProviderModal onClose={() => setShowAdd(false)} />}
  </div>
  )
}

function SaveButton({ saving, saved, disabled, onClick }: {
  saving: boolean
  saved: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={saving || disabled}
      className="btn-primary flex items-center gap-1.5 !px-3"
    >
      {saving ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : saved ? (
        <Check className="w-4 h-4" />
      ) : (
        <Save className="w-4 h-4" />
      )}
      {saved ? '已保存' : '保存'}
    </button>
  )
}

function AddProviderModal({ onClose }: { onClose: () => void }) {
  const { addProvider } = useSettingsStore()
  const [form, setForm] = useState({
    name: '',
    type: 'openai' as ProviderType,
    base_url: defaultBaseURLs.openai,
    api_key: '',
    model: '',
    max_context_len: 128000,
    websocket_mode: false,
  })
  const [saving, setSaving] = useState(false)
  const [showKey, setShowKey] = useState(false)

  const handleTypeChange = (type: ProviderType) => {
    setForm({
      ...form,
      type,
      base_url: defaultBaseURLs[type] || '',
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.model.trim()) return
    setSaving(true)
    try {
      await addProvider(form)
      onClose()
    } catch (err) {
      console.error('Failed to add provider:', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg">
        <div className="panel-header justify-between">
          <span>添加 LLM 提供商</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Provider Type */}
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">类型 *</label>
            <div className="grid grid-cols-2 gap-2">
              {providerTypes.map((pt) => (
                <button
                  key={pt.value}
                  type="button"
                  onClick={() => handleTypeChange(pt.value)}
                  className={`text-left px-3 py-2 rounded-lg border transition-colors ${
                    form.type === pt.value
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-surface-border hover:border-gray-300 text-gray-600'
                  }`}
                >
                  <div className="text-sm font-medium">{pt.label}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{pt.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Name */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">名称 *</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="input-field w-full"
              placeholder="例如：my-gpt4o, deepseek-v3"
              autoFocus
            />
          </div>

          {/* Model */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">模型名称 *</label>
            <input
              type="text"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="input-field w-full"
              placeholder={
                form.type === 'openai'
                  ? 'gpt-4o, gpt-4o-mini'
                  : form.type === 'anthropic'
                  ? 'claude-sonnet-4-20250514, claude-opus-4-20250514'
                  : form.type === 'ollama'
                  ? 'llama3, qwen2.5'
                  : 'deepseek-chat, qwen-max'
              }
            />
          </div>

          {/* API Key */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">API Key</label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                className="input-field w-full pr-10"
                placeholder={form.type === 'ollama' ? '本地服务无需 Key' : 'sk-...'}
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Base URL */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">API Base URL</label>
            <input
              type="text"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              className="input-field w-full"
              placeholder="https://api.example.com/v1"
            />
            <p className="text-xs text-gray-400 mt-1">
              {form.type === 'openai_compat'
                ? '填写兼容 OpenAI 格式的 API 地址'
                : '留空使用默认地址'}
            </p>
          </div>

          {/* Max Context Length */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">最大上下文长度 (tokens)</label>
            <input
              type="number"
              value={form.max_context_len}
              onChange={(e) => setForm({ ...form, max_context_len: parseInt(e.target.value) || 0 })}
              className="input-field w-full"
              placeholder="128000"
              min={1024}
              step={1024}
            />
            <p className="text-xs text-gray-400 mt-1">决定何时触发上下文压缩，填写模型支持的最大值</p>
          </div>

          {/* WebSocket Mode (only for openai / openai_compat) */}
          {(form.type === 'openai' || form.type === 'openai_compat') && (
            <div className="flex items-center justify-between bg-surface-50 rounded-lg px-3 py-2.5">
              <div>
                <div className="text-sm text-gray-700">WebSocket 模式</div>
                <div className="text-xs text-gray-400">使用持久 WebSocket 连接，降低多轮 tool call 延迟 (最高 ~40%)</div>
              </div>
              <button
                type="button"
                onClick={() => setForm({ ...form, websocket_mode: !form.websocket_mode })}
                className={`relative w-10 h-5 rounded-full transition-colors ${
                  form.websocket_mode ? 'bg-primary-600' : 'bg-gray-200'
                }`}
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    form.websocket_mode ? 'left-5' : 'left-0.5'
                  }`}
                />
              </button>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              取消
            </button>
            <button
              type="submit"
              disabled={saving || !form.name.trim() || !form.model.trim()}
              className="btn-primary"
            >
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function EditProviderRow({
  provider,
  onClose,
}: {
  provider: { name: string; type: string; base_url: string; model: string; has_api_key: boolean; max_context_len: number; websocket_mode?: boolean }
  onClose: () => void
}) {
  const { updateProvider } = useSettingsStore()
  const [form, setForm] = useState({
    base_url: provider.base_url,
    api_key: '',
    model: provider.model,
    max_context_len: provider.max_context_len || 128000,
    websocket_mode: provider.websocket_mode || false,
  })
  const [saving, setSaving] = useState(false)
  const [showKey, setShowKey] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateProvider(provider.name, {
        base_url: form.base_url,
        model: form.model,
        max_context_len: form.max_context_len,
        websocket_mode: form.websocket_mode,
        ...(form.api_key ? { api_key: form.api_key } : {}),
      })
      onClose()
    } catch (err) {
      console.error('Failed to update provider:', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-surface-50 rounded-lg p-3 space-y-2 border border-primary-200">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">{provider.name}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-primary-50 text-primary-600">
            {provider.type}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="p-1 rounded hover:bg-green-50 text-green-500 hover:text-green-600"
            title="保存"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-hover text-gray-400 hover:text-gray-600"
            title="取消"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-gray-400 mb-0.5">模型</label>
          <input
            type="text"
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            className="input-field w-full text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-0.5">
            API Key {provider.has_api_key && <span className="text-green-500">(已配置)</span>}
          </label>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              className="input-field w-full text-sm pr-8"
              placeholder="留空保持不变"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400"
            >
              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-0.5">Base URL</label>
        <input
          type="text"
          value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          className="input-field w-full text-sm"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-0.5">最大上下文 (tokens)</label>
        <input
          type="number"
          value={form.max_context_len}
          onChange={(e) => setForm({ ...form, max_context_len: parseInt(e.target.value) || 0 })}
          className="input-field w-full text-sm"
          placeholder="128000"
          min={1024}
          step={1024}
        />
      </div>
      {/* WebSocket Mode toggle (openai / openai_compat only) */}
      {(provider.type === 'openai' || provider.type === 'openai_compat') && (
        <div className="flex items-center justify-between mt-1">
          <div>
            <span className="text-xs text-gray-500">WebSocket 模式</span>
            <span className="text-xs text-gray-400 ml-1">持久连接，降低多轮 tool call 延迟</span>
          </div>
          <button
            type="button"
            onClick={() => setForm({ ...form, websocket_mode: !form.websocket_mode })}
            className={`relative w-9 h-[18px] rounded-full transition-colors ${
              form.websocket_mode ? 'bg-primary-600' : 'bg-gray-200'
            }`}
          >
            <div
              className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform ${
                form.websocket_mode ? 'left-[18px]' : 'left-[2px]'
              }`}
            />
          </button>
        </div>
      )}
    </div>
  )
}

function ToggleRow({
  label,
  description,
  enabled,
  onToggle,
}: {
  label: string
  description: string
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <div className="text-sm text-gray-700">{label}</div>
        <div className="text-xs text-gray-400">{description}</div>
      </div>
      <button
        onClick={onToggle}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          enabled ? 'bg-primary-600' : 'bg-gray-200'
        }`}
      >
        <div
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            enabled ? 'left-5' : 'left-0.5'
          }`}
        />
      </button>
    </div>
  )
}
