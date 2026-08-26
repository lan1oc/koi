//! Native backend core.
//!
//! This module is intentionally independent from Tauri so the command contract
//! and native handlers can be tested without starting or packaging the app.

pub(crate) mod archive_runtime;
mod asset_mapping;
mod asset_queries;
mod batch_input;
mod classification;
mod config;
mod data_processing;
mod dispatcher;
mod document_conversion;
pub(crate) mod enterprise_queries;
mod external_tools;
mod filesystem;
mod logging;
mod model_client;
mod native_runtime;
mod pdf_notice;
pub(crate) mod pdfium_runtime;
pub mod probe_broker;
mod probe_runner;
pub mod probe_sandbox;
mod probe_source_builder;
mod probe_wheels;
mod protocol;
mod registry;
mod retest;
mod retest_config;
mod retest_external;
mod retest_reports;
mod secret_store;
pub mod self_test;
mod settings;
mod task_manager;
mod templates;
mod threatbook_queries;
mod weekly_report;

pub use dispatcher::{BackendContext, BackendCore};
#[allow(unused_imports)]
pub use protocol::{BackendRequest, BackendResponse};

#[cfg_attr(test, allow(dead_code))]
pub fn run_internal_worker_from_args() -> Option<i32> {
    document_conversion::run_word_com_worker_from_args()
}

#[allow(unused_imports)]
#[cfg(test)]
pub use registry::CommandOwner;
#[cfg(test)]
pub use registry::CommandRegistry;

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempDir(PathBuf);

    impl TempDir {
        fn new(label: &str) -> Self {
            static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let unique = NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock must be after unix epoch")
                .as_nanos();
            let path = std::env::temp_dir().join(format!(
                "koi-rust-backend-{label}-{}-{nanos}-{unique}",
                std::process::id()
            ));
            fs::create_dir_all(&path).expect("create isolated test directory");
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn backend_protocol_oracle_fixture() -> Value {
        let fixture_text = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/fixtures/python_oracle/backend_protocol.v1.json"
        ));
        let fixture: Value =
            serde_json::from_str(fixture_text).expect("parse backend protocol oracle fixture");
        assert_eq!(fixture["format"], "koi-python-oracle-golden-v1");
        for forbidden in [
            "C:\\Users",
            "Users",
            "koi-oracle-",
            "old-key",
            "new-key",
            "hunter-key",
            "cookie-value",
            "xunke-value",
            "old-threat",
            "threat-key",
            "replaced-threat-key",
        ] {
            assert!(
                !fixture_text.contains(forbidden),
                "golden fixture contains forbidden host or secret marker {forbidden}"
            );
        }
        fixture
    }

    fn oracle_case<'a>(fixture: &'a Value, group: &str, name: &str) -> &'a Value {
        fixture["groups"][group]["cases"]
            .as_array()
            .expect("oracle fixture cases")
            .iter()
            .find(|case| case["name"].as_str() == Some(name))
            .unwrap_or_else(|| panic!("missing oracle fixture case {group}/{name}"))
    }

    fn normalize_root_paths(value: &mut Value, root: &Path) {
        let root = root.to_string_lossy().replace(r"\\?\", "");
        fn normalize(value: &mut Value, root: &str) {
            match value {
                Value::String(text) => {
                    *text = text.replace(r"\\?\", "").replace(root, "<ROOT>");
                }
                Value::Array(values) => values.iter_mut().for_each(|value| normalize(value, root)),
                Value::Object(values) => {
                    values.values_mut().for_each(|value| normalize(value, root));
                }
                _ => {}
            }
        }
        normalize(value, &root);
    }

    fn file_fingerprint(path: &Path) -> Value {
        use sha2::Digest;

        let bytes = fs::read(path).expect("read fingerprint file");
        let digest = sha2::Sha256::digest(&bytes);
        json!({
            "size": bytes.len(),
            "sha256": format!("{digest:x}"),
        })
    }

    fn core(temp: &TempDir) -> BackendCore {
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create home");
        fs::create_dir_all(&cwd).expect("create cwd");
        BackendCore::new(BackendContext::new(
            temp.path().join("data"),
            home,
            cwd,
            "v4.0.0",
        ))
        .expect("create backend core")
    }

    #[test]
    fn bundled_registry_has_exactly_97_unique_commands() {
        let registry = CommandRegistry::bundled().expect("load bundled command contract");
        assert_eq!(registry.len(), 97);

        let expected_native = [
            "app.version",
            "config.load",
            "config.set_dark_mode",
            "fs.roots",
            "fs.list_dir",
            "fs.path_info",
            "weekly_report.config.get",
            "weekly_report.config.set",
            "weekly_report.generate",
            "data.field_extract.headers",
            "data.field_extract.run",
            "data.filling.preview",
            "data.filling.run",
            "data.filling.auto_map",
            "data.filling.custom_map",
            "data.template.create",
            "data.template.save",
            "data.templates.list",
            "data.templates.get",
            "data.templates.create",
            "data.templates.update",
            "data.templates.delete",
            "data.templates.import",
            "data.templates.export",
            "info.config.get",
            "info.config.set",
            "info.enterprise.tyc.query",
            "info.enterprise.aiqicha.query",
            "info.enterprise.classification.get",
            "info.enterprise.classification.group.add",
            "info.enterprise.classification.group.rename",
            "info.enterprise.classification.group.delete",
            "info.enterprise.classification.company.add",
            "info.enterprise.classification.company.rename",
            "info.enterprise.classification.company.delete",
            "info.enterprise.classification.company.move",
            "info.asset.fofa.query",
            "info.asset.hunter.query",
            "info.asset.quake.query",
            "info.asset.unified.query",
            "info.asset.syntax_doc",
            "info.threatbook.ip",
            "info.threatbook.ip.batch",
            "info.threatbook.dns",
            "info.threatbook.file_report",
            "info.threatbook.file_multiengines",
            "info.threatbook.file_upload",
            "info.threatbook.config.get",
            "info.threatbook.config.set",
            "info.threatbook.test_connection",
            "info.export_text",
            "fs.open_path",
            "fs.open_url",
            "doc.convert.run",
            "doc.pdf_extract.preview",
            "doc.pdf_extract.run",
            "doc.pdf_extract.compress",
            "doc.notice.process",
            "doc.notice.process.start",
            "doc.notice.process.status",
            "doc.notice.counters.save",
            "doc.notice.classify",
            "doc.notice.convert_failed_pdf",
            "doc.open_path",
            "doc.agent.message",
            "doc.agent.status",
            "doc.agent.stop",
            "doc.agent.approval.respond",
            "doc.agent.auto_approval.set",
            "doc.agent.auto_approval.status",
            "doc.agent.operation.status",
            "doc.agent.operation.stop",
            "doc.agent.tools",
            "doc.retest.run",
            "doc.retest.list_files",
            "doc.retest.run_one",
            "doc.retest.run_one.start",
            "doc.retest.run_one.status",
            "doc.retest.run_one.stop",
            "doc.retest.confirmation.respond",
            "doc.retest.event_stream.info",
            "doc.retest.agent.start",
            "doc.retest.agent.message",
            "doc.retest.agent.status",
            "doc.retest.agent.stop",
            "doc.retest.agent_chat",
            "doc.retest.session.compact",
            "doc.retest.ai_config.get",
            "doc.retest.ai_config.set",
            "doc.retest.ai_config.test",
            "doc.retest.ai_config.key_status",
            "doc.retest.tools.list",
            "doc.retest.tools.status",
            "doc.retest.tools.install",
            "doc.retest.tools.install.status",
            "doc.retest.generate_reports_with_screenshot",
            "doc.retest.open_output",
        ];
        let native: Vec<_> = registry
            .iter()
            .filter(|spec| spec.owner == CommandOwner::Rust)
            .map(|spec| spec.name.as_str())
            .collect();
        assert_eq!(native, expected_native);
    }

    #[test]
    fn information_http_commands_are_native_and_never_call_the_python_bridge() {
        let temp = TempDir::new("information-http-routing");
        let backend = core(&temp);
        let cases = [
            ("info.asset.fofa.query", json!({"query": "ip=\"1.1.1.1\""})),
            (
                "info.asset.hunter.query",
                json!({"query": "ip=\"1.1.1.1\""}),
            ),
            ("info.asset.quake.query", json!({"query": "ip:\"1.1.1.1\""})),
            (
                "info.asset.unified.query",
                json!({"query": "ip=\"1.1.1.1\""}),
            ),
            ("info.threatbook.ip", json!({"ip": "1.1.1.1"})),
            ("info.threatbook.ip.batch", json!({"ips": ["1.1.1.1"]})),
            ("info.threatbook.dns", json!({"domain": "example.test"})),
            ("info.threatbook.file_report", json!({"resource": "abc"})),
            (
                "info.threatbook.file_multiengines",
                json!({"resource": "abc"}),
            ),
            (
                "info.threatbook.file_upload",
                json!({"file_path": "missing.bin"}),
            ),
            ("info.threatbook.test_connection", json!({})),
        ];

        for (command, payload) in cases {
            assert_eq!(
                backend.registry().get(command).map(|spec| spec.owner),
                Some(CommandOwner::Rust),
                "{command} must be owned by Rust"
            );
            let response = backend.dispatch(command, payload);
            assert!(
                response.ok,
                "{command} must return a structured data response"
            );
            assert_eq!(response.data["success"], false, "{command}");
        }
    }

    #[test]
    fn response_envelope_always_serializes_all_three_fields() {
        let success = serde_json::to_value(BackendResponse::success(json!({"value": 1})))
            .expect("serialize success response");
        assert_eq!(
            success,
            json!({"ok": true, "data": {"value": 1}, "error": null})
        );

        let failure = serde_json::to_value(BackendResponse::failure("boom"))
            .expect("serialize failure response");
        assert_eq!(failure, json!({"ok": false, "data": null, "error": "boom"}));
    }

    #[test]
    fn unknown_command_uses_existing_chinese_error_semantics() {
        let temp = TempDir::new("unknown");
        let backend = core(&temp);
        assert_eq!(
            backend.dispatch("missing.command", json!({})),
            BackendResponse::failure("未知命令: missing.command")
        );
    }

    #[test]
    fn delegated_command_preserves_payload_and_contract_timeout() {
        let temp = TempDir::new("bridge");
        let backend = core(&temp);
        let payload = json!({"input_path": "isolated-test"});

        let response = backend.dispatch("doc.convert.run", payload.clone());
        assert!(response.ok);
    }

    #[test]
    fn config_load_and_dark_mode_update_preserve_unknown_fields() {
        let temp = TempDir::new("config");
        let data_dir = temp.path().join("data");
        fs::create_dir_all(&data_dir).expect("create data dir");
        let config_path = data_dir.join("config.json");
        fs::write(
            &config_path,
            r#"{"custom":{"keep":"opaque-marker"},"ui":{"theme":"custom"}}"#,
        )
        .expect("write isolated config fixture");

        let backend = core(&temp);
        let loaded = backend.dispatch("config.load", json!({}));
        assert!(loaded.ok);
        assert_eq!(loaded.data["custom"]["keep"], "opaque-marker");
        assert_eq!(loaded.data["ui"]["theme"], "custom");

        let updated = backend.dispatch("config.set_dark_mode", json!({"dark_mode": true}));
        assert_eq!(updated.data, json!({"dark_mode": true}));

        let persisted: Value = serde_json::from_slice(
            &fs::read(&config_path).expect("read isolated persisted config"),
        )
        .expect("parse isolated persisted config");
        assert_eq!(persisted["custom"]["keep"], "opaque-marker");
        assert_eq!(persisted["ui"]["theme"], "custom");
        assert_eq!(persisted["ui"]["dark_mode"], true);
        assert_eq!(persisted["ui_settings"]["dark_mode"], true);
        assert!(!config_path.with_extension("json.tmp").exists());
    }

    #[test]
    fn native_settings_commands_preserve_payload_shapes_and_unknown_config() {
        let temp = TempDir::new("settings");
        let data_dir = temp.path().join("data");
        fs::create_dir_all(&data_dir).expect("create data dir");
        let config_path = data_dir.join("config.json");
        fs::write(
            &config_path,
            r#"{
                "custom":{"keep":"opaque-marker"},
                "fofa":{"email":"old@example.test","api_key":"old-key"},
                "weekly_report":{"vulnerability_notice_dir":"old-vuln"},
                "report_counters":{
                    "notification_number":10,
                    "rectification_number":20,
                    "unavailable_notification_numbers":[11],
                    "unavailable_rectification_numbers":[21]
                }
            }"#,
        )
        .expect("write isolated settings fixture");
        let backend = core(&temp);

        let weekly = backend.dispatch(
            "weekly_report.config.set",
            json!({
                "vulnerabilityNoticeDir": " C:\\vuln ",
                "event_notice_dir": "C:\\events",
                "excludeMondayNextNotice": true,
            }),
        );
        assert!(weekly.ok, "weekly config failed: {:?}", weekly.error);
        assert_eq!(weekly.data["vulnerability_notice_dir"], r"C:\vuln");
        assert_eq!(weekly.data["event_notice_dir"], r"C:\events");
        assert_eq!(weekly.data["exclude_monday_next_notice"], true);
        assert_eq!(weekly.data["last_updated"].as_str().map(str::len), Some(19));

        let information = backend.dispatch(
            "info.config.set",
            json!({
                "fofa_email": "new@example.test",
                "fofa_api_key": "new-key",
                "hunter_api_key": "hunter-key",
                "tyc_cookie": "cookie-value",
                "xunkebao_cookie": "xunke-value",
                "threatbook_api_key": "threat-key",
            }),
        );
        assert!(
            information.ok,
            "information config failed: {:?}",
            information.error
        );
        assert_eq!(information.data["fofa"]["email"], "new@example.test");
        assert_eq!(information.data["hunter"]["api_key"], "");
        assert_eq!(information.data["hunter"]["api_key_configured"], true);
        assert_eq!(information.data["hunter"]["api_key_masked"], "****-key");
        assert_eq!(information.data["tyc"]["cookie"], "");
        assert_eq!(information.data["tyc"]["cookie_configured"], true);
        assert_eq!(information.data["aiqicha"]["xunkebao_cookie"], "");
        assert_eq!(
            information.data["aiqicha"]["xunkebao_cookie_configured"],
            true
        );

        let threatbook = backend.dispatch(
            "info.threatbook.config.set",
            json!({"api_key": "replaced-threat-key"}),
        );
        assert_eq!(threatbook.data["api_key"], "");
        assert_eq!(threatbook.data["api_key_configured"], true);
        assert_eq!(threatbook.data["api_key_masked"], "****-key");

        let counters = backend.dispatch(
            "doc.notice.counters.save",
            json!({
                "notice_number": 12,
                "rectification_number": "22",
                "unavailable_notification_numbers": "13, 15-14",
                "unavailable_numbers": [23, "25-24"],
                "unavailable_type": "责令整改",
            }),
        );
        assert!(counters.ok, "counter save failed: {:?}", counters.error);
        assert_eq!(counters.data["success"], true);
        assert_eq!(counters.data["updated"], true);
        assert_eq!(counters.data["report_counters"]["notification_number"], 12);
        assert_eq!(counters.data["report_counters"]["rectification_number"], 22);
        assert_eq!(
            counters.data["report_counters"]["unavailable_notification_numbers"],
            json!([11, 13, 14, 15])
        );
        assert_eq!(
            counters.data["report_counters"]["unavailable_rectification_numbers"],
            json!([21, 23, 24, 25])
        );

        let no_change = backend.dispatch("doc.notice.counters.save", json!({"notice_number": 0}));
        assert_eq!(no_change.data["success"], true);
        assert_eq!(no_change.data["updated"], false);

        let persisted: Value = serde_json::from_slice(
            &fs::read(config_path).expect("read isolated persisted settings"),
        )
        .expect("parse isolated persisted settings");
        assert_eq!(persisted["custom"]["keep"], "opaque-marker");
        assert_eq!(persisted["fofa"]["api_key"], "");
        assert_eq!(persisted["threatbook_api_key"], "");
        let encrypted = fs::read_to_string(data_dir.join("secrets.dpapi.json"))
            .expect("read isolated DPAPI store");
        assert!(!encrypted.contains("new-key"));
        assert!(!encrypted.contains("replaced-threat-key"));
    }

    #[test]
    fn native_settings_match_redacted_python_protocol_golden_fixture() {
        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("settings-contract");
        let rust_data = temp.path().join("rust-data");
        fs::create_dir_all(&rust_data).expect("create Rust contract data");
        let initial_config = json!({
            "custom": {"keep": "contract-marker"},
            "fofa": {"email": "old@example.test", "api_key": "old-key"},
            "hunter": {"api_key": ""},
            "quake": {"api_key": ""},
            "tyc": {"cookie": ""},
            "aiqicha": {"cookie": "", "xunkebao_cookie": ""},
            "weekly_report": {
                "vulnerability_notice_dir": "old-vuln",
                "event_notice_dir": "old-event",
                "exclude_monday_next_notice": false,
                "last_updated": "",
            },
            "report_counters": {
                "notification_number": 10,
                "rectification_number": 20,
                "unavailable_notification_numbers": [11],
                "unavailable_rectification_numbers": [21],
                "year": 2026,
                "last_updated": "",
            },
            "threatbook_api_key": "old-threat",
        });
        let fixture_bytes = serde_json::to_vec_pretty(&initial_config).expect("serialize fixture");
        fs::write(rust_data.join("config.json"), &fixture_bytes).expect("write Rust fixture");

        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create contract home");
        fs::create_dir_all(&cwd).expect("create contract cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home, cwd, "4.0.0"))
            .expect("create Rust contract core");

        let cases = [
            ("weekly-config-get", "weekly_report.config.get", json!({})),
            (
                "weekly-config-set",
                "weekly_report.config.set",
                json!({
                    "vulnerabilityNoticeDir": " C:\\vuln ",
                    "event_notice_dir": "C:\\events",
                    "excludeMondayNextNotice": true,
                }),
            ),
            ("info-config-get", "info.config.get", json!({})),
            (
                "info-config-set",
                "info.config.set",
                json!({
                    "fofa_email": "new@example.test",
                    "fofa_api_key": "new-key",
                    "hunter_api_key": "hunter-key",
                    "tyc_cookie": "cookie-value",
                    "xunkebao_cookie": "xunke-value",
                    "threatbook_api_key": "threat-key",
                }),
            ),
            (
                "threatbook-config-get",
                "info.threatbook.config.get",
                json!({}),
            ),
            (
                "threatbook-config-set",
                "info.threatbook.config.set",
                json!({"api_key": "replaced-threat-key"}),
            ),
            (
                "notice-counters-no-change",
                "doc.notice.counters.save",
                json!({"notice_number": 0}),
            ),
            (
                "notice-counters-update",
                "doc.notice.counters.save",
                json!({
                    "notice_number": 12,
                    "rectification_number": "22",
                    "unavailable_notification_numbers": "13, 15-14",
                    "unavailable_numbers": [23, "25-24"],
                    "unavailable_type": "责令整改",
                }),
            ),
        ];

        for (name, command, payload) in cases {
            let mut rust_response = rust.dispatch(command, payload);
            scrub_timestamps(&mut rust_response.data);
            redact_settings_response(&mut rust_response.data);
            assert_eq!(
                serde_json::to_value(rust_response).expect("serialize Rust settings response"),
                oracle_case(&golden, "settings", name)["expected"],
                "Rust/golden response mismatch for {command}"
            );
        }
    }

    #[test]
    fn model_config_validation_matches_python_golden_without_network() {
        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("model-config-contract");
        let rust_data = temp.path().join("rust-data");
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&rust_data).expect("create Rust model data");
        fs::create_dir_all(&home).expect("create model home");
        fs::create_dir_all(&cwd).expect("create model cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home, cwd, "4.0.0"))
            .expect("create Rust model core");

        for (name, command) in [
            ("config-test-empty", "doc.retest.ai_config.test"),
            ("key-status-empty", "doc.retest.ai_config.key_status"),
        ] {
            let rust_response = rust.dispatch(command, json!({}));
            assert_eq!(
                serde_json::to_value(rust_response).expect("serialize Rust model response"),
                oracle_case(&golden, "model_config", name)["expected"],
                "Rust/golden response mismatch for {command}"
            );
        }
    }

    #[test]
    fn weekly_report_generation_matches_python_golden_on_isolated_notice_tree() {
        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("weekly-report-contract");
        let rust_data = temp.path().join("rust-data");
        let vulnerability_dir = temp.path().join("vulnerability-notices");
        let event_dir = temp.path().join("event-disposals");
        fs::create_dir_all(&rust_data).expect("create Rust weekly data");
        fs::create_dir_all(&vulnerability_dir).expect("create vulnerability fixture");
        fs::create_dir_all(event_dir.join("宁波丙有限公司")).expect("create event company fixture");
        fs::write(
            vulnerability_dir.join("20260629关于宁波甲有限公司存在安全漏洞通报.docx"),
            b"notice",
        )
        .expect("write current-week vulnerability fixture");
        fs::write(
            vulnerability_dir.join("20260707关于宁波乙有限公司安全漏洞通报.pdf"),
            b"notice",
        )
        .expect("write next-week vulnerability fixture");
        fs::write(
            vulnerability_dir.join("20260708关于忽略有限公司整改材料.docx"),
            b"attachment",
        )
        .expect("write ignored attachment fixture");
        fs::write(
            event_dir
                .join("宁波丙有限公司")
                .join("20260710网络安全事件报告书.docx"),
            b"event",
        )
        .expect("write event fixture");

        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create weekly home");
        fs::create_dir_all(&cwd).expect("create weekly cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data.clone(), home, cwd, "4.0.0"))
            .expect("create Rust weekly core");
        let payload = json!({
            "vulnerability_notice_dir": vulnerability_dir,
            "event_notice_dir": event_dir,
            "exclude_monday_next_notice": true,
            "report_date": "2026-07-06",
        });

        let mut rust_response = rust.dispatch("weekly_report.generate", payload);
        normalize_root_paths(&mut rust_response.data, temp.path());
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust weekly response"),
            golden["groups"]["weekly_report"]["expected"],
            "Rust/golden weekly report response mismatch"
        );
        assert_eq!(rust_response.data["summary"]["records"]["vulnerability"], 2);
        assert_eq!(rust_response.data["summary"]["records"]["event"], 1);
        assert_eq!(
            rust_response.data["summary"]["current_vulnerability"],
            json!(["宁波甲有限公司"])
        );
        assert_eq!(
            rust_response.data["summary"]["current_events"],
            json!(["宁波丙有限公司"])
        );
        assert_eq!(
            rust_response.data["summary"]["next_companies"],
            json!(["宁波乙有限公司"])
        );

        let mut persisted: Value = serde_json::from_slice(
            &fs::read(rust_data.join("config.json")).expect("read Rust weekly config"),
        )
        .expect("parse Rust weekly config");
        scrub_timestamps(&mut persisted);
        normalize_root_paths(&mut persisted, temp.path());
        assert_eq!(
            persisted["weekly_report"],
            golden["groups"]["weekly_report"]["persisted_weekly_report"]
        );
        assert_eq!(
            persisted["weekly_report"]["exclude_monday_next_notice"],
            true
        );
    }

    #[test]
    fn asset_syntax_docs_match_redacted_python_oracle_golden_fixture() {
        let temp = TempDir::new("asset-syntax-doc-contract");
        let rust_data = temp.path().join("rust-data");
        fs::create_dir_all(&rust_data).expect("create Rust asset data");
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create asset home");
        fs::create_dir_all(&cwd).expect("create asset cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home, cwd, "4.0.0"))
            .expect("create Rust asset core");

        let fixture_text = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/fixtures/python_oracle/asset_syntax_doc.v1.json"
        ));
        let fixture: Value =
            serde_json::from_str(fixture_text).expect("parse redacted asset syntax oracle fixture");
        assert_eq!(fixture["format"], "koi-python-oracle-golden-v1");
        assert_eq!(fixture["command"], "info.asset.syntax_doc");
        assert_eq!(fixture["normalization"]["redacted_fields"], json!([]));
        let fixture_lower = fixture_text.to_ascii_lowercase();
        for forbidden in ["api_key", "cookie", "authorization", "bearer "] {
            assert!(
                !fixture_lower.contains(forbidden),
                "golden fixture contains forbidden secret marker {forbidden}"
            );
        }

        for case in fixture["cases"].as_array().expect("fixture cases") {
            let name = case["name"].as_str().expect("fixture case name");
            let payload = case["payload"].clone();
            let rust_response = rust.dispatch("info.asset.syntax_doc", payload);
            let expected: BackendResponse = serde_json::from_value(case["expected"].clone())
                .expect("parse fixture response envelope");
            assert_eq!(
                rust_response, expected,
                "Rust syntax documentation mismatch for golden case {name}"
            );
        }
    }

    #[test]
    fn pdf_preview_and_invalid_extract_match_python_golden_fixture() {
        fn normalize_paths(response: &mut BackendResponse) {
            fn normalize(value: &mut Value) {
                match value {
                    Value::Object(map) => {
                        for (key, child) in map.iter_mut() {
                            if (key == "path"
                                || key == "output_file"
                                || key == "state_file"
                                || key == "target_path")
                                && child.is_string()
                            {
                                *child = Value::String("<path>".to_string());
                                continue;
                            }
                            normalize(child);
                        }
                    }
                    Value::Array(items) => items.iter_mut().for_each(normalize),
                    _ => {}
                }
            }
            normalize(&mut response.data);
        }

        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("pdf-contract");
        let rust_data = temp.path().join("rust-data");
        fs::create_dir_all(&rust_data).expect("create Rust PDF data");
        let pdf = temp.path().join("fixture.pdf");
        fs::write(
            &pdf,
            super::pdf_notice::make_blank_pdf(&[
                super::pdf_notice::PageInfo {
                    width: Some(240.0),
                    height: Some(320.0),
                },
                super::pdf_notice::PageInfo {
                    width: Some(300.0),
                    height: Some(420.0),
                },
            ]),
        )
        .expect("write PDF fixture");
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create PDF home");
        fs::create_dir_all(&cwd).expect("create PDF cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home, cwd, "4.0.0"))
            .expect("create Rust PDF core");

        let mut rust_preview = rust.dispatch(
            "doc.pdf_extract.preview",
            json!({"pdf_files": [pdf.clone()]}),
        );
        normalize_paths(&mut rust_preview);
        assert_eq!(
            serde_json::to_value(rust_preview).expect("serialize Rust PDF preview"),
            oracle_case(&golden, "pdf_extract", "two-page-preview")["expected"],
            "PDF preview golden response mismatch"
        );

        let mut rust_invalid = rust.dispatch(
            "doc.pdf_extract.run",
            json!({"pdf_file": pdf.clone(), "page_ranges": "99"}),
        );
        normalize_paths(&mut rust_invalid);
        assert_eq!(
            serde_json::to_value(rust_invalid).expect("serialize Rust invalid PDF response"),
            oracle_case(&golden, "pdf_extract", "out-of-range-extract")["expected"],
            "PDF invalid-range golden response mismatch"
        );
    }

    #[test]
    fn data_processing_commands_match_python_golden_and_workbook_structure() {
        use calamine::{open_workbook_auto, Data, Reader};
        use rust_xlsxwriter::Workbook;

        fn write_template(path: &Path, headers: &[&str]) {
            let mut workbook = Workbook::new();
            let worksheet = workbook.add_worksheet();
            for (column, header) in headers.iter().enumerate() {
                worksheet
                    .write_string(0, column as u16, *header)
                    .expect("write template header");
            }
            workbook.save(path).expect("save template workbook");
        }

        fn workbook_fingerprint(path: &Path) -> Value {
            let mut workbook = open_workbook_auto(path).expect("open generated workbook");
            let sheet_names = workbook.sheet_names().to_vec();
            let sheets = sheet_names
                .iter()
                .map(|sheet_name| {
                    let range = workbook
                        .worksheet_range(sheet_name)
                        .expect("read generated sheet");
                    let rows = range
                        .rows()
                        .map(|row| {
                            row.iter()
                                .map(|cell| match cell {
                                    Data::Empty => Value::Null,
                                    Data::Int(value) => json!(value),
                                    Data::Float(value) if value.fract() == 0.0 => {
                                        json!(*value as i64)
                                    }
                                    Data::Float(value) => json!(value),
                                    Data::Bool(value) => json!(value),
                                    Data::String(value)
                                    | Data::DateTimeIso(value)
                                    | Data::DurationIso(value) => json!(value),
                                    value => json!(value.to_string()),
                                })
                                .collect::<Vec<_>>()
                        })
                        .collect::<Vec<_>>();
                    json!({"name": sheet_name, "rows": rows})
                })
                .collect::<Vec<_>>();
            json!(sheets)
        }

        fn normalize_output_path(response: &mut BackendResponse) {
            if let Some(data) = response.data.as_object_mut() {
                if data
                    .get("output_file")
                    .is_some_and(|value| !value.is_null())
                {
                    data.insert(
                        "output_file".to_string(),
                        Value::String("<output_file>".to_string()),
                    );
                }
            }
        }

        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("data-processing-contract");
        let rust_data = temp.path().join("rust-data");
        let source = temp.path().join("source.csv");
        let template = temp.path().join("template.xlsx");
        let rust_output = temp.path().join("rust-output.xlsx");
        fs::create_dir_all(&rust_data).expect("create Rust data directory");
        fs::write(
            &source,
            "name,age,city\nAlice,31,Shanghai\nBob,,Beijing\nCarol,27,Shanghai\n",
        )
        .expect("write source CSV");
        write_template(&template, &["name", "age", "city", "unused"]);

        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create data processing home");
        fs::create_dir_all(&cwd).expect("create data processing cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home, cwd, "4.0.0"))
            .expect("create Rust data processing core");
        let mapping = json!({"name": "name", "age": "age", "city": "city"});

        let cases = [
            (
                "headers",
                "data.field_extract.headers",
                json!({"source_file": source}),
            ),
            (
                "extract",
                "data.field_extract.run",
                json!({"source_file": source, "selected_fields": ["name", "age"]}),
            ),
            (
                "auto-map",
                "data.filling.auto_map",
                json!({"source_file": source, "template_file": template}),
            ),
            (
                "custom-map",
                "data.filling.custom_map",
                json!({"source_file": source, "template_file": template, "field_mapping": mapping}),
            ),
            (
                "preview",
                "data.filling.preview",
                json!({
                    "source_file": source,
                    "template_file": template,
                    "field_mapping": mapping,
                    "preview_rows": 2,
                }),
            ),
        ];

        for (name, command, payload) in cases {
            let rust_response = rust.dispatch(command, payload);
            assert_eq!(
                serde_json::to_value(rust_response).expect("serialize Rust data response"),
                oracle_case(&golden, "data_processing", name)["expected"],
                "Rust/golden data response mismatch for {command}"
            );
        }

        let mut rust_response = rust.dispatch(
            "data.filling.run",
            json!({
                "source_file": source,
                "template_file": template,
                "field_mapping": mapping,
                "output_file": rust_output,
            }),
        );
        normalize_output_path(&mut rust_response);
        assert_eq!(
            serde_json::to_value(rust_response).expect("serialize Rust filling response"),
            golden["groups"]["data_processing"]["filling"]["expected"],
            "filling golden response mismatch"
        );
        assert_eq!(
            workbook_fingerprint(&rust_output),
            golden["groups"]["data_processing"]["filling"]["workbook_fingerprint"],
            "filled workbook structure differs from golden fingerprint"
        );
    }

    fn scrub_timestamps(value: &mut Value) {
        match value {
            Value::Object(values) => {
                if values.contains_key("last_updated") {
                    values.insert(
                        "last_updated".to_string(),
                        Value::String("<timestamp>".to_string()),
                    );
                }
                for value in values.values_mut() {
                    scrub_timestamps(value);
                }
            }
            Value::Array(values) => {
                for value in values {
                    scrub_timestamps(value);
                }
            }
            _ => {}
        }
    }

    fn redact_settings_response(value: &mut Value) {
        let Some(root) = value.as_object_mut() else {
            return;
        };
        for (section, field) in [
            ("fofa", "api_key"),
            ("hunter", "api_key"),
            ("quake", "api_key"),
            ("tyc", "cookie"),
            ("aiqicha", "cookie"),
            ("aiqicha", "xunkebao_cookie"),
        ] {
            if let Some(values) = root.get_mut(section).and_then(Value::as_object_mut) {
                redact_secret_field(values, field);
            }
        }
        redact_secret_field(root, "threatbook_api_key");
        redact_secret_field(root, "api_key");
    }

    fn redact_secret_field(values: &mut serde_json::Map<String, Value>, field: &str) {
        let secret = values
            .get(field)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if !values.contains_key(field) {
            return;
        }
        let configured = !secret.is_empty()
            || values
                .get(&format!("{field}_configured"))
                .and_then(Value::as_bool)
                .unwrap_or(false)
            || values
                .get(&format!("{field}_masked"))
                .and_then(Value::as_str)
                .is_some_and(|value| !value.is_empty());
        values.insert(field.to_string(), Value::String(String::new()));
        values.insert(format!("{field}_configured"), Value::Bool(configured));
        values.insert(
            format!("{field}_masked"),
            Value::String(if configured { "<masked>" } else { "" }.to_string()),
        );
    }

    fn scrub_template_volatile(value: &mut Value) {
        match value {
            Value::Object(values) => {
                for (key, child) in values.iter_mut() {
                    if matches!(
                        key.as_str(),
                        "created_at" | "updated_at" | "imported_at" | "last_used"
                    ) {
                        *child = Value::String("<timestamp>".to_string());
                    } else if matches!(key.as_str(), "id" | "template_id") {
                        *child = Value::String("<id>".to_string());
                    } else if key == "export_file" {
                        *child = Value::String("<export_file>".to_string());
                    } else {
                        scrub_template_volatile(child);
                    }
                }
            }
            Value::Array(values) => {
                for child in values {
                    scrub_template_volatile(child);
                }
            }
            _ => {}
        }
    }

    #[test]
    fn template_commands_match_python_golden_on_isolated_data() {
        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("templates-contract");
        let rust_data = temp.path().join("rust-data");
        let import_file = temp.path().join("import-template.json");
        fs::create_dir_all(rust_data.join("templates")).expect("create Rust template data");

        let fixture = json!({
            "fixed-a": {
                "id": "fixed-a",
                "name": "固定模板",
                "description": "固定描述",
                "field_mapping": {"目标": "来源"},
                "source_format": "excel",
                "template_format": "excel",
                "metadata": {"keep": "opaque"},
                "created_at": "2026-01-01T00:00:00.000000",
                "updated_at": "2026-01-01T00:00:00.000000",
                "version": "1.0.0",
                "usage_count": 1
            },
            "fixed-predefined": {
                "id": "fixed-predefined",
                "name": "预定义模板",
                "description": "预定义",
                "field_mapping": {},
                "source_format": "csv",
                "template_format": "excel",
                "metadata": {"is_predefined": true},
                "created_at": "2026-01-02T00:00:00.000000",
                "updated_at": "2026-01-02T00:00:00.000000",
                "usage_count": 0
            },
            "fixed-bool": {
                "id": "fixed-bool",
                "name": "布尔计数模板",
                "description": "异常兼容",
                "field_mapping": {},
                "source_format": "txt",
                "template_format": "excel",
                "metadata": {},
                "created_at": "2026-01-03T00:00:00.000000",
                "updated_at": "2026-01-03T00:00:00.000000",
                "usage_count": true
            }
        });
        let fixture_bytes =
            serde_json::to_vec_pretty(&fixture).expect("serialize template fixture");
        fs::write(rust_data.join("templates/templates.json"), &fixture_bytes)
            .expect("write Rust template fixture");
        fs::write(
            &import_file,
            serde_json::to_vec_pretty(&json!({
                "name": "导入模板",
                "description": "导入描述",
                "field_mapping": {"A": "B"},
                "metadata": {"source": "fixture"}
            }))
            .expect("serialize import fixture"),
        )
        .expect("write import fixture");

        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create template home");
        fs::create_dir_all(&cwd).expect("create template cwd");
        let rust = BackendCore::new(BackendContext::new(
            rust_data.clone(),
            home.clone(),
            cwd,
            "4.0.0",
        ))
        .expect("create Rust template core");

        {
            let compare = |name: &str, command: &str, payload: Value| {
                let mut rust_response = rust.dispatch(command, payload);
                scrub_template_volatile(&mut rust_response.data);
                normalize_root_paths(&mut rust_response.data, temp.path());
                assert_eq!(
                    serde_json::to_value(rust_response).expect("serialize Rust template response"),
                    oracle_case(&golden, "templates", name)["expected"],
                    "Rust/golden response mismatch for {command}"
                );
            };

            compare("list-all", "data.templates.list", json!({}));
            compare(
                "list-excel",
                "data.templates.list",
                json!({"filter_format": "excel"}),
            );
            compare(
                "get-fixed-a",
                "data.templates.get",
                json!({"template_id": "fixed-a"}),
            );
            compare(
                "mark-fixed-a-used",
                "data.templates.get",
                json!({"id": "fixed-a", "mark_used": true}),
            );
            compare(
                "mark-bool-used",
                "data.templates.get",
                json!({"id": "fixed-bool", "mark_used": true}),
            );
            compare(
                "update-fixed-a",
                "data.templates.update",
                json!({
                    "id": "fixed-a",
                    "name": "固定模板已更新",
                    "description": "更新描述",
                    "field_mapping": {"目标2": "来源2"},
                    "source_format": "csv",
                    "template_format": "txt",
                    "metadata": {"keep": "updated", "new": true},
                    "target_template": "target.xlsx",
                    "delimiter": "|"
                }),
            );
            compare(
                "create-alias",
                "data.template.create",
                json!({
                    "name": "新建模板",
                    "description": "新建描述",
                    "mapping": {"目标": "来源"},
                    "metadata": {"category": "test"},
                    "target_template": "new.xlsx",
                    "delimiter": ","
                }),
            );
            compare(
                "create-duplicate",
                "data.templates.create",
                json!({
                    "name": "新建模板",
                    "description": "新建描述",
                    "field_mapping": {"目标": "来源"}
                }),
            );
            compare(
                "delete-predefined-without-force",
                "data.templates.delete",
                json!({"name": "预定义模板"}),
            );
            compare(
                "delete-predefined-force",
                "data.templates.delete",
                json!({"id": "fixed-predefined", "force": true}),
            );
            compare(
                "import",
                "data.templates.import",
                json!({"import_path": import_file}),
            );
            compare(
                "import-overwrite",
                "data.templates.import",
                json!({"import_path": import_file, "overwrite": true}),
            );
            compare(
                "save-alias",
                "data.template.save",
                json!({
                    "name": "保存别名模板",
                    "description": "保存创建",
                    "field_mapping": {}
                }),
            );
        }

        let rust_export = home.join("rust-export").join("template");
        fs::create_dir_all(rust_export.parent().expect("Rust export parent"))
            .expect("create Rust export parent");
        let mut rust_export_response = rust.dispatch(
            "data.templates.export",
            json!({"id": "fixed-a", "export_path": rust_export}),
        );
        scrub_template_volatile(&mut rust_export_response.data);
        normalize_root_paths(&mut rust_export_response.data, temp.path());
        assert_eq!(
            serde_json::to_value(rust_export_response)
                .expect("serialize Rust template export response"),
            golden["groups"]["templates"]["export"]["expected"]
        );
        let rust_export_file = rust_export.with_extension("json");
        assert!(rust_export_file.exists());
        let mut rust_exported: Value = serde_json::from_slice(
            &fs::read(rust_export_file).expect("read Rust exported template"),
        )
        .expect("parse Rust exported template");
        scrub_template_volatile(&mut rust_exported);
        assert_eq!(
            rust_exported,
            golden["groups"]["templates"]["export"]["exported_template"]
        );

        let malformed_import = temp.path().join("malformed-import.json");
        fs::write(&malformed_import, b"[]").expect("write malformed import");
        let mut rust_malformed = rust.dispatch(
            "data.templates.import",
            json!({"import_path": malformed_import}),
        );
        scrub_template_volatile(&mut rust_malformed.data);
        normalize_root_paths(&mut rust_malformed.data, temp.path());
        assert_eq!(
            serde_json::to_value(rust_malformed).expect("serialize malformed template response"),
            golden["groups"]["templates"]["malformed_import"]["expected"]
        );

        let rust_missing_parent = temp.path().join("rust-missing").join("out");
        let mut rust_failure = rust.dispatch(
            "data.templates.export",
            json!({"id": "fixed-a", "export_path": rust_missing_parent}),
        );
        scrub_template_volatile(&mut rust_failure.data);
        normalize_root_paths(&mut rust_failure.data, temp.path());
        let golden_failure = &golden["groups"]["templates"]["missing_parent_export"]["expected"];
        assert!(rust_failure.ok);
        assert_eq!(rust_failure.data["success"], false);
        assert_eq!(
            rust_failure.data["success"],
            golden_failure["data"]["success"]
        );
        assert_eq!(
            rust_failure.data["export_file"],
            golden_failure["data"]["export_file"]
        );
        assert!(rust_failure.data["message"]
            .as_str()
            .is_some_and(|message| message.starts_with("导出模板失败:")));
        assert!(golden_failure["data"]["message"]
            .as_str()
            .is_some_and(|message| message.starts_with("导出模板失败:")));
        assert!(!temp.path().join("rust-missing").exists());

        let mut rust_templates: Value = serde_json::from_slice(
            &fs::read(rust_data.join("templates/templates.json"))
                .expect("read Rust persisted templates"),
        )
        .expect("parse Rust persisted templates");
        scrub_template_volatile(&mut rust_templates);
        let sort_templates = |value: Value| {
            let mut templates = value
                .as_object()
                .expect("template store object")
                .values()
                .cloned()
                .collect::<Vec<_>>();
            templates.sort_by_key(|template| {
                serde_json::to_string(template).expect("serialize normalized template")
            });
            templates
        };
        assert_eq!(
            sort_templates(rust_templates),
            golden["groups"]["templates"]["final_store_sorted"]
                .as_array()
                .expect("golden final template store")
                .clone()
        );
    }

    #[test]
    fn filesystem_open_commands_match_python_validation_without_launching() {
        let temp = TempDir::new("filesystem-open-contract");
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create isolated open home");
        fs::create_dir_all(&cwd).expect("create isolated open cwd");
        let backend = core(&temp);

        let invalid_url =
            backend.dispatch("fs.open_url", json!({"url": "file:///not-an-http-url"}));
        assert_eq!(
            invalid_url,
            BackendResponse::success(json!({
                "success": false,
                "message": "Invalid URL",
                "url": "file:///not-an-http-url"
            }))
        );

        let missing = temp.path().join("missing-open-target");
        let missing_response = backend.dispatch("fs.open_path", json!({"path": missing}));
        assert!(missing_response.ok);
        assert_eq!(missing_response.data["success"], false);
        assert_eq!(
            missing_response.data["message"],
            format!("Path does not exist: {}", missing.display())
        );
        assert_eq!(
            missing_response.data["path"],
            missing.to_string_lossy().to_string()
        );
        assert_eq!(backend.context().home_dir, home);
        assert_eq!(backend.context().cwd, cwd);
    }

    #[test]
    fn filesystem_handlers_match_python_payload_shapes() {
        let temp = TempDir::new("filesystem");
        let backend = core(&temp);
        let folder = temp.path().join("cwd").join("folder");
        fs::create_dir_all(folder.join("nested")).expect("create nested folder");
        fs::write(folder.join("b.TXT"), b"1234").expect("write file");
        fs::write(folder.join(".hidden.txt"), b"hidden").expect("write hidden file");

        let listing = backend.dispatch(
            "fs.list_dir",
            json!({"path": folder, "extensions": ["txt"]}),
        );
        assert!(listing.ok, "listing failed: {:?}", listing.error);
        let entries = listing.data["entries"].as_array().expect("entries array");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0]["name"], "nested");
        assert_eq!(entries[0]["is_dir"], true);
        assert_eq!(entries[1]["name"], "b.TXT");
        assert_eq!(entries[1]["extension"], "txt");
        assert_eq!(entries[1]["size"], 4);
        assert_eq!(entries[1]["matches_filter"], true);

        let path_info = backend.dispatch("fs.path_info", json!({"path": folder.join("b.TXT")}));
        assert_eq!(path_info.data["exists"], true);
        assert_eq!(path_info.data["is_file"], true);
        assert_eq!(path_info.data["is_dir"], false);

        let roots = backend.dispatch("fs.roots", json!({}));
        assert_eq!(
            roots.data["cwd"],
            Value::String(temp.path().join("cwd").to_string_lossy().to_string())
        );
        assert_eq!(
            roots.data["home"],
            Value::String(temp.path().join("home").to_string_lossy().to_string())
        );
    }

    #[test]
    fn list_dir_can_recover_to_nearest_existing_ancestor() {
        let temp = TempDir::new("recover");
        let backend = core(&temp);
        let missing = temp.path().join("cwd").join("gone").join("child");
        let response = backend.dispatch(
            "fs.list_dir",
            json!({"path": missing, "recover_missing_ancestor": true}),
        );

        assert!(response.ok, "recovery failed: {:?}", response.error);
        assert_eq!(
            response.data["path"],
            Value::String(temp.path().join("cwd").to_string_lossy().to_string())
        );
        assert_eq!(
            response.data["recovered_from"],
            Value::String(missing.to_string_lossy().to_string())
        );
    }

    #[test]
    fn export_text_matches_python_golden_and_keeps_output_isolated() {
        let golden = backend_protocol_oracle_fixture();
        let temp = TempDir::new("export-text");
        let rust_data = temp.path().join("rust-data");
        fs::create_dir_all(&rust_data).expect("create Rust export data");
        let home = temp.path().join("home");
        let cwd = temp.path().join("cwd");
        fs::create_dir_all(&home).expect("create export home");
        fs::create_dir_all(&cwd).expect("create export cwd");
        let rust = BackendCore::new(BackendContext::new(rust_data, home.clone(), cwd, "4.0.0"))
            .expect("create Rust export core");
        let output = home.join("exports").join("result.txt");
        let payload = json!({
            "output_file": output,
            "content": "导出内容\nsecond line",
        });
        let content = "导出内容\nsecond line";
        let expected_content = if cfg!(windows) {
            content.replace('\n', "\r\n")
        } else {
            content.to_string()
        };

        let mut rust_response = rust.dispatch("info.export_text", payload);
        normalize_root_paths(&mut rust_response.data, &home);
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust export response"),
            oracle_case(&golden, "export_text", "utf8-bom-content")["expected"]
        );
        assert!(rust_response.ok);
        assert_eq!(rust_response.data["bytes"], 3 + expected_content.len());
        assert_eq!(
            fs::read(&output).expect("read exported file"),
            [vec![0xEF, 0xBB, 0xBF], expected_content.as_bytes().to_vec()].concat()
        );
        assert_eq!(
            file_fingerprint(&output),
            oracle_case(&golden, "export_text", "utf8-bom-content")["file_fingerprint"]
        );

        let empty_output = home.join("exports").join("empty.txt");
        let empty_payload = json!({"output_file": empty_output, "content": "  \n"});
        rust_response = rust.dispatch("info.export_text", empty_payload);
        normalize_root_paths(&mut rust_response.data, &home);
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize empty export response"),
            oracle_case(&golden, "export_text", "blank-content")["expected"]
        );
        assert_eq!(rust_response.data["success"], false);
        assert!(!empty_output.exists());
        assert_eq!(
            empty_output.exists(),
            oracle_case(&golden, "export_text", "blank-content")["file_exists"]
        );

        rust_response = rust.dispatch("info.export_text", json!({"content": "missing path"}));
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize missing-path response"),
            oracle_case(&golden, "export_text", "missing-output-path")["expected"]
        );
        assert!(!rust_response.ok);

        let tilde_output = home.join("exports").join("tilde.txt");
        let tilde_payload = json!({
            "output_file": format!("~/exports/{}", tilde_output.file_name().unwrap().to_string_lossy()),
            "content": "tilde",
        });
        let tilde_response = rust.dispatch("info.export_text", tilde_payload);
        assert!(
            tilde_response.ok,
            "tilde export failed: {:?}",
            tilde_response.error
        );
        assert!(tilde_output.exists());
    }
}
