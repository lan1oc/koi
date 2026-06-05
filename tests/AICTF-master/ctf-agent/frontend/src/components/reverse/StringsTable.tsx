import { useState, useMemo } from 'react'
import { Search, ArrowUpDown } from 'lucide-react'
import type { StringsResult } from '../../types'

interface StringsTableProps {
  result: StringsResult | null
  loading: boolean
  onRefresh: (minLen: number) => void
}

export default function StringsTable({ result, loading, onRefresh }: StringsTableProps) {
  const [search, setSearch] = useState('')
  const [minLen, setMinLen] = useState(4)

  const filtered = useMemo(() => {
    if (!result?.strings) return []
    if (!search) return result.strings
    const q = search.toLowerCase()
    return result.strings.filter((s) => s.value.toLowerCase().includes(q))
  }, [result, search])

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索字符串..."
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
              text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <label className="text-xs text-gray-500">最小长度:</label>
          <input
            type="number"
            value={minLen}
            onChange={(e) => setMinLen(Number(e.target.value))}
            min={1}
            max={100}
            className="w-14 px-2 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
              text-gray-800 focus:outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
          />
          <button
            onClick={() => onRefresh(minLen)}
            disabled={loading}
            className="px-3 py-1.5 text-xs bg-purple-50 border border-purple-200 text-purple-600
              rounded-lg hover:bg-purple-100 disabled:opacity-50 transition-colors"
          >
            {loading ? '...' : '提取'}
          </button>
        </div>
      </div>

      {/* Stats */}
      {result && (
        <div className="text-xs text-gray-500 mb-2">
          共 {result.total} 条 · 显示 {filtered.length} 条
          {search && ` · 匹配 "${search}"`}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto rounded-xl border border-gray-200 bg-white">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-6 w-6 border-2 border-purple-500 border-t-transparent" />
          </div>
        ) : !result?.strings?.length ? (
          <div className="flex items-center justify-center h-32 text-sm text-gray-500">
            <ArrowUpDown className="w-4 h-4 mr-2" />
            点击「提取」获取字符串列表
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium w-12">#</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">内容</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 2000).map((s, i) => (
                <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-1.5 text-gray-400 font-mono">{i + 1}</td>
                  <td className="px-3 py-1.5 text-gray-700 font-mono break-all select-all">{s.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
