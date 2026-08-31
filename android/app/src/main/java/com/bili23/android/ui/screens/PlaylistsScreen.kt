package com.bili23.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Audiotrack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material.icons.filled.PlaylistPlay
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import com.bili23.android.data.Settings
import com.bili23.android.ui.AppViewModel
import java.io.File
import java.net.URLDecoder
import java.net.URLEncoder

/** 播放列表：视频/音频分节展示，各自独立创建 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistsScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    var refresh by remember { mutableStateOf(0) }
    var showCreateDialog by remember { mutableStateOf(false) }
    val videoPlaylists = remember(refresh) { Settings.getPlaylists(Settings.PLAYLIST_VIDEO) }
    val audioPlaylists = remember(refresh) { Settings.getPlaylists(Settings.PLAYLIST_AUDIO) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("播放列表") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showCreateDialog = true }) {
                        Icon(Icons.Filled.Add, contentDescription = "新建列表")
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                start = 16.dp, end = 16.dp, bottom = 16.dp
            ),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            item {
                Text(
                    "视频列表",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
            if (videoPlaylists.isEmpty()) {
                item {
                    Text(
                        "暂无视频列表，点右上角 + 新建",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                items(videoPlaylists.keys.toList(), key = { "v:$it" }) { name ->
                    PlaylistRow(
                        type = Settings.PLAYLIST_VIDEO,
                        name = name,
                        count = videoPlaylists[name]?.size ?: 0,
                        onClick = {
                            navController.navigate(
                                "playlist/${Settings.PLAYLIST_VIDEO}/${URLEncoder.encode(name, "UTF-8")}"
                            )
                        }
                    )
                }
            }

            item {
                Text(
                    "音频列表",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 16.dp)
                )
            }
            if (audioPlaylists.isEmpty()) {
                item {
                    Text(
                        "暂无音频列表，点右上角 + 新建",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                items(audioPlaylists.keys.toList(), key = { "a:$it" }) { name ->
                    PlaylistRow(
                        type = Settings.PLAYLIST_AUDIO,
                        name = name,
                        count = audioPlaylists[name]?.size ?: 0,
                        onClick = {
                            navController.navigate(
                                "playlist/${Settings.PLAYLIST_AUDIO}/${URLEncoder.encode(name, "UTF-8")}"
                            )
                        }
                    )
                }
            }
        }
    }

    if (showCreateDialog) {
        var name by remember { mutableStateOf("") }
        var type by remember { mutableStateOf(Settings.PLAYLIST_VIDEO) }
        AlertDialog(
            onDismissRequest = { showCreateDialog = false },
            title = { Text("新建播放列表") },
            text = {
                Column {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(
                            selected = type == Settings.PLAYLIST_VIDEO,
                            onClick = { type = Settings.PLAYLIST_VIDEO },
                            label = { Text("视频列表") }
                        )
                        FilterChip(
                            selected = type == Settings.PLAYLIST_AUDIO,
                            onClick = { type = Settings.PLAYLIST_AUDIO },
                            label = { Text("音频列表") }
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = name,
                        onValueChange = { name = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("列表名称") },
                        singleLine = true
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    if (Settings.createPlaylist(type, name)) {
                        showCreateDialog = false
                        refresh++
                    }
                }) { Text("创建") }
            },
            dismissButton = {
                TextButton(onClick = { showCreateDialog = false }) { Text("取消") }
            }
        )
    }
}

@Composable
private fun PlaylistRow(
    type: String,
    name: String,
    count: Int,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            Icons.Filled.PlaylistPlay,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                "$count 项",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (name == Settings.DEFAULT_AUDIO_FAVORITES || name == Settings.DEFAULT_VIDEO_FAVORITES) {
            Text(
                "收藏",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

/** 播放列表详情：展示列表内文件，支持播放全部 / 单项播放 / 移除 / 重命名 / 删除列表 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistDetailScreen(
    navController: NavHostController,
    vm: AppViewModel = viewModel(),
    type: String,
    encodedName: String
) {
    val name = remember(encodedName) { URLDecoder.decode(encodedName, "UTF-8") }
    val audioFiles by vm.audioFiles.collectAsState()
    val tasks by vm.downloadManager.tasks.collectAsState()
    var refresh by remember { mutableStateOf(0) }
    var showRenameDialog by remember { mutableStateOf(false) }
    var showDeleteDialog by remember { mutableStateOf(false) }
    val items = remember(refresh) { Settings.getPlaylistItems(type, name) }

    LaunchedEffect(Unit) {
        vm.scanAudioFiles()
        vm.scanDiskDownloads()
    }

    // 分类：仅保留磁盘上仍存在的文件
    val audioExt = setOf("mp3", "m4a", "flac", "wav", "aac", "ogg", "opus")
    val videoExt = setOf("mp4", "m4v", "mkv", "webm")
    val audioItems = items.filter { File(it).exists() && it.substringAfterLast('.').lowercase() in audioExt }
    val videoItems = items.filter { File(it).exists() && it.substringAfterLast('.').lowercase() in videoExt }

    val audioMap = audioFiles.associateBy { it.path }
    fun audioTitle(p: String) = audioMap[p]?.displayTitle ?: File(p).name.substringBeforeLast('.')
    fun videoTitle(p: String) = tasks.firstOrNull { it.filePath == p }?.title ?: File(p).name.substringBeforeLast('.')

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showRenameDialog = true }) {
                        Icon(Icons.Filled.Edit, contentDescription = "重命名")
                    }
                    IconButton(onClick = { showDeleteDialog = true }) {
                        Icon(Icons.Filled.Delete, contentDescription = "删除列表", tint = MaterialTheme.colorScheme.error)
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // 播放全部
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                if (audioItems.isNotEmpty()) {
                    Button(
                        onClick = { vm.playAudioPlaylist(audioItems, 0) },
                        modifier = Modifier.weight(1f)
                    ) {
                        Icon(Icons.Filled.PlaylistPlay, contentDescription = null)
                        Spacer(Modifier.width(4.dp))
                        Text("播放全部音频")
                    }
                }
                if (videoItems.isNotEmpty()) {
                    OutlinedButton(
                        onClick = {
                            vm.setVideoQueue(videoItems, 0)
                            navController.navigate("player")
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Icon(Icons.Filled.PlaylistPlay, contentDescription = null)
                        Spacer(Modifier.width(4.dp))
                        Text("播放全部视频")
                    }
                }
            }

            if (items.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("列表为空", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                        start = 16.dp, end = 16.dp, bottom = 16.dp
                    ),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    items(items, key = { it }) { path ->
                        val isVideo = path.substringAfterLast('.').lowercase() in videoExt
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(MaterialTheme.colorScheme.surfaceVariant)
                                .clickable {
                                    if (isVideo) {
                                        val idx = videoItems.indexOf(path).coerceAtLeast(0)
                                        vm.setVideoQueue(videoItems, idx)
                                        navController.navigate("player")
                                    } else {
                                        val idx = audioItems.indexOf(path).coerceAtLeast(0)
                                        vm.playAudioPlaylist(audioItems, idx)
                                    }
                                }
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            if (!isVideo) {
                                val a = audioMap[path]
                                if (a?.coverPath?.isNotEmpty() == true) {
                                    AsyncImage(
                                        model = File(a.coverPath),
                                        contentDescription = null,
                                        modifier = Modifier.size(36.dp).clip(RoundedCornerShape(6.dp)),
                                        contentScale = ContentScale.Crop
                                    )
                                } else {
                                    Icon(Icons.Filled.Audiotrack, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                                }
                            } else {
                                Icon(Icons.Filled.Movie, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                            }
                            Spacer(Modifier.width(10.dp))
                            Text(
                                text = if (isVideo) videoTitle(path) else audioTitle(path),
                                style = MaterialTheme.typography.bodyMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f)
                            )
                            IconButton(onClick = {
                                Settings.removeFromPlaylist(type, name, path)
                                refresh++
                            }) {
                                Icon(Icons.Filled.Delete, contentDescription = "移出列表", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
    }

    if (showRenameDialog) {
        var newName by remember { mutableStateOf(name) }
        AlertDialog(
            onDismissRequest = { showRenameDialog = false },
            title = { Text("重命名列表") },
            text = {
                OutlinedTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("新名称") },
                    singleLine = true
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (Settings.renamePlaylist(type, name, newName)) {
                        showRenameDialog = false
                        navController.popBackStack()
                    }
                }) { Text("保存") }
            },
            dismissButton = {
                TextButton(onClick = { showRenameDialog = false }) { Text("取消") }
            }
        )
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("删除列表") },
            text = { Text("确定删除列表“$name”吗？\n仅删除列表，不会删除已下载的文件。") },
            confirmButton = {
                TextButton(onClick = {
                    Settings.deletePlaylist(type, name)
                    showDeleteDialog = false
                    navController.popBackStack()
                }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) { Text("取消") }
            }
        )
    }
}

/**
 * 加入播放列表对话框（支持批量）：
 * 勾选/取消列表，可新建列表；列表按类型（视频/音频）独立。
 */
@Composable
fun AddToPlaylistDialog(
    paths: List<String>,
    type: String,
    onDismiss: () -> Unit,
    onChanged: () -> Unit = {}
) {
    var refresh by remember { mutableStateOf(0) }
    var showCreate by remember { mutableStateOf(false) }
    val playlists = remember(refresh) { Settings.getPlaylists(type) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("加入播放列表") },
        text = {
            Column {
                if (playlists.isEmpty()) {
                    Text(
                        "暂无${if (type == Settings.PLAYLIST_VIDEO) "视频" else "音频"}列表\n点下方“新建列表”创建",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )
                } else {
                    playlists.keys.forEach { name ->
                        val allIn = paths.isNotEmpty() && paths.all { Settings.isInPlaylist(type, name, it) }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    if (allIn) Settings.removeAllFromPlaylist(type, name, paths)
                                    else Settings.addAllToPlaylist(type, name, paths)
                                    refresh++
                                    onChanged()
                                }
                                .padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                if (allIn) Icons.Filled.CheckCircle else Icons.Filled.PlaylistAdd,
                                contentDescription = null,
                                tint = if (allIn) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.width(8.dp))
                            Text(
                                name,
                                style = MaterialTheme.typography.bodyMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f)
                            )
                            if (allIn) {
                                Text("已全部加入", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { showCreate = true }) { Text("新建列表") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("完成") }
        }
    )

    if (showCreate) {
        var n by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("新建${if (type == Settings.PLAYLIST_VIDEO) "视频" else "音频"}列表") },
            text = {
                OutlinedTextField(
                    value = n,
                    onValueChange = { n = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("列表名称") },
                    singleLine = true
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    val trimmed = n.trim()
                    if (Settings.createPlaylist(type, trimmed)) {
                        Settings.addAllToPlaylist(type, trimmed, paths)
                        showCreate = false
                        refresh++
                        onChanged()
                    }
                }) { Text("创建") }
            },
            dismissButton = {
                TextButton(onClick = { showCreate = false }) { Text("取消") }
            }
        )
    }
}
