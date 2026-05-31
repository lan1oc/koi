#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import contextlib
import csv
import io
import json
import sqlite3
import sys
import time
import threading
import shutil
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List

import requests

from modules.config.config_manager import ConfigManager

INFORMATION_GATHERING_COMMANDS = {
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
}

_AIQICHA_QUERY_LOCK = threading.RLock()
_AIQICHA_QUERY_INSTANCE = None


def is_information_gathering_command(command: str | None) -> bool:
    return str(command or "") in INFORMATION_GATHERING_COMMANDS


def handle_information_gathering_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if command == "info.config.get":
        return _info_config_get()
    if command == "info.config.set":
        return _info_config_set(payload)
    if command == "info.enterprise.tyc.query":
        return _enterprise_query("tyc", payload)
    if command == "info.enterprise.aiqicha.query":
        return _enterprise_query("aiqicha", payload)
    if command == "info.enterprise.classification.get":
        return _classification_get()
    if command == "info.enterprise.classification.group.add":
        return _classification_group_add(payload)
    if command == "info.enterprise.classification.group.rename":
        return _classification_group_rename(payload)
    if command == "info.enterprise.classification.group.delete":
        return _classification_group_delete(payload)
    if command == "info.enterprise.classification.company.add":
        return _classification_company_add(payload)
    if command == "info.enterprise.classification.company.rename":
        return _classification_company_rename(payload)
    if command == "info.enterprise.classification.company.delete":
        return _classification_company_delete(payload)
    if command == "info.enterprise.classification.company.move":
        return _classification_company_move(payload)
    if command == "info.asset.fofa.query":
        return _asset_fofa_query(payload)
    if command == "info.asset.hunter.query":
        return _asset_hunter_query(payload)
    if command == "info.asset.quake.query":
        return _asset_quake_query(payload)
    if command == "info.asset.unified.query":
        return _asset_unified_query(payload)
    if command == "info.asset.syntax_doc":
        return _asset_syntax_doc(payload)
    if command == "info.threatbook.ip":
        return _threatbook_ip(payload)
    if command == "info.threatbook.ip.batch":
        return _threatbook_ip_batch(payload)
    if command == "info.threatbook.dns":
        return _threatbook_dns(payload)
    if command == "info.threatbook.file_report":
        return _threatbook_file_report(payload)
    if command == "info.threatbook.file_multiengines":
        return _threatbook_file_multiengines(payload)
    if command == "info.threatbook.file_upload":
        return _threatbook_file_upload(payload)
    if command == "info.threatbook.config.get":
        return _threatbook_config_get()
    if command == "info.threatbook.config.set":
        return _threatbook_config_set(payload)
    if command == "info.threatbook.test_connection":
        return _threatbook_test_connection()
    if command == "info.export_text":
        return _export_text(payload)
    raise ValueError(f"未知信息收集命令: {command}")


def _load_config() -> Dict[str, Any]:
    return ConfigManager().load_config()


def _save_config(config: Dict[str, Any]) -> bool:
    return ConfigManager().save_config(config)


def _get_cached_aiqicha_query():
    global _AIQICHA_QUERY_INSTANCE
    with _AIQICHA_QUERY_LOCK:
        if _AIQICHA_QUERY_INSTANCE is None:
            from modules.Information_Gathering.Enterprise_Query.aiqicha_query import AiqichaQuery

            _AIQICHA_QUERY_INSTANCE = AiqichaQuery()
        return _AIQICHA_QUERY_INSTANCE


def _required_text(payload: Dict[str, Any], key: str, message: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(message)
    return value


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _classification_db_path() -> Path:
    try:
        from modules.utils.resource_path import get_app_dir, get_base_path

        app_dir = get_app_dir()
        candidates = [app_dir / "enterprise_classification.db"]
        if getattr(sys, "frozen", False):
            sidecar_parent = Path(sys.executable).parent.parent / "enterprise_classification.db"
            if sidecar_parent not in candidates:
                candidates.append(sidecar_parent)
        bundled_db = get_base_path() / "enterprise_classification.db"

        for candidate in candidates:
            if candidate.exists() and candidate.stat().st_size > 32 * 1024:
                return candidate

        writable_db = candidates[0]
        if not writable_db.exists() and bundled_db.exists():
            writable_db.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled_db, writable_db)
        return writable_db
    except Exception:
        meipass = getattr(sys, "_MEIPASS", None)
        base_dir = meipass if meipass else Path(__file__).resolve().parents[3]
        return Path(base_dir) / "enterprise_classification.db"


def _classification_connect() -> sqlite3.Connection:
    db_path = _classification_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            sort_order INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL,
            UNIQUE(name, group_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_group ON companies(group_id)")
    conn.commit()
    return conn


def _classification_read_state() -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    with _classification_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM groups ORDER BY sort_order, id")
        for group_row in cursor.fetchall():
            group_id = int(group_row["id"])
            group_name = str(group_row["name"])
            cursor.execute(
                "SELECT name FROM companies WHERE group_id = ? ORDER BY sort_order, id",
                (group_id,),
            )
            companies = [str(row["name"]).strip() for row in cursor.fetchall() if str(row["name"]).strip()]
            groups.append({"name": group_name, "companies": companies})
    return groups


def _classification_write_state(groups: List[Dict[str, Any]]) -> None:
    with _classification_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM companies")
        cursor.execute("DELETE FROM groups")
        for group_index, group in enumerate(groups):
            group_name = str(group.get("name") or "").strip()
            if not group_name:
                continue
            companies = []
            seen = set()
            for company in group.get("companies") or []:
                company_name = str(company).strip()
                if not company_name or company_name in seen:
                    continue
                seen.add(company_name)
                companies.append(company_name)
            if group_name == "未分类" and not companies:
                continue
            cursor.execute(
                "INSERT INTO groups (name, sort_order) VALUES (?, ?)",
                (group_name, group_index),
            )
            group_id = cursor.lastrowid
            for company_index, company_name in enumerate(companies):
                cursor.execute(
                    "INSERT INTO companies (name, group_id, sort_order) VALUES (?, ?, ?)",
                    (company_name, group_id, company_index),
                )
        conn.commit()


def _classification_state_response(message: str, groups: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    groups = groups if groups is not None else _classification_read_state()
    response_groups = []
    for group in groups:
        group_name = str(group.get("name") or "").strip()
        if not group_name:
            continue
        companies = []
        seen = set()
        for company in group.get("companies") or []:
            company_name = str(company).strip()
            if not company_name or company_name in seen:
                continue
            seen.add(company_name)
            companies.append(company_name)
        if group_name == "未分类" and not companies:
            continue
        response_groups.append({
            "name": group_name,
            "companies": companies,
            "company_count": len(companies),
        })
    total_companies = sum(len(group["companies"]) for group in response_groups)
    return {
        "success": True,
        "message": message,
        "db_path": str(_classification_db_path()),
        "total_groups": len(response_groups),
        "total_companies": total_companies,
        "groups": response_groups,
    }


def _classification_find_group(groups: List[Dict[str, Any]], group_name: str) -> Dict[str, Any]:
    for group in groups:
        if str(group.get("name") or "") == group_name:
            return group
    raise ValueError(f"分组不存在: {group_name}")


def _classification_get() -> Dict[str, Any]:
    groups = _classification_read_state()
    total_companies = sum(len(group.get("companies") or []) for group in groups)
    return _classification_state_response(f"已加载 {len(groups)} 个分组，{total_companies} 家企业", groups)


def _classification_group_add(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_name = _required_text(payload, "group_name", "请输入分组名称")
    groups = _classification_read_state()
    if any(str(group.get("name") or "") == group_name for group in groups):
        raise ValueError(f"分组已存在: {group_name}")
    groups.append({"name": group_name, "companies": []})
    _classification_write_state(groups)
    return _classification_state_response(f"已添加分组: {group_name}", groups)


def _classification_group_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    old_name = _required_text(payload, "old_name", "请选择要重命名的分组")
    new_name = _required_text(payload, "new_name", "请输入新分组名称")
    groups = _classification_read_state()
    if old_name == new_name:
        return _classification_state_response("分组名称未变化", groups)
    if any(str(group.get("name") or "") == new_name for group in groups):
        raise ValueError(f"分组已存在: {new_name}")
    for group in groups:
        if str(group.get("name") or "") == old_name:
            group["name"] = new_name
            _classification_write_state(groups)
            return _classification_state_response(f"已重命名分组: {old_name} -> {new_name}", groups)
    raise ValueError(f"分组不存在: {old_name}")


def _classification_group_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_name = _required_text(payload, "group_name", "请选择要删除的分组")
    groups = _classification_read_state()
    new_groups = [group for group in groups if str(group.get("name") or "") != group_name]
    if len(new_groups) == len(groups):
        raise ValueError(f"分组不存在: {group_name}")
    _classification_write_state(new_groups)
    return _classification_state_response(f"已删除分组: {group_name}", new_groups)


def _classification_company_add(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_name = _required_text(payload, "group_name", "请选择目标分组")
    company_names = _string_list(
        payload.get("company_names")
        or payload.get("companies")
        or payload.get("companies_text")
        or payload.get("text")
    )
    if not company_names:
        raise ValueError("请输入企业名称")

    groups = _classification_read_state()
    target_group = _classification_find_group(groups, group_name)
    existing = set(str(company) for company in target_group.get("companies") or [])
    added = 0
    for company_name in company_names:
        if company_name in existing:
            continue
        target_group.setdefault("companies", []).append(company_name)
        existing.add(company_name)
        added += 1

    _classification_write_state(groups)
    return _classification_state_response(f"已添加 {added} 家企业到 {group_name}", groups)


def _classification_company_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_name = _required_text(payload, "group_name", "请选择目标分组")
    old_name = _required_text(payload, "old_name", "请选择要修改的企业")
    new_name = _required_text(payload, "new_name", "请输入新企业名称")
    groups = _classification_read_state()
    target_group = _classification_find_group(groups, group_name)
    companies = list(target_group.get("companies") or [])
    if old_name == new_name:
        return _classification_state_response("企业名称未变化", groups)
    if new_name in companies:
        raise ValueError(f"企业已存在: {new_name}")
    for index, company_name in enumerate(companies):
        if company_name == old_name:
            companies[index] = new_name
            target_group["companies"] = companies
            _classification_write_state(groups)
            return _classification_state_response(f"已修改企业名称: {old_name} -> {new_name}", groups)
    raise ValueError(f"企业不存在: {old_name}")


def _classification_company_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_name = _required_text(payload, "group_name", "请选择目标分组")
    company_names = set(_string_list(payload.get("company_names") or payload.get("company_name") or payload.get("companies")))
    if not company_names:
        raise ValueError("请输入企业名称")

    groups = _classification_read_state()
    target_group = _classification_find_group(groups, group_name)
    companies = list(target_group.get("companies") or [])
    new_companies = [company for company in companies if company not in company_names]
    removed = len(companies) - len(new_companies)
    if removed == 0:
        raise ValueError("未找到要删除的企业")
    target_group["companies"] = new_companies
    _classification_write_state(groups)
    return _classification_state_response(f"已删除 {removed} 家企业", groups)


def _classification_company_move(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_group_name = _required_text(payload, "source_group", "请选择源分组")
    target_group_name = _required_text(payload, "target_group", "请选择目标分组")
    company_names = _string_list(payload.get("company_names") or payload.get("companies") or payload.get("company_name"))
    if not company_names:
        raise ValueError("请输入企业名称")
    if source_group_name == target_group_name:
        groups = _classification_read_state()
        return _classification_state_response("源分组和目标分组相同", groups)

    groups = _classification_read_state()
    source_group = _classification_find_group(groups, source_group_name)
    target_group = _classification_find_group(groups, target_group_name)
    selected_names = set(company_names)
    moved: List[str] = []
    remaining: List[str] = []
    for company_name in list(source_group.get("companies") or []):
        if company_name in selected_names:
            moved.append(company_name)
        else:
            remaining.append(company_name)

    if not moved:
        raise ValueError("未找到要移动的企业")

    target_companies = list(target_group.get("companies") or [])
    target_seen = set(target_companies)
    for company_name in moved:
        if company_name in target_seen:
            continue
        target_companies.append(company_name)
        target_seen.add(company_name)

    source_group["companies"] = remaining
    target_group["companies"] = target_companies
    _classification_write_state(groups)
    return _classification_state_response(f"已移动 {len(moved)} 家企业到 {target_group_name}", groups)


def _export_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    output_file = Path(_required_text(payload, "output_file", "请选择导出文件")).expanduser()
    content = str(payload.get("content") or "")
    if not content.strip():
        return {"success": False, "message": "没有可导出的内容", "output_file": str(output_file)}

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8-sig")
    return {
        "success": True,
        "message": f"导出完成: {output_file}",
        "output_file": str(output_file),
        "bytes": output_file.stat().st_size,
    }


def _int_value(payload: Dict[str, Any], key: str, default: int, minimum: int = 0, maximum: int = 10000) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _captured_lines(buffer: io.StringIO) -> List[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


class _SyntaxHtmlToTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "div",
        "p",
        "table",
        "thead",
        "tbody",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "ul",
        "ol",
    }
    _KNOWN_TAGS = _BLOCK_TAGS | {"td", "th", "br", "strong", "b", "code", "span"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def _append(self, value: str) -> None:
        if not value:
            return
        if self.parts and not self.parts[-1].endswith(("\n", " ", "\t")) and not value.startswith((" ", "\n", "\t", " | ")):
            self.parts.append(" ")
        self.parts.append(value)

    def _newline(self) -> None:
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag: str, _attrs: List[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "p", "div", "table", "tr"}:
            self._newline()
        if tag == "li":
            self._newline()
            self._append("- ")
        elif tag == "br":
            self._newline()
        elif tag not in self._KNOWN_TAGS:
            # Some old docs include unescaped examples such as <ListBucketResult>.
            self._append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self._append(" | ")
        if tag in self._BLOCK_TAGS or tag == "li":
            self._newline()
        elif tag not in self._KNOWN_TAGS:
            self._append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        text = " ".join(unescape(data).replace("\xa0", " ").split())
        if text:
            self._append(text)

    def get_text(self) -> str:
        lines: List[str] = []
        previous_blank = False
        for line in "".join(self.parts).splitlines():
            clean = " ".join(line.split()).strip(" |")
            if clean:
                lines.append(clean)
                previous_blank = False
            elif lines and not previous_blank:
                lines.append("")
                previous_blank = True
        return "\n".join(lines).strip()


def _html_to_plain_text(html: str) -> str:
    parser = _SyntaxHtmlToTextParser()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _read_lines_file(path_value: str) -> List[str]:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    suffix = path.suffix.lower()

    if suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd  # type: ignore
        except Exception as exc:
            raise RuntimeError("读取 Excel 批量文件需要 pandas") from exc
        df = pd.read_excel(path, header=None)
        return [str(value).strip() for value in df.iloc[:, 0].dropna().tolist() if str(value).strip()]

    if suffix == ".csv":
        lines: List[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            for row in reader:
                if row and str(row[0]).strip():
                    lines.append(str(row[0]).strip())
        return lines

    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            return [line.strip() for line in path.read_text(encoding=encoding).splitlines() if line.strip()]
        except UnicodeDecodeError:
            continue
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def _companies_from_payload(payload: Dict[str, Any]) -> List[str]:
    companies = payload.get("companies")
    if isinstance(companies, list):
        return [str(item).strip() for item in companies if str(item).strip()]

    company = str(payload.get("company") or payload.get("company_name") or "").strip()
    if company:
        return [company]

    batch_file = str(payload.get("batch_file") or payload.get("file_path") or "").strip()
    if batch_file:
        return _read_lines_file(batch_file)

    return []


def _format_tyc_result(result: Dict[str, Any]) -> str:
    if not result.get("success"):
        return f"查询失败: {result.get('error') or result.get('message') or '未知错误'}"
    companies = result.get("companies") or []
    if not companies:
        return "未找到企业信息"

    output = ["企业查询结果", "=" * 50]
    for index, company in enumerate(companies, 1):
        if not isinstance(company, dict):
            continue
        output.extend([
            f"\n[{index}] {company.get('name', '未知')}",
            f"法定代表人: {company.get('legalPersonName', '未知')}",
            f"注册资本: {company.get('regCapital', '未知')}",
            f"统一社会信用代码: {company.get('creditCode', '未知')}",
            f"注册地址: {company.get('regLocation', '未知')}",
        ])
        phones = company.get("phoneList") or []
        emails = company.get("emailList") or []
        websites = company.get("websites") or []
        if phones:
            output.append("联系电话: " + ", ".join(map(str, phones)))
        if emails:
            output.append("邮箱: " + ", ".join(map(str, emails)))
        if websites:
            output.append("网站: " + (", ".join(map(str, websites)) if isinstance(websites, list) else str(websites)))
        for label, key in (("ICP备案", "icp_records"), ("APP信息", "app_records"), ("微信公众号", "wechat_records")):
            records = company.get(key) or []
            output.append(f"{label}: {len(records)} 条" if isinstance(records, list) else f"{label}: 已返回")
    return "\n".join(output)


def _format_aiqicha_result(result: Dict[str, Any]) -> str:
    if not result:
        return "查询失败: 未获取到企业信息"
    if result.get("success") is False:
        return f"查询失败: {result.get('error') or result.get('message') or '未知错误'}"

    basic = result.get("basic_info") or {}
    industry = result.get("industry_info") or {}
    output = [
        f"企业查询结果: {result.get('company_name', '未知')}",
        "=" * 50,
        "\n【基本信息】",
        f"法人代表: {basic.get('legalPerson', '未获取到')}",
        f"企业地址: {basic.get('titleDomicile', '未获取到')}",
        f"注册资本: {basic.get('regCap', '未获取到')}",
        f"统一社会信用代码: {basic.get('regNo', '未获取到')}",
        f"企业邮箱: {basic.get('email', '未获取到')}",
        f"企业网站: {basic.get('website', '未获取到')}",
        f"企业电话: {basic.get('telephone', '未获取到')}",
        "\n【行业分类】",
        f"行业大类: {industry.get('industryCode1', '未获取到')}",
        f"行业中类: {industry.get('industryCode2', '未获取到')}",
        f"行业小类: {industry.get('industryCode3', '未获取到')}",
        f"具体分类: {industry.get('industryCode4', '未获取到')}",
        f"行业编号: {industry.get('industryNum', '未获取到')}",
    ]

    for title, key in (("ICP备案信息", "icp_info"), ("APP信息", "app_info"), ("微信公众号信息", "wechat_info"), ("员工联系方式", "contact_info")):
        values = result.get(key) or []
        output.append(f"\n【{title}】")
        if isinstance(values, list) and values:
            for index, item in enumerate(values, 1):
                output.append(f"{index}. {json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item}")
        else:
            output.append("暂无")
    return "\n".join(output)


def _enterprise_failure_message(source: str, formatted: str, raw: Any, logs: List[str]) -> str:
    candidates: List[str] = []
    if isinstance(raw, dict):
        for key in ("error", "message"):
            value = raw.get(key)
            if value:
                candidates.append(str(value))
    candidates.extend(str(item) for item in logs if item)
    if formatted:
        candidates.append(formatted)

    if source == "aiqicha":
        for text in candidates:
            if "Cookie 未包含百度登录态" in text or "更新爱企查登录 Cookie" in text:
                return text.strip()
            if "BDUSS" in text and ("登录态" in text or "Cookie" in text):
                return text.strip()

    for text in candidates:
        clean = text.strip()
        if clean and clean != "查询失败: 未获取到企业信息":
            return clean
    return "查询失败"


def _first_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
            if text:
                return text
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _enterprise_company_row(source: str, index: int, query: str, success: bool, data: Any, error: str = "") -> Dict[str, Any]:
    raw = data
    if source == "tyc":
        company_data: Dict[str, Any] = {}
        if isinstance(data, dict):
            companies = data.get("companies")
            if isinstance(companies, list) and companies and isinstance(companies[0], dict):
                company_data = companies[0]
            elif isinstance(data.get("data"), dict):
                nested = data.get("data") or {}
                nested_companies = nested.get("companies")
                if isinstance(nested_companies, list) and nested_companies and isinstance(nested_companies[0], dict):
                    company_data = nested_companies[0]
                else:
                    company_data = nested
            else:
                company_data = data
        return {
            "index": index,
            "source": "Tianyancha",
            "query": query,
            "success": success,
            "company_name": _first_value(company_data.get("name"), query),
            "legal_person": _first_value(company_data.get("legalPersonName"), company_data.get("legal_person")),
            "credit_code": _first_value(company_data.get("creditCode"), company_data.get("credit_code")),
            "reg_capital": _first_value(company_data.get("regCapital"), company_data.get("reg_capital")),
            "phone": _first_value(company_data.get("phoneList"), company_data.get("phone"), company_data.get("telephone")),
            "email": _first_value(company_data.get("emailList"), company_data.get("email")),
            "website": _first_value(company_data.get("websites"), company_data.get("website")),
            "address": _first_value(company_data.get("regLocation"), company_data.get("address")),
            "error": error,
            "raw": raw,
        }

    data_dict = data if isinstance(data, dict) else {}
    basic = data_dict.get("basic_info") if isinstance(data_dict.get("basic_info"), dict) else {}
    industry = data_dict.get("industry_info") if isinstance(data_dict.get("industry_info"), dict) else {}
    return {
        "index": index,
        "source": "Aiqicha",
        "query": query,
        "success": success,
        "company_name": _first_value(data_dict.get("company_name"), basic.get("entName"), query),
        "legal_person": _first_value(basic.get("legalPerson"), basic.get("legalPersonName")),
        "credit_code": _first_value(basic.get("regNo"), basic.get("creditCode")),
        "reg_capital": _first_value(basic.get("regCap"), basic.get("regCapital")),
        "phone": _first_value(basic.get("telephone"), basic.get("phone")),
        "email": _first_value(basic.get("email")),
        "website": _first_value(basic.get("website")),
        "address": _first_value(basic.get("titleDomicile"), basic.get("regLocation"), basic.get("address")),
        "industry": _first_value(industry.get("industryCode1"), industry.get("industryCode2"), industry.get("industryNum")),
        "error": error,
        "raw": raw,
    }


def _enterprise_result_rows(source: str, raw: Any, requested_companies: List[str], success: bool) -> List[Dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("results"), list):
        rows: List[Dict[str, Any]] = []
        for index, item in enumerate(raw.get("results") or [], 1):
            item_dict = item if isinstance(item, dict) else {}
            query = _first_value(
                item_dict.get("company"),
                item_dict.get("company_name"),
                requested_companies[index - 1] if index - 1 < len(requested_companies) else "",
            )
            item_success = bool(item_dict.get("success"))
            data = item_dict.get("data") if "data" in item_dict else item_dict
            error = "" if item_success else _first_value(item_dict.get("error"), item_dict.get("message"))
            rows.append(_enterprise_company_row(source, index, query, item_success, data, error))
        return rows

    if isinstance(raw, dict):
        query = requested_companies[0] if requested_companies else _first_value(raw.get("company_name"))
        error = "" if success else _first_value(raw.get("error"), raw.get("message"))
        return [_enterprise_company_row(source, 1, query, success, raw, error)]
    return []


def _enterprise_query(source: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    companies = _companies_from_payload(payload)
    if not companies:
        raise ValueError("请输入企业名称或选择批量文件")

    progress: List[str] = []
    buffer = io.StringIO()

    def progress_cb(message: str, *_args: Any) -> None:
        progress.append(str(message))

    with contextlib.redirect_stdout(buffer):
        if source == "tyc":
            from modules.Information_Gathering.Enterprise_Query.tianyancha_query import TianyanchaQuery

            engine = TianyanchaQuery()
            if len(companies) == 1:
                raw = engine.query_company_complete(companies[0], status_callback=progress_cb)
                success = bool(raw.get("success")) if isinstance(raw, dict) else False
                formatted = _format_tyc_result(raw if isinstance(raw, dict) else {})
            else:
                raw = engine.batch_search(companies, progress_callback=progress_cb)
                success = bool(raw.get("success")) if isinstance(raw, dict) else False
                formatted = engine.format_batch_results(raw) if isinstance(raw, dict) else ""
        else:
            with _AIQICHA_QUERY_LOCK:
                engine = _get_cached_aiqicha_query()
                if len(companies) == 1:
                    raw = engine.query_company_info(companies[0], status_callback=progress_cb)
                    success = bool(raw) and not (isinstance(raw, dict) and raw.get("success") is False)
                    formatted = _format_aiqicha_result(raw if isinstance(raw, dict) else {})
                else:
                    raw = engine.batch_search(companies, progress_callback=progress_cb)
                    success = bool(raw.get("success")) if isinstance(raw, dict) else False
                    formatted = engine.format_batch_results(raw) if isinstance(raw, dict) else ""

    progress.extend(_captured_lines(buffer))
    message = "查询完成" if success else _enterprise_failure_message(source, formatted, raw, progress)
    return {
        "success": success,
        "message": message,
        "source": source,
        "companies": companies,
        "formatted": formatted,
        "rows": _enterprise_result_rows(source, raw, companies, success),
        "raw": raw,
        "logs": progress,
    }


def _info_config_get() -> Dict[str, Any]:
    config = _load_config()
    return {
        "fofa": {
            "email": config.get("fofa", {}).get("email", ""),
            "api_key": config.get("fofa", {}).get("api_key", ""),
        },
        "hunter": {
            "api_key": config.get("hunter", {}).get("api_key", ""),
        },
        "quake": {
            "api_key": config.get("quake", {}).get("api_key", ""),
        },
        "tyc": {
            "cookie": config.get("tyc", {}).get("cookie", ""),
        },
        "aiqicha": {
            "cookie": config.get("aiqicha", {}).get("cookie", ""),
            "xunkebao_cookie": config.get("aiqicha", {}).get("xunkebao_cookie", ""),
        },
        "threatbook_api_key": config.get("threatbook_api_key", ""),
    }


def _info_config_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = _load_config()
    if "fofa_email" in payload or "fofa_api_key" in payload:
        config.setdefault("fofa", {})["email"] = str(payload.get("fofa_email") or "")
        config.setdefault("fofa", {})["api_key"] = str(payload.get("fofa_api_key") or "")
        config.setdefault("fofa", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "hunter_api_key" in payload:
        config.setdefault("hunter", {})["api_key"] = str(payload.get("hunter_api_key") or "")
        config.setdefault("hunter", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "quake_api_key" in payload:
        config.setdefault("quake", {})["api_key"] = str(payload.get("quake_api_key") or "")
        config.setdefault("quake", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "tyc_cookie" in payload:
        config.setdefault("tyc", {})["cookie"] = str(payload.get("tyc_cookie") or "")
        config.setdefault("tyc", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "aiqicha_cookie" in payload:
        config.setdefault("aiqicha", {})["cookie"] = str(payload.get("aiqicha_cookie") or "")
        config.setdefault("aiqicha", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "xunkebao_cookie" in payload:
        config.setdefault("aiqicha", {})["xunkebao_cookie"] = str(payload.get("xunkebao_cookie") or "")
        config.setdefault("aiqicha", {})["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if "threatbook_api_key" in payload:
        config["threatbook_api_key"] = str(payload.get("threatbook_api_key") or "")

    if not _save_config(config):
        raise RuntimeError("保存信息收集配置失败")
    return _info_config_get()


def _fofa_result_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(result.get("results") or [], 1):
        rows.append({
            "index": index,
            "host": item.get("host", ""),
            "ip": item.get("ip", ""),
            "port": item.get("port", ""),
            "title": item.get("title", ""),
            "country": item.get("country", ""),
            "protocol": item.get("protocol", ""),
            "raw": item,
        })
    return rows


def _asset_fofa_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = _required_text(payload, "query", "请输入 FOFA 查询语句")
    page = _int_value(payload, "page", 1, 1, 10000)
    size = _int_value(payload, "size", 100, 1, 10000)
    fields = str(payload.get("fields") or "host,ip,port,title,country,protocol").strip()
    config = _load_config()
    email = str(payload.get("email") or config.get("fofa", {}).get("email") or "")
    api_key = str(payload.get("api_key") or config.get("fofa", {}).get("api_key") or "")
    if not api_key:
        return {"success": False, "message": "FOFA API Key 未配置", "rows": [], "logs": []}

    from modules.Information_Gathering.Asset_Mapping.fofa import FOFASearcher

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = FOFASearcher(api_key=api_key, email=email).search(query, size=size, page=page, fields=fields)
    logs = _captured_lines(buffer)
    success = bool(result.get("success"))
    return {
        "success": success,
        "message": f"FOFA 查询完成，获得 {len(result.get('results') or [])} 条结果" if success else result.get("error", "FOFA 查询失败"),
        "rows": _fofa_result_rows(result),
        "raw": result,
        "logs": logs,
    }


def _asset_hunter_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = _required_text(payload, "query", "请输入 Hunter 查询语句")
    page = _int_value(payload, "page", 1, 1, 10000)
    page_size = _int_value(payload, "page_size", _int_value(payload, "size", 100, 1, 100), 1, 100)
    config = _load_config()
    api_key = str(payload.get("api_key") or config.get("hunter", {}).get("api_key") or "")
    if not api_key:
        return {"success": False, "message": "Hunter API Key 未配置", "rows": [], "logs": []}

    query_encoded = base64.urlsafe_b64encode(query.encode("utf-8")).decode("ascii")
    params = {
        "api-key": api_key,
        "search": query_encoded,
        "page": page,
        "page_size": page_size,
        "is_web": _int_value(payload, "is_web", 3, 1, 3),
        "port_filter": bool(payload.get("port_filter", False)),
    }
    for key in ("start_time", "end_time", "fields"):
        value = str(payload.get(key) or "").strip()
        if value:
            params[key] = value

    try:
        response = requests.get("https://hunter.qianxin.com/openApi/search", params=params, timeout=30)
        result = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"message": response.text}
    except Exception as exc:
        return {"success": False, "message": f"Hunter 查询失败: {exc}", "rows": [], "logs": []}

    success = response.status_code == 200 and result.get("code") in (200, "200", None)
    data = result.get("data") or {}
    assets = data.get("arr") or []
    rows = []
    for index, item in enumerate(assets, 1):
        rows.append({
            "index": index,
            "url": item.get("url") or item.get("web", {}).get("url") or item.get("domain", ""),
            "ip": item.get("ip", ""),
            "port": item.get("port", ""),
            "title": item.get("web_title") or item.get("web", {}).get("title") or item.get("title", ""),
            "company": item.get("company", ""),
            "status_code": item.get("status_code") or item.get("web", {}).get("status_code", ""),
            "raw": item,
        })
    return {
        "success": success,
        "message": f"Hunter 查询完成，获得 {len(rows)} 条结果" if success else result.get("message", f"HTTP {response.status_code}"),
        "rows": rows,
        "query_count": 1,
        "raw": result,
        "logs": [],
    }


def _asset_quake_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = _required_text(payload, "query", "请输入 Quake 查询语句")
    size = _int_value(payload, "size", 100, 1, 10000)
    start = _int_value(payload, "start", 0, 0, 1000000)
    config = _load_config()
    api_key = str(payload.get("api_key") or config.get("quake", {}).get("api_key") or "")
    if not api_key:
        return {"success": False, "message": "Quake API Key 未配置", "rows": [], "logs": []}

    from modules.Information_Gathering.Asset_Mapping.quake import QuakeAPI

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = QuakeAPI(api_key=api_key).search(query, size=size, start=start)
    logs = _captured_lines(buffer)
    data = result.get("data") or []
    rows = []
    for index, item in enumerate(data, 1):
        service = item.get("service") or {}
        rows.append({
            "index": index,
            "ip": item.get("ip", ""),
            "port": item.get("port", ""),
            "hostname": item.get("hostname") or item.get("domain", ""),
            "service": service.get("name") if isinstance(service, dict) else service,
            "title": item.get("title") or item.get("web", {}).get("title", ""),
            "location": item.get("location", {}),
            "org": item.get("org", ""),
            "raw": item,
        })
    success = bool(result.get("success"))
    return {
        "success": success,
        "message": f"Quake 查询完成，获得 {len(rows)} 条结果" if success else result.get("error", "Quake 查询失败"),
        "rows": rows,
        "raw": result,
        "logs": logs,
    }


def _asset_unified_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    platforms = payload.get("platforms") or ["fofa", "hunter", "quake"]
    if not isinstance(platforms, list):
        platforms = [str(platforms)]

    query_text = str(payload.get("query") or "").strip()
    batch_file = str(payload.get("batch_file") or payload.get("file_path") or "").strip()
    if batch_file:
        queries = _read_lines_file(batch_file)
    elif isinstance(payload.get("queries"), list):
        queries = [str(item).strip() for item in payload.get("queries") or [] if str(item).strip()]
    else:
        queries = [query_text] if query_text else []

    queries = list(dict.fromkeys(queries))
    if not queries:
        raise ValueError("请输入查询语句或选择批量文件")

    rows: List[Dict[str, Any]] = []
    logs: List[str] = []
    errors: List[str] = []
    for query in queries:
        query_payload = {**payload, "query": query}
        for platform in platforms:
            name = str(platform).lower()
            try:
                if name == "fofa":
                    result = _asset_fofa_query(query_payload)
                elif name == "hunter":
                    result = _asset_hunter_query(query_payload)
                elif name == "quake":
                    result = _asset_quake_query(query_payload)
                else:
                    continue
                logs.extend(result.get("logs") or [])
                if not result.get("success"):
                    errors.append(f"{query} / {platform}: {result.get('message')}")
                for row in result.get("rows") or []:
                    rows.append({"query": query, "platform": platform, **row})
            except Exception as exc:
                errors.append(f"{query} / {platform}: {exc}")
    return {
        "success": not errors,
        "message": f"统一查询完成，获得 {len(rows)} 条结果" if not errors else "统一查询部分失败: " + "；".join(errors),
        "rows": rows,
        "logs": logs,
        "errors": errors,
    }


def _asset_syntax_doc(payload: Dict[str, Any]) -> Dict[str, Any]:
    platform = _required_text(payload, "platform", "请选择语法平台").lower()
    if platform == "fofa":
        from modules.Information_Gathering.Asset_Mapping.fofa_syntax_doc import (
            get_fofa_common_fields,
            get_fofa_syntax_doc,
            get_fofa_syntax_examples,
        )

        title = "FOFA 网络空间测绘查询语法文档"
        html_doc = get_fofa_syntax_doc()
        common_fields = get_fofa_common_fields()
        examples = get_fofa_syntax_examples()
    elif platform == "hunter":
        from modules.Information_Gathering.Asset_Mapping.hunter_syntax_doc import (
            get_hunter_common_fields,
            get_hunter_syntax_doc,
            get_hunter_syntax_examples,
        )

        title = "Hunter 鹰图平台查询语法文档"
        html_doc = get_hunter_syntax_doc()
        common_fields = get_hunter_common_fields()
        examples = get_hunter_syntax_examples()
    elif platform == "quake":
        from modules.Information_Gathering.Asset_Mapping.quake_syntax_doc import (
            get_quake_common_fields,
            get_quake_syntax_doc,
            get_quake_syntax_examples,
        )

        title = "Quake 360网络空间测绘查询语法文档"
        html_doc = get_quake_syntax_doc()
        common_fields = get_quake_common_fields()
        examples = get_quake_syntax_examples()
    else:
        raise ValueError(f"不支持的语法平台: {platform}")

    return {
        "success": True,
        "message": f"已加载 {title}",
        "platform": platform,
        "title": title,
        "text": _html_to_plain_text(html_doc),
        "common_fields": common_fields,
        "examples": examples,
    }


def _threatbook_api() -> Any:
    from modules.Information_Gathering.Threat_Intelligence.threatbook_api import ThreatBookAPI

    return ThreatBookAPI(api_key=str(_load_config().get("threatbook_api_key") or ""))


def _threatbook_ip(payload: Dict[str, Any]) -> Dict[str, Any]:
    ip = _required_text(payload, "ip", "请输入 IP 地址")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().query_ip_reputation(ip, lang=str(payload.get("lang") or "zh"))
    success = "error" not in result
    return {"success": success, "message": "IP 信誉查询完成" if success else result.get("error"), "result": result, "logs": _captured_lines(buffer)}


def _threatbook_dns(payload: Dict[str, Any]) -> Dict[str, Any]:
    domain = _required_text(payload, "domain", "请输入域名")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().query_dns_compromise(domain)
    success = "error" not in result
    return {"success": success, "message": "域名失陷检测完成" if success else result.get("error"), "result": result, "logs": _captured_lines(buffer)}


def _threatbook_ip_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_ips = payload.get("ips")
    if isinstance(raw_ips, list):
        ips = [str(item).strip() for item in raw_ips if str(item).strip()]
    else:
        ip_text = str(payload.get("ip_text") or "").strip()
        ips = [line.strip() for line in ip_text.splitlines() if line.strip()]

    batch_file = str(payload.get("batch_file") or payload.get("file_path") or "").strip()
    if batch_file:
        ips.extend(_read_lines_file(batch_file))

    ips = list(dict.fromkeys(ips))
    if not ips:
        raise ValueError("请输入或选择 IP 列表")

    progress: List[str] = []

    def progress_cb(message: str) -> None:
        progress.append(str(message))

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        results = _threatbook_api().batch_query_ip(ips, progress_callback=progress_cb)

    rows = []
    for index, item in enumerate(results):
        row_ip = ips[index] if index < len(ips) else item.get("ip") or item.get("resource") or ""
        rows.append({"index": index + 1, "ip": row_ip, "success": "error" not in item, "raw": item})

    progress.extend(_captured_lines(buffer))
    failed = sum(1 for item in results if isinstance(item, dict) and "error" in item)
    return {
        "success": failed == 0,
        "message": f"批量查询完成: {len(results)} 个 IP" if failed == 0 else f"批量查询完成，{failed} 个失败",
        "rows": rows,
        "results": results,
        "logs": progress,
    }


def _threatbook_file_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    resource = _required_text(payload, "resource", "请输入文件哈希或 scan_id")
    resource_type = str(payload.get("resource_type") or "sha256").strip().lower()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().query_file_report(resource, resource_type)
    success = "error" not in result
    return {
        "success": success,
        "message": "文件报告查询完成" if success else result.get("error", "文件报告查询失败"),
        "result": result,
        "logs": _captured_lines(buffer),
    }


def _threatbook_file_multiengines(payload: Dict[str, Any]) -> Dict[str, Any]:
    resource = _required_text(payload, "resource", "请输入文件哈希")
    resource_type = str(payload.get("resource_type") or "sha256").strip().lower()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().query_file_multiengines(resource, resource_type)
    success = "error" not in result
    return {
        "success": success,
        "message": "多引擎检测完成" if success else result.get("error", "多引擎检测失败"),
        "result": result,
        "logs": _captured_lines(buffer),
    }


def _threatbook_file_upload(payload: Dict[str, Any]) -> Dict[str, Any]:
    file_path = _required_text(payload, "file_path", "请选择要上传分析的文件")
    sandbox_type = str(payload.get("sandbox_type") or "win7_sp1_enx86_office2013").strip()
    run_time = _int_value(payload, "run_time", 60, 30, 300)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().upload_file(file_path, sandbox_type=sandbox_type, run_time=run_time)
    success = "error" not in result
    return {
        "success": success,
        "message": "文件上传分析完成" if success else result.get("error", "文件上传分析失败"),
        "result": result,
        "logs": _captured_lines(buffer),
    }


def _threatbook_test_connection() -> Dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _threatbook_api().test_connection()
    return {
        "success": bool(result.get("success")),
        "message": str(result.get("message") or ("连接测试完成" if result.get("success") else "连接测试失败")),
        "result": result,
        "logs": _captured_lines(buffer),
    }


def _threatbook_config_get() -> Dict[str, Any]:
    return {"api_key": str(_load_config().get("threatbook_api_key") or "")}


def _threatbook_config_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = _load_config()
    config["threatbook_api_key"] = str(payload.get("api_key") or "")
    if not _save_config(config):
        raise RuntimeError("保存微步 API Key 失败")
    return _threatbook_config_get()
