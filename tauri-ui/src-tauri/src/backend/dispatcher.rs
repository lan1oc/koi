use super::asset_mapping;
use super::asset_queries;
use super::batch_control::BatchControlManager;
use super::classification::ClassificationStore;
use super::config::ConfigStore;
use super::data_processing;
use super::document_conversion;
use super::enterprise_queries;
use super::external_tools::ExternalToolManager;
use super::filesystem;
use super::logging::RedactingRollingLogger;
use super::model_client;
use super::native_runtime::NativeRuntime;
use super::pdf_notice;
use super::protocol::BackendResponse;
use super::registry::{CommandChannel, CommandOwner, CommandRegistry, NativeHandler};
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
    batch_control: BatchControlManager,
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
        let batch_control =
            BatchControlManager::new(context.user_data_dir.join(".koi-batch-tasks.json"))?;
        let logger = RedactingRollingLogger::new(&context.user_data_dir)?;
        let task_event_sink = native_runtime.task_event_sink();
        batch_control.add_event_sink(task_event_sink.clone());
        external_tools.add_event_sink(task_event_sink.clone());
        pdf_notice::add_event_sink(task_event_sink);
        Ok(Self {
            context,
            registry,
            config,
            classification,
            templates,
            native_runtime,
            external_tools,
            batch_control,
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
        let Some(handler) = self.registry.handler(command) else {
            return BackendResponse::failure(format!("Rust 命令未注册 handler: {command}"));
        };
        if spec.owner != CommandOwner::Rust || spec.channel != CommandChannel::RustConcurrent {
            return BackendResponse::failure(format!(
                "Rust-only 后端拒绝非 Rust 命令路由: {command}"
            ));
        }

        if handler == NativeHandler::DataProcessing {
            return data_processing::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        // Document conversion owns its typed native boundary; the owner check
        // remains an additional production-registry invariant.
        if handler == NativeHandler::DocumentConversion {
            return document_conversion::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::RetestConfig {
            return retest_config::dispatch(
                command,
                &payload,
                &self.config,
                &self.context.user_data_dir.join("retest-tools"),
            )
            .map(BackendResponse::success)
            .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::AssetMapping {
            return asset_mapping::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::EnterpriseQuery {
            return enterprise_queries::dispatch(command, &payload, &self.config)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::ModelClient {
            return model_client::dispatch(command, &payload, &self.config)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::RetestReport {
            return retest_reports::dispatch(
                command,
                &payload,
                &self.context.user_data_dir,
                &self.context.cwd,
            )
            .map(BackendResponse::success)
            .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::ExternalTools {
            return self
                .external_tools
                .dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        // PDF extraction and notice state primitives are native Rust handlers.
        if handler == NativeHandler::PdfNotice {
            if command.starts_with("doc.notice.") {
                let company_groups = match self.classification.company_group_pairs() {
                    Ok(groups) => groups,
                    Err(error) => return BackendResponse::failure(error),
                };
                let context = pdf_notice::NoticeRuntimeContext {
                    templates_dir: self.context.user_data_dir.join("Report_Template"),
                    config_path: self.context.user_data_dir.join("config.json"),
                    task_state_path: self.context.user_data_dir.join(".koi-notice-tasks.json"),
                    company_groups,
                };
                return pdf_notice::dispatch_with_context(command, &payload, &context)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure);
            }
            return pdf_notice::dispatch(command, &payload)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }

        if handler == NativeHandler::AssetQuery {
            let domain = format!("asset:{command}");
            match self.batch_control.control(&domain, &payload) {
                Ok(Some(response)) => return BackendResponse::success(response),
                Err(error) => return BackendResponse::failure(error),
                Ok(None) => {}
            }
            let run = match self.batch_control.begin(&domain, &payload) {
                Ok(run) => run,
                Err(error) => return BackendResponse::failure(error),
            };
            let result = asset_queries::dispatch(command, &payload, &self.config, run.token());
            let success = result.as_ref().is_ok_and(|outcome| outcome.success);
            let finish = self.batch_control.finish(run, success);
            return match (result, finish) {
                (Ok(outcome), Ok(true)) => BackendResponse::success(outcome.data),
                (Ok(_), Ok(false)) => BackendResponse::success(json!({
                    "success": false,
                    "message": "request cancelled",
                    "cancelled": true,
                    "stopped": true,
                })),
                (Err(error), _) | (_, Err(error)) => BackendResponse::failure(error),
            };
        }
        if handler == NativeHandler::ThreatBookQuery {
            let domain = format!("threatbook:{command}");
            match self.batch_control.control(&domain, &payload) {
                Ok(Some(response)) => return BackendResponse::success(response),
                Err(error) => return BackendResponse::failure(error),
                Ok(None) => {}
            }
            let run = match self.batch_control.begin(&domain, &payload) {
                Ok(run) => run,
                Err(error) => return BackendResponse::failure(error),
            };
            let result = threatbook_queries::dispatch(command, &payload, &self.config, run.token());
            let success = result.as_ref().is_ok_and(|outcome| outcome.success);
            let finish = self.batch_control.finish(run, success);
            return match (result, finish) {
                (Ok(outcome), Ok(true)) => BackendResponse::success(outcome.data),
                (Ok(_), Ok(false)) => BackendResponse::success(json!({
                    "success": false,
                    "message": "request cancelled",
                    "cancelled": true,
                    "stopped": true,
                })),
                (Err(error), _) | (_, Err(error)) => BackendResponse::failure(error),
            };
        }
        if handler == NativeHandler::NativeRuntime {
            return self
                .native_runtime
                .dispatch(command, &payload, &self.config)
                .map(BackendResponse::success)
                .unwrap_or_else(BackendResponse::failure);
        }
        if handler == NativeHandler::Direct {
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
                "fs.roots" => filesystem::roots(&self.context.cwd, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "fs.list_dir" => {
                    filesystem::list_dir(&payload, &self.context.cwd, &self.context.home_dir)
                        .map(BackendResponse::success)
                        .unwrap_or_else(BackendResponse::failure)
                }
                "fs.path_info" => filesystem::path_info(&payload, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "fs.open_path" => filesystem::open_path(&payload, &self.context.home_dir)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
                "fs.open_url" => filesystem::open_url(&payload)
                    .map(BackendResponse::success)
                    .unwrap_or_else(BackendResponse::failure),
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

        BackendResponse::failure(format!("Rust handler 路由未实现: {command}"))
    }
}
