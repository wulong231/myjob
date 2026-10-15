package com.bili23.android.data

import android.content.Context
import androidx.compose.runtime.mutableIntStateOf

/** 应用设置（SharedPreferences） */
object Settings {
    private const val PREFS = "bili23_prefs"
    private lateinit var prefs: android.content.SharedPreferences

    /** 主题状态（Compose 可观察，切换后界面立即刷新） */
    val themeModeState = mutableIntStateOf(0)

    fun init(context: Context) {
        if (!::prefs.isInitialized) {
            prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        }
        themeModeState.intValue = prefs.getInt("theme_mode", 0)
        migrateFavorites()
    }

    /** 下载目录名（应用私有目录下的子目录） */
    var downloadDirName: String
        get() = prefs.getString("download_dir", "Download") ?: "Download"
        set(value) {
            prefs.edit().putString("download_dir", value).apply()
        }

    /** 默认画质码（100=1080P） */
    var defaultQuality: Int
        get() = prefs.getInt("default_quality", 100)
        set(value) {
            prefs.edit().putInt("default_quality", value).apply()
        }

    /** 主题模式：0=跟随系统，1=浅色，2=深色 */
    var themeMode: Int
        get() = themeModeState.intValue
        set(value) {
            themeModeState.intValue = value
            prefs.edit().putInt("theme_mode", value).apply()
        }

    /** 视频播放模式：0=顺序 1=列表循环 2=单曲循环 3=随机 */
    var videoPlayMode: Int
        get() = prefs.getInt("video_play_mode", 0)
        set(value) {
            prefs.edit().putInt("video_play_mode", value).apply()
        }

    /** B站 Cookie */
    var cookie: String
        get() = prefs.getString("cookie", "") ?: ""
        set(value) {
            prefs.edit().putString("cookie", value).apply()
        }

    /** 是否已登录 */
    val isLoggedIn: Boolean
        get() = cookie.contains("SESSDATA=")

    /** 登录用户名（昵称，可选） */
    var nickname: String
        get() = prefs.getString("nickname", "") ?: ""
        set(value) {
            prefs.edit().putString("nickname", value).apply()
        }

    // ---- 音频标签（path → "title|artist"）----
    fun getAudioTag(path: String): Pair<String, String> {
        val raw = prefs.getString("audio_tag_$path", "") ?: ""
        if (raw.isEmpty()) return Pair("", "")
        val parts = raw.split("|", limit = 2)
        return Pair(parts.getOrElse(0) { "" }, parts.getOrElse(1) { "" })
    }

    fun setAudioTag(path: String, title: String, artist: String) {
        prefs.edit().putString("audio_tag_$path", "$title|$artist").apply()
    }

    fun clearAudioTag(path: String) {
        prefs.edit().remove("audio_tag_$path").apply()
    }

    // ------------------------------------------------------------------
    // 播放列表：视频/音频分命名空间，各自独立创建
    // 默认收藏列表：视频→“我收藏的视频”，音频→“我收藏的音频”
    // ------------------------------------------------------------------
    const val PLAYLIST_VIDEO = "video"
    const val PLAYLIST_AUDIO = "audio"

    /** 纯音乐分类：音频加入该分类时自动标记为纯音乐（不搜索歌词） */
    const val INSTRUMENTAL_PLAYLIST = "纯音乐"
    private const val PLAYLISTS_KEY_VIDEO = "playlists_video_json"
    private const val PLAYLISTS_KEY_AUDIO = "playlists_audio_json"
    private const val PLAYLISTS_KEY_OLD = "playlists_json"

    private fun playlistKey(type: String): String =
        if (type == PLAYLIST_VIDEO) PLAYLISTS_KEY_VIDEO else PLAYLISTS_KEY_AUDIO

    /** 读取指定类型的全部播放列表（保持插入顺序） */
    fun getPlaylists(type: String): MutableMap<String, MutableList<String>> {
        val raw = prefs.getString(playlistKey(type), "") ?: ""
        val map = LinkedHashMap<String, MutableList<String>>()
        if (raw.isNotBlank()) {
            try {
                val obj = org.json.JSONObject(raw)
                val keys = obj.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    val arr = obj.optJSONArray(k) ?: continue
                    val list = mutableListOf<String>()
                    for (i in 0 until arr.length()) list.add(arr.optString(i))
                    map[k] = list
                }
            } catch (_: Exception) {
            }
        }
        return map
    }

    private fun savePlaylists(type: String, map: Map<String, List<String>>) {
        val obj = org.json.JSONObject()
        map.forEach { (k, v) -> obj.put(k, org.json.JSONArray(v)) }
        prefs.edit().putString(playlistKey(type), obj.toString()).apply()
    }

    /** 批量保存指定类型播放列表（供批量修改使用） */
    fun applyPlaylists(type: String, map: Map<String, List<String>>) {
        savePlaylists(type, map)
    }

    /** 新建命名列表，成功返回 true（重名/空名返回 false） */
    fun createPlaylist(type: String, name: String): Boolean {
        val n = name.trim()
        if (n.isEmpty()) return false
        val map = getPlaylists(type)
        if (map.containsKey(n)) return false
        map[n] = mutableListOf()
        savePlaylists(type, map)
        return true
    }

    /** 重命名列表，成功返回 true */
    fun renamePlaylist(type: String, old: String, newName: String): Boolean {
        val n = newName.trim()
        if (n.isEmpty() || n == old) return false
        val map = getPlaylists(type)
        if (!map.containsKey(old) || map.containsKey(n)) return false
        val items = map.remove(old) ?: mutableListOf()
        map[n] = items
        savePlaylists(type, map)
        return true
    }

    /** 删除列表（不删除文件） */
    fun deletePlaylist(type: String, name: String) {
        val map = getPlaylists(type)
        if (map.remove(name) != null) savePlaylists(type, map)
    }

    /** 将文件加入列表（自动去重；加入"纯音乐"分类时自动标记为纯音乐） */
    fun addToPlaylist(type: String, name: String, path: String) {
        val map = getPlaylists(type)
        val list = map[name] ?: mutableListOf()
        if (!list.contains(path)) list.add(path)
        map[name] = list
        savePlaylists(type, map)
        if (isInstrumentalPlaylist(type, name)) markInstrumental(path)
    }

    /** 批量将文件加入列表（自动去重；加入"纯音乐"分类时自动标记为纯音乐） */
    fun addAllToPlaylist(type: String, name: String, paths: List<String>) {
        if (paths.isEmpty()) return
        val map = getPlaylists(type)
        val list = map[name] ?: mutableListOf()
        paths.forEach { if (!list.contains(it)) list.add(it) }
        map[name] = list
        savePlaylists(type, map)
        if (isInstrumentalPlaylist(type, name)) paths.forEach { markInstrumental(it) }
    }

    /** 从列表移除文件 */
    fun removeFromPlaylist(type: String, name: String, path: String) {
        val map = getPlaylists(type)
        val list = map[name] ?: return
        if (list.remove(path)) savePlaylists(type, map)
    }

    /** 批量从列表移除文件 */
    fun removeAllFromPlaylist(type: String, name: String, paths: List<String>) {
        if (paths.isEmpty()) return
        val map = getPlaylists(type)
        val list = map[name] ?: return
        var changed = false
        paths.forEach { if (list.remove(it)) changed = true }
        if (changed) savePlaylists(type, map)
    }

    fun getPlaylistItems(type: String, name: String): List<String> =
        getPlaylists(type)[name] ?: emptyList()

    fun isInPlaylist(type: String, name: String, path: String): Boolean =
        (getPlaylists(type)[name] ?: emptyList()).contains(path)

    // ---- 收藏：视频/音频分别归入对应类型的默认列表 ----
    const val DEFAULT_AUDIO_FAVORITES = "我收藏的音频"
    const val DEFAULT_VIDEO_FAVORITES = "我收藏的视频"

    /** 是否为视频文件路径 */
    fun isVideoPath(path: String): Boolean =
        path.substringAfterLast('.').lowercase() in setOf("mp4", "m4v", "mkv", "webm")

    /** 是否为音频文件路径 */
    fun isAudioPath(path: String): Boolean =
        path.substringAfterLast('.').lowercase() in setOf("mp3", "m4a", "flac", "wav", "aac", "ogg", "opus")

    /** 路径所属的列表类型 */
    fun playlistTypeOf(path: String): String =
        if (isVideoPath(path)) PLAYLIST_VIDEO else PLAYLIST_AUDIO

    /** 路径对应的默认收藏列表名 */
    fun favoriteListName(path: String): String =
        if (isVideoPath(path)) DEFAULT_VIDEO_FAVORITES else DEFAULT_AUDIO_FAVORITES

    fun getFavoritePaths(): Set<String> =
        ((getPlaylists(PLAYLIST_AUDIO)[DEFAULT_AUDIO_FAVORITES] ?: emptyList()) +
                (getPlaylists(PLAYLIST_VIDEO)[DEFAULT_VIDEO_FAVORITES] ?: emptyList())).toSet()

    fun isFavorite(path: String): Boolean =
        isInPlaylist(playlistTypeOf(path), favoriteListName(path), path)

    fun setFavorite(path: String, fav: Boolean) {
        if (fav) addToPlaylist(playlistTypeOf(path), favoriteListName(path), path)
        else removeFromPlaylist(playlistTypeOf(path), favoriteListName(path), path)
    }

    /** 迁移旧版收藏与共享列表 → 按路径类型分命名空间 */
    private fun migrateFavorites() {
        // 旧版共享列表（含默认“我的收藏”）按路径类型分发
        val oldRaw = prefs.getString(PLAYLISTS_KEY_OLD, "")
        if (!oldRaw.isNullOrBlank()) {
            try {
                val videoMap = getPlaylists(PLAYLIST_VIDEO)
                val audioMap = getPlaylists(PLAYLIST_AUDIO)
                val oldObj = org.json.JSONObject(oldRaw)
                val keys = oldObj.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    val arr = oldObj.optJSONArray(k) ?: continue
                    for (i in 0 until arr.length()) {
                        val path = arr.optString(i)
                        val type = playlistTypeOf(path)
                        val map = if (type == PLAYLIST_VIDEO) videoMap else audioMap
                        val name = when {
                            k == DEFAULT_VIDEO_FAVORITES || k == DEFAULT_AUDIO_FAVORITES -> favoriteListName(path)
                            else -> k
                        }
                        val list = map[name] ?: mutableListOf()
                        if (!list.contains(path)) list.add(path)
                        map[name] = list
                    }
                }
                savePlaylists(PLAYLIST_VIDEO, videoMap)
                savePlaylists(PLAYLIST_AUDIO, audioMap)
                prefs.edit().remove(PLAYLISTS_KEY_OLD).apply()
            } catch (_: Exception) {
            }
        }
        // 旧版 favorites StringSet
        val oldSet = prefs.getStringSet("favorites", null)
        if (oldSet != null) {
            oldSet.forEach { path ->
                val type = playlistTypeOf(path)
                val map = getPlaylists(type)
                val name = favoriteListName(path)
                val list = map[name] ?: mutableListOf()
                if (!list.contains(path)) list.add(path)
                map[name] = list
                savePlaylists(type, map)
            }
            prefs.edit().remove("favorites").apply()
        }
    }

    /** 批量更新两种类型播放列表中某个文件的路径（文件重命名后调用） */
    fun updatePlaylistPath(oldPath: String, newPath: String) {
        for (type in listOf(PLAYLIST_VIDEO, PLAYLIST_AUDIO)) {
            val map = getPlaylists(type)
            var changed = false
            map.forEach { (name, list) ->
                val idx = list.indexOf(oldPath)
                if (idx >= 0) {
                    list[idx] = newPath
                    changed = true
                }
            }
            if (changed) savePlaylists(type, map)
        }
    }

    // ------------------------------------------------------------------
    // 自定义排序（视频/音频多选可调整位置，持久化保存）
    // ------------------------------------------------------------------
    private const val ORDER_VIDEO = "order_video_json"
    private const val ORDER_AUDIO = "order_audio_json"

    fun getCustomOrder(type: String): List<String> {
        val key = if (type == PLAYLIST_VIDEO) ORDER_VIDEO else ORDER_AUDIO
        val raw = prefs.getString(key, "") ?: return emptyList()
        return runCatching {
            val arr = org.json.JSONArray(raw)
            (0 until arr.length()).map { arr.optString(it) }
        }.getOrDefault(emptyList())
    }

    fun setCustomOrder(type: String, order: List<String>) {
        val key = if (type == PLAYLIST_VIDEO) ORDER_VIDEO else ORDER_AUDIO
        prefs.edit().putString(key, org.json.JSONArray(order).toString()).apply()
    }

    /** 按自定义顺序重排列表（未在顺序中的排在后面，保持原相对顺序） */
    fun <T> reorderByCustom(list: List<T>, order: List<String>, pathOf: (T) -> String): List<T> {
        if (order.isEmpty()) return list
        val idx = order.withIndex().associate { it.value to it.index }
        return list.sortedWith(compareBy { idx[pathOf(it)] ?: Int.MAX_VALUE })
    }

    /** 将选中的路径整体上移/下移一格，返回新顺序（保持选中项相对顺序） */
    fun moveSelected(order: List<String>, selected: Set<String>, up: Boolean): List<String> {
        if (selected.isEmpty() || order.isEmpty()) return order
        val list = order.toMutableList()
        if (up) {
            var i = 1
            while (i < list.size) {
                if (list[i] in selected && list[i - 1] !in selected) {
                    val t = list[i - 1]; list[i - 1] = list[i]; list[i] = t
                }
                i++
            }
        } else {
            var i = list.size - 2
            while (i >= 0) {
                if (list[i] in selected && list[i + 1] !in selected) {
                    val t = list[i + 1]; list[i + 1] = list[i]; list[i] = t
                }
                i--
            }
        }
        return list
    }

    // ---- 歌词：保存为 .lrc 文件（原歌词）与 .lrc.tl（翻译），兼容旧版 prefs ----
    private fun lyricFile(path: String): java.io.File =
        java.io.File(path.substringBeforeLast('.') + ".lrc")

    private fun translationFile(path: String): java.io.File =
        java.io.File(path.substringBeforeLast('.') + ".lrc.tl")

    fun getLyric(path: String): String {
        val f = lyricFile(path)
        if (f.exists()) return runCatching { f.readText() }.getOrDefault("")
        return prefs.getString("lyric_$path", "") ?: ""
    }

    fun setLyric(path: String, lrc: String) {
        runCatching { lyricFile(path).writeText(lrc) }
        prefs.edit().putString("lyric_$path", lrc).apply()
    }

    fun getLyricTranslation(path: String): String {
        val f = translationFile(path)
        if (f.exists()) return runCatching { f.readText() }.getOrDefault("")
        return prefs.getString("lyric_tl_$path", "") ?: ""
    }

    fun setLyricTranslation(path: String, tl: String) {
        runCatching { translationFile(path).writeText(tl) }
        prefs.edit().putString("lyric_tl_$path", tl).apply()
    }

    fun clearLyric(path: String) {
        runCatching { lyricFile(path).delete() }
        runCatching { translationFile(path).delete() }
        prefs.edit().remove("lyric_$path").apply()
        prefs.edit().remove("lyric_tl_$path").apply()
    }

    /** 歌词偏移量（毫秒）：搜索到的歌词时间可能不准，保留用户微调值 */
    fun getLyricOffset(path: String): Long = prefs.getLong("lyric_offset_$path", 0L)

    fun setLyricOffset(path: String, offset: Long) {
        prefs.edit().putLong("lyric_offset_$path", offset).apply()
    }

    /** 桌面歌词（悬浮窗）开关 */
    var desktopLyricsEnabled: Boolean
        get() = prefs.getBoolean("desktop_lyrics", false)
        set(value) {
            prefs.edit().putBoolean("desktop_lyrics", value).apply()
        }

    /** 桌面歌词悬浮窗位置（-1 = 未设置，使用默认位置） */
    var desktopLyricsX: Int
        get() = prefs.getInt("desktop_lyrics_x", -1)
        set(value) {
            prefs.edit().putInt("desktop_lyrics_x", value).apply()
        }

    var desktopLyricsY: Int
        get() = prefs.getInt("desktop_lyrics_y", -1)
        set(value) {
            prefs.edit().putInt("desktop_lyrics_y", value).apply()
        }

    /** 歌词模式背景：true=纯黑底，false=虚化封面（默认） */
    var lyricsModeBlackBg: Boolean
        get() = prefs.getBoolean("lyrics_mode_black_bg", false)
        set(value) {
            prefs.edit().putBoolean("lyrics_mode_black_bg", value).apply()
        }

    /**
     * 本曲音量调整（分贝，-12~+12，0=原始音量）：按文件路径记忆，
     * 播放该曲时由播放服务静态应用（负值衰减、正值增益提升），不做动态压缩。
     */
    fun getTrackGain(path: String): Float = prefs.getFloat("gain_$path", 0f)

    fun setTrackGain(path: String, db: Float) {
        prefs.edit().putFloat("gain_$path", db).apply()
    }

    /** 是否标记为纯音乐（标记后不自动搜索歌词，歌词固定显示"纯音乐"） */
    fun isInstrumental(path: String): Boolean = prefs.getBoolean("instrumental_$path", false)

    fun setInstrumental(path: String, value: Boolean) {
        prefs.edit().putBoolean("instrumental_$path", value).apply()
    }

    /** 是否为"纯音乐"分类（仅音频类型） */
    fun isInstrumentalPlaylist(type: String, name: String): Boolean =
        type == PLAYLIST_AUDIO && name.trim() == INSTRUMENTAL_PLAYLIST

    /** 标记为纯音乐：写入"纯音乐"歌词占位，从而不触发歌词搜索（仅对音频生效） */
    fun markInstrumental(path: String) {
        if (!isAudioPath(path)) return
        setInstrumental(path, true)
        setLyric(path, LRC_INSTRUMENTAL)
        setLyricTranslation(path, "")
    }
}
