use koi_tauri_lib::{run_internal_worker_from_args, BackendContext, BackendCore};
use serde_json::{json, Value};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use zip::write::SimpleFileOptions;

const MARKER: &str = ".koi-isolated-verification-copy";

fn main() -> ExitCode {
    if let Some(code) = run_internal_worker_from_args() {
        return ExitCode::from(code as u8);
    }
    let args = std::env::args_os()
        .skip(1)
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    let result = match args.as_slice() {
        [target, data, source] => run(target, data, source),
        [target, data, source, mode] if mode == "--loopback" => run_loopback(target, data, source),
        _ => Err("usage: retest_live_audit <marked-target> <marked-data-dir> <copied-source> [--loopback]".into()),
    };
    let summary = match result {
        Ok(result) => result,
        Err(reason) => json!({"ok":false,"reason":reason}),
    };
    println!(
        "{}",
        serde_json::to_string(&summary).unwrap_or_else(|_| "{\"ok\":false}".into())
    );
    if summary["ok"] == true {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run_loopback(target: &Path, data: &Path, source: &Path) -> Result<Value, String> {
    let target = marked_directory(target)?;
    let source = if source.is_absolute() {
        source.to_path_buf()
    } else {
        target.join(source)
    };
    if !source.starts_with(&target) || source.exists() {
        return Err("loopback fixture must be a new file inside the isolated target".into());
    }
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("bind loopback fixture: {error}"))?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let stop = Arc::new(AtomicBool::new(false));
    let requests = Arc::new(AtomicUsize::new(0));
    listener
        .set_nonblocking(true)
        .map_err(|error| error.to_string())?;
    let server_stop = Arc::clone(&stop);
    let server_requests = Arc::clone(&requests);
    let server = thread::spawn(move || {
        while !server_stop.load(Ordering::Relaxed) {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
                    let mut request = [0u8; 4096];
                    let _ = stream.read(&mut request);
                    server_requests.fetch_add(1, Ordering::Relaxed);
                    let body = b"Access denied. Authentication required.";
                    let response = format!(
                        "HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    );
                    let _ = stream.write_all(response.as_bytes());
                    let _ = stream.write_all(body);
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(_) => break,
            }
        }
    });
    let result = write_loopback_notice(
        &source,
        &format!("http://127.0.0.1:{}/admin", address.port()),
    )
    .and_then(|()| run(&target, data, &source));
    stop.store(true, Ordering::Relaxed);
    let _ = server.join();
    result.map(|mut summary| {
        summary["loopback_http_requests"] = json!(requests.load(Ordering::Relaxed));
        summary
    })
}

fn write_loopback_notice(path: &Path, url: &str) -> Result<(), String> {
    let file =
        fs::File::create(path).map_err(|error| format!("create loopback notice: {error}"))?;
    let mut archive = zip::ZipWriter::new(file);
    archive
        .start_file("word/document.xml", SimpleFileOptions::default())
        .map_err(|error| error.to_string())?;
    let text = format!(
        "<?xml version=\"1.0\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>隔离测试通报：未授权访问。</w:t></w:r></w:p><w:p><w:r><w:t>通报目标 {url}；原风险是无登录访问管理页。请复测此 URL 的当前访问控制。</w:t></w:r></w:p></w:body></w:document>"
    );
    archive
        .write_all(text.as_bytes())
        .map_err(|error| error.to_string())?;
    archive.finish().map_err(|error| error.to_string())?;
    Ok(())
}

fn marked_directory(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err("audit directories must be absolute".into());
    }
    let canonical = fs::canonicalize(path).map_err(|error| format!("audit directory: {error}"))?;
    if !canonical.join(MARKER).is_file() {
        return Err("audit directory lacks its isolation marker".into());
    }
    Ok(ordinary_windows_path(canonical))
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

fn run(target: &Path, data: &Path, source: &Path) -> Result<Value, String> {
    let target = marked_directory(target)?;
    let data = marked_directory(data)?;
    if target.starts_with(&data) || data.starts_with(&target) {
        return Err("target and data directories must be separate".into());
    }
    let source = ordinary_windows_path(
        fs::canonicalize(source).map_err(|error| format!("audit source: {error}"))?,
    );
    if !source.starts_with(&target) || !source.is_file() {
        return Err("audit source must be a copied file inside the target".into());
    }
    let original_hash = hash_file(&source)?;
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let core = BackendCore::new_strict(BackendContext::new(
        data.clone(),
        data.join("home"),
        project_root,
        "4.0.0",
    ))?;
    let session_id = format!("live-audit-{}", std::process::id());
    let response = core.dispatch(
        "doc.retest.agent.message",
        json!({
            "session_id": session_id,
            "target_dir": target,
            "message": "请从当前唯一待处理通报开始实际复测并生成报告。只使用 allowed_operations 中的 retest_source_file，arguments.source_file 必须等于 resume_plan.next_source_file；不要仅回复计划。",
            "auto_approve": true,
            "force_resume": true,
            "generate_reports": true,
            "frontend_context": {"session":{"targetDir":target,"generateReports":true}},
        }),
    );
    if !response.ok {
        return Err("real model command failed before an Agent response".into());
    }
    let message = response.data;
    let model_connected = message["provider"].is_string() && message["model"].is_string();
    let operation_id = message["operation_id"].as_str().unwrap_or_default();
    if !model_connected || operation_id.is_empty() {
        return Ok(json!({
            "ok":false,"model_connected":model_connected,"tool_proposed":false,
            "blocked_stage":message["blocked_stage"],
            "reason":"real model did not propose an executable retest operation",
        }));
    }

    let deadline = Instant::now() + Duration::from_secs(12 * 60);
    loop {
        let status = core.dispatch(
            "doc.agent.operation.status",
            json!({"session_id":session_id,"operation_id":operation_id}),
        );
        if !status.ok {
            return Err("operation status command failed".into());
        }
        let operation = &status.data["operation"];
        let state = operation["status"].as_str().unwrap_or_default();
        if matches!(
            state,
            "completed" | "failed" | "cancelled" | "rejected" | "stale"
        ) {
            let reports = fs::read_dir(source.parent().unwrap_or(&target))
                .map_err(|error| format!("audit report scan: {error}"))?
                .filter_map(Result::ok)
                .filter(|entry| {
                    (entry
                        .file_name()
                        .to_string_lossy()
                        .ends_with("_复测报告.docx")
                        || entry
                            .file_name()
                            .to_string_lossy()
                            .ends_with("_复测待核验报告.docx"))
                        && entry.metadata().is_ok_and(|metadata| metadata.len() > 512)
                })
                .collect::<Vec<_>>();
            let report_count = reports.len();
            let pending_reports = reports
                .iter()
                .filter(|entry| {
                    entry
                        .file_name()
                        .to_string_lossy()
                        .ends_with("_复测待核验报告.docx")
                })
                .count();
            let source_preserved = hash_file(&source)? == original_hash;
            let detail = operation["detail"].as_str().unwrap_or_default();
            let verdict = serde_json::from_str::<Value>(detail)
                .ok()
                .and_then(|value| {
                    value["result_data"]["final_verdict"]
                        .as_str()
                        .map(str::to_string)
                });
            let executable = state == "completed"
                && report_count > 0
                && source_preserved
                && verdict.as_deref().is_some_and(|value| {
                    matches!(value, "reproduced" | "not_reproduced" | "inconclusive")
                });
            let verified =
                executable && pending_reports == 0 && verdict.as_deref() != Some("inconclusive");
            return Ok(json!({
                "ok":executable,"verified":verified,"model_connected":model_connected,
                "tool_proposed":true,"tool_name":operation["tool_name"],
                "operation_status":state,"verdict":verdict,
                "report_count":report_count,"pending_report_count":pending_reports,
                "source_preserved":source_preserved,
                "error_class":if state == "failed" {
                    operation["error"].as_str().unwrap_or_default()
                        .split(':').next().unwrap_or("operation_failed")
                } else { "" },
            }));
        }
        if Instant::now() >= deadline {
            let _ = core.dispatch(
                "doc.agent.operation.stop",
                json!({
                    "session_id":session_id,"operation_id":operation_id,
                }),
            );
            return Err("live retest timed out and was stopped".into());
        }
        thread::sleep(Duration::from_millis(500));
    }
}

fn hash_file(path: &Path) -> Result<Vec<u8>, String> {
    use sha2::{Digest, Sha256};
    let bytes = fs::read(path).map_err(|error| format!("audit source read: {error}"))?;
    Ok(Sha256::digest(bytes).to_vec())
}
