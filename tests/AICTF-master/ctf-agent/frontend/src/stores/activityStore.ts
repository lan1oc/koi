import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { wsService } from '../services/websocket'
import { agentApi } from '../services/api'
import { useNotificationStore } from './notificationStore'
import type { WSEvent, Challenge, AskUserQuestion } from '../types'

export interface ActivityEntry {
  id: string
  agentId: string
  challengeId: string
  challengeTitle: string
  type: 'tool_call' | 'content' | 'thinking' | 'status' | 'system_inject' | 'ask_user'
  systemInjectType?: string
  toolCallId?: string
  toolName?: string
  toolArgs?: string
  toolOutput?: string
  toolStatus?: 'running' | 'completed' | 'failed'
  content?: string
  timestamp: number
  duration?: number
}

export interface ActiveAgent {
  id: string
  challengeId: string
  challengeTitle: string
  model: string
  mode?: string
  sessionId: string
  running: boolean
  generatingWriteup?: boolean
  currentTool?: string
  rounds: number
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

interface ActivityState {
  entries: ActivityEntry[]
  agents: ActiveAgent[]
  pendingQuestions: Record<string, AskUserQuestion>  // agentId -> pending question

  // Historical token totals (persisted across sessions)
  historyPromptTokens: number
  historyCompletionTokens: number
  historyTotalTokens: number

  // Tracking state (not persisted)
  _challengeMap: Record<string, string>       // challengeId -> title
  _agentChallengeMap: Record<string, string>   // agentId -> challengeId
  _challengeIds: string[]
  _competitionId: string
  _parseAgentId: string | null
  _wsConnected: boolean
  _pollTimer: ReturnType<typeof setInterval> | null

  // Actions
  setChallenges: (challenges: Challenge[], competitionId: string) => void
  setParseAgentId: (id: string | null) => void
  connect: () => void
  disconnect: () => void
  clearEntries: () => void
  stopAgent: (agentId: string) => Promise<void>
  respondToAgentQuestion: (agentId: string, sessionId: string, answer: string) => Promise<void>
}

const MAX_ENTRIES = 200

let wsUnsub: (() => void) | null = null
let connectRefCount = 0

// --- Delta batching: preserve arrival order across thinking/content streams ---
interface DeltaSegment {
  agentId: string
  type: 'content' | 'thinking'
  text: string
  challengeId: string
  challengeTitle: string
}

const deltaBuffer: DeltaSegment[] = []
let deltaFlushTimer: ReturnType<typeof setTimeout> | null = null
const DELTA_FLUSH_INTERVAL = 150 // ms — flush buffered deltas every 150ms

export const useActivityStore = create<ActivityState>()(
  persist(
    (set, get) => ({
      entries: [],
      agents: [],
      pendingQuestions: {},
      historyPromptTokens: 0,
      historyCompletionTokens: 0,
      historyTotalTokens: 0,
      _challengeMap: {},
      _agentChallengeMap: {},
      _challengeIds: [],
      _competitionId: '',
      _parseAgentId: null,
      _wsConnected: false,
      _pollTimer: null,

      setChallenges: (challenges, competitionId) => {
        const map: Record<string, string> = {}
        const ids: string[] = []
        challenges.forEach((c) => {
          map[c.id] = c.title
          ids.push(c.id)
        })
        if (competitionId) {
          map[`parse-${competitionId}`] = 'AI 解析题目'
          ids.push(`parse-${competitionId}`)
        }
        set({
          _challengeMap: map,
          _challengeIds: ids,
          _competitionId: competitionId,
        })
      },

      setParseAgentId: (id) => {
        set({ _parseAgentId: id })
        if (id) {
          const { _competitionId, _agentChallengeMap } = get()
          if (_competitionId) {
            set({
              _agentChallengeMap: {
                ..._agentChallengeMap,
                [id]: `parse-${_competitionId}`,
              },
            })
          }
        }
      },

      connect: () => {
        connectRefCount++
        const state = get()
        if (state._wsConnected) return

        wsService.connect()
        if (wsService.connected) {
          wsService.subscribe('*')
        }

        // Subscribe to WS events
        wsUnsub = wsService.onAll((event: WSEvent) => {
          handleWSEvent(event, get, set)
        })

        // Start polling active agents + WS health check
        const poll = async () => {
          // Safety net: if WebSocket was closed externally (e.g. by agentStore),
          // reconnect and re-subscribe so Activity events keep flowing
          if (!wsService.connected) {
            wsService.connect()
            if (wsService.connected) {
              wsService.subscribe('*')
            }
          }

          try {
            const { _challengeIds, _challengeMap, _agentChallengeMap } = get()
            const challengeIdSet = new Set(_challengeIds)
            const runners = await agentApi.status()
            // When specific challenge IDs are registered, filter to those + any parse agents.
            // Parse agents have challenge_id like "parse-xxx" and should always be included.
            const relevant = challengeIdSet.size > 0
              ? (runners || []).filter((r) => challengeIdSet.has(r.challenge_id) || r.challenge_id.startsWith('parse-'))
              : (runners || [])
            const newAgentMap = { ..._agentChallengeMap }
            const newChallengeMap: Record<string, string> = {}

            const updated: ActiveAgent[] = relevant.map((r) => {
              newAgentMap[r.id] = r.challenge_id
              // Auto-register unknown challenge IDs (e.g. parse-xxx) into the title map
              if (!_challengeMap[r.challenge_id]) {
                const isParseAgent = r.challenge_id.startsWith('parse-')
                newChallengeMap[r.challenge_id] = isParseAgent ? 'AI 解析题目' : r.challenge_id
              }
              const existing = get().agents.find((a) => a.id === r.id)
              return {
                id: r.id,
                challengeId: r.challenge_id,
                challengeTitle: newChallengeMap[r.challenge_id] || _challengeMap[r.challenge_id] || r.challenge_id,
                model: r.model,
                mode: r.mode,
                sessionId: r.session_id,
                running: r.running,
                currentTool: existing?.currentTool,
                rounds: existing?.rounds || 0,
                promptTokens: existing?.promptTokens || 0,
                completionTokens: existing?.completionTokens || 0,
                totalTokens: existing?.totalTokens || 0,
              }
            })

            // Merge: keep agents that are locally marked running=true (driven by WS events)
            // but aren't in the poll result yet — avoids flicker during thinking/streaming.
            const pollIds = new Set(updated.map((a) => a.id))
            const localRunning = get().agents.filter(
              (a) => a.running && !pollIds.has(a.id)
            )
            const merged = [...updated, ...localRunning]

            set({
              agents: merged,
              _agentChallengeMap: newAgentMap,
              _challengeMap: { ..._challengeMap, ...newChallengeMap },
            })
          } catch {
            // ignore
          }
        }
        poll()
        const timer = setInterval(poll, 1500)

        set({ _wsConnected: true, _pollTimer: timer })
      },

      disconnect: () => {
        connectRefCount = Math.max(0, connectRefCount - 1)
        if (connectRefCount > 0) return // other consumers still active
        const { _pollTimer } = get()
        if (wsUnsub) {
          wsUnsub()
          wsUnsub = null
        }
        if (_pollTimer) {
          clearInterval(_pollTimer)
        }
        if (deltaFlushTimer) {
          clearTimeout(deltaFlushTimer)
          deltaFlushTimer = null
        }
        deltaBuffer.length = 0
        set({ _wsConnected: false, _pollTimer: null })
      },

      clearEntries: () => set({ entries: [], agents: [] }),

      stopAgent: async (agentId) => {
        try {
          await agentApi.stop(agentId)
          set((s) => ({
            agents: s.agents.map((a) =>
              a.id === agentId ? { ...a, running: false, currentTool: undefined } : a
            ),
          }))
        } catch (err) {
          console.error('Failed to stop agent:', err)
        }
      },

      respondToAgentQuestion: async (agentId, sessionId, answer) => {
        try {
          await agentApi.respondToQuestion(sessionId, answer)
          // Clear pending question immediately for responsive UI
          set((s) => {
            const next = { ...s.pendingQuestions }
            delete next[agentId]
            return { pendingQuestions: next }
          })
        } catch (err) {
          console.error('Failed to respond to question:', err)
        }
      },
    }),
    {
      name: 'ctf-activity',
      storage: {
        getItem: (name) => {
          const raw = sessionStorage.getItem(name)
          return raw ? JSON.parse(raw) : null
        },
        setItem: (name, value) => {
          sessionStorage.setItem(name, JSON.stringify(value))
        },
        removeItem: (name) => {
          sessionStorage.removeItem(name)
        },
      },
      partialize: (s) => ({
        entries: s.entries,
        agents: s.agents,
        historyPromptTokens: s.historyPromptTokens,
        historyCompletionTokens: s.historyCompletionTokens,
        historyTotalTokens: s.historyTotalTokens,
        _challengeMap: s._challengeMap,
        _agentChallengeMap: s._agentChallengeMap,
        _challengeIds: s._challengeIds,
        _competitionId: s._competitionId,
        _parseAgentId: s._parseAgentId,
      } as unknown as ActivityState),
    }
  )
)

function addEntry(
  set: (fn: (s: ActivityState) => Partial<ActivityState>) => void,
  partial: Omit<ActivityEntry, 'id' | 'timestamp'>
) {
  set((s) => {
    const next = [
      ...s.entries,
      {
        ...partial,
        id: `entry-${Date.now()}-${Math.random()}`,
        timestamp: Date.now(),
      },
    ]
    return { entries: next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next }
  })
}

/**
 * Buffer a content/thinking delta instead of immediately updating the store.
 * A periodic timer flushes all buffered deltas in one batch update.
 */
function bufferDelta(
  type: 'content' | 'thinking',
  agentId: string,
  text: string,
  challengeId: string,
  challengeTitle: string
) {
  const last = deltaBuffer[deltaBuffer.length - 1]
  if (last && last.agentId === agentId && last.type === type) {
    last.text += text
    last.challengeId = challengeId
    last.challengeTitle = challengeTitle
  } else {
    deltaBuffer.push({
      agentId,
      type,
      text,
      challengeId,
      challengeTitle,
    })
  }

  // Schedule flush if not already scheduled
  if (!deltaFlushTimer) {
    deltaFlushTimer = setTimeout(() => {
      deltaFlushTimer = null
      flushDeltas()
    }, DELTA_FLUSH_INTERVAL)
  }
}

function hasPendingDeltas(): boolean {
  return deltaBuffer.length > 0
}

function appendDeltaSegments(segments: DeltaSegment[]) {
  if (segments.length === 0) return

  useActivityStore.setState((s) => {
    const newEntries = [...s.entries]

    for (const segment of segments) {
      const lastEntry = newEntries[newEntries.length - 1]
      if (
        lastEntry &&
        lastEntry.agentId === segment.agentId &&
        lastEntry.type === segment.type
      ) {
        newEntries[newEntries.length - 1] = {
          ...lastEntry,
          content: (lastEntry.content || '') + segment.text,
        }
      } else {
        newEntries.push({
          id: `entry-${Date.now()}-${Math.random()}`,
          agentId: segment.agentId,
          challengeId: segment.challengeId,
          challengeTitle: segment.challengeTitle,
          type: segment.type,
          content: segment.text,
          timestamp: Date.now(),
        })
      }
    }

    const trimmed = newEntries.length > MAX_ENTRIES ? newEntries.slice(-MAX_ENTRIES) : newEntries
    return { entries: trimmed }
  })
}

function flushDeltasForAgent(agentId: string) {
  const flushed = deltaBuffer.filter((segment) => segment.agentId === agentId)
  if (flushed.length === 0) return
  const remaining = deltaBuffer.filter((segment) => segment.agentId !== agentId)
  deltaBuffer.length = 0
  deltaBuffer.push(...remaining)

  if (!hasPendingDeltas() && deltaFlushTimer) {
    clearTimeout(deltaFlushTimer)
    deltaFlushTimer = null
  }

  appendDeltaSegments(flushed)
}

/**
 * Flush all buffered content/thinking deltas into the store in one batch update.
 */
function flushDeltas() {
  const segments = [...deltaBuffer]
  deltaBuffer.length = 0

  // Nothing to flush
  if (segments.length === 0) return
  appendDeltaSegments(segments)
}

function handleWSEvent(
  event: WSEvent,
  get: () => ActivityState,
  set: (fn: (s: ActivityState) => Partial<ActivityState>) => void
) {
  const agentId = event.agent_id
  if (!agentId) return

  const state = get()
  let challengeId = state._agentChallengeMap[agentId]

  // Check if this is the parse agent
  if (!challengeId && state._parseAgentId && agentId === state._parseAgentId && state._competitionId) {
    challengeId = `parse-${state._competitionId}`
    set((s) => ({
      _agentChallengeMap: { ...s._agentChallengeMap, [agentId]: challengeId! },
    }))
  }

  // Try to find challenge from already-polled agents
  if (!challengeId) {
    const agent = state.agents.find(a => a.id === agentId)
    if (agent) {
      challengeId = agent.challengeId
      set((s) => ({
        _agentChallengeMap: { ...s._agentChallengeMap, [agentId]: challengeId! },
      }))
    }
  }

  // Try to resolve from event's challenge_id / challenge_title (e.g. pentest agents)
  if (!challengeId && event.challenge_id) {
    challengeId = event.challenge_id
    const eventTitle = event.challenge_title || challengeId
    set((s) => ({
      _agentChallengeMap: { ...s._agentChallengeMap, [agentId]: challengeId! },
      _challengeMap: { ...s._challengeMap, [challengeId!]: eventTitle },
    }))
  }

  // Auto-discover: if still unknown, accept the event and register the agent on the fly.
  // This handles parse agents and any other agents not pre-registered via setChallenges.
  if (!challengeId) {
    // Use event metadata if available, otherwise generic fallback
    challengeId = event.challenge_id || `unknown-${agentId}`
    const title = event.challenge_title || `Agent ${agentId.slice(0, 8)}`
    set((s) => ({
      _agentChallengeMap: { ...s._agentChallengeMap, [agentId]: challengeId! },
      _challengeMap: { ...s._challengeMap, [challengeId!]: title },
    }))
  }

  // Resolve display title – prefer freshly-set title, then stored map, then event metadata
  const title = get()._challengeMap[challengeId] || event.challenge_title || challengeId

  if (
    event.type !== 'content_delta' &&
    event.type !== 'message_delta' &&
    event.type !== 'thinking_delta' &&
    event.type !== 'token_usage'
  ) {
    flushDeltasForAgent(agentId)
  }

  switch (event.type) {
    case 'agent_start':
      set((s) => {
        const exists = s.agents.find((a) => a.id === agentId)
        if (exists) {
          return {
            agents: s.agents.map((a) =>
              a.id === agentId ? { ...a, running: true, rounds: 0, mode: event.mode || a.mode } : a
            ),
          }
        }
        return {
          agents: [
            ...s.agents,
            {
              id: agentId,
              challengeId: challengeId!,
              challengeTitle: title,
              model: event.model || '',
              mode: event.mode,
              sessionId: event.session_id,
              running: true,
              rounds: 0,
              promptTokens: 0,
              completionTokens: 0,
              totalTokens: 0,
            },
          ],
        }
      })
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: `Agent 开始运行 (${event.model || 'unknown'})`,
      })
      break

    case 'round_start':
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, rounds: a.rounds + 1 } : a
        ),
      }))
      break

    case 'agent_end':
      flushDeltasForAgent(agentId)
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, running: false, currentTool: undefined } : a
        ),
      }))
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: event.flag_found
          ? `Agent 完成！找到 Flag: ${event.flag_found}`
          : 'Agent 运行结束',
      })
      break

    case 'tool_call_start': {
      // Dedup: if entry already exists for this tool_call_id, update args if provided
      if (event.tool_call_id) {
        const existing = state.entries.find(
          (e) => e.type === 'tool_call' && e.toolCallId === event.tool_call_id
        )
        if (existing) {
          // runner.go emits a second tool_call_start with full args after streaming completes
          if (event.tool_args) {
            const newArgs = typeof event.tool_args === 'object'
              ? JSON.stringify(event.tool_args)
              : event.tool_args
            set((s) => ({
              entries: s.entries.map((e) =>
                e.toolCallId === event.tool_call_id && e.type === 'tool_call'
                  ? { ...e, toolArgs: newArgs }
                  : e
              ),
            }))
          }
          break
        }
      }
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, currentTool: event.tool_name } : a
        ),
      }))
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'tool_call',
        toolCallId: event.tool_call_id,
        toolName: event.tool_name,
        toolArgs: typeof event.tool_args === 'object' ? JSON.stringify(event.tool_args) : event.tool_args,
        toolStatus: 'running',
      })
      break
    }

    case 'tool_call_delta': {
      // Accumulate streaming arg fragments into the existing tool call entry
      if (event.tool_call_id && event.content) {
        set((s) => ({
          entries: s.entries.map((e) =>
            e.toolCallId === event.tool_call_id && e.type === 'tool_call'
              ? { ...e, toolArgs: (e.toolArgs || '') + event.content }
              : e
          ),
        }))
      }
      break
    }

    case 'tool_call_end':
      set((s) => {
        const newAgents = s.agents.map((a) => {
          if (a.id === agentId) {
            return { ...a, currentTool: undefined }
          }
          return a
        })
        // Match by tool_call_id for correct parallel tool call handling
        const entries = [...s.entries]
        let matchIdx = -1
        if (event.tool_call_id) {
          matchIdx = entries.findIndex(
            (e) => e.type === 'tool_call' && e.toolCallId === event.tool_call_id
          )
        }
        // Fallback: find last running entry for this agent
        if (matchIdx === -1) {
          const revIdx = [...entries].reverse().findIndex(
            (e) => e.agentId === agentId && e.type === 'tool_call' && e.toolStatus === 'running'
          )
          if (revIdx !== -1) matchIdx = entries.length - 1 - revIdx
        }
        if (matchIdx !== -1) {
          entries[matchIdx] = {
            ...entries[matchIdx],
            toolOutput: event.tool_output,
            toolStatus: event.success ? 'completed' : 'failed',
            duration: Date.now() - entries[matchIdx].timestamp,
          }
        }
        return { agents: newAgents, entries }
      })
      break

    case 'tool_output':
      set((s) => {
        const entries = [...s.entries]
        // Match by tool_call_id for correct parallel tool call handling
        let matchIdx = -1
        if (event.tool_call_id) {
          matchIdx = entries.findIndex(
            (e) => e.type === 'tool_call' && e.toolCallId === event.tool_call_id
          )
        }
        if (matchIdx === -1) {
          const revIdx = [...entries].reverse().findIndex(
            (e) => e.agentId === agentId && e.type === 'tool_call'
          )
          if (revIdx !== -1) matchIdx = entries.length - 1 - revIdx
        }
        if (matchIdx === -1) return {}
        entries[matchIdx] = {
          ...entries[matchIdx],
          toolOutput: event.tool_output,
          toolStatus: event.success ? 'completed' : 'failed',
        }
        return { entries }
      })
      break

    case 'content_delta':
    case 'message_delta': {
      // Buffer deltas and flush periodically (every 150ms) to avoid per-chunk re-renders
      bufferDelta('content', agentId, event.content || '', challengeId, title)
      break
    }

    case 'thinking_delta': {
      // Buffer deltas and flush periodically
      bufferDelta('thinking', agentId, event.content || '', challengeId, title)
      break
    }

    case 'flag_found':
      if (event.flag_found) {
        addEntry(set, {
          agentId,
          challengeId,
          challengeTitle: title,
          type: 'status',
          content: `🎉 找到 Flag: ${event.flag_found}`,
        })
        useNotificationStore.getState().addNotification({
          type: 'flag',
          title: '🎉 Flag 已获取！',
          message: '',
          flag: event.flag_found,
          challengeTitle: title,
        })
      }
      break

    case 'writeup_generating':
      // Keep agent column visible in /activity while writeup is being generated
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, generatingWriteup: true } : a
        ),
      }))
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: '正在生成 Writeup...',
      })
      break

    case 'writeup_generated':
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, generatingWriteup: false } : a
        ),
      }))
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: 'Writeup 生成完成',
      })
      break

    case 'lessons_extracting':
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: '正在提取做题经验...',
      })
      break

    case 'lessons_extracted':
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: '做题经验提取完成',
      })
      break

    case 'token_usage': {
      const pt = event.prompt_tokens || 0
      const ct = event.completion_tokens || 0
      const tt = event.total_tokens || 0
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId
            ? {
                ...a,
                promptTokens: a.promptTokens + pt,
                completionTokens: a.completionTokens + ct,
                totalTokens: a.totalTokens + tt,
              }
            : a
        ),
        historyPromptTokens: s.historyPromptTokens + pt,
        historyCompletionTokens: s.historyCompletionTokens + ct,
        historyTotalTokens: s.historyTotalTokens + tt,
      }))
      break
    }

    case 'error':
      flushDeltasForAgent(agentId)
      set((s) => ({
        agents: s.agents.map((a) =>
          a.id === agentId
            ? { ...a, running: false, currentTool: undefined, generatingWriteup: false }
            : a
        ),
      }))
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: `Error: ${event.error}`,
      })
      break

    case 'planning_phase':
    case 'reflection':
    case 'checkpoint':
    case 'repetition_warning':
    case 'flag_candidate':
    case 'thinking_overflow_hint': {
      const typeMap: Record<string, string> = {
        planning_phase: 'planning',
        reflection: 'reflection',
        checkpoint: 'checkpoint',
        repetition_warning: 'repetition',
        flag_candidate: 'flag_candidate',
        thinking_overflow_hint: 'thinking_hint',
      }
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'system_inject',
        systemInjectType: typeMap[event.type] || 'system',
        content: event.content || '',
      })
      break
    }

    case 'ask_user': {
      // AI is asking the user a question
      try {
        const questionData: AskUserQuestion = typeof event.data === 'string'
          ? JSON.parse(event.data)
          : (event.data as unknown as AskUserQuestion)
        if (questionData && questionData.question) {
          set((s) => ({
            pendingQuestions: { ...s.pendingQuestions, [agentId]: questionData },
          }))
          addEntry(set, {
            agentId,
            challengeId,
            challengeTitle: title,
            type: 'ask_user',
            content: questionData.question,
          })
        }
      } catch {
        addEntry(set, {
          agentId,
          challengeId,
          challengeTitle: title,
          type: 'ask_user',
          content: event.content || 'AI has a question',
        })
      }
      break
    }

    case 'ask_user_responded': {
      // User answered the question — clear pending
      set((s) => {
        const next = { ...s.pendingQuestions }
        delete next[agentId]
        return { pendingQuestions: next }
      })
      addEntry(set, {
        agentId,
        challengeId,
        challengeTitle: title,
        type: 'status',
        content: `用户已回答: ${event.content || ''}`,
      })
      break
    }
  }
}
