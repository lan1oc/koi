use koi_tauri_lib::{run_internal_worker_from_args, BackendContext, BackendCore};
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DriverRequest {
    command: String,
    #[serde(default)]
    payload: Value,
}

fn main() -> ExitCode {
    if let Some(code) = run_internal_worker_from_args() {
        return ExitCode::from(code as u8);
    }
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("backend protocol driver failed: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let data_dir = parse_data_dir()?;
    prepare_isolated_data(&data_dir)?;
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let context = BackendContext::new(
        data_dir.clone(),
        data_dir.join("home"),
        project_root,
        "4.0.0",
    );
    let core = BackendCore::new_strict(context)?;
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    for line in stdin.lock().lines() {
        let line = line.map_err(|error| format!("read request: {error}"))?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<DriverRequest>(&line) {
            Ok(request) => core.dispatch(request.command.trim(), request.payload),
            Err(error) => koi_tauri_lib::BackendResponse {
                ok: false,
                data: Value::Null,
                error: Some(format!("invalid driver request: {error}")),
            },
        };
        serde_json::to_writer(&mut stdout, &response)
            .map_err(|error| format!("serialize response: {error}"))?;
        stdout
            .write_all(b"\n")
            .and_then(|_| stdout.flush())
            .map_err(|error| format!("write response: {error}"))?;
    }
    Ok(())
}

fn parse_data_dir() -> Result<PathBuf, String> {
    let mut arguments = std::env::args_os().skip(1);
    let mut data_dir = None;
    while let Some(argument) = arguments.next() {
        if argument == "--data-dir" {
            if data_dir.is_some() {
                return Err("--data-dir may only be specified once".to_string());
            }
            data_dir = arguments.next().map(PathBuf::from);
        } else {
            return Err(format!(
                "unsupported argument: {}",
                argument.to_string_lossy()
            ));
        }
    }
    let data_dir = data_dir.ok_or_else(|| "--data-dir is required".to_string())?;
    if !data_dir.is_absolute() {
        return Err("--data-dir must be absolute".to_string());
    }
    Ok(data_dir)
}

fn prepare_isolated_data(data_dir: &Path) -> Result<(), String> {
    fs::create_dir_all(data_dir).map_err(|error| format!("create data directory: {error}"))?;
    let metadata = fs::symlink_metadata(data_dir)
        .map_err(|error| format!("inspect data directory: {error}"))?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err("--data-dir must be a real directory".to_string());
    }
    fs::create_dir_all(data_dir.join("home"))
        .map_err(|error| format!("create isolated home: {error}"))?;
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    seed_file(
        &project_root.join("enterprise_classification.db"),
        &data_dir.join("enterprise_classification.db"),
    )?;
    copy_missing_tree(
        &project_root.join("Report_Template"),
        &data_dir.join("Report_Template"),
    )?;
    copy_missing_tree(
        &project_root.join("modules/data_processing/templates"),
        &data_dir.join("templates"),
    )
}

fn seed_file(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        return Ok(());
    }
    fs::copy(source, destination)
        .map(|_| ())
        .map_err(|error| format!("seed {}: {error}", source.display()))
}

fn copy_missing_tree(source: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| format!("create seed directory: {error}"))?;
    for entry in fs::read_dir(source).map_err(|error| format!("read seed tree: {error}"))? {
        let entry = entry.map_err(|error| format!("read seed entry: {error}"))?;
        let source_path = entry.path();
        let metadata = fs::symlink_metadata(&source_path)
            .map_err(|error| format!("inspect seed entry: {error}"))?;
        if metadata.file_type().is_symlink() {
            return Err(format!(
                "seed tree contains a symlink: {}",
                source_path.display()
            ));
        }
        let destination_path = destination.join(entry.file_name());
        if metadata.is_dir() {
            copy_missing_tree(&source_path, &destination_path)?;
        } else if metadata.is_file() && !destination_path.exists() {
            fs::copy(&source_path, &destination_path)
                .map_err(|error| format!("copy seed {}: {error}", source_path.display()))?;
        }
    }
    Ok(())
}

#[allow(dead_code)]
fn error_response(message: &str) -> Value {
    json!({"ok": false, "data": null, "error": message})
}
