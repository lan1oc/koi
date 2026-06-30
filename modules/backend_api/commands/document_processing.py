#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

from modules.Document_Processing.doc_pdf import (
    compute_output_path,
    convert_pdf_to_word,
    convert_with_word_com,
    list_document_files,
)
from modules.Document_Processing.pdf_extract import (
    build_compressed_output_path,
    build_default_output_path,
    compress_pdf,
    extract_pages,
    merge_pages_from_multiple_pdfs,
    parse_page_ranges,
)
from modules.Document_Processing.Report_Rewrite.notice_name_utils import (
    NOTICE_ISSUE_KEYWORDS,
    filename_has_notice_issue,
)

DOCUMENT_PROCESSING_COMMANDS = {
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
}

DEFAULT_TEMPLATE_SKIP_KEYWORDS = ["漏洞隐患处置文件模板", "app整改模板", "处置文件模板"]
SUPPORTED_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}
WORD_SUFFIXES = {".doc", ".docx"}
NOTICE_PDF_NAME_RULES = (
    lambda name: name.startswith("授权委托书"),
    lambda name: name.startswith("责令整改"),
    lambda name: name.startswith("关于"),
    lambda name: "通报" in name,
    lambda name: _notification_name(name),
)
NOTICE_BACKUP_MARKERS = (".clean_backup.", ".final_backup.", ".backup.", ".temp.")
NOTICE_VULNERABILITY_KEYWORDS = NOTICE_ISSUE_KEYWORDS


class _ProgressTee(io.TextIOBase):
    def __init__(self, original: Any, progress: "NoticeProgress"):
        self.original = original
        self.progress = progress
        self._buffer = ""

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8")

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        value = str(text)
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.progress.log(line.rstrip())
        if self.original is not None and self.original is not sys.stdout:
            try:
                self.original.write(value)
            except Exception:
                pass
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            self.progress.log(self._buffer.rstrip())
        self._buffer = ""
        if self.original is not None and self.original is not sys.stdout:
            try:
                self.original.flush()
            except Exception:
                pass


class NoticeProgress:
    def __init__(self, total: int = 0):
        self.lock = threading.RLock()
        self.logs: List[str] = []
        self.progress = 0
        self.message = "等待开始..."
        self.processed = 0
        self.total = max(0, int(total or 0))

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "progress": self.progress,
                "message": self.message,
                "logs": list(self.logs),
                "processed": self.processed,
                "total_reports": self.total,
            }

    def log(self, message: Any) -> None:
        text = str(message or "").strip("\r\n")
        if not text:
            return
        with self.lock:
            self.logs.append(text)
            self.message = text

    def extend(self, messages: Iterable[Any]) -> None:
        for message in messages:
            self.log(message)

    def set(self, progress: int | float | None = None, message: Any | None = None) -> None:
        with self.lock:
            if progress is not None:
                self.progress = max(0, min(100, int(round(float(progress)))))
            if message is not None:
                self.message = str(message)

    def set_total(self, total: int) -> None:
        with self.lock:
            self.total = max(0, int(total or 0))

    def set_processed(self, processed: int, total: int | None = None, message: Any | None = None) -> None:
        with self.lock:
            self.processed = max(0, int(processed or 0))
            if total is not None:
                self.total = max(0, int(total or 0))
            total_value = self.total
            if total_value > 0:
                self.progress = max(self.progress, min(98, 20 + int(self.processed / total_value * 75)))
            if message is not None:
                self.message = str(message)


class ProgressLogList(list):
    def __init__(self, progress: NoticeProgress | None = None):
        super().__init__()
        self.progress = progress

    def append(self, item: Any) -> None:
        super().append(str(item))
        if self.progress:
            self.progress.log(item)

    def extend(self, items: Iterable[Any]) -> None:
        for item in items:
            self.append(item)

    def extend_silent(self, items: Iterable[Any]) -> None:
        for item in items:
            super().append(str(item))


_NOTICE_TASKS: Dict[str, Dict[str, Any]] = {}
_NOTICE_TASK_LOCK = threading.RLock()


def is_document_processing_command(command: str | None) -> bool:
    return str(command or "") in DOCUMENT_PROCESSING_COMMANDS


def handle_document_processing_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if command == "doc.convert.run":
        return _doc_convert_run(payload)
    if command == "doc.pdf_extract.preview":
        return _doc_pdf_extract_preview(payload)
    if command == "doc.pdf_extract.run":
        return _doc_pdf_extract_run(payload)
    if command == "doc.pdf_extract.compress":
        return _doc_pdf_compress_run(payload)
    if command == "doc.notice.process":
        return _doc_notice_process(payload)
    if command == "doc.notice.process.start":
        return _doc_notice_process_start(payload)
    if command == "doc.notice.process.status":
        return _doc_notice_process_status(payload)
    if command == "doc.notice.counters.save":
        return _doc_notice_counters_save(payload)
    if command == "doc.notice.classify":
        return _doc_notice_classify(payload)
    if command == "doc.notice.convert_failed_pdf":
        return _doc_notice_convert_failed_pdf(payload)
    if command == "doc.open_path":
        return _doc_open_path(payload)

    raise ValueError(f"未知文档处理命令: {command}")


def _required_text(payload: Dict[str, Any], key: str, message: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(message)
    return value


def _optional_text(payload: Dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value or None


def _normalize_conversion_type(value: Any) -> str:
    text = str(value or "word_to_pdf").strip()
    if text in {"word_to_pdf", "Word转PDF", "word-pdf"}:
        return "word_to_pdf"
    if text in {"pdf_to_word", "PDF转Word", "pdf-word"}:
        return "pdf_to_word"
    raise ValueError(f"不支持的转换类型: {text}")


def _path_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def _keyword_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _failure_dicts(failures: Iterable[tuple[Path, str]]) -> List[Dict[str, str]]:
    return [{"file": str(src), "name": src.name, "reason": str(reason)} for src, reason in failures]


def _captured_lines(buffer: io.StringIO) -> List[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


def _store_captured_lines(logs: List[str], lines: Iterable[Any]) -> None:
    if isinstance(logs, ProgressLogList):
        logs.extend_silent(lines)
    else:
        logs.extend(str(line) for line in lines)


def _append_log(logs: List[str], message: Any, progress: NoticeProgress | None = None) -> None:
    text = str(message or "")
    logs.append(text)
    if progress:
        progress.log(text)


def _extend_logs(logs: List[str], messages: Iterable[Any], progress: NoticeProgress | None = None) -> None:
    for message in messages:
        _append_log(logs, message, progress)


def _run_with_progress_capture(func: Any, progress: NoticeProgress | None = None) -> tuple[Any, List[str]]:
    buffer = io.StringIO()
    stream: Any = _ProgressTee(buffer, progress) if progress else buffer
    with contextlib.redirect_stdout(stream):
        result = func()
    try:
        stream.flush()
    except Exception:
        pass
    return result, _captured_lines(buffer)


def _call_with_progress_capture(func: Any, progress: NoticeProgress | None = None) -> tuple[Any, List[str], BaseException | None]:
    buffer = io.StringIO()
    stream: Any = _ProgressTee(buffer, progress) if progress else buffer
    result = None
    error: BaseException | None = None
    with contextlib.redirect_stdout(stream):
        try:
            result = func()
        except BaseException as exc:
            error = exc
    try:
        stream.flush()
    except Exception:
        pass
    return result, _captured_lines(buffer), error


def _format_exception(error: BaseException | None) -> str:
    if error is None:
        return ""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def _parse_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_number_ranges(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_parts = [str(item).strip() for item in value]
    else:
        raw_parts = re.split(r"[,，;；\s]+", str(value))

    numbers: set[int] = set()
    for part in raw_parts:
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = _parse_int(start_text)
            end = _parse_int(end_text)
            if start is None or end is None:
                continue
            low, high = sorted((start, end))
            numbers.update(range(low, high + 1))
            continue
        number = _parse_int(part)
        if number is not None:
            numbers.add(number)
    return sorted(number for number in numbers if number > 0)


def _default_report_counters() -> Dict[str, Any]:
    return {
        "notification_number": 1,
        "rectification_number": 1,
        "unavailable_notification_numbers": [],
        "unavailable_rectification_numbers": [],
        "year": datetime.now().year,
        "last_updated": "",
    }


def _ensure_report_counters(config: Dict[str, Any]) -> Dict[str, Any]:
    counters = config.get("report_counters")
    if not isinstance(counters, dict):
        counters = {}
    normalized = _default_report_counters()
    normalized.update(counters)
    if not isinstance(normalized.get("unavailable_notification_numbers"), list):
        normalized["unavailable_notification_numbers"] = []
    if not isinstance(normalized.get("unavailable_rectification_numbers"), list):
        normalized["unavailable_rectification_numbers"] = []
    config["report_counters"] = normalized
    return normalized


def _merge_number_lists(existing: Any, incoming: Any) -> List[int]:
    return sorted(set(_parse_number_ranges(existing)) | set(_parse_number_ranges(incoming)))


def _clean_used_unavailable_numbers(counters: Dict[str, Any]) -> None:
    notification_next = _parse_int(counters.get("notification_number")) or 1
    rectification_next = _parse_int(counters.get("rectification_number")) or 1
    counters["unavailable_notification_numbers"] = [
        number for number in _parse_number_ranges(counters.get("unavailable_notification_numbers")) if number >= notification_next
    ]
    counters["unavailable_rectification_numbers"] = [
        number for number in _parse_number_ranges(counters.get("unavailable_rectification_numbers")) if number >= rectification_next
    ]


def _unavailable_counter_key(unavailable_type: Any) -> str:
    text = str(unavailable_type or "通报")
    if "责令" in text or "整改" in text:
        return "unavailable_rectification_numbers"
    return "unavailable_notification_numbers"


def _merge_unavailable_update(updates: Dict[str, Any], counters: Dict[str, Any], key: str, incoming: Any) -> None:
    numbers = _parse_number_ranges(incoming)
    if not numbers:
        return
    existing = updates.get(key, counters.get(key))
    updates[key] = _merge_number_lists(existing, numbers)


def _build_report_counter_updates(payload: Dict[str, Any], counters: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}

    if "notice_number" in payload:
        notice_number = _parse_int(payload.get("notice_number"))
        if notice_number is not None and notice_number > 0:
            updates["notification_number"] = notice_number

    if "rectification_number" in payload:
        rectification_number = _parse_int(payload.get("rectification_number"))
        if rectification_number is not None and rectification_number > 0:
            updates["rectification_number"] = rectification_number

    if "unavailable_numbers" in payload:
        _merge_unavailable_update(
            updates,
            counters,
            _unavailable_counter_key(payload.get("unavailable_type")),
            payload.get("unavailable_numbers"),
        )

    if "unavailable_notification_numbers" in payload:
        _merge_unavailable_update(
            updates,
            counters,
            "unavailable_notification_numbers",
            payload.get("unavailable_notification_numbers"),
        )

    if "unavailable_rectification_numbers" in payload:
        _merge_unavailable_update(
            updates,
            counters,
            "unavailable_rectification_numbers",
            payload.get("unavailable_rectification_numbers"),
        )

    if updates:
        updates.setdefault("year", counters.get("year") or datetime.now().year)
        updates["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return updates


def _save_report_counter_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    from modules.config.config_manager import ConfigManager

    manager = ConfigManager()
    config = manager.load_config()
    counters = _ensure_report_counters(config)
    updates = _build_report_counter_updates(payload, counters)

    if not updates:
        return {
            "success": True,
            "updated": False,
            "message": "没有可保存的编号配置修改",
            "report_counters": counters,
        }

    if not manager.save_config({"report_counters": updates}):
        return {
            "success": False,
            "updated": False,
            "message": "编号配置保存失败",
            "report_counters": counters,
        }

    refreshed = manager.load_config()
    refreshed_counters = _ensure_report_counters(refreshed)
    return {
        "success": True,
        "updated": True,
        "message": "编号配置已保存到 report_counters",
        "report_counters": refreshed_counters,
    }


def _apply_report_counter_payload(payload: Dict[str, Any], logs: List[str]) -> None:
    counter_keys = {
        "notice_number",
        "rectification_number",
        "unavailable_numbers",
        "unavailable_notification_numbers",
        "unavailable_rectification_numbers",
    }
    if not any(key in payload for key in counter_keys):
        return

    try:
        result = _save_report_counter_payload(payload)
        logs.append(str(result.get("message") or "编号配置保存完成"))
    except Exception as exc:
        logs.append(f"编号配置保存失败: {exc}")


def _doc_notice_counters_save(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = _save_report_counter_payload(payload)
        return {
            "success": bool(result.get("success")),
            "updated": bool(result.get("updated")),
            "message": str(result.get("message") or "编号配置保存完成"),
            "report_counters": result.get("report_counters") or {},
            "logs": [str(result.get("message") or "编号配置保存完成")],
        }
    except Exception as exc:
        return {
            "success": False,
            "updated": False,
            "message": f"编号配置保存失败: {exc}",
            "report_counters": {},
            "logs": [traceback.format_exc()],
        }


def _normalize_rewrite_result(raw_result: Any, report_file: Path) -> Dict[str, Any]:
    if isinstance(raw_result, dict):
        raw_result.setdefault("success", bool(raw_result.get("success")))
        raw_result.setdefault("output_file", None)
        raw_result.setdefault("backup_file", None)
        raw_result.setdefault("needs_manual_processing", False)
        raw_result.setdefault("skip_reason", None if raw_result.get("success") else "通报改写失败")
        return raw_result

    if raw_result is True:
        return {
            "success": True,
            "output_file": None,
            "backup_file": None,
            "needs_manual_processing": False,
            "skip_reason": None,
        }

    return {
        "success": False,
        "output_file": None,
        "backup_file": None,
        "needs_manual_processing": False,
        "skip_reason": "通报改写未返回详细结果，可能是模板缺少插入标记 * 或文档格式不符合要求",
    }


def _normalize_grouping_result(raw_result: Any) -> Dict[str, Any]:
    if isinstance(raw_result, dict):
        raw_result.setdefault("moved", 0)
        raw_result.setdefault("skipped_exist", 0)
        raw_result.setdefault("errors", 0)
        return raw_result
    if raw_result is True:
        return {"moved": 0, "skipped_exist": 0, "errors": 0, "log": ["分类命令已完成"]}
    return {"moved": 0, "skipped_exist": 0, "errors": 1, "log": ["分类命令未返回详细结果"]}


def _open_path_in_system(path: Path) -> tuple[bool, str | None]:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except Exception as exc:
        return False, str(exc)


def _doc_convert_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    conversion_type = _normalize_conversion_type(payload.get("conversion_type"))
    input_path = Path(_required_text(payload, "input_path", "请选择输入路径")).expanduser()
    output_dir = _optional_text(payload, "output_dir")
    output_root = Path(output_dir).expanduser() if output_dir else None
    recursive = bool(payload.get("recursive", True))
    overwrite = bool(payload.get("overwrite", True))
    skip_template = bool(payload.get("skip_template", True))
    skip_keywords = _keyword_list(payload.get("skip_keywords"))

    if not input_path.exists():
        return {"success": False, "message": f"输入路径不存在: {input_path}", "logs": []}
    if output_root is not None and output_root.exists() and not output_root.is_dir():
        return {"success": False, "message": f"输出路径不是目录: {output_root}", "logs": []}

    if conversion_type == "word_to_pdf":
        file_type = "word"
        expected_extensions = {".doc", ".docx"}
        file_label = "Word"
        if skip_template:
            skip_keywords = DEFAULT_TEMPLATE_SKIP_KEYWORDS + skip_keywords
    else:
        file_type = "pdf"
        expected_extensions = {".pdf"}
        file_label = "PDF"

    if input_path.is_file():
        if input_path.suffix.lower() not in expected_extensions:
            return {"success": False, "message": f"输入文件不是{file_label}文件: {input_path}", "logs": []}
        if skip_keywords and any(keyword in input_path.name for keyword in skip_keywords):
            return {"success": False, "message": f"输入文件命中跳过关键词: {input_path.name}", "logs": []}
        input_root = input_path.parent
        input_files = [input_path]
    else:
        input_root = input_path
        input_files = list_document_files(input_root, recursive=recursive, file_type=file_type, skip_keywords=skip_keywords)

    if not input_files:
        return {"success": False, "message": f"未找到可转换的{file_label}文件", "logs": []}

    file_map = [(src, compute_output_path(src, input_root, output_root, conversion_type)) for src in input_files]
    logs = [
        f"开始转换: {'Word转PDF' if conversion_type == 'word_to_pdf' else 'PDF转Word'}",
        f"找到 {len(file_map)} 个文件",
    ]
    if output_root:
        logs.append(f"输出目录: {output_root}")

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            if conversion_type == "word_to_pdf":
                converted, skipped, failures = convert_with_word_com(file_map, overwrite=overwrite)
            else:
                converted, skipped, failures = convert_pdf_to_word(file_map, overwrite=overwrite)
    except RuntimeError as exc:
        logs.extend(_captured_lines(buffer))
        return {
            "success": False,
            "message": str(exc),
            "converted": 0,
            "skipped": 0,
            "failures": [],
            "logs": logs,
            "output_files": [],
        }

    logs.extend(_captured_lines(buffer))
    for src, reason in failures:
        logs.append(f"失败: {src.name} -> {reason}")

    failure_paths = {src.resolve() for src, _ in failures}
    output_files = [
        str(dst)
        for src, dst in file_map
        if src.resolve() not in failure_paths and dst.exists()
    ]
    message = f"转换完成：成功 {converted}，跳过 {skipped}，失败 {len(failures)}"

    return {
        "success": len(failures) == 0,
        "message": message,
        "converted": converted,
        "skipped": skipped,
        "failures": _failure_dicts(failures),
        "logs": logs,
        "output_files": output_files,
        "total": len(file_map),
    }


def _render_pdf_page_thumbnails(pdf_file: Path, page_count: int, max_width: int, limit: int) -> Dict[int, str]:
    thumbnails: Dict[int, str] = {}
    if limit <= 0:
        return thumbnails
    try:
        import fitz  # type: ignore
    except Exception:
        return thumbnails

    try:
        with fitz.open(str(pdf_file)) as document:
            for page_index in range(min(page_count, limit, document.page_count)):
                page = document.load_page(page_index)
                rect = page.rect
                zoom = max_width / rect.width if rect.width else 0.2
                zoom = max(0.12, min(0.45, zoom))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                thumbnails[page_index + 1] = f"data:image/png;base64,{encoded}"
    except Exception:
        return thumbnails
    return thumbnails


def _read_pdf_page_info(pdf_file: Path, include_thumbnails: bool = False, thumbnail_limit: int = 80) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError("未安装 pypdf，请先安装 pypdf 后再使用 PDF 页面提取") from exc

    reader = PdfReader(str(pdf_file))
    page_count = len(reader.pages)
    thumbnails = _render_pdf_page_thumbnails(pdf_file, page_count, 180, thumbnail_limit) if include_thumbnails else {}
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        width = None
        height = None
        try:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
        except Exception:
            pass
        pages.append({
            "page_number": index,
            "label": f"第 {index} 页 / 共 {page_count} 页",
            "width": width,
            "height": height,
            "thumbnail": thumbnails.get(index),
        })
    return {
        "path": str(pdf_file),
        "name": pdf_file.name,
        "page_count": page_count,
        "pages": pages,
    }


def _doc_pdf_extract_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    pdf_files = _path_list(payload.get("pdf_files") or payload.get("pdf_file"))
    include_thumbnails = bool(payload.get("include_thumbnails", False))
    thumbnail_limit = int(payload.get("thumbnail_limit") or 80)
    if not pdf_files:
        return {"success": False, "message": "请先选择PDF文件", "files": []}

    files = []
    failures = []
    for item in pdf_files:
        pdf_file = Path(item).expanduser()
        if not pdf_file.exists() or pdf_file.suffix.lower() != ".pdf":
            failures.append({"file": str(pdf_file), "reason": "文件不存在或不是PDF"})
            continue
        try:
            files.append(_read_pdf_page_info(pdf_file, include_thumbnails=include_thumbnails, thumbnail_limit=thumbnail_limit))
        except Exception as exc:
            failures.append({"file": str(pdf_file), "reason": str(exc)})

    total_pages = sum(int(file_info.get("page_count") or 0) for file_info in files)
    success = bool(files) and not failures
    message = f"预览加载完成，共 {len(files)} 个文件、{total_pages} 页" if files else "预览加载失败"
    if failures and files:
        message = f"预览部分完成，{len(failures)} 个文件加载失败"

    return {
        "success": success,
        "message": message,
        "files": files,
        "failures": failures,
        "total_pages": total_pages,
    }


def _normalize_page_selection(selection: Dict[str, Any], index: int) -> Dict[str, Any]:
    file_path = str(selection.get("file_path") or selection.get("path") or "").strip()
    page_num = int(selection.get("page_num") or selection.get("page_number") or 0)
    order = int(selection.get("order") or index + 1)
    if not file_path or page_num < 1:
        raise ValueError("页面选择数据不完整")
    return {"file_path": file_path, "page_num": page_num, "order": order}


def _doc_pdf_extract_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    pdf_files = _path_list(payload.get("pdf_files") or payload.get("pdf_file"))
    page_ranges = str(payload.get("page_ranges") or "").strip()
    output_file = _optional_text(payload, "output_file")
    raw_selections = payload.get("page_selections") or []

    if not pdf_files:
        return {"success": False, "message": "请先选择PDF文件", "logs": []}
    if not isinstance(raw_selections, list):
        return {"success": False, "message": "页面选择数据格式不正确", "logs": []}

    page_selections = [_normalize_page_selection(selection, index) for index, selection in enumerate(raw_selections)]
    buffer = io.StringIO()

    if page_selections:
        output_path = Path(output_file).expanduser() if output_file else Path(pdf_files[0]).expanduser().parent / "merged_pages.pdf"
        logs = [f"开始合并 {len(page_selections)} 页"]
        try:
            with contextlib.redirect_stdout(buffer):
                merged_count, file_count = merge_pages_from_multiple_pdfs(page_selections, output_path)
        except RuntimeError as exc:
            logs.extend(_captured_lines(buffer))
            return {"success": False, "message": str(exc), "logs": logs, "output_file": str(output_path)}
        logs.extend(_captured_lines(buffer))
        message = f"已合并 {merged_count} 页（来自 {file_count} 个文件）"
        return {
            "success": True,
            "message": message,
            "output_file": str(output_path),
            "merged_count": merged_count,
            "file_count": file_count,
            "logs": logs,
        }

    if len(pdf_files) != 1:
        return {"success": False, "message": "多文件提取请先加载预览并选择页面", "logs": []}

    input_path = Path(pdf_files[0]).expanduser()
    if not input_path.exists() or input_path.suffix.lower() != ".pdf":
        return {"success": False, "message": f"PDF文件不存在或格式不正确: {input_path}", "logs": []}
    if not page_ranges:
        return {"success": False, "message": "请输入页码范围，或先加载预览选择页面", "logs": []}

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError("未安装 pypdf，请先安装 pypdf 后再使用 PDF 页面提取") from exc

    total_pages = len(PdfReader(str(input_path)).pages)
    page_numbers = parse_page_ranges(page_ranges, total_pages)
    output_path = Path(output_file).expanduser() if output_file else build_default_output_path(input_path, page_ranges)
    logs = [f"开始提取 {input_path.name} 的 {len(page_numbers)} 页"]
    try:
        with contextlib.redirect_stdout(buffer):
            extracted, total = extract_pages(input_path, output_path, page_numbers)
    except RuntimeError as exc:
        logs.extend(_captured_lines(buffer))
        return {"success": False, "message": str(exc), "logs": logs, "output_file": str(output_path)}

    logs.extend(_captured_lines(buffer))
    return {
        "success": True,
        "message": f"已从 {input_path.name} 提取 {extracted}/{total} 页",
        "output_file": str(output_path),
        "extracted": extracted,
        "total_pages": total,
        "logs": logs,
    }


def _doc_pdf_compress_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    pdf_files = _path_list(payload.get("pdf_files") or payload.get("pdf_file"))
    output_file = _optional_text(payload, "output_file")
    output_dir = _optional_text(payload, "output_dir")
    compression_mode = str(payload.get("compression_mode") or "standard").strip().lower()

    if not pdf_files:
        return {"success": False, "message": "请先选择PDF文件", "logs": [], "output_files": []}
    if compression_mode not in {"standard", "strong"}:
        return {"success": False, "message": f"不支持的压缩模式: {compression_mode}", "logs": [], "output_files": []}

    output_root = Path(output_dir).expanduser() if output_dir else None
    if output_root is not None and output_root.exists() and not output_root.is_dir():
        return {"success": False, "message": f"输出路径不是目录: {output_root}", "logs": [], "output_files": []}

    logs: List[str] = [f"开始压缩 {len(pdf_files)} 个PDF文件"]
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for index, item in enumerate(pdf_files, start=1):
        input_path = Path(item).expanduser()
        if not input_path.exists() or input_path.suffix.lower() != ".pdf":
            failures.append({"file": str(input_path), "reason": "文件不存在或不是PDF"})
            continue

        if output_file and len(pdf_files) == 1:
            output_path = Path(output_file).expanduser()
        else:
            output_path = build_compressed_output_path(input_path, output_root)

        logs.append(f"[{index}/{len(pdf_files)}] 压缩 {input_path.name}")
        try:
            result = compress_pdf(input_path, output_path, mode=compression_mode)
            results.append(result)
            saved_percent = result.get("saved_percent", 0)
            logs.append(
                f"完成: {result.get('original_size_text')} -> {result.get('compressed_size_text')} "
                f"(节省 {saved_percent}%)"
            )
            if float(saved_percent or 0) <= 0:
                logs.append("提示: 该文件已经比较紧凑，压缩后体积未明显降低")
        except Exception as exc:
            failures.append({"file": str(input_path), "reason": str(exc)})
            logs.append(f"失败: {input_path.name} -> {exc}")

    output_files = [str(result["output_file"]) for result in results if result.get("output_file")]
    success = bool(results) and not failures
    total_original = sum(int(result.get("original_size") or 0) for result in results)
    total_compressed = sum(int(result.get("compressed_size") or 0) for result in results)
    total_saved = total_original - total_compressed
    total_saved_percent = round(total_saved / total_original * 100, 2) if total_original else 0.0
    message = f"压缩完成：成功 {len(results)} 个，失败 {len(failures)} 个，整体节省 {total_saved_percent}%"
    if failures and results:
        message = f"压缩部分完成：成功 {len(results)} 个，失败 {len(failures)} 个"
    elif failures and not results:
        message = f"压缩失败：{len(failures)} 个文件未处理成功"

    return {
        "success": success,
        "message": message,
        "logs": logs,
        "output_file": output_files[0] if output_files else None,
        "output_files": output_files,
        "results": results,
        "failures": failures,
        "total_original_size": total_original,
        "total_compressed_size": total_compressed,
        "total_saved_bytes": total_saved,
        "total_saved_percent": total_saved_percent,
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _template_dir() -> Path:
    try:
        from modules.utils.resource_path import get_report_template_dir

        return get_report_template_dir()
    except Exception:
        return _project_root() / "Report_Template"


def _find_template(keyword: str) -> Path | None:
    template_root = _template_dir()
    if not template_root.exists():
        return None
    candidates = sorted(
        item
        for item in template_root.iterdir()
        if item.is_file() and item.suffix.lower() in {".doc", ".docx"}
    )
    return next((item for item in candidates if keyword in item.name), None)


def _safe_chdir(target_dir: Path):
    class _Chdir:
        def __enter__(self):
            self.previous = Path.cwd()
            os.chdir(target_dir)
            return self

        def __exit__(self, exc_type, exc, tb):
            os.chdir(self.previous)

    return _Chdir()


def _notification_name(filename: str) -> bool:
    return filename_has_notice_issue(filename)


def _count_notification_docs(directory: Path) -> int:
    count = 0
    for docx_file in directory.rglob("*.docx"):
        if docx_file.name.startswith(("~$", ".")):
            continue
        if _notification_name(docx_file.name):
            count += 1
    return count


def _is_supported_archive(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES


def _iter_supported_archives(directory: Path) -> List[Path]:
    return sorted(
        (item for item in directory.rglob("*") if _is_supported_archive(item)),
        key=lambda item: (len(item.relative_to(directory).parts), str(item).lower()),
    )


def _unique_child_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def _safe_archive_member_target(extract_dir: Path, member_name: str) -> Path:
    target = (extract_dir / member_name).resolve()
    root = extract_dir.resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"压缩包包含不安全路径: {member_name}")
    return target


def _extract_zip_archive(archive_path: Path, extract_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zip_ref:
        for info in zip_ref.infolist():
            target = _safe_archive_member_target(extract_dir, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target = _unique_child_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _extract_7z_archive(archive_path: Path, extract_dir: Path) -> None:
    try:
        import py7zr  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 py7zr 依赖，无法解压 7z。请重新安装依赖或重新打包应用。") from exc

    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        archive.extractall(path=extract_dir)


def _extract_rar_archive(archive_path: Path, extract_dir: Path) -> None:
    try:
        import rarfile  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 rarfile 依赖，无法解压 rar。请重新安装依赖或重新打包应用。") from exc

    try:
        with rarfile.RarFile(archive_path, "r") as archive:
            archive.extractall(extract_dir)
    except rarfile.RarCannotExec as exc:  # type: ignore[attr-defined]
        raise RuntimeError("当前应用没有可用的 RAR 解码器，无法直接解压 rar；请先转成 zip/7z 或把 rar 解码器随应用打包。") from exc


def _merge_extracted_tree(source_dir: Path, target_dir: Path) -> None:
    source_root = source_dir.resolve()
    target_root = target_dir.resolve()
    for child in sorted(source_dir.rglob("*"), key=lambda item: (len(item.relative_to(source_dir).parts), str(item).lower())):
        child_resolved = child.resolve()
        if child_resolved == source_root or source_root not in child_resolved.parents:
            raise RuntimeError(f"解压临时目录包含不安全路径: {child}")
        relative_path = child.relative_to(source_dir)
        target = (target_dir / relative_path).resolve()
        if target == target_root or target_root not in target.parents:
            raise RuntimeError(f"解压目标包含不安全路径: {relative_path}")
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target = _unique_child_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(child), str(target))


def _safe_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    return cleaned or "未识别企业"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.name} ({index})")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}_{int(time.time())}")


def _normalize_company_from_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from modules.Document_Processing.Report_Rewrite import group_folders as gf

        company_name = gf.normalize_company(text)
    except Exception:
        company_name = None
    return company_name.strip() if company_name else None


def _detect_company_name_for_extract(archive_path: Path, extract_dir: Path) -> tuple[str | None, List[str]]:
    candidates: List[str] = []

    def add_candidate(value: Any) -> None:
        company_name = _normalize_company_from_text(value)
        if company_name and company_name not in candidates:
            candidates.append(company_name)

    add_candidate(archive_path.stem)
    for child in sorted(extract_dir.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(("~$", ".")):
            continue
        add_candidate(child.name)

    for doc_file in sorted(extract_dir.rglob("*.docx"), key=lambda item: str(item).lower()):
        if doc_file.name.startswith(("~$", ".")):
            continue
        if any(keyword in doc_file.name for keyword in ["模板", "授权委托书", "责令整改", "处置"]):
            continue
        add_candidate(doc_file.name)

    if len(candidates) == 1:
        return candidates[0], candidates
    if candidates:
        archive_company = _normalize_company_from_text(archive_path.stem)
        if archive_company in candidates:
            return archive_company, candidates
    return None, candidates


def _rename_extracted_dir_by_company(archive_path: Path, extract_dir: Path, logs: List[str]) -> Path:
    company_name, candidates = _detect_company_name_for_extract(archive_path, extract_dir)
    if not company_name:
        if candidates:
            logs.append(f"解压目录企业名不唯一，保留原目录名: {', '.join(candidates)}")
        else:
            logs.append("未识别到企业名，保留原解压目录名")
        return extract_dir

    target_dir = extract_dir.parent / _safe_folder_name(company_name)
    if target_dir.resolve() == extract_dir.resolve():
        logs.append(f"解压目录已按企业名命名: {target_dir.name}")
        return extract_dir

    target_dir = _unique_path(target_dir)
    try:
        shutil.move(str(extract_dir), str(target_dir))
        logs.append(f"解压目录已按企业名命名: {target_dir}")
        return target_dir
    except Exception as exc:
        logs.append(f"按企业名重命名解压目录失败，保留原目录: {exc}")
        return extract_dir


def _delete_archive_file(archive_path: Path, logs: List[str]) -> None:
    try:
        if archive_path.exists():
            archive_path.unlink()
            logs.append(f"已删除压缩包: {archive_path.name}")
    except Exception as exc:
        logs.append(f"删除压缩包失败 {archive_path.name}: {exc}")


def _extract_archive(archive_path: Path, logs: List[str]) -> tuple[Path | None, bool]:
    suffix = archive_path.suffix.lower()
    if suffix not in SUPPORTED_ARCHIVE_SUFFIXES:
        logs.append(f"暂不支持 {archive_path.suffix} 格式，请先手动解压")
        return None, False

    extract_dir = archive_path.parent
    logs.append(f"解压到压缩包所在目录: {extract_dir}")
    if suffix == ".zip":
        _extract_zip_archive(archive_path, extract_dir)
    elif suffix in {".7z", ".rar"}:
        temp_dir = archive_path.parent / f".koi_extract_{archive_path.stem}_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=False)
        try:
            if suffix == ".7z":
                _extract_7z_archive(archive_path, temp_dir)
            else:
                _extract_rar_archive(archive_path, temp_dir)
            _merge_extracted_tree(temp_dir, extract_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    logs.append(f"解压完成，已保留原压缩包: {archive_path.name}")
    return extract_dir, True


def _extract_archives_before_notice_processing(root_dir: Path, logs: List[str], progress: NoticeProgress | None = None) -> List[Dict[str, str]]:
    failures: List[Dict[str, str]] = []
    processed: set[Path] = set()

    while True:
        archives = [item for item in _iter_supported_archives(root_dir) if item.resolve() not in processed]
        if not archives:
            return failures

        logs.append(f"预解压压缩包: 发现 {len(archives)} 个")
        if progress:
            progress.set(message=f"预解压压缩包: 发现 {len(archives)} 个")

        for archive_path in archives:
            processed.add(archive_path.resolve())
            logs.append(f"预解压: {archive_path}")
            try:
                extract_dir, _ = _extract_archive(archive_path, logs)
                if extract_dir and progress:
                    progress.set(message=f"已解压: {archive_path.name}")
            except Exception as exc:
                failures.append({"file": str(archive_path), "reason": str(exc)})
                logs.append(f"解压失败 {archive_path.name}: {exc}")


def _latest_rectification_doc(directory: Path) -> Path | None:
    candidates = [
        path
        for suffix in WORD_SUFFIXES
        for path in directory.glob(f"责令整改*{suffix}")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_work_path(work_dir: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = work_dir / path
    return path.resolve()


def _manual_path_values(files: Iterable[Dict[str, Any]]) -> set[Path]:
    paths: set[Path] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        for key in ("file", "output_file", "backup_file"):
            path = _resolve_work_path(Path.cwd(), item.get(key))
            if path:
                paths.add(path)
    return paths


def _copy_template_for_manual_edit(template_file: Path | None, work_dir: Path, output_name: str, logs: List[str], reason: str) -> Path | None:
    if template_file is None:
        logs.append(f"{reason}，且未找到可保留的模板")
        return None

    source = Path(template_file)
    if not source.exists():
        logs.append(f"{reason}，模板文件不存在: {source}")
        return None

    suffix = source.suffix if source.suffix.lower() in WORD_SUFFIXES else ".docx"
    target_name = Path(output_name).with_suffix(suffix).name
    target = work_dir / target_name
    if target.exists():
        logs.append(f"{reason}，已保留现有待编辑文件: {target.name}")
        return target.resolve()

    try:
        shutil.copy2(source, target)
        logs.append(f"{reason}，已保留模板供手动编辑: {target}")
        return target.resolve()
    except Exception as exc:
        logs.append(f"保留模板失败 {source.name}: {exc}")
        return None


def _rectification_manual_reason(doc_path: Path, expected_company: str | None = None, expected_vuln: str | None = None) -> str | None:
    try:
        from docx import Document

        doc = Document(str(doc_path))
        full_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    except Exception as exc:
        return f"无法检查责令整改文档内容: {exc}"

    issues: List[str] = []
    placeholder_markers = ("【公司名】", "【漏洞类型】", "{公司名}", "{漏洞类型}", "公司名】", "漏洞类型】")
    if any(marker in full_text for marker in placeholder_markers):
        issues.append("仍包含公司名或漏洞类型占位符")

    if expected_company and expected_company not in full_text:
        issues.append("未写入企业名")

    if expected_vuln:
        vuln_needles = [expected_vuln]
        if expected_vuln.startswith("存在"):
            vuln_needles.append(expected_vuln[2:])
        else:
            vuln_needles.append(f"存在{expected_vuln}")
        if not any(needle and needle in full_text for needle in vuln_needles):
            issues.append("未写入漏洞类型")

    return "；".join(dict.fromkeys(issues)) if issues else None


def _is_notice_pdf_candidate(path: Path) -> bool:
    if path.name.startswith(("~$", ".")):
        return False
    if path.suffix.lower() not in WORD_SUFFIXES:
        return False
    if any(part == "Report_Template" for part in path.parts):
        return False
    if any(keyword in path.name for keyword in DEFAULT_TEMPLATE_SKIP_KEYWORDS) or "模板" in path.name:
        return False
    if path.name[0].isdigit():
        return False
    if any(marker in path.name for marker in NOTICE_BACKUP_MARKERS):
        return False
    return any(rule(path.name) for rule in NOTICE_PDF_NAME_RULES)


def _is_explicit_manual_pdf_candidate(path: Path) -> bool:
    if path.name.startswith(("~$", ".")):
        return False
    if path.suffix.lower() not in WORD_SUFFIXES:
        return False
    if any(part == "Report_Template" for part in path.parts):
        return False
    if any(keyword in path.name for keyword in DEFAULT_TEMPLATE_SKIP_KEYWORDS) or "模板" in path.name:
        return False
    return True


def _collect_notice_pdf_candidates(target_path: Path, failed_files: Any, logs: List[str]) -> List[Path]:
    candidates: set[Path] = set()

    if isinstance(failed_files, list):
        for item in failed_files:
            values: List[Any]
            if isinstance(item, dict):
                values = [item.get("output_file"), item.get("backup_file"), item.get("file")]
            else:
                values = [item]
            for value in values:
                path = _resolve_work_path(target_path, value)
                if path and path.exists() and _is_explicit_manual_pdf_candidate(path):
                    candidates.add(path)

    for file_path in target_path.rglob("*"):
        if file_path.is_file() and _is_notice_pdf_candidate(file_path):
            candidates.add(file_path.resolve())

    sorted_candidates = sorted(candidates, key=lambda item: str(item).lower())
    if sorted_candidates:
        logs.append(f"递归找到 {len(sorted_candidates)} 个可转换Word文件")
    return sorted_candidates


def _convert_generated_docs_to_pdf(
    work_dir: Path,
    logs: List[str],
    progress: NoticeProgress | None = None,
    skip_paths: Iterable[Path] | None = None,
) -> Dict[str, Any]:
    skip_resolved = {Path(path).resolve() for path in (skip_paths or [])}
    docx_files = []
    for pattern in ("授权委托书*.docx", "责令整改*.docx"):
        for file_path in work_dir.glob(pattern):
            if file_path.name.startswith("~$"):
                continue
            if any(marker in file_path.name for marker in (".clean_backup.docx", ".final_backup.docx", ".backup.docx")):
                continue
            if file_path.resolve() in skip_resolved:
                logs.append(f"跳过需手动处理的Word文件: {file_path.name}")
                continue
            docx_files.append(file_path)

    if not docx_files:
        logs.append("当前目录未找到需要转换的授权委托书或责令整改通知书")
        return {"converted": 0, "skipped": 0, "failures": [], "output_files": []}

    file_map = [(src, src.with_suffix(".pdf")) for src in docx_files]
    raw_result, captured, error = _call_with_progress_capture(
        lambda: convert_with_word_com(file_map, overwrite=True),
        progress,
    )
    if error is not None:
        raise error
    converted, skipped, failures = raw_result
    _store_captured_lines(logs, captured)

    failed_files = {src.resolve() for src, _ in failures}
    output_files = []
    for src, pdf_path in file_map:
        if src.resolve() in failed_files or not pdf_path.exists():
            continue
        output_files.append(str(pdf_path))
        try:
            src.unlink()
            logs.append(f"已删除原Word文件: {src.name}")
        except Exception as exc:
            logs.append(f"删除Word文件失败 {src.name}: {exc}")

    for src, reason in failures:
        logs.append(f"转换失败 {src.name}: {reason}")

    return {
        "converted": converted,
        "skipped": skipped,
        "failures": _failure_dicts(failures),
        "output_files": output_files,
    }


def _process_report_batch(
    report_files: Sequence[Path],
    company_name: str,
    template_paths: Dict[str, Path | None],
    soe_companies: set[str],
    logs: List[str],
    progress: NoticeProgress | None = None,
    progress_base: float = 20,
    progress_span: float = 75,
    processed_before: int = 0,
    total_reports: int = 0,
) -> Dict[str, Any]:
    generated_files: List[str] = []
    manual_files: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    pdf_outputs: List[str] = []

    if not report_files:
        return {"generated_files": generated_files, "manual_files": manual_files, "failures": failures, "pdf_outputs": pdf_outputs}

    work_dir = report_files[0].parent
    logs.append("=" * 80)
    logs.append(f"处理企业: {company_name} (共 {len(report_files)} 个文档)")
    if progress:
        progress.set(progress_base, f"处理企业: {company_name}")

    def update_step(step_percent: float, message: str) -> None:
        if not progress:
            return
        total_value = total_reports or progress.total or len(report_files)
        batch_ratio = (processed_before / total_value) if total_value else 0
        batch_span = (len(report_files) / total_value * progress_span) if total_value else progress_span
        progress.set(progress_base + batch_ratio * progress_span + batch_span * step_percent / 100, message)

    with _safe_chdir(work_dir):
        try:
            from modules.Document_Processing.Report_Rewrite.edit_authorization import edit_authorization
            from modules.Document_Processing.Report_Rewrite.edit_disposal import process_disposal
            from modules.Document_Processing.Report_Rewrite.edit_rectification import edit_rectification, extract_info_from_filename
            from modules.Document_Processing.Report_Rewrite.rewrite_report import rewrite_report
        except Exception as exc:
            failures.append({"file": str(work_dir), "reason": f"导入通报处理模块失败: {exc}"})
            logs.append(f"导入通报处理模块失败: {exc}")
            return {"generated_files": generated_files, "manual_files": manual_files, "failures": failures, "pdf_outputs": pdf_outputs}

        collected_vulns: List[str] = []
        logs.append("步骤1/5: 通报改写")
        update_step(0, "步骤1/5: 通报改写")
        for report_file in report_files:
            logs.append(f"改写文档: {report_file.name}")
            _, vuln = extract_info_from_filename(str(report_file))
            if vuln:
                collected_vulns.append(vuln)

            raw_result, captured, error = _call_with_progress_capture(
                lambda: rewrite_report(str(report_file), template_file=str(template_paths["rewrite"]) if template_paths["rewrite"] else None, start_para=1),
                progress,
            )
            if error is None:
                result = _normalize_rewrite_result(raw_result, report_file)
            else:
                result = {
                    "success": False,
                    "output_file": None,
                    "backup_file": None,
                    "needs_manual_processing": False,
                    "skip_reason": f"执行错误: {error}",
                }
                logs.append(_format_exception(error))
            _store_captured_lines(logs, captured)

            output_path = _resolve_work_path(work_dir, result.get("output_file"))
            backup_path = _resolve_work_path(work_dir, result.get("backup_file"))
            if output_path and output_path.exists():
                generated_files.append(str(output_path))
            if backup_path and backup_path.exists():
                generated_files.append(str(backup_path))

            if not result.get("success"):
                reason = str(result.get("skip_reason") or "通报改写失败")
                fallback_path = output_path if output_path and output_path.exists() else None
                if fallback_path is None:
                    fallback_name = re.sub(r"^\d+", "", report_file.name) or report_file.name
                    fallback_path = _copy_template_for_manual_edit(
                        template_paths["rewrite"],
                        work_dir,
                        fallback_name,
                        logs,
                        f"通报改写失败: {report_file.name}",
                    )
                    if fallback_path:
                        generated_files.append(str(fallback_path))
                failures.append({"file": str(report_file), "reason": reason})
                manual_files.append({
                    "file": str(report_file.resolve()),
                    "reason": reason,
                    "backup_file": str(backup_path) if backup_path and backup_path.exists() else None,
                    "output_file": str(fallback_path) if fallback_path and fallback_path.exists() else None,
                })
                logs.append(f"通报改写失败: {report_file.name} -> {reason}")
            elif result.get("needs_manual_processing"):
                manual_output = output_path if output_path and output_path.exists() else backup_path
                manual_files.append({
                    "file": str(report_file.resolve()),
                    "reason": result.get("skip_reason") or "需要手动处理",
                    "backup_file": str(backup_path) if backup_path and backup_path.exists() else None,
                    "output_file": str(manual_output) if manual_output and manual_output.exists() else None,
                })
                logs.append(f"需要手动处理: {report_file.name} -> {result.get('skip_reason')}")
        update_step(20, "步骤1/5完成")

        time.sleep(0.5)
        target_report = report_files[0]
        override_name = f"{company_name}存在多个漏洞" if len(report_files) > 1 else None

        logs.append("步骤2/5: 生成授权委托书")
        update_step(20, "步骤2/5: 生成授权委托书")
        ok, captured, error = _call_with_progress_capture(
            lambda: edit_authorization(
                    str(target_report),
                    template_file=str(template_paths["authorization"]) if template_paths["authorization"] else None,
                    override_name=override_name,
                ),
            progress,
        )
        if error is not None:
            ok = False
            logs.append(_format_exception(error))
            failures.append({"file": str(target_report), "reason": f"授权委托书生成异常: {error}"})
        _store_captured_lines(logs, captured)
        if not ok:
            failures.append({"file": str(target_report), "reason": "授权委托书生成失败"})
        generated_files.extend(str(path.resolve()) for path in work_dir.glob("授权委托书*.docx"))
        update_step(40, "步骤2/5完成")

        if company_name in soe_companies:
            logs.append(f"检测到国企: {company_name}，跳过责令整改通知书")
        else:
            logs.append("步骤3/5: 生成责令整改通知书")
            update_step(40, "步骤3/5: 生成责令整改通知书")
            combined_vulns = None
            if len(report_files) > 1 and collected_vulns:
                combined_vulns = "、".join(sorted(set(collected_vulns)))
                if not combined_vulns.endswith(("漏洞", "风险")):
                    combined_vulns += "漏洞"
            elif collected_vulns:
                combined_vulns = collected_vulns[0]

            rectification_started_at = time.time()
            ok, captured, error = _call_with_progress_capture(
                lambda: edit_rectification(
                        str(target_report),
                        template_file=str(template_paths["rectification"]) if template_paths["rectification"] else None,
                        company_name=company_name,
                        vuln_type=combined_vulns,
                    ),
                progress,
            )
            if error is not None:
                ok = False
                logs.append(_format_exception(error))
                failures.append({"file": str(target_report), "reason": f"责令整改通知书生成异常: {error}"})
            _store_captured_lines(logs, captured)
            if not ok:
                reason = "责令整改通知书生成失败"
                failures.append({"file": str(target_report), "reason": reason})
                fallback_rect = _copy_template_for_manual_edit(
                    template_paths["rectification"],
                    work_dir,
                    "责令整改通知书.docx",
                    logs,
                    reason,
                )
                if fallback_rect:
                    generated_files.append(str(fallback_rect))
                    manual_files.append({
                        "file": str(fallback_rect),
                        "reason": "责令整改通知书生成失败，请基于该模板手动补齐后再转换PDF",
                        "output_file": str(fallback_rect),
                    })
            latest_rect = _latest_rectification_doc(work_dir)
            if latest_rect:
                generated_files.append(str(latest_rect.resolve()))
                manual_reason = _rectification_manual_reason(latest_rect, company_name, combined_vulns)
                if manual_reason and latest_rect.stat().st_mtime >= rectification_started_at - 1:
                    latest_rect_resolved = str(latest_rect.resolve())
                    if not any(item.get("output_file") == latest_rect_resolved or item.get("file") == latest_rect_resolved for item in manual_files):
                        manual_files.append({
                            "file": latest_rect_resolved,
                            "reason": f"责令整改文档需要手动校正: {manual_reason}",
                            "output_file": latest_rect_resolved,
                        })
                    logs.append(f"责令整改文档需要手动校正: {manual_reason}")
        update_step(60, "步骤3/5完成")

        logs.append("步骤4/5: 处理处置文件")
        update_step(60, "步骤4/5: 处理处置文件")
        if not list(work_dir.glob("*处置*.docx")) and not list(work_dir.glob("*处置*.pdf")):
            if template_paths["disposal"]:
                ok, captured, error = _call_with_progress_capture(
                    lambda: process_disposal(str(template_paths["disposal"]), target_directory=work_dir),
                    progress,
                )
                if error is not None:
                    ok = False
                    logs.append(_format_exception(error))
                    failures.append({"file": str(work_dir), "reason": f"处置文件处理异常: {error}"})
                _store_captured_lines(logs, captured)
                if not ok:
                    failures.append({"file": str(work_dir), "reason": "处置文件处理失败"})
            else:
                logs.append("未找到处置文件模板，跳过")
        else:
            logs.append("处置文件已存在，跳过")
        generated_files.extend(str(path.resolve()) for path in work_dir.glob("*处置*.docx"))
        update_step(80, "步骤4/5完成")

        logs.append("步骤5/5: 转换授权委托书与责令整改通知书为PDF")
        update_step(80, "步骤5/5: 转换授权委托书与责令整改通知书为PDF")
        pdf_result = _convert_generated_docs_to_pdf(work_dir, logs, progress, skip_paths=_manual_path_values(manual_files))
        pdf_outputs.extend(pdf_result["output_files"])
        failures.extend(pdf_result["failures"])
        update_step(95, "步骤5/5完成")

    return {
        "generated_files": sorted(set(generated_files)),
        "manual_files": manual_files,
        "failures": failures,
        "pdf_outputs": pdf_outputs,
    }


def _discover_report_files(directory: Path, logs: List[str]) -> List[Path]:
    report_files: List[Path] = []
    for item in list(directory.glob("*.docx")):
        if item.name.startswith("~$"):
            continue
        if any(keyword in item.name for keyword in ["模板", "授权委托书", "责令整改", "处置"]):
            continue
        if not _notification_name(item.name):
            continue
        if not item.name[0].isdigit():
            new_name = f"{str(int(time.time() * 1000))[-10:]}{item.name}"
            new_path = item.parent / new_name
            try:
                item.rename(new_path)
                logs.append(f"重命名原始通报: {item.name} -> {new_name}")
                item = new_path
            except Exception as exc:
                logs.append(f"重命名失败 {item.name}: {exc}")
                continue
        report_files.append(item)
    return report_files


def _process_notice_directory(
    directory: Path,
    template_paths: Dict[str, Path | None],
    soe_companies: set[str],
    logs: List[str],
    processed_dirs: set[Path] | None = None,
    progress: NoticeProgress | None = None,
    total_reports: int = 0,
    processed_offset: int = 0,
) -> Dict[str, Any]:
    processed_dirs = processed_dirs or set()
    directory = directory.resolve()
    if directory in processed_dirs:
        return {"processed": 0, "generated_files": [], "manual_files": [], "failures": [], "pdf_outputs": []}
    processed_dirs.add(directory)

    processed = 0
    generated_files: List[str] = []
    manual_files: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    pdf_outputs: List[str] = []

    logs.append(f"扫描目录: {directory}")
    if progress:
        progress.set(message=f"扫描目录: {directory}")
    report_files = _discover_report_files(directory, logs)
    if report_files:
        company_groups: Dict[str, List[Path]] = {}
        for report_file in report_files:
            company_name = report_file.parent.name
            if company_name == report_file.parent.parent.name:
                try:
                    from modules.Document_Processing.Report_Rewrite import group_folders as gf

                    company_name = gf.normalize_company(report_file.name) or company_name
                except Exception:
                    pass
            company_groups.setdefault(company_name, []).append(report_file)

        for company_name, files in company_groups.items():
            result = _process_report_batch(
                files,
                company_name,
                template_paths,
                soe_companies,
                logs,
                progress=progress,
                processed_before=processed_offset + processed,
                total_reports=total_reports,
            )
            processed += len(files)
            if progress:
                progress.set_processed(processed_offset + processed, total_reports, f"已完成 {processed_offset + processed}/{total_reports} 个文档")
            generated_files.extend(result["generated_files"])
            manual_files.extend(result["manual_files"])
            failures.extend(result["failures"])
            pdf_outputs.extend(result["pdf_outputs"])
    else:
        logs.append(f"未在 {directory.name} 找到符合规则的通报文档")

    for subdir in [item for item in directory.iterdir() if item.is_dir() and not item.name.startswith(".")]:
        result = _process_notice_directory(
            subdir,
            template_paths,
            soe_companies,
            logs,
            processed_dirs,
            progress=progress,
            total_reports=total_reports,
            processed_offset=processed_offset + processed,
        )
        processed += result["processed"]
        if progress:
            progress.set_processed(processed_offset + processed, total_reports, f"已完成 {processed_offset + processed}/{total_reports} 个文档")
        generated_files.extend(result["generated_files"])
        manual_files.extend(result["manual_files"])
        failures.extend(result["failures"])
        pdf_outputs.extend(result["pdf_outputs"])

    return {
        "processed": processed,
        "generated_files": sorted(set(generated_files)),
        "manual_files": manual_files,
        "failures": failures,
        "pdf_outputs": sorted(set(pdf_outputs)),
    }


def _doc_notice_classify(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_path = Path(_required_text(payload, "target_path", "请选择要分类的目录")).expanduser()
    if not target_path.exists() or not target_path.is_dir():
        return {"success": False, "message": f"目标目录不存在或不是目录: {target_path}", "logs": []}

    logs: List[str] = []
    buffer = io.StringIO()
    try:
        from modules.Document_Processing.Report_Rewrite import group_folders as gf

        with contextlib.redirect_stdout(buffer):
            raw_result = gf.run_grouping(
                str(target_path),
                entries=str(payload.get("entries") or "both"),
                pattern=str(payload.get("pattern") or "exact"),
                groups_source=str(payload.get("groups_source") or "db"),
            )
        result = _normalize_grouping_result(raw_result)
    except Exception as exc:
        logs.extend(_captured_lines(buffer))
        logs.append(traceback.format_exc())
        return {"success": False, "message": f"分类失败: {exc}", "logs": logs}

    logs.extend(_captured_lines(buffer))
    logs.extend(str(line) for line in (result.get("log") or []) if str(line).strip())
    message = f"分类完成：移动 {result.get('moved', 0)} 个，跳过 {result.get('skipped_exist', 0)} 个，错误 {result.get('errors', 0)} 个"
    return {
        "success": result.get("errors", 0) == 0,
        "message": message,
        "logs": logs,
        "result": result,
    }


def _doc_notice_process(payload: Dict[str, Any], progress: NoticeProgress | None = None) -> Dict[str, Any]:
    target_path = Path(_required_text(payload, "target_path", "请选择文件夹或压缩包")).expanduser()
    auto_group = bool(payload.get("auto_group", True))
    logs: List[str] = ProgressLogList(progress) if progress else []

    if not target_path.exists():
        return {"success": False, "message": f"目标路径不存在: {target_path}", "logs": []}

    if progress:
        progress.set(3, "正在准备通报处理任务...")
    _apply_report_counter_payload(payload, logs)

    template_paths = {
        "rewrite": _find_template("通报模板"),
        "authorization": _find_template("授权委托书"),
        "rectification": _find_template("责令整改"),
        "disposal": _find_template("处置"),
    }
    for key, value in template_paths.items():
        logs.append(f"模板 {key}: {value if value else '未找到'}")
    if progress:
        progress.set(8, "模板检查完成")

    try:
        from modules.Document_Processing.Report_Rewrite import group_folders as gf

        soe_companies = gf.get_soe_companies()
    except Exception:
        soe_companies = set()

    if target_path.is_file():
        logs.append(f"检测到压缩包: {target_path.name}")
        if progress:
            progress.set(10, f"正在解压: {target_path.name}")
        try:
            target_path, _ = _extract_archive(target_path, logs)
            if target_path is None:
                return {"success": False, "message": "解压失败", "logs": logs}
        except Exception as exc:
            logs.append(traceback.format_exc())
            return {"success": False, "message": f"解压失败: {exc}", "logs": logs}

    if not target_path.is_dir():
        return {"success": False, "message": "只支持文件夹或ZIP压缩包", "logs": logs}

    if progress:
        progress.set(11, "正在预解压目录中的压缩包...")
    archive_failures = _extract_archives_before_notice_processing(target_path, logs, progress)

    if auto_group:
        logs.append("执行自动分类")
        if progress:
            progress.set(12, "执行自动分类")
        classify_result = _doc_notice_classify({"target_path": str(target_path)})
        logs.extend(classify_result.get("logs") or [])
        logs.append(classify_result.get("message") or "")

    total_reports = _count_notification_docs(target_path)
    logs.append(f"共发现 {total_reports} 个通报文档")
    if progress:
        progress.set_total(total_reports)
        progress.set(20 if total_reports else 95, f"共发现 {total_reports} 个通报文档")
    result = _process_notice_directory(
        target_path,
        template_paths,
        soe_companies,
        logs,
        progress=progress,
        total_reports=total_reports,
    )
    if archive_failures:
        result["failures"].extend(archive_failures)

    message = f"处理完成：处理 {result['processed']} 个文档，失败 {len(result['failures'])} 个，需手动处理 {len(result['manual_files'])} 个"
    if progress:
        progress.set(100, message)
    return {
        "success": len(result["failures"]) == 0,
        "message": message,
        "target_path": str(target_path),
        "total_reports": total_reports,
        "processed": result["processed"],
        "generated_files": result["generated_files"],
        "manual_files": result["manual_files"],
        "failures": result["failures"],
        "pdf_outputs": result["pdf_outputs"],
        "logs": logs,
    }


def _notice_task_worker(task_id: str, payload: Dict[str, Any]) -> None:
    with _NOTICE_TASK_LOCK:
        task = _NOTICE_TASKS.get(task_id)
    if not task:
        return

    progress = task["progress"]
    pythoncom = None
    try:
        import pythoncom as _pythoncom  # type: ignore

        pythoncom = _pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pythoncom = None
    try:
        result = _doc_notice_process(payload, progress=progress)
        with _NOTICE_TASK_LOCK:
            task.update({
                "running": False,
                "done": True,
                "success": bool(result.get("success")),
                "message": result.get("message") or ("处理完成" if result.get("success") else "处理失败"),
                "result": result,
                "finished_at": time.time(),
            })
    except Exception as exc:
        progress.log(_format_exception(exc))
        progress.set(0, f"处理失败: {exc}")
        result = {
            "success": False,
            "message": f"处理失败: {exc}",
            "logs": progress.snapshot().get("logs", []),
            "failures": [{"file": str(payload.get("target_path") or ""), "reason": str(exc)}],
            "generated_files": [],
            "manual_files": [],
            "pdf_outputs": [],
        }
        with _NOTICE_TASK_LOCK:
            task.update({
                "running": False,
                "done": True,
                "success": False,
                "message": result["message"],
                "result": result,
                "error": str(exc),
                "finished_at": time.time(),
            })
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _doc_notice_process_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_path = Path(_required_text(payload, "target_path", "请选择文件夹或ZIP压缩包")).expanduser()
    if not target_path.exists():
        return {"success": False, "message": f"目标路径不存在: {target_path}", "logs": []}

    task_id = uuid.uuid4().hex
    progress = NoticeProgress()
    progress.set(1, "任务已创建，正在启动...")
    task = {
        "task_id": task_id,
        "running": True,
        "done": False,
        "success": False,
        "message": "任务已创建，正在启动...",
        "progress": progress,
        "result": None,
        "created_at": time.time(),
        "finished_at": None,
    }
    with _NOTICE_TASK_LOCK:
        _NOTICE_TASKS[task_id] = task

    worker = threading.Thread(target=_notice_task_worker, args=(task_id, dict(payload)), daemon=True)
    task["thread"] = worker
    worker.start()
    snapshot = progress.snapshot()
    return {
        "success": True,
        "task_id": task_id,
        "running": True,
        "done": False,
        "message": snapshot["message"],
        "progress": snapshot["progress"],
        "logs": snapshot["logs"],
        "processed": 0,
        "total_reports": 0,
    }


def _doc_notice_process_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_id = _required_text(payload, "task_id", "缺少任务ID")
    with _NOTICE_TASK_LOCK:
        task = _NOTICE_TASKS.get(task_id)
        if not task:
            return {"success": False, "task_id": task_id, "done": True, "running": False, "message": "任务不存在或已过期", "logs": []}
        progress = task["progress"]
        snapshot = progress.snapshot()
        result = task.get("result") or {}
        done = bool(task.get("done"))
        running = bool(task.get("running"))
        success = bool(task.get("success")) if done else True
        message = str(task.get("message") or snapshot.get("message") or "")

    response = {
        "success": success,
        "task_id": task_id,
        "running": running,
        "done": done,
        "message": message,
        "progress": 100 if done and success else snapshot["progress"],
        "logs": snapshot["logs"],
        "processed": result.get("processed", snapshot["processed"]),
        "total_reports": result.get("total_reports", snapshot["total_reports"]),
        "target_path": result.get("target_path"),
        "generated_files": result.get("generated_files", []),
        "manual_files": result.get("manual_files", []),
        "failures": result.get("failures", []),
        "pdf_outputs": result.get("pdf_outputs", []),
        "error": task.get("error"),
    }
    if done:
        response["result"] = result
    return response


def _doc_notice_convert_failed_pdf(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_path = Path(_required_text(payload, "target_path", "请选择要转换的目录")).expanduser()
    failed_files = payload.get("failed_files") or []
    logs: List[str] = []
    if not target_path.exists() or not target_path.is_dir():
        return {"success": False, "message": f"目标目录不存在或不是目录: {target_path}", "logs": []}

    candidates = _collect_notice_pdf_candidates(target_path, failed_files, logs)
    file_map = [(src, src.with_suffix(".pdf")) for src in candidates]
    if not file_map:
        return {"success": False, "message": "未找到可转换的Word文档", "logs": logs}

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            converted, skipped, failures = convert_with_word_com(file_map, overwrite=True)
    except RuntimeError as exc:
        logs.extend(_captured_lines(buffer))
        return {
            "success": False,
            "message": str(exc),
            "converted": 0,
            "skipped": 0,
            "failures": [],
            "output_files": [],
            "deleted_files": [],
            "logs": logs,
        }

    logs.extend(_captured_lines(buffer))
    logs.extend(f"转换失败 {src.name}: {reason}" for src, reason in failures)
    failed_paths = {src.resolve() for src, _ in failures}
    output_files: List[str] = []
    deleted_files: List[str] = []
    for src, dst in file_map:
        if src.resolve() in failed_paths or not dst.exists():
            continue
        output_files.append(str(dst.resolve()))
        try:
            src.unlink()
            deleted_files.append(str(src.resolve()))
            logs.append(f"已删除原Word文件: {src}")
        except Exception as exc:
            logs.append(f"删除Word文件失败 {src.name}: {exc}")

    return {
        "success": len(failures) == 0,
        "message": f"转换完成：成功 {converted}，跳过 {skipped}，失败 {len(failures)}，删除Word {len(deleted_files)}",
        "converted": converted,
        "skipped": skipped,
        "failures": _failure_dicts(failures),
        "output_files": output_files,
        "deleted_files": deleted_files,
        "logs": logs,
    }


def _doc_open_path(payload: Dict[str, Any]) -> Dict[str, Any]:
    target = Path(_required_text(payload, "path", "请选择要打开的路径")).expanduser()
    if not target.exists():
        return {"success": False, "message": f"路径不存在: {target}", "path": str(target)}
    open_target = target.parent if target.is_file() else target
    opened, error = _open_path_in_system(open_target)
    return {
        "success": opened,
        "message": f"已打开: {open_target}" if opened else f"无法打开: {error}",
        "path": str(open_target),
    }
