//! Original notice context for legacy preset checks and model-directed tools.
use super::*;

pub(super) fn extract(text: &str) -> Value {
    let mut urls = extract_http_urls(text);
    append_reported_scan_urls(text, &mut urls);
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

fn append_reported_scan_urls(text: &str, urls: &mut Vec<String>) {
    let host_pattern = Regex::new(
        r"(?i)^\s*Nmap\s+scan\s+report\s+for\s+([^\s()（）〔〕]+)(?:\s*[（(][^\r\n]*[)）〕])?\s*$",
    )
    .expect("reported scan host");
    let port_pattern = Regex::new(
        r"(?i)^\s*([0-9]{1,5})\s*/\s*tcp\s+open\s+(ssl/[^\s]+|https(?:-alt)?|http(?:-proxy)?)\b",
    )
    .expect("reported web service port");
    // Bind each port to the host in its own scan block and to a URL already
    // present in the original notice. Scanner banners and adjacent scans do
    // not authorize another host or every port on the reported host.
    let reported = urls
        .iter()
        .filter_map(|value| url::Url::parse(value).ok())
        .collect::<Vec<_>>();
    let mut scan_host = None;
    for line in text.lines() {
        if let Some(host) = host_pattern.captures(line) {
            scan_host = url::Url::parse(&format!("https://{}/", &host[1]))
                .ok()
                .filter(|host| {
                    host.username().is_empty()
                        && host.password().is_none()
                        && host.port().is_none()
                        && host.path() == "/"
                        && reported.iter().any(|source| source.host() == host.host())
                });
            continue;
        }
        if line.trim_start().starts_with("截图 ")
            || line
                .trim_start()
                .to_ascii_lowercase()
                .starts_with("nmap scan report")
        {
            scan_host = None;
        }
        let Some(host) = scan_host.as_ref() else {
            continue;
        };
        let Some(port) = port_pattern.captures(line) else {
            continue;
        };
        let Ok(port_number) = port[1].parse::<u16>() else {
            continue;
        };
        if port_number == 0 {
            continue;
        }
        let service = port[2].to_ascii_lowercase();
        let mut endpoint = host.clone();
        let scheme = if service.starts_with("ssl/") || service.starts_with("https") {
            "https"
        } else {
            "http"
        };
        if endpoint.set_scheme(scheme).is_err() || endpoint.set_port(Some(port_number)).is_err() {
            continue;
        }
        let endpoint = endpoint.to_string();
        if !urls.contains(&endpoint) {
            urls.push(endpoint);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn context_binds_screenshot_scan_ports_to_the_reported_host() {
        let context = extract(
            "URL: https://reported.test\n截图 1：\nStarting Nmap ( https://nmap.org )\nNmap scan report for reported.test (192.0.2.10)\nPORT STATE SERVICE VERSION\n6443/tcp open ssl/http AppDynamics\n8080/tcp open http proxy\n22/tcp open ssh\n8443/tcp closed https\n0/tcp open https\n99999/tcp open https\nNmap scan report for other.test (192.0.2.11)\n9443/tcp open ssl/http\n截图 2：\n7443/tcp open ssl/http",
        );
        let urls = context["target_urls"].as_array().unwrap();
        assert!(urls.contains(&json!("https://reported.test:6443/")));
        assert!(urls.contains(&json!("http://reported.test:8080/")));
        for port in [22, 8443, 0, 99999, 9443, 7443] {
            assert!(!urls
                .iter()
                .any(|url| url.as_str().unwrap().contains(&format!(":{port}/"))));
        }
        assert!(!urls
            .iter()
            .any(|url| url.as_str().unwrap().contains("other.test")));
        let ocr = extract("URL: https://reported.test\nNmap scan report for reported.test （ 192 ． 0 ． 2 ． 10 〕\n6443 / tcp open ssl/http AppDynamics");
        assert!(ocr["target_urls"]
            .as_array()
            .unwrap()
            .contains(&json!("https://reported.test:6443/")));
    }

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
