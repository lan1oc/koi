//! Hash-locked external retest tool acquisition.
//!
//! The Nmap setup executable is treated only as an archive: it is never
//! launched. Selected files are extracted with KOI's verified 7-Zip runtime,
//! then checked against the embedded product inventory before an atomic
//! install. The historical sqlmap id maps to the built-in Rust SQL validator.

use super::task_manager::{TaskEventSink, TaskManager};
use super::{archive_runtime, retest_config};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
#[cfg(windows)]
use std::os::windows::fs::OpenOptionsExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use zip::ZipArchive;

const TOOLS: &[&str] = &["nmap", "sqlmap", "ffuf"];
const RETENTION_MS: u64 = 60 * 60 * 1_000;
const LOCK_FILE_NAME: &str = "external_tools.lock.json";
const LOCK_FORMAT: &str = "koi-retest-tools-lock-v1";
const LOCK_PLATFORM: &str = "windows-x64";
const MAX_ARTIFACT_BYTES: u64 = 128 * 1024 * 1024;
const MAX_PRODUCT_FILES: usize = 64;
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(15 * 60);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_DOWNLOAD_REQUESTS: usize = 64;
const MAX_CONSECUTIVE_DOWNLOAD_FAILURES: usize = 5;
const EMBEDDED_LOCK: &str = include_str!("external_tools.lock.json");
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
pub struct ExternalToolManager {
    root: PathBuf,
    tasks: Arc<Mutex<HashMap<String, Task>>>,
    lifecycle: Arc<TaskManager>,
}

#[derive(Clone)]
struct Task {
    id: String,
    generation: u64,
    running: bool,
    done: bool,
    success: bool,
    message: String,
    progress: u8,
    logs: Vec<String>,
    install_progress: Value,
    result: Option<Value>,
    error: String,
    created_at: u64,
    finished_at: Option<u64>,
}

#[derive(Deserialize, Default)]
struct InstallRequest {
    #[serde(default, deserialize_with = "deserialize_tools")]
    tools: Vec<String>,
    #[serde(default, rename = "async")]
    asynchronous: bool,
    #[serde(default)]
    background: bool,
}

#[derive(Deserialize)]
struct StatusRequest {
    task_id: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ToolLock {
    format: String,
    platform: String,
    artifacts: Vec<ToolArtifact>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ToolArtifact {
    tool: String,
    version: String,
    url: String,
    size: u64,
    sha256: String,
    archive_format: String,
    executable: String,
    executable_machine: String,
    license: String,
    files: Vec<ToolFile>,
    #[serde(default)]
    trees: Vec<ToolTree>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ToolFile {
    archive_path: String,
    install_path: String,
    size: u64,
    sha256: String,
    role: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ToolTree {
    archive_glob: String,
    install_root: String,
    file_count: usize,
    directory_count: usize,
    total_size: u64,
    manifest_sha256: String,
    role: String,
}

struct InstallLock {
    path: PathBuf,
    file: Option<File>,
}

impl InstallLock {
    fn acquire(root: &Path) -> Result<Self, String> {
        fs::create_dir_all(root)
            .map_err(|error| format!("failed to create external tool root: {error}"))?;
        let path = root.join(".external-tools.install.lock");
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(windows)]
        options.share_mode(0);
        let mut file = options
            .open(&path)
            .map_err(|error| {
                format!(
                    "another external tool installation is active, or its fail-closed lock requires review: {error}"
                )
            })?;
        writeln!(file, "pid={} created_at={}", std::process::id(), now_ms())
            .map_err(|error| format!("failed to write external tool install lock: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("failed to sync external tool install lock: {error}"))?;
        Ok(Self {
            path,
            file: Some(file),
        })
    }
}

impl Drop for InstallLock {
    fn drop(&mut self) {
        self.file.take();
        let _ = fs::remove_file(&self.path);
    }
}

struct StagingDir {
    path: PathBuf,
    committed: bool,
}

impl StagingDir {
    fn create(root: &Path, tool: &str) -> Result<Self, String> {
        let path = root.join(format!(".install-{tool}-{}", task_id()));
        fs::create_dir(&path).map_err(|error| {
            format!("failed to create external tool staging directory: {error}")
        })?;
        Ok(Self {
            path,
            committed: false,
        })
    }
}

impl Drop for StagingDir {
    fn drop(&mut self) {
        if !self.committed {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

impl ExternalToolManager {
    pub fn new(root: PathBuf) -> Result<Self, String> {
        fs::create_dir_all(&root)
            .map_err(|error| format!("failed to create retest tool directory: {error}"))?;
        let lifecycle = Arc::new(TaskManager::persistent(
            root.join(".koi-external-tool-tasks.json"),
        )?);
        Ok(Self {
            root,
            tasks: Arc::new(Mutex::new(HashMap::new())),
            lifecycle,
        })
    }

    pub(crate) fn add_event_sink(&self, sink: TaskEventSink) {
        self.lifecycle.add_event_sink(sink);
    }

    pub fn dispatch(&self, command: &str, payload: &Value) -> Result<Value, String> {
        match command {
            "doc.retest.tools.install" => self.install(payload),
            "doc.retest.tools.install.status" => self.status(payload),
            _ => Err(format!("external tool command not registered: {command}")),
        }
    }

    fn install(&self, payload: &Value) -> Result<Value, String> {
        let request: InstallRequest = serde_json::from_value(payload.clone())
            .map_err(|error| format!("invalid external tool install payload: {error}"))?;
        let tools = normalize_tools(&request.tools);
        if request.asynchronous || request.background {
            self.start(tools)
        } else {
            Ok(run_install(&self.root, &tools))
        }
    }

    fn status(&self, payload: &Value) -> Result<Value, String> {
        let request: StatusRequest = serde_json::from_value(payload.clone())
            .map_err(|error| format!("invalid external tool status payload: {error}"))?;
        let id = request.task_id.trim();
        if id.is_empty() {
            return Err("task_id is required".to_string());
        }
        self.prune();
        let tasks = self
            .tasks
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(tasks.get(id).map(task_payload).unwrap_or_else(|| {
            if let Some(snapshot) = self.lifecycle.snapshot(id) {
                return json!({
                    "success": false,
                    "task_id": snapshot.task_id,
                    "generation": snapshot.generation,
                    "running": snapshot.running,
                    "done": snapshot.done,
                    "stopped": snapshot.stopped,
                    "message": "External tool task was interrupted and recovered as stopped",
                    "progress": if snapshot.done {100} else {0},
                    "logs": [],
                    "log_count": 0,
                    "install_progress": {},
                    "failures": [{"tool":"all","reason":"task interrupted"}],
                    "error": "task interrupted"
                });
            }
            json!({
                "success": false, "task_id": id, "running": false, "done": true,
                "message": "External tool installation task not found or expired",
                "progress": 100, "logs": [], "log_count": 0,
                "install_progress": {},
                "failures": [{"tool":"all","reason":"task not found"}],
                "error": "task not found"
            })
        }))
    }

    fn start(&self, tools: Vec<String>) -> Result<Value, String> {
        self.prune();
        let id = task_id();
        let count = tools.len();
        let ticket = self
            .lifecycle
            .register(id.clone(), "external-tools", tools.join(","))?;
        let message = format!(
            "External tool installation task created: {}",
            tools.join(", ")
        );
        let task = Task {
            id: id.clone(),
            generation: ticket.generation,
            running: true,
            done: false,
            success: true,
            message: message.clone(),
            progress: 1,
            logs: vec![message.clone()],
            install_progress: json!({
                "phase":"start", "percent":0, "overall_percent":1,
                "tool_index":0, "tool_count":count, "message":message
            }),
            result: None,
            error: String::new(),
            created_at: now_ms(),
            finished_at: None,
        };
        self.tasks
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .insert(id.clone(), task);

        let tasks = Arc::clone(&self.tasks);
        let lifecycle = Arc::clone(&self.lifecycle);
        let root = self.root.clone();
        let worker_id = id.clone();
        let worker_ticket = ticket.clone();
        let spawn_result = thread::Builder::new()
            .name(format!("koi-tool-install-{id}"))
            .spawn(move || {
                if !lifecycle.is_active(&worker_ticket) {
                    return;
                }
                let result = run_install(&root, &tools);
                let success = result["success"].as_bool().unwrap_or(false);
                let message = result["message"]
                    .as_str()
                    .unwrap_or("External tool installation finished")
                    .to_string();
                let logs = result["logs"]
                    .as_array()
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_string)
                            .collect()
                    })
                    .unwrap_or_default();
                let error = if success {
                    String::new()
                } else {
                    result["failures"].to_string()
                };
                let accepted = lifecycle.finish(&worker_ticket, success).unwrap_or(false);
                if !accepted {
                    return;
                }
                let mut tasks = tasks
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
                if let Some(task) = tasks.get_mut(&worker_id) {
                    task.running = false;
                    task.done = true;
                    task.success = success;
                    task.message = message.clone();
                    task.progress = 100;
                    task.logs = logs;
                    task.install_progress = json!({
                        "phase": if success {"all_done"} else {"all_failed"},
                        "percent":100, "overall_percent":100,
                        "tool_index":count, "tool_count":count,
                        "message":message, "done":true, "success":success
                    });
                    task.result = Some(result);
                    task.error = error;
                    task.finished_at = Some(now_ms());
                }
            });
        if let Err(error) = spawn_result {
            let _ = self.lifecycle.cancel(&ticket.task_id);
            self.tasks
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .remove(&id);
            return Err(format!("failed to start external tool installer: {error}"));
        }

        let tasks = self
            .tasks
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(task_payload(tasks.get(&id).expect("task inserted")))
    }

    fn prune(&self) {
        let cutoff = now_ms().saturating_sub(RETENTION_MS);
        self.tasks
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .retain(|_, task| {
                task.running || task.finished_at.unwrap_or(task.created_at) >= cutoff
            });
    }
}

fn run_install(root: &Path, tools: &[String]) -> Value {
    let mut installed = Vec::new();
    let mut failures = Vec::new();
    let mut logs = Vec::new();
    let external_requested = tools.iter().any(|tool| tool != "sqlmap");
    let lock = if external_requested {
        match reviewed_lock() {
            Ok(lock) => Some(lock),
            Err(error) => return install_failure_payload(root, tools, &error),
        }
    } else {
        None
    };
    let _install_lock = if external_requested {
        match InstallLock::acquire(root) {
            Ok(lock) => Some(lock),
            Err(error) => return install_failure_payload(root, tools, &error),
        }
    } else {
        None
    };
    for tool in tools {
        if tool == "sqlmap" {
            installed.push(json!({
                "id":"sqlmap", "installed":true,
                "command":["koi://builtin/sql-validator"]
            }));
            logs.push("sqlmap tool id is provided by the built-in Rust SQL validator".to_string());
        } else {
            match install_reviewed_tool(root, lock.as_ref().expect("external lock loaded"), tool) {
                Ok((command, message)) => {
                    installed.push(json!({"id":tool,"installed":true,"command":[command]}));
                    logs.push(message);
                }
                Err(reason) => {
                    installed.push(json!({"id":tool,"installed":false,"command":[]}));
                    failures.push(json!({"tool":tool,"reason":reason}));
                    logs.push(format!("{tool} install failed closed: {reason}"));
                }
            }
        }
    }
    let success = failures.is_empty();
    json!({
        "success":success,
        "message": if success {"External retest tools are ready"} else {"Some external tools failed locked acquisition or verification"},
        "tool_root":root,
        "installed":installed,
        "failures":failures,
        "logs":logs,
        "status":retest_config::tools_status(root)
    })
}

fn install_failure_payload(root: &Path, tools: &[String], reason: &str) -> Value {
    let installed = tools
        .iter()
        .map(|tool| {
            if tool == "sqlmap" {
                json!({"id":tool,"installed":true,"command":["koi://builtin/sql-validator"]})
            } else {
                json!({"id":tool,"installed":false,"command":[]})
            }
        })
        .collect::<Vec<_>>();
    let failures = tools
        .iter()
        .filter(|tool| tool.as_str() != "sqlmap")
        .map(|tool| json!({"tool":tool,"reason":reason}))
        .collect::<Vec<_>>();
    json!({
        "success":failures.is_empty(),
        "message":if failures.is_empty() {"External retest tools are ready"} else {"External tool installation failed closed"},
        "tool_root":root,
        "installed":installed,
        "failures":failures,
        "logs":[reason],
        "status":retest_config::tools_status(root)
    })
}

fn reviewed_lock() -> Result<ToolLock, String> {
    if !cfg!(windows) || std::env::consts::ARCH != "x86_64" {
        return Err(
            "reviewed external tool acquisition is available only on Windows x64".to_string(),
        );
    }
    if !cfg!(debug_assertions) && !cfg!(test) {
        let executable = std::env::current_exe().map_err(|error| {
            format!("unable to locate koi.exe for tool lock verification: {error}")
        })?;
        let public_lock = executable
            .parent()
            .ok_or_else(|| "koi.exe has no parent directory".to_string())?
            .join(LOCK_FILE_NAME);
        let bytes = fs::read(&public_lock).map_err(|error| {
            format!(
                "unable to read public external tool lock {}: {error}",
                public_lock.display()
            )
        })?;
        if bytes != EMBEDDED_LOCK.as_bytes() {
            return Err(
                "public external tool lock does not match the lock embedded in koi.exe".to_string(),
            );
        }
    }
    parse_lock(EMBEDDED_LOCK)
}

/// Resolve an installed retest tool only after revalidating the complete
/// reviewed product inventory. Callers must never fall back to PATH because
/// that would bypass the locked acquisition boundary.
pub(crate) fn verified_tool_path(root: &Path, tool: &str) -> Result<Option<PathBuf>, String> {
    if !matches!(tool, "nmap" | "ffuf") {
        return Err(format!("unsupported managed retest tool: {tool}"));
    }
    let lock = reviewed_lock()?;
    let artifact = lock
        .artifacts
        .iter()
        .find(|artifact| artifact.tool == tool)
        .ok_or_else(|| format!("managed retest tool is missing from the embedded lock: {tool}"))?;
    let product_root = root.join(tool);
    if !product_root.exists() {
        return Ok(None);
    }
    verify_product(&product_root, artifact)?;
    let canonical_root = fs::canonicalize(&product_root)
        .map_err(|error| format!("unable to resolve managed {tool} directory: {error}"))?;
    let executable = fs::canonicalize(product_root.join(&artifact.executable))
        .map_err(|error| format!("unable to resolve managed {tool} executable: {error}"))?;
    if !executable.starts_with(&canonical_root) {
        return Err(format!(
            "managed {tool} executable escaped its product root"
        ));
    }
    Ok(Some(executable))
}

pub(crate) fn run_self_test() -> Result<bool, String> {
    let lock = reviewed_lock()?;
    let ffuf = lock
        .artifacts
        .iter()
        .find(|artifact| artifact.tool == "ffuf");
    let nmap = lock
        .artifacts
        .iter()
        .find(|artifact| artifact.tool == "nmap");
    Ok(ffuf.is_some_and(|artifact| artifact.version == "2.2.1")
        && nmap.is_some_and(|artifact| artifact.version == "7.991"))
}

fn parse_lock(source: &str) -> Result<ToolLock, String> {
    let lock: ToolLock = serde_json::from_str(source)
        .map_err(|error| format!("external tool lock is invalid JSON: {error}"))?;
    if lock.format != LOCK_FORMAT || lock.platform != LOCK_PLATFORM {
        return Err("external tool lock targets an unsupported format or platform".to_string());
    }
    if lock.artifacts.len() != 2 {
        return Err("external tool lock must contain exactly nmap and ffuf".to_string());
    }
    let mut tools = BTreeSet::new();
    for artifact in &lock.artifacts {
        if !tools.insert(artifact.tool.clone()) {
            return Err(format!(
                "external tool lock contains duplicate artifact: {}",
                artifact.tool
            ));
        }
        validate_artifact(artifact)?;
    }
    if tools != BTreeSet::from(["ffuf".to_string(), "nmap".to_string()]) {
        return Err("external tool lock must contain exactly nmap and ffuf".to_string());
    }
    Ok(lock)
}

fn validate_artifact(artifact: &ToolArtifact) -> Result<(), String> {
    let expected = match artifact.tool.as_str() {
        "ffuf" => (
            "2.2.1",
            "https://github.com/ffuf/ffuf/releases/download/v2.2.1/ffuf_2.2.1_windows_amd64.zip",
            "zip",
            "ffuf.exe",
            "x86_64",
        ),
        "nmap" => (
            "7.991",
            "https://nmap.org/dist/nmap-7.991-setup.exe",
            "nsis",
            "nmap.exe",
            "x86",
        ),
        other => return Err(format!("unsupported external tool lock artifact: {other}")),
    };
    if artifact.version != expected.0
        || artifact.url != expected.1
        || artifact.archive_format != expected.2
        || artifact.executable != expected.3
        || artifact.executable_machine != expected.4
        || artifact.size == 0
        || artifact.size > MAX_ARTIFACT_BYTES
        || !is_lower_hex_sha256(&artifact.sha256)
        || artifact.license.trim().is_empty()
    {
        return Err(format!(
            "{} lock provenance or platform metadata is invalid",
            artifact.tool
        ));
    }
    if artifact.files.is_empty()
        || artifact.files.len() > MAX_PRODUCT_FILES
        || artifact.trees.len() > 8
    {
        return Err(format!("{} product inventory is invalid", artifact.tool));
    }
    let mut archive_paths = BTreeSet::new();
    let mut install_paths = BTreeSet::new();
    let mut executable_count = 0_usize;
    for entry in &artifact.files {
        validate_relative_path(&entry.archive_path)?;
        validate_relative_path(&entry.install_path)?;
        if entry.archive_path.contains('/')
            || entry.install_path.contains('/')
            || entry.archive_path.contains('*')
            || entry.archive_path.contains('?')
        {
            return Err(format!(
                "{} direct product path must be a non-wildcard top-level file: {}",
                artifact.tool, entry.install_path
            ));
        }
        if entry.size == 0
            || entry.size > MAX_ARTIFACT_BYTES
            || !is_lower_hex_sha256(&entry.sha256)
            || entry.role.trim().is_empty()
            || !archive_paths.insert(entry.archive_path.clone())
            || !install_paths.insert(entry.install_path.clone())
        {
            return Err(format!(
                "{} product inventory entry is invalid: {}",
                artifact.tool, entry.install_path
            ));
        }
        if entry.install_path == artifact.executable && entry.role == "executable" {
            executable_count += 1;
        }
    }
    if executable_count != 1 {
        return Err(format!(
            "{} product inventory must identify exactly one executable",
            artifact.tool
        ));
    }
    let expected_direct_files = match artifact.tool.as_str() {
        "ffuf" => BTreeSet::from([
            "CHANGELOG.md".to_string(),
            "LICENSE".to_string(),
            "README.md".to_string(),
            "ffuf.exe".to_string(),
        ]),
        "nmap" => BTreeSet::from([
            "3rd-party-licenses.txt".to_string(),
            "CHANGELOG".to_string(),
            "LICENSE".to_string(),
            "README-WIN32".to_string(),
            "libcrypto-3.dll".to_string(),
            "libssh2.dll".to_string(),
            "libssl-3.dll".to_string(),
            "nmap-mac-prefixes".to_string(),
            "nmap-os-db".to_string(),
            "nmap-protocols".to_string(),
            "nmap-rpc".to_string(),
            "nmap-service-probes".to_string(),
            "nmap-services".to_string(),
            "nmap.exe".to_string(),
            "nmap.xsl".to_string(),
            "nse_main.lua".to_string(),
            "zlibwapi.dll".to_string(),
        ]),
        _ => unreachable!("tool checked above"),
    };
    if install_paths != expected_direct_files {
        return Err(format!(
            "{} direct product inventory does not match the reviewed runtime",
            artifact.tool
        ));
    }
    let mut tree_roots = BTreeSet::new();
    for tree in &artifact.trees {
        validate_relative_path(&tree.install_root)?;
        if tree.install_root.contains('/')
            || !tree_roots.insert(tree.install_root.clone())
            || install_paths.contains(&tree.install_root)
            || tree.file_count == 0
            || tree.file_count > 2_000
            || tree.directory_count > 512
            || tree.total_size == 0
            || tree.total_size > MAX_ARTIFACT_BYTES
            || !is_lower_hex_sha256(&tree.manifest_sha256)
            || tree.role.trim().is_empty()
        {
            return Err(format!(
                "{} product tree metadata is invalid: {}",
                artifact.tool, tree.install_root
            ));
        }
        let expected_glob = format!("{}/*", tree.install_root);
        if tree.archive_glob != expected_glob {
            return Err(format!(
                "{} product tree has an unreviewed archive glob: {}",
                artifact.tool, tree.archive_glob
            ));
        }
    }
    if artifact.tool == "ffuf" && !artifact.trees.is_empty() {
        return Err("ffuf product lock must not contain directory trees".to_string());
    }
    if artifact.tool == "nmap"
        && tree_roots != BTreeSet::from(["nselib".to_string(), "scripts".to_string()])
    {
        return Err("nmap product lock must contain exactly nselib and scripts trees".to_string());
    }
    if artifact.tool == "nmap" {
        let nselib = artifact
            .trees
            .iter()
            .find(|tree| tree.install_root == "nselib")
            .expect("nselib tree checked above");
        let scripts = artifact
            .trees
            .iter()
            .find(|tree| tree.install_root == "scripts")
            .expect("scripts tree checked above");
        if (
            nselib.file_count,
            nselib.directory_count,
            nselib.total_size,
            nselib.manifest_sha256.as_str(),
        ) != (
            186,
            3,
            8_223_140,
            "3b405a9f40dbc985c40c7fc5a5a20a8d76f5a19ac3f1d3562660398ef3842b6b",
        ) || (
            scripts.file_count,
            scripts.directory_count,
            scripts.total_size,
            scripts.manifest_sha256.as_str(),
        ) != (
            612,
            0,
            3_895_325,
            "740f923b6d74000195400302790adb9a57dab92a4db6ffd3d943c6a21a696085",
        ) {
            return Err(
                "nmap product tree fingerprints do not match the reviewed runtime".to_string(),
            );
        }
    }
    Ok(())
}

fn is_lower_hex_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_relative_path(value: &str) -> Result<PathBuf, String> {
    if value.is_empty() || value.contains('\\') || value.contains(':') {
        return Err(format!("invalid external tool inventory path: {value}"));
    }
    let path = Path::new(value);
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::Prefix(_)
                    | Component::RootDir
                    | Component::ParentDir
                    | Component::CurDir
            )
        })
    {
        return Err(format!("unsafe external tool inventory path: {value}"));
    }
    Ok(path.to_path_buf())
}

fn install_reviewed_tool(
    root: &Path,
    lock: &ToolLock,
    tool: &str,
) -> Result<(String, String), String> {
    let artifact = lock
        .artifacts
        .iter()
        .find(|artifact| artifact.tool == tool)
        .ok_or_else(|| format!("{tool} is not present in the reviewed tool lock"))?;
    let destination = root.join(tool);
    if destination.exists() {
        verify_product(&destination, artifact).map_err(|error| {
            format!(
                "existing managed {tool} directory failed verification and was left unchanged: {error}"
            )
        })?;
        let command = destination.join(&artifact.executable);
        return Ok((
            command.to_string_lossy().to_string(),
            format!("{tool} {} managed runtime verified", artifact.version),
        ));
    }
    let mut staging = StagingDir::create(root, tool)?;
    let archive_path = staging.path.join("artifact.download");
    download_artifact(artifact, &archive_path)?;
    let product_dir = staging.path.join("product");
    fs::create_dir(&product_dir)
        .map_err(|error| format!("failed to create {tool} product staging directory: {error}"))?;
    extract_artifact(artifact, &archive_path, &product_dir)?;
    verify_product(&product_dir, artifact)?;
    fs::remove_file(&archive_path).map_err(|error| {
        format!("failed to remove verified {tool} download staging file: {error}")
    })?;
    if destination.exists() {
        return Err(format!(
            "managed {tool} destination appeared during installation; refusing to overwrite it"
        ));
    }
    fs::rename(&product_dir, &destination)
        .map_err(|error| format!("failed to atomically commit {tool} runtime: {error}"))?;
    staging.committed = true;
    let _ = fs::remove_dir(&staging.path);
    let command = destination.join(&artifact.executable);
    Ok((
        command.to_string_lossy().to_string(),
        format!(
            "{tool} {} downloaded, hash-verified, and installed from its reviewed product inventory",
            artifact.version
        ),
    ))
}

fn download_artifact(artifact: &ToolArtifact, destination: &Path) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(DOWNLOAD_TIMEOUT)
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 5 {
                attempt.error("external tool download exceeded five redirects")
            } else if attempt.url().scheme() != "https" {
                attempt.error("external tool download refused a non-HTTPS redirect")
            } else {
                attempt.follow()
            }
        }))
        .user_agent("KOI/4.0.0 locked-external-tool-fetcher")
        .build()
        .map_err(|error| format!("failed to create locked download client: {error}"))?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| format!("failed to create locked download staging file: {error}"))?;
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut requests = 0_usize;
    let mut consecutive_failures = 0_usize;
    let mut last_error = String::new();
    let mut buffer = [0_u8; 64 * 1024];
    while total < artifact.size && requests < MAX_DOWNLOAD_REQUESTS {
        requests += 1;
        let request_start = total;
        let mut request = client.get(&artifact.url);
        if request_start > 0 {
            request = request.header(reqwest::header::RANGE, format!("bytes={request_start}-"));
        }
        let mut response = match request.send() {
            Ok(response) => response,
            Err(error) => {
                last_error = format!("request failed: {error}");
                consecutive_failures += 1;
                if consecutive_failures >= MAX_CONSECUTIVE_DOWNLOAD_FAILURES {
                    break;
                }
                continue;
            }
        };
        if response.url().scheme() != "https" {
            return Err(format!(
                "{} official download redirected outside HTTPS",
                artifact.tool
            ));
        }
        if request_start == 0 && response.status() == reqwest::StatusCode::OK {
            if response
                .content_length()
                .is_some_and(|length| length != artifact.size)
            {
                return Err(format!(
                    "{} download length does not match the locked artifact size",
                    artifact.tool
                ));
            }
        } else if response.status() == reqwest::StatusCode::PARTIAL_CONTENT {
            let content_range = response
                .headers()
                .get(reqwest::header::CONTENT_RANGE)
                .and_then(|value| value.to_str().ok())
                .ok_or_else(|| {
                    format!("{} resumed download omitted Content-Range", artifact.tool)
                })?;
            validate_content_range(content_range, request_start, artifact.size)?;
            if response
                .content_length()
                .is_some_and(|length| length == 0 || length > artifact.size - request_start)
            {
                return Err(format!(
                    "{} resumed response length exceeds the locked artifact",
                    artifact.tool
                ));
            }
        } else {
            last_error = format!("official download returned HTTP {}", response.status());
            consecutive_failures += 1;
            if consecutive_failures >= MAX_CONSECUTIVE_DOWNLOAD_FAILURES {
                break;
            }
            continue;
        }

        let response_start = total;
        loop {
            let count = match response.read(&mut buffer) {
                Ok(0) => break,
                Ok(count) => count,
                Err(error) => {
                    last_error = format!("response ended early: {error}");
                    break;
                }
            };
            total = total
                .checked_add(count as u64)
                .ok_or_else(|| format!("{} download size overflow", artifact.tool))?;
            if total > artifact.size || total > MAX_ARTIFACT_BYTES {
                return Err(format!(
                    "{} download exceeded its locked size",
                    artifact.tool
                ));
            }
            hasher.update(&buffer[..count]);
            output
                .write_all(&buffer[..count])
                .map_err(|error| format!("failed to write {} download: {error}", artifact.tool))?;
        }
        if total > response_start {
            consecutive_failures = 0;
        } else {
            consecutive_failures += 1;
            if consecutive_failures >= MAX_CONSECUTIVE_DOWNLOAD_FAILURES {
                break;
            }
        }
    }
    output
        .sync_all()
        .map_err(|error| format!("failed to sync {} download: {error}", artifact.tool))?;
    if total != artifact.size {
        return Err(format!(
            "{} download remained incomplete after {requests} bounded request(s): {last_error}",
            artifact.tool
        ));
    }
    if format!("{:x}", hasher.finalize()) != artifact.sha256 {
        return Err(format!(
            "{} download failed final SHA-256 verification",
            artifact.tool
        ));
    }
    Ok(())
}

fn validate_content_range(
    value: &str,
    expected_start: u64,
    expected_total: u64,
) -> Result<(), String> {
    let range = value
        .strip_prefix("bytes ")
        .ok_or_else(|| "resumed download returned an invalid Content-Range unit".to_string())?;
    let (bounds, total) = range
        .split_once('/')
        .ok_or_else(|| "resumed download returned an invalid Content-Range".to_string())?;
    let (start, end) = bounds
        .split_once('-')
        .ok_or_else(|| "resumed download returned invalid Content-Range bounds".to_string())?;
    let start = start
        .parse::<u64>()
        .map_err(|_| "resumed download returned an invalid start offset".to_string())?;
    let end = end
        .parse::<u64>()
        .map_err(|_| "resumed download returned an invalid end offset".to_string())?;
    let total = total
        .parse::<u64>()
        .map_err(|_| "resumed download returned an invalid total size".to_string())?;
    if start != expected_start || total != expected_total || end < start || end >= total {
        return Err(format!(
            "resumed download Content-Range mismatch: expected byte {expected_start} of {expected_total}, received {value}"
        ));
    }
    Ok(())
}

#[cfg(test)]
fn write_locked_artifact(
    reader: &mut impl Read,
    destination: &Path,
    expected_size: u64,
    expected_sha256: &str,
    label: &str,
) -> Result<(), String> {
    if expected_size == 0
        || expected_size > MAX_ARTIFACT_BYTES
        || !is_lower_hex_sha256(expected_sha256)
    {
        return Err(format!("{label} locked artifact metadata is invalid"));
    }
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| format!("failed to create locked download staging file: {error}"))?;
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|error| format!("failed while reading {label}: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| format!("{label} size overflow"))?;
        if total > expected_size || total > MAX_ARTIFACT_BYTES {
            return Err(format!("{label} exceeded its locked size"));
        }
        hasher.update(&buffer[..count]);
        output
            .write_all(&buffer[..count])
            .map_err(|error| format!("failed to write {label}: {error}"))?;
    }
    output
        .sync_all()
        .map_err(|error| format!("failed to sync {label}: {error}"))?;
    let digest = format!("{:x}", hasher.finalize());
    if total != expected_size || digest != expected_sha256 {
        return Err(format!("{label} failed size or SHA-256 verification"));
    }
    Ok(())
}

fn extract_artifact(
    artifact: &ToolArtifact,
    archive_path: &Path,
    product_dir: &Path,
) -> Result<(), String> {
    match artifact.archive_format.as_str() {
        "zip" => extract_zip_product(artifact, archive_path, product_dir),
        "nsis" => extract_nsis_product(artifact, archive_path, product_dir),
        other => Err(format!("unsupported locked archive format: {other}")),
    }
}

fn extract_zip_product(
    artifact: &ToolArtifact,
    archive_path: &Path,
    product_dir: &Path,
) -> Result<(), String> {
    let file = File::open(archive_path)
        .map_err(|error| format!("failed to open {} ZIP: {error}", artifact.tool))?;
    let mut archive = ZipArchive::new(file)
        .map_err(|error| format!("failed to parse {} ZIP: {error}", artifact.tool))?;
    if archive.len() != artifact.files.len() {
        return Err(format!(
            "{} ZIP inventory count mismatch: expected {}, found {}",
            artifact.tool,
            artifact.files.len(),
            archive.len()
        ));
    }
    let expected = artifact
        .files
        .iter()
        .map(|entry| (entry.archive_path.as_str(), entry))
        .collect::<HashMap<_, _>>();
    let mut extracted = BTreeSet::new();
    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|error| format!("failed to inspect {} ZIP entry: {error}", artifact.tool))?;
        let name = entry.name().to_string();
        validate_relative_path(&name)?;
        if entry.is_dir()
            || entry
                .unix_mode()
                .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err(format!(
                "{} ZIP contains a directory or symbolic link: {name}",
                artifact.tool
            ));
        }
        let locked = expected
            .get(name.as_str())
            .ok_or_else(|| format!("{} ZIP contains an unreviewed entry: {name}", artifact.tool))?;
        if !extracted.insert(name.clone()) || entry.size() != locked.size {
            return Err(format!(
                "{} ZIP entry is duplicated or has an unexpected size: {name}",
                artifact.tool
            ));
        }
        let relative = validate_relative_path(&locked.install_path)?;
        let output_path = product_dir.join(relative);
        if let Some(parent) = output_path.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                format!(
                    "failed to create {} product directory: {error}",
                    artifact.tool
                )
            })?;
        }
        copy_locked_reader(&mut entry, &output_path, locked.size, &locked.sha256)?;
    }
    Ok(())
}

fn extract_nsis_product(
    artifact: &ToolArtifact,
    archive_path: &Path,
    product_dir: &Path,
) -> Result<(), String> {
    let runtime = archive_runtime::discover_verified_runtime().map_err(|error| {
        format!("verified 7-Zip runtime is required for static Nmap setup extraction: {error}")
    })?;
    extract_nsis_product_with_runtime(artifact, archive_path, product_dir, Some(&runtime))
}

fn extract_nsis_product_with_runtime(
    artifact: &ToolArtifact,
    archive_path: &Path,
    product_dir: &Path,
    runtime: Option<&archive_runtime::VerifiedRuntime>,
) -> Result<(), String> {
    let runtime = runtime.ok_or_else(|| {
        "verified 7-Zip runtime is required; Nmap setup will not be executed as a fallback"
            .to_string()
    })?;
    let output_switch = format!("-o{}", product_dir.display());
    let mut command = Command::new(runtime.executable());
    command
        .args([
            "x",
            "-y",
            "-aoa",
            "-spe",
            "-bb0",
            "-sccUTF-8",
            &output_switch,
        ])
        .arg(archive_path)
        .args(
            artifact
                .files
                .iter()
                .map(|entry| entry.archive_path.as_str()),
        )
        .args(artifact.trees.iter().map(|tree| tree.archive_glob.as_str()))
        .current_dir(runtime.root())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000);
    let output = command.output().map_err(|error| {
        format!("failed to start verified 7-Zip for static Nmap extraction: {error}")
    })?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "verified 7-Zip could not statically extract Nmap setup: {}",
            stderr.trim().chars().take(2048).collect::<String>()
        ));
    }
    Ok(())
}

fn copy_locked_reader(
    reader: &mut impl Read,
    destination: &Path,
    expected_size: u64,
    expected_sha256: &str,
) -> Result<(), String> {
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| format!("failed to create extracted product file: {error}"))?;
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|error| format!("failed to read extracted product file: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| "extracted product size overflow".to_string())?;
        if total > expected_size {
            return Err("extracted product exceeded its locked size".to_string());
        }
        hasher.update(&buffer[..count]);
        output
            .write_all(&buffer[..count])
            .map_err(|error| format!("failed to write extracted product file: {error}"))?;
    }
    output
        .sync_all()
        .map_err(|error| format!("failed to sync extracted product file: {error}"))?;
    if total != expected_size || format!("{:x}", hasher.finalize()) != expected_sha256 {
        return Err("extracted product failed size or SHA-256 verification".to_string());
    }
    Ok(())
}

fn verify_product(root: &Path, artifact: &ToolArtifact) -> Result<(), String> {
    let metadata = fs::symlink_metadata(root)
        .map_err(|error| format!("unable to inspect managed tool directory: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("managed tool path is not a regular directory".to_string());
    }
    let expected_root = artifact
        .files
        .iter()
        .map(|entry| entry.install_path.clone())
        .chain(artifact.trees.iter().map(|tree| tree.install_root.clone()))
        .collect::<BTreeSet<_>>();
    let mut actual_root = BTreeSet::new();
    for entry in fs::read_dir(root)
        .map_err(|error| format!("unable to enumerate managed tool directory: {error}"))?
    {
        let entry =
            entry.map_err(|error| format!("unable to inspect managed tool entry: {error}"))?;
        let name = entry.file_name().to_string_lossy().to_string();
        validate_relative_path(&name)?;
        let file_type = entry
            .file_type()
            .map_err(|error| format!("unable to inspect managed tool entry type: {error}"))?;
        if file_type.is_symlink() || (!file_type.is_file() && !file_type.is_dir()) {
            return Err(format!(
                "managed tool root contains an unsupported entry: {}",
                entry.path().display()
            ));
        }
        actual_root.insert(name);
    }
    if actual_root != expected_root {
        return Err(format!(
            "product inventory mismatch (missing: {}; extra: {})",
            expected_root
                .difference(&actual_root)
                .cloned()
                .collect::<Vec<_>>()
                .join(", "),
            actual_root
                .difference(&expected_root)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    let canonical_root = fs::canonicalize(root)
        .map_err(|error| format!("unable to resolve managed tool directory: {error}"))?;
    for entry in &artifact.files {
        let relative = validate_relative_path(&entry.install_path)?;
        let path = canonical_root.join(relative);
        let canonical = fs::canonicalize(&path)
            .map_err(|error| format!("unable to resolve managed product file: {error}"))?;
        if !canonical.starts_with(&canonical_root) {
            return Err(format!(
                "managed product file escaped its root: {}",
                entry.install_path
            ));
        }
        let (size, digest) = hash_regular_file(&canonical, entry.size)?;
        if size != entry.size || digest != entry.sha256 {
            return Err(format!(
                "managed product hash mismatch: {}",
                entry.install_path
            ));
        }
    }
    for tree in &artifact.trees {
        let report = tree_manifest(&canonical_root.join(&tree.install_root))?;
        if report.file_count != tree.file_count
            || report.directory_count != tree.directory_count
            || report.total_size != tree.total_size
            || report.sha256 != tree.manifest_sha256
        {
            return Err(format!(
                "managed product tree manifest mismatch: {}",
                tree.install_root
            ));
        }
    }
    verify_pe_machine(
        &canonical_root.join(&artifact.executable),
        &artifact.executable_machine,
    )
}

struct TreeManifest {
    file_count: usize,
    directory_count: usize,
    total_size: u64,
    sha256: String,
}

fn tree_manifest(root: &Path) -> Result<TreeManifest, String> {
    let root_metadata = fs::symlink_metadata(root)
        .map_err(|error| format!("unable to inspect managed product tree: {error}"))?;
    if root_metadata.file_type().is_symlink() || !root_metadata.is_dir() {
        return Err("managed product tree is not a regular directory".to_string());
    }
    let mut pending = vec![root.to_path_buf()];
    let mut records = Vec::new();
    let mut file_count = 0_usize;
    let mut directory_count = 0_usize;
    let mut total_size = 0_u64;
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory)
            .map_err(|error| format!("unable to enumerate managed product tree: {error}"))?
        {
            let entry = entry.map_err(|error| {
                format!("unable to inspect managed product tree entry: {error}")
            })?;
            let file_type = entry
                .file_type()
                .map_err(|error| format!("unable to inspect managed product tree type: {error}"))?;
            if file_type.is_symlink() {
                return Err(format!(
                    "managed product tree contains a symbolic link: {}",
                    entry.path().display()
                ));
            }
            let relative = entry
                .path()
                .strip_prefix(root)
                .map_err(|_| "managed product tree entry escaped its root".to_string())?
                .to_string_lossy()
                .replace('\\', "/");
            validate_relative_path(&relative)?;
            if file_type.is_dir() {
                directory_count = directory_count
                    .checked_add(1)
                    .ok_or_else(|| "managed product tree directory count overflow".to_string())?;
                if directory_count > 512 {
                    return Err("managed product tree contains too many directories".to_string());
                }
                records.push(format!("D\t{relative}\n"));
                pending.push(entry.path());
            } else if file_type.is_file() {
                file_count = file_count
                    .checked_add(1)
                    .ok_or_else(|| "managed product tree file count overflow".to_string())?;
                if file_count > 2_000 {
                    return Err("managed product tree contains too many files".to_string());
                }
                let (size, digest) = hash_regular_file(&entry.path(), MAX_ARTIFACT_BYTES)?;
                total_size = total_size
                    .checked_add(size)
                    .ok_or_else(|| "managed product tree size overflow".to_string())?;
                if total_size > MAX_ARTIFACT_BYTES {
                    return Err("managed product tree exceeded its size limit".to_string());
                }
                records.push(format!("F\t{relative}\t{size}\t{digest}\n"));
            } else {
                return Err(format!(
                    "managed product tree contains an unsupported entry: {}",
                    entry.path().display()
                ));
            }
        }
    }
    records.sort();
    let mut hasher = Sha256::new();
    for record in records {
        hasher.update(record.as_bytes());
    }
    Ok(TreeManifest {
        file_count,
        directory_count,
        total_size,
        sha256: format!("{:x}", hasher.finalize()),
    })
}

fn hash_regular_file(path: &Path, max_bytes: u64) -> Result<(u64, String), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("unable to inspect managed product file: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > max_bytes {
        return Err(format!(
            "managed product entry is not a bounded regular file: {}",
            path.display()
        ));
    }
    let mut file = File::open(path)
        .map_err(|error| format!("unable to open managed product file: {error}"))?;
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("unable to hash managed product file: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| "managed product size overflow".to_string())?;
        if total > max_bytes {
            return Err("managed product exceeded its locked size".to_string());
        }
        hasher.update(&buffer[..count]);
    }
    Ok((total, format!("{:x}", hasher.finalize())))
}

fn verify_pe_machine(path: &Path, expected: &str) -> Result<(), String> {
    let mut file =
        File::open(path).map_err(|error| format!("unable to open managed executable: {error}"))?;
    let mut header = vec![0_u8; 4096];
    let count = file
        .read(&mut header)
        .map_err(|error| format!("unable to read managed executable header: {error}"))?;
    header.truncate(count);
    if header.len() < 0x40 || &header[..2] != b"MZ" {
        return Err("managed executable is not a PE image".to_string());
    }
    let pe_offset = u32::from_le_bytes(header[0x3c..0x40].try_into().unwrap()) as usize;
    if pe_offset
        .checked_add(6)
        .is_none_or(|end| end > header.len())
        || &header[pe_offset..pe_offset + 4] != b"PE\0\0"
    {
        return Err("managed executable has an invalid PE header".to_string());
    }
    let machine = u16::from_le_bytes(header[pe_offset + 4..pe_offset + 6].try_into().unwrap());
    let expected_machine = match expected {
        "x86" => 0x014c,
        "x86_64" => 0x8664,
        _ => return Err(format!("unsupported locked executable machine: {expected}")),
    };
    if machine != expected_machine {
        return Err(format!(
            "managed executable machine mismatch: expected 0x{expected_machine:04x}, found 0x{machine:04x}"
        ));
    }
    Ok(())
}

fn normalize_tools(values: &[String]) -> Vec<String> {
    let selected = values
        .iter()
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| TOOLS.contains(&value.as_str()))
        .collect::<BTreeSet<_>>();
    TOOLS
        .iter()
        .filter(|tool| selected.is_empty() || selected.contains(**tool))
        .map(|tool| (*tool).to_string())
        .collect()
}

fn deserialize_tools<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(match value {
        Value::String(value) => value
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .collect(),
        Value::Array(values) => values
            .into_iter()
            .filter_map(|value| value.as_str().map(str::to_string))
            .collect(),
        _ => Vec::new(),
    })
}

fn task_payload(task: &Task) -> Value {
    let failures = task
        .result
        .as_ref()
        .map(|result| result["failures"].clone())
        .unwrap_or_else(|| json!([]));
    let status = task
        .result
        .as_ref()
        .map(|result| result["status"].clone())
        .unwrap_or(Value::Null);
    json!({
        "success":task.success, "task_id":task.id, "generation":task.generation,
        "running":task.running, "stopped":false,
        "done":task.done, "message":task.message, "progress":task.progress,
        "logs":task.logs, "log_count":task.logs.len(),
        "install_progress":task.install_progress, "failures":failures,
        "error":task.error, "result":task.result, "status":status
    })
}

fn task_id() -> String {
    let mut hasher = Sha256::new();
    hasher.update(now_ms().to_le_bytes());
    hasher.update(std::process::id().to_le_bytes());
    hasher.update(NEXT_ID.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    hasher.finalize()[..16]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::time::Duration;
    use zip::write::SimpleFileOptions;

    struct TempDir(PathBuf);

    impl TempDir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "koi-external-tools-{label}-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn sqlmap_uses_builtin_validator_without_python() {
        let root = TempDir::new("sql");
        let manager = ExternalToolManager::new(root.0.clone()).unwrap();
        let result = manager
            .dispatch("doc.retest.tools.install", &json!({"tools":["sqlmap"]}))
            .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(
            result["installed"][0]["command"][0],
            "koi://builtin/sql-validator"
        );
        assert!(!result.to_string().contains("sqlmap.py"));
    }

    #[test]
    fn concurrent_install_lock_fails_closed_without_network_or_partial_products() {
        let root = TempDir::new("concurrent");
        let _lock = InstallLock::acquire(&root.0).unwrap();
        let manager = ExternalToolManager::new(root.0.clone()).unwrap();
        let result = manager
            .dispatch(
                "doc.retest.tools.install",
                &json!({"tools":["nmap","ffuf"]}),
            )
            .unwrap();
        assert_eq!(result["success"], false);
        assert_eq!(result["failures"].as_array().unwrap().len(), 2);
        assert!(result.to_string().contains("fail-closed lock"));
        assert!(!root.0.join("nmap").exists());
        assert!(!root.0.join("ffuf").exists());
    }

    #[test]
    fn embedded_lock_pins_exact_reviewed_sources_and_hashes() {
        let lock = parse_lock(EMBEDDED_LOCK).expect("parse embedded external tool lock");
        let ffuf = lock
            .artifacts
            .iter()
            .find(|artifact| artifact.tool == "ffuf")
            .unwrap();
        assert_eq!(ffuf.version, "2.2.1");
        assert_eq!(
            ffuf.sha256,
            "717e3d103ee36ce743a18605be66a4424fca27758eebed1e8ebb2eb0a3645589"
        );
        assert_eq!(ffuf.files.len(), 4);
        let nmap = lock
            .artifacts
            .iter()
            .find(|artifact| artifact.tool == "nmap")
            .unwrap();
        assert_eq!(nmap.version, "7.991");
        assert_eq!(
            nmap.sha256,
            "93bfd37bdb31a7adfd932beb5dbce06025da691d01a0939e806ea704f7367657"
        );
        assert!(nmap
            .files
            .iter()
            .any(|entry| entry.install_path == "nmap.exe"));
    }

    #[test]
    fn lock_rejects_source_tree_and_product_inventory_drift() {
        let mut changed: Value = serde_json::from_str(EMBEDDED_LOCK).unwrap();
        changed["artifacts"][1]["url"] = json!("https://example.invalid/nmap.exe");
        assert!(parse_lock(&changed.to_string())
            .unwrap_err()
            .contains("provenance"));

        let mut changed: Value = serde_json::from_str(EMBEDDED_LOCK).unwrap();
        changed["artifacts"][1]["files"][0]["install_path"] = json!("../escape.txt");
        assert!(parse_lock(&changed.to_string()).is_err());

        let mut changed: Value = serde_json::from_str(EMBEDDED_LOCK).unwrap();
        changed["artifacts"][1]["trees"][0]["manifest_sha256"] = json!("0".repeat(64));
        assert!(parse_lock(&changed.to_string())
            .unwrap_err()
            .contains("fingerprints"));
    }

    #[test]
    fn locked_artifact_writer_rejects_truncation_hash_mismatch_and_overflow() {
        let root = TempDir::new("artifact-hash");
        let bytes = b"locked artifact";
        let digest = sha256_bytes(bytes);
        write_locked_artifact(
            &mut Cursor::new(bytes),
            &root.0.join("valid.bin"),
            bytes.len() as u64,
            &digest,
            "fixture",
        )
        .unwrap();

        let truncated = write_locked_artifact(
            &mut Cursor::new(&bytes[..4]),
            &root.0.join("truncated.bin"),
            bytes.len() as u64,
            &digest,
            "fixture",
        )
        .unwrap_err();
        assert!(truncated.contains("size or SHA-256"));

        let mismatch = write_locked_artifact(
            &mut Cursor::new(bytes),
            &root.0.join("mismatch.bin"),
            bytes.len() as u64,
            &"0".repeat(64),
            "fixture",
        )
        .unwrap_err();
        assert!(mismatch.contains("size or SHA-256"));

        let overflow = write_locked_artifact(
            &mut Cursor::new(bytes),
            &root.0.join("overflow.bin"),
            4,
            &digest,
            "fixture",
        )
        .unwrap_err();
        assert!(overflow.contains("exceeded its locked size"));
    }

    #[test]
    fn resumed_download_requires_exact_content_range_offsets() {
        validate_content_range("bytes 4096-8191/16384", 4096, 16384).unwrap();
        assert!(validate_content_range("bytes 0-8191/16384", 4096, 16384)
            .unwrap_err()
            .contains("mismatch"));
        assert!(validate_content_range("bytes 4096-8191/32768", 4096, 16384)
            .unwrap_err()
            .contains("mismatch"));
        assert!(validate_content_range("items 4096-8191/16384", 4096, 16384).is_err());
        assert!(validate_content_range("bytes 4096-16384/16384", 4096, 16384).is_err());
    }

    #[test]
    fn zip_extraction_rejects_traversal_unreviewed_entries_and_bad_hashes() {
        let root = TempDir::new("zip-policy");
        let product = root.0.join("product");
        fs::create_dir(&product).unwrap();
        let bytes = b"fixture";
        let artifact = fixture_artifact("safe.txt", bytes, &sha256_bytes(bytes));

        let traversal = root.0.join("traversal.zip");
        write_zip(&traversal, &[("../safe.txt", bytes)]);
        assert!(extract_zip_product(&artifact, &traversal, &product)
            .unwrap_err()
            .contains("inventory path"));

        let unexpected = root.0.join("unexpected.zip");
        write_zip(&unexpected, &[("other.txt", bytes)]);
        assert!(extract_zip_product(&artifact, &unexpected, &product)
            .unwrap_err()
            .contains("unreviewed entry"));

        let bad_hash = root.0.join("bad-hash.zip");
        write_zip(&bad_hash, &[("safe.txt", bytes)]);
        let bad_artifact = fixture_artifact("safe.txt", bytes, &"0".repeat(64));
        assert!(extract_zip_product(&bad_artifact, &bad_hash, &product)
            .unwrap_err()
            .contains("SHA-256"));
    }

    #[test]
    fn product_inventory_rejects_extra_files_before_executable_use() {
        let root = TempDir::new("product-inventory");
        let bytes = b"fixture";
        let artifact = fixture_artifact("safe.txt", bytes, &sha256_bytes(bytes));
        fs::write(root.0.join("safe.txt"), bytes).unwrap();
        fs::write(root.0.join("unreviewed.dll"), b"extra").unwrap();
        assert!(verify_product(&root.0, &artifact)
            .unwrap_err()
            .contains("inventory mismatch"));
    }

    #[test]
    fn invalid_existing_managed_runtime_is_preserved_and_fails_before_download() {
        let root = TempDir::new("preserve-invalid");
        let destination = root.0.join("nmap");
        fs::create_dir(&destination).unwrap();
        fs::write(destination.join("user-sentinel.txt"), b"preserve").unwrap();
        let lock = parse_lock(EMBEDDED_LOCK).unwrap();
        let error = install_reviewed_tool(&root.0, &lock, "nmap").unwrap_err();
        assert!(error.contains("left unchanged"));
        assert_eq!(
            fs::read(destination.join("user-sentinel.txt")).unwrap(),
            b"preserve"
        );
        assert_eq!(fs::read_dir(&destination).unwrap().count(), 1);
    }

    #[test]
    fn non_directory_tool_root_is_rejected_without_modification() {
        let parent = TempDir::new("root-type");
        let root = parent.0.join("not-a-directory");
        fs::write(&root, b"preserve").unwrap();
        assert!(ExternalToolManager::new(root.clone()).is_err());
        assert_eq!(fs::read(root).unwrap(), b"preserve");
    }

    #[test]
    fn nmap_setup_has_no_execution_fallback_when_7zip_is_missing() {
        let root = TempDir::new("nmap-runtime-missing");
        let artifact = fixture_artifact("nmap.exe", b"fixture", &"0".repeat(64));
        let error = extract_nsis_product_with_runtime(
            &artifact,
            &root.0.join("nmap-setup.exe"),
            &root.0.join("product"),
            None,
        )
        .unwrap_err();
        assert!(error.contains("will not be executed as a fallback"));
    }

    #[test]
    fn tree_manifest_covers_paths_directories_sizes_and_file_hashes() {
        let root = TempDir::new("tree-manifest");
        let tree = root.0.join("tree");
        fs::create_dir_all(tree.join("nested")).unwrap();
        fs::write(tree.join("alpha.txt"), b"alpha").unwrap();
        fs::write(tree.join("nested").join("beta.txt"), b"beta").unwrap();
        let first = tree_manifest(&tree).unwrap();
        assert_eq!(first.file_count, 2);
        assert_eq!(first.directory_count, 1);
        assert_eq!(first.total_size, 9);

        fs::write(tree.join("nested").join("beta.txt"), b"changed").unwrap();
        let tampered = tree_manifest(&tree).unwrap();
        assert_ne!(tampered.sha256, first.sha256);
        fs::create_dir(tree.join("empty-extra")).unwrap();
        let extra_directory = tree_manifest(&tree).unwrap();
        assert_ne!(extra_directory.sha256, tampered.sha256);
    }

    #[test]
    #[ignore = "requires separately downloaded, hash-locked official release archives"]
    fn official_release_archives_match_locked_product_inventories() {
        let lock = parse_lock(EMBEDDED_LOCK).unwrap();
        let ffuf_archive = PathBuf::from(
            std::env::var_os("KOI_AUDIT_FFUF_ARCHIVE")
                .expect("KOI_AUDIT_FFUF_ARCHIVE must point to the official ffuf ZIP"),
        );
        let nmap_archive = PathBuf::from(
            std::env::var_os("KOI_AUDIT_NMAP_ARCHIVE")
                .expect("KOI_AUDIT_NMAP_ARCHIVE must point to the official Nmap setup"),
        );
        for (tool, archive_path) in [("ffuf", ffuf_archive), ("nmap", nmap_archive)] {
            let artifact = lock
                .artifacts
                .iter()
                .find(|artifact| artifact.tool == tool)
                .unwrap();
            let (size, digest) = hash_regular_file(&archive_path, artifact.size).unwrap();
            assert_eq!(size, artifact.size);
            assert_eq!(digest, artifact.sha256);
            let root = TempDir::new(&format!("official-{tool}"));
            let product = root.0.join("product");
            fs::create_dir(&product).unwrap();
            extract_artifact(artifact, &archive_path, &product).unwrap();
            verify_product(&product, artifact).unwrap();
        }
    }

    #[test]
    fn async_task_reaches_terminal_state() {
        let root = TempDir::new("async");
        let manager = ExternalToolManager::new(root.0.clone()).unwrap();
        let started = manager
            .dispatch(
                "doc.retest.tools.install",
                &json!({"tools":["sqlmap"],"async":true}),
            )
            .unwrap();
        let id = started["task_id"].as_str().unwrap().to_string();
        let mut status = started;
        for _ in 0..100 {
            if status["done"] == true {
                break;
            }
            thread::sleep(Duration::from_millis(5));
            status = manager
                .dispatch("doc.retest.tools.install.status", &json!({"task_id":id}))
                .unwrap();
        }
        assert_eq!(status["done"], true);
        assert_eq!(status["success"], true);
        assert_eq!(status["result"]["success"], true);
    }

    fn sha256_bytes(bytes: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        format!("{:x}", hasher.finalize())
    }

    fn fixture_artifact(path: &str, bytes: &[u8], digest: &str) -> ToolArtifact {
        ToolArtifact {
            tool: "ffuf".to_string(),
            version: "fixture".to_string(),
            url: "https://example.invalid/fixture.zip".to_string(),
            size: bytes.len() as u64,
            sha256: digest.to_string(),
            archive_format: "zip".to_string(),
            executable: path.to_string(),
            executable_machine: "x86_64".to_string(),
            license: "MIT".to_string(),
            files: vec![ToolFile {
                archive_path: path.to_string(),
                install_path: path.to_string(),
                size: bytes.len() as u64,
                sha256: digest.to_string(),
                role: "executable".to_string(),
            }],
            trees: Vec::new(),
        }
    }

    fn write_zip(path: &Path, entries: &[(&str, &[u8])]) {
        let file = File::create(path).unwrap();
        let mut writer = zip::ZipWriter::new(file);
        for (name, bytes) in entries {
            writer
                .start_file(*name, SimpleFileOptions::default())
                .unwrap();
            writer.write_all(bytes).unwrap();
        }
        writer.finish().unwrap();
    }
}
