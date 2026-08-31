package com.bili23.android

import com.bili23.android.data.WbiSigner
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * WBI 签名单元测试。
 * 验证混淆、URL 编码与 MD5 签名结果与 Python 版一致。
 */
class WbiSignerTest {

    private val imgKey = "7cd084941338484aae1ad9425b84077c"
    private val subKey = "4932caff0ff746eab6f01bf08b70ac45"

    @Test
    fun getMixinKey_matchesPython() {
        val mixin = WbiSigner.getMixinKey(imgKey + subKey)
        // 与 Python bilibili_api.py 中 _get_mixin_key 结果一致
        assertEquals(32, mixin.length)
        assertEquals("ea1db124af3c7062474693fa704f4ff8", mixin)
    }

    @Test
    fun quote_matchesUrlEncode() {
        assertEquals("a_b-c.d~", WbiSigner.quote("a_b-c.d~"))
        assertEquals("hello%20world", WbiSigner.quote("hello world"))
        assertEquals("%E4%B8%AD%E6%96%87", WbiSigner.quote("中文"))
        assertEquals("a%2Bb", WbiSigner.quote("a+b"))
    }

    @Test
    fun sign_returnsWtsAndWRid() {
        val signed = WbiSigner.sign(
            mapOf("search_type" to "video", "keyword" to "test"),
            imgKey,
            subKey
        )
        assert(signed.containsKey("wts"))
        assert(signed.containsKey("w_rid"))
        // w_rid 应为 32 位小写 MD5
        assertEquals(32, signed["w_rid"]!!.length)
    }

    @Test
    fun splitKey_extractsFilename() {
        assertEquals(
            "7cd084941338484aae1ad9425b84077c",
            WbiSigner.splitKey("https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png")
        )
    }
}
