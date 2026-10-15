"""均衡器对话框模块

提供 EqualizerDialog 类：10 频段增益调节 + 预设管理的均衡器 UI 对话框。
增益值通过 gain_changed 信号传递给外层，外层可据此做整体音量补偿
并持久化用户的 EQ 偏好。
"""
import logging
from typing import List, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel,
    Slider, PushButton, ComboBox, isDarkTheme,
)

logger = logging.getLogger(__name__)

# ---------- EQ 预设 ----------
EQ_PRESETS: Dict[str, List[int]] = {
    "平直":   [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "流行":   [+3, +1, +0, +2, +3, +3, +2, +1, +0, +1],
    "摇滚":   [+4, +3, +2, -1, -2, +1, +3, +4, +4, +4],
    "古典":   [+4, +3, +2, +0, -1, -1, +0, +2, +3, +4],
    "爵士":   [+3, +2, +1, +2, -1, -1, +0, +1, +2, +3],
    "电子":   [+4, +3, +0, +0, -2, +2, +4, +4, +4, +4],
    "人声":   [-2, -1, +0, +2, +4, +4, +3, +1, +0, -1],
}
EQ_BANDS = ["31Hz", "62Hz", "125Hz", "250Hz", "500Hz",
            "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]


class EqualizerDialog(QDialog):
    """均衡器对话框：10 频段增益调节 + 预设管理。
    由于 QMediaPlayer/QAudioOutput 不支持原生 EQ 滤波，
    本对话框作为 UI 控制面板：增益值会通过 gain_changed 信号
    传递给外层，外层可据此做整体音量补偿（按最大增益提升音量）
    并持久化用户的 EQ 偏好。"""
    gain_changed = Signal(list)

    def __init__(self, parent=None, initial_gains: List[int] = None):
        super().__init__(parent)
        self.setWindowTitle("均衡器 EQ")
        self.setFixedSize(560, 360)
        self._sliders: List[Slider] = []
        self._build_ui(initial_gains or [0] * 10)

    def _build_ui(self, initial_gains: List[int]):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = SubtitleLabel("🎛️ 均衡器 EQ")
        layout.addWidget(title)

        hint = CaptionLabel(
            "拖动滑块调节各频段增益（-12 ~ +12 dB）。\n"
            "由于 Qt 多媒体后端限制，EQ 主要作为偏好预设保存；"
            "整体音量会按最大增益做补偿。"
        )
        hint_color = "#AAAAAA" if isDarkTheme() else "gray"
        hint.setStyleSheet(f"color: {hint_color}; padding: 2px 0;")
        layout.addWidget(hint)

        # 预设栏
        preset_row = QHBoxLayout()
        preset_row.addWidget(BodyLabel("预设:"))
        self._preset_combo = ComboBox(self)
        self._preset_combo.addItems(list(EQ_PRESETS.keys()))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self._preset_combo)
        preset_row.addStretch()

        # 重置按钮
        reset_btn = PushButton("重置", self)
        reset_btn.setToolTip("所有频段归零")
        reset_btn.clicked.connect(self._reset_gains)
        preset_row.addWidget(reset_btn)
        layout.addLayout(preset_row)

        # 频段滑块网格
        bands_widget = QWidget(self)
        bands_layout = QGridLayout(bands_widget)
        bands_layout.setSpacing(6)
        for i, band_name in enumerate(EQ_BANDS):
            label = CaptionLabel(band_name)
            label.setAlignment(Qt.AlignCenter)
            bands_layout.addWidget(label, 0, i)

            slider = Slider(Qt.Vertical, self)
            slider.setRange(-12, 12)
            # 应用初始增益
            try:
                init_val = initial_gains[i] if i < len(initial_gains) else 0
            except Exception:
                init_val = 0
            slider.setValue(init_val)
            slider.setFixedHeight(100)
            slider.valueChanged.connect(lambda v, idx=i: self._on_slider_changed(idx, v))
            bands_layout.addWidget(slider, 1, i)
            self._sliders.append(slider)

            val_label = StrongBodyLabel(f"{init_val:+d}")
            val_label.setAlignment(Qt.AlignCenter)
            val_label.setFixedWidth(44)
            slider._val_label = val_label
            bands_layout.addWidget(val_label, 2, i)

        layout.addWidget(bands_widget, 1)

        # 底部说明
        info = CaptionLabel(
            "提示：选择预设可快速套用经典曲线；"
            "调节后会自动通过信号通知外层应用。"
        )
        info.setStyleSheet(f"color: {hint_color}; padding: 4px 0;")
        layout.addWidget(info)

    def _on_preset_changed(self, index: int):
        preset_name = self._preset_combo.currentText()
        gains = EQ_PRESETS.get(preset_name, [0] * 10)
        for i, gain in enumerate(gains):
            if i < len(self._sliders):
                self._sliders[i].setValue(gain)
        # emit 一次最终的增益列表
        self.gain_changed.emit(self.get_gains())

    def _on_slider_changed(self, idx: int, value: int):
        if 0 <= idx < len(self._sliders):
            lbl = getattr(self._sliders[idx], '_val_label', None)
            if lbl:
                lbl.setText(f"{value:+d}")
        self.gain_changed.emit(self.get_gains())

    def _reset_gains(self):
        for s in self._sliders:
            s.setValue(0)
        self.gain_changed.emit(self.get_gains())

    def get_gains(self) -> List[int]:
        return [s.value() for s in self._sliders]