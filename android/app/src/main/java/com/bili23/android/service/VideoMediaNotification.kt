package com.bili23.android.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.media.app.NotificationCompat.MediaStyle
import androidx.media3.exoplayer.ExoPlayer
import com.bili23.android.R

/**
 * 视频播放后台通知系统：
 * 1. 播放视频时在通知栏显示 播放/暂停/上一集/下一集/停止/定时关闭 按钮
 * 2. 通过广播回调控制当前播放器（后台也能控制）
 * 3. 定时关闭：循环切换 15/30/60 分钟，到时暂停并退出播放
 */
object VideoMediaController {
    const val ACTION_PLAY_PAUSE = "com.bili23.android.video.PLAY_PAUSE"
    const val ACTION_NEXT = "com.bili23.android.video.NEXT"
    const val ACTION_PREV = "com.bili23.android.video.PREV"
    const val ACTION_STOP = "com.bili23.android.video.STOP"
    const val ACTION_TIMER = "com.bili23.android.video.TIMER"

    @Volatile
    var player: ExoPlayer? = null
    var onNext: (() -> Unit)? = null
    var onPrev: (() -> Unit)? = null
    var onStop: (() -> Unit)? = null
    @Volatile
    var title: String = "视频播放"
    @Volatile
    var subtitle: String = ""

    private val handler = Handler(Looper.getMainLooper())

    // ---- 定时关闭（0=关闭；循环切换 15/30/60 分钟）----
    @Volatile
    var timerMillis: Long = 0L
        private set
    private val timerRunnable = object : Runnable {
        override fun run() {
            if (timerMillis > 0) {
                timerMillis -= 1000
                if (timerMillis <= 0) {
                    timerMillis = 0
                    // 到时：暂停并退出播放
                    player?.pause()
                    onStop?.invoke()
                    VideoMediaNotification.cancel()
                } else {
                    handler.postDelayed(this, 1000)
                }
            }
        }
    }

    /** 循环切换定时：关闭 → 15 分钟 → 30 分钟 → 60 分钟 → 关闭 */
    fun cycleTimer() {
        handler.removeCallbacks(timerRunnable)
        timerMillis = when {
            timerMillis <= 0 -> 15 * 60_000L
            timerMillis <= 15 * 60_000L -> 30 * 60_000L
            timerMillis <= 30 * 60_000L -> 60 * 60_000L
            else -> 0L
        }
        if (timerMillis > 0) handler.postDelayed(timerRunnable, 1000)
        VideoMediaNotification.update()
    }

    fun timerLabel(): String = when {
        timerMillis <= 0 -> "定时关闭"
        else -> "定时 ${(timerMillis / 60_000)} 分后关闭"
    }

    /** 清空控制引用（离开播放页时调用） */
    fun reset() {
        handler.removeCallbacks(timerRunnable)
        timerMillis = 0
        player = null
        onNext = null
        onPrev = null
        onStop = null
    }
}

/** 视频通知广播接收器：处理通知栏按钮（主线程执行，可安全操作 ExoPlayer） */
class VideoNotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            VideoMediaController.ACTION_PLAY_PAUSE -> {
                val p = VideoMediaController.player
                if (p != null) {
                    if (p.isPlaying) p.pause() else p.play()
                }
            }
            VideoMediaController.ACTION_NEXT -> VideoMediaController.onNext?.invoke()
            VideoMediaController.ACTION_PREV -> VideoMediaController.onPrev?.invoke()
            VideoMediaController.ACTION_STOP -> VideoMediaController.onStop?.invoke()
            VideoMediaController.ACTION_TIMER -> VideoMediaController.cycleTimer()
        }
        VideoMediaNotification.update()
    }
}

/** 视频播放通知：构建并显示/更新/取消 */
object VideoMediaNotification {
    private const val CHANNEL_ID = "bili23_video"
    private const val NOTIFICATION_ID = 2
    private var appContext: Context? = null

    fun init(context: Context) {
        val c = context.applicationContext
        appContext = c
        val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "视频播放", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            }
        )
    }

    fun update() {
        val c = appContext ?: return
        val isPlaying = VideoMediaController.player?.isPlaying == true

        fun pi(action: String, requestCode: Int): PendingIntent {
            val i = Intent(c, VideoNotificationReceiver::class.java).setAction(action)
            return PendingIntent.getBroadcast(
                c, requestCode, i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }

        val openIntent = c.packageManager.getLaunchIntentForPackage(c.packageName)
        val contentPi = PendingIntent.getActivity(
            c, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val playPauseIcon = if (isPlaying) R.drawable.ic_pause else R.drawable.ic_play
        val playPauseLabel = if (isPlaying) "暂停" else "播放"

        val timerText = VideoMediaController.timerLabel()
        val subtitle = VideoMediaController.subtitle
        val contentText = buildString {
            if (subtitle.isNotBlank()) append(subtitle)
            if (timerText != "定时关闭") {
                if (isNotEmpty()) append(" · ")
                append(timerText)
            }
            if (isEmpty()) append("正在播放")
        }

        val builder = NotificationCompat.Builder(c, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(VideoMediaController.title.ifBlank { "视频播放" })
            .setContentText(contentText)
            .setContentIntent(contentPi)
            .setOngoing(isPlaying)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(R.drawable.ic_prev, "上一集", pi(VideoMediaController.ACTION_PREV, 1))
            .addAction(playPauseIcon, playPauseLabel, pi(VideoMediaController.ACTION_PLAY_PAUSE, 2))
            .addAction(R.drawable.ic_next, "下一集", pi(VideoMediaController.ACTION_NEXT, 3))
            .addAction(R.drawable.ic_timer, timerText, pi(VideoMediaController.ACTION_TIMER, 4))
            .addAction(R.drawable.ic_close, "关闭", pi(VideoMediaController.ACTION_STOP, 5))
            .setStyle(
                MediaStyle().setShowActionsInCompactView(0, 1, 2)
            )

        val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, builder.build())
    }

    fun cancel() {
        appContext?.let {
            (it.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancel(NOTIFICATION_ID)
        }
    }
}
