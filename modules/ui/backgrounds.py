from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPen, QBrush, QPainterPath
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
        
        # Cyberpunk Data Stream Particles
        self.particles = []
        for _ in range(50):
            self.particles.append(self._create_particle())
            
        # Grid Animation State
        self._grid_offset = 0.0
        
    def _create_particle(self):
        return {
            'x': random.random(), # 0.0 to 1.0 relative width
            'y': random.random(), # 0.0 to 1.0 relative height
            'speed': random.uniform(0.002, 0.01),
            'length': random.uniform(0.05, 0.15),
            'opacity': random.uniform(0.3, 0.8),
            'color_type': random.choice(['cyan', 'purple'])
        }

    def set_theme(self, is_dark):
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Create a path for rounded rectangle to respect window border radius
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        
        # Clip to rounded rectangle
        painter.setClipPath(path)
        
        if self._is_dark:
            self._draw_cyberpunk_bg(painter)
        else:
            self._draw_hacker_grid_bg(painter)
            
    def _draw_cyberpunk_bg(self, p: QPainter):
        # Deep dark background
        p.fillRect(self.rect(), QColor(20, 20, 25))
        
        w = self.width()
        h = self.height()
        
        # Update and draw particles
        for particle in self.particles:
            # Update position
            particle['y'] += particle['speed']
            if particle['y'] > 1.2: # Reset if off screen
                particle['y'] = -0.2
                particle['x'] = random.random()
                
            # Draw
            x = particle['x'] * w
            y = particle['y'] * h
            length = particle['length'] * h
            
            # Gradient for the trail
            grad = QLinearGradient(x, y - length, x, y)
            
            if particle['color_type'] == 'cyan':
                c = QColor(0, 255, 255)
            else:
                c = QColor(180, 0, 255)
                
            c.setAlphaF(particle['opacity'])
            grad.setColorAt(1, c)
            grad.setColorAt(0, QColor(0, 0, 0, 0))
            
            p.setPen(QPen(QBrush(grad), 2))
            p.drawLine(QPointF(x, y - length), QPointF(x, y))
            
            # Draw "head" of the data stream
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 1.5, 1.5)

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
