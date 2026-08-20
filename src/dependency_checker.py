"""
依赖检查与自动安装模块
========================
在程序启动时检查 ffmpeg、Python 依赖包等是否可用，
缺失时自动通过 winget 或 pip 安装，无需用户手动操作。
"""
import os
import sys
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_command(cmd: list, timeout: int = 60) -> bool:
    """运行命令并返回是否成功"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False


def check_ffmpeg() -> bool:
    """检查系统 PATH 中是否有 ffmpeg"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def check_ffmpeg_bundled() -> str:
    """检查打包目录中是否有 ffmpeg.exe"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        path = os.path.join(sys._MEIPASS, "bin", "ffmpeg.exe")
        if os.path.exists(path):
            return path
    # 项目根目录下的 bin/ffmpeg.exe
    base = Path.cwd()
    path = str(base / "bin" / "ffmpeg.exe")
    if os.path.exists(path):
        return path
    return ""


def install_ffmpeg_winget() -> bool:
    """通过 winget 安装 ffmpeg（Windows 10/11 自带 winget）"""
    logger.info("尝试通过 winget 安装 ffmpeg...")
    try:
        result = subprocess.run(
            ["winget", "install", "FFmpeg", "--accept-source-agreements", "--accept-package-agreements"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info("ffmpeg 安装成功")
            return True
        logger.warning(f"winget 安装 ffmpeg 失败: {result.stderr[:200]}")
        return False
    except Exception as e:
        logger.warning(f"winget 安装 ffmpeg 异常: {e}")
        return False


def install_ffmpeg_chocolatey() -> bool:
    """通过 choco 安装 ffmpeg"""
    logger.info("尝试通过 Chocolatey 安装 ffmpeg...")
    try:
        result = subprocess.run(
            ["choco", "install", "ffmpeg", "-y"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info("ffmpeg 安装成功 (choco)")
            return True
        return False
    except Exception:
        return False


def install_ffmpeg_scoop() -> bool:
    """通过 scoop 安装 ffmpeg"""
    logger.info("尝试通过 Scoop 安装 ffmpeg...")
    try:
        result = subprocess.run(
            ["scoop", "install", "ffmpeg"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info("ffmpeg 安装成功 (scoop)")
            return True
        return False
    except Exception:
        return False


def ensure_ffmpeg() -> bool:
    """确保 ffmpeg 可用，缺失时自动安装"""
    if check_ffmpeg():
        logger.info("ffmpeg 已可用（系统 PATH）")
        return True

    bundled = check_ffmpeg_bundled()
    if bundled:
        logger.info(f"ffmpeg 已可用（本地打包: {bundled}）")
        return True

    logger.info("ffmpeg 未安装，尝试自动安装...")
    # 按优先级尝试安装
    if install_ffmpeg_winget():
        return True
    if install_ffmpeg_chocolatey():
        return True
    if install_ffmpeg_scoop():
        return True

    logger.warning("ffmpeg 自动安装失败，请手动安装（参考: https://ffmpeg.org/download.html）")
    return False


def ensure_python_deps() -> bool:
    """检查并安装缺失的 Python 依赖包"""
    required = {
        "PySide6": "PySide6",
        "qfluentwidgets": "qfluentwidgets",
        "mutagen": "mutagen",
        "httpx": "httpx",
        "cryptography": "cryptography",
        "pynput": "pynput",
    }
    missing = []
    for import_name, pkg_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg_name)

    if not missing:
        return True

    logger.info(f"检测到缺失依赖: {', '.join(missing)}，尝试自动安装...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install"] + missing,
            capture_output=True, text=True, timeout=300
        )
        # 验证安装
        for pkg in missing:
            try:
                __import__(pkg)
            except ImportError:
                logger.warning(f"依赖 {pkg} 安装失败，请手动安装")
                return False
        logger.info(f"依赖安装成功: {', '.join(missing)}")
        return True
    except Exception as e:
        logger.error(f"依赖安装失败: {e}")
        return False


def run_all_checks() -> dict:
    """运行所有依赖检查，返回结果字典"""
    results = {
        "ffmpeg": ensure_ffmpeg(),
        "python_deps": ensure_python_deps(),
    }
    return results