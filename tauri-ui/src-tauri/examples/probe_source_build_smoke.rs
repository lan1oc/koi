#[allow(dead_code)]
#[path = "../src/backend/probe_broker.rs"]
mod probe_broker;
#[path = "../src/backend/probe_sandbox.rs"]
mod probe_sandbox;
#[path = "../src/backend/probe_source_builder.rs"]
mod probe_source_builder;
#[path = "../src/backend/probe_wheels.rs"]
mod probe_wheels;

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(".tmp-probe-source-build-interactive");
    let result = probe_source_builder::execute_approved(&root, &json!({"package":"idna"}));
    let report = match result {
        Ok(value) => json!({"ok":true,"result":value}),
        Err(error) => json!({"ok":false,"error":error}),
    };
    let _ = fs::create_dir_all(&root);
    let _ = fs::write(
        root.join("latest.json"),
        serde_json::to_vec_pretty(&report).unwrap_or_else(|_| b"{\"ok\":false}".to_vec()),
    );
    if report["ok"] == Value::Bool(true) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
