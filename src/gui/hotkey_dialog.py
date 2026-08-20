"""快捷键编辑对话框"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QWidget, QKeyEvent
)
from qfluentwidgets import (
    SimpleCardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton
)
from ..config import cfg


class KeyCaptureEdit(QLineEdit):
    """按键捕获输入框：点击后按下的组合键会被记录"""

    keyCaptured = Qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击此处并按快捷键...")
        self.setFocusPolicy(Qt.StrongFocus)
        self._capturing = False
        self._mods = set()
        self._key = None

    def focusInEvent(self, event):
        self._capturing = True
        self.setPlaceholderText("请按下快捷键组合...")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._capturing = False
        self.setPlaceholderText("点击此处并按快捷键...")
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = event.key()
        mods = event.modifiers()

        # 忽略纯修饰键按下
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            return

        parts = []
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.ShiftModifier:
            parts.append("shift")
        if mods & Qt.MetaModifier:
            parts.append("cmd")

        # 映射主键
        key_map = {
            Qt.Key_Space: "space",
            Qt.Key_Left: "left",
            Qt.Key_Right: "right",
            Qt.Key_Up: "up",
            Qt.Key_Down: "down",
            Qt.Key_Return: "return",
            Qt.Key_Enter: "return",
            Qt.Key_Escape: "esc",
            Qt.Key_Tab: "tab",
            Qt.Key_Backspace: "backspace",
            Qt.Key_Delete: "delete",
            Qt.Key_Home: "home",
            Qt.Key_End: "end",
            Qt.Key_PageUp: "pageup",
            Qt.Key_PageDown: "pagedown",
            Qt.Key_Insert: "insert",
            Qt.Key_F1: "f1", Qt.Key_F2: "f2", Qt.Key_F3: "f3",
            Qt.Key_F4: "f4", Qt.Key_F5: "f5", Qt.Key_F6: "f6",
            Qt.Key_F7: "f7", Qt.Key_F8: "f8", Qt.Key_F9: "f9",
            Qt.Key_F10: "f10", Qt.Key_F11: "f11", Qt.Key_F12: "f12",
        }
        if key in key_map:
            parts.append(key_map[key])
        elif Qt.Key_0 <= key <= Qt.Key_9:
            parts.append(chr(key).lower())
        elif Qt.Key_A <= key <= Qt.Key_Z:
            parts.append(chr(key).lower())
        else:
            # 不支持的键
            return

        combo = "+".join(parts)
        self.setText(combo)
        self.keyCaptured.emit(combo)
        self.clearFocus()


class HotkeyDialog(QDialog):
    """快捷键编辑对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑全局快捷键")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        import json as _json
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = SubtitleLabel("⌨️ 全局快捷键设置")
        layout.addWidget(title)

        desc = CaptionLabel("点击下方输入框后按下目标组合键即可设置，支持 Ctrl/Alt/Shift + 字母/数字/方向键/F1~F12/空格/回车等")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        try:
            self._hk = _json.loads(cfg().get(cfg().global_hotkeys))
        except Exception:
            self._hk = {
                "play_pause": "ctrl+alt+space",
                "prev": "ctrl+alt+left",
                "next": "ctrl+alt+right",
                "vol_up": "ctrl+alt+up",
                "vol_down": "ctrl+alt+down",
            }

        self._edits = {}
        names = {
            'play_pause': '播放 / 暂停',
            'prev': '上一首',
            'next': '下一首',
            'vol_up': '音量加',
            'vol_down': '音量减',
        }

        card = SimpleCardWidget(self)
        card_layout = QVBoxLayout(card)
        for key, label in names.items():
            row = QHBoxLayout()
            row.addWidget(BodyLabel(label))
            row.addStretch()
            edit = KeyCaptureEdit(self)
            edit.setText(self._hk.get(key, ""))
            edit.setMinimumWidth(180)
            self._edits[key] = edit
            row.addWidget(edit)
            card_layout.addLayout(row)

        layout.addWidget(card)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reset_btn = PushButton("恢复默认", self)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)

        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = PrimaryPushButton("保存", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _reset_defaults(self):
        defaults = {
            "play_pause": "ctrl+alt+space",
            "prev": "ctrl+alt+left",
            "next": "ctrl+alt+right",
            "vol_up": "ctrl+alt+up",
            "vol_down": "ctrl+alt+down",
        }
        for key, val in defaults.items():
            if key in self._edits:
                self._edits[key].setText(val)

    def _save(self):
        import json as _json
        new_hk = {}
        for key, edit in self._edits.items():
            val = edit.text().strip()
            if val:
                new_hk[key] = val
        cfg().set(cfg().global_hotkeys, _json.dumps(new_hk))
        self.accept()
