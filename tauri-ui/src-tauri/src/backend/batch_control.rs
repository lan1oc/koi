use super::task_manager::{TaskEventSink, TaskManager, TaskTicket};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Default)]
pub(crate) struct CancellationToken(Arc<AtomicBool>);

impl CancellationToken {
    #[cfg(test)]
    pub(crate) fn new() -> Self {
        Self::default()
    }

    pub(crate) fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }

    pub(crate) fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

#[derive(Debug, Default, Deserialize)]
struct ControlRequest {
    #[serde(default)]
    action: String,
    #[serde(
        default,
        alias = "operation_id",
        alias = "operationId",
        alias = "taskId"
    )]
    task_id: String,
}

pub(crate) struct BatchRun {
    internal_id: Option<String>,
    ticket: Option<TaskTicket>,
    token: CancellationToken,
}

impl BatchRun {
    pub(crate) fn token(&self) -> CancellationToken {
        self.token.clone()
    }
}

struct ActiveRun {
    generation: u64,
    token: CancellationToken,
}

pub(crate) struct BatchControlManager {
    lifecycle: TaskManager,
    active: Mutex<HashMap<String, ActiveRun>>,
    // Serializes active-map transitions without holding the map lock while a
    // lifecycle operation invokes external event sinks.
    coordination: Mutex<()>,
}

impl BatchControlManager {
    pub(crate) fn new(path: PathBuf) -> Result<Self, String> {
        Ok(Self {
            lifecycle: TaskManager::persistent(path)?,
            active: Mutex::new(HashMap::new()),
            coordination: Mutex::new(()),
        })
    }

    pub(crate) fn control(&self, domain: &str, payload: &Value) -> Result<Option<Value>, String> {
        let request: ControlRequest = serde_json::from_value(payload.clone())
            .map_err(|error| format!("批量任务控制字段格式错误: {error}"))?;
        let action = request.action.trim().to_ascii_lowercase();
        if action.is_empty() || action == "run" || action == "start" {
            return Ok(None);
        }
        let task_id = request.task_id.trim();
        if task_id.is_empty() {
            return Err("task_id is required for batch task control".to_string());
        }
        let internal_id = internal_task_id(domain, task_id);
        match action.as_str() {
            "cancel" | "stop" => {
                let expected = {
                    let _coordination = self
                        .coordination
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner());
                    self.active
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner())
                        .get(&internal_id)
                        .map(|active| (active.generation, active.token.clone()))
                };
                // Lifecycle transitions publish events.  Keep the active-map
                // locks out of that call so a sink can synchronously reenter
                // task control without deadlocking this manager.
                let snapshot = self.lifecycle.cancel_generation(
                    &internal_id,
                    expected.as_ref().map(|(generation, _)| *generation),
                )?;
                // Signal the token captured before the lifecycle transition.
                // A newer run may bind the same public id while cancellation
                // events are being published; looking up the token only after
                // that publish would leave the old worker running.
                if snapshot.as_ref().is_some_and(|task| task.stopped) {
                    if let Some((_, token)) = expected.as_ref() {
                        token.cancel();
                    }
                }
                let active = self.remove_active_generation(
                    &internal_id,
                    expected.as_ref().map(|(generation, _)| *generation),
                    snapshot.as_ref(),
                );
                let stopped = snapshot.as_ref().is_some_and(|task| task.stopped);
                if stopped {
                    if let Some(active) = active.as_ref() {
                        active.token.cancel();
                    }
                }
                let exists = snapshot.is_some();
                let message = match snapshot.as_ref() {
                    Some(task) if task.stopped && active.is_some() => "批量任务取消信号已送达",
                    Some(task) if task.stopped => "批量任务已停止",
                    Some(task) if task.done => "批量任务已完成，未改变完成状态",
                    Some(_) => "批量任务状态未改变",
                    None => "批量任务不存在或已过期",
                };
                Ok(Some(json!({
                    "success": exists,
                    "cancelled": stopped,
                    "task_id": task_id,
                    "running": snapshot.as_ref().is_some_and(|task| task.running),
                    "done": snapshot.as_ref().is_some_and(|task| task.done),
                    "stopped": stopped,
                    "task_success": snapshot.as_ref().is_some_and(|task| task.success),
                    "generation": snapshot.as_ref().map(|task| task.generation),
                    "message": message,
                })))
            }
            "status" => {
                let snapshot = self.lifecycle.snapshot(&internal_id);
                Ok(Some(match snapshot {
                    Some(task) => json!({
                        "success": true,
                        "task_id": task_id,
                        "running": task.running,
                        "done": task.done,
                        "stopped": task.stopped,
                        "task_success": task.success,
                        "generation": task.generation,
                        "domain": domain,
                    }),
                    None => json!({
                        "success": false,
                        "task_id": task_id,
                        "running": false,
                        "done": true,
                        "stopped": false,
                        "message": "批量任务不存在或已过期",
                    }),
                }))
            }
            _ => Err(format!("unsupported batch task action: {action}")),
        }
    }

    pub(crate) fn add_event_sink(&self, sink: TaskEventSink) {
        self.lifecycle.add_event_sink(sink);
    }

    pub(crate) fn begin(&self, domain: &str, payload: &Value) -> Result<BatchRun, String> {
        let request: ControlRequest = serde_json::from_value(payload.clone())
            .map_err(|error| format!("批量任务控制字段格式错误: {error}"))?;
        let task_id = request.task_id.trim();
        let token = CancellationToken::default();
        if task_id.is_empty() {
            return Ok(BatchRun {
                internal_id: None,
                ticket: None,
                token,
            });
        }
        let internal_id = internal_task_id(domain, task_id);
        let ticket = self
            .lifecycle
            .register(internal_id.clone(), domain, task_id)?;
        self.bind_active_run(&internal_id, &ticket, token.clone());
        Ok(BatchRun {
            internal_id: Some(internal_id),
            ticket: Some(ticket),
            token,
        })
    }

    fn bind_active_run(&self, internal_id: &str, ticket: &TaskTicket, token: CancellationToken) {
        let _coordination = self
            .coordination
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut active_runs = self
            .active
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        active_runs.insert(
            internal_id.to_string(),
            ActiveRun {
                generation: ticket.generation,
                token: token.clone(),
            },
        );
        // A stop may have won immediately after lifecycle registration (for
        // example, through a caller that already held a lifecycle handle).
        // Never leave a live token attached to an inactive generation.
        if !self.lifecycle.is_active(ticket) {
            if active_runs
                .get(internal_id)
                .is_some_and(|active| active.generation == ticket.generation)
            {
                active_runs.remove(internal_id);
            }
            token.cancel();
        }
    }

    fn remove_active_generation(
        &self,
        internal_id: &str,
        expected_generation: Option<u64>,
        snapshot: Option<&super::task_manager::ManagedTaskState>,
    ) -> Option<ActiveRun> {
        let _coordination = self
            .coordination
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut active_runs = self
            .active
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let current_generation = active_runs.get(internal_id).map(|active| active.generation);
        let should_remove = match (expected_generation, current_generation, snapshot) {
            (Some(expected), Some(current), Some(snapshot)) if current == expected => {
                (snapshot.stopped && snapshot.generation == expected.saturating_add(1))
                    || (snapshot.done && !snapshot.running && snapshot.generation == expected)
            }
            // A cancellation that observed no active token may race the
            // subsequent binding. The stopped snapshot identifies the exact
            // generation it invalidated; preserve any later restart.
            (None, Some(current), Some(snapshot)) if snapshot.stopped => {
                current.saturating_add(1) == snapshot.generation
                    || (snapshot.done && !snapshot.running && current == snapshot.generation)
            }
            _ => false,
        };
        if should_remove {
            active_runs.remove(internal_id)
        } else {
            None
        }
    }

    pub(crate) fn finish(&self, run: BatchRun, success: bool) -> Result<bool, String> {
        let (Some(internal_id), Some(ticket)) = (run.internal_id, run.ticket) else {
            return Ok(true);
        };
        // Complete the lifecycle first.  Removing the token before this call
        // creates a cancellation window where stop can invalidate the task
        // state but cannot signal the worker.  Generation matching below keeps
        // a newer task with the same public id intact.
        let accepted = self.lifecycle.finish(&ticket, success)?;
        let _coordination = self
            .coordination
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut active = self
            .active
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if active
            .get(&internal_id)
            .is_some_and(|current| current.generation == ticket.generation)
        {
            active.remove(&internal_id);
        }
        Ok(accepted)
    }
}

fn internal_task_id(domain: &str, task_id: &str) -> String {
    format!("{domain}:{task_id}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manager() -> BatchControlManager {
        BatchControlManager {
            lifecycle: TaskManager::in_memory(),
            active: Mutex::new(HashMap::new()),
            coordination: Mutex::new(()),
        }
    }

    #[test]
    fn same_command_control_cancels_active_token_and_rejects_late_finish() {
        let manager = manager();
        let run = manager
            .begin("asset", &json!({"task_id":"batch-1"}))
            .expect("begin");
        let token = run.token();
        let status = manager
            .control("asset", &json!({"action":"status","task_id":"batch-1"}))
            .unwrap()
            .unwrap();
        assert_eq!(status["running"], true);
        let cancelled = manager
            .control("asset", &json!({"action":"cancel","task_id":"batch-1"}))
            .unwrap()
            .unwrap();
        assert_eq!(cancelled["cancelled"], true);
        assert!(token.is_cancelled());
        manager.finish(run, true).unwrap();
        let status = manager
            .control("asset", &json!({"action":"status","task_id":"batch-1"}))
            .unwrap()
            .unwrap();
        assert_eq!(status["stopped"], true);
        assert_eq!(status["task_success"], false);
    }

    #[test]
    fn finishing_a_tracked_task_removes_its_internal_active_entry() {
        let manager = manager();
        let run = manager
            .begin("asset", &json!({"taskId":"finished"}))
            .expect("begin");
        let internal_id = run.internal_id.clone().expect("internal id");
        assert!(manager
            .active
            .lock()
            .expect("active lock")
            .contains_key(&internal_id));
        assert!(manager.finish(run, true).expect("finish"));
        assert!(!manager
            .active
            .lock()
            .expect("active lock")
            .contains_key(&internal_id));
    }

    #[test]
    fn default_run_is_untracked_and_keeps_existing_payload_contract() {
        let manager = manager();
        assert!(manager.control("threatbook", &json!({})).unwrap().is_none());
        let run = manager.begin("threatbook", &json!({})).unwrap();
        assert!(run.internal_id.is_none());
        assert!(manager.finish(run, true).unwrap());
    }

    #[test]
    fn completed_task_cannot_be_reclassified_as_stopped() {
        let manager = manager();
        let run = manager
            .begin("asset", &json!({"task_id":"completed"}))
            .expect("begin");
        assert!(manager.finish(run, true).expect("finish"));

        let response = manager
            .control("asset", &json!({"action":"stop","task_id":"completed"}))
            .expect("control")
            .expect("control response");
        assert_eq!(response["success"], true);
        assert_eq!(response["cancelled"], false);
        assert_eq!(response["done"], true);
        assert_eq!(response["stopped"], false);
        assert_eq!(response["task_success"], true);
    }

    #[test]
    fn late_finish_does_not_remove_restarted_task_token() {
        let manager = manager();
        let first = manager
            .begin("asset", &json!({"task_id":"reused"}))
            .expect("first begin");
        manager
            .control("asset", &json!({"action":"stop","task_id":"reused"}))
            .expect("stop first")
            .expect("stop response");

        let second = manager
            .begin("asset", &json!({"task_id":"reused"}))
            .expect("second begin");
        let second_token = second.token();
        assert!(!manager.finish(first, true).expect("late finish"));

        let stopped = manager
            .control("asset", &json!({"action":"stop","task_id":"reused"}))
            .expect("stop second")
            .expect("stop response");
        assert_eq!(stopped["cancelled"], true);
        assert!(second_token.is_cancelled());
        assert!(!manager.finish(second, true).expect("finish stopped second"));
    }

    #[test]
    fn persistent_manager_recovers_interrupted_task_as_stopped() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "koi-batch-control-restart-{}-{}.json",
            std::process::id(),
            unique
        ));
        let manager = BatchControlManager::new(path.clone()).expect("manager");
        let run = manager
            .begin("threatbook", &json!({"task_id":"interrupted"}))
            .expect("begin");
        drop(manager);

        let restarted = BatchControlManager::new(path.clone()).expect("restarted manager");
        let status = restarted
            .control(
                "threatbook",
                &json!({"action":"status","task_id":"interrupted"}),
            )
            .expect("status")
            .expect("status response");
        assert_eq!(status["running"], false);
        assert_eq!(status["done"], true);
        assert_eq!(status["stopped"], true);
        assert!(!restarted.finish(run, true).expect("late finish"));
        drop(restarted);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn binding_a_task_after_generation_cancellation_cancels_its_token() {
        let manager = manager();
        let token = CancellationToken::default();
        let internal_id = internal_task_id("asset", "pre-cancel");
        let ticket = manager
            .lifecycle
            .register(internal_id.clone(), "asset", "pre-cancel")
            .expect("register");
        manager
            .lifecycle
            .cancel(&internal_id)
            .expect("cancel registered task");

        manager.bind_active_run(&internal_id, &ticket, token.clone());
        assert!(token.is_cancelled());
        assert!(!manager
            .active
            .lock()
            .expect("active lock")
            .contains_key(&internal_id));
    }

    #[test]
    fn generation_cleanup_does_not_remove_a_restarted_task_token() {
        let manager = manager();
        let internal_id = internal_task_id("asset", "bind-race");
        let ticket = manager
            .lifecycle
            .register(internal_id.clone(), "asset", "bind-race")
            .expect("register");
        let old_token = CancellationToken::default();
        manager.bind_active_run(&internal_id, &ticket, old_token.clone());
        manager
            .lifecycle
            .cancel_generation(&internal_id, Some(ticket.generation))
            .expect("cancel old generation");

        let restarted = manager
            .lifecycle
            .register(internal_id.clone(), "asset", "bind-race")
            .expect("register restarted task");
        let new_token = CancellationToken::default();
        manager.bind_active_run(&internal_id, &restarted, new_token.clone());

        // The old cancellation path may finish after the restart.  Its exact
        // generation check must leave the new worker token and map entry
        // untouched; the old token is signalled independently by the caller.
        old_token.cancel();
        assert!(manager
            .remove_active_generation(
                &internal_id,
                Some(ticket.generation),
                Some(&manager.lifecycle.snapshot(&internal_id).expect("snapshot"))
            )
            .is_none());
        assert!(old_token.is_cancelled());
        assert!(!new_token.is_cancelled());
        assert!(manager
            .active
            .lock()
            .expect("active lock")
            .get(&internal_id)
            .is_some_and(|active| active.generation == restarted.generation));
    }

    #[test]
    fn finish_publishes_before_removing_the_matching_worker_token() {
        use std::sync::{mpsc, Arc};

        let manager = Arc::new(manager());
        let (sender, receiver) = mpsc::sync_channel(1);
        let observer = Arc::downgrade(&manager);
        manager.add_event_sink(Arc::new(move |event| {
            if event.event == "finished" {
                let still_tracked = observer.upgrade().is_some_and(|manager| {
                    manager
                        .active
                        .lock()
                        .expect("active lock")
                        .contains_key(&event.task_id)
                });
                sender.send(still_tracked).expect("finish observer");
            }
        }));

        let run = manager
            .begin("asset", &json!({"task_id":"finish-order"}))
            .expect("begin");
        assert!(manager.finish(run, true).expect("finish"));
        assert!(receiver
            .recv_timeout(std::time::Duration::from_secs(1))
            .expect("finish event observer"));
    }

    #[test]
    fn cancellation_event_can_start_a_replacement_without_losing_old_token_signal() {
        use std::sync::{Arc, Mutex};

        let manager = Arc::new(manager());
        let first = manager
            .begin("asset", &json!({"task_id":"reentrant-cancel"}))
            .expect("first begin");
        let first_token = first.token();
        let replacement_token = Arc::new(Mutex::new(None));
        let replacement_slot = Arc::clone(&replacement_token);
        let weak_manager = Arc::downgrade(&manager);
        manager.add_event_sink(Arc::new(move |event| {
            if event.event == "cancelled" {
                let manager = weak_manager.upgrade().expect("manager remains alive");
                let replacement = manager
                    .begin("asset", &json!({"task_id":"reentrant-cancel"}))
                    .expect("replacement begin from sink");
                *replacement_slot.lock().expect("replacement token lock") =
                    Some(replacement.token());
            }
        }));

        let response = manager
            .control(
                "asset",
                &json!({"action":"cancel","task_id":"reentrant-cancel"}),
            )
            .expect("cancel reentrant task")
            .expect("cancel response");
        assert_eq!(response["cancelled"], true);
        assert!(first_token.is_cancelled());
        assert!(!replacement_token
            .lock()
            .expect("replacement token lock")
            .as_ref()
            .expect("replacement token")
            .is_cancelled());
    }
}
