package com.bili23.android.ui.components

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.lazy.grid.LazyGridState
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

/** 拖拽重排状态：长按拖动项时按指针悬停位置实时交换顺序（拖拽项实时跟随指针）。支持单列列表与多列网格。 */
class DragDropListState(private val gridState: LazyGridState) {
    var onMove: (Int, Int) -> Unit = { _, _ -> }
    var draggingItemIndex by mutableIntStateOf(-1)
        private set

    /** 开始拖拽指定项 */
    fun onDragStart(index: Int) {
        draggingItemIndex = index
    }

    /** 拖拽中：pointerX/YInItem 为指针相对被拖项左上角的偏移，换算为网格坐标定位目标项并交换（二维命中，多列网格正确换行） */
    fun onDrag(pointerXInItem: Float, pointerYInItem: Float) {
        if (draggingItemIndex == -1) return
        val item = gridState.layoutInfo.visibleItemsInfo.firstOrNull { it.index == draggingItemIndex }
            ?: return
        val gridX = item.offset.x + pointerXInItem
        val gridY = item.offset.y + pointerYInItem
        val target = gridState.layoutInfo.visibleItemsInfo.firstOrNull {
            gridX >= it.offset.x && gridX <= it.offset.x + it.size.width &&
                gridY >= it.offset.y && gridY <= it.offset.y + it.size.height
        }
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
    listState: LazyGridState,
    onMove: (Int, Int) -> Unit
): DragDropListState {
    val state = remember { DragDropListState(listState) }
    val currentOnMove by rememberUpdatedState(onMove)
    state.onMove = currentOnMove
    return state
}

/**
 * 项内拖拽手柄修改器：仅多选模式启用。
 * 长按项最右侧（手柄区域，默认 44dp）拖动即可重排；index/rowWidthPx 需用实时取值 lambda 传入。
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
                state.onDrag(change.position.x, change.position.y)
            },
            onDragEnd = { state.onDragStop() },
            onDragCancel = { state.onDragStop() }
        )
    }
}
