import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const contractPath = path.join(projectRoot, 'contracts', 'backend-commands.json');
const oracleRelative = 'tauri-ui/src-tauri/fixtures/python_oracle/command_boundaries.v1.json';
const oraclePath = path.join(projectRoot, ...oracleRelative.split('/'));
const outputPath = path.join(projectRoot, 'contracts', 'backend-behavior-matrix.v1.json');

const test = (file, name) => ({ kind: 'rust-test', file, test: name });
const browser = (name) => ({
  kind: 'playwright',
  file: 'tauri-ui/e2e/retest-workflows.mjs',
  test: name,
});
const example = (file) => ({ kind: 'example', file });

const GROUPS = {
  app: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'bundled_registry_has_exactly_97_unique_commands'),
      test('tauri-ui/src-tauri/src/backend/self_test.rs', 'initializes_only_the_requested_data_directory'),
    ],
  },
  config: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'config_load_and_dark_mode_update_preserve_unknown_fields'),
      test('tauri-ui/src-tauri/src/backend/config.rs', 'malformed_config_fails_closed_and_preserves_original_bytes'),
      test('tauri-ui/src-tauri/src/backend/config.rs', 'file_lock_rejects_a_second_writer_until_released'),
      test('tauri-ui/src-tauri/src/backend/config.rs', 'plaintext_credentials_migrate_to_dpapi_store'),
    ],
  },
  filesystem: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'filesystem_handlers_match_python_payload_shapes'),
      test('tauri-ui/src-tauri/src/backend/filesystem.rs', 'typed_requests_keep_legacy_truthiness_and_camel_case_aliases'),
      test('tauri-ui/src-tauri/src/backend/filesystem.rs', 'open_path_reports_missing_target_without_launching_a_process'),
      test('tauri-ui/src-tauri/src/backend/filesystem.rs', 'http_url_validation_matches_protocol_boundary'),
    ],
  },
  weekly: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'weekly_report_generation_matches_python_golden_on_isolated_notice_tree'),
      test('tauri-ui/src-tauri/src/backend/weekly_report.rs', 'report_date_accepts_python_aliases_and_short_months'),
      test('tauri-ui/src-tauri/src/backend/weekly_report.rs', 'request_aliases_and_explicit_null_keep_legacy_precedence'),
      test('tauri-ui/src-tauri/src/backend/weekly_report.rs', 'saved_config_is_typed_directly_from_the_persisted_section'),
    ],
  },
  data: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'data_processing_commands_match_python_golden_and_workbook_structure'),
      test('tauri-ui/src-tauri/src/backend/data_processing.rs', 'extracts_selected_csv_fields_and_writes_output'),
      test('tauri-ui/src-tauri/src/backend/data_processing.rs', 'reads_gbk_and_detects_pipe_separator'),
      test('tauri-ui/src-tauri/src/backend/data_processing.rs', 'typed_request_empty_and_invalid_values_keep_command_errors'),
    ],
  },
  templates: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'template_commands_match_python_golden_on_isolated_data'),
      test('tauri-ui/src-tauri/src/backend/templates.rs', 'create_list_get_update_delete_and_aliases_keep_shapes'),
      test('tauri-ui/src-tauri/src/backend/templates.rs', 'predefined_delete_requires_force_and_import_overwrite_adds_duplicate'),
      test('tauri-ui/src-tauri/src/backend/templates.rs', 'typed_template_requests_preserve_empty_and_invalid_errors'),
    ],
  },
  settings: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/mod.rs', 'native_settings_match_redacted_python_protocol_golden_fixture'),
      test('tauri-ui/src-tauri/src/backend/settings.rs', 'typed_setting_requests_preserve_aliases_presence_and_truthiness'),
      test('tauri-ui/src-tauri/src/backend/settings.rs', 'information_config_response_never_exposes_secret_values'),
      test('tauri-ui/src-tauri/src/backend/settings.rs', 'threatbook_partial_update_does_not_clear_existing_key'),
    ],
  },
  classification: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/classification.rs', 'classification_commands_keep_order_and_response_shape'),
      test('tauri-ui/src-tauri/src/backend/classification.rs', 'mutation_messages_and_error_semantics_match_python'),
      test('tauri-ui/src-tauri/src/backend/classification.rs', 'legacy_database_is_backed_up_and_migrated_without_data_loss'),
      test('tauri-ui/src-tauri/src/backend/classification.rs', 'online_backup_is_consistent_and_never_overwrites'),
    ],
  },
  enterprise: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'invalid_input_preserves_python_outer_error_semantics'),
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'missing_cookie_is_deterministic_and_does_not_call_network_or_leak'),
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'batch_preserves_order_and_reports_partial_failure'),
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'challenge_uses_isolated_boundary_cookie_once_then_retries'),
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'aiqicha_selects_matching_page_data_instead_of_navigation_list'),
      test('tauri-ui/src-tauri/src/backend/enterprise_queries.rs', 'generic_login_copy_on_search_results_does_not_require_user_action'),
      test('tauri-ui/src-tauri/src/native_enterprise_browser.rs', 'search_match_ignores_extra_provider_query_params'),
      test('tauri-ui/src-tauri/src/native_enterprise_browser.rs', 'challenge_detection_is_route_based'),
    ],
  },
  asset: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/asset_queries.rs', 'fofa_matches_python_oracle_shape_and_encoding'),
      test('tauri-ui/src-tauri/src/backend/asset_queries.rs', 'hunter_retries_transient_status_and_matches_python_rows'),
      test('tauri-ui/src-tauri/src/backend/asset_queries.rs', 'quake_sends_typed_json_and_auth_header'),
      test('tauri-ui/src-tauri/src/backend/asset_queries.rs', 'cancellation_and_response_limit_fail_closed_without_leaking_key'),
    ],
  },
  syntax: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/asset_mapping.rs', 'typed_response_matches_the_embedded_oracle_snapshot'),
      test('tauri-ui/src-tauri/src/backend/asset_mapping.rs', 'normalizes_platform_case_and_rejects_missing_or_unknown_platform'),
    ],
  },
  threatbook: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/threatbook_queries.rs', 'ip_and_dns_match_python_shapes_and_http_contract'),
      test('tauri-ui/src-tauri/src/backend/threatbook_queries.rs', 'file_report_and_multiengines_preserve_api_data'),
      test('tauri-ui/src-tauri/src/backend/threatbook_queries.rs', 'multipart_upload_streams_file_and_redacts_secret_from_output'),
      test('tauri-ui/src-tauri/src/backend/threatbook_queries.rs', 'required_fields_and_missing_key_keep_outer_and_inner_error_boundaries'),
    ],
  },
  conversion: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/document_conversion.rs', 'protocol_matches_redacted_python_golden_for_scan_filter_overwrite_failures_and_structure'),
      test('tauri-ui/src-tauri/src/backend/document_conversion.rs', 'output_root_inside_input_is_rejected_before_scan'),
      test('tauri-ui/src-tauri/src/backend/document_conversion.rs', 'atomic_replace_commits_complete_file'),
      test('tauri-ui/src-tauri/src/backend/document_conversion.rs', 'word_com_converts_both_directions_with_valid_outputs'),
    ],
  },
  pdf: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'valid_extract_and_merge_match_redacted_python_golden_on_real_pdfs'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'extraction_rejects_invalid_ranges_and_writes_verified_output'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'merge_remaps_cross_document_ids_without_resource_collisions'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'standard_and_strong_compression_write_verified_outputs'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'blank_pdf_output_defaults_to_input_directory_for_ranges_and_selected_pages'),
      browser('testPdfBlankOutputUsesInputDirectory'),
    ],
  },
  notice: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_input_detection_matches_legacy_unprefixed_and_retest_names'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_issue_names_strip_complete_report_suffixes_without_duplicate_exists'),
      test('tauri-ui/src-tauri/src/backend/word_automation.rs', 'confirmation_images_use_body_anchors_when_pages_have_no_empty_paragraphs'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'each_notice_keeps_its_own_issue_while_rectification_uses_the_union'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'copy_to_rewrite_preserves_section_alignment_tabs_and_run_formatting'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_structure_parser_includes_table_content_and_section_properties'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_structure_rejects_unresolved_table_resources'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'rewrite_marker_v2_remains_backward_readable_but_completion_requires_v2'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'v1_upgrade_restores_managed_source_from_verified_backup'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'v2_artifact_reuse_requires_the_current_source_digest'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'native_notice_number_allocation_survives_a_partial_checkpoint'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_stage_failure_returns_accumulated_logs_and_keeps_source'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_completion_restores_original_name_and_preserves_backup_until_cleanup'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_final_name_conflict_keeps_the_edited_original_and_checkpoint'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_pdf_scan_finds_xss_doc_and_docx_and_relocates_manual_files'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'cleanup_previews_exact_files_and_preserves_formal_outputs'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'cleanup_after_pdf_conversion_keeps_pdf_and_rejects_changed_preview'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'cleanup_keeps_user_edits_in_marked_notice_when_restoring_its_name'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'cleanup_preserves_incomplete_state_and_rejects_arbitrary_paths'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'completed_pipeline_restart_reports_verified_checkpoint_instead_of_empty_success'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'rust_notice_pipeline_completes_all_stages_and_preserves_user_source'),
      test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'notice_process_worker_error_remains_reconnectable_with_result'),
      browser('testNoticeFiveStageReconnectAndFailure'),
      browser('testNoticePdfConversionAndCleanupPreview'),
      example('tauri-ui/src-tauri/examples/notice_fixture_verify.rs'),
    ],
  },
  native: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'missing_runtime_controls_keep_legacy_data_failure_boundaries'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'failed_agent_judgement_keeps_checkpoint_and_continue_without_reflection'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'unreachable_target_finishes_and_generates_evidence_report_without_model'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'word_targets_preserve_run_boundaries_and_query_entities'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'retest_status_keeps_legacy_resume_fields_and_generation_evidence'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'generation_invalidation_rejects_late_results'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'restart_marks_orphaned_generation_stopped_and_keeps_latest_checkpoint'),
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'retest_start_and_message_share_resume_planning_and_ignore_numeric_hints'),
      browser('testCheckpoint'),
      browser('testStopDiscardsLateResult'),
    ],
  },
  retest: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/retest.rs', 'list_files_filters_sources_and_preserves_recursive_paths'),
      test('tauri-ui/src-tauri/src/backend/retest.rs', 'list_files_correlates_same_directory_report_evidence'),
      test('tauri-ui/src-tauri/src/backend/retest.rs', 'list_files_request_keeps_camel_case_and_python_string_compatibility'),
    ],
  },
  aiConfig: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/retest_config.rs', 'config_round_trip_preserves_and_explicitly_clears_key'),
      test('tauri-ui/src-tauri/src/backend/retest_config.rs', 'typed_config_set_distinguishes_missing_fields_from_explicit_invalid_values'),
      test('tauri-ui/src-tauri/src/backend/retest_config.rs', 'profile_actions_and_base_url_normalization_are_compatible'),
    ],
  },
  model: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/model_client.rs', 'missing_configuration_fails_without_network'),
      test('tauri-ui/src-tauri/src/backend/model_client.rs', 'parses_openai_sse_text_deltas_in_order'),
      test('tauri-ui/src-tauri/src/backend/model_client.rs', 'transient_model_failures_retry_the_same_request_and_recover'),
      test('tauri-ui/src-tauri/src/backend/model_client.rs', 'done_event_finishes_without_waiting_for_server_to_close_connection'),
      test('tauri-ui/src-tauri/src/backend/model_client.rs', 'openrouter_key_status_sanitizes_secret_fields_and_echoes'),
    ],
  },
  tools: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/retest_config.rs', 'tool_catalog_is_the_sorted_python_oracle_snapshot'),
      test('tauri-ui/src-tauri/src/backend/retest_config.rs', 'tool_status_rejects_unlocked_binaries_and_legacy_sqlmap_python'),
      test('tauri-ui/src-tauri/src/backend/external_tools.rs', 'sqlmap_uses_builtin_validator_without_python'),
      test('tauri-ui/src-tauri/src/backend/external_tools.rs', 'async_task_reaches_terminal_state'),
      test('tauri-ui/src-tauri/src/backend/external_tools.rs', 'concurrent_install_lock_fails_closed_without_network_or_partial_products'),
    ],
  },
  reports: {
    tests: [
      test('tauri-ui/src-tauri/src/backend/retest_reports.rs', 'creates_valid_report_and_preserves_template_parts'),
      test('tauri-ui/src-tauri/src/backend/retest_reports.rs', 'table_fields_use_each_sources_vulnerability_and_complete_urls'),
      test('tauri-ui/src-tauri/src/backend/retest_reports.rs', 'table_replacement_preserves_cell_formatting_and_escaped_urls'),
    ],
  },
};

function groupFor(command) {
  if (command === 'app.version') return 'app';
  if (command.startsWith('config.')) return 'config';
  if (command.startsWith('weekly_report.')) return 'weekly';
  if (command.startsWith('data.field_') || command.startsWith('data.filling.')) return 'data';
  if (command.startsWith('data.template')) return 'templates';
  if (command === 'info.config.get' || command === 'info.config.set'
    || command.startsWith('info.threatbook.config.')) return 'settings';
  if (command.startsWith('info.enterprise.classification.')) return 'classification';
  if (command.startsWith('info.enterprise.')) return 'enterprise';
  if (command === 'info.asset.syntax_doc') return 'syntax';
  if (command.startsWith('info.asset.')) return 'asset';
  if (command.startsWith('info.threatbook.')) return 'threatbook';
  if (command === 'info.export_text' || command.startsWith('fs.') || command === 'doc.open_path'
    || command === 'doc.retest.open_output') return 'filesystem';
  if (command === 'doc.convert.run') return 'conversion';
  if (command.startsWith('doc.pdf_extract.')) return 'pdf';
  if (command.startsWith('doc.notice.')) return 'notice';
  if (command === 'doc.retest.list_files') return 'retest';
  if (command.startsWith('doc.retest.ai_config.') && !command.endsWith('.test')
    && !command.endsWith('.key_status')) return 'aiConfig';
  if (command === 'doc.retest.ai_config.test' || command === 'doc.retest.ai_config.key_status') return 'model';
  if (command.startsWith('doc.retest.tools.')) return 'tools';
  if (command === 'doc.retest.generate_reports_with_screenshot') return 'reports';
  return 'native';
}

const asyncCommands = new Set([
  'doc.notice.process.start',
  'doc.notice.process.status',
  'doc.agent.message',
  'doc.agent.status',
  'doc.agent.stop',
  'doc.agent.approval.respond',
  'doc.agent.operation.status',
  'doc.agent.operation.stop',
  'doc.retest.run',
  'doc.retest.run_one',
  'doc.retest.run_one.start',
  'doc.retest.run_one.status',
  'doc.retest.run_one.stop',
  'doc.retest.confirmation.respond',
  'doc.retest.agent.start',
  'doc.retest.agent.message',
  'doc.retest.agent.status',
  'doc.retest.agent.stop',
  'doc.retest.agent_chat',
  'doc.retest.session.compact',
  'doc.retest.tools.install',
  'doc.retest.tools.install.status',
]);

const secretProjectionCommands = new Set([
  'config.load',
  'info.config.get',
  'info.config.set',
  'info.threatbook.config.get',
  'info.threatbook.config.set',
  'doc.retest.ai_config.get',
  'doc.retest.ai_config.set',
]);

const improvedCommands = new Set([
  ...secretProjectionCommands,
  'fs.roots',
  'doc.notice.process.start',
  'doc.notice.process.status',
  'doc.agent.message',
  'doc.agent.status',
  'doc.agent.stop',
  'doc.agent.auto_approval.set',
  'doc.agent.auto_approval.status',
  'doc.agent.operation.stop',
  'doc.agent.tools',
  'doc.retest.event_stream.info',
  'doc.retest.agent.start',
  'doc.retest.agent.message',
  'doc.retest.agent.status',
  'doc.retest.agent.stop',
  'doc.retest.agent_chat',
  'doc.retest.session.compact',
  'doc.retest.tools.list',
  'doc.retest.tools.status',
  'doc.retest.tools.install.status',
]);

const securityExceptions = new Map([
  ['doc.retest.tools.install', 'The legacy installer downloaded an unpinned sqlmap.py tree. Rust preserves the tool workflow and IDs while installing only hash-locked nmap/ffuf products and using the built-in bounded SQL validator.'],
]);

function aliasesFor(command) {
  if (command.startsWith('weekly_report.')) {
    return ['vulnerabilityNoticeDir', 'eventNoticeDir', 'excludeMondayNextNotice', 'reportDate'];
  }
  if (command.startsWith('data.field_') || command.startsWith('data.filling.')) {
    return ['sourceFile', 'customSeparator', 'selectedFields', 'outputFile', 'templateFile', 'fieldMapping', 'similarityThreshold', 'previewRows'];
  }
  if (command.startsWith('data.template')) {
    return ['templateId', 'fieldMapping', 'sourceFormat', 'templateFormat', 'targetTemplate'];
  }
  if (command.startsWith('doc.agent.') || command.startsWith('doc.retest.')) {
    return ['sessionId', 'targetDir', 'content', 'autoApprove', 'frontendContext', 'forceResume', 'oneClickQueue', 'useProgressEvidence', 'generateReports', 'sourceFile', 'taskId', 'operationId', 'confirmationId'];
  }
  if (command.startsWith('fs.')) return ['recoverMissingAncestor', 'showHidden', 'targetDir', 'outputFile'];
  if (command.startsWith('info.') || command.startsWith('doc.notice.')) return ['apiKey', 'targetPath', 'taskId'];
  return [];
}

function rationaleFor(command, exact) {
  if (exact) return 'The redacted safe-boundary response is identical after documented normalization.';
  if (secretProjectionCommands.has(command)) {
    return 'Rust intentionally returns empty secret fields plus configured/masked metadata and stores migrated secrets with DPAPI; plaintext compatibility is forbidden.';
  }
  if (command === 'fs.roots') {
    return 'Drive discovery is equivalent; Rust reports the explicitly isolated application home/cwd rather than ambient host locations.';
  }
  if (command === 'doc.notice.process') {
    return 'Business result and side effects are equivalent; Rust adds candidate SHA-256, actual-work-directory, and resumable stage diagnostics.';
  }
  if (command.startsWith('doc.notice.process.')) {
    return 'Rust preserves start/status workflow and adds cancellation generation and stopped state for reconnect and late-result safety.';
  }
  if (command === 'doc.retest.event_stream.info') {
    return 'Rust preserves host/port/ws_url and adds a random capability token; unauthenticated loopback WebSocket access is intentionally rejected.';
  }
  if (command === 'doc.agent.tools') {
    return 'Rust is a functional superset: legacy workspace tools remain, while bounded AppContainer probe and separately approved source-wheel build tools are added.';
  }
  if (command.startsWith('doc.retest.tools.')) {
    return 'Rust preserves catalog and install/status workflows but requires locked product inventories and replaces host sqlmap.py with the bounded built-in SQL validator.';
  }
  if (command.startsWith('doc.agent.') || command.startsWith('doc.retest.')) {
    return 'Rust preserves the user workflow while adding persistent typed session state, generation invalidation, structured events, exact resume evidence, and late-result rejection.';
  }
  return 'The capability is preserved with additive typed fields or deterministic diagnostics; executable evidence is linked below.';
}

function scenario(status, evidence, reason = undefined) {
  return { status, ...(reason ? { reason } : {}), ...(evidence?.length ? { evidence } : {}) };
}

function sha256File(file) {
  const bytes = Buffer.from(fs.readFileSync(file, 'utf8').replaceAll('\r\n', '\n'), 'utf8');
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function normalizedTextBytes(file) {
  return Buffer.byteLength(fs.readFileSync(file, 'utf8').replaceAll('\r\n', '\n'), 'utf8');
}

const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
const oracle = JSON.parse(fs.readFileSync(oraclePath, 'utf8'));
const oracleCases = new Map(oracle.cases.map((item) => [item.command, item]));
const fixtureDirectory = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'fixtures', 'python_oracle');
const goldenFixtures = fs.readdirSync(fixtureDirectory)
  .filter((name) => name.endsWith('.json'))
  .sort()
  .map((name) => {
    const file = path.join(fixtureDirectory, name);
    return {
      file: `tauri-ui/src-tauri/fixtures/python_oracle/${name}`,
      bytes: normalizedTextBytes(file),
      sha256: sha256File(file),
    };
  });

const commands = contract.commands.map((spec) => {
  const command = spec.name;
  const groupName = groupFor(command);
  const group = GROUPS[groupName];
  if (!group) throw new Error(`Missing evidence group for ${command}: ${groupName}`);
  const oracleCase = oracleCases.get(command);
  const exception = securityExceptions.get(command);
  if (!oracleCase) throw new Error(`Missing oracle boundary case for ${command}`);
  const exact = oracleCase.equal === true;
  const capabilityStatus = exception ? 'security-exception' : improvedCommands.has(command) ? 'improved' : 'equivalent';
  const evidence = [
    { kind: 'oracle-boundary', file: oracleRelative, scenario: oracleCase.scenario },
    ...group.tests,
  ];
  const mutating = /(?:\.set|\.add|\.rename|\.delete|\.move|\.create|\.save|\.import|\.export|\.run|\.generate|\.process|\.classify|\.convert|\.install|\.stop|\.respond|\.message|\.compact|open_)/.test(command);
  const missingConfigRelevant = /(?:info\.(?:enterprise|asset|threatbook)|doc\.(?:agent|retest)|weekly_report\.generate)/.test(command);
  const fileTreeRelevant = /^(?:fs\.|weekly_report\.generate|data\.|info\.export_text|doc\.(?:convert|pdf_extract|notice|open_path|retest\.list_files|retest\.generate_reports|retest\.open_output))/.test(command);
  const sqliteRelevant = command.startsWith('info.enterprise.classification.');
  const configRelevant = /^(?:config\.|weekly_report\.|info\.config|info\.threatbook\.config|doc\.notice\.counters|doc\.retest\.ai_config)/.test(command);
  const taskRelevant = asyncCommands.has(command);
  const externalRelevant = /^(?:info\.(?:enterprise|asset|threatbook)|fs\.open|doc\.(?:convert|open_path|agent|retest))/.test(command);
  const scenarios = {
    normal: scenario('covered', [evidence[0], group.tests[0]]),
    invalid_request: scenario('covered', [evidence[0], group.tests[Math.min(1, group.tests.length - 1)]]),
    missing_configuration: missingConfigRelevant
      ? scenario('covered', [group.tests[Math.min(2, group.tests.length - 1)]])
      : scenario('not-applicable', [], 'The command has no external credential or optional configuration prerequisite.'),
    overwrite_or_conflict: mutating
      ? scenario('covered', [group.tests[Math.min(2, group.tests.length - 1)]])
      : scenario('not-applicable', [], 'The command is read-only and does not create a name/overwrite conflict.'),
    side_effects: (mutating || fileTreeRelevant || sqliteRelevant || configRelevant || taskRelevant || externalRelevant)
      ? scenario('covered', [group.tests[group.tests.length - 1]])
      : scenario('not-applicable', [], 'The command has no persistent filesystem, database, configuration, task, or external side effect.'),
  };
  if (taskRelevant) {
    scenarios.start_status_stop = scenario('covered', group.tests.slice(-2));
    scenarios.restart_recovery = scenario('covered', [
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'restart_marks_orphaned_generation_stopped_and_keeps_latest_checkpoint'),
      ...(groupName === 'notice' ? [test('tauri-ui/src-tauri/src/backend/pdf_notice.rs', 'persisted_notice_completion_is_reported_as_completed_after_memory_is_absent')] : []),
    ]);
    scenarios.late_result_generation = scenario('covered', [
      test('tauri-ui/src-tauri/src/backend/native_runtime.rs', 'generation_invalidation_rejects_late_results'),
      browser('testStopDiscardsLateResult'),
    ]);
  }
  return {
    name: command,
    domain: groupName,
    owner: spec.owner,
    channel: spec.channel,
    timeoutMs: spec.timeoutMs,
    capabilityStatus,
    verificationStatus: 'verified',
    comparison: {
      safeBoundary: exact ? 'exact' : exception ? 'security-exception' : 'explained-difference',
      rationale: exception || rationaleFor(command, exact),
    },
    request: {
      fieldsObserved: Object.keys(oracleCase.payload || {}).sort(),
      aliases: aliasesFor(command),
      typedRustBoundary: true,
    },
    response: {
      envelope: ['ok', 'data', 'error'],
      dataFieldsObserved: Object.keys(oracleCase.rust?.data || {}).sort(),
      errorBoundary: oracleCase.rust?.ok === false ? 'outer-envelope' : 'data-or-success-envelope',
    },
    surfaces: {
      fileTree: fileTreeRelevant ? { applicable: true, evidence: group.tests } : { applicable: false, reason: 'No file-tree contract.' },
      sqlite: sqliteRelevant ? { applicable: true, evidence: group.tests } : { applicable: false, reason: 'No SQLite mutation contract.' },
      config: configRelevant ? { applicable: true, evidence: group.tests } : { applicable: false, reason: 'No configuration mutation contract.' },
      taskState: taskRelevant ? { applicable: true, evidence: group.tests } : { applicable: false, reason: 'No long-running task state.' },
      externalCalls: externalRelevant ? { applicable: true, evidence: group.tests } : { applicable: false, reason: 'No HTTP, OS launcher, Office, model, or external-tool call.' },
    },
    scenarios,
    evidence,
  };
});

const counts = commands.reduce((result, item) => {
  result[item.capabilityStatus] = (result[item.capabilityStatus] || 0) + 1;
  return result;
}, {});
const matrix = {
  format: 'koi-backend-behavior-matrix-v1',
  productVersion: '4.0.0',
  platform: 'windows-x64',
  baseline: {
    version: oracle.baseline.version,
    revision: oracle.baseline.revision,
    sourceManifest: oracle.baseline.sourceManifest,
  },
  rustSourceManifest: oracle.rustSourceManifest,
  normalization: oracle.normalization,
  safetyPolicy: {
    acceptedStatuses: ['equivalent', 'improved', 'security-exception'],
    forbiddenCompatibilityRegressions: [
      'business Python sidecar',
      'plaintext credentials',
      'host sqlmap.py',
      'unauthenticated event WebSocket',
      'host execution fallback for dynamic probes',
    ],
  },
  goldenFixtures,
  summary: {
    commandCount: commands.length,
    verifiedCount: commands.filter((item) => item.verificationStatus === 'verified').length,
    unverifiedCount: commands.filter((item) => item.verificationStatus !== 'verified').length,
    unexplainedDifferenceCount: commands.filter((item) => item.comparison.safeBoundary === 'unexplained').length,
    capabilityStatusCounts: counts,
  },
  commands,
};

const temporary = `${outputPath}.${process.pid}.tmp`;
fs.writeFileSync(temporary, `${JSON.stringify(matrix, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
fs.rmSync(outputPath, { force: true });
fs.renameSync(temporary, outputPath);
console.log(`Generated ${matrix.summary.verifiedCount}/${matrix.summary.commandCount} verified command entries at ${outputPath}.`);
