from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPen, QBrush, QPainterPath, QFont
import random
import math

class AnimatedBackground(QWidget):
    """
    Background widget that renders animated themes:
    - Dark Mode: Cyberpunk Digital Rain / Data Stream
    - Light Mode: Hacker Technical Grid
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) # Allow it to be a background
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        self._is_dark = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(30)  # ~30 FPS
        
        # Digital Rain State
        self._init_digital_rain()
            
        # Grid Animation State
        self._grid_offset = 0.0
        
    def _init_digital_rain(self):
        self.font_size = 14
        self.font = QFont("Consolas", self.font_size)
        self.font.setStyleHint(QFont.StyleHint.Monospace)
        self.font.setBold(True)
        self.cols = 0
        self.drops = [] # List of dicts: y, speed, length, chars
        self.chars_pool = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<>[]{}/\\*&^%$#@!"

    def _resize_digital_rain(self):
        # Called in resizeEvent or paintEvent if size changes
        new_cols = max(1, self.width() // self.font_size)
        if new_cols != self.cols:
            self.cols = new_cols
            self.drops = []
            for _ in range(self.cols):
                self.drops.append({
                    'y': random.randint(-self.height(), self.height()),
                    'speed': random.uniform(2, 5), # Slower, more readable speed
                    'length': random.randint(10, 25),
                    'chars': [random.choice(self.chars_pool) for _ in range(30)]
                })

    def _update_digital_rain(self):
        if not self.drops: return
        h = self.height()
        for drop in self.drops:
            drop['y'] += drop['speed']
            # Reset if fully off screen
            if drop['y'] - (drop['length'] * self.font_size) > h:
                drop['y'] = random.randint(-100, 0)
                drop['speed'] = random.uniform(2, 5)
                # Randomly change some chars
                if random.random() < 0.1:
                     drop['chars'] = [random.choice(self.chars_pool) for _ in range(30)]
        


    def set_theme(self, is_dark):
        self._is_dark = is_dark
        self.update()
        
    def update(self):
        if self._is_dark:
            self._update_digital_rain()
        super().update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Create a path for rounded rectangle to respect window border radius
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        
        # Clip to rounded rectangle
        painter.setClipPath(path)
        
        if self._is_dark:
            self._draw_digital_rain_bg(painter)
        else:
            self._draw_hacker_grid_bg(painter)
            
    def _draw_digital_rain_bg(self, p: QPainter):
        # Matrix Digital Rain
        p.fillRect(self.rect(), QColor(10, 12, 15)) # Very dark background
        
        # Check resize
        if self.width() // self.font_size != self.cols:
            self._resize_digital_rain()
            
        p.setFont(self.font)
        
        for i, drop in enumerate(self.drops):
            x = i * self.font_size
            head_y = int(drop['y'])
            
            # Draw trail
            # Optimization: Only draw visible chars
            start_j = 0
            end_j = drop['length']
            
            for j in range(start_j, end_j):
                char_y = head_y - (j * self.font_size)
                
                # Skip if off screen
                if char_y < -self.font_size or char_y > self.height() + self.font_size:
                    continue
                
                # Opacity calculation
                opacity = 1.0 - (j / drop['length'])
                opacity = max(0.0, opacity)
                
                # Color logic
                if j == 0: # Head
                    p.setPen(QColor(220, 255, 220, 255)) # Bright White-Green
                    # Randomly flip head char
                    char = random.choice(self.chars_pool)
                elif j < 3: # Upper trail
                    p.setPen(QColor(0, 255, 70, int(255 * opacity)))
                    char_idx = (int(drop['y'] / 20) + j) % len(drop['chars'])
                    char = drop['chars'][char_idx]
                else: # Lower trail
                    p.setPen(QColor(0, 200, 50, int(200 * opacity)))
                    char_idx = (int(drop['y'] / 20) + j) % len(drop['chars'])
                    char = drop['chars'][char_idx]
                
                p.drawText(x, char_y, char)

    def _draw_hacker_grid_bg(self, p: QPainter):
        # Clean white/gray background
        p.fillRect(self.rect(), QColor(245, 247, 250))
        
        w = self.width()
        h = self.height()
        
        # Grid settings
        grid_size = 40
        self._grid_offset = (self._grid_offset + 0.5) % grid_size
        
        # Draw Grid
        pen = QPen(QColor(200, 200, 200, 100))
        pen.setWidth(1)
        p.setPen(pen)
        
        # Vertical lines
        for x in range(0, w, grid_size):
            p.drawLine(x, 0, x, h)
            
        # Horizontal lines (moving)
        offset_y = int(self._grid_offset)
        for y in range(offset_y, h, grid_size):
            p.drawLine(0, y, w, y)
            
        # Draw random "active" grid cells
        if random.random() < 0.05: # Occasional flicker
            cell_x = random.randint(0, w // grid_size) * grid_size
            cell_y = random.randint(0, h // grid_size) * grid_size + offset_y
            
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 120, 215, 30)) # Light blue highlight
            p.drawRect(cell_x, cell_y, grid_size, grid_size)
            
        # Scanning Line (Hacker style)
        if not hasattr(self, '_scan_y'):
            self._scan_y = 0
            
        self._scan_y = (self._scan_y + 2) % h # Move 2 pixels per frame
        
        grad = QLinearGradient(0, self._scan_y, 0, self._scan_y + 40) # Wider beam
        grad.setColorAt(0, QColor(0, 255, 0, 0))
        grad.setColorAt(0.5, QColor(0, 255, 0, 30)) # Fainter
        grad.setColorAt(1, QColor(0, 255, 0, 0))
        p.fillRect(0, int(self._scan_y), w, 40, grad)
