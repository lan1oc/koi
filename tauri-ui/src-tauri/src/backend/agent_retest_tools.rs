//! Session tools shared by the conversational Agent and the retest queue.
use super::*;
use std::collections::BTreeSet;

pub(super) fn catalog() -> Vec<Value> {
    let queue = json!({"type":"object","properties":{"generate_reports":{"type":"boolean"},"use_progress_evidence":{"type":"boolean","description":"true=继续已有进度，false=新一轮AI复测并覆盖旧报告"}}});
    let specs = [
        ("inspect_session_state", "读取会话目标、当前复测轮次、完成证据和下一份通报。", "read", json!({"type":"object","properties":{}})),
        ("list_reports", "完整扫描通报目录，分页列出精确源文件路径、原通报和旧报告关系。use_progress_evidence=false列出全部原通报，不让旧报告跳过新一轮。用offset/limit读取后续页。", "read", json!({"type":"object","properties":{"offset":{"type":"integer"},"limit":{"type":"integer"},"use_progress_evidence":{"type":"boolean"}}})),
        ("read_notice", "读取原通报Word正文、表格、超链接和目标地址。通过source_file、file_name或list_reports序号指定。offset/limit按字符分页，使用next_offset读完整通报。", "read", json!({"type":"object","properties":{"source_file":{"type":"string"},"file_name":{"type":"string"},"file_index":{"type":"integer","minimum":1},"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":24000}}})),
        ("run_retest_queue", "执行AI批量复测：扫描、读取、取证、逐项判定和生成报告。用户要求重新测或覆盖旧报告时必须use_progress_evidence=false；继续本轮时true。新报告成功后原子替换旧报告。", "medium", queue.clone()),
        ("retest_url", "对用户明确给出的URL执行AI取证，无需Word通报；只允许该URL同源。", "medium", json!({"type":"object","properties":{"url":{"type":"string"},"vulnerability_types":{"type":"array","items":{"type":"string"}},"note":{"type":"string"}},"required":["url"]})),
        ("generate_reports", "根据本轮已保存的真实复测结果生成Word报告，可用file_name选择一份；不重新发送目标请求。", "write", json!({"type":"object","properties":{"file_name":{"type":"string"}}})),
        ("delete_reports", "仅在用户明确要求删除旧复测报告时执行；清理目标目录下已生成的报告，保留原通报。覆盖重测应使用run_retest_queue。", "write", json!({"type":"object","properties":{}})),
        ("install_tools", "安装并校验锁定的nmap/ffuf；sqlmap保持原工具ID，使用内置SQL核验。", "external", json!({"type":"object","properties":{"tools":{"type":"array","items":{"type":"string","enum":["nmap","sqlmap","ffuf"]}}}})),
        ("tool_status", "查看nmap/sqlmap/ffuf的实际安装和校验状态。", "read", json!({"type":"object","properties":{}})),
    ];
    specs
        .into_iter()
        .map(|(name, description, risk, parameters)| {
            json!({
                "name":name,"description":description,"risk":risk,"requiresApproval":risk!="read",
                "autoApprovalSupported":true,"workspaceOnly":true,"parameters":parameters
            })
        })
        .collect()
}

pub(super) fn is_retest_operation(name: &str) -> bool {
    matches!(name, "retest_source_file" | "run_retest_queue")
}

pub(super) fn queue_context(queue: Option<&RetestQueueState>) -> Value {
    queue.map(|queue| json!({
        "goal":queue.goal,"generate_reports":queue.generate_reports,"use_progress_evidence":queue.use_progress_evidence,
        "total_reports":queue.plan.source_files.len(),"completed_count":queue.plan.completed_source_files.len(),
        "pending_count":queue.plan.pending_source_files.len(),"next_source_file":queue.plan.next_source_file,
        "pending_source_files":queue.plan.pending_source_files.iter().take(10).collect::<Vec<_>>(),
        "completed_source_files":queue.plan.completed_source_files.iter().rev().take(5).collect::<Vec<_>>(),
        "current_file_checkpoint":queue.plan.current_file_checkpoint.as_ref().map(|value| json!({"source_file":value["source_file"],"stage":value["stage"]}))
        ,"plan":{"next_source_file":queue.plan.next_source_file,"pending_source_files":queue.plan.pending_source_files.iter().take(10).collect::<Vec<_>>()},
        "completion_items":queue.completion_items.iter().rev().take(50).map(|item|json!({"sourceFile":item["sourceFile"],"status":item["status"],"reportPaths":item["reportPaths"]})).collect::<Vec<_>>()
    })).unwrap_or(Value::Null)
}

fn queue_request(
    runtime: &NativeRuntime,
    id: &str,
    target: &str,
    arguments: &Map<String, Value>,
) -> AgentMessageRequest {
    let state = runtime.lock_state();
    let session = state.sessions.get(id);
    let progress = session.is_some_and(|session| session.resume_current_round)
        || arguments
            .get("use_progress_evidence")
            .and_then(model_bool)
            .unwrap_or(true);
    AgentMessageRequest {
        session_id: id.into(),
        target_dir: Some(target.into()),
        use_progress_evidence: progress,
        generate_reports: arguments
            .get("generate_reports")
            .or_else(|| arguments.get("generate_report"))
            .and_then(model_bool)
            .unwrap_or_else(|| {
                session
                    .and_then(|s| s.retest_queue.as_ref())
                    .is_some_and(|q| q.generate_reports)
            }),
        message: session
            .and_then(|s| s.events.iter().rev().find(|e| e["type"] == "message"))
            .and_then(|e| e["content"].as_str())
            .unwrap_or_default()
            .into(),
        force_resume: progress,
        frontend_context: session.map(
            |s| json!({"session":{"targetDir":target,"resumeState":legacy_retest_resume_state(s)}}),
        ),
        ..Default::default()
    }
}

fn selected_source(
    workspace: &Path,
    arguments: &Map<String, Value>,
    sources: &[String],
    next: Option<&str>,
) -> Result<PathBuf, String> {
    let explicit = arguments
        .get("source_file")
        .or_else(|| arguments.get("sourceFile"))
        .and_then(Value::as_str);
    let selected = if let Some(path) = explicit {
        path.to_string()
    } else if let Some(name) = arguments
        .get("file_name")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
    {
        let matches = sources
            .iter()
            .filter(|source| {
                source.as_str() == name
                    || Path::new(source).file_name().and_then(|n| n.to_str()) == Some(name)
            })
            .collect::<Vec<_>>();
        match matches.as_slice() {
            [path] => (*path).clone(),
            [] => return Err("通报文件名未找到，请使用list_reports中的精确路径".into()),
            _ => return Err("多个目录有同名通报，请使用精确路径".into()),
        }
    } else if let Some(index) = arguments.get("file_index").and_then(Value::as_u64) {
        sources
            .get(index.checked_sub(1).ok_or("file_index从1开始")? as usize)
            .ok_or("通报序号超出清单")?
            .clone()
    } else {
        next.ok_or("没有待复测通报，请先list_reports或明确要求新一轮")?
            .into()
    };
    let path = resolve_workspace_path(workspace, &selected)?;
    if !sources
        .iter()
        .any(|source| normalized_path_key(Path::new(source)) == normalized_path_key(&path))
    {
        return Err("所选文件不是扫描清单中的原通报".into());
    }
    Ok(path)
}

pub(super) fn execute(
    runtime: &NativeRuntime,
    id: &str,
    generation: u64,
    workspace_root: &str,
    operation: &OperationState,
) -> Result<String, String> {
    let workspace = if matches!(
        operation.tool_name.as_str(),
        "inspect_session_state" | "tool_status" | "install_tools"
    ) {
        PathBuf::from(workspace_root)
    } else {
        canonical_workspace(workspace_root)?
    };
    let arguments = retest_operation_arguments(operation)?;
    let data_dir = runtime.inner.path.parent().unwrap_or(Path::new("."));
    let value = match operation.tool_name.as_str() {
        "inspect_session_state" => {
            let state = runtime.lock_state();
            let session = state.sessions.get(id).ok_or("会话不存在")?;
            json!({"success":true,"workspaceRoot":workspace,"targetDir":workspace,"workspace_available":workspace.is_dir(),
                "status":session.status,"generate_reports_default":session.retest_queue.as_ref().is_some_and(|q|q.generate_reports),
                "retest_queue":queue_context(session.retest_queue.as_ref()),"resume_state":legacy_retest_resume_state(session)})
        }
        "tool_status" => retest_config::tools_status(&data_dir.join("retest-tools")),
        "install_tools" => {
            super::super::external_tools::ExternalToolManager::new(data_dir.join("retest-tools"))?
                .dispatch(
                "doc.retest.tools.install",
                &json!({"tools":arguments.get("tools").cloned().unwrap_or(json!([]))}),
            )?
        }
        "list_reports" | "read_notice" | "run_retest_queue" => {
            let request = queue_request(runtime, id, &workspace.to_string_lossy(), &arguments);
            let plan = if request.use_progress_evidence {
                retest_agent_state::resumed_round_plan(runtime, &request)
            } else {
                None
            };
            let plan = match plan {
                Some(plan) => plan,
                None => build_retest_resume_plan(&request, &runtime.home_dir)?
                    .ok_or("未选择通报目录")?,
            };
            if operation.tool_name == "list_reports" {
                let offset = arguments.get("offset").and_then(Value::as_u64).unwrap_or(0) as usize;
                let limit = arguments
                    .get("limit")
                    .and_then(Value::as_u64)
                    .unwrap_or(20)
                    .clamp(1, 40) as usize;
                let end = offset.saturating_add(limit).min(plan.source_files.len());
                json!({"success":true,"total_reports":plan.source_files.len(),"offset":offset,"next_offset":(end<plan.source_files.len()).then_some(end),
                    "pending_count":plan.pending_source_files.len(),"next_source_file":plan.next_source_file,"use_progress_evidence":request.use_progress_evidence,
                    "files":plan.source_files.iter().enumerate().skip(offset).take(limit).map(|(index,path)|json!({"file_index":index+1,"source_file":path,"completed":plan.completed_source_files.contains(path)})).collect::<Vec<_>>()})
            } else if operation.tool_name == "read_notice" {
                let path = selected_source(
                    &workspace,
                    &arguments,
                    &plan.source_files,
                    plan.next_source_file.as_deref(),
                )?;
                let text = extract_word_text(&path)?;
                let total = text.chars().count();
                let offset = arguments
                    .get("offset")
                    .and_then(Value::as_u64)
                    .unwrap_or(0)
                    .min(total as u64) as usize;
                let limit = arguments
                    .get("limit")
                    .and_then(Value::as_u64)
                    .unwrap_or(12000)
                    .clamp(1, 24000) as usize;
                let end = offset.saturating_add(limit).min(total);
                json!({"success":true,"source_file":path,"text":text.chars().skip(offset).take(limit).collect::<String>(),"offset":offset,"next_offset":(end<total).then_some(end),"total_chars":total,"truncated":end<total,"urls":extract_http_urls(&text),"source_evidence":native_retest_source_evidence(&path)?})
            } else {
                let first = plan.next_source_file.clone();
                {
                    let mut state = runtime.lock_state();
                    let session = state.sessions.get_mut(id).ok_or("会话不存在")?;
                    if session.generation != generation || session.stopped {
                        return Err("复测已停止".into());
                    }
                    retest_agent_state::start_queue(session, &plan, &request, "");
                    persist_locked(&runtime.inner, &state)?;
                }
                let Some(first) = first else {
                    return Ok(json!({"success":true,"pending_count":0,"summary":"本轮所有源通报已完成；新一轮请use_progress_evidence=false"}).to_string());
                };
                let mut single = operation.clone();
                single.tool_name = "retest_source_file".into();
                single.arguments = json!({"source_file":first,"mode":"ai","generate_report":request.generate_reports});
                return execute_retest_source_file_operation(
                    runtime,
                    id,
                    generation,
                    workspace_root,
                    &single,
                );
            }
        }
        "generate_reports" => {
            let (mut items, overwrite, checkpoint) = {
                let state = runtime.lock_state();
                let session = state.sessions.get(id).ok_or("会话不存在")?;
                let (items, overwrite) = session
                    .retest_queue
                    .as_ref()
                    .map(|queue| (queue.completion_items.clone(), !queue.use_progress_evidence))
                    .unwrap_or_default();
                (items, overwrite, session.resume_snapshot.clone())
            };
            let mut from_checkpoint = None;
            if let Some(checkpoint) = checkpoint.filter(|checkpoint| {
                matches!(
                    checkpoint["stage"].as_str(),
                    Some("result" | "report" | "inconclusive")
                ) && checkpoint["result_data"].is_object()
            }) {
                if let Some(source) = checkpoint["source_file"].as_str() {
                    let source = resolve_workspace_path(&workspace, source)?;
                    let evidence = native_retest_source_evidence(&source)?;
                    if native_retest_snapshot_matches_source(&checkpoint, &source, &evidence)
                        && !items.iter().any(|item| {
                            item["sourceFile"].as_str().is_some_and(|file| {
                                normalized_path_key(Path::new(file)) == normalized_path_key(&source)
                            })
                        })
                    {
                        items.push(json!({"sourceFile":source,"reason":checkpoint["summary"],"result_data":checkpoint["result_data"]}));
                        from_checkpoint = Some(checkpoint);
                    }
                }
            }
            let filter = arguments
                .get("file_name")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let mut reports = Vec::new();
            for item in items {
                let Some(source) = item["sourceFile"].as_str() else {
                    continue;
                };
                if !filter.is_empty()
                    && source != filter
                    && Path::new(source).file_name().and_then(|v| v.to_str()) != Some(filter)
                {
                    continue;
                }
                let source = resolve_workspace_path(&workspace, source)?;
                if !item["result_data"].is_object() {
                    continue;
                }
                if !generation_active(runtime, id, generation) {
                    return Err("报告生成已停止".into());
                }
                let result = retest_reports::dispatch_typed(
                    retest_reports::COMMAND,
                    &json!({"target_dir":workspace,"source_files":[source],"summary":item["reason"],"result_data":item["result_data"],"overwrite_existing":overwrite}),
                    data_dir,
                    &workspace,
                )?;
                if !result.succeeded() {
                    return Err("报告生成失败，原报告已保留".into());
                }
                if let Some(checkpoint) = from_checkpoint.as_ref().filter(|checkpoint| {
                    checkpoint["source_file"].as_str().is_some_and(|file| {
                        normalized_path_key(Path::new(file)) == normalized_path_key(&source)
                    })
                }) {
                    let outcome = NativeRetestOutcome {
                        success: true,
                        stopped: None,
                        message: "根据已保存证据生成报告".into(),
                        source_file: source.to_string_lossy().into_owned(),
                        manual_test_required: checkpoint["result_data"]["manual_test_required"]
                            == true,
                        blocked_by_ai_config: None,
                        blocked_stage: None,
                        blocked_title: None,
                        summary: checkpoint["summary"].as_str().map(str::to_string),
                        result_data: checkpoint["result_data"].clone(),
                        resume_snapshot: checkpoint.clone(),
                        trace_events: Vec::new(),
                        logs: Vec::new(),
                    };
                    retest_agent_state::complete_file(
                        runtime,
                        id,
                        generation,
                        &outcome,
                        result.reports(),
                    )?;
                }
                reports.extend_from_slice(result.reports());
                let mut state = runtime.lock_state();
                let session = state.sessions.get_mut(id).ok_or("会话不存在")?;
                if session.generation != generation || session.stopped {
                    return Err("报告生成已停止".into());
                }
                if let Some(queue) = session.retest_queue.as_mut() {
                    for report in result.reports() {
                        if !queue.reports.contains(report) {
                            queue.reports.push(report.clone());
                        }
                    }
                    if let Some(saved) = queue.completion_items.iter_mut().find(|saved| {
                        saved["sourceFile"].as_str().is_some_and(|path| {
                            normalized_path_key(Path::new(path)) == normalized_path_key(&source)
                        })
                    }) {
                        saved["reportPaths"] = json!(result.reports());
                    }
                }
                persist_locked(&runtime.inner, &state)?;
            }
            if reports.is_empty() {
                return Err("本轮没有已保存的复测结果可生成报告，请先复测通报".into());
            }
            json!({"success":true,"reports":reports})
        }
        "delete_reports" => {
            let state = runtime.lock_state();
            let session = state.sessions.get(id).ok_or("会话不存在")?;
            let instruction = session
                .events
                .iter()
                .rev()
                .find(|e| e["type"] == "message")
                .and_then(|e| e["content"].as_str())
                .unwrap_or_default();
            if !["删除", "清理", "delete"]
                .iter()
                .any(|term| instruction.contains(term))
            {
                return Err("用户尚未明确要求删除报告；重新复测请直接覆盖生成".into());
            }
            drop(state);
            let mut deleted = Vec::new();
            for report in retest::generated_report_files(&workspace) {
                let report = resolve_workspace_path(&workspace, &report.to_string_lossy())?;
                if !generation_active(runtime, id, generation) {
                    return Err("报告清理已停止".into());
                }
                fs::remove_file(&report).map_err(|error| format!("删除报告失败: {error}"))?;
                deleted.push(report);
            }
            let mut state = runtime.lock_state();
            if let Some(queue) = state
                .sessions
                .get_mut(id)
                .and_then(|s| s.retest_queue.as_mut())
            {
                let deleted_keys = deleted
                    .iter()
                    .map(|path| normalized_path_key(path))
                    .collect::<BTreeSet<_>>();
                queue.reports.retain(|report| {
                    !deleted_keys.contains(&normalized_path_key(Path::new(report)))
                });
                queue.plan.disk_report_evidence.clear();
                for item in &mut queue.completion_items {
                    if let Some(paths) = item["reportPaths"].as_array_mut() {
                        paths.retain(|path| {
                            path.as_str().is_none_or(|path| {
                                !deleted_keys.contains(&normalized_path_key(Path::new(path)))
                            })
                        });
                    }
                }
            }
            persist_locked(&runtime.inner, &state)?;
            json!({"success":true,"deleted":deleted})
        }
        "retest_url" => return execute_url(runtime, id, generation, &workspace, &arguments),
        _ => return Err(format!("未注册复测工具: {}", operation.tool_name)),
    };
    serde_json::to_string(&value).map_err(|error| error.to_string())
}

fn execute_url(
    runtime: &NativeRuntime,
    id: &str,
    generation: u64,
    workspace: &Path,
    arguments: &Map<String, Value>,
) -> Result<String, String> {
    let url = arguments
        .get("url")
        .and_then(Value::as_str)
        .ok_or("retest_url需要url")?;
    let authorized = runtime
        .lock_state()
        .sessions
        .get(id)
        .is_some_and(|session| {
            session
                .events
                .iter()
                .filter(|e| e["type"] == "message")
                .any(|event| {
                    extract_http_urls(event["content"].as_str().unwrap_or_default())
                        .iter()
                        .any(|given| given == url)
                })
        });
    if !authorized {
        return Err("retest_url需要用户对话中明确给出的目标URL".into());
    }
    let folder = workspace.join(".koi_retest_staging");
    fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let folder = resolve_workspace_path(workspace, &folder.to_string_lossy())?;
    let text = format!(
        "用户指定的现场核验：{url}\n问题：{}\n说明：{}",
        arguments.get("vulnerability_types").unwrap_or(&Value::Null),
        arguments
            .get("note")
            .and_then(Value::as_str)
            .unwrap_or_default()
    );
    let digest = format!("{:x}", Sha256::digest(format!("{id}\n{text}").as_bytes()));
    let mut path = folder.join(format!("url-{}.docx", &digest[..24]));
    if path.exists() {
        path = resolve_workspace_path(workspace, &path.to_string_lossy())?;
    }
    if !path.exists() {
        let mut zip = zip::ZipWriter::new(File::create(&path).map_err(|e| e.to_string())?);
        zip.start_file(
            "word/document.xml",
            zip::write::SimpleFileOptions::default(),
        )
        .map_err(|e| e.to_string())?;
        write!(zip,"<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:body></w:document>",quick_xml::escape::escape(&text)).map_err(|e|e.to_string())?;
        zip.finish().map_err(|e| e.to_string())?;
    }
    let resume_snapshot = {
        let mut state = runtime.lock_state();
        let session = state.sessions.get_mut(id).ok_or("会话不存在")?;
        if session.generation != generation || session.stopped {
            return Err("URL核验已停止".into());
        }
        let snapshot = session
            .resume_snapshot
            .as_ref()
            .and_then(retest_agent_state::file_checkpoint)
            .filter(|snapshot| {
                snapshot["source_file"].as_str().is_some_and(|source| {
                    normalized_path_key(Path::new(source)) == normalized_path_key(&path)
                })
            })
            .cloned();
        let message = session
            .events
            .iter()
            .rev()
            .find(|event| event["type"] == "message")
            .and_then(|event| event["content"].as_str())
            .unwrap_or("继续URL核验")
            .to_string();
        session.pending_agent_request = Some(AgentMessageRequest {
            session_id: id.into(),
            target_dir: Some(workspace.to_string_lossy().into_owned()),
            message,
            force_resume: true,
            use_progress_evidence: true,
            operation: Some(json!({"name":"retest_url","arguments":arguments})),
            ..Default::default()
        });
        persist_locked(&runtime.inner, &state)?;
        snapshot
    };
    let request = RunOneStartRequest {
        source_file: path.to_string_lossy().into_owned(),
        session_id: id.into(),
        use_ai: true,
        mode: "ai".into(),
        resume_snapshot,
        ..Default::default()
    };
    let result = ai_retest::execute(runtime, None, id, generation, &path, &request, "docx");
    let result = result?;
    if !result.success {
        return Err(result.message);
    }
    let mut state = runtime.lock_state();
    let session = state.sessions.get_mut(id).ok_or("会话不存在")?;
    if session.generation != generation || session.stopped {
        return Err("URL核验已停止".into());
    }
    session.pending_agent_request = None;
    persist_locked(&runtime.inner, &state)?;
    serde_json::to_string(&json!({"success":true,"url":url,"summary":result.summary,"result_data":result.result_data})).map_err(|e|e.to_string())
}

#[cfg(test)]
mod tests {
    use super::super::tests::{configure_model, mock_model_sequence, write_confirmation_fixture};
    use super::*;

    fn fixture(label: &str) -> (PathBuf, PathBuf, ConfigStore, NativeRuntime) {
        let root = std::env::temp_dir().join(format!(
            "koi-agent-tools-{label}-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let workspace = root.join("workspace");
        fs::create_dir_all(&workspace).unwrap();
        let config = ConfigStore::new(root.join("data/config.json"));
        let runtime = NativeRuntime::new(root.join("data"), workspace.clone()).unwrap();
        {
            let mut state = runtime.lock_state();
            let session = ensure_session(
                &mut state,
                "test",
                "retest",
                workspace.to_string_lossy().into_owned(),
            );
            session.generation = 1;
        }
        (root, workspace, config, runtime)
    }

    fn operation(tool: &str, arguments: Value) -> OperationState {
        OperationState {
            id: "test-operation".into(),
            approval_id: None,
            tool_name: tool.into(),
            status: "running".into(),
            risk: "read".into(),
            detail: String::new(),
            arguments,
            continuation_depth: 0,
            generation: 1,
            started_at: now_ms(),
            finished_at: None,
            error: None,
        }
    }

    #[test]
    fn tool_audit_parameters_envelope_executes_read_and_notice_pages_recover_full_text() {
        let (root, workspace, _, runtime) = fixture("audit-envelope-pages");
        fs::write(workspace.join("proof.txt"), "actual read proof").unwrap();
        let (id, _) = {
            let mut state = runtime.lock_state();
            create_operation_locked(
                &mut state,
                "test",
                1,
                &json!({"function":{"name":"read_file","arguments":"{\"path\":\"proof.txt\"}"}}),
                true,
            )
        };
        let read_operation = runtime.lock_state().sessions["test"].operations[&id].clone();
        assert_eq!(read_operation.tool_name, "read_file");
        assert_eq!(
            execute_workspace_operation(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &read_operation
            )
            .unwrap(),
            "actual read proof"
        );
        let source = workspace.join("通报.docx");
        let text = "完整通报原文".repeat(6000);
        write_confirmation_fixture(&source, &text);
        let first: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation("read_notice", json!({"source_file":source,"limit":24000})),
            )
            .unwrap(),
        )
        .unwrap();
        let next = first["next_offset"].as_u64().unwrap();
        let second: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation(
                    "read_notice",
                    json!({"source_file":source,"offset":next,"limit":24000}),
                ),
            )
            .unwrap(),
        )
        .unwrap();
        let combined = format!(
            "{}{}",
            first["text"].as_str().unwrap(),
            second["text"].as_str().unwrap()
        );
        assert!(combined.contains(&text));
        assert!(second["next_offset"].is_null());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn tool_audit_state_and_tool_status_work_when_notice_directory_is_missing() {
        let (root, workspace, _, runtime) = fixture("audit-state-missing");
        fs::remove_dir(&workspace).unwrap();
        let status: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation("inspect_session_state", json!({})),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(status["success"], true);
        assert_eq!(status["workspace_available"], false);
        let tools: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation("tool_status", json!({})),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(tools["success"], true);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn tool_audit_reports_recover_from_saved_verdict_without_retesting_target() {
        let (root, workspace, _, runtime) = fixture("audit-report-checkpoint");
        let source = workspace.join("关于测试存在漏洞的通报.docx");
        write_confirmation_fixture(&source, "原通报未提供目标，需要人工补充");
        let snapshot = native_result_resume_snapshot(
            &source,
            &native_retest_source_evidence(&source).unwrap(),
            "原通报缺少目标，证据不足",
            &json!({"urls":[],"final_verdict":"inconclusive","manual_test_required":true,"manual_count":1,"risk_count":0,"pass_count":0,"summary":"原通报缺少目标，证据不足","retest_results":[]}),
        );
        {
            let mut state = runtime.lock_state();
            state.sessions.get_mut("test").unwrap().resume_snapshot = Some(snapshot);
        }
        let response: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation("generate_reports", json!({})),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(response["success"], true, "{response}");
        assert!(Path::new(response["reports"][0].as_str().unwrap()).is_file());
        assert!(source.is_file());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn python_session_tools_are_advertised_with_native_executors() {
        let names = agent_operation_catalog()
            .iter()
            .filter_map(|spec| spec["name"].as_str().map(str::to_string))
            .collect::<Vec<_>>();
        for name in [
            "inspect_session_state",
            "list_reports",
            "run_retest_queue",
            "retest_url",
            "generate_reports",
            "delete_reports",
            "install_tools",
            "tool_status",
            "workspace_tree",
            "read_file",
            "search_code",
            "inspect_git_diff",
            "summarize_file",
            "run_command",
            "apply_patch",
            "run_tests",
            "build_project",
        ] {
            assert!(
                names.iter().any(|actual| actual == name),
                "missing Python tool {name}"
            );
        }
    }

    #[test]
    fn list_reports_pages_past_workspace_tree_limit_and_read_notice_reads_tables() {
        let (root, workspace, _config, runtime) = fixture("pagination");
        for index in 0..125 {
            write_confirmation_fixture(
                &workspace.join(format!("通报-{index:03}.docx")),
                "验证情况 URL：https://example.test/?q=1&amp;mode=2",
            );
        }
        let mut zip = zip::ZipWriter::new(File::create(workspace.join("通报-124.docx")).unwrap());
        zip.start_file(
            "word/document.xml",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(br#"<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>table-only-evidence https://example.test/?q=1&amp;mode=2</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:hyperlink r:id="rId1"><w:r><w:t>click for original endpoint</w:t></w:r></w:hyperlink></w:p></w:body></w:document>"#).unwrap();
        zip.start_file(
            "word/_rels/document.xml.rels",
            zip::write::SimpleFileOptions::default(),
        )
        .unwrap();
        zip.write_all(br#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" TargetMode="External" Target="https://example.test/hidden-target?x=1&amp;y=2"/></Relationships>"#).unwrap();
        zip.finish().unwrap();
        let output = execute(
            &runtime,
            "test",
            1,
            &workspace.to_string_lossy(),
            &operation(
                "list_reports",
                json!({"offset":120,"limit":20,"use_progress_evidence":false}),
            ),
        )
        .unwrap();
        let result: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(result["total_reports"], 125);
        assert_eq!(result["files"].as_array().unwrap().len(), 5);
        assert!(result["next_offset"].is_null());
        let output = execute(
            &runtime,
            "test",
            1,
            &workspace.to_string_lossy(),
            &operation("read_notice", json!({"file_index":125})),
        )
        .unwrap();
        let result: Value = serde_json::from_str(&output).unwrap();
        assert!(result["text"]
            .as_str()
            .unwrap()
            .contains("table-only-evidence"));
        assert!(result["urls"]
            .as_array()
            .unwrap()
            .iter()
            .any(|url| url == "https://example.test/?q=1&mode=2"));
        assert!(result["urls"]
            .as_array()
            .unwrap()
            .iter()
            .any(|url| url == "https://example.test/hidden-target?x=1&y=2"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn new_ai_round_ignores_old_report_evidence_and_continue_keeps_only_round_completion() {
        let (root, workspace, _config, runtime) = fixture("fresh-round");
        let first = workspace.join("关于甲公司存在漏洞通报.docx");
        let second = workspace.join("关于乙公司存在漏洞通报.docx");
        for source in [&first, &second] {
            write_confirmation_fixture(source, "漏洞核验 URL：https://example.test/");
            write_confirmation_fixture(
                &source.with_file_name(format!(
                    "{}_复测报告.docx",
                    source
                        .file_stem()
                        .unwrap()
                        .to_string_lossy()
                        .trim_end_matches("通报")
                )),
                "此前无AI检查：已修复",
            );
        }
        let request = AgentMessageRequest {
            session_id: "test".into(),
            target_dir: Some(workspace.to_string_lossy().into_owned()),
            use_progress_evidence: false,
            generate_reports: true,
            message: "用AI重新复测，覆盖旧报告".into(),
            ..Default::default()
        };
        let mut plan = build_retest_resume_plan(&request, &workspace)
            .unwrap()
            .unwrap();
        assert_eq!(plan.completed_source_files.len(), 0);
        assert_eq!(plan.pending_source_files.len(), 2);
        assert_eq!(plan.disk_report_evidence.len(), 2);
        let done = plan.pending_source_files.remove(0);
        plan.completed_source_files.push(done.clone());
        plan.next_source_file = plan.pending_source_files.first().cloned();
        plan.next_index = 1;
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("test").unwrap();
            retest_agent_state::start_queue(session, &plan, &request, "");
            session.status = "blocked".into();
            persist_locked(&runtime.inner, &state).unwrap();
        }
        drop(runtime);
        let runtime = NativeRuntime::new(root.join("data"), workspace.clone()).unwrap();
        let resumed = AgentMessageRequest {
            session_id: "test".into(),
            target_dir: Some(workspace.to_string_lossy().into_owned()),
            force_resume: true,
            use_progress_evidence: true,
            ..Default::default()
        };
        let plan = retest_agent_state::resumed_round_plan(&runtime, &resumed).unwrap();
        assert_eq!(plan.completed_source_files, vec![done]);
        assert_eq!(plan.pending_source_files.len(), 1);
        let context = queue_context(runtime.lock_state().sessions["test"].retest_queue.as_ref());
        assert_eq!(context["use_progress_evidence"], false);
        assert_eq!(context["pending_count"], 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn model_transport_continue_retries_saved_user_goal_without_old_queue_skip() {
        let (root, workspace, config, runtime) = fixture("pending-goal");
        let source = workspace.join("通报.docx");
        write_confirmation_fixture(&source, "原通报");
        let original = AgentMessageRequest {
            session_id: "test".into(),
            target_dir: Some(workspace.to_string_lossy().into_owned()),
            use_progress_evidence: false,
            message: "重新用AI复测并覆盖所有报告".into(),
            ..Default::default()
        };
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("test").unwrap();
            session.pending_agent_request = Some(original.clone());
            session.status = "blocked".into();
            persist_locked(&runtime.inner, &state).unwrap();
        }
        let (url, server) =
            mock_model_sequence(vec![json!({"reply":"已恢复新一轮要求","operation":null})]);
        configure_model(&config, &url);
        let response=runtime.dispatch("doc.retest.agent.message",&json!({"session_id":"test","message":"继续","target_dir":workspace,"force_resume":true}),&config).unwrap();
        assert_eq!(
            response["resume_plan"]["pending_source_files"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        let requests = server.join().unwrap();
        let body: Value =
            serde_json::from_str(requests[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        let input: Value =
            serde_json::from_str(body["messages"][1]["content"].as_str().unwrap()).unwrap();
        assert_eq!(input["message"], original.message);
        assert!(runtime.lock_state().sessions["test"]
            .pending_agent_request
            .is_none());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn model_selected_legacy_queue_tool_executes_a_fresh_ai_round_despite_old_reports() {
        let (root, workspace, config, runtime) = fixture("execute-fresh");
        let source = workspace.join("原通报.docx");
        write_confirmation_fixture(&source, "通报没有可访问的目标，需要补充材料");
        let old_report = workspace.join("原_复测报告.docx");
        write_confirmation_fixture(&old_report, "无AI批量复测旧结果");
        let old_bytes = fs::read(&old_report).unwrap();
        let (url, server) = mock_model_sequence(vec![
            json!({"reply":"按用户要求重新AI复测","operation":{"name":"run_retest_queue","arguments":{"use_progress_evidence":false,"generate_reports":false}}}),
            json!({"findings":[{"id":"f1","title":"缺少目标","target_urls":[],"validation_goal":"核验通报目标"}]}),
            json!({"finish":true,"judgements":[{"finding_id":"f1","verdict":"inconclusive","reason":"原通报缺目标","evidence_ids":[],"coverage_complete":false}]}),
            json!({"reply":"本轮AI复测结束，已如实记录证据缺口","operation":null}),
        ]);
        configure_model(&config, &url);
        runtime.dispatch("doc.retest.agent.message",&json!({"session_id":"test","target_dir":workspace,"message":"重新用AI复测","use_progress_evidence":false,"auto_approve":true}),&config).unwrap();
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let status = runtime
                .dispatch(
                    "doc.retest.agent.status",
                    &json!({"session_id":"test"}),
                    &config,
                )
                .unwrap();
            if status["status"] == "completed" && status["running"] == false {
                break;
            }
            assert!(Instant::now() < deadline, "{status}");
            thread::sleep(Duration::from_millis(20));
        }
        let queue = runtime.lock_state().sessions["test"]
            .retest_queue
            .clone()
            .unwrap();
        assert!(!queue.use_progress_evidence);
        assert_eq!(queue.completion_items.len(), 1);
        assert_eq!(
            queue.completion_items[0]["result_data"]["engine"],
            "rust_model_directed_agent"
        );
        assert_eq!(
            fs::read(&old_report).unwrap(),
            old_bytes,
            "old report remains until a new report is generated"
        );
        assert_eq!(server.join().unwrap().len(), 4);
        let generation = runtime.lock_state().sessions["test"].generation;
        let generated: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                generation,
                &workspace.to_string_lossy(),
                &operation("generate_reports", json!({})),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(generated["success"], true);
        assert!(
            !old_report.exists(),
            "stale old completion must be archived after successful replacement"
        );
        let queue = runtime.lock_state().sessions["test"]
            .retest_queue
            .clone()
            .unwrap();
        assert_eq!(queue.reports.len(), 1);
        assert_eq!(
            queue.completion_items[0]["reportPaths"],
            generated["reports"]
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn pre_fix_blocked_session_continue_restores_explicit_ai_rerun_from_user_events() {
        let (root, _workspace, _config, runtime) = fixture("old-blocked");
        let message = "之前无AI的复测报告有误，重新用AI复测，覆盖重写所有的复测报告";
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("test").unwrap();
            session.status = "blocked".into();
            session
                .events
                .push(make_event("message", "User message", message, "info", 1));
        }
        let mut request = AgentMessageRequest {
            session_id: "test".into(),
            force_resume: true,
            use_progress_evidence: true,
            ..Default::default()
        };
        retest_agent_state::restore_pending_request(&runtime, &mut request);
        assert_eq!(request.message, message);
        assert!(!request.use_progress_evidence);
        assert!(!request.force_resume);
        assert!(request.generate_reports);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn continue_current_round_overrides_model_restart_and_reuses_saved_investigation() {
        assert_saved_round_resume(Some(
            json!({"name":"run_retest_queue","arguments":{"use_progress_evidence":false,"generate_reports":true}}),
        ));
    }

    #[test]
    fn continue_judgement_dispatches_saved_file_without_session_replanning() {
        assert_saved_round_resume(None);
    }

    fn assert_saved_round_resume(operation: Option<Value>) {
        let (root, workspace, config, runtime) = fixture("model-restart-on-continue");
        let source = workspace.join("TLS通报.docx");
        write_confirmation_fixture(&source, "通报URL：https://example.test/tls");
        let fresh = AgentMessageRequest {
            session_id: "test".into(),
            target_dir: Some(workspace.to_string_lossy().into_owned()),
            message: "重新用AI复测并覆盖报告".into(),
            use_progress_evidence: false,
            generate_reports: true,
            ..Default::default()
        };
        let plan = build_retest_resume_plan(&fresh, &workspace)
            .unwrap()
            .unwrap();
        let snapshot = json!({"stage":"judgement","source_file":source,
            "source_evidence":native_retest_source_evidence(&source).unwrap(),
            "agent_investigation":{"rounds":4,"requests_used":0,
                "findings":[{"id":"f1","title":"TLS核验","target_urls":["https://example.test/tls"],"validation_goal":"核验原TLS密码套件"}],
                "evidence":[{"id":"e1","finding_id":"f1","tool":"run_tls_probe","call_hash":"saved-tls-gap","success":true,"verification":false,"checked_at":"2026-10-08",
                    "data":{"success":true,"message":"saved-tls-gap"}}],
                "feedback":"需要基于原证据判定缺口","finished":false}});
        {
            let mut state = runtime.lock_state();
            let session = state.sessions.get_mut("test").unwrap();
            retest_agent_state::start_queue(session, &plan, &fresh, "");
            session.resume_snapshot = Some(snapshot.clone());
            session.status = "blocked".into();
            persist_locked(&runtime.inner, &state).unwrap();
        }
        let (url, server) = mock_model_sequence(vec![
            json!({"finish":true,"judgements":[{"finding_id":"f1","verdict":"inconclusive","reason":"原有工具证据尚不能确认TLS修复","evidence_ids":["e1"],"coverage_complete":false}]}),
            json!({"reply":"已复用原证据完成缺口判定并生成报告","operation":null}),
        ]);
        configure_model(&config, &url);
        runtime
            .dispatch(
                "doc.retest.agent.message",
                &json!({"session_id":"test","target_dir":workspace,
            "message":"继续","force_resume":true,"use_progress_evidence":true,"auto_approve":true,"operation":operation}),
                &config,
            )
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let session = runtime.lock_state().sessions["test"].clone();
            if session.status == "completed" && !session.running {
                break;
            }
            assert!(Instant::now() < deadline, "{}", session.message);
            thread::sleep(Duration::from_millis(20));
        }
        let session = runtime.lock_state().sessions["test"].clone();
        let queue = session.retest_queue.as_ref().unwrap();
        assert!(
            !queue.use_progress_evidence,
            "Continue retains the fresh round's identity"
        );
        assert_eq!(queue.completion_items.len(), 1);
        assert_eq!(queue.reports.len(), 1);
        let saved = session.resume_snapshot.as_ref().unwrap();
        assert_eq!(saved["agent_investigation"]["rounds"], 5);
        assert_eq!(
            saved["agent_investigation"]["evidence"][0]["data"]["message"],
            "saved-tls-gap"
        );
        let operation = session
            .operations
            .values()
            .find(|operation| operation.generation == session.generation)
            .unwrap();
        if operation.tool_name == "run_retest_queue" {
            assert_eq!(operation.arguments["use_progress_evidence"], true);
        } else {
            assert_eq!(operation.tool_name, "retest_source_file");
        }
        let requests = server.join().unwrap();
        assert_eq!(requests.len(), 2);
        let body: Value =
            serde_json::from_str(requests[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        let input: Value =
            serde_json::from_str(body["messages"][1]["content"].as_str().unwrap()).unwrap();
        assert_eq!(input["investigation"]["rounds"], 4);
        assert_eq!(input["investigation"]["evidence"][0]["id"], "e1");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn delete_reports_includes_unmatched_and_inconclusive_outputs_and_preserves_sources() {
        let (root, workspace, _config, runtime) = fixture("delete-reports");
        let source = workspace.join("原始通报.docx");
        fs::write(&source, b"source untouched").unwrap();
        for name in [
            "旧_复测报告.docx",
            "旧_复测待核验报告.docx",
            "未匹配复测报告.doc",
        ] {
            fs::write(workspace.join(name), b"old report").unwrap();
        }
        {
            let mut state = runtime.lock_state();
            state
                .sessions
                .get_mut("test")
                .unwrap()
                .events
                .push(make_event(
                    "message",
                    "User message",
                    "删除旧复测报告",
                    "info",
                    1,
                ));
        }
        let value: Value = serde_json::from_str(
            &execute(
                &runtime,
                "test",
                1,
                &workspace.to_string_lossy(),
                &operation("delete_reports", json!({})),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(value["deleted"].as_array().unwrap().len(), 3);
        assert_eq!(fs::read(&source).unwrap(), b"source untouched");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn blocked_url_retest_retains_exact_input_and_restores_the_url_tool_on_continue() {
        let (root, workspace, _config, runtime) = fixture("url-continue");
        {
            let mut state = runtime.lock_state();
            state
                .sessions
                .get_mut("test")
                .unwrap()
                .events
                .push(make_event(
                    "message",
                    "User message",
                    "核验 https://example.test/login",
                    "info",
                    1,
                ));
        }
        let operation = operation(
            "retest_url",
            json!({"url":"https://example.test/login","note":"原始要求"}),
        );
        assert!(execute(
            &runtime,
            "test",
            1,
            &workspace.to_string_lossy(),
            &operation
        )
        .is_err());
        let saved = runtime.lock_state().sessions["test"]
            .pending_agent_request
            .clone()
            .unwrap();
        assert_eq!(saved.operation.as_ref().unwrap()["name"], "retest_url");
        let before = fs::read_dir(workspace.join(".koi_retest_staging"))
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .collect::<Vec<_>>();
        assert_eq!(before.len(), 1);
        assert!(before[0].is_file());
        let mut resumed = AgentMessageRequest {
            session_id: "test".into(),
            message: "继续".into(),
            force_resume: true,
            ..Default::default()
        };
        retest_agent_state::restore_pending_request(&runtime, &mut resumed);
        assert_eq!(resumed.operation, saved.operation);
        assert!(execute(
            &runtime,
            "test",
            1,
            &workspace.to_string_lossy(),
            &operation
        )
        .is_err());
        let after = fs::read_dir(workspace.join(".koi_retest_staging"))
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .collect::<Vec<_>>();
        assert_eq!(after, before);
        fs::remove_dir_all(root).unwrap();
    }
}
