package com.bili23.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.bili23.android.data.BiliApi
import com.bili23.android.data.AudioItem
import com.bili23.android.data.DownloadManager
import com.bili23.android.data.DownloadTask
import com.bili23.android.data.FavoriteFolder
import com.bili23.android.data.HomeStats
import com.bili23.android.data.PlayUrl
import com.bili23.android.data.QrLogin
import com.bili23.android.data.QrPollResult
import com.bili23.android.data.SearchResult
import com.bili23.android.data.Settings
import com.bili23.android.data.UserInfo
import com.bili23.android.data.VideoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

/** 全局共享状态 */
class AppViewModel(app: Application) : AndroidViewModel(app) {

    val api = BiliApi(BiliApi.buildClient())
    var downloadDir: File = File(app.getExternalFilesDir(null), Settings.downloadDirName).apply { mkdirs() }
        private set
    lateinit var downloadManager: DownloadManager

    init {
        downloadManager = DownloadManager(BiliApi.buildClient(), downloadDir)
    }

    /** 修改下载目录名并重建管理器 */
    fun changeDownloadDir(newName: String) {
        val name = newName.trim().ifBlank { "Download" }
        // 移除非法字符
        val safe = name.replace(Regex("[<>:\"/\\\\|?*]"), "_")
        Settings.downloadDirName = safe
        val app = getApplication<Application>()
        downloadDir = File(app.getExternalFilesDir(null), safe).apply { mkdirs() }
        downloadManager = DownloadManager(BiliApi.buildClient(), downloadDir)
        diskScanned = false
        scanAudioFiles()
        refreshHomeStats()
    }

    // ---- 搜索 ----
    private val _searchResults = MutableStateFlow<SearchResult>(SearchResult())
    val searchResults: StateFlow<SearchResult> get() = _searchResults
    private val _searchLoading = MutableStateFlow(false)
    val searchLoading: StateFlow<Boolean> get() = _searchLoading
    private val _searchKeyword = MutableStateFlow("")
    private val _searchPage = MutableStateFlow(1)

    // ---- 详情 / 播放 ----
    private val _videoInfo = MutableStateFlow<VideoInfo?>(null)
    val videoInfo: StateFlow<VideoInfo?> get() = _videoInfo
    private val _videoLoading = MutableStateFlow(false)
    val videoLoading: StateFlow<Boolean> get() = _videoLoading
    private val _playUrl = MutableStateFlow<PlayUrl>(PlayUrl())
    val playUrl: StateFlow<PlayUrl> get() = _playUrl

    // ---- 当前播放（视频）----
    private val _currentPlay = MutableStateFlow<Triple<String, Long, PlayUrl>?>(null)
    val currentPlay: StateFlow<Triple<String, Long, PlayUrl>?> get() = _currentPlay

    // ---- 本地文件播放（下载完成后直接播放）----
    private val _localPlayPath = MutableStateFlow<String?>(null)
    val localPlayPath: StateFlow<String?> get() = _localPlayPath

    // ---- 本地音频 ----
    private val _audioFiles = MutableStateFlow<List<AudioItem>>(emptyList())
    val audioFiles: StateFlow<List<AudioItem>> get() = _audioFiles

    // ---- 登录 ----
    private val _loggedIn = MutableStateFlow(Settings.isLoggedIn)
    val loggedIn: StateFlow<Boolean> get() = _loggedIn
    private val _loginUser = MutableStateFlow<UserInfo?>(null)
    val loginUser: StateFlow<UserInfo?> get() = _loginUser
    private val _qrLogin = MutableStateFlow<QrLogin?>(null)
    val qrLogin: StateFlow<QrLogin?> get() = _qrLogin
    private val _qrStatus = MutableStateFlow("")
    val qrStatus: StateFlow<String> get() = _qrStatus
    private var polling = false

    // ---- 首页统计 ----
    private val _homeStats = MutableStateFlow(HomeStats())
    val homeStats: StateFlow<HomeStats> get() = _homeStats

    fun search(keyword: String, page: Int = 1) {
        if (keyword.isBlank()) return
        _searchKeyword.value = keyword
        _searchPage.value = page
        _searchLoading.value = true
        viewModelScope.launch {
            val result = api.search(keyword, page)
            if (page <= 1) _searchResults.value = result
            else {
                val prev = _searchResults.value
                // 跨页去重（B站跨页可能返回相同 bvid），避免列表 key 重复导致崩溃
                val merged = prev.videos + result.videos
                val seen = HashSet<String>()
                val dedup = merged.filter { seen.add(it.bvid) }
                _searchResults.value = prev.copy(
                    videos = dedup,
                    total = result.total,
                    page = result.page,
                    hasMore = result.hasMore
                )
            }
            _searchLoading.value = false
        }
    }

    fun loadMore() {
        val cur = _searchResults.value
        if (cur.hasMore && !_searchLoading.value) {
            search(_searchKeyword.value, cur.page + 1)
        }
    }

    fun loadVideoDetail(bvid: String) {
        _videoLoading.value = true
        _videoInfo.value = null
        viewModelScope.launch {
            _videoInfo.value = api.getVideoInfo(bvid)
            _videoLoading.value = false
        }
    }

    fun loadPlayUrl(bvid: String, cid: Long, quality: Int) {
        viewModelScope.launch {
            _playUrl.value = api.getPlayUrl(bvid, cid, quality)
        }
    }

    /** 挂起式加载播放地址，供下载/播放按钮直接使用返回值 */
    suspend fun fetchPlayUrl(bvid: String, cid: Long, quality: Int): PlayUrl {
        val url = api.getPlayUrl(bvid, cid, quality)
        _playUrl.value = url
        return url
    }

    /** 从视频详情在线播放：清空本地播放状态，确保直接实时播放线上内容 */
    fun setCurrentPlay(bvid: String, cid: Long, url: PlayUrl) {
        _localPlayPath.value = null
        _videoPlaylistFilter.value = null
        _videoQueue.value = emptyList()
        _videoQueueIndex.value = 0
        _currentPlay.value = Triple(bvid, cid, url)
    }

    /** 设置本地视频播放路径（下载完成后直接播放） */
    fun setLocalPlayPath(path: String) {
        _videoPlaylistFilter.value = null
        _currentPlay.value = null
        _videoQueue.value = emptyList()
        _videoQueueIndex.value = 0
        _localPlayPath.value = path
    }

    // ---- 视频列表筛选（播放二级界面只显示所选收藏夹内容）----
    private val _videoPlaylistFilter = MutableStateFlow<String?>(null)
    val videoPlaylistFilter: StateFlow<String?> get() = _videoPlaylistFilter

    /** 从本地视频列表进入播放：记录当前筛选的收藏夹，播放页只展示该夹内视频 */
    fun playLocalVideo(path: String, playlist: String?) {
        setLocalPlayPath(path)
        _videoPlaylistFilter.value = playlist
    }

    // ---- 视频播放队列（顺序/循环/随机播放用）----
    private val _videoQueue = MutableStateFlow<List<String>>(emptyList())
    val videoQueue: StateFlow<List<String>> get() = _videoQueue
    private val _videoQueueIndex = MutableStateFlow(0)
    val videoQueueIndex: StateFlow<Int> get() = _videoQueueIndex

    /** 设置视频播放队列并定位到指定项 */
    fun setVideoQueue(paths: List<String>, index: Int) {
        val valid = paths.filter { File(it).exists() }
        _currentPlay.value = null
        _videoQueue.value = if (valid.size <= 1) emptyList() else valid
        _videoQueueIndex.value = index.coerceIn(0, (valid.size - 1).coerceAtLeast(0))
        _localPlayPath.value = valid.getOrNull(_videoQueueIndex.value)
    }

    /** 更新视频队列当前索引（切歌） */
    fun updateVideoQueueIndex(index: Int) {
        val q = _videoQueue.value
        if (q.isEmpty()) return
        val i = index.coerceIn(0, q.size - 1)
        _videoQueueIndex.value = i
        _localPlayPath.value = q[i]
    }

    /** 清空视频队列 */
    fun clearVideoQueue() {
        _videoQueue.value = emptyList()
        _videoQueueIndex.value = 0
    }

    /** 用播放列表启动音频前台服务（分类播放音频） */
    fun playAudioPlaylist(paths: List<String>, startIndex: Int) {
        val valid = paths.filter { File(it).exists() }
        if (valid.isEmpty()) return
        val audioMap = _audioFiles.value.associateBy { it.path }
        val titles = ArrayList<String>()
        val artists = ArrayList<String>()
        val covers = ArrayList<String>()
        valid.forEach { p ->
            val a = audioMap[p]
            titles.add(a?.displayTitle ?: File(p).name.substringBeforeLast('.'))
            artists.add(a?.artist ?: "")
            covers.add(a?.coverPath ?: "")
        }
        val ctx = getApplication<Application>()
        val intent = android.content.Intent(
            ctx, com.bili23.android.service.MusicPlaybackService::class.java
        ).apply {
            action = com.bili23.android.service.MusicPlaybackService.ACTION_SET_PLAYLIST
            putStringArrayListExtra(com.bili23.android.service.MusicPlaybackService.EXTRA_PATHS, ArrayList(valid))
            putStringArrayListExtra(com.bili23.android.service.MusicPlaybackService.EXTRA_TITLES, titles)
            putStringArrayListExtra(com.bili23.android.service.MusicPlaybackService.EXTRA_ARTISTS, artists)
            putStringArrayListExtra(com.bili23.android.service.MusicPlaybackService.EXTRA_COVERS, covers)
            putExtra(com.bili23.android.service.MusicPlaybackService.EXTRA_INDEX, startIndex.coerceIn(0, valid.size - 1))
        }
        ctx.startForegroundService(intent)
    }

    /** 播放本地音频（跳转到音频页自动播放） */
    fun playLocalAudio(path: String) {
        _localAudioToPlay.value = path
    }

    /** 清除待播放标记（音频页消费后调用，避免重复跳转/播放） */
    fun clearLocalAudioToPlay() {
        _localAudioToPlay.value = null
    }

    private val _localAudioToPlay = MutableStateFlow<String?>(null)
    val localAudioToPlay: StateFlow<String?> get() = _localAudioToPlay

    /** 扫描应用目录中的音频文件 */
    fun scanAudioFiles() {
        viewModelScope.launch(Dispatchers.IO) {
            val files = downloadDir.walkTopDown()
                .filter { it.isFile && it.extension.lowercase() in setOf("mp3", "m4a", "flac", "wav", "aac", "ogg") }
                .sortedBy { it.name.lowercase() }
                .map {
                    val tag = Settings.getAudioTag(it.absolutePath)
                    val title = if (tag.first.isNotEmpty()) tag.first
                    else guessSongTitle(it.name.substringBeforeLast('.'))
                    val cover = File(it.parentFile, "${it.name.substringBeforeLast('.')}.jpg")
                    AudioItem(
                        path = it.absolutePath,
                        title = title,
                        artist = tag.second,
                        coverPath = if (cover.exists()) cover.absolutePath else ""
                    )
                }
                .toList()
            // 应用多选调整过的自定义顺序
            _audioFiles.value = Settings.reorderByCustom(
                files, Settings.getCustomOrder(Settings.PLAYLIST_AUDIO)
            ) { it.path }
        }
    }

    /** 多选调整音频位置（上移/下移），持久化保存 */
    fun reorderAudio(paths: List<String>, up: Boolean) {
        val current = _audioFiles.value
        val order = current.map { it.path }
        val newOrder = Settings.moveSelected(order, paths.toSet(), up)
        Settings.setCustomOrder(Settings.PLAYLIST_AUDIO, newOrder)
        _audioFiles.value = Settings.reorderByCustom(current, newOrder) { it.path }
    }

    /** 多选调整视频位置（上移/下移），持久化保存 */
    fun reorderVideos(paths: List<String>, up: Boolean) {
        val order = downloadManager.tasks.value
            .map { it.filePath }
            .filter { it.isNotEmpty() }
            .distinct()
        val newOrder = Settings.moveSelected(order, paths.toSet(), up)
        Settings.setCustomOrder(Settings.PLAYLIST_VIDEO, newOrder)
    }

    /** 拖拽重排音频：将 fromPath 移动到 toPath 所在位置，持久化保存 */
    fun moveAudioPath(fromPath: String, toPath: String) {
        val current = _audioFiles.value
        if (current.isEmpty()) return
        val order = current.map { it.path }
        movePathInOrder(order, fromPath, toPath) { newOrder ->
            Settings.setCustomOrder(Settings.PLAYLIST_AUDIO, newOrder)
            _audioFiles.value = Settings.reorderByCustom(current, newOrder) { it.path }
        }
    }

    /** 拖拽重排视频：以磁盘视频文件为基准（清空下载记录后文件仍显示，拖拽也必须可用） */
    fun moveVideoPath(fromPath: String, toPath: String) {
        val disk = _localVideoFiles.value
        if (disk.isEmpty()) return
        val ordered = Settings.reorderByCustom(disk, Settings.getCustomOrder(Settings.PLAYLIST_VIDEO)) { it }
        movePathInOrder(ordered, fromPath, toPath) { newOrder ->
            Settings.setCustomOrder(Settings.PLAYLIST_VIDEO, newOrder)
        }
    }

    /** 将 fromPath 移到 toPath 处（from 移除后插入到 to），并在成功时执行持久化 */
    private inline fun movePathInOrder(
        order: List<String>,
        fromPath: String,
        toPath: String,
        save: (List<String>) -> Unit
    ) {
        val fromIdx = order.indexOf(fromPath)
        val toIdx = order.indexOf(toPath)
        if (fromIdx < 0 || toIdx < 0 || fromIdx == toIdx) return
        val newOrder = order.toMutableList().apply { add(toIdx, removeAt(fromIdx)) }
        save(newOrder)
    }

    /** 更新音频标签并重新扫描 */
    fun updateAudioTag(path: String, title: String, artist: String) {
        Settings.setAudioTag(path, title, artist)
        scanAudioFiles()
    }

    /** 按标签重命名歌曲与配套文件（歌名-歌手） */
    fun renameAudioByTag(path: String, title: String, artist: String) {
        val t = title.trim()
        val a = artist.trim()
        if (t.isEmpty() && a.isEmpty()) return
        val base = File(path)
        val name = when {
            t.isNotEmpty() && a.isNotEmpty() -> "${t}-${a}"
            t.isNotEmpty() -> t
            else -> a
        }
        val safeName = name.replace(Regex("[<>:\"/\\\\|?*\\u0000-\\u001f]"), "_")
            .trim().trimEnd('.', ' ')
        if (safeName.isEmpty()) return
        val parent = base.parentFile ?: return
        val newFile = File(parent, "$safeName.${base.extension}")
        if (newFile.absolutePath == base.absolutePath || newFile.exists()) return
        val oldPath = base.absolutePath
        if (!base.renameTo(newFile)) return
        val oldBase = oldPath.substringBeforeLast('.')
        runCatching { File("$oldBase.jpg").renameTo(File(parent, "$safeName.jpg")) }
        runCatching { File("$oldBase.lrc").renameTo(File(parent, "$safeName.lrc")) }
        runCatching { File("$oldBase.lrc.tl").renameTo(File(parent, "$safeName.lrc.tl")) }
        val newPath = newFile.absolutePath
        // 迁移标签
        Settings.setAudioTag(newPath, t, a)
        Settings.clearAudioTag(oldPath)
        // 歌词迁移（文件已移动，prefs 兜底读取后写入新路径）
        val oldLrc = Settings.getLyric(oldPath)
        if (oldLrc.isNotEmpty()) Settings.setLyric(newPath, oldLrc)
        val oldTl = Settings.getLyricTranslation(oldPath)
        if (oldTl.isNotEmpty()) Settings.setLyricTranslation(newPath, oldTl)
        // 更新播放列表与收藏路径引用
        Settings.updatePlaylistPath(oldPath, newPath)
        scanAudioFiles()
    }

    /** 从文件名猜测歌名（去除 B 站命名噪音，如 video_260810_233203 时间戳） */
    private fun guessSongTitle(fileName: String): String {
        var name = fileName
        // 去除 "_video_xxxxxxxx_xxxxxx" / "_audio_..." 时间戳后缀
        name = name.replace(Regex("_?(video|audio)?_\\d{6,}_\\d{6,}$"), "")
        name = name.replace(Regex("_?\\d{8}_\\d{6}$"), "")
        // 去除前后冗余分隔符
        name = name.trim('_', '-', ' ', '.')
        return name.ifBlank { fileName }
    }

    /** 扫描磁盘上已下载的视频/音频文件（应用重启后恢复下载记录，每会话仅执行一次） */
    private var diskScanned = false
    fun scanDiskDownloads() {
        // 每会话只扫描一次，避免“清空历史记录”后重新进入页面又被磁盘扫描加回来
        if (diskScanned) return
        diskScanned = true
        viewModelScope.launch(Dispatchers.IO) {
            // m4v 仅用于视频下载临时文件，不作为成品扫描，避免产生重复视频记录
            val videoExt = setOf("mp4", "mkv", "webm")
            val audioExt = setOf("mp3", "m4a", "flac", "wav", "aac", "ogg")
            val recovered = mutableListOf<DownloadTask>()
            // 正在下载的临时文件跳过，避免把 .m4v/.m4a 误当成品产生重复记录
            val tempSet = downloadManager.activeTempFiles.value

            fun walk(dir: File) {
                val files = dir.listFiles() ?: return
                for (f in files) {
                    if (f.isDirectory) { walk(f); continue }
                    if (f.absolutePath in tempSet) continue
                    val ext = f.extension.lowercase()
                    if (ext !in videoExt && ext !in audioExt) continue
                    val type = if (ext in videoExt) DownloadTask.TYPE_VIDEO else DownloadTask.TYPE_AUDIO
                    val name = f.name.substringBeforeLast('.')
                    recovered.add(
                        DownloadTask(
                            id = "disk_${f.absolutePath.hashCode()}",
                            title = name,
                            bvid = "",
                            cid = 0,
                            part = "",
                            quality = if (type == DownloadTask.TYPE_VIDEO) Settings.defaultQuality else 0,
                            status = DownloadTask.STATUS_COMPLETED,
                            filePath = f.absolutePath,
                            type = type
                        )
                    )
                }
            }
            walk(downloadDir)
            // 与内存任务合并（磁盘任务仅当不在内存任务中才添加）
            val current = downloadManager.tasks.value
            val existing = current.map { it.filePath }.toSet()
            val toAdd = recovered.filter { it.filePath !in existing }
            downloadManager.addTasks(toAdd)
        }
    }

    // ---- 本地视频文件（独立于下载记录，清空下载记录后仍保留）----
    private val _localVideoFiles = MutableStateFlow<List<String>>(emptyList())
    val localVideoFiles: StateFlow<List<String>> get() = _localVideoFiles

    /** 扫描磁盘上的本地视频文件路径（每次进入视频页调用，反映磁盘真实状态） */
    fun scanLocalVideos() {
        viewModelScope.launch(Dispatchers.IO) {
            _localVideoFiles.value = downloadDir.walkTopDown()
                .filter { it.isFile && it.extension.lowercase() in setOf("mp4", "mkv", "webm") }
                .map { it.absolutePath }
                .sortedBy { it.substringAfterLast('/') }
                .toList()
        }
    }

    // ------------------------------------------------------------------
    // 登录
    // ------------------------------------------------------------------
    fun refreshLoginState() {
        _loggedIn.value = Settings.isLoggedIn
        if (Settings.isLoggedIn) {
            viewModelScope.launch {
                _loginUser.value = api.getLoginUser()
            }
        } else {
            _loginUser.value = null
        }
    }

    fun startQrLogin() {
        viewModelScope.launch {
            _qrStatus.value = "正在获取二维码..."
            val qr = api.qrGenerate()
            if (qr == null || qr.url.isEmpty()) {
                _qrStatus.value = "获取二维码失败"
                return@launch
            }
            _qrLogin.value = qr
            _qrStatus.value = "请使用B站APP扫描二维码"
            polling = true
            while (polling) {
                delay(2000)
                val r = api.qrPoll(qr.qrcodeKey)
                if (r.code == 0) {
                    polling = false
                    Settings.cookie = r.cookie
                    Settings.nickname = ""
                    _loggedIn.value = true
                    _qrStatus.value = "登录成功！"
                    viewModelScope.launch { _loginUser.value = api.getLoginUser() }
                } else {
                    _qrStatus.value = r.message
                    if (r.code == 86038) {
                        polling = false
                        _qrLogin.value = null
                    }
                }
            }
        }
    }

    fun stopQrPoll() {
        polling = false
    }

    /** Cookie 登录 */
    fun loginWithCookie(cookie: String): String {
        if (!cookie.contains("SESSDATA=")) return "Cookie 中缺少 SESSDATA"
        Settings.cookie = cookie
        Settings.nickname = ""
        _loggedIn.value = true
        refreshLoginState()
        return ""
    }

    fun logout() {
        Settings.cookie = ""
        _loggedIn.value = false
        _loginUser.value = null
    }

    // ------------------------------------------------------------------
    // 首页统计
    // ------------------------------------------------------------------
    fun refreshHomeStats() {
        viewModelScope.launch(Dispatchers.IO) {
            _homeStats.value = downloadManager.scanStats()
        }
    }

    // ------------------------------------------------------------------
    // 歌词搜索
    // ------------------------------------------------------------------
    /** 网易云搜索歌曲列表 */
    suspend fun searchLyrics(keyword: String): List<Pair<String, Long>> =
        api.searchNetease(keyword)

    /** 获取歌词文本 */
    suspend fun fetchLyric(songId: Long): String =
        api.getNeteaseLyric(songId)

    /** 获取歌词 + 日语/外文翻译（LRC） */
    suspend fun fetchLyricWithTranslation(songId: Long): Pair<String, String> =
        api.getNeteaseLyricWithTranslation(songId)

    // ------------------------------------------------------------------
    // 我的收藏
    // ------------------------------------------------------------------
    private val _favoriteFolders = MutableStateFlow<List<FavoriteFolder>>(emptyList())
    val favoriteFolders: StateFlow<List<FavoriteFolder>> get() = _favoriteFolders
    private val _favoriteVideos = MutableStateFlow<List<VideoInfo>>(emptyList())
    val favoriteVideos: StateFlow<List<VideoInfo>> get() = _favoriteVideos
    private val _favLoading = MutableStateFlow(false)
    val favLoading: StateFlow<Boolean> get() = _favLoading

    fun loadFavoriteFolders() {
        val mid = _loginUser.value?.mid ?: return
        viewModelScope.launch {
            _favLoading.value = true
            _favoriteFolders.value = api.getFavoriteFolders(mid)
            _favLoading.value = false
        }
    }

    fun loadFavoriteVideos(folderId: Long) {
        viewModelScope.launch {
            _favLoading.value = true
            _favoriteVideos.value = api.getFavoriteVideos(folderId)
            _favLoading.value = false
        }
    }

    /** 删除本地音频文件（含同名封面、收藏标记） */
    fun deleteAudioFile(path: String) {
        deleteAudioFiles(listOf(path))
    }

    /** 批量删除本地音频文件（多选整理用） */
    fun deleteAudioFiles(paths: List<String>) {
        paths.forEach { p ->
            runCatching { File(p).delete() }
            Settings.setFavorite(p, false)
            Settings.clearLyric(p)
            removeFromAllPlaylists(p)
            runCatching { File(p.substringBeforeLast('.') + ".jpg").delete() }
        }
        scanAudioFiles()
    }

    /** 删除本地视频文件（含同名封面、收藏标记） */
    fun deleteVideoFile(path: String) {
        deleteVideoFiles(listOf(path))
    }

    /** 批量删除本地视频文件（多选整理用） */
    fun deleteVideoFiles(paths: List<String>) {
        paths.forEach { p ->
            runCatching { File(p).delete() }
            Settings.setFavorite(p, false)
            removeFromAllPlaylists(p)
            runCatching { File(p.substringBeforeLast('.') + ".jpg").delete() }
        }
        // 同步移除下载任务记录
        downloadManager.removeTaskByFile(paths)
    }

    /** 从全部播放列表中移除文件（删除文件时同步清理，视频/音频两种类型都清理） */
    private fun removeFromAllPlaylists(path: String) {
        for (type in listOf(Settings.PLAYLIST_VIDEO, Settings.PLAYLIST_AUDIO)) {
            val map = Settings.getPlaylists(type)
            var changed = false
            map.forEach { (name, list) ->
                if (list.remove(path)) changed = true
            }
            if (changed) Settings.applyPlaylists(type, map)
        }
    }

    /** 停止音频前台服务（播放视频前调用，避免音视频冲突） */
    fun stopMusic() {
        if (!com.bili23.android.service.MusicPlaybackService.serviceActive) return
        val ctx = getApplication<Application>()
        val intent = android.content.Intent(ctx, com.bili23.android.service.MusicPlaybackService::class.java).apply {
            action = com.bili23.android.service.MusicPlaybackService.ACTION_STOP
        }
        ctx.startService(intent)
    }
}
