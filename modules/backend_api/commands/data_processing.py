#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Any, Dict

from modules.data_processing.data_filler import DataFiller
from modules.data_processing.field_extractor import FieldExtractor
from modules.data_processing.template_manager import TemplateManager

ROOT_DIR = Path(__file__).resolve().parents[3]

DATA_PROCESSING_COMMANDS = {
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
}


def is_data_processing_command(command: str | None) -> bool:
    return str(command or "") in DATA_PROCESSING_COMMANDS


def handle_data_processing_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if command == "data.templates.list":
        return _data_templates_list(payload)
    if command == "data.templates.get":
        return _data_templates_get(payload)
    if command == "data.templates.create":
        return _data_templates_create(payload)
    if command == "data.templates.update":
        return _data_templates_update(payload)
    if command == "data.templates.delete":
        return _data_templates_delete(payload)
    if command == "data.templates.import":
        return _data_templates_import(payload)
    if command == "data.templates.export":
        return _data_templates_export(payload)
    if command == "data.template.create":
        return _data_templates_create(payload)
    if command == "data.template.save":
        return _data_template_save(payload)
    if command == "data.filling.preview":
        return _data_filling_preview(payload)
    if command == "data.filling.run":
        return _data_filling_run(payload)
    if command == "data.filling.auto_map":
        return _data_filling_auto_map(payload)
    if command == "data.filling.custom_map":
        return _data_filling_custom_map(payload)
    if command == "data.field_extract.headers":
        return _data_field_extract_headers(payload)
    if command == "data.field_extract.run":
        return _data_field_extract_run(payload)

    raise ValueError(f"未知数据处理命令: {command}")


def _required_text(payload: Dict[str, Any], key: str, message: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(message)
    return value


def _optional_text(payload: Dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value or None


def _field_mapping(payload: Dict[str, Any], allow_empty: bool = False) -> Dict[str, str]:
    raw_mapping = payload.get("field_mapping") or payload.get("mapping") or {}
    if not isinstance(raw_mapping, dict):
        raise ValueError("字段映射必须是对象")

    mapping = {
        str(template_field).strip(): str(source_field).strip()
        for template_field, source_field in raw_mapping.items()
        if str(template_field).strip() and str(source_field).strip()
    }
    if not allow_empty and not mapping:
        raise ValueError("请先设置字段映射")
    return mapping


def _source_format(file_path: str | None) -> str:
    suffix = Path(file_path or "").suffix.lower().lstrip(".")
    if suffix in {"xlsx", "xls"}:
        return "excel"
    if suffix == "csv":
        return "csv"
    if suffix in {"txt", "tsv"}:
        return "txt"
    return suffix or "unknown"


def _resolve_existing_path(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if path.is_absolute() or path.exists():
        return str(path)

    candidates = [
        Path.cwd() / path,
        ROOT_DIR / path,
        ROOT_DIR / "Report_Template" / path,
        ROOT_DIR / "modules" / "data_processing" / "templates" / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(path)


def _template_manager() -> TemplateManager:
    return TemplateManager()


def _normalize_template_entry(key: str, template: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(template)
    item.setdefault("id", str(template.get("id") or key))
    item.setdefault("name", str(template.get("name") or key))
    item.setdefault("field_mapping", template.get("field_mapping") or template.get("mapping") or {})
    return item


def _template_key(manager: TemplateManager, template_id: str | None) -> str:
    identifier = str(template_id or "").strip()
    if not identifier:
        raise ValueError("请先选择模板")
    if identifier in manager.templates:
        return identifier

    for key, template in manager.templates.items():
        if str(template.get("id") or "") == identifier or str(template.get("name") or "") == identifier:
            return key

    raise ValueError(f"模板不存在: {identifier}")


def _mapping_rows(source_fields: list[str], template_fields: list[str],
                  field_mapping: Dict[str, str],
                  confidence_scores: Dict[str, Any] | None = None) -> list[Dict[str, Any]]:
    rows = []
    mapped_source_fields = set()
    confidence_scores = confidence_scores or {}

    for template_field in template_fields:
        source_field = field_mapping.get(template_field, "")
        if source_field:
            mapped_source_fields.add(source_field)
        rows.append({
            "source_field": source_field,
            "template_field": template_field,
            "status": "已映射" if source_field else "待映射",
            "confidence": confidence_scores.get(template_field),
        })

    for source_field in source_fields:
        if source_field not in mapped_source_fields:
            rows.append({
                "source_field": source_field,
                "template_field": "",
                "status": "待映射",
                "confidence": None,
            })

    return rows


def _data_field_extract_headers(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = str(payload.get("source_file") or "").strip()
    custom_separator = str(payload.get("custom_separator") or "").strip() or None
    if not source_file:
        raise ValueError("请先选择数据文件")

    return FieldExtractor().get_available_fields(source_file, custom_separator=custom_separator)


def _data_field_extract_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = str(payload.get("source_file") or "").strip()
    output_file = str(payload.get("output_file") or "").strip() or None
    custom_separator = str(payload.get("custom_separator") or "").strip() or None
    selected_fields = payload.get("selected_fields") or []

    if not source_file:
        raise ValueError("请先选择数据文件")
    if not isinstance(selected_fields, list) or not selected_fields:
        raise ValueError("请选择要提取的字段")

    return FieldExtractor().extract_fields(
        source_file=source_file,
        selected_fields=[str(field) for field in selected_fields],
        output_file=output_file,
        custom_separator=custom_separator,
    )


def _data_templates_list(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = payload or {}
    manager = _template_manager()
    filter_format = _optional_text(payload, "filter_format")
    templates = [
        _normalize_template_entry(key, template)
        for key, template in manager.templates.items()
        if not filter_format or template.get("source_format") == filter_format
    ]
    templates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {
        "templates": templates,
        "count": len(templates),
    }


def _data_templates_get(payload: Dict[str, Any]) -> Dict[str, Any]:
    manager = _template_manager()
    key = _template_key(manager, payload.get("template_id") or payload.get("id") or payload.get("name"))
    if bool(payload.get("mark_used", False)):
        manager.use_template(key)
    return {
        "template": _normalize_template_entry(key, manager.templates[key]),
    }


def _data_templates_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _required_text(payload, "name", "请输入模板名称")
    description = str(payload.get("description") or "")
    field_mapping = _field_mapping(payload, allow_empty=True)
    source_format = str(payload.get("source_format") or "excel")
    template_format = str(payload.get("template_format") or "excel")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    manager = _template_manager()
    result = manager.create_template(
        name=name,
        description=description,
        field_mapping=field_mapping,
        source_format=source_format,
        template_format=template_format,
        metadata=metadata,
    )

    if result.get("success"):
        key = _template_key(manager, result.get("template_id"))
        template = manager.templates[key]
        for extra_key in ("target_template", "delimiter"):
            if payload.get(extra_key) not in (None, ""):
                template[extra_key] = str(payload.get(extra_key))
        manager._save_templates()
        result["template"] = _normalize_template_entry(key, template)

    return result


def _data_templates_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    manager = _template_manager()
    key = _template_key(manager, payload.get("template_id") or payload.get("id") or payload.get("name"))

    new_name = str(payload.get("name") or "").strip()
    if new_name:
        for other_key, template in manager.templates.items():
            if other_key != key and str(template.get("name") or "") == new_name:
                return {"success": False, "message": f"模板名称 '{new_name}' 已存在"}

    updates: Dict[str, Any] = {}
    for field in ("name", "description", "source_format", "template_format"):
        if payload.get(field) is not None:
            updates[field] = payload.get(field)
    if payload.get("field_mapping") is not None or payload.get("mapping") is not None:
        updates["field_mapping"] = _field_mapping(payload, allow_empty=True)
    if isinstance(payload.get("metadata"), dict):
        updates["metadata"] = payload.get("metadata")

    result = manager.update_template(key, **updates)
    if result.get("success"):
        template = manager.templates[key]
        for extra_key in ("target_template", "delimiter"):
            if payload.get(extra_key) is not None:
                template[extra_key] = str(payload.get(extra_key) or "")
        manager._save_templates()
        result["template"] = _normalize_template_entry(key, template)

    return result


def _data_templates_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    manager = _template_manager()
    key = _template_key(manager, payload.get("template_id") or payload.get("id") or payload.get("name"))
    template = manager.templates[key]
    metadata = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
    if metadata.get("is_predefined") and not bool(payload.get("force", False)):
        return {"success": False, "message": "预定义模板不能删除"}
    return manager.delete_template(key)


def _data_templates_import(payload: Dict[str, Any]) -> Dict[str, Any]:
    import_path = _required_text(payload, "import_path", "请选择要导入的模板文件")
    overwrite = bool(payload.get("overwrite", False))
    return _template_manager().import_template(import_path, overwrite=overwrite)


def _data_templates_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    manager = _template_manager()
    key = _template_key(manager, payload.get("template_id") or payload.get("id") or payload.get("name"))
    export_path = _required_text(payload, "export_path", "请选择导出保存位置")
    return manager.export_template(key, export_path)


def _data_template_save(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("template_id") or payload.get("id"):
        return _data_templates_update(payload)
    return _data_templates_create(payload)


def _data_filling_auto_map(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = _resolve_existing_path(_required_text(payload, "source_file", "请先选择源文件"))
    template_file = _resolve_existing_path(_required_text(payload, "template_file", "请先选择目标模板文件"))
    custom_separator = _optional_text(payload, "custom_separator") or _optional_text(payload, "delimiter")
    threshold = float(payload.get("similarity_threshold") or 0.6)

    result = DataFiller().auto_map_fields(
        source_file=source_file,
        template_file=template_file,
        custom_separator=custom_separator,
        similarity_threshold=threshold,
    )

    source_fields_result = FieldExtractor().get_available_fields(source_file, custom_separator=custom_separator)
    template_fields_result = FieldExtractor().get_available_fields(template_file)
    if source_fields_result.get("success") and template_fields_result.get("success"):
        result["source_fields"] = source_fields_result.get("fields", [])
        result["template_fields"] = template_fields_result.get("fields", [])
        result["mapping_rows"] = _mapping_rows(
            result["source_fields"],
            result["template_fields"],
            result.get("auto_mapping") or {},
            result.get("confidence_scores") or {},
        )
    return result


def _data_filling_custom_map(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = _resolve_existing_path(_required_text(payload, "source_file", "请先选择源文件"))
    template_file = _resolve_existing_path(_required_text(payload, "template_file", "请先选择目标模板文件"))
    custom_separator = _optional_text(payload, "custom_separator") or _optional_text(payload, "delimiter")
    field_mapping = _field_mapping(payload)

    source_fields_result = FieldExtractor().get_available_fields(source_file, custom_separator=custom_separator)
    template_fields_result = FieldExtractor().get_available_fields(template_file)
    if not source_fields_result.get("success"):
        return {"success": False, "message": source_fields_result.get("message") or "加载源字段失败"}
    if not template_fields_result.get("success"):
        return {"success": False, "message": template_fields_result.get("message") or "加载模板字段失败"}

    source_fields = source_fields_result.get("fields", [])
    template_fields = template_fields_result.get("fields", [])
    missing_sources = [field for field in field_mapping.values() if field not in source_fields]
    missing_templates = [field for field in field_mapping if field not in template_fields]
    if missing_sources or missing_templates:
        return {
            "success": False,
            "message": "字段映射中存在无效字段",
            "missing_sources": missing_sources,
            "missing_templates": missing_templates,
        }

    return {
        "success": True,
        "message": f"已设置 {len(field_mapping)} 个字段映射",
        "field_mapping": field_mapping,
        "mapping_rows": _mapping_rows(source_fields, template_fields, field_mapping),
        "source_fields": source_fields,
        "template_fields": template_fields,
    }


def _data_filling_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = _resolve_existing_path(_required_text(payload, "source_file", "请先选择源文件"))
    template_file = _resolve_existing_path(_required_text(payload, "template_file", "请先选择目标模板文件"))
    custom_separator = _optional_text(payload, "custom_separator") or _optional_text(payload, "delimiter")
    field_mapping = _field_mapping(payload)

    return DataFiller().preview_filling(
        source_file=source_file,
        template_file=template_file,
        field_mapping=field_mapping,
        preview_rows=int(payload.get("preview_rows") or 10),
        custom_separator=custom_separator,
    )


def _data_filling_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = _resolve_existing_path(_required_text(payload, "source_file", "请先选择源文件"))
    template_file = _resolve_existing_path(_required_text(payload, "template_file", "请先选择目标模板文件"))
    output_file = _required_text(payload, "output_file", "请选择输出文件")
    custom_separator = _optional_text(payload, "custom_separator") or _optional_text(payload, "delimiter")
    field_mapping = _field_mapping(payload)

    result = DataFiller().fill_template(
        source_file=source_file,
        template_file=template_file,
        field_mapping=field_mapping,
        output_file=output_file,
        custom_separator=custom_separator,
    )
    result["operation_type"] = "fill_template"
    result["mapped_fields"] = len(field_mapping)
    result["source_format"] = _source_format(source_file)
    if result.get("success"):
        statistics = result.get("statistics") or {}
        result_info = statistics.get("result_info") if isinstance(statistics.get("result_info"), dict) else {}
        result["filled_count"] = result_info.get("rows", 0)
    return result
