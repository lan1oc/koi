//! Typed Rust clients for FOFA, Hunter, and Quake asset queries.
//!
//! Endpoint injection stays explicit so tests never need real credentials or
//! external network access.

use super::batch_input::read_lines_file;
use super::config::ConfigStore;
use base64::engine::general_purpose::{STANDARD, URL_SAFE};
use base64::Engine as _;
use reqwest::blocking::{Client, RequestBuilder, Response};
use reqwest::StatusCode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::io::Read;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

pub const FOFA_COMMAND: &str = "info.asset.fofa.query";
pub const HUNTER_COMMAND: &str = "info.asset.hunter.query";
pub const QUAKE_COMMAND: &str = "info.asset.quake.query";
pub const UNIFIED_COMMAND: &str = "info.asset.unified.query";

const DEFAULT_MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

pub fn is_command(command: &str) -> bool {
    matches!(
        command,
        FOFA_COMMAND | HUNTER_COMMAND | QUAKE_COMMAND | UNIFIED_COMMAND
    )
}

#[derive(Debug, Clone)]
pub struct CancellationToken(Arc<AtomicBool>);

impl CancellationToken {
    pub fn new() -> Self {
        Self(Arc::new(AtomicBool::new(false)))
    }

    #[allow(dead_code)]
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }

    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

impl Default for CancellationToken {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone)]
pub struct RetryPolicy {
    pub max_attempts: u8,
    pub initial_backoff: Duration,
    pub request_timeout: Duration,
    pub max_response_bytes: usize,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            initial_backoff: Duration::from_millis(250),
            request_timeout: Duration::from_secs(30),
            max_response_bytes: DEFAULT_MAX_RESPONSE_BYTES,
        }
    }
}

#[derive(Debug, Clone)]
pub struct AssetEndpoints {
    pub fofa_search: String,
    pub hunter_search: String,
    pub quake_search: String,
}

impl Default for AssetEndpoints {
    fn default() -> Self {
        Self {
            fofa_search: "https://fofa.info/api/v1/search/all".to_string(),
            hunter_search: "https://hunter.qianxin.com/openApi/search".to_string(),
            quake_search: "https://quake.360.cn/api/v3/search/quake_service".to_string(),
        }
    }
}

pub struct AssetQueryService {
    client: Client,
    endpoints: AssetEndpoints,
    retry: RetryPolicy,
    cancellation: CancellationToken,
}

impl AssetQueryService {
    pub fn production() -> Result<Self, String> {
        Self::new(
            AssetEndpoints::default(),
            RetryPolicy::default(),
            CancellationToken::new(),
        )
    }

    pub fn new(
        endpoints: AssetEndpoints,
        retry: RetryPolicy,
        cancellation: CancellationToken,
    ) -> Result<Self, String> {
        let client = Client::builder()
            .user_agent("KOI/4.0.0")
            .redirect(reqwest::redirect::Policy::limited(5))
            .build()
            .map_err(|error| format!("创建资产查询 HTTP 客户端失败: {error}"))?;
        Ok(Self {
            client,
            endpoints,
            retry,
            cancellation,
        })
    }

    pub fn dispatch(
        &self,
        command: &str,
        payload: &Value,
        config: &Value,
    ) -> Result<Value, String> {
        let secrets = asset_secrets(payload, config);
        let result = match command {
            FOFA_COMMAND => self.fofa(payload, config),
            HUNTER_COMMAND => self.hunter(payload, config),
            QUAKE_COMMAND => self.quake(payload, config),
            UNIFIED_COMMAND => self.unified(payload, config),
            _ => Err(format!("未知资产查询命令: {command}")),
        };
        result
            .map(|mut value| {
                redact_secret_value(&mut value, &secrets);
                value
            })
            .map_err(|error| sanitize_error_owned(error, &secrets))
    }

    fn fofa(&self, payload: &Value, config: &Value) -> Result<Value, String> {
        let request: FofaRequest = parse_payload(payload)?;
        let query = required_query(&request.query, "请输入 FOFA 查询语句")?;
        let page = request.page.clamp(1, 10_000);
        let size = request.size.clamp(1, 10_000);
        let fields = if request.fields.is_empty() {
            "host,ip,port,title,country,protocol"
        } else {
            request.fields.trim()
        };
        let email = first_nonempty(&request.email, nested_string(config, "fofa", "email"));
        let api_key = first_nonempty(&request.api_key, nested_string(config, "fofa", "api_key"));
        if api_key.is_empty() {
            return Ok(json!({
                "success": false,
                "message": "FOFA API Key 未配置",
                "rows": [],
                "logs": [],
            }));
        }

        let qbase64 = STANDARD.encode(query.as_bytes());
        let response = self.send_with_retry(|| {
            self.client.get(&self.endpoints.fofa_search).query(&[
                ("email", email.as_str()),
                ("key", api_key.as_str()),
                ("qbase64", qbase64.as_str()),
                ("size", &size.to_string()),
                ("page", &page.to_string()),
                ("fields", fields),
            ])
        });

        let raw = match response {
            Ok(response) => fofa_oracle_result(response, query, fields),
            Err(error) => FofaOracleResult::failure(
                format!(
                    "请求异常: {}",
                    sanitize_error(&error, &[api_key.as_str(), email.as_str()])
                ),
                query,
            ),
        };
        let rows = fofa_rows(&raw);
        let success = raw.success;
        let message = if success {
            Value::String(format!(
                "FOFA 查询完成，获得 {} 条结果",
                raw.results.as_deref().unwrap_or_default().len()
            ))
        } else {
            raw.error
                .clone()
                .unwrap_or_else(|| Value::String("FOFA 查询失败".to_string()))
        };
        Ok(json!({
            "success": success,
            "message": message,
            "rows": rows,
            "raw": raw,
            "logs": [],
        }))
    }

    fn hunter(&self, payload: &Value, config: &Value) -> Result<Value, String> {
        let request: HunterRequest = parse_payload(payload)?;
        let query = required_query(&request.query, "请输入 Hunter 查询语句")?;
        let page = request.page.clamp(1, 10_000);
        let page_size = request
            .page_size
            .as_ref()
            .and_then(python_i64)
            .unwrap_or(request.size)
            .clamp(1, 100);
        let api_key = first_nonempty(&request.api_key, nested_string(config, "hunter", "api_key"));
        if api_key.is_empty() {
            return Ok(json!({
                "success": false,
                "message": "Hunter API Key 未配置",
                "rows": [],
                "logs": [],
            }));
        }

        let search = URL_SAFE.encode(query.as_bytes());
        let page_text = page.to_string();
        let page_size_text = page_size.to_string();
        let is_web_text = request.is_web.clamp(1, 3).to_string();
        let port_filter_text = if request.port_filter { "True" } else { "False" };
        let response = self.send_with_retry(|| {
            let mut params = vec![
                ("api-key", api_key.as_str()),
                ("search", search.as_str()),
                ("page", page_text.as_str()),
                ("page_size", page_size_text.as_str()),
                ("is_web", is_web_text.as_str()),
                ("port_filter", port_filter_text),
            ];
            for (key, value) in [
                ("start_time", request.start_time.trim()),
                ("end_time", request.end_time.trim()),
                ("fields", request.fields.trim()),
            ] {
                if !value.is_empty() {
                    params.push((key, value));
                }
            }
            self.client
                .get(&self.endpoints.hunter_search)
                .query(&params)
        });

        let response = match response {
            Ok(response) => response,
            Err(error) => {
                return Ok(json!({
                    "success": false,
                    "message": format!("Hunter 查询失败: {}", sanitize_error(&error, &[api_key.as_str()])),
                    "rows": [],
                    "logs": [],
                }));
            }
        };
        let status = response.status;
        let raw = if response.is_json_content_type {
            response
                .json
                .unwrap_or_else(|| json!({"message": response.body}))
        } else {
            json!({"message": response.body})
        };
        let api: HunterApiResponse = serde_json::from_value(raw.clone()).unwrap_or_default();
        let success = status == StatusCode::OK.as_u16() && hunter_code_success(api.code.as_ref());
        let rows = hunter_rows(&api);
        let message = if success {
            Value::String(format!("Hunter 查询完成，获得 {} 条结果", rows.len()))
        } else {
            raw.get("message")
                .cloned()
                .unwrap_or_else(|| Value::String(format!("HTTP {status}")))
        };
        Ok(json!({
            "success": success,
            "message": message,
            "rows": rows,
            "query_count": 1,
            "raw": raw,
            "logs": [],
        }))
    }

    fn quake(&self, payload: &Value, config: &Value) -> Result<Value, String> {
        let request: QuakeRequest = parse_payload(payload)?;
        let query = required_query(&request.query, "请输入 Quake 查询语句")?;
        let size = request.size.clamp(1, 10_000);
        let start = request.start.clamp(0, 1_000_000);
        let api_key = first_nonempty(&request.api_key, nested_string(config, "quake", "api_key"));
        if api_key.is_empty() {
            return Ok(json!({
                "success": false,
                "message": "Quake API Key 未配置",
                "rows": [],
                "logs": [],
            }));
        }

        let body = QuakeSearchBody {
            query: query.clone(),
            start,
            size,
        };
        let response = self.send_with_retry(|| {
            self.client
                .post(&self.endpoints.quake_search)
                .header("X-QuakeToken", &api_key)
                .json(&body)
        });
        let raw = match response {
            Ok(response) => quake_oracle_result(response, query),
            Err(error) => QuakeOracleResult::failure(
                format!("请求异常: {}", sanitize_error(&error, &[api_key.as_str()])),
                query,
            ),
        };
        let rows = quake_rows(&raw.data);
        let success = raw.success;
        let message = if success {
            Value::String(format!("Quake 查询完成，获得 {} 条结果", rows.len()))
        } else {
            Value::String(
                raw.error
                    .as_ref()
                    .map(python_string)
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or_else(|| "Quake 查询失败".to_string()),
            )
        };
        Ok(json!({
            "success": success,
            "message": message,
            "rows": rows,
            "raw": raw,
            "logs": [],
        }))
    }

    fn unified(&self, payload: &Value, config: &Value) -> Result<Value, String> {
        let request: UnifiedRequest = parse_payload(payload)?;
        let batch_file = if request.batch_file.is_empty() {
            request.file_path
        } else {
            request.batch_file
        };
        let mut queries = if !batch_file.trim().is_empty() {
            read_lines_file(Path::new(batch_file.trim()))?
        } else if let Some(queries) = request.queries {
            queries
        } else if request.query.trim().is_empty() {
            Vec::new()
        } else {
            vec![request.query.trim().to_string()]
        };
        let mut seen = HashSet::new();
        queries.retain(|query| seen.insert(query.clone()));
        if queries.is_empty() {
            return Err("请输入查询语句或选择批量文件".to_string());
        }

        let mut rows = Vec::new();
        let mut logs = Vec::new();
        let mut errors = Vec::new();
        for query in queries {
            let mut query_payload = payload.as_object().cloned().unwrap_or_default();
            query_payload.insert("query".to_string(), Value::String(query.clone()));
            let query_payload = Value::Object(query_payload);
            for platform in &request.platforms.0 {
                let result = match platform.normalized.as_str() {
                    "fofa" => self.fofa(&query_payload, config),
                    "hunter" => self.hunter(&query_payload, config),
                    "quake" => self.quake(&query_payload, config),
                    _ => continue,
                };
                let result = match result {
                    Ok(result) => result,
                    Err(error) => {
                        errors.push(format!("{query} / {}: {error}", platform.display));
                        continue;
                    }
                };
                if let Some(result_logs) = result.get("logs").and_then(Value::as_array) {
                    logs.extend(result_logs.iter().cloned());
                }
                if !result.get("success").is_some_and(python_truthy) {
                    let message = result
                        .get("message")
                        .map(python_display)
                        .unwrap_or_else(|| "None".to_string());
                    errors.push(format!("{query} / {}: {message}", platform.display));
                }
                if let Some(result_rows) = result.get("rows").and_then(Value::as_array) {
                    for row in result_rows {
                        let Some(row) = row.as_object() else {
                            errors.push(format!(
                                "{query} / {}: 查询结果行不是对象",
                                platform.display
                            ));
                            break;
                        };
                        let mut merged = Map::new();
                        merged.insert("query".to_string(), Value::String(query.clone()));
                        merged.insert("platform".to_string(), platform.output.clone());
                        merged.extend(row.clone());
                        rows.push(Value::Object(merged));
                    }
                }
            }
        }
        let success = errors.is_empty();
        let message = if success {
            format!("统一查询完成，获得 {} 条结果", rows.len())
        } else {
            format!("统一查询部分失败: {}", errors.join("，"))
        };
        Ok(json!({
            "success": success,
            "message": message,
            "rows": rows,
            "logs": logs,
            "errors": errors,
        }))
    }

    fn send_with_retry<F>(&self, build: F) -> Result<HttpResponse, String>
    where
        F: Fn() -> RequestBuilder,
    {
        let attempts = self.retry.max_attempts.max(1);
        let mut last_error = None;
        for attempt in 0..attempts {
            if self.cancellation.is_cancelled() {
                return Err("request cancelled".to_string());
            }
            match build().timeout(self.retry.request_timeout).send() {
                Ok(response) if retryable_status(response.status()) && attempt + 1 < attempts => {
                    last_error = Some(format!("HTTP {}", response.status().as_u16()));
                }
                Ok(response) => return read_response(response, self.retry.max_response_bytes),
                Err(error)
                    if (error.is_timeout() || error.is_connect()) && attempt + 1 < attempts =>
                {
                    last_error = Some(error.to_string());
                }
                Err(error) => return Err(error.to_string()),
            }
            let multiplier = 1_u32 << u32::from(attempt.min(6));
            let delay = self.retry.initial_backoff.saturating_mul(multiplier);
            self.wait_interruptibly(delay)?;
        }
        Err(last_error.unwrap_or_else(|| "request failed".to_string()))
    }

    fn wait_interruptibly(&self, duration: Duration) -> Result<(), String> {
        let deadline = Instant::now() + duration;
        loop {
            if self.cancellation.is_cancelled() {
                return Err("request cancelled".to_string());
            }
            let now = Instant::now();
            if now >= deadline {
                return Ok(());
            }
            thread::sleep((deadline - now).min(Duration::from_millis(50)));
        }
    }
}

pub fn dispatch(command: &str, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
    let persisted = config.load()?;
    AssetQueryService::production()?.dispatch(command, payload, &persisted)
}

#[derive(Debug, Deserialize)]
struct FofaRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    query: String,
    #[serde(default = "default_page", deserialize_with = "deserialize_python_i64")]
    page: i64,
    #[serde(default = "default_size", deserialize_with = "deserialize_python_size")]
    size: i64,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    fields: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    email: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    api_key: String,
}

#[derive(Debug, Deserialize)]
struct HunterRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    query: String,
    #[serde(default = "default_page", deserialize_with = "deserialize_python_i64")]
    page: i64,
    #[serde(default = "default_size", deserialize_with = "deserialize_python_size")]
    size: i64,
    #[serde(default)]
    page_size: Option<Value>,
    #[serde(
        default = "default_is_web",
        deserialize_with = "deserialize_python_is_web"
    )]
    is_web: i64,
    #[serde(default, deserialize_with = "deserialize_python_bool")]
    port_filter: bool,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    start_time: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    end_time: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    fields: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    api_key: String,
}

#[derive(Debug, Deserialize)]
struct QuakeRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    query: String,
    #[serde(default = "default_size", deserialize_with = "deserialize_python_size")]
    size: i64,
    #[serde(default, deserialize_with = "deserialize_python_i64")]
    start: i64,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    api_key: String,
}

#[derive(Debug, Deserialize)]
struct UnifiedRequest {
    #[serde(default)]
    platforms: UnifiedPlatforms,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    query: String,
    #[serde(default, deserialize_with = "deserialize_optional_string_list")]
    queries: Option<Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    batch_file: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    file_path: String,
}

#[derive(Debug)]
struct UnifiedPlatforms(Vec<PlatformChoice>);

impl Default for UnifiedPlatforms {
    fn default() -> Self {
        Self(default_platforms())
    }
}

impl<'de> Deserialize<'de> for UnifiedPlatforms {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        if !python_truthy(&value) {
            return Ok(Self::default());
        }
        let choices = match value {
            Value::Array(values) => values
                .into_iter()
                .map(PlatformChoice::from_list_item)
                .collect(),
            value => vec![PlatformChoice::from_single_value(value)],
        };
        Ok(Self(choices))
    }
}

#[derive(Debug)]
struct PlatformChoice {
    output: Value,
    display: String,
    normalized: String,
}

impl PlatformChoice {
    fn from_list_item(value: Value) -> Self {
        let display = python_display(&value);
        Self {
            output: value,
            normalized: display.to_lowercase(),
            display,
        }
    }

    fn from_single_value(value: Value) -> Self {
        let display = python_display(&value);
        Self {
            output: Value::String(display.clone()),
            normalized: display.to_lowercase(),
            display,
        }
    }
}

fn default_platforms() -> Vec<PlatformChoice> {
    ["fofa", "hunter", "quake"]
        .into_iter()
        .map(|platform| PlatformChoice {
            output: Value::String(platform.to_string()),
            display: platform.to_string(),
            normalized: platform.to_string(),
        })
        .collect()
}

#[derive(Debug, Serialize)]
struct QuakeSearchBody {
    query: String,
    start: i64,
    size: i64,
}

#[derive(Debug, Clone, Serialize)]
struct FofaOracleResult {
    success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    results: Option<Vec<Map<String, Value>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    size: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
    query: String,
}

impl FofaOracleResult {
    fn failure(error: String, query: String) -> Self {
        Self {
            success: false,
            results: None,
            size: None,
            total: None,
            error: Some(Value::String(error)),
            query,
        }
    }

    fn failure_value(error: Value, query: String) -> Self {
        Self {
            success: false,
            results: None,
            size: None,
            total: None,
            error: Some(error),
            query,
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct HunterApiResponse {
    #[serde(default)]
    code: Option<Value>,
    #[serde(default)]
    data: Option<HunterData>,
}

#[derive(Debug, Default, Deserialize)]
struct HunterData {
    #[serde(default)]
    arr: Option<Vec<Value>>,
}

#[derive(Debug, Default, Deserialize, Serialize)]
struct HunterAsset {
    #[serde(default)]
    url: Value,
    #[serde(default)]
    domain: Value,
    #[serde(default)]
    ip: Value,
    #[serde(default)]
    port: Value,
    #[serde(default)]
    web_title: Value,
    #[serde(default)]
    title: Value,
    #[serde(default)]
    company: Value,
    #[serde(default)]
    status_code: Value,
    #[serde(default)]
    web: Option<HunterWeb>,
    #[serde(flatten)]
    extra: Map<String, Value>,
}

#[derive(Debug, Default, Deserialize, Serialize)]
struct HunterWeb {
    #[serde(default)]
    url: Value,
    #[serde(default)]
    title: Value,
    #[serde(default)]
    status_code: Value,
    #[serde(flatten)]
    extra: Map<String, Value>,
}

#[derive(Debug, Serialize)]
struct AssetRow {
    index: usize,
    #[serde(flatten)]
    fields: Map<String, Value>,
    raw: Value,
}

#[derive(Debug, Serialize)]
struct QuakeOracleResult {
    success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
    query: String,
}

impl QuakeOracleResult {
    fn failure(error: String, query: String) -> Self {
        Self {
            success: false,
            data: None,
            total: None,
            error: Some(Value::String(error)),
            query,
        }
    }
}

struct HttpResponse {
    status: u16,
    body: String,
    json: Option<Value>,
    is_json_content_type: bool,
}

fn read_response(mut response: Response, max_bytes: usize) -> Result<HttpResponse, String> {
    if response
        .content_length()
        .is_some_and(|length| length > max_bytes as u64)
    {
        return Err(format!("response exceeds {max_bytes} byte limit"));
    }
    let status = response.status().as_u16();
    let is_json_content_type = response
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.starts_with("application/json"));
    let mut bytes = Vec::new();
    response
        .by_ref()
        .take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("read response failed: {error}"))?;
    if bytes.len() > max_bytes {
        return Err(format!("response exceeds {max_bytes} byte limit"));
    }
    let body = String::from_utf8_lossy(&bytes).into_owned();
    let parsed = serde_json::from_slice(&bytes).ok();
    Ok(HttpResponse {
        status,
        body,
        json: parsed,
        is_json_content_type,
    })
}

fn retryable_status(status: StatusCode) -> bool {
    status == StatusCode::TOO_MANY_REQUESTS || matches!(status.as_u16(), 500 | 502 | 503 | 504)
}

fn fofa_oracle_result(response: HttpResponse, query: String, fields: &str) -> FofaOracleResult {
    if response.status != StatusCode::OK.as_u16() {
        return FofaOracleResult::failure(
            format!("HTTP {}: {}", response.status, response.body),
            query,
        );
    }
    let Some(value) = response.json else {
        return FofaOracleResult::failure("请求异常: invalid JSON response".to_string(), query);
    };
    let api: FofaApiResponse = match serde_json::from_value(value) {
        Ok(api) => api,
        Err(error) => {
            return FofaOracleResult::failure(format!("请求异常: {error}"), query);
        }
    };
    if python_truthy(&api.error) {
        return FofaOracleResult::failure_value(api.errmsg, query);
    }
    let field_list: Vec<&str> = fields.split(',').collect();
    let results = api
        .results
        .unwrap_or_default()
        .into_iter()
        .filter(|item| item.len() >= field_list.len())
        .map(|item| {
            field_list
                .iter()
                .enumerate()
                .map(|(index, field)| ((*field).to_string(), item[index].clone()))
                .collect()
        })
        .collect();
    let size = api.size;
    FofaOracleResult {
        success: true,
        results: Some(results),
        size: Some(size.clone()),
        total: Some(size),
        error: None,
        query,
    }
}

#[derive(Debug, Default, Deserialize)]
struct FofaApiResponse {
    #[serde(default)]
    error: Value,
    #[serde(default = "default_unknown_error")]
    errmsg: Value,
    #[serde(default)]
    results: Option<Vec<Vec<Value>>>,
    #[serde(default = "default_zero_value")]
    size: Value,
}

fn fofa_rows(raw: &FofaOracleResult) -> Vec<AssetRow> {
    raw.results
        .as_deref()
        .unwrap_or_default()
        .iter()
        .enumerate()
        .map(|(index, item)| {
            let mut fields = Map::new();
            for key in ["host", "ip", "port", "title", "country", "protocol"] {
                fields.insert(
                    key.to_string(),
                    item.get(key).cloned().unwrap_or_else(empty_string),
                );
            }
            AssetRow {
                index: index + 1,
                fields,
                raw: Value::Object(item.clone()),
            }
        })
        .collect()
}

fn hunter_code_success(code: Option<&Value>) -> bool {
    match code {
        None | Some(Value::Null) => true,
        Some(Value::Number(value)) => value.as_i64() == Some(200),
        Some(Value::String(value)) => value == "200",
        _ => false,
    }
}

fn hunter_rows(api: &HunterApiResponse) -> Vec<AssetRow> {
    api.data
        .as_ref()
        .map(|data| {
            data.arr
                .as_deref()
                .unwrap_or_default()
                .iter()
                .enumerate()
                .filter_map(|(index, raw)| {
                    let item: HunterAsset = serde_json::from_value(raw.clone()).ok()?;
                    let web = item.web.as_ref();
                    let mut fields = Map::new();
                    fields.insert(
                        "url".to_string(),
                        first_truthy_value([
                            &item.url,
                            web.map(|value| &value.url).unwrap_or(&Value::Null),
                            &item.domain,
                        ]),
                    );
                    fields.insert("ip".to_string(), or_empty(&item.ip));
                    fields.insert("port".to_string(), or_empty(&item.port));
                    fields.insert(
                        "title".to_string(),
                        first_truthy_value([
                            &item.web_title,
                            web.map(|value| &value.title).unwrap_or(&Value::Null),
                            &item.title,
                        ]),
                    );
                    fields.insert("company".to_string(), or_empty(&item.company));
                    fields.insert(
                        "status_code".to_string(),
                        first_truthy_value([
                            &item.status_code,
                            web.map(|value| &value.status_code).unwrap_or(&Value::Null),
                        ]),
                    );
                    Some(AssetRow {
                        index: index + 1,
                        fields,
                        raw: raw.clone(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn quake_oracle_result(response: HttpResponse, query: String) -> QuakeOracleResult {
    if response.status != StatusCode::OK.as_u16() {
        return QuakeOracleResult::failure(
            format!("HTTP {}: {}", response.status, response.body),
            query,
        );
    }
    let Some(value) = response.json else {
        return QuakeOracleResult::failure("请求异常: invalid JSON response".to_string(), query);
    };
    let api: QuakeApiResponse = match serde_json::from_value(value) {
        Ok(api) => api,
        Err(error) => {
            return QuakeOracleResult::failure(format!("请求异常: {error}"), query);
        }
    };
    QuakeOracleResult {
        success: true,
        data: Some(api.data),
        total: Some(api.meta.map(|meta| meta.total).unwrap_or_else(|| json!(0))),
        error: None,
        query,
    }
}

#[derive(Debug, Default, Deserialize)]
struct QuakeApiResponse {
    #[serde(default = "default_empty_array")]
    data: Value,
    #[serde(default)]
    meta: Option<QuakeMeta>,
}

#[derive(Debug, Default, Deserialize)]
struct QuakeMeta {
    #[serde(default = "default_zero_value")]
    total: Value,
}

fn quake_rows(items: &Option<Value>) -> Vec<AssetRow> {
    items
        .as_ref()
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .enumerate()
        .filter_map(|(index, raw)| {
            let item = raw.as_object()?;
            let service = item.get("service").filter(|value| python_truthy(value));
            let service = match service {
                Some(Value::Object(value)) => value.get("name").cloned().unwrap_or(Value::Null),
                Some(value) => value.clone(),
                None => Value::Null,
            };
            let web_title = item
                .get("web")
                .and_then(Value::as_object)
                .and_then(|web| web.get("title"));
            let mut fields = Map::new();
            fields.insert("ip".to_string(), value_or_empty(item.get("ip")));
            fields.insert("port".to_string(), value_or_empty(item.get("port")));
            fields.insert(
                "hostname".to_string(),
                first_truthy_option([item.get("hostname"), item.get("domain")]),
            );
            fields.insert("service".to_string(), service);
            fields.insert(
                "title".to_string(),
                first_truthy_option([item.get("title"), web_title]),
            );
            fields.insert(
                "location".to_string(),
                item.get("location")
                    .cloned()
                    .unwrap_or_else(|| Value::Object(Map::new())),
            );
            fields.insert("org".to_string(), value_or_empty(item.get("org")));
            Some(AssetRow {
                index: index + 1,
                fields,
                raw: raw.clone(),
            })
        })
        .collect()
}

fn parse_payload<T>(payload: &Value) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn required_query(value: &str, message: &str) -> Result<String, String> {
    let value = value.trim();
    if value.is_empty() {
        Err(message.to_string())
    } else {
        Ok(value.to_string())
    }
}

fn nested_string(config: &Value, section: &str, key: &str) -> String {
    config
        .get(section)
        .and_then(|value| value.get(key))
        .map(python_or_empty)
        .unwrap_or_default()
}

fn first_nonempty(primary: &str, fallback: String) -> String {
    if primary.is_empty() {
        fallback
    } else {
        primary.to_string()
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn python_display(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(false) => false,
        Value::Number(value) => value.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
        Value::Bool(true) => true,
    }
}

fn empty_string() -> Value {
    Value::String(String::new())
}

fn or_empty(value: &Value) -> Value {
    if python_truthy(value) {
        value.clone()
    } else {
        empty_string()
    }
}

fn value_or_empty(value: Option<&Value>) -> Value {
    value.map(or_empty).unwrap_or_else(empty_string)
}

fn first_truthy_value<const N: usize>(values: [&Value; N]) -> Value {
    values
        .into_iter()
        .find(|value| python_truthy(value))
        .cloned()
        .unwrap_or_else(empty_string)
}

fn first_truthy_option<const N: usize>(values: [Option<&Value>; N]) -> Value {
    values
        .into_iter()
        .flatten()
        .find(|value| python_truthy(value))
        .cloned()
        .unwrap_or_else(empty_string)
}

fn default_page() -> i64 {
    1
}

fn default_size() -> i64 {
    100
}

fn default_is_web() -> i64 {
    3
}

fn default_unknown_error() -> Value {
    Value::String("未知错误".to_string())
}

fn default_zero_value() -> Value {
    json!(0)
}

fn default_empty_array() -> Value {
    Value::Array(Vec::new())
}

fn deserialize_python_or_empty<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Value::deserialize(deserializer).map(|value| python_or_empty(&value))
}

fn python_or_empty(value: &Value) -> String {
    if python_truthy(value) {
        python_string(value)
    } else {
        String::new()
    }
}

fn deserialize_python_i64<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(python_i64(&value).unwrap_or_default())
}

fn deserialize_python_size<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(python_i64(&value).unwrap_or_else(default_size))
}

fn deserialize_python_is_web<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(python_i64(&value).unwrap_or_else(default_is_web))
}

fn deserialize_python_bool<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Value::deserialize(deserializer).map(|value| python_truthy(&value))
}

fn deserialize_optional_string_list<'de, D>(
    deserializer: D,
) -> Result<Option<Vec<String>>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    let Value::Array(values) = value else {
        return Ok(None);
    };
    Ok(Some(
        values
            .iter()
            .map(python_display)
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .collect(),
    ))
}

fn python_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_u64().and_then(|value| i64::try_from(value).ok()))
            .or_else(|| value.as_f64().map(|value| value.trunc() as i64)),
        Value::String(value) => value.trim().parse::<i64>().ok(),
        Value::Bool(value) => Some(i64::from(*value)),
        _ => None,
    }
}

fn sanitize_error(error: &str, secrets: &[&str]) -> String {
    secrets
        .iter()
        .filter(|secret| !secret.is_empty())
        .fold(error.to_string(), |message, secret| {
            message.replace(secret, "[REDACTED]")
        })
}

fn asset_secrets(payload: &Value, config: &Value) -> Vec<String> {
    let mut secrets = Vec::new();
    for value in [
        payload.get("api_key"),
        payload.get("email"),
        config.get("fofa").and_then(|value| value.get("api_key")),
        config.get("fofa").and_then(|value| value.get("email")),
        config.get("hunter").and_then(|value| value.get("api_key")),
        config.get("quake").and_then(|value| value.get("api_key")),
    ]
    .into_iter()
    .flatten()
    {
        let secret = python_or_empty(value);
        if !secret.is_empty() && !secrets.contains(&secret) {
            secrets.push(secret);
        }
    }
    secrets
}

fn sanitize_error_owned(mut error: String, secrets: &[String]) -> String {
    for secret in secrets {
        error = error.replace(secret, "[REDACTED]");
    }
    error
}

fn redact_secret_value(value: &mut Value, secrets: &[String]) {
    if secrets.is_empty() {
        return;
    }
    match value {
        Value::String(value) => {
            *value = sanitize_error_owned(std::mem::take(value), secrets);
        }
        Value::Array(values) => {
            for value in values {
                redact_secret_value(value, secrets);
            }
        }
        Value::Object(values) => {
            let original = std::mem::take(values);
            for (key, mut value) in original {
                redact_secret_value(&mut value, secrets);
                values.insert(sanitize_error_owned(key, secrets), value);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::sync::mpsc;

    #[derive(Clone)]
    struct MockReply {
        status: u16,
        content_type: &'static str,
        body: &'static str,
    }

    fn mock_server(
        replies: Vec<MockReply>,
    ) -> (String, mpsc::Receiver<String>, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock server");
        let address = listener.local_addr().expect("mock address");
        let (sender, receiver) = mpsc::channel();
        let handle = thread::spawn(move || {
            for reply in replies {
                let (mut stream, _) = listener.accept().expect("accept mock request");
                let request = read_request(&mut stream);
                let _ = sender.send(request);
                let reason = if reply.status == 200 {
                    "OK"
                } else {
                    "Service Unavailable"
                };
                let response = format!(
                    "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    reply.status,
                    reason,
                    reply.content_type,
                    reply.body.len(),
                    reply.body
                );
                stream
                    .write_all(response.as_bytes())
                    .expect("write mock response");
            }
        });
        (format!("http://{address}"), receiver, handle)
    }

    fn read_request(stream: &mut TcpStream) -> String {
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .expect("set mock timeout");
        let mut bytes = Vec::new();
        let mut buffer = [0_u8; 4096];
        let mut expected = None;
        loop {
            let read = stream.read(&mut buffer).expect("read mock request");
            if read == 0 {
                break;
            }
            bytes.extend_from_slice(&buffer[..read]);
            if expected.is_none() {
                if let Some(header_end) = find_bytes(&bytes, b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..header_end]);
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("content-length: ")
                                .or_else(|| line.strip_prefix("Content-Length: "))
                        })
                        .and_then(|value| value.parse::<usize>().ok())
                        .unwrap_or(0);
                    expected = Some(header_end + 4 + length);
                }
            }
            if expected.is_some_and(|length| bytes.len() >= length) {
                break;
            }
        }
        String::from_utf8(bytes).expect("mock request must be utf8")
    }

    fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
        haystack
            .windows(needle.len())
            .position(|window| window == needle)
    }

    fn service(base: &str, attempts: u8, max_response_bytes: usize) -> AssetQueryService {
        AssetQueryService::new(
            AssetEndpoints {
                fofa_search: format!("{base}/fofa"),
                hunter_search: format!("{base}/hunter"),
                quake_search: format!("{base}/quake"),
            },
            RetryPolicy {
                max_attempts: attempts,
                initial_backoff: Duration::ZERO,
                request_timeout: Duration::from_secs(2),
                max_response_bytes,
            },
            CancellationToken::new(),
        )
        .expect("create test service")
    }

    #[test]
    fn fofa_matches_python_oracle_shape_and_encoding() {
        let (base, requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "application/json",
            body: r#"{"error":false,"size":1,"results":[["https://a.test","1.2.3.4",443,"Portal","CN","https"]]}"#,
        }]);
        let result = service(&base, 1, 4096)
            .dispatch(
                FOFA_COMMAND,
                &json!({"query":"title=\"门户\"","api_key":"secret","email":"a@example.test"}),
                &json!({}),
            )
            .expect("FOFA query");
        assert_eq!(
            result,
            json!({
                "success": true,
                "message": "FOFA 查询完成，获得 1 条结果",
                "rows": [{
                    "index": 1,
                    "host": "https://a.test",
                    "ip": "1.2.3.4",
                    "port": 443,
                    "title": "Portal",
                    "country": "CN",
                    "protocol": "https",
                    "raw": {
                        "host": "https://a.test",
                        "ip": "1.2.3.4",
                        "port": 443,
                        "title": "Portal",
                        "country": "CN",
                        "protocol": "https"
                    }
                }],
                "raw": {
                    "success": true,
                    "results": [{
                        "host": "https://a.test",
                        "ip": "1.2.3.4",
                        "port": 443,
                        "title": "Portal",
                        "country": "CN",
                        "protocol": "https"
                    }],
                    "size": 1,
                    "total": 1,
                    "query": "title=\"门户\""
                },
                "logs": []
            })
        );
        let request = requests.recv().expect("FOFA request");
        assert!(request.starts_with("GET /fofa?"));
        assert!(request.contains("key=secret"));
        assert!(request.contains("qbase64=dGl0bGU9IumXqOaItyI%3D"));
        server.join().expect("FOFA server");
    }

    #[test]
    fn hunter_retries_transient_status_and_matches_python_rows() {
        let (base, requests, server) = mock_server(vec![
            MockReply {
                status: 503,
                content_type: "text/plain",
                body: "busy",
            },
            MockReply {
                status: 200,
                content_type: "application/json; charset=utf-8",
                body: r#"{"code":200,"message":"ok","data":{"arr":[{"ip":"2.3.4.5","port":8443,"web":{"url":"https://b.test","title":"Console","status_code":200},"company":"Example"}]}}"#,
            },
        ]);
        let result = service(&base, 3, 4096)
            .dispatch(
                HUNTER_COMMAND,
                &json!({"query":"ip=\"2.3.4.5\"","api_key":"hunter-key","size":500,"port_filter":true}),
                &json!({}),
            )
            .expect("Hunter query");
        assert_eq!(result["success"], true);
        assert_eq!(result["message"], "Hunter 查询完成，获得 1 条结果");
        assert_eq!(result["rows"][0]["url"], "https://b.test");
        assert_eq!(result["rows"][0]["title"], "Console");
        assert_eq!(result["rows"][0]["status_code"], 200);
        assert_eq!(result["query_count"], 1);
        let first = requests.recv().expect("first Hunter request");
        let second = requests.recv().expect("retried Hunter request");
        for request in [&first, &second] {
            assert!(request.starts_with("GET /hunter?"));
            assert!(request.contains("api-key=hunter-key"));
            assert!(request.contains("page_size=100"));
            assert!(request.contains("port_filter=True"));
        }
        server.join().expect("Hunter server");
    }

    #[test]
    fn quake_sends_typed_json_and_auth_header() {
        let (base, requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "application/json",
            body: r#"{"data":[{"ip":"5.6.7.8","port":443,"domain":"c.test","service":{"name":"https"},"web":{"title":"Home"},"location":{"country_cn":"中国"},"org":"Example"}],"meta":{"total":9}}"#,
        }]);
        let result = service(&base, 1, 4096)
            .dispatch(
                QUAKE_COMMAND,
                &json!({"query":"domain:\"c.test\"","api_key":"quake-key","size":20,"start":3}),
                &json!({}),
            )
            .expect("Quake query");
        assert_eq!(result["success"], true);
        assert_eq!(result["message"], "Quake 查询完成，获得 1 条结果");
        assert_eq!(result["rows"][0]["hostname"], "c.test");
        assert_eq!(result["rows"][0]["service"], "https");
        assert_eq!(result["raw"]["total"], 9);
        let request = requests.recv().expect("Quake request");
        assert!(request.starts_with("POST /quake HTTP/1.1"));
        assert!(request
            .to_ascii_lowercase()
            .contains("x-quaketoken: quake-key"));
        assert!(request.contains(r#"{"query":"domain:\"c.test\"","start":3,"size":20}"#));
        server.join().expect("Quake server");
    }

    #[test]
    fn unified_query_matches_python_orchestration_shape() {
        let (base, requests, server) = mock_server(vec![
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"error":false,"size":1,"results":[["https://a.test","1.2.3.4",443,"Portal","CN","https"]]}"#,
            },
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"code":200,"data":{"arr":[{"ip":"2.3.4.5","port":8443,"domain":"b.test"}]}}"#,
            },
        ]);
        let result = service(&base, 1, 4096)
            .dispatch(
                UNIFIED_COMMAND,
                &json!({
                    "query": "title=\"Portal\"",
                    "platforms": ["FOFA", "unknown", "hunter"],
                    "api_key": "shared-key"
                }),
                &json!({}),
            )
            .expect("unified query");
        assert_eq!(result["success"], true);
        assert_eq!(result["message"], "统一查询完成，获得 2 条结果");
        assert_eq!(result["rows"][0]["query"], "title=\"Portal\"");
        assert_eq!(result["rows"][0]["platform"], "FOFA");
        assert_eq!(result["rows"][0]["host"], "https://a.test");
        assert_eq!(result["rows"][1]["platform"], "hunter");
        assert_eq!(result["rows"][1]["url"], "b.test");
        assert_eq!(result["errors"], json!([]));
        assert_eq!(result["logs"], json!([]));
        assert!(requests
            .recv()
            .expect("FOFA request")
            .starts_with("GET /fofa?"));
        assert!(requests
            .recv()
            .expect("Hunter request")
            .starts_with("GET /hunter?"));
        server.join().expect("unified server");

        assert_eq!(
            service("http://127.0.0.1:9", 1, 4096)
                .dispatch(
                    UNIFIED_COMMAND,
                    &json!({"queries": [], "query": "ignored"}),
                    &json!({}),
                )
                .expect_err("explicit empty query list takes precedence"),
            "请输入查询语句或选择批量文件"
        );
    }

    #[test]
    fn python_compatibility_edges_preserve_nulls_and_numeric_coercion() {
        let (base, requests, server) = mock_server(vec![
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"error":true,"errmsg":null}"#,
            },
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"error":false,"size":null,"results":null}"#,
            },
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"data":null,"meta":{"total":null}}"#,
            },
            MockReply {
                status: 200,
                content_type: "application/json",
                body: r#"{"error":false,"size":0,"results":[]}"#,
            },
        ]);
        let query_service = service(&base, 1, 4096);

        let api_error = query_service
            .dispatch(
                FOFA_COMMAND,
                &json!({"query":"one","api_key":"key"}),
                &json!({}),
            )
            .expect("FOFA API error");
        assert_eq!(api_error["success"], false);
        assert_eq!(api_error["message"], Value::Null);
        assert_eq!(api_error["raw"]["error"], Value::Null);

        let null_results = query_service
            .dispatch(
                FOFA_COMMAND,
                &json!({"query":"two","api_key":"key"}),
                &json!({}),
            )
            .expect("FOFA null results");
        assert_eq!(null_results["success"], true);
        assert_eq!(null_results["rows"], json!([]));
        assert_eq!(null_results["raw"]["size"], Value::Null);
        assert_eq!(null_results["raw"]["total"], Value::Null);

        let quake_nulls = query_service
            .dispatch(
                QUAKE_COMMAND,
                &json!({"query":"three","api_key":"key"}),
                &json!({}),
            )
            .expect("Quake null data");
        assert_eq!(quake_nulls["success"], true);
        assert_eq!(quake_nulls["rows"], json!([]));
        assert_eq!(quake_nulls["raw"]["data"], Value::Null);
        assert_eq!(quake_nulls["raw"]["total"], Value::Null);

        query_service
            .dispatch(
                FOFA_COMMAND,
                &json!({
                    "query":"four",
                    "api_key":"key",
                    "page": 2.9,
                    "size": "3.9"
                }),
                &json!({}),
            )
            .expect("FOFA numeric coercion");
        let requests: Vec<String> = (0..4)
            .map(|_| requests.recv().expect("mock request"))
            .collect();
        assert!(requests[3].contains("page=2"));
        assert!(requests[3].contains("size=100"));
        server.join().expect("compatibility server");

        assert_eq!(
            service("http://127.0.0.1:9", 1, 4096)
                .dispatch(
                    FOFA_COMMAND,
                    &json!({"query": false, "api_key": "key"}),
                    &json!({}),
                )
                .expect_err("falsy query"),
            "请输入 FOFA 查询语句"
        );
    }

    #[test]
    fn cancellation_and_response_limit_fail_closed_without_leaking_key() {
        let cancellation = CancellationToken::new();
        cancellation.cancel();
        let cancelled_service = AssetQueryService::new(
            AssetEndpoints::default(),
            RetryPolicy::default(),
            cancellation,
        )
        .expect("cancelled service");
        let result = cancelled_service
            .dispatch(
                FOFA_COMMAND,
                &json!({"query":"ip=\"1.1.1.1\"","api_key":"do-not-leak"}),
                &json!({}),
            )
            .expect("structured cancellation");
        let serialized = result.to_string();
        assert_eq!(result["success"], false);
        assert!(result["message"].as_str().unwrap().contains("cancelled"));
        assert!(!serialized.contains("do-not-leak"));

        let (base, _, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "application/json",
            body: r#"{"data":"01234567890123456789"}"#,
        }]);
        let limited = service(&base, 1, 8)
            .dispatch(
                QUAKE_COMMAND,
                &json!({"query":"ip:\"1.1.1.1\"","api_key":"hidden"}),
                &json!({}),
            )
            .expect("structured size failure");
        assert_eq!(limited["success"], false);
        assert!(limited["message"].as_str().unwrap().contains("byte limit"));
        assert!(!limited.to_string().contains("hidden"));
        server.join().expect("limited server");

        let (base, requests, server) = mock_server(vec![MockReply {
            status: 503,
            content_type: "application/json",
            body: r#"{"message":"retry"}"#,
        }]);
        let retry_cancellation = CancellationToken::new();
        let retry_service = AssetQueryService::new(
            AssetEndpoints {
                fofa_search: format!("{base}/fofa"),
                hunter_search: format!("{base}/hunter"),
                quake_search: format!("{base}/quake"),
            },
            RetryPolicy {
                max_attempts: 2,
                initial_backoff: Duration::from_secs(2),
                request_timeout: Duration::from_secs(2),
                max_response_bytes: 4096,
            },
            retry_cancellation.clone(),
        )
        .expect("retry cancellation service");
        let cancel_thread = thread::spawn(move || {
            thread::sleep(Duration::from_millis(200));
            retry_cancellation.cancel();
        });
        let cancelled_retry = retry_service
            .dispatch(
                HUNTER_COMMAND,
                &json!({"query":"ip=\"1.1.1.1\"","api_key":"retry-secret"}),
                &json!({}),
            )
            .expect("structured retry cancellation");
        cancel_thread.join().expect("retry cancellation thread");
        assert_eq!(cancelled_retry["success"], false);
        assert!(cancelled_retry["message"]
            .as_str()
            .is_some_and(|message| message.contains("cancelled")));
        assert!(!cancelled_retry.to_string().contains("retry-secret"));
        assert!(requests
            .recv()
            .expect("single retry request")
            .contains("/hunter"));
        server.join().expect("retry cancellation server");

        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 400,
            content_type: "application/json",
            body: r#"{"message":"rejected echo-secret"}"#,
        }]);
        let echoed = service(&base, 1, 4096)
            .dispatch(
                HUNTER_COMMAND,
                &json!({"query":"ip=\"1.1.1.1\"","api_key":"echo-secret"}),
                &json!({}),
            )
            .expect("structured API error");
        assert_eq!(echoed["success"], false);
        assert!(echoed.to_string().contains("[REDACTED]"));
        assert!(!echoed.to_string().contains("echo-secret"));
        server.join().expect("echo server");
    }
}
