import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Provider, AgentMode } from '../types'
import { providerApi, configApi } from '../services/api'

interface AgentConfigState {
  max_tool_rounds: number
  compaction_threshold: number
  compaction_interval: number
  keep_recent_rounds: number
}

interface EmbeddingConfigState {
  enabled: boolean
  base_url: string
  model: string
  dimensions: number
  timeout: number
  backfill: boolean
  has_api_key: boolean
}

interface SettingsState {
  // UI preferences
  theme: 'light' | 'dark' | 'pink'
  sidebarCollapsed: boolean
  showThinking: boolean
  showSystemInject: boolean
  autoScroll: boolean

  // Agent mode
  agentMode: AgentMode

  // Provider
  providers: Provider[]
  selectedModel: string
  utilityModel: string // model for compaction/writeup (empty = use agent model)

  // Work directory
  workDir: string

  // Tool binary directory
  toolDir: string

  // Agent config
  agentConfig: AgentConfigState

  // Embedding config
  embeddingConfig: EmbeddingConfigState

  // Vision tool config
  visionConfig: {
    provider_type: string
    base_url: string
    model: string
    max_tokens: number
    has_api_key: boolean
  }

  // Actions
  setTheme: (theme: 'light' | 'dark' | 'pink') => void
  setAgentMode: (mode: AgentMode) => void
  toggleSidebar: () => void
  toggleThinking: () => void
  toggleSystemInject: () => void
  toggleAutoScroll: () => void
  setModel: (model: string) => void
  setUtilityModel: (model: string) => void
  fetchProviders: () => Promise<void>
  addProvider: (data: {
    name: string
    type: string
    base_url: string
    api_key: string
    model: string
    max_context_len?: number
    websocket_mode?: boolean
  }) => Promise<void>
  updateProvider: (name: string, data: {
    type?: string
    base_url?: string
    api_key?: string
    model?: string
    max_context_len?: number
    websocket_mode?: boolean
  }) => Promise<void>
  removeProvider: (name: string) => Promise<void>
  fetchConfig: () => Promise<void>
  setWorkDir: (dir: string) => Promise<void>
  setToolDir: (dir: string) => Promise<void>
  fetchAgentConfig: () => Promise<void>
  updateAgentConfig: (data: Partial<AgentConfigState>) => Promise<void>
  fetchEmbeddingConfig: () => Promise<void>
  updateEmbeddingConfig: (data: {
    enabled?: boolean
    base_url?: string
    model?: string
    api_key?: string
    dimensions?: number
    timeout?: number
    backfill?: boolean
  }) => Promise<void>
  fetchVisionConfig: () => Promise<void>
  updateVisionConfig: (data: {
    provider_type: string
    base_url: string
    api_key?: string
    model: string
    max_tokens: number
  }) => Promise<void>
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      sidebarCollapsed: false,
      showThinking: true,
      showSystemInject: true,
      autoScroll: true,
      agentMode: 'ctf',
      providers: [],
      selectedModel: '',
      utilityModel: '',
      workDir: '',
      toolDir: '',
      agentConfig: {
        max_tool_rounds: 200,
        compaction_threshold: 0.75,
        compaction_interval: 20,
        keep_recent_rounds: 10,
      },
      embeddingConfig: {
        enabled: false,
        base_url: '',
        model: '',
        dimensions: 0,
        timeout: 30,
        backfill: true,
        has_api_key: false,
      },
      visionConfig: {
        provider_type: '',
        base_url: '',
        model: '',
        max_tokens: 4096,
        has_api_key: false,
      },

      setTheme: (theme) => set({ theme }),
      setAgentMode: (mode) => set({ agentMode: mode }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      toggleThinking: () => set((s) => ({ showThinking: !s.showThinking })),
      toggleSystemInject: () => set((s) => ({ showSystemInject: !s.showSystemInject })),
      toggleAutoScroll: () => set((s) => ({ autoScroll: !s.autoScroll })),
      setModel: (model) => {
        set({ selectedModel: model })
        // Sync to backend DB
        const um = get().utilityModel
        configApi.updateDefaultModel({ selected_model: model, utility_model: um }).catch((e) =>
          console.error('Failed to persist default model:', e)
        )
      },
      setUtilityModel: (model) => {
        set({ utilityModel: model })
        // Sync to backend DB
        const sm = get().selectedModel
        configApi.updateDefaultModel({ selected_model: sm, utility_model: model }).catch((e) =>
          console.error('Failed to persist utility model:', e)
        )
      },

      fetchProviders: async () => {
        try {
          const providers = await providerApi.list()
          set({ providers: providers || [] })
        } catch (e) {
          console.error('Failed to fetch providers:', e)
          set({ providers: [] })
        }
      },

      addProvider: async (data) => {
        await providerApi.add(data)
        await get().fetchProviders()
      },

      updateProvider: async (name, data) => {
        await providerApi.update(name, data)
        await get().fetchProviders()
      },

      removeProvider: async (name) => {
        await providerApi.remove(name)
        set((s) => ({
          providers: s.providers.filter((p) => p.name !== name),
        }))
      },

      fetchConfig: async () => {
        try {
          const cfg = await configApi.get()
          const agent = cfg.agent as Record<string, unknown> | undefined
          if (agent?.work_dir) {
            set({ workDir: agent.work_dir as string })
          }
          if (agent) {
            set({
              agentConfig: {
                max_tool_rounds: (agent.max_tool_rounds as number) || 200,
                compaction_threshold: (agent.compaction_threshold as number) || 0.75,
                compaction_interval: (agent.compaction_interval as number) || 20,
                keep_recent_rounds: (agent.keep_recent_rounds as number) || 10,
              },
            })
          }
          if (typeof cfg.tool_dir === 'string' && cfg.tool_dir) {
            set({ toolDir: cfg.tool_dir })
          }
          // Load persisted model selection from backend (overrides localStorage)
          if (typeof cfg.selected_model === 'string') {
            set({ selectedModel: cfg.selected_model })
          }
          if (typeof cfg.utility_model === 'string' && cfg.utility_model) {
            set({ utilityModel: cfg.utility_model })
          }
        } catch (e) {
          console.error('Failed to fetch config:', e)
        }
      },

      setWorkDir: async (dir: string) => {
        await configApi.updateWorkDir(dir)
        set({ workDir: dir })
      },

      setToolDir: async (dir: string) => {
        await configApi.updateToolDir(dir)
        set({ toolDir: dir })
      },

      fetchAgentConfig: async () => {
        try {
          const cfg = await configApi.get()
          const agent = cfg.agent as Record<string, unknown> | undefined
          if (agent) {
            set({
              agentConfig: {
                max_tool_rounds: (agent.max_tool_rounds as number) || 200,
                compaction_threshold: (agent.compaction_threshold as number) || 0.75,
                compaction_interval: (agent.compaction_interval as number) || 20,
                keep_recent_rounds: (agent.keep_recent_rounds as number) || 10,
              },
            })
          }
        } catch (e) {
          console.error('Failed to fetch agent config:', e)
        }
      },

      updateAgentConfig: async (data) => {
        const res = await configApi.updateAgentConfig(data)
        set({
          agentConfig: {
            max_tool_rounds: res.max_tool_rounds,
            compaction_threshold: res.compaction_threshold,
            compaction_interval: res.compaction_interval,
            keep_recent_rounds: res.keep_recent_rounds,
          },
        })
      },

      fetchEmbeddingConfig: async () => {
        try {
          const cfg = await configApi.getEmbeddingConfig()
          set({ embeddingConfig: cfg })
        } catch (e) {
          console.error('Failed to fetch embedding config:', e)
        }
      },

      updateEmbeddingConfig: async (data) => {
        const res = await configApi.updateEmbeddingConfig(data)
        set({
          embeddingConfig: {
            enabled: res.enabled,
            base_url: res.base_url,
            model: res.model,
            dimensions: res.dimensions,
            timeout: res.timeout,
            backfill: res.backfill,
            has_api_key: res.has_api_key,
          },
        })
      },

      fetchVisionConfig: async () => {
        try {
          const cfg = await configApi.getVisionConfig()
          set({ visionConfig: cfg })
        } catch (e) {
          console.error('Failed to fetch vision config:', e)
        }
      },

      updateVisionConfig: async (data) => {
        const res = await configApi.updateVisionConfig(data)
        set({
          visionConfig: {
            provider_type: res.provider_type,
            base_url: res.base_url,
            model: res.model,
            max_tokens: res.max_tokens,
            has_api_key: res.has_api_key,
          },
        })
      },
    }),
    {
      name: 'ctf-agent-settings',
      partialize: (s) => ({
        theme: s.theme,
        sidebarCollapsed: s.sidebarCollapsed,
        showThinking: s.showThinking,
        showSystemInject: s.showSystemInject,
        autoScroll: s.autoScroll,
        agentMode: s.agentMode,
        selectedModel: s.selectedModel,
        utilityModel: s.utilityModel,
      }),
    }
  )
)
