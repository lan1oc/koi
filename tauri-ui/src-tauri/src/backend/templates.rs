use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Map, Number, Value};
use std::collections::{hash_map::DefaultHasher, BTreeMap};
use std::fs::{self, File, OpenOptions};
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Default, Serialize)]
#[serde(untagged)]
enum CompatJson {
    #[default]
    Null,
    Bool(bool),
    Number(Number),
    String(String),
    Array(Vec<CompatJson>),
    Object(BTreeMap<String, CompatJson>),
}

impl From<Value> for CompatJson {
    fn from(value: Value) -> Self {
        match value {
            Value::Null => Self::Null,
            Value::Bool(value) => Self::Bool(value),
            Value::Number(value) => Self::Number(value),
            Value::String(value) => Self::String(value),
            Value::Array(values) => Self::Array(values.into_iter().map(Self::from).collect()),
            Value::Object(values) => Self::Object(
                values
                    .into_iter()
                    .map(|(key, value)| (key, Self::from(value)))
                    .collect(),
            ),
        }
    }
}

impl CompatJson {
    fn is_truthy(&self) -> bool {
        match self {
            Self::Null | Self::Bool(false) => false,
            Self::Bool(true) => true,
            Self::Number(number) => number.as_f64().is_some_and(|value| value != 0.0),
            Self::String(value) => !value.is_empty(),
            Self::Array(value) => !value.is_empty(),
            Self::Object(value) => !value.is_empty(),
        }
    }

    fn is_null(&self) -> bool {
        matches!(self, Self::Null)
    }

    fn is_empty_string(&self) -> bool {
        matches!(self, Self::String(value) if value.is_empty())
    }

    fn text(&self) -> String {
        match self {
            Self::Null => "None".to_string(),
            Self::Bool(true) => "True".to_string(),
            Self::Bool(false) => "False".to_string(),
            Self::Number(value) => value.to_string(),
            Self::String(value) => value.clone(),
            Self::Array(_) | Self::Object(_) => serde_json::to_string(self).unwrap_or_default(),
        }
    }

    fn to_json(&self) -> Result<Value, String> {
        serde_json::to_value(self).map_err(|error| format!("兼容字段序列化失败: {error}"))
    }

    fn object(&self) -> Option<&BTreeMap<String, CompatJson>> {
        match self {
            Self::Object(value) => Some(value),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
struct CompatField {
    present: bool,
    value: CompatJson,
}

impl Default for CompatField {
    fn default() -> Self {
        Self {
            present: false,
            value: CompatJson::Null,
        }
    }
}

impl<'de> Deserialize<'de> for CompatField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Ok(Self {
            present: true,
            value: CompatJson::from(Value::deserialize(deserializer)?),
        })
    }
}

impl CompatField {
    fn is_truthy(&self) -> bool {
        self.present && self.value.is_truthy()
    }

    fn is_null(&self) -> bool {
        self.value.is_null()
    }

    fn is_empty_string(&self) -> bool {
        self.value.is_empty_string()
    }

    fn text(&self) -> String {
        self.value.text()
    }

    fn trimmed_truthy_text(&self) -> Option<String> {
        self.is_truthy()
            .then(|| self.text().trim().to_string())
            .filter(|value| !value.is_empty())
    }

    fn to_json(&self) -> Result<Value, String> {
        self.value.to_json()
    }
}

#[derive(Clone, Debug, Default)]
struct MetadataField(Option<Map<String, Value>>);

impl<'de> Deserialize<'de> for MetadataField {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self(value.as_object().cloned()))
    }
}

impl MetadataField {
    fn object(&self) -> Option<&Map<String, Value>> {
        self.0.as_ref()
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateIdentifierFields {
    #[serde(default)]
    template_id: CompatField,
    #[serde(default, rename = "templateId")]
    template_id_alias: CompatField,
    #[serde(default)]
    id: CompatField,
}

impl TemplateIdentifierFields {
    fn candidates<'a>(&'a self, name: &'a CompatField) -> [&'a CompatField; 4] {
        [&self.template_id, &self.template_id_alias, &self.id, name]
    }

    fn has_id(&self) -> bool {
        self.template_id.is_truthy() || self.template_id_alias.is_truthy() || self.id.is_truthy()
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateWriteFields {
    #[serde(default)]
    name: CompatField,
    #[serde(default)]
    description: CompatField,
    #[serde(default)]
    field_mapping: CompatField,
    #[serde(default, rename = "fieldMapping")]
    field_mapping_alias: CompatField,
    #[serde(default)]
    mapping: CompatField,
    #[serde(default)]
    source_format: CompatField,
    #[serde(default, rename = "sourceFormat")]
    source_format_alias: CompatField,
    #[serde(default)]
    template_format: CompatField,
    #[serde(default, rename = "templateFormat")]
    template_format_alias: CompatField,
    #[serde(default)]
    metadata: MetadataField,
    #[serde(default)]
    target_template: CompatField,
    #[serde(default, rename = "targetTemplate")]
    target_template_alias: CompatField,
    #[serde(default)]
    delimiter: CompatField,
}

impl TemplateWriteFields {
    fn source_format(&self) -> &CompatField {
        if self.source_format.present {
            &self.source_format
        } else {
            &self.source_format_alias
        }
    }

    fn template_format(&self) -> &CompatField {
        if self.template_format.present {
            &self.template_format
        } else {
            &self.template_format_alias
        }
    }

    fn target_template(&self) -> &CompatField {
        if self.target_template.present {
            &self.target_template
        } else {
            &self.target_template_alias
        }
    }

    fn mapping_requested(&self) -> bool {
        [
            &self.field_mapping,
            &self.field_mapping_alias,
            &self.mapping,
        ]
        .into_iter()
        .any(|field| field.present && !field.is_null())
    }

    fn mapping(&self, allow_empty: bool) -> Result<BTreeMap<String, String>, String> {
        let raw = [
            &self.field_mapping,
            &self.field_mapping_alias,
            &self.mapping,
        ]
        .into_iter()
        .find(|field| field.is_truthy());
        let mut mapping = BTreeMap::new();
        if let Some(raw) = raw {
            let Some(raw_map) = raw.value.object() else {
                return Err("字段映射必须是对象".to_string());
            };
            for (template_field, source_field) in raw_map {
                let template_field = template_field.trim();
                let source_field = source_field.text().trim().to_string();
                if !template_field.is_empty() && !source_field.is_empty() {
                    mapping.insert(template_field.to_string(), source_field);
                }
            }
        }
        if !allow_empty && mapping.is_empty() {
            Err("请先设置字段映射".to_string())
        } else {
            Ok(mapping)
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateListRequest {
    #[serde(default)]
    filter_format: CompatField,
    #[serde(default, rename = "filterFormat")]
    filter_format_alias: CompatField,
}

impl TemplateListRequest {
    fn filter_format(&self) -> Option<String> {
        self.filter_format
            .trimmed_truthy_text()
            .or_else(|| self.filter_format_alias.trimmed_truthy_text())
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateGetRequest {
    #[serde(flatten)]
    identifier: TemplateIdentifierFields,
    #[serde(default)]
    name: CompatField,
    #[serde(default)]
    mark_used: CompatField,
    #[serde(default, rename = "markUsed")]
    mark_used_alias: CompatField,
}

impl TemplateGetRequest {
    fn mark_used(&self) -> bool {
        if self.mark_used.present {
            self.mark_used.is_truthy()
        } else {
            self.mark_used_alias.is_truthy()
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateCreateRequest {
    #[serde(flatten)]
    fields: TemplateWriteFields,
}

#[derive(Debug, Default, Deserialize)]
struct TemplateUpdateRequest {
    #[serde(flatten)]
    identifier: TemplateIdentifierFields,
    #[serde(flatten)]
    fields: TemplateWriteFields,
}

#[derive(Debug, Default, Deserialize)]
struct TemplateDeleteRequest {
    #[serde(flatten)]
    identifier: TemplateIdentifierFields,
    #[serde(default)]
    name: CompatField,
    #[serde(default)]
    force: CompatField,
}

#[derive(Debug, Default, Deserialize)]
struct TemplateImportRequest {
    #[serde(default)]
    import_path: CompatField,
    #[serde(default, rename = "importPath")]
    import_path_alias: CompatField,
    #[serde(default)]
    overwrite: CompatField,
}

impl TemplateImportRequest {
    fn import_path(&self) -> Result<String, String> {
        required_text(
            if self.import_path.present {
                &self.import_path
            } else {
                &self.import_path_alias
            },
            "请选择要导入的模板文件",
        )
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateExportRequest {
    #[serde(flatten)]
    identifier: TemplateIdentifierFields,
    #[serde(default)]
    name: CompatField,
    #[serde(default)]
    export_path: CompatField,
    #[serde(default, rename = "exportPath")]
    export_path_alias: CompatField,
}

impl TemplateExportRequest {
    fn export_path(&self) -> Result<String, String> {
        required_text(
            if self.export_path.present {
                &self.export_path
            } else {
                &self.export_path_alias
            },
            "请选择导出保存位置",
        )
    }
}

#[derive(Debug, Default, Deserialize)]
struct TemplateSaveRequest {
    #[serde(flatten)]
    identifier: TemplateIdentifierFields,
    #[serde(flatten)]
    fields: TemplateWriteFields,
}

#[derive(Debug, Serialize)]
struct TemplateListResponse {
    templates: Vec<Value>,
    count: usize,
}

#[derive(Debug, Serialize)]
struct TemplateGetResponse {
    template: Value,
}

#[derive(Debug, Serialize)]
struct TemplateCreateResponse {
    success: bool,
    message: String,
    template_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    template: Option<Value>,
}

#[derive(Debug, Serialize)]
struct TemplateUpdateResponse {
    success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    template: Option<Value>,
}

#[derive(Debug, Serialize)]
struct TemplateDeleteResponse {
    success: bool,
    message: String,
}

#[derive(Debug, Serialize)]
struct TemplateImportResponse {
    success: bool,
    message: String,
    template_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct TemplateExportResponse {
    success: bool,
    message: String,
    export_file: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(untagged)]
enum TemplateSaveResponse {
    Create(TemplateCreateResponse),
    Update(TemplateUpdateResponse),
}

/// Persistent data-processing template store.
///
/// The Python implementation creates a fresh `TemplateManager` for every
/// request.  Keep the same observable behaviour here: operations are
/// serialized, and the JSON file is read again while holding the lock for
/// every operation.  This also means an external edit (or another process)
/// is visible to the next request rather than being hidden by a process-local
/// cache.
pub struct TemplateStore {
    path: PathBuf,
    access: Mutex<()>,
}

impl TemplateStore {
    pub fn new(user_data_dir: PathBuf) -> Result<Self, String> {
        let path = user_data_dir.join("templates").join("templates.json");
        Ok(Self {
            path,
            access: Mutex::new(()),
        })
    }

    #[allow(dead_code)]
    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn list(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateListRequest = parse_request(payload)?;
        let _guard = self.lock();
        let templates = self.load_unlocked();
        let filter_format = request.filter_format();

        let mut entries: Vec<(String, Value)> = templates
            .iter()
            .filter(|(_, template)| {
                filter_format
                    .as_deref()
                    .is_none_or(|format| template_field_string(template, "source_format") == format)
            })
            .map(|(key, template)| (key.clone(), normalize_template_entry(key, template)))
            .collect();
        entries.sort_by(|(_, left), (_, right)| {
            let left_created = left
                .get("created_at")
                .map(python_string)
                .unwrap_or_default();
            let right_created = right
                .get("created_at")
                .map(python_string)
                .unwrap_or_default();
            right_created.cmp(&left_created)
        });
        let values: Vec<Value> = entries.into_iter().map(|(_, value)| value).collect();
        let count = values.len();
        serialize_response(TemplateListResponse {
            templates: values,
            count,
        })
    }

    pub fn get(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateGetRequest = parse_request(payload)?;
        let _guard = self.lock();
        let mut templates = self.load_unlocked();
        let key = template_key(&templates, request.identifier.candidates(&request.name))?;

        if request.mark_used() {
            if let Some(template) = templates.get_mut(&key).and_then(Value::as_object_mut) {
                increment_usage_count(template)?;
                template.insert("last_used".to_string(), Value::String(iso_timestamp()));
                // Python ignores the boolean returned by _save_templates in
                // use_template, so a transient write failure does not turn a
                // successful get into a protocol error.
                let _ = self.save_unlocked(&templates);
            }
        }

        let template = templates
            .get(&key)
            .ok_or_else(|| format!("模板不存在: {key}"))?;
        serialize_response(TemplateGetResponse {
            template: normalize_template_entry(&key, template),
        })
    }

    pub fn create(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateCreateRequest = parse_request(payload)?;
        serialize_response(self.create_typed(&request.fields)?)
    }

    fn create_typed(&self, fields: &TemplateWriteFields) -> Result<TemplateCreateResponse, String> {
        let _guard = self.lock();
        let name = required_text(&fields.name, "请输入模板名称")?;
        let description = if fields.description.is_truthy() {
            fields.description.text()
        } else {
            String::new()
        };
        let field_mapping = fields.mapping(true)?;
        let source_format = if fields.source_format().is_truthy() {
            fields.source_format().text()
        } else {
            "excel".to_string()
        };
        let template_format = if fields.template_format().is_truthy() {
            fields.template_format().text()
        } else {
            "excel".to_string()
        };
        let metadata = fields
            .metadata
            .object()
            .map(|value| Value::Object(value.clone()))
            .unwrap_or_else(|| json!({}));

        let mut templates = self.load_unlocked();
        if templates
            .values()
            .any(|template| template_name(template) == name)
        {
            return Ok(TemplateCreateResponse {
                success: false,
                message: format!("模板名称 '{name}' 已存在"),
                template_id: None,
                template: None,
            });
        }

        let template_id = generate_template_id(&name, &templates);
        let timestamp = iso_timestamp();
        let template = json!({
            "id": template_id,
            "name": name,
            "description": description,
            "field_mapping": field_mapping,
            "source_format": source_format,
            "template_format": template_format,
            "metadata": metadata,
            "created_at": timestamp,
            "updated_at": iso_timestamp(),
            "version": "1.0.0",
            "usage_count": 0,
        });
        templates.insert(template_id.clone(), template);

        if self.save_unlocked(&templates).is_err() {
            templates.remove(&template_id);
            return Ok(TemplateCreateResponse {
                success: false,
                message: "保存模板失败".to_string(),
                template_id: None,
                template: None,
            });
        }

        // The filling screen stores these two compatibility fields outside
        // TemplateManager's create_template signature.  Preserve its exact
        // "present and not None/empty string" rule.
        if let Some(template) = templates
            .get_mut(&template_id)
            .and_then(Value::as_object_mut)
        {
            for (key, value) in [
                ("target_template", fields.target_template()),
                ("delimiter", &fields.delimiter),
            ] {
                if value.present && !value.is_null() && !value.is_empty_string() {
                    template.insert(key.to_string(), Value::String(value.text()));
                }
            }
        }
        let _ = self.save_unlocked(&templates);

        let template = templates
            .get(&template_id)
            .ok_or_else(|| "创建模板后无法读取模板".to_string())?;
        Ok(TemplateCreateResponse {
            success: true,
            message: format!("成功创建模板 '{name}'"),
            template_id: Some(template_id.clone()),
            template: Some(normalize_template_entry(&template_id, template)),
        })
    }

    pub fn update(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateUpdateRequest = parse_request(payload)?;
        serialize_response(self.update_typed(&request.identifier, &request.fields)?)
    }

    fn update_typed(
        &self,
        identifier: &TemplateIdentifierFields,
        fields: &TemplateWriteFields,
    ) -> Result<TemplateUpdateResponse, String> {
        let _guard = self.lock();
        let mut templates = self.load_unlocked();
        let key = template_key(&templates, identifier.candidates(&fields.name))?;

        let new_name = if fields.name.is_truthy() {
            fields.name.text()
        } else {
            String::new()
        }
        .trim()
        .to_string();
        if !new_name.is_empty()
            && templates.iter().any(|(other_key, template)| {
                other_key != &key && template_name(template) == new_name
            })
        {
            return Ok(TemplateUpdateResponse {
                success: false,
                message: format!("模板名称 '{new_name}' 已存在"),
                template: None,
            });
        }

        let mapping_update = if fields.mapping_requested() {
            Some(fields.mapping(true)?)
        } else {
            None
        };

        let template = templates
            .get_mut(&key)
            .and_then(Value::as_object_mut)
            .ok_or_else(|| format!("模板不存在: {key}"))?;
        for (name, field) in [
            ("name", &fields.name),
            ("description", &fields.description),
            ("source_format", fields.source_format()),
            ("template_format", fields.template_format()),
        ] {
            if field.present && !field.is_null() {
                template.insert(name.to_string(), field.to_json()?);
            }
        }
        if let Some(mapping) = mapping_update {
            template.insert(
                "field_mapping".to_string(),
                serde_json::to_value(mapping)
                    .map_err(|error| format!("字段映射序列化失败: {error}"))?,
            );
        }
        if let Some(metadata) = fields.metadata.object() {
            template.insert("metadata".to_string(), Value::Object(metadata.clone()));
        }
        template.insert("updated_at".to_string(), Value::String(iso_timestamp()));
        let resulting_name = template
            .get("name")
            .map(python_string)
            .unwrap_or_else(|| key.clone());

        if self.save_unlocked(&templates).is_err() {
            return Ok(TemplateUpdateResponse {
                success: false,
                message: "保存模板失败".to_string(),
                template: None,
            });
        }

        if let Some(template) = templates.get_mut(&key).and_then(Value::as_object_mut) {
            for (extra, value) in [
                ("target_template", fields.target_template()),
                ("delimiter", &fields.delimiter),
            ] {
                if value.present && !value.is_null() {
                    let text = if value.is_truthy() {
                        value.text()
                    } else {
                        String::new()
                    };
                    template.insert(extra.to_string(), Value::String(text));
                }
            }
        }
        let _ = self.save_unlocked(&templates);

        let template = templates
            .get(&key)
            .ok_or_else(|| format!("模板不存在: {key}"))?;
        Ok(TemplateUpdateResponse {
            success: true,
            message: format!("成功更新模板 '{resulting_name}'"),
            template: Some(normalize_template_entry(&key, template)),
        })
    }

    pub fn delete(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateDeleteRequest = parse_request(payload)?;
        let _guard = self.lock();
        let mut templates = self.load_unlocked();
        let key = template_key(&templates, request.identifier.candidates(&request.name))?;
        let template = templates
            .get(&key)
            .ok_or_else(|| format!("模板不存在: {key}"))?;
        let predefined = template
            .get("metadata")
            .and_then(Value::as_object)
            .and_then(|metadata| metadata.get("is_predefined"))
            .is_some_and(|value| json_truthy(Some(value)));
        if predefined && !request.force.is_truthy() {
            return serialize_response(TemplateDeleteResponse {
                success: false,
                message: "预定义模板不能删除".to_string(),
            });
        }

        let name = template_name(template);
        templates.remove(&key);
        if self.save_unlocked(&templates).is_err() {
            return serialize_response(TemplateDeleteResponse {
                success: false,
                message: "保存模板失败".to_string(),
            });
        }
        serialize_response(TemplateDeleteResponse {
            success: true,
            message: format!("成功删除模板 '{name}'"),
        })
    }

    pub fn import_template(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateImportRequest = parse_request(payload)?;
        let _guard = self.lock();
        let import_path = request.import_path()?;
        let path = PathBuf::from(&import_path);
        if !path.exists() {
            return serialize_response(TemplateImportResponse {
                success: false,
                message: format!("文件不存在: {import_path}"),
                template_id: None,
            });
        }

        let raw = match fs::read(&path) {
            Ok(value) => value,
            Err(error) => {
                return serialize_response(TemplateImportResponse {
                    success: false,
                    message: format!("导入模板失败: {error}"),
                    template_id: None,
                });
            }
        };
        let mut template = match serde_json::from_slice::<Value>(&raw) {
            Ok(Value::Object(value)) => value,
            Ok(Value::Array(_) | Value::String(_) | Value::Number(_) | Value::Bool(_)) => {
                return serialize_response(TemplateImportResponse {
                    success: false,
                    message: "模板文件缺少必需字段: name".to_string(),
                    template_id: None,
                });
            }
            Ok(Value::Null) => {
                return serialize_response(TemplateImportResponse {
                    success: false,
                    message: "导入模板失败: argument of type 'NoneType' is not iterable"
                        .to_string(),
                    template_id: None,
                });
            }
            Err(error) => {
                return serialize_response(TemplateImportResponse {
                    success: false,
                    message: format!("导入模板失败: {error}"),
                    template_id: None,
                });
            }
        };

        for required in ["name", "description", "field_mapping"] {
            if !template.contains_key(required) {
                return serialize_response(TemplateImportResponse {
                    success: false,
                    message: format!("模板文件缺少必需字段: {required}"),
                    template_id: None,
                });
            }
        }

        let name = template.get("name").map(python_string).unwrap_or_default();
        let mut templates = self.load_unlocked();
        let overwrite = request.overwrite.is_truthy();
        if templates.values().any(|value| template_name(value) == name) && !overwrite {
            return serialize_response(TemplateImportResponse {
                success: false,
                message: format!("模板 '{name}' 已存在，使用overwrite=True覆盖"),
                template_id: None,
            });
        }

        let template_id = generate_template_id(&name, &templates);
        template.insert("id".to_string(), Value::String(template_id.clone()));
        template.insert("imported_at".to_string(), Value::String(iso_timestamp()));
        if !template.contains_key("created_at") {
            template.insert("created_at".to_string(), Value::String(iso_timestamp()));
        }
        template.insert("updated_at".to_string(), Value::String(iso_timestamp()));
        template.insert("usage_count".to_string(), json!(0));
        templates.insert(template_id.clone(), Value::Object(template));

        if self.save_unlocked(&templates).is_err() {
            templates.remove(&template_id);
            return serialize_response(TemplateImportResponse {
                success: false,
                message: "保存模板失败".to_string(),
                template_id: None,
            });
        }

        serialize_response(TemplateImportResponse {
            success: true,
            message: format!("成功导入模板 '{name}'"),
            template_id: Some(template_id),
        })
    }

    pub fn export_template(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateExportRequest = parse_request(payload)?;
        let _guard = self.lock();
        let templates = self.load_unlocked();
        let key = template_key(&templates, request.identifier.candidates(&request.name))?;
        let export_text = request.export_path()?;
        let mut export_path = PathBuf::from(&export_text);
        export_path = ensure_python_json_extension(export_path);

        let template = templates
            .get(&key)
            .ok_or_else(|| format!("模板不存在: {key}"))?;
        let name = template_name(template);
        let bytes = serde_json::to_vec_pretty(template)
            .map_err(|error| format!("导出模板失败: {error}"))?;
        if let Err(error) = fs::write(&export_path, bytes) {
            return serialize_response(TemplateExportResponse {
                success: false,
                message: format!("导出模板失败: {error}"),
                export_file: None,
            });
        }
        serialize_response(TemplateExportResponse {
            success: true,
            message: format!("成功导出模板 '{name}'"),
            export_file: Some(export_path.to_string_lossy().into_owned()),
        })
    }

    pub fn save(&self, payload: &Value) -> Result<Value, String> {
        let request: TemplateSaveRequest = parse_request(payload)?;
        let response = if request.identifier.has_id() {
            TemplateSaveResponse::Update(self.update_typed(&request.identifier, &request.fields)?)
        } else {
            TemplateSaveResponse::Create(self.create_typed(&request.fields)?)
        };
        serialize_response(response)
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, ()> {
        self.access
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn load_unlocked(&self) -> Map<String, Value> {
        if !self.path.exists() {
            let defaults = default_templates();
            let _ = self.save_unlocked(&defaults);
            return defaults;
        }
        let raw = match fs::read(&self.path) {
            Ok(value) => value,
            Err(_) => return Map::new(),
        };
        match serde_json::from_slice::<Value>(&raw) {
            Ok(Value::Object(value)) => value,
            Ok(_) | Err(_) => Map::new(),
        }
    }

    fn save_unlocked(&self, templates: &Map<String, Value>) -> Result<(), String> {
        let parent = self
            .path
            .parent()
            .ok_or_else(|| "模板文件路径缺少父目录".to_string())?;
        fs::create_dir_all(parent).map_err(|error| format!("创建模板目录失败: {error}"))?;
        let serialized = serde_json::to_vec_pretty(templates)
            .map_err(|error| format!("模板序列化失败: {error}"))?;
        let (temporary, mut file) = create_temp_file(&self.path)?;
        let result = (|| -> Result<(), String> {
            file.write_all(&serialized)
                .map_err(|error| format!("写入临时模板失败: {error}"))?;
            file.flush()
                .map_err(|error| format!("刷新临时模板失败: {error}"))?;
            file.sync_all()
                .map_err(|error| format!("同步临时模板失败: {error}"))?;
            drop(file);
            atomic_replace(&temporary, &self.path)?;
            sync_parent_directory(parent)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result
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
        .map_err(|error| format!("模板命令请求字段格式错误: {error}"))
}

fn serialize_response<T>(response: T) -> Result<Value, String>
where
    T: Serialize,
{
    serde_json::to_value(response).map_err(|error| format!("响应序列化失败: {error}"))
}

fn default_templates() -> Map<String, Value> {
    let timestamp = iso_timestamp();
    let template = json!({
        "id": "exposure_template_001",
        "name": "暴露面收集模板",
        "description": "用于暴露面收集数据的标准模板",
        "field_mapping": {
            "IP地址": "ip",
            "端口": "port",
            "协议": "protocol",
            "服务": "service",
            "标题": "title",
            "状态码": "status",
            "国家": "country",
            "城市": "city",
            "组织": "org"
        },
        "source_format": "excel",
        "template_format": "excel",
        "metadata": {
            "category": "security",
            "tags": ["暴露面", "网络安全", "IP扫描"]
        },
        "created_at": timestamp,
        "updated_at": iso_timestamp(),
        "version": "1.0.0",
        "usage_count": 0
    });
    let mut values = Map::new();
    values.insert("exposure_template_001".to_string(), template);
    values
}

fn required_text(field: &CompatField, message: &str) -> Result<String, String> {
    let value = if field.is_truthy() {
        field.text()
    } else {
        String::new()
    }
    .trim()
    .to_string();
    if value.is_empty() {
        Err(message.to_string())
    } else {
        Ok(value)
    }
}

fn template_key(
    templates: &Map<String, Value>,
    candidates: [&CompatField; 4],
) -> Result<String, String> {
    let identifier = candidates
        .into_iter()
        .find(|field| field.is_truthy())
        .map(CompatField::text)
        .unwrap_or_default()
        .trim()
        .to_string();
    if identifier.is_empty() {
        return Err("请先选择模板".to_string());
    }
    if templates.contains_key(&identifier) {
        return Ok(identifier);
    }
    for (key, template) in templates {
        if template
            .get("id")
            .filter(|value| json_truthy(Some(value)))
            .map(python_string)
            .is_some_and(|value| value == identifier)
            || template
                .get("name")
                .filter(|value| json_truthy(Some(value)))
                .map(python_string)
                .is_some_and(|value| value == identifier)
        {
            return Ok(key.clone());
        }
    }
    Err(format!("模板不存在: {identifier}"))
}

fn normalize_template_entry(key: &str, template: &Value) -> Value {
    let Some(template_object) = template.as_object() else {
        return template.clone();
    };
    let mut item = template_object.clone();
    if !item.contains_key("id") {
        let id = template
            .get("id")
            .filter(|value| json_truthy(Some(value)))
            .map(python_string)
            .unwrap_or_else(|| key.to_string());
        item.insert("id".to_string(), Value::String(id));
    }
    if !item.contains_key("name") {
        let name = template
            .get("name")
            .filter(|value| json_truthy(Some(value)))
            .map(python_string)
            .unwrap_or_else(|| key.to_string());
        item.insert("name".to_string(), Value::String(name));
    }
    if !item.contains_key("field_mapping") {
        let mapping = template
            .get("field_mapping")
            .filter(|value| json_truthy(Some(value)))
            .cloned()
            .or_else(|| {
                template
                    .get("mapping")
                    .filter(|value| json_truthy(Some(value)))
                    .cloned()
            })
            .unwrap_or_else(|| json!({}));
        item.insert("field_mapping".to_string(), mapping);
    }
    Value::Object(item)
}

fn template_name(template: &Value) -> String {
    template
        .get("name")
        .filter(|value| json_truthy(Some(value)))
        .map(python_string)
        .unwrap_or_default()
}

fn template_field_string(template: &Value, field: &str) -> String {
    template
        .get(field)
        .filter(|value| json_truthy(Some(value)))
        .map(python_string)
        .unwrap_or_default()
}

fn increment_usage_count(template: &mut Map<String, Value>) -> Result<(), String> {
    let current = template
        .get("usage_count")
        .ok_or_else(|| "模板缺少 usage_count".to_string())?;
    let next = match current {
        // Python bools are ints for arithmetic: False + 1 == 1 and
        // True + 1 == 2.  Keep that legacy behaviour for malformed files.
        Value::Bool(value) => json!(if *value { 2 } else { 1 }),
        Value::Number(number) if number.as_i64().is_some() => {
            json!(number.as_i64().unwrap_or_default() + 1)
        }
        Value::Number(number) if number.as_u64().is_some() => {
            json!(number.as_u64().unwrap_or_default().saturating_add(1))
        }
        Value::Number(number) if number.as_f64().is_some() => {
            json!(number.as_f64().unwrap_or_default() + 1.0)
        }
        _ => return Err("模板 usage_count 必须是数字".to_string()),
    };
    template.insert("usage_count".to_string(), next);
    Ok(())
}

fn ensure_python_json_extension(mut path: PathBuf) -> PathBuf {
    if python_path_has_suffix(&path) {
        return path;
    }

    // pathlib.Path.with_suffix('.json') appends for names with no suffix,
    // including dotfiles and names ending in a dot.  Trim a trailing separator
    // first so a directory-like input follows pathlib's normalisation.
    let mut text = path.to_string_lossy().into_owned();
    while (text.ends_with('\\') || text.ends_with('/')) && text.len() > 1 {
        text.pop();
    }
    text.push_str(".json");
    path = PathBuf::from(text);
    path
}

fn python_path_has_suffix(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return false;
    };
    let Some(dot) = name.rfind('.') else {
        return false;
    };
    dot != 0 && dot + 1 < name.len()
}

fn create_temp_file(destination: &Path) -> Result<(PathBuf, File), String> {
    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);
    let parent = destination
        .parent()
        .ok_or_else(|| "模板文件路径缺少父目录".to_string())?;
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("templates.json");

    for _ in 0..32 {
        let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let candidate = parent.join(format!(".{file_name}.tmp-{}-{unique}", std::process::id()));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => return Ok((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("创建临时模板失败: {error}")),
        }
    }
    Err("创建临时模板失败: 临时文件名冲突".to_string())
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        MoveFileExW(
            PCWSTR(source_wide.as_ptr()),
            PCWSTR(destination_wide.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("原子替换模板失败: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("原子替换模板失败: {error}"))
}

#[cfg(unix)]
fn sync_parent_directory(parent: &Path) -> Result<(), String> {
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| format!("同步模板目录失败: {error}"))
}

#[cfg(not(unix))]
fn sync_parent_directory(_parent: &Path) -> Result<(), String> {
    Ok(())
}

fn generate_template_id(name: &str, templates: &Map<String, Value>) -> String {
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    let nonce = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    for attempt in 0_u64.. {
        let mut hasher = DefaultHasher::new();
        name.hash(&mut hasher);
        now.hash(&mut hasher);
        nonce.hash(&mut hasher);
        attempt.hash(&mut hasher);
        std::process::id().hash(&mut hasher);
        let digest = format!("{:016x}", hasher.finish());
        let candidate = digest[..12].to_string();
        if !templates.contains_key(&candidate) {
            return candidate;
        }
    }
    unreachable!("an available template id must exist")
}

fn json_truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) | Some(Value::Bool(false)) => false,
        Some(Value::Bool(true)) => true,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|value| value != 0.0),
        Some(Value::String(value)) => !value.is_empty(),
        Some(Value::Array(value)) => !value.is_empty(),
        Some(Value::Object(value)) => !value.is_empty(),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(value) => {
            if *value {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

#[cfg(windows)]
fn iso_timestamp() -> String {
    // Python's datetime.now().isoformat() contains a local date/time and
    // microseconds.  The exact instant is intentionally not part of the
    // command contract, but retaining the shape keeps persisted templates
    // compatible with the legacy manager and its lexical sorting.
    #[repr(C)]
    struct WindowsSystemTime {
        year: u16,
        month: u16,
        day_of_week: u16,
        day: u16,
        hour: u16,
        minute: u16,
        second: u16,
        milliseconds: u16,
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetLocalTime(system_time: *mut WindowsSystemTime);
    }

    let mut value = std::mem::MaybeUninit::<WindowsSystemTime>::uninit();
    let value = unsafe {
        GetLocalTime(value.as_mut_ptr());
        value.assume_init()
    };
    let fraction = u32::from(value.milliseconds) * 1_000;
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{fraction:06}",
        value.year, value.month, value.day, value.hour, value.minute, value.second
    )
}

#[cfg(not(windows))]
fn iso_timestamp() -> String {
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_micros())
        .unwrap_or_default();
    let seconds = (micros / 1_000_000) as i64;
    let fraction = (micros % 1_000_000) as u32;
    let days = seconds.div_euclid(86_400);
    let day_seconds = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = day_seconds / 3_600;
    let minute = (day_seconds % 3_600) / 60;
    let second = day_seconds % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{fraction:06}")
}

#[cfg(not(windows))]
fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let shifted = days + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_parameter = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_parameter + 2) / 5 + 1;
    let month = month_parameter + if month_parameter < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    (year as i32, month as u32, day as u32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn isolated_store() -> (TemplateStore, PathBuf) {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("koi-template-store-{}-{nonce}", std::process::id()));
        let store = TemplateStore::new(root.clone()).expect("create isolated template store");
        (store, root)
    }

    #[test]
    fn create_list_get_update_delete_and_aliases_keep_shapes() {
        let (store, root) = isolated_store();
        let created = store
            .create(&json!({
                "name": "自定义模板",
                "description": "描述",
                "field_mapping": {"目标": "来源"},
                "target_template": "target.xlsx",
                "delimiter": "|"
            }))
            .expect("create");
        assert_eq!(created["success"], true);
        let id = created["template_id"].as_str().expect("id").to_string();
        assert_eq!(created["template"]["target_template"], "target.xlsx");

        let listed = store.list(&json!({})).expect("list");
        assert!(listed["count"].as_u64().unwrap_or_default() >= 2);
        let got = store
            .get(&json!({"id": id, "mark_used": true}))
            .expect("get");
        assert_eq!(got["template"]["usage_count"], 1);

        let updated = store
            .save(&json!({
                "template_id": id,
                "name": "改名",
                "delimiter": "",
                "field_mapping": {}
            }))
            .expect("update alias");
        assert_eq!(updated["success"], true);
        assert_eq!(updated["template"]["name"], "改名");
        assert_eq!(updated["template"]["delimiter"], "");

        let deleted = store.delete(&json!({"name": "改名"})).expect("delete");
        assert_eq!(deleted["success"], true);
        let missing = store.get(&json!({"name": "改名"}));
        assert_eq!(missing.unwrap_err(), "模板不存在: 改名");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn predefined_delete_requires_force_and_import_overwrite_adds_duplicate() {
        let (store, root) = isolated_store();
        let predefined = store
            .create(&json!({
                "name": "预定义模板",
                "description": "",
                "field_mapping": {},
                "metadata": {"is_predefined": true}
            }))
            .expect("create predefined");
        let predefined_id = predefined["template_id"].clone();
        let blocked = store
            .delete(&json!({"id": predefined_id}))
            .expect("predefined delete");
        assert_eq!(blocked["success"], false);
        assert_eq!(blocked["message"], "预定义模板不能删除");
        let forced = store
            .delete(&json!({"id": predefined_id, "force": true}))
            .expect("forced predefined delete");
        assert_eq!(forced["success"], true);

        let import_path = root.join("import.json");
        fs::write(
            &import_path,
            serde_json::to_vec_pretty(&json!({
                "name": "导入模板",
                "description": "导入",
                "field_mapping": {"A": "B"}
            }))
            .expect("serialize import"),
        )
        .expect("write import");
        let imported = store
            .import_template(&json!({"import_path": import_path}))
            .expect("import");
        assert_eq!(imported["success"], true);
        let duplicate = store
            .import_template(&json!({"import_path": root.join("import.json"), "overwrite": true}))
            .expect("overwrite import");
        assert_eq!(duplicate["success"], true);
        let listed = store.list(&json!({})).expect("list imported templates");
        let imported_count = listed["templates"]
            .as_array()
            .expect("template array")
            .iter()
            .filter(|template| template["name"] == "导入模板")
            .count();
        assert_eq!(imported_count, 2);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn export_adds_json_extension_without_creating_parent() {
        let (store, root) = isolated_store();
        let created = store
            .create(&json!({
                "name": "导出模板",
                "description": "",
                "field_mapping": {}
            }))
            .expect("create");
        let output = root.join("out").join("template");
        let result = store
            .export_template(&json!({
                "template_id": created["template_id"],
                "export_path": output
            }))
            .expect("export result");
        assert_eq!(result["success"], false);
        assert!(!root.join("out").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn typed_template_requests_accept_camel_case_aliases() {
        let (store, root) = isolated_store();
        let created = store
            .create(&json!({
                "name": "Camel模板",
                "description": "描述",
                "fieldMapping": {"目标": "来源"},
                "sourceFormat": "csv",
                "templateFormat": "xlsx",
                "targetTemplate": "target.xlsx"
            }))
            .expect("create with aliases");
        assert_eq!(created["success"], true);
        assert_eq!(created["template"]["field_mapping"]["目标"], "来源");
        assert_eq!(created["template"]["source_format"], "csv");
        assert_eq!(created["template"]["target_template"], "target.xlsx");

        let id = created["template_id"].clone();
        let got = store
            .get(&json!({"templateId": id, "markUsed": true}))
            .expect("get with aliases");
        assert_eq!(got["template"]["usage_count"], 1);

        let listed = store
            .list(&json!({"filterFormat": "csv"}))
            .expect("list with alias");
        assert_eq!(listed["count"], 1);

        let updated = store
            .save(&json!({
                "templateId": created["template_id"],
                "name": "Camel模板改名",
                "targetTemplate": "next.xlsx"
            }))
            .expect("save with aliases");
        assert_eq!(updated["template"]["name"], "Camel模板改名");
        assert_eq!(updated["template"]["target_template"], "next.xlsx");

        let import_request: TemplateImportRequest =
            parse_request(&json!({"importPath": " import.json ", "overwrite": 1})).unwrap();
        assert_eq!(import_request.import_path().unwrap(), "import.json");
        assert!(import_request.overwrite.is_truthy());
        let export_request: TemplateExportRequest = parse_request(&json!({
            "templateId": "template-id",
            "exportPath": " export.json "
        }))
        .unwrap();
        assert_eq!(export_request.export_path().unwrap(), "export.json");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn typed_template_requests_preserve_empty_and_invalid_errors() {
        let (store, root) = isolated_store();
        assert_eq!(
            store.create(&json!({"name": null})).unwrap_err(),
            "请输入模板名称"
        );
        assert_eq!(
            store
                .create(&json!({
                    "name": "坏映射",
                    "field_mapping": "not-an-object"
                }))
                .unwrap_err(),
            "字段映射必须是对象"
        );
        assert_eq!(store.get(&Value::Null).unwrap_err(), "请先选择模板");

        let request: TemplateUpdateRequest = parse_request(&json!({
            "template_id": "canonical",
            "templateId": "alias",
            "field_mapping": null,
            "mapping": {"目标": "来源"}
        }))
        .unwrap();
        assert_eq!(
            request.identifier.candidates(&request.fields.name)[0]
                .trimmed_truthy_text()
                .as_deref(),
            Some("canonical")
        );
        assert_eq!(request.fields.mapping(true).unwrap()["目标"], "来源");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn python_extension_edges_append_json_like_pathlib() {
        let cases = [
            ("template", "template.json"),
            ("template.", "template..json"),
            ("template..", "template...json"),
            (".template", ".template.json"),
            ("template.csv", "template.csv"),
        ];
        for (input, expected) in cases {
            assert_eq!(
                ensure_python_json_extension(PathBuf::from(input)),
                PathBuf::from(expected),
                "extension mismatch for {input}"
            );
        }
    }
}
