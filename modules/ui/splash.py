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
        self._red = QColor(204, 0, 0)  # Darker red
        self._transparent_bg = QColor(0, 0, 0, 220)
        
        # Joker Colors
        self._suit_color = QColor(102, 0, 153)      # Deep Purple
        self._shirt_color = QColor(50, 205, 50)     # Lime Green
        self._hair_color = QColor(0, 153, 51)       # Darker Green
        self._skin_color = QColor(255, 255, 255)    # Pale White
        self._lip_color = QColor(180, 0, 0)         # Blood Red
        self._eye_makeup = QColor(0, 0, 0, 180)     # Dark makeup
        
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
        """计算卡牌的变换参数 - 炫酷花切动画 (Fan -> Spring -> Orbit)"""
        cycle = t % 5.0  # 5秒一个循环
        progress = cycle / 5.0
        
        x, y, rotation = 0, 0, 0
        
        # 阶段1: 扇形展开 (0% - 20%)
        if progress < 0.2:
            p = progress / 0.2
            # 缓动
            p = 1 - math.pow(1 - p, 3)
            
            # 扇形展开角度
            spread = 40
            base_angle = -spread + (spread * card_index)
            
            # 向上移动并展开
            y = -30 * p
            x = (card_index - 1) * 20 * p
            rotation = base_angle * p
            
        # 阶段2: 准备弹牌 (20% - 25%)
        elif progress < 0.25:
            p = (progress - 0.2) / 0.05
            # 收缩准备
            y = -30 + 10 * p
            x = (card_index - 1) * 20 * (1 - p)
            rotation = (-40 + (40 * card_index)) * (1 - p)
            
        # 阶段3: 弹牌 (Spring) - 从左手飞向右手 (25% - 55%)
        elif progress < 0.55:
            p = (progress - 0.25) / 0.3
            
            # 每张牌有延迟
            delay = card_index * 0.05
            card_p = (p - delay) / (1 - 0.15) # 归一化
            
            if card_p < 0: # 还没开始飞
                x, y = 0, -20
            elif card_p > 1: # 已经到达
                x, y = 0, -20
            else:
                # 抛物线轨迹
                # 起点 (左手位置附近) -> 终点 (右手位置附近)
                start_x = -60
                end_x = 60
                
                # 当前X
                x = start_x + (end_x - start_x) * card_p
                
                # 抛物线高度
                arch = 100 * math.sin(card_p * math.pi)
                y = -20 - arch
                
                # 旋转 (飞速旋转)
                rotation = card_p * 720
                
        # 阶段4: 环绕旋转 (Orbit) (55% - 85%)
        elif progress < 0.85:
            p = (progress - 0.55) / 0.3
            
            # 围绕中心旋转
            radius = 60
            angle = p * 4 * math.pi + (card_index * 2 * math.pi / 3)
            
            x = radius * math.cos(angle)
            y = radius * math.sin(angle) - 20
            rotation = math.degrees(angle) + 90
            
        # 阶段5: 回收 (85% - 100%)
        else:
            p = (progress - 0.85) / 0.15
            p = 1 - math.pow(1 - p, 3) # 缓出
            
            # 从上一个位置回到中心
            # 这里简化处理，直接从最后的轨道位置回归
            last_angle = 4 * math.pi + (card_index * 2 * math.pi / 3)
            start_x = 60 * math.cos(last_angle)
            start_y = 60 * math.sin(last_angle) - 20
            
            x = start_x * (1 - p)
            y = start_y * (1 - p)
            rotation = (math.degrees(last_angle) + 90) * (1 - p)
        
        return x, y, rotation
    
    def _get_hand_transform(self, t, is_left):
        """计算手的变换参数 - 配合花切"""
        cycle = t % 5.0
        progress = cycle / 5.0
        
        direction = -1 if is_left else 1
        x, y, rotation = 0, 0, 0
        
        # 阶段1: 扇形展示 (双手张开)
        if progress < 0.2:
            p = progress / 0.2
            p = 1 - math.pow(1 - p, 3)
            x = 20 * direction * p
            y = 10 * p
            rotation = -10 * direction * p
            
        # 阶段2: 准备 (双手靠近)
        elif progress < 0.25:
            p = (progress - 0.2) / 0.05
            x = 20 * direction * (1 - p)
            y = 10 * (1 - p)
            rotation = -10 * direction * (1 - p)
            
        # 阶段3: 弹牌 (双手拉开距离)
        elif progress < 0.55:
            p = (progress - 0.25) / 0.3
            # 保持拉开姿势
            x = 40 * direction
            y = -10
            rotation = -20 * direction
            
            # 微动
            y += 5 * math.sin(p * 10)
            
        # 阶段4: 指挥旋转 (双手画圈)
        elif progress < 0.85:
            p = (progress - 0.55) / 0.3
            angle = p * 2 * math.pi
            
            x = 30 * direction + 10 * math.cos(angle)
            y = 10 * math.sin(angle)
            rotation = -10 * direction
            
        # 阶段5: 接牌 (回到原位)
        else:
            p = (progress - 0.85) / 0.15
            start_x = 30 * direction + 10 # 约略位置
            
            x = start_x * (1 - p)
            y = 0
            rotation = -10 * direction * (1 - p)
            
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
        
        # 绘制小丑头发
        self._draw_clown_hat(p, center_x, center_y - 60, t)
        
        # 绘制小丑头部
        self._draw_clown_head(p, center_x, center_y - 30)
        
        # 绘制小丑身体
        self._draw_clown_body(p, center_x, center_y)
        
        # 绘制小丑手
        left_hand_x, left_hand_y, left_hand_rot = self._get_hand_transform(t, True)
        right_hand_x, right_hand_y, right_hand_rot = self._get_hand_transform(t, False)
        self._draw_clown_hand(p, center_x - 70 + left_hand_x, center_y + 30 + left_hand_y, is_left=True)
        self._draw_clown_hand(p, center_x + 70 + right_hand_x, center_y + 30 + right_hand_y, is_left=False)
        
        # 绘制扑克牌
        card_data = [
            (center_x, center_y + 80, '♠', 'A', self._black),
            (center_x, center_y + 80, '♥', 'K', self._red),
            (center_x, center_y + 80, '♦', 'Q', self._red),
            (center_x, center_y + 80, '♣', 'J', self._black),
            (center_x, center_y + 80, '♠', '10', self._black)
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
        """绘制小丑头发 (替代帽子)"""
        p.save()
        p.translate(x, y)
        
        # 头发随节奏跳动
        bounce = -3 * abs(math.sin(1.5 * math.pi * t))
        scale_x = 1.0 + 0.05 * math.sin(3.0 * math.pi * t)
        p.translate(0, bounce)
        p.scale(scale_x, 1.0)
        
        # 狂野的头发路径
        hair_path = QPainterPath()
        hair_path.moveTo(-35, 10)
        # 左侧乱发
        hair_path.lineTo(-45, -10)
        hair_path.lineTo(-30, -5)
        hair_path.lineTo(-40, -25)
        hair_path.lineTo(-20, -15)
        # 顶部乱发
        hair_path.lineTo(-10, -35)
        hair_path.lineTo(0, -20)
        hair_path.lineTo(10, -35)
        hair_path.lineTo(20, -15)
        # 右侧乱发
        hair_path.lineTo(40, -25)
        hair_path.lineTo(30, -5)
        hair_path.lineTo(45, -10)
        hair_path.lineTo(35, 10)
        # 底部闭合
        hair_path.quadTo(0, 5, -35, 10)
        
        p.setBrush(QBrush(self._hair_color))
        p.setPen(QPen(self._black, 1))
        p.drawPath(hair_path)
        
        p.restore()
    
    def _draw_clown_head(self, p: QPainter, x, y):
        """绘制小丑头部 (更细致)"""
        p.save()
        p.translate(x, y)
        
        # 脸型 (稍微尖一点的下巴)
        face_path = QPainterPath()
        face_path.moveTo(-25, -20)
        face_path.lineTo(-25, 10)
        face_path.quadTo(0, 40, 25, 10) # 下巴
        face_path.lineTo(25, -20)
        face_path.quadTo(0, -30, -25, -20) # 额头
        
        p.setBrush(QBrush(self._skin_color))
        p.setPen(QPen(self._black, 2))
        p.drawPath(face_path)
        
        # 眼睛 (菱形妆容)
        p.setBrush(QBrush(self._eye_makeup))
        p.setPen(Qt.PenStyle.NoPen)
        
        # 左眼妆
        path_eye_l = QPainterPath()
        path_eye_l.moveTo(-15, -5)
        path_eye_l.lineTo(-15, -15)
        path_eye_l.lineTo(-10, -5)
        path_eye_l.lineTo(-15, 5)
        path_eye_l.lineTo(-20, -5)
        path_eye_l.closeSubpath()
        p.drawPath(path_eye_l)
        
        # 右眼妆
        path_eye_r = QPainterPath()
        path_eye_r.moveTo(15, -5)
        path_eye_r.lineTo(15, -15)
        path_eye_r.lineTo(20, -5)
        path_eye_r.lineTo(15, 5)
        path_eye_r.lineTo(10, -5)
        path_eye_r.closeSubpath()
        p.drawPath(path_eye_r)
        
        # 眼球
        p.setBrush(QBrush(self._black))
        p.drawEllipse(QRectF(-17, -7, 4, 4))
        p.drawEllipse(QRectF(13, -7, 4, 4))
        
        # 鼻子 (小一点，深红色)
        p.setBrush(QBrush(self._red))
        p.drawEllipse(QRectF(-4, 0, 8, 8))
        
        # 嘴巴 (夸张的笑容)
        p.setPen(QPen(self._lip_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        mouth_path = QPainterPath()
        mouth_path.moveTo(-20, 15)
        mouth_path.quadTo(0, 35, 20, 15) # 下唇线
        p.drawPath(mouth_path)
        
        mouth_upper = QPainterPath()
        mouth_upper.moveTo(-22, 13)
        mouth_upper.quadTo(0, 25, 22, 13) # 上唇线 (笑得更开)
        p.drawPath(mouth_upper)
        
        # 伤疤/嘴角延伸
        p.setPen(QPen(self._lip_color, 1))
        p.drawLine(-22, 13, -26, 10)
        p.drawLine(22, 13, 26, 10)
        
        p.restore()
    
    def _draw_clown_body(self, p: QPainter, x, y):
        """绘制小丑身体 (西装)"""
        p.save()
        p.translate(x, y)
        
        # 身体轮廓 (西装)
        body_path = QPainterPath()
        body_path.moveTo(-30, 0)
        body_path.lineTo(-35, 60) # 左肩向下
        body_path.lineTo(35, 60)  # 右肩向下
        body_path.lineTo(30, 0)
        body_path.closeSubpath()
        
        p.setBrush(QBrush(self._suit_color))
        p.setPen(QPen(self._black, 2))
        p.drawPath(body_path)
        
        # 衬衫 (V领区域)
        shirt_path = QPainterPath()
        shirt_path.moveTo(-15, 0)
        shirt_path.lineTo(0, 25)
        shirt_path.lineTo(15, 0)
        shirt_path.closeSubpath()
        p.setBrush(QBrush(self._shirt_color))
        p.drawPath(shirt_path)
        
        # 领带/领结
        p.setBrush(QBrush(QColor(50, 50, 50))) # 深色领带
        tie_path = QPainterPath()
        tie_path.moveTo(0, 25)
        tie_path.lineTo(-5, 55)
        tie_path.lineTo(5, 55)
        tie_path.closeSubpath()
        p.drawPath(tie_path)
        
        # 领结结头
        p.setBrush(QBrush(QColor(30, 30, 30)))
        p.drawEllipse(QRectF(-3, 22, 6, 6))
        
        # 西装领子 (Lapels)
        p.setBrush(QBrush(self._suit_color.darker(110))) # 稍深一点
        
        lapel_l = QPainterPath()
        lapel_l.moveTo(-30, 0)
        lapel_l.lineTo(-15, 0)
        lapel_l.lineTo(0, 35)
        lapel_l.lineTo(-10, 35)
        lapel_l.closeSubpath()
        p.drawPath(lapel_l)
        
        lapel_r = QPainterPath()
        lapel_r.moveTo(30, 0)
        lapel_r.lineTo(15, 0)
        lapel_r.lineTo(0, 35)
        lapel_r.lineTo(10, 35)
        lapel_r.closeSubpath()
        p.drawPath(lapel_r)
        
        # 胸花
        p.setBrush(QBrush(QColor(255, 200, 0))) # 黄色花
        p.drawEllipse(QRectF(15, 10, 8, 8))
        
        p.restore()
    
    def _draw_clown_hand(self, p: QPainter, x, y, is_left=False):
        """绘制小丑的手 (带手指，支持镜像，解剖学优化)"""
        p.save()
        p.translate(x, y)
        
        # 放大手部
        p.scale(1.6, 1.6)
        
        # 镜像处理 (如果是左手，水平翻转)
        if is_left:
            p.scale(-1, 1)
        
        p.setBrush(QBrush(self._white)) # 白手套
        p.setPen(QPen(self._black, 1))
        
        # 手掌 (稍微宽一点)
        p.drawEllipse(QRectF(-12, -12, 24, 24))
        
        # 手指 (优化长度和位置)
        # 拇指 (短粗，角度大)
        p.save()
        p.rotate(-50)
        p.drawEllipse(QRectF(10, -5, 10, 10))
        p.restore()
        
        # 食指 (中等)
        p.drawEllipse(QRectF(10, -10, 14, 7))
        # 中指 (最长)
        p.drawEllipse(QRectF(12, -3, 16, 7))
        # 无名指 (稍短)
        p.drawEllipse(QRectF(11, 4, 14, 7))
        # 小指 (最短)
        p.drawEllipse(QRectF(9, 10, 10, 6))
        
        p.restore()
    
    def _draw_playing_card(self, p: QPainter, x, y, rotation, suit, rank, color):
        """绘制扑克牌 (更真实)"""
        p.save()
        p.translate(x, y)
        p.rotate(rotation)
        
        # 卡牌尺寸
        card_width, card_height = 40, 60
        half_w, half_h = card_width / 2, card_height / 2
        
        # 绘制白色卡牌背景
        p.setBrush(QBrush(self._white))
        p.setPen(QPen(self._black, 1))
        p.drawRoundedRect(QRectF(-half_w, -half_h, card_width, card_height), 4, 4)
        
        # 内部装饰线
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawRoundedRect(QRectF(-half_w + 4, -half_h + 4, card_width - 8, card_height - 8), 2, 2)
        
        # 字体设置
        font_corner = QFont("Arial", 9, QFont.Weight.Bold)
        font_center = QFont("Arial", 24, QFont.Weight.Bold)
        
        # 绘制左上角
        p.setPen(color)
        p.setFont(font_corner)
        p.drawText(QRectF(-half_w + 2, -half_h + 2, 15, 15), Qt.AlignmentFlag.AlignCenter, rank)
        p.drawText(QRectF(-half_w + 2, -half_h + 12, 15, 15), Qt.AlignmentFlag.AlignCenter, suit)
        
        # 绘制右下角 (旋转180度)
        p.save()
        p.translate(half_w - 2, half_h - 2)
        p.rotate(180)
        p.drawText(QRectF(0, 0, 15, 15), Qt.AlignmentFlag.AlignCenter, rank)
        p.drawText(QRectF(0, 10, 15, 15), Qt.AlignmentFlag.AlignCenter, suit)
        p.restore()
        
        # 绘制中间大花色
        p.setFont(font_center)
        p.drawText(QRectF(-half_w, -half_h, card_width, card_height), Qt.AlignmentFlag.AlignCenter, suit)
        
        p.restore()
