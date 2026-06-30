#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Filename helpers shared by notice rewrite and rectification flows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


NOTICE_ISSUE_KEYWORDS = (
    "漏洞",
    "弱口令",
    "默认口令",
    "默认密码",
    "未授权",
    "越权",
    "注入",
    "SQL注入",
    "XSS",
    "SSRF",
    "RCE",
    "远程代码执行",
    "远程命令执行",
    "命令执行",
    "代码执行",
    "文件上传",
    "文件读取",
    "文件下载",
    "文件包含",
    "目录遍历",
    "路径遍历",
    "信息泄露",
    "敏感信息",
    "反序列化",
    "风险",
    "安全问题",
    "安全隐患",
    "事件",
    "感染",
    "攻击",
    "入侵",
    "勒索",
    "木马",
    "病毒",
    "挖矿",
    "篡改",
    "钓鱼",
)

EVENT_HINTS = ("事件", "感染", "攻击", "入侵", "勒索", "木马", "病毒", "挖矿", "篡改", "钓鱼", "遭受", "发生")
RISK_HINTS = ("风险", "隐患")
VULNERABILITY_HINTS = (
    "漏洞",
    "弱口令",
    "默认口令",
    "默认密码",
    "未授权",
    "越权",
    "注入",
    "XSS",
    "SSRF",
    "RCE",
    "代码执行",
    "命令执行",
    "文件上传",
    "文件读取",
    "文件下载",
    "文件包含",
    "目录遍历",
    "路径遍历",
    "信息泄露",
    "敏感信息",
    "反序列化",
)
VULNERABILITY_ALIAS_HINTS = (
    "dirty cow",
    "dirtycow",
    "log4j",
    "log4shell",
    "spring4shell",
    "shiro",
    "struts",
    "struts2",
    "weblogic",
    "fastjson",
    "thinkphp",
    "nacos",
    "jenkins",
    "tomcat",
    "redis",
    "zookeeper",
    "druid",
    "phpmyadmin",
    "apache",
    "nginx",
    "openssl",
    "heartbleed",
    "shellshock",
    "cve-",
)


def clean_notice_stem(filename: Any) -> str:
    stem = Path(str(filename or "")).stem
    stem = re.sub(r"[\s_-]*(?:19|20)\d{6,12}$", "", stem)
    stem = re.sub(r"^\d+", "", stem)
    return stem.strip(" \t\r\n，,。；;：:、-_—–")


def normalize_issue_type(value: Any, company_name: str | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    text = re.sub(r"[\s_-]*(?:19|20)\d{6,12}$", "", text).strip()
    text = re.sub(r"^疑似", "", text).strip()
    text = re.sub(r"^存在", "", text).strip()
    text = re.sub(r"^(?:的)?安全问题$", "安全问题", text)
    for suffix in (
        "的预警通报",
        "预警通报",
        "的通报",
        "通报",
        "的报告",
        "报告",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    text = re.sub(r"的报告（.*?）$", "", text)
    text = re.sub(r"报告（.*?）$", "", text)
    if company_name and company_name in text:
        text = text.split(company_name, 1)[-1].strip()
    text = text.strip(" \t\r\n，,。；;：:、-_—–")
    text = re.sub(r"安全安全", "安全", text)
    if not text:
        return None

    if text.endswith(("漏洞", "风险", "事件", "隐患", "安全问题", "安全隐患")):
        return text
    if "漏洞" in text:
        match = re.search(r"(.+?漏洞)", text)
        return match.group(1).strip() if match else text
    if "风险" in text:
        match = re.search(r"(.+?风险)", text)
        return match.group(1).strip() if match else text
    if "事件" in text:
        match = re.search(r"(.+?事件)", text)
        return match.group(1).strip() if match else text
    if any(hint in text for hint in EVENT_HINTS):
        return f"{text}事件"
    if any(hint in text for hint in RISK_HINTS):
        return f"{text}风险"
    lowered = text.lower()
    if any(hint in text for hint in VULNERABILITY_HINTS) or any(hint in lowered for hint in VULNERABILITY_ALIAS_HINTS):
        return f"{text}漏洞"
    return f"{text}隐患"


def filename_has_notice_issue(filename: Any) -> bool:
    name = clean_notice_stem(filename)
    if not name:
        return False
    if "关于" in name or "通报" in name:
        return True
    if "存在" in name:
        prefix, issue = name.split("存在", 1)
        issue = issue.strip(" \t\r\n，,。；;：:、-_—–")
        if prefix and issue:
            return True
    if "存在" in name and any(keyword in name for keyword in NOTICE_ISSUE_KEYWORDS):
        return True
    if any(keyword in name for keyword in ("有限公司", "股份有限公司", "集团", "科技")) and any(
        keyword in name for keyword in NOTICE_ISSUE_KEYWORDS
    ):
        return True
    if "技术检查" in name and any(keyword in name for keyword in NOTICE_ISSUE_KEYWORDS):
        return True
    return False
