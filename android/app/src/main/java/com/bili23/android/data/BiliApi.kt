package com.bili23.android.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** B站 API 客户端：搜索 / 视频信息 / DASH 播放地址 */
class BiliApi(private val okHttp: OkHttpClient) {

    companion object {
        private const val API_BASE = "https://api.bilibili.com"
        const val USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        private const val REFERER = "https://www.bilibili.com/"
        private const val KEY_TTL_MS = 600_000L // 10 分钟

        fun buildClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .build()
    }

    private var imgKey = ""
    private var subKey = ""
    private var keyFetchTime = 0L

    private fun newRequest(url: String, referer: String = REFERER): Request {
        val b = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .header("Referer", referer)
            .header("Origin", "https://www.bilibili.com")
            .header("Accept", "*/*")
        val cookie = Settings.cookie
        if (cookie.isNotBlank()) b.header("Cookie", cookie)
        return b.build()
    }

    /** 查询是否已登录（附带 Cookie 调用 nav 接口） */
    suspend fun isLogin(): Boolean = withContext(Dispatchers.IO) {
        if (Settings.cookie.isBlank()) return@withContext false
        try {
            val resp = fetchJson("$API_BASE/x/web-interface/nav")
            resp.optJSONObject("data")?.optBoolean("isLogin") == true
        } catch (_: Exception) {
            false
        }
    }

    /** 获取当前登录用户信息（昵称/头像） */
    suspend fun getLoginUser(): UserInfo? = withContext(Dispatchers.IO) {
        if (Settings.cookie.isBlank()) return@withContext null
        try {
            val resp = fetchJson("$API_BASE/x/web-interface/nav")
            val d = resp.optJSONObject("data") ?: return@withContext null
            if (d.optBoolean("isLogin") == false) return@withContext null
            UserInfo(
                mid = d.optLong("mid"),
                name = d.optString("uname"),
                face = d.optString("face")
            )
        } catch (_: Exception) {
            null
        }
    }

    private suspend fun fetchJson(url: String): JSONObject = withContext(Dispatchers.IO) {
        okHttp.newCall(newRequest(url)).execute().use { resp ->
            if (!resp.isSuccessful) throw IOException("HTTP ${resp.code}: $url")
            JSONObject(resp.body?.string() ?: "{}")
        }
    }

    /** 获取并缓存 WBI img_key / sub_key */
    private suspend fun ensureKeys() {
        val now = System.currentTimeMillis()
        if (imgKey.isNotEmpty() && now - keyFetchTime < KEY_TTL_MS) return
        try {
            val resp = fetchJson("$API_BASE/x/web-interface/nav")
            val data = resp.optJSONObject("data") ?: return
            val wbi = data.optJSONObject("wbi_img") ?: return
            val imgUrl = wbi.optString("img_url")
            val subUrl = wbi.optString("sub_url")
            if (imgUrl.isNotEmpty() && subUrl.isNotEmpty()) {
                imgKey = WbiSigner.splitKey(imgUrl)
                subKey = WbiSigner.splitKey(subUrl)
                keyFetchTime = now
            }
        } catch (_: Exception) {
            // 获取失败时降级为无签名请求
        }
    }

    private suspend fun signedGet(path: String, params: Map<String, String>): JSONObject {
        ensureKeys()
        val signed = if (imgKey.isNotEmpty() && subKey.isNotEmpty()) {
            WbiSigner.sign(params, imgKey, subKey)
        } else {
            params
        }
        val qs = signed.entries.joinToString("&") { "${it.key}=${WbiSigner.quote(it.value)}" }
        return fetchJson("$API_BASE$path?$qs")
    }

    /** 搜索视频 */
    suspend fun search(keyword: String, page: Int = 1, order: String = "totalrank"): SearchResult =
        withContext(Dispatchers.IO) {
            try {
                val resp = signedGet(
                    "/x/web-interface/wbi/search/type",
                    mapOf(
                        "search_type" to "video",
                        "keyword" to keyword,
                        "page" to page.toString(),
                        "order" to order,
                        "platform" to "pc",
                        "web_location" to "1430654"
                    )
                )
                if (resp.optInt("code") != 0) return@withContext SearchResult()
                val data = resp.optJSONObject("data") ?: return@withContext SearchResult()
                val resultArr = data.optJSONArray("result") ?: return@withContext SearchResult()

                val videos = mutableListOf<VideoInfo>()
                for (i in 0 until resultArr.length()) {
                    val item = resultArr.optJSONObject(i) ?: continue
                    val bvid = item.optString("bvid")
                    if (bvid.isEmpty()) continue
                    videos.add(
                        VideoInfo(
                            bvid = bvid,
                            avid = item.optLong("id"),
                            title = cleanTitle(item.optString("title")),
                            ownerName = item.optString("author"),
                            coverUrl = normalizeUrl(item.optString("pic")),
                            duration = parseDuration(item.optString("duration")),
                            views = item.optString("play").replace(",", "").toLongOrNull() ?: 0,
                            danmaku = item.optLong("video_review"),
                            tname = item.optString("typename"),
                            pubdate = item.optLong("pubdate"),
                            description = item.optString("description")
                        )
                    )
                }
                SearchResult(
                    videos = videos,
                    total = data.optLong("numResults"),
                    page = page,
                    // has_more 可能缺失/不稳定，用 numPages 兜底判断是否还有下一页
                    hasMore = data.optInt("has_more", 0) != 0 ||
                            page < data.optInt("numPages", 1)
                )
            } catch (_: Exception) {
                SearchResult()
            }
        }

    /** 获取视频详情（含分P） */
    suspend fun getVideoInfo(bvid: String): VideoInfo? = withContext(Dispatchers.IO) {
        try {
            val resp = fetchJson("$API_BASE/x/web-interface/view?bvid=${WbiSigner.quote(bvid)}")
            if (resp.optInt("code") != 0) return@withContext null
            val d = resp.optJSONObject("data") ?: return@withContext null
            val owner = d.optJSONObject("owner")
            val stat = d.optJSONObject("stat")

            val episodes = mutableListOf<EpisodeInfo>()
            val pages = d.optJSONArray("pages")
            if (pages != null) {
                for (i in 0 until pages.length()) {
                    val p = pages.optJSONObject(i) ?: continue
                    episodes.add(
                        EpisodeInfo(
                            page = p.optInt("page", i + 1),
                            cid = p.optLong("cid"),
                            part = p.optString("part"),
                            duration = p.optInt("duration")
                        )
                    )
                }
            }
            VideoInfo(
                bvid = bvid,
                avid = d.optLong("aid"),
                title = d.optString("title"),
                description = d.optString("desc"),
                ownerName = owner?.optString("name") ?: "",
                ownerFace = owner?.optString("face")?.let { normalizeUrl(it) } ?: "",
                duration = d.optInt("duration"),
                coverUrl = normalizeUrl(d.optString("pic")),
                views = stat?.optLong("view") ?: 0,
                danmaku = stat?.optLong("danmaku") ?: 0,
                favorites = stat?.optLong("favorite") ?: 0,
                likes = stat?.optLong("like") ?: 0,
                tname = d.optString("tname"),
                pubdate = d.optLong("pubdate"),
                episodes = episodes
            )
        } catch (_: Exception) {
            null
        }
    }

    /** 获取 DASH 播放地址（视频+音频流） */
    suspend fun getPlayUrl(bvid: String, cid: Long, quality: Int = 100): PlayUrl =
        withContext(Dispatchers.IO) {
            try {
                val resp = fetchJson(
                    "$API_BASE/x/player/wbi/playurl?bvid=${WbiSigner.quote(bvid)}&cid=$cid&qn=$quality&fnval=16&fourk=1"
                )
                if (resp.optInt("code") != 0) return@withContext PlayUrl()
                val d = resp.optJSONObject("data") ?: return@withContext PlayUrl()

                val accept = mutableListOf<Int>()
                val acceptArr = d.optJSONArray("accept_quality")
                if (acceptArr != null) {
                    for (i in 0 until acceptArr.length()) accept.add(acceptArr.optInt(i))
                }

                var videoUrl = ""
                var audioUrl = ""
                val dash = d.optJSONObject("dash")
                if (dash != null) {
                    val vArr = dash.optJSONArray("video")
                    if (vArr != null && vArr.length() > 0) {
                        var best: JSONObject? = null
                        for (i in 0 until vArr.length()) {
                            val v = vArr.optJSONObject(i) ?: continue
                            if (best == null || v.optInt("id") > best!!.optInt("id")) best = v
                        }
                        videoUrl = best?.optString("baseUrl") ?: ""
                    }
                    val aArr = dash.optJSONArray("audio")
                    if (aArr != null && aArr.length() > 0) {
                        var best: JSONObject? = null
                        for (i in 0 until aArr.length()) {
                            val a = aArr.optJSONObject(i) ?: continue
                            if (best == null || a.optInt("id") > best!!.optInt("id")) best = a
                        }
                        audioUrl = best?.optString("baseUrl") ?: ""
                    }
                }
                PlayUrl(d.optInt("quality"), videoUrl, audioUrl, accept)
            } catch (_: Exception) {
                PlayUrl()
            }
        }

    private fun cleanTitle(t: String): String = t.replace(Regex("<[^>]+>"), "")

    /** 将协议相对 URL（//xxx）补全为 https */
    private fun normalizeUrl(u: String): String =
        if (u.startsWith("//")) "https:$u" else u

    /** "177:10" / "1:30:00" → 秒 */
    private fun parseDuration(s: String): Int {
        return try {
            val parts = s.trim().split(":")
            when (parts.size) {
                3 -> parts[0].toInt() * 3600 + parts[1].toInt() * 60 + parts[2].toInt()
                2 -> parts[0].toInt() * 60 + parts[1].toInt()
                1 -> parts[0].toInt()
                else -> 0
            }
        } catch (_: Exception) {
            0
        }
    }

    // ------------------------------------------------------------------
    // 二维码登录
    // ------------------------------------------------------------------
    private val passportBase = "https://passport.bilibili.com"

    /** 生成二维码登录信息 */
    suspend fun qrGenerate(): QrLogin? = withContext(Dispatchers.IO) {
        try {
            val resp = fetchJson("$passportBase/x/passport-login/web/qrcode/generate")
            if (resp.optInt("code") != 0) return@withContext null
            val d = resp.optJSONObject("data") ?: return@withContext null
            QrLogin(
                url = d.optString("url"),
                qrcodeKey = d.optString("qrcode_key")
            )
        } catch (_: Exception) {
            null
        }
    }

    /**
     * 轮询二维码扫描状态。
     * @return 0=成功(返回 cookie 串)，其他=待处理
     */
    suspend fun qrPoll(qrcodeKey: String): QrPollResult = withContext(Dispatchers.IO) {
        try {
            // 使用原始请求以获取 Set-Cookie 响应头
            val url = "$passportBase/x/passport-login/web/qrcode/poll?qrcode_key=${WbiSigner.quote(qrcodeKey)}"
            val resp = okHttp.newCall(newRequest(url)).execute()
            val bodyStr = resp.body?.string() ?: "{}"
            val respJson = JSONObject(bodyStr)
            val data = respJson.optJSONObject("data") ?: return@withContext QrPollResult(-1, "", "数据为空")
            val code = data.optInt("code", -1)
            if (code == 0) {
                val url2 = data.optString("url")
                // 1. 从回调 URL 解析 cookie（URL 解码）
                var cookieStr = extractCookiesFromUrl(url2)
                // 2. 合并响应头中的 Set-Cookie
                val headerCookies = resp.headers("Set-Cookie")
                val setCookieParts = mutableListOf<String>()
                for (h in headerCookies) {
                    val kv = h.substringBefore(';')
                    if (kv.contains('=') && kv.substringBefore('=') in setOf("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5")) {
                        setCookieParts.add(kv)
                    }
                }
                if (setCookieParts.isNotEmpty()) {
                    val merged = (cookieStr.split("; ").filter { it.isNotEmpty() } + setCookieParts)
                        .distinctBy { it.substringBefore('=') }
                        .joinToString("; ")
                    cookieStr = merged
                }
                if (cookieStr.isNotEmpty()) QrPollResult(0, cookieStr, "登录成功")
                else QrPollResult(-1, "", "未能获取 Cookie")
            } else {
                val msg = when (code) {
                    86038 -> "二维码已失效"
                    86090 -> "已扫描，请在手机上确认"
                    86039 -> "等待扫描..."
                    else -> "等待扫描..."
                }
                QrPollResult(code, "", msg)
            }
        } catch (e: Exception) {
            QrPollResult(-1, "", "轮询异常: ${e.message}")
        }
    }

    private fun extractCookiesFromUrl(url: String): String {
        if (url.isEmpty()) return ""
        val parts = mutableListOf<String>()
        val query = url.substringAfter('?', "")
        for (kv in query.split("&")) {
            val idx = kv.indexOf('=')
            if (idx <= 0) continue
            val key = kv.substring(0, idx)
            val value = kv.substring(idx + 1)
            if (key in setOf("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5")) {
                parts.add("$key=${decodeUrl(value)}")
            }
        }
        return parts.joinToString("; ")
    }

    /** URL 解码（B站 cookie 值可能被编码） */
    private fun decodeUrl(s: String): String {
        return try {
            java.net.URLDecoder.decode(s, "UTF-8")
        } catch (_: Exception) {
            s
        }
    }

    // ------------------------------------------------------------------
    // 歌词搜索（网易云）
    // ------------------------------------------------------------------
    /** 网易云搜索歌曲，返回歌曲名+id 列表 */
    suspend fun searchNetease(keyword: String): List<Pair<String, Long>> = withContext(Dispatchers.IO) {
        val list = mutableListOf<Pair<String, Long>>()
        try {
            val resp = fetchJsonRaw(
                "https://music.163.com/api/search/get/web",
                params = mapOf("s" to keyword, "type" to "1", "limit" to "10", "offset" to "0")
            )
            val songs = resp.optJSONObject("result")?.optJSONArray("songs") ?: return@withContext list
            for (i in 0 until songs.length()) {
                val s = songs.optJSONObject(i) ?: continue
                val id = s.optLong("id")
                val name = s.optString("name")
                val artists = s.optJSONArray("artists")
                val artist = if (artists != null && artists.length() > 0) {
                    artists.optJSONObject(0)?.optString("name") ?: ""
                } else ""
                val full = if (artist.isNotEmpty()) "$name - $artist" else name
                list.add(Pair(full, id))
            }
        } catch (_: Exception) {
        }
        list
    }

    /** 按 songId 获取网易云歌词（LRC 文本） */
    suspend fun getNeteaseLyric(songId: Long): String = withContext(Dispatchers.IO) {
        try {
            val resp = fetchJsonRaw(
                "https://music.163.com/api/song/lyric",
                params = mapOf("id" to songId.toString(), "lv" to "1", "kv" to "1", "tv" to "-1")
            )
            resp.optJSONObject("lrc")?.optString("lyric") ?: ""
        } catch (_: Exception) {
            ""
        }
    }

    /** 按 songId 获取网易云歌词 + 翻译（返回原词、翻译两段 LRC） */
    suspend fun getNeteaseLyricWithTranslation(songId: Long): Pair<String, String> =
        withContext(Dispatchers.IO) {
            try {
                val resp = fetchJsonRaw(
                    "https://music.163.com/api/song/lyric",
                    params = mapOf("id" to songId.toString(), "lv" to "1", "kv" to "1", "tv" to "1")
                )
                val lrc = resp.optJSONObject("lrc")?.optString("lyric") ?: ""
                val tl = resp.optJSONObject("tlyric")?.optString("lyric") ?: ""
                Pair(lrc, tl)
            } catch (_: Exception) {
                Pair("", "")
            }
        }

    /** 通用 GET 请求（带参数、不强制签名），返回 JSONObject */
    private suspend fun fetchJsonRaw(base: String, params: Map<String, String>): JSONObject =
        withContext(Dispatchers.IO) {
            val qs = params.entries.joinToString("&") { "${it.key}=${WbiSigner.quote(it.value)}" }
            val url = if (params.isEmpty()) base else "$base?$qs"
            val req = Request.Builder()
                .url(url)
                .header("User-Agent", USER_AGENT)
                .header("Referer", "https://music.163.com")
                .build()
            okHttp.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) JSONObject()
                else JSONObject(resp.body?.string() ?: "{}")
            }
        }

    // ------------------------------------------------------------------
    // 我的收藏
    // ------------------------------------------------------------------
    /** 获取当前登录用户的收藏夹列表 */
    suspend fun getFavoriteFolders(mid: Long): List<FavoriteFolder> = withContext(Dispatchers.IO) {
        if (Settings.cookie.isBlank()) return@withContext emptyList()
        try {
            val resp = fetchJson("$API_BASE/x/v3/fav/folder/created/list-all?up_mid=$mid")
            if (resp.optInt("code") != 0) return@withContext emptyList()
            val list = resp.optJSONObject("data")?.optJSONArray("list") ?: return@withContext emptyList()
            val folders = mutableListOf<FavoriteFolder>()
            for (i in 0 until list.length()) {
                val f = list.optJSONObject(i) ?: continue
                folders.add(
                    FavoriteFolder(
                        id = f.optLong("id"),
                        title = f.optString("title"),
                        mediaCount = f.optInt("media_count"),
                        coverUrl = normalizeUrl(f.optString("cover"))
                    )
                )
            }
            folders
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** 获取收藏夹内的视频列表（分页） */
    suspend fun getFavoriteVideos(folderId: Long, page: Int = 1): FavoriteVideoPage =
        withContext(Dispatchers.IO) {
            if (Settings.cookie.isBlank()) return@withContext FavoriteVideoPage()
            try {
                val resp = fetchJson(
                    "$API_BASE/x/v3/fav/resource/list?media_id=$folderId&pn=$page&ps=20&platform=web&order=mtime"
                )
                if (resp.optInt("code") != 0) return@withContext FavoriteVideoPage()
                val data = resp.optJSONObject("data") ?: return@withContext FavoriteVideoPage()
                val list = data.optJSONArray("medias") ?: return@withContext FavoriteVideoPage()
                val videos = mutableListOf<VideoInfo>()
                for (i in 0 until list.length()) {
                    val m = list.optJSONObject(i) ?: continue
                    val bvid = m.optString("bvid")
                    if (bvid.isEmpty()) continue
                    videos.add(
                        VideoInfo(
                            bvid = bvid,
                            avid = m.optLong("id"),
                            title = m.optString("title"),
                            coverUrl = normalizeUrl(m.optString("cover")),
                            ownerName = m.optJSONObject("upper")?.optString("name") ?: "",
                            duration = m.optInt("duration"),
                            pubdate = m.optLong("pubtime")
                        )
                    )
                }
                FavoriteVideoPage(
                    videos = videos,
                    page = page,
                    hasMore = data.optInt("has_more") == 1
                )
            } catch (_: Exception) {
                FavoriteVideoPage()
            }
        }
}
