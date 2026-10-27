package com.bili23.android.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.MergingMediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.session.CommandButton
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.bili23.android.R
import com.bili23.android.data.BiliApi
import com.bili23.android.data.PlayUrl
import com.bili23.android.data.Settings
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import java.io.File
import kotlin.random.Random
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 视频播放前台服务（Media3 MediaSessionService）：
 * 1. 持有 ExoPlayer：息屏 / 切后台 / 划掉任务后仍继续播放，进程不被回收
 * 2. 通过 Media3 MediaSession 接入系统媒体会话：控制中心、锁屏、AOD、蓝牙 / 耳机媒体键
 *    都能直接控制 播放/暂停/上一集/下一集/拖拽进度
 * 3. 本地视频用播放器自身播放列表（顺序 / 列表循环 / 单曲循环 / 随机）；在线视频按分P
 *    单集换源播放，切集复用同一播放器（setMediaSource）不再重建，无黑屏闪烁
 * 4. 通知栏自定义按钮：定时关闭（15/30/60 分钟循环）+ 关闭；在线多分P 额外提供 上一集/下一集
 */
@OptIn(UnstableApi::class)
class VideoPlaybackService : MediaSessionService() {

    companion object {
        // ---- UI → 服务指令 ----
        const val ACTION_PLAY_LOCAL = "com.bili23.android.video.PLAY_LOCAL"
        const val ACTION_PLAY_ONLINE = "com.bili23.android.video.PLAY_ONLINE"
        const val ACTION_PLAY = "com.bili23.android.video.PLAY"
        const val ACTION_PAUSE = "com.bili23.android.video.PAUSE"
        const val ACTION_TOGGLE = "com.bili23.android.video.TOGGLE"
        const val ACTION_PREV = "com.bili23.android.video.PREV"
        const val ACTION_NEXT = "com.bili23.android.video.NEXT"
        const val ACTION_SEEK = "com.bili23.android.video.SEEK"
        const val ACTION_SET_MODE = "com.bili23.android.video.SET_MODE"
        const val ACTION_TIMER = "com.bili23.android.video.TIMER"
        const val ACTION_STOP = "com.bili23.android.video.STOP"

        const val EXTRA_PATHS = "paths"
        const val EXTRA_INDEX = "index"
        const val EXTRA_BVID = "bvid"
        const val EXTRA_CID = "cid"
        const val EXTRA_TITLE = "title"
        const val EXTRA_COVER = "cover"
        const val EXTRA_VIDEO_URL = "video_url"
        const val EXTRA_AUDIO_URL = "audio_url"
        const val EXTRA_QUALITY = "quality"
        const val EXTRA_POSITION = "position"
        const val EXTRA_MODE = "mode"

        private const val TAG = "Bili23Video"
        private const val CHANNEL_ID = "bili23_video"
        private const val NOTIFICATION_ID = 2
        private const val SESSION_ID = "BiliVideo"

        /** 通知栏 / 系统媒体控件自定义命令 */
        private val CUSTOM_PREV = SessionCommand(ACTION_PREV, Bundle.EMPTY)
        private val CUSTOM_NEXT = SessionCommand(ACTION_NEXT, Bundle.EMPTY)
        private val CUSTOM_TIMER = SessionCommand(ACTION_TIMER, Bundle.EMPTY)
        private val CUSTOM_STOP = SessionCommand(ACTION_STOP, Bundle.EMPTY)

        // 播放模式：0=顺序 1=列表循环 2=单曲循环 3=随机
        const val MODE_ORDER = 0
        const val MODE_LOOP_LIST = 1
        const val MODE_LOOP_ONE = 2
        const val MODE_SHUFFLE = 3

        // ---- 供 UI 轮询的播放状态 ----
        @Volatile
        var serviceActive: Boolean = false
            private set

        @Volatile
        var playMode: Int = MODE_ORDER
            private set

        @Volatile
        var isPlaying: Boolean = false
            private set

        /** 是否正在缓冲 / 拉取地址（UI 显示加载圈） */
        @Volatile
        var isBuffering: Boolean = false
            private set

        @Volatile
        var position: Long = 0L
            private set

        @Volatile
        var duration: Long = 0L
            private set

        @Volatile
        var currentTitle: String = ""
            private set

        /** 当前分P名（本地视频为空） */
        @Volatile
        var currentPart: String = ""
            private set

        /** 当前封面（本地为同级 jpg，在线为网络封面地址） */
        @Volatile
        var currentCover: String = ""
            private set

        /** 当前序号（0 起） */
        @Volatile
        var currentIndex: Int = 0
            private set

        /** 队列 / 选集总数 */
        @Volatile
        var queueCount: Int = 1
            private set

        /** 是否本地视频 */
        @Volatile
        var isLocal: Boolean = true
            private set

        /** 是否有多个条目（决定是否显示上一集/下一集） */
        @Volatile
        var hasQueueNav: Boolean = false
            private set

        /** 在线当前分P 的 cid（选集列表高亮用；本地为 0） */
        @Volatile
        var currentCid: Long = 0L
            private set

        /** 定时关闭剩余毫秒（0=未开启） */
        @Volatile
        var timerRemainingMs: Long = 0L
            private set

        /** 最近一次播放错误（空字符串=正常） */
        @Volatile
        var lastError: String = ""
            private set

        /** 当前媒体标识："local:路径" 或 "online:bvid:cid"，供 UI 判断是否已是同一内容 */
        @Volatile
        var currentMediaKey: String = ""
            private set

        /** 当前播放的本地文件路径（本地视频时有效，供界面高亮列表项） */
        @Volatile
        var currentLocalPath: String = ""
            private set

        /**
         * 供 PlayerView 绑定的播放器实例。服务与界面同进程，PlayerView 需要真实的
         * ExoPlayer 才能贴附渲染表面，因此这里直接暴露实例（服务销毁时置空）。
         */
        @Volatile
        var playerForUi: ExoPlayer? = null
            private set
    }

    private lateinit var player: ExoPlayer
    private lateinit var mediaSession: MediaSession
    private lateinit var contentIntent: PendingIntent

    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = MainScope()
    private val api by lazy { BiliApi(BiliApi.buildClient()) }

    /** 在线流的 HTTP 数据源（Referer / UA 校验），只负责 http(s) 协议 */
    private val httpDataSourceFactory = DefaultHttpDataSource.Factory()
        .setUserAgent(BiliApi.USER_AGENT)
        .setDefaultRequestProperties(
            mapOf(
                "Referer" to "https://www.bilibili.com/",
                "Origin" to "https://www.bilibili.com"
            )
        )
        .setAllowCrossProtocolRedirects(true)

    /**
     * 统一数据源：http(s) 走带 Referer/UA 的 [httpDataSourceFactory]，
     * file:// / content:// 等本地协议由 DefaultDataSource 自行处理。
     * 注意：不能把 HTTP 源工厂直接交给播放器，否则本地视频会因协议不支持而无法播放。
     */
    private val dataSourceFactory by lazy { DefaultDataSource.Factory(this, httpDataSourceFactory) }

    /** 本地队列（文件路径） */
    private val localPaths = mutableListOf<String>()
    /** 在线选集（cid + 分P名） */
    private val episodes = mutableListOf<Pair<Long, String>>()
    private var bvid = ""
    private var quality = 100
    /** 已解析的分P 播放地址缓存（cid → 地址），避免重复请求 */
    private val urlCache = HashMap<Long, PlayUrl>()
    /** 正在拉取新分P 地址（避免重复触发） */
    private var switching = false

    /** 是否已调用过 startForeground（避免重复转前台覆盖媒体通知） */
    private var foregroundStarted = false

    /** 定时关闭剩余毫秒（0=关闭） */
    private var timerMillis = 0L
    /** 通知中已展示的定时剩余分钟 */
    private var timerShownMinutes = 0

    private val progressSync = object : Runnable {
        override fun run() {
            try {
                syncState()
            } catch (_: Exception) {
                // 忽略单次同步失败
            }
            if (timerMillis > 0) {
                timerMillis -= 500
                if (timerMillis <= 0) {
                    timerMillis = 0
                    stopPlaybackAndSelf()
                    return
                }
                if (timerMinutes() != timerShownMinutes) {
                    timerShownMinutes = timerMinutes()
                    refreshNotification()
                }
            }
            mainHandler.postDelayed(this, 500)
        }
    }

    /** 前台就绪保护：15 秒内仍未开始播放则自动停止，避免占位通知常驻 */
    private val fgsGuard = object : Runnable {
        override fun run() {
            if (!player.isPlaying && player.playbackState != Player.STATE_BUFFERING) {
                stopPlaybackAndSelf()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        serviceActive = true
        // 播放模式沿用用户上次的选择（存于设置）
        playMode = Settings.videoPlayMode

        ensureChannel()
        // 媒体通知提供者：标题/正文使用服务状态，锁屏与控制中心由此集成
        setMediaNotificationProvider(BiliVideoNotificationProvider(this))

        player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(
                androidx.media3.exoplayer.source.DefaultMediaSourceFactory(dataSourceFactory)
            )
            // 拔耳机 / 蓝牙断开自动暂停
            .setHandleAudioBecomingNoisy(true)
            .build()
        player.setAudioAttributes(AudioAttributes.DEFAULT, true)
        player.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                when (playbackState) {
                    Player.STATE_BUFFERING -> isBuffering = true
                    Player.STATE_READY -> {
                        isBuffering = false
                        lastError = ""
                    }

                    Player.STATE_ENDED -> {
                        isBuffering = false
                        onEnded()
                    }

                    Player.STATE_IDLE -> isBuffering = false
                }
                syncState()
            }

            override fun onIsPlayingChanged(playing: Boolean) {
                if (playing) mainHandler.removeCallbacks(fgsGuard)
                syncState()
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                // 本地队列自动/手动切换：同步当前曲目（含随机顺序下的定位）
                if (isLocal) {
                    val path = mediaItem?.mediaId
                    if (path != null && File(path).exists()) {
                        currentIndex = player.currentMediaItemIndex.coerceAtLeast(0)
                        applyLocalMeta(path)
                    }
                }
                syncState()
            }

            override fun onPlayerError(error: PlaybackException) {
                isBuffering = false
                lastError = "播放失败：${error.errorCodeName}"
                Log.w(TAG, "onPlayerError", error)
                syncState()
            }
        })
        playerForUi = player

        contentIntent = PendingIntent.getActivity(
            this, 0,
            packageManager.getLaunchIntentForPackage(packageName),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        mediaSession = try {
            createSession(SESSION_ID)
        } catch (_: IllegalStateException) {
            createSession("$SESSION_ID-${System.currentTimeMillis()}")
        }
        // 必须显式注册：框架层控制器（系统 UI / 控制中心 / AOD）不会触发 Media3 的自动注册，
        // 不注册则通知栏无媒体卡、前台服务也会因未调用 startForeground 被系统杀死
        addSession(mediaSession)
        updateMediaButtonPreferences()
        mainHandler.post(progressSync)
    }

    /** 提前创建通知频道（与 Media3 默认一致：低重要性、不出横幅） */
    private fun ensureChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.bili23_video_channel),
                    NotificationManager.IMPORTANCE_LOW
                ).apply { setShowBadge(false) }
            )
        }
    }

    /** 创建媒体会话（含自定义按钮回调） */
    private fun createSession(id: String): MediaSession =
        MediaSession.Builder(this, player)
            .setId(id)
            .setSessionActivity(contentIntent)
            .setCallback(object : MediaSession.Callback {
                override fun onConnect(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo
                ): MediaSession.ConnectionResult {
                    val availableSessionCommands = MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS
                        .buildUpon()
                        .add(CUSTOM_PREV)
                        .add(CUSTOM_NEXT)
                        .add(CUSTOM_TIMER)
                        .add(CUSTOM_STOP)
                        .build()
                    return MediaSession.ConnectionResult.AcceptedResultBuilder(session)
                        .setAvailableSessionCommands(availableSessionCommands)
                        .build()
                }

                override fun onCustomCommand(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo,
                    customCommand: SessionCommand,
                    args: Bundle
                ): ListenableFuture<SessionResult> {
                    Log.i(TAG, "onCustomCommand: ${customCommand.customAction}")
                    when (customCommand.customAction) {
                        ACTION_PREV -> skipPrev()
                        ACTION_NEXT -> skipNext()
                        ACTION_TIMER -> cycleTimer()
                        ACTION_STOP -> stopPlaybackAndSelf()
                    }
                    return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
                }
            })
            .build()

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 系统以 START_STICKY 重启且无任务：直接停止，避免空闲会话
        if (intent == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        when (intent.action) {
            ACTION_PLAY_LOCAL -> {
                val paths = intent.getStringArrayListExtra(EXTRA_PATHS) ?: emptyList<String>()
                val index = intent.getIntExtra(EXTRA_INDEX, 0)
                // 先同步转前台：避免 startForegroundService 超时被杀
                startForegroundImmediately()
                MediaArbiter.stopMusic(this)
                playLocal(paths, index)
            }

            ACTION_PLAY_ONLINE -> {
                val b = intent.getStringExtra(EXTRA_BVID) ?: return START_NOT_STICKY
                val cid = intent.getLongExtra(EXTRA_CID, 0L)
                startForegroundImmediately()
                MediaArbiter.stopMusic(this)
                playOnline(
                    bvid = b,
                    cid = cid,
                    title = intent.getStringExtra(EXTRA_TITLE) ?: "",
                    cover = intent.getStringExtra(EXTRA_COVER) ?: "",
                    q = intent.getIntExtra(EXTRA_QUALITY, Settings.defaultQuality),
                    firstUrl = PlayUrl(
                        quality = intent.getIntExtra(EXTRA_QUALITY, Settings.defaultQuality),
                        videoUrl = intent.getStringExtra(EXTRA_VIDEO_URL) ?: "",
                        audioUrl = intent.getStringExtra(EXTRA_AUDIO_URL) ?: ""
                    )
                )
            }

            ACTION_PLAY -> player.play()
            ACTION_PAUSE -> player.pause()
            ACTION_TOGGLE -> if (player.isPlaying) player.pause() else player.play()
            ACTION_PREV -> skipPrev()
            ACTION_NEXT -> skipNext()
            ACTION_SEEK -> player.seekTo(intent.getLongExtra(EXTRA_POSITION, 0L))
            ACTION_SET_MODE -> {
                playMode = intent.getIntExtra(EXTRA_MODE, playMode)
                Settings.videoPlayMode = playMode
                applyPlayMode()
                refreshNotification()
            }

            ACTION_TIMER -> cycleTimer()
            ACTION_STOP -> {
                stopPlaybackAndSelf()
                return START_NOT_STICKY
            }
        }
        return super.onStartCommand(intent, flags, startId)
    }

    // ---------------- 本地视频 ----------------

    private fun playLocal(paths: List<String>, index: Int) {
        val valid = paths.filter { File(it).exists() }
        if (valid.isEmpty()) {
            stopPlaybackAndSelf()
            return
        }
        isLocal = true
        episodes.clear()
        urlCache.clear()
        bvid = ""
        switching = false
        currentCid = 0L
        localPaths.clear()
        localPaths.addAll(valid)

        val idx = index.coerceIn(0, valid.size - 1)
        val items = valid.map { p ->
            val builder = MediaItem.Builder()
                .setMediaId(p)
                .setUri(Uri.fromFile(File(p)))
                .setMediaMetadata(
                    MediaMetadata.Builder()
                        .setTitle(File(p).nameWithoutExtension)
                        .apply {
                            coverFileOf(p)?.let { setArtworkUri(Uri.fromFile(it)) }
                        }
                        .build()
                )
            builder.build()
        }
        player.setMediaItems(items, idx, 0L)
        applyLocalMeta(valid[idx])
        applyPlayMode()
        player.prepare()
        player.playWhenReady = true
        updateMediaButtonPreferences()
        syncState()
    }

    /** 同步本地视频的静态元数据（标题 / 封面 / 媒体标识） */
    private fun applyLocalMeta(path: String) {
        currentTitle = File(path).nameWithoutExtension
        currentCover = coverFileOf(path)?.absolutePath ?: ""
        currentMediaKey = "local:$path"
        currentLocalPath = path
        currentPart = ""
        currentCid = 0L
    }

    /** 同级封面文件（与视频同名的 jpg） */
    private fun coverFileOf(path: String): File? {
        val f = File(path.substringBeforeLast('.') + ".jpg")
        return if (f.exists()) f else null
    }

    // ---------------- 在线视频 ----------------

    private fun playOnline(
        bvid: String,
        cid: Long,
        title: String,
        cover: String,
        q: Int,
        firstUrl: PlayUrl
    ) {
        val sameVideo = this.bvid == bvid
        isLocal = false
        localPaths.clear()
        this.bvid = bvid
        quality = q
        if (!sameVideo) {
            episodes.clear()
            urlCache.clear()
        }
        // 至少保证当前分P 在列表内（分P 列表稍后由服务自行拉取补全）
        if (episodes.none { it.first == cid }) episodes.add(cid to "")
        if (firstUrl.videoUrl.isNotEmpty()) urlCache[cid] = firstUrl
        if (title.isNotBlank()) currentTitle = title
        if (cover.isNotBlank()) currentCover = cover
        val idx = episodes.indexOfFirst { it.first == cid }.coerceAtLeast(0)
        switching = false
        playOnlineAt(idx, 0L, autoPlay = true)
        // 只有当前分P 时才需要拉取分P 列表（已有列表说明是同一视频内切集）
        if (episodes.size <= 1) refreshEpisodes(bvid)
    }

    /**
     * 拉取视频分P 列表，供后台 / 通知栏切换上一集下一集。
     * 由服务自行获取，界面无需等待详情页加载完成。
     */
    private fun refreshEpisodes(targetBvid: String) {
        if (targetBvid.isEmpty()) return
        scope.launch {
            val info = withContext(Dispatchers.IO) {
                runCatching { api.getVideoInfo(targetBvid) }.getOrNull()
            } ?: return@launch
            // 拉取期间可能已经换视频：丢弃过期结果
            if (this@VideoPlaybackService.bvid != targetBvid) return@launch
            val eps = info.episodes.filter { it.cid > 0 }
            if (eps.size <= 1) return@launch
            val currentCidNow = currentCid
            episodes.clear()
            eps.forEach { episodes.add(it.cid to it.part) }
            if (currentTitle.isBlank()) currentTitle = info.title
            if (currentCover.isBlank()) currentCover = info.coverUrl
            // 保持当前分P 定位（换源后当前分P 不变，只更新序号与列表）
            val idx = episodes.indexOfFirst { it.first == currentCidNow }
            if (idx >= 0) currentIndex = idx
            updateMediaButtonPreferences()
            syncState()
        }
    }

    /**
     * 播放在线选集第 [index] 个分P。地址已缓存则直接换源；未缓存先拉取地址。
     * 换源使用同一个播放器（setMediaSource），不重建播放器，因此切集无黑屏闪烁。
     */
    private fun playOnlineAt(index: Int, startMs: Long, autoPlay: Boolean) {
        if (index !in episodes.indices) return
        val (cid, part) = episodes[index]
        currentIndex = index
        currentCid = cid
        currentPart = part
        currentMediaKey = "online:$bvid:$cid"
        val cached = urlCache[cid]
        if (cached != null && cached.videoUrl.isNotEmpty()) {
            applyOnlineSource(part, cached, startMs, autoPlay)
            return
        }
        switching = true
        isBuffering = true
        lastError = ""
        syncState()
        scope.launch {
            val url = withContext(Dispatchers.IO) {
                runCatching { api.getPlayUrl(bvid, cid, quality, Settings.audioQuality) }
                    .getOrDefault(PlayUrl())
            }
            switching = false
            if (url.videoUrl.isEmpty()) {
                isBuffering = false
                lastError = "获取播放地址失败，请重试"
                syncState()
                return@launch
            }
            urlCache[cid] = url
            applyOnlineSource(part, url, startMs, autoPlay)
        }
    }

    private fun applyOnlineSource(part: String, url: PlayUrl, startMs: Long, autoPlay: Boolean) {
        val item = MediaItem.Builder()
            .setMediaId(currentMediaKey)
            .setUri(Uri.parse(url.videoUrl))
            .setMimeType(MimeTypes.VIDEO_MP4)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(currentTitle.ifBlank { "视频播放" })
                    .setArtist(part)
                    .apply {
                        if (currentCover.startsWith("http")) setArtworkUri(Uri.parse(currentCover))
                    }
                    .build()
            )
            .build()
        val videoSource = ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(item)
        val source: MediaSource = if (url.audioUrl.isNotEmpty()) {
            val audioItem = MediaItem.Builder()
                .setUri(Uri.parse(url.audioUrl))
                .setMimeType(MimeTypes.AUDIO_AAC)
                .build()
            // MergingMediaSource 不携带 MediaItem，包一层后锁屏/控制中心才能显示标题
            ArtworkMediaSource(
                item,
                MergingMediaSource(
                    videoSource,
                    ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(audioItem)
                )
            )
        } else {
            videoSource
        }
        player.setMediaSource(source)
        applyPlayMode()
        player.prepare()
        if (startMs > 0) player.seekTo(startMs)
        player.playWhenReady = autoPlay
        isBuffering = false
        updateMediaButtonPreferences()
        syncState()
    }

    /** 携带 MediaItem 的包装源：让合并流也能向系统媒体会话暴露标题/封面 */
    private class ArtworkMediaSource(
        private val mediaItem: MediaItem,
        delegate: MediaSource
    ) : MediaSource by delegate {
        override fun getMediaItem(): MediaItem = mediaItem
    }

    // ---------------- 通用控制 ----------------

    /** 根据播放模式设置播放器循环 / 随机（系统媒体控件的上一首 / 下一首随之正确工作） */
    private fun applyPlayMode() {
        player.shuffleModeEnabled = playMode == MODE_SHUFFLE
        player.repeatMode = when (playMode) {
            MODE_LOOP_ONE -> Player.REPEAT_MODE_ONE
            // 本地：列表循环/随机交给播放器自身循环；在线：单集换源，由 onEnded 处理
            MODE_LOOP_LIST, MODE_SHUFFLE -> if (isLocal) Player.REPEAT_MODE_ALL else Player.REPEAT_MODE_OFF
            else -> Player.REPEAT_MODE_OFF
        }
    }

    /** 播放自然结束后的行为（与旧版一致：顺序到末尾停止、循环继续、随机乱序） */
    private fun onEnded() {
        when (playMode) {
            MODE_LOOP_ONE -> {
                player.seekTo(0)
                player.play()
            }

            MODE_SHUFFLE -> {
                if (queueCount <= 1) {
                    player.seekTo(0)
                    player.play()
                } else if (isLocal) {
                    // 播放器自身循环处理
                } else {
                    playOnlineAt(randomOtherIndex(), 0L, autoPlay = true)
                }
            }

            MODE_LOOP_LIST -> {
                if (isLocal) {
                    // 本地由播放器自身循环处理
                } else if (queueCount > 1) {
                    playOnlineAt((currentIndex + 1) % queueCount, 0L, autoPlay = true)
                } else {
                    // 在线且只有一集：循环本集
                    player.seekTo(0)
                    player.play()
                }
            }

            else -> {
                if (currentIndex < queueCount - 1) {
                    if (isLocal) {
                        // 播放器自动播放下一个
                    } else {
                        playOnlineAt(currentIndex + 1, 0L, autoPlay = true)
                    }
                } else {
                    player.seekTo(0)
                    player.pause()
                }
            }
        }
    }

    private fun randomOtherIndex(): Int {
        if (queueCount <= 1) return currentIndex
        var n = Random.nextInt(queueCount)
        while (n == currentIndex) n = Random.nextInt(queueCount)
        return n
    }

    private fun skipNext() {
        if (isLocal) {
            if (player.mediaItemCount <= 1) {
                player.seekTo(0)
                player.play()
            } else if (playMode == MODE_SHUFFLE) {
                player.seekToDefaultPosition(randomOtherIndex())
                player.play()
            } else if (player.hasNextMediaItem()) {
                player.seekToNextMediaItem()
            } else {
                player.seekToDefaultPosition(0)
                player.play()
            }
            syncState()
            return
        }
        if (queueCount <= 1) {
            player.seekTo(0)
            player.play()
            return
        }
        val next = if (playMode == MODE_SHUFFLE) randomOtherIndex() else (currentIndex + 1) % queueCount
        playOnlineAt(next, 0L, autoPlay = true)
    }

    private fun skipPrev() {
        // 播放 3 秒以上：先回到本集开头（与常见播放器一致）
        if (player.currentPosition > 3000) {
            player.seekTo(0)
            syncState()
            return
        }
        if (isLocal) {
            if (player.mediaItemCount <= 1) {
                player.seekTo(0)
            } else if (player.hasPreviousMediaItem()) {
                player.seekToPreviousMediaItem()
            } else {
                player.seekToDefaultPosition(player.mediaItemCount - 1)
            }
            syncState()
            return
        }
        if (queueCount <= 1) {
            player.seekTo(0)
            return
        }
        playOnlineAt(if (currentIndex <= 0) queueCount - 1 else currentIndex - 1, 0L, autoPlay = true)
    }

    /** 循环切换定时：关闭 → 15 分钟 → 30 分钟 → 60 分钟 → 关闭 */
    private fun cycleTimer() {
        timerMillis = when {
            timerMillis <= 0 -> 15 * 60_000L
            timerMillis <= 15 * 60_000L -> 30 * 60_000L
            timerMillis <= 30 * 60_000L -> 60 * 60_000L
            else -> 0L
        }
        timerShownMinutes = timerMinutes()
        refreshNotification()
    }

    /** 定时剩余分钟（向上取整；0 = 未开启） */
    private fun timerMinutes(): Int =
        if (timerMillis <= 0) 0 else ((timerMillis + 60_000L - 1) / 60_000L).toInt()

    private fun timerLabel(): String =
        if (timerMinutes() <= 0) "定时关闭" else "定时 ${timerMinutes()} 分"

    /** 刷新通知栏自定义按钮文案（Media3 自动重建媒体通知） */
    private fun refreshNotification() {
        if (::mediaSession.isInitialized) updateMediaButtonPreferences()
    }

    /** 通知栏自定义按钮：在线多分P 提供 上一集/下一集，其余为 定时关闭 / 关闭 */
    private fun updateMediaButtonPreferences() {
        val buttons = ImmutableList.builder<CommandButton>()
        if (!isLocal && episodes.size > 1) {
            buttons.add(
                CommandButton.Builder()
                    .setSessionCommand(CUSTOM_PREV)
                    .setDisplayName("上一集")
                    .setIconResId(R.drawable.ic_prev)
                    .setEnabled(true)
                    .build()
            )
            buttons.add(
                CommandButton.Builder()
                    .setSessionCommand(CUSTOM_NEXT)
                    .setDisplayName("下一集")
                    .setIconResId(R.drawable.ic_next)
                    .setEnabled(true)
                    .build()
            )
        }
        buttons.add(
            CommandButton.Builder()
                .setSessionCommand(CUSTOM_TIMER)
                .setDisplayName(timerLabel())
                .setIconResId(R.drawable.ic_timer)
                .setEnabled(true)
                .build()
        )
        buttons.add(
            CommandButton.Builder()
                .setSessionCommand(CUSTOM_STOP)
                .setDisplayName("关闭")
                .setIconResId(R.drawable.ic_close)
                .setEnabled(true)
                .build()
        )
        mediaSession.setMediaButtonPreferences(buttons.build())
    }

    /** 立即进入前台：占位通知与媒体通知同频道同 ID，播放开始后被自动替换 */
    private fun startForegroundImmediately() {
        // 已在后台运行则不再重复转前台：避免覆盖 Media3 已发布的媒体通知（通知栏闪烁）
        if (!foregroundStarted) {
            foregroundStarted = true
            val notification = NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_play)
                .setContentTitle(getString(R.string.app_name))
                .setContentText("正在准备播放…")
                .setContentIntent(contentIntent)
                .setOngoing(true)
                .setSilent(true)
                .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
                .build()
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
            )
            // 15 秒内仍未进入播放则自动停止，避免占位通知常驻
            mainHandler.removeCallbacks(fgsGuard)
            mainHandler.postDelayed(fgsGuard, 15_000)
        }
    }

    /** 停止播放并退出服务（定时到时 / 关闭按钮 / 退出播放页共用） */
    private fun stopPlaybackAndSelf() {
        mainHandler.removeCallbacks(fgsGuard)
        player.stop()
        player.clearMediaItems()
        localPaths.clear()
        episodes.clear()
        urlCache.clear()
        bvid = ""
        timerMillis = 0
        switching = false
        currentTitle = ""
        currentPart = ""
        currentCover = ""
        currentMediaKey = ""
        currentLocalPath = ""
        currentCid = 0L
        lastError = ""
        isBuffering = false
        foregroundStarted = false
        syncState()
        serviceActive = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /** 同步播放状态到静态字段（供 UI 轮询） */
    private fun syncState() {
        isPlaying = player.isPlaying
        position = player.currentPosition
        duration = player.duration.coerceAtLeast(0L)
        queueCount = if (isLocal) player.mediaItemCount.coerceAtLeast(1) else episodes.size.coerceAtLeast(1)
        if (isLocal) currentIndex = player.currentMediaItemIndex.coerceAtLeast(0)
        hasQueueNav = queueCount > 1
        timerRemainingMs = timerMillis
    }

    override fun onDestroy() {
        serviceActive = false
        mainHandler.removeCallbacks(progressSync)
        mainHandler.removeCallbacks(fgsGuard)
        scope.cancel()
        // 界面可能仍持有该实例：先解绑再释放，避免 PlayerView 引用已释放的播放器
        playerForUi = null
        player.release()
        if (::mediaSession.isInitialized) mediaSession.release()
        super.onDestroy()
    }

    /**
     * 媒体通知提供者：标题 / 正文使用服务自身状态（标题 · 分P · 序号 · 定时），
     * 不依赖播放器元数据，因此在线合并流也能正确显示。
     */
    private inner class BiliVideoNotificationProvider(context: Context) :
        DefaultMediaNotificationProvider(
            context,
            { NOTIFICATION_ID },
            CHANNEL_ID,
            R.string.bili23_video_channel
        ) {
        override fun getNotificationContentTitle(metadata: MediaMetadata): CharSequence =
            currentTitle.ifBlank { "视频播放" }

        override fun getNotificationContentText(metadata: MediaMetadata): CharSequence {
            val parts = ArrayList<String>(3)
            if (currentPart.isNotBlank()) parts.add(currentPart)
            if (hasQueueNav) parts.add("${currentIndex + 1}/$queueCount")
            val minutes = timerMinutes()
            if (minutes > 0) parts.add("定时 $minutes 分后关闭")
            return if (parts.isEmpty()) {
                if (isBuffering) "正在缓冲…" else "正在播放"
            } else {
                parts.joinToString(" · ")
            }
        }
    }
}
