use super::secret_store::{contains_plaintext_secrets, SecretStore};
use serde_json::{json, Map, Value};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
#[cfg(windows)]
use std::os::windows::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const CONFIG_LOCK_TIMEOUT: Duration = Duration::from_secs(10);
const CONFIG_LOCK_STALE_AFTER: Duration = Duration::from_secs(120);
const MAX_CONFIG_BYTES: u64 = 4 * 1024 * 1024;

pub struct ConfigStore {
    path: PathBuf,
    access: Mutex<()>,
}

impl ConfigStore {
    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            access: Mutex::new(()),
        }
    }

    pub fn load(&self) -> Result<Value, String> {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _file_lock = ConfigFileLock::acquire(&self.path, CONFIG_LOCK_TIMEOUT)?;
        self.load_unlocked()
    }

    /// Read configuration for an IPC response without exposing persisted
    /// credentials.  Callers that need a credential for an outbound request
    /// must use an internal transaction instead of this public projection.
    pub fn load_public(&self) -> Result<Value, String> {
        let mut config = self.load()?;
        redact_secrets(&mut config);
        Ok(config)
    }

    pub fn set_dark_mode(&self, dark_mode: bool) -> Result<Value, String> {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _file_lock = ConfigFileLock::acquire(&self.path, CONFIG_LOCK_TIMEOUT)?;
        let mut config = self.load_unlocked()?;
        set_object_field(&mut config, "ui_settings", "dark_mode", dark_mode)?;
        set_object_field(&mut config, "ui", "dark_mode", dark_mode)?;
        self.save_unlocked(&config)?;
        Ok(json!({"dark_mode": dark_mode}))
    }

    pub fn transact<F>(&self, operation: F) -> Result<Value, String>
    where
        F: FnOnce(&mut Value) -> Result<(Value, bool), String>,
    {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _file_lock = ConfigFileLock::acquire(&self.path, CONFIG_LOCK_TIMEOUT)?;
        let mut config = self.load_unlocked()?;
        let (response, changed) = operation(&mut config)?;
        if changed {
            self.save_unlocked(&config)?;
        }
        Ok(response)
    }

    fn load_unlocked(&self) -> Result<Value, String> {
        match fs::symlink_metadata(&self.path) {
            Ok(metadata) => {
                validate_config_metadata(&self.path, &metadata)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let config = default_config();
                self.save_unlocked(&config)?;
                return Ok(config);
            }
            Err(error) => {
                return Err(format!("读取配置文件失败 {}: {error}", self.path.display()));
            }
        }

        let raw = fs::read(&self.path)
            .map_err(|error| format!("读取配置文件失败 {}: {error}", self.path.display()))?;
        if raw.len() as u64 > MAX_CONFIG_BYTES {
            return Err(format!(
                "配置文件超过 {} 字节限制: {}",
                MAX_CONFIG_BYTES,
                self.path.display()
            ));
        }
        // Keep the legacy UTF-8 BOM compatibility accepted by the startup
        // initializer while still rejecting every other malformed payload.
        let json_bytes = raw.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&raw);
        let user_config = match serde_json::from_slice::<Value>(json_bytes) {
            Ok(Value::Object(values)) => Value::Object(values),
            Ok(_) => {
                return Err(format!("配置根节点必须是对象: {}", self.path.display()));
            }
            Err(error) => {
                return Err(format!(
                    "配置文件不是有效 JSON {}: {error}",
                    self.path.display()
                ));
            }
        };
        let plaintext_migration = contains_plaintext_secrets(&user_config);

        let mut merged = default_config();
        merge_json(&mut merged, user_config);
        SecretStore::load(&self.path)?.hydrate(&mut merged)?;
        let removed_version = merged
            .get_mut("app")
            .and_then(Value::as_object_mut)
            .and_then(|app| app.remove("version"))
            .is_some();
        if removed_version || plaintext_migration {
            self.save_unlocked(&merged)?;
        }
        Ok(merged)
    }

    fn save_unlocked(&self, config: &Value) -> Result<(), String> {
        if let Ok(metadata) = fs::symlink_metadata(&self.path) {
            validate_config_metadata(&self.path, &metadata)?;
        }
        let parent = self
            .path
            .parent()
            .ok_or_else(|| "配置文件路径缺少父目录".to_string())?;
        fs::create_dir_all(parent).map_err(|error| format!("创建配置目录失败: {error}"))?;

        let mut persisted = config.clone();
        let mut secrets = SecretStore::load(&self.path)?;
        secrets.externalize(&mut persisted)?;
        // The encrypted store is committed before plaintext is removed from
        // config.json. A failure therefore leaves the old configuration intact.
        secrets.save()?;
        let serialized = serde_json::to_vec_pretty(&persisted)
            .map_err(|error| format!("配置序列化失败: {error}"))?;
        let (temp_path, mut temp_file) = create_temp_file(&self.path)?;
        let write_result = (|| -> Result<(), String> {
            temp_file
                .write_all(&serialized)
                .map_err(|error| format!("写入临时配置失败: {error}"))?;
            temp_file
                .flush()
                .map_err(|error| format!("刷新临时配置失败: {error}"))?;
            temp_file
                .sync_all()
                .map_err(|error| format!("同步临时配置失败: {error}"))?;
            drop(temp_file);
            atomic_replace(&temp_path, &self.path)?;
            sync_parent_directory(parent)?;
            Ok(())
        })();

        if write_result.is_err() {
            let _ = fs::remove_file(&temp_path);
        }
        write_result
    }
}

fn validate_config_metadata(path: &Path, metadata: &fs::Metadata) -> Result<(), String> {
    if !metadata.is_file() || is_reparse_metadata(metadata) {
        return Err(format!(
            "配置文件必须是普通非重解析文件: {}",
            path.display()
        ));
    }
    if metadata.len() > MAX_CONFIG_BYTES {
        return Err(format!(
            "配置文件超过 {} 字节限制: {}",
            MAX_CONFIG_BYTES,
            path.display()
        ));
    }
    Ok(())
}

fn is_reparse_metadata(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_type().is_symlink() || metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

/// A small lock-file protocol keeps separate Koi processes from interleaving a
/// config read-modify-write cycle. The lock is deliberately adjacent to the
/// config so portable and installed data directories remain self-contained.
#[derive(Debug)]
struct ConfigFileLock {
    path: PathBuf,
    file: Option<File>,
}

impl ConfigFileLock {
    fn acquire(config_path: &Path, timeout: Duration) -> Result<Self, String> {
        let lock_path = config_path.with_file_name(format!(
            ".{}.lock",
            config_path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("config.json")
        ));
        let parent = lock_path
            .parent()
            .ok_or_else(|| "config lock path is missing a parent directory".to_string())?;
        validate_existing_directory_ancestors(parent)?;
        fs::create_dir_all(parent)
            .map_err(|error| format!("failed to create config lock directory: {error}"))?;
        validate_directory_chain(parent)?;

        let deadline = Instant::now() + timeout;
        loop {
            if let Ok(metadata) = fs::symlink_metadata(&lock_path) {
                if !metadata.is_file() || is_reparse_metadata(&metadata) {
                    return Err(format!(
                        "config lock must be a regular non-reparse file: {}",
                        lock_path.display()
                    ));
                }
            }
            let mut options = OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(windows)]
            options.share_mode(0);
            match options.open(&lock_path) {
                Ok(mut file) => {
                    let marker = format!("pid={}\n", std::process::id());
                    if let Err(error) = file
                        .write_all(marker.as_bytes())
                        .and_then(|_| file.sync_all())
                    {
                        drop(file);
                        let _ = fs::remove_file(&lock_path);
                        return Err(format!("failed to initialize config lock: {error}"));
                    }
                    return Ok(Self {
                        path: lock_path,
                        file: Some(file),
                    });
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    remove_stale_lock(&lock_path)?;
                    if Instant::now() >= deadline {
                        return Err(
                            "config is locked by another Koi process; retry shortly".to_string()
                        );
                    }
                    std::thread::sleep(Duration::from_millis(25));
                }
                Err(error) => return Err(format!("failed to acquire config lock: {error}")),
            }
        }
    }
}

impl Drop for ConfigFileLock {
    fn drop(&mut self) {
        self.file.take();
        let _ = fs::remove_file(&self.path);
    }
}

fn remove_stale_lock(lock_path: &Path) -> Result<(), String> {
    let metadata = match fs::symlink_metadata(lock_path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(format!("failed to inspect config lock: {error}")),
    };
    if !metadata.is_file() || is_reparse_metadata(&metadata) {
        return Err(format!(
            "config lock must be a regular non-reparse file: {}",
            lock_path.display()
        ));
    }
    let Ok(modified) = metadata.modified() else {
        return Ok(());
    };
    let Ok(age) = SystemTime::now().duration_since(modified) else {
        return Ok(());
    };
    if age > CONFIG_LOCK_STALE_AFTER {
        match fs::remove_file(lock_path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(format!("failed to remove stale config lock: {error}")),
        }
    } else {
        Ok(())
    }
}

fn validate_existing_directory_ancestors(path: &Path) -> Result<(), String> {
    let mut current = path.to_path_buf();
    loop {
        match fs::symlink_metadata(&current) {
            Ok(metadata) => {
                if !metadata.is_dir() || is_reparse_metadata(&metadata) {
                    return Err(format!(
                        "config directory must be a regular non-reparse directory: {}",
                        current.display()
                    ));
                }
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                if !current.pop() {
                    break;
                }
            }
            Err(error) => {
                return Err(format!(
                    "failed to inspect config directory {}: {error}",
                    current.display()
                ));
            }
        }
    }
    Ok(())
}

fn validate_directory_chain(path: &Path) -> Result<(), String> {
    let mut current = PathBuf::new();
    for component in path.components() {
        current.push(component.as_os_str());
        let metadata = fs::symlink_metadata(&current).map_err(|error| {
            format!(
                "failed to inspect config directory {}: {error}",
                current.display()
            )
        })?;
        if !metadata.is_dir() || is_reparse_metadata(&metadata) {
            return Err(format!(
                "config directory must be a regular non-reparse directory: {}",
                current.display()
            ));
        }
    }
    Ok(())
}

fn set_object_field(
    config: &mut Value,
    section: &str,
    field: &str,
    value: bool,
) -> Result<(), String> {
    let root = config
        .as_object_mut()
        .ok_or_else(|| "配置根节点必须是对象".to_string())?;
    let section_value = root
        .entry(section.to_string())
        .or_insert_with(|| Value::Object(Map::new()));
    let section_object = section_value
        .as_object_mut()
        .ok_or_else(|| format!("配置字段 {section} 必须是对象"))?;
    section_object.insert(field.to_string(), Value::Bool(value));
    Ok(())
}

fn merge_json(base: &mut Value, overlay: Value) {
    match (base, overlay) {
        (Value::Object(base), Value::Object(overlay)) => {
            for (key, value) in overlay {
                if let Some(existing) = base.get_mut(&key) {
                    merge_json(existing, value);
                } else {
                    base.insert(key, value);
                }
            }
        }
        (base, overlay) => *base = overlay,
    }
}

fn redact_secrets(value: &mut Value) {
    let Value::Object(values) = value else {
        if let Value::Array(items) = value {
            for item in items {
                redact_secrets(item);
            }
        }
        return;
    };

    let secret_fields: Vec<String> = values
        .keys()
        .filter(|key| is_secret_field(key))
        .cloned()
        .collect();
    for field in secret_fields {
        let secret = values
            .get(&field)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        values.insert(field.clone(), Value::String(String::new()));
        values.insert(
            format!("{field}_configured"),
            Value::Bool(!secret.is_empty()),
        );
        values.insert(
            format!("{field}_masked"),
            Value::String(mask_secret(&secret)),
        );
    }
    for child in values.values_mut() {
        redact_secrets(child);
    }
}

fn is_secret_field(field: &str) -> bool {
    let normalized = field
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect::<String>();
    [
        "apikey",
        "xapikey",
        "cookie",
        "setcookie",
        "xunkebaocookie",
        "threatbookapikey",
        "authorization",
        "xauthtoken",
        "xaccesstoken",
        "xrefreshtoken",
        "xsessiontoken",
        "password",
        "passwd",
        "token",
        "sessiontoken",
        "accesstoken",
        "refreshtoken",
        "secret",
        "clientsecret",
        "privatekey",
    ]
    .iter()
    .any(|marker| normalized == *marker)
}

fn mask_secret(secret: &str) -> String {
    let suffix: String = secret
        .chars()
        .rev()
        .take(4)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    if suffix.is_empty() {
        String::new()
    } else {
        format!("****{suffix}")
    }
}

fn default_config() -> Value {
    json!({
        "hunter": {"api_key": "", "last_updated": ""},
        "quake": {"api_key": "", "last_updated": ""},
        "fofa": {"email": "", "api_key": "", "last_updated": ""},
        "aiqicha": {"cookie": "", "xunkebao_cookie": "", "last_updated": ""},
        "tyc": {"cookie": "", "last_updated": ""},
        "ui": {
            "theme": "default",
            "window_size": {"width": 1400, "height": 900},
            "window_position": {"x": -1, "y": -1},
            "dark_mode": false,
            "last_updated": ""
        },
        "ui_settings": {
            "dark_mode": false,
            "close_to_tray": false,
            "last_updated": ""
        },
        "app": {"first_run": true, "last_updated": ""},
        "report_counters": {
            "notification_number": 1,
            "rectification_number": 1,
            "unavailable_notification_numbers": [],
            "unavailable_rectification_numbers": [],
            "year": current_year(),
            "last_updated": ""
        },
        "weekly_report": {
            "vulnerability_notice_dir": "",
            "event_notice_dir": "",
            "exclude_monday_next_notice": false,
            "last_updated": ""
        },
        "debug": {
            "tianyancha_debug_output": false,
            "tianyancha_console_log": false,
            "last_updated": ""
        },
        "retest_ai_agent": {
            "enabled": false,
            "active_profile_id": "default",
            "profiles": [
                {
                    "id": "default",
                    "name": "默认 OpenAI",
                    "provider": "openai",
                    "base_url": "",
                    "api_key": "",
                    "model": "",
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "last_updated": ""
                },
                {
                    "id": "openrouter-free",
                    "name": "OpenRouter 免费路由",
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "",
                    "model": "openrouter/free",
                    "temperature": 0.1,
                    "max_tokens": 1600,
                    "context_window": 128000,
                    "last_updated": ""
                }
            ],
            "last_updated": ""
        },
        "threatbook_api_key": ""
    })
}

fn current_year() -> i32 {
    let days = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() / 86_400)
        .unwrap_or(0) as i64;
    let shifted = days + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_parameter = (5 * day_of_year + 2) / 153;
    let month = month_parameter + if month_parameter < 10 { 3 } else { -9 };
    (year_of_era + era * 400 + i64::from(month <= 2)) as i32
}

fn create_temp_file(destination: &Path) -> Result<(PathBuf, File), String> {
    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("config.json");

    for _ in 0..32 {
        let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let candidate =
            destination.with_file_name(format!(".{file_name}.tmp-{}-{unique}", std::process::id()));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => return Ok((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("创建临时配置失败: {error}")),
        }
    }
    Err("创建临时配置失败: 临时文件名冲突".to_string())
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        MoveFileExW(
            PCWSTR(source_wide.as_ptr()),
            PCWSTR(destination_wide.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("原子替换配置失败: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("原子替换配置失败: {error}"))
}

#[cfg(unix)]
fn sync_parent_directory(parent: &Path) -> Result<(), String> {
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| format!("同步配置目录失败: {error}"))
}

#[cfg(not(unix))]
fn sync_parent_directory(_parent: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn current_year_is_plausible() {
        assert!((2024..=2200).contains(&current_year()));
    }

    #[test]
    fn recursive_merge_keeps_unknown_nested_fields() {
        let mut base = json!({"known": {"value": 1}});
        merge_json(&mut base, json!({"known": {"other": 2}, "unknown": true}));
        assert_eq!(
            base,
            json!({"known": {"value": 1, "other": 2}, "unknown": true})
        );
    }

    #[test]
    fn public_projection_redacts_nested_credentials() {
        let mut config = json!({
            "fofa": {"api_key": "fofa-secret-1234"},
            "retest_ai_agent": {"profiles": [{"api_key": "ai-secret-5678"}]},
            "tyc": {"cookie": "cookie-9012"},
            "safe": "visible"
        });
        redact_secrets(&mut config);
        let serialized = config.to_string();
        assert!(!serialized.contains("fofa-secret-1234"));
        assert!(!serialized.contains("ai-secret-5678"));
        assert!(!serialized.contains("cookie-9012"));
        assert_eq!(config["fofa"]["api_key"], "");
        assert_eq!(config["fofa"]["api_key_configured"], true);
        assert_eq!(
            config["retest_ai_agent"]["profiles"][0]["api_key_masked"],
            "****5678"
        );
        assert_eq!(config["safe"], "visible");
    }

    #[test]
    fn public_projection_redacts_legacy_secret_key_spellings() {
        let mut config = json!({
            "apiKey": "legacy-api-secret",
            "session_token": "legacy-session-secret",
            "authorization": "Bearer legacy-auth-secret",
            "token_count": 3,
            "safe": "visible",
        });
        redact_secrets(&mut config);
        let serialized = config.to_string();
        for secret in [
            "legacy-api-secret",
            "legacy-session-secret",
            "legacy-auth-secret",
        ] {
            assert!(!serialized.contains(secret), "projection leaked {secret}");
        }
        assert_eq!(config["apiKey"], "");
        assert_eq!(config["session_token"], "");
        assert_eq!(config["authorization"], "");
        assert_eq!(config["token_count"], 3);
    }

    #[test]
    fn file_lock_rejects_a_second_writer_until_released() {
        let directory = std::env::temp_dir().join(format!(
            "koi-config-lock-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let path = directory.join("config.json");
        let first = ConfigFileLock::acquire(&path, Duration::ZERO).expect("acquire first lock");
        let error = ConfigFileLock::acquire(&path, Duration::ZERO)
            .expect_err("second lock must not enter the transaction");
        assert!(error.contains("locked"));
        drop(first);
        ConfigFileLock::acquire(&path, Duration::ZERO).expect("released lock can be acquired");
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn malformed_config_fails_closed_and_preserves_original_bytes() {
        let directory = std::env::temp_dir().join(format!(
            "koi-config-malformed-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&directory).expect("create malformed config directory");
        let path = directory.join("config.json");
        let original = br#"{"broken": "unterminated}"#;
        fs::write(&path, original).expect("write malformed config");

        let store = ConfigStore::new(path.clone());
        let error = store
            .load()
            .expect_err("malformed config must abort loading");
        assert!(error.contains("不是有效 JSON"));
        assert_eq!(fs::read(&path).expect("read original config"), original);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn non_object_config_fails_closed_and_is_not_replaced() {
        let directory = std::env::temp_dir().join(format!(
            "koi-config-root-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&directory).expect("create root config directory");
        let path = directory.join("config.json");
        let original = br#"[]"#;
        fs::write(&path, original).expect("write array config");

        let store = ConfigStore::new(path.clone());
        let error = store
            .load()
            .expect_err("non-object config must abort loading");
        assert!(error.contains("根节点必须是对象"));
        assert_eq!(fs::read(&path).expect("read original config"), original);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn utf8_bom_config_remains_compatible() {
        let directory = std::env::temp_dir().join(format!(
            "koi-config-bom-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&directory).expect("create BOM config directory");
        let path = directory.join("config.json");
        fs::write(&path, b"\xEF\xBB\xBF{\"ui\":{\"dark_mode\":true}}").expect("write BOM config");

        let store = ConfigStore::new(path);
        let loaded = store.load().expect("BOM config should load");
        assert_eq!(loaded["ui"]["dark_mode"], true);
        let _ = fs::remove_dir_all(directory);
    }

    #[cfg(windows)]
    #[test]
    fn plaintext_credentials_migrate_to_dpapi_store() {
        let directory = std::env::temp_dir().join(format!(
            "koi-config-dpapi-test-{}-{}",
            std::process::id(),
            NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&directory).expect("create DPAPI test directory");
        let path = directory.join("config.json");
        fs::write(
            &path,
            serde_json::to_vec_pretty(&json!({
                "fofa": {"email": "operator@example.test", "api_key": "migration-secret-1234"}
            }))
            .expect("serialize legacy config"),
        )
        .expect("write legacy config");

        let store = ConfigStore::new(path.clone());
        let internal = store.load().expect("migrate and load credentials");
        assert_eq!(internal["fofa"]["api_key"], "migration-secret-1234");

        let config_on_disk = fs::read_to_string(&path).expect("read migrated config");
        let secrets_on_disk =
            fs::read_to_string(directory.join("secrets.dpapi.json")).expect("read DPAPI store");
        assert!(!config_on_disk.contains("migration-secret-1234"));
        assert!(!secrets_on_disk.contains("migration-secret-1234"));
        assert_eq!(
            serde_json::from_str::<Value>(&config_on_disk).expect("parse migrated config")["fofa"]
                ["api_key"],
            ""
        );

        let public = store.load_public().expect("load redacted config");
        assert_eq!(public["fofa"]["api_key"], "");
        assert_eq!(public["fofa"]["api_key_configured"], true);
        assert_eq!(public["fofa"]["api_key_masked"], "****1234");
        let _ = fs::remove_dir_all(directory);
    }

    static NEXT_TEST_ID: AtomicU64 = AtomicU64::new(0);
}
