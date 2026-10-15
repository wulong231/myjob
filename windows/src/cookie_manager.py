"""
Cookie 管理模块
===============
负责自动获取和刷新 Bilibili 所需的 Cookie。
支持从浏览器自动读取、手动输入、API 自动生成等方式。
"""
import sys
import os
import json
import time
import base64
import sqlite3
import shutil
import tempfile
import ctypes
import logging
import hmac
import hashlib
import random
import struct
import io
from pathlib import Path
from typing import Optional, Dict, List

from .config import get_config
from .network import api_get, api_post, update_cookies
from .models import CookieInfo

logger = logging.getLogger(__name__)


def _cfg():
    """获取当前全局配置"""
    return get_config()


def _cookie_backup_path() -> Path:
    """Cookie 独立备份文件路径（双保险，防止 QConfig 持久化失败）"""
    return Path.cwd() / ".bili23" / "config" / "cookie_backup.json"


def _save_cookie_backup(cookie_info: CookieInfo):
    """将登录 Cookie 写入独立备份文件，确保重启后可恢复"""
    try:
        backup_path = _cookie_backup_path()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "SESSDATA": cookie_info.sessdata or "",
            "bili_jct": cookie_info.bili_jct or "",
            "buvid3": cookie_info.buvid3 or "",
            "buvid4": cookie_info.buvid4 or "",
            "_uuid": cookie_info._uuid or "",
            "b_lsid": cookie_info.b_lsid or "",
            "b_nut": int(cookie_info.b_nut or 0),
            "bili_ticket": cookie_info.bili_ticket or "",
            "saved_at": int(time.time()),
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Cookie 备份已写入: {backup_path}")
    except Exception as e:
        logger.warning(f"Cookie 备份写入失败: {e}")


def _load_cookie_backup() -> Optional[dict]:
    """从独立备份文件读取 Cookie"""
    try:
        backup_path = _cookie_backup_path()
        if not backup_path.exists():
            return None
        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.debug(f"Cookie 备份读取失败: {e}")
        return None


def _clear_cookie_backup():
    """清除 Cookie 备份文件"""
    try:
        backup_path = _cookie_backup_path()
        if backup_path.exists():
            backup_path.unlink()
            logger.info("Cookie 备份已清除")
    except Exception as e:
        logger.debug(f"Cookie 备份清除失败: {e}")


class CookieManager:
    """Cookie 管理器"""

    BILIBILI_DOMAINS = [".bilibili.com", "bilibili.com", ".hdslb.com"]
    KEY_COOKIE_NAMES = ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', '_uuid']

    def __init__(self):
        self._cookie_info = CookieInfo()
        self._load_from_config()

    def _load_from_config(self):
        """从配置加载 Cookie，若配置缺失则尝试从备份文件恢复"""
        c = _cfg()
        sessdata = c.get(c.sessdata) or ""
        bili_jct = c.get(c.bili_jct) or ""

        # 若主配置中 SESSDATA 缺失，尝试从独立备份恢复
        if not sessdata:
            backup = _load_cookie_backup()
            if backup and backup.get("SESSDATA"):
                logger.info("主配置中 SESSDATA 缺失，从独立备份恢复登录 Cookie")
                sessdata = backup.get("SESSDATA", "")
                bili_jct = backup.get("bili_jct", "") or bili_jct
                # 回填到主配置
                try:
                    c.set(c.sessdata, sessdata)
                    c.set(c.bili_jct, bili_jct)
                    c.set(c.is_login, True)
                    c.set(c.is_expired, False)
                    from .config import save_config
                    save_config(c)
                except Exception as e:
                    logger.warning(f"回填备份 Cookie 到主配置失败: {e}")

        self._cookie_info = CookieInfo(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=c.get(c.buvid3),
            buvid4=c.get(c.buvid4),
            _uuid=c.get(c.uuid),
            b_lsid=c.get(c.b_lsid),
            b_nut=int(c.get(c.b_nut) or 0),
            bili_ticket=c.get(c.bili_ticket),
        )
        logger.debug(
            f"Cookie 加载完成: sessdata={'有' if sessdata else '无'}, "
            f"bili_jct={'有' if bili_jct else '无'}, is_login={c.get(c.is_login)}"
        )

    def _save_to_config(self):
        """保存 Cookie 到配置并持久化到磁盘"""
        c = _cfg()
        self._cookie_info = CookieInfo.from_dict(self._cookie_info.to_dict())
        c.set(c.sessdata, self._cookie_info.sessdata)
        c.set(c.bili_jct, self._cookie_info.bili_jct)
        c.set(c.buvid3, self._cookie_info.buvid3)
        c.set(c.buvid4, self._cookie_info.buvid4)
        c.set(c.uuid, self._cookie_info._uuid)
        c.set(c.b_lsid, self._cookie_info.b_lsid)
        c.set(c.b_nut, self._cookie_info.b_nut)
        c.set(c.bili_ticket, self._cookie_info.bili_ticket)
        # 持久化到磁盘，确保重启后 Cookie 不丢失
        try:
            from .config import save_config
            save_config(c)
        except Exception as e:
            logger.warning(f"Cookie 持久化失败: {e}")
        # 若存在登录 Cookie，额外写入独立备份文件（双保险）
        if self._cookie_info.sessdata:
            _save_cookie_backup(self._cookie_info)

    @property
    def info(self) -> CookieInfo:
        return self._cookie_info

    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return self._cookie_info.is_valid()

    def get_buvid(self) -> bool:
        """
        从 API 获取 buvid3、buvid4 等访客 Cookie。
        这些 Cookie 用于未登录状态下的基本功能。
        """
        try:
            response = api_get("https://api.bilibili.com/x/frontend/finger/spi")
            if response.get("code") == 0:
                data = response["data"]
                self._cookie_info.buvid3 = data.get("b_3", "")
                self._cookie_info.buvid4 = data.get("b_4", "")
                self._generate_uuid()
                self._generate_b_lsid()
                self._cookie_info.b_nut = int(time.time())
                self._generate_buvid_fp()
                self._save_to_config()
                update_cookies()
                logger.info("buvid 获取成功")
                return True
            else:
                logger.error(f"buvid 获取失败: {response.get('message')}")
                return False
        except Exception as e:
            logger.error(f"buvid 请求异常: {e}")
            return False

    def get_bili_ticket(self) -> bool:
        """获取 bili_ticket（Web 票据）"""
        try:
            timestamp = int(time.time())
            hexsign = self._hmac_sha256("XgwSnGZ1p", f"ts{timestamp}")

            response = api_post(
                "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                data={
                    "key_id": "ec02",
                    "hexsign": hexsign,
                    "context[ts]": str(timestamp),
                    "csrf": self._cookie_info.bili_jct,
                }
            )

            if response.get("code") == 0:
                self._cookie_info.bili_ticket = response["data"]["ticket"]
                self._save_to_config()
                update_cookies()
                logger.info("bili_ticket 获取成功")
                return True
            else:
                logger.debug(f"bili_ticket 获取失败: {response.get('message')}")
                return False
        except Exception as e:
            logger.debug(f"bili_ticket 请求异常: {e}")
            return False

    def _generate_uuid(self):
        """生成 _uuid"""
        t = int(time.time()) % 100000
        mp = list("123456789ABCDEF") + ["10"]
        pck = [8, 4, 4, 4, 12]
        gen_part = lambda x: "".join([random.choice(mp) for _ in range(x)])
        self._cookie_info._uuid = "-".join([gen_part(l) for l in pck]) + str(t).ljust(5, "0") + "infoc"

    def _generate_b_lsid(self):
        """生成 b_lsid"""
        ret = ""
        for _ in range(8):
            ret += hex(random.randint(0, 15))[2:].upper()
        ret = f"{ret}_{hex(int(time.time()))[2:].upper()}"
        self._cookie_info.b_lsid = ret

    def _generate_buvid_fp(self):
        """生成 buvid_fp（MurmurHash3 指纹）"""
        c = _cfg()
        key = c.get(c.user_agent)
        seed = 31
        source = io.BytesIO(bytes(key, "ascii"))
        m = self._murmur3_x64_128(source, seed)
        MOD = 1 << 64
        self._cookie_info.buvid_fp = f"{hex(m & (MOD - 1))[2:]}{hex(m >> 64)[2:]}"

    def _murmur3_x64_128(self, source: io.BufferedIOBase, seed: int) -> int:
        """MurmurHash3 x64_128 实现"""
        C1 = 0x87C37B91114253D5
        C2 = 0x4CF5AD432745937F
        C3 = 0x52DCE729
        C4 = 0x38495AB5
        R1, R2, R3, M = 27, 31, 33, 5
        h1, h2 = seed, seed
        processed = 0
        MOD = 1 << 64

        def fmix64(k: int) -> int:
            C1 = 0xFF51AFD7ED558CCD
            C2 = 0xC4CEB9FE1A85EC53
            R = 33
            tmp = k
            tmp ^= tmp >> R
            tmp = tmp * C1 % MOD
            tmp ^= tmp >> R
            tmp = tmp * C2 % MOD
            tmp ^= tmp >> R
            return tmp

        def rotate_left(x: int, k: int) -> int:
            bin_str = bin(x)[2:].rjust(64, "0")
            return int(bin_str[k:] + bin_str[:k], base=2)

        while True:
            read = source.read(16)
            processed += len(read)

            if len(read) == 16:
                k1 = struct.unpack("<q", read[:8])[0]
                k2 = struct.unpack("<q", read[8:])[0]
                h1 ^= (rotate_left(k1 * C1 % MOD, R2) * C2 % MOD)
                h1 = ((rotate_left(h1, R1) + h2) * M + C3) % MOD
                h2 ^= rotate_left(k2 * C2 % MOD, R3) * C1 % MOD
                h2 = ((rotate_left(h2, R2) + h1) * M + C4) % MOD

            elif len(read) == 0:
                h1 ^= processed
                h2 ^= processed
                h1 = (h1 + h2) % MOD
                h2 = (h2 + h1) % MOD
                h1 = fmix64(h1)
                h2 = fmix64(h2)
                h1 = (h1 + h2) % MOD
                h2 = (h2 + h1) % MOD
                return (h2 << 64) | h1
            else:
                k1, k2 = 0, 0
                if len(read) >= 15:
                    k2 ^= int(read[14]) << 48
                if len(read) >= 14:
                    k2 ^= int(read[13]) << 40
                if len(read) >= 13:
                    k2 ^= int(read[12]) << 32
                if len(read) >= 12:
                    k2 ^= int(read[11]) << 24
                if len(read) >= 11:
                    k2 ^= int(read[10]) << 16
                if len(read) >= 10:
                    k2 ^= int(read[9]) << 8
                if len(read) >= 9:
                    k2 ^= int(read[8])
                    k2 = rotate_left(k2 * C2 % MOD, R3) * C1 % MOD
                    h2 ^= k2
                if len(read) >= 8:
                    k1 ^= int(read[7]) << 56
                if len(read) >= 7:
                    k1 ^= int(read[6]) << 48
                if len(read) >= 6:
                    k1 ^= int(read[5]) << 40
                if len(read) >= 5:
                    k1 ^= int(read[4]) << 32
                if len(read) >= 4:
                    k1 ^= int(read[3]) << 24
                if len(read) >= 3:
                    k1 ^= int(read[2]) << 16
                if len(read) >= 2:
                    k1 ^= int(read[1]) << 8
                if len(read) >= 1:
                    k1 ^= int(read[0])
                k1 = rotate_left(k1 * C1 % MOD, R2) * C2 % MOD
                h1 ^= k1

    def _hmac_sha256(self, key: str, message: str) -> str:
        """HMAC-SHA256 签名"""
        key_bytes = key.encode("utf-8")
        message_bytes = message.encode("utf-8")
        hmac_obj = hmac.new(key_bytes, message_bytes, hashlib.sha256)
        return hmac_obj.digest().hex()

    def set_login_cookies(self, sessdata: str, bili_jct: str):
        """设置登录 Cookie，并标记为已登录"""
        logger.info(f"设置登录 Cookie: sessdata 长度={len(sessdata or '')}, bili_jct 长度={len(bili_jct or '')}")
        self._cookie_info.sessdata = sessdata
        self._cookie_info.bili_jct = bili_jct
        self._save_to_config()
        # 设置登录状态标记
        c = _cfg()
        c.set(c.is_login, True)
        c.set(c.is_expired, False)
        # 再次显式保存，确保 is_login 状态持久化
        try:
            from .config import save_config
            save_config(c)
        except Exception as e:
            logger.warning(f"保存 is_login 状态失败: {e}")
        update_cookies()
        logger.info("登录 Cookie 已设置并持久化")

        # 尝试获取用户信息（用户名、头像等）
        try:
            self._fetch_user_info()
        except Exception as e:
            logger.debug(f"获取用户信息失败: {e}")

    def _fetch_user_info(self):
        """获取并保存当前登录用户的信息"""
        c = _cfg()
        from .network import api_get
        resp = api_get("https://api.bilibili.com/x/web-interface/nav")
        if resp and resp.get("code") == 0:
            data = resp.get("data", {})
            mid = str(data.get("mid", ""))
            name = data.get("uname", "")
            avatar = data.get("face", "")
            level = data.get("level", 0)
            if mid:
                c.set(c.user_mid, mid)
            if name:
                c.set(c.user_name, name)
            if avatar:
                c.set(c.user_avatar, avatar)
            if level:
                c.set(c.user_level, level)
            logger.info(f"已获取用户信息: {name} (UID: {mid})")

    def clear_login_cookies(self):
        """清除登录 Cookie"""
        self._cookie_info.sessdata = ""
        self._cookie_info.bili_jct = ""
        self._save_to_config()
        _clear_cookie_backup()  # 同时清除独立备份
        update_cookies()
        c = _cfg()
        c.clear_login_cookies()
        logger.info("登录 Cookie 已清除")

    def get_all_cookies_dict(self) -> dict:
        """获取所有 Cookie 字典"""
        return self._cookie_info.to_dict()

    def init_guest_cookies(self):
        """初始化访客 Cookie（未登录状态）"""
        self.get_buvid()
        self.get_bili_ticket()


# 浏览器 Cookie 自动获取（保留原有功能，优化实现）
BROWSER_PATHS = {
    'chrome': {
        'name': 'Google Chrome',
        'user_data': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data'),
    },
    'edge': {
        'name': 'Microsoft Edge',
        'user_data': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data'),
    },
    '360': {
        'name': '360安全浏览器',
        'user_data': os.path.expandvars(r'%APPDATA%\360se6\User Data'),
    },
    'sogou': {
        'name': '搜狗浏览器',
        'user_data': os.path.expandvars(r'%APPDATA%\SogouExplorer\User Data'),
    },
    'qq': {
        'name': 'QQ浏览器',
        'user_data': os.path.expandvars(r'%LOCALAPPDATA%\Tencent\QQBrowser\User Data'),
    },
    'brave': {
        'name': 'Brave Browser',
        'user_data': os.path.expandvars(r'%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data'),
    },
}


def _decrypt_dpapi(encrypted_data: bytes) -> bytes:
    """使用 Windows DPAPI 解密数据"""
    if sys.platform != 'win32':
        raise RuntimeError('DPAPI 仅支持 Windows 系统')

    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.c_void_p),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    input_buf = ctypes.create_string_buffer(encrypted_data)
    input_addr = ctypes.addressof(input_buf)

    input_blob = DATA_BLOB()
    input_blob.cbData = len(encrypted_data)
    input_blob.pbData = input_addr

    output_blob = DATA_BLOB()
    output_blob.cbData = 0
    output_blob.pbData = 0

    success = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None, None, None, None, 0,
        ctypes.byref(output_blob)
    )

    if not success:
        error_code = kernel32.GetLastError()
        raise RuntimeError(f'DPAPI 解密失败，错误码: {error_code}')

    if output_blob.pbData == 0 or output_blob.cbData == 0:
        raise RuntimeError('DPAPI 解密返回空数据')

    result = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    return result


def _decrypt_aes_gcm(ciphertext: bytes, nonce: bytes, key: bytes) -> bytes:
    """使用 AES-GCM 解密 Cookie 值"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    if len(nonce) != 12:
        raise ValueError(f'nonce 长度错误: {len(nonce)}')
    if len(key) not in (16, 24, 32):
        raise ValueError(f'密钥长度错误: {len(key)}')

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext
    except InvalidTag:
        raise RuntimeError('AES-GCM 认证失败：密钥不正确或数据已损坏')


def _decode_cookie_value(plaintext: bytes) -> str:
    """将解密后的字节解码为 Cookie 字符串，处理二进制前缀"""
    try:
        text = plaintext.decode('utf-8')
        if text and all(0x20 <= ord(c) <= 0x7E for c in text):
            return text
    except UnicodeDecodeError:
        pass

    for start in range(len(plaintext)):
        try:
            text = plaintext[start:].decode('utf-8')
            if text and all(0x20 <= ord(c) <= 0x7E for c in text):
                if start > 0:
                    logger.debug(f'Cookie 值有 {start} 字节二进制前缀，已剥离')
                return text
        except UnicodeDecodeError:
            continue

    return plaintext.decode('latin-1', errors='replace')


def _get_encryption_keys(user_data_path: str) -> List[bytes]:
    """获取浏览器 AES 密钥"""
    ls_path = os.path.join(user_data_path, 'Local State')
    if not os.path.exists(ls_path):
        return []

    with open(ls_path, 'r', encoding='utf-8') as f:
        local_state = json.load(f)

    keys = []
    seen = set()

    # 标准 DPAPI 密钥
    encrypted_key_b64 = local_state.get('os_crypt', {}).get('encrypted_key', '')
    if encrypted_key_b64:
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            if encrypted_key.startswith(b'DPAPI'):
                data = encrypted_key[5:]
            else:
                data = encrypted_key
            aes_key = _decrypt_dpapi(data)
            if aes_key:
                key_hash = hash(aes_key)
                if key_hash not in seen:
                    seen.add(key_hash)
                    keys.append(aes_key)
        except Exception as e:
            logger.debug(f'标准 DPAPI 密钥获取失败: {e}')

    # Edge App-Bound 密钥
    for key_field in ['app_bound_encrypted_key', 'aster_app_bound_encrypted_key']:
        ab_key_b64 = local_state.get('os_crypt', {}).get(key_field, '')
        if ab_key_b64:
            try:
                ab_raw = base64.b64decode(ab_key_b64)
                if ab_raw.startswith(b'APPB'):
                    data = ab_raw[8:]
                    if data:
                        app_key = _decrypt_dpapi(data)
                        if app_key:
                            key_hash = hash(app_key)
                            if key_hash not in seen:
                                seen.add(key_hash)
                                keys.append(app_key)
            except Exception as e:
                logger.debug(f'App-Bound 密钥获取失败: {e}')

    return keys


def _find_cookie_dbs(user_data_path: str) -> List[str]:
    """查找浏览器所有 Profile 中的 Cookie 数据库"""
    cookie_dbs = []
    if not os.path.isdir(user_data_path):
        return cookie_dbs

    profiles = ['Default']
    for item in os.listdir(user_data_path):
        item_path = os.path.join(user_data_path, item)
        if os.path.isdir(item_path) and item.startswith('Profile '):
            profiles.append(item)

    for profile in profiles:
        for rel in ['Network/Cookies', 'Cookies']:
            p = os.path.join(user_data_path, profile, rel)
            if os.path.exists(p):
                cookie_dbs.append(p)
                break

    return cookie_dbs


def _safe_copy_db(src: str, dst: str, max_retries: int = 5) -> bool:
    """安全复制 Cookie 数据库"""
    for attempt in range(max_retries):
        try:
            shutil.copy2(src, dst)
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.3 * (attempt + 1))
        except Exception:
            break

    if sys.platform == 'win32':
        try:
            kernel32 = ctypes.windll.kernel32
            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            FILE_SHARE_DELETE = 0x00000004
            OPEN_EXISTING = 3
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

            handle = kernel32.CreateFileW(
                src, GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None, OPEN_EXISTING, 0, None
            )

            if handle != INVALID_HANDLE_VALUE and handle:
                file_size = kernel32.GetFileSize(handle, None)
                if file_size > 0 and file_size != 0xFFFFFFFF:
                    buf = ctypes.create_string_buffer(file_size)
                    bytes_read = ctypes.c_ulong(0)
                    success = kernel32.ReadFile(
                        handle, buf, file_size,
                        ctypes.byref(bytes_read), None
                    )
                    if success and bytes_read.value > 0:
                        with open(dst, 'wb') as f:
                            f.write(buf.raw[:bytes_read.value])
                        for ext in ['-wal', '-shm']:
                            wal_src = src + ext
                            wal_dst = dst + ext
                            if os.path.exists(wal_src):
                                try:
                                    shutil.copy2(wal_src, wal_dst)
                                except Exception:
                                    pass
                        return True
        except Exception:
            pass

    return False


def fetch_cookies_from_browser(browser_name: str) -> Optional[Dict[str, str]]:
    """从指定浏览器获取 Bilibili Cookie"""
    if browser_name not in BROWSER_PATHS:
        return None

    browser_info = BROWSER_PATHS[browser_name]
    user_data_path = browser_info['user_data']

    if not os.path.isdir(user_data_path):
        return None

    aes_keys = _get_encryption_keys(user_data_path)
    if not aes_keys:
        logger.debug(f'{browser_info["name"]} 获取 AES 密钥失败')
        return None

    cookie_dbs = _find_cookie_dbs(user_data_path)
    if not cookie_dbs:
        return None

    tmp_dir = tempfile.mkdtemp(prefix='bili_cookie_')
    tmp_db = os.path.join(tmp_dir, 'Cookies')

    try:
        for db_path in cookie_dbs:
            if not _safe_copy_db(db_path, tmp_db):
                continue

            try:
                conn = sqlite3.connect(tmp_db)
            except Exception:
                continue

            try:
                cursor = conn.cursor()
                cookies = {}

                for domain in CookieManager.BILIBILI_DOMAINS:
                    try:
                        cursor.execute(
                            'SELECT name, encrypted_value FROM cookies '
                            'WHERE host_key LIKE ?',
                            (f'%{domain}%',)
                        )
                    except sqlite3.OperationalError:
                        continue

                    for name, encrypted_value in cursor.fetchall():
                        if name not in CookieManager.KEY_COOKIE_NAMES:
                            continue
                        if not encrypted_value or len(encrypted_value) < 16:
                            continue

                        if encrypted_value[:3] in (b'v10', b'v20'):
                            nonce = encrypted_value[3:15]
                            ciphertext = encrypted_value[15:]
                            for aes_key in aes_keys:
                                try:
                                    plaintext = _decrypt_aes_gcm(ciphertext, nonce, aes_key)
                                    cookies[name] = _decode_cookie_value(plaintext)
                                    break
                                except Exception:
                                    continue

                conn.close()

                if len(cookies) >= 2:
                    logger.info(f'从 {browser_info["name"]} 获取到 {len(cookies)} 个 Cookie')
                    return cookies
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    return None


def get_available_browsers() -> List[dict]:
    """获取已安装的浏览器列表"""
    available = []
    for browser_name, info in BROWSER_PATHS.items():
        ud = info['user_data']
        ls = os.path.join(ud, 'Local State')
        if os.path.exists(ls):
            has_cookies = len(_find_cookie_dbs(ud)) > 0
            available.append({
                'name': browser_name,
                'display_name': info['name'],
                'has_cookies': has_cookies,
            })
    return available


def get_best_cookies() -> Optional[Dict[str, str]]:
    """获取最佳可用的 Bilibili Cookie"""
    for browser_name in BROWSER_PATHS:
        cookies = fetch_cookies_from_browser(browser_name)
        if cookies and 'SESSDATA' in cookies and 'bili_jct' in cookies:
            return cookies
    return None

_global_cookie_manager: Optional[CookieManager] = None

def get_cookie_manager() -> CookieManager:
    """获取全局 CookieManager 单例"""
    global _global_cookie_manager
    if _global_cookie_manager is None:
        _global_cookie_manager = CookieManager()
    return _global_cookie_manager

def reset_cookie_manager():
    """重置 CookieManager（用于重新加载配置）"""
    global _global_cookie_manager
    _global_cookie_manager = None
