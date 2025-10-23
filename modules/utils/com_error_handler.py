#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COM错误处理工具模块
提供增强的Word COM操作错误处理和重试机制
"""

import os
import sys
import time
import subprocess
import gc
from pathlib import Path
from typing import Callable, Any, Optional, Dict, List


def cleanup_word_processes():
    """清理可能残留的Word进程"""
    try:
        subprocess.run(['taskkill', '/f', '/im', 'WINWORD.EXE'], 
                      capture_output=True, check=False)
        time.sleep(1)
    except:
        pass


def robust_word_operation(operation_func: Callable, max_retries: int = 5, delay_base: float = 1.0, 
                         cleanup_on_retry: bool = True, verbose: bool = True) -> Any:
    """
    增强的Word操作函数，包含智能重试机制
    
    参数:
        operation_func: 要执行的操作函数
        max_retries: 最大重试次数
        delay_base: 基础延迟时间（秒）
        cleanup_on_retry: 重试时是否清理Word进程
        verbose: 是否输出详细信息
    
    返回:
        操作函数的返回值
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            # 清理可能存在的Word进程（除第一次尝试外）
            if attempt > 0 and cleanup_on_retry:
                if verbose:
                    print(f"[INFO] 第{attempt + 1}次尝试，清理Word进程...")
                cleanup_word_processes()
                
                # 强制垃圾回收
                gc.collect()
                
                # 等待时间递增
                delay = delay_base * (attempt + 1)
                time.sleep(delay)
            
            # 执行操作
            return operation_func()
            
        except Exception as e:
            last_exception = e
            error_code = getattr(e, 'args', [None])[0]
            
            if verbose:
                print(f"[ERROR] 第{attempt + 1}次尝试失败: {str(e)[:100]}")
                if error_code:
                    print(f"   错误代码: {error_code}")
            
            # 特定错误的处理策略
            if error_code == -2147352567:  # 文件损坏错误
                if verbose:
                    print(f"[INFO] 检测到文档损坏错误，将在下次尝试修复模式...")
                    
            elif error_code == -2147220995:  # 服务器连接错误
                if verbose:
                    print(f"[INFO] 检测到服务器连接错误，将重新创建COM对象...")
                    
            elif "Property 'Word.Application.Visible' can not be set" in str(e):
                if verbose:
                    print(f"[INFO] 检测到Word属性设置错误，将清理COM缓存...")
                # 清理COM缓存
                try:
                    import win32com.client.gencache
                    # 尝试不同的方法获取缓存路径
                    cache_dir = None
                    get_generate_path = getattr(win32com.client.gencache, 'GetGeneratePath', None)
                    get_cache_dir = getattr(win32com.client.gencache, 'GetCacheDir', None)
                    
                    if get_generate_path:
                        cache_dir = get_generate_path()
                    elif get_cache_dir:
                        cache_dir = get_cache_dir()
                    else:
                        # 使用默认路径
                        import tempfile
                        cache_dir = os.path.join(tempfile.gettempdir(), 'gen_py')
                    
                    if cache_dir and os.path.exists(cache_dir):
                        import shutil
                        shutil.rmtree(cache_dir, ignore_errors=True)
                except:
                    pass
                    
            # 如果是最后一次尝试，抛出异常
            if attempt == max_retries - 1:
                if verbose:
                    print(f"💥 所有重试都失败，抛出最后的异常")
                raise last_exception
                
    return None


def safe_open_document(word_app, file_path: str, max_attempts: int = 4, verbose: bool = True) -> Any:
    """
    安全的文档打开函数，尝试多种打开策略
    
    参数:
        word_app: Word应用程序对象
        file_path: 文档路径
        max_attempts: 最大尝试次数
        verbose: 是否输出详细信息
    
    返回:
        打开的文档对象
    """
    # 确保文件路径存在
    if not Path(file_path).exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    # 多种打开策略
    open_strategies = [
        {
            "name": "标准只读模式",
            "params": {
                "ReadOnly": True,
                "Visible": False,
                "ConfirmConversions": False,
                "AddToRecentFiles": False
            }
        },
        {
            "name": "受保护文档模式",
            "params": {
                "ReadOnly": True,
                "PasswordDocument": "",
                "WritePasswordDocument": "",
                "Visible": False,
                "ConfirmConversions": False
            }
        },
        {
            "name": "修复模式",
            "params": {
                "ReadOnly": True,
                "OpenAndRepair": True,
                "Visible": False
            }
        },
        {
            "name": "最简参数",
            "params": {
                "ReadOnly": True
            }
        }
    ]
    
    last_exception = None
    
    for strategy_idx, strategy in enumerate(open_strategies):
        for attempt in range(max_attempts):
            try:
                if verbose:
                    print(f"🔄 尝试{strategy['name']} (第{attempt+1}次)...")
                
                # 检查文件是否被锁定
                if attempt > 0:
                    for lock_check in range(3):
                        try:
                            with open(file_path, 'r+b') as test_file:
                                pass  # 如果能打开说明没有被锁定
                            break
                        except (PermissionError, OSError):
                            if lock_check < 2:
                                if verbose:
                                    print(f"    [WARNING] 文件被锁定，等待释放（{lock_check + 1}/3）")
                                time.sleep(1.0)
                            else:
                                raise Exception("文件被锁定无法访问")
                
                # 尝试打开文档
                doc = word_app.Documents.Open(file_path, **strategy['params'])
                
                if verbose:
                    print(f"[OK] {strategy['name']}成功")
                return doc
                
            except Exception as e:
                last_exception = e
                if verbose:
                    print(f"[ERROR] {strategy['name']}失败: {str(e)[:100]}")
                
                if attempt < max_attempts - 1:
                    # 清理COM残留
                    try:
                        import pythoncom
                        pythoncom.CoUninitialize()
                        pythoncom.CoInitialize()
                    except:
                        pass
                    time.sleep(0.5 + attempt * 0.3)
                    
    # 所有策略都失败
    raise Exception(f"所有打开策略都失败，最后错误: {last_exception}")


def smart_image_insertion(doc, image_path: str, target_paragraph: int, 
                         width: float = 99.2, height: float = 99.2, verbose: bool = True) -> Dict:
    """
    智能图片插入函数，包含错误处理和验证
    
    参数:
        doc: Word文档对象
        image_path: 图片路径
        target_paragraph: 目标段落索引
        width: 图片宽度（points）
        height: 图片高度（points）
        verbose: 是否输出详细信息
    
    返回:
        包含插入结果的字典
    """
    try:
        # 预检查文档状态
        initial_page_count = doc.Range().Information(4)
        
        # 检查段落是否存在
        if target_paragraph > doc.Paragraphs.Count:
            return {
                "success": False,
                "error": f"段落索引超出范围: {target_paragraph} > {doc.Paragraphs.Count}",
                "error_code": "PARAGRAPH_OUT_OF_RANGE"
            }
        
        # 插入图片
        paragraph = doc.Paragraphs(target_paragraph)
        range_obj = paragraph.Range
        range_obj.Collapse(0)
        
        inline_shape = range_obj.InlineShapes.AddPicture(
            FileName=image_path,
            LinkToFile=False,
            SaveWithDocument=True
        )
        
        # 设置图片大小
        inline_shape.Width = width
        inline_shape.Height = height
        
        # 验证插入结果
        final_page_count = doc.Range().Information(4)
        
        if verbose:
            print(f"[OK] 图片插入成功: 段落{target_paragraph}, 页数 {initial_page_count}→{final_page_count}")
        
        return {
            "success": True,
            "initial_pages": initial_page_count,
            "final_pages": final_page_count,
            "shape": inline_shape,
            "width": width,
            "height": height
        }
        
    except Exception as e:
        error_code = getattr(e, 'args', [None])[0]
        
        if verbose:
            print(f"[ERROR] 图片插入失败: {str(e)[:100]}")
            if error_code:
                print(f"   错误代码: {error_code}")
        
        return {
            "success": False,
            "error": str(e),
            "error_code": error_code
        }


def check_system_environment(verbose: bool = True) -> Dict[str, bool]:
    """
    检查系统环境是否适合COM操作
    
    参数:
        verbose: 是否输出详细信息
    
    返回:
        包含各项检查结果的字典
    """
    checks = {
        "word_installed": False,
        "sufficient_memory": False,
        "no_word_processes": False,
        "com_cache_clean": False
    }
    
    # 检查Word是否安装
    try:
        import win32com.client
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Quit()
        checks["word_installed"] = True
        if verbose:
            print("[OK] Word已安装且可访问")
    except Exception as e:
        if verbose:
            print(f"[ERROR] Word安装检查失败: {e}")
    
    # 检查内存
    try:
        import psutil
        memory = psutil.virtual_memory()
        available_gb = memory.available / (1024 * 1024 * 1024)
        checks["sufficient_memory"] = available_gb > 1.0  # 至少1GB可用内存
        if verbose:
            print(f"{'[OK]' if checks['sufficient_memory'] else '[ERROR]'} 可用内存: {available_gb:.1f}GB")
    except Exception as e:
        if verbose:
            print(f"[WARNING] 内存检查失败: {e}")
    
    # 检查Word进程
    try:
        import psutil
        word_processes = [p for p in psutil.process_iter(['name']) 
                         if p.info['name'] and 'word' in p.info['name'].lower()]
        checks["no_word_processes"] = len(word_processes) == 0
        if verbose:
            if checks["no_word_processes"]:
                print("[OK] 没有残留的Word进程")
            else:
                print(f"[WARNING] 发现 {len(word_processes)} 个Word进程")
    except Exception as e:
        if verbose:
            print(f"[WARNING] Word进程检查失败: {e}")
    
    # 检查COM缓存
    try:
        import win32com.client.gencache
        # 尝试不同的方法获取缓存路径
        cache_dir = None
        get_generate_path = getattr(win32com.client.gencache, 'GetGeneratePath', None)
        get_cache_dir = getattr(win32com.client.gencache, 'GetCacheDir', None)
        
        if get_generate_path:
            cache_dir = get_generate_path()
        elif get_cache_dir:
            cache_dir = get_cache_dir()
        else:
            # 使用默认路径
            import tempfile
            cache_dir = os.path.join(tempfile.gettempdir(), 'gen_py')
        
        checks["com_cache_clean"] = cache_dir is not None and os.path.exists(cache_dir)
        if verbose:
            print(f"{'[OK]' if checks['com_cache_clean'] else '[WARNING]'} COM缓存状态: {'正常' if checks['com_cache_clean'] else '可能需要清理'}")
    except Exception as e:
        if verbose:
            print(f"[WARNING] COM缓存检查失败: {e}")
    
    return checks


def check_word_app_connection(word_app, verbose: bool = True) -> bool:
    """
    检查Word应用程序连接是否有效
    
    参数:
        word_app: Word应用程序对象
        verbose: 是否输出详细信息
    
    返回:
        bool: 连接是否有效
    """
    if word_app is None:
        if verbose:
            print("[ERROR] Word应用程序对象为None")
        return False
    
    try:
        # 尝试访问Word应用程序的基本属性
        _ = word_app.Version
        _ = word_app.Documents.Count
        if verbose:
            print("[OK] Word应用程序连接正常")
        return True
    except Exception as e:
        if verbose:
            print(f"[ERROR] Word应用程序连接失效: {str(e)[:100]}")
        return False


def create_word_app_safely(visible: bool = False, display_alerts: bool = False, 
                          max_retries: int = 3, verbose: bool = True):
    """
    安全创建Word应用程序对象
    
    参数:
        visible: 是否显示Word窗口
        display_alerts: 是否显示警告
        max_retries: 最大重试次数
        verbose: 是否输出详细信息
    
    返回:
        Word应用程序对象
    """
    def create_app():
        import win32com.client
        word_app = win32com.client.Dispatch("Word.Application")
        
        # 设置属性时使用try-catch，避免属性设置失败
        try:
            word_app.Visible = visible
        except Exception as e:
            if verbose:
                print(f"[WARNING] 设置Visible属性失败: {e}")
        
        try:
            word_app.DisplayAlerts = 1 if display_alerts else 0
        except Exception as e:
            if verbose:
                print(f"[WARNING] 设置DisplayAlerts属性失败: {e}")
        
        return word_app
    
    return robust_word_operation(
        create_app, 
        max_retries=max_retries, 
        cleanup_on_retry=True,
        verbose=verbose
    )


# 导出的主要函数
__all__ = [
    'cleanup_word_processes',
    'robust_word_operation', 
    'safe_open_document',
    'smart_image_insertion',
    'check_system_environment',
    'check_word_app_connection',
    'create_word_app_safely'
]