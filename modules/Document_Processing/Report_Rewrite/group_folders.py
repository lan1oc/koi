import os
import shutil
import re
import sqlite3
from pathlib import Path
from modules.utils.resource_path import get_app_dir

COMPANY_KEYWORDS = [
    "公司", "集团", "股份",
    "有限责任公司", "有限公司",
    "制造厂", "工厂", "厂",
    "店", "中心", "研究所", "研究院", "医院", "学校",
    "商行", "事务所", "合作社", "农场", "工作室",
    "局", "厅", "处", "署", "队", "站", "网",
    "超市", "经营部", "便利店", "饭店", "酒店", "宾馆", "旅馆",
    "网吧", "俱乐部", "棋牌", "会所", "KTV", "吧",
    "委员会", "协会", "党支部", "联合会",
    "小学", "中学", "初中", "高中", "大学", "幼儿园", "托儿所",
    "基金会"
]

def is_company_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(k in s for k in COMPANY_KEYWORDS)

# 用于检测"联系不上"标记的正则（支持中英文括号、各种后缀备注）
UNREACHABLE_PATTERN = re.compile(r'[（(].*联系不上.*[）)]')

def extract_unreachable_tag(line: str) -> tuple[str, bool]:
    """
    检测行中是否包含"联系不上"标记，并返回去除标记后的公司名称。
    
    Returns:
        tuple: (清理后的公司名称, 是否标记了联系不上)
    """
    match = UNREACHABLE_PATTERN.search(line)
    if match:
        # 移除"联系不上"标记部分，保留公司名称
        cleaned = line[:match.start()].strip()
        return cleaned, True
    return line.strip(), False

def parse_groups(groups_file: str, encoding: str = "utf-8"):
    groups = {}
    current_group = "未分组"
    last_line_was_empty = True
    
    # 特殊分组名称
    UNREACHABLE_GROUP = "联系不上"
    
    with open(groups_file, "r", encoding=encoding) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                last_line_was_empty = True
                continue
            
            if last_line_was_empty:
                current_group = line
                groups.setdefault(current_group, [])
                last_line_was_empty = False
            elif is_company_line(line):
                # 检测是否标记了"联系不上"
                cleaned_company, is_unreachable = extract_unreachable_tag(line)
                
                if is_unreachable:
                    # 标记了"联系不上"的公司，放入特殊分组
                    groups.setdefault(UNREACHABLE_GROUP, []).append(cleaned_company)
                else:
                    # 正常公司，放入当前分组
                    groups.setdefault(current_group, []).append(line)
                last_line_was_empty = False
            else:
                current_group = line
                groups.setdefault(current_group, [])
                last_line_was_empty = False
                
    return groups

def _get_db_path() -> Path:
    try:
        base_dir = get_app_dir()
    except Exception:
        base_dir = Path(__file__).resolve().parents[3]
    return Path(base_dir) / "enterprise_classification.db"

def parse_groups_from_db() -> dict:
    db_path = _get_db_path()
    if not db_path.exists():
        return {}
    groups = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='groups'"
        )
        if not cursor.fetchone():
            conn.close()
            return {}
        cursor.execute("SELECT id, name FROM groups ORDER BY sort_order, id")
        group_rows = cursor.fetchall()
        for group_id, group_name in group_rows:
            cursor.execute(
                "SELECT name FROM companies WHERE group_id = ? ORDER BY sort_order, id",
                (group_id,),
            )
            # 清理企业名称中的{...}标签
            companies = []
            for row in cursor.fetchall():
                raw_name = row[0]
                # 去除{...}及其内容，例如 "中铁建城市开发有限公司{国企}" -> "中铁建城市开发有限公司"
                clean_name = re.sub(r'\{.*?\}', '', raw_name).strip()
                if clean_name:
                    companies.append(clean_name)
            groups[group_name] = companies
        conn.close()
        return groups
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return {}

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
    """从名称中提取企业全称（处理专项、关于等前缀，并精确匹配后缀）。"""
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
        "委员会", "协会", "党支部", "联合会", "基金会", "超市", "便利店",
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

def _has_disposal_template(target_dir: str) -> bool:
    try:
        for entry in os.listdir(target_dir):
            if entry.lower().endswith('.docx') and ('处置' in entry and '模板' in entry):
                return True
    except Exception:
        pass
    return False

def _pick_disposal_template() -> str | None:
    project_root = Path(__file__).resolve().parents[3]
    tmpl_dir = project_root / 'Report_Template'
    candidates: list[Path] = []
    if tmpl_dir.exists():
        for p in tmpl_dir.glob('*.docx'):
            if '处置' in p.name and '模板' in p.name:
                candidates.append(p)
        if not candidates:
            for p in tmpl_dir.glob('*处置*.docx'):
                candidates.append(p)
    if not candidates:
        fallback = project_root / 'Report_Template' / '处置文件模板.docx'
        if fallback.exists():
            candidates.append(fallback)
    return str(candidates[0]) if candidates else None

def _clean_template_name(name: str) -> str:
    m = re.match(r'^(\d+)(.*)$', name)
    return m.group(2) if m else name

def ensure_disposal_template(company_dir: str) -> None:
    if not os.path.isdir(company_dir):
        return
    if _has_disposal_template(company_dir):
        return
    template_path = _pick_disposal_template()
    if not template_path:
        return
    target_name = _clean_template_name(os.path.basename(template_path))
    dest_path = os.path.join(company_dir, target_name)
    if os.path.exists(dest_path):
        return
    try:
        shutil.copy2(template_path, dest_path)
    except Exception:
        pass

def preprocess_loose_files(source_dir: str, log: list) -> dict:
    """
    预处理松散文件：自动创建公司文件夹并将文件移入
    
    Args:
        source_dir: 源目录
        log: 日志列表
        
    Returns:
        dict: 统计信息 {created_folders, moved_files, skipped}
    """
    stats = {
        "created_folders": 0,
        "moved_files": 0,
        "skipped": 0
    }
    
    log.append("[PREPROCESS] 开始预处理松散文件...")
    
    # 获取目录中的所有条目
    try:
        entries = os.listdir(source_dir)
    except Exception as e:
        log.append(f"[PREPROCESS ERROR] 无法读取目录: {e}")
        return stats
    
    # 只处理文件（不是文件夹）
    for entry in entries:
        full_path = os.path.join(source_dir, entry)
        
        # 跳过文件夹
        if os.path.isdir(full_path):
            continue
        
        # 从文件名提取公司名称
        company_name = normalize_company(entry)
        
        if not company_name:
            stats["skipped"] += 1
            log.append(f"[PREPROCESS SKIP] 文件 '{entry}' 无法提取公司名称")
            continue
        
        # 创建公司文件夹（如果不存在）
        company_folder = os.path.join(source_dir, company_name)
        folder_created = False
        
        if not os.path.exists(company_folder):
            try:
                os.makedirs(company_folder, exist_ok=True)
                stats["created_folders"] += 1
                folder_created = True
                log.append(f"[PREPROCESS CREATE] 创建文件夹: {company_name}")
            except Exception as e:
                log.append(f"[PREPROCESS ERROR] 创建文件夹失败 '{company_name}': {e}")
                stats["skipped"] += 1
                continue
        
        # 移动文件到公司文件夹
        dest_path = os.path.join(company_folder, entry)
        
        if os.path.exists(dest_path):
            log.append(f"[PREPROCESS SKIP] 文件已存在: {dest_path}")
            stats["skipped"] += 1
            continue
        
        try:
            shutil.move(full_path, dest_path)
            stats["moved_files"] += 1
            action = "新建文件夹并移动" if folder_created else "移动"
            log.append(f"[PREPROCESS MOVE] {action}文件 '{entry}' -> {company_name}/")
        except Exception as e:
            log.append(f"[PREPROCESS ERROR] 移动文件失败 '{entry}': {e}")
            stats["skipped"] += 1
    
    log.append(
        f"[PREPROCESS SUMMARY] 创建文件夹={stats['created_folders']} "
        f"移动文件={stats['moved_files']} 跳过={stats['skipped']}"
    )
    
    return stats

def run_grouping(source_dir: str, groups_file: str | None = None, entries: str = "both", pattern: str = "exact", encoding: str = "utf-8", groups_source: str = "file"):
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
    result["log"].append(f"[INFO] source-dir: {source_dir}")
    if groups_source == "db":
        result["log"].append("[INFO] groups-source: database")
    else:
        result["log"].append(f"[INFO] groups-file: {groups_file}")
    
    # ========== 预处理：自动创建公司文件夹 ==========
    preprocess_stats = preprocess_loose_files(source_dir, result["log"])
    result["preprocessed_folders"] = preprocess_stats["created_folders"]
    result["preprocessed_files"] = preprocess_stats["moved_files"]
    
    # ========== 主分类流程 ==========
    if groups_source == "db":
        groups = parse_groups_from_db()
        if not groups:
            result["errors"] += 1
            result["log"].append("[ERROR] groups-source database is empty")
            return result
    else:
        if not groups_file or not os.path.isfile(groups_file):
            result["errors"] += 1
            result["log"].append(f"[ERROR] --groups-file not found: {groups_file}")
            return result
        groups = parse_groups(groups_file, encoding=encoding)
    entries_list = list_entries(source_dir, entries=entries)
    result["log"].append(f"[INFO] detected {len(entries_list)} items in source ({entries})")
    result["log"].append(f"[INFO] parsed {len(groups)} groups")
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
            # 未分组成功时，若该项为企业文件夹，则确保其中存在处置模板
            if is_dir:
                ensure_disposal_template(os.path.join(source_dir, name))
            continue
        group_dir = os.path.join(source_dir, group_name)
        ensure_dir(group_dir)
        ok, state = move_entry(source_dir, name, group_dir)
        if ok and state == "moved":
            result["moved"] += 1
            result["log"].append(f"[MOVE] {os.path.join(source_dir, name)} -> {os.path.join(group_dir, name)}")
            # 若移动的是企业文件夹，则确保其中存在处置模板
            dest_entry_path = os.path.join(group_dir, name)
            if os.path.isdir(dest_entry_path):
                ensure_disposal_template(dest_entry_path)
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
    
    # 收集当前目录下所有公司-镇街对应关系（遍历所有镇街文件夹）
    result["company_group_list"] = collect_all_company_groups(source_dir)
    
    # 检查是否所有企业都已分类
    all_classified, unclassified = check_all_classified(source_dir)
    result["all_classified"] = all_classified
    result["unclassified"] = unclassified
    
    return result


def check_all_classified(source_dir: str) -> tuple[bool, list]:
    """
    检查是否所有企业都已分类到镇街文件夹
    
    判断逻辑：根目录下是否还存在企业文件夹
    （企业文件夹 = 能用 normalize_company 提取出公司名的文件夹）
    
    Returns:
        tuple: (是否全部分类完成, 未分类的企业列表)
    """
    unclassified = []
    
    try:
        for entry_name in os.listdir(source_dir):
            entry_path = os.path.join(source_dir, entry_name)
            
            if not os.path.isdir(entry_path):
                continue
            
            # 如果能提取出公司名，说明这是企业文件夹，还在根目录下未分类
            company_name = normalize_company(entry_name)
            if company_name:
                unclassified.append(company_name)
    except Exception as e:
        print(f"[ERROR] check_all_classified: {e}")
    
    return len(unclassified) == 0, unclassified


def get_soe_companies() -> set[str]:
    """
    获取所有标记为国企的企业列表（返回去除了{国企}标签的清洗名称）
    """
    db_path = _get_db_path()
    if not db_path.exists():
        return set()
    
    soe_companies = set()
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 查找包含"{国企}"标签的企业
        cursor.execute(
            "SELECT name FROM companies WHERE name LIKE '%{国企}%'"
        )
        
        for row in cursor.fetchall():
            raw_name = row[0]
            # 去除{...}标签得到清洗后的名称
            clean_name = re.sub(r'\{.*?\}', '', raw_name).strip()
            if clean_name:
                soe_companies.add(clean_name)
                
        conn.close()
    except Exception as e:
        print(f"[ERROR] get_soe_companies: {e}")
        try:
            conn.close()
        except:
            pass
            
    return soe_companies


def collect_all_company_groups(source_dir: str) -> list:
    """
    遍历目录，收集所有公司-镇街对应关系（只收集已分类到镇街文件夹下的公司）
    
    结构假设：source_dir/镇街文件夹/公司文件夹
    
    Returns:
        list: [(公司名, 镇街名), ...]
    """
    company_group_list = []
    
    # 已知的镇街名称列表（不包含公司后缀的通常就是镇街）
    known_townships = set()
    
    try:
        # 第一遍：识别所有镇街文件夹
        for entry_name in os.listdir(source_dir):
            entry_path = os.path.join(source_dir, entry_name)
            
            if not os.path.isdir(entry_path):
                continue
            
            # 如果文件夹名不能提取出公司名，认为是镇街文件夹
            if not normalize_company(entry_name):
                known_townships.add(entry_name)
        
        # 第二遍：遍历镇街文件夹，收集公司
        for township_name in known_townships:
            township_path = os.path.join(source_dir, township_name)
            
            for company_name in os.listdir(township_path):
                company_path = os.path.join(township_path, company_name)
                
                # 只处理文件夹
                if not os.path.isdir(company_path):
                    continue
                
                # 提取公司名
                company_base = normalize_company(company_name)
                if company_base:
                    company_group_list.append((company_base, township_name))
    
    except Exception as e:
        print(f"[ERROR] collect_all_company_groups: {e}")
    
    return company_group_list
