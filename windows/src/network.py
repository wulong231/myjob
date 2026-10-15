"""
网络请求模块
============
封装 httpx 客户端，提供统一的请求接口。
支持连接复用、代理、重试等功能。
"""
import sys
import logging
import threading
import time
from typing import Optional, Dict, Any, Union, Callable
from urllib.parse import urlencode

import httpx

from .utils import retry

logger = logging.getLogger(__name__)

# 需要重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# 需要重试的异常类型
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    ConnectionError,
    TimeoutError,
)

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
    """网络请求封装类（支持自动重试）"""

    def __init__(self, url: str, method: str = "GET",
                 params: Optional[dict] = None,
                 json_data: Optional[dict] = None,
                 data: Optional[dict] = None,
                 headers: Optional[dict] = None,
                 timeout: Optional[float] = None,
                 max_retries: int = 2):
        self.url = url
        self.method = method.upper()
        self.params = params
        self.json_data = json_data
        self.data = data
        self.headers = headers or {}
        self.timeout = timeout
        self.max_retries = max_retries

    def _do_request(self) -> httpx.Response:
        """执行单个 HTTP 请求"""
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

    def request(self) -> httpx.Response:
        """发送请求并返回原始响应（自动重试可恢复的错误）"""
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._do_request()

                # 对可重试的状态码进行重试
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    wait = (attempt + 1) * 1.0
                    logger.warning(
                        f"HTTP {response.status_code} 对 {self.url[:60]}... "
                        f"第{attempt + 1}次重试，等待{wait:.0f}秒"
                    )
                    time.sleep(wait)
                    continue

                return response
            except RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait = (attempt + 1) * 1.5
                    logger.warning(
                        f"请求异常 {type(e).__name__}: {e} 对 {self.url[:60]}... "
                        f"第{attempt + 1}次重试，等待{wait:.0f}秒"
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    f"请求失败，已重试{self.max_retries}次: {self.url[:60]}...: {e}"
                )
                raise

        # 所有重试都失败
        if last_exception:
            raise last_exception
        return self._do_request()

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
                  chunk_size: int = 8192,
                  max_retries: int = 3) -> bool:
    """下载文件，支持进度回调（自动重试）"""
    # 规范化 URL：B站返回的封面地址以 // 开头（协议相对），需补全 https:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[7:]

    client = get_client()

    for attempt in range(max_retries + 1):
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
        except httpx.TimeoutException as e:
            logger.warning(f"下载超时 (第{attempt + 1}/{max_retries}次): {url[:60]}...")
            if attempt < max_retries:
                time.sleep((attempt + 1) * 2)
                continue
            logger.error(f"下载文件超时，已重试{max_retries}次: {e}")
            return False
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"下载文件失败 (第{attempt + 1}/{max_retries}次): {url[:60]}...: {e}")
                time.sleep((attempt + 1) * 1.5)
                continue
            logger.error(f"下载文件失败: {e}")
            return False
    return False


def download_chunk(url: str, file_path: str, start: int, end: int,
                    headers: Optional[dict] = None,
                    progress_callback: Optional[Callable[[int], None]] = None,
                    max_retries: int = 2) -> int:
    """下载文件的一个分片到独立临时文件，返回已下载字节数（自动重试）。
    progress_callback(downloaded_bytes) 在下载过程中被回调以报告实时进度。
    """
    client = get_client()
    chunk_size = end - start

    req_headers = {
        "Range": f"bytes={start}-{end - 1}",
    }
    if headers:
        req_headers.update(headers)

    for attempt in range(max_retries + 1):
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
        except (httpx.TimeoutException, httpx.ReadError, ConnectionError) as e:
            if attempt < max_retries:
                wait = (attempt + 1) * 1.5
                logger.warning(
                    f"分片下载失败 (第{attempt + 1}/{max_retries}次) "
                    f"[{start}-{end}]: {type(e).__name__}，等待{wait:.0f}秒后重试"
                )
                time.sleep(wait)
                continue
            logger.error(f"分片下载失败 [{start}-{end}]: {e}")
            return downloaded
        except Exception as e:
            logger.error(f"分片下载异常 [{start}-{end}]: {e}")
            return downloaded
    return 0
