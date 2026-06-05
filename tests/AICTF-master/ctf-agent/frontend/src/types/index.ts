// ─── Competition ───
export type CompetitionStatus = 'active' | 'archived' | 'importing'

export interface Competition {
  id: string
  name: string
  platform: string
  url: string
  credentials: string
  status: CompetitionStatus
  description: string
  platform_profile?: PlatformProfile | null
  start_time?: string
  end_time?: string
  created_at: string
  updated_at: string
  challenge_count: number
  solved_count: number
}

// PlatformProfile describes how the AI agent should interact with a CTF platform's API
export interface PlatformProfile {
  platform_type: string    // e.g. ctfd, gzctf, custom
  get_challenges: string   // how to list/get challenges
  get_instance: string     // how to query instance status
  start_instance: string   // how to start a container/靶机
  stop_instance: string    // how to stop a container
  renew_instance: string   // how to renew/extend instance
  submit_flag: string      // how to submit a flag
  notes: string            // additional notes
}

export interface CompetitionFilter {
  status?: CompetitionStatus
  search?: string
  limit?: number
  offset?: number
}

export interface ParseJob {
  id: string
  competition_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  total_found: number
  total_imported: number
  error: string
  started_at?: string
  completed_at?: string
}

// ─── Challenge ───
// Dynamic category - any string is valid; common ones: web, pwn, reverse, crypto, misc, forensics, blockchain, osint, ppc, etc.
export type ChallengeCategory = string
export type ChallengeStatus = 'unsolved' | 'in_progress' | 'solved' | 'failed'

export interface Challenge {
  id: string
  competition_id: string
  external_id?: string
  title: string
  category: ChallengeCategory
  platform: string
  url: string
  instance_url?: string
  description: string
  attachments: string[]
  flag: string
  writeup?: string
  points?: number
  status: ChallengeStatus
  created_at: string
  solved_at?: string
}

export interface ChallengeFilter {
  competition_id?: string
  category?: ChallengeCategory
  status?: ChallengeStatus
  platform?: string
  search?: string
  limit?: number
  offset?: number
}

// ─── Desktop Bootstrap / Onboarding ───
export interface BootstrapInfo {
  ok: boolean
  exists: boolean
  bootstrap_path: string
  data_root: string
  step: number
  completed: boolean
}

// ─── Session ───
export type SessionStatus = 'active' | 'paused' | 'completed' | 'failed'

export interface Session {
  id: string
  challenge_id: string
  agent_id: string
  status: SessionStatus
  model: string
  parent_id?: string
  branch_point?: number
  created_at: string
}

// ─── Message ───
export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export interface ToolCall {
  id: string
  name: string
  arguments: string
}

export interface Message {
  role: MessageRole
  content: string
  thinking?: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  name?: string
  timestamp: string
}

// ─── WebSocket Events ───
export type WSEventType =
  | 'agent_start'
  | 'agent_end'
  | 'round_start'
  | 'content_delta'
  | 'message_delta'
  | 'thinking_delta'
  | 'tool_call_start'
  | 'tool_call_delta'
  | 'tool_call_end'
  | 'tool_output'
  | 'flag_found'
  | 'flag_manual'
  | 'agent_waiting_flag_confirm'
  | 'error'
  | 'compaction'
  | 'sub_agent_spawn'
  | 'sub_agent_complete'
  | 'sub_agent_progress'
  | 'parse_complete'
  | 'challenge_imported'
  | 'writeup_generating'
  | 'writeup_generated'
  | 'lessons_extracting'
  | 'lessons_extracted'
  | 'user_message'
  | 'pipeline_start'
  | 'pipeline_end'
  | 'pipeline_stopped'
  | 'pipeline_challenge_start'
  | 'pipeline_challenge_end'
  | 'pipeline_challenge_skip'
  | 'todolist_update'
  | 'terminal_output'
  | 'heartbeat'
  | 'persistent_attempt'
  | 'persistent_retry'
  | 'persistent_complete'
  | 'ideas_update'
  | 'idea_agent_result'
  | 'token_usage'
  | 'post_solve_reflection'
  | 'finding_verify_status'
  | 'finding_llm_verify'
  | 'pentest_finding'
  | 'reflection'
  | 'planning_phase'
  | 'checkpoint'
  | 'repetition_warning'
  | 'flag_candidate'
  | 'thinking_overflow_hint'
  | 'arena_start'
  | 'arena_end'
  | 'arena_stopped'
  | 'arena_winner'
  | 'arena_slot_start'
  | 'nss_arena_start'
  | 'nss_arena_attempt_start'
  | 'nss_arena_attempt_end'
  | 'nss_arena_end'
  | 'nss_arena_error'
  | 'ask_user'
  | 'ask_user_responded'

export interface WSEvent {
  type: WSEventType
  agent_id: string
  session_id: string
  content?: string
  tool_call_id?: string
  tool_name?: string
  tool_args?: string | Record<string, unknown>
  tool_output?: string
  is_streaming?: boolean
  success?: boolean
  model?: string
  mode?: string
  agent_type?: string
  flag_found?: string
  error?: string
  data?: Record<string, unknown> | string
  challenge_id?: string
  challenge_title?: string
  // Token usage fields
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

// Interactive Q&A: AI asks user a question with multiple choice options
export interface AskUserQuestion {
  id: string
  question: string
  options: string[]
  context?: string
}

export type TopologyNodeStatus =
  | 'spawned'
  | 'running'
  | 'completed'
  | 'failed'
  | 'timed_out'
  | 'stopped'

export interface SubAgentTopologyEvent {
  parent_agent_id: string
  parent_session_id?: string
  root_session_id?: string
  child_agent_id: string
  child_session_id: string
  bg_id?: string
  agent_type: string
  task?: string
  model?: string
  mode?: string
  status: TopologyNodeStatus
  rounds?: number
  current_tool?: string
  summary?: string
  flag_found?: string
  elapsed?: string
  challenge_id?: string
  challenge_title?: string
}

export interface AgentTopologyNode {
  id: string
  parentId?: string
  sessionId: string
  rootSessionId: string
  challengeId?: string
  challengeTitle?: string
  agentType: string
  model?: string
  status: TopologyNodeStatus
  rounds: number
  currentTool?: string
  summary?: string
  task?: string
  flagFound?: string
  startedAt: number
  updatedAt: number
  isRoot?: boolean
}

export interface AgentTopologyGraph {
  rootSessionId: string
  challengeId?: string
  challengeTitle?: string
  rootAgentId?: string
  updatedAt: number
  nodes: Record<string, AgentTopologyNode>
}

// ─── IdeaAgentResult ───
export interface IdeaAgentResult {
  idea_id: string
  idea_content: string
  status: 'verified' | 'failed'
  summary: string
  flag_found: string
  session_id: string
  elapsed: string
}

// ─── Ideas ───
export interface Idea {
  id: string
  challenge_id: string
  content: string
  status: 'pending' | 'testing' | 'verified' | 'failed' | 'skipped'
  result: string
  created_at: string
  updated_at: string
}

// ─── TodoList ───
export interface TodoItem {
  id: number
  task: string
  status: 'pending' | 'in_progress' | 'done' | 'failed' | 'skipped'
  result?: string
}

// ─── Agent Mode ───
export type AgentMode = 'ctf' | 'audit' | 'pentest' | 'reverse' | 'inspection'

// ─── Agent ───
export type AgentType =
  | 'coordinator' | 'web' | 'pwn' | 'reverse' | 'crypto' | 'misc' | 'parser'
  | 'audit_coordinator' | 'sast' | 'dependency' | 'config_review' | 'logic'
  | 'pentest_coordinator' | 'recon' | 'vuln_scan' | 'exploit' | 'post_exploit'

export interface AgentInfo {
  id: string
  session_id: string
  challenge_id: string
  agent_type: AgentType
  mode: AgentMode
  model: string
  running: boolean
}

// ─── Audit Project ───
export type AuditStatus = 'pending' | 'auditing' | 'completed' | 'failed'
export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export interface AuditProject {
  id: string
  name: string
  source_type: 'local' | 'git' | 'upload'
  source_path: string
  git_url?: string
  language?: string
  framework?: string
  description?: string
  status: AuditStatus
  finding_count?: number
  created_at: string
  updated_at?: string
}

export interface AuditFinding {
  id: string
  project_id: string
  severity: FindingSeverity
  cwe_id?: string
  title: string
  description: string
  location: string
  poc?: string
  remediation?: string
  agent_type?: string
  created_at: string
}

// ─── Pentest Target ───
export type PentestStatus = 'idle' | 'scanning' | 'exploiting' | 'completed' | 'failed'

export interface PentestTarget {
  id: string
  name: string
  description?: string
  target_urls: string[]
  target_ips: string[]
  scope: string[]
  out_of_scope: string[]
  auth_info?: string
  hackerone_handle?: string
  audit_project_ids?: string[]
  status: PentestStatus
  finding_count?: number
  created_at: string
  updated_at?: string
}

export interface PentestFinding {
  id: string
  target_id: string
  vuln_type: string
  severity: FindingSeverity
  title: string
  description: string
  location: string
  payload?: string
  evidence?: string
  attack_chain?: string
  remediation?: string
  exploit_script?: string
  cvss_score?: number
  agent_type?: string
  verify_status?: 'pending' | 'running' | 'success' | 'failed' | 'error' | 'false_positive' | 'duplicate' | 'confirmed' | 'needs_review'
  verify_output?: string
  verified_at?: string
  created_at: string
}

// ─── Skill ───
export interface Skill {
  name: string
  description: string
  category: string
  tools_required: string[]
  file_path: string
}

// ─── Knowledge ───
export interface Writeup {
  id: string
  title: string
  category: string
  tags?: string[]
  content: string
  created_at: string
}

// ─── Provider ───
export type ProviderType = 'openai' | 'anthropic' | 'openai_compat' | 'ollama'

export interface Provider {
  name: string
  type: ProviderType
  base_url: string
  model: string
  max_context_len: number
  has_api_key: boolean
  websocket_mode?: boolean
}

// ─── Pipeline ───
export interface PipelineConfig {
  max_rounds: number            // 0 = use default
  max_time_per_challenge: number // seconds, 0 = no limit
  retry_failed: boolean
  skip_solved: boolean
  max_concurrent: number        // global max concurrent solves (0 = 1, sequential)
  category_concurrency: Record<string, number> // per-category max concurrent
  arena_model_b: string         // if non-empty, enable arena mode with this second model
}

export interface PipelineResult {
  challenge_id: string
  challenge_title: string
  status: 'pending' | 'solving' | 'solved' | 'failed' | 'skipped' | 'timeout'
  flag?: string
  session_id?: string
  duration_ms?: number
  retry?: boolean
}

export interface PipelineState {
  id: string
  challenge_ids: string[]
  model: string
  config: PipelineConfig
  status: 'running' | 'completed' | 'stopped'
  current: number
  total: number
  results: PipelineResult[]
  started_at: string
  completed_at?: string
}

// ─── Arena (Model Competition) ───
export interface ArenaSlot {
  model: string
  session_id: string
  agent_id: string
  status: 'running' | 'won' | 'lost' | 'failed' | 'stopped'
  flag?: string
  duration_ms?: number
}

export interface ArenaState {
  id: string
  challenge_id: string
  models: [string, string]
  sessions: [string, string]
  agent_ids: [string, string]
  status: 'running' | 'completed' | 'stopped'
  winner: string
  winner_idx: number
  flag?: string
  results: [ArenaSlot, ArenaSlot]
  started_at: string
  completed_at?: string
  duration_ms?: number
}

// ─── NSSCTF Agent Arena (Agent CTF mode) ───
export interface NSSArenaCurrent {
  attempt_id: string
  title: string
  category: string
  rating: number
  remaining_seconds: number
  session_id: string
  challenge_id: string
  started_at: number
}

export interface NSSArenaResult {
  attempt_id: string
  title: string
  category: string
  problem_rating: number
  state: string // solved, failed, abandoned, expired, invalid
  flag?: string
  rating_delta: number
  rating_after: number
  session_id: string
  challenge_id: string
  duration_ms: number
  finished_at: number
}

export interface NSSArenaState {
  id: string
  status: 'running' | 'stopped' | 'completed' | 'error'
  model: string
  utility_model: string
  base_url: string
  max_problems: number
  rating: number
  attempt_count: number
  solved_count: number
  failed_count: number
  processed: number
  current?: NSSArenaCurrent | null
  history: NSSArenaResult[]
  error?: string
  started_at: string
  updated_at: string
}

// ─── API Response ───
export interface APIResponse<T = unknown> {
  data?: T
  error?: string
  message?: string
}

// ─── MCP Server ───
export type MCPTransport = 'stdio' | 'sse'
export type MCPServerStatus = 'connected' | 'disconnected' | 'error' | 'connecting'

export interface MCPServer {
  name: string
  transport: MCPTransport
  command?: string
  args?: string[]
  url?: string
  env?: Record<string, string>
  status?: MCPServerStatus
  tools?: string[]
  error?: string
}

export interface MCPImportResult {
  name: string
  status: MCPServerStatus
  tools?: string[]
  error?: string
}

// ─── Prompt Entry ───
export interface PromptEntry {
  id: string
  content: string
  is_customized: boolean
  default_content: string
  updated_at?: string
}

// ─── Tip Category ───
export interface TipCategory {
  category: string
  content: string
  updated_at?: string
}

// ─── Tool Execution Display ───
export interface ToolExecution {
  id: string
  name: string
  arguments: Record<string, unknown>
  output?: string
  status: 'running' | 'completed' | 'failed'
  startTime: number
  endTime?: number
  /** Accumulated raw JSON fragments while LLM is still generating args (cleared on completion) */
  streamingArgs?: string
}

// ─── Streaming Message (for rendering) ───
export interface StreamingMessage {
  id: string
  role: MessageRole
  content: string
  thinking?: string
  toolCalls: ToolExecution[]
  isStreaming: boolean
  timestamp: string
  /** System-injected message (planning, reflection, checkpoint, etc.) */
  isSystemInject?: boolean
  /** Sub-type for system-injected messages */
  systemInjectType?: 'planning' | 'reflection' | 'checkpoint' | 'repetition' | 'flag_candidate' | 'thinking_hint' | 'system'
}

// ─── Solve Stats ───
export interface SolveRecord {
  session_id: string
  challenge_id: string
  agent_type: string
  model: string
  category: string
  success: boolean
  flag_found?: string
  rounds: number
  tool_calls: number
  tool_usage: Record<string, number>
  tool_errors: Record<string, number>
  reflections: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  started_at: string
  finished_at: string
  duration_secs: number
}

// ─── Inspection ───
export type InspectionStatus = 'idle' | 'running' | 'completed' | 'failed'
export type InspectionSeverity = 'critical' | 'warning' | 'info' | 'pass'

export interface InspectionHost {
  id: string
  name: string
  host: string
  port: number
  username: string
  auth_method: string
  status: InspectionStatus
  last_run_at?: string
  issue_count: number
  warn_count: number
  pass_count: number
  created_at: string
  updated_at: string
}

export interface InspectionRun {
  id: string
  host_id: string
  status: InspectionStatus
  modules: string[]
  issue_count: number
  warn_count: number
  pass_count: number
  started_at: string
  finished_at?: string
}

export interface InspectionResult {
  id: string
  host_id: string
  run_id: string
  module: string
  check_name: string
  severity: InspectionSeverity
  summary: string
  detail: string
  raw_output?: string
  created_at: string
}

export interface InspectionModule {
  name: string
  label: string
  description: string
}

// ─── Reverse Engineering Lab ───
export interface ReverseBinary {
  id: string
  name: string
  file_path: string
  file_size: number
  file_type: string
  arch: string
  checksec?: ChecksecResult
  packer_info?: PackerInfo
  session_id?: string
  terminal_id?: string
  analysis_note?: string
  uploaded_at: string
  analyzed_at?: string
}

export interface ChecksecResult {
  nx: string
  pie: string
  canary: string
  relro: string
  rpath?: string
  fortify?: string
  stripped?: string
  raw?: string
}

export interface PackerInfo {
  packed: boolean
  type: string
  confidence: number
  details: string
  suggestion: string
  signatures?: string[]
}

export interface StringsResult {
  strings: StringEntry[]
  total: number
}

export interface StringEntry {
  offset?: string
  value: string
}

export interface DecompileTask {
  task_id: string
  binary_id: string
  function_name?: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: string
  error?: string
  started_at: string
  finished_at?: string
}

export interface AlgorithmSignature {
  name: string
  category: string
  constants: string[]
  byte_pattern?: string
  description: string
  key_size?: string
  tips?: string
}
