use koi_tauri_lib::{run_internal_worker_from_args, BackendContext, BackendCore};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const MARKER: &str = ".koi-isolated-verification-copy";

fn main() -> ExitCode {
    if let Some(code) = run_internal_worker_from_args() {
        return ExitCode::from(code as u8);
    }
    let arguments = std::env::args_os()
        .skip(1)
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    let report = if arguments.len() == 2 {
        run(&arguments[0], &arguments[1])
            .map(|result| json!({"ok": true, "result": result}))
            .unwrap_or_else(|error| json!({"ok": false, "error": error}))
    } else {
        json!({"ok": false, "error": "usage: notice_fixture_verify <isolated-target> <isolated-data-dir>"})
    };
    println!(
        "{}",
        serde_json::to_string_pretty(&report).unwrap_or_else(|_| "{\"ok\":false}".to_string())
    );
    if report["ok"] == true {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run(target: &Path, data_dir: &Path) -> Result<Value, String> {
    let target = canonical_marked_directory(target, "target")?;
    let data_dir = canonical_marked_directory(data_dir, "data directory")?;
    if target == data_dir || target.starts_with(&data_dir) || data_dir.starts_with(&target) {
        return Err("isolated target and data directory must be separate".to_string());
    }
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    seed_file(
        &project_root.join("enterprise_classification.db"),
        &data_dir.join("enterprise_classification.db"),
    )?;
    copy_tree(
        &project_root.join("Report_Template"),
        &data_dir.join("Report_Template"),
    )?;
    let context = BackendContext::new(
        data_dir.clone(),
        data_dir.join("home"),
        project_root,
        "4.0.0",
    );
    let core = BackendCore::new_strict(context)?;
    let response = core.dispatch(
        "doc.notice.process",
        json!({"target_path": target, "auto_group": true}),
    );
    if !response.ok {
        return Err(response
            .error
            .unwrap_or_else(|| "notice command failed".to_string()));
    }
    let result = response.data;
    if result["success"] != true {
        return Err(format!("notice pipeline failed: {result}"));
    }
    for stage in [
        "rewrite",
        "authorization",
        "rectification",
        "disposal",
        "pdf",
    ] {
        if result["stages"][stage] != true {
            return Err(format!("notice stage {stage} is incomplete: {result}"));
        }
    }
    if result["processed"].as_u64().unwrap_or(0) == 0 {
        return Err(format!(
            "notice pipeline incorrectly processed zero files: {result}"
        ));
    }
    Ok(result)
}

fn canonical_marked_directory(path: &Path, label: &str) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err(format!("isolated {label} must be absolute"));
    }
    let canonical = fs::canonicalize(path)
        .map_err(|error| format!("cannot resolve isolated {label}: {error}"))?;
    if !canonical.join(MARKER).is_file() {
        return Err(format!("isolated {label} is missing {MARKER}"));
    }
    let raw = canonical.to_string_lossy();
    if let Some(rest) = raw.strip_prefix(r"\\?\UNC\") {
        Ok(PathBuf::from(format!(r"\\{rest}")))
    } else if let Some(rest) = raw.strip_prefix(r"\\?\") {
        Ok(PathBuf::from(rest))
    } else {
        Ok(canonical)
    }
}

fn seed_file(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        return Ok(());
    }
    let parent = destination
        .parent()
        .ok_or_else(|| "seed has no parent".to_string())?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    fs::copy(source, destination)
        .map(|_| ())
        .map_err(|error| format!("cannot seed {}: {error}", source.display()))
}

fn copy_tree(source: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    for entry in fs::read_dir(source).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let source_path = entry.path();
        let metadata = fs::symlink_metadata(&source_path).map_err(|error| error.to_string())?;
        if metadata.file_type().is_symlink() {
            return Err(format!(
                "template tree contains a symlink: {}",
                source_path.display()
            ));
        }
        let destination_path = destination.join(entry.file_name());
        if metadata.is_dir() {
            copy_tree(&source_path, &destination_path)?;
        } else if metadata.is_file() && !destination_path.exists() {
            fs::copy(&source_path, &destination_path).map_err(|error| error.to_string())?;
        }
    }
    Ok(())
}
