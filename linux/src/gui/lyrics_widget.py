"""歌词显示组件

包含 _LyricsItemDelegate（自定义委托）和 LyricsWidget（歌词滚动显示组件），
支持原文/双语/翻译三种显示模式，当前行带颜色渐变动画。
"""
import math
import logging
from typing import List, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QFont, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyleOptionViewItem,
)
from qfluentwidgets import CaptionLabel, isDarkTheme

logger = logging.getLogger(__name__)


class _LyricsItemDelegate(QStyledItemDelegate):
    """自定义委托：当前行用动画颜色绘制，其他行用默认色"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_row = -1
        self._anim_color = QColor("#4DB8FF")

    def set_current_row(self, row: int, color: QColor = None):
        self._current_row = row
        if color is not None:
            self._anim_color = color

    def paint(self, painter, option, index):
        if index.row() == self._current_row and self._anim_color.isValid():
            # 当前行：跳过父类绘制（避免重影），直接绘制文字
            text = index.data(Qt.DisplayRole)
            if text:
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                # 描边阴影增强可读性
                shadow_color = QColor(0, 0, 0, 60)
                painter.setPen(QPen(shadow_color))
                font = option.font
                font.setPointSize(font.pointSize() + 1)
                font.setBold(True)
                painter.setFont(font)
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    painter.drawText(option.rect.adjusted(dx, dy, dx, dy),
                                     Qt.AlignCenter, text)
                # 动画颜色文字
                painter.setPen(QPen(self._anim_color))
                painter.drawText(option.rect, Qt.AlignCenter, text)
                painter.restore()
        else:
            # 其他行：使用父类默认绘制
            super().paint(painter, option, index)


# ============================================================
# 歌词显示组件
# ============================================================
class LyricsWidget(QWidget):
    """歌词滚动显示组件，支持原文/双语/翻译三种显示模式，当前行带颜色渐变动画"""
    # 显示模式
    MODE_ORIGINAL = "original"     # 仅原文
    MODE_TRANSLATED = "translated" # 仅翻译
    MODE_BILINGUAL = "bilingual"   # 双语

    _DEFAULT_COLOR_DARK = QColor("#C0C0C0")
    _DEFAULT_COLOR_LIGHT = QColor(128, 128, 128)
    _CURRENT_COLOR_BASE = QColor("#4DB8FF")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lyrics: List[Tuple[float, str]] = []
        self._translated_lyrics: List[str] = []
        self._current_line: int = -1
        self._display_mode = self.MODE_ORIGINAL
        self._anim_offset: float = 0.0
        self._setup_ui()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(100)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self._list = QListWidget(self)
        self._apply_list_style()
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.setUniformItemSizes(False)

        # 设置自定义委托（颜色动画）
        self._delegate = _LyricsItemDelegate(self._list)
        self._list.setItemDelegate(self._delegate)

        layout.addWidget(self._list)

        self._hint = CaptionLabel("暂无歌词")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setStyleSheet("padding: 20px;")
        layout.addWidget(self._hint)

    def _get_default_color(self) -> QColor:
        return self._DEFAULT_COLOR_DARK if isDarkTheme() else self._DEFAULT_COLOR_LIGHT

    def _on_anim_tick(self):
        """颜色动画定时器：更新当前行文字颜色"""
        self._anim_offset = (self._anim_offset + 0.05) % 1.0
        if self._current_line >= 0:
            t = self._anim_offset * 2 * math.pi
            r = int(105 * (0.5 + 0.5 * math.sin(t)) + 150)
            g = int(50 * (0.5 + 0.5 * math.sin(t + 1.0)) + 100)
            b = int(105 * (0.5 + 0.5 * math.sin(t + 2.0)) + 150)
            color = QColor(r, g, b)
            self._delegate.set_current_row(self._current_line, color)
            self._list.viewport().update(self._list.viewport().rect())

    def _apply_list_style(self):
        """根据当前主题应用歌词列表样式"""
        if isDarkTheme():
            list_ss = """
                QListWidget {
                    background: transparent;
                    border: none;
                    outline: none;
                }
                QListWidget::item {
                    padding: 8px 12px;
                    text-align: center;
                    font-size: 14px;
                }
                QListWidget::item:selected {
                    font-size: 16px;
                    font-weight: bold;
                }
            """
        else:
            list_ss = """
                QListWidget {
                    background: transparent;
                    border: none;
                    outline: none;
                }
                QListWidget::item {
                    padding: 8px 12px;
                    text-align: center;
                    font-size: 14px;
                }
                QListWidget::item:selected {
                    font-size: 16px;
                    font-weight: bold;
                }
            """
        self._list.setStyleSheet(list_ss)

    def refresh_theme(self):
        """主题切换时刷新样式"""
        self._apply_list_style()

    def set_lyrics(self, lyrics: List[Tuple[float, str]], translated: List[str] = None):
        """设置歌词数据和可选的翻译数据"""
        self._lyrics = lyrics
        self._translated_lyrics = translated or []
        self._refresh_list()

    def set_translated_lyrics(self, translated: List[str]):
        """设置翻译歌词数据并刷新显示"""
        # 确保翻译列表与歌词列表长度一致
        if len(translated) != len(self._lyrics):
            # 长度不匹配时截断或补空
            if len(translated) < len(self._lyrics):
                translated = translated + [""] * (len(self._lyrics) - len(translated))
            else:
                translated = translated[:len(self._lyrics)]
        self._translated_lyrics = translated
        self._refresh_list()

    def set_display_mode(self, mode: str):
        """切换显示模式：original/translated/bilingual"""
        self._display_mode = mode
        self._refresh_list()

    def get_display_mode(self) -> str:
        return self._display_mode

    def has_translation(self) -> bool:
        """是否有翻译数据"""
        return bool(self._translated_lyrics) and any(t.strip() for t in self._translated_lyrics)

    def _refresh_list(self):
        """根据当前模式和数据刷新列表显示"""
        self._list.clear()
        if not self._lyrics:
            self._list.setVisible(False)
            self._hint.setVisible(True)
            self._current_line = -1
            return

        self._list.setVisible(True)
        self._hint.setVisible(False)

        for i, (_, text) in enumerate(self._lyrics):
            display_text = self._build_line_text(i, text)
            item = QListWidgetItem(display_text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(self._get_default_color())
            self._list.addItem(item)
        self._current_line = -1

    def _build_line_text(self, index: int, original: str) -> str:
        """根据显示模式构建单行歌词文本"""
        if self._display_mode == self.MODE_TRANSLATED and self.has_translation():
            return self._translated_lyrics[index] if index < len(self._translated_lyrics) else original
        elif self._display_mode == self.MODE_BILINGUAL and self.has_translation():
            trans = self._translated_lyrics[index] if index < len(self._translated_lyrics) else ""
            if trans and trans.strip():
                return f"{original}\n{trans}"
            return original
        else:
            return original

    def update_position(self, position_sec: float):
        if not self._lyrics:
            return ""
        lo, hi = 0, len(self._lyrics) - 1
        found = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._lyrics[mid][0] <= position_sec:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if found != self._current_line and found >= 0:
            # 重置旧行颜色为默认色
            if self._current_line >= 0 and self._current_line < self._list.count():
                prev_item = self._list.item(self._current_line)
                if prev_item:
                    prev_item.setForeground(self._get_default_color())
            self._current_line = found
            self._list.setCurrentRow(found)
            self._list.scrollToItem(self._list.item(found),
                                    QListWidget.PositionAtCenter)
            # 新行颜色由 _on_anim_tick 在下一帧设置
        if found >= 0:
            return self._lyrics[found][1]
        return ""

    def get_current_line_text(self, position_sec: float) -> str:
        if not self._lyrics:
            return ""
        lo, hi = 0, len(self._lyrics) - 1
        found = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._lyrics[mid][0] <= position_sec:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if found >= 0:
            return self._lyrics[found][1]
        return ""

    def get_current_line_progress(self, position_sec: float) -> tuple:
        """获取当前歌词行文本及演唱进度

        Returns:
            (text, progress): progress 范围 0.0~1.0，表示当前行已演唱比例
        """
        if not self._lyrics:
            return "", 0.0
        lo, hi = 0, len(self._lyrics) - 1
        found = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._lyrics[mid][0] <= position_sec:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if found < 0:
            return "", 0.0
        line_start = self._lyrics[found][0]
        # 下一行起始时间作为当前行结束参考
        if found + 1 < len(self._lyrics):
            line_end = self._lyrics[found + 1][0]
        else:
            line_end = line_start + 10.0  # 最后一行默认 10 秒
        duration = max(0.1, line_end - line_start)
        progress = max(0.0, min(1.0, (position_sec - line_start) / duration))
        return self._lyrics[found][1], progress

    def get_current_line_index(self, position_sec: float) -> int:
        """获取当前时间对应的歌词行索引"""
        if not self._lyrics:
            return -1
        lo, hi = 0, len(self._lyrics) - 1
        found = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._lyrics[mid][0] <= position_sec:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return found

    def clear(self):
        self._lyrics = []
        self._translated_lyrics = []
        self._list.clear()
        self._list.setVisible(False)
        self._hint.setVisible(True)
        self._current_line = -1