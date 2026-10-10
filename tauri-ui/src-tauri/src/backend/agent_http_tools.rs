//! Scoped native implementations for SQL request replay and optional path discovery.
use super::*;

pub(super) fn paths(
    tools: &mut Tools<'_>,
    call: &ToolCall,
    remaining: u32,
    targets: &[String],
) -> Result<(Value, u32, bool), String> {
    let mut candidates = targets.to_vec();
    let context = retest_notice_context::extract(&tools.notice_text);
    for path in call.arguments["paths"]
        .as_array()
        .into_iter()
        .flatten()
        .chain(context["path_candidates"].as_array().into_iter().flatten())
        .filter_map(Value::as_str)
    {
        if let Some(base) = targets.first().and_then(|base| url::Url::parse(base).ok()) {
            let address = base
                .join(path)
                .map_err(|error| error.to_string())?
                .to_string();
            if !allowed_url(&address, targets) {
                return Err("路径发现目标超出当前问题的授权同源范围".into());
            }
            candidates.push(address);
        }
    }
    let mut seen = BTreeSet::new();
    candidates.retain(|url| seen.insert(url.clone()));
    let mut observations = Vec::new();
    let mut used = 0;
    for url in candidates.into_iter().take(remaining.min(40) as usize) {
        let (result, count, _) = tools.http(
            &ToolCall {
                finding_id: call.finding_id.clone(),
                tool: "http_request".into(),
                arguments: json!({"url":url,"follow_redirects":false}),
            },
            remaining - used,
        )?;
        used += count;
        observations.push(result);
    }
    let success = observations.iter().any(|value| value["success"] == true);
    Ok((
        json!({"success":success,"tool":"ffuf","engine":"rust_http_shortlist","ffuf_available":false,"http_requests_used":used,"observations":observations,"message":"ffuf不可用，已使用内置HTTP工具核验原通报/模型指定短名单路径；可达性不是漏洞判定"}),
        used,
        false,
    ))
}

pub(super) fn sql(
    tools: &mut Tools<'_>,
    call: &ToolCall,
    remaining: u32,
    targets: &[String],
) -> Result<(Value, u32, bool), String> {
    if remaining < 2 {
        return Err("SQL验证需要至少两次请求预算".into());
    }
    let context = retest_notice_context::extract(&tools.notice_text);
    let mut request = call
        .arguments
        .get("request")
        .filter(|value| value.is_object())
        .cloned()
        .or_else(|| {
            context["http_request_candidates"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|value| {
                    value["url"]
                        .as_str()
                        .is_some_and(|url| allowed_url(url, targets))
                })
                .cloned()
        })
        .unwrap_or_else(|| json!({"url":targets.first()}));
    let address = request["url"].as_str().ok_or("SQL验证缺少原始URL")?;
    let base = url::Url::parse(address)
        .or_else(|_| {
            targets
                .first()
                .ok_or(url::ParseError::RelativeUrlWithoutBase)
                .and_then(|base| url::Url::parse(base)?.join(address))
        })
        .map_err(|error| error.to_string())?;
    if !allowed_url(base.as_str(), targets) {
        return Err("SQL原始请求不属于当前问题的授权同源目标".into());
    }
    request["url"] = json!(base.to_string());
    if let Some(headers) = request["headers"].as_object_mut() {
        headers.retain(|name, _| {
            !matches!(
                name.to_ascii_lowercase().as_str(),
                "host" | "content-length" | "connection" | "transfer-encoding"
            )
        });
    }
    let selected = call.arguments["parameter"].as_str();
    let mut mutations = Vec::new();
    let query = base
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect::<Vec<_>>();
    for (index, (name, _)) in query
        .iter()
        .enumerate()
        .filter(|(_, (name, _))| selected.is_none_or(|selected| selected == name))
    {
        let mut fields = query.clone();
        fields[index].1.push('\'');
        let mut url = base.clone();
        url.set_query(None);
        url.query_pairs_mut().extend_pairs(fields);
        let mut modified = request.clone();
        modified["url"] = json!(url.to_string());
        mutations.push((name.clone(), modified));
    }
    let content_type = request["headers"]
        .as_object()
        .into_iter()
        .flatten()
        .find(|(name, _)| name.eq_ignore_ascii_case("content-type"))
        .and_then(|(_, value)| value.as_str())
        .unwrap_or_default();
    let json_body = request
        .get("json_body")
        .or_else(|| request.get("json"))
        .cloned()
        .or_else(|| {
            content_type
                .contains("json")
                .then(|| {
                    serde_json::from_str::<Value>(request["body"].as_str().unwrap_or_default()).ok()
                })
                .flatten()
        });
    if let Some(body) = json_body.filter(Value::is_object) {
        for (name, value) in body
            .as_object()
            .into_iter()
            .flatten()
            .filter(|(name, _)| selected.is_none_or(|selected| selected == name.as_str()))
        {
            if !value.is_string() && !value.is_number() {
                continue;
            }
            let mut modified = request.clone();
            let mut data = body.clone();
            data[name] = json!(format!(
                "{}'",
                value
                    .as_str()
                    .map(str::to_string)
                    .unwrap_or_else(|| value.to_string())
            ));
            modified
                .as_object_mut()
                .expect("request object")
                .remove("body");
            modified
                .as_object_mut()
                .expect("request object")
                .remove("json");
            modified["json_body"] = data;
            mutations.push((name.clone(), modified));
        }
    } else if content_type.contains("x-www-form-urlencoded") {
        let fields =
            url::form_urlencoded::parse(request["body"].as_str().unwrap_or_default().as_bytes())
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect::<Vec<_>>();
        for (index, (name, _)) in fields
            .iter()
            .enumerate()
            .filter(|(_, (name, _))| selected.is_none_or(|selected| selected == name))
        {
            let mut data = fields.clone();
            data[index].1.push('\'');
            let mut modified = request.clone();
            modified["body"] = json!(url::form_urlencoded::Serializer::new(String::new())
                .extend_pairs(data)
                .finish());
            mutations.push((name.clone(), modified));
        }
    }
    if mutations.is_empty() {
        return Err(
            "SQL验证缺少可核验的URL/JSON/表单参数；请指定原始request和parameter或使用Python探针"
                .into(),
        );
    }
    let (baseline, mut used, _) = tools.http(
        &ToolCall {
            finding_id: call.finding_id.clone(),
            tool: "http_request".into(),
            arguments: request,
        },
        remaining,
    )?;
    if baseline["success"] != true || baseline["body_truncated"] == true {
        return Ok((
            json!({"success":false,"tool":"sqlmap","error":"SQL基线请求未完成或响应截断","observations":[baseline]}),
            used,
            false,
        ));
    }
    let baseline_markers = super::super::retest_external::sql_error_markers(
        baseline["body_excerpt"].as_str().unwrap_or_default(),
    );
    let mut checks = Vec::new();
    let mut observations = vec![baseline];
    for (parameter, arguments) in mutations.into_iter().take(3) {
        if used >= remaining {
            break;
        }
        let (observation, count, _) = tools.http(
            &ToolCall {
                finding_id: call.finding_id.clone(),
                tool: "http_request".into(),
                arguments,
            },
            remaining - used,
        )?;
        used += count;
        let markers = super::super::retest_external::sql_error_markers(
            observation["body_excerpt"].as_str().unwrap_or_default(),
        );
        let new = markers
            .difference(&baseline_markers)
            .cloned()
            .collect::<Vec<_>>();
        checks.push(json!({"parameter":parameter,"new_error_markers":new,"response_complete":observation["success"]==true && observation["body_truncated"]!=true}));
        observations.push(observation);
    }
    let success = checks
        .iter()
        .all(|value| value["response_complete"] == true)
        && !checks.is_empty();
    Ok((
        json!({"success":success,"tool":"sqlmap","engine":"rust_sql_differential","checks":checks,"observations":observations,"http_requests_used":used,"message":"按原始方法、认证和参数执行SQL基线/单引号差分；未出现错误不代表不存在SQL注入"}),
        used,
        success,
    ))
}
