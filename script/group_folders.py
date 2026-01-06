#!/usr/bin/env python3
"""
按 1.txt 的分组将企业文件或文件夹移动到对应组目录（本地脚本，不推送）。

场景适配：
  - 目录项名称常带事件描述（如“疑似遭恶意IP攻击附件20251114”、“所属XX系统存在漏洞附件YYYYMMDD”），脚本会自动提取企业全称（截止到“公司/集团/股份有限公司/有限责任公司/有限公司”），据此分组。

用法示例（Windows）：
  # 预览（仅文件夹）
  python script/group_folders.py --source-dir "D:\\企业根目录" --entries dirs --pattern exact --dry-run
  # 预览（文件与文件夹都整理）
  python script/group_folders.py --source-dir "D:\\企业根目录" --entries both --pattern contains --dry-run
  # 正式移动（同时处理文件与文件夹）
  python script/group_folders.py --source-dir "D:\\企业根目录" --entries both --pattern contains

默认分组文件：
  c:\\Users\\lan1o\\Desktop\\wow\\1.txt

脚本流程：
  - 解析分组文件：非公司关键词行作为组名；包含“公司/集团/股份/有限责任公司/有限公司”的行视为公司名（同样进行企业名规范化）。
  - 扫描 --source-dir 的一级目录项（文件/文件夹），从名称中抽取企业全称以匹配分组。
  - 在 --dest-dir（默认同 --source-dir）下创建组文件夹，将匹配到的目录项移动进去。

安全建议：
  - 先加 --dry-run 预览，再正式执行。
  - 多重匹配或找不到匹配会提示并跳过。
"""

import argparse
import os
import sys
import shutil
import re
from typing import Dict, List, Set, Tuple, Optional
from pathlib import Path


COMPANY_KEYWORDS = [
    "公司",
    "集团",
    "股份",
    "有限责任公司",
    "有限公司",
]

def is_company_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(k in s for k in COMPANY_KEYWORDS)


def parse_groups(groups_file: str, encoding: str = "utf-8") -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    current_group: Optional[str] = None
    with open(groups_file, "r", encoding=encoding) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                # 空行跳过
                continue
            if is_company_line(line):
                if not current_group:
                    # 先遇到公司行则归入“未分组”
                    current_group = "未分组"
                    groups.setdefault(current_group, [])
                groups.setdefault(current_group, []).append(line)
            else:
                # 新的组名
                current_group = line
                groups.setdefault(current_group, [])
    return groups


def list_entries(path: str, entries: str) -> List[Tuple[str, bool]]:
    """返回 (name, is_dir) 列表。
    entries: 'dirs' | 'files' | 'both'
    """
    out: List[Tuple[str, bool]] = []
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        is_dir = os.path.isdir(full)
        if entries == "dirs" and not is_dir:
            continue
        if entries == "files" and is_dir:
            continue
        out.append((entry, is_dir))
    return out


def normalize_company(name: str) -> Optional[str]:
    """从目录项名中提取企业全称（处理专项、关于等前缀，并精确匹配后缀）。"""
    s = name.strip()
    # 1. 清理常见前缀
    s = re.sub(r'^[（(【]专项[）)】]', '', s)
    s = re.sub(r'^关于', '', s)
    s = re.sub(r'^通报[：:]', '', s)
    s = s.strip()
    
    # 2. 提取“所属”之前的部分
    if "所属" in s:
        s = s.split("所属")[0].strip()
    
    # 3. 定义后缀优先级
    strong_suffixes = [
        "股份有限公司", "有限责任公司", "有限公司", "责任有限公司", 
        "集团公司", "集团", "公司", "制造厂", "工厂", "厂",
        "中心", "研究所", "研究院", "医院", "学校", "幼儿园", "托儿所",
        "商行", "事务所", "合作社", "农场", "经营部", "工作室",
        "委员会", "协会", "党支部", "联合会", "超市", "便利店",
        "饭店", "酒店", "宾馆", "旅馆"
    ]
    
    weak_suffixes = [
        "局", "厅", "处", "署", "队", "站", "网", "店", "吧", "KTV", "会所", "棋牌", "俱乐部"
    ]
    
    best_match_end = -1
    for suffix in strong_suffixes:
        idx = s.rfind(suffix)
        if idx != -1:
            end_pos = idx + len(suffix)
            if end_pos > best_match_end:
                best_match_end = end_pos
    
    if best_match_end != -1:
        return s[:best_match_end].strip()
    
    for suffix in weak_suffixes:
        idx = s.rfind(suffix)
        if idx != -1:
            end_pos = idx + len(suffix)
            if end_pos > best_match_end:
                best_match_end = end_pos
                
    if best_match_end != -1:
        return s[:best_match_end].strip()
    
    return None

def choose_group_for_company(company_base: str, groups: Dict[str, List[str]], mode: str) -> Tuple[Optional[str], str]:
    """基于公司名（规范化后）在分组中选择所属组。返回 (group_name, reason)。"""
    # 先构建规范化公司 -> 组 映射
    company_to_group: Dict[str, str] = {}
    all_companies: List[str] = []
    for g, comps in groups.items():
        for c in comps:
            c_norm = normalize_company(c) or c.strip()
            company_to_group.setdefault(c_norm, g)
            all_companies.append(c_norm)

    # exact 优先
    if company_base in company_to_group:
        return company_to_group[company_base], "exact"

    if mode == "exact":
        return None, "not_found"

    # contains 模式：唯一包含关系
    candidates = []
    for c_norm in all_companies:
        if company_base in c_norm or c_norm in company_base:
            candidates.append((c_norm, company_to_group[c_norm]))

    if len(candidates) == 1:
        return candidates[0][1], "contains"
    if len(candidates) == 0:
        return None, "not_found"
    detail = "|".join([c for c, _ in candidates])
    return None, f"ambiguous:{detail}"


def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def move_entry(src_dir: str, name: str, dest_group_dir: str, dry_run: bool) -> bool:
    src_path = os.path.join(src_dir, name)
    dest_path = os.path.join(dest_group_dir, name)
    if not os.path.exists(src_path):
        print(f"[WARN] source not found: {src_path}")
        return False
    if os.path.exists(dest_path):
        print(f"[SKIP] already exists in group: {dest_path}")
        return True
    print(f"[MOVE] {src_path} -> {dest_path}")
    if not dry_run:
        shutil.move(src_path, dest_path)
    return True


def _has_disposal_template(target_dir: str) -> bool:
    try:
        for entry in os.listdir(target_dir):
            if entry.lower().endswith('.docx') and ('处置' in entry and '模板' in entry):
                return True
    except Exception:
        pass
    return False


def _pick_disposal_template() -> Optional[str]:
    repo_root = Path(__file__).resolve().parents[1]
    tmpl_dir = repo_root / 'Report_Template'
    candidates: List[Path] = []
    if tmpl_dir.exists():
        for p in tmpl_dir.glob('*.docx'):
            if '处置' in p.name and '模板' in p.name:
                candidates.append(p)
        # 如果没有包含“模板”的，退化到任意含“处置”的模板
        if not candidates:
            for p in tmpl_dir.glob('*处置*.docx'):
                candidates.append(p)
    # 兜底相对路径
    if not candidates:
        fallback = repo_root / 'Report_Template' / '处置文件模板.docx'
        if fallback.exists():
            candidates.append(fallback)
    return str(candidates[0]) if candidates else None


def _clean_template_name(name: str) -> str:
    m = re.match(r'^(\d+)(.*)$', name)
    return m.group(2) if m else name


def ensure_disposal_template(company_dir: str, dry_run: bool) -> None:
    if not os.path.isdir(company_dir):
        return
    if _has_disposal_template(company_dir):
        print(f"[TEMPLATE] disposal template exists: {company_dir}")
        return
    template_path = _pick_disposal_template()
    if not template_path:
        print(f"[TEMPLATE] no disposal template found in Report_Template")
        return
    target_name = _clean_template_name(os.path.basename(template_path))
    dest_path = os.path.join(company_dir, target_name)
    if os.path.exists(dest_path):
        print(f"[TEMPLATE] target already exists: {dest_path}")
        return
    print(f"[TEMPLATE] copy disposal template -> {dest_path}")
    if not dry_run:
        try:
            shutil.copy2(template_path, dest_path)
        except Exception as e:
            print(f"[ERROR] copy template failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="按 1.txt 的分组整理企业目录项（文件/文件夹）")
    parser.add_argument("--source-dir", required=True, help="包含企业相关目录项的根目录（一级文件/文件夹）")
    parser.add_argument("--dest-dir", default=None, help="组目录的根路径（默认与 --source-dir 相同）")
    parser.add_argument("--groups-file", default=r"c:\\Users\\lan1o\\Desktop\\wow\\1.txt", help="分组文本文件路径")
    parser.add_argument("--encoding", default="utf-8", help="分组文本编码")
    parser.add_argument("--pattern", choices=["exact", "contains"], default="exact", help="文件夹名匹配策略")
    parser.add_argument("--entries", choices=["dirs", "files", "both"], default="both", help="处理对象：文件夹/文件/两者")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不移动")

    args = parser.parse_args()

    source_dir = os.path.abspath(args.source_dir)
    dest_dir = os.path.abspath(args.dest_dir or source_dir)
    groups_file = args.groups_file
    encoding = args.encoding
    mode = args.pattern
    entries = args.entries
    dry_run = args.dry_run

    if not os.path.isdir(source_dir):
        print(f"[ERROR] --source-dir is not a directory: {source_dir}")
        sys.exit(1)
    if not os.path.isfile(groups_file):
        print(f"[ERROR] --groups-file not found: {groups_file}")
        sys.exit(1)

    print(f"[INFO] source-dir: {source_dir}")
    print(f"[INFO] dest-dir:   {dest_dir}")
    print(f"[INFO] groups-file: {groups_file} (encoding={encoding})")
    print(f"[INFO] pattern: {mode}; dry-run: {dry_run}")

    groups = parse_groups(groups_file, encoding=encoding)
    entries_list = list_entries(source_dir, entries=entries)

    print(f"[INFO] detected {len(entries_list)} items in source ({entries})")
    print(f"[INFO] parsed {len(groups)} groups from text file")

    total_moves = 0
    for name, is_dir in entries_list:
        company_base = normalize_company(name)
        if not company_base:
            print(f"[MISS] entry '{name}' -> no_company_extracted")
            continue
        group_name, reason = choose_group_for_company(company_base, groups, mode)
        if not group_name:
            print(f"[MISS] entry '{name}' ({company_base}) -> {reason}")
            # 即便未分组成功，若该项是企业文件夹，也确保其中有处置模板
            if is_dir:
                ensure_disposal_template(os.path.join(source_dir, name), dry_run=dry_run)
            continue
        group_dir = os.path.join(dest_dir, group_name)
        ensure_dir(group_dir)
        ok = move_entry(source_dir, name, group_dir, dry_run=dry_run)
        if ok:
            total_moves += 1
            # 如果移动的是企业文件夹，则在其中确保存在处置模板
            dest_entry_path = os.path.join(group_dir, name)
            if os.path.isdir(dest_entry_path):
                ensure_disposal_template(dest_entry_path, dry_run=dry_run)

    print(f"[SUMMARY] moves planned: {total_moves}; dry-run={dry_run}")
    if dry_run:
        print("[NOTE] Run again without --dry-run to apply changes.")


if __name__ == "__main__":
    main()