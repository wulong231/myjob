package com.bili23.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import com.bili23.android.data.EpisodeInfo
import com.bili23.android.data.PlayUrl
import com.bili23.android.data.QUALITY_NAMES
import com.bili23.android.data.Settings
import com.bili23.android.data.formatCount
import com.bili23.android.data.formatDuration
import com.bili23.android.ui.AppViewModel
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoDetailScreen(
    navController: NavHostController,
    vm: AppViewModel,
    bvid: String
) {
    val context = LocalContext.current
    val videoInfo by vm.videoInfo.collectAsState()
    val loading by vm.videoLoading.collectAsState()
    val playUrl by vm.playUrl.collectAsState()

    LaunchedEffect(bvid) {
        vm.loadVideoDetail(bvid)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("视频详情") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        when {
            loading && videoInfo == null -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    contentAlignment = Alignment.Center
                ) { CircularProgressIndicator() }
            }

            videoInfo == null -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    contentAlignment = Alignment.Center
                ) {
                    Text("加载失败", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            else -> {
                val info = videoInfo!!
                var selectedEpisode by remember(info.bvid) { mutableStateOf(info.episodes.firstOrNull()?.page ?: 1) }
                var selectedQuality by remember(info.bvid) { mutableStateOf(Settings.defaultQuality) }
                // 合集多选下载：多选模式下可勾选多个分P批量下载
                var multiMode by remember(info.bvid) { mutableStateOf(false) }
                var selectedEps by remember(info.bvid) { mutableStateOf<Set<Int>>(emptySet()) }
                val scope = rememberCoroutineScope()

                /** 待下载的分P：多选时用勾选集合，否则用当前选中分P */
                fun epsToDownload(): List<EpisodeInfo> {
                    if (multiMode && selectedEps.isNotEmpty())
                        return info.episodes.filter { it.page in selectedEps }
                    return listOfNotNull(info.episodes.firstOrNull { it.page == selectedEpisode })
                }

                Column(modifier = Modifier.fillMaxSize().padding(padding)) {
                    LazyColumn(modifier = Modifier.weight(1f)) {
                        item {
                            AsyncImage(
                                model = info.coverUrl,
                                contentDescription = info.title,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .aspectRatio(16f / 9f),
                                contentScale = ContentScale.Crop
                            )
                        }
                        item {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = info.title,
                                    style = MaterialTheme.typography.titleLarge,
                                    maxLines = 3,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Spacer(Modifier.height(8.dp))
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    AsyncImage(
                                        model = info.ownerFace,
                                        contentDescription = info.ownerName,
                                        modifier = Modifier
                                            .size(32.dp)
                                            .clip(CircleShape),
                                        contentScale = ContentScale.Crop
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Column {
                                        Text(info.ownerName, style = MaterialTheme.typography.bodyMedium)
                                        Text(
                                            "${info.tname} · ${formatCount(info.views)}播放 · ${formatCount(info.danmaku)}弹幕",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                                if (info.description.isNotBlank()) {
                                    Spacer(Modifier.height(12.dp))
                                    Text(
                                        text = info.description,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 4,
                                        overflow = TextOverflow.Ellipsis
                                    )
                                }
                            }
                        }

                        // 分P选择（支持多选批量下载）
                        if (info.isMultiEpisode) {
                            item {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 16.dp, vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        "选集 (${info.episodes.size})",
                                        style = MaterialTheme.typography.titleMedium,
                                        modifier = Modifier.weight(1f)
                                    )
                                    if (multiMode) {
                                        TextButton(
                                            onClick = {
                                                selectedEps = if (selectedEps.size == info.episodes.size)
                                                    emptySet() else info.episodes.map { it.page }.toSet()
                                            },
                                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                                        ) { Text(if (selectedEps.size == info.episodes.size) "取消全选" else "全选") }
                                        TextButton(
                                            onClick = {
                                                multiMode = false
                                                selectedEps = emptySet()
                                            },
                                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                                        ) { Text("退出", color = MaterialTheme.colorScheme.error) }
                                    } else {
                                        TextButton(
                                            onClick = { multiMode = true },
                                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)
                                        ) { Text("多选") }
                                    }
                                }
                                LazyRow(
                                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                    modifier = Modifier.padding(bottom = 8.dp)
                                ) {
                                    items(info.episodes, key = { it.page }) { ep ->
                                        val selected = if (multiMode) ep.page in selectedEps
                                        else selectedEpisode == ep.page
                                        EpisodeChip(ep, selected) {
                                            if (multiMode) {
                                                selectedEps = if (ep.page in selectedEps) selectedEps - ep.page
                                                else selectedEps + ep.page
                                            } else {
                                                selectedEpisode = ep.page
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // 画质选择
                        item {
                            Text(
                                "画质",
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                            )
                            LazyRow(
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                modifier = Modifier.padding(bottom = 16.dp)
                            ) {
                                items(com.bili23.android.data.QUALITY_OPTIONS) { qn ->
                                    FilterChip(
                                        selected = selectedQuality == qn,
                                        onClick = { selectedQuality = qn },
                                        label = { Text(QUALITY_NAMES[qn] ?: "${qn}P") }
                                    )
                                }
                            }
                        }
                    }

                    // 底部操作栏
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Button(
                            onClick = {
                                val ep = info.episodes.firstOrNull { it.page == selectedEpisode }
                                val cid = ep?.cid ?: 0
                                if (cid > 0) {
                                    scope.launch {
                                        val url = vm.fetchPlayUrl(info.bvid, cid, selectedQuality)
                                        vm.setCurrentPlay(info.bvid, cid, url)
                                        if (url.videoUrl.isNotEmpty()) {
                                            navController.navigate("player")
                                        }
                                    }
                                }
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(Icons.Filled.PlayArrow, contentDescription = null)
                            Spacer(Modifier.width(4.dp))
                            Text("播放")
                        }
                        OutlinedButton(
                            onClick = {
                                val eps = epsToDownload()
                                if (eps.isEmpty()) return@OutlinedButton
                                scope.launch {
                                    android.widget.Toast.makeText(
                                        context,
                                        if (eps.size > 1) "正在获取 ${eps.size} 个视频下载地址..." else "正在获取视频下载地址...",
                                        android.widget.Toast.LENGTH_SHORT
                                    ).show()
                                    var ok = 0
                                    for (ep in eps) {
                                        val url = vm.fetchPlayUrl(info.bvid, ep.cid, selectedQuality)
                                        if (url.videoUrl.isNotEmpty()) {
                                            vm.downloadManager.startDownload(
                                                bvid = info.bvid,
                                                title = info.title,
                                                part = ep.part,
                                                cid = ep.cid,
                                                quality = selectedQuality,
                                                coverUrl = info.coverUrl,
                                                videoUrl = url.videoUrl,
                                                audioUrl = url.audioUrl
                                            )
                                            ok++
                                        }
                                    }
                                    android.widget.Toast.makeText(
                                        context,
                                        if (ok == eps.size) "已开始下载 $ok 个视频，可在下载管理查看"
                                        else "成功 $ok/${eps.size} 个，其余失败",
                                        android.widget.Toast.LENGTH_SHORT
                                    ).show()
                                }
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(Icons.Filled.Download, contentDescription = null)
                            Spacer(Modifier.width(4.dp))
                            Text(if (multiMode && selectedEps.size > 1) "视频(${selectedEps.size})" else "视频")
                        }
                        OutlinedButton(
                            onClick = {
                                val eps = epsToDownload()
                                if (eps.isEmpty()) return@OutlinedButton
                                scope.launch {
                                    android.widget.Toast.makeText(
                                        context,
                                        if (eps.size > 1) "正在获取 ${eps.size} 个音频下载地址..." else "正在获取音频下载地址...",
                                        android.widget.Toast.LENGTH_SHORT
                                    ).show()
                                    var ok = 0
                                    var skipped = 0
                                    for (ep in eps) {
                                        val url = vm.fetchPlayUrl(info.bvid, ep.cid, selectedQuality)
                                        if (url.audioUrl.isNotEmpty()) {
                                            // 双重查重：歌名 + 歌手都相同视为重复，跳过避免重复下载
                                            val dup = vm.findDuplicateAudio(info.title, ep.part)
                                            if (dup != null) {
                                                skipped++
                                                continue
                                            }
                                            vm.downloadManager.downloadAudioOnly(
                                                bvid = info.bvid,
                                                title = info.title,
                                                part = ep.part,
                                                cid = ep.cid,
                                                coverUrl = info.coverUrl,
                                                audioUrl = url.audioUrl,
                                                audioQuality = url.audioQuality
                                            )
                                            ok++
                                        }
                                    }
                                    android.widget.Toast.makeText(
                                        context,
                                        if (skipped > 0) "已开始下载 $ok 个音频，跳过 $skipped 个重复歌曲"
                                        else if (ok == eps.size) "已开始下载 $ok 个音频，可在音频页播放"
                                        else "成功 $ok/${eps.size} 个，其余失败",
                                        android.widget.Toast.LENGTH_SHORT
                                    ).show()
                                }
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(Icons.Filled.MusicNote, contentDescription = null)
                            Spacer(Modifier.width(4.dp))
                            Text(if (multiMode && selectedEps.size > 1) "音频(${selectedEps.size})" else "音频")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun EpisodeChip(ep: EpisodeInfo, selected: Boolean, onClick: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = {
            Column(modifier = Modifier.padding(vertical = 2.dp)) {
                Text(ep.part, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (ep.duration > 0) {
                    Text(
                        formatDuration(ep.duration.toLong()),
                        style = MaterialTheme.typography.labelSmall
                    )
                }
            }
        }
    )
}
