import { useNavigate } from 'react-router-dom'
import { Trophy, ExternalLink, Flag, CheckCircle2 } from 'lucide-react'
import type { Competition } from '../types'

interface CompetitionCardProps {
  competition: Competition
}

export default function CompetitionCard({ competition }: CompetitionCardProps) {
  const navigate = useNavigate()

  const statusLabel =
    competition.status === 'active'
      ? '进行中'
      : competition.status === 'archived'
      ? '已归档'
      : '导入中'

  const statusColor =
    competition.status === 'active'
      ? 'text-green-600 bg-green-50'
      : competition.status === 'archived'
      ? 'text-gray-500 bg-gray-50'
      : 'text-amber-600 bg-amber-50'

  const progress =
    competition.challenge_count > 0
      ? Math.round((competition.solved_count / competition.challenge_count) * 100)
      : 0

  return (
    <div
      onClick={() => navigate(`/competitions/${competition.id}`)}
      className="panel hover:border-primary-600/50 transition-colors cursor-pointer group"
    >
      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Trophy className="w-5 h-5 text-primary-500 flex-shrink-0" />
            <h3 className="font-semibold text-gray-900 group-hover:text-primary-600 transition-colors truncate">
              {competition.name}
            </h3>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${statusColor}`}>
            {statusLabel}
          </span>
        </div>

        {/* Platform & URL */}
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {competition.platform && <span>{competition.platform}</span>}
          {competition.url && (
            <a
              href={competition.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-primary-500 hover:text-primary-400"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-3 h-3" />
              平台链接
            </a>
          )}
        </div>

        {/* Description */}
        {competition.description && (
          <p className="text-sm text-gray-500 line-clamp-2">{competition.description}</p>
        )}

        {/* Progress */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 text-gray-500">
              <Flag className="w-3.5 h-3.5" />
              <span>{competition.challenge_count} 道题目</span>
            </div>
            <div className="flex items-center gap-1.5 text-green-600">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>{competition.solved_count} 已解决</span>
            </div>
          </div>
          <div className="w-full bg-surface-100 rounded-full h-1.5">
            <div
              className="bg-green-500 h-1.5 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Time */}
        {(competition.start_time || competition.end_time) && (
          <div className="text-xs text-gray-400">
            {competition.start_time && (
              <span>{new Date(competition.start_time).toLocaleDateString()}</span>
            )}
            {competition.start_time && competition.end_time && <span> - </span>}
            {competition.end_time && (
              <span>{new Date(competition.end_time).toLocaleDateString()}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
