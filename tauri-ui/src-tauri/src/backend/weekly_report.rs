use super::config::ConfigStore;
use super::settings;
use chrono::{DateTime, Datelike, Duration, Local, NaiveDate, NaiveDateTime, Utc};
use regex::Regex;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

const CLOSED_LOOP_DAYS: i64 = 7;
const ATTACHMENT_KEYWORDS: &[&str] = &[
    "授权委托书",
    "执法调查",
    "网络架构",
    "架构图",
    "应急响应",
    "异常说明",
    "数据异常",
    "处置报告",
    "整改报告",
    "整改反馈",
    "整改材料",
    "营业执照",
    "身份证",
    "截图",
    "说明",
    "附件",
    "证明",
    "模板",
    "汇总",
    "名单",
];
const EVENT_EXCLUDED_KEYWORDS: &[&str] =
    &["授权委托书", "执法调查", "架构", "截图", "反馈", "模板"];
const EVENT_REPORT_KEYWORDS: &[&str] = &[
    "处置情况",
    "处置报告",
    "核查报告",
    "事件报告书",
    "网络安全事件报告书",
    "网络攻击事件报告书",
    "事件的报告",
    "异常出境事件",
];

#[derive(Clone, Debug, Default)]
struct CompatText(String);

impl CompatText {
    fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for CompatText {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        let text = if json_truthy(&value) {
            python_string(&value).trim().to_string()
        } else {
            String::new()
        };
        Ok(Self(text))
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct CompatBoolField {
    present: bool,
    value: bool,
}

impl<'de> Deserialize<'de> for CompatBoolField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self {
            present: true,
            value: json_truthy(&value),
        })
    }
}

#[derive(Debug, Default, Deserialize)]
struct WeeklyReportRequest {
    #[serde(default)]
    vulnerability_notice_dir: CompatText,
    #[serde(default, rename = "vulnerabilityNoticeDir")]
    vulnerability_notice_dir_alias: CompatText,
    #[serde(default)]
    event_notice_dir: CompatText,
    #[serde(default, rename = "eventNoticeDir")]
    event_notice_dir_alias: CompatText,
    #[serde(default)]
    exclude_monday_next_notice: CompatBoolField,
    #[serde(default, rename = "excludeMondayNextNotice")]
    exclude_monday_next_notice_alias: CompatBoolField,
    #[serde(default)]
    report_date: CompatText,
    #[serde(default, rename = "reportDate")]
    report_date_alias: CompatText,
    #[serde(default)]
    today: CompatText,
}

#[derive(Debug, Default, Deserialize)]
struct WeeklyReportSavedConfig {
    #[serde(default)]
    vulnerability_notice_dir: CompatText,
    #[serde(default)]
    event_notice_dir: CompatText,
    #[serde(default)]
    exclude_monday_next_notice: CompatBoolField,
}

impl WeeklyReportRequest {
    fn vulnerability_notice_dir<'a>(&'a self, saved: &'a WeeklyReportSavedConfig) -> &'a str {
        first_non_empty([
            self.vulnerability_notice_dir.as_str(),
            self.vulnerability_notice_dir_alias.as_str(),
            saved.vulnerability_notice_dir.as_str(),
        ])
    }

    fn event_notice_dir<'a>(&'a self, saved: &'a WeeklyReportSavedConfig) -> &'a str {
        first_non_empty([
            self.event_notice_dir.as_str(),
            self.event_notice_dir_alias.as_str(),
            saved.event_notice_dir.as_str(),
        ])
    }

    fn exclude_monday_next_notice(&self, saved: &WeeklyReportSavedConfig) -> bool {
        if self.exclude_monday_next_notice.present {
            self.exclude_monday_next_notice.value
        } else if self.exclude_monday_next_notice_alias.present {
            self.exclude_monday_next_notice_alias.value
        } else {
            saved.exclude_monday_next_notice.value
        }
    }

    fn report_date_text(&self) -> &str {
        first_non_empty([
            self.report_date.as_str(),
            self.report_date_alias.as_str(),
            self.today.as_str(),
        ])
    }
}

#[derive(Clone, Debug, Serialize)]
struct ClosureWindowsResponse {
    current_week_start: String,
    current_week_end: String,
    next_week_start: String,
    next_week_end: String,
    current_closure_start: String,
    current_closure_end: String,
    current_notice_start: String,
    current_notice_end: String,
    next_notice_start: String,
    next_notice_end: String,
    event_completed_start: String,
    event_completed_end: String,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct WeeklyReportOptions {
    exclude_monday_next_notice: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct WeeklyReportRecordCounts {
    vulnerability: usize,
    event: usize,
}

#[derive(Clone, Debug, Serialize)]
struct WeeklyReportSummary {
    report: String,
    current_vulnerability: Vec<String>,
    current_events: Vec<String>,
    next_companies: Vec<String>,
    windows: ClosureWindowsResponse,
    options: WeeklyReportOptions,
    records: WeeklyReportRecordCounts,
}

#[derive(Clone, Debug, Serialize)]
struct WeeklyReportResponse {
    report: String,
    status: &'static str,
    vulnerability_notice_dir: String,
    event_notice_dir: String,
    exclude_monday_next_notice: bool,
    report_date: String,
    progress: Vec<String>,
    summary: WeeklyReportSummary,
}

#[derive(Clone, Debug)]
struct NoticeRecord {
    company: String,
    notice_at: NaiveDateTime,
    closure_date: NaiveDate,
    completed_at: NaiveDateTime,
    path: String,
}

#[derive(Clone, Copy, Debug)]
struct ClosureWindows {
    current_week_start: NaiveDate,
    current_week_end: NaiveDate,
    next_week_start: NaiveDate,
    next_week_end: NaiveDate,
    current_closure_start: NaiveDate,
    current_closure_end: NaiveDate,
    current_notice_start: NaiveDate,
    current_notice_end: NaiveDate,
    next_notice_start: NaiveDate,
    next_notice_end: NaiveDate,
    event_completed_start: NaiveDate,
    event_completed_end: NaiveDate,
}

pub fn generate(store: &ConfigStore, payload: &Value, home: &Path) -> Result<Value, String> {
    let request: WeeklyReportRequest = parse_request(payload)?;
    let saved = load_saved_config(store)?;
    let vulnerability_notice_dir = request.vulnerability_notice_dir(&saved).to_string();
    let event_notice_dir = request.event_notice_dir(&saved).to_string();
    let exclude_monday_next_notice = request.exclude_monday_next_notice(&saved);
    let report_date = parse_report_date(request.report_date_text())?;
    let windows = closure_windows(report_date, exclude_monday_next_notice);
    let mut progress = Vec::new();
    let vulnerability_records = collect_notice_records(
        &vulnerability_notice_dir,
        NoticeKind::Vulnerability,
        home,
        &mut progress,
    );
    let event_records =
        collect_notice_records(&event_notice_dir, NoticeKind::Event, home, &mut progress);

    let current_vulnerability =
        unique_companies(vulnerability_records.iter().filter_map(|record| {
            (windows.current_closure_start <= record.closure_date
                && record.closure_date <= windows.current_closure_end)
                .then_some(record.company.as_str())
        }));
    let current_events = unique_companies(event_records.iter().filter_map(|record| {
        let completed = record.completed_at.date();
        (windows.event_completed_start <= completed && completed <= windows.event_completed_end)
            .then_some(record.company.as_str())
    }));
    let next_companies = unique_companies(vulnerability_records.iter().filter_map(|record| {
        let noticed = record.notice_at.date();
        (windows.next_notice_start <= noticed && noticed <= windows.next_notice_end)
            .then_some(record.company.as_str())
    }));

    let report = [
        "本周：".to_string(),
        "针对已通报漏洞做出整改的企业有：".to_string(),
        format_company_list(&current_vulnerability),
        "对涉及发生网络安全事件完成整改处置的有：".to_string(),
        format_company_list(&current_events),
        String::new(),
        "下周：".to_string(),
        "将针对通报过并进行处置的企业有：".to_string(),
        format_company_list(&next_companies),
    ]
    .join("\n");

    if !vulnerability_notice_dir.is_empty() || !event_notice_dir.is_empty() {
        settings::weekly_report_set(
            store,
            &json!({
                "vulnerability_notice_dir": vulnerability_notice_dir,
                "event_notice_dir": event_notice_dir,
                "exclude_monday_next_notice": exclude_monday_next_notice,
            }),
        )?;
    }

    let summary = WeeklyReportSummary {
        report: report.clone(),
        current_vulnerability,
        current_events,
        next_companies,
        windows: windows.as_response(),
        options: WeeklyReportOptions {
            exclude_monday_next_notice,
        },
        records: WeeklyReportRecordCounts {
            vulnerability: vulnerability_records.len(),
            event: event_records.len(),
        },
    };

    serialize_response(WeeklyReportResponse {
        report,
        status: "success",
        vulnerability_notice_dir,
        event_notice_dir,
        exclude_monday_next_notice,
        report_date: report_date.format("%Y-%m-%d").to_string(),
        progress,
        summary,
    })
}

fn load_saved_config(store: &ConfigStore) -> Result<WeeklyReportSavedConfig, String> {
    let config = store.load()?;
    let weekly = config
        .as_object()
        .and_then(|root| root.get("weekly_report"))
        .unwrap_or(&Value::Null);
    parse_request(weekly)
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum NoticeKind {
    Vulnerability,
    Event,
}

fn closure_windows(today: NaiveDate, exclude_monday_next_notice: bool) -> ClosureWindows {
    let week_start = today - Duration::days(i64::from(today.weekday().num_days_from_monday()));
    let week_end = week_start + Duration::days(6);
    let current_closure_end = today.min(week_end);
    ClosureWindows {
        current_week_start: week_start,
        current_week_end: week_end,
        next_week_start: week_start + Duration::days(7),
        next_week_end: week_start + Duration::days(13),
        current_closure_start: week_start,
        current_closure_end,
        current_notice_start: week_start - Duration::days(CLOSED_LOOP_DAYS),
        current_notice_end: current_closure_end - Duration::days(CLOSED_LOOP_DAYS),
        next_notice_start: week_start + Duration::days(i64::from(exclude_monday_next_notice)),
        next_notice_end: week_end,
        event_completed_start: week_start,
        event_completed_end: week_end,
    }
}

impl ClosureWindows {
    fn as_response(self) -> ClosureWindowsResponse {
        ClosureWindowsResponse {
            current_week_start: iso_date(self.current_week_start),
            current_week_end: iso_date(self.current_week_end),
            next_week_start: iso_date(self.next_week_start),
            next_week_end: iso_date(self.next_week_end),
            current_closure_start: iso_date(self.current_closure_start),
            current_closure_end: iso_date(self.current_closure_end),
            current_notice_start: iso_date(self.current_notice_start),
            current_notice_end: iso_date(self.current_notice_end),
            next_notice_start: iso_date(self.next_notice_start),
            next_notice_end: iso_date(self.next_notice_end),
            event_completed_start: iso_date(self.event_completed_start),
            event_completed_end: iso_date(self.event_completed_end),
        }
    }
}

fn collect_notice_records(
    root_text: &str,
    kind: NoticeKind,
    home: &Path,
    progress: &mut Vec<String>,
) -> Vec<NoticeRecord> {
    let trimmed = root_text.trim().trim_matches('"');
    if trimmed.is_empty() {
        return Vec::new();
    }
    let root = expand_home(trimmed, home);
    if !root.exists() {
        progress.push(format!("通报路径不存在: {}", root.display()));
        return Vec::new();
    }
    if kind == NoticeKind::Event {
        return collect_event_records(&root, progress);
    }

    let mut entries = Vec::new();
    if root.is_file() {
        entries.push(root.clone());
    } else {
        collect_candidate_files(&root, &mut entries, is_candidate_vulnerability_file);
    }
    let mut records = entries
        .into_iter()
        .filter_map(|entry| {
            let company = extract_company_name(&entry, &root);
            if company.is_empty() {
                return None;
            }
            let notice_at = extract_notice_date(&entry);
            Some(NoticeRecord {
                company,
                notice_at,
                closure_date: notice_at.date() + Duration::days(CLOSED_LOOP_DAYS),
                completed_at: notice_at + Duration::days(CLOSED_LOOP_DAYS),
                path: path_text(&entry),
            })
        })
        .collect::<Vec<_>>();
    records.sort_by(|left, right| {
        left.closure_date
            .cmp(&right.closure_date)
            .then_with(|| left.company.cmp(&right.company))
            .then_with(|| left.path.cmp(&right.path))
    });
    progress.push(format!(
        "vulnerability 通报目录提取企业 {} 条: {}",
        records.len(),
        root.display()
    ));
    records
}

fn collect_event_records(root: &Path, progress: &mut Vec<String>) -> Vec<NoticeRecord> {
    if root.is_file() {
        let mut records = Vec::new();
        if is_candidate_event_file(
            root.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or(""),
        ) {
            let company = extract_company_name(root, root.parent().unwrap_or(root));
            if !company.is_empty() {
                let completed_at = extract_notice_date(root);
                records.push(NoticeRecord {
                    company,
                    notice_at: completed_at,
                    closure_date: completed_at.date(),
                    completed_at,
                    path: path_text(root),
                });
            }
        }
        return records;
    }

    let mut records = Vec::new();
    collect_event_directories(root, root, &mut records);
    records.sort_by(|left, right| {
        left.completed_at
            .cmp(&right.completed_at)
            .then_with(|| left.company.cmp(&right.company))
            .then_with(|| left.path.cmp(&right.path))
    });
    progress.push(format!(
        "event 应急处置目录提取企业 {} 条: {}",
        records.len(),
        root.display()
    ));
    records
}

fn collect_event_directories(root: &Path, directory: &Path, records: &mut Vec<NoticeRecord>) {
    let (directories, files) = sorted_directory_entries(directory);
    let candidate_files = files
        .into_iter()
        .filter(|path| {
            path.file_name()
                .and_then(|value| value.to_str())
                .is_some_and(is_candidate_event_file)
        })
        .collect::<Vec<_>>();
    if !candidate_files.is_empty() {
        let directory_name = directory
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("");
        let mut company = extract_company_from_text(directory_name, true);
        if company.is_empty() {
            company = extract_company_name(&candidate_files[0], root);
        }
        if !company.is_empty() {
            let completed_at = candidate_files
                .iter()
                .map(|path| extract_notice_date(path))
                .max()
                .unwrap_or_else(local_now);
            records.push(NoticeRecord {
                company,
                notice_at: completed_at,
                closure_date: completed_at.date(),
                completed_at,
                path: path_text(directory),
            });
        }
    }
    for child in directories {
        collect_event_directories(root, &child, records);
    }
}

fn collect_candidate_files(root: &Path, result: &mut Vec<PathBuf>, predicate: fn(&str) -> bool) {
    let (directories, files) = sorted_directory_entries(root);
    result.extend(files.into_iter().filter(|path| {
        path.file_name()
            .and_then(|value| value.to_str())
            .is_some_and(predicate)
    }));
    for directory in directories {
        collect_candidate_files(&directory, result, predicate);
    }
}

fn sorted_directory_entries(directory: &Path) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(directory) else {
        return (Vec::new(), Vec::new());
    };
    let mut directories = Vec::new();
    let mut files = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        match entry.file_type() {
            Ok(kind) if kind.is_dir() => directories.push(path),
            Ok(kind) if kind.is_symlink() && path.is_dir() => {}
            _ => files.push(path),
        }
    }
    directories.sort_by(|left, right| left.file_name().cmp(&right.file_name()));
    files.sort_by(|left, right| left.file_name().cmp(&right.file_name()));
    (directories, files)
}

fn is_candidate_vulnerability_file(file_name: &str) -> bool {
    if file_name.starts_with("~$") || !has_notice_extension(file_name) {
        return false;
    }
    let stem = file_stem(file_name);
    if contains_any(stem, ATTACHMENT_KEYWORDS) {
        return false;
    }
    if stem.contains("隐患通报") || stem.contains("安全漏洞通报") {
        return true;
    }
    contains_any(stem, &["存在", "感染风险", "流量异常"])
        && contains_any(
            stem,
            &[
                "漏洞",
                "安全",
                "风险",
                "木马",
                "未授权",
                "弱口令",
                "信息泄露",
            ],
        )
}

fn is_candidate_event_file(file_name: &str) -> bool {
    if file_name.starts_with("~$") || !has_notice_extension(file_name) {
        return false;
    }
    let stem = file_stem(file_name);
    !contains_any(stem, EVENT_EXCLUDED_KEYWORDS) && contains_any(stem, EVENT_REPORT_KEYWORDS)
}

fn has_notice_extension(file_name: &str) -> bool {
    Path::new(file_name)
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .is_some_and(|value| matches!(value.as_str(), "doc" | "docx" | "wps" | "pdf"))
}

fn file_stem(file_name: &str) -> &str {
    Path::new(file_name)
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(file_name)
}

fn extract_notice_date(path: &Path) -> NaiveDateTime {
    if let Some(stem) = path.file_stem().and_then(|value| value.to_str()) {
        if let Some(parsed) = parse_date_text(stem) {
            return parsed;
        }
    }
    for part in path.components().rev() {
        if let Some(parsed) = parse_date_text(&part.as_os_str().to_string_lossy()) {
            return parsed;
        }
    }
    path.metadata()
        .and_then(|metadata| metadata.modified())
        .ok()
        .map(|modified| DateTime::<Local>::from(modified).naive_local())
        .unwrap_or_else(local_now)
}

fn parse_date_text(text: &str) -> Option<NaiveDateTime> {
    let runs = digit_run_regex()
        .find_iter(text)
        .map(|matched| matched.as_str())
        .collect::<Vec<_>>();
    for raw in &runs {
        if raw.len() == 14 && (raw.starts_with("19") || raw.starts_with("20")) {
            if let Some(value) = parse_compact_date(&raw[..8]) {
                return Some(value);
            }
        }
    }
    for raw in &runs {
        if raw.len() == 8 && (raw.starts_with("19") || raw.starts_with("20")) {
            if let Some(value) = parse_compact_date(raw) {
                return Some(value);
            }
        }
    }
    for raw in &runs {
        let valid_epoch = match raw.len() {
            10 | 13 => {
                raw.as_bytes()
                    .first()
                    .is_some_and(|first| matches!(first, b'2'..=b'9'))
                    || raw.starts_with("16")
                    || raw.starts_with("17")
                    || raw.starts_with("18")
                    || raw.starts_with("19")
            }
            _ => false,
        };
        if !valid_epoch {
            continue;
        }
        let Ok(mut timestamp) = raw.parse::<i64>() else {
            continue;
        };
        if raw.len() == 13 {
            timestamp /= 1_000;
        }
        if let Some(value) = DateTime::<Utc>::from_timestamp(timestamp, 0) {
            let local = value.with_timezone(&Local).naive_local();
            if (2000..=2100).contains(&local.year()) {
                return Some(local);
            }
        }
    }
    if let Some(captures) = formatted_date_regex().captures(text) {
        if let Some(value) = date_from_captures(&captures, 1, 2, 3) {
            return Some(value);
        }
    }
    if let Some(captures) = month_day_regex().captures(text) {
        if let Some(value) = date_from_parts(
            Local::now().year(),
            captures.get(1)?.as_str().parse().ok()?,
            captures.get(2)?.as_str().parse().ok()?,
        ) {
            return Some(value);
        }
    }
    None
}

fn parse_compact_date(raw: &str) -> Option<NaiveDateTime> {
    date_from_parts(
        raw.get(0..4)?.parse().ok()?,
        raw.get(4..6)?.parse().ok()?,
        raw.get(6..8)?.parse().ok()?,
    )
}

fn date_from_captures(
    captures: &regex::Captures<'_>,
    year: usize,
    month: usize,
    day: usize,
) -> Option<NaiveDateTime> {
    date_from_parts(
        captures.get(year)?.as_str().parse().ok()?,
        captures.get(month)?.as_str().parse().ok()?,
        captures.get(day)?.as_str().parse().ok()?,
    )
}

fn date_from_parts(year: i32, month: u32, day: u32) -> Option<NaiveDateTime> {
    NaiveDate::from_ymd_opt(year, month, day)?.and_hms_opt(0, 0, 0)
}

fn extract_company_name(path: &Path, root: &Path) -> String {
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    let company = extract_company_from_text(stem, is_notice_title(stem));
    if !company.is_empty() {
        return company;
    }

    let relative = path.strip_prefix(root).unwrap_or(path);
    let mut parents = relative
        .parent()
        .map(|parent| {
            parent
                .components()
                .filter_map(|part| part.as_os_str().to_str())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    parents.reverse();
    for parent in parents {
        let company = extract_company_from_text(parent, true);
        if !company.is_empty() {
            return company;
        }
    }
    String::new()
}

fn is_notice_title(text: &str) -> bool {
    !contains_any(text, ATTACHMENT_KEYWORDS)
        && text.contains("通报")
        && contains_any(text, &["关于", "漏洞", "事件"])
}

fn extract_company_from_text(text: &str, allow_directory_fallback: bool) -> String {
    let value = normalize_notice_text(text);
    if value.is_empty() || contains_any(&value, ATTACHMENT_KEYWORDS) {
        return String::new();
    }
    if let Some(matched) = company_regex()
        .captures(&value)
        .and_then(|captures| captures.get(1))
    {
        return clean_company_name(matched.as_str());
    }
    if let Some(matched) = english_company_regex()
        .captures(&value)
        .and_then(|captures| captures.get(1))
    {
        return clean_company_name(matched.as_str());
    }

    let fallback = clean_company_name(&value);
    let length = fallback.chars().count();
    if allow_directory_fallback
        && (4..=40).contains(&length)
        && fallback
            .chars()
            .any(|character| ('\u{4e00}'..='\u{9fa5}').contains(&character))
        && !looks_like_date_or_bucket(&fallback)
        && !contains_any(
            &fallback,
            &[
                ATTACHMENT_KEYWORDS,
                &["通报", "漏洞", "事件", "处置", "整改"],
            ]
            .concat(),
        )
        && !company_count_regex().is_match(&fallback)
    {
        return fallback;
    }
    String::new()
}

fn normalize_notice_text(text: &str) -> String {
    let value = extension_regex().replace(text, "");
    let value = leading_noise_regex().replace(&value, "");
    let value = title_prefix_regex().replace(&value, "");
    let mut value = value.into_owned();
    truncate_at_first(&mut value, &["所属", "旗下", "名下"]);
    for prefix in ["鄞州区", "浙江省宁波市", "浙江省"] {
        if let Some(remainder) = value.strip_prefix(prefix) {
            value = remainder.trim_start_matches(['-', '_', '/']).to_string();
            break;
        }
    }
    truncate_at_first(
        &mut value,
        &[
            "存在",
            "发生",
            "网络安全事件",
            "安全漏洞",
            "漏洞通报",
            "安全通报",
            "通报",
            "处置",
            "整改",
            "报告",
            "复测",
        ],
    );
    trim_company_punctuation(&value).to_string()
}

fn clean_company_name(company: &str) -> String {
    let trimmed = company.trim();
    let without_prefix = company_prefix_regex().replace(trimmed, "");
    trim_company_punctuation(&without_prefix).to_string()
}

fn looks_like_date_or_bucket(text: &str) -> bool {
    let value = text.trim();
    value.is_empty() || parse_date_text(value).is_some() || date_bucket_regex().is_match(value)
}

fn unique_companies<'a>(companies: impl Iterator<Item = &'a str>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut result = Vec::new();
    for company in companies {
        let name = clean_company_name(company);
        if !name.is_empty() && seen.insert(name.clone()) {
            result.push(name);
        }
    }
    result
}

fn format_company_list(companies: &[String]) -> String {
    if companies.is_empty() {
        "无".to_string()
    } else {
        companies
            .iter()
            .enumerate()
            .map(|(index, company)| format!("{}.{}", index + 1, company))
            .collect::<Vec<_>>()
            .join("\n")
    }
}

fn parse_report_date(raw: &str) -> Result<NaiveDate, String> {
    if raw.is_empty() {
        return Ok(Local::now().date_naive());
    }
    let prefix = raw.chars().take(10).collect::<String>();
    let pieces = prefix.split('-').collect::<Vec<_>>();
    let parsed = if pieces.len() == 3 && pieces[0].len() == 4 {
        pieces[0]
            .parse()
            .ok()
            .zip(pieces[1].parse().ok())
            .zip(pieces[2].parse().ok())
            .and_then(|((year, month), day)| NaiveDate::from_ymd_opt(year, month, day))
    } else {
        None
    };
    parsed.ok_or_else(|| format!("周报基准日期格式错误，应为 YYYY-MM-DD: {raw}"))
}

fn first_non_empty<const N: usize>(values: [&str; N]) -> &str {
    values
        .into_iter()
        .find(|value| !value.is_empty())
        .unwrap_or_default()
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(false) => false,
        Value::Number(number) => number.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
        Value::Bool(true) => true,
    }
}

fn parse_request<T>(payload: &Value) -> Result<T, String>
where
    T: DeserializeOwned + Default,
{
    if !payload.is_object() {
        return Ok(T::default());
    }
    serde_json::from_value(payload.clone())
        .map_err(|error| format!("周报请求字段格式错误: {error}"))
}

fn serialize_response<T>(response: T) -> Result<Value, String>
where
    T: Serialize,
{
    serde_json::to_value(response).map_err(|error| format!("响应序列化失败: {error}"))
}

fn expand_home(value: &str, home: &Path) -> PathBuf {
    if value == "~" {
        return home.to_path_buf();
    }
    if let Some(remainder) = value
        .strip_prefix("~/")
        .or_else(|| value.strip_prefix("~\\"))
    {
        return home.join(remainder);
    }
    PathBuf::from(value)
}

fn path_text(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

fn iso_date(value: NaiveDate) -> String {
    value.format("%Y-%m-%d").to_string()
}

fn local_now() -> NaiveDateTime {
    Local::now().naive_local()
}

fn contains_any(value: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| value.contains(needle))
}

fn truncate_at_first(value: &mut String, needles: &[&str]) {
    if let Some(index) = needles.iter().filter_map(|needle| value.find(needle)).min() {
        value.truncate(index);
    }
}

fn trim_company_punctuation(value: &str) -> &str {
    value.trim_matches(|character: char| {
        character.is_whitespace()
            || matches!(
                character,
                '-' | '_'
                    | '—'
                    | '（'
                    | '）'
                    | '('
                    | ')'
                    | '['
                    | ']'
                    | '【'
                    | '】'
                    | '《'
                    | '》'
                    | '、'
                    | '，'
                    | ','
                    | '。'
                    | '.'
            )
    })
}

fn digit_run_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| Regex::new(r"[0-9]+").expect("valid digit-run regex"))
}

fn formatted_date_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(
            r"(?:^|[^0-9])((?:19|20)[0-9]{2})[-._/年]?\s*([0-9]{1,2})[-._/月]\s*([0-9]{1,2})日?(?:[^0-9]|$)",
        )
        .expect("valid formatted-date regex")
    })
}

fn month_day_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(r"(?:^|[^0-9])([0-9]{1,2})[.月]([0-9]{1,2})日?(?:[^0-9]|$)")
            .expect("valid month-day regex")
    })
}

fn company_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(
            r"([\x{4e00}-\x{9fa5}A-Za-z0-9（）()·&＆\-]{2,80}?(?:股份有限公司|集团有限公司|有限责任公司|有限公司|职业培训学校|培训学校|学校|医院有限公司|医院|研究院|协会|中心|集团|公司))",
        )
        .expect("valid company regex")
    })
}

fn english_company_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(r"([A-Za-z]+(?:\s+(?:Inc|Corp|Ltd|Co|Company|Group|Tech|Technology)))")
            .expect("valid English-company regex")
    })
}

fn extension_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| Regex::new(r"\.[A-Za-z0-9]{1,8}$").expect("valid extension regex"))
}

fn leading_noise_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| Regex::new(r"^[\d\s._\-（）()]+").expect("valid leading-noise regex"))
}

fn title_prefix_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(r"^(?:关于|附件\d*[:：]?|【[^】]*】)").expect("valid title-prefix regex")
    })
}

fn company_prefix_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(r"^(?:关于|附件\d*[:：]?|\d+[\s._\-]*)").expect("valid company-prefix regex")
    })
}

fn company_count_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| Regex::new(r"\d+个|\d+家|企业").expect("valid company-count regex"))
}

fn date_bucket_regex() -> &'static Regex {
    static VALUE: OnceLock<Regex> = OnceLock::new();
    VALUE.get_or_init(|| {
        Regex::new(r"^[\d\s._\-（）()年月日至周第批]+$").expect("valid date-bucket regex")
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn closure_window_matches_python_monday_rules() {
        let monday = NaiveDate::from_ymd_opt(2026, 7, 6).unwrap();
        let windows = closure_windows(monday, false);
        assert_eq!(windows.current_week_start, monday);
        assert_eq!(
            windows.current_week_end,
            NaiveDate::from_ymd_opt(2026, 7, 12).unwrap()
        );
        assert_eq!(
            windows.current_notice_start,
            NaiveDate::from_ymd_opt(2026, 6, 29).unwrap()
        );
        assert_eq!(
            windows.current_notice_end,
            NaiveDate::from_ymd_opt(2026, 6, 29).unwrap()
        );
        assert_eq!(windows.next_notice_start, monday);
        assert_eq!(
            closure_windows(monday, true).next_notice_start,
            NaiveDate::from_ymd_opt(2026, 7, 7).unwrap()
        );
    }

    #[test]
    fn date_and_company_parsing_match_supported_python_shapes() {
        assert_eq!(
            parse_date_text("notice-20260706123456-company")
                .unwrap()
                .date(),
            NaiveDate::from_ymd_opt(2026, 7, 6).unwrap()
        );
        assert_eq!(
            parse_date_text("2026年7月7日").unwrap().date(),
            NaiveDate::from_ymd_opt(2026, 7, 7).unwrap()
        );
        assert_eq!(
            extract_company_from_text("20260706关于宁波甲有限公司存在安全漏洞通报", true),
            "宁波甲有限公司"
        );
        assert_eq!(
            extract_company_from_text("浙江省宁波市宁波乙有限公司安全漏洞通报", true),
            "宁波乙有限公司"
        );
        assert!(extract_company_from_text("2026年第1批企业汇总", true).is_empty());
    }

    #[test]
    fn report_date_accepts_python_aliases_and_short_months() {
        let camel: WeeklyReportRequest = parse_request(&json!({"reportDate": "2026-7-6"})).unwrap();
        assert_eq!(
            parse_report_date(camel.report_date_text()).unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 6).unwrap()
        );
        let legacy: WeeklyReportRequest =
            parse_request(&json!({"today": "2026-07-06T12:00:00"})).unwrap();
        assert_eq!(
            parse_report_date(legacy.report_date_text()).unwrap(),
            NaiveDate::from_ymd_opt(2026, 7, 6).unwrap()
        );
        let invalid: WeeklyReportRequest = parse_request(&json!({"report_date": "bad"})).unwrap();
        assert_eq!(
            parse_report_date(invalid.report_date_text()).unwrap_err(),
            "周报基准日期格式错误，应为 YYYY-MM-DD: bad"
        );
    }

    #[test]
    fn request_aliases_and_explicit_null_keep_legacy_precedence() {
        let request: WeeklyReportRequest = parse_request(&json!({
            "vulnerabilityNoticeDir": " camel/path ",
            "eventNoticeDir": " event/path ",
            "exclude_monday_next_notice": null,
            "excludeMondayNextNotice": true
        }))
        .unwrap();
        let saved: WeeklyReportSavedConfig = parse_request(&json!({
            "vulnerability_notice_dir": "saved/vulnerability",
            "event_notice_dir": "saved/event",
            "exclude_monday_next_notice": true
        }))
        .unwrap();
        assert_eq!(request.vulnerability_notice_dir(&saved), "camel/path");
        assert_eq!(request.event_notice_dir(&saved), "event/path");
        assert!(!request.exclude_monday_next_notice(&saved));

        let empty: WeeklyReportRequest = parse_request(&Value::Null).unwrap();
        assert_eq!(
            empty.vulnerability_notice_dir(&saved),
            "saved/vulnerability"
        );
    }

    #[test]
    fn saved_config_is_typed_directly_from_the_persisted_section() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("koi-weekly-typed-config-{unique}"));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("config.json");
        fs::write(
            &path,
            serde_json::to_vec(&json!({
                "weekly_report": {
                    "vulnerability_notice_dir": 42,
                    "event_notice_dir": " event/path ",
                    "exclude_monday_next_notice": "yes"
                }
            }))
            .unwrap(),
        )
        .unwrap();

        let saved = load_saved_config(&ConfigStore::new(path)).unwrap();
        assert_eq!(saved.vulnerability_notice_dir.as_str(), "42");
        assert_eq!(saved.event_notice_dir.as_str(), "event/path");
        assert!(saved.exclude_monday_next_notice.value);
        fs::remove_dir_all(root).unwrap();
    }
}
