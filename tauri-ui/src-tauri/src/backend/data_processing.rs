use calamine::{open_workbook_auto, Data, Reader};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Map, Number, Value};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Default, Deserialize)]
struct TableSourceRequest {
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    source_file: Option<String>,
    #[serde(
        default,
        rename = "sourceFile",
        deserialize_with = "deserialize_trimmed_string"
    )]
    source_file_alias: Option<String>,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    custom_separator: Option<String>,
    #[serde(
        default,
        rename = "customSeparator",
        deserialize_with = "deserialize_trimmed_string"
    )]
    custom_separator_alias: Option<String>,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    delimiter: Option<String>,
}

impl TableSourceRequest {
    fn source_path(&self, message: &str) -> Result<PathBuf, String> {
        self.source_file
            .as_ref()
            .or(self.source_file_alias.as_ref())
            .map(PathBuf::from)
            .ok_or_else(|| message.to_string())
    }

    fn separator(&self) -> Option<char> {
        self.custom_separator
            .as_deref()
            .or(self.custom_separator_alias.as_deref())
            .or(self.delimiter.as_deref())
            .and_then(parse_separator)
    }
}

#[derive(Debug, Default, Deserialize)]
struct FieldHeadersRequest {
    #[serde(flatten)]
    source: TableSourceRequest,
}

#[derive(Debug, Default, Deserialize)]
struct FieldExtractRequest {
    #[serde(flatten)]
    source: TableSourceRequest,
    #[serde(default, deserialize_with = "deserialize_string_array")]
    selected_fields: Vec<String>,
    #[serde(
        default,
        rename = "selectedFields",
        deserialize_with = "deserialize_string_array"
    )]
    selected_fields_alias: Vec<String>,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    output_file: Option<String>,
    #[serde(
        default,
        rename = "outputFile",
        deserialize_with = "deserialize_trimmed_string"
    )]
    output_file_alias: Option<String>,
}

impl FieldExtractRequest {
    fn selected_fields(&self) -> &[String] {
        if self.selected_fields.is_empty() {
            &self.selected_fields_alias
        } else {
            &self.selected_fields
        }
    }

    fn output_file(&self) -> Option<&str> {
        self.output_file
            .as_deref()
            .or(self.output_file_alias.as_deref())
    }
}

#[derive(Debug, Default, Deserialize)]
struct FillingAutoMapRequest {
    #[serde(flatten)]
    source: TableSourceRequest,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    template_file: Option<String>,
    #[serde(
        default,
        rename = "templateFile",
        deserialize_with = "deserialize_trimmed_string"
    )]
    template_file_alias: Option<String>,
    #[serde(default, deserialize_with = "deserialize_optional_f64")]
    similarity_threshold: Option<f64>,
    #[serde(
        default,
        rename = "similarityThreshold",
        deserialize_with = "deserialize_optional_f64"
    )]
    similarity_threshold_alias: Option<f64>,
}

impl FillingAutoMapRequest {
    fn template_path(&self) -> Result<PathBuf, String> {
        self.template_file
            .as_ref()
            .or(self.template_file_alias.as_ref())
            .map(PathBuf::from)
            .ok_or_else(|| "请先选择目标模板文件".to_string())
    }

    fn similarity_threshold(&self) -> f64 {
        self.similarity_threshold
            .or(self.similarity_threshold_alias)
            .unwrap_or(0.6)
            .clamp(0.0, 1.0)
    }
}

#[derive(Debug, Default)]
enum MappingInput {
    #[default]
    Missing,
    Invalid,
    Mapping(BTreeMap<String, String>),
}

impl<'de> Deserialize<'de> for MappingInput {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        let Value::Object(values) = value else {
            return Ok(Self::Invalid);
        };
        let mapping = values
            .into_iter()
            .filter_map(|(template, source)| {
                let template = template.trim();
                let source = source.as_str()?.trim();
                (!template.is_empty() && !source.is_empty())
                    .then(|| (template.to_string(), source.to_string()))
            })
            .collect();
        Ok(Self::Mapping(mapping))
    }
}

#[derive(Debug, Default, Deserialize)]
struct FillingMappingRequest {
    #[serde(flatten)]
    source: TableSourceRequest,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    template_file: Option<String>,
    #[serde(
        default,
        rename = "templateFile",
        deserialize_with = "deserialize_trimmed_string"
    )]
    template_file_alias: Option<String>,
    #[serde(default)]
    field_mapping: MappingInput,
    #[serde(default, rename = "fieldMapping")]
    field_mapping_alias: MappingInput,
    #[serde(default)]
    mapping: MappingInput,
}

impl FillingMappingRequest {
    fn template_path(&self) -> Result<PathBuf, String> {
        self.template_file
            .as_ref()
            .or(self.template_file_alias.as_ref())
            .map(PathBuf::from)
            .ok_or_else(|| "请先选择目标模板文件".to_string())
    }

    fn mapping(&self) -> Result<&BTreeMap<String, String>, String> {
        let selected = match &self.field_mapping {
            MappingInput::Missing => match &self.field_mapping_alias {
                MappingInput::Missing => &self.mapping,
                value => value,
            },
            value => value,
        };
        match selected {
            MappingInput::Mapping(mapping) if !mapping.is_empty() => Ok(mapping),
            MappingInput::Missing | MappingInput::Invalid | MappingInput::Mapping(_) => {
                Err("请先设置字段映射".to_string())
            }
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct FillingCustomMapRequest {
    #[serde(flatten)]
    mapping: FillingMappingRequest,
}

#[derive(Debug, Default, Deserialize)]
struct FillingPreviewRequest {
    #[serde(flatten)]
    mapping: FillingMappingRequest,
    #[serde(default, deserialize_with = "deserialize_optional_u64")]
    preview_rows: Option<u64>,
    #[serde(
        default,
        rename = "previewRows",
        deserialize_with = "deserialize_optional_u64"
    )]
    preview_rows_alias: Option<u64>,
}

impl FillingPreviewRequest {
    fn row_limit(&self) -> usize {
        self.preview_rows
            .or(self.preview_rows_alias)
            .unwrap_or(10)
            .min(10_000) as usize
    }
}

#[derive(Debug, Default, Deserialize)]
struct FillingRunRequest {
    #[serde(flatten)]
    mapping: FillingMappingRequest,
    #[serde(default, deserialize_with = "deserialize_trimmed_string")]
    output_file: Option<String>,
    #[serde(
        default,
        rename = "outputFile",
        deserialize_with = "deserialize_trimmed_string"
    )]
    output_file_alias: Option<String>,
}

impl FillingRunRequest {
    fn output_path(&self) -> Result<PathBuf, String> {
        self.output_file
            .as_ref()
            .or(self.output_file_alias.as_ref())
            .map(PathBuf::from)
            .ok_or_else(|| "请选择输出文件".to_string())
    }
}

#[derive(Debug, Serialize)]
struct FieldDetail {
    data_type: String,
    null_count: usize,
    null_percentage: f64,
    unique_count: usize,
    sample_values: Vec<Value>,
    description: String,
}

#[derive(Debug, Serialize)]
struct FieldHeadersResponse {
    success: bool,
    message: String,
    fields: Vec<String>,
    field_details: BTreeMap<String, FieldDetail>,
    #[serde(skip_serializing_if = "Option::is_none")]
    detected_separator: Option<String>,
}

#[derive(Debug, Serialize)]
struct MemoryUsageStatistics {
    original_mb: f64,
    extracted_mb: f64,
}

#[derive(Debug, Serialize)]
struct ExtractionQualityStatistics {
    total_null_values: usize,
    null_percentage: f64,
}

#[derive(Debug, Serialize)]
struct ExtractionStatistics {
    original_rows: usize,
    original_columns: usize,
    extracted_rows: usize,
    extracted_columns: usize,
    extraction_ratio: f64,
    memory_usage: MemoryUsageStatistics,
    data_quality: ExtractionQualityStatistics,
}

#[derive(Debug, Serialize)]
struct FieldExtractResponse {
    success: bool,
    message: String,
    extracted_data: Option<Vec<Vec<Value>>>,
    output_file: Option<String>,
    #[serde(serialize_with = "serialize_optional_object")]
    statistics: Option<ExtractionStatistics>,
    #[serde(skip_serializing_if = "Option::is_none")]
    selected_fields: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    detected_separator: Option<String>,
}

#[derive(Debug, Serialize)]
struct MappingRow {
    source_field: String,
    template_field: String,
    status: String,
    confidence: Option<f64>,
}

#[derive(Debug, Serialize)]
struct AutoMapResponse {
    success: bool,
    message: String,
    auto_mapping: BTreeMap<String, String>,
    confidence_scores: BTreeMap<String, f64>,
    unmapped_fields: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    mapping_rows: Option<Vec<MappingRow>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_fields: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    template_fields: Option<Vec<String>>,
}

#[derive(Debug, Serialize)]
struct CustomMapResponse {
    success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    field_mapping: Option<BTreeMap<String, String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    mapping_rows: Option<Vec<MappingRow>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_fields: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    template_fields: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    missing_sources: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    missing_templates: Option<Vec<String>>,
}

#[derive(Debug, Serialize)]
struct MappedFieldInfo {
    source_field: String,
    source_type: String,
    template_type: String,
    source_sample: Vec<Value>,
    null_count: usize,
}

#[derive(Debug, Serialize)]
struct MappingInfo {
    mapped_fields: BTreeMap<String, MappedFieldInfo>,
    unmapped_template_fields: Vec<String>,
    unused_source_fields: Vec<String>,
}

#[derive(Debug, Serialize)]
struct FillingPreviewResponse {
    success: bool,
    message: String,
    preview_data: Option<Vec<Value>>,
    #[serde(serialize_with = "serialize_optional_object")]
    mapping_info: Option<MappingInfo>,
    warnings: Vec<String>,
}

#[derive(Debug, Serialize)]
struct TableDimensions {
    rows: usize,
    columns: usize,
}

#[derive(Debug, Serialize)]
struct FillingRatioStatistics {
    mapped_columns: usize,
    total_columns: usize,
    percentage: f64,
}

#[derive(Debug, Serialize)]
struct FillingQualityStatistics {
    total_cells: usize,
    filled_cells: usize,
    empty_cells: usize,
}

#[derive(Debug, Serialize)]
struct FillingStatistics {
    source_info: TableDimensions,
    template_info: TableDimensions,
    result_info: TableDimensions,
    filling_ratio: FillingRatioStatistics,
    data_quality: FillingQualityStatistics,
}

#[derive(Debug, Serialize)]
struct FillingRunResponse {
    success: bool,
    message: String,
    output_file: Option<String>,
    #[serde(serialize_with = "serialize_optional_object")]
    statistics: Option<FillingStatistics>,
    warnings: Vec<String>,
    operation_type: &'static str,
    mapped_fields: usize,
    source_format: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    filled_count: Option<usize>,
}

#[derive(Debug, Clone)]
struct DataTable {
    headers: Vec<String>,
    rows: Vec<Vec<Value>>,
    detected_separator: String,
}

impl DataTable {
    fn column_index(&self, name: &str) -> Option<usize> {
        self.headers.iter().position(|header| header == name)
    }

    fn records(&self) -> Vec<Value> {
        self.rows
            .iter()
            .map(|row| {
                let mut record = Map::with_capacity(self.headers.len());
                for (index, header) in self.headers.iter().enumerate() {
                    record.insert(
                        header.clone(),
                        row.get(index).cloned().unwrap_or(Value::Null),
                    );
                }
                Value::Object(record)
            })
            .collect()
    }

    fn normalize_pandas_numeric_columns(mut self) -> Self {
        for column in 0..self.headers.len() {
            let has_null = self
                .rows
                .iter()
                .any(|row| row.get(column).is_none_or(Value::is_null));
            let has_float = self.rows.iter().any(|row| {
                row.get(column)
                    .and_then(Value::as_number)
                    .is_some_and(|number| number.is_f64())
            });
            let numeric_only = self.rows.iter().all(|row| {
                row.get(column)
                    .is_none_or(|value| value.is_null() || value.is_number())
            });
            if numeric_only && (has_null || has_float) {
                for row in &mut self.rows {
                    let Some(value) = row.get_mut(column) else {
                        continue;
                    };
                    let Some(number) = value.as_f64().and_then(Number::from_f64) else {
                        continue;
                    };
                    *value = Value::Number(number);
                }
            }
        }
        self
    }

    fn normalize_pandas_delimited_columns(mut self) -> Self {
        self = self.normalize_pandas_numeric_columns();
        for column in 0..self.headers.len() {
            let has_string = self.rows.iter().any(|row| {
                row.get(column)
                    .is_some_and(|value| !value.is_null() && value.is_string())
            });
            if !has_string {
                continue;
            }
            for row in &mut self.rows {
                let Some(value) = row.get_mut(column) else {
                    continue;
                };
                if !value.is_null() && !value.is_string() {
                    *value = Value::String(display_value(value));
                }
            }
        }
        self
    }
}

pub fn dispatch(command: &str, payload: &Value) -> Result<Value, String> {
    match command {
        "data.field_extract.headers" => {
            field_extract_headers(&parse_request::<FieldHeadersRequest>(payload))
        }
        "data.field_extract.run" => {
            field_extract_run(&parse_request::<FieldExtractRequest>(payload))
        }
        "data.filling.auto_map" => {
            filling_auto_map(&parse_request::<FillingAutoMapRequest>(payload))
        }
        "data.filling.custom_map" => {
            filling_custom_map(&parse_request::<FillingCustomMapRequest>(payload))
        }
        "data.filling.preview" => filling_preview(&parse_request::<FillingPreviewRequest>(payload)),
        "data.filling.run" => filling_run(&parse_request::<FillingRunRequest>(payload)),
        _ => Err(format!("未知数据处理命令: {command}")),
    }
}

pub fn is_command(command: &str) -> bool {
    matches!(
        command,
        "data.field_extract.headers"
            | "data.field_extract.run"
            | "data.filling.preview"
            | "data.filling.run"
            | "data.filling.auto_map"
            | "data.filling.custom_map"
    )
}

fn field_extract_headers(request: &FieldHeadersRequest) -> Result<Value, String> {
    let source = request.source.source_path("请先选择数据文件")?;
    let response = match read_table(&source, request.source.separator()) {
        Ok(table) => {
            let mut details = BTreeMap::new();
            for (column, header) in table.headers.iter().enumerate() {
                let values: Vec<&Value> = table
                    .rows
                    .iter()
                    .map(|row| row.get(column).unwrap_or(&Value::Null))
                    .collect();
                let non_null: Vec<&Value> = values
                    .iter()
                    .copied()
                    .filter(|value| !is_empty(value))
                    .collect();
                let unique_count = non_null
                    .iter()
                    .map(|value| canonical_value(value))
                    .collect::<HashSet<_>>()
                    .len();
                let null_count = values.len().saturating_sub(non_null.len());
                let null_percentage = if values.is_empty() {
                    0.0
                } else {
                    ((null_count as f64 / values.len() as f64) * 10_000.0).round() / 100.0
                };
                let samples: Vec<Value> = non_null.into_iter().take(5).cloned().collect();
                details.insert(
                    header.clone(),
                    FieldDetail {
                        data_type: infer_type(&values).to_string(),
                        null_count,
                        null_percentage,
                        unique_count,
                        sample_values: samples,
                        description: describe_column(&values),
                    },
                );
            }
            FieldHeadersResponse {
                success: true,
                message: format!("找到 {} 个字段", table.headers.len()),
                fields: table.headers,
                field_details: details,
                detected_separator: Some(table.detected_separator),
            }
        }
        Err(error) => FieldHeadersResponse {
            success: false,
            message: format!("获取字段失败: {error}"),
            fields: Vec::new(),
            field_details: BTreeMap::new(),
            detected_separator: None,
        },
    };
    serialize_response(response)
}

fn field_extract_run(request: &FieldExtractRequest) -> Result<Value, String> {
    let source = request.source.source_path("请先选择数据文件")?;
    let selected = request.selected_fields().to_vec();
    if selected.is_empty() {
        return Err("请选择要提取的字段".to_string());
    }

    let result = (|| -> Result<FieldExtractResponse, String> {
        let table = read_table(&source, request.source.separator())?;
        let mut indices = Vec::with_capacity(selected.len());
        let mut missing = Vec::new();
        for field in &selected {
            match table.column_index(field) {
                Some(index) => indices.push(index),
                None => missing.push(field.clone()),
            }
        }
        if !missing.is_empty() {
            return Ok(FieldExtractResponse {
                success: false,
                message: format!("以下字段不存在: {}", missing.join(", ")),
                extracted_data: None,
                output_file: None,
                statistics: None,
                selected_fields: None,
                detected_separator: Some(table.detected_separator),
            });
        }

        let extracted = DataTable {
            headers: selected.clone(),
            rows: table
                .rows
                .iter()
                .map(|row| {
                    indices
                        .iter()
                        .map(|index| row.get(*index).cloned().unwrap_or(Value::Null))
                        .collect()
                })
                .collect(),
            detected_separator: table.detected_separator.clone(),
        };
        let output = request
            .output_file()
            .map(PathBuf::from)
            .map(|path| output_with_default_extension(path, "csv"));
        if let Some(path) = output.as_deref() {
            write_table(path, &extracted)?;
        }

        Ok(FieldExtractResponse {
            success: true,
            message: format!(
                "成功提取 {} 个字段，共 {} 行数据",
                selected.len(),
                extracted.rows.len()
            ),
            extracted_data: Some(extracted.rows.clone()),
            selected_fields: Some(selected.clone()),
            output_file: output.map(path_string),
            detected_separator: Some(extracted.detected_separator.clone()),
            statistics: Some(extraction_statistics(&extracted, &table)),
        })
    })();

    serialize_response(result.unwrap_or_else(|error| FieldExtractResponse {
        success: false,
        message: format!("提取失败: {error}"),
        extracted_data: None,
        output_file: None,
        statistics: None,
        selected_fields: None,
        detected_separator: None,
    }))
}

fn filling_auto_map(request: &FillingAutoMapRequest) -> Result<Value, String> {
    let source = request.source.source_path("请先选择源文件")?;
    let template = request.template_path()?;
    let threshold = request.similarity_threshold();

    let result = (|| -> Result<AutoMapResponse, String> {
        let source_table = read_table(&source, request.source.separator())?;
        let template_table = read_table(&template, None)?;
        let mut mapping = BTreeMap::new();
        let mut confidence = BTreeMap::new();
        let mut unmapped = Vec::new();

        for template_field in &template_table.headers {
            let mut best = None;
            for source_field in &source_table.headers {
                let score = field_similarity(template_field, source_field);
                if best.is_none_or(|(_, best_score)| score > best_score) {
                    best = Some((source_field, score));
                }
            }
            if let Some((source_field, score)) = best.filter(|(_, score)| *score >= threshold) {
                mapping.insert(template_field.clone(), source_field.clone());
                confidence.insert(template_field.clone(), score);
            } else {
                unmapped.push(template_field.clone());
            }
        }

        Ok(AutoMapResponse {
            success: true,
            message: format!(
                "自动映射了 {} 个字段，{} 个字段未映射",
                mapping.len(),
                unmapped.len()
            ),
            mapping_rows: Some(mapping_rows(
                &source_table.headers,
                &template_table.headers,
                &mapping,
                Some(&confidence),
            )),
            source_fields: Some(source_table.headers),
            template_fields: Some(template_table.headers),
            auto_mapping: mapping,
            confidence_scores: confidence,
            unmapped_fields: unmapped,
        })
    })();

    serialize_response(result.unwrap_or_else(|error| AutoMapResponse {
        success: false,
        message: format!("自动映射失败: {error}"),
        auto_mapping: BTreeMap::new(),
        confidence_scores: BTreeMap::new(),
        unmapped_fields: Vec::new(),
        mapping_rows: None,
        source_fields: None,
        template_fields: None,
    }))
}

fn filling_custom_map(request: &FillingCustomMapRequest) -> Result<Value, String> {
    let source = request.mapping.source.source_path("请先选择源文件")?;
    let template = request.mapping.template_path()?;
    let mapping = request.mapping.mapping()?;

    let source_table = match read_table(&source, request.mapping.source.separator()) {
        Ok(table) => table,
        Err(error) => {
            return serialize_response(CustomMapResponse {
                success: false,
                message: format!("加载源字段失败: {error}"),
                field_mapping: None,
                mapping_rows: None,
                source_fields: None,
                template_fields: None,
                missing_sources: None,
                missing_templates: None,
            })
        }
    };
    let template_table = match read_table(&template, None) {
        Ok(table) => table,
        Err(error) => {
            return serialize_response(CustomMapResponse {
                success: false,
                message: format!("加载模板字段失败: {error}"),
                field_mapping: None,
                mapping_rows: None,
                source_fields: None,
                template_fields: None,
                missing_sources: None,
                missing_templates: None,
            })
        }
    };

    let source_set: HashSet<&str> = source_table.headers.iter().map(String::as_str).collect();
    let template_set: HashSet<&str> = template_table.headers.iter().map(String::as_str).collect();
    let missing_sources: Vec<String> = mapping
        .values()
        .filter(|field| !source_set.contains(field.as_str()))
        .cloned()
        .collect();
    let missing_templates: Vec<String> = mapping
        .keys()
        .filter(|field| !template_set.contains(field.as_str()))
        .cloned()
        .collect();
    if !missing_sources.is_empty() || !missing_templates.is_empty() {
        return serialize_response(CustomMapResponse {
            success: false,
            message: "字段映射中存在无效字段".to_string(),
            field_mapping: None,
            mapping_rows: None,
            source_fields: None,
            template_fields: None,
            missing_sources: Some(missing_sources),
            missing_templates: Some(missing_templates),
        });
    }

    serialize_response(CustomMapResponse {
        success: true,
        message: format!("已设置 {} 个字段映射", mapping.len()),
        field_mapping: Some(mapping.clone()),
        mapping_rows: Some(mapping_rows(
            &source_table.headers,
            &template_table.headers,
            mapping,
            None,
        )),
        source_fields: Some(source_table.headers),
        template_fields: Some(template_table.headers),
        missing_sources: None,
        missing_templates: None,
    })
}

fn filling_preview(request: &FillingPreviewRequest) -> Result<Value, String> {
    let source = request.mapping.source.source_path("请先选择源文件")?;
    let template = request.mapping.template_path()?;
    let mapping = request.mapping.mapping()?;
    let rows = request.row_limit();

    let result = (|| -> Result<FillingPreviewResponse, String> {
        let source_table = read_table(&source, request.mapping.source.separator())?;
        let template_table = read_table(&template, None)?;
        let warnings = validate_mapping(&source_table.headers, &template_table.headers, mapping)?;
        let filled = fill_table(&source_table, &template_table.headers, mapping, Some(rows));
        Ok(FillingPreviewResponse {
            success: true,
            message: format!("预览前 {} 行填充结果", filled.rows.len()),
            preview_data: Some(filled.records()),
            mapping_info: Some(mapping_info(
                &source_table,
                &template_table.headers,
                mapping,
            )),
            warnings,
        })
    })();

    serialize_response(result.unwrap_or_else(|error| FillingPreviewResponse {
        success: false,
        message: format!("预览失败: {error}"),
        preview_data: None,
        mapping_info: None,
        warnings: Vec::new(),
    }))
}

fn filling_run(request: &FillingRunRequest) -> Result<Value, String> {
    let source = request.mapping.source.source_path("请先选择源文件")?;
    let template = request.mapping.template_path()?;
    let output = request.output_path()?;
    let output = output_with_default_extension(output, "xlsx");
    let mapping = request.mapping.mapping()?;

    let result = (|| -> Result<FillingRunResponse, String> {
        let source_table = read_table(&source, request.mapping.source.separator())?;
        let template_table = read_table(&template, None)?;
        let warnings = validate_mapping(&source_table.headers, &template_table.headers, mapping)?;
        let filled = fill_table(&source_table, &template_table.headers, mapping, None);
        write_table(&output, &filled)?;
        let statistics = filling_statistics(&source_table, &template_table, &filled);

        Ok(FillingRunResponse {
            success: true,
            message: format!("成功填充 {} 行数据到模板", filled.rows.len()),
            output_file: Some(path_string(&output)),
            statistics: Some(statistics),
            warnings,
            operation_type: "fill_template",
            mapped_fields: mapping.len(),
            source_format: source_format(&source),
            filled_count: Some(filled.rows.len()),
        })
    })();

    serialize_response(result.unwrap_or_else(|error| FillingRunResponse {
        success: false,
        message: format!("填充失败: {error}"),
        output_file: None,
        statistics: None,
        warnings: Vec::new(),
        operation_type: "fill_template",
        mapped_fields: mapping.len(),
        source_format: source_format(&source),
        filled_count: None,
    }))
}

fn read_table(path: &Path, custom_separator: Option<char>) -> Result<DataTable, String> {
    if !path.exists() {
        return Err(format!("文件不存在: {}", path.display()));
    }
    match extension(path).as_str() {
        "xlsx" | "xls" | "xlsb" | "ods" => read_excel(path),
        "csv" => read_delimited(
            path,
            custom_separator.unwrap_or(','),
            custom_separator.map(|_| "自定义分隔符"),
        ),
        "tsv" => read_delimited(path, custom_separator.unwrap_or('\t'), Some("制表符")),
        "txt" => read_text(path, custom_separator),
        suffix => Err(format!(
            "不支持的文件格式: .{suffix}。支持的格式: .xlsx, .xls, .csv, .txt, .tsv"
        )),
    }
}

fn read_excel(path: &Path) -> Result<DataTable, String> {
    let mut workbook =
        open_workbook_auto(path).map_err(|error| format!("读取 Excel 文件失败: {error}"))?;
    let range = workbook
        .worksheet_range_at(0)
        .ok_or_else(|| "Excel 文件没有工作表".to_string())?
        .map_err(|error| format!("读取 Excel 工作表失败: {error}"))?;
    let mut raw_rows = range.rows();
    let header_cells = raw_rows
        .next()
        .ok_or_else(|| "文件不包含表头".to_string())?;
    let headers = normalize_headers(header_cells.iter().map(excel_header).collect());
    let rows = raw_rows
        .map(|row| {
            (0..headers.len())
                .map(|index| row.get(index).map(excel_value).unwrap_or(Value::Null))
                .collect()
        })
        .collect();
    Ok(DataTable {
        headers,
        rows,
        detected_separator: "Excel格式".to_string(),
    }
    .normalize_pandas_numeric_columns())
}

fn read_text(path: &Path, custom_separator: Option<char>) -> Result<DataTable, String> {
    let content = read_text_content(path)?;
    if let Some(separator) = custom_separator {
        return parse_delimited_content(
            &content,
            separator,
            format!("自定义分隔符: \"{separator}\""),
        );
    }
    for (separator, label) in [
        ('\t', "制表符 (\"\\t\")"),
        (',', "逗号 (\",\")"),
        ('|', "竖线 (\"|\")"),
        (';', "分号 (\";\")"),
    ] {
        if let Ok(table) = parse_delimited_content(&content, separator, label.to_string()) {
            if table.headers.len() > 1 {
                return Ok(table);
            }
        }
    }
    let lines: Vec<Vec<Value>> = content
        .lines()
        .map(|line| vec![Value::String(line.trim().to_string())])
        .collect();
    Ok(DataTable {
        headers: vec!["content".to_string()],
        rows: lines,
        detected_separator: "按行读取".to_string(),
    })
}

fn read_delimited(path: &Path, separator: char, label: Option<&str>) -> Result<DataTable, String> {
    let content = read_text_content(path)?;
    let detected = match label {
        Some("自定义分隔符") => format!("自定义分隔符: \"{separator}\""),
        Some("制表符") => "制表符 (\"\\t\")".to_string(),
        _ => "逗号分隔符 (\",\")".to_string(),
    };
    parse_delimited_content(&content, separator, detected)
}

fn parse_delimited_content(
    content: &str,
    separator: char,
    detected: String,
) -> Result<DataTable, String> {
    if !separator.is_ascii() {
        return Err("分隔符必须是单字节字符".to_string());
    }
    let mut reader = csv::ReaderBuilder::new()
        .delimiter(separator as u8)
        .flexible(true)
        .from_reader(content.as_bytes());
    let headers = normalize_headers(
        reader
            .headers()
            .map_err(|error| format!("读取表头失败: {error}"))?
            .iter()
            .map(ToOwned::to_owned)
            .collect(),
    );
    if headers.is_empty() {
        return Err("文件不包含表头".to_string());
    }
    let mut rows = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|error| format!("读取数据失败: {error}"))?;
        rows.push(
            (0..headers.len())
                .map(|index| parse_scalar(record.get(index).unwrap_or_default()))
                .collect(),
        );
    }
    Ok(DataTable {
        headers,
        rows,
        detected_separator: detected,
    }
    .normalize_pandas_delimited_columns())
}

fn read_text_content(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|error| format!("读取文件失败: {error}"))?;
    if let Ok(text) = std::str::from_utf8(bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&bytes))
    {
        return Ok(text.to_string());
    }
    decode_gbk(&bytes).ok_or_else(|| "文件编码既不是 UTF-8，也不是 GBK/GB2312".to_string())
}

fn write_table(path: &Path, table: &DataTable) -> Result<(), String> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|error| format!("创建输出目录失败: {error}"))?;
    }
    match extension(path).as_str() {
        "xlsx" | "xls" => write_xlsx(path, table),
        "txt" | "tsv" => write_delimited(path, table, b'\t'),
        "csv" => write_delimited(path, table, b','),
        _ => write_delimited(&path.with_extension("csv"), table, b','),
    }
}

fn write_delimited(path: &Path, table: &DataTable, delimiter: u8) -> Result<(), String> {
    let mut writer = csv::WriterBuilder::new()
        .delimiter(delimiter)
        .from_path(path)
        .map_err(|error| format!("创建输出文件失败: {error}"))?;
    writer
        .write_record(&table.headers)
        .map_err(|error| format!("写入表头失败: {error}"))?;
    for row in &table.rows {
        writer
            .write_record(
                (0..table.headers.len())
                    .map(|index| row.get(index).map(display_value).unwrap_or_default()),
            )
            .map_err(|error| format!("写入数据失败: {error}"))?;
    }
    writer
        .flush()
        .map_err(|error| format!("保存文件失败: {error}"))
}

fn write_xlsx(path: &Path, table: &DataTable) -> Result<(), String> {
    use rust_xlsxwriter::Workbook;

    let mut workbook = Workbook::new();
    let worksheet = workbook.add_worksheet();
    for (column, header) in table.headers.iter().enumerate() {
        worksheet
            .write_string(0, column as u16, header)
            .map_err(|error| format!("写入 Excel 表头失败: {error}"))?;
    }
    for (row_index, row) in table.rows.iter().enumerate() {
        for column in 0..table.headers.len() {
            let value = row.get(column).unwrap_or(&Value::Null);
            let row_number = (row_index + 1) as u32;
            let column_number = column as u16;
            match value {
                Value::Null => {}
                Value::Bool(value) => {
                    worksheet
                        .write_boolean(row_number, column_number, *value)
                        .map_err(|error| format!("写入 Excel 数据失败: {error}"))?;
                }
                Value::Number(value) => {
                    worksheet
                        .write_number(
                            row_number,
                            column_number,
                            value.as_f64().unwrap_or_default(),
                        )
                        .map_err(|error| format!("写入 Excel 数据失败: {error}"))?;
                }
                _ => {
                    worksheet
                        .write_string(row_number, column_number, display_value(value))
                        .map_err(|error| format!("写入 Excel 数据失败: {error}"))?;
                }
            };
        }
    }
    workbook
        .save(path)
        .map_err(|error| format!("保存 Excel 文件失败: {error}"))
}

fn fill_table(
    source: &DataTable,
    template_headers: &[String],
    mapping: &BTreeMap<String, String>,
    limit: Option<usize>,
) -> DataTable {
    let indices: HashMap<&str, usize> = source
        .headers
        .iter()
        .enumerate()
        .map(|(index, header)| (header.as_str(), index))
        .collect();
    let rows = source
        .rows
        .iter()
        .take(limit.unwrap_or(usize::MAX))
        .map(|source_row| {
            template_headers
                .iter()
                .map(|template_field| {
                    mapping
                        .get(template_field)
                        .and_then(|source_field| indices.get(source_field.as_str()))
                        .and_then(|index| source_row.get(*index))
                        .cloned()
                        .unwrap_or(Value::Null)
                })
                .collect()
        })
        .collect();
    DataTable {
        headers: template_headers.to_vec(),
        rows,
        detected_separator: "Excel格式".to_string(),
    }
}

fn validate_mapping(
    source_fields: &[String],
    template_fields: &[String],
    mapping: &BTreeMap<String, String>,
) -> Result<Vec<String>, String> {
    let source: HashSet<&str> = source_fields.iter().map(String::as_str).collect();
    let template: HashSet<&str> = template_fields.iter().map(String::as_str).collect();
    let missing_template: Vec<&str> = mapping
        .keys()
        .map(String::as_str)
        .filter(|field| !template.contains(field))
        .collect();
    if !missing_template.is_empty() {
        return Err(format!(
            "模板中不存在以下字段: {}",
            missing_template.join(", ")
        ));
    }
    let missing_source: Vec<&str> = mapping
        .values()
        .map(String::as_str)
        .filter(|field| !source.contains(field))
        .collect();
    if !missing_source.is_empty() {
        return Err(format!(
            "源数据中不存在以下字段: {}",
            missing_source.join(", ")
        ));
    }
    let unmapped: Vec<&str> = template_fields
        .iter()
        .map(String::as_str)
        .filter(|field| !mapping.contains_key(*field))
        .collect();
    Ok(if unmapped.is_empty() {
        Vec::new()
    } else {
        vec![format!(
            "以下模板字段未映射，将保持为空: {}",
            unmapped.join(", ")
        )]
    })
}

fn mapping_rows(
    source_fields: &[String],
    template_fields: &[String],
    mapping: &BTreeMap<String, String>,
    confidence: Option<&BTreeMap<String, f64>>,
) -> Vec<MappingRow> {
    let mut used = HashSet::new();
    let mut rows = Vec::new();
    for template_field in template_fields {
        let source_field = mapping.get(template_field).cloned().unwrap_or_default();
        if !source_field.is_empty() {
            used.insert(source_field.clone());
        }
        rows.push(MappingRow {
            source_field,
            template_field: template_field.clone(),
            status: if mapping.contains_key(template_field) {
                "已映射".to_string()
            } else {
                "待映射".to_string()
            },
            confidence: confidence
                .and_then(|scores| scores.get(template_field))
                .copied(),
        });
    }
    for source_field in source_fields {
        if !used.contains(source_field) {
            rows.push(MappingRow {
                source_field: source_field.clone(),
                template_field: String::new(),
                status: "待映射".to_string(),
                confidence: None,
            });
        }
    }
    rows
}

fn parse_separator(separator: &str) -> Option<char> {
    if separator == r"\t" {
        Some('\t')
    } else if separator == r"\s+" {
        None
    } else {
        let mut chars = separator.chars();
        let first = chars.next()?;
        chars.next().is_none().then_some(first)
    }
}

fn normalize_headers(headers: Vec<String>) -> Vec<String> {
    let mut used = HashMap::<String, usize>::new();
    headers
        .into_iter()
        .enumerate()
        .map(|(index, header)| {
            let header = header.trim().trim_start_matches('\u{feff}');
            let base = if header.is_empty() {
                format!("Unnamed: {index}")
            } else {
                header.to_string()
            };
            let count = used.entry(base.clone()).or_insert(0);
            let normalized = if *count == 0 {
                base
            } else {
                format!("{base}.{count}")
            };
            *count += 1;
            normalized
        })
        .collect()
}

fn excel_header(value: &Data) -> String {
    match value {
        Data::Empty => String::new(),
        _ => display_excel(value),
    }
}

fn excel_value(value: &Data) -> Value {
    match value {
        Data::Empty => Value::Null,
        Data::Int(value) => Value::Number((*value).into()),
        Data::Float(value) if value.is_finite() && value.fract() == 0.0 => {
            Value::Number((*value as i64).into())
        }
        Data::Float(value) => Number::from_f64(*value)
            .map(Value::Number)
            .unwrap_or(Value::Null),
        Data::Bool(value) => Value::Bool(*value),
        Data::String(value) | Data::DateTimeIso(value) | Data::DurationIso(value) => {
            Value::String(value.clone())
        }
        _ => Value::String(display_excel(value)),
    }
}

fn display_excel(value: &Data) -> String {
    match value {
        Data::Empty => String::new(),
        Data::Int(value) => value.to_string(),
        Data::Float(value) => value.to_string(),
        Data::String(value) | Data::DateTimeIso(value) | Data::DurationIso(value) => value.clone(),
        Data::Bool(value) => value.to_string(),
        Data::DateTime(value) => value.as_f64().to_string(),
        Data::Error(value) => format!("{value:?}"),
    }
}

fn parse_scalar(value: &str) -> Value {
    let value = value.trim();
    if is_pandas_na(value) {
        Value::Null
    } else if value.eq_ignore_ascii_case("true") {
        Value::Bool(true)
    } else if value.eq_ignore_ascii_case("false") {
        Value::Bool(false)
    } else if let Ok(integer) = value.parse::<i64>() {
        Value::Number(integer.into())
    } else if let Ok(float) = value.parse::<f64>() {
        Number::from_f64(float)
            .map(Value::Number)
            .unwrap_or(Value::String(value.to_string()))
    } else {
        Value::String(value.to_string())
    }
}

fn is_pandas_na(value: &str) -> bool {
    matches!(
        value,
        "" | "#N/A"
            | "#N/A N/A"
            | "#NA"
            | "-1.#IND"
            | "-1.#QNAN"
            | "-NaN"
            | "-nan"
            | "1.#IND"
            | "1.#QNAN"
            | "<NA>"
            | "N/A"
            | "NA"
            | "NULL"
            | "NaN"
            | "None"
            | "n/a"
            | "nan"
            | "null"
    )
}

fn display_value(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(value) => value.clone(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        value => value.to_string(),
    }
}

fn canonical_value(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        _ => value.to_string(),
    }
}

fn is_empty(value: &Value) -> bool {
    value.is_null() || value.as_str().is_some_and(str::is_empty)
}

fn infer_type(values: &[&Value]) -> &'static str {
    let mut has_string = false;
    let mut has_float = false;
    let mut has_integer = false;
    let mut has_bool = false;
    for value in values.iter().filter(|value| !is_empty(value)) {
        match value {
            Value::Bool(_) => has_bool = true,
            Value::Number(number) if number.is_i64() || number.is_u64() => has_integer = true,
            Value::Number(_) => has_float = true,
            _ => has_string = true,
        }
    }
    if has_string
        || [has_float, has_integer, has_bool]
            .into_iter()
            .filter(|flag| *flag)
            .count()
            > 1
    {
        "object"
    } else if has_float {
        "float64"
    } else if has_integer {
        "int64"
    } else if has_bool {
        "bool"
    } else {
        "object"
    }
}

fn describe_column(values: &[&Value]) -> String {
    let data_type = infer_type(values);
    let non_null = values
        .iter()
        .copied()
        .filter(|value| !is_empty(value))
        .collect::<Vec<_>>();
    let null_count = values.len().saturating_sub(non_null.len());
    let unique_count = non_null
        .iter()
        .map(|value| canonical_value(value))
        .collect::<HashSet<_>>()
        .len();
    let mut description = match data_type {
        "int64" | "float64" => {
            let numbers = non_null.iter().filter_map(|value| value.as_f64());
            let (minimum, maximum) = numbers
                .fold((f64::INFINITY, f64::NEG_INFINITY), |range, value| {
                    (range.0.min(value), range.1.max(value))
                });
            format!("数值型字段，范围: {minimum:.2} - {maximum:.2}")
        }
        "object" if (unique_count as f64) < values.len() as f64 * 0.1 => {
            format!("分类型字段，{unique_count} 个不同值")
        }
        "object" => format!("文本型字段，{unique_count} 个不同值"),
        other => format!("{other} 类型字段"),
    };
    if null_count > 0 {
        description.push_str(&format!("，包含 {null_count} 个空值"));
    }
    description
}

fn field_similarity(left: &str, right: &str) -> f64 {
    let left = left
        .to_lowercase()
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();
    let right = right
        .to_lowercase()
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();
    let sequence_similarity = sequence_matcher_ratio(&left, &right);
    let keyword_pattern = regex::Regex::new(r"\w+").expect("static keyword regex");
    let left_keywords = keyword_pattern
        .find_iter(&left)
        .map(|value| value.as_str())
        .collect::<HashSet<_>>();
    let right_keywords = keyword_pattern
        .find_iter(&right)
        .map(|value| value.as_str())
        .collect::<HashSet<_>>();
    if left_keywords.is_empty() || right_keywords.is_empty() {
        return sequence_similarity;
    }
    let intersection = left_keywords.intersection(&right_keywords).count();
    let union = left_keywords.union(&right_keywords).count();
    (sequence_similarity + intersection as f64 / union as f64) / 2.0
}

fn sequence_matcher_ratio(left: &str, right: &str) -> f64 {
    let left = left.chars().collect::<Vec<_>>();
    let right = right.chars().collect::<Vec<_>>();
    if left.is_empty() && right.is_empty() {
        return 1.0;
    }

    fn matching_size(left: &[char], right: &[char]) -> usize {
        let mut best = (0, 0, 0);
        let mut previous = vec![0_usize; right.len() + 1];
        for (left_index, left_value) in left.iter().enumerate() {
            let mut current = vec![0_usize; right.len() + 1];
            for (right_index, right_value) in right.iter().enumerate() {
                if left_value == right_value {
                    current[right_index + 1] = previous[right_index] + 1;
                    if current[right_index + 1] > best.2 {
                        best = (
                            left_index + 1 - current[right_index + 1],
                            right_index + 1 - current[right_index + 1],
                            current[right_index + 1],
                        );
                    }
                }
            }
            previous = current;
        }
        if best.2 == 0 {
            0
        } else {
            best.2
                + matching_size(&left[..best.0], &right[..best.1])
                + matching_size(&left[best.0 + best.2..], &right[best.1 + best.2..])
        }
    }

    2.0 * matching_size(&left, &right) as f64 / (left.len() + right.len()) as f64
}

fn extraction_statistics(extracted: &DataTable, original: &DataTable) -> ExtractionStatistics {
    let total_null_values = extracted
        .rows
        .iter()
        .flatten()
        .filter(|value| is_empty(value))
        .count();
    let total_cells = extracted.rows.len() * extracted.headers.len();
    ExtractionStatistics {
        original_rows: original.rows.len(),
        original_columns: original.headers.len(),
        extracted_rows: extracted.rows.len(),
        extracted_columns: extracted.headers.len(),
        extraction_ratio: if original.headers.is_empty() {
            0.0
        } else {
            ((extracted.headers.len() as f64 / original.headers.len() as f64 * 100.0) * 100.0)
                .round()
                / 100.0
        },
        memory_usage: MemoryUsageStatistics {
            original_mb: approximate_table_megabytes(original),
            extracted_mb: approximate_table_megabytes(extracted),
        },
        data_quality: ExtractionQualityStatistics {
            total_null_values,
            null_percentage: if total_cells == 0 {
                0.0
            } else {
                ((total_null_values as f64 / total_cells as f64) * 10_000.0).round() / 100.0
            },
        },
    }
}

fn approximate_table_megabytes(table: &DataTable) -> f64 {
    let index_bytes = 132_usize;
    let data_bytes = table
        .rows
        .iter()
        .flatten()
        .map(|value| match value {
            Value::Null | Value::Number(_) => 8,
            Value::Bool(_) => 1,
            Value::String(value) => 49 + value.len(),
            value => 49 + value.to_string().len(),
        })
        .sum::<usize>();
    (((index_bytes + data_bytes) as f64 / 1024.0 / 1024.0) * 100.0).round() / 100.0
}

fn filling_statistics(
    source: &DataTable,
    template: &DataTable,
    filled: &DataTable,
) -> FillingStatistics {
    let mapped_columns = (0..filled.headers.len())
        .filter(|column| {
            filled
                .rows
                .iter()
                .any(|row| row.get(*column).is_some_and(|value| !is_empty(value)))
        })
        .count();
    let filled_cells = filled
        .rows
        .iter()
        .flatten()
        .filter(|value| !is_empty(value))
        .count();
    let total_cells = filled.rows.len() * filled.headers.len();
    FillingStatistics {
        source_info: TableDimensions {
            rows: source.rows.len(),
            columns: source.headers.len(),
        },
        template_info: TableDimensions {
            rows: template.rows.len(),
            columns: template.headers.len(),
        },
        result_info: TableDimensions {
            rows: filled.rows.len(),
            columns: filled.headers.len(),
        },
        filling_ratio: FillingRatioStatistics {
            mapped_columns,
            total_columns: filled.headers.len(),
            percentage: if filled.headers.is_empty() {
                0.0
            } else {
                ((mapped_columns as f64 / filled.headers.len() as f64) * 10_000.0).round() / 100.0
            },
        },
        data_quality: FillingQualityStatistics {
            total_cells,
            filled_cells,
            empty_cells: total_cells.saturating_sub(filled_cells),
        },
    }
}

fn mapping_info(
    source: &DataTable,
    template_fields: &[String],
    mapping: &BTreeMap<String, String>,
) -> MappingInfo {
    let mut mapped = BTreeMap::new();
    for (template, source_field) in mapping {
        let index = source.column_index(source_field);
        let values: Vec<&Value> = index
            .map(|index| {
                source
                    .rows
                    .iter()
                    .map(move |row| row.get(index).unwrap_or(&Value::Null))
                    .collect()
            })
            .unwrap_or_default();
        mapped.insert(
            template.clone(),
            MappedFieldInfo {
                source_field: source_field.clone(),
                source_type: infer_type(&values).to_string(),
                template_type: "object".to_string(),
                source_sample: values
                    .iter()
                    .filter(|value| !is_empty(value))
                    .take(3)
                    .copied()
                    .cloned()
                    .collect(),
                null_count: values.iter().filter(|value| is_empty(value)).count(),
            },
        );
    }
    MappingInfo {
        mapped_fields: mapped,
        unmapped_template_fields: template_fields
            .iter()
            .filter(|field| !mapping.contains_key(*field))
            .cloned()
            .collect(),
        unused_source_fields: source
            .headers
            .iter()
            .filter(|field| !mapping.values().any(|mapped| mapped == *field))
            .cloned()
            .collect(),
    }
}

fn source_format(path: &Path) -> String {
    match extension(path).as_str() {
        "xlsx" | "xls" => "excel".to_string(),
        "txt" | "tsv" => "txt".to_string(),
        suffix => suffix.to_string(),
    }
}

fn extension(path: &Path) -> String {
    path.extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_lowercase()
}

fn output_with_default_extension(path: PathBuf, extension: &str) -> PathBuf {
    if path.extension().is_none() {
        path.with_extension(extension)
    } else {
        path
    }
}

fn path_string(path: impl AsRef<Path>) -> String {
    path.as_ref().to_string_lossy().into_owned()
}

fn decode_gbk(bytes: &[u8]) -> Option<String> {
    encoding_rs::GBK
        .decode_without_bom_handling_and_without_replacement(bytes)
        .map(|text| text.into_owned())
}

fn parse_request<T>(payload: &Value) -> T
where
    T: DeserializeOwned + Default,
{
    if !payload.is_object() {
        return T::default();
    }
    serde_json::from_value(payload.clone()).unwrap_or_default()
}

fn serialize_response<T>(response: T) -> Result<Value, String>
where
    T: Serialize,
{
    serde_json::to_value(response).map_err(|error| format!("响应序列化失败: {error}"))
}

fn serialize_optional_object<S, T>(value: &Option<T>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
    T: Serialize,
{
    match value {
        Some(value) => value.serialize(serializer),
        None => BTreeMap::<String, String>::new().serialize(serializer),
    }
}

fn deserialize_trimmed_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value
        .as_ref()
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned))
}

fn deserialize_string_array<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value
        .as_ref()
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect())
}

fn deserialize_optional_f64<'de, D>(deserializer: D) -> Result<Option<f64>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value.as_ref().and_then(Value::as_f64))
}

fn deserialize_optional_u64<'de, D>(deserializer: D) -> Result<Option<u64>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value.as_ref().and_then(Value::as_u64))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let unique = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path = std::env::temp_dir().join(format!("koi-data-processing-{unique}"));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn extracts_selected_csv_fields_and_writes_output() {
        let temp = TempDir::new();
        let source = temp.0.join("source.csv");
        let output = temp.0.join("result.csv");
        fs::write(
            &source,
            "name,age,city\nAlice,31,Shanghai\nBob,28,Beijing\n",
        )
        .unwrap();
        let result = dispatch(
            "data.field_extract.run",
            &json!({
                "source_file": path_string(&source),
                "selected_fields": ["name", "city"],
                "output_file": path_string(&output),
            }),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["extracted_data"][0], json!(["Alice", "Shanghai"]));
        let written = read_table(&output, None).unwrap();
        assert_eq!(written.headers, vec!["name", "city"]);
        assert_eq!(written.rows.len(), 2);
    }

    #[test]
    #[cfg(windows)]
    fn reads_gbk_and_detects_pipe_separator() {
        let temp = TempDir::new();
        let source = temp.0.join("source.txt");
        // Encoded as Windows code page 936 (GBK).
        fs::write(
            &source,
            [
                0xD0, 0xD5, 0xC3, 0xFB, b'|', 0xB3, 0xC7, 0xCA, 0xD0, b'\n', 0xD5, 0xC5, 0xC8,
                0xFD, b'|', 0xC9, 0xCF, 0xBA, 0xA3, b'\n',
            ],
        )
        .unwrap();
        let result = dispatch(
            "data.field_extract.headers",
            &json!({"source_file": path_string(&source)}),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["fields"], json!(["姓名", "城市"]));
        assert_eq!(result["detected_separator"], "竖线 (\"|\")");
    }

    #[test]
    fn fills_excel_template_from_csv() {
        let temp = TempDir::new();
        let source = temp.0.join("source.csv");
        let template = temp.0.join("template.xlsx");
        let output = temp.0.join("filled.xlsx");
        fs::write(&source, "person,years\nAlice,31\nBob,28\n").unwrap();
        write_xlsx(
            &template,
            &DataTable {
                headers: vec!["name".to_string(), "age".to_string(), "note".to_string()],
                rows: vec![],
                detected_separator: "Excel格式".to_string(),
            },
        )
        .unwrap();
        let result = dispatch(
            "data.filling.run",
            &json!({
                "source_file": path_string(&source),
                "template_file": path_string(&template),
                "output_file": path_string(&output),
                "field_mapping": {"name": "person", "age": "years"},
            }),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["filled_count"], 2);
        let filled = read_excel(&output).unwrap();
        assert_eq!(filled.headers, vec!["name", "age", "note"]);
        assert_eq!(filled.rows[0], vec![json!("Alice"), json!(31), Value::Null]);
    }

    #[test]
    fn auto_map_returns_fields_and_mapping_rows() {
        let temp = TempDir::new();
        let source = temp.0.join("source.csv");
        let template = temp.0.join("template.csv");
        fs::write(&source, "company_name,address\nKoi,Shanghai\n").unwrap();
        fs::write(&template, "company name,address,owner\n").unwrap();
        let result = dispatch(
            "data.filling.auto_map",
            &json!({
                "source_file": path_string(&source),
                "template_file": path_string(&template),
                "similarity_threshold": 0.6,
            }),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["auto_mapping"]["address"], "address");
        assert_eq!(result["source_fields"], json!(["company_name", "address"]));
        assert_eq!(
            result["template_fields"],
            json!(["company name", "address", "owner"])
        );
    }

    #[test]
    fn custom_map_rejects_unknown_fields() {
        let temp = TempDir::new();
        let source = temp.0.join("source.csv");
        let template = temp.0.join("template.csv");
        fs::write(&source, "name\nAlice\n").unwrap();
        fs::write(&template, "full_name\n").unwrap();
        let result = dispatch(
            "data.filling.custom_map",
            &json!({
                "source_file": path_string(&source),
                "template_file": path_string(&template),
                "field_mapping": {"missing_template": "missing_source"},
            }),
        )
        .unwrap();
        assert_eq!(result["success"], false);
        assert_eq!(result["missing_sources"], json!(["missing_source"]));
        assert_eq!(result["missing_templates"], json!(["missing_template"]));
    }

    #[test]
    fn typed_requests_accept_camel_case_and_legacy_aliases() {
        let extract: FieldExtractRequest = parse_request(&json!({
            "sourceFile": " source.csv ",
            "selectedFields": [" name ", null, ""],
            "outputFile": " result.csv ",
            "delimiter": "\\t"
        }));
        assert_eq!(
            extract.source.source_path("missing").unwrap(),
            PathBuf::from("source.csv")
        );
        assert_eq!(extract.selected_fields(), &["name"]);
        assert_eq!(extract.output_file(), Some("result.csv"));
        assert_eq!(extract.source.separator(), Some('\t'));

        let auto: FillingAutoMapRequest = parse_request(&json!({
            "sourceFile": "source.csv",
            "templateFile": "template.xlsx",
            "customSeparator": "|",
            "similarityThreshold": 0.75
        }));
        assert_eq!(
            auto.template_path().unwrap(),
            PathBuf::from("template.xlsx")
        );
        assert_eq!(auto.source.separator(), Some('|'));
        assert_eq!(auto.similarity_threshold(), 0.75);

        let preview: FillingPreviewRequest = parse_request(&json!({
            "sourceFile": "source.csv",
            "templateFile": "template.xlsx",
            "fieldMapping": {"name": "source_name"},
            "previewRows": 23
        }));
        assert_eq!(preview.row_limit(), 23);
        assert_eq!(preview.mapping.mapping().unwrap()["name"], "source_name");

        let run: FillingRunRequest = parse_request(&json!({
            "sourceFile": "source.csv",
            "templateFile": "template.xlsx",
            "outputFile": "output.xlsx",
            "mapping": {"name": "source_name"}
        }));
        assert_eq!(run.output_path().unwrap(), PathBuf::from("output.xlsx"));
    }

    #[test]
    fn typed_request_empty_and_invalid_values_keep_command_errors() {
        assert_eq!(
            dispatch("data.field_extract.headers", &Value::Null).unwrap_err(),
            "请先选择数据文件"
        );
        assert_eq!(
            dispatch(
                "data.field_extract.run",
                &json!({"source_file": "source.csv", "selected_fields": []})
            )
            .unwrap_err(),
            "请选择要提取的字段"
        );

        let invalid: FillingCustomMapRequest = parse_request(&json!({
            "source_file": "source.csv",
            "template_file": "template.xlsx",
            "field_mapping": null,
            "mapping": {"name": "source_name"}
        }));
        assert_eq!(invalid.mapping.mapping().unwrap_err(), "请先设置字段映射");

        let malformed: FillingCustomMapRequest = parse_request(&json!({
            "field_mapping": "not-an-object"
        }));
        assert_eq!(malformed.mapping.mapping().unwrap_err(), "请先设置字段映射");
    }
}
