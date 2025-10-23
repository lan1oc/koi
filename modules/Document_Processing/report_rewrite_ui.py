#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网信办特供UI组件 - 批量处理工具

自动处理压缩包/文件夹中的通报文档，生成所需的三个文件
"""

import os
import subprocess
import sys
import zipfile
import shutil
from pathlib import Path
from typing import List

# 减少Qt字体和DirectWrite警告
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts.warning=false;qt.qpa.fonts=false'
os.environ['QT_QPA_PLATFORM'] = 'windows:fontengine=freetype'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'RoundPreferFloor'

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, 
    QLineEdit, QTextEdit, QLabel, QFileDialog, 
    QMessageBox, QProgressBar, QScrollArea
)

# 导入主题管理器
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from modules.ui.styles.theme_manager import ThemeManager


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
                        
                        # 检查是否是通报文档（使用与通报改写相同的识别规则）
                        is_report = False
                        
                        if '关于' in file or '通报' in file:
                            is_report = True
                        elif '存在' in file and '漏洞' in file:
                            is_report = True
                        elif any(keyword in file for keyword in ['有限公司', '股份有限公司', '集团', '科技']) and '漏洞' in file:
                            is_report = True
                        elif '技术检查' in file and '漏洞' in file:
                            is_report = True
                        
                        if is_report:
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
    
    def __init__(self, target_path: str, script_dir: Path, template_dir: Path):
        super().__init__()
        self.target_path = target_path
        self.script_dir = script_dir
        self.template_dir = template_dir
        # 脚本文件都在Report_Rewrite子目录中
        self.rewrite_script = script_dir / "Report_Rewrite" / "rewrite_report.py"
        self.authorization_script = script_dir / "Report_Rewrite" / "edit_authorization.py"
        self.rectification_script = script_dir / "Report_Rewrite" / "edit_rectification.py"
        self.disposal_script = script_dir / "Report_Rewrite" / "edit_disposal.py"
        
        # 进度跟踪
        self.total_reports = 0
        self.processed_reports = 0
        
        # 手动处理列表
        self.manual_processing_files = []
        
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
                
                # 检查是否是通报文档（扩展识别规则）
                # 1. 包含"关于"和"通报"的传统格式
                # 2. 包含"存在"和"漏洞"的技术检查格式
                # 3. 包含公司关键词（有限公司、股份有限公司等）和漏洞关键词的格式
                is_report = False
                
                if '关于' in item.name or '通报' in item.name:
                    is_report = True
                elif '存在' in item.name and '漏洞' in item.name:
                    is_report = True
                elif any(keyword in item.name for keyword in ['有限公司', '股份有限公司', '集团', '科技']) and '漏洞' in item.name:
                    is_report = True
                elif '技术检查' in item.name and '漏洞' in item.name:
                    is_report = True
                
                if not is_report:
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
                # 处理每个通报文档
                for report_file in report_files:
                    self.process_single_report(report_file)
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
    
    def process_single_report(self, report_file: Path):
        """处理单个通报文档"""
        try:
            self.progress_updated.emit("=" * 80)
            self.progress_updated.emit(f"📄 处理文档: {report_file.name}")
            self.progress_updated.emit("-" * 80)
            
            # 切换到文档所在目录
            original_dir = os.getcwd()
            os.chdir(report_file.parent)
            
            # 1. 通报改写 (0-25%)
            self.progress_updated.emit("🔄 步骤1/5: 通报改写")
            self._update_progress("🔄 步骤1/5: 通报改写", step_progress=0)
            
            if self.rewrite_template:
                # 复制模板到当前目录（脚本需要在当前目录找模板）
                import shutil
                template_name = Path(self.rewrite_template).name
                local_template = Path.cwd() / template_name
                if not local_template.exists():
                    shutil.copy2(self.rewrite_template, local_template)
                    self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
            
            rewrite_result = self.run_rewrite_script(report_file)
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
                        # 记录备份文件信息
                        backup_path = Path(rewrite_result['backup_file'])
                        if backup_path.exists():
                            self.progress_updated.emit(f"  ✅ 备份文件已保存: {backup_path.name}")
                else:
                    # 成功处理的文件，记录备份文件信息
                    if rewrite_result.get('backup_file'):
                        backup_path = Path(rewrite_result['backup_file'])
                        if backup_path.exists():
                            self.progress_updated.emit(f"  ✅ 通报文件已保存: {backup_path.name}")
                        else:
                            self.progress_updated.emit(f"  ⚠️ 备份文件不存在: {rewrite_result.get('backup_file')}")
                    else:
                        self.progress_updated.emit(f"  ⚠️ 未找到备份文件路径")
            
            # 等待文件系统和COM完全释放
            import time
            import gc
            gc.collect()  # 强制垃圾回收
            time.sleep(1.0)  # 增加等待时间
            self.progress_updated.emit("  ⏳ 等待文件系统释放...")
            
            self._update_progress("✅ 步骤1/5完成", step_progress=20)
            
            # 删除通报模板文件（因为生成文件名不同，不会被覆盖）
            if self.rewrite_template:
                template_name = Path(self.rewrite_template).name
                local_template = Path.cwd() / template_name
                if local_template.exists():
                    try:
                        local_template.unlink()
                        self.progress_updated.emit(f"  🗑️ 已删除通报模板: {template_name}")
                    except Exception as e:
                        self.progress_updated.emit(f"  ⚠️ 删除模板失败: {str(e)}")
            
            # 2. 生成授权委托书 (20-40%) - 每个通报都生成对应的授权委托书
            self.progress_updated.emit("🔄 步骤2/5: 生成授权委托书")
            self._update_progress("🔄 步骤2/5: 生成授权委托书", step_progress=20)
            
            if self.auth_template:
                template_name = Path(self.auth_template).name
                local_template = Path.cwd() / template_name
                if not local_template.exists():
                    shutil.copy2(self.auth_template, local_template)
                    self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
            
            # 执行脚本并检查结果，传递通报文档路径
            if self.run_script(self.authorization_script, [str(report_file)]):
                # 授权委托书生成成功，但不收集文件
                pass
            
            self._update_progress("✅ 步骤2/5完成", step_progress=40)
            
            # 3. 生成责令整改通知书 (50-75%) - 每个通报都生成对应的责令整改通知书
            self.progress_updated.emit("🔄 步骤3/5: 生成责令整改通知书")
            self._update_progress("🔄 步骤3/5: 生成责令整改通知书", step_progress=40)
            
            if self.rect_template:
                template_name = Path(self.rect_template).name
                local_template = Path.cwd() / template_name
                if not local_template.exists():
                    shutil.copy2(self.rect_template, local_template)
                    self.progress_updated.emit(f"  📋 已复制模板: {template_name}")
            
            # 删除可能存在的临时文件
            for temp_file in Path.cwd().glob("~$*"):
                try:
                    temp_file.unlink()
                except:
                    pass
            
            # 执行脚本并检查结果，传递通报文档路径
            if self.run_script(self.rectification_script, [str(report_file)]):
                # 责令整改通知书生成成功，但不收集文件
                pass
            
            self._update_progress("✅ 步骤3/5完成", step_progress=60)
            
            # 4. 处理处置文件 (75-100%) - 只在第一个通报时处理
            disposal_exists = list(Path.cwd().glob("*处置*.docx"))
            disposal_pdf_exists = list(Path.cwd().glob("*处置*.pdf"))
            
            if not disposal_exists and not disposal_pdf_exists:
                self.progress_updated.emit("🔄 步骤4/5: 处理处置文件")
                self._update_progress("🔄 步骤4/5: 处理处置文件", step_progress=60)
                
                if self.disposal_template:
                    # 直接调用处理函数，传入模板路径
                    if self.run_script(self.disposal_script, [str(self.disposal_template)]):
                        # 处置文件生成成功，但不收集文件
                        pass
                else:
                    self.progress_updated.emit("  ⚠️ 未找到处置文件模板，跳过此步骤")
            else:
                self.progress_updated.emit("⏭️ 步骤4/5: 处置文件已存在，跳过")
            
            self._update_progress("✅ 步骤4/5完成", step_progress=80)
            
            # 5. PDF转换 (80-100%) - 每个企业处理完成后立即转换
            self.progress_updated.emit("🔄 步骤5/5: 转换为PDF")
            self._update_progress("🔄 步骤5/5: 转换为PDF", step_progress=80)
            
            # 转换当前目录下的授权委托书和责令整改通知书为PDF
            pdf_success = self._convert_current_docs_to_pdf()
            
            if pdf_success:
                self.progress_updated.emit("✅ PDF转换完成")
            else:
                self.progress_updated.emit("⚠️ PDF转换部分失败，请检查日志")
            
            self._update_progress("✅ 步骤5/5完成", step_progress=95)
            
            self.progress_updated.emit(f"✅ {report_file.name} 处理完成（包含PDF转换）")
            
            # 更新进度 - 文档完成
            self.processed_reports += 1
            self._update_progress(f"📝 已完成 {self.processed_reports}/{self.total_reports} 个文档", step_progress=100)
            
            # 恢复原目录
            os.chdir(original_dir)
            
        except Exception as e:
            self.progress_updated.emit(f"❌ 处理 {report_file.name} 时出错: {str(e)}")
            import traceback
            self.progress_updated.emit(traceback.format_exc())
            # 即使失败也计数
            self.processed_reports += 1
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
            import sys
            sys.path.insert(0, str(self.script_dir))
            
            from Report_Rewrite.rewrite_report import rewrite_report
            
            # 调用函数并获取结果，设置start_para=3从"1.漏洞描述"开始复制
            result = rewrite_report(str(report_file), start_para=3)
            
            # 移除路径
            sys.path.remove(str(self.script_dir))
            
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
    
    def run_script(self, script_path: Path, args: List[str]) -> bool:
        """运行脚本"""
        try:
            cmd = [sys.executable, str(script_path)] + args
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 读取输出
            stdout, stderr = process.communicate()
            
            # 显示输出
            if stdout:
                for line in stdout.strip().split('\n'):
                    if line.strip():
                        self.progress_updated.emit(f"  {line}")
            
            if process.returncode == 0:
                return True
            else:
                if stderr:
                    self.progress_updated.emit(f"  ❌ 错误: {stderr}")
                return False
                
        except Exception as e:
            self.progress_updated.emit(f"  ❌ 执行错误: {str(e)}")
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
        
        # 获取模板目录路径（在项目根目录下）
        project_root = Path(__file__).parent.parent.parent
        self.template_dir = project_root / "Report_Template"
        
        self.init_ui()
        
    def on_theme_changed(self, is_dark_mode):
        """主题变更时的回调"""
        self.apply_theme_styles()
        
    def init_ui(self):
        """初始化UI"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # 创建内容容器
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
            "2. 点击「开始处理」按钮<br>"
            "3. 等待批量处理完成，获得Word和PDF两种格式"
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
        
        # 将滚动区域添加到主布局
        main_layout.addWidget(scroll_area)
        
        # 应用主题样式
        self.apply_theme_styles()
        
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
        
        # 应用样式到组件
        if hasattr(self, 'manual_info'):
            self.manual_info.setStyleSheet(info_style)
        if hasattr(self, 'manual_list'):
            self.manual_list.setStyleSheet(text_edit_style)
        if hasattr(self, 'pdf_convert_btn'):
            self.pdf_convert_btn.setStyleSheet(pdf_convert_style)

        if hasattr(self, 'clear_manual_btn'):
            self.clear_manual_btn.setStyleSheet(clear_style)
        
    def browse_path(self):
        """选择路径"""
        # 先尝试选择文件夹
        path = QFileDialog.getExistingDirectory(self, "选择包含通报文档的文件夹")
        
        # 如果没有选择文件夹，尝试选择压缩包
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择ZIP压缩包", "", "ZIP压缩包 (*.zip);;所有文件 (*)"
            )
        
        if path:
            self.path_input.setText(path)
            self.process_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            self.status_label.setText(f"✅ 已选择: {Path(path).name}")
            self.progress_text.clear()
            self.progress_text.append(f"✅ 已选择: {Path(path).name}")
            
    def start_processing(self):
        """开始批量处理"""
        target_path = self.path_input.text().strip()
        
        if not target_path:
            QMessageBox.warning(self, "警告", "请先选择路径")
            return
        
        if not Path(target_path).exists():
            QMessageBox.warning(self, "警告", "选择的路径不存在")
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
        self.worker = BatchReportProcessWorker(target_path, self.script_dir, self.template_dir)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.finished_signal.connect(self.on_processing_finished)
        self.worker.manual_processing_list.connect(self.on_manual_processing_list)
        self.worker.start()
        
    def on_progress_updated(self, message: str):
        """详细日志更新"""
        self.progress_text.append(message)
        # 自动滚动到底部
        scrollbar = self.progress_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_progress_changed(self, percentage: int, status: str):
        """进度条和状态文字更新"""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(status)

    def on_manual_processing_list(self, manual_files: list):
        """处理编辑失败文档列表"""
        # 存储文件信息供按钮操作使用
        self.manual_files_info = manual_files
        
        if manual_files:
            # 在日志中记录
            self.progress_text.append("=" * 80)
            self.progress_text.append("❌ 编辑失败的文档列表:")
            self.progress_text.append("=" * 80)
            
            # 在专门的UI区域中显示
            self.manual_group.setVisible(True)
            self.manual_list.clear()
            
            manual_content = []
            for i, file_info in enumerate(manual_files, 1):
                # 日志记录
                self.progress_text.append(f"{i}. 文档: {Path(file_info['file']).name}")
                self.progress_text.append(f"   原因: {file_info['reason']}")
                if file_info['backup_file']:
                    self.progress_text.append(f"   备份: {file_info['backup_file']}")
                if file_info['output_file']:
                    self.progress_text.append(f"   输出: {file_info['output_file']}")
                self.progress_text.append("")
                
                # UI区域显示（更简洁的格式）
                file_name = Path(file_info['file']).name
                reason = file_info['reason']
                manual_content.append(f"📄 {i}. {file_name}")
                manual_content.append(f"    ⚠️ 原因：{reason}")
                
                if file_info['output_file']:
                    output_name = Path(file_info['output_file']).name
                    manual_content.append(f"    📁 输出文件：{output_name}")
                
                if file_info['backup_file']:
                    backup_name = Path(file_info['backup_file']).name
                    manual_content.append(f"    💾 备份文件：{backup_name}")
                
                manual_content.append("")  # 空行分隔
            
            # 添加操作提示
            manual_content.append("💡 操作提示：")
            manual_content.append("• 点击'打开文件夹'快速定位文件")
            manual_content.append("• 手动修复编辑失败的问题后")
            manual_content.append("• 可点击'重新处理'重新生成PDF")
            manual_content.append("• 处理完成后点击'清除列表'")
            
            self.manual_list.setText("\n".join(manual_content))
            
            self.progress_text.append("📝 请手动修复上述文档的编辑问题，完成图片插入或其他必要操作。")
        else:
            # 如果没有编辑失败的文档，显示空状态
            self.manual_list.clear()
            self.manual_list.setPlaceholderText("暂无编辑失败的文档")
    
    def on_processing_finished(self, success: bool, message: str):
        """处理完成"""
        self.process_btn.setEnabled(True)
        self.progress_bar.setValue(100 if success else 0)
        self.status_label.setText(f"{'✅ 完成' if success else '❌ 失败'}: {message}")
        self.progress_text.append("=" * 80)
        self.progress_text.append(f"{'✅ 完成' if success else '❌ 失败'}: {message}")
        
        if success:
            QMessageBox.information(self, "成功", "🎉 批量处理完成！")
        else:
            QMessageBox.critical(self, "失败", f"❌ 批量处理失败：{message}")


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
            QMessageBox.warning(self, "警告", "请先选择目标路径")
            return
        
        if not Path(target_path).exists():
            QMessageBox.warning(self, "警告", "选择的路径不存在")
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
            
            QMessageBox.information(self, "转换完成", f"PDF转换完成！\n\n{message}")
        else:
            self.status_label.setText("❌ PDF转换失败")
            self.progress_text.append("=" * 80)
            self.progress_text.append("❌ PDF转换失败！")
            self.progress_text.append(message)
            
            QMessageBox.critical(self, "转换失败", f"PDF转换失败：\n\n{message}")
        
        # 自动滚动到底部
        scrollbar = self.progress_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


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
