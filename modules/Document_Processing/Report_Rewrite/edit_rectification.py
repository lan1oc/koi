#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
责令整改通知书编辑工具
自动替换公司名、漏洞类型和日期
"""

import sys
import io
import os
import re
import json
from datetime import datetime
from docx import Document
from pathlib import Path

# 设置Windows控制台编码为UTF-8
if sys.platform == 'win32':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except:
        pass


def get_config_file():
    """获取配置文件路径"""
    # 从脚本位置向上找到项目根目录
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent
    return project_root / "config.json"


def update_rectification_number(docx_file):
    """
    更新责令整改编号
    
    参数:
        docx_file: 生成的责令整改通知书路径
    
    返回:
        当前使用的编号
    """
    try:
        config_file = get_config_file()
        
        # 读取配置
        if not config_file.exists():
            print(f"  警告: 配置文件不存在: {config_file}")
            return None
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 获取当前编号
        if 'report_counters' not in config:
            config['report_counters'] = {
                'notification_number': 104,
                'rectification_number': 235,
                'year': datetime.now().year,
                'last_updated': ''
            }
        
        # 检查年份，如果是新年则重置编号
        current_year = datetime.now().year
        if 'year' not in config['report_counters'] or config['report_counters']['year'] != current_year:
            print(f"  🎊 检测到新年份: {current_year}，重置编号计数")
            config['report_counters']['notification_number'] = 1
            config['report_counters']['rectification_number'] = 1
            config['report_counters']['year'] = current_year
        
        current_number = config['report_counters']['rectification_number']
        
        # 打开文档并替换编号
        doc = Document(docx_file)
        replaced = False
        
        current_year = datetime.now().year
        
        for para in doc.paragraphs:
            para_text = para.text
            # 查找 鄞网办责字[YYYY]XXX号 的模式（支持任意年份）
            if '鄞网办责字' in para_text and '[' in para_text and ']' in para_text and '号' in para_text:
                # 提取当前的年份和编号
                year_match = re.search(r'\[(\d{4})\]', para_text)
                number_match = re.search(r'\](\d+)号', para_text)
                
                if year_match and number_match:
                    old_year = year_match.group(1)
                    old_number = number_match.group(1)
                    
                    # 对每个run进行替换
                    for run in para.runs:
                        # 替换年份中的数字（可能分散在多个runs中）
                        if old_year in run.text:
                            run.text = run.text.replace(old_year, str(current_year))
                            replaced = True
                        elif any(old_year[i:i+len(run.text)] == run.text for i in range(len(old_year)) if run.text and run.text.isdigit()):
                            # 处理年份被拆分的情况
                            for i in range(len(old_year)):
                                if old_year[i:i+len(run.text)] == run.text:
                                    run.text = str(current_year)[i:i+len(run.text)]
                                    replaced = True
                                    break
                        # 也处理包含'[202'这样的情况
                        elif '[' in run.text and any(c.isdigit() for c in run.text):
                            # 提取数字部分并替换
                            digits = ''.join(c for c in run.text if c.isdigit())
                            if digits and digits in old_year:
                                idx = old_year.index(digits)
                                new_digits = str(current_year)[idx:idx+len(digits)]
                                run.text = run.text.replace(digits, new_digits)
                                replaced = True
                        
                        # 替换编号
                        if old_number in run.text:
                            run.text = run.text.replace(old_number, str(current_number))
                            replaced = True
                
                # 找到目标段落后退出循环
                break
        
        if replaced:
            # 保存文档
            doc.save(docx_file)
            
            # 重新读取最新的配置文件，避免覆盖其他进程的更改
            with open(config_file, 'r', encoding='utf-8') as f:
                latest_config = json.load(f)
            
            # 只更新责令整改编号相关的字段，保留其他配置
            if 'report_counters' not in latest_config:
                latest_config['report_counters'] = {}
            
            latest_config['report_counters']['rectification_number'] = current_number + 1
            latest_config['report_counters']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(latest_config, f, ensure_ascii=False, indent=2)
            
            print(f"  ✓ 已更新责令整改编号: 鄞网办责字[{current_year}]{current_number}号")
            return current_number
        else:
            print(f"  警告: 未找到责令整改编号标记")
            return None
            
    except Exception as e:
        print(f"  警告: 更新责令整改编号失败: {str(e)}")
        return None


def extract_info_from_filename(filename):
    """
    从文件名中提取公司名和漏洞类型
    
    文件名格式示例：
    - 关于浙江格瓦拉数字科技有限公司所属Druid系统存在未授权访问安全漏洞通报.docx
    - 1760410609070舒普智能技术股份有限公司远程技术检查存在ecology远程命令执行漏洞.docx
    
    返回: (公司名, 漏洞描述)
    """
    # 去掉路径和扩展名
    basename = os.path.basename(filename)
    name_without_ext = basename.rsplit('.', 1)[0]
    
    # 去掉开头的数字
    name_clean = re.sub(r'^\d+', '', name_without_ext)
    
    # 提取公司名：尝试多种模式
    company_name = None
    
    # 模式1：关于...所属（最常见）
    company_match = re.search(r'关于(.+?)所属', name_clean)
    if company_match:
        company_name = company_match.group(1)
    else:
        # 模式2：关于...门户网站/官网/网站
        company_match = re.search(r'关于(.+?)(门户网站|官网|网站|平台|系统)', name_clean)
        if company_match:
            company_name = company_match.group(1)
        else:
            # 模式3：关于...存在（针对直接描述漏洞的文件名）
            company_match = re.search(r'关于(.+?)存在', name_clean)
            if company_match:
                company_name = company_match.group(1)
            else:
                # 模式4：关于...的
                company_match = re.search(r'关于(.+?)的', name_clean)
                if company_match:
                    company_name = company_match.group(1)
                else:
                    # 模式5：直接格式 - 公司名+技术检查/远程检查等
                    # 匹配：公司名（包含有限公司、股份有限公司等）+ 技术检查/远程检查等
                    company_match = re.search(r'^(.+?(?:有限公司|股份有限公司|集团|科技公司|科技))', name_clean)
                    if company_match:
                        company_name = company_match.group(1)
                    else:
                        # 模式6：尝试从"存在"之前提取公司名
                        company_match = re.search(r'^(.+?)(?:远程技术检查|技术检查|检查|远程|存在)', name_clean)
                        if company_match:
                            potential_company = company_match.group(1).strip()
                            # 验证是否包含公司关键词
                            if any(keyword in potential_company for keyword in ['有限公司', '股份有限公司', '集团', '科技']):
                                company_name = potential_company
    
    # 提取漏洞类型：尝试多种模式
    vuln_type = None
    
    # 模式1：查找"存在"和"通报"之间的内容（如：存在未授权访问安全漏洞）
    vuln_match = re.search(r'(存在.+?)通报', name_clean)
    if vuln_match:
        vuln_type = vuln_match.group(1)
    else:
        # 模式2：查找"系统"之后到"通报"之间的内容（如：MongDB未授权访问安全漏洞）
        vuln_match = re.search(r'系统(.+?)通报', name_clean)
        if vuln_match:
            content = vuln_match.group(1).strip()
            # 去掉开头的"的"字
            content = re.sub(r'^的', '', content)
            # 去掉可能的系统名称，只保留漏洞描述
            vuln_type = f"存在{content}"
        else:
            # 模式3：查找"网站"之后到"通报"之间的内容
            vuln_match = re.search(r'网站(.+?)通报', name_clean)
            if vuln_match:
                content = vuln_match.group(1).strip()
                # 去掉开头的"的"字
                content = re.sub(r'^的', '', content)
                vuln_type = f"存在{content}"
            else:
                # 模式4：查找"存在"到文件名结尾的内容（针对没有"通报"的文件名）
                vuln_match = re.search(r'(存在.+?)(?:\.docx|$)', name_clean)
                if vuln_match:
                    vuln_type = vuln_match.group(1)
                else:
                    # 模式5：查找"技术检查存在"模式
                    vuln_match = re.search(r'(?:远程技术检查|技术检查|检查)(存在.+?)(?:\.docx|$)', name_clean)
                    if vuln_match:
                        vuln_type = vuln_match.group(1)
                    else:
                        # 模式6：最后尝试，查找包含"漏洞"关键词的部分
                        vuln_match = re.search(r'([\u4e00-\u9fa5A-Za-z]+漏洞)', name_clean)
                        if vuln_match:
                            vuln_type = f"存在{vuln_match.group(1)}"
    
    return company_name, vuln_type


def extract_info_from_document(doc_file):
    """
    从通报文档中读取内容来提取信息（备用方案）
    """
    try:
        doc = Document(doc_file)
        # 读取文档内容，尝试从内容中提取信息
        full_text = '\n'.join([para.text for para in doc.paragraphs])
        
        # 从内容中提取公司名
        company_match = re.search(r'关于(.+?)所属', full_text)
        company_name = company_match.group(1) if company_match else None
        
        # 从内容中提取漏洞类型
        vuln_match = re.search(r'(存在.+?安全漏洞)', full_text)
        vuln_type = vuln_match.group(1) if vuln_match else None
        
        return company_name, vuln_type
    except Exception as e:
        print(f"从文档内容提取信息时出错: {e}")
        return None, None


def edit_rectification(report_file=None, template_file=None):
    """
    编辑责令整改通知书
    
    参数:
        report_file: 通报文档路径（如果为None，则自动查找）
        template_file: 责令整改模板路径（如果为None，则自动查找）
    """
    print("=" * 60)
    print("责令整改通知书编辑工具")
    print("=" * 60)
    
    # 如果未指定通报文件，自动查找
    if report_file is None:
        possible_reports = []
        for filename in os.listdir('.'):
            if filename.endswith('.docx'):
                # 排除模板和其他文件
                if 'Report_Template' not in filename and '授权委托书' not in filename and '模板' not in filename and '责令整改' not in filename:
                    # 优先选择以"关于"开头或包含"通报"的文件
                    if filename.startswith('关于') or '通报' in filename:
                        possible_reports.append(filename)
        
        if possible_reports:
            report_file = possible_reports[0]
            print(f"\n自动找到通报文档: {report_file}")
        else:
            print("\n未找到通报文档！")
            print("\n使用方法:")
            print("  方法1: 将通报文档放在当前目录，运行: python edit_rectification.py")
            print("  方法2: 指定文件: python edit_rectification.py <通报文档路径>")
            print("\n功能说明:")
            print("  1. 从通报文档中提取公司名和漏洞类型")
            print("  2. 在责令整改模板中替换公司名、漏洞类型和日期")
            print("  3. 生成责令整改通知书文件")
            print("\n重要提示:")
            print("  1. 模板文件会从 template 目录自动查找")
            print("  2. 模板文件必须是 .docx 格式")
            print("=" * 60)
            return False
    
    # 如果未指定模板文件，自动查找
    if template_file is None:
        template_candidates = []
        
        # 先在 template 目录查找
        if os.path.exists('Report_Template'):
            for filename in os.listdir('Report_Template'):
                if filename.endswith('.docx') and ('责令整改' in filename or '整改通知' in filename):
                    template_candidates.append(os.path.join('Report_Template', filename))
        
        # 如果 template 目录没找到，在当前目录查找
        if not template_candidates:
            for filename in os.listdir('.'):
                if filename.endswith('.docx') and ('责令整改' in filename or '整改通知' in filename):
                    template_candidates.append(filename)
        
        if not template_candidates:
            print("\n错误: 未找到责令整改模板文件！")
            print("  请确保以下位置之一存在责令整改模板文件：")
            print("    - template/责令整改*.docx")
            print("    - ./责令整改*.docx")
            return False
        
        template_file = template_candidates[0]
    
    # 从文件名提取信息
    company_name, vuln_type = extract_info_from_filename(report_file)
    
    # 如果从文件名提取失败，尝试从文档内容提取
    if not company_name or not vuln_type:
        print("从文件名提取信息失败，尝试从文档内容提取...")
        company_name_doc, vuln_type_doc = extract_info_from_document(report_file)
        if not company_name:
            company_name = company_name_doc
        if not vuln_type:
            vuln_type = vuln_type_doc
    
    if not company_name:
        print("\n警告: 无法提取公司名！")
        company_name = "【公司名】"
    
    if not vuln_type:
        print("\n警告: 无法提取漏洞类型！")
        vuln_type = "【漏洞类型】"
    
    # 获取当前日期
    today = datetime.now()
    current_date = f"{today.year}年{today.month}月{today.day}日"
    
    # 获取模板文件名（用于生成输出文件名）
    template_basename = os.path.basename(template_file)
    
    print(f"\n正在编辑责令整改通知书:")
    print(f"  模板文件: {template_file}")
    print(f"  公司名: {company_name}")
    print(f"  漏洞类型: {vuln_type}")
    print(f"  日期: {current_date}")
    print("=" * 60)
    
    try:
        # 加载模板文档
        doc = Document(template_file)
        
        replacements = 0
        
        # 遍历所有段落
        for para_idx, para in enumerate(doc.paragraphs, 1):
            original_text = para.text
            modified = False
            
            # 首先检查整个段落是否包含日期（因为日期可能被分成多个run）
            date_pattern = r'20\d{2}\s*年\s*\d+\s*月\s*\d+\s*日'
            if re.search(date_pattern, para.text):
                # 替换整个段落的日期
                new_para_text = re.sub(date_pattern, current_date, para.text)
                if new_para_text != para.text and para.runs:
                    # 清空所有run，只保留第一个
                    for run in para.runs[1:]:
                        run.text = ''
                    para.runs[0].text = new_para_text
                    modified = True
            else:
                # 如果没有日期，按run处理公司名和漏洞类型
                for run in para.runs:
                    run_text = run.text
                    new_text = run_text
                    
                    # 替换公司名（查找任何公司名模式）
                    if company_name and '有限公司' in run_text:
                        # 替换任何公司名为实际公司名
                        new_text = re.sub(r'[\u4e00-\u9fa5]+有限公司', company_name, new_text)
                    
                    # 替换漏洞类型
                    if vuln_type and ('存在' in run_text and '漏洞' in run_text):
                        # 替换任何漏洞描述为实际漏洞类型
                        # 去掉vuln_type中的"存在"和最后的"漏洞"字
                        vuln_clean = vuln_type.replace('存在', '').replace('安全漏洞', '').replace('漏洞', '')
                        new_text = re.sub(r'存在.+?漏洞', vuln_clean + '漏洞', new_text)
                    
                    # 如果有修改，更新run的文本
                    if new_text != run_text:
                        run.text = new_text
                        modified = True
            
            if modified:
                replacements += 1
                print(f"  段落 {para_idx} 已替换:")
                print(f"    原文: {original_text}")
                print(f"    新文: {para.text}")
                print()
        
        # 生成输出文件名（保持模板原文件名）
        output_file = template_basename
        
        # 保存文档
        doc.save(output_file)
        
        # 更新责令整改编号
        rectification_number = update_rectification_number(output_file)
        
        print("=" * 60)
        print(f"✓ 成功生成责令整改通知书!")
        print(f"  输出文件: {output_file}")
        print(f"  替换次数: {replacements} 个段落")
        if rectification_number:
            print(f"  文号: 鄞网办责字[2025]{rectification_number}号")
        print("=" * 60)
        
        return True
        
    except FileNotFoundError as e:
        print(f"\n错误: 找不到文件: {e}")
        return False
    except ValueError as e:
        print(f"\n错误: {e}")
        return False
    except Exception as e:
        print(f"\n编辑文档时出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    report_file = None
    
    if len(sys.argv) >= 2:
        # 如果提供了参数，使用参数
        report_file = sys.argv[1]
    
    # 执行编辑
    success = edit_rectification(report_file)
    
    if success:
        print("\n编辑完成！")
    else:
        print("\n编辑失败，请检查错误信息。")
        sys.exit(1)

