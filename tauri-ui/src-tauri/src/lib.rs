use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
mod app_paths;
mod backend;
mod initialization;
#[cfg(windows)]
mod native_enterprise_browser;

pub use backend::{run_internal_worker_from_args, BackendContext, BackendCore, BackendResponse};

use app_paths::{resolve_app_paths, AppPaths, PathResolutionOptions};
use initialization::{initialize_from_options_with_progress, INITIALIZATION_PROGRESS_EVENT};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};
use tauri::Emitter;
use tauri::{Manager, PhysicalPosition, PhysicalSize, WindowEvent};

#[cfg(windows)]
use windows::Win32::Foundation::{HWND, POINT};
#[cfg(windows)]
use windows::Win32::Graphics::Gdi::{ClientToScreen, CreateRoundRectRgn, SetWindowRgn};
#[cfg(windows)]
use windows::Win32::UI::WindowsAndMessaging::{SetWindowPos, SWP_NOACTIVATE, SWP_NOZORDER};

#[cfg(windows)]
const WINDOW_RADIUS_PX: i32 = 18;
const TRAY_SHOW_ID: &str = "tray-show";
const TRAY_HIDE_ID: &str = "tray-hide";
const TRAY_EXIT_ID: &str = "tray-exit";

static NATIVE_BACKEND_CORE: OnceLock<Result<BackendCore, String>> = OnceLock::new();
static WINDOW_BOUNDS: OnceLock<Mutex<Option<SavedWindowBounds>>> = OnceLock::new();

#[cfg(windows)]
struct TauriEnterpriseLoginBoundary {
    app: tauri::AppHandle<tauri::Wry>,
    profile_root: PathBuf,
    interactive_login: Mutex<()>,
}

#[cfg(windows)]
impl TauriEnterpriseLoginBoundary {
    fn new(app: tauri::AppHandle<tauri::Wry>, profile_root: PathBuf) -> Self {
        Self {
            app,
            profile_root,
            interactive_login: Mutex::new(()),
        }
    }
}

#[cfg(windows)]
impl backend::enterprise_queries::WebView2LoginBoundary for TauriEnterpriseLoginBoundary {
    fn capture_page(
        &self,
        source: backend::enterprise_queries::EnterpriseSource,
        target_url: &str,
        seed_cookie: &str,
    ) -> Result<backend::enterprise_queries::BrowserPageCapture, String> {
        use std::time::{Duration, Instant};
        use tauri::{WebviewUrl, WebviewWindowBuilder};

        // A single interactive login at a time prevents two backend calls
        // from racing the same site's persistent WebView2 profile.
        let _guard = self
            .interactive_login
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if source == backend::enterprise_queries::EnterpriseSource::Aiqicha {
            return native_enterprise_browser::capture_page(
                source,
                target_url,
                seed_cookie,
                &self.profile_root,
            );
        }
        let profile_dir = self.profile_root.join(source.profile_key());
        fs::create_dir_all(&profile_dir)
            .map_err(|error| format!("创建隔离 WebView2 profile 失败: {error}"))?;
        let metadata = fs::symlink_metadata(&profile_dir)
            .map_err(|error| format!("检查隔离 WebView2 profile 失败: {error}"))?;
        if !metadata.is_dir() || windows_reparse_path(&metadata) {
            return Err("隔离 WebView2 profile 必须是非重解析目录".to_string());
        }
        let target_url =
            url::Url::parse(target_url).map_err(|error| format!("企业查询 URL 无效: {error}"))?;
        if !backend::enterprise_queries::login_navigation_allowed(source, &target_url) {
            return Err("企业查询 URL 不在站点隔离范围内".to_string());
        }
        let login_url = url::Url::parse(source.login_url())
            .map_err(|error| format!("企业登录 URL 无效: {error}"))?;
        let label = format!(
            "enterprise-login-{}-{}",
            source.profile_key(),
            enterprise_login_nonce()
        );
        let navigation_source = source;
        let window =
            WebviewWindowBuilder::new(&self.app, &label, WebviewUrl::External(login_url.clone()))
                .title(source.login_title())
                .resizable(true)
                .visible(false)
                .data_directory(profile_dir)
                .on_navigation(move |url| {
                    backend::enterprise_queries::login_navigation_allowed(navigation_source, url)
                })
                // A popup would escape the explicit navigation callback and
                // could receive a different WebView2 profile. Provider login
                // must complete in this dedicated, site-isolated window.
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                .build()
                .map_err(|error| format!("创建企业登录 WebView2 窗口失败: {error}"))?;

        // The persisted DPAPI cookie is authoritative input. Inject it into
        // this provider-only profile before navigating to the actual search
        // URL, matching the successful legacy browser fallback without using
        // the user's ordinary browser profile.
        for (name, value) in backend::enterprise_queries::cookie_pairs_for_webview(seed_cookie) {
            let cookie = tauri::webview::Cookie::build((name, value))
                .domain(source.cookie_domain().to_string())
                .path("/")
                .secure(true)
                .build();
            window
                .set_cookie(cookie)
                .map_err(|error| format!("向企业查询 WebView2 注入 Cookie 失败: {error}"))?;
        }
        window
            .navigate(target_url.clone())
            .map_err(|error| format!("企业查询 WebView2 导航失败: {error}"))?;

        let deadline = Instant::now() + Duration::from_secs(10 * 60);
        let silent_deadline = Instant::now() + Duration::from_secs(30);
        let mut visible = false;
        let mut challenge_cleared_at = None;
        let mut last_html = None;
        let mut last_url = None;
        loop {
            if self.app.get_webview_window(&label).is_none() {
                return Err(format!("用户关闭了{}验证窗口", source.display_name()));
            }

            let current_url = window
                .url()
                .map_err(|error| format!("读取企业查询 WebView2 URL 失败: {error}"))?;
            if current_url.scheme() == "https"
                && !backend::enterprise_queries::login_navigation_allowed(source, &current_url)
            {
                let _ = window.close();
                return Err("企业查询 WebView2 导航离开了站点隔离范围".to_string());
            }
            let expected_page = enterprise_search_url_matches(source, &target_url, &current_url);
            let html = match enterprise_webview_html(&window, Duration::from_secs(3)) {
                Ok(Some(html)) => html,
                Ok(None) => String::new(),
                Err(error) if Instant::now() >= deadline => {
                    let _ = window.close();
                    return Err(error);
                }
                Err(_) => String::new(),
            };
            if html == ENTERPRISE_HTML_TOO_LARGE {
                let _ = window.close();
                return Err("企业查询 WebView2 页面超过大小限制".to_string());
            }
            let needs_action =
                backend::enterprise_queries::browser_page_requires_user_action(&current_url, &html);
            if expected_page && !html.is_empty() {
                last_html = Some(html.clone());
                last_url = Some(current_url.clone());
                if backend::enterprise_queries::browser_page_has_provider_data(source, &html) {
                    return finish_enterprise_capture(
                        &window,
                        source,
                        &target_url,
                        current_url,
                        html,
                        seed_cookie,
                    );
                }
            }

            if needs_action && !visible {
                window
                    .show()
                    .and_then(|_| window.set_focus())
                    .map_err(|error| format!("显示企业登录 WebView2 窗口失败: {error}"))?;
                visible = true;
                challenge_cleared_at = None;
            } else if visible && !needs_action && expected_page {
                let cleared = challenge_cleared_at.get_or_insert_with(Instant::now);
                if cleared.elapsed() >= Duration::from_secs(15) {
                    if let (Some(html), Some(final_url)) = (last_html.clone(), last_url.clone()) {
                        return finish_enterprise_capture(
                            &window,
                            source,
                            &target_url,
                            final_url,
                            html,
                            seed_cookie,
                        );
                    }
                }
            } else if visible && needs_action {
                challenge_cleared_at = None;
            }

            if !visible && Instant::now() >= silent_deadline {
                if let (Some(html), Some(final_url)) = (last_html.clone(), last_url.clone()) {
                    return finish_enterprise_capture(
                        &window,
                        source,
                        &target_url,
                        final_url,
                        html,
                        seed_cookie,
                    );
                }
                if expected_page {
                    let _ = window.close();
                    return Err("企业查询 WebView2 未能读取页面内容".to_string());
                }
            }
            if Instant::now() >= deadline {
                let _ = window.close();
                return Err("企业登录或验证窗口等待超时（10 分钟）".to_string());
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    }
}

#[cfg(windows)]
const ENTERPRISE_HTML_TOO_LARGE: &str = "__KOI_ENTERPRISE_HTML_TOO_LARGE__";

#[cfg(windows)]
fn enterprise_search_url_matches(
    source: backend::enterprise_queries::EnterpriseSource,
    target: &url::Url,
    current: &url::Url,
) -> bool {
    if !backend::enterprise_queries::login_navigation_allowed(source, current) {
        return false;
    }
    let key = match source {
        backend::enterprise_queries::EnterpriseSource::Tianyancha => "key",
        backend::enterprise_queries::EnterpriseSource::Aiqicha => "q",
    };
    let expected = target
        .query_pairs()
        .find_map(|(name, value)| (name == key).then(|| value.into_owned()));
    let actual = current
        .query_pairs()
        .find_map(|(name, value)| (name == key).then(|| value.into_owned()));
    expected.is_some() && expected == actual
}

#[cfg(windows)]
fn enterprise_webview_html(
    window: &tauri::WebviewWindow<tauri::Wry>,
    timeout: std::time::Duration,
) -> Result<Option<String>, String> {
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    window
        .eval_with_callback(
            r#"(() => {
                const html = document.documentElement ? document.documentElement.outerHTML : '';
                const bytes = new TextEncoder().encode(html).byteLength;
                return bytes > 8388608 ? '__KOI_ENTERPRISE_HTML_TOO_LARGE__' : html;
            })()"#,
            move |value| {
                let _ = sender.send(value);
            },
        )
        .map_err(|error| format!("读取企业查询 WebView2 页面失败: {error}"))?;
    let raw = receiver
        .recv_timeout(timeout)
        .map_err(|_| "读取企业查询 WebView2 页面超时".to_string())?;
    if raw == "null" || raw.trim().is_empty() {
        return Ok(None);
    }
    match serde_json::from_str::<String>(&raw) {
        Ok(html) => Ok(Some(html)),
        Err(_) => Ok(Some(raw)),
    }
}

#[cfg(windows)]
fn finish_enterprise_capture(
    window: &tauri::WebviewWindow<tauri::Wry>,
    source: backend::enterprise_queries::EnterpriseSource,
    target_url: &url::Url,
    final_url: url::Url,
    html: String,
    seed_cookie: &str,
) -> Result<backend::enterprise_queries::BrowserPageCapture, String> {
    if !backend::enterprise_queries::login_navigation_allowed(source, &final_url) {
        let _ = window.close();
        return Err("企业查询 WebView2 最终页面不在站点隔离范围内".to_string());
    }
    let cookie_header = window
        .cookies_for_url(target_url.clone())
        .ok()
        .and_then(|cookies| {
            let pairs = cookies
                .into_iter()
                .map(|cookie| (cookie.name().to_string(), cookie.value().to_string()));
            backend::enterprise_queries::login_cookie_header(source, pairs)
        })
        .or_else(|| {
            let pairs = backend::enterprise_queries::cookie_pairs_for_webview(seed_cookie);
            (!pairs.is_empty()).then(|| {
                pairs
                    .into_iter()
                    .map(|(name, value)| format!("{name}={value}"))
                    .collect::<Vec<_>>()
                    .join("; ")
            })
        });
    let _ = window.close();
    Ok(backend::enterprise_queries::BrowserPageCapture {
        cookie_header,
        page_html: Some(html),
        final_url: Some(final_url.to_string()),
    })
}

#[cfg(windows)]
fn windows_reparse_path(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_type().is_symlink() || metadata.file_attributes() & 0x400 != 0
}

#[cfg(windows)]
fn enterprise_login_nonce() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};
    static NEXT: AtomicU64 = AtomicU64::new(1);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "{}-{}-{nanos}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )
}

#[derive(Clone, Copy)]
struct SavedWindowBounds {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
}

fn window_bounds() -> &'static Mutex<Option<SavedWindowBounds>> {
    WINDOW_BOUNDS.get_or_init(|| Mutex::new(None))
}

fn app_root_dir() -> Option<PathBuf> {
    if let Some(dir) = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.to_path_buf()))
    {
        return Some(dir);
    }

    let mut dir = std::env::current_dir().ok()?;
    if dir.file_name().and_then(|name| name.to_str()) == Some("src-tauri") {
        dir.pop();
    }
    if dir.file_name().and_then(|name| name.to_str()) == Some("tauri-ui") {
        dir.pop();
    }
    Some(dir)
}

fn workspace_root_for(root_dir: &Path) -> Option<PathBuf> {
    if cfg!(debug_assertions) {
        root_dir
            .parent()
            .and_then(Path::parent)
            .map(Path::to_path_buf)
    } else {
        None
    }
}

fn runtime_paths(root_dir: &Path) -> Result<(AppPaths, PathResolutionOptions), String> {
    let workspace_root = workspace_root_for(root_dir);
    let options = PathResolutionOptions::from_process(root_dir.to_path_buf(), workspace_root)
        .map_err(|error| error.to_string())?;
    let paths = resolve_app_paths(&options)
        .map_err(|error| format!("路径初始化失败 [{}]: {error}", error.code()))?;
    Ok((paths, options))
}

fn app_user_data_dir() -> Option<PathBuf> {
    let root_dir = app_root_dir()?;
    runtime_paths(&root_dir)
        .ok()
        .map(|(paths, _)| paths.user_data_dir)
}

fn retest_cancel_key(value: &str) -> String {
    let cleaned: String = value
        .trim()
        .chars()
        .take(120)
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-') {
                ch
            } else {
                '_'
            }
        })
        .collect();
    if cleaned.is_empty() {
        "unknown".to_string()
    } else {
        cleaned
    }
}

fn write_retest_cancel_marker(kind: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Ok(());
    }
    let data_dir = app_user_data_dir().ok_or("无法定位应用数据目录")?;
    let control_dir = data_dir.join(".retest-control");
    fs::create_dir_all(&control_dir).map_err(|error| error.to_string())?;
    let epoch_ns = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    fs::write(
        control_dir.join(format!("{}-{}.stop", kind, retest_cancel_key(value))),
        epoch_ns.to_string(),
    )
    .map_err(|error| error.to_string())
}

fn close_to_tray_enabled() -> bool {
    let candidates = close_to_tray_candidates(app_user_data_dir());

    candidates.into_iter().any(|path| {
        let Ok(raw) = std::fs::read_to_string(path) else {
            return false;
        };
        let Ok(config) = serde_json::from_str::<Value>(&raw) else {
            return false;
        };
        config
            .get("ui_settings")
            .and_then(|settings| settings.get("close_to_tray"))
            .and_then(Value::as_bool)
            .unwrap_or(false)
    })
}

fn close_to_tray_candidates(user_data_dir: Option<PathBuf>) -> Vec<PathBuf> {
    user_data_dir
        .into_iter()
        .map(|data_dir| data_dir.join("config.json"))
        .collect()
}

#[cfg(test)]
mod isolation_tests {
    use super::close_to_tray_candidates;
    use std::path::PathBuf;

    #[test]
    fn strict_close_to_tray_candidates_only_use_isolated_data() {
        let data = PathBuf::from(r"C:\temp\koi-test-data");
        let candidates = close_to_tray_candidates(Some(data.clone()));

        assert_eq!(candidates, vec![data.join("config.json")]);
    }

    #[test]
    fn close_to_tray_candidates_ignore_missing_data() {
        assert!(close_to_tray_candidates(None).is_empty());
    }
}

#[tauri::command]
async fn call_backend(command: String, payload: Value) -> BackendResponse {
    tauri::async_runtime::spawn_blocking(move || call_backend_sync(command, payload))
        .await
        .unwrap_or_else(|error| BackendResponse {
            ok: false,
            data: Value::Null,
            error: Some(error.to_string()),
        })
}

#[tauri::command]
fn signal_retest_stop(session_id: String, task_id: Option<String>) -> Result<bool, String> {
    write_retest_cancel_marker("session", &session_id)?;
    if let Some(task_id) = task_id.as_deref() {
        write_retest_cancel_marker("task", task_id)?;
    }
    Ok(true)
}

#[tauri::command]
fn sync_window_region(window: tauri::Window) -> bool {
    update_window_region(&window);
    is_app_maximized(&window)
}

#[tauri::command]
fn toggle_app_maximize(window: tauri::Window) -> bool {
    let maximized = toggle_window_maximized(&window);
    update_window_region(&window);
    maximized
}

#[tauri::command]
async fn initialize_runtime(app: tauri::AppHandle) -> initialization::InitializationResponse {
    tauri::async_runtime::spawn_blocking(move || {
        let root_dir = match app_root_dir() {
            Some(root_dir) => root_dir,
            None => {
                return initialization::InitializationResponse::failed(
                    "unable to resolve application directory".to_string(),
                )
            }
        };
        let workspace_root = workspace_root_for(&root_dir);
        let options = match PathResolutionOptions::from_process(root_dir, workspace_root) {
            Ok(options) => options,
            Err(error) => return initialization::InitializationResponse::failed(error.to_string()),
        };
        initialize_from_options_with_progress(&options, |progress| {
            let _ = app.emit(INITIALIZATION_PROGRESS_EVENT, progress);
        })
    })
    .await
    .unwrap_or_else(|error| initialization::InitializationResponse::failed(error.to_string()))
}

fn call_backend_sync(command: String, payload: Value) -> BackendResponse {
    match native_backend_core() {
        Ok(core) => core.dispatch(&command, payload),
        Err(error) => BackendResponse {
            ok: false,
            data: Value::Null,
            error: Some(format!("Rust 后端初始化失败: {error}")),
        },
    }
}

fn native_backend_core() -> Result<&'static BackendCore, String> {
    match NATIVE_BACKEND_CORE.get_or_init(|| {
        let root_dir = app_root_dir().ok_or("unable to resolve application directory")?;
        let (paths, _) = runtime_paths(&root_dir)?;
        let context = BackendContext::new(
            paths.user_data_dir,
            dirs_home(),
            std::env::current_dir().unwrap_or(root_dir),
            env!("CARGO_PKG_VERSION"),
        );
        // Development and release binaries share the same Rust-only gate;
        // oracle compatibility constructors are test-only concerns.
        BackendCore::new_strict(context)
    }) {
        Ok(core) => Ok(core),
        Err(error) => Err(error.clone()),
    }
}

fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn show_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

fn toggle_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        match window.is_visible() {
            Ok(true) => {
                let _ = window.hide();
            }
            _ => {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }
    }
}

#[cfg(windows)]
fn apply_window_region(
    hwnd: windows::Win32::Foundation::HWND,
    maximized: bool,
    size: tauri::Result<tauri::PhysicalSize<u32>>,
) {
    if maximized {
        let _ = unsafe { SetWindowRgn(hwnd, None, true) };
        return;
    }

    let Ok(size) = size else {
        return;
    };

    let width = size.width.min(i32::MAX as u32) as i32;
    let height = size.height.min(i32::MAX as u32) as i32;
    if width <= 0 || height <= 0 {
        return;
    }

    let region = unsafe {
        CreateRoundRectRgn(
            0,
            0,
            width + 1,
            height + 1,
            WINDOW_RADIUS_PX * 2,
            WINDOW_RADIUS_PX * 2,
        )
    };

    if !region.is_invalid() {
        let _ = unsafe { SetWindowRgn(hwnd, Some(region), true) };
    }
}

#[cfg(windows)]
fn update_window_region<R: tauri::Runtime>(window: &tauri::Window<R>) {
    if let Ok(hwnd) = window.hwnd() {
        apply_window_region(hwnd, is_app_maximized(window), window.inner_size());
    }
}

#[cfg(windows)]
fn update_webview_window_region<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) {
    if let Ok(hwnd) = window.hwnd() {
        apply_window_region(hwnd, is_webview_app_maximized(window), window.inner_size());
    }
}

#[cfg(windows)]
fn is_app_maximized<R: tauri::Runtime>(window: &tauri::Window<R>) -> bool {
    window_bounds()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .is_some()
        || window.is_maximized().unwrap_or(false)
}

#[cfg(windows)]
fn is_webview_app_maximized<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) -> bool {
    window_bounds()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .is_some()
        || window.is_maximized().unwrap_or(false)
}

#[cfg(windows)]
fn client_origin(hwnd: HWND) -> Option<POINT> {
    let mut point = POINT { x: 0, y: 0 };
    unsafe { ClientToScreen(hwnd, &mut point).as_bool() }.then_some(point)
}

#[cfg(windows)]
fn set_outer_bounds(hwnd: HWND, position: PhysicalPosition<i32>, size: PhysicalSize<u32>) {
    let _ = unsafe {
        SetWindowPos(
            hwnd,
            None,
            position.x,
            position.y,
            size.width.min(i32::MAX as u32) as i32,
            size.height.min(i32::MAX as u32) as i32,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
    };
}

#[cfg(windows)]
fn restore_saved_bounds<R: tauri::Runtime>(window: &tauri::Window<R>, bounds: SavedWindowBounds) {
    if let Ok(hwnd) = window.hwnd() {
        set_outer_bounds(hwnd, bounds.position, bounds.size);
    } else {
        let _ = window.set_position(bounds.position);
        let _ = window.set_size(bounds.size);
    }
}

#[cfg(windows)]
fn maximize_to_work_area<R: tauri::Runtime>(window: &tauri::Window<R>) -> bool {
    let Some(monitor) = window.current_monitor().ok().flatten() else {
        let _ = window.maximize();
        return window.is_maximized().unwrap_or(false);
    };

    let work_area = *monitor.work_area();
    let Ok(hwnd) = window.hwnd() else {
        let _ = window.set_position(work_area.position);
        let _ = window.set_size(work_area.size);
        return true;
    };

    let Some(client_origin) = client_origin(hwnd) else {
        let _ = window.set_position(work_area.position);
        let _ = window.set_size(work_area.size);
        return true;
    };

    let outer_position = window
        .outer_position()
        .unwrap_or(PhysicalPosition::new(client_origin.x, client_origin.y));
    let outer_size = window.outer_size().unwrap_or(work_area.size);
    let inner_size = window.inner_size().unwrap_or(work_area.size);
    let client_offset_x = client_origin.x - outer_position.x;
    let client_offset_y = client_origin.y - outer_position.y;
    let frame_width = outer_size.width.saturating_sub(inner_size.width);
    let frame_height = outer_size.height.saturating_sub(inner_size.height);

    let target_position = PhysicalPosition::new(
        work_area.position.x - client_offset_x,
        work_area.position.y - client_offset_y,
    );
    let target_size = PhysicalSize::new(
        work_area.size.width.saturating_add(frame_width),
        work_area.size.height.saturating_add(frame_height),
    );

    set_outer_bounds(hwnd, target_position, target_size);
    true
}

#[cfg(windows)]
fn toggle_window_maximized<R: tauri::Runtime>(window: &tauri::Window<R>) -> bool {
    let mut guard = window_bounds()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());

    if let Some(bounds) = guard.take() {
        drop(guard);
        restore_saved_bounds(window, bounds);
        return false;
    }

    let bounds = match (window.outer_position(), window.outer_size()) {
        (Ok(position), Ok(size)) => SavedWindowBounds { position, size },
        _ => {
            let _ = window.maximize();
            return window.is_maximized().unwrap_or(false);
        }
    };

    *guard = Some(bounds);
    drop(guard);
    maximize_to_work_area(window)
}

#[cfg(not(windows))]
fn update_window_region<R: tauri::Runtime>(_window: &tauri::Window<R>) {}

#[cfg(not(windows))]
fn update_webview_window_region<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) {}

#[cfg(not(windows))]
fn is_app_maximized<R: tauri::Runtime>(window: &tauri::Window<R>) -> bool {
    window.is_maximized().unwrap_or(false)
}

#[cfg(not(windows))]
fn toggle_window_maximized<R: tauri::Runtime>(window: &tauri::Window<R>) -> bool {
    let maximized = window.is_maximized().unwrap_or(false);
    if maximized {
        let _ = window.unmaximize();
        false
    } else {
        let _ = window.maximize();
        true
    }
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, TRAY_SHOW_ID, "显示", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, TRAY_HIDE_ID, "隐藏", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let exit = MenuItem::with_id(app, TRAY_EXIT_ID, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &hide, &separator, &exit])?;

    let mut tray = TrayIconBuilder::with_id("main")
        .tooltip("koi")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            TRAY_SHOW_ID => show_main_window(app),
            TRAY_HIDE_ID => hide_main_window(app),
            TRAY_EXIT_ID => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::DoubleClick {
                button: MouseButton::Left,
                ..
            } = event
            {
                toggle_main_window(tray.app_handle());
            }
        });

    if let Some(icon) = app.default_window_icon().cloned() {
        tray = tray.icon(icon);
    }

    tray.build(app)?;
    Ok(())
}

fn run_self_test_from_args() -> Option<i32> {
    let mut requested = false;
    let mut data_dir: Option<PathBuf> = None;
    let mut arguments = std::env::args_os().skip(1);

    while let Some(argument) = arguments.next() {
        if argument == "--self-test" {
            requested = true;
        } else if argument == "--data-dir" {
            let Some(value) = arguments.next() else {
                eprintln!("--data-dir requires an absolute empty directory");
                return Some(2);
            };
            if data_dir.replace(PathBuf::from(value)).is_some() {
                eprintln!("--data-dir may only be specified once");
                return Some(2);
            }
        } else if requested {
            eprintln!(
                "unsupported self-test argument: {}",
                argument.to_string_lossy()
            );
            return Some(2);
        }
    }

    if !requested {
        return None;
    }
    let Some(data_dir) = data_dir else {
        eprintln!("--self-test requires --data-dir <absolute-empty-directory>");
        return Some(2);
    };
    if !data_dir.is_absolute() {
        eprintln!("--data-dir must be an absolute isolated directory");
        return Some(2);
    }
    match fs::read_dir(&data_dir) {
        Ok(mut entries) => {
            if entries.next().is_some() {
                eprintln!("--data-dir must be empty so self-test cannot touch user data");
                return Some(2);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            eprintln!("cannot inspect --data-dir: {error}");
            return Some(2);
        }
    }

    match backend::self_test::run(&data_dir, env!("CARGO_PKG_VERSION")) {
        Ok(report) => match serde_json::to_string(&report) {
            Ok(report) => {
                println!("{report}");
                Some(0)
            }
            Err(error) => {
                eprintln!("failed to serialize self-test report: {error}");
                Some(1)
            }
        },
        Err(error) => {
            eprintln!("self-test failed: {error}");
            Some(1)
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if let Some(exit_code) = backend::run_internal_worker_from_args() {
        std::process::exit(exit_code);
    }
    if let Some(exit_code) = run_self_test_from_args() {
        std::process::exit(exit_code);
    }
    tauri::Builder::default()
        .setup(|app| {
            setup_tray(app)?;
            #[cfg(windows)]
            {
                let user_data_dir = app_user_data_dir().ok_or_else(|| {
                    std::io::Error::other("unable to resolve enterprise WebView2 profile directory")
                })?;
                let boundary = Arc::new(TauriEnterpriseLoginBoundary::new(
                    app.handle().clone(),
                    user_data_dir
                        .join(".koi-runtime")
                        .join("enterprise-webview2"),
                ));
                backend::enterprise_queries::install_production_login_boundary(boundary)
                    .map_err(std::io::Error::other)?;
            }
            if let Some(webview_window) = app.get_webview_window("main") {
                let _ = webview_window.set_shadow(false);
                update_webview_window_region(&webview_window);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                WindowEvent::Resized(_) | WindowEvent::ScaleFactorChanged { .. } => {
                    update_window_region(window);
                }
                _ => {}
            }

            if let WindowEvent::CloseRequested { api, .. } = event {
                if close_to_tray_enabled() {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            call_backend,
            signal_retest_stop,
            sync_window_region,
            toggle_app_maximize,
            initialize_runtime
        ])
        .run(tauri::generate_context!())
        .expect("failed to run koi tauri application");
}
