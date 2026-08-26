use super::config::ConfigStore;
use serde::{Deserialize, Deserializer};
use serde_json::{json, Map, Value};
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

fn parse_request<T: serde::de::DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

pub fn weekly_report_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| Ok((weekly_report_response(config), false)))
}

pub fn set_dark_mode(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: DarkModeSetRequest = parse_request(payload)?;
    store.set_dark_mode(request.dark_mode.value)
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
        Ok((weekly_report_response(config), true))
    })
}

pub fn information_config_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| Ok((information_config_response(config), false)))
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
        Ok((information_config_response(config), true))
    })
}

pub fn threatbook_config_get(store: &ConfigStore) -> Result<Value, String> {
    store.transact(|config| Ok((threatbook_config_response(config), false)))
}

pub fn threatbook_config_set(store: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request: ThreatBookConfigSetRequest = parse_request(payload)?;
    let api_key = request.api_key.value;
    store.transact(move |config| {
        root_object_mut(config)?.insert("threatbook_api_key".to_string(), Value::String(api_key));
        Ok((threatbook_config_response(config), true))
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
                updates.insert("notification_number".to_string(), json!(number));
            }
        }
        if request.rectification_number.present {
            if let Some(number) = parse_positive_int(Some(&request.rectification_number.value)) {
                updates.insert("rectification_number".to_string(), json!(number));
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
                json!({
                    "success": true,
                    "updated": false,
                    "message": message,
                    "report_counters": counters,
                    "logs": [message],
                }),
                false,
            ));
        }

        let year = counters
            .get("year")
            .filter(|value| json_truthy(Some(value)))
            .cloned()
            .unwrap_or_else(|| json!(current_local_year()));
        updates.entry("year".to_string()).or_insert(year);
        updates.insert("last_updated".to_string(), Value::String(timestamp));

        let target = object_section_mut(config, "report_counters")?;
        for (key, value) in updates {
            target.insert(key, value);
        }
        let refreshed = normalized_report_counters(config);
        let message = "编号配置已保存到 report_counters";
        Ok((
            json!({
                "success": true,
                "updated": true,
                "message": message,
                "report_counters": refreshed,
                "logs": [message],
            }),
            true,
        ))
    })
}

fn weekly_report_response(config: &Value) -> Value {
    let weekly = config.get("weekly_report").and_then(Value::as_object);
    json!({
        "vulnerability_notice_dir": string_or_empty(weekly.and_then(|value| value.get("vulnerability_notice_dir"))),
        "event_notice_dir": string_or_empty(weekly.and_then(|value| value.get("event_notice_dir"))),
        "exclude_monday_next_notice": json_truthy(weekly.and_then(|value| value.get("exclude_monday_next_notice"))),
        "last_updated": string_or_empty(weekly.and_then(|value| value.get("last_updated"))),
    })
}

fn information_config_response(config: &Value) -> Value {
    let fofa_key = nested_string(config, "fofa", "api_key");
    let hunter_key = nested_string(config, "hunter", "api_key");
    let quake_key = nested_string(config, "quake", "api_key");
    let tyc_cookie = nested_string(config, "tyc", "cookie");
    let aiqicha_cookie = nested_string(config, "aiqicha", "cookie");
    let xunkebao_cookie = nested_string(config, "aiqicha", "xunkebao_cookie");
    let threatbook_key = string_or_empty(config.get("threatbook_api_key"));
    json!({
        "fofa": {
            "email": nested_string(config, "fofa", "email"),
            "api_key": "",
            "api_key_configured": !fofa_key.is_empty(),
            "api_key_masked": mask_secret(&fofa_key),
        },
        "hunter": {
            "api_key": "",
            "api_key_configured": !hunter_key.is_empty(),
            "api_key_masked": mask_secret(&hunter_key),
        },
        "quake": {
            "api_key": "",
            "api_key_configured": !quake_key.is_empty(),
            "api_key_masked": mask_secret(&quake_key),
        },
        "tyc": {
            "cookie": "",
            "cookie_configured": !tyc_cookie.is_empty(),
            "cookie_masked": mask_secret(&tyc_cookie),
        },
        "aiqicha": {
            "cookie": "",
            "cookie_configured": !aiqicha_cookie.is_empty(),
            "cookie_masked": mask_secret(&aiqicha_cookie),
            "xunkebao_cookie": "",
            "xunkebao_cookie_configured": !xunkebao_cookie.is_empty(),
            "xunkebao_cookie_masked": mask_secret(&xunkebao_cookie),
        },
        "threatbook_api_key": "",
        "threatbook_api_key_configured": !threatbook_key.is_empty(),
        "threatbook_api_key_masked": mask_secret(&threatbook_key),
    })
}

fn threatbook_config_response(config: &Value) -> Value {
    let api_key = string_or_empty(config.get("threatbook_api_key"));
    json!({
        "api_key": "",
        "api_key_configured": !api_key.is_empty(),
        "api_key_masked": mask_secret(&api_key),
    })
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
    counters.insert("notification_number".to_string(), json!(1));
    counters.insert("rectification_number".to_string(), json!(1));
    counters.insert("unavailable_notification_numbers".to_string(), json!([]));
    counters.insert("unavailable_rectification_numbers".to_string(), json!([]));
    counters.insert("year".to_string(), json!(current_local_year()));
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
            counters.insert(key.to_string(), json!([]));
        }
    }
    counters
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
    updates.insert(key.to_string(), json!(numbers));
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
        let serialized = response.to_string();
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
        assert_eq!(response["fofa"]["api_key"], "");
        assert_eq!(response["fofa"]["api_key_configured"], true);
        assert_eq!(response["fofa"]["api_key_masked"], "****1234");
        assert_eq!(response["tyc"]["cookie_configured"], true);
        assert_eq!(response["threatbook_api_key"], "");
        assert_eq!(response["threatbook_api_key_configured"], true);

        let threatbook = threatbook_config_response(&config);
        assert_eq!(threatbook["api_key"], "");
        assert_eq!(threatbook["api_key_configured"], true);
        assert_eq!(threatbook["api_key_masked"], "****1357");
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

    static SETTING_TEST_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
}
