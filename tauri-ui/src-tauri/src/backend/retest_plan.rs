//! Model-authored per-notice plans; execution status comes from actual tools.
use super::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(super) struct PlanStep {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub finding_ids: Vec<String>,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default)]
    pub purpose: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub evidence_ids: Vec<String>,
}

pub(super) fn update(state: &mut Investigation, proposed: Vec<PlanStep>, secret: &str) {
    for mut step in proposed.into_iter().take(24) {
        if step.id.trim().is_empty()
            || step.id.len() > 80
            || step.title.trim().is_empty()
            || step.finding_ids.len() > 24
            || step.tools.len() > 8
            || step
                .finding_ids
                .iter()
                .any(|id| !state.findings.iter().any(|finding| finding.id == *id))
            || step.tools.iter().any(|tool| {
                !investigation_catalog()
                    .iter()
                    .any(|spec| spec["name"] == *tool)
            })
        {
            continue;
        }
        step.title = truncate(&redact_agent_text(&step.title, secret), 160);
        step.purpose = truncate(&redact_agent_text(&step.purpose, secret), 600);
        // The model describes its intent. It cannot mark an unexecuted step done.
        step.status = "pending".into();
        step.evidence_ids.clear();
        if let Some(existing) = state
            .steps
            .iter_mut()
            .find(|existing| existing.id == step.id)
        {
            if existing.evidence_ids.is_empty() {
                *existing = step;
            }
        } else if state.steps.len() < 24 {
            state.steps.push(step);
        }
    }
}

pub(super) fn start(steps: &mut [PlanStep], call: &ToolCall) -> Option<usize> {
    let explicit = call.arguments["plan_step_id"].as_str();
    let matches = |step: &PlanStep| {
        (step.finding_ids.is_empty() || step.finding_ids.contains(&call.finding_id))
            && step.tools.contains(&call.tool)
    };
    let index = explicit
        .and_then(|id| steps.iter().position(|step| step.id == id && matches(step)))
        .or_else(|| {
            steps
                .iter()
                .position(|step| matches(step) && step.status != "completed")
        })?;
    steps[index].status = "running".into();
    Some(index)
}

pub(super) fn observe(steps: &mut [PlanStep], index: Option<usize>, id: &str, success: bool) {
    if let Some(step) = index.and_then(|index| steps.get_mut(index)) {
        step.status = if success { "completed" } else { "failed" }.into();
        step.evidence_ids.push(id.into());
    }
}

pub(super) fn view(source: &Path, state: &Investigation) -> Value {
    let steps = if state.steps.is_empty() {
        state.findings.iter().map(|finding| {
            let verdict = state.judgements.iter().find(|judgement| judgement.finding_id == finding.id);
            json!({"id":format!("finding-{}",finding.id),"title":finding.title,"purpose":finding.validation_goal,
                "tools":[],"finding_ids":[finding.id],"status":if let Some(verdict)=verdict {if verdict.verdict=="inconclusive" {"inconclusive"}else{"completed"}}else{"pending"},
                "evidence_ids":state.evidence.iter().filter(|evidence|evidence.finding_id==finding.id).map(|evidence|&evidence.id).collect::<Vec<_>>()})
        }).collect::<Vec<_>>()
    } else {
        state
            .steps
            .iter()
            .map(|step| {
                let mut view = serde_json::to_value(step).unwrap_or(Value::Null);
                if state.finished && !matches!(step.status.as_str(), "completed" | "failed") {
                    view["status"] = json!("inconclusive");
                }
                view
            })
            .collect()
    };
    let phase = if !state.phase.is_empty() {
        state.phase.as_str()
    } else if state.finished {
        "judging"
    } else if !state.evidence.is_empty() {
        "investigating"
    } else if !state.findings.is_empty() {
        "planning"
    } else {
        "reading"
    };
    json!({"sourceFile":source,"sourceFileName":source.file_name().map(|name|name.to_string_lossy()),"phase":phase,
        "action":state.action,"steps":steps,"findings":state.findings,"finished":state.finished,
        "modelRequest":state.model_request,"rounds":state.rounds,"evidenceCount":state.evidence.len()})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_completion_requires_actual_tool_result_and_survives_resume() {
        let mut state = Investigation::default();
        state.findings.push(FindingPlan {
            id: "f1".into(),
            title: "通报问题".into(),
            target_urls: vec!["http://example.test".into()],
            validation_goal: "复核原PoC".into(),
        });
        let proposed=serde_json::from_value(json!({"id":"s1","title":"读取原PoC并核对接口","finding_ids":["f1"],"tools":["read_notice"],"purpose":"复核原通报","status":"completed","evidence_ids":["invented"]})).unwrap();
        update(&mut state, vec![proposed], "");
        assert_eq!(state.steps[0].status, "pending");
        assert!(state.steps[0].evidence_ids.is_empty());
        let call = ToolCall {
            finding_id: "f1".into(),
            tool: "read_notice".into(),
            arguments: json!({"plan_step_id":"s1"}),
        };
        let index = start(&mut state.steps, &call);
        assert_eq!(state.steps[0].status, "running");
        observe(&mut state.steps, index, "e1", false);
        assert_eq!(state.steps[0].status, "failed");
        let index = start(&mut state.steps, &call);
        observe(&mut state.steps, index, "e2", true);
        let restored: Investigation =
            serde_json::from_value(serde_json::to_value(&state).unwrap()).unwrap();
        assert_eq!(restored.steps[0].status, "completed");
        assert_eq!(restored.steps[0].evidence_ids, vec!["e1", "e2"]);
        let view = view(Path::new("通报.docx"), &restored);
        assert_eq!(view["steps"][0]["purpose"], "复核原通报");
        assert_eq!(view["steps"][0]["status"], "completed");
    }
}
