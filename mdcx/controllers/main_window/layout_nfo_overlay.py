"""NFO 编辑器覆盖层与主窗 NFO 面板的几何计算。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
)


class LayoutNfoOverlayMixin:
    # 议题 #154：「编辑 NFO」覆盖层内容区字段最小高度（设计值）
    _NFO_EDITOR_TEXT_MIN_H = 150
    _NFO_EDITOR_TAG_MIN_H = 100
    _NFO_COMMA_HINT = "多个以逗号隔开"
    _NFO_OVERLAY_X = 8
    _NFO_OVERLAY_Y = 0
    _NFO_OVERLAY_MARGIN = 12
    _NFO_OVERLAY_BTN_W = 91
    _NFO_OVERLAY_BTN_H = 40
    _NFO_OVERLAY_BTN_GAP = 108
    _NFO_OVERLAY_BAR_H = 50
    _NFO_OVERLAY_TREE_GAP = 8
    # 整体高度缩减量的固定回退值（行高累加失败时才用）：35px
    _NFO_OVERLAY_H_TRIM = 35

    def _nfo_fixed_gap_offset(self) -> int | None:
        """底部条上沿在内容区的目标偏移 = 「原简介」行底到「标签」行顶的中点，按行固有高度算死。

        文件行（一般两行）/番号三联行/演员/标题/原标题行/简介框/原简介框的高度都是
        定死的（原生 QTextEdit 的 sizeHint 不随文本变，框高即 minimumHeight），与
        内容区当前尺寸无关——之前探针法首开量的是设计尺寸下的旧几何，第二次才收敛，
        故两次高度不一样。现改累加各行 `max(最小高, sizeHint, 最小sizeHint)` + 行距，
        次次一致。文件标签是 wordWrap 两行，高度随宽度轻微浮动，属唯一近似项。
        任一部件取不到就返回 None，调用方回退固定 trim。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_nfo_editor
        if content.layout() is None:
            return None

        def _row_h(*widgets) -> int | None:
            h = 0
            for w in widgets:
                if w is None:
                    return None
                h = max(h, w.minimumHeight(), w.sizeHint().height(), w.minimumSizeHint().height())
            return h

        rows = (
            (ui.label_381, ui.label_nfo),
            (
                ui.label_360,
                ui.lineEdit_nfo_number,
                ui.label_369,
                ui.comboBox_nfo,
                ui.label_380,
                ui.lineEdit_nfo_year,
            ),
            (ui.label_359, ui.lineEdit_nfo_actor),
            (ui.label_361, ui.lineEdit_nfo_title),
            (ui.label_372, ui.lineEdit_nfo_originaltitle),
            (ui.label_19, ui.textEdit_nfo_outline),
            (ui.label_371, ui.textEdit_nfo_originalplot),
        )
        total = 6  # outer 顶 margin
        for i, r in enumerate(rows):
            if i:
                total += 6  # outer 行距
            h = _row_h(*r)
            if h is None:
                return None
            total += h
        return total + 3  # 到标签行顶的半个行距

    def _ensure_nfo_editor_layout(self) -> None:
        """议题 #154/#166：覆盖层内容区改为行式布局，字段随宽度拉伸。

        .ui 里内容区固定 860×1300、19 个字段按绝对坐标摆放。改为 QVBoxLayout
        + 每行 QHBoxLayout；逗号提示改挂到演员/标签字段，不再占独立行。
        仅首次构建。
        """
        ui = self.Ui
        ui.label_370.hide()
        ui.label_379.hide()
        ui.lineEdit_nfo_actor.setPlaceholderText(self._NFO_COMMA_HINT)
        ui.lineEdit_nfo_actor.setToolTip(self._NFO_COMMA_HINT)
        ui.textEdit_nfo_tag.setPlaceholderText(self._NFO_COMMA_HINT)
        ui.textEdit_nfo_tag.setToolTip(self._NFO_COMMA_HINT)
        content = ui.scrollAreaWidgetContents_nfo_editor
        if content.layout() is not None:
            return
        ui.scrollArea_nfo.set_content_bottom_margin(0)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(9, 6, 9, 12)
        outer.setSpacing(6)

        def _label(text_label):
            text_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_label.setFixedWidth(82)
            return text_label

        def add_full_row(text_label, field) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_label(text_label))
            row.addWidget(field, 1)
            outer.addLayout(row)

        def add_pair_row(l1, f1, l2, f2) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_label(l1))
            row.addWidget(f1, 1)
            row.addWidget(_label(l2))
            row.addWidget(f2, 1)
            outer.addLayout(row)

        def add_triple_row(l1, f1, l2, f2, l3, f3) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            for text_label, field in ((l1, f1), (l2, f2), (l3, f3)):
                row.addWidget(_label(text_label))
                row.addWidget(field, 1)
            outer.addLayout(row)

        add_full_row(ui.label_381, ui.label_nfo)
        add_triple_row(
            ui.label_360,
            ui.lineEdit_nfo_number,
            ui.label_369,
            ui.comboBox_nfo,
            ui.label_380,
            ui.lineEdit_nfo_year,
        )
        add_full_row(ui.label_359, ui.lineEdit_nfo_actor)
        add_full_row(ui.label_361, ui.lineEdit_nfo_title)
        add_full_row(ui.label_372, ui.lineEdit_nfo_originaltitle)
        add_full_row(ui.label_19, ui.textEdit_nfo_outline)
        add_full_row(ui.label_371, ui.textEdit_nfo_originalplot)
        add_full_row(ui.label_362, ui.textEdit_nfo_tag)
        add_pair_row(ui.label_363, ui.lineEdit_nfo_release, ui.label_364, ui.lineEdit_nfo_runtime)
        add_pair_row(ui.label_373, ui.lineEdit_nfo_score, ui.label_374, ui.lineEdit_nfo_wanted)
        add_pair_row(ui.label_366, ui.lineEdit_nfo_director, ui.label_365, ui.lineEdit_nfo_series)
        add_pair_row(ui.label_368, ui.lineEdit_nfo_studio, ui.label_367, ui.lineEdit_nfo_publisher)
        add_full_row(ui.label_375, ui.lineEdit_nfo_poster)
        add_full_row(ui.label_376, ui.lineEdit_nfo_cover)
        add_full_row(ui.label_377, ui.lineEdit_nfo_trailer)
        add_full_row(ui.label_378, ui.lineEdit_nfo_website)
        for box, height in (
            (ui.textEdit_nfo_outline, self._NFO_EDITOR_TEXT_MIN_H),
            (ui.textEdit_nfo_originalplot, self._NFO_EDITOR_TEXT_MIN_H),
            (ui.textEdit_nfo_tag, self._NFO_EDITOR_TAG_MIN_H),
        ):
            box.setMinimumHeight(height)

    def _nfo_overlay_right_edge(self) -> int:
        """覆盖层右缘 = min(缩略图右缘, 结果树左缘 - 间距)，不盖住番号树。"""
        ui = self.Ui
        stacked_x = ui.stackedWidget.x()
        thumb = ui.label_thumb
        tree = ui.treeWidget_number
        thumb_right = stacked_x + thumb.x() + thumb.width()
        tree_left = stacked_x + tree.x()
        return min(thumb_right, tree_left - self._NFO_OVERLAY_TREE_GAP)

    def _sync_nfo_overlay_geometry(self) -> None:
        """议题 #166：覆盖层作为主页伴侣面板，右缘收到缩略图/结果树之间。"""
        ui = self.Ui
        nfo = ui.widget_nfo
        if nfo is None or nfo.isHidden():
            return
        self._ensure_nfo_editor_layout()
        nfo_x, nfo_y, margin = self._NFO_OVERLAY_X, self._NFO_OVERLAY_Y, self._NFO_OVERLAY_MARGIN
        nfo_right = self._nfo_overlay_right_edge()
        nfo_w = max(nfo_right - nfo_x, 280)
        tree_limit = ui.stackedWidget.x() + ui.treeWidget_number.x() - self._NFO_OVERLAY_TREE_GAP
        if nfo_x + nfo_w > tree_limit:
            nfo_w = max(tree_limit - nfo_x, 280)
        max_h = max(self.height() - nfo_y - margin, 300)
        content = ui.scrollAreaWidgetContents_nfo_editor
        lay = content.layout()
        if lay is not None:
            lay.activate()
            content_h = max(lay.sizeHint().height(), 200)
        else:
            content_h = 200
        # 底部条上沿对齐到「原简介/标签」两行正中间：按行固有高度算死（见
        # _nfo_fixed_gap_offset），与内容区当前尺寸无关，首开与之后完全一致。
        # 顶部位置不动；min() 钳窗口上限、下限 280 保极小窗口不塌。
        gap_mid = self._nfo_fixed_gap_offset()
        if gap_mid is not None:
            # 用户目测：中点基础上再上收 9px
            nfo_h = min(29 + gap_mid + self._NFO_OVERLAY_BAR_H - 9, max_h)
        else:
            nfo_h = min(29 + content_h + self._NFO_OVERLAY_BAR_H - self._NFO_OVERLAY_H_TRIM, max_h)
        nfo_h = max(nfo_h, 280)
        nfo.setGeometry(nfo_x, nfo_y, nfo_w, nfo_h)
        btn_w, btn_h, gap, bar_h = (
            self._NFO_OVERLAY_BTN_W,
            self._NFO_OVERLAY_BTN_H,
            self._NFO_OVERLAY_BTN_GAP,
            self._NFO_OVERLAY_BAR_H,
        )
        pair_w = btn_w + gap + btn_w
        save_x = max((nfo_w - pair_w) // 2, 0)
        close_x = save_x + btn_w + gap
        # 两按钮在底部操作条内上下居中（左右位置不变）：条高 50、按钮高 40，上下各留 5px
        btn_y = max(nfo_h - bar_h + (bar_h - btn_h) // 2, 0)
        ui.pushButton_nfo_close.setGeometry(close_x, btn_y, btn_w, btn_h)
        ui.pushButton_nfo_save.setGeometry(save_x, btn_y, btn_w, btn_h)
        ui.pushButton_nfo_save.raise_()
        ui.pushButton_nfo_close.raise_()
        ui.label_save_tips.setGeometry(margin, max(nfo_h - bar_h + (bar_h - 20) // 2, 0), max(save_x - margin, 60), 20)
        ui.label_4.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        ui.label_4.setGeometry(0, 5, nfo_w, ui.label_4.height())
        scroll = ui.scrollArea_nfo
        if scroll is not None:
            scroll.setGeometry(9, 29, max(nfo_w - 9 - margin, 200), max(nfo_h - 29 - bar_h, 200))
