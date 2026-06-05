import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  StreamingMessage,
  ToolExecution,
  WSEvent,
  Session,
  TodoItem,
  AskUserQuestion,
  SubAgentTopologyEvent,
} from '../types'
import { wsService } from '../services/websocket'
import { sessionApi, agentApi } from '../services/api'

function isToolFailureOutput(output?: string): boolean {
  if (!output) return false
  const s = output.trim()
  if (!s) return false
  if (s.startsWith('Error:') || s.startsWith('ERROR:') || s.startsWith('BLOCKED:')) return true
  if (/^HTTP\s+\d{3}:/.test(s)) return true
  if (s.includes('[exit:') || s.includes('[error:')) return true
  const lower = s.toLowerCase()
  if (lower.includes('flag incorrect')) return true
  if (lower.includes('rate limited')) return true
  if (lower.includes('competition is paused')) return true
  if (lower.includes('cheat detected')) return true
  return false
}

/** Detect system-injected "user" messages by their content prefix patterns. */
const SYSTEM_INJECT_PREFIXES = [
  '[System',               // reflection, planning, flag detection, thinking overflow
  '[TodoList Reminder',    // periodic todolist reminders
  '[Progress Checkpoint',  // progress checkpoints
  '[SOLVING IDEAS',        // ideas summary injection
]

function isSystemInjectedContent(content: string): boolean {
  const trimmed = content.trimStart()
  return SYSTEM_INJECT_PREFIXES.some(prefix => trimmed.startsWith(prefix))
}

function detectSystemInjectType(content: string): StreamingMessage['systemInjectType'] {
  const t = content.trimStart()
  if (t.startsWith('[System — Mandatory Planning')) return 'planning'
  if (t.startsWith('[System — Progress Review') || t.startsWith('[System — Strategy Review')) return 'reflection'
  if (t.startsWith('[System — Repetitive Pattern')) return 'repetition'
  if (t.startsWith('[System — Flag Detection')) return 'flag_candidate'
  if (t.startsWith('[System Notice]')) return 'thinking_hint'
  if (t.startsWith('[Progress Checkpoint')) return 'checkpoint'
  return 'system'
}

function parseSubAgentEvent(data: WSEvent['data']): SubAgentTopologyEvent | null {
  if (!data) return null
  if (typeof data === 'string') {
    try {
      return JSON.parse(data) as SubAgentTopologyEvent
    } catch {
      return null
    }
  }
  return data as unknown as SubAgentTopologyEvent
}

interface AgentState {
  // Current session
  session: Session | null
  messages: StreamingMessage[]
  currentMessage: StreamingMessage | null
  hasHydrated: boolean
  isRunning: boolean
  isGeneratingWriteup: boolean
  agentId: string | null
  model: string
  rounds: number
  flagFound: string | null
  loadingHistory: boolean
  isFullHistory: boolean

  // Sub-agents
  subAgents: Map<string, { type: string; status: string }>

  // TodoList
  todoItems: TodoItem[]

  // Interactive Q&A
  pendingQuestion: AskUserQuestion | null

  // Actions
  setSession: (session: Session | null) => void
  setAgentId: (id: string | null) => void
  setHasHydrated: (v: boolean) => void
  loadHistory: (sessionId: string) => Promise<void>
  loadFullHistory: (sessionId: string) => Promise<void>
  checkRunning: (sessionId: string) => Promise<void>
  connectWS: (sessionId: string) => void
  disconnectWS: () => void
  sendInput: (content: string) => void
  respondToQuestion: (answer: string) => void
  reset: () => void
  setModel: (model: string) => void

  // Internal
  _handleEvent: (event: WSEvent) => void
}

let wsUnsub: (() => void) | null = null

export const useAgentStore = create<AgentState>()(
  persist(
    (set, get) => ({
      session: null,
      messages: [],
      currentMessage: null,
      hasHydrated: false,
      isRunning: false,
      isGeneratingWriteup: false,
      agentId: null,
      model: '',
      rounds: 0,
      flagFound: null,
      loadingHistory: false,
      isFullHistory: false,
      subAgents: new Map(),
      todoItems: [],
      pendingQuestion: null,

      setSession: (session) => set({
        session,
        todoItems: [],
        pendingQuestion: null,
        flagFound: null,
        subAgents: new Map(),
        rounds: 0,
        currentMessage: null,
      }),
      setAgentId: (id) => set({ agentId: id }),
      setHasHydrated: (v) => set({ hasHydrated: v }),

      loadHistory: async (sessionId) => {
        set({ loadingHistory: true, isFullHistory: false })
        try {
          const history = await sessionApi.messages(sessionId)

          // Build a map of tool_call_id → tool output for merging into assistant messages
          const toolOutputs = new Map<string, { output: string; success: boolean }>()
          for (const m of history) {
            if (m.role === 'tool' && m.tool_call_id) {
              toolOutputs.set(m.tool_call_id, {
                output: m.content,
                success: !isToolFailureOutput(m.content),
              })
            }
          }

          const messages: StreamingMessage[] = history
            .filter((m) => m.role !== 'system' && m.role !== 'tool')
            .map((m, i) => {
              const isSysInject = m.role === 'user' && isSystemInjectedContent(m.content)
              return {
                id: `hist-${i}`,
                role: m.role,
                content: m.content,
                thinking: m.thinking || '',
                toolCalls: m.tool_calls?.map((tc) => {
                  const result = toolOutputs.get(tc.id)
                  return {
                    id: tc.id,
                    name: tc.name,
                    arguments: safeParseArgs(tc.arguments),
                    output: result?.output,
                    status: (result ? (result.success ? 'completed' : 'failed') : 'completed') as 'completed' | 'failed',
                    startTime: Date.now(),
                    endTime: Date.now(),
                  }
                }) || [],
                isStreaming: false,
                timestamp: m.timestamp,
                ...(isSysInject ? { isSystemInject: true, systemInjectType: detectSystemInjectType(m.content) } : {}),
              } as StreamingMessage
            })
          set({ messages, loadingHistory: false, isFullHistory: false })
        } catch (e) {
          console.error('Failed to load history:', e)
          set({ loadingHistory: false })
        }
      },

      loadFullHistory: async (sessionId) => {
        set({ loadingHistory: true })
        try {
          const history = await sessionApi.allMessages(sessionId)

          const toolOutputs = new Map<string, { output: string; success: boolean }>()
          for (const m of history) {
            if (m.role === 'tool' && m.tool_call_id) {
              toolOutputs.set(m.tool_call_id, {
                output: m.content,
                success: !isToolFailureOutput(m.content),
              })
            }
          }

          const messages: StreamingMessage[] = history
            .filter((m) => m.role !== 'system' && m.role !== 'tool')
            .map((m, i) => {
              const isSysInject = m.role === 'user' && isSystemInjectedContent(m.content)
              return {
                id: `full-${i}`,
                role: m.role,
                content: m.content,
                thinking: m.thinking || '',
                toolCalls: m.tool_calls?.map((tc) => {
                  const result = toolOutputs.get(tc.id)
                  return {
                    id: tc.id,
                    name: tc.name,
                    arguments: safeParseArgs(tc.arguments),
                    output: result?.output,
                    status: (result ? (result.success ? 'completed' : 'failed') : 'completed') as 'completed' | 'failed',
                    startTime: Date.now(),
                    endTime: Date.now(),
                  }
                }) || [],
                isStreaming: false,
                timestamp: m.timestamp,
                ...(isSysInject ? { isSystemInject: true, systemInjectType: detectSystemInjectType(m.content) } : {}),
              } as StreamingMessage
            })
          set({ messages, loadingHistory: false, isFullHistory: true })
        } catch (e) {
          console.error('Failed to load full history:', e)
          set({ loadingHistory: false })
        }
      },

      checkRunning: async (sessionId) => {
        try {
          const runners = await agentApi.status()
          const match = (runners || []).find((r) => r.session_id === sessionId && r.running)
          if (match) {
            set({ isRunning: true, agentId: match.id, model: match.model || get().model })
          } else {
            set({ isRunning: false, agentId: null })
          }
        } catch {
          // If status check fails, keep persisted state
        }
      },

      connectWS: (sessionId) => {
        // Unsubscribe previous handler to avoid duplicates
        if (wsUnsub) {
          wsUnsub()
          wsUnsub = null
        }
        wsService.connect(sessionId)
        wsUnsub = wsService.onAll(get()._handleEvent)
      },

      disconnectWS: () => {
        if (wsUnsub) {
          wsUnsub()
          wsUnsub = null
        }
        // Do NOT call wsService.disconnect() here!
        // The WebSocket is a shared resource managed by Layout/activityStore.
        // Closing it here kills all other WS consumers (Activity page, pipeline, etc.)
      },

      sendInput: (content) => {
        const { session, messages } = get()
        if (!session) return

        // Add user message to chat immediately (optimistic UI)
        const userMsg: StreamingMessage = {
          id: `user-${Date.now()}`,
          role: 'user',
          content,
          thinking: '',
          toolCalls: [],
          isStreaming: false,
          timestamp: new Date().toISOString(),
        }
        set({ messages: [...messages, userMsg] })

        // Use REST API for reliability (WebSocket may be disconnected)
        agentApi.sendChat(session.id, content).catch((err) => {
          console.error('sendChat failed, trying WebSocket fallback:', err)
          // Fallback to WebSocket
          wsService.sendUserInput(session.id, content)
        })
      },

      respondToQuestion: (answer) => {
        const { session } = get()
        if (!session) return
        agentApi.respondToQuestion(session.id, answer).then(() => {
          set({ pendingQuestion: null })
        }).catch((err) => {
          console.error('respondToQuestion failed:', err)
        })
      },

      reset: () => {
        if (wsUnsub) {
          wsUnsub()
          wsUnsub = null
        }
        set({
          session: null,
          messages: [],
          currentMessage: null,
          isRunning: false,
          isGeneratingWriteup: false,
          agentId: null,
          rounds: 0,
          flagFound: null,
          loadingHistory: false,
          subAgents: new Map(),
          todoItems: [],
          pendingQuestion: null,
        })
      },

      setModel: (model) => set({ model }),

      _handleEvent: (event: WSEvent) => {
        const { messages, currentMessage, session } = get()
        const subAgentPayload = event.type.startsWith('sub_agent_')
          ? parseSubAgentEvent(event.data)
          : null

        // Filter: only process events for this session (since WS subscribes to '*')
        if (session && event.session_id && event.session_id !== session.id) {
          const isRelatedSubAgent = subAgentPayload &&
            (subAgentPayload.root_session_id === session.id || subAgentPayload.parent_session_id === session.id)
          if (!isRelatedSubAgent) {
            return
          }
        }

        // Helper: check if event is from a sub-agent (not the parent coordinator)
        const parentId = get().agentId
        const isSubAgent = parentId && event.agent_id && event.agent_id !== parentId

        switch (event.type) {
          case 'agent_start': {
            if (isSubAgent) break // sub-agent start — don't override parent state
            set({
              isRunning: true,
              agentId: event.agent_id || parentId,
              model: event.model || get().model || '',
              flagFound: null,
              currentMessage: {
                id: `msg-${Date.now()}`,
                role: 'assistant',
                content: '',
                thinking: '',
                toolCalls: [],
                isStreaming: true,
                timestamp: new Date().toISOString(),
              },
            })
            break
          }

          case 'round_start': {
            // Sub-agent round_start should NOT finalize the coordinator's currentMessage
            if (isSubAgent) break

            // Finalize previous round's message (if any content) and start a new one
            const prev = get().currentMessage
            const msgs = get().messages
            if (prev && (prev.content || prev.toolCalls.length > 0 || prev.thinking)) {
              set({
                messages: [...msgs, { ...prev, isStreaming: false }],
                currentMessage: {
                  id: `msg-${Date.now()}`,
                  role: 'assistant',
                  content: '',
                  thinking: '',
                  toolCalls: [],
                  isStreaming: true,
                  timestamp: new Date().toISOString(),
                },
              })
            }
            break
          }

          case 'content_delta':
          case 'message_delta':
            set((state) => {
              if (!state.currentMessage) return state
              return {
                currentMessage: {
                  ...state.currentMessage,
                  content: state.currentMessage.content + (event.content || ''),
                },
              }
            })
            break

          case 'thinking_delta':
            set((state) => {
              if (!state.currentMessage) return state
              return {
                currentMessage: {
                  ...state.currentMessage,
                  thinking: (state.currentMessage.thinking || '') + (event.content || ''),
                },
              }
            })
            break

          case 'tool_call_start': {
            const tcId = event.tool_call_id || `tc-${Date.now()}`
            const toolName = isSubAgent ? `[sub] ${event.tool_name || ''}` : (event.tool_name || '')
            const parsedArgs = safeParseArgs(event.tool_args || '{}')
            // Use functional set to avoid stale currentMessage from get() snapshot
            set((state) => {
              const cm = state.currentMessage
              if (!cm) return {}
              // If card was already created by an early emit from processStream,
              // update its arguments with the now-complete args and clear streaming placeholder.
              if (event.tool_call_id) {
                const existingIdx = cm.toolCalls.findIndex((t) => t.id === event.tool_call_id)
                if (existingIdx >= 0) {
                  if (Object.keys(parsedArgs).length > 0) {
                    const updated = [...cm.toolCalls]
                    updated[existingIdx] = {
                      ...updated[existingIdx],
                      arguments: parsedArgs,
                      streamingArgs: undefined, // args complete, clear live preview
                    }
                    return { currentMessage: { ...cm, toolCalls: updated } }
                  }
                  return {} // already exists, no update needed
                }
              }
              const nextToolCall: ToolExecution = {
                id: tcId,
                name: toolName,
                arguments: parsedArgs,
                status: 'running',
                startTime: Date.now(),
              }
              return {
                currentMessage: {
                  ...cm,
                  toolCalls: [...cm.toolCalls, nextToolCall],
                },
              }
            })
            break;
          }

          case 'tool_call_delta':
            // Accumulate incremental JSON arg chunks so ToolCallCard can show a live preview.
            set((state) => {
              const cm = state.currentMessage
              if (!cm) return {}
              const tc = cm.toolCalls
              const chunk = event.content || ''
              if (!chunk) return {}
              const matchIdx = event.tool_call_id
                ? tc.findIndex((t) => t.id === event.tool_call_id)
                : tc.length - 1
              if (matchIdx < 0) return {}
              const updated = [...tc]
              const MAX_STREAMING = 80_000
              updated[matchIdx] = {
                ...updated[matchIdx],
                streamingArgs: (() => {
                  const next = (updated[matchIdx].streamingArgs || '') + chunk
                  return next.length <= MAX_STREAMING ? next : next.slice(-MAX_STREAMING)
                })(),
              }
              return { currentMessage: { ...cm, toolCalls: updated } }
            })
            break

          case 'tool_call_end':
            set((state) => {
              const cm = state.currentMessage
              if (!cm) return {}
              const tc = cm.toolCalls
              const matchIdx = event.tool_call_id
                ? tc.findIndex((t) => t.id === event.tool_call_id)
                : tc.length - 1
              if (matchIdx < 0) return {}
              const updated = [...tc]
              updated[matchIdx] = {
                ...updated[matchIdx],
                status: event.success === true ? 'completed' : (event.success === false ? 'failed' : 'completed'),
                endTime: Date.now(),
                output: event.tool_output || updated[matchIdx].output,
              }
              return { currentMessage: { ...cm, toolCalls: updated } }
            })
            break

          case 'tool_output':
            set((state) => {
              const cm = state.currentMessage
              if (!cm) return {}
              const tc = cm.toolCalls
              const matchIdx = event.tool_call_id
                ? tc.findIndex((t) => t.id === event.tool_call_id)
                : tc.length - 1
              if (matchIdx < 0) return {}
              const updated = [...tc]
              updated[matchIdx] = {
                ...updated[matchIdx],
                output: event.tool_output || updated[matchIdx].output,
                status: event.success === true ? 'completed' : 'failed',
                endTime: Date.now(),
              }
              return { currentMessage: { ...cm, toolCalls: updated } }
            })
            break

          case 'terminal_output': {
            // Streaming output from tools — append to the matching running tool call
            set((state) => {
              const cm = state.currentMessage
              if (!cm) return {}
              const tc = cm.toolCalls
              const chunk = event.data || event.content || ''
              if (!chunk) return {}
              // Match by tool_call_id, or fall back to the last running tool
              let matchIdx = event.tool_call_id
                ? tc.findIndex((t: ToolExecution) => t.id === event.tool_call_id)
                : -1
              if (matchIdx < 0) {
                for (let i = tc.length - 1; i >= 0; i--) {
                  if (tc[i].status === 'running') { matchIdx = i; break }
                }
              }
              if (matchIdx < 0) return {}
              const updated = [...tc]
              const MAX_TOOL_OUTPUT = 200_000
              updated[matchIdx] = {
                ...updated[matchIdx],
                output: (() => {
                  const next = (updated[matchIdx].output || '') + chunk
                  if (next.length <= MAX_TOOL_OUTPUT) return next
                  // Keep tail to remain responsive; preserve a short notice.
                  const tail = next.slice(-Math.floor(MAX_TOOL_OUTPUT * 0.9))
                  return `...[tool output truncated, was ${next.length} chars]...\n` + tail
                })(),
              }
              return { currentMessage: { ...cm, toolCalls: updated } }
            })
            break
          }

          case 'flag_found':
            set({ flagFound: event.flag_found || null })
            break

          case 'agent_waiting_flag_confirm':
            // Agent is paused waiting for user to confirm flag — no action needed
            // The GlobalFlagModal handles this via the flag_manual event
            break

          case 'ask_user': {
            // AI is asking the user a question with options
            try {
              const questionData: AskUserQuestion = typeof event.data === 'string'
                ? JSON.parse(event.data)
                : (event.data as unknown as AskUserQuestion)
              if (questionData && questionData.question) {
                set({ pendingQuestion: questionData })
              }
            } catch {
              // fallback: create question from content
              set({
                pendingQuestion: {
                  id: `q-${Date.now()}`,
                  question: event.content || 'AI has a question for you',
                  options: [],
                },
              })
            }
            break
          }

          case 'ask_user_responded':
            set({ pendingQuestion: null })
            break

          case 'writeup_generating':
            set({ isGeneratingWriteup: true })
            break

          case 'writeup_generated':
            set({ isGeneratingWriteup: false })
            break

          case 'agent_end': {
            if (isSubAgent) break // sub-agent end — don't override coordinator state
            set((state) => {
              const cm = state.currentMessage
              if (cm) {
                return {
                  messages: [...state.messages, { ...cm, isStreaming: false }],
                  currentMessage: null,
                  isRunning: false,
                  agentId: null,
                  rounds: state.rounds + 1,
                }
              }
              return { isRunning: false, agentId: null }
            })
            break
          }

          case 'error':
            if (isSubAgent) break
            set((state) => {
              const cm = state.currentMessage
              if (!cm) {
                return { isRunning: false, agentId: null }
              }
              const errText = event.error || event.content || 'Unknown error'
              return {
                messages: [
                  ...state.messages,
                  {
                    ...cm,
                    content: cm.content + `\n\n**Error:** ${errText}`,
                    isStreaming: false,
                  },
                ],
                currentMessage: null,
                isRunning: false,
                agentId: null,
              }
            })
            break

          case 'sub_agent_spawn':
            set((s) => {
              const payload = subAgentPayload
              const newAgents = new Map(s.subAgents)
              newAgents.set(event.agent_id, {
                type: payload?.agent_type || 'unknown',
                status: payload?.status || 'running',
              })
              return { subAgents: newAgents }
            })
            break

          case 'sub_agent_progress':
            // Update the sub-agent status so UI can show progress
            set((s) => {
              const payload = subAgentPayload
              const newAgents = new Map(s.subAgents)
              const agent = newAgents.get(event.agent_id)
              if (agent) {
                newAgents.set(event.agent_id, { ...agent, status: payload?.status || 'running' })
              }
              return { subAgents: newAgents }
            })
            break

          case 'sub_agent_complete':
            set((s) => {
              const payload = subAgentPayload
              const newAgents = new Map(s.subAgents)
              const agent = newAgents.get(event.agent_id)
              if (agent) {
                newAgents.set(event.agent_id, { ...agent, status: payload?.status || 'completed' })
              }
              return { subAgents: newAgents }
            })
            break

          case 'todolist_update':
            try {
              const items: TodoItem[] = typeof event.data === 'string' ? JSON.parse(event.data) : (event.data || [])
              set({ todoItems: items })
            } catch {
              // ignore parse errors
            }
            break

          case 'compaction':
            // Could show a notification
            break

          case 'user_message': {
            // User message echoed from backend — check if we already added it optimistically
            const content = event.content || ''
            const existingMsgs = get().messages
            // If the last message is a user message with the same content, skip (optimistic duplicate)
            const lastMsg = existingMsgs[existingMsgs.length - 1]
            if (lastMsg && lastMsg.role === 'user' && lastMsg.content === content && !lastMsg.isSystemInject) {
              break // already shown
            }
            // Otherwise it's a user message we haven't seen — show it
            if (content) {
              const isSystemMsg = isSystemInjectedContent(content)
              const userMsg: StreamingMessage = {
                id: `user-${Date.now()}`,
                role: 'user',
                content,
                toolCalls: [],
                isStreaming: false,
                timestamp: new Date().toISOString(),
                ...(isSystemMsg ? { isSystemInject: true, systemInjectType: 'system' } : {}),
              }
              set({ messages: [...get().messages, userMsg] })
            }
            break
          }

          case 'reflection':
          case 'planning_phase':
          case 'checkpoint':
          case 'repetition_warning':
          case 'flag_candidate':
          case 'thinking_overflow_hint': {
            // System-injected "user" messages — display them in the chat
            const injectContent = event.content || ''
            if (injectContent) {
              const typeMap: Record<string, StreamingMessage['systemInjectType']> = {
                'reflection': 'reflection',
                'planning_phase': 'planning',
                'checkpoint': 'checkpoint',
                'repetition_warning': 'repetition',
                'flag_candidate': 'flag_candidate',
                'thinking_overflow_hint': 'thinking_hint',
              }
              const sysMsg: StreamingMessage = {
                id: `sys-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                role: 'user',
                content: injectContent,
                toolCalls: [],
                isStreaming: false,
                timestamp: new Date().toISOString(),
                isSystemInject: true,
                systemInjectType: typeMap[event.type] || 'system',
              }
              set({ messages: [...get().messages, sysMsg] })
            }
            break
          }
        }
      },
    }),
    {
      name: 'ctf-agent-session',
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
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
        session: s.session,
        messages: s.messages,
        flagFound: s.flagFound,
        rounds: s.rounds,
        model: s.model,
        isRunning: s.isRunning,
        agentId: s.agentId,
      } as unknown as AgentState),
    }
  )
)

function safeParseArgs(args: string | Record<string, unknown>): Record<string, unknown> {
  if (typeof args === 'object') return args
  try {
    return JSON.parse(args)
  } catch {
    return { raw: args }
  }
}
