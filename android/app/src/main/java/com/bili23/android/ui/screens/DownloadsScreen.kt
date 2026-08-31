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
import androidx.compose.material.icons.filled.Audiotrack
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import com.bili23.android.data.DownloadTask
import com.bili23.android.data.qualityName
import com.bili23.android.ui.AppViewModel

@Composable
fun DownloadsScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val tasks by vm.downloadManager.tasks.collectAsState()
    var filter by remember { mutableIntStateOf(0) } // 0=全部 1=视频 2=音频
    var showClearDialog by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        vm.scanDiskDownloads()
        vm.scanAudioFiles()
    }

    val filtered = when (filter) {
        1 -> tasks.filter { it.type == DownloadTask.TYPE_VIDEO }
        2 -> tasks.filter { it.type == DownloadTask.TYPE_AUDIO }
        else -> tasks
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // 标题栏 + 清空历史
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 4.dp, top = 16.dp, end = 16.dp, bottom = 0.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            com.bili23.android.DrawerMenuButton()
            Text(
                text = "下载管理",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.weight(1f)
            )
            IconButton(onClick = { showClearDialog = true }) {
                Icon(
                    Icons.Filled.DeleteSweep,
                    contentDescription = "清空历史记录",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        // 分类筛选
        Row(
            modifier = Modifier.padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            FilterChip(selected = filter == 0, onClick = { filter = 0 }, label = { Text("全部") })
            FilterChip(selected = filter == 1, onClick = { filter = 1 }, label = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.VideoLibrary, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("视频")
                }
            })
            FilterChip(selected = filter == 2, onClick = { filter = 2 }, label = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Audiotrack, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("音频")
                }
            })
        }

        Spacer(Modifier.height(8.dp))

        if (filtered.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无下载记录", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    start = 16.dp, end = 16.dp, bottom = 16.dp
                ),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(filtered, key = { it.id }) { task ->
                    DownloadTaskItem(
                        task = task,
                        onPlay = {
                            if (task.type == DownloadTask.TYPE_VIDEO) {
                                vm.setLocalPlayPath(task.filePath)
                                navController.navigate("player")
                            } else {
                                vm.playLocalAudio(task.filePath)
                                navController.navigate("audio")
                            }
                        }
                    )
                }
            }
        }
    }

    if (showClearDialog) {
        AlertDialog(
            onDismissRequest = { showClearDialog = false },
            title = { Text("清空历史记录") },
            text = { Text("确定要清空所有下载历史记录吗？\n仅清空记录，不会删除已下载的文件。") },
            confirmButton = {
                TextButton(onClick = {
                    vm.downloadManager.clearHistory()
                    showClearDialog = false
                }) { Text("清空") }
            },
            dismissButton = {
                TextButton(onClick = { showClearDialog = false }) { Text("取消") }
            }
        )
    }
}

@Composable
private fun DownloadTaskItem(
    task: DownloadTask,
    onPlay: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .padding(12.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (task.coverUrl.isNotEmpty()) {
                AsyncImage(
                    model = task.coverUrl,
                    contentDescription = task.title,
                    modifier = Modifier
                        .width(72.dp)
                        .height(45.dp)
                        .clip(RoundedCornerShape(6.dp)),
                    contentScale = ContentScale.Crop
                )
            } else {
                Box(
                    modifier = Modifier
                        .width(72.dp)
                        .height(45.dp)
                        .clip(RoundedCornerShape(6.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        if (task.type == DownloadTask.TYPE_VIDEO) Icons.Filled.VideoLibrary else Icons.Filled.Audiotrack,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
            }
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = task.title,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = if (task.type == DownloadTask.TYPE_VIDEO) {
                        "${qualityName(task.quality)} · ${task.part}"
                    } else {
                        "音频 · ${task.part}"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (task.status == DownloadTask.STATUS_COMPLETED) {
                IconButton(onClick = onPlay) {
                    Icon(
                        Icons.Filled.PlayArrow,
                        contentDescription = "播放",
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        when (task.status) {
            DownloadTask.STATUS_COMPLETED -> {
                Text(
                    text = "已完成 · 点击播放",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable(onClick = onPlay)
                )
            }

            DownloadTask.STATUS_FAILED -> {
                Text(
                    text = "失败：${task.error}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.error
                )
            }

            DownloadTask.STATUS_MERGING -> {
                Text(
                    text = "合并中…",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            else -> {
                LinearProgressIndicator(
                    progress = { task.progress },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp))
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = "${(task.progress * 100).toInt()}%",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}
