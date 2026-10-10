//! Original notice context for legacy preset checks and model-directed tools.
use super::*;

pub(super) fn extract(text: &str) -> Value {
    let mut urls = extract_http_urls(text);
    let path_pattern =
        Regex::new(r"(?m)(?:路径|接口|path)\s*[:：=]\s*(/[^\s<>，。；]+)").expect("context paths");
    let mut paths = path_pattern
        .captures_iter(text)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect::<Vec<_>>();
    let request_pattern = Regex::new(
        r"(?im)^(GET|POST|HEAD|OPTIONS|TRACE|PUT|PATCH|DELETE)[ \t]+(\S+)[ \t]+HTTP/\d(?:\.\d)?[ \t]*\r?$",
    )
    .expect("HTTP request block");
    let mut requests = Vec::new();
    for found in request_pattern.captures_iter(text) {
        let tail = &text[found.get(0).expect("request").end()..];
        let mut headers = BTreeMap::new();
        let mut body = Vec::new();
        let mut body_started = false;
        for line in tail.trim_start_matches(['\r', '\n']).lines().take(40) {
            if line.trim().is_empty() {
                if body_started && !body.is_empty() {
                    break;
                }
                body_started = true;
                continue;
            }
            if body_started {
                if line.contains("处置措施") || line.contains("修复建议") {
                    break;
                }
                body.push(line);
            } else if let Some((key, value)) = line.split_once(':') {
                headers.insert(key.trim().to_string(), value.trim().to_string());
            } else {
                break;
            }
        }
        let path = found[2].to_string();
        if path.starts_with('/') && !paths.contains(&path) {
            paths.push(path.clone());
        }
        let host = headers
            .iter()
            .find(|(name, _)| name.eq_ignore_ascii_case("host"))
            .map(|(_, value)| value.as_str());
        let url = if path.starts_with("http") {
            Some(path)
        } else {
            urls.iter()
                .find_map(|base| {
                    let base = url::Url::parse(base).ok()?;
                    if host.is_some_and(|host| {
                        url::Url::parse(&format!("{}://{host}", base.scheme()))
                            .map_or(true, |authority| authority.origin() != base.origin())
                    }) {
                        return None;
                    }
                    base.join(&path).ok().map(|url| url.to_string())
                })
                .or_else(|| host.map(|host| format!("http://{host}{path}")))
        };
        if let Some(url) = url {
            requests.push(json!({"url":url,"method":found[1].to_ascii_uppercase(),"headers":headers,"body":body.join("\n")}));
        }
    }
    let username = Regex::new(r"(?i)(?:用户名|账号|帐号|username|user)\s*[:：=]\s*([^\s，；]+)")
        .expect("credential username");
    let password = Regex::new(r"(?i)(?:密码|password|passwd|pwd)\s*[:：=]\s*([^\s，；]+)")
        .expect("credential password");
    let credentials = username
        .captures(text)
        .and_then(|user| {
            password
                .captures(text)
                .map(|pass| json!({"username":user[1],"password":pass[1]}))
        })
        .into_iter()
        .collect::<Vec<_>>();
    let parameter = Regex::new(r"^[A-Za-z_][A-Za-z0-9_-]{0,60}\s*=").expect("reported parameter");
    let payloads = text
        .lines()
        .map(str::trim)
        .filter(|line| {
            parameter.is_match(line)
                && [
                    "sleep(", "union", "select", "or ", "and ", "<script", "%3c", "alert(", "../",
                    "..\\",
                ]
                .iter()
                .any(|keyword| line.to_lowercase().contains(keyword))
        })
        .take(8)
        .map(|raw| json!({"raw":raw,"url":urls.first()}))
        .collect::<Vec<_>>();
    let markers = [
        "Index of",
        "Parent Directory",
        "swagger",
        "openapi",
        "root:",
        "X-Powered-By",
        "Access-Control-Allow-Origin",
        "jquery",
        "phpinfo",
        "sourcesContent",
    ]
    .into_iter()
    .filter(|marker| text.to_lowercase().contains(&marker.to_lowercase()))
    .collect::<Vec<_>>();
    for request in &requests {
        if let Some(url) = request["url"].as_str() {
            if !urls.iter().any(|item| item == url) {
                urls.push(url.to_string());
            }
        }
    }
    for target in &urls {
        if let Ok(target) = url::Url::parse(target) {
            let path = target.path().to_string();
            if path != "/" && !paths.contains(&path) {
                paths.push(path);
            }
        }
    }
    json!({"target_urls":urls,"path_candidates":paths,"http_request_candidates":requests,
        "credential_candidates":credentials,"payload_candidates":payloads,"expected_markers":markers})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn context_restores_legacy_bare_domain_request_payload_and_credentials() {
        let context=extract("验证过程\n域名：example.test\nPOST /login HTTP/1.1\nHost: example.test\nContent-Type: application/json\n\n{\"login\":\"fixture\"}\n\n用户名：reported-user\n密码：reported-password\n路径：/swagger.json\nIndex of");
        assert!(context["target_urls"]
            .as_array()
            .unwrap()
            .iter()
            .any(|url| matches!(
                url.as_str(),
                Some("https://example.test/login" | "http://example.test/login")
            )));
        assert_eq!(context["http_request_candidates"][0]["method"], "POST");
        assert_eq!(
            context["http_request_candidates"][0]["body"],
            "{\"login\":\"fixture\"}"
        );
        assert_eq!(
            context["credential_candidates"][0]["username"],
            "reported-user"
        );
        assert_eq!(context["path_candidates"][0], "/swagger.json");
    }
}
