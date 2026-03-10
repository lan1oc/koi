#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台兼容层（替代原 COM 错误处理工具）。
"""

from typing import Any, Callable, Dict


def cleanup_word_processes() -> None:
    return


def robust_word_operation(
    operation_func: Callable,
    max_retries: int = 5,
    delay_base: float = 1.0,
    cleanup_on_retry: bool = True,
    verbose: bool = True,
) -> Any:
    return operation_func()


def safe_open_document(word_app: Any, file_path: str, max_attempts: int = 4, verbose: bool = True) -> Any:
    raise RuntimeError("COM 不可用：当前运行模式不支持 Word COM 打开文档")


def smart_image_insertion(
    doc: Any,
    image_path: str,
    target_paragraph: int,
    width: float = 99.2,
    height: float = 99.2,
    verbose: bool = True,
) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "COM 不可用：不支持该插图策略",
        "error_code": "COM_UNAVAILABLE",
    }


def check_system_environment(verbose: bool = True) -> Dict[str, bool]:
    return {
        "word_installed": False,
        "sufficient_memory": True,
        "no_word_processes": True,
        "com_cache_clean": True,
    }


def check_word_app_connection(word_app: Any, verbose: bool = True) -> bool:
    return False


def create_word_app_safely(
    visible: bool = False,
    display_alerts: bool = False,
    max_retries: int = 3,
    verbose: bool = True,
) -> Any:
    return None


__all__ = [
    "cleanup_word_processes",
    "robust_word_operation",
    "safe_open_document",
    "smart_image_insertion",
    "check_system_environment",
    "check_word_app_connection",
    "create_word_app_safely",
]