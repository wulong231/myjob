package com.bili23.android.data

import java.security.MessageDigest

/**
 * B站 WBI 签名器。
 * 与 Python 版 bilibili_api.py 中 _enc_wbi 逻辑保持完全一致：
 * - MIXIN_KEY_ENC_TAB 混淆
 * - 参数按 key ASCII 排序后以 key=value&... 拼接
 * - 使用 Python quote(safe='~') 语义编码（空格 %20，不编码 ~）
 * - MD5(param_str + mixin_key)
 */
object WbiSigner {

    private val MIXIN_KEY_ENC_TAB = intArrayOf(
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
        27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
    )

    /** 对原始 key 进行混淆，取前 32 位 */
    fun getMixinKey(orig: String): String {
        val sb = StringBuilder()
        for (i in MIXIN_KEY_ENC_TAB) {
            if (i < orig.length) sb.append(orig[i])
        }
        return if (sb.length > 32) sb.substring(0, 32) else sb.toString()
    }

    /** 从 key URL 中提取文件名（去掉路径和扩展名） */
    fun splitKey(keyUrl: String): String {
        val last = keyUrl.substringAfterLast('/')
        return last.substringBefore('.')
    }

    private fun md5Hex(input: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(input.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    /** Python urllib.parse.quote(s, safe='~') 语义 */
    fun quote(input: String): String {
        val sb = StringBuilder()
        for (c in input) {
            // 仅 ASCII 字母数字与 -_.~ 为安全字符；其余（含中文）按 UTF-8 百分号编码
            val code = c.code
            val asciiSafe = code < 128 && (c.isLetterOrDigit() || c == '-' || c == '_' || c == '.' || c == '~')
            if (asciiSafe) {
                sb.append(c)
            } else if (c == ' ') {
                sb.append("%20")
            } else {
                for (b in c.toString().toByteArray(Charsets.UTF_8)) {
                    sb.append('%').append("%02X".format(b))
                }
            }
        }
        return sb.toString()
    }

    /**
     * 对参数进行 WBI 签名。
     * @return 追加了 wts 与 w_rid 的新参数表
     */
    fun sign(params: Map<String, String>, imgKey: String, subKey: String): Map<String, String> {
        val mixinKey = getMixinKey(imgKey + subKey)
        val currTime = System.currentTimeMillis() / 1000L
        val p = HashMap(params)
        p["wts"] = currTime.toString()

        val sortedKeys = p.keys.sorted()
        val parts = sortedKeys.map { k -> "$k=${quote(p[k] ?: "")}" }
        val paramStr = parts.joinToString("&")

        val wRid = md5Hex(paramStr + mixinKey)
        p["w_rid"] = wRid
        return p
    }
}
