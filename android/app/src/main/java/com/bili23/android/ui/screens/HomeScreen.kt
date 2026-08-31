package com.bili23.android.ui.screens

import androidx.compose.foundation.Image
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Audiotrack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Login
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import com.bili23.android.ui.AppViewModel

@Composable
fun HomeScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    val stats by vm.homeStats.collectAsState()
    val loggedIn by vm.loggedIn.collectAsState()
    val user by vm.loginUser.collectAsState()

    LaunchedEffect(Unit) {
        vm.refreshHomeStats()
        vm.refreshLoginState()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        // 标题 + 登录
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            com.bili23.android.DrawerMenuButton()
            Column(modifier = Modifier.weight(1f)) {
                Text("Bili", style = MaterialTheme.typography.headlineMedium)
                Text(
                    "哔哩哔哩下载器",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            // 登录状态
            if (loggedIn) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.primaryContainer)
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    if (user?.face?.isNotEmpty() == true) {
                        AsyncImage(
                            model = user?.face,
                            contentDescription = null,
                            modifier = Modifier
                                .size(24.dp)
                                .clip(CircleShape)
                        )
                    }
                    Spacer(Modifier.width(6.dp))
                    Text(
                        user?.name ?: "已登录",
                        style = MaterialTheme.typography.labelMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            } else {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .clickable { navController.navigate("login") }
                        .background(MaterialTheme.colorScheme.primary)
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    Icon(
                        Icons.Filled.Login,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(Modifier.width(4.dp))
                    Text("登录", color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }

        Spacer(Modifier.height(16.dp))

        // 统计卡片
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    "下载统计",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Spacer(Modifier.height(12.dp))
                Row(modifier = Modifier.fillMaxWidth()) {
                    StatBlock(
                        modifier = Modifier.weight(1f),
                        icon = Icons.Filled.Movie,
                        value = "${stats.videoCount}",
                        label = "视频",
                        iconColor = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                    StatBlock(
                        modifier = Modifier.weight(1f),
                        icon = Icons.Filled.Audiotrack,
                        value = "${stats.audioCount}",
                        label = "音频",
                        iconColor = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                    StatBlock(
                        modifier = Modifier.weight(1f),
                        icon = Icons.Filled.Download,
                        value = stats.formatSize(),
                        label = "占用空间",
                        iconColor = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            }
        }

        Spacer(Modifier.height(16.dp))

        // 快捷入口
        Text("快捷入口", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Search,
                label = "搜索视频",
                onClick = { navController.navigate("search") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true } }
            )
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Movie,
                label = "本地视频",
                onClick = { navController.navigate("local_videos") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true; restoreState = true } }
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Audiotrack,
                label = "音频播放",
                onClick = { navController.navigate("audio") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true } }
            )
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Download,
                label = "下载管理",
                onClick = { navController.navigate("downloads") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true } }
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Favorite,
                label = "我的收藏",
                onClick = { navController.navigate("favorites") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true; restoreState = true } }
            )
            QuickEntry(
                modifier = Modifier.weight(1f),
                icon = Icons.Filled.Settings,
                label = "设置",
                onClick = { navController.navigate("settings") { popUpTo(navController.graph.startDestinationId) { saveState = true }; launchSingleTop = true } }
            )
        }

        Spacer(Modifier.height(16.dp))
        Text(
            "提示：登录后可获取更高的清晰度，下载的音频可在“音频”页面播放。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun StatBlock(
    modifier: Modifier,
    icon: ImageVector,
    value: String,
    label: String,
    iconColor: Color
) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, contentDescription = null, tint = iconColor, modifier = Modifier.size(28.dp))
        Spacer(Modifier.height(6.dp))
        Text(value, style = MaterialTheme.typography.titleMedium, color = iconColor, maxLines = 1)
        Text(label, style = MaterialTheme.typography.labelSmall, color = iconColor.copy(alpha = 0.8f))
    }
}

@Composable
private fun QuickEntry(
    modifier: Modifier,
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    enabled: Boolean = true
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .background(
                if (enabled) MaterialTheme.colorScheme.surfaceVariant
                else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            )
            .padding(vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            icon,
            contentDescription = label,
            tint = if (enabled) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
            modifier = Modifier.size(30.dp)
        )
        Spacer(Modifier.height(6.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = if (enabled) MaterialTheme.colorScheme.onSurface
            else MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
