package com.bili23.android.ui

import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.view.Window
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import com.bili23.android.data.Settings

private val LightColors = lightColorScheme(
    primary = Color(0xFF00AEEC),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFBDEAFF),
    onPrimaryContainer = Color(0xFF003648),
    secondary = Color(0xFF4A616D),
    background = Color(0xFFF8F9FB),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFE7E9EC)
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF67CFFF),
    onPrimary = Color(0xFF003648),
    primaryContainer = Color(0xFF004E66),
    onPrimaryContainer = Color(0xFFBDEAFF),
    secondary = Color(0xFFB1CAD6),
    background = Color(0xFF121417),
    surface = Color(0xFF1A1D20),
    surfaceVariant = Color(0xFF303337)
)

/** 非 Composable：按应用主题判断当前是否为深色 */
fun isDarkThemeNow(context: Context): Boolean {
    return when (Settings.themeModeState.intValue) {
        1 -> false
        2 -> true
        else -> {
            val uiMode = context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
            uiMode == Configuration.UI_MODE_NIGHT_YES
        }
    }
}

/**
 * 非 Composable：把状态栏/导航栏图标深浅同步到当前主题。
 * 深色 → 图标浅色（白）；浅色 → 图标深色（黑）。
 */
fun applySystemBarTheme(window: Window?, darkTheme: Boolean) {
    if (window == null) return
    val view = window.decorView
    WindowCompat.getInsetsController(window, view).apply {
        isAppearanceLightStatusBars = !darkTheme
        isAppearanceLightNavigationBars = !darkTheme
    }
}

/** 应用主题：跟随系统 / 浅色 / 深色（切换后立即生效） */
@Composable
fun Bili23Theme(content: @Composable () -> Unit) {
    val darkTheme = when (Settings.themeModeState.intValue) {
        1 -> false
        2 -> true
        else -> isSystemInDarkTheme()
    }

    // 同步系统状态栏/导航栏图标深浅，适配手动主题（主题切换时立即刷新）
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            applySystemBarTheme((view.context as? Activity)?.window, darkTheme)
        }
    }

    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content
    )
}
