#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delay helpers for backend tasks.

The Tauri UI receives progress through the backend API, so this module must not
depend on any desktop UI toolkit.
"""

import time
from typing import Callable, Optional


class AsyncDelay:
    """Small compatibility wrapper around ``time.sleep`` with progress hooks."""

    @staticmethod
    def _emit(callback: Optional[Callable], message: str) -> None:
        if not callback:
            return
        try:
            callback(message)
        except Exception:
            pass

    @staticmethod
    def delay(
        milliseconds: int,
        callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        seconds = max(0.0, milliseconds / 1000.0)
        if seconds:
            AsyncDelay._emit(progress_callback, f"等待请求间隔 {seconds:.2f} 秒...")
            time.sleep(seconds)

        if callback:
            callback()

    @staticmethod
    def delay_with_progress(
        milliseconds: int,
        progress_callback: Optional[Callable] = None,
        callback: Optional[Callable] = None,
    ) -> None:
        seconds = max(0.0, milliseconds / 1000.0)
        if seconds <= 0:
            if callback:
                callback()
            return

        update_interval = 0.1
        deadline = time.monotonic() + seconds
        steps = max(1, int(seconds / update_interval))
        step = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            step += 1
            AsyncDelay._emit(progress_callback, f"等待中... {min(step, steps)}/{steps}")
            time.sleep(min(update_interval, remaining))

        if callback:
            callback()
