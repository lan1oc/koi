import { useState, useEffect, useRef } from 'react'
import { Play, Loader2, Code, Copy, Check } from 'lucide-react'
import type { DecompileTask } from '../../types'

interface DecompileViewProps {
  tasks: DecompileTask[]
  onDecompile: (func?: string) => Promise<DecompileTask>
  onPoll: (taskId: string) => Promise<DecompileTask>
  binaryId: string
}

export default function DecompileView({ tasks, onDecompile, onPoll, binaryId }: DecompileViewProps) {
  const [funcName, setFuncName] = useState('')
  const [running, setRunning] = useState(false)
  const [activeTask, setActiveTask] = useState<DecompileTask | null>(null)
  const [copied, setCopied] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Poll active task
  useEffect(() => {
    if (!activeTask || activeTask.status === 'completed' || activeTask.status === 'failed') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await onPoll(activeTask.task_id)
        setActiveTask(updated)
        if (updated.status === 'completed' || updated.status === 'failed') {
          setRunning(false)
        }
      } catch { /* ignore poll errors */ }
    }, 2000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [activeTask?.task_id, activeTask?.status, onPoll])

  const handleDecompile = async () => {
    setRunning(true)
    try {
      const task = await onDecompile(funcName || undefined)
      setActiveTask(task)
    } catch {
      setRunning(false)
    }
  }

  const handleCopy = () => {
    if (activeTask?.result) {
      navigator.clipboard.writeText(activeTask.result)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const latestCompleted = tasks.filter((t) => t.status === 'completed')
  const displayTask = activeTask || (latestCompleted.length > 0 ? latestCompleted[latestCompleted.length - 1] : undefined)

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex items-center gap-2 mb-3">
        <input
          type="text"
          value={funcName}
          onChange={(e) => setFuncName(e.target.value)}
          placeholder="函数名 (留空=全部反编译)"
          className="flex-1 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
            text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
        />
        <button
          onClick={handleDecompile}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-purple-50 border border-purple-200
            text-purple-600 rounded-lg hover:bg-purple-100 disabled:opacity-50 transition-colors"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          反编译
        </button>
      </div>

      {/* Status */}
      {displayTask && (
        <div className="flex items-center gap-2 mb-2 text-xs">
          <span className={`px-2 py-0.5 rounded-full ${
            displayTask.status === 'completed' ? 'bg-green-50 text-green-600 border border-green-200' :
            displayTask.status === 'failed' ? 'bg-red-50 text-red-600 border border-red-200' :
            displayTask.status === 'running' ? 'bg-yellow-50 text-yellow-600 border border-yellow-200' :
            'bg-gray-100 text-gray-500'
          }`}>
            {displayTask.status === 'completed' ? '完成' :
             displayTask.status === 'failed' ? '失败' :
             displayTask.status === 'running' ? '运行中...' : '等待中'}
          </span>
          {displayTask.function_name && (
            <span className="text-gray-500">函数: {displayTask.function_name}</span>
          )}
          {displayTask.result && (
            <button onClick={handleCopy} className="ml-auto text-gray-400 hover:text-gray-600 transition-colors">
              {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      )}

      {/* Result */}
      <div className="flex-1 overflow-auto rounded-xl border border-gray-200 bg-white">
        {running && !displayTask?.result ? (
          <div className="flex flex-col items-center justify-center h-32 gap-2">
            <Loader2 className="w-6 h-6 text-purple-500 animate-spin" />
            <span className="text-sm text-gray-500">Ghidra 反编译中... 这可能需要几分钟</span>
          </div>
        ) : displayTask?.error ? (
          <div className="p-4 text-sm text-red-600">
            <p className="font-medium mb-1">反编译失败</p>
            <pre className="text-xs text-red-500 whitespace-pre-wrap">{displayTask.error}</pre>
          </div>
        ) : displayTask?.result ? (
          <pre className="p-4 text-xs font-mono text-gray-700 whitespace-pre-wrap overflow-auto">
            {displayTask.result}
          </pre>
        ) : (
          <div className="flex items-center justify-center h-32 text-sm text-gray-500">
            <Code className="w-4 h-4 mr-2" />
            点击「反编译」启动 Ghidra 分析
          </div>
        )}
      </div>

      {/* Task history */}
      {tasks.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tasks.map((t) => (
            <button
              key={t.task_id}
              onClick={() => setActiveTask(t)}
              className={`px-2 py-0.5 text-xs rounded-lg border transition-colors ${
                activeTask?.task_id === t.task_id
                  ? 'border-purple-300 text-purple-600 bg-purple-50'
                  : 'border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              {t.function_name || 'Full'} ({t.status})
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
