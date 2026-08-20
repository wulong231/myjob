"""
Bilibili API 客户端
===================
封装 Bilibili 官方 API，提供搜索、视频信息获取、弹幕下载等功能。
包含 WBI 签名支持（新版搜索 API 需要）。
"""
import logging
import time
import hashlib
from typing import List, Optional, Dict
from urllib.parse import urlencode

from .network import api_get, api_post, NetworkRequest
from .models import VideoInfo, EpisodeInfo, SearchResult, UserInfo, VideoQuality

logger = logging.getLogger(__name__)

API_BASE = "https://api.bilibili.com"
SEARCH_API = f"{API_BASE}/x/web-interface/wbi/search/type"
VIDEO_API = f"{API_BASE}/x/web-interface/view"
VIDEO_PLAYURL_API = f"{API_BASE}/x/player/wbi/playurl"
DANMAKU_API = f"https://api.bilibili.com/x/v1/dm/list.so"
USER_API = f"{API_BASE}/x/space/wbi/acc/info"
USER_NAV_API = f"{API_BASE}/x/web-interface/nav"
FAVORITES_API = f"{API_BASE}/x/v3/fav/resource/list"

# WBI 签名用的混合表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]


def _get_mixin_key(orig: str) -> str:
    """对原始 key 进行混淆"""
    return ''.join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


"""def _enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    # 为请求参数添加 WBI 签名
    mixin_key = _get_mixin_key(img_key + sub_key)
    curr_time = int(time.time())
    params = dict(params)
    params['wts'] = curr_time
    # 按 key 排序后拼接
    params_str = urlencode(sorted(params.items()))
    w_rid = hashlib.md5((params_str + mixin_key).encode()).hexdigest()
    params['w_rid'] = w_rid
    return params"""

import random
def _enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    #为请求参数添加 WBI 签名（手动拼接，确保编码一致）
    mixin_key = _get_mixin_key(img_key + sub_key)
    curr_time = int(time.time())
    params = dict(params)
    params['wts'] = curr_time

    # 1. 按参数名ASCII码升序排序
    sorted_keys = sorted(params.keys())
    
    # 2. 手动拼接为 "key1=value1&key2=value2" 格式
    #    关键：使用 quote 确保空格编码为 %20，且不编码 ~
    from urllib.parse import quote
    parts = []
    for k in sorted_keys:
        v = params[k]
        # 将参数值转换为字符串并进行URL编码
        encoded_value = quote(str(v), safe='~')
        parts.append(f"{k}={encoded_value}")
    
    params_str = "&".join(parts)
    
    # 3. 计算签名
    w_rid = hashlib.md5((params_str + mixin_key).encode('utf-8')).hexdigest()
    params['w_rid'] = w_rid
    
    # 调试日志（验证后可以删除）
    logger.debug(f"签名原文: {params_str} + {mixin_key[:8]}...")
    
    return params


def _split_key(key_url: str) -> str:
    """从 URL 中提取 key（文件名去掉路径和扩展名）"""
    # e.g. https://i0.hdslb.com/bfs/wbi/7cd08e941c714b61b0f2c9b3c2b3b16b.png
    return key_url.rsplit('/', 1)[-1].split('.')[0]


class WbiSigner:
    """WBI 签名器，缓存 img_key 和 sub_key"""

    def __init__(self):
        self._img_key = ""
        self._sub_key = ""
        self._last_fetch = 0
        self._cache_ttl = 600  # 10 分钟缓存

    def _fetch_keys(self):
        """从 nav API 获取 img_key 和 sub_key"""
        try:
            response = api_get(USER_NAV_API)
            data = response.get("data", {})
            if not data:
                logger.warning(f"nav 响应无 data: code={response.get('code')} msg={response.get('message')}")
                return
            wbi_img = data.get("wbi_img", {})
            img_url = wbi_img.get("img_url", "")
            sub_url = wbi_img.get("sub_url", "")
            if img_url and sub_url:
                self._img_key = _split_key(img_url)
                self._sub_key = _split_key(sub_url)
                self._last_fetch = time.time()
                logger.info(f"WBI keys 已获取: img={self._img_key[:8]}..., sub={self._sub_key[:8]}...")
            else:
                logger.warning(f"nav 响应无 wbi_img: img_url={img_url!r}, sub_url={sub_url!r}")
        except Exception as e:
            logger.warning(f"获取 WBI keys 失败: {e}")

    def sign(self, params: dict) -> dict:
        """对参数进行 WBI 签名"""
        # if not self._img_key or time.time() - self._last_fetch > self._cache_ttl:
        self._fetch_keys()
        if self._img_key and self._sub_key:
            return _enc_wbi(dict(params), self._img_key, self._sub_key)
        # 如果获取不到 key，退回不加签名
        logger.warning("WBI 签名跳过：未获取到 keys")
        return params


# 全局签名器实例
_wbi_signer = WbiSigner()


class BilibiliClient:
    """Bilibili API 客户端"""

    def __init__(self):
        self._user_info: Optional[UserInfo] = None

    # ========== 搜索 ==========

    # 排序方式映射（UI 显示名 -> API 参数值）
    SEARCH_ORDER_MAP = {
        "综合排序": "totalrank",
        "最多播放": "click",
        "最新发布": "pubdate",
        "最多弹幕": "dm",
        "最多收藏": "stow",
    }

    def search(self, keyword: str, page: int = 1, order: str = "totalrank") -> SearchResult:
        """
        搜索视频

        Args:
            keyword: 搜索关键词
            page: 页码
            order: 排序方式 (totalrank/click/pubdate/dm/stow)
        """
        # 规范化 order 参数：支持中文 UI 名称和 API 参数值
        order = self.SEARCH_ORDER_MAP.get(order, order)

        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "order": order,
            "platform": "pc",
            "web_location": "1430654",
        }

        # 使用 WBI 签名
        signed_params = _wbi_signer.sign(params)
        has_wbi = 'w_rid' in signed_params
        logger.info(f"搜索请求: keyword={keyword!r}, page={page}, order={order}, "
                    f"wbi_signed={has_wbi}")

        try:
            response = api_get(SEARCH_API, params=signed_params)
            code = response.get("code")
            message = response.get("message", "")
            logger.info(f"搜索响应: code={code}, message={message!r}")

            if code != 0:
                logger.error(f"搜索失败: code={code}, message={message}")
                return SearchResult()

            data = response.get("data") or {}
            videos = []

            for item in data.get("result", []) or []:
                try:
                    video = self._parse_search_result(item)
                    if video:
                        videos.append(video)
                except Exception as e:
                    logger.debug(f"解析搜索结果失败: {e}")

            result = SearchResult(
                videos=videos,
                total=int(data.get("numResults", 0) or 0),
                page=page,
                page_size=int(data.get("pageSize", 20) or 20),
                has_more=bool(data.get("has_more", False)),
            )
            logger.info(f"搜索成功: 共 {result.total} 条结果，本页 {len(videos)} 条")
            return result
        except Exception as e:
            logger.error(f"搜索请求异常: {e}", exc_info=True)
            return SearchResult()

    def search_users(self, keyword: str, page: int = 1) -> dict:
        """
        搜索 UP 主

        Args:
            keyword: 搜索关键词
            page: 页码

        Returns:
            dict: {
                'users': [{'mid': int, 'name': str, 'face': str,
                           'fans': int, 'videos': int, 'sign': str}],
                'total': int,
                'has_more': bool
            }
        """
        params = {
            "search_type": "bili_user",
            "keyword": keyword,
            "page": page,
            "platform": "pc",
            "web_location": "1430654",
        }
        signed_params = _wbi_signer.sign(params)
        logger.info(f"UP主搜索请求: keyword={keyword!r}, page={page}")

        try:
            response = api_get(SEARCH_API, params=signed_params)
            code = response.get("code")
            if code != 0:
                logger.error(f"UP主搜索失败: code={code}")
                return {'users': [], 'total': 0, 'has_more': False}

            data = response.get("data") or {}
            users = []
            for item in data.get("result", []) or []:
                try:
                    users.append({
                        'mid': int(item.get('mid', 0)),
                        'name': item.get('uname', ''),
                        'face': item.get('upic', ''),
                        'fans': int(item.get('fans', 0)),
                        'videos': int(item.get('videos', 0)),
                        'sign': item.get('usign', ''),
                        'level': int(item.get('level', 0)),
                        'is_live': bool(item.get('live_room', {}).get('liveStatus', 0)),
                    })
                except Exception as e:
                    logger.debug(f"解析UP主结果失败: {e}")

            result = {
                'users': users,
                'total': int(data.get('numResults', 0) or 0),
                'has_more': bool(data.get('has_more', False)),
            }
            logger.info(f"UP主搜索成功: 共 {result['total']} 条结果，本页 {len(users)} 条")
            return result
        except Exception as e:
            logger.error(f"UP主搜索异常: {e}", exc_info=True)
            return {'users': [], 'total': 0, 'has_more': False}

    def get_user_videos(self, mid: int, page: int = 1, page_size: int = 30) -> SearchResult:
        """
        获取 UP 主投稿视频

        Args:
            mid: 用户 mid
            page: 页码
            page_size: 每页数量
        """
        # 注意：不手动构造 headers，统一由 network.get_client() 处理 Cookie 与 User-Agent。
        # 手动构造 headers 会覆盖客户端默认的完整 UA（含 Chrome 版本号）与 buvid3 Cookie，
        # 触发 B 站 -412 风控。客户端已配置完整 Chrome UA 和 buvid3/buvid4。
        params = {
            "mid": mid,
            "pn": page,
            "ps": page_size,
            "order": "pubdate",
            "platform": "web",
            "web_location": "1550101",
        }
        # 需要 WBI 签名
        signed_params = _wbi_signer.sign(params)
        logger.info(f"获取UP主视频请求: mid={mid}, page={page}")
        try:
            response = api_get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
            code = response.get("code")
            if code != 0:
                logger.error(f"获取UP主视频失败: code={code}")
                return SearchResult()

            data = response.get("data") or {}
            list_data = data.get("list") or {}
            vlist = list_data.get("vlist") or []

            videos = []
            for item in vlist:
                try:
                    video = VideoInfo(
                        bvid=item.get("bvid", ""),
                        avid=int(item.get("aid", 0)),
                        title=item.get("title", ""),
                        owner_name=item.get("author", ""),
                        cover_url=item.get("pic", ""),
                        duration=item.get("length", 0) if isinstance(item.get("length"), int) else 0,
                        views=int(item.get("play", 0)),
                        description=item.get("description", ""),
                        pubdate=int(item.get("created", 0)),
                    )
                    videos.append(video)
                except Exception as e:
                    logger.debug(f"解析UP主视频失败: {e}")

            page_info = data.get("page") or {}
            result = SearchResult(
                videos=videos,
                total=int(page_info.get("count", 0) or 0),
                page=page,
                page_size=page_size,
                has_more=bool(page_info.get("count", 0) and
                              page * page_size < int(page_info.get("count", 0))),
            )
            logger.info(f"UP主视频获取成功: 共 {result.total} 条，本页 {len(videos)} 条")
            return result
        except Exception as e:
            logger.error(f"获取UP主视频异常: {e}", exc_info=True)
            return SearchResult()

    def _parse_search_result(self, item: dict) -> Optional[VideoInfo]:
        """解析搜索结果项"""
        try:
            bvid = item.get("bvid", "")
            if not bvid:
                return None

            # duration 可能是 "177:10" 或 "1:30:00" 格式
            duration_str = str(item.get("duration", "0"))
            duration_seconds = self._parse_duration(duration_str)

            # play 可能是字符串
            play_str = str(item.get("play", "0"))
            play = int(play_str.replace(",", "")) if play_str else 0

            return VideoInfo(
                bvid=bvid,
                avid=int(item.get("id", 0)),
                title=self._clean_title(item.get("title", "")),
                owner_name=item.get("author", ""),
                cover_url=item.get("pic", ""),
                duration=duration_seconds,
                views=play,
                danmaku_count=int(item.get("video_review", 0)),
                tname=item.get("typename", ""),
                pubdate=int(item.get("pubdate", 0)),
                description=item.get("description", ""),
            )
        except Exception as e:
            logger.debug(f"解析搜索结果项失败: {e}, item keys: {list(item.keys())[:10]}")
            return None

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """将 'MM:SS' 或 'H:MM:SS' 格式的时长转为秒数"""
        try:
            parts = duration_str.strip().split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:
                return int(parts[0])
        except (ValueError, TypeError):
            pass
        return 0

    def _clean_title(self, title: str) -> str:
        """清理标题中的高亮标签"""
        import re
        return re.sub(r'<[^>]+>', '', title)

    # ========== 视频信息 ==========

    def get_video_info(self, bvid: str) -> Optional[VideoInfo]:
        """获取视频详细信息"""
        try:
            response = api_get(VIDEO_API, params={"bvid": bvid})
            if response.get("code") != 0:
                logger.error(f"获取视频信息失败: {response.get('message')}")
                return None

            data = response["data"]
            video = VideoInfo(
                bvid=bvid,
                avid=data.get("aid", 0),
                title=data.get("title", ""),
                description=data.get("desc", ""),
                owner_name=data.get("owner", {}).get("name", ""),
                owner_face=data.get("owner", {}).get("face", ""),
                duration=data.get("duration", 0),
                cover_url=data.get("pic", ""),
                views=data.get("stat", {}).get("view", 0),
                danmaku_count=data.get("stat", {}).get("danmaku", 0),
                favorites=data.get("stat", {}).get("favorite", 0),
                likes=data.get("stat", {}).get("like", 0),
                tname=data.get("tname", ""),
                pubdate=data.get("pubdate", 0),
                total_episodes=data.get("videos", 1),
                is_multi_episode=data.get("videos", 1) > 1,
            )

            # 解析分P
            for page in data.get("pages", []):
                episode = EpisodeInfo(
                    page=page.get("page", 1),
                    cid=page.get("cid", 0),
                    part=page.get("part", ""),
                    duration=page.get("duration", 0),
                )
                video.episodes.append(episode)

            return video
        except Exception as e:
            logger.error(f"获取视频信息异常: {e}")
            return None

    def get_play_url(self, bvid: str, cid: int, quality: int = 100) -> Optional[Dict]:
        """获取视频播放地址"""
        try:
            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": quality,
                "fnval": 16,  # DASH 格式
                "fourk": 1,
            }

            response = api_get(VIDEO_PLAYURL_API, params=params)
            if response.get("code") != 0:
                logger.error(f"获取播放地址失败: {response.get('message')}")
                return None

            data = response["data"]
            result = {
                "quality": data.get("quality", 0),
                "accept_quality": data.get("accept_quality", []),
            }

            # DASH 格式
            dash = data.get("dash", {})
            if dash:
                video_dash = dash.get("video", [])
                audio_dash = dash.get("audio", [])

                if video_dash:
                    best_video = max(video_dash, key=lambda x: x.get("id", 0))
                    result["video_url"] = best_video.get("baseUrl", "")
                    result["video_id"] = best_video.get("id", 0)
                    result["video_codecs"] = best_video.get("codecs", "")
                    result["video_bandwidth"] = best_video.get("bandwidth", 0)

                if audio_dash:
                    best_audio = max(audio_dash, key=lambda x: x.get("id", 0))
                    result["audio_url"] = best_audio.get("baseUrl", "")
                    result["audio_id"] = best_audio.get("id", 0)
                    result["audio_bandwidth"] = best_audio.get("bandwidth", 0)

            return result
        except Exception as e:
            logger.error(f"获取播放地址异常: {e}")
            return None

    # ========== 用户信息 ==========

    def get_user_info(self) -> Optional[UserInfo]:
        """获取当前登录用户信息"""
        try:
            response = api_get(USER_NAV_API)
            if response.get("code") != 0:
                logger.debug(f"获取用户信息失败: {response.get('message')}")
                return None

            data = response["data"]
            self._user_info = UserInfo(
                mid=data.get("mid", 0),
                name=data.get("uname", ""),
                avatar=data.get("up", {}).get("face", "") if isinstance(data.get("up"), dict) else data.get("face", ""),
                level=data.get("level_info", {}).get("current_level", 0),
                exp=data.get("level_info", {}).get("current_exp", 0),
                coin=data.get("money", 0),
                is_login=data.get("isLogin", False),
            )

            # 保存用户信息到配置
            from .config import get_config
            c = get_config()
            if self._user_info.mid:
                c.set(c.user_mid, str(self._user_info.mid))
            if self._user_info.name:
                c.set(c.user_name, self._user_info.name)
            if self._user_info.avatar:
                c.set(c.user_avatar, self._user_info.avatar)
            c.set(c.user_level, self._user_info.level)

            return self._user_info
        except Exception as e:
            logger.debug(f"获取用户信息异常: {e}")
            return None

    def check_login_status(self) -> dict:
        """检查登录状态"""
        try:
            response = api_get(USER_NAV_API)
            return {
                "success": response.get("code") == 0,
                "data": response.get("data", {}),
                "message": response.get("message", ""),
            }
        except Exception as e:
            return {
                "success": False,
                "data": {},
                "message": str(e),
            }

    # ========== 收藏夹 ==========

    def get_favorite_folders(self) -> List[Dict]:
        """获取用户创建的收藏夹列表"""
        try:
            from .config import get_config
            c = get_config()
            mid = c.get(c.user_mid)
            if not mid:
                # 如果没有 mid，先获取用户信息
                user_info = self.get_user_info()
                if user_info:
                    mid = user_info.mid
            if not mid:
                logger.warning("无法获取用户 mid")
                return []

            url = f"https://api.bilibili.com/x/v3/fav/folder/created/list-all?up_mid={mid}"
            response = api_get(url)
            if response.get("code") != 0:
                logger.error(f"获取收藏夹列表失败: {response.get('message')}")
                return []

            folders = []
            for item in response.get("data", {}).get("list", []):
                folders.append({
                    "id": item.get("id", 0),
                    "title": item.get("title", ""),
                    "media_count": item.get("media_count", 0),
                    "cover": item.get("cover", ""),
                    "mid": item.get("mid", 0),
                })
            return folders
        except Exception as e:
            logger.error(f"获取收藏夹列表异常: {e}")
            return []

    def get_favorite_videos(self, media_id: int, page: int = 1, page_size: int = 20) -> Dict:
        """获取收藏夹内的视频列表"""
        try:
            params = {
                "media_id": media_id,
                "pn": page,
                "ps": page_size,
                "keyword": "",
                "order": "mtime",
                "type": 0,
                "tid": 0,
                "platform": "web",
                "web_location": "333.1387",
            }
            response = api_get(FAVORITES_API, params=params)
            if response.get("code") != 0:
                logger.error(f"获取收藏夹内容失败: {response.get('message')}")
                return {"videos": [], "total": 0}

            data = response.get("data", {})
            videos = []

            for item in data.get("medias", []) or []:
                try:
                    bvid = item.get("bvid", "")
                    if not bvid:
                        continue
                    duration_str = str(item.get("duration", "0"))
                    duration_seconds = self._parse_duration(duration_str)
                    play_info = item.get("cnt_info", {})
                    video = VideoInfo(
                        bvid=bvid,
                        avid=int(item.get("id", 0)),
                        title=item.get("title", ""),
                        owner_name=item.get("upper", {}).get("name", ""),
                        cover_url=item.get("cover", ""),
                        duration=duration_seconds,
                        views=int(play_info.get("play", 0)),
                        danmaku_count=int(play_info.get("danmaku", 0)),
                        favorites=int(play_info.get("collect", 0)),
                        pubdate=int(item.get("pubtime", 0)),
                        description=item.get("intro", ""),
                    )
                    videos.append(video)
                except Exception as e:
                    logger.debug(f"解析收藏夹视频失败: {e}")

            info = data.get("info", {})
            return {
                "videos": videos,
                "total": info.get("media_count", 0),
                "title": info.get("title", ""),
            }
        except Exception as e:
            logger.error(f"获取收藏夹内容异常: {e}")
            return {"videos": [], "total": 0}

    # ========== 弹幕 ==========

    def get_danmaku(self, cid: int) -> bytes:
        """获取弹幕 XML"""
        try:
            response = NetworkRequest(
                f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}"
            ).request()
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"获取弹幕失败: {e}")
            return b""

    # ========== 收藏夹 ==========


