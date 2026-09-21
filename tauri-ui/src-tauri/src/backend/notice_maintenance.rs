//! Conversion and explicit cleanup for the Cyberspace Office page.
use super::*;

#[derive(Debug, Clone, Copy, Deserialize, Default, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(super) enum NoticeMaintenanceAction {
    #[default]
    Convert,
    PreviewCleanup,
    Cleanup,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub(super) struct CleanupFile {
    pub(super) file: String,
    pub(super) size: u64,
    pub(super) sha256: String,
}

#[derive(Serialize)]
struct MaintenanceFailure {
    file: String,
    reason: String,
}

#[derive(Default, Serialize)]
pub(super) struct MaintenanceResponse {
    success: bool,
    message: String,
    converted: usize,
    skipped: usize,
    output_files: Vec<String>,
    deleted_files: Vec<String>,
    cleanup_files: Vec<CleanupFile>,
    failures: Vec<MaintenanceFailure>,
    logs: Vec<String>,
}

impl MaintenanceResponse {
    fn fail(&mut self, file: &Path, reason: impl Into<String>) {
        self.failures.push(MaintenanceFailure {
            file: file.to_string_lossy().into_owned(),
            reason: reason.into(),
        });
    }
}

// Reserve the directory in the same registry as "Start processing", including
// parent/child overlap. The reservation lasts through conversion or deletion.
struct MaintenanceGuard(String);
impl Drop for MaintenanceGuard {
    fn drop(&mut self) {
        if let Ok(mut tasks) = notice_tasks().lock() {
            tasks.remove(&self.0);
        }
    }
}

fn reserve_directory(root: &Path) -> Result<MaintenanceGuard, String> {
    let key = root.to_string_lossy().to_ascii_lowercase();
    let mut tasks = notice_tasks().lock().map_err(|_| "通报任务状态不可用")?;
    if active_notice_task_locked(&tasks, &key, None).is_some() {
        return Err("该目录或其子目录仍有通报任务运行，暂不能转换或清理".into());
    }
    let task_id = format!(
        "notice-maintenance-{}",
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    );
    tasks.insert(
        task_id.clone(),
        NoticeTask {
            task_id: task_id.clone(),
            generation: 1,
            target_path: root.to_string_lossy().into_owned(),
            target_key: key,
            running: true,
            done: false,
            success: false,
            progress: 0,
            message: "正在转换或清理通报文件".into(),
            logs: Vec::new(),
            result: None,
            error: None,
            created_at: now_seconds(),
            finished_at: None,
        },
    );
    Ok(MaintenanceGuard(task_id))
}

pub(super) fn dispatch(request: NoticeRequest) -> Result<Value, String> {
    let root = canonical_dir(Path::new(request.required_target_path()?))?;
    let _guard = reserve_directory(&root)?;
    let response = match request.action {
        NoticeMaintenanceAction::Convert => {
            if matches!(request.failed_files, FailedFilesField::Invalid) {
                return Ok(
                    json!({"success":false,"message":"失败文件列表格式无效","error_code":"invalid_failed_files","logs":[]}),
                );
            }
            let mut logs = Vec::new();
            finalize_notice_names_in_tree(&root, &mut logs)?;
            let sources = collect_candidates(&root, &request, &mut logs)?;
            convert_candidates(&sources, logs, |source, output| {
                convert_notice_word_to_pdf(source, output).map(|_| ())
            })?
        }
        NoticeMaintenanceAction::PreviewCleanup => cleanup_plan(&root)?,
        NoticeMaintenanceAction::Cleanup => execute_cleanup(&root, &request.cleanup_files)?,
    };
    serde_json::to_value(response).map_err(|error| error.to_string())
}

fn eligible_word(path: &Path, explicit: bool) -> bool {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default();
    if notice_file_kind(path) != Some("word")
        || name.starts_with(['.', '~'])
        || name.contains("模板")
        || path
            .components()
            .any(|part| part.as_os_str() == "Report_Template")
        || [".clean_backup.", ".final_backup.", ".backup.", ".temp."]
            .iter()
            .any(|part| name.contains(part))
    {
        return false;
    }
    if explicit {
        return true;
    }
    if name.starts_with(|ch: char| ch.is_ascii_digit())
        && !docx_path_has_current_rewrite_marker(path)
    {
        return false;
    }
    notice_name_candidate(path)
        || filename_has_notice_issue(name)
        || docx_path_has_current_rewrite_marker(path)
}

pub(super) fn collect_candidates(
    root: &Path,
    request: &NoticeRequest,
    logs: &mut Vec<String>,
) -> Result<Vec<PathBuf>, String> {
    let files = walk_files(root)?;
    let mut candidates = BTreeSet::new();
    if let FailedFilesField::Items(items) = &request.failed_files {
        for item in items {
            let raw = match item {
                FailedFileEntry::Path(value) => PathBuf::from(value),
                FailedFileEntry::MissingPath => return Err("失败文件缺少路径".into()),
                FailedFileEntry::Invalid => return Err("失败文件列表格式无效".into()),
            };
            let source = if raw.is_absolute() {
                raw
            } else {
                root.join(raw)
            };
            if source.is_file() {
                let actual = path_under(root, &source)?;
                if eligible_word(&actual, true) {
                    candidates.insert(actual);
                }
                continue;
            }
            let matches = files
                .iter()
                .filter(|path| path.file_name() == source.file_name() && eligible_word(path, true))
                .collect::<Vec<_>>();
            let company_matches = matches
                .iter()
                .copied()
                .filter(|path| {
                    path.parent().and_then(Path::file_name)
                        == source.parent().and_then(Path::file_name)
                })
                .collect::<Vec<_>>();
            let matches = if company_matches.is_empty() {
                matches
            } else {
                company_matches
            };
            if matches.len() == 1 {
                logs.push(format!(
                    "已重新定位分类后的Word文件: {} -> {}",
                    source.display(),
                    matches[0].display()
                ));
                candidates.insert(matches[0].clone());
            } else if matches.len() > 1 {
                logs.push(format!(
                    "分类后存在多个同名Word文件，无法确定目标: {}",
                    source.display()
                ));
            } else {
                logs.push(format!(
                    "失败列表中的Word文件已不存在: {}",
                    source.display()
                ));
            }
        }
    }
    if request
        .scan_target
        .unwrap_or(matches!(request.failed_files, FailedFilesField::Missing))
    {
        candidates.extend(files.into_iter().filter(|path| eligible_word(path, false)));
    }
    logs.push(format!(
        "找到 {} 个可转换Word文件（排除模板、备份和未完成工作副本）",
        candidates.len()
    ));
    Ok(candidates.into_iter().collect())
}

fn record_conversion(source: &Path, output: &Path, source_hash: &str) -> Result<(), String> {
    let Some(work_dir) = source.parent() else {
        return Ok(());
    };
    let Some(mut state) = load_notice_state(work_dir)? else {
        return Ok(());
    };
    let Some(items) = state
        .compatibility_fields
        .get_mut("rewrite_items")
        .and_then(Value::as_array_mut)
    else {
        return Ok(());
    };
    let mut changed = false;
    for item in items {
        if item["artifact"].as_str() == source.file_name().and_then(|name| name.to_str())
            && (item["artifact_sha256"]
                .as_str()
                .is_some_and(|hash| hash.eq_ignore_ascii_case(source_hash))
                || item["source"]["sha256"]
                    .as_str()
                    .is_some_and(|hash| notice_artifact_has_source_hash(source, hash)))
        {
            item["artifact_sha256"] = json!(source_hash);
            item["converted_pdf"] = json!(output.file_name().and_then(|name| name.to_str()));
            item["converted_pdf_sha256"] = json!(file_sha256(output)?);
            changed = true;
        }
    }
    if changed {
        let source_text = source.to_string_lossy();
        state
            .generated_files
            .retain(|path| path != source_text.as_ref());
        state.artifacts.retain(|path| path != source_text.as_ref());
        let output_text = output.to_string_lossy().into_owned();
        if !state.pdf_outputs.contains(&output_text) {
            state.pdf_outputs.push(output_text);
        }
        save_notice_state(work_dir, &state)?;
    }
    Ok(())
}

pub(super) fn convert_candidates(
    sources: &[PathBuf],
    logs: Vec<String>,
    mut convert: impl FnMut(&Path, &Path) -> Result<(), String>,
) -> Result<MaintenanceResponse, String> {
    let mut response = MaintenanceResponse {
        logs,
        ..Default::default()
    };
    if sources.is_empty() {
        response.message = "未找到可转换的Word文档".into();
        return Ok(response);
    }
    for source in sources {
        let output = source.with_extension("pdf");
        let result = (|| {
            let (_, before) = managed_source_fingerprint(source)?;
            // Always convert this Word revision. A readable old PDF does not
            // prove that the current source can safely be deleted.
            convert(source, &output)?;
            read_pdf(&output)?;
            let (_, after) = managed_source_fingerprint(source)?;
            if after != before {
                return Err("转换期间Word已被修改，保留原文件".into());
            }
            record_conversion(source, &output, &before)?;
            fs::remove_file(source).map_err(|error| format!("PDF已生成但删除Word失败: {error}"))?;
            Ok::<(), String>(())
        })();
        match result {
            Ok(()) => {
                response
                    .output_files
                    .push(output.to_string_lossy().into_owned());
                response
                    .deleted_files
                    .push(source.to_string_lossy().into_owned());
                response.logs.push(format!(
                    "PDF转换并校验成功，已删除对应Word: {}",
                    source.display()
                ));
            }
            Err(error) => {
                response.logs.push(format!(
                    "转换失败 {}: {error}；已保留Word",
                    source.display()
                ));
                response.fail(source, error);
            }
        }
    }
    response.converted = response.output_files.len();
    response.success = response.failures.is_empty() && response.converted > 0;
    response.message = format!(
        "转换完成：成功 {}，失败 {}，删除原Word {} 个",
        response.converted,
        response.failures.len(),
        response.deleted_files.len()
    );
    Ok(response)
}

pub(super) fn valid_completed_outputs(work_dir: &Path, state: &NoticeState) -> bool {
    state.completed
        && state.stages.all()
        && !state.pdf_outputs.is_empty()
        && state.pdf_outputs.iter().all(|path| {
            path_under(work_dir, Path::new(path)).is_ok_and(|path| read_pdf(&path).is_ok())
        })
        && state
            .compatibility_fields
            .get("rewrite_items")
            .and_then(Value::as_array)
            .is_some_and(|items| {
                !items.is_empty()
                    && items.iter().all(|item| {
                        rewrite_item_is_verified(item, work_dir)
                            || item["artifact"]
                                .as_str()
                                .filter(|name| safe_notice_component(name))
                                .zip(item["source"]["sha256"].as_str())
                                .is_some_and(|(name, hash)| {
                                    let artifact = work_dir.join(name);
                                    valid_docx_package(&artifact)
                                        && notice_artifact_has_source_hash(&artifact, hash)
                                })
                            || item["converted_pdf"]
                                .as_str()
                                .filter(|name| safe_notice_component(name))
                                .zip(item["converted_pdf_sha256"].as_str())
                                .is_some_and(|(name, hash)| {
                                    let path = work_dir.join(name);
                                    read_pdf(&path).is_ok()
                                        && file_sha256(&path)
                                            .is_ok_and(|actual| actual.eq_ignore_ascii_case(hash))
                                })
                    })
            })
}

fn cleanup_file(path: &Path) -> Result<CleanupFile, String> {
    let (size, sha256) = managed_source_fingerprint(path)?;
    Ok(CleanupFile {
        file: path.to_string_lossy().into_owned(),
        size,
        sha256,
    })
}

fn cleanup_plan(root: &Path) -> Result<MaintenanceResponse, String> {
    let files = walk_files(root)?;
    let mut response = MaintenanceResponse::default();
    let mut candidates = BTreeSet::new();
    for state_file in files
        .iter()
        .filter(|path| path.file_name().and_then(|name| name.to_str()) == Some(NOTICE_STATE_FILE))
    {
        let work_dir = state_file.parent().expect("state parent");
        let state = match load_notice_state(work_dir) {
            Ok(Some(state)) => state,
            Ok(None) => continue,
            Err(error) => {
                response.fail(state_file, error);
                continue;
            }
        };
        if !valid_completed_outputs(work_dir, &state) {
            response.fail(
                state_file,
                "任务未全部完成或正式产物未通过校验，保留断点和原件备份",
            );
            continue;
        }
        candidates.insert(state_file.clone());
        for record in managed_notice_sources(&state) {
            for path in [
                safe_managed_backup_path(work_dir, &record.backup_name),
                safe_managed_source_path(work_dir, &record.work_name),
            ]
            .into_iter()
            .flatten()
            .filter(|path| path.is_file())
            {
                let (size, hash) = managed_source_fingerprint(&path)?;
                if size == record.size && hash.eq_ignore_ascii_case(&record.sha256) {
                    candidates.insert(path);
                } else {
                    response.fail(&path, "过程文件已被修改，保留文件");
                }
            }
        }
    }
    // Orphaned hash-named backups are disposable only if the matching v2
    // notice still exists. An unrecognized hidden file is never a candidate.
    for backup in &files {
        let Some(work_dir) = backup.parent() else {
            continue;
        };
        let Some(name) = backup.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if safe_managed_backup_path(work_dir, name).is_none()
            || state_path(work_dir).exists()
            || candidates.contains(backup)
        {
            continue;
        }
        let digest = name
            .trim_start_matches(NOTICE_ORIGINAL_BACKUP_PREFIX)
            .trim_end_matches(".docx");
        if file_sha256(backup).is_ok_and(|actual| actual.eq_ignore_ascii_case(digest))
            && files.iter().any(|artifact| {
                artifact.parent() == Some(work_dir)
                    && artifact != backup
                    && notice_artifact_matches_source(artifact, backup)
            })
        {
            candidates.insert(backup.clone());
        }
    }
    response.cleanup_files = candidates
        .iter()
        .map(|path| cleanup_file(path))
        .collect::<Result<_, _>>()?;
    response.success = true;
    response.message = format!(
        "发现 {} 个可删除过程文件，{} 项需保留",
        response.cleanup_files.len(),
        response.failures.len()
    );
    Ok(response)
}

fn execute_cleanup(root: &Path, selected: &[CleanupFile]) -> Result<MaintenanceResponse, String> {
    if selected.is_empty() {
        return Err("请先预览并选择要删除的过程文件".into());
    }
    let plan = cleanup_plan(root)?;
    for selected in selected {
        if !plan.cleanup_files.contains(selected) {
            return Err(format!(
                "清理列表或文件内容已变化，请重新预览: {}",
                selected.file
            ));
        }
        path_under(root, Path::new(&selected.file))?;
    }
    let mut response = MaintenanceResponse::default();
    finalize_notice_names_in_tree(root, &mut response.logs)?;
    let current = cleanup_plan(root)?;
    let selected_paths = selected
        .iter()
        .map(|file| file.file.as_str())
        .collect::<BTreeSet<_>>();
    let mut files = current
        .cleanup_files
        .into_iter()
        .filter(|file| selected_paths.contains(file.file.as_str()))
        .collect::<Vec<_>>();
    // Delete checkpoint last, keeping recovery evidence if an earlier delete
    // fails. Recheck every file against the plan immediately before deletion.
    files.sort_by_key(|file| {
        Path::new(&file.file)
            .file_name()
            .and_then(|name| name.to_str())
            == Some(NOTICE_STATE_FILE)
    });
    for file in files {
        let path = Path::new(&file.file);
        if path.file_name().and_then(|name| name.to_str()) == Some(NOTICE_STATE_FILE)
            && !response.failures.is_empty()
        {
            response.fail(path, "有过程文件删除失败，保留断点以便重试");
            continue;
        }
        let result = (|| {
            path_under(root, path)?;
            if cleanup_file(path)? != file {
                return Err("文件已变化，请重新预览".into());
            }
            fs::remove_file(path).map_err(|error| format!("删除失败: {error}"))
        })();
        match result {
            Ok(()) => {
                response.deleted_files.push(file.file.clone());
                response.logs.push(format!("已删除过程文件: {}", file.file));
            }
            Err(error) => response.fail(path, error),
        }
    }
    response.success = response.failures.is_empty();
    response.output_files = walk_files(root)?
        .into_iter()
        .filter(|path| docx_path_has_current_rewrite_marker(path))
        .map(|path| path.to_string_lossy().into_owned())
        .collect();
    response.message = format!(
        "清理完成：删除 {} 个过程文件，失败 {} 个",
        response.deleted_files.len(),
        response.failures.len()
    );
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cleanup_rejects_running_parent_and_child_tasks() {
        let root = std::env::temp_dir().join(format!(
            "koi-maintenance-lock-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(root.join("child")).unwrap();
        let root = canonical_dir(&root).unwrap();
        let child = root.join("child");
        let guard = reserve_directory(&root).unwrap();
        assert!(dispatch(NoticeRequest {
            target_path: Some(child.to_string_lossy().into_owned()),
            action: NoticeMaintenanceAction::PreviewCleanup,
            ..Default::default()
        })
        .is_err());
        drop(guard);
        let guard = reserve_directory(&child).unwrap();
        assert!(dispatch(NoticeRequest {
            target_path: Some(root.to_string_lossy().into_owned()),
            action: NoticeMaintenanceAction::Cleanup,
            ..Default::default()
        })
        .is_err());
        drop(guard);
        assert!(dispatch(NoticeRequest {
            target_path: Some(root.to_string_lossy().into_owned()),
            action: NoticeMaintenanceAction::PreviewCleanup,
            ..Default::default()
        })
        .is_ok());
        fs::remove_dir_all(root).unwrap();
    }
}
