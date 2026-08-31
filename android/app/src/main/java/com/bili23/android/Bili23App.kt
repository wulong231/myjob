package com.bili23.android

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.bili23.android.data.BiliApi
import com.bili23.android.data.Settings
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** 应用入口：配置 Coil 图片加载器（带 B 站 UA/Referer，解决封面不显示问题） */
class Bili23App : Application(), ImageLoaderFactory {

    override fun onCreate() {
        super.onCreate()
        Settings.init(this)
    }

    override fun newImageLoader(): ImageLoader {
        val okHttp = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .addInterceptor { chain ->
                val req = chain.request().newBuilder()
                    .header("User-Agent", BiliApi.USER_AGENT)
                    .header("Referer", "https://www.bilibili.com/")
                    .build()
                chain.proceed(req)
            }
            .build()

        return ImageLoader.Builder(this)
            .okHttpClient(okHttp)
            .crossfade(true)
            .build()
    }
}
