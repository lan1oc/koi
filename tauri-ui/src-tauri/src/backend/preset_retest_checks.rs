//! Legacy preset IDs, executed with the same scoped HTTP broker as Agent probes.
use super::*;

pub(super) fn execute(
    tools: &mut Tools<'_>,
    call: &ToolCall,
    remaining: u32,
    targets: &[String],
) -> Result<(Value, u32, bool), String> {
    let id = call.arguments["check_id"]
        .as_str()
        .ok_or("run_preset_check需要check_id")?;
    let catalog: Vec<Value> = serde_json::from_str(include_str!("retest_tool_catalog.json"))
        .map_err(|e| e.to_string())?;
    if !catalog.iter().any(|spec| spec["tool_id"] == id) && id != "check_file_read_signature_replay"
    {
        return Err(format!("未知预设工具: {id}"));
    }
    if matches!(id, "check_ai_python_probe" | "collect_page_context") {
        let mut native_call = call.clone();
        native_call.tool = if id == "check_ai_python_probe" {
            "run_python_probe"
        } else {
            "collect_page_context"
        }
        .into();
        if native_call.tool == "collect_page_context" && native_call.arguments["url"].is_null() {
            native_call.arguments["url"] = json!(targets.first().ok_or("页面采集缺少目标")?);
        }
        return tools.call(&native_call, remaining, targets);
    }
    if id == "tool_external_status" {
        return Ok((
            retest_config::tools_status(&tools.data_dir.join("retest-tools")),
            0,
            false,
        ));
    }
    if id == "tool_install_external_tools" {
        let mut install = call.clone();
        install.tool = "install_tools".into();
        if install.arguments["tools"].is_null() {
            install.arguments["tools"] = json!(["nmap", "ffuf"]);
        }
        return tools.call(&install, remaining, targets);
    }
    if let Some(tool) = match id {
        "check_tls_config" => Some("run_tls_probe"),
        "check_nmap_service_probe" => Some("run_nmap"),
        "check_ffuf_short_discovery" => Some("run_ffuf"),
        "check_sqlmap_context_probe" => Some("run_sqlmap"),
        _ => None,
    } {
        let call = ToolCall {
            finding_id: call.finding_id.clone(),
            tool: tool.into(),
            arguments: {
                let mut arguments = call.arguments.clone();
                arguments["urls"] = arguments
                    .get("urls")
                    .cloned()
                    .unwrap_or_else(|| json!(targets));
                arguments
            },
        };
        return tools.call(&call, remaining, targets);
    }
    let context = retest_notice_context::extract(&tools.notice_text);
    if id == "check_weak_password_login"
        && !call.arguments["request"].is_object()
        && context["http_request_candidates"]
            .as_array()
            .is_none_or(|items| items.is_empty())
    {
        let credential = context["credential_candidates"]
            .as_array()
            .and_then(|items| items.first())
            .ok_or("原通报没有账号密码，未尝试登录")?;
        let target = targets.first().ok_or("登录复核缺少目标")?;
        if remaining < 2 {
            return Err("登录复核请求预算不足".into());
        }
        let (page, used, _) = tools.http(
            &ToolCall {
                finding_id: call.finding_id.clone(),
                tool: "http_request".into(),
                arguments: json!({"url":target,"follow_redirects":true}),
            },
            remaining,
        )?;
        let form_request = (|| {
            if page["success"] != true {
                return Err("无法读取登录页面".to_string());
            }
            let html = page["body_excerpt"].as_str().ok_or("无法读取登录页面")?;
            let forms = Regex::new(r"(?is)<form\b([^>]*)>(.*?)</form>").expect("HTML form");
            let form = forms
                .captures_iter(html)
                .find(|form| form[2].to_lowercase().contains("password"))
                .ok_or("页面没有标准密码表单；请用run_python_probe按原通报适配登录")?;
            let action =
                preset_observations::html_attribute(&form[1], "action").unwrap_or_default();
            let base = page["final_url"].as_str().unwrap_or(target);
            let url = url::Url::parse(base)
                .map_err(|e| e.to_string())?
                .join(&action)
                .map_err(|e| e.to_string())?
                .to_string();
            if !allowed_url(&url, targets) {
                return Err("登录表单提交地址超出授权同源范围".into());
            }
            let method = preset_observations::html_attribute(&form[1], "method")
                .unwrap_or_else(|| "GET".into())
                .to_ascii_uppercase();
            if !matches!(method.as_str(), "GET" | "POST") {
                return Err("登录表单方法不是GET/POST，请按通报适配验证".into());
            }
            let inputs = Regex::new(r"(?is)<input\b[^>]*>").expect("HTML inputs");
            let fields = inputs
                .find_iter(&form[2])
                .filter_map(|input| {
                    let name = preset_observations::html_attribute(input.as_str(), "name")?;
                    let kind = preset_observations::html_attribute(input.as_str(), "type")
                        .unwrap_or_else(|| "text".into())
                        .to_lowercase();
                    if matches!(
                        kind.as_str(),
                        "submit" | "button" | "reset" | "checkbox" | "radio" | "file"
                    ) {
                        return None;
                    }
                    Some((
                        name,
                        kind,
                        preset_observations::html_attribute(input.as_str(), "value")
                            .unwrap_or_default(),
                    ))
                })
                .collect::<Vec<_>>();
            let user = fields
                .iter()
                .position(|(name, kind, _)| {
                    matches!(kind.as_str(), "text" | "email")
                        && ["user", "account", "email", "login", "name"]
                            .iter()
                            .any(|part| name.to_lowercase().contains(part))
                })
                .or_else(|| {
                    fields
                        .iter()
                        .position(|(_, kind, _)| matches!(kind.as_str(), "text" | "email"))
                })
                .ok_or("标准表单缺少账号字段")?;
            let pass = fields
                .iter()
                .position(|(_, kind, _)| kind == "password")
                .ok_or("标准表单缺少密码字段")?;
            let fields = fields
                .into_iter()
                .enumerate()
                .map(|(index, (name, _, value))| {
                    (
                        name,
                        if index == user {
                            credential["username"]
                                .as_str()
                                .unwrap_or_default()
                                .to_string()
                        } else if index == pass {
                            credential["password"]
                                .as_str()
                                .unwrap_or_default()
                                .to_string()
                        } else {
                            value
                        },
                    )
                })
                .collect::<Vec<_>>();
            let body = url::form_urlencoded::Serializer::new(String::new())
                .extend_pairs(&fields)
                .finish();
            let address = if method == "GET" {
                let mut url = url::Url::parse(&url).map_err(|e| e.to_string())?;
                url.query_pairs_mut().extend_pairs(&fields);
                url.to_string()
            } else {
                url
            };
            Ok::<_, String>(
                json!({"url":address,"method":method,"headers":if method=="POST"{json!({"Content-Type":"application/x-www-form-urlencoded"})}else{json!({})},"body":if method=="POST"{body}else{String::new()}}),
            )
        })();
        let arguments = match form_request {
            Ok(arguments) => arguments,
            Err(error) => {
                return Ok((
                    json!({"success":false,"check_id":id,"error":error,"observations":[page]}),
                    used,
                    false,
                ))
            }
        };
        let (result, count, verification) = tools.http(
            &ToolCall {
                finding_id: call.finding_id.clone(),
                tool: "http_request".into(),
                arguments,
            },
            remaining - used,
        )?;
        let observations = vec![page, result];
        return Ok((
            json!({"success":observations[1]["success"],"check_id":id,"analysis":preset_observations::analyze(id,&observations,&context),"observations":observations,"note":"仅提交原通报账号一次，由模型根据业务返回判断"}),
            used + count,
            verification,
        ));
    }
    let replay = matches!(
        id,
        "check_http_request_replay"
            | "check_payload_replay"
            | "check_xss_reflection_replay"
            | "check_file_read_signature_replay"
            | "check_open_redirect_replay"
            | "check_weak_password_login"
    );
    let requests = if replay {
        let mut requests = context["http_request_candidates"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        if call.arguments["request"].is_object() {
            requests = vec![call.arguments["request"].clone()];
        }
        if requests.is_empty() && id != "check_weak_password_login" {
            requests = context["payload_candidates"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|payload| {
                    let raw = payload["raw"].as_str()?;
                    let mut url = url::Url::parse(payload["url"].as_str()?).ok()?;
                    let supplied = url::form_urlencoded::parse(raw.as_bytes()).collect::<Vec<_>>();
                    let names = supplied
                        .iter()
                        .map(|(name, _)| name.as_ref())
                        .collect::<BTreeSet<_>>();
                    let existing = url
                        .query_pairs()
                        .filter(|(name, _)| !names.contains(name.as_ref()))
                        .map(|(k, v)| (k.into_owned(), v.into_owned()))
                        .collect::<Vec<_>>();
                    url.set_query(None);
                    url.query_pairs_mut()
                        .extend_pairs(existing)
                        .extend_pairs(supplied);
                    Some(json!({"url":url.to_string()}))
                })
                .collect();
        }
        if requests.is_empty() && id != "check_weak_password_login" {
            requests = targets
                .iter()
                .filter(|target| target.contains('?'))
                .map(|target| json!({"url":target}))
                .collect();
        }
        if requests.is_empty() {
            return Err(format!("{id}缺少原通报请求/参数，请用http_request或run_python_probe按原通报构造验证；没有执行请求"));
        }
        requests
    } else {
        let mut urls = targets.to_vec();
        if matches!(
            id,
            "check_context_paths"
                | "check_directory_listing_signature"
                | "check_api_schema_exposure"
                | "check_editor_endpoint_config"
                | "check_sensitive_artifact_access"
                | "check_common_path_file_read"
                | "check_source_map_exposure"
        ) {
            for path in context["path_candidates"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
            {
                if let Some(url) = targets
                    .first()
                    .and_then(|base| url::Url::parse(base).ok())
                    .and_then(|base| base.join(path).ok())
                {
                    urls.push(url.to_string());
                }
            }
        }
        if id == "check_sensitive_artifact_access" {
            let lowered = tools.notice_text.to_lowercase();
            for (hint, path) in [
                (".env", "/.env"),
                (".git", "/.git/config"),
                ("swagger", "/swagger.json"),
                ("phpinfo", "/phpinfo.php"),
                ("package.json", "/package.json"),
            ] {
                if lowered.contains(hint) {
                    if let Some(url) = targets
                        .first()
                        .and_then(|base| url::Url::parse(base).ok())
                        .and_then(|base| base.join(path).ok())
                    {
                        urls.push(url.to_string());
                    }
                }
            }
        }
        let mut seen = BTreeSet::new();
        urls.retain(|url| allowed_url(url, targets) && seen.insert(url.clone()));
        urls.into_iter()
            .map(
                |url| json!({"url":url,"method":if id=="check_http_methods"{"OPTIONS"}else{"GET"},
                    "session":id!="check_auth_boundary","headers":if id=="check_security_headers"{json!({"Origin":"https://koi-retest.example.invalid"})}else{json!({})}}),
            )
            .collect()
    };
    let requests = if id == "check_http_methods" {
        requests.into_iter().flat_map(|request| [request.clone(), json!({"url":request["url"],"method":"TRACE","headers":{"X-Koi-Trace":"read-only-proof"}})]).collect::<Vec<_>>()
    } else if id == "check_common_path_file_read" && call.arguments["request"].is_object() {
        vec![call.arguments["request"].clone()]
    } else if id == "check_common_path_file_read" {
        let mut probes = Vec::new();
        for target in targets {
            let base = url::Url::parse(target).map_err(|error| error.to_string())?;
            let pairs = base
                .query_pairs()
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect::<Vec<_>>();
            let key = pairs
                .iter()
                .find(|(key, _)| {
                    ["file", "path", "page", "template", "document"]
                        .iter()
                        .any(|part| key.to_lowercase().contains(part))
                })
                .map(|(key, _)| key.clone());
            if let Some(key) = key {
                for path in [
                    "/etc/passwd",
                    "../../../../etc/passwd",
                    "C:\\Windows\\win.ini",
                ] {
                    let mut url = base.clone();
                    url.set_query(None);
                    url.query_pairs_mut()
                        .extend_pairs(pairs.iter().filter(|(name, _)| name != &key))
                        .append_pair(&key, path);
                    probes.push(json!({"url":url.to_string(),"method":"GET"}));
                }
            }
        }
        if probes.is_empty() {
            return Err(
                "原通报没有文件读取参数；请通过request指定原始请求或用Python探针适配接口".into(),
            );
        }
        probes
    } else {
        requests
    };
    let mut observations = Vec::new();
    let mut used = 0;
    for mut arguments in requests.into_iter().take(4) {
        if used >= remaining {
            break;
        }
        let url = arguments["url"].as_str().ok_or("预设请求缺少URL")?;
        if !allowed_url(url, targets) {
            return Err("原通报请求不属于当前问题的授权同源目标".into());
        }
        // The original Host identifies the authorized URL. The broker owns transport headers.
        if let Some(headers) = arguments.get_mut("headers").and_then(Value::as_object_mut) {
            headers.retain(|name, _| {
                !matches!(
                    name.to_ascii_lowercase().as_str(),
                    "host"
                        | "content-length"
                        | "transfer-encoding"
                        | "connection"
                        | "proxy-authorization"
                        | "proxy-connection"
                        | "upgrade"
                )
            });
        }
        let request = ToolCall {
            finding_id: call.finding_id.clone(),
            tool: "http_request".into(),
            arguments,
        };
        let (result, count, _) = tools.http(&request, remaining - used)?;
        used += count;
        observations.push(result);
    }
    if id == "check_source_map_exposure" {
        let script_pattern =
            Regex::new(r#"(?is)<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']"#).expect("script src");
        let mapping = Regex::new(r"(?m)sourceMappingURL\s*=\s*([^\s*]+)").expect("source map URL");
        let mut pending = observations
            .iter()
            .flat_map(|observation| {
                let body = observation["body_excerpt"].as_str().unwrap_or_default();
                let base = observation["final_url"]
                    .as_str()
                    .or_else(|| observation["url"].as_str())
                    .and_then(|url| url::Url::parse(url).ok());
                script_pattern
                    .captures_iter(body)
                    .filter_map(|c| base.as_ref()?.join(&c[1]).ok())
                    .chain(
                        mapping
                            .captures_iter(body)
                            .filter_map(|c| base.as_ref()?.join(&c[1]).ok()),
                    )
                    .map(|url| url.to_string())
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        let mut index = 0;
        while index < pending.len() && used < remaining && observations.len() < 6 {
            let address = pending[index].clone();
            index += 1;
            if !allowed_url(&address, targets)
                || observations.iter().any(|item| item["url"] == address)
            {
                continue;
            }
            let (result, count, _) = tools.http(
                &ToolCall {
                    finding_id: call.finding_id.clone(),
                    tool: "http_request".into(),
                    arguments: json!({"url":address}),
                },
                remaining - used,
            )?;
            used += count;
            if let Ok(base) = url::Url::parse(&address) {
                for c in mapping.captures_iter(result["body_excerpt"].as_str().unwrap_or_default())
                {
                    if let Ok(url) = base.join(&c[1]) {
                        pending.push(url.to_string());
                    }
                }
            }
            observations.push(result);
        }
    }
    let analysis = preset_observations::analyze(id, &observations, &context);
    let verified = observations
        .iter()
        .any(|o| o["success"] == true && o["body_truncated"] != true);
    let markers = context["expected_markers"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let matches = markers
        .into_iter()
        .filter(|marker| {
            observations.iter().any(|o| {
                o["body_excerpt"]
                    .as_str()
                    .unwrap_or_default()
                    .to_lowercase()
                    .contains(&marker.as_str().unwrap_or_default().to_lowercase())
            })
        })
        .collect::<Vec<_>>();
    Ok((
        json!({"success":verified,"check_id":id,"observations":observations,"analysis":analysis,"matched_notice_markers":matches,"note":"真实观察供模型判断；工具成功或目标200不代表漏洞已修复。"}),
        used,
        verified,
    ))
}
