package com.bili23.android

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.bili23.android.data.Settings
import com.bili23.android.ui.Bili23Theme
import com.bili23.android.ui.screens.LyricsModeScreen

/**
 * 歌词模式（横屏全屏）：
 * 虚化封面 / 纯黑底可切换，旋转唱片封面 + 大字进度时间 + 滚动歌词 + 播放/定时/播放方式控制。
 * 由音频播放页的"歌词模式"按钮进入，退出后自动恢复竖屏。
 */
class LyricsModeActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        Settings.init(applicationContext)
        // 歌词模式不休眠：进入本页面期间保持屏幕常亮（退出后自动失效）
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        // 沉浸全屏：隐藏状态栏与导航栏（下滑可临时唤出）
        WindowCompat.getInsetsController(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        setContent {
            Bili23Theme {
                LyricsModeScreen(onExit = { finish() })
            }
        }
    }
}