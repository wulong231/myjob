"""桌面悬浮歌词窗口"""
import math
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, QRect, QPoint, QSize
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QLinearGradient, QBrush, QFontMetrics, QPixmap, QImage
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QMenu
from PySide6.QtMultimedia import QMediaPlayer
from qfluentwidgets import SimpleCardWidget, isDarkTheme

logger = logging.getLogger(__name__)


class DesktopLyrics(QWidget):
    """桌面悬浮歌词窗口（声浪动效 + 卡拉OK渐变填充 + 玻璃质感 + 双语歌词）"""
    close_requested = Signal()

    def __init__(self, outer_instance):
        super().__init__(None)
        self._outer = outer_instance
        self._drag_pos: Optional[QPoint] = None
        self._current_text: str = ""
        self._current_translated_text: str = ""  # 翻译后的歌词文本
        self._current_progress: float = 0.0    # 当前行演唱进度 0~1
        self._font_size: int = 22
        self._opacity: int = 85
        self._anim_offset: float = 0.0        # 渐变流动偏移
        self._fade_alpha: float = 1.0          # 歌词切换淡入透明度
        self._show_black_bg: bool = False       # 是否保留黑底
        self._wave_phase: float = 0.0          # 声浪动画相位
        self._current_level: float = -1.0      # 当前音频 RMS（-1 表示无数据）
        self._is_playing: bool = False         # 当前是否在播放
        self._show_bilingual: bool = True      # 是否显示双语歌词
        self._setup_ui()
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(50)     # 20fps，驱动动画
        self._update_timer.timeout.connect(self._on_tick)
        self._update_timer.start()

    def _setup_ui(self):
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(760, 110)  # 增高以容纳双语歌词
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _on_tick(self):
        """每帧更新：声浪 + 流动渐变 + 淡入 + 卡拉OK进度。
        外层 AudioPlayerPage 已销毁或属性缺失时，安全回退到静止状态，避免闪退。"""
        # 渐变颜色流动
        self._anim_offset = (self._anim_offset + 0.008) % 1.0
        # 声浪相位推进（用于无音频数据时的回退波动 & 颜色变化）
        self._wave_phase = (self._wave_phase + 0.12) % (2 * math.pi)
        # 淡入效果
        if self._fade_alpha < 1.0:
            self._fade_alpha = min(1.0, self._fade_alpha + 0.06)

        # 外层引用与关键属性检查（最外层防崩：任何环节失败都安全回退）
        outer_ok = (
            self._outer is not None
            and hasattr(self._outer, "_player")
            and hasattr(self._outer, "_get_current_audio_level")
            and hasattr(self._outer, "lyrics_widget")
        )

        if outer_ok:
            # 获取当前播放状态与音频电平
            try:
                state = self._outer._player.playbackState()
                self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
                # 从外层获取当前时刻的 RMS 音量（0~1，-1 表示无数据）
                self._current_level = self._outer._get_current_audio_level()
            except Exception:
                self._is_playing = False
                self._current_level = -1.0

            # 刷新歌词文本和演唱进度
            try:
                if hasattr(self._outer._player, "position"):
                    pos_ms = self._outer._player.position()
                else:
                    pos_ms = 0
                # 应用歌词偏移（正值延后，负值提前）
                offset = getattr(self._outer, '_lyrics_offset_ms', 0)
                position_sec = (pos_ms + offset) / 1000.0
                lw = self._outer.lyrics_widget
                text, progress = "", 0.0
                line_idx = -1
                if hasattr(lw, "get_current_line_index"):
                    line_idx = lw.get_current_line_index(position_sec)
                if hasattr(lw, "get_current_line_progress"):
                    text, progress = lw.get_current_line_progress(position_sec)

                if self._current_text != text:
                    self._current_text = text
                    self._fade_alpha = 0.0  # 新歌词触发淡入
                    self._current_translated_text = ""  # 清除旧翻译
                self._current_progress = progress

                # 每帧都获取翻译文本（确保翻译到达后立即显示）
                if self._show_bilingual and line_idx >= 0 and hasattr(lw, '_translated_lyrics') and line_idx < len(lw._translated_lyrics):
                    trans = lw._translated_lyrics[line_idx]
                    if trans and trans.strip():
                        self._current_translated_text = trans
            except Exception:
                pass
        else:
            # 外层不可达：静止显示当前歌词，不再更新任何动态数据
            self._is_playing = False
            self._current_level = -1.0

        # 绘制刷新（即使外层挂了也允许绘制最后状态，避免白屏）
        try:
            self.update()
        except Exception:
            pass

    def closeEvent(self, event):
        """关闭时停止定时器，避免关闭后仍有定时器回调访问已销毁对象。"""
        try:
            if hasattr(self, "_update_timer") and self._update_timer:
                try:
                    self._update_timer.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.close_requested.emit()
        except Exception:
            pass
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()

    def set_font_size(self, size: int):
        self._font_size = max(12, min(48, size))
        self.update()

    def set_opacity(self, opacity: int):
        self._opacity = max(30, min(100, opacity))
        self.update()

    def set_black_bg(self, show: bool):
        self._show_black_bg = show
        self.update()

    def _show_context_menu(self, point: QPoint):
        menu = QMenu(self)
        action_close = menu.addAction("关闭桌面歌词")
        action_close.triggered.connect(self.close_requested.emit)

        menu.addSeparator()

        # 双语歌词开关
        action_bilingual = menu.addAction("显示双语歌词")
        action_bilingual.setCheckable(True)
        action_bilingual.setChecked(self._show_bilingual)
        action_bilingual.triggered.connect(lambda: self.set_bilingual(not self._show_bilingual))

        # 黑底开关
        action_bg = menu.addAction("保留黑底")
        action_bg.setCheckable(True)
        action_bg.setChecked(self._show_black_bg)
        action_bg.triggered.connect(lambda: self.set_black_bg(not self._show_black_bg))

        font_menu = menu.addMenu("字体大小")
        for size in [14, 16, 18, 20, 22, 24, 28, 32, 36]:
            a = font_menu.addAction(f"{size}px")
            a.setCheckable(True)
            a.setChecked(size == self._font_size)
            a.triggered.connect(lambda _=False, s=size: self.set_font_size(s))

        opacity_menu = menu.addMenu("透明度")
        for op in [40, 55, 70, 85, 100]:
            a = opacity_menu.addAction(f"{op}%")
            a.setCheckable(True)
            a.setChecked(op == self._opacity)
            a.triggered.connect(lambda _=False, o=op: self.set_opacity(o))

        menu.exec(self.mapToGlobal(point))

    def set_bilingual(self, show: bool):
        self._show_bilingual = show
        if not show:
            self._current_translated_text = ""
        self.update()

    def _draw_glass_bg(self, painter, base_alpha):
        """绘制玻璃质感背景"""
        bg_rect = self.rect().adjusted(2, 2, -2, -2)

        if self._show_black_bg:
            # 黑底：半透明深色 + 微妙渐变
            bg_grad = QLinearGradient(0, 0, 0, self.height())
            bg_grad.setColorAt(0.0, QColor(20, 20, 30, int(base_alpha * 0.75)))
            bg_grad.setColorAt(0.5, QColor(10, 10, 18, int(base_alpha * 0.65)))
            bg_grad.setColorAt(1.0, QColor(8, 8, 14, int(base_alpha * 0.72)))
        else:
            # 无黑底：浅色玻璃质感
            bg_grad = QLinearGradient(0, 0, 0, self.height())
            bg_grad.setColorAt(0.0, QColor(255, 255, 255, int(base_alpha * 0.18)))
            bg_grad.setColorAt(0.5, QColor(200, 210, 230, int(base_alpha * 0.10)))
            bg_grad.setColorAt(1.0, QColor(180, 190, 210, int(base_alpha * 0.14)))

        painter.setBrush(QBrush(bg_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, 16, 16)

        # 玻璃顶部高光带（模拟光线折射）
        highlight_grad = QLinearGradient(0, 2, 0, self.height() // 2)
        highlight_grad.setColorAt(0.0, QColor(255, 255, 255, int(base_alpha * 0.22)))
        highlight_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect.adjusted(1, 1, -1, -bg_rect.height() // 2 + 2), 15, 15)

        # 玻璃边框
        border_alpha = int(base_alpha * 0.10)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), 1))
        painter.drawRoundedRect(bg_rect, 16, 16)

    def _draw_waveform(self, painter, base_alpha):
        """绘制两侧声波动效。
        优先使用真实音频 RMS 电平驱动幅度，无数据时回退到伪随机波动。
        暂停时声浪归零，呈现静止状态。"""
        bar_count = 12
        bar_width = 3
        bar_gap = 4
        bar_area_width = bar_count * (bar_width + bar_gap)
        center_y = self.height() // 2
        max_bar_height = self.height() - 20

        # 当前真实音频电平（0~1），-1 表示无数据
        real_level = self._current_level if self._is_playing else -1.0
        # 无音频数据时的回退幅度：仅当播放中才动起来
        has_real_data = real_level >= 0.0

        for side in ('left', 'right'):
            if side == 'left':
                start_x = 16
            else:
                start_x = self.width() - 16 - bar_area_width

            for i in range(bar_count):
                if not self._is_playing:
                    # 暂停/停止：声浪几乎归零，仅保留极小幅度
                    amplitude = 0.05
                elif has_real_data:
                    # 真实音频驱动：以 RMS 为基础，叠加频谱样式的小波动
                    # 越靠中间的 bar 幅度越大，模拟频谱低频在中间的形态
                    # i 范围 0..11，中心位置约 5.5
                    center_dist = abs(i - (bar_count - 1) / 2) / ((bar_count - 1) / 2)
                    # 中心权重：中心 1.0，两端 0.55
                    center_weight = 1.0 - center_dist * 0.45
                    # 叠加细节波动（基于相位的正弦，幅度小）
                    phase = self._wave_phase + i * 0.4 + (0 if side == 'left' else math.pi / 3)
                    detail = (math.sin(phase) * 0.5 + 0.5) * 0.35 + 0.65
                    amplitude = min(1.0, real_level * center_weight * detail + 0.05)
                else:
                    # 回退：无音频数据时使用多正弦波叠加伪随机波动
                    phase = self._wave_phase + i * 0.4 + (0 if side == 'left' else math.pi / 3)
                    wave1 = math.sin(phase) * 0.5 + 0.5
                    wave2 = math.sin(phase * 2.3) * 0.3 + 0.3
                    wave3 = math.sin(phase * 0.7 + 1.0) * 0.2 + 0.2
                    amplitude = min(1.0, wave1 * 0.5 + wave2 * 0.3 + wave3 * 0.2)

                bar_height = int(max_bar_height * amplitude)
                if bar_height < 3:
                    bar_height = 3

                x = start_x + i * (bar_width + bar_gap)
                y = center_y - bar_height // 2

                # 渐变色：颜色随相位变化
                hue_t = self._wave_phase + i * 0.2
                r = int(255 * (0.5 + 0.5 * math.sin(hue_t)))
                g = int(180 * (0.5 + 0.5 * math.sin(hue_t + 2.0)))
                b = int(255 * (0.5 + 0.5 * math.sin(hue_t + 4.0)))
                grad = QLinearGradient(0, y, 0, y + bar_height)
                grad.setColorAt(0.0, QColor(r, g, b, int(base_alpha * 0.9)))
                grad.setColorAt(1.0, QColor(r, g, b, int(base_alpha * 0.3)))

                painter.setBrush(QBrush(grad))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRect(x, y, bar_width, bar_height), 2, 2)


    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        base_alpha = int(255 * self._opacity / 100)
        alpha = int(base_alpha * self._fade_alpha)

        # === 玻璃质感背景 ===
        self._draw_glass_bg(painter, base_alpha)

        # === 声浪动效 ===
        self._draw_waveform(painter, base_alpha)

        # === 歌词文本（卡拉OK渐变填充，支持双语） ===
        has_translation = bool(self._current_translated_text and self._current_translated_text.strip())
        display_text = self._current_text if self._current_text else "♪ 暂无歌词 ♪"

        if display_text == "♪ 暂无歌词 ♪":
            font = QFont("Microsoft YaHei UI", self._font_size, QFont.Bold)
            painter.setFont(font)
            text_rect = QRect(90, 0, self.width() - 180, self.height())
            painter.setPen(QPen(QColor(180, 180, 180, base_alpha)))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignHCenter, display_text)
        else:
            # 有翻译时：原文在上半部，翻译在下半部（小字号）
            if has_translation:
                orig_font = QFont("Microsoft YaHei UI", self._font_size, QFont.Bold)
                trans_font = QFont("Microsoft YaHei UI", max(12, self._font_size - 4), QFont.Normal)
                orig_rect = QRect(90, 4, self.width() - 180, self.height() // 2 + 4)
                trans_rect = QRect(90, self.height() // 2 - 4, self.width() - 180, self.height() // 2)

                # 绘制原文（带卡拉OK填充）
                self._draw_lyrics_line(painter, display_text, orig_font, orig_rect,
                                       alpha, base_alpha)
                # 绘制翻译（纯色，无卡拉OK填充，带淡入动画）
                painter.setFont(trans_font)
                trans_alpha = int(alpha * 0.75)
                trans_shadow = QColor(255, 255, 255, int(trans_alpha * 0.4))
                painter.setPen(QPen(trans_shadow))
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    painter.drawText(trans_rect.adjusted(dx, dy, dx, dy),
                                     Qt.AlignVCenter | Qt.AlignHCenter, self._current_translated_text)
                dim_color = QColor(200, 220, 255, trans_alpha)
                painter.setPen(QPen(dim_color))
                painter.drawText(trans_rect, Qt.AlignVCenter | Qt.AlignHCenter, self._current_translated_text)
            else:
                # 无翻译：整行居中显示
                font = QFont("Microsoft YaHei UI", self._font_size, QFont.Bold)
                text_rect = QRect(90, 0, self.width() - 180, self.height())
                self._draw_lyrics_line(painter, display_text, font, text_rect,
                                       alpha, base_alpha)

    def _draw_lyrics_line(self, painter, text, font, text_rect, alpha, base_alpha):
        """绘制单行歌词（带描边阴影 + 卡拉OK渐变填充）"""
        painter.setFont(font)
        # 1. 描边阴影增强可读性
        shadow_color = QColor(255, 255, 255, int(alpha * 0.5))
        painter.setPen(QPen(shadow_color))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            painter.drawText(text_rect.adjusted(dx, dy, dx, dy),
                             Qt.AlignVCenter | Qt.AlignHCenter, text)

        # 2. 未演唱部分（暗色底文）
        dim_color = QColor(255, 255, 255, int(alpha * 0.6)) if self._show_black_bg else QColor(255, 255, 255, int(alpha))
        painter.setPen(QPen(dim_color))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignHCenter, text)

        # 3. 已演唱部分（亮色渐变，按进度裁剪）
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text)
        sung_width = int(text_width * self._current_progress)

        if sung_width > 0:
            painter.save()
            clip_x = text_rect.x() + (text_rect.width() - text_width) // 2
            clip_rect = QRect(clip_x, text_rect.y(), sung_width, text_rect.height())
            painter.setClipRect(clip_rect)

            offset = self._anim_offset
            grad = QLinearGradient(clip_x - self.width() * offset, 0,
                                   clip_x + text_width, 0)
            t = offset * 2 * math.pi

            # 流动渐变：红色系→蓝色系
            r1 = int(105 * (0.5 + 0.5 * math.sin(t)) + 150)
            g1 = int(50 * (0.5 + 0.5 * math.sin(t + 1.0)))
            b1 = 5
            r2 = 5
            g2 = int(50 * (0.5 + 0.5 * math.sin(t + 4.14)))
            b2 = int(105 * (0.5 + 0.5 * math.sin(t + 3.14)) + 150)
            grad.setColorAt(0.0, QColor(r1, g1, b1, alpha))
            grad.setColorAt(0.5, QColor(r2, g2, b2, alpha))
            grad.setColorAt(1.0, QColor(r1, g1, b1, alpha))

            painter.setPen(QPen(QBrush(grad), 1))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignHCenter, text)
            painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None