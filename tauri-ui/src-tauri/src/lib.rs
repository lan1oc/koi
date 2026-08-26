use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicU32, AtomicU64, Ordering},
    mpsc::{self, Receiver, RecvTimeoutError},
    Mutex, OnceLock,
};
use std::thread;
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, PhysicalPosition, PhysicalSize, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
use windows::Win32::Foundation::{HWND, POINT};
#[cfg(windows)]
use windows::Win32::Graphics::Gdi::{ClientToScreen, CreateRoundRectRgn, SetWindowRgn};
#[cfg(windows)]
use windows::Win32::UI::WindowsAndMessaging::{SetWindowPos, SWP_NOACTIVATE, SWP_NOZORDER};

const CREATE_NO_WINDOW: u32 = 0x08000000;
#[cfg(windows)]
const WINDOW_RADIUS_PX: i32 = 18;
const TRAY_SHOW_ID: &str = "tray-show";
const TRAY_HIDE_ID: &str = "tray-hide";
const TRAY_EXIT_ID: &str = "tray-exit";

static SIDECAR: OnceLock<Mutex<Option<SidecarProcess>>> = OnceLock::new();
static SIDECAR_PID: AtomicU32 = AtomicU32::new(0);
static SIDECAR_GENERATION: AtomicU64 = AtomicU64::new(0);
static WINDOW_BOUNDS: OnceLock<Mutex<Option<SavedWindowBounds>>> = OnceLock::new();

#[derive(Clone, Copy)]
struct SavedWindowBounds {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
}

struct SidecarProcess {
    child: Child,
    stdout_rx: Receiver<String>,
}

fn sidecar() -> &'static Mutex<Option<SidecarProcess>> {
    SIDECAR.get_or_init(|| Mutex::new(None))
}

fn window_bounds() -> &'static Mutex<Option<SavedWindowBounds>> {
    WINDOW_BOUNDS.get_or_init(|| Mutex::new(None))
}

#[derive(Debug, Serialize, Deserialize)]
struct BackendRequest {
    command: String,
    payload: Value,
}

#[derive(Debug, Serialize, Deserialize)]
struct BackendResponse {
    ok: bool,
    data: Value,
    error: Option<String>,
}

enum BackendLauncher {
    Exe {
        root_dir: PathBuf,
        exe_path: PathBuf,
    },
    Python {
        root_dir: PathBuf,
        script_path: PathBuf,
    },
}

fn backend_launcher() -> Result<BackendLauncher, String> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.to_path_buf()));

    if let Some(dir) = exe_dir {
        let backend_dir_exe = dir.join("koi-backend").join("koi-backend.exe");
        if backend_dir_exe.exists() {
            return Ok(BackendLauncher::Exe {
                root_dir: dir,
                exe_path: backend_dir_exe,
            });
        }
        let backend_exe = dir.join("koi-backend.exe");
        if backend_exe.exists() {
            return Ok(BackendLauncher::Exe {
                root_dir: dir,
                exe_path: backend_exe,
            });
        }
        let backend_script = dir.join("modules").join("backend_api").join("main.py");
        if backend_script.exists() {
            return Ok(BackendLauncher::Python {
                root_dir: dir,
                script_path: backend_script,
            });
        }
    }

    let mut dir = std::env::current_dir().map_err(|error| error.to_string())?;
    if dir.file_name().and_then(|name| name.to_str()) == Some("src-tauri") {
        dir.pop();
    }
    if dir.file_name().and_then(|name| name.to_str()) == Some("tauri-ui") {
        dir.pop();
    }

    let backend_dir_exe = dir.join("koi-backend").join("koi-backend.exe");
    if backend_dir_exe.exists() {
        return Ok(BackendLauncher::Exe {
            root_dir: dir,
            exe_path: backend_dir_exe,
        });
    }

    let backend_exe = dir.join("koi-backend.exe");
    if backend_exe.exists() {
        return Ok(BackendLauncher::Exe {
            root_dir: dir,
            exe_path: backend_exe,
        });
    }

    let backend_script = dir.join("modules").join("backend_api").join("main.py");
    if backend_script.exists() {
        return Ok(BackendLauncher::Python {
            root_dir: dir,
            script_path: backend_script,
        });
    }

    Err("无法定位 Python 后端入口 koi-backend.exe 或 modules/backend_api/main.py".to_string())
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

fn user_data_dir(root_dir: &Path) -> PathBuf {
    if cfg!(debug_assertions) {
        return root_dir.to_path_buf();
    }

    root_dir
        .parent()
        .map(|parent| parent.join("koi-data"))
        .unwrap_or_else(|| root_dir.join("koi-data"))
}

fn app_user_data_dir() -> Option<PathBuf> {
    let launcher = backend_launcher().ok()?;
    let root_dir = match launcher {
        BackendLauncher::Exe { root_dir, .. } | BackendLauncher::Python { root_dir, .. } => root_dir,
    };
    Some(user_data_dir(&root_dir))
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
    let mut candidates = Vec::new();

    if let Some(data_dir) = app_user_data_dir() {
        candidates.push(data_dir.join("config.json"));
    }

    if let Some(root_dir) = app_root_dir() {
        candidates.push(root_dir.join("config.json"));
        candidates.push(root_dir.join("koi-backend").join("config.json"));
    };

    if let Ok(launcher) = backend_launcher() {
        let root_dir = match launcher {
            BackendLauncher::Exe { root_dir, .. } | BackendLauncher::Python { root_dir, .. } => {
                root_dir
            }
        };
        candidates.push(root_dir.join("config.json"));
    }

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

fn spawn_sidecar() -> Result<SidecarProcess, String> {
    let launcher = backend_launcher()?;

    let (root_dir, mut command) = match launcher {
        BackendLauncher::Exe { root_dir, exe_path } => (root_dir, Command::new(exe_path)),
        BackendLauncher::Python {
            root_dir,
            script_path,
        } => {
            let mut command = Command::new("python");
            command.arg(script_path);
            (root_dir, command)
        }
    };

    command
        .current_dir(&root_dir)
        .env("KOI_APP_DIR", &root_dir)
        .env("KOI_APP_VERSION", env!("CARGO_PKG_VERSION"))
        .env("KOI_USER_DATA_DIR", user_data_dir(&root_dir))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command.spawn().map_err(|error| error.to_string())?;
    SIDECAR_PID.store(child.id(), Ordering::SeqCst);

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "后端进程无法读取 (stdout)".to_string())?;
    let (stdout_tx, stdout_rx) = mpsc::channel::<String>();
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => break,
                Ok(_) => {
                    if stdout_tx.send(line).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });

    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            let mut reader = BufReader::new(stderr);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => line.clear(),
                }
            }
        });
    }

    Ok(SidecarProcess { child, stdout_rx })
}

fn stop_sidecar(process: &mut SidecarProcess) {
    let child_id = process.child.id();
    let _ = process.child.kill();
    let _ = process.child.wait();
    let _ = SIDECAR_PID.compare_exchange(child_id, 0, Ordering::SeqCst, Ordering::SeqCst);
}

fn terminate_sidecar_outside_lock() -> Result<bool, String> {
    SIDECAR_GENERATION.fetch_add(1, Ordering::SeqCst);
    let pid = SIDECAR_PID.swap(0, Ordering::SeqCst);
    if pid == 0 {
        return Ok(false);
    }

    #[cfg(windows)]
    {
        let pid_text = pid.to_string();
        let mut command = Command::new("taskkill");
        command.args(["/PID", pid_text.as_str(), "/T", "/F"]);
        command.creation_flags(CREATE_NO_WINDOW);
        let status = command.status().map_err(|error| error.to_string())?;
        return Ok(status.success());
    }

    #[cfg(not(windows))]
    {
        let pid_text = pid.to_string();
        let status = Command::new("kill")
            .args(["-9", pid_text.as_str()])
            .status()
            .map_err(|error| error.to_string())?;
        Ok(status.success())
    }
}

fn response_timeout_for(command: &str) -> Duration {
    match command {
        // Hybrid messages include a model round-trip. The frontend can still
        // send an out-of-band stop marker while this request is pending.
        "doc.agent.message" => Duration::from_secs(5 * 60),
        "doc.retest.agent.message"
        | "doc.retest.agent.start"
        | "doc.retest.agent.status"
        | "doc.retest.agent.stop"
        | "doc.retest.agent.snapshot"
        | "doc.agent.status"
        | "doc.agent.stop"
        | "doc.agent.approval.respond"
        | "doc.agent.tools" => Duration::from_secs(30),
        _ => Duration::from_secs(15 * 60),
    }
}

/// Send one request line and read one response line from the sidecar child.
fn sidecar_roundtrip(
    process: &mut SidecarProcess,
    request_json: &str,
    timeout: Duration,
) -> Result<BackendResponse, String> {
    if let Ok(Some(status)) = process.child.try_wait() {
        return Err(format!("后端进程已退出: {status}"));
    }

    // Write request.
    {
        let stdin = process
            .child
            .stdin
            .as_mut()
            .ok_or("后端进程无法写入 (stdin)")?;
        writeln!(stdin, "{}", request_json).map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }

    // Read response.
    let started = Instant::now();
    loop {
        let Some(remaining) = timeout.checked_sub(started.elapsed()) else {
            return Err(format!("后端响应超时: {} 秒未返回", timeout.as_secs()));
        };
        let line = match process.stdout_rx.recv_timeout(remaining) {
            Ok(line) => line,
            Err(RecvTimeoutError::Timeout) => {
                return Err(format!("后端响应超时: {} 秒未返回", timeout.as_secs()));
            }
            Err(RecvTimeoutError::Disconnected) => return Err("后端响应通道已关闭".to_string()),
        };

        if line.trim().is_empty() {
            continue;
        }
        match serde_json::from_str::<BackendResponse>(&line) {
            Ok(response) => return Ok(response),
            Err(_) => continue,
        }
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
async fn reset_backend_sidecar() -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(terminate_sidecar_outside_lock)
        .await
        .map_err(|error| error.to_string())?
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

fn call_backend_sync(command: String, payload: Value) -> BackendResponse {
    let request_generation = SIDECAR_GENERATION.load(Ordering::SeqCst);
    let timeout = response_timeout_for(&command);
    let request = BackendRequest { command, payload };
    let request_json = match serde_json::to_string(&request) {
        Ok(value) => value,
        Err(error) => {
            return BackendResponse {
                ok: false,
                data: Value::Null,
                error: Some(error.to_string()),
            }
        }
    };

    let mut guard = sidecar()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());

    if SIDECAR_GENERATION.load(Ordering::SeqCst) != request_generation {
        return BackendResponse {
            ok: false,
            data: Value::Null,
            error: Some("后端请求已被新的恢复操作取消".to_string()),
        };
    }

    // Ensure sidecar is running.
    if guard.is_none() {
        match spawn_sidecar() {
            Ok(child) => {
                *guard = Some(child);
            }
            Err(error) => {
                return BackendResponse {
                    ok: false,
                    data: Value::Null,
                    error: Some(error),
                }
            }
        }
    }

    let process = guard.as_mut().expect("guard is Some after init");

    // Never replay a backend command transparently. Most commands mutate
    // files, Agent turns, or task state; replaying after a timeout can execute
    // the same work twice. Recreate only the transport for the next request.
    match sidecar_roundtrip(process, &request_json, timeout) {
        Ok(response) => response,
        Err(first_error) => {
            if SIDECAR_GENERATION.load(Ordering::SeqCst) != request_generation {
                if let Some(mut stale) = guard.take() {
                    stop_sidecar(&mut stale);
                }
                return BackendResponse {
                    ok: false,
                    data: Value::Null,
                    error: Some("后端请求已被新的恢复操作取消".to_string()),
                };
            }
            if let Some(mut stale) = guard.take() {
                stop_sidecar(&mut stale);
            }
            let recovery = match spawn_sidecar() {
                Ok(new_child) => {
                    *guard = Some(new_child);
                    "后端连接已重建；为避免重复执行，原请求未自动重放".to_string()
                }
                Err(restart_error) => format!("后端连接重建失败: {restart_error}"),
            };
            BackendResponse {
                ok: false,
                data: Value::Null,
                error: Some(format!("后端调用失败: {first_error}; {recovery}")),
            }
        }
    }
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            setup_tray(app)?;
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
            reset_backend_sidecar,
            signal_retest_stop,
            sync_window_region,
            toggle_app_maximize
        ])
        .run(tauri::generate_context!())
        .expect("failed to run koi tauri application");
}
