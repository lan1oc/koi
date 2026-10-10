//! Normalize the tool-call envelopes used by JSON and function-call model providers.
use serde_json::Value;

pub(crate) fn name(raw: &Value) -> Option<&str> {
    let object = raw
        .get("function")
        .filter(|value| value.is_object())
        .unwrap_or(raw);
    ["tool_name", "tool", "name"]
        .into_iter()
        .find_map(|key| object.get(key).and_then(Value::as_str))
}

pub(crate) fn arguments(raw: &Value) -> Value {
    let object = raw
        .get("function")
        .filter(|value| value.is_object())
        .unwrap_or(raw);
    let value = ["arguments", "args", "parameters", "input"]
        .into_iter()
        .find_map(|key| object.get(key))
        .cloned()
        .unwrap_or_else(|| object.clone());
    if let Value::String(text) = &value {
        serde_json::from_str(text).unwrap_or(value)
    } else if value.is_null() {
        serde_json::json!({})
    } else {
        value
    }
}

pub(crate) fn failure(value: &Value) -> Option<String> {
    if value.get("success") != Some(&Value::Bool(false))
        && value.get("ok") != Some(&Value::Bool(false))
    {
        return None;
    }
    let detail = ["error", "message", "reason"]
        .into_iter()
        .filter_map(|key| value.get(key).and_then(Value::as_str))
        .find(|text| !text.trim().is_empty())
        .map(str::to_string)
        .or_else(|| {
            value["failures"]
                .as_array()
                .and_then(|items| items.first())
                .map(|item| item.to_string())
        })
        .unwrap_or_else(|| "工具返回未完成结果，不能作为成功执行".into());
    Some(match value["error_type"].as_str() {
        Some(kind) => format!("{kind}: {detail}"),
        None => detail,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn tool_audit_parameter_aliases_and_failure_semantics_match_all_provider_envelopes() {
        for key in ["arguments", "args", "parameters", "input"] {
            let mut raw = json!({"name":"http_request"});
            raw[key] = json!({"url":"http://127.0.0.1:9/"});
            assert_eq!(name(&raw), Some("http_request"));
            assert_eq!(arguments(&raw)["url"], "http://127.0.0.1:9/");
            raw[key] = json!("{\"url\":\"http://127.0.0.1:9/\"}");
            assert!(arguments(&raw).is_object());
        }
        assert_eq!(
            name(&json!({"function":{"name":"tool_status","arguments":"{}"}})),
            Some("tool_status")
        );
        assert!(
            failure(&json!({"success":false,"message":"runtime unavailable"}))
                .unwrap()
                .contains("runtime unavailable")
        );
        assert!(failure(&json!({"success":true,"findings":[]})).is_none());
    }
}
