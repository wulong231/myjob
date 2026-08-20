"""
网络请求模块
============
封装 httpx 客户端，提供统一的请求接口。
支持连接复用、代理、重试等功能。
"""
import sys
import logging
import threading
from typing import Optional, Dict, Any, Union, Callable
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_client: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def get_client() -> httpx.Client:
    """获取或创建全局 httpx 客户端"""
    global _client

    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _create_client()

    return _client


def _create_client() -> httpx.Client:
    """创建 httpx 客户端"""
    from .config import get_config, ProxyType

    config = get_config()

    limits = httpx.Limits(
        max_connections=config.get(config.download_thread),
        max_keepalive_connections=config.get(config.download_thread)
    )
    transport = httpx.HTTPTransport(retries=3)

    mounts = None
    if config.get(config.proxy_enabled):
        proxy_url = config.get(config.proxy_server)
        proxy_port = config.get(config.proxy_port)
        proxy_type = config.get(config.proxy_type)
        full_proxy = f"{proxy_type}://{proxy_url}:{proxy_port}"

        mounts = {
            "http://": httpx.HTTPTransport(proxy=full_proxy, retries=5),
            "https://": httpx.HTTPTransport(proxy=full_proxy, retries=5),
        }

    timeout = httpx.Timeout(config.get(config.request_timeout))

    client = httpx.Client(
        limits=limits,
        timeout=timeout,
        transport=transport,
        mounts=mounts,
        follow_redirects=True,
        headers={
            "Referer": "https://www.bilibili.com/",
            "User-Agent": config.get(config.user_agent),
        }
    )

    _apply_cookies(client)
    return client


def _apply_cookies(client: httpx.Client):
    """将配置中的 Cookie 应用到客户端"""
    from .config import get_config
    config = get_config()
    cookies = config.get_bilibili_cookies()
    for key, value in cookies.items():
        if value:
            client.cookies.set(
                name=key,
                value=value,
                domain=".bilibili.com",
                path="/"
            )


def update_cookies():
    """更新客户端的 Cookie（登录后调用）"""
    global _client
    if _client:
        _apply_cookies(_client)
        logger.debug("客户端Cookie已更新")


class NetworkRequest:
    """网络请求封装类"""

    def __init__(self, url: str, method: str = "GET",
                 params: Optional[dict] = None,
                 json_data: Optional[dict] = None,
                 data: Optional[dict] = None,
                 headers: Optional[dict] = None,
                 timeout: Optional[float] = None):
        self.url = url
        self.method = method.upper()
        self.params = params
        self.json_data = json_data
        self.data = data
        self.headers = headers or {}
        self.timeout = timeout

    def request(self) -> httpx.Response:
        """发送请求并返回原始响应"""
        client = get_client()

        kwargs = {
            "params": self.params,
            "headers": self.headers,
        }

        if self.json_data and self.method in ("POST", "PUT", "PATCH"):
            kwargs["json"] = self.json_data
        elif self.data and self.method in ("POST", "PUT", "PATCH"):
            kwargs["data"] = self.data

        if self.timeout:
            kwargs["timeout"] = self.timeout

        response = client.request(
            method=self.method,
            url=self.url,
            **kwargs
        )
        return response

    def json(self) -> dict:
        """发送请求并返回 JSON 数据"""
        response = self.request()
        response.raise_for_status()
        return response.json()

    def text(self) -> str:
        """发送请求并返回文本"""
        response = self.request()
        response.raise_for_status()
        return response.text

    def bytes(self) -> bytes:
        """发送请求并返回字节数据"""
        response = self.request()
        response.raise_for_status()
        return response.content


def api_get(url: str, params: Optional[dict] = None, **kwargs) -> dict:
    """快捷 GET 请求（返回 JSON）"""
    req = NetworkRequest(url, "GET", params=params, **kwargs)
    return req.json()


def api_post(url: str, json_data: Optional[dict] = None,
             data: Optional[dict] = None, **kwargs) -> dict:
    """快捷 POST 请求（返回 JSON）"""
    req = NetworkRequest(url, "POST", json_data=json_data, data=data, **kwargs)
    return req.json()


def download_file(url: str, save_path: str,
                  headers: Optional[dict] = None,
                  progress_callback=None,
                  chunk_size: int = 8192) -> bool:
    """下载文件，支持进度回调"""
    # 规范化 URL：B站返回的封面地址以 // 开头（协议相对），需补全 https:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[7:]

    client = get_client()

    try:
        with client.stream("GET", url, headers=headers or {}, follow_redirects=True) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            with open(save_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback:
                            progress_callback(downloaded, total_size)

        return True
    except Exception as e:
        logger.error(f"下载文件失败: {e}")
        return False


def download_chunk(url: str, file_path: str, start: int, end: int,
                    headers: Optional[dict] = None,
                    progress_callback: Optional[Callable[[int], None]] = None) -> int:
    """下载文件的一个分片到独立临时文件，返回已下载字节数。
    progress_callback(downloaded_bytes) 在下载过程中被回调以报告实时进度。
    """
    client = get_client()
    chunk_size = end - start

    req_headers = {
        "Range": f"bytes={start}-{end - 1}",
    }
    if headers:
        req_headers.update(headers)

    downloaded = 0
    try:
        with client.stream("GET", url, headers=req_headers, follow_redirects=True) as response:
            expected = int(response.headers.get("Content-Length", chunk_size))

            with open(file_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            try:
                                progress_callback(downloaded)
                            except Exception:
                                pass

        return downloaded
    except Exception as e:
        logger.error(f"分片下载失败 [{start}-{end}]: {e}")
        return downloaded
