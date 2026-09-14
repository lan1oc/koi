//! Fail-closed runtime verification and Windows AppContainer process launcher
//! for the optional dynamic Python probe.
//!
//! This is deliberately not a Python discovery mechanism. Only a runtime
//! named by a verified lock file below the supplied application directory can
//! be launched. A missing runtime, a hash mismatch, or any sandbox setup error
//! is fatal and never falls back to `python` from `PATH`.

#![allow(dead_code)] // Wired into the retest tool only after probe payload review.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::ffi::OsStr;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufReader, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const LOCK_FILE_NAME: &str = "probe-runtime.lock.json";
pub const EXPECTED_FORMAT: &str = "koi-probe-runtime-v1";
pub const EXPECTED_PLATFORM: &str = "windows-x64";
pub const EXPECTED_RUNTIME_VERSION: &str = "3.13.15";
pub const DEFAULT_MEMORY_LIMIT_BYTES: usize = 512 * 1024 * 1024;
pub const DEFAULT_CPU_LIMIT: Duration = Duration::from_secs(60);
pub const DEFAULT_WALL_LIMIT: Duration = Duration::from_secs(120);
pub const SOURCE_BUILD_MAX_PROCESSES: u32 = 4;
pub const SOURCE_BUILD_CPU_LIMIT: Duration = Duration::from_secs(10 * 60);
pub const SOURCE_BUILD_WALL_LIMIT: Duration = Duration::from_secs(10 * 60);
const MAX_LOCK_BYTES: u64 = 64 * 1024;
const MAX_RUNTIME_FILE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RUNTIME_TOTAL_BYTES: u64 = 512 * 1024 * 1024;
const MAX_RUNTIME_COPY_ATTEMPTS: u64 = 32;
static NEXT_RUNTIME_COPY_ID: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeRuntimeLock {
    pub format: String,
    pub implementation: String,
    pub version: String,
    pub platform: String,
    pub url: String,
    pub license: String,
    pub executable: String,
    /// SHA-256 of the official archive at `url`.
    pub sha256: String,
    /// Exact files extracted into the immutable runtime directory.
    pub files: Vec<LockedRuntimeFile>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LockedRuntimeFile {
    pub path: String,
    pub sha256: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct VerifiedProbeRuntime {
    version: String,
    runtime_root: PathBuf,
    executable: PathBuf,
    source_sha256: String,
    source_url: String,
    license: String,
    files: Vec<LockedRuntimeFile>,
}

impl VerifiedProbeRuntime {
    pub fn version(&self) -> &str {
        &self.version
    }

    pub fn runtime_root(&self) -> &Path {
        &self.runtime_root
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }

    pub fn source_sha256(&self) -> &str {
        &self.source_sha256
    }

    pub fn source_url(&self) -> &str {
        &self.source_url
    }

    pub fn license(&self) -> &str {
        &self.license
    }
}

/// Owns a per-launch copy of the locked runtime.
///
/// The packaged runtime is an immutable trust input shared by every KOI
/// process. AppContainer ACEs must never be added to that shared tree: ACL
/// grant/restore pairs from different processes can otherwise overwrite one
/// another. Each launch therefore executes a freshly copied and re-verified
/// runtime beside its one-time working directory.
struct DisposableProbeRuntime {
    runtime: VerifiedProbeRuntime,
    root: PathBuf,
    cleaned: bool,
}

impl DisposableProbeRuntime {
    fn create(
        source: &VerifiedProbeRuntime,
        request: &ProbeLaunchRequest,
    ) -> Result<Self, ProbeSandboxError> {
        // Revalidate immediately before opening source files. The destination
        // is independently hashed below, closing both discovery-to-copy and
        // copy-to-execution substitution paths.
        validate_verified_runtime_binding(source)?;
        let parent = request.working_directory.parent().ok_or_else(|| {
            ProbeSandboxError::new(
                "runtime-copy-root",
                "working directory has no parent for the disposable runtime",
            )
        })?;
        let parent = parent.canonicalize().map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-root",
                format!("cannot resolve runtime copy parent: {error}"),
            )
        })?;
        let parent_metadata = fs::symlink_metadata(&parent).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-root",
                format!("cannot inspect runtime copy parent: {error}"),
            )
        })?;
        if !parent_metadata.is_dir() || is_reparse_entry(&parent_metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-root",
                "runtime copy parent must be a non-symlink directory",
            ));
        }

        let root = create_disposable_runtime_root(&parent)?;
        let copied = copy_verified_runtime(source, &root);
        let runtime = match copied {
            Ok(runtime) => runtime,
            Err(mut error) => {
                if let Err(cleanup) = fs::remove_dir_all(&root) {
                    error.message.push_str(&format!(
                        "; disposable runtime cleanup also failed: {cleanup}"
                    ));
                }
                return Err(error);
            }
        };

        let disposable = Self {
            runtime,
            root,
            cleaned: false,
        };
        validate_runtime_separation(
            disposable.runtime.runtime_root(),
            &request.working_directory,
        )?;
        for directory in &request.read_only_directories {
            validate_runtime_separation(disposable.runtime.runtime_root(), directory)?;
        }
        Ok(disposable)
    }

    fn runtime(&self) -> &VerifiedProbeRuntime {
        &self.runtime
    }

    fn cleanup(&mut self) -> Result<(), ProbeSandboxError> {
        if self.cleaned {
            return Ok(());
        }
        fs::remove_dir_all(&self.root).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-cleanup",
                format!("cannot remove {}: {error}", self.root.display()),
            )
        })?;
        self.cleaned = true;
        Ok(())
    }
}

impl Drop for DisposableProbeRuntime {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProbeSandboxLimits {
    pub active_process_limit: u32,
    pub process_memory_bytes: usize,
    pub cpu_time_ms: u64,
    pub wall_time_ms: u64,
}

impl Default for ProbeSandboxLimits {
    fn default() -> Self {
        Self {
            active_process_limit: 1,
            process_memory_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
            cpu_time_ms: DEFAULT_CPU_LIMIT.as_millis() as u64,
            wall_time_ms: DEFAULT_WALL_LIMIT.as_millis() as u64,
        }
    }
}

impl ProbeSandboxLimits {
    pub fn source_build() -> Self {
        Self {
            active_process_limit: SOURCE_BUILD_MAX_PROCESSES,
            process_memory_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
            cpu_time_ms: SOURCE_BUILD_CPU_LIMIT.as_millis() as u64,
            wall_time_ms: SOURCE_BUILD_WALL_LIMIT.as_millis() as u64,
        }
    }

    fn validate_probe(&self) -> Result<(), ProbeSandboxError> {
        if self.active_process_limit != 1 {
            return Err(ProbeSandboxError::policy(
                "active process limit must remain exactly one",
            ));
        }
        if self.process_memory_bytes == 0 || self.process_memory_bytes > DEFAULT_MEMORY_LIMIT_BYTES
        {
            return Err(ProbeSandboxError::policy(
                "process memory limit must be between one byte and 512 MiB",
            ));
        }
        if self.cpu_time_ms == 0 || self.cpu_time_ms > DEFAULT_CPU_LIMIT.as_millis() as u64 {
            return Err(ProbeSandboxError::policy(
                "CPU limit must be between 1 ms and 60 seconds",
            ));
        }
        if self.wall_time_ms == 0 || self.wall_time_ms > DEFAULT_WALL_LIMIT.as_millis() as u64 {
            return Err(ProbeSandboxError::policy(
                "wall limit must be between 1 ms and 120 seconds",
            ));
        }
        Ok(())
    }

    fn validate_source_build(&self) -> Result<(), ProbeSandboxError> {
        if self.active_process_limit == 0 || self.active_process_limit > SOURCE_BUILD_MAX_PROCESSES
        {
            return Err(ProbeSandboxError::policy(
                "source build active process limit must be between one and four",
            ));
        }
        if self.process_memory_bytes == 0 || self.process_memory_bytes > DEFAULT_MEMORY_LIMIT_BYTES
        {
            return Err(ProbeSandboxError::policy(
                "source build process memory limit must be between one byte and 512 MiB",
            ));
        }
        if self.cpu_time_ms == 0 || self.cpu_time_ms > SOURCE_BUILD_CPU_LIMIT.as_millis() as u64 {
            return Err(ProbeSandboxError::policy(
                "source build CPU limit must be between 1 ms and 10 minutes",
            ));
        }
        if self.wall_time_ms == 0 || self.wall_time_ms > SOURCE_BUILD_WALL_LIMIT.as_millis() as u64
        {
            return Err(ProbeSandboxError::policy(
                "source build wall limit must be between 1 ms and 10 minutes",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProbeLaunchRequest {
    /// Command-line arguments after the verified Python executable.
    pub arguments: Vec<String>,
    /// One-time directory whose ACL permits the AppContainer to write.
    pub working_directory: PathBuf,
    /// Input directories granted read/execute access, never write access.
    pub read_only_directories: Vec<PathBuf>,
    pub limits: ProbeSandboxLimits,
    /// Enables the Rust HTTP broker. The AppContainer itself receives no
    /// network capability; only these target origins and their current IPs are
    /// authorized for brokered requests.
    pub http_broker: Option<ProbeHttpBrokerLaunch>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProbeHttpBrokerLaunch {
    pub authorized_targets: Vec<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProbeExit {
    pub exit_code: u32,
    pub timed_out: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProbeSandboxSelfTest {
    pub runtime_version: String,
    pub runtime_verified: bool,
    pub appcontainer_launched: bool,
    pub active_process_limit: u32,
    pub process_memory_bytes: usize,
    pub cpu_time_ms: u64,
    pub wall_time_ms: u64,
    pub direct_socket_blocked: bool,
    pub outside_file_access_blocked: bool,
    pub read_only_input_verified: bool,
    pub subprocess_blocked: bool,
    pub job_wall_timeout_verified: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SandboxIsolationReport {
    direct_socket_blocked: bool,
    direct_socket_result: String,
    outside_file_access_blocked: bool,
    read_only_input_verified: bool,
    subprocess_blocked: bool,
}

const SANDBOX_ISOLATION_SELF_TEST: &str = r#"
import json
import pathlib
import socket
import subprocess
import sys

outside, input_path, report_path = sys.argv[1:]

def denied(operation, codes):
    try:
        operation()
    except OSError as error:
        return error.errno in codes or getattr(error, "winerror", None) in codes
    return False

def direct_socket_test():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(("1.1.1.1", 443))
        return False, "connected"
    except OSError as error:
        code = getattr(error, "winerror", None) or error.errno
        return code in (13, 10013), "%s:%s" % (type(error).__name__, code)

def spawn_child():
    subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", "raise SystemExit(0)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=2,
    )

input_file = pathlib.Path(input_path)
direct_blocked, direct_result = direct_socket_test()
report = {
    "direct_socket_blocked": direct_blocked,
    "direct_socket_result": direct_result,
    "outside_file_access_blocked": denied(lambda: pathlib.Path(outside).read_text(encoding="utf-8"), (5, 13)),
    "read_only_input_verified": input_file.read_text(encoding="utf-8") == "immutable-input"
        and denied(lambda: input_file.write_text("tampered", encoding="utf-8"), (5, 13)),
    "subprocess_blocked": denied(spawn_child, (5, 13, 1450, 1816)),
}
pathlib.Path(report_path).write_text(json.dumps(report), encoding="utf-8")
raise SystemExit(0 if report["direct_socket_blocked"] and report["outside_file_access_blocked"] and report["read_only_input_verified"] and report["subprocess_blocked"] else 94)
"#;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProbeSandboxError {
    pub stage: &'static str,
    pub message: String,
}

impl ProbeSandboxError {
    fn new(stage: &'static str, message: impl Into<String>) -> Self {
        Self {
            stage,
            message: message.into(),
        }
    }

    fn policy(message: impl Into<String>) -> Self {
        Self::new("policy", message)
    }
}

impl std::fmt::Display for ProbeSandboxError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "probe sandbox {} failed: {}",
            self.stage, self.message
        )
    }
}

impl std::error::Error for ProbeSandboxError {}

/// Locate and verify the pinned runtime rooted at `application_dir`.
pub fn discover_verified_runtime(
    application_dir: &Path,
) -> Result<VerifiedProbeRuntime, ProbeSandboxError> {
    let application_dir = application_dir.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "runtime-root",
            format!("cannot resolve {}: {error}", application_dir.display()),
        )
    })?;
    if !application_dir.is_dir() {
        return Err(ProbeSandboxError::new(
            "runtime-root",
            format!("{} is not a directory", application_dir.display()),
        ));
    }

    let lock_path = application_dir.join(LOCK_FILE_NAME);
    let metadata = fs::symlink_metadata(&lock_path).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-lock",
            format!("cannot inspect {}: {error}", lock_path.display()),
        )
    })?;
    if !metadata.is_file() || is_reparse_entry(&metadata) || metadata.len() > MAX_LOCK_BYTES {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "lock must be a regular JSON file no larger than 64 KiB",
        ));
    }
    let bytes = fs::read(&lock_path).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-lock",
            format!("cannot read {}: {error}", lock_path.display()),
        )
    })?;
    let lock: ProbeRuntimeLock = serde_json::from_slice(&bytes).map_err(|error| {
        ProbeSandboxError::new("runtime-lock", format!("invalid lock JSON: {error}"))
    })?;
    validate_lock(&lock)?;

    let relative_executable = validated_runtime_path(&lock.executable)?;
    let runtime_root = application_dir.join("probe-runtime");
    let runtime_metadata = fs::symlink_metadata(&runtime_root).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot inspect {}: {error}", runtime_root.display()),
        )
    })?;
    if !runtime_metadata.is_dir() || is_reparse_entry(&runtime_metadata) {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            "probe-runtime must be a non-symlink directory",
        ));
    }
    let runtime_root = runtime_root.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot resolve runtime root: {error}"),
        )
    })?;
    verify_runtime_tree(&runtime_root, &lock.files)?;

    let executable_path = application_dir.join(relative_executable);
    let executable_metadata = fs::symlink_metadata(&executable_path).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot inspect {}: {error}", executable_path.display()),
        )
    })?;
    if !executable_metadata.is_file() || is_reparse_entry(&executable_metadata) {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            "locked executable must be a non-symlink regular file",
        ));
    }
    let executable = executable_path.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot resolve {}: {error}", executable_path.display()),
        )
    })?;
    if !executable.starts_with(&runtime_root) {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            "locked executable resolves outside probe-runtime",
        ));
    }
    if executable.file_name().and_then(|name| name.to_str()) != Some("python.exe") {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            "locked executable must be named python.exe",
        ));
    }

    Ok(VerifiedProbeRuntime {
        version: lock.version,
        runtime_root,
        executable,
        source_sha256: lock.sha256,
        source_url: lock.url,
        license: lock.license,
        files: lock.files,
    })
}

fn validate_lock(lock: &ProbeRuntimeLock) -> Result<(), ProbeSandboxError> {
    if lock.format != EXPECTED_FORMAT {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            format!("unsupported lock format {:?}", lock.format),
        ));
    }
    if lock.implementation != "CPython" {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "implementation must be CPython",
        ));
    }
    if !valid_cpython_version(&lock.version) {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            format!("version must be the reviewed CPython {EXPECTED_RUNTIME_VERSION} release"),
        ));
    }
    if lock.platform != EXPECTED_PLATFORM {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            format!("platform must be {EXPECTED_PLATFORM}"),
        ));
    }
    if !valid_official_python_url(&lock.url, &lock.version) {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "URL must be an HTTPS python.org CPython release artifact for the locked version",
        ));
    }
    if lock.license != "Python-2.0" {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "license must use the reviewed Python-2.0 identifier",
        ));
    }
    validate_sha256("source archive", &lock.sha256)?;
    if lock.files.is_empty() || lock.files.len() > 4096 {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "runtime file manifest must contain between 1 and 4096 files",
        ));
    }
    let executable = validated_runtime_path(&lock.executable)?;
    if executable != Path::new("probe-runtime/python.exe") {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "executable must be exactly probe-runtime/python.exe",
        ));
    }
    let mut unique_paths = HashSet::with_capacity(lock.files.len());
    let mut executable_locked = false;
    for file in &lock.files {
        let path = validated_runtime_path(&file.path)?;
        validate_sha256("runtime file", &file.sha256)?;
        let normalized = normalize_relative_path(&path).to_ascii_lowercase();
        if !unique_paths.insert(normalized) {
            return Err(ProbeSandboxError::new(
                "runtime-lock",
                format!("duplicate runtime path {:?}", file.path),
            ));
        }
        executable_locked |= path == executable;
    }
    if !executable_locked {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "executable must appear in the locked runtime file manifest",
        ));
    }
    Ok(())
}

fn valid_cpython_version(version: &str) -> bool {
    version == EXPECTED_RUNTIME_VERSION
}

fn valid_official_python_url(url: &str, version: &str) -> bool {
    url == format!("https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip")
}

fn validate_sha256(label: &str, digest: &str) -> Result<(), ProbeSandboxError> {
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            format!("{label} SHA-256 must contain exactly 64 hexadecimal characters"),
        ));
    }
    Ok(())
}

fn validated_runtime_path(value: &str) -> Result<PathBuf, ProbeSandboxError> {
    let path = validated_relative_path(value)?;
    let mut components = path.components();
    if components.next() != Some(Component::Normal(OsStr::new("probe-runtime")))
        || components.next().is_none()
    {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "runtime files must be below the probe-runtime directory",
        ));
    }
    Ok(path)
}

fn normalize_relative_path(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/")
}

fn verify_runtime_tree(
    runtime_root: &Path,
    files: &[LockedRuntimeFile],
) -> Result<(), ProbeSandboxError> {
    let mut expected = HashSet::with_capacity(files.len());
    for file in files {
        let relative = validated_runtime_path(&file.path)?;
        let relative_runtime = relative
            .strip_prefix("probe-runtime")
            .map_err(|_| ProbeSandboxError::new("runtime-lock", "invalid runtime path"))?;
        let path = runtime_root.join(relative_runtime);
        let metadata = fs::symlink_metadata(&path).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-file",
                format!("cannot inspect locked file {}: {error}", path.display()),
            )
        })?;
        if !metadata.is_file() || is_reparse_entry(&metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-file",
                format!(
                    "locked runtime file is not a regular non-symlink file: {}",
                    path.display()
                ),
            ));
        }
        let actual = sha256_file(&path)?;
        if !actual.eq_ignore_ascii_case(&file.sha256) {
            return Err(ProbeSandboxError::new(
                "runtime-hash",
                format!("SHA-256 mismatch for {}", path.display()),
            ));
        }
        expected.insert(normalize_relative_path(&relative).to_ascii_lowercase());
    }

    let mut actual = Vec::new();
    collect_regular_files(runtime_root, runtime_root, &mut actual)?;
    if actual
        .into_iter()
        .map(|path| {
            normalize_relative_path(&Path::new("probe-runtime").join(path)).to_ascii_lowercase()
        })
        .any(|path| !expected.contains(&path))
    {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            format!(
                "runtime contains an unlisted file below {}",
                runtime_root.display()
            ),
        ));
    }
    Ok(())
}

fn collect_regular_files(
    root: &Path,
    current: &Path,
    output: &mut Vec<PathBuf>,
) -> Result<(), ProbeSandboxError> {
    for entry in fs::read_dir(current).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot enumerate {}: {error}", current.display()),
        )
    })? {
        let entry =
            entry.map_err(|error| ProbeSandboxError::new("runtime-file", error.to_string()))?;
        let metadata = fs::symlink_metadata(entry.path()).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-file",
                format!("cannot inspect runtime entry: {error}"),
            )
        })?;
        if is_reparse_entry(&metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-file",
                "runtime tree must not contain symbolic links",
            ));
        }
        if metadata.is_dir() {
            collect_regular_files(root, &entry.path(), output)?;
        } else if metadata.is_file() {
            output.push(
                entry
                    .path()
                    .strip_prefix(root)
                    .map_err(|_| {
                        ProbeSandboxError::new("runtime-file", "runtime path escaped root")
                    })?
                    .to_path_buf(),
            );
        } else {
            return Err(ProbeSandboxError::new(
                "runtime-file",
                "runtime tree contains a non-file entry",
            ));
        }
    }
    Ok(())
}

#[cfg(windows)]
fn is_reparse_entry(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
fn is_reparse_entry(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

fn validated_relative_path(value: &str) -> Result<PathBuf, ProbeSandboxError> {
    let path = Path::new(value);
    if value.trim().is_empty() || path.is_absolute() {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "locked path must be a non-empty relative path",
        ));
    }
    if path.components().any(|component| {
        !matches!(component, Component::Normal(_))
            || component
                .as_os_str()
                .to_string_lossy()
                .contains(['/', '\\'])
    }) {
        return Err(ProbeSandboxError::new(
            "runtime-lock",
            "locked path may only contain normal relative components",
        ));
    }
    Ok(path.to_path_buf())
}

fn sha256_file(path: &Path) -> Result<String, ProbeSandboxError> {
    let file = File::open(path).map_err(|error| {
        ProbeSandboxError::new(
            "runtime-hash",
            format!("cannot open {}: {error}", path.display()),
        )
    })?;
    let mut reader = BufReader::new(file);
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = reader.read(&mut buffer).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-hash",
                format!("cannot hash {}: {error}", path.display()),
            )
        })?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn create_disposable_runtime_root(parent: &Path) -> Result<PathBuf, ProbeSandboxError> {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| ProbeSandboxError::new("runtime-copy-root", error.to_string()))?
        .as_nanos();
    for attempt in 0..MAX_RUNTIME_COPY_ATTEMPTS {
        let sequence = NEXT_RUNTIME_COPY_ID.fetch_add(1, Ordering::Relaxed);
        let candidate = parent.join(format!(
            ".koi-probe-runtime-{}-{nonce:x}-{sequence:x}-{attempt:x}",
            std::process::id()
        ));
        match fs::create_dir(&candidate) {
            Ok(()) => {
                let metadata = fs::symlink_metadata(&candidate).map_err(|error| {
                    ProbeSandboxError::new(
                        "runtime-copy-root",
                        format!("cannot inspect new runtime directory: {error}"),
                    )
                })?;
                if !metadata.is_dir() || is_reparse_entry(&metadata) {
                    let _ = fs::remove_dir_all(&candidate);
                    return Err(ProbeSandboxError::new(
                        "runtime-copy-root",
                        "new runtime directory is not a regular non-symlink directory",
                    ));
                }
                return candidate.canonicalize().map_err(|error| {
                    let _ = fs::remove_dir_all(&candidate);
                    ProbeSandboxError::new(
                        "runtime-copy-root",
                        format!("cannot resolve new runtime directory: {error}"),
                    )
                });
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(ProbeSandboxError::new(
                    "runtime-copy-root",
                    format!("cannot create disposable runtime directory: {error}"),
                ))
            }
        }
    }
    Err(ProbeSandboxError::new(
        "runtime-copy-root",
        "could not allocate a unique disposable runtime directory",
    ))
}

fn copy_verified_runtime(
    source: &VerifiedProbeRuntime,
    destination_root: &Path,
) -> Result<VerifiedProbeRuntime, ProbeSandboxError> {
    let mut copied_total = 0_u64;
    for locked in &source.files {
        let locked_path = validated_runtime_path(&locked.path)?;
        let relative = locked_path
            .strip_prefix("probe-runtime")
            .map_err(|_| ProbeSandboxError::new("runtime-lock", "invalid runtime path"))?;
        let source_path = source.runtime_root.join(relative);
        let source_metadata = fs::symlink_metadata(&source_path).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-source",
                format!("cannot inspect {}: {error}", source_path.display()),
            )
        })?;
        if !source_metadata.is_file() || is_reparse_entry(&source_metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-source",
                format!(
                    "runtime source is not a regular non-symlink file: {}",
                    source_path.display()
                ),
            ));
        }
        if source_metadata.len() == 0 || source_metadata.len() > MAX_RUNTIME_FILE_BYTES {
            return Err(ProbeSandboxError::new(
                "runtime-copy-source",
                format!(
                    "runtime source file exceeds the bounded copy size: {}",
                    source_path.display()
                ),
            ));
        }
        copied_total = copied_total
            .checked_add(source_metadata.len())
            .ok_or_else(|| {
                ProbeSandboxError::new("runtime-copy-source", "runtime size overflow")
            })?;
        if copied_total > MAX_RUNTIME_TOTAL_BYTES {
            return Err(ProbeSandboxError::new(
                "runtime-copy-source",
                "runtime copy exceeds the 512 MiB total limit",
            ));
        }

        let destination = destination_root.join(relative);
        if let Some(parent) = destination.parent() {
            create_runtime_copy_directories(destination_root, parent)?;
        }
        let input = File::open(&source_path).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-source",
                format!("cannot open {}: {error}", source_path.display()),
            )
        })?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&destination)
            .map_err(|error| {
                ProbeSandboxError::new(
                    "runtime-copy-destination",
                    format!("cannot create {}: {error}", destination.display()),
                )
            })?;
        let copied = io::copy(
            &mut input.take(source_metadata.len().saturating_add(1)),
            &mut output,
        )
        .map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy",
                format!(
                    "cannot copy {} to {}: {error}",
                    source_path.display(),
                    destination.display()
                ),
            )
        })?;
        if copied != source_metadata.len() {
            return Err(ProbeSandboxError::new(
                "runtime-copy-source",
                format!(
                    "runtime source size changed while copying {}",
                    source_path.display()
                ),
            ));
        }
        output.flush().map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy",
                format!("cannot flush {}: {error}", destination.display()),
            )
        })?;
        output.sync_all().map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy",
                format!("cannot sync {}: {error}", destination.display()),
            )
        })?;
        drop(output);

        let metadata = fs::symlink_metadata(&destination).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-destination",
                format!("cannot inspect {}: {error}", destination.display()),
            )
        })?;
        if !metadata.is_file() || is_reparse_entry(&metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-destination",
                "copied runtime entry is not a regular non-symlink file",
            ));
        }
        let actual = sha256_file(&destination)?;
        if !actual.eq_ignore_ascii_case(&locked.sha256) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-hash",
                format!("SHA-256 mismatch for copied file {}", destination.display()),
            ));
        }
    }

    verify_runtime_tree(destination_root, &source.files)?;
    let executable = destination_root.join(
        source
            .executable
            .strip_prefix(&source.runtime_root)
            .map_err(|_| {
                ProbeSandboxError::new(
                    "runtime-copy-destination",
                    "locked executable escaped its verified runtime root",
                )
            })?,
    );
    let executable = executable.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "runtime-copy-destination",
            format!("cannot resolve copied executable: {error}"),
        )
    })?;
    if !executable.starts_with(destination_root) {
        return Err(ProbeSandboxError::new(
            "runtime-copy-destination",
            "copied executable resolves outside the disposable runtime",
        ));
    }
    let copied = VerifiedProbeRuntime {
        version: source.version.clone(),
        runtime_root: destination_root.to_path_buf(),
        executable,
        source_sha256: source.source_sha256.clone(),
        source_url: source.source_url.clone(),
        license: source.license.clone(),
        files: source.files.clone(),
    };
    validate_verified_runtime_binding(&copied)?;
    Ok(copied)
}

fn create_runtime_copy_directories(root: &Path, directory: &Path) -> Result<(), ProbeSandboxError> {
    let relative = directory.strip_prefix(root).map_err(|_| {
        ProbeSandboxError::new(
            "runtime-copy-destination",
            "runtime copy directory escaped its destination root",
        )
    })?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        if !matches!(component, Component::Normal(_)) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-destination",
                "runtime copy directory contains an invalid component",
            ));
        }
        current.push(component.as_os_str());
        match fs::create_dir(&current) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => {
                return Err(ProbeSandboxError::new(
                    "runtime-copy-destination",
                    format!("cannot create {}: {error}", current.display()),
                ))
            }
        }
        let metadata = fs::symlink_metadata(&current).map_err(|error| {
            ProbeSandboxError::new(
                "runtime-copy-destination",
                format!("cannot inspect {}: {error}", current.display()),
            )
        })?;
        if !metadata.is_dir() || is_reparse_entry(&metadata) {
            return Err(ProbeSandboxError::new(
                "runtime-copy-destination",
                "runtime copy directory is not a regular non-symlink directory",
            ));
        }
    }
    Ok(())
}

pub fn run_verified_probe(
    runtime: &VerifiedProbeRuntime,
    request: &ProbeLaunchRequest,
) -> Result<ProbeExit, ProbeSandboxError> {
    request.limits.validate_probe()?;
    validate_launch_request(runtime, request)?;
    platform::run(runtime, request)
}

/// Run a reviewed source-package builder in a separate, networkless sandbox.
/// This entry point deliberately does not accept the Rust HTTP broker and has
/// a distinct four-process/ten-minute policy from dynamic probes.
pub fn run_verified_source_build(
    runtime: &VerifiedProbeRuntime,
    request: &ProbeLaunchRequest,
) -> Result<ProbeExit, ProbeSandboxError> {
    request.limits.validate_source_build()?;
    if request.http_broker.is_some() {
        return Err(ProbeSandboxError::policy(
            "source build sandbox must not receive an HTTP broker",
        ));
    }
    validate_launch_request(runtime, request)?;
    platform::run(runtime, request)
}

fn validate_launch_request(
    runtime: &VerifiedProbeRuntime,
    request: &ProbeLaunchRequest,
) -> Result<(), ProbeSandboxError> {
    validate_arguments(&request.arguments)?;
    validate_verified_runtime_binding(runtime)?;
    validate_working_directory(&request.working_directory)?;
    validate_runtime_separation(runtime.runtime_root(), &request.working_directory)?;
    for directory in &request.read_only_directories {
        validate_input_directory(directory, &request.working_directory)?;
        validate_runtime_separation(runtime.runtime_root(), directory)?;
    }
    Ok(())
}

fn validate_runtime_separation(
    runtime_root: &Path,
    directory: &Path,
) -> Result<(), ProbeSandboxError> {
    let runtime = runtime_root.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "runtime-file",
            format!("cannot resolve runtime root: {error}"),
        )
    })?;
    let directory = directory.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "sandbox-layout",
            format!("cannot resolve sandbox directory: {error}"),
        )
    })?;
    if runtime.starts_with(&directory) || directory.starts_with(&runtime) {
        return Err(ProbeSandboxError::policy(
            "runtime, read-only input, and writable work directories must not overlap",
        ));
    }
    Ok(())
}

/// Exercise runtime verification, AppContainer creation, suspended launch,
/// Job assignment, resume, and exit under the production limits.
pub fn run_sandbox_self_test(
    application_dir: &Path,
    working_directory: &Path,
) -> Result<ProbeSandboxSelfTest, ProbeSandboxError> {
    let runtime = discover_verified_runtime(application_dir)?;
    let limits = ProbeSandboxLimits::default();
    validate_working_directory(working_directory)?;
    let parent = working_directory.parent().ok_or_else(|| {
        ProbeSandboxError::new("self-test", "self-test work directory has no parent")
    })?;
    let fixtures = create_disposable_runtime_root(parent)?;
    let result = (|| {
        let input_directory = fixtures.join("inputs");
        fs::create_dir(&input_directory)
            .map_err(|error| ProbeSandboxError::new("self-test", error.to_string()))?;
        let input_path = input_directory.join("input.txt");
        let outside_path = fixtures.join("outside.txt");
        fs::write(&input_path, b"immutable-input")
            .and_then(|_| fs::write(&outside_path, b"private-outside-input"))
            .map_err(|error| ProbeSandboxError::new("self-test", error.to_string()))?;
        let output = working_directory.join("isolation-report.json");
        let exit = run_verified_probe(
            &runtime,
            &ProbeLaunchRequest {
                arguments: vec![
                    "-I".to_string(),
                    "-S".to_string(),
                    "-B".to_string(),
                    "-c".to_string(),
                    SANDBOX_ISOLATION_SELF_TEST.to_string(),
                    outside_path.to_string_lossy().into_owned(),
                    input_path.to_string_lossy().into_owned(),
                    output.to_string_lossy().into_owned(),
                ],
                working_directory: working_directory.to_path_buf(),
                read_only_directories: vec![input_directory],
                limits: limits.clone(),
                http_broker: None,
            },
        )?;
        let metadata = fs::symlink_metadata(&output)
            .map_err(|error| ProbeSandboxError::new("self-test", error.to_string()))?;
        if !metadata.is_file() || is_reparse_entry(&metadata) || metadata.len() > 64 * 1024 {
            return Err(ProbeSandboxError::new(
                "self-test",
                "OS isolation report is not a bounded regular file",
            ));
        }
        let report: SandboxIsolationReport = serde_json::from_slice(
            &fs::read(&output)
                .map_err(|error| ProbeSandboxError::new("self-test", error.to_string()))?,
        )
        .map_err(|error| ProbeSandboxError::new("self-test", error.to_string()))?;
        if exit.timed_out || exit.exit_code != 0 {
            return Err(ProbeSandboxError::new(
                "self-test",
                format!(
                    "OS isolation self-test exited with code {} (timed_out={}, direct_socket={})",
                    exit.exit_code, exit.timed_out, report.direct_socket_result
                ),
            ));
        }
        if !report.direct_socket_blocked
            || !report.outside_file_access_blocked
            || !report.read_only_input_verified
            || !report.subprocess_blocked
            || fs::read(&input_path).ok().as_deref() != Some(b"immutable-input")
        {
            return Err(ProbeSandboxError::new(
                "self-test",
                "an operating-system isolation assertion failed",
            ));
        }
        let timeout_exit = run_verified_probe(
            &runtime,
            &ProbeLaunchRequest {
                arguments: vec![
                    "-I".to_string(),
                    "-S".to_string(),
                    "-B".to_string(),
                    "-c".to_string(),
                    "while True: pass".to_string(),
                ],
                working_directory: working_directory.to_path_buf(),
                read_only_directories: Vec::new(),
                limits: ProbeSandboxLimits {
                    wall_time_ms: 250,
                    ..limits.clone()
                },
                http_broker: None,
            },
        )?;
        if !timeout_exit.timed_out {
            return Err(ProbeSandboxError::new(
                "self-test",
                "Job Object did not terminate the infinite-loop probe at the wall limit",
            ));
        }
        Ok(ProbeSandboxSelfTest {
            runtime_version: runtime.version().to_string(),
            runtime_verified: true,
            appcontainer_launched: true,
            active_process_limit: limits.active_process_limit,
            process_memory_bytes: limits.process_memory_bytes,
            cpu_time_ms: limits.cpu_time_ms,
            wall_time_ms: limits.wall_time_ms,
            direct_socket_blocked: report.direct_socket_blocked,
            outside_file_access_blocked: report.outside_file_access_blocked,
            read_only_input_verified: report.read_only_input_verified,
            subprocess_blocked: report.subprocess_blocked,
            job_wall_timeout_verified: timeout_exit.timed_out,
        })
    })();
    let cleanup = fs::remove_dir_all(&fixtures)
        .map_err(|error| ProbeSandboxError::new("self-test-cleanup", error.to_string()));
    match (result, cleanup) {
        (Ok(report), Ok(())) => Ok(report),
        (Err(error), Ok(())) | (Ok(_), Err(error)) => Err(error),
        (Err(mut error), Err(cleanup_error)) => {
            error.message.push_str(&format!("; {cleanup_error}"));
            Err(error)
        }
    }
}

fn validate_arguments(arguments: &[String]) -> Result<(), ProbeSandboxError> {
    if arguments.iter().any(|argument| argument.contains('\0')) {
        return Err(ProbeSandboxError::policy(
            "probe arguments must not contain NUL characters",
        ));
    }
    let units = arguments
        .iter()
        .map(|argument| argument.encode_utf16().count() + 3)
        .sum::<usize>();
    if units > 24_000 {
        return Err(ProbeSandboxError::policy(
            "probe argument payload exceeds the bounded command-line size",
        ));
    }
    Ok(())
}

fn validate_verified_runtime_binding(
    runtime: &VerifiedProbeRuntime,
) -> Result<(), ProbeSandboxError> {
    if !runtime.runtime_root.is_absolute()
        || !runtime.runtime_root.is_dir()
        || !runtime.executable.is_absolute()
        || !runtime.executable.is_file()
        || !runtime.executable.starts_with(&runtime.runtime_root)
    {
        return Err(ProbeSandboxError::new(
            "runtime-file",
            "verified runtime binding is unavailable",
        ));
    }
    verify_runtime_tree(&runtime.runtime_root, &runtime.files)
}

fn validate_working_directory(path: &Path) -> Result<(), ProbeSandboxError> {
    if !path.is_absolute() {
        return Err(ProbeSandboxError::policy(
            "working directory must be absolute",
        ));
    }
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        ProbeSandboxError::new(
            "working-directory",
            format!("cannot inspect {}: {error}", path.display()),
        )
    })?;
    if !metadata.is_dir() || is_reparse_entry(&metadata) {
        return Err(ProbeSandboxError::new(
            "working-directory",
            "working directory must be an existing non-symlink directory",
        ));
    }
    Ok(())
}

fn validate_input_directory(
    path: &Path,
    working_directory: &Path,
) -> Result<(), ProbeSandboxError> {
    if !path.is_absolute() {
        return Err(ProbeSandboxError::policy(
            "read-only input directory must be absolute",
        ));
    }
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        ProbeSandboxError::new(
            "input-directory",
            format!("cannot inspect {}: {error}", path.display()),
        )
    })?;
    if !metadata.is_dir() || is_reparse_entry(&metadata) {
        return Err(ProbeSandboxError::new(
            "input-directory",
            "input directory must be an existing non-symlink directory",
        ));
    }
    let input = path.canonicalize().map_err(|error| {
        ProbeSandboxError::new("input-directory", format!("cannot resolve input: {error}"))
    })?;
    let working = working_directory.canonicalize().map_err(|error| {
        ProbeSandboxError::new(
            "working-directory",
            format!("cannot resolve working directory: {error}"),
        )
    })?;
    if input.starts_with(&working) || working.starts_with(&input) {
        return Err(ProbeSandboxError::policy(
            "read-only input and writable working directory must not overlap",
        ));
    }
    Ok(())
}

#[cfg(all(windows, target_arch = "x86_64"))]
mod platform {
    use super::super::probe_broker::{
        ProbeBroker, MAX_BROKER_FRAME_BYTES, PROBE_BROKER_PROTOCOL_VERSION,
    };
    use super::{
        is_reparse_entry, DisposableProbeRuntime, ProbeExit, ProbeHttpBrokerLaunch,
        ProbeLaunchRequest, ProbeSandboxError, VerifiedProbeRuntime,
    };
    use std::ffi::{c_void, OsStr};
    use std::fs;
    use std::mem::size_of;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;
    use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
    use std::sync::Arc;
    use std::thread::{self, JoinHandle};
    use std::time::{SystemTime, UNIX_EPOCH};
    use windows::core::{HRESULT, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{
        CloseHandle, LocalFree, ERROR_BROKEN_PIPE, ERROR_FILE_NOT_FOUND, ERROR_PIPE_CONNECTED,
        ERROR_SUCCESS, GENERIC_READ, GENERIC_WRITE, HANDLE, HLOCAL, WAIT_OBJECT_0, WAIT_TIMEOUT,
    };
    use windows::Win32::Security::Authorization::{
        ConvertSidToStringSidW, ConvertStringSecurityDescriptorToSecurityDescriptorW,
        GetNamedSecurityInfoW, SetEntriesInAclW, SetNamedSecurityInfoW, EXPLICIT_ACCESS_W,
        GRANT_ACCESS, SDDL_REVISION_1, SE_FILE_OBJECT, TRUSTEE_IS_SID, TRUSTEE_IS_UNKNOWN,
        TRUSTEE_W,
    };
    use windows::Win32::Security::Cryptography::{
        BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
    };
    use windows::Win32::Security::Isolation::{
        CreateAppContainerProfile, DeleteAppContainerProfile,
    };
    use windows::Win32::Security::{
        ACL, DACL_SECURITY_INFORMATION, NO_INHERITANCE, PSECURITY_DESCRIPTOR, PSID,
        SECURITY_ATTRIBUTES, SECURITY_CAPABILITIES, SUB_CONTAINERS_AND_OBJECTS_INHERIT,
    };
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, ReadFile, WriteFile, DELETE, FILE_ATTRIBUTE_NORMAL, FILE_DELETE_CHILD,
        FILE_FLAG_FIRST_PIPE_INSTANCE, FILE_GENERIC_EXECUTE, FILE_GENERIC_READ, FILE_GENERIC_WRITE,
        FILE_SHARE_MODE, OPEN_EXISTING, PIPE_ACCESS_DUPLEX,
    };
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOB_OBJECT_LIMIT_PROCESS_MEMORY, JOB_OBJECT_LIMIT_PROCESS_TIME,
    };
    use windows::Win32::System::Pipes::{
        ConnectNamedPipe, CreateNamedPipeW, GetNamedPipeClientProcessId, PIPE_READMODE_BYTE,
        PIPE_REJECT_REMOTE_CLIENTS, PIPE_TYPE_BYTE, PIPE_WAIT,
    };
    use windows::Win32::System::Threading::{
        CreateProcessW, DeleteProcThreadAttributeList, GetExitCodeProcess,
        InitializeProcThreadAttributeList, ResumeThread, TerminateProcess,
        UpdateProcThreadAttribute, WaitForSingleObject, CREATE_SUSPENDED,
        CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT, LPPROC_THREAD_ATTRIBUTE_LIST,
        PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, STARTUPINFOEXW,
    };

    const TERMINATED_EXIT_CODE: u32 = 0x4B4F_4901;
    const MAX_ACL_TREE_ENTRIES: usize = 100_000;
    static NEXT_PROFILE_ID: AtomicU64 = AtomicU64::new(0);
    pub(super) fn run(
        runtime: &VerifiedProbeRuntime,
        request: &ProbeLaunchRequest,
    ) -> Result<ProbeExit, ProbeSandboxError> {
        let mut isolated = DisposableProbeRuntime::create(runtime, request)?;
        let result = unsafe {
            match AppContainerSid::create_unique() {
                Err(error) => Err(error),
                Ok(mut app_container) => {
                    let result = run_windows(isolated.runtime(), request, app_container.sid());
                    let cleanup = app_container.cleanup();
                    match (result, cleanup) {
                        (Ok(exit), Ok(())) => Ok(exit),
                        (Err(error), Ok(())) => Err(error),
                        (Ok(_), Err(error)) => Err(error),
                        (Err(mut error), Err(cleanup_error)) => {
                            error.message.push_str(&format!("; {cleanup_error}"));
                            Err(error)
                        }
                    }
                }
            }
        };
        let cleanup = isolated.cleanup();
        match (result, cleanup) {
            (Ok(exit), Ok(())) => Ok(exit),
            (Err(error), Ok(())) => Err(error),
            (Ok(_), Err(error)) => Err(error),
            (Err(mut error), Err(cleanup_error)) => {
                error.message.push_str(&format!("; {cleanup_error}"));
                Err(error)
            }
        }
    }

    unsafe fn run_windows(
        runtime: &VerifiedProbeRuntime,
        request: &ProbeLaunchRequest,
        app_container_sid: PSID,
    ) -> Result<ProbeExit, ProbeSandboxError> {
        let _working_acl = grant_directory_access_tree(
            &request.working_directory,
            app_container_sid,
            DirectoryAccess::ReadWrite,
        )?;
        let _runtime_acl = grant_directory_access_tree(
            runtime.runtime_root(),
            app_container_sid,
            DirectoryAccess::ReadOnly,
        )?;
        let mut _input_acls = Vec::with_capacity(request.read_only_directories.len());
        for directory in &request.read_only_directories {
            _input_acls.push(grant_directory_access_tree(
                directory,
                app_container_sid,
                DirectoryAccess::ReadOnly,
            )?);
        }
        let job = OwnedHandle::new(
            CreateJobObjectW(None, PCWSTR::null())
                .map_err(|error| win_error("job-create", error))?,
        );
        configure_job(job.0, request)?;

        let broker = request
            .http_broker
            .as_ref()
            .map(|launch| NamedPipeBroker::create(app_container_sid, launch))
            .transpose()?;
        let broker_environment = broker.as_ref().map(NamedPipeBroker::environment);

        let mut attributes = AttributeList::new()?;
        let mut capabilities = SECURITY_CAPABILITIES {
            AppContainerSid: app_container_sid,
            Capabilities: null_mut(),
            CapabilityCount: 0,
            Reserved: 0,
        };
        UpdateProcThreadAttribute(
            attributes.pointer(),
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES as usize,
            Some((&mut capabilities as *mut SECURITY_CAPABILITIES).cast()),
            size_of::<SECURITY_CAPABILITIES>(),
            None,
            None,
        )
        .map_err(|error| win_error("appcontainer-attribute", error))?;

        // `canonicalize` on Windows may return an extended-length `\\?\` path.
        // CreateProcessW accepts those paths in many cases, but its application
        // name/current-directory handling is inconsistent when an explicit
        // environment block and AppContainer attributes are present (it can
        // report ERROR_ENVVAR_NOT_FOUND before creating the process).  Feed the
        // Win32 API a canonical DOS/UNC path while retaining the verified
        // canonical paths for all security checks above.
        let executable_path = win32_process_path(&runtime.executable)?;
        let executable = wide(executable_path.as_os_str());
        let mut command_line = wide(OsStr::new(&build_command_line(
            &executable_path.to_string_lossy(),
            &request.arguments,
        )));
        let current_directory_path = win32_process_path(&request.working_directory)?;
        let current_directory = wide(current_directory_path.as_os_str());
        let environment =
            sanitized_environment(&request.working_directory, broker_environment.as_ref())?;
        let mut startup = STARTUPINFOEXW::default();
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.lpAttributeList = attributes.pointer();
        let mut process_info = PROCESS_INFORMATION::default();

        CreateProcessW(
            PCWSTR(executable.as_ptr()),
            Some(PWSTR(command_line.as_mut_ptr())),
            None,
            None,
            false,
            CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
            Some(environment.as_ptr().cast()),
            PCWSTR(current_directory.as_ptr()),
            &startup.StartupInfo,
            &mut process_info,
        )
        .map_err(|error| win_error("process-create-suspended", error))?;
        let process = OwnedHandle::new(process_info.hProcess);
        let thread = OwnedHandle::new(process_info.hThread);

        if let Err(error) = AssignProcessToJobObject(job.0, process.0) {
            let _ = TerminateProcess(process.0, TERMINATED_EXIT_CODE);
            let _ = WaitForSingleObject(process.0, 5_000);
            return Err(win_error("job-assign", error));
        }
        let active_broker = broker.map(|server| server.spawn(process_info.dwProcessId));
        if ResumeThread(thread.0) == u32::MAX {
            let _ = TerminateJobObject(job.0, TERMINATED_EXIT_CODE);
            let _ = WaitForSingleObject(process.0, 5_000);
            finish_broker(active_broker)?;
            return Err(ProbeSandboxError::new(
                "process-resume",
                "ResumeThread returned failure",
            ));
        }

        let wait = WaitForSingleObject(process.0, request.limits.wall_time_ms as u32);
        if wait == WAIT_TIMEOUT {
            TerminateJobObject(job.0, TERMINATED_EXIT_CODE)
                .map_err(|error| win_error("timeout-terminate", error))?;
            let _ = WaitForSingleObject(process.0, 5_000);
            finish_broker(active_broker)?;
            return Ok(ProbeExit {
                exit_code: TERMINATED_EXIT_CODE,
                timed_out: true,
            });
        }
        if wait != WAIT_OBJECT_0 {
            let _ = TerminateJobObject(job.0, TERMINATED_EXIT_CODE);
            let _ = WaitForSingleObject(process.0, 5_000);
            finish_broker(active_broker)?;
            return Err(ProbeSandboxError::new(
                "process-wait",
                format!("unexpected wait result {}", wait.0),
            ));
        }
        let mut exit_code = 0_u32;
        GetExitCodeProcess(process.0, &mut exit_code)
            .map_err(|error| win_error("process-exit", error))?;
        finish_broker(active_broker)?;
        Ok(ProbeExit {
            exit_code,
            timed_out: false,
        })
    }

    fn finish_broker(broker: Option<ActiveNamedPipeBroker>) -> Result<(), ProbeSandboxError> {
        match broker {
            Some(broker) => broker.finish(),
            None => Ok(()),
        }
    }

    struct BrokerEnvironment {
        pipe_name: String,
        token: String,
    }

    struct NamedPipeBroker {
        handle: OwnedHandle,
        pipe_name: String,
        token: String,
        broker: ProbeBroker,
    }

    impl NamedPipeBroker {
        unsafe fn create(
            app_container_sid: PSID,
            launch: &ProbeHttpBrokerLaunch,
        ) -> Result<Self, ProbeSandboxError> {
            if launch.authorized_targets.is_empty() || launch.authorized_targets.len() > 32 {
                return Err(ProbeSandboxError::new(
                    "broker-policy",
                    "HTTP broker requires between one and 32 authorized targets",
                ));
            }
            let mut random = [0_u8; 32];
            let status = BCryptGenRandom(None, &mut random, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
            if status.0 != 0 {
                return Err(ProbeSandboxError::new(
                    "broker-random",
                    format!("BCryptGenRandom failed with NTSTATUS 0x{:08x}", status.0),
                ));
            }
            let token = hex(&random);
            let pipe_name = format!(r"\\.\pipe\Koi.DynamicProbe.{}", hex(&random[..16]));
            let broker = ProbeBroker::new(token.clone(), &launch.authorized_targets)
                .map_err(|error| ProbeSandboxError::new("broker-policy", error.to_string()))?;

            let mut sid_text = PWSTR::null();
            ConvertSidToStringSidW(app_container_sid, &mut sid_text)
                .map_err(|error| win_error("broker-pipe-sid", error))?;
            let sid_text_owner = OwnedLocal::new(sid_text.0.cast());
            let sid = sid_text
                .to_string()
                .map_err(|error| ProbeSandboxError::new("broker-pipe-sid", error.to_string()))?;
            let sddl = wide(OsStr::new(&format!(
                "D:P(A;;GA;;;SY)(A;;GA;;;OW)(A;;GRGW;;;{sid})"
            )));
            let mut descriptor = PSECURITY_DESCRIPTOR::default();
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                PCWSTR(sddl.as_ptr()),
                SDDL_REVISION_1,
                &mut descriptor,
                None,
            )
            .map_err(|error| win_error("broker-pipe-acl", error))?;
            let descriptor_owner = OwnedLocal::new(descriptor.0);
            let attributes = SECURITY_ATTRIBUTES {
                nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: descriptor.0,
                bInheritHandle: false.into(),
            };
            let pipe_wide = wide(OsStr::new(&pipe_name));
            let handle = CreateNamedPipeW(
                PCWSTR(pipe_wide.as_ptr()),
                PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                64 * 1024,
                64 * 1024,
                0,
                Some(&attributes),
            );
            if handle.is_invalid() {
                return Err(win_error(
                    "broker-pipe-create",
                    windows::core::Error::from_win32(),
                ));
            }
            drop(descriptor_owner);
            drop(sid_text_owner);
            Ok(Self {
                handle: OwnedHandle::new(handle),
                pipe_name,
                token,
                broker,
            })
        }

        fn environment(&self) -> BrokerEnvironment {
            BrokerEnvironment {
                pipe_name: self.pipe_name.clone(),
                token: self.token.clone(),
            }
        }

        fn spawn(self, expected_process_id: u32) -> ActiveNamedPipeBroker {
            let NamedPipeBroker {
                handle,
                pipe_name,
                token,
                broker,
            } = self;
            let active_pipe_name = pipe_name.clone();
            let shutdown = Arc::new(AtomicBool::new(false));
            let server_shutdown = Arc::clone(&shutdown);
            // Raw Win32 handles are process-local but the ownership wrapper is
            // intentionally moved to the broker thread. Send the numeric
            // handle value and reconstruct it there so Rust does not infer a
            // cross-thread raw-pointer transfer.
            let raw_handle = handle.0 .0 as usize;
            std::mem::forget(handle);
            let join = thread::spawn(move || {
                let server = NamedPipeBroker {
                    handle: OwnedHandle::new(HANDLE(raw_handle as *mut c_void)),
                    pipe_name,
                    token,
                    broker,
                };
                server.serve(expected_process_id, &server_shutdown)
            });
            ActiveNamedPipeBroker {
                pipe_name: active_pipe_name,
                shutdown,
                join,
            }
        }

        fn serve(
            mut self,
            expected_process_id: u32,
            shutdown: &AtomicBool,
        ) -> Result<(), ProbeSandboxError> {
            unsafe {
                if let Err(error) = ConnectNamedPipe(self.handle.0, None) {
                    if error.code() != HRESULT::from_win32(ERROR_PIPE_CONNECTED.0) {
                        return Err(win_error("broker-pipe-connect", error));
                    }
                }
                let mut client_process_id = 0_u32;
                GetNamedPipeClientProcessId(self.handle.0, &mut client_process_id)
                    .map_err(|error| win_error("broker-pipe-client", error))?;
                if client_process_id != expected_process_id {
                    if shutdown.load(Ordering::Acquire) && client_process_id == std::process::id() {
                        return Ok(());
                    }
                    return Err(ProbeSandboxError::new(
                        "broker-pipe-client",
                        "named-pipe client is not the sandboxed probe process",
                    ));
                }

                loop {
                    let mut length_bytes = [0_u8; 4];
                    if !read_pipe_exact(self.handle.0, &mut length_bytes)? {
                        return Ok(());
                    }
                    let length = u32::from_le_bytes(length_bytes) as usize;
                    if length == 0 || length > MAX_BROKER_FRAME_BYTES {
                        return Err(ProbeSandboxError::new(
                            "broker-frame",
                            "named-pipe request frame exceeds the fixed limit",
                        ));
                    }
                    let mut frame = vec![0_u8; length];
                    if !read_pipe_exact(self.handle.0, &mut frame)? {
                        return Err(ProbeSandboxError::new(
                            "broker-frame",
                            "named-pipe request frame ended before its declared length",
                        ));
                    }
                    let reply = self.broker.handle_frame(&frame).map_err(|error| {
                        ProbeSandboxError::new("broker-frame", error.to_string())
                    })?;
                    write_pipe_all(self.handle.0, &reply)?;
                }
            }
        }
    }

    struct ActiveNamedPipeBroker {
        pipe_name: String,
        shutdown: Arc<AtomicBool>,
        join: JoinHandle<Result<(), ProbeSandboxError>>,
    }

    impl ActiveNamedPipeBroker {
        fn finish(self) -> Result<(), ProbeSandboxError> {
            self.shutdown.store(true, Ordering::Release);
            unsafe {
                let pipe = wide(OsStr::new(&self.pipe_name));
                if let Ok(handle) = CreateFileW(
                    PCWSTR(pipe.as_ptr()),
                    GENERIC_READ.0 | GENERIC_WRITE.0,
                    FILE_SHARE_MODE(0),
                    None,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    None,
                ) {
                    let _wake = OwnedHandle::new(handle);
                }
            }
            self.join.join().map_err(|_| {
                ProbeSandboxError::new("broker-thread", "HTTP broker thread panicked")
            })?
        }
    }

    unsafe fn read_pipe_exact(
        handle: HANDLE,
        mut output: &mut [u8],
    ) -> Result<bool, ProbeSandboxError> {
        let mut read_any = false;
        while !output.is_empty() {
            let mut read = 0_u32;
            match ReadFile(handle, Some(output), Some(&mut read), None) {
                Ok(()) if read > 0 => {
                    read_any = true;
                    output = &mut output[read as usize..];
                }
                Ok(()) => return Ok(read_any && output.is_empty()),
                Err(error) if error.code() == HRESULT::from_win32(ERROR_BROKEN_PIPE.0) => {
                    return Ok(false)
                }
                Err(error) => return Err(win_error("broker-pipe-read", error)),
            }
        }
        Ok(true)
    }

    unsafe fn write_pipe_all(handle: HANDLE, mut input: &[u8]) -> Result<(), ProbeSandboxError> {
        while !input.is_empty() {
            let mut written = 0_u32;
            WriteFile(handle, Some(input), Some(&mut written), None)
                .map_err(|error| win_error("broker-pipe-write", error))?;
            if written == 0 {
                return Err(ProbeSandboxError::new(
                    "broker-pipe-write",
                    "Windows reported a zero-byte named-pipe write",
                ));
            }
            input = &input[written as usize..];
        }
        Ok(())
    }

    fn hex(bytes: &[u8]) -> String {
        let mut output = String::with_capacity(bytes.len() * 2);
        for byte in bytes {
            use std::fmt::Write as _;
            let _ = write!(output, "{byte:02x}");
        }
        output
    }

    unsafe fn configure_job(
        job: HANDLE,
        request: &ProbeLaunchRequest,
    ) -> Result<(), ProbeSandboxError> {
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_PROCESS_TIME;
        limits.BasicLimitInformation.ActiveProcessLimit = request.limits.active_process_limit;
        limits.BasicLimitInformation.PerProcessUserTimeLimit =
            (request.limits.cpu_time_ms as i64) * 10_000;
        limits.ProcessMemoryLimit = request.limits.process_memory_bytes;
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
        .map_err(|error| win_error("job-limits", error))
    }

    unsafe fn grant_directory_access_tree(
        path: &std::path::Path,
        sid: PSID,
        access: DirectoryAccess,
    ) -> Result<DirectoryAclTreeGrant, ProbeSandboxError> {
        let paths = collect_acl_tree_paths(path)?;
        let mut grants = Vec::with_capacity(paths.len());
        for entry in paths {
            match grant_path_access(&entry, sid, access) {
                Ok(grant) => grants.push(grant),
                Err(error) => {
                    // Restore every grant already applied before returning the
                    // setup failure.  The guard also retries restoration during
                    // unwinding, but this path lets us avoid leaving a widened
                    // ACL when a later child is malformed or inaccessible.
                    for grant in grants.iter_mut().rev() {
                        grant.restore();
                    }
                    return Err(error);
                }
            }
        }
        Ok(DirectoryAclTreeGrant { grants })
    }

    fn collect_acl_tree_paths(
        path: &std::path::Path,
    ) -> Result<Vec<std::path::PathBuf>, ProbeSandboxError> {
        let metadata = fs::symlink_metadata(path).map_err(|error| {
            ProbeSandboxError::new(
                "acl-tree-inspect",
                format!("cannot inspect {}: {error}", path.display()),
            )
        })?;
        if !metadata.is_dir() || is_reparse_entry(&metadata) {
            return Err(ProbeSandboxError::new(
                "acl-tree-inspect",
                "ACL root must be an existing non-symlink directory",
            ));
        }
        let mut paths = Vec::new();
        let mut pending = vec![path.to_path_buf()];
        while let Some(current) = pending.pop() {
            if paths.len() >= MAX_ACL_TREE_ENTRIES {
                return Err(ProbeSandboxError::new(
                    "acl-tree-limit",
                    format!("ACL tree exceeds {MAX_ACL_TREE_ENTRIES} entries"),
                ));
            }
            let metadata = fs::symlink_metadata(&current).map_err(|error| {
                ProbeSandboxError::new(
                    "acl-tree-inspect",
                    format!("cannot inspect {}: {error}", current.display()),
                )
            })?;
            if is_reparse_entry(&metadata) || (!metadata.is_dir() && !metadata.is_file()) {
                return Err(ProbeSandboxError::new(
                    "acl-tree-inspect",
                    format!(
                        "ACL tree contains an unsupported or reparse entry: {}",
                        current.display()
                    ),
                ));
            }
            paths.push(current.clone());
            if metadata.is_dir() {
                for entry in fs::read_dir(&current).map_err(|error| {
                    ProbeSandboxError::new(
                        "acl-tree-inspect",
                        format!("cannot enumerate {}: {error}", current.display()),
                    )
                })? {
                    let entry = entry.map_err(|error| {
                        ProbeSandboxError::new("acl-tree-inspect", error.to_string())
                    })?;
                    pending.push(entry.path());
                }
            }
        }
        // Authorize parents first so newly created descendants inherit the
        // intended ACE, then restore in exact reverse order via the guard.
        paths.sort_by_key(|entry| entry.components().count());
        Ok(paths)
    }

    unsafe fn grant_path_access(
        path: &std::path::Path,
        sid: PSID,
        access: DirectoryAccess,
    ) -> Result<DirectoryAclGrant, ProbeSandboxError> {
        let metadata = fs::symlink_metadata(path).map_err(|error| {
            ProbeSandboxError::new(
                "acl-path-inspect",
                format!("cannot inspect {}: {error}", path.display()),
            )
        })?;
        if is_reparse_entry(&metadata) || (!metadata.is_dir() && !metadata.is_file()) {
            return Err(ProbeSandboxError::new(
                "acl-path-inspect",
                format!(
                    "ACL path is not a regular non-reparse object: {}",
                    path.display()
                ),
            ));
        }
        // Security descriptor APIs on some Windows builds reject the
        // extended-length path returned by Rust's `canonicalize` even though
        // ordinary file APIs accept it.  Use the verified path after reducing
        // it to a DOS/UNC spelling, just as for CreateProcessW below.
        let process_path = win32_process_path(path)?;
        let path_wide = wide(process_path.as_os_str());
        let mut old_acl = null_mut();
        let mut descriptor = PSECURITY_DESCRIPTOR::default();
        let status = GetNamedSecurityInfoW(
            PCWSTR(path_wide.as_ptr()),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            Some(&mut old_acl),
            None,
            &mut descriptor,
        );
        if status != ERROR_SUCCESS {
            return Err(win32_status("working-directory-acl-read", status.0));
        }
        let descriptor = OwnedLocal::new(descriptor.0);
        let inheritance = if metadata.is_dir() {
            SUB_CONTAINERS_AND_OBJECTS_INHERIT
        } else {
            // Inheritance flags are meaningful only for directory ACEs. The
            // explicit file grant is still required because existing files
            // do not necessarily inherit a newly-added parent ACE.
            NO_INHERITANCE
        };
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: match access {
                DirectoryAccess::ReadOnly => (FILE_GENERIC_READ | FILE_GENERIC_EXECUTE).0,
                DirectoryAccess::ReadWrite => {
                    (FILE_GENERIC_READ
                        | FILE_GENERIC_WRITE
                        | FILE_GENERIC_EXECUTE
                        | FILE_DELETE_CHILD
                        | DELETE)
                        .0
                }
            },
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: inheritance,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: null_mut(),
                MultipleTrusteeOperation: Default::default(),
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: PWSTR(sid.0.cast()),
            },
        };
        let mut new_acl = null_mut();
        let status = SetEntriesInAclW(Some(&[entry]), Some(old_acl), &mut new_acl);
        if status != ERROR_SUCCESS {
            return Err(win32_status("working-directory-acl-build", status.0));
        }
        let new_acl = OwnedLocal::new(new_acl.cast());
        let status = SetNamedSecurityInfoW(
            PCWSTR(path_wide.as_ptr()),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            Some(new_acl.0.cast()),
            None,
        );
        if status != ERROR_SUCCESS {
            return Err(win32_status("working-directory-acl-write", status.0));
        }
        Ok(DirectoryAclGrant {
            path: path_wide,
            original_descriptor: descriptor,
            original_acl: old_acl,
            restored: false,
        })
    }

    #[derive(Clone, Copy)]
    enum DirectoryAccess {
        ReadOnly,
        ReadWrite,
    }

    fn build_command_line(executable: &str, arguments: &[String]) -> String {
        std::iter::once(executable)
            .chain(arguments.iter().map(String::as_str))
            .map(quote_windows_argument)
            .collect::<Vec<_>>()
            .join(" ")
    }

    /// Convert an extended-length Windows path to the form expected by the
    /// process creation APIs.  Verification and ACL operations continue to use
    /// the canonical path; this conversion is only for CreateProcessW inputs.
    fn win32_process_path(path: &std::path::Path) -> Result<std::path::PathBuf, ProbeSandboxError> {
        let value = path.as_os_str().to_string_lossy();
        let normalized = if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
            format!(r"\\{rest}")
        } else if let Some(rest) = value.strip_prefix(r"\\?\") {
            rest.to_string()
        } else {
            value.into_owned()
        };
        if normalized.is_empty() || normalized.contains('\0') {
            return Err(ProbeSandboxError::new(
                "process-path",
                "process path is empty or contains a NUL character",
            ));
        }
        Ok(std::path::PathBuf::from(normalized))
    }

    fn sanitized_environment(
        working_directory: &std::path::Path,
        broker: Option<&BrokerEnvironment>,
    ) -> Result<Vec<u16>, ProbeSandboxError> {
        let system_root = std::env::var_os("SystemRoot").ok_or_else(|| {
            ProbeSandboxError::new(
                "environment",
                "SystemRoot is unavailable; host environment will not be inherited",
            )
        })?;
        let system_root = system_root.to_string_lossy();
        if system_root.contains('\0') {
            return Err(ProbeSandboxError::new(
                "environment",
                "SystemRoot contains an invalid NUL character",
            ));
        }
        // Environment values are consumed by the child runtime and by the
        // AppContainer profile broker.  Do not pass Rust's extended-length
        // canonical path form (`\\?\`) there: the process-creation path
        // accepts it, but profile environment expansion treats it as a
        // device name and can fail with ERROR_ENVVAR_NOT_FOUND (203).
        let temp = win32_process_path(working_directory)?
            .to_string_lossy()
            .into_owned();
        let required_path_variable = |name: &'static str| -> Result<String, ProbeSandboxError> {
            let value = std::env::var_os(name).ok_or_else(|| {
                ProbeSandboxError::new(
                    "environment",
                    format!("required Windows path variable {name} is unavailable"),
                )
            })?;
            let value = value.to_string_lossy();
            if value.is_empty() || value.contains('\0') {
                return Err(ProbeSandboxError::new(
                    "environment",
                    format!("required Windows path variable {name} is invalid"),
                ));
            }
            Ok(format!("{name}={value}"))
        };
        let mut variables = vec![
            format!("SystemRoot={system_root}"),
            format!("WINDIR={system_root}"),
            // Windows consults these known-folder variables while creating an
            // AppContainer process. They are path-only values; no arbitrary
            // host variables, Python configuration, or secrets are inherited.
            required_path_variable("SystemDrive")?,
            required_path_variable("USERPROFILE")?,
            required_path_variable("HOMEDRIVE")?,
            required_path_variable("HOMEPATH")?,
            required_path_variable("LOCALAPPDATA")?,
            required_path_variable("APPDATA")?,
            required_path_variable("ProgramData")?,
            // Keep DLL/system lookup deterministic without inheriting the
            // user's PATH (which may contain Python shims or secrets).
            format!("PATH={system_root}\\System32;{system_root}"),
            format!("TEMP={temp}"),
            format!("TMP={temp}"),
            "PYTHONUTF8=1".to_string(),
            "PYTHONDONTWRITEBYTECODE=1".to_string(),
            "PYTHONNOUSERSITE=1".to_string(),
            "PYTHONSAFEPATH=1".to_string(),
        ];
        if let Some(broker) = broker {
            variables.push(format!("KOI_PROBE_PIPE={}", broker.pipe_name));
            variables.push(format!("KOI_PROBE_TOKEN={}", broker.token));
            variables.push(format!(
                "KOI_PROBE_PROTOCOL={PROBE_BROKER_PROTOCOL_VERSION}"
            ));
        }
        variables.sort_by_key(|value| value.to_ascii_uppercase());
        let mut environment = Vec::new();
        for variable in variables {
            environment.extend(variable.encode_utf16());
            environment.push(0);
        }
        environment.push(0);
        Ok(environment)
    }

    fn quote_windows_argument(argument: &str) -> String {
        if !argument.is_empty()
            && !argument
                .chars()
                .any(|character| matches!(character, ' ' | '\t' | '"'))
        {
            return argument.to_string();
        }
        let mut output = String::from("\"");
        let mut backslashes = 0_usize;
        for character in argument.chars() {
            if character == '\\' {
                backslashes += 1;
            } else if character == '"' {
                output.push_str(&"\\".repeat(backslashes * 2 + 1));
                output.push('"');
                backslashes = 0;
            } else {
                output.push_str(&"\\".repeat(backslashes));
                backslashes = 0;
                output.push(character);
            }
        }
        output.push_str(&"\\".repeat(backslashes * 2));
        output.push('"');
        output
    }

    struct AppContainerSid {
        sid: PSID,
        profile_name: Vec<u16>,
        cleaned: bool,
    }

    impl AppContainerSid {
        unsafe fn create_unique() -> Result<Self, ProbeSandboxError> {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| ProbeSandboxError::new("clock", error.to_string()))?
                .as_nanos();
            let mut last_error = None;
            for attempt in 0..8_u64 {
                let profile_label = format!(
                    "Koi.DynamicProbe.{}.{}.{}",
                    std::process::id(),
                    nonce,
                    NEXT_PROFILE_ID.fetch_add(1, Ordering::Relaxed)
                );
                let profile_name = wide(OsStr::new(&profile_label));
                match CreateAppContainerProfile(
                    PCWSTR(profile_name.as_ptr()),
                    PCWSTR(profile_name.as_ptr()),
                    PCWSTR(profile_name.as_ptr()),
                    None,
                ) {
                    Ok(sid) => {
                        return Ok(Self {
                            sid,
                            profile_name,
                            cleaned: false,
                        })
                    }
                    Err(error)
                        if error.code() == HRESULT::from_win32(ERROR_FILE_NOT_FOUND.0)
                            && attempt < 7 =>
                    {
                        last_error = Some((profile_label, error));
                        thread::sleep(std::time::Duration::from_millis(200 * (attempt + 1)));
                    }
                    Err(error) => {
                        return Err(ProbeSandboxError::new(
                            "appcontainer-profile",
                            format!("CreateAppContainerProfile({profile_label:?}) failed: {error}"),
                        ))
                    }
                }
            }
            let (profile_label, error) = last_error.expect("retry loop recorded an error");
            Err(ProbeSandboxError::new(
                "appcontainer-profile",
                format!("CreateAppContainerProfile({profile_label:?}) failed after retry: {error}"),
            ))
        }

        fn sid(&self) -> PSID {
            self.sid
        }

        unsafe fn cleanup(&mut self) -> Result<(), ProbeSandboxError> {
            if self.cleaned {
                return Ok(());
            }
            let deletion = DeleteAppContainerProfile(PCWSTR(self.profile_name.as_ptr()))
                .map_err(|error| win_error("appcontainer-cleanup", error));
            let _ = windows::Win32::Security::FreeSid(self.sid);
            self.cleaned = true;
            deletion
        }
    }

    impl Drop for AppContainerSid {
        fn drop(&mut self) {
            unsafe {
                let _ = self.cleanup();
            }
        }
    }

    struct DirectoryAclGrant {
        path: Vec<u16>,
        original_descriptor: OwnedLocal,
        original_acl: *mut ACL,
        restored: bool,
    }

    struct DirectoryAclTreeGrant {
        grants: Vec<DirectoryAclGrant>,
    }

    impl Drop for DirectoryAclTreeGrant {
        fn drop(&mut self) {
            unsafe {
                for grant in self.grants.iter_mut().rev() {
                    grant.restore();
                }
            }
        }
    }

    impl DirectoryAclGrant {
        unsafe fn restore(&mut self) {
            if self.restored {
                return;
            }
            let original_acl = if self.original_acl.is_null() {
                None
            } else {
                Some(self.original_acl.cast_const())
            };
            let status = SetNamedSecurityInfoW(
                PCWSTR(self.path.as_ptr()),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                original_acl,
                None,
            );
            self.restored = status == ERROR_SUCCESS;
        }
    }

    impl Drop for DirectoryAclGrant {
        fn drop(&mut self) {
            unsafe {
                self.restore();
            }
            let _ = &self.original_descriptor;
        }
    }

    struct AttributeList {
        storage: Vec<usize>,
        pointer: LPPROC_THREAD_ATTRIBUTE_LIST,
    }

    impl AttributeList {
        unsafe fn new() -> Result<Self, ProbeSandboxError> {
            let mut bytes = 0_usize;
            let _ = InitializeProcThreadAttributeList(None, 1, None, &mut bytes);
            if bytes == 0 {
                return Err(ProbeSandboxError::new(
                    "attribute-list-size",
                    "Windows returned a zero attribute-list size",
                ));
            }
            let words = bytes.div_ceil(size_of::<usize>());
            let mut storage = vec![0_usize; words];
            let pointer = LPPROC_THREAD_ATTRIBUTE_LIST(storage.as_mut_ptr().cast());
            InitializeProcThreadAttributeList(Some(pointer), 1, None, &mut bytes)
                .map_err(|error| win_error("attribute-list-init", error))?;
            Ok(Self { storage, pointer })
        }

        fn pointer(&mut self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
            self.pointer
        }
    }

    impl Drop for AttributeList {
        fn drop(&mut self) {
            unsafe {
                DeleteProcThreadAttributeList(self.pointer);
            }
            self.storage.clear();
        }
    }

    struct OwnedHandle(HANDLE);

    impl OwnedHandle {
        fn new(handle: HANDLE) -> Self {
            Self(handle)
        }
    }

    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }

    struct OwnedLocal(*mut c_void);

    impl OwnedLocal {
        fn new(pointer: *mut c_void) -> Self {
            Self(pointer)
        }
    }

    impl Drop for OwnedLocal {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe {
                    let _ = LocalFree(Some(HLOCAL(self.0)));
                }
            }
        }
    }

    fn wide(value: &OsStr) -> Vec<u16> {
        value.encode_wide().chain(std::iter::once(0)).collect()
    }

    fn win_error(stage: &'static str, error: windows::core::Error) -> ProbeSandboxError {
        ProbeSandboxError::new(stage, error.to_string())
    }

    fn win32_status(stage: &'static str, status: u32) -> ProbeSandboxError {
        ProbeSandboxError::new(stage, format!("Windows error {status}"))
    }

    #[cfg(test)]
    pub(super) fn dacl_fingerprint(path: &std::path::Path) -> Result<Vec<u8>, ProbeSandboxError> {
        unsafe {
            let process_path = win32_process_path(path)?;
            let path_wide = wide(process_path.as_os_str());
            let mut acl: *mut ACL = null_mut();
            let mut descriptor = PSECURITY_DESCRIPTOR::default();
            let status = GetNamedSecurityInfoW(
                PCWSTR(path_wide.as_ptr()),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                Some(&mut acl),
                None,
                &mut descriptor,
            );
            if status != ERROR_SUCCESS {
                return Err(win32_status("test-acl-read", status.0));
            }
            let _descriptor = OwnedLocal::new(descriptor.0);
            if acl.is_null() {
                return Ok(Vec::new());
            }
            let length = (*acl).AclSize as usize;
            Ok(std::slice::from_raw_parts(acl.cast::<u8>(), length).to_vec())
        }
    }

    #[cfg(test)]
    mod tests {
        use super::{
            collect_acl_tree_paths, quote_windows_argument, sanitized_environment,
            win32_process_path,
        };
        use std::fs;
        use std::path::{Path, PathBuf};
        use std::time::{SystemTime, UNIX_EPOCH};

        #[test]
        fn command_line_quoting_preserves_spaces_quotes_and_backslashes() {
            assert_eq!(quote_windows_argument("simple"), "simple");
            assert_eq!(quote_windows_argument("two words"), "\"two words\"");
            assert_eq!(quote_windows_argument("a\\\"b"), "\"a\\\\\\\"b\"");
            assert_eq!(quote_windows_argument(r"trailing \"), r#""trailing \\""#);
        }

        #[test]
        fn environment_does_not_inherit_host_secrets_or_python_paths() {
            let block = sanitized_environment(Path::new(r"C:\probe-work"), None)
                .expect("build sanitized environment");
            let rendered = String::from_utf16_lossy(&block);
            assert!(rendered.contains("PYTHONNOUSERSITE=1"));
            assert!(rendered.contains("TEMP=C:\\probe-work"));
            assert!(!rendered.to_ascii_uppercase().contains("PYTHONPATH="));
            assert!(!rendered.to_ascii_uppercase().contains("API_KEY="));
        }

        #[test]
        fn process_path_removes_extended_prefix_without_changing_unc_semantics() {
            assert_eq!(
                win32_process_path(Path::new(r"\\?\C:\koi\probe-runtime\python.exe")).unwrap(),
                Path::new(r"C:\koi\probe-runtime\python.exe")
            );
            assert_eq!(
                win32_process_path(Path::new(r"\\?\UNC\server\share\python.exe")).unwrap(),
                Path::new(r"\\server\share\python.exe")
            );
        }

        #[test]
        fn acl_tree_enumeration_covers_existing_files_in_parent_first_order() {
            let root = std::env::temp_dir().join(format!(
                "koi-acl-tree-test-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .expect("clock")
                    .as_nanos()
            ));
            fs::create_dir_all(root.join("nested/deeper")).expect("create ACL test tree");
            fs::write(root.join("runner.py"), b"probe").expect("write ACL test file");
            fs::write(root.join("nested/deeper/input.json"), b"{}").expect("write nested file");

            let paths = collect_acl_tree_paths(&root).expect("enumerate ACL tree");
            assert_eq!(paths.first(), Some(&PathBuf::from(&root)));
            assert!(paths.iter().any(|path| path == &root.join("runner.py")));
            assert!(paths
                .iter()
                .any(|path| path == &root.join("nested/deeper/input.json")));
            assert!(paths
                .windows(2)
                .all(|pair| pair[0].components().count() <= pair[1].components().count()));
            let _ = fs::remove_dir_all(root);
        }
    }
}

#[cfg(not(all(windows, target_arch = "x86_64")))]
mod platform {
    use super::{ProbeExit, ProbeLaunchRequest, ProbeSandboxError, VerifiedProbeRuntime};

    pub(super) fn run(
        _runtime: &VerifiedProbeRuntime,
        _request: &ProbeLaunchRequest,
    ) -> Result<ProbeExit, ProbeSandboxError> {
        Err(ProbeSandboxError::new(
            "platform",
            "the dynamic probe sandbox is available only on Windows x64",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_ID: AtomicU64 = AtomicU64::new(0);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "koi-probe-sandbox-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).expect("create temp directory");
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn lock(executable: &str, sha256: &str) -> ProbeRuntimeLock {
        ProbeRuntimeLock {
            format: EXPECTED_FORMAT.to_string(),
            implementation: "CPython".to_string(),
            version: EXPECTED_RUNTIME_VERSION.to_string(),
            platform: EXPECTED_PLATFORM.to_string(),
            url: format!(
                "https://www.python.org/ftp/python/{EXPECTED_RUNTIME_VERSION}/python-{EXPECTED_RUNTIME_VERSION}-embed-amd64.zip"
            ),
            license: "Python-2.0".to_string(),
            executable: executable.to_string(),
            sha256: "a".repeat(64),
            files: vec![LockedRuntimeFile {
                path: executable.to_string(),
                sha256: sha256.to_string(),
            }],
        }
    }

    fn write_fixture(root: &Path, runtime_bytes: &[u8]) -> ProbeRuntimeLock {
        let runtime_dir = root.join("probe-runtime");
        fs::create_dir_all(&runtime_dir).expect("create runtime dir");
        fs::write(runtime_dir.join("python.exe"), runtime_bytes).expect("write runtime fixture");
        let digest = format!("{:x}", Sha256::digest(runtime_bytes));
        let lock = lock("probe-runtime/python.exe", &digest);
        fs::write(
            root.join(LOCK_FILE_NAME),
            serde_json::to_vec_pretty(&lock).expect("serialize lock"),
        )
        .expect("write lock");
        lock
    }

    #[test]
    fn discovers_only_a_hash_matching_locked_runtime() {
        let temp = TempDir::new();
        let lock = write_fixture(&temp.0, b"fixture-not-an-executable");
        let runtime = discover_verified_runtime(&temp.0).expect("discover runtime");
        assert_eq!(runtime.version(), EXPECTED_RUNTIME_VERSION);
        assert_eq!(runtime.source_sha256(), lock.sha256);
        assert_eq!(
            runtime.executable(),
            temp.0
                .join("probe-runtime/python.exe")
                .canonicalize()
                .expect("canonical runtime")
        );
    }

    #[test]
    fn rejects_tampered_runtime_without_path_fallback() {
        let temp = TempDir::new();
        write_fixture(&temp.0, b"original");
        fs::write(temp.0.join("probe-runtime/python.exe"), b"tampered").expect("tamper runtime");
        let error = discover_verified_runtime(&temp.0).expect_err("must reject tamper");
        assert_eq!(error.stage, "runtime-hash");
    }

    #[test]
    fn rejects_path_traversal_and_unknown_lock_fields() {
        let temp = TempDir::new();
        let traversal = lock("../python.exe", &"0".repeat(64));
        fs::write(
            temp.0.join(LOCK_FILE_NAME),
            serde_json::to_vec(&traversal).expect("serialize traversal lock"),
        )
        .expect("write traversal lock");
        assert_eq!(
            discover_verified_runtime(&temp.0)
                .expect_err("reject traversal")
                .stage,
            "runtime-lock"
        );

        fs::write(
            temp.0.join(LOCK_FILE_NAME),
            br#"{"format":"koi-probe-runtime-v1","implementation":"CPython","version":"3.13.15","platform":"windows-x64","url":"https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip","license":"Python-2.0","executable":"probe-runtime/python.exe","sha256":"0000000000000000000000000000000000000000000000000000000000000000","files":[{"path":"probe-runtime/python.exe","sha256":"0000000000000000000000000000000000000000000000000000000000000000"}],"unreviewed":true}"#,
        )
        .expect("write unknown-field lock");
        assert_eq!(
            discover_verified_runtime(&temp.0)
                .expect_err("reject unknown field")
                .stage,
            "runtime-lock"
        );
    }

    #[test]
    fn rejects_unofficial_url_version_platform_and_empty_license() {
        let mut fixture = lock("probe-runtime/python.exe", &"0".repeat(64));
        fixture.url = "https://example.invalid/python.zip".to_string();
        assert!(validate_lock(&fixture).is_err());
        fixture.url = format!(
            "https://www.python.org/ftp/python/{EXPECTED_RUNTIME_VERSION}/python-{EXPECTED_RUNTIME_VERSION}-embed-amd64.zip"
        );
        fixture.version = "3.14.0rc1".to_string();
        assert!(validate_lock(&fixture).is_err());
        fixture.version = EXPECTED_RUNTIME_VERSION.to_string();
        fixture.platform = "windows-arm64".to_string();
        assert!(validate_lock(&fixture).is_err());
        fixture.platform = EXPECTED_PLATFORM.to_string();
        fixture.license.clear();
        assert!(validate_lock(&fixture).is_err());
    }

    #[test]
    fn launch_request_rejects_policy_weakening_before_process_creation() {
        let temp = TempDir::new();
        write_fixture(&temp.0, b"fixture-not-an-executable");
        let runtime = discover_verified_runtime(&temp.0).expect("discover runtime");
        let request = ProbeLaunchRequest {
            arguments: vec![],
            working_directory: temp.0.clone(),
            read_only_directories: vec![],
            limits: ProbeSandboxLimits {
                active_process_limit: 2,
                ..ProbeSandboxLimits::default()
            },
            http_broker: None,
        };
        let error = run_verified_probe(&runtime, &request).expect_err("reject weak limits");
        assert_eq!(error.stage, "policy");
    }

    #[test]
    fn source_build_policy_is_separate_bounded_and_networkless() {
        let limits = ProbeSandboxLimits::source_build();
        limits
            .validate_source_build()
            .expect("reviewed source build limits");
        assert_eq!(limits.active_process_limit, 4);
        assert_eq!(limits.cpu_time_ms, 10 * 60 * 1_000);
        assert_eq!(limits.wall_time_ms, 10 * 60 * 1_000);
        assert!(limits.validate_probe().is_err());

        let mut too_many = limits.clone();
        too_many.active_process_limit = 5;
        assert!(too_many.validate_source_build().is_err());
        let mut too_long = limits;
        too_long.wall_time_ms += 1;
        assert!(too_long.validate_source_build().is_err());
    }

    #[test]
    fn source_build_entry_rejects_http_broker_before_launch() {
        let temp = TempDir::new();
        write_fixture(&temp.0, b"fixture-not-an-executable");
        let runtime = discover_verified_runtime(&temp.0).expect("discover runtime");
        let work = temp.0.join("build-work");
        fs::create_dir(&work).unwrap();
        let request = ProbeLaunchRequest {
            arguments: Vec::new(),
            working_directory: work,
            read_only_directories: Vec::new(),
            limits: ProbeSandboxLimits::source_build(),
            http_broker: Some(ProbeHttpBrokerLaunch {
                authorized_targets: vec!["https://pypi.org/".to_string()],
            }),
        };
        let error = run_verified_source_build(&runtime, &request)
            .expect_err("source build broker must be refused");
        assert_eq!(error.stage, "policy");
    }

    #[test]
    fn launch_rehashes_runtime_to_close_discovery_to_use_tampering() {
        let temp = TempDir::new();
        let lock = write_fixture(&temp.0, b"original");
        let runtime = discover_verified_runtime(&temp.0).expect("discover runtime");
        fs::write(runtime.executable(), b"changed-after-discovery").expect("tamper runtime");
        let request = ProbeLaunchRequest {
            arguments: vec![],
            working_directory: temp.0.clone(),
            read_only_directories: vec![],
            limits: ProbeSandboxLimits::default(),
            http_broker: None,
        };
        let error = run_verified_probe(&runtime, &request).expect_err("reject changed runtime");
        assert_eq!(error.stage, "runtime-hash");
        assert_eq!(runtime.source_sha256(), lock.sha256);
    }

    #[test]
    fn rejects_unlisted_runtime_files_and_nul_arguments() {
        let temp = TempDir::new();
        write_fixture(&temp.0, b"original");
        fs::write(temp.0.join("probe-runtime/injected.pyd"), b"unreviewed")
            .expect("write unlisted file");
        let error = discover_verified_runtime(&temp.0).expect_err("reject unlisted file");
        assert_eq!(error.stage, "runtime-file");

        assert_eq!(
            validate_arguments(&["bad\0argument".to_string()])
                .expect_err("reject NUL")
                .stage,
            "policy"
        );
    }

    #[test]
    fn bundled_probe_runtime_lock_matches_every_extracted_file() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let runtime = discover_verified_runtime(&workspace).expect("bundled probe runtime");
        assert_eq!(runtime.version(), EXPECTED_RUNTIME_VERSION);
        assert_eq!(runtime.source_sha256().len(), 64);
        assert!(runtime.executable().is_file());
    }

    #[test]
    fn parallel_launch_preparation_uses_unique_verified_runtime_copies() {
        let temp = TempDir::new();
        write_fixture(&temp.0, b"shared-locked-runtime");
        let runtime = std::sync::Arc::new(
            discover_verified_runtime(&temp.0).expect("discover shared runtime fixture"),
        );
        let source_path = runtime.executable().to_path_buf();
        let source_bytes = fs::read(&source_path).expect("read source runtime");
        let source_readonly = fs::metadata(&source_path)
            .expect("source runtime metadata")
            .permissions()
            .readonly();
        let launch_count = 8;
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(launch_count));
        let mut launches = Vec::new();
        for index in 0..launch_count {
            let work = temp.0.join(format!("work-{index}"));
            fs::create_dir(&work).expect("create isolated work directory");
            let runtime = runtime.clone();
            let barrier = barrier.clone();
            launches.push(std::thread::spawn(move || {
                let request = ProbeLaunchRequest {
                    arguments: Vec::new(),
                    working_directory: work,
                    read_only_directories: Vec::new(),
                    limits: ProbeSandboxLimits::default(),
                    http_broker: None,
                };
                let mut isolated = DisposableProbeRuntime::create(&runtime, &request)
                    .expect("copy and verify disposable runtime");
                let copied_root = isolated.runtime().runtime_root().to_path_buf();
                assert_ne!(copied_root, runtime.runtime_root());
                assert_eq!(
                    fs::read(isolated.runtime().executable()).expect("read copied runtime"),
                    b"shared-locked-runtime"
                );
                // Keep all copies alive together so uniqueness is exercised
                // under the same scheduling window.
                barrier.wait();
                isolated.cleanup().expect("remove disposable runtime");
                copied_root
            }));
        }

        let copied_roots = launches
            .into_iter()
            .map(|launch| launch.join().expect("runtime copy thread"))
            .collect::<Vec<_>>();
        let unique = copied_roots.iter().collect::<HashSet<_>>();
        assert_eq!(unique.len(), launch_count);
        assert!(copied_roots.iter().all(|root| !root.exists()));
        assert_eq!(
            fs::read(&source_path).expect("reread source runtime"),
            source_bytes
        );
        assert_eq!(
            fs::metadata(&source_path)
                .expect("source runtime metadata after copies")
                .permissions()
                .readonly(),
            source_readonly
        );
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    #[ignore = "requires an interactive Windows profile capable of creating AppContainers"]
    fn parallel_real_launches_keep_locked_runtime_acl_and_inputs_immutable() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let runtime = std::sync::Arc::new(
            discover_verified_runtime(&workspace).expect("bundled locked probe runtime"),
        );
        let mut source_acls =
            vec![platform::dacl_fingerprint(runtime.runtime_root()).expect("runtime root DACL")];
        for locked in &runtime.files {
            let relative = validated_runtime_path(&locked.path)
                .expect("locked path")
                .strip_prefix("probe-runtime")
                .expect("runtime prefix")
                .to_path_buf();
            source_acls.push(
                platform::dacl_fingerprint(&runtime.runtime_root().join(relative))
                    .expect("runtime file DACL"),
            );
        }

        let temp = TempDir::new();
        let mut launches = Vec::new();
        let mut work_directories = Vec::new();
        for index in 0..2 {
            let work = temp.0.join(format!("parallel-work-{index}"));
            let input = temp.0.join(format!("parallel-input-{index}"));
            fs::create_dir(&work).expect("create work directory");
            fs::create_dir(&input).expect("create input directory");
            let input_file = input.join("input.txt");
            fs::write(&input_file, format!("input-{index}")).expect("write immutable input");
            work_directories.push(work.clone());
            let runtime = runtime.clone();
            launches.push(std::thread::spawn(move || {
                let output = work.join("result.json");
                let script = r#"
from pathlib import Path
import json
import sys
import time

source = Path(sys.argv[1])
output = Path(sys.argv[2])
work = Path.cwd()
(work / "ready").write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15
while not (work / "release").is_file():
    if time.monotonic() >= deadline:
        raise RuntimeError("parallel launch rendezvous timed out")
    time.sleep(0.05)
value = source.read_text(encoding="utf-8")
write_blocked = False
try:
    source.write_text("tampered", encoding="utf-8")
except OSError:
    write_blocked = True
output.write_text(json.dumps({"value": value, "write_blocked": write_blocked}), encoding="utf-8")
raise SystemExit(0 if write_blocked else 93)
"#;
                let exit = run_verified_probe(
                    &runtime,
                    &ProbeLaunchRequest {
                        arguments: vec![
                            "-I".to_string(),
                            "-S".to_string(),
                            "-B".to_string(),
                            "-c".to_string(),
                            script.to_string(),
                            input_file.to_string_lossy().to_string(),
                            output.to_string_lossy().to_string(),
                        ],
                        working_directory: work,
                        read_only_directories: vec![input],
                        limits: ProbeSandboxLimits::default(),
                        http_broker: None,
                    },
                )?;
                if exit.timed_out || exit.exit_code != 0 {
                    return Err(ProbeSandboxError::new(
                        "parallel-test",
                        format!(
                            "sandboxed probe exited with {} (timed_out={})",
                            exit.exit_code, exit.timed_out
                        ),
                    ));
                }
                let report: serde_json::Value =
                    serde_json::from_slice(&fs::read(output).map_err(|error| {
                        ProbeSandboxError::new("parallel-test", error.to_string())
                    })?)
                    .map_err(|error| ProbeSandboxError::new("parallel-test", error.to_string()))?;
                Ok::<_, ProbeSandboxError>(report)
            }));
        }

        let coordinator_work = work_directories.clone();
        let coordinator = std::thread::spawn(move || -> Result<(), String> {
            let deadline = std::time::Instant::now() + Duration::from_secs(20);
            while !coordinator_work
                .iter()
                .all(|work| work.join("ready").is_file())
            {
                if std::time::Instant::now() >= deadline {
                    return Err("parallel probes did not run concurrently".to_string());
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            for work in coordinator_work {
                fs::write(work.join("release"), b"release").map_err(|error| error.to_string())?;
            }
            Ok(())
        });

        for (index, launch) in launches.into_iter().enumerate() {
            let report = launch
                .join()
                .expect("parallel launch thread")
                .expect("parallel AppContainer launch");
            assert_eq!(report["value"], format!("input-{index}"));
            assert_eq!(report["write_blocked"], true);
            assert_eq!(
                fs::read_to_string(temp.0.join(format!("parallel-input-{index}/input.txt")))
                    .expect("read preserved input"),
                format!("input-{index}")
            );
        }
        coordinator
            .join()
            .expect("parallel launch coordinator")
            .expect("both probes reached rendezvous");

        let mut after_acls =
            vec![platform::dacl_fingerprint(runtime.runtime_root())
                .expect("runtime root DACL after")];
        for locked in &runtime.files {
            let relative = validated_runtime_path(&locked.path)
                .expect("locked path")
                .strip_prefix("probe-runtime")
                .expect("runtime prefix")
                .to_path_buf();
            after_acls.push(
                platform::dacl_fingerprint(&runtime.runtime_root().join(relative))
                    .expect("runtime file DACL after"),
            );
        }
        assert_eq!(after_acls, source_acls, "packaged runtime ACL changed");
        assert!(!fs::read_dir(&temp.0)
            .expect("enumerate sandbox test root")
            .filter_map(Result::ok)
            .any(|entry| entry
                .file_name()
                .to_string_lossy()
                .starts_with(".koi-probe-runtime-")));
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    fn windows_appcontainer_setup_never_falls_back_to_host_execution() {
        let temp = TempDir::new();
        let runtime_dir = temp.0.join("probe-runtime");
        let working_dir = temp.0.join("work");
        fs::create_dir_all(&runtime_dir).expect("create runtime directory");
        fs::create_dir_all(&working_dir).expect("create working directory");
        let system_root = std::env::var_os("SystemRoot").expect("SystemRoot");
        let command = PathBuf::from(system_root).join("System32/cmd.exe");
        let executable = runtime_dir.join("python.exe");
        fs::copy(command, &executable).expect("copy test process image");
        let digest = sha256_file(&executable).expect("hash test process image");
        let lock = lock("probe-runtime/python.exe", &digest);
        fs::write(
            temp.0.join(LOCK_FILE_NAME),
            serde_json::to_vec_pretty(&lock).expect("serialize lock"),
        )
        .expect("write lock");
        let runtime = discover_verified_runtime(&temp.0).expect("verify test runtime");
        let marker = temp.0.join("host-fallback-marker.txt");
        let result = run_verified_probe(
            &runtime,
            &ProbeLaunchRequest {
                arguments: vec![
                    "/d".to_string(),
                    "/s".to_string(),
                    "/c".to_string(),
                    format!("echo launched>\"{}\"", marker.display()),
                ],
                working_directory: working_dir,
                read_only_directories: vec![],
                limits: ProbeSandboxLimits::default(),
                http_broker: None,
            },
        );
        match result {
            Ok(exit) => {
                assert!(!exit.timed_out);
                // cmd.exe is copied and deliberately renamed to python.exe.
                // Newer Windows builds may reject that image/name pairing
                // after process creation.  Either successful execution or a
                // nonzero sandboxed exit is acceptable here; the invariant is
                // that no host fallback is ever used.
                if exit.exit_code == 0 {
                    assert!(marker.is_file(), "sandboxed process did not run");
                } else {
                    assert!(!marker.exists(), "failed sandboxed process wrote marker");
                }
            }
            Err(error) => {
                assert!(
                    !marker.exists(),
                    "sandbox setup failure must not execute through a host fallback: {error}"
                );
                assert!(!error.stage.is_empty());
            }
        }
    }
}
