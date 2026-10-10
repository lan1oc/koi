//! Extract check-specific observations without making the model's final verdict.
use super::*;

fn header<'a>(observation: &'a Value, name: &str) -> &'a str {
    observation["headers"]
        .as_object()
        .into_iter()
        .flatten()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .and_then(|(_, value)| value.as_str())
        .unwrap_or_default()
}

pub(super) fn analyze(id: &str, observations: &[Value], context: &Value) -> Vec<Value> {
    observations.iter().map(|observation| {
        let body = observation["body_excerpt"].as_str().unwrap_or_default();
        let lower = body.to_lowercase();
        let parsed = serde_json::from_str::<Value>(body).ok();
        let mut result = json!({"url":observation["url"],"method":observation["method"],"status_code":observation["status_code"],"response_complete":observation["success"]==true && observation["body_truncated"]!=true});
        let directory = ["index of", "parent directory", "directory listing for"].into_iter().filter(|marker|lower.contains(marker)).collect::<Vec<_>>();
        let signatures = ["phpinfo()", "php version", "[core]", "[extensions]", "sourcescontent", "root:x:0:0:", "root:*:0:0:", "[fonts]", "[mci extensions]", "swagger", "openapi"].into_iter().filter(|marker| lower.contains(marker)).collect::<Vec<_>>();
        match id {
            "check_directory_listing_signature" => result["directory_markers"] = json!(directory),
            "check_auth_boundary" | "check_weak_password_login" => {
                let status = observation["status_code"].as_u64().unwrap_or(0);
                result["access_denied"] = json!(matches!(status,401|403));
                result["login_form_present"] = json!(Regex::new(r#"(?is)<input\b[^>]*\btype\s*=\s*(?:["']password["']|password)"#).expect("password form").is_match(body));
                result["redirect_location"] = json!(header(observation,"location"));
                result["authentication_verified"] = json!(false);
                result["note"] = json!("业务身份与访问权限由模型对照原通报确认，HTTP 200不能证明登录成功或未授权访问");
            }
            "check_header_disclosure" | "check_endpoint_fingerprint" => {
                let selected = ["server","x-powered-by","x-aspnet-version","x-aspnetmvc-version","x-generator","x-runtime","via","x-backend-server","x-application-context","x-jenkins"];
                result["disclosed_headers"] = json!(selected.into_iter().filter_map(|name| { let value=header(observation,name); (!value.is_empty()).then_some((name,value)) }).collect::<BTreeMap<_,_>>());
                if id=="check_endpoint_fingerprint" { result["body_markers"] = json!(signatures); }
            }
            "check_security_headers" => {
                let cors=header(observation,"access-control-allow-origin");
                let csp=header(observation,"content-security-policy");
                let frame=header(observation,"x-frame-options");
                result["cors"] = json!({"allow_origin":cors,"allow_credentials":header(observation,"access-control-allow-credentials"),"test_origin":"https://koi-retest.example.invalid","reflects_test_origin":cors=="https://koi-retest.example.invalid","wildcard":cors=="*"});
                result["frame_policy"] = json!({"x_frame_options":frame,"csp":csp,"has_frame_ancestors":csp.to_lowercase().contains("frame-ancestors"),"policy_present":!frame.is_empty()||csp.to_lowercase().contains("frame-ancestors")});
            }
            "check_http_methods" => {
                let methods=header(observation,"allow").split(',').map(str::trim).filter(|name|!name.is_empty()).collect::<Vec<_>>();
                result["advertised_methods"] = json!(methods);
                result["trace_response"] = json!(observation["method"]=="TRACE" && observation["status_code"]==200);
                result["trace_echo_marker"] = json!(observation["method"]=="TRACE" && lower.contains("x-koi-trace: read-only-proof"));
            }
            "check_api_schema_exposure" => result["schema"] = json!({"openapi":parsed.as_ref().map(|v|v["openapi"].clone()),"swagger":parsed.as_ref().map(|v|v["swagger"].clone()),"paths_present":parsed.as_ref().is_some_and(|v|v["paths"].is_object()),"ui_marker":lower.contains("swagger-ui")||lower.contains("swagger ui")}),
            "check_source_map_exposure" => result["source_map"] = json!({"sources_present":parsed.as_ref().is_some_and(|v|v["sources"].is_array()),"sources_content_present":parsed.as_ref().is_some_and(|v|v["sourcesContent"].is_array()),"version":parsed.as_ref().map(|v|v["version"].clone())}),
            "check_editor_endpoint_config" => result["editor_config"] = json!({"upload_action":parsed.as_ref().map(|v|v["imageActionName"].clone()),"config_keys":parsed.as_ref().and_then(Value::as_object).map(|v|v.keys().filter(|key|key.to_lowercase().contains("action")||key.to_lowercase().contains("upload")).collect::<Vec<_>>()),"upload_vulnerability_verified":false}),
            "check_open_redirect_replay" => {
                let location=header(observation,"location");
                let base=observation["url"].as_str().and_then(|url|url::Url::parse(url).ok());
                let target=base.as_ref().and_then(|url|url.join(location).ok());
                result["location"] = json!(location);
                result["external_redirect"] = json!(matches!(observation["status_code"].as_u64(),Some(301|302|303|307|308)) && !location.is_empty() && target.as_ref().zip(base.as_ref()).is_some_and(|(target,base)|target.origin()!=base.origin()));
            }
            "check_xss_reflection_replay" | "check_payload_replay" => {
                let values=observation["url"].as_str().and_then(|url|url::Url::parse(url).ok()).map(|url|url.query_pairs().map(|(_,v)|v.into_owned()).collect::<Vec<_>>()).unwrap_or_default();
                result["reflected_payloads"] = json!(values.into_iter().filter(|value|!value.is_empty() && (value.contains('<')||value.contains("alert(")||value.contains("../"))).map(|value|json!({"raw_reflected":body.contains(&value),"encoded_reflected":body.contains(&value.replace('&',"&amp;").replace('<',"&lt;").replace('>',"&gt;")),"payload":value,"script_execution_verified":false})).collect::<Vec<_>>());
            }
            "check_file_read_signature_replay" | "check_common_path_file_read" | "check_sensitive_artifact_access" | "check_url_content" => result["content_signatures"] = json!(signatures),
            _ => {}
        }
        result["matched_notice_markers"] = json!(context["expected_markers"].as_array().into_iter().flatten().filter_map(Value::as_str).filter(|marker|lower.contains(&marker.to_lowercase())||observation["headers"].to_string().to_lowercase().contains(&marker.to_lowercase())).collect::<Vec<_>>());
        result
    }).collect()
}

pub(super) fn html_attribute(tag: &str, name: &str) -> Option<String> {
    let re = Regex::new(&format!(
        r#"(?is)(?:^|[\s<]){}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))"#,
        regex::escape(name)
    ))
    .ok()?;
    let matched = re.captures(tag)?;
    let raw = (1..=3).find_map(|index| matched.get(index))?.as_str();
    Some(
        quick_xml::escape::unescape(raw)
            .map(|s| s.into_owned())
            .unwrap_or_else(|_| raw.to_string()),
    )
}
