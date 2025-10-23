#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步延时工具
提供非阻塞的延时功能，避免UI卡死
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import time
from typing import Callable, Optional


class AsyncDelay:
    """
    异步延时工具类
    提供非阻塞的延时功能，避免UI卡死
    """
    
    @staticmethod
    def delay(milliseconds: int, callback: Optional[Callable] = None, progress_callback: Optional[Callable] = None):
        """
        执行异步延时
        
        Args:
            milliseconds: 延时毫秒数
            callback: 延时结束后的回调函数
            progress_callback: 进度回调函数，用于更新UI
        """
        # 创建一个事件循环等待延时完成
        timer = QTimer()
        timer.setSingleShot(True)
        
        if callback:
            timer.timeout.connect(callback)
        else:
            timer.timeout.connect(lambda: None)
            
        timer.start(milliseconds)
        
        # 发送心跳信号，避免UI卡死
        if progress_callback:
            progress_callback(f"等待请求间隔 {milliseconds/1000} 秒...")
        
        # 等待定时器完成 - 优化等待过程，减少CPU占用
        loop = QTimer()
        loop.setSingleShot(True)
        loop.start(milliseconds)
        
        # 使用更长的休眠间隔，减少CPU占用
        sleep_interval = 0.1  # 100毫秒的休眠间隔
        while loop.isActive():
            QApplication.processEvents()
            # 增加休眠时间，减少CPU占用
            time.sleep(sleep_interval)
    
    @staticmethod
    def delay_with_progress(milliseconds: int, progress_callback: Optional[Callable] = None, callback: Optional[Callable] = None):
        """
        执行带进度更新的异步延时
        
        Args:
            milliseconds: 延时毫秒数
            progress_callback: 进度回调函数，用于更新UI
            callback: 延时结束后的回调函数
        """
        # 计算更新间隔 (每100毫秒更新一次进度)
        update_interval = 100
        steps = max(1, milliseconds // update_interval)
        
        # 创建进度更新定时器
        for step in range(1, steps + 1):
            # 创建一个事件循环等待延时完成
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda s=step: progress_callback(f"等待中... {s}/{steps}") if progress_callback else None)
            timer.start(step * update_interval)
            
        # 最终定时器
        final_timer = QTimer()
        final_timer.setSingleShot(True)
        
        if callback:
            final_timer.timeout.connect(callback)
        else:
            final_timer.timeout.connect(lambda: None)
            
        final_timer.start(milliseconds)
        
        # 等待定时器完成
        loop = QTimer()
        loop.setSingleShot(True)
        loop.start(milliseconds)
        
        while loop.isActive():
            QApplication.processEvents()
            # 增加休眠时间，减少CPU占用
            time.sleep(0.05)