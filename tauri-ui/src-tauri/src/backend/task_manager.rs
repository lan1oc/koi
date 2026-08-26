//! Shared generation-aware lifecycle tracking for native long-running tasks.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const TASK_STATE_VERSION: u32 = 1;
const TASK_RETENTION_MS: u64 = 24 * 60 * 60 * 1_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TaskTicket {
    pub(crate) task_id: String,
    pub(crate) generation: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct ManagedTaskState {
    pub(crate) task_id: String,
    pub(crate) domain: String,
    pub(crate) target_key: String,
    pub(crate) generation: u64,
    pub(crate) running: bool,
    pub(crate) done: bool,
    pub(crate) stopped: bool,
    pub(crate) success: bool,
    pub(crate) created_at: u64,
    pub(crate) finished_at: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct TaskLifecycleEvent {
    pub(crate) event: String,
    pub(crate) task_id: String,
    pub(crate) domain: String,
    pub(crate) generation: u64,
    pub(crate) timestamp: u64,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct PersistedTaskState {
    schema_version: u32,
    sequence: u64,
    tasks: BTreeMap<String, ManagedTaskState>,
}

pub(crate) struct TaskManager {
    path: Option<PathBuf>,
    state: Mutex<PersistedTaskState>,
    subscribers: Mutex<Vec<mpsc::SyncSender<TaskLifecycleEvent>>>,
}

impl TaskManager {
    pub(crate) fn persistent(path: PathBuf) -> Result<Self, String> {
        let mut state = load_state(&path)?;
        recover_interrupted_tasks(&mut state);
        let manager = Self {
            path: Some(path),
            state: Mutex::new(state),
            subscribers: Mutex::new(Vec::new()),
        };
        manager.persist()?;
        Ok(manager)
    }

    pub(crate) fn in_memory() -> Self {
        Self {
            path: None,
            state: Mutex::new(PersistedTaskState {
                schema_version: TASK_STATE_VERSION,
                ..PersistedTaskState::default()
            }),
            subscribers: Mutex::new(Vec::new()),
        }
    }

    pub(crate) fn register(
        &self,
        task_id: impl Into<String>,
        domain: impl Into<String>,
        target_key: impl Into<String>,
    ) -> Result<TaskTicket, String> {
        let task_id = task_id.into();
        let domain = domain.into();
        let target_key = target_key.into();
        if task_id.trim().is_empty() || domain.trim().is_empty() {
            return Err("managed task id and domain are required".to_string());
        }
        let now = now_ms();
        let (ticket, event) = {
            let mut state = self.lock_state();
            prune_locked(&mut state, now);
            if state.tasks.values().any(|task| {
                task.running
                    && task.domain == domain
                    && !target_key.is_empty()
                    && task.target_key == target_key
            }) {
                return Err(format!(
                    "an active {domain} task already owns target {target_key}"
                ));
            }
            state.sequence = state.sequence.saturating_add(1);
            let generation = state
                .tasks
                .get(&task_id)
                .map(|task| task.generation.saturating_add(1))
                .unwrap_or(state.sequence.max(1));
            let task = ManagedTaskState {
                task_id: task_id.clone(),
                domain: domain.clone(),
                target_key,
                generation,
                running: true,
                done: false,
                stopped: false,
                success: false,
                created_at: now,
                finished_at: None,
            };
            state.tasks.insert(task_id.clone(), task);
            persist_locked(self.path.as_deref(), &state)?;
            let ticket = TaskTicket {
                task_id: task_id.clone(),
                generation,
            };
            let event = TaskLifecycleEvent {
                event: "started".to_string(),
                task_id,
                domain,
                generation,
                timestamp: now,
            };
            (ticket, event)
        };
        self.publish(event);
        Ok(ticket)
    }

    pub(crate) fn is_active(&self, ticket: &TaskTicket) -> bool {
        self.lock_state()
            .tasks
            .get(&ticket.task_id)
            .is_some_and(|task| {
                task.generation == ticket.generation && task.running && !task.stopped
            })
    }

    pub(crate) fn finish(&self, ticket: &TaskTicket, success: bool) -> Result<bool, String> {
        let now = now_ms();
        let event = {
            let mut state = self.lock_state();
            let Some(task) = state.tasks.get_mut(&ticket.task_id) else {
                return Ok(false);
            };
            if task.generation != ticket.generation || !task.running || task.stopped {
                return Ok(false);
            }
            task.running = false;
            task.done = true;
            task.success = success;
            task.finished_at = Some(now);
            let event = TaskLifecycleEvent {
                event: "finished".to_string(),
                task_id: task.task_id.clone(),
                domain: task.domain.clone(),
                generation: task.generation,
                timestamp: now,
            };
            persist_locked(self.path.as_deref(), &state)?;
            event
        };
        self.publish(event);
        Ok(true)
    }

    pub(crate) fn cancel(&self, task_id: &str) -> Result<Option<ManagedTaskState>, String> {
        let now = now_ms();
        let (snapshot, event) = {
            let mut state = self.lock_state();
            let Some(task) = state.tasks.get_mut(task_id) else {
                return Ok(None);
            };
            task.generation = task.generation.saturating_add(1);
            task.running = false;
            task.done = true;
            task.stopped = true;
            task.success = false;
            task.finished_at = Some(now);
            let snapshot = task.clone();
            let event = TaskLifecycleEvent {
                event: "cancelled".to_string(),
                task_id: task.task_id.clone(),
                domain: task.domain.clone(),
                generation: task.generation,
                timestamp: now,
            };
            persist_locked(self.path.as_deref(), &state)?;
            (snapshot, event)
        };
        self.publish(event);
        Ok(Some(snapshot))
    }

    pub(crate) fn snapshot(&self, task_id: &str) -> Option<ManagedTaskState> {
        self.lock_state().tasks.get(task_id).cloned()
    }

    #[cfg(test)]
    pub(crate) fn subscribe(&self) -> mpsc::Receiver<TaskLifecycleEvent> {
        let (sender, receiver) = mpsc::sync_channel(32);
        self.subscribers
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .push(sender);
        receiver
    }

    fn persist(&self) -> Result<(), String> {
        let state = self.lock_state();
        persist_locked(self.path.as_deref(), &state)
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, PersistedTaskState> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn publish(&self, event: TaskLifecycleEvent) {
        let mut subscribers = self
            .subscribers
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        subscribers.retain(|sender| match sender.try_send(event.clone()) {
            Ok(()) | Err(mpsc::TrySendError::Full(_)) => true,
            Err(mpsc::TrySendError::Disconnected(_)) => false,
        });
    }
}

fn recover_interrupted_tasks(state: &mut PersistedTaskState) {
    let now = now_ms();
    for task in state.tasks.values_mut().filter(|task| task.running) {
        task.generation = task.generation.saturating_add(1);
        task.running = false;
        task.done = true;
        task.stopped = true;
        task.success = false;
        task.finished_at = Some(now);
    }
}

fn prune_locked(state: &mut PersistedTaskState, now: u64) {
    state.tasks.retain(|_, task| {
        task.running
            || now.saturating_sub(task.finished_at.unwrap_or(task.created_at)) <= TASK_RETENTION_MS
    });
}

fn load_state(path: &Path) -> Result<PersistedTaskState, String> {
    if !path.exists() {
        return Ok(PersistedTaskState {
            schema_version: TASK_STATE_VERSION,
            ..PersistedTaskState::default()
        });
    }
    let bytes = fs::read(path).map_err(|error| format!("read task state failed: {error}"))?;
    let state: PersistedTaskState = serde_json::from_slice(&bytes)
        .map_err(|error| format!("parse task state failed: {error}"))?;
    if state.schema_version != TASK_STATE_VERSION {
        return Err(format!(
            "unsupported task state version: {}",
            state.schema_version
        ));
    }
    Ok(state)
}

fn persist_locked(path: Option<&Path>, state: &PersistedTaskState) -> Result<(), String> {
    let Some(path) = path else {
        return Ok(());
    };
    let parent = path
        .parent()
        .ok_or_else(|| "task state path has no parent".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("create task state dir failed: {error}"))?;
    let bytes = serde_json::to_vec_pretty(state)
        .map_err(|error| format!("encode task state failed: {error}"))?;
    let temp = path.with_file_name(format!(
        ".{}.tmp-{}-{}",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("tasks"),
        std::process::id(),
        now_ms()
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)
        .map_err(|error| format!("create temporary task state failed: {error}"))?;
    let result = (|| {
        file.write_all(&bytes)
            .map_err(|error| format!("write task state failed: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("sync task state failed: {error}"))?;
        drop(file);
        atomic_replace(&temp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source = source
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let destination = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    unsafe {
        MoveFileExW(
            PCWSTR(source.as_ptr()),
            PCWSTR(destination.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("atomically replace task state failed: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("replace task state failed: {error}"))
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}

pub(crate) fn run_self_test(path: &Path) -> Result<bool, String> {
    let manager = TaskManager::persistent(path.to_path_buf())?;
    let ticket = manager.register("self-test-task", "self-test", "isolated")?;
    let cancelled = manager
        .cancel(&ticket.task_id)?
        .ok_or_else(|| "task manager self-test cancel lost task".to_string())?;
    let late_rejected = !manager.finish(&ticket, true)?;
    drop(manager);
    let restored = TaskManager::persistent(path.to_path_buf())?
        .snapshot("self-test-task")
        .ok_or_else(|| "task manager self-test did not persist task".to_string())?;
    Ok(cancelled.stopped
        && cancelled.generation > ticket.generation
        && late_rejected
        && restored.stopped
        && !restored.running)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_state(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "koi-task-manager-{label}-{}-{}.json",
            std::process::id(),
            now_ms()
        ))
    }

    #[test]
    fn cancellation_advances_generation_and_rejects_late_completion() {
        let manager = TaskManager::in_memory();
        let events = manager.subscribe();
        let ticket = manager
            .register("task-1", "notice", "c:/target")
            .expect("register");
        assert!(manager.is_active(&ticket));
        let cancelled = manager.cancel(&ticket.task_id).unwrap().unwrap();
        assert!(cancelled.stopped);
        assert!(cancelled.generation > ticket.generation);
        assert!(!manager.is_active(&ticket));
        assert!(!manager.finish(&ticket, true).unwrap());
        assert_eq!(events.recv().unwrap().event, "started");
        assert_eq!(events.recv().unwrap().event, "cancelled");
    }

    #[test]
    fn persisted_running_task_is_stopped_on_restart() {
        let path = temp_state("restart");
        let manager = TaskManager::persistent(path.clone()).unwrap();
        let ticket = manager
            .register("task-restart", "external-tools", "managed")
            .unwrap();
        drop(manager);
        let restarted = TaskManager::persistent(path.clone()).unwrap();
        let task = restarted.snapshot(&ticket.task_id).unwrap();
        assert!(task.stopped);
        assert!(!task.running);
        assert!(task.generation > ticket.generation);
        assert!(!restarted.finish(&ticket, true).unwrap());
        let _ = fs::remove_file(path);
    }
}
