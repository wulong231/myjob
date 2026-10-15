"""
下载器模块
==========
实现分片下载、断点续传、自动重试等功能。
支持令牌桶限速、下载进度回调。
"""
import os
import sys
import time
import threading
import logging
import hashlib
import json
from pathlib import Path
from typing import Optional, Callable, List

from .config import get_config
from .network import download_chunk, download_file, get_client
from .models import DownloadTask, DownloadStatus, MediaType, EpisodeInfo, VideoInfo
from .utils import safe_makedirs, safe_delete

logger = logging.getLogger(__name__)


class DownloadInterrupted(RuntimeError):
    """下载因暂停/取消/分片未完成而中止，任务保持当前状态（便于断点续传）"""


# 默认分片大小：降低到 256KB，使小文件也有多个分片以实时显示进度
CHUNK_SIZE = 256 * 1024  # 256 KB per chunk
DEFAULT_CHUNKS = 16

# B站画质码 → 显示名称
QUALITY_MAP = {
    16: "360P", 32: "480P", 64: "720P", 80: "720P",
    100: "1080P", 116: "1080P+", 120: "4K",
    125: "杜比视界", 126: "4K", 127: "1080P60",
}


def _quality_name(qn: int) -> str:
    """将画质码转为可读名称"""
    return QUALITY_MAP.get(qn, f"{qn}P")


def _cfg():
    return get_config()


class TokenBucket:
    """令牌桶限速器"""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: float = 1) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens += elapsed * self.rate
            if self.tokens > self.capacity:
                self.tokens = self.capacity
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait(self, tokens: float = 1):
        while not self.consume(tokens):
            time.sleep(0.01)


class BilibiliDownloader:
    """Bilibili 下载器"""

    def __init__(self):
        self._tasks: List[DownloadTask] = []
        self._running_tasks: List[DownloadTask] = []
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._token_bucket: Optional[TokenBucket] = None
        self._progress_callbacks: List[Callable] = []

        if _cfg().get(_cfg().speed_limit_enabled):
            self._init_speed_limiter()

    def _init_speed_limiter(self):
        """初始化限速器"""
        rate_mbps = _cfg().get(_cfg().speed_limit_rate)
        rate_bps = rate_mbps * 1024 * 1024
        self._token_bucket = TokenBucket(rate_bps, rate_bps * 2)

    def add_progress_callback(self, callback: Callable):
        """添加进度回调"""
        self._progress_callbacks.append(callback)

    def remove_progress_callback(self, callback: Callable):
        """移除进度回调"""
        self._progress_callbacks.remove(callback)

    def get_tasks(self) -> List[DownloadTask]:
        """获取所有任务"""
        return self._tasks.copy()

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """获取指定任务"""
        for task in self._tasks:
            if task.task_id == task_id:
                return task
        return None

    def add_task(self, task: DownloadTask) -> str:
        """添加下载任务（已存在相同任务则返回已有任务ID，避免重复）"""
        task.task_id = self._generate_task_id(task)

        with self._lock:
            # 去重检查：若已存在相同 task_id 的任务，直接返回，不重复添加
            for existing in self._tasks:
                if existing.task_id == task.task_id:
                    # 如果已有任务是完成/失败状态，替换为新任务以支持重试
                    if existing.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED):
                        existing.status = DownloadStatus.PENDING
                        existing.progress = 0.0
                        existing.error_message = ""
                        existing.downloaded_size = 0
                        existing.download_speed = 0
                        logger.info(f"重置已完成/失败任务: {task.task_id}")
                        return task.task_id
                    # 正在下载/暂停/等待中的任务直接返回，避免重复
                    logger.info(f"任务已存在，跳过重复添加: {task.task_id}")
                    return task.task_id
            task.status = DownloadStatus.PENDING
            self._tasks.append(task)

        logger.info(f"添加下载任务: {task.task_id} - {task.episode.part if task.episode else 'N/A'}")
        return task.task_id

    def start_task(self, task_id: str) -> bool:
        """开始下载任务"""
        task = self.get_task(task_id)
        if not task:
            return False

        thread = threading.Thread(
            target=self._download_task,
            args=(task,),
            daemon=True,
            name=f"download-{task_id}"
        )
        thread.start()
        return True

    def pause_task(self, task_id: str) -> bool:
        """暂停下载任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        if task.status == DownloadStatus.DOWNLOADING:
            task.status = DownloadStatus.PAUSED
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复下载任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        if task.status == DownloadStatus.PAUSED:
            self.start_task(task_id)
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """取消下载任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        task.status = DownloadStatus.FAILED
        task.error_message = "用户取消"
        self._notify_progress(task)
        return True

    def remove_task(self, task_id: str) -> bool:
        """移除下载任务"""
        with self._lock:
            for i, task in enumerate(self._tasks):
                if task.task_id == task_id:
                    self._tasks.pop(i)
                    return True
        return False

    def pause_all(self):
        """暂停所有下载"""
        self._pause_event.clear()
        for task in self._tasks:
            if task.status == DownloadStatus.DOWNLOADING:
                task.status = DownloadStatus.PAUSED

    def resume_all(self):
        """恢复所有下载"""
        self._pause_event.set()
        for task in self._tasks:
            if task.status == DownloadStatus.PAUSED:
                self.start_task(task.task_id)

    def _generate_task_id(self, task: DownloadTask) -> str:
        """生成任务 ID"""
        cid = task.episode.cid if task.episode else 0
        raw = f"{task.video_info.bvid}_{cid}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _notify_progress(self, task: DownloadTask):
        """通知进度更新"""
        for callback in self._progress_callbacks:
            try:
                callback(task)
            except Exception as e:
                logger.debug(f"进度回调异常: {e}")

    def _download_task(self, task: DownloadTask):
        """执行下载任务"""
        task.status = DownloadStatus.DOWNLOADING
        self._notify_progress(task)

        try:
            if task.download_type == MediaType.VIDEO:
                self._download_video(task)
            elif task.download_type == MediaType.AUDIO:
                self._download_audio_only(task)
            elif task.download_type == MediaType.DANMAKU:
                self._download_danmaku(task)
            elif task.download_type == MediaType.COVER:
                self._download_cover(task)
        except DownloadInterrupted as e:
            # 暂停/取消/分片未完成：保留当前状态，便于断点续传
            logger.info(f"下载任务中止（保留状态）: {task.task_id}: {e}")
        except Exception as e:
            task.status = DownloadStatus.FAILED
            task.error_message = str(e)
            logger.error(f"下载任务失败: {task.task_id}: {e}")
        finally:
            self._notify_progress(task)

    def _download_video(self, task: DownloadTask):
        """下载视频"""
        from .bilibili_api import BilibiliClient

        client = BilibiliClient()
        episode = task.episode

        # 如果没有 episode（cid），先获取视频信息
        if not episode or not episode.cid:
            video_info = client.get_video_info(task.video_info.bvid)
            if video_info and video_info.episodes:
                episode = video_info.episodes[0]
                task.episode = episode
            else:
                raise RuntimeError("无法获取视频 CID")

        # 检查登录状态：720P 高码率及以上（qn >= 80）需要登录
        requested_qn = task.quality.value
        cfg = _cfg()
        is_login = bool(cfg.get(cfg.is_login))
        requires_login = requested_qn >= 80
        if requires_login and not is_login:
            quality_name = QUALITY_MAP.get(requested_qn, f"{requested_qn}P")
            if requested_qn >= 100:
                raise RuntimeError(f"下载 {quality_name} 画质需要登录B站账号，请先登录后再下载")
            else:
                raise RuntimeError(f"下载 {quality_name} 及以上画质需要登录B站账号，请先登录后再下载")

        # 获取播放地址
        play_data = client.get_play_url(
            task.video_info.bvid,
            episode.cid,
            task.quality.value
        )

        if not play_data:
            raise RuntimeError("无法获取播放地址")

        # 记录实际下载的画质
        actual_qn = play_data.get("quality", 0)
        task.actual_quality = actual_qn
        logger.info(f"请求画质: {_quality_name(requested_qn)}，实际画质: {_quality_name(actual_qn)}")

        # 确定输出目录（视频单独存放在 downloads/videos/ 下）
        output_dir = _cfg().get(_cfg().download_path)
        # 视频存放在 downloads/videos/UP主/ 目录下
        video_base_dir = os.path.join(output_dir, "videos")
        uploader_dir = os.path.join(video_base_dir, self._sanitize_filename(task.video_info.owner_name))
        os.makedirs(uploader_dir, exist_ok=True)

        base_name = self._build_filename(task)

        video_url = play_data.get("video_url", "")
        audio_url = play_data.get("audio_url", "")

        # 下载视频
        if video_url:
            video_path = os.path.join(uploader_dir, f"{base_name}_video.m4s")
            self._download_with_resume(video_url, video_path, task)

        # 下载音频
        if audio_url:
            audio_path = os.path.join(uploader_dir, f"{base_name}_audio.m4s")
            self._download_with_resume(audio_url, audio_path, task)

        # 合并音视频
        if video_url and audio_url:
            final_path = os.path.join(uploader_dir, f"{base_name}.mp4")
            self._merge_video_audio(
                os.path.join(uploader_dir, f"{base_name}_video.m4s"),
                os.path.join(uploader_dir, f"{base_name}_audio.m4s"),
                final_path
            )
            task.file_path = final_path

            # 清理临时文件
            for suffix in ["_video.m4s", "_audio.m4s"]:
                tmp = os.path.join(uploader_dir, f"{base_name}{suffix}")
                if os.path.exists(tmp):
                    os.remove(tmp)
        elif video_url:
            task.file_path = os.path.join(uploader_dir, f"{base_name}.mp4")

        task.status = DownloadStatus.COMPLETED

    def _get_audio_output_dir(self, task: DownloadTask, video_info=None) -> str:
        """根据归类模式确定音频输出目录（统一放在 musics 文件夹下）"""
        base_dir = _cfg().get(_cfg().download_path)
        # 音频文件统一放在 musics 子目录下
        output_dir = os.path.join(base_dir, "musics") if base_dir else os.path.join(os.getcwd(), "musics")
        artist = self._sanitize_filename(task.video_info.owner_name) if task.video_info else "未知艺术家"

        from .config import AudioCategoryMode
        mode = _cfg().get(_cfg().audio_category_mode)
        if hasattr(mode, 'value'):
            mode_val = mode.value
        else:
            mode_val = str(mode)

        if mode_val == "none" or not mode_val:
            return os.path.join(output_dir, artist)
        elif mode_val == "artist":
            return os.path.join(output_dir, artist)
        elif mode_val == "album":
            # 使用视频标题作为"专辑"名
            album = self._sanitize_filename(task.video_info.title[:50]) if task.video_info else "未知专辑"
            return os.path.join(output_dir, artist, album)
        elif mode_val == "type":
            # 使用视频分区名归类
            tname = self._sanitize_filename(video_info.tname) if video_info and video_info.tname else "其他"
            return os.path.join(output_dir, tname, artist)
        return os.path.join(output_dir, artist)

    def _download_audio_only(self, task: DownloadTask):
        """仅下载音频流并转换为指定格式"""
        from .bilibili_api import BilibiliClient

        client = BilibiliClient()
        episode = task.episode

        # 如果没有 episode（cid），先获取视频信息
        if not episode or not episode.cid:
            video_info = client.get_video_info(task.video_info.bvid)
            if video_info and video_info.episodes:
                episode = video_info.episodes[0]
                task.episode = episode
                # 更新 video_info 中的分区信息
                if task.video_info:
                    task.video_info.tname = video_info.tname
            else:
                raise RuntimeError("无法获取视频 CID")
        else:
            # 已有 episode，但仍需获取完整视频信息用于封面和归类
            video_info = client.get_video_info(task.video_info.bvid)
            if video_info and task.video_info:
                task.video_info.tname = video_info.tname
                task.video_info.cover_url = video_info.cover_url or task.video_info.cover_url

        # 获取播放地址
        play_data = client.get_play_url(
            task.video_info.bvid,
            episode.cid,
            task.quality.value
        )

        if not play_data:
            raise RuntimeError("无法获取播放地址")

        audio_url = play_data.get("audio_url", "")
        if not audio_url:
            raise RuntimeError("该视频没有独立的音频流")

        # 根据归类模式确定输出目录
        uploader_dir = self._get_audio_output_dir(task, video_info)
        os.makedirs(uploader_dir, exist_ok=True)

        base_name = self._build_filename(task)

        # 下载原始音频流（B站 DASH 音频流为 AAC 编码，封装在 fMP4/m4s 容器中）
        audio_m4s_path = os.path.join(uploader_dir, f"{base_name}_audio.m4s")
        self._download_with_resume(audio_url, audio_m4s_path, task)

        # 确定目标格式
        from .config import AudioFormat
        audio_format = _cfg().get(_cfg().audio_format)
        target_ext = "mp3"
        if hasattr(audio_format, 'value'):
            target_ext = audio_format.value

        # 尝试使用 ffmpeg 转换格式
        final_path = os.path.join(uploader_dir, f"{base_name}.{target_ext}")

        # 准备封面图路径（用于嵌入）
        cover_path = None
        if _cfg().get(_cfg().embed_cover) and task.video_info and task.video_info.cover_url:
            cover_path = os.path.join(uploader_dir, f"{base_name}_cover.jpg")
            try:
                from .network import download_file
                download_file(task.video_info.cover_url, cover_path)
                logger.info(f"封面下载成功: {cover_path}")
            except Exception as e:
                logger.warning(f"封面下载失败: {e}")
                cover_path = None

        try:
            self._convert_audio(audio_m4s_path, final_path, target_ext, cover_path)
            # 转换成功，删除临时文件
            if os.path.exists(audio_m4s_path):
                os.remove(audio_m4s_path)
            logger.info(f"音频已转换并保存为 {target_ext.upper()}: {final_path}")
        except Exception as e:
            logger.warning(f"ffmpeg 转换失败（{e}），将保存为原始 AAC/m4a 格式")
            # 转换失败：直接将 m4s 重命名为 m4a（AAC 音频，大多数播放器支持）
            fallback_path = os.path.join(uploader_dir, f"{base_name}.m4a")
            try:
                if os.path.exists(fallback_path):
                    os.remove(fallback_path)
                os.rename(audio_m4s_path, fallback_path)
                final_path = fallback_path
                logger.info(f"音频已保存为 M4A: {final_path}")
            except Exception as rename_err:
                logger.error(f"重命名为 m4a 也失败: {rename_err}")
                final_path = audio_m4s_path

        # 清理临时封面文件
        if cover_path and os.path.exists(cover_path):
            try:
                os.remove(cover_path)
            except Exception:
                pass

        task.file_path = final_path
        task.status = DownloadStatus.COMPLETED
        logger.info(f"音频下载完成: {final_path}")

    def _find_ffmpeg(self) -> str:
        """查找可用的 ffmpeg 可执行文件，返回路径或空字符串"""
        import subprocess
        # 1. 系统 PATH 中的 ffmpeg
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return "ffmpeg"
        except Exception:
            pass
        # 2. PyInstaller 打包模式：从解压临时目录 _MEIPASS/bin/ 查找
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            packed_ffmpeg = os.path.join(sys._MEIPASS, "bin", "ffmpeg.exe")
            if os.path.exists(packed_ffmpeg):
                return packed_ffmpeg
        # 3. 项目 bin/ 中的 ffmpeg（开发模式，放在 Bili23_core/bin/ffmpeg.exe）
        bundle_ffmpeg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "bin", "ffmpeg.exe"
        )
        if os.path.exists(bundle_ffmpeg):
            return bundle_ffmpeg
        return ""

    def _convert_audio(self, input_path: str, output_path: str, format: str = "mp3",
                       cover_path: str = None):
        """使用 ffmpeg 转换音频格式，可选嵌入封面图"""
        import subprocess

        ffmpeg_bin = self._find_ffmpeg()
        if not ffmpeg_bin:
            raise RuntimeError("未找到 ffmpeg，无法转换格式")

        has_cover = cover_path and os.path.exists(cover_path)

        # 构建命令
        cmd = [ffmpeg_bin, "-y", "-i", input_path]
        if has_cover:
            cmd += ["-i", cover_path]

        # 音频编码
        acodec_args = []
        if format == "mp3":
            acodec_args = ["-acodec", "libmp3lame", "-q:a", "2"]
        elif format == "flac":
            acodec_args = ["-acodec", "flac"]
        elif format == "wav":
            acodec_args = ["-acodec", "pcm_s16le"]
        elif format == "aac":
            acodec_args = ["-acodec", "aac", "-b:a", "192k"]
        elif format == "opus":
            acodec_args = ["-acodec", "libopus", "-b:a", "128k"]

        if has_cover and format in ("mp3", "aac"):
            # 嵌入封面：用 -map 明确选择音频流和封面图流
            cmd += ["-map", "0:a:0", "-map", "1:0"]
            cmd += acodec_args
            cmd += ["-c:v:0", "mjpeg", "-id3v2_version", "3", "-write_id3v1", "1"]
        else:
            # 不嵌入封面
            cmd += ["-vn"]
            cmd += acodec_args

        cmd.append(output_path)

        logger.debug(f"ffmpeg 命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 转换失败 (code={result.returncode}): {result.stderr[:500]}")

    def _download_with_resume(self, url: str, save_path: str, task: DownloadTask):
        """支持断点续传的下载（支持实时进度反馈、暂停/取消响应、完整性校验）"""
        old_file_path = task.file_path
        task.file_path = save_path

        client = get_client()
        total_size = 0
        try:
            head_response = client.head(url, follow_redirects=True)
            if head_response.status_code == 200:
                total_size = int(head_response.headers.get("Content-Length", 0))
        except Exception:
            pass

        if total_size == 0:
            try:
                range_resp = client.get(
                    url, headers={"Range": "bytes=0-0"}, follow_redirects=True
                )
                if range_resp.status_code == 206:
                    content_range = range_resp.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_size = int(content_range.rsplit("/", 1)[-1])
                elif range_resp.status_code == 200:
                    total_size = int(range_resp.headers.get("Content-Length", 0))
            except Exception as e:
                logger.warning(f"获取文件大小失败: {e}")

        task.total_size = total_size
        logger.info(f"下载文件大小: {total_size} bytes, URL: {url[:80]}...")

        if total_size == 0:
            task.file_path = old_file_path
            self._stream_download(url, save_path, task)
            return

        # 磁盘空间检查，避免写满磁盘导致文件损坏
        self._check_disk_space(save_path, total_size)

        # 分片下载
        num_chunks = self._get_chunk_count(total_size)
        chunk_size = (total_size + num_chunks - 1) // num_chunks
        task.chunks_total = num_chunks

        # 断点续传：通过状态文件记录已完成分片，避免把预分配的空文件误判为已下载
        state_file = save_path + ".state.json"
        state = self._load_state(state_file, total_size, num_chunks, chunk_size)
        pre_completed = state["completed"]  # 之前已完成的分片索引
        base_bytes = state["base_bytes"]    # 之前已完成分片的字节数

        if not os.path.exists(save_path):
            # 主文件不存在时，之前完成分片的数据也已丢失，需全部重下
            pre_completed = set()
            base_bytes = 0
            self._create_empty_file(save_path, total_size)

        # 全局进度跟踪（线程安全）
        lock = threading.Lock()
        chunk_downloaded_dict: Dict[int, int] = {}  # chunk_idx -> 该分片已下载字节数
        completed_chunks: set = set()  # 本次新完成的分片

        # 最后一次全局通知时间（节流）
        task._last_progress_notify = 0.0
        task._sub_progress_last_bytes = 0

        def _save_state_locked():
            """将已完成分片写入状态文件（须在持有 lock 时调用）"""
            try:
                with open(state_file, "w") as f:
                    json.dump({
                        "total_size": total_size,
                        "num_chunks": num_chunks,
                        "completed": sorted(pre_completed | completed_chunks),
                    }, f)
            except Exception as e:
                logger.debug(f"写入状态文件失败: {e}")

        def _notify_global(force: bool = False):
            """汇总所有分片进度并通知全局（带节流）"""
            now = time.time()
            if not force and (now - task._last_progress_notify < 0.1):
                return
            task._last_progress_notify = now

            with lock:
                total = base_bytes
                for ch_idx in range(num_chunks):
                    if ch_idx in pre_completed:
                        continue
                    if ch_idx in completed_chunks:
                        # 完整的分片
                        ch_start = ch_idx * chunk_size
                        ch_end = min((ch_idx + 1) * chunk_size, total_size)
                        total += (ch_end - ch_start)
                    elif ch_idx in chunk_downloaded_dict:
                        total += chunk_downloaded_dict[ch_idx]
            self._update_progress(task, total_size, total, pre_completed | completed_chunks)

        def download_chunk_range(chunk_idx, start, end):
            chunk_file = f"{save_path}.chunk_{chunk_idx}"
            length = end - start

            # 检查此分片是否已下载（状态文件缺失时的兜底续传）
            if os.path.exists(chunk_file) and os.path.getsize(chunk_file) >= max(1, length):
                try:
                    self._merge_chunk(chunk_file, save_path, start)
                    if os.path.exists(chunk_file):
                        os.remove(chunk_file)
                except Exception as merge_err:
                    logger.warning(f"合并已下载分片失败 {chunk_idx}: {merge_err}")
                with lock:
                    completed_chunks.add(chunk_idx)
                    _save_state_locked()
                _notify_global(force=True)
                return

            # 暂停/取消时不再启动新的分片下载
            if not self._pause_event.is_set() or task.status != DownloadStatus.DOWNLOADING:
                return

            # 实时子进度回调
            def chunk_cb(downloaded_bytes: int):
                with lock:
                    chunk_downloaded_dict[chunk_idx] = downloaded_bytes
                _notify_global(force=False)

            downloaded = download_chunk(url, chunk_file, start, end, progress_callback=chunk_cb)

            # 下载期间被暂停/取消，保留分片文件以便续传
            if task.status != DownloadStatus.DOWNLOADING:
                return

            if downloaded >= length:
                # 合并分片到主文件
                try:
                    self._merge_chunk(chunk_file, save_path, start)
                    if os.path.exists(chunk_file):
                        try:
                            os.remove(chunk_file)
                        except Exception:
                            pass
                    with lock:
                        completed_chunks.add(chunk_idx)
                        _save_state_locked()
                except Exception as merge_err:
                    logger.warning(f"合并分片失败 {chunk_idx}: {merge_err}")
                _notify_global(force=True)
            else:
                # 分片不完整（服务端截断等），删除后重下
                logger.warning(f"分片 {chunk_idx} 下载不完整（{downloaded}/{length} bytes），将重试")
                try:
                    os.remove(chunk_file)
                except Exception:
                    pass

        threads = []
        for i in range(num_chunks):
            if i in pre_completed:
                continue
            start = i * chunk_size
            end = min(start + chunk_size, total_size)
            t = threading.Thread(
                target=download_chunk_range,
                args=(i, start, end),
                daemon=True
            )
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 清理未完成的分片
        for i in range(num_chunks):
            chunk_file = f"{save_path}.chunk_{i}"
            if os.path.exists(chunk_file):
                try:
                    os.remove(chunk_file)
                except Exception:
                    pass

        # 完整性校验：所有分片必须全部完成，且文件大小达标
        all_completed = (len(pre_completed) + len(completed_chunks)) >= num_chunks
        if all_completed and os.path.exists(save_path) and os.path.getsize(save_path) < total_size:
            all_completed = False

        if not all_completed:
            # 保留主文件与状态文件以便续传；不再强制标记完成
            if task.status == DownloadStatus.DOWNLOADING:
                task.status = DownloadStatus.FAILED
                task.error_message = "下载中断，部分分片未完成，可重新下载续传"
                self._notify_progress(task)
            raise DownloadInterrupted(task.error_message or "下载未完成")

        # 全部完成：删除状态文件，标记完成
        try:
            os.remove(state_file)
        except Exception:
            pass
        task.progress = 1.0
        task.downloaded_size = total_size
        self._notify_progress(task)
        task.file_path = old_file_path

    def _stream_download(self, url: str, save_path: str, task: DownloadTask,
                         max_retries: int = 3):
        """无法获取文件大小时的流式下载（支持断点续传与自动重试）"""
        from .network import get_client

        client = get_client()
        task.file_path = save_path
        downloaded = 0
        if os.path.exists(save_path):
            downloaded = os.path.getsize(save_path)

        for attempt in range(max_retries + 1):
            last_notify = 0
            try:
                headers = {"Range": f"bytes={downloaded}-"} if downloaded > 0 else {}
                with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"下载失败: HTTP {response.status_code}")

                    # 服务端不支持 Range 时需从头重新下载
                    if response.status_code == 200 and downloaded > 0:
                        downloaded = 0

                    mode = "wb" if downloaded == 0 else "ab"
                    with open(save_path, mode) as f:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                task.downloaded_size = downloaded
                                # 节流通知
                                now = time.time()
                                if now - last_notify >= 0.3:
                                    if hasattr(task, '_stream_last_bytes'):
                                        task.download_speed = (downloaded - task._stream_last_bytes) / (now - last_notify)
                                    task._stream_last_bytes = downloaded
                                    last_notify = now
                                    self._notify_progress(task)

                task.progress = 1.0
                task.downloaded_size = downloaded
                logger.info(f"流式下载完成: {save_path} ({downloaded} bytes)")
                return
            except Exception as e:
                if attempt < max_retries:
                    wait = (attempt + 1) * 2
                    logger.warning(
                        f"流式下载中断 (第{attempt + 1}/{max_retries}次): {e}，"
                        f"等待{wait}秒后续传"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"流式下载失败: {e}")
                raise

    def _get_chunk_count(self, total_size: int) -> int:
        """获取分片数量"""
        threads = _cfg().get(_cfg().download_thread)
        if total_size <= 0:
            return threads
        size_per_chunk = CHUNK_SIZE
        count = max(1, total_size // size_per_chunk)
        return min(count, threads * 4)

    def _create_empty_file(self, path: str, size: int):
        """创建文件并预分配空间（大文件用 seek，避免一次性分配巨大内存）"""
        if _cfg().get(_cfg().preallocate_file_space):
            with open(path, "wb") as f:
                if size > 0:
                    f.seek(size - 1)
                    f.write(b"\0")
        else:
            with open(path, "wb") as f:
                pass

    def _load_state(self, state_file: str, total_size: int, num_chunks: int,
                    chunk_size: int) -> dict:
        """读取断点续传状态文件；缺失或无效时返回空状态"""
        result = {"completed": set(), "base_bytes": 0}
        try:
            if not os.path.exists(state_file):
                return result
            with open(state_file, "r") as f:
                state = json.load(f)
            if state.get("total_size") != total_size or state.get("num_chunks") != num_chunks:
                return result
            base = 0
            completed = set()
            for i in state.get("completed", []):
                i = int(i)
                if i < 0 or i >= num_chunks:
                    continue
                completed.add(i)
                ch_start = i * chunk_size
                ch_end = min(ch_start + chunk_size, total_size)
                base += (ch_end - ch_start)
            result["completed"] = completed
            result["base_bytes"] = base
        except Exception as e:
            logger.warning(f"读取断点续传状态失败，将重新下载: {e}")
        return result

    def _check_disk_space(self, save_path: str, required: int):
        """检查目标磁盘空间是否充足，不足则抛出异常以避免文件损坏"""
        import shutil
        try:
            free = shutil.disk_usage(os.path.dirname(os.path.abspath(save_path))).free
        except Exception:
            return
        # 音视频分片同时落盘、合并时还需额外空间，按 2.5 倍预留
        need = int(required * 2.5)
        if free < required:
            raise RuntimeError(
                f"磁盘空间不足：文件需要 {required / 1024 / 1024:.0f} MB，"
                f"可用 {free / 1024 / 1024:.0f} MB"
            )
        if free < need:
            logger.warning(
                f"磁盘空间偏少：建议预留 {need / 1024 / 1024:.0f} MB（含合并临时空间），"
                f"当前可用 {free / 1024 / 1024:.0f} MB"
            )

    def _merge_chunk(self, chunk_file: str, save_path: str, start: int):
        """将分片文件按偏移写入主文件（分块拷贝，避免大分片占用过多内存）"""
        with open(save_path, "r+b") as f:
            f.seek(start)
            with open(chunk_file, "rb") as cf:
                while True:
                    buf = cf.read(1024 * 1024)
                    if not buf:
                        break
                    f.write(buf)

    def _update_progress(self, task: DownloadTask, total_size: int, downloaded_bytes: int,
                         completed_chunks: Optional[set] = None):
        """更新下载进度（支持精确字节进度和分片级进度）"""
        if total_size <= 0:
            return

        if downloaded_bytes > total_size:
            downloaded_bytes = total_size

        task.downloaded_size = downloaded_bytes
        task.progress = downloaded_bytes / total_size

        if completed_chunks is not None:
            task.chunks_total = self._get_chunk_count(total_size)
            task.chunks_completed = len(completed_chunks)

        # 计算下载速度
        now = time.time()
        if not hasattr(task, '_speed_last_time'):
            task._speed_last_time = now
            task._speed_last_bytes = downloaded_bytes
        else:
            elapsed = now - task._speed_last_time
            if elapsed >= 0.1:
                task.download_speed = max(0.0, (downloaded_bytes - task._speed_last_bytes) / elapsed)
                task._speed_last_time = now
                task._speed_last_bytes = downloaded_bytes

        self._notify_progress(task)

    def _download_danmaku(self, task: DownloadTask):
        """下载弹幕"""
        try:
            from .bilibili_api import BilibiliClient

            client = BilibiliClient()
            danmaku_data = client.get_danmaku(task.episode.cid)

            if not danmaku_data:
                raise RuntimeError("弹幕数据为空")

            output_dir = _cfg().get(_cfg().download_path)
            uploader_dir = os.path.join(output_dir, self._sanitize_filename(task.video_info.owner_name))
            safe_makedirs(uploader_dir)

            base_name = self._build_filename(task)
            danmaku_path = os.path.join(uploader_dir, f"{base_name}.xml")

            with open(danmaku_path, "wb") as f:
                f.write(danmaku_data)

            task.file_path = danmaku_path
            task.status = DownloadStatus.COMPLETED
            logger.info(f"弹幕下载完成: {danmaku_path}")
        except Exception as e:
            logger.error(f"弹幕下载失败: {e}")
            task.status = DownloadStatus.FAILED
            task.error_message = str(e)

    def _download_cover(self, task: DownloadTask):
        """下载封面"""
        try:
            if not task.video_info or not task.video_info.cover_url:
                raise RuntimeError("没有封面 URL")

            output_dir = _cfg().get(_cfg().download_path)
            uploader_dir = os.path.join(output_dir, self._sanitize_filename(task.video_info.owner_name))
            safe_makedirs(uploader_dir)

            base_name = self._build_filename(task)
            cover_path = os.path.join(uploader_dir, f"{base_name}.jpg")

            success = download_file(task.video_info.cover_url, cover_path)
            if not success:
                raise RuntimeError("封面下载失败")

            task.file_path = cover_path
            task.status = DownloadStatus.COMPLETED
            logger.info(f"封面下载完成: {cover_path}")
        except Exception as e:
            logger.error(f"封面下载失败: {e}")
            task.status = DownloadStatus.FAILED
            task.error_message = str(e)

    def _merge_video_audio(self, video_path: str, audio_path: str, output_path: str):
        """合并音视频（自动重试）"""
        # 先找到 ffmpeg 可执行文件路径
        ffmpeg_bin = self._find_ffmpeg()
        if not ffmpeg_bin:
            logger.warning("ffmpeg 未找到，无法合并音视频")
            import shutil
            shutil.copy2(video_path, output_path)
            logger.warning(f"已复制视频文件（无音频）: {output_path}")
            return

        max_attempts = 3
        for attempt in range(max_attempts):
            # 优先尝试 ffmpeg-python 库（会有更好的错误信息）
            try:
                import ffmpeg
                # 设置 ffmpeg 二进制路径，确保打包后也能找到
                os.environ["PATH"] = os.pathsep.join([
                    os.path.dirname(ffmpeg_bin),
                    os.environ.get("PATH", "")
                ])
                (
                    ffmpeg
                    .input(video_path)
                    .input(audio_path)
                    .output(
                        output_path,
                        vcodec="copy",
                        acodec="copy",
                        movflags="faststart",
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True, timeout=900)
                )
                logger.info(f"音视频合并成功: {output_path}")
                return
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"ffmpeg-python 合并失败: {e}")

            # 回退：使用命令行直接调用
            import subprocess
            cmd = [
                ffmpeg_bin, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=900)
                if result.returncode == 0:
                    logger.info(f"音视频合并成功（命令行）: {output_path}")
                    return
                logger.warning(f"ffmpeg 命令行合并失败 (code={result.returncode}): {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning("ffmpeg 合并超时")
            except FileNotFoundError:
                logger.warning(f"ffmpeg 未找到: {ffmpeg_bin}")
                break
            except Exception as e:
                logger.warning(f"ffmpeg 命令行合并异常: {e}")

            if attempt < max_attempts - 1:
                wait = (attempt + 1) * 2
                logger.info(f"等待{wait}秒后重试合并...")
                time.sleep(wait)

        # 所有合并尝试失败，直接复制视频文件
        logger.warning(f"音视频合并失败，使用视频文件作为最终结果: {video_path}")
        import shutil
        try:
            shutil.copy2(video_path, output_path)
            logger.info(f"已复制视频文件: {output_path}")
        except Exception as e:
            logger.error(f"复制视频文件失败: {e}")
            raise RuntimeError(f"音视频合并失败，且无法复制视频: {e}")

    def _build_filename(self, task: DownloadTask) -> str:
        """构建文件名"""
        title = self._sanitize_filename(task.video_info.title)
        # 处理 episode 为 None 的边界情况
        if not task.episode:
            return title
        part = self._sanitize_filename(task.episode.part or f"P{task.episode.page}")

        # 多分P视频：文件名包含分P信息，避免覆盖
        # is_multi_episode 由 VideoDetailDialog 或 get_video_info 设置
        # total_episodes > 1 作为补充判断
        if (task.video_info.is_multi_episode or task.video_info.total_episodes > 1) and task.episode.part:
            return f"{title}_{part}"
        return title

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名中的非法字符，确保生成的文件名在任何文件系统上都安全"""
        if not name or not isinstance(name, str):
            return "untitled"
        # 替换非法字符
        invalid_chars = '<>:"/\\|?*\x00-\x1f'
        for char in invalid_chars:
            name = name.replace(char, '_')
        # 去除首尾的空格和点（Windows 不允许文件名以点结尾）
        name = name.strip('. ')
        # 限制长度（Windows 最大 255 字符，留余量）
        name = name[:200] if len(name) > 200 else name
        # 防止空文件名
        if not name:
            name = "untitled"
        return name


def create_downloader() -> BilibiliDownloader:
    """创建下载器实例"""
    return BilibiliDownloader()
