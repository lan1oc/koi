//! Model-authored questions and durable user choices.
use super::*;
use std::collections::BTreeSet;

pub(super) fn parse(completion: &Value, secret: &str, generation: u64) -> Option<Value> {
    let raw = completion
        .get("follow_up")
        .or_else(|| completion.get("question"))
        .filter(|value| value.is_object())?;
    let question = raw["question"]
        .as_str()
        .or_else(|| raw["prompt"].as_str())?
        .trim();
    if question.is_empty() {
        return None;
    }
    let question = truncate(&redact_agent_text(question, secret), 1200);
    let mut options = Vec::new();
    let mut seen = BTreeSet::new();
    for option in raw["options"].as_array().into_iter().flatten().take(6) {
        let label = option
            .as_str()
            .or_else(|| option["label"].as_str())
            .unwrap_or_default()
            .trim();
        let value = option["value"]
            .as_str()
            .or_else(|| option["message"].as_str())
            .unwrap_or(label)
            .trim();
        if label.is_empty()
            || value.is_empty()
            || matches!(label, "结束" | "自定义")
            || !seen.insert(label.to_string())
        {
            continue;
        }
        options.push(json!({"id":format!("choice-{}",options.len()+1),"label":truncate(&redact_agent_text(label,secret),80),"value":truncate(&redact_agent_text(value,secret),4000)}));
    }
    let digest = format!("{:x}", Sha256::digest(question.as_bytes()));
    Some(
        json!({"id":format!("question-{generation}-{}",&digest[..12]),"question":question,"options":options,"generation":generation}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn model_choices_persist_and_end_requires_completed_queue_and_reports() {
        let root = std::env::temp_dir().join(format!("koi-followup-{}", now_ms()));
        let work = root.join("work");
        fs::create_dir_all(&work).unwrap();
        let config = ConfigStore::new(root.join("data/config.json"));
        let runtime = NativeRuntime::new(root.join("data"), work.clone()).unwrap();
        {
            let mut state = runtime.lock_state();
            let session = ensure_session(
                &mut state,
                "choices",
                "retest",
                work.to_string_lossy().into_owned(),
            );
            session.status = "blocked".into();
        }
        assert!(runtime
            .dispatch(
                "doc.retest.agent.stop",
                &json!({"session_id":"choices","complete_task":true}),
                &config
            )
            .is_err());
        let question=parse(&json!({"follow_up":{"question":"下一步需要做什么？","options":[{"label":"查看报告","value":"查看已生成的复测报告"},{"label":"核对证据","value":"核对本轮证据"}]}}),"",0).unwrap();
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("choices").unwrap();
            session.status = "completed".into();
            session.follow_up = Some(question.clone());
            persist_locked(&runtime.inner, &state).unwrap();
        }
        let source = work.join("notice.docx");
        let report = work.join("notice-report.docx");
        fs::write(&source, b"fixture source").unwrap();
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("choices").unwrap();
            session.retest_queue=Some(serde_json::from_value(json!({"plan":{"target_dir":work,"source_files":[source],"completed_source_files":[],"pending_source_files":[source],"next_index":0,"next_source_file":source,"current_file_checkpoint":null,"disk_report_evidence":[],"completed_count_hint":0,"next_index_hint":0,"numeric_hints_used":false},"generate_reports":true,"goal":"完成通报与报告"})).unwrap());
            assert!(!can_end_task(session));
            let queue = session.retest_queue.as_mut().unwrap();
            queue.plan.pending_source_files.clear();
            queue.plan.next_source_file = None;
            assert!(
                !can_end_task(session),
                "a missing completion record cannot finish the task"
            );
            let queue = session.retest_queue.as_mut().unwrap();
            queue.plan.completed_source_files = vec![source.to_string_lossy().into_owned()];
            queue
                .completion_items
                .push(json!({"sourceFile":source,"reportPaths":[report]}));
            assert!(
                !can_end_task(session),
                "a required missing report cannot finish the task"
            );
            fs::write(&report, b"fixture generated report").unwrap();
            assert!(can_end_task(session));
            persist_locked(&runtime.inner, &state).unwrap();
        }
        let recovered = NativeRuntime::new(root.join("data"), work.clone()).unwrap();
        let status = recovered
            .dispatch(
                "doc.retest.agent.status",
                &json!({"session_id":"choices"}),
                &config,
            )
            .unwrap();
        assert_eq!(status["follow_up"], question);
        assert_eq!(status["can_end_task"], true);
        let ended = recovered
            .dispatch(
                "doc.retest.agent.stop",
                &json!({"session_id":"choices","complete_task":true}),
                &config,
            )
            .unwrap();
        assert_eq!(ended["task_ended"], true);
        assert_eq!(ended["progress"], 100);
        assert_eq!(ended["resume_state"]["canContinue"], false);
        assert!(ended["follow_up"].is_null());
        let resumed = recovered
            .dispatch(
                "doc.retest.agent.message",
                &json!({"session_id":"choices","message":"继续","force_resume":true}),
                &config,
            )
            .unwrap();
        assert_eq!(resumed["task_ended"], true);
        assert_eq!(resumed["running"], false);
        let plain = recovered
            .dispatch(
                "doc.retest.agent.message",
                &json!({"session_id":"choices","message":"继续"}),
                &config,
            )
            .unwrap();
        assert_eq!(plain["task_ended"], true);
        assert_eq!(plain["running"], false);
        fs::remove_dir_all(root).unwrap();
    }
}
