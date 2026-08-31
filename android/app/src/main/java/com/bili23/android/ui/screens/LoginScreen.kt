package com.bili23.android.ui.screens

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.filled.QrCode
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.bili23.android.ui.AppViewModel
import kotlinx.coroutines.launch
import com.bili23.android.ui.QrCodeHelper

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(navController: NavHostController, vm: AppViewModel = viewModel()) {
    var tabIndex by remember { mutableIntStateOf(0) }
    val qrLogin by vm.qrLogin.collectAsState()
    val qrStatus by vm.qrStatus.collectAsState()

    var qrBitmap by remember { mutableStateOf<Bitmap?>(null) }

    // 二维码 URL → Bitmap
    LaunchedEffect(qrLogin?.url) {
        qrBitmap = qrLogin?.url?.let { QrCodeHelper.generate(it) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("B站登录") },
                navigationIcon = {
                    IconButton(onClick = {
                        vm.stopQrPoll()
                        navController.popBackStack()
                    }) {
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
            TabRow(selectedTabIndex = tabIndex) {
                Tab(
                    selected = tabIndex == 0,
                    onClick = { tabIndex = 0 },
                    text = { Text("二维码登录") }
                )
                Tab(
                    selected = tabIndex == 1,
                    onClick = { tabIndex = 1 },
                    text = { Text("Cookie登录") }
                )
            }

            when (tabIndex) {
                0 -> QrLoginTab(vm = vm, qrBitmap = qrBitmap, qrStatus = qrStatus)
                else -> CookieLoginTab(vm = vm)
            }
        }
    }
}

@Composable
private fun QrLoginTab(
    vm: AppViewModel,
    qrBitmap: Bitmap?,
    qrStatus: String
) {
    LaunchedEffect(Unit) {
        vm.startQrLogin()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            "请使用B站APP扫描二维码登录",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(20.dp))

        Box(
            modifier = Modifier
                .size(240.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center
        ) {
            if (qrBitmap != null) {
                Image(
                    bitmap = qrBitmap!!.asImageBitmap(),
                    contentDescription = "登录二维码",
                    modifier = Modifier
                        .size(220.dp)
                        .padding(10.dp),
                    contentScale = ContentScale.Fit
                )
            } else {
                Text(
                    qrStatus.ifBlank { "正在获取二维码..." },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        Spacer(Modifier.height(16.dp))
        Text(
            qrStatus,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary
        )
        Spacer(Modifier.height(12.dp))
        Button(onClick = {
            vm.stopQrPoll()
            vm.startQrLogin()
        }) {
            Text("刷新二维码")
        }
        Spacer(Modifier.height(8.dp))
        Text(
            "提示：登录后可下载 1080P 及更高画质",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun CookieLoginTab(vm: AppViewModel) {
    var cookieText by remember { mutableStateOf(vm.loginUser.value?.let { "" } ?: "") }
    var errorMsg by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        Text(
            "从浏览器登录 bilibili.com 后，复制 Cookie 粘贴到这里",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(
            value = cookieText,
            onValueChange = { cookieText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Cookie") },
            placeholder = { Text("SESSDATA=xxx; bili_jct=xxx; ...") },
            minLines = 4
        )
        if (errorMsg.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(errorMsg, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = {
                val err = vm.loginWithCookie(cookieText.trim())
                errorMsg = err
                if (err.isEmpty()) {
                    vm.stopQrPoll()
                    vm.refreshLoginState()
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("使用 Cookie 登录")
        }
        Spacer(Modifier.height(16.dp))
        Text(
            "获取 Cookie 方法：\n1. 电脑浏览器登录 bilibili.com\n2. 按 F12 打开开发者工具\n3. 切换到 Network 面板，刷新页面\n4. 任选一个请求，复制请求头中的 Cookie 值",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
