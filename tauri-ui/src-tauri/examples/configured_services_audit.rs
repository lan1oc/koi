use koi_tauri_lib::{BackendContext, BackendCore};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const MARKER: &str = ".koi-isolated-verification-copy";

fn main() -> ExitCode {
    let data_dir = std::env::args_os().nth(1).map(PathBuf::from);
    let result = data_dir
        .ok_or_else(|| "usage: configured_services_audit <marked-data-dir>".to_string())
        .and_then(run);
    let output = match result {
        Ok(value) => value,
        Err(reason) => json!({"ok":false,"reason_class":classify(&reason)}),
    };
    println!(
        "{}",
        serde_json::to_string(&output).unwrap_or_else(|_| "{\"ok\":false}".into())
    );
    if output["ok"] == true {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run(data_dir: PathBuf) -> Result<Value, String> {
    let data_dir =
        ordinary_windows_path(fs::canonicalize(&data_dir).map_err(|error| error.to_string())?);
    if !data_dir.join(MARKER).is_file() {
        return Err("data directory lacks isolation marker".into());
    }
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let core = BackendCore::new_strict(BackendContext::new(
        data_dir.clone(),
        data_dir.join("home"),
        project_root,
        "4.0.0",
    ))?;
    let config = core.dispatch("info.config.get", json!({}));
    if !config.ok {
        return Err("public configuration projection failed".into());
    }
    let configured = json!({
        "fofa":config.data["fofa"]["api_key_configured"],
        "hunter":config.data["hunter"]["api_key_configured"],
        "quake":config.data["quake"]["api_key_configured"],
        "threatbook":config.data["threatbook_api_key_configured"],
        "tyc":config.data["tyc"]["cookie_configured"],
        "aiqicha":config.data["aiqicha"]["cookie_configured"],
    });
    let cases = [
        (
            "fofa",
            "info.asset.fofa.query",
            json!({"query":"domain=\"example.com\"","page":1,"size":1}),
        ),
        (
            "hunter",
            "info.asset.hunter.query",
            json!({"query":"domain=\"example.com\"","page":1,"page_size":1}),
        ),
        (
            "quake",
            "info.asset.quake.query",
            json!({"query":"domain:\"example.com\"","start":0,"size":1}),
        ),
        (
            "threatbook_connection",
            "info.threatbook.test_connection",
            json!({}),
        ),
        (
            "threatbook_ip",
            "info.threatbook.ip",
            json!({"ip":"8.8.8.8"}),
        ),
        (
            "threatbook_dns",
            "info.threatbook.dns",
            json!({"domain":"example.com"}),
        ),
        (
            "tyc",
            "info.enterprise.tyc.query",
            json!({"company":"宁波银行股份有限公司"}),
        ),
        (
            "aiqicha",
            "info.enterprise.aiqicha.query",
            json!({"company":"宁波银行股份有限公司"}),
        ),
        ("model", "doc.retest.ai_config.test", json!({})),
    ];
    let mut results = serde_json::Map::new();
    for (label, command, payload) in cases {
        results.insert(
            label.to_string(),
            summarize(core.dispatch(command, payload)),
        );
    }
    let successful = results
        .values()
        .filter(|value| value["business_success"] == true)
        .count();
    Ok(json!({
        "ok":true,
        "configured":configured,
        "successful_live_calls":successful,
        "attempted_live_calls":results.len(),
        "results":results,
    }))
}

fn ordinary_windows_path(path: PathBuf) -> PathBuf {
    let raw = path.to_string_lossy();
    if let Some(rest) = raw.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = raw.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path
    }
}

fn summarize(response: koi_tauri_lib::BackendResponse) -> Value {
    let outer_ok = response.ok;
    let data = response.data;
    let business_success = data["success"].as_bool().unwrap_or(outer_ok);
    let count = ["rows", "results", "items", "companies"]
        .iter()
        .find_map(|key| data.get(*key).and_then(Value::as_array).map(Vec::len))
        .unwrap_or(0);
    let reason = response
        .error
        .or_else(|| {
            data.get("message")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .unwrap_or_default();
    json!({
        "outer_ok":outer_ok,
        "business_success":business_success,
        "result_count":count,
        "reason_class":if business_success { "" } else { classify(&reason) },
    })
}

fn classify(value: &str) -> &'static str {
    let lower = value.to_ascii_lowercase();
    if value.contains("未配置") || lower.contains("not configured") {
        "not_configured"
    } else if value.contains("登录") || value.contains("风控") || lower.contains("challenge") {
        "login_or_challenge"
    } else if lower.contains("401") || lower.contains("403") || value.contains("无效") {
        "credential_or_permission"
    } else if lower.contains("timeout") || value.contains("超时") {
        "timeout"
    } else if lower.contains("connect") || value.contains("请求异常") || value.contains("网络")
    {
        "network"
    } else if value.trim().is_empty() {
        "unspecified"
    } else {
        "provider_response"
    }
}

#[allow(dead_code)]
fn _marked(path: &Path) -> bool {
    path.join(MARKER).is_file()
}
