"""
数据模型模块
============
定义视频信息、下载任务等数据类。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class VideoQuality(Enum):
    """视频画质"""
    P360 = 16
    P480 = 32
    P720 = 80
    P1080 = 100
    P1080P = 116
    P1080P_PLUS = 127
    P4K = 126
    DOLBY = 125
    HDR = 120


class DownloadStatus(Enum):
    """下载状态"""
    PENDING = "pending"
    PARSING = "parsing"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaType(Enum):
    """媒体类型"""
    VIDEO = "video"
    AUDIO = "audio"
    DANMAKU = "danmaku"
    SUBTITLE = "subtitle"
    COVER = "cover"
    METADATA = "metadata"


@dataclass
class VideoInfo:
    """视频信息"""
    bvid: str
    avid: int
    title: str
    description: str = ""
    owner_name: str = ""
    owner_face: str = ""
    duration: int = 0
    cover_url: str = ""
    pubdate: int = 0
    views: int = 0
    danmaku_count: int = 0
    favorites: int = 0
    likes: int = 0
    tname: str = ""
    episodes: List['EpisodeInfo'] = field(default_factory=list)
    total_episodes: int = 0
    is_multi_episode: bool = False


@dataclass
class EpisodeInfo:
    """分P信息"""
    page: int = 1
    cid: int = 0
    part: str = ""
    duration: int = 0
    video_url: str = ""
    audio_url: str = ""
    quality: VideoQuality = VideoQuality.P1080
    file_size: int = 0


@dataclass
class DownloadTask:
    """下载任务"""
    task_id: str = ""
    video_info: Optional[VideoInfo] = None
    episode: Optional[EpisodeInfo] = None
    download_type: MediaType = MediaType.VIDEO
    quality: VideoQuality = VideoQuality.P1080
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    downloaded_size: int = 0
    total_size: int = 0
    download_speed: float = 0.0
    file_path: str = ""
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 3
    chunks_total: int = 0
    chunks_completed: int = 0
    actual_quality: int = 0  # 实际下载的画质码（如 80=720P, 100=1080P）


@dataclass
class UserInfo:
    """用户信息"""
    mid: int = 0
    name: str = ""
    avatar: str = ""
    level: int = 0
    exp: int = 0
    coin: int = 0
    is_login: bool = False
    is_expired: bool = False


@dataclass
class SearchResult:
    """搜索结果"""
    videos: List[VideoInfo] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_more: bool = False


@dataclass
class CookieInfo:
    """Cookie信息"""
    sessdata: str = ""
    bili_jct: str = ""
    buvid3: str = ""
    buvid4: str = ""
    _uuid: str = ""
    b_lsid: str = ""
    b_nut: int = 0
    bili_ticket: str = ""
    bili_ticket_expires: int = 0

    def to_dict(self) -> dict:
        return {
            'SESSDATA': self.sessdata,
            'bili_jct': self.bili_jct,
            'buvid3': self.buvid3,
            'buvid4': self.buvid4,
            '_uuid': self._uuid,
            'b_lsid': self.b_lsid,
            'b_nut': str(self.b_nut),
            'bili_ticket': self.bili_ticket,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CookieInfo':
        return cls(
            sessdata=data.get('SESSDATA', ''),
            bili_jct=data.get('bili_jct', ''),
            buvid3=data.get('buvid3', ''),
            buvid4=data.get('buvid4', ''),
            _uuid=data.get('_uuid', ''),
            b_lsid=data.get('b_lsid', ''),
            b_nut=int(data.get('b_nut', 0)),
            bili_ticket=data.get('bili_ticket', ''),
        )

    def is_valid(self) -> bool:
        return bool(self.sessdata and self.bili_jct)
