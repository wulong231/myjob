"""音频播放器页面（全面升级版）
================================
功能：播放/暂停、进度拖拽、音量调节、播放模式切换、记忆播放位置、
      均衡器EQ、歌词显示、定时关闭、批量管理、播放列表导入导出、
      倍速播放、全局快捷键、迷你播放模式、桌面悬浮歌词、播放历史统计。
"""
import os
import re
import ast
import logging
import random
import hashlib
from typing import List, Optional, Dict, Tuple
import os

from ..utils import scandir_recursive, retry, safe_delete, safe_rmdir

from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QPoint, QRect, QSize, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QThread
from PySide6.QtGui import QPixmap, QImage, QColor, QAction, QKeySequence, QShortcut, QPainter, QFont, QBrush, QPen, QLinearGradient, QPalette, QTransform, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QSizePolicy, QMenu, QSplitter, QMessageBox, QInputDialog,
    QCheckBox, QGridLayout, QFrame, QApplication, QDialog,
    QSlider as QSliderWidget, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QStyledItemDelegate, QStyleOptionViewItem,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from qfluentwidgets import (
    SimpleCardWidget, BodyLabel, CaptionLabel, StrongBodyLabel,
    SubtitleLabel, Slider, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon as FIcon, setTheme, isDarkTheme, ComboBox, CheckBox,
    MessageBox, SwitchButton, SegmentedWidget, SegmentedItem,
    InfoBar, InfoBarPosition, Dialog, CardWidget, LineEdit,
)

from ..config import get_config
from ..bilibili_api import BilibiliClient
from .equalizer_dialog import EqualizerDialog
from .desktop_lyrics import DesktopLyrics
from .lyrics_widget import LyricsWidget
from .widgets import _SyncToTransferWorker, RotatingCoverLabel, _AudioLevelWorker, _extract_metadata
from .translate_worker import _TranslateWorker
from .lyrics_editor_dialog import LyricsEditorDialog

logger = logging.getLogger(__name__)


AUDIO_EXTENSIONS = ('.mp3', '.m4a', '.flac', '.wav', '.aac', '.opus')

PLAYBACK_RATES = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "1.75x", "2.0x"]

# ---------- 播放模式枚举 ----------
PLAY_MODE_LIST = "list"          # 列表循环
PLAY_MODE_SINGLE = "single"      # 单曲循环
PLAY_MODE_RANDOM = "random"      # 随机播放

PLAY_MODE_ICONS = {
    PLAY_MODE_LIST: FIcon.SYNC,       # 列表循环
    PLAY_MODE_SINGLE: FIcon.PLAY,     # 单曲循环
    PLAY_MODE_RANDOM: FIcon.COPY,     # 随机播放
}
PLAY_MODE_NAMES = {
    PLAY_MODE_LIST: "列表循环",
    PLAY_MODE_SINGLE: "单曲循环",
    PLAY_MODE_RANDOM: "随机播放",
}


def _format_time(ms: int) -> str:
    if ms <= 0:
        return "00:00"
    total_seconds = int(ms) // 1000
    m, s = divmod(total_seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parse_lrc(path: str) -> List[Tuple[float, str]]:
    """解析 .lrc 歌词文件，返回 [(time_sec, text), ...]"""
    lyrics = []
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 支持 1~3 位小数（百分秒/毫秒），捕获小数部分用于精确解析
                matches = re.findall(r'\[(\d+):(\d+)(?:\.(\d+))?\]', line)
                text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', line).strip()
                if not text:
                    continue
                for m_str, s_str, ms_str in matches:
                    t = int(m_str) * 60 + int(s_str)
                    if ms_str:
                        # 根据小数位数换算成秒的小数部分
                        t += int(ms_str) / (10 ** len(ms_str))
                    lyrics.append((float(t), text))
    except Exception as e:
        logger.debug(f"解析歌词失败 {path}: {e}")
    lyrics.sort(key=lambda x: x[0])
    return lyrics


def _find_lrc_for_audio(audio_path: str) -> Optional[str]:
    """查找与音频同名的 .lrc 文件"""
    base = os.path.splitext(audio_path)[0]
    for ext in ('.lrc', '.LRC'):
        lrc_path = base + ext
        if os.path.isfile(lrc_path):
            return lrc_path
    return None


def _extract_cover_from_audio(audio_path: str) -> Optional[bytes]:
    """从音频文件提取嵌入的封面图"""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(audio_path)
        if audio is None:
            return None
        if hasattr(audio, 'tags') and audio.tags:
            for key in audio.tags:
                key_str = str(key)
                if 'APIC' in key_str:
                    return audio.tags[key].data
        if hasattr(audio, 'pictures'):
            for pic in audio.pictures:
                return pic.data
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"提取封面失败 {audio_path}: {e}")
    return None


# ============================================================
# 同步到音乐库工作线程
# ============================================================


# ============================================================
# SVG 图标生成
# ============================================================
def _make_heart_icon(filled: bool, color: str = "#FF4757") -> QIcon:
    """生成爱心图标：filled=True 红色实心，filled=False 灰色空心"""
    if filled:
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
            <path fill="{color}" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5
            2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3
            19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
        </svg>'''
    else:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
            <path fill="none" stroke="#999" stroke-width="2" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5
            2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3
            19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
        </svg>'''
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import QByteArray
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# ============================================================
# 主播放器页面
# ============================================================
class AudioPlayerPage(QWidget):
    """内置音频播放器页面（全面升级版）"""

    play_state_changed = Signal(bool)
    # 全局热键触发信号（后台线程 -> 主线程，使用 Qt 信号机制安全跨线程）
    hotkey_triggered = Signal(str)

    # ================================================================
    # 迷你播放器（嵌套类）
    # ================================================================
    class MiniPlayer(QWidget):
        """迷你悬浮播放窗口"""
        close_requested = Signal()

        def __init__(self, outer_instance):
            super().__init__(None)
            self._outer = outer_instance
            self._drag_pos: Optional[QPoint] = None
            self._setup_ui()

        def _setup_ui(self):
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
            )
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setFixedSize(380, 150)

            card = SimpleCardWidget(self)
            card.setGeometry(0, 0, 380, 150)

            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(8)

            top_row = QHBoxLayout()
            top_row.setSpacing(10)

            self.cover_label = QLabel()
            self.cover_label.setFixedSize(60, 60)
            self.cover_label.setAlignment(Qt.AlignCenter)
            # 使用透明背景，让主题自动适配，避免深色模式下浅灰背景刺眼
            self.cover_label.setStyleSheet(
                "background: transparent; border-radius: 8px; font-size: 28px;"
            )
            self.cover_label.setText("🎵")
            top_row.addWidget(self.cover_label)

            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)
            self.title_label = StrongBodyLabel("未播放")
            font = self.title_label.font()
            font.setPixelSize(14)
            self.title_label.setFont(font)
            self.title_label.setWordWrap(False)
            info_layout.addWidget(self.title_label)
            self.artist_label = CaptionLabel("")
            info_layout.addWidget(self.artist_label)
            info_layout.addStretch()
            top_row.addLayout(info_layout, 1)

            self.close_btn = ToolButton(FIcon.CLOSE, self)
            self.close_btn.setFixedSize(28, 28)
            self.close_btn.setToolTip("关闭迷你模式")
            self.close_btn.clicked.connect(self.close_requested.emit)
            top_row.addWidget(self.close_btn)

            layout.addLayout(top_row)

            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(6)
            ctrl_row.addStretch()

            self.prev_btn = ToolButton(FIcon.LEFT_ARROW, self)
            self.prev_btn.setToolTip("上一首")
            self.prev_btn.clicked.connect(lambda: self._outer._play_prev())
            ctrl_row.addWidget(self.prev_btn)

            self.play_btn = PushButton(FIcon.PLAY, "播放", self)
            self.play_btn.setFixedHeight(32)
            self.play_btn.clicked.connect(lambda: self._outer._toggle_play())
            ctrl_row.addWidget(self.play_btn)

            self.next_btn = ToolButton(FIcon.RIGHT_ARROW, self)
            self.next_btn.setToolTip("下一首")
            self.next_btn.clicked.connect(lambda: self._outer._play_next())
            ctrl_row.addWidget(self.next_btn)

            ctrl_row.addStretch()
            layout.addLayout(ctrl_row)

            self._sync_from_outer()

        def _sync_from_outer(self):
            outer = self._outer
            self.title_label.setText(outer.track_title_label.text())
            self.artist_label.setText(outer.track_artist_label.text())
            if outer.cover_label.pixmap():
                pm = outer.cover_label.pixmap().scaled(
                    60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.cover_label.setPixmap(pm)
            else:
                self.cover_label.setText("🎵")
            state = outer._player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self.play_btn.setIcon(FIcon.PAUSE)
                self.play_btn.setText("暂停")
            else:
                self.play_btn.setIcon(FIcon.PLAY)
                self.play_btn.setText("播放")

        def update_info(self, title: str, artist: str, pixmap: Optional[QPixmap]):
            self.title_label.setText(title)
            self.artist_label.setText(artist)
            if pixmap:
                pm = pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.cover_label.setPixmap(pm)
            else:
                self.cover_label.setText("🎵")

        def update_play_state(self, is_playing: bool):
            if is_playing:
                self.play_btn.setIcon(FIcon.PAUSE)
                self.play_btn.setText("暂停")
            else:
                self.play_btn.setIcon(FIcon.PLAY)
                self.play_btn.setText("播放")

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

    

    # ================================================================
    # 主构造
    # ================================================================
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AudioPlayerPage")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("QWidget#AudioPlayerPage { background: transparent; }")

        self._playlist: List[str] = []
        self._current_index: int = -1
        self._is_seeking: bool = False
        self._last_volume: int = 70
        self._play_mode: str = PLAY_MODE_LIST
        self._lyrics_data: List[Tuple[float, str]] = []
        self._playback_rate: float = 1.0

        # 子播放列表：从收藏夹/歌手/专辑分类中播放时，用子列表替代主列表的播放顺序
        # _sub_playlist 为 None 时使用主 _playlist，非 None 时使用子列表
        self._sub_playlist: Optional[List[str]] = None

        self._sleep_timer: Optional[QTimer] = None
        self._sleep_remaining: int = 0

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(self._last_volume / 100.0)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._on_progress_tick)

        # 断点续播：定期保存播放位置到数据库（5秒一次，避免频繁写库）
        self._save_position_timer = QTimer(self)
        self._save_position_timer.setInterval(5000)
        self._save_position_timer.timeout.connect(self._save_current_position)

        try:
            from ..database import get_database
            self._db = get_database()
        except Exception as e:
            logger.warning(f"数据库初始化失败: {e}")
            self._db = None

        self._mini_player: Optional[AudioPlayerPage.MiniPlayer] = None
        self._desktop_lyrics: Optional[DesktopLyrics] = None

        self._global_hotkeys = None
        self._pynput_available = False
        # Win32 全局热键线程控制
        self._hotkey_thread = None
        self._hotkey_stop_flag = None
        self._hotkey_connected = False

        # 音频电平缓存：{audio_path: [rms_levels]}，供桌面歌词声浪使用
        self._audio_level_cache: Dict[str, list] = {}
        # 元数据缓存：{audio_path: {'title':..., 'artist':..., 'album':...}}，避免重复打开文件
        self._meta_cache: Dict[str, Dict[str, str]] = {}
        self._audio_level_worker: Optional[_AudioLevelWorker] = None
        # 当前播放歌曲的 RMS 曲线（指向 cache 中的列表，切换歌曲时更新）
        self._current_audio_levels: list = []
        # 歌词显示偏移（毫秒，正值延后，负值提前），从配置读取
        try:
            self._lyrics_offset_ms = int(get_config().get(get_config().lyrics_offset_ms))
        except Exception:
            self._lyrics_offset_ms = 0

        self._setup_ui()
        self._connect_signals()
        self._setup_shortcuts()

        self._load_settings()
        self._scan_audio_files()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("音频播放器"))
        title_row.addStretch()

        self.mini_btn = ToolButton(FIcon.HOME, self)
        self.mini_btn.setToolTip("迷你模式")
        title_row.addWidget(self.mini_btn)

        self.lyrics_switch_label = CaptionLabel("桌面歌词")
        title_row.addWidget(self.lyrics_switch_label)
        self.desktop_lyrics_switch = SwitchButton(self)
        self.desktop_lyrics_switch.setToolTip("开启/关闭桌面悬浮歌词")
        title_row.addWidget(self.desktop_lyrics_switch)

        self.sleep_btn = ToolButton(FIcon.BRIGHTNESS, self)
        self.sleep_btn.setToolTip("定时关闭")
        title_row.addWidget(self.sleep_btn)

        self.eq_btn = ToolButton(FIcon.MIX_VOLUMES, self)
        self.eq_btn.setToolTip("均衡器")
        title_row.addWidget(self.eq_btn)

        self.import_btn = ToolButton(FIcon.FOLDER_ADD, self)
        self.import_btn.setToolTip("导入播放列表")
        title_row.addWidget(self.import_btn)

        self.export_btn = ToolButton(FIcon.SAVE_AS, self)
        self.export_btn.setToolTip("导出播放列表")
        title_row.addWidget(self.export_btn)

        self.sync_lib_btn = ToolButton(FIcon.SYNC, self)
        self.sync_lib_btn.setToolTip("同步到 transfer 文件夹")
        title_row.addWidget(self.sync_lib_btn)

        main_layout.addLayout(title_row)

        splitter = QSplitter(Qt.Vertical, self)
        splitter.setChildrenCollapsible(False)

        # 顶部区域：水平 QSplitter，左侧正在播放卡片 + 右侧歌词卡片（可拖动调整宽度）
        top_widget = QSplitter(Qt.Horizontal, self)
        top_widget.setChildrenCollapsible(False)
        top_widget.setHandleWidth(6)
        top_widget.setStyleSheet("QSplitter::handle { background: transparent; }")

        self.now_playing_card = SimpleCardWidget(self)
        np_layout = QVBoxLayout(self.now_playing_card)
        np_layout.setContentsMargins(20, 20, 20, 20)
        np_layout.setSpacing(10)

        info_row = QHBoxLayout()

        self.cover_label = RotatingCoverLabel(self.now_playing_card)
        info_row.addWidget(self.cover_label)

        track_info_layout = QVBoxLayout()
        track_info_layout.setSpacing(4)
        self.track_title_label = StrongBodyLabel("未播放")
        font = self.track_title_label.font()
        font.setPixelSize(16)
        self.track_title_label.setFont(font)
        track_info_layout.addWidget(self.track_title_label)
        self.track_artist_label = CaptionLabel("")
        track_info_layout.addWidget(self.track_artist_label)
        track_info_layout.addStretch()
        info_row.addLayout(track_info_layout, 1)
        np_layout.addLayout(info_row)

        self.progress_slider = QSliderWidget(Qt.Horizontal, self.now_playing_card)
        self.progress_slider.setRange(0, 0)
        self._apply_progress_slider_style()
        np_layout.addWidget(self.progress_slider)

        time_layout = QHBoxLayout()
        self.current_time_label = CaptionLabel("00:00")
        time_layout.addWidget(self.current_time_label)
        time_layout.addStretch()
        self.total_time_label = CaptionLabel("00:00")
        time_layout.addWidget(self.total_time_label)
        np_layout.addLayout(time_layout)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.addStretch()

        self.play_mode_btn = ToolButton(PLAY_MODE_ICONS[self._play_mode], self.now_playing_card)
        self.play_mode_btn.setToolTip(PLAY_MODE_NAMES[self._play_mode])
        ctrl_layout.addWidget(self.play_mode_btn)

        self.prev_btn = ToolButton(FIcon.LEFT_ARROW, self.now_playing_card)
        self.prev_btn.setToolTip("上一首")
        ctrl_layout.addWidget(self.prev_btn)

        self.play_btn = ToolButton(FIcon.PLAY, self.now_playing_card)
        self.play_btn.setToolTip("播放/暂停")
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setStyleSheet("""
            ToolButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667EEA, stop:1 #764BA2);
                color: white;
                border: none;
                border-radius: 24px;
            }
            ToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5A6FD6, stop:1 #6A3F92);
            }
            ToolButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4E60C2, stop:1 #5E3582);
            }
        """)
        ctrl_layout.addWidget(self.play_btn)

        self.next_btn = ToolButton(FIcon.RIGHT_ARROW, self.now_playing_card)
        self.next_btn.setToolTip("下一首")
        ctrl_layout.addWidget(self.next_btn)

        self.fav_btn = ToolButton(self.now_playing_card)
        self.fav_btn.setIcon(_make_heart_icon(filled=False))
        self.fav_btn.setToolTip("收藏/取消收藏")
        ctrl_layout.addWidget(self.fav_btn)

        ctrl_layout.addStretch()
        np_layout.addLayout(ctrl_layout)

        vol_layout = QHBoxLayout()
        vol_layout.setContentsMargins(0, 0, 0, 0)

        vol_layout.addWidget(CaptionLabel("倍速:"))
        self.rate_combo = ComboBox(self.now_playing_card)
        self.rate_combo.addItems(PLAYBACK_RATES)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setFixedWidth(88)
        self.rate_combo.setToolTip("播放倍速")
        vol_layout.addWidget(self.rate_combo)
        vol_layout.addSpacing(12)

        self.volume_btn = ToolButton(FIcon.VOLUME, self.now_playing_card)
        self.volume_btn.setToolTip("静音/取消静音")
        vol_layout.addWidget(self.volume_btn)

        self.volume_slider = Slider(Qt.Horizontal, self.now_playing_card)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self._last_volume)
        self.volume_slider.setFixedWidth(160)
        vol_layout.addWidget(self.volume_slider)
        vol_layout.addStretch()
        np_layout.addLayout(vol_layout)

        # 正在播放卡片最小宽度，避免拖动时被压缩到不可见
        self.now_playing_card.setMinimumWidth(280)
        top_widget.addWidget(self.now_playing_card)

        lyrics_card = SimpleCardWidget(self)
        lyrics_layout = QVBoxLayout(lyrics_card)
        lyrics_layout.setContentsMargins(10, 10, 10, 10)
        lyrics_header = QHBoxLayout()
        lyrics_header.addWidget(StrongBodyLabel("歌词"))
        lyrics_header.addStretch()

        self.edit_lrc_btn = ToolButton(FIcon.EDIT, lyrics_card)
        self.edit_lrc_btn.setToolTip("编辑歌词")
        lyrics_header.addWidget(self.edit_lrc_btn)

        self.search_lrc_btn = ToolButton(FIcon.SEARCH, lyrics_card)
        self.search_lrc_btn.setToolTip("搜索歌词")
        lyrics_header.addWidget(self.search_lrc_btn)

        self.load_lrc_btn = ToolButton(FIcon.FOLDER, lyrics_card)
        self.load_lrc_btn.setToolTip("手动加载歌词")
        lyrics_header.addWidget(self.load_lrc_btn)

        # 歌词延时调节：-0.3s / +0.3s（实时调整，不修改 LRC 文件）
        self.lyrics_offset_label = CaptionLabel("0.0s")
        self.lyrics_offset_label.setFixedWidth(42)
        self.lyrics_offset_label.setAlignment(Qt.AlignCenter)
        self.lyrics_offset_label.setToolTip("歌词显示偏移（正值延后，负值提前）")
        lyrics_header.addWidget(self.lyrics_offset_label)

        self.lyrics_delay_minus_btn = ToolButton(FIcon.REMOVE, lyrics_card)
        self.lyrics_delay_minus_btn.setToolTip("歌词提前 0.3 秒")
        lyrics_header.addWidget(self.lyrics_delay_minus_btn)

        self.lyrics_delay_plus_btn = ToolButton(FIcon.ADD, lyrics_card)
        self.lyrics_delay_plus_btn.setToolTip("歌词延后 0.3 秒")
        lyrics_header.addWidget(self.lyrics_delay_plus_btn)

        # 歌词翻译按钮
        self.translate_lrc_btn = ToolButton(FIcon.LANGUAGE, lyrics_card)
        self.translate_lrc_btn.setToolTip("翻译歌词（联网）")
        lyrics_header.addWidget(self.translate_lrc_btn)

        # 人工纠正翻译按钮
        self.correct_lrc_btn = ToolButton(FIcon.EDIT, lyrics_card)
        self.correct_lrc_btn.setToolTip("人工纠正翻译结果")
        self.correct_lrc_btn.setEnabled(False)
        lyrics_header.addWidget(self.correct_lrc_btn)

        # 删除翻译按钮
        self.delete_trans_btn = ToolButton(FIcon.DELETE, lyrics_card)
        self.delete_trans_btn.setToolTip("删除中文翻译")
        self.delete_trans_btn.setEnabled(False)
        lyrics_header.addWidget(self.delete_trans_btn)

        # 字幕模式切换：原文 / 双语 / 翻译
        self.lyrics_mode_combo = ComboBox(lyrics_card)
        self.lyrics_mode_combo.addItems(["原文", "双语", "翻译"])
        self.lyrics_mode_combo.setCurrentIndex(0)
        self.lyrics_mode_combo.setFixedWidth(70)
        self.lyrics_mode_combo.setToolTip("切换歌词显示模式")
        lyrics_header.addWidget(self.lyrics_mode_combo)

        lyrics_layout.addLayout(lyrics_header)
        self.lyrics_widget = LyricsWidget(lyrics_card)
        lyrics_layout.addWidget(self.lyrics_widget)
        # 歌词卡片最小宽度，避免拖动时被压缩到不可见
        lyrics_card.setMinimumWidth(280)
        top_widget.addWidget(lyrics_card)
        # 设置水平分割比例：正在播放卡片占 2，歌词卡片占 3
        top_widget.setSizes([400, 600])

        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_widget.setStyleSheet("background: transparent;")
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # 使用 QTabWidget 组织：播放列表 / 音乐收藏夹 / 按歌手 / 按专辑
        self.bottom_tabs = QTabWidget(self)
        self.bottom_tabs.setDocumentMode(True)
        bottom_layout.addWidget(self.bottom_tabs)

        # === 标签1：播放列表（保留原有功能） ===
        playlist_tab = QWidget()
        playlist_tab.setStyleSheet("background: transparent;")
        pl_layout = QVBoxLayout(playlist_tab)
        pl_layout.setContentsMargins(0, 6, 0, 0)

        header_layout = QHBoxLayout()
        header_layout.addWidget(StrongBodyLabel("播放列表"))

        self.search_combo = ComboBox(self)
        self.search_combo.addItems(["全部", "收藏", "最近播放"])
        self.search_combo.setFixedWidth(120)
        header_layout.addWidget(self.search_combo)

        header_layout.addStretch()

        self.batch_btn = PushButton(FIcon.MENU, "批量操作", self)
        header_layout.addWidget(self.batch_btn)

        self.dup_btn = PushButton(FIcon.COPY, "重复检测", self)
        header_layout.addWidget(self.dup_btn)

        # 新增：自动整理分类按钮（手动触发也会弹出整理结果通知）
        self.categorize_btn = PushButton(FIcon.HOME, "📁 整理分类", self)
        self.categorize_btn.setToolTip("按配置的归类模式（按歌手/按专辑）整理所有音频文件到对应目录")
        header_layout.addWidget(self.categorize_btn)

        self.rescan_btn = PushButton(FIcon.SYNC, "重新扫描", self)
        self.rescan_btn.setToolTip("重新扫描下载目录")
        header_layout.addWidget(self.rescan_btn)

        self.clean_btn = PushButton(FIcon.DELETE, "🗑 清理空文件", self)
        self.clean_btn.setToolTip("删除大小为 0 的空音频文件和空目录")
        header_layout.addWidget(self.clean_btn)

        pl_layout.addLayout(header_layout)

        self.playlist_list = QListWidget(self)
        self.playlist_list.setAlternatingRowColors(True)
        self.playlist_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.playlist_list.setUniformItemSizes(True)
        self.playlist_list.setContextMenuPolicy(Qt.CustomContextMenu)
        pl_layout.addWidget(self.playlist_list)

        self.empty_hint = CaptionLabel("暂无音频文件，请先下载音频或重新扫描")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setVisible(False)
        pl_layout.addWidget(self.empty_hint)

        self.bottom_tabs.addTab(playlist_tab, "播放列表")

        # === 标签2：音乐收藏夹（从 MusicFolderPage 嵌入） ===
        self._setup_folder_tab()

        # === 标签3：按歌手分类 ===
        self._setup_artist_tab()

        # === 标签4：按专辑分类 ===
        self._setup_album_tab()

        splitter.addWidget(bottom_widget)
        splitter.setSizes([300, 250])
        main_layout.addWidget(splitter, 1)

        self.sleep_label = CaptionLabel("")
        self.sleep_label.setAlignment(Qt.AlignCenter)
        # 睡眠定时器颜色：深色模式用亮黄橙色保证可读性，浅色模式用标准橙色
        sleep_color = "#FFCC66" if isDarkTheme() else "orange"  # COLOR-11: 睡眠定时器文字颜色（深色#FFCC66 / 浅色orange）
        self.sleep_label.setStyleSheet(f"color: {sleep_color};")
        self.sleep_label.setVisible(False)
        main_layout.addWidget(self.sleep_label)

    # ------------------------------------------------------------------
    # 标签页构建：音乐收藏夹 / 按歌手 / 按专辑
    # ------------------------------------------------------------------
    def _setup_folder_tab(self):
        """构建音乐收藏夹标签页"""
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 6, 0, 0)

        # 顶部工具栏
        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("音乐收藏夹"))
        header.addStretch()

        self.folder_create_btn = PushButton(FIcon.ADD, "新建收藏夹", self)
        self.folder_create_btn.clicked.connect(self._create_folder)
        header.addWidget(self.folder_create_btn)

        self.folder_add_btn = PushButton(FIcon.FOLDER_ADD, "添加音频", self)
        self.folder_add_btn.setEnabled(False)
        self.folder_add_btn.clicked.connect(self._add_files_to_folder)
        header.addWidget(self.folder_add_btn)

        layout.addLayout(header)

        # 左右分割：左侧收藏夹列表 + 右侧歌曲列表
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 左侧：收藏夹列表
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(CaptionLabel("收藏夹列表"))
        self.folder_list = QListWidget(self)
        self.folder_list.setAlternatingRowColors(True)
        self.folder_list.setIconSize(QSize(32, 32))
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._folder_context_menu)
        self.folder_list.itemClicked.connect(self._on_folder_clicked)
        left_layout.addWidget(self.folder_list)
        splitter.addWidget(left)

        # 右侧：歌曲列表
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_title = StrongBodyLabel("请选择收藏夹")
        right_layout.addWidget(self.folder_title)
        self.folder_song_list = QListWidget(self)
        self.folder_song_list.setAlternatingRowColors(True)
        self.folder_song_list.setIconSize(QSize(40, 40))
        self.folder_song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_song_list.customContextMenuRequested.connect(self._folder_song_context_menu)
        self.folder_song_list.itemDoubleClicked.connect(self._play_folder_song)
        right_layout.addWidget(self.folder_song_list)
        splitter.addWidget(right)

        splitter.setSizes([220, 380])
        layout.addWidget(splitter, 1)

        self._current_folder_id: int = -1
        self.bottom_tabs.addTab(tab, "音乐收藏夹")
        self._load_folders()

    def _setup_artist_tab(self):
        """构建按歌手分类标签页"""
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 6, 0, 0)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("按歌手分类"))
        header.addStretch()
        self.artist_rescan_btn = PushButton(FIcon.SYNC, "刷新", self)
        self.artist_rescan_btn.clicked.connect(self._load_artists)
        header.addWidget(self.artist_rescan_btn)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 左侧：歌手列表
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(CaptionLabel("歌手列表"))
        self.artist_list = QListWidget(self)
        self.artist_list.setAlternatingRowColors(True)
        self.artist_list.itemClicked.connect(self._on_artist_clicked)
        left_layout.addWidget(self.artist_list)
        splitter.addWidget(left)

        # 右侧：该歌手的歌曲
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.artist_title = StrongBodyLabel("请选择歌手")
        right_layout.addWidget(self.artist_title)
        self.artist_song_list = QListWidget(self)
        self.artist_song_list.setAlternatingRowColors(True)
        self.artist_song_list.itemDoubleClicked.connect(self._play_artist_song)
        self.artist_song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.artist_song_list.customContextMenuRequested.connect(self._on_artist_song_context_menu)
        right_layout.addWidget(self.artist_song_list)
        splitter.addWidget(right)

        splitter.setSizes([220, 380])
        layout.addWidget(splitter, 1)

        self._artist_map: Dict[str, List[str]] = {}  # {歌手名: [文件路径, ...]}
        self.bottom_tabs.addTab(tab, "按歌手")
        self._load_artists()

    def _setup_album_tab(self):
        """构建按专辑分类标签页"""
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 6, 0, 0)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("按专辑分类"))
        header.addStretch()
        self.album_rescan_btn = PushButton(FIcon.SYNC, "刷新", self)
        self.album_rescan_btn.clicked.connect(self._load_albums)
        header.addWidget(self.album_rescan_btn)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 左侧：专辑列表
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(CaptionLabel("专辑列表"))
        self.album_list = QListWidget(self)
        self.album_list.setAlternatingRowColors(True)
        self.album_list.itemClicked.connect(self._on_album_clicked)
        left_layout.addWidget(self.album_list)
        splitter.addWidget(left)

        # 右侧：该专辑的歌曲
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.album_title = StrongBodyLabel("请选择专辑")
        right_layout.addWidget(self.album_title)
        self.album_song_list = QListWidget(self)
        self.album_song_list.setAlternatingRowColors(True)
        self.album_song_list.itemDoubleClicked.connect(self._play_album_song)
        self.album_song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.album_song_list.customContextMenuRequested.connect(self._on_album_song_context_menu)
        right_layout.addWidget(self.album_song_list)
        splitter.addWidget(right)

        splitter.setSizes([220, 380])
        layout.addWidget(splitter, 1)

        self._album_map: Dict[str, List[str]] = {}  # {专辑名: [文件路径, ...]}
        self.bottom_tabs.addTab(tab, "按专辑")
        self._load_albums()

    # ------------------------------------------------------------------
    # 音乐收藏夹功能
    # ------------------------------------------------------------------
    def _load_folders(self):
        """加载收藏夹列表，并显示封面色块图标"""
        self.folder_list.clear()
        if not self._db:
            return
        try:
            folders = self._db.get_music_folders()
        except Exception:
            folders = []
        if not folders:
            item = QListWidgetItem("📂 暂无收藏夹，点击「新建」创建")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.folder_list.addItem(item)
            return
        for f in folders:
            name = f.get('name', '未命名')
            count = f.get('item_count', 0)
            item = QListWidgetItem(f"{name}  ({count}首)")
            item.setData(Qt.UserRole, f)
            # 使用 cover_color 绘制圆形色块作为封面图标
            cover_color = f.get('cover_color', '#667EEA')
            icon = self._create_color_icon(cover_color, size=32)
            item.setIcon(icon)
            self.folder_list.addItem(item)

    def _create_color_icon(self, color_hex: str, size: int = 32) -> QIcon:
        """根据颜色值创建一个圆形色块图标"""
        from PySide6.QtGui import QPixmap, QPainter, QColor, QBrush
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(color_hex)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, size - 4, size - 4)
        painter.end()
        return QIcon(pixmap)

    def _on_folder_clicked(self, item):
        """点击收藏夹，加载歌曲列表"""
        data = item.data(Qt.UserRole)
        if not data:
            return
        self._current_folder_id = data.get('id', -1)
        self.folder_title.setText(f"🎵 {data.get('name', '')}")
        self.folder_add_btn.setEnabled(True)
        self._load_folder_songs()

    def _load_folder_songs(self):
        """加载收藏夹内歌曲，并尝试显示音频封面图标"""
        self.folder_song_list.clear()
        if self._current_folder_id < 0 or not self._db:
            return
        try:
            items = self._db.get_music_folder_items(self._current_folder_id)
        except Exception:
            items = []
        if not items:
            item = QListWidgetItem("📭 暂无歌曲，点击「添加音频」导入")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.folder_song_list.addItem(item)
            return
        # 封面提取限制：歌曲过多时只提取前 30 首，避免阻塞 UI
        max_cover_load = 30
        for idx, s in enumerate(items):
            name = s.get('title') or s.get('file_name', '未知')
            artist = s.get('artist', '')
            text = name + (f" - {artist}" if artist else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s)
            item.setToolTip(s.get('file_path', ''))
            # 尝试提取封面图标（限制数量避免卡顿）
            if idx < max_cover_load:
                fp = s.get('file_path', '')
                if fp and os.path.isfile(fp):
                    try:
                        cover_data = _extract_cover_from_audio(fp)
                        if cover_data:
                            img = QImage()
                            img.loadFromData(cover_data)
                            if not img.isNull():
                                pixmap = QPixmap.fromImage(img).scaled(
                                    40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                )
                                item.setIcon(QIcon(pixmap))
                    except Exception:
                        pass
            self.folder_song_list.addItem(item)

    def _create_folder(self):
        """创建新收藏夹"""
        name, ok = QInputDialog.getText(self, "新建收藏夹", "收藏夹名称:")
        if not ok or not name.strip():
            return
        try:
            fid = self._db.create_music_folder(name.strip())
            if fid > 0:
                from qfluentwidgets import InfoBar
                InfoBar.success("创建成功", f"收藏夹「{name.strip()}」已创建",
                                duration=2500, parent=self)
                self._load_folders()
        except Exception as e:
            logger.error(f"创建收藏夹失败: {e}")

    def _folder_context_menu(self, point):
        """收藏夹右键菜单"""
        item = self.folder_list.itemAt(point)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        act_delete = menu.addAction("🗑 删除收藏夹")
        action = menu.exec(self.folder_list.mapToGlobal(point))
        if action == act_delete:
            from qfluentwidgets import MessageBox
            w = MessageBox("确认删除",
                           f"确定删除收藏夹「{data.get('name')}」吗？\n收藏夹内的歌曲记录将被清除（文件不会被删除）。",
                           self)
            if w.exec():
                try:
                    self._db.delete_music_folder(data.get('id', -1))
                    self._current_folder_id = -1
                    self.folder_title.setText("请选择收藏夹")
                    self.folder_song_list.clear()
                    self.folder_add_btn.setEnabled(False)
                    self._load_folders()
                except Exception as e:
                    logger.error(f"删除收藏夹失败: {e}")

    def _add_files_to_folder(self):
        """添加音频文件到当前收藏夹"""
        if self._current_folder_id < 0:
            return
        ext_filter = " ".join(f"*{e}" for e in AUDIO_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频文件", "",
            f"音频文件 ({ext_filter});;所有文件 (*.*)"
        )
        if not files:
            return
        count = 0
        for path in files:
            if not path.lower().endswith(AUDIO_EXTENSIONS):
                continue
            meta = _extract_metadata(path)
            try:
                self._db.add_to_music_folder(
                    self._current_folder_id, path,
                    os.path.basename(path),
                    meta.get('title', ''),
                    meta.get('artist', ''),
                    meta.get('album', ''),
                    int(meta.get('duration', 0))
                )
                count += 1
            except Exception as e:
                logger.warning(f"添加音频到收藏夹失败: {e}")
        from qfluentwidgets import InfoBar
        if count > 0:
            InfoBar.success("添加成功", f"已添加 {count} 首歌曲",
                            duration=2500, parent=self)
        else:
            InfoBar.warning("未添加", "选择的文件中没有支持的音频格式",
                            duration=2500, parent=self)
        self._load_folder_songs()
        self._load_folders()

    def _folder_song_context_menu(self, point):
        """收藏夹歌曲右键菜单"""
        item = self.folder_song_list.itemAt(point)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        file_path = data.get('file_path', '')
        menu = QMenu(self)
        act_play = menu.addAction("▶️ 播放")
        act_edit = menu.addAction("📝 编辑信息")
        menu.addSeparator()
        act_remove = menu.addAction("💔 从收藏夹移除")
        action = menu.exec(self.folder_song_list.mapToGlobal(point))
        if action == act_play:
            self._play_folder_song(item)
        elif action == act_edit:
            if file_path and os.path.isfile(file_path):
                self._edit_tags(file_path)
        elif action == act_remove:
            try:
                self._db.remove_from_music_folder(
                    self._current_folder_id, file_path)
                self._load_folder_songs()
                self._load_folders()
            except Exception as e:
                logger.error(f"移除歌曲失败: {e}")

    def _play_folder_song(self, item):
        """双击播放收藏夹中的歌曲——按收藏夹顺序播放"""
        data = item.data(Qt.UserRole)
        if not data:
            return
        file_path = data.get('file_path', '')
        if not os.path.isfile(file_path):
            from qfluentwidgets import InfoBar
            InfoBar.warning("文件不存在", file_path, duration=3000, parent=self)
            return
        # 收集当前收藏夹中所有歌曲路径
        folder_songs = []
        clicked_idx = 0
        for i in range(self.folder_song_list.count()):
            it = self.folder_song_list.item(i)
            d = it.data(Qt.UserRole)
            if isinstance(d, dict) and d.get('file_path', ''):
                p = d['file_path']
                if p == file_path:
                    clicked_idx = len(folder_songs)
                folder_songs.append(p)
        # 使用子列表播放，按收藏夹顺序
        self._play_from_sub_list(folder_songs, clicked_idx)

    # ------------------------------------------------------------------
    # 按歌手分类功能
    # ------------------------------------------------------------------
    def _load_artists(self):
        """从播放列表的所有音频中提取歌手信息并分组"""
        self.artist_list.clear()
        self._artist_map.clear()
        for path in self._playlist:
            meta = self._get_meta_cached(path)
            artist = (meta.get('artist', '') or '').strip() or "未知歌手"
            self._artist_map.setdefault(artist, []).append(path)

        # 按歌曲数量降序排列
        sorted_artists = sorted(self._artist_map.items(),
                                key=lambda x: len(x[1]), reverse=True)
        for artist, songs in sorted_artists:
            item = QListWidgetItem(f"🎤 {artist}  ({len(songs)}首)")
            item.setData(Qt.UserRole, artist)
            self.artist_list.addItem(item)

    def _on_artist_clicked(self, item):
        """点击歌手，加载其歌曲列表"""
        artist = item.data(Qt.UserRole)
        if not artist:
            return
        self.artist_title.setText(f"🎤 {artist}")
        self.artist_song_list.clear()
        songs = self._artist_map.get(artist, [])
        for path in songs:
            meta = self._get_meta_cached(path)
            title = (meta.get('title', '') or '').strip() or os.path.splitext(os.path.basename(path))[0]
            album = (meta.get('album', '') or '').strip()
            text = f"♪ {title}" + (f"  [{album}]" if album else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.artist_song_list.addItem(item)

    def _play_artist_song(self, item):
        """双击播放歌手分类中的歌曲——按歌手分类顺序播放"""
        path = item.data(Qt.UserRole)
        if not path or not os.path.isfile(path):
            return
        # 获取当前歌手的所有歌曲
        songs = []
        clicked_idx = 0
        for i in range(self.artist_song_list.count()):
            it = self.artist_song_list.item(i)
            p = it.data(Qt.UserRole)
            if p:
                if p == path:
                    clicked_idx = len(songs)
                songs.append(p)
        self._play_from_sub_list(songs, clicked_idx)

    # ------------------------------------------------------------------
    # 按专辑分类功能
    # ------------------------------------------------------------------
    def _load_albums(self):
        """从播放列表的所有音频中提取专辑信息并分组"""
        self.album_list.clear()
        self._album_map.clear()
        for path in self._playlist:
            meta = self._get_meta_cached(path)
            album = (meta.get('album', '') or '').strip() or "未知专辑"
            self._album_map.setdefault(album, []).append(path)

        # 按歌曲数量降序排列
        sorted_albums = sorted(self._album_map.items(),
                               key=lambda x: len(x[1]), reverse=True)
        for album, songs in sorted_albums:
            item = QListWidgetItem(f"💿 {album}  ({len(songs)}首)")
            item.setData(Qt.UserRole, album)
            self.album_list.addItem(item)

    def _on_album_clicked(self, item):
        """点击专辑，加载其歌曲列表"""
        album = item.data(Qt.UserRole)
        if not album:
            return
        self.album_title.setText(f"💿 {album}")
        self.album_song_list.clear()
        songs = self._album_map.get(album, [])
        for path in songs:
            meta = self._get_meta_cached(path)
            title = (meta.get('title', '') or '').strip() or os.path.splitext(os.path.basename(path))[0]
            artist = (meta.get('artist', '') or '').strip()
            text = f"♪ {title}" + (f"  - {artist}" if artist else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.album_song_list.addItem(item)

    def _play_album_song(self, item):
        """双击播放专辑分类中的歌曲——按专辑分类顺序播放"""
        path = item.data(Qt.UserRole)
        if not path or not os.path.isfile(path):
            return
        # 获取当前专辑的所有歌曲
        songs = []
        clicked_idx = 0
        for i in range(self.album_song_list.count()):
            it = self.album_song_list.item(i)
            p = it.data(Qt.UserRole)
            if p:
                if p == path:
                    clicked_idx = len(songs)
                songs.append(p)
        self._play_from_sub_list(songs, clicked_idx)

    # ------------------------------------------------------------------
    # 歌手/专辑列表的右键菜单（编辑信息）
    # ------------------------------------------------------------------
    def _on_artist_song_context_menu(self, point: QPoint):
        """歌手分类歌曲右键菜单"""
        item = self.artist_song_list.itemAt(point)
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        menu = QMenu(self)
        act_play = menu.addAction("▶️ 播放")
        act_play.triggered.connect(lambda: self._play_artist_song(item))
        menu.addSeparator()
        act_edit = menu.addAction("📝 编辑信息")
        act_edit.triggered.connect(lambda: self._edit_tags(path))
        menu.addSeparator()
        act_open = menu.addAction("📁 打开所在文件夹")
        act_open.triggered.connect(lambda: self._open_in_explorer(path))
        menu.exec(self.artist_song_list.mapToGlobal(point))

    def _on_album_song_context_menu(self, point: QPoint):
        """专辑分类歌曲右键菜单"""
        item = self.album_song_list.itemAt(point)
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        menu = QMenu(self)
        act_play = menu.addAction("▶️ 播放")
        act_play.triggered.connect(lambda: self._play_album_song(item))
        menu.addSeparator()
        act_edit = menu.addAction("📝 编辑信息")
        act_edit.triggered.connect(lambda: self._edit_tags(path))
        menu.addSeparator()
        act_open = menu.addAction("📁 打开所在文件夹")
        act_open.triggered.connect(lambda: self._open_in_explorer(path))
        menu.exec(self.album_song_list.mapToGlobal(point))

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _on_rescan_and_notify(self):
        """手动点击重新扫描：设置标记使扫描后自动分类结果可通知"""
        self._scan_notify_next = True
        self._scan_audio_files()

    def _connect_signals(self):
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        self.play_btn.clicked.connect(self._toggle_play)
        self.prev_btn.clicked.connect(self._play_prev)
        self.next_btn.clicked.connect(self._play_next)
        # 手动点击重新扫描 → 下次 _scan_audio_files 执行完自动分类后弹整理结果
        self.rescan_btn.clicked.connect(self._on_rescan_and_notify)
        self.clean_btn.clicked.connect(self._clean_empty_files)
        self.play_mode_btn.clicked.connect(self._cycle_play_mode)
        self.fav_btn.clicked.connect(self._toggle_favorite)
        self.load_lrc_btn.clicked.connect(self._manual_load_lrc)
        self.edit_lrc_btn.clicked.connect(self._edit_lyrics)
        self.search_lrc_btn.clicked.connect(self._search_lyrics_online)
        self.eq_btn.clicked.connect(self._show_equalizer)
        self.lyrics_delay_minus_btn.clicked.connect(lambda: self._adjust_lyrics_offset(-300))
        self.lyrics_delay_plus_btn.clicked.connect(lambda: self._adjust_lyrics_offset(300))
        self.translate_lrc_btn.clicked.connect(self._translate_lyrics)
        self.correct_lrc_btn.clicked.connect(self._correct_translation)
        self.delete_trans_btn.clicked.connect(self._delete_translation)
        self.lyrics_mode_combo.currentIndexChanged.connect(self._on_lyrics_mode_changed)
        self.sleep_btn.clicked.connect(self._show_sleep_menu)
        self.import_btn.clicked.connect(self._import_playlist)
        self.export_btn.clicked.connect(self._export_playlist)
        self.sync_lib_btn.clicked.connect(self._sync_to_transfer)
        self.batch_btn.clicked.connect(self._show_batch_menu)
        self.dup_btn.clicked.connect(self._detect_duplicates)
        # 手动点击整理分类 → 独立触发自动分类并通知结果
        self.categorize_btn.clicked.connect(
            lambda: self._auto_categorize_playlist(notify=True)
        )

        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderMoved.connect(self._on_slider_moved)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)

        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_btn.clicked.connect(self._toggle_mute)

        self.playlist_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.playlist_list.customContextMenuRequested.connect(self._on_context_menu)
        self.search_combo.currentIndexChanged.connect(lambda: self._apply_filter())

        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)

        self.mini_btn.clicked.connect(self._toggle_mini_player)
        self.desktop_lyrics_switch.checkedChanged.connect(self._toggle_desktop_lyrics)

    # ------------------------------------------------------------------
    # 快捷键（本地 + 全局）
    # ------------------------------------------------------------------
    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=self._play_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self._play_next)
        # 音量控制（与视频播放器保持一致）
        QShortcut(QKeySequence(Qt.Key_Up), self,
                  activated=lambda: self.volume_slider.setValue(min(100, self.volume_slider.value() + 5)))
        QShortcut(QKeySequence(Qt.Key_Down), self,
                  activated=lambda: self.volume_slider.setValue(max(0, self.volume_slider.value() - 5)))
        QShortcut(QKeySequence(Qt.Key_M), self, activated=self._toggle_mute)
        # 快进/快退 10 秒（与视频播放器保持一致）
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self._seek_backward)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self._seek_forward)

        # 全局快捷键通过 _setup_global_hotkeys 使用 Win32 API 注册，后台也生效
        self._setup_global_hotkeys()

    def _setup_global_hotkeys(self):
        """设置全局快捷键（使用 Win32 RegisterHotKey，后台也可用）

        关键修复：
        1. 后台线程通过 Qt 信号 hotkey_triggered 把动作名传回主线程，
           避免在后台线程直接调用 QTimer.singleShot（跨线程不安全）。
        2. 用 PeekMessage 轮询 + sleep 避免 GetMessage 永久阻塞导致
           线程无法响应退出。
        """
        import json as _json
        import ctypes
        from ctypes import wintypes

        # 连接信号到槽（Qt 自动使用 QueuedConnection 跨线程传递到主线程）
        if self._hotkey_connected:
            self.hotkey_triggered.disconnect()
        self.hotkey_triggered.connect(self._on_hotkey_triggered, Qt.QueuedConnection)
        self._hotkey_connected = True

        # 从配置读取快捷键
        try:
            hk_cfg = _json.loads(get_config().get(get_config().global_hotkeys))
        except Exception:
            hk_cfg = {
                "play_pause": "ctrl+alt+space",
                "prev": "ctrl+alt+left",
                "next": "ctrl+alt+right",
                "vol_up": "ctrl+alt+up",
                "vol_down": "ctrl+alt+down",
            }

        # 解析快捷键字符串为 (modifiers, vk_code)
        MOD_MAP = {'ctrl': 0x0002, 'alt': 0x0001, 'shift': 0x0004, 'cmd': 0x0008}
        VK_MAP = {
            'space': 0x20, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
            'return': 0x0D, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09,
            'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
            'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
            'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
            'f11': 0x7A, 'f12': 0x7B,
        }

        hotkeys_to_register = {}
        for action, combo_str in hk_cfg.items():
            parts = [p.strip().lower() for p in combo_str.split('+')]
            mods = 0
            vk = 0
            for p in parts:
                if p in MOD_MAP:
                    mods |= MOD_MAP[p]
                elif p in VK_MAP:
                    vk = VK_MAP[p]
                elif len(p) == 1 and p.isalpha():
                    vk = ord(p.upper())  # A-Z => 0x41-0x5A
                elif len(p) == 1 and p.isdigit():
                    vk = ord(p)  # 0-9 => 0x30-0x39
            if vk and mods:
                hotkeys_to_register[action] = (mods | 0x4000, vk)  # 0x4000 = MOD_NOREPEAT

        if not hotkeys_to_register:
            logger.warning("无可注册的全局快捷键")
            self._pynput_available = False
            return

        # 创建后台线程注册热键并监听消息
        import threading

        # 用 list 包装共享状态，便于线程内修改
        stop_flag = {'stop': False}

        def _hotkey_thread():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # 动作ID映射
            action_ids = {}
            hotkey_id = 1
            for action in hotkeys_to_register:
                action_ids[hotkey_id] = action
                hotkey_id += 1

            # 注册热键
            registered = []
            for hid, action in action_ids.items():
                mods, vk = hotkeys_to_register[action]
                if user32.RegisterHotKey(None, hid, mods, vk):
                    registered.append((hid, action))
                    logger.info(f"已注册全局热键: {action} (id={hid})")
                else:
                    err = kernel32.GetLastError()
                    logger.warning(f"注册热键失败: {action} (错误码={err}, 可能被其他程序占用)")

            if not registered:
                logger.warning("所有全局热键注册失败，降级为应用内快捷键")
                return

            # 消息循环：用 PeekMessage 非阻塞轮询，便于响应停止标志
            msg = wintypes.MSG()
            PM_REMOVE = 0x0001
            logger.info("全局热键消息循环已启动（后台可用）")
            while not stop_flag['stop']:
                # PeekMessage 非阻塞查询
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    if msg.message == 0x0312:  # WM_HOTKEY
                        hid = msg.wParam
                        action = action_ids.get(hid)
                        if action:
                            # 通过 Qt 信号把动作名传到主线程（线程安全）
                            self.hotkey_triggered.emit(action)
                # 适当休眠，避免 CPU 占用过高
                kernel32.Sleep(15)  # ~60fps 轮询

            # 注销热键
            for hid, _ in registered:
                user32.UnregisterHotKey(None, hid)
            logger.info("全局热键已注销")

        self._hotkey_stop_flag = stop_flag
        self._hotkey_thread = threading.Thread(target=_hotkey_thread, daemon=True)
        self._hotkey_thread.start()
        self._pynput_available = True
        logger.info("Win32 全局快捷键线程已启动")

    def _on_hotkey_triggered(self, action: str):
        """主线程槽函数：执行热键动作（由 hotkey_triggered 信号触发）"""
        if action == 'play_pause':
            self._toggle_play()
        elif action == 'prev':
            self._play_prev()
        elif action == 'next':
            self._play_next()
        elif action == 'vol_up':
            self.volume_slider.setValue(min(100, self.volume_slider.value() + 5))
        elif action == 'vol_down':
            self.volume_slider.setValue(max(0, self.volume_slider.value() - 5))

    # ------------------------------------------------------------------
    # 设置加载/保存
    # ------------------------------------------------------------------
    def _load_settings(self):
        if not self._db:
            return
        vol = self._db.get_setting("player_volume", None)
        if vol is not None:
            try:
                v = int(vol)
                self._last_volume = v
                self.volume_slider.setValue(v)
            except (ValueError, TypeError):
                pass
        mode = self._db.get_setting("play_mode", None)
        if mode and mode in PLAY_MODE_ICONS:
            self._play_mode = mode
            self.play_mode_btn.setIcon(PLAY_MODE_ICONS[mode])
            self.play_mode_btn.setToolTip(PLAY_MODE_NAMES[mode])

        rate_str = self._db.get_setting("playback_rate", None)
        if rate_str:
            try:
                rate_val = float(rate_str)
                self._playback_rate = rate_val
                display = f"{rate_val:.2f}".rstrip('0').rstrip('.') + "x"
                matches = [r for r in PLAYBACK_RATES if abs(float(r.replace('x', '')) - rate_val) < 0.01]
                if matches:
                    self.rate_combo.setCurrentText(matches[0])
                self._player.setPlaybackRate(rate_val)
            except (ValueError, TypeError):
                pass

    def _save_settings(self):
        if not self._db:
            return
        self._db.set_setting("player_volume", str(self.volume_slider.value()))
        self._db.set_setting("play_mode", self._play_mode)
        self._db.set_setting("playback_rate", f"{self._playback_rate:.4f}")

    # ------------------------------------------------------------------
    # 倍速控制
    # ------------------------------------------------------------------
    def _on_rate_changed(self, index: int):
        try:
            text = self.rate_combo.currentText()
            rate = float(text.replace('x', ''))
            self._playback_rate = rate
            self._player.setPlaybackRate(rate)
            self._save_settings()
        except Exception as e:
            logger.warning(f"切换倍速失败: {e}")

    # ------------------------------------------------------------------
    # 迷你播放器
    # ------------------------------------------------------------------
    def _toggle_mini_player(self):
        if self._mini_player is None:
            self._mini_player = AudioPlayerPage.MiniPlayer(self)
            self._mini_player.close_requested.connect(self._close_mini_player)
            screen = QApplication.primaryScreen().availableGeometry()
            self._mini_player.move(screen.width() - 400, 120)
            self._mini_player.show()
            InfoBar.success("迷你模式", "已开启迷你播放模式",
                            duration=2000, parent=self)
        else:
            self._close_mini_player()

    def _close_mini_player(self):
        if self._mini_player:
            try:
                self._mini_player.close()
            except Exception:
                pass
            self._mini_player = None
            InfoBar.info("迷你模式", "已退出迷你播放模式",
                         duration=2000, parent=self)

    # ------------------------------------------------------------------
    # 桌面悬浮歌词
    # ------------------------------------------------------------------
    def _toggle_desktop_lyrics(self, checked: bool):
        if checked:
            if self._desktop_lyrics is None:
                self._desktop_lyrics = DesktopLyrics(self)
                self._desktop_lyrics.close_requested.connect(
                    lambda: self.desktop_lyrics_switch.setChecked(False)
                )
                screen = QApplication.primaryScreen().availableGeometry()
                self._desktop_lyrics.move(
                    (screen.width() - 760) // 2,
                    screen.height() - 140
                )
            self._desktop_lyrics.show()
            InfoBar.success("桌面歌词", "已开启桌面悬浮歌词",
                            duration=2000, parent=self)
        else:
            if self._desktop_lyrics:
                try:
                    self._desktop_lyrics.close()
                except Exception:
                    pass
                self._desktop_lyrics = None

    # ------------------------------------------------------------------
    # 扫描音频文件
    # ------------------------------------------------------------------
    @property
    def _active_playlist(self) -> List[str]:
        """获取当前活跃的播放列表（子列表优先，否则主列表）"""
        return self._sub_playlist if self._sub_playlist is not None else self._playlist

    def _play_from_sub_list(self, paths: List[str], start_index: int = 0):
        """从子播放列表（收藏夹/歌手/专辑）开始播放。
        设置 _sub_playlist 并从 start_index 处开始播放。
        主播放列表的 _current_index 同步更新到子列表中歌曲在主列表的位置。"""
        if not paths:
            return
        self._sub_playlist = list(paths)  # 复制一份避免外部修改
        path = self._sub_playlist[start_index]
        # 同步主播放列表索引
        if path in self._playlist:
            self._current_index = self._playlist.index(path)
        else:
            self._current_index = -1
        # 使用子列表播放
        self._player.setSource(QUrl.fromLocalFile(path))
        self._do_play()
        self._update_play_ui(path)
        # 高亮主列表中的当前歌曲
        self._highlight_current_in_main_list()

    def _update_play_ui(self, path: str):
        """更新播放界面（标题、歌手、封面、歌词、收藏按钮等）"""
        try:
            display_name = os.path.basename(path)
            self.track_title_label.setText(display_name)

            meta = _extract_metadata(path)
            if meta['title']:
                self.track_title_label.setText(meta['title'])
            self.track_artist_label.setText(
                meta['artist'] or os.path.dirname(path).split(os.sep)[-1]
            )

            cover_data = _extract_cover_from_audio(path)
            pixmap = None
            if cover_data:
                img = QImage()
                img.loadFromData(cover_data)
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img).scaled(
                        200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.cover_label.set_pixmap(pixmap)
                else:
                    self.cover_label.set_pixmap(QPixmap())
            else:
                self.cover_label.set_pixmap(QPixmap())

            if self._mini_player:
                self._mini_player.update_info(
                    self.track_title_label.text(),
                    self.track_artist_label.text(),
                    pixmap
                )

            self._load_lyrics(path)
            self._update_fav_button(path)

            if self._db:
                try:
                    self._db.add_play_history(
                        file_path=path,
                        file_name=display_name,
                        title=meta.get('title', ''),
                        artist=meta.get('artist', ''),
                        album=meta.get('album', ''),
                        duration=self._player.duration(),
                        position_ms=0
                    )
                except Exception:
                    pass
            self._start_audio_level_analysis(path)
        except Exception as e:
            logger.debug(f"更新播放UI失败: {e}")

    def _highlight_current_in_main_list(self):
        """在主播放列表中高亮当前正在播放的歌曲"""
        if self._current_index >= 0 and self._current_index < self.playlist_list.count():
            self.playlist_list.setCurrentRow(self._current_index)

    def _get_download_path(self) -> str:
        """获取音频文件扫描目录（统一在 musics 子目录下）"""
        try:
            config = get_config()
            path = config.get(config.download_path)
            if path:
                musics_path = os.path.join(str(path), "musics")
                os.makedirs(musics_path, exist_ok=True)
                return musics_path
            return ""
        except Exception as e:
            logger.warning(f"获取下载路径失败: {e}")
            return ""

    def _clean_empty_files(self):
        """清理空音频文件和空目录"""
        from qfluentwidgets import InfoBar
        download_path = self._get_download_path()
        if not download_path or not os.path.isdir(download_path):
            InfoBar.info("没有文件", "音乐目录不存在", duration=2000, parent=self)
            return

        deleted_files = 0
        deleted_dirs = 0

        # 遍历所有子目录，删除空音频文件（0 字节）
        for root, dirs, files in os.walk(download_path, topdown=False):
            for name in files:
                if name.lower().endswith(AUDIO_EXTENSIONS):
                    path = os.path.join(root, name)
                    try:
                        if os.path.getsize(path) == 0:
                            os.remove(path)
                            deleted_files += 1
                            logger.info(f"删除空音频文件: {path}")
                    except Exception as e:
                        logger.debug(f"删除文件失败 {path}: {e}")
            # 删除空目录
            try:
                if root != download_path and not os.listdir(root):
                    os.rmdir(root)
                    deleted_dirs += 1
                    logger.info(f"删除空目录: {root}")
            except Exception:
                pass

        if deleted_files > 0 or deleted_dirs > 0:
            InfoBar.success(
                "清理完成",
                f"删除 {deleted_files} 个空文件，{deleted_dirs} 个空目录",
                duration=3000, parent=self
            )
            # 清理后重新扫描
            self._scan_audio_files()
        else:
            InfoBar.info("无需清理", "未发现空文件或空目录", duration=2000, parent=self)

    def _scan_audio_files(self):
        # 停止播放器，避免清空播放列表时播放器访问无效索引导致崩溃
        try:
            if self._player.playbackState() != QMediaPlayer.StoppedState:
                self._player.stop()
        except Exception:
            pass

        self.playlist_list.setUpdatesEnabled(False)
        self.playlist_list.clear()
        self._playlist.clear()
        self._current_index = -1
        self.playlist_list.setUpdatesEnabled(True)
        # 清空元数据缓存（文件可能已被外部修改标签）
        self._invalidate_meta_cache()

        download_path = self._get_download_path()
        if not download_path or not os.path.isdir(download_path):
            self._update_empty_hint()
            return

        # 使用 scandir_recursive 加速扫描（比 os.walk 快 2~3 倍）
        found: List[str] = []
        try:
            found = scandir_recursive(download_path, AUDIO_EXTENSIONS)
        except Exception as e:
            logger.error(f"扫描音频文件失败: {e}", exc_info=True)

        found.sort(key=lambda p: os.path.basename(p).lower())
        self._playlist = found
        self._populate_list()
        self._update_empty_hint()
        # 同步刷新歌手/专辑分类
        self._load_artists()
        self._load_albums()
        logger.info(f"扫描完成，共找到 {len(self._playlist)} 个音频文件")

        # ===== 自动分类：扫描完后立即整理未归类的文件 =====
        # 启动时首次扫描不弹 InfoBar（避免打扰），手动点击刷新扫描按钮触发的会调用独立整理按钮才弹
        notify = getattr(self, '_scan_notify_next', False)
        try:
            if hasattr(self, '_scan_notify_next'):
                delattr(self, '_scan_notify_next')
        except Exception:
            pass
        try:
            moved, _, _ = self._auto_categorize_playlist(notify=notify)
            if moved > 0:
                # 分类移动了文件后，重新刷新 UI（播放列表、歌手/专辑页也要重新整理
                # _auto_categorize_playlist 已同步 self._playlist 已更新，
                # 这里重新 populate + 即可
                self._populate_list()
                self._load_artists()
                self._load_albums()
                self._load_folders()
                if self._current_folder_id:
                    self._load_folder_songs()
        except Exception as e:
            logger.warning(f"扫描后自动分类失败: {e}")

    def _get_meta_cached(self, path: str) -> Dict[str, str]:
        """获取音频元数据（带缓存）。文件移动后应调用 _invalidate_meta_cache 清除。"""
        if path in self._meta_cache:
            return self._meta_cache[path]
        meta = _extract_metadata(path)
        self._meta_cache[path] = meta
        return meta

    def _invalidate_meta_cache(self, path: str = None):
        """清除元数据缓存。path=None 时清空全部。"""
        if path is None:
            self._meta_cache.clear()
        else:
            self._meta_cache.pop(path, None)

    def _display_title_for(self, path: str) -> str:
        """生成播放列表显示文本：优先用歌名标签，无标签时回退到文件名（去扩展名）。
        格式：歌名  或  歌名 - 歌手  或  文件名"""
        meta = self._get_meta_cached(path)
        title = (meta.get('title', '') or '').strip()
        artist = (meta.get('artist', '') or '').strip()
        if not title:
            # 无标签时使用文件名（去掉扩展名），便于识别
            title = os.path.splitext(os.path.basename(path))[0]
        if artist:
            return f"{title} - {artist}"
        return title

    def _populate_list(self, items: Optional[List[str]] = None):
        self.playlist_list.setUpdatesEnabled(False)
        self.playlist_list.clear()
        source = items if items is not None else self._playlist
        for path in source:
            display_name = self._display_title_for(path)
            prefix = ""
            if self._db and self._db.is_favorite(path):
                prefix = "❤ "
            item = QListWidgetItem(f"{prefix}{display_name}")
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.playlist_list.addItem(item)
        self.playlist_list.setUpdatesEnabled(True)
        self.playlist_list.update()

    def _update_empty_hint(self):
        empty = self.playlist_list.count() == 0
        self.empty_hint.setVisible(empty)
        self.playlist_list.setVisible(not empty)

    # ------------------------------------------------------------------
    # 筛选
    # ------------------------------------------------------------------
    def _apply_filter(self):
        mode = self.search_combo.currentText()
        if mode == "全部":
            self._populate_list()
        elif mode == "收藏" and self._db:
            favs = self._db.get_favorites()
            fav_paths = [f['file_path'] for f in favs if os.path.isfile(f['file_path'])]
            self._populate_list(fav_paths)
        elif mode == "最近播放" and self._db:
            history = self._db.get_play_history(limit=200)
            hist_paths = [h['file_path'] for h in history if os.path.isfile(h['file_path'])]
            self._populate_list(hist_paths)

    # ------------------------------------------------------------------
    # 播放控制
    # ------------------------------------------------------------------
    def _toggle_play(self):
        if self._current_index < 0 and self._playlist:
            self._play_index(0)
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._do_play()
        elif state == QMediaPlayer.PlaybackState.StoppedState:
            if self._current_index >= 0:
                self._do_play()
            elif self._playlist:
                self._play_index(0)

    def _do_play(self):
        """统一的播放方法，确保与视频互斥"""
        window = self.window()
        if window and hasattr(window, 'stop_video_requested'):
            window.stop_video_requested.emit()
        self._player.play()

    def _play_index(self, index: int, resume: bool = True):
        if not self._playlist or not (0 <= index < len(self._playlist)):
            return

        # 切换歌曲时中止正在进行的翻译
        self._translate_aborted = True

        if self._current_index >= 0 and self._db:
            try:
                if self._current_index < len(self._playlist):
                    pos = self._player.position()
                    if pos > 1000:
                        self._db.save_position(self._playlist[self._current_index], pos)
            except Exception:
                pass

        self._current_index = index
        path = self._playlist[index]
        try:
            self._player.stop()
            url = QUrl.fromLocalFile(path)
            self._player.setSource(url)

            resume_pos = 0
            if resume and self._db:
                saved = self._db.get_position(path)
                if saved and saved > 1000:
                    resume_pos = saved

            self._do_play()
            self._player.setPlaybackRate(self._playback_rate)

            # 启动音频电平分析（用于桌面歌词声浪与音乐同步）
            self._start_audio_level_analysis(path)

            display_name = os.path.basename(path)
            self.track_title_label.setText(display_name)

            meta = _extract_metadata(path)
            if meta['title']:
                self.track_title_label.setText(meta['title'])
            self.track_artist_label.setText(
                meta['artist'] or os.path.dirname(path).split(os.sep)[-1]
            )

            cover_data = _extract_cover_from_audio(path)
            pixmap = None
            if cover_data:
                img = QImage()
                img.loadFromData(cover_data)
                if not img.isNull():
                    # 使用更高分辨率显示封面（200x200，HiDPI 下更清晰）
                    pixmap = QPixmap.fromImage(img).scaled(
                        200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.cover_label.set_pixmap(pixmap)
                else:
                    self.cover_label.set_pixmap(QPixmap())
            else:
                self.cover_label.set_pixmap(QPixmap())

            if self._mini_player:
                self._mini_player.update_info(
                    self.track_title_label.text(),
                    self.track_artist_label.text(),
                    pixmap
                )

            self._load_lyrics(path)
            self._update_fav_button(path)

            if self._db:
                try:
                    self._db.add_play_history(
                        file_path=path,
                        file_name=display_name,
                        title=meta.get('title', ''),
                        artist=meta.get('artist', ''),
                        album=meta.get('album', ''),
                        duration=self._player.duration(),
                        position_ms=0
                    )
                except Exception:
                    pass

            if resume_pos > 1000:
                QTimer.singleShot(500, lambda: self._try_resume_position(resume_pos))

            self.playlist_list.setCurrentRow(index)
            logger.info(f"开始播放: {display_name}")
        except Exception as e:
            logger.error(f"播放文件失败 {path}: {e}", exc_info=True)
            self.track_title_label.setText("播放失败")

    def _try_resume_position(self, pos: int):
        try:
            duration = self._player.duration()
            if duration > 0 and pos < duration - 2000:
                self._player.setPosition(pos)
                InfoBar.success(
                    "已恢复播放位置",
                    f"从 {_format_time(pos)} 继续播放",
                    duration=3000,
                    parent=self
                ).setPosition(InfoBarPosition.TOP)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 音频电平分析（驱动桌面歌词声浪与音乐同步）
    # ------------------------------------------------------------------
    def _start_audio_level_analysis(self, audio_path: str):
        """切换歌曲时启动后台音频电平分析；若已缓存则直接使用。"""
        # 立即清空当前曲线，避免上一首的声浪数据串台
        self._current_audio_levels = []
        # 命中缓存：直接使用
        if audio_path in self._audio_level_cache:
            self._current_audio_levels = self._audio_level_cache[audio_path]
            return
        # 上一条还在跑就停掉（避免堆积）
        if self._audio_level_worker and self._audio_level_worker.isRunning():
            try:
                self._audio_level_worker.requestInterruption()
                self._audio_level_worker.quit()
                self._audio_level_worker.wait(500)
            except Exception:
                pass
        # 定位 ffmpeg（优先系统 PATH，其次项目自带 bundle）
        import shutil
        ffmpeg_path = ""
        try:
            # 1. 系统 PATH
            result = shutil.which("ffmpeg")
            if result:
                # 验证是否真的可执行（避免假阳性路径）
                import subprocess
                try:
                    r = subprocess.run(
                        [result, "-version"], capture_output=True, text=True, timeout=3,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if r.returncode == 0:
                        ffmpeg_path = result
                except Exception:
                    pass
            # 2. 项目 bundle 中的 ffmpeg
            if not ffmpeg_path:
                bundle_ffmpeg = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "参考资料", "bundle", "ffmpeg.exe"
                )
                if os.path.exists(bundle_ffmpeg):
                    ffmpeg_path = bundle_ffmpeg
        except Exception:
            ffmpeg_path = ""
        if not ffmpeg_path:
            # 没有可用 ffmpeg：直接返回空曲线（保持声浪回退到伪随机模式），不启动 worker
            logger.debug("未找到可用 ffmpeg，跳过音频电平分析，声浪使用伪随机模式")
            return
        self._audio_level_worker = _AudioLevelWorker(audio_path, ffmpeg_path, self)
        self._audio_level_worker.finished.connect(self._on_audio_level_done)
        self._audio_level_worker.start()

    def _on_audio_level_done(self, audio_path: str, levels: list):
        """音频电平分析完成回调：缓存结果，若仍是当前歌曲则立即应用。"""
        try:
            self._audio_level_cache[audio_path] = levels
        except Exception:
            return
        # 限制缓存大小，避免内存无限增长
        try:
            if len(self._audio_level_cache) > 20:
                # 删除最早加入的项（Python 3.7+ dict 保持插入顺序）
                oldest = next(iter(self._audio_level_cache))
                if oldest != audio_path:
                    self._audio_level_cache.pop(oldest, None)
        except Exception:
            pass
        # 仅当当前正在播放的就是这首歌时才应用
        try:
            if (0 <= self._current_index < len(self._playlist)
                    and self._playlist[self._current_index] == audio_path):
                self._current_audio_levels = levels
        except Exception:
            pass

    def _get_current_audio_level(self) -> float:
        """获取当前播放时刻的 RMS 音量（0~1）。
        若无数据（分析未完成或失败）返回 -1，调用方回退到伪随机波动。"""
        try:
            if not self._current_audio_levels:
                return -1.0
            pos_ms = self._player.position()
            idx = int(pos_ms / _AudioLevelWorker.INTERVAL_MS)
            if 0 <= idx < len(self._current_audio_levels):
                # 取当前位置附近 3 个点的最大值，让声浪更灵动
                lo = max(0, idx - 1)
                hi = idx + 2
                window = self._current_audio_levels[lo: hi]
                if not window:
                    return 0.0
                return max(window)
        except Exception:
            return -1.0
        return -1.0

    def _play_next(self):
        pl = self._active_playlist
        if not pl:
            return
        # 获取当前歌曲在活跃列表中的索引
        cur_path = self._playlist[self._current_index] if 0 <= self._current_index < len(self._playlist) else None
        if cur_path and cur_path in pl:
            cur_active_idx = pl.index(cur_path)
        else:
            cur_active_idx = -1

        if self._play_mode == PLAY_MODE_SINGLE:
            self._player.setPosition(0)
            self._do_play()
            return
        if self._play_mode == PLAY_MODE_RANDOM:
            if len(pl) > 1:
                next_active_idx = random.randint(0, len(pl) - 1)
                while next_active_idx == cur_active_idx:
                    next_active_idx = random.randint(0, len(pl) - 1)
            else:
                next_active_idx = 0
        else:
            if cur_active_idx < 0:
                next_active_idx = 0
            else:
                next_active_idx = (cur_active_idx + 1) % len(pl)

        next_path = pl[next_active_idx]
        if next_path in self._playlist:
            self._current_index = self._playlist.index(next_path)
        self._player.setSource(QUrl.fromLocalFile(next_path))
        self._do_play()
        self._update_play_ui(next_path)
        self._highlight_current_in_main_list()

    def _play_prev(self):
        pl = self._active_playlist
        if not pl:
            return
        cur_path = self._playlist[self._current_index] if 0 <= self._current_index < len(self._playlist) else None
        if cur_path and cur_path in pl:
            cur_active_idx = pl.index(cur_path)
        else:
            cur_active_idx = -1

        if cur_active_idx < 0:
            if pl:
                prev_path = pl[0]
                if prev_path in self._playlist:
                    self._current_index = self._playlist.index(prev_path)
                self._player.setSource(QUrl.fromLocalFile(prev_path))
                self._do_play()
                self._update_play_ui(prev_path)
            return
        prev_active_idx = (cur_active_idx - 1) % len(pl)
        prev_path = pl[prev_active_idx]
        if prev_path in self._playlist:
            self._current_index = self._playlist.index(prev_path)
        self._player.setSource(QUrl.fromLocalFile(prev_path))
        self._do_play()
        self._update_play_ui(prev_path)
        self._highlight_current_in_main_list()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击主播放列表中的歌曲，清除子列表回到主列表顺序"""
        path = item.data(Qt.UserRole)
        if not path:
            return
        # 从主列表双击播放时，清除子列表，回到主列表顺序
        self._sub_playlist = None
        try:
            index = self._playlist.index(path)
        except ValueError:
            return
        self._play_index(index)

    # ------------------------------------------------------------------
    # 播放模式
    # ------------------------------------------------------------------
    def _cycle_play_mode(self):
        modes = [PLAY_MODE_LIST, PLAY_MODE_SINGLE, PLAY_MODE_RANDOM]
        current_idx = modes.index(self._play_mode)
        self._play_mode = modes[(current_idx + 1) % len(modes)]
        self.play_mode_btn.setIcon(PLAY_MODE_ICONS[self._play_mode])
        self.play_mode_btn.setToolTip(PLAY_MODE_NAMES[self._play_mode])
        self._save_settings()
        InfoBar.success("播放模式", PLAY_MODE_NAMES[self._play_mode],
                        duration=2000, parent=self)

    # ------------------------------------------------------------------
    # 收藏
    # ------------------------------------------------------------------
    def _toggle_favorite(self):
        if self._current_index < 0 or not self._db:
            return
        path = self._playlist[self._current_index]
        if self._db.is_favorite(path):
            self._db.remove_favorite(path)
            self.fav_btn.setIcon(_make_heart_icon(filled=False))
            InfoBar.success("已取消收藏", "", duration=2000, parent=self)
        else:
            display_name = os.path.basename(path)
            meta = _extract_metadata(path)
            self._db.add_favorite(path, display_name,
                                  meta.get('title', ''), meta.get('artist', ''))
            self.fav_btn.setIcon(_make_heart_icon(filled=True))
            InfoBar.success("已添加收藏", display_name, duration=2000, parent=self)
        self._populate_list()

    def _update_fav_button(self, path: str):
        if self._db and self._db.is_favorite(path):
            self.fav_btn.setIcon(_make_heart_icon(filled=True))
        else:
            self.fav_btn.setIcon(_make_heart_icon(filled=False))

    # ------------------------------------------------------------------
    # 歌词
    # ------------------------------------------------------------------
    def _load_lyrics(self, audio_path: str):
        lrc_path = _find_lrc_for_audio(audio_path)
        if lrc_path:
            self._lyrics_data = _parse_lrc(lrc_path)
            # 尝试加载缓存的翻译
            translated = self._load_cached_translation(lrc_path)
            self.lyrics_widget.set_lyrics(self._lyrics_data, translated)
            has_trans = bool(translated) and any(t.strip() for t in translated)
            if has_trans:
                self.lyrics_mode_combo.setEnabled(True)
                self.correct_lrc_btn.setEnabled(True)
                self.delete_trans_btn.setEnabled(True)
            else:
                self.lyrics_mode_combo.setEnabled(True)
                self.correct_lrc_btn.setEnabled(False)
                self.delete_trans_btn.setEnabled(False)
        else:
            self._lyrics_data = []
            self.lyrics_widget.clear()
            self.lyrics_mode_combo.setEnabled(False)
            self.correct_lrc_btn.setEnabled(False)
            self.delete_trans_btn.setEnabled(False)

    def _load_cached_translation(self, lrc_path: str) -> list:
        """加载缓存的翻译文件（.lrc.zh.lrc），同时将文件头中的来源标记写回 InfoBar"""
        trans_path = lrc_path.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
        if os.path.isfile(trans_path):
            try:
                with open(trans_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    lines = f.readlines()
                # 解析翻译行（保留时间戳格式但只取文本）
                result = []
                source = ""
                for line in lines:
                    line = line.strip()
                    if not line:
                        result.append("")
                        continue
                    # 检查文件头中的翻译来源标记
                    if line.startswith("# 翻译来源:"):
                        source = line.split(":", 1)[1].strip()
                        continue
                    text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', line).strip()
                    result.append(text)
                # 如果有来源标记，在 InfoBar 中显示
                if source:
                    from qfluentwidgets import InfoBar
                    InfoBar.info("翻译已加载", f"来源: {source}", duration=2000,
                                 parent=self.parent() if self.parent() else None)
                return result
            except Exception:
                pass
        return []

    def _save_translation(self, lrc_path: str, translated_lines: list, source_name: str = ""):
        """保存翻译到 .zh.lrc 文件（source_name 会写入文件头）"""
        trans_path = lrc_path.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
        try:
            with open(trans_path, 'w', encoding='utf-8') as f:
                # 写入翻译来源标记（文件头注释）
                if source_name:
                    f.write(f"# 翻译来源: {source_name}\n")
                for i, (time_sec, _) in enumerate(self._lyrics_data):
                    trans = translated_lines[i] if i < len(translated_lines) else ""
                    m = int(time_sec // 60)
                    s = int(time_sec % 60)
                    ms = int((time_sec - int(time_sec)) * 100)
                    f.write(f"[{m:02d}:{s:02d}.{ms:02d}]{trans}\n")
        except Exception as e:
            logger.error(f"保存翻译失败: {e}")

    def _translate_lyrics(self):
        """联网翻译当前歌词"""
        if not self._lyrics_data:
            InfoBar.warning("无歌词", "请先加载歌词后再翻译", duration=3000, parent=self)
            return

        # 设置 abort 标志，旧的翻译线程会自动忽略
        self._translate_aborted = True

        # 检查是否已有翻译缓存
        audio_path = self._playlist[self._current_index]
        lrc_path = _find_lrc_for_audio(audio_path)
        if lrc_path and self.lyrics_widget.has_translation():
            InfoBar.success("翻译已存在", "已加载缓存的翻译，可切换显示模式",
                            duration=2000, parent=self)
            self.lyrics_mode_combo.setCurrentIndex(1)  # 切换到双语
            return

        # 检查 DeepSeek API Key 是否已配置
        from ..config import get_config
        api_key = get_config().get(get_config().deepseek_api_key)
        if not api_key:
            InfoBar.warning(
                "未配置 AI 翻译",
                "DeepSeek API Key 未设置，将使用百度翻译（质量一般）。\n"
                "可在设置页面配置 DeepSeek API Key 以获得更好的翻译效果。",
                duration=5000, parent=self
            )

        InfoBar.info("正在翻译", "正在联网翻译歌词，请稍候...", duration=3000, parent=self)
        self.translate_lrc_btn.setEnabled(False)

        # 提取原文行
        original_lines = [text for _, text in self._lyrics_data]

        # 记录当前歌曲路径，用于翻译完成后校验
        self._translate_audio_path = audio_path
        self._translate_lrc_path = lrc_path
        self._translate_aborted = False

        # 启动翻译线程
        self._translate_worker = _TranslateWorker(original_lines, parent=self)
        self._translate_worker.finished.connect(self._on_translate_finished)
        self._translate_worker.error.connect(self._on_translate_error)
        self._translate_worker.start()

    def _on_translate_finished(self, _source_path: str, translated_lines: list, source_name: str = ""):
        """翻译完成回调"""
        self.translate_lrc_btn.setEnabled(True)

        # 检查是否已被用户切换歌曲时取消（aborted）
        if getattr(self, '_translate_aborted', False):
            logger.debug("翻译已完成但用户已切换歌曲，忽略结果")
            return

        self.lyrics_widget.set_translated_lyrics(translated_lines)

        # 保存翻译缓存（校验歌曲路径是否一致）
        lrc_path = getattr(self, '_translate_lrc_path', None)
        if lrc_path and os.path.isfile(lrc_path):
            self._save_translation(lrc_path, translated_lines, source_name)

        source_tag = f"（来源: {source_name}）" if source_name else ""
        InfoBar.success("翻译完成", f"可点击下拉框切换显示模式{source_tag}",
                        duration=3000, parent=self)
        # 自动切换到双语模式
        self.lyrics_mode_combo.setCurrentIndex(1)
        # 启用人工纠正和删除翻译按钮
        self.correct_lrc_btn.setEnabled(True)
        self.delete_trans_btn.setEnabled(True)

    def _on_translate_error(self, _source_path: str, error_msg: str):
        """翻译失败回调"""
        self.translate_lrc_btn.setEnabled(True)
        InfoBar.error("翻译失败", error_msg, duration=3000, parent=self)

    def _on_lyrics_mode_changed(self, index: int):
        """歌词显示模式切换"""
        mode_map = {0: LyricsWidget.MODE_ORIGINAL, 1: LyricsWidget.MODE_BILINGUAL, 2: LyricsWidget.MODE_TRANSLATED}
        mode = mode_map.get(index, LyricsWidget.MODE_ORIGINAL)
        self.lyrics_widget.set_display_mode(mode)

    def _correct_translation(self):
        """人工纠正翻译对话框"""
        if not self._lyrics_data:
            InfoBar.warning("无歌词", "请先加载歌词", duration=2000, parent=self)
            return
        if not self.lyrics_widget.has_translation():
            InfoBar.warning("无翻译", "请先进行翻译", duration=2000, parent=self)
            return

        # 获取当前翻译
        translated_lines = self.lyrics_widget._translated_lyrics.copy() if hasattr(self.lyrics_widget, '_translated_lyrics') else []
        # 格式：原文行 | 翻译行，便于用户对照修改
        content_lines = []
        for i, (_, original) in enumerate(self._lyrics_data):
            trans = translated_lines[i] if i < len(translated_lines) else ""
            content_lines.append(f"{original}\t{trans}")
        content = "\n".join(content_lines)

        # 打开编辑对话框
        dialog = LyricsEditorDialog(
            self.track_title_label.text() or "歌词",
            content,
            None,
            self
        )
        if dialog.exec():
            # 解析修改后的内容
            corrected = []
            for line in dialog.get_text().splitlines():
                line = line.strip()
                if not line:
                    corrected.append("")
                    continue
                # 按 tab 分割，取翻译部分（第二列）
                parts = line.split("\t", 1)
                if len(parts) >= 2:
                    corrected.append(parts[1].strip())
                else:
                    corrected.append(parts[0].strip())

            # 确保行数一致
            while len(corrected) < len(self._lyrics_data):
                corrected.append("")
            corrected = corrected[:len(self._lyrics_data)]

            # 更新歌词组件
            self.lyrics_widget.set_translated_lyrics(corrected)

            # 保存到文件
            if self._current_index >= 0:
                audio_path = self._playlist[self._current_index]
                lrc_path = _find_lrc_for_audio(audio_path)
                if lrc_path:
                    self._save_translation(lrc_path, corrected)

            InfoBar.success("修改已保存", "翻译结果已更新并保存", duration=2000, parent=self)

    def _delete_translation(self):
        """删除当前歌曲的中文翻译文件（.zh.lrc）"""
        if self._current_index < 0:
            return

        audio_path = self._playlist[self._current_index]
        lrc_path = _find_lrc_for_audio(audio_path)
        if not lrc_path:
            InfoBar.warning("无翻译", "当前歌曲没有歌词文件", duration=2000, parent=self)
            return

        trans_path = lrc_path.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
        if not os.path.isfile(trans_path):
            InfoBar.warning("无翻译", "当前歌曲没有中文翻译", duration=2000, parent=self)
            return

        # 确认删除
        from qfluentwidgets import MessageBox
        msg = MessageBox(
            "确认删除翻译",
            f"确定要删除「{os.path.basename(audio_path)}」的中文翻译吗？\n此操作不可恢复。",
            self
        )
        if not msg.exec():
            return

        try:
            os.remove(trans_path)
            logger.info(f"已删除翻译文件: {trans_path}")
        except Exception as e:
            InfoBar.error("删除失败", str(e), duration=3000, parent=self)
            return

        # 清除歌词组件中的翻译数据
        self.lyrics_widget.set_translated_lyrics([])
        self.lyrics_mode_combo.setCurrentIndex(0)  # 切回原文模式
        self.correct_lrc_btn.setEnabled(False)
        self.delete_trans_btn.setEnabled(False)

        InfoBar.success("翻译已删除", "中文翻译文件已移除", duration=2000, parent=self)

    def _manual_load_lrc(self):
        if self._current_index < 0:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择歌词文件", "", "歌词文件 (*.lrc *.txt);;所有文件 (*)"
        )
        if path:
            self._lyrics_data = _parse_lrc(path)
            translated = self._load_cached_translation(path)
            self.lyrics_widget.set_lyrics(self._lyrics_data, translated)
            if self._lyrics_data:
                InfoBar.success("歌词加载成功", f"共 {len(self._lyrics_data)} 行",
                                duration=2000, parent=self)
            else:
                InfoBar.warning("歌词加载失败", "无法解析歌词文件",
                                duration=3000, parent=self)

    def _edit_lyrics(self):
        """打开歌词编辑器对话框（支持同时编辑原文和翻译）"""
        if self._current_index < 0:
            InfoBar.warning("未播放", "请先选择一首歌曲", duration=2000, parent=self)
            return

        audio_path = self._playlist[self._current_index]
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        lrc_path = _find_lrc_for_audio(audio_path)

        # 读取现有歌词内容
        existing_text = ""
        if lrc_path:
            try:
                with open(lrc_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    existing_text = f.read()
            except Exception:
                pass
        # 读取翻译歌词（.zh.lrc），追加到编辑器末尾
        if lrc_path:
            trans_path = lrc_path.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
            if os.path.isfile(trans_path):
                try:
                    with open(trans_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        trans_text = f.read().strip()
                    if trans_text:
                        existing_text += "\n\n# ===== 翻译歌词（可编辑） =====\n"
                        existing_text += trans_text
                except Exception:
                    pass

        dialog = LyricsEditorDialog(
            audio_name, existing_text,
            lrc_path=lrc_path,
            source=None,
            parent=self,
        )
        if dialog.exec():
            # 保存歌词
            lyrics_text = dialog.get_lyrics_text()
            save_path = dialog.get_save_path() or os.path.join(
                os.path.dirname(audio_path), f"{audio_name}.lrc"
            )

            # 分离原文和翻译
            final_lrc = lyrics_text
            trans_part = ""
            sep = "# ===== 翻译歌词"
            if sep in lyrics_text:
                parts = lyrics_text.split(sep, 1)
                final_lrc = parts[0].strip()
                trans_part = parts[1].strip()
                # 去掉第一行（分隔符剩余部分，如 "（可编辑） =====\n"）
                first_newline = trans_part.find("\n")
                if first_newline >= 0:
                    trans_part = trans_part[first_newline:].strip()

            try:
                # 保存原文
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(final_lrc)
                # 保存翻译
                if trans_part:
                    trans_save_path = save_path.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
                    with open(trans_save_path, 'w', encoding='utf-8') as f:
                        f.write(trans_part)
                # 重新加载歌词
                self._lyrics_data = _parse_lrc(save_path)
                translated = self._load_cached_translation(save_path)
                self.lyrics_widget.set_lyrics(self._lyrics_data, translated)
                InfoBar.success("歌词已保存", f"保存到 {os.path.basename(save_path)}",
                                duration=3000, parent=self)
            except Exception as e:
                InfoBar.error("保存失败", str(e), duration=3000, parent=self)

    def _search_lyrics_online(self):
        """在线搜索歌词（从 B 站 CC 字幕获取原文与翻译 LRC）。
        支持按歌名（标签中的 title）或按文件名两种方式搜索，用户可自选其一。"""
        if self._current_index < 0:
            InfoBar.warning("未播放", "请先选择一首歌曲", duration=2000, parent=self)
            return

        audio_path = self._playlist[self._current_index]
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        meta = _extract_metadata(audio_path)
        title = meta.get('title', '')
        artist = meta.get('artist', '')

        # 让用户选择搜索关键词来源
        if title and title != audio_name:
            choices = [f"按歌名搜索：{title}", f"按文件名搜索：{audio_name}"]
            choice, ok = QInputDialog.getItem(
                self, "搜索歌词", "请选择搜索关键词：", choices, 0, False
            )
            if not ok:
                return
            search_key = title if choice == choices[0] else audio_name
        else:
            search_key = title or audio_name

        InfoBar.info("搜索中", f"正在搜索「{search_key}」的 B 站视频...",
                     duration=3000, parent=self)

        # 第一步：后台线程用 B 站搜索接口查找视频（CC 字幕通常含歌词）
        class LyricsSearchWorker(QThread):
            candidates = Signal(list)   # [(bvid, title, author), ...]
            failed = Signal(str)        # error_message

            def __init__(self, keyword):
                super().__init__()
                self._keyword = keyword

            def run(self):
                try:
                    client = BilibiliClient()
                    result = client.search(self._keyword, page=1)
                    videos = result.videos if result else []
                    cands = [
                        (v.bvid, v.title,
                         getattr(v, 'owner_name', '') or getattr(v, 'owner', ''))
                        for v in videos[:10]
                    ]
                    if not cands:
                        self.failed.emit("未找到相关视频")
                        return
                    self.candidates.emit(cands)
                except Exception as e:
                    self.failed.emit(str(e))

        worker = LyricsSearchWorker(search_key)
        self._lyrics_search_worker = worker  # 防止被 GC

        def on_candidates(cands):
            labels = [f"{t}  |  {a}" for _, t, a in cands]
            choice, ok = QInputDialog.getItem(
                self, "选择视频", "请选择含歌词的视频（取自 B 站 CC 字幕）：",
                labels, 0, False
            )
            if not ok:
                InfoBar.info("已取消", "未获取歌词", duration=2000, parent=self)
                return
            idx = labels.index(choice)
            # 用户选的排最前，其余候选按顺序兜底（自动换到有字幕的视频）
            ordered = [cands[idx][0]] + [c[0] for c in cands if c[0] != cands[idx][0]]
            self._fetch_subtitle_lyrics(ordered, audio_path, audio_name, search_key, artist)

        def on_failed(err):
            InfoBar.warning("搜索失败", err, duration=3000, parent=self)

        worker.candidates.connect(on_candidates)
        worker.failed.connect(on_failed)
        worker.start()

    def _fetch_subtitle_lyrics(self, bvids, audio_path, audio_name, search_key, artist):
        """第二步：按顺序尝试候选视频的 CC 字幕，转换为原文 .lrc 与翻译 .zh.lrc 并保存。
        若全部视频都没有 CC 字幕，则回退到网易云搜索歌词。"""
        InfoBar.info("获取中", "正在提取 B 站字幕歌词...", duration=3000, parent=self)

        class SubtitleWorker(QThread):
            found = Signal(str, str, str)  # (original_lrc, translation_lrc, source)
            failed = Signal(str)

            def __init__(self, bvids):
                super().__init__()
                self._bvids = bvids

            def run(self):
                client = BilibiliClient()
                last_err = "候选视频均无 CC 字幕，无法提取歌词"
                for bvid in self._bvids:
                    try:
                        info = client.get_video_info(bvid)
                        if not info or not info.episodes:
                            continue
                        cid = info.episodes[0].cid
                        subs = client.get_subtitles(bvid, cid)
                        if not subs:
                            continue

                        # 原文：优先不含“翻译”且为中文的字幕；翻译：含“翻译”或与原文不同语言
                        non_trans = [s for s in subs if '翻译' not in s.get('lan_doc', '')]
                        trans = [s for s in subs if '翻译' in s.get('lan_doc', '')]
                        original = None
                        if non_trans:
                            original = next(
                                (s for s in non_trans if s.get('lan', '').lower().startswith('zh')),
                                non_trans[0],
                            )
                        translation = trans[0] if trans else None
                        if not translation and original:
                            other = [
                                s for s in subs
                                if s.get('lan', '') != original.get('lan', '') and s is not original
                            ]
                            if other:
                                translation = other[0]

                        orig_lrc = client.get_subtitle_lrc(original['subtitle_url']) if original else ""
                        trans_lrc = client.get_subtitle_lrc(translation['subtitle_url']) if translation else ""
                        if orig_lrc or trans_lrc:
                            source = f"B站 - {info.title}"
                            self.found.emit(orig_lrc, trans_lrc, source)
                            return
                    except Exception as e:
                        last_err = str(e)
                self.failed.emit(last_err)

        worker = SubtitleWorker(bvids)
        self._lyrics_subtitle_worker = worker  # 防止被 GC

        def on_found(orig_lrc, trans_lrc, source):
            try:
                default_path = os.path.join(os.path.dirname(audio_path), f"{audio_name}.lrc")
                existing = _find_lrc_for_audio(audio_path) or default_path
                saved = []
                if orig_lrc:
                    with open(existing, 'w', encoding='utf-8') as f:
                        f.write(orig_lrc)
                    self._lyrics_data = _parse_lrc(existing)
                    saved.append(os.path.basename(existing))
                translated = []
                if trans_lrc:
                    trans_path = existing.replace('.lrc', '.zh.lrc').replace('.LRC', '.zh.lrc')
                    with open(trans_path, 'w', encoding='utf-8') as f:
                        f.write(trans_lrc)
                    saved.append(os.path.basename(trans_path))
                    translated = self._load_cached_translation(existing)
                self.lyrics_widget.set_lyrics(self._lyrics_data, translated)
                InfoBar.success("歌词已获取",
                                f"来源: {source} | 已保存 {'、'.join(saved)}",
                                duration=4000, parent=self)
            except Exception as e:
                InfoBar.error("保存歌词失败", str(e), duration=3000, parent=self)

        def on_failed(err):
            InfoBar.warning("B站无可用字幕", err, duration=2500, parent=self)
            self._search_netease_fallback(search_key, artist, audio_path, audio_name)

        worker.found.connect(on_found)
        worker.failed.connect(on_failed)
        worker.start()

    def _search_netease_fallback(self, search_key, artist, audio_path, audio_name):
        """网易云兜底搜索歌词（B 站候选视频均无 CC 字幕时调用）。"""
        InfoBar.info("回退搜索", f"B站无字幕，正在用网易云搜索「{search_key}」...",
                     duration=3000, parent=self)

        class NeteaseLyricsWorker(QThread):
            found = Signal(str, str)  # (lyrics_text, source)
            failed = Signal(str)       # error_message

            def __init__(self, keyword, artist):
                super().__init__()
                self._keyword = keyword
                self._artist = artist

            def run(self):
                try:
                    import httpx
                    client = httpx.Client(timeout=10)
                    search_url = "https://music.163.com/api/search/get/web"
                    resp = client.post(search_url, data={
                        "s": f"{self._keyword} {self._artist}".strip(),
                        "type": "1",
                        "offset": "0",
                        "total": "true",
                        "limit": "5",
                    }, headers={"Referer": "https://music.163.com"})
                    data = resp.json()
                    songs = data.get("result", {}).get("songs", [])
                    if not songs:
                        self.failed.emit("未找到匹配的歌曲")
                        return
                    song_id = songs[0]["id"]
                    lrc_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
                    lrc_resp = client.get(lrc_url, headers={"Referer": "https://music.163.com"})
                    lrc_data = lrc_resp.json()
                    lrc_text = lrc_data.get("lrc", {}).get("lyric", "")
                    if lrc_text:
                        source = (f"网易云 - {songs[0].get('name', '')} "
                                  f"({songs[0].get('artists', [{}])[0].get('name', '')})")
                        self.found.emit(lrc_text, source)
                    else:
                        self.failed.emit("该歌曲暂无歌词")
                    client.close()
                except Exception as e:
                    self.failed.emit(str(e))

        worker = NeteaseLyricsWorker(search_key, artist)
        self._lyrics_netease_worker = worker  # 防止被 GC

        def on_found(lrc_text, source):
            # 弹出编辑器让用户预览并修改，确认后再保存（沿用原网易云交互）
            audio_name_ext = os.path.splitext(os.path.basename(audio_path))[0]
            default_save_path = os.path.join(os.path.dirname(audio_path), f"{audio_name_ext}.lrc")
            existing_lrc = _find_lrc_for_audio(audio_path) or default_save_path
            try:
                dialog = LyricsEditorDialog(
                    audio_name_ext, lrc_text,
                    lrc_path=existing_lrc,
                    source=source,
                    parent=self,
                )
            except Exception as e:
                logger.warning(f"创建歌词编辑器失败，直接保存: {e}")
                try:
                    with open(default_save_path, 'w', encoding='utf-8') as f:
                        f.write(lrc_text)
                    self._lyrics_data = _parse_lrc(default_save_path)
                    self.lyrics_widget.set_lyrics(self._lyrics_data)
                    InfoBar.success("歌词已保存",
                                    f"来源: {source} | 已保存到 {os.path.basename(default_save_path)}",
                                    duration=4000, parent=self)
                except Exception as e2:
                    InfoBar.error("保存歌词失败", str(e2), duration=3000, parent=self)
                return
            try:
                if not dialog.exec():
                    InfoBar.info("已取消", "歌词未保存", duration=2000, parent=self)
                    return
            except Exception as e:
                logger.warning(f"歌词编辑器执行异常: {e}")
                return
            try:
                edited_text = dialog.get_lyrics_text()
            except Exception:
                edited_text = lrc_text
            try:
                save_path = dialog.get_save_path()
            except Exception:
                save_path = None
            if not save_path:
                save_path = default_save_path
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(edited_text)
                self._lyrics_data = _parse_lrc(save_path)
                self.lyrics_widget.set_lyrics(self._lyrics_data)
                InfoBar.success("歌词已保存",
                                f"来源: {source} | 已保存到 {os.path.basename(save_path)}",
                                duration=4000, parent=self)
            except Exception as e:
                InfoBar.error("保存歌词失败", str(e), duration=3000, parent=self)

        def on_failed(err):
            InfoBar.warning("搜索失败", err, duration=3000, parent=self)

        worker.found.connect(on_found)
        worker.failed.connect(on_failed)
        worker.start()

    # ------------------------------------------------------------------
    # 均衡器
    # ------------------------------------------------------------------
    def _show_equalizer(self):
        """弹出均衡器对话框。
        每次 show 时复用已存在的对话框实例；首次创建时连接 gain_changed 信号。"""
        if not hasattr(self, '_eq_dialog') or not self._eq_dialog:
            # 读取持久化的 EQ 增益（若有）—— config 以 JSON 字符串形式存储
            initial = []
            try:
                import json as _json
                _cfg = get_config()
                if hasattr(_cfg, 'eq_gains'):
                    saved_raw = _cfg.get(_cfg.eq_gains)
                    if isinstance(saved_raw, str):
                        parsed = _json.loads(saved_raw)
                        if isinstance(parsed, list) and len(parsed) == 10:
                            initial = [int(x) for x in parsed]
                    elif isinstance(saved_raw, list) and len(saved_raw) == 10:
                        initial = [int(x) for x in saved_raw]
            except Exception:
                initial = []
            if not initial:
                initial = [0] * 10
            self._eq_dialog = EqualizerDialog(self, initial_gains=initial)
            self._eq_dialog.gain_changed.connect(self._on_eq_changed)
        # 每次显示时应用当前增益（确保音量补偿生效）
        try:
            self._on_eq_changed(self._eq_dialog.get_gains())
        except Exception:
            pass
        self._eq_dialog.show()
        self._eq_dialog.raise_()
        self._eq_dialog.activateWindow()

    def _on_eq_changed(self, gains: list):
        """EQ 增益变化时的处理：按最大正增益做整体音量补偿，并持久化偏好。"""
        try:
            # 持久化 EQ 增益（以 JSON 字符串形式存入 config）
            _cfg = get_config()
            if hasattr(_cfg, 'eq_gains'):
                import json as _json
                _cfg.set(_cfg.eq_gains, _json.dumps([int(g) for g in gains]))
                _cfg.save()
        except Exception:
            pass
        # 音量补偿：Qt 后端不支持频段 EQ，但可按最大正增益提升整体音量
        # 让用户能感知到 EQ「增强」效果（不超过 1.5 倍避免爆音）
        try:
            max_gain = max(gains) if gains else 0
            # base_volume 来自用户设置的音量滑块（0~100）
            base = getattr(self, '_last_volume', 100) / 100.0
            # 补偿系数：max_gain 每 +1dB 增加 0.05 倍，上限 1.5
            comp = min(1.5, base * (1.0 + max(0, max_gain) * 0.05))
            comp = max(0.0, comp)
            if hasattr(self, '_audio_output') and self._audio_output:
                self._audio_output.setVolume(comp)
        except Exception as e:
            logger.debug(f"EQ 音量补偿失败: {e}")

    # ------------------------------------------------------------------
    # 歌词延时调节（实时偏移，不修改 LRC 文件）
    # ------------------------------------------------------------------
    def _adjust_lyrics_offset(self, delta_ms: int):
        """调整歌词显示偏移：delta_ms > 0 延后，< 0 提前。
        实时生效，不修改 LRC 文件，偏移值持久化到 config。"""
        self._lyrics_offset_ms += delta_ms
        # 限制范围 ±10 秒
        self._lyrics_offset_ms = max(-10000, min(10000, self._lyrics_offset_ms))
        # 更新 UI 显示
        offset_sec = self._lyrics_offset_ms / 1000.0
        sign = "+" if offset_sec >= 0 else ""
        self.lyrics_offset_label.setText(f"{sign}{offset_sec:.1f}s")
        # 持久化到 config
        try:
            _cfg = get_config()
            _cfg.set(_cfg.lyrics_offset_ms, self._lyrics_offset_ms)
            _cfg.save()
        except Exception:
            pass
        # 立即刷新一次歌词位置（让用户马上看到效果）
        try:
            if self._lyrics_data and hasattr(self, '_player'):
                pos = self._player.position()
                self.lyrics_widget.update_position((pos + self._lyrics_offset_ms) / 1000.0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 定时关闭（睡眠模式）
    # ------------------------------------------------------------------
    def _show_sleep_menu(self):
        menu = QMenu(self)
        for minutes, label in [(15, "15分钟后"), (30, "30分钟后"),
                                (60, "60分钟后"), (90, "90分钟后"),
                                (-1, "播放完当前列表后"),
                                (0, "取消定时")]:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked, m=minutes: self._set_sleep_timer(m))
        menu.exec(self.sleep_btn.mapToGlobal(QPoint(0, self.sleep_btn.height())))

    def _set_sleep_timer(self, minutes: int):
        if minutes == 0:
            if self._sleep_timer:
                self._sleep_timer.stop()
                self._sleep_timer = None
            self._sleep_remaining = 0
            self.sleep_label.setVisible(False)
            InfoBar.success("已取消定时关闭", "", duration=2000, parent=self)
            return

        if self._sleep_timer:
            self._sleep_timer.stop()

        if minutes == -1:
            self._sleep_remaining = -1
            self.sleep_label.setText("将在播放完当前列表后停止")
            self.sleep_label.setVisible(True)
            return

        self._sleep_remaining = minutes * 60
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(1000)
        self._sleep_timer.timeout.connect(self._on_sleep_tick)
        self._sleep_timer.start()
        self.sleep_label.setText(f"定时关闭: {minutes} 分钟后")
        self.sleep_label.setVisible(True)
        InfoBar.success("定时关闭", f"{minutes} 分钟后停止播放",
                        duration=2000, parent=self)

    def _on_sleep_tick(self):
        self._sleep_remaining -= 1
        if self._sleep_remaining <= 0:
            self._player.stop()
            if self._sleep_timer:
                self._sleep_timer.stop()
                self._sleep_timer = None
            self.sleep_label.setVisible(False)
            InfoBar.success("定时关闭", "已停止播放", duration=3000, parent=self)
        else:
            m, s = divmod(self._sleep_remaining, 60)
            self.sleep_label.setText(f"定时关闭: {m:02d}:{s:02d} 后停止")

    # ------------------------------------------------------------------
    # 进度条与时间显示
    # ------------------------------------------------------------------
    def _on_position_changed(self, position: int):
        self.current_time_label.setText(_format_time(position))
        if not self._is_seeking:
            self.progress_slider.setValue(int(position))
        if self._lyrics_data:
            self.lyrics_widget.update_position((position + self._lyrics_offset_ms) / 1000.0)

    def _on_duration_changed(self, duration: int):
        self.progress_slider.setRange(0, int(duration))
        self.total_time_label.setText(_format_time(duration))

    def _on_progress_tick(self):
        if self._is_seeking:
            return
        try:
            position = self._player.position()
            self.progress_slider.setValue(int(position))
            self.current_time_label.setText(_format_time(int(position)))
            if self._lyrics_data:
                self.lyrics_widget.update_position((position + self._lyrics_offset_ms) / 1000.0)
        except Exception as e:
            logger.debug(f"刷新进度失败: {e}")

    def _save_current_position(self):
        """保存当前播放位置到数据库（用于断点续播）"""
        try:
            if 0 <= self._current_index < len(self._playlist):
                path = self._playlist[self._current_index]
                position = self._player.position()
                duration = self._player.duration()
                # 已播放到结尾则清除记录，避免下次从头续播
                if duration > 0 and position >= duration - 2000:
                    from ..database import get_database
                    get_database().clear_position(path)
                elif position > 1000:
                    from ..database import get_database
                    get_database().save_position(path, int(position))
        except Exception as e:
            logger.debug(f"保存播放位置失败: {e}")

    def _on_slider_pressed(self):
        self._is_seeking = True

    def _on_slider_moved(self, value: int):
        self.current_time_label.setText(_format_time(value))

    def _on_slider_released(self):
        value = self.progress_slider.value()
        try:
            self._player.setPosition(value)
        except Exception as e:
            logger.warning(f"跳转进度失败: {e}")
        finally:
            self._is_seeking = False

    # ------------------------------------------------------------------
    # 音量控制
    # ------------------------------------------------------------------
    def _on_volume_changed(self, value: int):
        try:
            self._audio_output.setVolume(value / 100.0)
        except Exception:
            pass
        if value <= 0:
            self.volume_btn.setIcon(FIcon.MUTE)
        else:
            self.volume_btn.setIcon(FIcon.VOLUME)
            self._last_volume = value
        self._save_settings()

    def _toggle_mute(self):
        if self.volume_slider.value() > 0:
            self._last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            restore = self._last_volume if self._last_volume > 0 else 70
            self.volume_slider.setValue(restore)

    def _seek_forward(self):
        """快进 10 秒"""
        cur = self._player.position()
        dur = self._player.duration()
        if dur > 0:
            self._player.setPosition(min(dur, cur + 10000))

    def _seek_backward(self):
        """快退 10 秒"""
        cur = self._player.position()
        self._player.setPosition(max(0, cur - 10000))

    # ------------------------------------------------------------------
    # 播放状态与自动下一首
    # ------------------------------------------------------------------
    def _on_playback_state_changed(self, state):
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        if is_playing:
            self.play_btn.setIcon(FIcon.PAUSE)
            self.play_btn.setToolTip("暂停")
            self._progress_timer.start()
            self._save_position_timer.start()  # 开始定时保存播放位置
            self.cover_label.set_playing(True)
            self.play_state_changed.emit(True)
        else:
            self.play_btn.setIcon(FIcon.PLAY)
            self.play_btn.setToolTip("播放")
            self._progress_timer.stop()
            self._save_position_timer.stop()  # 停止定时保存
            self._save_current_position()     # 立即保存一次
            self.cover_label.set_playing(False)
            self.play_state_changed.emit(False)
        if self._mini_player:
            self._mini_player.update_play_state(is_playing)

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._sleep_remaining == -1 and self._current_index == len(self._playlist) - 1:
                self._player.stop()
                self._sleep_remaining = 0
                self.sleep_label.setVisible(False)
                return
            self._play_next()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            logger.warning("无法解析的媒体文件，尝试播放下一首")
            self._play_next()

    def _on_player_error(self, error, error_string):
        logger.error(f"播放器错误 [{error}]: {error_string}")
        self.track_title_label.setText("播放出错")

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _on_context_menu(self, point: QPoint):
        item = self.playlist_list.itemAt(point)
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return

        menu = QMenu(self)

        action_play = menu.addAction("播放")
        action_play.triggered.connect(lambda: self._play_by_path(path))

        if self._db and self._db.is_favorite(path):
            action_fav = menu.addAction("💔 取消收藏")
            action_fav.triggered.connect(lambda: self._remove_fav_by_path(path))
        else:
            action_fav = menu.addAction("❤ 添加收藏")
            action_fav.triggered.connect(lambda: self._add_fav_by_path(path))

        menu.addSeparator()

        action_tag = menu.addAction("📝 编辑标签")
        action_tag.triggered.connect(lambda: self._edit_tags(path))

        menu.addSeparator()

        action_open = menu.addAction("📁 打开所在文件夹")
        action_open.triggered.connect(lambda: self._open_in_explorer(path))

        action_del = menu.addAction("🗑 删除文件")
        action_del.triggered.connect(lambda: self._delete_file(path))

        menu.exec(self.playlist_list.mapToGlobal(point))

    def _play_by_path(self, path: str):
        try:
            index = self._playlist.index(path)
            self._play_index(index)
        except ValueError:
            pass

    def _add_fav_by_path(self, path: str):
        if not self._db:
            return
        display_name = os.path.basename(path)
        meta = _extract_metadata(path)
        self._db.add_favorite(path, display_name,
                              meta.get('title', ''), meta.get('artist', ''))
        self._populate_list()

    def _remove_fav_by_path(self, path: str):
        if not self._db:
            return
        self._db.remove_favorite(path)
        self._populate_list()

    def _open_in_explorer(self, path: str):
        import subprocess
        subprocess.Popen(["explorer", "/select,", path])

    def _delete_file(self, path: str):
        ret = QMessageBox.question(
            self, "删除文件",
            f"确定要删除文件吗？\n{os.path.basename(path)}\n此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            try:
                os.remove(path)
                if self._db:
                    self._db.remove_favorite(path)
                    self._db.clear_position(path)
                self._scan_audio_files()
                InfoBar.success("已删除文件", "", duration=2000, parent=self)
            except Exception as e:
                InfoBar.error("删除失败", str(e), duration=3000, parent=self)

    # ------------------------------------------------------------------
    # 标签编辑 + 自动归类移动
    # ------------------------------------------------------------------
    def _build_category_target_path(self, src_path: str, artist: str, album: str) -> Optional[str]:
        """
        根据配置的 audio_category_mode 计算分类后的目标路径。

        分类模式（见 config.AudioCategoryMode）：
        - none / artist: <download_path>/<artist>/<文件名>
        - album:         <download_path>/<artist>/<album>/<文件名>
        - type:          <download_path>/<tname>/<artist>/<文件名>
                        （编辑标签时没有视频分区信息，退化为 artist 模式）

        Returns:
            新的完整文件路径。如果目录与原路径相同，或计算失败，返回 None。
        """
        try:
            from ..config import get_config, AudioCategoryMode
            cfg = get_config()
            base_dir = str(cfg.get(cfg.download_path))
            if not base_dir:
                return None
            # 音频文件统一在 musics 子目录下归类
            base_dir = os.path.join(base_dir, "musics")

            mode = cfg.get(cfg.audio_category_mode)
            if hasattr(mode, 'value'):
                mode_val = mode.value
            else:
                mode_val = str(mode) if mode else "artist"

            # 合法字符的清理（与 downloader 一致）
            def _s(name: str, default: str) -> str:
                n = (name or "").strip() or default
                # Windows 不允许的文件名字符
                import re as _re
                n = _re.sub(r'[\/:*?"<>|]', '_', n)
                return n[:80]  # 限制长度避免路径过长

            artist_s = _s(artist, "未知艺术家")
            album_s = _s(album, "未知专辑")
            filename = os.path.basename(src_path)

            if mode_val == "none" or mode_val == "artist" or mode_val == "type":
                target_dir = os.path.join(base_dir, artist_s)
            elif mode_val == "album":
                target_dir = os.path.join(base_dir, artist_s, album_s)
            else:
                target_dir = os.path.join(base_dir, artist_s)

            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)

            # 规范化路径后对比
            if os.path.normcase(os.path.abspath(target_path)) == \
               os.path.normcase(os.path.abspath(src_path)):
                return None
            return target_path
        except Exception as e:
            logger.warning(f"计算分类目标路径失败: {e}")
            return None

    def _move_file_and_sync(self, old_path: str, new_path: str) -> bool:
        """
        移动音频文件，并同步数据库 / 播放列表 / 当前播放状态中的路径引用。

        还会同步移动同名的 .lrc 歌词文件。

        Returns:
            是否成功移动（或本来就在同一路径）
        """
        if not os.path.isfile(old_path):
            return False
        # 规范化路径
        old_abs = os.path.normcase(os.path.abspath(old_path))
        new_abs = os.path.normcase(os.path.abspath(new_path))
        if old_abs == new_abs:
            return True

        # 避免目标路径已存在同名文件
        if os.path.exists(new_path):
            base, ext = os.path.splitext(new_path)
            idx = 1
            while True:
                alt = f"{base}_{idx}{ext}"
                if not os.path.exists(alt):
                    new_path = alt
                    new_abs = os.path.normcase(os.path.abspath(new_path))
                    break
                idx += 1

        try:
            import shutil
            # 1. 移动音频文件
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
            logger.info(f"音频文件已归类移动: {old_path} -> {new_path}")
        except Exception as e:
            logger.error(f"移动文件失败 {old_path} -> {new_path}: {e}")
            InfoBar.error("移动失败", f"无法移动文件：{e}",
                          duration=3000, parent=self)
            return False

        # 2. 移动同名 .lrc 歌词文件
        try:
            old_lrc = os.path.splitext(old_path)[0] + ".lrc"
            if os.path.isfile(old_lrc):
                new_lrc = os.path.splitext(new_path)[0] + ".lrc"
                if os.path.exists(new_lrc):
                    os.remove(new_lrc)
                shutil.move(old_lrc, new_lrc)
        except Exception as e:
            logger.debug(f"移动歌词文件失败 (可忽略): {e}")

        # 2.1 同步元数据缓存：删除旧路径，新路径下次提取时自动缓存
        self._invalidate_meta_cache(old_path)

        # 3. 更新数据库中的所有 file_path 引用
        if self._db:
            self._db.rename_file_path(old_path, new_path)

        # 4. 更新当前播放列表（内存中的 _playlist）
        try:
            for i in range(len(self._playlist)):
                if os.path.normcase(os.path.abspath(self._playlist[i])) == old_abs:
                    self._playlist[i] = new_path
        except Exception:
            pass

        # 5. 如果当前正在播放该文件，需要切换到新路径并恢复播放位置/状态
        was_playing = False
        resume_position_ms = 0
        try:
            if self._current_index >= 0 and self._current_index < len(self._playlist):
                cur_path = self._playlist[self._current_index]
                if os.path.normcase(os.path.abspath(cur_path)) == new_abs:
                    # 就是当前正在播放的
                    state = self._player.playbackState()
                    was_playing = (state == QMediaPlayer.PlayingState)
                    resume_position_ms = self._player.position()
                    self._player.stop()
                    self._player.setSource(QUrl.fromLocalFile(new_path))
                    # 稍后异步恢复位置
                    def _resume():
                        try:
                            self._player.setPosition(resume_position_ms)
                            if was_playing:
                                self._do_play()
                        except Exception:
                            pass
                    QTimer.singleShot(50, _resume)
        except Exception as e:
            logger.debug(f"恢复当前播放状态失败: {e}")

        # 6. 更新收藏夹歌曲标签页中的数据（folder_song_list）
        try:
            for i in range(self.folder_song_list.count()):
                item = self.folder_song_list.item(i)
                if item:
                    data = item.data(Qt.UserRole)
                    if isinstance(data, dict):
                        fp = data.get('file_path', '')
                        if fp and os.path.normcase(os.path.abspath(fp)) == old_abs:
                            data['file_path'] = new_path
                            item.setData(Qt.UserRole, data)
        except Exception:
            pass

        return True

    def _categorize_file(self, path: str) -> Optional[str]:
        """
        对单个音频文件按配置的 audio_category_mode 自动分类（物理移动到对应目录）。

        流程：
        1. 从文件元数据（标签）中提取 artist / album
        2. 用 _build_category_target_path 计算分类后的目标路径
        3. 若与当前路径不同 → 调用 _move_file_and_sync 执行移动 + 同步数据库/播放列表/播放状态
        4. 若无 artist 标签（未知歌手），退化为"未知艺术家"，仍会归类（用户标签页中可见"未知歌手"）

        Returns:
            若发生移动，返回移动后的新路径；否则返回 None。
        """
        if not path or not os.path.isfile(path):
            return None
        # 提取元数据
        meta = _extract_metadata(path)
        artist = (meta.get('artist') or '').strip()
        album = (meta.get('album') or '').strip()
        # 计算目标路径
        target = self._build_category_target_path(path, artist, album)
        if not target:
            return None
        # 执行移动
        if self._move_file_and_sync(path, target):
            return target
        return None

    def _auto_categorize_playlist(self,
                                  notify: bool = False) -> Tuple[int, int, int]:
        """
        对当前播放列表中的所有音频文件执行自动分类。

        适合入口：
        - 扫描完成后（_scan_audio_files 末尾）
        - 豆包下载完成并刷新扫描后
        - 用户在 UI 上点击"整理分类"按钮

        Args:
            notify: 是否在完成后弹出 InfoBar 提示整理结果

        Returns:
            (moved_count, skipped_count, error_count)
        """
        if not self._playlist:
            if notify:
                InfoBar.info("无文件", "播放列表为空，无需整理",
                             duration=2000, parent=self)
            return 0, 0, 0

        moved = 0
        skipped = 0
        errored = 0

        # 注意：_move_file_and_sync 会在原地修改 self._playlist 的元素
        # 所以用 snapshot 遍历一份当前快照，避免索引错乱
        snapshot = list(self._playlist)

        for path in snapshot:
            try:
                new_path = self._categorize_file(path)
                if new_path is None:
                    skipped += 1
                else:
                    moved += 1
            except Exception as e:
                errored += 1
                logger.warning(f"自动分类失败: {path} - {e}")

        if notify:
            if moved > 0:
                InfoBar.success(
                    "自动分类完成",
                    f"已整理 {moved} 个文件"
                    + (f"，跳过 {skipped} 个" if skipped > 0 else "")
                    + (f"，失败 {errored} 个" if errored > 0 else ""),
                    duration=3000, parent=self
                )
            elif errored > 0:
                InfoBar.warning(
                    "自动分类完成",
                    f"无文件被移动，{errored} 个文件处理失败",
                    duration=2500, parent=self
                )
            else:
                InfoBar.info(
                    "自动分类完成",
                    f"全部 {skipped} 个文件已在正确位置",
                    duration=2000, parent=self
                )

        return moved, skipped, errored

    def _edit_tags(self, path: str):
        """编辑音频元数据（标题、歌手、专辑），写入音频文件。

        保存后会：
        1. 如果 artist/album 发生变化，按照配置的 audio_category_mode 把文件移动到对应目录
        2. 同步更新数据库、播放列表、当前播放状态中的路径引用
        """
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(path)
            if audio is None:
                InfoBar.warning("不支持", "无法编辑此文件格式的标签",
                                duration=3000, parent=self)
                return
            from mutagen.id3 import TIT2, TPE1, TALB, ID3NoHeaderError
            from mutagen.mp3 import MP3
            from mutagen.mp4 import MP4

            # M4A/MP4 标签键映射
            M4A_KEY_MAP = {'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb'}

            # ========== 统一的取值方法（区分 MP3 / M4A / 其他格式）==========
            def get_val(key: str) -> str:
                """正确取值：MP3 用 ID3 帧，M4A 用 \xa9 原子，其他格式直接 audio.get(key)"""
                if isinstance(audio, MP3):
                    mapping = {'title': 'TIT2', 'artist': 'TPE1', 'album': 'TALB'}
                    id3_key = mapping.get(key, key)
                    if audio.tags and id3_key in audio.tags:
                        frame = audio.tags[id3_key]
                        if hasattr(frame, 'text') and frame.text:
                            return str(frame.text[0])
                    return ''
                elif isinstance(audio, MP4):
                    atom = M4A_KEY_MAP.get(key, key)
                    v = audio.get(atom, '')
                    if isinstance(v, list):
                        return str(v[0]) if v else ''
                    return str(v) if v else ''
                else:
                    v = audio.get(key, '')
                    if isinstance(v, list):
                        return str(v[0]) if v else ''
                    return str(v) if v else ''

            current_title = get_val('title') or os.path.splitext(os.path.basename(path))[0]
            current_artist = get_val('artist')
            current_album = get_val('album')

            # ========== 构建对话框 ==========
            dialog = QDialog(self)
            dialog.setWindowTitle("编辑歌曲信息")
            dialog.setModal(True)
            dialog.setFixedWidth(380)
            dlg_layout = QVBoxLayout(dialog)
            dlg_layout.setContentsMargins(24, 24, 24, 16)
            dlg_layout.setSpacing(10)

            title_label = SubtitleLabel("📝 编辑歌曲信息", dialog)
            dlg_layout.addWidget(title_label)

            file_hint = CaptionLabel(os.path.basename(path), dialog)
            file_hint.setWordWrap(True)
            dlg_layout.addWidget(file_hint)

            dlg_layout.addSpacing(6)

            dlg_layout.addWidget(BodyLabel("🎵 歌名（标题）", dialog))
            title_edit = LineEdit(dialog)
            title_edit.setText(current_title)
            dlg_layout.addWidget(title_edit)

            dlg_layout.addWidget(BodyLabel("🎤 歌手", dialog))
            artist_edit = LineEdit(dialog)
            artist_edit.setText(current_artist)
            artist_edit.setPlaceholderText("输入歌手名，保存后自动按歌手/专辑归类")
            dlg_layout.addWidget(artist_edit)

            dlg_layout.addWidget(BodyLabel("💿 专辑", dialog))
            album_edit = LineEdit(dialog)
            album_edit.setText(current_album)
            album_edit.setPlaceholderText("输入专辑名（按专辑归类模式下有效）")
            dlg_layout.addWidget(album_edit)

            # 归类模式提示
            try:
                from ..config import get_config, AudioCategoryMode
                cfg = get_config()
                mode = cfg.get(cfg.audio_category_mode)
                mode_val = mode.value if hasattr(mode, 'value') else str(mode)
                mode_hint_map = {
                    'none': '不归类（直接保存到根目录）',
                    'artist': '按歌手名归类（<下载目录>/<歌手>/<歌曲>）',
                    'album': '按歌手+专辑归类（<下载目录>/<歌手>/<专辑>/<歌曲>）',
                    'type': '按视频分区归类（编辑标签时退化为按歌手）',
                }
                hint_text = mode_hint_map.get(mode_val, '按歌手归类')
                hint = CaptionLabel(f"📂 归类模式：{hint_text}", dialog)
                hint.setWordWrap(True)
                dlg_layout.addWidget(hint)
            except Exception:
                pass

            dlg_layout.addSpacing(8)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            cancel_btn = PushButton("取消", dialog)
            save_btn = PrimaryPushButton("💾 保存并归类", dialog)
            btn_layout.addWidget(cancel_btn)
            btn_layout.addWidget(save_btn)
            dlg_layout.addLayout(btn_layout)

            result_holder = {'saved': False}

            def on_save():
                result_holder['saved'] = True
                dialog.accept()

            save_btn.clicked.connect(on_save)
            cancel_btn.clicked.connect(lambda: dialog.reject())

            dialog.exec()

            if not result_holder['saved']:
                return

            new_title = title_edit.text().strip()
            new_artist = artist_edit.text().strip()
            new_album = album_edit.text().strip()

            # ========== 如果正在播放该文件，先暂停并记录位置 ==========
            was_playing = False
            resume_position = 0
            is_current_file = False
            if self._current_index >= 0 and self._current_index < len(self._playlist):
                cur_path = os.path.normcase(os.path.abspath(self._playlist[self._current_index]))
                edit_path = os.path.normcase(os.path.abspath(path))
                if cur_path == edit_path:
                    is_current_file = True
                    state = self._player.playbackState()
                    was_playing = (state == QMediaPlayer.PlayingState)
                    resume_position = self._player.position()
                    self._player.stop()

            # ========== 写入标签 ==========
            changed = False

            def set_tag(key_id3: str, frame_cls, key_simple: str, new_val: str, cur_val: str):
                """统一设置标签，兼容 MP3(ID3) / M4A(MP4原子) / 其他格式"""
                nonlocal changed
                if new_val == cur_val:
                    return
                if new_val:
                    if isinstance(audio, MP3):
                        # MP3：删除旧帧，添加新帧（必要时先初始化 ID3 头）
                        if audio.tags is None:
                            try:
                                audio.add_tags()
                            except Exception:
                                pass
                        if audio.tags and key_id3 in audio.tags:
                            del audio.tags[key_id3]
                        if audio.tags:
                            audio.tags.add(frame_cls(encoding=3, text=new_val))
                    elif isinstance(audio, MP4):
                        # M4A/MP4：使用 \xa9 原子键
                        atom = M4A_KEY_MAP.get(key_simple, key_simple)
                        audio[atom] = new_val
                    else:
                        audio[key_simple] = new_val
                else:
                    # 清空标签
                    if isinstance(audio, MP3):
                        if audio.tags and key_id3 in audio.tags:
                            del audio.tags[key_id3]
                    elif isinstance(audio, MP4):
                        atom = M4A_KEY_MAP.get(key_simple, key_simple)
                        if atom in audio:
                            del audio[atom]
                    elif key_simple in audio:
                        del audio[key_simple]
                changed = True

            set_tag('TIT2', TIT2, 'title', new_title, current_title)
            set_tag('TPE1', TPE1, 'artist', new_artist, current_artist)
            set_tag('TALB', TALB, 'album', new_album, current_album)

            move_result_msg = ""
            moved = False
            new_path = path

            if changed:
                audio.save()
                logger.info(f"标签已写入文件: {path}")
                # 清除该文件元数据缓存，让播放列表/分类显示读到新标签
                self._invalidate_meta_cache(path)

                # ========== 保存成功后按分类模式移动文件 ==========
                # 只有当 artist 或 album 有变化时才可能需要移动
                need_move = (new_artist != current_artist) or (new_album != current_album)
                if need_move:
                    target = self._build_category_target_path(path, new_artist, new_album)
                    if target:
                        moved = self._move_file_and_sync(path, target)
                        if moved:
                            new_path = target
                            rel = os.path.relpath(new_path, os.path.dirname(path)) \
                                if os.path.dirname(path) else os.path.basename(new_path)
                            move_result_msg = f"\n📂 已按配置归类到：{rel}"

            # ========== 刷新 UI ==========
            if changed:
                main_msg = f"歌曲信息已保存{'并归类' if moved else ''}"
                InfoBar.success("已更新", main_msg + move_result_msg,
                                duration=3500, parent=self)
            else:
                InfoBar.info("无变化", "未做任何修改", duration=2000, parent=self)

            # 刷新当前播放信息
            if self._current_index >= 0:
                cur_path_abs = os.path.normcase(os.path.abspath(
                    self._playlist[self._current_index]
                    if self._current_index < len(self._playlist) else ""
                ))
                new_path_abs = os.path.normcase(os.path.abspath(new_path))
                if cur_path_abs and cur_path_abs == new_path_abs:
                    self.track_title_label.setText(new_title or current_title)
                    self.track_artist_label.setText(new_artist or "未知歌手")
                    if self._mini_player:
                        self._mini_player.update_info(
                            new_title or current_title,
                            new_artist or "未知歌手",
                            None
                        )

            # 刷新播放列表、收藏夹、分类展示
            try:
                self._populate_list()
            except Exception:
                pass
            try:
                self._load_artists()
            except Exception:
                pass
            try:
                self._load_albums()
            except Exception:
                pass
            try:
                self._load_folders()
                if self._current_folder_id:
                    self._load_folder_songs()
            except Exception:
                pass

            # ========== 恢复播放（如果修改前正在播放该文件且未被移动） ==========
            if is_current_file and not moved and was_playing:
                # _move_file_and_sync 内部已处理移动时的恢复，此处处理未移动时的情况
                # 注意：_move_file_and_sync 中已注册了 QTimer.singleShot 恢复，这里需要避免重复
                if self._player.playbackState() == QMediaPlayer.StoppedState:
                    try:
                        self._player.setSource(QUrl.fromLocalFile(new_path))
                        self._player.setPosition(resume_position)
                        self._do_play()
                    except Exception:
                        pass

        except ImportError:
            InfoBar.warning("缺少依赖", "需要安装 mutagen 库", duration=3000, parent=self)
        except Exception as e:
            logger.error(f"编辑标签失败: {e}", exc_info=True)
            InfoBar.error("编辑失败", str(e), duration=3000, parent=self)

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------
    def _show_batch_menu(self):
        selected_items = self.playlist_list.selectedItems()
        if not selected_items:
            InfoBar.warning("未选择", "请先选择文件", duration=2000, parent=self)
            return

        menu = QMenu(self)
        paths = [item.data(Qt.UserRole) for item in selected_items if item.data(Qt.UserRole)]

        action_add_fav = menu.addAction(f"批量收藏 ({len(paths)})")
        action_add_fav.triggered.connect(lambda: self._batch_add_fav(paths))

        action_del = menu.addAction(f"批量删除 ({len(paths)})")
        action_del.triggered.connect(lambda: self._batch_delete(paths))

        action_move = menu.addAction(f"批量移动 ({len(paths)})")
        action_move.triggered.connect(lambda: self._batch_move(paths))

        menu.exec(self.batch_btn.mapToGlobal(QPoint(0, self.batch_btn.height())))

    def _batch_add_fav(self, paths: List[str]):
        if not self._db:
            return
        for path in paths:
            display_name = os.path.basename(path)
            meta = _extract_metadata(path)
            self._db.add_favorite(path, display_name,
                                  meta.get('title', ''), meta.get('artist', ''))
        self._populate_list()
        InfoBar.success("批量收藏", f"已收藏 {len(paths)} 个文件",
                        duration=2000, parent=self)

    def _batch_delete(self, paths: List[str]):
        ret = QMessageBox.question(
            self, "批量删除",
            f"确定要删除 {len(paths)} 个文件吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return
        count = 0
        for path in paths:
            try:
                os.remove(path)
                if self._db:
                    self._db.remove_favorite(path)
                    self._db.clear_position(path)
                count += 1
            except Exception:
                pass
        self._scan_audio_files()
        InfoBar.success("批量删除", f"已删除 {count}/{len(paths)} 个文件",
                        duration=2000, parent=self)

    def _batch_move(self, paths: List[str]):
        target_dir = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if not target_dir:
            return
        count = 0
        for path in paths:
            try:
                import shutil
                dest = os.path.join(target_dir, os.path.basename(path))
                if os.path.exists(dest):
                    name, ext = os.path.splitext(os.path.basename(path))
                    dest = os.path.join(target_dir, f"{name}_1{ext}")
                shutil.move(path, dest)
                count += 1
            except Exception as e:
                logger.warning(f"移动文件失败 {path}: {e}")
        self._scan_audio_files()
        InfoBar.success("批量移动", f"已移动 {count}/{len(paths)} 个文件",
                        duration=2000, parent=self)

    # ------------------------------------------------------------------
    # 重复文件检测
    # ------------------------------------------------------------------
    def _detect_duplicates(self):
        if not self._playlist:
            InfoBar.warning("无文件", "没有可检测的音频文件", duration=2000, parent=self)
            return

        InfoBar.info("正在检测", "正在计算文件指纹...", duration=2000, parent=self)

        # 使用 QTimer.singleShot 延迟执行，让 InfoBar 先显示
        QTimer.singleShot(100, self._do_detect_duplicates)

    def _do_detect_duplicates(self):
        """执行重复文件检测（延迟执行，不阻塞 UI）"""
        groups: Dict[str, List[str]] = {}
        for path in self._playlist:
            try:
                with open(path, 'rb') as f:
                    md5 = hashlib.md5(f.read()).hexdigest()
                groups.setdefault(md5, []).append(path)
            except Exception:
                pass

        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        if not duplicates:
            InfoBar.success("无重复", "未检测到重复文件", duration=2000, parent=self)
            return

        total_dup = sum(len(v) - 1 for v in duplicates.values())
        msg = f"检测到 {len(duplicates)} 组重复，共 {total_dup} 个冗余文件。\n"
        for md5, paths in list(duplicates.items())[:5]:
            msg += f"\n  {os.path.basename(paths[0])} ({len(paths)}份)"
        if len(duplicates) > 5:
            msg += f"\n...还有 {len(duplicates) - 5} 组"

        ret = QMessageBox.question(
            self, "重复文件检测", msg + "\n\n是否删除冗余文件（每组保留一个）？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        # 删除冗余文件：每组保留第一个，删除其余
        deleted_count = 0
        failed_paths = []
        for paths in duplicates.values():
            keep = paths[0]
            for dup_path in paths[1:]:
                try:
                    # 如果正在播放被删除的文件，先停止
                    if self._current_index >= 0 and self._current_index < len(self._playlist):
                        cur = os.path.normcase(os.path.abspath(self._playlist[self._current_index]))
                        dup = os.path.normcase(os.path.abspath(dup_path))
                        if cur == dup:
                            self._player.stop()
                            self._current_index = -1
                    os.remove(dup_path)
                    if self._db:
                        self._db.remove_favorite(dup_path)
                        self._db.clear_position(dup_path)
                    deleted_count += 1
                except Exception as e:
                    failed_paths.append(os.path.basename(dup_path))
                    logger.warning(f"删除重复文件失败 {dup_path}: {e}")

        # 重新扫描
        self._scan_audio_files()

        if failed_paths:
            InfoBar.warning("部分删除失败",
                           f"已删除 {deleted_count} 个冗余文件，{len(failed_paths)} 个失败",
                           duration=3000, parent=self)
        else:
            InfoBar.success("清理完成",
                           f"已删除 {deleted_count} 个冗余文件",
                           duration=2000, parent=self)

    # ------------------------------------------------------------------
    # 播放列表导入/导出
    # ------------------------------------------------------------------
    def _export_playlist(self):
        if not self._playlist:
            InfoBar.warning("无文件", "播放列表为空", duration=2000, parent=self)
            return
        path, ftype = QFileDialog.getSaveFileName(
            self, "导出播放列表", "playlist",
            "M3U 播放列表 (*.m3u);;PLS 播放列表 (*.pls);;所有文件 (*)"
        )
        if not path:
            return
        try:
            if path.endswith('.m3u'):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("#EXTM3U\n")
                    for audio_path in self._playlist:
                        meta = _extract_metadata(audio_path)
                        title = meta.get('title') or os.path.basename(audio_path)
                        artist = meta.get('artist', '')
                        duration = 0
                        f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                        f.write(audio_path + "\n")
            elif path.endswith('.pls'):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("[playlist]\n")
                    for i, audio_path in enumerate(self._playlist, 1):
                        f.write(f"File{i}={audio_path}\n")
                    f.write(f"NumberOfEntries={len(self._playlist)}\n")
                    f.write("Version=2\n")
            InfoBar.success("导出成功", f"已导出到 {path}", duration=2000, parent=self)
        except Exception as e:
            InfoBar.error("导出失败", str(e), duration=3000, parent=self)

    def _import_playlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入播放列表", "",
            "M3U 播放列表 (*.m3u);;PLS 播放列表 (*.pls);;所有文件 (*)"
        )
        if not path:
            return
        try:
            imported: List[str] = []
            if path.endswith('.m3u'):
                with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and os.path.isfile(line):
                            imported.append(line)
            elif path.endswith('.pls'):
                with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('File') and '=' in line:
                            file_path = line.split('=', 1)[1]
                            if os.path.isfile(file_path):
                                imported.append(file_path)

            if imported:
                self._playlist = imported
                self._populate_list()
                self._update_empty_hint()
                InfoBar.success("导入成功", f"已导入 {len(imported)} 个文件",
                                duration=2000, parent=self)
            else:
                InfoBar.warning("导入为空", "未找到有效的音频文件路径",
                                duration=3000, parent=self)
        except Exception as e:
            InfoBar.error("导入失败", str(e), duration=3000, parent=self)

    # ------------------------------------------------------------------
    # 同步到 transfer 目录
    # ------------------------------------------------------------------
    def _sync_to_transfer(self):
        """将播放列表中所有音频和歌词同步到 transfer 目录"""
        if not self._playlist:
            InfoBar.warning("无文件", "播放列表为空，无法同步", duration=2000, parent=self)
            return

        # 使用项目根目录下的 transfer 文件夹
        from pathlib import Path as _P
        transfer_path = str(_P.cwd() / "transfer")
        os.makedirs(transfer_path, exist_ok=True)

        # 禁用按钮，防止重复点击
        self.sync_lib_btn.setEnabled(False)
        self._sync_worker = _SyncToTransferWorker(
            list(self._playlist), transfer_path, parent=self
        )
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.start()

    def _on_sync_finished(self, copied: int, skipped: int, errors: int):
        """同步完成回调"""
        self.sync_lib_btn.setEnabled(True)
        parts = []
        if copied > 0:
            parts.append(f"复制 {copied} 个")
        if skipped > 0:
            parts.append(f"跳过 {skipped} 个")
        if errors > 0:
            parts.append(f"失败 {errors} 个")
        msg = "，".join(parts) if parts else "无需同步"
        if errors > 0:
            InfoBar.warning("同步完成", msg, duration=4000, parent=self)
        else:
            InfoBar.success("同步完成", msg, duration=3000, parent=self)

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------
    def stop(self):
        """停止播放并保存状态"""
        try:
            self._progress_timer.stop()
            if self._current_index >= 0 and self._db:
                pos = self._player.position()
                if pos > 1000:
                    self._db.save_position(self._playlist[self._current_index], pos)
            self._save_settings()
            self._player.stop()
            self._player.setSource(QUrl())
            # 停止全局热键线程
            if hasattr(self, '_hotkey_stop_flag') and self._hotkey_stop_flag:
                self._hotkey_stop_flag['stop'] = True
            if self._global_hotkeys:
                try:
                    self._global_hotkeys.stop()
                except Exception:
                    pass
            if self._mini_player:
                try:
                    self._mini_player.close()
                except Exception:
                    pass
            if self._desktop_lyrics:
                try:
                    self._desktop_lyrics.close()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"停止播放器失败: {e}")

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def _apply_progress_slider_style(self):
        """根据当前主题应用进度条样式"""
        if isDarkTheme():
            slider_ss = """  # BG-11: 进度条背景色（深色方案）
                QSlider::groove:horizontal {
                    height: 6px;
                    background: #3C3C3C;
                    border-radius: 3px;
                }
                QSlider::sub-page:horizontal {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #8899EE, stop:1 #9977CC);
                    border-radius: 3px;
                }
                QSlider::handle:horizontal {
                    width: 14px;
                    height: 14px;
                    margin: -5px 0;
                    border-radius: 7px;
                    background: #CCCCCC;
                    border: 2px solid #8899EE;
                }
                QSlider::handle:horizontal:hover {
                    border: 2px solid #9977CC;
                    background: #DDDDEE;
                }
            """
        else:
            slider_ss = """  # BG-12: 进度条背景色（浅色方案）
                QSlider::groove:horizontal {
                    height: 6px;
                    background: #E0E0E0;
                    border-radius: 3px;
                }
                QSlider::sub-page:horizontal {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #667EEA, stop:1 #764BA2);
                    border-radius: 3px;
                }
                QSlider::handle:horizontal {
                    width: 14px;
                    height: 14px;
                    margin: -5px 0;
                    border-radius: 7px;
                    background: white;
                    border: 2px solid #667EEA;
                }
                QSlider::handle:horizontal:hover {
                    border: 2px solid #764BA2;
                    background: #F0F0FF;
                }
            """
        self.progress_slider.setStyleSheet(slider_ss)

    def _on_theme_changed(self):
        """主题切换时刷新样式"""
        # 标签颜色由 monkey-patch 自动处理，无需手动更新
        # 刷新进度条样式
        try:
            self._apply_progress_slider_style()
        except Exception:
            pass
        # 刷新歌词组件样式
        try:
            if hasattr(self, 'lyrics_widget'):
                self.lyrics_widget.refresh_theme()
        except Exception:
            pass
        # 刷新所有列表组件的文字颜色
        self._apply_list_text_color()
        # 刷新播放列表（更新封面背景色等）
        try:
            self._populate_list()
        except Exception:
            pass
        # 刷新分类列表
        try:
            self._load_artists()
        except Exception:
            pass
        try:
            self._load_albums()
        except Exception:
            pass
        try:
            self._load_folders()
            if self._current_folder_id:
                self._load_folder_songs()
        except Exception:
            pass

    def _apply_list_text_color(self):
        """根据当前主题设置所有列表的文字颜色"""
        if isDarkTheme():
            list_ss = "QListWidget { color: #FFFFFF; } QListWidget::item:selected { color: #4DB8FF; }"  # COLOR-12: 列表文字颜色（深色#FFFFFF / 选中#4DB8FF）
        else:
            list_ss = "QListWidget { color: #000000; } QListWidget::item:selected { color: #0094FF; }"  # COLOR-13: 列表文字颜色（浅色#000000 / 选中#0094FF）
        for attr in ('playlist_list', 'folder_list', 'folder_song_list',
                     'artist_list', 'artist_song_list', 'album_list', 'album_song_list'):
            if hasattr(self, attr):
                try:
                    getattr(self, attr).setStyleSheet(list_ss)
                except Exception:
                    pass
