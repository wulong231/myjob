package com.bili23.android.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Binder
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media.app.NotificationCompat.MediaStyle
import androidx.media3.common.AudioAttributes
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import com.bili23.android.MainActivity
import com.bili23.android.R
import java.io.File
import kotlin.random.Random

/**
 * 音频播放前台服务：
 * 1. 持有 ExoPlayer 保证息屏/切后台仍继续播放
 * 2. 通过 MediaSession 提供通知栏播放/暂停/上一首/下一首控制
 * 3. 支持播放列表 + 播放模式（顺序/列表循环/单曲循环/随机）
 * 4. 拖拽进度（seek）与封面显示
 */
class MusicPlaybackService : Service() {

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
    }

    private data class Track(
        val path: String,
        val title: String,
        val artist: String,
        val cover: String
    )

    private lateinit var player: ExoPlayer
    private lateinit var mediaSession: MediaSessionCompat
    private lateinit var notificationManager: NotificationManager
    private val tracks = mutableListOf<Track>()
    private var currentIndex = -1

    /** 主线程定时同步播放进度（ExoPlayer 只允许在主线程访问），并周期性刷新通知进度 */
    private val mainHandler = Handler(Looper.getMainLooper())
    private var notifyTicks = 0
    /** 定时关闭剩余毫秒（0=关闭），循环切换 15/30/60 分钟 */
    private var timerMillis: Long = 0L
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
                }
            }
            // 约每 2.4 秒刷新一次通知栏进度/时间（后台运行也能看到进度）
            notifyTicks++
            if (notifyTicks % 6 == 0) {
                try {
                    updateNotification()
                } catch (_: Exception) {
                }
            }
            mainHandler.postDelayed(this, 400)
        }
    }

    /** 循环切换定时：关闭 → 15 → 30 → 60 分钟 → 关闭 */
    fun cycleTimer() {
        timerMillis = when {
            timerMillis <= 0 -> 15 * 60_000L
            timerMillis <= 15 * 60_000L -> 30 * 60_000L
            timerMillis <= 30 * 60_000L -> 60 * 60_000L
            else -> 0L
        }
        updateNotification()
    }

    private fun timerLabel(): String = when {
        timerMillis <= 0 -> "定时关闭"
        else -> "定时 ${(timerMillis / 60_000).coerceAtLeast(1)} 分后关闭"
    }

    /** 停止播放并退出服务（定时到时/停止按钮共用） */
    private fun stopPlaybackAndSelf() {
        player.stop()
        player.clearMediaItems()
        tracks.clear()
        currentIndex = -1
        currentTitle = ""
        currentArtist = ""
        currentCover = ""
        currentPath = ""
        timerMillis = 0
        syncState()
        serviceActive = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private val binder = LocalBinder()

    inner class LocalBinder : Binder() {
        fun getService(): MusicPlaybackService = this@MusicPlaybackService
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        serviceActive = true
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        createChannel()

        player = ExoPlayer.Builder(this).build()
        // 音频焦点：播放时请求焦点，其他 App 播放时自动暂停/降音，恢复后自动续播
        player.setAudioAttributes(AudioAttributes.DEFAULT, true)
        player.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                syncState()
                if (playbackState == Player.STATE_ENDED) {
                    onTrackEnded()
                }
                updateNotification()
            }

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                syncState()
                updateNotification()
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                syncState()
                updateNotification()
            }

            override fun onPlayerError(error: PlaybackException) {
                syncState()
                updateNotification()
            }
        })

        // 主线程周期同步进度到静态状态（ExoPlayer 只允许在主线程访问）
        mainHandler.post(progressSync)

        mediaSession = MediaSessionCompat(this, "BiliMusic").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onPlay() {
                    player.play()
                    updateNotification()
                }

                override fun onPause() {
                    player.pause()
                    updateNotification()
                }

                override fun onSkipToNext() {
                    skipNext()
                }

                override fun onSkipToPrevious() {
                    skipPrev()
                }

                override fun onSeekTo(pos: Long) {
                    player.seekTo(pos)
                }
            })
            isActive = true
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PLAY_PATH -> {
                val path = intent.getStringExtra(EXTRA_PATH) ?: return START_NOT_STICKY
                val title = intent.getStringExtra(EXTRA_TITLE) ?: ""
                val artist = intent.getStringExtra(EXTRA_ARTIST) ?: ""
                val cover = intent.getStringExtra(EXTRA_COVER) ?: ""
                addTrack(Track(path, title, artist, cover))
            }

            ACTION_SET_PLAYLIST -> {
                val paths = intent.getStringArrayListExtra(EXTRA_PATHS) ?: emptyList<String>()
                val titles = intent.getStringArrayListExtra(EXTRA_TITLES) ?: emptyList<String>()
                val artists = intent.getStringArrayListExtra(EXTRA_ARTISTS) ?: emptyList<String>()
                val covers = intent.getStringArrayListExtra(EXTRA_COVERS) ?: emptyList<String>()
                val startIndex = intent.getIntExtra(EXTRA_INDEX, 0)
                setPlaylist(paths, titles, artists, covers, startIndex)
            }

            ACTION_SET_MODE -> {
                playMode = intent.getIntExtra(EXTRA_MODE, playMode)
                updateNotification()
            }

            ACTION_SEEK -> player.seekTo(intent.getLongExtra(EXTRA_POSITION, 0L))

            ACTION_PLAY -> player.play()
            ACTION_PAUSE -> player.pause()
            ACTION_TOGGLE -> if (player.isPlaying) player.pause() else player.play()
            ACTION_PREV -> skipPrev()
            ACTION_NEXT -> skipNext()
            ACTION_TIMER -> cycleTimer()
            ACTION_STOP -> {
                stopPlaybackAndSelf()
                return START_NOT_STICKY
            }
        }
        updateNotification()
        return START_STICKY
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
        if (tracks.isEmpty()) return
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

        val builder = MediaItem.Builder().setUri(Uri.fromFile(File(t.path)))
        if (t.cover.isNotEmpty() && File(t.cover).exists()) {
            builder.setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(currentTitle)
                    .setArtist(currentArtist)
                    .setArtworkUri(Uri.fromFile(File(t.cover)))
                    .build()
            )
        }
        player.setMediaItem(builder.build())
        player.prepare()
        player.playWhenReady = autoPlay
        updateNotification()
    }

    /** 一首播放结束后按播放模式自动切歌 */
    private fun onTrackEnded() {
        when (playMode) {
            MODE_LOOP_ONE -> {
                player.seekTo(0)
                player.play()
            }

            MODE_SHUFFLE -> {
                if (tracks.size > 1) {
                    var next = Random.nextInt(tracks.size)
                    while (next == currentIndex) next = Random.nextInt(tracks.size)
                    playTrack(next)
                } else {
                    player.seekTo(0)
                    player.play()
                }
            }

            MODE_ORDER -> {
                if (currentIndex < tracks.size - 1) {
                    playTrack(currentIndex + 1)
                } else {
                    player.seekTo(0)
                    player.pause()
                }
            }

            else -> { // MODE_LOOP_LIST
                playTrack((currentIndex + 1) % tracks.size)
            }
        }
    }

    private fun skipNext() {
        if (tracks.isEmpty()) return
        when (playMode) {
            MODE_SHUFFLE -> {
                if (tracks.size > 1) {
                    var next = Random.nextInt(tracks.size)
                    while (next == currentIndex) next = Random.nextInt(tracks.size)
                    playTrack(next)
                } else {
                    player.seekTo(0)
                    player.play()
                }
            }

            MODE_ORDER -> {
                if (currentIndex < tracks.size - 1) playTrack(currentIndex + 1)
                else playTrack(0)
            }

            else -> playTrack((currentIndex + 1) % tracks.size)
        }
    }

    private fun skipPrev() {
        if (tracks.isEmpty()) return
        if (player.currentPosition > 3000) {
            player.seekTo(0)
            return
        }
        playTrack(if (currentIndex <= 0) tracks.size - 1 else currentIndex - 1)
    }

    /** 同步播放状态到静态字段（供 UI 轮询） */
    private fun syncState() {
        currentPosition = player.currentPosition
        currentDuration = player.duration.coerceAtLeast(0L)
        isPlaying = player.isPlaying
    }

    /** 构建并显示前台通知（含播放控制） */
    private fun updateNotification() {
        val sessionIntent = packageManager.getLaunchIntentForPackage(packageName)
        val contentIntent = PendingIntent.getActivity(
            this, 0, sessionIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 播放/暂停
        val playPauseIntent = Intent(this, MusicPlaybackService::class.java).apply {
            action = if (player.isPlaying) ACTION_PAUSE else ACTION_PLAY
        }
        val playPausePi = PendingIntent.getService(
            this, 1, playPauseIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 上一首
        val prevIntent = Intent(this, MusicPlaybackService::class.java).apply { action = ACTION_PREV }
        val prevPi = PendingIntent.getService(
            this, 2, prevIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 下一首
        val nextIntent = Intent(this, MusicPlaybackService::class.java).apply { action = ACTION_NEXT }
        val nextPi = PendingIntent.getService(
            this, 3, nextIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 停止（后台运行时也可停止播放并退出服务）
        val stopIntent = Intent(this, MusicPlaybackService::class.java).apply { action = ACTION_STOP }
        val stopPi = PendingIntent.getService(
            this, 4, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 定时关闭（循环切换 15/30/60 分钟）
        val timerIntent = Intent(this, MusicPlaybackService::class.java).apply { action = ACTION_TIMER }
        val timerPi = PendingIntent.getService(
            this, 5, timerIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 封面图（若存在）
        var coverBitmap: android.graphics.Bitmap? = null
        if (currentCover.isNotEmpty()) {
            try {
                val f = File(currentCover)
                if (f.exists()) coverBitmap = BitmapFactory.decodeFile(f.absolutePath)
            } catch (_: Exception) {
                coverBitmap = null
            }
        }

        // MediaSession 状态
        val state = PlaybackStateCompat.Builder()
            .setActions(
                PlaybackStateCompat.ACTION_PLAY or
                        PlaybackStateCompat.ACTION_PAUSE or
                        PlaybackStateCompat.ACTION_PLAY_PAUSE or
                        PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                        PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                        PlaybackStateCompat.ACTION_SEEK_TO
            )
            .setState(
                if (player.isPlaying) PlaybackStateCompat.STATE_PLAYING
                else PlaybackStateCompat.STATE_PAUSED,
                player.currentPosition,
                1f
            )
            .build()
        mediaSession.setPlaybackState(state)

        val metadataBuilder = MediaMetadataCompat.Builder()
            .putString(MediaMetadataCompat.METADATA_KEY_TITLE, currentTitle)
            .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, currentArtist)
            .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, player.duration)
        if (coverBitmap != null) {
            metadataBuilder.putBitmap(MediaMetadataCompat.METADATA_KEY_ALBUM_ART, coverBitmap)
        } else if (currentCover.isNotEmpty() && File(currentCover).exists()) {
            metadataBuilder.putString(
                MediaMetadataCompat.METADATA_KEY_ALBUM_ART_URI,
                Uri.fromFile(File(currentCover)).toString()
            )
        }
        mediaSession.setMetadata(metadataBuilder.build())

        val timerLabel = timerLabel()
        val contentText = buildString {
            if (currentArtist.isNotBlank()) append(currentArtist)
            if (timerLabel != "定时关闭") {
                if (isNotEmpty()) append(" · ")
                append(timerLabel)
            }
            if (isEmpty()) append("正在播放")
        }

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(currentTitle.ifBlank { "Bili 音乐" })
            .setContentText(contentText)
            .setContentIntent(contentIntent)
            .setOngoing(player.isPlaying)
            .setOnlyAlertOnce(true)
            .addAction(R.drawable.ic_prev, "上一首", prevPi)
            .addAction(
                if (player.isPlaying) R.drawable.ic_pause else R.drawable.ic_play,
                if (player.isPlaying) "暂停" else "播放",
                playPausePi
            )
            .addAction(R.drawable.ic_next, "下一首", nextPi)
            .addAction(R.drawable.ic_timer, timerLabel, timerPi)
            .addAction(R.drawable.ic_close, "关闭", stopPi)
            .setStyle(
                MediaStyle()
                    .setMediaSession(mediaSession.sessionToken)
                    .setShowActionsInCompactView(0, 1, 2)
                    .setShowCancelButton(true)
            )
        if (coverBitmap != null) {
            builder.setLargeIcon(coverBitmap)
        }

        startForeground(NOTIFICATION_ID, builder.build())
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "音乐播放",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "后台音乐播放控制"
            setShowBadge(false)
        }
        notificationManager.createNotificationChannel(channel)
    }

    override fun onDestroy() {
        serviceActive = false
        mainHandler.removeCallbacks(progressSync)
        player.release()
        mediaSession.release()
        super.onDestroy()
    }
}
