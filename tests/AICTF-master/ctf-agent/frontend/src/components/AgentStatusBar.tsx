import { Activity, Cpu, Zap, Users } from 'lucide-react'
import { useAgentStore } from '../stores/agentStore'

export default function AgentStatusBar() {
  const { isRunning, isGeneratingWriteup, model, rounds, subAgents, flagFound } = useAgentStore()

  const activeSubAgents = Array.from(subAgents.values()).filter(
    (a) => a.status === 'running' || a.status === 'spawned'
  ).length
  const isActive = isRunning || isGeneratingWriteup

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-white [html.theme-dark_&]:bg-[#1a1d27] border-t border-surface-border text-xs">
      {/* Status */}
      <div className="flex items-center gap-1.5">
        <div
          className={`w-2 h-2 rounded-full ${
            isRunning ? 'bg-amber-500 animate-pulse-soft' : isGeneratingWriteup ? 'bg-blue-500 animate-pulse-soft' : flagFound ? 'bg-green-500' : 'bg-gray-300'
          }`}
        />
        <span className={isRunning ? 'text-amber-600' : isGeneratingWriteup ? 'text-blue-600' : flagFound ? 'text-green-600' : 'text-gray-400'}>
          {isRunning ? '运行中' : isGeneratingWriteup ? 'Writeup 生成中' : flagFound ? '已解决！' : '空闲'}
        </span>
      </div>

      <div className="w-px h-4 bg-surface-border" />

      {/* Model */}
      <div className="flex items-center gap-1 text-gray-500">
        <Cpu className="w-3 h-3" />
        <span>{model}</span>
      </div>

      <div className="w-px h-4 bg-surface-border" />

      {/* Rounds */}
      <div className="flex items-center gap-1 text-gray-500">
        <Zap className="w-3 h-3" />
        <span>第 {rounds} 轮</span>
      </div>

      {/* Sub-agents */}
      {subAgents.size > 0 && (
        <>
          <div className="w-px h-4 bg-surface-border" />
          <div className="flex items-center gap-1 text-gray-500">
            <Users className="w-3 h-3" />
            <span>
              {activeSubAgents}/{subAgents.size} 个智能体
            </span>
          </div>
        </>
      )}

      <div className="flex-1" />

      {/* Flag */}
      {flagFound && !isActive && (
        <span className="text-green-600 font-mono">
          🚩 {flagFound}
        </span>
      )}
    </div>
  )
}
