//! Typed enterprise-query clients for Tianyancha and Aiqicha.
//!
//! The old implementation mixed scraping, browser automation and result
//! formatting in Python.  This module deliberately keeps the IPC contract
//! small and typed while making the browser boundary explicit.  A production
//! request never launches an unspecified browser: when a login or risk
//! challenge is encountered, the configured WebView2 boundary must provide a
//! cookie or the request fails closed.

use super::batch_input::read_lines_file;
use super::config::ConfigStore;
use reqwest::blocking::{Client, RequestBuilder};
use reqwest::header::{CONTENT_TYPE, COOKIE, USER_AGENT};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::io::Read;
use std::sync::{Arc, OnceLock};
use std::thread;
use std::time::Duration;

pub const TYC_COMMAND: &str = "info.enterprise.tyc.query";
pub const AIQICHA_COMMAND: &str = "info.enterprise.aiqicha.query";

const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
const MAX_COMPANIES: usize = 500;

/// Provider used by the query client.  Keeping this explicit avoids silently
/// falling back to DrissionPage or a host browser in a packaged build.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnterpriseSource {
    Tianyancha,
    Aiqicha,
}

#[cfg_attr(test, allow(dead_code))]
impl EnterpriseSource {
    fn from_command(command: &str) -> Option<Self> {
        match command {
            TYC_COMMAND => Some(Self::Tianyancha),
            AIQICHA_COMMAND => Some(Self::Aiqicha),
            _ => None,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Tianyancha => "Tianyancha",
            Self::Aiqicha => "Aiqicha",
        }
    }

    fn key(self) -> &'static str {
        match self {
            Self::Tianyancha => "tyc",
            Self::Aiqicha => "aiqicha",
        }
    }

    fn display_name(self) -> &'static str {
        match self {
            Self::Tianyancha => "天眼查",
            Self::Aiqicha => "爱企查",
        }
    }

    pub(crate) fn profile_key(self) -> &'static str {
        self.key()
    }

    pub(crate) fn login_url(self) -> &'static str {
        match self {
            Self::Tianyancha => "https://www.tianyancha.com/",
            Self::Aiqicha => "https://aiqicha.baidu.com/",
        }
    }

    pub(crate) fn login_title(self) -> String {
        format!("{} 登录", self.display_name())
    }
}

/// A browser implementation is intentionally injected.  The Tauri shell can
/// later provide a site-isolated WebView2 implementation without changing the
/// command contract; the core keeps a fail-closed implementation for now.
pub trait WebView2LoginBoundary: Send + Sync {
    fn obtain_cookie(
        &self,
        source: EnterpriseSource,
        target_url: &str,
    ) -> Result<Option<String>, String>;
}

#[derive(Debug, Default)]
pub struct FailClosedLoginBoundary;

impl WebView2LoginBoundary for FailClosedLoginBoundary {
    fn obtain_cookie(
        &self,
        source: EnterpriseSource,
        _target_url: &str,
    ) -> Result<Option<String>, String> {
        Err(format!(
            "{}需要在隔离 WebView2 中完成登录；当前构建未提供登录窗口",
            source.display_name()
        ))
    }
}

static PRODUCTION_LOGIN_BOUNDARY: OnceLock<Arc<dyn WebView2LoginBoundary>> = OnceLock::new();

/// Install the Tauri/WebView2 boundary before the first backend command is
/// dispatched.  Tests and self-test intentionally leave it unset so they can
/// prove that browser access fails closed outside an interactive app runtime.
#[cfg_attr(test, allow(dead_code))]
pub(crate) fn install_production_login_boundary(
    boundary: Arc<dyn WebView2LoginBoundary>,
) -> Result<(), String> {
    PRODUCTION_LOGIN_BOUNDARY
        .set(boundary)
        .map_err(|_| "enterprise WebView2 login boundary is already installed".to_string())
}

fn production_login_boundary() -> Arc<dyn WebView2LoginBoundary> {
    PRODUCTION_LOGIN_BOUNDARY
        .get()
        .cloned()
        .unwrap_or_else(|| Arc::new(FailClosedLoginBoundary))
}

#[derive(Debug, Clone)]
pub struct EnterpriseEndpoints {
    pub tyc_search: String,
    pub aiqicha_search: String,
}

impl Default for EnterpriseEndpoints {
    fn default() -> Self {
        Self {
            tyc_search: "https://www.tianyancha.com/nsearch".to_string(),
            aiqicha_search: "https://aiqicha.baidu.com/s".to_string(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct EnterpriseRetryPolicy {
    pub max_attempts: u8,
    pub request_timeout: Duration,
    pub max_response_bytes: usize,
    pub batch_interval: Duration,
}

impl Default for EnterpriseRetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 2,
            request_timeout: Duration::from_secs(30),
            max_response_bytes: MAX_RESPONSE_BYTES,
            batch_interval: Duration::from_millis(250),
        }
    }
}

#[derive(Clone)]
pub struct EnterpriseQueryService {
    client: Client,
    endpoints: EnterpriseEndpoints,
    retry: EnterpriseRetryPolicy,
    login: Arc<dyn WebView2LoginBoundary>,
}

impl EnterpriseQueryService {
    pub fn production() -> Result<Self, String> {
        Self::new(
            EnterpriseEndpoints::default(),
            EnterpriseRetryPolicy::default(),
            production_login_boundary(),
        )
    }

    pub fn new(
        endpoints: EnterpriseEndpoints,
        retry: EnterpriseRetryPolicy,
        login: Arc<dyn WebView2LoginBoundary>,
    ) -> Result<Self, String> {
        validate_endpoint(&endpoints.tyc_search)?;
        validate_endpoint(&endpoints.aiqicha_search)?;
        let client = Client::builder()
            .user_agent("KOI/4.0.0 enterprise-query")
            // Cookies must never follow a cross-origin redirect.  A provider
            // redirect is reported as a structured HTTP failure and can be
            // retried after the user completes the isolated login flow.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| format!("创建企业查询 HTTP 客户端失败: {error}"))?;
        Ok(Self {
            client,
            endpoints,
            retry,
            login,
        })
    }

    pub fn dispatch(
        &self,
        command: &str,
        payload: &Value,
        config: &Value,
    ) -> Result<Value, String> {
        let source = EnterpriseSource::from_command(command)
            .ok_or_else(|| format!("未知企业查询命令: {command}"))?;
        let request: EnterpriseRequest = parse_payload(payload)?;
        let companies = request.companies()?;
        if companies.is_empty() {
            return Err("请输入企业名称或选择批量文件".to_string());
        }
        if companies.len() > MAX_COMPANIES {
            return Err(format!("企业查询数量不能超过 {MAX_COMPANIES}"));
        }

        let configured_cookie = source_cookie(config, source);
        let mut browser_cookie = String::new();
        let mut login_error = None;
        let cookie = if configured_cookie.is_empty() {
            let endpoint = match source {
                EnterpriseSource::Tianyancha => &self.endpoints.tyc_search,
                EnterpriseSource::Aiqicha => &self.endpoints.aiqicha_search,
            };
            match self.login.obtain_cookie(source, endpoint) {
                Ok(Some(cookie)) if !cookie.trim().is_empty() => {
                    browser_cookie = cookie.trim().to_string();
                    browser_cookie.as_str()
                }
                Ok(_) => "",
                Err(error) => {
                    login_error = Some(error);
                    ""
                }
            }
        } else {
            configured_cookie.as_str()
        };
        let mut result = if cookie.is_empty() {
            self.missing_cookie(source, &companies, login_error.as_deref())
        } else if companies.len() == 1 {
            self.single(source, &companies[0], cookie)
        } else {
            self.batch(source, &companies, cookie)
        };

        redact_cookie_value(&mut result, &configured_cookie);
        redact_cookie_value(&mut result, &browser_cookie);
        Ok(result)
    }

    fn missing_cookie(
        &self,
        source: EnterpriseSource,
        companies: &[String],
        login_error: Option<&str>,
    ) -> Value {
        let mut message = format!(
            "{} Cookie 未配置，请先在隔离 WebView2 中登录",
            source.display_name()
        );
        if let Some(error) = login_error.filter(|error| !error.trim().is_empty()) {
            let detail = error.trim().chars().take(500).collect::<String>();
            message.push_str(&format!("；登录窗口失败: {detail}"));
        }
        let rows = companies
            .iter()
            .enumerate()
            .map(|(index, company)| {
                enterprise_row(source, index + 1, company, false, json!({}), &message)
            })
            .collect::<Vec<_>>();
        if companies.len() == 1 {
            let raw = json!({
                "success": false,
                "error": message,
                "query": companies[0],
                "companies": [],
            });
            return json!({
                "success": false,
                "message": message,
                "source": source.key(),
                "companies": companies,
                "formatted": format!("查询失败: {message}"),
                "rows": rows,
                "raw": raw,
                "logs": [message],
            });
        }

        let results = companies
            .iter()
            .enumerate()
            .map(|(index, company)| {
                json!({
                    "company": company,
                    "error": message,
                    "success": false,
                    "index": index + 1,
                })
            })
            .collect::<Vec<_>>();
        let raw = json!({
            "success": false,
            "results": results,
            "total": companies.len(),
            "success_count": 0,
            "failure_count": companies.len(),
            "error": message,
            "message": format!("批量查询失败，Cookie 未配置"),
        });
        json!({
            "success": false,
            "message": message,
            "source": source.key(),
            "companies": companies,
            "formatted": format!("批量查询失败: {message}"),
            "rows": rows,
            "raw": raw,
            "logs": [message],
        })
    }

    fn single(&self, source: EnterpriseSource, company: &str, cookie: &str) -> Value {
        let response = self.query_one_with_boundary(source, company, cookie);
        match response {
            Ok(raw) => {
                let success = raw_success(source, &raw);
                let message = if success {
                    "查询完成".to_string()
                } else {
                    raw_error(&raw).unwrap_or_else(|| "未找到企业信息".to_string())
                };
                let data = raw.clone();
                json!({
                    "success": success,
                    "message": message,
                    "source": source.key(),
                    "companies": [company],
                    "formatted": format_single(source, &raw),
                    "rows": [enterprise_row(source, 1, company, success, data, &message)],
                    "raw": raw,
                    "logs": [],
                })
            }
            Err(error) => {
                let safe_error = sanitize_cookie_text(&error, cookie);
                let raw = failure_raw(source, company, &safe_error);
                json!({
                    "success": false,
                    "message": safe_error,
                    "source": source.key(),
                    "companies": [company],
                    "formatted": format!("查询失败: {safe_error}"),
                    "rows": [enterprise_row(source, 1, company, false, json!({}), &safe_error)],
                    "raw": raw,
                    "logs": [safe_error],
                })
            }
        }
    }

    fn batch(&self, source: EnterpriseSource, companies: &[String], cookie: &str) -> Value {
        let mut result_items = Vec::with_capacity(companies.len());
        let mut rows = Vec::with_capacity(companies.len());
        let mut logs = Vec::new();
        let mut success_count = 0usize;
        for (index, company) in companies.iter().enumerate() {
            if index > 0 && !self.retry.batch_interval.is_zero() {
                thread::sleep(self.retry.batch_interval);
            }
            match self.query_one_with_boundary(source, company, cookie) {
                Ok(raw) if raw_success(source, &raw) => {
                    success_count += 1;
                    result_items.push(json!({
                        "company": company,
                        "data": raw,
                        "success": true,
                        "index": index + 1,
                    }));
                    rows.push(enterprise_row(
                        source,
                        index + 1,
                        company,
                        true,
                        result_items
                            .last()
                            .and_then(|item| item.get("data"))
                            .cloned()
                            .unwrap_or_default(),
                        "",
                    ));
                    logs.push(format!("查询 {company} 成功"));
                }
                Ok(raw) => {
                    let error = raw_error(&raw).unwrap_or_else(|| "未找到企业信息".to_string());
                    result_items.push(json!({
                        "company": company,
                        "error": error,
                        "success": false,
                        "index": index + 1,
                    }));
                    rows.push(enterprise_row(
                        source,
                        index + 1,
                        company,
                        false,
                        raw,
                        &error,
                    ));
                    logs.push(format!("查询 {company} 失败: {error}"));
                }
                Err(error) => {
                    let safe_error = sanitize_cookie_text(&error, cookie);
                    result_items.push(json!({
                        "company": company,
                        "error": safe_error,
                        "success": false,
                        "index": index + 1,
                    }));
                    rows.push(enterprise_row(
                        source,
                        index + 1,
                        company,
                        false,
                        json!({}),
                        &safe_error,
                    ));
                    logs.push(format!("查询 {company} 失败: {safe_error}"));
                }
            }
        }
        let total = companies.len();
        // Both legacy providers return a completed batch envelope even when
        // individual rows failed; callers inspect row.success/failure_count.
        let success = true;
        let message = format!("批量查询完成，成功: {success_count}/{total}");
        let raw = json!({
            "success": success,
            "results": result_items,
            "total": total,
            "success_count": success_count,
            "failure_count": total - success_count,
            "message": message,
        });
        json!({
            "success": success,
            "message": message,
            "source": source.key(),
            "companies": companies,
            "formatted": format_batch(source, &raw),
            "rows": rows,
            "raw": raw,
            "logs": logs,
        })
    }

    fn query_one(
        &self,
        source: EnterpriseSource,
        company: &str,
        cookie: &str,
    ) -> Result<Value, String> {
        let endpoint = match source {
            EnterpriseSource::Tianyancha => &self.endpoints.tyc_search,
            EnterpriseSource::Aiqicha => &self.endpoints.aiqicha_search,
        };
        let mut last_error = "企业查询请求失败".to_string();
        for attempt in 0..self.retry.max_attempts.max(1) {
            let mut request = self.client.get(endpoint);
            request = match source {
                EnterpriseSource::Tianyancha => request.query(&[("key", company)]),
                EnterpriseSource::Aiqicha => request.query(&[("q", company), ("t", "0")]),
            };
            request = request
                .header(COOKIE, cookie)
                .header(
                    USER_AGENT,
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131",
                )
                .header("Accept-Language", "zh-CN,zh;q=0.9");
            match self.send(request) {
                Ok((status, content_type, body)) => {
                    if status >= 400 {
                        last_error = format!("HTTP {status}");
                    } else if is_challenge(&body) {
                        return Err("检测到登录或风控验证，需要 WebView2 登录".to_string());
                    } else {
                        return parse_provider_response(source, company, &content_type, &body);
                    }
                }
                Err(error) => last_error = error,
            }
            if attempt + 1 < self.retry.max_attempts.max(1) {
                thread::sleep(Duration::from_millis(100 * (attempt as u64 + 1)));
            }
        }
        Err(last_error)
    }

    fn query_one_with_boundary(
        &self,
        source: EnterpriseSource,
        company: &str,
        cookie: &str,
    ) -> Result<Value, String> {
        match self.query_one(source, company, cookie) {
            Ok(value) => Ok(value),
            Err(error) if is_login_error(&error) => {
                let endpoint = match source {
                    EnterpriseSource::Tianyancha => &self.endpoints.tyc_search,
                    EnterpriseSource::Aiqicha => &self.endpoints.aiqicha_search,
                };
                let browser_cookie = self
                    .login
                    .obtain_cookie(source, endpoint)
                    .map_err(|boundary_error| sanitize_cookie_text(&boundary_error, cookie))?
                    .ok_or_else(|| {
                        format!("{} WebView2 未返回有效 Cookie", source.display_name())
                    })?;
                let browser_cookie = browser_cookie.trim().to_string();
                if browser_cookie.is_empty() {
                    return Err(format!(
                        "{} WebView2 未返回有效 Cookie",
                        source.display_name()
                    ));
                }
                let mut value = self
                    .query_one(source, company, &browser_cookie)
                    .map_err(|retry_error| sanitize_cookie_text(&retry_error, &browser_cookie))?;
                // A mock/provider may echo request headers in a JSON body.  A
                // browser-obtained cookie is therefore redacted before it can
                // reach the IPC response, even though it was not persisted.
                redact_cookie_value(&mut value, &browser_cookie);
                Ok(value)
            }
            Err(error) => Err(error),
        }
    }

    fn send(&self, request: RequestBuilder) -> Result<(u16, String, String), String> {
        let response = request
            .timeout(self.retry.request_timeout)
            .send()
            .map_err(|error| format!("企业查询请求失败: {error}"))?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_string();
        let mut bytes = Vec::new();
        response
            .take((self.retry.max_response_bytes.min(MAX_RESPONSE_BYTES) + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|error| format!("读取企业查询响应失败: {error}"))?;
        if bytes.len() > self.retry.max_response_bytes.min(MAX_RESPONSE_BYTES) {
            return Err("企业查询响应超过大小限制".to_string());
        }
        let body =
            String::from_utf8(bytes).map_err(|_| "企业查询响应不是有效 UTF-8".to_string())?;
        Ok((status, content_type, body))
    }
}

pub fn dispatch(command: &str, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
    let persisted = config.load()?;
    EnterpriseQueryService::production()?.dispatch(command, payload, &persisted)
}

#[derive(Debug, Default, Deserialize)]
struct EnterpriseRequest {
    #[serde(default, deserialize_with = "deserialize_python_string")]
    company: String,
    #[serde(default, deserialize_with = "deserialize_python_string")]
    company_name: String,
    #[serde(default, deserialize_with = "deserialize_optional_string_list")]
    companies: Option<Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_python_string")]
    batch_file: String,
    #[serde(default, deserialize_with = "deserialize_python_string")]
    file_path: String,
}

impl EnterpriseRequest {
    fn companies(self) -> Result<Vec<String>, String> {
        let mut values = if let Some(values) = self.companies {
            values
        } else if !self.company.trim().is_empty() {
            vec![self.company]
        } else if !self.company_name.trim().is_empty() {
            vec![self.company_name]
        } else {
            let path = if self.batch_file.trim().is_empty() {
                self.file_path.trim()
            } else {
                self.batch_file.trim()
            };
            if path.is_empty() {
                Vec::new()
            } else {
                read_lines_file(std::path::Path::new(path))?
            }
        };
        values = values
            .into_iter()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .collect();
        Ok(values)
    }
}

fn parse_payload<T: DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone())
        .map_err(|error| format!("企业查询请求字段无效: {error}"))
}

fn source_cookie(config: &Value, source: EnterpriseSource) -> String {
    let section = match source {
        EnterpriseSource::Tianyancha => "tyc",
        EnterpriseSource::Aiqicha => "aiqicha",
    };
    config
        .get(section)
        .and_then(Value::as_object)
        .and_then(|object| object.get("cookie").and_then(python_string))
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn parse_provider_response(
    source: EnterpriseSource,
    query: &str,
    content_type: &str,
    body: &str,
) -> Result<Value, String> {
    let _is_json = content_type.to_ascii_lowercase().contains("json");
    let parsed = serde_json::from_str::<Value>(body).ok();
    let value = parsed.or_else(|| extract_embedded_json(body).into_iter().next());
    let Some(value) = value else {
        return Err("未找到可解析的企业信息".to_string());
    };

    if source == EnterpriseSource::Aiqicha {
        if value.get("basic_info").is_some() {
            let mut result = value;
            if result.get("company_name").is_none() {
                result["company_name"] = Value::String(query.to_string());
            }
            return Ok(result);
        }
        let candidate = find_company_list(&value)
            .and_then(|list| list.first())
            .cloned()
            .unwrap_or_else(|| value.clone());
        return Ok(aiqicha_result(query, &candidate));
    }

    if value.get("companies").is_some() && value.get("success").is_some() {
        return Ok(value);
    }
    let companies = find_company_list(&value)
        .map(|list| list.iter().map(normalize_tyc_company).collect::<Vec<_>>())
        .unwrap_or_default();
    if companies.is_empty() {
        return Err("未找到企业信息".to_string());
    }
    Ok(json!({"success": true, "companies": companies, "query": query}))
}

fn extract_embedded_json(body: &str) -> Vec<Value> {
    let mut values = Vec::new();
    let mut cursor = 0usize;
    while let Some(start) = body[cursor..].find("<script") {
        let absolute_start = cursor + start;
        let Some(tag_end_rel) = body[absolute_start..].find('>') else {
            break;
        };
        let content_start = absolute_start + tag_end_rel + 1;
        let Some(end_rel) = body[content_start..].find("</script>") else {
            break;
        };
        let content_end = content_start + end_rel;
        let text = body[content_start..content_end].trim();
        if !text.is_empty() {
            let unescaped_json = text.replace(r#"\""#, "\"");
            if let Ok(value) = serde_json::from_str::<Value>(text) {
                values.push(value);
            } else if let Ok(value) = serde_json::from_str::<Value>(&unescaped_json) {
                values.push(value);
            } else if let Some(value) = balanced_json_value(text) {
                values.push(value);
            } else if let Some(value) = balanced_json_value(&unescaped_json) {
                values.push(value);
            }
        }
        cursor = content_end + "</script>".len();
    }
    values
}

fn balanced_json_value(text: &str) -> Option<Value> {
    let start = text.find(['{', '['])?;
    let bytes = text.as_bytes();
    let mut stack = Vec::<u8>::new();
    let mut quoted = false;
    let mut escaped = false;
    for (offset, byte) in bytes[start..].iter().enumerate() {
        if quoted {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                quoted = false;
            }
            continue;
        }
        match *byte {
            b'"' => quoted = true,
            b'{' | b'[' => stack.push(*byte),
            b'}' | b']' => {
                let expected = if *byte == b'}' { b'{' } else { b'[' };
                if stack.last().copied() != Some(expected) {
                    return None;
                }
                stack.pop();
                if stack.is_empty() {
                    return serde_json::from_str(&text[start..start + offset + 1]).ok();
                }
            }
            _ => {}
        }
    }
    None
}

fn find_company_list(value: &Value) -> Option<&Vec<Value>> {
    if let Some(object) = value.as_object() {
        for key in ["companyList", "resultList", "companies", "list"] {
            if let Some(list) = object.get(key).and_then(Value::as_array) {
                return Some(list);
            }
        }
        for key in [
            "data",
            "result",
            "props",
            "pageProps",
            "dehydratedState",
            "state",
        ] {
            if let Some(nested) = object.get(key) {
                if let Some(found) = find_company_list(nested) {
                    return Some(found);
                }
            }
        }
    }
    if let Some(list) = value.as_array() {
        for item in list {
            if let Some(found) = find_company_list(item) {
                return Some(found);
            }
        }
    }
    None
}

fn normalize_tyc_company(value: &Value) -> Value {
    let object = value.as_object().cloned().unwrap_or_default();
    json!({
        "id": first_value(&object, &["id", "pid", "companyId"]),
        "name": first_value(&object, &["name", "companyName", "entName"]),
        "legalPersonName": first_value(&object, &["legalPersonName", "legalPerson", "legal_person"]),
        "regCapital": first_value(&object, &["regCapital", "regCap", "reg_capital"]),
        "creditCode": first_value(&object, &["creditCode", "regNo", "credit_code"]),
        "regLocation": first_value(&object, &["regLocation", "titleDomicile", "address"]),
        "phoneList": first_present_value(&object, &["phoneList", "phone", "telephone"], json!([])),
        "emailList": first_present_value(&object, &["emailList", "email"], json!([])),
        "websites": first_present_value(&object, &["websites", "website", "webSite"], json!("")),
        "categoryNameLv1": first_value(&object, &["categoryNameLv1", "industryCode1"]),
        "categoryNameLv2": first_value(&object, &["categoryNameLv2", "industryCode2"]),
        "categoryNameLv3": first_value(&object, &["categoryNameLv3", "industryCode3"]),
        "categoryNameLv4": first_value(&object, &["categoryNameLv4", "industryCode4"]),
    })
}

fn aiqicha_result(query: &str, value: &Value) -> Value {
    let object = value.as_object().cloned().unwrap_or_default();
    let basic = object
        .get("basic_info")
        .or_else(|| object.get("basicInfo"))
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_else(|| object.clone());
    let industry = object
        .get("industry_info")
        .or_else(|| object.get("industryMore"))
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    json!({
        "company_name": first_value(&object, &["company_name", "companyName", "name", "entName"]).if_empty_then(query),
        "basic_info": {
            "legalPerson": first_value(&basic, &["legalPerson", "legalPersonName"]),
            "titleDomicile": first_value(&basic, &["titleDomicile", "regLocation", "address"]),
            "regCap": first_value(&basic, &["regCap", "regCapital"]),
            "regNo": first_value(&basic, &["regNo", "creditCode"]),
            "email": first_value(&basic, &["email"]),
            "website": first_value(&basic, &["website", "webSite"]),
            "telephone": first_value(&basic, &["telephone", "phone"]),
            "entName": first_value(&basic, &["entName", "name", "companyName"]),
        },
        "industry_info": {
            "industryCode1": first_value(&industry, &["industryCode1"]),
            "industryCode2": first_value(&industry, &["industryCode2"]),
            "industryCode3": first_value(&industry, &["industryCode3"]),
            "industryCode4": first_value(&industry, &["industryCode4"]),
            "industryNum": first_value(&industry, &["industryNum"]),
        },
        "icp_info": array_or_empty(object.get("icp_info").or_else(|| object.get("icpInfo"))),
        "app_info": array_or_empty(object.get("app_info").or_else(|| object.get("appInfo"))),
        "wechat_info": array_or_empty(object.get("wechat_info").or_else(|| object.get("wechatInfo"))),
        "contact_info": array_or_empty(object.get("contact_info").or_else(|| object.get("contactInfo"))),
    })
}

fn raw_success(source: EnterpriseSource, raw: &Value) -> bool {
    raw.get("success")
        .and_then(Value::as_bool)
        .unwrap_or_else(|| source == EnterpriseSource::Aiqicha && raw.get("basic_info").is_some())
}

fn raw_error(raw: &Value) -> Option<String> {
    ["error", "message"]
        .iter()
        .filter_map(|key| raw.get(*key).and_then(python_string))
        .map(|value| value.trim().to_string())
        .find(|value| !value.is_empty())
}

fn failure_raw(_source: EnterpriseSource, query: &str, error: &str) -> Value {
    json!({"success": false, "error": error, "query": query, "companies": []})
}

fn enterprise_row(
    source: EnterpriseSource,
    index: usize,
    query: &str,
    success: bool,
    data: Value,
    error: &str,
) -> Value {
    let object = data.as_object().cloned().unwrap_or_default();
    let (name, legal, credit, capital, phone, email, website, address, industry) = match source {
        EnterpriseSource::Tianyancha => {
            let company = object
                .get("companies")
                .and_then(Value::as_array)
                .and_then(|items| items.first())
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_else(|| object.clone());
            (
                first_value(&company, &["name", "company_name"]).if_empty_then(query),
                first_value(&company, &["legalPersonName", "legal_person"]),
                first_value(&company, &["creditCode", "credit_code"]),
                first_value(&company, &["regCapital", "reg_capital"]),
                first_value(&company, &["phoneList", "phone", "telephone"]),
                first_value(&company, &["emailList", "email"]),
                first_value(&company, &["websites", "website"]),
                first_value(&company, &["regLocation", "address"]),
                String::new(),
            )
        }
        EnterpriseSource::Aiqicha => {
            let basic = object
                .get("basic_info")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            (
                first_value(&object, &["company_name"]).if_empty_then(query),
                first_value(&basic, &["legalPerson", "legalPersonName"]),
                first_value(&basic, &["regNo", "creditCode"]),
                first_value(&basic, &["regCap", "regCapital"]),
                first_value(&basic, &["telephone", "phone"]),
                first_value(&basic, &["email"]),
                first_value(&basic, &["website"]),
                first_value(&basic, &["titleDomicile", "address"]),
                first_value(
                    object
                        .get("industry_info")
                        .and_then(Value::as_object)
                        .unwrap_or(&Map::new()),
                    &["industryCode1", "industryCode2", "industryNum"],
                ),
            )
        }
    };
    json!({
        "index": index,
        "source": source.label(),
        "query": query,
        "success": success,
        "company_name": name,
        "legal_person": legal,
        "credit_code": credit,
        "reg_capital": capital,
        "phone": phone,
        "email": email,
        "website": website,
        "address": address,
        "industry": industry,
        "error": error,
        "raw": data,
    })
}

fn format_single(source: EnterpriseSource, raw: &Value) -> String {
    if !raw_success(source, raw) {
        return format!(
            "查询失败: {}",
            raw_error(raw).unwrap_or_else(|| "未获取到企业信息".to_string())
        );
    }
    let rows = raw
        .get("companies")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_else(|| vec![raw.clone()]);
    let mut output = vec!["企业查询结果".to_string(), "=".repeat(50)];
    for (index, item) in rows.iter().enumerate() {
        let object = item.as_object().cloned().unwrap_or_default();
        let name = first_value(&object, &["name", "company_name"]).if_empty_then("未知");
        output.push(format!("\n[{}] {name}", index + 1));
        match source {
            EnterpriseSource::Tianyancha => {
                output.push(format!(
                    "法定代表人: {}",
                    first_value(&object, &["legalPersonName"]).if_empty_then("未知")
                ));
                output.push(format!(
                    "注册资本: {}",
                    first_value(&object, &["regCapital"]).if_empty_then("未知")
                ));
                output.push(format!(
                    "统一社会信用代码: {}",
                    first_value(&object, &["creditCode"]).if_empty_then("未知")
                ));
                output.push(format!(
                    "注册地址: {}",
                    first_value(&object, &["regLocation"]).if_empty_then("未知")
                ));
            }
            EnterpriseSource::Aiqicha => {
                let basic = object
                    .get("basic_info")
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_else(|| object.clone());
                output.push(format!(
                    "法定代表人: {}",
                    first_value(&basic, &["legalPerson", "legalPersonName"])
                        .if_empty_then("未获取到")
                ));
                output.push(format!(
                    "企业地址: {}",
                    first_value(&basic, &["titleDomicile", "address"]).if_empty_then("未获取到")
                ));
                output.push(format!(
                    "注册资本: {}",
                    first_value(&basic, &["regCap", "regCapital"]).if_empty_then("未获取到")
                ));
                output.push(format!(
                    "统一社会信用代码: {}",
                    first_value(&basic, &["regNo", "creditCode"]).if_empty_then("未获取到")
                ));
            }
        }
    }
    output.join("\n")
}

fn format_batch(source: EnterpriseSource, raw: &Value) -> String {
    let total = raw.get("total").and_then(Value::as_u64).unwrap_or(0);
    let success = raw
        .get("success_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let failed = raw
        .get("failure_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let mut output = vec![
        format!("{}批量查询结果", source.display_name()),
        "=".repeat(50),
        format!("总查询数量: {total}"),
        format!("成功查询: {success}"),
        format!("失败查询: {failed}"),
        format!(
            "成功率: {:.1}%",
            if total == 0 {
                0.0
            } else {
                success as f64 * 100.0 / total as f64
            }
        ),
    ];
    if let Some(items) = raw.get("results").and_then(Value::as_array) {
        output.push("\n详细结果:".to_string());
        for (index, item) in items.iter().enumerate() {
            let company = item
                .get("company")
                .and_then(python_string)
                .unwrap_or_default();
            if item
                .get("success")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                output.push(format!("{}. 成功 {company}", index + 1));
            } else {
                output.push(format!(
                    "{}. 失败 {company}: {}",
                    index + 1,
                    item.get("error")
                        .and_then(python_string)
                        .unwrap_or_default()
                ));
            }
        }
    }
    output.join("\n")
}

fn is_challenge(body: &str) -> bool {
    let lower = body.to_ascii_lowercase();
    [
        "captcha",
        "验证码",
        "人机验证",
        "安全验证",
        "risk control",
        "风控",
        "请登录",
        "login required",
    ]
    .iter()
    .any(|needle| lower.contains(&needle.to_ascii_lowercase()))
}

fn is_login_error(error: &str) -> bool {
    ["WebView2", "登录", "风控", "captcha", "验证码"]
        .iter()
        .any(|needle| error.contains(needle))
}

/// The login WebView is a browser capability, so navigation is constrained to
/// the provider's own registrable domain.  This still permits Tianyancha's
/// login subdomains and Baidu Passport while preventing a challenge page from
/// navigating the dedicated profile to an unrelated site.
pub(crate) fn login_navigation_allowed(source: EnterpriseSource, url: &url::Url) -> bool {
    if url.scheme() != "https"
        || url.username() != ""
        || url.password().is_some()
        || url.port_or_known_default() != Some(443)
    {
        return false;
    }
    let Some(host) = url.host_str().map(str::to_ascii_lowercase) else {
        return false;
    };
    match source {
        EnterpriseSource::Tianyancha => {
            host == "tianyancha.com" || host.ends_with(".tianyancha.com")
        }
        EnterpriseSource::Aiqicha => host == "baidu.com" || host.ends_with(".baidu.com"),
    }
}

/// Convert WebView2 cookies to an HTTP Cookie header only after provider-
/// specific login evidence is present.  Cookie names/values containing header
/// delimiters are discarded instead of being forwarded to reqwest.
pub(crate) fn login_cookie_header(
    source: EnterpriseSource,
    cookies: impl IntoIterator<Item = (String, String)>,
) -> Option<String> {
    let mut safe = BTreeMap::<String, String>::new();
    for (name, value) in cookies {
        let name = name.trim();
        let value = value.trim();
        if name.is_empty()
            || value.is_empty()
            || !name.bytes().all(cookie_name_byte)
            || value.contains(['\r', '\n', ';'])
        {
            continue;
        }
        safe.insert(name.to_string(), value.to_string());
    }
    if !has_login_cookie_signal(source, &safe) {
        return None;
    }
    Some(
        safe.into_iter()
            .map(|(name, value)| format!("{name}={value}"))
            .collect::<Vec<_>>()
            .join("; "),
    )
}

fn cookie_name_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric()
        || matches!(
            byte,
            b'!' | b'#'
                | b'$'
                | b'%'
                | b'&'
                | b'\''
                | b'*'
                | b'+'
                | b'-'
                | b'.'
                | b'^'
                | b'_'
                | b'`'
                | b'|'
                | b'~'
        )
}

fn has_login_cookie_signal(source: EnterpriseSource, cookies: &BTreeMap<String, String>) -> bool {
    match source {
        EnterpriseSource::Tianyancha => {
            if cookies.contains_key("tyc-user-info") {
                return true;
            }
            let key_count = [
                "HWWAFSESTIME",
                "HWWAFSESID",
                "tyc-user-info",
                "auth_token",
                "sessionid",
            ]
            .iter()
            .filter(|key| cookies.contains_key(**key))
            .count();
            if key_count >= 3 {
                return true;
            }
            let tyc_count = cookies
                .keys()
                .filter(|name| {
                    let lower = name.to_ascii_lowercase();
                    lower.contains("tyc") || lower.contains("tianyancha")
                })
                .count();
            let has_user_marker = cookies.keys().any(|name| {
                let lower = name.to_ascii_lowercase();
                ["user", "auth", "login", "token"]
                    .iter()
                    .any(|marker| lower.contains(marker))
            });
            tyc_count > 2 && cookies.len() > 8 && has_user_marker
        }
        EnterpriseSource::Aiqicha => {
            if cookies.get("BDUSS").is_some_and(|value| value.len() > 16)
                || cookies
                    .get("BDUSS_BFESS")
                    .is_some_and(|value| value.len() > 16)
                || cookies.contains_key("STOKEN")
                || cookies.contains_key("PTOKEN")
            {
                return true;
            }
            let userish = cookies
                .keys()
                .filter(|name| {
                    let upper = name.to_ascii_uppercase();
                    ["BDUSS", "TOKEN", "PASS", "UID", "USER", "LOGIN", "BAIDU"]
                        .iter()
                        .any(|marker| upper.contains(marker))
                })
                .count();
            userish >= 2 && cookies.len() >= 10
        }
    }
}

fn first_value(object: &Map<String, Value>, keys: &[&str]) -> String {
    for key in keys {
        if let Some(value) = object.get(*key) {
            let text = value_to_text(value);
            if !text.is_empty() {
                return text;
            }
        }
    }
    String::new()
}

fn first_present_value(object: &Map<String, Value>, keys: &[&str], default: Value) -> Value {
    for key in keys {
        if let Some(value) = object.get(*key) {
            return value.clone();
        }
    }
    default
}

fn array_or_empty(value: Option<&Value>) -> Value {
    value
        .filter(|value| value.is_array())
        .cloned()
        .unwrap_or_else(|| json!([]))
}

fn value_to_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(value) => value.trim().to_string(),
        Value::Array(values) => values
            .iter()
            .map(value_to_text)
            .filter(|v| !v.is_empty())
            .collect::<Vec<_>>()
            .join(", "),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::Object(_) => String::new(),
    }
}

trait StringFallback {
    fn if_empty_then(self, fallback: &str) -> String;
}

impl StringFallback for String {
    fn if_empty_then(self, fallback: &str) -> String {
        if self.is_empty() {
            fallback.to_string()
        } else {
            self
        }
    }
}

fn python_string(value: &Value) -> Option<String> {
    let text = value_to_text(value);
    if text.is_empty() {
        None
    } else {
        Some(text)
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

fn deserialize_python_string<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(if python_truthy(&value) {
        python_display(&value)
    } else {
        String::new()
    })
}

fn deserialize_optional_string_list<'de, D>(
    deserializer: D,
) -> Result<Option<Vec<String>>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    match value {
        Value::Null => Ok(None),
        Value::Array(values) => Ok(Some(
            values
                .iter()
                .map(python_display)
                .filter(|v| !v.is_empty())
                .collect(),
        )),
        // Python's compatibility helper only accepts a real list for the
        // `companies` field; scalar values fall through to `company`/
        // `company_name`/batch-file resolution.
        Value::String(_) | Value::Bool(_) | Value::Number(_) | Value::Object(_) => Ok(None),
    }
}

fn sanitize_text(text: &str, secrets: &[&str]) -> String {
    let mut value = text.to_string();
    for secret in secrets.iter().copied().filter(|secret| !secret.is_empty()) {
        value = value.replace(secret, "[REDACTED]");
    }
    value
}

fn sanitize_cookie_text(text: &str, cookie: &str) -> String {
    let parts = cookie
        .split(';')
        .flat_map(|part| {
            let part = part.trim();
            [
                Some(part),
                part.split_once('=').map(|(_, value)| value.trim()),
            ]
        })
        .filter(|part| part.is_some_and(|part| !part.is_empty()))
        .flatten()
        .collect::<Vec<_>>();
    sanitize_text(text, &parts)
}

fn redact_cookie_value(value: &mut Value, cookie: &str) {
    if cookie.is_empty() {
        return;
    }
    let parts = cookie
        .split(';')
        .flat_map(|part| {
            let part = part.trim();
            [
                Some(part),
                part.split_once('=').map(|(_, value)| value.trim()),
            ]
        })
        .filter(|part| part.is_some_and(|part| !part.is_empty()))
        .flatten()
        .collect::<Vec<_>>();
    match value {
        Value::String(text) => {
            for part in &parts {
                *text = text.replace(part, "[REDACTED]");
            }
        }
        Value::Array(values) => values
            .iter_mut()
            .for_each(|value| redact_cookie_value(value, cookie)),
        Value::Object(object) => object
            .values_mut()
            .for_each(|value| redact_cookie_value(value, cookie)),
        _ => {}
    }
}

fn validate_endpoint(endpoint: &str) -> Result<(), String> {
    let url = reqwest::Url::parse(endpoint)
        .map_err(|error| format!("企业查询 endpoint 无效: {error}"))?;
    let scheme = url.scheme();
    if scheme == "https" {
        return Ok(());
    }
    if scheme == "http" {
        let host = url.host_str().unwrap_or_default().to_ascii_lowercase();
        if matches!(host.as_str(), "localhost" | "127.0.0.1" | "::1") {
            return Ok(());
        }
    }
    Err("企业查询 endpoint 必须使用 HTTPS（测试仅允许 loopback HTTP）".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::mpsc;

    struct MockReply {
        status: u16,
        content_type: &'static str,
        body: String,
    }

    fn mock_server(
        replies: Vec<MockReply>,
    ) -> (String, mpsc::Receiver<String>, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock server");
        let address = listener.local_addr().expect("mock address");
        let (tx, rx) = mpsc::channel();
        let handle = thread::spawn(move || {
            for reply in replies {
                let (mut stream, _) = listener.accept().expect("accept request");
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .expect("timeout");
                let mut buffer = [0_u8; 8192];
                let count = stream.read(&mut buffer).expect("read request");
                tx.send(String::from_utf8_lossy(&buffer[..count]).to_string())
                    .expect("capture request");
                let response = format!(
                    "HTTP/1.1 {} OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    reply.status, reply.content_type, reply.body.len(), reply.body
                );
                stream
                    .write_all(response.as_bytes())
                    .expect("write response");
            }
        });
        (format!("http://{}", address), rx, handle)
    }

    fn service(base: &str, max_response_bytes: usize) -> EnterpriseQueryService {
        EnterpriseQueryService::new(
            EnterpriseEndpoints {
                tyc_search: format!("{base}/tyc"),
                aiqicha_search: format!("{base}/aiqicha"),
            },
            EnterpriseRetryPolicy {
                max_attempts: 1,
                request_timeout: Duration::from_secs(2),
                max_response_bytes,
                batch_interval: Duration::ZERO,
            },
            Arc::new(FailClosedLoginBoundary),
        )
        .expect("service")
    }

    struct StaticCookieBoundary {
        cookie: String,
        calls: Arc<AtomicUsize>,
    }

    impl WebView2LoginBoundary for StaticCookieBoundary {
        fn obtain_cookie(
            &self,
            _source: EnterpriseSource,
            _target_url: &str,
        ) -> Result<Option<String>, String> {
            self.calls.fetch_add(1, Ordering::Relaxed);
            Ok(Some(self.cookie.clone()))
        }
    }

    #[test]
    fn missing_cookie_is_deterministic_and_does_not_call_network_or_leak() {
        let service = service("http://127.0.0.1:9", 4096);
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company": "Acme"}),
                &json!({"tyc": {"cookie": ""}}),
            )
            .expect("result");
        assert_eq!(result["success"], false);
        assert_eq!(result["source"], "tyc");
        assert!(result["message"]
            .as_str()
            .unwrap()
            .contains("Cookie 未配置"));
        assert!(result["message"]
            .as_str()
            .unwrap()
            .contains("当前构建未提供登录窗口"));
        assert_eq!(result["rows"][0]["company_name"], "Acme");
        assert_eq!(result["raw"]["companies"], json!([]));
    }

    #[test]
    fn invalid_input_preserves_python_outer_error_semantics() {
        let service = service("http://127.0.0.1:9", 4096);
        let error = service
            .dispatch(AIQICHA_COMMAND, &json!({}), &json!({}))
            .expect_err("empty input must fail");
        assert_eq!(error, "请输入企业名称或选择批量文件");
    }

    #[test]
    fn parses_tyc_embedded_next_data_and_redacts_cookie() {
        let body = r#"<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"dehydratedState":{"queries":[{"state":{"data":{"companyList":[{"id":"1","name":"Acme","legalPersonName":"Ada","creditCode":"C1","regCapital":"10万"}]}}}]}}}}</script></html>"#;
        let _ = body;
        let body = r#"<html><script>{"companyList":[{"name":"Acme","legalPersonName":"Ada","creditCode":"C1","regCapital":"10"}]}</script></html>"#;
        let (base, requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: body.to_string(),
        }]);
        let service = service(&base, 4096);
        let cookie = "auth_token=secret-cookie";
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"Acme"}),
                &json!({"tyc":{"cookie":cookie}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(result["rows"][0]["company_name"], "Acme");
        assert!(!result.to_string().contains(cookie));
        let request = requests.recv().expect("request");
        assert!(request
            .to_ascii_lowercase()
            .contains("cookie: auth_token=secret-cookie"));
        server.join().expect("server");
    }

    #[test]
    fn batch_preserves_order_and_reports_partial_failure() {
        let ok_body = r#"{"success":true,"companies":[{"name":"A","creditCode":"A1"}]}"#;
        let blocked = "<html>captcha required</html>";
        let (base, _requests, server) = mock_server(vec![
            MockReply {
                status: 200,
                content_type: "application/json",
                body: ok_body.to_string(),
            },
            MockReply {
                status: 200,
                content_type: "text/html",
                body: blocked.to_string(),
            },
        ]);
        let service = service(&base, 4096);
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"companies":["A","B"]}),
                &json!({"tyc":{"cookie":"cookie"}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(result["rows"][0]["query"], "A");
        assert_eq!(result["rows"][1]["query"], "B");
        assert_eq!(result["raw"]["success_count"], 1);
        server.join().expect("server");
    }

    #[test]
    fn challenge_uses_isolated_boundary_cookie_once_then_retries() {
        let success_body = r#"{"success":true,"companies":[{"name":"A","creditCode":"A1"}]}"#;
        let (base, requests, server) = mock_server(vec![
            MockReply {
                status: 200,
                content_type: "text/html",
                body: "captcha required".to_string(),
            },
            MockReply {
                status: 200,
                content_type: "application/json",
                body: success_body.to_string(),
            },
        ]);
        let calls = Arc::new(AtomicUsize::new(0));
        let service = EnterpriseQueryService::new(
            EnterpriseEndpoints {
                tyc_search: format!("{base}/tyc"),
                aiqicha_search: format!("{base}/aiqicha"),
            },
            EnterpriseRetryPolicy {
                max_attempts: 1,
                request_timeout: Duration::from_secs(2),
                max_response_bytes: 4096,
                batch_interval: Duration::ZERO,
            },
            Arc::new(StaticCookieBoundary {
                cookie: "browser-cookie=private".to_string(),
                calls: Arc::clone(&calls),
            }),
        )
        .expect("service");
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"A"}),
                &json!({"tyc":{"cookie":"old-cookie"}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(calls.load(Ordering::Relaxed), 1);
        let first = requests.recv().expect("first request");
        let second = requests.recv().expect("second request");
        assert!(first.to_ascii_lowercase().contains("cookie: old-cookie"));
        assert!(second
            .to_ascii_lowercase()
            .contains("cookie: browser-cookie=private"));
        assert!(!result.to_string().contains("browser-cookie=private"));
        server.join().expect("server");
    }

    #[test]
    fn response_limit_fails_closed() {
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "application/json",
            body: "x".repeat(1024),
        }]);
        let service = service(&base, 64);
        let result = service
            .dispatch(
                AIQICHA_COMMAND,
                &json!({"company":"A"}),
                &json!({"aiqicha":{"cookie":"cookie"}}),
            )
            .expect("structured result");
        assert_eq!(result["success"], false);
        assert!(result["message"].as_str().unwrap().contains("大小限制"));
        server.join().expect("server");
    }

    #[test]
    fn login_navigation_is_site_isolated() {
        assert!(login_navigation_allowed(
            EnterpriseSource::Tianyancha,
            &url::Url::parse("https://login.tianyancha.com/path").unwrap()
        ));
        assert!(!login_navigation_allowed(
            EnterpriseSource::Tianyancha,
            &url::Url::parse("https://tianyancha.com.attacker.test/").unwrap()
        ));
        assert!(login_navigation_allowed(
            EnterpriseSource::Aiqicha,
            &url::Url::parse("https://wappass.baidu.com/passport/").unwrap()
        ));
        assert!(!login_navigation_allowed(
            EnterpriseSource::Aiqicha,
            &url::Url::parse("http://aiqicha.baidu.com/").unwrap()
        ));
    }

    #[test]
    fn login_cookie_header_requires_provider_specific_evidence() {
        assert!(login_cookie_header(
            EnterpriseSource::Tianyancha,
            vec![("HWWAFSESID".into(), "only-one".into())]
        )
        .is_none());
        let tyc = login_cookie_header(
            EnterpriseSource::Tianyancha,
            vec![
                ("tyc-user-info".into(), "signed-user".into()),
                ("auth_token".into(), "secret".into()),
                ("bad".into(), "line\r\ninjection".into()),
            ],
        )
        .expect("valid Tianyancha login cookie");
        assert!(tyc.contains("tyc-user-info=signed-user"));
        assert!(!tyc.contains("injection"));

        assert!(login_cookie_header(
            EnterpriseSource::Aiqicha,
            vec![("BDUSS".into(), "short".into())]
        )
        .is_none());
        let aiqicha = login_cookie_header(
            EnterpriseSource::Aiqicha,
            vec![("BDUSS".into(), "12345678901234567".into())],
        )
        .expect("valid Aiqicha login cookie");
        assert_eq!(aiqicha, "BDUSS=12345678901234567");
    }
}
