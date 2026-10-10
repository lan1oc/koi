//! Checkpoints belong to application data; the selected notice tree contains user artifacts.
use super::*;
use std::cell::RefCell;

thread_local! {
    static STORAGE: RefCell<Option<PathBuf>> = const { RefCell::new(None) };
}

pub(super) struct NoticeStateStorageGuard(Option<Option<PathBuf>>);
impl NoticeStateStorageGuard {
    pub(super) fn enter(directory: Option<&Path>) -> Self {
        Self(
            directory
                .map(|directory| STORAGE.with(|slot| slot.replace(Some(directory.to_path_buf())))),
        )
    }
}
impl Drop for NoticeStateStorageGuard {
    fn drop(&mut self) {
        if let Some(previous) = self.0.take() {
            STORAGE.with(|slot| slot.replace(previous));
        }
    }
}

pub(super) fn state_path(root: &Path) -> PathBuf {
    STORAGE.with(|slot| match slot.borrow().as_ref() {
        Some(directory) => {
            let key = root.to_string_lossy().replace('\\', "/");
            let key = key.trim_start_matches("//?/").trim_end_matches('/');
            #[cfg(windows)]
            let key = key.to_lowercase();
            directory.join(format!("{:x}.json", Sha256::digest(key.as_bytes())))
        }
        None => root.join(NOTICE_STATE_FILE),
    })
}

pub(super) fn is_checkpoint(path: &Path) -> bool {
    if path.file_name().and_then(|name| name.to_str()) == Some(NOTICE_STATE_FILE) {
        return true;
    }
    STORAGE.with(|slot| {
        slot.borrow().as_ref().is_some_and(|directory| {
            path.parent() == Some(directory.as_path())
                && path
                    .file_stem()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| {
                        name.len() == 64
                            && name.chars().all(|character| character.is_ascii_hexdigit())
                    })
                && path.extension().and_then(|extension| extension.to_str()) == Some("json")
        })
    })
}

pub(super) fn state_directories(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut directories = Vec::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        if state_path(&directory).is_file() || directory.join(NOTICE_STATE_FILE).is_file() {
            directories.push(directory.clone());
        }
        for entry in
            fs::read_dir(&directory).map_err(|error| format!("无法读取通报断点目录: {error}"))?
        {
            let path = entry.map_err(|error| error.to_string())?.path();
            let metadata = fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
            if metadata.is_dir() && !notice_path_is_reparse(&metadata) {
                pending.push(path);
            }
        }
    }
    directories.sort();
    Ok(directories)
}

pub(super) fn cleanup_path_allowed(root: &Path, path: &Path) -> Result<(), String> {
    if path_under(root, path).is_ok() {
        return Ok(());
    }
    if is_checkpoint(path) {
        let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
        if metadata.is_file() && !notice_path_is_reparse(&metadata) {
            let bytes = fs::read(path).map_err(|error| error.to_string())?;
            let state: NoticeState = serde_json::from_slice(&bytes)
                .map_err(|error| format!("通报断点文件损坏: {error}"))?;
            if let Ok(directory) = path_under(root, Path::new(&state.target_path)) {
                if state_path(&directory) == path {
                    return Ok(());
                }
            }
        }
    }
    Err("清理文件不属于所选通报目录".into())
}

pub(super) fn rename_entry(source: &Path, destination: &Path) -> Result<(), String> {
    let internal = STORAGE.with(|slot| slot.borrow().is_some());
    let states = if internal && source.is_dir() {
        state_directories(source)?
            .into_iter()
            .map(|directory| {
                let relative = directory
                    .strip_prefix(source)
                    .map_err(|error| error.to_string())?
                    .to_path_buf();
                Ok((
                    state_path(&directory),
                    destination.join(relative),
                    load_notice_state(&directory)?,
                ))
            })
            .collect::<Result<Vec<_>, String>>()?
    } else {
        Vec::new()
    };
    let mut prepared = Vec::new();
    for (_, directory, state) in &states {
        if let Some(state) = state {
            let mut relocated = state.clone();
            rebase_notice_state(directory, &mut relocated);
            save_notice_state(directory, &relocated)?;
            prepared.push(state_path(directory));
        }
    }
    if let Err(error) = fs::rename(source, destination) {
        for path in prepared {
            let _ = fs::remove_file(path);
        }
        return Err(error.to_string());
    }
    for (old_path, directory, state) in states {
        if state.is_some() && old_path != state_path(&directory) {
            fs::remove_file(old_path)
                .map_err(|error| format!("目录已移动，旧断点清理失败: {error}"))?;
        }
    }
    Ok(())
}
