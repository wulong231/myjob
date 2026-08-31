package com.bili23.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
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
import com.bili23.android.data.FavoriteFolder
import com.bili23.android.data.VideoInfo
import com.bili23.android.data.formatDuration
import com.bili23.android.ui.AppViewModel

/** 我的收藏：展示收藏夹列表，点击查看收藏的视频 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FavoritesScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val folders by vm.favoriteFolders.collectAsState()
    val videos by vm.favoriteVideos.collectAsState()
    val loading by vm.favLoading.collectAsState()
    val loadingMore by vm.favLoadingMore.collectAsState()
    val hasMore by vm.favHasMore.collectAsState()
    var selectedFolder by remember { mutableLongStateOf(-1L) }

    LaunchedEffect(Unit) {
        vm.refreshLoginState()
        vm.loadFavoriteFolders()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("我的收藏") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
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
            if (loading && folders.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                return@Column
            }

            if (folders.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("暂无收藏夹", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                return@Column
            }

            // 收藏夹横向选择
            LazyRow(
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(folders, key = { it.id }) { folder ->
                    FolderChip(
                        folder = folder,
                        selected = folder.id == selectedFolder,
                        onClick = {
                            selectedFolder = folder.id
                            vm.loadFavoriteVideos(folder.id)
                        }
                    )
                }
            }

            // 收藏视频列表
            if (videos.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(bottom = 60.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text("点击上方收藏夹查看视频", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                        start = 16.dp, end = 16.dp, bottom = 16.dp
                    ),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(videos, key = { it.bvid }) { video ->
                        FavoriteVideoItem(video) {
                            navController.navigate("detail/${video.bvid}")
                        }
                    }
                    item {
                        if (loadingMore) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                CircularProgressIndicator(modifier = Modifier.size(24.dp))
                            }
                        } else if (hasMore) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                horizontalArrangement = Arrangement.Center
                            ) {
                                OutlinedButton(onClick = { vm.loadMoreFavoriteVideos() }) {
                                    Text("下一页")
                                }
                            }
                        } else {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    "已加载全部",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FolderChip(folder: FavoriteFolder, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(
                if (selected) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.surfaceVariant
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            Icons.Filled.Favorite,
            contentDescription = null,
            tint = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(16.dp)
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = folder.title,
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = "${folder.mediaCount}",
            style = MaterialTheme.typography.labelSmall,
            color = if (selected) MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.8f)
            else MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun FavoriteVideoItem(video: VideoInfo, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp)
    ) {
        Box {
            AsyncImage(
                model = video.coverUrl,
                contentDescription = video.title,
                modifier = Modifier
                    .width(140.dp)
                    .aspectRatio(16f / 10f)
                    .clip(RoundedCornerShape(8.dp)),
                contentScale = ContentScale.Crop
            )
            if (video.duration > 0) {
                Text(
                    text = formatDuration(video.duration.toLong()),
                    style = MaterialTheme.typography.labelSmall,
                    color = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(4.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.7f))
                        .padding(horizontal = 4.dp, vertical = 1.dp)
                )
            }
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 12.dp)
        ) {
            Text(
                text = video.title,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = video.ownerName,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
        }
        Icon(
            Icons.Filled.PlayArrow,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary
        )
    }
}
