import { create } from 'zustand'
import type {
  ReverseBinary,
  StringsResult,
  DecompileTask,
  AlgorithmSignature,
} from '../types'
import { reverseApi } from '../services/api'

interface ReverseState {
  // Data
  binaries: ReverseBinary[]
  selectedBinary: ReverseBinary | null
  stringsResult: StringsResult | null
  decompileTasks: DecompileTask[]
  algorithms: AlgorithmSignature[]
  terminalId: string | null
  sessionId: string | null
  aiSessionId: string | null

  // UI state
  loading: boolean
  analyzing: boolean
  uploading: boolean
  error: string | null

  // Actions
  loadBinaries: (search?: string) => Promise<void>
  uploadBinary: (file: File) => Promise<ReverseBinary>
  selectBinary: (id: string) => Promise<void>
  clearSelection: () => void
  deleteBinary: (id: string) => Promise<void>
  runAnalysis: (id: string) => Promise<void>
  loadStrings: (id: string, opts?: { min_len?: number; encoding?: string }) => Promise<void>
  startDecompile: (id: string, func?: string) => Promise<DecompileTask>
  pollDecompile: (binaryId: string, taskId: string) => Promise<DecompileTask>
  createTerminal: (id: string) => Promise<{ terminal_id: string; session_id: string }>
  startAIAnalysis: (id: string, opts?: { message?: string; model?: string }) => Promise<string>
  loadAlgorithms: () => Promise<void>
}

export const useReverseStore = create<ReverseState>()((set, get) => ({
  binaries: [],
  selectedBinary: null,
  stringsResult: null,
  decompileTasks: [],
  algorithms: [],
  terminalId: null,
  sessionId: null,
  aiSessionId: null,
  loading: false,
  analyzing: false,
  uploading: false,
  error: null,

  loadBinaries: async (search?: string) => {
    set({ loading: true, error: null })
    try {
      const binaries = await reverseApi.list(search)
      set({ binaries, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  uploadBinary: async (file: File) => {
    set({ uploading: true, error: null })
    try {
      const binary = await reverseApi.upload(file)
      set((s) => ({
        binaries: [binary, ...s.binaries],
        selectedBinary: binary,
        uploading: false,
        // Clear old AI session so the new binary gets a fresh context
        aiSessionId: null,
      }))
      return binary
    } catch (e: any) {
      set({ error: e.message, uploading: false })
      throw e
    }
  },

  selectBinary: async (id: string) => {
    set({ loading: true, error: null, stringsResult: null, decompileTasks: [], terminalId: null, sessionId: null, aiSessionId: null })
    try {
      const binary = await reverseApi.get(id)
      set({
        selectedBinary: binary,
        terminalId: binary.terminal_id || null,
        sessionId: binary.session_id || null,
        // Restore aiSessionId so useEffect can reconnect WS when switching binaries
        aiSessionId: binary.session_id || null,
        loading: false,
      })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  clearSelection: () => {
    set({
      selectedBinary: null,
      stringsResult: null,
      decompileTasks: [],
      terminalId: null,
      sessionId: null,
      aiSessionId: null,
    })
  },

  deleteBinary: async (id: string) => {
    try {
      await reverseApi.delete(id)
      set((s) => ({
        binaries: s.binaries.filter((b) => b.id !== id),
        selectedBinary: s.selectedBinary?.id === id ? null : s.selectedBinary,
      }))
    } catch (e: any) {
      set({ error: e.message })
    }
  },

  runAnalysis: async (id: string) => {
    set({ analyzing: true, error: null })
    try {
      const binary = await reverseApi.analyze(id)
      set((s) => ({
        selectedBinary: binary,
        binaries: s.binaries.map((b) => (b.id === id ? binary : b)),
        analyzing: false,
      }))
    } catch (e: any) {
      set({ error: e.message, analyzing: false })
    }
  },

  loadStrings: async (id: string, opts?) => {
    set({ loading: true, error: null })
    try {
      const result = await reverseApi.getStrings(id, opts)
      set({ stringsResult: result, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  startDecompile: async (id: string, func?: string) => {
    set({ error: null })
    try {
      const task = await reverseApi.decompile(id, func)
      set((s) => ({ decompileTasks: [...s.decompileTasks, task] }))
      return task
    } catch (e: any) {
      set({ error: e.message })
      throw e
    }
  },

  pollDecompile: async (binaryId: string, taskId: string) => {
    const task = await reverseApi.getDecompileResult(binaryId, taskId)
    set((s) => ({
      decompileTasks: s.decompileTasks.map((t) =>
        t.task_id === taskId ? task : t
      ),
    }))
    return task
  },

  createTerminal: async (id: string) => {
    const result = await reverseApi.createTerminal(id)
    set({
      terminalId: result.terminal_id,
      sessionId: result.session_id,
    })
    return result
  },

  startAIAnalysis: async (id: string, opts?) => {
    set({ error: null })
    try {
      const result = await reverseApi.aiAnalyze(id, opts)
      set({ aiSessionId: result.session_id })
      return result.session_id
    } catch (e: any) {
      set({ error: e.message })
      throw e
    }
  },

  loadAlgorithms: async () => {
    try {
      const algorithms = await reverseApi.getAlgorithms()
      set({ algorithms })
    } catch (e: any) {
      set({ error: e.message })
    }
  },
}))
