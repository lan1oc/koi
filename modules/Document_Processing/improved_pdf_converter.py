#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进的PDF转换工具
解决转换卡住的问题
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import threading
from pathlib import Path
from typing import List, Tuple, Optional


def kill_word_processes():
    """强制终止所有Word进程"""
    try:
        # 使用taskkill强制终止Word进程
        subprocess.run(['taskkill', '/f', '/im', 'WINWORD.EXE'], 
                      capture_output=True, check=False)
        subprocess.run(['taskkill', '/f', '/im', 'winword.exe'], 
                      capture_output=True, check=False)
        time.sleep(2)
        print("✅ Word进程已清理")
    except Exception as e:
        print(f"⚠️ 清理Word进程时出错: {e}")


def safe_path_for_com(file_path: str) -> Tuple[str, bool, Optional[str]]:
    """
    为COM操作准备安全的文件路径
    返回: (安全路径, 是否使用临时路径, 临时目录路径)
    """
    original_path = Path(file_path)
    
    # 检查路径长度和中文字符
    path_str = str(original_path)
    has_chinese = any('\u4e00' <= char <= '\u9fff' for char in path_str)
    is_too_long = len(path_str) > 200  # 更保守的长度限制
    
    if has_chinese or is_too_long:
        # 创建临时路径
        temp_dir = Path(tempfile.gettempdir()) / f"pdf_convert_{int(time.time())}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用英文文件名
        safe_name = f"temp_doc_{int(time.time())}{original_path.suffix}"
        temp_path = temp_dir / safe_name
        
        # 复制文件到临时位置
        shutil.copy2(original_path, temp_path)
        
        print(f"📁 使用临时路径: {temp_path}")
        return str(temp_path), True, str(temp_dir)
    
    return path_str, False, None


def convert_single_file_improved(src_path: str, dst_path: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    改进的单文件转换函数
    """
    try:
        import win32com.client
    except ImportError:
        return False, "未安装pywin32，请运行: pip install pywin32"
    
    # 准备安全路径
    safe_src, use_temp_src, temp_src_dir = safe_path_for_com(src_path)
    safe_dst, use_temp_dst, temp_dst_dir = safe_path_for_com(dst_path)
    
    word_app = None
    doc = None
    conversion_success = False
    error_message = ""
    
    try:
        # 创建Word应用程序
        print("🚀 启动Word应用程序...")
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0  # 禁用所有警告
        
        # 打开文档
        print(f"📖 打开文档: {Path(src_path).name}")
        doc = word_app.Documents.Open(
            safe_src,
            ReadOnly=True,
            Visible=False,
            ConfirmConversions=False,
            AddToRecentFiles=False
        )
        
        # 确保输出目录存在
        Path(safe_dst).parent.mkdir(parents=True, exist_ok=True)
        
        # 使用线程进行转换，带超时控制
        conversion_result = {"success": False, "error": None}
        
        def conversion_task():
            try:
                print(f"🔄 开始转换为PDF...")
                doc.ExportAsFixedFormat(
                    OutputFileName=safe_dst,
                    ExportFormat=17,  # wdExportFormatPDF
                    OptimizeFor=0,    # wdExportOptimizeForPrint
                    BitmapMissingFonts=True,
                    DocStructureTags=False,
                    CreateBookmarks=0,  # wdExportCreateNoBookmarks
                    UseDocHeaderFooter=True
                )
                conversion_result["success"] = True
                print("✅ PDF转换完成")
            except Exception as e:
                conversion_result["error"] = str(e)
                print(f"❌ 转换失败: {e}")
        
        # 启动转换线程
        thread = threading.Thread(target=conversion_task)
        thread.daemon = True
        thread.start()
        
        # 等待转换完成或超时
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            # 超时处理
            print(f"⏰ 转换超时({timeout}秒)，强制终止...")
            error_message = f"转换超时({timeout}秒)"
            
            # 强制关闭文档和应用程序
            try:
                if doc:
                    doc.Close(SaveChanges=0)
                if word_app:
                    word_app.Quit(SaveChanges=0)
            except:
                pass
            
            # 强制终止Word进程
            kill_word_processes()
            
            return False, error_message
        
        # 检查转换结果
        if conversion_result["success"]:
            conversion_success = True
            
            # 如果使用了临时路径，需要复制回原位置
            if use_temp_dst:
                final_dst = dst_path
                Path(final_dst).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(safe_dst, final_dst)
                print(f"📋 文件已复制到最终位置: {final_dst}")
            
        elif conversion_result["error"]:
            error_message = conversion_result["error"]
        else:
            error_message = "转换失败，原因未知"
            
    except Exception as e:
        error_message = f"转换过程出错: {str(e)}"
        print(f"❌ {error_message}")
        
    finally:
        # 清理资源
        try:
            if doc:
                doc.Close(SaveChanges=0)
        except:
            pass
        
        try:
            if word_app:
                word_app.Quit(SaveChanges=0)
        except:
            pass
        
        # 清理临时文件
        if use_temp_src and temp_src_dir:
            try:
                shutil.rmtree(temp_src_dir, ignore_errors=True)
            except:
                pass
                
        if use_temp_dst and temp_dst_dir and not conversion_success:
            try:
                shutil.rmtree(temp_dst_dir, ignore_errors=True)
            except:
                pass
        
        # 确保Word进程完全退出
        time.sleep(1)
        
    return conversion_success, error_message


def batch_convert_improved(input_files: List[str], output_dir: str = None, timeout: int = 30) -> dict:
    """
    改进的批量转换函数
    """
    results = {
        "success": [],
        "failed": [],
        "total": len(input_files)
    }
    
    print(f"🎯 开始批量转换 {len(input_files)} 个文件")
    
    for i, input_file in enumerate(input_files, 1):
        input_path = Path(input_file)
        
        # 确定输出路径
        if output_dir:
            output_path = Path(output_dir) / f"{input_path.stem}.pdf"
        else:
            output_path = input_path.parent / f"{input_path.stem}.pdf"
        
        print(f"\n📄 [{i}/{len(input_files)}] 转换: {input_path.name}")
        
        # 在每个文件转换前清理Word进程
        if i > 1:  # 第一个文件不需要清理
            print("🧹 清理Word进程...")
            kill_word_processes()
        
        success, error = convert_single_file_improved(str(input_path), str(output_path), timeout)
        
        if success:
            results["success"].append(str(input_path))
            print(f"✅ 成功: {input_path.name} -> {output_path.name}")
        else:
            results["failed"].append((str(input_path), error))
            print(f"❌ 失败: {input_path.name} - {error}")
    
    # 最终清理
    kill_word_processes()
    
    print(f"\n🎉 批量转换完成!")
    print(f"✅ 成功: {len(results['success'])} 个文件")
    print(f"❌ 失败: {len(results['failed'])} 个文件")
    
    return results


if __name__ == "__main__":
    # 测试用例
    test_file = r"C:\Users\lan1o\Desktop\网信办\运营中心\运营中心通报\改写存放\test.docx"
    if Path(test_file).exists():
        print("🧪 测试单文件转换...")
        success, error = convert_single_file_improved(test_file, test_file.replace('.docx', '.pdf'))
        if success:
            print("✅ 测试成功!")
        else:
            print(f"❌ 测试失败: {error}")