//! Native state infrastructure for the agent and retest command families.
//!
//! This module deliberately owns orchestration state, rather than pretending
//! to be an AI client or a document scanner.  It provides the durable,
//! generation-aware protocol used by the native model, probe, report, and
//! locked external-tool implementations. No business Python process or
//! sidecar is available here.

use super::config::ConfigStore;
use super::model_client;
use super::probe_runner;
use super::probe_source_builder;
use super::retest;
use super::retest_external;
use super::retest_reports;
use quick_xml::events::Event as XmlEvent;
use quick_xml::Reader as XmlReader;
use regex::Regex;
use reqwest::blocking::Client as BlockingHttpClient;
use reqwest::redirect::Policy as RedirectPolicy;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Cursor, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use zip::ZipArchive;

/// Commands with a native state-machine implementation.
pub const NATIVE_RUNTIME_COMMANDS: &[&str] = &[
    "doc.agent.message",
    "doc.agent.status",
    "doc.agent.stop",
    "doc.agent.approval.respond",
    "doc.agent.auto_approval.set",
    "doc.agent.auto_approval.status",
    "doc.agent.operation.status",
    "doc.agent.operation.stop",
    "doc.agent.tools",
    "doc.retest.run",
    "doc.retest.run_one",
    "doc.retest.run_one.start",
    "doc.retest.run_one.status",
    "doc.retest.run_one.stop",
    "doc.retest.confirmation.respond",
    "doc.retest.event_stream.info",
    "doc.retest.agent.start",
    "doc.retest.agent.message",
    "doc.retest.agent.status",
    "doc.retest.agent.stop",
    "doc.retest.agent_chat",
    "doc.retest.session.compact",
];

pub fn is_command(command: &str) -> bool {
    NATIVE_RUNTIME_COMMANDS.contains(&command)
}

const STATE_VERSION: u32 = 1;
const STATE_FILE: &str = ".koi_native_runtime_state.json";
const MAX_EVENTS: usize = 400;
const MAX_LOGS: usize = 400;
const MAX_MESSAGE: usize = 8_000;
const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

static NEXT_LOCAL_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Deserialize, Default)]
struct SessionRequest {
    #[serde(default)]
    session_id: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct AgentMessageRequest {
    #[serde(default)]
    session_id: String,
    #[serde(default, alias = "content")]
    message: String,
    #[serde(default)]
    auto_approve: Option<bool>,
    #[serde(default)]
    operation: Option<Value>,
    #[serde(default)]
    frontend_context: Option<Value>,
    #[serde(default, alias = "targetDir")]
    target_dir: Option<String>,
    #[serde(default)]
    force_resume: bool,
    #[serde(default)]
    one_click_queue: bool,
    #[serde(default = "default_true")]
    use_progress_evidence: bool,
    #[serde(default)]
    generate_reports: bool,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct AgentStartRequest {
    #[serde(default)]
    session_id: String,
    #[serde(default, alias = "targetDir")]
    target_dir: Option<String>,
    #[serde(default, alias = "content")]
    message: String,
    #[serde(default)]
    force_resume: bool,
    #[serde(default)]
    generate_reports: bool,
    #[serde(default)]
    one_click_queue: bool,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct AutoApprovalRequest {
    #[serde(default)]
    session_id: String,
    #[serde(default, alias = "autoApprove", alias = "auto_approve")]
    enabled: bool,
    #[serde(default)]
    note: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct ApprovalRequest {
    #[serde(default, alias = "confirmation_id")]
    approval_id: String,
    #[serde(default)]
    session_id: String,
    #[serde(default)]
    decision: String,
    #[serde(default)]
    note: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct OperationRequest {
    #[serde(default)]
    session_id: String,
    #[serde(default, alias = "operationId")]
    operation_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct RunOneStartRequest {
    source_file: String,
    #[serde(default)]
    session_id: String,
    #[serde(default)]
    round_id: String,
    #[serde(default)]
    source_file_name: String,
    #[serde(default)]
    mode: String,
    #[serde(default)]
    use_ai: bool,
    #[serde(default)]
    resume_snapshot: Option<Value>,
    #[serde(default)]
    requires_confirmation: bool,
}

#[derive(Debug, Clone, Deserialize)]
struct RetestBatchRequest {
    target_dir: String,
    #[serde(default = "default_true")]
    use_ai: bool,
    #[serde(default = "default_true")]
    generate_reports: bool,
    #[serde(default)]
    session_id: String,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Deserialize, Default)]
struct TaskStatusRequest {
    task_id: String,
    #[serde(default)]
    log_offset: usize,
    #[serde(default)]
    trace_event_offset: usize,
}

#[derive(Debug, Clone, Serialize)]
struct RetestResumePlan {
    target_dir: String,
    source_files: Vec<String>,
    completed_source_files: Vec<String>,
    pending_source_files: Vec<String>,
    next_index: usize,
    next_source_file: Option<String>,
    current_file_checkpoint: Option<Value>,
    disk_report_evidence: Vec<Value>,
    completed_count_hint: usize,
    next_index_hint: usize,
    numeric_hints_used: bool,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct ConfirmationRequest {
    #[serde(default, alias = "approval_id")]
    confirmation_id: String,
    #[serde(default)]
    session_id: String,
    #[serde(default)]
    decision: String,
    #[serde(default)]
    note: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct CompactRequest {
    #[serde(default)]
    session_id: String,
    #[serde(default)]
    local_memory: String,
    #[serde(default)]
    frontend_context: Option<Value>,
    #[serde(default)]
    compact_stats: Option<Value>,
    #[serde(default)]
    recent_events: Option<Vec<Value>>,
    #[serde(default)]
    logs: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedState {
    schema_version: u32,
    sequence: u64,
    sessions: BTreeMap<String, SessionState>,
    tasks: BTreeMap<String, TaskState>,
    confirmations: BTreeMap<String, ConfirmationState>,
}

impl Default for PersistedState {
    fn default() -> Self {
        Self {
            schema_version: STATE_VERSION,
            sequence: 0,
            sessions: BTreeMap::new(),
            tasks: BTreeMap::new(),
            confirmations: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SessionState {
    id: String,
    kind: String,
    workspace_root: String,
    generation: u64,
    running: bool,
    stopped: bool,
    status: String,
    message: String,
    auto_approve: bool,
    events: Vec<Value>,
    operations: BTreeMap<String, OperationState>,
    approvals: BTreeMap<String, ApprovalState>,
    resume_snapshot: Option<Value>,
    logs: Vec<String>,
    updated_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct OperationState {
    id: String,
    approval_id: Option<String>,
    tool_name: String,
    status: String,
    risk: String,
    detail: String,
    #[serde(default)]
    arguments: Value,
    #[serde(default)]
    continuation_depth: u8,
    generation: u64,
    started_at: u64,
    finished_at: Option<u64>,
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ApprovalState {
    id: String,
    operation_id: Option<String>,
    decision: String,
    note: String,
    generation: u64,
    created_at: u64,
    resolved_at: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ConfirmationState {
    id: String,
    session_id: String,
    #[serde(default)]
    task_id: String,
    #[serde(default)]
    source_file: String,
    #[serde(default)]
    request: Option<RunOneStartRequest>,
    decision: String,
    note: String,
    generation: u64,
    created_at: u64,
    resolved_at: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TaskState {
    id: String,
    session_id: String,
    generation: u64,
    running: bool,
    done: bool,
    stopped: bool,
    success: bool,
    progress: u8,
    message: String,
    source_file: String,
    logs: Vec<String>,
    trace_events: Vec<Value>,
    resume_snapshot: Option<Value>,
    result: Option<Value>,
    error: Option<String>,
    created_at: u64,
    finished_at: Option<u64>,
}

#[derive(Debug, Clone)]
struct EventInfo {
    host: String,
    port: u16,
    token: String,
    ws_url: String,
}

#[derive(Debug)]
struct EventBus {
    subscribers: Mutex<Vec<mpsc::SyncSender<String>>>,
}

impl EventBus {
    fn new() -> Self {
        Self {
            subscribers: Mutex::new(Vec::new()),
        }
    }

    fn subscribe(&self) -> mpsc::Receiver<String> {
        let (sender, receiver) = mpsc::sync_channel(64);
        self.subscribers
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .push(sender);
        receiver
    }

    fn publish(&self, value: String) {
        let mut subscribers = self
            .subscribers
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        subscribers.retain(|sender| match sender.try_send(value.clone()) {
            Ok(()) | Err(mpsc::TrySendError::Full(_)) => true,
            Err(mpsc::TrySendError::Disconnected(_)) => false,
        });
    }
}

struct RuntimeInner {
    path: PathBuf,
    state: Mutex<PersistedState>,
    event_info: EventInfo,
    event_bus: Arc<EventBus>,
    stop_server: Arc<AtomicBool>,
}

impl Drop for RuntimeInner {
    fn drop(&mut self) {
        self.stop_server.store(true, Ordering::Release);
    }
}

/// Durable native runtime shared by all command dispatches.
#[derive(Clone)]
pub struct NativeRuntime {
    inner: Arc<RuntimeInner>,
    home_dir: PathBuf,
}

impl NativeRuntime {
    pub fn new(data_dir: PathBuf, home_dir: PathBuf) -> Result<Self, String> {
        fs::create_dir_all(&data_dir)
            .map_err(|error| format!("failed to create native runtime directory: {error}"))?;
        let path = data_dir.join(STATE_FILE);
        let state = load_state(&path)?;
        let (event_info, event_bus, stop_server) = start_event_server()?;
        Ok(Self {
            inner: Arc::new(RuntimeInner {
                path,
                state: Mutex::new(state),
                event_info,
                event_bus,
                stop_server,
            }),
            home_dir,
        })
    }

    pub fn dispatch(
        &self,
        command: &str,
        payload: &Value,
        config: &ConfigStore,
    ) -> Result<Value, String> {
        match command {
            "doc.agent.message" => self.agent_message(payload, config, false),
            "doc.agent.status" => self.agent_status(payload),
            "doc.agent.stop" => self.agent_stop(payload),
            "doc.agent.approval.respond" => self.agent_approval(payload),
            "doc.agent.auto_approval.set" => self.agent_auto_approval(payload),
            "doc.agent.auto_approval.status" => self.agent_auto_approval_status(payload),
            "doc.agent.operation.status" => self.operation_status(payload),
            "doc.agent.operation.stop" => self.operation_stop(payload),
            "doc.agent.tools" => Ok(self.agent_tools(payload)),
            "doc.retest.run" => self.retest_run(payload, config),
            "doc.retest.run_one" => self.retest_run_one(payload, config),
            "doc.retest.run_one.start" => self.retest_run_one_start(payload),
            "doc.retest.run_one.status" => self.retest_run_one_status(payload),
            "doc.retest.run_one.stop" => self.retest_run_one_stop(payload),
            "doc.retest.confirmation.respond" => self.retest_confirmation(payload),
            "doc.retest.event_stream.info" => Ok(self.event_stream_info()),
            "doc.retest.agent.start" => self.retest_agent_start(payload, config),
            "doc.retest.agent.message" => self.agent_message(payload, config, true),
            "doc.retest.agent.status" => self.retest_agent_status(payload),
            "doc.retest.agent.stop" => self.retest_agent_stop(payload),
            "doc.retest.agent_chat" => self.agent_chat(payload, config),
            "doc.retest.session.compact" => self.session_compact(payload, config),
            _ => Err(format!("native runtime command not registered: {command}")),
        }
    }

    fn event_stream_info(&self) -> Value {
        json!({
            "success": true,
            "message": "Rust loopback event stream ready",
            "host": self.inner.event_info.host,
            "port": self.inner.event_info.port,
            "token": self.inner.event_info.token,
            "ws_url": self.inner.event_info.ws_url,
        })
    }

    fn agent_tools(&self, payload: &Value) -> Value {
        let request = parse_payload::<SessionRequest>(payload).unwrap_or_default();
        let session_id = self.session_id_or_new(&request.session_id, "agent");
        json!({
            "success": true,
            "session_id": session_id,
            "auto_approve": self.session_auto_approve(&session_id),
            "workspace_root": self.workspace_root(payload),
            "tools": [
                {"name":"workspace_tree","description":"List files and directories under the current workspace root. Read-only.","risk":"read","requiresApproval":false,"workspaceOnly":true,"parameters":{"type":"object","properties":{"path":{"type":"string"},"max_entries":{"type":"integer"}}}},
                {"name":"read_file","description":"Read a UTF-8 text file inside the workspace. Read-only.","risk":"read","requiresApproval":false,"workspaceOnly":true,"parameters":{"type":"object","properties":{"path":{"type":"string"},"max_chars":{"type":"integer"}},"required":["path"]}},
                {"name":"search_code","description":"Search text in workspace files. Read-only.","risk":"read","requiresApproval":false,"workspaceOnly":true,"parameters":{"type":"object","properties":{"query":{"type":"string"},"path":{"type":"string"},"max_matches":{"type":"integer"}},"required":["query"]}},
                {"name":"inspect_git_diff","description":"Inspect current git diff/stat for the workspace. Read-only.","risk":"read","requiresApproval":false,"workspaceOnly":true,"parameters":{"type":"object","properties":{}}},
                {"name":"summarize_file","description":"Read and summarize the shape of a source file. Read-only.","risk":"read","requiresApproval":false,"workspaceOnly":true,"parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
                {"name":"run_python_probe","description":"Run a bounded AI-authored Python HTTP probe in the locked Windows AppContainer runtime. Network access is only available through the authorized Rust named-pipe broker. Optional packages must be present in the reviewed recursive wheel lock; source distributions and host pip are refused.","risk":"external","requiresApproval":true,"autoApprovalSupported":true,"workspaceOnly":false,"parameters":{"type":"object","properties":{"script":{"type":"string"},"targets":{"type":"array","items":{"type":"string"},"maxItems":20},"context":{"type":"object"},"packages":{"type":"array","items":{"type":"string"},"maxItems":32}},"required":["script","targets"]}},
                {"name":"build_python_probe_wheel","description":"After a separate probe-package approval, build one reviewed source distribution in a disposable networkless Windows AppContainer. This operation always requires a second manual approval and cannot be auto-approved.","risk":"source_build","requiresApproval":true,"autoApprovalSupported":false,"workspaceOnly":false,"parameters":{"type":"object","properties":{"package":{"type":"string"}},"required":["package"]}},
                {"name":"run_command","description":"Run a shell command inside the workspace after user approval and command sandbox checks.","risk":"command","requiresApproval":true,"autoApprovalSupported":true,"workspaceOnly":true,"parameters":{"type":"object","properties":{"command":{"type":"string"},"cwd":{"type":"string"},"timeout_seconds":{"type":"integer"}},"required":["command"]}},
                {"name":"apply_patch","description":"Apply a unified text diff inside the workspace after user approval.","risk":"write","requiresApproval":true,"autoApprovalSupported":true,"workspaceOnly":true,"parameters":{"type":"object","properties":{"patch":{"type":"string"}},"required":["patch"]}},
                {"name":"run_tests","description":"Run project tests after user approval.","risk":"test","requiresApproval":true,"autoApprovalSupported":true,"workspaceOnly":true,"parameters":{"type":"object","properties":{"command":{"type":"string"},"cwd":{"type":"string"}}}},
                {"name":"build_project","description":"Run project build checks after user approval.","risk":"build","requiresApproval":true,"autoApprovalSupported":true,"workspaceOnly":true,"parameters":{"type":"object","properties":{"command":{"type":"string"},"cwd":{"type":"string"}}}}
            ]
        })
    }

    fn agent_message(
        &self,
        payload: &Value,
        config: &ConfigStore,
        retest: bool,
    ) -> Result<Value, String> {
        let request: AgentMessageRequest = parse_payload(payload)?;
        let session_id = required_or_new(
            &request.session_id,
            if retest { "retest" } else { "agent" },
            self,
        );
        let message = request.message.trim().to_string();
        if message.is_empty() {
            return Err("message is required".to_string());
        }
        let resume_plan = if retest && (request.force_resume || request.one_click_queue) {
            build_retest_resume_plan(&request, &self.home_dir)?
        } else {
            None
        };
        let mut frontend_context = request
            .frontend_context
            .as_ref()
            .map(|value| sanitize_value(value, 0));
        if let Some(plan) = resume_plan.as_ref() {
            let context = frontend_context.get_or_insert_with(|| json!({}));
            if !context.is_object() {
                *context = json!({"legacy_context": context.clone()});
            }
            context["rustResumePlan"] = json!(plan);
        }
        let mut state = self.lock_state();
        let (generation, auto_approve, history, workspace_root) = {
            let session = ensure_session(
                &mut state,
                &session_id,
                if retest { "retest" } else { "agent" },
                self.workspace_root(payload),
            );
            let generation = begin_generation(session);
            session.running = true;
            session.stopped = false;
            session.status = "model_request".to_string();
            session.message = "Agent is reasoning".to_string();
            if let Some(enabled) = request.auto_approve {
                session.auto_approve = enabled;
            }
            if let Some(frontend_context) = frontend_context.as_ref() {
                session.resume_snapshot = Some(frontend_context.clone());
            }
            let user_event = make_event("message", "User message", &message, "info", generation);
            push_event(session, user_event);
            if let Some(plan) = resume_plan.as_ref() {
                let next = plan.next_source_file.as_deref().unwrap_or("queue complete");
                push_event(
                    session,
                    make_event(
                        "status",
                        "Rust resume evidence verified",
                        &format!(
                            "trusted_completed={}; next_source_file={next}; numeric_hints_used=false",
                            plan.completed_source_files.len()
                        ),
                        "info",
                        generation,
                    ),
                );
            }
            session.logs.push(truncate(&message, MAX_MESSAGE));
            trim_session(session);
            let history = session
                .events
                .iter()
                .rev()
                .take(40)
                .rev()
                .map(|value| sanitize_value(value, 0))
                .collect::<Vec<_>>();
            (
                generation,
                session.auto_approve,
                history,
                session.workspace_root.clone(),
            )
        };
        persist_locked(&self.inner, &state)?;
        drop(state);
        self.publish_session_event(&session_id, None, Some(generation));

        if let Some(operation) = request.operation.as_ref() {
            let operation_auto_approve = operation_may_auto_approve(operation, auto_approve);
            let mut state = self.lock_state();
            let session = state.sessions.get(&session_id).expect("session exists");
            if session.generation != generation || session.stopped {
                return Ok(stale_generation_response(
                    &session_id,
                    generation,
                    session.generation,
                ));
            }
            let (operation_id, approval_id) = create_operation_locked(
                &mut state,
                &session_id,
                generation,
                operation,
                operation_auto_approve,
            );
            let session = state.sessions.get_mut(&session_id).expect("session exists");
            session.running = false;
            session.status = if operation_auto_approve {
                "approved_pending_executor"
            } else {
                "awaiting_approval"
            }
            .to_string();
            session.message = if operation_auto_approve {
                "Operation approved and waiting for the Rust executor"
            } else {
                "Operation is waiting for user approval"
            }
            .to_string();
            push_event(
                session,
                make_event(
                    "tool_call",
                    "Operation proposed",
                    &operation_id,
                    "warn",
                    generation,
                ),
            );
            let proposed_message = session.message.clone();
            persist_locked(&self.inner, &state)?;
            drop(state);
            if operation_auto_approve {
                self.start_operation_executor(&session_id, &operation_id, generation)?;
            }
            self.publish_session_event(&session_id, None, Some(generation));
            let state = self.lock_state();
            let snapshot =
                session_snapshot(state.sessions.get(&session_id).expect("session exists"));
            return Ok(json!({
                "success": true,
                "session_id": session_id,
                "running": operation_auto_approve,
                "active": true,
                "blocked": !operation_auto_approve,
                "message": proposed_message,
                "final_message": proposed_message,
                "status": snapshot["status"],
                "progress": 0,
                "generation": generation,
                "operation_id": operation_id,
                "approval_id": approval_id,
                "auto_approved": operation_auto_approve,
                "resume_plan": resume_plan,
                "agent_session": snapshot,
            }));
        }

        let model_input = json!({
            "session_id": session_id,
            "mode": if retest { "retest" } else { "hybrid" },
            "workspace_root": workspace_root,
            "message": message,
            "auto_approve": auto_approve,
            "recent_events": history,
            "frontend_context": frontend_context,
            "resume_plan": resume_plan,
            "force_resume": request.force_resume,
            "one_click_queue": request.one_click_queue,
            "generate_reports": request.generate_reports,
            "response_schema": {
                "reply": "user-visible response",
                "thinking": "brief evidence-based reasoning, optional",
                "operation": "null or one typed operation object with tool_name, risk, and detail"
            }
        });
        const SYSTEM: &str = "You are the KOI security document agent. Return exactly one JSON object. Use only supplied evidence. Never claim a command, retest, file edit, or report completed unless the evidence says so. When resume_plan is present it is authoritative: numeric hints were not used to skip files, and next_source_file is the first unfinished exact source path. If an external or mutating action is required, put one operation object in operation; otherwise operation must be null. Keep reply concise and actionable.";
        // The transport emits provider deltas synchronously.  Every delta is
        // checked against the session generation before it enters durable
        // state or the WebSocket event bus; stopping a session therefore
        // invalidates both the eventual reply and any late token chunks.
        let mut stream_discarded = false;
        let mut on_delta = |delta: &str| {
            let accepted = self.publish_model_delta(&session_id, generation, delta);
            if !accepted {
                stream_discarded = true;
            }
            accepted
        };
        match model_client::complete_json_streaming(
            config,
            payload,
            SYSTEM,
            &model_input,
            &mut on_delta,
        ) {
            Ok(completion) => {
                let reply = completion
                    .json
                    .get("reply")
                    .or_else(|| completion.json.get("message"))
                    .or_else(|| completion.json.get("final_message"))
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| "model response omitted reply".to_string())?
                    .chars()
                    .take(6_000)
                    .collect::<String>();
                let thinking = completion
                    .json
                    .get("thinking")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .map(|value| truncate(value, 3_000));
                let model_operation = completion
                    .json
                    .get("operation")
                    .filter(|value| value.is_object())
                    .cloned();
                let provider = completion.provider;
                let model = completion.model;
                let _model_output_length = completion.content.len();
                let model_operation_auto_approve = model_operation
                    .as_ref()
                    .is_some_and(|operation| operation_may_auto_approve(operation, auto_approve));

                let mut state = self.lock_state();
                let session = state
                    .sessions
                    .get_mut(&session_id)
                    .ok_or_else(|| "session not found".to_string())?;
                if stream_discarded || session.generation != generation || session.stopped {
                    return Ok(stale_generation_response(
                        &session_id,
                        generation,
                        session.generation,
                    ));
                }
                session.running = false;
                session.status = "completed".to_string();
                session.message = reply.clone();
                if let Some(thinking) = thinking.as_ref() {
                    push_event(
                        session,
                        make_event("thought", "Agent reasoning", thinking, "info", generation),
                    );
                }
                push_event(
                    session,
                    make_event("chat", "Agent", &reply, "ok", generation),
                );
                session
                    .logs
                    .push(format!("Agent: {}", truncate(&reply, 1_000)));
                trim_session(session);

                let operation_result = model_operation.as_ref().map(|operation| {
                    create_operation_locked(
                        &mut state,
                        &session_id,
                        generation,
                        operation,
                        model_operation_auto_approve,
                    )
                });
                if operation_result.is_some() {
                    let session = state.sessions.get_mut(&session_id).expect("session exists");
                    session.status = if model_operation_auto_approve {
                        "approved_pending_executor"
                    } else {
                        "awaiting_approval"
                    }
                    .to_string();
                }
                let session = state.sessions.get(&session_id).expect("session exists");
                let snapshot = session_snapshot(session);
                let status = session.status.clone();
                let logs = session.logs.clone();
                persist_locked(&self.inner, &state)?;
                drop(state);
                let operation_to_start = operation_result
                    .as_ref()
                    .filter(|_| model_operation_auto_approve)
                    .map(|(operation, _)| operation.clone());
                if let Some(operation_id) = operation_to_start.as_deref() {
                    self.start_operation_executor(&session_id, operation_id, generation)?;
                }
                self.publish_session_event(&session_id, None, Some(generation));
                let (operation_id, approval_id) = operation_result
                    .map(|(operation, approval)| (Value::String(operation), json!(approval)))
                    .unwrap_or((Value::Null, Value::Null));
                Ok(json!({
                    "success": true,
                    "session_id": session_id,
                    "running": model_operation.is_some() && model_operation_auto_approve,
                    "active": true,
                    "blocked": model_operation.is_some() && !model_operation_auto_approve,
                    "message": reply,
                    "final_message": reply,
                    "reply": reply,
                    "thinking": thinking,
                    "status": status,
                    "progress": 100,
                    "generation": generation,
                    "provider": provider,
                    "model": model,
                    "operation_id": operation_id,
                    "approval_id": approval_id,
                    "auto_approved": model_operation.is_some() && model_operation_auto_approve,
                    "resume_plan": resume_plan,
                    "agent_session": snapshot,
                    "logs": logs,
                }))
            }
            Err(error) => {
                let mut state = self.lock_state();
                let session = state
                    .sessions
                    .get_mut(&session_id)
                    .ok_or_else(|| "session not found".to_string())?;
                if session.generation != generation || session.stopped {
                    return Ok(stale_generation_response(
                        &session_id,
                        generation,
                        session.generation,
                    ));
                }
                session.running = false;
                session.status = "blocked".to_string();
                session.message = format!("Rust model request failed: {error}");
                push_event(
                    session,
                    make_event(
                        "status",
                        "Agent model request blocked",
                        &error,
                        "warn",
                        generation,
                    ),
                );
                let snapshot = session_snapshot(session);
                let logs = session.logs.clone();
                persist_locked(&self.inner, &state)?;
                self.publish_session_event(&session_id, None, Some(generation));
                Ok(json!({
                    "success": false,
                    "session_id": session_id,
                    "running": false,
                    "active": true,
                    "blocked": true,
                    "blocked_by_ai_config": true,
                    "blocked_stage": "model_transport",
                    "blocked_title": "Rust model request failed",
                    "message": format!("Rust model request failed: {error}"),
                    "final_message": format!("Rust model request failed: {error}"),
                    "status": "blocked",
                    "progress": 0,
                    "generation": generation,
                    "resume_plan": resume_plan,
                    "agent_session": snapshot,
                    "logs": logs,
                }))
            }
        }
    }

    fn agent_status(&self, payload: &Value) -> Result<Value, String> {
        let request: SessionRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "agent", self);
        let mut state = self.lock_state();
        let session = ensure_session(
            &mut state,
            &session_id,
            "agent",
            self.workspace_root(payload),
        );
        let response = agent_status_response(session);
        persist_locked(&self.inner, &state)?;
        Ok(response)
    }

    fn agent_stop(&self, payload: &Value) -> Result<Value, String> {
        let request: SessionRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "agent", self);
        if !self.lock_state().sessions.contains_key(&session_id) {
            let mut state = self.lock_state();
            ensure_session(
                &mut state,
                &session_id,
                "agent",
                self.workspace_root(payload),
            );
            persist_locked(&self.inner, &state)?;
        }
        self.stop_session(&session_id, "agent")
    }

    fn agent_auto_approval(&self, payload: &Value) -> Result<Value, String> {
        let request: AutoApprovalRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "agent", self);
        let mut state = self.lock_state();
        let session = ensure_session(
            &mut state,
            &session_id,
            "agent",
            self.workspace_root(payload),
        );
        session.auto_approve = request.enabled;
        session.updated_at = now_ms();
        if !request.note.trim().is_empty() {
            let generation = session.generation;
            push_event(
                session,
                make_event(
                    "status",
                    "Auto approval updated",
                    &request.note,
                    "info",
                    generation,
                ),
            );
        }
        let snapshot = session_snapshot(session);
        persist_locked(&self.inner, &state)?;
        self.publish_session_event(
            &session_id,
            None,
            snapshot.get("generation").and_then(Value::as_u64),
        );
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "auto_approve": request.enabled,
            "workspace_root": snapshot["workspace_root"],
            "agent_session": snapshot,
            "message": if request.enabled { "Auto approval enabled" } else { "Auto approval disabled" },
        }))
    }

    fn agent_auto_approval_status(&self, payload: &Value) -> Result<Value, String> {
        let request: SessionRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "agent", self);
        let mut state = self.lock_state();
        let session = ensure_session(
            &mut state,
            &session_id,
            "agent",
            self.workspace_root(payload),
        );
        let auto = session.auto_approve;
        let workspace_root = session.workspace_root.clone();
        let snapshot = session_snapshot(session);
        persist_locked(&self.inner, &state)?;
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "auto_approve": auto,
            "workspace_root": workspace_root,
            "agent_session": snapshot,
        }))
    }

    fn agent_approval(&self, payload: &Value) -> Result<Value, String> {
        let request: ApprovalRequest = parse_payload(payload)?;
        let approval_id = required_text(&request.approval_id, "approval_id")?;
        let decision = normalize_decision(&request.decision)?;
        let mut state = self.lock_state();
        let (session_id, operation_id, generation) = find_approval(&state, &approval_id)
            .ok_or_else(|| "approval request not found or expired".to_string())?;
        if !request.session_id.trim().is_empty() && request.session_id != session_id {
            return Err("approval does not belong to session_id".to_string());
        }
        let session = state
            .sessions
            .get_mut(&session_id)
            .ok_or_else(|| "agent session not found".to_string())?;
        if session.generation != generation || session.stopped {
            return Err("approval belongs to an inactive generation".to_string());
        }
        if let Some(approval) = session.approvals.get_mut(&approval_id) {
            approval.decision = decision.to_string();
            approval.note = truncate(&request.note, 2_000);
            approval.resolved_at = Some(now_ms());
        }
        if let Some(operation_id) = operation_id.as_ref() {
            if let Some(operation) = session.operations.get_mut(operation_id) {
                operation.status = if decision == "approve" {
                    "approved_pending_executor"
                } else {
                    "rejected"
                }
                .to_string();
                operation.finished_at = (decision != "approve").then(now_ms);
            }
        }
        let event = make_event(
            "approval",
            "Approval resolved",
            decision,
            if decision == "approve" { "ok" } else { "warn" },
            generation,
        );
        push_event(session, event);
        let snapshot = session_snapshot(session);
        persist_locked(&self.inner, &state)?;
        drop(state);
        if decision == "approve" {
            if let Some(operation_id) = operation_id.as_deref() {
                self.start_operation_executor(&session_id, operation_id, generation)?;
            }
        }
        self.publish_session_event(&session_id, None, Some(generation));
        let state = self.lock_state();
        let latest_snapshot = state
            .sessions
            .get(&session_id)
            .map(session_snapshot)
            .unwrap_or(snapshot);
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "approval_id": approval_id,
            "decision": decision,
            "operation_id": operation_id,
            "status": if decision == "approve" { "running" } else { "rejected" },
            "agent_session": latest_snapshot,
        }))
    }

    fn operation_status(&self, payload: &Value) -> Result<Value, String> {
        let request: OperationRequest = parse_payload(payload)?;
        let session_id = required_text(&request.session_id, "session_id")?;
        let operation_id = required_text(&request.operation_id, "operation_id")?;
        let state = self.lock_state();
        let session = state
            .sessions
            .get(&session_id)
            .ok_or_else(|| "agent session not found".to_string())?;
        let operation = session
            .operations
            .get(&operation_id)
            .ok_or_else(|| "operation not found".to_string())?;
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "operation_id": operation_id,
            "operation": operation,
            "running_operation": if operation.status == "running" { json!(operation) } else { Value::Null },
            "agent_session": session_snapshot(session),
        }))
    }

    fn operation_stop(&self, payload: &Value) -> Result<Value, String> {
        let request: OperationRequest = parse_payload(payload)?;
        let session_id = required_text(&request.session_id, "session_id")?;
        let operation_id = required_text(&request.operation_id, "operation_id")?;
        let mut state = self.lock_state();
        let session = state
            .sessions
            .get_mut(&session_id)
            .ok_or_else(|| "agent session not found".to_string())?;
        let generation = begin_generation(session);
        let operation = session
            .operations
            .get_mut(&operation_id)
            .ok_or_else(|| "operation not found".to_string())?;
        operation.status = "cancelled".to_string();
        operation.finished_at = Some(now_ms());
        operation.error = Some("cancelled by user".to_string());
        session.running = false;
        session.stopped = false;
        session.status = "operation_cancelled".to_string();
        session.message = "Operation cancelled".to_string();
        push_event(
            session,
            make_event(
                "status",
                "Operation cancelled",
                &operation_id,
                "warn",
                generation,
            ),
        );
        let snapshot = session_snapshot(session);
        persist_locked(&self.inner, &state)?;
        self.publish_session_event(&session_id, None, Some(generation));
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "operation_id": operation_id,
            "cancelled": true,
            "generation": generation,
            "agent_session": snapshot,
        }))
    }

    fn start_operation_executor(
        &self,
        session_id: &str,
        operation_id: &str,
        generation: u64,
    ) -> Result<(), String> {
        {
            let mut state = self.lock_state();
            let session = state
                .sessions
                .get_mut(session_id)
                .ok_or_else(|| "agent session not found".to_string())?;
            if session.generation != generation || session.stopped {
                return Err("operation belongs to an inactive generation".to_string());
            }
            let operation = session
                .operations
                .get_mut(operation_id)
                .ok_or_else(|| "operation not found".to_string())?;
            operation.status = "running".to_string();
            operation.finished_at = None;
            operation.error = None;
            session.running = true;
            session.status = "operation_running".to_string();
            session.message = format!("Running operation: {}", operation.tool_name);
            persist_locked(&self.inner, &state)?;
        }
        self.publish_session_event(session_id, None, Some(generation));
        let runtime = self.clone();
        let session_id = session_id.to_string();
        let operation_id = operation_id.to_string();
        thread::Builder::new()
            .name(format!("koi-agent-operation-{operation_id}"))
            .spawn(move || runtime.finish_operation(&session_id, &operation_id, generation))
            .map_err(|error| format!("failed to start Rust operation executor: {error}"))?;
        Ok(())
    }

    fn finish_operation(&self, session_id: &str, operation_id: &str, generation: u64) {
        let (operation, workspace_root) = {
            let state = self.lock_state();
            let Some(session) = state.sessions.get(session_id) else {
                return;
            };
            let Some(operation) = session.operations.get(operation_id) else {
                return;
            };
            (operation.clone(), session.workspace_root.clone())
        };
        let result = if operation.tool_name == "run_python_probe" {
            let data_dir = self.inner.path.parent().unwrap_or(Path::new("."));
            probe_runner::execute(data_dir, &operation.arguments).and_then(|value| {
                serde_json::to_string_pretty(&value)
                    .map_err(|error| format!("serialize dynamic probe result failed: {error}"))
            })
        } else if operation.tool_name == "build_python_probe_wheel" {
            let data_dir = self.inner.path.parent().unwrap_or(Path::new("."));
            probe_source_builder::execute_approved(data_dir, &operation.arguments).and_then(
                |value| {
                    serde_json::to_string_pretty(&value)
                        .map_err(|error| format!("serialize source build result failed: {error}"))
                },
            )
        } else {
            execute_read_only_operation(&workspace_root, &operation)
        };
        let (operation_status, observation) = match &result {
            Ok(output) => ("completed", truncate(output, 12_000)),
            Err(error) => ("failed", truncate(error, 4_000)),
        };
        let mut state = self.lock_state();
        let Some(session) = state.sessions.get_mut(session_id) else {
            return;
        };
        if session.generation != generation || session.stopped {
            return;
        }
        let Some(current) = session.operations.get_mut(operation_id) else {
            return;
        };
        if current.generation != generation || current.status != "running" {
            return;
        }
        let (tone, message) = match result {
            Ok(output) => {
                current.status = "completed".to_string();
                current.detail = truncate(&output, 24_000);
                current.error = None;
                ("ok", format!("Operation completed: {}", current.tool_name))
            }
            Err(error) => {
                current.status = "failed".to_string();
                current.error = Some(truncate(&error, 4_000));
                ("error", format!("Operation failed: {error}"))
            }
        };
        current.finished_at = Some(now_ms());
        session.running = session
            .operations
            .values()
            .any(|operation| operation.status == "running");
        session.status = if session.running {
            "operation_running"
        } else {
            "operation_completed"
        }
        .to_string();
        session.message = message.clone();
        push_event(
            session,
            make_event(
                "tool_result",
                "Rust operation result",
                &message,
                tone,
                generation,
            ),
        );
        trim_session(session);
        let _ = persist_locked(&self.inner, &state);
        drop(state);
        self.publish_session_event(session_id, None, Some(generation));
        self.reflect_operation(
            session_id,
            operation_id,
            generation,
            &operation.tool_name,
            operation_status,
            &observation,
            operation.continuation_depth,
        );
    }

    #[allow(clippy::too_many_arguments)]
    fn reflect_operation(
        &self,
        session_id: &str,
        operation_id: &str,
        generation: u64,
        tool_name: &str,
        status: &str,
        observation: &str,
        continuation_depth: u8,
    ) {
        let config_path = self
            .inner
            .path
            .parent()
            .unwrap_or(Path::new("."))
            .join("config.json");
        let config = ConfigStore::new(config_path);
        let input = json!({
            "session_id": session_id,
            "operation_id": operation_id,
            "tool_name": tool_name,
            "status": status,
            "observation": observation,
            "continuation_depth": continuation_depth,
            "max_continuation_depth": 8,
            "instruction": "Reflect only on this recorded observation. Return JSON with reply, optional thinking, and at most one typed operation. Set operation to null when no further tool is required."
        });
        const SYSTEM: &str = "You are the KOI agent continuation step. Use only the recorded operation observation. Return one JSON object with reply, optional thinking, and operation. You may propose at most one typed operation when additional evidence is required. Never exceed max_continuation_depth and never invent tool results.";
        let (reply, thinking, next_operation) = match model_client::complete_json(
            &config,
            &json!({"session_id": session_id}),
            SYSTEM,
            &input,
        ) {
            Ok(completion) => {
                let next = completion
                    .json
                    .get("operation")
                    .filter(|operation| operation.is_object())
                    .cloned()
                    .filter(|_| continuation_depth < 8)
                    .map(|mut value| {
                        value["continuation_depth"] = json!(continuation_depth + 1);
                        value
                    });
                (
                    completion
                        .json
                        .get("reply")
                        .or_else(|| completion.json.get("message"))
                        .and_then(Value::as_str)
                        .map(|value| truncate(value, 6_000))
                        .filter(|value| !value.is_empty())
                        .unwrap_or_else(|| format!("{tool_name} finished with status={status}.")),
                    completion
                        .json
                        .get("thinking")
                        .and_then(Value::as_str)
                        .map(|value| truncate(value, 3_000)),
                    next,
                )
            }
            Err(_) => (
                format!("{tool_name} finished with status={status}."),
                None,
                None,
            ),
        };
        let mut state = self.lock_state();
        let Some(session) = state.sessions.get(session_id) else {
            return;
        };
        if session.generation != generation || session.stopped {
            return;
        }
        let auto_approve = session.auto_approve;
        let next_auto_approve = next_operation
            .as_ref()
            .is_some_and(|operation| operation_may_auto_approve(operation, auto_approve));
        let next_result = next_operation.as_ref().map(|operation| {
            create_operation_locked(
                &mut state,
                session_id,
                generation,
                operation,
                next_auto_approve,
            )
        });
        let Some(session) = state.sessions.get_mut(session_id) else {
            return;
        };
        if let Some(thinking) = thinking.as_ref() {
            push_event(
                session,
                make_event("thought", "Agent reflection", thinking, "info", generation),
            );
        }
        push_event(
            session,
            make_event("chat", "Agent", &reply, "ok", generation),
        );
        session.message = reply;
        session.status = if next_result.is_some() {
            if next_auto_approve {
                "approved_pending_executor"
            } else {
                "awaiting_approval"
            }
        } else {
            "completed"
        }
        .to_string();
        session.running = next_result.is_some() && next_auto_approve;
        trim_session(session);
        let _ = persist_locked(&self.inner, &state);
        drop(state);
        if let Some((next_operation_id, _)) = next_result.as_ref().filter(|_| next_auto_approve) {
            let _ = self.start_operation_executor(session_id, next_operation_id, generation);
        }
        self.publish_session_event(session_id, None, Some(generation));
    }

    fn retest_run(&self, payload: &Value, _config: &ConfigStore) -> Result<Value, String> {
        let request: RetestBatchRequest = parse_payload(payload)?;
        let target_text = required_text(&request.target_dir, "target_dir")?;
        let target = expand_user(Path::new(&target_text), &self.home_dir);
        if !target.is_dir() {
            return Ok(json!({
                "success":false,
                "message":format!("通报目录不存在: {}", target.display()),
                "logs":[]
            }));
        }
        let listed = retest::list_files(&json!({"target_dir":target}), &self.home_dir)?;
        let sources = listed
            .get("source_files")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(PathBuf::from)
            .collect::<Vec<_>>();
        let session_id = required_or_new(&request.session_id, "retest-batch", self);
        let generation = {
            let mut state = self.lock_state();
            let session = ensure_session(
                &mut state,
                &session_id,
                "retest",
                target.to_string_lossy().to_string(),
            );
            let generation = begin_generation(session);
            session.running = true;
            session.stopped = false;
            session.status = "batch_running".to_string();
            session.message = format!("Batch retest started for {} document(s)", sources.len());
            persist_locked(&self.inner, &state)?;
            generation
        };
        let mut logs = listed
            .get("logs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect::<Vec<_>>();
        let mut summaries = Vec::new();
        let mut reports = Vec::new();
        let mut risk_count = 0_u64;
        let mut pass_count = 0_u64;
        let mut failed_count = 0_u64;
        let mut processed_sources = Vec::new();
        for (index, source) in sources.iter().enumerate() {
            if !generation_active(self, &session_id, generation) {
                return Ok(json!({
                    "success":false,
                    "stopped":true,
                    "message":"Retest stopped; resume snapshot preserved",
                    "target_dir":target,
                    "processed":processed_sources.len(),
                    "source_files":processed_sources,
                    "reports":reports,
                    "summary":summaries.join("\n\n"),
                    "risk_count":risk_count,
                    "pass_count":pass_count,
                    "failed_count":failed_count,
                    "resume_snapshot":{"target_dir":target,"source_files":sources,"next_index":index},
                    "logs":logs,
                }));
            }
            logs.push(format!(
                "处理 ({}/{}): {}",
                index + 1,
                sources.len(),
                source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
            ));
            let item = RunOneStartRequest {
                source_file: source.to_string_lossy().to_string(),
                session_id: session_id.clone(),
                round_id: format!("batch-{generation}-{index}"),
                source_file_name: source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
                    .to_string(),
                mode: if request.use_ai { "ai" } else { "fast" }.to_string(),
                use_ai: request.use_ai,
                resume_snapshot: None,
                requires_confirmation: false,
            };
            let format = inspect_word_signature(source)?;
            match execute_native_retest(self, &session_id, generation, source, &item, format) {
                Ok(result) => {
                    processed_sources.push(source.to_string_lossy().to_string());
                    logs.extend(
                        result
                            .get("logs")
                            .and_then(Value::as_array)
                            .into_iter()
                            .flatten()
                            .filter_map(Value::as_str)
                            .map(str::to_string),
                    );
                    let summary = result
                        .get("summary")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    summaries.push(summary.clone());
                    let data = result.get("result_data").cloned().unwrap_or(Value::Null);
                    risk_count += data.get("risk_count").and_then(Value::as_u64).unwrap_or(0);
                    pass_count += data.get("pass_count").and_then(Value::as_u64).unwrap_or(0);
                    failed_count += data
                        .get("failed_count")
                        .and_then(Value::as_u64)
                        .unwrap_or(0);
                    if result.get("success") != Some(&Value::Bool(true)) {
                        failed_count = failed_count.saturating_add(1);
                    }
                    if request.generate_reports {
                        let report = retest_reports::dispatch(
                            retest_reports::COMMAND,
                            &json!({
                                "target_dir":target,
                                "source_files":[source],
                                "summary":summary,
                                "result_data":data,
                            }),
                            self.inner.path.parent().unwrap_or(Path::new(".")),
                            &target,
                        )?;
                        reports.extend(
                            report
                                .get("reports")
                                .and_then(Value::as_array)
                                .into_iter()
                                .flatten()
                                .filter_map(Value::as_str)
                                .map(str::to_string),
                        );
                        if report.get("success") != Some(&Value::Bool(true)) {
                            failed_count = failed_count.saturating_add(1);
                        }
                    }
                }
                Err(error) => {
                    failed_count = failed_count.saturating_add(1);
                    logs.push(format!("{} 复测失败: {error}", source.display()));
                }
            }
        }
        let message = if request.generate_reports {
            format!(
                "复测完成：处理 {} 份文档，生成 {} 份报告，漏洞未修复/可复现 {} 份，复测通过 {} 份，执行失败 {} 份",
                sources.len(), reports.len(), risk_count, pass_count, failed_count
            )
        } else {
            format!(
                "复测完成：处理 {} 份文档，等待截图写入报告，漏洞未修复/可复现 {} 份，复测通过 {} 份，执行失败 {} 份",
                sources.len(), risk_count, pass_count, failed_count
            )
        };
        {
            let mut state = self.lock_state();
            if let Some(session) = state.sessions.get_mut(&session_id) {
                if session.generation == generation && !session.stopped {
                    session.running = false;
                    session.status = "completed".to_string();
                    session.message = message.clone();
                    session.resume_snapshot = Some(json!({
                        "target_dir":target,
                        "source_files":sources,
                        "next_index":sources.len(),
                        "reports":reports,
                    }));
                }
            }
            persist_locked(&self.inner, &state)?;
        }
        Ok(json!({
            "success":true,
            "message":message,
            "target_dir":target,
            "processed":sources.len(),
            "manual_count":0,
            "risk_count":risk_count,
            "pass_count":pass_count,
            "failed_count":failed_count,
            "source_files":processed_sources,
            "reports":reports,
            "summary":summaries.join("\n\n"),
            "logs":logs,
        }))
    }

    fn retest_run_one(&self, payload: &Value, _config: &ConfigStore) -> Result<Value, String> {
        // Keep the synchronous alias explicit.  The start/status protocol is
        // the only path which can safely preserve a cancellation generation.
        let mut value = self.retest_run_one_start(payload)?;
        if value.get("done") == Some(&Value::Bool(true)) {
            return Ok(value);
        }
        value["message"] = Value::String(
            "Use doc.retest.run_one.start and status for resumable execution".to_string(),
        );
        Ok(value)
    }

    fn retest_run_one_start(&self, payload: &Value) -> Result<Value, String> {
        let request: RunOneStartRequest = parse_payload(payload)?;
        let source = required_text(&request.source_file, "source_file")?;
        let source_path = expand_user(Path::new(&source), &self.home_dir);
        validate_word_input(&source_path)?;
        let valid_container = inspect_word_signature(&source_path)?;
        let session_id = required_or_new(&request.session_id, "retest", self);
        let mut state = self.lock_state();
        let task_id = next_id(&mut state, "task");
        let confirmation_id = request
            .requires_confirmation
            .then(|| next_id(&mut state, "confirmation"));
        let generation = {
            let session = ensure_session(
                &mut state,
                &session_id,
                "retest",
                source_path
                    .parent()
                    .unwrap_or(&self.home_dir)
                    .to_string_lossy()
                    .to_string(),
            );
            let generation = begin_generation(session);
            session.running = confirmation_id.is_none();
            session.stopped = false;
            session.status = if confirmation_id.is_some() {
                "awaiting_confirmation"
            } else {
                "running"
            }
            .to_string();
            session.message = if confirmation_id.is_some() {
                "Retest is waiting for user confirmation".to_string()
            } else {
                format!("Rust retest started: {}", source_path.display())
            };
            generation
        };
        let validation_log = format!("Validated Word input: {}", source_path.display());
        let trace_events = vec![make_event(
            "status",
            "Retest task started",
            &source,
            "info",
            generation,
        )];
        if let Some(confirmation_id) = confirmation_id.as_ref() {
            state.confirmations.insert(
                confirmation_id.clone(),
                ConfirmationState {
                    id: confirmation_id.clone(),
                    session_id: session_id.clone(),
                    task_id: task_id.clone(),
                    source_file: source_path.to_string_lossy().to_string(),
                    request: Some(request.clone()),
                    decision: String::new(),
                    note: String::new(),
                    generation,
                    created_at: now_ms(),
                    resolved_at: None,
                },
            );
        }
        {
            let session = state.sessions.get_mut(&session_id).expect("session exists");
            for event in &trace_events {
                push_event(session, event.clone());
            }
            session.logs.push(validation_log.clone());
            trim_session(session);
        }
        let resume_snapshot = request.resume_snapshot.clone();
        let task = TaskState {
            id: task_id.clone(),
            session_id: session_id.clone(),
            generation,
            running: confirmation_id.is_none(),
            done: false,
            stopped: false,
            success: false,
            progress: if confirmation_id.is_some() { 0 } else { 1 },
            message: if confirmation_id.is_some() {
                "Retest is waiting for user confirmation".to_string()
            } else {
                "Retest task started".to_string()
            },
            source_file: source_path.to_string_lossy().to_string(),
            logs: vec![validation_log],
            trace_events: trace_events.clone(),
            resume_snapshot: resume_snapshot.clone(),
            result: confirmation_id.as_ref().map(|confirmation_id| {
                json!({
                    "success": false,
                    "message": "Retest is waiting for user confirmation",
                    "source_file": source_path.to_string_lossy(),
                    "confirmation_id": confirmation_id,
                    "manual_test_required": false,
                    "resume_snapshot": resume_snapshot,
                })
            }),
            error: None,
            created_at: now_ms(),
            finished_at: None,
        };
        state.tasks.insert(task_id.clone(), task);
        persist_locked(&self.inner, &state)?;
        let initial = task_response(
            state.tasks.get(&task_id).expect("task inserted"),
            confirmation_id.is_none(),
            false,
        );
        drop(state);
        if confirmation_id.is_none() {
            self.spawn_retest_worker(
                task_id.clone(),
                session_id.clone(),
                generation,
                source_path,
                request,
                valid_container,
            );
        }
        self.publish_session_event(&session_id, Some(&task_id), Some(generation));
        Ok(initial)
    }

    fn spawn_retest_worker(
        &self,
        task_id: String,
        session_id: String,
        generation: u64,
        source_path: PathBuf,
        request: RunOneStartRequest,
        format: &'static str,
    ) {
        let runtime = self.clone();
        thread::Builder::new()
            .name(format!("koi-rust-retest-{task_id}"))
            .spawn(move || {
                let result = execute_native_retest(
                    &runtime,
                    &session_id,
                    generation,
                    &source_path,
                    &request,
                    format,
                );
                runtime.finish_retest_task(&task_id, &session_id, generation, result);
            })
            .ok();
    }

    fn finish_retest_task(
        &self,
        task_id: &str,
        session_id: &str,
        generation: u64,
        result: Result<Value, String>,
    ) {
        let mut state = self.lock_state();
        let Some(task_snapshot) = state.tasks.get(task_id) else {
            return;
        };
        let Some(session_snapshot) = state.sessions.get(session_id) else {
            return;
        };
        if task_snapshot.generation != generation
            || session_snapshot.generation != generation
            || session_snapshot.stopped
            || task_snapshot.stopped
        {
            return;
        }
        let success = result
            .as_ref()
            .ok()
            .and_then(|value| value.get("success"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let message = result
            .as_ref()
            .ok()
            .and_then(|value| value.get("message"))
            .and_then(Value::as_str)
            .unwrap_or("Rust retest failed")
            .to_string();
        let error = result.as_ref().err().cloned();
        let result_value = result.ok();
        {
            let task = state.tasks.get_mut(task_id).expect("task still exists");
            task.running = false;
            task.done = true;
            task.success = success;
            task.progress = if success { 100 } else { 0 };
            task.message = message.clone();
            task.error = error;
            task.result = result_value.clone();
            task.finished_at = Some(now_ms());
        }
        if let Some(session) = state.sessions.get_mut(session_id) {
            session.running = false;
            session.status = if success { "completed" } else { "failed" }.to_string();
            session.message = message.clone();
            if let Some(result) = result_value.as_ref() {
                if let Some(snapshot) = result.get("resume_snapshot") {
                    session.resume_snapshot = Some(snapshot.clone());
                }
                if let Some(events) = result.get("trace_events").and_then(Value::as_array) {
                    for event in events {
                        push_event(session, event.clone());
                    }
                }
                if let Some(logs) = result.get("logs").and_then(Value::as_array) {
                    for log in logs.iter().filter_map(Value::as_str) {
                        session.logs.push(truncate(log, 2_000));
                    }
                }
            }
            trim_session(session);
        }
        let _ = persist_locked(&self.inner, &state);
        drop(state);
        self.publish_session_event(session_id, Some(task_id), Some(generation));
    }

    fn retest_run_one_status(&self, payload: &Value) -> Result<Value, String> {
        let request: TaskStatusRequest = parse_payload(payload)?;
        let task_id = required_text(&request.task_id, "task_id")?;
        let state = self.lock_state();
        let Some(task) = state.tasks.get(&task_id) else {
            return Ok(json!({
                "success": false,
                "task_id": task_id,
                "running": false,
                "done": true,
                "message": "Retest task not found or expired",
                "logs": [],
                "trace_events": [],
            }));
        };
        Ok(task_response_with_offsets(
            task,
            request.log_offset,
            request.trace_event_offset,
        ))
    }

    fn retest_run_one_stop(&self, payload: &Value) -> Result<Value, String> {
        let request: TaskStatusRequest = parse_payload(payload)?;
        let task_id = required_text(&request.task_id, "task_id")?;
        let mut state = self.lock_state();
        let (session_id, old_snapshot, source_file) = {
            let task = state
                .tasks
                .get_mut(&task_id)
                .ok_or_else(|| "Retest task not found or expired".to_string())?;
            task.running = false;
            task.done = true;
            task.stopped = true;
            task.success = false;
            task.message = "Retest stopped; resume snapshot preserved".to_string();
            task.error = None;
            task.finished_at = Some(now_ms());
            (
                task.session_id.clone(),
                task.resume_snapshot.clone(),
                task.source_file.clone(),
            )
        };
        let generation = if let Some(session) = state.sessions.get_mut(&session_id) {
            let generation = begin_generation(session);
            session.running = false;
            session.stopped = true;
            session.status = "stopped".to_string();
            session.message = "Retest stopped; resume snapshot preserved".to_string();
            session.resume_snapshot = old_snapshot.clone();
            push_event(
                session,
                make_event("status", "Retest stopped", &source_file, "warn", generation),
            );
            Some(generation)
        } else {
            None
        };
        let task = state
            .tasks
            .get(&task_id)
            .expect("task remains available")
            .clone();
        persist_locked(&self.inner, &state)?;
        self.publish_session_event(&session_id, Some(&task_id), generation);
        let mut response = task_response(&task, false, true);
        response["resume_snapshot"] = old_snapshot.unwrap_or(Value::Null);
        if let Some(generation) = generation {
            response["generation"] = json!(generation);
        }
        Ok(response)
    }

    fn retest_confirmation(&self, payload: &Value) -> Result<Value, String> {
        let request: ConfirmationRequest = parse_payload(payload)?;
        let confirmation_id = required_text(&request.confirmation_id, "confirmation_id")?;
        let decision = normalize_decision(&request.decision)?;
        let mut state = self.lock_state();
        let confirmation = state
            .confirmations
            .get(&confirmation_id)
            .cloned()
            .ok_or_else(|| "confirmation request not found or expired".to_string())?;
        if !request.session_id.trim().is_empty() && request.session_id != confirmation.session_id {
            return Err("confirmation does not belong to session_id".to_string());
        }
        if confirmation.resolved_at.is_some() {
            return Err("confirmation request has already been resolved".to_string());
        }
        let session_id = confirmation.session_id.clone();
        let generation = confirmation.generation;
        let task_id = required_text(&confirmation.task_id, "persisted confirmation task_id")?;
        let source_file = required_text(
            &confirmation.source_file,
            "persisted confirmation source_file",
        )?;
        let session = state
            .sessions
            .get(&session_id)
            .ok_or_else(|| "confirmation session no longer exists".to_string())?;
        if session.generation != generation || session.stopped {
            return Err("confirmation belongs to an inactive generation".to_string());
        }
        let task = state
            .tasks
            .get(&task_id)
            .ok_or_else(|| "confirmation task no longer exists".to_string())?;
        if task.session_id != session_id
            || task.generation != generation
            || task.source_file != source_file
        {
            return Err("confirmation task context does not match persisted state".to_string());
        }
        if task.done || task.stopped || task.running {
            return Err("confirmation task is no longer awaiting a decision".to_string());
        }

        let worker_context = if decision == "approve" {
            let start_request = confirmation.request.clone().ok_or_else(|| {
                "confirmation cannot resume because its persisted request is unavailable"
                    .to_string()
            })?;
            let source_path = PathBuf::from(&source_file);
            validate_word_input(&source_path)?;
            let format = inspect_word_signature(&source_path)?;
            Some((source_path, start_request, format))
        } else {
            None
        };
        let resume_snapshot = task.resume_snapshot.clone();
        let message = if decision == "approve" {
            format!("Rust retest approved and started: {source_file}")
        } else {
            "Retest confirmation rejected; resume snapshot preserved".to_string()
        };

        {
            let confirmation = state
                .confirmations
                .get_mut(&confirmation_id)
                .expect("confirmation remains available");
            confirmation.decision = decision.to_string();
            confirmation.note = truncate(&request.note, 2_000);
            confirmation.resolved_at = Some(now_ms());
        }
        {
            let task = state
                .tasks
                .get_mut(&task_id)
                .expect("task remains available");
            task.running = decision == "approve";
            task.done = decision == "reject";
            task.stopped = false;
            task.success = false;
            task.progress = if decision == "approve" { 1 } else { 0 };
            task.message = message.clone();
            task.error = None;
            task.finished_at = (decision == "reject").then(now_ms);
            task.result = if decision == "reject" {
                Some(json!({
                    "success": false,
                    "rejected": true,
                    "message": message,
                    "source_file": source_file,
                    "resume_snapshot": resume_snapshot,
                }))
            } else {
                None
            };
        }
        {
            let session = state
                .sessions
                .get_mut(&session_id)
                .expect("session remains available");
            session.running = decision == "approve";
            session.stopped = false;
            session.status = if decision == "approve" {
                "running"
            } else {
                "rejected"
            }
            .to_string();
            session.message = message.clone();
            if decision == "reject" {
                if let Some(snapshot) = resume_snapshot.as_ref() {
                    session.resume_snapshot = Some(snapshot.clone());
                }
            }
            push_event(
                session,
                make_event(
                    "confirmation",
                    "Confirmation resolved",
                    &format!("{decision}: {source_file}"),
                    if decision == "approve" { "ok" } else { "warn" },
                    generation,
                ),
            );
            trim_session(session);
        }
        persist_locked(&self.inner, &state)?;
        let response = json!({
            "success": true,
            "confirmation_id": confirmation_id,
            "decision": decision,
            "session_id": session_id,
            "task_id": task_id,
            "source_file": source_file,
            "generation": generation,
            "running": decision == "approve",
            "done": decision == "reject",
            "rejected": decision == "reject",
            "resume_snapshot": resume_snapshot,
        });
        drop(state);
        if let Some((source_path, start_request, format)) = worker_context {
            self.spawn_retest_worker(
                task_id.clone(),
                session_id.clone(),
                generation,
                source_path,
                start_request,
                format,
            );
        }
        self.publish_session_event(&session_id, Some(&task_id), Some(generation));
        Ok(response)
    }

    fn retest_agent_start(&self, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
        let request: AgentStartRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "retest", self);
        if request.one_click_queue {
            let target = request.target_dir.as_deref().unwrap_or_default();
            let target_path = expand_user(Path::new(target), &self.home_dir);
            if target.trim().is_empty() || !target_path.is_dir() {
                return Ok(json!({
                    "success": false,
                    "session_id": session_id,
                    "running": false,
                    "blocked": false,
                    "message": format!("Target directory does not exist: {}", target_path.display()),
                    "logs": [],
                }));
            }
        }
        let mut message_payload = payload.clone();
        if let Some(object) = message_payload.as_object_mut() {
            object.insert("session_id".to_string(), Value::String(session_id));
            if request.message.trim().is_empty() {
                object.insert(
                    "message".to_string(),
                    Value::String(
                        "Start the Rust retest queue and preserve exact file evidence.".to_string(),
                    ),
                );
            }
        }
        let mut response = self.agent_message(&message_payload, config, true)?;
        response["generate_reports"] = Value::Bool(request.generate_reports);
        response["force_resume"] = Value::Bool(request.force_resume);
        response["one_click_queue"] = Value::Bool(request.one_click_queue);
        Ok(response)
    }

    fn retest_agent_status(&self, payload: &Value) -> Result<Value, String> {
        let request: SessionRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "retest", self);
        let mut state = self.lock_state();
        let session = ensure_session(
            &mut state,
            &session_id,
            "retest",
            self.workspace_root(payload),
        );
        let response = agent_retest_response(session, session.generation);
        persist_locked(&self.inner, &state)?;
        Ok(response)
    }

    fn retest_agent_stop(&self, payload: &Value) -> Result<Value, String> {
        let request: SessionRequest = parse_payload(payload)?;
        let session_id = required_or_new(&request.session_id, "retest", self);
        if !self.lock_state().sessions.contains_key(&session_id) {
            let mut state = self.lock_state();
            ensure_session(
                &mut state,
                &session_id,
                "retest",
                self.workspace_root(payload),
            );
            persist_locked(&self.inner, &state)?;
        }
        self.stop_session(&session_id, "retest")
    }

    fn agent_chat(&self, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
        let request: AgentMessageRequest = parse_payload(payload)?;
        let message = request.message.trim();
        if message.is_empty() {
            return Err("message is required".to_string());
        }
        let mut response = self.agent_message(payload, config, true)?;
        if response.get("reply").is_none() || response["reply"] == Value::Null {
            response["reply"] = response
                .get("final_message")
                .cloned()
                .unwrap_or_else(|| Value::String(String::new()));
        }
        response["streaming"] = Value::Bool(false);
        Ok(response)
    }

    fn session_compact(&self, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
        let request: CompactRequest = parse_payload(payload)?;
        let session_id = required_text(&request.session_id, "session_id")?;
        let (generation, event_count, log_count) = {
            let state = self.lock_state();
            let session = state
                .sessions
                .get(&session_id)
                .ok_or_else(|| "session not found".to_string())?;
            (session.generation, session.events.len(), session.logs.len())
        };
        let memory = request
            .local_memory
            .trim()
            .chars()
            .take(16_000)
            .collect::<String>();
        let frontend_context = request
            .frontend_context
            .as_ref()
            .map(|value| sanitize_value(value, 0))
            .unwrap_or(Value::Null);
        let compact_stats = request
            .compact_stats
            .as_ref()
            .map(|value| sanitize_value(value, 0))
            .unwrap_or(Value::Null);
        let recent_events = request
            .recent_events
            .as_ref()
            .map(|values| {
                values
                    .iter()
                    .rev()
                    .take(80)
                    .rev()
                    .map(|value| sanitize_value(value, 0))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let recent_logs = request
            .logs
            .as_ref()
            .map(|values| {
                values
                    .iter()
                    .rev()
                    .take(80)
                    .rev()
                    .map(|value| truncate(value, 800))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let local_checkpoint = json!({
            "session_id": session_id,
            "generation": generation,
            "event_count": event_count,
            "log_count": log_count,
            "local_memory": memory,
            "compact_stats": compact_stats,
        });
        let model_input = json!({
            "session_id": session_id,
            "local_deterministic_memory": memory,
            "frontend_context": frontend_context,
            "compact_stats": compact_stats,
            "recent_events": recent_events,
            "recent_logs": recent_logs,
            "required_schema": {
                "memory_markdown": "complete resumable Markdown memory",
                "brief": "one sentence summary",
                "warning": "missing information or risk, otherwise empty",
                "confidence": "high|medium|low"
            }
        });
        const SYSTEM: &str = "You compact a KOI security-retest session into resumable memory. Use only supplied evidence, preserve exact file paths and structured checkpoints, and return one JSON object with memory_markdown, brief, warning, and confidence. Never infer a completed test or report.";

        let completion = model_client::complete_json(config, payload, SYSTEM, &model_input);
        match completion {
            Ok(completion) => {
                let memory_markdown = completion
                    .json
                    .get("memory_markdown")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| "model response omitted memory_markdown".to_string())?
                    .chars()
                    .take(24_000)
                    .collect::<String>();
                let brief = completion
                    .json
                    .get("brief")
                    .and_then(Value::as_str)
                    .map(|value| truncate(value, 1_200))
                    .unwrap_or_default();
                let warning = completion
                    .json
                    .get("warning")
                    .and_then(Value::as_str)
                    .map(|value| truncate(value, 1_200))
                    .unwrap_or_default();
                let confidence = completion
                    .json
                    .get("confidence")
                    .and_then(Value::as_str)
                    .filter(|value| matches!(*value, "high" | "medium" | "low"))
                    .unwrap_or("medium")
                    .to_string();
                let provider = completion.provider;
                let model = completion.model;
                let _model_output_length = completion.content.len();
                let mut state = self.lock_state();
                let session = state
                    .sessions
                    .get_mut(&session_id)
                    .ok_or_else(|| "session not found".to_string())?;
                if session.generation != generation || session.stopped {
                    return Ok(json!({
                        "success": false,
                        "message": "Compaction result discarded because the session generation changed",
                        "ai_compacted": false,
                        "compact_failed": true,
                        "error_code": "stale_generation",
                        "generation": generation,
                        "current_generation": session.generation,
                    }));
                }
                let snapshot = json!({
                    "session_id": session_id,
                    "generation": generation,
                    "memory_markdown": memory_markdown,
                    "brief": brief,
                    "warning": warning,
                    "confidence": confidence,
                    "local_checkpoint": local_checkpoint,
                });
                session.resume_snapshot = Some(snapshot.clone());
                session.status = "compacted".to_string();
                session.message = "AI semantic compaction completed".to_string();
                push_event(
                    session,
                    make_event("status", "Session compacted", &brief, "ok", generation),
                );
                trim_session(session);
                persist_locked(&self.inner, &state)?;
                self.publish_session_event(&session_id, None, Some(generation));
                Ok(json!({
                    "success": true,
                    "message": "AI semantic compaction completed",
                    "ai_compacted": true,
                    "memory_markdown": memory_markdown,
                    "brief": brief,
                    "warning": warning,
                    "confidence": confidence,
                    "provider": provider,
                    "model": model,
                    "model_call_started": true,
                    "failure_stage": "",
                    "session_id": session_id,
                    "generation": generation,
                    "resume_snapshot": snapshot,
                }))
            }
            Err(error) => {
                let mut state = self.lock_state();
                let session = state
                    .sessions
                    .get_mut(&session_id)
                    .ok_or_else(|| "session not found".to_string())?;
                let stale = session.generation != generation || session.stopped;
                let snapshot = if stale {
                    session.resume_snapshot.clone()
                } else {
                    session.resume_snapshot = Some(local_checkpoint);
                    session.status = "compact_checkpoint_saved".to_string();
                    session.message =
                        "Local checkpoint saved after AI compaction failure".to_string();
                    push_event(
                        session,
                        make_event(
                            "status",
                            "Local checkpoint saved",
                            &error,
                            "warn",
                            generation,
                        ),
                    );
                    trim_session(session);
                    session.resume_snapshot.clone()
                };
                if !stale {
                    persist_locked(&self.inner, &state)?;
                    self.publish_session_event(&session_id, None, Some(generation));
                }
                Ok(json!({
                    "success": false,
                    "message": format!("AI semantic compaction failed: {error}"),
                    "ai_compacted": false,
                    "compact_failed": true,
                    "blocked_stage": "session_compaction",
                    "blocked_title": "AI semantic compaction unavailable",
                    "failure_stage": "model_request",
                    "model_call_started": false,
                    "session_id": session_id,
                    "generation": generation,
                    "resume_snapshot": snapshot,
                    "error_code": if stale { "stale_generation" } else { "model_request_failed" },
                }))
            }
        }
    }

    fn stop_session(&self, session_id: &str, kind: &str) -> Result<Value, String> {
        let mut state = self.lock_state();
        let (generation, message, cancelled_operations) = {
            let session = state
                .sessions
                .get_mut(session_id)
                .ok_or_else(|| "session not found".to_string())?;
            if session.kind != kind {
                return Err("session kind mismatch".to_string());
            }
            let generation = begin_generation(session);
            session.running = false;
            session.stopped = true;
            session.status = "stopped".to_string();
            session.message = if kind == "agent" {
                "Agent stopped"
            } else {
                "Retest stopped; resume snapshot preserved"
            }
            .to_string();
            for operation in session.operations.values_mut() {
                if !is_terminal_operation(&operation.status) {
                    operation.status = "cancelled".to_string();
                    operation.finished_at = Some(now_ms());
                }
            }
            push_event(
                session,
                make_event(
                    "status",
                    &session.message,
                    "generation invalidated",
                    "warn",
                    generation,
                ),
            );
            trim_session(session);
            (
                generation,
                session.message.clone(),
                session.operations.len(),
            )
        };
        for task in state
            .tasks
            .values_mut()
            .filter(|task| task.session_id == session_id && !task.done)
        {
            task.running = false;
            task.done = true;
            task.stopped = true;
            task.success = false;
            task.message = message.clone();
            task.finished_at = Some(now_ms());
        }
        let snapshot = session_snapshot(state.sessions.get(session_id).expect("session exists"));
        persist_locked(&self.inner, &state)?;
        self.publish_session_event(session_id, None, Some(generation));
        Ok(json!({
            "success": true,
            "session_id": session_id,
            "message": message,
            "stopped": true,
            "running": false,
            "generation": generation,
            "cancelled_operations": cancelled_operations,
            "agent_session": snapshot,
        }))
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, PersistedState> {
        self.inner
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn publish_model_delta(&self, session_id: &str, generation: u64, delta: &str) -> bool {
        let delta = delta.trim_end_matches('\0');
        if delta.is_empty() {
            return true;
        }
        let mut state = self.lock_state();
        let Some(session) = state.sessions.get_mut(session_id) else {
            return false;
        };
        if session.generation != generation || session.stopped {
            return false;
        }
        let event = make_event("token", "Agent token", delta, "info", generation);
        push_event(session, event.clone());
        if persist_locked(&self.inner, &state).is_err() {
            return false;
        }
        drop(state);
        self.publish_trace_event(session_id, None, &event);
        true
    }

    fn session_id_or_new(&self, requested: &str, kind: &str) -> String {
        if requested.trim().is_empty() {
            format!("{kind}-{}", NEXT_LOCAL_ID.fetch_add(1, Ordering::Relaxed))
        } else {
            requested.trim().to_string()
        }
    }

    fn workspace_root(&self, payload: &Value) -> String {
        payload
            .get("target_dir")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .map(|value| {
                expand_user(Path::new(value), &self.home_dir)
                    .to_string_lossy()
                    .to_string()
            })
            .unwrap_or_else(|| self.home_dir.to_string_lossy().to_string())
    }

    fn session_auto_approve(&self, session_id: &str) -> bool {
        self.lock_state()
            .sessions
            .get(session_id)
            .map(|session| session.auto_approve)
            .unwrap_or(true)
    }

    fn publish_session_event(
        &self,
        session_id: &str,
        task_id: Option<&str>,
        generation: Option<u64>,
    ) {
        let event = json!({
            "type": "retest_trace_event",
            "session_id": session_id,
            "task_id": task_id.unwrap_or(""),
            "event": {
                "id": format!("state-{}", now_ms()),
                "type": "status",
                "title": "Native state updated",
                "content": "",
                "tone": "info",
                "generation": generation.unwrap_or(0),
            }
        });
        self.inner.event_bus.publish(event.to_string());
    }

    fn publish_trace_event(&self, session_id: &str, task_id: Option<&str>, event: &Value) {
        self.inner.event_bus.publish(
            json!({
                "type": "retest_trace_event",
                "session_id": session_id,
                "task_id": task_id.unwrap_or(""),
                "event": event,
            })
            .to_string(),
        );
    }

    #[cfg(test)]
    pub(crate) fn apply_task_result_for_test(
        &self,
        task_id: &str,
        generation: u64,
        result: Value,
    ) -> bool {
        let mut state = self.lock_state();
        let accepted = apply_task_result_locked(&mut state, task_id, generation, result);
        if accepted {
            let _ = persist_locked(&self.inner, &state);
        }
        accepted
    }

    #[cfg(test)]
    pub(crate) fn create_running_task_for_test(&self, session_id: &str) -> (String, u64) {
        let mut state = self.lock_state();
        let generation = {
            let session = ensure_session(
                &mut state,
                session_id,
                "retest",
                self.home_dir.to_string_lossy().to_string(),
            );
            session.running = true;
            session.stopped = false;
            begin_generation(session)
        };
        let task_id = next_id(&mut state, "task");
        state.tasks.insert(
            task_id.clone(),
            TaskState {
                id: task_id.clone(),
                session_id: session_id.to_string(),
                generation,
                running: true,
                done: false,
                stopped: false,
                success: false,
                progress: 10,
                message: "running".to_string(),
                source_file: String::new(),
                logs: Vec::new(),
                trace_events: Vec::new(),
                resume_snapshot: Some(json!({"stage":"execution","generation":generation})),
                result: None,
                error: None,
                created_at: now_ms(),
                finished_at: None,
            },
        );
        persist_locked(&self.inner, &state).expect("persist test task");
        (task_id, generation)
    }
}

fn execute_native_retest(
    runtime: &NativeRuntime,
    session_id: &str,
    generation: u64,
    source_path: &Path,
    request: &RunOneStartRequest,
    format: &str,
) -> Result<Value, String> {
    let document_text = extract_word_text(source_path)?;
    let urls = extract_http_urls(&document_text);
    let mut logs = vec![format!("Rust retest started: {}", source_path.display())];
    let mut trace_events = vec![make_event(
        "status",
        "Word notice parsed",
        &format!("{} URL(s) extracted", urls.len()),
        "info",
        generation,
    )];
    let mut observations = Vec::new();
    let client = BlockingHttpClient::builder()
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(12))
        .redirect(RedirectPolicy::none())
        .user_agent("KOI/4.0.0 Rust retest")
        .build()
        .map_err(|error| format!("create Rust retest HTTP client failed: {error}"))?;
    for (index, url) in urls.iter().enumerate() {
        if !generation_active(runtime, session_id, generation) {
            return Ok(json!({
                "success": false,
                "stopped": true,
                "message": "Retest stopped; resume snapshot preserved",
                "source_file": source_path,
                "urls": urls,
                "retest_results": observations,
                "resume_snapshot": {"source_file":source_path,"valid_urls":urls,"next_url_index":index,"retest_results":observations},
                "logs": logs,
                "trace_events": trace_events,
            }));
        }
        let observation = match client.get(url).send() {
            Ok(response) => {
                let status = response.status().as_u16();
                let headers = response
                    .headers()
                    .iter()
                    .filter_map(|(name, value)| {
                        value.to_str().ok().map(|value| {
                            (
                                name.as_str().to_string(),
                                Value::String(truncate(value, 500)),
                            )
                        })
                    })
                    .collect::<Map<String, Value>>();
                let mut bytes = Vec::new();
                response
                    .take(20 * 1024 + 1)
                    .read_to_end(&mut bytes)
                    .map_err(|error| format!("read response failed: {error}"))?;
                let truncated = bytes.len() > 20 * 1024;
                bytes.truncate(20 * 1024);
                let body = String::from_utf8_lossy(&bytes).to_string();
                let lower = body.to_ascii_lowercase();
                let markers = [
                    ("swagger", "swagger_api"),
                    ("openapi", "swagger_api"),
                    ("index of /", "directory_listing"),
                    ("parent directory", "directory_listing"),
                    ("phpinfo()", "phpinfo"),
                    (".env", "sensitive_file"),
                ];
                let signatures = markers
                    .iter()
                    .filter(|(marker, _)| lower.contains(marker))
                    .map(|(_, label)| Value::String((*label).to_string()))
                    .collect::<Vec<_>>();
                Ok::<Value, String>(json!({
                    "url": url,
                    "status_code": status,
                    "success": status < 500,
                    "target_unreachable": false,
                    "headers": headers,
                    "body_excerpt": truncate(&body, 2_000),
                    "body_truncated": truncated,
                    "signatures": signatures,
                    "decisive_reproduction": false,
                }))
            }
            Err(error) => Ok::<Value, String>(json!({
                "url": url,
                "success": false,
                "target_unreachable": true,
                "error": redact_retest_error(&error.to_string()),
                "decisive_reproduction": false,
            })),
        }?;
        logs.push(format!(
            "{} URL {}/{} checked",
            source_path.display(),
            index + 1,
            urls.len()
        ));
        trace_events.push(make_event(
            "tool_result",
            "Rust HTTP observation",
            &format!(
                "{} status={}",
                url,
                observation.get("status_code").unwrap_or(&Value::Null)
            ),
            if observation["success"] == true {
                "ok"
            } else {
                "warn"
            },
            generation,
        ));
        observations.push(observation);
    }

    let tool_root = runtime
        .inner
        .path
        .parent()
        .unwrap_or(Path::new("."))
        .join("retest-tools");
    let external_checks =
        retest_external::run_context_checks(&tool_root, &client, &urls, &document_text, || {
            !generation_active(runtime, session_id, generation)
        });
    let external_risk_count = external_checks
        .iter()
        .map(retest_external::RetestToolResult::risk_count)
        .sum::<usize>();
    let external_failed_count = external_checks
        .iter()
        .filter(|check| !check.success)
        .count();
    for check in &external_checks {
        logs.extend(
            check
                .logs
                .iter()
                .map(|line| truncate(&redact_retest_error(line), 2_000)),
        );
        trace_events.push(make_event(
            "tool_result",
            &format!("Rust retest tool: {}", check.tool_id),
            &truncate(&check.message, 1_000),
            if check.success { "ok" } else { "warn" },
            generation,
        ));
    }
    let external_checks_value = serde_json::to_value(&external_checks)
        .map_err(|error| format!("serialize native retest tool results failed: {error}"))?;

    let mut result_data = json!({
        "engine":"rust_fast_retest",
        "format":format,
        "source_file":source_path,
        "source_file_name":request.source_file_name,
        "round_id":request.round_id,
        "mode":request.mode,
        "urls":urls,
        "retest_results":observations,
        "observation_count":observations.len(),
        "risk_count":external_risk_count,
        "pass_count":observations.iter().filter(|item| item["target_unreachable"] == true).count(),
        "failed_count":external_failed_count,
        "manual_test_required":external_failed_count > 0,
        "external_check_count":external_checks.len(),
        "external_checks":external_checks_value,
    });
    let mut success = true;
    let mut message = format!("Rust retest completed: {} URL(s)", urls.len());
    if request.use_ai {
        let config_path = runtime
            .inner
            .path
            .parent()
            .unwrap_or(Path::new("."))
            .join("config.json");
        let config = ConfigStore::new(config_path);
        let judgement = model_client::complete_json(
            &config,
            &json!({"session_id":session_id}),
            "Judge only the supplied retest observations. Return JSON with summary, risk_count, pass_count, and failed_count. Do not invent vulnerabilities.",
            &result_data,
        );
        match judgement {
            Ok(completion) => {
                if let Some(summary) = completion.json.get("summary") {
                    let summary_text = summary
                        .as_str()
                        .map(str::to_string)
                        .unwrap_or_else(|| summary.to_string());
                    result_data["summary"] = Value::String(truncate(&summary_text, 6_000));
                }
                for key in ["risk_count", "pass_count", "failed_count"] {
                    if let Some(value) = completion.json.get(key).and_then(Value::as_u64) {
                        result_data[key] = json!(value.min(10_000));
                    }
                }
                message = "Rust retest completed with Rust model judgement".to_string();
            }
            Err(error) => {
                success = false;
                message = format!("Rust retest blocked at AI judgement: {error}");
                result_data["blocked_by_ai_config"] = Value::Bool(true);
                result_data["blocked_stage"] = Value::String("judgement".to_string());
            }
        }
    }
    logs.push(message.clone());
    Ok(json!({
        "success":success,
        "message":message,
        "source_file":source_path,
        "manual_test_required":false,
        "summary":result_data.get("summary").cloned().unwrap_or_else(|| Value::String(message.clone())),
        "result_data":result_data,
        "resume_snapshot":{"source_file":source_path,"valid_urls":urls,"next_url_index":urls.len(),"retest_results":observations},
        "trace_events":trace_events,
        "logs":logs,
    }))
}

fn generation_active(runtime: &NativeRuntime, session_id: &str, generation: u64) -> bool {
    let state = runtime.lock_state();
    state
        .sessions
        .get(session_id)
        .is_some_and(|session| session.generation == generation && !session.stopped)
}

fn extract_word_text(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|error| format!("read Word input failed: {error}"))?;
    if bytes.len() > 64 * 1024 * 1024 {
        return Err("Word input exceeds 64 MiB retest limit".to_string());
    }
    let mut archive = ZipArchive::new(Cursor::new(bytes))
        .map_err(|error| format!("Word input is not a valid OOXML package: {error}"))?;
    let mut document = archive
        .by_name("word/document.xml")
        .map_err(|error| format!("Word input lacks word/document.xml: {error}"))?;
    let mut xml = Vec::new();
    document
        .read_to_end(&mut xml)
        .map_err(|error| format!("read Word XML failed: {error}"))?;
    let mut reader = XmlReader::from_reader(Cursor::new(xml));
    reader.config_mut().trim_text(true);
    let mut buffer = Vec::new();
    let mut text = String::new();
    loop {
        match reader.read_event_into(&mut buffer) {
            Ok(XmlEvent::Text(value)) => {
                text.push_str(
                    &value
                        .decode()
                        .map_err(|error| format!("decode Word text failed: {error}"))?,
                );
                text.push('\n');
            }
            Ok(XmlEvent::CData(value)) => {
                text.push_str(
                    &value
                        .decode()
                        .map_err(|error| format!("decode Word text failed: {error}"))?,
                );
                text.push('\n');
            }
            Ok(XmlEvent::Eof) => break,
            Ok(_) => {}
            Err(error) => return Err(format!("parse Word XML failed: {error}")),
        }
        buffer.clear();
    }
    Ok(text)
}

fn extract_http_urls(text: &str) -> Vec<String> {
    let regex = Regex::new(r#"https?://[^\s<>"']+"#).expect("valid URL regex");
    let mut seen = BTreeMap::new();
    for found in regex.find_iter(text) {
        let value = found
            .as_str()
            .trim_end_matches(['。', '，', ',', '.', ';', ')', ']', '}'])
            .to_string();
        if let Ok(parsed) = reqwest::Url::parse(&value) {
            if parsed.host_str().is_some() && matches!(parsed.scheme(), "http" | "https") {
                seen.entry(value).or_insert(());
            }
        }
    }
    seen.into_keys().take(100).collect()
}

fn redact_retest_error(value: &str) -> String {
    value
        .replace("Authorization", "[REDACTED]")
        .replace("Bearer ", "Bearer [REDACTED]")
}

fn build_retest_resume_plan(
    request: &AgentMessageRequest,
    home_dir: &Path,
) -> Result<Option<RetestResumePlan>, String> {
    let frontend = request.frontend_context.as_ref().and_then(Value::as_object);
    let session = frontend
        .and_then(|value| value.get("session"))
        .and_then(Value::as_object);
    let resume_state = session
        .and_then(|value| {
            value
                .get("resumeState")
                .or_else(|| value.get("resume_state"))
        })
        .and_then(Value::as_object);
    let progress = frontend
        .and_then(|value| {
            value
                .get("progressEvidence")
                .or_else(|| value.get("progress_evidence"))
        })
        .and_then(Value::as_object);
    let target_text = request
        .target_dir
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .or_else(|| {
            resume_state
                .and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
        })
        .or_else(|| {
            session
                .and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
        })
        .or_else(|| {
            progress
                .and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
        });
    let Some(target_text) = target_text else {
        return Ok(None);
    };
    let target = expand_user(Path::new(target_text), home_dir);
    if !target.is_dir() {
        return Err(format!(
            "resume target directory does not exist: {}",
            target.display()
        ));
    }
    let target = fs::canonicalize(&target)
        .map_err(|error| format!("canonicalize resume target failed: {error}"))?;
    let listed = retest::list_files(&json!({"target_dir":target}), home_dir)?;
    let source_files = listed
        .get("source_files")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    let source_keys = source_files
        .iter()
        .map(|path| normalized_path_key(path))
        .collect::<Vec<_>>();
    let mut name_indices = BTreeMap::<String, Vec<usize>>::new();
    for (index, source) in source_files.iter().enumerate() {
        if let Some(name) = source.file_name().and_then(|value| value.to_str()) {
            name_indices
                .entry(name.to_lowercase())
                .or_default()
                .push(index);
        }
    }

    let frontend_target = resume_state
        .and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
        .or_else(|| {
            session.and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
        })
        .or_else(|| {
            progress.and_then(|value| value.get("targetDir").or_else(|| value.get("target_dir")))
        })
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let frontend_matches_target = frontend_target
        .map(|value| {
            normalized_path_key(&expand_user(Path::new(value), home_dir))
                == normalized_path_key(&target)
        })
        .unwrap_or(true);
    let mut completed = BTreeMap::<usize, &'static str>::new();
    let disk_report_evidence = listed
        .get("existing_report_evidence")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if request.use_progress_evidence {
        for item in &disk_report_evidence {
            let source = item
                .get("source_file")
                .or_else(|| item.get("sourceFile"))
                .and_then(Value::as_str)
                .unwrap_or_default();
            if let Some(index) =
                match_resume_source(source, &target, &source_files, &source_keys, &name_indices)
            {
                completed.insert(index, "disk_report");
            }
        }
        if frontend_matches_target {
            let completion_items = resume_state
                .and_then(|value| {
                    value
                        .get("completionItems")
                        .or_else(|| value.get("completion_items"))
                })
                .and_then(Value::as_array);
            for item in completion_items.into_iter().flatten() {
                let Some(object) = item.as_object() else {
                    continue;
                };
                let status = object
                    .get("status")
                    .or_else(|| object.get("fixStatus"))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim()
                    .to_ascii_lowercase();
                if !matches!(status.as_str(), "clean" | "risk" | "completed" | "success") {
                    continue;
                }
                let source = object
                    .get("sourceFile")
                    .or_else(|| object.get("source_file"))
                    .or_else(|| object.get("sourceFileName"))
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if let Some(index) =
                    match_resume_source(source, &target, &source_files, &source_keys, &name_indices)
                {
                    completed.entry(index).or_insert("structured_completion");
                }
            }
            let completed_names = progress
                .and_then(|value| {
                    value
                        .get("completedFileNames")
                        .or_else(|| value.get("completed_file_names"))
                })
                .and_then(Value::as_array);
            for name in completed_names
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
            {
                if let Some(index) =
                    match_resume_source(name, &target, &source_files, &source_keys, &name_indices)
                {
                    completed.entry(index).or_insert("structured_filename");
                }
            }
        }
    }

    let current_file_checkpoint = if request.use_progress_evidence && frontend_matches_target {
        resume_state
            .and_then(|value| {
                value
                    .get("currentFile")
                    .or_else(|| value.get("current_file"))
            })
            .and_then(Value::as_object)
            .and_then(|current| {
                let snapshot = current
                    .get("resumeSnapshot")
                    .or_else(|| current.get("resume_snapshot"))
                    .and_then(Value::as_object);
                let stage = current
                    .get("stage")
                    .or_else(|| snapshot.and_then(|value| value.get("stage")))
                    .or_else(|| snapshot.and_then(|value| value.get("resume_stage")))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim()
                    .to_ascii_lowercase();
                if !matches!(
                    stage.as_str(),
                    "execution"
                        | "verification"
                        | "tool"
                        | "judgement"
                        | "result"
                        | "completed"
                        | "judgement_complete"
                        | "report"
                        | "report_generation"
                ) {
                    return None;
                }
                let source = current
                    .get("sourceFile")
                    .or_else(|| current.get("source_file"))
                    .or_else(|| snapshot.and_then(|value| value.get("source_file")))
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let index = match_resume_source(
                    source,
                    &target,
                    &source_files,
                    &source_keys,
                    &name_indices,
                )?;
                Some(json!({
                    "index": index,
                    "stage": stage,
                    "source_file": source_files[index].to_string_lossy(),
                    "resume_snapshot": snapshot.map(|value| sanitize_value(&Value::Object(value.clone()), 0)).unwrap_or(Value::Null),
                }))
            })
    } else {
        None
    };

    let next_index = source_files
        .iter()
        .enumerate()
        .find_map(|(index, _)| (!completed.contains_key(&index)).then_some(index))
        .unwrap_or(source_files.len());
    let completed_source_files = source_files
        .iter()
        .enumerate()
        .filter(|(index, _)| completed.contains_key(index))
        .map(|(_, path)| path.to_string_lossy().to_string())
        .collect::<Vec<_>>();
    let pending_source_files = source_files
        .iter()
        .enumerate()
        .filter(|(index, _)| !completed.contains_key(index))
        .map(|(_, path)| path.to_string_lossy().to_string())
        .collect::<Vec<_>>();
    let completed_count_hint = progress
        .and_then(|value| {
            value
                .get("completedCountHint")
                .or_else(|| value.get("completed_count_hint"))
        })
        .and_then(value_to_usize)
        .unwrap_or_default();
    let next_index_hint = progress
        .and_then(|value| {
            value
                .get("nextIndexHint")
                .or_else(|| value.get("next_index_hint"))
        })
        .and_then(value_to_usize)
        .unwrap_or_default();
    Ok(Some(RetestResumePlan {
        target_dir: target.to_string_lossy().to_string(),
        source_files: source_files
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect(),
        completed_source_files,
        pending_source_files,
        next_index,
        next_source_file: source_files
            .get(next_index)
            .map(|path| path.to_string_lossy().to_string()),
        current_file_checkpoint,
        disk_report_evidence,
        completed_count_hint,
        next_index_hint,
        numeric_hints_used: false,
    }))
}

fn match_resume_source(
    raw: &str,
    target: &Path,
    source_files: &[PathBuf],
    source_keys: &[String],
    name_indices: &BTreeMap<String, Vec<usize>>,
) -> Option<usize> {
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    let path = Path::new(raw);
    let has_path_identity = path.is_absolute() || path.components().count() > 1;
    if has_path_identity {
        let candidate = if path.is_absolute() {
            path.to_path_buf()
        } else {
            target.join(path)
        };
        let key = normalized_path_key(&candidate);
        if let Some(index) = source_keys.iter().position(|source| source == &key) {
            return Some(index);
        }
    }
    let name = path.file_name()?.to_string_lossy().to_lowercase();
    let matches = name_indices.get(&name)?;
    (matches.len() == 1)
        .then_some(matches[0])
        .filter(|index| *index < source_files.len())
}

fn normalized_path_key(path: &Path) -> String {
    let absolute = fs::canonicalize(path).unwrap_or_else(|_| {
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map(|cwd| cwd.join(path))
                .unwrap_or_else(|_| path.to_path_buf())
        }
    });
    let value = absolute.to_string_lossy().replace('\\', "/");
    if cfg!(windows) {
        value.to_lowercase()
    } else {
        value
    }
}

fn value_to_usize(value: &Value) -> Option<usize> {
    value
        .as_u64()
        .and_then(|value| usize::try_from(value).ok())
        .or_else(|| {
            value
                .as_str()
                .and_then(|value| value.trim().parse::<usize>().ok())
        })
}

fn parse_payload<T: DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone())
        .map_err(|error| format!("invalid request payload: {error}"))
}

fn required_text(value: &str, field: &str) -> Result<String, String> {
    let text = value.trim();
    if text.is_empty() {
        Err(format!("{field} is required"))
    } else {
        Ok(text.to_string())
    }
}

fn required_or_new(requested: &str, kind: &str, runtime: &NativeRuntime) -> String {
    runtime.session_id_or_new(requested, kind)
}

fn ensure_session<'a>(
    state: &'a mut PersistedState,
    id: &str,
    kind: &str,
    workspace: String,
) -> &'a mut SessionState {
    state
        .sessions
        .entry(id.to_string())
        .or_insert_with(|| SessionState {
            id: id.to_string(),
            kind: kind.to_string(),
            workspace_root: workspace,
            generation: 0,
            running: false,
            stopped: false,
            status: "idle".to_string(),
            message: String::new(),
            auto_approve: true,
            events: Vec::new(),
            operations: BTreeMap::new(),
            approvals: BTreeMap::new(),
            resume_snapshot: None,
            logs: Vec::new(),
            updated_at: now_ms(),
        })
}

fn begin_generation(session: &mut SessionState) -> u64 {
    session.generation = session.generation.saturating_add(1).max(1);
    session.updated_at = now_ms();
    session.generation
}

fn next_id(state: &mut PersistedState, prefix: &str) -> String {
    state.sequence = state.sequence.saturating_add(1);
    format!("{prefix}-{}-{}", now_ms(), state.sequence)
}

fn operation_may_auto_approve(raw: &Value, session_auto_approve: bool) -> bool {
    if !session_auto_approve {
        return false;
    }
    let tool_name = raw
        .get("tool_name")
        .or_else(|| raw.get("tool"))
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    // Source distributions require a second explicit user decision even when
    // ordinary agent operations are configured for auto approval.
    tool_name != "build_python_probe_wheel"
}

fn create_operation_locked(
    state: &mut PersistedState,
    session_id: &str,
    generation: u64,
    raw: &Value,
    auto_approve: bool,
) -> (String, Option<String>) {
    let operation_id = next_id(state, "operation");
    let approval_id = if auto_approve {
        None
    } else {
        Some(next_id(state, "approval"))
    };
    let object = raw.as_object().cloned().unwrap_or_default();
    let tool_name = object
        .get("tool_name")
        .or_else(|| object.get("tool"))
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let risk = object
        .get("risk")
        .and_then(Value::as_str)
        .unwrap_or("external")
        .to_string();
    let detail = object
        .get("detail")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let operation_status = if auto_approve {
        "approved_pending_executor"
    } else {
        "awaiting_approval"
    };
    let session = state.sessions.get_mut(session_id).expect("session exists");
    session.operations.insert(
        operation_id.clone(),
        OperationState {
            id: operation_id.clone(),
            approval_id: approval_id.clone(),
            tool_name,
            status: operation_status.to_string(),
            risk,
            detail,
            arguments: object
                .get("arguments")
                .or_else(|| object.get("args"))
                .cloned()
                .unwrap_or_else(|| Value::Object(object.clone())),
            continuation_depth: object
                .get("continuation_depth")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                .min(8) as u8,
            generation,
            started_at: now_ms(),
            finished_at: None,
            error: None,
        },
    );
    if let Some(id) = approval_id.as_ref() {
        session.approvals.insert(
            id.clone(),
            ApprovalState {
                id: id.clone(),
                operation_id: Some(operation_id.clone()),
                decision: String::new(),
                note: String::new(),
                generation,
                created_at: now_ms(),
                resolved_at: None,
            },
        );
    }
    (operation_id, approval_id)
}

fn execute_read_only_operation(
    workspace_root: &str,
    operation: &OperationState,
) -> Result<String, String> {
    let arguments = operation.arguments.as_object().cloned().unwrap_or_default();
    let workspace = fs::canonicalize(workspace_root)
        .map_err(|error| format!("workspace root is unavailable: {error}"))?;
    match operation.tool_name.as_str() {
        "workspace_tree" => {
            let requested = arguments.get("path").and_then(Value::as_str).unwrap_or("");
            let root = resolve_workspace_path(&workspace, requested)?;
            if !root.is_dir() {
                return Err("workspace_tree path is not a directory".to_string());
            }
            let limit = arguments
                .get("max_entries")
                .and_then(Value::as_u64)
                .unwrap_or(120)
                .clamp(1, 500) as usize;
            let mut stack = vec![root];
            let mut entries = Vec::new();
            while let Some(directory) = stack.pop() {
                let mut children = fs::read_dir(&directory)
                    .map_err(|error| format!("cannot list {}: {error}", directory.display()))?
                    .filter_map(Result::ok)
                    .collect::<Vec<_>>();
                children.sort_by_key(|entry| entry.file_name());
                for entry in children {
                    if entries.len() >= limit {
                        break;
                    }
                    let path = entry.path();
                    let metadata = match fs::symlink_metadata(&path) {
                        Ok(metadata) if !metadata.file_type().is_symlink() => metadata,
                        _ => continue,
                    };
                    let relative = path
                        .strip_prefix(&workspace)
                        .unwrap_or(&path)
                        .to_string_lossy()
                        .replace('\\', "/");
                    entries.push(format!(
                        "{} {}",
                        if metadata.is_dir() { "dir" } else { "file" },
                        relative
                    ));
                    if metadata.is_dir() {
                        stack.push(path);
                    }
                }
                if entries.len() >= limit {
                    break;
                }
            }
            Ok(entries.join("\n"))
        }
        "read_file" | "summarize_file" => {
            let requested = arguments
                .get("path")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| "path is required".to_string())?;
            let path = resolve_workspace_path(&workspace, requested)?;
            let metadata = fs::metadata(&path)
                .map_err(|error| format!("cannot inspect {}: {error}", path.display()))?;
            if !metadata.is_file() || metadata.len() > 10 * 1024 * 1024 {
                return Err("file must be a regular file no larger than 10 MiB".to_string());
            }
            let max_chars = arguments
                .get("max_chars")
                .and_then(Value::as_u64)
                .unwrap_or(12_000)
                .clamp(1, 100_000) as usize;
            let bytes = fs::read(&path)
                .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
            let text = std::str::from_utf8(&bytes)
                .map_err(|_| "file is not valid UTF-8 text".to_string())?;
            let excerpt = text.chars().take(max_chars).collect::<String>();
            if operation.tool_name == "summarize_file" {
                Ok(format!(
                    "path={}\nbytes={}\nlines={}\n\n{}",
                    path.strip_prefix(&workspace)
                        .unwrap_or(&path)
                        .to_string_lossy(),
                    metadata.len(),
                    text.lines().count(),
                    excerpt
                ))
            } else {
                Ok(excerpt)
            }
        }
        "search_code" => {
            let query = arguments
                .get("query")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| "query is required".to_string())?;
            let requested = arguments.get("path").and_then(Value::as_str).unwrap_or("");
            let root = resolve_workspace_path(&workspace, requested)?;
            let limit = arguments
                .get("max_matches")
                .and_then(Value::as_u64)
                .unwrap_or(80)
                .clamp(1, 200) as usize;
            let mut files = if root.is_file() {
                vec![root]
            } else {
                collect_workspace_files(&root, 5_000)?
            };
            files.sort();
            let mut matches = Vec::new();
            for file in files {
                if matches.len() >= limit {
                    break;
                }
                let metadata = match fs::metadata(&file) {
                    Ok(metadata) if metadata.is_file() && metadata.len() <= 2 * 1024 * 1024 => {
                        metadata
                    }
                    _ => continue,
                };
                let _ = metadata;
                let Ok(text) = fs::read_to_string(&file) else {
                    continue;
                };
                for (index, line) in text.lines().enumerate() {
                    if line.contains(query) {
                        matches.push(format!(
                            "{}:{}:{}",
                            file.strip_prefix(&workspace)
                                .unwrap_or(&file)
                                .to_string_lossy()
                                .replace('\\', "/"),
                            index + 1,
                            truncate(line.trim(), 500)
                        ));
                        if matches.len() >= limit {
                            break;
                        }
                    }
                }
            }
            Ok(matches.join("\n"))
        }
        "inspect_git_diff" => Err(
            "inspect_git_diff requires the reviewed native git executor and is not enabled"
                .to_string(),
        ),
        _ => Err(format!(
            "Rust executor refuses unsupported or mutating tool: {}",
            operation.tool_name
        )),
    }
}

fn resolve_workspace_path(workspace: &Path, requested: &str) -> Result<PathBuf, String> {
    let candidate = if requested.trim().is_empty() {
        workspace.to_path_buf()
    } else {
        let path = Path::new(requested.trim());
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            workspace.join(path)
        }
    };
    let canonical = fs::canonicalize(&candidate)
        .map_err(|error| format!("workspace path does not exist: {error}"))?;
    if !canonical.starts_with(workspace) {
        return Err("workspace path escapes the session root".to_string());
    }
    Ok(canonical)
}

fn collect_workspace_files(root: &Path, limit: usize) -> Result<Vec<PathBuf>, String> {
    let mut files = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let entries = fs::read_dir(&directory)
            .map_err(|error| format!("cannot list {}: {error}", directory.display()))?;
        for entry in entries.filter_map(Result::ok) {
            if files.len() >= limit {
                return Ok(files);
            }
            let path = entry.path();
            let metadata = match fs::symlink_metadata(&path) {
                Ok(metadata) if !metadata.file_type().is_symlink() => metadata,
                _ => continue,
            };
            if metadata.is_dir() {
                stack.push(path);
            } else if metadata.is_file() {
                files.push(path);
            }
        }
    }
    Ok(files)
}

fn find_approval(
    state: &PersistedState,
    approval_id: &str,
) -> Option<(String, Option<String>, u64)> {
    state.sessions.iter().find_map(|(session_id, session)| {
        session.approvals.get(approval_id).map(|approval| {
            (
                session_id.clone(),
                approval.operation_id.clone(),
                approval.generation,
            )
        })
    })
}

fn session_snapshot(session: &SessionState) -> Value {
    json!({
        "id": session.id,
        "session_id": session.id,
        "kind": session.kind,
        "workspace_root": session.workspace_root,
        "generation": session.generation,
        "running": session.running,
        "stopped": session.stopped,
        "status": session.status,
        "message": session.message,
        "auto_approve": session.auto_approve,
        "events": session.events,
        "operations": session.operations,
        "approvals": session.approvals,
        "resume_snapshot": session.resume_snapshot,
        "logs": session.logs,
        "updated_at": session.updated_at,
    })
}

fn agent_status_response(session: &SessionState) -> Value {
    let operations: Vec<Value> = session
        .operations
        .values()
        .map(|operation| json!(operation))
        .collect();
    let running: Vec<Value> = session
        .operations
        .values()
        .filter(|operation| {
            operation.status == "running" || operation.status == "awaiting_approval"
        })
        .map(|operation| json!(operation))
        .collect();
    json!({
        "success": true,
        "session_id": session.id,
        "auto_approve": session.auto_approve,
        "workspace_root": session.workspace_root,
        "running": session.running,
        "status": session.status,
        "generation": session.generation,
        "agent_session": session_snapshot(session),
        "operations": operations,
        "running_operations": running,
    })
}

fn agent_retest_response(session: &SessionState, generation: u64) -> Value {
    json!({
        "success": true,
        "active": true,
        "session_id": session.id,
        "running": session.running,
        "stopped": session.stopped,
        "blocked": session.status == "blocked",
        "message": session.message,
        "status": session.status,
        "progress": if session.running { 1 } else { 0 },
        "generation": generation,
        "logs": session.logs,
        "trace_events": session.events,
        "trace_event_count": session.events.len(),
        "resume_snapshot": session.resume_snapshot,
    })
}

fn stale_generation_response(session_id: &str, generation: u64, current_generation: u64) -> Value {
    json!({
        "success": false,
        "session_id": session_id,
        "running": false,
        "active": true,
        "blocked": false,
        "message": "Model result discarded because the session generation changed",
        "final_message": "Model result discarded because the session generation changed",
        "error_code": "stale_generation",
        "generation": generation,
        "current_generation": current_generation,
    })
}

fn task_response(task: &TaskState, _running: bool, stopped: bool) -> Value {
    let result = task.result.clone().unwrap_or(Value::Null);
    let resume_snapshot = task
        .resume_snapshot
        .clone()
        .or_else(|| result.get("resume_snapshot").cloned())
        .unwrap_or(Value::Null);
    json!({
        "success": task.success,
        "task_id": task.id,
        "session_id": task.session_id,
        "running": task.running,
        "done": task.done,
        "stopped": stopped || task.stopped,
        "progress": task.progress,
        "message": task.message,
        "source_file": task.source_file,
        "manual_test_required": result.get("manual_test_required").cloned().unwrap_or(Value::Bool(false)),
        "blocked_by_ai_config": result.get("result_data").and_then(|value| value.get("blocked_by_ai_config")).cloned().unwrap_or(Value::Bool(false)),
        "resume_snapshot": resume_snapshot,
        "result_data": result.get("result_data").cloned().unwrap_or(Value::Null),
        "result": result,
        "logs": task.logs,
        "log_count": task.logs.len(),
        "trace_events": task.trace_events,
        "trace_event_count": task.trace_events.len(),
        "error": task.error,
        "generation": task.generation,
    })
}

fn task_response_with_offsets(task: &TaskState, log_offset: usize, event_offset: usize) -> Value {
    let mut response = task_response(task, task.running, task.stopped);
    let logs = task
        .logs
        .iter()
        .skip(log_offset.min(task.logs.len()))
        .cloned()
        .collect::<Vec<_>>();
    let events = task
        .trace_events
        .iter()
        .skip(event_offset.min(task.trace_events.len()))
        .cloned()
        .collect::<Vec<_>>();
    response["logs"] = json!(logs);
    response["log_count"] = json!(task.logs.len());
    response["trace_events"] = json!(events);
    response["trace_event_count"] = json!(task.trace_events.len());
    response
}

#[cfg(test)]
fn apply_task_result_locked(
    state: &mut PersistedState,
    task_id: &str,
    generation: u64,
    result: Value,
) -> bool {
    let Some(task) = state.tasks.get_mut(task_id) else {
        return false;
    };
    let Some(session) = state.sessions.get(&task.session_id) else {
        return false;
    };
    if task.generation != generation
        || session.generation != generation
        || session.stopped
        || !task.running
    {
        return false;
    }
    task.running = false;
    task.done = true;
    task.success = result
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    task.message = result
        .get("message")
        .and_then(Value::as_str)
        .unwrap_or("Task completed")
        .to_string();
    task.result = Some(result);
    task.progress = if task.success { 100 } else { task.progress };
    task.finished_at = Some(now_ms());
    true
}

fn is_terminal_operation(status: &str) -> bool {
    matches!(
        status,
        "completed" | "failed" | "rejected" | "cancelled" | "stale"
    )
}

fn push_event(session: &mut SessionState, event: Value) {
    session.events.push(event);
    trim_session(session);
}

fn trim_session(session: &mut SessionState) {
    if session.events.len() > MAX_EVENTS {
        let keep_from = session.events.len() - MAX_EVENTS;
        session.events.drain(0..keep_from);
    }
    if session.logs.len() > MAX_LOGS {
        let keep_from = session.logs.len() - MAX_LOGS;
        session.logs.drain(0..keep_from);
    }
}

fn make_event(event_type: &str, title: &str, content: &str, tone: &str, generation: u64) -> Value {
    json!({
        "id": format!("trace-{}-{}", now_ms(), NEXT_LOCAL_ID.fetch_add(1, Ordering::Relaxed)),
        "type": event_type,
        "title": truncate(title, 500),
        "content": truncate(content, 8_000),
        "tone": tone,
        "timestamp": now_ms(),
        "generation": generation,
    })
}

fn normalize_decision(value: &str) -> Result<&'static str, String> {
    match value.trim().to_ascii_lowercase().as_str() {
        "approve" | "approved" | "allow" | "yes" | "true" | "1" => Ok("approve"),
        "reject" | "rejected" | "deny" | "no" | "false" | "0" => Ok("reject"),
        _ => Err("decision must be approve or reject".to_string()),
    }
}

fn truncate(value: &str, max: usize) -> String {
    value.chars().take(max).collect()
}

fn sanitize_value(value: &Value, depth: usize) -> Value {
    if depth > 6 {
        return Value::String("<depth-limit>".to_string());
    }
    match value {
        Value::Object(values) => Value::Object(
            values
                .iter()
                .map(|(key, value)| {
                    let lowered = key.to_ascii_lowercase();
                    let secret = matches!(
                        lowered.as_str(),
                        "password"
                            | "passwd"
                            | "pwd"
                            | "cookie"
                            | "authorization"
                            | "token"
                            | "api_key"
                            | "x-api-key"
                    );
                    (
                        key.clone(),
                        if secret {
                            Value::String("<redacted>".to_string())
                        } else {
                            sanitize_value(value, depth + 1)
                        },
                    )
                })
                .collect::<Map<String, Value>>(),
        ),
        Value::Array(values) => Value::Array(
            values
                .iter()
                .take(100)
                .map(|value| sanitize_value(value, depth + 1))
                .collect(),
        ),
        Value::String(value) => Value::String(truncate(value, MAX_MESSAGE)),
        _ => value.clone(),
    }
}

fn expand_user(path: &Path, home: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if text == "~" {
        return home.to_path_buf();
    }
    if let Some(rest) = text.strip_prefix("~/").or_else(|| text.strip_prefix("~\\")) {
        return home.join(rest);
    }
    path.to_path_buf()
}

fn validate_word_input(path: &Path) -> Result<(), String> {
    if !path.exists() || !path.is_file() {
        return Err(format!("Word input does not exist: {}", path.display()));
    }
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if extension != "doc" && extension != "docx" {
        return Err(format!("Unsupported Word input extension: .{extension}"));
    }
    Ok(())
}

fn inspect_word_signature(path: &Path) -> Result<&'static str, String> {
    let mut file =
        File::open(path).map_err(|error| format!("failed to read Word input: {error}"))?;
    let mut bytes = [0_u8; 8];
    let count = file
        .read(&mut bytes)
        .map_err(|error| format!("failed to read Word signature: {error}"))?;
    if count >= 2 && bytes[..2] == *b"PK" {
        Ok("docx_zip")
    } else if count >= 4 && bytes[..4] == [0xD0, 0xCF, 0x11, 0xE0] {
        Ok("doc_ole")
    } else {
        Err(format!(
            "Word input has an invalid container signature: {}",
            path.display()
        ))
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or(0)
}

fn load_state(path: &Path) -> Result<PersistedState, String> {
    if !path.exists() {
        return Ok(PersistedState::default());
    }
    let bytes =
        fs::read(path).map_err(|error| format!("failed to read native runtime state: {error}"))?;
    let state: PersistedState = serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid native runtime state: {error}"))?;
    if state.schema_version != STATE_VERSION {
        return Err(format!(
            "unsupported native runtime state version: {}",
            state.schema_version
        ));
    }
    Ok(state)
}

fn persist_locked(inner: &RuntimeInner, state: &PersistedState) -> Result<(), String> {
    let parent = inner
        .path
        .parent()
        .ok_or_else(|| "native runtime state has no parent".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("failed to create native state directory: {error}"))?;
    let bytes = serde_json::to_vec_pretty(state)
        .map_err(|error| format!("failed to encode native state: {error}"))?;
    static NEXT_TEMP: AtomicU64 = AtomicU64::new(1);
    let temp = parent.join(format!(
        ".{}.tmp-{}-{}",
        STATE_FILE,
        std::process::id(),
        NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)
        .map_err(|error| format!("failed to create native state temp file: {error}"))?;
    let result = (|| -> Result<(), String> {
        file.write_all(&bytes)
            .map_err(|error| format!("failed to write native state: {error}"))?;
        file.flush()
            .map_err(|error| format!("failed to flush native state: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("failed to sync native state: {error}"))?;
        drop(file);
        atomic_replace(&temp, &inner.path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        MoveFileExW(
            PCWSTR(source_wide.as_ptr()),
            PCWSTR(destination_wide.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("failed to replace native state: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination)
        .map_err(|error| format!("failed to replace native state: {error}"))
}

fn start_event_server() -> Result<(EventInfo, Arc<EventBus>, Arc<AtomicBool>), String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to bind event stream: {error}"))?;
    listener
        .set_nonblocking(true)
        .map_err(|error| format!("failed to configure event stream: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("failed to read event stream port: {error}"))?
        .port();
    let token = random_token()?;
    let bus = Arc::new(EventBus::new());
    let stop = Arc::new(AtomicBool::new(false));
    let thread_bus = Arc::clone(&bus);
    let thread_stop = Arc::clone(&stop);
    let thread_token = token.clone();
    thread::Builder::new()
        .name("koi-rust-event-stream".to_string())
        .spawn(move || {
            while !thread_stop.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let bus = Arc::clone(&thread_bus);
                        let token = thread_token.clone();
                        let client_stop = Arc::clone(&thread_stop);
                        let _ = thread::Builder::new()
                            .name("koi-rust-event-client".to_string())
                            .spawn(move || handle_websocket(stream, &token, bus, client_stop));
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(25))
                    }
                    Err(_) => break,
                }
            }
        })
        .map_err(|error| format!("failed to start event stream: {error}"))?;
    let host = "127.0.0.1".to_string();
    Ok((
        EventInfo {
            host: host.clone(),
            port,
            ws_url: format!("ws://{host}:{port}/events?token={token}"),
            token,
        },
        bus,
        stop,
    ))
}

fn handle_websocket(mut stream: TcpStream, token: &str, bus: Arc<EventBus>, stop: Arc<AtomicBool>) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut request = Vec::with_capacity(1024);
    let mut one = [0_u8; 1];
    while request.len() < 16 * 1024 {
        match stream.read(&mut one) {
            Ok(0) => return,
            Ok(_) => {
                request.push(one[0]);
                if request.ends_with(b"\r\n\r\n") {
                    break;
                }
            }
            Err(_) => return,
        }
    }
    let text = String::from_utf8_lossy(&request);
    let path = text
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("");
    let expected_path = format!("/events?token={token}");
    if path != expected_path {
        let _ = stream.write_all(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
        return;
    }
    let key = text
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.trim()
                .eq_ignore_ascii_case("Sec-WebSocket-Key")
                .then_some(value.trim())
        })
        .unwrap_or("");
    if key.is_empty() {
        let _ = stream.write_all(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
        return;
    }
    let mut handshake = key.as_bytes().to_vec();
    handshake.extend_from_slice(WS_GUID.as_bytes());
    let accept = base64_encode(&sha1(&handshake));
    let response = format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n");
    if stream.write_all(response.as_bytes()).is_err() {
        return;
    }
    let receiver = bus.subscribe();
    while !stop.load(Ordering::Acquire) {
        match receiver.recv_timeout(Duration::from_millis(250)) {
            Ok(message) => {
                if write_ws_text(&mut stream, &message).is_err() {
                    break;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}

fn write_ws_text(stream: &mut TcpStream, message: &str) -> std::io::Result<()> {
    let bytes = message.as_bytes();
    if bytes.len() < 126 {
        stream.write_all(&[0x81, bytes.len() as u8])?;
    } else if bytes.len() <= u16::MAX as usize {
        stream.write_all(&[0x81, 126])?;
        stream.write_all(&(bytes.len() as u16).to_be_bytes())?;
    } else {
        stream.write_all(&[0x81, 127])?;
        stream.write_all(&(bytes.len() as u64).to_be_bytes())?;
    }
    stream.write_all(bytes)
}

fn random_token() -> Result<String, String> {
    let mut bytes = [0_u8; 24];
    fill_random(&mut bytes)?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

#[cfg(windows)]
fn fill_random(bytes: &mut [u8]) -> Result<(), String> {
    #[link(name = "bcrypt")]
    unsafe extern "system" {
        fn BCryptGenRandom(
            algorithm: *mut std::ffi::c_void,
            buffer: *mut u8,
            length: u32,
            flags: u32,
        ) -> i32;
    }
    let status = unsafe {
        BCryptGenRandom(
            std::ptr::null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            0x00000002,
        )
    };
    if status == 0 {
        Ok(())
    } else {
        Err(format!("BCryptGenRandom failed: 0x{status:08x}"))
    }
}

#[cfg(unix)]
fn fill_random(bytes: &mut [u8]) -> Result<(), String> {
    let mut file = File::open("/dev/urandom")
        .map_err(|error| format!("random source unavailable: {error}"))?;
    file.read_exact(bytes)
        .map_err(|error| format!("random source unavailable: {error}"))
}

#[cfg(not(any(windows, unix)))]
fn fill_random(bytes: &mut [u8]) -> Result<(), String> {
    let mut value = now_ms();
    for byte in bytes.iter_mut() {
        value ^= value.rotate_left(13).wrapping_add(0x9e3779b97f4a7c15);
        *byte = value as u8;
    }
    Ok(())
}

fn base64_encode(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut output = String::new();
    let mut index = 0;
    while index < bytes.len() {
        let a = bytes[index];
        let b = bytes.get(index + 1).copied().unwrap_or(0);
        let c = bytes.get(index + 2).copied().unwrap_or(0);
        output.push(TABLE[(a >> 2) as usize] as char);
        output.push(TABLE[((a & 0x03) << 4 | b >> 4) as usize] as char);
        output.push(if index + 1 < bytes.len() {
            TABLE[((b & 0x0f) << 2 | c >> 6) as usize] as char
        } else {
            '='
        });
        output.push(if index + 2 < bytes.len() {
            TABLE[(c & 0x3f) as usize] as char
        } else {
            '='
        });
        index += 3;
    }
    output
}

fn sha1(input: &[u8]) -> [u8; 20] {
    let mut message = input.to_vec();
    let bit_len = (message.len() as u64).wrapping_mul(8);
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_len.to_be_bytes());
    let mut h = [
        0x67452301_u32,
        0xefcdab89,
        0x98badcfe,
        0x10325476,
        0xc3d2e1f0,
    ];
    for chunk in message.chunks_exact(64) {
        let mut words = [0_u32; 80];
        for (index, word) in words[..16].iter_mut().enumerate() {
            let offset = index * 4;
            *word = u32::from_be_bytes([
                chunk[offset],
                chunk[offset + 1],
                chunk[offset + 2],
                chunk[offset + 3],
            ]);
        }
        for index in 16..80 {
            words[index] =
                (words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16])
                    .rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (index, word) in words.iter().enumerate() {
            let (f, k) = match index {
                0..=19 => ((b & c) | ((!b) & d), 0x5a827999),
                20..=39 => (b ^ c ^ d, 0x6ed9eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1bbcdc),
                _ => (b ^ c ^ d, 0xca62c1d6),
            };
            let temp = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    let mut output = [0_u8; 20];
    for (index, word) in h.iter().enumerate() {
        output[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    output
}

#[cfg(test)]
mod tests {
    use super::super::retest_config;
    use super::*;
    use std::io::{Read, Write};

    fn mock_model_server(
        model_json: Value,
        accepted: Option<mpsc::Sender<()>>,
        response_delay: Duration,
    ) -> (String, thread::JoinHandle<String>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind model mock");
        let address = listener.local_addr().expect("model mock address");
        let content = serde_json::to_string(&model_json).expect("model response JSON");
        let body = json!({"choices":[{"message":{"content":content}}]}).to_string();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept model request");
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .expect("model mock timeout");
            let mut request = Vec::new();
            let mut buffer = [0_u8; 4096];
            loop {
                let count = stream.read(&mut buffer).expect("read model request");
                if count == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..count]);
                let Some(header_end) = request.windows(4).position(|item| item == b"\r\n\r\n")
                else {
                    continue;
                };
                let headers = String::from_utf8_lossy(&request[..header_end + 4]);
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .and_then(|value| value.trim().parse::<usize>().ok())
                    })
                    .unwrap_or(0);
                if request.len() >= header_end + 4 + content_length {
                    break;
                }
            }
            if let Some(sender) = accepted {
                sender.send(()).expect("notify accepted model request");
            }
            thread::sleep(response_delay);
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(), body
            );
            stream
                .write_all(response.as_bytes())
                .expect("write model response");
            String::from_utf8_lossy(&request).to_string()
        });
        (format!("http://{address}/v1"), handle)
    }

    fn mock_streaming_model_server() -> (
        String,
        mpsc::Receiver<()>,
        mpsc::Sender<()>,
        thread::JoinHandle<String>,
    ) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind streaming model mock");
        let address = listener.local_addr().expect("streaming model address");
        let (first_sent, first_received) = mpsc::channel();
        let (release_late, late_released) = mpsc::channel();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept streaming request");
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .expect("streaming mock timeout");
            let mut request = Vec::new();
            let mut buffer = [0_u8; 4096];
            loop {
                let count = stream.read(&mut buffer).expect("read streaming request");
                if count == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..count]);
                let Some(header_end) = request.windows(4).position(|item| item == b"\r\n\r\n")
                else {
                    continue;
                };
                let headers = String::from_utf8_lossy(&request[..header_end + 4]);
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .and_then(|value| value.trim().parse::<usize>().ok())
                    })
                    .unwrap_or(0);
                if request.len() >= header_end + 4 + content_length {
                    break;
                }
            }

            let first = json!({
                "choices": [{"delta": {"content": r#"{"reply":"accepted"#}}]
            });
            let late = json!({
                "choices": [{"delta": {"content": r#"}"#}}]
            });
            let headers = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n";
            stream
                .write_all(headers.as_bytes())
                .expect("write SSE headers");
            stream
                .write_all(format!("data: {first}\r\n\r\n").as_bytes())
                .expect("write first SSE delta");
            stream.flush().expect("flush first SSE delta");
            first_sent.send(()).expect("notify first SSE delta");
            late_released
                .recv_timeout(Duration::from_secs(3))
                .expect("release late SSE delta");
            let _ =
                stream.write_all(format!("data: {late}\r\n\r\ndata: [DONE]\r\n\r\n").as_bytes());
            let _ = stream.flush();
            String::from_utf8_lossy(&request).to_string()
        });
        (
            format!("http://{address}/v1"),
            first_received,
            release_late,
            handle,
        )
    }

    fn mock_model_sequence(responses: Vec<Value>) -> (String, thread::JoinHandle<Vec<String>>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind model sequence mock");
        let address = listener.local_addr().expect("model sequence address");
        let handle = thread::spawn(move || {
            let mut requests = Vec::new();
            for model_json in responses {
                let (mut stream, _) = listener.accept().expect("accept sequence request");
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .expect("sequence timeout");
                let mut request = Vec::new();
                let mut buffer = [0_u8; 4096];
                loop {
                    let count = stream.read(&mut buffer).expect("read sequence request");
                    if count == 0 {
                        break;
                    }
                    request.extend_from_slice(&buffer[..count]);
                    let Some(header_end) = request.windows(4).position(|item| item == b"\r\n\r\n")
                    else {
                        continue;
                    };
                    let headers = String::from_utf8_lossy(&request[..header_end + 4]);
                    let content_length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .and_then(|value| value.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if request.len() >= header_end + 4 + content_length {
                        break;
                    }
                }
                let content = serde_json::to_string(&model_json).expect("sequence JSON");
                let body = json!({"choices":[{"message":{"content":content}}]}).to_string();
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(), body
                );
                stream
                    .write_all(response.as_bytes())
                    .expect("write sequence response");
                requests.push(String::from_utf8_lossy(&request).to_string());
            }
            requests
        });
        (format!("http://{address}/v1"), handle)
    }

    fn configure_model(store: &ConfigStore, base_url: &str) {
        retest_config::dispatch(
            "doc.retest.ai_config.set",
            &json!({
                "profile_id":"default",
                "provider":"openai",
                "base_url":base_url,
                "api_key":"native-runtime-test-secret",
                "model":"mock-model"
            }),
            store,
            Path::new("unused-tools"),
        )
        .expect("configure native model");
    }

    fn runtime(label: &str) -> NativeRuntime {
        let path = std::env::temp_dir().join(format!("koi-native-runtime-{label}-{}", now_ms()));
        NativeRuntime::new(path, std::env::temp_dir()).expect("runtime")
    }

    #[test]
    fn websocket_accept_hash_matches_rfc_example() {
        let digest = sha1(b"dGhlIHNhbXBsZSBub25jZQ==258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
        assert_eq!(base64_encode(&digest), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=");
    }

    #[test]
    fn event_stream_requires_its_random_token() {
        let first = runtime("event-auth-a");
        let second = runtime("event-auth-b");
        assert_ne!(first.inner.event_info.token, second.inner.event_info.token);

        let mut denied = TcpStream::connect(("127.0.0.1", first.inner.event_info.port))
            .expect("connect denied client");
        denied
            .write_all(
                b"GET /events?token=wrong HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n",
            )
            .expect("write denied handshake");
        let mut denied_response = [0_u8; 256];
        let denied_count = denied.read(&mut denied_response).expect("read denial");
        assert!(String::from_utf8_lossy(&denied_response[..denied_count]).contains("403 Forbidden"));

        let mut allowed = TcpStream::connect(("127.0.0.1", first.inner.event_info.port))
            .expect("connect allowed client");
        let request = format!(
            "GET /events?token={} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n",
            first.inner.event_info.token
        );
        allowed
            .write_all(request.as_bytes())
            .expect("write allowed handshake");
        let mut allowed_response = [0_u8; 512];
        let allowed_count = allowed.read(&mut allowed_response).expect("read handshake");
        let response = String::from_utf8_lossy(&allowed_response[..allowed_count]);
        assert!(response.contains("101 Switching Protocols"));
        assert!(response.contains("Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo="));
    }

    #[test]
    fn generation_invalidation_rejects_late_results() {
        let runtime = runtime("generation");
        let config =
            ConfigStore::new(std::env::temp_dir().join(format!("koi-native-config-{}", now_ms())));
        let (task_id, generation) = runtime.create_running_task_for_test("s");
        let stopped = runtime
            .dispatch("doc.retest.agent.stop", &json!({"session_id":"s"}), &config)
            .expect("stop");
        assert!(stopped["generation"].as_u64().unwrap() > generation);
        assert!(!runtime.apply_task_result_for_test(
            &task_id,
            generation,
            json!({"success":true,"message":"late"})
        ));
        let status = runtime
            .dispatch(
                "doc.retest.run_one.status",
                &json!({"task_id":task_id}),
                &config,
            )
            .expect("status");
        assert_eq!(status["stopped"], true);
        assert_eq!(status["result"], Value::Null);
    }

    #[test]
    fn stopped_generation_discards_late_stream_tokens_and_reply() {
        let dir = std::env::temp_dir().join(format!("koi-native-sse-stale-{}", now_ms()));
        let config = Arc::new(ConfigStore::new(dir.join("config.json")));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        let bus_events = runtime.inner.event_bus.subscribe();
        let (base_url, first_received, release_late, server) = mock_streaming_model_server();
        configure_model(&config, &base_url);

        let call_runtime = runtime.clone();
        let call_config = Arc::clone(&config);
        let call = thread::spawn(move || {
            call_runtime
                .dispatch(
                    "doc.agent.message",
                    &json!({"session_id":"stream-stale","message":"stream a JSON reply"}),
                    &call_config,
                )
                .expect("streaming agent response")
        });
        first_received
            .recv_timeout(Duration::from_secs(2))
            .expect("first SSE delta sent");

        let deadline = std::time::Instant::now() + Duration::from_secs(2);
        let first_generation = loop {
            let status = runtime
                .dispatch(
                    "doc.agent.status",
                    &json!({"session_id":"stream-stale"}),
                    &config,
                )
                .expect("streaming status");
            let first_token = status["agent_session"]["events"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|event| {
                    event["type"] == "token" && event["content"] == r#"{"reply":"accepted"#
                });
            if let Some(event) = first_token {
                break event["generation"]
                    .as_u64()
                    .expect("token event generation");
            }
            assert!(
                std::time::Instant::now() < deadline,
                "first SSE token was not published incrementally"
            );
            thread::sleep(Duration::from_millis(10));
        };
        let first_bus_token = loop {
            let message = bus_events
                .recv_timeout(Duration::from_secs(2))
                .expect("first token event broadcast");
            let message: Value = serde_json::from_str(&message).expect("event bus JSON");
            if message["event"]["type"] == "token" {
                break message;
            }
        };
        assert_eq!(first_bus_token["session_id"], "stream-stale");
        assert_eq!(first_bus_token["event"]["generation"], first_generation);
        assert_eq!(first_bus_token["event"]["content"], r#"{"reply":"accepted"#);

        let stopped = runtime
            .dispatch(
                "doc.agent.stop",
                &json!({"session_id":"stream-stale"}),
                &config,
            )
            .expect("stop streaming session");
        assert!(stopped["generation"].as_u64().unwrap() > first_generation);
        release_late.send(()).expect("release late SSE delta");

        let response = call.join().expect("join streaming model call");
        let request = server.join().expect("join streaming model server");
        assert!(request.contains("\"stream\":true"));
        assert_eq!(response["success"], false);
        assert_eq!(response["error_code"], "stale_generation");

        let status = runtime
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"stream-stale"}),
                &config,
            )
            .expect("stopped streaming status");
        let token_events = status["agent_session"]["events"]
            .as_array()
            .expect("session events")
            .iter()
            .filter(|event| event["type"] == "token")
            .collect::<Vec<_>>();
        assert_eq!(token_events.len(), 1);
        assert_eq!(token_events[0]["generation"], first_generation);
        assert_eq!(token_events[0]["content"], r#"{"reply":"accepted"#);
        assert!(!token_events.iter().any(|event| event["content"]
            .as_str()
            .is_some_and(|content| content.contains(" late"))));
        assert!(!status["agent_session"]["events"]
            .as_array()
            .unwrap()
            .iter()
            .any(|event| event["type"] == "chat"));
        assert!(!bus_events.try_iter().any(|message| {
            let message: Value = serde_json::from_str(&message).expect("event bus JSON");
            message["event"]["type"] == "token"
        }));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn agent_state_survives_runtime_restart() {
        let dir = std::env::temp_dir().join(format!("koi-native-persist-{}", now_ms()));
        let config_path = dir.join("config.json");
        let config = ConfigStore::new(config_path);
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        let response = runtime
            .dispatch(
                "doc.agent.auto_approval.set",
                &json!({"session_id":"persisted","enabled":true}),
                &config,
            )
            .expect("set");
        assert_eq!(response["auto_approve"], true);
        drop(runtime);
        let restarted = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("restart");
        let status = restarted
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"persisted"}),
                &config,
            )
            .expect("status");
        assert_eq!(status["auto_approve"], true);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn stop_advances_generation_and_marks_operations_cancelled() {
        let runtime = runtime("stop");
        let config = ConfigStore::new(
            std::env::temp_dir().join(format!("koi-native-stop-config-{}", now_ms())),
        );
        let _ = runtime.dispatch("doc.agent.message", &json!({"session_id":"s","message":"hello","operation":{"tool_name":"run","risk":"external"}}), &config).expect("message");
        let before = runtime
            .dispatch("doc.agent.status", &json!({"session_id":"s"}), &config)
            .expect("status");
        let before_generation = before["generation"].as_u64().unwrap();
        let stopped = runtime
            .dispatch("doc.agent.stop", &json!({"session_id":"s"}), &config)
            .expect("stop");
        assert!(stopped["generation"].as_u64().unwrap() > before_generation);
        assert_eq!(stopped["running"], false);
        assert_eq!(stopped["stopped"], true);
    }

    #[test]
    fn stopped_generation_rejects_pending_approval() {
        let runtime = runtime("approval-generation");
        let config = ConfigStore::new(
            std::env::temp_dir().join(format!("koi-native-approval-config-{}", now_ms())),
        );
        let message = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"approval-session",
                    "message":"request operation",
                    "auto_approve":false,
                    "operation":{"tool_name":"run_retest","risk":"external"}
                }),
                &config,
            )
            .expect("message");
        let approval_id = message["approval_id"].as_str().unwrap().to_string();
        runtime
            .dispatch(
                "doc.agent.stop",
                &json!({"session_id":"approval-session"}),
                &config,
            )
            .expect("stop");
        let error = runtime
            .dispatch(
                "doc.agent.approval.respond",
                &json!({
                    "session_id":"approval-session",
                    "approval_id":approval_id,
                    "decision":"approve"
                }),
                &config,
            )
            .expect_err("stale approval must fail");
        assert!(error.contains("inactive generation"));
    }

    #[test]
    fn session_compaction_uses_rust_model_transport_and_persists_memory() {
        let dir = std::env::temp_dir().join(format!("koi-native-compact-{}", now_ms()));
        let config = ConfigStore::new(dir.join("config.json"));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        runtime
            .dispatch(
                "doc.agent.auto_approval.set",
                &json!({"session_id":"compact-session","enabled":true}),
                &config,
            )
            .expect("create session");
        let (base_url, server) = mock_model_server(
            json!({
                "memory_markdown":"# KOI session\n\nExact checkpoint retained.",
                "brief":"Checkpoint retained",
                "warning":"",
                "confidence":"high"
            }),
            None,
            Duration::ZERO,
        );
        configure_model(&config, &base_url);
        let response = runtime
            .dispatch(
                "doc.retest.session.compact",
                &json!({
                    "session_id":"compact-session",
                    "local_memory":"exact-file.docx completed",
                    "frontend_context":{"currentFile":"exact-file.docx","cookie":"must-not-leak"},
                    "recent_events":[{"type":"status","path":"exact-file.docx"}],
                    "logs":["verified exact-file.docx"]
                }),
                &config,
            )
            .expect("compact session");
        let request = server.join().expect("join model server");
        assert_eq!(response["success"], true);
        assert_eq!(response["ai_compacted"], true);
        assert_eq!(response["confidence"], "high");
        assert!(response["memory_markdown"]
            .as_str()
            .unwrap()
            .contains("Exact checkpoint"));
        assert!(request.contains("POST /v1/chat/completions HTTP/1.1"));
        assert!(request.contains("exact-file.docx"));
        assert!(!request.contains("must-not-leak"));

        drop(runtime);
        let restarted = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("restart");
        let status = restarted
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"compact-session"}),
                &config,
            )
            .expect("status");
        assert!(
            status["agent_session"]["resume_snapshot"]["memory_markdown"]
                .as_str()
                .unwrap()
                .contains("Exact checkpoint")
        );
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn session_compaction_discards_model_result_after_stop_generation() {
        let dir = std::env::temp_dir().join(format!("koi-native-compact-stale-{}", now_ms()));
        let config = Arc::new(ConfigStore::new(dir.join("config.json")));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        runtime
            .dispatch(
                "doc.agent.auto_approval.set",
                &json!({"session_id":"stale-compact","enabled":false}),
                &config,
            )
            .expect("create session");
        let (accepted_tx, accepted_rx) = mpsc::channel();
        let (base_url, server) = mock_model_server(
            json!({
                "memory_markdown":"late memory must be discarded",
                "brief":"late",
                "warning":"",
                "confidence":"high"
            }),
            Some(accepted_tx),
            Duration::from_millis(100),
        );
        configure_model(&config, &base_url);
        let compact_runtime = runtime.clone();
        let compact_config = Arc::clone(&config);
        let compact = thread::spawn(move || {
            compact_runtime
                .dispatch(
                    "doc.retest.session.compact",
                    &json!({"session_id":"stale-compact","local_memory":"before stop"}),
                    &compact_config,
                )
                .expect("compact response")
        });
        accepted_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("model request accepted");
        runtime
            .dispatch(
                "doc.agent.stop",
                &json!({"session_id":"stale-compact"}),
                &config,
            )
            .expect("stop session");
        let response = compact.join().expect("join compact call");
        server.join().expect("join model server");
        assert_eq!(response["success"], false);
        assert_eq!(response["error_code"], "stale_generation");
        let status = runtime
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"stale-compact"}),
                &config,
            )
            .expect("status");
        assert_eq!(status["agent_session"]["resume_snapshot"], Value::Null);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn agent_message_uses_rust_model_transport_and_records_typed_events() {
        let dir = std::env::temp_dir().join(format!("koi-native-agent-model-{}", now_ms()));
        let config = ConfigStore::new(dir.join("config.json"));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        let (base_url, server) = mock_model_server(
            json!({
                "reply":"I found no execution evidence, so no completion is claimed.",
                "thinking":"Only the supplied session message is available.",
                "operation":null
            }),
            None,
            Duration::ZERO,
        );
        configure_model(&config, &base_url);
        let response = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"model-agent",
                    "message":"Summarize the current evidence",
                    "frontend_context":{"currentFile":"notice.docx","api_key":"must-not-leak"}
                }),
                &config,
            )
            .expect("agent response");
        let request = server.join().expect("join model server");
        assert_eq!(response["success"], true);
        assert_eq!(response["status"], "completed");
        assert_eq!(response["operation_id"], Value::Null);
        assert!(response["reply"]
            .as_str()
            .unwrap()
            .contains("no completion"));
        assert!(request.contains("POST /v1/chat/completions HTTP/1.1"));
        assert!(request.contains("notice.docx"));
        assert!(!request.contains("must-not-leak"));
        let events = response["agent_session"]["events"].as_array().unwrap();
        assert!(events.iter().any(|event| event["type"] == "thought"));
        assert!(events.iter().any(|event| event["type"] == "chat"));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn retest_agent_chat_returns_model_reply_and_non_streaming_shape() {
        let dir = std::env::temp_dir().join(format!("koi-native-agent-chat-{}", now_ms()));
        let config = ConfigStore::new(dir.join("config.json"));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        let (base_url, server) = mock_model_server(
            json!({"reply":"Chat reply retained","thinking":"Evidence only","operation":null}),
            None,
            Duration::ZERO,
        );
        configure_model(&config, &base_url);
        let response = runtime
            .dispatch(
                "doc.retest.agent_chat",
                &json!({"session_id":"chat-session","message":"What is known?"}),
                &config,
            )
            .expect("chat response");
        server.join().expect("join model server");
        assert_eq!(response["success"], true);
        assert_eq!(response["streaming"], false);
        assert_eq!(response["reply"], "Chat reply retained");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn agent_message_discards_late_model_reply_after_stop() {
        let dir = std::env::temp_dir().join(format!("koi-native-agent-stale-{}", now_ms()));
        let config = Arc::new(ConfigStore::new(dir.join("config.json")));
        let runtime = NativeRuntime::new(dir.clone(), std::env::temp_dir()).expect("runtime");
        let (accepted_tx, accepted_rx) = mpsc::channel();
        let (base_url, server) = mock_model_server(
            json!({"reply":"late reply","thinking":"late","operation":null}),
            Some(accepted_tx),
            Duration::from_millis(100),
        );
        configure_model(&config, &base_url);
        let call_runtime = runtime.clone();
        let call_config = Arc::clone(&config);
        let call = thread::spawn(move || {
            call_runtime
                .dispatch(
                    "doc.agent.message",
                    &json!({"session_id":"late-agent","message":"wait for model"}),
                    &call_config,
                )
                .expect("agent response")
        });
        accepted_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("model request accepted");
        runtime
            .dispatch(
                "doc.agent.stop",
                &json!({"session_id":"late-agent"}),
                &config,
            )
            .expect("stop agent");
        let response = call.join().expect("join agent call");
        server.join().expect("join model server");
        assert_eq!(response["success"], false);
        assert_eq!(response["error_code"], "stale_generation");
        let status = runtime
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"late-agent"}),
                &config,
            )
            .expect("status");
        assert_eq!(status["status"], "stopped");
        assert!(!status["agent_session"]["events"]
            .as_array()
            .unwrap()
            .iter()
            .any(|event| event["content"] == "late reply"));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn agent_tools_expose_workspace_and_sandboxed_probe_contracts() {
        let runtime = runtime("agent-tools");
        let config = ConfigStore::new(
            std::env::temp_dir().join(format!("koi-native-tools-config-{}", now_ms())),
        );
        let response = runtime
            .dispatch("doc.agent.tools", &json!({"session_id":"tools"}), &config)
            .expect("tools response");
        let tools = response["tools"].as_array().expect("tools list");
        let names = tools
            .iter()
            .filter_map(|tool| tool["name"].as_str())
            .collect::<Vec<_>>();
        assert_eq!(names.len(), 11);
        assert!(names.contains(&"read_file"));
        assert!(names.contains(&"apply_patch"));
        assert!(names.contains(&"run_python_probe"));
        assert!(names.contains(&"build_python_probe_wheel"));
        let probe = tools
            .iter()
            .find(|tool| tool["name"] == "run_python_probe")
            .expect("dynamic probe tool");
        assert_eq!(probe["requiresApproval"], true);
        assert_eq!(probe["risk"], "external");
        let source_build = tools
            .iter()
            .find(|tool| tool["name"] == "build_python_probe_wheel")
            .expect("source build tool");
        assert_eq!(source_build["requiresApproval"], true);
        assert_eq!(source_build["autoApprovalSupported"], false);
        assert_eq!(response["auto_approve"], true);
    }

    #[test]
    fn source_build_never_uses_session_auto_approval() {
        let root = std::env::temp_dir().join(format!("koi-source-approval-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).unwrap();
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");
        let proposed = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"source-build-second-approval",
                    "message":"build the reviewed source package",
                    "target_dir":workspace,
                    "auto_approve":true,
                    "operation":{
                        "tool_name":"build_python_probe_wheel",
                        "risk":"source_build",
                        "arguments":{"package":"idna"}
                    }
                }),
                &config,
            )
            .expect("propose source build");
        assert_eq!(proposed["blocked"], true);
        assert_eq!(proposed["running"], false);
        assert_eq!(proposed["auto_approved"], false);
        assert!(proposed["approval_id"].as_str().is_some());
        let _ = fs::remove_dir_all(root);
    }

    fn wait_for_operation(
        runtime: &NativeRuntime,
        config: &ConfigStore,
        session_id: &str,
        operation_id: &str,
    ) -> Value {
        for _ in 0..100 {
            let status = runtime
                .dispatch(
                    "doc.agent.operation.status",
                    &json!({"session_id":session_id,"operation_id":operation_id}),
                    config,
                )
                .expect("operation status");
            if matches!(
                status["operation"]["status"].as_str(),
                Some("completed" | "failed" | "cancelled" | "rejected")
            ) {
                return status;
            }
            thread::sleep(Duration::from_millis(5));
        }
        panic!("operation did not reach a terminal state");
    }

    #[test]
    fn approved_read_only_operations_execute_inside_workspace_and_escape_fails_closed() {
        let root = std::env::temp_dir().join(format!("koi-native-operation-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).expect("create operation workspace");
        fs::write(workspace.join("evidence.txt"), "exact evidence line\n").expect("write evidence");
        fs::write(root.join("outside.txt"), "outside secret").expect("write outside fixture");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");

        let proposed = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"approved-read",
                    "message":"read exact evidence",
                    "target_dir":workspace,
                    "auto_approve":false,
                    "operation":{"tool_name":"read_file","risk":"read","args":{"path":"evidence.txt","max_chars":1000}}
                }),
                &config,
            )
            .expect("propose read");
        assert_eq!(proposed["blocked"], true);
        let approval_id = proposed["approval_id"].as_str().unwrap();
        let operation_id = proposed["operation_id"].as_str().unwrap();
        let approved = runtime
            .dispatch(
                "doc.agent.approval.respond",
                &json!({"session_id":"approved-read","approval_id":approval_id,"decision":"approve"}),
                &config,
            )
            .expect("approve read");
        assert_eq!(approved["success"], true);
        let completed = wait_for_operation(&runtime, &config, "approved-read", operation_id);
        assert_eq!(completed["operation"]["status"], "completed");
        assert!(completed["operation"]["detail"]
            .as_str()
            .unwrap()
            .contains("exact evidence line"));

        let escaped = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"escaped-read",
                    "message":"reject escape",
                    "target_dir":root.join("workspace"),
                    "auto_approve":true,
                    "operation":{"tool_name":"read_file","risk":"read","args":{"path":"../outside.txt"}}
                }),
                &config,
            )
            .expect("start escaped read");
        let escaped_id = escaped["operation_id"].as_str().unwrap();
        let failed = wait_for_operation(&runtime, &config, "escaped-read", escaped_id);
        assert_eq!(failed["operation"]["status"], "failed");
        assert!(failed["operation"]["error"]
            .as_str()
            .unwrap()
            .contains("escapes"));
        assert!(!failed.to_string().contains("outside secret"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn dynamic_probe_operation_never_falls_back_when_appcontainer_is_unavailable() {
        let root = std::env::temp_dir().join(format!("koi-native-probe-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).expect("create probe workspace");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");
        let started = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"sandbox-probe",
                    "message":"run isolated probe",
                    "target_dir":workspace,
                    "auto_approve":true,
                    "operation":{
                        "tool_name":"run_python_probe",
                        "risk":"external",
                        "arguments":{
                            "script":"def run(targets, context):\n    return {'unexpected_host_execution': True}\n",
                            "targets":["http://127.0.0.1:9/"],
                            "context":{}
                        }
                    }
                }),
                &config,
            )
            .expect("start sandboxed probe");
        let operation_id = started["operation_id"].as_str().expect("operation id");
        let terminal = {
            let mut terminal = Value::Null;
            for _ in 0..600 {
                terminal = runtime
                    .dispatch(
                        "doc.agent.operation.status",
                        &json!({"session_id":"sandbox-probe","operation_id":operation_id}),
                        &config,
                    )
                    .expect("probe operation status");
                if matches!(
                    terminal["operation"]["status"].as_str(),
                    Some("completed" | "failed" | "cancelled" | "rejected")
                ) {
                    break;
                }
                thread::sleep(Duration::from_millis(50));
            }
            terminal
        };
        assert!(
            matches!(
                terminal["operation"]["status"].as_str(),
                Some("completed" | "failed" | "cancelled" | "rejected")
            ),
            "probe operation did not reach terminal state: {terminal}"
        );
        if terminal["operation"]["status"] == "failed" {
            let error = terminal["operation"]["error"].as_str().unwrap_or_default();
            assert!(
                error.contains("probe sandbox") || error.contains("AppContainer"),
                "unexpected fail-closed error: {error}"
            );
        } else {
            assert_eq!(terminal["operation"]["status"], "completed");
            assert_eq!(
                terminal["operation"]["detail"]
                    .as_str()
                    .and_then(|detail| serde_json::from_str::<Value>(detail).ok())
                    .and_then(|detail| detail.get("sandbox").cloned()),
                Some(Value::String("windows_appcontainer".to_string()))
            );
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn operation_reflection_can_schedule_one_typed_follow_up_operation() {
        let root = std::env::temp_dir().join(format!("koi-native-follow-up-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).expect("create follow-up workspace");
        fs::write(workspace.join("evidence.txt"), "follow-up evidence").expect("evidence");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");
        let (base_url, server) = mock_model_sequence(vec![
            json!({
                "reply":"first tool completed",
                "thinking":"need one more exact read",
                "operation":{"tool_name":"read_file","risk":"read","detail":"follow up","args":{"path":"evidence.txt","max_chars":1000}}
            }),
            json!({"reply":"follow-up complete","thinking":"evidence retained","operation":null}),
        ]);
        configure_model(&config, &base_url);
        let first = runtime
            .dispatch(
                "doc.agent.message",
                &json!({
                    "session_id":"follow-up",
                    "message":"inspect evidence",
                    "target_dir":workspace,
                    "auto_approve":true
                }),
                &config,
            )
            .expect("first model turn");
        assert_eq!(first["success"], true);
        let first_operation = first["operation_id"].as_str().expect("first operation");
        let terminal = wait_for_operation(&runtime, &config, "follow-up", first_operation);
        assert_eq!(terminal["operation"]["status"], "completed");
        for _ in 0..200 {
            let status = runtime
                .dispatch(
                    "doc.agent.status",
                    &json!({"session_id":"follow-up"}),
                    &config,
                )
                .expect("follow-up status");
            if status["agent_session"]["status"] == "completed"
                && status["agent_session"]["message"] == "follow-up complete"
            {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        let status = runtime
            .dispatch(
                "doc.agent.status",
                &json!({"session_id":"follow-up"}),
                &config,
            )
            .expect("final follow-up status");
        assert_eq!(status["agent_session"]["message"], "follow-up complete");
        let requests = server.join().expect("join sequence model server");
        assert_eq!(requests.len(), 2);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn retest_start_and_message_share_resume_planning_and_ignore_numeric_hints() {
        let root = std::env::temp_dir().join(format!("koi-native-resume-plan-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).expect("create resume workspace");
        fs::write(workspace.join("first.docx"), b"fixture").expect("first source");
        fs::write(workspace.join("second.docx"), b"fixture").expect("second source");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");
        let frontend_context = json!({
            "session":{"targetDir":workspace},
            "progressEvidence":{
                "targetDir":workspace,
                "completedCountHint":2,
                "nextIndexHint":2,
                "nextSourceFileName":"second.docx"
            }
        });

        let (start_url, start_server) = mock_model_server(
            json!({"reply":"start planned","thinking":"exact evidence","operation":null}),
            None,
            Duration::ZERO,
        );
        configure_model(&config, &start_url);
        let started = runtime
            .dispatch(
                "doc.retest.agent.start",
                &json!({
                    "session_id":"resume-start",
                    "target_dir":workspace,
                    "message":"continue",
                    "one_click_queue":true,
                    "force_resume":true,
                    "frontend_context":frontend_context
                }),
                &config,
            )
            .expect("start response");
        let start_request = start_server.join().expect("start model request");

        let (message_url, message_server) = mock_model_server(
            json!({"reply":"message planned","thinking":"exact evidence","operation":null}),
            None,
            Duration::ZERO,
        );
        configure_model(&config, &message_url);
        let messaged = runtime
            .dispatch(
                "doc.retest.agent.message",
                &json!({
                    "session_id":"resume-message",
                    "target_dir":workspace,
                    "message":"continue",
                    "force_resume":true,
                    "frontend_context":frontend_context
                }),
                &config,
            )
            .expect("message response");
        let message_request = message_server.join().expect("message model request");

        assert_eq!(started["resume_plan"], messaged["resume_plan"]);
        assert_eq!(started["resume_plan"]["completed_source_files"], json!([]));
        assert_eq!(
            started["resume_plan"]["pending_source_files"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        assert_eq!(started["resume_plan"]["next_index"], 0);
        assert_eq!(started["resume_plan"]["numeric_hints_used"], false);
        assert!(start_request.contains("numeric_hints_used"));
        assert!(message_request.contains("numeric_hints_used"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn resume_plan_uses_exact_disk_report_path_for_duplicate_filenames() {
        let root = std::env::temp_dir().join(format!("koi-native-resume-duplicate-{}", now_ms()));
        let first_dir = root.join("first");
        let second_dir = root.join("second");
        fs::create_dir_all(&first_dir).expect("create first directory");
        fs::create_dir_all(&second_dir).expect("create second directory");
        let first = first_dir.join("notice.docx");
        let second = second_dir.join("notice.docx");
        fs::write(&first, b"first source").expect("first source");
        fs::write(&second, b"second source").expect("second source");
        fs::write(second_dir.join("notice复测报告.docx"), b"report").expect("disk report evidence");
        let request: AgentMessageRequest = parse_payload(&json!({
            "message":"continue",
            "target_dir":root,
            "force_resume":true,
            "frontend_context":{
                "session":{"targetDir":root},
                "progressEvidence":{
                    "targetDir":root,
                    "completedFileNames":["notice.docx"],
                    "completedCountHint":2,
                    "nextIndexHint":2
                }
            }
        }))
        .expect("typed request");
        let plan = build_retest_resume_plan(&request, &root)
            .expect("resume plan")
            .expect("plan present");

        assert_eq!(plan.completed_source_files.len(), 1);
        assert_eq!(
            normalized_path_key(Path::new(&plan.completed_source_files[0])),
            normalized_path_key(&second)
        );
        assert!(plan
            .pending_source_files
            .iter()
            .any(|path| normalized_path_key(Path::new(path)) == normalized_path_key(&first)));
        assert!(!plan.numeric_hints_used);
        let _ = fs::remove_dir_all(root);
    }

    fn write_confirmation_fixture(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().expect("fixture parent"))
            .expect("create confirmation fixture directory");
        let output = File::create(path).expect("create confirmation docx");
        let mut writer = zip::ZipWriter::new(output);
        writer
            .start_file(
                "word/document.xml",
                zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::DEFLATE),
            )
            .expect("confirmation document part");
        writer
            .write_all(
                format!(
                    r#"<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"#
                )
                .as_bytes(),
            )
            .expect("confirmation document XML");
        writer.finish().expect("finish confirmation docx");
    }

    fn wait_for_retest_task(runtime: &NativeRuntime, config: &ConfigStore, task_id: &str) -> Value {
        for _ in 0..200 {
            let status = runtime
                .dispatch(
                    "doc.retest.run_one.status",
                    &json!({"task_id":task_id}),
                    config,
                )
                .expect("retest task status");
            if status["done"] == true {
                return status;
            }
            thread::sleep(Duration::from_millis(10));
        }
        panic!("retest task did not reach a terminal state");
    }

    #[test]
    fn confirmation_approve_starts_the_linked_rust_worker() {
        let root = std::env::temp_dir().join(format!("koi-confirm-approve-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        let source = workspace.join("approved.docx");
        write_confirmation_fixture(&source, "approved confirmation fixture");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace).expect("runtime");

        let started = runtime
            .dispatch(
                "doc.retest.run_one.start",
                &json!({
                    "source_file":source,
                    "session_id":"confirm-approve",
                    "round_id":"approve-round",
                    "mode":"fast",
                    "use_ai":false,
                    "requires_confirmation":true
                }),
                &config,
            )
            .expect("start confirmation task");
        assert_eq!(started["running"], false);
        assert_eq!(started["done"], false);
        let task_id = started["task_id"].as_str().unwrap().to_string();
        let confirmation_id = started["result"]["confirmation_id"]
            .as_str()
            .unwrap()
            .to_string();
        {
            let state = runtime.lock_state();
            let confirmation = state.confirmations.get(&confirmation_id).unwrap();
            assert_eq!(confirmation.task_id, task_id);
            assert_eq!(Path::new(&confirmation.source_file), source.as_path());
            assert_eq!(
                confirmation.request.as_ref().unwrap().round_id,
                "approve-round"
            );
        }

        let approved = runtime
            .dispatch(
                "doc.retest.confirmation.respond",
                &json!({
                    "confirmation_id":confirmation_id,
                    "session_id":"confirm-approve",
                    "decision":"approve"
                }),
                &config,
            )
            .expect("approve confirmation");
        assert_eq!(approved["success"], true);
        assert_eq!(approved["task_id"], task_id);
        assert_eq!(approved["running"], true);

        let completed = wait_for_retest_task(&runtime, &config, &task_id);
        assert_eq!(completed["done"], true);
        assert_eq!(completed["success"], true);
        assert_eq!(completed["result_data"]["engine"], "rust_fast_retest");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn confirmation_reject_terminates_task_and_preserves_resume_snapshot() {
        let root = std::env::temp_dir().join(format!("koi-confirm-reject-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        let source = workspace.join("rejected.docx");
        write_confirmation_fixture(&source, "rejected confirmation fixture");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace).expect("runtime");
        let snapshot = json!({
            "stage":"judgement",
            "current_file":source,
            "evidence":{"exact_path":source}
        });
        let started = runtime
            .dispatch(
                "doc.retest.run_one.start",
                &json!({
                    "source_file":source,
                    "session_id":"confirm-reject",
                    "round_id":"reject-round",
                    "use_ai":false,
                    "requires_confirmation":true,
                    "resume_snapshot":snapshot
                }),
                &config,
            )
            .expect("start confirmation task");
        let task_id = started["task_id"].as_str().unwrap().to_string();
        let confirmation_id = started["result"]["confirmation_id"]
            .as_str()
            .unwrap()
            .to_string();

        let rejected = runtime
            .dispatch(
                "doc.retest.confirmation.respond",
                &json!({
                    "confirmation_id":confirmation_id,
                    "session_id":"confirm-reject",
                    "decision":"reject",
                    "note":"user declined"
                }),
                &config,
            )
            .expect("reject confirmation");
        assert_eq!(rejected["rejected"], true);
        assert_eq!(rejected["done"], true);
        assert_eq!(rejected["running"], false);
        assert_eq!(rejected["resume_snapshot"], snapshot);
        let status = runtime
            .dispatch(
                "doc.retest.run_one.status",
                &json!({"task_id":task_id}),
                &config,
            )
            .expect("rejected status");
        assert_eq!(status["done"], true);
        assert_eq!(status["success"], false);
        assert_eq!(status["stopped"], false);
        assert_eq!(status["result"]["rejected"], true);
        assert_eq!(status["resume_snapshot"], snapshot);
        let state = runtime.lock_state();
        assert_eq!(
            state.sessions["confirm-reject"].resume_snapshot,
            Some(snapshot)
        );
        drop(state);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn pending_confirmation_survives_restart_with_complete_worker_context() {
        let root = std::env::temp_dir().join(format!("koi-confirm-restart-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        let source = workspace.join("restart.docx");
        write_confirmation_fixture(&source, "restart confirmation fixture");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data.clone(), workspace.clone()).expect("runtime");
        let started = runtime
            .dispatch(
                "doc.retest.run_one.start",
                &json!({
                    "source_file":source,
                    "session_id":"confirm-restart",
                    "round_id":"restart-round",
                    "source_file_name":"restart.docx",
                    "mode":"fast",
                    "use_ai":false,
                    "requires_confirmation":true
                }),
                &config,
            )
            .expect("start persisted confirmation task");
        let task_id = started["task_id"].as_str().unwrap().to_string();
        let confirmation_id = started["result"]["confirmation_id"]
            .as_str()
            .unwrap()
            .to_string();
        let persisted: Value = serde_json::from_slice(
            &fs::read(data.join(STATE_FILE)).expect("read persisted native state"),
        )
        .expect("parse persisted native state");
        let persisted_confirmation = &persisted["confirmations"][&confirmation_id];
        assert_eq!(persisted_confirmation["task_id"], task_id);
        assert_eq!(
            persisted_confirmation["source_file"],
            source.to_string_lossy().as_ref()
        );
        assert_eq!(
            persisted_confirmation["request"]["round_id"],
            "restart-round"
        );
        drop(runtime);

        let restarted = NativeRuntime::new(data, workspace).expect("restart runtime");
        let approved = restarted
            .dispatch(
                "doc.retest.confirmation.respond",
                &json!({
                    "confirmation_id":confirmation_id,
                    "session_id":"confirm-restart",
                    "decision":"approve"
                }),
                &config,
            )
            .expect("approve after restart");
        assert_eq!(approved["task_id"], task_id);
        let completed = wait_for_retest_task(&restarted, &config, &task_id);
        assert_eq!(completed["success"], true);
        assert_eq!(completed["result_data"]["round_id"], "restart-round");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn stop_invalidates_pending_confirmation_and_discards_late_task_result() {
        let root = std::env::temp_dir().join(format!("koi-confirm-stale-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        let source = workspace.join("stale.docx");
        write_confirmation_fixture(&source, "stale confirmation fixture");
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace).expect("runtime");
        let snapshot = json!({"stage":"confirmation","source_file":source});
        let started = runtime
            .dispatch(
                "doc.retest.run_one.start",
                &json!({
                    "source_file":source,
                    "session_id":"confirm-stale",
                    "use_ai":false,
                    "requires_confirmation":true,
                    "resume_snapshot":snapshot
                }),
                &config,
            )
            .expect("start stale confirmation task");
        let task_id = started["task_id"].as_str().unwrap().to_string();
        let generation = started["generation"].as_u64().unwrap();
        let confirmation_id = started["result"]["confirmation_id"]
            .as_str()
            .unwrap()
            .to_string();
        let stopped = runtime
            .dispatch(
                "doc.retest.run_one.stop",
                &json!({"task_id":task_id}),
                &config,
            )
            .expect("stop pending confirmation task");
        assert!(stopped["generation"].as_u64().unwrap() > generation);
        assert_eq!(stopped["resume_snapshot"], snapshot);

        let error = runtime
            .dispatch(
                "doc.retest.confirmation.respond",
                &json!({
                    "confirmation_id":confirmation_id,
                    "session_id":"confirm-stale",
                    "decision":"approve"
                }),
                &config,
            )
            .expect_err("stale confirmation must fail");
        assert!(error.contains("inactive generation"));
        runtime.finish_retest_task(
            &task_id,
            "confirm-stale",
            generation,
            Ok(json!({
                "success":true,
                "message":"late result must be discarded",
                "resume_snapshot":{"stage":"late"}
            })),
        );
        let status = runtime
            .dispatch(
                "doc.retest.run_one.status",
                &json!({"task_id":task_id}),
                &config,
            )
            .expect("stopped task status");
        assert_eq!(status["stopped"], true);
        assert_eq!(status["resume_snapshot"], snapshot);
        assert!(!status.to_string().contains("late result must be discarded"));
        let state = runtime.lock_state();
        let confirmation = state.confirmations.get(&confirmation_id).unwrap();
        assert!(confirmation.resolved_at.is_none());
        assert!(confirmation.decision.is_empty());
        drop(state);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn run_one_worker_extracts_urls_persists_observations_and_resumes() {
        let root = std::env::temp_dir().join(format!("koi-native-run-one-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).expect("create run-one workspace");
        let source = workspace.join("notice.docx");
        let output = File::create(&source).expect("create docx");
        let mut writer = zip::ZipWriter::new(output);
        writer
            .start_file(
                "word/document.xml",
                zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::DEFLATE),
            )
            .expect("document part");
        writer
            .write_all(
                r#"<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>retest target http://127.0.0.1:1/unreachable</w:t></w:r></w:p></w:body></w:document>"#
                    .as_bytes(),
            )
            .expect("document XML");
        writer.finish().expect("finish docx");

        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).expect("runtime");
        let started = runtime
            .dispatch(
                "doc.retest.run_one.start",
                &json!({
                    "source_file":source,
                    "session_id":"run-one",
                    "use_ai":false,
                    "mode":"fast"
                }),
                &config,
            )
            .expect("start run-one");
        assert_eq!(started["running"], true);
        let task_id = started["task_id"].as_str().unwrap().to_string();
        let mut status = started;
        for _ in 0..200 {
            if status["done"] == true {
                break;
            }
            thread::sleep(Duration::from_millis(10));
            status = runtime
                .dispatch(
                    "doc.retest.run_one.status",
                    &json!({"task_id":task_id}),
                    &config,
                )
                .expect("run-one status");
        }
        assert_eq!(status["done"], true);
        assert_eq!(status["success"], true);
        assert_eq!(status["result_data"]["engine"], "rust_fast_retest");
        assert_eq!(
            status["result_data"]["retest_results"][0]["target_unreachable"],
            true
        );
        assert_eq!(status["resume_snapshot"]["next_url_index"], 1);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn batch_retest_aggregates_exact_discovered_files_without_reports() {
        let root = std::env::temp_dir().join(format!("koi-native-batch-{}", now_ms()));
        let workspace = root.join("workspace");
        let data = root.join("data");
        fs::create_dir_all(&workspace).unwrap();
        for name in ["first.docx", "second.docx"] {
            let output = File::create(workspace.join(name)).unwrap();
            let mut writer = zip::ZipWriter::new(output);
            writer
                .start_file(
                    "word/document.xml",
                    zip::write::SimpleFileOptions::default()
                        .compression_method(zip::CompressionMethod::DEFLATE),
                )
                .unwrap();
            writer
                .write_all(
                    format!(
                        r#"<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{name} http://127.0.0.1:1/test</w:t></w:r></w:p></w:body></w:document>"#
                    )
                    .as_bytes(),
                )
                .unwrap();
            writer.finish().unwrap();
        }
        let config = ConfigStore::new(data.join("config.json"));
        let runtime = NativeRuntime::new(data, workspace.clone()).unwrap();
        let result = runtime
            .dispatch(
                "doc.retest.run",
                &json!({
                    "target_dir":workspace,
                    "session_id":"batch",
                    "use_ai":false,
                    "generate_reports":false
                }),
                &config,
            )
            .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["processed"], 2);
        assert_eq!(result["source_files"].as_array().unwrap().len(), 2);
        assert_eq!(result["reports"], json!([]));
        let _ = fs::remove_dir_all(root);
    }
}
