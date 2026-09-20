//! Native helpers for AI retest file discovery and exact report correlation.
//!
//! Tool execution and the generation-aware retest state machine live in
//! `native_runtime`; this module owns the typed `doc.retest.list_files`
//! boundary and never delegates to a sidecar.

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

const GENERATED_REPORT_MARKER: &str = "\u{590d}\u{6d4b}\u{62a5}\u{544a}";
const GENERATED_REPORT_DIRS: [&str; 3] = [
    "retest_reports",
    ".koi_retest_screenshots",
    ".koi_retest_staging",
];
const NOTICE_MARKERS: [&str; 3] = [
    "\u{901a}\u{62a5}\u{62a5}\u{544a}",
    "\u{5b89}\u{5168}\u{6f0f}\u{6d1e}",
    "vulnerability",
];
const NON_REPORT_KEYWORDS: [&str; 9] = [
    "\u{6a21}\u{677f}",
    "template",
    "\u{5904}\u{7f6e}\u{6587}\u{4ef6}",
    "\u{793a}\u{4f8b}",
    "\u{6837}\u{4f8b}",
    "example",
    "\u{8bf4}\u{660e}",
    "readme",
    "\u{5907}\u{4efd}",
];
const NOTICE_NAME_TERMS: [&str; 9] = [
    "\u{6f0f}\u{6d1e}",
    "\u{672a}\u{6388}\u{6743}",
    "\u{8d8a}\u{6743}",
    "\u{5f31}\u{53e3}\u{4ee4}",
    "\u{4fe1}\u{606f}\u{6cc4}\u{9732}",
    "\u{654f}\u{611f}\u{4fe1}\u{606f}",
    "\u{6ce8}\u{5165}",
    "\u{5b89}\u{5168}\u{95ee}\u{9898}",
    "\u{5b89}\u{5168}\u{9690}\u{60a3}",
];
const DIRECT_NOTICE_TERMS: [&str; 9] = [
    "\u{63a5}\u{53e3}\u{672a}\u{6388}\u{6743}",
    "\u{672a}\u{6388}\u{6743}\u{8bbf}\u{95ee}",
    "\u{672a}\u{6388}\u{6743}\u{63a5}\u{53e3}",
    "\u{63a5}\u{53e3}\u{8d8a}\u{6743}",
    "sql\u{6ce8}\u{5165}",
    "xss",
    "ssrf",
    "rce",
    "\u{5f31}\u{53e3}\u{4ee4}",
];

#[derive(Debug, Default, Deserialize)]
struct ListFilesRequest {
    #[serde(
        default,
        alias = "targetDir",
        deserialize_with = "deserialize_compat_string"
    )]
    target_dir: Option<String>,
}

/// Handle `~`, `~/...`, and `~\...` the same way as Python's `expanduser`
/// for the app's single-user desktop context.
fn expand_user(value: &str, home: &Path) -> PathBuf {
    if value == "~" {
        return home.to_path_buf();
    }
    if let Some(relative) = value
        .strip_prefix("~/")
        .or_else(|| value.strip_prefix("~\\"))
    {
        return home.join(relative);
    }
    PathBuf::from(value)
}

fn required_text(value: Option<String>, message: &str) -> Result<String, String> {
    let value = value.unwrap_or_default();
    if value.trim().is_empty() {
        Err(message.to_string())
    } else {
        Ok(value.trim().to_string())
    }
}

fn deserialize_compat_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value.as_ref().and_then(value_to_truthy_string))
}

fn value_to_truthy_string(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::Bool(false) => None,
        Value::Bool(true) => Some("True".to_string()),
        Value::Number(number) => {
            let text = number.to_string();
            (number.as_f64().is_some_and(|item| item != 0.0)).then_some(text)
        }
        Value::String(text) => (!text.is_empty()).then_some(text.clone()),
        Value::Array(items) => (!items.is_empty()).then_some(value.to_string()),
        Value::Object(items) => (!items.is_empty()).then_some(value.to_string()),
    }
}

fn is_word_file(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| matches!(value.to_ascii_lowercase().as_str(), "doc" | "docx"))
        .unwrap_or(false)
}

fn path_component_text(component: &std::ffi::OsStr) -> String {
    component.to_string_lossy().to_lowercase()
}

fn is_generated_report_path(path: &Path) -> bool {
    let name = path
        .file_name()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if name.contains(GENERATED_REPORT_MARKER)
        || name.contains("复测待核验报告")
        || name.contains("retest report")
    {
        return true;
    }
    path.components().any(|component| {
        let text = path_component_text(component.as_os_str());
        GENERATED_REPORT_DIRS.iter().any(|item| text == *item)
    })
}

fn looks_like_notice_filename(filename: &str) -> bool {
    let lowered = filename.to_lowercase();
    if NOTICE_MARKERS
        .iter()
        .any(|marker| filename.contains(marker) || lowered.contains(marker))
    {
        return true;
    }

    let stem = Path::new(filename)
        .file_stem()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if DIRECT_NOTICE_TERMS.iter().any(|term| stem.contains(term)) {
        return true;
    }

    // Python's first filename pattern is `存在.{0,60}<risk term>`.  A
    // character-counted window keeps this equivalent without pulling a regex
    // engine into the small native backend.
    if let Some(start) = stem.find("\u{5b58}\u{5728}") {
        let tail: String = stem[start + "\u{5b58}\u{5728}".len()..]
            .chars()
            .take(60)
            .collect();
        if NOTICE_NAME_TERMS.iter().any(|term| tail.contains(term)) {
            return true;
        }
    }
    false
}

fn collect_word_files(dir: &Path, logs: &mut Vec<String>, output: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        // os.walk does not follow directory symlinks by default.  It still
        // exposes symlinked files, so only prune symlinked directories.
        if file_type.is_symlink() {
            if path.is_dir() {
                continue;
            }
        } else if file_type.is_dir() {
            collect_word_files(&path, logs, output);
            continue;
        }
        if !path.is_file() || !is_word_file(&path) {
            continue;
        }

        let filename = path
            .file_name()
            .map(|value| value.to_string_lossy().to_string())
            .unwrap_or_default();
        let filename_lower = filename.to_lowercase();
        if filename.starts_with("~$") {
            logs.push(format!(
                "[\u{8df3}\u{8fc7}] Word\u{4e34}\u{65f6}\u{6587}\u{4ef6}: {}",
                path.display()
            ));
            continue;
        }
        if filename.starts_with('.') {
            logs.push(format!(
                "[\u{8df3}\u{8fc7}] \u{9690}\u{85cf}\u{6587}\u{4ef6}: {}",
                path.display()
            ));
            continue;
        }
        if is_generated_report_path(&path) {
            logs.push(format!(
                "[skip] Generated retest report: {}",
                path.display()
            ));
            continue;
        }
        if !looks_like_notice_filename(&filename)
            && NON_REPORT_KEYWORDS
                .iter()
                .any(|keyword| filename_lower.contains(keyword))
        {
            logs.push(format!(
                "[\u{8df3}\u{8fc7}] \u{975e}\u{901a}\u{62a5}\u{6587}\u{4ef6}: {}",
                path.display()
            ));
            continue;
        }
        output.push(path);
    }
}

fn collect_all_files(dir: &Path, output: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if file_type.is_symlink() {
            if path.is_dir() {
                continue;
            }
            if path.is_file() {
                output.push(path);
            }
            continue;
        }
        if file_type.is_dir() {
            collect_all_files(&path, output);
        } else if file_type.is_file() {
            output.push(path);
        }
    }
}

fn path_key(path: &Path) -> String {
    let absolute = fs::canonicalize(path).unwrap_or_else(|_| {
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map(|cwd| cwd.join(path))
                .unwrap_or_else(|_| path.to_path_buf())
        }
    });
    let mut text = absolute.to_string_lossy().replace('\\', "/");
    if cfg!(windows) {
        text = text.to_lowercase();
    }
    text.trim_end_matches('/').to_string()
}

fn strip_retest_report_marker(mut text: String) -> String {
    loop {
        let before = text.clone();
        let trimmed = text.trim_end().to_string();
        text = trimmed;
        if text.ends_with(GENERATED_REPORT_MARKER) {
            let length = text.len() - GENERATED_REPORT_MARKER.len();
            text.truncate(length);
        } else {
            let lower = text.to_lowercase();
            if lower.ends_with("retest report") {
                text.truncate(text.len() - "retest report".len());
            } else if lower.ends_with("retestreport") {
                text.truncate(text.len() - "retestreport".len());
            } else {
                break;
            }
        }
        text = text.trim_end_matches([' ', '_', '-']).to_string();
        if text == before {
            break;
        }
    }
    text
}

fn notice_identity_keys(value: &str) -> Vec<String> {
    let name = Path::new(value)
        .file_name()
        .map(|item| item.to_string_lossy().to_string())
        .unwrap_or_default();
    if name.is_empty() {
        return Vec::new();
    }
    let stem = Path::new(&name)
        .file_stem()
        .map(|item| item.to_string_lossy().to_string())
        .unwrap_or_default();
    let mut candidates = vec![stem.clone(), strip_retest_report_marker(stem)];
    for candidate in candidates.clone() {
        for suffix in ["\u{7684}\u{901a}\u{62a5}", "\u{901a}\u{62a5}"] {
            if candidate.ends_with(suffix) && candidate.len() > suffix.len() {
                candidates.push(
                    candidate[..candidate.len() - suffix.len()]
                        .trim()
                        .to_string(),
                );
            }
        }
    }
    let mut keys = Vec::new();
    for candidate in candidates {
        let normalized: String = candidate
            .trim()
            .to_lowercase()
            .chars()
            .filter(|item| !item.is_whitespace())
            .collect();
        if !normalized.is_empty() && !keys.contains(&normalized) {
            keys.push(normalized);
        }
    }
    keys
}

#[derive(Debug, Clone)]
struct SourceInfo {
    path: PathBuf,
    parent_key: String,
    identity_keys: Vec<String>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ListFilesResponse {
    pub(crate) success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    target_dir: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) source_files: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_source_files: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_source_file_names: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) existing_report_evidence: Option<Vec<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_count_hint: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    next_index_hint: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    next_source_file: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    next_source_file_name: Option<String>,
    pub(crate) logs: Vec<String>,
}

fn report_evidence(target_dir: &Path, source_files: &[PathBuf]) -> Vec<Value> {
    let sources: Vec<SourceInfo> = source_files
        .iter()
        .map(|path| SourceInfo {
            path: path.clone(),
            parent_key: path_key(path.parent().unwrap_or_else(|| Path::new("."))),
            identity_keys: notice_identity_keys(
                &path
                    .file_name()
                    .map(|item| item.to_string_lossy().to_string())
                    .unwrap_or_default(),
            ),
        })
        .collect();

    let mut by_parent: HashMap<(String, String), usize> = HashMap::new();
    let mut by_key: HashMap<String, Vec<usize>> = HashMap::new();
    for (index, source) in sources.iter().enumerate() {
        for key in &source.identity_keys {
            by_parent
                .entry((source.parent_key.clone(), key.clone()))
                .or_insert(index);
            by_key.entry(key.clone()).or_default().push(index);
        }
    }

    let mut reports = Vec::new();
    collect_all_files(target_dir, &mut reports);
    let mut evidence_by_source: HashMap<String, Value> = HashMap::new();
    for report_path in reports {
        if !is_word_file(&report_path) || !is_generated_report_path(&report_path) {
            continue;
        }
        if report_path
            .file_name()
            .is_some_and(|name| name.to_string_lossy().contains("复测待核验报告"))
        {
            continue;
        }
        let report_name = report_path
            .file_name()
            .map(|item| item.to_string_lossy().to_string())
            .unwrap_or_default();
        let parent_key = path_key(report_path.parent().unwrap_or_else(|| Path::new(".")));
        let mut matched: Option<usize> = None;
        for key in notice_identity_keys(&report_name) {
            if let Some(index) = by_parent.get(&(parent_key.clone(), key.clone())) {
                matched = Some(*index);
                break;
            }
            if let Some(candidates) = by_key.get(&key) {
                if candidates.len() == 1 {
                    matched = candidates.first().copied();
                    break;
                }
            }
        }
        let Some(index) = matched else {
            continue;
        };
        let source = &sources[index];
        let source_key = path_key(&source.path);
        evidence_by_source.entry(source_key).or_insert_with(|| {
            json!({
                "source_file": source.path.to_string_lossy(),
                "source_file_name": source.path.file_name().map(|item| item.to_string_lossy()).unwrap_or_default(),
                "report_path": report_path.to_string_lossy(),
                "report_file_name": report_name,
            })
        });
    }

    sources
        .iter()
        .filter_map(|source| evidence_by_source.get(&path_key(&source.path)).cloned())
        .collect()
}

/// Discover source notices and existing generated-report evidence.
pub fn list_files(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    serde_json::to_value(list_files_typed(payload, fallback_home)?)
        .map_err(|error| format!("serialize retest file list failed: {error}"))
}

pub(crate) fn list_files_typed(
    payload: &Value,
    fallback_home: &Path,
) -> Result<ListFilesResponse, String> {
    let request: ListFilesRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("请求参数格式错误: {error}"))?;
    let target_text = required_text(
        request.target_dir,
        "\u{8bf7}\u{9009}\u{62e9}\u{901a}\u{62a5}\u{76ee}\u{5f55}",
    )?;
    let target_dir = expand_user(&target_text, fallback_home);
    if !target_dir.exists() || !target_dir.is_dir() {
        return Ok(ListFilesResponse {
            success: false,
            message: format!(
                "\u{901a}\u{62a5}\u{76ee}\u{5f55}\u{4e0d}\u{5b58}\u{5728}: {}",
                target_dir.display()
            ),
            target_dir: None,
            total: None,
            source_files: None,
            completed_source_files: None,
            completed_source_file_names: None,
            existing_report_evidence: None,
            completed_count_hint: None,
            next_index_hint: None,
            next_source_file: None,
            next_source_file_name: None,
            logs: Vec::new(),
        });
    }

    let mut logs = Vec::new();
    let mut word_files = Vec::new();
    collect_word_files(&target_dir, &mut logs, &mut word_files);
    let evidence = report_evidence(&target_dir, &word_files);
    let completed_names: Vec<String> = evidence
        .iter()
        .filter_map(|item| {
            item.get("source_file_name")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect();
    let next_index_hint = completed_names.len();
    let next_source_file = word_files
        .get(next_index_hint)
        .map(|item| item.to_string_lossy().to_string())
        .unwrap_or_default();
    logs.push(format!(
        "\u{626b}\u{63cf}\u{5b8c}\u{6210}\u{ff0c}\u{53d1}\u{73b0} {} \u{4efd}\u{539f}\u{59cb}\u{901a}\u{62a5}\u{6587}\u{6863}\u{ff1b}\u{4ece}\u{540c}\u{76ee}\u{5f55}\u{590d}\u{6d4b}\u{62a5}\u{544a}\u{8bc6}\u{522b}\u{5230} {} \u{4efd}\u{5df2}\u{5b8c}\u{6210}\u{901a}\u{62a5}",
        word_files.len(),
        completed_names.len()
    ));
    let mut message = format!(
        "\u{53d1}\u{73b0} {} \u{4efd}\u{539f}\u{59cb}\u{901a}\u{62a5}\u{6587}\u{6863}",
        word_files.len()
    );
    if !completed_names.is_empty() {
        message.push_str(&format!(
            "\u{ff0c}\u{5df2}\u{4ece}\u{590d}\u{6d4b}\u{62a5}\u{544a}\u{8bc6}\u{522b} {} \u{4efd}\u{5df2}\u{5b8c}\u{6210}",
            completed_names.len()
        ));
    }

    Ok(ListFilesResponse {
        success: true,
        message,
        target_dir: Some(target_dir.to_string_lossy().into_owned()),
        total: Some(word_files.len()),
        source_files: Some(
            word_files
                .iter()
                .map(|item| item.to_string_lossy().to_string())
                .collect(),
        ),
        completed_source_files: Some(
            evidence
                .iter()
                .filter_map(|item| {
                    item.get("source_file")
                        .and_then(Value::as_str)
                        .map(str::to_string)
                })
                .collect(),
        ),
        completed_source_file_names: Some(completed_names),
        existing_report_evidence: Some(evidence),
        completed_count_hint: Some(next_index_hint),
        next_index_hint: Some(next_index_hint),
        next_source_file: Some(next_source_file),
        next_source_file_name: Some(
            word_files
                .get(next_index_hint)
                .and_then(|item| item.file_name())
                .map(|item| item.to_string_lossy().to_string())
                .unwrap_or_default(),
        ),
        logs,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempDir(PathBuf);

    impl TempDir {
        fn new(label: &str) -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock must be after epoch")
                .as_nanos();
            let path = std::env::temp_dir().join(format!(
                "koi-rust-retest-{label}-{}-{nonce}",
                std::process::id()
            ));
            fs::create_dir_all(&path).expect("create isolated retest fixture");
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn list_files_filters_sources_and_preserves_recursive_paths() {
        let temp = TempDir::new("filter");
        let nested = temp.path().join("nested");
        let generated = temp.path().join("retest_reports");
        fs::create_dir_all(&nested).expect("create nested fixture");
        fs::create_dir_all(&generated).expect("create generated fixture");
        fs::write(temp.path().join("安全漏洞通报.docx"), b"fixture").expect("source");
        fs::write(nested.join("notice.doc"), b"fixture").expect("generic source");
        fs::write(temp.path().join("模板.docx"), b"template").expect("template");
        fs::write(temp.path().join("~$临时.docx"), b"temporary").expect("temporary");
        fs::write(generated.join("安全漏洞复测报告.docx"), b"report").expect("report");

        let response = list_files(&json!({"target_dir": temp.path()}), Path::new("C:\\home"))
            .expect("list files response");
        assert_eq!(response["success"], true);
        assert_eq!(response["total"], 2);
        let files = response["source_files"].as_array().expect("source files");
        assert!(files.iter().any(|item| item
            .as_str()
            .unwrap_or_default()
            .ends_with("安全漏洞通报.docx")));
        assert!(files.iter().any(|item| item
            .as_str()
            .unwrap_or_default()
            .ends_with("nested\\notice.doc")
            || item
                .as_str()
                .unwrap_or_default()
                .ends_with("nested/notice.doc")));
        assert!(response["logs"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item.as_str().unwrap_or_default().contains("非通报文件")));
    }

    #[test]
    fn list_files_correlates_same_directory_report_evidence() {
        let temp = TempDir::new("evidence");
        fs::write(temp.path().join("存在弱口令通报.docx"), b"source").expect("source");
        fs::write(temp.path().join("存在弱口令复测报告.docx"), b"report").expect("report");
        let response = list_files(&json!({"target_dir": temp.path()}), Path::new("C:\\home"))
            .expect("list files response");
        assert_eq!(
            response["completed_source_file_names"],
            json!(["存在弱口令通报.docx"])
        );
        assert_eq!(response["completed_count_hint"], 1);
        assert_eq!(response["next_index_hint"], 1);
        assert!(response["existing_report_evidence"][0]["report_file_name"]
            .as_str()
            .unwrap_or_default()
            .contains("复测报告"));
    }

    #[test]
    fn inconclusive_report_is_not_a_source_or_completed_disk_evidence() {
        let temp = TempDir::new("inconclusive-evidence");
        fs::write(temp.path().join("存在弱口令通报.docx"), b"source").expect("source");
        fs::write(
            temp.path().join("存在弱口令_复测待核验报告.docx"),
            b"unreachable target evidence",
        )
        .expect("inconclusive report");
        let response = list_files(&json!({"target_dir":temp.path()}), Path::new("C:\\home"))
            .expect("list files response");
        assert_eq!(response["total"], 1);
        assert_eq!(response["completed_count_hint"], 0);
        assert_eq!(response["existing_report_evidence"], json!([]));
        assert_eq!(response["next_index_hint"], 0);
    }

    #[test]
    fn list_files_missing_target_is_a_data_failure() {
        let missing =
            std::env::temp_dir().join(format!("koi-rust-retest-missing-{}", std::process::id()));
        let response = list_files(&json!({"target_dir": missing}), Path::new("C:\\home"))
            .expect("missing target returns data failure");
        assert_eq!(response["success"], false);
        assert!(response["message"]
            .as_str()
            .unwrap_or_default()
            .contains("通报目录不存在"));
        assert_eq!(response["logs"], json!([]));
    }

    #[test]
    fn list_files_requires_target_directory_payload() {
        let error = list_files(&json!({}), Path::new("C:\\home")).expect_err("required target");
        assert_eq!(error, "请选择通报目录");
    }

    #[test]
    fn list_files_request_keeps_camel_case_and_python_string_compatibility() {
        let request: ListFilesRequest =
            serde_json::from_value(json!({"targetDir": 42})).expect("typed compatibility request");
        assert_eq!(request.target_dir.as_deref(), Some("42"));
    }
}
