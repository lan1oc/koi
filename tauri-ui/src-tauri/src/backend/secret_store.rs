use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine as _;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const SECRET_FILE_NAME: &str = "secrets.dpapi.json";
const SECRET_SCHEMA_VERSION: u32 = 1;
const MAX_SECRET_FILE_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Default, Serialize, Deserialize)]
struct SecretFile {
    schema_version: u32,
    #[serde(default)]
    entries: BTreeMap<String, String>,
}

pub(crate) struct SecretStore {
    path: PathBuf,
    entries: BTreeMap<String, String>,
    dirty: bool,
}

impl SecretStore {
    pub(crate) fn load(config_path: &Path) -> Result<Self, String> {
        let parent = config_path
            .parent()
            .ok_or_else(|| "config path has no parent directory".to_string())?;
        let path = parent.join(SECRET_FILE_NAME);
        match fs::symlink_metadata(&path) {
            Ok(metadata) => {
                validate_secret_metadata(&path, &metadata)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Self {
                    path,
                    entries: BTreeMap::new(),
                    dirty: true,
                });
            }
            Err(error) => {
                return Err(format!("failed to inspect DPAPI store: {error}"));
            }
        }

        let raw =
            fs::read(&path).map_err(|error| format!("failed to read DPAPI store: {error}"))?;
        if raw.len() as u64 > MAX_SECRET_FILE_BYTES {
            return Err(format!(
                "DPAPI store exceeds the {} byte limit",
                MAX_SECRET_FILE_BYTES
            ));
        }
        let file: SecretFile = serde_json::from_slice(&raw)
            .map_err(|error| format!("failed to parse DPAPI store: {error}"))?;
        if file.schema_version != SECRET_SCHEMA_VERSION {
            return Err(format!(
                "unsupported DPAPI store schema: {}",
                file.schema_version
            ));
        }
        Ok(Self {
            path,
            entries: file.entries,
            dirty: false,
        })
    }

    pub(crate) fn hydrate(&self, config: &mut Value) -> Result<(), String> {
        validate_secret_value_types(config, &mut Vec::new())?;
        let mut path = Vec::new();
        hydrate_value(config, &mut path, &self.entries)
    }

    pub(crate) fn externalize(&mut self, config: &mut Value) -> Result<(), String> {
        validate_secret_value_types(config, &mut Vec::new())?;
        let mut path = Vec::new();
        let mut visited = BTreeSet::new();
        externalize_value(
            config,
            &mut path,
            &mut self.entries,
            &mut visited,
            &mut self.dirty,
        )?;
        let before = self.entries.len();
        self.entries.retain(|key, _| visited.contains(key));
        self.dirty |= before != self.entries.len();
        Ok(())
    }

    pub(crate) fn save(&mut self) -> Result<(), String> {
        if !self.dirty && self.path.exists() {
            return Ok(());
        }
        let parent = self
            .path
            .parent()
            .ok_or_else(|| "DPAPI store path has no parent directory".to_string())?;
        fs::create_dir_all(parent)
            .map_err(|error| format!("failed to create DPAPI store directory: {error}"))?;
        let serialized = serde_json::to_vec_pretty(&SecretFile {
            schema_version: SECRET_SCHEMA_VERSION,
            entries: self.entries.clone(),
        })
        .map_err(|error| format!("failed to serialize DPAPI store: {error}"))?;
        atomic_write(&self.path, &serialized)?;
        self.dirty = false;
        Ok(())
    }
}

pub(crate) fn contains_plaintext_secrets(value: &Value) -> bool {
    match value {
        Value::Object(values) => values.iter().any(|(key, child)| {
            (is_secret_field(key)
                && match child {
                    Value::String(secret) => !secret.is_empty(),
                    Value::Null => false,
                    // A non-string secret is malformed input and must force
                    // the migration path to validate it rather than silently
                    // leaving it in the plaintext configuration.
                    _ => true,
                })
                || contains_plaintext_secrets(child)
        }),
        Value::Array(items) => items.iter().any(contains_plaintext_secrets),
        _ => false,
    }
}

fn hydrate_value(
    value: &mut Value,
    path: &mut Vec<String>,
    entries: &BTreeMap<String, String>,
) -> Result<(), String> {
    match value {
        Value::Object(values) => {
            for (key, child) in values {
                path.push(escape_component(key));
                if is_secret_field(key) {
                    let entry_key = store_key(path);
                    let is_blank = child.as_str().map(str::is_empty).unwrap_or(true);
                    if is_blank {
                        if let Some(ciphertext) = entries.get(&entry_key) {
                            *child = Value::String(unprotect(ciphertext)?);
                        }
                    }
                } else {
                    hydrate_value(child, path, entries)?;
                }
                path.pop();
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter_mut().enumerate() {
                path.push(array_component(child, index));
                hydrate_value(child, path, entries)?;
                path.pop();
            }
        }
        _ => {}
    }
    Ok(())
}

fn externalize_value(
    value: &mut Value,
    path: &mut Vec<String>,
    entries: &mut BTreeMap<String, String>,
    visited: &mut BTreeSet<String>,
    dirty: &mut bool,
) -> Result<(), String> {
    match value {
        Value::Object(values) => {
            for (key, child) in values {
                path.push(escape_component(key));
                if is_secret_field(key) {
                    let entry_key = store_key(path);
                    visited.insert(entry_key.clone());
                    let secret = match child {
                        Value::String(secret) => secret.clone(),
                        Value::Null => String::new(),
                        _ => {
                            return Err(format!(
                                "secret field {} must be a string or null",
                                store_key(path)
                            ));
                        }
                    };
                    if secret.is_empty() {
                        *dirty |= entries.remove(&entry_key).is_some();
                    } else {
                        let unchanged = entries
                            .get(&entry_key)
                            .map(|ciphertext| unprotect(ciphertext))
                            .transpose()?
                            .as_deref()
                            == Some(secret.as_str());
                        if !unchanged {
                            entries.insert(entry_key, protect(&secret)?);
                            *dirty = true;
                        }
                    }
                    *child = Value::String(String::new());
                } else {
                    externalize_value(child, path, entries, visited, dirty)?;
                }
                path.pop();
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter_mut().enumerate() {
                path.push(array_component(child, index));
                externalize_value(child, path, entries, visited, dirty)?;
                path.pop();
            }
        }
        _ => {}
    }
    Ok(())
}

fn is_secret_field(field: &str) -> bool {
    let normalized = field
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect::<String>();
    if normalized.starts_with("token")
        && ["count", "limit", "remaining", "index", "total"]
            .iter()
            .any(|suffix| normalized.ends_with(suffix))
    {
        return false;
    }
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

fn validate_secret_value_types(value: &Value, path: &mut Vec<String>) -> Result<(), String> {
    match value {
        Value::Object(values) => {
            for (key, child) in values {
                path.push(escape_component(key));
                if is_secret_field(key) && !matches!(child, Value::String(_) | Value::Null) {
                    return Err(format!(
                        "secret field {} must be a string or null",
                        store_key(path)
                    ));
                }
                validate_secret_value_types(child, path)?;
                path.pop();
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter().enumerate() {
                path.push(array_component(child, index));
                validate_secret_value_types(child, path)?;
                path.pop();
            }
        }
        _ => {}
    }
    Ok(())
}

fn array_component(value: &Value, index: usize) -> String {
    value
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .map(|id| format!("@id={}", escape_component(id)))
        .unwrap_or_else(|| index.to_string())
}

fn escape_component(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

fn store_key(path: &[String]) -> String {
    format!("/{}", path.join("/"))
}

#[cfg(windows)]
fn protect(secret: &str) -> Result<String, String> {
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{LocalFree, HLOCAL};
    use windows::Win32::Security::Cryptography::{
        CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let mut input = secret.as_bytes().to_vec();
    let input_blob = CRYPT_INTEGER_BLOB {
        cbData: input
            .len()
            .try_into()
            .map_err(|_| "secret is too large for DPAPI".to_string())?,
        pbData: input.as_mut_ptr(),
    };
    let mut output = CRYPT_INTEGER_BLOB::default();
    unsafe {
        CryptProtectData(
            &input_blob,
            PCWSTR::null(),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    }
    .map_err(|error| format!("DPAPI encryption failed: {error}"))?;
    if output.pbData.is_null() {
        return Err("DPAPI encryption returned no data".to_string());
    }
    let encrypted = unsafe {
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        let _ = LocalFree(Some(HLOCAL(output.pbData.cast())));
        bytes
    };
    Ok(BASE64.encode(encrypted))
}

#[cfg(windows)]
fn unprotect(ciphertext: &str) -> Result<String, String> {
    use windows::Win32::Foundation::{LocalFree, HLOCAL};
    use windows::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let mut encrypted = BASE64
        .decode(ciphertext)
        .map_err(|error| format!("invalid DPAPI ciphertext encoding: {error}"))?;
    let input_blob = CRYPT_INTEGER_BLOB {
        cbData: encrypted
            .len()
            .try_into()
            .map_err(|_| "DPAPI ciphertext is too large".to_string())?,
        pbData: encrypted.as_mut_ptr(),
    };
    let mut output = CRYPT_INTEGER_BLOB::default();
    unsafe {
        CryptUnprotectData(
            &input_blob,
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    }
    .map_err(|error| format!("DPAPI decryption failed: {error}"))?;
    if output.pbData.is_null() {
        return Err("DPAPI decryption returned no data".to_string());
    }
    let decrypted = unsafe {
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        let _ = LocalFree(Some(HLOCAL(output.pbData.cast())));
        bytes
    };
    String::from_utf8(decrypted).map_err(|_| "DPAPI secret is not valid UTF-8".to_string())
}

#[cfg(not(windows))]
fn protect(_secret: &str) -> Result<String, String> {
    Err("DPAPI secret storage is only available on Windows".to_string())
}

#[cfg(not(windows))]
fn unprotect(_ciphertext: &str) -> Result<String, String> {
    Err("DPAPI secret storage is only available on Windows".to_string())
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    let parent = path
        .parent()
        .ok_or_else(|| "DPAPI store path has no parent directory".to_string())?;
    if let Ok(metadata) = fs::symlink_metadata(path) {
        validate_secret_metadata(path, &metadata)?;
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or(SECRET_FILE_NAME);
    let temporary = parent.join(format!(
        ".{name}.tmp-{}-{}",
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    ));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| format!("failed to create temporary DPAPI store: {error}"))?;
        file.write_all(bytes)
            .and_then(|_| file.flush())
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("failed to write temporary DPAPI store: {error}"))?;
        drop(file);
        replace_file(&temporary, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn validate_secret_metadata(path: &Path, metadata: &fs::Metadata) -> Result<(), String> {
    if !metadata.is_file() || is_reparse_metadata(metadata) {
        return Err(format!(
            "DPAPI store must be a regular non-reparse file: {}",
            path.display()
        ));
    }
    if metadata.len() > MAX_SECRET_FILE_BYTES {
        return Err(format!(
            "DPAPI store exceeds the {} byte limit: {}",
            MAX_SECRET_FILE_BYTES,
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

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        MoveFileExW(
            PCWSTR(source.as_ptr()),
            PCWSTR(destination.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("failed to replace DPAPI store atomically: {error}"))
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn recognizes_legacy_secret_header_spellings_without_matching_counters() {
        for field in [
            "api_key",
            "X-API-Key",
            "Set-Cookie",
            "x-auth-token",
            "session_token",
            "private-key",
        ] {
            assert!(is_secret_field(field), "{field} should be secret");
        }
        for field in ["token_count", "token_limit", "total"] {
            assert!(!is_secret_field(field), "{field} is metadata, not a secret");
        }
    }

    #[test]
    fn rejects_non_string_secret_values_before_mutating_configuration() {
        let path = std::env::temp_dir().join("koi-secret-store-test-config.json");
        let mut store = SecretStore {
            path,
            entries: BTreeMap::new(),
            dirty: false,
        };
        let original = json!({"api_key": {"unexpected": true}, "safe": "value"});
        let mut value = original.clone();
        let error = store
            .externalize(&mut value)
            .expect_err("structured secret values must be rejected");
        assert!(error.contains("must be a string or null"));
        assert_eq!(value, original);
        assert!(contains_plaintext_secrets(&original));
    }
}
