"""歌词编辑器对话框

提供手动编辑歌词、时间戳插入、播放时间调节、歌词延时调整等功能。
"""
import os
import re
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QCheckBox,
)
from PySide6.QtMultimedia import QMediaPlayer
from qfluentwidgets import (
    SimpleCardWidget, BodyLabel, StrongBodyLabel, SubtitleLabel,
    CaptionLabel, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon as FIcon, InfoBar, isDarkTheme,
)

logger = logging.getLogger(__name__)


class LyricsEditorDialog(QDialog):
    """歌词编辑器：支持手动编辑、时间戳插入、播放时间调节、歌词延时调整。
    直接继承 QDialog 避免与 qfluentwidgets Dialog 内部布局冲突导致内容空白。"""
    def __init__(self, song_name: str, existing_text: str, lrc_path: str = None,
                 source: str = None, parent=None):
        super().__init__(parent)
        self._song_name = song_name
        self._lrc_path = lrc_path
        self._save_path = lrc_path
        self._source = source
        self.setWindowTitle("歌词编辑器")
        self.setFixedSize(720, 620)
        self._build_ui(existing_text)

    def _build_ui(self, existing_text: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # 标题
        title = SubtitleLabel(f"🎵 歌词编辑 - {self._song_name}")
        layout.addWidget(title)

        # 来源（如果有）
        if self._source:
            source_hint = CaptionLabel(f"来源：{self._source}")
            color = "#9AA4B2" if isDarkTheme() else "gray"
            source_hint.setStyleSheet(f"color: {color}; padding: 0 0 2px 0;")
            layout.addWidget(source_hint)

        # 提示信息
        hint = CaptionLabel(
            "每行一句歌词，可使用 [mm:ss.xx] 格式添加时间戳。\n"
            "「插入时间戳」在光标处插入当前播放时间；「-0.3s / +0.3s」批量调整所有时间戳。"
        )
        hint_color = "#AAAAAA" if isDarkTheme() else "gray"
        hint.setStyleSheet(f"color: {hint_color}; padding: 4px 0;")
        layout.addWidget(hint)

        # ===== 播放时间控制行：显示当前时间 + 跳转/前进/后退 =====
        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        time_row.addWidget(BodyLabel("当前播放:"))

        self._time_label = StrongBodyLabel("--:--.--")
        self._time_label.setMinimumWidth(80)
        self._time_label.setStyleSheet(
            "font-family: Consolas, 'Courier New'; "
            "color: #6C5CE7;"
        )
        time_row.addWidget(self._time_label)

        # 后退 5 秒
        self._back_btn = ToolButton(FIcon.SKIP_BACK, self)
        self._back_btn.setToolTip("后退 5 秒")
        self._back_btn.clicked.connect(lambda: self._seek_relative(-5000))
        time_row.addWidget(self._back_btn)

        # 前进 5 秒
        self._fwd_btn = ToolButton(FIcon.SKIP_FORWARD, self)
        self._fwd_btn.setToolTip("前进 5 秒")
        self._fwd_btn.clicked.connect(lambda: self._seek_relative(5000))
        time_row.addWidget(self._fwd_btn)

        # 跳转到光标所在行的时间戳
        self._jump_btn = PushButton(FIcon.SEND, "跳转到此行", self)
        self._jump_btn.setToolTip("跳转到光标所在行的时间戳位置")
        self._jump_btn.clicked.connect(self._jump_to_cursor_line)
        time_row.addWidget(self._jump_btn)

        time_row.addStretch()

        # 播放/暂停切换
        self._play_toggle_btn = ToolButton(FIcon.PLAY, self)
        self._play_toggle_btn.setToolTip("播放/暂停")
        self._play_toggle_btn.clicked.connect(self._toggle_play)
        time_row.addWidget(self._play_toggle_btn)

        layout.addLayout(time_row)

        # 定时刷新当前播放时间标签
        self._time_timer = QTimer(self)
        self._time_timer.setInterval(200)
        self._time_timer.timeout.connect(self._refresh_time_label)
        self._time_timer.start()

        # ===== 工具栏：时间戳操作 =====
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.insert_ts_btn = PushButton(FIcon.CALENDAR, "插入时间戳", self)
        self.insert_ts_btn.setToolTip("在光标处插入当前播放时间 [mm:ss.xx]")
        self.insert_ts_btn.clicked.connect(self._insert_timestamp)
        toolbar.addWidget(self.insert_ts_btn)

        # 歌词延时调节：-0.3s / +0.3s
        self.delay_minus_btn = PushButton("-0.3s", self)
        self.delay_minus_btn.setToolTip("所有时间戳整体减 0.3 秒（歌词提前）")
        self.delay_minus_btn.clicked.connect(lambda: self._shift_all_timestamps(-300))
        toolbar.addWidget(self.delay_minus_btn)

        self.delay_plus_btn = PushButton("+0.3s", self)
        self.delay_plus_btn.setToolTip("所有时间戳整体加 0.3 秒（歌词延后）")
        self.delay_plus_btn.clicked.connect(lambda: self._shift_all_timestamps(300))
        toolbar.addWidget(self.delay_plus_btn)

        self.format_btn = PushButton(FIcon.FONT, "格式化", self)
        self.format_btn.setToolTip("为每行添加递增时间戳（每 5 秒一行）")
        self.format_btn.clicked.connect(self._format_lyrics)
        toolbar.addWidget(self.format_btn)

        self.clear_ts_btn = PushButton(FIcon.DELETE, "清除时间戳", self)
        self.clear_ts_btn.setToolTip("移除所有时间戳标记")
        self.clear_ts_btn.clicked.connect(self._clear_timestamps)
        toolbar.addWidget(self.clear_ts_btn)

        toolbar.addStretch()

        self.save_as_btn = PushButton(FIcon.SAVE_AS, "另存为", self)
        self.save_as_btn.clicked.connect(self._save_as)
        toolbar.addWidget(self.save_as_btn)

        layout.addLayout(toolbar)

        # ===== 歌词编辑区 =====
        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(existing_text)
        # 根据主题设置编辑区背景，确保深/浅色都可读
        if isDarkTheme():
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background: #2B2D30;
                    color: #D8D8D8;
                    border: 1px solid #3C3F44;
                    border-radius: 8px;
                    font-family: 'Microsoft YaHei UI', 'Consolas';
                    font-size: 14px;
                    padding: 8px;
                }
            """)
        else:
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background: #FFFFFF;
                    color: #1F1F1F;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                    font-family: 'Microsoft YaHei UI', 'Consolas';
                    font-size: 14px;
                    padding: 8px;
                }
            """)
        layout.addWidget(self.text_edit, 1)

        # ===== 底部按钮 =====
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = PushButton("取消", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = PrimaryPushButton(FIcon.SAVE, "保存", self)
        self.save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 播放时间控制
    # ------------------------------------------------------------------
    def _get_player(self):
        """获取外层播放器（安全访问）"""
        outer = self.parent()
        if outer and hasattr(outer, '_player'):
            return outer._player
        return None

    def _refresh_time_label(self):
        """定时刷新当前播放时间显示"""
        player = self._get_player()
        if not player:
            return
        try:
            pos_ms = player.position()
            m = pos_ms // 60000
            s = (pos_ms % 60000) // 1000
            cs = (pos_ms % 1000) // 10
            self._time_label.setText(f"{m:02d}:{s:02d}.{cs:02d}")
            # 同步更新播放/暂停按钮图标
            state = player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._play_toggle_btn.setIcon(FIcon.PAUSE)
            else:
                self._play_toggle_btn.setIcon(FIcon.PLAY)
        except Exception:
            pass

    def _seek_relative(self, delta_ms: int):
        """相对跳转：前进/后退 delta_ms 毫秒"""
        player = self._get_player()
        if not player:
            return
        try:
            new_pos = max(0, player.position() + delta_ms)
            duration = player.duration()
            if duration > 0:
                new_pos = min(new_pos, duration)
            player.setPosition(new_pos)
        except Exception:
            pass

    def _toggle_play(self):
        """切换播放/暂停"""
        player = self._get_player()
        if not player:
            return
        try:
            state = player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                player.pause()
            else:
                outer = self.parent()
                if outer and hasattr(outer, '_do_play'):
                    outer._do_play()
                else:
                    player.play()
        except Exception:
            pass

    def _jump_to_cursor_line(self):
        """跳转到光标所在行的时间戳对应的时间"""
        cursor = self.text_edit.textCursor()
        block = cursor.block()
        line_text = block.text()
        # 匹配行首时间戳 [mm:ss.xx] 或 [mm:ss]
        match = re.match(r'\[(\d+):(\d+)(?:\.(\d+))?\]', line_text)
        if not match:
            InfoBar.warning("无时间戳", "该行没有时间戳，无法跳转", duration=2000, parent=self)
            return
        try:
            m = int(match.group(1))
            s = int(match.group(2))
            ms_str = match.group(3) or "0"
            # 补齐到 2 位（[mm:ss.x] → ms=x*10）
            ms = int(ms_str.ljust(2, '0')[:2])
            pos_ms = m * 60000 + s * 1000 + ms * 10
            player = self._get_player()
            if player:
                player.setPosition(pos_ms)
                InfoBar.success("已跳转", f"到 {m:02d}:{s:02d}.{ms:02d}",
                                duration=1500, parent=self)
        except Exception as e:
            logger.debug(f"跳转失败: {e}")

    # ------------------------------------------------------------------
    # 时间戳操作
    # ------------------------------------------------------------------
    def _insert_timestamp(self):
        """在光标位置插入当前播放时间"""
        player = self._get_player()
        if not player:
            InfoBar.warning("无法插入", "播放器未激活", duration=2000, parent=self)
            return
        try:
            pos_ms = player.position()
            total_s = pos_ms // 1000
            ms = (pos_ms % 1000) // 10
            m = total_s // 60
            s = total_s % 60
            ts = f"[{m:02d}:{s:02d}.{ms:02d}]"
            cursor = self.text_edit.textCursor()
            cursor.insertText(ts)
            self.text_edit.setTextCursor(cursor)
        except Exception as e:
            logger.debug(f"插入时间戳失败: {e}")

    def _shift_all_timestamps(self, delta_ms: int):
        """批量调整所有时间戳：delta_ms > 0 延后，< 0 提前。
        支持格式：[mm:ss.xx]（百分秒）、[mm:ss.xxx]（毫秒）、[mm:ss]"""
        text = self.text_edit.toPlainText()

        def shift_match(match):
            try:
                m = int(match.group(1))
                s = int(match.group(2))
                ms_str = match.group(3)
                if ms_str:
                    # 根据小数位数换算成毫秒：.5=500ms, .50=500ms, .500=500ms
                    ms = int(int(ms_str) / (10 ** len(ms_str)) * 1000)
                else:
                    ms = 0
                # 计算原始时间（毫秒）+ 偏移
                total_ms = m * 60000 + s * 1000 + ms + delta_ms
                if total_ms < 0:
                    total_ms = 0
                new_m = total_ms // 60000
                new_s = (total_ms % 60000) // 1000
                new_ms = (total_ms % 1000) // 10  # 输出用百分秒（2位）
                return f"[{new_m:02d}:{new_s:02d}.{new_ms:02d}]"
            except Exception:
                return match.group(0)

        # 匹配 [mm:ss.xx]、[mm:ss.xxx] 或 [mm:ss]，支持 1~3 位小数
        new_text = re.sub(r'\[(\d+):(\d+)(?:\.(\d{1,3}))?\]', shift_match, text)
        self.text_edit.setPlainText(new_text)
        direction = "延后" if delta_ms > 0 else "提前"
        amount = abs(delta_ms) / 1000.0
        try:
            InfoBar.success("延时调整", f"所有时间戳{direction} {amount:.1f} 秒",
                            duration=2000, parent=self)
        except Exception:
            # InfoBar 在 QDialog 中可能异常，回退到窗口标题提示
            self.setWindowTitle(f"歌词编辑器 - 已{direction} {amount:.1f} 秒")

    def _format_lyrics(self):
        """为无时间戳的行自动添加递增时间戳"""
        text = self.text_edit.toPlainText()
        lines = text.split('\n')
        formatted = []
        current_time = 0.0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 移除已有时间戳
            clean = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', line).strip()
            if clean:
                m = int(current_time // 60)
                s = int(current_time % 60)
                ms = int((current_time % 1) * 100)
                formatted.append(f"[{m:02d}:{s:02d}.{ms:02d}]{clean}")
                current_time += 5.0  # 每行默认间隔 5 秒
        self.text_edit.setPlainText('\n'.join(formatted))
        InfoBar.success("格式化完成", f"共 {len(formatted)} 行", duration=2000, parent=self)

    def _clear_timestamps(self):
        """清除所有时间戳标记"""
        text = self.text_edit.toPlainText()
        cleaned = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', text)
        # 清理多余空格
        lines = [line.strip() for line in cleaned.split('\n')]
        self.text_edit.setPlainText('\n'.join(lines))

    def _save_as(self):
        """选择另存为路径"""
        default_name = f"{self._song_name}.lrc"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存歌词文件", default_name, "LRC 歌词 (*.lrc);;文本文件 (*.txt)"
        )
        if path:
            self._save_path = path

    def get_lyrics_text(self) -> str:
        return self.text_edit.toPlainText()

    def get_save_path(self) -> str:
        return self._save_path or ""

    def get_text(self) -> str:
        """获取编辑后的歌词文本"""
        return self.text_edit.toPlainText()

    def closeEvent(self, event):
        """关闭时停止时间刷新定时器"""
        try:
            if hasattr(self, '_time_timer') and self._time_timer:
                self._time_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)