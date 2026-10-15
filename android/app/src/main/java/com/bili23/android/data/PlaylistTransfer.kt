package com.bili23.android.data

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 分类（播放列表）导入导出：多台手机共享同一套收藏夹。
 *
 * 因为绝对路径在不同手机上不同，导出时只记录**文件名**（音频附带歌名/歌手用于兜底匹配），
 * 导入时在本机文件中按文件名查找、找不到再按歌名+歌手匹配，
 * 匹配到才加入分类，不会写入无效路径。
 */
object PlaylistTransfer {

    private const val APP_TAG = "Bili23"
    private const val FORMAT_VERSION = 1

    /** 导入结果 */
    data class Result(
        val createdPlaylists: Int,
        val addedTracks: Int,
        val missingTracks: Int,
        val syncedTags: Int,
        val message: String
    )

    /** 导出全部分类（音频 + 视频）到文件，返回文件对象 */
    fun export(context: Context, audioItems: List<AudioItem>): File {
        // 路径 → 歌名/歌手（音频元信息，用于对方手机兜底匹配与标签同步）
        val meta = HashMap<String, Pair<String, String>>()
        audioItems.forEach { meta[it.path] = it.title to it.artist }

        val root = JSONObject()
        root.put("app", APP_TAG)
        root.put("type", "playlists")
        root.put("version", FORMAT_VERSION)
        root.put("exportedAt", System.currentTimeMillis())

        val lists = JSONObject()
        for (type in listOf(Settings.PLAYLIST_AUDIO, Settings.PLAYLIST_VIDEO)) {
            val out = JSONObject()
            Settings.getPlaylists(type).forEach { (name, paths) ->
                val arr = JSONArray()
                paths.forEach { p ->
                    val entry = JSONObject()
                    entry.put("file", File(p).name)
                    // 优先取本机已保存的标签（用户编辑过的），其次取列表扫描结果
                    val saved = Settings.getAudioTag(p)
                    val scanned = meta[p]
                    val t = saved.first.ifBlank { scanned?.first.orEmpty() }
                    val a = saved.second.ifBlank { scanned?.second.orEmpty() }
                    if (t.isNotBlank()) entry.put("title", t)
                    if (a.isNotBlank()) entry.put("artist", a)
                    arr.put(entry)
                }
                out.put(name, arr)
            }
            lists.put(type, out)
        }
        root.put("playlists", lists)

        val dir = File(context.getExternalFilesDir(null), "export").apply { mkdirs() }
        val stamp = SimpleDateFormat("yyyyMMdd_HHmm", Locale.CHINA).format(Date())
        val file = File(dir, "Bili23分类_$stamp.json")
        file.writeText(root.toString(2))
        return file
    }

    /** 从导出的 JSON 文件导入（合并：同名分类追加缺失歌曲，不删除本机已有内容） */
    fun import(context: Context, uri: Uri, audioItems: List<AudioItem>): Result {
        val text = try {
            context.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
        } catch (_: Exception) {
            null
        } ?: return Result(0, 0, 0, 0, "无法读取该文件")

        val root = try {
            JSONObject(text)
        } catch (_: Exception) {
            return Result(0, 0, 0, 0, "文件格式不正确（不是 Bili23 导出的分类文件）")
        }
        if (root.optString("app") != APP_TAG) {
            return Result(0, 0, 0, 0, "文件格式不正确（不是 Bili23 导出的分类文件）")
        }
        val lists = root.optJSONObject("playlists")
            ?: return Result(0, 0, 0, 0, "文件中没有分类数据")

        // 本机匹配索引：文件名（小写）→ 本地路径；歌名+歌手 → 本地路径；路径 → 本地曲目
        val byName = HashMap<String, String>()
        val byTitle = HashMap<String, String>()
        val byItem = HashMap<String, AudioItem>()
        audioItems.forEach { item ->
            byName.putIfAbsent(File(item.path).name.lowercase(Locale.ROOT), item.path)
            byItem[item.path] = item
            if (item.title.isNotBlank()) {
                byTitle.putIfAbsent(titleKey(item.title, item.artist), item.path)
            }
        }
        // 扫描本机全部下载文件（含视频与改名后的下载目录），按文件名兜底匹配
        runCatching {
            File(context.getExternalFilesDir(null) ?: return@runCatching, "").walkTopDown().forEach { f ->
                if (f.isFile) byName.putIfAbsent(f.name.lowercase(Locale.ROOT), f.absolutePath)
            }
        }

        var created = 0
        var added = 0
        var missing = 0
        var syncedTags = 0
        for (type in listOf(Settings.PLAYLIST_AUDIO, Settings.PLAYLIST_VIDEO)) {
            val inMap = lists.optJSONObject(type) ?: continue
            val local = Settings.getPlaylists(type)
            val names = inMap.keys()
            while (names.hasNext()) {
                val name = names.next()
                val arr = inMap.optJSONArray(name) ?: continue
                if (!local.containsKey(name)) {
                    local[name] = mutableListOf()
                    created++
                }
                val list = local[name] ?: mutableListOf<String>().also { local[name] = it }
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    val fileName = obj.optString("file").lowercase(Locale.ROOT)
                    var resolved = byName[fileName]
                    if (resolved == null) {
                        val title = obj.optString("title")
                        if (title.isNotBlank()) {
                            resolved = byTitle[titleKey(title, obj.optString("artist"))]
                        }
                    }
                    if (resolved.isNullOrBlank()) {
                        missing++
                        continue
                    }
                    if (!list.contains(resolved)) {
                        list.add(resolved)
                        added++
                    }
                    // 导入到"纯音乐"分类：同步自动标记，避免对方手机再次搜索歌词
                    if (Settings.isInstrumentalPlaylist(type, name)) {
                        Settings.markInstrumental(resolved)
                    }
                    // 同步歌名/歌手：仅当与对方不一致时写入（非空值才覆盖），使两台手机显示一致
                    if (type == Settings.PLAYLIST_AUDIO) {
                        val localItem = byItem[resolved]
                        val exTitle = obj.optString("title").trim()
                        val exArtist = obj.optString("artist").trim()
                        if (localItem != null && (exTitle.isNotBlank() || exArtist.isNotBlank())) {
                            val t = exTitle.ifBlank { localItem.title }
                            val a = exArtist.ifBlank { localItem.artist }
                            if (t != localItem.title || a != localItem.artist) {
                                Settings.setAudioTag(resolved, t, a)
                                syncedTags++
                            }
                        }
                    }
                }
            }
            Settings.applyPlaylists(type, local)
        }

        val msg = buildString {
            append("导入完成：新增 ").append(created).append(" 个分类，加入 ").append(added).append(" 首")
            if (syncedTags > 0) append("，同步歌名/歌手 ").append(syncedTags).append(" 首")
            if (missing > 0) append("；").append(missing).append(" 首在本机未找到（需先下载同名文件）")
        }
        return Result(created, added, missing, syncedTags, msg)
    }

    private fun titleKey(title: String, artist: String): String =
        "${title.trim().lowercase(Locale.ROOT)}|${artist.trim().lowercase(Locale.ROOT)}"
}