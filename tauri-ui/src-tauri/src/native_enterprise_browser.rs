use crate::backend::enterprise_queries::{
    browser_page_has_provider_data_for_query, browser_page_requires_user_action,
    cookie_pairs_for_webview, login_cookie_header, login_navigation_allowed, BrowserPageCapture,
    EnterpriseSource,
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
const BACKGROUND_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum BrowserMode {
    Background,
    Interactive,
}

enum CaptureOutcome {
    Captured(BrowserPageCapture),
    NeedsUserAction { cookie_header: Option<String> },
}

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
    // Loading a script-rendered search page does not imply that a person
    // needs to interact. Only a confirmed login/captcha escalates to a window.
    let mut run = launch_browser(&browser, profile_root, source, BrowserMode::Background)?;
    match capture_from_browser(
        &mut run,
        source,
        &target,
        seed_cookie,
        BrowserMode::Background,
    )? {
        CaptureOutcome::Captured(capture) => Ok(capture),
        CaptureOutcome::NeedsUserAction { cookie_header } => {
            drop(run);
            let mut run = launch_browser(&browser, profile_root, source, BrowserMode::Interactive)?;
            match capture_from_browser(
                &mut run,
                source,
                &target,
                cookie_header.as_deref().unwrap_or(seed_cookie),
                BrowserMode::Interactive,
            )? {
                CaptureOutcome::Captured(capture) => Ok(capture),
                CaptureOutcome::NeedsUserAction { .. } => Err("企业安全验证尚未完成".into()),
            }
        }
    }
}

fn launch_browser(
    browser: &Path,
    profile_root: &Path,
    source: EnterpriseSource,
    mode: BrowserMode,
) -> Result<BrowserRun, String> {
    use std::os::windows::process::CommandExt;

    let profile = temporary_profile(profile_root, source)?;
    let mut command = Command::new(browser);
    command
        .arg(format!("--user-data-dir={}", profile.display()))
        .args([
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--incognito",
        ]);
    match mode {
        BrowserMode::Background => {
            command.args(["--headless=new", "--window-size=1365,900"]);
        }
        BrowserMode::Interactive => {
            command.args(["--start-maximized", "--new-window"]);
        }
    }
    let child = command
        .arg("about:blank")
        .creation_flags(0x0800_0000) // CREATE_NO_WINDOW: never flash a console.
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| {
            let _ = fs::remove_dir(&profile);
            "启动独立企业验证浏览器失败"
        })?;
    Ok(BrowserRun { child, profile })
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
    mode: BrowserMode,
) -> Result<CaptureOutcome, String> {
    let (mut cdp, session) = connect_browser(run)?;
    if mode == BrowserMode::Background {
        let version = cdp.command("Browser.getVersion", json!({}), None)?;
        if let Some(agent) = version["userAgent"].as_str() {
            // Use a desktop Chromium UA, as the legacy silent query did, so
            // the provider serves the same search data in either render mode.
            cdp.command(
                "Network.setUserAgentOverride",
                json!({
                    "userAgent": agent.replace("HeadlessChrome/", "Chrome/"),
                    "acceptLanguage": "zh-CN,zh;q=0.9",
                }),
                Some(&session),
            )?;
        }
    }
    capture_search_page(run, &mut cdp, &session, source, target, seed_cookie, mode)
}

fn connect_browser(run: &mut BrowserRun) -> Result<(Cdp, String), String> {
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
    let mut cdp = Cdp {
        socket,
        next_id: 0,
        #[cfg(test)]
        fixture_html: None,
    };
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
    Ok((cdp, session))
}

fn capture_search_page(
    run: &mut BrowserRun,
    cdp: &mut Cdp,
    session: &str,
    source: EnterpriseSource,
    target: &url::Url,
    seed_cookie: &str,
    mode: BrowserMode,
) -> Result<CaptureOutcome, String> {
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
            Some(session),
        )?;
    }
    cdp.command(
        "Page.navigate",
        json!({"url":target.as_str()}),
        Some(session),
    )?;

    let deadline = Instant::now()
        + match mode {
            BrowserMode::Background => BACKGROUND_TIMEOUT,
            BrowserMode::Interactive => LOGIN_TIMEOUT,
        };
    let query = target_query(source, target);
    let mut user_action_seen_at = None;
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
        let snapshot = cdp.evaluate(session)?;
        let current = url::Url::parse(&snapshot.url).map_err(|_| "浏览器当前 URL 无效")?;
        if current.scheme() == "http" && is_same_search(target, &current) && challenge_seen {
            cdp.command(
                "Page.navigate",
                json!({"url":target.as_str()}),
                Some(session),
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
            && browser_page_has_provider_data_for_query(source, &query, &snapshot.html)
        {
            return finish_capture(
                cdp,
                session,
                source,
                target,
                current,
                snapshot.html,
                seed_cookie,
            )
            .map(CaptureOutcome::Captured);
        }
        if snapshot.too_large {
            return Err("企业验证浏览器页面超过大小限制".into());
        }
        let challenge = browser_challenge_url(&current)
            || browser_page_requires_user_action(&current, &snapshot.visible_text);
        if mode == BrowserMode::Background && challenge {
            // Give transient redirect/loading gates time to resolve by
            // themselves before interrupting the user with a login window.
            let seen_at = user_action_seen_at.get_or_insert_with(Instant::now);
            if snapshot.ready && seen_at.elapsed() >= Duration::from_secs(3) {
                let cookie_header =
                    capture_cookie_header(cdp, session, source, target, seed_cookie)?;
                let _ = cdp.command("Browser.close", json!({}), None);
                return Ok(CaptureOutcome::NeedsUserAction { cookie_header });
            }
        } else {
            user_action_seen_at = None;
        }
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
                    Some(session),
                )?;
                retry_after_challenge = true;
            }
        }
        if on_search && snapshot.ready && !challenge {
            let stable = stable_search_at.get_or_insert_with(Instant::now);
            if stable.elapsed() >= Duration::from_secs(10) {
                return finish_capture(
                    cdp,
                    session,
                    source,
                    target,
                    current,
                    snapshot.html,
                    seed_cookie,
                )
                .map(CaptureOutcome::Captured);
            }
        } else if !challenge {
            stable_search_at = None;
        }
        if Instant::now() >= deadline {
            return Err(match mode {
                BrowserMode::Background => "企业页面后台加载超时（30 秒），请稍后重试",
                BrowserMode::Interactive => "等待手动完成企业登录或安全验证超时（10 分钟）",
            }
            .into());
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
    let cookie_header = capture_cookie_header(cdp, session, source, target, seed_cookie)?;
    let _ = cdp.command("Browser.close", json!({}), None);
    Ok(BrowserPageCapture {
        cookie_header,
        page_html: Some(html),
        final_url: Some(current.to_string()),
    })
}

fn capture_cookie_header(
    cdp: &mut Cdp,
    session: &str,
    source: EnterpriseSource,
    target: &url::Url,
    seed_cookie: &str,
) -> Result<Option<String>, String> {
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
    Ok(login_cookie_header(source, pairs)
        .or_else(|| (!seed_cookie.trim().is_empty()).then(|| seed_cookie.to_string())))
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
    visible_text: String,
    too_large: bool,
    ready: bool,
}

struct Cdp {
    socket: WebSocket<MaybeTlsStream<TcpStream>>,
    next_id: u64,
    #[cfg(test)]
    fixture_html: Option<&'static str>,
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
            #[cfg(test)]
            if response["method"] == "Fetch.requestPaused" {
                if let Some(html) = self.fixture_html {
                    use base64::Engine;
                    self.next_id += 1;
                    let reply = json!({
                        "id":self.next_id,
                        "sessionId":response["sessionId"],
                        "method":"Fetch.fulfillRequest",
                        "params":{
                            "requestId":response["params"]["requestId"],
                            "responseCode":200,
                            "responseHeaders":[{"name":"Content-Type","value":"text/html; charset=utf-8"}],
                            "body":base64::engine::general_purpose::STANDARD.encode(html),
                        },
                    });
                    self.socket
                        .send(Message::Text(reply.to_string().into()))
                        .map_err(|_| "cannot serve isolated browser fixture")?;
                }
                continue;
            }
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
                        visibleText: tooLarge ? '' : (document.body ? document.body.innerText : ''),
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
            visible_text: value["visibleText"]
                .as_str()
                .unwrap_or_default()
                .to_string(),
            too_large: value["tooLarge"].as_bool().unwrap_or(false),
            ready: value["ready"].as_bool().unwrap_or(false),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn visible_windows_for_process(process: u32) -> usize {
        use windows::Win32::Foundation::{HWND, LPARAM};
        use windows::Win32::UI::WindowsAndMessaging::{
            EnumWindows, GetWindowThreadProcessId, IsWindowVisible,
        };
        unsafe extern "system" fn visit(window: HWND, data: LPARAM) -> windows::core::BOOL {
            let (process, count) = &mut *(data.0 as *mut (u32, usize));
            let mut owner = 0;
            GetWindowThreadProcessId(window, Some(&mut owner));
            if owner == *process && IsWindowVisible(window).as_bool() {
                *count += 1;
            }
            true.into()
        }
        let mut result = (process, 0usize);
        unsafe {
            EnumWindows(Some(visit), LPARAM(&mut result as *mut _ as isize)).unwrap();
        }
        result.1
    }

    fn capture_fixture(html: &'static str) -> CaptureOutcome {
        let source = EnterpriseSource::Aiqicha;
        let root = std::env::temp_dir().join(format!(
            "koi-aiqicha-background-test-{}",
            std::process::id()
        ));
        let mut run = launch_browser(
            &find_browser().expect("Chrome or Edge"),
            &root,
            source,
            BrowserMode::Background,
        )
        .unwrap();
        let process = run.child.id();
        let stopped = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let monitor_stop = std::sync::Arc::clone(&stopped);
        let monitor = thread::spawn(move || {
            let mut windows = 0;
            while !monitor_stop.load(std::sync::atomic::Ordering::Relaxed) {
                windows = windows.max(visible_windows_for_process(process));
                thread::sleep(Duration::from_millis(20));
            }
            windows
        });
        let result = (|| {
            let (mut cdp, session) = connect_browser(&mut run)?;
            cdp.fixture_html = Some(html);
            cdp.command(
                "Fetch.enable",
                json!({"patterns":[{"urlPattern":"*"}]}),
                Some(&session),
            )?;
            let target = url::Url::parse("https://aiqicha.baidu.com/s?q=Acme&t=0").unwrap();
            capture_search_page(
                &mut run,
                &mut cdp,
                &session,
                source,
                &target,
                "BDUSS=12345678901234567",
                BrowserMode::Background,
            )
        })();
        drop(run);
        stopped.store(true, std::sync::atomic::Ordering::Relaxed);
        assert_eq!(
            monitor.join().unwrap(),
            0,
            "background queries must never show a browser window"
        );
        result.unwrap()
    }

    #[test]
    #[ignore = "requires installed Chrome or Edge; serves only isolated fixture HTML"]
    fn background_browser_reads_delayed_results_without_any_visible_window() {
        let outcome = capture_fixture(
            r#"<html><body>登录后查看更多功能<span hidden>请完成安全验证</span><script>
            setTimeout(() => {
                const data = document.createElement('script'); data.type = 'application/json';
                data.textContent = JSON.stringify({resultList:[{entName:'Acme',regNo:'C1',legalPerson:'Ada'}]});
                document.body.appendChild(data);
            }, 1500);
        </script></body></html>"#,
        );
        let CaptureOutcome::Captured(capture) = outcome else {
            panic!("search data must stay in the background")
        };
        assert!(browser_page_has_provider_data_for_query(
            EnterpriseSource::Aiqicha,
            "Acme",
            capture.page_html.as_deref().unwrap()
        ));
        assert!(capture.cookie_header.is_some());
    }

    #[test]
    #[ignore = "requires installed Chrome or Edge; serves only isolated fixture HTML"]
    fn background_browser_only_requests_interaction_for_visible_verification() {
        let outcome = capture_fixture("<html><body>请完成安全验证</body></html>");
        let CaptureOutcome::NeedsUserAction { cookie_header } = outcome else {
            panic!("a real verification gate needs the interactive phase")
        };
        assert!(
            cookie_header.is_some(),
            "the login phase must retain the seeded session"
        );
    }

    #[test]
    #[ignore = "requires installed Chrome or Edge; serves only isolated fixture HTML"]
    fn background_browser_empty_results_do_not_open_a_login_window() {
        let outcome = capture_fixture("<html><body>没有找到相关企业 登录/注册</body></html>");
        assert!(
            matches!(outcome, CaptureOutcome::Captured(_)),
            "no results are not a login challenge"
        );
    }

    #[test]
    #[ignore = "live read-only Aiqicha query; requires KOI_ENTERPRISE_AUDIT_DATA and KOI_ENTERPRISE_AUDIT_COMPANY"]
    fn configured_aiqicha_query_succeeds_without_visible_browser() {
        use crate::backend::enterprise_queries::{
            install_production_login_boundary, WebView2LoginBoundary, AIQICHA_COMMAND,
        };
        struct BackgroundBoundary(PathBuf);
        impl WebView2LoginBoundary for BackgroundBoundary {
            fn capture_page(
                &self,
                source: EnterpriseSource,
                target: &str,
                cookie: &str,
            ) -> Result<BrowserPageCapture, String> {
                let mut run = launch_browser(
                    &find_browser().ok_or("no browser")?,
                    &self.0,
                    source,
                    BrowserMode::Background,
                )?;
                let outcome = capture_from_browser(
                    &mut run,
                    source,
                    &url::Url::parse(target).unwrap(),
                    cookie,
                    BrowserMode::Background,
                )?;
                assert_eq!(visible_windows_for_process(run.child.id()), 0);
                match outcome {
                    CaptureOutcome::Captured(capture) => {
                        eprintln!("live audit: background page captured");
                        Ok(capture)
                    }
                    CaptureOutcome::NeedsUserAction { .. } => {
                        eprintln!("live audit: provider requires manual verification");
                        Err("live provider currently requires manual verification".into())
                    }
                }
            }
        }
        let data = PathBuf::from(
            std::env::var_os("KOI_ENTERPRISE_AUDIT_DATA").expect("isolated audit data directory"),
        );
        assert!(data.join(".koi-isolated-verification-copy").is_file());
        let company = std::env::var("KOI_ENTERPRISE_AUDIT_COMPANY").expect("audit company");
        install_production_login_boundary(std::sync::Arc::new(BackgroundBoundary(
            data.join("browser"),
        )))
        .unwrap();
        let core = crate::BackendCore::new_strict(crate::BackendContext::new(
            data.clone(),
            data.join("home"),
            data,
            "4.0.0",
        ))
        .unwrap();
        let response = core.dispatch(AIQICHA_COMMAND, json!({"company":company}));
        assert!(response.ok, "live query command failed");
        let result = response.data;
        // Do not print the response or credentials even if the provider fails.
        assert_eq!(
            result["success"], true,
            "live company query did not return business data"
        );
        assert_eq!(result["rows"][0]["company_name"], company);
    }

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
