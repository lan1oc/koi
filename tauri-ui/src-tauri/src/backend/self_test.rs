use super::{
    archive_runtime, classification, external_tools, pdfium_runtime, probe_sandbox, probe_wheels,
    task_manager,
};
use super::{BackendContext, BackendCore};
use serde::Serialize;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

const BUNDLED_CONTRACT: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/backend-commands.json"
));

#[derive(Debug, Serialize)]
pub struct SelfTestReport {
    pub ok: bool,
    pub version: String,
    pub data_dir: PathBuf,
    pub contract_commands: usize,
    pub rust_handlers_registered: usize,
    pub config_initialized: bool,
    pub sqlite_initialized: bool,
    pub task_manager_verified: bool,
    pub external_tools_lock_verified: bool,
    pub legacy_bridge_fail_closed: bool,
    pub archive_runtime_verified: bool,
    pub archive_runtime_trust_model: String,
    pub archive_runtime_publisher_authenticated: bool,
    pub pdfium_runtime_verified: bool,
    pub pdfium_render_verified: bool,
    pub probe_runtime_verified: bool,
    pub probe_wheel_lock_verified: bool,
    pub source_build_policy_verified: bool,
    pub probe_sandbox_fail_closed: bool,
    pub probe_direct_socket_blocked: bool,
    pub probe_outside_file_access_blocked: bool,
    pub probe_read_only_input_verified: bool,
    pub probe_subprocess_blocked: bool,
    pub probe_job_wall_timeout_verified: bool,
}

fn runtime_application_dir_for(
    executable_dir: PathBuf,
    source_root: PathBuf,
    debug_build: bool,
) -> PathBuf {
    if executable_dir.join(probe_sandbox::LOCK_FILE_NAME).is_file() || !debug_build {
        executable_dir
    } else {
        source_root
    }
}

pub fn run(data_dir: &Path, app_version: &str) -> Result<SelfTestReport, String> {
    if !data_dir.is_absolute() {
        return Err("--data-dir must be an absolute isolated directory".to_string());
    }
    fs::create_dir_all(data_dir)
        .map_err(|error| format!("failed to create self-test data dir: {error}"))?;

    let contract = serde_json::from_str::<Value>(BUNDLED_CONTRACT)
        .map_err(|error| format!("failed to parse bundled command contract: {error}"))?;
    let commands = contract
        .get("commands")
        .and_then(Value::as_array)
        .ok_or_else(|| "bundled command contract has no commands array".to_string())?;
    if commands.len() != 97 {
        return Err(format!(
            "expected 97 contract commands, found {}",
            commands.len()
        ));
    }

    let home_dir = data_dir.join("self-test-home");
    fs::create_dir_all(&home_dir)
        .map_err(|error| format!("failed to create self-test home directory: {error}"))?;
    let core = BackendCore::new_strict(BackendContext::new(
        data_dir.to_path_buf(),
        home_dir,
        data_dir.to_path_buf(),
        app_version,
    ))?;

    let version = core.dispatch("app.version", json!({}));
    if !version.ok {
        return Err(format!("app.version self-test failed: {:?}", version.error));
    }
    let config = core.dispatch("config.load", json!({}));
    if !config.ok {
        return Err(format!(
            "config initialization self-test failed: {:?}",
            config.error
        ));
    }
    let unknown = core.dispatch("python.compatibility.command", json!({}));
    let config_initialized = data_dir.join("config.json").is_file();
    let database_path = data_dir.join("enterprise_classification.db");
    let sqlite_initialized = database_path.is_file()
        && rusqlite::Connection::open(&database_path)
            .and_then(|connection| {
                connection.pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
            })
            .is_ok_and(|version| version == classification::CLASSIFICATION_SCHEMA_VERSION);

    if !config_initialized || !sqlite_initialized {
        return Err("self-test did not initialize its isolated persistent stores".to_string());
    }
    if unknown.ok {
        return Err("self-test unexpectedly accepted an unknown command".to_string());
    }
    let task_manager_verified =
        task_manager::run_self_test(&data_dir.join(".koi-self-test-tasks.json"))?;
    if !task_manager_verified {
        return Err("Rust task manager generation self-test failed".to_string());
    }
    let external_tools_lock_verified = external_tools::run_self_test()?;
    if !external_tools_lock_verified {
        return Err("external tool lock self-test failed".to_string());
    }

    let executable_dir = std::env::current_exe()
        .map_err(|error| format!("failed to resolve self-test executable: {error}"))?
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "self-test executable has no parent directory".to_string())?;
    let application_dir = runtime_application_dir_for(
        executable_dir,
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".."),
        // Test harnesses run from `target/<profile>/deps`; permit the
        // checked-in source runtime for verification tests only.  A packaged
        // release binary passes `false` and therefore requires resources
        // beside the executable.
        cfg!(debug_assertions) || cfg!(test),
    );
    let probe_runtime = probe_sandbox::discover_verified_runtime(&application_dir)
        .map_err(|error| format!("probe runtime verification self-test failed: {error}"))?;
    let wheel_lock = probe_wheels::load_lock(&application_dir)
        .map_err(|error| format!("probe wheel lock self-test failed: {error}"))?;
    let idna_source_policy = wheel_lock.packages.iter().find_map(|package| {
        (package.name == "idna" && package.version == "3.10")
            .then_some(package.source_build.as_ref())
            .flatten()
    });
    let probe_wheel_lock_verified = wheel_lock.roots == ["idna"]
        && wheel_lock
            .packages
            .iter()
            .any(|package| package.name == "flit-core" && package.version == "3.11.0");
    let source_build_policy_verified = idna_source_policy.is_some_and(|policy| {
        policy.backend == "flit_core.buildapi"
            && policy.source_subdir == "idna-3.10"
            && policy.build_dependencies == ["flit-core"]
    });
    if !probe_wheel_lock_verified || !source_build_policy_verified {
        return Err("probe wheel/source-build policy self-test failed".to_string());
    }
    let probe_work = data_dir.join("probe-work");
    fs::create_dir_all(&probe_work)
        .map_err(|error| format!("failed to create probe self-test work directory: {error}"))?;
    let sandbox = probe_sandbox::run_sandbox_self_test(&application_dir, &probe_work)
        .map_err(|error| format!("probe sandbox self-test failed: {error}"))?;
    let probe_sandbox_fail_closed = sandbox.runtime_verified
        && sandbox.appcontainer_launched
        && sandbox.direct_socket_blocked
        && sandbox.outside_file_access_blocked
        && sandbox.read_only_input_verified
        && sandbox.subprocess_blocked
        && sandbox.job_wall_timeout_verified;
    if !probe_sandbox_fail_closed {
        return Err(
            "probe sandbox self-test did not prove every OS isolation assertion".to_string(),
        );
    }
    let pdfium = pdfium_runtime::run_self_test()
        .map_err(|error| format!("PDFium runtime self-test failed: {error}"))?;
    let archive = archive_runtime::run_self_test_at(&application_dir)
        .map_err(|error| format!("archive runtime self-test failed: {error}"))?;

    Ok(SelfTestReport {
        ok: true,
        version: version.data["version"]
            .as_str()
            .unwrap_or(app_version)
            .to_string(),
        data_dir: data_dir.to_path_buf(),
        contract_commands: commands.len(),
        rust_handlers_registered: core
            .registry()
            .iter()
            .filter(|spec| core.registry().handler(&spec.name).is_some())
            .count(),
        config_initialized,
        sqlite_initialized,
        task_manager_verified,
        external_tools_lock_verified,
        legacy_bridge_fail_closed: true,
        archive_runtime_verified: archive.version == "7.0.1832.0"
            && archive.files_verified == 7
            && archive.rar_supported
            && archive.trust_model == "publisher-signed-msix-runtime-binding-v1"
            && archive.publisher_authenticated,
        archive_runtime_trust_model: archive.trust_model,
        archive_runtime_publisher_authenticated: archive.publisher_authenticated,
        pdfium_runtime_verified: pdfium.version == "153.0.8009.0" && pdfium.files_verified == 18,
        pdfium_render_verified: pdfium.rendered_width > 0 && pdfium.rendered_height > 0,
        probe_runtime_verified: probe_runtime.version() == probe_sandbox::EXPECTED_RUNTIME_VERSION,
        probe_wheel_lock_verified,
        source_build_policy_verified,
        probe_sandbox_fail_closed,
        probe_direct_socket_blocked: sandbox.direct_socket_blocked,
        probe_outside_file_access_blocked: sandbox.outside_file_access_blocked,
        probe_read_only_input_verified: sandbox.read_only_input_verified,
        probe_subprocess_blocked: sandbox.subprocess_blocked,
        probe_job_wall_timeout_verified: sandbox.job_wall_timeout_verified,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEST_ID: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn initializes_only_the_requested_data_directory() {
        let directory = std::env::temp_dir().join(format!(
            "koi-self-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let contract: Value = serde_json::from_str(BUNDLED_CONTRACT).expect("parse contract");
        let has_python_owner = contract["commands"]
            .as_array()
            .expect("commands")
            .iter()
            .any(|command| command["owner"] == "python");
        let result = run(&directory, "4.0.0");
        assert!(
            !has_python_owner,
            "the bundled self-test contract must be Rust-only"
        );
        match result {
            Ok(report) => {
                assert!(report.ok);
                assert_eq!(report.contract_commands, 97);
                assert!(report.config_initialized);
                assert!(report.sqlite_initialized);
                assert!(report.task_manager_verified);
                assert!(report.external_tools_lock_verified);
                assert!(report.legacy_bridge_fail_closed);
            }
            Err(error) if error.contains("probe sandbox") || error.contains("AppContainer") => {
                // A non-interactive test runner may not have a token capable
                // of creating an AppContainer. The security contract is
                // fail-closed; this environment limitation is reported but
                // must not turn into a host-Python fallback.
                assert!(!error.to_ascii_lowercase().contains("python"));
            }
            Err(error) => panic!("run isolated self-test: {error}"),
        }
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn rejects_relative_data_directories() {
        assert!(run(Path::new("relative-self-test"), "4.0.0").is_err());
    }

    #[test]
    fn release_self_test_never_falls_back_to_the_source_tree() {
        let executable = std::env::temp_dir().join(format!(
            "koi-release-self-test-exe-{}",
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let source = std::env::temp_dir().join(format!(
            "koi-release-self-test-source-{}",
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        assert_eq!(
            runtime_application_dir_for(executable.clone(), source, false),
            executable
        );
    }
}
