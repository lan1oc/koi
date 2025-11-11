from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
import subprocess
from pathlib import Path


class ManualFixDialog(QDialog):
    """当自动改写失败时提示用户手动修正的对话框。

    显示错误说明与目标文件位置，并提供：
    - 打开文件夹（便于用户手动编辑）
    - 改成成功（确认已手动修正，继续流程）
    - 取消（关闭对话框，不继续）
    """

    def __init__(self, parent=None, message: str = "自动化改写出错，请手动改写。", target_dir: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("需要手动改写")
        self.setModal(True)
        self.target_dir = target_dir

        layout = QVBoxLayout(self)

        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        if target_dir:
            path_label = QLabel(f"位置：{str(target_dir)}")
            path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(path_label)

        btns = QHBoxLayout()

        open_btn = QPushButton("📂 打开文件夹")
        confirm_btn = QPushButton("✅ 改成成功")
        cancel_btn = QPushButton("取消")

        btns.addWidget(open_btn)
        btns.addWidget(confirm_btn)
        btns.addWidget(cancel_btn)

        layout.addLayout(btns)

        open_btn.clicked.connect(self._open_folder)
        confirm_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        self.setMinimumWidth(420)

    def _open_folder(self):
        if self.target_dir and self.target_dir.exists():
            try:
                # 在Windows中打开资源管理器
                subprocess.Popen(["explorer", str(self.target_dir)])
            except Exception:
                pass