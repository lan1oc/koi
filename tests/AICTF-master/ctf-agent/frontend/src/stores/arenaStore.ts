import { create } from 'zustand'
import { wsService } from '../services/websocket'
import { arenaApi } from '../services/api'
import type { ArenaSlot } from '../types'

export interface ArenaEntry {
  arenaId: string
  challengeId: string
  models: [string, string]
  running: boolean
  winner: string
  winnerIdx: number
  flag: string
  results: [ArenaSlot, ArenaSlot]
  startedAt: number | null
  durationMs: number
}

interface ArenaStoreState {
  arenas: ArenaEntry[]

  startArena: (
    challengeId: string,
    modelA: string,
    modelB: string,
    utilityModel?: string
  ) => Promise<string | null>
  stopArena: (arenaId: string) => Promise<void>
  dismiss: (arenaId: string) => void
  getArenaForChallenge: (challengeId: string) => ArenaEntry | null
  initWS: () => () => void
  restoreFromBackend: () => Promise<void>
}

export const useArenaStore = create<ArenaStoreState>()((set, get) => ({
  arenas: [],

  startArena: async (challengeId, modelA, modelB, utilityModel) => {
    try {
      const { arena_id, models } = await arenaApi.start(challengeId, modelA, modelB, utilityModel)
      const newEntry: ArenaEntry = {
        arenaId: arena_id,
        challengeId,
        models,
        running: true,
        winner: '',
        winnerIdx: -1,
        flag: '',
        results: [
          { model: models[0], session_id: '', agent_id: '', status: 'running' },
          { model: models[1], session_id: '', agent_id: '', status: 'running' },
        ],
        startedAt: Date.now(),
        durationMs: 0,
      }
      set((s) => ({ arenas: [...s.arenas, newEntry] }))
      return arena_id
    } catch (err) {
      console.error('Failed to start arena:', err)
      return null
    }
  },

  stopArena: async (arenaId) => {
    try {
      await arenaApi.stop(arenaId)
      set((s) => ({
        arenas: s.arenas.map((a) =>
          a.arenaId === arenaId ? { ...a, running: false } : a
        ),
      }))
    } catch (err) {
      console.error('Failed to stop arena:', err)
    }
  },

  dismiss: (arenaId) => {
    set((s) => ({ arenas: s.arenas.filter((a) => a.arenaId !== arenaId) }))
  },

  getArenaForChallenge: (challengeId) => {
    const { arenas } = get()
    return arenas.find((a) => a.challengeId === challengeId) || null
  },

  restoreFromBackend: async () => {
    try {
      const states = await arenaApi.status()
      if (!states || states.length === 0) return
      const backendEntries: ArenaEntry[] = states.map((s) => ({
        arenaId: s.id,
        challengeId: s.challenge_id,
        models: s.models,
        running: s.status === 'running',
        winner: s.winner,
        winnerIdx: s.winner_idx,
        flag: s.flag || '',
        results: s.results,
        startedAt: new Date(s.started_at).getTime(),
        durationMs: s.duration_ms || 0,
      }))
      // Merge: update existing entries and add new ones
      set((prev) => {
        const existingIds = new Set(prev.arenas.map((a) => a.arenaId))
        const updated = prev.arenas.map((a) => {
          const fresh = backendEntries.find((b) => b.arenaId === a.arenaId)
          return fresh ?? a
        })
        const added = backendEntries.filter((b) => !existingIds.has(b.arenaId))
        return { arenas: [...updated, ...added] }
      })
    } catch {
      // ignore
    }
  },

  initWS: () => {
    const unsubStart = wsService.on('arena_start', (event) => {
      // Arena started (could be from another client)
      const arenaId = typeof event.data === 'string' ? event.data : ''
      if (!arenaId) return
      const existing = get().arenas.find((a) => a.arenaId === arenaId)
      if (existing) return // already tracked
    })

    const unsubWinner = wsService.on('arena_winner', (event) => {
      const arenaId = typeof event.data === 'string' ? event.data : ''
      if (!arenaId) return
      set((s) => ({
        arenas: s.arenas.map((a) => {
          if (a.arenaId !== arenaId) return a
          const winnerModel = event.model || ''
          const winnerIdx = a.models[0] === winnerModel ? 0 : 1
          const results = [...a.results] as [ArenaSlot, ArenaSlot]
          results[winnerIdx] = { ...results[winnerIdx], status: 'won', flag: event.flag_found || '' }
          results[1 - winnerIdx] = { ...results[1 - winnerIdx], status: 'lost' }
          return {
            ...a,
            winner: winnerModel,
            winnerIdx,
            flag: event.flag_found || '',
            results,
          }
        }),
      }))
    })

    const unsubEnd = wsService.on('arena_end', (event) => {
      const arenaId = typeof event.data === 'string' ? event.data : ''
      if (!arenaId) return
      set((s) => ({
        arenas: s.arenas.map((a) =>
          a.arenaId === arenaId
            ? {
                ...a,
                running: false,
                flag: event.flag_found || a.flag,
                durationMs: (event as unknown as Record<string, unknown>).duration_ms as number || 0,
              }
            : a
        ),
      }))
    })

    const unsubStopped = wsService.on('arena_stopped', (event) => {
      const arenaId = typeof event.data === 'string' ? event.data : ''
      if (!arenaId) return
      set((s) => ({
        arenas: s.arenas.map((a) =>
          a.arenaId === arenaId ? { ...a, running: false } : a
        ),
      }))
    })

    const unsubSlotStart = wsService.on('arena_slot_start', (event) => {
      const arenaId = typeof event.data === 'string' ? event.data : ''
      if (!arenaId) return
      set((s) => ({
        arenas: s.arenas.map((a) => {
          if (a.arenaId !== arenaId) return a
          const model = event.model || ''
          const idx = a.models[0] === model ? 0 : 1
          const results = [...a.results] as [ArenaSlot, ArenaSlot]
          results[idx] = {
            ...results[idx],
            session_id: event.session_id || '',
            agent_id: event.agent_id || '',
            status: 'running',
          }
          return { ...a, results }
        }),
      }))
    })

    return () => {
      unsubStart()
      unsubWinner()
      unsubEnd()
      unsubStopped()
      unsubSlotStart()
    }
  },
}))
