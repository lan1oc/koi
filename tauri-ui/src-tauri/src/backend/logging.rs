use super::protocol::BackendResponse;
use chrono::{SecondsFormat, Utc};
use regex::Regex;
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

const LOG_SCHEMA_VERSION: u32 = 1;
const DEFAULT_MAX_BYTES: u64 = 2 * 1024 * 1024;
const DEFAULT_ARCHIVES: usize = 4;
const MAX_COMMAND_CHARS: usize = 256;
const MAX_ERROR_CHARS: usize = 8_000;
const REDACTED: &str = "[REDACTED]";
const TRUNCATED: &str = "...[TRUNCATED]";

#[derive(Debug, Default)]
pub(crate) struct RedactionContext {
    sensitive_values: Vec<String>,
}

pub(crate) struct RedactingRollingLogger {
    path: PathBuf,
    max_bytes: u64,
    max_archives: usize,
    access: Mutex<()>,
}

impl RedactingRollingLogger {
    pub(crate) fn new(user_data_dir: &Path) -> Result<Self, String> {
        Self::with_limits(
            user_data_dir.join("logs/koi-core.jsonl"),
            DEFAULT_MAX_BYTES,
            DEFAULT_ARCHIVES,
        )
    }

    fn with_limits(path: PathBuf, max_bytes: u64, max_archives: usize) -> Result<Self, String> {
        let parent = path
            .parent()
            .ok_or_else(|| "backend log path has no parent".to_string())?;
        fs::create_dir_all(parent)
            .map_err(|error| format!("failed to create backend log directory: {error}"))?;
        Ok(Self {
            path,
            max_bytes: max_bytes.max(1),
            max_archives,
            access: Mutex::new(()),
        })
    }

    pub(crate) fn capture(&self, payload: &Value) -> RedactionContext {
        let mut sensitive_values = Vec::new();
        collect_sensitive_values(payload, false, &mut sensitive_values);
        sensitive_values.sort_by_key(|value| std::cmp::Reverse(value.len()));
        sensitive_values.dedup();
        RedactionContext { sensitive_values }
    }

    pub(crate) fn log_command(
        &self,
        command: &str,
        response: &BackendResponse,
        context: &RedactionContext,
    ) -> Result<(), String> {
        let error = response
            .error
            .as_deref()
            .map(|error| truncate_field(&redact_text(error, context), MAX_ERROR_CHARS));
        let record = json!({
            "schema_version": LOG_SCHEMA_VERSION,
            "timestamp": Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            "level": if response.ok { "info" } else { "error" },
            "event": "backend.command",
            "command": truncate_field(&redact_text(command, context), MAX_COMMAND_CHARS),
            "ok": response.ok,
            "error": error,
        });
        let mut encoded = serde_json::to_vec(&record)
            .map_err(|error| format!("failed to encode backend log record: {error}"))?;
        encoded.push(b'\n');

        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.rotate_if_needed(encoded.len() as u64)?;
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .map_err(|error| format!("failed to open backend log: {error}"))?;
        file.write_all(&encoded)
            .map_err(|error| format!("failed to write backend log: {error}"))?;
        file.flush()
            .map_err(|error| format!("failed to flush backend log: {error}"))
    }

    fn rotate_if_needed(&self, incoming_bytes: u64) -> Result<(), String> {
        let current_bytes = fs::metadata(&self.path)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        if current_bytes == 0 || current_bytes.saturating_add(incoming_bytes) <= self.max_bytes {
            return Ok(());
        }

        if self.max_archives == 0 {
            fs::remove_file(&self.path)
                .map_err(|error| format!("failed to rotate backend log: {error}"))?;
            return Ok(());
        }
        for index in (1..=self.max_archives).rev() {
            let source = if index == 1 {
                self.path.clone()
            } else {
                archived_path(&self.path, index - 1)
            };
            if !source.exists() {
                continue;
            }
            let destination = archived_path(&self.path, index);
            if destination.exists() {
                fs::remove_file(&destination)
                    .map_err(|error| format!("failed to prune backend log archive: {error}"))?;
            }
            fs::rename(&source, &destination)
                .map_err(|error| format!("failed to rotate backend log: {error}"))?;
        }
        Ok(())
    }
}

fn archived_path(path: &Path, index: usize) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("koi-core.jsonl");
    path.with_file_name(format!("{file_name}.{index}"))
}

fn collect_sensitive_values(value: &Value, sensitive: bool, output: &mut Vec<String>) {
    match value {
        Value::Object(entries) => {
            for (key, value) in entries {
                collect_sensitive_values(value, sensitive || is_sensitive_key(key), output);
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_sensitive_values(value, sensitive, output);
            }
        }
        Value::String(value) if sensitive && !value.is_empty() => output.push(value.clone()),
        Value::Number(value) if sensitive => output.push(value.to_string()),
        Value::Bool(value) if sensitive => output.push(value.to_string()),
        _ => {}
    }
}

fn is_sensitive_key(key: &str) -> bool {
    let normalized = key
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect::<String>();
    [
        "apikey",
        "authorization",
        "cookie",
        "password",
        "passwd",
        "secret",
        "token",
    ]
    .iter()
    .any(|marker| normalized.contains(marker))
}

fn redact_text(text: &str, context: &RedactionContext) -> String {
    let mut redacted = text.to_string();
    for value in &context.sensitive_values {
        redacted = redacted.replace(value, REDACTED);
    }
    for regex in secret_patterns() {
        redacted = regex.replace_all(&redacted, "$1[REDACTED]").into_owned();
    }
    redacted
}

fn truncate_field(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    let mut truncated = value.chars().take(max_chars).collect::<String>();
    truncated.push_str(TRUNCATED);
    truncated
}

fn secret_patterns() -> &'static [Regex] {
    static PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        [
            r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;]+",
            r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\r\n]+",
            r#"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;&]+"#,
        ]
        .into_iter()
        .map(|pattern| Regex::new(pattern).expect("static secret redaction regex"))
        .collect()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_directory(label: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "koi-core-log-{label}-{}-{suffix}",
            std::process::id()
        ));
        fs::create_dir_all(&path).expect("create temp directory");
        path
    }

    #[test]
    fn structured_log_redacts_payload_and_header_secrets() {
        let directory = temp_directory("redaction");
        let path = directory.join("core.jsonl");
        let logger =
            RedactingRollingLogger::with_limits(path.clone(), 16 * 1024, 2).expect("logger");
        let payload = json!({
            "api_key": "payload-secret-123",
            "nested": {"cookie": "session=payload-cookie-456"}
        });
        let context = logger.capture(&payload);
        let response = BackendResponse::failure(
            "api_key=payload-secret-123 Authorization: Bearer header-secret Cookie: raw-cookie",
        );
        logger
            .log_command("info.asset.fofa.query", &response, &context)
            .expect("write log");

        let encoded = fs::read_to_string(&path).expect("read log");
        assert!(!encoded.contains("payload-secret-123"));
        assert!(!encoded.contains("payload-cookie-456"));
        assert!(!encoded.contains("header-secret"));
        assert!(!encoded.contains("raw-cookie"));
        assert!(encoded.contains(REDACTED));
        let record: Value = serde_json::from_str(encoded.trim()).expect("parse JSONL record");
        assert_eq!(record["event"], "backend.command");
        assert_eq!(record["ok"], false);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn rolling_log_bounds_archive_count_and_keeps_json_lines() {
        let directory = temp_directory("rotation");
        let path = directory.join("core.jsonl");
        let logger = RedactingRollingLogger::with_limits(path.clone(), 260, 2).expect("logger");
        let context = RedactionContext::default();
        for index in 0..12 {
            logger
                .log_command(
                    "doc.retest.run_one.start",
                    &BackendResponse::failure(format!(
                        "bounded rotation record {index}: {}",
                        "x".repeat(80)
                    )),
                    &context,
                )
                .expect("write rotating log");
        }

        assert!(path.is_file());
        let archive_one = archived_path(&path, 1);
        let archive_two = archived_path(&path, 2);
        assert!(archive_one.is_file());
        assert!(archive_two.is_file());
        assert!(!archived_path(&path, 3).exists());
        for candidate in [&path, &archive_one, &archive_two] {
            for line in fs::read_to_string(candidate).expect("read archive").lines() {
                serde_json::from_str::<Value>(line).expect("archive line is valid JSON");
            }
        }
        let _ = fs::remove_dir_all(directory);
    }
}
