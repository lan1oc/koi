import { useState } from 'react'
import { ChevronUp, ChevronDown, ListTodo, CircleDot, CheckCircle2, XCircle, SkipForward, Circle } from 'lucide-react'
import { useAgentStore } from '../stores/agentStore'
import type { TodoItem } from '../types'

const statusConfig: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  pending: {
    icon: <Circle className="w-3.5 h-3.5" />,
    color: 'text-gray-400',
    label: '待办',
  },
  in_progress: {
    icon: <CircleDot className="w-3.5 h-3.5 animate-pulse" />,
    color: 'text-amber-500',
    label: '进行中',
  },
  done: {
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
    color: 'text-emerald-500',
    label: '完成',
  },
  failed: {
    icon: <XCircle className="w-3.5 h-3.5" />,
    color: 'text-red-500',
    label: '失败',
  },
  skipped: {
    icon: <SkipForward className="w-3.5 h-3.5" />,
    color: 'text-gray-400',
    label: '跳过',
  },
}

export default function TodoListPanel() {
  const todoItems = useAgentStore((s) => s.todoItems)
  const [expanded, setExpanded] = useState(false)

  if (todoItems.length === 0) return null

  const pending = todoItems.filter((t) => t.status === 'pending').length
  const inProgress = todoItems.filter((t) => t.status === 'in_progress').length
  const done = todoItems.filter((t) => t.status === 'done').length
  const failed = todoItems.filter((t) => t.status === 'failed').length

  return (
    <div className="border-t border-surface-border bg-white [html.theme-dark_&]:bg-[#1a1d27]">
      {/* Toggle Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-1.5 text-xs hover:bg-surface-hover transition-colors"
      >
        <ListTodo className="w-3.5 h-3.5 text-primary-500" />
        <span className="font-medium text-gray-700">TodoList</span>
        <span className="text-gray-400">
          {done}/{todoItems.length} 完成
        </span>
        {inProgress > 0 && (
          <span className="text-amber-500 flex items-center gap-0.5">
            <CircleDot className="w-3 h-3 animate-pulse" />
            {inProgress}
          </span>
        )}
        {failed > 0 && (
          <span className="text-red-500 flex items-center gap-0.5">
            <XCircle className="w-3 h-3" />
            {failed}
          </span>
        )}
        {pending > 0 && (
          <span className="text-gray-400">{pending} 待办</span>
        )}
        <span className="flex-1" />
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
        ) : (
          <ChevronUp className="w-3.5 h-3.5 text-gray-400" />
        )}
      </button>

      {/* Expanded Items */}
      {expanded && (
        <div className="px-4 pb-2 space-y-1">
          {todoItems.map((item) => (
            <TodoItemRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}

function TodoItemRow({ item }: { item: TodoItem }) {
  const cfg = statusConfig[item.status] || statusConfig.pending

  return (
    <div className={`flex items-start gap-2 text-xs px-2 py-1 rounded ${
      item.status === 'in_progress' ? 'bg-amber-50' :
      item.status === 'done' ? 'bg-emerald-50/50' :
      item.status === 'failed' ? 'bg-red-50/50' : 'bg-surface-50'
    }`}>
      <span className={`flex-shrink-0 mt-0.5 ${cfg.color}`}>{cfg.icon}</span>
      <div className="min-w-0 flex-1">
        <span className={`${item.status === 'failed' ? 'line-through text-gray-400' : 'text-gray-700'}`}>
          {item.task}
        </span>
        {item.result && (
          <div className={`mt-0.5 text-[10px] ${
            item.status === 'failed' ? 'text-red-400' :
            item.status === 'done' ? 'text-emerald-500' : 'text-gray-400'
          }`}>
            → {item.result}
          </div>
        )}
      </div>
    </div>
  )
}
