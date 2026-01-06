import json
import os
import re
from collections import Counter

# 导入分类逻辑（来自 group_folders.py）
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
    "小学", "中学", "初中", "高中", "大学", "幼儿园", "托儿所"
]

def is_company_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(k in s for k in COMPANY_KEYWORDS)

def normalize_company(name: str):
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
    # 强后缀：通常是企业或机构的正式结尾
    strong_suffixes = [
        "股份有限公司", "有限责任公司", "有限公司", "责任有限公司", 
        "集团公司", "集团", "公司", "制造厂", "工厂", "厂",
        "中心", "研究所", "研究院", "医院", "学校", "幼儿园", "托儿所",
        "商行", "事务所", "合作社", "农场", "经营部", "工作室",
        "委员会", "协会", "党支部", "联合会", "超市", "便利店",
        "饭店", "酒店", "宾馆", "旅馆"
    ]
    
    # 弱后缀：可能是公司名一部分，也可能是描述词（如“网站”、“僵尸网”）
    weak_suffixes = [
        "局", "厅", "处", "署", "队", "站", "网", "店", "吧", "KTV", "会所", "棋牌", "俱乐部"
    ]
    
    # 优先寻找强后缀，并取最后出现的一个（以匹配最全的名称，如“集团股份有限公司”）
    best_match_end = -1
    
    for suffix in strong_suffixes:
        idx = s.rfind(suffix)
        if idx != -1:
            end_pos = idx + len(suffix)
            if end_pos > best_match_end:
                best_match_end = end_pos
    
    if best_match_end != -1:
        return s[:best_match_end].strip()
    
    # 如果没有强后缀，再尝试弱后缀
    for suffix in weak_suffixes:
        idx = s.rfind(suffix)
        if idx != -1:
            end_pos = idx + len(suffix)
            if end_pos > best_match_end:
                best_match_end = end_pos
                
    if best_match_end != -1:
        return s[:best_match_end].strip()
    
    return None

def parse_groups(groups_file: str):
    groups = {}
    current_group = "未分组"
    
    with open(groups_file, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            
            if is_company_line(line):
                if current_group not in groups:
                    groups[current_group] = []
                # 清理"（联系不上）"等标记
                cleaned_company = re.sub(r'[（(].*联系不上.*[）)]', '', line).strip()
                groups[current_group].append(cleaned_company)
            else:
                # 认为是镇街名称
                current_group = line
                if current_group not in groups:
                    groups[current_group] = []
    return groups

def get_company_to_group_map(groups: dict):
    company_to_group = {}
    for group_name, companies in groups.items():
        for company in companies:
            norm = normalize_company(company) or company
            company_to_group[norm] = group_name
    return company_to_group

import csv
from datetime import datetime
from openpyxl import Workbook

from openpyxl.styles import Font, Alignment, PatternFill

import argparse

def process_single_file(data_file: str):
    """处理单个文件并返回通报数据列表"""
    try:
        with open(data_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file {data_file}: {e}")
        return []

    # 跳过 HTTP 头
    start_idx = content.find("{")
    if start_idx == -1:
        # 尝试直接解析，可能没有 HTTP 头
        json_str = content
    else:
        json_str = content[start_idx:]
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复可能的截断 JSON
        if "}" in json_str:
            last_brace = json_str.rfind("}")
            try:
                data = json.loads(json_str[:last_brace+1])
            except:
                print(f"Failed to recover JSON in {data_file}")
                return []
        else:
            print(f"No valid JSON in {data_file}")
            return []
    
    return data.get("notificationPigeonholeData", [])

def run_statistics(input_path: str, groups_file: str):
    # 1. 加载分类信息
    groups = parse_groups(groups_file)
    company_to_group = get_company_to_group_map(groups)
    
    # 2. 收集所有文件中的通报数据
    notifications = []
    if os.path.isfile(input_path):
        notifications = process_single_file(input_path)
    elif os.path.isdir(input_path):
        print(f"正在扫描文件夹: {input_path}")
        for root, dirs, files in os.walk(input_path):
            for file in files:
                if file.endswith((".py", ".txt", ".csv", ".xlsx")):
                    continue
                file_path = os.path.join(root, file)
                print(f"  读取文件: {file}")
                notifications.extend(process_single_file(file_path))
    else:
        print(f"错误: 路径不存在 {input_path}")
        return

    if not notifications:
        print("未发现有效的通报数据。")
        return

    print(f"共加载 {len(notifications)} 条通报数据。")
    
    all_townships = [t for t in groups.keys() if t != "未分组" and t != "联系不上"]
    
    company_counts = Counter()
    township_counts = Counter()
    township_to_companies = {} 
    company_to_township = {} 
    
    unmapped_companies = set()

    # 3. 统计逻辑
    for item in notifications:
        # 严格只从 noticeTitle 提取企业名
        title = item.get("noticeTitle", "")
        if not title:
            continue
            
        company_name = normalize_company(title)
        
        # 如果从标题提取不出企业名，则跳过或记录（不再使用 model4）
        if not company_name:
            continue
        
        company_counts[company_name] += 1
        
        # 查找镇街
        township = company_to_group.get(company_name)
        if not township:
            for t in all_townships:
                if t in company_name:
                    township = t
                    break
        
        if not township:
            for c_norm, g in company_to_group.items():
                if company_name in c_norm or c_norm in company_name:
                    township = g
                    break
        
        if not township:
            unmapped_companies.add(company_name)
            township = "未知镇街"

        township_counts[township] += 1
        company_to_township[company_name] = township
        
        if township not in township_to_companies:
            township_to_companies[township] = Counter()
        township_to_companies[township][company_name] += 1

    # 4. 判断输出逻辑
    if unmapped_companies:
        print("\n" + "!"*60)
        print("发现未识别镇街的企业，请更新 1.txt 后再次运行脚本")
        print("!"*60)
        print("\n[待查询企业名单]")
        unmapped_list = sorted([(c, company_counts[c]) for c in unmapped_companies], key=lambda x: x[1], reverse=True)
        for i, (comp, count) in enumerate(unmapped_list, 1):
            print(f"{i}. {comp}")
        print("\n提示: 请将上述企业名称复制并分配到 1.txt 中的对应镇街下方。")
        return

    # 如果没有未识别的企业，则输出表格
    print("\n" + "="*60)
    print("所有企业已识别镇街，正在生成统计报表...")
    print("="*60)

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = os.path.dirname(os.path.abspath(input_path))
    output_dir = os.path.join(base_dir, "script")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    csv_file = f"statistics_report_{timestamp}.csv"
    xlsx_file = f"statistics_report_{timestamp}.xlsx"
    csv_path = os.path.join(output_dir, csv_file)
    xlsx_path = os.path.join(output_dir, xlsx_file)
    
    try:
        # 准备 Top 10 数据
        top_10_list = company_counts.most_common(10)
        top_10_data = []
        for i, (company, count) in enumerate(top_10_list, 1):
            township = company_to_township.get(company, "未知")
            top_10_data.append(f"Top {i}: {company} ({township}) - {count}次")

        # 写入 CSV
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["镇街/部门", "企业数量/企业名称", "通报次数", "全区 Top 10 企业排名"])
            sorted_townships = township_counts.most_common()
            
            max_rows = max(len(top_10_data), sum(len(township_to_companies[t]) + 1 for t in township_counts))
            
            # 由于 CSV 结构限制，我们逐行写入，并在前 10 行附带 Top 10 信息
            current_row = 0
            for township, total_count in sorted_townships:
                comp_list = township_to_companies[township].most_common()
                company_count = len(comp_list)
                
                # 汇总行
                top_col = top_10_data[current_row] if current_row < len(top_10_data) else ""
                writer.writerow([township, f"共通报 {company_count} 家企业", f"总计 {total_count} 次", top_col])
                current_row += 1
                
                # 企业行
                for comp, count in comp_list:
                    top_col = top_10_data[current_row] if current_row < len(top_10_data) else ""
                    writer.writerow(["", comp, count, top_col])
                    current_row += 1
            
            # 如果 Top 10 还没写完，继续写
            while current_row < len(top_10_data):
                writer.writerow(["", "", "", top_10_data[current_row]])
                current_row += 1
        
        # 写入 XLSX
        wb = Workbook()
        ws = wb.active
        if ws is None:
            raise RuntimeError("无法创建 Excel 工作表")
            
        ws.title = "通报统计报表"
        
        # 表头
        headers = ["镇街/部门", "企业数量/企业名称", "通报次数", "全区 Top 10 企业排名"]
        ws.append(headers)
        
        # 样式定义
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        township_font = Font(bold=True, color="000000")
        township_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
        top10_font = Font(bold=True, color="C00000") # 红色字体标识 Top 10
        center_aligned = Alignment(horizontal="center", vertical="center")
        left_aligned = Alignment(horizontal="left", vertical="center")
        
        # 设置表头样式
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_aligned
            
        # 写入主统计数据
        current_data_row = 2
        for township, total_count in sorted_townships:
            comp_list = township_to_companies[township].most_common()
            company_count = len(comp_list)
            
            # 写入镇街汇总行
            ws.cell(row=current_data_row, column=1, value=township)
            ws.cell(row=current_data_row, column=2, value=f"共通报 {company_count} 家企业")
            ws.cell(row=current_data_row, column=3, value=f"总计 {total_count} 次")
            
            # 设置汇总行样式
            for col in range(1, 4):
                cell = ws.cell(row=current_data_row, column=col)
                cell.font = township_font
                cell.fill = township_fill
                cell.alignment = left_aligned
            
            current_data_row += 1
            
            # 写入该镇街下的企业
            for comp, count in comp_list:
                ws.cell(row=current_data_row, column=2, value=comp)
                ws.cell(row=current_data_row, column=3, value=count)
                ws.cell(row=current_data_row, column=2).alignment = Alignment(indent=2)
                current_data_row += 1

        # 写入 Top 10 数据（放在第四列）
        for i, top_str in enumerate(top_10_data, 2):
            cell = ws.cell(row=i, column=4, value=top_str)
            cell.font = top10_font
            cell.alignment = left_aligned
        
        # 调整列宽
        ws.column_dimensions['A'].width = 15
        ws.column_dimensions['B'].width = 45
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 60
        
        wb.save(xlsx_path)
        
        wb.save(xlsx_path)
        
        print(f"\n✅ 报表生成成功:")
        print(f"   CSV:  {csv_path}")
        print(f"   XLSX: {xlsx_path}")
        
        print("\n[全区 Top 10 企业预览]")
        top_10 = company_counts.most_common(10)
        for i, (company, count) in enumerate(top_10, 1):
            township = company_to_township.get(company)
            print(f"{i:2}. {company:30} ({township}) | {count} 次")
            
    except Exception as e:
        print(f"生成报表失败: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="网信办通报数据分类统计脚本")
    parser.add_argument("input", nargs="?", default=r"c:\Users\lan1o\Desktop\wow\1", help="数据文件路径或包含文件的文件夹路径")
    parser.add_argument("--groups", default=r"c:\Users\lan1o\Desktop\wow\1.txt", help="分组定义文件路径")
    
    args = parser.parse_args()
    run_statistics(args.input, args.groups)
