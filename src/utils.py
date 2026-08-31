"""
工具模块
========
通用工具函数：快速文件扫描、重试装饰器、全局异常钩子等。
"""

import os
import sys
import time
import logging
import functools
from typing import List, Callable, Optional, Tuple, Type, Any, TypeVar

F = TypeVar('F', bound=Callable[..., Any])

logger = logging.getLogger(__name__)


# ==================== 快速文件扫描 ====================

def scandir_recursive(
    root_path: str,
    extensions: Tuple[str, ...],
    follow_symlinks: bool = False,
) -> List[str]:
    """使用 os.scandir 递归扫描文件，比 os.walk 快 2~3 倍。

    Args:
        root_path: 扫描根目录
        extensions: 文件扩展名元组（小写），如 ('.mp3', '.flac')
        follow_symlinks: 是否跟随符号链接

    Returns:
        匹配的文件绝对路径列表
    """
    result: List[str] = []
    try:
        # 使用栈模拟递归，避免深目录递归栈溢出
        stack = [root_path]
        while stack:
            dir_path = stack.pop()
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=follow_symlinks):
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=follow_symlinks):
                                if entry.name.lower().endswith(extensions):
                                    result.append(entry.path)
                        except OSError:
                            # 跳过无权限访问的文件/目录
                            continue
            except (PermissionError, OSError):
                # 跳过无权限访问的目录
                continue
    except Exception as e:
        logger.error(f"扫描目录失败 {root_path}: {e}")
    return result


def count_files_recursive(root_path: str, extensions: Tuple[str, ...]) -> int:
    """快速统计符合扩展名的文件数量（不收集路径，节省内存）"""
    count = 0
    try:
        stack = [root_path]
        while stack:
            dir_path = stack.pop()
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_dir():
                                stack.append(entry.path)
                            elif entry.is_file():
                                if entry.name.lower().endswith(extensions):
                                    count += 1
                        except OSError:
                            continue
            except (PermissionError, OSError):
                continue
    except Exception:
        pass
    return count


def get_folder_size(root_path: str) -> int:
    """快速计算目录总大小（字节），使用 scandir 遍历"""
    total = 0
    try:
        stack = [root_path]
        while stack:
            dir_path = stack.pop()
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_dir():
                                stack.append(entry.path)
                            elif entry.is_file():
                                total += entry.stat().st_size
                        except OSError:
                            continue
            except (PermissionError, OSError):
                continue
    except Exception:
        pass
    return total


# ==================== 重试装饰器 ====================

def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int, int], Any]] = None,
) -> Callable[[F], F]:
    """重试装饰器：函数执行失败时自动重试。

    Args:
        max_retries: 最大重试次数
        delay: 初始重试延迟（秒）
        backoff: 每次重试延迟倍数
        exceptions: 需要重试的异常类型
        on_retry: 每次重试前的回调，参数为 (exception, retry_count, max_retries)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            current_delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        if on_retry:
                            try:
                                on_retry(e, attempt + 1, max_retries)
                            except Exception:
                                pass
                        logger.warning(
                            f"{func.__name__} 失败 (第{attempt + 1}/{max_retries}次): {e}，"
                            f"{current_delay:.1f}秒后重试"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 已重试{max_retries}次仍失败: {e}"
                        )
            raise last_exception
        return wrapper
    return decorator


# ==================== 全局异常钩子 ====================

def _global_exception_handler(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: object,
) -> None:
    """全局未捕获异常处理器"""
    # 跳过 KeyboardInterrupt（用户手动中断）
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical(
        "未捕获的异常",
        exc_info=(exc_type, exc_value, exc_traceback),
    )

    # 尝试在控制台输出（开发阶段）
    try:
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback)
    except Exception:
        pass


def setup_global_exception_hook() -> None:
    """设置全局异常钩子，捕获所有未处理的异常并记录日志"""
    sys.excepthook = _global_exception_handler

    # 也捕获 QThread 中的异常（PySide6 默认吞掉线程异常）
    try:
        import PySide6
        from PySide6.QtCore import QMessageLogContext

        def qt_message_handler(
            mode: int,
            context: QMessageLogContext,
            message: str,
        ) -> None:
            """Qt 消息处理器，将 Qt 的 warning/critical 也记录到日志"""
            if mode == 0:  # QtDebugMsg
                logger.debug(f"Qt: {message}")
            elif mode == 1:  # QtWarningMsg
                logger.warning(f"Qt: {message}")
            elif mode == 2:  # QtCriticalMsg
                logger.error(f"Qt: {message}")
            elif mode == 3:  # QtFatalMsg
                logger.critical(f"Qt: {message}")
            else:
                logger.info(f"Qt: {message}")

        PySide6.QtCore.qInstallMessageHandler(qt_message_handler)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"设置 Qt 消息处理器失败: {e}")


# ==================== 安全文件操作 ====================

def safe_delete(path: str) -> bool:
    """安全删除文件，失败时记录日志"""
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except OSError as e:
        logger.warning(f"删除文件失败 {path}: {e}")
    return False


def safe_rmdir(path: str) -> bool:
    """安全删除空目录，失败时记录日志"""
    try:
        if os.path.isdir(path):
            os.rmdir(path)
            return True
    except OSError as e:
        logger.warning(f"删除目录失败 {path}: {e}")
    return False


def safe_makedirs(path: str) -> bool:
    """安全创建目录，失败时记录日志"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError as e:
        logger.error(f"创建目录失败 {path}: {e}")
    return False