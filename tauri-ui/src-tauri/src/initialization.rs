use crate::app_paths::{resolve_app_paths, AppPaths, PathResolutionOptions};
use serde::Serialize;
use serde_json::Value;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub const INITIALIZATION_PROGRESS_EVENT: &str = "koi-initialization-progress";
const INITIALIZATION_STEPS: u8 = 5;
const SQLITE_HEADER: &[u8; 16] = b"SQLite format 3\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InitializationStage {
    Paths,
    Config,
    Database,
    Resources,
    Runtime,
    Ready,
}

impl InitializationStage {
    const fn label(self) -> &'static str {
        match self {
            Self::Paths => "paths",
            Self::Config => "config",
            Self::Database => "database",
            Self::Resources => "resources",
            Self::Runtime => "runtime",
            Self::Ready => "ready",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InitializationStatus {
    Starting,
    Completed,
    Error,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InitializationProgress {
    pub stage: InitializationStage,
    pub status: InitializationStatus,
    pub completed_steps: u8,
    pub total_steps: u8,
    pub percent: u8,
    pub message: String,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfigInitialization {
    pub path: PathBuf,
    pub byte_len: u64,
    pub valid_json_object: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DatabaseInitialization {
    pub path: PathBuf,
    pub byte_len: u64,
    pub valid_sqlite_header: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourceStatus {
    pub name: String,
    pub path: PathBuf,
    pub required: bool,
    pub available: bool,
    pub entry_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourcesInitialization {
    pub items: Vec<ResourceStatus>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeInitialization {
    pub directory: PathBuf,
    pub writable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InitializationReport {
    pub ready: bool,
    pub paths: AppPaths,
    pub config: ConfigInitialization,
    pub database: DatabaseInitialization,
    pub resources: ResourcesInitialization,
    pub runtime: RuntimeInitialization,
    pub elapsed_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct InitializationResponse {
    pub ok: bool,
    pub data: Value,
    pub error: Option<String>,
}

impl From<Result<InitializationReport, InitializationFailure>> for InitializationResponse {
    fn from(result: Result<InitializationReport, InitializationFailure>) -> Self {
        match result {
            Ok(report) => Self::ready(report),
            Err(error) => Self::failed(error.to_string()),
        }
    }
}

impl InitializationResponse {
    fn ready(report: InitializationReport) -> Self {
        match serde_json::to_value(report) {
            Ok(data) => Self {
                ok: true,
                data,
                error: None,
            },
            Err(error) => Self::failed(format!(
                "ready initialization failed: unable to serialize result: {error}"
            )),
        }
    }

    pub fn failed(error: impl Into<String>) -> Self {
        Self {
            ok: false,
            data: Value::Null,
            error: Some(error.into()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InitializationFailure {
    pub stage: InitializationStage,
    pub message: String,
}

impl InitializationFailure {
    fn new(stage: InitializationStage, message: impl Into<String>) -> Self {
        Self {
            stage,
            message: message.into(),
        }
    }
}

impl fmt::Display for InitializationFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} initialization failed: {}",
            self.stage.label(),
            self.message
        )
    }
}

impl std::error::Error for InitializationFailure {}

#[allow(dead_code)]
pub fn initialize(paths: &AppPaths) -> InitializationResponse {
    initialize_with_progress(paths, |_| {})
}

#[allow(dead_code)]
pub fn initialize_with_progress<F>(paths: &AppPaths, mut emit_progress: F) -> InitializationResponse
where
    F: FnMut(InitializationProgress),
{
    emit_stage(
        &mut emit_progress,
        InitializationStage::Paths,
        InitializationStatus::Starting,
        0,
        None,
    );
    emit_stage(
        &mut emit_progress,
        InitializationStage::Paths,
        InitializationStatus::Completed,
        1,
        None,
    );
    initialize_resolved(paths.clone(), &mut emit_progress)
}

pub fn initialize_from_options_with_progress<F>(
    options: &PathResolutionOptions,
    mut emit_progress: F,
) -> InitializationResponse
where
    F: FnMut(InitializationProgress),
{
    emit_stage(
        &mut emit_progress,
        InitializationStage::Paths,
        InitializationStatus::Starting,
        0,
        None,
    );
    let paths = match resolve_app_paths(options) {
        Ok(paths) => paths,
        Err(error) => {
            emit_stage(
                &mut emit_progress,
                InitializationStage::Paths,
                InitializationStatus::Error,
                0,
                Some(error.to_string()),
            );
            return InitializationResponse::failed(format!(
                "paths initialization failed [{}]: {error}",
                error.code()
            ));
        }
    };
    emit_stage(
        &mut emit_progress,
        InitializationStage::Paths,
        InitializationStatus::Completed,
        1,
        None,
    );
    initialize_resolved(paths, &mut emit_progress)
}

fn initialize_resolved<F>(paths: AppPaths, emit_progress: &mut F) -> InitializationResponse
where
    F: FnMut(InitializationProgress),
{
    let started = Instant::now();

    let config = match run_stage(emit_progress, InitializationStage::Config, 1, || {
        initialize_config(&paths.config_path)
    }) {
        Ok(status) => status,
        Err(error) => return InitializationResponse::failed(error.to_string()),
    };

    let database = match run_stage(emit_progress, InitializationStage::Database, 2, || {
        initialize_database(&paths)
    }) {
        Ok(status) => status,
        Err(error) => return InitializationResponse::failed(error.to_string()),
    };

    let resources = match run_stage(emit_progress, InitializationStage::Resources, 3, || {
        initialize_resources(&paths)
    }) {
        Ok(status) => status,
        Err(error) => return InitializationResponse::failed(error.to_string()),
    };

    let runtime = match run_stage(emit_progress, InitializationStage::Runtime, 4, || {
        initialize_runtime(&paths.runtime_dir)
    }) {
        Ok(status) => status,
        Err(error) => return InitializationResponse::failed(error.to_string()),
    };

    let elapsed_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    let report = InitializationReport {
        ready: true,
        paths,
        config,
        database,
        resources,
        runtime,
        elapsed_ms,
    };
    emit_stage(
        emit_progress,
        InitializationStage::Ready,
        InitializationStatus::Completed,
        INITIALIZATION_STEPS,
        None,
    );
    InitializationResponse::ready(report)
}

fn run_stage<T, F, O>(
    emit_progress: &mut F,
    stage: InitializationStage,
    already_completed: u8,
    operation: O,
) -> Result<T, InitializationFailure>
where
    F: FnMut(InitializationProgress),
    O: FnOnce() -> Result<T, String>,
{
    emit_stage(
        emit_progress,
        stage,
        InitializationStatus::Starting,
        already_completed,
        None,
    );
    match operation() {
        Ok(value) => {
            emit_stage(
                emit_progress,
                stage,
                InitializationStatus::Completed,
                already_completed.saturating_add(1),
                None,
            );
            Ok(value)
        }
        Err(message) => {
            emit_stage(
                emit_progress,
                stage,
                InitializationStatus::Error,
                already_completed,
                Some(message.clone()),
            );
            Err(InitializationFailure::new(stage, message))
        }
    }
}

fn emit_stage<F>(
    emit_progress: &mut F,
    stage: InitializationStage,
    status: InitializationStatus,
    completed_steps: u8,
    error: Option<String>,
) where
    F: FnMut(InitializationProgress),
{
    let bounded_completed = completed_steps.min(INITIALIZATION_STEPS);
    let percent = (u16::from(bounded_completed) * 100 / u16::from(INITIALIZATION_STEPS)) as u8;
    let message = match status {
        InitializationStatus::Starting => format!("Initializing {}", stage.label()),
        InitializationStatus::Completed => format!("Initialized {}", stage.label()),
        InitializationStatus::Error => format!("Failed to initialize {}", stage.label()),
    };
    emit_progress(InitializationProgress {
        stage,
        status,
        completed_steps: bounded_completed,
        total_steps: INITIALIZATION_STEPS,
        percent,
        message,
        error,
    });
}

fn initialize_config(path: &Path) -> Result<ConfigInitialization, String> {
    if !path.exists() {
        atomic_create_missing(path, b"{}\n")?;
    }
    let bytes = fs::read(path)
        .map_err(|error| format!("unable to read config {}: {error}", path.display()))?;
    let json_bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&bytes);
    let value: Value = serde_json::from_slice(json_bytes)
        .map_err(|error| format!("config is not valid JSON at {}: {error}", path.display()))?;
    if !value.is_object() {
        return Err(format!(
            "config root must be a JSON object: {}",
            path.display()
        ));
    }
    Ok(ConfigInitialization {
        path: path.to_path_buf(),
        byte_len: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        valid_json_object: true,
    })
}

fn initialize_database(paths: &AppPaths) -> Result<DatabaseInitialization, String> {
    let path = &paths.database_path;
    if !path.exists() {
        let seed = paths.app_dir.join("seed/enterprise_classification.db");
        if seed.is_file() {
            copy_file_if_missing(&seed, path)?;
        } else {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).map_err(|error| {
                    format!(
                        "unable to create database directory {}: {error}",
                        parent.display()
                    )
                })?;
            }
            rusqlite::Connection::open(path).map_err(|error| {
                format!(
                    "unable to create SQLite database {}: {error}",
                    path.display()
                )
            })?;
        }
    }
    let metadata = fs::metadata(path)
        .map_err(|error| format!("unable to inspect database {}: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!("database is not a file: {}", path.display()));
    }
    let mut file = File::open(path)
        .map_err(|error| format!("unable to open database {}: {error}", path.display()))?;
    let mut header = [0_u8; SQLITE_HEADER.len()];
    file.read_exact(&mut header)
        .map_err(|error| format!("unable to read SQLite header {}: {error}", path.display()))?;
    if &header != SQLITE_HEADER {
        return Err(format!(
            "database does not have a valid SQLite header: {}",
            path.display()
        ));
    }
    Ok(DatabaseInitialization {
        path: path.to_path_buf(),
        byte_len: metadata.len(),
        valid_sqlite_header: true,
    })
}

fn initialize_resources(paths: &AppPaths) -> Result<ResourcesInitialization, String> {
    seed_directory_missing(
        &paths.app_dir.join("seed/Report_Template"),
        &paths.report_templates_dir,
    )?;
    seed_directory_missing(
        &paths.app_dir.join("seed/templates"),
        &paths.data_templates_dir,
    )?;
    let specifications = [
        (
            "report_templates",
            paths.report_templates_dir.as_path(),
            true,
        ),
        ("data_templates", paths.data_templates_dir.as_path(), true),
        ("external_tools", paths.external_tools_dir.as_path(), false),
    ];
    let mut items = Vec::with_capacity(specifications.len());
    for (name, path, required) in specifications {
        let available = path.is_dir();
        if required && !available {
            return Err(format!(
                "required resource directory is unavailable: {}",
                path.display()
            ));
        }
        let entry_count = if available {
            let count = fs::read_dir(path)
                .map_err(|error| {
                    format!(
                        "unable to read resource directory {}: {error}",
                        path.display()
                    )
                })?
                .count();
            u64::try_from(count).unwrap_or(u64::MAX)
        } else {
            0
        };
        items.push(ResourceStatus {
            name: name.to_string(),
            path: path.to_path_buf(),
            required,
            available,
            entry_count,
        });
    }
    Ok(ResourcesInitialization { items })
}

fn atomic_create_missing(destination: &Path, bytes: &[u8]) -> Result<(), String> {
    if destination.exists() {
        return Ok(());
    }
    let parent = destination
        .parent()
        .ok_or_else(|| format!("destination has no parent: {}", destination.display()))?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "unable to create seed directory {}: {error}",
            parent.display()
        )
    })?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock error: {error}"))?
        .as_nanos();
    let temporary = parent.join(format!(
        ".{}.koi-seed-{}-{nonce}",
        destination
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("resource"),
        std::process::id()
    ));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| {
                format!(
                    "unable to create seed temp file {}: {error}",
                    temporary.display()
                )
            })?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|error| {
                format!(
                    "unable to sync seed temp file {}: {error}",
                    temporary.display()
                )
            })?;
        if destination.exists() {
            return Ok(());
        }
        fs::rename(&temporary, destination).map_err(|error| {
            format!(
                "unable to atomically install seed {} -> {}: {error}",
                temporary.display(),
                destination.display()
            )
        })?;
        Ok(())
    })();
    if temporary.exists() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn copy_file_if_missing(source: &Path, destination: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("unable to inspect seed file {}: {error}", source.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!(
            "seed source is not a regular file: {}",
            source.display()
        ));
    }
    let bytes = fs::read(source)
        .map_err(|error| format!("unable to read seed file {}: {error}", source.display()))?;
    atomic_create_missing(destination, &bytes)
}

fn seed_directory_missing(source: &Path, destination: &Path) -> Result<(), String> {
    if !source.exists() {
        return if destination.is_dir() {
            Ok(())
        } else {
            Err(format!(
                "required seed directory is unavailable: {}",
                source.display()
            ))
        };
    }
    let source_metadata = fs::symlink_metadata(source).map_err(|error| {
        format!(
            "unable to inspect seed directory {}: {error}",
            source.display()
        )
    })?;
    if source_metadata.file_type().is_symlink() || !source_metadata.is_dir() {
        return Err(format!(
            "seed source is not a regular directory: {}",
            source.display()
        ));
    }
    fs::create_dir_all(destination).map_err(|error| {
        format!(
            "unable to create resource directory {}: {error}",
            destination.display()
        )
    })?;
    for entry in fs::read_dir(source).map_err(|error| {
        format!(
            "unable to read seed directory {}: {error}",
            source.display()
        )
    })? {
        let entry = entry.map_err(|error| format!("unable to read seed entry: {error}"))?;
        let metadata = entry.metadata().map_err(|error| {
            format!(
                "unable to inspect seed entry {}: {error}",
                entry.path().display()
            )
        })?;
        if entry
            .file_type()
            .map(|kind| kind.is_symlink())
            .unwrap_or(true)
        {
            return Err(format!(
                "seed tree contains a symbolic link: {}",
                entry.path().display()
            ));
        }
        let target = destination.join(entry.file_name());
        if metadata.is_dir() {
            seed_directory_missing(&entry.path(), &target)?;
        } else if metadata.is_file() {
            copy_file_if_missing(&entry.path(), &target)?;
        } else {
            return Err(format!(
                "seed tree contains an unsupported entry: {}",
                entry.path().display()
            ));
        }
    }
    Ok(())
}

fn initialize_runtime(path: &Path) -> Result<RuntimeInitialization, String> {
    fs::create_dir_all(path).map_err(|error| {
        format!(
            "unable to create runtime directory {}: {error}",
            path.display()
        )
    })?;
    if !path.is_dir() {
        return Err(format!(
            "runtime path is not a directory: {}",
            path.display()
        ));
    }

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock error: {error}"))?
        .as_nanos();
    let probe_path = path.join(format!(".write-probe-{}-{nonce}", std::process::id()));
    let mut probe = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&probe_path)
        .map_err(|error| {
            format!(
                "runtime directory is not writable {}: {error}",
                path.display()
            )
        })?;
    probe
        .write_all(b"koi-runtime-probe")
        .and_then(|_| probe.sync_all())
        .map_err(|error| format!("runtime write probe failed {}: {error}", path.display()))?;
    drop(probe);
    fs::remove_file(&probe_path).map_err(|error| {
        format!(
            "unable to remove runtime write probe {}: {error}",
            probe_path.display()
        )
    })?;

    Ok(RuntimeInitialization {
        directory: path.to_path_buf(),
        writable: true,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app_paths::{BuildProfile, PathResolutionOptions};
    use std::env;

    struct Fixture {
        root: PathBuf,
        paths: AppPaths,
    }

    impl Fixture {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock is after unix epoch")
                .as_nanos();
            let root = env::temp_dir().join(format!(
                "koi-initialization-test-{}-{nonce}",
                std::process::id()
            ));
            let workspace = root.join("workspace");
            let app_dir = workspace.join("app");
            let data_dir = root.join("test-data");
            fs::create_dir_all(&app_dir).expect("create app directory");
            fs::create_dir_all(data_dir.join("Report_Template"))
                .expect("create report template directory");
            fs::create_dir_all(data_dir.join("templates")).expect("create data template directory");
            fs::write(
                data_dir.join("config.json"),
                br#"{"api_key":"secret-value","ui_settings":{}}"#,
            )
            .expect("write config");
            let mut database = SQLITE_HEADER.to_vec();
            database.resize(100, 0);
            fs::write(data_dir.join("enterprise_classification.db"), database)
                .expect("write database");
            fs::write(data_dir.join("Report_Template/template.docx"), b"test")
                .expect("write report template");
            fs::write(data_dir.join("templates/templates.json"), b"{}")
                .expect("write data template");

            let options = PathResolutionOptions {
                app_dir,
                workspace_root: Some(workspace.clone()),
                configured_user_data_dir: Some(data_dir.into_os_string()),
                local_app_data_dir: Some(root.join("local-app-data")),
                test_mode: true,
                build_profile: BuildProfile::Debug,
                temp_root: env::temp_dir(),
                current_dir: workspace,
            };
            let paths = resolve_app_paths(&options).expect("fixture paths resolve");
            Self { root, paths }
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    #[test]
    fn initialization_emits_real_monotonic_progress_and_ready_response() {
        let fixture = Fixture::new();
        let mut events = Vec::new();
        let response = initialize_with_progress(&fixture.paths, |event| events.push(event));

        assert!(response.ok, "{:?}", response.error);
        assert!(response.error.is_none());
        assert_eq!(response.data.get("ready"), Some(&Value::Bool(true)));
        assert_eq!(
            events.first().map(|event| event.stage),
            Some(InitializationStage::Paths)
        );
        assert_eq!(
            events.last().map(|event| event.stage),
            Some(InitializationStage::Ready)
        );
        assert_eq!(events.last().map(|event| event.percent), Some(100));
        assert!(events
            .windows(2)
            .all(|pair| pair[0].percent <= pair[1].percent));
        assert!(fixture.paths.runtime_dir.is_dir());
        assert_eq!(
            fs::read_dir(&fixture.paths.runtime_dir)
                .expect("read runtime directory")
                .count(),
            0
        );

        let serialized = serde_json::to_string(&response).expect("serialize response");
        assert!(!serialized.contains("secret-value"));
    }

    #[test]
    fn invalid_config_returns_protocol_error_and_error_progress() {
        let fixture = Fixture::new();
        fs::write(&fixture.paths.config_path, b"not-json").expect("replace config");
        let mut events = Vec::new();

        let response = initialize_with_progress(&fixture.paths, |event| events.push(event));

        assert!(!response.ok);
        assert_eq!(response.data, Value::Null);
        assert!(response
            .error
            .as_deref()
            .is_some_and(|error| error.starts_with("config initialization failed:")));
        let last = events.last().expect("error progress event");
        assert_eq!(last.stage, InitializationStage::Config);
        assert_eq!(last.status, InitializationStatus::Error);
        assert!(last.error.is_some());
    }

    #[test]
    fn path_rejection_uses_the_same_response_protocol() {
        let fixture = Fixture::new();
        let options = PathResolutionOptions {
            app_dir: fixture.paths.app_dir.clone(),
            workspace_root: Some(fixture.root.join("workspace")),
            configured_user_data_dir: None,
            local_app_data_dir: Some(fixture.root.join("local-app-data")),
            test_mode: true,
            build_profile: BuildProfile::Debug,
            temp_root: env::temp_dir(),
            current_dir: fixture.root.clone(),
        };
        let mut events = Vec::new();

        let response = initialize_from_options_with_progress(&options, |event| events.push(event));

        let encoded = serde_json::to_value(&response).expect("serialize protocol response");
        let keys = encoded
            .as_object()
            .expect("response is an object")
            .keys()
            .cloned()
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(
            keys,
            ["data", "error", "ok"]
                .into_iter()
                .map(str::to_string)
                .collect()
        );
        assert!(!response.ok);
        assert_eq!(response.data, Value::Null);
        assert!(response
            .error
            .as_deref()
            .is_some_and(|error| error.contains("test_user_data_dir_required")));
        assert_eq!(
            events.last().map(|event| event.stage),
            Some(InitializationStage::Paths)
        );
        assert_eq!(
            events.last().map(|event| event.status),
            Some(InitializationStatus::Error)
        );
    }

    #[test]
    fn missing_required_resources_stops_before_runtime_writes() {
        let fixture = Fixture::new();
        fs::remove_dir_all(&fixture.paths.report_templates_dir)
            .expect("remove required resource directory");

        let response = initialize(&fixture.paths);

        assert!(!response.ok);
        assert!(response
            .error
            .as_deref()
            .is_some_and(|error| error.starts_with("resources initialization failed:")));
        assert!(!fixture.paths.runtime_dir.exists());
    }

    #[test]
    fn first_start_seeds_only_missing_data_and_preserves_existing_files() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after unix epoch")
            .as_nanos();
        let root = env::temp_dir().join(format!("koi-seed-test-{}-{nonce}", std::process::id()));
        let app_dir = root.join("installed-app");
        let data_dir = root.join("user-data");
        fs::create_dir_all(app_dir.join("seed/Report_Template"))
            .expect("create report seed directory");
        fs::create_dir_all(app_dir.join("seed/templates")).expect("create data seed directory");
        fs::create_dir_all(&data_dir).expect("create user data directory");
        fs::write(
            app_dir.join("seed/Report_Template/default.docx"),
            b"seed-report",
        )
        .expect("write report seed");
        fs::write(
            app_dir.join("seed/templates/templates.json"),
            b"seed-template",
        )
        .expect("write data seed");
        let seed_database = app_dir.join("seed/enterprise_classification.db");
        rusqlite::Connection::open(&seed_database)
            .expect("create seed database")
            .execute_batch("CREATE TABLE seed(value TEXT);")
            .expect("initialize seed database");
        fs::create_dir_all(data_dir.join("Report_Template"))
            .expect("create existing report directory");
        fs::write(
            data_dir.join("Report_Template/default.docx"),
            b"user-report",
        )
        .expect("write existing user report");

        let options = PathResolutionOptions {
            app_dir,
            workspace_root: None,
            configured_user_data_dir: Some(data_dir.clone().into_os_string()),
            local_app_data_dir: Some(root.join("local-app-data")),
            test_mode: true,
            build_profile: BuildProfile::Release,
            temp_root: env::temp_dir(),
            current_dir: root.clone(),
        };
        let paths = resolve_app_paths(&options).expect("seed test paths resolve");
        let response = initialize(&paths);

        assert!(response.ok, "{:?}", response.error);
        assert_eq!(fs::read(&paths.config_path).unwrap(), b"{}\n");
        assert_eq!(
            fs::read(paths.report_templates_dir.join("default.docx")).unwrap(),
            b"user-report"
        );
        assert_eq!(
            fs::read(paths.data_templates_dir.join("templates.json")).unwrap(),
            b"seed-template"
        );
        assert!(paths.database_path.is_file());
        let _ = fs::remove_dir_all(root);
    }
}
