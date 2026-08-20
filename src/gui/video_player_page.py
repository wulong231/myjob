"""视频播放器页面
==================
功能：视频播放、暂停、进度控制、音量调节、全屏播放、播放列表管理。
下载的视频存储在 downloads/videos/ 目录下。
"""
import os
import logging
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QIcon, QPixmap, QImage, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QSlider, QLabel, QSizePolicy, QMenu, QFileDialog, QMessageBox,
    QSpacerItem, QApplication, QTabWidget, QDialog, QFrame, QInputDialog,
    QSplitter,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from qfluentwidgets import (
    SimpleCardWidget, BodyLabel, CaptionLabel, StrongBodyLabel,
    PushButton, PrimaryPushButton, ToolButton,
    FluentIcon as FIcon, isDarkTheme, InfoBar,
    ComboBox, LineEdit, ScrollArea, FlowLayout, PillPushButton,
)

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v')

COVER_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


class _VideoCoverLoader(QThread):
    """异步加载视频封面缩略图线程（优先加载同目录封面图，否则尝试 ffmpeg 提取）"""
    loaded = Signal(str, QPixmap)  # (path, pixmap)

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self._video_path = video_path

    def run(self):
        try:
            pix = self._load_cover()
            if pix and not pix.isNull():
                self.loaded.emit(self._video_path, pix)
        except Exception as e:
            logger.debug(f"加载视频封面异常 {self._video_path}: {e}")

    def _load_cover(self) -> Optional[QPixmap]:
        base = os.path.splitext(self._video_path)[0]
        # 1. 尝试同目录下同名的封面图
        for ext in COVER_EXTENSIONS:
            cover_path = base + ext
            if os.path.isfile(cover_path):
                img = QImage(cover_path)
                if not img.isNull():
                    return QPixmap.fromImage(img)
        # 2. 尝试 _cover.jpg 后缀
        for ext in COVER_EXTENSIONS:
            cover_path = base + "_cover" + ext
            if os.path.isfile(cover_path):
                img = QImage(cover_path)
                if not img.isNull():
                    return QPixmap.fromImage(img)
        # 3. 尝试 ffmpeg 提取第一帧（如果 ffmpeg 可用）
        try:
            import tempfile
            import subprocess
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            cmd = [
                "ffmpeg", "-y", "-i", self._video_path,
                "-ss", "00:00:01", "-vframes", "1",
                "-q:v", "2", "-s", "200x120", tmp_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            if result.returncode == 0 and os.path.exists(tmp_path):
                img = QImage(tmp_path)
                os.remove(tmp_path)
                if not img.isNull():
                    return QPixmap.fromImage(img)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return None


def _format_time(ms: int) -> str:
    """毫秒转 mm:ss 格式"""
    s = max(0, ms // 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# 标签分类显示图标
TAG_CATEGORY_ICONS = {
    "系列": "📁",
    "属性": "🎯",
    "风格": "🎨",
    "自定义": "📌",
}

# 标签分类配色（badge 背景色）
TAG_CATEGORY_COLORS = {
    "系列": "#9C27B0",
    "属性": "#2196F3",
    "风格": "#FF9800",
    "自定义": "#607D8B",
}


def _tag_badge_style(category: str) -> str:
    """根据分类生成 badge 的 QSS 样式"""
    color = TAG_CATEGORY_COLORS.get(category, "#607D8B")
    return (
        f"background: {color}; color: white; "
        "border-radius: 8px; padding: 1px 6px; font-size: 11px;"
    )


class VideoTagEditDialog(QDialog):
    """视频标签编辑对话框

    提供分类选择、当前标签列表（可删除）、输入新标签并选择分类后添加、
    预设标签快捷添加以及保存功能。
    """

    def __init__(self, file_path: str, current_tags: list, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        # current_tags: [{'tag': str, 'category': str}, ...]，做一份工作副本
        self._tags = [{"tag": t["tag"],
                       "category": t.get("category", "自定义")}
                      for t in current_tags]
        self.setWindowTitle("编辑视频标签")
        self.resize(480, 600)
        self._setup_ui()
        self._refresh_current_tags()
        self._refresh_presets()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题与文件名
        layout.addWidget(StrongBodyLabel("编辑视频标签"))
        filename = os.path.splitext(os.path.basename(self._file_path))[0]
        file_hint = CaptionLabel(f"📁 {filename[:50]}")
        file_hint.setWordWrap(True)
        layout.addWidget(file_hint)

        # ---------- 当前标签区 ----------
        layout.addWidget(BodyLabel("当前标签（点击右侧 ✕ 移除）："))
        self.tags_scroll = ScrollArea()
        self.tags_scroll.setWidgetResizable(True)
        self.tags_scroll.setMinimumHeight(90)
        self.tags_scroll.setMaximumHeight(160)
        self.tags_container = QWidget()
        self.tags_flow = FlowLayout(self.tags_container)
        self.tags_flow.setSpacing(6)
        self.tags_scroll.setWidget(self.tags_container)
        layout.addWidget(self.tags_scroll)

        self.empty_tag_hint = CaptionLabel("暂无标签，请在下方添加")
        self.empty_tag_hint.setAlignment(Qt.AlignCenter)
        empty_color = "#999" if isDarkTheme() else "gray"
        self.empty_tag_hint.setStyleSheet(f"color: {empty_color}; padding: 4px;")
        layout.addWidget(self.empty_tag_hint)

        # ---------- 添加新标签区 ----------
        from ..database import VIDEO_TAG_CATEGORIES
        add_card = SimpleCardWidget(self)
        add_layout = QVBoxLayout(add_card)
        add_layout.setContentsMargins(12, 12, 12, 12)
        add_layout.setSpacing(8)

        add_layout.addWidget(BodyLabel("添加新标签："))
        row = QHBoxLayout()
        row.addWidget(CaptionLabel("分类:"))
        self.category_combo = ComboBox(self)
        for cat in VIDEO_TAG_CATEGORIES:
            icon = TAG_CATEGORY_ICONS.get(cat, "📌")
            self.category_combo.addItem(f"{icon} {cat}", userData=cat)
        self.category_combo.currentIndexChanged.connect(self._refresh_presets)
        row.addWidget(self.category_combo, 1)

        row.addWidget(CaptionLabel("标签:"))
        self.tag_input = LineEdit(self)
        self.tag_input.setPlaceholderText("输入标签名后回车或点击添加")
        self.tag_input.setClearButtonEnabled(True)
        self.tag_input.returnPressed.connect(self._add_input_tag)
        row.addWidget(self.tag_input, 2)

        self.add_btn = PrimaryPushButton("添加", self)
        self.add_btn.clicked.connect(self._add_input_tag)
        row.addWidget(self.add_btn)
        add_layout.addLayout(row)
        layout.addWidget(add_card)

        # ---------- 预设标签区 ----------
        layout.addWidget(BodyLabel("预设标签（点击快捷添加）："))
        self.preset_scroll = ScrollArea()
        self.preset_scroll.setWidgetResizable(True)
        self.preset_scroll.setMinimumHeight(70)
        self.preset_scroll.setMaximumHeight(120)
        self.preset_container = QWidget()
        self.preset_flow = FlowLayout(self.preset_container)
        self.preset_flow.setSpacing(6)
        self.preset_scroll.setWidget(self.preset_container)
        layout.addWidget(self.preset_scroll)

        layout.addStretch()

        # ---------- 底部按钮 ----------
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = PrimaryPushButton("💾 保存", self)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _refresh_current_tags(self):
        """刷新当前标签列表"""
        # 清空旧 widget（FlowLayout.takeAt 直接返回 widget，兼容两种实现）
        while self.tags_flow.count():
            item = self.tags_flow.takeAt(0)
            w = item.widget() if hasattr(item, "widget") else item
            if w is not None:
                w.deleteLater()

        self.empty_tag_hint.setVisible(not self._tags)
        self.tags_scroll.setVisible(bool(self._tags))

        for t in self._tags:
            badge = self._make_tag_badge(t["tag"], t["category"], removable=True)
            # 用 lambda 默认参数捕获当前 tag，避免闭包延迟问题
            badge.clicked.connect(
                lambda _=False, tag=t["tag"]: self._remove_tag(tag)
            )
            self.tags_flow.addWidget(badge)

    def _refresh_presets(self):
        """根据当前选中的分类刷新预设标签"""
        while self.preset_flow.count():
            item = self.preset_flow.takeAt(0)
            w = item.widget() if hasattr(item, "widget") else item
            if w is not None:
                w.deleteLater()

        category = self.category_combo.currentData() or "自定义"
        from ..database import VIDEO_TAG_PRESETS
        presets = VIDEO_TAG_PRESETS.get(category, [])
        # 自定义分类无预设时给出提示
        if not presets:
            hint = CaptionLabel("该分类无预设标签，请直接输入")
            hint.setAlignment(Qt.AlignCenter)
            empty_color = "#999" if isDarkTheme() else "gray"
            hint.setStyleSheet(f"color: {empty_color}; padding: 4px;")
            self.preset_flow.addWidget(hint)
            return

        existing = {t["tag"] for t in self._tags}
        for name in presets:
            badge = self._make_tag_badge(name, category, removable=False)
            if name in existing:
                badge.setEnabled(False)
                badge.setToolTip("已添加")
            else:
                badge.setToolTip("点击添加")
                badge.clicked.connect(
                    lambda _=False, n=name, c=category: self._add_tag(n, c)
                )
            self.preset_flow.addWidget(badge)

    def _make_tag_badge(self, name: str, category: str,
                        removable: bool = True) -> PillPushButton:
        """创建一个标签 badge 按钮"""
        color = TAG_CATEGORY_COLORS.get(category, "#607D8B")
        if removable:
            text = f"{name}  ✕"
        else:
            text = f"{name}"
        badge = PillPushButton(text, self)
        badge.setCheckable(False)
        # 不同分类用不同背景色，便于区分
        badge.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; "
            "border: none; padding: 4px 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {color}; opacity: 0.85; }}"
        )
        badge.setToolTip(f"[{category}] {name}")
        return badge

    def _add_input_tag(self):
        """从输入框添加标签"""
        text = self.tag_input.text().strip()
        if not text:
            return
        # 支持逗号分隔批量输入
        names = [t.strip() for t in text.replace("，", ",").split(",") if t.strip()]
        category = self.category_combo.currentData() or "自定义"
        for name in names:
            self._add_tag(name, category)
        self.tag_input.clear()
        self.tag_input.setFocus()

    def _add_tag(self, name: str, category: str):
        """添加一个标签到当前列表（去重）"""
        name = name.strip()
        if not name:
            return
        for t in self._tags:
            if t["tag"] == name:
                # 已存在则更新分类
                t["category"] = category
                self._refresh_current_tags()
                self._refresh_presets()
                return
        self._tags.append({"tag": name, "category": category})
        self._refresh_current_tags()
        self._refresh_presets()

    def _remove_tag(self, name: str):
        """移除一个标签"""
        self._tags = [t for t in self._tags if t["tag"] != name]
        self._refresh_current_tags()
        self._refresh_presets()

    def get_tags(self) -> list:
        """返回编辑后的标签列表 [{'tag', 'category'}, ...]"""
        return self._tags


class VideoPlayerPage(QWidget):
    """视频播放器页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playlist: List[str] = []
        self._current_index: int = -1
        self._is_seeking: bool = False

        # 分类映射：{UP主名: [paths]}、{类型: [paths]}
        self._uploader_map: dict = {}
        self._type_map: dict = {}

        # 封面缓存
        self._cover_cache: dict = {}
        self._cover_loaders: list = []

        # 媒体播放器
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        # 进度刷新定时器
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._on_progress_tick)

        # 断点续播：定期保存进度定时器（5秒保存一次，避免频繁写库）
        self._save_position_timer = QTimer(self)
        self._save_position_timer.setInterval(5000)
        self._save_position_timer.timeout.connect(self._save_current_position)

        self._setup_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self._scan_video_files()

    def _setup_ui(self):
        """构建UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # 标题栏
        title_row = QHBoxLayout()
        title_row.addWidget(StrongBodyLabel("视频播放器"))
        title_row.addStretch()

        # 全屏按钮
        self.fullscreen_btn = ToolButton(FIcon.FULL_SCREEN, self)
        self.fullscreen_btn.setToolTip("全屏播放 (F)")
        title_row.addWidget(self.fullscreen_btn)

        # 打开文件按钮
        self.open_btn = ToolButton(FIcon.FOLDER, self)
        self.open_btn.setToolTip("打开视频文件")
        title_row.addWidget(self.open_btn)

        main_layout.addLayout(title_row)

        # 主内容区：水平 QSplitter，左侧播放列表 + 右侧视频窗口（可拖动调整宽度）
        h_splitter = QSplitter(Qt.Horizontal, self)
        h_splitter.setChildrenCollapsible(False)
        h_splitter.setHandleWidth(6)

        # 左侧：标签页（播放列表 / 按UP主 / 按类型）
        list_card = SimpleCardWidget(self)
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(4)

        # 顶部操作栏
        list_header = QHBoxLayout()
        list_header.addWidget(CaptionLabel("视频库"))
        list_header.addStretch()

        self.rescan_btn = ToolButton(FIcon.SYNC, self)
        self.rescan_btn.setToolTip("刷新视频列表")
        self.rescan_btn.setFixedSize(28, 28)
        list_header.addWidget(self.rescan_btn)

        list_layout.addLayout(list_header)

        # 标签页
        self.left_tabs = QTabWidget(self)
        self.left_tabs.setDocumentMode(True)

        # 标签1：播放列表
        list_tab = QWidget()
        list_tab_layout = QVBoxLayout(list_tab)
        list_tab_layout.setContentsMargins(0, 0, 0, 0)

        self.video_list = QListWidget(self)
        self.video_list.setAlternatingRowColors(True)
        self.video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        list_tab_layout.addWidget(self.video_list)

        self.left_tabs.addTab(list_tab, "列表")

        # 标签2：按UP主
        uploader_tab = QWidget()
        uploader_tab_layout = QVBoxLayout(uploader_tab)
        uploader_tab_layout.setContentsMargins(0, 0, 0, 0)

        self.uploader_list = QListWidget(self)
        self.uploader_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.uploader_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        uploader_tab_layout.addWidget(self.uploader_list)

        self.uploader_detail = QWidget()
        self.uploader_detail_layout = QVBoxLayout(self.uploader_detail)
        self.uploader_detail_layout.setContentsMargins(0, 0, 0, 0)

        self.uploader_title = CaptionLabel("")
        self.uploader_detail_layout.addWidget(self.uploader_title)

        self.uploader_video_list = QListWidget(self)
        self.uploader_video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.uploader_video_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        self.uploader_detail_layout.addWidget(self.uploader_video_list)

        self.uploader_detail.setVisible(False)

        # 使用一个容器来切换UP主列表和详情
        self.uploader_container = QWidget()
        self.uploader_container_layout = QVBoxLayout(self.uploader_container)
        self.uploader_container_layout.setContentsMargins(0, 0, 0, 0)
        self.uploader_container_layout.addWidget(self.uploader_list)
        self.uploader_container_layout.addWidget(self.uploader_detail)

        self.left_tabs.addTab(self.uploader_container, "UP主")

        # 标签3：按类型
        type_tab = QWidget()
        type_tab_layout = QVBoxLayout(type_tab)
        type_tab_layout.setContentsMargins(0, 0, 0, 0)

        self.type_list = QListWidget(self)
        self.type_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        type_tab_layout.addWidget(self.type_list)

        self.type_detail = QWidget()
        self.type_detail_layout = QVBoxLayout(self.type_detail)
        self.type_detail_layout.setContentsMargins(0, 0, 0, 0)

        self.type_title = CaptionLabel("")
        self.type_detail_layout.addWidget(self.type_title)

        self.type_video_list = QListWidget(self)
        self.type_video_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        self.type_detail_layout.addWidget(self.type_video_list)

        self.type_detail.setVisible(False)

        self.type_container = QWidget()
        self.type_container_layout = QVBoxLayout(self.type_container)
        self.type_container_layout.setContentsMargins(0, 0, 0, 0)
        self.type_container_layout.addWidget(self.type_list)
        self.type_container_layout.addWidget(self.type_detail)

        self.left_tabs.addTab(self.type_container, "类型")

        # 标签4：按标签
        tag_tab = QWidget()
        tag_tab_layout = QVBoxLayout(tag_tab)
        tag_tab_layout.setContentsMargins(0, 0, 0, 0)

        self.tag_list = QListWidget(self)
        self.tag_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        tag_tab_layout.addWidget(self.tag_list)

        self.tag_detail = QWidget()
        self.tag_detail_layout = QVBoxLayout(self.tag_detail)
        self.tag_detail_layout.setContentsMargins(0, 0, 0, 0)

        # 返回按钮
        tag_back_btn = ToolButton(FIcon.LEFT_ARROW, self)
        tag_back_btn.setFixedSize(32, 32)
        tag_back_btn.clicked.connect(self._on_tag_back)
        back_layout = QHBoxLayout()
        back_layout.addWidget(tag_back_btn)
        self.tag_title = CaptionLabel("")
        back_layout.addWidget(self.tag_title, 1)
        self.tag_detail_layout.addLayout(back_layout)

        self.tag_video_list = QListWidget(self)
        self.tag_video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_video_list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        self.tag_detail_layout.addWidget(self.tag_video_list)

        self.tag_detail.setVisible(False)

        self.tag_container = QWidget()
        self.tag_container_layout = QVBoxLayout(self.tag_container)
        self.tag_container_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_container_layout.addWidget(self.tag_list)
        self.tag_container_layout.addWidget(self.tag_detail)

        self.left_tabs.addTab(self.tag_container, "标签")

        list_layout.addWidget(self.left_tabs)

        # 左侧列表最小宽度，避免拖动时被压缩到不可见
        list_card.setMinimumWidth(160)
        h_splitter.addWidget(list_card)

        # 右侧：垂直 QSplitter，视频窗口 + 控制栏（可拖动调整高度）
        v_splitter = QSplitter(Qt.Vertical, self)
        v_splitter.setChildrenCollapsible(False)
        v_splitter.setHandleWidth(6)

        # 视频显示窗口
        video_card = SimpleCardWidget(self)
        video_card_layout = QVBoxLayout(video_card)
        video_card_layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setMinimumSize(480, 270)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._player.setVideoOutput(self.video_widget)
        video_card_layout.addWidget(self.video_widget)

        # 全屏独立窗口（QVideoWidget 嵌在 FluentWindow 中无法直接 enterFullScreen）
        self._fullscreen_window: Optional[QWidget] = None
        self._fullscreen_video_widget: Optional[QVideoWidget] = None

        v_splitter.addWidget(video_card)

        # 控制栏
        controls_card = SimpleCardWidget(self)
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(12, 12, 12, 12)
        controls_layout.setSpacing(8)

        # 进度条
        progress_row = QHBoxLayout()
        self.current_time_label = CaptionLabel("00:00")
        progress_row.addWidget(self.current_time_label)

        self.progress_slider = QSlider(Qt.Horizontal, self)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setEnabled(False)
        progress_row.addWidget(self.progress_slider, 1)

        self.total_time_label = CaptionLabel("00:00")
        progress_row.addWidget(self.total_time_label)

        controls_layout.addLayout(progress_row)

        # 播放控制按钮
        btn_row = QHBoxLayout()

        self.prev_btn = ToolButton(FIcon.LEFT_ARROW, self)
        self.prev_btn.setToolTip("上一个 (Ctrl+Left)")
        btn_row.addWidget(self.prev_btn)

        self.play_btn = ToolButton(FIcon.PLAY, self)
        self.play_btn.setToolTip("播放/暂停 (Space)")
        self.play_btn.setFixedSize(40, 40)
        btn_row.addWidget(self.play_btn)

        self.next_btn = ToolButton(FIcon.RIGHT_ARROW, self)
        self.next_btn.setToolTip("下一个 (Ctrl+Right)")
        btn_row.addWidget(self.next_btn)

        btn_row.addSpacing(20)

        # 音量控制
        self.volume_btn = ToolButton(FIcon.VOLUME, self)
        self.volume_btn.setToolTip("静音/取消静音")
        btn_row.addWidget(self.volume_btn)

        self.volume_slider = QSlider(Qt.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        btn_row.addWidget(self.volume_slider)

        btn_row.addStretch()

        # 倍速播放
        self.speed_label = CaptionLabel("1.0x")
        btn_row.addWidget(self.speed_label)

        self.speed_btn = ToolButton(FIcon.SPEED_HIGH, self)
        self.speed_btn.setToolTip("切换播放速度")
        btn_row.addWidget(self.speed_btn)

        controls_layout.addLayout(btn_row)

        # 控制栏最小高度，避免拖动时被压缩到不可见
        controls_card.setMinimumHeight(100)
        v_splitter.addWidget(controls_card)

        # 设置垂直分割比例：视频窗口占大部分，控制栏占小部分
        v_splitter.setSizes([500, 130])

        h_splitter.addWidget(v_splitter)
        # 设置水平分割比例：左侧列表 220，右侧视频区占剩余
        h_splitter.setSizes([220, 760])
        main_layout.addWidget(h_splitter, 1)

        # 空状态提示
        self.empty_hint = CaptionLabel("📭 暂无视频文件\n下载的视频将自动保存在 downloads/videos/ 目录")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        empty_hint_color = "#999" if isDarkTheme() else "gray"
        self.empty_hint.setStyleSheet(f"color: {empty_hint_color}; padding: 20px;")
        self.empty_hint.setVisible(False)
        main_layout.addWidget(self.empty_hint)

    def _connect_signals(self):
        """连接信号"""
        self.play_btn.clicked.connect(self._toggle_play)
        self.prev_btn.clicked.connect(self._play_prev)
        self.next_btn.clicked.connect(self._play_next)
        self.volume_btn.clicked.connect(self._toggle_mute)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        self.open_btn.clicked.connect(self._open_file)
        self.rescan_btn.clicked.connect(self._scan_video_files)
        self.speed_btn.clicked.connect(self._cycle_speed)

        self.video_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.video_list.customContextMenuRequested.connect(self._on_context_menu)

        # UP主分类信号
        self.uploader_list.itemClicked.connect(self._on_uploader_clicked)
        self.uploader_video_list.itemDoubleClicked.connect(self._play_uploader_video)

        # 类型分类信号
        self.type_list.itemClicked.connect(self._on_type_clicked)
        self.type_video_list.itemDoubleClicked.connect(self._play_type_video)

        # 标签分类信号
        self.tag_list.itemClicked.connect(self._on_tag_clicked)
        self.tag_video_list.itemDoubleClicked.connect(self._play_tag_video)

        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderMoved.connect(self._on_slider_moved)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)

    def _setup_shortcuts(self):
        """设置快捷键"""
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=self._play_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self._play_next)
        QShortcut(QKeySequence(Qt.Key_F), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._exit_fullscreen)
        # 音量控制
        QShortcut(QKeySequence(Qt.Key_Up), self, activated=self._volume_up)
        QShortcut(QKeySequence(Qt.Key_Down), self, activated=self._volume_down)
        QShortcut(QKeySequence(Qt.Key_M), self, activated=self._toggle_mute_key)
        # 快进/快退 10 秒
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self._seek_backward)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self._seek_forward)
        # 数字键跳转百分比
        for i in range(10):
            key = getattr(Qt, f"Key_{i}")
            QShortcut(QKeySequence(key), self, activated=lambda i=i: self._seek_percent(i * 10))

    def _get_video_path(self) -> str:
        """获取视频存储目录"""
        from ..config import get_config
        cfg = get_config()
        base_download = cfg.get(cfg.download_path) or os.path.join(os.getcwd(), "downloads")
        video_path = os.path.join(base_download, "videos")
        os.makedirs(video_path, exist_ok=True)
        return video_path

    def _scan_video_files(self):
        """扫描视频文件"""
        self.video_list.clear()
        self._playlist.clear()
        self._current_index = -1
        # 清除标签缓存，避免删除/移动文件后显示过期标签
        if hasattr(self, "_video_tags_cache"):
            self._video_tags_cache.clear()

        video_path = self._get_video_path()
        if not os.path.isdir(video_path):
            self._update_empty_hint()
            return

        found: List[str] = []
        try:
            for root, _dirs, files in os.walk(video_path):
                for name in files:
                    if name.lower().endswith(VIDEO_EXTENSIONS):
                        full_path = os.path.join(root, name)
                        if os.path.isfile(full_path):
                            found.append(full_path)
        except Exception as e:
            logger.error(f"扫描视频文件失败: {e}")

        found.sort(key=lambda p: os.path.basename(p).lower())
        self._playlist = found

        # 填充列表（使用自定义 widget 显示封面）
        for path in self._playlist:
            item_widget = self._create_video_list_item(path)
            item = QListWidgetItem()
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            item.setSizeHint(item_widget.sizeHint())
            self.video_list.addItem(item)
            self.video_list.setItemWidget(item, item_widget)

        self._update_empty_hint()
        self._load_uploaders()
        self._load_types()
        self._load_tags()
        logger.info(f"扫描完成，共找到 {len(self._playlist)} 个视频文件")

    def _update_empty_hint(self):
        """更新空状态提示"""
        empty = self.video_list.count() == 0
        self.empty_hint.setVisible(empty)
        self.video_list.setVisible(not empty)

    def _on_theme_changed(self):
        """主题切换时刷新颜色"""
        empty_hint_color = "#999" if isDarkTheme() else "gray"
        self.empty_hint.setStyleSheet(f"color: {empty_hint_color}; padding: 20px;")
        # 刷新视频列表以更新封面背景色
        self._update_list_from_playlist()

    def _toggle_play(self):
        """播放/暂停切换"""
        state = self._player.playbackState()
        if state == QMediaPlayer.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PausedState:
            self._do_play()
        elif state == QMediaPlayer.StoppedState:
            if self._current_index >= 0:
                self._do_play()
            elif self._playlist:
                self._play_index(0)

    def _do_play(self):
        """统一的播放方法，确保与音频互斥"""
        window = self.window()
        if window and hasattr(window, 'stop_audio_requested'):
            window.stop_audio_requested.emit()
        self._player.play()

    def _play_prev(self):
        """上一首"""
        if not self._playlist:
            return
        if self._current_index > 0:
            self._play_index(self._current_index - 1)
        else:
            self._play_index(len(self._playlist) - 1)

    def _play_next(self):
        """下一首"""
        if not self._playlist:
            return
        if self._current_index < len(self._playlist) - 1:
            self._play_index(self._current_index + 1)
        else:
            self._play_index(0)

    def _play_index(self, index: int, resume: bool = True):
        """播放指定索引的视频

        :param resume: 是否从上次保存的位置续播（默认 True）
        """
        if index < 0 or index >= len(self._playlist):
            return

        # 切换前保存当前视频的播放进度
        if 0 <= self._current_index < len(self._playlist):
            self._save_current_position()

        path = self._playlist[index]
        self._current_index = index
        self._player.setSource(QUrl.fromLocalFile(path))

        # 断点续播：恢复上次保存的播放位置
        if resume:
            try:
                from ..database import get_database
                db = get_database()
                saved_pos = db.get_position(path)
                if saved_pos > 1000:  # 超过 1 秒才恢复
                    self._player.setPosition(saved_pos)
            except Exception as e:
                logger.debug(f"恢复播放位置失败: {e}")

        self._do_play()

        # 更新列表选中状态
        self.video_list.setCurrentRow(index)
        self.progress_slider.setEnabled(True)

    def _toggle_mute(self):
        """静音切换"""
        self._audio_output.setMuted(not self._audio_output.isMuted())
        self.volume_btn.setIcon(FIcon.VOLUME)

    def _on_volume_changed(self, value: int):
        """音量变化"""
        self._audio_output.setVolume(value / 100.0)

    def _volume_up(self):
        """增加音量 10%"""
        cur = self.volume_slider.value()
        self.volume_slider.setValue(min(100, cur + 10))

    def _volume_down(self):
        """减少音量 10%"""
        cur = self.volume_slider.value()
        self.volume_slider.setValue(max(0, cur - 10))

    def _toggle_mute_key(self):
        """快捷键静音切换"""
        self._toggle_mute()

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

    def _seek_percent(self, pct: int):
        """跳转到视频的指定百分比位置"""
        dur = self._player.duration()
        if dur > 0:
            self._player.setPosition(int(dur * pct / 100))

    def _toggle_fullscreen(self):
        """全屏切换：使用独立窗口实现全屏"""
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        """进入全屏：创建独立窗口，将视频输出切换到全屏窗口"""
        if self._fullscreen_window:
            self._fullscreen_window.showFullScreen()
            return

        self._fullscreen_window = QWidget()
        self._fullscreen_window.setWindowTitle("Bili23 视频播放 - 全屏")
        self._fullscreen_window.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint
        )
        layout = QVBoxLayout(self._fullscreen_window)
        layout.setContentsMargins(0, 0, 0, 0)

        self._fullscreen_video_widget = QVideoWidget(self._fullscreen_window)
        layout.addWidget(self._fullscreen_video_widget)

        # 将视频输出切换到全屏窗口
        self._player.setVideoOutput(self._fullscreen_video_widget)

        # ESC 退出全屏
        QShortcut(QKeySequence(Qt.Key_Escape), self._fullscreen_window,
                  activated=self._exit_fullscreen)
        # 空格暂停
        QShortcut(QKeySequence(Qt.Key_Space), self._fullscreen_window,
                  activated=self._toggle_play)

        self._fullscreen_window.showFullScreen()

    def _exit_fullscreen(self):
        """退出全屏：将视频输出切换回主界面"""
        if self._fullscreen_window:
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_video_widget = None
        # 将视频输出切换回主界面的 video_widget
        self._player.setVideoOutput(self.video_widget)

    def _open_file(self):
        """打开视频文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开视频文件", "",
            "视频文件 (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v);;所有文件 (*)"
        )
        if path and os.path.isfile(path):
            self._playlist.insert(0, path)
            self._update_list_from_playlist()
            self._play_index(0)

    def _update_list_from_playlist(self):
        """从播放列表更新列表控件"""
        self.video_list.clear()
        for path in self._playlist:
            item_widget = self._create_video_list_item(path)
            item = QListWidgetItem()
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            item.setSizeHint(item_widget.sizeHint())
            self.video_list.addItem(item)
            self.video_list.setItemWidget(item, item_widget)

    def _create_video_list_item(self, path: str) -> QWidget:
        """创建带封面和标签的视频列表项 widget"""
        item = SimpleCardWidget(self)
        item.setFixedHeight(84)
        layout = QHBoxLayout(item)
        layout.setContentsMargins(8, 6, 8, 6)

        # 封面缩略图
        thumbnail = QLabel("🎬")
        thumbnail.setObjectName("video_thumbnail")
        thumbnail.setFixedSize(QSize(90, 50))
        thumbnail.setAlignment(Qt.AlignCenter)
        thumb_bg = "#3C3C3C" if isDarkTheme() else "#E8ECF4"
        thumbnail.setStyleSheet(f"background: {thumb_bg}; border-radius: 6px; font-size: 24px;")
        layout.addWidget(thumbnail)

        # 记录视频路径，用于封面加载回调匹配
        thumbnail.setProperty("video_path", path)

        # 异步加载封面
        if path in self._cover_cache:
            pix = self._cover_cache[path]
            if pix and not pix.isNull():
                thumbnail.setPixmap(pix.scaled(90, 50, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                thumbnail.setStyleSheet("background: transparent; border-radius: 6px;")
        else:
            self._cover_cache[path] = None
            loader = _VideoCoverLoader(path, self)
            loader.loaded.connect(lambda p, px: self._on_video_cover_loaded(p, px))
            self._cover_loaders.append(loader)
            loader.start()

        # 信息区
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        display_name = os.path.splitext(os.path.basename(path))[0]
        title = BodyLabel(display_name[:40])
        title.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(title)

        # 文件大小
        size_str = ""
        try:
            size = os.path.getsize(path)
            if size > 1024 * 1024 * 1024:
                size_str = f"{size / 1024 / 1024 / 1024:.1f} GB"
            elif size > 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            else:
                size_str = f"{size / 1024:.0f} KB"
        except Exception:
            pass
        folder = os.path.basename(os.path.dirname(path))
        meta = CaptionLabel(f"📁 {folder}" + (f"  ·  💾 {size_str}" if size_str else ""))
        info_layout.addWidget(meta)

        # 标签 badge 行
        tag_row = QHBoxLayout()
        tag_row.setSpacing(4)
        tag_row.setContentsMargins(0, 0, 0, 0)
        tags = self._get_video_tags_cached(path)
        max_show = 4  # 最多显示 4 个，超出显示 +N
        for t in tags[:max_show]:
            tag_row.addWidget(self._make_mini_badge(t["tag"], t.get("category", "自定义")))
        if len(tags) > max_show:
            more = QLabel(f"+{len(tags) - max_show}")
            more.setStyleSheet("color: gray; font-size: 10px;")
            tag_row.addWidget(more)
        tag_row.addStretch()
        info_layout.addLayout(tag_row)

        info_layout.addStretch()
        layout.addLayout(info_layout, 1)
        return item

    def _get_video_tags_cached(self, path: str) -> list:
        """获取视频标签（带内存缓存，标签编辑后会清除缓存）"""
        if not hasattr(self, "_video_tags_cache"):
            self._video_tags_cache: dict = {}
        if path in self._video_tags_cache:
            return self._video_tags_cache[path]
        try:
            from ..database import get_database
            db = get_database()
            tags = db.get_video_tags(path)
        except Exception as e:
            logger.debug(f"获取视频标签失败 {path}: {e}")
            tags = []
        self._video_tags_cache[path] = tags
        return tags

    def _make_mini_badge(self, name: str, category: str) -> QLabel:
        """创建列表项中的小标签 badge"""
        badge = QLabel(name)
        color = TAG_CATEGORY_COLORS.get(category, "#607D8B")
        badge.setStyleSheet(
            f"background: {color}; color: white; "
            "border-radius: 7px; padding: 1px 6px; font-size: 10px;"
        )
        badge.setFixedHeight(16)
        badge.setToolTip(f"[{category}] {name}")
        return badge

    def _refresh_video_list_tags(self):
        """标签编辑后刷新视频列表的标签显示"""
        # 清除标签缓存并重建列表（封面已缓存，重建开销低）
        if hasattr(self, "_video_tags_cache"):
            self._video_tags_cache.clear()
        self._update_list_from_playlist()

    def _on_video_cover_loaded(self, path: str, pix: QPixmap):
        """视频封面加载完成回调"""
        if pix and not pix.isNull():
            self._cover_cache[path] = pix
            scaled = pix.scaled(90, 50, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            for i in range(self.video_list.count()):
                item = self.video_list.item(i)
                widget = self.video_list.itemWidget(item)
                if widget:
                    thumb = widget.findChild(QLabel, "video_thumbnail")
                    if thumb and thumb.property("video_path") == path:
                        thumb.setPixmap(scaled)
                        thumb.setStyleSheet("background: transparent; border-radius: 6px;")

    def _cycle_speed(self):
        """切换播放速度"""
        speeds = [0.5, 1.0, 1.25, 1.5, 2.0]
        current = self._player.playbackRate()
        try:
            idx = speeds.index(current)
            next_idx = (idx + 1) % len(speeds)
        except ValueError:
            next_idx = 1  # 默认回到 1.0
        new_speed = speeds[next_idx]
        self._player.setPlaybackRate(new_speed)
        self.speed_label.setText(f"{new_speed}x")

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击播放"""
        path = item.data(Qt.UserRole)
        if path and path in self._playlist:
            self._play_index(self._playlist.index(path))

    def _on_context_menu(self, point):
        """右键菜单"""
        item = self.video_list.itemAt(point)
        if not item:
            return

        path = item.data(Qt.UserRole)
        menu = QMenu(self)

        play_action = menu.addAction("▶ 播放")
        play_action.triggered.connect(lambda: self._on_item_double_clicked(item))

        menu.addSeparator()

        tag_action = menu.addAction("🏷 编辑标签")
        tag_action.triggered.connect(lambda: self._edit_video_tags(path))

        rename_action = menu.addAction("✏️ 重命名")
        rename_action.triggered.connect(lambda: self._rename_video(path))

        open_folder_action = menu.addAction("📁 打开所在文件夹")
        open_folder_action.triggered.connect(lambda: self._open_in_explorer(path))

        delete_action = menu.addAction("🗑 删除文件")
        delete_action.triggered.connect(lambda: self._delete_video(path))

        menu.exec(self.video_list.mapToGlobal(point))

    def _rename_video(self, path: str):
        """重命名视频文件"""
        if not os.path.isfile(path):
            return

        current_name = os.path.basename(path)
        name_without_ext, ext = os.path.splitext(current_name)
        new_name, ok = QInputDialog.getText(
            self, "重命名", "输入新文件名:", text=name_without_ext
        )
        if not ok or not new_name.strip() or new_name.strip() == name_without_ext:
            return

        new_name = new_name.strip()
        # 确保保留扩展名
        if not new_name.lower().endswith(ext.lower()):
            new_name += ext

        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            InfoBar.warning("重命名失败", "该文件名已存在", duration=2000, parent=self)
            return

        try:
            os.rename(path, new_path)
            self._rename_related_files(path, new_path)
            InfoBar.success("重命名成功", f"已重命名为 {new_name}", duration=2000, parent=self)
            self._scan_video_files()
        except Exception as e:
            InfoBar.error("重命名失败", str(e), duration=3000, parent=self)

    def _rename_related_files(self, old_path: str, new_path: str):
        """同步重命名相关的歌词和封面文件"""
        old_base = os.path.splitext(old_path)[0]
        new_base = os.path.splitext(new_path)[0]
        for suffix in ['.lrc', '.zh.lrc', '.jpg', '.png', '.webp']:
            old_file = old_base + suffix
            new_file = new_base + suffix
            if os.path.exists(old_file) and not os.path.exists(new_file):
                try:
                    os.rename(old_file, new_file)
                except Exception:
                    pass

    def _open_in_explorer(self, path: str):
        """在资源管理器中打开"""
        if os.path.isfile(path):
            import subprocess
            subprocess.run(["explorer", "/select,", path], shell=True)

    def _delete_video(self, path: str):
        """删除视频文件"""
        if not os.path.isfile(path):
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除文件吗？\n{os.path.basename(path)}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # 停止播放
            if self._current_index >= 0 and self._playlist[self._current_index] == path:
                self._player.stop()
                self._current_index = -1

            os.remove(path)
            InfoBar.success("删除成功", f"已删除 {os.path.basename(path)}", duration=2000, parent=self)
            self._scan_video_files()
        except Exception as e:
            InfoBar.error("删除失败", str(e), duration=3000, parent=self)

    def _on_slider_pressed(self):
        self._is_seeking = True

    def _on_slider_moved(self, value: int):
        self.current_time_label.setText(_format_time(value))

    def _on_slider_released(self):
        value = self.progress_slider.value()
        self._player.setPosition(value)
        self._is_seeking = False

    def _on_position_changed(self, position: int):
        self.current_time_label.setText(_format_time(position))
        if not self._is_seeking:
            self.progress_slider.setValue(int(position))

    def _on_duration_changed(self, duration: int):
        self.progress_slider.setRange(0, int(duration))
        self.total_time_label.setText(_format_time(duration))

    def _on_state_changed(self, state):
        """播放状态变化"""
        if state == QMediaPlayer.PlayingState:
            self.play_btn.setIcon(FIcon.PAUSE)
            self._progress_timer.start()
            self._save_position_timer.start()
        elif state == QMediaPlayer.PausedState:
            self.play_btn.setIcon(FIcon.PLAY)
            self._progress_timer.stop()
            self._save_position_timer.stop()
            self._save_current_position()
        elif state == QMediaPlayer.StoppedState:
            self.play_btn.setIcon(FIcon.PLAY)
            self._progress_timer.stop()
            self._save_position_timer.stop()
            self._save_current_position()

    def _on_error(self, error):
        """播放错误"""
        logger.error(f"视频播放错误: {self._player.errorString()}")
        InfoBar.error("播放失败", self._player.errorString(), duration=3000, parent=self)

    def _on_progress_tick(self):
        """进度刷新"""
        if self._is_seeking:
            return
        try:
            position = self._player.position()
            self.progress_slider.setValue(int(position))
            self.current_time_label.setText(_format_time(int(position)))
        except Exception:
            pass

    def _save_current_position(self):
        """保存当前视频播放位置到数据库（用于断点续播）"""
        try:
            if 0 <= self._current_index < len(self._playlist):
                path = self._playlist[self._current_index]
                position = self._player.position()
                duration = self._player.duration()
                # 已播放到结尾（或接近结尾）则清除记录，避免下次从头续播
                if duration > 0 and position >= duration - 2000:
                    from ..database import get_database
                    get_database().clear_position(path)
                elif position > 1000:
                    from ..database import get_database
                    get_database().save_position(path, int(position))
        except Exception as e:
            logger.debug(f"保存播放位置失败: {e}")

    def stop(self):
        """停止播放并保存位置（供外部调用）"""
        self._save_position_timer.stop()
        self._save_current_position()
        self._player.stop()

    def closeEvent(self, event):
        """页面关闭时保存播放位置"""
        self._save_current_position()
        super().closeEvent(event)

    def _on_media_status_changed(self, status):
        """媒体状态变化：播放结束时清除进度记录"""
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.EndOfMedia:
            try:
                if 0 <= self._current_index < len(self._playlist):
                    path = self._playlist[self._current_index]
                    from ..database import get_database
                    get_database().clear_position(path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 按UP主分类
    # ------------------------------------------------------------------
    def _get_uploader_for_path(self, path: str) -> str:
        """从路径中提取UP主名（downloads/videos/UP主名/ 文件夹结构）"""
        try:
            video_dir = self._get_video_path()
            rel = os.path.relpath(os.path.dirname(path), video_dir)
            # rel 形如 "UP主名" 或 "UP主名/子目录"
            parts = rel.replace("\\", "/").split("/")
            if parts and parts[0] != ".":
                return parts[0]
        except Exception:
            pass
        return "未知UP主"

    def _load_uploaders(self):
        """加载UP主分类列表"""
        self.uploader_list.clear()
        self._uploader_map.clear()
        self.uploader_detail.setVisible(False)
        self.uploader_list.setVisible(True)

        for path in self._playlist:
            uploader = self._get_uploader_for_path(path)
            self._uploader_map.setdefault(uploader, []).append(path)

        sorted_uploaders = sorted(self._uploader_map.items(),
                                  key=lambda x: len(x[1]), reverse=True)
        for uploader, videos in sorted_uploaders:
            item = QListWidgetItem(f"👤 {uploader}  ({len(videos)}个)")
            item.setData(Qt.UserRole, uploader)
            self.uploader_list.addItem(item)

    def _on_uploader_clicked(self, item):
        """点击UP主，显示其视频列表"""
        uploader = item.data(Qt.UserRole)
        if not uploader:
            return
        self.uploader_title.setText(f"👤 {uploader}")
        self.uploader_video_list.clear()
        videos = self._uploader_map.get(uploader, [])
        for path in videos:
            display_name = os.path.splitext(os.path.basename(path))[0]
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.uploader_video_list.addItem(item)
        self.uploader_list.setVisible(False)
        self.uploader_detail.setVisible(True)

    def _play_uploader_video(self, item):
        """双击播放UP主分类中的视频"""
        path = item.data(Qt.UserRole)
        if path and path in self._playlist:
            self._play_index(self._playlist.index(path))

    # ------------------------------------------------------------------
    # 按类型分类
    # ------------------------------------------------------------------
    def _get_type_for_path(self, path: str) -> str:
        """根据文件扩展名分类"""
        ext = os.path.splitext(path)[1].lower()
        type_map = {
            '.mp4': 'MP4', '.mkv': 'MKV', '.avi': 'AVI',
            '.mov': 'MOV', '.wmv': 'WMV', '.flv': 'FLV',
            '.webm': 'WebM', '.m4v': 'M4V',
        }
        return type_map.get(ext, '其他')

    def _load_types(self):
        """加载类型分类列表"""
        self.type_list.clear()
        self._type_map.clear()
        self.type_detail.setVisible(False)
        self.type_list.setVisible(True)

        for path in self._playlist:
            vtype = self._get_type_for_path(path)
            self._type_map.setdefault(vtype, []).append(path)

        sorted_types = sorted(self._type_map.items(),
                              key=lambda x: len(x[1]), reverse=True)
        for vtype, videos in sorted_types:
            item = QListWidgetItem(f"📁 {vtype}  ({len(videos)}个)")
            item.setData(Qt.UserRole, vtype)
            self.type_list.addItem(item)

    def _on_type_clicked(self, item):
        """点击类型，显示其视频列表"""
        vtype = item.data(Qt.UserRole)
        if not vtype:
            return
        self.type_title.setText(f"📁 {vtype}")
        self.type_video_list.clear()
        videos = self._type_map.get(vtype, [])
        for path in videos:
            display_name = os.path.splitext(os.path.basename(path))[0]
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.type_video_list.addItem(item)
        self.type_list.setVisible(False)
        self.type_detail.setVisible(True)

    def _play_type_video(self, item):
        """双击播放类型分类中的视频"""
        path = item.data(Qt.UserRole)
        if path and path in self._playlist:
            self._play_index(self._playlist.index(path))

    # ------------------------------------------------------------------
    # 按标签分类
    # ------------------------------------------------------------------
    def _load_tags(self):
        """加载标签分类列表（按分类分组显示）"""
        self.tag_list.clear()
        self.tag_detail.setVisible(False)
        self.tag_list.setVisible(True)

        try:
            from ..database import get_database, VIDEO_TAG_CATEGORIES
            db = get_database()
            all_tags = db.get_all_video_tags()  # [{'tag', 'category'}, ...]

            # 统计每个标签在当前播放列表中的有效视频数，并按分类分组
            grouped: dict = {}  # {category: [(tag, count), ...]}
            for t in all_tags:
                cat = t.get("category", "自定义")
                tag = t["tag"]
                videos = db.get_videos_by_tag(tag)
                valid_count = sum(1 for v in videos if v in self._playlist)
                if valid_count > 0:
                    grouped.setdefault(cat, []).append((tag, valid_count))

            if not grouped:
                return

            # 按预设顺序遍历分类，保证显示顺序一致；未在预设中的分类追加在后
            categories = list(VIDEO_TAG_CATEGORIES)
            for cat in grouped:
                if cat not in categories:
                    categories.append(cat)

            for cat in categories:
                items = grouped.get(cat)
                if not items:
                    continue
                # 分类标题项（不可选中，仅作分组展示）
                icon = TAG_CATEGORY_ICONS.get(cat, "📌")
                header = QListWidgetItem(f"{icon} {cat}")
                header.setData(Qt.UserRole, None)  # None 标记为标题项
                header.setFlags(Qt.ItemIsEnabled)  # 仅 enabled，不可选中
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                color = TAG_CATEGORY_COLORS.get(cat, "#607D8B")
                header.setForeground(QColor(color))
                self.tag_list.addItem(header)

                # 该分类下的标签项
                for tag, count in items:
                    item = QListWidgetItem(f"    🏷 {tag}  ({count}个)")
                    item.setData(Qt.UserRole, tag)
                    # 额外记录分类，供详情标题使用
                    item.setData(Qt.UserRole + 1, cat)
                    self.tag_list.addItem(item)
        except Exception as e:
            logger.warning(f"加载标签分类失败: {e}")

    def _on_tag_clicked(self, item):
        """点击标签，显示其视频列表"""
        tag = item.data(Qt.UserRole)
        if not tag:
            # 分类标题项，忽略点击
            return
        cat = item.data(Qt.UserRole + 1) or "自定义"
        icon = TAG_CATEGORY_ICONS.get(cat, "📌")
        self.tag_title.setText(f"{icon} [{cat}] {tag}")
        self.tag_video_list.clear()
        try:
            from ..database import get_database
            db = get_database()
            videos = db.get_videos_by_tag(tag)
            for path in videos:
                if path not in self._playlist:
                    continue
                display_name = os.path.splitext(os.path.basename(path))[0]
                item = QListWidgetItem(display_name)
                item.setData(Qt.UserRole, path)
                item.setToolTip(path)
                self.tag_video_list.addItem(item)
        except Exception as e:
            logger.warning(f"加载标签视频失败: {e}")
        self.tag_list.setVisible(False)
        self.tag_detail.setVisible(True)

    def _play_tag_video(self, item):
        """双击播放标签分类中的视频"""
        path = item.data(Qt.UserRole)
        if path and path in self._playlist:
            self._play_index(self._playlist.index(path))

    def _on_tag_back(self):
        """从标签详情返回标签列表"""
        self.tag_list.setVisible(True)
        self.tag_detail.setVisible(False)

    def _edit_video_tags(self, path: str):
        """编辑视频标签对话框"""
        try:
            from ..database import get_database
            db = get_database()
            current_tags = db.get_video_tags(path)

            dialog = VideoTagEditDialog(path, current_tags, self)
            if dialog.exec():
                new_tags = dialog.get_tags()  # [{'tag', 'category'}, ...]
                # 清除旧标签并按新列表重新写入（含分类）
                db.clear_video_tags(path)
                for t in new_tags:
                    db.add_video_tag(path, t["tag"], t.get("category", "自定义"))
                InfoBar.success("标签已保存", f"已设置 {len(new_tags)} 个标签",
                                duration=2000, parent=self)
                self._load_tags()
                # 刷新当前播放列表项的标签显示
                self._refresh_video_list_tags()
        except Exception as e:
            logger.error(f"编辑标签失败: {e}", exc_info=True)
            InfoBar.error("编辑标签失败", str(e), duration=3000, parent=self)