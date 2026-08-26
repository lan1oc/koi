//! Hash-locked 7-Zip runtime used for 7z and RAR inspection/extraction.
//!
//! The executable is never resolved from `PATH`. The public lock must match
//! the lock embedded in `koi.exe`, and the complete runtime inventory is
//! checked before each archive operation.

use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::Read;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

pub const LOCK_FILE_NAME: &str = "archive-runtime.lock.json";
pub const RUNTIME_DIR_NAME: &str = "archive-runtime";
const EMBEDDED_LOCK: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../archive-runtime.lock.json"
));
const EXPECTED_FORMAT: &str = "koi-archive-runtime-v1";
const EXPECTED_PLATFORM: &str = "windows-x64";
const EXPECTED_ARCHITECTURE: &str = "x86_64";
const EXPECTED_PROJECT: &str = "7-Zip";
const EXECUTABLE_FILE_NAME: &str = "7z.exe";
const CODEC_FILE_NAME: &str = "7z.dll";
const LICENSE_FILE_NAME: &str = "License.txt";
const MAX_RUNTIME_FILE_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeLock {
    format: String,
    version: String,
    platform: String,
    architecture: String,
    source: RuntimeSource,
    licenses: RuntimeLicenses,
    executable: String,
    files: Vec<RuntimeFile>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeSource {
    project: String,
    upstream_url: String,
    release_url: String,
    installer_url: String,
    installer_size: u64,
    installer_sha256: String,
    release_date: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeLicenses {
    console_spdx: String,
    library_summary: String,
    notice_file: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeFile {
    path: String,
    size: u64,
    sha256: String,
    role: String,
}

#[derive(Debug, Clone)]
pub(crate) struct VerifiedRuntime {
    root: PathBuf,
    executable: PathBuf,
}

#[derive(Debug, Clone)]
pub(crate) struct RuntimeReport {
    pub(crate) version: String,
    pub(crate) files_verified: usize,
    pub(crate) rar_supported: bool,
}

impl VerifiedRuntime {
    pub(crate) fn root(&self) -> &Path {
        &self.root
    }

    pub(crate) fn executable(&self) -> &Path {
        &self.executable
    }
}

fn is_lower_hex_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_relative_file_path(value: &str) -> Result<PathBuf, String> {
    if value.is_empty() || value.contains('\\') {
        return Err(format!("invalid archive runtime lock path: {value}"));
    }
    let path = Path::new(value);
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::Prefix(_) | Component::RootDir | Component::ParentDir
            )
        })
    {
        return Err(format!("unsafe archive runtime lock path: {value}"));
    }
    Ok(path.to_path_buf())
}

fn parse_embedded_lock() -> Result<RuntimeLock, String> {
    let lock: RuntimeLock = serde_json::from_str(EMBEDDED_LOCK)
        .map_err(|error| format!("embedded archive runtime lock is invalid: {error}"))?;
    if lock.format != EXPECTED_FORMAT
        || lock.platform != EXPECTED_PLATFORM
        || lock.architecture != EXPECTED_ARCHITECTURE
        || lock.source.project != EXPECTED_PROJECT
        || lock.executable != EXECUTABLE_FILE_NAME
    {
        return Err("embedded archive runtime lock targets an unsupported build".to_string());
    }
    if lock.version.trim().is_empty()
        || lock.source.installer_size == 0
        || !is_lower_hex_sha256(&lock.source.installer_sha256)
        || !lock.source.upstream_url.starts_with("https://")
        || !lock
            .source
            .release_url
            .starts_with("https://github.com/ip7z/7zip/releases/")
        || !lock
            .source
            .installer_url
            .starts_with("https://github.com/ip7z/7zip/releases/download/")
        || lock.source.release_date.trim().is_empty()
    {
        return Err("embedded archive runtime source provenance is incomplete".to_string());
    }
    if lock.licenses.console_spdx != "LGPL-2.1-or-later"
        || lock.licenses.notice_file != LICENSE_FILE_NAME
        || !lock
            .licenses
            .library_summary
            .contains("LicenseRef-unRAR-restriction")
    {
        return Err("embedded archive runtime license metadata is invalid".to_string());
    }

    let mut paths = BTreeSet::new();
    let mut executable_count = 0_usize;
    let mut codec_count = 0_usize;
    let mut license_count = 0_usize;
    for entry in &lock.files {
        validate_relative_file_path(&entry.path)?;
        if entry.size == 0
            || entry.size > MAX_RUNTIME_FILE_BYTES
            || !is_lower_hex_sha256(&entry.sha256)
        {
            return Err(format!(
                "invalid archive runtime lock entry: {}",
                entry.path
            ));
        }
        if !paths.insert(entry.path.clone()) {
            return Err(format!(
                "duplicate archive runtime lock entry: {}",
                entry.path
            ));
        }
        match (entry.path.as_str(), entry.role.as_str()) {
            (EXECUTABLE_FILE_NAME, "console-runtime") => executable_count += 1,
            (CODEC_FILE_NAME, "codec-runtime") => codec_count += 1,
            (LICENSE_FILE_NAME, "license") => license_count += 1,
            _ => {}
        }
    }
    if executable_count != 1 || codec_count != 1 || license_count != 1 || paths.len() != 3 {
        return Err(
            "archive runtime lock must contain exactly 7z.exe, 7z.dll, and License.txt".to_string(),
        );
    }
    Ok(lock)
}

fn runtime_inventory(root: &Path) -> Result<BTreeSet<String>, String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = BTreeSet::new();
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory)
            .map_err(|error| format!("unable to enumerate archive runtime: {error}"))?
        {
            let entry =
                entry.map_err(|error| format!("unable to enumerate archive runtime: {error}"))?;
            let file_type = entry
                .file_type()
                .map_err(|error| format!("unable to inspect archive runtime entry: {error}"))?;
            if file_type.is_symlink() {
                return Err(format!(
                    "archive runtime must not contain symbolic links: {}",
                    entry.path().display()
                ));
            }
            if file_type.is_dir() {
                pending.push(entry.path());
            } else if file_type.is_file() {
                let relative = entry
                    .path()
                    .strip_prefix(root)
                    .map_err(|_| "archive runtime path escaped its root".to_string())?
                    .to_string_lossy()
                    .replace('\\', "/");
                files.insert(relative);
            } else {
                return Err(format!(
                    "unsupported archive runtime entry: {}",
                    entry.path().display()
                ));
            }
        }
    }
    Ok(files)
}

fn sha256_file(path: &Path, max_bytes: u64) -> Result<(u64, String), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("unable to read archive runtime metadata: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!(
            "archive runtime entry is not a regular file: {}",
            path.display()
        ));
    }
    if metadata.len() > max_bytes {
        return Err(format!(
            "archive runtime entry is too large: {}",
            path.display()
        ));
    }
    let mut file = File::open(path)
        .map_err(|error| format!("unable to open archive runtime entry: {error}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("unable to hash archive runtime entry: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| "archive runtime entry size overflow".to_string())?;
        if total > max_bytes {
            return Err(format!(
                "archive runtime entry is too large: {}",
                path.display()
            ));
        }
        hasher.update(&buffer[..count]);
    }
    Ok((total, format!("{:x}", hasher.finalize())))
}

fn verify_pe_x64(path: &Path, label: &str) -> Result<(), String> {
    let bytes = fs::read(path).map_err(|error| format!("unable to read {label}: {error}"))?;
    if bytes.len() < 0x40 || &bytes[..2] != b"MZ" {
        return Err(format!("archive runtime {label} is not a PE image"));
    }
    let pe_offset = u32::from_le_bytes(bytes[0x3c..0x40].try_into().unwrap()) as usize;
    if pe_offset.checked_add(6).is_none_or(|end| end > bytes.len())
        || &bytes[pe_offset..pe_offset + 4] != b"PE\0\0"
    {
        return Err(format!("archive runtime {label} has an invalid PE header"));
    }
    let machine = u16::from_le_bytes(bytes[pe_offset + 4..pe_offset + 6].try_into().unwrap());
    if machine != 0x8664 {
        return Err(format!(
            "archive runtime {label} is not Windows x64 (machine 0x{machine:04x})"
        ));
    }
    Ok(())
}

pub(crate) fn verify_runtime_at(base: &Path) -> Result<VerifiedRuntime, String> {
    let public_lock = base.join(LOCK_FILE_NAME);
    let lock_bytes = fs::read(&public_lock).map_err(|error| {
        format!(
            "unable to read archive runtime lock {}: {error}",
            public_lock.display()
        )
    })?;
    if lock_bytes != EMBEDDED_LOCK.as_bytes() {
        return Err(
            "public archive runtime lock does not match the lock embedded in koi.exe".to_string(),
        );
    }
    let lock = parse_embedded_lock()?;
    let runtime_dir = base.join(RUNTIME_DIR_NAME);
    let canonical_root = fs::canonicalize(&runtime_dir).map_err(|error| {
        format!(
            "unable to resolve archive runtime directory {}: {error}",
            runtime_dir.display()
        )
    })?;
    if !canonical_root.is_dir() {
        return Err("archive runtime path is not a directory".to_string());
    }
    let expected = lock
        .files
        .iter()
        .map(|entry| entry.path.clone())
        .collect::<BTreeSet<_>>();
    let actual = runtime_inventory(&canonical_root)?;
    if actual != expected {
        let missing = expected.difference(&actual).cloned().collect::<Vec<_>>();
        let extra = actual.difference(&expected).cloned().collect::<Vec<_>>();
        return Err(format!(
            "archive runtime inventory mismatch (missing: {}; extra: {})",
            missing.join(", "),
            extra.join(", ")
        ));
    }
    for entry in &lock.files {
        let relative = validate_relative_file_path(&entry.path)?;
        let path = canonical_root.join(relative);
        let canonical = fs::canonicalize(&path)
            .map_err(|error| format!("unable to resolve archive runtime entry: {error}"))?;
        if !canonical.starts_with(&canonical_root) {
            return Err(format!(
                "archive runtime entry escaped its root: {}",
                entry.path
            ));
        }
        let (size, digest) = sha256_file(&canonical, MAX_RUNTIME_FILE_BYTES)?;
        if size != entry.size || digest != entry.sha256 {
            return Err(format!("archive runtime hash mismatch: {}", entry.path));
        }
    }
    let executable = canonical_root.join(EXECUTABLE_FILE_NAME);
    verify_pe_x64(&executable, EXECUTABLE_FILE_NAME)?;
    verify_pe_x64(&canonical_root.join(CODEC_FILE_NAME), CODEC_FILE_NAME)?;
    Ok(VerifiedRuntime {
        root: canonical_root,
        executable,
    })
}

fn runtime_base_candidates_for(
    debug_build: bool,
    debug_override: Option<PathBuf>,
    executable_dir: Option<PathBuf>,
    source_root: PathBuf,
) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if debug_build {
        if let Some(path) = debug_override {
            candidates.push(path);
        }
    }
    if let Some(parent) = executable_dir {
        candidates.push(parent);
    }
    if debug_build {
        candidates.push(source_root);
    }
    let mut unique = BTreeSet::new();
    candidates
        .into_iter()
        .filter(|path| unique.insert(path.clone()))
        .collect()
}

fn runtime_base_candidates() -> Vec<PathBuf> {
    let debug_override = cfg!(debug_assertions)
        .then(|| std::env::var_os("KOI_ARCHIVE_RUNTIME_BASE").map(PathBuf::from))
        .flatten();
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let source_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..");
    runtime_base_candidates_for(
        cfg!(debug_assertions),
        debug_override,
        executable_dir,
        source_root,
    )
}

pub(crate) fn discover_verified_runtime() -> Result<VerifiedRuntime, String> {
    let candidates = runtime_base_candidates();
    let mut errors = Vec::new();
    for base in &candidates {
        match verify_runtime_at(base) {
            Ok(runtime) => return Ok(runtime),
            Err(error) => errors.push(format!("{}: {error}", base.display())),
        }
    }
    Err(format!(
        "no verified archive runtime is available; {}",
        errors.join(" | ")
    ))
}

pub(crate) fn run_self_test_at(base: &Path) -> Result<RuntimeReport, String> {
    let runtime = verify_runtime_at(base)?;
    let lock = parse_embedded_lock()?;
    let mut command = Command::new(runtime.executable());
    command
        .args(["i", "-sccUTF-8"])
        .current_dir(runtime.root())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000);
    let output = command
        .output()
        .map_err(|error| format!("unable to start archive runtime self-test: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "archive runtime self-test failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let capabilities = String::from_utf8(output.stdout)
        .map_err(|error| format!("archive runtime self-test output is not UTF-8: {error}"))?;
    let rar_supported = capabilities
        .lines()
        .any(|line| line.split_whitespace().any(|field| field == "Rar"))
        && capabilities
            .lines()
            .any(|line| line.split_whitespace().any(|field| field == "Rar5"));
    if !rar_supported {
        return Err("archive runtime does not advertise RAR and RAR5 decoders".to_string());
    }
    Ok(RuntimeReport {
        version: lock.version,
        files_verified: lock.files.len(),
        rar_supported,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEST_ID: AtomicU64 = AtomicU64::new(1);

    fn temporary_base(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "koi-archive-runtime-{label}-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn bundled_runtime_matches_embedded_lock() {
        let source_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let runtime = verify_runtime_at(&source_root).expect("verify bundled archive runtime");
        assert_eq!(
            runtime
                .executable()
                .file_name()
                .and_then(|name| name.to_str()),
            Some(EXECUTABLE_FILE_NAME)
        );
        let report = run_self_test_at(&source_root).expect("run archive runtime self-test");
        assert_eq!(report.version, "26.02");
        assert_eq!(report.files_verified, 3);
        assert!(report.rar_supported);
    }

    #[test]
    fn release_build_never_uses_debug_override_or_source_tree() {
        let candidates = runtime_base_candidates_for(
            false,
            Some(PathBuf::from("override")),
            Some(PathBuf::from("release")),
            PathBuf::from("source"),
        );
        assert_eq!(candidates, vec![PathBuf::from("release")]);
    }

    #[test]
    fn rejects_traversal_in_lock_paths() {
        assert!(validate_relative_file_path("../7z.exe").is_err());
        assert!(validate_relative_file_path("folder\\7z.exe").is_err());
        assert!(validate_relative_file_path("C:/7z.exe").is_err());
    }

    #[test]
    fn rejects_runtime_file_tampering_and_extra_plugins() {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let base = temporary_base("tamper");
        fs::copy(source.join(LOCK_FILE_NAME), base.join(LOCK_FILE_NAME)).unwrap();
        copy_runtime_tree(&source.join(RUNTIME_DIR_NAME), &base.join(RUNTIME_DIR_NAME));

        let executable = base.join(RUNTIME_DIR_NAME).join(EXECUTABLE_FILE_NAME);
        let mut bytes = fs::read(&executable).unwrap();
        bytes[128] ^= 1;
        fs::write(&executable, bytes).unwrap();
        assert!(verify_runtime_at(&base)
            .unwrap_err()
            .contains("hash mismatch"));

        fs::copy(
            source.join(RUNTIME_DIR_NAME).join(EXECUTABLE_FILE_NAME),
            &executable,
        )
        .unwrap();
        fs::write(base.join(RUNTIME_DIR_NAME).join("unreviewed.dll"), b"extra").unwrap();
        assert!(verify_runtime_at(&base)
            .unwrap_err()
            .contains("inventory mismatch"));
        let _ = fs::remove_dir_all(base);
    }

    fn copy_runtime_tree(source: &Path, destination: &Path) {
        fs::create_dir_all(destination).unwrap();
        for entry in fs::read_dir(source).unwrap() {
            let entry = entry.unwrap();
            let target = destination.join(entry.file_name());
            if entry.file_type().unwrap().is_dir() {
                copy_runtime_tree(&entry.path(), &target);
            } else {
                fs::copy(entry.path(), target).unwrap();
            }
        }
    }
}
