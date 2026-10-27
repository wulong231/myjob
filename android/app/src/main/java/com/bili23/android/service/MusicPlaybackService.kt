package com.bili23.android.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.audiofx.Equalizer
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.CommandButton
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaNotification
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.bili23.android.R
import com.bili23.android.data.Settings
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import java.io.File
import kotlin.random.Random

/**
 * 音频播放前台服务（Media3 MediaSessionService）：
 * 1. 持有 ExoPlayer 保证息屏 / 切后台仍继续播放
 * 2. 通过 Media3 MediaSession 接入系统媒体会话：vivo originOS6 / 各品牌控制中心、锁屏、
 *    AOD 音乐控件、通知栏媒体卡、蓝牙 / 耳机媒体键均可直接控制 播放/暂停/上一首/下一首/拖拽进度
 * 3. 播放列表 + 播放模式（顺序 / 列表循环 / 单曲循环 / 随机）由播放器自身维护（repeat/shuffle）
 * 4. 通知栏自定义按钮：定时关闭（15/30/60 分钟循环）+ 关闭
 * 5. 耳机 / 蓝牙断开自动暂停，重新连接自动续播
 */
@OptIn(UnstableApi::class)
class MusicPlaybackService : MediaSessionService() {

    companion object {
        const val ACTION_PLAY = "com.bili23.android.PLAY"
        const val ACTION_PAUSE = "com.bili23.android.PAUSE"
        const val ACTION_TOGGLE = "com.bili23.android.TOGGLE"
        const val ACTION_PREV = "com.bili23.android.PREV"
        const val ACTION_NEXT = "com.bili23.android.NEXT"
        const val ACTION_PLAY_PATH = "com.bili23.android.PLAY_PATH"
        const val ACTION_SET_PLAYLIST = "com.bili23.android.SET_PLAYLIST"
        const val ACTION_SET_MODE = "com.bili23.android.SET_MODE"
        const val ACTION_SEEK = "com.bili23.android.SEEK"
        const val ACTION_STOP = "com.bili23.android.STOP"
        const val ACTION_TIMER = "com.bili23.android.TIMER"
        const val ACTION_TOGGLE_OVERLAY = "com.bili23.android.TOGGLE_OVERLAY"

        const val EXTRA_PATH = "path"
        const val EXTRA_TITLE = "title"
        const val EXTRA_ARTIST = "artist"
        const val EXTRA_COVER = "cover"
        const val EXTRA_PATHS = "paths"
        const val EXTRA_TITLES = "titles"
        const val EXTRA_ARTISTS = "artists"
        const val EXTRA_COVERS = "covers"
        const val EXTRA_INDEX = "index"
        const val EXTRA_POSITION = "position"
        const val EXTRA_MODE = "mode"

        private const val CHANNEL_ID = "bili23_music"
        private const val NOTIFICATION_ID = 1

        /** 日志标签（排查系统媒体控件回调等） */
        private const val TAG = "Bili23Music"

        /** 媒体会话 ID（系统媒体控件 / 锁屏 / AOD 识别会话用） */
        private const val SESSION_ID = "BiliMusic"

        // 通知栏 / 系统媒体控件自定义命令（定时关闭、关闭）
        private val CUSTOM_TIMER = SessionCommand(ACTION_TIMER, Bundle.EMPTY)
        private val CUSTOM_STOP = SessionCommand(ACTION_STOP, Bundle.EMPTY)

        // 播放模式：0=顺序播放 1=列表循环 2=单曲循环 3=随机播放
        const val MODE_ORDER = 0
        const val MODE_LOOP_LIST = 1
        const val MODE_LOOP_ONE = 2
        const val MODE_SHUFFLE = 3

        /** 当前播放模式（UI 可直接读写切换） */
        @Volatile
        var playMode: Int = MODE_ORDER

        /** 服务是否正在运行（供 UI 判断是否需要发送停止指令） */
        @Volatile
        var serviceActive: Boolean = false

        /** 桌面歌词悬浮窗是否正在显示（供 UI 显示按钮状态） */
        @Volatile
        var overlayActive: Boolean = false
            private set

        /** 定时关闭剩余毫秒（0=未开启），供音频页 / 歌词模式显示 */
        @Volatile
        var timerRemainingMs: Long = 0L
            private set

        /** 当前播放列表（供横屏歌词模式的列表面板使用） */
        @Volatile
        var playlistTitles: List<String> = emptyList()
            private set

        @Volatile
        var playlistPaths: List<String> = emptyList()
            private set

        /** 当前曲目在列表中的序号（0 起） */
        @Volatile
        var currentListIndex: Int = 0
            private set

        var currentTitle: String = ""
            private set
        var currentArtist: String = ""
            private set
        var currentCover: String = ""
            private set

        /** 当前实际播放的文件路径（切歌后供 UI 同步封面/歌词） */
        @Volatile
        var currentPath: String = ""
            private set

        /** 供 UI 轮询的播放状态 */
        @Volatile
        var currentPosition: Long = 0L
            private set
        @Volatile
        var currentDuration: Long = 0L
            private set
        @Volatile
        var isPlaying: Boolean = false
            private set

        /** 是否因耳机/蓝牙断开而自动暂停（耳机重新连接后自动续播） */
        @Volatile
        var pausedForHeadset: Boolean = false
            private set

        /**
         * 最近一次播放列表快照：通知栏"关闭"会停止服务并清空列表，
         * App 内再次点播放时用这份快照恢复，避免"关闭通知后无法继续播放"
         */
        @Volatile
        var lastPaths: List<String> = emptyList()
            private set
        @Volatile
        var lastTitles: List<String> = emptyList()
            private set
        @Volatile
        var lastArtists: List<String> = emptyList()
            private set
        @Volatile
        var lastCovers: List<String> = emptyList()
            private set
        @Volatile
        var lastIndex: Int = 0
            private set

        /** 保存当前列表快照（停止服务前调用） */
        fun saveSnapshot(
            paths: List<String>,
            titles: List<String>,
            artists: List<String>,
            covers: List<String>,
            index: Int
        ) {
            if (paths.isEmpty()) return
            lastPaths = paths
            lastTitles = titles
            lastArtists = artists
            lastCovers = covers
            lastIndex = index
        }
    }

    private data class Track(
        val path: String,
        val title: String,
        val artist: String,
        val cover: String
    )

    private lateinit var player: ExoPlayer
    private lateinit var mediaSession: MediaSession
    private lateinit var contentIntent: PendingIntent
    private val tracks = mutableListOf<Track>()
    private var currentIndex = -1

    /** 主线程定时同步播放进度（ExoPlayer 只允许在主线程访问） */
    private val mainHandler = Handler(Looper.getMainLooper())
    /** 定时关闭剩余毫秒（0=关闭），每次点击累加 15 分钟，最长 60 分钟 */
    private var timerMillis: Long = 0L
    /** 桌面歌词悬浮窗（懒创建，随播放显隐） */
    private var overlay: LyricsOverlay? = null
    /** 通知中已展示的定时剩余分钟（分钟变化时刷新通知文本） */
    private var timerShownMinutes = 0
    /** 耳机/蓝牙重新连接检测计数（约每 2 秒检查一次） */
    private var headsetCheckTicks = 0
    /** 本曲音量调整：已应用的分贝值与对应路径（设置变化时即时重新应用） */
    private var gainEq: Equalizer? = null
    private var appliedGain: Float = 0f
    private var appliedGainPath: String = ""
    /** 均衡器处理器（注入音频 sink）；eqAppliedKey 用于按 400ms 轮询即时同步设置 */
    private val eqProcessor = EqualizerAudioProcessor()
    private var eqAppliedKey: String = ""
    /**
     * 前台就绪保护：服务转前台后 15 秒内仍未进入播放（文件异常、列表为空等），
     * 自动停止服务，避免占位通知常驻
     */
    private val fgsGuard = object : Runnable {
        override fun run() {
            if (!player.isPlaying && player.playbackState != Player.STATE_BUFFERING) {
                stopPlaybackAndSelf()
            }
        }
    }
    private val progressSync = object : Runnable {
        override fun run() {
            try {
                syncState()
            } catch (_: Exception) {
                // 忽略单次同步失败，继续
            }
            // 定时关闭倒计时（每 400ms 递减）
            if (timerMillis > 0) {
                timerMillis -= 400
                if (timerMillis <= 0) {
                    timerMillis = 0
                    stopPlaybackAndSelf()
                } else if (timerMinutes() != timerShownMinutes) {
                    // 剩余分钟变化：刷新通知，正文中的定时信息同步更新
                    timerShownMinutes = timerMinutes()
                    refreshNotification()
                }
            }
            // 桌面歌词：悬浮窗已显示则同步进度；开关为开且当前有曲目时自动显示
            val ov = overlay
            if (ov != null && ov.isShowing) {
                ov.syncPosition(currentPosition, isPlaying)
            } else if (Settings.desktopLyricsEnabled && currentPath.isNotEmpty()) {
                showOverlay()
            }
            // 本曲音量调整：设置值或曲目变化时即时重新应用
            if (currentPath.isNotEmpty() &&
                (currentPath != appliedGainPath || Settings.getTrackGain(currentPath) != appliedGain)
            ) {
                applyTrackGain(currentPath)
            }
            // 均衡器：开关/增益变化时即时更新处理器（不影响播放器构建，无需重挂效果）
            val eqKey = Settings.eqEnabled.toString() + "|" + Settings.eqGainsCsv
            if (eqKey != eqAppliedKey) {
                eqAppliedKey = eqKey
                eqProcessor.update(Settings.eqEnabled, Settings.getEqGains())
            }
            // 耳机/蓝牙重新连接后自动续播（因断开而暂停时）
            headsetCheckTicks++
            if (pausedForHeadset && headsetCheckTicks % 5 == 0 && hasHeadsetDevice()) {
                pausedForHeadset = false
                player.play()
            }
            mainHandler.postDelayed(this, 400)
        }
    }

    /** 耳机/蓝牙断开时自动暂停（ACTION_AUDIO_BECOMING_NOISY：有线耳机拔出、蓝牙断开都会触发） */
    private val headsetReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY && player.isPlaying) {
                player.pause()
                pausedForHeadset = true
            }
        }
    }

    /**
     * 应用本曲音量调整（静态，不做动态压缩）：
     * - 分贝 ≤ 0：直接用播放器音量精确衰减（10^(dB/20)），不挂音效；
     * - 分贝 > 0：播放器音量置满，用 Equalizer 全频段增益提升（受设备最大档位限制）。
     * 每首歌的设置按路径记忆，切歌或调整后 400ms 内自动生效。
     */
    private fun applyTrackGain(path: String) {
        val db = Settings.getTrackGain(path)
        appliedGain = db
        appliedGainPath = path
        gainEq?.release()
        gainEq = null
        if (db <= 0f) {
            player.volume = Math.pow(10.0, (db / 20.0)).toFloat().coerceIn(0f, 1f)
            return
        }
        player.volume = 1f
        try {
            val e = Equalizer(0, player.audioSessionId)
            val maxLevel = e.bandLevelRange?.getOrNull(1)?.toFloat() ?: (db * 100f)
            val target = (db * 100f).coerceAtMost(maxLevel).toInt().toShort()
            for (i in 0 until e.numberOfBands) {
                e.setBandLevel(i.toShort(), target)
            }
            e.enabled = true
            gainEq = e
        } catch (_: Exception) {
            // 设备不支持均衡器时保持原始音量
            gainEq = null
        }
    }

    /** 检测当前是否有耳机/蓝牙音频输出设备（getDevices 无需任何权限） */
    private fun hasHeadsetDevice(): Boolean {
        return try {
            val am = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP ||
                    it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                    it.type == AudioDeviceInfo.TYPE_WIRED_HEADSET ||
                    it.type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES
            }
        } catch (_: Exception) {
            false
        }
    }

    /** 定时剩余分钟（向上取整；0 = 未开启） */
    private fun timerMinutes(): Int =
        if (timerMillis <= 0) 0 else ((timerMillis + 60_000L - 1) / 60_000L).toInt()

    /** 点击一次累加 15 分钟定时，最长 60 分钟；已满 60 分钟后再点一次取消定时 */
    fun cycleTimer() {
        timerMillis = if (timerMillis >= 60 * 60_000L) {
            0L
        } else {
            (timerMillis + 15 * 60_000L).coerceAtMost(60 * 60_000L)
        }
        timerShownMinutes = timerMinutes()
        refreshNotification()
        // 点击后给出即时反馈（同时通知正文会显示定时状态）
        val msg = if (timerMillis <= 0) {
            "已取消定时关闭"
        } else {
            "定时 ${timerMinutes()} 分钟后自动关闭"
        }
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private fun timerLabel(): String {
        val minutes = timerMinutes()
        return if (minutes <= 0) "定时关闭" else "定时 $minutes 分"
    }

    /** 显示桌面歌词悬浮窗（需已授权"显示在其他应用上层"；未授权时静默跳过） */
    private fun showOverlay() {
        if (currentPath.isEmpty()) return
        val o = overlay ?: LyricsOverlay(this) {
            // 点击悬浮窗上的 ×：关闭并记住开关状态
            Settings.desktopLyricsEnabled = false
            hideOverlay()
        }.also { overlay = it }
        if (!o.canShow()) return
        o.loadTrack(currentPath)
        o.syncPosition(player.currentPosition, player.isPlaying)
        o.show()
        overlayActive = o.isShowing
    }

    /** 隐藏桌面歌词悬浮窗（保留开关偏好，便于下次播放自动显示） */
    private fun hideOverlay() {
        overlay?.hide()
        overlayActive = false
    }

    /** 切换桌面歌词（音频页按钮 / 服务指令入口） */
    private fun toggleOverlay() {
        if (overlayActive) {
            Settings.desktopLyricsEnabled = false
            hideOverlay()
            return
        }
        if (currentPath.isEmpty()) {
            Toast.makeText(this, "请先播放音乐再开启桌面歌词", Toast.LENGTH_SHORT).show()
            return
        }
        if (!android.provider.Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "请先授予\"显示在其他应用上层\"权限", Toast.LENGTH_SHORT).show()
            return
        }
        Settings.desktopLyricsEnabled = true
        showOverlay()
    }

    /** 刷新通知栏：更新自定义按钮（定时标签等），Media3 自动重建媒体通知 */
    private fun refreshNotification() {
        if (::mediaSession.isInitialized) {
            updateMediaButtonPreferences()
        }
    }

    /** 停止播放并退出服务（定时到时/停止按钮共用） */
    private fun stopPlaybackAndSelf() {
        mainHandler.removeCallbacks(fgsGuard)
        // 先保存列表快照：关闭通知后 App 内仍可点播放继续
        saveSnapshot(
            tracks.map { it.path },
            tracks.map { it.title },
            tracks.map { it.artist },
            tracks.map { it.cover },
            currentIndex.coerceAtLeast(0)
        )
        player.stop()
        player.clearMediaItems()
        tracks.clear()
        currentIndex = -1
        currentTitle = ""
        currentArtist = ""
        currentCover = ""
        currentPath = ""
        timerMillis = 0
        pausedForHeadset = false
        syncState()
        serviceActive = false
        // 停止播放时移除悬浮歌词（保留开关偏好）
        hideOverlay()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onCreate() {
        super.onCreate()
        serviceActive = true

        // 提前创建通知频道（Media3 也会创建，这里保证占位前台通知随时可显示）
        ensureChannel()

        // 媒体通知提供者：指定频道 / 通知 ID（系统媒体控件、锁屏、AOD 均基于此通知集成），
        // 并在通知正文（歌手行）追加定时关闭状态，拉下通知栏即可看到
        setMediaNotificationProvider(BiliNotificationProvider(this))

        // 播放器（不使用音频卸载：实测本机 vivo 硬解通道无声，已回退普通解码）
        // 渲染器工厂注入均衡器处理器，实现 10 段实时 EQ
        player = ExoPlayer.Builder(this, EqualizerRenderersFactory(this, eqProcessor)).build()
        // 音频焦点：播放时请求焦点，其他 App 播放时自动暂停/降音，恢复后自动续播
        player.setAudioAttributes(AudioAttributes.DEFAULT, true)
        player.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                syncState()
                // 顺序播放模式下最后一首播完：回到开头并暂停（与旧版行为一致）
                if (playbackState == Player.STATE_ENDED && playMode == MODE_ORDER) {
                    player.seekTo(0, 0)
                    player.pause()
                }
            }

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                // 已进入播放：撤掉前台就绪保护
                if (isPlaying) mainHandler.removeCallbacks(fgsGuard)
                syncState()
            }

            override fun onAudioSessionIdChanged(audioSessionId: Int) {
                // 音频会话就绪/变化：重新应用本曲音量调整（均衡器需挂在会话上）
                if (appliedGainPath.isNotEmpty()) applyTrackGain(appliedGainPath)
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                // 自动切歌 / 手动切歌后同步当前曲目（含随机播放顺序下的定位）
                currentIndex = player.currentMediaItemIndex
                val track = tracks.firstOrNull { it.path == mediaItem?.mediaId }
                if (track != null) {
                    currentIndex = tracks.indexOf(track)
                    currentTitle = track.title.ifBlank { File(track.path).name.substringBeforeLast('.') }
                    currentArtist = track.artist
                    currentCover = track.cover
                    currentPath = track.path
                }
                // 切歌后重载桌面歌词（仅悬浮窗显示中才读文件）
                if (overlayActive) overlay?.loadTrack(currentPath)
                syncState()
            }

            override fun onPlayerError(error: PlaybackException) {
                syncState()
            }
        })

        // 点击通知打开应用
        contentIntent = PendingIntent.getActivity(
            this, 0,
            packageManager.getLaunchIntentForPackage(packageName),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 创建媒体会话；若上次异常退出导致会话 ID 泄漏（同进程内 ID 重复），
        // 退回使用带时间戳的唯一 ID，避免启动即崩溃的死循环
        mediaSession = try {
            createSession(SESSION_ID)
        } catch (_: IllegalStateException) {
            createSession("$SESSION_ID-${System.currentTimeMillis()}")
        }

        // 关键一步：把会话显式注册到服务。
        // 本应用 UI 全部通过 Intent 控制播放、不使用 MediaController，
        // 而系统框架层控制器（SystemUI / 控制中心 / AOD）是经 MediaSessionManager
        // 直连的，不会触发 Media3 的自动注册（onGetSession 仅在有 Media3 控制器
        // 绑定服务时被调用）。不注册则 Media3 不托管媒体通知与前台状态：
        // 通知栏/锁屏不出现媒体卡片，且 startForegroundService 后无人调用
        // startForeground，进程会被系统以超时异常杀死（会话与控件一并消失）。
        addSession(mediaSession)

        // 通知栏自定义按钮：定时关闭 + 关闭
        updateMediaButtonPreferences()

        // 主线程周期同步进度到静态状态（ExoPlayer 只允许在主线程访问）
        mainHandler.post(progressSync)

        // 注册耳机/蓝牙断开监听（系统受保护广播，无需任何权限）
        val headsetFilter = IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(headsetReceiver, headsetFilter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(headsetReceiver, headsetFilter)
        }
    }

    /** 提前创建通知频道（Media3 默认设置一致：低重要性、不出横幅） */
    private fun ensureChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.bili23_music_channel),
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
    }

    /**
     * 媒体通知提供者：在通知正文（歌手行）后追加定时关闭状态，
     * 例如"ヨルシカ · 定时 15 分后关闭"；未开启定时时保持原样。
     * 每次重建通知都会读取当前剩余分钟，因此倒计时中的分钟变化也会同步。
     */
    private inner class BiliNotificationProvider(context: Context) : MediaNotification.Provider {

        /** 通知内容构建委托给 Media3 默认实现，只覆盖歌手行文案 */
        private val delegate: DefaultMediaNotificationProvider =
            object : DefaultMediaNotificationProvider(
                context,
                { NOTIFICATION_ID },
                CHANNEL_ID,
                R.string.bili23_music_channel
            ) {
                override fun getNotificationContentText(metadata: MediaMetadata): CharSequence? {
                    val artist = metadata.artist?.toString().orEmpty()
                    val minutes = timerMinutes()
                    if (minutes <= 0) return artist
                    val timerText = "定时 $minutes 分后关闭"
                    return if (artist.isBlank()) timerText else "$artist · $timerText"
                }
            }

        override fun createNotification(
            session: MediaSession,
            mediaButtonPreferences: ImmutableList<CommandButton>,
            actionFactory: MediaNotification.ActionFactory,
            onNotificationChanged: MediaNotification.Provider.Callback
        ): MediaNotification = delegate.createNotification(
            session,
            mediaButtonPreferences,
            actionFactory,
            object : MediaNotification.Provider.Callback {
                override fun onNotificationChanged(notification: MediaNotification) {
                    onNotificationChanged.onNotificationChanged(notification)
                    // 封面异步加载完成后，Media3 会按"未播放"重新判定前台状态并撤销前台，
                    // 导致暂停时通知卡被系统清理；这里立刻把服务转回前台
                    keepForeground(notification)
                }
            }
        )

        override fun handleCustomCommand(
            session: MediaSession,
            action: String,
            extras: Bundle
        ): Boolean = delegate.handleCustomCommand(session, action, extras)
    }

    /**
     * 暂停时也让服务保持前台常驻：Media3 默认只在"正在播放"时转前台，
     * 暂停后即退出前台，部分机型（vivo OriginOS 等）会因此移除通知卡、
     * 冻结或回收进程，通知栏 / 控制中心控件随之失效。
     */
    override fun onUpdateNotification(session: MediaSession, startInForegroundRequired: Boolean) {
        super.onUpdateNotification(session, startInForegroundRequired || tracks.isNotEmpty())
    }

    /** 从最近任务划掉应用时保留服务与通知：暂停状态也能继续从通知栏控制 */
    override fun onTaskRemoved(rootIntent: Intent?) {
        if (tracks.isEmpty()) {
            stopPlaybackAndSelf()
        }
        // 有曲目在列表中时不停止服务，只有通知栏"关闭"按钮或定时才会停止
    }

    /** 以媒体通知把服务重新转回前台（暂停保活） */
    private fun keepForeground(notification: MediaNotification) {
        if (tracks.isEmpty()) return
        try {
            ServiceCompat.startForeground(
                this,
                notification.notificationId,
                notification.notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
            )
        } catch (_: Exception) {
            // Android 12+ 后台转前台受限时忽略：通知仍以普通通知保留
        }
    }

    /** 创建媒体会话（含自定义按钮回调） */
    private fun createSession(id: String): MediaSession =
        MediaSession.Builder(this, player)
            .setId(id)
            .setSessionActivity(contentIntent)
            .setCallback(object : MediaSession.Callback {
                /**
                 * 控制器连接时声明自定义命令（定时关闭 / 关闭）对该控制器可用。
                 * 通知栏按钮与系统媒体面板（锁屏 / 控制中心弹窗）的按钮，
                 * 均要求命令在控制器的可用命令集合内，否则按钮会被判定为不可用而不显示。
                 */
                override fun onConnect(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo
                ): MediaSession.ConnectionResult {
                    val availableSessionCommands = MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS
                        .buildUpon()
                        .add(CUSTOM_TIMER)
                        .add(CUSTOM_STOP)
                        .build()
                    return MediaSession.ConnectionResult.AcceptedResultBuilder(session)
                        .setAvailableSessionCommands(availableSessionCommands)
                        .build()
                }

                // 通知栏 / 系统媒体控件点击自定义按钮（定时关闭、关闭）时回调
                override fun onCustomCommand(
                    session: MediaSession,
                    controller: MediaSession.ControllerInfo,
                    customCommand: SessionCommand,
                    args: Bundle
                ): ListenableFuture<SessionResult> {
                    Log.i(TAG, "onCustomCommand: ${customCommand.customAction}")
                    when (customCommand.customAction) {
                        ACTION_TIMER -> cycleTimer()
                        ACTION_STOP -> stopPlaybackAndSelf()
                    }
                    return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
                }
            })
            .build()

    /**
     * 立即进入前台：收到 startForegroundService 指令时同步调用 startForeground()。
     * 系统要求 startForegroundService() 后数秒内必须 startForeground()，否则会以
     * ForegroundServiceDidNotStartInTimeException 杀死进程（会话 / 通知 / 锁屏控件随之消失）；
     * 而 Media3 只会在播放真正开始后才转前台。占位通知与媒体通知同频道同 ID，
     * 播放开始后会被 Media3 的媒体通知自动替换。
     */
    private fun startForegroundImmediately() {
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

    /** 返回给系统媒体控制器 / 锁屏 / AOD 的媒体会话 */
    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 系统以 START_STICKY 重启且无任务（intent 为空）：直接停止，避免留下空闲会话
        if (intent == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        when (intent.action) {
            ACTION_PLAY_PATH -> {
                val path = intent.getStringExtra(EXTRA_PATH) ?: return super.onStartCommand(intent, flags, startId)
                val title = intent.getStringExtra(EXTRA_TITLE) ?: ""
                val artist = intent.getStringExtra(EXTRA_ARTIST) ?: ""
                val cover = intent.getStringExtra(EXTRA_COVER) ?: ""
                // UI 以 startForegroundService 启动：先同步转前台，避免系统前台服务时限崩溃
                startForegroundImmediately()
                // 音频开始播放：停止视频服务，避免音视频同时出声
                MediaArbiter.stopVideo(this)
                addTrack(Track(path, title, artist, cover))
            }

            ACTION_SET_PLAYLIST -> {
                val paths = intent.getStringArrayListExtra(EXTRA_PATHS) ?: emptyList<String>()
                val titles = intent.getStringArrayListExtra(EXTRA_TITLES) ?: emptyList<String>()
                val artists = intent.getStringArrayListExtra(EXTRA_ARTISTS) ?: emptyList<String>()
                val covers = intent.getStringArrayListExtra(EXTRA_COVERS) ?: emptyList<String>()
                val startIndex = intent.getIntExtra(EXTRA_INDEX, 0)
                // UI 以 startForegroundService 启动：先同步转前台，避免系统前台服务时限崩溃
                startForegroundImmediately()
                // 音频开始播放：停止视频服务，避免音视频同时出声
                MediaArbiter.stopVideo(this)
                setPlaylist(paths, titles, artists, covers, startIndex)
            }

            ACTION_SET_MODE -> {
                playMode = intent.getIntExtra(EXTRA_MODE, playMode)
                applyPlayMode()
                refreshNotification()
            }

            ACTION_SEEK -> player.seekTo(intent.getLongExtra(EXTRA_POSITION, 0L))

            ACTION_PLAY -> {
                MediaArbiter.stopVideo(this)
                if (player.mediaItemCount == 0) restoreLastPlaylist() else player.play()
            }
            ACTION_PAUSE -> player.pause()
            ACTION_TOGGLE -> when {
                player.isPlaying -> player.pause()
                player.mediaItemCount == 0 -> restoreLastPlaylist()
                else -> player.play()
            }
            ACTION_PREV -> if (player.mediaItemCount == 0) restoreLastPlaylist() else skipPrev()
            ACTION_NEXT -> if (player.mediaItemCount == 0) restoreLastPlaylist() else skipNext()
            ACTION_TIMER -> cycleTimer()
            ACTION_TOGGLE_OVERLAY -> toggleOverlay()
            ACTION_STOP -> {
                stopPlaybackAndSelf()
                return START_NOT_STICKY
            }
        }
        return super.onStartCommand(intent, flags, startId)
    }

    private fun setPlaylist(
        paths: List<String>,
        titles: List<String>,
        artists: List<String>,
        covers: List<String>,
        startIndex: Int
    ) {
        tracks.clear()
        for (i in paths.indices) {
            tracks.add(
                Track(
                    path = paths[i],
                    title = titles.getOrNull(i) ?: "",
                    artist = artists.getOrNull(i) ?: "",
                    cover = covers.getOrNull(i) ?: ""
                )
            )
        }
        // 列表为空（文件均已失效等）：直接停止服务，避免服务空转
        if (tracks.isEmpty()) {
            stopPlaybackAndSelf()
            return
        }
        val idx = startIndex.coerceIn(0, tracks.size - 1)
        playTrack(idx)
    }

    private fun addTrack(t: Track) {
        val idx = tracks.indexOfFirst { it.path == t.path }
        if (idx >= 0) {
            playTrack(idx)
        } else {
            tracks.add(t)
            playTrack(tracks.size - 1)
        }
    }

    private fun playTrack(index: Int, autoPlay: Boolean = true) {
        if (index !in tracks.indices) return
        currentIndex = index
        val t = tracks[index]
        currentTitle = t.title.ifBlank { File(t.path).name.substringBeforeLast('.') }
        currentArtist = t.artist
        currentCover = t.cover
        currentPath = t.path

        // 将整个播放列表交给播放器维护（mediaId=路径，便于随机/切歌时反查曲目），并定位到当前曲目
        val items = tracks.map { tr ->
            val builder = MediaItem.Builder()
                .setMediaId(tr.path)
                .setUri(Uri.fromFile(File(tr.path)))
            if (tr.cover.isNotEmpty() && File(tr.cover).exists()) {
                builder.setMediaMetadata(
                    MediaMetadata.Builder()
                        .setTitle(tr.title.ifBlank { File(tr.path).name.substringBeforeLast('.') })
                        .setArtist(tr.artist)
                        .setArtworkUri(Uri.fromFile(File(tr.cover)))
                        .build()
                )
            }
            builder.build()
        }
        player.setMediaItems(items, index, 0L)
        applyPlayMode()
        player.prepare()
        player.playWhenReady = autoPlay
        syncState()
    }

    /**
     * 服务已被通知栏"关闭"停止后，再次收到播放指令（App 内点播放等）时，
     * 用上次播放列表快照恢复曲目并继续播放
     */
    private fun restoreLastPlaylist() {
        if (lastPaths.isEmpty()) return
        tracks.clear()
        lastPaths.indices.forEach { i ->
            tracks.add(
                Track(
                    path = lastPaths[i],
                    title = lastTitles.getOrElse(i) { "" },
                    artist = lastArtists.getOrElse(i) { "" },
                    cover = lastCovers.getOrElse(i) { "" }
                )
            )
        }
        playTrack(lastIndex.coerceIn(0, tracks.size - 1))
    }

    /** 根据播放模式设置播放器的 循环/随机（系统媒体控件上一首/下一首随之正确工作） */
    private fun applyPlayMode() {
        player.shuffleModeEnabled = playMode == MODE_SHUFFLE
        player.repeatMode = when (playMode) {
            MODE_LOOP_ONE -> Player.REPEAT_MODE_ONE
            MODE_LOOP_LIST, MODE_SHUFFLE -> Player.REPEAT_MODE_ALL
            else -> Player.REPEAT_MODE_OFF
        }
    }

    private fun skipNext() {
        if (tracks.isEmpty()) return
        when {
            playMode == MODE_SHUFFLE -> {
                // 随机：手动切歌时随机挑一首不同的（与旧版一致）
                if (tracks.size > 1) {
                    var next = Random.nextInt(tracks.size)
                    while (next == currentIndex) next = Random.nextInt(tracks.size)
                    player.seekToDefaultPosition(next)
                } else {
                    player.seekTo(0)
                    player.play()
                }
            }

            player.hasNextMediaItem() -> player.seekToNextMediaItem()

            else -> player.seekToDefaultPosition(0) // 顺序播放到末尾：回到第一首
        }
        syncState()
    }

    private fun skipPrev() {
        if (tracks.isEmpty()) return
        if (player.currentPosition > 3000) {
            player.seekTo(0)
        } else if (player.hasPreviousMediaItem()) {
            player.seekToPreviousMediaItem()
        } else {
            player.seekToDefaultPosition(tracks.size - 1) // 第一首：回到最后一首
        }
        syncState()
    }

    /** 同步播放状态到静态字段（供 UI 轮询） */
    private fun syncState() {
        currentPosition = player.currentPosition
        currentDuration = player.duration.coerceAtLeast(0L)
        isPlaying = player.isPlaying
        timerRemainingMs = timerMillis
        refreshPlaylistSnapshot()
    }

    /** 同步播放列表快照（列表结构变化时才重建标题，避免每次轮询都做字符串处理） */
    private var snapshotSize = -1
    private fun refreshPlaylistSnapshot() {
        if (snapshotSize != tracks.size) {
            snapshotSize = tracks.size
            playlistTitles = tracks.map { it.title.ifBlank { File(it.path).name.substringBeforeLast('.') } }
            playlistPaths = tracks.map { it.path }
        }
        currentListIndex = currentIndex.coerceAtLeast(0)
    }

    /** 通知栏自定义按钮：定时关闭 + 关闭（Media3 默认通知会渲染并转发为自定义命令） */
    private fun updateMediaButtonPreferences() {
        mediaSession.setMediaButtonPreferences(
            ImmutableList.of(
                CommandButton.Builder()
                    .setSessionCommand(CUSTOM_TIMER)
                    .setDisplayName(timerLabel())
                    .setIconResId(R.drawable.ic_timer)
                    .setEnabled(true)
                    .build(),
                CommandButton.Builder()
                    .setSessionCommand(CUSTOM_STOP)
                    .setDisplayName("关闭")
                    .setIconResId(R.drawable.ic_close)
                    .setEnabled(true)
                    .build()
            )
        )
    }

    override fun onDestroy() {
        serviceActive = false
        mainHandler.removeCallbacks(progressSync)
        mainHandler.removeCallbacks(fgsGuard)
        // 释放本曲音量均衡器，避免占用音频会话
        gainEq?.release()
        gainEq = null
        // 移除桌面歌词悬浮窗，避免窗口泄漏
        overlay?.hide()
        overlay = null
        overlayActive = false
        try {
            unregisterReceiver(headsetReceiver)
        } catch (_: Exception) {
        }
        pausedForHeadset = false
        // 必须先释放播放器与会话：MediaSessionService.onDestroy() 只释放 binder，
        // 不会释放 MediaSession；泄漏的会话 ID 会导致下次启动报
        // "Session ID must be unique" 直接崩溃
        player.release()
        if (::mediaSession.isInitialized) {
            mediaSession.release()
        }
        super.onDestroy()
    }
}
