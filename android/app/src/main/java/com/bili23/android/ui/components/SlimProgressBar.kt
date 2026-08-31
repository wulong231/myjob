package com.bili23.android.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.drag
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

/**
 * 细条动画进度条：圆角细轨道 + 平滑填充动画 + 圆点滑块。
 * 支持点击 / 拖拽 seek；拖拽过程中通过回调同步显示位置。
 */
@Composable
fun SlimProgressBar(
    valueMs: Long,
    maxMs: Long,
    onSeek: (Long) -> Unit,
    modifier: Modifier = Modifier,
    onDragStateChange: (Boolean) -> Unit = {},
    onDragValueChange: (Long) -> Unit = {},
    activeColor: Color = MaterialTheme.colorScheme.primary,
    trackColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    thumbColor: Color = MaterialTheme.colorScheme.primary
) {
    val max = maxMs.coerceAtLeast(1L)
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableFloatStateOf(0f) }
    val fraction by animateFloatAsState(
        targetValue = if (dragging) dragFraction
        else (valueMs.toFloat() / max).coerceIn(0f, 1f),
        animationSpec = tween(durationMillis = 180),
        label = "slimProgress"
    )
    val thumbSize = 14.dp
    val trackHeight = 4.dp
    // 记录进度条实际宽度（像素），用于定位圆点滑块
    var barWidthPx by remember { mutableFloatStateOf(0f) }

    Box(
        modifier = modifier
            .height(24.dp)
            .onSizeChanged { barWidthPx = it.width.toFloat() }
            .pointerInput(max) {
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false) ?: return@awaitEachGesture
                    var dragActive = false
                    // 超过触摸滑动阈值进入拖拽；纯点击时 drag 直接返回
                    drag(down.id) { change ->
                        if (!dragActive) {
                            dragActive = true
                            dragging = true
                            dragFraction = (down.position.x / size.width.toFloat()).coerceIn(0f, 1f)
                            onDragStateChange(true)
                            onDragValueChange((dragFraction * max.toFloat()).toLong())
                        }
                        dragFraction = (change.position.x / size.width.toFloat()).coerceIn(0f, 1f)
                        change.consume()
                        onDragValueChange((dragFraction * max.toFloat()).toLong())
                    }
                    if (dragActive) {
                        // 拖拽结束：定位到当前位置
                        onSeek((dragFraction * max.toFloat()).toLong().coerceIn(0L, max))
                        dragging = false
                        onDragStateChange(false)
                    } else {
                        // 点击：直接定位
                        onSeek((down.position.x / size.width.toFloat() * max.toFloat()).toLong().coerceIn(0L, max))
                    }
                }
            }
    ) {
        // 轨道
        Box(
            Modifier
                .fillMaxWidth()
                .align(Alignment.CenterStart)
                .height(trackHeight)
                .clip(RoundedCornerShape(2.dp))
                .background(trackColor)
        )
        // 已播放填充（平滑动画）
        Box(
            Modifier
                .fillMaxWidth(fraction)
                .align(Alignment.CenterStart)
                .height(trackHeight)
                .clip(RoundedCornerShape(2.dp))
                .background(activeColor)
        )
        // 圆点滑块（垂直居中，仅水平偏移）
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .offset { IntOffset((barWidthPx * fraction - thumbSize.toPx() / 2).roundToInt(), 0) }
                .size(thumbSize)
                .clip(CircleShape)
                .background(thumbColor)
        )
    }
}
