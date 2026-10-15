package com.bili23.android.data

/** 歌词行 */
data class LyricLine(val timeMs: Long, val text: String)

/**
 * 纯音乐标记歌词：在标签编辑中勾选"纯音乐"后写入歌词缓存，
 * 从而不触发自动搜索，音频页 / 桌面歌词 / 歌词模式统一显示"纯音乐"。
 */
const val LRC_INSTRUMENTAL = "[00:00.00]纯音乐"

/** 解析 LRC 文本 → 歌词行列表（过滤空行与词曲编曲等元信息行，避免与翻译错位） */
fun parseLrc(lrc: String): List<LyricLine> {
    val lines = mutableListOf<LyricLine>()
    val regex = Regex("\\[(\\d{1,2}):(\\d{1,2})(?:\\.(\\d{1,3}))?]")
    for (raw in lrc.split("\n")) {
        val matches = regex.findAll(raw).toList()
        if (matches.isEmpty()) continue
        val text = raw.substringAfterLast(']').trim()
        if (text.isEmpty()) continue
        // 过滤词曲编曲、制作人等非歌词元信息行（日译中时这些行会与翻译错位）
        if (isCreditLine(text)) continue
        for (m in matches) {
            val min = m.groupValues[1].toIntOrNull() ?: 0
            val sec = m.groupValues[2].toIntOrNull() ?: 0
            val msPart = m.groupValues[3]
            val ms = when (msPart.length) {
                1 -> msPart.toIntOrNull()?.times(100) ?: 0
                2 -> msPart.toIntOrNull()?.times(10) ?: 0
                3 -> msPart.toIntOrNull() ?: 0
                else -> 0
            }
            lines.add(LyricLine(min * 60_000L + sec * 1000L + ms, text))
        }
    }
    return lines.sortedBy { it.timeMs }
}

/** 是否为词曲编曲等元信息行（不计入歌词显示） */
private fun isCreditLine(text: String): Boolean {
    val t = text.trim()
    if (t.isEmpty()) return true
    // 词曲编曲/制作/标注 等，以及 [ti:][ar:][by:][al:] 标签
    return Regex(
        "^(作词|作曲|编曲|制作人|制作|监制|混音|录音|母带|和声|吉他|贝斯|鼓手|键盘|钢琴|弦乐|出品|" +
            "producer|composer|lyricist|arranger|mix|record|master)\\s*[:：]",
        RegexOption.IGNORE_CASE
    ).containsMatchIn(t) ||
            Regex("^(by|ti|ar|al|offset)\\s*[:：]", RegexOption.IGNORE_CASE).containsMatchIn(t)
}

/** 当前播放行索引（考虑偏移） */
fun currentLyricIndex(lines: List<LyricLine>, posMs: Long, offsetMs: Long): Int {
    if (lines.isEmpty()) return -1
    val adjusted = posMs - offsetMs
    var idx = -1
    for (i in lines.indices) {
        if (adjusted >= lines[i].timeMs) idx = i
        else break
    }
    return idx
}

/**
 * 当前行演唱进度 0~1（用于卡拉OK填充）：
 * 由当前行起始时间到下一行起始时间的区间计算，最后一行按 4 秒估算
 */
fun currentLineProgress(lines: List<LyricLine>, index: Int, posMs: Long, offsetMs: Long): Float {
    if (index !in lines.indices) return 0f
    val adjusted = posMs - offsetMs
    val start = lines[index].timeMs
    val end = lines.getOrNull(index + 1)?.timeMs ?: (start + 4000L)
    val span = (end - start).coerceAtLeast(1L)
    return ((adjusted - start).toFloat() / span).coerceIn(0f, 1f)
}