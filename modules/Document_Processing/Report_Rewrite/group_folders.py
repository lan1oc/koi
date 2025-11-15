import os
import shutil
import re

COMPANY_KEYWORDS = [
    "公司",
    "集团",
    "股份",
    "有限责任公司",
    "有限公司",
]

COMPANY_SUFFIX_PATTERN = re.compile(r"^(.+?(股份有限公司|有限责任公司|有限公司|集团|公司))")

def is_company_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(k in s for k in COMPANY_KEYWORDS)

def parse_groups(groups_file: str, encoding: str = "utf-8"):
    groups = {}
    current_group = None
    with open(groups_file, "r", encoding=encoding) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if is_company_line(line):
                if not current_group:
                    current_group = "未分组"
                    groups.setdefault(current_group, [])
                groups.setdefault(current_group, []).append(line)
            else:
                current_group = line
                groups.setdefault(current_group, [])
    return groups

def list_entries(path: str, entries: str):
    out = []
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        is_dir = os.path.isdir(full)
        if entries == "dirs" and not is_dir:
            continue
        if entries == "files" and is_dir:
            continue
        out.append((entry, is_dir))
    return out

def normalize_company(name: str):
    s = name.strip()
    m = COMPANY_SUFFIX_PATTERN.match(s)
    if m:
        return m.group(1).strip()
    return None

def choose_group_for_company(company_base: str, groups: dict, mode: str):
    company_to_group = {}
    all_companies = []
    for g, comps in groups.items():
        for c in comps:
            c_norm = normalize_company(c) or c.strip()
            company_to_group.setdefault(c_norm, g)
            all_companies.append(c_norm)
    if company_base in company_to_group:
        return company_to_group[company_base], "exact"
    if mode == "exact":
        return None, "not_found"
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

def move_entry(src_dir: str, name: str, dest_group_dir: str, dry_run: bool = False):
    src_path = os.path.join(src_dir, name)
    dest_path = os.path.join(dest_group_dir, name)
    if not os.path.exists(src_path):
        return False, "source_not_found"
    if os.path.exists(dest_path):
        return True, "already_exists"
    shutil.move(src_path, dest_path)
    return True, "moved"

def run_grouping(source_dir: str, groups_file: str, entries: str = "both", pattern: str = "exact", encoding: str = "utf-8"):
    result = {
        "moved": 0,
        "skipped_exist": 0,
        "miss_no_company": 0,
        "miss_not_found": 0,
        "miss_ambiguous": 0,
        "errors": 0,
        "log": [],
    }
    if not os.path.isdir(source_dir):
        result["errors"] += 1
        result["log"].append(f"[ERROR] --source-dir is not a directory: {source_dir}")
        return result
    if not os.path.isfile(groups_file):
        result["errors"] += 1
        result["log"].append(f"[ERROR] --groups-file not found: {groups_file}")
        return result
    result["log"].append(f"[INFO] source-dir: {source_dir}")
    result["log"].append(f"[INFO] groups-file: {groups_file}")
    groups = parse_groups(groups_file, encoding=encoding)
    entries_list = list_entries(source_dir, entries=entries)
    result["log"].append(f"[INFO] detected {len(entries_list)} items in source ({entries})")
    result["log"].append(f"[INFO] parsed {len(groups)} groups from text file")
    for name, is_dir in entries_list:
        company_base = normalize_company(name)
        if not company_base:
            result["miss_no_company"] += 1
            result["log"].append(f"[MISS] entry '{name}' -> no_company_extracted")
            continue
        group_name, reason = choose_group_for_company(company_base, groups, pattern)
        if not group_name:
            if reason == "not_found":
                result["miss_not_found"] += 1
            elif reason.startswith("ambiguous:"):
                result["miss_ambiguous"] += 1
            else:
                result["errors"] += 1
            result["log"].append(f"[MISS] entry '{name}' ({company_base}) -> {reason}")
            continue
        group_dir = os.path.join(source_dir, group_name)
        ensure_dir(group_dir)
        ok, state = move_entry(source_dir, name, group_dir)
        if ok and state == "moved":
            result["moved"] += 1
            result["log"].append(f"[MOVE] {os.path.join(source_dir, name)} -> {os.path.join(group_dir, name)}")
        elif ok and state == "already_exists":
            result["skipped_exist"] += 1
            result["log"].append(f"[SKIP] already exists in group: {os.path.join(group_dir, name)}")
        else:
            result["errors"] += 1
            result["log"].append(f"[WARN] source not found: {os.path.join(source_dir, name)}")
    result["log"].append(
        f"[SUMMARY] moved={result['moved']} skipped_exist={result['skipped_exist']} "
        f"miss_no_company={result['miss_no_company']} miss_not_found={result['miss_not_found']} "
        f"miss_ambiguous={result['miss_ambiguous']} errors={result['errors']}"
    )
    return result