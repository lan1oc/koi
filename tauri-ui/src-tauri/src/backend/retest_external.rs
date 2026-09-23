//! Bounded native wrappers for the optional retest tools.
//!
//! Nmap and ffuf are executed only from the hash-locked managed product
//! directories. The historical sqlmap check id is implemented by a small
//! Rust HTTP differential validator and never launches Python.

use super::external_tools;
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};
use url::Url;

const MAX_COMMAND_OUTPUT: usize = 16 * 1024;
const MAX_HTTP_BODY: usize = 20 * 1024;
const MAX_SQL_REQUESTS: usize = 6;
const PROCESS_POLL_INTERVAL: Duration = Duration::from_millis(50);
static NEXT_RUN_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Serialize)]
pub(crate) struct RetestToolFinding {
    pub(crate) kind: String,
    pub(crate) severity: String,
    pub(crate) detail: String,
    pub(crate) evidence: String,
    pub(crate) source: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct RetestToolResult {
    pub(crate) tool_id: String,
    pub(crate) tool: String,
    pub(crate) available: bool,
    pub(crate) success: bool,
    pub(crate) message: String,
    pub(crate) findings: Vec<RetestToolFinding>,
    pub(crate) logs: Vec<String>,
}

impl RetestToolResult {
    pub(crate) fn risk_count(&self) -> usize {
        self.findings
            .iter()
            .filter(|finding| matches!(finding.severity.as_str(), "medium" | "high" | "critical"))
            .count()
    }
}

pub(crate) fn run_context_checks(
    tool_root: &Path,
    client: &Client,
    urls: &[String],
    document_text: &str,
    is_cancelled: impl Fn() -> bool,
) -> Vec<RetestToolResult> {
    let lowered = document_text.to_lowercase();
    let mut results = Vec::new();
    if contains_any(&lowered, &["sql注入", "sql 注入", "sqli", "database error"]) {
        results.push(run_sql_validator(client, urls, &is_cancelled));
    }
    if contains_any(
        &lowered,
        &["端口", "服务暴露", "service exposure", "弱口令", "未授权"],
    ) {
        results.push(run_nmap(tool_root, urls, &is_cancelled));
    }
    if contains_any(
        &lowered,
        &[
            "敏感文件",
            "目录遍历",
            "目录列表",
            "未授权",
            "swagger",
            ".env",
            "备份",
            "source map",
        ],
    ) {
        results.push(run_ffuf(tool_root, urls, &lowered, &is_cancelled));
    }
    results
}

fn contains_any(value: &str, markers: &[&str]) -> bool {
    markers.iter().any(|marker| value.contains(marker))
}

/// Agent-selected tools. Selection is explicit; the notice text never picks
/// a tool on this path. The model supplies only previously authorized URLs.
pub(crate) fn run_selected(
    tool: &str,
    tool_root: &Path,
    client: &Client,
    urls: &[String],
    is_cancelled: impl Fn() -> bool,
) -> RetestToolResult {
    match tool {
        "run_nmap" => run_nmap(tool_root, urls, &is_cancelled),
        "run_sqlmap" => run_sql_validator(client, urls, &is_cancelled),
        "run_ffuf" => run_ffuf(tool_root, urls, "", &is_cancelled),
        "run_tls_probe" => run_tls_probe(tool_root, urls, &is_cancelled),
        _ => skipped_result(tool, tool, "Unknown explicit retest tool"),
    }
}

fn run_tls_probe(
    tool_root: &Path,
    urls: &[String],
    cancelled: &impl Fn() -> bool,
) -> RetestToolResult {
    let executable = match external_tools::verified_tool_path(tool_root, "nmap") {
        Ok(Some(path)) => path,
        Ok(None) => return unavailable_result("check_tls_config", "nmap"),
        Err(error) => return verification_failure("check_tls_config", "nmap", error),
    };
    let Some(url) = urls
        .iter()
        .find_map(|value| Url::parse(value).ok().filter(|url| url.scheme() == "https"))
    else {
        return skipped_result(
            "check_tls_config",
            "nmap",
            "TLS verification requires an explicit HTTPS target",
        );
    };
    let host = url.host_str().unwrap_or_default();
    let arguments = vec![
        "-n".into(),
        "-Pn".into(),
        "-sT".into(),
        "--script".into(),
        "ssl-enum-ciphers,ssl-cert".into(),
        "--script-timeout".into(),
        "30s".into(),
        "--host-timeout".into(),
        "60s".into(),
        "-p".into(),
        url.port_or_known_default().unwrap_or(443).to_string(),
        host.into(),
    ];
    match run_bounded_command(
        &executable,
        &arguments,
        executable.parent().unwrap_or(tool_root),
        Duration::from_secs(70),
        cancelled,
    ) {
        Ok(output) => RetestToolResult {
            tool_id: "check_tls_config".into(),
            tool: "nmap".into(),
            available: true,
            success: true,
            message: "已采集目标端口的 TLS 协议、密码套件和证书，交由模型对照原通报判定".into(),
            findings: vec![RetestToolFinding {
                kind: "TLS protocol/cipher/certificate evidence".into(),
                severity: "info".into(),
                detail: "Read-only handshake evidence; no exploit or load test.".into(),
                evidence: output,
                source: "reported_target".into(),
            }],
            logs: vec!["Nmap ssl-enum-ciphers / ssl-cert completed".into()],
        },
        Err(error) => execution_failure("check_tls_config", "nmap", error),
    }
}

fn run_nmap(
    tool_root: &Path,
    urls: &[String],
    is_cancelled: &impl Fn() -> bool,
) -> RetestToolResult {
    let executable = match external_tools::verified_tool_path(tool_root, "nmap") {
        Ok(Some(path)) => path,
        Ok(None) => return unavailable_result("check_nmap_service_probe", "nmap"),
        Err(error) => return verification_failure("check_nmap_service_probe", "nmap", error),
    };
    let Some(target) = nmap_target(urls) else {
        return skipped_result(
            "check_nmap_service_probe",
            "nmap",
            "No valid HTTP(S) target host was available for the bounded Nmap check",
        );
    };
    let arguments = nmap_arguments(&target.host, &target.ports);
    let cwd = executable.parent().unwrap_or(tool_root);
    match run_bounded_command(
        &executable,
        &arguments,
        cwd,
        Duration::from_secs(60),
        is_cancelled,
    ) {
        Ok(output) => {
            let open_lines = output
                .lines()
                .map(str::trim)
                .filter(|line| {
                    line.split_whitespace()
                        .any(|part| part.eq_ignore_ascii_case("open"))
                })
                .take(12)
                .collect::<Vec<_>>();
            let findings = if open_lines.is_empty() {
                vec![RetestToolFinding {
                    kind: "Nmap service probe found no open port evidence".to_string(),
                    severity: "info".to_string(),
                    detail: format!(
                        "The bounded TCP connect scan checked {} on the reported host and found no open service line.",
                        target.ports.iter().map(u16::to_string).collect::<Vec<_>>().join(",")
                    ),
                    evidence: target.host.clone(),
                    source: "context".to_string(),
                }]
            } else {
                vec![RetestToolFinding {
                    kind: "Nmap service fingerprint evidence".to_string(),
                    severity: "medium".to_string(),
                    detail: "The bounded TCP connect scan returned open service fingerprints on the reported host."
                        .to_string(),
                    evidence: open_lines.join("\n"),
                    source: "context".to_string(),
                }]
            };
            RetestToolResult {
                tool_id: "check_nmap_service_probe".to_string(),
                tool: "nmap".to_string(),
                available: true,
                success: true,
                message: "Bounded Nmap TCP connect probe completed".to_string(),
                findings,
                logs: vec![format!(
                    "nmap checked host {} with {} reviewed ports",
                    target.host,
                    target.ports.len()
                )],
            }
        }
        Err(error) => execution_failure("check_nmap_service_probe", "nmap", error),
    }
}

struct NmapTarget {
    host: String,
    ports: Vec<u16>,
}

fn nmap_target(urls: &[String]) -> Option<NmapTarget> {
    let parsed = urls.iter().find_map(|value| {
        let parsed = Url::parse(value).ok()?;
        matches!(parsed.scheme(), "http" | "https").then_some(parsed)
    })?;
    let host = parsed.host_str()?.to_string();
    let mut ports = Vec::new();
    if let Some(port) = parsed.port_or_known_default() {
        ports.push(port);
    }
    for port in [80, 443, 8080, 8443] {
        if !ports.contains(&port) {
            ports.push(port);
        }
    }
    ports.truncate(6);
    Some(NmapTarget { host, ports })
}

fn nmap_arguments(host: &str, ports: &[u16]) -> Vec<String> {
    vec![
        "-n".to_string(),
        "-Pn".to_string(),
        "-sT".to_string(),
        "-sV".to_string(),
        "--version-light".to_string(),
        "--max-retries".to_string(),
        "1".to_string(),
        "--host-timeout".to_string(),
        "45s".to_string(),
        "-p".to_string(),
        ports
            .iter()
            .map(u16::to_string)
            .collect::<Vec<_>>()
            .join(","),
        host.to_string(),
    ]
}

fn run_ffuf(
    tool_root: &Path,
    urls: &[String],
    document_text: &str,
    is_cancelled: &impl Fn() -> bool,
) -> RetestToolResult {
    let executable = match external_tools::verified_tool_path(tool_root, "ffuf") {
        Ok(Some(path)) => path,
        Ok(None) => return unavailable_result("check_ffuf_short_discovery", "ffuf"),
        Err(error) => return verification_failure("check_ffuf_short_discovery", "ffuf", error),
    };
    let Some(origin) = urls.iter().find_map(|value| http_origin(value)) else {
        return skipped_result(
            "check_ffuf_short_discovery",
            "ffuf",
            "No valid HTTP(S) origin was available for the short-list ffuf check",
        );
    };
    let words = ffuf_words(urls, document_text);
    if words.is_empty() {
        return skipped_result(
            "check_ffuf_short_discovery",
            "ffuf",
            "No reviewed short-list path matched the notice context",
        );
    }
    let run = match TemporaryRunDirectory::new("ffuf") {
        Ok(run) => run,
        Err(error) => return execution_failure("check_ffuf_short_discovery", "ffuf", error),
    };
    let wordlist = run.path.join("words.txt");
    let output_path = run.path.join("ffuf.json");
    if let Err(error) = fs::write(&wordlist, words.join("\n")) {
        return execution_failure(
            "check_ffuf_short_discovery",
            "ffuf",
            format!("failed to create bounded ffuf wordlist: {error}"),
        );
    }
    let arguments = vec![
        "-u".to_string(),
        format!("{}/FUZZ", origin.trim_end_matches('/')),
        "-w".to_string(),
        wordlist.to_string_lossy().to_string(),
        "-of".to_string(),
        "json".to_string(),
        "-o".to_string(),
        output_path.to_string_lossy().to_string(),
        "-t".to_string(),
        "5".to_string(),
        "-timeout".to_string(),
        "8".to_string(),
        "-maxtime".to_string(),
        "60".to_string(),
        "-ac".to_string(),
        "-s".to_string(),
    ];
    let cwd = executable.parent().unwrap_or(tool_root);
    let command_output = match run_bounded_command(
        &executable,
        &arguments,
        cwd,
        Duration::from_secs(75),
        is_cancelled,
    ) {
        Ok(output) => output,
        Err(error) => return execution_failure("check_ffuf_short_discovery", "ffuf", error),
    };
    let parsed = read_ffuf_output(&output_path).unwrap_or_default();
    let findings = if parsed.results.is_empty() {
        vec![RetestToolFinding {
            kind: "Ffuf short-list discovery found no response evidence".to_string(),
            severity: "info".to_string(),
            detail: format!(
                "The bounded wordlist contained {} reviewed paths.",
                words.len()
            ),
            evidence: origin.clone(),
            source: "context".to_string(),
        }]
    } else {
        let evidence = parsed
            .results
            .iter()
            .take(10)
            .map(|item| {
                format!(
                    "{} | status={}, len={}",
                    redact_url(&item.url),
                    item.status,
                    item.length
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        vec![RetestToolFinding {
            kind: "Ffuf short-list path discovery evidence".to_string(),
            severity: "medium".to_string(),
            detail:
                "The bounded ffuf run returned notice-related paths that require content review."
                    .to_string(),
            evidence,
            source: "context".to_string(),
        }]
    };
    RetestToolResult {
        tool_id: "check_ffuf_short_discovery".to_string(),
        tool: "ffuf".to_string(),
        available: true,
        success: true,
        message: "Bounded ffuf short-list discovery completed".to_string(),
        findings,
        logs: vec![format!(
            "ffuf tested {} reviewed paths; diagnostic bytes={}",
            words.len(),
            command_output.len()
        )],
    }
}

fn http_origin(value: &str) -> Option<String> {
    let parsed = Url::parse(value).ok()?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return None;
    }
    let host = parsed.host_str()?;
    let mut origin = format!("{}://{}", parsed.scheme(), host);
    if let Some(port) = parsed.port() {
        origin.push_str(&format!(":{port}"));
    }
    Some(origin)
}

fn ffuf_words(urls: &[String], document_text: &str) -> Vec<String> {
    let mut words = BTreeSet::new();
    for url in urls
        .iter()
        .take(20)
        .filter_map(|value| Url::parse(value).ok())
    {
        let path = url.path().trim_matches('/');
        if !path.is_empty() && path.len() <= 120 && !path.contains("..") {
            words.insert(path.to_string());
        }
    }
    for (markers, candidates) in [
        (
            &["未授权", "登录"][..],
            &["login", "admin", "admin/login", "manager", "console"][..],
        ),
        (
            &["敏感文件", ".env", "配置泄露"][..],
            &[".env", "config.json", "application.yml", "web.config"][..],
        ),
        (
            &["swagger", "openapi"][..],
            &["swagger-ui.html", "v3/api-docs", "openapi.json"][..],
        ),
        (
            &["备份", "源码泄露"][..],
            &["backup.zip", "www.zip", ".git/config"][..],
        ),
    ] {
        if markers.iter().any(|marker| document_text.contains(marker)) {
            words.extend(candidates.iter().map(|value| (*value).to_string()));
        }
    }
    words.into_iter().take(40).collect()
}

#[derive(Debug, Default, Deserialize)]
struct FfufOutput {
    #[serde(default)]
    results: Vec<FfufItem>,
}

#[derive(Debug, Deserialize)]
struct FfufItem {
    #[serde(default)]
    url: String,
    #[serde(default)]
    status: u16,
    #[serde(default)]
    length: u64,
}

fn read_ffuf_output(path: &Path) -> Result<FfufOutput, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("ffuf did not produce a readable JSON result: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > 4 * 1024 * 1024
    {
        return Err("ffuf JSON result is not a bounded regular file".to_string());
    }
    let bytes = fs::read(path).map_err(|error| format!("failed to read ffuf JSON: {error}"))?;
    serde_json::from_slice(&bytes).map_err(|error| format!("failed to parse ffuf JSON: {error}"))
}

fn run_sql_validator(
    client: &Client,
    urls: &[String],
    is_cancelled: &impl Fn() -> bool,
) -> RetestToolResult {
    let mut findings = Vec::new();
    let mut logs = Vec::new();
    let mut requests = 0_usize;
    for value in urls.iter().take(10) {
        if requests + 2 > MAX_SQL_REQUESTS || is_cancelled() {
            break;
        }
        let Ok(url) = Url::parse(value) else {
            continue;
        };
        if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
            continue;
        }
        let pairs = url.query_pairs().into_owned().collect::<Vec<_>>();
        let Some((parameter, original)) = pairs.first() else {
            continue;
        };
        let baseline = match fetch_bounded(client, &url) {
            Ok(body) => body,
            Err(error) => {
                logs.push(format!(
                    "SQL baseline skipped for {}: {error}",
                    redact_url(value)
                ));
                continue;
            }
        };
        requests += 1;
        if is_cancelled() {
            break;
        }
        let mut mutated = url.clone();
        {
            let mut query = mutated.query_pairs_mut();
            query.clear();
            for (index, (name, item)) in pairs.iter().enumerate() {
                if index == 0 {
                    query.append_pair(name, &format!("{item}'"));
                } else {
                    query.append_pair(name, item);
                }
            }
        }
        let mutation = match fetch_bounded(client, &mutated) {
            Ok(body) => body,
            Err(error) => {
                logs.push(format!(
                    "SQL mutation failed for {}: {error}",
                    redact_url(value)
                ));
                continue;
            }
        };
        requests += 1;
        let baseline_markers = sql_error_markers(&baseline);
        let mutation_markers = sql_error_markers(&mutation);
        let new_markers = mutation_markers
            .difference(&baseline_markers)
            .cloned()
            .collect::<Vec<_>>();
        if !new_markers.is_empty() {
            findings.push(RetestToolFinding {
                kind: "Built-in SQL validator found error differential evidence".to_string(),
                severity: "high".to_string(),
                detail: format!(
                    "A single-quote mutation of parameter {parameter} introduced database error markers not present in the baseline. No data extraction was attempted."
                ),
                evidence: format!("{} | markers={}", redact_url(value), new_markers.join(",")),
                source: "context".to_string(),
            });
        } else {
            findings.push(RetestToolFinding {
                kind: "Built-in SQL validator found no error differential".to_string(),
                severity: "info".to_string(),
                detail: format!(
                    "Parameter {parameter} was checked with one bounded syntax mutation; no new database error marker was observed."
                ),
                evidence: redact_url(value),
                source: "context".to_string(),
            });
        }
        let _ = original;
    }
    let message = if requests == 0 {
        "Built-in SQL validator found no URL query parameter to test"
    } else {
        "Built-in Rust SQL differential validation completed"
    };
    RetestToolResult {
        tool_id: "check_sqlmap_context_probe".to_string(),
        tool: "sqlmap".to_string(),
        available: true,
        success: !is_cancelled(),
        message: message.to_string(),
        findings,
        logs: {
            logs.push(format!(
                "built-in SQL validator used {requests}/{MAX_SQL_REQUESTS} requests"
            ));
            logs
        },
    }
}

fn fetch_bounded(client: &Client, url: &Url) -> Result<String, String> {
    let response = client
        .get(url.clone())
        .send()
        .map_err(|error| format!("bounded SQL request failed: {error}"))?;
    let mut bytes = Vec::new();
    response
        .take(MAX_HTTP_BODY as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("bounded SQL response read failed: {error}"))?;
    bytes.truncate(MAX_HTTP_BODY);
    Ok(String::from_utf8_lossy(&bytes).to_ascii_lowercase())
}

fn sql_error_markers(body: &str) -> BTreeSet<String> {
    [
        "sql syntax",
        "mysql_fetch",
        "you have an error in your sql",
        "ora-",
        "postgresql",
        "unterminated quoted string",
        "sqlite error",
        "sqlstate[",
        "odbc sql",
        "microsoft ole db",
    ]
    .into_iter()
    .filter(|marker| body.contains(marker))
    .map(str::to_string)
    .collect()
}

fn redact_url(value: &str) -> String {
    let Ok(mut url) = Url::parse(value) else {
        return "<invalid-url>".to_string();
    };
    let had_query = url.query().is_some();
    url.set_query(None);
    url.set_fragment(None);
    if had_query {
        format!("{}?<redacted>", url)
    } else {
        url.to_string()
    }
}

fn run_bounded_command(
    executable: &Path,
    arguments: &[String],
    cwd: &Path,
    timeout: Duration,
    is_cancelled: &impl Fn() -> bool,
) -> Result<String, String> {
    let mut command = Command::new(executable);
    command
        .args(arguments)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start managed tool: {error}"))?;
    let started = Instant::now();
    loop {
        if is_cancelled() {
            let _ = child.kill();
            let _ = child.wait();
            return Err("managed tool cancelled by inactive generation".to_string());
        }
        if started.elapsed() > timeout {
            let _ = child.kill();
            let _ = child.wait();
            return Err("managed tool exceeded its wall-clock limit".to_string());
        }
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => thread::sleep(PROCESS_POLL_INTERVAL),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("managed tool status failed: {error}"));
            }
        }
    }
    let output = child
        .wait_with_output()
        .map_err(|error| format!("managed tool output failed: {error}"))?;
    let mut combined = output.stdout;
    combined.extend_from_slice(&output.stderr);
    combined.truncate(MAX_COMMAND_OUTPUT);
    let text = String::from_utf8_lossy(&combined).to_string();
    if !output.status.success() {
        return Err(format!(
            "managed tool exited with status {}: {}",
            output.status,
            text.trim()
        ));
    }
    Ok(text)
}

fn unavailable_result(tool_id: &str, tool: &str) -> RetestToolResult {
    RetestToolResult {
        tool_id: tool_id.to_string(),
        tool: tool.to_string(),
        available: false,
        success: true,
        message: format!("{tool} is not installed in the verified managed tool directory"),
        findings: vec![RetestToolFinding {
            kind: format!("{tool} optional check unavailable"),
            severity: "info".to_string(),
            detail: format!(
                "Install the locked {tool} runtime before retrying this optional check."
            ),
            evidence: String::new(),
            source: "context".to_string(),
        }],
        logs: vec![format!(
            "{tool} optional check skipped: managed product not installed"
        )],
    }
}

fn skipped_result(tool_id: &str, tool: &str, reason: &str) -> RetestToolResult {
    RetestToolResult {
        tool_id: tool_id.to_string(),
        tool: tool.to_string(),
        available: true,
        success: true,
        message: reason.to_string(),
        findings: Vec::new(),
        logs: vec![reason.to_string()],
    }
}

fn verification_failure(tool_id: &str, tool: &str, error: String) -> RetestToolResult {
    RetestToolResult {
        tool_id: tool_id.to_string(),
        tool: tool.to_string(),
        available: false,
        success: false,
        message: format!("{tool} product verification failed closed"),
        findings: Vec::new(),
        logs: vec![error],
    }
}

fn execution_failure(tool_id: &str, tool: &str, error: String) -> RetestToolResult {
    RetestToolResult {
        tool_id: tool_id.to_string(),
        tool: tool.to_string(),
        available: true,
        success: false,
        message: format!("{tool} bounded execution failed"),
        findings: Vec::new(),
        logs: vec![error],
    }
}

struct TemporaryRunDirectory {
    path: PathBuf,
}

impl TemporaryRunDirectory {
    fn new(label: &str) -> Result<Self, String> {
        let path = std::env::temp_dir().join(format!(
            "koi-{label}-run-{}-{}",
            std::process::id(),
            NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path)
            .map_err(|error| format!("failed to create managed tool run directory: {error}"))?;
        Ok(Self { path })
    }
}

impl Drop for TemporaryRunDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::redirect::Policy;
    use std::io::Write as _;
    use std::net::TcpListener;

    #[test]
    fn command_arguments_are_bounded_and_never_enable_raw_packet_modes() {
        let arguments = nmap_arguments("127.0.0.1", &[80, 443]);
        assert!(arguments.contains(&"-sT".to_string()));
        assert!(!arguments
            .iter()
            .any(|value| matches!(value.as_str(), "-sS" | "-O" | "--script")));
        assert!(arguments.contains(&"45s".to_string()));
    }

    #[test]
    fn ffuf_wordlist_is_context_bounded_and_deduplicated() {
        let words = ffuf_words(
            &["https://example.test/admin/login?next=1".to_string()],
            "未授权 敏感文件 swagger 备份",
        );
        assert!(words.len() <= 40);
        assert!(words.contains(&"admin/login".to_string()));
        assert!(words.contains(&".env".to_string()));
        assert!(words.contains(&"v3/api-docs".to_string()));
        assert_eq!(words.iter().collect::<BTreeSet<_>>().len(), words.len());
    }

    #[test]
    fn built_in_sql_validator_preserves_tool_id_and_detects_new_error_marker() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock SQL server");
        let address = listener.local_addr().expect("mock address");
        let server = thread::spawn(move || {
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().expect("accept SQL request");
                let mut request = [0_u8; 4096];
                let count = stream.read(&mut request).expect("read request");
                let request = String::from_utf8_lossy(&request[..count]);
                let body = if request.contains("%27") {
                    "You have an error in your SQL syntax"
                } else {
                    "normal response"
                };
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                )
                .expect("write response");
            }
        });
        let client = Client::builder()
            .timeout(Duration::from_secs(2))
            .redirect(Policy::none())
            .build()
            .expect("client");
        let result =
            run_sql_validator(&client, &[format!("http://{address}/item?id=1")], &|| false);
        server.join().expect("mock server");
        assert_eq!(result.tool_id, "check_sqlmap_context_probe");
        assert_eq!(result.tool, "sqlmap");
        assert!(result.available);
        assert_eq!(result.risk_count(), 1);
        assert!(result.findings[0].evidence.contains("?<redacted>"));
        assert!(!result.findings[0].evidence.contains("id=1"));
    }
}
