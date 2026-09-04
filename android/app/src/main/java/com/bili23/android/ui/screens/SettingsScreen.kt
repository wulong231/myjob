package com.bili23.android.ui.screens

import com.bili23.android.BuildConfig
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.bili23.android.data.Settings
import com.bili23.android.ui.AppViewModel

@Composable
fun SettingsScreen(vm: AppViewModel = viewModel(), navController: NavHostController? = null) {
    var showThemeDialog by remember { mutableStateOf(false) }
    var showQualityDialog by remember { mutableStateOf(false) }
    var showCookieDialog by remember { mutableStateOf(false) }
    var showLogoutDialog by remember { mutableStateOf(false) }
    var showDirDialog by remember { mutableStateOf(false) }
    val loggedIn by vm.loggedIn.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            com.bili23.android.DrawerMenuButton()
            Text("设置", style = MaterialTheme.typography.headlineSmall)
        }

        Spacer(Modifier.height(16.dp))

        // 账号
        SettingsItem(
            title = if (loggedIn) "B站账号" else "B站登录",
            subtitle = if (loggedIn) (vm.loginUser.collectAsState().value?.name ?: "已登录") else "未登录，点击登录可获取更高画质"
        ) {
            if (loggedIn) showLogoutDialog = true
            else navController?.navigate("login")
        }

        // 主题
        SettingsItem(
            title = "主题模式",
            subtitle = themeName(Settings.themeMode)
        ) { showThemeDialog = true }

        // 默认画质
        SettingsItem(
            title = "默认画质",
            subtitle = com.bili23.android.data.qualityName(Settings.defaultQuality)
        ) { showQualityDialog = true }

        // Cookie（未展示明文，仅提示）
        SettingsItem(
            title = "B站 Cookie",
            subtitle = if (Settings.cookie.isBlank()) "未设置（可选）" else "已设置"
        ) { showCookieDialog = true }

        // 下载目录
        SettingsItem(
            title = "下载目录",
            subtitle = vm.downloadDir.absolutePath
        ) { showDirDialog = true }

        Spacer(Modifier.height(24.dp))
        Text(
            text = "Bili v${BuildConfig.VERSION_NAME} · Android 版",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }

    if (showThemeDialog) {
        SingleChoiceDialog(
            title = "主题模式",
            options = listOf("跟随系统", "浅色", "深色"),
            selectedIndex = Settings.themeMode
        ) { index ->
            Settings.themeMode = index
            showThemeDialog = false
        }
    }

    if (showQualityDialog) {
        val options = com.bili23.android.data.QUALITY_OPTIONS
        val labels = options.map { com.bili23.android.data.qualityName(it) }
        SingleChoiceDialog(
            title = "默认画质",
            options = labels,
            selectedIndex = options.indexOf(Settings.defaultQuality).coerceAtLeast(0)
        ) { index ->
            Settings.defaultQuality = options[index]
            showQualityDialog = false
        }
    }

    if (showDirDialog) {
        var dirName by remember { mutableStateOf(Settings.downloadDirName) }
        AlertDialog(
            onDismissRequest = { showDirDialog = false },
            title = { Text("修改下载目录") },
            text = {
                Column {
                    Text(
                        "输入新的下载目录名（应用私有目录下）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = dirName,
                        onValueChange = { dirName = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("目录名") },
                        singleLine = true
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "修改后将创建新目录，旧目录中的文件不会被移动。",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    vm.changeDownloadDir(dirName)
                    showDirDialog = false
                }) { Text("保存") }
            },
            dismissButton = {
                TextButton(onClick = { showDirDialog = false }) { Text("取消") }
            }
        )
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text("退出登录") },
            text = { Text("确定要退出当前账号吗？") },
            confirmButton = {
                TextButton(onClick = {
                    vm.logout()
                    showLogoutDialog = false
                }) { Text("退出") }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) { Text("取消") }
            }
        )
    }

    if (showCookieDialog) {
        var text by remember { mutableStateOf(Settings.cookie) }
        AlertDialog(
            onDismissRequest = { showCookieDialog = false },
            title = { Text("B站 Cookie（可选）") },
            text = {
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    placeholder = { Text("登录后从浏览器复制 Cookie 粘贴到这里，可提升清晰度上限") },
                    minLines = 3
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    Settings.cookie = text.trim()
                    showCookieDialog = false
                }) { Text("保存") }
            },
            dismissButton = {
                TextButton(onClick = { showCookieDialog = false }) { Text("取消") }
            }
        )
    }
}

@Composable
private fun SettingsItem(title: String, subtitle: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (subtitle.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(
                    subtitle,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun SingleChoiceDialog(
    title: String,
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit
) {
    AlertDialog(
        onDismissRequest = { onSelect(selectedIndex) },
        title = { Text(title) },
        text = {
            Column {
                options.forEachIndexed { index, option ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        RadioButton(
                            selected = index == selectedIndex,
                            onClick = { onSelect(index) }
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(option)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSelect(selectedIndex) }) { Text("取消") }
        }
    )
}

private fun themeName(mode: Int): String = when (mode) {
    1 -> "浅色"
    2 -> "深色"
    else -> "跟随系统"
}
