import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Database, Folder, Cpu, CheckCircle2, ChevronRight, AlertCircle } from 'lucide-react'
import { bootstrapApi, providerApi } from '../services/api'
import { useSettingsStore } from '../stores/settingsStore'
import { getModeHomePath } from '../utils/modeRoutes'

type Step = 1 | 2 | 3

export default function Onboarding() {
  const navigate = useNavigate()
  const {
    providers,
    fetchProviders,
    fetchConfig,
    workDir,
    toolDir,
    setWorkDir,
    setToolDir,
    setModel,
    setUtilityModel,
    agentMode,
  } = useSettingsStore()

  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState<Step>(1)
  const [dataRoot, setDataRoot] = useState('')
  const [restartRequired, setRestartRequired] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Provider fields (minimal)
  const [providerName, setProviderName] = useState('openai')
  const [providerType, setProviderType] = useState('openai')
  const [providerBaseURL, setProviderBaseURL] = useState('')
  const [providerModel, setProviderModel] = useState('')
  const [providerAPIKey, setProviderAPIKey] = useState('')
  const providerList = providers || []

  const pickFolder = async (title: string): Promise<string | null> => {
    const wAny = window as any
    if (typeof wAny.pickFolder === 'function') {
      const picked = await wAny.pickFolder(title)
      return picked ? String(picked) : null
    }
    // Browser fallback (may be unsupported in WebView2 depending on version/policy)
    const picker = (window as any).showDirectoryPicker
    if (typeof picker === 'function') {
      try {
        // In browsers that support File System Access API, we could retrieve a handle.
        // Converting a directory handle into a full native path is not standardized, so we fall back to null.
        await picker({ id: 'lovelyirisagent', mode: 'readwrite' })
        return null
      } catch {
        return null
      }
    }
    return null
  }

  const canProceedStep3 = useMemo(() => {
    return providerName.trim() !== '' && providerType.trim() !== '' && providerModel.trim() !== ''
  }, [providerName, providerType, providerModel])

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const bs = await bootstrapApi.get()
        if (bs?.completed) {
          navigate(getModeHomePath(agentMode), { replace: true })
          return
        }
        setDataRoot(bs?.data_root || '')
        const initialStep = (bs?.step || 1) as Step
        setStep(initialStep)

        await Promise.all([fetchConfig(), fetchProviders()])
      } catch (e) {
        console.error(e)
        setError('无法加载引导信息（后端未启动或接口异常）')
      } finally {
        setLoading(false)
      }
    })()
  }, [fetchConfig, fetchProviders, navigate])

  const saveStep1 = async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await bootstrapApi.update({ data_root: dataRoot.trim(), step: 2, completed: false })
      setRestartRequired(!!res.restart_required)
      if (!res.restart_required) {
        setStep(2)
      }
    } catch (e) {
      console.error(e)
      setError('保存数据目录失败')
    } finally {
      setSaving(false)
    }
  }

  const saveStep2 = async () => {
    setSaving(true)
    setError(null)
    try {
      if (workDir.trim()) await setWorkDir(workDir.trim())
      await setToolDir(toolDir.trim())
      await bootstrapApi.update({ step: 3 })
      setStep(3)
    } catch (e) {
      console.error(e)
      setError('保存工作目录/工具目录失败')
    } finally {
      setSaving(false)
    }
  }

  const saveStep3 = async () => {
    setSaving(true)
    setError(null)
    try {
      const name = providerName.trim()
      const providerExists = providerList.some((p) => p.name === name)
      if (providerExists) {
        await providerApi.update(name, {
          type: providerType.trim(),
          base_url: providerBaseURL.trim(),
          model: providerModel.trim(),
          ...(providerAPIKey.trim() ? { api_key: providerAPIKey.trim() } : {}),
        })
      } else {
        await providerApi.add({
          name,
          type: providerType.trim(),
          base_url: providerBaseURL.trim(),
          api_key: providerAPIKey.trim(),
          model: providerModel.trim(),
        })
      }
      await fetchProviders()
      setModel(name)
      setUtilityModel(name)
      await bootstrapApi.update({ completed: true, step: 99 })
      navigate(getModeHomePath(agentMode), { replace: true })
    } catch (e) {
      console.error(e)
      setError('保存 LLM 配置失败（请检查 API Key / Base URL / 网络）')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-full flex items-center justify-center bg-surface-50">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-primary-100 flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
          </div>
          <div className="text-gray-500 font-medium">正在加载配置...</div>
        </div>
      </div>
    )
  }

  const steps = [
    { id: 1, title: '数据目录', icon: Database, desc: '配置核心数据存储位置' },
    { id: 2, title: '工作空间', icon: Folder, desc: '设置 Agent 运行环境' },
    { id: 3, title: 'AI 模型', icon: Cpu, desc: '连接大语言模型' },
  ]

  return (
    <div className="min-h-full bg-gradient-to-br from-surface-50 via-surface-100 to-primary-50/30 flex items-center justify-center p-6">
      <div className="w-full max-w-3xl bg-white/80 backdrop-blur-xl rounded-3xl shadow-2xl border border-white/60 overflow-hidden flex flex-col md:flex-row">
        
        {/* Left Sidebar - Steps */}
        <div className="w-full md:w-64 bg-surface-50/50 p-8 border-b md:border-b-0 md:border-r border-gray-200/50">
          <div className="flex items-center gap-3 mb-10">
            <div className="w-8 h-8 text-primary-600">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
                <path d="M19 8 L22 5 L22 11 Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" fill="none"/>
                <ellipse cx="11" cy="12" rx="8" ry="5.5" stroke="currentColor" strokeWidth="1.4"/>
                <circle cx="6" cy="11" r="1" fill="currentColor"/>
                <path d="M10 6.5 Q12 4 14 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
                <path d="M3.5 12.5 Q3 11.5 3.5 10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
              </svg>
            </div>
            <span className="text-lg font-bold bg-gradient-to-r from-primary-600 to-indigo-600 bg-clip-text text-transparent">
              LovelyIrisAgent
            </span>
          </div>

          <div className="space-y-6">
            {steps.map((s) => {
              const Icon = s.icon
              const isActive = step === s.id
              const isPast = step > s.id
              return (
                <div key={s.id} className={`flex items-start gap-4 transition-opacity duration-300 ${isActive ? 'opacity-100' : isPast ? 'opacity-60' : 'opacity-40'}`}>
                  <div className={`mt-0.5 flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors duration-300 ${
                    isActive ? 'bg-primary-100 text-primary-600 ring-4 ring-primary-50' :
                    isPast ? 'bg-green-100 text-green-600' :
                    'bg-gray-100 text-gray-400'
                  }`}>
                    {isPast ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-4 h-4" />}
                  </div>
                  <div>
                    <div className={`font-medium ${isActive ? 'text-gray-900' : 'text-gray-600'}`}>{s.title}</div>
                    <div className="text-xs text-gray-500 mt-0.5">{s.desc}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Right Content Area */}
        <div className="flex-1 p-8 md:p-10 flex flex-col">
          <div className="flex-1">
            {error && (
              <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl flex items-start gap-3 text-red-600">
                <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                <div className="text-sm">{error}</div>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">配置数据目录</h2>
                  <p className="text-gray-500 text-sm">
                    选择一个安全的位置来存储你的数据库、会话记录、上传的附件和技能库。
                  </p>
                </div>

                <div className="space-y-4">
                  <div className="space-y-2">
                    <label className="block text-sm font-medium text-gray-700">数据根目录路径</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Database className="w-5 h-5 text-gray-400" />
                      </div>
                      <input
                        value={dataRoot}
                        onChange={(e) => setDataRoot(e.target.value)}
                        className="block w-full pl-10 pr-28 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50"
                        placeholder="例如：C:\Users\xxx\AppData\Roaming\LovelyIrisAgent"
                      />
						<button
							type="button"
							className="absolute inset-y-1.5 right-1.5 px-3 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors"
							onClick={async (e) => {
								e.preventDefault()
								const p = await pickFolder('选择数据目录')
								if (p) setDataRoot(p)
							}}
						>
							选择…
						</button>
                    </div>
                    <p className="text-xs text-gray-400 pl-1">默认位于 AppData\Roaming 下，建议保持默认。</p>
                  </div>

                  {restartRequired && (
                    <div className="p-4 bg-amber-50 border border-amber-100 rounded-xl flex items-start gap-3 text-amber-700">
                      <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                      <div className="text-sm">
                        <span className="font-medium block mb-1">需要重启应用</span>
                        数据目录已变更，请关闭当前窗口并重新打开应用。重启后将自动进入下一步。
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">设置工作空间</h2>
                  <p className="text-gray-500 text-sm">
                    配置 Agent 运行时的临时文件存放位置和外部工具路径。
                  </p>
                </div>

                <div className="space-y-5">
                  <div className="space-y-2">
                    <label className="block text-sm font-medium text-gray-700">Agent 工作目录</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Folder className="w-5 h-5 text-gray-400" />
                      </div>
                      <input 
                        value={workDir} 
                        onChange={(e) => useSettingsStore.setState({ workDir: e.target.value })} 
                        className="block w-full pl-10 pr-28 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50" 
                        placeholder="输入工作目录路径"
                      />
						<button
							type="button"
							className="absolute inset-y-1.5 right-1.5 px-3 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors"
							onClick={async (e) => {
								e.preventDefault()
								const p = await pickFolder('选择工作目录')
								if (p) useSettingsStore.setState({ workDir: p })
							}}
						>
							选择…
						</button>
                    </div>
                    <p className="text-xs text-gray-400 pl-1">用于保存每道题的临时文件、脚本、下载内容等。</p>
                  </div>

                  <div className="space-y-2">
                    <label className="block text-sm font-medium text-gray-700">工具目录 <span className="text-gray-400 font-normal">(可选)</span></label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Cpu className="w-5 h-5 text-gray-400" />
                      </div>
                      <input 
                        value={toolDir} 
                        onChange={(e) => useSettingsStore.setState({ toolDir: e.target.value })} 
                        className="block w-full pl-10 pr-28 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50" 
                        placeholder="输入工具目录路径"
                      />
						<button
							type="button"
							className="absolute inset-y-1.5 right-1.5 px-3 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors"
							onClick={async (e) => {
								e.preventDefault()
								const p = await pickFolder('选择工具目录')
								if (p) useSettingsStore.setState({ toolDir: p })
							}}
						>
							选择…
						</button>
                    </div>
                    <p className="text-xs text-gray-400 pl-1">用于保存下载/编译的外部工具，后端会自动将其加入 PATH。</p>
                  </div>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">连接 AI 模型</h2>
                  <p className="text-gray-500 text-sm">
                    配置你的第一个大语言模型提供商。完成后可在设置中添加更多。
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-gray-700">配置名称</label>
                    <input 
                      value={providerName} 
                      onChange={(e) => setProviderName(e.target.value)} 
                      className="block w-full px-3 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50 text-sm" 
                      placeholder="例如：OpenAI-GPT4"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-gray-700">接口类型</label>
                    <select 
                      value={providerType} 
                      onChange={(e) => setProviderType(e.target.value)} 
                      className="block w-full px-3 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50 text-sm"
                    >
                      <option value="openai">OpenAI</option>
                      <option value="anthropic">Anthropic</option>
                      <option value="ollama">Ollama</option>
                      <option value="openai_compat">OpenAI 兼容接口</option>
                    </select>
                  </div>
                  <div className="md:col-span-2 space-y-1.5">
                    <label className="block text-xs font-medium text-gray-700">Base URL <span className="text-gray-400 font-normal">(可选)</span></label>
                    <input 
                      value={providerBaseURL} 
                      onChange={(e) => setProviderBaseURL(e.target.value)} 
                      className="block w-full px-3 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50 text-sm" 
                      placeholder="例如：https://api.openai.com/v1" 
                    />
                  </div>
                  <div className="md:col-span-2 space-y-1.5">
                    <label className="block text-xs font-medium text-gray-700">模型名称 (Model)</label>
                    <input 
                      value={providerModel} 
                      onChange={(e) => setProviderModel(e.target.value)} 
                      className="block w-full px-3 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50 text-sm" 
                      placeholder="例如：gpt-4o / claude-3-5-sonnet-20240620" 
                    />
                  </div>
                  <div className="md:col-span-2 space-y-1.5">
                    <label className="block text-xs font-medium text-gray-700">API Key</label>
                    <input 
                      type="password"
                      value={providerAPIKey} 
                      onChange={(e) => setProviderAPIKey(e.target.value)} 
                      className="block w-full px-3 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all bg-white/50 text-sm" 
                      placeholder="输入你的 API 密钥（Ollama 等本地模型可留空）" 
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div className="mt-10 pt-6 border-t border-gray-100 flex items-center justify-between">
            {step > 1 ? (
              <button 
                onClick={() => setStep((step - 1) as Step)} 
                className="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-xl transition-colors"
              >
                返回上一步
              </button>
            ) : (
              <div /> // Spacer
            )}

            {step === 1 && (
              <button
                onClick={saveStep1}
                disabled={saving || !dataRoot.trim() || restartRequired}
                className="flex items-center gap-2 px-6 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-primary-600/20"
              >
                {saving ? '保存中...' : '下一步'}
                {!saving && <ChevronRight className="w-4 h-4" />}
              </button>
            )}

            {step === 2 && (
              <button
                onClick={saveStep2}
                disabled={saving || !workDir.trim()}
                className="flex items-center gap-2 px-6 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-primary-600/20"
              >
                {saving ? '保存中...' : '下一步'}
                {!saving && <ChevronRight className="w-4 h-4" />}
              </button>
            )}

            {step === 3 && (
              <button
                onClick={saveStep3}
                disabled={saving || !canProceedStep3}
                className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-primary-600 to-indigo-600 hover:from-primary-700 hover:to-indigo-700 text-white text-sm font-medium rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-primary-600/20"
              >
                {saving ? '配置中...' : '完成配置，进入系统'}
                {!saving && <CheckCircle2 className="w-4 h-4" />}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
