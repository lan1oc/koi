import { create } from 'zustand'
import type { Challenge, ChallengeFilter, ChallengeCategory, ChallengeStatus } from '../types'
import { challengeApi } from '../services/api'

interface ChallengeState {
  challenges: Challenge[]
  totalCount: number
  currentPage: number
  pageSize: number
  loading: boolean
  error: string | null
  filter: ChallengeFilter
  selectedChallenge: Challenge | null

  // Persisted UI filter state (survives navigation)
  catFilter: string
  statusFilter: string
  searchQuery: string
  // Per-category challenge counts (from unfiltered fetch)
  categoryCounts: Record<string, number>

  // Actions
  fetchChallenges: () => Promise<void>
  fetchChallengesPaginated: (page?: number) => Promise<void>
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  setFilter: (filter: Partial<ChallengeFilter>) => void
  setCatFilter: (cat: string) => void
  setStatusFilter: (status: string) => void
  setSearchQuery: (q: string) => void
  refreshCategoryCounts: (competitionId?: string) => Promise<void>
  selectChallenge: (challenge: Challenge | null) => void
  createChallenge: (data: Partial<Challenge>) => Promise<Challenge>
  updateChallenge: (id: string, data: Partial<Challenge>) => Promise<void>
  updateChallengeStatus: (id: string, status: string, flag?: string) => Promise<void>
  deleteChallenge: (id: string) => Promise<void>
  getChallenge: (id: string) => Promise<Challenge>
}

export const useChallengeStore = create<ChallengeState>((set, get) => ({
  challenges: [],
  totalCount: 0,
  currentPage: 1,
  pageSize: 24,
  loading: false,
  error: null,
  filter: {},
  selectedChallenge: null,
  catFilter: '',
  statusFilter: '',
  searchQuery: '',
  categoryCounts: {},

  fetchChallenges: async () => {
    set({ loading: true, error: null })
    try {
      const challenges = await challengeApi.list(get().filter)
      set({ challenges: challenges || [], totalCount: (challenges || []).length, loading: false })
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  fetchChallengesPaginated: async (page?: number) => {
    const state = get()
    const p = page ?? state.currentPage
    set({ loading: true, error: null, currentPage: p })
    try {
      const result = await challengeApi.listPaginated({
        ...state.filter,
        limit: state.pageSize,
        offset: (p - 1) * state.pageSize,
      })
      set({ challenges: result.items || [], totalCount: result.total, loading: false })
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  setPage: (page) => {
    set({ currentPage: page })
    get().fetchChallengesPaginated(page)
  },

  setPageSize: (size) => {
    set({ pageSize: size, currentPage: 1 })
    get().fetchChallengesPaginated(1)
  },

  setFilter: (filter) => {
    set({ filter, currentPage: 1 })
    get().fetchChallenges()
  },

  setCatFilter: (cat) => set({ catFilter: cat }),
  setStatusFilter: (status) => set({ statusFilter: status }),
  setSearchQuery: (q) => set({ searchQuery: q }),

  refreshCategoryCounts: async (competitionId) => {
    try {
      const all = await challengeApi.list({ competition_id: competitionId })
      const counts: Record<string, number> = {}
      for (const c of (all || [])) {
        const cat = c.category || 'misc'
        counts[cat] = (counts[cat] || 0) + 1
      }
      set({ categoryCounts: counts })
    } catch { /* ignore */ }
  },

  selectChallenge: (challenge) => set({ selectedChallenge: challenge }),

  createChallenge: async (data) => {
    const challenge = await challengeApi.create(data)
    set((s) => ({ challenges: [challenge, ...s.challenges] }))
    return challenge
  },

  updateChallenge: async (id, data) => {
    const updated = await challengeApi.update(id, data)
    set((s) => ({
      challenges: s.challenges.map((c) => (c.id === id ? updated : c)),
      selectedChallenge: s.selectedChallenge?.id === id ? updated : s.selectedChallenge,
    }))
  },

  updateChallengeStatus: async (id, status, flag?) => {
    const updated = await challengeApi.updateStatus(id, status, flag)
    set((s) => ({
      challenges: s.challenges.map((c) => (c.id === id ? updated : c)),
      selectedChallenge: s.selectedChallenge?.id === id ? updated : s.selectedChallenge,
    }))
  },

  deleteChallenge: async (id) => {
    await challengeApi.delete(id)
    set((s) => ({
      challenges: s.challenges.filter((c) => c.id !== id),
      selectedChallenge: s.selectedChallenge?.id === id ? null : s.selectedChallenge,
    }))
  },

  getChallenge: async (id) => {
    const challenge = await challengeApi.get(id)
    return challenge
  },
}))

// ─── Stats helpers ───
export function getCategoryStats(challenges: Challenge[]): Record<string, { total: number; solved: number }> {
  const list = challenges || []
  const stats: Record<string, { total: number; solved: number }> = {}
  for (const c of list) {
    const cat = c.category || 'misc'
    if (!stats[cat]) stats[cat] = { total: 0, solved: 0 }
    stats[cat].total++
    if (c.status === 'solved') stats[cat].solved++
  }
  return stats
}

export function getStatusCounts(challenges: Challenge[]): Record<ChallengeStatus, number> {
  const list = challenges || []
  return {
    unsolved: list.filter((c) => c.status === 'unsolved').length,
    in_progress: list.filter((c) => c.status === 'in_progress').length,
    solved: list.filter((c) => c.status === 'solved').length,
    failed: list.filter((c) => c.status === 'failed').length,
  }
}
