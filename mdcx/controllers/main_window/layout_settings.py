"""设置页的刮削目录 / 命名 / 水印 / 网络四块布局。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import (
    QPoint,
)
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QLayout,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)


class LayoutSettingsMixin:
    # 刮削目录页文件清理提示的设计宽（MDCx.ui label_271 设计几何 140,490,381,16）。
    _GUAXIAOMULU_TIP_DESIGN_W = 381

    def _sync_guaxiaomulu_page_align(self, _scroll=None) -> None:
        """设置-刮削目录：把本页两处对齐入口整条重跑（钩子用，零参可调）。

        挂在刮削目录滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「对齐」在同一个
        事件里做完，中间态（提示被拉宽后居中右偏、「刮削时自动清理」先停在右缘）
        不会被绘制。休眠页直接返回，由切 tab 的 showEvent 补齐。

        顺序敏感：两处都要排在通用拉伸之后，且「刮削时自动清理」换列排在提示对齐
        之后——前者的对齐位置依赖网格终态列宽，而提示对齐内部会重跑一次
        sync_wide_children_width()（宽态），把它钉回右缘。
        """
        scroll = _scroll if _scroll is not None else getattr(self, "_guaxiaomulu_scroll", None)
        self._sync_guaxiaomulu_clean_tip_align(scroll)
        self._sync_guaxiaomulu_checkbox_align(scroll)

    def _sync_guaxiaomulu_clean_tip_align(self, scroll=None) -> None:
        """设置-刮削目录：最大化时文件清理提示左移到按钮下方居中，最小化不动。

        用户需求：最大化时「⚠️ 使用前请确认规则是否已启用！！！不启用不生效！！！」
        （label_271）向左移动到「点击检查待刮削目录并清理文件」按钮
        （pushButton_check_and_clean_files）下方；最小化时布局、页面、控件保持不变，
        只能左右移动、不能上下移动。

        根因：label_271 宽 381 ≥ 组框内宽一半，被 CustomScrollArea 通用宽幅同步判为
        _STRETCH，最大化时宽按「设计宽 + extra」铺开；文本 AlignCenter 居中，
        整体右偏到按钮右侧，而按钮本身是 _KEEP 原位不动。

        做法（只改「页面被拉宽」的态，还原态一个像素都不碰，双向幂等）：
          - 拉伸量 <= 0 直接 return：几何完全交给通用同步，本方法不复位、不摘
            registry（理由同 _sync_actor_page_align：复位会覆盖通用同步的缩回量，
            还原态凭空移位）。
          - 拉伸量 > 0：先显式重跑一次宽幅同步拿到终态按钮位置，再把提示按设计宽
            摆到按钮下方水平居中（x = 按钮.x + (按钮宽 - 设计宽)//2，y/h 不动）；
            越界（窄屏）则保持通用逻辑给出的位置。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_61", None)
        tip = getattr(ui, "label_271", None)
        btn = getattr(ui, "pushButton_check_and_clean_files", None)
        if box is None or tip is None or btn is None or not box.isVisibleTo(self):
            return
        if self._scroll_stretch_extra(scroll) <= 0:
            return
        if scroll is not None and scroll.isVisibleTo(self):
            scroll.sync_wide_children_width()  # 取终态按钮位置，勿量过期几何
        g = tip.geometry()
        nx = btn.x() + (btn.width() - self._GUAXIAOMULU_TIP_DESIGN_W) // 2
        if nx < 0 or nx + self._GUAXIAOMULU_TIP_DESIGN_W > tip.parentWidget().width():
            return
        if g.x() != nx or g.width() != self._GUAXIAOMULU_TIP_DESIGN_W:
            tip.setGeometry(nx, g.y(), self._GUAXIAOMULU_TIP_DESIGN_W, g.height())

    # ── 刮削目录页两处横向对齐（需求①软链接行让位 / ②③自动清理换列）──
    # 「文件扫描设置」软链接行：行布局 / 前导项 / 目标。
    # 目标是 horizontalLayout_19 里 gridLayout_19 第 (3,1) 格的子布局，
    # 两项都是 Minimum 策略、总需求恰好等于 col1 宽（窄 504 / 宽 1394）。
    _GUAXIAOMULU_SCAN_ROW = (
        "horizontalLayout_115",
        "checkBox_check_symlink",
        "checkBox_check_symlink_definition",
    )
    # 两态锚点（自身保持不动）：「记录刮削成功的文件列表」，horizontalLayout_133 第二项。
    _GUAXIAOMULU_SCAN_ANCHOR = "checkBox_record_success_file"
    # 「文件清理设置」组里六个「启用」（gridLayout_52 各行末列 Fixed 110）左缘一致，
    # 任取其一即代表该列竖线；组框内绝对定位的「刮削时自动清理」要对齐它。
    _GUAXIAOMULU_ENABLE_ANCHOR = "checkBox_clean_file_ext"
    # 「刮削时自动清理」是 groupBox_61 内的绝对定位项、不受任何布局管理，
    # 通用宽幅同步按 _DOCK_RIGHT 只 move(设计x + extra)、宽高不动
    # （设计几何 520,430,141,41），故宽态左移 / 窄态右移都由本方法在同一事件里
    # move 回去（宽度 141 保持不变——需求只说左右移动）。
    _GUAXIAOMULU_AUTO_CLEAN = "checkBox_auto_clean"
    # 前导项收窄让位的下限：低于此值会夹住「检查并清理失效的软链接」自己的文字
    # （实测其 sizeHint 宽 101），宁可不右移。窗口窄于约 960 时会触发该守卫。
    _GUAXIAOMULU_MIN_LEAD_W = 150
    # ── 命名页画质命名规则行（最大化时「使用路径中包含的画质信息」右移到「视频文件名」列）──
    # 行布局 horizontalLayout_112 在 layoutWidget_26 内，三项 Minimum/Minimum/Fixed、
    # 总需求恰好等于容器宽（窄 471：197 + 196 + 66 + 2×6），与刮削目录 horizontalLayout_115
    # 同构：既不能 setGeometry（会被下次 layout 激活覆盖），也不能只插间隔（总需求一旦
    # 小于容器宽，Qt 把富余摊给其余 Minimum 项、目标弹回原位）。
    # 做法是「容器加宽 + 固定间隔」：容器加宽 need、目标前插 need - spacing 宽的间隔，
    # 行内总需求恒等于容器宽（多出的一项引入一个新间距，spacer = need - spacing），
    # 三项自身宽度纹丝不动，「不获取分辨率」随行同步右移。锚点（自身不动）是
    # checkBox_filename_4k「视频文件名」（绝对定位，窄宽两态 abs 恒 450）。
    _NAMING_DEFN_ROW = (
        "horizontalLayout_112",
        "radioButton_videosize_video",
        "radioButton_videosize_path",
    )
    # 行内第三个单选（Fixed 策略）：它的宽度不参与 need 计算，但必须一并钉死——
    # 不同环境字体不同，它的 hint 也不同（实测 66 vs 99），行内总需求必须按三项实测
    # 宽逐项加总，靠"估算"一定会对不上、挤压会吃掉间隔或目标自身的宽度。
    _NAMING_DEFN_TAIL = "radioButton_videosize_none"
    _NAMING_DEFN_ANCHOR = "checkBox_filename_4k"
    _NAMING_DEFN_HOLDER = "layoutWidget_26"
    _NAMING_DEFN_FRAME = "frame_6"
    # ── 命名页窄态（最小化）三复选框左移到 path 列 ──
    # 目标：checkBox_filename_mosaic（马赛克组视频文件名）/ checkBox_cd_part_space
    # （分集分隔符空格）/ checkBox_filename_4k（画质组视频文件名），设计局部 x 均为
    # 420（abs 450）；锚点 radioButton_videosize_path（使用路径中包含的画质信息，
    # 自身不动，窄宽两态 abs 恒 403）。三目标均为组框内绝对定位项，直接 move(x)，
    # 只改 x 不碰 y/宽高；经公共祖先 content 换算，严格上下对齐。最大化时本分支
    # 不动手（先清干净即 return），宽态布局控件提示纹丝不动。
    _NAMING_NARROW_ANCHOR = "radioButton_videosize_path"
    _NAMING_NARROW_TARGETS = (
        "checkBox_filename_mosaic",
        "checkBox_cd_part_space",
        "checkBox_filename_4k",
    )
    # ── 命名页小数点复选框（窄宽两态都向「不获取分辨率」对齐）──
    # 目标 checkBox_cd_part_point（分集组绝对定位项，设计局部 x=560）；
    # 锚点 radioButton_videosize_none（画质行末项，自身不动——宽态它随行同步右移
    # 是 _sync_naming_definition_align 做的，本方法只读它的落定位置，故与
    # _NAMING_DEFN_TAIL 是同一控件）。
    # 两态实测（content-abs；1000×700 窄态 / 1920×1170 宽态，离屏）：
    #   窄态 point 590 vs none 605（差 -15）；宽态 point 590 vs none 653（差 -63，
    #   none 随 path 右移了 47）。用户需求：两态都把小数点移到与不获取分辨率
    #   严格上下对齐，不获取分辨率保持不动（取代此前的「小数点与空格保持 140
    #   设计间距、等距右随」——窄态下该约定本来也从未成立：空格被左移 47 而小数点
    #   纹丝不动，point-space 实测 187 ≠ 140，正是旧回归测试 [1000] 挂掉的原因）。
    # 越界判据用 sizeHint 宽（实测 59）而非控件全宽 110：窄态父组框被宽幅同步收窄
    # （1000 宽窗口下 groupBox_38 仅 649，目标局部 x=575，575+110=685 会误判越界），
    # 而实际内容（勾选框 + “.小数点”文字）仅 59 宽，575+59=634 完全可见。
    _NAMING_POINT_TARGET = "checkBox_cd_part_point"
    _NAMING_POINT_ANCHOR = "radioButton_videosize_none"
    # ── 水印页水印设置组（最大化时四行左标签冒号左移到「首个水印位置：」冒号）──
    # gridLayout_24 的 col0 在宽态被 QGridLayout 摊了 +272 富余（label_128 从 x0 被推到
    # x272，右缘 180→452），而锚点所在 gridLayout_30 的 col0 恒 130（右缘恒 180）。
    # 做法是把 col0 钉死 130 + stretch 全给 col1（演员页 gridLayout_14 的 col0 同款根因），
    # 四行标签自动归位，右侧复选框/滑杆/提示词随 col1 同步左移。锚点（自身不动）是
    # label_126「首个水印位置：」。
    _WATERMARK_GRID = "gridLayout_24"
    _WATERMARK_ANCHOR = "label_126"
    _WATERMARK_COL = 0
    _WATERMARK_COL_W = 130
    # col1 四个内容行的布局名（与 _WATERMARK_GRID 同文件 .ui 内连续定义）：各在尾部补
    # 一个水平 Expanding 间隔。col1 行内多为 Maximum 策略（capped 在 sizeHint）或
    # Fixed 宽（滑杆 400~500、LCD 70），无处吸收富余时多出的宽度会溢回 col0，
    # 光钉 col0/stretch 拉不动；尾部间隔让 col1 可以无界吸收，富余才全进 col1、
    # col0 恒 130。行内原有项宽度纹丝不动（间隔吸收全部富余）。
    _WATERMARK_CONTENT_ROWS = (
        "horizontalLayout_7",
        "horizontalLayout_15",
        "horizontalLayout_14",
        "horizontalLayout_5",
    )
    # ── 水印页宽态右移对齐（新增需求）──
    # thumb、固定一个位置 → 与右上严格上下对齐；fanart、固定不同位置 → 与右下
    # 严格上下对齐；右上、右下（不固定位置组的 radioButton_top_right /
    # radioButton_bottom_right）自身保持不动。最小化时不动。
    # 再新增：破解 → 右上，无码 → 右下，4K/8K → 左下（锚点为不固定位置组的
    # radioButton_top_right / radioButton_bottom_right / radioButton_bottom_left，
    # 均保持不动）；有码保持不动。注意同行顺序是 有码-破解-流出-无码-4K/8K，
    # 破解右移必然连带其后的流出同步右移（用户已确认：三项对齐、流出跟随）。
    # 又新增：有码 → 左上右上中间，流出 → 右上右下中间（左上/右上/右下保持不动；
    # 流出按字面要去左上右下中间，但会被钉在右上的破解挡住，用户改定为右上右下中间）。
    # 锚点可写单个控件名（取其左缘），或写两个控件名的元组（取两者左缘的中点）。
    _WATERMARK_SHIFT_ANCHOR_TOP = "radioButton_top_right"
    _WATERMARK_SHIFT_ANCHOR_BOTTOM = "radioButton_bottom_right"
    # 每行按从左到右顺序收敛：先推前一个目标（会连带后一个），再推后一个
    _WATERMARK_SHIFT_ROWS = (
        ("horizontalLayout_7", "checkBox_thumb_mark", "radioButton_top_right"),
        ("horizontalLayout_7", "checkBox_fanart_mark", "radioButton_bottom_right"),
        ("horizontalLayout_5", "radioButton_fixed_corner", "radioButton_top_right"),
        ("horizontalLayout_5", "radioButton_fixed_position", "radioButton_bottom_right"),
        ("horizontalLayout_14", "checkBox_censored", ("radioButton_top_left", "radioButton_top_right")),
        ("horizontalLayout_14", "checkBox_umr", "radioButton_top_right"),
        ("horizontalLayout_14", "checkBox_leak", ("radioButton_top_right", "radioButton_bottom_right")),
        ("horizontalLayout_14", "checkBox_uncensored", "radioButton_bottom_right"),
        ("horizontalLayout_14", "checkBox_hd", "radioButton_bottom_left"),
    )

    def _sync_guaxiaomulu_checkbox_align(self, scroll=None) -> None:
        """刮削目录页：软链接行让位 +「刮削时自动清理」按态换列（三条需求）。

        用户需求（三条锚点自身均保持不动）：
          ① 最大化/最小化时把「获取软链接指向的原文件的分辨率」左移到与「记录刮削成功
             的文件列表」严格上下对齐——两态都做，实测两态都是 -58px。
          ② 最大化时把「刮削时自动清理」左移到与「记录刮削成功的文件列表」严格上下对齐。
          ③ 最小化时把「刮削时自动清理」右移到与「启用」严格上下对齐。

        实测几何（abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          窄态 record 383 / definition 441 / check_symlink 186 / auto_clean 528 / 启用 579
          宽态 record 828 / definition 886 / check_symlink 186 / auto_clean 1418 / 启用 1469
        需求①两态右移量同为 58px：锚点列随窗口右移，而软链接行的前导项恒钉在
        col1 起点 186，两者之差与态无关。锚点 x 一律运行时 mapTo 实测、不写死。

        两条手法（根因不同，勿混用）：
          ① horizontalLayout_115 是 gridLayout_19 的子布局，两项都是 Minimum 策略
             且总需求恰好等于 col1 宽，故既不能用 setGeometry（会被下次 layout 激活
             覆盖）也不能只插间隔（行内总需求一旦小于容器宽，Qt 会把富余摊给其余
             Minimum 项、目标又弹回原位）。做法是「前导项收窄让位」：把「检查并清理
             失效的软链接」钉到 need_w = 锚点x - 前导项x - 行间距 - 中间项宽之和，
             目标作为行内唯一的可拉伸项正好吃光剩余宽度，左缘即落在锚点上。
             钉宽每遍先**真解锁**（setMinimumWidth(0) + setMaximumWidth(QWIDGETSIZE_MAX)）
             再量——这正是 _actor_info_width_locks 用 setFixedWidth(saved) 永不真解锁
             的坑：拿上一遍的钉宽去算，误差会逐遍累积。
             need_w < 150 时保持解锁、不右移（宁可不满足也不夹住前导项自己的文字）。
          ② 「刮削时自动清理」是 groupBox_61 内的绝对定位项，直接 move 即可；但通用
             宽幅同步每遍会按 _DOCK_RIGHT 把它钉回「设计x + extra」（窄 498 / 宽
             1388），所以本方法必须排在 sync_wide_children_width() 之后——滚动区的
             _post_wide_sync_hook 与 _sync_page_layouts 尾部两处调用都满足这一点，
             与 _sync_guaxiaomulu_clean_tip_align 同款排布。只改 x，y 与宽不动。

        判态用几何拉伸量 _scroll_stretch_extra()（> 0 为宽态）而非 isMaximized()：
        窗口管理器最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，
        用户会看到「先在右边、再跳到左边」（同 _sync_actor_page_align 的理由）。
        幂等：每遍先解锁再按当前几何重算，双向幂等、窄↔宽往返自愈。休眠页零成本。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box32 = getattr(ui, "groupBox_32", None)
        box61 = getattr(ui, "groupBox_61", None)
        anchor = getattr(ui, self._GUAXIAOMULU_SCAN_ANCHOR, None)
        if box32 is None or box61 is None or anchor is None or not box32.isVisibleTo(self):
            return
        content = box32.parentWidget()
        if content is None or box61.parentWidget() is not content:
            return
        if scroll is None:
            scroll = getattr(self, "_guaxiaomulu_scroll", None)

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        # ① 软链接行：前导项收窄让位，目标左缘落到锚点列（两态都做）。
        row_name, lead_name, target_name = self._GUAXIAOMULU_SCAN_ROW
        row = getattr(ui, row_name, None)
        lead = getattr(ui, lead_name, None)
        target = getattr(ui, target_name, None)
        if row is not None and lead is not None and target is not None:
            if lead.parentWidget() is target.parentWidget():
                lead.setMinimumWidth(0)
                lead.setMaximumWidth(QWIDGETSIZE_MAX)
                lead.updateGeometry()
                row.invalidate()
                row.activate()  # 先落定，才能量到本行的当前真实 x 与宽
                lidx = row.indexOf(lead)
                tidx = row.indexOf(target)
                if lidx >= 0 and tidx > lidx:
                    anchor_x = left_x(anchor)
                    between = 0
                    for i in range(lidx + 1, tidx):
                        mid = row.itemAt(i).widget()
                        if mid is not None:
                            between += mid.width()
                    need_w = anchor_x - left_x(lead) - row.spacing() * (tidx - lidx) - between
                    if need_w >= self._GUAXIAOMULU_MIN_LEAD_W:
                        lead.setFixedWidth(need_w)
                        row.invalidate()
                        row.activate()
                        # 回读修正：上面已按构造式推出「目标x == 锚点x」，这里不依赖
                        # Qt 分配细节再校一遍，残差就再让多少（仍以不夹住文字为界）。
                        d = anchor_x - left_x(target)
                        if d:
                            fixed = max(need_w - d, self._GUAXIAOMULU_MIN_LEAD_W)
                            lead.setFixedWidth(fixed)
                            row.invalidate()
                            row.activate()

        # ②③ 「刮削时自动清理」：窄态与“微宽死区”对到「启用」列，真宽态对到
        # 「记录刮削成功的文件列表」列。死区（刚过拉伸门限、外宽 ~1054~1650）
        # 里若按旧规则去记录列，用户小窗下看到它停在启用列左侧（与截图一致）；
        # 改为：拉伸量>600（约外宽 1650+，即全屏最大化类）或窗口已最大化时才去
        # 记录列，其余一律去启用列。最大化行为不变（1920 下 extra=866>600）。
        clean = getattr(ui, self._GUAXIAOMULU_AUTO_CLEAN, None)
        enable = getattr(ui, self._GUAXIAOMULU_ENABLE_ANCHOR, None)
        if clean is not None and enable is not None and clean.parentWidget() is box61:
            extra = self._scroll_stretch_extra(scroll)
            src = anchor if (extra > 600 or self.isMaximized()) else enable
            # 跨分支 mapTo（record 在 groupBox_32、目标在 groupBox_61）是未定义行为，
            # 必须经公共祖先 content 中转再换算回 groupBox_61 的局部坐标。
            box_x = box61.mapTo(content, QPoint(0, 0)).x()
            nx = src.mapTo(content, QPoint(0, 0)).x() - box_x
            # 不越过滚动内容右缘（否则内容最小宽被抬高、冒出一条水平滚动条）
            limit = content.width() - box_x
            if nx != clean.x() and 0 <= nx and nx + clean.width() <= limit:
                clean.move(nx, clean.y())

    def _sync_reuse_meta_gap_align(self) -> None:
        """刮削模式页：四行的右侧复选框严格同 x 上下对齐。

        锚点是 STRM 行（其左右两个复选框之间只有布局间距，没有间隔占位），
        复用行、整理模式间隔行、视频模式行的右侧复选框则各自带一个 gap spacer
        （第 1 项），差值只来自“首框宽度差 + 行内间距差”，由 gap spacer 补齐。

        四行同处 gridLayout_2 第 1 列（左缘天然一致）。sizeHint 在 show 前后会变
        （初始化公式一次算不准，窄态实测差 6px），故按实测差值闭环收敛：量各框经
        content 中转的 x 差，残差就加多少，相等即 no-op。gap 钉 Fixed、行尾 spacer
        保持 Expanding，宽态富余只进尾部；gap 变宽不改变行总宽（尾部吸收），不触发
        新的 resize，不会自激。休眠页跳过（切页同拍收敛，无漂移可见）。
        """
        ui = self.Ui
        content = getattr(ui, "scrollAreaWidgetContents_guaxiaomoshi", None)
        if content is None or not content.isVisibleTo(self):
            return
        strm_box = getattr(ui, "checkBox_separate_overwrite_strm", None)
        if strm_box is None:
            return
        # 待收敛的行：右侧复选框 + 行内用于调节间距的 gap spacer（第 1 项）
        rows: list[tuple[QWidget, QLayout, QSpacerItem]] = []
        for box_name, row_name in (
            ("checkBox_separate_overwrite_meta", "horizontalLayout_reuse_meta"),
            ("checkBox_sortmode_movefile", "horizontalLayout_125"),
        ):
            box = getattr(ui, box_name, None)
            row = getattr(ui, row_name, None)
            if box is None or row is None:
                continue
            gap_item = row.itemAt(1)
            gap = gap_item.spacerItem() if gap_item is not None else None
            if gap is None:
                continue
            # 行尾 spacer 保持 Expanding：gap 变宽不改变行总宽（富余由尾部吸收），
            # 因此不会触发新的 resize，不会自激
            tail_item = row.itemAt(3)
            tail = tail_item.spacerItem() if tail_item is not None else None
            if tail is not None and tail.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Expanding:
                tail.changeSize(
                    max(tail.sizeHint().width(), 0), 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
                )
            rows.append((box, row, gap))
        if not rows:
            return
        for _box, _row, gap in rows:
            if gap.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Fixed:
                gap.changeSize(max(gap.sizeHint().width(), 0), 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        for _ in range(4):
            xs = strm_box.mapTo(content, QPoint(0, 0)).x()
            if all(box.mapTo(content, QPoint(0, 0)).x() == xs for box, _row, _gap in rows):
                break
            for box, row, gap in rows:
                xm = box.mapTo(content, QPoint(0, 0)).x()
                if xm == xs:
                    continue
                gap.changeSize(
                    max(gap.sizeHint().width() + (xs - xm), 0), 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
                )
                row.invalidate()
                row.activate()

    def _sync_javdb_tip_pos(self) -> None:
        """刮削模式页：Javdb 延时提示（label_26）上移一行并钉死。

        label_26 已移出 gridLayout_15、独立为 groupBox_53 子件（.ui 设计几何
        (146,160,513,28)：相对旧 grid 内位置上移一行 = fontMetrics 高 14）；
        grid 内 0-2 行不受影响（容器高已同步收缩 181→129）。
        运行时钉死两点：x 经 content 映射与 label_separate_mode 文本左缘精确
        相等（用户要求严格对齐）；y = 容器.y + row2底 + spacing + share − h，
        其中 share = (H − 各行高 − 2*spacing) / 3 全运行时实测（富余摊槽位的
        真实值），h = 提示自身 fontMetrics 高。|dx|、|dy| ≤ 1 即 no-op，
        休眠页/缺件早退，切页同拍收敛。
        """
        ui = self.Ui
        content = getattr(ui, "scrollAreaWidgetContents_guaxiaomoshi", None)
        tip = getattr(ui, "label_26", None)
        sep = getattr(ui, "label_separate_mode", None)
        grid_widget = getattr(ui, "gridLayoutWidget_15", None)
        grid = getattr(ui, "gridLayout_15", None)
        if (
            content is None
            or tip is None
            or sep is None
            or grid_widget is None
            or grid is None
            or not content.isVisibleTo(self)
        ):
            return
        # x：与分离模式描述文本左缘精确相等（经 content 中转，同 _sync_reuse_meta_gap_align）。
        anchor_x = sep.mapTo(content, QPoint(0, 0)).x()
        if abs(anchor_x - tip.mapTo(content, QPoint(0, 0)).x()) > 1:
            tip.move(tip.x() + (anchor_x - tip.mapTo(content, QPoint(0, 0)).x()), tip.y())
        # y：row2 底 + spacing + 所属槽位富余 − 一行字高（全运行时实测）。
        spacing = grid.verticalSpacing()
        if spacing < 0:
            spacing = grid.spacing()
        rows_h = 0
        row2_bottom = None
        for _r in range(3):
            _item = grid.itemAtPosition(_r, 1)
            if _item is None:
                return
            _g = _item.geometry()  # 第 1 列是 HBox 不是 widget，必须用 cell 几何（widget() 取不到）
            rows_h += _g.height()
            if _r == 2:
                row2_bottom = _g.y() + _g.height()
        if row2_bottom is None:
            return
        share = (grid_widget.height() - rows_h - 2 * spacing) / 3
        expect_y = grid_widget.y() + row2_bottom + spacing + share - tip.fontMetrics().height()
        if abs(expect_y - tip.y()) > 1:
            tip.move(tip.x(), round(expect_y))

    def _clear_naming_defn_align(self) -> None:
        """清掉命名页画质行加宽/间隔（每遍同步先清后建，故幂等、往返自愈）。

        holder（layoutWidget_26）是 frame_6 内绝对定位的容器：只恢复 min/max
        不会收回宽度（widget 保持当前宽），必须按记录值把宽度写回去，否则加宽量
        逐遍累积（实测 holder 471→554、窄态也要不回来）。
         seeing narrow restores here too: wide anchor is filename_4k design pos,
        narrow moves it left — must restore before wide measures, and baseline
        (method-disabled) must be true design.
        """
        self._clear_naming_narrow_align()
        for row, spacer in self._naming_defn_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._naming_defn_spacers = []
        for kind, obj, saved in reversed(self._naming_defn_restores):
            if obj is None:
                continue
            if kind == "width":
                # 先真解锁：holder 加宽用的是 setFixedWidth（min == max == 加宽值），
                # 不先恢复 min/max 的话 setGeometry 会被钳在加宽值、窄态也要不回来
                # （实测 holder 471→559 越垒越高）。
                obj.setMinimumWidth(0)
                obj.setMaximumWidth(QWIDGETSIZE_MAX)
                obj.setGeometry(obj.x(), obj.y(), saved, obj.height())
                obj.updateGeometry()
            elif kind == "unlock":
                # 行内 Minimum 项的钉宽：行布局每遍从零重排，真解锁即可。
                obj.setMinimumWidth(0)
                obj.setMaximumWidth(QWIDGETSIZE_MAX)
                obj.updateGeometry()
        self._naming_defn_restores = []
        ui = getattr(self, "Ui", None)
        row = getattr(ui, self._NAMING_DEFN_ROW[0], None) if ui is not None else None
        if row is not None and row.parentWidget() is not None:
            row.invalidate()
            row.activate()

    def _clear_naming_narrow_align(self) -> None:
        """清掉命名页窄态三复选框左移（每遍先清后建，幂等往返自愈）。"""
        for obj, saved_x in reversed(self._naming_narrow_restores):
            if obj is None:
                continue
            try:
                if obj.x() != saved_x:
                    obj.move(saved_x, obj.y())
            except RuntimeError:
                continue
        self._naming_narrow_restores = []

    def _sync_naming_definition_align(self, scroll=None) -> None:
        """命名页画质命名规则：最大化时 path 右移到视频文件名列 + 小数点对齐 none 列。

        用户需求：最大化时把「使用路径中包含的画质信息」向右移动到与下方「视频文件名」
        严格上下对齐的位置，「不获取分辨率」同步向右移动，「视频文件名」位置保持不变；
        同时把「.小数点」向右移动到与「不获取分辨率」严格上下对齐（读落定后的 none
        位置，故排在间隔收敛之后）；最小化时画质行保持不变（窄态只做三复选框左移 +
        小数点对齐，见 _sync_naming_narrow_align）。

        实测几何（abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          video 200 / path 403 / none 605 / filename_4k 450（两态完全一致，通用宽幅同步
          不碰 layoutWidget_26，frame_6 只被拉宽到 1510、内部 471 宽的行原地不动）。
        故 need 恒为 47（= 450 - 403），仍运行时 mapTo 实测、不写死。

        手法「容器加宽 + 固定间隔」（见类常量注释）：holder 加宽 need，目标前插
        need - spacing 宽的 Fixed 间隔。行内总需求恒等于容器宽，间隔不会被挤瘦，
        三项自身宽度纹丝不动。插完实测回读、按差值 changeSize 三轮收敛。
        必须排在 _sync_definition_group_spacing 之后：后者每遍按 frame_layout 的
        sizeHint 高度重钉 frame 高（只取高度，本间隔高为 0 不影响），且它用
        setGeometry(..., frame_lw.width(), ...) 保留容器宽度——排前面会把本方法刚加的
        宽度当成终态保留，逻辑仍自洽；但它 activate() 的是旧几何，排后面量到的 need
        才是终态。窄态第一步清干净即 return，最小化逐像素不变。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_65", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_naming_defn_align()
        self._clear_naming_narrow_align()
        if scroll is None:
            scroll = getattr(ui, "scrollArea_7", None)
        if self._scroll_stretch_extra(scroll) <= 0:
            self._sync_naming_narrow_align(scroll)
            return  # 窄态：只做三复选框左移，宽态分支不动
        content = box.parentWidget()
        anchor = getattr(ui, self._NAMING_DEFN_ANCHOR, None)
        holder = getattr(ui, self._NAMING_DEFN_HOLDER, None)
        frame = getattr(ui, self._NAMING_DEFN_FRAME, None)
        row_name, _lead_name, target_name = self._NAMING_DEFN_ROW
        row = getattr(ui, row_name, None)
        target = getattr(ui, target_name, None)
        lead = getattr(ui, self._NAMING_DEFN_ROW[1], None)
        tailfix = getattr(ui, self._NAMING_DEFN_TAIL, None)
        if content is None or anchor is None or holder is None or frame is None:
            return
        if row is None or target is None or lead is None or tailfix is None:
            return
        if target.parentWidget() is not holder or row.parentWidget() is not holder:
            return

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        row.invalidate()
        row.activate()
        anchor_x = left_x(anchor)
        need = anchor_x - left_x(target)
        if need <= 0:
            return
        spacing = row.spacing()
        spacer_w = need - spacing
        if spacer_w <= 0:
            return
        # 三个单选全钉死在当前宽（见类常量注释），再逐项加总定容器宽：
        # 行内总需求恒等于容器宽，间隔既不会被挤瘦、富余也不会摊给行首。
        # 恢复时真解锁（行布局每遍从零重排，不存在"拆掉上游锁"问题）。
        for w in (lead, target, tailfix):
            self._naming_defn_restores.append(("unlock", w, None))
            w.setFixedWidth(w.width())
        new_w = lead.width() + spacer_w + target.width() + tailfix.width() + spacing * row.count()
        # 不越过所在 frame 右缘（否则内容最小宽被抬高、冒出水平滚动条）
        if holder.x() + new_w > frame.width():
            return
        self._naming_defn_restores.append(("width", holder, holder.width()))
        holder.setFixedWidth(new_w)
        holder.updateGeometry()
        idx = row.indexOf(target)
        if idx < 0:
            return
        spacer = QSpacerItem(spacer_w, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        row.insertItem(idx, spacer)
        self._naming_defn_spacers.append((row, spacer))
        row.invalidate()
        row.activate()
        # 回读修正：spacer 与 holder 联动增减（行内总需求恒等于容器宽，间隔既不会被
        # 挤瘦、富余也不会摊给行首的 Minimum 项），故一步即收敛；holder 加宽受 frame
        # 右缘钳制，超界则放弃修正（保持近似值，下一遍再修）。
        for _ in range(3):
            d = anchor_x - left_x(target)
            if not d:
                break
            if holder.x() + holder.width() + d > frame.width():
                break
            spacer.changeSize(max(0, spacer.sizeHint().width() + d), 0)
            holder.setFixedWidth(holder.width() + d)
            row.invalidate()
            row.activate()
        # 小数点：宽态向「不获取分辨率」对齐。必须排在间隔收敛之后——none 的位置
        # 由上面的收敛循环刚定下，此时量到的是终态；helper 内自己再换算一次，
        # 不依赖本方法的 anchor_x。
        self._move_naming_point_to_none(content)

    def _move_naming_point_to_none(self, content) -> None:
        """命名页：小数点复选框左缘对齐「不获取分辨率」左缘（窄宽两态都做）。

        用户需求：最小化时把「.小数点」向左移动、最大化时向右移动到与「不获取
        分辨率」严格上下对齐的位置，「不获取分辨率」位置保持不变（方向由运行时
        几何决定：量到在哪边就往哪边移，不写死左右）。
        目标是分集组内绝对定位项，直接 move(x)，只改 x 不碰 y/宽高；跨组 mapTo
        经公共祖先 content 中转；越界则放弃。复位记录复用 _naming_narrow_restores
        （调用方每遍先清后建，故幂等、往返自愈）。小数点在
        CustomScrollArea._MANUAL_WIDGET_NAMES 里，通用宽幅同步不会登记/搬动它。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or content is None:
            return
        target = getattr(ui, self._NAMING_POINT_TARGET, None)
        anchor = getattr(ui, self._NAMING_POINT_ANCHOR, None)
        if target is None or anchor is None:
            return
        parent = target.parentWidget()
        if parent is None or parent.parentWidget() is not content:
            # 目标须是内容直属组框的子项，否则换算无意义
            return
        try:
            anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
            target_x = target.mapTo(content, target.rect().topLeft()).x()
        except Exception:
            return
        d = anchor_x - target_x
        if not d:
            return
        nx = target.x() + d
        if nx < 0:
            return
        need = max(target.sizeHint().width(), target.minimumSizeHint().width())
        if nx + need > parent.width():
            return
        if target.x() != nx:
            self._naming_narrow_restores.append((target, target.x()))
            target.move(nx, target.y())

    def _sync_naming_narrow_align(self, scroll=None) -> None:
        """命名页窄态：三复选框左移到 path 列 + 小数点对齐 none 列，锚点均不动。

        用户需求：最小化时把视频文件名（上下两个：checkBox_filename_mosaic /
        checkBox_filename_4k）与空格（checkBox_cd_part_space）向左移动到与
        「使用路径中包含的画质信息」（radioButton_videosize_path）上下严格对齐，
        把「.小数点」（checkBox_cd_part_point）移动到与「不获取分辨率」
        （radioButton_videosize_none）上下严格对齐，两个锚点位置均保持不变；
        最大化时页面布局控件提示等均保持不变（本分支窄态才动手，宽态调用方已
        提前 return——宽态的小数点由 _sync_naming_definition_align 负责）。

        三目标均为组框内绝对定位项（设计局部 x 均为 420），直接 move(x)，只改 x
        不碰 y/宽高；跨组 mapTo 必须经公共祖先 content 中转。越界则放弃该项。
        休眠页跳过（切页 showEvent 会补齐）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_65", None)
        if box is None or not box.isVisibleTo(self):
            return
        content = box.parentWidget()
        anchor = getattr(ui, self._NAMING_NARROW_ANCHOR, None)
        if content is None or anchor is None:
            return
        try:
            anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
        except Exception:
            return
        for name in self._NAMING_NARROW_TARGETS:
            target = getattr(ui, name, None)
            if target is None:
                continue
            parent = target.parentWidget()
            if parent is None or parent.parentWidget() is not content:
                # 目标须是内容直属组框的子项，否则换算无意义
                if parent is None:
                    continue
            try:
                target_x = target.mapTo(content, target.rect().topLeft()).x()
            except Exception:
                continue
            d = anchor_x - target_x
            if not d:
                continue
            nx = target.x() + d
            if nx < 0 or nx + target.width() > parent.width():
                continue
            if target.x() != nx:
                self._naming_narrow_restores.append((target, target.x()))
                target.move(nx, target.y())
        # 小数点：窄态同样向「不获取分辨率」对齐（锚点不动）
        self._move_naming_point_to_none(content)

    def _clear_watermark_colon_align(self) -> None:
        """清掉水印页网格列钉死 + 四行尾部间隔 + 宽态右移间隔（每遍先清后建，幂等）。"""
        ui = getattr(self, "Ui", None)
        for row_name, spacer in self._watermark_shift_spacers:
            row = getattr(ui, row_name, None) if ui is not None else None
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._watermark_shift_spacers = []
        for row_name, spacer in self._watermark_tail_spacers:
            row = getattr(ui, row_name, None) if ui is not None else None
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._watermark_tail_spacers = []
        for kind, obj, saved in reversed(self._watermark_col_restores):
            if obj is None:
                continue
            if kind == "colmin":
                obj.setColumnMinimumWidth(saved[0], saved[1])
            elif kind == "colstretch":
                obj.setColumnStretch(saved, 0)
        self._watermark_col_restores = []
        ui = getattr(self, "Ui", None)
        grid = getattr(ui, self._WATERMARK_GRID, None) if ui is not None else None
        if grid is not None:
            grid.invalidate()
            grid.activate()

    def _sync_watermark_colon_align(self, scroll=None) -> None:
        """水印页水印设置：最大化时四行左标签冒号左移到「首个水印位置：」冒号 + 右移对齐。

        用户需求：最大化时把「添加水印的图片」「水印大小」「水印类型」「水印位置」向左
        移动到与「首个水印位置：」严格上下对齐的位置（注意是对齐冒号），「首个水印位置：」
        的位置保持不变，右侧的复选框、提示词、组件等同步向左移动；最小化时界面、控件、
        组件等等均保持不变。

        新增需求（宽态，锚点均保持不动）：thumb、固定一个位置向右移动到与右上严格
        上下对齐；fanart、固定不同位置向右移动到与右下严格上下对齐。右上/右下指
        不固定位置组的 radioButton_top_right / radioButton_bottom_right。
        再新增（宽态）：破解 → 右上，无码 → 右下，4K/8K → 左下（左下指同组的
        radioButton_bottom_left）。有码保持不动；流出被破解连带同步右移（同行
        顺序有码-破解-流出-…，已与用户确认）。
        又新增（宽态）：有码 → 左上与右上中间，流出 → 右上与右下中间（左上指
        同组的 radioButton_top_left）。此时有码/流出各自拥有独立间隔，破解/
        无码/4K8K 的对齐保持不变。

        实测几何（右缘 abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          窄态四标签右缘全 180 == 锚点 180（天然对齐，col0 恒 130）；
          宽态四标签右缘全 452 vs 锚点 180（col0 被 QGridLayout 摊了 +272 富余）。
        做法见类常量注释：col0 钉死 130 + stretch 全给 col1。窄态第一步清干净即
        return，最小化逐像素不变。休眠页跳过。判态用几何拉伸量而非 isMaximized()。

        右移手法：col1 两行（horizontalLayout_7/5）目标前插 Fixed 间隔。行尾已有
        Expanding 间隔吸收富余，故固定间隔只会把目标向右推、行内其余项宽度不动；
        每行按顺序收敛（先推前一个目标、再推后一个），插完回读三轮收敛。只允许
        右移（need <= 0 则该项保持 0 宽间隔），越界则放弃。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_31", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_watermark_colon_align()
        if scroll is None:
            scroll = getattr(ui, "scrollArea_4", None)
        if self._scroll_stretch_extra(scroll) <= 0:
            return  # 窄态：一个像素不碰
        grid = getattr(ui, self._WATERMARK_GRID, None)
        if grid is None:
            return
        col = self._WATERMARK_COL
        self._watermark_col_restores.append(("colmin", grid, (col, grid.columnMinimumWidth(col))))
        self._watermark_col_restores.append(("colstretch", grid, col))
        self._watermark_col_restores.append(("colstretch", grid, col + 1))
        grid.setColumnMinimumWidth(col, self._WATERMARK_COL_W)
        grid.setColumnStretch(col, 0)
        grid.setColumnStretch(col + 1, 1)
        # col1 四行尾部补 Expanding 间隔（类常量注释）：无处吸收富余时多出的宽度会
        # 溢回 col0，尾部间隔让 col1 无界吸收，行内原有项宽度纹丝不动。
        for row_name in self._WATERMARK_CONTENT_ROWS:
            row = getattr(ui, row_name, None)
            if row is None:
                continue
            tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            row.addItem(tail)
            self._watermark_tail_spacers.append((row_name, tail))
        grid.invalidate()
        grid.activate()
        # ── 宽态右移对齐：thumb/固定一个位置 → 右上，fanart/固定不同位置 → 右下 ──
        content = box.parentWidget()
        if content is None:
            return
        for row_name, target_name, anchor_name in self._WATERMARK_SHIFT_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            if isinstance(anchor_name, tuple):
                anchors = [getattr(ui, n, None) for n in anchor_name]
                anchor = anchors[0]
                if row is None or target is None or any(a is None for a in anchors):
                    continue
            else:
                anchor = getattr(ui, anchor_name, None)
                anchors = None
                if row is None or target is None or anchor is None:
                    continue
            if target.parentWidget() is None:
                continue
            idx = row.indexOf(target)
            if idx < 0:
                continue
            spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._watermark_shift_spacers.append((row_name, spacer))
            row.invalidate()
            row.activate()
            for _ in range(3):
                try:
                    if anchors is not None:
                        xs = [a.mapTo(content, a.rect().topLeft()).x() for a in anchors]
                        anchor_x = (xs[0] + xs[1]) // 2
                    else:
                        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
                    target_x = target.mapTo(content, target.rect().topLeft()).x()
                except Exception:
                    break
                d = anchor_x - target_x
                if not d:
                    break
                new_w = spacer.sizeHint().width() + d
                if new_w < 0:
                    break  # 只允许右移：锚点在左则保持 0 宽间隔
                try:
                    target_parent = target.parentWidget()
                    limit = content.width() - target_parent.mapTo(content, target_parent.rect().topLeft()).x()
                except Exception:
                    break
                if target.width() + new_w > limit and d > 0:
                    break
                spacer.changeSize(new_w, 0)
                row.invalidate()
                row.activate()

    # ============ 网络页：「网络设置」分组按内容收紧 ============
    #
    # 设计几何（MDCx.ui，设计态逐字读出）：
    #   groupBox_28「网络设置」   x30 y20  w701 h627
    #     └ gridLayoutWidget_9    x20 y30  w661 h597（内层 gridLayout_9）
    #   groupBox_10「Cookie设置」 x30 y662 w601
    #   groupBox_14（API Token）  x30 y1278 h230
    #   groupBox_44（本站目录）   x30 y1523 h210
    _NET_BOX = "groupBox_28"
    _NET_BOX_DESIGN_Y = 20
    _NET_BOX_DESIGN_H = 627
    _NET_HOST = "gridLayoutWidget_9"
    _NET_HOST_DESIGN_Y = 30
    _NET_HOST_DESIGN_H = 597
    # 「网络设置」之下三个分组的 (控件名, 设计 y)
    _NET_FOLLOW_BOXES = (("groupBox_10", 662), ("groupBox_14", 1278), ("groupBox_44", 1523))
    # 「使用代理 / 全部走代理」同行所在行（gridLayout_9 的 row 0，跨 col 1~3）
    _NET_PROXY_ROW = "horizontalLayout_17"
    _NET_PROXY_USE = "checkBox_use_proxy"

    def _sync_wangluo_proxy_row_margin(self) -> None:
        """设置-网络：「全部走代理」右留白 ≡「使用代理」左留白，「使用代理」原地不动。

        用户需求：「全部走代理向左移动使得全部走代理最右侧到右边界的间距与使用代理
        最左侧到左边界的间距相等，使用代理位置保持不变，只向左移动全部走代理」。

        两侧留白量必须量到**同一条分界线**才有可比性：gridLayout_9 的内容左右缘。
        该网格 contentsMargins 为 0 且铺满容器 gridLayoutWidget_9，组框边框那点内外缩
        对左右同量，加不加都不影响「相等」这个判据（本机离屏实测 1085×720 窗口：
        网格 661 宽、col 0 = 132、spacing = 6、行内布局 x=138 w=523）。

          · 左留白 = 标签列宽（col 0，最宽的是「HTTPS 证书校验:」）+ 网格 spacing，
            也就是「使用代理」左缘到网格内容左缘那 138px——由**网格算法**算出；
          · 右留白 = horizontalLayout_17 的右内边距——由**写死的数字**给出
            （MDCx.ui 里 138 作设计态初值，让 .ui 自己就能看出版式意图）。

        两者不同源：换字体 / 改系统 DPI / 换语言包都会让左留白变而右留白不变，等式即
        破。故每遍用 mapTo 实测左留白（不写死常数），回写右内边距，二值恒等。

        「使用代理」一个像素都不动：它是本行第 1 项、左内边距 0、中间是 Expanding
        spacer，行内富余宽度全被 spacer 吃掉，故本方法只碰右内边距一个属性。

        幂等：右内边距已等于实测左留白即返回。休眠页也照跑（几何本就是设计值，
        与 _sync_wangluo_net_box_hug 的休眠页早退互不打架——那管的是高度）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        host = getattr(ui, self._NET_HOST, None)
        row = getattr(ui, self._NET_PROXY_ROW, None)
        use = getattr(ui, self._NET_PROXY_USE, None)
        if host is None or row is None or use is None:
            return
        if use.parentWidget() is not host:
            return  # 结构变了：开关不再与本行同父，交给上层排查，别盲改内边距
        grid = host.layout()
        if grid is not None:
            # 容器拉宽后网格未必已重排，量到的会是上一遍的列宽（左留白跟着旧值走）
            grid.invalidate()
            grid.activate()
        lead = use.mapTo(host, QPoint(0, 0)).x()
        if lead <= 0:
            return  # 尚未布局，读数无意义，保持 .ui 的设计初值
        margins = row.contentsMargins()
        if margins.right() == lead:
            return
        row.setContentsMargins(margins.left(), margins.top(), lead, margins.bottom())

    def _sync_wangluo_net_box_hug(self, _scroll=None) -> None:
        """设置-网络：宽态把「网络设置」分组收紧到贴住内容，窄态逐像素回到设计几何。

        用户需求（最大化）：「状态：留空不校验（默认）」下方、`Cookie设置` 分组之前
        有一大片空白，删掉它；最小化时页面布局、组件、控件、提示词等等全部保持不变。

        根因（本机实测，离屏 Qt 同构复现）：本页内容 widget 无布局管理器，四个分组
        绝对定位且高度写死；通用宽幅同步（CustomScrollArea.sync_wide_children_width）
        每遍都按登记的设计几何 setGeometry，**只改宽、高恒为设计值**。而分组里的
        两段说明（label_103 代理说明、label_cf_bypass_trusted_hosts_desc 校验服务说明）
        是 wordWrap 换行标签：窗口拉宽后折行数下降、文字所需高度随之变矮
        （离屏实测 label_103 136→120→100→80px、校验服务说明 54→40→26→12px），而
        gridLayout_9 又设了 alignment=AlignTop（上一轮治「文字下方留空行」时加的），
        于是省下来的高度全部堆在网格底部——组框仍按 627 高画、内容只到 567/533/513，
        多出来的 30/64/84px 就是截图里那片空盒子。空白随窗口越宽越大（离屏实测视口
        972/1272/1672 → 空白 30/64/84px），与用户「最大化才出现」的描述一致。

        做法（只改宽态的高度，窄态一个像素都不动，双向幂等）：
          - 判态用几何拉伸量 _scroll_stretch_extra() > 0 而非 isMaximized()：窗口
            管理器最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False。
          - 宽态：先让 gridLayout_9 失效重排（拉宽后换行数才会真正收窄），再按
            childrenRect 量内容真实底边，容器高 = 底边、组框高 = 容器 y + 容器高
            （保持 .ui 里 627 = 30 + 597 那条恒等式）；组框矮了多少，下面三个分组
            就整体上移多少，四个分组之间 15px 的设计间距原样保留——空白被删掉，
            而不是挪到别处（tests/test_network_settings_group_hug.py 逐条锁）。
          - 窄态：容器/组框/后续分组一律复位到设计几何。不靠通用同步「顺带复位」，
            显式复位才能保证任何调用路径下最小化态都等于设计值。

        休眠页直接返回（几何本就是设计值），由切 tab 的 showEvent 补齐——与
        _sync_zimu_fill_blank / _sync_guaxiaomulu_page_align 同一套钩子约定。

        本函数同时是「全部走代理」行左右留白对齐的入口（钩子只有一个）：
        _sync_wangluo_proxy_row_margin 排在最前先行，两步互不干涉（一个改高度、
        一个改行内右内边距），但都必须晚于网格拉伸——拉伸会改列宽，先量后拉会量到
        过期列宽（同 _sync_guaxiaomulu_clean_tip_align「须排在拉伸之后」的理由）。
        """
        self._sync_wangluo_proxy_row_margin()
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, self._NET_BOX, None)
        host = getattr(ui, self._NET_HOST, None)
        if box is None or host is None:
            return
        scroll = _scroll if _scroll is not None else getattr(self, "_wangluo_scroll", None)
        if scroll is None:
            return
        if not box.isVisibleTo(self):
            return  # 休眠页：几何本就是设计值，切页 showEvent 会再跑一遍
        if self._scroll_stretch_extra(scroll) > 0:
            # 拉宽后换行数才收窄，必须让布局重排一遍再量，否则量到的是拉宽前的底边
            layout = host.layout()
            if layout is None:
                return
            layout.invalidate()
            layout.activate()
            host_h = host.childrenRect().bottom() + 1
            if host_h <= 0:
                return  # 尚未布局，读数无意义，保持设计几何
            box_h = self._NET_HOST_DESIGN_Y + host_h
        else:
            host_h = self._NET_HOST_DESIGN_H
            box_h = self._NET_BOX_DESIGN_H
        changed = False
        if box.height() != box_h:
            box.setGeometry(box.x(), self._NET_BOX_DESIGN_Y, box.width(), box_h)
            changed = True
        if host.height() != host_h:
            host.setGeometry(host.x(), self._NET_HOST_DESIGN_Y, host.width(), host_h)
            changed = True
        # 组框矮了多少，下面三个分组就上移多少，组间距恒为设计值 15px
        delta = box_h - self._NET_BOX_DESIGN_H
        for name, design_y in self._NET_FOLLOW_BOXES:
            sub = getattr(ui, name, None)
            if sub is None:
                continue
            want_y = design_y + delta
            if sub.y() != want_y:
                sub.move(sub.x(), want_y)
                changed = True
        if changed:
            scroll.sync_content_min_height()
