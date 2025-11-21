import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QFont

class AnimatedSplash(QWidget):
    def __init__(self, icon_path: str | None = None):
        super().__init__(parent=None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedSize(400, 360)
        self._pix = QPixmap(icon_path) if icon_path and not QPixmap(icon_path).isNull() else None
        
        # 预缓存颜色对象，避免重复创建
        self._black = QColor(0, 0, 0)
        self._white = QColor(255, 255, 255)
        self._red = QColor(255, 0, 0)
        self._transparent_bg = QColor(0, 0, 0, 220)
        self._hat_color = QColor(255, 102, 102)
        self._body_color = QColor(85, 153, 255)
        self._hand_color = QColor(255, 204, 204)
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(8)  # 120fps，极致流畅
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        print("使用小丑花切扑克牌加载动画 (120fps)")

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
        """计算卡牌的变换参数 - 完整花切动画（优化版）"""
        cycle = t % 6.0
        progress = cycle / 6.0
        
        # 不同卡牌的延迟
        delays = [0.0, 0.083, 0.167]
        delay = delays[card_index]
        adjusted_progress = (progress - delay) % 1.0
        
        x, y, rotation = 0, 0, 0
        
        # 完整的花切和飞牌动画序列
        if adjusted_progress < 0.033:  # 花切开始
            factor = adjusted_progress / 0.033
            y = -20 * factor
            rotation = (15 if card_index == 2 else -15 if card_index == 0 else 0) * factor
        elif adjusted_progress < 0.083:  # 花切上升
            factor = (adjusted_progress - 0.033) / 0.05
            base_y = -20
            y = base_y + (-5 if card_index == 1 else -5) * factor
            rotation = (25 if card_index == 2 else -25 if card_index == 0 else 0) * factor
        elif adjusted_progress < 0.125:  # 花切下降
            factor = (adjusted_progress - 0.083) / 0.042
            y = -25 + 15 * factor
            rotation = (25 if card_index == 2 else -25 if card_index == 0 else 0) * (1 - factor)
        elif adjusted_progress < 0.167:  # 花切回落
            factor = (adjusted_progress - 0.125) / 0.042
            y = -10 + 10 * factor
            rotation = (10 if card_index == 2 else -10 if card_index == 0 else 0) * (1 - factor)
        elif adjusted_progress < 0.208:  # 飞牌第一阶段 - 向左上方飞出
            factor = (adjusted_progress - 0.167) / 0.041
            x = -50 * factor
            y = -50 * factor
            rotation = -90 * factor
        elif adjusted_progress < 0.25:  # 飞牌第二阶段 - 向左飞行
            factor = (adjusted_progress - 0.208) / 0.042
            x = -50 - 50 * factor
            y = -50 + 50 * factor
            rotation = -90 - 90 * factor
        elif adjusted_progress < 0.292:  # 飞牌第三阶段 - 绕到底部
            factor = (adjusted_progress - 0.25) / 0.042
            x = -100 + 50 * factor
            y = 50 * factor
            rotation = -180 - 90 * factor
        elif adjusted_progress < 0.333:  # 飞牌第四阶段 - 绕到右侧
            factor = (adjusted_progress - 0.292) / 0.041
            x = -50 + 100 * factor
            y = 50
            rotation = -270 - 90 * factor
        elif adjusted_progress < 0.375:  # 飞牌第五阶段 - 回到右上
            factor = (adjusted_progress - 0.333) / 0.042
            x = 50 + 50 * factor
            y = 50 - 50 * factor
            rotation = -360 - 90 * factor
        elif adjusted_progress < 0.417:  # 飞牌第六阶段 - 回到手上
            factor = (adjusted_progress - 0.375) / 0.042
            x = 100 - 100 * factor
            y = 0
            rotation = -450 - 90 * factor
        # else: 暂停在原位
        
        return x, y, rotation
    
    def _get_hand_transform(self, t, is_left):
        """计算手的变换参数 - 完整动画"""
        cycle = t % 6.0
        progress = cycle / 6.0
        
        direction = -1 if is_left else 1
        x, y, rotation = 0, 0, 0
        
        if progress < 0.033:  # 花切动作
            factor = progress / 0.033
            x = 15 * direction * factor
            y = -10 * factor
            rotation = -15 * direction * factor
        elif progress < 0.083:
            factor = (progress - 0.033) / 0.05
            x = 15 * direction + 5 * direction * factor
            y = -10 - 5 * factor
            rotation = -15 * direction - 5 * direction * factor
        elif progress < 0.125:
            factor = (progress - 0.083) / 0.042
            x = 20 * direction - 10 * direction * factor
            y = -15 + 10 * factor
            rotation = -20 * direction + 10 * direction * factor
        elif progress < 0.167:
            factor = (progress - 0.125) / 0.042
            x = 10 * direction - 10 * direction * factor
            y = -5 + 5 * factor
            rotation = -10 * direction + 10 * direction * factor
        elif progress < 0.208:  # 手向上抬准备发牌
            factor = (progress - 0.167) / 0.041
            x = 10 * direction * factor
            y = -20 * factor
            rotation = -25 * direction * factor
        elif progress < 0.25:  # 手进行发牌动作
            factor = (progress - 0.208) / 0.042
            x = 10 * direction + 10 * direction * factor
            y = -20 - 10 * factor
            rotation = -25 * direction - 10 * direction * factor
        elif progress < 0.292:  # 手回到身侧
            factor = (progress - 0.25) / 0.042
            x = 20 * direction - 15 * direction * factor
            y = -30 + 20 * factor
            rotation = -35 * direction + 20 * direction * factor
        elif progress < 0.333:
            factor = (progress - 0.292) / 0.041
            x = 5 * direction - 5 * direction * factor
            y = -10 + 10 * factor
            rotation = -15 * direction + 15 * direction * factor
        elif progress < 0.375:  # 等待接牌
            factor = (progress - 0.333) / 0.042
            x = 10 * direction * factor
        elif progress < 0.417:  # 手向外伸准备接牌
            factor = (progress - 0.375) / 0.042
            x = 10 * direction + 20 * direction * factor
            y = -10 * factor
            rotation = -15 * direction * factor
        elif progress < 0.458:  # 接住牌
            factor = (progress - 0.417) / 0.041
            x = 30 * direction - 10 * direction * factor
            y = -10 + 5 * factor
            rotation = -15 * direction + 5 * direction * factor
        elif progress < 0.5:  # 手回到初始位置
            factor = (progress - 0.458) / 0.042
            x = 20 * direction - 20 * direction * factor
            y = -5 + 5 * factor
            rotation = -10 * direction + 10 * direction * factor
        # else: 暂停
        
        return x, y, rotation

    def paintEvent(self, _):
        p = QPainter(self)
        # 开启高质量渲染以支持120fps
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        
        # 完全透明背景（不绘制背景板）
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        
        t = self._elapsed.elapsed() / 1000.0
        center_x, center_y = self.width() / 2, 140
        
        # 绘制小丑帽子
        self._draw_clown_hat(p, center_x, center_y - 60, t)
        
        # 绘制小丑头部
        self._draw_clown_head(p, center_x, center_y - 30)
        
        # 绘制小丑身体
        self._draw_clown_body(p, center_x, center_y)
        
        # 绘制小丑手
        left_hand_x, left_hand_y, left_hand_rot = self._get_hand_transform(t, True)
        right_hand_x, right_hand_y, right_hand_rot = self._get_hand_transform(t, False)
        self._draw_clown_hand(p, center_x - 70 + left_hand_x, center_y + 30 + left_hand_y)
        self._draw_clown_hand(p, center_x + 70 + right_hand_x, center_y + 30 + right_hand_y)
        
        # 绘制扑克牌
        card_data = [
            (center_x - 40, center_y + 110, '♠', 'A', self._black),
            (center_x, center_y + 110, '♥', 'K', self._red),
            (center_x + 40, center_y + 110, '♦', 'Q', self._red)
        ]
        
        for i, (base_x, base_y, suit, rank, color) in enumerate(card_data):
            dx, dy, rotation = self._get_card_transform(t, i)
            self._draw_playing_card(p, base_x + dx, base_y + dy, rotation, suit, rank, color)
        
        # 绘制加载文本
        p.setPen(self._white)
        font = QFont("Microsoft YaHei UI", 10)
        p.setFont(font)
        p.drawText(QRectF(0, self.height() - 70, self.width(), 30), 
                   Qt.AlignmentFlag.AlignCenter, "正在加载，请稍候...")
        
        font_small = QFont("Microsoft YaHei UI", 8)
        p.setFont(font_small)
        p.drawText(QRectF(0, self.height() - 40, self.width(), 20), 
                   Qt.AlignmentFlag.AlignCenter, "首次启动可能需要较长时间")
        
        p.end()
    
    def _draw_clown_hat(self, p: QPainter, x, y, t):
        """绘制小丑帽子"""
        p.save()
        p.translate(x, y)
        
        # 帽子跳动和旋转
        bounce = -5 * abs(math.sin(1.5 * math.pi * t))
        rotation = 5 * math.sin(1.5 * math.pi * t)
        p.translate(0, bounce)
        p.rotate(rotation)
        
        # 三角形帽子
        hat_path = QPainterPath()
        hat_path.moveTo(0, 0)
        hat_path.lineTo(-30, 40)
        hat_path.lineTo(30, 40)
        hat_path.closeSubpath()
        
        p.setBrush(QBrush(self._hat_color))
        p.setPen(QPen(self._black, 2))
        p.drawPath(hat_path)
        
        p.restore()
    
    def _draw_clown_head(self, p: QPainter, x, y):
        """绘制小丑头部"""
        p.save()
        p.translate(x, y)
        
        # 头部
        p.setBrush(QBrush(self._white))
        p.setPen(QPen(self._black, 2))
        p.drawEllipse(QRectF(-30, -30, 60, 60))
        
        # 眼睛
        p.setBrush(QBrush(self._black))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(-20, -15, 10, 15))
        p.drawEllipse(QRectF(10, -15, 10, 15))
        
        # 红鼻子
        p.setBrush(QBrush(self._red))
        p.drawEllipse(QRectF(-7.5, -5, 15, 15))
        
        # 嘴巴
        p.setPen(QPen(self._black, 3))
        mouth_path = QPainterPath()
        mouth_path.moveTo(-15, 10)
        mouth_path.quadTo(0, 25, 15, 10)
        p.drawPath(mouth_path)
        
        p.restore()
    
    def _draw_clown_body(self, p: QPainter, x, y):
        """绘制小丑身体"""
        p.save()
        p.translate(x, y)
        
        p.setBrush(QBrush(self._body_color))
        p.setPen(QPen(self._black, 2))
        p.drawEllipse(QRectF(-25, 0, 50, 70))
        
        p.restore()
    
    def _draw_clown_hand(self, p: QPainter, x, y):
        """绘制小丑的手"""
        p.save()
        p.translate(x, y)
        
        p.setBrush(QBrush(self._hand_color))
        p.setPen(QPen(self._black, 1))
        p.drawEllipse(QRectF(-12.5, -12.5, 25, 25))
        
        p.restore()
    
    def _draw_playing_card(self, p: QPainter, x, y, rotation, suit, rank, color):
        """绘制扑克牌"""
        p.save()
        p.translate(x, y)
        p.rotate(rotation)
        
        # 卡牌尺寸
        card_width, card_height = 40, 60
        half_w, half_h = card_width / 2, card_height / 2
        
        # 绘制白色卡牌背景
        p.setBrush(QBrush(self._white))
        p.setPen(QPen(self._black, 2))
        p.drawRoundedRect(QRectF(-half_w, -half_h, card_width, card_height), 5, 5)
        
        # 绘制左上角的花色
        p.setPen(color)
        font_suit = QFont("Arial", 14, QFont.Weight.Bold)
        p.setFont(font_suit)
        suit_rect = QRectF(-half_w + 3, -half_h + 2, 20, 20)
        p.drawText(suit_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, suit)
        
        # 绘制右下角的点数（旋转180度）
        p.save()
        p.translate(half_w - 3, half_h - 2)
        p.rotate(180)
        font_rank = QFont("Arial", 12, QFont.Weight.Bold)
        p.setFont(font_rank)
        rank_rect = QRectF(0, 0, 20, 20)
        p.drawText(rank_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, rank)
        p.restore()
        
        p.restore()
