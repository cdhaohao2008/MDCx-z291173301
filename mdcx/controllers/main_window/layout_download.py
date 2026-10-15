"""设置页的字幕与下载两页布局。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import (
    QPoint,
    Qt,
)
from PyQt6.QtWidgets import (
    QSizePolicy,
)


class LayoutDownloadMixin:
    # 字幕页「添加外挂字幕」组设计几何（MDCx.ui groupBox_45: x30 y310 w701 h425）。
    _ZIMU_BOX_DESIGN_Y = 310
    _ZIMU_BOX_DESIGN_H = 425
    # 字幕页纵向铺排的目标底垫：绿色说明底边与组框底边之间只留 12px，
    # 其余多余底垫删除（绿色说明上提、组框底边同步上收）。
    _ZIMU_TEAL_BOTTOM_PAD = 12

    def _zimu_wide_rows(self, filler: int, teal_h: int):
        """字幕页宽态纵向铺排：各行 y 与组框高（公式化，双向幂等）。

        _sync_zimu_fill_blank（定组框高）与 _sync_zimu_row_align（定各行 y）
        共用同一公式，任一先跑结果一致，不存在“对齐完又被覆盖”。
        铺排：上方网格 4 行各增 unit（unit = filler//8），长按钮下移 5*unit，
        复选框行下移 5*unit + unit//3，绿色说明先按 5*unit + 2*(unit//3)
        铺排、再整体上移 X（删掉下方多余底垫；X 取到底垫只剩 12px 所需量，
        并钳位不越过复选框行），组框高按绿色说明底部贴合
        （box_h = teal_y + teal_h + 12，恒 <= 设计高 + filler）。
        filler <= 0 时 unit/X 自动归零，返回值即设计几何。
        """
        unit = max(0, filler) // 8
        gap = unit // 3
        btn_y = self._ZIMU_BUTTON_DESIGN_Y + 5 * unit
        checks_y = self._ZIMU_CHECKS_DESIGN_Y + 5 * unit + gap
        spread_teal_y = self._ZIMU_TEAL_DESIGN_Y + 5 * unit + 2 * gap
        pad_full = self._ZIMU_BOX_DESIGN_H + filler - (spread_teal_y + teal_h)
        room = max(0, spread_teal_y - (checks_y + 38))
        up = min(max(0, pad_full - self._ZIMU_TEAL_BOTTOM_PAD), room)
        teal_y = spread_teal_y - up
        box_h = min(self._ZIMU_BOX_DESIGN_H + filler, teal_y + teal_h + self._ZIMU_TEAL_BOTTOM_PAD)
        return unit, btn_y, checks_y, teal_y, box_h

    # 组内复选框行 / 绿色说明 label_125 / 长按钮的设计 y（宽态铺排的归位基准）。
    _ZIMU_CHECKS_DESIGN_Y = 272
    _ZIMU_TEAL_DESIGN_Y = 309
    _ZIMU_BUTTON_DESIGN_Y = 220
    # 上方网格容器 gridLayoutWidget_27 的设计高（宽态按行铺排量同步增高）。
    _ZIMU_GRID_DESIGN_H = 186
    # 「点击下载字幕包」（label_download_sub_zip）的文字对齐：恒 AlignLeft|AlignVCenter。
    #
    # 根因（用户截图，最小化态）：该 QLabel 的设计态是 AlignCenter，而它所在的
    # horizontalLayout_10 是「两项均分布局」——窄态下提示文字「下载字幕包解压…」
    # 与链接同行均分，链接格子被拉到 84~250px 宽，格子左缘本就与「视频文件名」
    # （checkBox_filename）左缘同位（同宽时实测 content 坐标都是 433），但居中把
    # 可见文字整体右移了 (格子宽-文字宽)/2（用户环境格子约 200px、文字 105px，
    # 右移约 47px；本仓默认字体下 0~28px 随窗口浮动），于是「点击下载字幕包」
    # 看上去比「视频文件名」右移一大截。改左对齐后，可见文字左缘 == 链接格子
    # 左缘，两行同位时即与「视频文件名」严格上下对齐。
    # 宽态本来就用这个值（见 _sync_zimu_row_align），两态统一后不再有“宽态对、
    # 窄态偏右”的割裂；文字位置以外的任何几何（格子、提示文字、宽态铺排）不动。
    _ZIMU_LINK_ALIGN = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def _sync_zimu_page_align(self, _scroll=None) -> None:
        """设置-字幕：把底部空白收缩 + 行对齐入口整条重跑（钩子用，零参可调）。

        挂在字幕滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「收缩/对齐」在
        同一个事件里做完，中间态（白色填充/右缘控件先被绘制一帧）不会出现。
        休眠页直接返回，由切 tab 的 showEvent 补齐。

        顺序：先 _sync_zimu_fill_blank（它内部会重跑宽幅同步拿到终态，通用
        同步会把右缘锚定的复选框搬回右侧），再 _sync_zimu_row_align（按终态
        几何左移）。顺序颠倒会对齐完又被通用同步覆盖。
        """
        scroll = _scroll if _scroll is not None else getattr(self, "_zimu_scroll", None)
        self._sync_zimu_fill_blank(scroll)
        self._sync_zimu_row_align(scroll)

    def _sync_zimu_fill_blank(self, scroll=None) -> None:
        """设置-字幕：高视口下把组框下方的白色填充收进末尾组框，矮视口不动。

        用户需求：最大化时「添加外挂字幕」组最底部下方有大片白色空白，删除或缩进；
        最小化时界面、布局、控件保持不变；组内控件不移动（只动组框底边）。

        根因：字幕页内容短（groupBox_45 底缘 735，内容最小高 = 735 + 底部余量 72），
        widgetResizable=true 的滚动区在视口更高时把内容拉伸到视口高，多出的部分
        即组框下方的白色填充（1920x1170 下约 380px）；矮窗口视口 < 内容最小高，
        出现垂直滚动条、无填充。

        做法（只改「出现白色填充」的态，其余一个像素都不碰，双向幂等）：
          - 先显式重跑一次宽幅同步拿到终态视口/组框（registry 高度从未改动，
            每次复位回设计值 425，无累积漂移），再算填充
            filler = 视口高 - (组框.y + 设计高) - 底部余量；
          - filler <= 0（矮视口/最小化）直接 return：几何完全交给通用同步；
          - filler > 0：组框高度按 _zimu_wide_rows 公式收缩（x/y/宽不动，
            组间距保持设计值 19 不放大；绿色说明上提、底垫只留 12px，
            删掉的多余底垫转为组框下方的页面底色，纵向不再有单块大空白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_45", None)
        if box is None or not box.isVisibleTo(self):
            return
        if scroll is None:
            scroll = getattr(self, "_zimu_scroll", None)
        if scroll is None:
            return
        if scroll.isVisibleTo(self):
            scroll.sync_wide_children_width()  # 取终态视口与组框，勿量过期几何
        viewport = scroll.viewport()
        if viewport is None:
            return
        margin = scroll.content_bottom_margin()
        filler = viewport.height() - (self._ZIMU_BOX_DESIGN_Y + self._ZIMU_BOX_DESIGN_H) - margin
        if filler <= 0:
            return
        teal = getattr(ui, "label_125", None)
        want_h = self._zimu_wide_rows(filler, teal.height() if teal is not None else 131)[4]
        g = box.geometry()
        if g.y() != self._ZIMU_BOX_DESIGN_Y or g.height() != want_h:
            box.setGeometry(g.x(), self._ZIMU_BOX_DESIGN_Y, g.width(), want_h)
            scroll.sync_content_min_height()

    def _sync_zimu_row_align(self, scroll=None) -> None:
        """设置-字幕：两处控件对齐「视频文件名」——复选框只宽态、下载链接两态都做。

        用户需求（最大化态）：「新添加字幕的视频在结束后重新刮削」
        （checkBox_sub_rescrape）左移到与「视频文件名」（checkBox_filename，
        位置保持不变）左缘上下对齐；「点击下载字幕包」
        （label_download_sub_zip）左移到「视频文件名」下方（左缘同样对齐）。

        用户需求（最小化态）：「点击下载字幕包」也左移到与「视频文件名」严格
        上下对齐，「视频文件名」位置保持不变；最大化时页面、布局、控件、提示
        文字等均保持不变（故宽态分支一字未改）。
        最小化态只需把链接文字从设计态的 AlignCenter 换成 _ZIMU_LINK_ALIGN：
        该行是两项均分布局，窄态下链接格子左缘本就与「视频文件名」左缘同位，
        偏右的全部来自居中（详见 _ZIMU_LINK_ALIGN 处的实测数据）。
        残留残差（不修，几何上无法两全）：「视频文件名」行也是两项均分，其第二项
        起点 = 行首 + 半行宽；下载行第二项起点 = 提示词自然宽 + 间距。窗口够宽
        时两者相等 → 严格对齐（本仓默认字体 Sans Serif 9pt/offscreen 96dpi 实测
        窗口 ≥ 1000px 残差 0，含用户截图的 1014x730）；更窄时提示词宽于半行宽
        （2*228+6 > 行宽），链接格子只能停在提示词右侧，残差 19~49px
        （800/900/950 宽实测 49/44/19）。要消除它只能压窄提示词（用户明确要求
        不动提示词）或让链接压住提示词，故保留残差，由
        tests/test_window_state_matrix.py::test_zimu_download_link_aligns_to_filename_when_narrow
        逐值锁定。

        根因：复选框是 groupBox_45 的直接子项，宽 236 ≥ 内宽一半不成立、右缘
        425+236=661 ≥ 组宽 701*0.9，被通用宽幅同步判为 _DOCK_RIGHT，最大化时
        整体右移到右缘；下载行是横向均分布局，链接位置随列宽漂移。
        上游「视频文件名」行同样是两项均分布局，两列 col0 同为 130，当前恰好
        同位——本方法按活测量的「视频文件名」左缘钉死，不依赖这种巧合。

        做法（只改「页面被拉宽」的态，还原态逐像素复原，双向幂等）：
          - extra <= 0 直接拆除下载行间隔、解除 label_102 钉宽、把链接文字改回
            左对齐、复位复选框行 y 后 return（复选框 x/组框几何由通用同步按设计复位）；
          - extra > 0：以「视频文件名」经公共祖先 content 映射的 x 为基准
            （注：QWidget.mapTo 要求目标是调用者的祖先，跨分支直接映射会
            拿到未定义值，离屏实测恒偏 +302，故一律经 content 中转）；
            复选框 move() 到基准 x（y 按纵向铺排值一并落定，越界则放弃）；
            下载行把 label_102 钉回 sizeHint 宽 + 插入固定间隔把链接推到
            基准 x（只允许左移，右推/放不下则放弃，链接右缘恒等于行右缘）。
            链接 QLabel 设计态是 AlignCenter：格子拉宽后即使左缘对齐，可见
            文字仍居中偏右，故宽态把文字对齐改左（窄态同样保持左对齐，见上）。
          - 纵向均匀铺排（宽态有填充时）：填充量按八等分铺进行内行距——上方
            网格 4 行各增 unit（unit = filler//8），长按钮下移 5*unit，
            复选框行下移 5*unit + unit//3（紧贴长按钮下方，间隙只 +unit//3），
            绿色说明先按 5*unit + 2*(unit//3) 铺排、再整体上提删掉下方多余
            底垫（底边与组框底边只留 12px，钳位不越过复选框行），组框高同步
            收缩；
            组框 y 钉回设计值，组间距保持 19 不放大。任一单块空白
            都不再是“大片”，下半部分相对位置保持紧凑。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_45", None)
        filename = getattr(ui, "checkBox_filename", None)
        rescrape = getattr(ui, "checkBox_sub_rescrape", None)
        add_chs = getattr(ui, "checkBox_sub_add_chs", None)
        teal = getattr(ui, "label_125", None)
        button = getattr(ui, "pushButton_add_sub_for_all_video", None)
        lead = getattr(ui, "label_102", None)
        link = getattr(ui, "label_download_sub_zip", None)
        lay = getattr(ui, "horizontalLayout_10", None)
        grid = getattr(ui, "gridLayout_27", None)
        grid27 = getattr(ui, "gridLayoutWidget_27", None)
        if (
            box is None
            or filename is None
            or rescrape is None
            or add_chs is None
            or teal is None
            or button is None
            or lead is None
            or link is None
            or lay is None
            or grid is None
            or grid27 is None
            or not box.isVisibleTo(self)
        ):
            return
        if scroll is None:
            scroll = getattr(self, "_zimu_scroll", None)
        if scroll is None:
            return
        content = scroll.widget()
        if content is None:
            return
        if self._scroll_stretch_extra(scroll) <= 0:
            # 还原态：清零网格行最小高、拆除下载行间隔、解除前导钉宽、复位复选框
            # 行 y，其余交给通用同步复位。链接文字这里仍钉 _ZIMU_LINK_ALIGN
            # （不再恢复居中）：窄态下格子左缘已与「视频文件名」同位，改左对齐
            # 即让可见文字与它严格上下对齐，且不碰任何控件几何。
            if link.alignment() != self._ZIMU_LINK_ALIGN:
                link.setAlignment(self._ZIMU_LINK_ALIGN)
            if add_chs.y() != self._ZIMU_CHECKS_DESIGN_Y:
                add_chs.move(add_chs.x(), self._ZIMU_CHECKS_DESIGN_Y)
            if any(grid.rowMinimumHeight(r) != 0 for r in range(4)):
                for r in range(4):
                    grid.setRowMinimumHeight(r, 0)
                grid.invalidate()
                grid.activate()
            spacer = self._zimu_dl_spacer
            if spacer is not None and lay.indexOf(spacer) >= 0:
                lay.removeItem(spacer)
                self._zimu_dl_gap = -1
                self._pin_row_lead_width(lead, None)
                lay.invalidate()
                lay.activate()
            elif self._pin_row_lead_width(lead, None):
                lay.invalidate()
                lay.activate()
            return
        # 纵向均匀铺排：先清零行最小高再量设计行高，避免在已铺排几何上累加；
        # 上方网格 4 行各增 unit，长按钮/复选框行/绿色说明整体跟进（下半部分
        # 相对位置保持紧凑，复选框行与绿色说明只比设计间隙多 unit//3）。
        viewport = scroll.viewport()
        filler = 0
        if viewport is not None:
            filler = (
                viewport.height() - (self._ZIMU_BOX_DESIGN_Y + self._ZIMU_BOX_DESIGN_H) - scroll.content_bottom_margin()
            )
        unit, btn_y, checks_y, teal_y, _box_h = self._zimu_wide_rows(filler, teal.height())
        if any(grid.rowMinimumHeight(r) != 0 for r in range(4)):
            for r in range(4):
                grid.setRowMinimumHeight(r, 0)
            grid.invalidate()
            grid.activate()
        if unit > 0:
            for r in range(4):
                grid.setRowMinimumHeight(r, grid.cellRect(r, 1).height() + unit)
            gg = grid27.geometry()
            if gg.height() != self._ZIMU_GRID_DESIGN_H + 4 * unit:
                grid27.setGeometry(gg.x(), gg.y(), gg.width(), self._ZIMU_GRID_DESIGN_H + 4 * unit)
            grid.invalidate()
            grid.activate()
        if button.y() != btn_y:
            button.move(button.x(), btn_y)
        if add_chs.y() != checks_y:
            add_chs.move(add_chs.x(), checks_y)
        if teal.y() != teal_y:
            # label_125 与长按钮是通用同步的 _STRETCH 项：每次重跑都会按设计
            # 几何复位，此处落在终态之后 move，只改 y 不碰宽高。
            teal.move(teal.x(), teal_y)
        # 基准：「视频文件名」左缘（经 content 中转到各坐标系，见 docstring）。
        fn_cx = filename.mapTo(content, QPoint(0, 0)).x()
        # ---- 「新添加字幕…重新刮削」复选框：x 到基准，y 按铺排 ----
        tx_box = fn_cx - box.x()
        if tx_box >= 0 and tx_box + rescrape.width() <= box.width() - 8:
            if rescrape.x() != tx_box or rescrape.y() != checks_y:
                rescrape.move(tx_box, checks_y)
        # ---- 「点击下载字幕包」：钉前导 + 固定间隔，只允许左移 ----
        tx_g27 = fn_cx - box.x() - grid27.x()
        lead_w = lead.sizeHint().width()
        want_gap = tx_g27 - lead.x() - lead_w - lay.spacing()
        ok = want_gap >= 0 and tx_g27 <= link.x() and tx_g27 + link.sizeHint().width() <= grid27.width()
        new_gap = want_gap if ok else 0
        changed = self._pin_row_lead_width(lead, lead_w if ok else None)
        want_align = self._ZIMU_LINK_ALIGN if ok else Qt.AlignmentFlag.AlignCenter
        if link.alignment() != want_align:
            link.setAlignment(want_align)
        spacer = self._zimu_dl_spacer
        if self._zimu_dl_gap != new_gap or spacer is None or lay.indexOf(spacer) != 1:
            if spacer is None or lay.indexOf(spacer) != 1:
                if spacer is not None and lay.indexOf(spacer) >= 0:
                    lay.removeItem(spacer)
                # PyQt6 的 insertSpacing 返回值恒为 None，改插完再 itemAt 取回
                lay.insertSpacing(1, new_gap)
                spacer = lay.itemAt(1)
                self._zimu_dl_spacer = spacer
            if spacer is not None:
                spacer.changeSize(new_gap, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                self._zimu_dl_gap = new_gap
                changed = True
        if not changed:
            return
        lay.invalidate()
        lay.activate()
        ui.gridLayout_27.invalidate()
        ui.gridLayout_27.activate()

    # ============ page_setting / 下载页: 「下载」行钉到「保留旧文件」行同一竖线 ============
    # 逐项对应关系（左=下载行 groupBox_24/horizontalLayoutWidget_14/horizontalLayout_16，
    # 右=保留旧文件行 groupBox_33/horizontalLayoutWidget_18/horizontalLayout_23）。
    # 「压缩」对应「剧照副本」是用户截图红框指定的位置；末项「主题视频」只存在于
    # 保留旧文件行，无对应项。封面图虽是两行共同的首项（x 天然同位），仍列入：
    # 见 _sync_xiazai_row_align 里关于「宽度也要跟」的那段说明。
    _XIAZAI_ROW_ALIGN_PAIRS = (
        ("checkBox_download_poster", "checkBox_old_poster"),
        ("checkBox_download_thumb", "checkBox_old_thumb"),
        ("checkBox_download_fanart", "checkBox_old_fanart"),
        ("checkBox_download_extrafanart", "checkBox_old_extrafanart"),
        ("checkBox_download_trailer", "checkBox_old_trailer"),
        ("checkBox_download_nfo", "checkBox_old_nfo"),
        ("checkBox_compress_downloaded_images", "checkBox_old_extrafanart_copy"),
    )

    def _sync_xiazai_row_align(self, xiazai_scroll=None) -> None:
        """设置-下载：把「下载」行的 7 个复选框逐项钉到「保留旧文件」行的同一竖线。

        用户需求（截图，最小化态）：「下载」行的复选框要向下与「保留旧文件」行
        严格上下对齐；「保留旧文件」行的位置保持不变。最大化态同样要求对齐。
        纵向（y/高）本就一致（实测两行容器在 content 里同 x=90、同高 31、两行
        复选框同高 17），故只重钉 x 与宽。

        根因：两行的容器与内部布局在 .ui 里长得几乎一样（都是
        horizontalLayoutWidget_* + QHBoxLayout），但项数不同——下载行 7 项、
        保留旧文件行 8 项，且第 7 项文案不同（「压缩」对「剧照副本」，其后还有
        「主题视频」）。QBoxLayout 在无 stretch、无 expanding 项时把余量**均分**
        给各项，于是第 k 项左缘 = 行首 + Σ(前 k 项自然宽 + spacing) + k·余量/项数，
        项数少的那一行每一项都落在 8 项那行的右侧。实测逐项偏差（content 坐标，
        离屏、默认 9pt 字体）：窗口 900 宽 +7~+52px、1032 宽 +12~+69px、
        1200 宽 +14~+83px、1500 宽 +20~+115px、1920 宽 +27~+160px——正是截图里
        「越往右偏得越多」的形状。

        为什么宽度也要跟：只 move x 的话，左邻仍停在自己的布局位置上，而它被拉宽
        后的控件里画的是**左对齐**文字——实测窗口 1200 宽时「压缩」被移到 671，
        而它左邻「nfo」的控件在 644、文字画到 687，两者字形直接压在一起（实测
        1200/1500/1920 各压 16~28px）。把宽度也重钉成保留旧文件行的同项宽度后，
        每个控件右缘正好止于下一项左缘（那正是保留旧文件行自身的排布），
        极窄窗口下文字被裁的宽度也与参照行一致，实测各宽度字形重叠恒为 0。

        挂在下载滚动区拉伸之后的钩子上（CustomScrollArea._post_wide_sync_hook）：
        通用拉伸会把两个行容器按「设计宽 + extra」拉宽并 invalidate+activate 重排，
        钩子跑在其后才是终态几何，同拍完成、不会被绘制出中间态。休眠页直接返回
        （量到的是设计态陈旧几何），由切 tab 的 showEvent 补齐。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        scroll = xiazai_scroll if xiazai_scroll is not None else getattr(self, "_xiazai_scroll", None)
        if scroll is None or not scroll.isVisibleTo(self):
            return
        content = scroll.widget()
        if content is None:
            return
        for dl_name, old_name in self._XIAZAI_ROW_ALIGN_PAIRS:
            dl = getattr(ui, dl_name, None)
            old = getattr(ui, old_name, None)
            if dl is None or old is None:
                continue
            # 两个复选框分属两个不同 groupBox，x 必须经公共祖先 content 归一后才能比：
            # QWidget.mapTo 要求目标是调用者的祖先，跨分支直接比 widget.x() 拿到的是
            # 「相对各自行容器」的局部坐标，会把真偏差算成 0（同 verify_actor_mapto）。
            have = dl.mapTo(content, QPoint(0, 0)).x()
            want = old.mapTo(content, QPoint(0, 0)).x()
            old_w = old.width()
            if have == want and dl.width() == old_w:
                continue  # 已对齐（含幂等重跑）：不发任何几何事件
            # 只重钉 x 与宽：y 与高度交给各自布局，跨行控件的纵向关系不动。
            dl.setGeometry(dl.x() + (want - have), dl.y(), old_w, dl.height())
