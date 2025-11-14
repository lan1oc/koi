#!/usr/bin/env python3
"""
Group company folders by headings defined in a text file.

Usage examples (Windows):
  python script/group_folders.py --source-dir "D:\\企业根目录" --pattern exact --dry-run
  python script/group_folders.py --source-dir "D:\\企业根目录" --pattern contains

By default, the groups file points to:
  c:\\Users\\lan1o\\Desktop\\wow\\1.txt

This script will:
  - Parse groups from the text file (each heading line is a group; company lines contain keywords like "公司", "集团", "股份").
  - Scan immediate subfolders in --source-dir, match them to company names.
  - Create group folders under --dest-dir (default: same as --source-dir).
  - Move matched company folders into the corresponding group folder.

Safety:
  - Use --dry-run first to preview actions.
  - Ambiguous or missing matches are reported and skipped.
"""

import argparse
import os
import sys
import shutil
from typing import Dict, List, Set, Tuple


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
    current_group: str = None
    with open(groups_file, "r", encoding=encoding) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                # Blank line, ignore
                continue
            if is_company_line(line):
                if not current_group:
                    # Company encountered before any group heading; place under "未分组"
                    current_group = "未分组"
                    groups.setdefault(current_group, [])
                groups.setdefault(current_group, []).append(line)
            else:
                # New group heading
                current_group = line
                groups.setdefault(current_group, [])
    return groups


def list_immediate_subdirs(path: str) -> Set[str]:
    names: Set[str] = set()
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            names.add(entry)
    return names


def find_match(company: str, folder_names: Set[str], mode: str) -> Tuple[str, str]:
    """
    Return (matched_name, reason). matched_name is None if not found or ambiguous.
    mode: "exact" or "contains"
    """
    if mode == "exact":
        if company in folder_names:
            return company, "exact"
        return None, "not_found"
    # contains mode
    # Prefer exact first
    if company in folder_names:
        return company, "exact"
    candidates = [name for name in folder_names if company in name or name in company]
    if len(candidates) == 1:
        return candidates[0], "contains"
    if len(candidates) == 0:
        return None, "not_found"
    return None, f"ambiguous:{'|'.join(candidates)}"


def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def move_folder(src_dir: str, name: str, dest_group_dir: str, dry_run: bool) -> bool:
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


def main():
    parser = argparse.ArgumentParser(description="Group company folders by headings from a text file")
    parser.add_argument("--source-dir", required=True, help="Directory containing company folders (top-level)")
    parser.add_argument("--dest-dir", default=None, help="Destination root for group folders (default: source-dir)")
    parser.add_argument("--groups-file", default=r"c:\\Users\\lan1o\\Desktop\\wow\\1.txt", help="Path to grouping text file")
    parser.add_argument("--encoding", default="utf-8", help="Text file encoding")
    parser.add_argument("--pattern", choices=["exact", "contains"], default="exact", help="Matching strategy for folder names")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without moving folders")

    args = parser.parse_args()

    source_dir = os.path.abspath(args.source_dir)
    dest_dir = os.path.abspath(args.dest_dir or source_dir)
    groups_file = args.groups_file
    encoding = args.encoding
    mode = args.pattern
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
    folder_names = list_immediate_subdirs(source_dir)

    print(f"[INFO] detected {len(folder_names)} folders in source")
    print(f"[INFO] parsed {len(groups)} groups from text file")

    total_moves = 0
    for group, companies in groups.items():
        if not companies:
            print(f"[INFO] group '{group}' has no companies; skipping folder creation")
            continue

        group_dir = os.path.join(dest_dir, group)
        ensure_dir(group_dir)
        print(f"[GROUP] {group} -> {group_dir}")

        for company in companies:
            matched, reason = find_match(company, folder_names, mode)
            if not matched:
                print(f"[MISS] company '{company}' -> {reason}")
                continue
            ok = move_folder(source_dir, matched, group_dir, dry_run=dry_run)
            if ok:
                total_moves += 1
                # Update folder_names to reflect move
                folder_names.discard(matched)

    print(f"[SUMMARY] moves planned: {total_moves}; dry-run={dry_run}")
    if dry_run:
        print("[NOTE] Run again without --dry-run to apply changes.")


if __name__ == "__main__":
    main()