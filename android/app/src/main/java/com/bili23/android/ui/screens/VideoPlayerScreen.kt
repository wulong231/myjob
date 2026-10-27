package com.bili23.android.ui.screens

import android.content.Intent
import android.content.res.Configuration
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import com.bili23.android.data.PlayUrl
import com.bili23.android.data.Settings
import com.bili23.android.data.qualityName
import com.bili23.android.service.VideoPlaybackService
import com.bili23.android.ui.AppViewModel
import com.bili23.android.ui.applySystemBarTheme
import com.bili23.android.ui.isDarkThemeNow
import java.io.File
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 毫秒 → mm:ss（视频进度显示） */
private fun formatVideoMs(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0L)
    return "%d:%02d".format(total / 60, total % 60)
}

/**
 * 视频播放页（界面层）：
 * 播放内核由 [VideoPlaybackService]（Media3 MediaSessionService）持有，本页只做
 * 渲染（PlayerView 绑定服务播放器）、控制（发送 Intent 指令）与状态展示（轮询服务状态）。
 * 这样息屏 / 后台可继续播放，且能接入系统媒体会话（锁屏 / 控制中心 / AOD / 蓝牙媒体键）。
 */
@androidx.annotation.OptIn(UnstableApi::class)
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoPlayerScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val context = LocalContext.current
    val currentPlay by vm.currentPlay.collectAsState()
    val localPath by vm.localPlayPath.collectAsState()
    val videoQueue by vm.videoQueue.collectAsState()
    val tasks by vm.downloadManager.tasks.collectAsState()
    val play = currentPlay?.third ?: PlayUrl()
    val isLocal = localPath != null
    val configuration = LocalConfiguration.current
    val isLandscape = configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    // 平板（最小宽度 ≥ 600dp，如小米平板5Pro 2K 横屏使用）：横屏不自动全屏，仅手动全屏
    val isTablet = configuration.smallestScreenWidthDp >= 600

    // 本地全部视频（作为单视频播放时的隐式队列；若从某收藏夹进入则只展示该夹内视频）
    val playlistFilter by vm.videoPlaylistFilter.collectAsState()
    val allLocalVideos = remember(tasks, playlistFilter) {
        tasks.filter {
            it.type == com.bili23.android.data.DownloadTask.TYPE_VIDEO &&
                    it.status == com.bili23.android.data.DownloadTask.STATUS_COMPLETED &&
                    File(it.filePath).exists()
        }.map { it.filePath }.let { list ->
            if (playlistFilter != null)
                list.filter { Settings.isInPlaylist(Settings.PLAYLIST_VIDEO, playlistFilter!!, it) }
            else list
        }
    }
    // 交给服务播放的本地队列：已有播放队列则用它，否则用当前展示的全部本地视频（与旧版一致）
    val localQueue = if (!isLocal) emptyList()
    else if (videoQueue.size > 1) videoQueue
    else allLocalVideos

    // 在线播放：进入播放页时若详情页尚未加载，重新拉取（用于展示选集列表）
    val videoInfo by vm.videoInfo.collectAsState()
    val onlineEpisodes = if (!isLocal) (videoInfo?.episodes ?: emptyList()) else emptyList()
    LaunchedEffect(currentPlay?.first, isLocal) {
        val bvid = currentPlay?.first
        if (!isLocal && bvid != null && videoInfo?.bvid != bvid) vm.loadVideoDetail(bvid)
    }

    // 本次播放内容标识：与服务当前内容一致时只绑定界面，不重新开始播放
    val desiredKey = if (isLocal) "local:${localPath ?: ""}"
    else "online:${currentPlay?.first ?: ""}:${currentPlay?.second ?: 0L}"

    // ---- 服务状态（轮询同步） ----
    var playMode by remember { mutableIntStateOf(VideoPlaybackService.playMode) }
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }
    var isPlaying by remember { mutableStateOf(false) }
    var buffering by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf("") }
    var curIndex by remember { mutableIntStateOf(0) }
    var queueCount by remember { mutableIntStateOf(1) }
    var hasNav by remember { mutableStateOf(false) }
    var curLocalPath by remember { mutableStateOf("") }
    var curCid by remember { mutableLongStateOf(0L) }
    var curTitle by remember { mutableStateOf("") }
    /** PlayerView 绑定的播放器实例（服务创建后通过轮询/启动等待取回） */
    var uiPlayer by remember { mutableStateOf<ExoPlayer?>(null) }

    var manualFullscreen by remember { mutableStateOf(false) }
    val isFullscreen = (!isTablet && isLandscape) || manualFullscreen

    // 画面适配：false=适应屏幕(等比)，true=裁切铺满
    var cropFill by remember { mutableStateOf(false) }

    // 全屏控制条自动隐藏
    var controlsVisible by remember { mutableStateOf(true) }
    val scope = rememberCoroutineScope()
    var hideJob by remember { mutableStateOf<Job?>(null) }

    // 收藏状态（仅本地视频）：以服务当前播放的本地文件为准
    var favState by remember(curLocalPath) { mutableStateOf(Settings.isFavorite(curLocalPath)) }

    /** 向视频服务发送指令（仅用于控制指令；开始播放由 startPlayback 处理） */
    fun cmd(action: String, block: Intent.() -> Unit = {}) {
        context.startService(
            Intent(context, VideoPlaybackService::class.java).apply {
                this.action = action
                block()
            }
        )
    }

    /** 发起播放：本地提交队列 + 起始序号；在线提交 bvid/cid 与已取到的播放地址 */
    fun startPlayback() {
        if (isLocal) {
            val path = localPath ?: return
            // 队列为空（如已清理下载记录、只剩磁盘文件）时退化为单曲播放，保证一定能播
            val queue = if (localQueue.contains(path)) localQueue else listOf(path)
            val index = queue.indexOf(path).coerceAtLeast(0)
            cmd(VideoPlaybackService.ACTION_PLAY_LOCAL) {
                putStringArrayListExtra(VideoPlaybackService.EXTRA_PATHS, ArrayList(queue))
                putExtra(VideoPlaybackService.EXTRA_INDEX, index)
            }
        } else {
            val bvid = currentPlay?.first ?: return
            val cid = currentPlay?.second ?: return
            cmd(VideoPlaybackService.ACTION_PLAY_ONLINE) {
                putExtra(VideoPlaybackService.EXTRA_BVID, bvid)
                putExtra(VideoPlaybackService.EXTRA_CID, cid)
                putExtra(VideoPlaybackService.EXTRA_TITLE, videoInfo?.title ?: "")
                putExtra(VideoPlaybackService.EXTRA_COVER, videoInfo?.coverUrl ?: "")
                putExtra(VideoPlaybackService.EXTRA_QUALITY, play.quality)
                putExtra(VideoPlaybackService.EXTRA_VIDEO_URL, play.videoUrl)
                putExtra(VideoPlaybackService.EXTRA_AUDIO_URL, play.audioUrl)
            }
        }
    }

    /** 退出播放页：停止播放并返回（息屏 / Home 键离开则继续后台播放） */
    fun exitPlayer() {
        // 先解绑 PlayerView，避免播放器销毁后视图仍引用
        uiPlayer = null
        if (VideoPlaybackService.serviceActive) cmd(VideoPlaybackService.ACTION_STOP)
        navController.popBackStack()
    }

    /** 在线切换分P：拉取地址后交给播放页重新发起播放 */
    fun playOnlineEpisode(cid: Long) {
        if (cid <= 0) return
        val bvid = currentPlay?.first ?: return
        val q = play.quality
        scope.launch {
            val url = vm.fetchPlayUrl(bvid, cid, q)
            if (url.videoUrl.isNotEmpty()) vm.setCurrentPlay(bvid, cid, url)
        }
    }

    fun cycleMode() {
        val next = (playMode + 1) % 4
        playMode = next
        Settings.videoPlayMode = next
        if (VideoPlaybackService.serviceActive) {
            cmd(VideoPlaybackService.ACTION_SET_MODE) {
                putExtra(VideoPlaybackService.EXTRA_MODE, next)
            }
        }
    }

    fun pokeControls() {
        controlsVisible = true
        if (!isFullscreen) return
        hideJob?.cancel()
        hideJob = scope.launch {
            delay(3000)
            if (VideoPlaybackService.isPlaying) controlsVisible = false
        }
    }

    fun toggleControls() {
        if (controlsVisible) {
            hideJob?.cancel()
            controlsVisible = false
        } else {
            pokeControls()
        }
    }

    // 进入播放页：若服务未在播放同一内容则发起播放，并把服务播放器绑定给 PlayerView
    LaunchedEffect(desiredKey, localQueue.size) {
        if (isLocal && localPath == null) return@LaunchedEffect
        val bound = VideoPlaybackService.serviceActive &&
                VideoPlaybackService.currentMediaKey == desiredKey
        if (!bound) startPlayback()
        var tries = 0
        while (uiPlayer == null && tries < 60) {
            uiPlayer = VideoPlaybackService.playerForUi
            if (uiPlayer == null) {
                delay(50)
                tries++
            }
        }
    }

    // 轮询服务状态（进度 / 播放态 / 队列位置 / 定时 / 错误）
    LaunchedEffect(desiredKey) {
        while (true) {
            playMode = if (VideoPlaybackService.serviceActive) VideoPlaybackService.playMode
            else Settings.videoPlayMode
            position = VideoPlaybackService.position
            duration = VideoPlaybackService.duration
            isPlaying = VideoPlaybackService.isPlaying
            buffering = VideoPlaybackService.isBuffering
            errorMsg = VideoPlaybackService.lastError
            curIndex = VideoPlaybackService.currentIndex
            queueCount = VideoPlaybackService.queueCount
            hasNav = VideoPlaybackService.hasQueueNav
            curLocalPath = if (VideoPlaybackService.isLocal) VideoPlaybackService.currentLocalPath else ""
            curCid = VideoPlaybackService.currentCid
            curTitle = VideoPlaybackService.currentTitle
            if (uiPlayer == null) uiPlayer = VideoPlaybackService.playerForUi
            delay(500)
        }
    }

    // 全屏进入/退出时重置控制条显隐
    LaunchedEffect(isFullscreen) {
        if (isFullscreen) pokeControls() else {
            hideJob?.cancel()
            controlsVisible = true
        }
    }

    // 全屏/横屏：隐藏/显示系统栏，并强制横屏（退出时强制恢复竖屏）
    DisposableEffect(isFullscreen) {
        // 全屏时禁用全局左划菜单
        com.bili23.android.FullscreenController.isFullscreen = isFullscreen
        val activity = context as? android.app.Activity
        val window = activity?.window
        val view = window?.decorView
        val controller = window?.let {
            androidx.core.view.WindowCompat.getInsetsController(it, view ?: return@let null)
        }
        if (isFullscreen) {
            activity?.requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            controller?.systemBarsBehavior =
                androidx.core.view.WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller?.hide(androidx.core.view.WindowInsetsCompat.Type.systemBars())
        } else {
            // 平板不强制竖屏（横屏使用），恢复系统默认方向；手机仍强制竖屏
            activity?.requestedOrientation =
                if (isTablet) android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                else android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            controller?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            applySystemBarTheme(window, isDarkThemeNow(context))
        }
        onDispose {
            com.bili23.android.FullscreenController.isFullscreen = false
            activity?.requestedOrientation =
                if (isTablet) android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                else android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            controller?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            applySystemBarTheme(window, isDarkThemeNow(context))
        }
    }

    /** 退出全屏：取消手动全屏并恢复方向（手机强制竖屏；平板恢复系统默认方向） */
    fun exitFullscreen() {
        manualFullscreen = false
        (context as? android.app.Activity)?.requestedOrientation =
            if (isTablet) android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            else android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
    }

    // 全屏/横屏时拦截返回：先退回竖屏播放界面；竖屏时返回=退出播放（停止后台播放）
    BackHandler(enabled = isFullscreen) { exitFullscreen() }
    BackHandler(enabled = !isFullscreen) { exitPlayer() }

    Scaffold(
        topBar = {
            if (!isFullscreen) {
                TopAppBar(
                    title = {
                        Text(
                            when {
                                hasNav -> "${curIndex + 1}/$queueCount"
                                isLocal -> "本地视频"
                                else -> curTitle.ifBlank { "播放" }
                            },
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = { exitPlayer() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    actions = {
                        if (isLocal) {
                            // 收藏切换
                            IconButton(onClick = {
                                if (curLocalPath.isEmpty()) return@IconButton
                                val newFav = !favState
                                favState = newFav
                                Settings.setFavorite(curLocalPath, newFav)
                            }) {
                                Icon(
                                    if (favState) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                                    contentDescription = "收藏",
                                    tint = if (favState) MaterialTheme.colorScheme.error
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            IconButton(onClick = {
                                val path = curLocalPath.ifBlank { localPath ?: return@IconButton }
                                exitPlayer()
                                vm.deleteVideoFile(path)
                            }) {
                                Icon(Icons.Filled.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
                            }
                        }
                        IconButton(onClick = {
                            if (isFullscreen) exitFullscreen() else manualFullscreen = true
                        }) {
                            Icon(
                                if (isFullscreen) Icons.Filled.FullscreenExit else Icons.Filled.Fullscreen,
                                contentDescription = if (isFullscreen) "退出全屏" else "全屏"
                            )
                        }
                    }
                )
            }
        }
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .then(
                        if (isFullscreen) Modifier
                        else Modifier.padding(padding)
                    )
            ) {
                // 视频画面：全屏/横屏铺满，否则保持原始高度（点击切换控制条 / 双击播放暂停）
                Box(
                    modifier = (if (isFullscreen) {
                        Modifier
                            .fillMaxWidth()
                            .weight(1f)
                    } else {
                        Modifier
                            .fillMaxWidth()
                    })
                        .background(Color.Black)
                        .pointerInput(Unit) {
                            detectTapGestures(
                                onTap = { if (isFullscreen) toggleControls() },
                                onDoubleTap = {
                                    if (VideoPlaybackService.serviceActive) {
                                        cmd(VideoPlaybackService.ACTION_TOGGLE)
                                    }
                                }
                            )
                        }
                ) {
                    AndroidView(
                        factory = { ctx ->
                            PlayerView(ctx).apply {
                                useController = false
                                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                                keepScreenOn = true
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        update = { view ->
                            val p = uiPlayer
                            if (p != null && view.player !== p) view.player = p
                            // 裁切铺满 / 适应屏幕
                            view.resizeMode = if (cropFill)
                                AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                            else AspectRatioFrameLayout.RESIZE_MODE_FIT
                        },
                        // 视图离开时解绑，避免引用已释放的播放器
                        onRelease = { it.player = null }
                    )
                    // 缓冲 / 拉取播放地址时显示加载圈
                    if (buffering && errorMsg.isBlank()) {
                        CircularProgressIndicator(
                            modifier = Modifier.align(Alignment.Center).size(36.dp),
                            color = Color.White
                        )
                    }
                    // 播放失败：提示并可原地重试
                    if (errorMsg.isNotBlank()) {
                        Column(
                            modifier = Modifier.align(Alignment.Center),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(errorMsg, color = Color.White, style = MaterialTheme.typography.bodyMedium)
                            TextButton(onClick = { startPlayback() }) { Text("重试") }
                        }
                    }
                }

                // 非全屏：控制条 + 信息区
                if (!isFullscreen) {
                    VideoControlsBar(
                        isPlaying = isPlaying,
                        position = position,
                        duration = duration,
                        playMode = playMode,
                        showQueueNav = hasNav,
                        overlay = false,
                        cropFill = cropFill,
                        onToggleResize = { cropFill = !cropFill },
                        onPlayPause = { cmd(VideoPlaybackService.ACTION_TOGGLE) },
                        onPrev = { cmd(VideoPlaybackService.ACTION_PREV) },
                        onNext = { cmd(VideoPlaybackService.ACTION_NEXT) },
                        onSeek = { pos ->
                            cmd(VideoPlaybackService.ACTION_SEEK) {
                                putExtra(VideoPlaybackService.EXTRA_POSITION, pos)
                            }
                        },
                        onCycleMode = { cycleMode() }
                    )
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(16.dp)
                    ) {
                        if (isLocal) {
                            Text(
                                text = (curLocalPath.ifBlank { localPath ?: "" }).substringAfterLast('/'),
                                style = MaterialTheme.typography.titleMedium,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis
                            )
                            // 已下载视频列表（点击切换播放）
                            if (allLocalVideos.isNotEmpty()) {
                                Spacer(Modifier.height(12.dp))
                                Text(
                                    "已下载视频（${allLocalVideos.size}）",
                                    style = MaterialTheme.typography.titleSmall
                                )
                                Spacer(Modifier.height(4.dp))
                                allLocalVideos.forEachIndexed { idx, p ->
                                    val isCurrent = p == curLocalPath
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(
                                                if (isCurrent) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                                                else MaterialTheme.colorScheme.surfaceVariant
                                            )
                                            .clickable { vm.setVideoQueue(allLocalVideos, idx) }
                                            .padding(horizontal = 10.dp, vertical = 8.dp),
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Icon(
                                            if (isCurrent) Icons.Filled.PlayArrow else Icons.Filled.Movie,
                                            contentDescription = null,
                                            modifier = Modifier.size(18.dp),
                                            tint = if (isCurrent) MaterialTheme.colorScheme.primary
                                            else MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Text(
                                            text = p.substringAfterLast('/'),
                                            style = MaterialTheme.typography.bodyMedium,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            color = if (isCurrent) MaterialTheme.colorScheme.primary
                                            else MaterialTheme.colorScheme.onSurface
                                        )
                                    }
                                    Spacer(Modifier.height(4.dp))
                                }
                            }
                        } else {
                            Text(
                                text = curTitle.ifBlank { videoInfo?.title ?: "" },
                                style = MaterialTheme.typography.titleMedium,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                text = "画质：${qualityName(play.quality)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            // 在线选集列表（点击切换分P）
                            if (onlineEpisodes.isNotEmpty()) {
                                Spacer(Modifier.height(12.dp))
                                Text(
                                    "选集（${onlineEpisodes.size}）",
                                    style = MaterialTheme.typography.titleSmall
                                )
                                Spacer(Modifier.height(4.dp))
                                onlineEpisodes.forEach { ep ->
                                    val isCurrent = ep.cid == curCid
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(
                                                if (isCurrent) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                                                else MaterialTheme.colorScheme.surfaceVariant
                                            )
                                            .clickable { if (!isCurrent) playOnlineEpisode(ep.cid) }
                                            .padding(horizontal = 10.dp, vertical = 8.dp),
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Icon(
                                            if (isCurrent) Icons.Filled.PlayArrow else Icons.Filled.Movie,
                                            contentDescription = null,
                                            modifier = Modifier.size(18.dp),
                                            tint = if (isCurrent) MaterialTheme.colorScheme.primary
                                            else MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Text(
                                            text = ep.part,
                                            style = MaterialTheme.typography.bodyMedium,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            color = if (isCurrent) MaterialTheme.colorScheme.primary
                                            else MaterialTheme.colorScheme.onSurface
                                        )
                                    }
                                    Spacer(Modifier.height(4.dp))
                                }
                            }
                        }
                    }
                }
            }

            // 全屏/横屏时：底部悬浮控制条 + 顶部退出按钮（可自动隐藏）
            if (isFullscreen && controlsVisible) {
                IconButton(
                    onClick = { exitFullscreen() },
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp)
                ) {
                    Icon(
                        Icons.Filled.FullscreenExit,
                        contentDescription = "退出全屏",
                        tint = Color.White
                    )
                }
                VideoControlsBar(
                    isPlaying = isPlaying,
                    position = position,
                    duration = duration,
                    playMode = playMode,
                    showQueueNav = hasNav,
                    overlay = true,
                    cropFill = cropFill,
                    onToggleResize = { cropFill = !cropFill },
                    onPlayPause = { cmd(VideoPlaybackService.ACTION_TOGGLE) },
                    onPrev = { cmd(VideoPlaybackService.ACTION_PREV) },
                    onNext = { cmd(VideoPlaybackService.ACTION_NEXT) },
                    onSeek = { pos ->
                        cmd(VideoPlaybackService.ACTION_SEEK) {
                            putExtra(VideoPlaybackService.EXTRA_POSITION, pos)
                        }
                    },
                    onCycleMode = { cycleMode() },
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Color.Black.copy(alpha = 0.55f))
                )
            }
        }
    }
}

/** 视频控制条：拖拽进度 + 播放/暂停 + 上一集/下一集 + 播放模式 + 画面适配切换 */
@Composable
private fun VideoControlsBar(
    isPlaying: Boolean,
    position: Long,
    duration: Long,
    playMode: Int,
    showQueueNav: Boolean,
    overlay: Boolean,
    cropFill: Boolean,
    onToggleResize: () -> Unit,
    onPlayPause: () -> Unit,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Long) -> Unit,
    onCycleMode: () -> Unit,
    modifier: Modifier = Modifier
) {
    val contentColor = if (overlay) Color.White else MaterialTheme.colorScheme.onSurface
    val subColor = if (overlay) Color.White.copy(alpha = 0.8f) else MaterialTheme.colorScheme.onSurfaceVariant

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(
                if (overlay) Color.Transparent
                else MaterialTheme.colorScheme.surfaceVariant
            )
            .padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        // 进度条 + 时间（细条动画，拖动同步显示）
        var dragging by remember { mutableStateOf(false) }
        var dragMs by remember { mutableLongStateOf(-1L) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = formatVideoMs(if (dragging) dragMs.coerceAtLeast(0) else position),
                style = MaterialTheme.typography.labelSmall,
                color = subColor
            )
            com.bili23.android.ui.components.SlimProgressBar(
                valueMs = position,
                maxMs = duration,
                onSeek = onSeek,
                onDragStateChange = { d ->
                    dragging = d
                    if (!d) dragMs = -1L
                },
                onDragValueChange = { dragMs = it },
                activeColor = if (overlay) Color.White else MaterialTheme.colorScheme.primary,
                trackColor = if (overlay) Color.White.copy(alpha = 0.3f)
                else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.15f),
                thumbColor = if (overlay) Color.White else MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 8.dp)
            )
            Text(
                text = formatVideoMs(duration),
                style = MaterialTheme.typography.labelSmall,
                color = subColor
            )
        }
        // 控制按钮
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (showQueueNav) {
                IconButton(onClick = onPrev) {
                    Icon(Icons.Filled.SkipPrevious, contentDescription = "上一集", tint = contentColor)
                }
            }
            IconButton(onClick = onPlayPause) {
                Icon(
                    if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    contentDescription = "播放/暂停",
                    tint = contentColor,
                    modifier = Modifier.width(40.dp)
                )
            }
            if (showQueueNav) {
                IconButton(onClick = onNext) {
                    Icon(Icons.Filled.SkipNext, contentDescription = "下一集", tint = contentColor)
                }
            }
            IconButton(onClick = onCycleMode) {
                val (icon, desc) = when (playMode) {
                    1 -> Icons.Filled.Repeat to "列表循环"
                    2 -> Icons.Filled.RepeatOne to "单曲循环"
                    3 -> Icons.Filled.Shuffle to "随机播放"
                    else -> Icons.Filled.Repeat to "顺序播放"
                }
                Icon(icon, contentDescription = desc, tint = if (overlay) Color.White else MaterialTheme.colorScheme.primary)
            }
            // 画面适配：适应屏幕 / 裁切铺满
            TextButton(
                onClick = onToggleResize,
                modifier = Modifier.padding(horizontal = 4.dp)
            ) {
                Text(
                    text = if (cropFill) "裁切" else "适应",
                    style = MaterialTheme.typography.labelMedium,
                    color = contentColor
                )
            }
        }
        Text(
            text = when (playMode) {
                1 -> "列表循环"
                2 -> "单曲循环"
                3 -> "随机播放"
                else -> "顺序播放"
            },
            style = MaterialTheme.typography.labelSmall,
            color = subColor,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )
    }
}
