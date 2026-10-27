package com.bili23.android.service

import android.content.Context
import android.content.Intent

/**
 * 音视频互斥仲裁：音频与视频各自是独立的前台服务，同时播放会互相干扰。
 * 任一方开始播放时，由服务层统一停止另一方（不依赖界面各自调用，覆盖所有入口）。
 */
object MediaArbiter {

    /** 停止音频服务（视频开始播放时调用） */
    fun stopMusic(context: Context) {
        if (!MusicPlaybackService.serviceActive) return
        context.startService(
            Intent(context, MusicPlaybackService::class.java).apply {
                action = MusicPlaybackService.ACTION_STOP
            }
        )
    }

    /** 停止视频服务（音频开始播放时调用） */
    fun stopVideo(context: Context) {
        if (!VideoPlaybackService.serviceActive) return
        context.startService(
            Intent(context, VideoPlaybackService::class.java).apply {
                action = VideoPlaybackService.ACTION_STOP
            }
        )
    }
}
