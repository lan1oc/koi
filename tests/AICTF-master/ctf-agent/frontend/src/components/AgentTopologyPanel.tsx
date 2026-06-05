import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Flag, GitBranch, Wrench } from 'lucide-react'
import { useTopologyStore } from '../stores/topologyStore'
import type { AgentTopologyGraph, AgentTopologyNode, TopologyNodeStatus } from '../types'

interface AgentTopologyPanelProps {
  sessionId?: string
  challengeId?: string
  onOpenSession?: (sessionId: string) => void
}

interface GraphNodeLayout {
  node: AgentTopologyNode
  depth: number
  x: number
  y: number
}

const statusStyles: Record<TopologyNodeStatus, string> = {
  spawned: 'bg-slate-100 text-slate-600 border-slate-200',
  running: 'bg-amber-50 text-amber-700 border-amber-200',
  completed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  timed_out: 'bg-orange-50 text-orange-700 border-orange-200',
  stopped: 'bg-gray-100 text-gray-600 border-gray-200',
}

const statusLabels: Record<TopologyNodeStatus, string> = {
  spawned: '已拉起',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  timed_out: '超时',
  stopped: '已停止',
}

const NODE_WIDTH = 220
const NODE_HEIGHT = 122
const COLUMN_GAP = 120
const ROW_GAP = 34
const CANVAS_PADDING = 28

function pickGraph(
  graphs: Record<string, AgentTopologyGraph>,
  sessionId?: string,
  challengeId?: string
): AgentTopologyGraph | null {
  if (sessionId && graphs[sessionId]) {
    return graphs[sessionId]
  }
  if (sessionId) {
    const matched = Object.values(graphs).find((graph) =>
      Object.values(graph.nodes).some((node) => node.sessionId === sessionId)
    )
    if (matched) {
      return matched
    }
  }
  const values = Object.values(graphs)
    .filter((graph) => !challengeId || graph.challengeId === challengeId)
    .sort((a, b) => b.updatedAt - a.updatedAt)
  return values[0] || null
}

function shortId(value?: string): string {
  return value ? value.slice(0, 8) : 'unknown'
}

function formatAgentLabel(node: AgentTopologyNode): string {
  if (node.isRoot) return '主控 Agent'
  return node.agentType.replace(/_/g, ' ')
}

function formatRelativeAge(updatedAt: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - updatedAt) / 1000))
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

function isStale(node: AgentTopologyNode, now: number): boolean {
  if (node.status !== 'running' && node.status !== 'spawned') return false
  return now-node.updatedAt > 45_000
}

function buildChildrenMap(nodes: Record<string, AgentTopologyNode>) {
  const map: Record<string, AgentTopologyNode[]> = {}
  for (const node of Object.values(nodes)) {
    if (!node.parentId) continue
    if (!map[node.parentId]) {
      map[node.parentId] = []
    }
    map[node.parentId].push(node)
  }
  for (const entries of Object.values(map)) {
    entries.sort((a, b) => a.startedAt - b.startedAt)
  }
  return map
}

function buildLayouts(nodes: Record<string, AgentTopologyNode>) {
  const childrenMap = buildChildrenMap(nodes)
  const roots = Object.values(nodes)
    .filter((node) => !node.parentId)
    .sort((a, b) => a.startedAt - b.startedAt)

  const depthMap = new Map<string, number>()
  const order: AgentTopologyNode[] = []
  const queue = roots.map((node) => ({ node, depth: 0 }))

  while (queue.length > 0) {
    const current = queue.shift()
    if (!current || depthMap.has(current.node.id)) continue
    depthMap.set(current.node.id, current.depth)
    order.push(current.node)
    for (const child of childrenMap[current.node.id] || []) {
      queue.push({ node: child, depth: current.depth + 1 })
    }
  }

  for (const node of Object.values(nodes)) {
    if (!depthMap.has(node.id)) {
      depthMap.set(node.id, 0)
      order.push(node)
    }
  }

  const layers = new Map<number, AgentTopologyNode[]>()
  for (const node of order) {
    const depth = depthMap.get(node.id) || 0
    if (!layers.has(depth)) {
      layers.set(depth, [])
    }
    layers.get(depth)!.push(node)
  }

  const layouts = new Map<string, GraphNodeLayout>()
  const maxDepth = Math.max(0, ...Array.from(layers.keys()))
  let maxRows = 1

  for (let depth = 0; depth <= maxDepth; depth += 1) {
    const layer = (layers.get(depth) || []).sort((a, b) => a.startedAt - b.startedAt)
    maxRows = Math.max(maxRows, layer.length)
    layer.forEach((node, index) => {
      layouts.set(node.id, {
        node,
        depth,
        x: CANVAS_PADDING + depth * (NODE_WIDTH + COLUMN_GAP),
        y: CANVAS_PADDING + index * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }

  const width = CANVAS_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP
  const height = CANVAS_PADDING * 2 + maxRows * NODE_HEIGHT + Math.max(0, maxRows - 1) * ROW_GAP

  return { roots, childrenMap, layouts, width, height, maxDepth }
}

function GraphNode({
  layout,
  selected,
  stale,
  now,
  onSelect,
}: {
  layout: GraphNodeLayout
  selected: boolean
  stale: boolean
  now: number
  onSelect: (nodeId: string) => void
}) {
  const { node, x, y } = layout

  return (
    <button
      type="button"
      onClick={() => onSelect(node.id)}
      className={`absolute rounded-3xl border bg-white/95 p-0 text-left shadow-sm transition-all ${
        selected
          ? 'border-blue-300 ring-2 ring-blue-100 shadow-lg'
          : 'border-slate-200 hover:border-slate-300 hover:shadow-md'
      }`}
      style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <div className="flex h-full flex-col overflow-hidden rounded-3xl">
        <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
                <GitBranch className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-900">{formatAgentLabel(node)}</div>
                <div className="mt-0.5 text-[11px] text-slate-500">#{shortId(node.id)}</div>
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusStyles[node.status]}`}>
              {statusLabels[node.status]}
            </span>
            {stale && (
              <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-medium text-red-700">
                卡住
              </span>
            )}
          </div>
        </div>

        <div className="grid flex-1 grid-cols-2 gap-2 px-4 py-3 text-xs">
          <div className="rounded-2xl bg-slate-50 px-2.5 py-2">
            <div className="text-[10px] text-slate-500">轮次</div>
            <div className="mt-1 font-semibold text-slate-800">{node.rounds}</div>
          </div>
          <div className="rounded-2xl bg-slate-50 px-2.5 py-2">
            <div className="text-[10px] text-slate-500">更新</div>
            <div className="mt-1 font-semibold text-slate-800">{formatRelativeAge(node.updatedAt, now)}</div>
          </div>
          <div className="col-span-2 rounded-2xl bg-slate-50 px-2.5 py-2">
            <div className="flex items-center gap-1 text-[10px] text-slate-500">
              <Wrench className="h-3 w-3" />
              当前工具
            </div>
            <div className="mt-1 truncate font-semibold text-slate-800">{node.currentTool || 'idle'}</div>
          </div>
        </div>
      </div>
    </button>
  )
}

export default function AgentTopologyPanel({ sessionId, challengeId, onOpenSession }: AgentTopologyPanelProps) {
  const graphs = useTopologyStore((state) => state.graphs)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const graph = useMemo(() => pickGraph(graphs, sessionId, challengeId), [graphs, sessionId, challengeId])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5000)
    return () => window.clearInterval(timer)
  }, [])

  const {
    layouts,
    selectedNode,
    staleNodes,
    nodeCount,
    runningCount,
    doneCount,
    width,
    height,
    maxDepth,
  } = useMemo(() => {
    if (!graph) {
      return {
        layouts: new Map<string, GraphNodeLayout>(),
        selectedNode: null as AgentTopologyNode | null,
        staleNodes: [] as AgentTopologyNode[],
        nodeCount: 0,
        runningCount: 0,
        doneCount: 0,
        width: 0,
        height: 0,
        maxDepth: 0,
      }
    }

    const nodes = Object.values(graph.nodes)
    const next = buildLayouts(graph.nodes)
    const fallbackSelected =
      nodes.find((node) => node.sessionId === sessionId)?.id ||
      graph.rootAgentId ||
      nodes.sort((a, b) => a.startedAt - b.startedAt)[0]?.id ||
      null
    const effectiveSelectedId = selectedNodeId && graph.nodes[selectedNodeId] ? selectedNodeId : fallbackSelected

    return {
      layouts: next.layouts,
      selectedNode: effectiveSelectedId ? graph.nodes[effectiveSelectedId] || null : null,
      staleNodes: nodes.filter((node) => isStale(node, now)),
      nodeCount: nodes.length,
      runningCount: nodes.filter((node) => node.status === 'running' || node.status === 'spawned').length,
      doneCount: nodes.filter((node) => node.status === 'completed').length,
      width: next.width,
      height: next.height,
      maxDepth: next.maxDepth,
    }
  }, [graph, now, selectedNodeId, sessionId])

  useEffect(() => {
    if (!graph) {
      setSelectedNodeId(null)
      return
    }
    if (selectedNodeId && graph.nodes[selectedNodeId]) {
      return
    }
    const nextSelectedId =
      Object.values(graph.nodes).find((node) => node.sessionId === sessionId)?.id ||
      graph.rootAgentId ||
      Object.keys(graph.nodes)[0] ||
      null
    setSelectedNodeId(nextSelectedId)
  }, [graph, selectedNodeId, sessionId])

  if (!graph || layouts.size === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm rounded-3xl border border-dashed border-slate-300 bg-white/80 px-6 py-8 text-center">
          <div className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
            <GitBranch className="h-5 w-5" />
          </div>
          <div className="text-sm font-semibold text-slate-800">拓扑图尚未生成</div>
          <div className="mt-2 text-xs leading-5 text-slate-500">
            启动当前任务后，这里会显示主控 Agent 与各个子 Agent 的节点图和执行关系。
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto bg-[radial-gradient(circle_at_top,_rgba(148,163,184,0.12),_transparent_48%)] p-5">
      <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/90 px-4 py-3 shadow-sm">
        <div>
          <div className="text-sm font-semibold text-slate-900">Agent 节点拓扑</div>
          <div className="mt-1 text-xs text-slate-500">
            {graph.challengeTitle || graph.challengeId || '当前任务'} · root session {shortId(graph.rootSessionId)}
          </div>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>层级 {maxDepth + 1}</div>
          <div>最近更新 {new Date(graph.updatedAt).toLocaleTimeString()}</div>
        </div>
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="text-[11px] text-slate-500">节点总数</div>
          <div className="mt-1 text-xl font-semibold text-slate-900">{nodeCount}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="text-[11px] text-slate-500">运行中</div>
          <div className="mt-1 text-xl font-semibold text-amber-700">{runningCount}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="text-[11px] text-slate-500">已完成</div>
          <div className="mt-1 text-xl font-semibold text-emerald-700">{doneCount}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="text-[11px] text-slate-500">卡住告警</div>
          <div className="mt-1 text-xl font-semibold text-red-700">{staleNodes.length}</div>
        </div>
      </div>

      {staleNodes.length > 0 && (
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 shadow-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <div className="font-medium">检测到可能卡住的节点</div>
            <div className="mt-1 text-xs leading-5 text-red-700">
              {staleNodes.map((node) => `${formatAgentLabel(node)}(${shortId(node.id)})`).join('、')}
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="overflow-auto rounded-[28px] border border-slate-200 bg-white/80 p-4 shadow-sm">
          <div
            className="relative rounded-[24px] bg-[linear-gradient(90deg,rgba(148,163,184,0.06)_1px,transparent_1px),linear-gradient(rgba(148,163,184,0.06)_1px,transparent_1px)]"
            style={{
              width: Math.max(width, 720),
              height: Math.max(height, 280),
              backgroundSize: '28px 28px',
            }}
          >
            <svg
              width={Math.max(width, 720)}
              height={Math.max(height, 280)}
              className="absolute inset-0"
            >
              {Array.from(layouts.values()).map((layout) => {
                if (!layout.node.parentId) return null
                const parent = layouts.get(layout.node.parentId)
                if (!parent) return null

                const startX = parent.x + NODE_WIDTH
                const startY = parent.y + NODE_HEIGHT / 2
                const endX = layout.x
                const endY = layout.y + NODE_HEIGHT / 2
                const controlOffset = Math.max(44, (endX - startX) / 2)

                return (
                  <path
                    key={`${parent.node.id}-${layout.node.id}`}
                    d={`M ${startX} ${startY} C ${startX + controlOffset} ${startY}, ${endX - controlOffset} ${endY}, ${endX} ${endY}`}
                    fill="none"
                    stroke={selectedNode?.id === layout.node.id || selectedNode?.id === parent.node.id ? '#2563eb' : '#cbd5e1'}
                    strokeWidth={selectedNode?.id === layout.node.id || selectedNode?.id === parent.node.id ? 2.5 : 2}
                    strokeDasharray={layout.node.status === 'spawned' ? '6 6' : undefined}
                    opacity={0.95}
                  />
                )
              })}
            </svg>

            {Array.from(layouts.values()).map((layout) => (
              <GraphNode
                key={layout.node.id}
                layout={layout}
                selected={selectedNodeId === layout.node.id}
                stale={isStale(layout.node, now)}
                now={now}
                onSelect={setSelectedNodeId}
              />
            ))}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-0">
          {!selectedNode ? (
            <div className="text-sm text-slate-500">选择一个节点查看详情。</div>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="text-xs text-slate-500">当前节点</div>
                <div className="mt-1 text-lg font-semibold text-slate-900">{formatAgentLabel(selectedNode)}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${statusStyles[selectedNode.status]}`}>
                    {statusLabels[selectedNode.status]}
                  </span>
                  {isStale(selectedNode, now) && (
                    <span className="rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-[11px] font-medium text-red-700">
                      疑似卡住
                    </span>
                  )}
                </div>
              </div>

              <div className="grid gap-3">
                <div className="rounded-2xl bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">Agent ID</div>
                  <div className="mt-1 break-all text-xs font-medium text-slate-700">{selectedNode.id}</div>
                </div>
                <div className="rounded-2xl bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">Session ID</div>
                  <div className="mt-1 break-all text-xs font-medium text-slate-700">{selectedNode.sessionId}</div>
                </div>
                <div className="rounded-2xl bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">Parent Agent</div>
                  <div className="mt-1 break-all text-xs font-medium text-slate-700">{selectedNode.parentId || 'root'}</div>
                </div>
              </div>

              <div className="space-y-2 rounded-2xl border border-slate-200 px-3 py-3">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>执行概况</span>
                  <span>更新于 {formatRelativeAge(selectedNode.updatedAt, now)} 前</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-xl bg-slate-50 px-3 py-2">
                    <div className="text-slate-500">模型</div>
                    <div className="mt-1 break-all font-medium text-slate-800">{selectedNode.model || 'inherit'}</div>
                  </div>
                  <div className="rounded-xl bg-slate-50 px-3 py-2">
                    <div className="text-slate-500">轮次</div>
                    <div className="mt-1 font-medium text-slate-800">{selectedNode.rounds}</div>
                  </div>
                  <div className="rounded-xl bg-slate-50 px-3 py-2 col-span-2">
                    <div className="text-slate-500">当前工具</div>
                    <div className="mt-1 break-all font-medium text-slate-800">{selectedNode.currentTool || 'idle'}</div>
                  </div>
                </div>
              </div>

              {selectedNode.task && (
                <div>
                  <div className="text-xs text-slate-500">任务</div>
                  <div className="mt-1 rounded-2xl bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">
                    {selectedNode.task}
                  </div>
                </div>
              )}

              {selectedNode.summary && (
                <div>
                  <div className="text-xs text-slate-500">摘要</div>
                  <div className="mt-1 rounded-2xl bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">
                    {selectedNode.summary}
                  </div>
                </div>
              )}

              {selectedNode.flagFound && (
                <div className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
                  <Flag className="h-3.5 w-3.5" />
                  {selectedNode.flagFound}
                </div>
              )}

              {onOpenSession && (
                <button
                  type="button"
                  onClick={() => onOpenSession(selectedNode.sessionId)}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-blue-700"
                >
                  打开该会话
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
