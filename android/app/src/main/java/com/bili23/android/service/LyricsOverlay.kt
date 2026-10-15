package com.bili23.android.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings as AndroidSettings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import com.bili23.android.data.LyricLine
import com.bili23.android.data.Settings
import com.bili23.android.data.currentLineProgress
import com.bili23.android.data.currentLyricIndex
import com.bili23.android.data.parseLrc
import kotlin.math.abs

/**
 * 桌面歌词悬浮窗（参照桌面版 DesktopLyrics）：
 * 悬浮于其他应用上层显示当前歌词行（卡拉OK渐变填充 + 双语翻译），支持拖动与关闭。
 * 由 MusicPlaybackService 托管：随播放进度刷新，播放停止时隐藏。
 */
class LyricsOverlay(private val context: Context, private val onClose: () -> Unit) {

    private val windowManager =
        context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var view: LyricOverlayView? = null
    private lateinit var params: WindowManager.LayoutParams

    /** 歌词数据（按曲目加载一次，避免每帧读文件） */
    private var lines: List<LyricLine> = emptyList()
    private var translations: List<LyricLine> = emptyList()
    private var offsetMs: Long = 0L

    /** 位置同步基准：服务每 400ms 同步一次，视图内按时间插值实现平滑卡拉OK */
    private var basePosMs: Long = 0L
    private var baseUptime: Long = 0L
    private var playing = false

    /** 屏幕是否点亮（息屏时不做无谓刷新） */
    private var screenOn = true

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            screenOn = intent.action == Intent.ACTION_SCREEN_ON
            view?.updateTicker()
        }
    }

    val isShowing: Boolean get() = view != null

    /** 是否已获得"显示在其他应用上层"权限 */
    fun canShow(): Boolean = AndroidSettings.canDrawOverlays(context)

    /** 切换曲目：读取并解析该曲目的歌词 / 翻译 / 偏移（仅在曲目变化时读文件） */
    fun loadTrack(path: String) {
        lines = emptyList()
        translations = emptyList()
        offsetMs = 0L
        if (path.isNotEmpty()) {
            lines = parseLrc(Settings.getLyric(path))
            translations = parseLrc(Settings.getLyricTranslation(path))
            offsetMs = Settings.getLyricOffset(path)
        }
        view?.apply {
            computeTextWidth()
            relayout()
            invalidate()
        }
    }

    /** 服务同步播放进度（每 400ms 一次） */
    fun syncPosition(posMs: Long, isPlaying: Boolean) {
        basePosMs = posMs
        baseUptime = SystemClock.elapsedRealtime()
        playing = isPlaying
        view?.updateTicker()
    }

    fun show() {
        if (view != null) return
        if (!canShow()) return

        val v = LyricOverlayView(context)
        val dm = context.resources.displayMetrics
        v.computeTextWidth()
        val width = v.windowWidth
        val height = v.windowHeight
        params = WindowManager.LayoutParams(
            width,
            height,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            // 使用上次保存的位置，否则默认放在屏幕下方居中
            x = Settings.desktopLyricsX.takeIf { it >= 0 }
                ?: ((dm.widthPixels - width) / 2).coerceAtLeast(0)
            y = Settings.desktopLyricsY.takeIf { it >= 0 }
                ?: (dm.heightPixels * 0.72f).toInt()
        }
        params.x = clampX(params.x)
        params.y = clampY(params.y)

        runCatching { windowManager.addView(v, params) }
            .onSuccess {
                view = v
                screenOn = true
                context.registerReceiver(
                    screenReceiver,
                    IntentFilter().apply {
                        addAction(Intent.ACTION_SCREEN_ON)
                        addAction(Intent.ACTION_SCREEN_OFF)
                    }
                )
                v.updateTicker()
            }
    }

    fun hide() {
        val v = view ?: return
        view = null
        runCatching { windowManager.removeView(v) }
        runCatching { context.unregisterReceiver(screenReceiver) }
        mainHandler.removeCallbacksAndMessages(null)
    }

    private fun clampX(x: Int): Int {
        val dm = context.resources.displayMetrics
        val w = if (::params.isInitialized) params.width else 0
        return x.coerceIn(0, (dm.widthPixels - w).coerceAtLeast(0))
    }

    private fun clampY(y: Int): Int {
        val dm = context.resources.displayMetrics
        val h = if (::params.isInitialized) params.height else 0
        return y.coerceIn(0, (dm.heightPixels - h).coerceAtLeast(0))
    }

    /** 当前播放位置（播放中按时间插值，避免 400ms 一跳） */
    private fun currentPosMs(): Long =
        if (playing) basePosMs + (SystemClock.elapsedRealtime() - baseUptime) else basePosMs

    /**
     * 悬浮歌词视图：自绘卡拉OK歌词（未演唱暗色 / 已演唱彩色渐变裁剪）、
     * 翻译行、左上角关闭按钮，支持整条拖动。
     */
    private inner class LyricOverlayView(ctx: Context) : View(ctx) {

        private val density = resources.displayMetrics.density
        private val scaledDensity = resources.displayMetrics.scaledDensity

        private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xCC101018.toInt() }
        private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 1.5f * density
            color = 0x33FFFFFF
        }
        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = Paint.Align.CENTER
            typeface = Typeface.DEFAULT_BOLD
            setShadowLayer(6f, 0f, 2f, 0xE6000000.toInt())
        }
        private val transPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = Paint.Align.CENTER
            setShadowLayer(6f, 0f, 2f, 0xE6000000.toInt())
        }
        private val closePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = Paint.Align.CENTER
            typeface = Typeface.DEFAULT_BOLD
            color = 0x99FFFFFF.toInt()
        }
        private val bgRect = RectF()
        private val closeRect = RectF()

        /** 主歌词基准字号（sp→px） */
        private val baseTextSize = 20f * scaledDensity

        /** 窗口与内容尺寸（按歌词最长行计算一次，保持同曲稳定） */
        var windowWidth = (240 * density).toInt()
            private set
        var windowHeight = (46 * density).toInt()
            private set

        /** 闭合裁剪用的临时测量宽度 */
        private var lineTextWidth = 0f

        /** 拖动状态 */
        private var downRawX = 0f
        private var downRawY = 0f
        private var startX = 0
        private var startY = 0
        private var dragging = false
        private val touchSlop = 6f * density

        private val ticker = object : Runnable {
            override fun run() {
                if (view !== this@LyricOverlayView || !playing || !screenOn) return
                invalidate()
                postDelayed(this, 33)
            }
        }

        fun updateTicker() {
            removeCallbacks(ticker)
            if (playing && screenOn && view === this) post(ticker)
        }

        /** 按歌词最长行计算窗口宽度（限制在屏幕内），并根据是否有翻译决定高度 */
        fun computeTextWidth() {
            val dm = resources.displayMetrics
            val cap = dm.widthPixels - (24 * density).toInt()
            textPaint.textSize = baseTextSize
            var maxW = 0f
            for (l in lines) maxW = maxOf(maxW, textPaint.measureText(l.text))
            for (l in translations) maxW = maxOf(maxW, transPaint.also { it.textSize = baseTextSize * 0.72f }.measureText(l.text))
            windowWidth = (maxW + 56 * density).toInt()
                .coerceIn((200 * density).toInt(), cap)
            windowHeight = ((if (translations.isNotEmpty()) 74 else 46) * density).toInt()
        }

        fun relayout() {
            if (view !== this || !::params.isInitialized) return
            params.width = windowWidth
            params.height = windowHeight
            params.x = clampX(params.x)
            params.y = clampY(params.y)
            runCatching { windowManager.updateViewLayout(this, params) }
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val w = width.toFloat()
            val h = height.toFloat()
            bgRect.set(1f, 1f, w - 1f, h - 1f)
            canvas.drawRoundRect(bgRect, 14f * density, 14f * density, bgPaint)
            canvas.drawRoundRect(bgRect, 14f * density, 14f * density, borderPaint)

            // 关闭按钮（右上角 ×）
            closePaint.textSize = 16f * scaledDensity
            closeRect.set(w - 34 * density, 0f, w, 30 * density)
            canvas.drawText("×", closeRect.centerX(), 21 * density, closePaint)

            // 当前行文本
            val pos = currentPosMs()
            val idx = currentLyricIndex(lines, pos, offsetMs)
            val text = lines.getOrNull(idx)?.text ?: "♪ 暂无歌词 ♪"

            textPaint.textSize = baseTextSize
            transPaint.textSize = baseTextSize * 0.72f
            var textW = textPaint.measureText(text)
            val availW = w - 28 * density
            // 过长歌词自动缩小字号，保证整行可见
            if (textW > availW && textW > 0f) {
                val scale = availW / textW
                textPaint.textSize = (baseTextSize * scale).coerceAtLeast(10f * scaledDensity)
                textW = textPaint.measureText(text)
            }
            lineTextWidth = textW

            val hasTrans = idx in lines.indices &&
                translations.getOrNull(idx)?.text?.isNotBlank() == true
            val mainBaseline = if (hasTrans) 32 * density else h / 2f + textPaint.textSize / 3f

            // 未演唱部分：半透明白
            textPaint.color = 0x99FFFFFF.toInt()
            canvas.drawText(text, w / 2f, mainBaseline, textPaint)

            // 已演唱部分：彩色渐变裁剪填充（卡拉OK）
            val progress = currentLineProgress(lines, idx, pos, offsetMs)
            if (progress > 0f && idx in lines.indices) {
                val left = (w - textW) / 2f
                canvas.save()
                canvas.clipRect(left, 0f, left + textW * progress, h)
                val karaoke = Paint(textPaint).apply {
                    shader = LinearGradient(
                        left, 0f, left + textW, 0f,
                        intArrayOf(0xFFFF6B9D.toInt(), 0xFFFFD166.toInt(), 0xFF4ECDC4.toInt()),
                        null, Shader.TileMode.CLAMP
                    )
                }
                canvas.drawText(text, w / 2f, mainBaseline, karaoke)
                canvas.restore()
            }

            // 翻译行
            if (hasTrans) {
                transPaint.color = 0xCCBFD8FF.toInt()
                canvas.drawText(
                    translations[idx].text, w / 2f,
                    h - 14 * density, transPaint
                )
            }
        }

        override fun onTouchEvent(event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downRawX = event.rawX
                    downRawY = event.rawY
                    startX = params.x
                    startY = params.y
                    dragging = false
                    return true
                }

                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downRawX
                    val dy = event.rawY - downRawY
                    if (!dragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) dragging = true
                    if (dragging) {
                        params.x = clampX((startX + dx).toInt())
                        params.y = clampY((startY + dy).toInt())
                        runCatching { windowManager.updateViewLayout(this, params) }
                    }
                    return true
                }

                MotionEvent.ACTION_UP -> {
                    if (dragging) {
                        // 记录位置，下次打开恢复
                        Settings.desktopLyricsX = params.x
                        Settings.desktopLyricsY = params.y
                    } else if (closeRect.contains(event.x, event.y)) {
                        onClose()
                    }
                    return true
                }
            }
            return super.onTouchEvent(event)
        }
    }
}