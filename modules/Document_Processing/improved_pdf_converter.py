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
from pathlib import Path
from typing import List, Tuple, Optional


def kill_word_processes():
    """兼容保留：跨平台模式不再依赖Word进程。"""
    return


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


def _find_soffice_executable() -> Optional[str]:
    """Find LibreOffice executable across platforms."""
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found
    mac_default = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac_default.exists():
        return str(mac_default)
    return None


def _convert_with_soffice(src_path: str, dst_path: str) -> Tuple[bool, str]:
    """Convert by LibreOffice headless mode."""
    soffice = _find_soffice_executable()
    if not soffice:
        return False, "未找到 LibreOffice/soffice"

    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.gettempdir()) / f"improved_soffice_{int(time.time())}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_dir), str(src)],
            capture_output=True,
            text=True,
            check=False,
        )
        generated_pdf = tmp_dir / f"{src.stem}.pdf"
        if proc.returncode != 0 or not generated_pdf.exists():
            stderr = (proc.stderr or "").strip()[:200]
            stdout = (proc.stdout or "").strip()[:200]
            detail = stderr or stdout or f"退出码 {proc.returncode}"
            return False, f"LibreOffice转换失败: {detail}"

        shutil.copy2(generated_pdf, dst)
        return True, ""
    except Exception as e:
        return False, f"LibreOffice转换异常: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_single_file_improved(src_path: str, dst_path: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    改进的单文件转换函数
    """
    try:
        import win32com.client as win32  # type: ignore
    except Exception:
        return False, "未安装 pywin32（win32com），无法使用 Word COM 转换"

    safe_src, use_temp_src, temp_src_dir = safe_path_for_com(src_path)
    safe_dst, use_temp_dst, temp_dst_dir = safe_path_for_com(dst_path)

    word_app = None
    doc = None
    try:
        word_app = win32.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0

        doc = word_app.Documents.Open(
            safe_src,
            ReadOnly=True,
            Visible=False,
            ConfirmConversions=False,
            AddToRecentFiles=False,
        )
        doc.ExportAsFixedFormat(
            OutputFileName=safe_dst,
            ExportFormat=17,  # wdExportFormatPDF
        )

        if use_temp_dst:
            final_dst = dst_path
            Path(final_dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(safe_dst, final_dst)
            print(f"📋 文件已复制到最终位置: {final_dst}")

        return True, ""
    except Exception as e:
        return False, f"Word COM转换失败: {e}"
    finally:
        try:
            if doc:
                doc.Close(SaveChanges=0)
        except Exception:
            pass
        try:
            if word_app:
                word_app.Quit(SaveChanges=0)
        except Exception:
            pass

        # 清理临时文件
        if use_temp_src and temp_src_dir:
            try:
                shutil.rmtree(temp_src_dir, ignore_errors=True)
            except:
                pass
                
        if use_temp_dst and temp_dst_dir:
            try:
                shutil.rmtree(temp_dst_dir, ignore_errors=True)
            except:
                pass


def batch_convert_improved(input_files: List[str], output_dir: Optional[str] = None, timeout: int = 30) -> dict:
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
        
        success, error = convert_single_file_improved(str(input_path), str(output_path), timeout)
        
        if success:
            results["success"].append(str(input_path))
            print(f"✅ 成功: {input_path.name} -> {output_path.name}")
        else:
            results["failed"].append((str(input_path), error))
            print(f"❌ 失败: {input_path.name} - {error}")
    
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
