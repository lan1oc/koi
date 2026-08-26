//! Locked Python wheel handling for the dynamic probe runtime.
//!
//! The probe is allowed to use Python only as a narrowly scoped dynamic
//! capability.  Consequently package installation has a deliberately small
//! surface: a checked-in lock describes the complete dependency closure,
//! artifacts are fetched only from the PyPI index/host, every archive is
//! hashed before use, and installation is an offline ZIP extraction.  Source
//! distributions are never built implicitly.  Callers must opt into the
//! explicit source-build policy, which currently remains fail-closed until a
//! dedicated Windows build sandbox is provided.

use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;
use zip::ZipArchive;

pub const LOCK_FILE_NAME: &str = "probe-wheels.lock.json";
pub const LOCK_FORMAT: &str = "koi-probe-wheels-v1";
pub const PYPI_SIMPLE_SOURCE: &str = "https://pypi.org/simple";
const EMBEDDED_LOCK: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../probe-wheels.lock.json"
));
const MAX_LOCK_BYTES: u64 = 2 * 1024 * 1024;
const MAX_WHEEL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_INSTALL_BYTES: u64 = 256 * 1024 * 1024;
const MAX_FILES_PER_WHEEL: usize = 20_000;
const MAX_PACKAGES: usize = 512;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeWheelLock {
    pub format: String,
    /// This is intentionally an exact string, not a configurable mirror.
    pub source: String,
    /// Packages requested by the probe feature.  Their transitive closure is
    /// checked before any artifact is downloaded.
    #[serde(default)]
    pub roots: Vec<String>,
    pub packages: Vec<LockedWheelPackage>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LockedWheelPackage {
    pub name: String,
    pub version: String,
    /// Normalized package names in the already-resolved dependency graph.
    /// A lock generator must include every transitive dependency here.
    #[serde(default)]
    pub dependencies: Vec<String>,
    /// Import roots explicitly reviewed for the probe.  Distribution names
    /// and import names are not always identical (for example Pillow/PIL), so
    /// this is kept separate from `name`.
    #[serde(default)]
    pub imports: Vec<String>,
    pub wheel: LockedWheelArtifact,
    /// Optional source distribution metadata is retained for audit purposes,
    /// but it can never be selected by the normal wheel path.
    #[serde(default)]
    pub source_distribution: Option<LockedWheelArtifact>,
    /// Reviewed PEP 517 build metadata. The builder is invoked only by the
    /// separate, manually approved source-build operation.
    #[serde(default)]
    pub source_build: Option<LockedSourceBuild>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LockedSourceBuild {
    /// Importable PEP 517 backend module, for example `flit_core.buildapi`.
    pub backend: String,
    /// Exact project directory created below the extraction root.
    pub source_subdir: String,
    /// Complete, already-locked binary-wheel closure needed by the backend.
    #[serde(default)]
    pub build_dependencies: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LockedWheelArtifact {
    pub filename: String,
    pub url: String,
    pub sha256: String,
    #[serde(default)]
    pub size: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedWheel {
    pub name: String,
    pub version: String,
    pub artifact: LockedWheelArtifact,
    pub imports: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DownloadedWheel {
    pub package: ResolvedWheel,
    pub path: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PreparedSourceBuild {
    pub name: String,
    pub version: String,
    pub source: LockedWheelArtifact,
    pub backend: String,
    pub source_subdir: String,
    pub build_dependencies: Vec<DownloadedWheel>,
    pub source_path: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WheelInstallReport {
    pub packages: Vec<String>,
    pub files: usize,
    pub bytes: u64,
    pub site_packages: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedBuiltWheel {
    pub filename: String,
    pub sha256: String,
    pub size: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WheelError {
    pub stage: &'static str,
    pub message: String,
}

impl WheelError {
    fn new(stage: &'static str, message: impl Into<String>) -> Self {
        Self {
            stage,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for WheelError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "probe wheel {} failed: {}",
            self.stage, self.message
        )
    }
}

impl std::error::Error for WheelError {}

/// Read and validate the lock beside the packaged application.
pub fn load_lock(application_dir: &Path) -> Result<ProbeWheelLock, WheelError> {
    let path = application_dir.join(LOCK_FILE_NAME);
    let metadata = fs::symlink_metadata(&path).map_err(|error| {
        WheelError::new(
            "lock",
            format!("cannot inspect {}: {error}", path.display()),
        )
    })?;
    if !metadata.is_file() || is_reparse(&metadata) || metadata.len() > MAX_LOCK_BYTES {
        return Err(WheelError::new(
            "lock",
            "wheel lock must be a regular non-symlink file no larger than 2 MiB",
        ));
    }
    let bytes = fs::read(&path).map_err(|error| {
        WheelError::new("lock", format!("cannot read {}: {error}", path.display()))
    })?;
    if bytes != EMBEDDED_LOCK.as_bytes() {
        return Err(WheelError::new(
            "lock",
            "public probe wheel lock does not match the lock embedded in koi.exe",
        ));
    }
    let lock: ProbeWheelLock = serde_json::from_slice(&bytes)
        .map_err(|error| WheelError::new("lock", format!("invalid wheel lock JSON: {error}")))?;
    validate_lock(&lock)?;
    Ok(lock)
}

/// Validate the complete dependency graph without touching the network.
pub fn validate_lock(lock: &ProbeWheelLock) -> Result<(), WheelError> {
    if lock.format != LOCK_FORMAT {
        return Err(WheelError::new(
            "lock",
            format!("unsupported wheel lock format {:?}", lock.format),
        ));
    }
    if lock.source != PYPI_SIMPLE_SOURCE {
        return Err(WheelError::new(
            "lock",
            "wheel source must be exactly https://pypi.org/simple",
        ));
    }
    if lock.packages.len() > MAX_PACKAGES {
        return Err(WheelError::new(
            "lock",
            format!("wheel lock cannot contain more than {MAX_PACKAGES} packages"),
        ));
    }
    let mut by_name = BTreeMap::<String, &LockedWheelPackage>::new();
    for package in &lock.packages {
        let name = normalize_name(&package.name)?;
        if package.version.trim().is_empty() || package.version.len() > 128 {
            return Err(WheelError::new(
                "lock",
                format!("invalid version for package {name}"),
            ));
        }
        if by_name.insert(name.clone(), package).is_some() {
            return Err(WheelError::new("lock", format!("duplicate package {name}")));
        }
        validate_artifact(&package.wheel, false)?;
        validate_wheel_compatibility(&name, &package.version, &package.wheel.filename)?;
        if let Some(source) = package.source_distribution.as_ref() {
            validate_artifact(source, true)?;
        }
        match (&package.source_distribution, &package.source_build) {
            (None, Some(_)) => {
                return Err(WheelError::new(
                    "lock",
                    format!("source build metadata for {name} has no source distribution"),
                ))
            }
            (_, Some(build)) => {
                validate_import_name(&build.backend)?;
                validated_source_subdir(&build.source_subdir)?;
                if build.build_dependencies.len() > 64 {
                    return Err(WheelError::new(
                        "lock",
                        format!("source build for {name} contains too many dependencies"),
                    ));
                }
            }
            _ => {}
        }
        for dependency in &package.dependencies {
            normalize_name(dependency)?;
        }
        for import in &package.imports {
            validate_import_name(import)?;
        }
    }

    for root in &lock.roots {
        let root = normalize_name(root)?;
        if !by_name.contains_key(&root) {
            return Err(WheelError::new(
                "lock",
                format!("root package {root} is not present in the lock"),
            ));
        }
    }
    for package in &lock.packages {
        let name = normalize_name(&package.name)?;
        let mut seen = BTreeSet::new();
        for dependency in &package.dependencies {
            let dependency = normalize_name(dependency)?;
            if !seen.insert(dependency.clone()) {
                return Err(WheelError::new(
                    "lock",
                    format!("duplicate dependency {dependency} in {name}"),
                ));
            }
            if !by_name.contains_key(&dependency) {
                return Err(WheelError::new(
                    "lock",
                    format!("dependency {dependency} of {name} is not locked"),
                ));
            }
        }
        if let Some(build) = package.source_build.as_ref() {
            let mut seen_build = BTreeSet::new();
            for dependency in &build.build_dependencies {
                let dependency = normalize_name(dependency)?;
                if dependency == name {
                    return Err(WheelError::new(
                        "lock",
                        format!("source build for {name} depends on itself"),
                    ));
                }
                if !seen_build.insert(dependency.clone()) {
                    return Err(WheelError::new(
                        "lock",
                        format!("duplicate source-build dependency {dependency} in {name}"),
                    ));
                }
                if !by_name.contains_key(&dependency) {
                    return Err(WheelError::new(
                        "lock",
                        format!("source-build dependency {dependency} of {name} is not locked"),
                    ));
                }
            }
        }
    }
    // A cycle would make the lock's install order ambiguous and usually means
    // the resolver accidentally recorded an unresolved requirement.
    for package in &lock.packages {
        let root = normalize_name(&package.name)?;
        detect_cycle(&root, &by_name, &mut Vec::new(), &mut BTreeSet::new())?;
    }
    Ok(())
}

fn detect_cycle(
    name: &str,
    packages: &BTreeMap<String, &LockedWheelPackage>,
    stack: &mut Vec<String>,
    completed: &mut BTreeSet<String>,
) -> Result<(), WheelError> {
    if completed.contains(name) {
        return Ok(());
    }
    if stack.iter().any(|item| item == name) {
        return Err(WheelError::new(
            "lock",
            format!("dependency cycle detected at {name}"),
        ));
    }
    stack.push(name.to_string());
    let package = packages
        .get(name)
        .ok_or_else(|| WheelError::new("lock", format!("package {name} is not locked")))?;
    for dependency in &package.dependencies {
        detect_cycle(&normalize_name(dependency)?, packages, stack, completed)?;
    }
    stack.pop();
    completed.insert(name.to_string());
    Ok(())
}

/// Resolve a requested package list to a deterministic, dependency-first
/// closure.  Package names are normalized using the Python distribution-name
/// rules (case-insensitive and `-`/`_`/`.` equivalent).
pub fn resolve_packages(
    lock: &ProbeWheelLock,
    requested: &[String],
) -> Result<Vec<ResolvedWheel>, WheelError> {
    validate_lock(lock)?;
    let by_name = lock
        .packages
        .iter()
        .map(|package| Ok((normalize_name(&package.name)?, package)))
        .collect::<Result<BTreeMap<_, _>, WheelError>>()?;
    let roots = if requested.is_empty() {
        lock.roots.clone()
    } else {
        requested.to_vec()
    };
    if roots.is_empty() {
        return Err(WheelError::new(
            "resolve",
            "at least one locked probe package must be requested",
        ));
    }
    let mut order = Vec::new();
    let mut emitted = BTreeSet::new();
    for root in roots {
        emit_dependency_first(&normalize_name(&root)?, &by_name, &mut emitted, &mut order)?;
    }
    Ok(order
        .into_iter()
        .map(|name| {
            let package = by_name[&name];
            ResolvedWheel {
                name,
                version: package.version.clone(),
                artifact: package.wheel.clone(),
                imports: package.imports.clone(),
            }
        })
        .collect())
}

fn emit_dependency_first(
    name: &str,
    packages: &BTreeMap<String, &LockedWheelPackage>,
    emitted: &mut BTreeSet<String>,
    order: &mut Vec<String>,
) -> Result<(), WheelError> {
    if emitted.contains(name) {
        return Ok(());
    }
    let package = packages
        .get(name)
        .ok_or_else(|| WheelError::new("resolve", format!("package {name} is not locked")))?;
    for dependency in &package.dependencies {
        emit_dependency_first(&normalize_name(dependency)?, packages, emitted, order)?;
    }
    emitted.insert(name.to_string());
    order.push(name.to_string());
    Ok(())
}

/// Download the locked wheel closure.  A valid matching cache file is reused;
/// otherwise the artifact is fetched with redirects disabled and atomically
/// replaced only after the expected SHA-256 is verified.
pub fn download_packages(
    application_dir: &Path,
    cache_dir: &Path,
    requested: &[String],
) -> Result<Vec<DownloadedWheel>, WheelError> {
    let lock = load_lock(application_dir)?;
    let packages = resolve_packages(&lock, requested)?;
    ensure_cache_dir(cache_dir)?;
    let client = artifact_client()?;
    let mut output = Vec::with_capacity(packages.len());
    for package in packages {
        let artifact = &package.artifact;
        validate_artifact(artifact, false)?;
        let path = ensure_cached_artifact(&client, cache_dir, artifact)?;
        output.push(DownloadedWheel { package, path });
    }
    Ok(output)
}

fn ensure_cache_dir(cache_dir: &Path) -> Result<(), WheelError> {
    fs::create_dir_all(cache_dir).map_err(|error| {
        WheelError::new(
            "download",
            format!("cannot create wheel cache {}: {error}", cache_dir.display()),
        )
    })?;
    let cache_metadata = fs::symlink_metadata(cache_dir).map_err(|error| {
        WheelError::new(
            "download",
            format!(
                "cannot inspect wheel cache {}: {error}",
                cache_dir.display()
            ),
        )
    })?;
    if !cache_metadata.is_dir() || is_reparse(&cache_metadata) {
        return Err(WheelError::new(
            "download",
            "wheel cache must be a non-symlink directory",
        ));
    }
    Ok(())
}

fn artifact_client() -> Result<Client, WheelError> {
    Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(30))
        .user_agent("KOI/4.0.0 probe-wheel-fetcher")
        .build()
        .map_err(|error| WheelError::new("download", format!("create HTTP client failed: {error}")))
}

fn ensure_cached_artifact(
    client: &Client,
    cache_dir: &Path,
    artifact: &LockedWheelArtifact,
) -> Result<PathBuf, WheelError> {
    let path = cache_dir.join(format!("{}-{}", &artifact.sha256[..16], artifact.filename));
    let mut valid_cache = false;
    if path.exists() {
        let metadata = fs::symlink_metadata(&path).map_err(|error| {
            WheelError::new(
                "download",
                format!("cannot inspect cached artifact {}: {error}", path.display()),
            )
        })?;
        if !metadata.is_file() || is_reparse(&metadata) {
            return Err(WheelError::new(
                "download",
                format!(
                    "cached artifact is not a regular non-symlink file: {}",
                    path.display()
                ),
            ));
        }
        valid_cache = hash_matches(&path, &artifact.sha256)?;
        if !valid_cache {
            fs::remove_file(&path).map_err(|error| {
                WheelError::new(
                    "download",
                    format!("remove invalid cached artifact failed: {error}"),
                )
            })?;
        }
    }
    if !valid_cache {
        let temporary = cache_dir.join(format!(".{}.part", unique_suffix()));
        let result = download_one(client, artifact, &temporary).and_then(|_| {
            fs::rename(&temporary, &path).map_err(|error| {
                WheelError::new(
                    "download",
                    format!("atomically install {} failed: {error}", path.display()),
                )
            })
        });
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result?;
    }
    Ok(path)
}

fn download_one(
    client: &Client,
    artifact: &LockedWheelArtifact,
    temporary: &Path,
) -> Result<(), WheelError> {
    let response = client.get(&artifact.url).send().map_err(|error| {
        WheelError::new(
            "download",
            format!("download {} failed: {error}", artifact.filename),
        )
    })?;
    if response.status().is_redirection() {
        return Err(WheelError::new(
            "download",
            "PyPI wheel download redirects are refused; lock the final artifact URL",
        ));
    }
    if !response.status().is_success() {
        return Err(WheelError::new(
            "download",
            format!(
                "download {} returned HTTP {}",
                artifact.filename,
                response.status()
            ),
        ));
    }
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(temporary)
        .map_err(|error| {
            WheelError::new(
                "download",
                format!("create temporary wheel failed: {error}"),
            )
        })?;
    let mut hasher = Sha256::new();
    let mut total = 0u64;
    let mut stream = response;
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = stream
            .read(&mut buffer)
            .map_err(|error| WheelError::new("download", format!("read wheel failed: {error}")))?;
        if count == 0 {
            break;
        }
        total = total.saturating_add(count as u64);
        if total > MAX_WHEEL_BYTES || artifact.size.is_some_and(|size| total > size) {
            return Err(WheelError::new(
                "download",
                format!("wheel {} exceeds locked size", artifact.filename),
            ));
        }
        hasher.update(&buffer[..count]);
        file.write_all(&buffer[..count])
            .map_err(|error| WheelError::new("download", format!("write wheel failed: {error}")))?;
    }
    file.sync_all()
        .map_err(|error| WheelError::new("download", format!("sync wheel failed: {error}")))?;
    let digest = hex_digest(hasher.finalize());
    if !digest.eq_ignore_ascii_case(&artifact.sha256) {
        return Err(WheelError::new(
            "download",
            format!("SHA-256 mismatch for {}", artifact.filename),
        ));
    }
    if artifact.size.is_some_and(|size| size != total) {
        return Err(WheelError::new(
            "download",
            format!("size mismatch for {}", artifact.filename),
        ));
    }
    Ok(())
}

/// Install already downloaded wheels without invoking pip or running a build
/// backend.  This function is intentionally offline and writes only inside
/// the supplied one-time directory.
pub fn install_offline(
    wheels: &[DownloadedWheel],
    site_packages: &Path,
) -> Result<WheelInstallReport, WheelError> {
    if wheels.is_empty() {
        return Err(WheelError::new("install", "no locked wheels to install"));
    }
    if site_packages.exists() {
        let metadata = fs::symlink_metadata(site_packages).map_err(|error| {
            WheelError::new("install", format!("cannot inspect site-packages: {error}"))
        })?;
        if !metadata.is_dir() || is_reparse(&metadata) {
            return Err(WheelError::new(
                "install",
                "site-packages must be a non-symlink directory",
            ));
        }
        if fs::read_dir(site_packages)
            .map_err(|error| WheelError::new("install", error.to_string()))?
            .next()
            .is_some()
        {
            return Err(WheelError::new(
                "install",
                "offline install destination must be empty",
            ));
        }
    } else {
        fs::create_dir_all(site_packages).map_err(|error| {
            WheelError::new("install", format!("create site-packages failed: {error}"))
        })?;
    }

    let mut seen_paths = BTreeSet::new();
    let mut file_count = 0usize;
    let mut total_bytes = 0u64;
    let mut package_names = Vec::with_capacity(wheels.len());
    for wheel in wheels {
        validate_artifact(&wheel.package.artifact, false)?;
        let metadata = fs::symlink_metadata(&wheel.path).map_err(|error| {
            WheelError::new(
                "install",
                format!(
                    "cannot inspect cached wheel {}: {error}",
                    wheel.path.display()
                ),
            )
        })?;
        if !metadata.is_file() || is_reparse(&metadata) {
            return Err(WheelError::new(
                "install",
                format!(
                    "cached wheel is not a regular non-symlink file: {}",
                    wheel.path.display()
                ),
            ));
        }
        let mut file = File::open(&wheel.path)
            .map_err(|error| WheelError::new("install", format!("open wheel failed: {error}")))?;
        if !hash_open_file(&mut file, &wheel.package.artifact.sha256)? {
            return Err(WheelError::new(
                "install",
                format!("cached wheel hash mismatch: {}", wheel.path.display()),
            ));
        }
        let mut archive = ZipArchive::new(file)
            .map_err(|error| WheelError::new("install", format!("invalid wheel ZIP: {error}")))?;
        if archive.len() > MAX_FILES_PER_WHEEL {
            return Err(WheelError::new("install", "wheel contains too many files"));
        }
        package_names.push(format!("{}=={}", wheel.package.name, wheel.package.version));
        let data_prefix = wheel_data_prefix(&wheel.package.artifact.filename)?;
        for index in 0..archive.len() {
            let mut entry = archive.by_index(index).map_err(|error| {
                WheelError::new("install", format!("read wheel entry failed: {error}"))
            })?;
            let archive_path = safe_zip_path(entry.name())?;
            let relative = wheel_install_path(&archive_path, &data_prefix)?;
            // Wheel metadata can contain RECORD and WHEEL files, but .pth
            // files execute arbitrary startup code and are not needed by the
            // restricted probe importer.
            if relative
                .extension()
                .is_some_and(|extension| extension.to_string_lossy().eq_ignore_ascii_case("pth"))
            {
                return Err(WheelError::new(
                    "install",
                    format!("wheel contains unsupported .pth file: {}", entry.name()),
                ));
            }
            if entry.is_dir() {
                fs::create_dir_all(site_packages.join(&relative)).map_err(|error| {
                    WheelError::new("install", format!("create wheel directory failed: {error}"))
                })?;
                continue;
            }
            file_count += 1;
            if file_count > MAX_FILES_PER_WHEEL.saturating_mul(wheels.len()) {
                return Err(WheelError::new(
                    "install",
                    "offline install contains too many files",
                ));
            }
            let destination = site_packages.join(&relative);
            let key = relative
                .to_string_lossy()
                .replace('\\', "/")
                .to_ascii_lowercase();
            if !seen_paths.insert(key) {
                return Err(WheelError::new(
                    "install",
                    format!("wheel path collision: {}", entry.name()),
                ));
            }
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent).map_err(|error| {
                    WheelError::new("install", format!("create wheel parent failed: {error}"))
                })?;
            }
            let mut output = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&destination)
                .map_err(|error| {
                    WheelError::new("install", format!("create wheel file failed: {error}"))
                })?;
            let mut buffer = [0u8; 64 * 1024];
            loop {
                let count = entry.read(&mut buffer).map_err(|error| {
                    WheelError::new("install", format!("read wheel file failed: {error}"))
                })?;
                if count == 0 {
                    break;
                }
                total_bytes = total_bytes.saturating_add(count as u64);
                if total_bytes > MAX_INSTALL_BYTES {
                    return Err(WheelError::new(
                        "install",
                        "offline install exceeds 256 MiB",
                    ));
                }
                output.write_all(&buffer[..count]).map_err(|error| {
                    WheelError::new("install", format!("write wheel file failed: {error}"))
                })?;
            }
            output.sync_all().map_err(|error| {
                WheelError::new("install", format!("sync wheel file failed: {error}"))
            })?;
        }
    }
    Ok(WheelInstallReport {
        packages: package_names,
        files: file_count,
        bytes: total_bytes,
        site_packages: site_packages.to_path_buf(),
    })
}

/// Validate the only artifact allowed to leave a source-build sandbox.
pub fn verify_built_wheel(
    package_name: &str,
    package_version: &str,
    path: &Path,
) -> Result<VerifiedBuiltWheel, WheelError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        WheelError::new(
            "source-build-output",
            format!("cannot inspect built wheel {}: {error}", path.display()),
        )
    })?;
    if !metadata.is_file() || is_reparse(&metadata) || metadata.len() > MAX_WHEEL_BYTES {
        return Err(WheelError::new(
            "source-build-output",
            "built wheel must be a regular non-symlink file no larger than 64 MiB",
        ));
    }
    let filename = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| WheelError::new("source-build-output", "built wheel name is not UTF-8"))?
        .to_string();
    let normalized = normalize_name(package_name)?;
    validate_wheel_compatibility(&normalized, package_version, &filename)?;

    let file = File::open(path).map_err(|error| {
        WheelError::new(
            "source-build-output",
            format!("cannot open built wheel: {error}"),
        )
    })?;
    let mut archive = ZipArchive::new(file).map_err(|error| {
        WheelError::new(
            "source-build-output",
            format!("built wheel is not a valid ZIP: {error}"),
        )
    })?;
    if archive.is_empty() || archive.len() > MAX_FILES_PER_WHEEL {
        return Err(WheelError::new(
            "source-build-output",
            "built wheel contains an invalid number of entries",
        ));
    }
    let mut total = 0_u64;
    let mut seen = BTreeSet::new();
    let mut has_metadata = false;
    let mut has_wheel = false;
    let mut has_record = false;
    for index in 0..archive.len() {
        let entry = archive.by_index(index).map_err(|error| {
            WheelError::new(
                "source-build-output",
                format!("cannot inspect built wheel entry: {error}"),
            )
        })?;
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err(WheelError::new(
                "source-build-output",
                format!("built wheel contains a symbolic link: {}", entry.name()),
            ));
        }
        let relative = safe_zip_path(entry.name())?;
        if relative
            .extension()
            .is_some_and(|extension| extension.to_string_lossy().eq_ignore_ascii_case("pth"))
        {
            return Err(WheelError::new(
                "source-build-output",
                "built wheel contains an executable .pth file",
            ));
        }
        let key = relative
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !seen.insert(key.clone()) {
            return Err(WheelError::new(
                "source-build-output",
                format!("built wheel contains a case-insensitive path collision: {key}"),
            ));
        }
        total = total
            .checked_add(entry.size())
            .ok_or_else(|| WheelError::new("source-build-output", "built wheel size overflow"))?;
        if total > MAX_INSTALL_BYTES {
            return Err(WheelError::new(
                "source-build-output",
                "built wheel expands beyond 256 MiB",
            ));
        }
        let upper = key.to_ascii_uppercase();
        has_metadata |= upper.ends_with(".DIST-INFO/METADATA");
        has_wheel |= upper.ends_with(".DIST-INFO/WHEEL");
        has_record |= upper.ends_with(".DIST-INFO/RECORD");
    }
    if !(has_metadata && has_wheel && has_record) {
        return Err(WheelError::new(
            "source-build-output",
            "built wheel is missing METADATA, WHEEL, or RECORD",
        ));
    }
    let sha256 = sha256_path(path)?;
    Ok(VerifiedBuiltWheel {
        filename,
        sha256,
        size: metadata.len(),
    })
}

pub fn persist_built_wheel(
    cache_dir: &Path,
    source: &Path,
    verified: &VerifiedBuiltWheel,
) -> Result<PathBuf, WheelError> {
    ensure_cache_dir(cache_dir)?;
    let destination = cache_dir.join(format!(
        "built-{}-{}",
        &verified.sha256[..16],
        verified.filename
    ));
    if destination.exists() {
        let metadata = fs::symlink_metadata(&destination).map_err(|error| {
            WheelError::new(
                "source-build-output",
                format!("inspect cache failed: {error}"),
            )
        })?;
        if !metadata.is_file()
            || is_reparse(&metadata)
            || metadata.len() != verified.size
            || !hash_matches(&destination, &verified.sha256)?
        {
            return Err(WheelError::new(
                "source-build-output",
                "existing built-wheel cache entry does not match the verified artifact",
            ));
        }
        return Ok(destination);
    }
    let temporary = cache_dir.join(format!(".{}.built.part", unique_suffix()));
    let copy_result = (|| {
        let input = File::open(source).map_err(|error| {
            WheelError::new(
                "source-build-output",
                format!("open output failed: {error}"),
            )
        })?;
        let mut output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| {
                WheelError::new(
                    "source-build-output",
                    format!("create cache failed: {error}"),
                )
            })?;
        let copied =
            std::io::copy(&mut input.take(MAX_WHEEL_BYTES + 1), &mut output).map_err(|error| {
                WheelError::new(
                    "source-build-output",
                    format!("copy output failed: {error}"),
                )
            })?;
        if copied != verified.size || copied > MAX_WHEEL_BYTES {
            return Err(WheelError::new(
                "source-build-output",
                "built wheel changed while it was committed",
            ));
        }
        output.sync_all().map_err(|error| {
            WheelError::new("source-build-output", format!("sync cache failed: {error}"))
        })?;
        if !hash_matches(&temporary, &verified.sha256)? {
            return Err(WheelError::new(
                "source-build-output",
                "built wheel changed while it was committed",
            ));
        }
        fs::rename(&temporary, &destination).map_err(|error| {
            WheelError::new(
                "source-build-output",
                format!("commit cache failed: {error}"),
            )
        })
    })();
    if copy_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    copy_result?;
    Ok(destination)
}

fn wheel_install_path(path: &Path, data_prefix: &str) -> Result<PathBuf, WheelError> {
    let normalized = path.to_string_lossy().replace('\\', "/");
    let lower = normalized.to_ascii_lowercase();
    if !lower.starts_with(data_prefix) {
        return Ok(path.to_path_buf());
    }
    let suffix = &normalized[data_prefix.len()..];
    let Some((scheme, relative)) = suffix.split_once('/') else {
        return Err(WheelError::new(
            "install",
            format!("wheel .data path is incomplete: {normalized}"),
        ));
    };
    // Purelib and platlib are the only wheel data schemes that belong on the
    // isolated sys.path.  Scripts could execute outside the probe contract;
    // headers/data would create files unrelated to imports.
    if !matches!(scheme.to_ascii_lowercase().as_str(), "purelib" | "platlib") {
        return Err(WheelError::new(
            "install",
            format!("wheel contains unsupported .data scheme {scheme:?}"),
        ));
    }
    safe_zip_path(relative)
}

fn wheel_data_prefix(filename: &str) -> Result<String, WheelError> {
    let stem = filename
        .strip_suffix(".whl")
        .ok_or_else(|| WheelError::new("install", "wheel filename must end with .whl"))?;
    let mut fields = stem.split('-');
    let distribution = fields
        .next()
        .ok_or_else(|| WheelError::new("install", "wheel distribution tag is missing"))?;
    let version = fields
        .next()
        .ok_or_else(|| WheelError::new("install", "wheel version tag is missing"))?;
    Ok(format!("{distribution}-{version}.data/").to_ascii_lowercase())
}

/// Enforce the explicit second-approval gate before any source artifact is
/// downloaded or a build sandbox is created.
pub fn reject_source_distribution(
    package: &LockedWheelPackage,
    second_approval: bool,
) -> Result<(), WheelError> {
    if package.source_distribution.is_none() {
        return Ok(());
    }
    if !second_approval {
        return Err(WheelError::new(
            "source-build-approval",
            format!(
                "source distribution for {} requires a second explicit approval",
                package.name
            ),
        ));
    }
    if package.source_build.is_none() {
        return Err(WheelError::new(
            "source-build-review",
            format!(
                "source distribution for {} has no reviewed build backend or dependency closure",
                package.name
            ),
        ));
    }
    Ok(())
}

/// Resolve and download a reviewed source artifact plus its complete binary
/// build-dependency closure. Downloading still happens in Rust; the subsequent
/// backend invocation must use `run_verified_source_build`, never host Python.
pub fn prepare_source_build(
    application_dir: &Path,
    cache_dir: &Path,
    requested: &str,
    second_approval: bool,
) -> Result<PreparedSourceBuild, WheelError> {
    let lock = load_lock(application_dir)?;
    let requested = normalize_name(requested)?;
    let package = lock
        .packages
        .iter()
        .find(|package| normalize_name(&package.name).ok().as_deref() == Some(&requested))
        .ok_or_else(|| {
            WheelError::new(
                "source-build-review",
                format!("source package {requested} is not present in the reviewed lock"),
            )
        })?;
    reject_source_distribution(package, second_approval)?;
    let source = package
        .source_distribution
        .clone()
        .expect("source gate checked");
    let build = package.source_build.clone().expect("source gate checked");
    validate_artifact(&source, true)?;
    ensure_cache_dir(cache_dir)?;
    let client = artifact_client()?;
    let source_path = ensure_cached_artifact(&client, cache_dir, &source)?;
    let build_dependencies = if build.build_dependencies.is_empty() {
        Vec::new()
    } else {
        download_packages(application_dir, cache_dir, &build.build_dependencies)?
    };
    Ok(PreparedSourceBuild {
        name: requested,
        version: package.version.clone(),
        source,
        backend: build.backend,
        source_subdir: build.source_subdir,
        build_dependencies,
        source_path,
    })
}

fn validate_wheel_compatibility(
    package_name: &str,
    package_version: &str,
    filename: &str,
) -> Result<(), WheelError> {
    let stem = filename
        .strip_suffix(".whl")
        .ok_or_else(|| WheelError::new("lock", "wheel filename must end with .whl"))?;
    let fields = stem.split('-').collect::<Vec<_>>();
    if !matches!(fields.len(), 5 | 6) {
        return Err(WheelError::new(
            "lock",
            format!("wheel filename has an unsupported tag layout: {filename}"),
        ));
    }
    let distribution = normalize_name(fields[0])?;
    if distribution != package_name {
        return Err(WheelError::new(
            "lock",
            format!("wheel distribution {distribution} does not match package {package_name}"),
        ));
    }
    let locked_version = package_version.trim().replace('-', "_");
    if fields[1] != locked_version {
        return Err(WheelError::new(
            "lock",
            format!(
                "wheel version {} does not match locked version {package_version}",
                fields[1]
            ),
        ));
    }
    let python_tag = fields[fields.len() - 3];
    let abi_tag = fields[fields.len() - 2];
    let platform_tag = fields[fields.len() - 1];
    let supports_py3 = python_tag.split('.').any(|tag| tag == "py3");
    let pure = supports_py3 && abi_tag == "none" && matches!(platform_tag, "any" | "win_amd64");
    let exact_native = python_tag.split('.').any(|tag| tag == "cp313")
        && matches!(abi_tag, "cp313" | "none")
        && platform_tag == "win_amd64";
    let stable_abi = abi_tag == "abi3"
        && platform_tag == "win_amd64"
        && python_tag.split('.').any(cpython_abi3_tag_supported);
    if !pure && !exact_native && !stable_abi {
        return Err(WheelError::new(
            "lock",
            format!("wheel {filename} is not compatible with locked CPython 3.13 Windows x64"),
        ));
    }
    Ok(())
}

fn cpython_abi3_tag_supported(tag: &str) -> bool {
    let Some(version) = tag.strip_prefix("cp") else {
        return false;
    };
    let Ok(version) = version.parse::<u16>() else {
        return false;
    };
    matches!(version, 32..=39 | 310..=313)
}

fn validate_artifact(artifact: &LockedWheelArtifact, source: bool) -> Result<(), WheelError> {
    let filename = artifact.filename.trim();
    if filename.is_empty()
        || filename.len() > 255
        || filename.contains(['/', '\\'])
        || (!source && !filename.to_ascii_lowercase().ends_with(".whl"))
        || (source
            && !filename.to_ascii_lowercase().ends_with(".tar.gz")
            && !filename.to_ascii_lowercase().ends_with(".zip"))
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid wheel artifact filename {filename:?}"),
        ));
    }
    let parsed = reqwest::Url::parse(&artifact.url)
        .map_err(|_| WheelError::new("lock", format!("invalid artifact URL: {}", artifact.url)))?;
    if parsed.scheme() != "https"
        || parsed.host_str() != Some("files.pythonhosted.org")
        || parsed.username() != ""
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err(WheelError::new(
            "lock",
            format!(
                "artifact URL is not an official files.pythonhosted.org URL: {}",
                artifact.url
            ),
        ));
    }
    let url_filename = parsed
        .path_segments()
        .and_then(|mut segments| segments.next_back())
        .unwrap_or_default();
    if url_filename != filename {
        return Err(WheelError::new(
            "lock",
            format!("artifact URL filename does not match {filename}"),
        ));
    }
    if artifact.sha256.len() != 64 || !artifact.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid SHA-256 for {}", artifact.filename),
        ));
    }
    if artifact
        .size
        .is_some_and(|size| size == 0 || size > MAX_WHEEL_BYTES)
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid size for {}", artifact.filename),
        ));
    }
    Ok(())
}

fn normalize_name(value: &str) -> Result<String, WheelError> {
    let trimmed = value.trim();
    if !trimmed
        .bytes()
        .next()
        .is_some_and(|byte| byte.is_ascii_alphanumeric())
        || !trimmed
            .bytes()
            .next_back()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid Python package name {value:?}"),
        ));
    }
    let mut normalized = String::new();
    let mut separator = false;
    for character in trimmed.chars() {
        if matches!(character, '-' | '_' | '.') {
            separator = true;
            continue;
        }
        if separator && !normalized.is_empty() {
            normalized.push('-');
        }
        separator = false;
        normalized.push(character.to_ascii_lowercase());
    }
    if normalized.is_empty()
        || normalized.len() > 128
        || normalized.starts_with('-')
        || normalized.ends_with('-')
        || !normalized
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid Python package name {value:?}"),
        ));
    }
    Ok(normalized)
}

fn validate_import_name(value: &str) -> Result<(), WheelError> {
    let value = value.trim();
    if value.is_empty()
        || value.len() > 128
        || value.split('.').any(|part| {
            let mut bytes = part.bytes();
            !bytes
                .next()
                .is_some_and(|byte| byte.is_ascii_alphabetic() || byte == b'_')
                || !bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
        })
    {
        return Err(WheelError::new(
            "lock",
            format!("invalid locked import name {value:?}"),
        ));
    }
    Ok(())
}

fn validated_source_subdir(value: &str) -> Result<PathBuf, WheelError> {
    if value.trim() != value || value.ends_with('/') {
        return Err(WheelError::new(
            "lock",
            format!("invalid source build subdirectory {value:?}"),
        ));
    }
    safe_zip_path(value).map_err(|_| {
        WheelError::new(
            "lock",
            format!("invalid source build subdirectory {value:?}"),
        )
    })
}

fn safe_zip_path(value: &str) -> Result<PathBuf, WheelError> {
    if value.trim().is_empty() || value.contains('\\') || value.starts_with('/') {
        return Err(WheelError::new(
            "install",
            format!("unsafe wheel path {value:?}"),
        ));
    }
    let raw = value.strip_suffix('/').unwrap_or(value);
    if raw
        .split('/')
        .any(|segment| segment.is_empty() || matches!(segment, "." | ".."))
    {
        return Err(WheelError::new(
            "install",
            format!("wheel path contains a non-canonical segment: {value:?}"),
        ));
    }
    let mut normalized = PathBuf::new();
    for component in Path::new(value).components() {
        let Component::Normal(segment) = component else {
            return Err(WheelError::new(
                "install",
                format!("wheel path escapes site-packages: {value:?}"),
            ));
        };
        let segment = segment.to_string_lossy();
        if unsafe_windows_segment(&segment) {
            return Err(WheelError::new(
                "install",
                format!("wheel path contains an unsafe Windows segment: {value:?}"),
            ));
        }
        normalized.push(segment.as_ref());
    }
    if normalized.as_os_str().is_empty() {
        return Err(WheelError::new("install", "wheel path is empty"));
    }
    Ok(normalized)
}

fn unsafe_windows_segment(segment: &str) -> bool {
    if segment.is_empty() || segment.contains([':', '\0']) || segment.ends_with([' ', '.']) {
        return true;
    }
    let stem = segment
        .split_once('.')
        .map(|(stem, _)| stem)
        .unwrap_or(segment)
        .trim_end_matches([' ', '.'])
        .to_ascii_uppercase();
    matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || stem
            .strip_prefix("COM")
            .or_else(|| stem.strip_prefix("LPT"))
            .is_some_and(|suffix| suffix.len() == 1 && matches!(suffix.as_bytes()[0], b'1'..=b'9'))
}

fn hash_matches(path: &Path, expected: &str) -> Result<bool, WheelError> {
    let mut file = File::open(path).map_err(|error| {
        WheelError::new("hash", format!("open {} failed: {error}", path.display()))
    })?;
    hash_open_file(&mut file, expected)
}

fn sha256_path(path: &Path) -> Result<String, WheelError> {
    let mut file = File::open(path).map_err(|error| {
        WheelError::new("hash", format!("open {} failed: {error}", path.display()))
    })?;
    let mut reader = (&mut file).take(MAX_WHEEL_BYTES + 1);
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|error| WheelError::new("hash", format!("read wheel failed: {error}")))?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > MAX_WHEEL_BYTES {
            return Err(WheelError::new("hash", "wheel exceeds 64 MiB"));
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hex_digest(hasher.finalize()))
}

fn hash_open_file(file: &mut File, expected: &str) -> Result<bool, WheelError> {
    file.seek(SeekFrom::Start(0))
        .map_err(|error| WheelError::new("hash", format!("seek wheel failed: {error}")))?;
    let mut hasher = Sha256::new();
    let mut bytes = 0u64;
    let mut buffer = [0u8; 64 * 1024];
    let too_large = {
        let mut reader = (&mut *file).take(MAX_WHEEL_BYTES + 1);
        loop {
            let count = reader
                .read(&mut buffer)
                .map_err(|error| WheelError::new("hash", format!("read wheel failed: {error}")))?;
            if count == 0 {
                break false;
            }
            bytes += count as u64;
            if bytes > MAX_WHEEL_BYTES {
                break true;
            }
            hasher.update(&buffer[..count]);
        }
    };
    file.seek(SeekFrom::Start(0))
        .map_err(|error| WheelError::new("hash", format!("rewind wheel failed: {error}")))?;
    if too_large {
        return Ok(false);
    }
    Ok(hex_digest(hasher.finalize()).eq_ignore_ascii_case(expected))
}

fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    bytes
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn unique_suffix() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};
    static NEXT: AtomicU64 = AtomicU64::new(1);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "{}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed),
        nanos
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
    use std::io::Cursor;
    use zip::write::SimpleFileOptions;

    fn digest(bytes: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        hex_digest(hasher.finalize())
    }

    fn artifact(filename: &str, bytes: &[u8]) -> LockedWheelArtifact {
        LockedWheelArtifact {
            filename: filename.to_string(),
            url: format!("https://files.pythonhosted.org/packages/aa/{filename}"),
            sha256: digest(bytes),
            size: Some(bytes.len() as u64),
        }
    }

    fn lock(packages: Vec<LockedWheelPackage>) -> ProbeWheelLock {
        ProbeWheelLock {
            format: LOCK_FORMAT.to_string(),
            source: PYPI_SIMPLE_SOURCE.to_string(),
            roots: vec![packages[0].name.clone()],
            packages,
        }
    }

    #[test]
    fn validates_recursive_closure_and_resolves_dependency_first() {
        let c = b"c";
        let b = b"b";
        let a = b"a";
        let lock = lock(vec![
            LockedWheelPackage {
                name: "A_Pkg".into(),
                version: "1.0".into(),
                dependencies: vec!["b-pkg".into()],
                imports: vec!["a_pkg".into()],
                wheel: artifact("a_pkg-1.0-py3-none-any.whl", a),
                source_distribution: None,
                source_build: None,
            },
            LockedWheelPackage {
                name: "b-pkg".into(),
                version: "2.0".into(),
                dependencies: vec!["c.pkg".into()],
                imports: vec!["b_pkg".into()],
                wheel: artifact("b_pkg-2.0-py3-none-any.whl", b),
                source_distribution: None,
                source_build: None,
            },
            LockedWheelPackage {
                name: "c.pkg".into(),
                version: "3.0".into(),
                dependencies: Vec::new(),
                imports: vec!["c_pkg".into()],
                wheel: artifact("c.pkg-3.0-py3-none-any.whl", c),
                source_distribution: None,
                source_build: None,
            },
        ]);
        let resolved = resolve_packages(&lock, &[]).expect("resolve closure");
        assert_eq!(
            resolved.iter().map(|p| p.name.as_str()).collect::<Vec<_>>(),
            ["c-pkg", "b-pkg", "a-pkg"]
        );
    }

    #[test]
    fn empty_reviewed_lock_is_valid_but_cannot_resolve_unknown_packages() {
        let lock = ProbeWheelLock {
            format: LOCK_FORMAT.to_string(),
            source: PYPI_SIMPLE_SOURCE.to_string(),
            roots: Vec::new(),
            packages: Vec::new(),
        };
        validate_lock(&lock).expect("empty reviewed lock");
        assert!(resolve_packages(&lock, &["not-reviewed".into()]).is_err());
        assert!(resolve_packages(&lock, &[]).is_err());
    }

    #[test]
    fn packaged_lock_must_exactly_match_the_embedded_review() {
        let source_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let lock = load_lock(&source_root).expect("load reviewed workspace lock");
        assert_eq!(lock.roots, vec!["idna"]);

        let root = std::env::temp_dir().join(format!("koi-wheel-lock-{}", unique_suffix()));
        fs::create_dir_all(&root).unwrap();
        let tampered = EMBEDDED_LOCK.replace("idna-3.10", "idna-3.11");
        fs::write(root.join(LOCK_FILE_NAME), tampered).unwrap();
        let error = load_lock(&root).expect_err("tampered public lock must fail");
        assert!(error.message.contains("does not match"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_wheels_for_other_python_or_platform_tags() {
        for filename in [
            "one-1-cp312-cp312-win_amd64.whl",
            "one-1-cp313-cp313-win_arm64.whl",
            "one-1-cp313-cp313-manylinux_x86_64.whl",
            "one-1-cp314-abi3-win_amd64.whl",
        ] {
            let lock = lock(vec![LockedWheelPackage {
                name: "one".into(),
                version: "1".into(),
                dependencies: Vec::new(),
                imports: vec!["one".into()],
                wheel: artifact(filename, b"one"),
                source_distribution: None,
                source_build: None,
            }]);
            assert!(validate_lock(&lock).is_err(), "accepted {filename}");
        }
        for filename in [
            "one-1-py2.py3-none-any.whl",
            "one-1-py3-none-win_amd64.whl",
            "one-1-cp37-abi3-win_amd64.whl",
            "one-1-cp313-cp313-win_amd64.whl",
        ] {
            let lock = lock(vec![LockedWheelPackage {
                name: "one".into(),
                version: "1".into(),
                dependencies: Vec::new(),
                imports: vec!["one".into()],
                wheel: artifact(filename, b"one"),
                source_distribution: None,
                source_build: None,
            }]);
            validate_lock(&lock).unwrap_or_else(|error| panic!("rejected {filename}: {error}"));
        }
    }

    #[test]
    fn rejects_missing_recursive_dependency_and_cycles() {
        let mut package = LockedWheelPackage {
            name: "one".into(),
            version: "1".into(),
            dependencies: vec!["missing".into()],
            imports: Vec::new(),
            wheel: artifact("one-1-py3-none-any.whl", b"one"),
            source_distribution: None,
            source_build: None,
        };
        let missing_lock = lock(vec![package.clone()]);
        assert!(validate_lock(&missing_lock).is_err());
        package.dependencies = vec!["one".into()];
        let cyclic_lock = lock(vec![package]);
        assert!(validate_lock(&cyclic_lock).is_err());
    }

    #[test]
    fn source_build_requires_second_approval_and_reviewed_backend() {
        let mut lock = lock(vec![LockedWheelPackage {
            name: "one".into(),
            version: "1".into(),
            dependencies: Vec::new(),
            imports: Vec::new(),
            wheel: artifact("one-1-py3-none-any.whl", b"one"),
            source_distribution: Some(artifact("one.tar.gz", b"source")),
            source_build: None,
        }]);
        assert!(validate_lock(&lock).is_ok());
        assert!(reject_source_distribution(&lock.packages[0], false).is_err());
        assert!(reject_source_distribution(&lock.packages[0], true).is_err());
        lock.packages[0].source_build = Some(LockedSourceBuild {
            backend: "reviewed_backend.build".into(),
            source_subdir: "one-1".into(),
            build_dependencies: Vec::new(),
        });
        assert!(validate_lock(&lock).is_ok());
        assert!(reject_source_distribution(&lock.packages[0], false).is_err());
        assert!(reject_source_distribution(&lock.packages[0], true).is_ok());
        lock.source = "https://mirror.invalid/simple".into();
        assert!(validate_lock(&lock).is_err());
    }

    #[test]
    fn offline_install_rejects_escape_and_pth_and_accepts_safe_wheel() {
        fn make_zip(path: &str, content: &[u8]) -> Vec<u8> {
            let mut bytes = Cursor::new(Vec::new());
            {
                let mut writer = zip::ZipWriter::new(&mut bytes);
                writer
                    .start_file(path, SimpleFileOptions::default())
                    .expect("start file");
                writer.write_all(content).expect("write file");
                writer.finish().expect("finish zip");
            }
            bytes.into_inner()
        }
        let root = std::env::temp_dir().join(format!("koi-wheel-test-{}", unique_suffix()));
        fs::create_dir_all(&root).expect("create root");
        let safe = make_zip("demo/__init__.py", b"x");
        let safe_path = root.join("demo-1-py3-none-any.whl");
        fs::write(&safe_path, &safe).expect("write safe wheel");
        let safe_package = ResolvedWheel {
            name: "demo".into(),
            version: "1".into(),
            artifact: artifact("demo-1-py3-none-any.whl", &safe),
            imports: vec!["demo".into()],
        };
        let report = install_offline(
            &[DownloadedWheel {
                package: safe_package,
                path: safe_path,
            }],
            &root.join("site"),
        )
        .expect("safe wheel install");
        assert_eq!(report.files, 1);
        assert!(report.site_packages.join("demo/__init__.py").is_file());

        let bad = make_zip("../escape.py", b"x");
        let bad_path = root.join("bad-1-py3-none-any.whl");
        fs::write(&bad_path, &bad).expect("write bad wheel");
        let result = install_offline(
            &[DownloadedWheel {
                package: ResolvedWheel {
                    name: "bad".into(),
                    version: "1".into(),
                    artifact: artifact("bad-1-py3-none-any.whl", &bad),
                    imports: Vec::new(),
                },
                path: bad_path,
            }],
            &root.join("bad-site"),
        );
        assert!(result.is_err());
        let pth = make_zip("bad.pth", b"import os");
        let pth_path = root.join("pth-1-py3-none-any.whl");
        fs::write(&pth_path, &pth).expect("write pth wheel");
        assert!(install_offline(
            &[DownloadedWheel {
                package: ResolvedWheel {
                    name: "pth".into(),
                    version: "1".into(),
                    artifact: artifact("pth-1-py3-none-any.whl", &pth),
                    imports: Vec::new(),
                },
                path: pth_path,
            }],
            &root.join("pth-site"),
        )
        .is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn wheel_data_installs_only_importable_lib_schemes() {
        assert_eq!(
            wheel_data_prefix("demo_pkg-1.0-py3-none-any.whl").unwrap(),
            "demo_pkg-1.0.data/"
        );
        assert_eq!(
            wheel_install_path(Path::new("demo-1.data/purelib/demo/mod.py"), "demo-1.data/")
                .unwrap(),
            PathBuf::from("demo/mod.py")
        );
        assert!(
            wheel_install_path(Path::new("demo-1.data/scripts/demo.exe"), "demo-1.data/").is_err()
        );
        assert!(
            wheel_install_path(Path::new("demo-1.data/data/config.json"), "demo-1.data/").is_err()
        );
    }

    #[test]
    fn package_and_wheel_paths_use_canonical_windows_safe_names() {
        assert_eq!(normalize_name("Demo__Pkg...Name").unwrap(), "demo-pkg-name");
        assert!(normalize_name("-bad").is_err());
        assert!(validate_import_name("valid_pkg.module").is_ok());
        assert!(validate_import_name("3invalid").is_err());
        for path in [
            "../escape.py",
            "module/./file.py",
            "module/file.py:stream",
            "module/NUL.txt",
            "module/COM1",
            "module/trailing. ",
        ] {
            assert!(
                safe_zip_path(path).is_err(),
                "accepted unsafe path {path:?}"
            );
        }
        assert_eq!(
            safe_zip_path("module/sub/file.py").unwrap(),
            PathBuf::from("module/sub/file.py")
        );
    }
}
