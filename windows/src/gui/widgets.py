"""音频播放器组件：工作线程与旋转封面"""
import os
import math
import struct
import logging
from typing import List, Optional, Dict, Tuple

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QPixmap, QPainter, QFont, QBrush, QPen, QLinearGradient, QTransform, QColor
from PySide6.QtWidgets import QLabel

logger = logging.getLogger(__name__)


def _extract_metadata(audio_path: str) -> Dict[str, str]:
    """提取音频元数据 (title, artist, album)。
    - MP3 (.mp3): 使用 mutagen.mp3.MP3 + TIT2/TPE1/TALB 帧
    - M4A/MP4 (.m4a, .mp4): 使用 mutagen.mp4.MP4 的 '\xa9nam' / '\xa9ART' / '\xa9alb' 原子
    - FLAC (.flac): 使用 mutagen.flac.FLAC 的 vorbis 注释
    - OGG/OPUS/WAV/其他: 走通用 MutagenFile + 字符串 key
    读取完成后立即释放本地引用，避免 Windows 文件句柄占用导致后续 move 失败。
    """
    meta = {'title': '', 'artist': '', 'album': ''}
    if not audio_path or not os.path.isfile(audio_path):
        return meta
    ext = os.path.splitext(audio_path)[1].lower()
    try:
        if ext == '.mp3':
            from mutagen.mp3 import MP3 as _MP3
            audio = _MP3(audio_path)
            def _mp3_get(id3_key: str) -> str:
                if audio.tags and id3_key in audio.tags:
                    f = audio.tags[id3_key]
                    if hasattr(f, 'text') and f.text:
                        return str(f.text[0])
                return ''
            meta['title']  = _mp3_get('TIT2')
            meta['artist'] = _mp3_get('TPE1')
            meta['album']  = _mp3_get('TALB')
            try:
                if hasattr(audio, 'filename'):
                    audio.filename = None
                del audio
            except Exception:
                pass
        elif ext in ('.m4a', '.mp4'):
            from mutagen.mp4 import MP4 as _MP4
            audio = _MP4(audio_path)
            mp4_map = {'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb'}
            for k, atom in mp4_map.items():
                v = audio.get(atom, '')
                if isinstance(v, list):
                    meta[k] = str(v[0]) if v else ''
                else:
                    meta[k] = str(v) if v else ''
            try:
                del audio
            except Exception:
                pass
        elif ext == '.flac':
            from mutagen.flac import FLAC as _FLAC
            audio = _FLAC(audio_path)
            for k in ('title', 'artist', 'album'):
                v = audio.get(k, '')
                if isinstance(v, list):
                    meta[k] = str(v[0]) if v else ''
                else:
                    meta[k] = str(v) if v else ''
            try:
                del audio
            except Exception:
                pass
        else:
            # OGG / OPUS / WAV / 其他 → 走通用 MutagenFile
            from mutagen import File as _MF
            audio = _MF(audio_path)
            if audio is not None:
                for k in ('title', 'artist', 'album'):
                    v = audio.get(k, '')
                    if isinstance(v, list):
                        meta[k] = str(v[0]) if v else ''
                    else:
                        meta[k] = str(v) if v else ''
            try:
                if audio is not None:
                    del audio
            except Exception:
                pass

        for k, v in list(meta.items()):
            if not v or v == '[]':
                meta[k] = ''
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"提取元数据失败 {audio_path}: {e}")
    return meta


class _SyncToTransferWorker(QThread):
    """后台同步音频和歌词到 transfer 目录（排除重复）"""
    finished = Signal(int, int, int)  # (copied, skipped, errors)

    def __init__(self, playlist: List[str], transfer_path: str, parent=None):
        super().__init__(parent)
        self._playlist = playlist
        self._transfer_path = transfer_path

    def run(self):
        import shutil
        import hashlib
        os.makedirs(self._transfer_path, exist_ok=True)

        copied = 0
        skipped = 0
        errors = 0

        # 预扫描目标目录，建立已有文件索引（文件名 -> (大小, md5)）
        existing_files = {}
        for fname in os.listdir(self._transfer_path):
            fpath = os.path.join(self._transfer_path, fname)
            if os.path.isfile(fpath):
                try:
                    existing_files[fname] = (os.path.getsize(fpath), None)
                except Exception:
                    pass

        for audio_path in self._playlist:
            if not os.path.isfile(audio_path):
                errors += 1
                continue

            try:
                # 获取元数据，按"歌名 - 歌手"命名
                meta = _extract_metadata(audio_path)
                title = meta.get('title', '')
                artist = meta.get('artist', '')
                ext = os.path.splitext(audio_path)[1]

                if title and artist:
                    dest_name = f"{title} - {artist}{ext}"
                elif title:
                    dest_name = f"{title}{ext}"
                else:
                    dest_name = os.path.basename(audio_path)

                # 清理文件名中的非法字符
                dest_name = self._sanitize_filename(dest_name)
                dest_path = os.path.join(self._transfer_path, dest_name)

                # 去重检查：文件名 + 大小 + MD5
                src_size = os.path.getsize(audio_path)
                if dest_name in existing_files:
                    dest_size, dest_md5 = existing_files[dest_name]
                    if dest_size == src_size:
                        # 大小相同，进一步校验 MD5
                        if dest_md5 is None:
                            dest_md5 = self._file_md5(dest_path)
                            existing_files[dest_name] = (dest_size, dest_md5)
                        src_md5 = self._file_md5(audio_path)
                        if dest_md5 == src_md5:
                            skipped += 1
                            # 仍然尝试复制歌词（歌词可能不存在）
                            self._copy_lyrics(audio_path, dest_name)
                            continue

                shutil.copy2(audio_path, dest_path)
                copied += 1
                # 更新索引
                existing_files[dest_name] = (src_size, None)

                # 同时复制同名 .lrc 和 .zh.lrc 歌词文件
                self._copy_lyrics(audio_path, dest_name)

            except Exception as e:
                logger.warning(f"同步文件失败 {audio_path}: {e}")
                errors += 1

        self.finished.emit(copied, skipped, errors)

    @staticmethod
    def _file_md5(path: str, chunk_size: int = 8192) -> str:
        """计算文件 MD5 值"""
        import hashlib
        md5 = hashlib.md5()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()

    def _copy_lyrics(self, audio_path: str, dest_audio_name: str):
        """复制同名歌词文件到目标目录（排除重复）"""
        import shutil
        base = os.path.splitext(audio_path)[0]
        dest_base = os.path.splitext(dest_audio_name)[0]

        for suffix in ('.lrc', '.zh.lrc'):
            src_lrc = base + suffix
            if os.path.isfile(src_lrc):
                dest_lrc = os.path.join(self._transfer_path, dest_base + suffix)
                if os.path.isfile(dest_lrc):
                    # 大小相同则跳过
                    if os.path.getsize(dest_lrc) == os.path.getsize(src_lrc):
                        continue
                try:
                    shutil.copy2(src_lrc, dest_lrc)
                except Exception as e:
                    logger.debug(f"复制歌词失败 {src_lrc}: {e}")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """移除文件名中的非法字符"""
        illegal = r'<>:"/\|?*'
        for ch in illegal:
            name = name.replace(ch, '')
        # 去除首尾空格和点号
        name = name.strip(' .')
        return name or 'untitled'


class RotatingCoverLabel(QLabel):
    """可旋转的封面图组件，播放时缓慢旋转"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle: float = 0.0
        self._pixmap: Optional[QPixmap] = None
        self._is_playing: bool = False
        # 加大封面显示尺寸，配合 200x200 高清 pixmap 更清晰
        self.setFixedSize(160, 160)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: transparent; border-radius: 80px;")
        self.setText("🎵")

        self._timer = QTimer(self)
        self._timer.setInterval(50)  # 20fps
        self._timer.timeout.connect(self._on_tick)

    def set_pixmap(self, pixmap: QPixmap):
        """设置封面图并启动旋转"""
        self._pixmap = pixmap
        self._angle = 0.0
        self.update()

    def set_playing(self, playing: bool):
        """播放/暂停旋转"""
        self._is_playing = playing
        if playing and self._pixmap:
            self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def _on_tick(self):
        self._angle = (self._angle + 0.5) % 360
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            # 无封面图时，绘制带渐变背景的圆形 + 音符图标
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            rect = self.rect()
            gradient = QLinearGradient(0, 0, rect.width(), rect.height())
            gradient.setColorAt(0, QColor("#667EEA"))
            gradient.setColorAt(1, QColor("#764BA2"))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect.adjusted(2, 2, -2, -2))
            painter.setPen(QPen(QColor(255, 255, 255, 200)))
            font = QFont("Segoe UI Emoji", 28)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "🎵")
            return

        # 有封面图时，旋转绘制
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        # 圆形裁剪
        path_rect = self.rect()
        painter.setClipRect(path_rect)

        # 绘制旋转的封面
        transform = painter.transform()
        center = self.rect().center()
        transform.translate(center.x(), center.y())
        transform.rotate(self._angle)
        transform.translate(-center.x(), -center.y())
        painter.setTransform(transform)

        # 圆形遮罩
        painter.setBrush(QBrush(self._pixmap.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(self.rect().adjusted(4, 4, -4, -4))

        # 绘制中心圆点（黑胶效果）
        painter.setTransform(QTransform())  # 重置变换
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        center = self.rect().center()
        painter.drawEllipse(center, 8, 8)
        painter.setBrush(QBrush(QColor(80, 80, 80)))
        painter.drawEllipse(center, 3, 3)


class _AudioLevelWorker(QThread):
    """后台使用 ffmpeg 解码音频文件，计算每 50ms 的 RMS 音量曲线。
    计算结果通过 finished 信号返回 (audio_path, levels_list)。
    若 ffmpeg 不可用或解码失败，返回空列表（调用方回退到伪随机波动）。"""
    finished = Signal(str, list)  # (audio_path, rms_levels 0~1)

    # 进度采样率与间隔
    SAMPLE_RATE = 8000          # 低采样率已足够声浪可视化，减少数据量
    INTERVAL_MS = 50            # 每 50ms 一个 RMS 采样点（与桌面歌词刷新率匹配）
    MAX_LEVELS = 432000         # 理论上限：6 小时 × 3600s × 20 次/秒 = 432000，防内存爆炸
    MAX_RUNTIME_SEC = 180       # 单文件分析最长 3 分钟，防 ffmpeg 挂死

    def __init__(self, audio_path: str, ffmpeg_path: str = "ffmpeg", parent=None):
        super().__init__(parent)
        self._audio_path = audio_path
        self._ffmpeg_path = ffmpeg_path

    def run(self):
        import time
        start_ts = time.time()
        try:
            import subprocess
            import shutil

            ffmpeg = self._ffmpeg_path or shutil.which("ffmpeg")
            if not ffmpeg:
                self.finished.emit(self._audio_path, [])
                return
            # 输入文件必须存在
            if not os.path.exists(self._audio_path):
                self.finished.emit(self._audio_path, [])
                return

            samples_per_interval = int(self.SAMPLE_RATE * self.INTERVAL_MS / 1000)
            bytes_per_interval = samples_per_interval * 2  # 16-bit signed
            if bytes_per_interval <= 0:
                self.finished.emit(self._audio_path, [])
                return

            cmd = [
                ffmpeg, "-i", self._audio_path,
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ac", "1",                       # 单声道
                "-ar", str(self.SAMPLE_RATE),
                "-y",
                "-",                              # 输出到 stdout
            ]
            # 关闭 stdin/stderr 避免继承主进程句柄导致异常环境下卡住
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            levels: list = []
            read_chunk = bytes_per_interval
            try:
                while not self.isInterruptionRequested():
                    # 总运行时长上限，防止 ffmpeg 异常挂死
                    if time.time() - start_ts > self.MAX_RUNTIME_SEC:
                        break
                    data = proc.stdout.read(read_chunk)
                    if not data or len(data) < read_chunk:
                        break
                    n = len(data) // 2
                    if n <= 0:
                        break
                    samples = struct.unpack("<%dh" % n, data)
                    sum_sq = 0
                    for s in samples:
                        sum_sq += s * s
                    rms = math.sqrt(sum_sq / n)
                    # 归一化到 0~1（16-bit signed 最大值 32767），并适度放大
                    norm = min(1.0, rms / 32767.0)
                    # 应用非线性放大让小音量也可见
                    norm = math.pow(norm, 0.6)
                    levels.append(norm)
                    # 绝对数量上限，防异常文件（超长/损坏）导致内存爆炸
                    if len(levels) >= self.MAX_LEVELS:
                        break
            finally:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                                proc.wait(timeout=1)
                            except Exception:
                                pass
                except Exception:
                    pass

            self.finished.emit(self._audio_path, levels)
        except Exception as e:
            logger.debug(f"音频电平分析失败 {self._audio_path}: {e}")
            try:
                self.finished.emit(self._audio_path, [])
            except Exception:
                pass