#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报生成器模块

从用户设置的漏洞通报路径和事件通报路径中提取企业名称，按七天闭环规则
生成固定格式的本周/下周处置周报。
"""

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class WeeklyReportGenerator:
    """七天闭环周报生成器."""

    CLOSED_LOOP_DAYS = 7
    EVENT_LABELS = {
        "vulnerability": "漏洞通报",
        "event": "事件通报",
    }

    def __init__(self):
        self.company_patterns = [
            r"([\u4e00-\u9fa5A-Za-z0-9（）()·&＆\-]{2,80}?(?:股份有限公司|集团有限公司|有限责任公司|有限公司|职业培训学校|培训学校|学校|医院有限公司|医院|研究院|协会|中心|集团|公司))",
            r"([A-Za-z]+(?:\s+(?:Inc|Corp|Ltd|Co|Company|Group|Tech|Technology)))",
        ]
        self.attachment_keywords = [
            "授权委托书", "执法调查", "网络架构", "架构图", "应急响应", "异常说明",
            "数据异常", "处置报告", "整改报告", "整改反馈", "整改材料", "营业执照",
            "身份证", "截图", "说明", "附件", "证明", "模板", "汇总", "名单",
        ]
        self.notice_keywords = ["通报", "安全漏洞", "网络安全事件", "漏洞"]

    def generate_report(
        self,
        vulnerability_notice_dir: Optional[str] = None,
        event_notice_dir: Optional[str] = None,
    ) -> str:
        """生成闭环周报."""
        return self.generate_closure_report(vulnerability_notice_dir, event_notice_dir)

    def generate_closure_report(
        self,
        vulnerability_notice_dir: Optional[str] = None,
        event_notice_dir: Optional[str] = None,
    ) -> str:
        """按七天闭环规则生成固定格式周报."""
        try:
            return self.generate_closure_summary(vulnerability_notice_dir, event_notice_dir)["report"]
        except Exception as e:
            return f"生成报告时出错: {str(e)}"

    def generate_closure_summary(
        self,
        vulnerability_notice_dir: Optional[str] = None,
        event_notice_dir: Optional[str] = None,
        today: Optional[date] = None,
        exclude_monday_next_notice: bool = False,
    ) -> Dict[str, Any]:
        """生成周报和结构化统计信息."""
        today = today or datetime.now().date()
        windows = self._closure_windows(today, exclude_monday_next_notice=exclude_monday_next_notice)
        vulnerability_records = self._collect_notice_records(vulnerability_notice_dir, "vulnerability")
        event_records = self._collect_notice_records(event_notice_dir, "event")

        current_vulnerability = self._unique_companies(
            record["company"] for record in vulnerability_records
            if windows["current_closure_start"] <= record["closure_date"] <= windows["current_closure_end"]
        )
        current_events = self._unique_companies(
            record["company"] for record in event_records
            if windows["event_completed_start"] <= record["completed_date"].date() <= windows["event_completed_end"]
        )
        next_companies = self._unique_companies(
            record["company"] for record in vulnerability_records
            if windows["next_notice_start"] <= record["notice_date"].date() <= windows["next_notice_end"]
        )

        report = "\n".join([
                "本周：",
                "针对已通报漏洞做出整改的企业有：",
                self._format_company_list(current_vulnerability),
                "对涉及发生网络安全事件完成整改处置的有：",
                self._format_company_list(current_events),
                "",
                "下周：",
                "将针对通报过并进行处置的企业有：",
                self._format_company_list(next_companies),
        ])
        return {
            "report": report,
            "current_vulnerability": current_vulnerability,
            "current_events": current_events,
            "next_companies": next_companies,
            "windows": {key: value.isoformat() for key, value in windows.items()},
            "options": {
                "exclude_monday_next_notice": exclude_monday_next_notice,
            },
            "records": {
                "vulnerability": len(vulnerability_records),
                "event": len(event_records),
            },
        }

    def _closure_windows(self, today: date, exclude_monday_next_notice: bool = False) -> Dict[str, date]:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        next_week_start = week_start + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=6)
        current_closure_start = week_start
        current_closure_end = min(today, week_end)
        current_notice_start = current_closure_start - timedelta(days=self.CLOSED_LOOP_DAYS)
        current_notice_end = current_closure_end - timedelta(days=self.CLOSED_LOOP_DAYS)
        next_notice_start = week_start + timedelta(days=1 if exclude_monday_next_notice else 0)
        next_notice_end = week_end
        return {
            "current_week_start": week_start,
            "current_week_end": week_end,
            "next_week_start": next_week_start,
            "next_week_end": next_week_end,
            "current_closure_start": current_closure_start,
            "current_closure_end": current_closure_end,
            "current_notice_start": current_notice_start,
            "current_notice_end": current_notice_end,
            "next_notice_start": next_notice_start,
            "next_notice_end": next_notice_end,
            "event_completed_start": week_start,
            "event_completed_end": week_end,
        }

    def _collect_notice_records(self, notice_dir: Optional[str], notice_type: str) -> List[Dict]:
        """从通报目录中提取企业名称和通报日期."""
        root_text = str(notice_dir or "").strip().strip('"')
        if not root_text:
            return []

        root = Path(root_text).expanduser()
        if not root.exists():
            print(f"通报路径不存在: {root}")
            return []

        if notice_type == "event":
            return self._collect_event_disposal_records(root)

        entries: List[Path] = []
        if root.is_file():
            entries.append(root)
        else:
            for current_root, dirs, files in os.walk(root):
                dirs.sort()
                files.sort()
                for file_name in files:
                    if not self._is_candidate_notice_file(file_name, notice_type):
                        continue
                    entries.append(Path(current_root) / file_name)

        records: List[Dict] = []
        for entry in entries:
            company = self._extract_company_name(entry, root)
            if not company:
                continue
            notice_date = self._extract_notice_date(entry)
            records.append({
                "company": company,
                "notice_date": notice_date,
                "closure_date": notice_date.date() + timedelta(days=self.CLOSED_LOOP_DAYS),
                "completed_date": notice_date + timedelta(days=self.CLOSED_LOOP_DAYS),
                "path": str(entry),
                "type": notice_type,
            })

        records.sort(key=lambda item: (item["closure_date"], item["company"], item["path"]))
        print(f"{notice_type} 通报目录提取企业 {len(records)} 条: {root}")
        return records

    def _collect_event_disposal_records(self, root: Path) -> List[Dict]:
        """从应急处置目录按企业目录提取完成处置的事件记录."""
        records: List[Dict] = []
        if root.is_file():
            if self._is_candidate_event_disposal_file(root.name):
                company = self._extract_company_name(root, root.parent)
                if company:
                    completed_date = self._extract_notice_date(root)
                    records.append({
                        "company": company,
                        "notice_date": completed_date,
                        "closure_date": completed_date.date(),
                        "completed_date": completed_date,
                        "path": str(root),
                        "type": "event",
                    })
            return records

        for current_root, dirs, files in os.walk(root):
            dirs.sort()
            files.sort()
            candidate_files = [
                Path(current_root) / file_name
                for file_name in files
                if self._is_candidate_event_disposal_file(file_name)
            ]
            if not candidate_files:
                continue

            directory = Path(current_root)
            company = self._extract_company_from_text(directory.name, allow_directory_fallback=True)
            if not company:
                company = self._extract_company_name(candidate_files[0], root)
            if not company:
                continue

            completed_date = max(
                (self._extract_notice_date(path) for path in candidate_files),
                default=datetime.fromtimestamp(directory.stat().st_mtime),
            )
            records.append({
                "company": company,
                "notice_date": completed_date,
                "closure_date": completed_date.date(),
                "completed_date": completed_date,
                "path": str(directory),
                "type": "event",
            })

        records.sort(key=lambda item: (item["completed_date"], item["company"], item["path"]))
        print(f"event 应急处置目录提取企业 {len(records)} 条: {root}")
        return records

    def _is_candidate_notice_file(self, file_name: str, notice_type: str) -> bool:
        if file_name.startswith("~$"):
            return False
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".doc", ".docx", ".wps", ".pdf"}:
            return False
        stem = Path(file_name).stem
        if any(keyword in stem for keyword in self.attachment_keywords):
            return False
        if notice_type == "event":
            return self._is_candidate_event_disposal_file(file_name)
        if "隐患通报" in stem or "安全漏洞通报" in stem:
            return True
        return (
            ("存在" in stem or "感染风险" in stem or "流量异常" in stem)
            and any(keyword in stem for keyword in ["漏洞", "安全", "风险", "木马", "未授权", "弱口令", "信息泄露"])
        )

    def _is_candidate_event_disposal_file(self, file_name: str) -> bool:
        if file_name.startswith("~$"):
            return False
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".doc", ".docx", ".wps", ".pdf"}:
            return False
        stem = Path(file_name).stem
        if any(keyword in stem for keyword in ["授权委托书", "执法调查", "架构", "截图", "反馈", "模板"]):
            return False
        return any(keyword in stem for keyword in [
            "处置情况", "处置报告", "核查报告", "事件报告书", "网络安全事件报告书",
            "网络攻击事件报告书", "事件的报告", "异常出境事件",
        ])

    def _extract_notice_date(self, path: Path) -> datetime:
        """优先从路径文本提取通报日期，失败时使用文件修改时间."""
        for part in [path.stem, *reversed(path.parts)]:
            parsed = self._parse_date_text(part)
            if parsed:
                return parsed

        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return datetime.now()

    def _parse_date_text(self, text: str) -> Optional[datetime]:
        value = str(text or "")

        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})\d{6}(?!\d)", value):
            parsed = self._build_date(match.group(1), match.group(2), match.group(3))
            if parsed:
                return parsed

        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", value):
            parsed = self._build_date(match.group(1), match.group(2), match.group(3))
            if parsed:
                return parsed

        for match in re.finditer(r"(?<!\d)(1[6-9]\d{8}|[2-9]\d{9}|1[6-9]\d{11}|[2-9]\d{12})(?!\d)", value):
            raw = match.group(1)
            timestamp = int(raw)
            if len(raw) == 13:
                timestamp = timestamp // 1000
            try:
                parsed = datetime.fromtimestamp(timestamp)
            except (OSError, OverflowError, ValueError):
                continue
            if 2000 <= parsed.year <= 2100:
                return parsed

        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})[\-._/年]?\s*(\d{1,2})[\-._/月]\s*(\d{1,2})日?(?!\d)", value):
            parsed = self._build_date(match.group(1), match.group(2), match.group(3))
            if parsed:
                return parsed

        current_year = datetime.now().year
        for match in re.finditer(r"(?<!\d)(\d{1,2})[.月](\d{1,2})日?(?!\d)", value):
            parsed = self._build_date(str(current_year), match.group(1), match.group(2))
            if parsed:
                return parsed

        return None

    def _build_date(self, year: str, month: str, day: str) -> Optional[datetime]:
        try:
            return datetime(int(year), int(month), int(day))
        except ValueError:
            return None

    def _extract_company_name(self, path: Path, root: Path) -> str:
        """从文件名或父级目录中提取企业名."""
        candidates = [path.stem]
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            relative_parts = path.parts
        parent_parts = list(relative_parts[:-1])
        candidates.extend(reversed(parent_parts))

        for candidate in candidates:
            allow_fallback = candidate in parent_parts or self._is_notice_title(candidate)
            company = self._extract_company_from_text(candidate, allow_directory_fallback=allow_fallback)
            if company:
                return company
        return ""

    def _is_notice_title(self, text: str) -> bool:
        value = str(text or "")
        if any(keyword in value for keyword in self.attachment_keywords):
            return False
        return "通报" in value and ("关于" in value or "漏洞" in value or "事件" in value)

    def _extract_company_from_text(self, text: str, allow_directory_fallback: bool = False) -> str:
        value = self._normalize_notice_text(text)
        if not value:
            return ""
        if any(keyword in value for keyword in self.attachment_keywords):
            return ""

        for pattern in self.company_patterns:
            match = re.search(pattern, value)
            if match:
                return self._clean_company_name(match.group(1))

        fallback = self._clean_company_name(value)
        if (
            allow_directory_fallback
            and 4 <= len(fallback) <= 40
            and re.search(r"[\u4e00-\u9fa5]", fallback)
            and not self._looks_like_date_or_bucket(fallback)
            and not any(keyword in fallback for keyword in [*self.attachment_keywords, "通报", "漏洞", "事件", "处置", "整改"])
            and not re.search(r"\d+个|\d+家|企业", fallback)
        ):
            return fallback
        return ""

    def _normalize_notice_text(self, text: str) -> str:
        value = str(text or "")
        value = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", value)
        value = re.sub(r"^[\d\s._\-（）()]+", "", value)
        value = re.sub(r"^(?:关于|附件\d*[:：]?|【[^】]*】)", "", value)
        value = re.split(r"(?:所属|旗下|名下)", value, 1)[0]
        value = re.sub(r"^(?:鄞州区|浙江省宁波市|浙江省)[\-_/]*", "", value)
        value = re.split(r"(?:存在|发生|网络安全事件|安全漏洞|漏洞通报|安全通报|通报|处置|整改|报告|复测)", value, 1)[0]
        return value.strip(" -_—（）()[]【】《》、，,。.")

    def _clean_company_name(self, company: str) -> str:
        value = str(company or "").strip()
        value = re.sub(r"^(?:关于|附件\d*[:：]?|\d+[\s._\-]*)", "", value)
        return value.strip(" -_—（）()[]【】《》、，,。.")

    def _looks_like_date_or_bucket(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        if self._parse_date_text(value):
            return True
        return bool(re.fullmatch(r"[\d\s._\-（）()年月日至周第批]+", value))

    def _unique_companies(self, companies: Iterable[str]) -> List[str]:
        seen = set()
        result = []
        for company in companies:
            name = self._clean_company_name(company)
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    def _format_company_list(self, companies: List[str]) -> str:
        if not companies:
            return "无"
        return "\n".join(f"{index}.{company}" for index, company in enumerate(companies, 1))


def main():
    """测试函数."""
    print("周报生成器模块加载成功")
    generator = WeeklyReportGenerator()
    print(generator.generate_report())


if __name__ == "__main__":
    main()
