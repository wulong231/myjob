package com.bili23.android.ui.components

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** 拖拽重排状态：长按拖动行时按指针悬停位置实时交换顺序（拖拽项实时跟随指针） */
class DragDropListState(private val listState: LazyListState) {
    var onMove: (Int, Int) -> Unit = { _, _ -> }
    var draggingItemIndex by mutableIntStateOf(-1)
        private set

    /** 开始拖拽指定行 */
    fun onDragStart(index: Int) {
        draggingItemIndex = index
    }

    /** 拖拽中：pointerYInItem 为指针相对被拖行顶部的偏移，换算为列表坐标定位目标行并交换 */
    fun onDrag(pointerYInItem: Float) {
        if (draggingItemIndex == -1) return
        val item = listState.layoutInfo.visibleItemsInfo.firstOrNull { it.index == draggingItemIndex }
            ?: return
        val listY = item.offset + pointerYInItem
        val target = listState.layoutInfo.visibleItemsInfo
            .firstOrNull { listY >= it.offset && listY <= it.offset + it.size }
        if (target != null && target.index != draggingItemIndex) {
            val from = draggingItemIndex
            onMove(from, target.index)
            draggingItemIndex = target.index
        }
    }

    fun onDragStop() {
        draggingItemIndex = -1
    }
}

@Composable
fun rememberDragDropListState(
    listState: LazyListState,
    onMove: (Int, Int) -> Unit
): DragDropListState {
    val state = remember { DragDropListState(listState) }
    val currentOnMove by rememberUpdatedState(onMove)
    state.onMove = currentOnMove
    return state
}

/**
 * 行内拖拽手柄修改器：仅多选模式启用。
 * 长按行最右侧（手柄区域，默认 44dp）拖动即可重排；index/rowWidthPx 需用实时取值 lambda 传入。
 */
fun Modifier.dragReorderHandle(
    state: DragDropListState,
    index: () -> Int,
    enabled: Boolean,
    rowWidthPx: () -> Int,
    handleWidth: Dp = 44.dp
): Modifier {
    if (!enabled) return this
    return this.pointerInput(state) {
        val handlePx = handleWidth.toPx()
        detectDragGesturesAfterLongPress(
            onDragStart = { offset ->
                if (offset.x >= rowWidthPx() - handlePx) {
                    state.onDragStart(index())
                }
            },
            onDrag = { change, _ ->
                change.consume()
                state.onDrag(change.position.y)
            },
            onDragEnd = { state.onDragStop() },
            onDragCancel = { state.onDragStop() }
        )
    }
}
