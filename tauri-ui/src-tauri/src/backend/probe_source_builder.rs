//! Manually approved, networkless PEP 517 source-package builder.
//!
//! Rust downloads and verifies every artifact first. Extraction and backend
//! execution then happen inside a disposable AppContainer/Job with no HTTP
//! broker, at most four processes, and a ten-minute CPU/wall limit.

use super::{probe_sandbox, probe_wheels};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_REPORT_BYTES: u64 = 1024 * 1024;
static NEXT_BUILD_ID: AtomicU64 = AtomicU64::new(1);

const SOURCE_BUILD_BOOTSTRAP: &str = r#"import importlib
import json
import os
import pathlib
import shutil
import stat
import sys
import tarfile
import traceback
import zipfile

MAX_ENTRIES = 20000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024

def clean_parts(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise RuntimeError("source archive contains an unsafe path")
    path = pathlib.PurePosixPath(name.rstrip("/"))
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") or ":" in part for part in path.parts):
        raise RuntimeError("source archive contains an unsafe path: %s" % name)
    return path.parts

def destination(root, parts):
    target = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([target, root]) != root:
        raise RuntimeError("source archive path escaped extraction root")
    return target

def validate_common(entries):
    if not entries or len(entries) > MAX_ENTRIES:
        raise RuntimeError("source archive contains an invalid number of entries")
    seen = set()
    total = 0
    for name, size, is_dir, _ in entries:
        parts = clean_parts(name)
        key = "/".join(parts).casefold()
        if key in seen:
            raise RuntimeError("source archive contains a case-insensitive path collision")
        seen.add(key)
        if not is_dir:
            if size < 0 or size > MAX_FILE_BYTES:
                raise RuntimeError("source archive member exceeds 64 MiB")
            total += size
            if total > MAX_EXPANDED_BYTES:
                raise RuntimeError("source archive expands beyond 256 MiB")

def copy_bounded(source, target, expected):
    written = 0
    with open(target, "xb") as output:
        while True:
            chunk = source.read(min(65536, expected - written + 1))
            if not chunk:
                break
            written += len(chunk)
            if written > expected:
                raise RuntimeError("source archive member exceeded its declared size")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if written != expected:
        raise RuntimeError("source archive member size did not match its declaration")

def extract_zip(archive_path, root):
    with zipfile.ZipFile(archive_path, "r") as archive:
        entries = []
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o177777
            kind = stat.S_IFMT(mode)
            if info.flag_bits & 1:
                raise RuntimeError("encrypted source archives are refused")
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise RuntimeError("source archive contains a link or special file")
            entries.append((info.filename, info.file_size, info.is_dir(), info))
        validate_common(entries)
        for name, size, is_dir, info in entries:
            target = destination(root, clean_parts(name))
            if is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info, "r") as source:
                copy_bounded(source, target, size)

def extract_tar(archive_path, root):
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        entries = []
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("source archive contains a link or special file")
            entries.append((member.name, member.size, member.isdir(), member))
        validate_common(entries)
        for name, size, is_dir, member in entries:
            target = destination(root, clean_parts(name))
            if is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("source archive member could not be opened")
            with source:
                copy_bounded(source, target, size)

def main():
    config_path, report_path = sys.argv[1], sys.argv[2]
    with open(config_path, "r", encoding="utf-8") as stream:
        config = json.load(stream)
    report = {"ok": False}
    try:
        archive_path = os.path.realpath(config["source_archive"])
        extraction_root = os.path.realpath(config["extraction_root"])
        output_root = os.path.realpath(config["output_root"])
        os.makedirs(extraction_root, exist_ok=False)
        os.makedirs(output_root, exist_ok=False)
        filename = str(config["source_filename"]).lower()
        if filename.endswith(".zip"):
            extract_zip(archive_path, extraction_root)
        elif filename.endswith(".tar.gz"):
            extract_tar(archive_path, extraction_root)
        else:
            raise RuntimeError("source archive format is not reviewed")

        source_root = destination(extraction_root, clean_parts(config["source_subdir"]))
        if not os.path.isdir(source_root):
            raise RuntimeError("locked source project directory is missing")
        dependencies = os.path.realpath(config["dependency_root"])
        sys.path.insert(0, dependencies)
        sys.path.insert(0, source_root)
        os.chdir(source_root)
        backend = importlib.import_module(config["backend"])
        build_wheel = getattr(backend, "build_wheel", None)
        if not callable(build_wheel):
            raise RuntimeError("locked PEP 517 backend has no build_wheel hook")
        wheel_name = build_wheel(output_root, {}, None)
        if not isinstance(wheel_name, str) or os.path.basename(wheel_name) != wheel_name or not wheel_name.endswith(".whl"):
            raise RuntimeError("PEP 517 backend returned an unsafe wheel name")
        outputs = os.listdir(output_root)
        if outputs != [wheel_name]:
            raise RuntimeError("source builder produced unexpected extra artifacts")
        report = {"ok": True, "wheel": wheel_name}
    except BaseException as error:
        report = {
            "ok": False,
            "error_type": type(error).__name__,
            "error": str(error)[:4000],
            "traceback": traceback.format_exc(limit=12)[-12000:],
        }
    with open(report_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    return 0 if report.get("ok") else 1

raise SystemExit(main())
"#;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceBuildRequest {
    package: String,
}

pub fn execute_approved(data_dir: &Path, arguments: &Value) -> Result<Value, String> {
    let request: SourceBuildRequest = serde_json::from_value(arguments.clone())
        .map_err(|error| format!("invalid source build arguments: {error}"))?;
    let package = request.package.trim();
    if package.is_empty() || package.len() > 128 {
        return Err("source build package is required".to_string());
    }
    let application_dir = runtime_application_dir()?;
    let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
        .map_err(|error| error.to_string())?;
    let cache = data_dir.join(".koi-runtime").join("probe-wheel-cache");
    let prepared = probe_wheels::prepare_source_build(&application_dir, &cache, package, true)
        .map_err(|error| error.to_string())?;
    execute_prepared(data_dir, &runtime, &cache, &prepared)
}

fn execute_prepared(
    data_dir: &Path,
    runtime: &probe_sandbox::VerifiedProbeRuntime,
    cache_dir: &Path,
    prepared: &probe_wheels::PreparedSourceBuild,
) -> Result<Value, String> {
    let root = data_dir
        .join(".koi-runtime")
        .join("probe-source-builds")
        .join(unique_id());
    let work = root.join("work");
    let inputs = root.join("inputs");
    let dependencies = root.join("dependencies");
    fs::create_dir_all(&work).map_err(|error| format!("create build work failed: {error}"))?;
    fs::create_dir(&inputs).map_err(|error| format!("create build inputs failed: {error}"))?;
    fs::create_dir(&dependencies)
        .map_err(|error| format!("create build dependencies failed: {error}"))?;

    let result = (|| {
        let source_copy = inputs.join(&prepared.source.filename);
        copy_locked_input(
            &prepared.source_path,
            &source_copy,
            &prepared.source.sha256,
            prepared.source.size,
        )?;
        if !prepared.build_dependencies.is_empty() {
            probe_wheels::install_offline(&prepared.build_dependencies, &dependencies)
                .map_err(|error| error.to_string())?;
        }
        let builder = work.join("koi_source_builder.py");
        let config = work.join("build.json");
        let report = work.join("result.json");
        let extraction = work.join("source");
        let output = work.join("wheel-out");
        write_new(&builder, SOURCE_BUILD_BOOTSTRAP.as_bytes())?;
        let config_bytes = serde_json::to_vec(&json!({
            "source_archive": source_copy,
            "source_filename": prepared.source.filename,
            "source_subdir": prepared.source_subdir,
            "extraction_root": extraction,
            "output_root": output,
            "dependency_root": dependencies,
            "backend": prepared.backend,
        }))
        .map_err(|error| format!("serialize source build config failed: {error}"))?;
        write_new(&config, &config_bytes)?;
        let exit = probe_sandbox::run_verified_source_build(
            runtime,
            &probe_sandbox::ProbeLaunchRequest {
                arguments: vec![
                    "-I".to_string(),
                    "-S".to_string(),
                    "-B".to_string(),
                    builder.to_string_lossy().to_string(),
                    config.to_string_lossy().to_string(),
                    report.to_string_lossy().to_string(),
                ],
                working_directory: work.clone(),
                read_only_directories: vec![inputs.clone(), dependencies.clone()],
                limits: probe_sandbox::ProbeSandboxLimits::source_build(),
                http_broker: None,
            },
        )
        .map_err(|error| error.to_string())?;
        let report_value = read_report(&report)?;
        if exit.timed_out {
            return Err("source wheel build exceeded the 10 minute wall limit".to_string());
        }
        if exit.exit_code != 0 || report_value["ok"] != true {
            let kind = report_value["error_type"]
                .as_str()
                .unwrap_or("SourceBuildError");
            let message = report_value["error"]
                .as_str()
                .unwrap_or("source wheel build failed");
            return Err(format!("{kind}: {message}"));
        }
        let wheel_name = report_value["wheel"]
            .as_str()
            .ok_or_else(|| "source builder did not report a wheel".to_string())?;
        if Path::new(wheel_name)
            .file_name()
            .and_then(|value| value.to_str())
            != Some(wheel_name)
        {
            return Err("source builder returned an unsafe wheel path".to_string());
        }
        let wheel = output.join(wheel_name);
        let verified = probe_wheels::verify_built_wheel(&prepared.name, &prepared.version, &wheel)
            .map_err(|error| error.to_string())?;
        let cached = probe_wheels::persist_built_wheel(cache_dir, &wheel, &verified)
            .map_err(|error| error.to_string())?;
        Ok(json!({
            "success": true,
            "package": prepared.name,
            "version": prepared.version,
            "wheel": verified.filename,
            "wheel_sha256": verified.sha256,
            "wheel_size": verified.size,
            "cache_path": cached,
            "sandbox": "windows_appcontainer",
            "network": "disabled",
            "active_process_limit": probe_sandbox::SOURCE_BUILD_MAX_PROCESSES,
            "cpu_time_ms": probe_sandbox::SOURCE_BUILD_CPU_LIMIT.as_millis(),
            "wall_time_ms": probe_sandbox::SOURCE_BUILD_WALL_LIMIT.as_millis(),
            "second_approval": true,
        }))
    })();
    let cleanup = fs::remove_dir_all(&root);
    match (result, cleanup) {
        (Ok(value), Ok(())) => Ok(value),
        (Err(error), Ok(())) => Err(error),
        (Ok(_), Err(error)) => Err(format!("source build cleanup failed: {error}")),
        (Err(error), Err(cleanup)) => Err(format!(
            "{error}; source build cleanup also failed: {cleanup}"
        )),
    }
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

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("create {} failed: {error}", path.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", path.display()))
}

fn copy_locked_input(
    source: &Path,
    destination: &Path,
    expected_sha256: &str,
    expected_size: Option<u64>,
) -> Result<(), String> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("inspect source distribution failed: {error}"))?;
    if !metadata.is_file() || is_reparse(&metadata) {
        return Err("source distribution must be a regular non-symlink file".to_string());
    }
    if expected_size.is_some_and(|size| size != metadata.len()) {
        return Err("source distribution size changed after verification".to_string());
    }
    let mut input = File::open(source).map_err(|error| format!("open source failed: {error}"))?;
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(destination)
        .map_err(|error| format!("create source input failed: {error}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|error| format!("read source input failed: {error}"))?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > 64 * 1024 * 1024 {
            return Err("source distribution exceeds 64 MiB".to_string());
        }
        hasher.update(&buffer[..count]);
        output
            .write_all(&buffer[..count])
            .map_err(|error| format!("write source input failed: {error}"))?;
    }
    output
        .sync_all()
        .map_err(|error| format!("sync source input failed: {error}"))?;
    let digest = format!("{:x}", hasher.finalize());
    if total != metadata.len() || !digest.eq_ignore_ascii_case(expected_sha256) {
        return Err("source distribution changed after verification".to_string());
    }
    Ok(())
}

fn read_report(path: &Path) -> Result<Value, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("source builder did not produce a report: {error}"))?;
    if !metadata.is_file() || metadata.len() > MAX_REPORT_BYTES {
        return Err("source builder report is invalid".to_string());
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    File::open(path)
        .and_then(|file| file.take(MAX_REPORT_BYTES + 1).read_to_end(&mut bytes))
        .map_err(|error| format!("read source builder report failed: {error}"))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("source builder report is invalid JSON: {error}"))
}

fn unique_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "source-build-{}-{}-{nanos}",
        std::process::id(),
        NEXT_BUILD_ID.fetch_add(1, Ordering::Relaxed)
    )
}

#[cfg(windows)]
fn is_reparse(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_type().is_symlink() || metadata.file_attributes() & 0x400 != 0
}

#[cfg(not(windows))]
fn is_reparse(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;
    use std::io::Cursor;
    use zip::write::SimpleFileOptions;

    fn digest(bytes: &[u8]) -> String {
        format!("{:x}", Sha256::digest(bytes))
    }

    fn zip_bytes(entries: &[(&str, &[u8])]) -> Vec<u8> {
        let cursor = Cursor::new(Vec::new());
        let mut archive = zip::ZipWriter::new(cursor);
        for (path, bytes) in entries {
            archive
                .start_file(*path, SimpleFileOptions::default())
                .unwrap();
            archive.write_all(bytes).unwrap();
        }
        archive.finish().unwrap().into_inner()
    }

    fn backend_source() -> &'static [u8] {
        br#"import os
import zipfile

def build_wheel(output_root, config_settings=None, metadata_directory=None):
    del config_settings, metadata_directory
    name = "demo-1-py3-none-any.whl"
    path = os.path.join(output_root, name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        wheel.writestr("demo/__init__.py", "VALUE = 'built-in-appcontainer'\n")
        wheel.writestr("demo-1.dist-info/METADATA", "Metadata-Version: 2.1\nName: demo\nVersion: 1\n")
        wheel.writestr("demo-1.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: koi-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr("demo-1.dist-info/RECORD", "")
    return name
"#
    }

    fn prepared_fixture(
        root: &Path,
        source_entries: &[(&str, &[u8])],
    ) -> probe_wheels::PreparedSourceBuild {
        fs::create_dir_all(root).unwrap();
        let source_bytes = zip_bytes(source_entries);
        let source_path = root.join("demo-1.zip");
        fs::write(&source_path, &source_bytes).unwrap();

        let backend_bytes = zip_bytes(&[("builder_backend.py", backend_source())]);
        let backend_path = root.join("builder_backend-1-py3-none-any.whl");
        fs::write(&backend_path, &backend_bytes).unwrap();
        probe_wheels::PreparedSourceBuild {
            name: "demo".to_string(),
            version: "1".to_string(),
            source: probe_wheels::LockedWheelArtifact {
                filename: "demo-1.zip".to_string(),
                url: "https://files.pythonhosted.org/packages/test/demo-1.zip".to_string(),
                sha256: digest(&source_bytes),
                size: Some(source_bytes.len() as u64),
            },
            backend: "builder_backend".to_string(),
            source_subdir: "demo-1".to_string(),
            build_dependencies: vec![probe_wheels::DownloadedWheel {
                package: probe_wheels::ResolvedWheel {
                    name: "builder-backend".to_string(),
                    version: "1".to_string(),
                    artifact: probe_wheels::LockedWheelArtifact {
                        filename: "builder_backend-1-py3-none-any.whl".to_string(),
                        url: "https://files.pythonhosted.org/packages/test/builder_backend-1-py3-none-any.whl".to_string(),
                        sha256: digest(&backend_bytes),
                        size: Some(backend_bytes.len() as u64),
                    },
                    imports: vec!["builder_backend".to_string()],
                },
                path: backend_path,
            }],
            source_path,
        }
    }

    fn temp_root(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("koi-source-builder-{label}-{}", unique_id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    #[ignore = "requires an interactive Windows profile capable of creating AppContainers"]
    fn builds_valid_wheel_in_networkless_four_process_sandbox() {
        let root = temp_root("success");
        let fixture = root.join("fixture");
        let prepared = prepared_fixture(
            &fixture,
            &[
                ("demo-1/pyproject.toml", b"[build-system]\n"),
                ("demo-1/demo/__init__.py", b"SOURCE = True\n"),
            ],
        );
        let application = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let runtime = probe_sandbox::discover_verified_runtime(&application).unwrap();
        let result = execute_prepared(&root, &runtime, &root.join("cache"), &prepared)
            .expect("source build sandbox");
        assert_eq!(result["success"], true);
        assert_eq!(result["network"], "disabled");
        assert_eq!(result["active_process_limit"], 4);
        assert_eq!(result["second_approval"], true);
        let cached = PathBuf::from(result["cache_path"].as_str().unwrap());
        assert!(cached.is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    #[ignore = "requires an interactive Windows profile capable of creating AppContainers"]
    fn rejects_source_archive_escape_before_backend_execution() {
        let root = temp_root("escape");
        let fixture = root.join("fixture");
        let marker = root.join("backend-ran.txt");
        let marker_literal =
            base64::engine::general_purpose::STANDARD.encode(marker.to_string_lossy().as_bytes());
        let backend = format!(
            "import base64, pathlib\npathlib.Path(base64.b64decode({marker_literal:?}).decode()).write_text('ran')\ndef build_wheel(*args): raise RuntimeError('must not run')\n"
        );
        let mut prepared = prepared_fixture(
            &fixture,
            &[
                ("demo-1/pyproject.toml", b"[build-system]\n"),
                ("../escape.txt", b"escape"),
            ],
        );
        let backend_bytes = zip_bytes(&[("builder_backend.py", backend.as_bytes())]);
        fs::write(&prepared.build_dependencies[0].path, &backend_bytes).unwrap();
        prepared.build_dependencies[0].package.artifact.sha256 = digest(&backend_bytes);
        prepared.build_dependencies[0].package.artifact.size = Some(backend_bytes.len() as u64);
        let application = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let runtime = probe_sandbox::discover_verified_runtime(&application).unwrap();
        let error = execute_prepared(&root, &runtime, &root.join("cache"), &prepared)
            .expect_err("traversal source must fail");
        assert!(error.contains("unsafe path"), "{error}");
        assert!(!marker.exists());
        assert!(!root.join("escape.txt").exists());
        let _ = fs::remove_dir_all(root);
    }
}
