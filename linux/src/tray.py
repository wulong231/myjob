"""
系统托盘和单实例管理
====================
支持最小化到托盘、单实例运行、跨进程唤醒等功能。
"""
import sys
import os
import json
import socket
import tempfile
import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

logger = logging.getLogger(__name__)

# 单实例通信端口
SINGLE_INSTANCE_PORT = 47832
SINGLE_INSTANCE_HOST = "127.0.0.1"


class SingleInstanceManager:
    """单实例管理器"""

    def __init__(self):
        self._socket = None
        self._is_primary = True

    def try_acquire(self) -> bool:
        """尝试获取单实例锁"""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._socket.bind((SINGLE_INSTANCE_HOST, SINGLE_INSTANCE_PORT))
            self._socket.listen(5)
            self._socket.setblocking(False)
            self._is_primary = True
            logger.debug("单实例锁获取成功")
            return True
        except OSError:
            self._is_primary = False
            logger.debug("已有实例在运行，尝试唤醒...")
            self._socket.close()
            self._socket = None
            self._notify_existing_instance()
            return False

    def _notify_existing_instance(self):
        """通知已存在的实例"""
        try:
            notify_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            notify_socket.connect((SINGLE_INSTANCE_HOST, SINGLE_INSTANCE_PORT))
            notify_socket.sendall(b"SHOW")
            notify_socket.close()
            logger.debug("已通知现有实例显示窗口")
        except Exception as e:
            logger.debug(f"通知现有实例失败: {e}")

    def is_primary(self) -> bool:
        return self._is_primary

    def close(self):
        """关闭单实例管理器"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass


class TrayIconManager(QObject):
    """系统托盘图标管理器"""

    show_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray: Optional[QSystemTrayIcon] = None
        self._setup_tray()

    def _setup_tray(self):
        """设置托盘图标"""
        # 创建托盘图标
        icon = self._create_default_icon()
        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip("Bili23 - B站下载器")

        # 创建托盘菜单
        menu = QMenu()

        show_action = menu.addAction("📺 显示主窗口")
        show_action.triggered.connect(self.show_requested.emit)

        menu.addSeparator()

        download_action = menu.addAction("📥 打开下载目录")
        download_action.triggered.connect(self._open_download_dir)

        menu.addSeparator()

        quit_action = menu.addAction("🚪 退出")
        quit_action.triggered.connect(self.quit_requested.emit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)

    def _create_default_icon(self) -> QIcon:
        """创建默认图标"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制圆形背景
        painter.setBrush(QBrush(QColor("#6C5CE7")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 56, 56)

        # 绘制文字
        painter.setPen(QPen(QColor("#FFFFFF")))
        font = painter.font()
        font.setPixelSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "B23")

        painter.end()
        return QIcon(pixmap)

    def _on_tray_activated(self, reason):
        """托盘图标激活"""
        if reason == QSystemTrayIcon.Trigger:
            self.show_requested.emit()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_requested.emit()

    def _open_download_dir(self):
        """打开下载目录"""
        from .config import get_config
        from .utils import open_in_file_manager
        config = get_config()
        path = config.get(config.download_path)
        if os.path.exists(path):
            open_in_file_manager(path)

    def show(self):
        """显示托盘图标"""
        if self._tray:
            self._tray.show()

    def hide(self):
        """隐藏托盘图标"""
        if self._tray:
            self._tray.hide()

    def show_notification(self, title: str, message: str,
                          icon=QSystemTrayIcon.Information, duration: int = 3000):
        """显示托盘通知"""
        if self._tray:
            self._tray.showMessage(title, message, icon, duration)

    def update_tooltip(self, tooltip: str):
        """更新提示文字"""
        if self._tray:
            self._tray.setToolTip(tooltip)
