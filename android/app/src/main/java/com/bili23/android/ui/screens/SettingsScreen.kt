package com.bili23.android.ui.screens

import android.content.Intent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.bili23.android.data.AUDIO_QUALITY_AUTO
import com.bili23.android.data.AUDIO_QUALITY_OPTIONS
import com.bili23.android.data.PlaylistTransfer
import com.bili23.android.data.Settings
import com.bili23.android.data.audioQualityName
import com.bili23.android.ui.AppViewModel

@Composable
fun SettingsScreen(vm: AppViewModel = viewModel(), navController: NavHostController? = null) {
    var showThemeDialog by remember { mutableStateOf(false) }
    var showQualityDialog by remember { mutableStateOf(false) }
    var showAudioQualityDialog by remember { mutableStateOf(false) }
    var showCookieDialog by remember { mutableStateOf(false) }
    var showLogoutDialog by remember { mutableStateOf(false) }
    var showDirDialog by remember { mutableStateOf(false) }
    val loggedIn by vm.loggedIn.collectAsState()
    val context = LocalContext.current

    // 导入分类：选择其他手机导出的分类文件，合并到本机（不覆盖已有内容）
    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            val result = PlaylistTransfer.import(context, uri, vm.audioFiles.value)
            Toast.makeText(context, result.message, Toast.LENGTH_LONG).show()
            // 导入可能同步了歌名/歌手，重新扫描以刷新列表显示
            if (result.syncedTags > 0) vm.scanAudioFiles()
        }
    }

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

        // 音频音质
        SettingsItem(
            title = "音频音质",
            subtitle = audioQualityLabel(Settings.audioQuality)
        ) { showAudioQualityDialog = true }

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

        // 分类导入导出：多台手机共享同一套收藏夹
        SettingsItem(
            title = "导出分类",
            subtitle = "生成分类文件，分享给其他手机（微信 / QQ / 蓝牙等）"
        ) {
            runCatching {
                val file = PlaylistTransfer.export(context, vm.audioFiles.value)
                val uri = FileProvider.getUriForFile(
                    context, "${context.packageName}.fileprovider", file
                )
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "application/json"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    putExtra(Intent.EXTRA_SUBJECT, "Bili23 分类备份")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                Toast.makeText(context, "已导出：${file.name}", Toast.LENGTH_LONG).show()
                context.startActivity(Intent.createChooser(send, "导出分类"))
            }.onFailure {
                Toast.makeText(context, "导出失败：${it.message}", Toast.LENGTH_LONG).show()
            }
        }

        SettingsItem(
            title = "导入分类",
            subtitle = "选择其他手机导出的分类文件，合并到本机收藏夹"
        ) {
            importLauncher.launch(arrayOf("application/json", "text/plain", "*/*"))
        }

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

    if (showAudioQualityDialog) {
        val options = listOf(AUDIO_QUALITY_AUTO) + AUDIO_QUALITY_OPTIONS
        val labels = options.map { audioQualityLabel(it) }
        SingleChoiceDialog(
            title = "音频音质",
            options = labels,
            selectedIndex = options.indexOf(Settings.audioQuality).coerceAtLeast(0)
        ) { index ->
            Settings.audioQuality = options[index]
            showAudioQualityDialog = false
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

/** 音频音质文案：无损/杜比标注需大会员（杜比另受机型解码限制） */
private fun audioQualityLabel(value: Int): String = when (value) {
    AUDIO_QUALITY_AUTO -> "自动（无损优先）"
    30251 -> "Hi-Res 无损（需大会员）"
    30250 -> "杜比全景声（需大会员，依机型）"
    else -> audioQualityName(value)
}
