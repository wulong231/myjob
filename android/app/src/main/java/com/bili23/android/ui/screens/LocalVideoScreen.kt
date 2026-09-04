package com.bili23.android.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import com.bili23.android.data.DownloadTask
import com.bili23.android.data.Settings
import com.bili23.android.ui.AppViewModel
import com.bili23.android.ui.components.CompactIconButton
import com.bili23.android.ui.components.dragReorderHandle
import com.bili23.android.ui.components.rememberDragDropListState
import java.io.File
import java.util.Locale

/** 本地视频播放模块：列出已下载的视频并播放（支持全屏、收藏、多选整理） */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun LocalVideoScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val tasks by vm.downloadManager.tasks.collectAsState()

    // 多选模式
    var selectionMode by remember { mutableStateOf(false) }
    var selectedIds by remember { mutableStateOf<Set<String>>(emptySet()) }
    // 添加到播放列表
    var addToListPath by remember { mutableStateOf<String?>(null) }
    // 多选“加入列表”
    var addSelectedToPlaylist by remember { mutableStateOf(false) }
    // 收藏刷新
    var favTick by remember { mutableStateOf(0) }
    val favPaths = remember(favTick) { Settings.getFavoritePaths() }
    // 播放列表筛选（null = 全部视频，仅视频类型列表）
    var selectedPlaylist by remember { mutableStateOf<String?>(null) }
    var playlistTick by remember { mutableStateOf(0) }
    val playlists = remember(playlistTick) { Settings.getPlaylists(Settings.PLAYLIST_VIDEO) }

    LaunchedEffect(Unit) {
        vm.scanLocalVideos()
    }

    // 已下载视频：以磁盘文件为准（清空下载记录后文件仍显示），任务提供标题等元数据
    val diskVideos by vm.localVideoFiles.collectAsState()
    val taskByPath = remember(tasks) {
        tasks.filter { it.type == DownloadTask.TYPE_VIDEO && it.status == DownloadTask.STATUS_COMPLETED }
            .associateBy { it.filePath }
    }
    val videos = remember(diskVideos, taskByPath) {
        diskVideos.map { path ->
            taskByPath[path] ?: DownloadTask(
                id = "disk_${path.hashCode()}",
                title = File(path).nameWithoutExtension,
                bvid = "",
                cid = 0,
                part = "",
                quality = Settings.defaultQuality,
                status = DownloadTask.STATUS_COMPLETED,
                filePath = path,
                type = DownloadTask.TYPE_VIDEO
            )
        }
    }
    // 应用多选调整过的自定义顺序
    var orderTick by remember { mutableIntStateOf(0) }
    val customOrder = remember(orderTick) { Settings.getCustomOrder(Settings.PLAYLIST_VIDEO) }
    val orderedVideos = remember(videos, customOrder) {
        Settings.reorderByCustom(videos, customOrder) { it.filePath }
    }
    // 当前展示的视频：选中列表时只显示该列表内视频
    val displayVideos = if (selectedPlaylist == null) orderedVideos
    else orderedVideos.filter { Settings.isInPlaylist(Settings.PLAYLIST_VIDEO, selectedPlaylist!!, it.filePath) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (selectionMode) "已选 ${selectedIds.size} 项" else "视频") },
                navigationIcon = {
                    if (selectionMode) {
                        IconButton(onClick = {
                            selectedIds = emptySet()
                            selectionMode = false
                        }) {
                            Icon(Icons.Filled.Delete, contentDescription = "退出多选", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    } else {
                        com.bili23.android.DrawerMenuButton()
                    }
                },
                actions = {
                    if (selectionMode) {
                        TextButton(
                            onClick = {
                                selectedIds = if (selectedIds.size == displayVideos.size)
                                    emptySet() else displayVideos.map { it.id }.toSet()
                            },
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 4.dp)
                        ) { Text("全选", style = MaterialTheme.typography.labelMedium) }
                        TextButton(
                            onClick = { if (selectedIds.isNotEmpty()) addSelectedToPlaylist = true },
                            enabled = selectedIds.isNotEmpty(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 4.dp)
                        ) { Text("加入列表", style = MaterialTheme.typography.labelMedium) }
                        TextButton(
                            onClick = {
                                vm.deleteVideoFiles(selectedIds.mapNotNull { id ->
                                    displayVideos.firstOrNull { it.id == id }?.filePath
                                })
                                selectedIds = emptySet()
                                selectionMode = false
                            },
                            enabled = selectedIds.isNotEmpty(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 4.dp)
                        ) { Text("删除", style = MaterialTheme.typography.labelMedium) }
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            // 播放列表筛选：全部视频 / 各命名列表
            LazyRow(
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                item {
                    FilterChip(
                        selected = selectedPlaylist == null,
                        onClick = { selectedPlaylist = null },
                        label = { Text("全部视频") }
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

            if (displayVideos.isEmpty()) {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        if (selectedPlaylist == null) "暂无本地视频，请先下载" else "该播放列表暂无视频",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )
                }
            } else {
                // 多选拖拽重排（长按行右侧手柄拖动）
                val videoListState = rememberLazyListState()
                val videoDragState = rememberDragDropListState(videoListState) { from, to ->
                    val fromPath = displayVideos.getOrNull(from)?.filePath
                    val toPath = displayVideos.getOrNull(to)?.filePath
                    if (fromPath != null && toPath != null) {
                        vm.moveVideoPath(fromPath, toPath)
                        orderTick++
                    }
                }
                LazyColumn(
                    state = videoListState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    itemsIndexed(displayVideos, key = { _, it -> it.id }) { index, task ->
                    val isChecked = task.id in selectedIds
                    val path = task.filePath
                    val isFav = path in favPaths
                    val localCover = File(path.substringBeforeLast('.') + ".jpg")
                    val currentIndex by rememberUpdatedState(index)
                    var rowWidth by remember { mutableIntStateOf(0) }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .animateItem(placementSpec = tween(150))
                            .onSizeChanged { rowWidth = it.width }
                            .graphicsLayer {
                                val dragged = videoDragState.draggingItemIndex == currentIndex
                                scaleX = if (dragged) 1.02f else 1f
                                scaleY = if (dragged) 1.02f else 1f
                            }
                            .clip(RoundedCornerShape(10.dp))
                            .background(
                                if (selectionMode && isChecked) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                                else MaterialTheme.colorScheme.surfaceVariant
                            )
                            .combinedClickable(
                                onClick = {
                                    if (selectionMode) {
                                        selectedIds = if (isChecked) selectedIds - task.id else selectedIds + task.id
                                    } else {
                                        // 记录当前收藏夹筛选，播放二级界面只显示该夹内视频
                                        vm.playLocalVideo(path, selectedPlaylist)
                                        navController.navigate("player")
                                    }
                                },
                                onLongClick = {
                                    if (!selectionMode) {
                                        selectionMode = true
                                        selectedIds = setOf(task.id)
                                    }
                                }
                            )
                            .dragReorderHandle(videoDragState, { currentIndex }, selectionMode, { rowWidth })
                            .padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (selectionMode) {
                            Checkbox(
                                checked = isChecked,
                                onCheckedChange = {
                                    selectedIds = if (it) selectedIds + task.id else selectedIds - task.id
                                }
                            )
                            Spacer(Modifier.width(4.dp))
                        }
                        // 封面
                        if (localCover.exists()) {
                            AsyncImage(
                                model = localCover,
                                contentDescription = task.title,
                                modifier = Modifier
                                    .width(84.dp)
                                    .height(50.dp)
                                    .clip(RoundedCornerShape(6.dp)),
                                contentScale = ContentScale.Crop
                            )
                        } else {
                            Box(
                                modifier = Modifier
                                    .width(84.dp)
                                    .height(50.dp)
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(MaterialTheme.colorScheme.primaryContainer),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Filled.Movie,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onPrimaryContainer
                                )
                            }
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = task.title,
                                style = MaterialTheme.typography.bodyMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                text = formatFileSize(File(path).length()),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
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
                            CompactIconButton(
                                onClick = {
                                    Settings.setFavorite(path, !isFav)
                                    favTick++
                                },
                                icon = if (isFav) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                                contentDescription = "收藏",
                                tint = if (isFav) MaterialTheme.colorScheme.error
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            CompactIconButton(
                                onClick = { addToListPath = path },
                                icon = Icons.Filled.PlaylistAdd,
                                contentDescription = "加入播放列表"
                            )
                        }
                    }
                }
                }
            }
        }
    }

    // 添加到播放列表对话框（单项）
    addToListPath?.let { path ->
        AddToPlaylistDialog(
            paths = listOf(path),
            type = Settings.PLAYLIST_VIDEO,
            onDismiss = { addToListPath = null },
            onChanged = { playlistTick++ }
        )
    }

    // 多选“加入列表”对话框
    if (addSelectedToPlaylist) {
        AddToPlaylistDialog(
            paths = selectedIds.mapNotNull { id ->
                displayVideos.firstOrNull { it.id == id }?.filePath
            },
            type = Settings.PLAYLIST_VIDEO,
            onDismiss = {
                addSelectedToPlaylist = false
                selectedIds = emptySet()
                selectionMode = false
            },
            onChanged = { playlistTick++ }
        )
    }
}

private fun formatFileSize(bytes: Long): String = when {
    bytes >= 1024L * 1024 * 1024 -> String.format(Locale.ROOT, "%.2f GB", bytes / 1024.0 / 1024 / 1024)
    bytes >= 1024L * 1024 -> String.format(Locale.ROOT, "%.2f MB", bytes / 1024.0 / 1024)
    else -> String.format(Locale.ROOT, "%.1f KB", bytes / 1024.0)
}
