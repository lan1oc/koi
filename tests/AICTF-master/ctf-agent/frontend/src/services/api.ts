import type {
  Challenge,
  ChallengeFilter,
  Competition,
  CompetitionFilter,
  PlatformProfile,
  ParseJob,
  Session,
  Message,
  Skill,
  Writeup,
  Provider,
  APIResponse,
  MCPServer,
  MCPImportResult,
  AgentInfo,
  Idea,
  PipelineState,
  PipelineConfig,
  PromptEntry,
} from '../types'

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `HTTP ${res.status}`)
  }
  return res.json()
}

// ─── Challenges ───
export const challengeApi = {
  list(filter?: ChallengeFilter) {
    const params = new URLSearchParams()
    if (filter?.competition_id) params.set('competition_id', filter.competition_id)
    if (filter?.category) params.set('category', filter.category)
    if (filter?.status) params.set('status', filter.status)
    if (filter?.platform) params.set('platform', filter.platform)
    if (filter?.search) params.set('search', filter.search)
    if (filter?.limit) params.set('limit', String(filter.limit))
    if (filter?.offset) params.set('offset', String(filter.offset))
    const qs = params.toString()
    return request<Challenge[]>(`/challenges${qs ? `?${qs}` : ''}`)
  },

  /** Paginated list - returns { items, total } */
  listPaginated(filter?: ChallengeFilter) {
    const params = new URLSearchParams()
    if (filter?.competition_id) params.set('competition_id', filter.competition_id)
    if (filter?.category) params.set('category', filter.category)
    if (filter?.status) params.set('status', filter.status)
    if (filter?.platform) params.set('platform', filter.platform)
    if (filter?.search) params.set('search', filter.search)
    params.set('limit', String(filter?.limit || 24))
    params.set('offset', String(filter?.offset || 0))
    const qs = params.toString()
    return request<{ items: Challenge[]; total: number }>(`/challenges?${qs}`)
  },

  get(id: string) {
    return request<Challenge>(`/challenges/${id}`)
  },

  create(data: Partial<Challenge>) {
    return request<Challenge>('/challenges', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  update(id: string, data: Partial<Challenge>) {
    return request<Challenge>(`/challenges/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  delete(id: string) {
    return request<void>(`/challenges/${id}`, { method: 'DELETE' })
  },

  upload(id: string, files: FileList) {
    const formData = new FormData()
    for (let i = 0; i < files.length; i++) {
      formData.append('files', files[i])
    }
    return fetch(`${BASE}/challenges/${id}/upload`, {
      method: 'POST',
      body: formData,
    }).then(r => r.json())
  },

  updateStatus(id: string, status: string, flag?: string) {
    return request<Challenge>(`/challenges/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, ...(flag ? { flag } : {}) }),
    })
  },

  getWriteup(id: string) {
    return request<{ writeup: string }>(`/challenges/${id}/writeup`)
  },

  getPromptPreview(id: string) {
    return request<{ prompt: string }>(`/challenges/${id}/prompt-preview`)
  },

  generateWriteup(id: string, model?: string) {
    return request<{ status: string; session_id: string }>(`/challenges/${id}/generate-writeup`, {
      method: 'POST',
      body: JSON.stringify({ model }),
    })
  },

  generateReflection(id: string) {
    return request<{ status: string; session_id: string }>(`/challenges/${id}/generate-reflection`, {
      method: 'POST',
    })
  },

  getProgressReport(id: string) {
    return request<{ content: string; exists: boolean }>(`/challenges/${id}/progress-report`)
  },

  getKeyFindings(id: string) {
    return request<{
      key_findings: string[]
      flag_candidates: string[]
      milestones: Array<{
        round: number
        type: string
        action: string
        tool_name: string
        result: string
        time: string
      }>
    }>(`/challenges/${id}/key-findings`)
  },
}

// ─── Competitions ───
export const competitionApi = {
  list(filter?: CompetitionFilter) {
    const params = new URLSearchParams()
    if (filter?.status) params.set('status', filter.status)
    if (filter?.search) params.set('search', filter.search)
    if (filter?.limit) params.set('limit', String(filter.limit))
    if (filter?.offset) params.set('offset', String(filter.offset))
    const qs = params.toString()
    return request<Competition[]>(`/competitions${qs ? `?${qs}` : ''}`)
  },

  get(id: string) {
    return request<Competition>(`/competitions/${id}`)
  },

  getRaw(id: string) {
    return request<Competition>(`/competitions/${id}/raw`)
  },

  create(data: Partial<Competition>) {
    return request<Competition>('/competitions', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  update(id: string, data: Partial<Competition>) {
    return request<Competition>(`/competitions/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  delete(id: string) {
    return request<void>(`/competitions/${id}`, { method: 'DELETE' })
  },

  challenges(id: string, filter?: ChallengeFilter) {
    const params = new URLSearchParams()
    if (filter?.category) params.set('category', filter.category)
    if (filter?.status) params.set('status', filter.status)
    if (filter?.search) params.set('search', filter.search)
    const qs = params.toString()
    return request<Challenge[]>(`/competitions/${id}/challenges${qs ? `?${qs}` : ''}`)
  },

  parse(id: string, model?: string, instruction?: string) {
    return request<{ job_id: string; session_id: string; agent_id: string; status: string }>(`/competitions/${id}/parse`, {
      method: 'POST',
      body: JSON.stringify({ model, instruction }),
    })
  },

  parseStatus(competitionId: string, jobId: string) {
    return request<ParseJob>(`/competitions/${competitionId}/parse-status/${jobId}`)
  },

  getPlatformProfile(id: string) {
    return request<{ platform_profile: PlatformProfile | null }>(`/competitions/${id}/platform-profile`)
  },

  setPlatformProfile(id: string, profile: PlatformProfile) {
    return request<{ ok: boolean }>(`/competitions/${id}/platform-profile`, {
      method: 'PUT',
      body: JSON.stringify({ platform_profile: profile }),
    })
  },

  analyzePlatform(id: string, model?: string) {
    return request<{ session_id: string; status: string }>(`/competitions/${id}/analyze-platform`, {
      method: 'POST',
      body: JSON.stringify({ model }),
    })
  },
}

// ─── Ideas ───
export const ideasApi = {
  list(challengeId: string) {
    return request<Idea[]>(`/challenges/${challengeId}/ideas`)
  },

  create(challengeId: string, content: string) {
    return request<Idea>(`/challenges/${challengeId}/ideas`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    })
  },

  update(ideaId: string, status: string, result?: string) {
    return request<{ ok: boolean }>(`/ideas/${ideaId}`, {
      method: 'PUT',
      body: JSON.stringify({ status, result: result || '' }),
    })
  },

  delete(ideaId: string) {
    return request<{ ok: boolean }>(`/ideas/${ideaId}`, { method: 'DELETE' })
  },

  clearAll(challengeId: string) {
    return request<{ ok: boolean }>(`/challenges/${challengeId}/ideas`, { method: 'DELETE' })
  },

  search(challengeId: string, query: string) {
    return request<Idea[]>(`/challenges/${challengeId}/ideas/search?q=${encodeURIComponent(query)}`)
  },
}

// ─── Sessions ───
export const sessionApi = {
  create(challengeId: string, model?: string) {
    return request<Session>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ challenge_id: challengeId, model }),
    })
  },

  get(id: string) {
    return request<Session>(`/sessions/${id}`)
  },

  messages(id: string) {
    return request<Message[]>(`/sessions/${id}/messages`)
  },

  allMessages(id: string) {
    return request<Message[]>(`/sessions/${id}/all-messages`)
  },

  exportChatUrl(id: string) {
    return `${BASE}/sessions/${id}/export-chat`
  },

  branch(id: string, messageIndex: number) {
    return request<Session>(`/sessions/${id}/branch`, {
      method: 'POST',
      body: JSON.stringify({ message_index: messageIndex }),
    })
  },

  createTerminal(sessionId: string) {
    return request<{ terminal_id: string }>(`/sessions/${sessionId}/terminal`, {
      method: 'POST',
    })
  },

  getByChallenge(challengeId: string) {
    return request<Session>(`/challenge-session/${challengeId}`)
  },

  delete(id: string) {
    return request<{ ok: boolean }>(`/sessions/${id}`, {
      method: 'DELETE',
    })
  },
}

// ─── Agent ───
export const agentApi = {
  solve(challengeId: string, sessionId?: string, model?: string, utilityModel?: string, interactive?: boolean) {
    return request<{ agent_id: string; session_id: string }>('/agent/solve', {
      method: 'POST',
      body: JSON.stringify({
        challenge_id: challengeId,
        session_id: sessionId,
        model,
        utility_model: utilityModel || undefined,
        interactive: interactive || false,
      }),
    })
  },

  continue(sessionId: string, model?: string, message?: string, utilityModel?: string, interactive?: boolean) {
    return request<{ agent_id: string; session_id: string }>('/agent/continue', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        model,
        message,
        utility_model: utilityModel || undefined,
        interactive: interactive || false,
      }),
    })
  },

  stop(agentId: string) {
    return request<APIResponse>(`/agent/stop/${encodeURIComponent(agentId)}`, {
      method: 'POST',
    })
  },

  confirmFlag(sessionId: string, confirmation: 'correct' | 'wrong', flag: string) {
    return request<{ ok: boolean; confirmation: string }>('/agent/flag-confirm', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        confirmation,
        flag,
      }),
    })
  },

  persistentSolve(challengeId: string, model?: string, utilityModel?: string) {
    return request<{ status: string; challenge_id: string }>('/agent/persistent-solve', {
      method: 'POST',
      body: JSON.stringify({
        challenge_id: challengeId,
        model,
        utility_model: utilityModel || undefined,
      }),
    })
  },

  persistentStop(challengeId: string) {
    return request<{ status: string }>(`/agent/persistent-stop/${encodeURIComponent(challengeId)}`, {
      method: 'POST',
    })
  },

  status() {
    return request<AgentInfo[]>('/agent/status')
  },

  sendChat(sessionId: string, content: string) {
    return request<{ ok: boolean }>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, content }),
    })
  },

  respondToQuestion(sessionId: string, answer: string) {
    return request<{ ok: boolean; answer: string }>('/agent/ask-user-respond', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, answer }),
    })
  },
}

// ─── Pipeline ───
export const pipelineApi = {
  start(challengeIds: string[], model?: string, config?: Partial<PipelineConfig>) {
    return request<{ pipeline_id: string; total: number }>('/pipeline/start', {
      method: 'POST',
      body: JSON.stringify({ challenge_ids: challengeIds, model, config }),
    })
  },

  stop(pipelineId: string) {
    return request<APIResponse>(`/pipeline/stop/${encodeURIComponent(pipelineId)}`, {
      method: 'POST',
    })
  },

  status() {
    return request<PipelineState[]>('/pipeline/status')
  },
}

// ─── Arena (Model Competition) ───
export const arenaApi = {
  start(challengeId: string, modelA: string, modelB: string, utilityModel?: string) {
    return request<{ arena_id: string; challenge_id: string; models: [string, string] }>('/arena/start', {
      method: 'POST',
      body: JSON.stringify({ challenge_id: challengeId, model_a: modelA, model_b: modelB, utility_model: utilityModel }),
    })
  },

  stop(arenaId: string) {
    return request<APIResponse>(`/arena/stop/${encodeURIComponent(arenaId)}`, {
      method: 'POST',
    })
  },

  status() {
    return request<import('../types').ArenaState[]>('/arena/status')
  },
}

// ─── NSSCTF Agent Arena (Agent CTF mode) ───
export const nssArenaApi = {
  start(opts: { token?: string; model?: string; utilityModel?: string; baseUrl?: string; maxProblems?: number }) {
    return request<{ arena_id: string; status: string }>('/nssctf/arena/start', {
      method: 'POST',
      body: JSON.stringify({
        token: opts.token || undefined,
        model: opts.model || undefined,
        utility_model: opts.utilityModel || undefined,
        base_url: opts.baseUrl || undefined,
        max_problems: opts.maxProblems || 0,
      }),
    })
  },

  stop() {
    return request<{ status: string }>('/nssctf/arena/stop', { method: 'POST' })
  },

  status() {
    return request<{ running: boolean; arena: import('../types').NSSArenaState | null }>('/nssctf/arena/status')
  },
}

// ─── Knowledge ───
export const knowledgeApi = {
  list(category?: string) {
    const qs = category ? `?category=${category}` : ''
    return request<Writeup[]>(`/knowledge${qs}`)
  },

  search(query: string) {
    return request<Writeup[]>(`/knowledge/search?q=${encodeURIComponent(query)}`)
  },

  get(id: string) {
    return request<Writeup>(`/knowledge/${encodeURIComponent(id)}`)
  },
}

// ─── Skills ───
export const skillApi = {
  list() {
    return request<Skill[]>('/skills')
  },

  content(name: string) {
    return request<{ content: string }>(`/skills/${encodeURIComponent(name)}/content`)
  },

  reload() {
    return request<{ message: string; count: number }>('/skills/reload', { method: 'POST' })
  },

  syncFromTips() {
    return request<{ synced: number; skipped: number; files: string[] }>('/tips/sync-to-skills', { method: 'POST' })
  },

  create(data: { category: string; file_name: string; content: string }) {
    return request<Skill>('/skills', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  update(name: string, content: string) {
    return request<Skill>(`/skills/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    })
  },

  delete(name: string) {
    return request<{ status: string }>(`/skills/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
  },
}

// ─── Providers ───
export const providerApi = {
  list() {
    return request<Provider[]>('/providers')
  },

  add(data: {
    name: string
    type: string
    base_url: string
    api_key: string
    model: string
    max_context_len?: number
    websocket_mode?: boolean
  }) {
    return request<Provider>('/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  update(name: string, data: {
    type?: string
    base_url?: string
    api_key?: string
    model?: string
    max_context_len?: number
    websocket_mode?: boolean
  }) {
    return request<Provider>(`/providers/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  remove(name: string) {
    return request<void>(`/providers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
  },
}

// ─── Config ───
export const configApi = {
  get() {
    return request<Record<string, unknown>>('/config')
  },

  updateWorkDir(workDir: string) {
    return request<{ ok: boolean; work_dir: string }>('/config/workdir', {
      method: 'PUT',
      body: JSON.stringify({ work_dir: workDir }),
    })
  },

  updateToolDir(toolDir: string) {
    return request<{ ok: boolean; tool_dir: string }>('/config/tooldir', {
      method: 'PUT',
      body: JSON.stringify({ tool_dir: toolDir }),
    })
  },

  getVisionConfig() {
    return request<{
      provider_type: string
      base_url: string
      model: string
      max_tokens: number
      has_api_key: boolean
    }>('/config/vision')
  },

  updateVisionConfig(data: {
    provider_type: string
    base_url: string
    api_key?: string
    model: string
    max_tokens: number
  }) {
    return request<{
      ok: boolean
      provider_type: string
      base_url: string
      model: string
      max_tokens: number
      has_api_key: boolean
    }>('/config/vision', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  testVisionConfig() {
    return request<{ ok: boolean; result?: string; error?: string }>('/config/vision/test', {
      method: 'POST',
    })
  },

  updateDefaultModel(data: { selected_model: string; utility_model: string }) {
    return request<{ ok: boolean; selected_model: string; utility_model: string }>('/config/default-model', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  updateAgentConfig(data: {
    max_tool_rounds?: number
    compaction_threshold?: number
    compaction_interval?: number
    keep_recent_rounds?: number
  }) {
    return request<{
      ok: boolean
      max_tool_rounds: number
      compaction_threshold: number
      compaction_interval: number
      keep_recent_rounds: number
    }>('/config/agent', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  getEmbeddingConfig() {
    return request<{
      enabled: boolean
      base_url: string
      model: string
      dimensions: number
      timeout: number
      backfill: boolean
      has_api_key: boolean
    }>('/config/embedding')
  },

  updateEmbeddingConfig(data: {
    enabled?: boolean
    base_url?: string
    model?: string
    api_key?: string
    dimensions?: number
    timeout?: number
    backfill?: boolean
  }) {
    return request<{
      ok: boolean
      enabled: boolean
      base_url: string
      model: string
      dimensions: number
      timeout: number
      backfill: boolean
      has_api_key: boolean
    }>('/config/embedding', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
}

// ─── Desktop Bootstrap (onboarding) ───
export const bootstrapApi = {
  get() {
    return request<{ ok: boolean; exists: boolean; bootstrap_path: string; data_root: string; step: number; completed: boolean }>('/bootstrap')
  },

  update(data: { data_root?: string; step?: number; completed?: boolean }) {
    return request<{ ok: boolean; restart_required: boolean; bootstrap: { data_root: string; step: number; completed: boolean } }>('/bootstrap', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
}

// ─── Prompts ───
export const promptApi = {
  list() {
    return request<PromptEntry[]>('/prompts')
  },

  get(id: string) {
    return request<PromptEntry>(`/prompts/${encodeURIComponent(id)}`)
  },

  update(id: string, content: string) {
    return request<{ ok: boolean }>(`/prompts/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    })
  },

  reset(id: string) {
    return request<{ ok: boolean }>(`/prompts/${encodeURIComponent(id)}/reset`, {
      method: 'POST',
    })
  },
}

// ─── Tips (categorized experience library) ───
export const tipsApi = {
  list() {
    return request<import('../types').TipCategory[]>('/tips')
  },

  get(category: string) {
    return request<{ category: string; content: string }>(`/tips/${encodeURIComponent(category)}`)
  },

  update(category: string, content: string) {
    return request<{ ok: boolean }>(`/tips/${encodeURIComponent(category)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    })
  },

  create(category: string, content: string) {
    return request<{ ok: boolean }>('/tips', {
      method: 'POST',
      body: JSON.stringify({ category, content }),
    })
  },

  delete(category: string) {
    return request<void>(`/tips/${encodeURIComponent(category)}`, { method: 'DELETE' })
  },

  embeddingStats() {
    return request<{ total: number; embedded: number; has_embedder: boolean; model: string; enabled: boolean }>('/tips/embedding-stats')
  },

  backfillEmbeddings() {
    return request<{ updated: number; total: number; embedded: number }>('/tips/backfill-embeddings', {
      method: 'POST',
    })
  },
}

// ─── MCP Servers ───
export const mcpApi = {
  list() {
    return request<MCPServer[]>('/mcp/servers')
  },

  add(server: MCPServer) {
    return request<MCPServer>('/mcp/servers', {
      method: 'POST',
      body: JSON.stringify(server),
    })
  },

  remove(name: string) {
    return request<void>(`/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
  },

  test(name: string) {
    return request<{ status: string; tools?: string[]; error?: string }>(
      `/mcp/servers/${encodeURIComponent(name)}/test`,
      { method: 'POST' }
    )
  },

  update(name: string, server: Partial<MCPServer>) {
    return request<MCPServer>(`/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(server),
    })
  },

  connect(name: string) {
    return request<{ status: string; tools?: string[]; error?: string }>(
      `/mcp/servers/${encodeURIComponent(name)}/connect`,
      { method: 'POST' }
    )
  },

  disconnect(name: string) {
    return request<{ status: string }>(
      `/mcp/servers/${encodeURIComponent(name)}/disconnect`,
      { method: 'POST' }
    )
  },

  import(json: string) {
    return request<MCPImportResult[]>('/mcp/servers/import', {
      method: 'POST',
      body: json,
    })
  },
}

// ─── Memories ───
export interface Memory {
  id: string
  category: string
  content: string
  tags?: string[]
  source: string
  created_at: string
  updated_at: string
}

export const memoriesApi = {
  list() {
    return request<Memory[]>('/memories')
  },

  get(id: string) {
    return request<Memory>(`/memories/${encodeURIComponent(id)}`)
  },

  update(id: string, content: string) {
    return request<Memory>(`/memories/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    })
  },

  delete(id: string) {
    return request<{ ok: boolean }>(`/memories/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
  },

  embeddingStats() {
    return request<{
      total: number
      embedded: number
      has_embedder: boolean
      model: string
      enabled: boolean
    }>('/memories/embedding-stats')
  },

  backfillEmbeddings() {
    return request<{
      updated: number
      total: number
      embedded: number
    }>('/memories/backfill-embeddings', { method: 'POST' })
  },
}

// ─── Tags Management ───
export interface TagStats {
  knowledge: { total: number; tagged: number; unique_tags: number }
  tips: { total: number; tagged: number; unique_tags: number }
  memories: { total: number; tagged: number; unique_tags: number }
}

export interface AutoTagProgress {
  total: number
  done: number
  failed: number
  running: boolean
  message: string
}

export interface TipItem {
  id: number
  category: string
  content: string
  tags: string[]
  source: string
  hit_count: number
  created_at: string
  updated_at: string
}

export const tagsApi = {
  stats() {
    return request<TagStats>('/tags/stats')
  },

  listAll() {
    return request<Record<string, { count: number; sources: string[] }>>('/tags/list')
  },

  autoTagKnowledge(onlyUntagged = true, model?: string) {
    const params = new URLSearchParams({ only_untagged: String(onlyUntagged) })
    if (model) params.set('model', model)
    return request<{ message: string; total: number }>(`/tags/knowledge/auto-tag?${params}`, {
      method: 'POST',
    })
  },

  autoTagTips(onlyUntagged = true, model?: string) {
    const params = new URLSearchParams({ only_untagged: String(onlyUntagged) })
    if (model) params.set('model', model)
    return request<{ message: string }>(`/tags/tips/auto-tag?${params}`, { method: 'POST' })
  },

  autoTagMemories(onlyUntagged = true, model?: string) {
    const params = new URLSearchParams({ only_untagged: String(onlyUntagged) })
    if (model) params.set('model', model)
    return request<{ message: string; total: number }>(`/tags/memories/auto-tag?${params}`, {
      method: 'POST',
    })
  },

  progress(target: 'knowledge' | 'tips' | 'memories') {
    return request<AutoTagProgress>(`/tags/progress/${target}`)
  },

  updateKnowledgeTags(id: string, tags: string[]) {
    return request<{ ok: boolean; tags: string[] }>(`/knowledge/${encodeURIComponent(id)}/tags`, {
      method: 'PUT',
      body: JSON.stringify({ tags }),
    })
  },

  updateMemoryTags(id: string, tags: string[]) {
    return request<{ ok: boolean; tags: string[] }>(`/memories/${encodeURIComponent(id)}/tags`, {
      method: 'PUT',
      body: JSON.stringify({ tags }),
    })
  },

  listTipItems() {
    return request<TipItem[]>('/tip-items')
  },

  updateTipItemTags(id: number, tags: string[]) {
    return request<{ ok: boolean; tags: string[] }>(`/tip-items/${id}/tags`, {
      method: 'PUT',
      body: JSON.stringify({ tags }),
    })
  },
}

// ─── Solve Stats ───
export const solveStatsApi = {
  list(limit = 50) {
    return request<{ items: import('../types').SolveRecord[]; total: number }>(
      `/solve-stats?limit=${limit}`
    )
  },
}

// ─── Inspection ───
export const inspectionApi = {
  // Modules
  listModules() {
    return request<import('../types').InspectionModule[]>('/inspection/modules')
  },

  // Hosts
  listHosts() {
    return request<import('../types').InspectionHost[]>('/inspection/hosts')
  },
  createHost(data: { name: string; host: string; port?: number; username: string; password: string; auth_method?: string }) {
    return request<import('../types').InspectionHost>('/inspection/hosts', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
  getHost(id: string) {
    return request<import('../types').InspectionHost>(`/inspection/hosts/${id}`)
  },
  deleteHost(id: string) {
    return request<{ status: string }>(`/inspection/hosts/${id}`, { method: 'DELETE' })
  },

  // Test connection
  testConnection(data: { host: string; port?: number; username: string; password: string }) {
    return request<{ success: boolean; error?: string; message?: string }>('/inspection/test-connection', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  // Start inspection
  startInspection(hostId: string, data: { password: string; modules?: string[] }) {
    return request<{ run_id: string; host_id: string; status: string; modules: string[] }>(
      `/inspection/hosts/${hostId}/start`,
      { method: 'POST', body: JSON.stringify(data) }
    )
  },

  // Runs
  listRuns(hostId: string) {
    return request<import('../types').InspectionRun[]>(`/inspection/hosts/${hostId}/runs`)
  },

  // Results
  listResults(runId: string) {
    return request<import('../types').InspectionResult[]>(`/inspection/runs/${runId}/results`)
  },

  // Export
  exportReport(runId: string, format: 'markdown' | 'html' | 'json' = 'markdown') {
    return `${BASE}/inspection/runs/${runId}/export?format=${format}`
  },
}

// ─── Reverse Engineering Lab ───
export const reverseApi = {
  upload(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return fetch(`${BASE}/reverse/upload`, {
      method: 'POST',
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      return res.json() as Promise<import('../types').ReverseBinary>
    })
  },

  list(search?: string) {
    const qs = search ? `?search=${encodeURIComponent(search)}` : ''
    return request<import('../types').ReverseBinary[]>(`/reverse/binaries${qs}`)
  },

  get(id: string) {
    return request<import('../types').ReverseBinary>(`/reverse/binaries/${id}`)
  },

  delete(id: string) {
    return request<{ status: string }>(`/reverse/binaries/${id}`, { method: 'DELETE' })
  },

  analyze(id: string) {
    return request<import('../types').ReverseBinary>(`/reverse/binaries/${id}/analyze`, { method: 'POST' })
  },

  getStrings(id: string, opts?: { min_len?: number; encoding?: string }) {
    const params = new URLSearchParams()
    if (opts?.min_len) params.set('min_len', String(opts.min_len))
    if (opts?.encoding) params.set('encoding', opts.encoding)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request<import('../types').StringsResult>(`/reverse/binaries/${id}/strings${qs}`)
  },

  decompile(id: string, functionName?: string) {
    return request<import('../types').DecompileTask>(`/reverse/binaries/${id}/decompile`, {
      method: 'POST',
      body: JSON.stringify({ function: functionName }),
    })
  },

  getDecompileResult(id: string, taskId: string) {
    return request<import('../types').DecompileTask>(`/reverse/binaries/${id}/decompile/${taskId}`)
  },

  createTerminal(id: string) {
    return request<{ terminal_id: string; session_id: string }>(`/reverse/binaries/${id}/terminal`, {
      method: 'POST',
    })
  },

  aiAnalyze(id: string, data?: { message?: string; model?: string }) {
    return request<{ session_id: string; agent_id: string; binary_id: string }>(
      `/reverse/binaries/${id}/ai-analyze`,
      { method: 'POST', body: JSON.stringify(data || {}) }
    )
  },

  getAlgorithms() {
    return request<import('../types').AlgorithmSignature[]>('/reverse/algorithms')
  },
}
