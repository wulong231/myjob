package com.bili23.android.data

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 下载管理器：
 * 1. 视频：并行下载 DASH 视频流 + 音频流，MediaMuxer 合并为 MP4，存至 videos/ 目录
 * 2. 音频：仅下载 DASH 音频流，保存为 M4A，存至 audios/ 目录
 * 3. 提供首页统计：视频数 / 音频数 / 占用空间
 */
class DownloadManager(
    private val okHttp: OkHttpClient,
    private val downloadDir: File
) {
    /** 视频目录 */
    val videoDir: File = File(downloadDir, "videos").apply { mkdirs() }

    /** 音频目录 */
    val audioDir: File = File(downloadDir, "audios").apply { mkdirs() }

    private val _tasks = MutableStateFlow<List<DownloadTask>>(emptyList())
    val tasks: StateFlow<List<DownloadTask>> get() = _tasks

    private val _completed = MutableStateFlow<List<String>>(emptyList())
    val completed: StateFlow<List<String>> get() = _completed

    /** 正在写入的临时文件路径（扫描磁盘时跳过，避免把 .m4v/.m4a 临时文件误当成品产生重复记录） */
    private val _activeTempFiles = MutableStateFlow<Set<String>>(emptySet())
    val activeTempFiles: StateFlow<Set<String>> get() = _activeTempFiles

    private fun trackTemp(paths: Set<String>) {
        _activeTempFiles.value = _activeTempFiles.value + paths
    }

    private fun untrackTemp(paths: Set<String>) {
        _activeTempFiles.value = _activeTempFiles.value - paths
    }

    private val cancelled = AtomicBoolean(false)

    fun cancelAll() {
        cancelled.set(true)
    }

    fun resetCancel() {
        cancelled.set(false)
    }

    /** 下载视频（合并为 MP4） */
    suspend fun startDownload(
        bvid: String,
        title: String,
        part: String,
        cid: Long,
        quality: Int,
        coverUrl: String,
        videoUrl: String,
        audioUrl: String,
        onStatus: (DownloadTask) -> Unit = {}
    ): DownloadTask = withContext(Dispatchers.IO) {
        val name = buildFileName(title, part)

        val id = "v_${bvid}_$cid"
        var task = DownloadTask(
            id = id,
            title = title,
            bvid = bvid,
            cid = cid,
            part = part,
            quality = quality,
            coverUrl = coverUrl,
            status = DownloadTask.STATUS_DOWNLOADING,
            type = DownloadTask.TYPE_VIDEO
        )
        _tasks.value = _tasks.value.filter { it.id != id } + task
        onStatus(task)

        val vFile = File(videoDir, "$name.m4v")
        val aFile = File(videoDir, "$name.m4a")
        val outFile = File(videoDir, "$name.mp4")
        val tempSet = setOf(vFile.absolutePath, aFile.absolutePath)
        trackTemp(tempSet)

        try {
            val referer = "https://www.bilibili.com/"

            task = task.copy(status = DownloadTask.STATUS_DOWNLOADING)
            updateTask(task)
            downloadStream(videoUrl, vFile, referer) { v ->
                task = task.copy(progress = v * 0.9f, speed = 0)
                updateTask(task)
            }

            downloadStream(audioUrl, aFile, referer) { a ->
                task = task.copy(progress = 0.9f + a * 0.05f)
                updateTask(task)
            }

            if (cancelled.get()) throw IOException("已取消")

            task = task.copy(status = DownloadTask.STATUS_MERGING, progress = 0.95f)
            updateTask(task)
            mergeVideoAudio(vFile.absolutePath, aFile.absolutePath, outFile.absolutePath)

            vFile.delete()
            aFile.delete()
            // 清理扫描可能把 .m4v/.m4a 临时文件误当成品而加入的幻影任务
            _tasks.value = _tasks.value.filter {
                it.filePath != vFile.absolutePath && it.filePath != aFile.absolutePath
            }

            task = task.copy(
                status = DownloadTask.STATUS_COMPLETED,
                progress = 1f,
                filePath = outFile.absolutePath
            )
            updateTask(task)
            onStatus(task)
            _completed.value = _completed.value + outFile.absolutePath
            // 下载封面图（与媒体文件同名 .jpg，供播放器显示）
            downloadCoverIfNeeded(coverUrl, File(videoDir, "$name.jpg"))
            task
        } catch (e: Exception) {
            task = task.copy(status = DownloadTask.STATUS_FAILED, error = e.message ?: "下载失败")
            updateTask(task)
            onStatus(task)
            task
        } finally {
            untrackTemp(tempSet)
        }
    }

    /** 仅下载音频（DASH 音频流 AAC，保存为 M4A 到 audios/ 目录） */
    suspend fun downloadAudioOnly(
        bvid: String,
        title: String,
        part: String,
        cid: Long,
        coverUrl: String,
        audioUrl: String,
        onStatus: (DownloadTask) -> Unit = {}
    ): DownloadTask = withContext(Dispatchers.IO) {
        val name = buildFileName(title, part)

        val id = "a_${bvid}_$cid"
        var task = DownloadTask(
            id = id,
            title = title,
            bvid = bvid,
            cid = cid,
            part = part,
            quality = 0,
            coverUrl = coverUrl,
            status = DownloadTask.STATUS_DOWNLOADING,
            type = DownloadTask.TYPE_AUDIO
        )
        _tasks.value = _tasks.value.filter { it.id != id } + task
        onStatus(task)

        val outFile = File(audioDir, "$name.m4a")
        val tempSet = setOf(outFile.absolutePath)
        trackTemp(tempSet)

        try {
            val referer = "https://www.bilibili.com/"

            task = task.copy(status = DownloadTask.STATUS_DOWNLOADING)
            updateTask(task)
            downloadStream(audioUrl, outFile, referer) { a ->
                task = task.copy(progress = a, speed = 0)
                updateTask(task)
            }

            if (cancelled.get()) throw IOException("已取消")

            task = task.copy(
                status = DownloadTask.STATUS_COMPLETED,
                progress = 1f,
                filePath = outFile.absolutePath
            )
            updateTask(task)
            onStatus(task)
            _completed.value = _completed.value + outFile.absolutePath
            // 下载封面图（与媒体文件同名 .jpg，供播放器显示）
            downloadCoverIfNeeded(coverUrl, File(audioDir, "$name.jpg"))
            task
        } catch (e: Exception) {
            task = task.copy(status = DownloadTask.STATUS_FAILED, error = e.message ?: "下载失败")
            updateTask(task)
            onStatus(task)
            task
        } finally {
            untrackTemp(tempSet)
        }
    }

    /** 下载封面图到媒体文件旁（不阻塞下载主流程，失败静默） */
    private fun downloadCoverIfNeeded(coverUrl: String, target: File) {
        if (coverUrl.isBlank() || target.exists()) return
        try {
            val request = Request.Builder()
                .url(coverUrl)
                .header("User-Agent", BiliApi.USER_AGENT)
                .header("Referer", "https://www.bilibili.com/")
                .build()
            okHttp.newCall(request).execute().use { resp ->
                if (resp.isSuccessful) {
                    resp.body?.byteStream()?.use { input ->
                        target.outputStream().use { output -> input.copyTo(output) }
                    }
                }
            }
        } catch (_: Exception) {
            // 封面下载失败不影响主媒体
        }
    }

    private fun updateTask(task: DownloadTask) {
        _tasks.value = _tasks.value.map { if (it.id == task.id) task else it }
    }

    /** 批量添加任务（用于从磁盘恢复下载记录） */
    fun addTasks(list: List<DownloadTask>) {
        if (list.isEmpty()) return
        _tasks.value = _tasks.value + list
    }

    private fun removeTask(id: String) {
        _tasks.value = _tasks.value.filter { it.id != id }
    }

    fun deleteTask(id: String) {
        val t = _tasks.value.firstOrNull { it.id == id } ?: return
        if (t.filePath.isNotEmpty()) File(t.filePath).delete()
        removeTask(id)
    }

    /** 按文件路径批量移除下载任务记录（文件已删除时调用） */
    fun removeTaskByFile(paths: List<String>) {
        if (paths.isEmpty()) return
        val set = paths.toHashSet()
        _tasks.value = _tasks.value.filterNot { it.filePath in set }
    }

    fun clearCompleted() {
        val completedIds = _tasks.value.filter { it.status == DownloadTask.STATUS_COMPLETED }.map { it.id }
        _tasks.value = _tasks.value.filter { it.status != DownloadTask.STATUS_COMPLETED }
        completedIds.forEach { id ->
            _tasks.value.firstOrNull { it.id == id }?.let { File(it.filePath).delete() }
        }
    }

    /** 清空下载历史记录（仅清记录，不删除文件） */
    fun clearHistory() {
        _tasks.value = emptyList()
    }

    /** 扫描首页统计：视频数 / 音频数 / 占用空间 */
    fun scanStats(): HomeStats {
        val videoExt = setOf("mp4", "m4v", "mkv", "webm")
        val audioExt = setOf("mp3", "m4a", "flac", "wav", "aac", "ogg", "opus")
        var videoCount = 0
        var audioCount = 0
        var bytes = 0L

        fun walk(dir: File) {
            val files = dir.listFiles() ?: return
            for (f in files) {
                if (f.isDirectory) {
                    walk(f)
                } else {
                    val ext = f.extension.lowercase()
                    if (videoExt.contains(ext)) videoCount++
                    else if (audioExt.contains(ext)) audioCount++
                    if (f.isFile) bytes += f.length()
                }
            }
        }
        walk(downloadDir)
        return HomeStats(videoCount, audioCount, bytes)
    }

    /** 流式下载单个文件，返回 0~1 进度 */
    private fun downloadStream(url: String, target: File, referer: String, onProgress: (Float) -> Unit) {
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", BiliApi.USER_AGENT)
            .header("Referer", referer)
            .build()
        okHttp.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) throw IOException("下载失败 HTTP ${resp.code}")
            val body = resp.body ?: throw IOException("空响应体")
            val total = body.contentLength()
            var read = 0L
            val buffer = ByteArray(64 * 1024)
            body.byteStream().use { input ->
                target.outputStream().use { output ->
                    while (true) {
                        if (cancelled.get()) throw IOException("已取消")
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        read += n
                        if (total > 0) onProgress(read.toFloat() / total)
                    }
                }
            }
        }
    }

    /** 使用 MediaMuxer 合并视频与音频流为 MP4 */
    private fun mergeVideoAudio(videoPath: String, audioPath: String, outputPath: String) {
        val muxer = MediaMuxer(outputPath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        val trackPairs = mutableListOf<Pair<MediaExtractor, Int>>()
        try {
            val vExt = MediaExtractor()
            vExt.setDataSource(videoPath)
            for (i in 0 until vExt.trackCount) {
                val fmt = vExt.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("video/")) {
                    vExt.selectTrack(i)
                    val idx = muxer.addTrack(fmt)
                    trackPairs.add(Pair(vExt, idx))
                    break
                }
            }

            val aExt = MediaExtractor()
            aExt.setDataSource(audioPath)
            for (i in 0 until aExt.trackCount) {
                val fmt = aExt.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("audio/")) {
                    aExt.selectTrack(i)
                    val idx = muxer.addTrack(fmt)
                    trackPairs.add(Pair(aExt, idx))
                    break
                }
            }

            if (trackPairs.isEmpty()) throw IOException("未找到可合并的轨道")

            muxer.start()
            val buffer = ByteBuffer.allocate(1024 * 1024)
            val info = MediaCodec.BufferInfo()

            for ((ext, trackIdx) in trackPairs) {
                ext.seekTo(0, MediaExtractor.SEEK_TO_CLOSEST_SYNC)
                while (true) {
                    if (cancelled.get()) throw IOException("已取消")
                    val size = ext.readSampleData(buffer, 0)
                    if (size < 0) break
                    info.offset = 0
                    info.size = size
                    info.presentationTimeUs = ext.sampleTime
                    val sf = ext.sampleFlags
                    info.flags = if (sf and MediaExtractor.SAMPLE_FLAG_SYNC != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                    muxer.writeSampleData(trackIdx, buffer, info)
                    ext.advance()
                }
            }
            muxer.stop()
        } finally {
            muxer.release()
            trackPairs.forEach { runCatching { it.first.release() } }
        }
    }

    /**
     * 构建安全的下载文件名：
     * 1. 分P名与标题重复/为空时不拼接，避免标题重复
     * 2. 按 UTF-8 字节数截断（文件系统文件名上限 255 字节，中日韩字符占 3 字节）
     */
    private fun buildFileName(title: String, part: String): String {
        val safeTitle = sanitizeFilename(title)
        val p = part.trim()
        val raw = if (p.isBlank() || p == title || p == safeTitle) safeTitle
        else "${safeTitle}_${sanitizeFilename(p)}"
        return truncateBytes(raw, 180)
    }

    private fun sanitizeFilename(name: String): String {
        var s = name.replace(Regex("[<>:\"/\\\\|?*\\u0000-\\u001f]"), "_")
        s = s.trim().trimEnd('.', ' ')
        if (s.isEmpty()) s = "untitled"
        return s
    }

    /** 按 UTF-8 字节数截断字符串（避免文件名超长导致 ENOENT） */
    private fun truncateBytes(s: String, maxBytes: Int): String {
        if (s.toByteArray(Charsets.UTF_8).size <= maxBytes) return s
        var low = 0
        var high = s.length
        while (low < high) {
            val mid = (low + high + 1) / 2
            if (s.substring(0, mid).toByteArray(Charsets.UTF_8).size <= maxBytes) low = mid
            else high = mid - 1
        }
        return s.substring(0, low)
    }
}
