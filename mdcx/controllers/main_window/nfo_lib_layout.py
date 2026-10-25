"""NFO 资料库页面的布局。纯 Qt, 不依赖任何业务模块。"""

import traceback

from PyQt6.QtCore import (
    QPoint,
    Qt,
)
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QFormLayout,
    QWidget,
)

from mdcx.config.manager import manager
from mdcx.signals import signal_qt


class NfoLibLayoutMixin:
    # 议题 #117：信息管理页「简介/标签」多行框的设计高度（.ui 中 min=max=60）。
    # 视口放不下整表时按缺口压缩这两个框，压缩下限 40（再矮就没法看内容，
    # 宁可保留滚动条）。
    _NFO_LIB_FIELD_FULL_H = 60
    _NFO_LIB_FIELD_MIN_H = 40
    # 最大化时「简介/标签」多行框吸收视口富余高度的上限。再高就会把两行
    # 内容拉成一大片空白（1440p 上尤其明显），超出部分留在表单下方。
    _NFO_LIB_FIELD_MAX_H = 300

    def _sync_nfo_lib_action_buttons(self) -> None:
        """复位「批量保存」「保存当前nfo文件」的宽度上限，并把「裁剪封面」对齐批量保存的高度。

        三按钮 3:4:3 的宽度由三栏 stretch 保证（init 里 3:4:3，三按钮各自铺满
        所在栏）；这里解除可能残留的 maximumWidth 限制，让它们重新铺满所在
        边框（groupBox / 表单跨列区域 / 预览栏）。「裁剪封面」改用批量保存同款
        样式后，把高度对齐，保证上下留白一致（y 对齐见 _sync_nfo_lib_action_row）。
        """
        ui = self.Ui
        batch = ui.pushButton_nfo_lib_batch_save
        for button in (batch, ui.pushButton_nfo_lib_save):
            button.setMinimumWidth(0)
            if button.maximumWidth() != QWIDGETSIZE_MAX:
                button.setMaximumWidth(QWIDGETSIZE_MAX)
            owner = button.parentWidget()
            if owner is not None and owner.layout() is not None:
                owner.layout().invalidate()
                owner.layout().activate()
        # 「裁剪封面」与「批量保存」同高：批量保存的固定高度来自 minimumHeight 36
        height = max(batch.minimumHeight(), batch.sizeHint().height())
        crop = ui.pushButton_nfo_lib_crop
        if crop.minimumHeight() != height:
            crop.setMinimumHeight(height)

    def _sync_nfo_lib_batch_status(self) -> None:
        """状态 label 空文本时不占位（批量处理没在跑时白占一整行 + 6px 间隔）。

        写法文本有三处（`_run_batch` 开始 / `on_nfo_lib_batch_progress` 进度 /
        `on_nfo_lib_batch_done` 完成），一律走 `_set_nfo_lib_batch_status`，布局
        同步时本方法再兜一遍，两边谁先写都不会失配。"""
        status = self.Ui.label_nfo_lib_batch_status
        want = bool(status.text().strip())
        if status.isHidden() == want:  # 显隐与内容不符才动，避免每遍无谓触发布局
            status.setVisible(want)

    def _set_nfo_lib_batch_status(self, text: str) -> None:
        """写批量操作状态文本并立刻同步显隐。

        `QLabel` 没有 `textChanged` 信号，无法像 `QLineEdit` 那样挂连接，只能由
        写入方自己调一次；统一走这里，免得漏掉某条写入路径。"""
        self.Ui.label_nfo_lib_batch_status.setText(text)
        self._sync_nfo_lib_batch_status()

    def _sync_nfo_lib_batch_panel(self) -> None:
        """让「批量操作」分组贴着内容收紧，省下的高度让给上方的 NFO 列表。

        现象（用户截图）：「批量保存」上方的用法提示是 wordWrap 的说明 label，
        .ui 给它钉了 64px 硬下限，但文字在左栏实际宽度下只要 3 行，文字底下空出
        一片；再叠上恒定占位的空状态 label（空文本也占 14px + 6px 间隔），分组底边
        比实际内容高出约 40px，NFO 列表被白白压矮。

        做法：
        1. 提示 label 的下限改成「真实字体在当前宽度下折行后的实测高」
           （heightForWidth）。下限正是撑开 wordWrap 的唯一机制，不能直接删成 0
           ——v2.2.x 加 64px 就是为了防 Windows 字体/DPI 缩放下末行被裁；改为按
           实测高度给，既不留空白也不会裁字。
        2. 空状态 label 隐藏（见 _sync_nfo_lib_batch_status）。

        实测高度必须运行时按当前字体算，不能写死常数：offline/离屏环境没有中文字体，
        heightForWidth 会明显低估；同一份代码在 Windows 正常字体下折行数就不同。

        1 里那三行「置 0 → 量 → 写回」不能省：`QLabel::heightForWidth` 会被
        `minimumHeight` 钳住（下限 64 时它就返回 64），不先归零量到的永远是旧下限。

        分组是 nfo_lib_list_layout 末位、列表是 Expanding，故省下的高度会自动回到
        listWidget_nfo_lib，本方法不必再手动搬运。"""
        ui = self.Ui
        hint = ui.label_nfo_lib_batch_hint
        self._sync_nfo_lib_batch_status()
        for _ in range(3):  # 「量宽→改下限」最多三轮：宽度变了下一轮量到新值
            width = hint.width()
            if width <= 0:
                return
            previous = hint.minimumHeight()
            hint.setMinimumHeight(0)  # 绕开旧下限，纯量文字真正需要多高
            needed = hint.heightForWidth(width)
            hint.setMinimumHeight(needed if needed > 0 else previous)
            if hint.minimumHeight() == previous:
                return

    def _on_nfo_lib_batch_toggled(self, on: bool) -> None:
        """「批量操作」分组标题勾选框：展开 / 折叠分组内容。

        .ui 把分组声明成 checkable + unchecked，本意是默认折叠；但 pyuic6 在子控件
        建好之前就调了 setCheckable / setChecked，Qt 当时无子控件可管，分组就从未
        真正折叠过——只剩 unchecked 自带的「子控件全 disabled」效果：控件灰着，却照
        样占满 200 多 px 高度。

        这里把 toggled 接成真正的折叠：收起时藏起全部直属子控件（含状态行，文本保留，
        分组只剩标题栏约 40px，省下的高度回到 NFO 列表），展开时恢复。Qt 自己管
        enabled（勾选自动 enable、去勾自动 disable），与这里的显隐管理不冲突。
        展开时状态行（label_nfo_lib_batch_status）不由这里定显隐：它空文本时本来就
        该藏，统一交给 _sync_nfo_lib_batch_status 按文本说了算。"""
        box = self.Ui.groupBox_nfo_lib_batch
        status = self.Ui.label_nfo_lib_batch_status
        if on:
            for child in box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if child is status:
                    continue
                child.setVisible(True)
            self._sync_nfo_lib_batch_status()  # 状态行按有没有文本单独定
            # 刚展开：先强制走一遍分组布局让宽度就位，再按当前宽度重算 hint 下限
            layout = box.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            self._sync_nfo_lib_batch_panel()
        else:
            for child in box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                child.setVisible(False)
            # 折叠分支同样要先落定 grid：隐藏子控件只抛 LayoutRequest，grid 缓存的
            # 还是旧最小高；若直接排外层，activate 会按旧值排，分组高度卡住不收
            # （实测 enframed：minHint 已是 32，高度仍冻在 226）。必须先 invalidate
            # 再 activate，把 grid 的最小高同步刷掉，外层才能按新值分配。
            grid = box.layout()
            if grid is not None:
                grid.invalidate()
                grid.activate()
        # 子控件显隐只 post LayoutRequest 不标脏布局，此时直接 activate 会因布局仍是
        # clean 而返回 False 无所作为（实测）；必须先 invalidate 再 activate，才能同步
        # 重排，让高度在分组与列表之间立刻重新分配（窗口未 show 时尤其靠这一步）。
        outer = box.parentWidget()
        if outer is not None and outer.layout() is not None:
            outer.layout().invalidate()
            outer.layout().activate()
        self._sync_nfo_lib_action_row()  # 展开/折叠改了左按钮底边，按钮行重对齐
        if getattr(self, "_nfo_lib_batch_ready", False):
            # 用户亲手勾选/去勾：记入配置文件，重启恢复。初始化恢复期间不写盘
            # （Init_Singal 里 _nfo_lib_batch_ready 置 False，避免启动就无谓落盘）。
            try:
                manager.config.nfo_lib_batch_expanded = on
                manager.save()
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _sync_nfo_lib_action_row(self) -> None:
        """让「批量保存 / 保存当前nfo文件 / 裁剪封面」三按钮底边严格对齐。

        三按钮分属三列不同容器（左分组 grid / 中表单末行 / 右预览 VBox），列等高
        但各自内容高度不同，天然 y 各异（实测 1030×700：600 / 629 / 478）。又不能
        靠拉伸表单去凑——`test_minimized_layout_untouched_and_restores` 把非最大化态
        简介/标签锁死 60px，表单内容该多高就多高，谁都别去动它。

        做法：以「保存当前nfo文件」底边为基准，左列分组下方、右列裁剪封面下方各垫
        一个间隙 widget（.ui 里的 widget_nfo_lib_left_gap / widget_nfo_lib_preview_gap，
        默认高 0），把左按钮和裁剪封面顶到与基准同一高度。间隙必须按增量式重算
        （新间隙 = 旧间隙 + 当前底边 − 基准）：直接按「当前底边 − 基准」绝对值写会在
        0 与目标值之间来回振荡（实测三遍同步：0 → 11 → 0），因为量到的底边本身已
        经含了旧间隙的贡献。负值钳 0（例如表单内容超出视口被滚走时）。
        宽度 3:4:3 由三栏 stretch 保证，高度 36 由 _sync_nfo_lib_action_buttons
        保证，这里只管 y 对齐。

        折叠态（分组未勾选）下批量保存藏着，左间隙归零；但右间隙照样按基准
        重算——右列海报/缩略图 stretch 会吸走富余高度把裁剪封面顶下去，不垫的
        话裁剪封面与保存按钮错开（需求：勾不勾选都必须水平对齐）。
        必须跑在 _sync_nfo_lib_batch_panel 之后——hint 下限变化会改分组高，进而改
        左按钮底边，排前面量到的是旧值（见 _sync_page_layouts 调用序）。
        """
        ui = self.Ui
        left_gap = ui.widget_nfo_lib_left_gap
        preview_gap = ui.widget_nfo_lib_preview_gap
        content = ui.nfo_lib_content
        if content.height() <= 0:
            return
        origin = QPoint(0, 0)
        if not ui.groupBox_nfo_lib_batch.isChecked():
            # 折叠态：只归零左间隙，右间隙继续按下走主分支同样的增量重算。
            if left_gap.height() != 0:
                left_gap.setFixedHeight(0)
            # 先落定一次再量：间隙变化只抛 LayoutRequest，此时量到的是旧几何。
            layout = content.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            ref = ui.pushButton_nfo_lib_save.mapTo(content, origin).y() + ui.pushButton_nfo_lib_save.height()
            crop_bottom = ui.pushButton_nfo_lib_crop.mapTo(content, origin).y() + ui.pushButton_nfo_lib_crop.height()
            preview_want = max(0, preview_gap.height() + (crop_bottom - ref))
            if preview_gap.height() != preview_want:
                preview_gap.setFixedHeight(preview_want)
            layout = content.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            return
        # 先落定一次再量：排在前面的 _sync_nfo_lib_batch_panel 刚改过 hint 下限，
        # 只调了 setMinimumHeight（只抛 LayoutRequest），此时量到的是旧几何。
        layout = content.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        ref = ui.pushButton_nfo_lib_save.mapTo(content, origin).y() + ui.pushButton_nfo_lib_save.height()
        left_bottom = (
            ui.pushButton_nfo_lib_batch_save.mapTo(content, origin).y() + ui.pushButton_nfo_lib_batch_save.height()
        )
        crop_bottom = ui.pushButton_nfo_lib_crop.mapTo(content, origin).y() + ui.pushButton_nfo_lib_crop.height()
        left_want = max(0, left_gap.height() + (left_bottom - ref))
        if left_gap.height() != left_want:
            left_gap.setFixedHeight(left_want)
        preview_want = max(0, preview_gap.height() + (crop_bottom - ref))
        if preview_gap.height() != preview_want:
            preview_gap.setFixedHeight(preview_want)
        layout = content.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

    def _sync_nfo_lib_preview_pixmaps(self, force: bool = False) -> None:
        """海报/缩略图预览按 label 当前边界等比缩放（图片贴边、保持长宽比）。

        载图处（on_nfo_lib_data_loaded / _refresh_nfo_lib_previews）只存原图
        （_nfo_lib_poster_pix / _nfo_lib_thumb_pix），这里按 label.contentsRect()
        的实时尺寸 KeepAspectRatio 重缩放：窗口变化后 label 变大变小，图片都
        重新贴边；QLabel 自己不会跟几何重缩放，以前载图时按固定 200×280 /
        200×120 缩一次就不管了，窗口一变图片就贴不上边。
        原图为空（无图）时不动 label，占位文字由载图处负责。
        平时只在目标尺寸变化时 setPixmap，避免每遍同步都重设引发闪烁/重排；
        但载入新图后必须传 force=True：不同番号的封面常是同一长宽比（FC2
        归档里多为 1:1），缩放到同一个预览框后尺寸完全一致，只比尺寸会误判
        「图没变」而不 setPixmap，表现为切换番号后仍显示上一张封面/缩略图。
        跑在 _sync_page_layouts 末尾（预览与按钮行无关，排最后即可），载图后
        也调一次让新图立刻贴边。
        """
        for pix, label in (
            (self._nfo_lib_poster_pix, self.Ui.label_nfo_lib_poster_preview),
            (self._nfo_lib_thumb_pix, self.Ui.label_nfo_lib_thumb_preview),
        ):
            if pix is None or pix.isNull():
                continue
            size = label.contentsRect().size()
            if size.width() <= 0 or size.height() <= 0:
                continue
            scaled = pix.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            current = label.pixmap()
            if force or current is None or current.isNull() or current.size() != scaled.size():
                label.setPixmap(scaled)

    def _nfo_lib_form_rows(self) -> list[tuple[QWidget | None, QWidget | None]]:
        """列出信息管理表单 QFormLayout 每一行的 (标签控件, 字段控件)。

        第 15 行「保存当前nfo文件」是跨列按钮，只有字段没有标签。
        """
        layout = self.Ui.formLayout_nfo_lib
        rows: list[tuple[QWidget | None, QWidget | None]] = []
        for row in range(layout.rowCount()):
            label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field_item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            rows.append(
                (
                    label_item.widget() if label_item is not None else None,
                    field_item.widget() if field_item is not None else None,
                )
            )
        return rows

    def _pin_nfo_lib_form_rows(self, pinned: bool) -> None:
        """钉住/还原信息管理表单各行的最大高度（最大化时消除行间空白）。

        现象：窗口最大化后内容 widget 被拉高到视口高，QFormLayout 把多出来的
        高度平均分给所有「还能长高」的行——单行输入框的 sizeHint 只有 22px，
        分到的却是 54px，于是每一行下面凭空多出约一行宽的空白（用户截图：
        发行日/年份之间）。

        做法：除「简介/标签」两个多行框外，把每行控件的最大高度钉到各自自然
        高（sizeHint 与 minimumHeight 取大者，保存按钮 36px 不受影响），富余
        高度就只会流向那两个多行框，行距回到设计的 4px。
        pinned=False 时按钉住前记下的值原样还原，最小化态布局不受影响。
        """
        flex_fields = (
            self.Ui.plainTextEdit_nfo_lib_outline,
            self.Ui.plainTextEdit_nfo_lib_tag,
        )
        saved: dict = self.__dict__.setdefault("_nfo_lib_row_max_heights", {})
        if not pinned and not saved:
            return
        for label, field in self._nfo_lib_form_rows():
            if field in flex_fields:
                continue
            for widget in (label, field):
                if widget is None:
                    continue
                if not pinned:
                    widget.setMaximumHeight(saved.pop(widget, QWIDGETSIZE_MAX))
                    continue
                if widget not in saved:
                    saved[widget] = widget.maximumHeight()
                natural = max(widget.sizeHint().height(), widget.minimumHeight())
                widget.setMaximumHeight(natural)

    def _sync_nfo_lib_form_fields(self) -> None:
        """小窗时压缩信息管理页「简介/标签」高度，让保存按钮免滚动可见（议题 #117）。

        现象：窗口缩到默认尺寸以下时，15 行表单 + 底部余量总高超出滚动视口，
        出现垂直滚动条，「保存当前nfo文件」被推到视口外，用户以为按钮丢了。
        做法：按视口可用高动态定这两个多行框的高——全高放得下就保持设计高
        （最小化时布局完全不变），放不下就按缺口在两个框之间等分压缩，
        最低压到 _NFO_LIB_FIELD_MIN_H。

        最大化时额外消除行间空白（见 _pin_nfo_lib_form_rows）：各行钉到自然高，
        视口的富余高度全部交给「简介/标签」两个多行框（各自封顶
        _NFO_LIB_FIELD_MAX_H），超出封顶的部分留在表单下方而不是摊到行间。
        """
        ui = self.Ui
        scroll = ui.scrollArea_nfo_lib_form
        content = ui.scrollAreaWidgetContents_nfo_lib
        layout = content.layout()
        viewport_h = scroll.viewport().height()
        if layout is None or viewport_h <= 0:
            return
        boxes = (ui.plainTextEdit_nfo_lib_outline, ui.plainTextEdit_nfo_lib_tag)
        full = self._NFO_LIB_FIELD_FULL_H
        floor = self._NFO_LIB_FIELD_MIN_H

        def apply_box_height(height: int) -> int:
            """把两个多行框钉到 height，返回整表紧凑排布所需高（含底部余量）。"""
            for box in boxes:
                box.setMinimumHeight(height)
                box.setMaximumHeight(height)
            layout.invalidate()
            layout.activate()
            content.updateGeometry()
            return layout.sizeHint().height() + scroll.content_bottom_margin()

        maxed = self.isMaximized()
        self._pin_nfo_lib_form_rows(maxed)
        if not maxed:
            content.setMaximumHeight(QWIDGETSIZE_MAX)

        base = apply_box_height(full)
        deficit = base - viewport_h
        if deficit > 0:
            # 缺口在两个框之间均摊（向上取整保证压够），并守住可读下限
            shrink = min(-(-deficit // len(boxes)), full - floor)
            if shrink > 0:
                apply_box_height(full - shrink)
        elif maxed:
            slack = viewport_h - base
            grow = min(slack // len(boxes), self._NFO_LIB_FIELD_MAX_H - full)
            if grow > 0:
                apply_box_height(full + grow)
            if slack > 2 * grow:
                # 两框已到封顶高度：把内容 widget 也钉到紧凑高，富余高度留在
                # 表单下方（否则 QFormLayout 会把它摊回行间，行距又不紧凑了）
                content.setMaximumHeight(layout.sizeHint().height() + scroll.content_bottom_margin())
                layout.invalidate()
                layout.activate()
                content.updateGeometry()
        scroll.sync_content_min_height()
