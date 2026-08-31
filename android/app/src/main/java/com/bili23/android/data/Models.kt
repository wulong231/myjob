package com.bili23.android.data

import java.util.Locale

/** 数据模型：与桌面版 models.py 对应 */

data class VideoInfo(
    val bvid: String,
    val avid: Long,
    val title: String,
    val description: String = "",
    val ownerName: String = "",
    val ownerFace: String = "",
    val duration: Int = 0,
    val coverUrl: String = "",
    val views: Long = 0,
    val danmaku: Long = 0,
    val favorites: Long = 0,
    val likes: Long = 0,
    val tname: String = "",
    val pubdate: Long = 0,
    val episodes: List<EpisodeInfo> = emptyList()
) {
    val isMultiEpisode: Boolean get() = episodes.size > 1
}

data class EpisodeInfo(
    val page: Int = 1,
    val cid: Long = 0,
    val part: String = "",
    val duration: Int = 0
)

data class SearchResult(
    val videos: List<VideoInfo> = emptyList(),
    val total: Long = 0,
    val page: Int = 1,
    val hasMore: Boolean = false
)

/** 收藏夹内视频分页结果 */
data class FavoriteVideoPage(
    val videos: List<VideoInfo> = emptyList(),
    val page: Int = 1,
    val hasMore: Boolean = false
)

/** DASH 播放地址 */
data class PlayUrl(
    val quality: Int = 0,
    val videoUrl: String = "",
    val audioUrl: String = "",
    val acceptQuality: List<Int> = emptyList()
)

/** 画质码 → 显示名 */
val QUALITY_NAMES: Map<Int, String> = mapOf(
    16 to "360P", 32 to "480P", 64 to "720P", 80 to "720P",
    100 to "1080P", 116 to "1080P+", 120 to "4K", 125 to "杜比视界",
    126 to "4K", 127 to "1080P60"
)

fun qualityName(qn: Int): String = QUALITY_NAMES[qn] ?: "${qn}P"

/** 可选画质码（按显示名去重，保留更高码，避免 720P/4K 重复项） */
val QUALITY_OPTIONS: List<Int> = listOf(16, 32, 64, 80, 100, 116, 120, 125, 126, 127)
    .reversed().distinctBy { qualityName(it) }.reversed()

/** 下载任务 */
data class DownloadTask(
    val id: String,
    val title: String,
    val bvid: String,
    val cid: Long,
    val part: String,
    val quality: Int,
    val coverUrl: String = "",
    val progress: Float = 0f,
    val status: String = STATUS_PENDING, // pending/downloading/merging/completed/failed
    val filePath: String = "",
    val error: String = "",
    val speed: Long = 0L,
    val type: String = TYPE_VIDEO      // video/audio
) {
    companion object {
        const val STATUS_PENDING = "pending"
        const val STATUS_DOWNLOADING = "downloading"
        const val STATUS_MERGING = "merging"
        const val STATUS_COMPLETED = "completed"
        const val STATUS_FAILED = "failed"

        const val TYPE_VIDEO = "video"
        const val TYPE_AUDIO = "audio"
    }
}

/** 本地音频条目 */
data class AudioItem(
    val path: String,
    val title: String,
    val artist: String = "",
    val album: String = "",
    val coverPath: String = ""
) {
    /** 显示用的歌名：优先取 title（可能为空白时回退到文件名） */
    val displayTitle: String get() = title.ifBlank { fileName }

    /** 文件名（去扩展名） */
    val fileName: String get() = path.substringAfterLast('/').substringBeforeLast('.')
}

/** 二维码登录数据 */
data class QrLogin(
    val url: String = "",
    val qrcodeKey: String = ""
)

/** 二维码轮询结果 */
data class QrPollResult(
    val code: Int = -1,       // 0=成功
    val cookie: String = "",  // 登录成功后的 cookie 串
    val message: String = ""
)

/** 用户信息 */
data class UserInfo(
    val mid: Long = 0,
    val name: String = "",
    val face: String = ""
)

/** 首页统计 */
data class HomeStats(
    val videoCount: Int = 0,
    val audioCount: Int = 0,
    val totalBytes: Long = 0L
) {
    fun formatSize(): String {
        val b = totalBytes
        return when {
            b >= 1024L * 1024 * 1024 -> String.format(Locale.ROOT, "%.2f GB", b / 1024.0 / 1024 / 1024)
            b >= 1024L * 1024 -> String.format(Locale.ROOT, "%.2f MB", b / 1024.0 / 1024)
            b >= 1024 -> String.format(Locale.ROOT, "%.1f KB", b / 1024.0)
            else -> "$b B"
        }
    }
}

/** 收藏夹 */
data class FavoriteFolder(
    val id: Long = 0,
    val title: String = "",
    val mediaCount: Int = 0,
    val coverUrl: String = ""
)

/** 时长格式化 */
fun formatDuration(sec: Long): String {
    val s = sec % 60
    val m = (sec / 60) % 60
    val h = sec / 3600
    return if (h > 0) String.format(Locale.ROOT, "%d:%02d:%02d", h, m, s)
    else String.format(Locale.ROOT, "%d:%02d", m, s)
}

/** 数字格式化（播放量等） */
fun formatCount(n: Long): String = when {
    n >= 100000000 -> String.format(Locale.ROOT, "%.1f亿", n / 100000000.0)
    n >= 10000 -> String.format(Locale.ROOT, "%.1f万", n / 10000.0)
    else -> n.toString()
}
