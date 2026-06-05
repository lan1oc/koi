import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { wsService } from '../services/websocket'
import { pipelineApi } from '../services/api'
import type { PipelineResult, PipelineConfig } from '../types'

export interface PipelineEntry {
  pipelineId: string
  running: boolean
  current: number
  total: number
  results: PipelineResult[]
  startedAt: number | null
  totalDurationMs: number
  config: PipelineConfig
  competitionId?: string
  label?: string
}

interface PipelineState {
  pipelines: PipelineEntry[]
  minimized: boolean

  startPipeline: (
    challengeIds: string[],
    challenges: { id: string; title: string }[],
    model?: string,
    config?: Partial<PipelineConfig>,
    competitionId?: string,
    label?: string
  ) => Promise<string | null>
  stopPipeline: (pipelineId: string) => Promise<void>
  dismiss: (pipelineId: string) => void
  dismissAll: () => void
  setMinimized: (v: boolean) => void
  initWS: () => () => void
  getElapsedMs: (pipelineId: string) => number
  restoreFromBackend: () => Promise<void>
  getPipelineForCompetition: (competitionId: string) => PipelineEntry | null
  getActivePipeline: () => PipelineEntry | null
}

const defaultConfig: PipelineConfig = { max_rounds: 0, max_time_per_challenge: 0, retry_failed: false, skip_solved: true, max_concurrent: 0, category_concurrency: {}, arena_model_b: '' }

export const usePipelineStore = create<PipelineState>()(
  persist(
    (set, get) => ({
      pipelines: [],
      minimized: false,

      startPipeline: async (challengeIds, challenges, model, config, competitionId, label) => {
        try {
          const mergedConfig: PipelineConfig = {
            max_rounds: config?.max_rounds ?? 0,
            max_time_per_challenge: config?.max_time_per_challenge ?? 0,
            retry_failed: config?.retry_failed ?? false,
            skip_solved: config?.skip_solved ?? true,
            max_concurrent: config?.max_concurrent ?? 0,
            category_concurrency: config?.category_concurrency ?? {},
            arena_model_b: config?.arena_model_b ?? '',
          }
          const { pipeline_id, total } = await pipelineApi.start(challengeIds, model, mergedConfig)
          const newEntry: PipelineEntry = {
            pipelineId: pipeline_id,
            running: true,
            total,
            current: 0,
            startedAt: Date.now(),
            totalDurationMs: 0,
            config: mergedConfig,
            competitionId,
            label,
            results: challengeIds.map((id) => {
              const ch = challenges.find((c) => c.id === id)
              return { challenge_id: id, challenge_title: ch?.title || id, status: 'pending' as const }
            }),
          }
          set((s) => ({ pipelines: [...s.pipelines, newEntry], minimized: false }))
          return pipeline_id
        } catch (err) {
          console.error('Failed to start pipeline:', err)
          return null
        }
      },

      stopPipeline: async (pipelineId) => {
        try {
          await pipelineApi.stop(pipelineId)
          set((s) => ({
            pipelines: s.pipelines.map((p) =>
              p.pipelineId === pipelineId ? { ...p, running: false } : p
            ),
          }))
        } catch (err) {
          console.error('Failed to stop pipeline:', err)
        }
      },

      dismiss: (pipelineId) => {
        set((s) => ({ pipelines: s.pipelines.filter((p) => p.pipelineId !== pipelineId) }))
      },

      dismissAll: () => set({ pipelines: [] }),

      setMinimized: (v) => set({ minimized: v }),

      getElapsedMs: (pipelineId) => {
        const p = get().pipelines.find((e) => e.pipelineId === pipelineId)
        if (!p) return 0
        if (!p.running && p.totalDurationMs > 0) return p.totalDurationMs
        if (!p.startedAt) return 0
        return Date.now() - p.startedAt
      },

      getPipelineForCompetition: (competitionId) => {
        const { pipelines } = get()
        const matches = pipelines.filter((p) => p.competitionId === competitionId)
        if (matches.length === 0) return null
        return (
          matches.find((p) => p.running) ||
          matches.reduce((a, b) => ((a.startedAt || 0) > (b.startedAt || 0) ? a : b))
        )
      },

      getActivePipeline: () => {
        const { pipelines } = get()
        return pipelines.find((p) => p.running) || (pipelines.length > 0 ? pipelines[pipelines.length - 1] : null)
      },

      restoreFromBackend: async () => {
        try {
          const backendPipelines = await pipelineApi.status()
          if (!backendPipelines || backendPipelines.length === 0) {
            set((s) => ({ pipelines: s.pipelines.map((p) => p.running ? { ...p, running: false } : p) }))
            return
          }
          set((s) => {
            const backendMap = new Map(backendPipelines.map((p: any) => [p.id, p]))
            const existingIds = new Set(s.pipelines.map((p) => p.pipelineId))
            const newEntries: PipelineEntry[] = []

            for (const bp of backendPipelines) {
              if (existingIds.has(bp.id)) continue
              const isRunning = bp.status === 'running'
              const startTs = bp.started_at ? new Date(bp.started_at).getTime() : Date.now()
              const durationMs = bp.completed_at ? new Date(bp.completed_at).getTime() - startTs : 0
              newEntries.push({
                pipelineId: bp.id,
                running: isRunning,
                current: bp.current,
                total: bp.total,
                results: (bp.results || []).map((r: any) => ({
                  challenge_id: r.challenge_id, challenge_title: r.challenge_title,
                  status: r.status, flag: r.flag, duration_ms: r.duration_ms,
                })),
                startedAt: startTs,
                totalDurationMs: isRunning ? 0 : durationMs,
                config: bp.config || { ...defaultConfig },
              })
            }

            return {
              pipelines: [
                ...s.pipelines.map((p) => {
                  const bp = backendMap.get(p.pipelineId)
                  if (!bp) return p.running ? { ...p, running: false } : p
                  const isRunning = bp.status === 'running'
                  const startTs = bp.started_at ? new Date(bp.started_at).getTime() : p.startedAt || Date.now()
                  const durationMs = bp.completed_at ? new Date(bp.completed_at).getTime() - startTs : 0
                  return {
                    ...p, running: isRunning, current: bp.current, total: bp.total,
                    startedAt: startTs, totalDurationMs: isRunning ? 0 : durationMs,
                    config: bp.config || p.config,
                    results: (bp.results || []).map((r: any) => ({
                      challenge_id: r.challenge_id, challenge_title: r.challenge_title,
                      status: r.status, flag: r.flag, duration_ms: r.duration_ms,
                    })),
                  }
                }),
                ...newEntries,
              ],
            }
          })
        } catch (e) {
          console.error('Failed to restore pipeline status:', e)
        }
      },

      initWS: () => {
        get().restoreFromBackend()

        const unsub = wsService.onAll((event: any) => {
          if (!event.pipeline_id) return
          const { pipelines } = get()
          const exists = pipelines.some((p) => p.pipelineId === event.pipeline_id)

          if (event.type === 'pipeline_start' && !exists) {
            get().restoreFromBackend()
            return
          }

          if (!exists) return

          switch (event.type) {
            case 'pipeline_challenge_start':
              set((s) => ({
                pipelines: s.pipelines.map((p) =>
                  p.pipelineId !== event.pipeline_id ? p : {
                    ...p, current: event.current || p.current,
                    results: p.results.map((r) =>
                      r.challenge_id === event.challenge_id ? { ...r, status: 'solving' as const } : r
                    ),
                  }
                ),
              }))
              break

            case 'pipeline_challenge_end':
              set((s) => ({
                pipelines: s.pipelines.map((p) =>
                  p.pipelineId !== event.pipeline_id ? p : {
                    ...p, current: event.current || p.current,
                    results: p.results.map((r) =>
                      r.challenge_id === event.challenge_id
                        ? { ...r, status: (event.flag_found ? 'solved' : 'failed') as 'solved' | 'failed',
                            flag: event.flag_found || undefined, duration_ms: event.duration_ms || 0,
                            session_id: event.session_id || undefined }
                        : r
                    ),
                  }
                ),
              }))
              break

            case 'pipeline_challenge_skip':
              set((s) => ({
                pipelines: s.pipelines.map((p) =>
                  p.pipelineId !== event.pipeline_id ? p : {
                    ...p, current: event.current || p.current,
                    results: p.results.map((r) =>
                      r.challenge_id === event.challenge_id ? { ...r, status: 'skipped' as const } : r
                    ),
                  }
                ),
              }))
              break

            case 'pipeline_end':
            case 'pipeline_stopped':
              set((s) => ({
                pipelines: s.pipelines.map((p) =>
                  p.pipelineId !== event.pipeline_id ? p : {
                    ...p, running: false, current: event.current || p.current,
                    totalDurationMs: event.duration_ms || (p.startedAt ? Date.now() - p.startedAt : 0),
                  }
                ),
              }))
              break
          }
        })

        return unsub
      },
    }),
    {
      name: 'pipeline-store',
      partialize: (s) => ({
        pipelines: s.pipelines,
        minimized: s.minimized,
      }),
    }
  )
)
