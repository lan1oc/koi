#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网信办特供UI组件 - 批量处理工具

自动处理压缩包/文件夹中的通报文档，生成所需的三个文件
"""

import os
import sys
import json
import zipfile
import shutil
import re
from collections import defaultdict
from pathlib import Path
from typing import List

# 减少Qt字体和DirectWrite警告
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts.warning=false;qt.qpa.fonts=false'
os.environ['QT_QPA_PLATFORM'] = 'windows:fontengine=freetype'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'RoundPreferFloor'

from PySide6.QtCore import QThread, Signal, Qt, QEventLoop, QFileSystemWatcher
from PySide6.QtGui import QPixmap, QColor, QIntValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, 
    QLineEdit, QTextEdit, QLabel, QFileDialog, 
    QMessageBox, QProgressBar, QScrollArea, QComboBox, QCheckBox,
    QTabWidget, QSplitter, QSizePolicy, QDialog
)
from modules.ui.message_box_helper import show_warning, show_information, show_critical

# 复测相关工具（已移动到模块目录）
from modules.Document_Processing.retest.word_vulnerability_scanner import WordVulnerabilityScanner
from modules.Document_Processing.retest.vulnerability_batch_scanner import VulnerabilityRetestScanner
from modules.Document_Processing.retest.retest_report_generator import RetestReportGenerator

# 导入主题管理器
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from modules.ui.styles.theme_manager import ThemeManager

def is_notification_file(filename: str) -> bool:
    """
    判断文件名是否为通报文档

    识别规则：
    1. 包含"关于"或"通报"
    2. 包含"存在"和"漏洞"
    3. 包含"所属"和"存在"（模式A/D/H：企业所属系统存在漏洞）
    4. 包含公司关键词和"漏洞"
    5. 包含"技术检查"和"漏洞"
    """
    if '关于' in filename or '通报' in filename:
        return True
    if '存在' in filename and '漏洞' in filename:
        return True
    if '所属' in filename and '存在' in filename:
        return True
    if any(kw in filename for kw in ['有限公司', '股份有限公司', '集团', '科技']) and '漏洞' in filename:
        return True
    if '技术检查' in filename and '漏洞' in filename:
        return True
    return False

# 不支持自动复测的漏洞类型（需要人工验证）
# 仅拦截「必须交互/爆破/业务上下文」才能验证的类型；未授权访问、目录/路径遍历、任意文件读取
# 已改为由扫描器对通报 URL 与站点根常见路径做轻量复测（见 vulnerability_batch_scanner）。
NON_TESTABLE_VULN_TYPES = {
    'sql注入', 'SQL注入', 'SQL Injection', 'sql',
    '弱口令', '弱密码', 'Weak Password', 'weak password',
    'XSS', 'xss', 'Cross-site Scripting', '跨站脚本',
    '命令注入', 'Command Injection', 'command injection',
    '文件上传', 'File Upload', 'file upload',
    '敏感信息泄露', 'Information Disclosure',
    '暴力破解', 'Brute Force',
    'CSRF', 'csrf', 'Cross-Site Request Forgery',
}

try:
    from modules.ui.dialogs.manual_fix_dialog import ManualFixDialog
except Exception:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))
    from modules.ui.dialogs.manual_fix_dialog import ManualFixDialog


class PDFConvertWorker(QThread):
    """PDF转换工作线程"""
    progress_updated = Signal(str)  # 详细日志信息
    progress_changed = Signal(int, str)  # 进度百分比, 状态文字
    finished_signal = Signal(bool, str)
    
    def __init__(self, target_path: str):
        super().__init__()
        self.target_path = target_path
        self.should_stop = False
        
    def stop(self):
        """停止转换"""
        self.should_stop = True
        
    def run(self):
        """执行PDF转换"""
        try:
            self.progress_updated.emit("开始搜索Word文档...")
            self.progress_changed.emit(0, "搜索中...")
            
            # 递归查找通报文档（只转换通报文档）
            word_files = []
            for root, dirs, files in os.walk(self.target_path):
                if self.should_stop:
                    return
                for file in files:
                    if file.endswith('.docx') and not file.startswith('~$'):
                        # 排除模板和已生成的文件
                        if any(kw in file for kw in ['模板', '授权委托书', '责令整改', '处置']):
                            continue
                        
                        # 检查是否是通报文档
                        if is_notification_file(file):
                            file_path = os.path.join(root, file)
                            # 检查是否已有对应的PDF文件
                            pdf_path = file_path.replace('.docx', '.pdf')
                            if not os.path.exists(pdf_path):
                                word_files.append(file_path)
            
            if not word_files:
                self.progress_updated.emit("未找到需要转换的Word文档")
                self.finished_signal.emit(True, "未找到需要转换的Word文档")
                return
                
            self.progress_updated.emit(f"找到 {len(word_files)} 个Word文档需要转换")
            
            # 转换文档
            converted_count = 0
            failed_count = 0
            
            for i, word_file in enumerate(word_files):
                if self.should_stop:
                    return
                    
                try:
                    self.progress_updated.emit(f"正在转换: {os.path.basename(word_file)}")
                    progress = int((i / len(word_files)) * 100)
                    self.progress_changed.emit(progress, f"转换中 ({i+1}/{len(word_files)})")
                    
                    # 调用PDF转换
                    pdf_path = word_file.replace('.docx', '.pdf')
                    success = self._convert_to_pdf(word_file, pdf_path)
                    
                    if success:
                        # 转换成功，删除原Word文档
                        try:
                            os.remove(word_file)
                            converted_count += 1
                            self.progress_updated.emit(f"✓ 转换成功并删除原文档: {os.path.basename(word_file)}")
                        except Exception as delete_error:
                            converted_count += 1  # 转换成功了，只是删除失败
                            self.progress_updated.emit(f"✓ 转换成功，但删除原文档失败: {os.path.basename(word_file)} - {str(delete_error)}")
                    else:
                        failed_count += 1
                        self.progress_updated.emit(f"✗ 转换失败: {os.path.basename(word_file)}")
                        # 检查PDF文件是否存在以提供更多信息
                        if os.path.exists(pdf_path):
                            self.progress_updated.emit(f"  注意: PDF文件已存在但转换函数返回失败")
                        else:
                            self.progress_updated.emit(f"  PDF文件未生成: {pdf_path}")
                        
                except Exception as e:
                    failed_count += 1
                    self.progress_updated.emit(f"✗ 转换出错: {os.path.basename(word_file)} - {str(e)}")
                    # 提供更多调试信息
                    self.progress_updated.emit(f"  错误类型: {type(e).__name__}")
                    if hasattr(e, 'errno'):
                        if hasattr(e, 'errno') and isinstance(e, OSError):
                            self.progress_updated.emit(f"  错误代码: {e.errno}")
            
            self.progress_changed.emit(100, "转换完成")
            
            # 完成总结
            summary = f"转换完成！成功: {converted_count}, 失败: {failed_count}"
            self.progress_updated.emit(summary)
            self.finished_signal.emit(True, summary)
            
        except Exception as e:
            error_msg = f"PDF转换过程出错: {str(e)}"
            self.progress_updated.emit(error_msg)
            self.finished_signal.emit(False, error_msg)
    
    def _convert_to_pdf(self, word_path: str, pdf_path: str) -> bool:
        """转换Word文档为PDF - 直接调用转换函数"""
        try:
            # 导入转换函数
            script_dir = Path(__file__).parent
            sys.path.insert(0, str(script_dir))
            from doc_pdf import convert_with_word_com
            
            # 准备文件路径
            input_file = Path(word_path)
            output_file = Path(pdf_path)
            
            # 确保输出目录存在
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            self.progress_updated.emit(f"开始转换: {input_file.name}")
            
            # 调用转换函数
            files_to_convert = [(input_file, output_file)]
            num_converted, num_skipped, failures = convert_with_word_com(
                files=files_to_convert,
                overwrite=True
            )
            
            if failures:
                # 有转换失败
                for failed_file, reason in failures:
                    self.progress_updated.emit(f"转换失败: {failed_file.name} - {reason}")
                return False
            elif num_converted > 0:
                # 转换成功
                self.progress_updated.emit(f"转换成功: {output_file.name}")
                return True
            else:
                # 被跳过
                self.progress_updated.emit(f"文件被跳过: {input_file.name}")
                return False
                
        except ImportError as e:
            self.progress_updated.emit(f"导入错误: 无法导入转换模块 - {str(e)}")
            return False
        except Exception as e:
            self.progress_updated.emit(f"转换异常: {str(e)}")
            return False


class BatchReportProcessWorker(QThread):
    """批量处理通报文档的工作线程"""
    progress_updated = Signal(str)  # 详细日志信息
    progress_changed = Signal(int, str)  # 进度百分比, 状态文字
    finished_signal = Signal(bool, str)
    manual_processing_list = Signal(list)  # 编辑失败的文档列表
    # 人工校正流程：主线程弹窗请求、以及用户响应回传
    manual_fix_required = Signal(str, str)  # (message, target_dir)
    resume_after_manual_fix = Signal(bool)  # 用户是否确认已修正
    
    def __init__(self, target_path: str, script_dir: Path, template_dir: Path, auto_group: bool = False):
        super().__init__()
        self.target_path = target_path
        self.script_dir = script_dir
        self.template_dir = template_dir
        self.auto_group = auto_group
        # 脚本文件都在Report_Rewrite子目录中
        self.rewrite_script = script_dir / "Report_Rewrite" / "rewrite_report.py"
        self.authorization_script = script_dir / "Report_Rewrite" / "edit_authorization.py"
        self.rectification_script = script_dir / "Report_Rewrite" / "edit_rectification.py"
        self.disposal_script = script_dir / "Report_Rewrite" / "edit_disposal.py"
        
        # 获取国企名单
        try:
            from modules.Document_Processing.Report_Rewrite import group_folders as gf
            self.soe_companies = gf.get_soe_companies()
        except Exception as e:
            print(f"获取国企名单失败: {e}")
            self.soe_companies = set()
        
        # 进度跟踪
        self.total_reports = 0
        self.processed_reports = 0
        
        # 手动处理列表
        self.manual_processing_files = []

        # 人工校正等待事件
        self._manual_fix_event_loop = None
        self._manual_fix_result = False
        self.resume_after_manual_fix.connect(self._on_manual_fix_resolved)
        
        # 查找模板文件
        self.rewrite_template = self._find_template("通报模板")
        self.auth_template = self._find_template("授权委托书")
        self.rect_template = self._find_template("责令整改")
        self.disposal_template = self._find_template("处置")
    
    def _find_template(self, keyword: str) -> str:
        """查找模板文件"""
        if not self.template_dir.exists():
            self.progress_updated.emit(f"⚠️ 模板目录不存在: {self.template_dir}")
            return ""
        
        for file in self.template_dir.glob("*.docx"):
            if keyword in file.name:
                self.progress_updated.emit(f"✅ 找到模板: {file.name}")
                return str(file.absolute())
        
        self.progress_updated.emit(f"⚠️ 未找到包含'{keyword}'的模板文件")
        return ""

    def _on_manual_fix_resolved(self, proceed: bool):
        """接收主线程返回的人为校正结果，并退出等待循环"""
        self._manual_fix_result = proceed
        if self._manual_fix_event_loop is not None:
            try:
                self._manual_fix_event_loop.quit()
            except Exception:
                pass
    
    def _count_reports(self, directory: Path) -> int:
        """统计目录中的通报文档数量（包括子目录和压缩包内）"""
        count = 0
        try:
            # 递归查找所有.docx文件
            for docx_file in directory.rglob("*.docx"):
                # 跳过临时文件和已生成的文件
                if docx_file.name.startswith('~$'):
                    continue
                
                # 统计以数字开头的通报文档，或者以"关于"开头的原始通报
                if docx_file.name[0].isdigit() and '通报' in docx_file.name:
                    count += 1
                elif docx_file.name.startswith('关于') and '通报' in docx_file.name:
                    count += 1
                elif is_notification_file(docx_file.name):
                    count += 1
        except Exception as e:
            self.progress_updated.emit(f"⚠️ 统计文件时出错: {str(e)}")
        return count
    
    def _update_progress(self, status: str = "", step_progress: int = 0):
        """更新进度条
        
        Args:
            status: 状态文字
            step_progress: 当前步骤的进度（0-100），用于单个文档内的步骤进度
        """
        if self.total_reports > 0:
            # 基础进度20%，剩余80%由文件处理完成度决定
            base_progress = 20
            
            # 每个文档占80%进度的一部分
            per_report_progress = 80 / self.total_reports
            
            # 已完成文档的进度
            completed_progress = self.processed_reports * per_report_progress
            
            # 当前文档的步骤进度（步骤进度 * 单个文档的进度权重）
            current_step_progress = (step_progress / 100) * per_report_progress
            
            # 总进度 = 基础20% + 已完成文档进度 + 当前文档步骤进度
            percentage = int(base_progress + completed_progress + current_step_progress)
            
            if not status:
                status = f"📝 处理中 ({self.processed_reports + 1}/{self.total_reports})"
            
            self.progress_changed.emit(percentage, status)
        else:
            # 如果total_reports为0，显示0%而不是50%
            self.progress_changed.emit(0, status if status else "等待开始...")
    
    def run(self):
        try:
            target = Path(self.target_path)
            archive_to_delete = None  # 记录需要删除的压缩包
            
            if not target.exists():
                self.finished_signal.emit(False, "目标路径不存在")
                return
            
            # 第一步：初始化
            self.progress_changed.emit(5, "🔍 正在扫描文件...")
            
            # 如果是压缩包，先解压
            if target.is_file() and target.suffix.lower() in ['.zip', '.rar', '.7z']:
                self.progress_updated.emit(f"📦 检测到压缩包: {target.name}")
                self.progress_changed.emit(10, "📦 正在解压压缩包...")
                archive_to_delete = target  # 记录压缩包路径
                target, should_delete = self.extract_archive(target)
                if target is None:
                    self.finished_signal.emit(False, "解压失败")
                    return
                # 如果不需要删除（比如解压失败），清空标记
                if not should_delete:
                    archive_to_delete = None

            # 自动分类（如果启用）
            if self.auto_group and target.is_dir():
                self.progress_updated.emit("🗂️ 正在执行自动分类...")
                self.progress_changed.emit(12, "🗂️ 正在自动分类...")
                try:
                    from modules.Document_Processing.Report_Rewrite import group_folders as gf
                    # 使用默认配置：数据库源、both entries、exact pattern
                    result = gf.run_grouping(str(target), groups_source="db")
                    
                    self.progress_updated.emit(f"  ✅ 分类完成: 移动 {result['moved']} 个, 跳过 {result['skipped_exist']} 个")
                    if result['errors'] > 0:
                        self.progress_updated.emit(f"  ⚠️ 分类过程有 {result['errors']} 个错误")
                    
                    # 记录未分类的企业
                    if not result['all_classified']:
                        unclassified_count = len(result['unclassified'])
                        self.progress_updated.emit(f"  ⚠️ 还有 {unclassified_count} 个企业未分类")
                        
                except Exception as e:
                    self.progress_updated.emit(f"  ❌ 自动分类失败: {str(e)}")
                    # 分类失败不阻断后续流程，只是打印错误
            
            # 统计总文件数
            self.progress_changed.emit(15, "📊 正在统计文件数量...")
            self.total_reports = self._count_reports(target)
            self.progress_updated.emit(f"📊 共发现 {self.total_reports} 个通报文档")
            
            # 如果是文件夹，递归处理
            if target.is_dir():
                self.progress_changed.emit(20, f"📁 开始处理 {self.total_reports} 个文档...")
                self.progress_updated.emit(f"📁 开始处理文件夹: {target.name}")
                self.process_directory(target)
            else:
                self.progress_updated.emit("⚠️ 只支持文件夹或压缩包")
                self.finished_signal.emit(False, "不支持的文件类型")
                return
            
            # 处理完成后，删除原压缩包
            if archive_to_delete and archive_to_delete.exists():
                try:
                    self.progress_updated.emit(f"🗑️ 删除原压缩包: {archive_to_delete.name}")
                    archive_to_delete.unlink()
                    self.progress_updated.emit(f"✅ 压缩包已删除")
                except Exception as e:
                    self.progress_updated.emit(f"⚠️ 删除压缩包失败: {str(e)}")
            
            # 所有企业已完成独立的PDF转换，无需统一转换
            self.progress_updated.emit("✅ 所有企业的PDF转换已在各自处理过程中完成")
            self.progress_changed.emit(100, "✅ 批量处理完成")
            
            # 发出手动处理列表信号
            if self.manual_processing_files:
                self.manual_processing_list.emit(self.manual_processing_files)
            
            self.finished_signal.emit(True, "所有处理完成")
            
        except Exception as e:
            # 即使出错也发出手动处理列表
            if self.manual_processing_files:
                self.manual_processing_list.emit(self.manual_processing_files)
            self.finished_signal.emit(False, f"处理错误: {str(e)}")
    
    def extract_archive(self, archive_path: Path) -> tuple:
        """
        解压压缩包
        返回: (解压后的目录, 是否需要删除压缩包)
        """
        try:
            # 只支持ZIP格式（其他格式需要额外库）
            if archive_path.suffix.lower() != '.zip':
                self.progress_updated.emit(f"⚠️ 暂不支持 {archive_path.suffix} 格式，请先手动解压")
                return None, False
            
            # 创建以压缩包名命名的文件夹
            extract_dir = archive_path.parent / archive_path.stem
            
            # 如果文件夹已存在，先删除
            if extract_dir.exists():
                self.progress_updated.emit(f"⚠️ 文件夹已存在，将覆盖: {extract_dir.name}")
                shutil.rmtree(extract_dir)
            
            # 创建文件夹
            extract_dir.mkdir(exist_ok=True)
            
            self.progress_updated.emit(f"📂 解压到: {extract_dir.name}/")
            
            # 解压文件
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            self.progress_updated.emit(f"✅ 解压完成")
            
            # 返回解压目录和需要删除压缩包的标记
            return extract_dir, True
            
        except Exception as e:
            self.progress_updated.emit(f"❌ 解压失败: {str(e)}")
            return None, False
    
    def process_directory(self, directory: Path, processed_folders=None):
        """递归处理文件夹"""
        if processed_folders is None:
            processed_folders = set()
        
        # 避免重复处理同一个文件夹
        dir_absolute = directory.absolute()
        if dir_absolute in processed_folders:
            self.progress_updated.emit(f"⏭️ 跳过已处理的文件夹: {directory.name}")
            return
        processed_folders.add(dir_absolute)
        
        try:
            self.progress_updated.emit(f"🔍 正在扫描: {directory.name}")
            
            # 先查找并处理所有压缩包
            zip_files = list(directory.glob("*.zip"))
            if zip_files:
                self.progress_updated.emit(f"📦 在 {directory.name} 中找到 {len(zip_files)} 个压缩包")
                for zip_file in zip_files:
                    self.progress_updated.emit(f"📦 开始处理压缩包: {zip_file.name}")
                    extract_dir, should_delete = self.extract_archive(zip_file)
                    if extract_dir and extract_dir.is_dir():
                        self.progress_updated.emit(f"📂 解压完成，进入文件夹: {extract_dir.name}")
                        # 递归处理解压后的文件夹
                        self.process_directory(extract_dir, processed_folders)
                        # 删除压缩包
                        if should_delete and zip_file.exists():
                            try:
                                zip_file.unlink()
                                self.progress_updated.emit(f"🗑️ 已删除压缩包: {zip_file.name}")
                            except Exception as e:
                                self.progress_updated.emit(f"⚠️ 删除压缩包失败: {str(e)}")
                # 处理完压缩包后，不再处理当前目录的文件，直接返回
                return
            
            # 查找所有通报文档（只处理原始通报，以数字开头的文件）
            report_files = []
            all_docx = list(directory.glob("*.docx"))
            
            self.progress_updated.emit(f"📄 在 {directory.name} 中找到 {len(all_docx)} 个 .docx 文件")
            
            # 只在当前目录查找，不递归
            for item in all_docx:
                self.progress_updated.emit(f"  检查文件: {item.name}")
                
                # 排除Word临时文件（~$开头）
                if item.name.startswith('~$'):
                    self.progress_updated.emit(f"    ⏭️ 跳过（Word临时文件）")
                    continue
                
                # 排除模板和已生成的文件
                if any(kw in item.name for kw in ['模板', '授权委托书', '责令整改', '处置']):
                    self.progress_updated.emit(f"    ⏭️ 跳过（模板或已生成文件）")
                    continue
                
                # 检查是否是通报文档
                is_notif = is_notification_file(item.name)
                self.progress_updated.emit(f"    🔍 调试: 所属={('所属' in item.name)}, 存在={('存在' in item.name)}, 结果={is_notif}")
                if not is_notif:
                    self.progress_updated.emit(f"    ⏭️ 跳过（文件名不符合规则）")
                    continue
                
                # 检查是否以数字开头
                if not item.name[0].isdigit():
                    # 不以数字开头，需要重命名
                    self.progress_updated.emit(f"    🔄 检测到原始通报，添加随机数前缀...")
                    
                    # 生成随机数前缀（10位数字）
                    import random
                    import time
                    random_prefix = str(int(time.time() * 1000))[-10:]  # 使用时间戳的后10位
                    
                    # 新文件名
                    new_name = f"{random_prefix}{item.name}"
                    new_path = item.parent / new_name
                    
                    try:
                        # 重命名文件
                        item.rename(new_path)
                        self.progress_updated.emit(f"    ✅ 重命名: {item.name} → {new_name}")
                        item = new_path  # 更新item为新路径
                    except Exception as e:
                        self.progress_updated.emit(f"    ❌ 重命名失败: {str(e)}")
                        continue
                
                self.progress_updated.emit(f"    ✅ 识别为原始通报文档")
                report_files.append(item)
            
            if report_files:
                self.progress_updated.emit(f"📋 在 {directory.name} 中共找到 {len(report_files)} 个通报文档")
                
                # 按企业分组通报文档
                company_groups = {}
                for report_file in report_files:
                    # 获取当前企业名称
                    current_company = report_file.parent.name
                    
                    # 尝试从文件名提取公司名（作为备选）
                    if current_company == report_file.parent.parent.name: # 可能是未分类的情况
                        from modules.Document_Processing.Report_Rewrite import group_folders as gf
                        extracted_name = gf.normalize_company(report_file.name)
                        if extracted_name:
                            current_company = extracted_name
                    
                    if current_company not in company_groups:
                        company_groups[current_company] = []
                    company_groups[current_company].append(report_file)
                
                # 处理每个企业的文档批次
                for company_name, files in company_groups.items():
                    self.process_report_batch(files, company_name)
            else:
                self.progress_updated.emit(f"⚠️ 在 {directory.name} 中未找到符合条件的通报文档")
            
            # 递归处理子文件夹
            subdirs = [d for d in directory.iterdir() if d.is_dir() and not d.name.startswith('.')]
            if subdirs:
                self.progress_updated.emit(f"📁 在 {directory.name} 中找到 {len(subdirs)} 个子文件夹")
                for subdir in subdirs:
                    self.process_directory(subdir, processed_folders)
                
        except Exception as e:
            self.progress_updated.emit(f"❌ 处理文件夹时出错: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())

    def _find_latest_rectification_doc(self) -> Path | None:
        """查找当前目录最新的责令整改通知书docx文件（类内工具方法）。"""
        try:
            candidates = list(Path.cwd().glob("责令整改*.docx"))
            if not candidates:
                return None
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None

    def _rectification_doc_has_placeholders(self, doc_path: Path) -> bool:
        """检测责令整改文档是否仍包含占位符，需要人工处理。"""
        try:
            from docx import Document
            doc = Document(str(doc_path))
            full_text = "\n".join([p.text for p in doc.paragraphs])
            return ("【公司名】" in full_text) or ("【漏洞类型】" in full_text)
        except Exception:
            return False

    def process_report_batch(self, report_files: list[Path], company_name: str):
        """处理同一家企业的通报文档批次"""
        if not report_files:
            return
        try:
            self.progress_updated.emit("=" * 80)
            self.progress_updated.emit(f"🏢 处理企业: {company_name} (共 {len(report_files)} 个文档)")
            self.progress_updated.emit("-" * 80)
            
            # 切换到文档所在目录
            original_dir = os.getcwd()
            work_dir = report_files[0].parent
            os.chdir(work_dir)
            
            # 1. 通报改写 (0-20%) - 逐个处理
            self.progress_updated.emit("🔄 步骤1/5: 通报改写")
            self._update_progress("🔄 步骤1/5: 通报改写", step_progress=0)
            
            if self.rewrite_template:
                import shutil
                template_name = Path(self.rewrite_template).name
                local_template = Path.cwd() / template_name
                if not local_template.exists():
                    shutil.copy2(self.rewrite_template, local_template)
                    self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
            
            collected_vulns = []
            
            for report_file in report_files:
                self.progress_updated.emit(f"  📄 改写文档: {report_file.name}")
                rewrite_result = self.run_rewrite_script(report_file)
                
                # 收集漏洞信息
                from modules.Document_Processing.Report_Rewrite.edit_rectification import extract_info_from_filename
                _, vuln = extract_info_from_filename(str(report_file))
                if vuln:
                    collected_vulns.append(vuln)
                
                if not rewrite_result['success']:
                    self.progress_updated.emit(f"⚠️ 通报改写失败：{rewrite_result['skip_reason']}")
                    # 即使改写失败，也记录备份文件信息
                    if rewrite_result.get('backup_file'):
                        backup_path = Path(rewrite_result['backup_file'])
                        if backup_path.exists():
                            self.progress_updated.emit(f"  ✅ 备份文件已保存: {backup_path.name}")
                else:
                    # 检查是否需要手动处理
                    if rewrite_result['needs_manual_processing']:
                        manual_info = {
                            'file': str(report_file),
                            'reason': rewrite_result['skip_reason'],
                            'backup_file': rewrite_result['backup_file'],
                            'output_file': rewrite_result['output_file']
                        }
                        self.manual_processing_files.append(manual_info)
                        self.progress_updated.emit(f"  ⚠️ 需要手动处理：{rewrite_result['skip_reason']}")
                        if rewrite_result['backup_file']:
                            backup_path = Path(rewrite_result['backup_file'])
                            if backup_path.exists():
                                self.progress_updated.emit(f"  ✅ 备份文件已保存: {backup_path.name}")
                    else:
                        if rewrite_result.get('backup_file'):
                            backup_path = Path(rewrite_result['backup_file'])
                            if backup_path.exists():
                                self.progress_updated.emit(f"  ✅ 通报文件已保存: {backup_path.name}")
            
            # 等待文件系统释放
            import time
            import gc
            gc.collect()
            time.sleep(1.0)
            self.progress_updated.emit("  ⏳ 等待文件系统释放...")
            
            # 删除通报模板
            if self.rewrite_template:
                template_name = Path(self.rewrite_template).name
                local_template = Path.cwd() / template_name
                if local_template.exists():
                    try:
                        local_template.unlink()
                        self.progress_updated.emit(f"  🗑️ 已删除通报模板: {template_name}")
                    except Exception as e:
                        self.progress_updated.emit(f"  ⚠️ 删除模板失败: {str(e)}")
            
            self._update_progress("✅ 步骤1/5完成", step_progress=20)
            
            # 2. 生成授权委托书 (20-40%) - 批量只需一份
            self.progress_updated.emit("🔄 步骤2/5: 生成授权委托书")
            self._update_progress("🔄 步骤2/5: 生成授权委托书", step_progress=20)
            
            if self.auth_template:
                template_name = Path(self.auth_template).name
                local_template = Path.cwd() / template_name
                if not local_template.exists():
                    shutil.copy2(self.auth_template, local_template)
                    self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
            
            # 确定参数
            target_report = report_files[0]
            override_name = None
            if len(report_files) > 1:
                override_name = f"{company_name}存在多个漏洞"
                self.progress_updated.emit(f"  ℹ️ 检测到多个通报，授权委托书将使用名称: {override_name}")
            
            self.run_authorization_script(target_report, override_name=override_name)
            self._update_progress("✅ 步骤2/5完成", step_progress=40)
            
            # 3. 生成责令整改通知书 (40-60%) - 批量只需一份
            is_soe = company_name in self.soe_companies
            if is_soe:
                self.progress_updated.emit(f"  🏢 检测到国企: {company_name}，跳过生成责令整改通知书")
                self.progress_updated.emit("⏭️ 步骤3/5: 跳过责令整改通知书 (国企)")
            else:
                self.progress_updated.emit("🔄 步骤3/5: 生成责令整改通知书")
                self._update_progress("🔄 步骤3/5: 生成责令整改通知书", step_progress=40)
                
                if self.rect_template:
                    template_name = Path(self.rect_template).name
                    local_template = Path.cwd() / template_name
                    if not local_template.exists():
                        shutil.copy2(self.rect_template, local_template)
                        self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
                
                # 删除临时文件
                for temp_file in Path.cwd().glob("~$*"):
                    try:
                        temp_file.unlink()
                    except:
                        pass
                
                combined_vulns = None
                if len(report_files) > 1 and collected_vulns:
                    # 去重并合并
                    unique_vulns = sorted(list(set(collected_vulns)))
                    combined_vulns = "、".join(unique_vulns)
                    # 确保以漏洞或风险结尾
                    if not combined_vulns.endswith("漏洞") and not combined_vulns.endswith("风险"):
                         combined_vulns += "漏洞"
                    self.progress_updated.emit(f"  ℹ️ 检测到多个通报，合并漏洞类型: {combined_vulns}")
                elif len(report_files) == 1 and collected_vulns:
                    combined_vulns = collected_vulns[0]
                
                self.run_rectification_script(target_report, company_name=company_name, vuln_type=combined_vulns)
                
                # 检查人工校正
                latest_rect = self._find_latest_rectification_doc()
                if latest_rect and self._rectification_doc_has_placeholders(latest_rect):
                    self.progress_updated.emit("  ❌ 自动化改写失败：公司名或漏洞类型未识别，需手动改写。")
                    msg = (
                        "自动化改写出错，请手动改写。\n"
                        "可能原因：公司名未识别正确或漏洞类型为None。\n"
                        "请在生成的‘责令整改’文档中修正后，点击‘改成成功’继续。"
                    )
                    try:
                        self.manual_fix_required.emit(msg, str(Path.cwd()))
                    except Exception as e:
                        self.progress_updated.emit(f"  ⚠️ 弹窗通知失败：{e}")
                    self._manual_fix_event_loop = QEventLoop()
                    self._manual_fix_result = False
                    self._manual_fix_event_loop.exec()

                    if self._manual_fix_result:
                        self.progress_updated.emit("  ✅ 已确认手动改写完成，进入PDF转换…")
                        # 提前进行PDF转换
                        self._convert_current_docs_to_pdf()
                        self._update_progress("✅ 步骤5/5完成", step_progress=95)
                        self.progress_updated.emit(f"✅ {company_name} 处理完成")
                        self.processed_reports += len(report_files)
                        self._update_progress(f"📝 已完成 {self.processed_reports}/{self.total_reports} 个文档", step_progress=100)
                        os.chdir(original_dir)
                        return
                    else:
                        self.progress_updated.emit("  ⏭️ 用户取消继续，已跳过PDF转换。")
            
            self._update_progress("✅ 步骤3/5完成", step_progress=60)
            
            # 4. 处置文件 (60-80%)
            disposal_exists = list(Path.cwd().glob("*处置*.docx"))
            disposal_pdf_exists = list(Path.cwd().glob("*处置*.pdf"))
            
            if not disposal_exists and not disposal_pdf_exists:
                self.progress_updated.emit("🔄 步骤4/5: 处理处置文件")
                self._update_progress("🔄 步骤4/5: 处理处置文件", step_progress=60)
                if self.disposal_template:
                    if self.run_disposal_script(str(self.disposal_template)):
                        pass
                else:
                    self.progress_updated.emit("  ⚠️ 未找到处置文件模板，跳过此步骤")
            else:
                self.progress_updated.emit("⏭️ 步骤4/5: 处置文件已存在，跳过")
                
            self._update_progress("✅ 步骤4/5完成", step_progress=80)
            
            # 5. PDF转换
            self.progress_updated.emit("🔄 步骤5/5: 转换为PDF")
            self._update_progress("🔄 步骤5/5: 转换为PDF", step_progress=80)
            
            pdf_success = self._convert_current_docs_to_pdf()
            if pdf_success:
                self.progress_updated.emit("✅ PDF转换完成")
            else:
                self.progress_updated.emit("⚠️ PDF转换部分失败，请检查日志")
            
            self._update_progress("✅ 步骤5/5完成", step_progress=95)
            
            self.progress_updated.emit(f"✅ {company_name} 处理完成")
            
            # 更新总进度
            self.processed_reports += len(report_files)
            self._update_progress(f"📝 已完成 {self.processed_reports}/{self.total_reports} 个文档", step_progress=100)
            
            os.chdir(original_dir)
            
        except Exception as e:
            self.progress_updated.emit(f"❌ 处理 {company_name} 时出错: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            self.processed_reports += len(report_files)
            self._update_progress(f"⚠️ 已处理 {self.processed_reports}/{self.total_reports} 个文档 (部分失败)", step_progress=100)
    
    def convert_to_pdf(self):
        """将当前目录下的Word文档转换为PDF（只转换完整处理的文档）"""
        try:
            from .doc_pdf import convert_with_word_com
            
            # 找到当前目录下的所有Word文档（排除模板和需要手动处理的文档）
            current_dir = Path.cwd()
            docx_files = []
            
            # 要转换的文件名模式（排除通报文档，只转换授权委托书和责令整改通知书）
            patterns = [
                # "关于*.docx",  # 改写后的通报 - 根据用户要求不转换PDF
                "授权委托书*.docx",  # 授权委托书
                "责令整改*.docx",  # 责令整改通知书
            ]
            
            # 获取需要手动处理的文件列表（这些文件不应该转换PDF）
            manual_files = set()
            for manual_info in self.manual_processing_files:
                if manual_info.get('output_file'):
                    manual_files.add(Path(manual_info['output_file']).name)
            
            for pattern in patterns:
                for file in current_dir.glob(pattern):
                    if not file.name.startswith('~$'):  # 排除临时文件
                        # 排除备份文件
                        if ('.clean_backup.docx' in file.name or 
                            '.final_backup.docx' in file.name or 
                            '.backup.docx' in file.name):
                            self.progress_updated.emit(f"  ⏭️ 跳过备份文件: {file.name}")
                            continue
                        # 跳过需要手动处理的文件
                        if file.name in manual_files:
                            self.progress_updated.emit(f"  ⏭️ 跳过需要手动处理的文档: {file.name}")
                            continue
                        docx_files.append(file)
            
            if not docx_files:
                self.progress_updated.emit("  ⚠️ 未找到需要转换的Word文档（或所有文档都需要手动处理）")
                return
            
            # 构建文件映射（源文件 -> PDF文件）
            file_map = []
            for docx_file in docx_files:
                pdf_file = docx_file.with_suffix('.pdf')
                file_map.append((docx_file, pdf_file))
            
            self.progress_updated.emit(f"  📄 找到 {len(file_map)} 个文档需要转换")
            
            # 调用PDF转换函数
            converted, skipped, failures = convert_with_word_com(file_map, overwrite=True)
            
            # 删除转换成功的Word文件并收集PDF文件
            converted_files = []
            failed_files = set(src for src, reason in failures)
            
            for docx_file, pdf_file in file_map:
                if docx_file not in failed_files and pdf_file.exists():
                    try:
                        docx_file.unlink()
                        converted_files.append(docx_file.name)
                        self.progress_updated.emit(f"  🗑️ 已删除原Word文件: {docx_file.name}")
                    except Exception as e:
                        self.progress_updated.emit(f"  ⚠️ 删除Word文件失败 {docx_file.name}: {str(e)}")
            
            # 输出结果
            if converted > 0:
                self.progress_updated.emit(f"  ✅ 成功转换 {converted} 个文档")
                if converted_files:
                    self.progress_updated.emit(f"  🗑️ 已删除 {len(converted_files)} 个原Word文件")
            if skipped > 0:
                self.progress_updated.emit(f"  ⏭️ 跳过 {skipped} 个文档")
            if failures:
                for src, reason in failures:
                    self.progress_updated.emit(f"  ❌ 转换失败 {src.name}: {reason}")
            
            # 保留Word文档作为备份，不删除
            if converted > 0:
                self.progress_updated.emit(f"  📁 Word文档已保留作为备份，PDF转换完成")
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ PDF转换出错: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
    
    def _convert_current_docs_to_pdf(self) -> bool:
        """转换当前目录下的授权委托书和责令整改通知书为PDF"""
        try:
            from .doc_pdf import convert_with_word_com
            
            # 找到当前目录下需要转换的Word文档
            current_dir = Path.cwd()
            docx_files = []
            
            # 要转换的文件名模式（只转换授权委托书和责令整改通知书）
            patterns = [
                "授权委托书*.docx",  # 授权委托书
                "责令整改*.docx",  # 责令整改通知书
            ]
            
            for pattern in patterns:
                for file in current_dir.glob(pattern):
                    if not file.name.startswith('~$'):  # 排除临时文件
                        # 排除备份文件
                        if ('.clean_backup.docx' in file.name or 
                            '.final_backup.docx' in file.name or 
                            '.backup.docx' in file.name):
                            continue
                        docx_files.append(file)
            
            if not docx_files:
                self.progress_updated.emit("  ⚠️ 当前目录未找到需要转换的文档")
                return True  # 没有文件需要转换也算成功
            
            # 构建文件映射（源文件 -> PDF文件）
            file_map = []
            for docx_file in docx_files:
                pdf_file = docx_file.with_suffix('.pdf')
                file_map.append((docx_file, pdf_file))
            
            self.progress_updated.emit(f"  📄 转换 {len(file_map)} 个文档为PDF")
            
            # 调用PDF转换函数
            converted, skipped, failures = convert_with_word_com(file_map, overwrite=True)
            
            # 删除转换成功的Word文件
            failed_files = set(src for src, reason in failures)
            
            for docx_file, pdf_file in file_map:
                if docx_file not in failed_files and pdf_file.exists():
                    try:
                        docx_file.unlink()
                        self.progress_updated.emit(f"  🗑️ 已删除原Word文件: {docx_file.name}")
                    except Exception as e:
                        self.progress_updated.emit(f"  ⚠️ 删除Word文件失败 {docx_file.name}: {str(e)}")
            
            # 输出结果
            if converted > 0:
                self.progress_updated.emit(f"  ✅ 成功转换 {converted} 个文档为PDF")
            if skipped > 0:
                self.progress_updated.emit(f"  ⏭️ 跳过 {skipped} 个文档")
            if failures:
                for src, reason in failures:
                    self.progress_updated.emit(f"  ❌ 转换失败 {src.name}: {reason}")
            
            # 如果有失败的转换，返回False
            return len(failures) == 0
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ PDF转换出错: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            return False
    
    def run_rewrite_script(self, report_file: Path) -> dict:
        """运行改写脚本并解析返回值"""
        try:
            # 直接调用rewrite_report函数而不是通过subprocess
            # 直接调用rewrite_report函数而不是通过subprocess
            from modules.Document_Processing.Report_Rewrite.rewrite_report import rewrite_report
            
            result = rewrite_report(str(report_file), start_para=1)
            
            return result
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ 改写脚本执行错误: {str(e)}")
            return {
                'success': False,
                'output_file': None,
                'backup_file': None,
                'needs_manual_processing': False,
                'skip_reason': f'执行错误: {str(e)}'
            }
    
    def run_authorization_script(self, report_file: Path, **kwargs) -> bool:
        """运行授权委托书生成脚本 - 直接调用函数"""
        try:
            # 直接调用函数而不是通过subprocess
            # 直接调用函数而不是通过subprocess
            from modules.Document_Processing.Report_Rewrite.edit_authorization import edit_authorization
            
            # 调用函数并获取结果
            self.progress_updated.emit(f"  🔧 调用 edit_authorization 函数...")
            result = edit_authorization(str(report_file), **kwargs)
            
            if result:
                self.progress_updated.emit(f"  ✅ 授权委托书生成成功")
            else:
                self.progress_updated.emit(f"  ⚠️ 授权委托书生成失败")
            
            return result
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ 授权委托书脚本执行错误: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            return False
    
    def run_rectification_script(self, report_file: Path, **kwargs) -> bool:
        """运行责令整改通知书生成脚本 - 直接调用函数"""
        try:
            # 直接调用函数而不是通过subprocess
            # 直接调用函数而不是通过subprocess
            from modules.Document_Processing.Report_Rewrite.edit_rectification import edit_rectification
            
            # 调用函数并获取结果
            self.progress_updated.emit(f"  🔧 调用 edit_rectification 函数...")
            result = edit_rectification(str(report_file), **kwargs)
            
            if result:
                self.progress_updated.emit(f"  ✅ 责令整改通知书生成成功")
            else:
                self.progress_updated.emit(f"  ⚠️ 责令整改通知书生成失败")
            
            return result
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ 责令整改脚本执行错误: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            return False
    
    def run_disposal_script(self, template_file: str) -> bool:
        """运行处置文件处理脚本 - 直接调用函数"""
        try:
            # 直接调用函数而不是通过subprocess
            # 直接调用函数而不是通过subprocess
            from modules.Document_Processing.Report_Rewrite.edit_disposal import process_disposal
            
            # 调用函数并获取结果
            self.progress_updated.emit(f"  🔧 调用 process_disposal 函数...")
            result = process_disposal(template_file)
            
            if result:
                self.progress_updated.emit(f"  ✅ 处置文件处理成功")
            else:
                self.progress_updated.emit(f"  ⚠️ 处置文件处理失败")
            
            return result
            
        except Exception as e:
            self.progress_updated.emit(f"  ❌ 处置文件脚本执行错误: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            return False
    
    def _auto_convert_specific_docs_to_pdf(self, target_dir: Path):
        """
        自动转换责令整改和授权委托书为PDF
        """
        try:
            # 查找责令整改和授权委托书文档
            target_keywords = ["责令整改", "授权委托书"]
            converted_count = 0
            
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    if file.endswith('.docx'):
                        # 检查文件名是否包含目标关键字
                        for keyword in target_keywords:
                            if keyword in file:
                                word_path = Path(root) / file
                                pdf_path = word_path.with_suffix('.pdf')
                                
                                # 如果PDF已存在，跳过
                                if pdf_path.exists():
                                    self.progress_updated.emit(f"  ⏭️ PDF已存在，跳过: {file}")
                                    continue
                                
                                self.progress_updated.emit(f"  📄 正在转换: {file}")
                                
                                # 调用doc_pdf.py进行转换，并删除原文件
                                if self._convert_single_doc_to_pdf(str(word_path), str(pdf_path), delete_original=True):
                                    self.progress_updated.emit(f"  ✅ 转换成功: {file}")
                                    converted_count += 1
                                else:
                                    self.progress_updated.emit(f"  ❌ 转换失败: {file}")
                                break  # 找到匹配的关键字后跳出内层循环
            
            if converted_count > 0:
                self.progress_updated.emit(f"📄 自动PDF转换完成，成功转换 {converted_count} 个文档")
            else:
                self.progress_updated.emit(f"📄 未找到需要转换的责令整改或授权委托书文档")
                
        except Exception as e:
            self.progress_updated.emit(f"❌ 自动PDF转换失败: {str(e)}")
    
    def _convert_single_doc_to_pdf(self, word_path: str, pdf_path: str, delete_original: bool = False) -> bool:
        """
        转换单个Word文档为PDF - 直接调用转换函数
        
        Args:
            word_path: Word文档路径
            pdf_path: PDF输出路径
            delete_original: 转换成功后是否删除原文件
        """
        try:
            # 导入转换函数
            sys.path.insert(0, str(self.script_dir))
            from doc_pdf import convert_with_word_com
            
            # 准备文件路径
            input_file = Path(word_path)
            output_file = Path(pdf_path)
            
            # 确保输出目录存在
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            self.progress_updated.emit(f"    开始转换: {input_file.name}")
            
            # 调用转换函数
            files_to_convert = [(input_file, output_file)]
            num_converted, num_skipped, failures = convert_with_word_com(
                files=files_to_convert,
                overwrite=True
            )
            
            if failures:
                # 有转换失败
                for failed_file, reason in failures:
                    self.progress_updated.emit(f"    转换失败: {failed_file.name} - {reason}")
                return False
            elif num_converted > 0:
                 # 转换成功
                 self.progress_updated.emit(f"    转换成功: {output_file.name}")
                 
                 # 如果需要删除原文件
                 if delete_original:
                     try:
                         input_file.unlink()  # 删除原文件
                         self.progress_updated.emit(f"    已删除原文件: {input_file.name}")
                     except Exception as delete_error:
                         self.progress_updated.emit(f"    删除原文件失败: {input_file.name} - {str(delete_error)}")
                 
                 return True
            else:
                # 被跳过
                self.progress_updated.emit(f"    文件被跳过: {input_file.name}")
                return False
                
        except ImportError as e:
            self.progress_updated.emit(f"    导入错误: 无法导入转换模块 - {str(e)}")
            return False
        except Exception as e:
            self.progress_updated.emit(f"    转换错误: {str(e)}")
            return False


class ReportRewriteUI(QWidget):
    """网信办特供UI组件 - 批量处理"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 使用ThemeManager来管理主题
        self.theme_manager = ThemeManager()
        
        # 连接主题变更信号
        self.theme_manager.dark_mode_changed.connect(self.on_theme_changed)
        
        # 获取脚本路径 - 指向Document_Processing目录以便导入Report_Rewrite模块
        self.script_dir = Path(__file__).parent
        
        # 获取模板目录路径（支持开发和打包环境）
        try:
            from modules.utils.resource_path import get_report_template_dir
            self.template_dir = get_report_template_dir()
        except ImportError:
            # 回退到原始方式
            project_root = Path(__file__).parent.parent.parent
            self.template_dir = project_root / "Report_Template"
        
        # 配置文件监控
        self.config_watcher = QFileSystemWatcher(self)
        self.config_watcher.fileChanged.connect(self.on_config_file_changed)
        
        self.init_ui()
        
        # 启动后添加文件监控
        config_file = self.get_config_file()
        if config_file.exists():
            self.config_watcher.addPath(str(config_file))

    def get_config_file(self):
        """获取配置文件路径"""
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe，配置文件在exe同级目录
            return Path(sys.executable).parent / "config.json"
        else:
            # 开发环境：从脚本位置向上找到项目根目录
            script_dir = Path(__file__).resolve().parent
            project_root = script_dir.parent.parent
            return project_root / "config.json"

    def load_config(self):
        """加载配置到UI"""
        try:
            config_file = self.get_config_file()
            if not config_file.exists():
                return
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if 'report_counters' in config:
                counters = config['report_counters']
                if 'notification_number' in counters:
                    self.notification_edit.setText(str(counters['notification_number']))
                
                if 'rectification_number' in counters:
                    self.rectification_edit.setText(str(counters['rectification_number']))

                if hasattr(self, "unavailable_numbers_edit") and hasattr(self, "unavailable_target_combo"):
                    # 兼容旧字段 unavailable_numbers：若新字段不存在则回填两套
                    old = counters.get("unavailable_numbers", None)
                    notif_nums = counters.get("unavailable_notification_numbers", None)
                    rect_nums = counters.get("unavailable_rectification_numbers", None)

                    def _norm(v) -> list[int]:
                        if v is None:
                            return []
                        if isinstance(v, list):
                            out = []
                            for x in v:
                                try:
                                    n = int(str(x).strip())
                                    if n > 0:
                                        out.append(n)
                                except Exception:
                                    pass
                            return sorted(set(out))
                        return self._parse_unavailable_numbers_text(str(v))

                    if (notif_nums is None or rect_nums is None) and old is not None:
                        base = _norm(old)
                        notif_nums = base if notif_nums is None else _norm(notif_nums)
                        rect_nums = base if rect_nums is None else _norm(rect_nums)
                    else:
                        notif_nums = _norm(notif_nums)
                        rect_nums = _norm(rect_nums)

                    self._unavailable_numbers_cache = {
                        "notification": notif_nums,
                        "rectification": rect_nums,
                    }
                    # 默认显示当前下拉选中的那套
                    self._load_unavailable_cache_to_edit()
                    
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _current_unavailable_target(self) -> str:
        """notification | rectification"""
        if not hasattr(self, "unavailable_target_combo"):
            return "notification"
        data = self.unavailable_target_combo.currentData()
        return data if data in ("notification", "rectification") else "notification"

    def _ensure_unavailable_cache(self):
        if not hasattr(self, "_unavailable_numbers_cache") or not isinstance(self._unavailable_numbers_cache, dict):
            self._unavailable_numbers_cache = {"notification": [], "rectification": []}
        self._unavailable_numbers_cache.setdefault("notification", [])
        self._unavailable_numbers_cache.setdefault("rectification", [])

    def _persist_unavailable_edit_to_cache(self):
        """把当前输入框内容写回缓存（切换下拉前/保存前调用）。"""
        if not hasattr(self, "unavailable_numbers_edit"):
            return
        self._ensure_unavailable_cache()
        key = self._current_unavailable_target()
        self._unavailable_numbers_cache[key] = self._parse_unavailable_numbers_text(self.unavailable_numbers_edit.text())

    def _load_unavailable_cache_to_edit(self):
        """把缓存中当前目标的列表展示到输入框。"""
        if not hasattr(self, "unavailable_numbers_edit"):
            return
        self._ensure_unavailable_cache()
        key = self._current_unavailable_target()
        nums = self._unavailable_numbers_cache.get(key, [])
        s = ",".join(str(int(n)) for n in nums) if nums else ""
        self.unavailable_numbers_edit.setText(s)

    def _on_unavailable_target_changed(self):
        """下拉切换：先保存当前编辑内容，再切换展示。"""
        try:
            self._persist_unavailable_edit_to_cache()
            self._load_unavailable_cache_to_edit()
        except Exception:
            pass

    @staticmethod
    def _parse_unavailable_numbers_text(text: str) -> list[int]:
        """
        解析“不可用编号”输入框内容。
        支持：
        - 170
        - 170,171 / 170，171
        - 170-175 / 170~175
        - 空格/分号分隔
        返回：去重排序后的正整数列表
        """
        if not text:
            return []
        s = str(text).strip()
        if not s:
            return []
        s = s.replace("，", ",").replace("；", ";").replace("~", "-")
        parts = re.split(r"[,\s;]+", s)
        out: set[int] = set()
        for p in parts:
            p = (p or "").strip()
            if not p:
                continue
            if "-" in p:
                a, b = p.split("-", 1)
                try:
                    start = int(a.strip())
                    end = int(b.strip())
                    if start <= 0 or end <= 0:
                        continue
                    if start > end:
                        start, end = end, start
                    # 防御：避免超大区间导致卡死
                    if end - start > 200000:
                        continue
                    for n in range(start, end + 1):
                        out.add(n)
                except Exception:
                    continue
            else:
                try:
                    n = int(p)
                    if n > 0:
                        out.add(n)
                except Exception:
                    continue
        return sorted(out)

    def save_config(self):
        """保存配置到文件"""
        try:
            config_file = self.get_config_file()
            
            # 读取现有配置（保留其他字段）
            config = {}
            if config_file.exists():
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except Exception:
                    pass
            
            # 更新计数器
            if 'report_counters' not in config:
                config['report_counters'] = {}
            
            try:
                notif_num = int(self.notification_edit.text()) if self.notification_edit.text() else 1
                rect_num = int(self.rectification_edit.text()) if self.rectification_edit.text() else 1
            except ValueError:
                show_warning(self, "警告", "请输入有效的数字")
                return

            config['report_counters']['notification_number'] = notif_num
            config['report_counters']['rectification_number'] = rect_num

            # 不可用编号：分别保存两套
            if hasattr(self, "unavailable_numbers_edit") and hasattr(self, "unavailable_target_combo"):
                self._persist_unavailable_edit_to_cache()
                self._ensure_unavailable_cache()
                config['report_counters']['unavailable_notification_numbers'] = self._unavailable_numbers_cache.get("notification", [])
                config['report_counters']['unavailable_rectification_numbers'] = self._unavailable_numbers_cache.get("rectification", [])
            
            # 保存文件
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            show_information(self, "成功", "编号配置已更新")
                
        except Exception as e:
            print(f"保存配置失败: {e}")
            show_warning(self, "警告", f"保存配置失败: {str(e)}")

    def on_config_file_changed(self, path):
        """配置文件发生变化时的回调"""
        # 避免在手动保存时触发重载循环，这里简单处理即可，因为load_config只读
        # 如果当前正在编辑配置（虽然批量处理时应该禁用编辑），重新加载可能会打断
        # 但既然要求实时更新，就直接加载
        self.load_config()
        
    def on_theme_changed(self, is_dark_mode):
        """主题变更时的回调"""
        self.apply_theme_styles()
        
    def init_ui(self):
        """初始化UI"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 顶层使用Tab，通报杂活 + 复测一键出
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # ===== 通报杂活 Tab =====
        general_tab = QWidget()
        self.tab_widget.addTab(general_tab, "通报杂活")

        # 通报杂活内部使用滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 功能说明
        info_label = QLabel(
            "📌 <b>网信办通报批量处理工具</b><br><br>"
            "<b>功能说明：</b><br>"
            "• 自动处理文件夹或压缩包中的通报文档<br>"
            "• 支持ZIP压缩包自动解压<br>"
            "• 自动生成：通报改写、授权委托书、责令整改通知书<br>"
            "• 自动处理处置文件模板（复制/编辑）📋<br>"
            "• 自动转换为PDF格式（Word + PDF双份）📄<br>"
            "• 智能编号管理，支持年度自动重置<br><br>"
            "<b>使用方法：</b><br>"
            "1. 选择包含通报文档的文件夹或ZIP压缩包<br>"
            "2. 勾选需要的功能（如自动分类）<br>"
            "3. 确认或修改起始编号配置<br>"
            "4. 点击「开始处理」按钮"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 15px; font-size: 12px; line-height: 1.5;")
        layout.addWidget(info_label)
        layout.addSpacing(15)
        
        # 路径选择组
        path_group = QGroupBox("📁 目标选择")
        path_layout = QVBoxLayout(path_group)
        
        # 路径输入
        path_input_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择文件夹或ZIP压缩包...")
        self.path_input.setReadOnly(True)
        path_input_layout.addWidget(self.path_input)
        
        # 浏览按钮
        browse_btn = QPushButton("📂 选择路径")
        browse_btn.setMinimumWidth(120)
        browse_btn.clicked.connect(self.browse_path)
        path_input_layout.addWidget(browse_btn)
        
        path_layout.addLayout(path_input_layout)
        layout.addWidget(path_group)
        layout.addSpacing(10)

        # 编号配置组
        # from PySide6.QtWidgets import QSpinBox # 不再使用QSpinBox
        config_group = QGroupBox("🔢 编号配置")
        config_layout = QHBoxLayout(config_group)
        
        # 通报序号
        self.notification_label = QLabel("通报序号:")
        config_layout.addWidget(self.notification_label)
        self.notification_edit = QLineEdit()
        self.notification_edit.setPlaceholderText("1")
        self.notification_edit.setToolTip("设置下一个通报文档的期数")
        # 设置只允许输入数字
        self.notification_edit.setValidator(QIntValidator(1, 99999))
        self.notification_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notification_edit.setFixedWidth(80) # 设置固定宽度
        config_layout.addWidget(self.notification_edit)
        
        config_layout.addSpacing(20)
        
        # 责令整改序号
        self.rectification_label = QLabel("责令整改序号:")
        config_layout.addWidget(self.rectification_label)
        self.rectification_edit = QLineEdit()
        self.rectification_edit.setPlaceholderText("1")
        self.rectification_edit.setToolTip("设置下一个责令整改通知书的文号")
        # 设置只允许输入数字
        self.rectification_edit.setValidator(QIntValidator(1, 99999))
        self.rectification_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rectification_edit.setFixedWidth(80) # 设置固定宽度
        config_layout.addWidget(self.rectification_edit)

        config_layout.addSpacing(20)

        # 不可用编号
        self.unavailable_numbers_label = QLabel("不可用编号:")
        config_layout.addWidget(self.unavailable_numbers_label)

        # 不可用编号作用对象
        self.unavailable_target_combo = QComboBox()
        self.unavailable_target_combo.addItem("通报", "notification")
        self.unavailable_target_combo.addItem("责令整改", "rectification")
        self.unavailable_target_combo.setToolTip("选择不可用编号作用于哪一类编号")
        self.unavailable_target_combo.setFixedWidth(90)
        self.unavailable_target_combo.currentIndexChanged.connect(self._on_unavailable_target_changed)
        config_layout.addWidget(self.unavailable_target_combo)

        self.unavailable_numbers_edit = QLineEdit()
        self.unavailable_numbers_edit.setPlaceholderText("如：170,172-175")
        self.unavailable_numbers_edit.setToolTip("设置不可用编号（逗号分隔或区间）。当编号递增/取号命中这些数字时会自动跳过。")
        self.unavailable_numbers_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unavailable_numbers_edit.setFixedWidth(160)
        config_layout.addWidget(self.unavailable_numbers_edit)
        
        config_layout.addStretch()

        # 确认修改按钮
        self.save_config_btn = QPushButton("确认修改")
        self.save_config_btn.clicked.connect(self.save_config)
        # 样式由 theme_manager 统一管理
        config_layout.addWidget(self.save_config_btn)
        
        layout.addWidget(config_group)
        layout.addSpacing(10)
        
        # 加载配置
        self.load_config()

        # 分组数据标签
        self.group_label = QLabel("分组数据: 本地数据库")
        # 初始样式将在 apply_theme_styles 中设置
        self.group_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.group_label)
        
        # 处理按钮
        self.process_btn = QPushButton("🚀 开始处理")
        self.process_btn.setMinimumHeight(50)
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self.start_processing)
        self.process_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
        """)
        layout.addWidget(self.process_btn)

        self.group_btn = QPushButton("🗂️ 一键分类")
        self.group_btn.setMinimumHeight(40)
        self.group_btn.clicked.connect(self.start_grouping)
        layout.addWidget(self.group_btn)
        
        # 进度显示区
        progress_group = QGroupBox("📊 处理进度")
        progress_layout = QVBoxLayout(progress_group)
        
        # 状态文字
        self.status_label = QLabel("等待选择路径...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px 5px;")
        progress_layout.addWidget(self.status_label)
        progress_layout.addSpacing(5)
        
        # 进度条（使用全局主题样式）
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(28)
        # 不设置自定义样式，使用全局主题
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addSpacing(15)
        
        # 详细日志
        log_label = QLabel("📝 详细日志")
        log_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 5px 0px;")
        progress_layout.addWidget(log_label)
        progress_layout.addSpacing(5)
        
        self.progress_text = QTextEdit()
        self.progress_text.setReadOnly(True)
        self.progress_text.setPlaceholderText("等待开始处理...")
        self.progress_text.setMaximumHeight(180)
        self.progress_text.setStyleSheet("""
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 10px;
            padding: 10px;
        """)
        progress_layout.addWidget(self.progress_text)
        
        layout.addWidget(progress_group)
        
        # 编辑失败文档列表区域
        self.manual_group = QGroupBox("❌ 编辑失败的文档")
        manual_layout = QVBoxLayout(self.manual_group)
        
        # 说明文字
        self.manual_info = QLabel(
            "以下文档在编辑过程中出现错误（如插入图片失败、格式调整失败等）："
        )
        manual_layout.addWidget(self.manual_info)
        
        # 编辑失败文档列表
        self.manual_list = QTextEdit()
        self.manual_list.setReadOnly(True)
        self.manual_list.setPlaceholderText("暂无编辑失败的文档")
        self.manual_list.setMaximumHeight(150)
        manual_layout.addWidget(self.manual_list)
        
        # 操作按钮区域
        manual_buttons_layout = QHBoxLayout()
        
        # PDF转换按钮
        self.pdf_convert_btn = QPushButton("📄 转换PDF")
        self.pdf_convert_btn.setToolTip("递归查找目录下的Word文档并转换为PDF，转换后删除原Word文档")
        self.pdf_convert_btn.clicked.connect(self.start_pdf_conversion)
        manual_buttons_layout.addWidget(self.pdf_convert_btn)
        
        # 清除列表按钮
        self.clear_manual_btn = QPushButton("🗑️ 清除列表")
        self.clear_manual_btn.setToolTip("清除编辑失败文档列表")
        self.clear_manual_btn.clicked.connect(self.clear_manual_list)
        manual_buttons_layout.addWidget(self.clear_manual_btn)
        
        manual_buttons_layout.addStretch()  # 添加弹性空间
        manual_layout.addLayout(manual_buttons_layout)
        
        # 存储手动处理文件信息
        self.manual_files_info = []
        
        # 手动处理区域始终显示
        layout.addWidget(self.manual_group)
        
        # 添加底部弹性空间
        layout.addStretch()
        
        # 将内容容器添加到滚动区域
        scroll_area.setWidget(content_widget)
        
        # 将滚动区域添加到通报杂活Tab
        tab_layout = QVBoxLayout(general_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll_area)
        
        # 应用主题样式
        self.apply_theme_styles()

        # ===== 复测一键出 Tab =====
        self.retest_tab = RetestOneClickUI(self)
        self.tab_widget.addTab(self.retest_tab, "复测一键出")
        
    def apply_theme_styles(self):
        """根据当前主题应用样式"""
        is_dark_mode = self.theme_manager._dark_mode
        
        # 设置说明文字样式
        if is_dark_mode:
            # 暗色模式样式
            info_style = "font-size: 12px; color: #ff6b35; font-weight: bold; padding: 5px 0px;"
            text_edit_style = """
                QTextEdit {
                    font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
                    font-size: 11px;
                    padding: 10px;
                    background-color: #2d2d2d;
                    color: #f0f0f0;
                    border: 2px solid #ff6b35;
                    border-radius: 5px;
                }
                QTextEdit:focus {
                    border: 2px solid #bb86fc;
                    outline: none;
                }
            """
            # 按钮样式 - 暗色模式
            open_folder_style = """
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """

            clear_style = """
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
                QPushButton:pressed {
                    background-color: #E65100;
                }
            """
            pdf_convert_style = """
                QPushButton {
                    background-color: #9C27B0;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #7B1FA2;
                }
                QPushButton:pressed {
                    background-color: #6A1B9A;
                }
            """
            
            confirm_style = """
                QPushButton {
                    background-color: #424242;
                    color: white;
                    border: 1px solid #616161;
                    padding: 5px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #616161;
                    border: 1px solid #757575;
                }
                QPushButton:pressed {
                    background-color: #212121;
                    border: 1px solid #424242;
                }
            """
            
            # 标签样式 - 暗色模式
            label_style = "color: #e4e4e7; font-weight: bold;"
            # 输入框样式 - 暗色模式
            line_edit_style = """
                QLineEdit {
                    padding: 5px;
                    border: 1px solid #555;
                    border-radius: 4px;
                    background-color: #2d2d2d;
                    color: #e4e4e7;
                }
                QLineEdit:focus {
                    border: 1px solid #bb86fc;
                }
            """
        else:
            # 亮色模式样式
            info_style = "font-size: 12px; color: #d63384; font-weight: bold; padding: 5px 0px;"
            text_edit_style = """
                QTextEdit {
                    font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
                    font-size: 11px;
                    padding: 10px;
                    background-color: #fff9f0;
                    color: #343a40;
                    border: 2px solid #d63384;
                    border-radius: 5px;
                }
                QTextEdit:focus {
                    border: 2px solid #007bff;
                    outline: none;
                }
            """
            # 按钮样式 - 亮色模式
            open_folder_style = """
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
                QPushButton:pressed {
                    background-color: #1e7e34;
                }
            """

            clear_style = """
                QPushButton {
                    background-color: #fd7e14;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #e8590c;
                }
                QPushButton:pressed {
                    background-color: #d5480a;
                }
            """
            pdf_convert_style = """
                QPushButton {
                    background-color: #6f42c1;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #5a32a3;
                }
                QPushButton:pressed {
                    background-color: #4c2a85;
                }
            """
            
            confirm_style = """
                QPushButton {
                    background-color: #007bff;
                    color: white;
                    border: none;
                    padding: 5px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0056b3;
                }
                QPushButton:pressed {
                    background-color: #004085;
                }
            """
            
            # 标签样式 - 亮色模式
            label_style = "color: #343a40; font-weight: bold;"
            # 输入框样式 - 亮色模式
            line_edit_style = """
                QLineEdit {
                    padding: 5px;
                    border: 1px solid #ced4da;
                    border-radius: 4px;
                    background-color: white;
                    color: #495057;
                }
                QLineEdit:focus {
                    border: 1px solid #80bdff;
                }
            """
        
        # 应用样式到组件
        if hasattr(self, 'manual_info'):
            self.manual_info.setStyleSheet(info_style)
        if hasattr(self, 'manual_list'):
            self.manual_list.setStyleSheet(text_edit_style)
        if hasattr(self, 'pdf_convert_btn'):
            self.pdf_convert_btn.setStyleSheet(pdf_convert_style)
        if hasattr(self, 'save_config_btn'):
            self.save_config_btn.setStyleSheet(confirm_style)
        if hasattr(self, 'group_label'):
            if is_dark_mode:
                self.group_label.setStyleSheet("background-color: #3f3f46; color: #e4e4e7; border-radius: 4px; padding: 4px 8px; font-size: 12px;")
            else:
                self.group_label.setStyleSheet("background-color: #e9ecef; color: #495057; border-radius: 4px; padding: 4px 8px; font-size: 12px;")

        if hasattr(self, 'clear_manual_btn'):
            self.clear_manual_btn.setStyleSheet(clear_style)
            
        # 应用到输入框
        if hasattr(self, 'notification_edit'):
            self.notification_edit.setStyleSheet(line_edit_style)
        if hasattr(self, 'rectification_edit'):
            self.rectification_edit.setStyleSheet(line_edit_style)
            
        # 应用到标签
        if hasattr(self, 'notification_label'):
            self.notification_label.setStyleSheet(label_style)
        if hasattr(self, 'rectification_label'):
            self.rectification_label.setStyleSheet(label_style)
        
    def browse_path(self):
        """选择路径"""
        from modules.ui.file_dialog_helper import get_file_or_directory
        
        # 使用统一的文件/目录选择对话框，用户可以在一个对话框中切换文件和目录模式
        path = get_file_or_directory(
            self,
            "选择包含通报文档的文件夹或ZIP压缩包",
            "",
            "所有文件 (*);;ZIP压缩包 (*.zip)"
            )
        
        if path:
            self.path_input.setText(path)
            self.process_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            self.status_label.setText(f"✅ 已选择: {Path(path).name}")
            self.progress_text.clear()
            self.progress_text.append(f"✅ 已选择: {Path(path).name}")
            self.group_btn.setEnabled(True)
            
    def start_processing(self):
        """开始批量处理"""
        target_path = self.path_input.text().strip()
        
        if not target_path:
            show_warning(self, "警告", "请先选择路径")
            return
        
        if not Path(target_path).exists():
            show_warning(self, "警告", "选择的路径不存在")
            return
        
        # 确认对话框
        reply = QMessageBox.question(
            self, 
            "确认处理", 
            f"即将批量处理以下路径中的所有通报文档：\n\n{target_path}\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 禁用按钮
        self.process_btn.setEnabled(False)
        self.group_btn.setEnabled(False)
        self.notification_edit.setEnabled(False)
        self.rectification_edit.setEnabled(False)
        self.save_config_btn.setEnabled(False)
        
        self.progress_bar.setValue(0)
        self.status_label.setText("🚀 正在初始化...")
        self.progress_text.clear()
        self.progress_text.append("🚀 开始批量处理...")
        self.progress_text.append(f"📍 目标路径: {target_path}")
        self.progress_text.append("=" * 80)
        
        # 重置手动处理区域
        self.manual_list.clear()
        self.manual_list.setPlaceholderText("暂无需要手动处理的文档")
        
        # 启动工作线程
        auto_group = True
        self.worker = BatchReportProcessWorker(target_path, self.script_dir, self.template_dir, auto_group=auto_group)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.finished_signal.connect(self.on_processing_finished)
        self.worker.manual_processing_list.connect(self.on_manual_processing_list)
        # 连接人工校正请求：在主线程展示弹窗，并回传结果
        self.worker.manual_fix_required.connect(self.on_manual_fix_required)
        self.worker.start()

    def on_manual_fix_required(self, message: str, target_dir: str):
        """在主线程中展示人工校正对话框，并将用户选择回传给工作线程"""
        try:
            dlg = ManualFixDialog(self, message=message, target_dir=Path(target_dir))
            proceed = bool(dlg.exec())
        except Exception as e:
            show_critical(self, "人工校正", f"弹窗创建失败：{e}\n将跳过继续流程。")
            proceed = False
        # 回传用户选择给工作线程以继续或跳过
        try:
            self.worker.resume_after_manual_fix.emit(proceed)
        except Exception:
            # 如果工作线程已结束或不可用，忽略
            pass
        
    def start_grouping(self):
        target_path = self.path_input.text().strip()
        if not target_path:
            show_warning(self, "警告", "请先选择路径")
            return
        from modules.Document_Processing.Report_Rewrite import group_folders as gf
        groups = gf.parse_groups_from_db()
        if not groups:
            show_warning(self, "警告", "数据库中没有分类数据，请先在分类管理中维护")
            return
        
        entries = "both"
        pattern = "exact"
        confirm_text = (
            f"即将对以下路径进行企业一键分类：\n\n{target_path}\n\n"
            f"分组数据：本地数据库\n处理对象：{entries}\n匹配策略：{pattern}"
        )
        confirm_text += "\n\n是否继续？"
        reply = QMessageBox.question(
            None,
            "确认分类",
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.group_btn.setEnabled(False)
        self.status_label.setText("🗂️ 正在分类...")
        self.progress_text.append("\n🗂️ 开始一键分类...")
        self.progress_text.append(f"📍 目标路径: {target_path}")
        self.progress_text.append("📄 分组数据: 本地数据库")
        self.progress_text.append("=" * 80)
        self.group_worker = GroupFoldersWorker(target_path, entries, pattern, "db")
        self.group_worker.progress_updated.connect(self.on_progress_updated)
        self.group_worker.finished_signal.connect(self.on_grouping_finished)
        self.group_worker.start()

    def on_grouping_finished(self, success: bool, message: str, company_group_list: list, all_classified: bool):
        self.group_btn.setEnabled(True)
        if success:
            self.status_label.setText("✅ 分类完成")
            # 只有当所有企业都被分类后，才弹出对话框显示
            if all_classified and company_group_list:
                dialog = CompanyGroupDialog(company_group_list, self)
                dialog.exec()
            else:
                # 有企业未分类，只显示普通消息
                show_information(None, "分类完成", f"{message}\n\n请检查日志，确认所有企业都已分类后再次执行。")
        else:
            self.status_label.setText("❌ 分类失败")
            show_critical(None, "错误", message)

    def on_progress_updated(self, message: str):
        self.progress_text.append(message)
        scrollbar = self.progress_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_progress_changed(self, percentage: int, status: str):
        self.progress_bar.setValue(percentage)
        self.status_label.setText(status)

    def on_manual_processing_list(self, manual_files: list):
        self.manual_files_info = manual_files
        if manual_files:
            self.progress_text.append("=" * 80)
            self.progress_text.append("❌ 编辑失败的文档列表:")
            self.progress_text.append("=" * 80)
            self.manual_group.setVisible(True)
            self.manual_list.clear()
            manual_content = []
            for i, file_info in enumerate(manual_files, 1):
                self.progress_text.append(f"{i}. 文档: {Path(file_info['file']).name}")
                self.progress_text.append(f"   原因: {file_info['reason']}")
                if file_info.get('backup_file'):
                    self.progress_text.append(f"   备份: {file_info['backup_file']}")
                if file_info.get('output_file'):
                    self.progress_text.append(f"   输出: {file_info['output_file']}")
                self.progress_text.append("")
                file_name = Path(file_info['file']).name
                reason = file_info['reason']
                manual_content.append(f"📄 {i}. {file_name}")
                manual_content.append(f"    ⚠️ 原因：{reason}")
                if file_info.get('output_file'):
                    output_name = Path(file_info['output_file']).name
                    manual_content.append(f"    📁 输出文件：{output_name}")
                if file_info.get('backup_file'):
                    backup_name = Path(file_info['backup_file']).name
                    manual_content.append(f"    💾 备份文件：{backup_name}")
                manual_content.append("")
            manual_content.extend([
                "💡 操作提示：",
                "• 点击'打开文件夹'快速定位文件",
                "• 手动修复编辑失败的问题后",
                "• 可点击'重新处理'重新生成PDF",
                "• 处理完成后点击'清除列表'",
            ])
            self.manual_list.setText("\n".join(manual_content))
            self.progress_text.append("📝 请手动修复上述文档的编辑问题，完成图片插入或其他必要操作。")
        else:
            self.manual_list.clear()
            self.manual_list.setPlaceholderText("暂无编辑失败的文档")

    def on_processing_finished(self, success: bool, message: str):
        self.process_btn.setEnabled(True)
        self.group_btn.setEnabled(True)
        self.notification_edit.setEnabled(True)
        self.rectification_edit.setEnabled(True)
        self.save_config_btn.setEnabled(True)
        
        self.progress_bar.setValue(100 if success else 0)
        self.status_label.setText(f"{'✅ 完成' if success else '❌ 失败'}: {message}")
        self.progress_text.append("=" * 80)
        self.progress_text.append(f"{'✅ 完成' if success else '❌ 失败'}: {message}")
        if success:
            show_information(None, "成功", "🎉 批量处理完成！")
        else:
            show_critical(None, "失败", f"❌ 批量处理失败：{message}")

    def clear_manual_list(self):
        """清除编辑失败文档列表"""
        self.manual_files_info = []
        self.manual_list.clear()
        self.manual_list.setPlaceholderText("暂无编辑失败的文档")
        self.progress_text.append("🗑️ 已清除编辑失败文档列表")
    
    def start_pdf_conversion(self):
        """开始PDF转换"""
        target_path = self.path_input.text().strip()
        
        if not target_path:
            show_warning(self, "警告", "请先选择目标路径")
            return
        
        if not Path(target_path).exists():
            show_warning(self, "警告", "选择的路径不存在")
            return
        
        # 确认对话框
        reply = QMessageBox.question(
            self, 
            "确认转换", 
            f"即将递归查找以下路径中的Word文档并转换为PDF：\n\n{target_path}\n\n⚠️ 转换成功后将删除原Word文档\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 禁用按钮
        self.pdf_convert_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("🔍 正在搜索Word文档...")
        self.progress_text.clear()
        self.progress_text.append("📄 开始PDF转换...")
        self.progress_text.append(f"📍 目标路径: {target_path}")
        self.progress_text.append("=" * 80)
        
        # 启动PDF转换工作线程
        self.pdf_worker = PDFConvertWorker(target_path)
        self.pdf_worker.progress_updated.connect(self.on_pdf_progress_updated)
        self.pdf_worker.progress_changed.connect(self.on_pdf_progress_changed)
        self.pdf_worker.finished_signal.connect(self.on_pdf_conversion_finished)
        self.pdf_worker.start()
    
    def on_pdf_progress_updated(self, message: str):
        """PDF转换详细日志更新"""
        self.progress_text.append(message)
        # 自动滚动到底部
        scrollbar = self.progress_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_pdf_progress_changed(self, percentage: int, status: str):
        """PDF转换进度条和状态文字更新"""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(status)
        
    def on_pdf_conversion_finished(self, success: bool, message: str):
        """PDF转换完成"""
        self.pdf_convert_btn.setEnabled(True)
        self.progress_bar.setValue(100 if success else 0)
        
        if success:
            self.status_label.setText("✅ PDF转换完成")
            self.progress_text.append("=" * 80)
            self.progress_text.append("✅ PDF转换任务完成！")
            self.progress_text.append(message)
            
            show_information(self, "转换完成", f"PDF转换完成！\n\n{message}")
        else:
            self.status_label.setText("❌ PDF转换失败")
            self.progress_text.append("=" * 80)
            self.progress_text.append("❌ PDF转换失败！")
            self.progress_text.append(message)
            
            show_critical(self, "转换失败", f"PDF转换失败：\n\n{message}")
        
        # 自动滚动到底部
        scrollbar = self.progress_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class CompanyGroupDialog(QDialog):
    """企业-镇街对应关系弹窗"""
    
    def __init__(self, company_group_list: list, parent=None):
        super().__init__(parent)
        # 过滤掉"联系不上"分组的企业
        self.company_group_list = [
            (company, group) for company, group in company_group_list 
            if group != "联系不上"
        ]
        self.setWindowTitle("📋 分类结果 - 企业镇街对应关系")
        self.setMinimumSize(600, 500)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 检测暗色模式
        from modules.ui.styles.theme_manager import ThemeManager
        is_dark = ThemeManager()._dark_mode
        
        # 标题说明
        title_label = QLabel(f"✅ 分类完成！共 {len(self.company_group_list)} 家企业")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        layout.addWidget(title_label)
        
        # 表格展示
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["企业名称", "所属镇街"])
        self.table.setRowCount(len(self.company_group_list))
        
        # 隐藏行号（垂直表头）
        self.table.verticalHeader().setVisible(False)
        
        # 填充数据
        for row, (company, group) in enumerate(self.company_group_list):
            company_item = QTableWidgetItem(company)
            group_item = QTableWidgetItem(group)
            self.table.setItem(row, 0, company_item)
            self.table.setItem(row, 1, group_item)
        
        # 设置表格样式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        if is_dark:
            # 暗色模式样式
            self.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                }
                QLabel {
                    color: #e0e0e0;
                    background-color: transparent;
                }
                QPushButton {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    border: 1px solid #3d3d3d;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #3d3d3d;
                    border-color: #bb86fc;
                }
            """)
            self.table.setStyleSheet("""
                QTableWidget {
                    background-color: #1e1e1e;
                    alternate-background-color: #252525;
                    color: #e0e0e0;
                    gridline-color: #3d3d3d;
                    border: 1px solid #3d3d3d;
                }
                QTableWidget::item {
                    padding: 8px;
                    color: #e0e0e0;
                    background-color: transparent;
                }
                QTableWidget::item:selected {
                    background-color: #483d8b !important;
                    color: #ffffff !important;
                }
                QTableWidget::item:focus {
                    background-color: #483d8b !important;
                    color: #ffffff !important;
                }
                QHeaderView::section {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    padding: 8px;
                    border: none;
                    border-bottom: 1px solid #3d3d3d;
                    font-weight: bold;
                }
            """)
            # 额外设置选中颜色
            from PySide6.QtGui import QPalette, QColor
            palette = self.table.palette()
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#483d8b"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            self.table.setPalette(palette)
        else:
            # 亮色模式样式
            self.setStyleSheet("""
                QDialog {
                    background-color: #ffffff;
                    color: #343a40;
                }
                QLabel {
                    color: #343a40;
                    background-color: transparent;
                }
                QPushButton {
                    background-color: #f8f9fa;
                    color: #343a40;
                    border: 1px solid #dee2e6;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #e9ecef;
                    border-color: #007bff;
                }
            """)
            self.table.setStyleSheet("""
                QTableWidget {
                    background-color: #ffffff;
                    alternate-background-color: #f8f9fa;
                    color: #343a40;
                    gridline-color: #dee2e6;
                    border: 1px solid #dee2e6;
                }
                QTableWidget::item {
                    padding: 8px;
                    color: #343a40;
                }
                QTableWidget::item:selected {
                    background-color: #007bff;
                    color: #ffffff;
                }
                QHeaderView::section {
                    background-color: #f8f9fa;
                    color: #343a40;
                    padding: 8px;
                    border: none;
                    border-bottom: 1px solid #dee2e6;
                    font-weight: bold;
                }
            """)
        
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        
        copy_btn = QPushButton("📋 复制到剪贴板")
        copy_btn.setMinimumHeight(36)
        copy_btn.clicked.connect(self.copy_to_clipboard)
        
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(36)
        close_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(copy_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def copy_to_clipboard(self):
        """复制数据到剪贴板（制表符分隔，方便粘贴到Excel）"""
        from PySide6.QtWidgets import QApplication
        
        # 生成制表符分隔的文本
        lines = ["企业名称\t所属镇街"]
        for company, group in self.company_group_list:
            lines.append(f"{company}\t{group}")
        
        text = "\n".join(lines)
        
        # 复制到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        
        # 提示
        show_information(self, "复制成功", f"已复制 {len(self.company_group_list)} 条记录到剪贴板！\n\n可直接粘贴到Excel等表格软件中。")


class GroupFoldersWorker(QThread):
    progress_updated = Signal(str)
    finished_signal = Signal(bool, str, list, bool)  # 新增：企业-镇街列表, 是否全部分类完成
    
    def __init__(self, source_dir: str, entries: str, pattern: str, groups_source: str, groups_file: str | None = None):
        super().__init__()
        self.source_dir = source_dir
        self.entries = entries
        self.pattern = pattern
        self.groups_source = groups_source
        self.groups_file = groups_file
    
    def run(self):
        try:
            from modules.Document_Processing.Report_Rewrite import group_folders as gf
            result = gf.run_grouping(
                source_dir=self.source_dir,
                entries=self.entries,
                pattern=self.pattern,
                groups_source=self.groups_source,
                groups_file=self.groups_file,
            )
            for line in result["log"]:
                self.progress_updated.emit(line)
            summary = (
                f"移动: {result['moved']} | 已存在: {result['skipped_exist']} | 未抽取公司: {result['miss_no_company']} | "
                f"未找到: {result['miss_not_found']} | 歧义: {result['miss_ambiguous']} | 错误: {result['errors']}"
            )
            # 传递企业-镇街对应列表
            company_group_list = result.get("company_group_list", [])
            # 使用新的判断逻辑：检查根目录下是否还有企业文件夹
            all_classified = result.get("all_classified", False)
            self.finished_signal.emit(True, summary, company_group_list, all_classified)
        except Exception as e:
            self.progress_updated.emit(f"[ERROR] {str(e)}")
            self.finished_signal.emit(False, str(e), [], False)


class RetestPipelineWorker(QThread):
    """复测一键出 - 后端工作线程：支持文件扫描和单文件处理"""
    progress_updated = Signal(str)
    progress_changed = Signal(int, str)
    finished_signal = Signal(bool, str)
    
    # 扫描完成信号：返回找到的文件列表
    scan_finished = Signal(list)
    # 单个文件处理完成信号：返回 (文件路径, 结果字典)
    file_processed = Signal(str, dict)

    def __init__(self, target_dir: str, parent=None):
        super().__init__(parent)
        self.target_dir = Path(target_dir)
        self.mode = 'scan'  # 'scan' or 'process_single'
        self.current_file = None
        
        # 缓存扫描器实例
        self.word_scanner = None
        self.retest_scanner: VulnerabilityRetestScanner | None = None

    def set_mode_scan(self):
        self.mode = 'scan'

    def set_mode_process_single(self, file_path: str):
        self.mode = 'process_single'
        self.current_file = file_path

    def run(self):
        try:
            if self.mode == 'scan':
                self._run_scan()
            elif self.mode == 'process_single':
                self._run_process_single()
        except Exception as e:
            self.finished_signal.emit(False, f"工作线程出错：{e}")

    def _run_scan(self):
        """扫描目录下的所有通报文档"""
        if not self.target_dir.exists():
            self.finished_signal.emit(False, f"目标目录不存在：{self.target_dir}")
            return

        self.progress_changed.emit(5, "🔍 正在扫描通报文档...")
        
        # 使用 WordVulnerabilityScanner 查找文件
        # 这里我们只需要文件列表，但复用 scanner 的 find_word_files 逻辑比较方便
        # 或者直接实例化 scanner
        self.word_scanner = WordVulnerabilityScanner(str(self.target_dir))
        files = self.word_scanner.find_word_files()
        
        # 转换为字符串列表
        file_paths = [str(f) for f in files]
        
        self.progress_updated.emit(f"📄 扫描完成，发现 {len(file_paths)} 份通报文档")
        self.scan_finished.emit(file_paths)

    def _run_process_single(self):
        """处理单个文件：提取漏洞类型和URL -> 按类型定向复测 -> 返回结果"""
        if not self.current_file or not Path(self.current_file).exists():
            self.finished_signal.emit(False, f"文件不存在：{self.current_file}")
            return

        file_path = Path(self.current_file)
        self.progress_updated.emit(f"🔄 正在处理：{file_path.name}")
        
        # 1. 扫描单个文档：提取漏洞类型和 URL/IP
        if not self.word_scanner:
            self.word_scanner = WordVulnerabilityScanner(str(self.target_dir))
            
        scan_result = self.word_scanner.scan_document(file_path)
        vuln_types = scan_result.get("vulnerability_types", [])
        urls = scan_result.get("urls", [])

        # 过滤出 HTTP/HTTPS URL，并剔除 Word 内部 schema 等无效占位
        def _is_valid_http_target(u: str) -> bool:
            if not isinstance(u, str):
                return False
            if not u.startswith(("http://", "https://")):
                return False
            if u.startswith(("http://schemas.microsoft.com", "https://schemas.microsoft.com")):
                return False
            return True

        valid_urls = [u for u in urls if _is_valid_http_target(u)]

        # 如果连漏洞类型都没有，就直接返回给上层，由 UI 决定怎么提示
        if not vuln_types:
            self.progress_updated.emit(f"⚠️ {file_path.name} 未识别到漏洞类型，跳过自动复测")
            self.file_processed.emit(
                str(file_path),
                {
                    "file": str(file_path),
                    "urls": valid_urls,
                    "retest_results": [],
                    "scan_result": scan_result,
                    "manual_test_required": True,
                    "reason": "未识别到漏洞类型，无法匹配自动 PoC 规则，请人工复测。",
                },
            )
            return

        # 2. 根据漏洞类型判断是否属于“明显不能脚本化复测”的类别（如 SSH / SPF / FTP 等）
        # 这里只做一个简单的关键词黑名单，你后续可以在 NON_TESTABLE_VULN_TYPES 里继续补充
        joined_vuln = "；".join(vuln_types)
        is_non_testable = any(nt in joined_vuln for nt in NON_TESTABLE_VULN_TYPES)

        # 初始化复测扫描器，后续需要用到它来判断可支持的漏洞
        if not self.retest_scanner:
            self.retest_scanner = VulnerabilityRetestScanner(timeout=15, max_workers=5)

        supported_types, unsupported_types = self.retest_scanner.classify_vuln_types(vuln_types)
        scan_result["supported_vuln_types"] = supported_types
        scan_result["unsupported_vuln_types"] = unsupported_types

        if is_non_testable:
            unsupported_types = vuln_types if not unsupported_types else unsupported_types

        if is_non_testable or not valid_urls or not supported_types:
            # 没有可用 URL，或者属于不能自动复测的类型 —— 直接返回“需人工复测”的结果
            if not valid_urls:
                self.progress_updated.emit(f"⚠️ {file_path.name} 未提取到可用于 HTTP/HTTPS 复测的 URL")
            else:
                self.progress_updated.emit(
                    f"ℹ️ {file_path.name} 漏洞类型为 {vuln_types}，当前仅支持 HTTP/HTTPS 类自动 PoC，请人工复测"
                )

            reason_parts = []
            if not valid_urls:
                reason_parts.append("未提取到可用 URL")
            if not supported_types:
                reason_parts.append("漏洞类型缺少自动 PoC 规则")
            if is_non_testable:
                reason_parts.append("属于手工验证类漏洞")

            self.file_processed.emit(
                str(file_path),
                {
                    "file": str(file_path),
                    "urls": valid_urls,
                    "retest_results": [],
                    "scan_result": scan_result,
                    "manual_test_required": True,
                    "reason": "；".join(reason_parts) or "请人工复测。",
                    "unsupported_vuln_types": unsupported_types or vuln_types,
                },
            )
            return

        # 3. 使用新的“按漏洞类型定向复测”接口，对每一个 URL 做 PoC
        retest_results: list[dict] = []
        for u in valid_urls:
            single_result = self.retest_scanner.scan_url_for_vuln_types(u, supported_types)
            single_result["unsupported_vuln_types"] = unsupported_types
            retest_results.append(single_result)

        vuln_count = sum(len(r.get('vulnerabilities', [])) for r in retest_results)
        if vuln_count > 0:
            self.progress_updated.emit(f"⚠️ {file_path.name} 发现 {vuln_count} 个风险项")
        else:
            self.progress_updated.emit(f"✅ {file_path.name} 未发现风险")

        # 返回综合结果（包含漏洞类型 + URL + 复测详情），供 UI 渲染 + 报告生成
        result_data = {
            "file": str(file_path),
            "urls": valid_urls,
            "retest_results": retest_results,
            "scan_result": scan_result,
            "manual_test_required": False,
            "unsupported_vuln_types": unsupported_types,
            "supported_vuln_types": supported_types,
        }
        self.file_processed.emit(str(file_path), result_data)


class RetestOneClickUI(QWidget):
    """网信办 - 复测一键出标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = ThemeManager()
        self.theme_manager.dark_mode_changed.connect(self.on_theme_changed)

        self.worker: RetestPipelineWorker | None = None
        self.last_screenshot_path: str | None = None

        # 获取复测模板路径（支持开发和打包环境）
        try:
            from modules.utils.resource_path import get_report_template_dir, get_app_dir
            self.project_root = get_app_dir()
            self.retest_template = get_report_template_dir() / "复测模板.docx"
        except ImportError:
            # 回退到原始方式
            self.project_root = Path(__file__).parent.parent.parent
            self.retest_template = self.project_root / "Report_Template" / "复测模板.docx"

        self.init_ui()

    def on_theme_changed(self, is_dark_mode: bool):
        # 可以根据主题微调样式，这里保持简洁，主要依赖全局ThemeManager
        pass

    def init_ui(self):
        # 最外层先放一个可滚动区域，避免内容太高时整个标签页没有纵向滚动条
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        outer_layout.addWidget(scroll_area)

        content_widget = QWidget()
        scroll_area.setWidget(content_widget)

        # 真实内容布局都放在 content_widget 里
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 顶部区域（说明 / 路径 / 按钮 / 进度），单独一个容器，便于整体控制高度占比
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(top_widget)

        # 说明
        info = QLabel(
            "🛰️ <b>复测一键出</b><br>"
            "1. 选择包含【通报文档】的目录<br>"
            "2. 自动扫描Word获取漏洞类型和URL<br>"
            "3. 自动对URL进行批量复测并在下方展示结果<br>"
            "4. 自动截图复测结果区域，写入复测模板正文中的“*”位置，批量生成复测报告"
        )
        info.setWordWrap(True)
        top_layout.addWidget(info)

        # 目录选择
        path_group = QGroupBox("📁 通报目录")
        path_layout = QHBoxLayout(path_group)

        self.retest_path_input = QLineEdit()
        self.retest_path_input.setPlaceholderText("选择包含通报Word文档的目录...")
        self.retest_path_input.setReadOnly(True)
        browse_btn = QPushButton("📂 选择目录")
        browse_btn.clicked.connect(self.browse_retest_dir)

        path_layout.addWidget(self.retest_path_input)
        path_layout.addWidget(browse_btn)
        top_layout.addWidget(path_group)

        # 控制按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 一键复测")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start_retest)

        self.open_output_btn = QPushButton("📂 打开报告目录")
        self.open_output_btn.setMinimumHeight(40)
        self.open_output_btn.clicked.connect(self.open_output_dir)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.open_output_btn)
        btn_layout.addStretch()
        top_layout.addLayout(btn_layout)

        # 进度
        progress_group = QGroupBox("📊 复测进度")
        progress_layout = QVBoxLayout(progress_group)

        self.retest_status_label = QLabel("等待开始复测...")
        progress_layout.addWidget(self.retest_status_label)

        self.retest_progress_bar = QProgressBar()
        self.retest_progress_bar.setMinimum(0)
        self.retest_progress_bar.setMaximum(100)
        self.retest_progress_bar.setValue(0)
        progress_layout.addWidget(self.retest_progress_bar)

        top_layout.addWidget(progress_group)

        # 结果显示区域（会被截图）
        result_group = QGroupBox("📜 复测结果预览（将对该区域自动截图写入复测报告）")
        result_layout = QVBoxLayout(result_group)

        self.retest_result_text = QTextEdit()
        self.retest_result_text.setReadOnly(True)
        # 让预览区默认有比较大的纵向空间
        self.retest_result_text.setMinimumHeight(320)
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.retest_result_text.setSizePolicy(size_policy)
        # 关闭自动换行，用水平滚动条来展示长行
        self.retest_result_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # 用等宽字体，方便对齐查看
        self.retest_result_text.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;"
        )
        self.retest_result_text.setPlaceholderText("复测结果将在这里展示，并作为证明截图写入复测报告。")
        result_layout.addWidget(self.retest_result_text)

        # 日志输出
        log_group = QGroupBox("📝 详细日志")
        log_layout = QVBoxLayout(log_group)

        self.retest_log = QTextEdit()
        self.retest_log.setReadOnly(True)
        log_layout.addWidget(self.retest_log)

        # 使用垂直分割条包起来，让用户可以拖动调整两块区域的纵向比例
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(result_group)
        splitter.addWidget(log_group)
        splitter.setStretchFactor(0, 3)  # 预览区更高
        splitter.setStretchFactor(1, 1)  # 日志区稍矮

        # 整个“结果+日志”区域作为一个块，占标签页大约 1/3 高度
        main_layout.addWidget(splitter)
        main_layout.setStretch(main_layout.indexOf(top_widget), 2)   # 顶部区域 ~2/3
        main_layout.setStretch(main_layout.indexOf(splitter), 1)     # 结果区域 ~1/3

    # ==== 事件处理 ====

    def browse_retest_dir(self):
        from modules.ui.file_dialog_helper import get_existing_directory
        path = get_existing_directory(self, "选择通报所在目录")
        if path:
            self.retest_path_input.setText(path)
            self.retest_status_label.setText(f"✅ 已选择目录：{Path(path).name}")

    def start_retest(self):
        target_path = self.retest_path_input.text().strip()
        if not target_path:
            show_warning(self, "提示", "请先选择通报目录")
            return

        if not Path(target_path).exists():
            show_warning(self, "错误", "选择的目录不存在")
            return

        if not self.retest_template.exists():
            show_warning(
                self,
                "错误",
                f"未找到复测模板文件：\n{self.retest_template}\n\n请确认模板是否存在。",
            )
            return

        # 重置UI
        self.start_btn.setEnabled(False)
        self.retest_progress_bar.setValue(0)
        self.retest_status_label.setText("🚀 正在启动复测流程...")
        self.retest_log.clear()
        self.retest_result_text.clear()
        self.last_screenshot_path = None
        
        # 初始化处理队列
        self.pending_files = []
        self.total_files = 0
        self.processed_count = 0

        # 启动后台线程 - 第一步：扫描文件
        self.worker = RetestPipelineWorker(target_path, self)
        self.worker.progress_updated.connect(self.on_retest_progress_updated)
        self.worker.progress_changed.connect(self.on_retest_progress_changed)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.file_processed.connect(self.on_file_processed)
        self.worker.finished_signal.connect(self.on_worker_finished)
        
        self.worker.set_mode_scan()
        self.worker.start()

    def on_scan_finished(self, files: list):
        """扫描完成，开始逐个处理文件"""
        self.pending_files = files
        self.total_files = len(files)
        self.processed_count = 0
        
        if self.total_files == 0:
            self.retest_status_label.setText("⚠️ 未找到通报文档")
            self.start_btn.setEnabled(True)
            return
            
        self.retest_status_label.setText(f"✅ 扫描完成，共 {self.total_files} 个文档，开始逐个复测...")
        self.process_next_file()

    def process_next_file(self):
        """处理下一个文件"""
        if not self.pending_files:
            # 所有文件处理完成
            self.retest_status_label.setText("🎉 所有文档复测完成！")
            self.retest_progress_bar.setValue(100)
            self.start_btn.setEnabled(True)
            show_information(self, "完成", f"已完成 {self.total_files} 个文档的复测与报告生成。")
            return

        # 取出下一个文件
        next_file = self.pending_files.pop(0)
        
        # 更新进度条
        progress = int((self.processed_count / self.total_files) * 100)
        self.retest_progress_bar.setValue(progress)
        
        # 让worker处理该文件
        if self.worker:
            self.worker.set_mode_process_single(next_file)
            self.worker.start()

    def on_file_processed(self, file_path: str, result_data: dict):
        """单个文件复测完成，更新UI -> 截图 -> 生成报告"""
        self.processed_count += 1
        
        # 检查是否需要人工复测
        if result_data.get('manual_test_required'):
            reason = result_data.get('reason', '需要人工复测')
            self.retest_log.append(f"⚠️ {Path(file_path).name}: {reason}")
            
            # 渲染人工核验信息到预览区
            self.render_manual_verification_summary(
                file_path,
                result_data,
            )
            
            # 延迟后截图并生成报告
            from PySide6.QtCore import QTimer
            
            def _step_capture_and_generate_manual():
                # 截图
                screenshot_path = self.capture_result_screenshot()
                
                # 即使是人工核验的文档也生成报告
                if screenshot_path:
                    self.generate_single_report(file_path, result_data, screenshot_path)
                
                # 继续下一个
                self.process_next_file()
                
            # 300ms 延迟给UI刷新
            QTimer.singleShot(300, _step_capture_and_generate_manual)
            return

        
        # 1. 更新UI显示复测结果
        urls = result_data.get('urls', [])
        retest_results = result_data.get('retest_results', [])
        
        self.render_retest_summary(
            urls,
            retest_results,
            Path(file_path).name,
            result_data.get("scan_result"),
            result_data.get("unsupported_vuln_types"),
        )
        
        # 2. 稍微延迟以确保UI渲染完成，然后截图并生成报告
        from PySide6.QtCore import QTimer
        
        def _step_capture_and_generate():
            # 截图
            screenshot_path = self.capture_result_screenshot()
            
            # 生成报告
            if screenshot_path:
                self.generate_single_report(file_path, result_data, screenshot_path)
            
            # 继续下一个
            self.process_next_file()
            
        # 300ms 延迟给UI刷新
        QTimer.singleShot(300, _step_capture_and_generate)

    def on_worker_finished(self, success: bool, message: str):
        """Worker线程结束（可能是出错，也可能是单次任务完成）"""
        if not success:
            self.retest_log.append(f"❌ 错误: {message}")
            # 如果是扫描阶段出错，恢复按钮
            if self.total_files == 0: 
                self.start_btn.setEnabled(True)

    def generate_single_report(self, file_path: str, result_data: dict, screenshot_path: str):
        """生成单个文件的复测报告"""
        try:
            # 为了保证字段完全匹配 RetestReportGenerator 的预期，这里直接让它重新扫描一次该通报文档，
            # 而不是复用 WordVulnerabilityScanner 的原始结果。
            generator = RetestReportGenerator(
                target_dir=str(Path(file_path).parent),
                template_path=str(self.retest_template),
                output_dir=None,
                screenshot_path=screenshot_path
            )
            
            # 使用 RetestReportGenerator 自己的 scan_document 提取标题 / 漏洞类型 / URL
            scan_result = generator.scan_document(Path(file_path))

            # 调用生成单个报告的方法
            output_path = generator.generate_report(scan_result)
            
            if output_path:
                self.retest_log.append(f"✅ 报告已生成: {output_path.name}")
                
                # 报告生成成功后，删除截图文件以节省空间
                try:
                    screenshot_file = Path(screenshot_path)
                    if screenshot_file.exists():
                        screenshot_file.unlink()
                        self.retest_log.append(f"🗑️ 已清理截图: {screenshot_file.name}")
                except Exception as del_e:
                    self.retest_log.append(f"⚠️ 清理截图失败: {del_e}")
            else:
                self.retest_log.append(f"❌ 报告生成失败: {Path(file_path).name}")
                
        except Exception as e:
            self.retest_log.append(f"❌ 生成报告异常: {e}")

    def on_retest_progress_updated(self, message: str):
        self.retest_log.append(message)
        sb = self.retest_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_retest_progress_changed(self, percentage: int, status: str):
        # 在单文件循环模式下，进度条由 process_next_file 控制，这里主要更新状态文字
        self.retest_status_label.setText(status)

    # ==== 复测结果展示 & 截图 & 报告生成 ====

    def render_retest_summary(
        self,
        urls: list[str],
        results: list[dict],
        file_name: str = "",
        scan_result: dict | None = None,
        unsupported_vuln_types: list[str] | None = None,
    ):
        """把复测结果整理成一个简明但信息量比较足的文本视图，展示在结果区（用于截图）"""
        lines: list[str] = []
        if file_name:
            lines.append(f"文件：{file_name}")

        vuln_types = (scan_result or {}).get("vulnerability_types") or []
        if vuln_types:
            lines.append("通报漏洞类型： " + "；".join(vuln_types))

        if unsupported_vuln_types:
            lines.append(
                "⚠️ 以下漏洞类型暂不支持自动脚本 PoC，需要人工复测： "
                + "；".join(unsupported_vuln_types)
            )

        lines.append("复测结果概要")
        lines.append("=" * 60)
        lines.append(f"复测URL数量：{len(urls)}")
        vuln_total = sum(len(r.get("vulnerabilities", [])) for r in results)
        lines.append(f"发现风险记录总数：{vuln_total}")
        lines.append("")

        for idx, item in enumerate(results, 1):
            url = item.get("url", "")
            vulns = item.get("vulnerabilities", []) or []
            error = item.get("error")
            original_vuln_types = item.get("original_vuln_types") or vuln_types

            lines.append(f"[{idx}] {url}")
            if original_vuln_types:
                lines.append("    通报漏洞类型： " + "；".join(original_vuln_types))
            matched_types = item.get("matched_vuln_types") or []
            if matched_types and matched_types != original_vuln_types:
                lines.append("    本次脚本覆盖的类型： " + "；".join(matched_types))

            rm = item.get("request_meta") or {}
            if rm and not rm.get("error"):
                lines.append(
                    "    主请求：HTTP "
                    f"{rm.get('status_code', '?')} | "
                    f"{rm.get('elapsed_ms', '?')} ms | "
                    f"正文约 {rm.get('content_length', '?')} 字节 | "
                    f"最终 URL：{rm.get('final_url', url)}"
                )
            elif rm.get("error"):
                lines.append(f"    主请求元数据不可用：{rm.get('error')}")

            fc = item.get("filtered_misc_count")
            if fc:
                lines.append(
                    f"    ℹ️ 与通报类型对齐后已过滤无关基线项 {fc} 条（不计入上方风险数）"
                )

            top_note = item.get("note")
            if top_note and not error:
                lines.append(f"    说明：{top_note}")

            if error:
                lines.append(f"    ❌ 复测错误：{error}")
                lines.append("")
                continue

            if not vulns:
                lines.append("    ✅ 未发现风险（本次检测口径）")
                lines.append("")
                continue

            # 输出每条 PoC 结果，附带严重级别与简要说明
            for v in vulns:
                v_type = v.get("type", "未知类型")
                sev = v.get("severity", "info")
                detail = v.get("detail", "")
                evidence = v.get("evidence")
                note = v.get("note")
                # 把严重级别换成更友好的文字
                sev_map = {
                    "high": "高危",
                    "medium": "中危",
                    "low": "低危",
                    "info": "信息",
                }
                sev_label = sev_map.get(sev, sev)
                lines.append(f"    [{sev_label}] {v_type} - {detail}")
                if evidence:
                    lines.append(f"        证据：{evidence}")
                if note:
                    lines.append(f"        说明：{note}")
            lines.append("")

        self.retest_result_text.setPlainText("\n".join(lines))

    def render_manual_verification_summary(
        self,
        file_path: str,
        result_data: dict,
    ):
        """渲染人工核验类文档的详细信息到预览区（用于截图写入报告）"""
        lines: list[str] = []
        file_name = Path(file_path).name
        
        lines.append("=" * 60)
        lines.append("📋 复测报告 - 需人工核验")
        lines.append("=" * 60)
        lines.append("")
        
        # 文件名
        lines.append(f"📄 文件：{file_name}")
        lines.append("")
        
        # 从通报中识别到的漏洞类型
        scan_result = result_data.get("scan_result", {})
        vuln_types = scan_result.get("vulnerability_types", [])
        if vuln_types:
            lines.append("🔍 通报漏洞类型：")
            for vt in vuln_types:
                lines.append(f"    • {vt}")
        else:
            lines.append("🔍 通报漏洞类型：未识别到")
        lines.append("")
        
        # 提取到的URL/IP
        urls = result_data.get("urls", [])
        if urls:
            lines.append("🌐 提取到的URL/IP：")
            for u in urls:
                lines.append(f"    • {u}")
        else:
            lines.append("🌐 提取到的URL/IP：未检测到可用于HTTP/HTTPS复测的目标")
        lines.append("")
        
        # 无法自动复测的原因
        reason = result_data.get("reason", "")
        unsupported_types = result_data.get("unsupported_vuln_types", [])
        
        lines.append("⚠️ 无法自动复测原因：")
        if reason:
            for part in reason.split("；"):
                if part.strip():
                    lines.append(f"    • {part.strip()}")
        if unsupported_types:
            lines.append(f"    • 漏洞类型暂无自动PoC规则：{', '.join(unsupported_types)}")
        lines.append("")
        
        # 醒目的人工核验提示
        lines.append("=" * 60)
        lines.append("⚡ 复测结论：需人工核验")
        lines.append("=" * 60)
        lines.append("")
        lines.append("本通报涉及的漏洞类型不适用于自动化脚本复测，")
        lines.append("请安全人员根据通报内容进行人工验证。")
        lines.append("")
        lines.append("建议操作：")
        lines.append("    1. 阅读原始通报文档了解漏洞详情")
        lines.append("    2. 使用专业工具对目标进行手工测试")
        lines.append("    3. 根据测试结果填写最终复测结论")
        lines.append("")
        
        # 时间戳
        from datetime import datetime
        lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.retest_result_text.setPlainText("\n".join(lines))

    def capture_result_screenshot(self) -> str | None:
        """对复测结果区域截图并保存成PNG文件
        
        要求：
        - 暗色模式：黑色背景
        - 亮色模式：白色背景
        """
        try:
            widget = self.retest_result_text

            # 根据当前主题设置背景色
            is_dark = getattr(self.theme_manager, "_dark_mode", False)
            bg_color = QColor(0, 0, 0) if is_dark else QColor(255, 255, 255)

            # 创建一张与控件大小相同的 QPixmap，并先用纯色填充背景
            pixmap = QPixmap(widget.size())
            pixmap.fill(bg_color)

            # 再把控件内容渲染到这张 pixmap 上，这样不会出现透明底
            widget.render(pixmap)

            screenshots_dir = self.project_root / "retest_screenshots"
            screenshots_dir.mkdir(exist_ok=True)

            from datetime import datetime

            filename = f"retest_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            save_path = screenshots_dir / filename
            if pixmap.save(str(save_path), "PNG"):
                self.retest_log.append(f"📷 已保存复测结果截图：{save_path}")
                return str(save_path)
            else:
                self.retest_log.append("⚠️ 保存复测截图失败")
                return None
        except Exception as e:
            self.retest_log.append(f"⚠️ 截图失败：{e}")
            return None



    def open_output_dir(self):
        """尝试打开最近一次复测使用的目录（各通报所在目录即输出目录）"""
        if not self.retest_path_input.text().strip():
            show_warning(self, "提示", "请先选择通报目录并完成一次复测")
            return
        target = Path(self.retest_path_input.text().strip())
        if not target.exists():
            show_warning(self, "错误", "当前选择的目录不存在")
            return
        try:
            os.startfile(str(target))
        except Exception as e:
            show_critical(self, "错误", f"无法打开目录：{e}")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    import sys
    
    # 设置高DPI缩放策略（必须在QApplication创建之前）
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    window = ReportRewriteUI()
    window.show()
    sys.exit(app.exec())
