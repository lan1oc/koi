import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Plus,
  Search,
  Sparkles,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Trash2,
  Square,
  Settings,
  ListChecks,
  X,
  PlayCircle,
  Flag,
  Timer,
  Pencil,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Waypoints,
  Save,
} from 'lucide-react'
import { competitionApi, agentApi, challengeApi } from '../services/api'
import { useChallengeStore } from '../stores/challengeStore'
import { useSettingsStore } from '../stores/settingsStore'
import { usePipelineStore } from '../stores/pipelineStore'
import { wsService } from '../services/websocket'
import ChallengeCard from '../components/ChallengeCard'
import CompetitionFormModal from '../components/CompetitionFormModal'
import type { Competition, Challenge, ParseJob, ChallengeCategory, ChallengeStatus, PlatformProfile } from '../types'

const BASE_CATEGORIES = ['web', 'pwn', 'reverse', 'crypto', 'misc', 'forensics']
const statuses: ChallengeStatus[] = ['unsolved', 'in_progress', 'solved', 'failed']

/** Generate page number array with ellipsis for large page counts */
function generatePageNumbers(current: number, total: number): (number | '...')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '...')[] = []
  pages.push(1)
  if (current > 3) pages.push('...')
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
    pages.push(i)
  }
  if (current < total - 2) pages.push('...')
  pages.push(total)
  return pages
}

function formatDuration(ms: number): string {
  if (ms <= 0) return '0s'
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h${m}m${s}s`
  if (m > 0) return `${m}m${s}s`
  return `${s}s`
}

export default function CompetitionDetail() {
  const { competitionId } = useParams<{ competitionId: string }>()
  const navigate = useNavigate()
  const { challenges, totalCount, currentPage, pageSize, fetchChallengesPaginated, setPage, setPageSize,
    loading, createChallenge, deleteChallenge, updateChallenge,
    catFilter, setCatFilter, statusFilter, setStatusFilter, searchQuery, setSearchQuery,
    categoryCounts, refreshCategoryCounts } = useChallengeStore()
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const { selectedModel, providers, fetchProviders } = useSettingsStore()

  // Ensure providers are loaded for arena model selector
  useEffect(() => { fetchProviders() }, [])

  const [competition, setCompetition] = useState<Competition | null>(null)
  const [loadingComp, setLoadingComp] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editingChallenge, setEditingChallenge] = useState<Challenge | null>(null)

  // Parse state
  const [parseJob, setParseJob] = useState<ParseJob | null>(null)
  const [parsing, setParsing] = useState(false)
  const [parseError, setParseError] = useState('')
  const [parseAgentId, setParseAgentId] = useState<string | null>(null)
  const [showParseModal, setShowParseModal] = useState(false)
  const [showPlatformProfileModal, setShowPlatformProfileModal] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Pipeline (batch solve) state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [pipelineCollapsed, setPipelineCollapsed] = useState(false)
  const pipelineStartAction = usePipelineStore((s) => s.startPipeline)
  const pipelineStopAction = usePipelineStore((s) => s.stopPipeline)
  const pipelineDismiss = usePipelineStore((s) => s.dismiss)
  const pipelineGetElapsed = usePipelineStore((s) => s.getElapsedMs)
  const getPipelineForCompetition = usePipelineStore((s) => s.getPipelineForCompetition)
  // Get pipeline entry for this competition
  const pipelineEntry = competitionId ? getPipelineForCompetition(competitionId) : null
  const pipelineRunning = pipelineEntry?.running ?? false
  const pipelineResults = pipelineEntry?.results ?? []
  const pipelineCurrent = pipelineEntry?.current ?? 0
  const pipelineTotal = pipelineEntry?.total ?? 0
  const pipelineId = pipelineEntry?.pipelineId ?? null
  const [elapsedMs, setElapsedMs] = useState(0)
  const [pipeMaxRounds, setPipeMaxRounds] = useState(0)
  const [pipeMaxTime, setPipeMaxTime] = useState(0)
  const [resettingInProgress, setResettingInProgress] = useState(false)
  const [pipeRetry, setPipeRetry] = useState(false)
  const [pipeMaxConcurrent, setPipeMaxConcurrent] = useState(0)
  const [pipeCatConc, setPipeCatConc] = useState<Record<string, number>>({})
  const [showConcSettings, setShowConcSettings] = useState(false)
  const [pipeArenaModelB, setPipeArenaModelB] = useState('')

  // Live elapsed timer for pipeline
  useEffect(() => {
    if (!pipelineId) return
    const tick = () => setElapsedMs(pipelineGetElapsed(pipelineId))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [pipelineId, pipelineRunning, pipelineGetElapsed])

  // Load competition
  useEffect(() => {
    if (!competitionId) return
    setLoadingComp(true)
    competitionApi.get(competitionId).then((comp) => {
      setCompetition(comp)
      setLoadingComp(false)
    }).catch(() => {
      setLoadingComp(false)
    })
  }, [competitionId])

  // Helper: update filter in store and fetch page 1
  const refreshChallengeList = useCallback((page?: number) => {
    if (!competitionId) return
    useChallengeStore.setState({
      filter: {
        competition_id: competitionId,
        search: searchQuery || undefined,
        category: (catFilter || undefined) as ChallengeCategory | undefined,
        status: (statusFilter || undefined) as ChallengeStatus | undefined,
      },
      currentPage: page ?? 1,
    })
    fetchChallengesPaginated(page ?? 1)
  }, [competitionId, searchQuery, catFilter, statusFilter, fetchChallengesPaginated])

  // Load challenges for this competition
  useEffect(() => {
    if (!competitionId) return
    useChallengeStore.setState({
      catFilter: '',
      statusFilter: '',
      searchQuery: '',
      filter: { competition_id: competitionId },
      currentPage: 1,
    })
    setSelectMode(false)
    setSelectedIds(new Set())
    fetchChallengesPaginated(1)
    refreshCategoryCounts(competitionId)
  }, [competitionId, fetchChallengesPaginated, refreshCategoryCounts])

  // Search/filter debounce
  useEffect(() => {
    if (!competitionId) return
    const timer = setTimeout(() => {
      refreshChallengeList(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery, catFilter, statusFilter, competitionId, refreshChallengeList])

  // Cleanup poll on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  // Listen for parse_complete and challenge_imported events
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!competitionId) return
    wsService.connect()
    const unsub = wsService.onAll((event) => {
      if (event.type === 'challenge_imported') {
        // Real-time: a new challenge was just imported, debounce refresh to avoid flooding
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
        refreshTimerRef.current = setTimeout(() => {
          refreshChallengeList()
          refreshCategoryCounts(competitionId)
          competitionApi.get(competitionId).then(setCompetition)
        }, 500)
      }
      if (event.type === 'parse_complete') {
        // Final refresh when everything is done
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
        refreshChallengeList()
        refreshCategoryCounts(competitionId)
        competitionApi.get(competitionId).then(setCompetition)
        setParsing(false)
        setParseAgentId(null)
        if (pollRef.current) clearInterval(pollRef.current)
      }

      // Pipeline events: refresh challenge list when a challenge completes or pipeline ends
      const pe = event as any
      if (pe.type === 'pipeline_challenge_end' || pe.type === 'pipeline_end' || pe.type === 'pipeline_stopped') {
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
        refreshTimerRef.current = setTimeout(() => {
          refreshChallengeList()
          refreshCategoryCounts(competitionId)
          competitionApi.get(competitionId).then(setCompetition)
        }, 500)
      }
    })
    return () => {
      unsub()
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    }
  }, [competitionId, refreshChallengeList])

  const handleParse = useCallback(async (instruction?: string) => {
    if (!competitionId) return
    setShowParseModal(false)
    setParsing(true)
    setParseError('')
    setParseJob(null)

    // Clear any existing polling interval before creating a new one
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    try {
      const { job_id, agent_id } = await competitionApi.parse(
        competitionId,
        selectedModel,
        instruction?.trim() || undefined
      )
      setParseAgentId(agent_id || null)

      // Start polling
      pollRef.current = setInterval(async () => {
        try {
          const job = await competitionApi.parseStatus(competitionId, job_id)
          setParseJob(job)

          if (job.status === 'completed' || job.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current)
            setParsing(false)
            setParseAgentId(null)
            if (job.status === 'failed') {
              setParseError(job.error || '解析失败')
            } else {
              // Refresh challenges
              refreshChallengeList()
              // Refresh competition for updated counts
              competitionApi.get(competitionId).then(setCompetition)
            }
          }
        } catch {
          // Keep polling
        }
      }, 2000)
    } catch (err) {
      setParsing(false)
      setParseError((err as Error).message)
    }
  }, [competitionId, selectedModel])

  const handleDelete = async () => {
    if (!competitionId || !confirm('确定要删除这个比赛吗？所有关联的题目也会被删除。')) return
    try {
      await competitionApi.delete(competitionId)
      navigate('/competitions')
    } catch (err) {
      console.error('Failed to delete competition:', err)
    }
  }

  const handleDeleteChallenge = async (id: string) => {
    try {
      await deleteChallenge(id)
      if (competitionId) {
        competitionApi.get(competitionId).then(setCompetition)
      }
    } catch (err) {
      console.error('Failed to delete challenge:', err)
    }
  }

  const handleStopParse = async () => {
    if (!parseAgentId) return
    try {
      await agentApi.stop(parseAgentId)
      setParsing(false)
      setParseAgentId(null)
      if (pollRef.current) clearInterval(pollRef.current)
      // Refresh challenges in case some were already imported
      if (competitionId) {
        refreshChallengeList()
        competitionApi.get(competitionId).then(setCompetition)
      }
    } catch (err) {
      console.error('Failed to stop parser agent:', err)
    }
  }

  // Pipeline handlers
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const c of challenges) next.add(c.id)
      return next
    })
  }

  const selectAllUnsolved = async () => {
    if (!competitionId) return
    try {
      // Respect the current filter scope, then exclude solved items.
      const all = await challengeApi.list({
        competition_id: competitionId,
        ...(catFilter ? { category: catFilter as ChallengeCategory } : {}),
        ...(statusFilter ? { status: statusFilter as ChallengeStatus } : {}),
        ...(searchQuery ? { search: searchQuery } : {}),
      })
      const unsolved = (all || []).filter((c) => c.status !== 'solved').map((c) => c.id)
      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (const id of unsolved) next.add(id)
        return next
      })
    } catch (e) {
      console.error('Failed to fetch all unsolved challenges:', e)
    }
  }

  const resetInProgress = async () => {
    if (!competitionId) return
    if (!confirm('确定要将所有「进行中」的题目重置为「未解答」吗？')) return
    setResettingInProgress(true)
    try {
      const all = await challengeApi.list({
        competition_id: competitionId,
        status: 'in_progress' as ChallengeStatus,
      })
      const targets = (all || []).filter((c) => c.status === 'in_progress')
      await Promise.all(targets.map((c) => challengeApi.updateStatus(c.id, 'unsolved')))
      refreshChallengeList()
      refreshCategoryCounts(competitionId)
    } catch (e) {
      console.error('Failed to reset in_progress challenges:', e)
    } finally {
      setResettingInProgress(false)
    }
  }

  const handleStartPipeline = async () => {
    if (selectedIds.size === 0) return
    const ids = Array.from(selectedIds)
    // Fetch full challenge info for all selected IDs (they may span multiple pages)
    let allChallenges: Challenge[] = []
    try {
      allChallenges = (await challengeApi.list({ competition_id: competitionId })) || []
    } catch { allChallenges = challenges }
    const chList = allChallenges
      .filter((c) => selectedIds.has(c.id))
      .map((c) => ({ id: c.id, title: c.title }))
    // Build category_concurrency, only include non-zero values
    const catConc: Record<string, number> = {}
    for (const [cat, val] of Object.entries(pipeCatConc)) {
      if (val > 0) catConc[cat] = val
    }
    await pipelineStartAction(ids, chList, selectedModel, {
      max_rounds: pipeMaxRounds,
      max_time_per_challenge: pipeMaxTime,
      retry_failed: pipeRetry,
      max_concurrent: pipeMaxConcurrent,
      category_concurrency: catConc,
      arena_model_b: pipeArenaModelB,
    }, competitionId, competition?.name)
    setSelectMode(false)
    setSelectedIds(new Set())
    setPipelineCollapsed(false)
  }

  const handleStopPipeline = async () => {
    if (!pipelineId) return
    await pipelineStopAction(pipelineId)
  }

  if (loadingComp) {
    return (
      <div className="p-6 text-center text-gray-500">
        <Loader2 className="w-6 h-6 animate-spin mx-auto" />
      </div>
    )
  }

  if (!competition) {
    return (
      <div className="p-6 text-center text-gray-500">
        比赛不存在
      </div>
    )
  }

  return (
    <div className="relative flex flex-col h-full">
      {/* Floating header */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[calc(100%-2rem)]">
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-2xl bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_4px_24px_rgba(0,0,0,0.08)]">
        <button
          onClick={() => navigate('/competitions')}
          className="p-1.5 rounded-lg hover:bg-surface-hover transition-colors flex-shrink-0"
        >
          <ArrowLeft className="w-4 h-4 text-gray-500" />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-bold text-gray-900 truncate">{competition.name}</h1>
          <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
            {competition.platform && <span>{competition.platform}</span>}
            {competition.url && (
              <a
                href={competition.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-primary-500 hover:text-primary-400"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                平台链接
              </a>
            )}
            <span>
              {competition.challenge_count} 题 / {competition.solved_count} 已解决
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowPlatformProfileModal(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors"
            title="解析该平台的 API 格式，配置靶机开关、Flag提交等信息"
          >
            <Waypoints className="w-4 h-4" />
            平台格式
          </button>
          <button
            onClick={() => parsing ? undefined : setShowParseModal(true)}
            disabled={parsing}
            className="btn-primary flex items-center gap-2"
          >
            {parsing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {parsing ? 'AI 解析中...' : 'AI 解析题目'}
          </button>
          {parsing && (
            <button
              onClick={handleStopParse}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-red-50 text-red-600 hover:bg-red-100 transition-colors text-sm font-medium"
              title="停止 AI 解析"
            >
              <Square className="w-3.5 h-3.5" />
              停止
            </button>
          )}
          <button
            onClick={() => {
              setSelectMode(!selectMode)
              if (selectMode) setSelectedIds(new Set())
            }}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectMode
                ? 'bg-primary-100 text-primary-700'
                : 'bg-surface-50 text-gray-600 hover:bg-surface-hover'
            }`}
          >
            <ListChecks className="w-4 h-4" />
            {selectMode ? '取消选择' : '批量解题'}
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="btn-secondary flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            手动添加
          </button>
          <button
            onClick={() => setShowEdit(true)}
            className="p-2 rounded-lg text-gray-400 hover:text-primary-500 hover:bg-primary-50 transition-colors"
            title="编辑比赛"
          >
            <Settings className="w-4 h-4" />
          </button>
          <button
            onClick={handleDelete}
            className="p-2 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="删除比赛"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto pt-20 pb-4 px-4 space-y-4">

      {/* Parse Progress */}
      {(parseJob || parseError) && (
        <div className={`panel p-3 flex items-center gap-3 flex-shrink-0 ${parseError ? 'border-red-200' : 'border-primary-200'}`}>
          {parseJob?.status === 'running' && (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
              <span className="text-sm text-gray-600">
                正在解析... 已发现 {parseJob.total_found} 道题目，已导入 {parseJob.total_imported} 道
              </span>
            </>
          )}
          {parseJob?.status === 'completed' && (
            <>
              <CheckCircle2 className="w-4 h-4 text-green-500" />
              <span className="text-sm text-green-600">
                解析完成！共导入 {parseJob.total_imported}/{parseJob.total_found} 道题目
              </span>
            </>
          )}
          {(parseJob?.status === 'failed' || parseError) && (
            <>
              <AlertCircle className="w-4 h-4 text-red-500" />
              <span className="text-sm text-red-600">
                {parseError || parseJob?.error || '解析失败'}
              </span>
            </>
          )}
        </div>
      )}

      {/* Select Mode Action Bar */}
      {selectMode && (
        <div className="panel p-3 flex items-center gap-3 flex-shrink-0 border-primary-200 bg-primary-50/30 flex-wrap">
          <span className="text-sm text-gray-600">
            已选择 <strong className="text-primary-600">{selectedIds.size}</strong> 道题目
          </span>
          <button
            onClick={selectAll}
            className="text-xs text-primary-600 hover:text-primary-700 font-medium"
          >
            全选当前页
          </button>
          <button
            onClick={selectAllUnsolved}
            className="text-xs text-primary-600 hover:text-primary-700 font-medium"
          >
            全选未解决
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-xs text-gray-500 hover:text-gray-700 font-medium"
          >
            清空
          </button>
          <div className="flex items-center gap-3 ml-4">
            <label className="flex items-center gap-1 text-xs text-gray-600">
              最大轮次
              <input
                type="number"
                min={0}
                value={pipeMaxRounds || ''}
                onChange={(e) => setPipeMaxRounds(parseInt(e.target.value) || 0)}
                placeholder="默认"
                className="w-16 px-1.5 py-0.5 rounded border border-gray-300 text-xs"
              />
            </label>
            <label className="flex items-center gap-1 text-xs text-gray-600">
              限时(秒)
              <input
                type="number"
                min={0}
                value={pipeMaxTime || ''}
                onChange={(e) => setPipeMaxTime(parseInt(e.target.value) || 0)}
                placeholder="不限"
                className="w-16 px-1.5 py-0.5 rounded border border-gray-300 text-xs"
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={pipeRetry}
                onChange={(e) => setPipeRetry(e.target.checked)}
                className="rounded border-gray-300"
              />
              失败重试
            </label>
            <label className="flex items-center gap-1 text-xs text-gray-600">
              并发数
              <input
                type="number"
                min={0}
                value={pipeMaxConcurrent || ''}
                onChange={(e) => setPipeMaxConcurrent(parseInt(e.target.value) || 0)}
                placeholder="顺序"
                className="w-16 px-1.5 py-0.5 rounded border border-gray-300 text-xs"
              />
            </label>
            <button
              onClick={() => setShowConcSettings(!showConcSettings)}
              className={`text-xs font-medium px-2 py-0.5 rounded transition-colors ${
                showConcSettings ? 'bg-primary-100 text-primary-700' : 'text-primary-600 hover:text-primary-700 hover:bg-primary-50'
              }`}
            >
              分类并发
            </button>
            <label className="flex items-center gap-1 text-xs text-gray-600">
              <span className="text-amber-600 font-medium">⚔ 竞技场</span>
              <select
                value={pipeArenaModelB}
                onChange={(e) => setPipeArenaModelB(e.target.value)}
                className="w-28 px-1.5 py-0.5 rounded border border-gray-300 text-xs"
              >
                <option value="">关闭</option>
                {providers
                  .filter((p) => p.name !== selectedModel)
                  .map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          {showConcSettings && (
            <div className="flex items-center gap-2 ml-4 mt-1">
              {Object.keys(categoryCounts).map((cat: string) => (
                <label key={cat} className="flex items-center gap-1 text-xs text-gray-600">
                  <span className="capitalize">{cat}</span>
                  <input
                    type="number"
                    min={0}
                    value={pipeCatConc[cat] || ''}
                    onChange={(e) => setPipeCatConc({ ...pipeCatConc, [cat]: parseInt(e.target.value) || 0 })}
                    placeholder="-"
                    className="w-12 px-1 py-0.5 rounded border border-gray-300 text-xs text-center"
                  />
                </label>
              ))}
            </div>
          )}
          <div className="flex-1" />
          <button
            onClick={handleStartPipeline}
            disabled={selectedIds.size === 0}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            <PlayCircle className="w-4 h-4" />
            开始流水线解题 ({selectedIds.size})
          </button>
        </div>
      )}

      {/* Pipeline Progress */}
      {pipelineResults.length > 0 && (
        <div className="panel flex-shrink-0 border-primary-200">
          {/* Header row — always visible, click to collapse/expand */}
          <div
            className="p-2.5 flex items-center justify-between cursor-pointer hover:bg-surface-50 select-none"
            onClick={() => setPipelineCollapsed(!pipelineCollapsed)}
          >
            <div className="flex items-center gap-2">
              {pipelineRunning ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-primary-500" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
              )}
              <span className="text-sm font-medium text-gray-700">
                流水线 {pipelineRunning ? '进行中' : '已完成'}: {pipelineCurrent}/{pipelineTotal}
              </span>
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Timer className="w-3 h-3" />
                {formatDuration(elapsedMs)}
              </span>
              <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary-500 rounded-full transition-all duration-500"
                  style={{ width: `${pipelineTotal > 0 ? (pipelineCurrent / pipelineTotal) * 100 : 0}%` }}
                />
              </div>
              {/* Quick stats */}
              {pipelineCollapsed && (() => {
                const solved = pipelineResults.filter((r) => r.status === 'solved').length
                const failed = pipelineResults.filter((r) => r.status === 'failed').length
                const solving = pipelineResults.filter((r) => r.status === 'solving').length
                return (
                  <span className="flex items-center gap-2 text-xs ml-1">
                    {solved > 0 && <span className="text-green-600 flex items-center gap-0.5"><Flag className="w-3 h-3" />{solved}</span>}
                    {failed > 0 && <span className="text-red-500 flex items-center gap-0.5"><AlertCircle className="w-3 h-3" />{failed}</span>}
                    {solving > 0 && <span className="text-amber-600 flex items-center gap-0.5"><Loader2 className="w-3 h-3 animate-spin" />{solving}</span>}
                  </span>
                )
              })()}
            </div>
            <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              {pipelineRunning && (
                <button
                  onClick={handleStopPipeline}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100 text-xs font-medium"
                >
                  <Square className="w-3 h-3" />
                  停止
                </button>
              )}
              {!pipelineRunning && pipelineId && (
                <button
                  onClick={() => pipelineDismiss(pipelineId)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); setPipelineCollapsed(!pipelineCollapsed) }}
                className="text-gray-400 hover:text-gray-600"
                title={pipelineCollapsed ? '展开' : '折叠'}
              >
                {pipelineCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
              </button>
            </div>
          </div>
          {/* Results row — collapsible */}
          {!pipelineCollapsed && (
            <div className="px-3 pb-3 flex flex-wrap gap-2">
              {pipelineResults.map((r) => (
                <button
                  key={r.challenge_id}
                  onClick={() => {
                    const params = r.session_id ? `?session=${r.session_id}` : ''
                    navigate(`/solve/${r.challenge_id}${params}`)
                  }}
                  title={r.session_id ? '点击查看对话记录' : '点击跳转到解题界面'}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium transition-opacity hover:opacity-80 cursor-pointer ${
                    r.status === 'solved'
                      ? 'bg-green-50 text-green-700'
                      : r.status === 'failed'
                      ? 'bg-red-50 text-red-600'
                      : r.status === 'timeout'
                      ? 'bg-orange-50 text-orange-600'
                      : r.status === 'solving'
                      ? 'bg-amber-50 text-amber-700'
                      : r.status === 'skipped'
                      ? 'bg-gray-100 text-gray-500'
                      : 'bg-gray-50 text-gray-500'
                  }`}
                >
                  {r.status === 'solving' && <Loader2 className="w-3 h-3 animate-spin" />}
                  {r.status === 'solved' && <Flag className="w-3 h-3" />}
                  {r.status === 'failed' && <AlertCircle className="w-3 h-3" />}
                  {r.status === 'timeout' && <Timer className="w-3 h-3" />}
                  {r.retry && <span className="text-[10px] opacity-60">↻</span>}
                  <span className="truncate max-w-[120px]">{r.challenge_title}</span>
                  {r.duration_ms != null && r.duration_ms > 0 && (
                    <span className="text-[10px] opacity-70">{formatDuration(r.duration_ms)}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Main Content: Challenge Grid */}
      <div className="flex gap-4 flex-1 min-h-0">
        {/* Challenge List */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          {/* Filters */}
          <div className="flex items-center gap-3 flex-wrap flex-shrink-0 mb-4">
            <div className="relative flex-1 min-w-[200px] max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索题目..."
                className="input-field w-full pl-9"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="input-field"
            >
              <option value="">全部状态</option>
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ').charAt(0).toUpperCase() + s.replace('_', ' ').slice(1)}
                </option>
              ))}
            </select>
            <button
              onClick={resetInProgress}
              disabled={resettingInProgress}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-orange-600 hover:bg-orange-50 border border-orange-200 transition-colors disabled:opacity-50"
              title="将所有进行中的题目重置为未解答"
            >
              {resettingInProgress ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RotateCcw className="w-3.5 h-3.5" />
              )}
              重置进行中
            </button>
          </div>

          {/* Category Tabs */}
          <div className="flex items-center gap-1.5 flex-shrink-0 mb-4 overflow-x-auto">
            {(() => {
              const totalCount = Object.values(categoryCounts).reduce((a, b) => a + b, 0)
              // Build dynamic category list from actual data
              const dynamicCats = Object.keys(categoryCounts).sort((a, b) => {
                const order = ['web', 'pwn', 'reverse', 'crypto', 'misc', 'forensics']
                const ai = order.indexOf(a), bi = order.indexOf(b)
                return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
              })
              return (
                <>
                  <button
                    onClick={() => setCatFilter('')}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                      catFilter === ''
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-50 text-gray-500 hover:bg-surface-hover hover:text-gray-700'
                    }`}
                  >
                    全部
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      catFilter === '' ? 'bg-white/20' : 'bg-gray-200/60'
                    }`}>{totalCount}</span>
                  </button>
                  {dynamicCats.map((c) => (
                    <button
                      key={c}
                      onClick={() => setCatFilter(catFilter === c ? '' : c)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                        catFilter === c
                          ? 'bg-primary-500 text-white'
                          : 'bg-surface-50 text-gray-500 hover:bg-surface-hover hover:text-gray-700'
                      }`}
                    >
                      {c.toUpperCase()}
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                        catFilter === c ? 'bg-white/20' : 'bg-gray-200/60'
                      }`}>{categoryCounts[c] || 0}</span>
                    </button>
                  ))}
                </>
              )
            })()}
          </div>

          {/* Challenge Grid */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="text-center text-gray-500 py-12">加载题目中...</div>
            ) : challenges.length === 0 ? (
              <div className="text-center text-gray-500 py-12">
                <p className="text-lg mb-2">暂无题目</p>
                <p className="text-sm">点击 "AI 解析题目" 自动获取，或手动添加题目</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 pb-4">
                {challenges.map((c) => (
                  <ChallengeCard
                    key={c.id}
                    challenge={c}
                    onDelete={handleDeleteChallenge}
                    onEdit={(ch) => setEditingChallenge(ch)}
                    selectable={selectMode}
                    selected={selectedIds.has(c.id)}
                    onSelect={toggleSelect}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Pagination — fixed at bottom, outside scroll area */}
          {!loading && challenges.length > 0 && totalPages > 1 && (
            <div className="flex items-center justify-between pt-3 pb-1 border-t border-gray-200 flex-shrink-0">
              <div className="text-sm text-gray-500">
                共 {totalCount} 道题目，第 {currentPage}/{totalPages} 页
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  className="btn-secondary px-2 py-1 disabled:opacity-40"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {generatePageNumbers(currentPage, totalPages).map((p, i) =>
                  p === '...' ? (
                    <span key={`ellipsis-${i}`} className="px-2 text-gray-400">…</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p as number)}
                      className={`px-3 py-1 rounded text-sm ${
                        currentPage === p
                          ? 'bg-indigo-600 text-white'
                          : 'btn-secondary'
                      }`}
                    >
                      {p}
                    </button>
                  )
                )}
                <button
                  onClick={() => setPage(currentPage + 1)}
                  disabled={currentPage >= totalPages}
                  className="btn-secondary px-2 py-1 disabled:opacity-40"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="input-field text-sm py-1 ml-2"
                >
                  {[12, 24, 48, 96].map((n) => (
                    <option key={n} value={n}>{n} / 页</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Create Challenge Modal */}
      {showCreate && (
        <CreateChallengeInCompetitionModal
          competitionId={competitionId!}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Edit Competition Modal */}
      {showEdit && (
        <CompetitionFormModal
          competition={competition}
          onClose={() => setShowEdit(false)}
          onSaved={(updated) => setCompetition(updated)}
        />
      )}

      {/* Edit Challenge Modal */}
      {editingChallenge && (
        <EditChallengeModal
          challenge={editingChallenge}
          onClose={() => setEditingChallenge(null)}
          onSaved={(updated) => {
            setEditingChallenge(null)
            if (competitionId) {
              competitionApi.get(competitionId).then(setCompetition)
            }
          }}
        />
      )}

      {/* Parse Modal */}
      {showParseModal && (
        <ParseInstructionModal
          onClose={() => setShowParseModal(false)}
          onConfirm={(instruction) => handleParse(instruction)}
        />
      )}

      {/* Platform Profile Modal */}
      {showPlatformProfileModal && competitionId && (
        <PlatformProfileModal
          competitionId={competitionId}
          platformUrl={competition?.url || ''}
          platformName={competition?.platform || ''}
          selectedModel={selectedModel}
          onClose={() => setShowPlatformProfileModal(false)}
          onSaved={() => {
            setShowPlatformProfileModal(false)
            if (competitionId) competitionApi.get(competitionId).then(setCompetition)
          }}
        />
      )}
      </div>
    </div>
  )
}

function ParseInstructionModal({
  onClose,
  onConfirm,
}: {
  onClose: () => void
  onConfirm: (instruction?: string) => void
}) {
  const [instruction, setInstruction] = useState('')

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-md">
        <div className="panel-header justify-between">
          <span className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-primary-500" />
            AI 解析题目
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-4 space-y-4">
          <p className="text-sm text-gray-500">
            AI 将自动访问比赛平台获取题目信息。你可以输入额外指令来控制解析行为。
          </p>
          <div>
            <label className="block text-xs text-gray-500 mb-1">额外指令（可选）</label>
            <input
              type="text"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              className="input-field w-full"
              placeholder="如：只获取 web 和 crypto 分类的题目"
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter') onConfirm(instruction || undefined) }}
            />
            <p className="text-xs text-gray-400 mt-1.5">
              示例：获取前5道题 / 只获取web题目 / 跳过已有的题目
            </p>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="btn-secondary">取消</button>
            <button
              onClick={() => onConfirm(instruction || undefined)}
              className="btn-primary flex items-center gap-2"
            >
              <Sparkles className="w-4 h-4" />
              开始解析
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function EditChallengeModal({
  challenge,
  onClose,
  onSaved,
}: {
  challenge: Challenge
  onClose: () => void
  onSaved: (updated: Challenge) => void
}) {
  const { updateChallenge, categoryCounts } = useChallengeStore()
  const [form, setForm] = useState({
    title: challenge.title,
    category: challenge.category,
    url: challenge.url || '',
    instance_url: challenge.instance_url || '',
    description: challenge.description || '',
    flag: challenge.flag || '',
  })
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await updateChallenge(challenge.id, { ...challenge, ...form })
      onSaved(challenge)
    } catch (err) {
      console.error('Failed to update challenge:', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg">
        <div className="panel-header justify-between">
          <span className="flex items-center gap-2">
            <Pencil className="w-4 h-4 text-primary-500" />
            编辑题目
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">标题 *</label>
            <input
              type="text"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="input-field w-full"
              placeholder="题目名称"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">分类</label>
              <input
                type="text"
                list="edit-category-list"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="input-field w-full"
                placeholder="输入或选择分类"
              />
              <datalist id="edit-category-list">
                {[...new Set([...BASE_CATEGORIES, ...Object.keys(categoryCounts)])].map((c: string) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">URL</label>
              <input
                type="url"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                className="input-field w-full"
                placeholder="https://..."
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">靶机地址</label>
            <input
              type="text"
              value={form.instance_url}
              onChange={(e) => setForm({ ...form, instance_url: e.target.value })}
              className="input-field w-full"
              placeholder="http://靶机地址:端口"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">描述</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="input-field w-full resize-none"
              rows={4}
              placeholder="题目描述、提示信息..."
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Flag</label>
            <input
              type="text"
              value={form.flag}
              onChange={(e) => setForm({ ...form, flag: e.target.value })}
              className="input-field w-full"
              placeholder="flag{...}"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">取消</button>
            <button type="submit" disabled={saving || !form.title.trim()} className="btn-primary">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CreateChallengeInCompetitionModal({
  competitionId,
  onClose,
}: {
  competitionId: string
  onClose: () => void
}) {
  const { createChallenge, categoryCounts } = useChallengeStore()
  const [form, setForm] = useState({
    title: '',
    category: 'web',
    url: '',
    description: '',
  })
  const [creating, setCreating] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setCreating(true)
    try {
      await createChallenge({
        ...form,
        competition_id: competitionId,
      })
      onClose()
    } catch (err) {
      console.error('Failed to create challenge:', err)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg">
        <div className="panel-header justify-between">
          <span>添加题目</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">标题 *</label>
            <input
              type="text"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="input-field w-full"
              placeholder="题目名称"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">分类</label>
              <input
                type="text"
                list="create-category-list"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="input-field w-full"
                placeholder="输入或选择分类"
              />
              <datalist id="create-category-list">
                {[...new Set([...BASE_CATEGORIES, ...Object.keys(categoryCounts)])].map((c: string) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">URL</label>
              <input
                type="url"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                className="input-field w-full"
                placeholder="https://..."
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">描述</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="input-field w-full resize-none"
              rows={3}
              placeholder="题目描述、提示信息..."
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">取消</button>
            <button type="submit" disabled={creating || !form.title.trim()} className="btn-primary">
              {creating ? '创建中...' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Platform Profile Modal ───
function PlatformProfileModal({
  competitionId,
  platformUrl,
  platformName,
  selectedModel,
  onClose,
  onSaved,
}: {
  competitionId: string
  platformUrl: string
  platformName: string
  selectedModel?: string
  onClose: () => void
  onSaved: () => void
}) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeStatus, setAnalyzeStatus] = useState<string>('')
  const analyzePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [profile, setProfile] = useState<PlatformProfile>({
    platform_type: platformName || '',
    get_challenges: '',
    get_instance: '',
    start_instance: '',
    stop_instance: '',
    renew_instance: '',
    submit_flag: '',
    notes: '',
  })

  // Load existing profile
  useEffect(() => {
    competitionApi.getPlatformProfile(competitionId).then((res) => {
      if (res.platform_profile) {
        setProfile((prev) => ({ ...prev, ...res.platform_profile }))
      }
    }).catch(() => {}).finally(() => setLoading(false))
  }, [competitionId])

  const handleSave = async () => {
    setSaving(true)
    try {
      await competitionApi.setPlatformProfile(competitionId, profile)
      onSaved()
    } catch (err) {
      console.error('Failed to save platform profile:', err)
    } finally {
      setSaving(false)
    }
  }

  // AI automatic analysis
  const handleAIAnalyze = async () => {
    setAnalyzing(true)
    setAnalyzeStatus('正在启动 AI 分析...')
    // Record initial profile state to detect real changes
    const initialHash = JSON.stringify(profile)
    try {
      const { session_id } = await competitionApi.analyzePlatform(competitionId, selectedModel)
      setAnalyzeStatus('AI 正在探测平台 API，请稍候...')

      // Helper: fetch profile and update form
      const fetchAndApplyProfile = async (): Promise<boolean> => {
        const res = await competitionApi.getPlatformProfile(competitionId)
        if (res.platform_profile) {
          const newHash = JSON.stringify(res.platform_profile)
          // Only update if profile actually changed from initial state
          if (newHash !== initialHash && newHash !== '{}' && newHash !== 'null') {
            setProfile((prev) => ({ ...prev, ...res.platform_profile! }))
            setAnalyzeStatus('AI 分析完成！')
            setAnalyzing(false)
            return true
          }
        }
        return false
      }

      // Listen for WS event — immediate detection
      const unsub = wsService.on('platform_profile_saved', async (event: any) => {
        if (event.session_id === session_id) {
          unsub()
          if (analyzePollRef.current) {
            clearInterval(analyzePollRef.current)
            analyzePollRef.current = null
          }
          await fetchAndApplyProfile()
        }
      })

      // Also poll as fallback in case WS event is missed
      let pollCount = 0
      analyzePollRef.current = setInterval(async () => {
        pollCount++
        try {
          const done = await fetchAndApplyProfile()
          if (done) {
            unsub()
            if (analyzePollRef.current) {
              clearInterval(analyzePollRef.current)
              analyzePollRef.current = null
            }
          } else if (pollCount > 90) {
            // Timeout after ~3 minutes
            unsub()
            setAnalyzeStatus('分析超时，AI 可能仍在运行，请稍后刷新查看。')
            setAnalyzing(false)
            if (analyzePollRef.current) {
              clearInterval(analyzePollRef.current)
              analyzePollRef.current = null
            }
          }
        } catch {
          // keep polling
        }
      }, 2000)
    } catch (err) {
      setAnalyzeStatus('启动 AI 分析失败: ' + (err as Error).message)
      setAnalyzing(false)
    }
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (analyzePollRef.current) {
        clearInterval(analyzePollRef.current)
      }
    }
  }, [])

  // Auto-fill templates based on platform type
  const handleAutoFill = (type: string) => {
    const baseUrl = platformUrl.replace(/\/$/, '') || 'https://platform.example.com'
    const templates: Record<string, Partial<PlatformProfile>> = {
      ctfd: {
        platform_type: 'ctfd',
        get_challenges: `GET ${baseUrl}/api/v1/challenges — 获取题目列表\nGET ${baseUrl}/api/v1/challenges/{id} — 获取题目详情、描述、附件\n认证: Authorization: Token {api_token} 或 Cookie 中带 session`,
        get_instance: `GET ${baseUrl}/api/v1/plugins/ctfd-whale/container?challenge_id={id} — 查询容器状态\n返回 JSON，包含 url / instance / address 等字段`,
        start_instance: `POST ${baseUrl}/api/v1/plugins/ctfd-whale/container?challenge_id={id} — 启动靶机\n返回容器地址，可能需 2-3 秒后 GET 查询地址`,
        stop_instance: `DELETE ${baseUrl}/api/v1/plugins/ctfd-whale/container?challenge_id={id} — 关闭靶机`,
        renew_instance: `PATCH ${baseUrl}/api/v1/plugins/ctfd-whale/container?challenge_id={id} — 续期靶机`,
        submit_flag: `POST ${baseUrl}/api/v1/challenges/attempt\nBody: {"challenge_id": {id(int)}, "submission": "{flag}"}\nHeader: Content-Type: application/json\n返回 data.status: correct/incorrect/already_solved`,
        notes: '标准 CTFd 平台 (ctf.show 等)。认证方式: Token 或 Cookie+CSRF Nonce。',
      },
      gzctf: {
        platform_type: 'gzctf',
        get_challenges: `GET ${baseUrl}/api/game/{game_id}/challenges — 获取题目列表\nGET ${baseUrl}/api/game/{game_id}/challenges/{id} — 获取题目详情\n认证: Cookie`,
        get_instance: `GET ${baseUrl}/api/game/{game_id}/container/{id} — 查询容器状态`,
        start_instance: `POST ${baseUrl}/api/game/{game_id}/container/{id} — 启动靶机`,
        stop_instance: `DELETE ${baseUrl}/api/game/{game_id}/container/{id} — 关闭靶机`,
        renew_instance: `PUT ${baseUrl}/api/game/{game_id}/container/{id} — 续期靶机`,
        submit_flag: `POST ${baseUrl}/api/game/{game_id}/challenges/{id}\nBody: {"flag": "{flag}"}\nHeader: Content-Type: application/json`,
        notes: 'GZCTF 平台。需要 game_id (可从比赛 URL 中提取)。',
      },
    }
    if (templates[type]) {
      setProfile((prev) => ({ ...prev, ...templates[type] }))
    }
  }

  const fieldConfig = [
    { key: 'get_challenges', label: '获取题目信息', placeholder: '描述如何获取题目列表和详情的 API 格式...\n如: GET /api/v1/challenges\n认证方式: Token / Cookie' },
    { key: 'get_instance', label: '获取靶机状态', placeholder: '描述如何查询容器/靶机状态...\n如: GET /api/v1/plugins/ctfd-whale/container?challenge_id={id}' },
    { key: 'start_instance', label: '开启靶机', placeholder: '描述如何启动一个容器/靶机...\n如: POST /api/v1/plugins/ctfd-whale/container?challenge_id={id}' },
    { key: 'stop_instance', label: '关闭靶机', placeholder: '描述如何关闭/销毁一个容器/靶机...\n如: DELETE /api/v1/plugins/ctfd-whale/container?challenge_id={id}' },
    { key: 'renew_instance', label: '续期靶机', placeholder: '描述如何续期/延长靶机生命周期...\n如: PATCH ...' },
    { key: 'submit_flag', label: '提交 Flag', placeholder: '描述如何提交 Flag...\n如: POST /api/v1/challenges/attempt\nBody: {"challenge_id": 123, "submission": "flag{...}"}' },
  ] as const

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div className="panel w-full max-w-2xl p-8 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-primary-500" />
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="panel-header justify-between flex-shrink-0">
          <span className="flex items-center gap-2">
            <Waypoints className="w-4 h-4 text-amber-500" />
            解析平台格式
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          <p className="text-sm text-gray-500">
            配置该平台的 API 格式，AI 在解题时会根据这些信息正确地获取题目、开关靶机、提交 Flag。
          </p>

          {/* Platform type selector with auto-fill */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">平台类型</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={profile.platform_type}
                onChange={(e) => setProfile({ ...profile, platform_type: e.target.value })}
                className="input-field flex-1"
                placeholder="ctfd / gzctf / custom"
              />
              <button
                onClick={() => handleAutoFill('ctfd')}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors whitespace-nowrap"
              >
                CTFd 模板
              </button>
              <button
                onClick={() => handleAutoFill('gzctf')}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-green-50 text-green-600 hover:bg-green-100 transition-colors whitespace-nowrap"
              >
                GZCTF 模板
              </button>
              <button
                onClick={() => setProfile({ platform_type: '', get_challenges: '', get_instance: '', start_instance: '', stop_instance: '', renew_instance: '', submit_flag: '', notes: '' })}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors whitespace-nowrap"
              >
                清空
              </button>
            </div>
          </div>

          {/* AI Auto-analyze */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleAIAnalyze}
              disabled={analyzing || !platformUrl}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {analyzing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              {analyzing ? 'AI 分析中...' : 'AI 自动分析'}
            </button>
            {analyzeStatus && (
              <span className={`text-xs ${analyzing ? 'text-purple-600' : analyzeStatus.includes('完成') ? 'text-green-600' : analyzeStatus.includes('失败') || analyzeStatus.includes('超时') ? 'text-red-500' : 'text-gray-500'}`}>
                {analyzeStatus}
              </span>
            )}
            {!platformUrl && (
              <span className="text-xs text-red-400">需要先设置平台地址</span>
            )}
          </div>

          {/* API fields */}
          {fieldConfig.map(({ key, label, placeholder }) => (
            <div key={key}>
              <label className="block text-xs text-gray-500 mb-1">{label}</label>
              <textarea
                value={(profile as any)[key] || ''}
                onChange={(e) => setProfile({ ...profile, [key]: e.target.value })}
                className="input-field w-full resize-none text-xs font-mono"
                rows={3}
                placeholder={placeholder}
              />
            </div>
          ))}

          {/* Notes */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">附加说明</label>
            <textarea
              value={profile.notes}
              onChange={(e) => setProfile({ ...profile, notes: e.target.value })}
              className="input-field w-full resize-none text-xs"
              rows={2}
              placeholder="其他需要 AI 注意的平台特殊情况..."
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-surface-border flex-shrink-0">
          <button onClick={onClose} className="btn-secondary">取消</button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary flex items-center gap-2"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
