use crate::backend::enterprise_queries::{
    browser_page_has_provider_data_for_query, cookie_pairs_for_webview, login_cookie_header,
    login_navigation_allowed, BrowserPageCapture, EnterpriseSource,
};
use serde_json::{json, Value};
use std::fs;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{connect, Message, WebSocket};

const MAX_HTML_BYTES: usize = 8 * 1024 * 1024;
const LOGIN_TIMEOUT: Duration = Duration::from_secs(10 * 60);

pub(super) fn capture_page(
    source: EnterpriseSource,
    target_url: &str,
    seed_cookie: &str,
    profile_root: &Path,
) -> Result<BrowserPageCapture, String> {
    let target = url::Url::parse(target_url).map_err(|_| "企业搜索 URL 无效")?;
    if !login_navigation_allowed(source, &target) {
        return Err("企业搜索 URL 不在允许的站点范围内".into());
    }
    let browser = find_browser().ok_or("未找到 Chrome 或 Edge 浏览器，无法完成企业验证")?;
    let profile = temporary_profile(profile_root, source)?;
    let child = Command::new(browser)
        .arg(format!("--user-data-dir={}", profile.display()))
        .args([
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--start-maximized",
            "--incognito",
            "--new-window",
            "about:blank",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "启动独立企业验证浏览器失败")?;
    let mut run = BrowserRun { child, profile };
    capture_from_browser(&mut run, source, &target, seed_cookie)
}

fn find_browser() -> Option<PathBuf> {
    [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    .into_iter()
    .map(PathBuf::from)
    .find(|path| fs::symlink_metadata(path).is_ok_and(|meta| meta.is_file() && !is_reparse(&meta)))
}

fn temporary_profile(root: &Path, source: EnterpriseSource) -> Result<PathBuf, String> {
    fs::create_dir_all(root).map_err(|_| "创建企业验证 profile 根目录失败")?;
    let meta = fs::symlink_metadata(root).map_err(|_| "检查企业验证 profile 失败")?;
    if !meta.is_dir() || is_reparse(&meta) {
        return Err("企业验证 profile 根目录必须是普通目录".into());
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "系统时间无效")?
        .as_nanos();
    let profile = root.join(format!(
        "{}-{}-{nanos}",
        source.profile_key(),
        std::process::id()
    ));
    fs::create_dir(&profile).map_err(|_| "创建一次性企业验证 profile 失败")?;
    Ok(profile)
}

fn is_reparse(meta: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    meta.file_type().is_symlink() || meta.file_attributes() & 0x400 != 0
}

struct BrowserRun {
    child: Child,
    profile: PathBuf,
}

impl BrowserRun {
    fn close(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
        // Only this invocation's nonce-named child of the checked profile root
        // can be removed. A Chrome child may briefly hold a file open; failure
        // leaves the profile for a later cleanup rather than touching user data.
        let _ = fs::remove_dir_all(&self.profile);
    }
}

impl Drop for BrowserRun {
    fn drop(&mut self) {
        self.close();
    }
}

fn capture_from_browser(
    run: &mut BrowserRun,
    source: EnterpriseSource,
    target: &url::Url,
    seed_cookie: &str,
) -> Result<BrowserPageCapture, String> {
    let port = wait_for_debug_port(run)?;
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
        .map_err(|_| "创建本地浏览器控制连接失败")?;
    let version: Value = client
        .get(format!("http://127.0.0.1:{port}/json/version"))
        .send()
        .and_then(|response| response.json())
        .map_err(|_| "无法连接企业验证浏览器的本地控制端口")?;
    let ws_url = version["webSocketDebuggerUrl"]
        .as_str()
        .ok_or("企业验证浏览器未提供控制端口")?;
    let ws_url_parsed = url::Url::parse(ws_url).map_err(|_| "浏览器控制地址无效")?;
    if ws_url_parsed.scheme() != "ws"
        || ws_url_parsed.host_str() != Some("127.0.0.1")
        || ws_url_parsed.port() != Some(port)
        || !ws_url_parsed.path().starts_with("/devtools/browser/")
    {
        return Err("浏览器控制地址不在本地隔离范围内".into());
    }
    let (mut socket, _) = connect(ws_url).map_err(|_| "连接企业验证浏览器失败")?;
    if let MaybeTlsStream::Plain(stream) = socket.get_mut() {
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .map_err(|_| "设置浏览器控制超时失败")?;
        stream
            .set_write_timeout(Some(Duration::from_secs(5)))
            .map_err(|_| "设置浏览器控制超时失败")?;
    }
    let mut cdp = Cdp { socket, next_id: 0 };
    let targets = cdp.command("Target.getTargets", json!({}), None)?;
    let target_id = targets["targetInfos"]
        .as_array()
        .and_then(|targets| {
            targets.iter().find_map(|target| {
                (target["type"] == "page" && target["url"] == "about:blank")
                    .then(|| target["targetId"].as_str().map(str::to_string))
                    .flatten()
            })
        })
        .ok_or("浏览器未打开隔离的隐私验证窗口")?;
    let session = cdp.command(
        "Target.attachToTarget",
        json!({"targetId":target_id,"flatten":true}),
        None,
    )?["sessionId"]
        .as_str()
        .ok_or("浏览器未附加验证页")?
        .to_string();
    cdp.command("Page.enable", json!({}), Some(&session))?;
    cdp.command("Network.enable", json!({}), Some(&session))?;
    let pairs = cookie_pairs_for_webview(seed_cookie);
    if !pairs.is_empty() {
        let cookies = pairs
            .into_iter()
            .map(|(name, value)| {
                json!({
                    "name":name,
                    "value":value,
                    "domain":format!(".{}", source.cookie_domain()),
                    "path":"/",
                    "secure":true,
                    "httpOnly":false
                })
            })
            .collect::<Vec<_>>();
        cdp.command(
            "Network.setCookies",
            json!({"cookies":cookies}),
            Some(&session),
        )?;
    }
    cdp.command(
        "Page.navigate",
        json!({"url":target.as_str()}),
        Some(&session),
    )?;

    let deadline = Instant::now() + LOGIN_TIMEOUT;
    let mut challenge_seen = false;
    let mut retry_after_challenge = false;
    let mut cleared_at = None;
    let mut stable_search_at = None;
    loop {
        if run
            .child
            .try_wait()
            .map_err(|_| "检查浏览器状态失败")?
            .is_some()
        {
            return Err("用户关闭了企业验证浏览器".into());
        }
        let snapshot = cdp.evaluate(&session)?;
        let current = url::Url::parse(&snapshot.url).map_err(|_| "浏览器当前 URL 无效")?;
        if current.scheme() == "http" && is_same_search(target, &current) && challenge_seen {
            cdp.command(
                "Page.navigate",
                json!({"url":target.as_str()}),
                Some(&session),
            )?;
            retry_after_challenge = true;
            continue;
        }
        if current.scheme() != "about" && !login_navigation_allowed(source, &current) {
            return Err("企业验证浏览器离开了允许的站点范围".into());
        }
        let on_search = is_same_search(target, &current);
        if on_search
            && !snapshot.too_large
            && browser_page_has_provider_data_for_query(
                source,
                &target_query(source, target),
                &snapshot.html,
            )
        {
            return finish_capture(
                &mut cdp,
                &session,
                source,
                target,
                current,
                snapshot.html,
                seed_cookie,
            );
        }
        if snapshot.too_large {
            return Err("企业验证浏览器页面超过大小限制".into());
        }
        let challenge = browser_challenge_url(&current);
        if challenge {
            challenge_seen = true;
            cleared_at = None;
            stable_search_at = None;
        } else if challenge_seen && !retry_after_challenge && on_search {
            let clear = cleared_at.get_or_insert_with(Instant::now);
            if clear.elapsed() >= Duration::from_secs(5) {
                cdp.command(
                    "Page.navigate",
                    json!({"url":target.as_str()}),
                    Some(&session),
                )?;
                retry_after_challenge = true;
            }
        }
        if on_search && snapshot.ready && !challenge {
            let stable = stable_search_at.get_or_insert_with(Instant::now);
            if stable.elapsed() >= Duration::from_secs(10) {
                return finish_capture(
                    &mut cdp,
                    &session,
                    source,
                    target,
                    current,
                    snapshot.html,
                    seed_cookie,
                );
            }
        } else if !challenge {
            stable_search_at = None;
        }
        if Instant::now() >= deadline {
            return Err("等待手动完成企业登录或安全验证超时（10 分钟）".into());
        }
        thread::sleep(Duration::from_millis(750));
    }
}

fn finish_capture(
    cdp: &mut Cdp,
    session: &str,
    source: EnterpriseSource,
    target: &url::Url,
    current: url::Url,
    html: String,
    seed_cookie: &str,
) -> Result<BrowserPageCapture, String> {
    let cookies = cdp.command(
        "Network.getCookies",
        json!({"urls":[target.as_str()]}),
        Some(session),
    )?;
    let pairs = cookies["cookies"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|cookie| {
            Some((
                cookie["name"].as_str()?.to_string(),
                cookie["value"].as_str()?.to_string(),
            ))
        });
    let cookie_header = login_cookie_header(source, pairs)
        .or_else(|| (!seed_cookie.trim().is_empty()).then(|| seed_cookie.to_string()));
    let _ = cdp.command("Browser.close", json!({}), None);
    Ok(BrowserPageCapture {
        cookie_header,
        page_html: Some(html),
        final_url: Some(current.to_string()),
    })
}

fn wait_for_debug_port(run: &mut BrowserRun) -> Result<u16, String> {
    let path = run.profile.join("DevToolsActivePort");
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if let Ok(meta) = fs::symlink_metadata(&path) {
            if !meta.is_file() || is_reparse(&meta) || meta.len() > 1024 {
                return Err("浏览器控制端口文件无效".into());
            }
            if let Ok(raw) = fs::read_to_string(&path) {
                if let Some(port) = parse_debug_port(&raw) {
                    return Ok(port);
                }
            }
        }
        if run
            .child
            .try_wait()
            .map_err(|_| "检查浏览器启动状态失败")?
            .is_some()
        {
            return Err("企业验证浏览器启动后立即退出".into());
        }
        if Instant::now() >= deadline {
            return Err("企业验证浏览器控制端口启动超时".into());
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn parse_debug_port(raw: &str) -> Option<u16> {
    let port = raw.lines().next()?.trim().parse::<u16>().ok()?;
    (port != 0).then_some(port)
}

fn browser_challenge_url(url: &url::Url) -> bool {
    let route = format!("{}{}", url.host_str().unwrap_or_default(), url.path());
    [
        "/login",
        "captcha",
        "passport",
        "antirobot",
        "challenge",
        "verify",
    ]
    .iter()
    .any(|marker| route.to_ascii_lowercase().contains(marker))
}

fn is_same_search(target: &url::Url, current: &url::Url) -> bool {
    target.host_str() == current.host_str()
        && target.path() == current.path()
        && target.query_pairs().next().and_then(|(k, v)| {
            current
                .query_pairs()
                .find(|(name, _)| name == &k)
                .map(|(_, current)| current == v)
        }) == Some(true)
}

fn target_query(source: EnterpriseSource, target: &url::Url) -> String {
    let key = if source == EnterpriseSource::Tianyancha {
        "key"
    } else {
        "q"
    };
    target
        .query_pairs()
        .find_map(|(name, value)| (name == key).then(|| value.into_owned()))
        .unwrap_or_default()
}

struct PageSnapshot {
    url: String,
    html: String,
    too_large: bool,
    ready: bool,
}

struct Cdp {
    socket: WebSocket<MaybeTlsStream<TcpStream>>,
    next_id: u64,
}

impl Cdp {
    fn command(
        &mut self,
        method: &str,
        params: Value,
        session: Option<&str>,
    ) -> Result<Value, String> {
        self.next_id += 1;
        let id = self.next_id;
        let mut message = json!({"id":id,"method":method,"params":params});
        if let Some(session) = session {
            message["sessionId"] = Value::String(session.to_string());
        }
        self.socket
            .send(Message::Text(message.to_string().into()))
            .map_err(|_| format!("浏览器控制命令 {method} 发送失败"))?;
        loop {
            let response = self
                .socket
                .read()
                .map_err(|_| format!("浏览器控制命令 {method} 等待失败"))?;
            let Message::Text(text) = response else {
                continue;
            };
            let response: Value = serde_json::from_str(&text).map_err(|_| "浏览器控制响应无效")?;
            if response["id"].as_u64() != Some(id) {
                continue;
            }
            if response.get("error").is_some() {
                return Err(format!("浏览器控制命令 {method} 执行失败"));
            }
            return Ok(response["result"].clone());
        }
    }

    fn evaluate(&mut self, session: &str) -> Result<PageSnapshot, String> {
        let response = self.command(
            "Runtime.evaluate",
            json!({
                "expression":format!(r#"(() => {{
                    const html = document.documentElement ? document.documentElement.outerHTML : '';
                    const tooLarge = new TextEncoder().encode(html).byteLength > {MAX_HTML_BYTES};
                    return {{
                        url: location.href,
                        html: tooLarge ? '' : html,
                        tooLarge,
                        ready: document.readyState === 'complete'
                    }};
                }})()"#),
                "returnByValue":true
            }),
            Some(session),
        )?;
        let value = &response["result"]["value"];
        Ok(PageSnapshot {
            url: value["url"].as_str().unwrap_or("about:blank").to_string(),
            html: value["html"].as_str().unwrap_or_default().to_string(),
            too_large: value["tooLarge"].as_bool().unwrap_or(false),
            ready: value["ready"].as_bool().unwrap_or(false),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn debug_port_rejects_invalid_values() {
        assert_eq!(parse_debug_port("49152\n/devtools/browser/id"), Some(49152));
        assert_eq!(parse_debug_port("0\n/devtools/browser/id"), None);
        assert_eq!(parse_debug_port("not-a-port"), None);
    }

    #[test]
    fn search_match_ignores_extra_provider_query_params() {
        let target = url::Url::parse("https://aiqicha.baidu.com/s?q=Acme&t=0").unwrap();
        let current = url::Url::parse("https://aiqicha.baidu.com/s?q=Acme&t=0&p_type=2").unwrap();
        assert!(is_same_search(&target, &current));
        assert!(!is_same_search(
            &target,
            &url::Url::parse("https://aiqicha.baidu.com/s?q=Other").unwrap()
        ));
    }

    #[test]
    fn challenge_detection_is_route_based() {
        assert!(browser_challenge_url(
            &url::Url::parse("https://wappass.baidu.com/static/captcha/tuxing_v2.html").unwrap()
        ));
        assert!(!browser_challenge_url(
            &url::Url::parse("https://aiqicha.baidu.com/s?q=Acme").unwrap()
        ));
    }
}
