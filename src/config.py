"""
配置管理模块
============
使用 qfluentwidgets 的 QConfig 机制进行配置持久化。
支持主题、下载、网络等各项配置。
"""
import sys
import logging
from enum import Enum
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QStandardPaths
from qfluentwidgets import (
    QConfig, ConfigItem, OptionsConfigItem, BoolValidator,
    OptionsValidator, RangeConfigItem, RangeValidator,
    EnumSerializer, qconfig, Theme
)

logger = logging.getLogger(__name__)


class Language(Enum):
    CHINESE = "zh_CN"
    TAIWAN = "zh_TW"
    ENGLISH = "en_US"


class ProxyType(Enum):
    NONE = "none"
    HTTP = "http"
    SOCKS5 = "socks5"


class DownloadStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoQuality(Enum):
    P360 = 16
    P480 = 32
    P720 = 80
    P1080 = 100
    P1080P = 116
    P1080P_PLUS = 127
    P4K = 126
    DOLBY = 125
    HDR = 120


class AudioFormat(Enum):
    MP3 = "mp3"
    FLAC = "flac"
    WAV = "wav"
    AAC = "aac"
    OPUS = "opus"


class WhenClose(Enum):
    MINIMIZE = "minimize"
    ALWAYS_ASK = "always_ask"
    EXIT = "exit"


class AudioCategoryMode(Enum):
    """音频归类模式"""
    NONE = "none"           # 不归类，直接放在艺术家目录
    BY_ARTIST = "artist"    # 按艺术家归类
    BY_ALBUM = "album"      # 按专辑（视频合集）归类
    BY_TYPE = "type"        # 按视频分区归类


class AppConfig(QConfig):
    """应用配置类"""

    # 基础设置
    language = OptionsConfigItem(
        "General", "Language", Language.CHINESE,
        OptionsValidator([Language.CHINESE, Language.TAIWAN, Language.ENGLISH]),
        EnumSerializer(Language)
    )
    theme = OptionsConfigItem(
        "General", "Theme", Theme.LIGHT,
        OptionsValidator([Theme.LIGHT, Theme.DARK, Theme.AUTO]),
        EnumSerializer(Theme)
    )
    mica_effect = ConfigItem("General", "MicaEffect", True, BoolValidator())
    stay_on_top = ConfigItem("General", "StayOnTop", False, BoolValidator())
    when_close_window = OptionsConfigItem(
        "General", "WhenClose", WhenClose.MINIMIZE,
        OptionsValidator([WhenClose.MINIMIZE, WhenClose.ALWAYS_ASK, WhenClose.EXIT]),
        EnumSerializer(WhenClose)
    )

    # 下载设置
    download_path = ConfigItem("Download", "Path", "")
    download_thread = RangeConfigItem(
        "Download", "ThreadCount", 3,
        RangeValidator(1, 10)
    )
    speed_limit_enabled = ConfigItem("Download", "SpeedLimitEnabled", False, BoolValidator())
    speed_limit_rate = RangeConfigItem(
        "Download", "SpeedLimitMBps", 10,
        RangeValidator(1, 100)
    )
    auto_extract_audio = ConfigItem("Download", "AutoExtractAudio", True, BoolValidator())
    skip_existing = ConfigItem("Download", "SkipExisting", True, BoolValidator())
    preallocate_file_space = ConfigItem("Download", "PreallocateFile", False, BoolValidator())
    video_quality = OptionsConfigItem(
        "Download", "VideoQuality", VideoQuality.P1080,
        OptionsValidator([
            VideoQuality.P360, VideoQuality.P480, VideoQuality.P720,
            VideoQuality.P1080, VideoQuality.P1080P, VideoQuality.P1080P_PLUS,
            VideoQuality.P4K, VideoQuality.DOLBY, VideoQuality.HDR
        ]),
        EnumSerializer(VideoQuality)
    )
    audio_format = OptionsConfigItem(
        "Download", "AudioFormat", AudioFormat.MP3,
        OptionsValidator([AudioFormat.MP3, AudioFormat.FLAC, AudioFormat.WAV, AudioFormat.AAC, AudioFormat.OPUS]),
        EnumSerializer(AudioFormat)
    )
    audio_category_mode = OptionsConfigItem(
        "Download", "AudioCategoryMode", AudioCategoryMode.BY_ARTIST,
        OptionsValidator([AudioCategoryMode.NONE, AudioCategoryMode.BY_ARTIST, AudioCategoryMode.BY_ALBUM, AudioCategoryMode.BY_TYPE]),
        EnumSerializer(AudioCategoryMode)
    )
    embed_cover = ConfigItem("Download", "EmbedCover", True, BoolValidator())

    # 音乐库路径（已弃用，改用 transfer 目录）
    # music_library_path = ConfigItem("Music", "LibraryPath", "")

    # 网络设置
    proxy_enabled = ConfigItem("Network", "ProxyEnabled", False, BoolValidator())
    proxy_type = OptionsConfigItem(
        "Network", "ProxyType", ProxyType.HTTP,
        OptionsValidator([ProxyType.HTTP, ProxyType.SOCKS5]),
        EnumSerializer(ProxyType)
    )
    proxy_server = ConfigItem("Network", "ProxyServer", "127.0.0.1")
    proxy_port = RangeConfigItem(
        "Network", "ProxyPort", 7890,
        RangeValidator(1, 65535)
    )
    request_timeout = RangeConfigItem(
        "Network", "Timeout", 30,
        RangeValidator(5, 300)
    )

    # B站用户相关
    user_agent = ConfigItem("Bilibili", "UserAgent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    is_login = ConfigItem("Bilibili", "IsLogin", False, BoolValidator())
    sessdata = ConfigItem("Bilibili", "SESSDATA", "")
    bili_jct = ConfigItem("Bilibili", "bili_jct", "")
    buvid3 = ConfigItem("Bilibili", "buvid3", "")
    buvid4 = ConfigItem("Bilibili", "buvid4", "")
    buvid_fp = ConfigItem("Bilibili", "buvid_fp", "")
    bili_ticket = ConfigItem("Bilibili", "bili_ticket", "")
    bili_ticket_expires = ConfigItem("Bilibili", "bili_ticket_expires", 0)
    uuid = ConfigItem("Bilibili", "_uuid", "")
    b_lsid = ConfigItem("Bilibili", "b_lsid", "")
    b_nut = ConfigItem("Bilibili", "b_nut", 0)
    buvid_expires = ConfigItem("Bilibili", "buvid_expires", 0)

    # 用户信息
    user_mid = ConfigItem("User", "MID", "")
    user_name = ConfigItem("User", "Name", "")
    user_avatar = ConfigItem("User", "Avatar", "")
    user_level = ConfigItem("User", "Level", 0)
    is_expired = ConfigItem("User", "IsExpired", False, BoolValidator())

    # 首次使用标记
    tutorial_dialog_shown = ConfigItem("Flags", "TutorialShown", False, BoolValidator())
    accepted_terms = ConfigItem("Flags", "AcceptedTerms", False, BoolValidator())
    silent_start = ConfigItem("Flags", "SilentStart", False, BoolValidator())

    # 音频播放器偏好
    # EQ 增益列表（10 频段，-12~+12），以 JSON 字符串形式持久化
    eq_gains = ConfigItem("Audio", "EqGains", "[0,0,0,0,0,0,0,0,0,0]")
    # 歌词显示偏移（毫秒，正值延后，负值提前）
    lyrics_offset_ms = ConfigItem("Audio", "LyricsOffsetMs", 0, RangeValidator(-10000, 10000))
    # 全局快捷键配置（JSON 字符串）
    global_hotkeys = ConfigItem(
        "Audio", "GlobalHotkeys",
        '{"play_pause": "ctrl+alt+space", "prev": "ctrl+alt+left", "next": "ctrl+alt+right", "vol_up": "ctrl+alt+up", "vol_down": "ctrl+alt+down"}'
    )

    def __init__(self):
        super().__init__()
        self._init_download_path()

    def _init_download_path(self):
        """初始化下载路径"""
        path = self.get(self.download_path)
        if not path:
            default_path = str(Path.cwd() / "downloads")
            self.set(self.download_path, default_path, save=False)
        Path(self.get(self.download_path)).mkdir(parents=True, exist_ok=True)

    def get_bilibili_cookies(self) -> dict:
        """获取当前存储的Bilibili Cookie字典"""
        cookies = {}
        for key in ['sessdata', 'bili_jct', 'buvid3', 'buvid4', 'buvid_fp',
                    'bili_ticket', 'uuid', 'b_lsid', 'b_nut']:
            value = self.get(getattr(self, key, None))
            if value:
                cookie_name_map = {
                    'sessdata': 'SESSDATA',
                    'bili_jct': 'bili_jct',
                    'buvid3': 'buvid3',
                    'buvid4': 'buvid4',
                    'buvid_fp': 'buvid_fp',
                    'bili_ticket': 'bili_ticket',
                    'uuid': '_uuid',
                    'b_lsid': 'b_lsid',
                    'b_nut': 'b_nut',
                }
                cookies[cookie_name_map.get(key, key)] = str(value)
        return cookies

    def set_login_cookies(self, cookies: dict):
        """设置登录Cookie"""
        if 'SESSDATA' in cookies:
            self.set(self.sessdata, cookies['SESSDATA'])
            self.set(self.is_login, True)
        if 'bili_jct' in cookies:
            self.set(self.bili_jct, cookies['bili_jct'])
        if 'buvid3' in cookies:
            self.set(self.buvid3, cookies['buvid3'])
        if 'buvid4' in cookies:
            self.set(self.buvid4, cookies['buvid4'])
        if '_uuid' in cookies:
            self.set(self.uuid, cookies['_uuid'])
        if 'b_lsid' in cookies:
            self.set(self.b_lsid, cookies['b_lsid'])
        if 'b_nut' in cookies:
            self.set(self.b_nut, cookies['b_nut'])
        if 'bili_ticket' in cookies:
            self.set(self.bili_ticket, cookies['bili_ticket'])

    def clear_login_cookies(self):
        """清除登录Cookie"""
        self.set(self.sessdata, "")
        self.set(self.bili_jct, "")
        self.set(self.is_login, False)
        self.set(self.user_mid, "")
        self.set(self.user_name, "")
        self.set(self.is_expired, False)


def setup_config() -> AppConfig:
    """初始化全局配置"""
    global _config_instance, config
    config_dir = Path.cwd() / ".bili23" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    _config_instance = AppConfig()
    # 必须传入 config 实例，否则 AppConfig.file 不会被设置为正确路径，
    # 导致 set() 时保存到默认的 config/config.json 而非 .bili23/config/config.json
    qconfig.load(str(config_path), _config_instance)
    # 显式设置 file，确保后续 set() 触发的自动保存写入正确路径
    _config_instance.file = Path(config_path)
    config = _config_instance
    logger.info(f"配置文件路径: {config_path}")
    logger.debug(f"配置实例 file 属性: {_config_instance.file}")
    return _config_instance


def get_config() -> AppConfig:
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig()
    return _config_instance


def save_config(config: AppConfig):
    """保存配置"""
    # QConfig.save() 不接受参数，使用 self._cfg.file（在 load 时已设置）
    # config.save() 会写入 config.file 指向的路径
    config.save()
    logger.debug(f"配置已保存到: {config.file}")


# 全局配置实例（延迟初始化）
_config_instance: Optional[AppConfig] = None

# 便捷访问：config 作为全局别名（需先调用 setup_config() 或 get_config()）
config: Optional[AppConfig] = None


def _ensure_initialized():
    """确保配置已初始化（在 QApplication 创建后调用）"""
    global _config_instance, config
    if _config_instance is None:
        _config_instance = AppConfig()
        config = _config_instance
    return _config_instance
