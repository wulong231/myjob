"""
Bili23 - B站下载器
==================
基于 PySide6 + qfluentwidgets 的现代化 B站视频下载工具。
支持高清画质、多线程下载、断点续传、自动获取 Cookie 等功能。

作者: Bili23 Team
版本: 2.0.0
"""
import sys
import os
import logging
from pathlib import Path

# 确保 src 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from qfluentwidgets import FluentIcon as FIcon

from src.config import setup_config, save_config
from src.gui.main_window import MainWindow
from src.tray import SingleInstanceManager, TrayIconManager


def setup_logging():
    """配置日志"""
    log_dir = Path.cwd() / ".bili23" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"bili23_{os.getpid()}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(str(log_file), encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )


def main():
    """主入口"""
    # 必须在任何其他操作之前设置全局异常钩子
    from src.utils import setup_global_exception_hook
    setup_global_exception_hook()

    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Bili23 启动中...")

    # 检查并自动安装依赖（ffmpeg 等）
    try:
        from src.dependency_checker import run_all_checks
        dep_results = run_all_checks()
        for name, ok in dep_results.items():
            if ok:
                logger.info(f"依赖检查通过: {name}")
            else:
                logger.warning(f"依赖检查未通过: {name}，部分功能可能受限")
    except Exception as e:
        logger.debug(f"依赖检查异常: {e}")

    # 创建 QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Bili23")
    app.setOrganizationName("Bili23")

    # 设置应用图标
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app_icon.jpg")
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    # 初始化配置
    config = setup_config()

    # 单实例检测
    instance_mgr = SingleInstanceManager()
    if not instance_mgr.try_acquire():
        logger.info("已有实例在运行，已唤醒")
        return 0

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 创建托盘管理器
    tray_mgr = TrayIconManager()
    tray_mgr.show_requested.connect(window._show_and_activate)
    tray_mgr.quit_requested.connect(app.quit)
    tray_mgr.show()

    # 更新托盘提示
    tray_mgr.update_tooltip("Bili23 - B站下载器")
    tray_mgr.show_notification(
        "Bili23",
        "应用已启动，最小化到系统托盘可后台运行",
        QSystemTrayIcon.Information,
        3000
    )

    # 处理单实例唤醒
    def check_single_instance():
        if instance_mgr._socket:
            try:
                conn, addr = instance_mgr._socket.accept()
                data = conn.recv(1024)
                if data == b"SHOW":
                    window._show_and_activate()
                conn.close()
            except BlockingIOError:
                pass
            except Exception:
                pass

    instance_timer = QTimer()
    instance_timer.timeout.connect(check_single_instance)
    instance_timer.start(500)

    # 保存配置
    about_to_quit = lambda: save_config(config)
    app.aboutToQuit.connect(about_to_quit)

    # 运行
    exit_code = app.exec()

    # 清理
    instance_mgr.close()
    tray_mgr.hide()
    save_config(config)

    logger.info(f"Bili23 退出，退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
