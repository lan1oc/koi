//! Typed ThreatBook clients and compatibility handlers.
//!
//! The service keeps endpoint injection explicit so unit tests use only a
//! loopback mock. Production registration is handled by the backend registry.

use super::batch_control::CancellationToken;
use super::batch_input::read_lines_file;
use super::config::ConfigStore;
use reqwest::blocking::multipart::{Form, Part};
use reqwest::blocking::{Client, RequestBuilder, Response};
use reqwest::header::{CONTENT_TYPE, USER_AGENT};
use reqwest::StatusCode;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::Read;
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

pub const IP_COMMAND: &str = "info.threatbook.ip";
pub const IP_BATCH_COMMAND: &str = "info.threatbook.ip.batch";
pub const DNS_COMMAND: &str = "info.threatbook.dns";
pub const FILE_REPORT_COMMAND: &str = "info.threatbook.file_report";
pub const FILE_MULTIENGINES_COMMAND: &str = "info.threatbook.file_multiengines";
pub const FILE_UPLOAD_COMMAND: &str = "info.threatbook.file_upload";
pub const TEST_CONNECTION_COMMAND: &str = "info.threatbook.test_connection";

const USER_AGENT_VALUE: &str = "ThreatBook-API-Client/1.0";
const DEFAULT_MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
const MAX_UPLOAD_BYTES: u64 = 100 * 1024 * 1024;

struct CancelableFileReader {
    file: File,
    cancellation: CancellationToken,
}

impl Read for CancelableFileReader {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        if self.cancellation.is_cancelled() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Interrupted,
                "upload cancelled",
            ));
        }
        self.file.read(buffer)
    }
}

#[derive(Debug, Clone)]
pub struct RetryPolicy {
    pub max_attempts: u8,
    pub initial_backoff: Duration,
    pub request_timeout: Duration,
    pub upload_timeout: Duration,
    pub max_response_bytes: usize,
    pub batch_interval: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            initial_backoff: Duration::from_millis(250),
            request_timeout: Duration::from_secs(30),
            upload_timeout: Duration::from_secs(120),
            max_response_bytes: DEFAULT_MAX_RESPONSE_BYTES,
            batch_interval: Duration::from_secs(1),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ThreatBookEndpoints {
    pub ip_reputation: String,
    pub dns: String,
    pub file_report: String,
    pub file_multiengines: String,
    pub file_upload: String,
}

impl Default for ThreatBookEndpoints {
    fn default() -> Self {
        let base = "https://api.threatbook.cn";
        Self {
            ip_reputation: format!("{base}/v3/scene/ip_reputation"),
            dns: format!("{base}/v3/scene/dns"),
            file_report: format!("{base}/v3/file/report"),
            file_multiengines: format!("{base}/v3/file/report/multiengines"),
            file_upload: format!("{base}/v3/file/upload"),
        }
    }
}

#[derive(Clone)]
pub struct ThreatBookService {
    client: Client,
    endpoints: ThreatBookEndpoints,
    retry: RetryPolicy,
    cancellation: CancellationToken,
}

impl ThreatBookService {
    pub fn production(cancellation: CancellationToken) -> Result<Self, String> {
        Self::new(
            ThreatBookEndpoints::default(),
            RetryPolicy::default(),
            cancellation,
        )
    }

    pub fn new(
        endpoints: ThreatBookEndpoints,
        retry: RetryPolicy,
        cancellation: CancellationToken,
    ) -> Result<Self, String> {
        let client = Client::builder()
            // The API key is sent in the query or multipart body. A redirect
            // must be surfaced as a bounded failure rather than replaying the
            // credential at an unreviewed origin.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| format!("创建 ThreatBook HTTP 客户端失败: {error}"))?;
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
        let api_key = config
            .get("threatbook_api_key")
            .map(python_or_empty)
            .unwrap_or_default();
        let result = match command {
            IP_COMMAND => self.ip_command(payload, &api_key),
            IP_BATCH_COMMAND => self.ip_batch_command(payload, &api_key),
            DNS_COMMAND => self.dns_command(payload, &api_key),
            FILE_REPORT_COMMAND => self.file_report_command(payload, &api_key),
            FILE_MULTIENGINES_COMMAND => self.file_multiengines_command(payload, &api_key),
            FILE_UPLOAD_COMMAND => self.file_upload_command(payload, &api_key),
            TEST_CONNECTION_COMMAND => Ok(self.test_connection_command(&api_key)),
            _ => Err(format!("未知 ThreatBook 命令: {command}")),
        };
        result
            .map(|mut value| {
                redact_secret_value(&mut value, &api_key);
                value
            })
            .map_err(|error| sanitize_text(&error, &api_key))
    }

    fn ip_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: IpRequest = parse_payload(payload)?;
        let ip = required_text(&request.ip, "请输入 IP 地址")?;
        let lang = if request.lang.is_empty() {
            "zh"
        } else {
            request.lang.as_str()
        };
        let result = self.query_ip_reputation(&ip, lang, api_key);
        Ok(single_command_response(result, "IP 信誉查询完成"))
    }

    fn dns_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: DnsRequest = parse_payload(payload)?;
        let domain = required_text(&request.domain, "请输入域名")?;
        let (result, logs) = self.query_dns_compromise(&domain, api_key);
        Ok(single_command_response_with_logs(
            result,
            "域名失陷检测完成",
            logs,
        ))
    }

    fn ip_batch_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: BatchIpRequest = parse_payload(payload)?;
        let mut ips = if let Some(values) = request.ips {
            values
        } else {
            request
                .ip_text
                .trim()
                .lines()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .collect()
        };
        let batch_file = if request.batch_file.is_empty() {
            request.file_path
        } else {
            request.batch_file
        };
        let batch_file = batch_file.trim();
        if !batch_file.is_empty() {
            ips.extend(read_lines_file(Path::new(batch_file))?);
        }
        let mut seen = HashSet::new();
        ips.retain(|ip| seen.insert(ip.clone()));
        if ips.is_empty() {
            return Err("请输入或选择 IP 列表".to_string());
        }

        let total = ips.len();
        let mut results = Vec::with_capacity(total);
        let mut logs = Vec::with_capacity(total);
        for (index, ip) in ips.iter().enumerate() {
            logs.push(format!("正在查询第 {}/{total} 个IP: {ip}", index + 1));
            results.push(self.query_ip_reputation(ip, "zh", api_key));
            if index + 1 < total {
                if let Err(error) = self.wait_interruptibly(self.retry.batch_interval) {
                    for (remaining_index, remaining_ip) in ips.iter().enumerate().skip(index + 1) {
                        logs.push(format!(
                            "正在查询第 {}/{total} 个IP: {remaining_ip}",
                            remaining_index + 1
                        ));
                        results.push(json!({"error": error.clone()}));
                    }
                    break;
                }
            }
        }

        let rows: Vec<Value> = results
            .iter()
            .enumerate()
            .map(|(index, item)| {
                json!({
                    "index": index + 1,
                    "ip": ips.get(index).cloned().unwrap_or_else(|| {
                        item.get("ip")
                            .or_else(|| item.get("resource"))
                            .map(python_or_empty)
                            .unwrap_or_default()
                    }),
                    "success": !contains_error(item),
                    "raw": item,
                })
            })
            .collect();
        let failed = results.iter().filter(|item| contains_error(item)).count();
        let message = if failed == 0 {
            format!("批量查询完成: {} 个 IP", results.len())
        } else {
            format!("批量查询完成，{failed} 个失败")
        };
        Ok(json!({
            "success": failed == 0,
            "message": message,
            "rows": rows,
            "results": results,
            "logs": logs,
        }))
    }

    fn file_report_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: FileResourceRequest = parse_payload(payload)?;
        let resource = required_text(&request.resource, "请输入文件哈希或 scan_id")?;
        let resource_type = normalized_default(&request.resource_type, "sha256", true);
        let result = self.query_file_report(&resource, &resource_type, api_key);
        Ok(single_command_response(result, "文件报告查询完成"))
    }

    fn file_multiengines_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: FileResourceRequest = parse_payload(payload)?;
        let resource = required_text(&request.resource, "请输入文件哈希")?;
        let resource_type = normalized_default(&request.resource_type, "sha256", true);
        let result = self.query_file_multiengines(&resource, &resource_type, api_key);
        Ok(single_command_response(result, "多引擎检测完成"))
    }

    fn file_upload_command(&self, payload: &Value, api_key: &str) -> Result<Value, String> {
        let request: FileUploadRequest = parse_payload(payload)?;
        let file_path = required_text(&request.file_path, "请选择要上传分析的文件")?;
        let sandbox_type =
            normalized_default(&request.sandbox_type, "win7_sp1_enx86_office2013", false);
        let run_time = request.run_time.clamp(30, 300);
        let (result, logs) = self.upload_file(
            Path::new(&file_path),
            &file_path,
            &sandbox_type,
            run_time,
            api_key,
        );
        Ok(single_command_response_with_logs(
            result,
            "文件上传分析完成",
            logs,
        ))
    }

    fn test_connection_command(&self, api_key: &str) -> Value {
        let result = if api_key.is_empty() {
            json!({"success": false, "message": "API密钥未设置"})
        } else {
            let query = self.query_ip_reputation("8.8.8.8", "zh", api_key);
            if contains_error(&query) {
                json!({
                    "success": false,
                    "message": query.get("error").cloned().unwrap_or(Value::Null),
                })
            } else {
                json!({"success": true, "message": "API连接正常"})
            }
        };
        let success = result
            .get("success")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let message = result
            .get("message")
            .filter(|value| python_truthy(value))
            .map(python_string)
            .unwrap_or_else(|| {
                if success {
                    "连接测试完成".to_string()
                } else {
                    "连接测试失败".to_string()
                }
            });
        json!({
            "success": success,
            "message": message,
            "result": result,
            "logs": [],
        })
    }

    fn query_ip_reputation(&self, ip: &str, lang: &str, api_key: &str) -> Value {
        let raw = match self.get_json(
            &self.endpoints.ip_reputation,
            &[("resource", ip), ("lang", lang)],
            api_key,
        ) {
            Ok(raw) => raw,
            Err(error) => return json!({"error": error}),
        };
        if contains_error(&raw) {
            return raw;
        }
        format_ip_result(ip, raw).unwrap_or_else(|error| json!({"error": error}))
    }

    fn query_dns_compromise(&self, domain: &str, api_key: &str) -> (Value, Vec<String>) {
        let raw = match self.get_json(&self.endpoints.dns, &[("resource", domain)], api_key) {
            Ok(raw) => raw,
            Err(error) => json!({"error": error}),
        };
        let mut logs = debug_json_lines("[DEBUG] DNS API调用结果: ", &raw);
        if contains_error(&raw) {
            return (raw, logs);
        }
        let data = raw.get("data").cloned().unwrap_or_else(empty_object);
        logs.extend(debug_json_lines("[DEBUG] v3 API返回的data数据: ", &data));
        let domain_info = data
            .get("domains")
            .and_then(|domains| domains.get(domain))
            .cloned()
            .unwrap_or_else(empty_object);
        logs.extend(debug_json_lines(
            &format!("[DEBUG] 域名 {domain} 的信息: "),
            &domain_info,
        ));
        let result = format_dns_result(domain, raw).unwrap_or_else(|error| json!({"error": error}));
        (result, logs)
    }

    fn query_file_report(&self, resource: &str, resource_type: &str, api_key: &str) -> Value {
        let raw = match self.get_json(
            &self.endpoints.file_report,
            &[("resource", resource), ("resource_type", resource_type)],
            api_key,
        ) {
            Ok(raw) => raw,
            Err(error) => return json!({"error": error}),
        };
        if contains_error(&raw) {
            return raw;
        }
        format_file_report(resource, resource_type, raw)
            .unwrap_or_else(|error| json!({"error": error}))
    }

    fn query_file_multiengines(&self, resource: &str, resource_type: &str, api_key: &str) -> Value {
        let raw = match self.get_json(
            &self.endpoints.file_multiengines,
            &[("resource", resource), ("resource_type", resource_type)],
            api_key,
        ) {
            Ok(raw) => raw,
            Err(error) => return json!({"error": error}),
        };
        if contains_error(&raw) {
            return raw;
        }
        format_file_multiengines(resource, resource_type, raw)
            .unwrap_or_else(|error| json!({"error": error}))
    }

    fn upload_file(
        &self,
        path: &Path,
        display_path: &str,
        sandbox_type: &str,
        run_time: i64,
        api_key: &str,
    ) -> (Value, Vec<String>) {
        if api_key.is_empty() {
            return (json!({"error": "API密钥未设置"}), Vec::new());
        }
        let metadata = match fs::metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return (
                    json!({"error": format!("文件不存在: {display_path}")}),
                    Vec::new(),
                );
            }
            Err(error) => {
                return (json!({"error": format!("上传异常: {error}")}), Vec::new());
            }
        };
        let file_size = metadata.len();
        if file_size > MAX_UPLOAD_BYTES {
            return (
                json!({
                    "error": format!(
                        "文件过大: {:.1}MB，超过100MB限制",
                        file_size as f64 / (1024.0 * 1024.0)
                    )
                }),
                Vec::new(),
            );
        }
        let file_name = path
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        let mut logs = vec![
            format!(
                "[DEBUG] 上传文件: {display_path}, 大小: {:.2}MB",
                file_size as f64 / (1024.0 * 1024.0)
            ),
            format!("[DEBUG] 沙箱类型: {sandbox_type}, 运行时间: {run_time}秒"),
            format!("[DEBUG] 请求URL: {}", self.endpoints.file_upload),
            format!(
                "[DEBUG] 请求参数: {{'apikey': '[REDACTED]', 'sandbox_type': '{sandbox_type}', 'run_time': {run_time}}}"
            ),
        ];
        let response = self.send_with_retry(self.retry.upload_timeout, || {
            let file = File::open(path).map_err(|error| format!("open upload failed: {error}"))?;
            let reader = CancelableFileReader {
                file,
                cancellation: self.cancellation.clone(),
            };
            let part = Part::reader_with_length(reader, file_size).file_name(file_name.clone());
            let form = Form::new()
                .text("apikey", api_key.to_string())
                .text("sandbox_type", sandbox_type.to_string())
                .text("run_time", run_time.to_string())
                .part("file", part);
            Ok(self
                .client
                .post(&self.endpoints.file_upload)
                .multipart(form))
        });
        let response = match response {
            Ok(response) => response,
            Err(error) => {
                return (
                    json!({
                        "error": format!("上传失败: {}", sanitize_text(&error, api_key))
                    }),
                    logs,
                );
            }
        };
        if !(200..300).contains(&response.status) {
            return (
                json!({
                    "error": format!(
                        "上传失败: HTTP {}: {}",
                        response.status,
                        sanitize_text(&response.body, api_key)
                    )
                }),
                logs,
            );
        }
        let Some(mut raw) = response.json else {
            return (
                json!({"error": "响应解析失败: invalid JSON response"}),
                logs,
            );
        };
        redact_secret_value(&mut raw, api_key);
        logs.extend(debug_json_lines("[DEBUG] 文件上传API响应: ", &raw));
        if raw.get("response_code").and_then(Value::as_i64) != Some(0) {
            let message = raw
                .get("verbose_msg")
                .map(python_string)
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| "上传失败".to_string());
            return (json!({"error": format!("API错误: {message}")}), logs);
        }
        let data = raw.get("data").cloned().unwrap_or_else(empty_object);
        let result = json!({
            "file_name": file_name,
            "file_path": display_path,
            "file_size": file_size,
            "sandbox_type": sandbox_type,
            "run_time": run_time,
            "upload_time": local_timestamp(),
            "sha256": field_or(&data, "sha256", Value::String(String::new())),
            "md5": field_or(&data, "md5", Value::String(String::new())),
            "sha1": field_or(&data, "sha1", Value::String(String::new())),
            "permalink": field_or(&data, "permalink", Value::String(String::new())),
            "raw_data": raw,
        });
        (result, logs)
    }

    fn get_json(
        &self,
        endpoint: &str,
        params: &[(&str, &str)],
        api_key: &str,
    ) -> Result<Value, String> {
        if api_key.is_empty() {
            return Err("API密钥未设置".to_string());
        }
        let mut query = params.to_vec();
        query.push(("apikey", api_key));
        let response = self
            .send_with_retry(self.retry.request_timeout, || {
                Ok(self
                    .client
                    .get(endpoint)
                    .header(USER_AGENT, USER_AGENT_VALUE)
                    .header(CONTENT_TYPE, "application/json")
                    .query(&query))
            })
            .map_err(|error| format!("请求失败: {}", sanitize_text(&error, api_key)))?;
        if !(200..300).contains(&response.status) {
            return Err(format!(
                "请求失败: HTTP {}: {}",
                response.status,
                sanitize_text(&response.body, api_key)
            ));
        }
        let mut raw = response
            .json
            .ok_or_else(|| "响应解析失败: invalid JSON response".to_string())?;
        redact_secret_value(&mut raw, api_key);
        Ok(raw)
    }

    fn send_with_retry<F>(&self, timeout: Duration, build: F) -> Result<HttpResponse, String>
    where
        F: Fn() -> Result<RequestBuilder, String>,
    {
        let attempts = self.retry.max_attempts.max(1);
        let mut last_error = None;
        for attempt in 0..attempts {
            if self.cancellation.is_cancelled() {
                return Err("request cancelled".to_string());
            }
            let request = build()?;
            match request.timeout(timeout).send() {
                Ok(response) if retryable_status(response.status()) && attempt + 1 < attempts => {
                    last_error = Some(format!("HTTP {}", response.status().as_u16()));
                }
                Ok(response) => {
                    return read_response(response, self.retry.max_response_bytes);
                }
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

pub(crate) struct ThreatBookDispatchOutcome {
    pub(crate) data: Value,
    pub(crate) success: bool,
}

pub fn dispatch(
    command: &str,
    payload: &Value,
    config: &ConfigStore,
    cancellation: CancellationToken,
) -> Result<ThreatBookDispatchOutcome, String> {
    let persisted = config.load()?;
    let data =
        ThreatBookService::production(cancellation)?.dispatch(command, payload, &persisted)?;
    let success = data
        .get("success")
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("{command} returned a response without boolean success"))?;
    Ok(ThreatBookDispatchOutcome { data, success })
}

#[derive(Debug, Default, Deserialize)]
struct IpRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    ip: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    lang: String,
}

#[derive(Debug, Default, Deserialize)]
struct DnsRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    domain: String,
}

#[derive(Debug, Default, Deserialize)]
struct BatchIpRequest {
    #[serde(default, deserialize_with = "deserialize_optional_string_list")]
    ips: Option<Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    ip_text: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    batch_file: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    file_path: String,
}

#[derive(Debug, Default, Deserialize)]
struct FileResourceRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    resource: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    resource_type: String,
}

#[derive(Debug, Deserialize)]
struct FileUploadRequest {
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    file_path: String,
    #[serde(default, deserialize_with = "deserialize_python_or_empty")]
    sandbox_type: String,
    #[serde(
        default = "default_run_time",
        deserialize_with = "deserialize_python_i64"
    )]
    run_time: i64,
}

fn default_run_time() -> i64 {
    60
}

#[derive(Debug, Default, Deserialize)]
struct IpApiResponse {
    #[serde(default)]
    data: HashMap<String, IpReputationRecord>,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct IpReputationRecord {
    #[serde(default = "default_no_threat")]
    severity: Value,
    #[serde(default = "default_false")]
    is_malicious: Value,
    #[serde(default = "default_unknown")]
    confidence_level: Value,
    #[serde(default = "empty_array")]
    tags_classes: Value,
    #[serde(default = "empty_array")]
    judgments: Value,
    #[serde(default = "empty_object")]
    basic: Value,
    #[serde(default = "empty_object")]
    asn: Value,
    #[serde(default = "default_empty_string")]
    update_time: Value,
    #[serde(default = "default_empty_string")]
    permalink: Value,
    #[serde(default = "empty_array")]
    malware_families: Value,
    #[serde(default = "empty_array")]
    campaigns: Value,
    #[serde(default = "empty_array")]
    actors: Value,
    #[serde(default = "empty_array")]
    ttps: Value,
    #[serde(default = "empty_array")]
    cves: Value,
    #[serde(default = "empty_array")]
    iocs: Value,
    #[serde(default = "empty_array")]
    intelligence_tags: Value,
    #[serde(default = "default_zero")]
    threat_score: Value,
    #[serde(default = "default_empty_string")]
    first_seen: Value,
    #[serde(default = "default_empty_string")]
    last_seen: Value,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct DnsApiResponse {
    #[serde(default)]
    data: DnsData,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct DnsData {
    #[serde(default)]
    domains: HashMap<String, DnsRecord>,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct DnsRecord {
    #[serde(default = "default_no_threat")]
    severity: Value,
    #[serde(default = "empty_array")]
    judgments: Value,
    #[serde(default = "empty_array")]
    tags_classes: Value,
    #[serde(default = "default_unknown")]
    confidence_level: Value,
    #[serde(default = "default_false")]
    is_malicious: Value,
    #[serde(default = "default_empty_string")]
    permalink: Value,
    #[serde(default = "empty_object")]
    rank: Value,
    #[serde(default = "empty_object")]
    categories: Value,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct FileReportApiResponse {
    #[serde(default)]
    data: FileReportData,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Deserialize)]
struct FileReportData {
    #[serde(default = "default_empty_string")]
    sha256: Value,
    #[serde(default = "default_empty_string")]
    md5: Value,
    #[serde(default = "default_empty_string")]
    sha1: Value,
    #[serde(default = "default_empty_string")]
    file_name: Value,
    #[serde(default = "default_zero")]
    file_size: Value,
    #[serde(default = "default_empty_string")]
    file_type: Value,
    #[serde(default = "default_unknown_english")]
    reputation_level: Value,
    #[serde(default = "default_zero")]
    confidence: Value,
    #[serde(default = "empty_array")]
    threat_types: Value,
    #[serde(default = "empty_object")]
    engines: Value,
    #[serde(default = "default_empty_string")]
    scan_date: Value,
    #[serde(default = "default_empty_string")]
    permalink: Value,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

impl Default for FileReportData {
    fn default() -> Self {
        Self {
            sha256: default_empty_string(),
            md5: default_empty_string(),
            sha1: default_empty_string(),
            file_name: default_empty_string(),
            file_size: default_zero(),
            file_type: default_empty_string(),
            reputation_level: default_unknown_english(),
            confidence: default_zero(),
            threat_types: empty_array(),
            engines: empty_object(),
            scan_date: default_empty_string(),
            permalink: default_empty_string(),
            _extra: HashMap::new(),
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct FileMultienginesApiResponse {
    #[serde(default)]
    data: FileMultienginesData,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Default, Deserialize)]
struct FileMultienginesData {
    #[serde(default)]
    multiengines: MultienginesRecord,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

#[derive(Debug, Deserialize)]
struct MultienginesRecord {
    #[serde(default = "default_unknown_english")]
    threat_level: Value,
    #[serde(default = "default_zero")]
    total: Value,
    #[serde(default = "default_zero")]
    total2: Value,
    #[serde(default = "default_zero")]
    positives: Value,
    #[serde(default = "default_empty_string")]
    scan_date: Value,
    #[serde(default = "default_empty_string")]
    malware_type: Value,
    #[serde(default = "default_empty_string")]
    malware_family: Value,
    #[serde(default = "default_false")]
    is_white: Value,
    #[serde(default = "empty_object")]
    scans: Value,
    #[serde(flatten)]
    _extra: HashMap<String, Value>,
}

impl Default for MultienginesRecord {
    fn default() -> Self {
        Self {
            threat_level: default_unknown_english(),
            total: default_zero(),
            total2: default_zero(),
            positives: default_zero(),
            scan_date: default_empty_string(),
            malware_type: default_empty_string(),
            malware_family: default_empty_string(),
            is_white: default_false(),
            scans: empty_object(),
            _extra: HashMap::new(),
        }
    }
}

struct HttpResponse {
    status: u16,
    body: String,
    json: Option<Value>,
}

fn read_response(mut response: Response, max_bytes: usize) -> Result<HttpResponse, String> {
    if response
        .content_length()
        .is_some_and(|length| length > max_bytes as u64)
    {
        return Err(format!("response exceeds {max_bytes} byte limit"));
    }
    let status = response.status().as_u16();
    let mut bytes = Vec::new();
    response
        .by_ref()
        .take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("read response failed: {error}"))?;
    if bytes.len() > max_bytes {
        return Err(format!("response exceeds {max_bytes} byte limit"));
    }
    Ok(HttpResponse {
        status,
        body: String::from_utf8_lossy(&bytes).into_owned(),
        json: serde_json::from_slice(&bytes).ok(),
    })
}

fn retryable_status(status: StatusCode) -> bool {
    status == StatusCode::TOO_MANY_REQUESTS || matches!(status.as_u16(), 500 | 502 | 503 | 504)
}

fn format_ip_result(ip: &str, raw: Value) -> Result<Value, String> {
    let api: IpApiResponse =
        serde_json::from_value(raw.clone()).map_err(|error| format!("响应解析失败: {error}"))?;
    let record = api.data.get(ip);
    let severity = record
        .map(|item| item.severity.clone())
        .unwrap_or_else(default_no_threat);
    let is_malicious = record
        .map(|item| item.is_malicious.clone())
        .unwrap_or_else(default_false);
    let reputation_level = if python_truthy(&is_malicious) {
        "恶意"
    } else {
        match severity.as_str() {
            Some("无威胁" | "none") => "良好",
            Some("low") => "低危",
            Some("medium") => "中危",
            Some("high") => "高危",
            _ => "未知",
        }
    };
    let basic = record
        .map(|item| item.basic.clone())
        .unwrap_or_else(empty_object);
    let location = basic.get("location").cloned().unwrap_or_else(empty_object);
    Ok(json!({
        "ip": ip,
        "query_time": local_timestamp(),
        "reputation_level": reputation_level,
        "confidence": record.map(|item| item.confidence_level.clone()).unwrap_or_else(default_unknown),
        "threat_types": record.map(|item| item.tags_classes.clone()).unwrap_or_else(empty_array),
        "judgments": record.map(|item| item.judgments.clone()).unwrap_or_else(empty_array),
        "basic": basic,
        "location": location,
        "asn": record.map(|item| item.asn.clone()).unwrap_or_else(empty_object),
        "severity": severity,
        "is_malicious": is_malicious,
        "update_time": record.map(|item| item.update_time.clone()).unwrap_or_else(default_empty_string),
        "permalink": record.map(|item| item.permalink.clone()).unwrap_or_else(default_empty_string),
        "malware_families": record.map(|item| item.malware_families.clone()).unwrap_or_else(empty_array),
        "campaigns": record.map(|item| item.campaigns.clone()).unwrap_or_else(empty_array),
        "actors": record.map(|item| item.actors.clone()).unwrap_or_else(empty_array),
        "ttps": record.map(|item| item.ttps.clone()).unwrap_or_else(empty_array),
        "cves": record.map(|item| item.cves.clone()).unwrap_or_else(empty_array),
        "iocs": record.map(|item| item.iocs.clone()).unwrap_or_else(empty_array),
        "intelligence_tags": record.map(|item| item.intelligence_tags.clone()).unwrap_or_else(empty_array),
        "threat_score": record.map(|item| item.threat_score.clone()).unwrap_or_else(default_zero),
        "first_seen": record.map(|item| item.first_seen.clone()).unwrap_or_else(default_empty_string),
        "last_seen": record.map(|item| item.last_seen.clone()).unwrap_or_else(default_empty_string),
        "raw_data": raw,
    }))
}

fn format_dns_result(domain: &str, raw: Value) -> Result<Value, String> {
    let api: DnsApiResponse =
        serde_json::from_value(raw.clone()).map_err(|error| format!("响应解析失败: {error}"))?;
    let record = api.data.domains.get(domain);
    let tags_classes = record
        .map(|item| item.tags_classes.clone())
        .unwrap_or_else(empty_array);
    let mut malware_families = Vec::new();
    if let Some(classes) = tags_classes.as_array() {
        for tag_class in classes {
            let Some(tag_class) = tag_class.as_object() else {
                continue;
            };
            if tag_class.get("tags_type").and_then(Value::as_str) != Some("virus_family") {
                continue;
            }
            if let Some(tags) = tag_class.get("tags").and_then(Value::as_array) {
                malware_families.extend(tags.iter().cloned());
            }
        }
    }
    let rank = record.map(|item| &item.rank).and_then(Value::as_object);
    let rank_value = |name: &str| {
        rank.and_then(|value| value.get(name))
            .and_then(Value::as_object)
            .and_then(|value| value.get("global_rank"))
            .cloned()
            .unwrap_or_else(|| json!(-1))
    };
    let categories = record
        .map(|item| &item.categories)
        .and_then(Value::as_object)
        .and_then(|value| value.get("second_cats"))
        .cloned()
        .unwrap_or_else(|| Value::String(String::new()));
    Ok(json!({
        "domain": domain,
        "query_time": local_timestamp(),
        "is_malicious": record.map(|item| item.is_malicious.clone()).unwrap_or_else(default_false),
        "severity": record.map(|item| item.severity.clone()).unwrap_or_else(default_no_threat),
        "confidence_level": record.map(|item| item.confidence_level.clone()).unwrap_or_else(default_unknown),
        "judgments": record.map(|item| item.judgments.clone()).unwrap_or_else(empty_array),
        "tags_classes": tags_classes,
        "malware_families": malware_families,
        "permalink": record.map(|item| item.permalink.clone()).unwrap_or_else(default_empty_string),
        "alexa_rank": rank_value("alexa_rank"),
        "umbrella_rank": rank_value("umbrella_rank"),
        "categories": categories,
        "raw_data": raw,
    }))
}

fn format_file_report(resource: &str, resource_type: &str, raw: Value) -> Result<Value, String> {
    let api: FileReportApiResponse =
        serde_json::from_value(raw.clone()).map_err(|error| format!("响应解析失败: {error}"))?;
    let data = &api.data;
    Ok(json!({
        "resource": resource,
        "resource_type": resource_type,
        "query_time": local_timestamp(),
        "sha256": data.sha256.clone(),
        "md5": data.md5.clone(),
        "sha1": data.sha1.clone(),
        "file_name": data.file_name.clone(),
        "file_size": data.file_size.clone(),
        "file_type": data.file_type.clone(),
        "reputation_level": data.reputation_level.clone(),
        "confidence": data.confidence.clone(),
        "threat_types": data.threat_types.clone(),
        "engines": data.engines.clone(),
        "scan_date": data.scan_date.clone(),
        "permalink": data.permalink.clone(),
        "raw_data": raw,
    }))
}

fn format_file_multiengines(
    resource: &str,
    resource_type: &str,
    raw: Value,
) -> Result<Value, String> {
    let api: FileMultienginesApiResponse =
        serde_json::from_value(raw.clone()).map_err(|error| format!("响应解析失败: {error}"))?;
    let data = &api.data.multiengines;
    Ok(json!({
        "resource": resource,
        "resource_type": resource_type,
        "query_time": local_timestamp(),
        "threat_level": data.threat_level.clone(),
        "total_engines": data.total.clone(),
        "total2_engines": data.total2.clone(),
        "positive_engines": data.positives.clone(),
        "scan_date": data.scan_date.clone(),
        "malware_type": data.malware_type.clone(),
        "malware_family": data.malware_family.clone(),
        "is_white": data.is_white.clone(),
        "engines_detail": data.scans.clone(),
        "raw_data": raw,
    }))
}

fn single_command_response(result: Value, success_message: &str) -> Value {
    single_command_response_with_logs(result, success_message, Vec::new())
}

fn single_command_response_with_logs(
    result: Value,
    success_message: &str,
    logs: Vec<String>,
) -> Value {
    let success = !contains_error(&result);
    let message = if success {
        Value::String(success_message.to_string())
    } else {
        result.get("error").cloned().unwrap_or(Value::Null)
    };
    json!({
        "success": success,
        "message": message,
        "result": result,
        "logs": logs,
    })
}

fn parse_payload<T>(payload: &Value) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn deserialize_python_or_empty<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Value::deserialize(deserializer).map(|value| python_or_empty(&value))
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
            .map(python_string)
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .collect(),
    ))
}

fn deserialize_python_i64<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(python_i64(&value).unwrap_or_else(default_run_time))
}

fn python_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_u64().and_then(|value| i64::try_from(value).ok()))
            .or_else(|| value.as_f64().map(|value| value.trunc() as i64)),
        Value::String(value) => value.trim().parse().ok(),
        Value::Bool(value) => Some(i64::from(*value)),
        Value::Null | Value::Array(_) | Value::Object(_) => None,
    }
}

fn required_text(value: &str, message: &str) -> Result<String, String> {
    let value = value.trim();
    if value.is_empty() {
        Err(message.to_string())
    } else {
        Ok(value.to_string())
    }
}

fn normalized_default(value: &str, default: &str, lowercase: bool) -> String {
    let value = if value.is_empty() { default } else { value }.trim();
    if lowercase {
        value.to_lowercase()
    } else {
        value.to_string()
    }
}

fn python_or_empty(value: &Value) -> String {
    if python_truthy(value) {
        python_string(value)
    } else {
        String::new()
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_string)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(_) => value.to_string(),
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

fn contains_error(value: &Value) -> bool {
    value
        .as_object()
        .is_some_and(|value| value.contains_key("error"))
}

fn field_or(data: &Value, key: &str, default: Value) -> Value {
    data.get(key).cloned().unwrap_or(default)
}

fn default_empty_string() -> Value {
    Value::String(String::new())
}

fn default_unknown() -> Value {
    Value::String("未知".to_string())
}

fn default_unknown_english() -> Value {
    Value::String("unknown".to_string())
}

fn default_no_threat() -> Value {
    Value::String("无威胁".to_string())
}

fn default_zero() -> Value {
    json!(0)
}

fn default_false() -> Value {
    Value::Bool(false)
}

fn empty_array() -> Value {
    Value::Array(Vec::new())
}

fn empty_object() -> Value {
    Value::Object(Map::new())
}

fn local_timestamp() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

fn debug_json_lines(prefix: &str, value: &Value) -> Vec<String> {
    let formatted = serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string());
    let mut lines = formatted.lines();
    let mut result = Vec::new();
    if let Some(first) = lines.next() {
        result.push(format!("{prefix}{first}"));
    }
    result.extend(
        lines
            .filter(|line| !line.trim().is_empty())
            .map(str::to_string),
    );
    result
}

fn sanitize_text(value: &str, secret: &str) -> String {
    if secret.is_empty() {
        value.to_string()
    } else {
        value.replace(secret, "[REDACTED]")
    }
}

fn redact_secret_value(value: &mut Value, secret: &str) {
    if secret.is_empty() {
        return;
    }
    match value {
        Value::String(value) => *value = sanitize_text(value, secret),
        Value::Array(values) => {
            for value in values {
                redact_secret_value(value, secret);
            }
        }
        Value::Object(values) => {
            let original = std::mem::take(values);
            for (key, mut value) in original {
                redact_secret_value(&mut value, secret);
                values.insert(sanitize_text(&key, secret), value);
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
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering as AtomicOrdering};
    use std::sync::mpsc;

    static TEST_FILE_ID: AtomicU64 = AtomicU64::new(0);

    #[derive(Clone)]
    struct MockReply {
        status: u16,
        content_type: &'static str,
        body: String,
    }

    impl MockReply {
        fn json(body: &str) -> Self {
            Self {
                status: 200,
                content_type: "application/json",
                body: body.to_string(),
            }
        }
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
                let reason = match reply.status {
                    200 => "OK",
                    429 => "Too Many Requests",
                    503 => "Service Unavailable",
                    _ => "Error",
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
        let mut expected_length = None;
        let mut chunked = false;
        loop {
            match stream.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => bytes.extend_from_slice(&buffer[..read]),
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                    ) =>
                {
                    break;
                }
                Err(error) => panic!("read mock request: {error}"),
            }
            if expected_length.is_none() {
                if let Some(header_end) = find_bytes(&bytes, b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..header_end]);
                    let content_length = headers.lines().find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        name.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse::<usize>().ok())
                            .flatten()
                    });
                    chunked = headers.lines().any(|line| {
                        line.to_ascii_lowercase()
                            .starts_with("transfer-encoding: chunked")
                    });
                    expected_length = content_length.map(|length| header_end + 4 + length);
                    if content_length.is_none() && !chunked {
                        break;
                    }
                }
            }
            if expected_length.is_some_and(|length| bytes.len() >= length) {
                break;
            }
            if chunked && bytes.ends_with(b"\r\n0\r\n\r\n") {
                break;
            }
        }
        String::from_utf8_lossy(&bytes).into_owned()
    }

    fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
        haystack
            .windows(needle.len())
            .position(|window| window == needle)
    }

    fn service(base: &str, attempts: u8, max_response_bytes: usize) -> ThreatBookService {
        ThreatBookService::new(
            ThreatBookEndpoints {
                ip_reputation: format!("{base}/v3/scene/ip_reputation"),
                dns: format!("{base}/v3/scene/dns"),
                file_report: format!("{base}/v3/file/report"),
                file_multiengines: format!("{base}/v3/file/report/multiengines"),
                file_upload: format!("{base}/v3/file/upload"),
            },
            RetryPolicy {
                max_attempts: attempts,
                initial_backoff: Duration::ZERO,
                request_timeout: Duration::from_secs(2),
                upload_timeout: Duration::from_secs(2),
                max_response_bytes,
                batch_interval: Duration::ZERO,
            },
            CancellationToken::new(),
        )
        .expect("create ThreatBook service")
    }

    fn configured() -> Value {
        json!({"threatbook_api_key": "top-secret-key"})
    }

    fn temp_file(extension: &str, contents: &[u8]) -> PathBuf {
        let id = TEST_FILE_ID.fetch_add(1, AtomicOrdering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "koi-threatbook-{}-{id}.{extension}",
            std::process::id()
        ));
        fs::write(&path, contents).expect("write test file");
        path
    }

    #[test]
    fn ip_and_dns_match_python_shapes_and_http_contract() {
        let (base, requests, server) = mock_server(vec![
            MockReply::json(
                r#"{"data":{"1.2.3.4":{"severity":"high","is_malicious":true,"confidence_level":"high","tags_classes":[{"tags_type":"attack_method","tags":["scan"]}],"judgments":["botnet"],"basic":{"location":{"country":"CN","city":"Beijing"}},"asn":{"number":64512},"permalink":"https://x.threatbook.cn/ip/1.2.3.4","malware_families":["demo"],"threat_score":99}}}"#,
            ),
            MockReply::json(
                r#"{"data":{"domains":{"bad.test":{"severity":"medium","is_malicious":true,"confidence_level":"high","judgments":["c2"],"tags_classes":[{"tags_type":"virus_family","tags":["family-a"]},{"tags_type":"attack_method","tags":["redirect"]}],"rank":{"alexa_rank":{"global_rank":12}},"categories":{"second_cats":"malware"},"permalink":"https://x.threatbook.cn/domain/bad.test"}}}}"#,
            ),
        ]);
        let service = service(&base, 1, 4096);

        let ip = service
            .dispatch(
                IP_COMMAND,
                &json!({"ip": " 1.2.3.4 ", "lang": "en"}),
                &configured(),
            )
            .expect("IP command");
        assert_eq!(ip["success"], true);
        assert_eq!(ip["message"], "IP 信誉查询完成");
        assert_eq!(ip["result"]["ip"], "1.2.3.4");
        assert_eq!(ip["result"]["reputation_level"], "恶意");
        assert_eq!(ip["result"]["threat_score"], 99);
        assert_eq!(ip["result"]["location"]["city"], "Beijing");
        assert!(ip["logs"].as_array().is_some_and(Vec::is_empty));

        let dns = service
            .dispatch(DNS_COMMAND, &json!({"domain": "bad.test"}), &configured())
            .expect("DNS command");
        assert_eq!(dns["success"], true);
        assert_eq!(dns["result"]["malware_families"], json!(["family-a"]));
        assert_eq!(dns["result"]["alexa_rank"], 12);
        assert_eq!(dns["result"]["umbrella_rank"], -1);
        assert!(dns["logs"].as_array().is_some_and(|logs| logs.len() > 3));

        let ip_request = requests.recv().expect("IP request");
        let ip_request_lower = ip_request.to_ascii_lowercase();
        assert!(ip_request.starts_with("GET /v3/scene/ip_reputation?"));
        assert!(ip_request.contains("resource=1.2.3.4"));
        assert!(ip_request.contains("lang=en"));
        assert!(ip_request.contains("apikey=top-secret-key"));
        assert!(ip_request_lower.contains("user-agent: threatbook-api-client/1.0"));
        assert!(ip_request_lower.contains("content-type: application/json"));
        let dns_request = requests.recv().expect("DNS request");
        assert!(dns_request.starts_with("GET /v3/scene/dns?"));
        assert!(dns_request.contains("resource=bad.test"));
        server.join().expect("mock server");

        assert!(!ip.to_string().contains("top-secret-key"));
        assert!(!dns.to_string().contains("top-secret-key"));
    }

    #[test]
    fn file_report_and_multiengines_preserve_api_data() {
        let (base, requests, server) = mock_server(vec![
            MockReply::json(
                r#"{"data":{"sha256":"abc","md5":"def","file_name":"sample.exe","file_size":42,"file_type":"PE","reputation_level":"malicious","confidence":95,"threat_types":["trojan"],"engines":{"demo":{"result":"hit"}},"scan_date":"2026-01-02","permalink":"https://x/report/abc"}}"#,
            ),
            MockReply::json(
                r#"{"data":{"multiengines":{"threat_level":"malicious","total":10,"total2":11,"positives":4,"scan_date":"2026-01-02","malware_type":"trojan","malware_family":"demo","is_white":false,"scans":{"engine-a":{"result":"hit"}}}}}"#,
            ),
        ]);
        let service = service(&base, 1, 4096);

        let report = service
            .dispatch(
                FILE_REPORT_COMMAND,
                &json!({"resource":"abc", "resource_type":"SHA256"}),
                &configured(),
            )
            .expect("file report");
        assert_eq!(report["success"], true);
        assert_eq!(report["result"]["resource_type"], "sha256");
        assert_eq!(report["result"]["file_name"], "sample.exe");
        assert_eq!(report["result"]["engines"]["demo"]["result"], "hit");

        let engines = service
            .dispatch(
                FILE_MULTIENGINES_COMMAND,
                &json!({"resource":"abc", "resource_type":"sha256"}),
                &configured(),
            )
            .expect("multiengines");
        assert_eq!(engines["success"], true);
        assert_eq!(engines["result"]["total_engines"], 10);
        assert_eq!(engines["result"]["total2_engines"], 11);
        assert_eq!(engines["result"]["positive_engines"], 4);
        assert_eq!(
            engines["result"]["engines_detail"]["engine-a"]["result"],
            "hit"
        );

        let report_request = requests.recv().expect("report request");
        assert!(report_request.starts_with("GET /v3/file/report?"));
        assert!(report_request.contains("resource_type=sha256"));
        let engines_request = requests.recv().expect("engines request");
        assert!(engines_request.starts_with("GET /v3/file/report/multiengines?"));
        server.join().expect("mock server");
    }

    #[test]
    fn batch_deduplicates_in_order_and_keeps_per_item_failures() {
        let (base, requests, server) = mock_server(vec![
            MockReply::json(r#"{"data":{"1.1.1.1":{"severity":"none"}}}"#),
            MockReply::json(r#"{"error":"quota reached"}"#),
        ]);
        let service = service(&base, 1, 4096);
        let result = service
            .dispatch(
                IP_BATCH_COMMAND,
                &json!({"ip_text":"1.1.1.1\n1.1.1.1\n2.2.2.2\n"}),
                &configured(),
            )
            .expect("batch command");
        assert_eq!(result["success"], false);
        assert_eq!(result["message"], "批量查询完成，1 个失败");
        assert_eq!(result["rows"].as_array().map(Vec::len), Some(2));
        assert_eq!(result["rows"][0]["ip"], "1.1.1.1");
        assert_eq!(result["rows"][0]["success"], true);
        assert_eq!(result["rows"][1]["ip"], "2.2.2.2");
        assert_eq!(result["rows"][1]["success"], false);
        assert_eq!(
            result["logs"],
            json!([
                "正在查询第 1/2 个IP: 1.1.1.1",
                "正在查询第 2/2 个IP: 2.2.2.2"
            ])
        );
        assert!(requests.recv().expect("first request").contains("1.1.1.1"));
        assert!(requests.recv().expect("second request").contains("2.2.2.2"));
        server.join().expect("mock server");
    }

    #[test]
    fn multipart_upload_streams_file_and_redacts_secret_from_output() {
        let (base, requests, server) = mock_server(vec![MockReply::json(
            r#"{"response_code":0,"data":{"sha256":"sha-value","md5":"md5-value","sha1":"sha1-value","permalink":"https://x/upload/sha-value"}}"#,
        )]);
        let service = service(&base, 1, 4096);
        let file = temp_file("bin", b"streamed-upload-content");
        let result = service
            .dispatch(
                FILE_UPLOAD_COMMAND,
                &json!({
                    "file_path": file.to_string_lossy(),
                    "sandbox_type": "win10_21h2_x64",
                    "run_time": 999
                }),
                &configured(),
            )
            .expect("upload command");
        assert_eq!(result["success"], true);
        assert_eq!(result["result"]["sha256"], "sha-value");
        assert_eq!(result["result"]["run_time"], 300);
        assert_eq!(result["result"]["file_size"], 23);
        assert!(!result.to_string().contains("top-secret-key"));
        assert!(result.to_string().contains("[REDACTED]"));

        let request = requests.recv().expect("upload request");
        assert!(request.starts_with("POST /v3/file/upload HTTP/1.1"));
        assert!(request.to_ascii_lowercase().contains("multipart/form-data"));
        assert!(request.contains("name=\"apikey\""));
        assert!(request.contains("top-secret-key"));
        assert!(request.contains("name=\"sandbox_type\""));
        assert!(request.contains("win10_21h2_x64"));
        assert!(request.contains("name=\"run_time\""));
        assert!(request.contains("300"));
        assert!(request.contains("streamed-upload-content"));
        server.join().expect("mock server");
        fs::remove_file(file).expect("remove upload fixture");
    }

    #[test]
    fn retries_transient_status_and_tests_connection_with_fixed_ip() {
        let (base, requests, server) = mock_server(vec![
            MockReply {
                status: 503,
                content_type: "text/plain",
                body: "busy".to_string(),
            },
            MockReply::json(r#"{"data":{"8.8.8.8":{"severity":"none"}}}"#),
        ]);
        let service = service(&base, 2, 4096);
        let result = service
            .dispatch(TEST_CONNECTION_COMMAND, &json!({}), &configured())
            .expect("connection test");
        assert_eq!(result["success"], true);
        assert_eq!(result["message"], "API连接正常");
        assert_eq!(result["result"]["success"], true);
        for _ in 0..2 {
            let request = requests.recv().expect("retry request");
            assert!(request.contains("resource=8.8.8.8"));
        }
        server.join().expect("mock server");
    }

    #[test]
    fn cancellation_response_limit_and_server_echo_fail_closed_without_secret_leaks() {
        let cancellation = CancellationToken::new();
        cancellation.cancel();
        let cancelled = ThreatBookService::new(
            ThreatBookEndpoints::default(),
            RetryPolicy::default(),
            cancellation,
        )
        .expect("cancelled service")
        .dispatch(IP_COMMAND, &json!({"ip":"1.1.1.1"}), &configured())
        .expect("structured cancellation");
        assert_eq!(cancelled["success"], false);
        assert!(cancelled["message"]
            .as_str()
            .is_some_and(|message| message.contains("cancelled")));
        assert!(!cancelled.to_string().contains("top-secret-key"));

        let (base, requests, server) = mock_server(vec![MockReply::json(
            r#"{"data":{"1.1.1.1":{"severity":"none"}}}"#,
        )]);
        let batch_cancellation = CancellationToken::new();
        let batch_service = ThreatBookService::new(
            ThreatBookEndpoints {
                ip_reputation: format!("{base}/v3/scene/ip_reputation"),
                dns: format!("{base}/v3/scene/dns"),
                file_report: format!("{base}/v3/file/report"),
                file_multiengines: format!("{base}/v3/file/report/multiengines"),
                file_upload: format!("{base}/v3/file/upload"),
            },
            RetryPolicy {
                max_attempts: 1,
                initial_backoff: Duration::ZERO,
                request_timeout: Duration::from_secs(2),
                upload_timeout: Duration::from_secs(2),
                max_response_bytes: 4096,
                batch_interval: Duration::from_secs(2),
            },
            batch_cancellation.clone(),
        )
        .expect("batch cancellation service");
        let cancel_thread = thread::spawn(move || {
            thread::sleep(Duration::from_millis(200));
            batch_cancellation.cancel();
        });
        let batch = batch_service
            .dispatch(
                IP_BATCH_COMMAND,
                &json!({"ip_text":"1.1.1.1\n2.2.2.2"}),
                &configured(),
            )
            .expect("cancelled batch response");
        cancel_thread.join().expect("cancel thread");
        assert_eq!(batch["results"].as_array().map(Vec::len), Some(2));
        assert_eq!(batch["results"][1]["error"], "request cancelled");
        assert!(requests
            .recv()
            .expect("only HTTP request")
            .contains("1.1.1.1"));
        server.join().expect("batch cancellation server");

        let oversized_body = format!(r#"{{"data":{{}},"padding":"{}"}}"#, "x".repeat(128));
        let (base, _requests, server) = mock_server(vec![MockReply::json(&oversized_body)]);
        let limited = service(&base, 1, 32)
            .dispatch(IP_COMMAND, &json!({"ip":"1.1.1.1"}), &configured())
            .expect("structured limit failure");
        assert_eq!(limited["success"], false);
        assert!(limited["message"]
            .as_str()
            .is_some_and(|message| message.contains("32 byte limit")));
        assert!(!limited.to_string().contains("top-secret-key"));
        server.join().expect("mock server");

        let echoed = r#"{"error":"rejected top-secret-key"}"#.to_string();
        let (base, _requests, server) = mock_server(vec![MockReply::json(&echoed)]);
        let redacted = service(&base, 1, 4096)
            .dispatch(IP_COMMAND, &json!({"ip":"1.1.1.1"}), &configured())
            .expect("structured API error");
        assert_eq!(redacted["success"], false);
        assert!(redacted.to_string().contains("[REDACTED]"));
        assert!(!redacted.to_string().contains("top-secret-key"));
        server.join().expect("mock server");
    }

    #[test]
    fn batch_file_aliases_and_encodings_match_existing_inputs() {
        let text = temp_file("txt", "3.3.3.3\r\n4.4.4.4\r\n".as_bytes());
        assert_eq!(
            read_lines_file(&text).expect("text lines"),
            vec!["3.3.3.3", "4.4.4.4"]
        );
        fs::remove_file(text).expect("remove text fixture");

        let csv = temp_file("csv", b"\xef\xbb\xbf5.5.5.5,name\r\n6.6.6.6,name\r\n");
        assert_eq!(
            read_lines_file(&csv).expect("CSV lines"),
            vec!["5.5.5.5", "6.6.6.6"]
        );
        fs::remove_file(csv).expect("remove CSV fixture");
    }

    #[test]
    fn required_fields_and_missing_key_keep_outer_and_inner_error_boundaries() {
        let service = ThreatBookService::production(CancellationToken::default())
            .expect("production service");
        assert_eq!(
            service
                .dispatch(IP_COMMAND, &json!({"ip":"  "}), &json!({}))
                .expect_err("missing IP"),
            "请输入 IP 地址"
        );
        let missing_key = service
            .dispatch(IP_COMMAND, &json!({"ip":"1.1.1.1"}), &json!({}))
            .expect("missing key is command data");
        assert_eq!(missing_key["success"], false);
        assert_eq!(missing_key["message"], "API密钥未设置");
        assert_eq!(missing_key["result"], json!({"error":"API密钥未设置"}));

        let connection = service
            .dispatch(TEST_CONNECTION_COMMAND, &json!({}), &json!({}))
            .expect("missing connection key");
        assert_eq!(connection["success"], false);
        assert_eq!(connection["message"], "API密钥未设置");
        assert_eq!(
            connection["result"],
            json!({"success":false,"message":"API密钥未设置"})
        );
    }
}
