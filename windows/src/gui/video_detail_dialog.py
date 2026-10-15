"""
视频详情对话框
==============
显示视频详细信息并提供下载选项。
支持多分P选择（异步加载分P信息）、全选、批量下载。
"""
import os
from typing import Optional, List

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QWidget, QListWidget, QListWidgetItem,
    QProgressBar, QAbstractItemView
)
from qfluentwidgets import (
    TabWidget, BodyLabel, SubtitleLabel, CaptionLabel,
    StrongBodyLabel, PrimaryPushButton, PushButton,
    ComboBox, CheckBox, FluentIcon as FIcon, InfoBar, isDarkTheme,
)

from ..models import VideoInfo, EpisodeInfo, DownloadTask, MediaType, VideoQuality
from ..config import config


class _FetchVideoInfoWorker(QThread):
    """异步获取视频分P信息"""
    finished = Signal(object)  # VideoInfo or None
    error = Signal(str)

    def __init__(self, bvid: str, parent=None):
        super().__init__(parent)
        self._bvid = bvid

    def run(self):
        try:
            from ..bilibili_api import BilibiliClient
            client = BilibiliClient()
            info = client.get_video_info(self._bvid)
            self.finished.emit(info)
        except Exception as e:
            self.error.emit(str(e))


class VideoDetailDialog(QDialog):
    """视频详情对话框（支持多分P选择与批量下载）"""

    def __init__(self, video: VideoInfo, parent=None):
        super().__init__(parent)
        self.video = video
        self.setWindowTitle(video.title[:50])
        self.resize(620, 600)
        # 保存窗口引用，用于发射下载信号
        self._main_window = self._find_main_window(parent)
        # 异步加载分P信息的工作线程
        self._fetch_worker: Optional[_FetchVideoInfoWorker] = None
        self._setup_ui()
        # 若 video.episodes 为空，异步获取分P信息
        if not self.video.episodes:
            self._fetch_episodes()

    def _find_main_window(self, parent):
        """向上查找 MainWindow 引用"""
        p = parent
        while p is not None:
            if hasattr(p, 'download_task_added'):
                return p
            p = p.parent() if hasattr(p, 'parent') else None
        return None

    def _setup_ui(self):
        # 设置对话框背景色，匹配 qfluentwidgets 主题
        bg = "#282828" if isDarkTheme() else "#F0F0F0"
        self.setStyleSheet(f"QDialog {{ background: {bg}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 视频标题
        title_label = StrongBodyLabel(self.video.title)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # 视频信息
        info_layout = QHBoxLayout()
        info_items = [
            f"👁 {self.video.views:,}",
            f"💬 {self.video.danmaku_count}",
            f"⭐ {self.video.favorites}",
            f"👤 {self.video.owner_name}",
        ]
        for item in info_items:
            info_layout.addWidget(CaptionLabel(item))
        info_layout.addStretch()
        layout.addLayout(info_layout)

        # 分P选择区域
        self.episode_header_layout = QHBoxLayout()
        self.episode_header_layout.addWidget(BodyLabel("选择分P:"))
        self.episode_header_layout.addStretch()

        # 全选/取消全选按钮
        self.select_all_btn = PushButton("全选")
        self.select_all_btn.setFixedWidth(80)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        self.episode_header_layout.addWidget(self.select_all_btn)

        layout.addLayout(self.episode_header_layout)

        # 分P列表（多选模式）
        self.episode_list = QListWidget()
        self.episode_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.episode_list.setMaximumHeight(220)
        self.episode_list.setStyleSheet("QListWidget { background: transparent; border: 1px solid #ccc; border-radius: 4px; }")
        self._populate_episodes()
        layout.addWidget(self.episode_list)

        # 加载提示（异步获取分P时显示）
        self.loading_label = CaptionLabel("")
        self.loading_label.setStyleSheet("color: #888;")
        layout.addWidget(self.loading_label)

        # 画质选择
        quality_row = QHBoxLayout()
        quality_row.addWidget(BodyLabel("画质:"))
        self.quality_combo = ComboBox()
        quality_options = [
            ("360P", VideoQuality.P360),
            ("480P", VideoQuality.P480),
            ("720P", VideoQuality.P720),
            ("1080P", VideoQuality.P1080),
            ("1080P+", VideoQuality.P1080P),
            ("1080P60", VideoQuality.P1080P_PLUS),
            ("4K", VideoQuality.P4K),
            ("杜比视界", VideoQuality.DOLBY),
            ("HDR", VideoQuality.HDR),
        ]
        for name, value in quality_options:
            self.quality_combo.addItem(name, userData=value)
        self.quality_combo.setCurrentIndex(3)  # 默认1080P
        quality_row.addWidget(self.quality_combo, 1)
        layout.addLayout(quality_row)

        # 下载选项
        options_layout = QHBoxLayout()
        self.download_video_check = CheckBox("下载视频")
        self.download_video_check.setChecked(True)
        self.download_audio_check = CheckBox("下载音频")
        self.download_audio_check.setChecked(True)
        self.download_danmaku_check = CheckBox("下载弹幕")
        options_layout.addWidget(self.download_video_check)
        options_layout.addWidget(self.download_audio_check)
        options_layout.addWidget(self.download_danmaku_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 下载按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.download_btn = PrimaryPushButton("⬇ 开始下载")
        self.download_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self.download_btn)

        layout.addLayout(btn_layout)

    def _populate_episodes(self):
        """填充分P列表"""
        self.episode_list.clear()
        if not self.video.episodes:
            return
        for ep in self.video.episodes:
            dur = ep.duration or 0
            text = f"P{ep.page} - {ep.part} ({dur}秒)"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, ep)
            self.episode_list.addItem(item)
        # 默认选中第一个
        if self.episode_list.count() > 0:
            self.episode_list.setCurrentRow(0)

    def _fetch_episodes(self):
        """异步获取分P信息"""
        self.loading_label.setText("⏳ 正在获取分P信息...")
        self.download_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self._fetch_worker = _FetchVideoInfoWorker(self.video.bvid, self)
        self._fetch_worker.finished.connect(self._on_episodes_loaded)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_episodes_loaded(self, video_info):
        """分P信息加载完成"""
        self.download_btn.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        if video_info and video_info.episodes:
            # 更新 video 的 episodes 列表
            self.video.episodes = video_info.episodes
            self.video.total_episodes = video_info.total_episodes
            self.video.is_multi_episode = video_info.is_multi_episode
            self._populate_episodes()
            count = len(self.video.episodes)
            self.loading_label.setText(f"✅ 共 {count} 个分P")
            if count > 1:
                self.loading_label.setText(f"✅ 共 {count} 个分P，可多选下载")
        else:
            self.loading_label.setText("⚠️ 未能获取分P信息，将下载默认分P")

    def _on_fetch_error(self, err: str):
        """分P信息加载失败"""
        self.download_btn.setEnabled(True)
        self.select_all_btn.setEnabled(False)
        self.loading_label.setText(f"⚠️ 获取分P失败: {err}")

    def _toggle_select_all(self):
        """全选/取消全选"""
        if self.episode_list.count() == 0:
            return
        # 判断当前是否已全选
        all_selected = (len(self.episode_list.selectedItems()) == self.episode_list.count())
        if all_selected:
            # 取消全选
            self.episode_list.clearSelection()
            self.select_all_btn.setText("全选")
        else:
            # 全选
            self.episode_list.selectAll()
            self.select_all_btn.setText("取消全选")

    def _get_selected_episodes(self) -> List[EpisodeInfo]:
        """获取选中的分P列表"""
        episodes = []
        for item in self.episode_list.selectedItems():
            ep = item.data(Qt.UserRole)
            if ep:
                episodes.append(ep)
        # 如果没有选中任何项，回退到第一个
        if not episodes and self.video.episodes:
            episodes = [self.video.episodes[0]]
        return episodes

    def _start_download(self):
        """开始下载（支持批量下载选中的分P）"""
        episodes = self._get_selected_episodes()
        if not episodes:
            InfoBar.warning("无分P", "未选择任何分P", duration=2000, parent=self)
            return

        quality_value = self.quality_combo.currentData()
        download_video = self.download_video_check.isChecked()
        download_audio = self.download_audio_check.isChecked()
        download_danmaku = self.download_danmaku_check.isChecked()

        if not (download_video or download_audio or download_danmaku):
            InfoBar.warning("无下载项", "请至少选择一种下载内容", duration=2000, parent=self)
            return

        # 批量创建下载任务
        task_count = 0
        for episode in episodes:
            if download_video:
                task = DownloadTask(
                    video_info=self.video,
                    episode=episode,
                    download_type=MediaType.VIDEO,
                    quality=VideoQuality(quality_value),
                )
                self._emit_task(task)
                task_count += 1
            if download_audio:
                audio_task = DownloadTask(
                    video_info=self.video,
                    episode=episode,
                    download_type=MediaType.AUDIO,
                    quality=VideoQuality(quality_value),
                )
                self._emit_task(audio_task)
                task_count += 1
            if download_danmaku:
                danmaku_task = DownloadTask(
                    video_info=self.video,
                    episode=episode,
                    download_type=MediaType.DANMAKU,
                )
                self._emit_task(danmaku_task)
                task_count += 1

        if task_count > 0:
            InfoBar.success("已添加", f"已添加 {len(episodes)} 个分P 共 {task_count} 个下载任务",
                            duration=3000, parent=self)
        self.accept()

    def _emit_task(self, task: DownloadTask):
        """发射下载任务信号"""
        if self._main_window and hasattr(self._main_window, 'download_task_added'):
            self._main_window.download_task_added.emit(task)
        else:
            # 回退：通过 window() 查找
            window = self.window()
            if hasattr(window, 'download_task_added'):
                window.download_task_added.emit(task)
