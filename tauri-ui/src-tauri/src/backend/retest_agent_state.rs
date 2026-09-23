//! Queue progress and file checkpoints have independent lifetimes. Model
//! context/compaction may summarize them, but must never replace either.
use super::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(super) struct RetestQueueState {
    pub plan: RetestResumePlan,
    pub generate_reports: bool,
    pub goal: String,
    #[serde(default)]
    pub completion_items: Vec<Value>,
    #[serde(default)]
    pub reports: Vec<String>,
    #[serde(default)]
    pub summaries: Vec<String>,
}

/// Checkpoints contain evidence several levels below the UI envelope. The
/// six-level chat sanitizer destroys their types and must not be used here.
pub(super) fn sanitize_retest_checkpoint(value: &Value, secret: &str) -> Value {
    fn scrub(value: &Value, secret: &str, depth: usize) -> Value {
        if depth > 32 {
            return Value::Null;
        }
        match value {
            Value::Object(object) => Value::Object(
                object
                    .iter()
                    .map(|(key, value)| {
                        (
                            key.clone(),
                            if is_sensitive_field_name(key) {
                                json!("<redacted>")
                            } else {
                                scrub(value, secret, depth + 1)
                            },
                        )
                    })
                    .collect(),
            ),
            Value::Array(items) => Value::Array(
                items
                    .iter()
                    .take(1000)
                    .map(|item| scrub(item, secret, depth + 1))
                    .collect(),
            ),
            Value::String(value) => json!(truncate(&redact_agent_text(value, secret), 100_000)),
            _ => value.clone(),
        }
    }
    scrub(value, secret, 0)
}

pub(super) fn file_checkpoint(value: &Value) -> Option<&Value> {
    fn find(value: &Value, depth: usize) -> Option<&Value> {
        if depth > 10 || !value.is_object() {
            return None;
        }
        // Prefer the actual snapshot to its queue wrapper (which also has
        // stage/source_file, but no saved investigation or source digest).
        for key in [
            "resume_snapshot",
            "resumeSnapshot",
            "current_file_checkpoint",
            "currentFileCheckpoint",
            "currentFile",
            "current_file",
            "resumeState",
            "resume_state",
            "session",
            "rustResumePlan",
        ] {
            if let Some(found) = value.get(key).and_then(|child| find(child, depth + 1)) {
                return Some(found);
            }
        }
        (value.get("stage").and_then(Value::as_str).is_some()
            && value
                .get("source_file")
                .or_else(|| value.get("sourceFile"))
                .and_then(Value::as_str)
                .is_some())
        .then_some(value)
    }
    find(value, 0)
}

pub(super) fn restore_request(runtime: &NativeRuntime, request: &mut AgentMessageRequest) {
    let state = runtime.lock_state();
    let Some(session) = state.sessions.get(&request.session_id) else {
        return;
    };
    if request.target_dir.as_deref().is_some_and(|target| {
        !target.trim().is_empty()
            && normalized_path_key(&expand_user(Path::new(target), &runtime.home_dir))
                != normalized_path_key(Path::new(&session.workspace_root))
    }) {
        return;
    }
    if request
        .target_dir
        .as_deref()
        .is_none_or(|target| target.trim().is_empty())
    {
        request.target_dir = Some(session.workspace_root.clone());
    }
    let durable = legacy_retest_resume_state(session);
    let context = request.frontend_context.get_or_insert_with(|| json!({}));
    if !context.is_object() {
        *context = json!({});
    }
    if !context["session"].is_object() {
        context["session"] = json!({});
    }
    if !context["session"]["resumeState"].is_object() {
        context["session"]["resumeState"] = json!({});
    }
    let incoming = &mut context["session"]["resumeState"];
    if durable["currentFile"].is_object() {
        incoming["currentFile"] = durable["currentFile"].clone();
    }
    for key in ["targetDir", "sourceFiles"] {
        if incoming.get(key).is_none() || incoming[key].is_null() {
            incoming[key] = durable[key].clone();
        }
    }
    for key in [
        "completionItems",
        "diskCompletedReportEvidence",
        "reports",
        "summaries",
    ] {
        let mut items = incoming[key].as_array().cloned().unwrap_or_default();
        for item in durable[key].as_array().into_iter().flatten() {
            if !items.contains(item) {
                items.push(item.clone());
            }
        }
        incoming[key] = json!(items);
    }
    if let Some(queue) = &session.retest_queue {
        request.generate_reports |= queue.generate_reports;
        // Exact backend completion paths also cover runs where report
        // generation was disabled or the UI closed before the last event.
        if !context["progressEvidence"].is_object() {
            context["progressEvidence"] = json!({});
        }
        let mut completed = context["progressEvidence"]["completedFileNames"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        completed.extend(
            queue
                .plan
                .completed_source_files
                .iter()
                .map(|path| json!(path)),
        );
        context["progressEvidence"]["completedFileNames"] = json!(completed);
        context["progressEvidence"]["targetDir"] = json!(queue.plan.target_dir);
    }
}

pub(super) fn start_queue(
    session: &mut SessionState,
    plan: &RetestResumePlan,
    request: &AgentMessageRequest,
    secret: &str,
) {
    let previous = session.retest_queue.take().filter(|queue| {
        request.use_progress_evidence
            && normalized_path_key(Path::new(&queue.plan.target_dir))
                == normalized_path_key(Path::new(&plan.target_dir))
    });
    let mut queue = previous.unwrap_or_else(|| RetestQueueState {
        plan: plan.clone(),
        generate_reports: request.generate_reports,
        goal: redact_agent_text(&request.message, secret),
        completion_items: Vec::new(),
        reports: Vec::new(),
        summaries: Vec::new(),
    });
    queue.plan = plan.clone();
    queue.generate_reports = request.generate_reports;
    if let Some(checkpoint) = plan
        .current_file_checkpoint
        .as_ref()
        .and_then(file_checkpoint)
    {
        session.resume_snapshot = Some(sanitize_retest_checkpoint(checkpoint, secret));
    }
    session.workspace_root = plan.target_dir.clone();
    session.retest_queue = Some(queue);
}

pub(super) fn complete_file(
    runtime: &NativeRuntime,
    session_id: &str,
    generation: u64,
    outcome: &NativeRetestOutcome,
    reports: &[String],
) -> Result<(), String> {
    let mut state = runtime.lock_state();
    let session = state
        .sessions
        .get_mut(session_id)
        .ok_or("agent session not found")?;
    if session.stopped || session.generation != generation {
        return Err("retest completion was cancelled".into());
    }
    if let Some(queue) = session.retest_queue.as_mut() {
        let source = &outcome.source_file;
        let key = normalized_path_key(Path::new(source));
        if !queue
            .plan
            .completed_source_files
            .iter()
            .any(|path| normalized_path_key(Path::new(path)) == key)
        {
            queue.plan.completed_source_files.push(source.clone());
        }
        queue
            .plan
            .pending_source_files
            .retain(|path| normalized_path_key(Path::new(path)) != key);
        queue.plan.next_source_file = queue.plan.pending_source_files.first().cloned();
        queue.plan.next_index = queue
            .plan
            .next_source_file
            .as_ref()
            .and_then(|next| {
                queue
                    .plan
                    .source_files
                    .iter()
                    .position(|source| source == next)
            })
            .unwrap_or(queue.plan.source_files.len());
        queue.plan.current_file_checkpoint = None;
        let status = if outcome.result_data["risk_count"].as_u64().unwrap_or(0) > 0 {
            "risk"
        } else if outcome.manual_test_required {
            "manual"
        } else {
            "clean"
        };
        queue
            .completion_items
            .retain(|item| item["sourceFile"] != *source);
        queue.completion_items.push(json!({"sourceFile":source,"sourceFileName":Path::new(source).file_name().map(|name| name.to_string_lossy()),
            "status":status,"reason":outcome.summary,"reportPaths":reports}));
        queue.reports.extend(
            reports
                .iter()
                .filter(|path| !queue.reports.contains(path))
                .cloned()
                .collect::<Vec<_>>(),
        );
        if let Some(summary) = &outcome.summary {
            queue.summaries.push(summary.clone());
        }
    }
    persist_locked(&runtime.inner, &state)
}

pub(super) fn resume_state(session: &SessionState) -> Option<Value> {
    let checkpoint = session.resume_snapshot.as_ref().and_then(file_checkpoint);
    let queue = session.retest_queue.as_ref();
    if checkpoint.is_none() && queue.is_none() {
        return None;
    }
    let source = checkpoint.and_then(|value| value["source_file"].as_str());
    let source_files = queue
        .map(|queue| queue.plan.source_files.clone())
        .unwrap_or_else(|| source.into_iter().map(str::to_string).collect());
    let next_index = queue.map(|queue| queue.plan.next_index).unwrap_or(0);
    let current = checkpoint.filter(|_| source.is_some_and(|source| queue.is_none_or(|queue| {
        !queue.plan.completed_source_files.iter().any(|done| normalized_path_key(Path::new(done)) == normalized_path_key(Path::new(source)))
    }))).map(|snapshot| json!({
        "index":source_files.iter().position(|item| Some(item.as_str()) == source).unwrap_or(next_index),
        "sourceFile":source,"sourceFileName":source.and_then(|source| Path::new(source).file_name()).map(|name| name.to_string_lossy()),
        "stage":snapshot["stage"],"resumeSnapshot":snapshot,
    }));
    let pending = queue.is_some_and(|queue| !queue.plan.pending_source_files.is_empty());
    let blocked = session.status == "blocked";
    Some(json!({
        "canContinue":session.stopped || blocked || pending || (current.is_some() && session.status != "completed"),
        "targetDir":queue.map(|queue| queue.plan.target_dir.as_str()).unwrap_or(&session.workspace_root),
        "sourceFiles":source_files,"nextIndex":next_index,
        "summaries":queue.map(|queue| &queue.summaries).cloned().unwrap_or_default(),
        "reports":queue.map(|queue| &queue.reports).cloned().unwrap_or_default(),
        "completionItems":queue.map(|queue| &queue.completion_items).cloned().unwrap_or_default(),
        "diskCompletedFileNames":[],"diskCompletedReportEvidence":queue.map(|queue| &queue.plan.disk_report_evidence).cloned().unwrap_or_default(),
        "allLogs":session.logs,"failedCount":0,
        "generateReports":queue.is_some_and(|queue| queue.generate_reports),
        "blockedReason":if blocked || session.stopped { session.message.as_str() } else { "" },
        "blockedStage":if blocked { checkpoint.and_then(|value| value["stage"].as_str()).unwrap_or("model_transport") } else { "" },
        "blockedTitle":if blocked { "Agent等待继续" } else { "" },"currentFile":current,
    }))
}

pub(super) fn operation_observation(output: &str) -> String {
    let Ok(result) = serde_json::from_str::<Value>(output) else {
        return truncate(output, 12_000);
    };
    // Keep a complete JSON observation even when raw HTTP evidence is large.
    json!({"success":result["success"],"source_file":result["source_file"],"summary":result["summary"],
        "final_verdict":result["result_data"]["final_verdict"],"coverage":result["result_data"]["coverage"],
        "finding_judgements":result["result_data"]["finding_judgements"],"reports":result["reports"],
        "manual_test_required":result["result_data"]["manual_test_required"]}).to_string()
}

pub(super) fn continue_queue(
    runtime: &NativeRuntime,
    session_id: &str,
    generation: u64,
) -> Result<bool, String> {
    let mut state = runtime.lock_state();
    let session = state
        .sessions
        .get(session_id)
        .ok_or("agent session not found")?;
    if session.generation != generation || session.stopped {
        return Ok(true);
    }
    let Some(queue) = session.retest_queue.as_ref() else {
        return Ok(false);
    };
    let Some(source) = queue.plan.next_source_file.clone() else {
        return Ok(false);
    };
    let auto_approve = session.auto_approve;
    let operation = json!({"tool_name":"retest_source_file","risk":"medium","arguments":{
        "source_file":source,"mode":"ai","generate_report":queue.generate_reports}});
    let (operation_id, _) =
        create_operation_locked(&mut state, session_id, generation, &operation, auto_approve);
    let session = state.sessions.get_mut(session_id).expect("queue session");
    session.running = auto_approve;
    session.status = if auto_approve {
        "approved_pending_executor"
    } else {
        "awaiting_approval"
    }
    .into();
    session.message = format!("继续处理下一份通报：{source}");
    let operation = session
        .operations
        .get(&operation_id)
        .expect("queue operation")
        .clone();
    push_event(
        session,
        operation_trace_event(
            &operation,
            "tool_call",
            if auto_approve { "running" } else { "blocked" },
            &format!("Agent继续复测：{source}"),
            "info",
        ),
    );
    persist_locked(&runtime.inner, &state)?;
    drop(state);
    if auto_approve {
        if let Err(error) = runtime.start_operation_executor(session_id, &operation_id, generation)
        {
            runtime.record_operation_start_failure(session_id, &operation_id, generation, &error);
        }
    }
    runtime.publish_session_event(session_id, None, Some(generation));
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::super::tests::{configure_model, mock_model_sequence, write_confirmation_fixture};
    use super::*;

    fn fixture(label: &str) -> (PathBuf, PathBuf, ConfigStore, NativeRuntime) {
        let root = std::env::temp_dir().join(format!("koi-queue-{label}-{}", now_ms()));
        let workspace = root.join("workspace");
        fs::create_dir_all(&workspace).unwrap();
        let config = ConfigStore::new(root.join("data/config.json"));
        let runtime = NativeRuntime::new(root.join("data"), workspace.clone()).unwrap();
        (root, workspace, config, runtime)
    }

    fn wait_terminal(runtime: &NativeRuntime, config: &ConfigStore, id: &str) -> Value {
        let deadline = std::time::Instant::now() + Duration::from_secs(15);
        loop {
            let status = runtime
                .dispatch("doc.retest.agent.status", &json!({"session_id":id}), config)
                .unwrap();
            if !status["running"].as_bool().unwrap_or(false)
                && matches!(
                    status["status"].as_str(),
                    Some("completed" | "blocked" | "failed")
                )
            {
                return status;
            }
            assert!(
                std::time::Instant::now() < deadline,
                "queue timed out: {status}"
            );
            thread::sleep(Duration::from_millis(10));
        }
    }

    #[test]
    fn one_click_agent_completes_ten_files_without_losing_queue_or_report_preference() {
        let (root, workspace, config, runtime) = fixture("ten-files");
        let sources = (1..=10)
            .map(|index| workspace.join(format!("{index:02}.docx")))
            .collect::<Vec<_>>();
        for source in &sources {
            write_confirmation_fixture(source, "原通报缺少目标和账号，需要补充后核验");
        }
        let mut replies = vec![
            json!({"reply":"开始逐项复测","operation":{"tool_name":"retest_source_file","arguments":{"source_file":sources[0]}}}),
        ];
        replies.extend((0..10).map(|_| json!({"findings":[{"id":"f1","title":"待补充目标","target_urls":[],"validation_goal":"核验原通报"}],
            "finish":true,"judgements":[{"finding_id":"f1","verdict":"inconclusive","reason":"原通报缺少目标和账号"}]})));
        replies.push(json!({"reply":"十份通报均已分析，待补充材料","operation":null}));
        let (url, server) = mock_model_sequence(replies);
        configure_model(&config, &url);
        let started = runtime.dispatch("doc.retest.agent.start", &json!({"session_id":"queue","target_dir":workspace,"one_click_queue":true,"generate_reports":false}), &config).unwrap();
        if started["running"] == true {
            assert!(started["progress"].as_u64().unwrap() < 100);
        }
        let status = wait_terminal(&runtime, &config, "queue");
        assert_eq!(status["status"], "completed", "{status}");
        assert_eq!(status["resume_state"]["nextIndex"], 10);
        assert_eq!(status["progress"], 100);
        assert_eq!(
            status["resume_state"]["completionItems"]
                .as_array()
                .unwrap()
                .len(),
            10
        );
        assert_eq!(status["resume_state"]["generateReports"], false);
        assert_eq!(status["resume_state"]["reports"], json!([]));
        assert_eq!(status["resume_state"]["canContinue"], false);
        assert_eq!(
            status["agent_session"]["operations"]
                .as_object()
                .unwrap()
                .len(),
            10
        );
        let requests = server.join().unwrap();
        assert_eq!(requests.len(), 12);
        let body: Value =
            serde_json::from_str(requests.last().unwrap().split("\r\n\r\n").nth(1).unwrap())
                .unwrap();
        let input: Value =
            serde_json::from_str(body["messages"][1]["content"].as_str().unwrap()).unwrap();
        assert_eq!(
            input["retest_queue"]["plan"]["pending_source_files"],
            json!([])
        );
        assert_eq!(
            input["retest_queue"]["completion_items"]
                .as_array()
                .unwrap()
                .len(),
            10
        );
        assert!(input["allowed_operations"].is_array());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn persisted_agent_evidence_survives_compaction_restart_and_chat_continue() {
        let (root, workspace, config, runtime) = fixture("resume");
        let source = workspace.join("notice.docx");
        let target = "http://127.0.0.1:9/previous-proof";
        write_confirmation_fixture(&source, &format!("原通报 {target}"));
        let snapshot = json!({"stage":"judgement","source_file":source,"source_evidence":native_retest_source_evidence(&source).unwrap(),
            "agent_investigation":{"rounds":12,"requests_used":1,"findings":[{"id":"f1","title":"已取证问题","target_urls":[target],"validation_goal":"复核原始证据"}],
                "evidence":[{"id":"e1","finding_id":"f1","tool":"http_request","call_hash":"old-proof","success":true,"verification":true,"checked_at":"2026-09-21","data":{"success":true,"url":target,"body_excerpt":"saved-proof","nested":{"items":[{"status":200}]}}}]}});
        {
            let mut state = runtime.lock_state();
            let session = ensure_session(
                &mut state,
                "resume",
                "retest",
                workspace.to_string_lossy().into_owned(),
            );
            session.resume_snapshot = Some(snapshot.clone());
            session.status = "blocked".into();
            persist_locked(&runtime.inner, &state).unwrap();
        }
        let (url, server) = mock_model_sequence(vec![
            json!({"memory_markdown":"已完成取证，等待判定","brief":"保留原证据","confidence":"high"}),
        ]);
        configure_model(&config, &url);
        let compact = runtime
            .dispatch(
                "doc.retest.session.compact",
                &json!({"session_id":"resume","local_memory":"已取证"}),
                &config,
            )
            .unwrap();
        assert_eq!(compact["success"], true);
        server.join().unwrap();
        drop(runtime);
        let runtime = NativeRuntime::new(root.join("data"), workspace.clone()).unwrap();
        let status = runtime
            .dispatch(
                "doc.retest.agent.status",
                &json!({"session_id":"resume"}),
                &config,
            )
            .unwrap();
        assert_eq!(
            status["resume_state"]["currentFile"]["resumeSnapshot"]["agent_investigation"],
            snapshot["agent_investigation"]
        );
        let (url, server) = mock_model_sequence(vec![
            json!({"reply":"继续已保存的判定","operation":{"tool_name":"retest_source_file","arguments":{"source_file":source,"generate_report":false}}}),
            json!({"finish":true,"judgements":[{"finding_id":"f1","verdict":"reproduced","reason":"saved-proof证据确认","coverage_complete":true,"evidence_ids":["e1"]}]}),
            json!({"reply":"根据已保存证据完成判定","operation":null}),
        ]);
        configure_model(&config, &url);
        runtime.dispatch("doc.retest.agent.message", &json!({"session_id":"resume","message":"继续","force_resume":true,
            "frontend_context":{"session":{"resumeState":{"currentFile":{"sourceFile":source,"stage":"judgement","resumeSnapshot":{"stage":"judgement","source_file":source}}}}}}), &config).unwrap();
        let resumed = wait_terminal(&runtime, &config, "resume");
        assert_eq!(resumed["status"], "completed", "{resumed}");
        assert_eq!(resumed["latest_result_data"]["final_verdict"], "reproduced");
        assert_eq!(resumed["latest_result_data"]["http_requests_used"], 1);
        assert_eq!(
            resumed["resume_snapshot"]["agent_investigation"]["rounds"],
            13
        );
        let requests = server.join().unwrap();
        assert_eq!(requests.len(), 3);
        assert!(requests[1].contains("saved-proof"));
        assert!(requests[1].contains("\\\"status\\\":200"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn wrapped_frontend_checkpoint_keeps_deep_evidence_types_and_redacts_credentials() {
        let (root, workspace, _, runtime) = fixture("wrapped");
        let source = workspace.join("notice.docx");
        write_confirmation_fixture(&source, "通报");
        let evidence = json!({"findings":[{"id":"f1"}],"evidence":[{"data":{"result":{"checks":[{"success":true,"cookie":"never-leak"}]}}}]});
        let request: AgentMessageRequest = serde_json::from_value(json!({"message":"继续","target_dir":workspace,"force_resume":true,
            "frontend_context":{"session":{"resumeState":{"currentFile":{"sourceFile":source,"stage":"judgement","resumeSnapshot":{
                "stage":"judgement","source_file":source,"agent_investigation":evidence}}}}}})).unwrap();
        let plan = build_retest_resume_plan(&request, &workspace)
            .unwrap()
            .unwrap();
        {
            let mut state = runtime.lock_state();
            let session = ensure_session(
                &mut state,
                "wrapped",
                "retest",
                workspace.to_string_lossy().into_owned(),
            );
            start_queue(session, &plan, &request, "");
        }
        let (_, checkpoint) = retest_operation_context(&runtime, "wrapped", 0).unwrap();
        let snapshot = checkpoint.unwrap();
        assert_eq!(
            snapshot["agent_investigation"]["evidence"][0]["data"]["result"]["checks"][0]
                ["success"],
            true
        );
        assert_eq!(
            snapshot["agent_investigation"]["evidence"][0]["data"]["result"]["checks"][0]["cookie"],
            "<redacted>"
        );
        assert_eq!(snapshot["source_file"], json!(source));
        fs::remove_dir_all(root).unwrap();
    }
}
