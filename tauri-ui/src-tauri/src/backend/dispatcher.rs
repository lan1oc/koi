use super::asset_mapping;
use super::asset_queries;
use super::classification::ClassificationStore;
use super::config::ConfigStore;
use super::data_processing;
use super::document_conversion;
use super::enterprise_queries;
use super::external_tools::ExternalToolManager;
use super::filesystem;
use super::logging::RedactingRollingLogger;
use super::model_client;
use super::native_runtime::{self, NativeRuntime};
use super::pdf_notice;
use super::protocol::BackendResponse;
use super::registry::{CommandChannel, CommandOwner, CommandRegistry};
use super::retest;
use super::retest_config;
use super::retest_reports;
use super::settings;
use super::templates::TemplateStore;
use super::threatbook_queries;
use super::weekly_report;
use serde_json::{json, Value};
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct BackendContext {
    pub user_data_dir: PathBuf,
    pub home_dir: PathBuf,
    pub cwd: PathBuf,
    pub app_version: String,
}

impl BackendContext {
    pub fn new(
        user_data_dir: PathBuf,
        home_dir: PathBuf,
        cwd: PathBuf,
        app_version: impl Into<String>,
    ) -> Self {
        Self {
            user_data_dir,
            home_dir,
            cwd,
            app_version: app_version.into().trim_start_matches('v').to_string(),
        }
    }
}

pub struct BackendCore {
    context: BackendContext,
    registry: CommandRegistry,
    config: ConfigStore,
    classification: ClassificationStore,
    templates: TemplateStore,
    native_runtime: NativeRuntime,
    external_tools: ExternalToolManager,
    logger: RedactingRollingLogger,
}

impl BackendCore {
    #[allow(dead_code)]
    pub fn new(context: BackendContext) -> Result<Self, String> {
        let registry = CommandRegistry::bundled()?;
        registry.validate_rust_handlers(false)?;
        Self::with_registry(context, registry)
    }

    /// Production entry point. Unlike the migration constructor, this gate
    /// requires all 97 commands to be registered as native Rust handlers.
    #[allow(dead_code)]
    pub fn new_strict(context: BackendContext) -> Result<Self, String> {
        let registry = CommandRegistry::bundled_strict()?;
        Self::with_registry(context, registry)
    }

    fn with_registry(context: BackendContext, registry: CommandRegistry) -> Result<Self, String> {
        let config = ConfigStore::new(context.user_data_dir.join("config.json"));
        let classification =
            ClassificationStore::new(context.user_data_dir.join("enterprise_classification.db"))?;
        let templates = TemplateStore::new(context.user_data_dir.clone())?;
        let native_runtime =
            NativeRuntime::new(context.user_data_dir.clone(), context.home_dir.clone())?;
        let external_tools = ExternalToolManager::new(context.user_data_dir.join("retest-tools"))?;
        let logger = RedactingRollingLogger::new(&context.user_data_dir)?;
        Ok(Self {
            context,
            registry,
            config,
            classification,
            templates,
            native_runtime,
            external_tools,
            logger,
        })
    }

    #[allow(dead_code)]
    pub fn registry(&self) -> &CommandRegistry {
        &self.registry
    }

    #[cfg(test)]
    pub fn context(&self) -> &BackendContext {
        &self.context
    }

    pub fn dispatch(&self, command: &str, payload: Value) -> BackendResponse {
        let redaction = self.logger.capture(&payload);
        let response = self.dispatch_unlogged(command, payload);
        let _ = self.logger.log_command(command, &response, &redaction);
        response
    }

    fn dispatch_unlogged(&self, command: &str, payload: Value) -> BackendResponse {
        let Some(spec) = self.registry.get(command) else {
            return BackendResponse::failure(format!("未知命令: {command}"));
        };

        if data_processing::is_command(command) {
            return data_processing::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        // Document conversion owns its typed native boundary; the owner check
        // remains an additional production-registry invariant.
        if spec.owner == CommandOwner::Rust && document_conversion::is_command(command) {
            return document_conversion::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if retest_config::is_command(command) {
            return retest_config::dispatch(
                command,
                &payload,
                &self.config,
                &self.context.user_data_dir.join("retest-tools"),
            )
            .map(BackendResponse::success)
            .unwrap_or_else(BackendResponse::failure);
        }

        if asset_mapping::is_command(command) {
            return asset_mapping::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if spec.owner == CommandOwner::Rust && enterprise_queries::is_command(command) {
            return enterprise_queries::dispatch(command, &payload, &self.config)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if model_client::is_command(command) {
            return model_client::dispatch(command, &payload, &self.config)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if spec.owner == CommandOwner::Rust && command == retest_reports::COMMAND {
            return retest_reports::dispatch(
                command,
                &payload,
                &self.context.user_data_dir,
                &self.context.cwd,
            )
            .map(BackendResponse::success)
            .unwrap_or_else(BackendResponse::failure);
        }

        if self.external_tools.is_command(command) {
            return self
                .external_tools
                .dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        // PDF extraction and notice state primitives are native Rust handlers.
        if pdf_notice::is_command(command) {
            let mut native_payload = payload.clone();
            if command.starts_with("doc.notice.") {
                if let Some(object) = native_payload.as_object_mut() {
                    object.insert(
                        "_notice_templates_dir".to_string(),
                        json!(self.context.user_data_dir.join("Report_Template")),
                    );
                    if matches!(
                        command,
                        "doc.notice.process"
                            | "doc.notice.process.start"
                            | "doc.notice.process.status"
                            | "doc.notice.convert_failed_pdf"
                    ) {
                        object.insert("_rust_notice_pipeline".to_string(), json!(true));
                        object.insert(
                            "_notice_config_path".to_string(),
                            json!(self.context.user_data_dir.join("config.json")),
                        );
                    }
                    let has_groups = ["company_group_list", "company_groups", "groups"]
                        .iter()
                        .any(|key| {
                            object
                                .get(*key)
                                .and_then(Value::as_array)
                                .is_some_and(|items| !items.is_empty())
                        });
                    if !has_groups {
                        if let Ok(state) = self.classification.get() {
                            let mut pairs = Vec::new();
                            if let Some(groups) = state.get("groups").and_then(Value::as_array) {
                                for group in groups {
                                    let Some(group_name) =
                                        group.get("name").and_then(Value::as_str)
                                    else {
                                        continue;
                                    };
                                    let Some(companies) =
                                        group.get("companies").and_then(Value::as_array)
                                    else {
                                        continue;
                                    };
                                    for company in companies.iter().filter_map(Value::as_str) {
                                        pairs.push(json!([company, group_name]));
                                    }
                                }
                            }
                            object.insert("company_group_list".to_string(), Value::Array(pairs));
                        }
                    }
                }
            }
            return pdf_notice::dispatch(command, &native_payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if spec.owner == CommandOwner::Rust && spec.channel == CommandChannel::RustConcurrent {
            if asset_queries::is_command(command) {
                return asset_queries::dispatch(command, &payload, &self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure);
            }
            if threatbook_queries::is_command(command) {
                return threatbook_queries::dispatch(command, &payload, &self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure);
            }
            if native_runtime::is_command(command) {
                return self
                    .native_runtime
                    .dispatch(command, &payload, &self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure);
            }
            return match command {
                "app.version" => BackendResponse::success(json!({
                    "version": self.context.app_version,
                })),
                "config.load" => self
                    .config
                    .load_public()
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "config.set_dark_mode" => settings::set_dark_mode(&self.config, &payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "weekly_report.config.get" => settings::weekly_report_get(&self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "weekly_report.config.set" => settings::weekly_report_set(&self.config, &payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "weekly_report.generate" => {
                    weekly_report::generate(&self.config, &payload, &self.context.home_dir)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                "info.config.get" => settings::information_config_get(&self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.config.set" => settings::information_config_set(&self.config, &payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.threatbook.config.get" => settings::threatbook_config_get(&self.config)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.threatbook.config.set" => {
                    settings::threatbook_config_set(&self.config, &payload)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                "info.enterprise.classification.get" => self
                    .classification
                    .get()
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.group.add" => self
                    .classification
                    .group_add(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.group.rename" => self
                    .classification
                    .group_rename(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.group.delete" => self
                    .classification
                    .group_delete(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.company.add" => self
                    .classification
                    .company_add(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.company.rename" => self
                    .classification
                    .company_rename(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.company.delete" => self
                    .classification
                    .company_delete(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.enterprise.classification.company.move" => self
                    .classification
                    .company_move(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.list" => self
                    .templates
                    .list(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.get" => self
                    .templates
                    .get(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.create" | "data.template.create" => self
                    .templates
                    .create(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.update" => self
                    .templates
                    .update(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.delete" => self
                    .templates
                    .delete(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.import" => self
                    .templates
                    .import_template(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.templates.export" => self
                    .templates
                    .export_template(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "data.template.save" => self
                    .templates
                    .save(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "fs.roots" => BackendResponse::success(filesystem::roots(
                    &self.context.cwd,
                    &self.context.home_dir,
                )),
                "fs.list_dir" => {
                    filesystem::list_dir(&payload, &self.context.cwd, &self.context.home_dir)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                "fs.path_info" => BackendResponse::success(filesystem::path_info(
                    &payload,
                    &self.context.home_dir,
                )),
                "fs.open_path" => BackendResponse::success(filesystem::open_path(
                    &payload,
                    &self.context.home_dir,
                )),
                "fs.open_url" => BackendResponse::success(filesystem::open_url(&payload)),
                "doc.open_path" => filesystem::open_document_path(&payload, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "doc.retest.open_output" => {
                    filesystem::open_retest_output(&payload, &self.context.home_dir)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                "doc.retest.list_files" => retest::list_files(&payload, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "info.export_text" => filesystem::export_text(&payload, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "doc.notice.counters.save" => {
                    settings::notice_counters_save(&self.config, &payload)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                _ => BackendResponse::failure(format!("Rust 命令未实现: {command}")),
            };
        }

        BackendResponse::failure(format!("Rust 命令未实现: {command}"))
    }
}
