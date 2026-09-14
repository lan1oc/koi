use rusqlite::{backup::Backup, params, Connection, TransactionBehavior};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub(crate) const CLASSIFICATION_SCHEMA_VERSION: i64 = 1;
const SQLITE_BUSY_TIMEOUT: Duration = Duration::from_secs(5);

static NEXT_BACKUP_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, PartialEq, Eq)]
struct GroupState {
    name: String,
    companies: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct ClassificationGroupResponse {
    name: String,
    companies: Vec<String>,
    company_count: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct ClassificationResponse {
    success: bool,
    message: String,
    db_path: String,
    total_groups: usize,
    total_companies: usize,
    groups: Vec<ClassificationGroupResponse>,
}

#[derive(Debug, Clone, Default)]
struct CompatText(String);

impl<'de> Deserialize<'de> for CompatText {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self(if python_truthy(&value) {
            python_string(&value).trim().to_string()
        } else {
            String::new()
        }))
    }
}

#[derive(Debug, Clone, Default)]
struct CompatStringCandidate {
    truthy: bool,
    values: Vec<String>,
}

impl<'de> Deserialize<'de> for CompatStringCandidate {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        let truthy = python_truthy(&value);
        let values = match &value {
            Value::Array(values) => values
                .iter()
                .map(python_string)
                .filter(|value| !value.trim().is_empty())
                .map(|value| value.trim().to_string())
                .collect(),
            value if truthy => python_string(value)
                .lines()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .collect(),
            _ => Vec::new(),
        };
        Ok(Self { truthy, values })
    }
}

#[derive(Debug, Default, Deserialize)]
struct GroupAddRequest {
    #[serde(default)]
    group_name: CompatText,
}

#[derive(Debug, Default, Deserialize)]
struct GroupRenameRequest {
    #[serde(default)]
    old_name: CompatText,
    #[serde(default)]
    new_name: CompatText,
}

#[derive(Debug, Default, Deserialize)]
struct GroupDeleteRequest {
    #[serde(default)]
    group_name: CompatText,
}

#[derive(Debug, Default, Deserialize)]
struct CompanyNameAliases {
    #[serde(default)]
    company_names: CompatStringCandidate,
    #[serde(default)]
    company_name: CompatStringCandidate,
    #[serde(default)]
    companies: CompatStringCandidate,
    #[serde(default)]
    companies_text: CompatStringCandidate,
    #[serde(default)]
    text: CompatStringCandidate,
}

impl CompanyNameAliases {
    fn select(&self, candidates: [&CompatStringCandidate; 5]) -> Vec<String> {
        candidates
            .into_iter()
            .find(|candidate| candidate.truthy)
            .map(|candidate| candidate.values.clone())
            .unwrap_or_default()
    }

    fn add_names(&self) -> Vec<String> {
        self.select([
            &self.company_names,
            &self.companies,
            &self.companies_text,
            &self.text,
            &self.company_name,
        ])
    }

    fn delete_names(&self) -> Vec<String> {
        self.select([
            &self.company_names,
            &self.company_name,
            &self.companies,
            &self.companies_text,
            &self.text,
        ])
    }

    fn move_names(&self) -> Vec<String> {
        self.select([
            &self.company_names,
            &self.companies,
            &self.companies_text,
            &self.text,
            &self.company_name,
        ])
    }
}

#[derive(Debug, Default, Deserialize)]
struct CompanyAddRequest {
    #[serde(default)]
    group_name: CompatText,
    #[serde(flatten)]
    names: CompanyNameAliases,
}

#[derive(Debug, Default, Deserialize)]
struct CompanyRenameRequest {
    #[serde(default)]
    group_name: CompatText,
    #[serde(default)]
    old_name: CompatText,
    #[serde(default)]
    new_name: CompatText,
}

#[derive(Debug, Default, Deserialize)]
struct CompanyDeleteRequest {
    #[serde(default)]
    group_name: CompatText,
    #[serde(flatten)]
    names: CompanyNameAliases,
}

#[derive(Debug, Default, Deserialize)]
struct CompanyMoveRequest {
    #[serde(default)]
    source_group: CompatText,
    #[serde(default)]
    target_group: CompatText,
    #[serde(flatten)]
    names: CompanyNameAliases,
}

fn parse_request<T: serde::de::DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn required_compat_text(value: CompatText, message: &str) -> Result<String, String> {
    if value.0.is_empty() {
        Err(message.to_string())
    } else {
        Ok(value.0)
    }
}

fn serialize_response(response: ClassificationResponse) -> Result<Value, String> {
    serde_json::to_value(response).map_err(|error| format!("分类响应序列化失败: {error}"))
}

/// SQLite-backed enterprise classification storage.
///
/// Connections are deliberately short lived. The mutex serializes the small
/// read/modify/write operations so two UI requests cannot reorder one another.
pub struct ClassificationStore {
    path: PathBuf,
    access: Mutex<()>,
}

impl ClassificationStore {
    pub fn new(path: PathBuf) -> Result<Self, String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("创建分类数据库目录失败: {error}"))?;
        }
        let had_database = fs::metadata(&path)
            .map(|metadata| metadata.is_file() && metadata.len() > 0)
            .unwrap_or(false);
        let store = Self {
            path,
            access: Mutex::new(()),
        };
        store.initialize_schema(had_database)?;
        Ok(store)
    }

    /// Create a transactionally consistent snapshot without replacing an
    /// existing destination. This uses SQLite's online backup API so callers
    /// never copy a live database file directly.
    #[allow(dead_code)] // Maintenance API; the 97-command production contract must stay fixed.
    pub fn backup_to(&self, destination: &Path) -> Result<PathBuf, String> {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let connection = open_connection(&self.path)?;
        backup_connection_to(&connection, &self.path, destination)?;
        Ok(destination.to_path_buf())
    }

    pub fn get(&self) -> Result<Value, String> {
        let groups = self.read_groups()?;
        let total = groups
            .iter()
            .map(|group| group.companies.len())
            .sum::<usize>();
        self.state_response(
            format!("已加载 {} 个分组，{} 家企业", groups.len(), total),
            groups,
        )
    }

    pub(crate) fn company_group_pairs(&self) -> Result<Vec<(String, String)>, String> {
        Ok(self
            .read_groups()?
            .into_iter()
            .flat_map(|group| {
                let group_name = group.name;
                group
                    .companies
                    .into_iter()
                    .map(move |company| (company, group_name.clone()))
            })
            .collect())
    }

    pub fn group_add(&self, payload: &Value) -> Result<Value, String> {
        let request: GroupAddRequest = parse_request(payload)?;
        let group_name = required_compat_text(request.group_name, "请输入分组名称")?;
        let mut groups = self.read_groups()?;
        if groups.iter().any(|group| group.name == group_name) {
            return Err(format!("分组已存在: {group_name}"));
        }
        groups.push(GroupState {
            name: group_name.clone(),
            companies: Vec::new(),
        });
        self.write_groups(&groups)?;
        self.state_response(format!("已添加分组: {group_name}"), groups)
    }

    pub fn group_rename(&self, payload: &Value) -> Result<Value, String> {
        let request: GroupRenameRequest = parse_request(payload)?;
        let old_name = required_compat_text(request.old_name, "请选择要重命名的分组")?;
        let new_name = required_compat_text(request.new_name, "请输入新分组名称")?;
        let mut groups = self.read_groups()?;
        if old_name == new_name {
            return self.state_response("分组名称未变化".to_string(), groups);
        }
        if groups.iter().any(|group| group.name == new_name) {
            return Err(format!("分组已存在: {new_name}"));
        }
        let Some(group) = groups.iter_mut().find(|group| group.name == old_name) else {
            return Err(format!("分组不存在: {old_name}"));
        };
        group.name = new_name.clone();
        self.write_groups(&groups)?;
        self.state_response(format!("已重命名分组: {old_name} -> {new_name}"), groups)
    }

    pub fn group_delete(&self, payload: &Value) -> Result<Value, String> {
        let request: GroupDeleteRequest = parse_request(payload)?;
        let group_name = required_compat_text(request.group_name, "请选择要删除的分组")?;
        let groups = self.read_groups()?;
        let new_groups: Vec<_> = groups
            .iter()
            .filter(|group| group.name != group_name)
            .cloned()
            .collect();
        if new_groups.len() == groups.len() {
            return Err(format!("分组不存在: {group_name}"));
        }
        self.write_groups(&new_groups)?;
        self.state_response(format!("已删除分组: {group_name}"), new_groups)
    }

    pub fn company_add(&self, payload: &Value) -> Result<Value, String> {
        let request: CompanyAddRequest = parse_request(payload)?;
        let group_name = required_compat_text(request.group_name, "请选择目标分组")?;
        let company_names = request.names.add_names();
        if company_names.is_empty() {
            return Err("请输入企业名称".to_string());
        }

        let mut groups = self.read_groups()?;
        let group = find_group_mut(&mut groups, &group_name)?;
        let mut existing: HashSet<String> = group.companies.iter().cloned().collect();
        let mut added = 0;
        for company_name in company_names {
            if existing.insert(company_name.clone()) {
                group.companies.push(company_name);
                added += 1;
            }
        }
        self.write_groups(&groups)?;
        self.state_response(format!("已添加 {added} 家企业到 {group_name}"), groups)
    }

    pub fn company_rename(&self, payload: &Value) -> Result<Value, String> {
        let request: CompanyRenameRequest = parse_request(payload)?;
        let group_name = required_compat_text(request.group_name, "请选择目标分组")?;
        let old_name = required_compat_text(request.old_name, "请选择要修改的企业")?;
        let new_name = required_compat_text(request.new_name, "请输入新企业名称")?;
        let mut groups = self.read_groups()?;
        if !groups.iter().any(|group| group.name == group_name) {
            return Err(format!("分组不存在: {group_name}"));
        }
        if old_name == new_name {
            return self.state_response("企业名称未变化".to_string(), groups);
        }
        let group = find_group_mut(&mut groups, &group_name)?;
        if group.companies.iter().any(|company| company == &new_name) {
            return Err(format!("企业已存在: {new_name}"));
        }
        let Some(company) = group
            .companies
            .iter_mut()
            .find(|company| company.as_str() == old_name)
        else {
            return Err(format!("企业不存在: {old_name}"));
        };
        *company = new_name.clone();
        self.write_groups(&groups)?;
        self.state_response(format!("已修改企业名称: {old_name} -> {new_name}"), groups)
    }

    pub fn company_delete(&self, payload: &Value) -> Result<Value, String> {
        let request: CompanyDeleteRequest = parse_request(payload)?;
        let group_name = required_compat_text(request.group_name, "请选择目标分组")?;
        let company_names = request.names.delete_names();
        if company_names.is_empty() {
            return Err("请输入企业名称".to_string());
        }
        let selected: HashSet<String> = company_names.into_iter().collect();
        let mut groups = self.read_groups()?;
        let group = find_group_mut(&mut groups, &group_name)?;
        let before = group.companies.len();
        group
            .companies
            .retain(|company| !selected.contains(company));
        let removed = before.saturating_sub(group.companies.len());
        if removed == 0 {
            return Err("未找到要删除的企业".to_string());
        }
        self.write_groups(&groups)?;
        self.state_response(format!("已删除 {removed} 家企业"), groups)
    }

    pub fn company_move(&self, payload: &Value) -> Result<Value, String> {
        let request: CompanyMoveRequest = parse_request(payload)?;
        let source_group_name = required_compat_text(request.source_group, "请选择源分组")?;
        let target_group_name = required_compat_text(request.target_group, "请选择目标分组")?;
        let company_names = request.names.move_names();
        if company_names.is_empty() {
            return Err("请输入企业名称".to_string());
        }
        if source_group_name == target_group_name {
            return self.state_response("源分组和目标分组相同".to_string(), self.read_groups()?);
        }

        let selected: HashSet<String> = company_names.into_iter().collect();
        let mut groups = self.read_groups()?;
        let source_index = groups
            .iter()
            .position(|group| group.name == source_group_name)
            .ok_or_else(|| format!("分组不存在: {source_group_name}"))?;
        let target_index = groups
            .iter()
            .position(|group| group.name == target_group_name)
            .ok_or_else(|| format!("分组不存在: {target_group_name}"))?;

        let mut moved = Vec::new();
        let mut remaining = Vec::new();
        for company in groups[source_index].companies.drain(..) {
            if selected.contains(&company) {
                moved.push(company);
            } else {
                remaining.push(company);
            }
        }
        if moved.is_empty() {
            return Err("未找到要移动的企业".to_string());
        }
        groups[source_index].companies = remaining;
        let target_companies = &mut groups[target_index].companies;
        let target_seen: HashSet<String> = target_companies.iter().cloned().collect();
        for company in &moved {
            if !target_seen.contains(company) {
                target_companies.push(company.clone());
            }
        }
        self.write_groups(&groups)?;
        self.state_response(
            format!("已移动 {} 家企业到 {target_group_name}", moved.len()),
            groups,
        )
    }

    fn state_response(&self, message: String, groups: Vec<GroupState>) -> Result<Value, String> {
        let mut response_groups = Vec::new();
        for group in groups {
            let name = group.name.trim().to_string();
            if name.is_empty() {
                continue;
            }
            let mut companies = Vec::new();
            let mut seen = HashSet::new();
            for company in group.companies {
                let company = company.trim().to_string();
                if !company.is_empty() && seen.insert(company.clone()) {
                    companies.push(company);
                }
            }
            if name == "未分类" && companies.is_empty() {
                continue;
            }
            let company_count = companies.len();
            response_groups.push(ClassificationGroupResponse {
                name,
                companies,
                company_count,
            });
        }
        let total_companies = response_groups
            .iter()
            .map(|group| group.company_count)
            .sum::<usize>();
        let total_groups = response_groups.len();
        serialize_response(ClassificationResponse {
            success: true,
            message,
            db_path: self.path.to_string_lossy().into_owned(),
            total_groups,
            total_companies,
            groups: response_groups,
        })
    }

    fn read_groups(&self) -> Result<Vec<GroupState>, String> {
        self.with_connection(|connection| {
            let mut group_statement = connection
                .prepare("SELECT id, name FROM groups ORDER BY sort_order, id")
                .map_err(sql_error)?;
            let group_rows = group_statement
                .query_map([], |row| {
                    Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
                })
                .map_err(sql_error)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(sql_error)?;
            drop(group_statement);
            let mut groups = Vec::with_capacity(group_rows.len());
            for (group_id, name) in group_rows {
                let mut company_statement = connection
                    .prepare(
                        "SELECT name FROM companies WHERE group_id = ?1 ORDER BY sort_order, id",
                    )
                    .map_err(sql_error)?;
                let companies = company_statement
                    .query_map(params![group_id], |row| row.get::<_, String>(0))
                    .map_err(sql_error)?
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(sql_error)?
                    .into_iter()
                    .map(|company| company.trim().to_string())
                    .filter(|company| !company.is_empty())
                    .collect();
                groups.push(GroupState { name, companies });
            }
            Ok(groups)
        })
    }

    fn write_groups(&self, groups: &[GroupState]) -> Result<(), String> {
        self.with_connection(|connection| {
            let transaction = connection.transaction().map_err(sql_error)?;
            transaction
                .execute("DELETE FROM companies", [])
                .map_err(sql_error)?;
            transaction.execute("DELETE FROM groups", []).map_err(sql_error)?;
            for (group_index, group) in groups.iter().enumerate() {
                let group_name = group.name.trim();
                if group_name.is_empty() {
                    continue;
                }
                let mut companies = Vec::new();
                let mut seen = HashSet::new();
                for company in &group.companies {
                    let company = company.trim();
                    if !company.is_empty() && seen.insert(company.to_string()) {
                        companies.push(company.to_string());
                    }
                }
                if group_name == "未分类" && companies.is_empty() {
                    continue;
                }
                transaction
                    .execute(
                        "INSERT INTO groups (name, sort_order) VALUES (?1, ?2)",
                        params![group_name, group_index as i64],
                    )
                    .map_err(sql_error)?;
                let group_id = transaction.last_insert_rowid();
                for (company_index, company) in companies.iter().enumerate() {
                    transaction
                        .execute(
                            "INSERT INTO companies (name, group_id, sort_order) VALUES (?1, ?2, ?3)",
                            params![company, group_id, company_index as i64],
                        )
                        .map_err(sql_error)?;
                }
            }
            transaction.commit().map_err(sql_error)
        })
    }

    fn with_connection<T>(
        &self,
        operation: impl FnOnce(&mut Connection) -> Result<T, String>,
    ) -> Result<T, String> {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut connection = open_connection(&self.path)?;
        operation(&mut connection)
    }

    fn initialize_schema(&self, had_database: bool) -> Result<(), String> {
        let _guard = self
            .access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut connection = open_connection(&self.path)?;
        let version = schema_version(&connection)?;
        if version > CLASSIFICATION_SCHEMA_VERSION {
            return Err(format!(
                "分类数据库版本 {version} 高于当前支持版本 {CLASSIFICATION_SCHEMA_VERSION}，拒绝降级打开"
            ));
        }

        let backup_path = if had_database && version < CLASSIFICATION_SCHEMA_VERSION {
            let path = migration_backup_path(&self.path, version, CLASSIFICATION_SCHEMA_VERSION);
            backup_connection_to(&connection, &self.path, &path)?;
            Some(path)
        } else {
            None
        };

        if version < CLASSIFICATION_SCHEMA_VERSION {
            if let Err(error) = migrate_schema(&mut connection, version) {
                return Err(match backup_path {
                    Some(path) => format!("{error}；迁移前备份已保留: {}", path.display()),
                    None => error,
                });
            }
        }
        validate_database(&connection)
    }
}

fn open_connection(path: &Path) -> Result<Connection, String> {
    let connection = Connection::open(path).map_err(sql_error)?;
    connection
        .busy_timeout(SQLITE_BUSY_TIMEOUT)
        .map_err(sql_error)?;
    connection
        .pragma_update(None, "foreign_keys", true)
        .map_err(sql_error)?;
    Ok(connection)
}

fn schema_version(connection: &Connection) -> Result<i64, String> {
    connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(sql_error)
}

fn migrate_schema(connection: &mut Connection, from_version: i64) -> Result<(), String> {
    if from_version != 0 {
        return Err(format!(
            "没有从分类数据库版本 {from_version} 到 {CLASSIFICATION_SCHEMA_VERSION} 的迁移路径"
        ));
    }
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(sql_error)?;
    transaction
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                sort_order INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                UNIQUE(name, group_id)
            );
            CREATE INDEX IF NOT EXISTS idx_companies_group ON companies(group_id);",
        )
        .map_err(sql_error)?;
    validate_schema_layout(&transaction)?;
    transaction
        .pragma_update(None, "user_version", CLASSIFICATION_SCHEMA_VERSION)
        .map_err(sql_error)?;
    transaction.commit().map_err(sql_error)
}

fn validate_schema_layout(connection: &Connection) -> Result<(), String> {
    connection
        .prepare("SELECT id, name, sort_order FROM groups LIMIT 0")
        .map_err(|error| format!("分类数据库 groups 表结构不兼容: {error}"))?;
    connection
        .prepare("SELECT id, name, group_id, sort_order FROM companies LIMIT 0")
        .map_err(|error| format!("分类数据库 companies 表结构不兼容: {error}"))?;
    Ok(())
}

fn validate_database(connection: &Connection) -> Result<(), String> {
    validate_schema_layout(connection)?;
    let result: String = connection
        .pragma_query_value(None, "quick_check", |row| row.get(0))
        .map_err(sql_error)?;
    if result != "ok" {
        return Err(format!("分类数据库完整性检查失败: {result}"));
    }
    Ok(())
}

fn migration_backup_path(path: &Path, from_version: i64, to_version: i64) -> PathBuf {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    let sequence = NEXT_BACKUP_ID.fetch_add(1, Ordering::Relaxed);
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("enterprise_classification.db");
    path.with_file_name(format!(
        "{file_name}.pre-v{from_version}-to-v{to_version}-{timestamp}-{}-{sequence}.bak",
        std::process::id()
    ))
}

fn backup_connection_to(
    source: &Connection,
    source_path: &Path,
    destination: &Path,
) -> Result<(), String> {
    if destination == source_path {
        return Err("分类数据库备份目标不能是源数据库".to_string());
    }
    if destination.exists() {
        return Err(format!(
            "分类数据库备份目标已存在，拒绝覆盖: {}",
            destination.display()
        ));
    }
    let parent = destination
        .parent()
        .ok_or_else(|| "分类数据库备份目标没有父目录".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("创建分类数据库备份目录失败: {error}"))?;
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("classification-backup.db");
    let temporary = parent.join(format!(
        ".{file_name}.tmp-{}-{}",
        std::process::id(),
        NEXT_BACKUP_ID.fetch_add(1, Ordering::Relaxed)
    ));

    let result = (|| -> Result<(), String> {
        let mut destination_connection = Connection::open(&temporary).map_err(sql_error)?;
        {
            let backup = Backup::new(source, &mut destination_connection).map_err(sql_error)?;
            backup
                .run_to_completion(128, Duration::from_millis(5), None)
                .map_err(sql_error)?;
        }
        validate_database(&destination_connection)?;
        drop(destination_connection);
        fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&temporary)
            .and_then(|file| file.sync_all())
            .map_err(|error| format!("同步分类数据库备份失败: {error}"))?;
        if destination.exists() {
            return Err(format!(
                "分类数据库备份目标已存在，拒绝覆盖: {}",
                destination.display()
            ));
        }
        fs::rename(&temporary, destination)
            .map_err(|error| format!("提交分类数据库备份失败: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn find_group_mut<'a>(
    groups: &'a mut [GroupState],
    name: &str,
) -> Result<&'a mut GroupState, String> {
    groups
        .iter_mut()
        .find(|group| group.name == name)
        .ok_or_else(|| format!("分组不存在: {name}"))
}

fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn sql_error(error: rusqlite::Error) -> String {
    format!("分类数据库操作失败: {error}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_directory(label: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "koi-classification-{label}-{}-{suffix}",
            std::process::id()
        ));
        fs::create_dir_all(&path).expect("create temp directory");
        path
    }

    fn temp_database() -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "koi-classification-test-{}-{suffix}.db",
            std::process::id()
        ))
    }

    #[test]
    fn classification_commands_keep_order_and_response_shape() {
        let path = temp_database();
        let store = ClassificationStore::new(path.clone()).expect("create database");
        let added = store
            .group_add(&json!({"group_name": "一组"}))
            .expect("add group");
        assert_eq!(added["groups"][0]["name"], "一组");
        store
            .company_add(&json!({"group_name": "一组", "companies_text": "甲\n乙\n甲"}))
            .expect("add companies");
        let state = store.get().expect("read state");
        assert_eq!(state["total_companies"], 2);
        assert_eq!(state["groups"][0]["companies"], json!(["甲", "乙"]));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn typed_aliases_preserve_legacy_truthiness_and_precedence() {
        let add: CompanyAddRequest = parse_request(&json!({
            "group_name": "目标",
            "company_names": ["   "],
            "companies": ["不得回退"]
        }))
        .unwrap();
        assert!(
            add.names.add_names().is_empty(),
            "a truthy first alias remains selected after its entries normalize away"
        );

        let add: CompanyAddRequest = parse_request(&json!({
            "group_name": "目标",
            "company_names": [],
            "companies": ["甲", null, true, 0]
        }))
        .unwrap();
        assert_eq!(add.names.add_names(), ["甲", "None", "True", "0"]);

        let delete: CompanyDeleteRequest = parse_request(&json!({
            "group_name": "目标",
            "company_names": false,
            "company_name": "乙\n 丙 ",
            "companies": ["不得采用"]
        }))
        .unwrap();
        assert_eq!(delete.names.delete_names(), ["乙", "丙"]);
    }

    #[test]
    fn typed_response_serializes_the_legacy_json_shape() {
        let response = ClassificationResponse {
            success: true,
            message: "已加载 1 个分组，2 家企业".to_string(),
            db_path: "classification.db".to_string(),
            total_groups: 1,
            total_companies: 2,
            groups: vec![ClassificationGroupResponse {
                name: "甲组".to_string(),
                companies: vec!["甲企业".to_string(), "乙企业".to_string()],
                company_count: 2,
            }],
        };
        assert_eq!(
            serialize_response(response).unwrap(),
            json!({
                "success": true,
                "message": "已加载 1 个分组，2 家企业",
                "db_path": "classification.db",
                "total_groups": 1,
                "total_companies": 2,
                "groups": [{
                    "name": "甲组",
                    "companies": ["甲企业", "乙企业"],
                    "company_count": 2
                }]
            })
        );
    }

    #[test]
    fn empty_uncategorized_group_is_not_returned() {
        let path = temp_database();
        let store = ClassificationStore::new(path.clone()).expect("create database");
        store
            .group_add(&json!({"group_name": "未分类"}))
            .expect("add group");
        let state = store.get().expect("read state");
        assert_eq!(state["total_groups"], 0);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn mutation_messages_and_error_semantics_match_python() {
        let path = temp_database();
        let store = ClassificationStore::new(path.clone()).expect("create database");

        assert_eq!(
            store.group_add(&json!({"group_name": "甲组"})).unwrap()["message"],
            "已添加分组: 甲组"
        );
        assert_eq!(
            store.group_add(&json!({"group_name": "乙组"})).unwrap()["message"],
            "已添加分组: 乙组"
        );
        assert_eq!(
            store
                .company_add(&json!({
                    "group_name": "甲组",
                    "company_names": ["企业一", "企业二", "企业一"]
                }))
                .unwrap()["message"],
            "已添加 2 家企业到 甲组"
        );
        assert_eq!(
            store
                .company_move(&json!({
                    "source_group": "甲组",
                    "target_group": "乙组",
                    "company_name": "企业一"
                }))
                .unwrap()["message"],
            "已移动 1 家企业到 乙组"
        );
        assert_eq!(
            store
                .company_delete(&json!({
                    "group_name": "乙组",
                    "company_names": ["企业一"]
                }))
                .unwrap()["message"],
            "已删除 1 家企业"
        );
        assert_eq!(
            store
                .company_rename(&json!({
                    "group_name": "甲组",
                    "old_name": "企业二",
                    "new_name": "企业二改名"
                }))
                .unwrap()["message"],
            "已修改企业名称: 企业二 -> 企业二改名"
        );
        assert_eq!(
            store
                .company_rename(&json!({
                    "group_name": "不存在",
                    "old_name": "相同",
                    "new_name": "相同"
                }))
                .unwrap_err(),
            "分组不存在: 不存在"
        );
        assert_eq!(
            store
                .company_move(&json!({
                    "source_group": "甲组",
                    "target_group": "乙组",
                    "company_name": "不存在的企业"
                }))
                .unwrap_err(),
            "未找到要移动的企业"
        );

        let _ = fs::remove_file(path);
    }

    #[test]
    fn new_database_is_created_at_current_schema_version() {
        let path = temp_database();
        let _store = ClassificationStore::new(path.clone()).expect("create database");
        let connection = Connection::open(&path).expect("open database");
        assert_eq!(
            schema_version(&connection).expect("read schema version"),
            CLASSIFICATION_SCHEMA_VERSION
        );
        validate_database(&connection).expect("validate database");
        drop(connection);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn legacy_database_is_backed_up_and_migrated_without_data_loss() {
        let directory = temp_directory("legacy-migration");
        let path = directory.join("enterprise_classification.db");
        let connection = Connection::open(&path).expect("create legacy database");
        connection
            .execute_batch(
                "CREATE TABLE groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    sort_order INTEGER NOT NULL
                );
                CREATE TABLE companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    group_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    UNIQUE(name, group_id)
                );
                CREATE INDEX idx_companies_group ON companies(group_id);
                INSERT INTO groups (name, sort_order) VALUES ('旧分组', 0);
                INSERT INTO companies (name, group_id, sort_order) VALUES ('旧企业', 1, 0);",
            )
            .expect("create legacy schema");
        assert_eq!(schema_version(&connection).unwrap(), 0);
        drop(connection);

        let store = ClassificationStore::new(path.clone()).expect("migrate legacy database");
        let state = store.get().expect("read migrated data");
        assert_eq!(state["groups"][0]["name"], "旧分组");
        assert_eq!(state["groups"][0]["companies"], json!(["旧企业"]));
        let connection = Connection::open(&path).expect("open migrated database");
        assert_eq!(schema_version(&connection).unwrap(), 1);
        drop(connection);

        let backups = fs::read_dir(&directory)
            .expect("read migration directory")
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|candidate| {
                candidate
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| {
                        name.starts_with("enterprise_classification.db.pre-v0-to-v1-")
                            && name.ends_with(".bak")
                    })
            })
            .collect::<Vec<_>>();
        assert_eq!(backups.len(), 1, "one pre-migration backup is retained");
        let backup = Connection::open(&backups[0]).expect("open migration backup");
        assert_eq!(schema_version(&backup).unwrap(), 0);
        assert_eq!(
            backup
                .query_row("SELECT name FROM companies", [], |row| row
                    .get::<_, String>(0))
                .unwrap(),
            "旧企业"
        );
        drop(backup);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn future_schema_version_is_rejected_without_modification() {
        let directory = temp_directory("future-version");
        let path = directory.join("enterprise_classification.db");
        let connection = Connection::open(&path).expect("create future database");
        connection
            .execute_batch(
                "CREATE TABLE groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    sort_order INTEGER NOT NULL
                );
                CREATE TABLE companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    group_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    UNIQUE(name, group_id)
                );
                PRAGMA user_version = 2;",
            )
            .expect("create future schema");
        drop(connection);

        let error = ClassificationStore::new(path.clone())
            .err()
            .expect("future version must fail closed");
        assert!(error.contains("高于当前支持版本"));
        let connection = Connection::open(&path).expect("reopen future database");
        assert_eq!(schema_version(&connection).unwrap(), 2);
        drop(connection);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn online_backup_is_consistent_and_never_overwrites() {
        let directory = temp_directory("online-backup");
        let path = directory.join("enterprise_classification.db");
        let backup_path = directory.join("snapshots/classification.db");
        let store = ClassificationStore::new(path).expect("create database");
        store
            .group_add(&json!({"group_name": "备份内"}))
            .expect("add first group");
        assert_eq!(
            store.backup_to(&backup_path).expect("create online backup"),
            backup_path
        );
        store
            .group_add(&json!({"group_name": "备份后"}))
            .expect("add second group");

        let backup_store =
            ClassificationStore::new(backup_path.clone()).expect("open online backup");
        let backup_state = backup_store.get().expect("read backup state");
        assert_eq!(backup_state["total_groups"], 1);
        assert_eq!(backup_state["groups"][0]["name"], "备份内");
        let error = store
            .backup_to(&backup_path)
            .expect_err("existing backup must not be overwritten");
        assert!(error.contains("拒绝覆盖"));
        let _ = fs::remove_dir_all(directory);
    }
}
