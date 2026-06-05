import { useNavigate } from 'react-router-dom'
import { Flag, ExternalLink, Clock, CheckCircle2, Trash2, Play, Sparkles, FastForward, ChevronDown, Pencil } from 'lucide-react'
import { agentApi, sessionApi } from '../services/api'
import { useSettingsStore } from '../stores/settingsStore'
import { useChallengeStore } from '../stores/challengeStore'
import type { Challenge, ChallengeCategory } from '../types'
import { useState, useRef, useEffect, memo } from 'react'

const categoryBadgeClass: Record<string, string> = {
  web: 'badge-web',
  pwn: 'badge-pwn',
  reverse: 'badge-reverse',
  crypto: 'badge-crypto',
  misc: 'badge-misc',
  forensics: 'badge-forensics',
}

function getBadgeClass(category: string): string {
  return categoryBadgeClass[category] || 'badge-misc'
}

interface ChallengeCardProps {
  challenge: Challenge
  compact?: boolean
  onDelete?: (id: string) => void
  onEdit?: (challenge: Challenge) => void
  selectable?: boolean
  selected?: boolean
  onSelect?: (id: string) => void
}

const statusOptions = [
  { value: 'unsolved', label: '待解', color: 'text-gray-500' },
  { value: 'pending', label: '等待中', color: 'text-gray-400' },
  { value: 'in_progress', label: '进行中', color: 'text-amber-600' },
  { value: 'solved', label: '已解决', color: 'text-green-600' },
  { value: 'failed', label: '失败', color: 'text-red-500' },
]

function ChallengeCardInner({ challenge, compact, onDelete, onEdit, selectable, selected, onSelect }: ChallengeCardProps) {
  const navigate = useNavigate()
  const { selectedModel } = useSettingsStore()
  const { updateChallengeStatus } = useChallengeStore()
  const [solving, setSolving] = useState(false)
  const [showStatusMenu, setShowStatusMenu] = useState(false)
  const statusMenuRef = useRef<HTMLDivElement>(null)
  const hasInstance = (challenge.category === 'web' || challenge.category === 'pwn') && challenge.instance_url

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (statusMenuRef.current && !statusMenuRef.current.contains(e.target as Node)) {
        setShowStatusMenu(false)
      }
    }
    if (showStatusMenu) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showStatusMenu])

  const handleStatusChange = async (newStatus: string) => {
    setShowStatusMenu(false)
    if (newStatus === challenge.status) return
    try {
      await updateChallengeStatus(challenge.id, newStatus)
    } catch (err) {
      console.error('Failed to update status:', err)
    }
  }

  const statusColor =
    challenge.status === 'solved'
      ? 'text-green-600'
      : challenge.status === 'in_progress'
      ? 'text-amber-600'
      : challenge.status === 'failed'
      ? 'text-red-500'
      : 'text-gray-400'

  const handleClick = () => {
    navigate(`/solve/${challenge.id}`)
  }

  const handleSolve = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setSolving(true)
    try {
      await agentApi.solve(challenge.id, undefined, selectedModel)
    } catch (err) {
      console.error('Failed to start solving:', err)
    } finally {
      setSolving(false)
    }
  }

  const handleContinue = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setSolving(true)
    try {
      const sess = await sessionApi.getByChallenge(challenge.id)
      await agentApi.continue(sess.id, selectedModel)
    } catch (err) {
      console.error('Failed to continue solving:', err)
    } finally {
      setSolving(false)
    }
  }

  const isInterrupted = challenge.status === 'in_progress' || challenge.status === 'failed'

  if (compact) {
    return (
      <button
        onClick={handleClick}
        className="flex items-center gap-3 w-full px-3 py-2 rounded-lg hover:bg-surface-hover transition-colors text-left"
      >
        <Flag className={`w-4 h-4 ${statusColor} flex-shrink-0`} />
        <span className="text-sm text-gray-700 truncate flex-1">{challenge.title}</span>
        <span className={getBadgeClass(challenge.category)}>{challenge.category}</span>
      </button>
    )
  }

  return (
    <div
      onClick={selectable ? () => onSelect?.(challenge.id) : handleClick}
      className={`panel transition-all duration-300 cursor-pointer group ${
        challenge.status === 'solved' ? 'panel-solved' : ''
      } ${
        selectable && selected
          ? 'border-primary-500 bg-primary-50/30 ring-1 ring-primary-500/30'
          : challenge.status === 'solved'
          ? 'border-green-400 bg-green-50/50 ring-1 ring-green-400/30 hover:border-green-500 hover:shadow-green-100'
          : 'hover:border-primary-600/50'
      }`}
    >
      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            {selectable && (
              <input
                type="checkbox"
                checked={selected || false}
                onChange={() => onSelect?.(challenge.id)}
                onClick={(e) => e.stopPropagation()}
                className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 flex-shrink-0"
              />
            )}
            <h3 className="font-semibold text-gray-900 group-hover:text-primary-600 transition-colors truncate">
              {challenge.title}
            </h3>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {challenge.points != null && challenge.points > 0 && (
              <span className="text-xs font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">{challenge.points}pt</span>
            )}
            <span className={getBadgeClass(challenge.category)}>{challenge.category}</span>
          </div>
        </div>

        {/* Platform & URL */}
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {challenge.platform && <span>{challenge.platform}</span>}
          {challenge.url && (
            <a
              href={challenge.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-primary-500 hover:text-primary-400"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-3 h-3" />
              链接
            </a>
          )}
        </div>

        {/* Description */}
        {challenge.description && (
          <p className="text-sm text-gray-500 line-clamp-2">{challenge.description}</p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1">
          <div className="relative" ref={statusMenuRef}>
            <button
              onClick={(e) => { e.stopPropagation(); setShowStatusMenu(!showStatusMenu) }}
              className={`flex items-center gap-1 text-xs ${statusColor} hover:bg-gray-100 rounded px-1.5 py-0.5 transition-colors`}
              title="点击修改状态"
            >
              {challenge.status === 'solved' ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : (
                <Clock className="w-3.5 h-3.5" />
              )}
              <span className="capitalize">{challenge.status.replace('_', ' ')}</span>
              <ChevronDown className="w-3 h-3 opacity-50" />
            </button>
            {showStatusMenu && (
              <div className="absolute left-0 bottom-full mb-1 bg-white [html.theme-dark_&]:bg-[#1e2133] border border-gray-200 rounded-lg shadow-lg z-50 py-1 min-w-[120px]">
                {statusOptions.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={(e) => { e.stopPropagation(); handleStatusChange(opt.value) }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 transition-colors flex items-center gap-2 ${
                      challenge.status === opt.value ? 'bg-gray-50 font-medium' : ''
                    } ${opt.color}`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {challenge.attachments?.length > 0 && (
              <span className="text-xs text-gray-400">
                {challenge.attachments.length} 个文件
              </span>
            )}

            {/* Solve / Continue button */}
            {challenge.status !== 'solved' && (
              isInterrupted ? (
                <button
                  onClick={handleContinue}
                  disabled={solving}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 text-amber-600 hover:bg-amber-100 text-xs font-medium transition-colors"
                  title="继续解题"
                >
                  <FastForward className="w-3 h-3" />
                  {solving ? '启动中...' : '继续'}
                </button>
              ) : (
                <button
                  onClick={handleSolve}
                  disabled={solving}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-primary-50 text-primary-600 hover:bg-primary-100 text-xs font-medium transition-colors"
                  title="AI 解题"
                >
                  <Sparkles className="w-3 h-3" />
                  {solving ? '启动中...' : '解题'}
                </button>
              )
            )}

            {/* Launch instance button for web/pwn */}
            {hasInstance && (
              <a
                href={challenge.instance_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-1 px-2 py-0.5 rounded bg-green-50 text-green-600 hover:bg-green-100 text-xs font-medium transition-colors"
                title="打开靶机"
              >
                <Play className="w-3 h-3" />
                靶机
              </a>
            )}

            {/* Edit button */}
            {onEdit && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onEdit(challenge)
                }}
                className="p-1 rounded text-gray-300 hover:text-primary-500 hover:bg-primary-50 transition-colors opacity-0 group-hover:opacity-100"
                title="编辑题目"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Delete button */}
            {onDelete && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  if (confirm(`确定删除题目 "${challenge.title}" 吗？`)) {
                    onDelete(challenge.id)
                  }
                }}
                className="p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                title="删除题目"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const ChallengeCard = memo(ChallengeCardInner)
export default ChallengeCard
