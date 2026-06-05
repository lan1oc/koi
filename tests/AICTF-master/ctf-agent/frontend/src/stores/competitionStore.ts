import { create } from 'zustand'
import type { Competition, CompetitionFilter } from '../types'
import { competitionApi } from '../services/api'

interface CompetitionState {
  competitions: Competition[]
  loading: boolean
  error: string | null
  filter: CompetitionFilter
  selectedCompetition: Competition | null

  fetchCompetitions: () => Promise<void>
  setFilter: (filter: Partial<CompetitionFilter>) => void
  selectCompetition: (competition: Competition | null) => void
  createCompetition: (data: Partial<Competition>) => Promise<Competition>
  updateCompetition: (id: string, data: Partial<Competition>) => Promise<void>
  deleteCompetition: (id: string) => Promise<void>
  getCompetition: (id: string) => Promise<Competition>
}

export const useCompetitionStore = create<CompetitionState>((set, get) => ({
  competitions: [],
  loading: false,
  error: null,
  filter: {},
  selectedCompetition: null,

  fetchCompetitions: async () => {
    set({ loading: true, error: null })
    try {
      const competitions = await competitionApi.list(get().filter)
      set({ competitions: competitions || [], loading: false })
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  setFilter: (filter) => {
    set((s) => ({ filter: { ...s.filter, ...filter } }))
    get().fetchCompetitions()
  },

  selectCompetition: (competition) => set({ selectedCompetition: competition }),

  createCompetition: async (data) => {
    const competition = await competitionApi.create(data)
    set((s) => ({ competitions: [competition, ...s.competitions] }))
    return competition
  },

  updateCompetition: async (id, data) => {
    const updated = await competitionApi.update(id, data)
    set((s) => ({
      competitions: s.competitions.map((c) => (c.id === id ? updated : c)),
      selectedCompetition: s.selectedCompetition?.id === id ? updated : s.selectedCompetition,
    }))
  },

  deleteCompetition: async (id) => {
    await competitionApi.delete(id)
    set((s) => ({
      competitions: s.competitions.filter((c) => c.id !== id),
      selectedCompetition: s.selectedCompetition?.id === id ? null : s.selectedCompetition,
    }))
  },

  getCompetition: async (id) => {
    return await competitionApi.get(id)
  },
}))
