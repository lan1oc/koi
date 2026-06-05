import { useState } from 'react'
import { MessageCircleQuestion, Send, CheckCircle } from 'lucide-react'
import type { AskUserQuestion } from '../types'

interface AskUserModalProps {
  question: AskUserQuestion
  onRespond: (answer: string) => void
}

export default function AskUserModal({ question, onRespond }: AskUserModalProps) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null)
  const [customInput, setCustomInput] = useState('')
  const [isCustomMode, setIsCustomMode] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (answer: string) => {
    if (!answer.trim() || submitted) return
    setSubmitted(true)
    onRespond(answer.trim())
  }

  const handleOptionClick = (option: string) => {
    setSelectedOption(option)
    setIsCustomMode(false)
    handleSubmit(option)
  }

  const handleCustomSubmit = () => {
    if (customInput.trim()) {
      handleSubmit(customInput.trim())
    }
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-2xl animate-in fade-in slide-in-from-bottom-2 duration-300">
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-4 backdrop-blur-sm">
          <div className="flex items-center gap-2 text-green-400">
            <CheckCircle className="h-5 w-5" />
            <span className="text-sm font-medium">已回答</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="relative overflow-hidden rounded-xl border border-amber-500/30 bg-gradient-to-b from-amber-500/10 to-amber-500/5 shadow-lg shadow-amber-500/5 backdrop-blur-sm">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-amber-500/20 px-5 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/20">
            <MessageCircleQuestion className="h-4 w-4 text-amber-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-amber-300">AI 需要你的帮助</h3>
            {question.context && (
              <p className="mt-0.5 text-xs text-zinc-400">{question.context}</p>
            )}
          </div>
          <div className="ml-auto">
            <span className="inline-flex items-center rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-400 ring-1 ring-amber-500/30">
              等待回答
            </span>
          </div>
        </div>

        {/* Question */}
        <div className="px-5 py-4">
          <p className="text-sm leading-relaxed text-zinc-200">{question.question}</p>
        </div>

        {/* Options */}
        {question.options.length > 0 && (
          <div className="space-y-2 px-5 pb-3">
            {question.options.map((option, idx) => (
              <button
                key={idx}
                onClick={() => handleOptionClick(option)}
                disabled={submitted}
                className={`group flex w-full items-center gap-3 rounded-lg border px-4 py-2.5 text-left text-sm transition-all ${
                  selectedOption === option
                    ? 'border-amber-500 bg-amber-500/20 text-amber-200'
                    : 'border-zinc-700 bg-zinc-800/50 text-zinc-300 hover:border-amber-500/50 hover:bg-amber-500/10 hover:text-amber-200'
                } disabled:cursor-not-allowed disabled:opacity-50`}
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-700 text-xs font-medium text-zinc-400 transition-colors group-hover:bg-amber-500/30 group-hover:text-amber-300">
                  {String.fromCharCode(65 + idx)}
                </span>
                <span className="flex-1">{option}</span>
              </button>
            ))}
          </div>
        )}

        {/* Custom input */}
        <div className="border-t border-amber-500/10 px-5 py-3">
          {!isCustomMode ? (
            <button
              onClick={() => setIsCustomMode(true)}
              className="w-full rounded-lg border border-dashed border-zinc-600 px-4 py-2 text-center text-xs text-zinc-500 transition-colors hover:border-amber-500/50 hover:text-amber-400"
            >
              ✏️ 自定义回答
            </button>
          ) : (
            <div className="flex gap-2">
              <input
                type="text"
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCustomSubmit()
                  if (e.key === 'Escape') {
                    setIsCustomMode(false)
                    setCustomInput('')
                  }
                }}
                placeholder="输入你的回答..."
                autoFocus
                className="flex-1 rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-500 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500/30"
              />
              <button
                onClick={handleCustomSubmit}
                disabled={!customInput.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                发送
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
