use super::config::ConfigStore;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Number, Value};
use std::collections::BTreeSet;
#[cfg(not(windows))]
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Default)]
struct CompatTextField {
    present: bool,
    value: String,
}

impl<'de> Deserialize<'de> for CompatTextField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self {
            present: true,
            value: string_or_empty(Some(&value)),
        })
    }
}

#[derive(Debug, Clone, Default)]
struct CompatBoolField {
    value: bool,
}

impl<'de> Deserialize<'de> for CompatBoolField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self {
            value: json_truthy(Some(&value)),
        })
    }
}

#[derive(Debug, Clone)]
struct CompatValueField {
    present: bool,
    value: Value,
}

impl Default for CompatValueField {
    fn default() -> Self {
        Self {
            present: false,
            value: Value::Null,
        }
    }
}

impl<'de> Deserialize<'de> for CompatValueField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Ok(Self {
            present: true,
            value: Value::deserialize(deserializer)?,
        })
    }
}

#[derive(Debug, Default, Deserialize)]
struct WeeklyReportSetRequest {
    #[serde(default, alias = "vulnerabilityNoticeDir")]
    vulnerability_notice_dir: CompatTextField,
    #[serde(default, alias = "eventNoticeDir")]
    event_notice_dir: CompatTextField,
    #[serde(default, alias = "excludeMondayNextNotice")]
    exclude_monday_next_notice: CompatBoolField,
}

#[derive(Debug, Default, Deserialize)]
struct DarkModeSetRequest {
    #[serde(default, alias = "darkMode")]
    dark_mode: CompatBoolField,
}

#[derive(Debug, Default, Deserialize)]
struct InformationConfigSetRequest {
    #[serde(default)]
    fofa_email: CompatTextField,
    #[serde(default)]
    fofa_api_key: CompatTextField,
    #[serde(default)]
    hunter_api_key: CompatTextField,
    #[serde(default)]
    quake_api_key: CompatTextField,
    #[serde(default)]
    tyc_cookie: CompatTextField,
    #[serde(default)]
    aiqicha_cookie: CompatTextField,
    #[serde(default)]
    xunkebao_cookie: CompatTextField,
    #[serde(default)]
    threatbook_api_key: CompatTextField,
}

#[derive(Debug, Default, Deserialize)]
struct ThreatBookConfigSetRequest {
    #[serde(default, alias = "apiKey")]
    api_key: CompatTextField,
}

#[derive(Debug, Default, Deserialize)]
struct NoticeCountersSaveRequest {
    #[serde(default)]
    notice_number: CompatValueField,
    #[serde(default)]
    rectification_number: CompatValueField,
    #[serde(default)]
    unavailable_numbers: CompatValueField,
    #[serde(default)]
    unavailable_type: CompatTextField,
    #[serde(default)]
    unavailable_notification_numbers: CompatValueField,
    #[serde(default)]
    unavailable_rectification_numbers: CompatValueField,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct DarkModeResponse {
    dark_mode: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct WeeklyReportConfigResponse {
    vulnerability_notice_dir: String,
    event_notice_dir: String,
    exclude_monday_next_notice: bool,
    last_updated: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct FofaConfigResponse {
    email: String,
    api_key: String,
    api_key_configured: bool,
    api_key_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApiKeyConfigResponse {
    api_key: String,
    api_key_configured: bool,
    api_key_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct CookieConfigResponse {
    cookie: String,
    cookie_configured: bool,
    cookie_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct AiqichaConfigResponse {
    cookie: String,
    cookie_configured: bool,
    cookie_masked: String,
    xunkebao_cookie: String,
    xunkebao_cookie_configured: bool,
    xunkebao_cookie_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct InformationConfigResponse {
    fofa: FofaConfigResponse,
    hunter: ApiKeyConfigResponse,
    quake: ApiKeyConfigResponse,
    tyc: CookieConfigResponse,
    aiqicha: AiqichaConfigResponse,
    threatbook_api_key: String,
    threatbook_api_key_configured: bool,
    threatbook_api_key_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ThreatBookConfigResponse {
    api_key: String,
    api_key_configured: bool,
    api_key_masked: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
enum CounterScalar {
    Null,
    Bool(bool),
    Number(Number),
    Text(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ReportCountersResponse {
    notification_number: CounterScalar,
    rectification_number: CounterScalar,
    unavailable_notification_numbers: Vec<CounterScalar>,
    unavailable_rectification_numbers: Vec<CounterScalar>,
    year: CounterScalar,
    last_updated: String,
    #[serde(flatten)]
    extensions: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct NoticeCountersSaveResponse {
    success: bool,
    updated: bool,
    message: String,
    report_counters: ReportCountersResponse,
    logs: Vec<String>,
}

impl NoticeCountersSaveResponse {
    fn success(updated: bool, message: &str, report_counters: ReportCountersResponse) -> Self {
        Self {
            success: true,
            updated,
            message: message.to_string(),
            report_counters,
            logs: vec![message.to_string()],
        }
    }
}

fn parse_request<T: serde::de::DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn serialize_response<T: Serialize>(response: T) -> Result<Value, String> {
    serde_json::to_value(response).map_err(|error| format!("配置响应序列化失败: {error}"))
}

pub fn weekly_report_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| Ok((serialize_response(weekly_report_response(config))?, false)))
}

pub fn set_dark_mode(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: DarkModeSetRequest = parse_request(payload)?;
    let dark_mode = request.dark_mode.value;
    store.set_dark_mode(dark_mode)?;
    serialize_response(DarkModeResponse { dark_mode })
}

pub fn weekly_report_set(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: WeeklyReportSetRequest = parse_request(payload)?;
    let vulnerability_notice_dir = request.vulnerability_notice_dir.value.trim().to_string();
    let event_notice_dir = request.event_notice_dir.value.trim().to_string();
    let exclude_monday_next_notice = request.exclude_monday_next_notice.value;
    let timestamp = local_timestamp();

    store.transact(move |config| {
        let weekly = object_section_mut(config, "weekly_report")?;
        weekly.insert(
            "vulnerability_notice_dir".to_string(),
            Value::String(vulnerability_notice_dir),
        );
        weekly.insert(
            "event_notice_dir".to_string(),
            Value::String(event_notice_dir),
        );
        weekly.insert(
            "exclude_monday_next_notice".to_string(),
            Value::Bool(exclude_monday_next_notice),
        );
        weekly.insert("last_updated".to_string(), Value::String(timestamp));
        Ok((serialize_response(weekly_report_response(config))?, true))
    })
}

pub fn information_config_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| {
        Ok((
            serialize_response(information_config_response(config))?,
            false,
        ))
    })
}

pub fn information_config_set(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: InformationConfigSetRequest = parse_request(payload)?;
    let timestamp = local_timestamp();
    store.transact(move |config| {
        if request.fofa_email.present || request.fofa_api_key.present {
            let section = object_section_mut(config, "fofa")?;
            if request.fofa_email.present {
                section.insert(
                    "email".to_string(),
                    Value::String(request.fofa_email.value.clone()),
                );
            }
            if request.fofa_api_key.present {
                section.insert(
                    "api_key".to_string(),
                    Value::String(request.fofa_api_key.value.clone()),
                );
            }
            section.insert("last_updated".to_string(), Value::String(timestamp.clone()));
        }
        update_typed_string_section(
            config,
            &request.hunter_api_key,
            "hunter",
            "api_key",
            &timestamp,
        )?;
        update_typed_string_section(
            config,
            &request.quake_api_key,
            "quake",
            "api_key",
            &timestamp,
        )?;
        update_typed_string_section(config, &request.tyc_cookie, "tyc", "cookie", &timestamp)?;
        update_typed_string_section(
            config,
            &request.aiqicha_cookie,
            "aiqicha",
            "cookie",
            &timestamp,
        )?;
        update_typed_string_section(
            config,
            &request.xunkebao_cookie,
            "aiqicha",
            "xunkebao_cookie",
            &timestamp,
        )?;
        if request.threatbook_api_key.present {
            root_object_mut(config)?.insert(
                "threatbook_api_key".to_string(),
                Value::String(request.threatbook_api_key.value.clone()),
            );
        }
        Ok((
            serialize_response(information_config_response(config))?,
            true,
        ))
    })
}

pub fn threatbook_config_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| {
        Ok((
            serialize_response(threatbook_config_response(config))?,
            false,
        ))
    })
}

pub fn threatbook_config_set(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: ThreatBookConfigSetRequest = parse_request(payload)?;
    if !request.api_key.present {
        // A partial settings update must not clear a credential merely because
        // the caller omitted the field.  `null` remains an explicit clear via
        // CompatTextField's `present = true` semantics.
        return store.transact(|config| {
            Ok((
                serialize_response(threatbook_config_response(config))?,
                false,
            ))
        });
    }
    let api_key = request.api_key.value;
    store.transact(move |config| {
        root_object_mut(config)?.insert("threatbook_api_key".to_string(), Value::String(api_key));
        Ok((
            serialize_response(threatbook_config_response(config))?,
            true,
        ))
    })
}

pub fn notice_counters_save(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: NoticeCountersSaveRequest = parse_request(payload)?;
    let timestamp = local_timestamp();
    store.transact(move |config| {
        let counters = normalized_report_counters(config);
        let mut updates = Map::new();

        if request.notice_number.present {
            if let Some(number) = parse_positive_int(Some(&request.notice_number.value)) {
                updates.insert(
                    "notification_number".to_string(),
                    Value::Number(number.into()),
                );
            }
        }
        if request.rectification_number.present {
            if let Some(number) = parse_positive_int(Some(&request.rectification_number.value)) {
                updates.insert(
                    "rectification_number".to_string(),
                    Value::Number(number.into()),
                );
            }
        }
        if request.unavailable_numbers.present {
            let unavailable_type = &request.unavailable_type.value;
            let key = if unavailable_type.contains("责令") || unavailable_type.contains("整改")
            {
                "unavailable_rectification_numbers"
            } else {
                "unavailable_notification_numbers"
            };
            merge_unavailable_update(
                &mut updates,
                &counters,
                key,
                &request.unavailable_numbers.value,
            );
        }
        for (key, value) in [
            (
                "unavailable_notification_numbers",
                &request.unavailable_notification_numbers,
            ),
            (
                "unavailable_rectification_numbers",
                &request.unavailable_rectification_numbers,
            ),
        ] {
            if value.present {
                merge_unavailable_update(&mut updates, &counters, key, &value.value);
            }
        }

        if updates.is_empty() {
            let message = "没有可保存的编号配置修改";
            return Ok((
                serialize_response(NoticeCountersSaveResponse::success(
                    false,
                    message,
                    report_counters_response(&counters),
                ))?,
                false,
            ));
        }

        let year = counters
            .get("year")
            .filter(|value| json_truthy(Some(value)))
            .cloned()
            .unwrap_or_else(|| Value::Number(current_local_year().into()));
        updates.entry("year".to_string()).or_insert(year);
        updates.insert("last_updated".to_string(), Value::String(timestamp));

        let target = object_section_mut(config, "report_counters")?;
        for (key, value) in updates {
            target.insert(key, value);
        }
        let refreshed = normalized_report_counters(config);
        let message = "编号配置已保存到 report_counters";
        Ok((
            serialize_response(NoticeCountersSaveResponse::success(
                true,
                message,
                report_counters_response(&refreshed),
            ))?,
            true,
        ))
    })
}

fn weekly_report_response(config: &Value) -> WeeklyReportConfigResponse {
    let weekly = config.get("weekly_report").and_then(Value::as_object);
    WeeklyReportConfigResponse {
        vulnerability_notice_dir: string_or_empty(
            weekly.and_then(|value| value.get("vulnerability_notice_dir")),
        ),
        event_notice_dir: string_or_empty(weekly.and_then(|value| value.get("event_notice_dir"))),
        exclude_monday_next_notice: json_truthy(
            weekly.and_then(|value| value.get("exclude_monday_next_notice")),
        ),
        last_updated: string_or_empty(weekly.and_then(|value| value.get("last_updated"))),
    }
}

fn information_config_response(config: &Value) -> InformationConfigResponse {
    let fofa_key = nested_string(config, "fofa", "api_key");
    let hunter_key = nested_string(config, "hunter", "api_key");
    let quake_key = nested_string(config, "quake", "api_key");
    let tyc_cookie = nested_string(config, "tyc", "cookie");
    let aiqicha_cookie = nested_string(config, "aiqicha", "cookie");
    let xunkebao_cookie = nested_string(config, "aiqicha", "xunkebao_cookie");
    let threatbook_key = string_or_empty(config.get("threatbook_api_key"));
    InformationConfigResponse {
        fofa: FofaConfigResponse {
            email: nested_string(config, "fofa", "email"),
            api_key: String::new(),
            api_key_configured: !fofa_key.is_empty(),
            api_key_masked: mask_secret(&fofa_key),
        },
        hunter: ApiKeyConfigResponse {
            api_key: String::new(),
            api_key_configured: !hunter_key.is_empty(),
            api_key_masked: mask_secret(&hunter_key),
        },
        quake: ApiKeyConfigResponse {
            api_key: String::new(),
            api_key_configured: !quake_key.is_empty(),
            api_key_masked: mask_secret(&quake_key),
        },
        tyc: CookieConfigResponse {
            cookie: String::new(),
            cookie_configured: !tyc_cookie.is_empty(),
            cookie_masked: mask_secret(&tyc_cookie),
        },
        aiqicha: AiqichaConfigResponse {
            cookie: String::new(),
            cookie_configured: !aiqicha_cookie.is_empty(),
            cookie_masked: mask_secret(&aiqicha_cookie),
            xunkebao_cookie: String::new(),
            xunkebao_cookie_configured: !xunkebao_cookie.is_empty(),
            xunkebao_cookie_masked: mask_secret(&xunkebao_cookie),
        },
        threatbook_api_key: String::new(),
        threatbook_api_key_configured: !threatbook_key.is_empty(),
        threatbook_api_key_masked: mask_secret(&threatbook_key),
    }
}

fn threatbook_config_response(config: &Value) -> ThreatBookConfigResponse {
    let api_key = string_or_empty(config.get("threatbook_api_key"));
    ThreatBookConfigResponse {
        api_key: String::new(),
        api_key_configured: !api_key.is_empty(),
        api_key_masked: mask_secret(&api_key),
    }
}

fn mask_secret(secret: &str) -> String {
    let suffix: String = secret
        .chars()
        .rev()
        .take(4)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    if suffix.is_empty() {
        String::new()
    } else {
        format!("****{suffix}")
    }
}

fn normalized_report_counters(config: &Value) -> Map<String, Value> {
    let mut counters = Map::new();
    counters.insert("notification_number".to_string(), Value::Number(1.into()));
    counters.insert("rectification_number".to_string(), Value::Number(1.into()));
    counters.insert(
        "unavailable_notification_numbers".to_string(),
        Value::Array(Vec::new()),
    );
    counters.insert(
        "unavailable_rectification_numbers".to_string(),
        Value::Array(Vec::new()),
    );
    counters.insert(
        "year".to_string(),
        Value::Number(current_local_year().into()),
    );
    counters.insert("last_updated".to_string(), Value::String(String::new()));
    if let Some(existing) = config.get("report_counters").and_then(Value::as_object) {
        for (key, value) in existing {
            counters.insert(key.clone(), value.clone());
        }
    }
    for key in [
        "unavailable_notification_numbers",
        "unavailable_rectification_numbers",
    ] {
        if !counters.get(key).is_some_and(Value::is_array) {
            counters.insert(key.to_string(), Value::Array(Vec::new()));
        }
    }
    counters
}

fn report_counters_response(counters: &Map<String, Value>) -> ReportCountersResponse {
    let mut extensions = counters.clone();
    let notification_number = take_counter_scalar(&mut extensions, "notification_number", 1);
    let rectification_number = take_counter_scalar(&mut extensions, "rectification_number", 1);
    let unavailable_notification_numbers =
        take_counter_list(&mut extensions, "unavailable_notification_numbers");
    let unavailable_rectification_numbers =
        take_counter_list(&mut extensions, "unavailable_rectification_numbers");
    let year = take_counter_scalar(&mut extensions, "year", i64::from(current_local_year()));
    let last_updated = string_or_empty(extensions.remove("last_updated").as_ref());
    ReportCountersResponse {
        notification_number,
        rectification_number,
        unavailable_notification_numbers,
        unavailable_rectification_numbers,
        year,
        last_updated,
        extensions,
    }
}

fn take_counter_scalar(
    counters: &mut Map<String, Value>,
    key: &str,
    default: i64,
) -> CounterScalar {
    counters
        .remove(key)
        .and_then(counter_scalar)
        .unwrap_or(CounterScalar::Number(default.into()))
}

fn take_counter_list(counters: &mut Map<String, Value>, key: &str) -> Vec<CounterScalar> {
    counters
        .remove(key)
        .and_then(|value| match value {
            Value::Array(values) => Some(values.into_iter().filter_map(counter_scalar).collect()),
            _ => None,
        })
        .unwrap_or_default()
}

fn counter_scalar(value: Value) -> Option<CounterScalar> {
    match value {
        Value::Null => Some(CounterScalar::Null),
        Value::Bool(value) => Some(CounterScalar::Bool(value)),
        Value::Number(value) => Some(CounterScalar::Number(value)),
        Value::String(value) => Some(CounterScalar::Text(value)),
        Value::Array(_) | Value::Object(_) => None,
    }
}

fn merge_unavailable_update(
    updates: &mut Map<String, Value>,
    counters: &Map<String, Value>,
    key: &str,
    incoming: &Value,
) {
    let incoming = parse_number_ranges(incoming);
    if incoming.is_empty() {
        return;
    }
    let existing_value = updates.get(key).or_else(|| counters.get(key));
    let mut numbers = existing_value.map(parse_number_ranges).unwrap_or_default();
    numbers.extend(incoming);
    updates.insert(
        key.to_string(),
        Value::Array(
            numbers
                .into_iter()
                .map(|number| Value::Number(number.into()))
                .collect(),
        ),
    );
}

fn parse_number_ranges(value: &Value) -> BTreeSet<i64> {
    let parts = match value {
        Value::Array(values) => values.iter().map(value_to_python_string).collect(),
        _ => split_number_text(&value_to_python_string(value)),
    };
    let mut numbers = BTreeSet::new();
    for part in parts {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((start, end)) = part.split_once('-') {
            let (Some(start), Some(end)) = (parse_int_text(start), parse_int_text(end)) else {
                continue;
            };
            let low = start.min(end).max(1);
            let high = start.max(end);
            if high >= low {
                numbers.extend(low..=high);
            }
        } else if let Some(number) = parse_int_text(part).filter(|number| *number > 0) {
            numbers.insert(number);
        }
    }
    numbers
}

fn split_number_text(value: &str) -> Vec<String> {
    value
        .split(|character: char| {
            character.is_whitespace() || matches!(character, ',' | '，' | ';' | '；')
        })
        .map(ToOwned::to_owned)
        .collect()
}

fn parse_positive_int(value: Option<&Value>) -> Option<i64> {
    value
        .map(value_to_python_string)
        .and_then(|value| parse_int_text(&value))
        .filter(|number| *number > 0)
}

fn parse_int_text(value: &str) -> Option<i64> {
    value.trim().parse::<i64>().ok()
}

fn update_typed_string_section(
    config: &mut Value,
    request: &CompatTextField,
    section: &str,
    field: &str,
    timestamp: &str,
) -> Result<(), String> {
    if !request.present {
        return Ok(());
    }
    let section = object_section_mut(config, section)?;
    section.insert(field.to_string(), Value::String(request.value.clone()));
    section.insert(
        "last_updated".to_string(),
        Value::String(timestamp.to_string()),
    );
    Ok(())
}

fn object_section_mut<'a>(
    config: &'a mut Value,
    section: &str,
) -> Result<&'a mut Map<String, Value>, String> {
    let root = root_object_mut(config)?;
    let value = root
        .entry(section.to_string())
        .or_insert_with(|| Value::Object(Map::new()));
    value
        .as_object_mut()
        .ok_or_else(|| format!("配置字段 {section} 必须是对象"))
}

fn root_object_mut(config: &mut Value) -> Result<&mut Map<String, Value>, String> {
    config
        .as_object_mut()
        .ok_or_else(|| "配置根节点必须是对象".to_string())
}

fn nested_string(config: &Value, section: &str, field: &str) -> String {
    string_or_empty(config.get(section).and_then(|value| value.get(field)))
}

fn string_or_empty(value: Option<&Value>) -> String {
    value.map(string_or_empty_value).unwrap_or_default()
}

fn string_or_empty_value(value: &Value) -> String {
    if !json_truthy(Some(value)) {
        String::new()
    } else {
        value_to_python_string(value)
    }
}

fn value_to_python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn json_truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) | Some(Value::Bool(false)) => false,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|number| number != 0.0),
        Some(Value::String(value)) => !value.is_empty(),
        Some(Value::Array(value)) => !value.is_empty(),
        Some(Value::Object(value)) => !value.is_empty(),
        Some(Value::Bool(true)) => true,
    }
}

fn current_local_year() -> i32 {
    local_date_parts().0
}

fn local_timestamp() -> String {
    let (year, month, day, hour, minute, second) = local_date_parts();
    format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}")
}

#[cfg(windows)]
fn local_date_parts() -> (i32, u32, u32, u32, u32, u32) {
    #[repr(C)]
    struct WindowsSystemTime {
        year: u16,
        month: u16,
        day_of_week: u16,
        day: u16,
        hour: u16,
        minute: u16,
        second: u16,
        milliseconds: u16,
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetLocalTime(system_time: *mut WindowsSystemTime);
    }

    let mut value = std::mem::MaybeUninit::<WindowsSystemTime>::uninit();
    // GetLocalTime always initializes the supplied SYSTEMTIME structure.
    let value = unsafe {
        GetLocalTime(value.as_mut_ptr());
        value.assume_init()
    };
    (
        i32::from(value.year),
        u32::from(value.month),
        u32::from(value.day),
        u32::from(value.hour),
        u32::from(value.minute),
        u32::from(value.second),
    )
}

#[cfg(not(windows))]
fn local_date_parts() -> (i32, u32, u32, u32, u32, u32) {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0);
    let days = (seconds / 86_400) as i64;
    let day_seconds = seconds % 86_400;
    let (year, month, day) = civil_from_days(days);
    (
        year,
        month,
        day,
        (day_seconds / 3_600) as u32,
        ((day_seconds % 3_600) / 60) as u32,
        (day_seconds % 60) as u32,
    )
}

#[cfg(not(windows))]
fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let shifted = days + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_parameter = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_parameter + 2) / 5 + 1;
    let month = month_parameter + if month_parameter < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    (year as i32, month as u32, day as u32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn number_ranges_match_python_rules() {
        assert_eq!(
            parse_number_ranges(&json!("1, 3-5；2")),
            BTreeSet::from([1, 2, 3, 4, 5])
        );
        assert_eq!(
            parse_number_ranges(&json!(["7", "9-8", "bad"])),
            BTreeSet::from([7, 8, 9])
        );
    }

    #[test]
    fn timestamp_has_python_compatible_shape() {
        let timestamp = local_timestamp();
        assert_eq!(timestamp.len(), 19);
        assert_eq!(&timestamp[4..5], "-");
        assert_eq!(&timestamp[10..11], " ");
        assert!((2024..=2200).contains(&current_local_year()));
    }

    #[test]
    fn typed_setting_requests_preserve_aliases_presence_and_truthiness() {
        let weekly: WeeklyReportSetRequest = parse_request(&json!({
            "vulnerabilityNoticeDir": 42,
            "eventNoticeDir": false,
            "excludeMondayNextNotice": "yes"
        }))
        .expect("typed weekly settings");
        assert_eq!(weekly.vulnerability_notice_dir.value, "42");
        assert_eq!(weekly.event_notice_dir.value, "");
        assert!(weekly.exclude_monday_next_notice.value);

        let information: InformationConfigSetRequest =
            parse_request(&json!({"fofa_email": null, "hunter_api_key": ""}))
                .expect("typed information settings");
        assert!(information.fofa_email.present);
        assert_eq!(information.fofa_email.value, "");
        assert!(information.hunter_api_key.present);
        assert!(!information.quake_api_key.present);

        let threatbook: ThreatBookConfigSetRequest =
            parse_request(&json!({"apiKey": true})).expect("typed ThreatBook settings");
        assert_eq!(threatbook.api_key.value, "True");
    }

    #[test]
    fn typed_setting_responses_keep_legacy_json_fields() {
        let config = json!({
            "weekly_report": {
                "vulnerability_notice_dir": "vulnerability",
                "event_notice_dir": "events",
                "exclude_monday_next_notice": "enabled",
                "last_updated": "2026-09-14 12:34:56"
            },
            "report_counters": {
                "notification_number": "12",
                "rectification_number": 22,
                "unavailable_notification_numbers": [11, "13"],
                "unavailable_rectification_numbers": [21],
                "year": "2026",
                "last_updated": "2026-09-14 12:34:56",
                "future_counter_option": {"keep": true}
            }
        });

        assert_eq!(
            serialize_response(weekly_report_response(&config)).unwrap(),
            json!({
                "vulnerability_notice_dir": "vulnerability",
                "event_notice_dir": "events",
                "exclude_monday_next_notice": true,
                "last_updated": "2026-09-14 12:34:56"
            })
        );

        let counters = normalized_report_counters(&config);
        let response = NoticeCountersSaveResponse::success(
            false,
            "没有可保存的编号配置修改",
            report_counters_response(&counters),
        );
        assert_eq!(
            serialize_response(response).unwrap(),
            json!({
                "success": true,
                "updated": false,
                "message": "没有可保存的编号配置修改",
                "report_counters": {
                    "notification_number": "12",
                    "rectification_number": 22,
                    "unavailable_notification_numbers": [11, "13"],
                    "unavailable_rectification_numbers": [21],
                    "year": "2026",
                    "last_updated": "2026-09-14 12:34:56",
                    "future_counter_option": {"keep": true}
                },
                "logs": ["没有可保存的编号配置修改"]
            })
        );

        assert_eq!(
            serialize_response(DarkModeResponse { dark_mode: true }).unwrap(),
            json!({"dark_mode": true})
        );
    }

    #[test]
    fn information_config_response_never_exposes_secret_values() {
        let config = json!({
            "fofa": {"email": "operator@example.test", "api_key": "fofa-secret-1234"},
            "hunter": {"api_key": "hunter-secret-5678"},
            "quake": {"api_key": "quake-secret-9012"},
            "tyc": {"cookie": "tyc-cookie-3456"},
            "aiqicha": {"cookie": "aiqicha-cookie-7890", "xunkebao_cookie": "xunkebao-cookie-2468"},
            "threatbook_api_key": "threatbook-secret-1357"
        });

        let response = information_config_response(&config);
        let serialized = serde_json::to_string(&response).expect("serialize information config");
        for secret in [
            "fofa-secret-1234",
            "hunter-secret-5678",
            "quake-secret-9012",
            "tyc-cookie-3456",
            "aiqicha-cookie-7890",
            "xunkebao-cookie-2468",
            "threatbook-secret-1357",
        ] {
            assert!(!serialized.contains(secret), "response leaked {secret}");
        }
        assert!(response.fofa.api_key.is_empty());
        assert!(response.fofa.api_key_configured);
        assert_eq!(response.fofa.api_key_masked, "****1234");
        assert!(response.tyc.cookie_configured);
        assert!(response.threatbook_api_key.is_empty());
        assert!(response.threatbook_api_key_configured);

        let threatbook = threatbook_config_response(&config);
        assert!(threatbook.api_key.is_empty());
        assert!(threatbook.api_key_configured);
        assert_eq!(threatbook.api_key_masked, "****1357");
    }

    #[test]
    fn fofa_email_update_does_not_clear_a_redacted_key() {
        let directory = std::env::temp_dir().join(format!(
            "koi-settings-test-{}-{}",
            std::process::id(),
            SETTING_TEST_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let path = directory.join("config.json");
        let store = ConfigStore::new(path);
        store
            .transact(|config| {
                let fofa = object_section_mut(config, "fofa")?;
                fofa.insert(
                    "email".to_string(),
                    Value::String("old@example.test".to_string()),
                );
                fofa.insert(
                    "api_key".to_string(),
                    Value::String("keep-this-key".to_string()),
                );
                Ok((Value::Null, true))
            })
            .expect("seed config");

        information_config_set(&store, &json!({"fofa_email": "new@example.test"}))
            .expect("update email only");
        let persisted = store.load().expect("load persisted config");
        assert_eq!(persisted["fofa"]["email"], "new@example.test");
        assert_eq!(persisted["fofa"]["api_key"], "keep-this-key");
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn threatbook_partial_update_does_not_clear_existing_key() {
        let directory = std::env::temp_dir().join(format!(
            "koi-threatbook-settings-test-{}-{}",
            std::process::id(),
            SETTING_TEST_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let path = directory.join("config.json");
        let store = ConfigStore::new(path);
        store
            .transact(|config| {
                root_object_mut(config)?.insert(
                    "threatbook_api_key".to_string(),
                    Value::String("keep-threatbook-key".to_string()),
                );
                Ok((Value::Null, true))
            })
            .expect("seed ThreatBook key");

        let response = threatbook_config_set(&store, &json!({})).expect("partial update");
        assert_eq!(response["api_key_configured"], true);
        let persisted = store.load().expect("load persisted config");
        assert_eq!(persisted["threatbook_api_key"], "keep-threatbook-key");
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn threatbook_null_key_is_still_an_explicit_clear() {
        let directory = std::env::temp_dir().join(format!(
            "koi-threatbook-clear-test-{}-{}",
            std::process::id(),
            SETTING_TEST_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let path = directory.join("config.json");
        let store = ConfigStore::new(path);
        store
            .transact(|config| {
                root_object_mut(config)?.insert(
                    "threatbook_api_key".to_string(),
                    Value::String("clear-me".to_string()),
                );
                Ok((Value::Null, true))
            })
            .expect("seed ThreatBook key");

        let response =
            threatbook_config_set(&store, &json!({"apiKey": null})).expect("explicit clear");
        assert_eq!(response["api_key_configured"], false);
        let persisted = store.load().expect("load persisted config");
        assert_eq!(persisted["threatbook_api_key"], "");
        let _ = std::fs::remove_dir_all(directory);
    }

    static SETTING_TEST_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
}
