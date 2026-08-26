use super::probe_sandbox::{self, ProbeHttpBrokerLaunch, ProbeLaunchRequest, ProbeSandboxLimits};
use super::probe_wheels;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_SCRIPT_BYTES: usize = 64 * 1024;
const MAX_CONTEXT_BYTES: usize = 512 * 1024;
const MAX_OUTPUT_BYTES: u64 = 4 * 1024 * 1024;
const MAX_TARGETS: usize = 20;
static NEXT_RUN_ID: AtomicU64 = AtomicU64::new(1);

const PROBE_BOOTSTRAP: &str = r#"import base64
import builtins
import json
import os
import re
import struct
import sys
import traceback
import types
import urllib.parse

# Keep bootstrap capabilities explicit. User scripts receive scoped wrappers
# below instead of these process-level handles.
_BOOTSTRAP_OPEN = builtins.open
_BOOTSTRAP_COMPILE = builtins.compile
_BOOTSTRAP_IMPORT = builtins.__import__
_BOOTSTRAP_SYSTEM_EXIT = builtins.SystemExit
_BOOTSTRAP_BASE_EXCEPTION = builtins.BaseException
_BOOTSTRAP_TRACEBACK_FORMAT_EXC = traceback.format_exc

PROTOCOL = int(os.environ.get("KOI_PROBE_PROTOCOL", "0"))
PIPE_NAME = os.environ.get("KOI_PROBE_PIPE", "")
TOKEN = os.environ.get("KOI_PROBE_TOKEN", "")
_pipe = None
_request_sequence = 0

def _read_exact(stream, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise RuntimeError("probe broker pipe closed early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def _broker_call(method, url, headers=None, body=b"", follow_redirects=True):
    global _pipe, _request_sequence
    if not PIPE_NAME or not TOKEN or PROTOCOL != 1:
        raise RuntimeError("probe HTTP broker is unavailable")
    if _pipe is None:
        _pipe = _BOOTSTRAP_OPEN(PIPE_NAME, "r+b", buffering=0)
    _request_sequence += 1
    request = {
        "version": PROTOCOL,
        "token": TOKEN,
        "request_id": "probe-%d" % _request_sequence,
        "method": str(method or "GET").upper(),
        "url": str(url or ""),
        "headers": {str(k): str(v) for k, v in dict(headers or {}).items()},
        "body_base64": base64.b64encode(body).decode("ascii") if body else "",
        "follow_redirects": bool(follow_redirects),
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    _pipe.write(struct.pack("<I", len(payload)))
    _pipe.write(payload)
    length = struct.unpack("<I", _read_exact(_pipe, 4))[0]
    if length <= 0 or length > 86 * 1024 * 1024:
        raise RuntimeError("probe broker returned an invalid frame length")
    reply = json.loads(_read_exact(_pipe, length).decode("utf-8"))
    if not reply.get("ok"):
        error = reply.get("error") or {}
        raise RuntimeError("%s: %s" % (error.get("code", "broker_error"), error.get("message", "request denied")))
    return reply.get("data") or {}

class Response:
    def __init__(self, data):
        self.status_code = int(data.get("status_code") or 0)
        self.headers = dict(data.get("headers") or {})
        self.url = str(data.get("final_url") or "")
        self.elapsed_ms = int(data.get("elapsed_ms") or 0)
        self.content = base64.b64decode(data.get("body_base64") or "")
        self.text = self.content.decode("utf-8", errors="replace")
    @property
    def ok(self):
        return 200 <= self.status_code < 400
    def json(self):
        return json.loads(self.text)
    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP %d" % self.status_code)

def http_request(method, url, headers=None, data=None, json_data=None, json=None,
                 allow_redirects=True, timeout=12, **kwargs):
    del timeout, kwargs
    body = b""
    final_headers = dict(headers or {})
    payload = json_data if json_data is not None else json
    if payload is not None:
        body = globals()["json"].dumps(payload, separators=(",", ":")).encode("utf-8")
        final_headers.setdefault("content-type", "application/json")
    elif data is not None:
        if isinstance(data, bytes):
            body = data
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            final_headers.setdefault("content-type", "application/x-www-form-urlencoded")
        else:
            raise TypeError("unsupported request body")
    return Response(_broker_call(method, url, final_headers, body, allow_redirects))

class Session:
    def request(self, method, url, **kwargs):
        return http_request(method, url, **kwargs)
    def get(self, url, **kwargs): return self.request("GET", url, **kwargs)
    def post(self, url, **kwargs): return self.request("POST", url, **kwargs)
    def put(self, url, **kwargs): return self.request("PUT", url, **kwargs)
    def patch(self, url, **kwargs): return self.request("PATCH", url, **kwargs)
    def delete(self, url, **kwargs): return self.request("DELETE", url, **kwargs)

requests = types.SimpleNamespace(
    request=http_request,
    get=lambda url, **kwargs: http_request("GET", url, **kwargs),
    post=lambda url, **kwargs: http_request("POST", url, **kwargs),
    put=lambda url, **kwargs: http_request("PUT", url, **kwargs),
    patch=lambda url, **kwargs: http_request("PATCH", url, **kwargs),
    delete=lambda url, **kwargs: http_request("DELETE", url, **kwargs),
    Session=Session,
)

SAFE_MODULES = {
    "base64": base64,
    "json": json,
    "re": re,
    "traceback": types.SimpleNamespace(format_exc=_BOOTSTRAP_TRACEBACK_FORMAT_EXC),
    "urllib.parse": urllib.parse,
    "requests": requests,
}
_LOCKED_IMPORT_ROOTS = set()
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    del level
    if name in SAFE_MODULES:
        return SAFE_MODULES[name]
    root = str(name).split(".", 1)[0]
    if root in _LOCKED_IMPORT_ROOTS:
        return _BOOTSTRAP_IMPORT(name, globals, locals, fromlist, 0)
    raise ImportError("module is not available in the KOI probe sandbox: %s" % name)

SAFE_NAMES = [
    "abs", "all", "any", "bool", "bytes", "bytearray", "chr", "dict", "enumerate",
    "BaseException", "Exception", "SystemExit", "compile", "filter", "float", "format",
    "getattr", "hasattr", "hex", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "object", "ord", "pow", "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "type", "ValueError", "RuntimeError",
    "TypeError", "open", "zip",
]
safe_builtins = {name: getattr(builtins, name) for name in SAFE_NAMES}
safe_builtins["__import__"] = safe_import

def _scoped_open(work_root, file, mode="r", buffering=-1, encoding=None, errors=None,
                 newline=None, closefd=True, opener=None):
    # The dynamic script may inspect only its one-time work directory. The
    # AppContainer remains the outer boundary, while this check prevents an
    # accidental absolute path or a pre-existing reparse link from widening
    # the script's file capability.
    candidate = os.path.realpath(os.path.join(work_root, os.fspath(file)) if not os.path.isabs(os.fspath(file)) else os.fspath(file))
    root = os.path.realpath(work_root)
    try:
        inside = os.path.normcase(os.path.commonpath([candidate, root])) == os.path.normcase(root)
    except ValueError:
        inside = False
    if not inside:
        raise PermissionError("probe open is restricted to the working directory")
    if opener is not None:
        raise PermissionError("custom openers are not available in the probe sandbox")
    return _BOOTSTRAP_OPEN(
        candidate,
        mode,
        buffering=buffering,
        encoding=encoding,
        errors=errors,
        newline=newline,
        closefd=closefd,
    )

def _script_builtins(work_root):
    scoped = dict(safe_builtins)
    scoped["open"] = lambda file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None: _scoped_open(
        work_root, file, mode, buffering, encoding, errors, newline, closefd, opener
    )
    return scoped

def main():
    request_path, output_path = sys.argv[1], sys.argv[2]
    with _BOOTSTRAP_OPEN(request_path, "r", encoding="utf-8") as stream:
        request = json.load(stream)
    package_root = str(request.get("site_packages") or "").strip()
    if package_root:
        # The directory is granted read-only by the Rust launcher.  It is
        # inserted before user code runs, while imports remain allow-listed by
        # the lock's explicit import roots.
        sys.path.insert(0, package_root)
        _LOCKED_IMPORT_ROOTS.update(
            str(item).split(".", 1)[0]
            for item in list(request.get("allowed_imports") or [])
        )
    scope = {
        "__builtins__": _script_builtins(os.path.dirname(os.path.realpath(request_path))),
        "__name__": "koi_dynamic_probe",
        "http_request": http_request,
        "requests": requests,
        "json": json,
        "re": re,
        "traceback": SAFE_MODULES["traceback"],
    }
    report = {"ok": False}
    try:
        code = _BOOTSTRAP_COMPILE(request.get("script") or "", "<koi-dynamic-probe>", "exec")
        exec(code, scope, scope)
        run = scope.get("run")
        if not callable(run):
            raise RuntimeError("probe script must define run(targets, context)")
        result = run(list(request.get("targets") or []), dict(request.get("context") or {}))
        report = {"ok": True, "result": result}
    except _BOOTSTRAP_BASE_EXCEPTION as error:
        report = {
            "ok": False,
            "error_type": type(error).__name__,
            "error": str(error)[:4000],
            "traceback": _BOOTSTRAP_TRACEBACK_FORMAT_EXC(limit=12)[-12000:],
        }
    with _BOOTSTRAP_OPEN(output_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, separators=(",", ":"))
    return 0 if report.get("ok") else 1

raise _BOOTSTRAP_SYSTEM_EXIT(main())
"#;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DynamicProbeRequest {
    script: String,
    targets: Vec<String>,
    #[serde(default)]
    context: Value,
    /// Optional distribution names from the reviewed recursive wheel lock.
    /// Unknown or source-only distributions fail before the sandbox launches.
    #[serde(default)]
    packages: Vec<String>,
}

pub fn execute(data_dir: &Path, arguments: &Value) -> Result<Value, String> {
    let request: DynamicProbeRequest = serde_json::from_value(arguments.clone())
        .map_err(|error| format!("invalid run_python_probe arguments: {error}"))?;
    validate_request(&request)?;
    let application_dir = runtime_application_dir()?;
    let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
        .map_err(|error| error.to_string())?;
    let downloaded = if request.packages.is_empty() {
        Vec::new()
    } else {
        let cache = data_dir.join(".koi-runtime").join("probe-wheel-cache");
        probe_wheels::download_packages(&application_dir, &cache, &request.packages)
            .map_err(|error| error.to_string())?
    };
    let root = data_dir.join(".koi-runtime").join("dynamic-probes");
    fs::create_dir_all(&root)
        .map_err(|error| format!("create dynamic probe directory failed: {error}"))?;
    let work_dir = root.join(unique_id());
    fs::create_dir(&work_dir)
        .map_err(|error| format!("create one-time dynamic probe directory failed: {error}"))?;
    // Keep installed wheels outside the writable work directory.  The
    // launcher grants this sibling directory read/execute access only, so a
    // probe cannot modify its own imported code during execution.
    let package_dir = if downloaded.is_empty() {
        None
    } else {
        let path = root.join(unique_id());
        fs::create_dir(&path)
            .map_err(|error| format!("create one-time wheel directory failed: {error}"))?;
        if let Err(error) = probe_wheels::install_offline(&downloaded, &path) {
            let _ = fs::remove_dir_all(&path);
            let _ = fs::remove_dir_all(&work_dir);
            return Err(error.to_string());
        }
        Some(path)
    };
    let result = execute_in_directory(
        &runtime,
        &request,
        &downloaded,
        package_dir.as_deref(),
        &work_dir,
    );
    let cleanup = fs::remove_dir_all(&work_dir);
    let package_cleanup = package_dir
        .as_ref()
        .map(fs::remove_dir_all)
        .unwrap_or(Ok(()));
    match (result, cleanup, package_cleanup) {
        (Ok(value), Ok(()), Ok(())) => Ok(value),
        (Err(error), Ok(()), Ok(())) => Err(error),
        (Ok(_), Err(error), Ok(())) | (Ok(_), Ok(()), Err(error)) => {
            Err(format!("dynamic probe cleanup failed: {error}"))
        }
        (Err(error), Err(cleanup), Ok(())) | (Err(error), Ok(()), Err(cleanup)) => Err(format!(
            "{error}; dynamic probe cleanup also failed: {cleanup}"
        )),
        (Ok(_), Err(work), Err(package)) => Err(format!(
            "dynamic probe cleanup failed: {work}; package cleanup also failed: {package}"
        )),
        (Err(error), Err(work), Err(package)) => Err(format!(
            "{error}; dynamic probe cleanup failed: {work}; package cleanup also failed: {package}"
        )),
    }
}

fn execute_in_directory(
    runtime: &probe_sandbox::VerifiedProbeRuntime,
    request: &DynamicProbeRequest,
    wheels: &[probe_wheels::DownloadedWheel],
    site_packages: Option<&Path>,
    work_dir: &Path,
) -> Result<Value, String> {
    let runner = work_dir.join("koi_probe_runner.py");
    let input = work_dir.join("request.json");
    let output = work_dir.join("result.json");
    let allowed_imports = wheels
        .iter()
        .flat_map(|wheel| wheel.package.imports.iter().cloned())
        .collect::<Vec<_>>();
    write_new_file(&runner, PROBE_BOOTSTRAP.as_bytes())?;
    let input_bytes = serde_json::to_vec(&json!({
        "script": request.script,
        "targets": request.targets,
        "context": request.context,
        "site_packages": site_packages.map(|path| path.to_string_lossy().to_string()),
        "allowed_imports": allowed_imports,
    }))
    .map_err(|error| format!("serialize dynamic probe request failed: {error}"))?;
    write_new_file(&input, &input_bytes)?;
    let exit = probe_sandbox::run_verified_probe(
        runtime,
        &ProbeLaunchRequest {
            arguments: vec![
                "-I".to_string(),
                "-S".to_string(),
                "-B".to_string(),
                runner.to_string_lossy().to_string(),
                input.to_string_lossy().to_string(),
                output.to_string_lossy().to_string(),
            ],
            working_directory: work_dir.to_path_buf(),
            read_only_directories: site_packages.into_iter().map(Path::to_path_buf).collect(),
            limits: ProbeSandboxLimits::default(),
            http_broker: Some(ProbeHttpBrokerLaunch {
                authorized_targets: request.targets.clone(),
            }),
        },
    )
    .map_err(|error| error.to_string())?;
    if exit.timed_out {
        return Err("dynamic probe exceeded the 120 second wall limit".to_string());
    }
    let report = read_limited_json(&output)?;
    if report.get("ok") != Some(&Value::Bool(true)) {
        let kind = report
            .get("error_type")
            .and_then(Value::as_str)
            .unwrap_or("ProbeError");
        let message = report
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("dynamic probe failed");
        return Err(format!("{kind}: {message}"));
    }
    Ok(json!({
        "success": true,
        "python_probe": true,
        "sandbox": "windows_appcontainer",
        "network": "rust_named_pipe_broker",
        "exit_code": exit.exit_code,
        "result": report.get("result").cloned().unwrap_or(Value::Null),
    }))
}

fn validate_request(request: &DynamicProbeRequest) -> Result<(), String> {
    let script_bytes = request.script.len();
    if script_bytes == 0 || script_bytes > MAX_SCRIPT_BYTES {
        return Err(format!(
            "dynamic probe script must contain 1..={MAX_SCRIPT_BYTES} UTF-8 bytes"
        ));
    }
    if request.targets.is_empty() || request.targets.len() > MAX_TARGETS {
        return Err(format!(
            "dynamic probe requires 1..={MAX_TARGETS} authorized targets"
        ));
    }
    if request.packages.len() > 32 {
        return Err("dynamic probe package list cannot exceed 32 entries".to_string());
    }
    for target in &request.targets {
        let parsed = reqwest::Url::parse(target)
            .map_err(|_| format!("dynamic probe target URL is invalid: {target}"))?;
        if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
            return Err(format!("dynamic probe target is not HTTP(S): {target}"));
        }
    }
    let context = serde_json::to_vec(&request.context)
        .map_err(|error| format!("dynamic probe context is invalid: {error}"))?;
    if context.len() > MAX_CONTEXT_BYTES {
        return Err(format!(
            "dynamic probe context exceeds {MAX_CONTEXT_BYTES} bytes"
        ));
    }
    Ok(())
}

fn runtime_application_dir() -> Result<PathBuf, String> {
    if let Some(directory) = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .filter(|path| path.join(probe_sandbox::LOCK_FILE_NAME).is_file())
    {
        return Ok(directory);
    }
    if cfg!(debug_assertions) {
        return Ok(PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".."));
    }
    Err("locked probe runtime is missing beside the application".to_string())
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("create {} failed: {error}", path.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", path.display()))
}

fn read_limited_json(path: &Path) -> Result<Value, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("dynamic probe did not produce a result: {error}"))?;
    if !metadata.is_file() || metadata.len() > MAX_OUTPUT_BYTES {
        return Err("dynamic probe result exceeds the 4 MiB limit".to_string());
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    File::open(path)
        .and_then(|file| file.take(MAX_OUTPUT_BYTES + 1).read_to_end(&mut bytes))
        .map_err(|error| format!("read dynamic probe result failed: {error}"))?;
    if bytes.len() as u64 > MAX_OUTPUT_BYTES {
        return Err("dynamic probe result exceeds the 4 MiB limit".to_string());
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("dynamic probe result is invalid JSON: {error}"))
}

fn unique_id() -> String {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!(
        "probe-{}-{}-{nonce}",
        std::process::id(),
        NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed)
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    fn temp_dir(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "koi-probe-runner-{label}-{}-{}",
            std::process::id(),
            NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).expect("create probe test directory");
        path
    }

    #[test]
    fn rejects_empty_targets_and_oversized_scripts() {
        let empty = DynamicProbeRequest {
            script: "def run(targets, context): return []".to_string(),
            targets: Vec::new(),
            context: json!({}),
            packages: Vec::new(),
        };
        assert!(validate_request(&empty).is_err());
        let oversized = DynamicProbeRequest {
            script: "x".repeat(MAX_SCRIPT_BYTES + 1),
            targets: vec!["https://example.test/".to_string()],
            context: json!({}),
            packages: Vec::new(),
        };
        assert!(validate_request(&oversized).is_err());
        let too_many_packages = DynamicProbeRequest {
            script: "def run(targets, context): return []".to_string(),
            targets: vec!["https://example.test/".to_string()],
            context: json!({}),
            packages: (0..33).map(|index| format!("package-{index}")).collect(),
        };
        assert!(validate_request(&too_many_packages).is_err());
    }

    #[test]
    fn packaged_wheel_lock_allows_only_reviewed_packages() {
        let application_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let lock = probe_wheels::load_lock(&application_dir).expect("bundled wheel lock");
        assert_eq!(lock.roots, vec!["idna"]);
        assert_eq!(lock.packages.len(), 2);
        assert!(lock
            .packages
            .iter()
            .any(|package| package.name == "flit-core"));
        assert_eq!(
            probe_wheels::resolve_packages(&lock, &["idna".into()])
                .expect("reviewed package")
                .len(),
            1
        );
        let error = probe_wheels::resolve_packages(&lock, &["not-reviewed".into()])
            .expect_err("unreviewed package must be refused");
        assert_eq!(error.stage, "resolve");
    }

    #[test]
    fn bootstrap_exposes_broker_only_and_denies_socket_import() {
        assert!(PROBE_BOOTSTRAP.contains("KOI_PROBE_PIPE"));
        assert!(PROBE_BOOTSTRAP.contains("module is not available"));
        assert!(!PROBE_BOOTSTRAP.contains("subprocess."));
        for forbidden in ["socket", "subprocess", "ctypes", "winreg", "os"] {
            assert!(
                !PROBE_BOOTSTRAP.contains(&format!("\"{forbidden}\":")),
                "forbidden module exposed in SAFE_MODULES: {forbidden}"
            );
        }
        assert!(!PROBE_BOOTSTRAP.contains("eval("));
        assert!(!PROBE_BOOTSTRAP.contains("os.system"));
    }

    #[test]
    fn bootstrap_declares_minimum_runtime_builtins_and_restricted_traceback() {
        for required in ["BaseException", "SystemExit", "compile", "open"] {
            assert!(
                PROBE_BOOTSTRAP.contains(&format!("\"{required}\"")),
                "bootstrap did not explicitly provide {required}"
            );
        }
        assert!(PROBE_BOOTSTRAP.contains("\"traceback\": types.SimpleNamespace"));
        assert!(PROBE_BOOTSTRAP.contains("_script_builtins"));
        assert!(PROBE_BOOTSTRAP.contains("probe open is restricted to the working directory"));
        assert!(PROBE_BOOTSTRAP.contains("custom openers are not available"));
    }

    #[cfg(windows)]
    #[test]
    fn bundled_bootstrap_runs_scripts_and_rejects_forbidden_imports() {
        let application_dir = runtime_application_dir().expect("probe application directory");
        let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
            .expect("bundled probe runtime");
        let root = temp_dir("bootstrap-script");
        let runner = root.join("runner.py");
        let request = root.join("request.json");
        let output = root.join("result.json");
        fs::write(&runner, PROBE_BOOTSTRAP.as_bytes()).expect("write bootstrap");
        fs::write(
            &request,
            serde_json::to_vec(&json!({
                "script": r#"
def run(targets, context):
    import traceback
    forbidden_errors = {}
    for module_name in ("socket", "subprocess", "os", "ctypes", "winreg"):
        try:
            __import__(module_name)
            forbidden_errors[module_name] = "unexpected_import_success"
        except BaseException as error:
            forbidden_errors[module_name] = type(error).__name__
    try:
        open("../outside.txt", "r")
        open_error = "unexpected_open_success"
    except BaseException as error:
        open_error = type(error).__name__
    with open("inside.txt", "w", encoding="utf-8") as stream:
        stream.write("ok")
    code = compile("1 + 1", "<probe-test>", "eval")
    return {
        "forbidden_errors": forbidden_errors,
        "open_error": open_error,
        "traceback_available": traceback.format_exc() is not None,
        "system_exit_is_exception": issubclass(SystemExit, BaseException),
        "compile_type": type(code).__name__,
    }
"#,
                "targets": ["https://example.test/"],
                "context": {},
            }))
            .expect("serialize bootstrap request"),
        )
        .expect("write bootstrap request");
        let status = Command::new(runtime.executable())
            .args([
                "-I",
                "-S",
                "-B",
                runner.to_string_lossy().as_ref(),
                request.to_string_lossy().as_ref(),
                output.to_string_lossy().as_ref(),
            ])
            .current_dir(&root)
            .env_remove("KOI_PROBE_PIPE")
            .env_remove("KOI_PROBE_TOKEN")
            .status()
            .expect("run bundled bootstrap");
        assert!(status.success(), "bootstrap process failed: {status}");
        let report: Value =
            serde_json::from_slice(&fs::read(&output).expect("read bootstrap result"))
                .expect("parse bootstrap result");
        assert_eq!(report["ok"], true);
        for forbidden in ["socket", "subprocess", "os", "ctypes", "winreg"] {
            assert_eq!(
                report["result"]["forbidden_errors"][forbidden],
                "ImportError"
            );
        }
        assert_eq!(report["result"]["open_error"], "PermissionError");
        assert_eq!(report["result"]["traceback_available"], true);
        assert_eq!(report["result"]["system_exit_is_exception"], true);
        assert_eq!(report["result"]["compile_type"], "code");
        assert_eq!(
            fs::read(root.join("inside.txt")).expect("read allowed file"),
            b"ok"
        );
        assert!(!root.parent().unwrap().join("outside.txt").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    #[ignore = "requires an interactive Windows user profile that can create AppContainers"]
    fn executes_in_the_real_locked_appcontainer_without_host_python() {
        let data_dir = temp_dir("appcontainer");
        let result = execute(
            &data_dir,
            &json!({
                "script": "def run(targets, context):\n    return {'target_count': len(targets), 'marker': context.get('marker')}\n",
                "targets": ["http://127.0.0.1:9/"],
                "context": {"marker": "appcontainer-ok"}
            }),
        )
        .expect("run locked AppContainer probe");
        assert_eq!(result["success"], true);
        assert_eq!(result["sandbox"], "windows_appcontainer");
        assert_eq!(result["result"]["target_count"], 1);
        assert_eq!(result["result"]["marker"], "appcontainer-ok");
        assert!(!data_dir
            .join(".koi-runtime/dynamic-probes")
            .read_dir()
            .is_ok_and(|mut entries| entries.next().is_some()));
        let _ = fs::remove_dir_all(data_dir);
    }
}
