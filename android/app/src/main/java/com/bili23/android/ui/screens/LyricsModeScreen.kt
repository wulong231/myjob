package com.bili23.android.ui.screens

import android.content.Context
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import com.bili23.android.data.LyricLine
import com.bili23.android.data.Settings
import com.bili23.android.data.currentLyricIndex
import com.bili23.android.data.parseLrc
import com.bili23.android.service.MusicPlaybackService
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.min

/** 当前实时时间 HH:mm */
private fun clockHHmm(): String =
    java.time.LocalTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))

/**
 * 歌词模式（横屏全屏）：
 * 背景 = 虚化封面（动态流动）/ 纯黑（可切换并记忆）；左侧旋转唱片封面（正圆）；
 * 右侧实时时钟 + 滚动歌词高亮（点击歌词行可跳转到该句）；底部播放方式 / 上一首 / 播放暂停 / 下一首 / 定时关闭 / 背景切换；
 * 左划调出播放列表面板（点击切歌），右划或点 × 关闭。
 */
@Composable
fun LyricsModeScreen(onExit: () -> Unit) {
    val context = LocalContext.current

    // ---- 服务状态（轮询同步，与音频页一致） ----
    var position by remember { mutableLongStateOf(0L) }
    var isPlaying by remember { mutableStateOf(false) }
    var playMode by remember { mutableIntStateOf(MusicPlaybackService.playMode) }
    var timerMs by remember { mutableLongStateOf(0L) }
    var path by remember { mutableStateOf(MusicPlaybackService.currentPath) }
    var title by remember { mutableStateOf(MusicPlaybackService.currentTitle) }
    var artist by remember { mutableStateOf(MusicPlaybackService.currentArtist) }
    var cover by remember { mutableStateOf(MusicPlaybackService.currentCover) }

    // ---- 歌词与本地状态 ----
    var lyrics by remember { mutableStateOf<List<LyricLine>>(emptyList()) }
    var translations by remember { mutableStateOf<List<LyricLine>>(emptyList()) }
    var lyricOffset by remember { mutableLongStateOf(0L) }
    var blackBg by remember { mutableStateOf(Settings.lyricsModeBlackBg) }
    /** 实时时钟（HH:mm，每秒刷新） */
    var clockText by remember { mutableStateOf(clockHHmm()) }
    // 播放列表（左划调出）
    var listTitles by remember { mutableStateOf<List<String>>(emptyList()) }
    var listPaths by remember { mutableStateOf<List<String>>(emptyList()) }
    var listIndex by remember { mutableIntStateOf(0) }
    var showList by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        while (true) {
            clockText = clockHHmm()
            // 对齐整秒刷新，避免显示跳秒
            delay(1000L - System.currentTimeMillis() % 1000L)
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
            position = MusicPlaybackService.currentPosition
            isPlaying = MusicPlaybackService.isPlaying
            playMode = MusicPlaybackService.playMode
            timerMs = MusicPlaybackService.timerRemainingMs
            listTitles = MusicPlaybackService.playlistTitles
            listPaths = MusicPlaybackService.playlistPaths
            listIndex = MusicPlaybackService.currentListIndex
            val p = MusicPlaybackService.currentPath
            if (p != path) {
                path = p
                cover = MusicPlaybackService.currentCover
                title = MusicPlaybackService.currentTitle
                artist = MusicPlaybackService.currentArtist
            }
            delay(250)
        }
    }

    // 曲目变化时加载歌词（与音频页共用解析逻辑）
    LaunchedEffect(path) {
        if (path.isEmpty()) {
            lyrics = emptyList()
            translations = emptyList()
            lyricOffset = 0L
            return@LaunchedEffect
        }
        lyrics = parseLrc(Settings.getLyric(path))
        translations = parseLrc(Settings.getLyricTranslation(path))
        lyricOffset = Settings.getLyricOffset(path)
    }

    BackHandler { onExit() }

    /** 向播放服务发送指令（服务未运行时忽略） */
    fun svc(action: String, block: Intent.() -> Unit = {}) {
        if (!MusicPlaybackService.serviceActive) return
        context.startService(
            Intent(context, MusicPlaybackService::class.java).apply {
                this.action = action
                block()
            }
        )
    }

    val currentIdx = currentLyricIndex(lyrics, position, lyricOffset)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            // 左划调出播放列表；列表打开时右划关闭
            .pointerInput(showList) {
                var total = 0f
                detectHorizontalDragGestures(
                    onDragEnd = { total = 0f },
                    onDragCancel = { total = 0f },
                    onHorizontalDrag = { _, drag ->
                        total += drag
                        if (!showList && total < -70f) {
                            showList = true
                            total = 0f
                        } else if (showList && total > 70f) {
                            showList = false
                            total = 0f
                        }
                    }
                )
            }
    ) {
        // ---- 背景：虚化封面 + 暗色蒙层，或纯黑 ----
        if (!blackBg) BlurredCoverBackground(cover)

        Column(modifier = Modifier.fillMaxSize()) {
            Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
                // ---- 左：旋转唱片封面（正圆） ----
                BoxWithConstraints(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(0.42f)
                        .padding(20.dp),
                    contentAlignment = Alignment.Center
                ) {
                    // 取可用宽高的较小值作为正方形边长，保证唱片是正圆且完整居中
                    val side = min(maxWidth.value, maxHeight.value)
                    RotatingDisc(
                        coverPath = cover,
                        isPlaying = isPlaying,
                        modifier = Modifier.size(side.dp)
                    )
                }

                // ---- 右：实时时间 + 歌词 ----
                Column(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(0.58f)
                        .padding(top = 14.dp, end = 20.dp, bottom = 4.dp)
                ) {
                    // 最大一块：实时时间（HH:mm）
                    Text(
                        text = clockText,
                        fontSize = 68.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.White
                    )
                    Spacer(Modifier.height(2.dp))
                    // 歌名 · 歌手
                    Text(
                        text = if (title.isBlank()) "暂无播放" else
                            (if (artist.isBlank()) title else "$title · $artist"),
                        fontSize = 15.sp,
                        color = Color.White.copy(alpha = 0.85f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(bottom = 6.dp)
                    )
                    // 滚动歌词（当前行高亮 + 翻译）
                    if (lyrics.isEmpty()) {
                        Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                            Text("♪ 暂无歌词 ♪", color = Color.White.copy(alpha = 0.5f), fontSize = 16.sp)
                        }
                    } else {
                        LyricLines(
                            lyrics = lyrics,
                            translations = translations,
                            currentIndex = currentIdx,
                            onLineClick = { timeMs ->
                                // 点击歌词行跳转：歌词时间 + 偏移 = 实际播放位置
                                svc(MusicPlaybackService.ACTION_SEEK) {
                                    putExtra(MusicPlaybackService.EXTRA_POSITION, timeMs + lyricOffset)
                                }
                            },
                            modifier = Modifier.weight(1f).fillMaxWidth()
                        )
                    }
                }
            }

            // ---- 底部控制条 ----
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // 播放方式
                val (modeIcon, modeLabel) = when (playMode) {
                    MusicPlaybackService.MODE_LOOP_LIST -> Icons.Filled.Repeat to "列表循环"
                    MusicPlaybackService.MODE_LOOP_ONE -> Icons.Filled.RepeatOne to "单曲循环"
                    MusicPlaybackService.MODE_SHUFFLE -> Icons.Filled.Shuffle to "随机播放"
                    else -> Icons.Filled.Repeat to "顺序播放"
                }
                LabeledIconButton(modeIcon, modeLabel) {
                    val next = (playMode + 1) % 4
                    playMode = next
                    MusicPlaybackService.playMode = next
                    svc(MusicPlaybackService.ACTION_SET_MODE) {
                        putExtra(MusicPlaybackService.EXTRA_MODE, next)
                    }
                }
                Spacer(Modifier.width(10.dp))

                LabeledIconButton(
                    Icons.Filled.SkipPrevious, "上一首", iconSize = 34.dp
                ) { svc(MusicPlaybackService.ACTION_PREV) }
                LabeledIconButton(
                    if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    if (isPlaying) "暂停" else "播放",
                    iconSize = 40.dp
                ) { svc(MusicPlaybackService.ACTION_TOGGLE) }
                LabeledIconButton(
                    Icons.Filled.SkipNext, "下一首", iconSize = 34.dp
                ) { svc(MusicPlaybackService.ACTION_NEXT) }
                Spacer(Modifier.width(10.dp))

                // 定时关闭（点击累加 15 分钟，最长 60 分钟，满后再点取消）
                LabeledIconButton(
                    Icons.Filled.Timer,
                    if (timerMs > 0) "定时 ${((timerMs + 59_999L) / 60_000L).coerceAtLeast(1)} 分" else "定时关闭",
                    tint = if (timerMs > 0) MaterialTheme.colorScheme.primary else Color.White
                ) { svc(MusicPlaybackService.ACTION_TIMER) }
                Spacer(Modifier.width(10.dp))

                // 背景切换：虚化封面 / 纯黑底（记忆选择）
                LabeledIconButton(
                    if (blackBg) Icons.Filled.DarkMode else Icons.Filled.Image,
                    if (blackBg) "纯黑底" else "虚化封面"
                ) {
                    blackBg = !blackBg
                    Settings.lyricsModeBlackBg = blackBg
                }
            }
        }

        // ---- 播放列表面板（左划调出） ----
        AnimatedVisibility(
            visible = showList,
            enter = slideInHorizontally(initialOffsetX = { it }) + fadeIn(),
            exit = slideOutHorizontally(targetOffsetX = { it }) + fadeOut(),
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .fillMaxHeight()
                .fillMaxWidth(0.52f)
        ) {
            PlaylistPanel(
                titles = listTitles,
                currentIndex = listIndex,
                onPick = { idx ->
                    listPaths.getOrNull(idx)?.let { p ->
                        svc(MusicPlaybackService.ACTION_PLAY_PATH) {
                            putExtra(MusicPlaybackService.EXTRA_PATH, p)
                        }
                    }
                    showList = false
                }
            )
        }

        // ---- 退出按钮（右上角） ----
        IconButton(
            onClick = onExit,
            modifier = Modifier.align(Alignment.TopEnd).padding(6.dp)
        ) {
            Icon(Icons.Filled.Close, contentDescription = "退出歌词模式", tint = Color.White.copy(alpha = 0.85f))
        }
    }
}

/** 播放列表面板：当前曲目高亮并自动滚动到可见位置，点击切歌 */
@Composable
private fun PlaylistPanel(
    titles: List<String>,
    currentIndex: Int,
    onPick: (Int) -> Unit
) {
    val listState = rememberLazyListState()
    LaunchedEffect(currentIndex, titles.size) {
        if (currentIndex in titles.indices) listState.animateScrollToItem(currentIndex)
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.8f))
            .padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "播放列表（${titles.size}）",
                color = Color.White,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold
            )
        }
        if (titles.isEmpty()) {
            Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("列表为空", color = Color.White.copy(alpha = 0.5f), fontSize = 13.sp)
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(bottom = 8.dp)
            ) {
                itemsIndexed(titles) { idx, t ->
                    val active = idx == currentIndex
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .clickable { onPick(idx) }
                            .padding(horizontal = 8.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = if (active) "▸" else "${idx + 1}",
                            color = if (active) MaterialTheme.colorScheme.primary
                            else Color.White.copy(alpha = 0.5f),
                            fontSize = 12.sp,
                            modifier = Modifier.width(26.dp)
                        )
                        Text(
                            text = t,
                            color = if (active) MaterialTheme.colorScheme.primary else Color.White,
                            fontSize = 14.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
            }
        }
    }
}

/** 背景：把封面解码成极小位图后放大（双线性）得到虚化效果，再压一层暗色蒙层保证文字可读 */
@Composable
private fun BlurredCoverBackground(coverPath: String) {
    val context = LocalContext.current
    var bitmap by remember { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(coverPath) {
        bitmap = null
        if (coverPath.isEmpty()) return@LaunchedEffect
        bitmap = withContext(Dispatchers.IO) {
            runCatching {
                val request = ImageRequest.Builder(context)
                    .data(File(coverPath))
                    .size(10)   // 极小解码尺寸 → 放大后模糊度更高
                    .allowHardware(false)
                    .build()
                val result = context.imageLoader.execute(request)
                (result as? SuccessResult)?.drawable?.toBitmap()?.asImageBitmap()
            }.getOrNull()
        }
    }

    bitmap?.let {
        // 动态流动：缓慢缩放 + 双向平移循环，营造背景呼吸/流动感
        val transition = rememberInfiniteTransition(label = "bgFlow")
        val scale by transition.animateFloat(
            initialValue = 1.30f,
            targetValue = 1.55f,
            animationSpec = infiniteRepeatable(tween(18000, easing = LinearEasing), RepeatMode.Reverse),
            label = "bgScale"
        )
        val offsetX by transition.animateFloat(
            initialValue = -90f,
            targetValue = 90f,
            animationSpec = infiniteRepeatable(tween(23000, easing = LinearEasing), RepeatMode.Reverse),
            label = "bgOffsetX"
        )
        val offsetY by transition.animateFloat(
            initialValue = -60f,
            targetValue = 60f,
            animationSpec = infiniteRepeatable(tween(16000, easing = LinearEasing), RepeatMode.Reverse),
            label = "bgOffsetY"
        )
        Image(
            bitmap = it,
            contentDescription = null,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                    translationX = offsetX * density
                    translationY = offsetY * density
                },
            contentScale = ContentScale.Crop,
            filterQuality = FilterQuality.Low,
            alpha = 0.65f
        )
    }
    Box(modifier = Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f)))
}

/** 旋转唱片封面：正方形 + 正圆裁切；播放时缓慢转动（12°/秒），暂停时停在当前角度 */
@Composable
private fun RotatingDisc(coverPath: String, isPlaying: Boolean, modifier: Modifier = Modifier) {
    var rotation by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(isPlaying) {
        if (!isPlaying) return@LaunchedEffect
        var last = withFrameNanos { it }
        while (true) {
            val now = withFrameNanos { it }
            rotation = (rotation + (now - last) / 1_000_000_000f * 12f) % 360f
            last = now
        }
    }

    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clip(CircleShape)
                .background(Color.White.copy(alpha = 0.10f))
                .padding(12.dp),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape)
                    .background(Color(0xFF101014)),
                contentAlignment = Alignment.Center
            ) {
                if (coverPath.isNotEmpty()) {
                    AsyncImage(
                        model = File(coverPath),
                        contentDescription = null,
                        modifier = Modifier
                            .fillMaxSize()
                            .graphicsLayer { rotationZ = rotation }
                            .clip(CircleShape),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    Icon(
                        Icons.Filled.LibraryMusic,
                        contentDescription = null,
                        tint = Color.White.copy(alpha = 0.6f),
                        modifier = Modifier.size(64.dp)
                    )
                }
            }
        }
    }
}

/** 滚动歌词列表：当前行高亮放大，下方显示对应翻译，自动滚动到当前行 */
@Composable
private fun LyricLines(
    lyrics: List<LyricLine>,
    translations: List<LyricLine>,
    currentIndex: Int,
    onLineClick: (Long) -> Unit,
    modifier: Modifier = Modifier
) {
    val listState = rememberLazyListState()
    LaunchedEffect(currentIndex) {
        if (currentIndex >= 0) {
            listState.animateScrollToItem(currentIndex.coerceAtMost(lyrics.lastIndex))
        }
    }
    LazyColumn(
        state = listState,
        modifier = modifier,
        contentPadding = PaddingValues(vertical = 60.dp)
    ) {
        itemsIndexed(lyrics) { index, line ->
            val active = index == currentIndex
            Text(
                text = line.text,
                fontSize = if (active) 21.sp else 15.sp,
                fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                color = if (active) MaterialTheme.colorScheme.primary else Color.White.copy(alpha = 0.55f),
                textAlign = TextAlign.Start,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(6.dp))
                    // 点击歌词行 → 跳到该行对应的播放位置
                    .clickable { onLineClick(line.timeMs) }
                    .padding(vertical = if (active) 4.dp else 3.dp)
            )
            if (active) {
                translations.getOrNull(index)?.text?.takeIf { it.isNotBlank() }?.let { tl ->
                    Text(
                        text = tl,
                        fontSize = 14.sp,
                        color = Color.White.copy(alpha = 0.75f),
                        modifier = Modifier
                            .clip(RoundedCornerShape(6.dp))
                            .clickable { onLineClick(line.timeMs) }
                            .padding(bottom = 4.dp)
                    )
                }
            }
        }
    }
}

/** 底部统一按钮：固定宽度的 图标+文字 竖排，保证所有按钮图标严格对齐 */
@Composable
private fun LabeledIconButton(
    icon: ImageVector,
    label: String,
    tint: Color = Color.White,
    iconSize: Dp = 28.dp,
    onClick: () -> Unit
) {
    Column(
        modifier = Modifier.width(78.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // 图标容器固定高度，不同图标大小也能保持同一水平线
        Box(modifier = Modifier.height(46.dp), contentAlignment = Alignment.Center) {
            IconButton(onClick = onClick) {
                Icon(icon, contentDescription = label, tint = tint, modifier = Modifier.size(iconSize))
            }
        }
        Text(
            label,
            fontSize = 11.sp,
            color = tint.copy(alpha = 0.85f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center
        )
    }
}