package com.bili23.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Audiotrack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PlaylistPlay
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.bili23.android.data.Settings
import com.bili23.android.ui.AppViewModel
import com.bili23.android.ui.Bili23Theme
import com.bili23.android.ui.screens.AudioPlayerScreen
import com.bili23.android.ui.screens.DownloadsScreen
import com.bili23.android.ui.screens.FavoritesScreen
import com.bili23.android.ui.screens.HomeScreen
import com.bili23.android.ui.screens.LocalVideoScreen
import com.bili23.android.ui.screens.LoginScreen
import com.bili23.android.ui.screens.PlaylistDetailScreen
import com.bili23.android.ui.screens.PlaylistsScreen
import com.bili23.android.ui.screens.SearchScreen
import com.bili23.android.ui.screens.SettingsScreen
import com.bili23.android.ui.screens.VideoDetailScreen
import com.bili23.android.ui.screens.VideoPlayerScreen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        Settings.init(applicationContext)
        setContent {
            Bili23Theme {
                AppRoot()
            }
        }
    }
}

/** 全局侧边栏控制器：任意页面可调用 [open] 打开抽屉 */
object DrawerController {
    var open: (() -> Unit)? = null
}

/** 全屏状态控制器：视频全屏时禁用全局左划菜单 */
object FullscreenController {
    var isFullscreen by androidx.compose.runtime.mutableStateOf(false)
}

/** 页面顶部菜单按钮（打开侧边栏） */
@Composable
fun DrawerMenuButton() {
    IconButton(onClick = { DrawerController.open?.invoke() }) {
        Icon(Icons.Filled.Menu, contentDescription = "菜单")
    }
}

@Composable
private fun AppRoot(vm: AppViewModel = viewModel()) {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val loggedIn by vm.loggedIn.collectAsState()

    DrawerController.open = { scope.launch { drawerState.open() } }

    val bottomRoutes = setOf("home", "search", "local_videos", "downloads", "audio", "settings")
    val showBottomBar = currentRoute in bottomRoutes

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = !FullscreenController.isFullscreen,
        drawerContent = {
            AppDrawer(navController, drawerState, loggedIn)
        }
    ) {
        Scaffold(
            bottomBar = {
                if (showBottomBar) {
                    BottomBar(navController, currentRoute)
                }
            }
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = "home",
                modifier = Modifier.padding(padding),
                enterTransition = {
                    fadeIn(tween(250)) +
                        slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Start, tween(350))
                },
                exitTransition = {
                    fadeOut(tween(180)) +
                        slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Start, tween(250))
                },
                popEnterTransition = {
                    fadeIn(tween(250)) +
                        slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.End, tween(350))
                },
                popExitTransition = {
                    fadeOut(tween(180)) +
                        slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.End, tween(250))
                }
            ) {
                composable("home") { HomeScreen(navController, vm) }
                composable("search") { SearchScreen(navController, vm) }
                composable("downloads") { DownloadsScreen(navController, vm) }
                composable("audio") { AudioPlayerScreen(vm) }
                composable("settings") { SettingsScreen(vm, navController) }
                composable("login") { LoginScreen(navController, vm) }
                composable("local_videos") { LocalVideoScreen(navController, vm) }
                composable("playlists") { PlaylistsScreen(navController, vm) }
                composable("playlist/{type}/{name}") { entry ->
                    val type = entry.arguments?.getString("type") ?: ""
                    val name = entry.arguments?.getString("name") ?: ""
                    PlaylistDetailScreen(navController, vm, type, name)
                }
                composable("favorites") { FavoritesScreen(navController, vm) }
                composable("detail/{bvid}") { entry ->
                    val bvid = entry.arguments?.getString("bvid") ?: ""
                    VideoDetailScreen(navController, vm, bvid)
                }
                composable("player") {
                    VideoPlayerScreen(navController, vm)
                }
            }
        }
    }
}

@Composable
private fun AppDrawer(
    navController: NavHostController,
    drawerState: androidx.compose.material3.DrawerState,
    loggedIn: Boolean
) {
    val scope = rememberCoroutineScope()
    fun navigate(route: String) {
        scope.launch { drawerState.close() }
        navController.navigate(route) {
            popUpTo(navController.graph.startDestinationId) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    ModalDrawerSheet {
        Text(
            "Bili",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 16.dp)
        )
        HorizontalDivider()
        DrawerItem(Icons.Filled.Home, "首页") { navigate("home") }
        DrawerItem(Icons.Filled.Search, "搜索视频") { navigate("search") }
        DrawerItem(Icons.Filled.Movie, "本地视频") { navigate("local_videos") }
        DrawerItem(Icons.Filled.Audiotrack, "音频播放") { navigate("audio") }
        DrawerItem(Icons.Filled.PlaylistPlay, "播放列表") { navigate("playlists") }
        DrawerItem(Icons.Filled.Download, "下载管理") { navigate("downloads") }
        if (loggedIn) {
            DrawerItem(Icons.Filled.Favorite, "我的收藏") { navigate("favorites") }
        }
        DrawerItem(Icons.Filled.Settings, "设置") { navigate("settings") }
    }
}

@Composable
private fun DrawerItem(icon: ImageVector, label: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 24.dp, vertical = 14.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
    ) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        androidx.compose.foundation.layout.Spacer(Modifier.padding(12.dp))
        Text(label, style = MaterialTheme.typography.bodyLarge)
    }
}

private data class BottomItem(val route: String, val label: String, val icon: ImageVector)

private val bottomItems = listOf(
    BottomItem("home", "首页", Icons.Filled.Home),
    BottomItem("search", "搜索", Icons.Filled.Search),
    BottomItem("local_videos", "视频", Icons.Filled.Movie),
    BottomItem("downloads", "下载", Icons.Filled.Download),
    BottomItem("audio", "音频", Icons.Filled.Audiotrack),
    BottomItem("settings", "设置", Icons.Filled.Settings),
)

@Composable
private fun BottomBar(navController: NavHostController, currentRoute: String?) {
    NavigationBar {
        bottomItems.forEach { item ->
            NavigationBarItem(
                selected = currentRoute == item.route,
                onClick = {
                    navController.navigate(item.route) {
                        popUpTo(navController.graph.startDestinationId) { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                },
                icon = { Icon(item.icon, contentDescription = item.label) },
                label = { Text(item.label) }
            )
        }
    }
}
