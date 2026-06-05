import { useState } from 'react'
import { Search, Key, Lock, Hash, Shield } from 'lucide-react'
import type { AlgorithmSignature } from '../../types'

interface AlgorithmTableProps {
  algorithms: AlgorithmSignature[]
  loading: boolean
}

const categoryIcons: Record<string, typeof Key> = {
  stream_cipher: Key,
  block_cipher: Lock,
  hash: Hash,
  encoding: Shield,
  checksum: Hash,
}

const categoryColors: Record<string, string> = {
  stream_cipher: 'border-blue-200 bg-blue-50',
  block_cipher: 'border-purple-200 bg-purple-50',
  hash: 'border-green-200 bg-green-50',
  encoding: 'border-amber-200 bg-amber-50',
  checksum: 'border-gray-200 bg-gray-50',
}

export default function AlgorithmTable({ algorithms, loading }: AlgorithmTableProps) {
  const [search, setSearch] = useState('')

  const filtered = algorithms.filter((a) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      a.name.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q) ||
      a.constants.some((c) => c.toLowerCase().includes(q))
    )
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-purple-500 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="relative mb-3">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索算法名/常量..."
          className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
            text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
        />
      </div>

      <div className="flex-1 overflow-auto space-y-2">
        {filtered.map((algo) => {
          const Icon = categoryIcons[algo.category] || Key
          const colorClass = categoryColors[algo.category] || categoryColors.checksum
          return (
            <div key={algo.name} className={`p-3 rounded-xl border ${colorClass}`}>
              <div className="flex items-center gap-2 mb-1.5">
                <Icon className="w-3.5 h-3.5 text-gray-500" />
                <span className="text-sm font-medium text-gray-800">{algo.name}</span>
                {algo.key_size && (
                  <span className="text-xs text-gray-500 ml-auto">{algo.key_size}</span>
                )}
              </div>
              <p className="text-xs text-gray-500 mb-2">{algo.description}</p>
              <div className="space-y-1">
                {algo.constants.map((c, i) => (
                  <div key={i} className="flex items-start gap-1.5">
                    <span className="text-[10px] text-gray-400 mt-0.5 shrink-0">▸</span>
                    <code className="text-[11px] font-mono text-amber-700 break-all">{c}</code>
                  </div>
                ))}
              </div>
              {algo.tips && (
                <p className="text-[11px] text-purple-600 mt-2 italic">💡 {algo.tips}</p>
              )}
            </div>
          )
        })}
        {filtered.length === 0 && (
          <div className="text-sm text-gray-500 text-center py-8">无匹配算法</div>
        )}
      </div>
    </div>
  )
}
