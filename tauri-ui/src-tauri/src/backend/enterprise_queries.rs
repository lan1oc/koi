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

    pub(crate) fn display_name(self) -> &'static str {
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

    pub(crate) fn cookie_domain(self) -> &'static str {
        match self {
            Self::Tianyancha => "tianyancha.com",
            Self::Aiqicha => "baidu.com",
        }
    }

    pub(crate) fn login_title(self) -> String {
        format!("{} 登录", self.display_name())
    }
}

/// Result returned by the site-isolated browser boundary. Browser HTML is
/// parsed by the Rust core instead of being trusted as a normalized response,
/// and the final URL is independently checked before its contents are used.
#[derive(Debug, Clone, Default)]
pub struct BrowserPageCapture {
    pub cookie_header: Option<String>,
    pub page_html: Option<String>,
    pub final_url: Option<String>,
}

/// A browser implementation is intentionally injected. The Tauri shell
/// provides a site-isolated WebView2 profile; core-only builds fail closed.
pub trait WebView2LoginBoundary: Send + Sync {
    fn capture_page(
        &self,
        source: EnterpriseSource,
        target_url: &str,
        seed_cookie: &str,
    ) -> Result<BrowserPageCapture, String>;
}

#[derive(Debug, Default)]
pub struct FailClosedLoginBoundary;

impl WebView2LoginBoundary for FailClosedLoginBoundary {
    fn capture_page(
        &self,
        source: EnterpriseSource,
        _target_url: &str,
        _seed_cookie: &str,
    ) -> Result<BrowserPageCapture, String> {
        Err(format!(
            "{}需要在隔离浏览器中完成登录；当前构建未提供登录窗口",
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
            // `/nsearch` now returns a permanent same-origin redirect. Keep
            // the production endpoint on the canonical page so the request
            // never needs to replay a login cookie through redirect handling.
            tyc_search: "https://www.tianyancha.com/search".to_string(),
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

    #[cfg(test)]
    pub fn dispatch(
        &self,
        command: &str,
        payload: &Value,
        config: &Value,
    ) -> Result<Value, String> {
        self.dispatch_with_cookie_refresh(command, payload, config)
            .map(|(value, _)| value)
    }

    fn dispatch_with_cookie_refresh(
        &self,
        command: &str,
        payload: &Value,
        config: &Value,
    ) -> Result<(Value, Option<String>), String> {
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
        let mut refreshed_cookie = None;
        let mut result = if companies.len() == 1 {
            self.single(
                source,
                &companies[0],
                &configured_cookie,
                &mut refreshed_cookie,
            )
        } else {
            self.batch(
                source,
                &companies,
                &configured_cookie,
                &mut refreshed_cookie,
            )
        };

        redact_cookie_value(&mut result, &configured_cookie);
        if let Some(cookie) = refreshed_cookie.as_deref() {
            redact_cookie_value(&mut result, cookie);
        }
        Ok((result, refreshed_cookie))
    }

    fn single(
        &self,
        source: EnterpriseSource,
        company: &str,
        cookie: &str,
        refreshed_cookie: &mut Option<String>,
    ) -> Value {
        let response = self.query_one_with_boundary(source, company, cookie);
        match response {
            Ok((raw, refresh)) => {
                if refresh.is_some() {
                    *refreshed_cookie = refresh;
                }
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

    fn batch(
        &self,
        source: EnterpriseSource,
        companies: &[String],
        cookie: &str,
        refreshed_cookie: &mut Option<String>,
    ) -> Value {
        let mut result_items = Vec::with_capacity(companies.len());
        let mut rows = Vec::with_capacity(companies.len());
        let mut logs = Vec::new();
        let mut success_count = 0usize;
        let mut current_cookie = cookie.to_string();
        for (index, company) in companies.iter().enumerate() {
            if index > 0 && !self.retry.batch_interval.is_zero() {
                thread::sleep(self.retry.batch_interval);
            }
            match self.query_one_with_boundary(source, company, &current_cookie) {
                Ok((raw, refresh)) if raw_success(source, &raw) => {
                    if let Some(refresh) = refresh {
                        current_cookie = refresh.clone();
                        *refreshed_cookie = Some(refresh);
                    }
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
                Ok((raw, refresh)) => {
                    if let Some(refresh) = refresh {
                        current_cookie = refresh.clone();
                        *refreshed_cookie = Some(refresh);
                    }
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
                    let safe_error = sanitize_cookie_text(&error, &current_cookie);
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
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
                )
                .header("Accept-Language", "zh-CN,zh;q=0.9")
                .header(
                    "Accept",
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                )
                .header("Cache-Control", "max-age=0")
                .header("Upgrade-Insecure-Requests", "1")
                .header("Sec-Fetch-Site", "same-origin")
                .header("Sec-Fetch-Mode", "navigate")
                .header("Sec-Fetch-User", "?1")
                .header("Sec-Fetch-Dest", "document")
                .header(
                    "sec-ch-ua",
                    r#""Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141""#,
                )
                .header("sec-ch-ua-mobile", "?0")
                .header("sec-ch-ua-platform", r#""Windows""#);
            if source == EnterpriseSource::Tianyancha {
                request = request.header("Referer", format!("{endpoint}?key={company}"));
                if let Some(auth_token) = cookie_header_value(cookie, "auth_token") {
                    request = request.header("X-AUTH-TOKEN", auth_token);
                }
            }
            match self.send(request) {
                Ok((status, content_type, body)) => {
                    if (300..400).contains(&status) {
                        return Err(format!("HTTP {status}，需要隔离浏览器登录"));
                    } else if status >= 400 {
                        last_error = format!("HTTP {status}");
                    } else {
                        match parse_provider_response(source, company, &content_type, &body) {
                            Ok(value) => return Ok(value),
                            Err(_error) if is_challenge(&body) => {
                                return Err("检测到登录或风控验证，需要隔离浏览器登录".to_string())
                            }
                            Err(error) => last_error = error,
                        }
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
    ) -> Result<(Value, Option<String>), String> {
        let initial = if cookie.trim().is_empty() {
            Err(format!(
                "{} Cookie 未配置，需要隔离浏览器登录",
                source.display_name()
            ))
        } else {
            self.query_one(source, company, cookie)
        };
        let fallback_reason = match initial {
            Ok(value) => return Ok((value, None)),
            Err(error) if !should_use_browser_fallback(&error) => return Err(error),
            Err(error) => error,
        };

        let target_url = self.query_url(source, company)?;
        let capture = self
            .login
            .capture_page(source, &target_url, cookie)
            .map_err(|error| {
                sanitize_cookie_text(&format!("{fallback_reason}；{error}"), cookie)
            })?;
        validate_browser_capture(source, &capture, self.retry.max_response_bytes)?;

        let browser_cookie = capture
            .cookie_header
            .as_deref()
            .map(sanitize_cookie_header)
            .filter(|value| !value.is_empty());
        let mut browser_parse_error = None;
        if let Some(html) = capture
            .page_html
            .as_deref()
            .filter(|html| !html.trim().is_empty())
        {
            match parse_provider_response(source, company, "text/html", html) {
                Ok(value) => return Ok((value, browser_cookie)),
                Err(_) if is_challenge(html) => {
                    return Err(format!(
                        "{}隔离浏览器页面仍处于登录或风控验证状态",
                        source.display_name()
                    ))
                }
                Err(error) => browser_parse_error = Some(error),
            }
        }

        let Some(browser_cookie) = browser_cookie else {
            return Err(browser_parse_error.unwrap_or_else(|| {
                format!(
                    "{}隔离浏览器未返回可解析页面或有效 Cookie",
                    source.display_name()
                )
            }));
        };
        let value = self
            .query_one(source, company, &browser_cookie)
            .map_err(|retry_error| sanitize_cookie_text(&retry_error, &browser_cookie))?;
        Ok((value, Some(browser_cookie)))
    }

    fn query_url(&self, source: EnterpriseSource, company: &str) -> Result<String, String> {
        let endpoint = match source {
            EnterpriseSource::Tianyancha => &self.endpoints.tyc_search,
            EnterpriseSource::Aiqicha => &self.endpoints.aiqicha_search,
        };
        let mut url = url::Url::parse(endpoint)
            .map_err(|error| format!("企业查询 endpoint 无效: {error}"))?;
        {
            let mut pairs = url.query_pairs_mut();
            match source {
                EnterpriseSource::Tianyancha => {
                    pairs.append_pair("key", company);
                }
                EnterpriseSource::Aiqicha => {
                    pairs.append_pair("q", company).append_pair("t", "0");
                }
            }
        }
        Ok(url.into())
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

fn cookie_header_value<'a>(cookie: &'a str, wanted: &str) -> Option<&'a str> {
    cookie.split(';').find_map(|item| {
        let (name, value) = item.trim().split_once('=')?;
        (name.trim().eq_ignore_ascii_case(wanted) && !value.trim().is_empty()).then(|| value.trim())
    })
}

pub fn dispatch(command: &str, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
    let persisted = config.load()?;
    let source = EnterpriseSource::from_command(command)
        .ok_or_else(|| format!("未知企业查询命令: {command}"))?;
    let (mut result, refreshed_cookie) = EnterpriseQueryService::production()?
        .dispatch_with_cookie_refresh(command, payload, &persisted)?;
    if let Some(cookie) = refreshed_cookie.filter(|cookie| {
        !cookie.trim().is_empty() && cookie.trim() != source_cookie(&persisted, source)
    }) {
        match persist_refreshed_cookie(config, source, &cookie) {
            Ok(()) => append_result_log(
                &mut result,
                format!("{}浏览器登录态已安全更新", source.display_name()),
            ),
            Err(error) => append_result_log(
                &mut result,
                format!("{}浏览器登录态更新失败: {error}", source.display_name()),
            ),
        }
        redact_cookie_value(&mut result, &cookie);
    }
    Ok(result)
}

fn persist_refreshed_cookie(
    config: &ConfigStore,
    source: EnterpriseSource,
    cookie: &str,
) -> Result<(), String> {
    let section = source.key().to_string();
    let cookie = cookie.to_string();
    config.transact(move |value| {
        let root = value
            .as_object_mut()
            .ok_or_else(|| "配置根节点必须是对象".to_string())?;
        let section_value = root
            .entry(section.clone())
            .or_insert_with(|| Value::Object(Map::new()));
        let section_object = section_value
            .as_object_mut()
            .ok_or_else(|| format!("配置字段 {section} 必须是对象"))?;
        section_object.insert("cookie".to_string(), Value::String(cookie));
        section_object.insert(
            "last_updated".to_string(),
            Value::String(chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()),
        );
        Ok((Value::Null, true))
    })?;
    Ok(())
}

fn append_result_log(result: &mut Value, message: String) {
    let Some(object) = result.as_object_mut() else {
        return;
    };
    let logs = object
        .entry("logs".to_string())
        .or_insert_with(|| Value::Array(Vec::new()));
    if let Some(logs) = logs.as_array_mut() {
        logs.push(Value::String(message));
    }
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
    let mut values = Vec::new();
    if let Ok(value) = serde_json::from_str::<Value>(body) {
        values.push(value);
    }
    values.extend(extract_embedded_json(body));
    if values.is_empty() {
        return Err("未找到可解析的企业信息".to_string());
    }

    if source == EnterpriseSource::Aiqicha {
        for value in &values {
            if value.get("basic_info").is_some() && aiqicha_value_matches_query(value, query) {
                let mut result = value.clone();
                if result.get("company_name").is_none() {
                    result["company_name"] = Value::String(query.to_string());
                }
                return Ok(result);
            }
            if let Some(candidate) = find_best_aiqicha_candidate(value, query) {
                return Ok(aiqicha_result(query, candidate));
            }
        }
        return Err("未找到与查询名称匹配的企业信息".to_string());
    }

    for value in values {
        if value.get("companies").is_some() && value.get("success").is_some() {
            return Ok(value);
        }
        let companies = find_company_list(&value)
            .map(|list| list.iter().map(normalize_tyc_company).collect::<Vec<_>>())
            .unwrap_or_default();
        if !companies.is_empty() {
            return Ok(json!({"success": true, "companies": companies, "query": query}));
        }
    }
    Err("未找到企业信息".to_string())
}

fn aiqicha_value_matches_query(value: &Value, query: &str) -> bool {
    let Some(object) = value.as_object() else {
        return false;
    };
    let basic = object
        .get("basic_info")
        .or_else(|| object.get("basicInfo"))
        .and_then(Value::as_object);
    let name = first_value(
        object,
        &[
            "company_name",
            "companyName",
            "name",
            "entName",
            "titleName",
        ],
    )
    .if_empty_then(
        &basic
            .map(|basic| first_value(basic, &["entName", "companyName", "name"]))
            .unwrap_or_default(),
    );
    if company_name_match_score(query, &name) == 0 {
        return false;
    }
    basic.is_some_and(aiqicha_object_has_business_identity)
}

fn find_best_aiqicha_candidate<'a>(value: &'a Value, query: &str) -> Option<&'a Value> {
    fn visit<'a>(value: &'a Value, query: &str, depth: usize, best: &mut Option<(u8, &'a Value)>) {
        if depth > 64 {
            return;
        }
        match value {
            Value::Object(object) => {
                let name = first_value(
                    object,
                    &[
                        "company_name",
                        "companyName",
                        "entName",
                        "titleName",
                        "name",
                    ],
                );
                let score = company_name_match_score(query, &name);
                if score > best.map_or(0, |(best_score, _)| best_score)
                    && aiqicha_object_has_business_identity(object)
                {
                    *best = Some((score, value));
                }
                for nested in object.values() {
                    visit(nested, query, depth + 1, best);
                }
            }
            Value::Array(items) => {
                for item in items {
                    visit(item, query, depth + 1, best);
                }
            }
            _ => {}
        }
    }

    let mut best = None;
    visit(value, query, 0, &mut best);
    best.map(|(_, value)| value)
}

fn aiqicha_object_has_business_identity(object: &Map<String, Value>) -> bool {
    [
        "pid",
        "pidStr",
        "regNo",
        "creditCode",
        "legalPerson",
        "legalPersonName",
        "regCap",
        "regCapital",
        "titleDomicile",
        "regLocation",
        "openTime",
        "startDate",
    ]
    .iter()
    .any(|key| {
        object
            .get(*key)
            .and_then(python_string)
            .is_some_and(|value| !value.trim().is_empty())
    })
}

fn company_name_match_score(query: &str, candidate: &str) -> u8 {
    let query = normalize_company_name(query);
    let candidate = normalize_company_name(candidate);
    if candidate.is_empty() {
        return 0;
    }
    if query.is_empty() {
        return 1;
    }
    if query == candidate {
        return 100;
    }
    let query_core = company_name_core(&query);
    let candidate_core = company_name_core(&candidate);
    if query_core.chars().count() >= 4 && query_core == candidate_core {
        return 90;
    }
    if query_core.chars().count() >= 6
        && (query_core.contains(&candidate_core) || candidate_core.contains(&query_core))
    {
        return 80;
    }
    if query.chars().count() >= 8 && (query.contains(&candidate) || candidate.contains(&query)) {
        return 70;
    }
    if query.chars().count() <= 4 && candidate.contains(&query) {
        return 50;
    }
    0
}

fn normalize_company_name(value: &str) -> String {
    clean_html_text(value)
        .to_lowercase()
        .chars()
        .filter(|character| {
            !character.is_whitespace()
                && !matches!(
                    character,
                    '（' | '）'
                        | '('
                        | ')'
                        | '-'
                        | '_'
                        | '·'
                        | '.'
                        | ','
                        | '，'
                        | '。'
                        | '、'
                        | '/'
                )
        })
        .collect()
}

fn company_name_core(value: &str) -> String {
    for suffix in [
        "有限责任公司",
        "股份有限公司",
        "股份公司",
        "有限公司",
        "责任公司",
        "分公司",
        "总公司",
        "公司",
    ] {
        if value.ends_with(suffix) && value.chars().count() > suffix.chars().count() {
            return value[..value.len() - suffix.len()].to_string();
        }
    }
    value.to_string()
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
            "queries",
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
        "name": clean_html_text(&first_value(&object, &["name", "companyName", "entName"])),
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
        "company_name": clean_html_text(&first_value(&object, &["company_name", "companyName", "entName", "titleName", "name"])).if_empty_then(query),
        "company_id": first_value(&object, &["pid", "pidStr", "id", "companyId"]),
        "basic_info": {
            "legalPerson": first_value(&basic, &["legalPerson", "legalPersonName"]),
            "titleDomicile": first_value(&basic, &["titleDomicile", "regLocation", "address"]),
            "regCap": first_value(&basic, &["regCap", "regCapital"]),
            "regNo": first_value(&basic, &["regNo", "creditCode"]),
            "openTime": first_value(&basic, &["openTime", "startDate", "estiblishTime", "establishTime"]),
            "status": first_value(&basic, &["openStatus", "regStatus", "status"]),
            "email": first_value(&basic, &["email", "emailList"]),
            "website": first_value(&basic, &["website", "webSite"]),
            "telephone": first_value(&basic, &["telephone", "phone", "phoneList"]),
            "entName": clean_html_text(&first_value(&basic, &["entName", "titleName", "name", "companyName"])),
        },
        "industry_info": {
            "industryCode1": first_value(&industry, &["industryCode1", "industryNameLv1", "industry"]),
            "industryCode2": first_value(&industry, &["industryCode2", "industryNameLv2"]),
            "industryCode3": first_value(&industry, &["industryCode3", "industryNameLv3"]),
            "industryCode4": first_value(&industry, &["industryCode4", "industryNameLv4"]),
            "industryNum": first_value(&industry, &["industryNum", "industryCode"]),
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
        "antirobot",
        "验证码",
        "人机验证",
        "安全验证",
        "行为验证",
        "请进行身份验证以继续使用",
        "请完成安全验证",
        "risk control",
        "风控",
        "login required",
        "登录后查看",
        "请先登录",
        "扫码登录",
    ]
    .iter()
    .any(|needle| lower.contains(&needle.to_ascii_lowercase()))
}

fn is_login_error(error: &str) -> bool {
    [
        "WebView2",
        "隔离浏览器",
        "登录",
        "风控",
        "captcha",
        "验证码",
    ]
    .iter()
    .any(|needle| error.contains(needle))
}

fn should_use_browser_fallback(error: &str) -> bool {
    is_login_error(error)
        || [
            "Cookie 未配置",
            "未找到企业信息",
            "未找到与查询名称匹配",
            "未找到可解析的企业信息",
            "企业查询请求失败",
            "HTTP 3",
            "HTTP 401",
            "HTTP 403",
            "HTTP 429",
        ]
        .iter()
        .any(|marker| error.contains(marker))
}

fn validate_browser_capture(
    source: EnterpriseSource,
    capture: &BrowserPageCapture,
    configured_limit: usize,
) -> Result<(), String> {
    let final_url = capture
        .final_url
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| format!("{}隔离浏览器未返回最终 URL", source.display_name()))?;
    let final_url = url::Url::parse(final_url)
        .map_err(|error| format!("{}隔离浏览器最终 URL 无效: {error}", source.display_name()))?;
    if !login_navigation_allowed(source, &final_url) {
        return Err(format!(
            "{}隔离浏览器最终页面不在允许的站点范围内",
            source.display_name()
        ));
    }
    if capture
        .page_html
        .as_ref()
        .is_some_and(|html| html.len() > configured_limit.min(MAX_RESPONSE_BYTES))
    {
        return Err("企业查询隔离浏览器页面超过大小限制".to_string());
    }
    Ok(())
}

#[cfg_attr(test, allow(dead_code))]
pub(crate) fn browser_page_has_provider_data(source: EnterpriseSource, html: &str) -> bool {
    parse_provider_response(source, "", "text/html", html).is_ok()
}

#[cfg_attr(test, allow(dead_code))]
pub(crate) fn browser_page_has_provider_data_for_query(
    source: EnterpriseSource,
    query: &str,
    html: &str,
) -> bool {
    parse_provider_response(source, query, "text/html", html).is_ok()
}

#[cfg_attr(test, allow(dead_code))]
pub(crate) fn browser_page_requires_user_action(url: &url::Url, html: &str) -> bool {
    let route = format!(
        "{}{}",
        url.host_str().unwrap_or_default().to_ascii_lowercase(),
        url.path().to_ascii_lowercase()
    );
    [
        "captcha",
        "antirobot",
        "challenge",
        "verification",
        "passport",
        "/login",
    ]
    .iter()
    .any(|marker| route.contains(marker))
        || [
            "captcha.tianyancha.com",
            "antirobot.tianyancha.com",
            "请进行身份验证以继续使用",
            "请完成安全验证",
            "行为验证",
            "人机验证",
            "滑块验证",
        ]
        .iter()
        .any(|marker| {
            html.to_ascii_lowercase()
                .contains(&marker.to_ascii_lowercase())
        })
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
    let safe_pairs = cookies
        .into_iter()
        .filter_map(|(name, value)| safe_cookie_pair(&name, &value))
        .collect::<Vec<_>>();
    let safe = safe_pairs.iter().cloned().collect::<BTreeMap<_, _>>();
    if !has_login_cookie_signal(source, &safe) {
        return None;
    }
    Some(
        safe_pairs
            .into_iter()
            .map(|(name, value)| format!("{name}={value}"))
            .collect::<Vec<_>>()
            .join("; "),
    )
}

pub(crate) fn cookie_pairs_for_webview(header: &str) -> Vec<(String, String)> {
    header
        .split(';')
        .filter_map(|item| item.trim().split_once('='))
        .filter_map(|(name, value)| safe_cookie_pair(name, value))
        .collect()
}

fn sanitize_cookie_header(header: &str) -> String {
    cookie_pairs_for_webview(header)
        .into_iter()
        .map(|(name, value)| format!("{name}={value}"))
        .collect::<Vec<_>>()
        .join("; ")
}

fn safe_cookie_pair(name: &str, value: &str) -> Option<(String, String)> {
    let name = name.trim();
    let value = value.trim();
    if name.is_empty()
        || value.is_empty()
        || !name.bytes().all(cookie_name_byte)
        || value.contains(['\r', '\n', ';'])
    {
        return None;
    }
    Some((name.to_string(), value.to_string()))
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

fn clean_html_text(value: &str) -> String {
    static HTML_TAG: OnceLock<regex::Regex> = OnceLock::new();
    HTML_TAG
        .get_or_init(|| regex::Regex::new(r"<[^>]+>").expect("static HTML tag regex"))
        .replace_all(value, "")
        .trim()
        .to_string()
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
    let parts = cookie_redaction_parts(cookie);
    sanitize_text(text, &parts)
}

fn cookie_redaction_parts(cookie: &str) -> Vec<&str> {
    let mut parts = Vec::new();
    if !cookie.trim().is_empty() {
        parts.push(cookie.trim());
    }
    for pair in cookie
        .split(';')
        .map(str::trim)
        .filter(|part| !part.is_empty())
    {
        parts.push(pair);
        if let Some((_, value)) = pair.split_once('=') {
            let value = value.trim();
            // Short numeric cookie values also occur inside credit codes and
            // phone numbers. Redact the complete name=value pair, but only
            // redact standalone values when they are token-sized.
            if value.len() >= 16 {
                parts.push(value);
            }
        }
    }
    parts
}

fn redact_cookie_value(value: &mut Value, cookie: &str) {
    if cookie.is_empty() {
        return;
    }
    let parts = cookie_redaction_parts(cookie);
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
    use std::sync::Mutex;

    type RecordedValues = Arc<Mutex<Vec<String>>>;

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
        fn capture_page(
            &self,
            source: EnterpriseSource,
            _target_url: &str,
            _seed_cookie: &str,
        ) -> Result<BrowserPageCapture, String> {
            self.calls.fetch_add(1, Ordering::Relaxed);
            Ok(BrowserPageCapture {
                cookie_header: Some(self.cookie.clone()),
                page_html: None,
                final_url: Some(source.login_url().to_string()),
            })
        }
    }

    struct CapturingBoundary {
        capture: BrowserPageCapture,
        seeds: Arc<Mutex<Vec<String>>>,
        targets: Arc<Mutex<Vec<String>>>,
    }

    impl WebView2LoginBoundary for CapturingBoundary {
        fn capture_page(
            &self,
            _source: EnterpriseSource,
            target_url: &str,
            seed_cookie: &str,
        ) -> Result<BrowserPageCapture, String> {
            self.seeds.lock().unwrap().push(seed_cookie.to_string());
            self.targets.lock().unwrap().push(target_url.to_string());
            Ok(self.capture.clone())
        }
    }

    fn service_with_capture(
        base: &str,
        max_response_bytes: usize,
        capture: BrowserPageCapture,
    ) -> (EnterpriseQueryService, RecordedValues, RecordedValues) {
        let seeds = Arc::new(Mutex::new(Vec::new()));
        let targets = Arc::new(Mutex::new(Vec::new()));
        let service = EnterpriseQueryService::new(
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
            Arc::new(CapturingBoundary {
                capture,
                seeds: Arc::clone(&seeds),
                targets: Arc::clone(&targets),
            }),
        )
        .expect("service");
        (service, seeds, targets)
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
        let body = r#"<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"dehydratedState":{"queries":[{"state":{"data":{"data":{"companyList":[{"id":"1","name":"<em>Acme</em>","legalPersonName":"Ada","creditCode":"C1","regCapital":"10万"}]}}}}]}}}}</script></html>"#;
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
    fn valid_provider_data_wins_over_generic_login_copy() {
        let body = r#"<html><p>登录后查看更多功能</p><script>{"companyList":[{"name":"Acme","creditCode":"C1"}]}</script></html>"#;
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: body.to_string(),
        }]);
        let result = service(&base, 4096)
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"Acme"}),
                &json!({"tyc":{"cookie":"auth_token=seed"}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(result["rows"][0]["company_name"], "Acme");
        server.join().expect("server");
    }

    #[test]
    fn aiqicha_selects_matching_page_data_instead_of_navigation_list() {
        let body = r#"<html><script>{"list":[{"id":"nav","name":"爱企查"}]}</script><script>window.pageData = {"queryWord":"Acme Ltd","result":{"resultList":[{"pid":"p1","entName":"<em>Acme Ltd</em>","legalPerson":"Ada","regNo":"C1","regCapital":"10万"}]}};</script></html>"#;
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: body.to_string(),
        }]);
        let result = service(&base, 4096)
            .dispatch(
                AIQICHA_COMMAND,
                &json!({"company":"Acme Ltd"}),
                &json!({"aiqicha":{"cookie":"BDUSS=12345678901234567"}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(result["rows"][0]["company_name"], "Acme Ltd");
        assert_eq!(result["rows"][0]["legal_person"], "Ada");
        assert_eq!(result["rows"][0]["credit_code"], "C1");
        server.join().expect("server");
    }

    #[test]
    fn aiqicha_navigation_data_is_not_a_business_success() {
        let body = r#"<html><script>{"list":[{"id":"nav","name":"爱企查"}]}</script></html>"#;
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: body.to_string(),
        }]);
        let result = service(&base, 4096)
            .dispatch(
                AIQICHA_COMMAND,
                &json!({"company":"Acme Ltd"}),
                &json!({"aiqicha":{"cookie":"BDUSS=12345678901234567"}}),
            )
            .expect("result");
        assert_eq!(result["success"], false);
        assert_ne!(result["rows"][0]["company_name"], "爱企查");
        server.join().expect("server");
    }

    #[test]
    fn browser_html_is_parsed_before_http_retry_and_receives_seed_cookie() {
        let browser_html = r#"<html><p>登录后查看更多功能</p><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"dehydratedState":{"queries":[{"state":{"data":{"data":{"companyList":[{"id":"1","name":"<em>Acme</em>","creditCode":"C1"}]}}}}]}}}}</script></html>"#;
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: "captcha required".to_string(),
        }]);
        let capture = BrowserPageCapture {
            cookie_header: Some("auth_token=browser-secret".to_string()),
            page_html: Some(browser_html.to_string()),
            final_url: Some("https://www.tianyancha.com/search?key=Acme".to_string()),
        };
        let (service, seeds, targets) = service_with_capture(&base, 4096, capture);
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"Acme"}),
                &json!({"tyc":{"cookie":"auth_token=seed-secret"}}),
            )
            .expect("result");
        assert_eq!(result["success"], true);
        assert_eq!(result["rows"][0]["company_name"], "Acme");
        assert_eq!(seeds.lock().unwrap().as_slice(), ["auth_token=seed-secret"]);
        let targets = targets.lock().unwrap();
        assert_eq!(targets.len(), 1);
        assert!(targets[0].contains("/tyc?key=Acme"));
        assert!(!result.to_string().contains("browser-secret"));
        server.join().expect("server");
    }

    #[test]
    fn generic_login_copy_on_search_results_does_not_require_user_action() {
        let url = url::Url::parse("https://www.tianyancha.com/search?key=Acme").unwrap();
        assert!(!browser_page_requires_user_action(
            &url,
            "<html>登录后查看更多功能 登录/注册 <em>Acme</em></html>"
        ));
        assert!(browser_page_requires_user_action(
            &url::Url::parse("https://www.tianyancha.com/login?from=/search").unwrap(),
            "扫码登录"
        ));
        assert!(browser_page_requires_user_action(&url, "请完成安全验证"));
    }

    #[test]
    fn browser_capture_rejects_cross_site_final_url() {
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: "captcha required".to_string(),
        }]);
        let capture = BrowserPageCapture {
            cookie_header: Some("auth_token=browser-secret".to_string()),
            page_html: Some(r#"<script>{"companyList":[{"name":"Acme"}]}</script>"#.into()),
            final_url: Some("https://tianyancha.com.attacker.test/search?key=Acme".into()),
        };
        let (service, _, _) = service_with_capture(&base, 4096, capture);
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"Acme"}),
                &json!({"tyc":{"cookie":"auth_token=seed-secret"}}),
            )
            .expect("structured result");
        assert_eq!(result["success"], false);
        assert!(result["message"].as_str().unwrap().contains("站点范围"));
        assert!(!result.to_string().contains("browser-secret"));
        server.join().expect("server");
    }

    #[test]
    fn browser_capture_rejects_oversized_html() {
        let (base, _requests, server) = mock_server(vec![MockReply {
            status: 200,
            content_type: "text/html",
            body: "captcha required".to_string(),
        }]);
        let capture = BrowserPageCapture {
            cookie_header: Some("auth_token=browser-secret".to_string()),
            page_html: Some("x".repeat(65)),
            final_url: Some("https://www.tianyancha.com/search?key=Acme".into()),
        };
        let (service, _, _) = service_with_capture(&base, 64, capture);
        let result = service
            .dispatch(
                TYC_COMMAND,
                &json!({"company":"Acme"}),
                &json!({"tyc":{"cookie":"auth_token=seed-secret"}}),
            )
            .expect("structured result");
        assert_eq!(result["success"], false);
        assert!(result["message"].as_str().unwrap().contains("大小限制"));
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

    #[test]
    fn cookie_redaction_preserves_business_numbers() {
        let cookie = "short=37; phone_tail=0028; auth_token=secret-value-with-length";
        let mut result = json!({
            "creditCode":"91330200711192037M",
            "phone":"0574-87050028",
            "echo":"short=37; auth_token=secret-value-with-length",
            "secret":"secret-value-with-length"
        });
        redact_cookie_value(&mut result, cookie);
        assert_eq!(result["creditCode"], "91330200711192037M");
        assert_eq!(result["phone"], "0574-87050028");
        assert!(!result
            .to_string()
            .contains("auth_token=secret-value-with-length"));
        assert!(!result.to_string().contains("secret-value-with-length"));
    }
}
