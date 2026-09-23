//! Typed Rust transport for retest model configuration checks.

use super::config::ConfigStore;
use super::retest_config::{self, RuntimeAiProfile};
use reqwest::blocking::{Client, Response};
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use reqwest::{StatusCode, Url};
use serde::Serialize;
use serde_json::{json, Map, Value};
use std::error::Error as _;
use std::io::{BufRead, BufReader, Read};
use std::thread;
use std::time::{Duration, Instant};

const RESPONSE_LIMIT: u64 = 8 * 1024 * 1024;
// SSE includes envelopes, usage, reasoning and heartbeats for every token.
// Bound the wire, each event and the actual answer independently.
const SSE_WIRE_LIMIT: u64 = 64 * 1024 * 1024;
const SSE_EVENT_LIMIT: usize = 1024 * 1024;
const COMPLETION_TEXT_LIMIT: usize = 2 * 1024 * 1024;
const MODEL_REQUEST_TIMEOUT: Duration = Duration::from_secs(180);
const MODEL_ATTEMPTS: usize = 3;
const MODEL_RETRY_BUDGET: Duration = Duration::from_secs(240);
const OPENROUTER_DEFAULT_BASE_URL: &str = "https://openrouter.ai/api/v1";

#[derive(Debug, Clone)]
pub(crate) struct ModelCompletion {
    pub provider: String,
    pub model: String,
    pub content: String,
    pub json: Value,
}

pub fn dispatch(command: &str, payload: &Value, config: &ConfigStore) -> Result<Value, String> {
    match command {
        "doc.retest.ai_config.test" => test_configuration(config, payload),
        "doc.retest.ai_config.key_status" => key_status(config, payload),
        _ => Err(format!("native model command not registered: {command}")),
    }
}

pub(crate) fn complete_json(
    config: &ConfigStore,
    payload: &Value,
    system: &str,
    user: &Value,
) -> Result<ModelCompletion, String> {
    let profile = retest_config::runtime_profile(config, payload)?;
    let missing = missing_profile_fields(&profile);
    if !missing.is_empty() {
        return Err(format!("模型配置缺少 {}", missing.join("、")));
    }
    let user =
        serde_json::to_string(user).map_err(|error| format!("serialize model request: {error}"))?;
    complete_json_with_profile(&profile, system, &user)
}

/// Complete a JSON request while exposing provider-native text deltas.
///
/// The callback is deliberately synchronous and generation-agnostic here;
/// callers that own a session must perform their generation check before
/// accepting each delta. Keeping that policy above the transport prevents a
/// model client from accidentally mutating durable agent state.
pub(crate) fn complete_json_streaming(
    config: &ConfigStore,
    payload: &Value,
    system: &str,
    user: &Value,
    on_delta: &mut dyn FnMut(&str) -> bool,
) -> Result<ModelCompletion, String> {
    let profile = retest_config::runtime_profile(config, payload)?;
    let missing = missing_profile_fields(&profile);
    if !missing.is_empty() {
        return Err(format!("模型配置缺少 {}", missing.join("、")));
    }
    let user =
        serde_json::to_string(user).map_err(|error| format!("serialize model request: {error}"))?;
    complete_json_with_profile_stream(&profile, system, &user, Some(on_delta))
}

#[derive(Debug, Serialize)]
struct ModelTestResponse {
    success: bool,
    message: String,
    provider: String,
    model: String,
    elapsed_ms: u128,
    #[serde(skip_serializing_if = "Option::is_none")]
    reply: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

fn test_configuration(config: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let profile = retest_config::runtime_profile(config, payload)?;
    let missing = missing_profile_fields(&profile);
    if !missing.is_empty() {
        return to_value(ModelTestResponse {
            success: false,
            message: format!("模型测试失败：缺少 {}", missing.join("、")),
            provider: profile.provider,
            model: profile.model,
            elapsed_ms: 0,
            reply: None,
            error: None,
        });
    }

    let started = Instant::now();
    match complete_connectivity_json(&profile) {
        Ok(reply) => {
            let ok = reply.get("ok").and_then(Value::as_bool).unwrap_or(true);
            let detail = reply
                .get("message")
                .or_else(|| reply.get("reply"))
                .and_then(Value::as_str)
                .unwrap_or("模型已返回 JSON，通信正常")
                .trim();
            to_value(ModelTestResponse {
                success: ok,
                message: format!("模型测试{}：{detail}", if ok { "成功" } else { "失败" }),
                provider: profile.provider,
                model: profile.model,
                elapsed_ms: started.elapsed().as_millis(),
                // Providers occasionally echo request headers or credentials
                // in a diagnostic JSON field.  Keep the compatibility reply
                // shape, but apply the same recursive secret scrub used by
                // the key-status endpoint before exposing it to IPC/UI.
                reply: Some(python_json_dump(&sanitize_remote_value(
                    &reply,
                    &profile.api_key,
                    0,
                ))),
                error: None,
            })
        }
        Err(error) => {
            let error = redact_secret(&error, &profile.api_key);
            to_value(ModelTestResponse {
                success: false,
                message: format!("模型测试失败：{error}"),
                provider: profile.provider,
                model: profile.model,
                elapsed_ms: started.elapsed().as_millis(),
                reply: None,
                error: Some(error),
            })
        }
    }
}

fn missing_profile_fields(profile: &RuntimeAiProfile) -> Vec<&'static str> {
    let mut missing = Vec::new();
    if profile.api_key.trim().is_empty() {
        missing.push("API Key");
    }
    if profile.model.trim().is_empty() {
        missing.push("Model");
    }
    if profile.provider.trim().is_empty() || profile.provider == "auto" {
        missing.push("Provider");
    }
    missing
}

fn complete_connectivity_json(profile: &RuntimeAiProfile) -> Result<Value, String> {
    let system = "你是 KOI 的模型连通性检查器。只返回一个 JSON 对象。";
    let user = serde_json::to_string(&json!({
        "task": "请确认当前模型 API 是否可通信。",
        "schema": {"ok": true, "message": "一句中文测试结果"},
    }))
    .map_err(|error| format!("serialize connectivity request: {error}"))?;

    complete_json_with_profile(profile, system, &user).map(|completion| completion.json)
}

fn complete_json_with_profile(
    profile: &RuntimeAiProfile,
    system: &str,
    user: &str,
) -> Result<ModelCompletion, String> {
    complete_json_with_profile_stream(profile, system, user, None)
}

fn complete_json_with_profile_stream(
    profile: &RuntimeAiProfile,
    system: &str,
    user: &str,
    mut on_delta: Option<&mut dyn FnMut(&str) -> bool>,
) -> Result<ModelCompletion, String> {
    let (url, headers, body) = if profile.provider == "anthropic" {
        let url = append_endpoint(&profile.base_url, "messages")?;
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-api-key",
            secret_header(&profile.api_key, "Anthropic API Key")?,
        );
        headers.insert("anthropic-version", HeaderValue::from_static("2023-06-01"));
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        (
            url,
            headers,
            json!({
                "model": profile.model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": profile.temperature,
                "max_tokens": profile.max_tokens,
                "stream": true,
            }),
        )
    } else {
        let url = append_endpoint(&profile.base_url, "chat/completions")?;
        let mut headers = HeaderMap::new();
        headers.insert(
            AUTHORIZATION,
            secret_header(&format!("Bearer {}", profile.api_key), "Authorization")?,
        );
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        (
            url,
            headers,
            json!({
                "model": profile.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": profile.temperature,
                "max_tokens": profile.max_tokens,
                "response_format": {"type": "json_object"},
                "stream": true,
            }),
        )
    };

    let response = send_model_request(
        &http_client()?,
        &url,
        &headers,
        &body,
        &profile.api_key,
        &mut on_delta,
    )?;
    let is_sse = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.to_ascii_lowercase().contains("text/event-stream"));
    let text = if is_sse {
        read_sse_response(response, profile, &mut on_delta)?
    } else {
        let data = read_json_response(response, &profile.api_key)?;
        let text = if profile.provider == "anthropic" {
            data.get("content")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter(|block| block.get("type").and_then(Value::as_str) == Some("text"))
                .map(|block| {
                    block
                        .get("text")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                })
                .collect::<String>()
        } else {
            openai_content(&data)
        };
        if !text.is_empty() {
            if let Some(callback) = on_delta.as_mut() {
                let safe_text = redact_secret(&text, &profile.api_key);
                if !callback(&safe_text) {
                    return Err("模型流已取消".to_string());
                }
            }
        }
        text
    };
    let parsed = parse_json_object(&text).ok_or_else(|| "模型响应不是 JSON 对象".to_string())?;
    Ok(ModelCompletion {
        provider: profile.provider.clone(),
        model: profile.model.clone(),
        content: text,
        json: parsed,
    })
}

fn model_request_active(on_delta: &mut Option<&mut dyn FnMut(&str) -> bool>) -> Result<(), String> {
    // An empty delta is a heartbeat only; callers check cancellation without
    // appending a token or creating a new event.
    if on_delta.as_mut().is_some_and(|callback| !callback("")) {
        return Err("模型流已取消".to_string());
    }
    Ok(())
}

fn retryable_status(status: StatusCode) -> bool {
    matches!(status.as_u16(), 408 | 429 | 500 | 502 | 503 | 504)
}

fn transport_error_detail(error: reqwest::Error, secret: &str) -> String {
    let category = if error.is_timeout() {
        "模型请求超时"
    } else if error.is_connect() {
        "模型连接失败（请检查网络、DNS、TLS 或代理）"
    } else {
        "模型请求传输失败"
    };
    let error = error.without_url();
    let mut reasons = vec![error.to_string()];
    let mut source = error.source();
    for _ in 0..5 {
        let Some(cause) = source else { break };
        let text = cause.to_string();
        if !reasons.contains(&text) {
            reasons.push(text);
        }
        source = cause.source();
    }
    format!(
        "{category}: {}",
        truncate(&redact_secret(&reasons.join("；"), secret), 700)
    )
}

fn send_model_request(
    client: &Client,
    url: &Url,
    headers: &HeaderMap,
    body: &Value,
    secret: &str,
    on_delta: &mut Option<&mut dyn FnMut(&str) -> bool>,
) -> Result<Response, String> {
    let deadline = Instant::now() + MODEL_RETRY_BUDGET;
    for attempt in 1..=MODEL_ATTEMPTS {
        model_request_active(on_delta)?;
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(
                "模型请求超时（已达到 240 秒重试总时限）；当前证据已保留，可点继续重试".into(),
            );
        }
        let result = client
            .post(url.clone())
            .headers(headers.clone())
            .json(body)
            .timeout(remaining.min(MODEL_REQUEST_TIMEOUT))
            .send();
        let retry_delay = match result {
            Ok(response) if retryable_status(response.status()) && attempt < MODEL_ATTEMPTS => {
                let seconds = response
                    .headers()
                    .get(reqwest::header::RETRY_AFTER)
                    .and_then(|header| header.to_str().ok())
                    .and_then(|value| value.parse::<u64>().ok())
                    .unwrap_or(attempt as u64)
                    .clamp(1, 5);
                Duration::from_secs(seconds)
            }
            Ok(response) => return Ok(response),
            Err(error) => {
                let retryable = error.is_connect() || error.is_timeout() || error.is_request();
                let detail = transport_error_detail(error, secret);
                if !retryable || attempt == MODEL_ATTEMPTS {
                    return Err(format!("{detail}（已尝试 {attempt}/{MODEL_ATTEMPTS} 次）；当前证据已保留，可点继续重试"));
                }
                Duration::from_secs(attempt as u64)
            }
        };
        let retry_at = (Instant::now() + retry_delay).min(deadline);
        while Instant::now() < retry_at {
            model_request_active(on_delta)?;
            thread::sleep(Duration::from_millis(100));
        }
    }
    unreachable!("bounded retry loop returns a response or error")
}

fn read_sse_response(
    response: Response,
    profile: &RuntimeAiProfile,
    on_delta: &mut Option<&mut dyn FnMut(&str) -> bool>,
) -> Result<String, String> {
    let status = response.status();
    if !status.is_success() {
        let body = read_limited(response)?;
        let text = redact_secret(&String::from_utf8_lossy(&body), &profile.api_key);
        return Err(format!(
            "HTTP {}: {}",
            status.as_u16(),
            truncate(&text, 500)
        ));
    }
    if response
        .content_length()
        .is_some_and(|length| length > SSE_WIRE_LIMIT)
    {
        return Err(format!("模型 SSE 数据流超过 {} 字节限制", SSE_WIRE_LIMIT));
    }

    read_sse_stream(response, profile, on_delta)
}

fn read_sse_stream<R: Read>(
    reader: R,
    profile: &RuntimeAiProfile,
    on_delta: &mut Option<&mut dyn FnMut(&str) -> bool>,
) -> Result<String, String> {
    let mut reader = BufReader::new(reader.take(SSE_WIRE_LIMIT + 1));
    let mut collected = String::new();
    let mut data_lines = Vec::new();
    let mut event_name = String::new();
    let mut raw_line = Vec::new();
    let mut bytes_read = 0_u64;
    let mut first_line = true;
    let mut event_bytes = 0usize;

    loop {
        raw_line.clear();
        model_request_active(on_delta)?;
        let count = (&mut reader)
            .take((SSE_EVENT_LIMIT + 1) as u64)
            .read_until(b'\n', &mut raw_line)
            .map_err(|error| format!("读取模型 SSE 响应失败: {error}"))?;
        if count == 0 {
            break;
        }
        bytes_read = bytes_read.saturating_add(count as u64);
        if bytes_read > SSE_WIRE_LIMIT {
            return Err(format!("模型 SSE 数据流超过 {} 字节限制", SSE_WIRE_LIMIT));
        }
        if raw_line.len() > SSE_EVENT_LIMIT {
            return Err("模型 SSE 单个事件超过 1 MiB 限制".into());
        }
        let mut line =
            std::str::from_utf8(&raw_line).map_err(|_| "模型 SSE 响应不是 UTF-8".to_string())?;
        line = line.strip_suffix('\n').unwrap_or(line);
        line = line.strip_suffix('\r').unwrap_or(line);
        if first_line {
            line = line.strip_prefix('\u{feff}').unwrap_or(line);
            first_line = false;
        }

        if line.is_empty() {
            let data = data_lines.join("\n");
            if !consume_sse_event(&event_name, &data, profile, &mut collected, on_delta)? {
                return Err("模型流已取消".to_string());
            }
            if sse_finished(&event_name, &data) {
                data_lines.clear();
                event_name.clear();
                break;
            }
            data_lines.clear();
            event_name.clear();
            event_bytes = 0;
            continue;
        }
        if line.starts_with(':') {
            continue;
        }
        let (field, value) = line.split_once(':').unwrap_or((line, ""));
        let value = value.strip_prefix(' ').unwrap_or(value);
        match field {
            "event" => event_name = value.to_string(),
            "data" => {
                event_bytes = event_bytes.saturating_add(value.len());
                if event_bytes > SSE_EVENT_LIMIT {
                    return Err("模型 SSE 单个事件超过 1 MiB 限制".into());
                }
                data_lines.push(value.to_string());
            }
            _ => {}
        }
    }
    if (!data_lines.is_empty() || !event_name.is_empty())
        && !consume_sse_event(
            &event_name,
            &data_lines.join("\n"),
            profile,
            &mut collected,
            on_delta,
        )?
    {
        return Err("模型流已取消".to_string());
    }
    if collected.is_empty() {
        return Err("模型 SSE 未返回文本内容".to_string());
    }
    Ok(collected)
}

fn sse_finished(event: &str, data: &str) -> bool {
    data.trim() == "[DONE]"
        || event == "message_stop"
        || serde_json::from_str::<Value>(data)
            .ok()
            .is_some_and(|value| value["type"] == "message_stop")
}

fn consume_sse_event(
    event: &str,
    data: &str,
    profile: &RuntimeAiProfile,
    collected: &mut String,
    on_delta: &mut Option<&mut dyn FnMut(&str) -> bool>,
) -> Result<bool, String> {
    let data = data.trim();
    if data.is_empty() || data == "[DONE]" {
        return Ok(true);
    }
    let value: Value = serde_json::from_str(data)
        .map_err(|error| format!("模型 SSE 数据不是有效 JSON: {error}"))?;
    if let Some(error) = value.get("error") {
        let detail = error
            .get("message")
            .and_then(Value::as_str)
            .or_else(|| error.as_str())
            .unwrap_or("模型 SSE 返回错误");
        return Err(redact_secret(detail, &profile.api_key));
    }
    let delta = if profile.provider == "anthropic" {
        if event == "content_block_delta"
            || value.get("type").and_then(Value::as_str) == Some("content_block_delta")
        {
            value
                .get("delta")
                .and_then(|delta| delta.get("text"))
                .and_then(Value::as_str)
                .unwrap_or_default()
        } else {
            ""
        }
    } else {
        value
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .and_then(|choice| choice.get("delta"))
            .and_then(|delta| delta.get("content"))
            .and_then(Value::as_str)
            .unwrap_or_default()
    };
    if !delta.is_empty() {
        if collected.len().saturating_add(delta.len()) > COMPLETION_TEXT_LIMIT {
            return Err("模型输出文本超过 2 MiB 限制，请分轮返回工具或结论".into());
        }
        collected.push_str(delta);
        if let Some(callback) = on_delta.as_deref_mut() {
            let safe_delta = redact_secret(delta, &profile.api_key);
            if !callback(&safe_delta) {
                return Ok(false);
            }
        }
    }
    Ok(true)
}

fn openai_content(data: &Value) -> String {
    let content = data
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|choices| choices.first())
        .and_then(|choice| choice.get("message"))
        .and_then(|message| message.get("content"));
    match content {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Array(parts)) => parts
            .iter()
            .filter_map(|part| {
                part.get("text")
                    .and_then(Value::as_str)
                    .or_else(|| part.as_str())
            })
            .collect(),
        _ => String::new(),
    }
}

fn parse_json_object(raw: &str) -> Option<Value> {
    let mut text = raw.trim();
    if text.starts_with("```") {
        text = text
            .strip_prefix("```json")
            .or_else(|| text.strip_prefix("```"))?;
        text = text.strip_suffix("```").unwrap_or(text).trim();
    }
    if let Ok(value @ Value::Object(_)) = serde_json::from_str::<Value>(text) {
        return Some(value);
    }
    let start = text.find('{')?;
    let end = text.rfind('}')?;
    serde_json::from_str::<Value>(&text[start..=end])
        .ok()
        .filter(Value::is_object)
}

fn key_status(config: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let profile = retest_config::runtime_profile(config, payload)?;
    let limits = free_model_limits();
    if profile.provider != "openrouter" {
        return Ok(json!({
            "success": false,
            "message": "当前 Key 状态查询仅支持 OpenRouter。请切换到 OpenRouter 免费路由配置后再查询。",
            "provider": profile.provider,
            "model": profile.model,
            "free_model_limits": limits,
        }));
    }
    if profile.api_key.trim().is_empty() {
        return Ok(json!({
            "success": false,
            "message": "请先填写或保存 OpenRouter API Key，再查询当前限制和剩余额度。",
            "provider": profile.provider,
            "model": profile.model,
            "free_model_limits": limits,
        }));
    }

    let base_url = if profile.base_url.trim().is_empty() {
        OPENROUTER_DEFAULT_BASE_URL
    } else {
        profile.base_url.trim()
    };
    let endpoint = append_endpoint(base_url, "key")?;
    let started = Instant::now();
    let response = http_client()?
        .get(endpoint.clone())
        .header(
            AUTHORIZATION,
            secret_header(&format!("Bearer {}", profile.api_key), "Authorization")?,
        )
        .send();
    let elapsed = || started.elapsed().as_millis();
    let response = match response {
        Ok(response) => response,
        Err(error) => {
            let error = redact_secret(&error.to_string(), &profile.api_key);
            return Ok(json!({
                "success": false,
                "message": format!("OpenRouter Key 状态查询异常: {error}"),
                "provider": profile.provider,
                "model": profile.model,
                "endpoint": endpoint,
                "elapsed_ms": elapsed(),
                "error": error,
                "free_model_limits": limits,
            }));
        }
    };
    let status = response.status();
    let body = read_limited(response)?;
    if status == StatusCode::TOO_MANY_REQUESTS {
        return Ok(json!({
            "success": false,
            "message": "OpenRouter Key 状态查询被限流（HTTP 429），请稍后再试。",
            "provider": profile.provider,
            "model": profile.model,
            "endpoint": endpoint,
            "status_code": status.as_u16(),
            "elapsed_ms": elapsed(),
            "free_model_limits": limits,
        }));
    }
    if !status.is_success() {
        let body = redact_secret(&String::from_utf8_lossy(&body), &profile.api_key);
        let error = format!("HTTP {}", status.as_u16());
        return Ok(json!({
            "success": false,
            "message": format!("OpenRouter Key 状态查询失败（HTTP {}）: {}", status.as_u16(), truncate(&body, 500)),
            "provider": profile.provider,
            "model": profile.model,
            "endpoint": endpoint,
            "status_code": status.as_u16(),
            "elapsed_ms": elapsed(),
            "error": error,
            "free_model_limits": limits,
        }));
    }
    let data: Value = match serde_json::from_slice(&body) {
        Ok(data) => data,
        Err(error) => {
            let error = redact_secret(&error.to_string(), &profile.api_key);
            return Ok(json!({
                "success": false,
                "message": format!("OpenRouter Key 状态返回内容不是 JSON: {error}"),
                "provider": profile.provider,
                "model": profile.model,
                "endpoint": endpoint,
                "status_code": status.as_u16(),
                "elapsed_ms": elapsed(),
                "error": error,
                "free_model_limits": limits,
            }));
        }
    };
    let safe_data = sanitize_remote_value(&data, &profile.api_key, 0);
    Ok(json!({
        "success": true,
        "message": "OpenRouter Key 状态已读取。免费路由在本应用内会串行并按 20 次/分钟保护；每日额度以 OpenRouter 当前账号状态为准。",
        "provider": profile.provider,
        "model": profile.model,
        "endpoint": endpoint,
        "status_code": status.as_u16(),
        "elapsed_ms": elapsed(),
        "summary": key_status_summary(&safe_data),
        "data": safe_data,
        "free_model_limits": limits,
    }))
}

fn free_model_limits() -> Value {
    json!({
        "requests_per_minute": 20,
        "daily_without_credits": 50,
        "daily_with_credits": 1000,
        "credits_threshold_usd": 10,
    })
}

fn key_status_summary(data: &Value) -> Value {
    let source = data
        .get("data")
        .filter(|value| value.is_object())
        .unwrap_or(data);
    let mut summary = Map::new();
    for key in [
        "label",
        "usage",
        "limit",
        "limit_remaining",
        "limit_reset",
        "is_free_tier",
        "rate_limit",
        "rate_limit_remaining",
        "requests",
        "requests_remaining",
        "credits",
        "credit_balance",
    ] {
        if let Some(value) = source.get(key) {
            summary.insert(key.to_string(), value.clone());
        }
    }
    Value::Object(summary)
}

fn sanitize_remote_value(value: &Value, secret: &str, depth: usize) -> Value {
    if depth > 8 {
        return Value::String(truncate(
            &redact_secret(&python_json_dump(value), secret),
            500,
        ));
    }
    match value {
        Value::Object(source) => Value::Object(
            source
                .iter()
                .filter(|(key, _)| !is_secret_key(key))
                .map(|(key, value)| {
                    (
                        redact_secret(key, secret),
                        sanitize_remote_value(value, secret, depth + 1),
                    )
                })
                .collect(),
        ),
        Value::Array(values) => Value::Array(
            values
                .iter()
                .take(50)
                .map(|value| sanitize_remote_value(value, secret, depth + 1))
                .collect(),
        ),
        Value::String(text) => Value::String(truncate(&redact_secret(text, secret), 2_000)),
        _ => value.clone(),
    }
}

fn is_secret_key(key: &str) -> bool {
    matches!(
        key.to_ascii_lowercase().as_str(),
        "api_key" | "apikey" | "key" | "token" | "authorization" | "password" | "secret"
    )
}

fn append_endpoint(base_url: &str, endpoint: &str) -> Result<Url, String> {
    let base = base_url.trim().trim_end_matches('/');
    let url = format!("{base}/{endpoint}");
    let parsed = Url::parse(&url).map_err(|error| format!("无效的模型 Base URL: {error}"))?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err("模型 Base URL 必须是 http 或 https URL".to_string());
    }
    Ok(parsed)
}

fn secret_header(value: &str, label: &str) -> Result<HeaderValue, String> {
    HeaderValue::from_str(value).map_err(|_| format!("{label} 包含无效字符"))
}

fn http_client() -> Result<Client, String> {
    Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(45))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|error| format!("创建模型 HTTP 客户端失败: {error}"))
}

fn read_json_response(response: Response, secret: &str) -> Result<Value, String> {
    let status = response.status();
    let body = read_limited(response)?;
    if !status.is_success() {
        let text = redact_secret(&String::from_utf8_lossy(&body), secret);
        return Err(format!(
            "HTTP {}: {}",
            status.as_u16(),
            truncate(&text, 500)
        ));
    }
    serde_json::from_slice(&body).map_err(|error| format!("模型响应不是有效 JSON: {error}"))
}

fn read_limited(response: Response) -> Result<Vec<u8>, String> {
    if response
        .content_length()
        .is_some_and(|length| length > RESPONSE_LIMIT)
    {
        return Err(format!("HTTP 响应超过 {} 字节限制", RESPONSE_LIMIT));
    }
    let mut body = Vec::new();
    response
        .take(RESPONSE_LIMIT + 1)
        .read_to_end(&mut body)
        .map_err(|error| format!("读取 HTTP 响应失败: {error}"))?;
    if body.len() as u64 > RESPONSE_LIMIT {
        return Err(format!("HTTP 响应超过 {} 字节限制", RESPONSE_LIMIT));
    }
    Ok(body)
}

fn redact_secret(text: &str, secret: &str) -> String {
    if secret.is_empty() {
        text.to_string()
    } else {
        text.replace(secret, "***")
    }
}

fn truncate(text: &str, limit: usize) -> String {
    text.chars().take(limit).collect()
}

fn python_json_dump(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string()),
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_json_dump)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(key, value)| format!(
                    "{}: {}",
                    serde_json::to_string(key).unwrap_or_else(|_| "\"\"".to_string()),
                    python_json_dump(value)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

fn to_value<T: Serialize>(value: T) -> Result<Value, String> {
    serde_json::to_value(value).map_err(|error| format!("serialize model response: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::thread;

    static NEXT_ID: AtomicU64 = AtomicU64::new(1);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "koi-model-client-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).expect("create temp directory");
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn mock_server(response: &'static str) -> (String, thread::JoinHandle<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock server");
        let address = listener.local_addr().expect("mock address");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .expect("set timeout");
            let mut request = Vec::new();
            let mut buffer = [0u8; 4096];
            loop {
                let count = stream.read(&mut buffer).expect("read request");
                if count == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..count]);
                let header_end = request.windows(4).position(|item| item == b"\r\n\r\n");
                if let Some(header_end) = header_end {
                    let headers = String::from_utf8_lossy(&request[..header_end + 4]);
                    let content_length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .and_then(|value| value.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if request.len() >= header_end + 4 + content_length {
                        break;
                    }
                }
            }
            stream
                .write_all(response.as_bytes())
                .expect("write response");
            String::from_utf8_lossy(&request).to_string()
        });
        (format!("http://{address}/v1"), handle)
    }

    fn configure(store: &ConfigStore, provider: &str, base_url: &str, key: &str) {
        retest_config::dispatch(
            "doc.retest.ai_config.set",
            &json!({
                "profile_id": "default",
                "provider": provider,
                "base_url": base_url,
                "api_key": key,
                "model": "mock-model",
            }),
            store,
            Path::new("unused-tools"),
        )
        .expect("save profile");
    }

    fn retry_server(statuses: Vec<u16>) -> (String, thread::JoinHandle<usize>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            let mut received = 0;
            for status in statuses {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                loop {
                    let mut buffer = [0u8; 4096];
                    let count = stream.read(&mut buffer).unwrap();
                    if count == 0 {
                        break;
                    }
                    request.extend_from_slice(&buffer[..count]);
                    if let Some(end) = request.windows(4).position(|b| b == b"\r\n\r\n") {
                        let headers = String::from_utf8_lossy(&request[..end]).to_ascii_lowercase();
                        let length = headers
                            .lines()
                            .find_map(|line| {
                                line.strip_prefix("content-length:")
                                    .and_then(|v| v.trim().parse::<usize>().ok())
                            })
                            .unwrap_or(0);
                        if request.len() >= end + 4 + length {
                            break;
                        }
                    }
                }
                received += 1;
                if status == 0 {
                    continue;
                } // reset before any response header
                let body = if status == 200 {
                    r#"{"choices":[{"message":{"content":"{\"ok\":true}"}}]}"#
                } else {
                    r#"{"error":{"message":"temporary service failure"}}"#
                };
                write!(stream, "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
            }
            received
        });
        (format!("http://{address}/v1"), handle)
    }

    #[test]
    fn transient_model_failures_retry_the_same_request_and_recover() {
        let (url, server) = retry_server(vec![0, 503, 200]);
        let mut profile = streaming_profile("openai");
        profile.base_url = url;
        let result = complete_json_with_profile(&profile, "system", "same evidence").unwrap();
        assert_eq!(result.json["ok"], true);
        assert_eq!(server.join().unwrap(), 3);
    }

    #[test]
    fn model_auth_errors_are_not_retried() {
        let (url, server) = retry_server(vec![401]);
        let mut profile = streaming_profile("openai");
        profile.base_url = url;
        let result = complete_json_with_profile(&profile, "system", "evidence").unwrap_err();
        assert!(result.starts_with("HTTP 401:"));
        assert_eq!(server.join().unwrap(), 1);
    }

    #[test]
    fn cancellation_during_retry_backoff_sends_no_late_request() {
        let (url, server) = retry_server(vec![503]);
        let mut profile = streaming_profile("openai");
        profile.base_url = url;
        let mut polls = 0;
        let mut callback = |_: &str| {
            polls += 1;
            polls == 1
        };
        let result =
            complete_json_with_profile_stream(&profile, "system", "evidence", Some(&mut callback));
        assert_eq!(result.unwrap_err(), "模型流已取消");
        assert_eq!(server.join().unwrap(), 1);
    }

    #[test]
    fn done_event_finishes_without_waiting_for_server_to_close_connection() {
        struct OpenConnection(std::io::Cursor<Vec<u8>>);
        impl Read for OpenConnection {
            fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
                let read = self.0.read(bytes)?;
                if read == 0 {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::TimedOut,
                        "connection remains open",
                    ));
                }
                Ok(read)
            }
        }
        for terminal in [
            "data: [DONE]\n\n",
            "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n",
        ] {
            let body = format!("data: {{\"choices\":[{{\"delta\":{{\"content\":\"{{\\\"ok\\\":true}}\"}}}}]}}\n\n{terminal}");
            let result = read_sse_stream(
                OpenConnection(std::io::Cursor::new(body.into_bytes())),
                &streaming_profile("openai"),
                &mut None,
            )
            .unwrap();
            assert_eq!(result, r#"{"ok":true}"#);
        }
    }

    fn streaming_profile(provider: &str) -> RuntimeAiProfile {
        RuntimeAiProfile {
            id: "test".to_string(),
            name: "SSE test".to_string(),
            provider: provider.to_string(),
            base_url: "http://127.0.0.1/v1".to_string(),
            api_key: "sse-test-secret".to_string(),
            model: "mock-model".to_string(),
            temperature: 0.0,
            max_tokens: 512,
            context_window: 4_096,
        }
    }

    #[test]
    fn sse_envelope_over_one_megabyte_keeps_small_answer_and_checks_cancellation() {
        let reasoning = format!(
            "data: {}\n\n",
            json!({"choices":[{"delta":{"reasoning_content":"x".repeat(1200)}}]})
        );
        let mut stream = reasoning.repeat(1200);
        stream.push_str("data: {\"choices\":[{\"delta\":{\"content\":\"{\\\"ok\\\":true}\"}}]}\n\ndata: [DONE]\n\n");
        assert!(stream.len() > 1024 * 1024);
        assert_eq!(
            read_sse_stream(stream.as_bytes(), &streaming_profile("openai"), &mut None).unwrap(),
            r#"{"ok":true}"#
        );
        let mut heartbeats = 0;
        let mut cancel = |_: &str| {
            heartbeats += 1;
            heartbeats < 10
        };
        assert!(read_sse_stream(
            stream.as_bytes(),
            &streaming_profile("openai"),
            &mut Some(&mut cancel)
        )
        .unwrap_err()
        .contains("取消"));
    }

    #[test]
    fn sse_limits_individual_frames_and_collected_text() {
        let oversized = format!("data: {}", "x".repeat(SSE_EVENT_LIMIT));
        assert!(read_sse_stream(
            oversized.as_bytes(),
            &streaming_profile("openai"),
            &mut None
        )
        .unwrap_err()
        .contains("单个事件"));
        let mut text = "x".repeat(COMPLETION_TEXT_LIMIT);
        assert!(consume_sse_event(
            "",
            r#"{"choices":[{"delta":{"content":"x"}}]}"#,
            &streaming_profile("openai"),
            &mut text,
            &mut None
        )
        .unwrap_err()
        .contains("输出文本"));
    }

    #[test]
    fn parses_openai_sse_text_deltas_in_order() {
        let body = concat!(
            "\u{feff}: keep-alive\r\n",
            "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\r\n\r\n",
            "data: {\"choices\":[{\"delta\":{\"content\":\"{\\\"ok\\\":\"}}]}\r\n\r\n",
            "data: {\"choices\":[{\"delta\":{\"content\":\"true}\"}}]}\r\n\r\n",
            "data: [DONE]\r\n\r\n"
        );
        let profile = streaming_profile("openai");
        let mut deltas = Vec::new();
        let text = {
            let mut callback = |delta: &str| {
                if delta.is_empty() {
                    return true;
                }
                deltas.push(delta.to_string());
                true
            };
            let mut callback: Option<&mut dyn FnMut(&str) -> bool> = Some(&mut callback);
            read_sse_stream(body.as_bytes(), &profile, &mut callback).expect("parse OpenAI SSE")
        };

        assert_eq!(text, r#"{"ok":true}"#);
        assert_eq!(deltas, vec![r#"{"ok":"#, "true}"]);
        assert_eq!(parse_json_object(&text), Some(json!({"ok": true})));
    }

    #[test]
    fn parses_anthropic_named_and_typed_sse_deltas() {
        let body = concat!(
            "event: message_start\n",
            "data: {\"type\":\"message_start\",\"message\":{}}\n\n",
            "event: content_block_delta\n",
            "data: {\"type\":\"content_block_delta\",\n",
            "data: \"delta\":{\"type\":\"text_delta\",\"text\":\"{\\\"ok\\\":\"}}\n\n",
            "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"true}\"}}\n\n",
            "event: message_stop\n",
            "data: {\"type\":\"message_stop\"}\n\n"
        );
        let profile = streaming_profile("anthropic");
        let mut deltas = Vec::new();
        let text = {
            let mut callback = |delta: &str| {
                if delta.is_empty() {
                    return true;
                }
                deltas.push(delta.to_string());
                true
            };
            let mut callback: Option<&mut dyn FnMut(&str) -> bool> = Some(&mut callback);
            read_sse_stream(body.as_bytes(), &profile, &mut callback).expect("parse Anthropic SSE")
        };

        assert_eq!(text, r#"{"ok":true}"#);
        assert_eq!(deltas, vec![r#"{"ok":"#, "true}"]);
        assert_eq!(parse_json_object(&text), Some(json!({"ok": true})));
    }

    #[test]
    fn streaming_callback_can_cancel_before_later_events_are_consumed() {
        let body = concat!(
            "data: {\"choices\":[{\"delta\":{\"content\":\"first\"}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{\"content\":\"late\"}}]}\n\n",
            "data: [DONE]\n\n"
        );
        let profile = streaming_profile("openai");
        let mut deltas = Vec::new();
        let result = {
            let mut callback = |delta: &str| {
                if delta.is_empty() {
                    return true;
                }
                deltas.push(delta.to_string());
                false
            };
            let mut callback: Option<&mut dyn FnMut(&str) -> bool> = Some(&mut callback);
            read_sse_stream(body.as_bytes(), &profile, &mut callback)
        };

        assert_eq!(result.unwrap_err(), "模型流已取消");
        assert_eq!(deltas, vec!["first"]);
    }

    #[test]
    fn streaming_deltas_redact_profile_key_before_callbacks() {
        let body = concat!(
            "data: {\"choices\":[{\"delta\":{\"content\":\"sse-test-secret\"}}]}\n\n",
            "data: [DONE]\n\n"
        );
        let profile = streaming_profile("openai");
        let mut deltas = Vec::new();
        let text = {
            let mut callback = |delta: &str| {
                if delta.is_empty() {
                    return true;
                }
                deltas.push(delta.to_string());
                true
            };
            let mut callback: Option<&mut dyn FnMut(&str) -> bool> = Some(&mut callback);
            read_sse_stream(body.as_bytes(), &profile, &mut callback).expect("parse secret SSE")
        };
        assert_eq!(text, "sse-test-secret");
        assert_eq!(deltas, vec!["***"]);
        assert!(!deltas.join("").contains("sse-test-secret"));
    }

    #[test]
    fn openai_configuration_test_uses_typed_request_and_never_returns_key() {
        let body = r#"{"choices":[{"message":{"content":"{\"ok\":true,\"message\":\"通信正常\",\"echo\":\"model-secret-123\"}"}}]}"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        let response: &'static str = Box::leak(response.into_boxed_str());
        let (base_url, server) = mock_server(response);
        let temp = TempDir::new();
        let store = ConfigStore::new(temp.0.join("config.json"));
        configure(&store, "openai", &base_url, "model-secret-123");

        let result = dispatch("doc.retest.ai_config.test", &json!({}), &store)
            .expect("test model configuration");
        let request = server.join().expect("join mock server");
        assert_eq!(result["success"], true);
        assert_eq!(result["message"], "模型测试成功：通信正常");
        assert!(request.contains("POST /v1/chat/completions HTTP/1.1"));
        assert!(request.contains("authorization: Bearer model-secret-123"));
        assert!(request.contains("\"response_format\""));
        assert!(!result.to_string().contains("model-secret-123"));
    }

    #[test]
    fn openrouter_key_status_sanitizes_secret_fields_and_echoes() {
        let body = r#"{"data":{"label":"free","limit":50,"api_key":"model-secret-456","note":"echo model-secret-456"}}"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        let response: &'static str = Box::leak(response.into_boxed_str());
        let (base_url, server) = mock_server(response);
        let temp = TempDir::new();
        let store = ConfigStore::new(temp.0.join("config.json"));
        configure(&store, "openrouter", &base_url, "model-secret-456");

        let result = dispatch("doc.retest.ai_config.key_status", &json!({}), &store)
            .expect("read key status");
        let request = server.join().expect("join mock server");
        assert_eq!(result["success"], true);
        assert_eq!(result["summary"]["limit"], 50);
        assert!(request.contains("GET /v1/key HTTP/1.1"));
        assert!(request.contains("authorization: Bearer model-secret-456"));
        assert!(!result.to_string().contains("model-secret-456"));
        assert!(result["data"]["data"].get("api_key").is_none());
        assert_eq!(result["data"]["data"]["note"], "echo ***");
    }

    #[test]
    fn missing_configuration_fails_without_network() {
        let temp = TempDir::new();
        let store = ConfigStore::new(temp.0.join("config.json"));
        let result = dispatch("doc.retest.ai_config.test", &json!({}), &store)
            .expect("missing configuration response");
        assert_eq!(result["success"], false);
        assert!(result["message"].as_str().unwrap().contains("API Key"));
    }
}
