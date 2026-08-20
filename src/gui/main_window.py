"""
GUI 主窗口
==========
基于 PySide6 + qfluentwidgets 的现代化主界面。
"""
import time
import sys
import os
import logging
from typing import Optional, List

from PySide6.QtCore import Qt, QTimer, Signal, QSize, QThread, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QPixmap, QImage, QPainter, QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QScrollArea,
    QSizePolicy, QSystemTrayIcon, QMenu, QSplitter, QInputDialog, QMessageBox,
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, MessageBox,
    SimpleCardWidget, FlowLayout, PillPushButton, SearchLineEdit,
    LineEdit, PasswordLineEdit, SpinBox, CheckBox,
    ComboBox, Slider, BodyLabel, CaptionLabel, StrongBodyLabel,
    SubtitleLabel, TitleLabel, LargeTitleLabel,
    ProgressRing, IndeterminateProgressRing,
    ToolButton, TransparentToolButton, HyperlinkLabel,
    Theme, setTheme, isDarkTheme, qrouter,
    FluentIcon as FIcon,
    CommandBar, Action,
    PrimaryPushButton, PushButton, ScrollArea,
    InfoBar, InfoBarPosition,
)

from ..config import get_config, AppConfig, WhenClose, AudioCategoryMode
from ..models import VideoInfo, DownloadTask, DownloadStatus, MediaType, VideoQuality as ModelVideoQuality
from ..bilibili_api import BilibiliClient
from ..downloader import BilibiliDownloader, create_downloader, _quality_name
from ..cookie_manager import CookieManager, get_best_cookies, fetch_cookies_from_browser
from .audio_player_page import AudioPlayerPage
from .video_player_page import VideoPlayerPage

logger = logging.getLogger(__name__)

# 便捷访问
def cfg():
    """获取当前全局配置"""
    return get_config()


class _CoverLoader(QThread):
    """异步加载封面图线程"""
    loaded = Signal(str, QPixmap)  # (url, pixmap)

    def __init__(self, url: str, parent_widget, parent=None):
        super().__init__(parent)
        # 规范化 URL：B站返回的封面地址以 // 开头（协议相对），需补全 https:
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("http://"):
            url = "https://" + url[7:]
        self._url = url
        self._parent_widget = parent_widget

    def run(self):
        try:
            from ..network import get_client
            client = get_client()
            resp = client.get(self._url, follow_redirects=True)
            if resp.status_code == 200 and resp.content:
                img = QImage()
                if img.loadFromData(resp.content):
                    pix = QPixmap.fromImage(img)
                    if not pix.isNull():
                        self.loaded.emit(self._url, pix)
                        return
                else:
                    logger.debug(f"封面图片解析失败: {self._url} (content-size={len(resp.content)})")
            else:
                logger.debug(f"封面加载非200: status={resp.status_code}, url={self._url}")
        except Exception as e:
            logger.warning(f"加载封面异常 {self._url}: {e}")


class SearchWorker(QThread):
    """后台搜索线程，避免阻塞UI"""
    finished = Signal(object)  # SearchResult
    error = Signal(str)

    def __init__(self, client: BilibiliClient, keyword: str, page: int = 1, order: str = "totalrank"):
        super().__init__()
        self._client = client
        self._keyword = keyword
        self._page = page
        self._order = order

    def run(self):
        try:
            result = self._client.search(self._keyword, self._page, self._order)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class UserSearchWorker(QThread):
    """UP主搜索线程"""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, client: BilibiliClient, keyword: str, page: int = 1):
        super().__init__()
        self._client = client
        self._keyword = keyword
        self._page = page

    def run(self):
        try:
            result = self._client.search_users(self._keyword, self._page)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class UserVideoWorker(QThread):
    """获取UP主投稿视频线程"""
    finished = Signal(object)  # SearchResult
    error = Signal(str)

    def __init__(self, client: BilibiliClient, mid: int, page: int = 1):
        super().__init__()
        self._client = client
        self._mid = mid
        self._page = page

    def run(self):
        try:
            result = self._client.get_user_videos(self._mid, self._page)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class FavoritesWorker(QThread):
    """后台加载收藏夹线程"""
    folders_loaded = Signal(list)   # 收藏夹列表
    videos_loaded = Signal(list, int)  # 视频列表, 总数
    error = Signal(str)

    def __init__(self, client: BilibiliClient, mode: str = "folders", media_id: int = 0, page: int = 1):
        super().__init__()
        self._client = client
        self._mode = mode
        self._media_id = media_id
        self._page = page

    def run(self):
        try:
            if self._mode == "folders":
                folders = self._client.get_favorite_folders()
                self.folders_loaded.emit(folders)
            elif self._mode == "videos":
                result = self._client.get_favorite_videos(self._media_id, self._page)
                self.videos_loaded.emit(result.get("videos", []), result.get("total", 0))
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(FluentWindow):
    """主窗口"""

    search_requested = Signal(str)
    download_task_added = Signal(object)
    login_status_changed = Signal(bool)
    stop_audio_requested = Signal()
    stop_video_requested = Signal()

    def __init__(self):
        super().__init__()

        self.bilibili_client = BilibiliClient()
        self.cookie_manager = CookieManager()
        self.downloader = create_downloader()

        self.search_results: List[VideoInfo] = []
        self.current_video: Optional[VideoInfo] = None

        self.downloader.add_progress_callback(self._on_download_progress)

        # 下载页面刷新定时器（在 _setup_navigation 后创建）
        self._dl_refresh_timer = None
        self._page_anim = None  # 页面切换淡入动画

        self._setup_window()
        self._setup_navigation()
        self._setup_tray_icon()
        self._connect_signals()
        self._load_user_info()
        self._init_guest_cookies()

    def _setup_window(self):
        self.setWindowTitle("")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        # 设置应用图标
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "app_icon.jpg"
        )
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon, QPixmap
            self.setWindowIcon(QIcon(icon_path))

        setTheme(cfg().get(cfg().theme))
        if cfg().get(cfg().mica_effect):
            self.setMicaEffectEnabled(True)
        if cfg().get(cfg().stay_on_top):
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

    def _setup_navigation(self):
        self.home_page = HomePage(self)
        self.home_page.setObjectName("homePage")
        self.search_page = SearchPage(self)
        self.search_page.setObjectName("searchPage")
        self.favorites_page = FavoritesPage(self)
        self.favorites_page.setObjectName("favoritesPage")
        self.download_page = DownloadPage(self)
        self.download_page.setObjectName("downloadPage")
        self.audio_player_page = AudioPlayerPage(self)
        self.audio_player_page.setObjectName("audioPlayerPage")
        self.video_player_page = VideoPlayerPage(self)
        self.video_player_page.setObjectName("videoPlayerPage")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsPage")

        self.addSubInterface(self.home_page, FIcon.HOME, "首页")
        self.addSubInterface(self.search_page, FIcon.SEARCH, "搜索")
        self.addSubInterface(self.favorites_page, FIcon.HEART, "我的收藏")
        self.addSubInterface(self.download_page, FIcon.DOWNLOAD, "下载管理")
        self.addSubInterface(self.audio_player_page, FIcon.CALENDAR, "音频播放")
        self.addSubInterface(self.video_player_page, FIcon.VIDEO, "视频播放")
        self.addSubInterface(self.settings_page, FIcon.SETTING, "设置", NavigationItemPosition.BOTTOM)

        self.switchTo(self.home_page)

        # 下载页面刷新定时器：持续定时刷新下载列表（200ms），下载进行中时保持运行
        self._dl_refresh_timer = QTimer(self)
        self._dl_refresh_timer.setInterval(200)
        self._dl_refresh_timer.timeout.connect(self._on_dl_refresh_tick)

    def switchTo(self, widget):
        """切换页面并播放淡入动画"""
        super().switchTo(widget)
        # 淡入动画
        if self._page_anim:
            self._page_anim.stop()
        widget.setWindowOpacity(0.0)
        self._page_anim = QPropertyAnimation(widget, b"windowOpacity", self)
        self._page_anim.setDuration(200)
        self._page_anim.setStartValue(0.0)
        self._page_anim.setEndValue(1.0)
        self._page_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._page_anim.start()

    def _on_dl_refresh_tick(self):
        """定时器触发：刷新下载列表（下载进行中时持续运行）"""
        self.download_page.refresh_tasks()
        # 检查是否还有活跃任务，若全部完成则停止定时器
        has_active = any(
            t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING)
            for t in self.downloader.get_tasks()
        )
        if not has_active and self._dl_refresh_timer.isActive():
            self._dl_refresh_timer.stop()
            # 最后一次刷新确保显示完成状态
            self.download_page.refresh_tasks()

    def _setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        # 优先使用自定义图标，回退到系统图标
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "app_icon.jpg"
        )
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            from PySide6.QtWidgets import QStyle
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray_icon.setToolTip("B站下载器")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self._show_and_activate)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _connect_signals(self):
        self.search_requested.connect(self._on_search)
        self.download_task_added.connect(self._on_download_task_added)
        self.login_status_changed.connect(self._on_login_status_changed)
        self.stop_audio_requested.connect(self._stop_audio_playback)
        self.stop_video_requested.connect(self._stop_video_playback)

    def _stop_audio_playback(self):
        """停止音频播放（视频播放时调用），同时关闭桌面歌词"""
        try:
            if hasattr(self, 'audio_player_page') and self.audio_player_page:
                player = self.audio_player_page
                if hasattr(player, '_player') and player._player:
                    player._player.stop()
                # 关闭桌面歌词
                if hasattr(player, 'desktop_lyrics_switch') and player.desktop_lyrics_switch:
                    player.desktop_lyrics_switch.setChecked(False)
                elif hasattr(player, '_desktop_lyrics') and player._desktop_lyrics:
                    try:
                        player._desktop_lyrics.close()
                    except Exception:
                        pass
                    player._desktop_lyrics = None
        except Exception:
            pass

    def _stop_video_playback(self):
        """停止视频播放（音频播放时调用）"""
        try:
            if hasattr(self, 'video_player_page') and self.video_player_page:
                player = self.video_player_page
                if hasattr(player, '_player') and player._player:
                    player._player.stop()
        except Exception:
            pass

    def _load_user_info(self):
        if cfg().get(cfg().is_login):
            # 通过 check_login_status 判断，避免网络抖动误清登录状态
            status = self.bilibili_client.check_login_status()
            if status.get("success"):
                # 登录有效，刷新用户信息
                user_info = self.bilibili_client.get_user_info()
                if user_info and user_info.mid:
                    self.login_status_changed.emit(True)
                else:
                    # 用户信息获取失败但登录状态有效（网络抖动），保持登录
                    logger.warning("用户信息获取失败，但登录状态有效，保持登录")
                    self.login_status_changed.emit(True)
            else:
                msg = status.get("message", "")
                # 仅当 API 明确返回未登录（-101）或账号未登录时才清除
                if "登录" in msg or "login" in msg.lower() or status.get("data", {}).get("isLogin") is False:
                    logger.warning(f"登录 Cookie 已失效: {msg}，清除登录状态")
                    cfg().set(cfg().is_login, False)
                    cfg().set(cfg().is_expired, True)
                    self.login_status_changed.emit(False)
                else:
                    # 网络异常或其他错误，不清除登录状态，避免误清
                    logger.warning(f"登录状态检查失败: {msg}，保持登录状态待重试")
                    self.login_status_changed.emit(True)
        else:
            self.login_status_changed.emit(False)

    def _init_guest_cookies(self):
        if not self.cookie_manager.info.buvid3:
            self.cookie_manager.init_guest_cookies()

    def _on_search(self, keyword: str):
        """发起搜索（首页或搜索框触发，使用搜索页选中的排序方式）"""
        if not keyword:
            return
        # 读取搜索页面选中的排序方式
        order_text = self.search_page.sort_combo.currentText() if hasattr(self.search_page, 'sort_combo') else "综合排序"
        # 保存搜索上下文，用于分页
        self._search_keyword = keyword
        self._search_order = order_text
        self._search_page_num = 1
        self._do_search(keyword, 1, order_text)

    def _do_search(self, keyword: str, page: int, order: str):
        """执行搜索"""
        if not keyword:
            return
        # 如果有搜索正在运行，先等待完成
        if hasattr(self, '_search_worker') and self._search_worker and self._search_worker.isRunning():
            return
        # 显示加载状态
        self.search_page.set_loading()
        self.switchTo(self.search_page)
        # 启动后台搜索线程
        self._search_worker = SearchWorker(self.bilibili_client, keyword, page, order)
        self._search_worker.finished.connect(self._on_search_done)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.start()

    def _on_search_done(self, result):
        """搜索完成回调"""
        logger.info(f"搜索完成: {len(result.videos) if hasattr(result, 'videos') else 0} 个结果")
        self.search_page.set_results(result)

    def _on_search_error(self, error_msg):
        """搜索错误回调"""
        logger.error(f"搜索错误: {error_msg}")
        self.search_page.set_error(error_msg)

    def _do_user_search(self, keyword: str, page: int):
        """执行UP主搜索"""
        if not keyword:
            return
        if hasattr(self, '_user_search_worker') and self._user_search_worker and self._user_search_worker.isRunning():
            return
        self.search_page.set_loading()
        self.switchTo(self.search_page)
        self._user_search_worker = UserSearchWorker(self.bilibili_client, keyword, page)
        self._user_search_worker.finished.connect(self._on_user_search_done)
        self._user_search_worker.error.connect(self._on_search_error)
        self._user_search_worker.start()

    def _on_user_search_done(self, result):
        """UP主搜索完成回调"""
        logger.info(f"UP主搜索完成: {len(result.get('users', []))} 个结果")
        self.search_page.set_user_results(result)

    def _do_load_user_videos(self, mid: int, page: int):
        """加载UP主投稿视频"""
        if hasattr(self, '_user_video_worker') and self._user_video_worker and self._user_video_worker.isRunning():
            return
        self._user_video_worker = UserVideoWorker(self.bilibili_client, mid, page)
        self._user_video_worker.finished.connect(self._on_user_videos_done)
        self._user_video_worker.error.connect(self._on_search_error)
        self._user_video_worker.start()

    def _on_user_videos_done(self, result):
        """UP主视频加载完成"""
        logger.info(f"UP主视频加载完成: {len(result.videos) if hasattr(result, 'videos') else 0} 个")
        self.search_page.set_user_videos(result)

    def _on_download_task_added(self, task: DownloadTask):
        task_id = self.downloader.add_task(task)
        self.download_page.refresh_tasks()
        self.downloader.start_task(task_id)

    def _on_download_progress(self, task: DownloadTask):
        """下载进度回调：启动定时器持续刷新（定时器持续运行直到所有任务完成）"""
        if not self._dl_refresh_timer.isActive():
            self._dl_refresh_timer.start()

    def _on_login_status_changed(self, is_logged_in: bool):
        self.home_page.update_login_status(is_logged_in)
        self.search_page.update_login_status(is_logged_in)
        self.favorites_page.update_login_status(is_logged_in)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_and_activate()

    def _show_and_activate(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self):
        # 退出前显式保存配置，确保 Cookie 等状态持久化
        try:
            from ..config import save_config
            save_config(cfg())
        except Exception as e:
            logger.warning(f"退出时保存配置失败: {e}")
        self.tray_icon.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        when_close = cfg().get(cfg().when_close_window)
        if when_close == WhenClose.EXIT:
            self._quit_app()
        elif when_close == WhenClose.MINIMIZE:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage("B站下载器", "已最小化到系统托盘", QSystemTrayIcon.Information, 2000)
        else:
            reply = MessageBox(self, "确认退出", "确定要退出吗？\n点击\"确定\"退出，\"取消\"最小化到托盘。")
            if reply.exec():
                self._quit_app()
            else:
                event.ignore()
                self.hide()


class HomePage(QWidget):
    """首页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = LargeTitleLabel("🎵 B站下载器")
        subtitle = SubtitleLabel("B站视频下载工具 · 支持高清画质 · 自动获取Cookie")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        search_card = SimpleCardWidget(self)
        search_layout = QVBoxLayout(search_card)

        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索视频、UP主、番剧...")
        self.search_edit.setFixedHeight(44)
        self.search_edit.searchSignal.connect(self._on_search)
        search_layout.addWidget(self.search_edit)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        for label, kw in [("🔥 热门", "热门"), ("🎵 音乐", "音乐"), ("🎮 游戏", "游戏"), ("📺 番剧", "番剧")]:
            btn = PillPushButton(label)
            btn.clicked.connect(lambda checked, k=kw: self._do_search(k))
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        search_layout.addLayout(btn_layout)
        layout.addWidget(search_card)

        self.login_card = SimpleCardWidget(self)
        login_layout = QVBoxLayout(self.login_card)
        self.login_label = SubtitleLabel("未登录")
        self.login_desc = CaptionLabel("登录后可获取更高画质和会员视频")
        self.login_btn = PrimaryPushButton("👤 登录B站")
        self.login_btn.clicked.connect(self._on_login_clicked)
        login_layout.addWidget(self.login_label)
        login_layout.addWidget(self.login_desc)
        login_layout.addWidget(self.login_btn)
        layout.addWidget(self.login_card)

        info_card = SimpleCardWidget(self)
        info_layout = QHBoxLayout(info_card)
        for icon, label, value in [("📥", "已下载", "0 个视频"), ("⚡", "下载速度", "0 MB/s"), ("💾", "存储空间", "0 MB")]:
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(20, 10, 20, 10)
            i_label = QLabel(icon)
            i_label.setStyleSheet("font-size: 24px;")
            i_label.setAlignment(Qt.AlignCenter)
            v_label = StrongBodyLabel(value)
            v_label.setAlignment(Qt.AlignCenter)
            n_label = CaptionLabel(label)
            n_label.setAlignment(Qt.AlignCenter)
            item_layout.addWidget(i_label)
            item_layout.addWidget(v_label)
            item_layout.addWidget(n_label)
            info_layout.addWidget(item)
        layout.addWidget(info_card)
        layout.addStretch()

    def _do_search(self, keyword: str):
        self.window().search_requested.emit(keyword)

    def _on_search(self, keyword: str):
        self.window().search_requested.emit(keyword)

    def _on_login_clicked(self):
        from .login_dialog import LoginDialog
        main_win = self.window()
        dialog = LoginDialog(main_win)
        dialog._main_window = main_win
        if dialog.exec():
            self.update_login_status(True)

    def update_login_status(self, is_logged_in: bool):
        is_expired = cfg().get(cfg().is_expired)
        if is_logged_in:
            self.login_label.setText("✅ 已登录")
            self.login_desc.setText("您可以下载更高画质的视频")
            self.login_btn.setText("🔄 切换账号")
        elif is_expired:
            self.login_label.setText("⚠️ Cookie已过期")
            self.login_desc.setText("登录状态已失效，请重新登录")
            self.login_btn.setText("🔑 重新登录")
        else:
            self.login_label.setText("❌ 未登录")
            self.login_desc.setText("登录后可获取更高画质和会员视频")
            self.login_btn.setText("👤 登录B站")


class SearchPage(QWidget):
    """搜索结果页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_results = []
        self._current_page = 1
        self._current_keyword = ""
        self._current_order = "综合排序"
        self._search_type = "video"  # "video" 或 "user"
        self._current_user_mid = 0   # UP主搜索时记录当前 mid
        self._total = 0
        self._has_more = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        search_layout = QHBoxLayout()

        # 搜索类型切换
        self.type_combo = ComboBox()
        self.type_combo.addItems(["搜索视频", "搜索UP主"])
        self.type_combo.setFixedWidth(110)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        search_layout.addWidget(self.type_combo)

        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索B站视频...")
        self.search_edit.setFixedHeight(40)
        self.search_edit.searchSignal.connect(self._on_search)
        search_layout.addWidget(self.search_edit)

        self.sort_combo = ComboBox()
        self.sort_combo.addItems(["综合排序", "最多播放", "最新发布", "最多弹幕", "最多收藏"])
        self.sort_combo.setFixedWidth(130)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        search_layout.addWidget(self.sort_combo)
        layout.addLayout(search_layout)

        self.result_list = QListWidget()
        self.result_list.setStyleSheet("""
            QListWidget { border: none; background: transparent; outline: none; }
            QListWidget::item { padding: 8px; margin: 4px 0; }
        """)
        self.result_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.result_list)

        page_layout = QHBoxLayout()
        page_layout.addStretch()
        self.prev_btn = ToolButton(FIcon.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._prev_page)
        self.page_label = BodyLabel("第 1 页")
        self.next_btn = ToolButton(FIcon.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self.prev_btn)
        page_layout.addWidget(self.page_label)
        page_layout.addWidget(self.next_btn)
        page_layout.addStretch()
        layout.addLayout(page_layout)

    def _on_sort_changed(self, _index):
        """排序方式变化时，使用当前关键词重新搜索第1页"""
        if self._current_keyword:
            self._current_order = self.sort_combo.currentText()
            self._current_page = 1
            self.window()._do_search(self._current_keyword, 1, self._current_order)

    def _clear_list_widgets(self):
        """清理列表中所有项目的 widget，防止内存泄漏"""
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            widget = self.result_list.itemWidget(item)
            if widget:
                self.result_list.removeItemWidget(item)
                widget.deleteLater()
        self.result_list.clear()

    def set_loading(self):
        """显示加载状态"""
        self._clear_list_widgets()
        item = QListWidgetItem(self.result_list)
        item.setFlags(Qt.NoItemFlags)
        widget = QLabel("正在搜索中，请稍候...")
        widget.setAlignment(Qt.AlignCenter)
        empty_color = "#AAAAAA" if isDarkTheme() else "gray"
        widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
        item.setSizeHint(widget.sizeHint())
        self.result_list.addItem(item)
        self.result_list.setItemWidget(item, widget)

    def set_error(self, msg: str):
        """显示错误状态"""
        self._clear_list_widgets()
        item = QListWidgetItem(self.result_list)
        item.setFlags(Qt.NoItemFlags)
        widget = QLabel(f"搜索失败: {msg}")
        widget.setAlignment(Qt.AlignCenter)
        widget.setStyleSheet("color: red; padding: 40px;")
        item.setSizeHint(widget.sizeHint())
        self.result_list.addItem(item)
        self.result_list.setItemWidget(item, widget)

    def set_results(self, result):
        """设置搜索结果（接受 SearchResult 对象或列表）"""
        if hasattr(result, 'videos'):
            # SearchResult 对象
            self._current_results = result.videos
            self._total = result.total
            self._has_more = result.has_more
        else:
            # 兼容直接传入列表
            self._current_results = result
            self._total = len(result)
            self._has_more = False
        # 同步当前页码
        if hasattr(result, 'page'):
            self._current_page = result.page
        self._update_page_label()
        self._render_results()

    def _render_results(self):
        try:
            self._clear_list_widgets()

            if not self._current_results:
                item = QListWidgetItem(self.result_list)
                item.setFlags(Qt.NoItemFlags)
                widget = QLabel("未找到相关视频")
                widget.setAlignment(Qt.AlignCenter)
                empty_color = "#AAAAAA" if isDarkTheme() else "gray"
                widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
                item.setSizeHint(widget.sizeHint())
                self.result_list.addItem(item)
                self.result_list.setItemWidget(item, widget)
                return

            for video in self._current_results:
                try:
                    item_widget = self._create_video_item(video)
                    item = QListWidgetItem(self.result_list)
                    item.setData(Qt.UserRole, video)
                    item.setSizeHint(item_widget.sizeHint())
                    self.result_list.addItem(item)
                    self.result_list.setItemWidget(item, item_widget)
                except Exception as e:
                    logger.warning(f"渲染搜索结果项失败: {e}")
        except Exception as e:
            logger.error(f"渲染搜索结果异常: {e}", exc_info=True)

    def _create_video_item(self, video: VideoInfo) -> QWidget:
        item = SimpleCardWidget(self)
        item.setFixedHeight(90)
        layout = QHBoxLayout(item)
        layout.setContentsMargins(12, 8, 12, 8)

        # 封面图：优先异步加载网络封面，无封面时显示占位符
        thumbnail = QLabel("🎬")
        thumbnail.setObjectName("thumbnail")  # 便于加载完成后精确查找
        thumbnail.setFixedSize(QSize(100, 60))
        thumbnail.setAlignment(Qt.AlignCenter)
        thumb_bg = "#3C3C3C" if isDarkTheme() else "#E8ECF4"
        thumbnail.setStyleSheet(f"background: {thumb_bg}; border-radius: 8px; font-size: 32px;")
        layout.addWidget(thumbnail)

        # 异步加载封面图
        cover_url = getattr(video, 'cover_url', '') or ''
        if cover_url:
            # 规范化 URL（与 _CoverLoader 内部一致，确保缓存键匹配）
            norm_url = cover_url
            if norm_url.startswith("//"):
                norm_url = "https:" + norm_url
            elif norm_url.startswith("http://"):
                norm_url = "https://" + norm_url[7:]

            # 用动态属性记录该缩略图对应的 URL，加载完成后只更新匹配项
            thumbnail.setProperty("cover_url", norm_url)

            if not hasattr(self, '_cover_cache'):
                self._cover_cache = {}
            if not hasattr(self, '_cover_loaders'):
                self._cover_loaders = []  # 防止 loader 被垃圾回收

            if norm_url in self._cover_cache:
                pix = self._cover_cache[norm_url]
                if pix and not pix.isNull():
                    thumbnail.setPixmap(pix.scaled(100, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                    thumbnail.setStyleSheet("background: transparent; border-radius: 8px;")
            else:
                self._cover_cache[norm_url] = None  # 防止重复请求
                loader = _CoverLoader(cover_url, thumbnail, self)
                loader.loaded.connect(lambda url, pix: self._on_cover_loaded(url, pix))
                self._cover_loaders.append(loader)
                loader.start()

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_text = (video.title or "未知标题")[:50]
        title = BodyLabel(title_text)
        title.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(title)
        views = video.views or 0
        danmaku = video.danmaku_count or 0
        duration = video.duration or 0
        meta = CaptionLabel(f"👁 {views:,}  ·  💬 {danmaku}  ·  ⏱ {duration}秒")
        info_layout.addWidget(meta)
        author = CaptionLabel(f"👤 {video.owner_name or '未知'}")
        info_layout.addWidget(author)
        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)
        download_btn = PrimaryPushButton("下载视频")
        download_btn.setFixedWidth(80)
        download_btn.clicked.connect(lambda: self._on_download_clicked(video, MediaType.VIDEO))
        btn_layout.addWidget(download_btn)

        audio_btn = PushButton("下载音频")
        audio_btn.setFixedWidth(80)
        audio_btn.clicked.connect(lambda: self._on_download_clicked(video, MediaType.AUDIO))
        btn_layout.addWidget(audio_btn)
        layout.addLayout(btn_layout)
        return item

    def _on_cover_loaded(self, url: str, pix: QPixmap):
        """封面图加载完成回调：只更新 URL 匹配的缩略图"""
        if pix and not pix.isNull():
            self._cover_cache[url] = pix
            scaled = pix.scaled(100, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            # 遍历当前列表，仅更新 cover_url 属性匹配的缩略图
            for i in range(self.result_list.count()):
                item = self.result_list.item(i)
                widget = self.result_list.itemWidget(item)
                if widget:
                    thumb = widget.findChild(QLabel, "thumbnail")
                    if thumb and thumb.property("cover_url") == url:
                        thumb.setPixmap(scaled)
                        thumb.setStyleSheet("background: transparent; border-radius: 8px;")

    def _on_type_changed(self, index):
        """切换搜索类型"""
        self._search_type = "user" if index == 1 else "video"
        self.search_edit.setPlaceholderText("搜索UP主名称..." if self._search_type == "user" else "搜索B站视频...")
        # 切换时清空结果
        self._clear_list_widgets()
        self._current_results = []
        # 排序框仅对视频搜索有意义
        self.sort_combo.setEnabled(self._search_type == "video")

    def _on_search(self, keyword: str):
        if not keyword:
            return
        self._current_keyword = keyword
        self._current_order = self.sort_combo.currentText()
        self._current_page = 1
        self._current_user_mid = 0  # 重置
        if self._search_type == "user":
            self.window()._do_user_search(keyword, 1)
        else:
            self.window()._do_search(keyword, 1, self._current_order)

    def set_user_results(self, result: dict):
        """设置UP主搜索结果"""
        users = result.get('users', [])
        self._current_results = users  # 同步结果列表，供翻页守卫使用
        self._total = result.get('total', 0)
        self._has_more = result.get('has_more', False)
        self._update_page_label()
        self._render_user_results(users)

    def _render_user_results(self, users: list):
        """渲染UP主搜索结果"""
        try:
            self._clear_list_widgets()
            if not users:
                item = QListWidgetItem(self.result_list)
                item.setFlags(Qt.NoItemFlags)
                widget = QLabel("未找到相关UP主")
                widget.setAlignment(Qt.AlignCenter)
                empty_color = "#AAAAAA" if isDarkTheme() else "gray"
                widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
                item.setSizeHint(widget.sizeHint())
                self.result_list.addItem(item)
                self.result_list.setItemWidget(item, widget)
                return

            for user in users:
                try:
                    item_widget = self._create_user_item(user)
                    item = QListWidgetItem(self.result_list)
                    item.setData(Qt.UserRole, user)
                    item.setSizeHint(item_widget.sizeHint())
                    self.result_list.addItem(item)
                    self.result_list.setItemWidget(item, item_widget)
                except Exception as e:
                    logger.warning(f"渲染UP主结果项失败: {e}")
        except Exception as e:
            logger.error(f"渲染UP主结果异常: {e}", exc_info=True)

    def _create_user_item(self, user: dict) -> QWidget:
        """创建UP主搜索结果项"""
        item = SimpleCardWidget(self)
        item.setFixedHeight(80)
        layout = QHBoxLayout(item)
        layout.setContentsMargins(12, 8, 12, 8)

        # 头像
        avatar = QLabel("👤")
        avatar.setObjectName("avatar")  # 便于加载完成后精确查找
        avatar.setFixedSize(QSize(50, 50))
        avatar.setAlignment(Qt.AlignCenter)
        avatar_bg = "#3C3C3C" if isDarkTheme() else "#E8ECF4"
        avatar.setStyleSheet(f"background: {avatar_bg}; border-radius: 25px; font-size: 24px;")
        layout.addWidget(avatar)

        # 异步加载头像
        face_url = user.get('face', '')
        if face_url:
            # 规范化 URL（与 _CoverLoader 内部一致）
            norm_url = face_url
            if norm_url.startswith("//"):
                norm_url = "https:" + norm_url
            elif norm_url.startswith("http://"):
                norm_url = "https://" + norm_url[7:]

            # 用动态属性记录该头像对应的 URL
            avatar.setProperty("cover_url", norm_url)

            if not hasattr(self, '_cover_cache'):
                self._cover_cache = {}
            if not hasattr(self, '_cover_loaders'):
                self._cover_loaders = []
            if norm_url not in self._cover_cache:
                self._cover_cache[norm_url] = None
                loader = _CoverLoader(face_url, avatar, self)
                loader.loaded.connect(lambda url, pix: self._on_avatar_loaded(url, pix))
                self._cover_loaders.append(loader)
                loader.start()

        # 信息区
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        name_label = StrongBodyLabel(user.get('name', '未知'))
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label)

        fans = user.get('fans', 0)
        videos = user.get('videos', 0)
        sign = user.get('sign', '') or ''
        meta_text = f"粉丝 {fans:,}  ·  投稿 {videos} 个"
        if user.get('is_live'):
            meta_text += "  ·  🔴直播中"
        meta = CaptionLabel(meta_text)
        info_layout.addWidget(meta)
        if sign:
            sign_label = CaptionLabel(f"签名: {sign[:40]}")
            sign_color = "#AAAAAA" if isDarkTheme() else "gray"
            sign_label.setStyleSheet(f"color: {sign_color};")
            info_layout.addWidget(sign_label)
        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        # 查看投稿按钮
        view_btn = PrimaryPushButton("查看投稿")
        view_btn.setFixedWidth(90)
        mid = user.get('mid', 0)
        view_btn.clicked.connect(lambda: self._load_user_videos(mid))
        layout.addWidget(view_btn)
        return item

    def _on_avatar_loaded(self, url: str, pix: QPixmap):
        """头像加载完成回调：只更新 URL 匹配的头像"""
        if pix and not pix.isNull():
            self._cover_cache[url] = pix
            scaled = pix.scaled(50, 50, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            for i in range(self.result_list.count()):
                item = self.result_list.item(i)
                widget = self.result_list.itemWidget(item)
                if widget:
                    avatar = widget.findChild(QLabel, "avatar")
                    if avatar and avatar.property("cover_url") == url:
                        avatar.setPixmap(scaled)
                        avatar.setStyleSheet("background: transparent; border-radius: 25px;")

    def _load_user_videos(self, mid: int):
        """加载UP主投稿视频"""
        self._current_user_mid = mid
        self._current_page = 1
        self.set_loading()
        self.window()._do_load_user_videos(mid, 1)

    def set_user_videos(self, result):
        """设置UP主投稿视频结果（保持 user_videos 模式以支持分页）"""
        self._search_type = "user_videos"
        self.set_results(result)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        video = item.data(Qt.UserRole)
        if video:
            self._show_video_detail(video)

    def _show_video_detail(self, video: VideoInfo):
        from .video_detail_dialog import VideoDetailDialog
        dialog = VideoDetailDialog(video, self)
        dialog.exec()

    def _on_download_clicked(self, video: VideoInfo, media_type: MediaType = MediaType.VIDEO):
        # 视频类型：弹出详情对话框，支持多分P选择（对话框会自动异步获取分P信息）
        if media_type == MediaType.VIDEO:
            from .video_detail_dialog import VideoDetailDialog
            dialog = VideoDetailDialog(video, self)
            dialog.exec()
            return

        # 音频类型：保持直接下载行为
        quality_val = cfg().get(cfg().video_quality)
        # 将配置中的 VideoQuality 枚举转换为 models.VideoQuality
        if hasattr(quality_val, 'value'):
            quality_enum = ModelVideoQuality(quality_val.value)
        else:
            quality_enum = ModelVideoQuality(quality_val)
        task = DownloadTask(
            video_info=video,
            episode=video.episodes[0] if video.episodes else None,
            download_type=media_type,
            quality=quality_enum,
        )
        self.window().download_task_added.emit(task)

    def _prev_page(self):
        if self._current_page <= 1:
            return
        # user_videos 模式仅依赖 mid；其他模式需要 keyword
        if self._search_type == "user_videos":
            if not self._current_user_mid:
                return
        elif not self._current_keyword:
            return
        # time.sleep(1)
        self._current_page -= 1
        self._dispatch_page()

    def _next_page(self):
        # user_videos 模式仅依赖 mid；其他模式需要 keyword
        if self._search_type == "user_videos":
            if not self._current_user_mid:
                return
        elif not self._current_keyword:
            return
        # 有更多或有足够结果即可翻页
        if self._search_type == "user_videos":
            if not self._has_more and len(self._current_results) < 30:
                return
        else:  # video / user
            if not self._has_more and len(self._current_results) < 20:
                return
        # time.sleep(1)
        self._current_page += 1
        self._dispatch_page()

    def _dispatch_page(self):
        """根据当前搜索类型分发到对应的加载方法"""
        if self._search_type == "user_videos" and self._current_user_mid:
            self.window()._do_load_user_videos(self._current_user_mid, self._current_page)
        elif self._search_type == "user":
            self.window()._do_user_search(self._current_keyword, self._current_page)
        else:  # video
            self.window()._do_search(self._current_keyword, self._current_page, self._current_order)
        self._update_page_label()

    def _update_page_label(self):
        self.page_label.setText(f"第 {self._current_page} 页")

    def update_login_status(self, is_logged_in: bool):
        pass


class FavoritesPage(QWidget):
    """收藏夹页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folders = []
        self._current_videos = []
        self._current_folder_id = 0
        self._current_page = 1
        self._loaded = False
        self._fav_worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        title = SubtitleLabel("我的收藏")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.refresh_btn = ToolButton(FIcon.SYNC)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(self.load_folders)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        # 收藏夹选择
        folder_row = QHBoxLayout()
        folder_row.addWidget(BodyLabel("收藏夹:"))
        self.folder_combo = ComboBox()
        self.folder_combo.setMinimumWidth(200)
        self.folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        folder_row.addWidget(self.folder_combo, 1)
        layout.addLayout(folder_row)

        # 视频列表
        self.result_list = QListWidget()
        self.result_list.setStyleSheet("""
            QListWidget { border: none; background: transparent; outline: none; }
            QListWidget::item { padding: 4px; margin: 2px 0; }
        """)
        layout.addWidget(self.result_list)

        # 分页
        page_layout = QHBoxLayout()
        page_layout.addStretch()
        self.prev_btn = ToolButton(FIcon.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._prev_page)
        self.page_label = BodyLabel("第 1 页")
        self.next_btn = ToolButton(FIcon.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self.prev_btn)
        page_layout.addWidget(self.page_label)
        page_layout.addWidget(self.next_btn)
        page_layout.addStretch()
        layout.addLayout(page_layout)

    def showEvent(self, event):
        """页面显示时自动加载"""
        if not self._loaded and cfg().get(cfg().is_login):
            self._loaded = True
            self.load_folders()
        super().showEvent(event)

    def load_folders(self):
        """加载收藏夹列表"""
        if not cfg().get(cfg().is_login):
            MessageBox("提示", "请先登录B站账号", self).exec()
            return

        # 停止之前的 worker 线程
        if self._fav_worker and self._fav_worker.isRunning():
            self._fav_worker.quit()
            self._fav_worker.wait(2000)

        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItem("加载中...")
        self.folder_combo.blockSignals(False)

        main_win = self.window()
        self._fav_worker = FavoritesWorker(main_win.bilibili_client, mode="folders")
        self._fav_worker.folders_loaded.connect(self._on_folders_loaded)
        self._fav_worker.error.connect(self._on_fav_error)
        self._fav_worker.start()

    def _on_folders_loaded(self, folders):
        self._folders = folders
        # 暂存当前选中的文件夹 ID，避免 combo box 更新时触发递归
        old_folder_id = self._current_folder_id
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        if not folders:
            self.folder_combo.addItem("暂无收藏夹")
            self._current_folder_id = 0
            self.folder_combo.blockSignals(False)
            return
        for f in folders:
            self.folder_combo.addItem(f"{f['title']} ({f['media_count']})")
        # 尝试恢复之前选中的文件夹，否则选第一个
        target_idx = 0
        for i, f in enumerate(folders):
            if f["id"] == old_folder_id:
                target_idx = i
                break
        self._current_folder_id = folders[target_idx]["id"]
        self._current_page = 1
        self.folder_combo.setCurrentIndex(target_idx)
        self.folder_combo.blockSignals(False)
        if self._current_folder_id:
            self.load_videos()

    def _on_folder_changed(self, index):
        if index < 0 or index >= len(self._folders):
            return
        self._current_folder_id = self._folders[index]["id"]
        self._current_page = 1
        self.load_videos()

    def load_videos(self):
        """加载收藏夹视频"""
        if not self._current_folder_id:
            return

        # 停止之前的 worker 线程
        if self._fav_worker and self._fav_worker.isRunning():
            self._fav_worker.quit()
            self._fav_worker.wait(2000)

        self._clear_list_widgets()
        item = QListWidgetItem(self.result_list)
        item.setFlags(Qt.NoItemFlags)
        widget = QLabel("加载中...")
        widget.setAlignment(Qt.AlignCenter)
        empty_color = "#AAAAAA" if isDarkTheme() else "gray"
        widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
        item.setSizeHint(widget.sizeHint())
        self.result_list.addItem(item)
        self.result_list.setItemWidget(item, widget)

        main_win = self.window()
        self._fav_worker = FavoritesWorker(
            main_win.bilibili_client, mode="videos",
            media_id=self._current_folder_id, page=self._current_page
        )
        self._fav_worker.videos_loaded.connect(self._on_videos_loaded)
        self._fav_worker.error.connect(self._on_fav_error)
        self._fav_worker.start()

    def _on_videos_loaded(self, videos, total):
        self._current_videos = videos
        self._render_videos()

    def _on_fav_error(self, msg):
        self._clear_list_widgets()
        item = QListWidgetItem(self.result_list)
        item.setFlags(Qt.NoItemFlags)
        widget = QLabel(f"加载失败: {msg}")
        widget.setAlignment(Qt.AlignCenter)
        widget.setStyleSheet("color: red; padding: 40px;")
        item.setSizeHint(widget.sizeHint())
        self.result_list.addItem(item)
        self.result_list.setItemWidget(item, widget)

    def _clear_list_widgets(self):
        try:
            for i in range(self.result_list.count()):
                item = self.result_list.item(0)
                widget = self.result_list.itemWidget(item)
                if widget:
                    self.result_list.removeItemWidget(item)
                    widget.deleteLater()
                self.result_list.takeItem(0)
        except Exception as e:
            logger.warning(f"清理列表控件异常: {e}")

    def _render_videos(self):
        try:
            self._clear_list_widgets()
            if not self._current_videos:
                item = QListWidgetItem(self.result_list)
                item.setFlags(Qt.NoItemFlags)
                widget = QLabel("暂无收藏视频")
                widget.setAlignment(Qt.AlignCenter)
                empty_color = "#AAAAAA" if isDarkTheme() else "gray"
                widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
                item.setSizeHint(widget.sizeHint())
                self.result_list.addItem(item)
                self.result_list.setItemWidget(item, widget)
                return

            for video in self._current_videos:
                try:
                    item_widget = self._create_video_item(video)
                    item = QListWidgetItem(self.result_list)
                    item.setData(Qt.UserRole, video)
                    item.setSizeHint(item_widget.sizeHint())
                    self.result_list.addItem(item)
                    self.result_list.setItemWidget(item, item_widget)
                except Exception as e:
                    logger.warning(f"渲染收藏视频项失败: {e}")
        except Exception as e:
            logger.error(f"渲染收藏视频异常: {e}", exc_info=True)

    def _create_video_item(self, video: VideoInfo) -> QWidget:
        card = SimpleCardWidget(self)
        card.setFixedHeight(90)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)

        # 封面图：优先异步加载网络封面，无封面时显示占位符
        thumbnail = QLabel("🎬")
        thumbnail.setObjectName("thumbnail")  # 便于加载完成后精确查找
        thumbnail.setFixedSize(QSize(100, 60))
        thumbnail.setAlignment(Qt.AlignCenter)
        thumb_bg = "#3C3C3C" if isDarkTheme() else "#E8ECF4"
        thumbnail.setStyleSheet(f"background: {thumb_bg}; border-radius: 8px; font-size: 32px;")
        layout.addWidget(thumbnail)

        # 异步加载封面图
        cover_url = getattr(video, 'cover_url', '') or ''
        if cover_url:
            norm_url = cover_url
            if norm_url.startswith("//"):
                norm_url = "https:" + norm_url
            elif norm_url.startswith("http://"):
                norm_url = "https://" + norm_url[7:]

            thumbnail.setProperty("cover_url", norm_url)

            if not hasattr(self, '_cover_cache'):
                self._cover_cache = {}
            if not hasattr(self, '_cover_loaders'):
                self._cover_loaders = []

            if norm_url in self._cover_cache:
                pix = self._cover_cache[norm_url]
                if pix and not pix.isNull():
                    thumbnail.setPixmap(pix.scaled(100, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                    thumbnail.setStyleSheet("background: transparent; border-radius: 8px;")
            else:
                self._cover_cache[norm_url] = None
                loader = _CoverLoader(cover_url, thumbnail, self)
                loader.loaded.connect(lambda url, pix: self._on_cover_loaded(url, pix))
                self._cover_loaders.append(loader)
                loader.start()

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_text = (video.title or "未知标题")[:45]
        title = BodyLabel(title_text)
        title.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(title)
        views = video.views or 0
        meta = CaptionLabel(f"👁 {views:,}  ·  👤 {video.owner_name or '未知'}")
        info_layout.addWidget(meta)
        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)
        dl_btn = PrimaryPushButton("下载视频")
        dl_btn.setFixedWidth(90)
        dl_btn.clicked.connect(lambda: self._on_download_clicked(video, MediaType.VIDEO))
        btn_layout.addWidget(dl_btn)
        audio_btn = PushButton("下载音频")
        audio_btn.setFixedWidth(90)
        audio_btn.clicked.connect(lambda: self._on_download_clicked(video, MediaType.AUDIO))
        btn_layout.addWidget(audio_btn)
        layout.addLayout(btn_layout)
        return card

    def _on_cover_loaded(self, url: str, pix: QPixmap):
        """封面图加载完成回调：只更新 URL 匹配的缩略图"""
        if pix and not pix.isNull():
            self._cover_cache[url] = pix
            scaled = pix.scaled(100, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            for i in range(self.result_list.count()):
                item = self.result_list.item(i)
                widget = self.result_list.itemWidget(item)
                if widget:
                    thumb = widget.findChild(QLabel, "thumbnail")
                    if thumb and thumb.property("cover_url") == url:
                        thumb.setPixmap(scaled)
                        thumb.setStyleSheet("background: transparent; border-radius: 8px;")

    def _on_download_clicked(self, video: VideoInfo, media_type: MediaType = MediaType.VIDEO):
        # 视频类型：弹出详情对话框，支持多分P选择（对话框会自动异步获取分P信息）
        if media_type == MediaType.VIDEO:
            from .video_detail_dialog import VideoDetailDialog
            dialog = VideoDetailDialog(video, self)
            dialog.exec()
            return

        # 音频类型：保持直接下载行为
        quality_val = cfg().get(cfg().video_quality)
        if hasattr(quality_val, 'value'):
            quality_enum = ModelVideoQuality(quality_val.value)
        else:
            quality_enum = ModelVideoQuality(quality_val)
        task = DownloadTask(
            video_info=video,
            episode=video.episodes[0] if video.episodes else None,
            download_type=media_type,
            quality=quality_enum,
        )
        self.window().download_task_added.emit(task)

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self.page_label.setText(f"第 {self._current_page} 页")
            self.load_videos()

    def _next_page(self):
        self._current_page += 1
        self.page_label.setText(f"第 {self._current_page} 页")
        self.load_videos()

    def update_login_status(self, is_logged_in: bool):
        if is_logged_in and not self._loaded:
            self._loaded = True
            self.load_folders()


class MusicFolderPage(QWidget):
    """音乐收藏夹页面：管理本地音频收藏夹分组"""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            from ..database import get_database
            self._db = get_database()
        except Exception:
            self._db = None
        self._current_folder_id: int = -1
        self._setup_ui()
        self._load_folders()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)

        # 顶部标题栏
        header = QHBoxLayout()
        title = SubtitleLabel("🎶 音乐收藏夹")
        header.addWidget(title)
        header.addStretch()

        self.create_btn = PushButton(FIcon.ADD, "新建收藏夹", self)
        self.create_btn.clicked.connect(self._create_folder)
        header.addWidget(self.create_btn)

        layout.addLayout(header)

        # 主内容区：左侧收藏夹列表 + 右侧歌曲列表
        splitter = QSplitter(Qt.Horizontal, self)

        # === 左侧：收藏夹列表 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(BodyLabel("收藏夹列表"))

        self.folder_list = QListWidget(self)
        self.folder_list.setAlternatingRowColors(True)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._folder_context_menu)
        self.folder_list.itemClicked.connect(self._on_folder_clicked)
        left_layout.addWidget(self.folder_list)
        splitter.addWidget(left_widget)

        # === 右侧：歌曲列表 ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_header = QHBoxLayout()
        self.folder_title = StrongBodyLabel("请选择收藏夹")
        right_header.addWidget(self.folder_title)
        right_header.addStretch()

        self.add_file_btn = PushButton(FIcon.FOLDER_ADD, "添加音频", self)
        self.add_file_btn.setEnabled(False)
        self.add_file_btn.clicked.connect(self._add_files_to_folder)
        right_header.addWidget(self.add_file_btn)

        right_layout.addLayout(right_header)

        self.song_list = QListWidget(self)
        self.song_list.setAlternatingRowColors(True)
        self.song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.song_list.customContextMenuRequested.connect(self._song_context_menu)
        self.song_list.itemDoubleClicked.connect(self._play_song)
        right_layout.addWidget(self.song_list)
        splitter.addWidget(right_widget)

        splitter.setSizes([280, 520])
        layout.addWidget(splitter, 1)

    def _load_folders(self):
        """加载收藏夹列表"""
        self.folder_list.clear()
        if not self._db:
            return
        folders = self._db.get_music_folders()
        if not folders:
            item = QListWidgetItem("📂 暂无收藏夹，点击「新建」创建")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.folder_list.addItem(item)
            return
        for f in folders:
            name = f.get('name', '未命名')
            count = f.get('item_count', 0)
            color = f.get('cover_color', '#667EEA')
            item = QListWidgetItem(f"🎵 {name}  ({count}首)")
            item.setData(Qt.UserRole, f)
            item.setToolTip(f"创建时间: {f.get('created_at', '')}\n描述: {f.get('description', '无')}")
            self.folder_list.addItem(item)

    def _on_folder_clicked(self, item):
        """点击收藏夹，加载歌曲列表"""
        data = item.data(Qt.UserRole)
        if not data:
            return
        self._current_folder_id = data.get('id', -1)
        self.folder_title.setText(f"🎵 {data.get('name', '')}")
        self.add_file_btn.setEnabled(True)
        self._load_songs()

    def _load_songs(self):
        """加载收藏夹内歌曲"""
        self.song_list.clear()
        if self._current_folder_id < 0 or not self._db:
            return
        items = self._db.get_music_folder_items(self._current_folder_id)
        if not items:
            item = QListWidgetItem("📭 暂无歌曲，点击「添加音频」导入")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.song_list.addItem(item)
            return
        for s in items:
            name = s.get('title') or s.get('file_name', '未知')
            artist = s.get('artist', '')
            text = f"♪ {name}" + (f" - {artist}" if artist else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s)
            item.setToolTip(s.get('file_path', ''))
            self.song_list.addItem(item)

    def _create_folder(self):
        """创建新收藏夹"""
        name, ok = QInputDialog.getText(self, "新建收藏夹", "收藏夹名称:")
        if not ok or not name.strip():
            return
        fid = self._db.create_music_folder(name.strip())
        if fid > 0:
            from qfluentwidgets import InfoBar
            InfoBar.success("创建成功", f"收藏夹「{name.strip()}」已创建",
                            duration=2500, parent=self)
            self._load_folders()

    def _folder_context_menu(self, point):
        """收藏夹右键菜单"""
        item = self.folder_list.itemAt(point)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        act_rename = menu.addAction("✏️ 重命名")
        act_delete = menu.addAction("🗑 删除收藏夹")
        action = menu.exec(self.folder_list.mapToGlobal(point))
        if action == act_rename:
            new_name, ok = QInputDialog.getText(
                self, "重命名", "新名称:", text=data.get('name', '')
            )
            if ok and new_name.strip():
                self._db.rename_music_folder(data['id'], new_name.strip())
                self._load_folders()
        elif action == act_delete:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定删除收藏夹「{data.get('name')}」吗？\n收藏夹内的歌曲记录将被清除（文件不会被删除）。",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._db.delete_music_folder(data['id'])
                self._current_folder_id = -1
                self.folder_title.setText("请选择收藏夹")
                self.song_list.clear()
                self.add_file_btn.setEnabled(False)
                self._load_folders()

    def _add_files_to_folder(self):
        """添加音频文件到当前收藏夹"""
        if self._current_folder_id < 0:
            return
        from .audio_player_page import _extract_metadata, AUDIO_EXTENSIONS
        # 构建文件过滤器
        ext_filter = " ".join(f"*{e}" for e in AUDIO_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频文件", "",
            f"音频文件 ({ext_filter});;所有文件 (*.*)"
        )
        if not files:
            return
        count = 0
        for path in files:
            # 跳过不支持的格式
            if not path.lower().endswith(AUDIO_EXTENSIONS):
                continue
            meta = _extract_metadata(path)
            self._db.add_to_music_folder(
                self._current_folder_id, path,
                os.path.basename(path),
                meta.get('title', ''),
                meta.get('artist', ''),
                meta.get('album', ''),
                int(meta.get('duration', 0))
            )
            count += 1
        from qfluentwidgets import InfoBar
        if count > 0:
            InfoBar.success("添加成功", f"已添加 {count} 首歌曲",
                            duration=2500, parent=self)
        else:
            InfoBar.warning("未添加", "选择的文件中没有支持的音频格式",
                            duration=2500, parent=self)
        self._load_songs()
        self._load_folders()

    def _song_context_menu(self, point):
        """歌曲右键菜单"""
        item = self.song_list.itemAt(point)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        act_play = menu.addAction("▶️ 播放")
        act_remove = menu.addAction("💔 从收藏夹移除")
        action = menu.exec(self.song_list.mapToGlobal(point))
        if action == act_play:
            self._play_song(item)
        elif action == act_remove:
            self._db.remove_from_music_folder(self._current_folder_id, data.get('file_path', ''))
            self._load_songs()
            self._load_folders()

    def _play_song(self, item):
        """双击播放歌曲"""
        data = item.data(Qt.UserRole)
        if not data:
            return
        file_path = data.get('file_path', '')
        if not os.path.isfile(file_path):
            from qfluentwidgets import InfoBar
            InfoBar.warning("文件不存在", file_path, duration=3000, parent=self)
            return
        # 切换到音频播放页并播放
        window = self.window()
        if window and hasattr(window, 'audio_player_page'):
            player = window.audio_player_page
            # 确保歌曲在播放列表中
            if file_path not in player._playlist:
                player._playlist.insert(0, file_path)
                player._populate_list()
            idx = player._playlist.index(file_path)
            player._play_index(idx)
            window.switchTo(window.audio_player_page)


class DownloadPage(QWidget):
    """下载管理页面（主窗口 _dl_refresh_timer 负责进度刷新，本页定时器仅用于检测完成切换）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(1000)  # 1s 检测任务完成切换
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._had_active_tasks = False  # 上次刷新时是否有进行中的任务
        self._setup_ui()

    def showEvent(self, event):
        """页面显示时启动自动刷新"""
        self._auto_refresh_timer.start()
        self.refresh_tasks()
        super().showEvent(event)

    def hideEvent(self, event):
        """页面隐藏时停止自动刷新，节省 CPU"""
        self._auto_refresh_timer.stop()
        super().hideEvent(event)

    def _auto_refresh(self):
        """定时检测任务完成状态（进度刷新由主窗口 _dl_refresh_timer 负责）"""
        try:
            window = self.window()
            if window and hasattr(window, 'downloader'):
                tasks = window.downloader.get_tasks()
                has_active = any(
                    t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING)
                    for t in tasks
                )
                # 仅在任务数量变化时刷新（处理任务增删）
                if has_active or self.task_list.count() != len(tasks):
                    self.refresh_tasks()

                self._had_active_tasks = has_active
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        toolbar = QHBoxLayout()
        title = SubtitleLabel("📥 下载管理")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.pause_all_btn = ToolButton(FIcon.PAUSE)
        self.pause_all_btn.setToolTip("暂停全部")
        self.pause_all_btn.clicked.connect(self._pause_all)
        toolbar.addWidget(self.pause_all_btn)

        self.resume_all_btn = ToolButton(FIcon.SYNC)
        self.resume_all_btn.setToolTip("恢复全部")
        self.resume_all_btn.clicked.connect(self._resume_all)
        toolbar.addWidget(self.resume_all_btn)

        self.clear_btn = ToolButton(FIcon.DELETE)
        self.clear_btn.setToolTip("清除已完成")
        self.clear_btn.clicked.connect(self._clear_completed)
        toolbar.addWidget(self.clear_btn)

        self.clear_all_btn = PushButton("清空全部")
        self.clear_all_btn.setFixedHeight(32)
        self.clear_all_btn.setToolTip("清空所有下载任务（不会删除已下载文件）")
        self.clear_all_btn.clicked.connect(self._clear_all)
        toolbar.addWidget(self.clear_all_btn)

        layout.addLayout(toolbar)

        self.task_list = QListWidget()
        self.task_list.setStyleSheet("""
            QListWidget { border: none; background: transparent; outline: none; }
            QListWidget::item { padding: 4px; margin: 2px 0; }
        """)
        layout.addWidget(self.task_list)

    def refresh_tasks(self):
        window = self.window()
        if not window or not hasattr(window, 'downloader'):
            return
        tasks = window.downloader.get_tasks()

        # 增量更新：只更新变化的 item，避免全量重建
        existing_ids = set()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_id = item.data(Qt.UserRole)
            if task_id:
                existing_ids.add(task_id)

        current_ids = {t.task_id for t in tasks}

        # 有任务增删时全量重建
        if existing_ids != current_ids:
            # 断开信号，避免重建过程中触发不必要的选中变化
            self.task_list.blockSignals(True)
            # 清理旧 widget
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                widget = self.task_list.itemWidget(item)
                if widget:
                    self.task_list.removeItemWidget(item)
                    widget.deleteLater()
            self.task_list.clear()

            if not tasks:
                item = QListWidgetItem(self.task_list)
                item.setFlags(Qt.NoItemFlags)
                widget = QLabel("暂无下载任务")
                widget.setAlignment(Qt.AlignCenter)
                empty_color = "#AAAAAA" if isDarkTheme() else "gray"
                widget.setStyleSheet(f"color: {empty_color}; padding: 40px;")
                item.setSizeHint(widget.sizeHint())
                self.task_list.addItem(item)
                self.task_list.setItemWidget(item, widget)
                return

            for task in tasks:
                item_widget = self._create_task_item(task)
                item = QListWidgetItem(self.task_list)
                item.setData(Qt.UserRole, task.task_id)
                item.setSizeHint(item_widget.sizeHint())
                self.task_list.addItem(item)
                self.task_list.setItemWidget(item, item_widget)
            # 恢复信号
            self.task_list.blockSignals(False)
        else:
            # 只更新已有 item 的内容
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                task_id = item.data(Qt.UserRole)
                if not task_id:
                    continue
                task = next((t for t in tasks if t.task_id == task_id), None)
                if not task:
                    continue
                widget = self.task_list.itemWidget(item)
                if widget:
                    self._update_task_item(widget, task)

    def _create_task_item(self, task: DownloadTask) -> QWidget:
        card = SimpleCardWidget(self)
        card.setFixedHeight(70)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)

        status_label = QLabel(self._get_status_icon(task))
        status_label.setFixedWidth(30)
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(status_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)

        title_text = task.video_info.title[:40] if task.video_info else "未知"
        if task.episode and task.episode.part:
            title_text += f" - {task.episode.part}"
        name_label = BodyLabel(title_text)
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label)

        progress_bar = QProgressBar()
        progress_bar.setFixedHeight(6)
        progress_bar.setTextVisible(False)
        progress_val = int(max(0, task.progress) * 100)
        progress_bar.setValue(progress_val)
        info_layout.addWidget(progress_bar)

        # 进度文本 + 速度 + 画质
        quality_str = ""
        if task.status == DownloadStatus.COMPLETED and task.actual_quality > 0:
            quality_str = f"  ·  🎬 {_quality_name(task.actual_quality)}"

        if task.status == DownloadStatus.COMPLETED:
            progress_text = f"✅ 下载完成{quality_str}"
        elif task.status == DownloadStatus.FAILED:
            progress_text = f"❌ 失败: {task.error_message}"
        elif task.status == DownloadStatus.DOWNLOADING:
            pct = int(max(0, task.progress) * 100)
            speed_str = ""
            if task.download_speed > 0:
                if task.download_speed >= 1024 * 1024:
                    speed_str = f"  {task.download_speed / 1024 / 1024:.1f} MB/s"
                elif task.download_speed >= 1024:
                    speed_str = f"  {task.download_speed / 1024:.0f} KB/s"
            size_str = ""
            if task.total_size > 0:
                size_str = f"  {task.downloaded_size / 1024 / 1024:.1f}/{task.total_size / 1024 / 1024:.1f} MB"
            progress_text = f"{pct}%{speed_str}{size_str}"
        else:
            progress_text = f"{int(max(0, task.progress) * 100)}%"
        progress_label = CaptionLabel(progress_text)
        info_layout.addWidget(progress_label)
        layout.addLayout(info_layout, 1)

        btn_layout = QVBoxLayout()
        if task.status == DownloadStatus.DOWNLOADING:
            pause_btn = ToolButton(FIcon.PAUSE)
            pause_btn.setToolTip("暂停")
            pause_btn.clicked.connect(lambda: self._pause_task(task.task_id))
            btn_layout.addWidget(pause_btn)
        elif task.status == DownloadStatus.PAUSED:
            resume_btn = ToolButton(FIcon.SYNC)
            resume_btn.setToolTip("恢复")
            resume_btn.clicked.connect(lambda: self._resume_task(task.task_id))
            btn_layout.addWidget(resume_btn)
        elif task.status == DownloadStatus.COMPLETED:
            folder_btn = ToolButton(FIcon.FOLDER)
            folder_btn.setToolTip("打开文件")
            folder_btn.clicked.connect(lambda: self._open_file(task))
            btn_layout.addWidget(folder_btn)

        delete_btn = ToolButton(FIcon.CLOSE)
        delete_btn.setToolTip("删除")
        delete_btn.clicked.connect(lambda: self._remove_task(task.task_id))
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)
        return card

    def _update_task_item(self, card: QWidget, task: DownloadTask):
        """增量更新已有任务卡片（避免全量重建）"""
        try:
            layout = card.layout()
            # info_layout 是第2个元素（index=1）
            info_layout = layout.itemAt(1).layout()
            # status_label 是第1个元素
            status_label = layout.itemAt(0).widget()
            status_label.setText(self._get_status_icon(task))

            # name_label (0), progress_bar (1), progress_label (2)
            progress_bar = info_layout.itemAt(1).widget()
            progress_val = int(max(0, task.progress) * 100)
            progress_bar.setValue(progress_val)

            progress_label = info_layout.itemAt(2).widget()
            quality_str = ""
            if task.status == DownloadStatus.COMPLETED and task.actual_quality > 0:
                quality_str = f"  ·  🎬 {_quality_name(task.actual_quality)}"

            if task.status == DownloadStatus.COMPLETED:
                progress_label.setText(f"✅ 下载完成{quality_str}")
            elif task.status == DownloadStatus.FAILED:
                progress_label.setText(f"❌ 失败: {task.error_message}")
            elif task.status == DownloadStatus.DOWNLOADING:
                pct = int(max(0, task.progress) * 100)
                speed_str = ""
                if task.download_speed > 0:
                    if task.download_speed >= 1024 * 1024:
                        speed_str = f"  {task.download_speed / 1024 / 1024:.1f} MB/s"
                    elif task.download_speed >= 1024:
                        speed_str = f"  {task.download_speed / 1024:.0f} KB/s"
                size_str = ""
                if task.total_size > 0:
                    size_str = f"  {task.downloaded_size / 1024 / 1024:.1f}/{task.total_size / 1024 / 1024:.1f} MB"
                progress_label.setText(f"{pct}%{speed_str}{size_str}")
            else:
                progress_label.setText(f"{int(max(0, task.progress) * 100)}%")
        except Exception as e:
            logger.debug(f"增量更新任务卡片失败: {e}")

    def _get_status_icon(self, task: DownloadTask) -> str:
        icons = {
            DownloadStatus.PENDING: "⏳",
            DownloadStatus.DOWNLOADING: "⬇",
            DownloadStatus.PAUSED: "⏸",
            DownloadStatus.COMPLETED: "✅",
            DownloadStatus.FAILED: "❌",
        }
        return icons.get(task.status, "❓")

    def _pause_all(self):
        self.window().downloader.pause_all()
        self.refresh_tasks()

    def _resume_all(self):
        self.window().downloader.resume_all()
        self.refresh_tasks()

    def _clear_completed(self):
        window = self.window()
        for task in window.downloader.get_tasks():
            if task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED):
                window.downloader.remove_task(task.task_id)
        self.refresh_tasks()

    def _clear_all(self):
        """清空全部下载任务（带确认对话框）"""
        window = self.window()
        tasks = window.downloader.get_tasks()
        if not tasks:
            InfoBar.info("提示", "下载列表为空", duration=2000, parent=self)
            return
        # 弹出确认对话框
        msg_box = MessageBox(
            "清空全部下载记录",
            f"确定要清空全部 {len(tasks)} 个下载任务吗？\n注意：正在下载的任务将被取消，已下载的文件不会被删除。",
            self
        )
        if msg_box.exec():
            # 取消所有进行中的任务
            for task in tasks:
                if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING):
                    window.downloader.cancel_task(task.task_id)
            # 清空任务列表
            for task in tasks:
                window.downloader.remove_task(task.task_id)
            self.refresh_tasks()
            InfoBar.success("已清空", "下载列表已清空", duration=2000, parent=self)

    def _pause_task(self, task_id: str):
        self.window().downloader.pause_task(task_id)
        self.refresh_tasks()

    def _resume_task(self, task_id: str):
        self.window().downloader.resume_task(task_id)
        self.refresh_tasks()

    def _remove_task(self, task_id: str):
        self.window().downloader.remove_task(task_id)
        self.refresh_tasks()

    def _open_file(self, task: DownloadTask):
        if task.file_path and os.path.exists(task.file_path):
            import subprocess
            subprocess.Popen(["explorer", "/select,", task.file_path])


class SettingsPage(QWidget):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent;")
        self._setup_ui()

    def _setup_ui(self):
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        container = QWidget()
        container.setObjectName("settingsContainer")
        container.setStyleSheet("QWidget#settingsContainer { background: transparent; }")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(20)

        # 外观
        general_card = SimpleCardWidget(container)
        general_layout = QVBoxLayout(general_card)
        general_title = SubtitleLabel("🎨 外观")
        general_layout.addWidget(general_title)

        theme_row = QHBoxLayout()
        theme_row.addWidget(BodyLabel("主题"))
        theme_row.addStretch()
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["浅色", "深色", "跟随系统"])
        theme_map = {Theme.LIGHT: 0, Theme.DARK: 1, Theme.AUTO: 2}
        self.theme_combo.setCurrentIndex(theme_map.get(cfg().get(cfg().theme), 2))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        general_layout.addLayout(theme_row)

        mica_row = QHBoxLayout()
        mica_row.addWidget(BodyLabel("云母效果"))
        mica_row.addStretch()
        self.mica_check = CheckBox()
        self.mica_check.setChecked(cfg().get(cfg().mica_effect))
        self.mica_check.toggled.connect(lambda c: cfg().set(cfg().mica_effect, c))
        mica_row.addWidget(self.mica_check)
        general_layout.addLayout(mica_row)
        layout.addWidget(general_card)

        # 下载设置
        download_card = SimpleCardWidget(container)
        download_layout = QVBoxLayout(download_card)
        download_title = SubtitleLabel("📥 下载设置")
        download_layout.addWidget(download_title)

        path_row = QHBoxLayout()
        path_label = BodyLabel("下载路径")
        self.path_edit = LineEdit()
        self.path_edit.setText(cfg().get(cfg().download_path))
        self.path_edit.setReadOnly(True)
        browse_btn = PrimaryPushButton("浏览")
        browse_btn.clicked.connect(lambda: self._browse_path())
        path_row.addWidget(path_label)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        download_layout.addLayout(path_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(BodyLabel("默认画质"))
        quality_row.addStretch()
        self.quality_combo = ComboBox()
        self.quality_combo.addItems(["360P", "480P", "720P", "1080P", "1080P+", "1080P60", "4K", "杜比视界", "HDR"])
        quality_row.addWidget(self.quality_combo)
        download_layout.addLayout(quality_row)

        thread_row = QHBoxLayout()
        thread_row.addWidget(BodyLabel("并发下载数"))
        thread_row.addStretch()
        self.thread_spin = SpinBox()
        self.thread_spin.setRange(1, 10)
        self.thread_spin.setValue(cfg().get(cfg().download_thread))
        thread_row.addWidget(self.thread_spin)
        download_layout.addLayout(thread_row)

        limit_row = QHBoxLayout()
        self.limit_check = CheckBox("启用下载限速")
        self.limit_check.setChecked(cfg().get(cfg().speed_limit_enabled))
        limit_row.addWidget(self.limit_check)
        limit_row.addStretch()
        self.limit_spin = SpinBox()
        self.limit_spin.setRange(1, 100)
        self.limit_spin.setValue(cfg().get(cfg().speed_limit_rate))
        self.limit_spin.setSuffix(" MB/s")
        limit_row.addWidget(self.limit_spin)
        download_layout.addLayout(limit_row)

        audio_row = QHBoxLayout()
        self.audio_check = CheckBox("下载完成后自动抽取音频")
        self.audio_check.setChecked(cfg().get(cfg().auto_extract_audio))
        audio_row.addWidget(self.audio_check)
        audio_row.addStretch()
        download_layout.addLayout(audio_row)

        # 音频格式选择
        format_row = QHBoxLayout()
        format_row.addWidget(BodyLabel("音频格式"))
        format_row.addStretch()
        self.format_combo = ComboBox()
        self.format_combo.addItems(["MP3", "FLAC", "WAV", "AAC", "OPUS"])
        format_map = {"mp3": 0, "flac": 1, "wav": 2, "aac": 3, "opus": 4}
        from ..config import AudioFormat
        current_format = cfg().get(cfg().audio_format)
        fmt_val = current_format.value if hasattr(current_format, 'value') else str(current_format)
        self.format_combo.setCurrentIndex(format_map.get(fmt_val, 0))
        format_row.addWidget(self.format_combo)
        download_layout.addLayout(format_row)

        # 音频归类模式
        category_row = QHBoxLayout()
        category_row.addWidget(BodyLabel("音频归类"))
        category_row.addStretch()
        self.category_combo = ComboBox()
        self.category_combo.addItems(["不归类", "按艺术家", "按专辑", "按分区"])
        cat_map = {"none": 0, "artist": 1, "album": 2, "type": 3}
        current_cat = cfg().get(cfg().audio_category_mode)
        cat_val = current_cat.value if hasattr(current_cat, 'value') else str(current_cat)
        self.category_combo.setCurrentIndex(cat_map.get(cat_val, 1))
        category_row.addWidget(self.category_combo)
        download_layout.addLayout(category_row)

        # 封面嵌入
        cover_row = QHBoxLayout()
        self.cover_check = CheckBox("自动嵌入音频封面")
        self.cover_check.setChecked(cfg().get(cfg().embed_cover))
        self.cover_check.toggled.connect(lambda c: cfg().set(cfg().embed_cover, c))
        cover_row.addWidget(self.cover_check)
        cover_row.addStretch()
        download_layout.addLayout(cover_row)

        # 连接信号
        self.format_combo.currentIndexChanged.connect(self._on_audio_format_changed)
        self.category_combo.currentIndexChanged.connect(self._on_category_mode_changed)
        self.audio_check.toggled.connect(lambda c: cfg().set(cfg().auto_extract_audio, c))
        self.thread_spin.valueChanged.connect(lambda v: cfg().set(cfg().download_thread, v))
        self.limit_check.toggled.connect(lambda c: cfg().set(cfg().speed_limit_enabled, c))
        self.limit_spin.valueChanged.connect(lambda v: cfg().set(cfg().speed_limit_rate, v))

        layout.addWidget(download_card)

        # 快捷键设置
        hotkey_card = SimpleCardWidget(container)
        hotkey_layout = QVBoxLayout(hotkey_card)
        hotkey_title = SubtitleLabel("⌨️ 快捷键")
        hotkey_layout.addWidget(hotkey_title)

        self._hk_rows = {}
        self._setup_hotkey_labels(hotkey_layout)

        edit_hk_btn = PrimaryPushButton("编辑快捷键")
        edit_hk_btn.clicked.connect(self._edit_hotkeys)
        hotkey_layout.addWidget(edit_hk_btn)

        hk_desc = CaptionLabel("全局快捷键在应用后台时也能使用，需要 pynput 库支持")
        hotkey_layout.addWidget(hk_desc)
        layout.addWidget(hotkey_card)

        # Cookie 管理
        cookie_card = SimpleCardWidget(container)
        cookie_layout = QVBoxLayout(cookie_card)
        cookie_title = SubtitleLabel("🍪 Cookie 管理")
        cookie_layout.addWidget(cookie_title)

        scan_row = QHBoxLayout()
        scan_btn = PrimaryPushButton("🔍 扫描浏览器")
        scan_btn.clicked.connect(self._scan_browser)
        scan_row.addWidget(scan_btn)

        cookie_input_btn = PushButton("📝 手动输入")
        cookie_input_btn.clicked.connect(self._manual_input_cookies)
        scan_row.addWidget(cookie_input_btn)

        clear_cookie_btn = PushButton("🗑 清除登录")
        clear_cookie_btn.clicked.connect(self._clear_cookies)
        scan_row.addWidget(clear_cookie_btn)

        cookie_layout.addLayout(scan_row)
        self.cookie_status = CaptionLabel(self._get_cookie_status_text())
        cookie_layout.addWidget(self.cookie_status)
        layout.addWidget(cookie_card)

        # 关于
        about_card = SimpleCardWidget(container)
        about_layout = QVBoxLayout(about_card)
        about_title = SubtitleLabel("ℹ️ 关于")
        about_layout.addWidget(about_title)
        about_text = BodyLabel("B站下载工具 - 基于 PySide6 + qfluentwidgets 的现代化 B站下载工具。")
        about_layout.addWidget(about_text)
        layout.addWidget(about_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)

    def _on_theme_changed(self, index: int):
        theme_map = {0: Theme.LIGHT, 1: Theme.DARK, 2: Theme.AUTO}
        new_theme = theme_map.get(index, Theme.AUTO)
        cfg().set(cfg().theme, new_theme)
        setTheme(new_theme)
        # 通知各页面刷新主题相关颜色
        window = self.window()
        if window:
            if hasattr(window, 'video_player_page') and window.video_player_page:
                window.video_player_page._on_theme_changed()
            if hasattr(window, 'audio_player_page') and window.audio_player_page:
                window.audio_player_page._on_theme_changed()

    def _on_audio_format_changed(self, index: int):
        from ..config import AudioFormat
        fmt_map = {0: AudioFormat.MP3, 1: AudioFormat.FLAC, 2: AudioFormat.WAV, 3: AudioFormat.AAC, 4: AudioFormat.OPUS}
        cfg().set(cfg().audio_format, fmt_map.get(index, AudioFormat.MP3))

    def _on_category_mode_changed(self, index: int):
        from ..config import AudioCategoryMode
        mode_map = {0: AudioCategoryMode.NONE, 1: AudioCategoryMode.BY_ARTIST, 2: AudioCategoryMode.BY_ALBUM, 3: AudioCategoryMode.BY_TYPE}
        cfg().set(cfg().audio_category_mode, mode_map.get(index, AudioCategoryMode.BY_ARTIST))

    def _browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if path:
            self.path_edit.setText(path)
            cfg().set(cfg().download_path, path)

    def _setup_hotkey_labels(self, layout):
        """初始化快捷键显示标签"""
        import json as _json
        try:
            hk = _json.loads(cfg().get(cfg().global_hotkeys))
        except Exception:
            hk = {}
        names = {
            'play_pause': '播放/暂停',
            'prev': '上一首',
            'next': '下一首',
            'vol_up': '音量加',
            'vol_down': '音量减',
        }
        for key, label in names.items():
            row = QHBoxLayout()
            row.addWidget(BodyLabel(label))
            row.addStretch()
            val = hk.get(key, '未设置')
            lbl = CaptionLabel(val)
            row.addWidget(lbl)
            self._hk_rows[key] = lbl
            wrapper = QWidget()
            wrapper.setLayout(row)
            layout.addWidget(wrapper)

    def _update_hotkey_labels(self):
        """更新快捷键显示标签文本"""
        import json as _json
        try:
            hk = _json.loads(cfg().get(cfg().global_hotkeys))
        except Exception:
            hk = {}
        for key, lbl in self._hk_rows.items():
            lbl.setText(hk.get(key, '未设置'))

    def _edit_hotkeys(self):
        """打开快捷键编辑对话框"""
        from .hotkey_dialog import HotkeyDialog
        dialog = HotkeyDialog(self)
        if dialog.exec():
            self._update_hotkey_labels()

    def _scan_browser(self):
        cookies = get_best_cookies()
        if cookies and 'SESSDATA' in cookies:
            self.window().cookie_manager.set_login_cookies(
                cookies.get('SESSDATA', ''),
                cookies.get('bili_jct', '')
            )
            self.cookie_status.setText(self._get_cookie_status_text())
            self.window().login_status_changed.emit(True)
            MessageBox("扫描成功", "成功从浏览器获取 Cookie！", self).exec()
        else:
            MessageBox("扫描失败", "未能从浏览器获取有效的登录 Cookie。", self).exec()

    def _manual_input_cookies(self):
        from .login_dialog import CookieInputDialog
        dialog = CookieInputDialog(self)
        if dialog.exec():
            cookies = dialog.get_cookies()
            if cookies.get("SESSDATA") and cookies.get("bili_jct"):
                self.window().cookie_manager.set_login_cookies(
                    cookies["SESSDATA"], cookies["bili_jct"]
                )
                self.cookie_status.setText(self._get_cookie_status_text())
                self.window().login_status_changed.emit(True)
                MessageBox("输入成功", "Cookie 已保存！", self).exec()
            else:
                MessageBox("输入失败", "SESSDATA 和 bili_jct 不能为空。", self).exec()

    def _clear_cookies(self):
        self.window().cookie_manager.clear_login_cookies()
        self.cookie_status.setText(self._get_cookie_status_text())
        self.window().login_status_changed.emit(False)

    def _get_cookie_status_text(self) -> str:
        if cfg().get(cfg().is_login):
            user_name = cfg().get(cfg().user_name) or "未知用户"
            return f"✅ 已登录为: {user_name}"
        return "❌ 未登录"
