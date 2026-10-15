"""歌词翻译工作线程（异步翻译）

提供 _TranslateWorker QThread 类，用于异步翻译歌词文本。
翻译策略：DeepSeek AI 优先 → 百度翻译降级 → MyMemory 兜底。
"""
import logging
from typing import List

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


# ============================================================
# 歌词翻译（联网）
# ============================================================
class _TranslateWorker(QThread):
    """异步翻译歌词线程（DeepSeek AI 优先 → 百度降级 → MyMemory 兜底）"""
    finished = Signal(str, list, str)  # (source_path, translated_lines, source_name)
    error = Signal(str, str)      # (source_path, error_msg)

    def __init__(self, lines: list, source: str = "ja", target: str = "zh", parent=None):
        super().__init__(parent)
        self._lines = lines
        self._source = source
        self._target = target

    def run(self):
        # 整段发送给 AI，获得更好的上下文理解和润色
        original_text = "\n".join(self._lines)
        try:
            from ..network import get_client
            client = get_client()
            translated = self._ai_batch_translate(original_text, client)
            if translated:
                results = translated.split("\n")
                while len(results) < len(self._lines):
                    results.append("")
                self.finished.emit("", results[:len(self._lines)], "DeepSeek AI")
                return
        except Exception:
            pass

        # AI 翻译失败，降级到百度翻译（批量）
        try:
            import urllib.parse
            import urllib.request
            import json as _json
            logger.info("百度翻译尝试中...")
            translated = self._baidu_batch_translate(original_text, urllib.parse, urllib.request, _json)
            if translated:
                results = translated.split("\n")
                while len(results) < len(self._lines):
                    results.append("")
                self.finished.emit("", results[:len(self._lines)], "百度翻译")
                return
        except Exception as e:
            logger.warning(f"百度翻译失败: {e}")

        # 最终降级：逐行翻译（MyMemory 兜底）
        import urllib.parse
        import urllib.request
        import json as _json
        translated = []
        fail_count = 0
        for line in self._lines:
            if not line.strip():
                translated.append("")
                continue
            try:
                result = self._mymemory_translate(line, urllib.parse, urllib.request, _json)
                translated.append(result if result and result.strip() else line)
            except Exception:
                translated.append(line)
                fail_count += 1

        if fail_count == len(self._lines):
            self.error.emit("", "翻译服务不可用，请检查网络连接")
        else:
            self.finished.emit("", translated, "MyMemory")

    def _ai_batch_translate(self, text: str, client) -> str:
        """DeepSeek AI 批量翻译：整段发送，带润色指令，输出自然中文"""
        import json as _json
        from ..config import get_config
        api_key = get_config().get(get_config().deepseek_api_key)
        if not api_key:
            return ""  # 未配置 API Key，跳过 DeepSeek

        url = "https://api.deepseek.com/v1/chat/completions"
        system_prompt = (
            f"你是一个专业的歌词翻译专家。请将以下{self._source}歌词逐行翻译成中文。"
            "要求：\n"
            "1. 保持原文的每行格式，翻译结果用换行符分隔\n"
            "2. 翻译要自然流畅，符合中文表达习惯\n"
            "3. 注意歌词的韵律和意境，适当润色\n"
            "4. 不要添加额外说明，只返回翻译结果\n"
            "5. 如果原文包含特殊符号或英文字母，保留原样"
        )
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        try:
            resp = client.post(url, json=payload, timeout=60,
                               headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices and len(choices) > 0:
                    result = choices[0].get("message", {}).get("content", "").strip()
                    if result:
                        return result
        except Exception:
            pass
        return ""

    def _baidu_batch_translate(self, text, urllib_parse, urllib_request, _json):
        """百度翻译 API（批量翻译整段文本，自动分片避免超长）"""
        import hashlib
        import random
        from ..config import get_config
        cfg = get_config()
        appid = cfg.get(cfg.baidu_translate_appid) or "20260731002656664"
        secret_key = cfg.get(cfg.baidu_translate_secret) or "TgtzQWT7ppHS4ZLtWj_T"

        # 百度翻译使用不同的语言代码：ja → jp, zh → zh
        BAIDU_LANG_MAP = {
            "ja": "jp", "zh": "zh", "en": "en",
            "ko": "kor", "fr": "fra", "es": "spa",
            "auto": "auto",
        }
        baidu_from = BAIDU_LANG_MAP.get(self._source, self._source)
        baidu_to = BAIDU_LANG_MAP.get(self._target, self._target)

        # 百度翻译单次请求限制约 6000 字节，按行分片处理
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_size = 0
        for line in lines:
            line_size = len(line.encode("utf-8")) + 1  # +1 for \n
            if current_size + line_size > 5000 and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        def _translate_chunk(chunk_text):
            salt = str(random.randint(32768, 65536))
            sign = hashlib.md5((appid + chunk_text + salt + secret_key).encode("utf-8")).hexdigest()
            url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
            params = {
                "q": chunk_text,
                "from": baidu_from,
                "to": baidu_to,
                "appid": appid,
                "salt": salt,
                "sign": sign,
            }
            full_url = f"{url}?{urllib_parse.urlencode(params)}"
            req = urllib_request.Request(full_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with urllib_request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                if "trans_result" in data:
                    # 用换行符连接各行的翻译结果，保持歌词行数一致
                    return "\n".join([item["dst"] for item in data["trans_result"]])
                elif "error_code" in data:
                    raise Exception(f"百度翻译API错误 ({data['error_code']}): {data.get('error_msg', '')}")
                return ""

        results = []
        for chunk in chunks:
            try:
                result = _translate_chunk(chunk)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"百度翻译分片失败: {e}")
                return ""  # 任一失败则整体降级
        return "\n".join(results) if results else ""

    def _mymemory_translate(self, text, urllib_parse, urllib_request, _json):
        """MyMemory 翻译 API（兜底方案，国内可访问）"""
        source_lang = self._source if self._source != "auto" else "ja"
        lang_pair = f"{source_lang}|zh-CN"
        url = f"https://api.mymemory.translated.net/get?q={urllib_parse.quote(text)}&langpair={lang_pair}"
        req = urllib_request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            result = data.get("responseData", {}).get("translatedText", "")
            if result:
                idx = result.find("MYMEMORY WARNING")
                if idx >= 0:
                    result = result[:idx].strip()
                return result
            return ""