import { create } from 'zustand'
import { wsService } from '../services/websocket'
import type {
  AgentTopologyGraph,
  AgentTopologyNode,
  SubAgentTopologyEvent,
  TopologyNodeStatus,
  WSEvent,
} from '../types'

interface TopologyState {
  graphs: Record<string, AgentTopologyGraph>
  connect: () => void
  disconnect: () => void
  resetSession: (rootSessionId: string) => void
}

let wsUnsub: (() => void) | null = null
let connectRefCount = 0

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

function ensureGraph(
  graphs: Record<string, AgentTopologyGraph>,
  rootSessionId: string,
  challengeId?: string,
  challengeTitle?: string
): AgentTopologyGraph {
  const existing = graphs[rootSessionId]
  if (existing) {
    return {
      ...existing,
      challengeId: existing.challengeId || challengeId,
      challengeTitle: existing.challengeTitle || challengeTitle,
      updatedAt: Date.now(),
      nodes: { ...existing.nodes },
    }
  }
  return {
    rootSessionId,
    challengeId,
    challengeTitle,
    updatedAt: Date.now(),
    nodes: {},
  }
}

function ensureNode(
  graph: AgentTopologyGraph,
  nodeId: string,
  partial: Partial<AgentTopologyNode>
): AgentTopologyNode {
  const existing = graph.nodes[nodeId]
  const next: AgentTopologyNode = {
    id: nodeId,
    sessionId: partial.sessionId || existing?.sessionId || graph.rootSessionId,
    rootSessionId: partial.rootSessionId || existing?.rootSessionId || graph.rootSessionId,
    agentType: partial.agentType || existing?.agentType || 'coordinator',
    status: partial.status || existing?.status || 'running',
    rounds: partial.rounds ?? existing?.rounds ?? 0,
    startedAt: partial.startedAt || existing?.startedAt || Date.now(),
    updatedAt: Date.now(),
    challengeId: partial.challengeId || existing?.challengeId || graph.challengeId,
    challengeTitle: partial.challengeTitle || existing?.challengeTitle || graph.challengeTitle,
    model: partial.model || existing?.model,
    currentTool: partial.currentTool ?? existing?.currentTool,
    summary: partial.summary ?? existing?.summary,
    task: partial.task ?? existing?.task,
    flagFound: partial.flagFound ?? existing?.flagFound,
    parentId: partial.parentId ?? existing?.parentId,
    isRoot: partial.isRoot ?? existing?.isRoot,
  }
  graph.nodes[nodeId] = next
  return next
}

function statusFromTerminalEvent(event: WSEvent): TopologyNodeStatus {
  if (event.type === 'error') return 'failed'
  return 'completed'
}

function handleTopologyEvent(event: WSEvent) {
  const agentId = event.agent_id
  if (!agentId) return

  useTopologyStore.setState((state) => {
    const graphs = { ...state.graphs }

    const findGraphByNode = () => {
      for (const graph of Object.values(graphs)) {
        if (graph.nodes[agentId]) return graph
      }
      return null
    }

    switch (event.type) {
      case 'agent_start': {
        const knownGraph = findGraphByNode()
        const rootSessionId = knownGraph?.nodes[agentId]?.rootSessionId || event.session_id
        if (!rootSessionId) return {}
        const graph = ensureGraph(graphs, rootSessionId, event.challenge_id, event.challenge_title)
        const node = ensureNode(graph, agentId, {
          sessionId: event.session_id || rootSessionId,
          rootSessionId,
          challengeId: event.challenge_id || knownGraph?.nodes[agentId]?.challengeId,
          challengeTitle: event.challenge_title || knownGraph?.nodes[agentId]?.challengeTitle,
          model: event.model,
          status: 'running',
          isRoot: knownGraph ? knownGraph.nodes[agentId]?.isRoot : true,
          agentType: knownGraph?.nodes[agentId]?.agentType || 'coordinator',
        })
        if (!node.parentId && !graph.rootAgentId) {
          graph.rootAgentId = agentId
          node.isRoot = true
        }
        graphs[rootSessionId] = graph
        return { graphs }
      }

      case 'round_start':
      case 'tool_call_start':
      case 'tool_call_end':
      case 'flag_found':
      case 'agent_end':
      case 'error': {
        const graph = findGraphByNode()
        if (!graph) return {}
        const node = graph.nodes[agentId]
        if (!node) return {}
        if (event.type === 'round_start') {
          node.rounds += 1
        } else if (event.type === 'tool_call_start') {
          node.currentTool = event.tool_name
          node.status = 'running'
        } else if (event.type === 'tool_call_end') {
          node.currentTool = undefined
        } else if (event.type === 'flag_found') {
          node.flagFound = event.flag_found
        } else if (event.type === 'agent_end' || event.type === 'error') {
          node.currentTool = undefined
          node.status = statusFromTerminalEvent(event)
          node.summary = event.error || node.summary
          if (event.flag_found) {
            node.flagFound = event.flag_found
          }
        }
        node.updatedAt = Date.now()
        graph.updatedAt = Date.now()
        graphs[graph.rootSessionId] = { ...graph, nodes: { ...graph.nodes } }
        return { graphs }
      }

      case 'sub_agent_spawn':
      case 'sub_agent_progress':
      case 'sub_agent_complete': {
        const payload = parseSubAgentEvent(event.data)
        if (!payload) return {}
        const rootSessionId = payload.root_session_id || payload.parent_session_id || payload.child_session_id
        const graph = ensureGraph(
          graphs,
          rootSessionId,
          payload.challenge_id || event.challenge_id,
          payload.challenge_title || event.challenge_title
        )

        if (payload.parent_agent_id) {
          const parent = ensureNode(graph, payload.parent_agent_id, {
            sessionId: payload.parent_session_id || rootSessionId,
            rootSessionId,
            challengeId: payload.challenge_id,
            challengeTitle: payload.challenge_title,
            status: 'running',
            isRoot: payload.parent_session_id === rootSessionId || !graph.rootAgentId,
            agentType: graph.rootAgentId ? 'coordinator' : 'coordinator',
          })
          if (!graph.rootAgentId && parent.isRoot) {
            graph.rootAgentId = parent.id
          }
        }

        const child = ensureNode(graph, payload.child_agent_id, {
          parentId: payload.parent_agent_id || undefined,
          sessionId: payload.child_session_id,
          rootSessionId,
          challengeId: payload.challenge_id,
          challengeTitle: payload.challenge_title,
          agentType: payload.agent_type,
          model: payload.model,
          status: payload.status,
          rounds: payload.rounds ?? graph.nodes[payload.child_agent_id]?.rounds ?? 0,
          currentTool: payload.current_tool,
          summary: payload.summary,
          task: payload.task,
          flagFound: payload.flag_found,
          isRoot: false,
        })
        child.updatedAt = Date.now()
        graph.updatedAt = Date.now()
        graphs[rootSessionId] = graph
        return { graphs }
      }
    }

    return {}
  })
}

export const useTopologyStore = create<TopologyState>((set) => ({
  graphs: {},

  connect: () => {
    connectRefCount += 1
    if (wsUnsub) return
    if (!wsService.connected) {
      wsService.connect()
    }
    wsUnsub = wsService.onAll(handleTopologyEvent)
  },

  disconnect: () => {
    connectRefCount = Math.max(0, connectRefCount - 1)
    if (connectRefCount > 0) return
    if (wsUnsub) {
      wsUnsub()
      wsUnsub = null
    }
  },

  resetSession: (rootSessionId) =>
    set((state) => {
      const graphs = { ...state.graphs }
      delete graphs[rootSessionId]
      return { graphs }
    }),
}))
