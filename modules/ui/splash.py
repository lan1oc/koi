import math
import random
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, QElapsedTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QFont, QLinearGradient, QRadialGradient

class AnimatedSplash(QWidget):
    def __init__(self, icon_path: str | None = None, version: str = "1.0.0"):
        super().__init__(parent=None)
        self.version = version
        # 移除 SplashScreen 标志，避免点击其他窗口时被隐藏
        # 只使用 FramelessWindowHint，让窗口可以正常显示在其他窗口下面，但不会消失
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        # Increase size for better visual impact
        self.setFixedSize(800, 500)
        self._pix = QPixmap(icon_path) if icon_path and not QPixmap(icon_path).isNull() else None
        
        # Hacker Theme Colors
        self._bg_color = QColor(5, 10, 20)          # Deep dark blue/black
        self._cyan = QColor(0, 255, 255)            # Cyber cyan
        self._cyan_dim = QColor(0, 255, 255, 50)    # Dim cyan
        self._purple = QColor(180, 0, 255)          # Cyber purple
        self._text_color = QColor(220, 230, 255)    # White-ish blue
        self._grid_color = QColor(0, 255, 255, 20)  # Very faint grid
        self._alert_red = QColor(255, 50, 50)       # Alert red
        self._success_green = QColor(50, 255, 50)   # Success green
        
        # Random data for "decryption" effect
        self._hex_lines = []
        for _ in range(20):
            self._hex_lines.append(self._generate_hex_line())
            
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)  # ~60fps
        
        self._data_timer = QTimer(self)
        self._data_timer.timeout.connect(self._update_data)
        self._data_timer.start(100)
        
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        print("Using Final Hacker Style Splash Screen")

    def _generate_hex_line(self):
        chars = "0123456789ABCDEF"
        return " ".join(["".join([random.choice(chars) for _ in range(2)]) for _ in range(8)])

    def _update_data(self):
        # Scroll hex lines
        self._hex_lines.pop(0)
        self._hex_lines.append(self._generate_hex_line())

    def showCentered(self):
        scr = self.screen().availableGeometry() if self.screen() else self.geometry()
        x = scr.center().x() - self.width() // 2
        y = scr.center().y() - self.height() // 2
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.repaint()

    def _get_card_transform(self, t, card_index):
        """Calculates card transformation - Unified smooth Pandora flourish"""
        cycle = t % 2.5  # 2.5 seconds full cycle (Speed up)
        progress = cycle / 2.5
        
        x, y, rotation = 0, 0, 0
        num_cards = 5
        
        # Phase 1: Pressure Fan (0% - 20%)
        if progress < 0.2:
            p = progress / 0.2
            p = p * p * (3 - 2 * p)  # Smoothstep
            
            fan_angle_base = -30
            fan_angle_range = 60
            card_angle = fan_angle_base + (fan_angle_range / (num_cards - 1)) * card_index
            
            fan_radius = 50 * p
            x = fan_radius * math.cos(math.radians(card_angle)) * p
            y = fan_radius * math.sin(math.radians(card_angle)) * p
            rotation = card_angle + 90
            
        # Phase 2: Tornado Spin (20% - 40%)
        elif progress < 0.4:
            p = (progress - 0.2) / 0.2
            p = p * p * (3 - 2 * p)
            
            fan_angle_base = -30
            fan_angle_range = 60
            start_angle = fan_angle_base + (fan_angle_range / (num_cards - 1)) * card_index
            
            tornado_rotation = p * 180
            radius = 50 + 20 * math.sin(p * math.pi)
            final_angle = start_angle + tornado_rotation
            
            x = radius * math.cos(math.radians(final_angle))
            y = radius * math.sin(math.radians(final_angle))
            rotation = final_angle + 90
            
            offset_angle = card_index * 5
            rotation += offset_angle * p
            
        # Phase 3: Wave Cascade (40% - 65%)
        elif progress < 0.65:
            p = (progress - 0.4) / 0.25
            
            wave_delay = card_index * 0.15
            card_p = max(0, min(1, (p - wave_delay) / (1 - wave_delay)))
            card_p = card_p * card_p * (3 - 2 * card_p)
            
            if card_p <= 0:
                tornado_end = 180
                fan_angle_base = -30
                fan_angle_range = 60
                start_angle = fan_angle_base + (fan_angle_range / (num_cards - 1)) * card_index
                final_angle = start_angle + tornado_end
                radius = 70
                
                x = radius * math.cos(math.radians(final_angle))
                y = radius * math.sin(math.radians(final_angle))
                rotation = final_angle + 90 + card_index * 5
            else:
                fan_angle_base = -30
                fan_angle_range = 60
                start_angle = fan_angle_base + (fan_angle_range / (num_cards - 1)) * card_index + 180
                start_radius = 70
                start_x = start_radius * math.cos(math.radians(start_angle))
                start_y = start_radius * math.sin(math.radians(start_angle))
                
                end_angle = 180 - start_angle
                end_x = -start_x
                end_y = start_y
                
                x = start_x + (end_x - start_x) * card_p
                arc_height = 40 * math.sin(card_p * math.pi)
                y = start_y + (end_y - start_y) * card_p - arc_height
                
                start_rotation = start_angle + 90 + card_index * 5
                end_rotation = end_angle + 90
                rotation = start_rotation + (end_rotation - start_rotation) * card_p + 360 * card_p
                
        # Phase 4: Orbital Display (65% - 85%)
        elif progress < 0.85:
            p = (progress - 0.65) / 0.2
            p = p * p * (3 - 2 * p)
            
            orbit_radius = 50
            base_angle = (360 / num_cards) * card_index
            rotation_offset = p * 180
            final_angle = base_angle + rotation_offset
            
            x = orbit_radius * math.cos(math.radians(final_angle))
            y = orbit_radius * math.sin(math.radians(final_angle))
            rotation = final_angle + 90
            
        # Phase 5: Twirl Back (85% - 100%)
        else:
            p = (progress - 0.85) / 0.15
            p = 1 - math.pow(1 - p, 3)
            
            orbit_radius = 50
            base_angle = (360 / num_cards) * card_index + 180
            
            start_x = orbit_radius * math.cos(math.radians(base_angle))
            start_y = orbit_radius * math.sin(math.radians(base_angle))
            start_rotation = base_angle + 90
            
            twirl_angle = p * 360
            
            x = start_x * (1 - p) + (card_index - 2) * 2 * p
            y = start_y * (1 - p)
            rotation = start_rotation + twirl_angle
        
        return x, y, rotation

    def _get_hand_transform(self, t, is_left):
        """Calculates hand transformation"""
        cycle = t % 2.5
        progress = cycle / 2.5
        
        x, y, rotation = 0, 0, 0
        
        # Phase 1: Pressure Fan (0% - 20%)
        if progress < 0.2:
            p = progress / 0.2
            p = p * p * (3 - 2 * p)
            
            if is_left:
                x = 10 * p
                y = 5 * p
                rotation = 10 * p
            else:
                x = 15 * p
                y = -3 * p
                rotation = -12 * p
                
        # Phase 2: Tornado Spin (20% - 40%)
        elif progress < 0.4:
            p = (progress - 0.2) / 0.2
            p = p * p * (3 - 2 * p)
            
            if is_left:
                angle = p * 180
                x = 10 + 15 * p
                y = 5 + 8 * math.sin(math.radians(angle))
                rotation = 10 + 10 * p
            else:
                x = 15 - 5 * p
                y = -3 + 5 * p
                rotation = -12 + 7 * p
                
        # Phase 3: Wave Cascade (40% - 65%)
        elif progress < 0.65:
            p = (progress - 0.4) / 0.25
            
            if is_left:
                x = 25 + 10 * p
                y = 13 - 8 * p
                rotation = 20 + 5 * p
                y += 3 * math.sin(p * 12)
            else:
                x = 10 + 15 * p
                y = 2 - 5 * p
                rotation = -5 + 10 * p
                
        # Phase 4: Orbital Display (65% - 85%)
        elif progress < 0.85:
            p = (progress - 0.65) / 0.2
            
            if is_left:
                angle = p * 180
                x = 35 + 8 * math.cos(math.radians(angle))
                y = 5 + 8 * math.sin(math.radians(angle))
                rotation = 25 - 10 * p
            else:
                angle = p * 180 + 180
                x = 25 + 8 * math.cos(math.radians(angle))
                y = -3 + 8 * math.sin(math.radians(angle))
                rotation = 5 + 10 * p
                
        # Phase 5: Twirl Back (85% - 100%)
        else:
            p = (progress - 0.85) / 0.15
            p = 1 - math.pow(1 - p, 3)
            
            if is_left:
                start_x = 35
                start_y = 5
                twirl_offset = 6 * math.cos(p * math.pi * 2)
                x = start_x * (1 - p) + twirl_offset
                y = start_y * (1 - p) + 4 * math.sin(p * math.pi * 2)
                rotation = 15 * (1 - p)
            else:
                start_x = 25
                start_y = -3
                twirl_offset = -6 * math.sin(p * math.pi * 2)
                x = start_x * (1 - p) + twirl_offset
                y = start_y * (1 - p) - 4 * math.cos(p * math.pi * 2)
                rotation = 15 * (1 - p)
            
        return x, y, rotation

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        
        t = self._elapsed.elapsed() / 1000.0
        w, h = self.width(), self.height()
        
        # 1. Background
        self._draw_background(p, w, h, t)
        
        # 2. Grid & Decor
        self._draw_grid(p, w, h, t)
        
        # 3. Side Data (Hex dump)
        self._draw_side_data(p, w, h)
        
        # 4. Central Animation (Logo -> Cyber Clown)
        self._draw_central_content(p, w, h, t)
        
        # 5. Loading Bar & Text
        self._draw_loading_bar(p, w, h, t)
        
        # 6. Overlay Scanline
        self._draw_scanline(p, w, h, t)
        
        p.end()

    def _draw_background(self, p: QPainter, w, h, t):
        # Main background with slight gradient
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, self._bg_color)
        grad.setColorAt(1, self._bg_color.darker(150))
        p.fillRect(0, 0, w, h, grad)
        
        # Large faint background text "FORENSICS"
        p.save()
        font = QFont("Impact", 120, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 10)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255, 5), 2)) # Very faint
        p.rotate(-5)
        p.drawText(QRectF(-50, 50, w+100, h), Qt.AlignmentFlag.AlignCenter, "FORENSICS")
        p.restore()
        
        # "ANALYSIS" text at bottom
        p.save()
        font_analysis = QFont("Arial Black", 60, QFont.Weight.Bold)
        p.setFont(font_analysis)
        p.setPen(QPen(QColor(0, 0, 0, 100), 0)) # Shadow
        p.setBrush(QColor(20, 30, 40))
        p.drawText(QRectF(0, h - 120, w, 100), Qt.AlignmentFlag.AlignCenter, "ANALYSIS")
        p.restore()

    def _draw_grid(self, p: QPainter, w, h, t):
        p.save()
        p.setPen(QPen(self._grid_color, 1))
        
        # Horizontal lines
        for i in range(0, h, 40):
            p.drawLine(0, i, w, i)
            
        # Vertical lines
        for i in range(0, w, 40):
            p.drawLine(i, 0, i, h)
            
        # Corner brackets
        corner_len = 30
        p.setPen(QPen(self._cyan, 2))
        
        # Top-Left
        p.drawLine(10, 10, 10 + corner_len, 10)
        p.drawLine(10, 10, 10, 10 + corner_len)
        
        # Top-Right
        p.drawLine(w - 10, 10, w - 10 - corner_len, 10)
        p.drawLine(w - 10, 10, w - 10, 10 + corner_len)
        
        # Bottom-Left
        p.drawLine(10, h - 10, 10 + corner_len, h - 10)
        p.drawLine(10, h - 10, 10, h - 10 - corner_len)
        
        # Bottom-Right
        p.drawLine(w - 10, h - 10, w - 10 - corner_len, h - 10)
        p.drawLine(w - 10, h - 10, w - 10, h - 10 - corner_len)
        
        # Top bar line
        p.setPen(QPen(self._cyan_dim, 1))
        p.drawLine(50, 40, w - 50, 40)
        p.drawText(60, 35, "SECURE ENV")
        p.drawText(w - 150, 35, f"MEM_INTEGRITY: 100%")
        
        # Bottom bar line (Cleaned up)
        p.drawLine(50, h - 40, w - 50, h - 40)
        
        p.restore()

    def _draw_side_data(self, p: QPainter, w, h):
        p.save()
        font = QFont("Consolas", 8)
        p.setFont(font)
        p.setPen(QPen(self._cyan_dim, 1))
        
        # Left side hex dump
        x_start = 20
        y_start = 100
        line_height = 14
        
        for i, line in enumerate(self._hex_lines):
            # Fade out top and bottom
            alpha = 255
            if i < 3: alpha = i * 80
            if i > len(self._hex_lines) - 4: alpha = (len(self._hex_lines) - i) * 80
            
            color = QColor(self._cyan_dim)
            color.setAlpha(min(150, alpha))
            p.setPen(color)
            
            p.drawText(x_start, y_start + i * line_height, line)
            
        p.restore()

    def _draw_central_content(self, p: QPainter, w, h, t):
        p.save()
        cx, cy = w / 2, h / 2 - 20
        p.translate(cx, cy)
        
        # Sequence Logic
        # 0s - 1.5s: Logo Fade In/Out
        # 1.5s - End: Cyber Clown Fade In
        
        logo_opacity = 0.0
        anim_opacity = 0.0
        
        if t < 1.0:
            logo_opacity = min(1.0, t * 2) # Fade in
        elif t < 1.5:
            logo_opacity = max(0.0, 1.0 - (t - 1.0) * 2) # Fade out
        else:
            logo_opacity = 0.0
            anim_opacity = min(1.0, (t - 1.5) * 2) # Fade in animation
            
        # Draw Logo (if visible)
        if logo_opacity > 0:
            p.save()
            p.setOpacity(logo_opacity)
            
            # Hexagon Background for Logo
            path = QPainterPath()
            r = 80
            for i in range(6):
                angle = math.radians(30 + i * 60)
                x = r * math.cos(angle)
                y = r * math.sin(angle)
                if i == 0: path.moveTo(x, y)
                else: path.lineTo(x, y)
            path.closeSubpath()
            
            p.setPen(QPen(self._cyan, 2))
            p.setBrush(QColor(0, 0, 0, 180))
            p.drawPath(path)
            
            if self._pix:
                scaled_pix = self._pix.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(-50, -50, scaled_pix)
            p.restore()
            
        # Draw Cyber Clown (if visible)
        if anim_opacity > 0:
            p.save()
            p.setOpacity(anim_opacity)
            
            # Adjust time for animation loop to start smoothly
            anim_t = t - 1.5
            
            # Draw Clown Body Elements
            self._draw_cyber_clown_hat(p, 0, -60, anim_t)
            self._draw_cyber_clown_head(p, 0, -30)
            self._draw_cyber_clown_body(p, 0, 0)
            
            # Draw Cyber Hands
            left_hand_x, left_hand_y, left_hand_rot = self._get_hand_transform(anim_t, True)
            right_hand_x, right_hand_y, right_hand_rot = self._get_hand_transform(anim_t, False)
            
            self._draw_cyber_hand(p, -70 + left_hand_x, 30 + left_hand_y, is_left=True)
            self._draw_cyber_hand(p, 70 + right_hand_x, 30 + right_hand_y, is_left=False)
            
            # Draw Cyber Cards
            card_data = [
                (0, 50, 'A'), (0, 50, 'K'), (0, 50, 'Q'), (0, 50, 'J'), (0, 50, '10')
            ]
            
            for i, (base_x, base_y, rank) in enumerate(card_data):
                dx, dy, rotation = self._get_card_transform(anim_t, i)
                self._draw_cyber_card(p, base_x + dx, base_y + dy, rotation, rank)
                
            p.restore()
            
        p.restore()

    def _draw_cyber_clown_hat(self, p: QPainter, x, y, t):
        """Volumetric Green Hair"""
        p.save()
        p.translate(x, y)
        
        # Hair bounce
        bounce = -3 * abs(math.sin(1.5 * math.pi * t))
        scale_x = 1.0 + 0.05 * math.sin(3.0 * math.pi * t)
        p.translate(0, bounce)
        p.scale(scale_x, 1.0)
        
        # Base Hair Shape (Darker Green)
        hair_path = QPainterPath()
        hair_path.moveTo(-35, 10)
        hair_path.lineTo(-45, -10)
        hair_path.lineTo(-30, -5)
        hair_path.lineTo(-40, -25)
        hair_path.lineTo(-20, -15)
        hair_path.lineTo(-10, -35)
        hair_path.lineTo(0, -20)
        hair_path.lineTo(10, -35)
        hair_path.lineTo(20, -15)
        hair_path.lineTo(40, -25)
        hair_path.lineTo(30, -5)
        hair_path.lineTo(45, -10)
        hair_path.lineTo(35, 10)
        hair_path.quadTo(0, 5, -35, 10)
        
        # Gradient for Volume
        grad = QRadialGradient(0, -10, 40)
        grad.setColorAt(0, QColor(0, 100, 0))     # Dark Green Center
        grad.setColorAt(1, QColor(0, 255, 0))     # Neon Green Edges
        
        p.setBrush(grad)
        p.setPen(QPen(QColor(0, 255, 0), 1))
        p.drawPath(hair_path)
        
        # Add some stray hairs for detail
        p.setPen(QPen(QColor(0, 255, 0, 150), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(5):
             p.drawArc(QRectF(-40 + i*15, -30 + (i%2)*5, 10, 10), 0, 180 * 16)
        
        p.restore()

    def _draw_cyber_clown_head(self, p: QPainter, x, y):
        """3D Sinister Joker Head"""
        p.save()
        p.translate(x, y)
        
        # Face Shape
        face_path = QPainterPath()
        face_path.moveTo(-25, -20)
        face_path.lineTo(-25, 10)
        face_path.quadTo(0, 45, 25, 10) # Sharper chin
        face_path.lineTo(25, -20)
        face_path.quadTo(0, -30, -25, -20)
        
        # 3D Skin Gradient (Pale/Dead)
        skin_grad = QRadialGradient(-10, -10, 50)
        skin_grad.setColorAt(0, QColor(240, 240, 255)) # Pale White
        skin_grad.setColorAt(1, QColor(180, 180, 200)) # Grayish Shadow
        
        p.setBrush(skin_grad)
        p.setPen(QPen(QColor(100, 100, 100), 1))
        p.drawPath(face_path)
        
        # Eyes (Sunken & Evil)
        # Sockets
        p.setBrush(QColor(20, 10, 30)) # Dark purple/black
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(-16, -12, 10, 10))
        p.drawEllipse(QRectF(6, -12, 10, 10))
        
        # Glowing Pupils
        p.setBrush(self._purple)
        p.drawEllipse(QRectF(-13, -9, 4, 4))
        p.drawEllipse(QRectF(9, -9, 4, 4))
        
        # Nose (Red & Shaded)
        nose_grad = QRadialGradient(-2, -2, 6)
        nose_grad.setColorAt(0, QColor(255, 100, 100))
        nose_grad.setColorAt(1, QColor(150, 0, 0))
        p.setBrush(nose_grad)
        p.drawEllipse(QRectF(-4, 0, 8, 8))
        
        # Glasgow Smile (Scarred & Wide)
        p.setPen(QPen(QColor(180, 0, 0), 2)) # Blood red
        p.setBrush(Qt.BrushStyle.NoBrush)
        
        mouth_path = QPainterPath()
        mouth_path.moveTo(-28, 12) # Way out left
        mouth_path.quadTo(-15, 18, 0, 20) # Lower lip curve
        mouth_path.quadTo(15, 18, 28, 12) # Way out right
        
        # Upper lip jagged
        mouth_path.moveTo(-28, 12)
        mouth_path.lineTo(-20, 15)
        mouth_path.lineTo(0, 18)
        mouth_path.lineTo(20, 15)
        mouth_path.lineTo(28, 12)
        
        p.drawPath(mouth_path)
        
        # Scars
        p.setPen(QPen(QColor(100, 0, 0, 100), 1))
        p.drawLine(-28, 12, -32, 8)
        p.drawLine(28, 12, 32, 8)
        
        p.restore()

    def _draw_cyber_clown_body(self, p: QPainter, x, y):
        """3D Purple Suit"""
        p.save()
        p.translate(x, y)
        
        # Suit Shape
        body_path = QPainterPath()
        body_path.moveTo(-30, 0)
        body_path.lineTo(-38, 60) # Broader shoulders
        body_path.lineTo(38, 60)
        body_path.lineTo(30, 0)
        body_path.closeSubpath()
        
        # Suit Gradient (Velvet Purple)
        suit_grad = QLinearGradient(-30, 0, 30, 60)
        suit_grad.setColorAt(0, QColor(100, 0, 150))
        suit_grad.setColorAt(0.5, QColor(60, 0, 100))
        suit_grad.setColorAt(1, QColor(30, 0, 60))
        
        p.setBrush(suit_grad)
        p.setPen(QPen(QColor(20, 0, 40), 1))
        p.drawPath(body_path)
        
        # Lapels (Lighter Purple)
        p.setBrush(QColor(120, 0, 180))
        lapel_path = QPainterPath()
        lapel_path.moveTo(-30, 0)
        lapel_path.lineTo(-15, 35)
        lapel_path.lineTo(-10, 0)
        p.drawPath(lapel_path)
        
        lapel_path_r = QPainterPath()
        lapel_path_r.moveTo(30, 0)
        lapel_path_r.lineTo(15, 35)
        lapel_path_r.lineTo(10, 0)
        p.drawPath(lapel_path_r)
        
        # Shirt (Green)
        p.setBrush(QColor(0, 100, 50))
        p.drawPolygon([QPointF(-10, 0), QPointF(10, 0), QPointF(0, 25)])
        
        # Tie (Yellow/Orange Pattern)
        tie_path = QPainterPath()
        tie_path.moveTo(0, 25)
        tie_path.lineTo(-4, 55)
        tie_path.lineTo(4, 55)
        tie_path.closeSubpath()
        
        p.setBrush(QColor(200, 150, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(tie_path)
        
        p.restore()

    def _draw_cyber_hand(self, p: QPainter, x, y, is_left=False):
        p.save()
        p.translate(x, y)
        p.scale(1.6, 1.6)
        if is_left: p.scale(-1, 1)
        
        # Wireframe Hand Style
        p.setBrush(QColor(0, 0, 0, 150))
        p.setPen(QPen(self._purple, 1))
        
        # Palm
        p.drawEllipse(QRectF(-12, -12, 24, 24))
        # Tech nodes on palm
        p.setBrush(self._cyan)
        p.drawEllipse(QRectF(-4, -4, 8, 8))
        p.setBrush(QColor(0, 0, 0, 150))
        
        # Fingers (Wireframe lines)
        p.drawLine(0, 0, 15, -8) # Thumb
        p.drawLine(0, 0, 17, -10) # Index
        p.drawLine(0, 0, 20, -3) # Middle
        p.drawLine(0, 0, 18, 4) # Ring
        p.drawLine(0, 0, 14, 10) # Pinky
        
        # Finger tips (Glowing nodes)
        p.setBrush(self._purple)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(13, -10, 4, 4))
        p.drawEllipse(QRectF(15, -12, 4, 4))
        p.drawEllipse(QRectF(18, -5, 4, 4))
        p.drawEllipse(QRectF(16, 2, 4, 4))
        p.drawEllipse(QRectF(12, 8, 4, 4))
        
        p.restore()

    def _draw_cyber_card(self, p: QPainter, x, y, rotation, rank):
        p.save()
        p.translate(x, y)
        p.rotate(rotation)
        
        w, h = 40, 60
        
        # Card Body (Glass effect)
        p.setBrush(QColor(0, 255, 255, 20))
        p.setPen(QPen(self._cyan, 1))
        p.drawRoundedRect(QRectF(-w/2, -h/2, w, h), 4, 4)
        
        # Rank Text
        p.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        p.setPen(self._cyan)
        p.drawText(QRectF(-w/2, -h/2, w, h), Qt.AlignmentFlag.AlignCenter, rank)
        
        # Decor lines
        p.drawLine(int(-w/2), int(-h/2 + 10), int(-w/2 + 10), int(-h/2))
        p.drawLine(int(w/2), int(h/2 - 10), int(w/2 - 10), int(h/2))
        
        p.restore()

    def _draw_loading_bar(self, p: QPainter, w, h, t):
        p.save()
        
        # 优化: 确保进度条能到达100%
        # 4.5秒内完成,给主窗口切换留出0.5秒缓冲
        progress = min(1.0, t / 4.5)
        
        bar_w = 400
        bar_h = 6
        x = (w - bar_w) / 2
        y = h - 80
        
        # Label "KOI" - Centered and Large, no overlap
        p.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        p.setPen(self._text_color)
        # Positioned slightly above the loading bar area
        p.drawText(QRectF(0, y - 60, w, 40), Qt.AlignmentFlag.AlignCenter, "KOI")
        
        # Version Number
        p.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        p.setPen(self._cyan_dim)
        p.drawText(QRectF(0, y - 30, w, 20), Qt.AlignmentFlag.AlignCenter, f"v{self.version}")
        
        # Removed "LUXE EDITION" as requested
        
        # Background bar
        p.setBrush(QColor(30, 30, 30))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(int(x), int(y), int(bar_w), int(bar_h))
        
        # Fill bar (Gradient)
        grad = QLinearGradient(x, y, x + bar_w, y)
        grad.setColorAt(0, self._purple)
        grad.setColorAt(1, self._cyan)
        
        p.setBrush(grad)
        p.drawRect(int(x), int(y), int(bar_w * progress), int(bar_h))
        
        # Percentage
        p.setPen(self._cyan)
        p.drawText(x + bar_w + 10, y + 7, f"{int(progress * 100)}%")
        
        # Console logs simulation (Moved lower to avoid overlap)
        log_y = y + 20
        p.setFont(QFont("Consolas", 8))
        
        logs = [
            "> SYS.INIT [OK]",
            "> LOAD.MODULES [OK]",
            "> SECURE.CHANNEL [OK]",
            "> USER.AUTH [OK]"
        ]
        
        # Show logs based on time
        # Speed up log display to ensure all are shown
        num_logs = min(len(logs), int(t * 2.0) + 1)
        for i in range(num_logs):
            # All logs green for success
            p.setPen(self._success_green)
            
            # Draw logs centered below bar
            p.drawText(QRectF(0, log_y + i * 15, w, 15), Qt.AlignmentFlag.AlignCenter, logs[i])
            
        p.restore()

    def _draw_scanline(self, p: QPainter, w, h, t):
        # Horizontal scanline moving down
        scan_y = (t * 200) % h
        
        grad = QLinearGradient(0, scan_y, 0, scan_y + 20)
        grad.setColorAt(0, QColor(0, 255, 255, 0))
        grad.setColorAt(0.5, QColor(0, 255, 255, 50))
        grad.setColorAt(1, QColor(0, 255, 255, 0))
        
        p.fillRect(0, scan_y, w, 20, grad)


def show_splash():
    """
    创建并显示启动动画窗口 (用于线程模式)
    返回窗口实例以便后续关闭
    """
    import sys
    import os
    import json
    from PySide6.QtWidgets import QApplication
    
    # 检查是否已有 QApplication 实例
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    # 获取图标路径和版本号
    def get_resource_path(relative_path):
        """获取资源文件的绝对路径"""
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(base_path, relative_path)
    
    def get_version():
        """从配置文件获取版本号"""
        try:
            from modules.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            app_config = config_manager.get_config('app')
            version = app_config.get('version')
            if version:
                return version
        except Exception:
            pass
        return None  # 返回 None 而不是硬编码版本号
    
    icon_path = get_resource_path("1.ico")
    version = get_version() or "未知版本"
    
    # 创建并显示动画窗口
    splash = AnimatedSplash(
        icon_path if os.path.exists(icon_path) else None, 
        version=version
    )
    splash.showCentered()
    
    # 处理事件以显示窗口
    app.processEvents()
    
    return splash
