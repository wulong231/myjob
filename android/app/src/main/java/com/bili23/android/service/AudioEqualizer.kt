package com.bili23.android.service

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.BaseAudioProcessor
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.audio.AudioCapabilities
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin

/** 均衡器频段中心频率（Hz），与桌面版 windows/src/gui/equalizer_dialog.py 对齐 */
val EQ_BAND_FREQS = floatArrayOf(31f, 62f, 125f, 250f, 500f, 1000f, 2000f, 4000f, 8000f, 16000f)

/** 频段显示名 */
val EQ_BAND_LABELS = listOf("31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")

/** 单段增益上下限（dB） */
const val EQ_GAIN_LIMIT = 12

/** 预设曲线（10 段增益，dB），与桌面版一致 */
val EQ_PRESETS: Map<String, List<Int>> = linkedMapOf(
    "平直" to List(EQ_BAND_FREQS.size) { 0 },
    "流行" to listOf(3, 1, 0, 2, 3, 3, 2, 1, 0, 1),
    "摇滚" to listOf(4, 3, 2, -1, -2, 1, 3, 4, 4, 4),
    "古典" to listOf(4, 3, 2, 0, -1, -1, 0, 2, 3, 4),
    "爵士" to listOf(3, 2, 1, 2, -1, -1, 0, 1, 2, 3),
    "电子" to listOf(4, 3, 0, 0, -2, 2, 4, 4, 4, 4),
    "人声" to listOf(-2, -1, 0, 2, 4, 4, 3, 1, 0, -1),
)

/**
 * 10 段均衡器音频处理器：由 10 个 peaking 双二阶滤波器串联实现，
 * 频段与桌面版一致（31Hz~16kHz，±12dB）。
 *
 * - 关闭时直通（仅一次内存拷贝），因此开关可即时生效、无需重建播放器；
 * - 开启时按 -max(0, 最大正增益) 做预衰减，避免大增益导致削波；
 * - 支持 16bit / float PCM（1~8 声道）；flush 时重置滤波器状态。
 */
@OptIn(UnstableApi::class)
class EqualizerAudioProcessor : BaseAudioProcessor() {

    private val bandCount = EQ_BAND_FREQS.size
    private val revision = AtomicInteger(0)

    @Volatile private var enabled = false
    @Volatile private var gainsDb = IntArray(bandCount)

    // 以下字段仅在音频线程访问
    private var appliedRevision = -1
    private var appliedRate = 0
    private var appliedChannels = 0
    private val coeffs = Array(bandCount) { FloatArray(5) } // b0,b1,b2,a1,a2
    private var activeBands = IntArray(0)                   // 增益非零的频段（0dB 段等于直通，跳过）
    private var preamp = 1f
    private var states = emptyArray<FloatArray>()

    /** 由播放服务调用：更新开关与各段增益（dB） */
    fun update(enabled: Boolean, gains: List<Int>) {
        gainsDb = IntArray(bandCount) { i ->
            (gains.getOrNull(i) ?: 0).coerceIn(-EQ_GAIN_LIMIT, EQ_GAIN_LIMIT)
        }
        this.enabled = enabled
        revision.incrementAndGet()
    }

    override fun onConfigure(inputAudioFormat: AudioProcessor.AudioFormat): AudioProcessor.AudioFormat {
        if (inputAudioFormat.encoding != C.ENCODING_PCM_16BIT &&
            inputAudioFormat.encoding != C.ENCODING_PCM_FLOAT
        ) {
            return AudioProcessor.AudioFormat.NOT_SET
        }
        if (inputAudioFormat.channelCount !in 1..8) return AudioProcessor.AudioFormat.NOT_SET
        return inputAudioFormat
    }

    override fun onFlush() {
        clearState()
    }

    override fun onReset() {
        clearState()
        appliedRevision = -1
        appliedRate = 0
        appliedChannels = 0
    }

    private fun clearState() {
        for (s in states) java.util.Arrays.fill(s, 0f)
    }

    override fun queueInput(inputBuffer: ByteBuffer) {
        val size = inputBuffer.remaining()
        if (size == 0) return
        val out = replaceOutputBuffer(size)

        if (!enabled) {
            // 直通：原样拷贝
            out.put(inputBuffer.duplicate())
            inputBuffer.position(inputBuffer.limit())
            out.flip()
            return
        }

        ensureFilters()
        out.order(ByteOrder.LITTLE_ENDIAN)
        val src = inputBuffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
        val channels = appliedChannels
        val isFloat = inputAudioFormat.encoding == C.ENCODING_PCM_FLOAT
        var written: Int
        if (isFloat) {
            val input = src.asFloatBuffer()
            val output = out.asFloatBuffer()
            val frames = input.remaining() / channels
            for (f in 0 until frames) {
                for (c in 0 until channels) {
                    output.put(process(c, input.get() * preamp))
                }
            }
            written = frames * channels * 4
        } else {
            val input = src.asShortBuffer()
            val output = out.asShortBuffer()
            val frames = input.remaining() / channels
            for (f in 0 until frames) {
                for (c in 0 until channels) {
                    val y = process(c, input.get() / 32768f * preamp)
                    output.put((y.coerceIn(-1f, 1f) * 32767f).toInt().toShort())
                }
            }
            written = frames * channels * 2
        }
        inputBuffer.position(inputBuffer.limit())
        out.position(written)
        out.flip()
    }

    /** 逐样本过一遍启用中的滤波器（状态按声道隔离，Transposed DF-II） */
    private fun process(channel: Int, input: Float): Float {
        var y = input
        val st = states[channel]
        val bands = activeBands
        for (i in bands.indices) {
            val b = bands[i]
            val c = coeffs[b]
            val k = b * 2
            val z1 = st[k]
            val z2 = st[k + 1]
            val o = c[0] * y + z1
            st[k] = c[1] * y - c[3] * o + z2
            st[k + 1] = c[2] * y - c[4] * o
            y = o
        }
        return y
    }

    /** 采样率/声道/增益变化时重建系数与状态 */
    private fun ensureFilters() {
        val rev = revision.get()
        val rate = inputAudioFormat.sampleRate
        val channels = inputAudioFormat.channelCount
        if (rev == appliedRevision && rate == appliedRate && channels == appliedChannels) return

        val gains = gainsDb
        val active = ArrayList<Int>(bandCount)
        var maxBoost = 0
        for (b in 0 until bandCount) {
            if (gains[b] != 0) active.add(b)
            if (gains[b] > maxBoost) maxBoost = gains[b]
        }
        activeBands = IntArray(active.size) { active[it] }
        preamp = 10f.pow(-maxBoost / 20f)

        val nyquistLimit = rate * 0.45f
        for (b in 0 until bandCount) {
            val freq = minOf(EQ_BAND_FREQS[b], nyquistLimit).toDouble()
            peaking(coeffs[b], freq, gains[b].toDouble(), rate.toDouble())
        }
        if (states.size != channels) states = Array(channels) { FloatArray(bandCount * 2) }
        else clearState()

        appliedRevision = rev
        appliedRate = rate
        appliedChannels = channels
    }

    /** RBJ peaking 系数（按 a0 归一化）：out = [b0, b1, b2, a1, a2]，Q 取 1.4（约 1 倍频程带宽） */
    private fun peaking(out: FloatArray, freq: Double, gainDb: Double, sampleRate: Double) {
        val q = 1.4
        val a = 10.0.pow(gainDb / 40.0)
        val w0 = 2.0 * PI * freq / sampleRate
        val cosW = cos(w0)
        val alpha = sin(w0) / (2.0 * q)
        val a0 = 1.0 + alpha / a
        out[0] = ((1.0 + alpha * a) / a0).toFloat()
        out[1] = (-2.0 * cosW / a0).toFloat()
        out[2] = ((1.0 - alpha * a) / a0).toFloat()
        out[3] = (-2.0 * cosW / a0).toFloat()
        out[4] = ((1.0 - alpha / a) / a0).toFloat()
    }
}

/** 渲染器工厂：把均衡器处理器注入音频 sink，其余行为与默认实现一致 */
@OptIn(UnstableApi::class)
class EqualizerRenderersFactory(
    context: Context,
    private val processor: AudioProcessor
) : DefaultRenderersFactory(context) {

    override fun buildAudioSink(
        context: Context,
        enableFloatOutput: Boolean,
        enableAudioTrackPlaybackParams: Boolean
    ): AudioSink = DefaultAudioSink.Builder(context)
        .setAudioCapabilities(AudioCapabilities.getCapabilities(context))
        .setAudioProcessors(arrayOf(processor))
        .setEnableFloatOutput(enableFloatOutput)
        .setEnableAudioTrackPlaybackParams(enableAudioTrackPlaybackParams)
        .build()
}
