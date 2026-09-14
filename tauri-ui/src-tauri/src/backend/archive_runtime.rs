//! Publisher-signed NanaZip runtime used for 7z and RAR inspection/extraction.
//!
//! The executable is never resolved from `PATH`. The public lock must match
//! the lock embedded in `koi.exe`, and the complete runtime inventory is
//! checked before each archive operation. The extracted console and libraries
//! must remain byte-identical to entries in a Microsoft Marketplace signed
//! MSIX whose Authenticode chain is verified by Windows on every use.

use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::Read;
#[cfg(windows)]
use std::os::windows::ffi::OsStrExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
#[cfg(windows)]
use windows::core::PCWSTR;
#[cfg(windows)]
use windows::Win32::Foundation::{HANDLE, HWND};
#[cfg(windows)]
use windows::Win32::Security::WinTrust::{
    WinVerifyTrust, WINTRUST_ACTION_GENERIC_VERIFY_V2, WINTRUST_DATA, WINTRUST_DATA_0,
    WINTRUST_FILE_INFO, WTD_CACHE_ONLY_URL_RETRIEVAL, WTD_CHOICE_FILE, WTD_REVOCATION_CHECK_NONE,
    WTD_REVOKE_NONE, WTD_SAFER_FLAG, WTD_STATEACTION_CLOSE, WTD_STATEACTION_VERIFY, WTD_UI_NONE,
};
use zip::ZipArchive;

pub const LOCK_FILE_NAME: &str = "archive-runtime.lock.json";
pub const RUNTIME_DIR_NAME: &str = "archive-runtime";
const EMBEDDED_LOCK: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../archive-runtime.lock.json"
));
const EXPECTED_FORMAT: &str = "koi-archive-runtime-v3";
const EXPECTED_PLATFORM: &str = "windows-x64";
const EXPECTED_ARCHITECTURE: &str = "x86_64";
const EXPECTED_PROJECT: &str = "NanaZip";
const EXPECTED_RELEASE_COMMIT: &str = "4f6f082858cb959a82c0d64a46352d7fb40ff146";
const EXPECTED_RELEASE_ASSET: &str = "NanaZip_7.0.1832.0.msixbundle";
const EXPECTED_RELEASE_ASSET_URL: &str =
    "https://github.com/M2Team/NanaZip/releases/download/7.0.1832.0/NanaZip_7.0.1832.0.msixbundle";
const EXPECTED_RELEASE_ASSET_SHA256: &str =
    "10ce4246ea9efc0dcc7780e676cdcc6c7c74eca0abeb19a5ea76f384d9be2a75";
const EXPECTED_LICENSE_ASSET: &str = "NanaZip_7.0.1832.0_Binaries.zip";
const EXPECTED_LICENSE_ASSET_URL: &str = "https://github.com/M2Team/NanaZip/releases/download/7.0.1832.0/NanaZip_7.0.1832.0_Binaries.zip";
const EXPECTED_LICENSE_ASSET_SHA256: &str =
    "3cfd7745e87e1b8409a467f08dafdbd51d5c666d9df82c2770d38639ad31f910";
const EXPECTED_SIGNED_PACKAGE_SHA256: &str =
    "df0469573ec269a5bc1dc589a68a19dda3dc8dfe4b4a8d849de81ee42c422e40";
const EXPECTED_TRUST_MODEL: &str = "publisher-signed-msix-runtime-binding-v1";
const EXPECTED_SIGNER_SUBJECT: &str = "CN=E310A153-74A9-4D81-800B-857A8D58408A";
const EXPECTED_SIGNER_THUMBPRINT: &str = "6f9e58cdb36763170616b86c419b8bb19e85e86c";
const EXPECTED_PACKAGE_IDENTITY: &str = "40174MouriNaruto.NanaZip";
const SIGNED_PACKAGE_FILE_NAME: &str = "NanaZipPackage_7.0.1832.0_x64.msix";
const EXECUTABLE_FILE_NAME: &str = "NanaZip.Universal.Console.exe";
const CORE_FILE_NAME: &str = "NanaZip.Core.dll";
const CODEC_FILE_NAME: &str = "NanaZip.Codecs.dll";
const BASE_SUPPORT_FILE_NAME: &str = "K7Base.dll";
const USER_SUPPORT_FILE_NAME: &str = "K7User.dll";
const LICENSE_FILE_NAME: &str = "License.txt";
const MAX_RUNTIME_FILE_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeLock {
    format: String,
    version: String,
    engine_version: String,
    platform: String,
    architecture: String,
    source: RuntimeSource,
    trust: RuntimeTrust,
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
    release_commit: String,
    release_asset: String,
    release_asset_url: String,
    release_asset_size: u64,
    release_asset_sha256: String,
    license_asset: String,
    license_asset_url: String,
    license_asset_size: u64,
    license_asset_sha256: String,
    signed_package: String,
    signed_package_size: u64,
    signed_package_sha256: String,
    release_date: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTrust {
    model: String,
    publisher_authenticated: bool,
    publisher_signature: PublisherSignature,
    package_identity: PackageIdentity,
    evidence: Vec<TrustEvidence>,
    reviewed_at: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct PublisherSignature {
    package: String,
    signer_subject: String,
    signer_thumbprint: String,
    timestamped: bool,
    runtime_binding: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct PackageIdentity {
    name: String,
    publisher: String,
    version: String,
    architecture: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustEvidence {
    kind: String,
    authority: String,
    url: String,
    #[serde(default)]
    artifact: Option<String>,
    #[serde(default)]
    artifact_url: Option<String>,
    #[serde(default)]
    sha256: Option<String>,
    #[serde(default)]
    commit: Option<String>,
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
    pub(crate) trust_model: String,
    pub(crate) publisher_authenticated: bool,
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
    if lock.version != "7.0.1832.0"
        || lock.engine_version != "2609.1"
        || lock.source.release_commit != EXPECTED_RELEASE_COMMIT
        || lock.source.upstream_url != "https://github.com/M2Team/NanaZip"
        || lock.source.release_url != "https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0"
        || lock.source.release_asset != EXPECTED_RELEASE_ASSET
        || lock.source.release_asset_url != EXPECTED_RELEASE_ASSET_URL
        || lock.source.release_asset_size != 11_930_165
        || lock.source.release_asset_sha256 != EXPECTED_RELEASE_ASSET_SHA256
        || lock.source.license_asset != EXPECTED_LICENSE_ASSET
        || lock.source.license_asset_url != EXPECTED_LICENSE_ASSET_URL
        || lock.source.license_asset_size != 8_090_745
        || lock.source.license_asset_sha256 != EXPECTED_LICENSE_ASSET_SHA256
        || lock.source.signed_package != SIGNED_PACKAGE_FILE_NAME
        || lock.source.signed_package_size != 5_858_305
        || lock.source.signed_package_sha256 != EXPECTED_SIGNED_PACKAGE_SHA256
        || lock.source.release_date != "2026-09-06"
    {
        return Err("embedded archive runtime source provenance is incomplete".to_string());
    }
    validate_trust(&lock.trust)?;
    if lock.licenses.console_spdx != "MIT AND LGPL-2.1-or-later"
        || lock.licenses.notice_file != LICENSE_FILE_NAME
        || !lock
            .licenses
            .library_summary
            .contains("LicenseRef-unRAR-restriction")
    {
        return Err("embedded archive runtime license metadata is invalid".to_string());
    }

    let mut paths = BTreeSet::new();
    let mut required_roles = BTreeSet::new();
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
        let required = matches!(
            (entry.path.as_str(), entry.role.as_str()),
            (SIGNED_PACKAGE_FILE_NAME, "publisher-signed-package")
                | (EXECUTABLE_FILE_NAME, "console-runtime")
                | (CORE_FILE_NAME, "core-runtime")
                | (CODEC_FILE_NAME, "codec-runtime")
                | (BASE_SUPPORT_FILE_NAME, "base-support-runtime")
                | (USER_SUPPORT_FILE_NAME, "user-support-runtime")
                | (LICENSE_FILE_NAME, "license")
        );
        if !required || !required_roles.insert(entry.role.as_str()) {
            return Err(format!(
                "unexpected archive runtime path or role: {} ({})",
                entry.path, entry.role
            ));
        }
    }
    if paths.len() != 7 || required_roles.len() != 7 {
        return Err("archive runtime lock must contain the signed NanaZip package, its five bound runtime files, and License.txt".to_string());
    }
    Ok(lock)
}

fn validate_trust(trust: &RuntimeTrust) -> Result<(), String> {
    if trust.model != EXPECTED_TRUST_MODEL
        || !trust.publisher_authenticated
        || trust.publisher_signature.package != "authenticode-valid"
        || trust.publisher_signature.signer_subject != EXPECTED_SIGNER_SUBJECT
        || trust.publisher_signature.signer_thumbprint != EXPECTED_SIGNER_THUMBPRINT
        || !trust.publisher_signature.timestamped
        || trust.publisher_signature.runtime_binding != "byte-identical-msix-entries"
        || trust.package_identity.name != EXPECTED_PACKAGE_IDENTITY
        || trust.package_identity.publisher != EXPECTED_SIGNER_SUBJECT
        || trust.package_identity.version != "7.0.1832.0"
        || trust.package_identity.architecture != "x64"
        || trust.reviewed_at != "2026-09-14"
        || trust.evidence.len() != 3
    {
        return Err("archive runtime trust declaration is invalid".to_string());
    }

    let mut kinds = BTreeSet::new();
    for evidence in &trust.evidence {
        if !kinds.insert(evidence.kind.as_str()) {
            return Err("archive runtime trust evidence contains duplicate kinds".to_string());
        }
        let valid = match evidence.kind.as_str() {
            "official-release-asset" => {
                evidence.authority == "M2-Team NanaZip GitHub release"
                    && evidence.url
                        == "https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0"
                    && evidence.artifact.as_deref() == Some(EXPECTED_RELEASE_ASSET)
                    && evidence.artifact_url.as_deref() == Some(EXPECTED_RELEASE_ASSET_URL)
                    && evidence.sha256.as_deref() == Some(EXPECTED_RELEASE_ASSET_SHA256)
                    && evidence.commit.is_none()
            }
            "microsoft-marketplace-authenticode" => {
                evidence.authority == "Microsoft Marketplace CA G 024"
                    && evidence.url
                        == "https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0"
                    && evidence.artifact.as_deref() == Some(SIGNED_PACKAGE_FILE_NAME)
                    && evidence.sha256.as_deref() == Some(EXPECTED_SIGNED_PACKAGE_SHA256)
                    && evidence.artifact_url.is_none()
                    && evidence.commit.is_none()
            }
            "signed-package-runtime-binding" => {
                evidence.authority == "KOI release review"
                    && evidence.url
                        == "https://github.com/M2Team/NanaZip/tree/4f6f082858cb959a82c0d64a46352d7fb40ff146"
                    && evidence.artifact.as_deref()
                        == Some("NanaZip.Universal.Console.exe,NanaZip.Core.dll,NanaZip.Codecs.dll,K7Base.dll,K7User.dll")
                    && evidence.sha256.is_none()
                    && evidence.artifact_url.is_none()
                    && evidence.commit.as_deref() == Some(EXPECTED_RELEASE_COMMIT)
            }
            _ => false,
        };
        if !valid {
            return Err(format!(
                "archive runtime trust evidence is invalid: {}",
                evidence.kind
            ));
        }
    }
    Ok(())
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
    if pe_offset
        .checked_add(24)
        .is_none_or(|end| end > bytes.len())
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
    let optional_header_size =
        u16::from_le_bytes(bytes[pe_offset + 20..pe_offset + 22].try_into().unwrap()) as usize;
    let optional_header = pe_offset + 24;
    if optional_header_size < 152
        || optional_header
            .checked_add(optional_header_size)
            .is_none_or(|end| end > bytes.len())
        || u16::from_le_bytes(
            bytes[optional_header..optional_header + 2]
                .try_into()
                .unwrap(),
        ) != 0x020b
    {
        return Err(format!(
            "archive runtime {label} has an invalid PE32+ optional header"
        ));
    }
    Ok(())
}

fn runtime_lock_entry<'a>(lock: &'a RuntimeLock, path: &str) -> Result<&'a RuntimeFile, String> {
    lock.files
        .iter()
        .find(|entry| entry.path == path)
        .ok_or_else(|| format!("archive runtime lock is missing {path}"))
}

fn verify_msix_entry(
    archive: &mut ZipArchive<File>,
    package_path: &str,
    lock: &RuntimeLock,
) -> Result<(), String> {
    let expected = runtime_lock_entry(lock, package_path)?;
    let mut entry = archive
        .by_name(package_path)
        .map_err(|error| format!("signed NanaZip package is missing {package_path}: {error}"))?;
    if entry.is_dir() || entry.size() != expected.size || entry.size() > MAX_RUNTIME_FILE_BYTES {
        return Err(format!(
            "signed NanaZip package entry has an invalid size: {package_path}"
        ));
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = entry
            .read(&mut buffer)
            .map_err(|error| format!("read signed NanaZip package entry failed: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| "signed NanaZip package entry size overflow".to_string())?;
        if total > expected.size {
            return Err(format!(
                "signed NanaZip package entry exceeds its lock: {package_path}"
            ));
        }
        hasher.update(&buffer[..count]);
    }
    let digest = format!("{:x}", hasher.finalize());
    if total != expected.size || digest != expected.sha256 {
        return Err(format!(
            "signed NanaZip package entry does not match the runtime lock: {package_path}"
        ));
    }
    Ok(())
}

fn verify_signed_package_contents(path: &Path, lock: &RuntimeLock) -> Result<(), String> {
    let file =
        File::open(path).map_err(|error| format!("open signed NanaZip package failed: {error}"))?;
    let mut archive = ZipArchive::new(file)
        .map_err(|error| format!("signed NanaZip package is not a valid MSIX: {error}"))?;
    for entry in [
        EXECUTABLE_FILE_NAME,
        CORE_FILE_NAME,
        CODEC_FILE_NAME,
        BASE_SUPPORT_FILE_NAME,
        USER_SUPPORT_FILE_NAME,
    ] {
        verify_msix_entry(&mut archive, entry, lock)?;
    }
    let mut manifest = String::new();
    archive
        .by_name("AppxManifest.xml")
        .map_err(|error| format!("signed NanaZip package lacks AppxManifest.xml: {error}"))?
        .take(256 * 1024)
        .read_to_string(&mut manifest)
        .map_err(|error| format!("read NanaZip package identity failed: {error}"))?;
    for identity in [
        &format!("Name=\"{EXPECTED_PACKAGE_IDENTITY}\""),
        &format!("Publisher=\"{EXPECTED_SIGNER_SUBJECT}\""),
        "Version=\"7.0.1832.0\"",
        "ProcessorArchitecture=\"x64\"",
        &format!("Executable=\"{EXECUTABLE_FILE_NAME}\""),
    ] {
        if !manifest.contains(identity) {
            return Err(format!(
                "signed NanaZip package identity is missing {identity}"
            ));
        }
    }
    let signature = archive
        .by_name("AppxSignature.p7x")
        .map_err(|error| format!("signed NanaZip package lacks AppxSignature.p7x: {error}"))?;
    if signature.size() == 0 || signature.size() > 256 * 1024 {
        return Err("signed NanaZip package has an invalid signature part".to_string());
    }
    Ok(())
}

#[cfg(windows)]
fn verify_publisher_signature(path: &Path) -> Result<(), String> {
    let wide = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let mut file_info = WINTRUST_FILE_INFO {
        cbStruct: std::mem::size_of::<WINTRUST_FILE_INFO>() as u32,
        pcwszFilePath: PCWSTR(wide.as_ptr()),
        hFile: HANDLE::default(),
        pgKnownSubject: std::ptr::null_mut(),
    };
    let mut trust_data = WINTRUST_DATA {
        cbStruct: std::mem::size_of::<WINTRUST_DATA>() as u32,
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_FILE,
        Anonymous: WINTRUST_DATA_0 {
            pFile: &mut file_info,
        },
        dwStateAction: WTD_STATEACTION_VERIFY,
        dwProvFlags: WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_NONE | WTD_SAFER_FLAG,
        ..Default::default()
    };
    let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    // SAFETY: Both WinTrust structures and the UTF-16 path live through the
    // verify/close pair, and every pointer refers to initialized storage.
    let status = unsafe {
        WinVerifyTrust(
            HWND::default(),
            &mut action,
            (&mut trust_data as *mut WINTRUST_DATA).cast(),
        )
    };
    trust_data.dwStateAction = WTD_STATEACTION_CLOSE;
    // SAFETY: This closes only the state handle created by the verify call.
    unsafe {
        WinVerifyTrust(
            HWND::default(),
            &mut action,
            (&mut trust_data as *mut WINTRUST_DATA).cast(),
        );
    }
    if status != 0 {
        return Err(format!(
            "NanaZip MSIX publisher signature verification failed: 0x{:08x}",
            status as u32
        ));
    }
    Ok(())
}

#[cfg(not(windows))]
fn verify_publisher_signature(_path: &Path) -> Result<(), String> {
    Err("NanaZip publisher signature verification requires Windows".to_string())
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
    let signed_package = canonical_root.join(SIGNED_PACKAGE_FILE_NAME);
    verify_publisher_signature(&signed_package)?;
    verify_signed_package_contents(&signed_package, &lock)?;
    let executable = canonical_root.join(EXECUTABLE_FILE_NAME);
    verify_pe_x64(&executable, EXECUTABLE_FILE_NAME)?;
    verify_pe_x64(&canonical_root.join(CORE_FILE_NAME), CORE_FILE_NAME)?;
    verify_pe_x64(&canonical_root.join(CODEC_FILE_NAME), CODEC_FILE_NAME)?;
    verify_pe_x64(
        &canonical_root.join(BASE_SUPPORT_FILE_NAME),
        BASE_SUPPORT_FILE_NAME,
    )?;
    verify_pe_x64(
        &canonical_root.join(USER_SUPPORT_FILE_NAME),
        USER_SUPPORT_FILE_NAME,
    )?;
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
    // Unit/integration test binaries live below `target/<profile>/deps` and
    // do not carry the immutable runtime beside them.  Test-only source-tree
    // lookup lets those tests verify the checked-in lock; production release
    // binaries keep the source-tree fallback disabled.
    let allow_test_source = cfg!(debug_assertions) || cfg!(test);
    let debug_override = allow_test_source
        .then(|| std::env::var_os("KOI_ARCHIVE_RUNTIME_BASE").map(PathBuf::from))
        .flatten();
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let source_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..");
    runtime_base_candidates_for(
        allow_test_source,
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
        trust_model: lock.trust.model,
        publisher_authenticated: lock.trust.publisher_authenticated,
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
        assert_eq!(report.version, "7.0.1832.0");
        assert_eq!(report.files_verified, 7);
        assert!(report.rar_supported);
        assert_eq!(report.trust_model, EXPECTED_TRUST_MODEL);
        assert!(report.publisher_authenticated);
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

    #[test]
    fn signed_package_is_valid_and_tampering_breaks_publisher_verification() {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join(RUNTIME_DIR_NAME)
            .join(SIGNED_PACKAGE_FILE_NAME);
        verify_publisher_signature(&source).expect("publisher-signed NanaZip package");
        let base = temporary_base("tampered-signature");
        let package = base.join(SIGNED_PACKAGE_FILE_NAME);
        let mut bytes = fs::read(source).unwrap();
        bytes[1024] ^= 1;
        fs::write(&package, bytes).unwrap();
        assert!(verify_publisher_signature(&package)
            .unwrap_err()
            .contains("publisher signature verification failed"));
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
