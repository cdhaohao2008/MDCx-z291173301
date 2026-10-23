"""布局总入口 _sync_page_layouts 以及高级设置页 / 站点偏好区的布局。调用顺序是有语义的, 见 _sync_page_layouts 内的说明注释。"""

from PyQt6.QtCore import (
    QEventLoop,
    QPoint,
    QTimer,
)
from PyQt6.QtWidgets import (
    QApplication,
    QSizePolicy,
)

from mdcx.views.CustomClass import CustomScrollArea


class LayoutMasterMixin:
    def _sync_page_layouts(self) -> None:
        """让所有页面的内部组件跟随主窗口尺寸缩放。

        窗口右侧 stackedWidget resizeEvent 同步，但子页面（page_setting里的tabWidget、
        page_tool的自定义区域、page_net的textBrowser），仅需位置在绝对坐标系下按比例还原。
        方法：基于主窗口追加 (210,6) → 用处当前发扬的尺寸作为基准，对元素调用一次 setGeometry。
        每个组件保留最初设计偏移 (X, Y)，仅需对宽 高 按比例缩放。
        """
        ui = self.Ui
        # stackedWidget 可用宽高（扣除侧栏和上下间距）
        avail_w = max(self.width() - 210 - 2, 400)
        avail_h = max(self.height() - self._CONTENT_TOP_OFFSET - self._CONTENT_BOTTOM_MARGIN, 300)

        # 关键前置：QStackedWidget 只 resize 当前可见页，休眠页永远停留在设计尺寸。
        # 必须先把所有页面统一 resize 到 stackedWidget 尺寸，后续基于 page.width()/height()
        # 的计算才有正确基准（否则"先缩放窗口再切页"时全部按设计尺寸 820x692 布局）。
        # Windows 原生边框最大化时，对带 QLayout 页面的 resize 可能因窗口重建事件
        # 时序错过布局更新（议题 #78：信息管理页右侧残留 ~194px 空白、底部控件坠落
        # 视野）——resize 后对每页布局显式 invalidate + activate 强制重排。
        stacked = ui.stackedWidget
        for index in range(stacked.count()):
            page = stacked.widget(index)
            page.resize(avail_w, avail_h)
            layout = page.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

        # ============ page_main（软件界面）：横向 + 纵向跟随 ============
        # 设计基准宽 820：宽幅控件拉伸贴右缘、右缘锚定控件保持宽度平移、其余保持原位。
        main_page = ui.page_main
        main_w = main_page.width()
        # 幂等：基于设计基准 820 的 cover_scale（全函数共用，须在统计栏/封面段前计算）
        cover_scale = main_w / 820
        # 宽幅拉伸（设计右缘≈页面右缘）：文件路径标签、分隔线
        ui.label_file_path.resize(max(main_w - 34, 300), ui.label_file_path.height())
        ui.line_14.resize(max(main_w - 49, 300), ui.line_14.height())
        # 右缘锚定（结果树宽随 cover_scale 拉伸贴向缩略图右缘、右缘贴齐页面右 18px；
        # 议题 #173：固定 202 宽在最大化时离缩略图过远，改随窗口拉伸、两态间距一致）
        tree_w = max(int(202 * cover_scale), 202)
        ui.pushButton_start_cap.move(max(main_w - 120 - 20, 20), 13)
        # 统计标签最大化时左对齐到结果树左缘、贴到「成功」列正上方（此前右对齐会停在
        # 树右上角、与「成功」错位）；纵向两态同高、始终贴住顶部分隔线下方，与还原/
        # 最小化一致，避免最大化时整组下沉、与顶部线之间留出空隙
        _maxed = self.isMaximized()
        _tree_x = max(main_w - tree_w - 18, 300)
        ui.label_result.move(_tree_x if _maxed else max(main_w - 211 - 9, 300), 70)
        ui.treeWidget_number.move(_tree_x, 110)
        # 最大化时列表向下延伸到界面底部
        new_tree_h = max(avail_h - 130, 300) if _maxed else max(ui.treeWidget_number.height(), 100)
        ui.treeWidget_number.resize(tree_w, new_tree_h)
        # 刷子按钮（清空结果列表）：最大化时向右移动到开始按钮右侧，预留上下拉动条空间；
        # 还原/最小化态沿用贴右缘原位（设计态 main_w=820 时为 760，双向幂等不变）。
        if _maxed:
            start_right = ui.pushButton_start_cap.x() + ui.pushButton_start_cap.width()
            # 向右移动到开始按钮右侧（保留 10px 间距），并预留滚动条空间（不越过原保留右缘）
            _brush_x = min(start_right + 10, max(main_w - 20 - 40, 300))
        else:
            _brush_x = max(main_w - 20 - 40, 300)
        ui.pushButton_tree_clear.move(min(_brush_x, max(main_w - ui.pushButton_tree_clear.width(), 0)), 110)
        # 选择目录按钮跟随开始按钮左移，保持 14px 视觉间距（设计 666 与 680 之间）
        ui.pushButton_select_media_folder.move(max(ui.pushButton_start_cap.x() - 101 - 14, 20), 13)

        # 议题 #124/#135：封面/缩略图按窗口宽度横向等比放大（160×220 → ×scale），
        # 下方信息区（简介/标签/日期/导演/制作 + 右列时长/系列/发行 + 分隔线 + 勾选框）
        # 按封面框的增高量整体**下移**，保持与「番号/标题/封面」同一左列（x 不变），
        # 从而不会被放大的黑框盖住。#135 修正：此前误将信息区整组**右移**到缩略图
        # 右侧，导致最小化时字段被推到窗口右半、与番号/标题/封面不对齐。
        ui.label_poster.setGeometry(int(80 * cover_scale), 160, int(156 * cover_scale), int(220 * cover_scale))
        ui.label_thumb.setGeometry(int(252 * cover_scale), 160, int(328 * cover_scale), int(220 * cover_scale))
        # 议题 #144: 框放大后原图按新框尺寸重渲染(窗口缩放与图片显示同步)
        self._rescale_preview_pixmaps()
        cover_bottom = int(160 + 220 * cover_scale)
        # 信息区下移量 = 封面框增高量；再夹到页面可用高度内，避免宽而矮的窗口把末行裁掉
        info_delta = min(cover_bottom - 380, max(main_page.height() - 700, 0))
        # 议题 #154（撤销 #152 的行高增长）：简介/标签恒定 40px、最多两行，超出的文本
        # 按当前宽度做两行省略（宽度越大每行容纳越多，最大化自然比最小化显示更多）；
        # 下方各行只随封面增高 info_delta 下移，不再被行高增量推出页底。
        info_grow = info_delta  # 简介/标签以下各行的总下移量
        ui.label_poster_size.setGeometry(
            int(80 * cover_scale), cover_bottom, int(411 * cover_scale), int(40 * cover_scale)
        )
        ui.label_thumb_size.setGeometry(
            int(222 * cover_scale), cover_bottom, int(201 * cover_scale), int(40 * cover_scale)
        )
        thumb_right = int(580 * cover_scale)
        # 编辑 NFO/打开文件夹/播放/右键菜单四个按钮：右缘恒与缩略图框右边界严格上下
        # 对齐（组内相对位置与间距不变，组宽 160 = 4×40），最大化/还原两态同一条规则，
        # 缩略图框自身位置不动。对齐基准取缩略图实际右缘（x+w）而非 int(580*scale)，
        # 避免两处 int() 分开取整出现 1px 偏差。
        # 极窄窗（缩略图右缘退到设计右缘 587 左侧）时夹回设计位：只右移不左移。
        _align_right = max(ui.label_thumb.x() + ui.label_thumb.width(), self._MAIN_ACTION_ROW_RIGHT)
        _rx = _align_right - ui.pushButton_right_menu.width()
        _px = _rx - ui.pushButton_play.width()
        _fx = _px - ui.pushButton_open_folder.width()
        _nx = _fx - ui.pushButton_open_nfo.width()
        ui.pushButton_right_menu.move(_rx, 110)
        ui.pushButton_play.move(_px, 110)
        ui.pushButton_open_folder.move(_fx, 110)
        ui.pushButton_open_nfo.move(_nx, 110)
        # 显示封面勾选框右缘同样对齐到缩略图右边界：最大化走对齐，还原/最小化沿用设计坐标 490
        if _maxed:
            ui.checkBox_cover.move(_align_right - ui.checkBox_cover.width(), cover_bottom)
        else:
            ui.checkBox_cover.move(490, cover_bottom)
        # 信息区各控件：左列标签锚定设计 x=30（与「番号/标题/封面」对齐），y 统一下移
        # info_delta；下划线/值列按 cover_scale 等比例加长（议题 #141）：
        #   · 简介/标签（设计 x=70、宽 500）与右列时长/系列/发行（设计 x=350）的下划线
        #     右缘延伸到「缩略图框右缘」thumb_right = 580×scale；
        #   · 左列窄字段（日期/导演/制作，设计宽 220）宽度按 ×scale 加长；
        #   · 右列整体按 ×scale 右移，避免与加长后的左列窄字段重叠。
        # 左列标签（x 固定，保持与番号/标题/封面竖向对齐）
        # 简介/标签两行标签与其值行同顶（#154 行高恒定），其余行用 info_grow
        ui.label_18.move(30, 430 + info_delta)
        ui.label_33.move(30, 480 + info_delta)
        for name, y in (
            ("label_13", 530),
            ("label_23", 580),
            ("label_30", 630),
        ):
            getattr(ui, name).move(30, y + info_grow)
        # 简介/标签：左缘 x=70，右缘延伸到缩略图右缘；行高恒定 40px、最多两行（#154），
        # 下划线贴行底(设计偏移 30)，简介之下的各行只随 info_delta 下移
        wide_w = max(thumb_right - 70, 60)
        ui.label_outline.setGeometry(70, 430 + info_delta, wide_w, 40)
        ui.line_6.setGeometry(70, 460 + info_delta, wide_w, ui.line_6.height())
        ui.label_tag.setGeometry(70, 480 + info_delta, wide_w, 40)
        ui.line_7.setGeometry(70, 510 + info_delta, wide_w, ui.line_7.height())
        # 宽度变化后按新宽度重算简介/标签的两行省略文本（#154：最大化显示更多内容）
        self._refresh_main_outline_tag()
        # 左列窄字段（日期/导演/制作）：宽度按 ×scale 等比例加长
        narrow_w = max(int(220 * cover_scale), 60)
        for name, y in (
            ("label_release", 530),
            ("label_director", 580),
            ("label_studio", 630),
            ("line_8", 560),
            ("line_12", 610),
            ("line_13", 660),
        ):
            getattr(ui, name).setGeometry(70, y + info_grow, narrow_w, getattr(ui, name).height())
        # 右列（标签 x=310、值 x=350，按 ×scale 右移）：下划线右缘延伸到缩略图右缘
        right_label_x = int(310 * cover_scale)
        right_value_x = int(350 * cover_scale)
        right_line_w = max(thumb_right - right_value_x, 60)
        for name, y in (
            ("label_31", 580),
            ("label_22", 530),
            ("label_24", 630),
        ):
            getattr(ui, name).move(right_label_x, y + info_grow)
        for name, y in (
            ("label_series", 580),
            ("label_runtime", 530),
            ("label_publish", 630),
            ("line_9", 560),
            ("line_10", 610),
            ("line_11", 660),
        ):
            getattr(ui, name).setGeometry(right_value_x, y + info_grow, right_line_w, getattr(ui, name).height())
        # 上区行（y70 番号/演员、y110 标题）右界受同右行按钮限制（label_source 460 /
        # pushButton_open_nfo 427）：右界 = min(对应限制, 结果树左缘-30)
        top_right = max(min(450, ui.treeWidget_number.x() - 30), 420)
        title_right = max(min(417, ui.treeWidget_number.x() - 30), 390)
        ui.label_number.resize(max(top_right - 80, 161), ui.label_number.height())
        ui.label_actor.resize(max(top_right - 300, 161), ui.label_actor.height())
        ui.label_title.resize(max(title_right - 80, 341), ui.label_title.height())

        # ============ page_setting: tabWidget + 内部12个 scrollArea ============
        # tabWidget 设计参考几何(20,10,800,682) → scrollArea(0,0,796,658)
        # 保持 tabWidget 固定 X/Y=20,10，宽高跟随主窗口
        # tab 右边距收到 16（20-4）：QTabWidget 的 pane 内框约占 4px（左右各 ~2），
        # 滚动区若铺满 tab 页宽（上一版 scroll_w=tab_w），右缘连同滚动条会被内框
        # 裁掉 2~4px——几何量对、画面被吃，看着比主界面窄。4px 从"滚动区留白"挪到
        # "tab 右边距"：滚动区保留 4px 框内余量（右缘不被裁、整条完整可见），
        # 滚动条右缘仍落在 20+内缩2+scroll_w=页宽-18，与软件界面结果树右缘对齐。
        tab_w = max(avail_w - 36, 200)
        tab_h = max(avail_h - 20, 150)
        scroll_w = max(tab_w - 4, 396)
        scroll_h = max(tab_h - 24, 326)  # tab栏约占24px + 4px 边框
        ui.tabWidget.setGeometry(20, 10, tab_w, tab_h)

        # Qt 绝对定位布局中：先让所有 tab 的 tab_page 自身 resize 到正确尺寸，
        # 这样 scrollArea 才会感知到变化；然后对每个 scrollArea 显式设置几何。
        # 否则 scrollArea 保留设计器固定尺寸（如 796x658），不跟随变化。
        # 高级页（tab5）/ 演员页（tab_5）滚动区要留给 _sync_advanced_page_align /
        # _sync_actor_page_align 做宽幅同步 + 量基准，休眠页由切 tab 的 showEvent 补齐。
        adv_scroll = None
        actor_scroll = None
        guaxiaomulu_scroll = None
        zimu_scroll = None
        xiazai_scroll = None
        for index in range(ui.tabWidget.count()):
            tab_page = ui.tabWidget.widget(index)
            # 关键：tab_page 必须先获得新尺寸，scrollArea 才能跟随同步
            tab_page.resize(tab_w, tab_h)
            scroll_area = tab_page.findChild(CustomScrollArea)
            if scroll_area is not None and scroll_area.parentWidget() == tab_page:
                scroll_area.setGeometry(0, 0, scroll_w, scroll_h)
                if tab_page.objectName() == "tab5":
                    adv_scroll = scroll_area
                elif tab_page.objectName() == "tab_5":
                    actor_scroll = scroll_area
                content = scroll_area.widget()
                if content is not None and content.objectName() == "scrollAreaWidgetContents_guaxiaomulu":
                    guaxiaomulu_scroll = scroll_area
                elif content is not None and content.objectName() == "scrollAreaWidgetContents_zimu":
                    zimu_scroll = scroll_area
                elif content is not None and content.objectName() == "scrollAreaWidgetContents_xiazai":
                    xiazai_scroll = scroll_area

        # ---- page_setting 底部配置操作浮框（当前配置/另存为/恢复默认/保存）----
        # 设计基准 y620-692 贴页底（page_setting 高 692）。窗口放大后浮框停在设计
        # 高度、视觉悬空——整组按 (设计页高 692 - 设计 y) 的下缘边距锚定新底部，
        # 保存按钮（设计右缘 731/页宽 820）同步右缘锚定，背景 label 拉伸贴宽。
        setting_page = ui.page_setting
        sp_h = setting_page.height()
        sp_w = setting_page.width()
        bottom = max(sp_h - (692 - 630), 100)  # 控件组设计基线 y=630
        ui.label_config.setGeometry(0, max(sp_h - (692 - 620), 90), max(sp_w - 21, 400), 72)
        ui.comboBox_change_config.move(100, max(bottom + 5, 105))
        ui.pushButton_save_config.move(max(sp_w - 241 - 89, 500), bottom)
        # 另存为/恢复默认向右移动，使三段间距相等：
        # 当前配置右→另存为左 = 另存为右→恢复默认左 = 恢复默认右→保存左
        _cb_r = ui.comboBox_change_config.x() + ui.comboBox_change_config.width()
        _save_l = ui.pushButton_save_config.x()
        _gap = max((_save_l - _cb_r - ui.pushButton_save_new_config.width() - ui.pushButton_init_config.width()) / 3, 0)
        ui.pushButton_save_new_config.move(int(_cb_r + _gap), bottom)
        ui.pushButton_init_config.move(int(_cb_r + _gap * 2 + ui.pushButton_save_new_config.width()), bottom)
        # 「当前配置:」标签（设计 y=629，与基线 630 差 1）随浮框组贴底，
        # 否则最大化后停在设计位置、悬在滚动内容中部（用户截图中的浮框问题）
        ui.label_241.move(20, max(bottom - 1, 100))

        # ============ page_tool: scrollArea_10 ============
        tool_area = ui.page_tool
        scroll_10 = tool_area.findChild(CustomScrollArea)
        if scroll_10 is not None and scroll_10.parentWidget() == tool_area:
            scroll_10.setGeometry(20, 0, max(tool_area.width() - 20 - 20, 400), max(tool_area.height() - 75, 300))
            scroll_10.sync_wide_children_width()
            self._sync_actor_db_tool_layout()
            # 封面补图组三选项行随组框拉宽同步拉开间距（须在 sync_wide_children_width
            # 之后，才能读到拉宽后的组宽）
            self._sync_cover_backfill_option_row()
            # 显示输入框（含 TMDB 下拉）向右拓宽到右侧按钮左侧（须在上面两者
            # 之后，取按钮终态位置；大小态通用，无需 isMaximized 分支）
            self._sync_tool_page_input_fill()
            # ---- page_tool 底部配置操作栏（当前配置/另存为/恢复默认/保存）----
            # 与 page_setting 底部栏同组件同功能：滚动区高度收掉 75px 给页脚留位，
            # 页脚按 (设计页高 692 - 设计 y) 的下缘边距锚定新底部，保存按钮右缘锚定。
            tp_h = tool_area.height()
            tp_w = tool_area.width()
            t_bottom = max(tp_h - (692 - 630), 100)
            ui.label_config_tool.setGeometry(0, max(tp_h - (692 - 620), 90), max(tp_w - 21, 400), 72)
            ui.comboBox_change_config_tool.move(100, max(t_bottom + 5, 105))
            ui.pushButton_save_config_tool.move(max(tp_w - 241 - 89, 500), t_bottom)
            # 与 page_setting 一致：三段间距相等
            _cb_r_t = ui.comboBox_change_config_tool.x() + ui.comboBox_change_config_tool.width()
            _save_l_t = ui.pushButton_save_config_tool.x()
            _gap_t = max(
                (
                    _save_l_t
                    - _cb_r_t
                    - ui.pushButton_save_new_config_tool.width()
                    - ui.pushButton_init_config_tool.width()
                )
                / 3,
                0,
            )
            ui.pushButton_save_new_config_tool.move(int(_cb_r_t + _gap_t), t_bottom)
            ui.pushButton_init_config_tool.move(
                int(_cb_r_t + _gap_t * 2 + ui.pushButton_save_new_config_tool.width()), t_bottom
            )
            ui.label_241_tool.move(20, max(t_bottom - 1, 100))

        # ============ page_net: textBrowser_net_main + 右侧按钮 ============
        # 议题 #67: 文本区从按钮条带下方 (y=60) 开始, 按钮不再悬浮遮挡日志首行
        net_area = ui.page_net
        net_browser = ui.textBrowser_net_main
        if net_browser.parentWidget() == net_area:
            net_browser.setGeometry(30, 60, max(net_area.width() - 30 - 2, 400), max(net_area.height() - 60, 300))
        # 设计基准页面宽 822：check_net 右缘 800(右距20)、net_copy 右缘 670(右距152)、net_retry 右缘 548(右距274)
        ui.pushButton_check_net.move(max(net_area.width() - 142, 20), 13)
        ui.pushButton_net_copy.move(max(net_area.width() - 262, 20), 13)
        ui.pushButton_net_retry.move(max(net_area.width() - 384, 20), 13)

        # ============ page_about: textBrowser_about ============
        about_browser = ui.textBrowser_about
        if about_browser.parentWidget() == ui.page_about:
            about_browser.setGeometry(
                30, 0, max(ui.page_about.width() - 30 - 2, 300), max(ui.page_about.height() - 0, 300)
            )

        # ============ page_log: textBrowser_log_main (上) / textBrowser_log_main_2 (下) / log_main_3(失败列表) ============
        # 日志区右缘与软件界面结果树右缘对齐（同为页宽-18）：x=28，宽=页宽-28-18
        log_page = ui.page_log
        log_w = max(log_page.width() - 28 - 18, 300)
        log_h_total = log_page.height()
        # 上栏日志显示从顶端 y=0 开始；滚动条是独立控件 verticalScrollBar_log_main，
        # 其轨道上延到开始按钮下方 y=57（开始按钮 y13+h40 底部 53，留 4px 间隙），
        # 下缘贴上栏底；清空按钮移至滚动条左侧、x 与软件界面清空按钮同值。
        # 显示与滚动分离：滚动范围与内置滚动条一致，轨道与按钮矩形不相交。
        log_bar_w = 16
        log_bar_top = 57
        # 下栏隐藏时上栏铺满整页；显示时上下按原比例 (421:271 ≈ 61%:39%) 分高
        lower_browser = ui.textBrowser_log_main_2
        if lower_browser.isHidden():
            upper_h = max(log_h_total, 100)
        else:
            upper_h = max(int(log_h_total * 0.61), 100)
        lower_h = max(log_h_total - upper_h - 1, 100)
        upper_w = max(log_w, 300)
        text_w = max(upper_w - log_bar_w, 200)
        ui.textBrowser_log_main.setGeometry(28, 0, text_w, upper_h)
        ui.verticalScrollBar_log_main.setGeometry(
            28 + text_w, log_bar_top, log_bar_w, max(upper_h - log_bar_top, log_bar_w)
        )
        if not lower_browser.isHidden():
            lower_browser.setGeometry(28, upper_h + 1, upper_w, lower_h)
        # 覆盖性日志视图 (失败列表) 铺满整个日志页（右缘同样收到页宽-18，与上下日志区滚动条对齐）
        ui.textBrowser_log_main_3.setGeometry(0, 0, max(log_page.width() - 18, 300), max(log_page.height() - 2, 300))
        # 设计基准页面宽 822/高 692：按钮右缘锚定右侧、底部按钮锚定下缘（与软件界面开始按钮同右缘）；
        # 清空按钮 x 取页宽-60，与软件界面清空结果列表按钮（pushButton_tree_clear，非最大化同为页宽-60）左右一致
        ui.pushButton_start_cap2.move(max(log_page.width() - 120 - 20, 20), 13)
        ui.pushButton_clear_logs.move(max(log_page.width() - 60, 20), 61)
        ui.pushButton_view_failed_list.move(max(log_page.width() - 255, 20), 13)
        # 复制日志按钮：与检测网络页复制结果按钮同尺寸 110x40，
        # 失败按钮左侧 14px 间距（链式锚定，窄窗钳位后间距依然成立）
        ui.pushButton_copy_logs.setGeometry(max(ui.pushButton_view_failed_list.x() - 14 - 110, 20), 13, 110, 40)
        ui.pushButton_show_hide_logs.move(0, max(log_page.height() - 42, 13))
        ui.pushButton_save_failed_list.move(0, max(log_page.height() - 42, 13))
        # 外置滚动条跟随几何变化后，重新镜像内置滚动条的范围与位置
        self._mirror_log_scrollbar()

        # ============ widget_nfo（「编辑 NFO」覆盖层）随主窗口缩放（议题 #152/#154/#166）============
        # 可见时作为主页伴侣面板：左贴导航右缘、右收到缩略图/结果树之间，不盖住番号树。
        self._sync_nfo_overlay_geometry()

        # ============ page_nfo_library: 简介/标签高度自适应（议题 #117）============
        self._sync_nfo_lib_form_fields()

        # 目录显示框与筛选框在布局里均分宽度（.ui horstretch 均为 1），无需运行时同步。
        self._sync_nfo_lib_action_buttons()

        # 「批量操作」分组贴着内容收紧（提示 label 按实测折行高、空状态 label 不占位），
        # 省下的高度自动回到上方 Expanding 的 NFO 列表。必须排在按钮同步之后：
        # 那里会对 gridLayout_nfo_lib_batch 做 invalidate/activate，分组宽高到此才是终态。
        self._sync_nfo_lib_batch_panel()

        # 三按钮底边对齐：左间隙/右间隙按表单保存按钮底边重算（需求 3）。
        # 必须排在 _sync_nfo_lib_batch_panel 之后——hint 下限变化会改分组高，
        # 进而改左按钮底边，排前面量到的是旧值。
        self._sync_nfo_lib_action_row()

        # 预览图按 label 边界等比贴边：窗口变化后 label 尺寸变了，载图时按固定
        # 尺寸缩好的 pixmap 不会自己跟变。排最后，与按钮行无关。
        self._sync_nfo_lib_preview_pixmaps()

        # ============ page_setting / 命名页: 模板预览固定高度 + 说明文字贴合 ============
        self._sync_naming_template_section()

        # ============ page_setting / 命名页: 画质组按内容收紧 HD 行到分辨率行的间距 ============
        # 必须排在通用拉伸之后：网格列宽（从而说明文字折行数、需要的总高度）
        # 取决于拉伸后的终态宽度，-template/翻译两组同理。
        self._sync_definition_group_spacing()
        # 命名页画质行右移对齐：必须排在 _sync_definition_group_spacing 之后——后者每遍
        # activate() frame_layout 并按其 sizeHint 高度重钉 frame 高，排前面量到的 need
        # 才是终态（本间隔高为 0，不影响它的 frame_h 计算）。
        self._sync_naming_definition_align(getattr(ui, "scrollArea_7", None))

        # ============ page_setting / 翻译页: 简介组与演员组按内容收紧间距 ============
        # 必须排在通用拉伸之后：两个网格的列宽（从而提示文字折行数、说明文字需
        # 要的总高度）取决于拉伸后的终态宽度。
        self._sync_fanyi_group_spacing()

        # ============ page_setting / 水印页: 四行左标签冒号左移到「首个水印位置：」冒号 ============
        # 排在通用拉伸之后：gridLayoutWidget_24 的宽由通用宽幅同步铺开，内部列分配由本方法钉死。
        # 窄态内部直接 return，最小化布局逐像素不变。
        self._sync_watermark_colon_align(getattr(ui, "scrollArea_4", None))

        # ============ page_setting / 刮削网站页: 「指定网站」下拉框右缘对齐「锁定类型」 ============
        # 必须排在通用拉伸之后：本方法要量「锁定类型」下拉框在 content 里的实时右缘，
        # 而两个组框的宽度刚被宽幅同步按新视口改写（排前面量到的是上一视口的旧值）。
        self._sync_site_pref_combo_width()

        # ============ page_setting / 刮削网站页: 「刮削不到？看这里！」按钮垂直居中到下拉框 ============
        # 必须排在 _sync_site_pref_combo_width 之后：本方法按下拉框的实时几何重钉
        # 按钮 y，而上一步刚改写下拉框的宽度上限（进而影响所在行高与行位置）。
        self._sync_scrape_note_vertical()

        # ============ page_setting / 刮削网站页: 宽态国产传媒说明单行时收回空行 ============
        # 排在通用拉伸之后：本方法量的是该说明的终态宽度与其折行数，只有宽幅同步
        # 按新视口改写完组框/网格列宽后量到的 need 才是终态（否则宽度还是上一视口
        # 的旧值，单行判定会迟一拍）。也不影响 _sync_scrape_note_vertical——它锚的是
        # 另一个组框（groupBox_11）里的「指定网站」下拉框，与本组网格无交集。
        self._sync_site_type_tip_single_line()

        # ============ page_setting / NFO页: 宽幅组落定（先落定再量） ============
        # verify_gb 复验血案：tab 切换时 showEvent 的 wide-sync 跑在级联中途
        # （视口 805），落定到 819 后再无事件触发它，groupBox_81 带着 stale
        # extra 定格（715+9=724），与水印组恒差 14px，且后面六个控制器全在
        # stale 几何上量测。在 NFO 控制器量测之前显式重跑一次 NFO 滚动区的
        # 宽幅同步（同 resizeEvent 顺序：先拉伸后补最小高），保证控制器量的
        # 全是终态几何。休眠页跳过（切页 showEvent + beats 会补齐）。
        if ui.groupBox_81.isVisibleTo(self):
            ui.scrollArea_13.sync_wide_children_width()
            ui.scrollArea_13.sync_content_min_height()

        # ============ page_setting / NFO页: 左标签冒号左移与组标题冒号对齐 ============
        self._sync_nfo_colon_align()

        # ============ page_setting / NFO页: 宽视口下右列左对齐到 thirds ============
        self._sync_nfo_right_column_align()

        # ============ page_setting / NFO页: 宽视口下原标题/简介/原简介左对齐到发行日期列 ============
        self._sync_nfo_title_plot_align()

        # ============ page_setting / NFO页: 窄态下分级信息/时长左对齐到发行日期列 ============
        self._sync_nfo_row_align()

        # ============ page_setting / NFO页: 窄态下末项自定义/想看人数右对齐到上映日期列 ============
        self._sync_nfo_tail_align()

        # ============ page_setting / NFO页: 宽态下合集两项左对齐到片商/发行商列 ============
        self._sync_nfo_set_align()

        # ============ page_setting / NFO页: 窄态下片商行后三项对齐到标签两行 ============
        self._sync_nfo_studio_row_align()

        # ============ page_setting / NFO页: 窄态下字段说明按钮左移进组框 ============
        self._sync_nfo_field_tips()

        # ============ page_setting / 高级页: 四行第1列对齐到「刮削结束后自动退出软件」 ============
        # 必须排在最后：本控制器要量高级页的实时列宽，而宽幅同步会改写
        # groupBox_12 的列宽，放前面量到的是过期值（同 verify_gb 血案）。
        self._sync_advanced_page_align(adv_scroll)
        # 高级页窄态：「每次间隔」时长框右缘缩到与「间歇刮削」文件数框右缘对齐
        # （还原态单列一条需求，最大化态一个像素都不碰）。必须排在上面这个方法
        # **之后**：它末尾那批 gridLayout_20.activate() 会把两行重新排一遍，提前
        # 量到的是过期几何；且它自带早退分支，不能从里面挂钩子。
        self._sync_advanced_page_rest_interval_align(self._scroll_stretch_extra(self._adv_scroll) > 0)
        # 高级页：「移动文件」行的「覆盖旧文件」「保留旧文件」与「界面外观」行的
        # 「隐藏边框（美观样式）」「暗黑模式」严格上下对齐（锚点两枚不动）。
        # 必须排在上面两个方法之后：它要量锚点行两枚复选框的终态坐标。
        self._sync_advanced_page_move_file_align()
        # 高级页：「任务模式」行的「存储在网盘」与「界面外观」行的「暗黑模式」
        # 严格上下对齐（还原态左移、最大化态右移，「暗黑模式」不动）。
        # 与「移动文件」行同款手法，必须排在上面几个方法之后：它同样要量锚点行
        # 两枚复选框的终态宽度。
        self._sync_advanced_page_task_mode_align()

        # ============ page_setting / 演员页: 两行控件对齐到各自基准线 ============
        # 同样排在通用拉伸之后：本方法先落设计几何再按最大化分支覆盖。
        self._sync_actor_page_align(actor_scroll)
        # 演员信息组三列对齐（行标签冒号 + 三个分隔符行对到 Graphis 三列）。
        # 必须在 _sync_actor_page_align 之后：本方法要量 checkBox_actor_photo_ne_new
        # 的左缘当 A3 锚点，而锚点位置由前者刚定下。
        self._sync_actor_info_columns(actor_scroll)
        # 最大化态 A2 列对齐。排在 ② 之后是**必须的**：② 末尾会 grid.invalidate()
        # + activate() 整个 gridLayout_14，把 _DOCK_RIGHT 的绝对定位项重新钉回
        # 「design_x + extra」的右缘（实测「补全完成后自动补全演员头像」被弹回
        # 1348）；排在 ① 之后是为了 A2 锚点 x 已是终态。
        self._sync_actor_page_wide_a2_align(actor_scroll)
        # 窄态右移对齐（最小化时把三个「仅缺少…/本地头像库」对到锚点列）：必须在
        # _sync_actor_info_columns 之后——它要量后者刚钉好的两个单选的当前 x。
        self._sync_actor_page_narrow_align(actor_scroll)

        # ============ page_setting / 刮削目录页: 文件清理提示左移到按钮下方 ============
        # 排在通用拉伸之后：提示是 _STRETCH，最大化时先被拉宽右偏，本方法同拍拉回；
        # 还原态（extra <= 0）内部直接 return，最小化布局逐像素不变。
        guaxiaomulu_scroll = (
            guaxiaomulu_scroll if guaxiaomulu_scroll is not None else getattr(self, "_guaxiaomulu_scroll", None)
        )
        self._sync_guaxiaomulu_clean_tip_align(guaxiaomulu_scroll)
        # 本页两处横向对齐（软链接行让位 +「刮削时自动清理」按态换列）：必须排在
        # 上面那次宽态重跑之后，否则「刮削时自动清理」会被 _DOCK_RIGHT 钉回右缘。
        self._sync_guaxiaomulu_checkbox_align(guaxiaomulu_scroll)

        # ============ page_setting / 刮削模式页: 复用行第二复选框对齐 STRM 行 ====
        # 覆盖元数据框须与覆盖 STRM 框同 x（上下严格对齐）且永不再动：按实测差值闭环
        # 收敛（sizeHint 在 show 前后会变，初始化公式一次算不准），相等即 no-op；
        # 休眠页内部直接 return，切页同拍收敛。
        self._sync_reuse_meta_gap_align()

        # ============ page_setting / 刮削模式页: Javdb 延时提示上移一行并钉死 =
        # label_26 已移出 grid 独立为 groupBox_53 子件：x 与分离模式描述文本
        # 精确对齐、y 上移一行；grid 内 0-2 行保持不动。休眠页内部 return。
        self._sync_javdb_tip_pos()

        # ============ page_setting / 字幕页: 底部填充收缩 + 两处左对齐 ============
        # 排在通用拉伸之后：必须走统一入口 _sync_zimu_page_align（先收缩后对齐）。
        # 若尾部只调 _sync_zimu_fill_blank，它内部的重跑宽幅同步会把钩子刚对好的
        # 复选框搬回右缘（钩子才是破坏者同款）；矮视口各分支内部直接 return，
        # 最小化布局逐像素不变。
        self._sync_zimu_page_align(zimu_scroll if zimu_scroll is not None else getattr(self, "_zimu_scroll", None))

        # ============ page_setting / 下载页: 「下载」行钉到「保留旧文件」行同位 ============
        # 排在通用拉伸之后：本方法要量「保留旧文件」行各复选框在 content 里的实时
        # x/宽，而两个行容器刚被宽幅同步按新视口改写并重排（排前面量到的是上一视口
        # 的旧值）。休眠页内部 return，由切 tab 的 showEvent + 钩子补齐。
        self._sync_xiazai_row_align(
            xiazai_scroll if xiazai_scroll is not None else getattr(self, "_xiazai_scroll", None)
        )

    def _sync_advanced_page_wide_hook(self) -> None:
        """滚动区宽幅拉伸之后立刻把高级页四行对回基准线（零参，钩子用）。

        见 _sync_advanced_page_align 的说明：通用拉伸先把网格里两项均分的行
        （界面外观行的「暗黑模式」、隐藏入口行的「隐藏NFO库管理」）等分推到右缘，
        本控制器要到下一拍才把它们拉回「刮削结束后自动退出软件」那条竖线。
        那一帧一旦被绘制，用户就会看到「先在右侧、再向左漂移」——最大化方向是
        「隐藏NFO库管理」，还原方向是「暗黑模式」（还原时 layoutWidget5 还留着
        最大化态的加宽宽度，同样先把两项等分往外推）。挂在拉伸之后的钩子上，
        两者就在同一拍内完成，中间态不会被绘制。

        与 _sync_nfo_page_align / _sync_actor_page_align 同源，休眠页同样零成本。
        """
        # 宽幅同步刚在 CustomScrollArea._run_post_wide_sync_hook 里做完，列宽已是
        # 终态，这里不必（也不宜）再递归跑一遍 sync_wide_children_width()。
        self._sync_advanced_page_align(self._adv_scroll, wide_synced=True)

    def _advanced_page_window_maximized(self) -> bool:
        """高级页：窗口当前是不是真·最大化（决定「最小化态需求」是否生效）。

        判据不能用几何拉伸量（`_scroll_stretch_extra() > 0`）：真机（dpr=1.25、
        屏幕 1536×864）**还原态**窗口 1085×793 的拉伸量已经是 **+33 > 0**，几何
        量会把还原态误判成「最大化」，「最小化时」那一支根本不执行（用户截图：
        目标纹丝不动）。故这里用窗口管理器给的状态位。

        最大化/还原那一拍窗口管理器「先发尺寸、后发状态」，resizeEvent 里
        isMaximized() 还是旧值；状态位到位后 changeEvent 会
        `QTimer.singleShot(0, self._sync_page_layouts)` 补一次重排（见
        window_ops.changeEvent），故最坏只闪一帧、随即归位。
        """
        return bool(self.isMaximized() or self.isFullScreen())

    def _sync_advanced_page_align(self, adv_scroll=None, wide_synced=False) -> None:
        """设置-高级：六行控件对齐到「显示字段来源信息」同一条竖线（最大化态）。

        v2.1.9 之前这页的竖线是「刮削结束后自动退出软件」，本次需求把竖线换成
        用户指定的 `checkBox_show_from_log`（显示字段来源信息），并把竖线本身
        （「刮削结束后自动退出软件」）也纳入要左移的目标——它原来既是基准又是
        目标，基准不能自己动，故拆成「阶段一先搬基准、阶段二再按基准对齐其余
        四行」两步。七项目标（截图红框 1~5，其中第 3 框是两枚「关」）：
        checkBox_auto_exit / checkBox_show_dialog_stop_scrape /
        checkBox_hide_menu_icon / checkBox_dark_mode / checkBox_hide_nfo_nav /
        radioButton_log_off / radioButton_update_off。前五项在本方法内处理，
        后两项（两枚「关」）由 _sync_advanced_page_tail_align 跟随
        checkBox_hide_nfo_nav 自动到位——它量的是 nfo 的实时 x，nfo 换竖线它
        就跟着换，无需改动。

        最新一条需求（「隐藏NFO库管理」与两枚「关」在**最小化态**向左移动到与
        「显示字段来源信息」上下严格对齐，且「显示字段来源信息」位置保持不变）
        落在下面「隐藏入口行」那一段：窄态锚点由 anchor 换成 col_x(src_from)，
        即该动的是 nfo 而非 from（与上一批 _sync_advanced_page_debug_row 方向
        相反，故那一方法已连同调用一并删除，见方法体内「调试模式行本方法不再
        介入」那段）。最大化那一支的 pin_d/room 判据一个字节都没改，宽态结果
        与本批需求之前逐位相同。

        竖线取法分两态（这是「最小化时页面、布局、控件、提示词等等均保持不变」
        的唯一保证）：最大化取 `checkBox_show_from_log`；还原态仍取
        `checkBox_auto_exit` 的自然位——它在 1030×753 下是 x=412，而新锚点只有
        x=292，若还原态也用新锚点，这五项会从 412 被左移到 292，正好违反需求。
        逐项试过「还原态一律解除钉宽」同样不行：解除后第 8 行「隐藏菜单栏图标」
        会掉到 353、第 9 行「暗黑模式」会掉到 393，与改动前的 412 都不等。

        用户截图（先最大化态、后还原态两轮）：「停止刮削时」「隐藏菜单栏图标
        （Mac）」「暗黑模式」「隐藏 NFO 库管理」四个复选框的左缘都挤在第1列起
        点，要求对齐到第2行「刮削结束后自动退出软件」的正下方严格上下对齐；该
        基准复选框自身位置必须保持不变。最大化态要全对齐、还原态只要求前三个
        （「隐藏NFO库管理」在还原态放不下，用户没要求、也不该裁字）——该限制
        已由最新一条需求解除（见方法体内「隐藏入口行」段与开头那段说明）。

        根因（离屏实测 + 用户截图双证，gridLayoutWidget_20 两列 QGridLayout，
        col1 起于 x=97）：QHBoxLayout 把剩余空间在**所有可拉伸项之间等分**
        （弹窗确认行 811/811、界面外观行 272/272、隐藏入口行 539/538/539、
        隐藏图标行 191/104/1321），所以第1列里每一个复选框的绝对 x 都随列宽漂移。
        最大化时 CustomScrollArea.sync_wide_children_width() 把列从 568 拉到
        1628，两项均分的那几行末位被推到 x=914，而 Fixed 前缀行（隐藏图标行）
        仍停在 x=404——同一条竖线上出现三个不同的左缘，等分只认剩余空间总量，
        既不能靠 margin 也不能靠撑宽前导项（等分会推着目标项一起走）。

        做法（量基准 + 钉死前导项，纯函数、双向幂等）：
        阶段一搬基准：checkBox_auto_exit 与 checkBox_auto_start 同在
        horizontalLayout_102 里两均分，故钉死前导项 checkBox_auto_start 为
        `pin_2 = 竖线 - row_x - spacing`，末位即精确落竖线。阶段二量到的
        `anchor = col_x(checkBox_auto_exit)` 在最大化态恒等于
        col_x(checkBox_show_from_log)（实测 1100×800 = 201、1920×1170 = 474），
        在还原态就是自然位，两态共用下面同一份代码。每遍现量现用，不写死像素。
        令 pin = anchor - row_x - spacing，钉死该行前导控件为 pin 宽后剩余空间
        全部归末位项，目标项的绝对 x 恒等于 anchor：
          弹窗确认行  钉「退出软件时」            -> 「停止刮削时」        落 anchor
          隐藏图标行  在 label_42 之后插固定间隔  -> 「隐藏菜单栏图标（Mac）」落 anchor，
                      前两项保持贴 col1 左缘（改用整行左 margin 会把「隐藏Dock图标
                      （Mac）」「保存后重启生效」一起推走，破坏本页左缘节奏）
          界面外观行  把 layoutWidget5 加宽到 2*(anchor-row_x)-spacing（两项均分）
                      -> 「暗黑模式」落 anchor；该容器是 frame 的普通子 QWidget
                      （frame 无 layout），故用 setGeometry 而非 layout 属性
                      竖线前移后该容器会**收窄**（1100×800 由 658 收到 396），
                      下界 lw.sizeHint()=152 与上界 frame.width() 都仍成立
          隐藏入口行  钉「隐藏 Emby 演员管理」    -> 「隐藏 NFO 库管理」落 anchor，
                      并把它自己钉回 sizeHint 宽（QCheckBox 可拉伸，不钉会被余量
                      撑到 658px，左对齐绘制时字形只占 152，与说明标签之间空出
                      394px，见用户截图红框）-> 说明标签紧贴其右 6px。锚点两态统一 =
                       「显示字段来源信息」col_x(src_from)（宽态阶段一已让 anchor 等于
                       它，故最大化结果逐位不变）
        前导控件全是左对齐绘制，钉宽/插间隔只改右侧留白，不移动自身字形。
        走 setFixedWidth / QSpacerItem / setGeometry 而非 move()：layout
        重新 activate 会覆盖 move()。任一行余量放不下（窗口太窄、说明标签挤不
        下）就整行解除，保持设计态原样。
        「隐藏入口：」冒号对齐已在 MDCx.ui/.py 静态补齐 RightToLeft + AlignRight，
        与同列标签共用网格列右缘，不需运行时介入。休眠页跳过。

        v2.7.6 又加三条需求（只动窄态，宽态逐位不变）：
        ① 「保存后重启生效」挪到「隐藏菜单栏图标（Mac）」**右侧**：MDCx.ui 里
          horizontalLayout_dock 的项序改成「隐藏Dock图标 | 隐藏菜单栏图标 |
          保存后重启生效」，同时把「隐藏菜单栏图标（Mac）」的 sizePolicy 由
          Minimum 改成 Fixed——Minimum 会独吞整行余量，提示词会被顶到行末，
          改 Fixed 后它才紧贴在复选框文字右侧；提示词自己改成 Minimum 顶住余量，
          该行才仍是「可拉伸项」，否则 QGridLayout 的 col1 不再伸展、整页列宽错乱。
        ② 窄态「隐藏菜单栏图标（Mac）」与「暗黑模式」严格上下对齐，且「暗黑模式」
          位置保持不变：隐藏图标行的目标竖线在窄态改取「暗黑模式」的**实测终态
          x**（不是共用 anchor——窄态 anchor 是「显示字段内容信息」那条线，真机上
          「暗黑模式」与它并不重合）。故「界面外观行」一段排到隐藏图标行之前，
          且窄态先 activate 一次 lay_c 再量。
        ③ 窄态「无限次刮削」与「无按钮」严格上下对齐，且「无按钮」位置保持不变：
          保留任务行的目标竖线在窄态改取 radioButton_hide_none 的实测 x，且本段
          整段挪到 _sync_advanced_page_tail_align() 之后（「无」的终态 x 是那里
          钉出来的）。宽态仍取「停止刮削时」，与本批需求之前逐位相同。
          （注：③ 的「窄态」判据是几何拉伸量，真机上不成立，已被下面 ④ 取代。）
        ④ 还原态「无限次刮削」与「显示字段来源信息」严格上下对齐，且「显示字段
          来源信息」位置保持不变：目标竖线在还原态改取 col_x(src_from)。**判态
          换成窗口管理器给的「真·最大化」状态**（_advanced_page_window_maximized）：
          几何拉伸量在真机还原态窗口（1085×793）已经是 +33 > 0，会把还原态误判
          成最大化、这一支根本不执行（用户截图：目标纹丝不动）。最大化态仍取
          「停止刮削时」，页面布局、控件、组件、提示词全部保持不变。
          （v3.0 起目标由「显示字段内容信息」改成「显示字段来源信息」——用户要
          的是**向左**移到「显示字段来源信息」那条竖线上，不是向右。）
        """
        ui = self.Ui
        host = ui.gridLayoutWidget_20
        if not host.isVisibleTo(self):
            return
        # 同 verify_gb 血案：先显式重跑宽幅同步，保证量到的是终态列宽。
        # 从拉伸之后的钩子进来时列宽已经是终态，wide_synced=True 跳过这次递归。
        if not wide_synced and adv_scroll is not None and adv_scroll.isVisibleTo(self):
            adv_scroll.sync_wide_children_width()
        anchor_box = ui.checkBox_auto_exit
        lead_box = ui.checkBox_show_dialog_exit
        auto_start = ui.checkBox_auto_start
        src_from = ui.checkBox_show_from_log
        src_data = ui.checkBox_show_data_log
        if not (
            anchor_box.isVisibleTo(self)
            and lead_box.isVisibleTo(self)
            and auto_start.isVisibleTo(self)
            and src_from.isVisibleTo(self)
        ):
            return
        # 「该对齐隐藏入口行」的判据同样改成几何量而非 isMaximized()：窗口管理器
        # 最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，于是
        # 钉宽被跳过、右缘等分被绘制，等标志到位再重排一次才对齐——用户看到
        # 「隐藏NFO库管理先在右侧、再向左漂移」。还原态拉伸量为负，与原先
        # 「非最大化不钉」的行为一致。
        wide = self._scroll_stretch_extra(self._adv_scroll) > 0
        # 新锚点「显示字段来源信息」在 groupBox_3（调试模式）里、不是 host 的
        # 后代，mapTo(host, ...) 无效（Qt 只在祖先链上定义），须经公共祖先
        # scrollAreaWidgetContents_gaoji 中转再减去 host 的 content 坐标。
        content = ui.scrollAreaWidgetContents_gaoji
        host_x = host.mapTo(content, QPoint(0, 0)).x()

        def col_x(widget) -> int:
            """控件左缘换算到 gridLayoutWidget_20 的局部坐标（跨分支经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x() - host_x

        row_x = col_x(lead_box)
        col_w = host.width() - row_x

        # ---- 调试模式行（groupBox_3）本方法不再介入 -----------------------------
        # 曾有过一个 _sync_advanced_page_debug_row：它在**还原态**把「显示字段来源信息」
        # 右移到 nfo 那一列（钉 web/from 两段）。本批需求与之**方向相反**且明写
        # 「显示字段来源信息位置保持不变」，故窄态已把那两段钉宽整段撤掉，该方法连同
        # 调用一并删除：调试模式行回到三均分的自然位，「显示字段内容信息」的坐标
        # 于是与「只有通用宽幅逻辑」的基线逐位相同（它正是本方法窄态的竖线锚点）。
        # 最大化态本来就只做解除（那时 from 与 nfo 天然同列，钉不钉一样），故宽态
        # 结果与删除前逐位相同。

        # ---- 阶段一：先把需求①自己的目标「刮削结束后自动退出软件」搬到新竖线上 ----
        # 它与「自动启动后自动开始刮削」同在 horizontalLayout_102 里两均分、x 随
        # 列宽漂移，本方法原先从不触碰该行；要让它左移只能先钉死前导项（钉宽 =
        # 目标列坐标 - row_x - spacing，末位即精确落目标）。竖线取法分两态：
        #   最大化：取需求指定的新锚点 checkBox_show_from_log；
        #   还原态：取「刮削结束后自动退出软件」的自然位（＝本方法进入前的旧基准）。
        # 还原态必须如此——新锚点在 1030×753 下只有 x=292，而旧基准自然位 412，
        # 若沿用新锚点，这五项会从 412 被左移到 292，直接违反「最小化时逐像素不变」。
        # 钉完立刻 activate（改约束不重排）再统一按 col_x(anchor_box) 量竖线：
        # 宽态此时它恰等于新锚点，于是后面四段两种窗宽状态共用同一份代码、天然
        # 幂等、互不依赖，也避免了「还原时先量到上一次宽态钉宽」的一帧错位。
        # 最大化：照旧，钉前导项把「刮削结束后自动退出软件」搬到「显示字段来源信息」
        # 那条竖线（目标即新锚点）。还原态的目标是「隐藏菜单栏图标（Mac）」，而
        # 它的坐标要等下面第 8 行那批 activate 才定下来，故窄态那一半挪到方法末尾
        # （见下方「窄态阶段一」），此处只处理宽态。
        lay_2 = ui.horizontalLayout_102  # 自动启动后自动开始刮削 / 刮削结束后自动退出软件
        if wide:
            target = col_x(src_from)
            pin_2 = target - row_x - lay_2.spacing()
            ok_2 = (
                pin_2 >= auto_start.sizeHint().width()
                and col_w - pin_2 - lay_2.spacing() >= anchor_box.sizeHint().width()
            )
            changed = self._pin_row_lead_width(auto_start, pin_2 if ok_2 else None)
        else:
            # 窄态：先解除上一遍可能残留的宽态钉宽，否则下面量到的是带钉宽的坐标
            changed = self._pin_row_lead_width(auto_start, None)
        if changed:
            lay_2.invalidate()
            lay_2.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()
            row_x = col_x(lead_box)
            col_w = host.width() - row_x
        # ok_2 为真时它恰在 target 上，为假时是自然位——两种情形都直接量它即可
        anchor = col_x(anchor_box)
        # 下面三行（弹窗确认行 / 隐藏图标行 / 界面外观行）的竖线分两态取：
        #   最大化：沿用上一批需求，仍是「显示字段来源信息」那条竖线（= 阶段一钉完
        #     后 auto_exit 的坐标，故上面量到的 anchor 在宽态恒等于新锚点）；
        #   还原态：换成「显示字段内容信息」（本批需求②）。实测 1030×753 是 495、
        #     1000×700 是 475，都在那条旧基准（auto_exit 自然位 412~430）的右侧，
        #     所以本批在还原态是**右移**；上一批需求说的「向左」是相对最大化态而言，
        #     两批方向相反但落点一致（都精确对齐到锚点左缘），互不冲突。
        if not wide:
            anchor = col_x(src_data)
        if anchor <= row_x or col_w <= 0:
            return
        lay_a = ui.horizontalLayout_55  # 退出软件时 / 停止刮削时
        lay_b = ui.horizontalLayout_dock  # 隐藏Dock图标 / 隐藏菜单栏图标 / 保存后重启生效
        lay_d = ui.horizontalLayout_nav_hide  # 隐藏Emby演员管理 / 隐藏NFO库管理 / 说明
        # 阶段一已就位（改了就当场 activate），此处重新起算：下面四段共用行末
        # 那批 invalidate+activate
        changed = False

        # ---- 弹窗确认行：钉「退出软件时」，「停止刮削时」即落 anchor（两态生效） ----
        stop_scrape = ui.checkBox_show_dialog_stop_scrape
        pin_a = anchor - row_x - lay_a.spacing()
        ok_a = (
            pin_a >= lead_box.sizeHint().width() and col_w - pin_a - lay_a.spacing() >= stop_scrape.sizeHint().width()
        )
        changed |= self._pin_row_lead_width(lead_box, pin_a if ok_a else None)

        # ---- 界面外观行：「暗黑模式」落 anchor，两条路子按「容器装不装得下」二选一 ----
        # 本段必须排在「隐藏图标行」**之前**：窄态需求②要「隐藏菜单栏图标（Mac）」
        # 与「暗黑模式」严格上下对齐，而「暗黑模式」位置保持不变，故隐藏图标行的
        # 目标取「暗黑模式」的实测终态 x；不先让本行落定就量不到它的终态坐标。
        # 路子甲（最大化）：layoutWidget5 加宽到 2*(anchor-row_x)-spacing，行内两项
        #   均分，末位即落 anchor。want_w 恒等于 col_w（anchor = row_x + col_w/2 + 3，
        #   两项均分同式），即最多填满 frame，绝不溢出。
        # 路子乙（还原态，需求②）：anchor 换成了更靠右的「显示字段内容信息」，
        #   2*(anchor-row_x) 实测 644~684，而 frame 只有 523~553，甲路必然越界。
        #   改钉死前导项「隐藏窗口标题栏」为 anchor - lw左缘 - spacing，容器保持
        #   设计宽 _ADV_FRAME_LW_W，末位「暗黑模式」照样精确落 anchor，且容器右缘
        #   与还原态现状完全一致（不新增任何越界/裁字）。
        lw = ui.layoutWidget5
        lay_c = ui.horizontalLayout_62
        lead_c = ui.checkBox_hide_window_title
        dark_c = ui.checkBox_dark_mode
        want_w = 2 * (anchor - row_x) - lay_c.spacing()
        ok_even = want_w <= ui.frame.width() and want_w >= lw.sizeHint().width()
        pin_c = anchor - col_x(lw) - lay_c.spacing()
        ok_pin = (
            pin_c >= lead_c.sizeHint().width() and lw.width() - pin_c - lay_c.spacing() >= dark_c.sizeHint().width()
        )
        new_w = want_w if ok_even else self._ADV_FRAME_LW_W
        pin_w = None if ok_even or not ok_pin else pin_c
        changed |= self._pin_row_lead_width(lead_c, pin_w)
        if lw.width() != new_w:
            lw.setGeometry(lw.x(), lw.y(), new_w, lw.height())
            changed = True

        # ---- 隐藏图标行：插固定间隔把「隐藏菜单栏图标（Mac）」单独推到目标竖线 ----
        # v2.7.6 行内顺序改为：隐藏Dock图标（Mac）| 间隔 | 隐藏菜单栏图标（Mac）|
        # 保存后重启生效 —— 需求①要那条 teal 提示词挪到「隐藏菜单栏图标（Mac）」
        # 复选框的右侧（贴着它的文字），不再挤在「隐藏Dock图标」后面。间隔因此插在
        # 第 1、2 项之间（index 1），末项是提示词标签。
        # 目标竖线分两态：
        #   最大化：仍是 anchor（「显示字段来源信息」那条线），最大化结果与本批
        #     需求之前逐位不变；
        #   还原态（需求②）：取「暗黑模式」的实测终态 x —— 需求写的是「隐藏菜单栏
        #     图标与暗黑模式严格上下对齐，且暗黑模式位置保持不变」，而窄态的
        #     anchor 是「显示字段内容信息」那条线，真机上两者并不重合（暗黑模式
        #     在 543、显示字段内容信息在 787），沿用 anchor 根本对不上。
        # 实测前必须让「界面外观行」真正落定：_pin_row_lead_width 只改约束不重排，
        # lw 的宽度也是刚 setGeometry 出来的，故窄态先 invalidate+activate 一次
        # lay_c（不 activate gridLayout_20，避免中间态把网格最小宽顶大）。
        dock_icon = ui.checkBox_hide_dock_icon
        label_42 = ui.label_42
        menu_icon = ui.checkBox_hide_menu_icon
        if not wide:
            lay_c.invalidate()
            lay_c.activate()
        target_b = anchor if wide else col_x(dark_c)
        # 行内顺序 [隐藏Dock图标 | 间隔 | 隐藏菜单栏图标 | 保存后重启生效]：
        # 前缀只到「隐藏菜单栏图标」，末尾还要给提示词标签留出它自己的宽度
        # （它是 Minimum 策略，sizeHint 即不裁字的下界）。
        prefix = dock_icon.sizeHint().width() + lay_b.spacing()
        tail_b = menu_icon.sizeHint().width() + lay_b.spacing() + label_42.sizeHint().width()
        avail_b = col_w - prefix - tail_b
        gap_b = target_b - row_x - prefix
        # 间隔项是 Fixed 策略的 QSpacerItem，它的 sizeHint 会算进行内最小宽度，
        # 故间隔一旦超过 avail_b，整行的最小宽度就会撑破网格列宽——那会把整页
        # （连同不许动的「暗黑模式」）一起推走，等于把需求②自己毁掉。
        # 放不下就把目标竖线夹到可行区间内：宁可离目标近一点也不裁字、不撑破列宽。
        if gap_b < 0:
            gap_b = 0
        elif gap_b > avail_b:
            gap_b = avail_b
        new_gap_b = gap_b
        if self._adv_dock_gap != new_gap_b:
            # PyQt6 的 insertSpacing 返回值恒为 None，改插完再 itemAt 取回
            spacer = self._adv_dock_spacer
            if spacer is not None and lay_b.indexOf(spacer) != 1:
                # 间隔项的位置变了（v2.7.6 起插在第 1、2 项之间），先摘掉旧的，
                # 否则行里会留下两个间隔项
                lay_b.removeItem(spacer)
                spacer = None
            if spacer is None:
                lay_b.insertSpacing(1, new_gap_b)
                spacer = lay_b.itemAt(1)
                self._adv_dock_spacer = spacer
            if spacer is not None:
                spacer.changeSize(new_gap_b, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                self._adv_dock_gap = new_gap_b
                changed = True

        # ---- 隐藏入口行：钉「隐藏 Emby 演员管理」，「隐藏NFO库管理」落锚点 ----
        # 钉住后还须把 nfo 本身也钉回 sizeHint 宽：QCheckBox 默认 sizePolicy 可拉伸，
        # 最大化时它会独吞余量把说明标签顶到 1323（实测），而复选框是左对齐绘制、
        # 文字只占 152，于是文字与说明标签之间出现 394px 空洞（用户截图红框）。
        # 钉死后余量全归末位的说明标签，它紧贴 nfo 文字右侧 6px。
        # 锚点统一取「显示字段来源信息」col_x(src_from)，**两态相同**：
        #   最大化：阶段一已把「刮削结束后自动退出软件」钉到 src_from 那条竖线，故
        #     anchor 恒等于 col_x(src_from)（真机实测 1200/1366/1536 三档 anchor 与
        #     nav_x 逐位相等 289/344/401），pin_d/room/need_d/ok_d 一个字节都没变，
        #     最大化结果与本批改动前逐位相同。
        #   最小化：需求是「隐藏NFO库管理向左移动到与它上下严格对齐，且它位置保持
        #     不变」，故该动的是 nfo 而不是 from（与本批撤销的
        #     _sync_advanced_page_debug_row 方向相反）。实测 nfo 的自然位在 from
        #     左侧（真机 1085×793 是 328 vs 311），所以这一步就是一次**左移**。
        # **为什么不能继续拿 anchor 分两态**：真机 dpr=1.25、屏幕 1536×864，用户
        # 还原态窗口 1085×793 的 _scroll_stretch_extra 已经是 **+33 > 0**，程序
        # 把它判成「最大化」，最小化那段代码根本不会执行（用户截图：三个目标纹丝
        # 不动）。该尺寸下阶段一的门也会卡掉（anchor 停在自然位 401 ≠ 311），
        # 于是宽态那一支算出 pin_d=298、room=291 < need_d=371（= nfo 111 + 说明
        # 标签 260）而整行放弃。改用 col_x(src_from) 后 pin_d=148、room=441 ≥ 371
        # 恰好放得下，而真最大化三档因 anchor≡nav_x 而逐位不变。
        # 放不下时整行放弃（解除钉宽、保持自然位）。下限只卡 nfo 的 sizeHint：说明
        # 标签「仅隐藏入口…」在窄态本就压得动（实测已被压到 240/211/151），拿它
        # 一起卡门会让窄态这一段永远放不下（实测 col_w=557 时 room 只剩 332 < 360）。
        actor = ui.checkBox_hide_actor_nav
        nfo = ui.checkBox_hide_nfo_nav
        hint = ui.label_nav_hide_hint
        nav_x = col_x(src_from)
        pin_d = nav_x - row_x - lay_d.spacing()
        room = col_w - pin_d - 2 * lay_d.spacing()
        need_d = nfo.sizeHint().width() + (hint.sizeHint().width() if wide else 0)
        ok_d = pin_d >= actor.sizeHint().width() and room >= need_d
        changed |= self._pin_row_lead_width(actor, pin_d if ok_d else None)
        changed |= self._pin_row_lead_width(nfo, nfo.sizeHint().width() if ok_d else None)

        if changed:
            for lay in (lay_a, lay_b, lay_d, lay_c):
                lay.invalidate()
                lay.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()

        # ---- 窄态阶段一（本批需求）：「刮削结束后自动退出软件」右移到「隐藏菜单栏图标」----
        # 必须排在上面那批 activate 之后：窄态下「隐藏菜单栏图标」的左缘是由第 8 行
        # 的 gap_b 决定的，而 gap_b 又由本方法的 anchor 算出——只有这批 activate 跑完
        # 它才是终态坐标（实测 1030×753 为 435），提前量到的是上一遍的旧值。
        # 反过来本方法也不受这一段影响：第 2 行是 (2,1) 那格，与第 8 行不同格，
        # 钉 auto_start 只改它自己的格内几何，不会把第 8 行的坐标再推走。
        # 宽态不需要这一段：那时「隐藏菜单栏图标」与「刮削结束后自动退出软件」
        # 本来就同在「显示字段来源信息」那条竖线上（实测 1100×800 起四档全等），
        # 阶段一已在上方把它对到位。
        if not wide:
            menu_x = col_x(menu_icon)
            pin_m = menu_x - row_x - lay_2.spacing()
            room_m = col_w - pin_m - lay_2.spacing()
            ok_m = pin_m >= auto_start.sizeHint().width() and room_m >= anchor_box.sizeHint().width() and menu_x > row_x
            if self._pin_row_lead_width(auto_start, pin_m if ok_m else None):
                lay_2.invalidate()
                lay_2.activate()
                ui.gridLayout_20.invalidate()
                ui.gridLayout_20.activate()

        # ---- 下半页三处右移对齐：必须排在 gridLayout_20.activate() 之后 ----
        # 需求①的锚点「隐藏NFO库管理」正是上面这批 activate 才定下的最终 x，
        # 提前量到的是它被等分推到右缘的旧值（用户截图红框里那两个「关」就是这么
        # 被钉歪的）。changed 为假时网格几何本就是终态，照量不误。
        self._sync_advanced_page_tail_align()

        # ---- 保留任务行：「无限次刮削」落到目标竖线（两态生效） ----
        # 「无限次刮削」自身的位置由前导项「记住任务，重启续刮」的钉宽决定，只钉
        # 前导项即可。目标竖线按**窗口是否真·最大化**分两态（不能用几何拉伸量：
        # 真机还原态窗口 1085×793 的拉伸量已是 +33 > 0，会被误判成最大化，
        # 「最小化时」那一支根本不执行——见 _advanced_page_window_maximized）：
        #   最大化：仍是「停止刮削时」col_x(stop_scrape)，最大化结果与本批需求之前
        #     逐位相同（页面布局、控件、组件、提示词全部保持不变）；
        #   还原态（v3.0 需求①）：取「显示字段来源信息」col_x(src_from) —— 需求
        #     原话「最小化时无限次刮削向左移动到与显示字段来源信息严格上下对齐的
        #     位置，显示字段来源信息位置保持不变」。真机还原态的「停止刮削时」钉
        #     不上（同行前导项「退出软件时」sizeHint 太大，整行放弃后它停在自然位
        #     543），「显示字段内容信息」那条线（787）又太靠右，故只能取「显示字段
        #     来源信息」——它自己不许动，实现同样只钉前导项「记住任务，重启续刮」。
        # 本段必须排在 _sync_advanced_page_tail_align() 之后：下半页那几行会改
        # gridLayout_20 的列宽，提前量到的是旧列宽下的坐标。row5 与 row6 同处
        # gridLayout_20 的 col1，行左缘天然相等，但仍按实测分开起算，避免布局
        # 边距假设。
        lay_r = ui.horizontalLayout_89
        remain_task = ui.checkBox_remain_task
        infinite_scrape = ui.checkBox_infinite_scrape
        row5_x = col_x(remain_task)
        if self._advanced_page_window_maximized():
            want_r = col_x(stop_scrape)
        else:
            want_r = col_x(src_from)
        col_w_r = host.width() - row5_x
        pin_r = want_r - row5_x - lay_r.spacing()
        ok_r = (
            want_r > row5_x
            and pin_r >= remain_task.sizeHint().width()
            and col_w_r - pin_r - lay_r.spacing() >= infinite_scrape.sizeHint().width()
        )
        if self._pin_row_lead_width(remain_task, pin_r if ok_r else None):
            lay_r.invalidate()
            lay_r.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()

    def _sync_advanced_page_move_file_align(self) -> None:
        """高级页：「移动文件」行的两枚复选框与「界面外观」行严格上下对齐。

        需求：「覆盖旧文件」与「隐藏边框（美观样式）」严格上下对齐、「保留旧文件」
        与「暗黑模式」严格上下对齐，且锚点两枚自身位置保持不变。

        做法：新行与「界面外观」行同构（QFrame → 普通子 QWidget → QHBoxLayout），
        两行同处 gridLayout_20 的 col1，行左缘天然相等；只要把新行前导项
        「覆盖旧文件」钉成与锚点前导项「隐藏边框（美观样式）」等宽，末位
        「保留旧文件」就精确落在「暗黑模式」的竖线上（末位项吃掉行内全部余量，
        自身左对齐绘制）。锚点行一个字都不动：只读它的实测宽度，不改它的约束。

        容器宽度跟着锚点容器走（两行行内几何完全一致）；放不下时（剩余空间不足
        末位项的 sizeHint，会裁字）宁可把容器加宽让字显示完整，也绝不压窄
        末位项——压窄会改变它的左缘，需求就破了。容器是 frame 的普通子 QWidget，
        允许与锚点容器一样略微溢出 frame（锚点容器本身就是 550 设计宽）。
        """

        ui = self.Ui
        host = ui.gridLayoutWidget_20
        if not host.isVisibleTo(self):
            return

        lw_c = ui.layoutWidget5  # 锚点容器（界面外观行）
        lay_c = ui.horizontalLayout_62  # 锚点行内布局
        lead_c = ui.checkBox_hide_window_title  # 锚点第 1 项（宽度即新行前导项的目标宽度）
        lw_m = getattr(ui, "layoutWidget_move_file", None)  # 新行容器
        lay_m = getattr(ui, "horizontalLayout_move_file", None)  # 新行行内布局
        over = getattr(ui, "checkBox_move_overwrite", None)  # 新行第 1 项
        keep = getattr(ui, "checkBox_move_keep", None)  # 新行末位项
        if lw_m is None or lay_m is None or over is None or keep is None:
            return

        # 锚点行必须先落定：钉宽只改约束不重排，末位项的坐标要等布局真正
        # activate 之后才是终态。
        lay_c.invalidate()
        lay_c.activate()

        # 新行容器与锚点容器同起点同宽：两行的行内几何完全一致
        if lw_m.width() != lw_c.width():
            lw_m.setGeometry(lw_m.x(), lw_m.y(), lw_c.width(), lw_m.height())
        lay_m.invalidate()
        lay_m.activate()

        margins = lay_m.contentsMargins()
        spacing = lay_m.spacing()
        # 末位「保留旧文件」要落在「暗黑模式」的竖线上 → 前导项宽度取锚点前导项宽度
        pin = lead_c.width()
        need = margins.left() + pin + spacing + keep.sizeHint().width() + margins.right()
        if lw_m.width() < need:
            # 装不下就把容器加宽（普通子 QWidget，允许略微溢出 frame），
            # 绝不压窄末位项——压窄会改变它的左缘，需求就破了。
            lw_m.setGeometry(lw_m.x(), lw_m.y(), need, lw_m.height())
            lay_m.invalidate()
            lay_m.activate()
        ok = pin >= over.sizeHint().width()
        if self._pin_row_lead_width(over, pin if ok else None):
            lay_m.invalidate()
            lay_m.activate()
        # 末位项的最终左缘必须与「暗黑模式」一致，否则说明前导项宽度没生效
        # （例如字体未就绪导致 sizeHint 变化），此时不强行改动锚点。

    def _sync_advanced_page_task_mode_align(self) -> None:
        """高级页：「任务模式」行的「存储在网盘」与「暗黑模式」严格上下对齐。

        需求（2026-10-23，最小化/最大化两态各一张截图）：
          还原态「存储在网盘」**向左**移到与「暗黑模式」严格上下对齐；
          最大化态「存储在网盘」**向右**移到与「暗黑模式」严格上下对齐；
          「暗黑模式」自身位置保持不变（一个字都不动）。

        为什么不能靠 .ui 里的固定几何：任务模式行的内嵌 widget 在设计态是
        `(0,-10,550,51)`，而「界面外观」行的 layoutWidget5 宽度会被
        `_sync_advanced_page_align` 按窗口状态改写（还原态钉前导项、最大化态
        加宽到 `2*(anchor-row_x)-spacing`，实测 1085×793 是 416、1536×864 是 716），
        两行宽度一旦不等，两项均分的第 2 项就落不到同一条竖线上（实测 1085 时
        「存储在网盘」379 vs「暗黑模式」312，1536 时 379 vs 462）。

        做法与 `_sync_advanced_page_move_file_align` 同构（两行同处 gridLayout_20
        的 col1，行左缘天然相等）：
          ① 容器宽度取锚点容器 layoutWidget5 的实测宽度；
          ② 前导项「存储在本地」钉成锚点前导项「隐藏边框（美观样式）」的实测
             宽度——锚点行在还原态是「钉前导项」、最大化态是「两项均分」，两种
             情况下这条等式都成立，末位「存储在网盘」于是精确落在「暗黑模式」
             的竖线上；
          ③ 放不下（剩余空间不足末位项 sizeHint，会裁字）时把容器加宽，绝不压窄
             末位项——压窄会改变它的左缘，需求就破了。
        锚点行只读不写，位置保持不变。
        """

        ui = self.Ui
        host = ui.gridLayoutWidget_20
        if not host.isVisibleTo(self):
            return

        lw_c = ui.layoutWidget5  # 锚点容器（界面外观行）
        lay_c = ui.horizontalLayout_62  # 锚点行内布局
        lead_c = ui.checkBox_hide_window_title  # 锚点第 1 项（宽度即前导项目标宽度）
        lw_t = getattr(ui, "layoutWidget_task_mode", None)  # 任务模式行容器
        lay_t = getattr(ui, "horizontalLayout_task_mode", None)  # 任务模式行内布局
        local = getattr(ui, "checkBox_task_store_local", None)  # 任务模式行第 1 项
        netdisk = getattr(ui, "checkBox_task_store_netdisk", None)  # 任务模式行末位项
        if lw_t is None or lay_t is None or local is None or netdisk is None:
            return

        # 锚点行必须先落定：钉宽只改约束不重排，末位项的坐标要等布局真正
        # activate 之后才是终态。
        lay_c.invalidate()
        lay_c.activate()

        # 容器与锚点容器同宽：两行行内几何一致，第 2 项才落在同一条竖线
        if lw_t.width() != lw_c.width():
            lw_t.setGeometry(lw_t.x(), lw_t.y(), lw_c.width(), lw_t.height())
        lay_t.invalidate()
        lay_t.activate()

        margins = lay_t.contentsMargins()
        spacing = lay_t.spacing()
        pin = lead_c.width()
        need = margins.left() + pin + spacing + netdisk.sizeHint().width() + margins.right()
        if lw_t.width() < need:
            # 装不下就把容器加宽（frame 的普通子 QWidget，允许略微溢出 frame），
            # 绝不压窄末位项——压窄会改变它的左缘，需求就破了。
            lw_t.setGeometry(lw_t.x(), lw_t.y(), need, lw_t.height())
            lay_t.invalidate()
            lay_t.activate()
        ok = pin >= local.sizeHint().width()
        if self._pin_row_lead_width(local, pin if ok else None):
            lay_t.invalidate()
            lay_t.activate()

    def _sync_advanced_page_rest_interval_align(self, wide: bool) -> None:
        """还原态：「每次间隔」时长框右缘缩到与「间歇刮削」文件数框右缘严格对齐。

        本批需求②。同一 grid（`gridLayout_20`）col1 上的两行：
        row3 = `horizontalLayout_109`（间歇刮削：☑连续刮削 + 文件数框 + 「个文件后，
        自动休息」+ 休息时长框 + 「（时:分:秒）」），row4 = `horizontalLayout_104`
        （☑每次间隔 + 间隔时长框 + 长说明标签）。**长的是 hl109**（真实字体下需要
        76+141+117+141+80 + 4×6 = 579，而 hl104 只要 76+141+314 + 2×6 = 543），
        窄态下 hl109 先放不下，Qt 只能压缩行内**唯一还压得动的项**——两枚
        `QLineEdit`（它们 sizePolicy 是 Fixed 可以被压，标签的 minimumSizeHint ==
        sizeHint 故一格不让），于是 `lineEdit_rest_count` 被压窄；hl104 那行却仍有
        余量、`lineEdit_timed_interval` 保持满宽 141px，右缘于是越过上面那枚的
        右缘——正是用户红线标出的那截参差。**锚点行与其余控件一律不动**，只缩
        每次间隔这一枚，钉成「右缘 == 文件数框右缘」：
            want = (anchor 右缘) - (target 左缘)
        缩的是 hl104 的第二项，故只有它右侧的 `label_84` 会左移、行内总宽变小；
        hl104 本来就有余量、不会去挤行外任何东西。

        量目标自然位之前**必须先解除上一遍自己的钉宽并重排**（与
        `_sync_advanced_page_debug_row` 的「自我强化」同坑：带着旧钉宽去量，量到的
        是自己钉出来的落点）。`want` 只有在「确实更窄且仍夹得住内容」时才钉，放不下
        就保持自然态、绝不硬压。最大化态**只做解除**：那一态两枚框本来就都是满宽
        141px，钉不钉一样，故最大化界面逐像素不变。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_gaoji
        if not content.isVisibleTo(self):
            return
        anchor_row = ui.horizontalLayout_109
        target_row = ui.horizontalLayout_104
        anchor = ui.lineEdit_rest_count
        target = ui.lineEdit_timed_interval
        if not (
            anchor_row is not None
            and target_row is not None
            and anchor_row.parentWidget() is not None
            and target_row.parentWidget() is not None
            and anchor is not None
            and target is not None
            and anchor.isVisibleTo(self)
            and target.isVisibleTo(self)
        ):
            return

        def cx(widget) -> int:
            """控件左缘映射到滚动内容的绝对 x（跨分支必须经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x()

        def anchor_right() -> int:
            return cx(anchor) + anchor.width()

        # ---- 最大化态只解除：那一态本来就等宽，钉了也是徒增一次重排 ----
        if wide:
            if self._pin_row_lead_width(target, None):
                target_row.invalidate()
                target_row.activate()
            return

        # ---- 还原态：先解除并重排，量到的是自然位而不是自己上遍钉出来的落点 ----
        if self._pin_row_lead_width(target, None):
            target_row.invalidate()
            target_row.activate()
        anchor_row.invalidate()
        anchor_row.activate()
        want = anchor_right() - cx(target)
        if not (0 < want < target.width() and want >= target.minimumSizeHint().width()):
            return
        if self._pin_row_lead_width(target, want):
            target_row.invalidate()
            target_row.activate()
        # 读回纠偏：重排后可能残留 1px 取整误差，补回去。
        drift = anchor_right() - cx(target) - target.width()
        if drift:
            self._pin_row_lead_width(target, target.width() - drift)
            target_row.invalidate()
            target_row.activate()

    def _sync_advanced_page_tail_align(self) -> None:
        """高级页下半三处对齐（三条需求分属最大化 / 最小化两态），锚点一律不动。

        需求分两批、方向相反，实现上按「落点取哪个锚点」区分：
          最大化态（第一批）：
          ① 「保存日志」「检查更新」两行的「关」右移到与「隐藏NFO库管理」严格
             上下对齐；
          ② 「隐藏窗口」行的「点最小化按钮」右移到与「显示字段来源信息」严格
             上下对齐；
          ③ 同一行最右侧的「无」右移到与「显示字段内容信息」严格上下对齐。
          最小化态（第二批，「最大化时页面、布局、控件、提示词等均保持不变」）：
          ① 同上的两行「关」**向左**移到与「隐藏NFO库管理」严格上下对齐——而
             上一条需求已把窄态的 nfo 钉到「显示字段来源信息」那一列（见
             _sync_advanced_page_align 隐藏入口行段），故两枚「关」实际是随它
             一起落到 from_log 那条竖线上，三者同列；
          ② 「点最小化按钮」**向左**移到与「隐藏NFO库管理」严格上下对齐
             （注意最小化态的锚点是 nfo 而非 from_log，两态不同）；
          ③ 「无」**向左**移到与「显示字段内容信息」严格上下对齐（与最大化态
             同一锚点，故这一条两态共用同一份代码）。
        锚点自身（「隐藏NFO库管理」「显示字段来源信息」「显示字段内容信息」
        「显示刮削过程信息」）全程不动。

        三处根因不同，手法也不同，勿互相套用：
          ① 两行的容器（horizontalLayoutWidget_11 / _7）是 groupBox_17 / _4 的
             **直接子项**，被通用宽幅同步判成 _STRETCH、每遍按「设计宽+extra」
             拉宽并 invalidate+activate 内部行布局；行内两个单选均分余量（实测
             宽态 742/741），于是「关」的左缘随窗宽漂移。锚点自身也在同一次
             拉伸里被摆好，故只需**钉死前导项「开」**：行内只剩末位「关」可拉伸，
             它的左缘恒等于「容器左缘 + 钉宽 + spacing」，取钉宽 = 锚点x -
             「开」x - spacing 即严格对齐（与 _pin_row_lead_width 同一套）。
          ②③ 「隐藏窗口」行的容器 layoutWidget_17 **完全不参与拉伸**——它是
             frame_3 的子控件、frame_3 又是 gridLayoutWidget_20 的子控件，而
             通用同步只登记「顶层组框的直接子项」，故它四个尺寸下恒为 551x32、
             行内三个单选按 551 均分（实测 180/179/180，宽窄两态一模一样）。
             两个锚点却在另一个组框（groupBox_3）里、随该组一起被拉伸，行内位置
             与锚点位置之间没有任何联动。只能**钉死前两项 + 把容器加宽**：
             设 m/n 为「点最小化按钮」「无」的落点（相对容器左缘），钉
             「点关闭按钮」= m-spacing、钉「点最小化按钮」= n-m-spacing，则
             两者左缘分别恰为 m、n；容器宽须 ≥ n + 「无」sizeHint，否则末位被
             压到裁字（这一条与界面外观行加宽 layoutWidget5 是同款手法）。

        锚点与落点全部运行时 mapTo 实测，不写死像素。宽态实测（竖线换到
        checkBox_show_from_log 之后）：1920 为 nfo=589 / from=589 / data=1088、
        关=589、mini=589、none=1088；1100 最小的一档为 nfo=316 / from=316 /
        data=541、关=316、mini=316、none=541。窄态 1030 实测 nfo=294（=
        from 的自然位，本批需求把它左移到此）/ from=294 / data=495，关=294
        （钉宽 198）、mini=294（钉 close=192 / mini=176、容器 411）、
        none=486（→data，容器收窄）。窄态之所以也要做：nfo 在窄态是这半页
        靠右的一条竖线，且两枚「关」的窄态自然位 497 恰在它右侧 200px——
        不钉住就会一直歪着。mapTo 一律经公共祖先
        scrollAreaWidgetContents_gaoji 中转：三处目标分属 groupBox_17/_4
        （groupBox_12 的兄弟）与 frame_3（groupBox_12 的孙子），跨分支 mapTo 是
        未定义行为（同 _sync_guaxiaomulu_checkbox_align 的教训）。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_gaoji
        if not content.isVisibleTo(self):
            return
        # 判态用几何拉伸量而非 isMaximized()：窗口管理器最大化时先发尺寸、后发
        # 状态标志，那一拍 isMaximized() 还是 False，用户会看到「先在原位、再
        # 跳到对齐位」，与本页既有的隐藏NFO库管理/暗黑模式同款理由。
        wide = self._scroll_stretch_extra(self._adv_scroll) > 0
        nfo = ui.checkBox_hide_nfo_nav
        src_from = ui.checkBox_show_from_log
        src_data = ui.checkBox_show_data_log
        if not (nfo.isVisibleTo(self) and src_from.isVisibleTo(self) and src_data.isVisibleTo(self)):
            return

        def cx(widget) -> int:
            """控件左缘映射到滚动内容的绝对 x（跨分支必须经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x()

        changed = False
        lays: list = []

        nfo_x = cx(nfo)

        # ---- 两枚「关」：两态都跟 nfo ----------------------------------------------------
        # 宽态这是上一批需求②（nfo 已由 _sync_advanced_page_align 钉到 from_log
        # 那条竖线上），本批需求只要求最大化时逐位不变，故这一支原样保留。
        # 窄态此前跟的是「显示字段内容信息」（离屏实测 1030×753 = 497 / 1000×700
        # = 477，是这半页最靠右的那条竖线）；本批需求要两枚「关」**向左**移到
        # 「显示字段来源信息」那一列，改法是把锚点换成 nfo 即可——窄态的 nfo 已
        # 被钉到 from_log（离屏 294 / 300），两者同列，落点自然跟着左移过去
        # （497 → 294）。若那一段因放不下而放弃（820 宽），三者仍同列不散。
        off_x = nfo_x
        for cont, lay, lead, tail in (
            (ui.horizontalLayoutWidget_11, ui.horizontalLayout_13, ui.radioButton_log_on, ui.radioButton_log_off),
            (ui.horizontalLayoutWidget_7, ui.horizontalLayout_9, ui.radioButton_update_on, ui.radioButton_update_off),
        ):
            if not cont.isVisibleTo(self):
                continue
            need = off_x - cx(lead) - lay.spacing()
            room = cont.width() - need - lay.spacing()
            ok = need >= lead.sizeHint().width() and room >= tail.sizeHint().width()
            if self._pin_row_lead_width(lead, need if ok else None):
                changed = True
                lays.append(lay)

        # ---- ②③ 「点最小化按钮」/「无」；落点按态取，判据仍要防「放不下」 ----
        lw = ui.layoutWidget_17
        lay_h = ui.horizontalLayout_106
        frame3 = ui.frame_3
        close_r = ui.radioButton_hide_close
        mini_r = ui.radioButton_hide_mini
        none_r = ui.radioButton_hide_none
        if lw.isVisibleTo(self) and frame3.isVisibleTo(self):
            base = cx(lw)
            sp = lay_h.spacing()
            # 「点最小化按钮」：宽态对齐「显示字段来源信息」，窄态对齐「隐藏NFO库
            # 管理」。后者本批需求已钉到 from_log 那一列，故两态实际同落一条线
            # （离屏窄态实测两者都是 294）。取错会让它在还原后停在 from 上
            # 而 nfo 留在自然位（这正是需求①与需求②在窄态要求落到同一条竖线
            # 上的用意）。
            m = (cx(src_from) if wide else nfo_x) - base
            # 「无」：两态同一锚点「显示字段内容信息」。
            n = cx(src_data) - base
            w_close = m - sp
            w_mini = n - m - sp
            # 容器宽度只需「恰好放下「无」」，两个下界语义不同、勿混：
            #   下界取 lw.sizeHint()（168 = 三个单选 hint 之和 + 两个间隔），
            #     低于它末位必被压、裁字；
            #   上界取 frame3.width()，超出即越出 frame_3（frame 无布局，
            #     越界子控件会被父控件绘制区裁掉）。
            # 刻意**不**拿设计宽 551 当下界：n 随 extra 增长，extra 刚转正时
            # want_w 只有 400 出头（1100 宽实测 457 < 551），拿 551 卡门会让
            # 「刚过最大化线的那一大段窗宽」全部对不上（实测 1100x800 漏排）。
            # 宽态下把容器收窄到 457 不裁字：三项已各自钉到 ≥ sizeHint 的宽度。
            # 窄态容器同样会收窄（551 → 411），这一条是需求③要的「向左移动」。
            want_w = n + none_r.sizeHint().width()
            ok_h = (
                m > sp
                and n > m
                and w_close >= close_r.sizeHint().width()
                and w_mini >= mini_r.sizeHint().width()
                and lw.sizeHint().width() <= want_w <= frame3.width()
            )
            if ok_h:
                if self._pin_row_lead_width(close_r, w_close) | self._pin_row_lead_width(mini_r, w_mini):
                    changed = True
                if lw.width() != want_w:
                    lw.setGeometry(lw.x(), lw.y(), want_w, lw.height())
                    changed = True
                if lay_h not in lays:
                    lays.append(lay_h)
            else:
                # 真放不下（钉宽会裁字或越出 frame_3）：逐项解除并按设计宽复位。
                # 窄态实测 w_close/w_mini 均 ≥ sizeHint、want_w=411 落在
                # [168, 588] 内，故窄态不走这条分支。
                if self._pin_row_lead_width(close_r, None) | self._pin_row_lead_width(mini_r, None):
                    changed = True
                if lw.width() != self._ADV_HIDE_LW_W:
                    lw.setGeometry(lw.x(), lw.y(), self._ADV_HIDE_LW_W, lw.height())
                    changed = True
                if lay_h not in lays:
                    lays.append(lay_h)

        if not changed:
            return
        # 钉宽只改约束、不会立刻重排：必须显式 activate，否则要等下一轮事件，
        # 而那之前 resizeEvent 已经画完（用户看到「先在原位、再跳过去」）。
        for lay in lays:
            lay.invalidate()
            lay.activate()

    @staticmethod
    def _pin_row_lead_width(box, width) -> bool:
        """把行内前导控件钉成固定宽（width=None 表示解除），返回是否发生改动。

        见 _sync_advanced_page_align：只有钉死前导项，末位项的绝对位置才与
        列宽解耦。走 setFixedWidth（= setMinimumWidth + setMaximumWidth）而非
        move()，因为 layout 重新 activate 会覆盖 move()；解除时恢复
        (0, QWIDGETSIZE_MAX) 而不是 0，否则控件会被压成零宽。
        """
        if width is None:
            new_min, new_max = 0, 16777215  # 16777215 = QWIDGETSIZE_MAX
        else:
            new_min = new_max = max(0, int(width))
        if box.minimumWidth() == new_min and box.maximumWidth() == new_max:
            return False
        box.setMinimumWidth(new_min)
        box.setMaximumWidth(new_max)
        return True

    def _queue_nfo_post_cascade_sync(self) -> None:
        """tab 切换后第一拍：只排队，把全量同步留到级联落定后的第二拍。"""
        QTimer.singleShot(0, self._sync_page_layouts)

    def _settle_settings_after_switch(self) -> None:
        """切 tab/切页后同步落定设置页（首开 NFO 字段说明跳动修复）。

        现象：初次打开设置-NFO 的瞬间，「字段说明」按钮从右边跳到左边
        （再次打开不再出现）。根因链：
        1) tab 切换只走双拍 beats（280 行注释：直接读会拿到级联前 stale
           几何钉错 thirds，故第一拍只排队、第二拍才全量同步）；
        2) paint 发生在 beats 之前，首开第一拍常看到中间态视口
           （滚动条闪烁 805 级），trailing 按它把组框定格偏窄，
           field pin 误判溢出把按钮左移 → 肉眼看到跳动；第二拍落定后
           复位 640，之后各次打开几何早已落定、beats 全是 no-op，
           故不再跳。
        做法：currentChanged 上直连本方法（paint 之前执行），至多 3 轮
        {全量同步+泵事件}至稳（快照按钮 x/组宽/视口；trailing
        的 setGeometry 同步生效、泵让滚动条级联落定），切 tab 返回时几何
        已是终态（注：曾试 setUpdatesEnabled 关 paint 抑中间帧，反而扰动
        渲染扫描类量测致落点偏移 rd.x 203→213、country_year/tail 挂，
        已删除）。只接离散切换信号，不进 resize 路径；beats 原位保留
        作级联兜底；设置页/NFO 休眠时直接返回（零成本）。
        """
        ui = self.Ui
        if not ui.page_setting.isVisibleTo(self):
            return
        btn = ui.pushButton_field_tips_nfo
        if not btn.isVisibleTo(self):
            return
        gb = ui.groupBox_81
        sc = ui.scrollArea_13
        for _ in range(3):
            before = (btn.x(), gb.width(), sc.viewport().width())
            self._sync_page_layouts()
            # 只拦用户输入重入：布局/绘制/定时器照常 pump，deferred 输入事后补派，不丢事件
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            after = (btn.x(), gb.width(), sc.viewport().width())
            if after == before:
                break

    def _sync_settings_scrollbar_widths(self) -> None:
        """设置页各页签竖向滚动条厚度兜底（保证逐页等宽、有 sane 下限）

        这就是用户「演员/网络/高级（以及字幕/水印）几页滚动条看着更细」那个现象
        的修法。取证的坑在于：**必须先让设置页真正显示出来**再去量——stackedWidget
        里 page_setting 的下标是 4（不是 2），早前几版脚本按 2 进页，页面始终
        isVisibleTo False，本方法每次都在守卫处早退，于是量到的「12 页一致、都是
        16px」全是假象（那批数据只有真正被布局过的一条是真的）。
        正确取证：QT_SCALE_FACTOR=0.8（对应用户 1920x1080 + 125% 系统缩放）、
        窗口 1030x650、进入设置页后逐页切，**对每条可见滚动条 grab() 逐像素量**——
        修前 11 页里 10 页渲染宽度就是 12px（恰好落在字幕/水印/演员/网络/高级），
        修后 11 页全是 16px，与 QSS 声明一致。
        做法：切页落定后取各页厚度，只采信落在合理区间（8~48px）的读数，取
        其中最宽者为准，把其余一律 setFixedWidth 对齐；已一致时完全 no-op
        （幂等）；除滚动条自身厚度外不改任何几何，组框与行列宽由末尾的全量
        同步按新视口重排。
        基准含软件界面结果树与软件日志主栏的滚动条（只读不钉）：设置页各页签
        的目标厚度与这两处取最宽者，保证设置页滚动条与主界面/日志页同宽。
        读数来源（离屏整窗实测，勿再改回 width()）：厚度取 **sizeHint()** 而非
        width()。QSS 里 `QScrollBar:vertical{width:16px}` 是权威厚度，它落在
        sizeHint 上；width() 只是控件当前几何，未 polish / 未被布局过的页签停在
        平台默认 PM_ScrollBarExtent（实测 12，比 QSS 少 4）。这正是「首开某页
        是宽的、切走再回来变窄、且每次落在随机页签」的成因：先用 width() 取到
        某个未抛光页的 12，再被 setFixedWidth 永久钉死（min=max=12 覆盖 QSS），
        12 页一齐降级且再也回不到 16。sizeHint 不受布局时序影响，12 页恒为 16。
        取最宽者（max）而非最窄：一次坏读数只能把自己拉回众数，不能拖着全组
        降级——这与本方法文档、docs/Development.md 及
        tests/test_window_state_matrix.py 的断言一致（min 会让该回归测试失败）。
        另：未布局页除厚度外还可能报出荒唐的**长度**（Qt 默认 100px），本方法只
        管厚度，不涉长度。
        注：本项目 Python 3.14 free-threading 下信号槽内抛异常会直接带崩
        进程（已见 add_log 槽事故），故整体 try/except 兜底。
        """
        try:
            ui = self.Ui
            if not ui.page_setting.isVisibleTo(self):
                return
            bars = []
            for index in range(ui.tabWidget.count()):
                page = ui.tabWidget.widget(index)
                if page is None:
                    continue
                area = page.findChild(CustomScrollArea)
                if area is None:
                    continue
                bar = area.verticalScrollBar()
                for widget in (area, area.viewport(), bar):
                    widget.ensurePolished()
                bars.append(bar)
            if len(bars) < 2:
                return
            # 只采信合理区间读数：未布局页可能报出荒唐值（Qt 默认 100px 那种），
            # 必须滤掉，否则会把所有页签错钉成 100px（离屏实测教训）
            # 软件界面/软件日志的滚动条只做宽度基准（只读不钉），保证设置页与之同宽
            ref_bars = []
            for ref in (ui.treeWidget_number, ui.textBrowser_log_main):
                try:
                    ref_bar = ref.verticalScrollBar()
                    ref_bar.ensurePolished()
                    ref_bars.append(ref_bar)
                except Exception:
                    continue
            declared = [bar.sizeHint().width() for bar in bars + ref_bars]
            sane = [width for width in declared if 8 <= width <= 48]
            if not sane:
                # sizeHint 全不可信时退回几何读数，仍取最宽者兜底（含主界面/日志基准）
                sane = [bar.width() for bar in bars + ref_bars if 8 <= bar.width() <= 48]
                if not sane:
                    return
            target = max(sane)
            corrected = False
            for bar in bars:
                # 按「约束」而不是按「几何」判定是否需要钉：若某条 width() 恰好已经
                # 等于 target（例如首开时唯一被布局过的那一条），几何判据会把它判为
                # 已是宽态而放过——那条就永远只靠 QSS 撑着，后续任何一次 polish/
                # 布局都能把它打回平台默认厚度，正是「随机落在某个页签」的残余。
                # 逐条钉成 min=max=target 才是幂等且封死的终态。
                if bar.minimumWidth() != target or bar.maximumWidth() != target:
                    bar.setFixedWidth(target)
                    corrected = True
            if corrected:
                # 改宽只改几何不改绘制：抛光时缓存的 groove/handle 矩形仍是旧值，
                # 必须重新抛光让绘制跟上，否则属性对了画面仍是窄的（逐像素实测教训）。
                # 抛光不改几何，不会自激成 resize 回环。
                for bar in bars:
                    try:
                        bar.style().unpolish(bar)
                        bar.style().polish(bar)
                        bar.update()
                    except Exception:
                        continue
                # 视口随之变化，立刻按新视口重排（否则组框按旧视口定格）
                self._sync_page_layouts()
        except Exception:
            return

    # 设置-刮削网站：「网站偏好」组里「指定网站」下拉框右缘对齐「锁定类型」下拉框
    _SITE_PREF_COMBO = "comboBox_website_all"  # 指定网站（row 3 col 1，gridLayout_28）
    _SITE_PREF_COMBO_REF = "comboBox_fixed_scraping_type"  # 锁定类型（row 17 col 1，gridLayout_36）
    _SITE_PREF_SCROLL = "scrollArea_8"  # 刮削网站页签的滚动区
    # 「刮削不到？看这里！」按钮：groupBox_11 的绝对定位子控件（不在任何 layout 里），
    # y 由 _sync_scrape_note_vertical 按下拉框实时中心重钉，故不随行高/字号漂移。
    _SITE_PREF_NOTE_BUTTON = "pushButton_scrape_note"

    # 两个下拉框同在 scrollAreaWidgetContents_guaxiaowangzhan 内、都落在各自网格的
    # 第 1 列，故该 content 是二者的公共祖先（跨分支 mapTo 必须经公共祖先中转）。
    # 「网站偏好」只有 2 列、「类型刮削网站」有 4 列（多出「编辑网站」「网站优先」
    # 两个按钮列），列宽因此天然差 111px（离屏实测窄态 513-402、宽态 1403-1292，
    # 两态差值恒等），表现为「指定网站」下拉框右缘越过「锁定类型」111px。
    def _sync_site_pref_combo_width(self) -> None:
        """设置-刮削网站：「指定网站」下拉框右缘收缩到「锁定类型」下拉框右缘。

        用户需求：「软件设置-刮削网站-指定网站下拉框右侧收缩到锁定类型右侧的位置」。
        做法：量出参考下拉框（锁定类型）在公共祖先 content 里的右缘，换算成
        「指定网站」下拉框的可用宽度上限并 setMaximumWidth 钉住——不用 move()/
        setGeometry()，因为两者都在 QGridLayout 里，layout 重新 activate 会直接
        覆盖绝对坐标（与 _pin_row_lead_width 同一结论），而宽度上限是布局本身
        遵守的约束。每次全量同步都按当前视口重算，故窄态/宽态各自收敛到差值 0，
        且窗口在两态间来回变化时宽度会跟着重新张开（只减不增会锁死在窄态）。
        幂等：目标宽度不变时不再触碰控件；本方法在整条 resize 路径上高频调用，
        故对休眠页签做可见性早退（成本近似为零，且避免从未布局的假读数）。
        """
        ui = self.Ui
        combo = getattr(ui, self._SITE_PREF_COMBO, None)
        ref = getattr(ui, self._SITE_PREF_COMBO_REF, None)
        if combo is None or ref is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            # 从未打开过的页签：两个下拉框还停在未经布局的默认几何（实测 100px 宽），
            # 此时量到的右缘是假读数，据此钉上限会把宽度钉死在错值上。整段早退、
            # 不碰任何约束，等首次切进本页签（currentChanged → _settle_settings_after_switch
            # 与 _queue_nfo_post_cascade_sync 都会再跑一遍全量同步）时几何已落定再对齐。
            return
        content = scroll.widget()
        # 落定前置：本控制器量的是两个下拉框的实时右缘，而它们所在的组框宽度由
        # CustomScrollArea 的宽幅同步按当前视口改写。首次打开本页签时宽幅同步还
        # 没跑（组框停在未布局的默认宽度，实测两框仅 100~219px 宽），此刻量到的
        # 是中间态假读数——若据此钉上限，宽度会被永久钉死在 147px，再也张不开
        # （钉住后布局不再扩张，钉值与实际需求形成自锁）。故先显式重跑一遍宽幅
        # 同步（同 _sync_nfo_page_align 对 scrollArea_13 的处理），再量终态。
        scroll.sync_wide_children_width()
        # 设计上限取 .ui 的 16000（comboBox_website_all 声明的 maximumSize 宽），
        # 首次进入时记下，供「读数无意义」分支原样交回布局——不能拿 QWIDGETSIZE_MAX
        # 顶替，那会永久改掉设计约束。
        if self._site_pref_combo_design_max is None:
            self._site_pref_combo_design_max = combo.maximumWidth()
        design_max = self._site_pref_combo_design_max
        # 尚未布局（宽高为 0）或滚动区没内容时读数无意义，放开上限交回布局
        if content is None or combo.width() <= 0 or ref.width() <= 0 or content.width() <= 0:
            if combo.maximumWidth() != design_max:
                combo.setMaximumWidth(design_max)
            return
        combo_x = combo.mapTo(content, QPoint(0, 0)).x()
        ref_right = ref.mapTo(content, ref.rect().bottomRight()).x() + 1
        target = ref_right - combo_x
        floor = combo.minimumSizeHint().width()
        if target < floor:
            # 视口窄到「锁定类型」所在四列网格（多出「编辑网站」「网站优先」两列）
            # 先被挤瘪，参考框右缘已退到本框最小可用宽度之内，此时对齐目标不可达
            # （实测 720x680 窗口下目标仅 93px < 最小 147px）。钉一个低于自身最小
            # 尺寸的上限只会与布局互相拉扯，故交回设计上限、放弃本轮对齐。
            if combo.maximumWidth() != design_max:
                combo.setMaximumWidth(design_max)
            return
        if combo.maximumWidth() != target:
            combo.setMaximumWidth(target)

    def _sync_scrape_note_vertical(self) -> None:
        """设置-刮削网站：「刮削不到？看这里！」按钮垂直居中到「指定网站」下拉框。

        用户需求：「向上移动后要居于下拉框水平中间的位置」。该按钮是 groupBox_11
        的绝对定位子控件（不在任何 layout 里），.ui 里声明的 y 是**死值**——网格行高
        会随字体变化（下拉框上方的 widget_field_priority_options 行、以及各说明
        文字的折行数都参与撑高），行序一换这个死值就与下拉框错行。只改 .ui 能对齐
        当前默认字号，一旦用户改 UI 缩放（comboBox_ui_scale 支持 80%~300%，
        init.py 的 _UI_SCALE_VALUES）或系统字号，行高就变、按钮跟着漂。

        故这里在每次全量同步里按「下拉框实时中心」重钉按钮 y：move() 只改 y、不碰
        宽度与 x（x 由 CustomScrollArea 的 _DOCK_RIGHT 右缘锚定负责，见
        CustomClass.py 的 _classify_inner——那里判 _DOCK_RIGHT 依赖按钮的 right()
        落位，本方法不动 x 故不与之冲突）。只用 setGeometry 的 y 分量，保持 x/宽高
        原样。
        休眠页签整段早退：从未布局时下拉框停在未布局的假几何（实测 y=28、高 30），
        据此钉 y 会把按钮钉到错行且再无事件纠正（休眠读取数是同 _sync_site_pref_
        combo_width 里的假读数陷阱）。切进本页签时 currentChanged 的 settle/beats
        会补跑全量同步，那时几何已落定。
        幂等：目标 y 不变时不触碰控件（本方法在整条 resize 路径上高频调用）。
        """
        ui = self.Ui
        combo = getattr(ui, self._SITE_PREF_COMBO, None)
        button = getattr(ui, self._SITE_PREF_NOTE_BUTTON, None)
        if combo is None or button is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            return
        # 取按钮的父控件（groupBox_11）作公共祖先：按钮直接挂在它下面，而下拉框
        # 嵌在再下一层的 layoutWidget1 网格里，两者的 y 分属不同坐标系，必须经
        # 公共祖先中转才能直接比（直接用下拉框的 parentWidget 会差出
        # layoutWidget1 在组框内的偏移 28px）。两者高度不同（30 vs 26），
        # 用中心点对齐。
        anchor = button.parentWidget()
        if anchor is None or combo.height() <= 0 or combo.width() <= 0:
            return
        combo_y = combo.mapTo(anchor, QPoint(0, 0)).y()
        target = combo_y + (combo.height() - button.height()) // 2
        if button.y() != target:
            button.move(button.x(), target)

    # 设置-刮削网站：「类型刮削网站」组里国产传媒说明（label_232）与「动漫里番」
    _SITE_TYPE_GRID = "gridLayout_36"  # 类型刮削网站网格（layoutWidget_6 上的四列网格）
    _SITE_TYPE_GUOCHAN_TIP = "label_232"  # 国产传媒说明（row 9 col 1~3，wordWrap）
    # 单行判定容差：heightForWidth 的返回值与 fontMetrics().height() 有零头差
    _SITE_TYPE_SINGLE_LINE_SLACK = 3

    def _sync_site_type_tip_single_line(self) -> None:
        """设置-刮削网站：宽态国产传媒说明单行时收回空行，「动漫里番」上移一行。

        用户需求：「软件设置-刮削网站-类型刮削网站页最大化时将动漫里番向上移动一行，
        因为提示词已经在一行显示了，目前最大化时动漫里番离国产番号的间距太大了」，
        且「最小化时的界面、布局、组件、控件、提示词等等均保持不变」。

        根因：label_232（国产传媒说明）开了 wordWrap，.ui 里钉了 maximumSize 高 34
        （=两行），而 QGridLayout 定行高走 sizeHint 受 maximumSize 夹取、**不走
        heightForWidth**（离屏实测：把上限放开后各宽度下都取 sizeHint 的 43~78px，
        从不按实际折行数收缩）。窗口最大化后该说明所在的三列可用宽度足够，提示词
        只剩一行（实测 heightForWidth = 15px），行高却仍被钉死在 34px，行下方留出
        约 19px 死白，「动漫里番」整块被顶下去一行——正是用户截图里的大间距。
        只改 .ui 无解（静态值无法随窗口宽度变化），只能在运行时收敛。

        做法：量出该说明在当前终态宽度下的真实需要高度 need = heightForWidth(width)，
        仅当它确实只占一行（need ≤ 单行高 + 容差）且该页已被拉宽（见
        _scroll_stretch_extra）时，把 maximumSize 高收成 need，让网格压缩掉这一行；
        同一笔高度再以 gridLayout_36 的 bottomMargin 原样还回去，使网格自然高度与
        容器高度之差（余量 36px）保持不变——否则 QGridLayout 会把少掉的高度摊到 18
        个 verticalSpacing 上（每档 +1px），「动漫里番」只上移 6px 而非一行（实测）。

        最小化不变：窄态该说明仍需两行及以上（实测 1014 及以下 need ≥ 30px），
        freed = 0，本方法对控件与布局零改动，与改动前逐像素一致；且宽窄来回切换时
        两侧都能各自收敛回终态（离屏实测 1014→1400→1920→1014 全程验证）。
        幂等：两个目标值与现值一致时完全不触碰控件，故在整条 resize 路径上高频
        调用无副作用。need 与单行高都取自当前字体实测，与 UI 缩放无关。
        """
        ui = self.Ui
        grid = getattr(ui, self._SITE_TYPE_GRID, None)
        tip = getattr(ui, self._SITE_TYPE_GUOCHAN_TIP, None)
        if grid is None or tip is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            # 休眠页签整段早退：从未布局时 tip 停在未经布局的默认宽度，量到的 need
            # 是假读数，据此收上限会把高度永久钉死在错值上（与
            # _sync_site_pref_combo_width 同一个假读数陷阱）。切进本页签时
            # currentChanged 的 settle/beats 会补跑全量同步，那时几何已落定。
            return
        # 设计上限取 .ui 声明的 maximumSize 高（34px，两行），首次进入时记下，
        # 窄态据此原样交回布局——不能拿 QWIDGETSIZE_MAX 顶替，那会永久改掉设计约束。
        if self._site_type_tip_design_max_h is None:
            self._site_type_tip_design_max_h = tip.maximumHeight()
        design_max_h = self._site_type_tip_design_max_h
        # 尚未布局（宽度为 0）或控件不开 wordWrap 时 heightForWidth 无意义，
        # 放行交回布局（不做任何改动）。
        if not tip.hasHeightForWidth() or tip.width() <= 0:
            if tip.maximumHeight() != design_max_h:
                tip.setMaximumHeight(design_max_h)
            return
        need = tip.heightForWidth(tip.width())
        line_h = tip.fontMetrics().height()
        freed = 0
        if self._scroll_stretch_extra(scroll) > 0 and 0 < need <= line_h + self._SITE_TYPE_SINGLE_LINE_SLACK:
            # 只在真正单行时收紧：两行及以上说明本来就占满 34px，收了反而截断提示词
            freed = max(0, design_max_h - need)
        if tip.maximumHeight() != design_max_h - freed:
            tip.setMaximumHeight(design_max_h - freed)
        # 收回的高度以底边距还回，保持网格自然高度不变 → 少掉的行高不会被摊进间隔
        margins = grid.contentsMargins()
        if margins.bottom() != freed:
            grid.setContentsMargins(margins.left(), margins.top(), margins.right(), freed)
            grid.invalidate()
            grid.activate()
