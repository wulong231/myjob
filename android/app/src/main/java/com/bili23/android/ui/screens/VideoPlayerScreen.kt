package com.bili23.android.ui.screens

import androidx.activity.compose.BackHandler
import android.content.res.Configuration
import android.net.Uri
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
import androidx.compose.runtime.mutableFloatStateOf
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
import androidx.media3.common.AudioAttributes
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.MergingMediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import com.bili23.android.data.BiliApi
import com.bili23.android.data.PlayUrl
import com.bili23.android.data.Settings
import com.bili23.android.data.qualityName
import com.bili23.android.ui.AppViewModel
import com.bili23.android.ui.applySystemBarTheme
import com.bili23.android.ui.isDarkThemeNow
import java.io.File
import kotlin.random.Random
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 毫秒 → mm:ss（视频进度显示） */
private fun formatVideoMs(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0L)
    return "%d:%02d".format(total / 60, total % 60)
}

@androidx.annotation.OptIn(UnstableApi::class)
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoPlayerScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val context = LocalContext.current
    val currentPlay by vm.currentPlay.collectAsState()
    val localPath by vm.localPlayPath.collectAsState()
    val videoQueue by vm.videoQueue.collectAsState()
    val videoQueueIndex by vm.videoQueueIndex.collectAsState()
    val tasks by vm.downloadManager.tasks.collectAsState()
    val play = currentPlay?.third ?: PlayUrl()
    val isLocal = localPath != null
    val configuration = LocalConfiguration.current
    val isLandscape = configuration.orientation == Configuration.ORIENTATION_LANDSCAPE

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
    // 播放模式：0=顺序 1=列表循环 2=单曲循环 3=随机
    var playMode by remember { mutableIntStateOf(Settings.videoPlayMode) }
    val inQueue = videoQueue.size > 1

    // 在线播放选集（来自详情页已加载的视频信息；若进入播放器时未加载则重新拉取）
    val videoInfo by vm.videoInfo.collectAsState()
    val onlineEpisodes = if (!isLocal) (videoInfo?.episodes ?: emptyList()) else emptyList()
    val onlineIndex = onlineEpisodes.indexOfFirst { it.cid == currentPlay?.second }
    LaunchedEffect(currentPlay?.first, isLocal) {
        val bvid = currentPlay?.first
        if (!isLocal && bvid != null && videoInfo?.bvid != bvid) {
            vm.loadVideoDetail(bvid)
        }
    }

    // 可切换的视频集合：本地用队列/本地列表；在线用该视频的选集（分P）
    val navVideos = if (!isLocal) emptyList()
    else if (inQueue) videoQueue
    else allLocalVideos
    val navIndex = if (!isLocal) 0
    else if (inQueue) videoQueueIndex
    else allLocalVideos.indexOf(localPath).coerceAtLeast(0)
    val canNav = if (isLocal) navVideos.size > 1 else onlineEpisodes.size > 1

    var player by remember { mutableStateOf<ExoPlayer?>(null) }
    var manualFullscreen by remember { mutableStateOf(false) }
    val isFullscreen = isLandscape || manualFullscreen

    // 画面适配：false=适应屏幕(等比)，true=裁切铺满
    var cropFill by remember { mutableStateOf(false) }

    // 全屏控制条自动隐藏
    var controlsVisible by remember { mutableStateOf(true) }
    val scope = rememberCoroutineScope()
    var hideJob by remember { mutableStateOf<Job?>(null) }

    fun pokeControls() {
        controlsVisible = true
        if (!isFullscreen) return
        hideJob?.cancel()
        hideJob = scope.launch {
            delay(3000)
            val p = player
            if (p?.isPlaying == true) controlsVisible = false
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

    // 全屏进入/退出时重置控制条显隐
    LaunchedEffect(isFullscreen) {
        if (isFullscreen) pokeControls() else {
            hideJob?.cancel()
            controlsVisible = true
        }
    }

    // 播放进度/状态（用于自绘控制条）
    var posMs by remember { mutableLongStateOf(0L) }
    var durMs by remember { mutableLongStateOf(0L) }
    var isVideoPlaying by remember { mutableStateOf(false) }

    // 收藏状态（仅本地视频）
    val localPathForFav = localPath
    var favState by remember(localPathForFav) { mutableStateOf(Settings.isFavorite(localPathForFav ?: "")) }

    // 本地路径优先，其次在线 DASH
    val playKey = if (isLocal) "local:$localPath" else play.videoUrl

    fun syncPlayerState() {
        val p = player
        if (p != null) {
            posMs = p.currentPosition
            durMs = p.duration.coerceAtLeast(0L)
            isVideoPlaying = p.isPlaying
        }
    }

    /** 在线播放指定分P（拉取地址后切换，不经过本地队列） */
    fun playOnlineEpisode(cid: Long) {
        if (cid <= 0) return
        val bvid = currentPlay?.first ?: return
        val q = play.quality
        scope.launch {
            val url = vm.fetchPlayUrl(bvid, cid, q)
            if (url.videoUrl.isNotEmpty()) {
                vm.setCurrentPlay(bvid, cid, url)
            }
        }
    }

    fun onVideoEnded() {
        if (!canNav) {
            if (playMode == 2) { // 单曲循环
                player?.seekTo(0)
                player?.play()
            }
            return
        }
        if (!isLocal) {
            // 在线多P自动连播
            when (playMode) {
                2 -> {
                    player?.seekTo(0)
                    player?.play()
                }

                1 -> {
                    if (onlineIndex < onlineEpisodes.size - 1)
                        playOnlineEpisode(onlineEpisodes[onlineIndex + 1].cid)
                    else playOnlineEpisode(onlineEpisodes.firstOrNull()?.cid ?: 0)
                }

                else -> {
                    if (onlineIndex < onlineEpisodes.size - 1)
                        playOnlineEpisode(onlineEpisodes[onlineIndex + 1].cid)
                    else {
                        player?.seekTo(0)
                        player?.pause()
                    }
                }
            }
            return
        }
        when (playMode) {
            2 -> { // 单曲循环
                player?.seekTo(0)
                player?.play()
            }

            3 -> { // 随机
                if (navVideos.size > 1) {
                    var n = Random.nextInt(navVideos.size)
                    while (n == navIndex) n = Random.nextInt(navVideos.size)
                    vm.setVideoQueue(navVideos, n)
                } else {
                    player?.seekTo(0)
                    player?.play()
                }
            }

            0 -> { // 顺序：播完末尾即停止
                if (navIndex < navVideos.size - 1) {
                    vm.setVideoQueue(navVideos, navIndex + 1)
                } else {
                    player?.seekTo(0)
                    player?.pause()
                }
            }

            else -> { // 列表循环
                vm.setVideoQueue(navVideos, (navIndex + 1) % navVideos.size)
            }
        }
    }

    fun nextVideo() {
        if (!canNav) return
        if (!isLocal) {
            val next = onlineEpisodes.getOrNull(onlineIndex + 1) ?: return
            playOnlineEpisode(next.cid)
            return
        }
        when (playMode) {
            3 -> {
                if (navVideos.size > 1) {
                    var n = Random.nextInt(navVideos.size)
                    while (n == navIndex) n = Random.nextInt(navVideos.size)
                    vm.setVideoQueue(navVideos, n)
                }
            }

            0 -> {
                if (navIndex < navVideos.size - 1) vm.setVideoQueue(navVideos, navIndex + 1)
                else vm.setVideoQueue(navVideos, 0)
            }

            else -> vm.setVideoQueue(navVideos, (navIndex + 1) % navVideos.size)
        }
    }

    fun prevVideo() {
        if (!canNav) return
        if (!isLocal) {
            val prev = onlineEpisodes.getOrNull(onlineIndex - 1) ?: return
            playOnlineEpisode(prev.cid)
            return
        }
        if (posMs > 3000) {
            player?.seekTo(0)
            return
        }
        vm.setVideoQueue(navVideos, if (navIndex <= 0) navVideos.size - 1 else navIndex - 1)
    }

    fun cycleMode() {
        playMode = (playMode + 1) % 4
        Settings.videoPlayMode = playMode
    }

    /** 绑定视频通知控制器：通知栏按钮可控制当前播放器 */
    fun bindVideoNotification(p: ExoPlayer) {
        com.bili23.android.service.VideoMediaController.player = p
        com.bili23.android.service.VideoMediaController.onNext = { nextVideo() }
        com.bili23.android.service.VideoMediaController.onPrev = { prevVideo() }
        com.bili23.android.service.VideoMediaController.onStop = {
            p.stop()
            navController.popBackStack()
        }
        com.bili23.android.service.VideoMediaController.title =
            if (isLocal) (localPath ?: "").substringAfterLast('/')
            else (videoInfo?.title?.ifBlank { null } ?: "视频播放")
        com.bili23.android.service.VideoMediaController.subtitle =
            if (!canNav) ""
            else if (isLocal) "${navIndex + 1}/${navVideos.size}"
            else "${onlineIndex + 1}/${onlineEpisodes.size}"
        com.bili23.android.service.VideoMediaNotification.update()
    }

    // 构建播放器（含队列自动切集）
    DisposableEffect(playKey, videoQueueIndex) {
        // 播放视频前停止音频服务，避免音视频同时播放
        vm.stopMusic()
        // 初始化视频通知系统（可后台控制播放/暂停）
        com.bili23.android.service.VideoMediaNotification.init(context)
        if (isLocal && localPath != null) {
            val f = File(localPath!!)
            if (f.exists()) {
                val newPlayer = ExoPlayer.Builder(context).build()
                // 音频焦点：避免与其他 App 的音乐播放冲突（被抢占时暂停/降音，恢复后续播）
                newPlayer.setAudioAttributes(AudioAttributes.DEFAULT, true)
                newPlayer.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        syncPlayerState()
                        if (playbackState == Player.STATE_ENDED) onVideoEnded()
                    }

                    override fun onIsPlayingChanged(isPlaying: Boolean) {
                        syncPlayerState()
                    }
                })
                newPlayer.setMediaItem(MediaItem.fromUri(Uri.fromFile(f)))
                newPlayer.prepare()
                newPlayer.playWhenReady = true
                player = newPlayer
                bindVideoNotification(newPlayer)
            }
        } else if (play.videoUrl.isNotEmpty()) {
            val newPlayer = buildBiliPlayer(context, play)
            player = newPlayer
            newPlayer.prepare()
            newPlayer.playWhenReady = true
            bindVideoNotification(newPlayer)
        }
        onDispose {
            player?.release()
            player = null
            com.bili23.android.service.VideoMediaNotification.cancel()
            com.bili23.android.service.VideoMediaController.reset()
        }
    }

    // 轮询播放进度（用于自绘控制条 + 同步通知栏）
    LaunchedEffect(playKey) {
        var notifyTicks = 0
        while (true) {
            syncPlayerState()
            // 每约 2 秒刷新一次通知栏状态/进度
            notifyTicks++
            if (notifyTicks % 4 == 0) {
                com.bili23.android.service.VideoMediaController.title =
                    if (isLocal) (localPath ?: "").substringAfterLast('/')
                    else (videoInfo?.title?.ifBlank { null } ?: "视频播放")
                com.bili23.android.service.VideoMediaController.subtitle =
                    if (!canNav) ""
                    else if (isLocal) "${navIndex + 1}/${navVideos.size}"
                    else "${onlineIndex + 1}/${onlineEpisodes.size}"
                com.bili23.android.service.VideoMediaNotification.update()
            }
            kotlinx.coroutines.delay(500)
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
            activity?.requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            controller?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            applySystemBarTheme(window, isDarkThemeNow(context))
        }
        onDispose {
            com.bili23.android.FullscreenController.isFullscreen = false
            activity?.requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            controller?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            applySystemBarTheme(window, isDarkThemeNow(context))
        }
    }

    /** 退出全屏：取消手动全屏并强制恢复竖屏（解决横屏状态下恢复按钮失效） */
    fun exitFullscreen() {
        manualFullscreen = false
        (context as? android.app.Activity)?.requestedOrientation =
            android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
    }

    // 全屏/横屏时拦截系统返回手势（左划边缘返回）：先退回竖屏播放界面，而不是直接退出播放器
    BackHandler(enabled = isFullscreen) {
        exitFullscreen()
    }

    Scaffold(
        topBar = {
            if (!isFullscreen) {
                TopAppBar(
                    title = {
                        Text(
                            when {
                                canNav && isLocal -> "${navIndex + 1}/${navVideos.size}"
                                canNav -> "${onlineIndex + 1}/${onlineEpisodes.size}"
                                isLocal -> "本地视频"
                                else -> "播放"
                            }
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = {
                            player?.stop()
                            navController.popBackStack()
                        }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    actions = {
                        if (isLocal) {
                            // 收藏切换
                            IconButton(onClick = {
                                val path = localPath ?: return@IconButton
                                val newFav = !favState
                                favState = newFav
                                Settings.setFavorite(path, newFav)
                            }) {
                                Icon(
                                    if (favState) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                                    contentDescription = "收藏",
                                    tint = if (favState) MaterialTheme.colorScheme.error
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            IconButton(onClick = {
                                val path = localPath
                                if (path != null) {
                                    player?.stop()
                                    vm.deleteVideoFile(path)
                                    navController.popBackStack()
                                }
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
                val hasSource = (isLocal && File(localPath ?: "").exists()) || play.videoUrl.isNotEmpty()
                if (!hasSource) {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("未获取到播放地址", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    return@Column
                }

                // 视频画面：全屏/横屏铺满，否则 16:9（全屏时点击切换控制条显隐）
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
                            // 单击切控制条（全屏时），双击播放/暂停
                            detectTapGestures(
                                onTap = { if (isFullscreen) toggleControls() },
                                onDoubleTap = {
                                    val p = player
                                    if (p != null) {
                                        if (p.isPlaying) p.pause() else p.play()
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
                            val p = player
                            if (p != null && view.player !== p) {
                                view.player = p
                            }
                            // 裁切铺满 / 适应屏幕
                            view.resizeMode = if (cropFill)
                                AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                            else AspectRatioFrameLayout.RESIZE_MODE_FIT
                        }
                    )
                }

                // 非全屏：控制条 + 信息区
                if (!isFullscreen) {
                    VideoControlsBar(
                        isPlaying = isVideoPlaying,
                        position = posMs,
                        duration = durMs,
                        playMode = playMode,
                        showQueueNav = canNav,
                        overlay = false,
                        cropFill = cropFill,
                        onToggleResize = { cropFill = !cropFill },
                        onPlayPause = {
                            val p = player ?: return@VideoControlsBar
                            if (p.isPlaying) p.pause() else p.play()
                        },
                        onPrev = { prevVideo() },
                        onNext = { nextVideo() },
                        onSeek = { player?.seekTo(it) },
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
                                text = (localPath ?: "").substringAfterLast('/'),
                                style = MaterialTheme.typography.titleMedium
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
                                    val isCurrent = p == localPath
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
                                text = "画质：${qualityName(play.quality)}",
                                style = MaterialTheme.typography.titleMedium
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                text = "当前以分离式 DASH 流播放（视频+音频已自动合并）",
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
                                    val isCurrent = ep.cid == currentPlay?.second
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
                    isPlaying = isVideoPlaying,
                    position = posMs,
                    duration = durMs,
                    playMode = playMode,
                    showQueueNav = canNav,
                    overlay = true,
                    cropFill = cropFill,
                    onToggleResize = { cropFill = !cropFill },
                    onPlayPause = {
                        val p = player ?: return@VideoControlsBar
                        if (p.isPlaying) p.pause() else p.play()
                    },
                    onPrev = { prevVideo() },
                    onNext = { nextVideo() },
                    onSeek = { player?.seekTo(it) },
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

@androidx.annotation.OptIn(UnstableApi::class)
private fun buildBiliPlayer(context: android.content.Context, play: PlayUrl): ExoPlayer {
    val dataSourceFactory = DefaultHttpDataSource.Factory()
        .setUserAgent(BiliApi.USER_AGENT)
        .setDefaultRequestProperties(
            mapOf(
                "Referer" to "https://www.bilibili.com/",
                "Origin" to "https://www.bilibili.com"
            )
        )
        .setAllowCrossProtocolRedirects(true)

    val player = ExoPlayer.Builder(context)
        .setMediaSourceFactory(
            androidx.media3.exoplayer.source.DefaultMediaSourceFactory(dataSourceFactory)
        )
        .build()
    // 音频焦点：避免与其他 App 的音乐播放冲突（被抢占时暂停/降音，恢复后续播）
    player.setAudioAttributes(AudioAttributes.DEFAULT, true)

    val videoItem = MediaItem.Builder()
        .setUri(Uri.parse(play.videoUrl))
        .setMimeType(MimeTypes.VIDEO_MP4)
        .build()
    val audioItem = MediaItem.Builder()
        .setUri(Uri.parse(play.audioUrl))
        .setMimeType(MimeTypes.AUDIO_AAC)
        .build()

    if (play.audioUrl.isNotEmpty()) {
        val source = MergingMediaSource(
            ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(videoItem),
            ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(audioItem)
        )
        player.setMediaSource(source)
    } else {
        player.setMediaItem(videoItem)
    }
    return player
}
