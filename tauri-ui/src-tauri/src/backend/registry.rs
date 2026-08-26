use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

const BUNDLED_CONTRACT: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/backend-commands.json"
));
const RUST_HANDLER_SOURCE: &str = "tauri-ui/src-tauri/src/backend/registry.rs";

/// The implementation inventory is deliberately kept next to the dispatcher
/// contract.  It is the authoritative list of commands which have a native
/// Rust handler today; the JavaScript verifier reads the marked block below so
/// that a migration check cannot accidentally claim that an unimplemented
/// command has already moved to Rust.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RustHandlerKind {
    Direct,
    Alias(&'static str),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RustHandlerSpec {
    pub name: &'static str,
    pub kind: RustHandlerKind,
}

// CONTRACT_RUST_HANDLERS_BEGIN
pub const RUST_HANDLER_SPECS: &[RustHandlerSpec] = &[
    RustHandlerSpec {
        name: "app.version",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "config.load",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "config.set_dark_mode",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "fs.roots",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "fs.list_dir",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "fs.path_info",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "weekly_report.config.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "weekly_report.config.set",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "weekly_report.generate",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.field_extract.headers",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.field_extract.run",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.filling.preview",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.filling.run",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.filling.auto_map",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.filling.custom_map",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.template.create",
        kind: RustHandlerKind::Alias("data.templates.create"),
    },
    RustHandlerSpec {
        name: "data.template.save",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.list",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.create",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.update",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.delete",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.import",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "data.templates.export",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.config.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.config.set",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.tyc.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.aiqicha.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.asset.syntax_doc",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.asset.fofa.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.asset.hunter.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.asset.quake.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.asset.unified.query",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.group.add",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.group.rename",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.group.delete",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.company.add",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.company.rename",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.company.delete",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.enterprise.classification.company.move",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.config.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.config.set",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.ip",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.ip.batch",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.dns",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.file_report",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.file_multiengines",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.file_upload",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.threatbook.test_connection",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "info.export_text",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "fs.open_path",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "fs.open_url",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.convert.run",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.pdf_extract.preview",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.pdf_extract.run",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.pdf_extract.compress",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.classify",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.process",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.process.start",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.process.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.counters.save",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.notice.convert_failed_pdf",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.open_path",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.list_files",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.event_stream.info",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.session.compact",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.agent_chat",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.message",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.stop",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.approval.respond",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.auto_approval.set",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.auto_approval.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.operation.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.operation.stop",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.agent.tools",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.run",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.run_one",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.run_one.start",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.run_one.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.run_one.stop",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.confirmation.respond",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.agent.start",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.agent.message",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.agent.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.agent.stop",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.open_output",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.ai_config.get",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.ai_config.set",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.ai_config.test",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.ai_config.key_status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.tools.list",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.tools.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.tools.install",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.tools.install.status",
        kind: RustHandlerKind::Direct,
    },
    RustHandlerSpec {
        name: "doc.retest.generate_reports_with_screenshot",
        kind: RustHandlerKind::Direct,
    },
];
// CONTRACT_RUST_HANDLERS_END

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommandOwner {
    Rust,
    Python,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommandChannel {
    RustConcurrent,
    PythonSerial,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandSpec {
    pub name: String,
    pub owner: CommandOwner,
    pub channel: CommandChannel,
    #[serde(rename = "timeoutMs")]
    pub timeout_ms: u64,
}

#[derive(Debug, Deserialize)]
struct CommandContract {
    #[serde(rename = "schemaVersion")]
    schema_version: u32,
    #[serde(default, rename = "rustHandlerSource")]
    rust_handler_source: Option<String>,
    commands: Vec<CommandSpec>,
}

#[derive(Debug, Clone)]
pub struct CommandRegistry {
    ordered: Vec<CommandSpec>,
    by_name: HashMap<String, usize>,
}

impl CommandRegistry {
    #[allow(dead_code)]
    pub fn bundled() -> Result<Self, String> {
        Self::from_json(BUNDLED_CONTRACT)
    }

    /// Load the bundled contract and enforce the Rust-only production gate.
    ///
    /// Strict mode requires every contract command to have a native handler and
    /// rejects every Python owner. The non-strict parser is retained for isolated
    /// contract-fixture tests only.
    #[allow(dead_code)]
    pub fn bundled_strict() -> Result<Self, String> {
        let registry = Self::from_json(BUNDLED_CONTRACT)?;
        registry.validate_rust_handlers(true)?;
        let python_owners = registry
            .ordered
            .iter()
            .filter(|spec| spec.owner == CommandOwner::Python)
            .map(|spec| spec.name.as_str())
            .collect::<Vec<_>>();
        if !python_owners.is_empty() {
            return Err(format!(
                "production requires 97/97 Rust command owners; Python owners remain: {}",
                python_owners.join(", ")
            ));
        }
        Ok(registry)
    }

    pub fn from_json(raw: &str) -> Result<Self, String> {
        let contract: CommandContract =
            serde_json::from_str(raw).map_err(|error| format!("命令契约解析失败: {error}"))?;
        if contract.schema_version != 1 {
            return Err(format!("不支持的命令契约版本: {}", contract.schema_version));
        }
        if contract.commands.is_empty() {
            return Err("命令契约不能为空".to_string());
        }

        if let Some(source) = contract.rust_handler_source.as_deref() {
            if source.trim() != RUST_HANDLER_SOURCE
                || source.contains("..")
                || source.starts_with('/')
            {
                return Err("Rust handler source path is invalid".to_string());
            }
        }

        let mut by_name = HashMap::with_capacity(contract.commands.len());
        let mut seen = HashSet::with_capacity(contract.commands.len());
        for (index, spec) in contract.commands.iter().enumerate() {
            if spec.name.trim().is_empty() {
                return Err(format!("命令契约第 {} 项名称为空", index + 1));
            }
            if !seen.insert(spec.name.as_str()) {
                return Err(format!("命令契约包含重复命令: {}", spec.name));
            }
            if spec.timeout_ms == 0 {
                return Err(format!("命令超时必须大于 0: {}", spec.name));
            }
            match (spec.owner, spec.channel) {
                (CommandOwner::Rust, CommandChannel::RustConcurrent)
                | (CommandOwner::Python, CommandChannel::PythonSerial) => {}
                _ => return Err(format!("命令 owner/channel 不匹配: {}", spec.name)),
            }
            by_name.insert(spec.name.clone(), index);
        }

        Ok(Self {
            ordered: contract.commands,
            by_name,
        })
    }

    #[allow(dead_code)]
    pub fn rust_handler_specs() -> &'static [RustHandlerSpec] {
        RUST_HANDLER_SPECS
    }

    pub fn has_rust_handler(name: &str) -> bool {
        RUST_HANDLER_SPECS.iter().any(|spec| spec.name == name)
    }

    /// Verify that the contract and the native implementation inventory agree.
    ///
    /// This inventory check is intentionally asymmetric for fixture parsing:
    /// * every actual Rust handler must have a contract entry;
    /// * every `owner: rust` entry must have an actual handler;
    /// * strict inventory mode additionally forbids a known Rust handler from
    ///   retaining `owner: python`.
    pub fn validate_rust_handlers(&self, strict: bool) -> Result<(), String> {
        let mut errors = Vec::new();
        let mut seen_handlers = HashSet::with_capacity(RUST_HANDLER_SPECS.len());

        for handler in RUST_HANDLER_SPECS {
            if !seen_handlers.insert(handler.name) {
                errors.push(format!("重复的 Rust handler 元数据: {}", handler.name));
                continue;
            }
            if let RustHandlerKind::Alias(target) = handler.kind {
                if !RUST_HANDLER_SPECS
                    .iter()
                    .any(|candidate| candidate.name == target)
                {
                    errors.push(format!(
                        "Rust handler alias target not registered: {} -> {}",
                        handler.name, target
                    ));
                }
            }
            match self.get(handler.name) {
                None => errors.push(format!("Rust handler 未登记在命令契约中: {}", handler.name)),
                Some(spec) if strict && spec.owner == CommandOwner::Python => errors.push(format!(
                    "生产 strict 模式禁止 Rust handler 使用 Python owner: {}",
                    handler.name
                )),
                Some(_) => {}
            }
        }

        for spec in &self.ordered {
            if spec.owner == CommandOwner::Rust && !Self::has_rust_handler(&spec.name) {
                errors.push(format!(
                    "命令契约声明 Rust owner 但没有 Rust handler: {}",
                    spec.name
                ));
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors.join("; "))
        }
    }

    pub fn get(&self, name: &str) -> Option<&CommandSpec> {
        self.by_name.get(name).map(|index| &self.ordered[*index])
    }

    #[allow(dead_code)]
    pub fn iter(&self) -> impl Iterator<Item = &CommandSpec> {
        self.ordered.iter()
    }

    #[allow(dead_code)]
    pub fn len(&self) -> usize {
        self.ordered.len()
    }

    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.ordered.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_duplicate_names() {
        let raw = r#"{
            "schemaVersion": 1,
            "commands": [
                {"name":"same","owner":"rust","channel":"rust_concurrent","timeoutMs":1},
                {"name":"same","owner":"rust","channel":"rust_concurrent","timeoutMs":1}
            ]
        }"#;
        let error = CommandRegistry::from_json(raw).expect_err("duplicate must fail");
        assert!(error.contains("重复命令"));
    }

    #[test]
    fn bundled_contract_matches_native_handler_inventory() {
        let registry = CommandRegistry::bundled().expect("load bundled contract");
        registry
            .validate_rust_handlers(false)
            .expect("all native handlers must be represented by the contract");
        assert_eq!(
            registry
                .iter()
                .filter(|spec| spec.owner == CommandOwner::Rust)
                .count(),
            RUST_HANDLER_SPECS.len()
        );
        let strict = CommandRegistry::bundled_strict();
        if registry
            .iter()
            .any(|spec| spec.owner == CommandOwner::Python)
        {
            assert!(strict.is_err(), "production must reject every Python owner");
        } else {
            strict.expect("an all-Rust contract must pass the production gate");
        }
    }

    #[test]
    fn strict_mode_rejects_python_owners() {
        // Re-label one known native command as Python while leaving all other
        // entries untouched. The inventory check catches the implemented
        // command, while the production gate also rejects every remaining
        // Python migration placeholder.
        let raw = BUNDLED_CONTRACT.replace(
            r#"{"name": "app.version", "owner": "rust", "channel": "rust_concurrent", "timeoutMs": 15000}"#,
            r#"{"name": "app.version", "owner": "python", "channel": "python_serial", "timeoutMs": 15000}"#,
        );
        let registry = CommandRegistry::from_json(&raw).expect("parse migration fixture");
        assert!(!CommandRegistry::has_rust_handler("future.python.command"));
        assert!(CommandRegistry::has_rust_handler("app.version"));
        assert!(registry.validate_rust_handlers(true).is_err());
        assert!(registry.validate_rust_handlers(false).is_ok());
        CommandRegistry::bundled_strict()
            .expect("the bundled all-Rust contract must pass strict mode");
    }
}
