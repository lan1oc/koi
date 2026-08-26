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
        if !path.exists() {
            return Ok(Self {
                path,
                entries: BTreeMap::new(),
                dirty: true,
            });
        }

        let raw =
            fs::read(&path).map_err(|error| format!("failed to read DPAPI store: {error}"))?;
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
        let mut path = Vec::new();
        hydrate_value(config, &mut path, &self.entries)
    }

    pub(crate) fn externalize(&mut self, config: &mut Value) -> Result<(), String> {
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
                && child
                    .as_str()
                    .map(|secret| !secret.is_empty())
                    .unwrap_or(false))
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
                    let secret = child.as_str().unwrap_or_default().to_string();
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
    matches!(
        field,
        "api_key" | "cookie" | "xunkebao_cookie" | "threatbook_api_key"
    )
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
