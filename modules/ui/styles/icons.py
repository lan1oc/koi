#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Optional
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt
from PySide6.QtCore import QSize

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None  # 运行环境若无QtSvg，自动回退


_SVG_MAP = {
    "sun": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <circle cx="12" cy="12" r="4"/>
  <line x1="12" y1="1" x2="12" y2="3"/>
  <line x1="12" y1="21" x2="12" y2="23"/>
  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
  <line x1="1" y1="12" x2="3" y2="12"/>
  <line x1="21" y1="12" x2="23" y2="12"/>
  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
</svg>
""",
    "moon": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
</svg>
""",
    "minus": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <line x1="5" y1="12" x2="19" y2="12"/>
</svg>
""",
    "square": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
</svg>
""",
    "restore": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <rect x="7" y="7" width="10" height="10" rx="2" ry="2"/>
  <polyline points="7 7 7 3 21 3 21 17 17 17"/>
</svg>
""",
    "close": """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <line x1="18" y1="6" x2="6" y2="18"/>
  <line x1="6" y1="6" x2="18" y2="18"/>
</svg>
""",
}


def get_icon(name: str, size: int = 24, color: str = None) -> Optional[QIcon]:
    svg = _SVG_MAP.get(name)
    if not svg:
        return None
    if QSvgRenderer is None:
        return None
    
    # Apply color if provided
    if color:
        svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
        svg = svg.replace('fill="currentColor"', f'fill="{color}"')
        
    try:
        renderer = QSvgRenderer(bytearray(svg, encoding="utf-8"))
        pm = QPixmap(QSize(size, size))
        pm.fill(Qt.transparent)  # type: ignore[name-defined]
        from PySide6.QtGui import QPainter
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        return QIcon(pm)
    except Exception:
        return None