package com.bili23.android.ui.screens

import android.content.Intent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Lyrics
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.bili23.android.data.AudioItem
import com.bili23.android.data.Settings
import com.bili23.android.service.MusicPlaybackService
import com.bili23.android.ui.AppViewModel
import com.bili23.android.ui.components.CompactIconButton
import com.bili23.android.ui.components.dragReorderHandle
import com.bili23.android.ui.components.rememberDragDropListState
import java.io.File
import kotlinx.coroutines.launch

/** 歌词行 */
private data class LyricLine(val timeMs: Long, val text: String)

/** 解析 LRC 文本 → 歌词行列表（过滤空行与词曲编曲等元信息行，避免与翻译错位） */
private fun parseLrc(lrc: String): List<LyricLine> {
    val lines = mutableListOf<LyricLine>()
    val regex = Regex("\\[(\\d{1,2}):(\\d{1,2})(?:\\.(\\d{1,3}))?]")
    for (raw in lrc.split("\n")) {
        val matches = regex.findAll(raw).toList()
        if (matches.isEmpty()) continue
        val text = raw.substringAfterLast(']').trim()
        if (text.isEmpty()) continue
        // 过滤词曲编曲、制作人等非歌词元信息行（日译中时这些行会与翻译错位）
        if (isCreditLine(text)) continue
        for (m in matches) {
            val min = m.groupValues[1].toIntOrNull() ?: 0
            val sec = m.groupValues[2].toIntOrNull() ?: 0
            val msPart = m.groupValues[3]
            val ms = when (msPart.length) {
                1 -> msPart.toIntOrNull()?.times(100) ?: 0
                2 -> msPart.toIntOrNull()?.times(10) ?: 0
                3 -> msPart.toIntOrNull() ?: 0
                else -> 0
            }
            lines.add(LyricLine(min * 60_000L + sec * 1000L + ms, text))
        }
    }
    return lines.sortedBy { it.timeMs }
}

/** 是否为词曲编曲等元信息行（不计入歌词显示） */
private fun isCreditLine(text: String): Boolean {
    val t = text.trim()
    if (t.isEmpty()) return true
    // 词曲编曲/制作/标注 等，以及 [ti:][ar:][by:][al:] 标签
    return Regex(
        "^(作词|作曲|编曲|制作人|制作|监制|混音|录音|母带|和声|吉他|贝斯|鼓手|键盘|钢琴|弦乐|出品|" +
            "producer|composer|lyricist|arranger|mix|record|master)\\s*[:：]",
        RegexOption.IGNORE_CASE
    ).containsMatchIn(t) ||
            Regex("^(by|ti|ar|al|offset)\\s*[:：]", RegexOption.IGNORE_CASE).containsMatchIn(t)
}

/** 当前播放行索引（考虑偏移） */
private fun currentLyricIndex(lines: List<LyricLine>, posMs: Long, offsetMs: Long): Int {
    if (lines.isEmpty()) return -1
    val adjusted = posMs - offsetMs
    var idx = -1
    for (i in lines.indices) {
        if (adjusted >= lines[i].timeMs) idx = i
        else break
    }
    return idx
}

/** 毫秒 → mm:ss */
private fun formatMs(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0L)
    return "%d:%02d".format(total / 60, total % 60)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AudioPlayerScreen(vm: AppViewModel = viewModel()) {
    val context = LocalContext.current
    val audioFiles by vm.audioFiles.collectAsState()
    val localToPlay by vm.localAudioToPlay.collectAsState()

    // 选中的音频（不自动播放，需点击播放按钮）
    var selectedPath by remember { mutableStateOf<String?>(null) }
    // 当前实际播放的音频
    var currentPath by remember { mutableStateOf<String?>(null) }
    var isPlaying by remember { mutableStateOf(false) }
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }
    // 播放模式
    var playMode by remember { mutableIntStateOf(MusicPlaybackService.playMode) }

    // 歌词
    var lyrics by remember { mutableStateOf<List<LyricLine>>(emptyList()) }
    var translations by remember { mutableStateOf<List<LyricLine>>(emptyList()) }
    var lyricOffset by remember { mutableLongStateOf(0L) }
    var showSearchDialog by remember { mutableStateOf(false) }
    // 歌词自动匹配状态
    var lyricLoading by remember { mutableStateOf(false) }
    var lyricStatus by remember { mutableStateOf("") }

    // 标签编辑
    var editTagItem by remember { mutableStateOf<AudioItem?>(null) }
    // 添加到播放列表
    var addToListPath by remember { mutableStateOf<String?>(null) }
    // 歌词编辑
    var showLyricEdit by remember { mutableStateOf(false) }
    // 播放列表筛选（null = 全部音频，仅音频类型列表）
    var selectedPlaylist by remember { mutableStateOf<String?>(null) }
    var playlistTick by remember { mutableStateOf(0) }
    val playlists = remember(playlistTick) { Settings.getPlaylists(Settings.PLAYLIST_AUDIO) }
    // 歌手分类筛选（null = 全部歌手）
    var selectedArtist by remember { mutableStateOf<String?>(null) }
    val artists = remember(audioFiles) {
        audioFiles.map { it.artist }.filter { it.isNotBlank() }.distinct().sorted()
    }
    // 搜索框：按歌手/歌名模糊筛选
    var searchKeyword by remember { mutableStateOf("") }
    // 分类（播放列表 + 歌手）收纳开关
    var filtersExpanded by remember { mutableStateOf(false) }

    // 当前展示的音频列表：按播放列表 + 歌手 + 搜索词三重筛选
    val displayAudio = audioFiles.filter { item ->
        (selectedPlaylist == null || Settings.isInPlaylist(Settings.PLAYLIST_AUDIO, selectedPlaylist!!, item.path)) &&
            (selectedArtist == null || item.artist == selectedArtist) &&
            (searchKeyword.isBlank() ||
                item.artist.contains(searchKeyword, ignoreCase = true) ||
                item.displayTitle.contains(searchKeyword, ignoreCase = true))
    }

    // 多选模式
    var selectionMode by remember { mutableStateOf(false) }
    var selectedPaths by remember { mutableStateOf<Set<String>>(emptySet()) }
    // 多选“加入列表”
    var addSelectedToPlaylist by remember { mutableStateOf(false) }

    // 收藏刷新标记
    var favTick by remember { mutableStateOf(0) }
    val favPaths = remember(favTick) { Settings.getFavoritePaths() }

    LaunchedEffect(Unit) {
        vm.scanAudioFiles()
    }

    /** 播放列表并定位到指定曲目（支持上一首/下一首/随机，列表范围为当前展示列表） */
    fun playListAt(index: Int, path: String) {
        val list = displayAudio
        if (list.isEmpty()) return
        val intent = Intent(context, MusicPlaybackService::class.java).apply {
            action = MusicPlaybackService.ACTION_SET_PLAYLIST
            putStringArrayListExtra(MusicPlaybackService.EXTRA_PATHS, ArrayList(list.map { it.path }))
            putStringArrayListExtra(MusicPlaybackService.EXTRA_TITLES, ArrayList(list.map { it.displayTitle }))
            putStringArrayListExtra(MusicPlaybackService.EXTRA_ARTISTS, ArrayList(list.map { it.artist }))
            putStringArrayListExtra(MusicPlaybackService.EXTRA_COVERS, ArrayList(list.map { it.coverPath }))
            putExtra(MusicPlaybackService.EXTRA_INDEX, index.coerceIn(0, list.size - 1))
        }
        context.startForegroundService(intent)
        selectedPath = path
        currentPath = path
    }

    /** 播放单曲（下载管理跳转等场景） */
    fun playViaService(path: String) {
        val item = audioFiles.firstOrNull { it.path == path }
        val intent = Intent(context, MusicPlaybackService::class.java).apply {
            action = MusicPlaybackService.ACTION_PLAY_PATH
            putExtra(MusicPlaybackService.EXTRA_PATH, path)
            putExtra(MusicPlaybackService.EXTRA_TITLE, item?.displayTitle ?: "")
            putExtra(MusicPlaybackService.EXTRA_ARTIST, item?.artist ?: "")
            putExtra(MusicPlaybackService.EXTRA_COVER, item?.coverPath ?: "")
        }
        context.startForegroundService(intent)
        selectedPath = path
        currentPath = path
    }

    // 从下载管理跳转播放（用户明确点击播放，允许自动播）
    LaunchedEffect(localToPlay) {
        val path = localToPlay ?: return@LaunchedEffect
        val f = File(path)
        if (f.exists()) {
            selectedPath = path
            currentPath = path
            lyrics = emptyList()
            translations = emptyList()
            lyricOffset = 0L
            playViaService(path)
        }
        // 消费后清除标记，避免后续进入音频页时重复自动跳转/播放
        vm.clearLocalAudioToPlay()
    }

    // 播放曲目变化时自动匹配歌词：优先读缓存，其次自动搜索网易云取第一条
    LaunchedEffect(currentPath) {
        val path = currentPath ?: return@LaunchedEffect
        val item = audioFiles.firstOrNull { it.path == path } ?: return@LaunchedEffect
        val cached = Settings.getLyric(path)
        if (cached.isNotBlank()) {
            lyrics = parseLrc(cached)
            translations = parseLrc(Settings.getLyricTranslation(path))
            // 恢复该曲目保留的歌词偏移（搜索到的歌词时间可能不准）
            lyricOffset = Settings.getLyricOffset(path)
            lyricLoading = false
            lyricStatus = ""
            return@LaunchedEffect
        }
        lyricLoading = true
        lyricStatus = "正在自动匹配歌词..."
        lyrics = emptyList()
        translations = emptyList()
        val results = vm.searchLyrics(item.displayTitle)
        val (lrc, tl) = if (results.isEmpty()) Pair("", "")
        else vm.fetchLyricWithTranslation(results.first().second)
        lyricLoading = false
        if (lrc.isNotEmpty()) {
            lyrics = parseLrc(lrc)
            translations = parseLrc(tl)
            lyricOffset = 0L
            Settings.setLyricOffset(path, 0L)
            Settings.setLyric(path, lrc)
            Settings.setLyricTranslation(path, tl)
            lyricStatus = ""
        } else {
            lyricStatus = "未自动匹配到歌词，点右上角图标可手动搜索"
        }
    }

    /** 开始播放（仅当有选中时） */
    fun playSelected(path: String) {
        currentPath = path
        lyrics = emptyList()
        translations = emptyList()
        lyricOffset = 0L
        val idx = displayAudio.indexOfFirst { it.path == path }
        if (idx >= 0) playListAt(idx, path) else playViaService(path)
    }

    /** 循环切换播放模式 */
    fun cycleMode() {
        playMode = (playMode + 1) % 4
        MusicPlaybackService.playMode = playMode
        context.startService(
            Intent(context, MusicPlaybackService::class.java).apply {
                action = MusicPlaybackService.ACTION_SET_MODE
                putExtra(MusicPlaybackService.EXTRA_MODE, playMode)
            }
        )
    }

    val current = audioFiles.firstOrNull { it.path == currentPath }
    // 是否显示歌词（顶部按钮可开关，默认关闭）
    var showLyrics by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize()) {
        // 顶部：菜单 + 标题 + 歌词搜索 + 歌词开关
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 4.dp, top = 4.dp, end = 4.dp, bottom = 0.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            com.bili23.android.DrawerMenuButton()
            Text(
                text = "音频播放",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.weight(1f)
            )
            IconButton(onClick = { if (currentPath != null) showSearchDialog = true }) {
                Icon(Icons.Filled.Lyrics, contentDescription = "搜索歌词")
            }
            // 歌词显示开关
            IconButton(onClick = { showLyrics = !showLyrics }) {
                Icon(
                    Icons.Filled.Lyrics,
                    contentDescription = if (showLyrics) "关闭歌词" else "显示歌词",
                    tint = if (showLyrics) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                )
            }
        }

        // 搜索框：按歌手/歌名定位歌曲
        OutlinedTextField(
            value = searchKeyword,
            onValueChange = { searchKeyword = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 4.dp),
            placeholder = { Text("搜索歌手 / 歌名") },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            trailingIcon = {
                if (searchKeyword.isNotEmpty()) {
                    IconButton(onClick = { searchKeyword = "" }) {
                        Icon(Icons.Filled.Close, contentDescription = "清空")
                    }
                }
            },
            singleLine = true,
            shape = RoundedCornerShape(24.dp)
        )

        // 分类收纳按钮：展开/收起播放列表与歌手分类
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { filtersExpanded = !filtersExpanded }
                .padding(horizontal = 16.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "分类",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(Modifier.width(2.dp))
            Icon(
                if (filtersExpanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
                tint = MaterialTheme.colorScheme.primary
            )
            Spacer(Modifier.width(6.dp))
            Text(
                text = if (filtersExpanded) "收起分类" else "展开播放列表 / 歌手分类",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        // 播放列表筛选：全部音频 / 各命名列表（收纳区域）
        if (filtersExpanded) {
        LazyRow(
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            item {
                FilterChip(
                    selected = selectedPlaylist == null,
                    onClick = { selectedPlaylist = null },
                    label = { Text("全部音频") }
                )
            }
            items(playlists.keys.toList(), key = { it }) { name ->
                FilterChip(
                    selected = selectedPlaylist == name,
                    onClick = { selectedPlaylist = name },
                    label = { Text(name) }
                )
            }
        }

        // 歌手分类筛选：按歌手定位对应歌曲（始终显示入口，未设置歌手时只有“全部歌手”）
        LazyRow(
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            item {
                FilterChip(
                    selected = selectedArtist == null,
                    onClick = { selectedArtist = null },
                    label = { Text("全部歌手") }
                )
            }
            items(artists, key = { it }) { artist ->
                FilterChip(
                    selected = selectedArtist == artist,
                    onClick = { selectedArtist = artist },
                    label = { Text(artist) }
                )
            }
        }
        } // 收纳区域结束

        // 多选工具栏（小字体，保证一行放得下）
        if (selectionMode) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "已选 ${selectedPaths.size} 项",
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.weight(1f)
                )
                TextButton(
                    onClick = {
                        selectedPaths = if (selectedPaths.size == displayAudio.size)
                            emptySet() else displayAudio.map { it.path }.toSet()
                    },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                ) { Text("全选", style = MaterialTheme.typography.labelMedium) }
                TextButton(
                    onClick = { if (selectedPaths.isNotEmpty()) addSelectedToPlaylist = true },
                    enabled = selectedPaths.isNotEmpty(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                ) {
                    Icon(Icons.Filled.PlaylistAdd, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(2.dp))
                    Text("加入列表", style = MaterialTheme.typography.labelMedium)
                }
                TextButton(
                    onClick = {
                        vm.deleteAudioFiles(selectedPaths.toList())
                        selectedPaths = emptySet()
                        selectionMode = false
                    },
                    enabled = selectedPaths.isNotEmpty(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                ) {
                    Icon(Icons.Filled.Delete, contentDescription = null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(2.dp))
                    Text("删除", style = MaterialTheme.typography.labelMedium)
                }
                TextButton(
                    onClick = {
                        selectedPaths = emptySet()
                        selectionMode = false
                    },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                ) { Text("完成", style = MaterialTheme.typography.labelMedium) }
            }
        }

        // 当前播放卡片
        if (current != null && !selectionMode) {
            NowPlayingCard(
                item = current,
                isPlaying = isPlaying,
                position = position,
                duration = duration,
                playMode = playMode,
                onPlayPause = {
                    context.startService(
                        Intent(context, MusicPlaybackService::class.java).apply {
                            action = MusicPlaybackService.ACTION_TOGGLE
                        }
                    )
                },
                onPrev = {
                    context.startService(
                        Intent(context, MusicPlaybackService::class.java).apply {
                            action = MusicPlaybackService.ACTION_PREV
                        }
                    )
                },
                onNext = {
                    context.startService(
                        Intent(context, MusicPlaybackService::class.java).apply {
                            action = MusicPlaybackService.ACTION_NEXT
                        }
                    )
                },
                onSeek = { pos ->
                    context.startService(
                        Intent(context, MusicPlaybackService::class.java).apply {
                            action = MusicPlaybackService.ACTION_SEEK
                            putExtra(MusicPlaybackService.EXTRA_POSITION, pos)
                        }
                    )
                },
                onCycleMode = { cycleMode() }
            )

            // 歌词自动匹配状态提示
            if (lyricStatus.isNotEmpty()) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp)
                ) {
                    if (lyricLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(6.dp))
                    }
                    Text(
                        lyricStatus,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            // 歌词显示区（滚动高亮 + 点击跳转 + 偏移微调 + 本地编辑，顶部按钮可关闭）
            if (showLyrics && lyrics.isNotEmpty()) {
                val curIdx = currentLyricIndex(lyrics, position, lyricOffset)
                Box {
                    LyricsView(
                        lines = lyrics,
                        currentIndex = curIdx,
                        offsetMs = lyricOffset,
                        translations = translations,
                        onSeek = { targetMs ->
                            context.startService(
                                Intent(context, MusicPlaybackService::class.java).apply {
                                    action = MusicPlaybackService.ACTION_SEEK
                                    putExtra(MusicPlaybackService.EXTRA_POSITION, targetMs)
                                }
                            )
                        },
                        onOffsetChange = {
                            lyricOffset = it
                            // 保存偏移，下次播放同一曲目时恢复
                            currentPath?.let { p -> Settings.setLyricOffset(p, it) }
                        },
                        onResetOffset = {
                            lyricOffset = 0L
                            currentPath?.let { p -> Settings.setLyricOffset(p, 0L) }
                        }
                    )
                    IconButton(
                        onClick = { showLyricEdit = true },
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(4.dp)
                    ) {
                        Icon(
                            Icons.Filled.Edit,
                            contentDescription = "编辑歌词",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }

        if (displayAudio.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    if (selectedPlaylist == null) "暂无音频文件\n请先下载视频的音频"
                    else "该播放列表暂无音频\n点右上角图标可加入列表",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center
                )
            }
        } else {
            // 多选拖拽重排（长按行右侧手柄拖动）
            val audioListState = rememberLazyListState()
            val audioDragState = rememberDragDropListState(audioListState) { from, to ->
                val fromPath = displayAudio.getOrNull(from)?.path
                val toPath = displayAudio.getOrNull(to)?.path
                if (fromPath != null && toPath != null) vm.moveAudioPath(fromPath, toPath)
            }
            LazyColumn(
                state = audioListState,
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    start = 16.dp, end = 16.dp, bottom = 16.dp
                ),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                itemsIndexed(displayAudio, key = { _, it -> it.path }) { index, item ->
                    val isSelected = item.path == selectedPath
                    val isCurrent = item.path == currentPath
                    val isChecked = item.path in selectedPaths
                    val currentIndex by rememberUpdatedState(index)
                    var rowWidth by remember { mutableIntStateOf(0) }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .animateItem(placementSpec = tween(150))
                            .onSizeChanged { rowWidth = it.width }
                            .graphicsLayer {
                                val dragged = audioDragState.draggingItemIndex == currentIndex
                                scaleX = if (dragged) 1.02f else 1f
                                scaleY = if (dragged) 1.02f else 1f
                            }
                            .clip(RoundedCornerShape(10.dp))
                            .background(
                                when {
                                    selectionMode && isChecked -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                                    isSelected -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
                                    else -> androidx.compose.ui.graphics.Color.Transparent
                                }
                            )
                            .combinedClickable(
                                onClick = {
                                    if (selectionMode) {
                                        selectedPaths = if (isChecked) selectedPaths - item.path
                                        else selectedPaths + item.path
                                    } else {
                                        selectedPath = item.path
                                    }
                                },
                                onDoubleClick = {
                                    if (!selectionMode) playSelected(item.path)
                                },
                                onLongClick = {
                                    if (!selectionMode) {
                                        selectionMode = true
                                        selectedPaths = setOf(item.path)
                                    }
                                }
                            )
                            .dragReorderHandle(audioDragState, { currentIndex }, selectionMode, { rowWidth })
                            .padding(horizontal = 8.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (selectionMode) {
                            Checkbox(
                                checked = isChecked,
                                onCheckedChange = {
                                    selectedPaths = if (it) selectedPaths + item.path else selectedPaths - item.path
                                }
                            )
                            Spacer(Modifier.width(4.dp))
                        }
                        // 封面或图标
                        if (item.coverPath.isNotEmpty()) {
                            AsyncImage(
                                model = File(item.coverPath),
                                contentDescription = item.displayTitle,
                                modifier = Modifier
                                    .size(32.dp)
                                    .clip(RoundedCornerShape(6.dp)),
                                contentScale = ContentScale.Crop
                            )
                        } else {
                            Icon(
                                Icons.Filled.LibraryMusic,
                                contentDescription = null,
                                tint = if (isCurrent) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Spacer(Modifier.size(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            // 只显示歌名
                            Text(
                                text = item.displayTitle,
                                style = MaterialTheme.typography.bodyMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                color = if (isCurrent) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurface
                            )
                            if (item.artist.isNotBlank()) {
                                Text(
                                    text = item.artist,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                        if (selectionMode) {
                            // 拖拽手柄：长按拖动重排
                            Box(
                                modifier = Modifier
                                    .size(28.dp)
                                    .padding(end = 4.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Filled.DragHandle,
                                    contentDescription = "拖动排序",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        } else {
                            // 收藏
                            val fav = item.path in favPaths
                            CompactIconButton(
                                onClick = {
                                    Settings.setFavorite(item.path, !fav)
                                    favTick++
                                },
                                icon = if (fav) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                                contentDescription = "收藏",
                                tint = if (fav) MaterialTheme.colorScheme.error
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            // 加入播放列表
                            CompactIconButton(
                                onClick = { addToListPath = item.path },
                                icon = Icons.Filled.PlaylistAdd,
                                contentDescription = "加入播放列表"
                            )
                            // 编辑标签
                            CompactIconButton(
                                onClick = { editTagItem = item },
                                icon = Icons.Filled.Edit,
                                contentDescription = "编辑标签"
                            )
                        }
                    }
                }
            }
        }
    }

    // 标签编辑对话框
    editTagItem?.let { item ->
        EditTagDialog(
            item = item,
            onDismiss = { editTagItem = null },
            onSave = { title, artist ->
                vm.updateAudioTag(item.path, title, artist)
                vm.renameAudioByTag(item.path, title, artist)
                editTagItem = null
            }
        )
    }

    // 添加到播放列表对话框（单项）
    addToListPath?.let { path ->
        AddToPlaylistDialog(
            paths = listOf(path),
            type = Settings.PLAYLIST_AUDIO,
            onDismiss = { addToListPath = null },
            onChanged = { playlistTick++ }
        )
    }

    // 多选“加入列表”对话框
    if (addSelectedToPlaylist) {
        AddToPlaylistDialog(
            paths = selectedPaths.toList(),
            type = Settings.PLAYLIST_AUDIO,
            onDismiss = {
                addSelectedToPlaylist = false
                selectedPaths = emptySet()
                selectionMode = false
            },
            onChanged = { playlistTick++ }
        )
    }

    // 歌词本地编辑对话框（歌词保存为 .lrc 文件，可改原文与翻译）
    if (showLyricEdit) {
        val p = currentPath
        if (p == null) {
            showLyricEdit = false
        } else {
            var text by remember(p) { mutableStateOf(Settings.getLyric(p)) }
            var tlText by remember(p) { mutableStateOf(Settings.getLyricTranslation(p)) }
            AlertDialog(
                onDismissRequest = { showLyricEdit = false },
                title = { Text("编辑歌词") },
                text = {
                    Column {
                        OutlinedTextField(
                            value = text,
                            onValueChange = { text = it },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(240.dp),
                            placeholder = { Text("LRC 歌词（[mm:ss.xx] 文本），保存为 .lrc 文件") }
                        )
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = tlText,
                            onValueChange = { tlText = it },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(160.dp),
                            placeholder = { Text("翻译（日语等，逐行对应），保存为 .lrc.tl 文件") }
                        )
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        Settings.setLyric(p, text)
                        Settings.setLyricTranslation(p, tlText)
                        lyrics = parseLrc(text)
                        translations = parseLrc(tlText)
                        lyricOffset = 0L
                        Settings.setLyricOffset(p, 0L)
                        showLyricEdit = false
                    }) { Text("保存") }
                },
                dismissButton = {
                    TextButton(onClick = { showLyricEdit = false }) { Text("取消") }
                }
            )
        }
    }

    // 歌词搜索对话框
    if (showSearchDialog) {
        LyricsSearchDialog(
            title = current?.displayTitle ?: "",
            onDismiss = { showSearchDialog = false },
            onLyricsLoaded = { lrcText, tlText ->
                lyrics = parseLrc(lrcText)
                translations = parseLrc(tlText)
                lyricOffset = 0L
                lyricStatus = ""
                val p = currentPath
                if (p != null) {
                    Settings.setLyricOffset(p, 0L)
                    Settings.setLyric(p, lrcText)
                    Settings.setLyricTranslation(p, tlText)
                }
                showSearchDialog = false
            }
        )
    }

    // 从服务轮询播放进度与当前曲目（自动切歌时同步封面/歌词）
    LaunchedEffect(Unit) {
        while (true) {
            position = MusicPlaybackService.currentPosition
            duration = MusicPlaybackService.currentDuration
            isPlaying = MusicPlaybackService.isPlaying
            playMode = MusicPlaybackService.playMode
            val sp = MusicPlaybackService.currentPath
            if (sp.isNotEmpty() && sp != currentPath) {
                // 服务端已切歌（自动下一首/上一首等），同步本地当前曲目
                currentPath = sp
                selectedPath = sp
                lyrics = emptyList()
                translations = emptyList()
                lyricOffset = 0L
            }
            kotlinx.coroutines.delay(250)
        }
    }
}

/** 滚动歌词视图：自动滚动到当前行、当前行高亮、翻译显示、点击跳转、偏移微调 */
@Composable
private fun LyricsView(
    lines: List<LyricLine>,
    currentIndex: Int,
    offsetMs: Long,
    translations: List<LyricLine> = emptyList(),
    onSeek: (Long) -> Unit,
    onOffsetChange: (Long) -> Unit,
    onResetOffset: () -> Unit
) {
    val listState = rememberLazyListState()
    LaunchedEffect(currentIndex) {
        if (currentIndex >= 0) {
            listState.animateScrollToItem(currentIndex.coerceAtLeast(0))
        }
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
            .height(220.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
    ) {
        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f)
        ) {
            itemsIndexed(lines) { index, line ->
                val isCurrent = index == currentIndex
                // 翻译按时间戳对齐（原文可能含词曲编曲等被过滤的行，索引会错位）
                val tl = translations.firstOrNull { it.timeMs == line.timeMs }
                // 当前行动画：放大 + 高亮，随播放切换平滑过渡
                val scale by animateFloatAsState(
                    targetValue = if (isCurrent) 1.07f else 1f,
                    animationSpec = tween(durationMillis = 300),
                    label = "lyricScale"
                )
                val alpha by animateFloatAsState(
                    targetValue = if (isCurrent) 1f else 0.7f,
                    animationSpec = tween(durationMillis = 300),
                    label = "lyricAlpha"
                )
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSeek(line.timeMs + offsetMs) }
                        .padding(vertical = 6.dp, horizontal = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = line.text,
                        style = if (isCurrent) MaterialTheme.typography.titleMedium
                        else MaterialTheme.typography.bodyMedium,
                        color = if (isCurrent) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .scale(scale)
                            .alpha(alpha)
                    )
                    if (tl != null && tl.text.isNotBlank()) {
                        // 翻译字幕随当前行切换平滑过渡（与原文同步动画）
                        val tlScale by animateFloatAsState(
                            targetValue = if (isCurrent) 1.05f else 1f,
                            animationSpec = tween(durationMillis = 300),
                            label = "translationScale"
                        )
                        val tlAlpha by animateFloatAsState(
                            targetValue = if (isCurrent) 1f else 0.4f,
                            animationSpec = tween(durationMillis = 300),
                            label = "translationAlpha"
                        )
                        Text(
                            text = tl.text,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                            textAlign = TextAlign.Center,
                            modifier = Modifier
                                .scale(tlScale)
                                .alpha(tlAlpha)
                        )
                    }
                }
            }
        }
        // 偏移微调
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = { onOffsetChange(offsetMs - 500) }) { Text("-0.5s") }
            Text(
                "偏移 ${offsetMs / 1000.0}s",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            TextButton(onClick = { onOffsetChange(offsetMs + 500) }) { Text("+0.5s") }
            TextButton(onClick = onResetOffset) { Text("归零") }
        }
    }
}

/** 当前播放卡片：封面 + 进度拖拽 + 上一首/播放/下一首 + 播放模式 */
@Composable
private fun NowPlayingCard(
    item: AudioItem,
    isPlaying: Boolean,
    position: Long,
    duration: Long,
    playMode: Int,
    onPlayPause: () -> Unit,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Long) -> Unit,
    onCycleMode: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 封面
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center
            ) {
                if (item.coverPath.isNotEmpty()) {
                    AsyncImage(
                        model = File(item.coverPath),
                        contentDescription = item.displayTitle,
                        modifier = Modifier
                            .size(44.dp)
                            .clip(RoundedCornerShape(10.dp)),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    Icon(
                        Icons.Filled.LibraryMusic,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            }
            Spacer(Modifier.size(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.displayTitle,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                if (item.artist.isNotBlank()) {
                    Text(
                        text = item.artist,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }

        // 进度条 + 时间（细条动画，拖动同步显示）
        var dragging by remember { mutableStateOf(false) }
        var dragMs by remember { mutableLongStateOf(-1L) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = formatMs(if (dragging) dragMs.coerceAtLeast(0) else position),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
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
                activeColor = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.15f),
                thumbColor = MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 8.dp)
            )
            Text(
                text = formatMs(duration),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        // 控制按钮：上一首 / 播放 / 下一首 / 播放模式
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onPrev) {
                Icon(Icons.Filled.SkipPrevious, contentDescription = "上一首")
            }
            IconButton(onClick = onPlayPause) {
                Icon(
                    if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    contentDescription = "播放/暂停",
                    modifier = Modifier.size(44.dp)
                )
            }
            IconButton(onClick = onNext) {
                Icon(Icons.Filled.SkipNext, contentDescription = "下一首")
            }
            IconButton(onClick = onCycleMode) {
                val (icon, desc) = when (playMode) {
                    MusicPlaybackService.MODE_LOOP_LIST -> Icons.Filled.Repeat to "列表循环"
                    MusicPlaybackService.MODE_LOOP_ONE -> Icons.Filled.RepeatOne to "单曲循环"
                    MusicPlaybackService.MODE_SHUFFLE -> Icons.Filled.Shuffle to "随机播放"
                    else -> Icons.Filled.Repeat to "顺序播放"
                }
                Icon(icon, contentDescription = desc, tint = MaterialTheme.colorScheme.primary)
            }
        }
        Text(
            text = when (playMode) {
                MusicPlaybackService.MODE_LOOP_LIST -> "列表循环"
                MusicPlaybackService.MODE_LOOP_ONE -> "单曲循环"
                MusicPlaybackService.MODE_SHUFFLE -> "随机播放"
                else -> "顺序播放"
            },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

/** 标签编辑对话框 */
@Composable
private fun EditTagDialog(
    item: AudioItem,
    onDismiss: () -> Unit,
    onSave: (String, String) -> Unit
) {
    var title by remember { mutableStateOf(item.title) }
    var artist by remember { mutableStateOf(item.artist) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑标签") },
        text = {
            Column {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("歌名") },
                    singleLine = true
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = artist,
                    onValueChange = { artist = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("歌手") },
                    singleLine = true
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(title.trim(), artist.trim()) }) { Text("保存") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

/** 网易云歌词搜索对话框（支持翻译） */
@Composable
private fun LyricsSearchDialog(
    title: String,
    onDismiss: () -> Unit,
    onLyricsLoaded: (String, String) -> Unit
) {
    val vm: AppViewModel = viewModel()
    val scope = rememberCoroutineScope()
    var keyword by remember { mutableStateOf(title) }
    var searching by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Pair<String, Long>>>(emptyList()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("搜索歌词") },
        text = {
            Column {
                OutlinedTextField(
                    value = keyword,
                    onValueChange = { keyword = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("歌曲名/关键词") },
                    singleLine = true
                )
                Spacer(Modifier.height(8.dp))
                if (searching) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp))
                        Spacer(Modifier.size(8.dp))
                        Text("搜索中...", style = MaterialTheme.typography.bodySmall)
                    }
                } else if (error.isNotEmpty()) {
                    Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
                if (results.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Column {
                        results.forEach { (name, id) ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        scope.launch {
                                            searching = true
                                            error = ""
                                            val (lrc, tl) = vm.fetchLyricWithTranslation(id)
                                            searching = false
                                            if (lrc.isNotEmpty()) onLyricsLoaded(lrc, tl)
                                            else error = "该歌曲暂无歌词"
                                        }
                                    }
                                    .padding(vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(Icons.Filled.Lyrics, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(Modifier.size(8.dp))
                                Text(name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (keyword.isNotBlank()) {
                    scope.launch {
                        searching = true
                        error = ""
                        results = emptyList()
                        val list = vm.searchLyrics(keyword)
                        searching = false
                        if (list.isEmpty()) error = "未找到匹配歌曲"
                        else results = list
                    }
                }
            }) { Text("搜索") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}
