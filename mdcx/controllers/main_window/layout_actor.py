"""演员页 / 工具页的绝对定位布局计算。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import (
    QPoint,
)
from PyQt6.QtWidgets import (
    QSizePolicy,
    QSpacerItem,
)


class LayoutActorMixin:
    # 软件工具页演员库分组内部常态几何（紧凑排布）。
    # _sync 按此摆常态，最大化只加宽（y/h 取字典）。
    _ACTOR_DB_TOOL_DESIGN = {
        "label_actor_db_note": (40, 30, 621, 20),
        "pushButton_actor_db_open": (40, 90, 200, 28),
        "pushButton_actor_db_stop": (260, 90, 200, 28),
        "pushButton_actor_db_clean_male": (40, 118, 200, 30),
        "pushButton_actor_db_fill_Minnano": (260, 118, 200, 30),
        "pushButton_actor_db_verify_tmdbid": (40, 148, 200, 30),
        "pushButton_actor_db_check": (260, 148, 200, 30),
        "pushButton_actor_db_update_nfo_tmdbid": (40, 184, 200, 30),
        "pushButton_actor_db_fill_zh_javdb": (260, 184, 200, 30),
        "lineEdit_actor_db_nfo_dir": (40, 222, 451, 30),
        "pushButton_actor_db_pick_nfo_dir": (571, 217, 110, 40),
        "label_actor_db_update_nfo_desc": (40, 260, 621, 28),
        "pushButton_actor_db_sync_aliases": (571, 292, 110, 40),
        "comboBox_actor_db_alias_source": (40, 296, 451, 32),
        "checkBox_actor_db_alias_all": (40, 336, 142, 28),
        "label_actor_db_sync_offset": (186, 336, 56, 28),
        "spinBox_actor_db_sync_offset": (246, 336, 64, 28),
        "label_actor_db_sync_limit": (314, 336, 56, 28),
        "spinBox_actor_db_sync_limit": (374, 336, 72, 28),
        "label_actor_db_sync_slice_hint": (450, 336, 211, 28),
        "label_actor_db_sync_aliases_desc": (40, 356, 621, 42),
    }
    # groupBox_actor_db_maintenance 的 .ui 设计几何（30, 20, 701, 412）。
    # 通用逻辑每遍把组框高复位到此值，本方法窄态分支绝对设值、双向幂等。
    _ACTOR_DB_TOOL_BOX_DESIGN = (30, 20, 701, 412)
    # 最小化/还原态：单文件刮削组（groupBox_7）整体下移量（顶部说明删除后不再需要增高，
    # 保留为 0 以保持组间距与设计一致）。
    # 设计几何：演员库组底边 20+412=432，单文件组顶边 452（常态间隙 20）；
    # 单文件组底边 452+241=693，裁剪组（groupBox_13）顶边
    # 713，间隙 20。绝对设值（设计顶边 452 + 位移），双向幂等；
    # 最大化分支不动（通用逻辑每遍把组顶边复位到设计值，宽态自然回到 452）。
    _TOOL_SINGLE_FILE_DESIGN_Y = 452
    _TOOL_SINGLE_FILE_SHIFT = 0
    # 演员库维护组底部的别名分片行控件（按设计横排顺序，从左到右）。
    # 最小化/还原态整行顺排时按此顺序取设计宽度依次摆放，且首项「全量更新并入」
    # 的左缘由 _actor_db_sync_row_left 对齐到封面补图组的「覆盖已有图片」。
    _ACTOR_DB_SYNC_ROW_NAMES = (
        "checkBox_actor_db_alias_all",
        "label_actor_db_sync_offset",
        "spinBox_actor_db_sync_offset",
        "label_actor_db_sync_limit",
        "spinBox_actor_db_sync_limit",
        "label_actor_db_sync_slice_hint",
    )
    # 「补全别名」说明标签（label_actor_db_sync_aliases_desc）最小化态的加宽封顶。
    # 实测依据（12px 字号，整串 996px）：设计宽 621px 下首行只能排到「…缺别名的行，」
    # （612px），第二行从「勾选「全量更新」」起；768px 下首行恰好排到「…则并入全部」
    # （768px），第二行为「行，用「起始行数/单次限制」可分片续跑」——即用户要的折行。
    # 再宽只会在右缘留白、不改变折行，故按可用宽自适应后封顶此值（见
    # _actor_db_aliases_desc_width）；组框被通用逻辑压到设计宽以下时退回设计宽 621px，
    # 窄窗行为与改动前逐像素一致。
    _ACTOR_DB_ALIASES_DESC_MAX_W = 768

    @classmethod
    def _actor_db_aliases_desc_width(cls, box_w: int) -> int:
        """最小化态「补全别名」说明标签宽度：随组框可用宽自适应、封顶 768px。

        标签 x=40、右边距按设计对称留 40px，故可用宽 = 组框宽 - 80；下限取
        _ACTOR_DB_TOOL_DESIGN 的设计宽（组框窄于设计宽时不再缩小，避免窄窗回归）。
        """
        design_w = cls._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_aliases_desc"][2]
        return max(min(box_w - 80, cls._ACTOR_DB_ALIASES_DESC_MAX_W), design_w)

    # 「起始行数0+单次限制5000=默认更新数据表行数」提示标签（label_actor_db_sync_slice_hint）
    # 最小化态单行整串所需的额外余量。背景：文案由「默认更新值」改为「默认更新数据表
    # 行数」后，12px 字号下该串 horizontalAdvance 由 240px 涨到 288px，超过设计宽
    # 211px；标签 wordWrap=True，排不下就折成两行、第二行被 28px 行高裁掉尾字。
    # 实测（离屏）：QTextDocument 量高在宽 ≤295px 时为 36px（两行）、≥296px 时
    # 22px（单行），即单行临界宽约 288+8=296；余量取 8px。QLabel.heightForWidth
    # 在此不可信（宽 211 也报 26px），判据以 QTextDocument 为准，同
    # tests/test_actor_db_hint_height.py 的坑注。
    _ACTOR_DB_SLICE_HINT_PAD = 8

    @classmethod
    def _actor_db_slice_hint_width(cls, hint) -> int:
        """最小化态分片行提示标签宽度：按字体度量取单行整串宽，不足设计宽时仍取设计宽。

        hint 的 wordWrap=True 是设计需要（窄窗时不让文字顶出组框左缘外），但常态下
        设计宽 211px 排不下加长后的整串文案，折行会裁字；故按「整串宽 + 余量」加宽，
        不足设计宽时（换回短文案或大字号以外的度量差异）保持 211px 不动。
        行内左缘仍由 _ACTOR_DB_SYNC_ROW_NAMES 顺排决定，只有末位标签的宽度向右拓展。
        """
        hint.ensurePolished()  # 字号来自样式表，未 polish 时 fontMetrics 不反映 12px
        design_w = cls._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_slice_hint"][2]
        need = hint.fontMetrics().horizontalAdvance(hint.text()) + cls._ACTOR_DB_SLICE_HINT_PAD
        return max(design_w, need)

    def _actor_db_sync_row_left(self, ui, box) -> int:
        """最小化态别名分片行的左缘（组内局部 x）：与封面补图组「覆盖已有图片」严格同列。

        背景：两枚复选框分属兄弟 groupBox，绝对 x 相等即视觉上下对齐。_sync_page_layouts
        里本方法早于 _sync_cover_backfill_option_row 执行，读到的是上一遍写回的几何——
        但「覆盖已有图片」的 x 恒为设计值（_sync_cover_backfill_option_row 只按 extra
        平移另两枚，首框永远钉在 40），故本测量跨遍稳定、可直接依赖。

        跨框 mapTo 是未定义行为（两框无祖先关系，同 _sync_guaxiaomulu_clean_tip_align 里
        「跨分支 mapTo」的坑注），故经共同祖先（滚动内容区）中转：各自 mapTo(host)
        后作差，得到的就是 box 的局部 x。

        回退：ui 结构不符预期（缺框、缺控件、父子关系变化）时回退设计值 40，
        即 .ui 里的设计几何，保证与最大化态不产生额外偏差。
        """
        fallback = self._ACTOR_DB_TOOL_DESIGN["checkBox_actor_db_alias_all"][0]
        cover_box = getattr(ui, "groupBox_cover_backfill", None)
        overwrite = getattr(ui, "checkBox_cover_backfill_overwrite", None)
        if cover_box is None or overwrite is None or overwrite.parentWidget() is not cover_box:
            return fallback
        host = box.parentWidget()
        if host is None or cover_box.parentWidget() is not host:
            return fallback
        return overwrite.mapTo(host, QPoint(0, 0)).x() - box.mapTo(host, QPoint(0, 0)).x()

    # 软件工具页封面补图组三选项行的常态几何（与 MDCx.ui 一致；y 中心同为 135）。
    # _sync_cover_backfill_option_row 按此落常态，最大化只把两处间隙等量拉开。
    _COVER_BACKFILL_OPTION_DESIGN = {
        "checkBox_cover_backfill_overwrite": (40, 125, 161, 20),
        "checkBox_cover_backfill_watermark": (220, 125, 161, 20),
        "checkBox_create_link": (410, 120, 191, 30),
    }
    # groupBox_cover_backfill 的 .ui 设计宽度（30, 962, 701, 200）：增量基准。
    _COVER_BACKFILL_DESIGN_W = 701
    # 「清除所有.actors 文件夹」与 checkBox_actor_photo_ne_new（请求 Graphis 最新
    # 图片）左缘对齐——用户截图上它仍停在最右，未纳入后续对齐需求。
    _ACTOR_PAGE_GRAPHIS_TARGETS = ("pushButton_del_actor_folder",)
    # 最大化态：「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘。目标即上面
    # _ACTOR_PAGE_GRAPHIS_TARGETS 那枚（groupBox_68 内 _DOCK_RIGHT 绝对定位项）；锚点
    # 取「本地头像库」行的 pushButton_select_actor_photo_folder——另一个
    # pushButton_select_gfriends_local 与它在 layoutWidget_8 的 gridLayout 里同列，
    # 窄态 689 / 宽态 1579 两态右缘恒等，任选其一皆可。
    _ACTOR_PAGE_DEL_BTN = "pushButton_del_actor_folder"
    _ACTOR_PAGE_SEL_BTN = "pushButton_select_actor_photo_folder"
    # 最大化态：「网络头像库：」显示输入框(lineEdit_net_actor_photo)与「Gfriends 本地
    # 仓库：」「本地头像库：」两行的显示输入框上下对齐。后两者与一枚 Fixed 110px 的
    # 「选择目录」按钮同处一个水平行，网格只能按「输入框 + spacing + 按钮」排完，
    # 右缘自然停在按钮列；而「网络头像库」行的输入框是 layoutWidget_8 网格里的直
    # 接项、右边没有按钮，宽态下会独占整列富余宽度，比另两枚宽出整整一枚按钮的宽
    # （1920 实测 1393 vs 1277，右缘 1579 vs 1463），上下参差。故宽态把它钉成与
    # 「Gfriends 本地仓库」输入框同宽：左缘本就同列（A1），钉宽后右缘也相等。
    # 参照输入框取 Gfriends 那枚而不是「本地头像库」那枚：两者宽态实测恒等，
    # 而 Gfriends 那枚与需求① 反推按钮列用的是同一行，几何已在本拍落定。
    _ACTOR_PAGE_NET_PATH_EDIT = "lineEdit_net_actor_photo"
    _ACTOR_PAGE_PATH_REF_EDIT = "lineEdit_gfriends_local_path"
    # 最小化态：同一枚「网络头像库」输入框改由 _sync_actor_page_narrow_align 末尾第 ⑤ 步
    # 钉宽（用户要求窄态右缘缩进对齐），与宽态第 ⑥ 步互为镜像、同一对控件同一手法。
    # 该网格（layoutWidget_8）要一并登记进 _clear_actor_narrow_align 的重排行名里，
    # 否则解锁后网格不重排，控件仍停在窄态钉宽。
    _ACTOR_PAGE_NET_PATH_GRID = "layoutWidget_8"
    # 与 checkBox_actor_photo_ne_face（使用 Graphis 头像，即 A2 列）左缘对齐的两个
    # 右缘锚定项：「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」。
    _ACTOR_PAGE_A2_TARGETS = (
        "checkBox_actor_photo_auto",
        "checkBox_actor_info_photo",
    )
    # A2 列锚点：使用 Graphis 头像
    _ACTOR_PAGE_A2_ANCHOR = "checkBox_actor_photo_ne_face"
    # 需求②：checkBox_actor_photo_kodi 与 radioButton_actor_photo_miss
    # （仅缺少头像的演员）左缘对齐——后者本就被移到 A2，故 kodi 随之到位。
    _ACTOR_PAGE_MISS_TARGETS = ("checkBox_actor_photo_kodi",)
    # 窄态：上方两枚「开始补全」收窄到与最下方那枚同宽（参照 pushButton_add_actor_pic_kodi）。
    # 三者分属三个 groupBox 的绝对定位项，宽度互不影响，故可独立处理。
    _ACTOR_NARROW_ADD_BTN_TARGETS = ("pushButton_add_actor_info", "pushButton_add_actor_pic")
    # 窄态：「仅缺少信息的演员」「仅缺少头像的演员」也左移到 A2 列。它们都是各自行的
    # **尾项**，行内间隔只能增不能减，故左移只能靠同行前导项（两个「所有演员」）收窄让位。
    # 「本地头像库」所在的来源行 hl95 结构不同（目标是 Fixed 宽单选、行尾是嵌套子布局），
    # 由下面 _ACTOR_NARROW_SOURCE_PULL 单独处理，不并入本表。
    # (行布局, 目标控件, 前导项控件, 容器)
    _ACTOR_NARROW_LEFT_PULL_ROWS = (
        (
            "horizontalLayout_101",
            "radioButton_actor_info_miss",
            "radioButton_actor_info_all",
            "layoutWidget_15",
        ),
        (
            "horizontalLayout_96",
            "radioButton_actor_photo_miss",
            "radioButton_actor_photo_all",
            "layoutWidget_12",
        ),
        (
            "horizontalLayout_103",
            "radioButton_server_jellyfin",
            "radioButton_server_emby",
            "gridLayoutWidget_25",
        ),
    )
    # 窄态：来源行 hl95 的「本地头像库」连同紧跟其后的「点击下载头像包」左移到 A2 列。
    # (行布局, 目标控件, 前导项控件, 行尾嵌套子布局)
    # 该行套不了上面那套「前导项收窄 + 行尾插 Expanding 间隔」：目标单选是 Fixed 宽
    # （min==max==59）吸不走余量、必须插间隔；而行尾 hl97 是嵌套子布局（内含
    # 「点击下载头像包」一枚 QLabel、文字实测 84px），插了间隔会与它争余量、把链接
    # 文字夹没（实测被压到 49px）。改用「stretch 挪给行尾 + 前导项钉窄」：前导项钉死
    # 后不再参与余量分配，行尾吃满剩余宽度（只会变宽、不会夹字），目标左缘正好落在
    # 前导项右侧。曾试过直接钉住行尾那枚 QLabel 的现宽，副作用是 hl95 的最小宽随之
    # 变化、把 layoutWidget_8 的三等分挤偏（A2 由 356 漂到 362），故不取。
    _ACTOR_NARROW_SOURCE_PULL = (
        "horizontalLayout_95",
        "radioButton_actor_photo_local",
        "radioButton_actor_photo_net",
        "horizontalLayout_97",
    )
    # 前导项收窄下限：绝对保底 90px。「所有演员」类短文本真实渲染约 75~90px，
    # 90 既不夹字、又让 850~940 宽的窄窗也能对齐。早期写死 130 会在窄窗下因
    # 1px 之差整行放弃（940 宽真实字体环境下 want=129 < 130，「仅缺少头像的
    # 演员」停在 A2 列右侧 124px，正是用户截图里的错位）。刻意不用 sizeHint：
    # 离屏桩字体（50px）与真实 CJK 字体（~130px）对同一控件量出完全不同的值，
    # 跟随它反而让行为随环境漂移（已实测回退）。与 _ACTOR_NARROW_MIN_DONOR_W /
    # _ACTOR_PAGE_A2_MIN_LEAD_W 同口径。只用于窄态左移两处，宽态逻辑不引用，
    # 最大化不受影响。
    _ACTOR_NARROW_MIN_LEAD_W = 90
    # QSizePolicy::GrowFlag 的位值。PyQt6 的 QSizePolicy.Policy 只导出 Fixed /
    # Minimum / Maximum / Preferred / MinimumExpanding / Expanding / Ignored 七档，
    # 没有单独导出 GrowFlag，只能按位取（GrowFlag=1、ShrinkFlag=2）。
    _SIZE_POLICY_GROW_FLAG = 1
    # ── 最大化态：三个布局行把目标控件对到 A2 列 ──
    # (行布局, 容器, 目标控件, 目标前的末项, 是否需要加宽容器)
    # 「仅缺少头像的演员」所在 layoutWidget_12 是固定宽 511 的绝对定位件，塞不进
    # 203px 的右移量，必须先把容器加宽（见 _ACTOR_INFO_SCOPE_HOLDER_DESIGN 注释
    # 里 layoutWidget_15 的同款做法）；另两行的容器是随窗口变的一整列。
    _ACTOR_PAGE_A2_ROWS = (
        (
            "horizontalLayout_96",
            "layoutWidget_12",
            "radioButton_actor_photo_miss",
            "radioButton_actor_photo_all",
            True,
        ),
        (
            "horizontalLayout_103",
            "gridLayoutWidget_25",
            "radioButton_server_jellyfin",
            "radioButton_server_emby",
            False,
        ),
        (
            "horizontalLayout_95",
            "layoutWidget_8",
            "radioButton_actor_photo_local",
            "radioButton_actor_photo_net",
            False,
        ),
    )
    # 「点击下载头像包」（label_download_actor_zip，在 hl95 尾部子布局 hl97 内）与
    # 「本地头像库」同行紧跟其后，用户要求二者一同对齐到 A2——它不是独立目标，
    # 只需跟着尾部 stretch 走，故不在上表单列，此处仅供断言/文档引用。
    _ACTOR_PAGE_A2_FOLLOWERS = (("radioButton_actor_photo_local", "label_download_actor_zip"),)
    # layoutWidget_12 的设计几何（相对 frame_2，MDCx.ui 140,1,511,41）：宽态加宽、
    # 窄态按此复位。它不进任何 registry，故窄态通用同步不会自愈，必须显式还原。
    _ACTOR_PAGE_HOLDER12_DESIGN = (140, 1, 511, 41)
    # 前导项收窄让位的下限：文字 + 单选指示器实测 ~130px，低于此值宁可不移
    _ACTOR_PAGE_A2_MIN_LEAD_W = 150
    # checkBox_actor_photo_kodi 在 groupBox_68 内被 _classify_inner 判为 None
    # （既非 _STRETCH 也非右缘 ≥90%），压根没进 registry，于是通用宽幅同步
    # 既不会推它、也不会在还原时把它推回来。最大化被本方法挪走后只能靠自己复位，
    # 故单独记下它的设计几何（相对 groupBox_68，与 MDCx.ui 一致）。
    # （「刮削结束后自动创建头像」已上移到「图片已存在时」行：y=68 使其文字与
    # label_415「图片已存在时：」文字中心严格同高——两者墨迹中心都是 87.6。）
    _ACTOR_PAGE_MISS_DESIGN = (300, 68, 180, 40)
    # ── 演员信息组（groupBox_64）列对齐：行标签冒号 + 各行左缘对到 Graphis 列 ──
    # 锚点是 groupBox_41（头像组）horizontalLayout_93 里三个 Graphis 复选框的左缘：
    # 宽态实测 186 / 652 / 1119；窄态实测 186 / 346 / 505（此时 A1 恰与演员信息组
    # col1 起点、「中文简体」同列，故窄态用 A1 当基准 = 用户要的「与中文简体对齐」）。
    # 这里只存控件名，实际 x 一律运行时 mapTo 实测，不写死。
    _ACTOR_INFO_A1_ANCHOR = "checkBox_actor_photo_ne_backdrop"  # 使用Graphis背景
    _ACTOR_INFO_A2_ANCHOR = "checkBox_actor_photo_ne_face"  # 使用Graphis头像
    _ACTOR_INFO_A3_ANCHOR = "checkBox_actor_photo_ne_new"  # 请求Graphis最新图片
    # 演员信息组 gridLayout_14 的 col0（行标签列）设计宽
    _ACTOR_INFO_LABEL_COL_W = 130
    # 「补全范围：」行（绝对定位链路 frame_4/layoutWidget_15/horizontalLayout_101）
    _ACTOR_INFO_SCOPE_ROW = ("radioButton_actor_info_all", "radioButton_actor_info_miss")
    # layoutWidget_15 相对 frame_4 的设计几何（MDCx.ui 140,10,511,32）
    _ACTOR_INFO_SCOPE_HOLDER_DESIGN = (140, 10, 511, 32)
    # 把它左移到 136 = gridLayout_14 的 col1 起点（= content 186 = A1 列），
    # 于是「所有演员」自然落在 A1 左缘，无需再插间隔。
    _ACTOR_INFO_SCOPE_WIDE_X = 136
    # 「补全范围：」两个单选的设计宽（窄态实测 253/252，511 = 253+6+252 恰好铺满
    # layoutWidget_15 的设计宽）。宽态拉宽容器前必须先按这两值 setFixedWidth，否则
    # Minimum 策略的单选会跟着容器长到 366，钉位间隔就没空间了。
    _ACTOR_INFO_SCOPE_W = (253, 252)
    # 宽态把容器拉宽后，「仅缺少信息的演员」右缘 + 内边距留白
    _ACTOR_INFO_SCOPE_PAD = 20
    # 宽态：「演员信息数据库：」路径输入框的右缘目标列 = 「选择目录」按钮左缘。
    # 取 Gfriends 本地仓库那枚（pushButton_select_gfriends_local，Fixed 110px 不动）——
    # 它与「本地头像库」行的 pushButton_select_actor_photo_folder 同处
    # layoutWidget_8 网格的同一列，两态右缘恒等，故「选择文件」按它对齐即与下方两枚
    # 「选择目录」严格上下对齐，而下方两枚自身位置一个像素都不动。
    _ACTOR_INFO_SEL_FOLDER_BTN = "pushButton_select_gfriends_local"
    # 上面那行路径输入框锁宽的下限：MDCx.ui 里 lineEdit_actor_db_path 的 minimumSize
    # 宽 300。宽度不足（窗口很窄）时宁可不锁，保持通用布局给出的宽度。
    _ACTOR_INFO_PATH_MIN_W = 300
    # 宽态各行左缘目标（需求① + 上一轮的②③④）：「使用数据库补全演员信息」与
    # 「不存在中文时，翻译日语为中文」连同同排后续控件一并对齐 A1；语言行维持
    # 简/繁/日 = A1/A2/A3。「演员信息数据库：」路径行不在此表——它由需求② 单独
    # 按「左缘 A1、右缘 A2」铺排（见 _sync_actor_info_columns）。
    _ACTOR_INFO_WIDE_TARGETS = {
        "horizontalLayout_92": (
            ("radioButton_actor_info_zh_cn", "A1"),
            ("radioButton_actor_info_zh_tw", "A2"),
            ("radioButton_actor_info_ja", "A3"),
        ),
        "horizontalLayout_100": (("checkBox_actor_info_translate", "A1"),),
        "horizontalLayout_159": (("checkBox_actor_db", "A1"),),
    }
    # 受控行的前导缩进（必须先归零，行起点才等于 col1 起点——间隔只能右推、不能左拉）：
    # .ui 里 hl100 是 hl98 的**子布局**、hl159 是 hl158 的子布局，缩进来自「父布局的
    # spacing + 前导控件」，不是子布局自己的 margin：
    #   hl98 = [label_280(Fixed 10), hl100]  → spacing 6 + label 10 = 16px
    #   hl158 = [hl159(leftMargin 20)]       → 20px
    # 故对**父布局**归零 spacing、对 hl159 归零 leftMargin，并把 label_280 压到 0 宽。
    # (父布局名, spacing, 左内边距, 行首占位控件名或 None)
    _ACTOR_INFO_ROW_LEAD_INDENT = (
        ("horizontalLayout_98", 0, "label_280"),
        ("horizontalLayout_159", 0, None),
    )
    # 自身 leftMargin 非零、需归零的行布局（hl159 的 20px）
    _ACTOR_INFO_ROW_ZERO_MARGIN = ("horizontalLayout_159",)
    # 窄态：语言行把「中文繁体」右移到 A2、「日语」右移到 A3（中文简体不动）；
    # 「不存在中文时，翻译日语为中文」与「使用数据库补全演员信息」连同同排后续控件
    # 左移到 A1。窄态 A1→A2 仅 160px，但语言行尾部本就有 Expanding 间隔可吸收位移，
    # 故繁/日两列放得下（1000 宽实测 need 102/101）。
    _ACTOR_INFO_NARROW_TARGETS = {
        "horizontalLayout_92": (
            ("radioButton_actor_info_zh_tw", "A2"),
            ("radioButton_actor_info_ja", "A3"),
        ),
        "horizontalLayout_100": (("checkBox_actor_info_translate", "A1"),),
        "horizontalLayout_159": (("checkBox_actor_db", "A1"),),
    }
    # ── 演员页窄态（最小化/还原）右移对齐 ──
    # 锚点（自身保持不动）：checkBox_actor_photo_ne_face「使用Graphis头像」。
    # 它是 A2 列的对齐基准，窄态下各缺信息/缺头像行向左移动到与 A2 严格上下对齐。
    # 最大化时（_actor_page_stretch_extra() > 0）窄态逻辑不生效，全部保持不变。
    _ACTOR_NARROW_ANCHOR = "checkBox_actor_photo_ne_face"
    # 走「目标收窄 + 同行间距撑开」让位的行（需求①②④）：
    # (行布局, 目标控件, 容器, 需钉宽的项[(控件, 钉宽)])
    # 前两行的容器宽恒为设计值 511（layoutWidget_15 每遍被 _sync_actor_info_columns
    # 重设，layoutWidget_12 压根不进任何 registry），故钉宽值是常数 253/252；
    # 服务类型行的容器宽随窗口变（col1 = 503/473/1393），两个单选是「均分」关系，
    # 钉宽值必须取当前实宽，locks 里写 None 即表示「钉到当前宽」。
    _ACTOR_NARROW_SCOPE_ROWS = (
        (
            "horizontalLayout_101",
            "radioButton_actor_info_miss",
            "layoutWidget_15",
            (("radioButton_actor_info_all", 253), ("radioButton_actor_info_miss", 252)),
        ),
        (
            "horizontalLayout_96",
            "radioButton_actor_photo_miss",
            "layoutWidget_12",
            (("radioButton_actor_photo_all", 253), ("radioButton_actor_photo_miss", 252)),
        ),
        (
            "horizontalLayout_103",
            "radioButton_server_jellyfin",
            "gridLayoutWidget_25",
            (("radioButton_server_emby", None), ("radioButton_server_jellyfin", None)),
        ),
    )
    # 「演员信息数据库：」行（gridLayoutWidget_14/horizontalLayout_155）：
    # 「选择文件」右移到与「选择目录」同列，路径框右缘同时撑到按钮左缘。
    # (行布局, 路径框, 按钮, 对齐基准按钮)
    _ACTOR_NARROW_PATH_ROW = (
        "horizontalLayout_155",
        "lineEdit_actor_db_path",
        "pushButton_select_actor_info_db",
        "pushButton_select_gfriends_local",
    )
    # 路径框收窄下限：低于此值宁可不右移（实测需求值 409 + extra，最低 ~297）
    _ACTOR_NARROW_PATH_MIN_W = 200
    # 「来源」行（layoutWidget_8 的 horizontalLayout_95）：目标是「本地头像库」，其右侧
    # 「点击下载头像包」（hl97 子布局）与它同属一行、随之一起右移。
    # (行布局, 目标控件, 前导项控件名, 行尾子布局名)
    _ACTOR_NARROW_SOURCE_ROW = (
        "horizontalLayout_95",
        "radioButton_actor_photo_local",
        "radioButton_actor_photo_net",
        "horizontalLayout_97",
    )
    # 目标控件收窄让位的下限：文字 + 单选指示器实测 ~130px，低于此值宁可不右移，
    # 也不让控件把自己的文字挤没（当前 need 上限 ~35px，实测不会触发，留作防线）。
    _ACTOR_NARROW_MIN_DONOR_W = 150

    def _sync_actor_db_tool_layout(self) -> None:
        """软件工具页演员库分组：紧凑排布 + 最大化拉宽。

        背景：scrollArea_10 内 groupBox_actor_db_maintenance 最大化时被通用逻辑拉宽，
        而内部绝对定位子项默认只有拉伸/右缘锚定两种跟随（说明被钉到最右侧、
        输入框/下拉拉伸盖住按钮）。本方法在 _sync_page_layouts 末尾执行
        （通用拉伸之后覆盖），接管组内全部 22 个控件：
        - 常态（最小化/还原）：按 _ACTOR_DB_TOOL_DESIGN 紧凑排布；
        - 最大化：宽幅控件拉宽，右列按钮（LibreDMM/停止/minnano/检查）保持在右列。

        例外两处：常态下「补全别名」说明「来源TMDB需配置TMDB API KEY；…」
        （整串实测 996px）按组框可用宽加宽（封顶 768px，
        见 _ACTOR_DB_ALIASES_DESC_MAX_W 的折行实测）、高度取两行；常态下末位提示标签
        「起始行数0+单次限制5000=默认更新数据表行数」按字体度量取单行整串宽
        （设计宽排不下会折行裁字，见 _actor_db_slice_hint_width）。
        （顶部同文案说明已删除，组内其余控件整体上移一行，组框同步收窄。）
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_actor_db_maintenance", None)
        if box is None or not box.isVisibleTo(self):
            # 休眠页跳过（切页 showEvent 后 _sync_page_layouts 会补齐）
            return
        widgets = {name: getattr(ui, name, None) for name in self._ACTOR_DB_TOOL_DESIGN}
        if any(w is None for w in widgets.values()):
            return
        # 链接缺项说明、打开库说明、JavDB中文名空说明已删除（两态隐藏）
        ui.label_actor_db_link_desc.hide()
        ui.label_actor_db_open_desc.hide()
        ui.label_actor_db_fill_zh_javdb_desc.hide()
        maxed = self.isMaximized()
        box_w = box.width()
        # 先按常态紧凑几何落位
        for name, (x, y, w, h) in self._ACTOR_DB_TOOL_DESIGN.items():
            widgets[name].setGeometry(x, y, w, h)
        note = widgets["label_actor_db_note"]
        if not maxed:
            # 基准取 _ACTOR_DB_TOOL_BOX_DESIGN 而非当前高：绝对设值、双向幂等。
            _bx, _by, _bw, _ = box.geometry().getRect()
            box.setGeometry(_bx, _by, _bw, self._ACTOR_DB_TOOL_BOX_DESIGN[3])
            # 常态复位顶部两枚按钮位置（translate/link 不在 _ACTOR_DB_TOOL_DESIGN 内，
            # 最大化分支改过它们的宽度，窄态必须显式恢复 200 宽）
            ui.pushButton_actor_db_translate.setGeometry(40, 58, 200, 32)
            ui.pushButton_actor_db_link.setGeometry(260, 58, 200, 32)
            # 「补全别名」说明按组框可用宽加宽（封顶见 _ACTOR_DB_ALIASES_DESC_MAX_W）：
            # 设计宽 621px 下首行只排到「…缺别名的行，」，加宽后首行排到「…则并入全部」，
            # 折行与用户要求一致。组框窄于设计宽时退回 621px，其余控件相对间距不变。
            _, desc_y0, _, desc_h0 = self._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_aliases_desc"]
            widgets["label_actor_db_sync_aliases_desc"].setGeometry(
                40, desc_y0, self._actor_db_aliases_desc_width(box_w), desc_h0
            )
            # 窄窗下通用逻辑会收缩单文件组输入框并左移其按钮，nfo/别名两行按钮
            # 跟随同量 extra 收缩（输入框/下拉宽度由 _sync_tool_page_input_fill
            # 按实时按钮位置统一拓宽，此处只摆按钮）
            extra_nb = box_w - 701
            if extra_nb != 0:
                _, pick_y0, _, pick_h0 = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_pick_nfo_dir"]
                # 保底 19px 间隙且输入框不窄于 150：按钮 x 不小于 40+150+19
                pick_x_nb = max(571 + extra_nb, 40 + 150 + 19)
                widgets["pushButton_actor_db_pick_nfo_dir"].setGeometry(pick_x_nb, pick_y0, 110, pick_h0)
                # 补全别名按钮与清空信息按钮同列：清空信息通用逻辑按 571+extra 左移，本按钮同公式跟随
                _, alias_y0, alias_w0, alias_h0 = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_sync_aliases"]
                widgets["pushButton_actor_db_sync_aliases"].setGeometry(571 + extra_nb, alias_y0, alias_w0, alias_h0)
            # 别名分片行：统一 y 高度，整行零间隙顺排，左缘与封面补图组的
            # 「覆盖已有图片」严格上下对齐（用户要求）。此前把右缘钉到封面补图
            # 番号输入框右缘 552 反推左缘，六控件设计宽合计 601 > 552-40，
            # 左缘被推到 -49（组框左缘之外），首枚复选框被裁成「更新并入」；
            # 改由 _actor_db_sync_row_left 直接取对齐左缘（设计值 40），
            # 整行随之前移，右缘随之落到 641（末位提示标签按字体度量加宽后为 726，
            # 见下方 _actor_db_slice_hint_width），窄窗下本就略越组框右缘——
            # 组框不裁剪子控件，与组宽无关。
            _, sync_y, _, _ = self._ACTOR_DB_TOOL_DESIGN["checkBox_actor_db_alias_all"]
            current_x = self._actor_db_sync_row_left(ui, box)
            for name in self._ACTOR_DB_SYNC_ROW_NAMES:
                w = self._ACTOR_DB_TOOL_DESIGN[name][2]
                # 末位提示标签按字体度量取单行整串宽（加长文案后 211px 设计宽排不下，
                # wordWrap 会折成两行、第二行被 28px 行高裁掉）：宽度不够就向右拓展，
                # 左缘仍紧接末位 spin，行内其余五项逐像素不动。组框不裁剪子控件，
                # 窄窗下整行本就越出组框右缘（实测 760px 窗宽时右缘 641 > 组宽 409），
                # 故此处不再按组框可用宽封顶，避免又折回两行。见 _actor_db_slice_hint_width。
                if name == "label_actor_db_sync_slice_hint":
                    w = self._actor_db_slice_hint_width(widgets[name])
                widgets[name].setGeometry(current_x, sync_y, w, 28)
                current_x += w
            # 最小化/还原态：单文件刮削组顶边按设计值绝对设值、双向幂等。
            # （顶部说明删除后不再需要下移一行，_TOOL_SINGLE_FILE_SHIFT 保留为 0。）
            # 最大化分支不执行，宽态仍停在设计顶边 452。
            single = getattr(ui, "groupBox_7", None)
            if single is not None:
                _sx, _, _sw, _sh = single.geometry().getRect()
                single.setGeometry(_sx, self._TOOL_SINGLE_FILE_DESIGN_Y + self._TOOL_SINGLE_FILE_SHIFT, _sw, _sh)
            return
        # ---- 最大化：拉宽 ----
        extra = max(box_w - 701, 0)  # 组框相对设计宽度的增量
        note.setGeometry(40, 30, 621 + extra, 20)
        # ---- 顶部 5×2 维护按钮：两列同步向左右拓宽（extra 均分，列间距 20 不变，高度不变）----
        half = extra // 2
        left_w = 200 + half
        right_x = 260 + half
        right_w = 200 + extra - half
        ui.pushButton_actor_db_translate.setGeometry(40, 58, left_w, 32)
        ui.pushButton_actor_db_link.setGeometry(right_x, 58, right_w, 32)
        widgets["pushButton_actor_db_open"].setGeometry(40, 90, left_w, 28)
        widgets["pushButton_actor_db_stop"].setGeometry(right_x, 90, right_w, 28)
        widgets["pushButton_actor_db_clean_male"].setGeometry(40, 118, left_w, 30)
        widgets["pushButton_actor_db_fill_Minnano"].setGeometry(right_x, 118, right_w, 30)
        widgets["pushButton_actor_db_verify_tmdbid"].setGeometry(40, 148, left_w, 30)
        widgets["pushButton_actor_db_check"].setGeometry(right_x, 148, right_w, 30)
        widgets["pushButton_actor_db_update_nfo_tmdbid"].setGeometry(40, 184, left_w, 30)
        widgets["pushButton_actor_db_fill_zh_javdb"].setGeometry(right_x, 184, right_w, 30)
        widgets["label_actor_db_update_nfo_desc"].setGeometry(40, 260, 621 + extra, 28)
        widgets["label_actor_db_sync_aliases_desc"].setGeometry(40, 356, 621 + extra, 42)
        # nfo 目录行：选择目录按钮落位 (571+extra, 110x40)；输入框宽度由
        # _sync_tool_page_input_fill 统一拓宽到按钮左侧，此处不再定宽
        _, pick_y, _, pick_h = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_pick_nfo_dir"]
        pick_w = 110
        pick_x = 571 + extra
        widgets["pushButton_actor_db_pick_nfo_dir"].setGeometry(pick_x, pick_y, pick_w, pick_h)
        # 别名行：补全别名按钮与「选择目录/选择文件」同列同尺寸 (571+extra, 110x40)；
        # TMDB 下拉宽度同样由 _sync_tool_page_input_fill 接管
        _ax, combo_y, _, _ah = self._ACTOR_DB_TOOL_DESIGN["comboBox_actor_db_alias_source"]
        widgets["pushButton_actor_db_sync_aliases"].setGeometry(pick_x, combo_y - 4, 110, 40)
        # 起始行/限量提示：紧贴 5000 调整框右侧，不随右缘锚定飞到最右边
        # 最大化时别名同步行其余控件保持设计几何不动（原有行为）
        spin = ui.spinBox_actor_db_sync_limit
        hint = widgets["label_actor_db_sync_slice_hint"]
        hint.setGeometry(spin.x() + spin.width() + 10, spin.y(), 261, spin.height())

    def _sync_cover_backfill_option_row(self) -> None:
        """软件工具页封面补图组三选项行：最大化时同步拉开间距。

        背景：scrollArea_10 内 groupBox_cover_backfill 最大化时被通用逻辑拉宽，
        而组内三枚复选框（覆盖已有图片 / 添加水印 / 刮削过程中自动创建软链接）
        在通用登记表里都判为 None——宽度 161/191 不足「拉伸」阈值 340，右缘 601
        也不到「右缘锚定」阈值 631，于是被整体丢下：组框变宽而三框仍挤在
        40/220/410，右侧空出一大片。本方法在 _sync_page_layouts 中紧随通用拉伸
        与 _sync_actor_db_tool_layout 之后执行（务必晚于 sync_wide_children_width，
        否则读到的组宽还是旧的），接管这三枚复选框的水平位置。

        公式（x 只动、y/w/h 恒定）：
        - extra = max(组宽 - 701, 0)：组框相对设计宽度的增量；
        - half = extra // 2：两处间隙各摊一半，首框贴左缘、末框贴右缘；
        - 覆盖已有图片 40 固定，添加水印 220+half，软链接 410+extra。
        于是 gap1 = 19+half、gap2 = 29+half（差恒为 10，与常态一致），
        末框右缘 601+extra 与组内缘 701+extra 的距离恒为 100px。

        判据用几何量而非 isMaximized()：最大化时窗口管理器先发尺寸、状态位稍后
        才生效，用 isMaximized() 会先停在常态、再跳到宽态（见
        _actor_page_stretch_extra 的坑）。extra==0 时三框恰好写回常态几何，
        故本方法天然幂等，缩小还原也能逐像素复原。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_cover_backfill", None)
        if box is None or not box.isVisibleTo(self):
            # 休眠页跳过（切页 showEvent 后 _sync_page_layouts 会补齐）
            return
        opts = {name: getattr(ui, name, None) for name in self._COVER_BACKFILL_OPTION_DESIGN}
        if any(w is None for w in opts.values()):
            return
        extra = max(box.width() - self._COVER_BACKFILL_DESIGN_W, 0)
        half = extra // 2
        x1, y1, w1, h1 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_cover_backfill_overwrite"]
        x2, y2, w2, h2 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_cover_backfill_watermark"]
        x3, y3, w3, h3 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_create_link"]
        opts["checkBox_cover_backfill_overwrite"].setGeometry(x1, y1, w1, h1)
        opts["checkBox_cover_backfill_watermark"].setGeometry(x2 + half, y2, w2, h2)
        opts["checkBox_create_link"].setGeometry(x3 + extra, y3, w3, h3)

    def _sync_tool_page_input_fill(self) -> None:
        """软件工具页显示输入框（含 TMDB 下拉）向右拓宽到右侧按钮左侧。

        背景：通用逻辑只把输入拉到设计宽+extra、按钮按右缘锚定，行内 80px
        间隙恒定（按钮改窄后空出）。本方法在 _sync_page_layouts 中紧随通用拉伸、
        _sync_actor_db_tool_layout、_sync_cover_backfill_option_row 之后执行，
        取按钮终态位置把输入右缘钉到按钮左缘-19（19px 为原设计间隙）。

        判据用实时按钮几何而非 isMaximized()：大小态通用，窄窗下按钮左移时
        输入同步收缩；仅改宽，x/y/h 不动（封面补图番号输入除外：其 x 随
        标签列缩进，见下）。布局容器内的输入（网盘/本地目录、
        本地资源库/演员名查缺）通过拓宽容器让输入列吸收增量。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        GAP = 19  # 输入右缘与右侧按钮左缘间距
        # 绝对定位输入：右缘 = 同行右侧按钮左缘 - GAP
        for in_name, btn_name in (
            ("lineEdit_single_file_path", "pushButton_select_file"),
            ("lineEdit_appoint_url", "pushButton_select_file_clear_info"),
            ("lineEdit_actor_db_nfo_dir", "pushButton_actor_db_pick_nfo_dir"),
            ("comboBox_actor_db_alias_source", "pushButton_actor_db_sync_aliases"),
        ):
            edit = getattr(ui, in_name, None)
            btn = getattr(ui, btn_name, None)
            if edit is None or btn is None:
                continue
            edit.setGeometry(edit.x(), edit.y(), max(btn.x() - GAP - edit.x(), 150), edit.height())
        # 封面补图番号行：标签与软链接助手组本地目录标签（label_338，Fixed 100
        # 列）同列，输入框与网盘目录输入同列缩进；右缘仍钉到开始补图按钮左侧。
        # 网盘/本地目录标签与输入行位置保持不变，只读其几何作列基准。
        cover_edit = getattr(ui, "lineEdit_cover_backfill_numbers", None)
        cover_btn = getattr(ui, "pushButton_cover_backfill_start", None)
        cover_box = getattr(ui, "groupBox_cover_backfill", None)
        if cover_edit is not None and cover_btn is not None and cover_box is not None:
            net_box = getattr(ui, "gridLayoutWidget_36", None)
            src_box = getattr(ui, "groupBox_21", None)
            ref_label = getattr(ui, "label_338", None)
            ref_input = getattr(ui, "lineEdit_netdisk_path", None)
            if net_box is not None and src_box is not None and ref_label is not None and ref_input is not None:
                dx = net_box.x() + (src_box.x() - cover_box.x())
                cover_label = getattr(ui, "label_cover_backfill_number", None)
                if cover_label is not None:
                    cover_label.setGeometry(dx + ref_label.x(), cover_edit.y(), ref_label.width(), cover_edit.height())
                new_x = dx + ref_input.x()
            else:
                new_x = cover_edit.x()
            cover_edit.setGeometry(new_x, cover_edit.y(), max(cover_btn.x() - GAP - new_x, 150), cover_edit.height())
        # 布局容器内的输入：拓宽容器（标签列 Fixed，输入列吸收增量）
        for box_name, btn_name in (
            ("gridLayoutWidget_36", "pushButton_select_netdisk_path"),
            ("gridLayoutWidget_18", "pushButton_select_local_library"),
        ):
            box = getattr(ui, box_name, None)
            btn = getattr(ui, btn_name, None)
            if box is None or btn is None:
                continue
            box.setGeometry(box.x(), box.y(), max(btn.x() - GAP - box.x(), 230), box.height())
            lay = box.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
        # 刮削排除目录行（移动视频组）无右侧按钮：右缘与其它输入行看齐，
        # 钉到右侧按钮列左缘 - GAP（按钮列各按钮 x 一致，任取其一作基准）
        esc = getattr(ui, "lineEdit_escape_dir_move", None)
        ref_btn = getattr(ui, "pushButton_select_file", None)
        move = getattr(ui, "pushButton_move_mp4", None)
        if esc is not None:
            if ref_btn is not None:
                esc.setGeometry(esc.x(), esc.y(), max(ref_btn.x() - GAP - esc.x(), 150), esc.height())
            elif move is not None:
                esc.setGeometry(esc.x(), esc.y(), max(move.x() + move.width() - esc.x(), 150), esc.height())
        # 宽操作按钮（刮削/选择图片/一键创建软链接/开始移动/检查缺失番号）：
        # 右缘与本组显示输入框右缘看齐（= 右侧按钮列左缘 - GAP）；本组无右侧
        # 按钮时借用页级按钮列基准；仅改宽，x/y/h 不动
        page_ref = getattr(ui, "pushButton_select_file", None)
        for act_name, ref_name in (
            ("pushButton_start_single_file", "pushButton_select_file"),
            ("pushButton_select_thumb", None),
            ("pushButton_find_missing_number", "pushButton_select_local_library"),
            ("pushButton_move_mp4", None),
            ("pushButton_creat_symlink", "pushButton_select_netdisk_path"),
        ):
            act = getattr(ui, act_name, None)
            ref = getattr(ui, ref_name, None) if ref_name else page_ref
            if act is None or ref is None:
                continue
            act.setGeometry(act.x(), act.y(), max(ref.x() - GAP - act.x(), 150), act.height())
        # 「演员名查缺」右侧的类型下拉框：左缘与「选择目录」按钮左缘严格对齐、
        # 宽度同按钮、高度同输入框（用户 2026-10-25 要求）。宽度/高度都读实时几何，
        # 页宽变化时按钮被右缘锚定右移，下拉跟着走，两者永远同一条竖线上。
        combo = getattr(ui, "comboBox_actor_type", None)
        select_btn = getattr(ui, "pushButton_select_local_library", None)
        actor_edit = getattr(ui, "lineEdit_actors_name", None)
        anchor = getattr(ui, "groupBox_19", None)
        if combo is not None and select_btn is not None and actor_edit is not None and anchor is not None:
            edit_top = actor_edit.mapTo(anchor, actor_edit.rect().topLeft()).y()
            combo.setGeometry(select_btn.x(), edit_top, select_btn.width(), actor_edit.height())

    @staticmethod
    def _scroll_stretch_extra(scroll) -> int:
        """某个设置页滚动区当前的横向拉伸量（> 0 表示该页确实被拉宽了）。

        公式与 CustomScrollArea.sync_wide_children_width() 内部用的完全一致：
        视口宽 - 设计宽 - 右边距，这样「被拉宽」这件事只有一个判据来源。
        """
        if scroll is None:
            return 0
        content = scroll.widget()
        viewport = scroll.viewport()
        design_w = getattr(content, "_wide_children_design_width", 0) if content is not None else 0
        if not design_w or viewport is None:
            return 0
        return viewport.width() - design_w - scroll.content_right_trim()

    def _actor_page_stretch_extra(self) -> int:
        """演员页当前的横向拉伸量（见 _scroll_stretch_extra）。

        > 0 表示页面确实被拉宽了，这才是「该把三行对到基准线上」的判据。
        这里刻意不用 isMaximized()：最大化时窗口管理器先发尺寸、状态标志稍后才
        生效，那一拍里 isMaximized() 还是 False，于是右缘锚定被绘制出来，等标志
        到位再重排一次才对齐——用户看到的就是「先在右边、再跳到左边」。改用几何
        量后，拉伸与对齐永远发生在同一拍，与标志到达顺序无关。
        """
        return self._scroll_stretch_extra(getattr(self, "_actor_scroll", None))

    def _sync_actor_page_align(self, actor_scroll=None) -> None:
        """软件设置-演员页：两个基准线上的四个控件左缘对齐（仅页面被拉宽时生效）。

        用户截图（最大化态，1920 屏 content 1650 宽，组框 1569 宽）：
          ① 「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」「清除所有
             .actors 文件夹」三者的左缘停在 content_x=1348/1348/1388，而「请求
             Graphis 最新图片」在 1136，要求三者与它严格上下对齐（各自左移
             212/212/252px）；「请求 Graphis 最新图片」自身保持不变。
          ② 「刮削结束后自动创建头像」要求与「仅缺少头像的演员」严格上下对齐（右移
             119px）；「仅缺少头像的演员」自身保持不变。
        还原态页面、控件、布局必须保持不变（与纯设计几何逐像素一致）。

        根因：groupBox_41/64/68 的这四个控件是绝对定位直接子项，CustomScrollArea
        的通用宽幅同步按 _classify_inner 分类——右缘 ≥ 组框宽 90% 的判为
        _DOCK_RIGHT，最大化时执行 sub.move(design_x + extra) 把它们钉到右缘；
        而锚点 checkBox_actor_photo_ne_new 在 layoutWidget_8 内，是 _STRETCH
        （两项等分拉伸），于是被推到 1136，与右缘钉定的三者分属两条线。

        做法（只改「页面被拉宽」的态，还原态一个像素都不碰，纯函数、双向幂等）：
        本方法既挂在滚动区拉伸之后的钩子上（CustomClass._post_wide_sync_hook），
        也在 _sync_page_layouts 末尾再跑一遍：
          - 拉伸量 <= 0（还原态）**直接 return，一个 setGeometry 都不发**：还原态
            几何完全由 CustomScrollArea.sync_wide_children_width() 产出，本方法
            若去「落回设计几何」就会把 _DOCK_RIGHT 的 design_x + extra 覆盖成
            design_x，还原态凭空右移 -extra（实测 win=1030 时 extra=-26，三个控件
            齐刷刷右移 26px），违反「最小化时界面、控件、布局等等保持不变」。同理
            也不能把这几个名字挪进 _MANUAL_* 从 registry 里摘掉——那会让通用同步
            彻底不碰它们，还原态同样回到设计 x。故一律不摘不改。
          - 拉伸量 > 0：先显式重跑一次宽幅同步（拿到终态 extra，休眠页由切 tab 的
            showEvent 补齐），再用 mapTo 把锚点量到与目标同一个 content 祖先
            坐标系，得到「锚点绝对 x」与「目标当前绝对 x」，目标新 x = 当前 x +
            差值后 setGeometry；守卫 x>=0 且右缘不越父级，越界（窄屏）则该控件保持
            通用逻辑给出的位置。
          - 还原时通用逻辑每遍都会 move(design_x + extra) 自愈，不依赖本方法复位。
        休眠页跳过。

        历史坑：本方法早期用 isMaximized() 当判据，在窗口管理器「先发尺寸、后发状态」
        的真实顺序下判据读成 False，右缘锚定被绘制出来，等标志到位才二次对齐，于是
        出现「先在右边、再跳到左边」的跳动。判据换成 _actor_page_stretch_extra() 的
        几何拉伸量后，拉伸与对齐必然同一拍完成；还原时同样一拍完成缩回。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_41", None)
        if box is None or not box.isVisibleTo(self):
            return
            # 还原态（页面未被拉宽）：除 checkBox_actor_photo_kodi 外一个像素都不碰，
            # 几何完全交给通用宽幅同步（见 docstring）。kodi 未进 registry，通用逻辑
            # 不会自愈，必须显式复位，否则拉宽挪走后会一直停在锚点线上。
            # 判据是拉伸量而非 isMaximized()，理由见 _actor_page_stretch_extra。
            # ③「刮削结束后自动创建头像」（kodi）未进 registry，通用同步不会自愈，必须跟着
            # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在下面 hl96 循环
            # **之后**：量到的是 miss 移动后的新 x。
            return
        if actor_scroll is not None and actor_scroll.isVisibleTo(self):
            actor_scroll.sync_wide_children_width()  # 取终态 extra，勿量过期几何
        graphis = getattr(ui, "checkBox_actor_photo_ne_new", None)
        miss = getattr(ui, "radioButton_actor_photo_miss", None)
        widgets = {
            name: getattr(ui, name, None) for name in self._ACTOR_PAGE_GRAPHIS_TARGETS + self._ACTOR_PAGE_MISS_TARGETS
        }
        if graphis is None or miss is None or any(w is None for w in widgets.values()):
            return
        content = box.parentWidget()
        if content is None:
            return

        def shift_to(name, anchor):
            """把 name 的左缘对到 anchor 的左缘（同一 content 坐标系）。"""
            w = widgets[name]
            if w.parentWidget() is None or anchor.parentWidget() is None:
                return
            dx = anchor.mapTo(content, anchor.rect().topLeft()).x() - w.mapTo(content, w.rect().topLeft()).x()
            g = w.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > w.parentWidget().width():
                return  # 越出父级（窄屏最大化）：保持通用逻辑给出的位置
            if dx:
                w.setGeometry(nx, g.y(), g.width(), g.height())

        for name in self._ACTOR_PAGE_GRAPHIS_TARGETS:
            shift_to(name, graphis)
        for name in self._ACTOR_PAGE_MISS_TARGETS:
            shift_to(name, miss)

    def _clear_actor_wide_align(self) -> None:
        """清掉最大化态 A2 列对齐留下的钉宽/容器几何/stretch（先清后建，故幂等）。

        与 _clear_actor_narrow_align 同款：钉宽「记录原 min/max、原样写回」，
        不用 setFixedWidth(0) 真解锁——本方法与窄态那一对都会跑在
        _sync_actor_info_columns 之后，真解锁会拆掉那一拍刚钉好的宽态铺排。
        逆序写回的原因同上：同一控件一趟里可能被钉两次。
        """
        for kind, obj, saved in reversed(self._actor_wide_restores):
            if obj is None:
                continue
            if kind == "size":
                obj.setMinimumWidth(saved[0])
                obj.setMaximumWidth(saved[1])
                obj.updateGeometry()
            elif kind == "geometry":
                obj.setGeometry(saved)
            elif kind == "stretch":
                for i, value in enumerate(saved):
                    obj.setStretch(i, value)
        self._actor_wide_restores = []
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        for row_name, _, _, _, _ in self._ACTOR_PAGE_A2_ROWS:
            row = getattr(ui, row_name, None)
            if row is None or row.parentWidget() is None:
                continue
            row.invalidate()
            row.activate()

    def _sync_actor_page_wide_a2_align(self, actor_scroll=None) -> None:
        """最大化态：把若干控件左缘对到 A2 列（使用 Graphis 头像），锚点自身不动。

        用户需求（最大化时；最小化/还原态页面、布局、控件保持不变）：
          ① 「Jellyfin」「补全完成后自动补全演员头像」「本地头像库」「点击下载头像包」
             「刮削结束后自动补全演员头像」向左移动到与「使用 Graphis 头像」严格上下
             对齐的位置，「使用 Graphis 头像」自身保持不变；
          ② 「仅缺少头像的演员」「刮削结束后自动创建头像」向右移动到同一列。
          ③ 「清除所有.actors文件夹」右侧向右移动到与「选择目录」按钮上下对齐
             （右缘对齐，只平移不改宽度）。
          ④ 「网络头像库：」显示输入框收窄成与「Gfriends 本地仓库：」「本地头像库：」
             两行显示输入框同宽（上下对齐；左缘本就同列，收窄后右缘也相等）。

        A2 锚点是 checkBox_actor_photo_ne_face（使用 Graphis 头像，layoutWidget_8 内
        的 _STRETCH 三等分项），实际 x 一律运行时 mapTo 实测，绝不写死——
        1920 宽实测 652、1600 宽实测 546。

        三类控件三种手法（与窄态那套互不重叠，各自登记、各自还原）：
          - 右缘锚定的绝对定位项（「补全完成后自动补全演员头像」等）由
            _sync_actor_page_align 的 shift_to 处理，本方法不碰。
          - 只需「前导项收窄让位」的行：hl103（Jellyfin）与 hl95（本地头像库）。
            两行都是「均分可用宽」，把目标前的末项钉窄，目标的左缘就落在
            (行左缘 + 前导宽 + spacing) 上；行内总需求随之小于可用宽，**尾部项
            吸收全部余量**（hl103 的 Jellyfin / hl95 的 hl97），故这里必须把
            stretch 从头一项挪给尾一项——否则 Qt 会把余量摊回头一项，钉窄失效。
          - 容器是固定宽绝对定位件的行：hl96（仅缺少头像的演员）所在的
            layoutWidget_12 恒为 511，塞不下 203px 的右移量，先把容器加宽到
            「2×(目标相对位置) + spacing」让两等分项各占一半，再钉住。
          - 网格里的直系输入框（lineEdit_net_actor_photo）：钉宽（lock_width），
            见方法末尾 ⑥ 的注释。

        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _actor_page_stretch_extra docstring。窄态第一步清干净即 return，
        最小化态一个像素都不碰（layoutWidget_12 按设计几何复位，它不进任何
        registry、通用同步不会自愈）。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_41", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_actor_wide_align()
        if self._actor_page_stretch_extra() <= 0:
            # 窄态：只还原被加宽的容器（它不进任何 registry，通用同步不会自愈）。
            # kodi 的窄态位置由 _sync_actor_page_align 的窄态分支负责（它把 kodi
            # 按设计几何复位），本方法窄态一个像素都不碰它——否则会覆盖 ① 的结果。
            holder = getattr(ui, "layoutWidget_12", None)
            if holder is not None and holder.parentWidget() is not None:
                holder.setGeometry(*self._ACTOR_PAGE_HOLDER12_DESIGN)
            return
        # 刻意**不**重跑 sync_wide_children_width()：它会把 ① 刚对好的右缘锚定项
        # 重新 move(design_x + extra) 钉回右缘，把 ① 的成果整个抹掉。① 排在本方法
        # 之前、同一拍里刚跑完宽幅同步，量到的几何已是终态。
        content = box.parentWidget()
        if content is None:
            return
        anchor = getattr(ui, self._ACTOR_PAGE_A2_ANCHOR, None)
        if anchor is None:
            return
        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        def lock_width(w, width):
            if w is None:
                return
            if w.minimumWidth() == width and w.maximumWidth() == width:
                return
            self._actor_wide_restores.append(("size", w, (w.minimumWidth(), w.maximumWidth())))
            w.setFixedWidth(width)
            w.updateGeometry()

        def lock_stretch(row, tail_idx):
            self._actor_wide_restores.append(("stretch", row, [row.stretch(i) for i in range(row.count())]))
            for i in range(row.count()):
                row.setStretch(i, 1 if i == tail_idx else 0)
            row.invalidate()
            row.activate()

        # ① 两个「自动补全演员头像」是右缘锚定的绝对定位项（groupBox_41 / groupBox_64
        # 的直接子项），通用宽幅同步每遍都按 design_x + extra 把它们钉回右缘，故这里
        # 与 _sync_actor_page_align 的 shift_to 同款：量出差值后 setGeometry 左移。
        # 放在本方法而不是 _sync_actor_page_align 里，是因为 _sync_actor_info_columns
        # 末尾的 grid.invalidate()+activate() 会把它们重新弹回右缘——本方法排在它
        # 之后，才不会被覆盖（还原态则完全交给通用同步，本方法一个像素都不碰）。
        for name in self._ACTOR_PAGE_A2_TARGETS:
            w = getattr(ui, name, None)
            if w is None or w.parentWidget() is None:
                continue
            dx = anchor_x - left_x(w)
            g = w.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > w.parentWidget().width():
                continue  # 越出父级：保持通用逻辑给出的位置
            if dx:
                w.setGeometry(nx, g.y(), g.width(), g.height())

        # ③「刮削结束后自动创建头像」（kodi）未进 registry，通用同步不会自愈，必须跟着
        # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在下面 hl96 循环
        # **之后**：量到的是 miss 移动后的新 x。
        # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在 ② 的 hl96 循环
        # **之后**：量到的是 miss 移动后的新 x。
        for row_name, holder_name, target_name, lead_name, widen in self._ACTOR_PAGE_A2_ROWS:
            row = getattr(ui, row_name, None)
            holder = getattr(ui, holder_name, None)
            target = getattr(ui, target_name, None)
            lead = getattr(ui, lead_name, None)
            if row is None or holder is None or target is None or lead is None:
                continue
            if row.parentWidget() is not holder or target.parentWidget() is not holder:
                continue
            tidx = row.indexOf(target)
            lidx = row.indexOf(lead)
            if tidx < 0 or lidx < 0 or lidx >= tidx:
                continue
            if widen:
                # 容器是固定宽绝对定位件：先按「两等分项各占一半」加宽，再钉住两半。
                dx, dy, _, dh = self._ACTOR_PAGE_HOLDER12_DESIGN
                target_rel = anchor_x - holder.mapTo(content, holder.rect().topLeft()).x()
                width = 2 * target_rel + row.spacing()
                if width <= self._ACTOR_PAGE_HOLDER12_DESIGN[2]:
                    # 死区（外宽 ~1054~1400）：容器已够宽，不加宽、直接按下收窄
                    # 前导项；目标已在锚点左侧时仍跳过（交给通用逻辑）。
                    if left_x(target) <= anchor_x:
                        continue
                else:
                    self._actor_wide_restores.append(("geometry", holder, holder.geometry()))
                    holder.setGeometry(dx, dy, width, dh)
                    grid = getattr(ui, "gridLayout_14", None)
                    if grid is not None:
                        grid.invalidate()
                        grid.activate()
            row.invalidate()
            row.activate()
            # 前导项钉到「让目标的左缘正好落在锚点上」的宽度
            between = sum(
                row.itemAt(i).widget().width() for i in range(lidx + 1, tidx) if row.itemAt(i).widget() is not None
            )
            need_w = anchor_x - left_x(lead) - row.spacing() * (tidx - lidx) - between
            if need_w < self._ACTOR_PAGE_A2_MIN_LEAD_W:
                continue  # 会把前导项自己的文字挤没：宁可不移
            # 余量必须全部交给目标之后的尾部项，否则 Qt 会摊回头一项、钉窄失效
            lock_stretch(row, tidx)
            lock_width(lead, need_w)
            row.invalidate()
            row.activate()
        kodi = getattr(ui, "checkBox_actor_photo_kodi", None)
        miss = getattr(ui, "radioButton_actor_photo_miss", None)
        if kodi is not None and miss is not None and kodi.parentWidget() is not None:
            # kodi 按自己的残差一步到位（可左可右）：死区里 miss 落位后残差恒为 0，
            # 沿用 miss 的 dx 会永远跳过；两者基线本就同 x，各自对准 A2 才是严格对齐。
            # miss 被守卫拦下时也不再连带 kodi——kodi 只看自己的位置。
            dxk = anchor_x - left_x(kodi)
            kg = kodi.geometry()
            kx = kg.x() + dxk
            if dxk != 0 and 0 <= kx and kx + kg.width() <= kodi.parentWidget().width():
                kodi.setGeometry(kx, kg.y(), kg.width(), kg.height())
        # ④ 最大化态：最下方「开始补全」按钮(pushButton_add_actor_pic_kodi)宽度与
        # 上方「开始补全」按钮(pushButton_add_actor_pic)一致，上方按钮自身不动；
        # 最小化时本方法首步清干净即 return，按钮宽保持设计值 50。
        # 注意：上面的 kodi 是复选框 checkBox_actor_photo_kodi，此处是同名后缀的按钮。
        ref_btn = getattr(ui, "pushButton_add_actor_pic", None)
        kodi_btn = getattr(ui, "pushButton_add_actor_pic_kodi", None)
        if kodi_btn is not None and ref_btn is not None and kodi_btn.parentWidget() is not None:
            target_w = ref_btn.width()
            if target_w > 0 and kodi_btn.width() != target_w:
                if 0 <= kodi_btn.x() and kodi_btn.x() + target_w <= kodi_btn.parentWidget().width():
                    # 绝对定位件只锁 min/max 还原时不会自动缩回（无布局驱动），故连同
                    # 几何一起登记，窄态 _clear_actor_wide_align 逆序写回即复原 130。
                    self._actor_wide_restores.append(("geometry", kodi_btn, kodi_btn.geometry()))
                    lock_width(kodi_btn, target_w)
                    kg2 = kodi_btn.geometry()
                    kodi_btn.setGeometry(kg2.x(), kg2.y(), target_w, kg2.height())
        # ⑤ 最大化态：「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘。实测两者
        # 右缘差在宽态恒为 20px（1920 1559 vs 1579 / 1600 1239 vs 1259 / 1366 1005 vs
        # 1025 / 1100 739 vs 759），窄态为 -7px，故只在本方法（宽态）里补这段右移，
        # 最小化态一个像素都不碰。
        # 只平移不改宽度：需求说的是「右侧向右移动」，而两者设计宽本就不同
        # （171 vs 110），拉宽会把「清除所有.actors文件夹」的按钮撑成另一种长相。
        # 目标是 groupBox_68 内 _DOCK_RIGHT 绝对定位项，通用宽幅同步每遍都按
        # design_x + extra 钉回，故与 ① 同款 setGeometry 即天然幂等、窄态往返自愈，
        # 不必登记 _actor_wide_restores（与 _ACTOR_PAGE_A2_TARGETS 同理）。
        del_btn = getattr(ui, self._ACTOR_PAGE_DEL_BTN, None)
        sel_btn = getattr(ui, self._ACTOR_PAGE_SEL_BTN, None)
        if (
            del_btn is not None
            and sel_btn is not None
            and del_btn.parentWidget() is not None
            and sel_btn.parentWidget() is not None
        ):
            dx = left_x(sel_btn) + sel_btn.width() - left_x(del_btn) - del_btn.width()
            g = del_btn.geometry()
            nx = g.x() + dx
            if dx and 0 <= nx and nx + g.width() <= del_btn.parentWidget().width():
                del_btn.setGeometry(nx, g.y(), g.width(), g.height())
        # ⑥ 最大化态：「网络头像库：」显示输入框钉成与「Gfriends 本地仓库：」「本地
        # 头像库：」两行显示输入框同宽（上下对齐）。它在 layoutWidget_8 网格里是直接项、
        # 右侧无按钮，宽态独占整列富余宽；另两枚右缘被 Fixed 110px 的「选择目录」按钮
        # 顶住，故差出一枚按钮宽。钉宽是唯一手段（它不进任何 registry，通用宽幅同步
        # 只按设计宽拉伸它的父容器，不会碰它自身的宽，故钉住的宽不会被抹掉）；
        # 格子比控件宽时 Qt 把控件排在格子左缘，左缘本就与另两枚同列（A1），
        # 钉宽后右缘也相等。窄态第一步清干净即 return，一个像素都不碰——
        # 窄态里同一枚输入框由 _sync_actor_page_narrow_align 末尾第 ⑤ 步负责
        # （最小化时右缘要向左缩进对齐，成因与手法完全相同）。
        net = getattr(ui, self._ACTOR_PAGE_NET_PATH_EDIT, None)
        ref = getattr(ui, self._ACTOR_PAGE_PATH_REF_EDIT, None)
        net_grid = getattr(ui, "layoutWidget_8", None)
        if (
            net is not None
            and ref is not None
            and net_grid is not None
            and net_grid.layout() is not None
            and net.parentWidget() is net_grid
            and ref.parentWidget() is not None
        ):
            grid8 = net_grid.layout()
            grid8.invalidate()
            grid8.activate()  # 先落定，才能量到参照输入框的终态宽
            want_w = ref.width()
            if 0 < want_w < net.width() and want_w >= net.minimumWidth():
                lock_width(net, want_w)
                grid8.invalidate()
                grid8.activate()
                # 读回纠偏：布局重排后若有 1px 级取整误差，用实测差补回去
                drift = net.width() - want_w
                if drift:
                    lock_width(net, want_w - drift)
                    grid8.invalidate()
                    grid8.activate()

    def _clear_actor_info_spacers(self) -> None:
        """清掉 _sync_actor_info_columns 注入的间隔项与宽度锁（每遍同步先清后建，故幂等）。

        宽度锁必须一并解除：钉位时给控件 setFixedWidth 防 Minimum 策略被间隔挤瘦，
        还原态若不解锁，控件就永久钉在宽态的宽/窄上（演员数据库路径输入框尤其明显）。
        """
        for w, width in self._actor_info_width_locks:
            if w is not None:
                w.setFixedWidth(width)
                w.updateGeometry()
        self._actor_info_width_locks = []
        for obj, saved, _kind in self._actor_info_margin_restores:
            if obj is None:
                continue
            if isinstance(saved, int):
                obj.setSpacing(saved)
            else:
                obj.setContentsMargins(saved)
        self._actor_info_margin_restores = []
        for row, spacer in self._actor_info_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._actor_info_spacers = []

    def _sync_actor_page_wide_hooks(self, actor_scroll=None) -> None:
        """演员页宽幅拉伸后的四拍对齐（顺序敏感，勿调换）。

        ① _sync_actor_page_align：把「清除所有.actors 文件夹」对到 checkBox_actor_photo_ne_new
           （请求 Graphis 最新图片），把两个「自动补全演员头像」对到 A2 列。
        ② _sync_actor_info_columns：演员信息组三列对齐，它的 A3 锚点正是同一个
           checkBox_actor_photo_ne_new，必须在 ① 之后量才不会读到过期 x。
        ③ _sync_actor_page_wide_a2_align：最大化态把「Jellyfin」「本地头像库」「仅缺少
           头像的演员」等对到 A2 列（使用 Graphis 头像），并把「清除所有.actors 文件夹」
           右缘对到「选择目录」按钮右缘（需求③，也是宽态专属）。排在 ② 之后是**必须的**：
           ② 末尾 grid.invalidate()+activate() 会把 _DOCK_RIGHT 的绝对定位项重新
           钉回右缘（design_x + extra），把 ① 刚对好的两个「自动补全演员头像」弹回
           去（实测被弹回 1348）。
        ④ _sync_actor_page_narrow_align：窄态把「仅缺少信息的演员」「仅缺少头像
           的演员」「本地头像库」右移到「补全完成后自动补全演员头像」那一列上——
           必须在 ② 之后，因为它要量的正是 ② 顺带定下的那两个单选的当前 x。
        """
        self._sync_actor_page_align(actor_scroll)
        self._sync_actor_info_columns(actor_scroll)
        self._sync_actor_page_wide_a2_align(actor_scroll)
        self._sync_actor_page_narrow_align(actor_scroll)

    def _sync_actor_info_columns(self, actor_scroll=None) -> None:
        """演员信息组：行标签冒号对齐 + 各行左缘对齐到 Graphis 列 + 路径框宽度铺排。

        锚点是 groupBox_41（头像组）三个 Graphis 复选框的左缘，运行时 mapTo 实测：
          A1 = 使用Graphis背景、A2 = 使用Graphis头像、A3 = 请求Graphis最新图片。
        窄态(1000) 实测 A1 = 186，与演员信息组 col1 起点同 x；宽态(1920) = 186/652/1119。
        「中文简体」自身恒在 col1 起点（= A1），故窄态用 A1 当基准与用户要求的
        「与中文简体严格上下对齐」完全等价。

        行标签冒号对齐（窄宽双态）：「补全语言：」「演员信息数据库：」与「补全范围：」
        的右缘严格一致。两标签是 Fixed 130 右对齐，只要 gridLayout_14 的 col0 从 x=0
        起算就自然成立——.ui 已给 col1 各行加尾部 Expanding spacer 把 col0 钉到最左。
        本方法把 col0 钉死 130px 下限：否则 QGridLayout 会把富余宽度摊给 col0
        （实测宽态 col0 长到 762、col1 起点被推到 818），col1 内的行起点右移。

        宽态（需求①、②）：
          ① 「使用数据库补全演员信息」「不存在中文时，翻译日语为中文」及其同排后续
             控件（点击下载链接 / 不勾选则无中文时使用日语）左缘对齐 A1；
             「中文简体」同在 A1，「中文繁体」A2、「日语」A3 不变。
          ② 「演员信息数据库：」路径输入框左缘扩到 A1、右缘缩到「选择目录」按钮左缘，
             「选择文件」按钮随之右移到该列，与下方两枚「选择目录」严格上下对齐
             （下方两枚自身位置不变）。窄态此行不动（窄态由需求⑨ 的钉宽负责）。
        窄态：「不存在中文时，翻译日语为中文」「使用数据库补全演员信息」
          及其同排后续控件左缘对齐 A1（即「中文简体」所在列）；「所有演员」同左移到
          A1；语言行「中文繁体」右移到 A2、「日语」右移到 A3（中文简体不动，
          A2/A3 锚点自身不动；行尾 Expanding 间隔吸收位移）。

        共同手法（col1 内的行受 QGridLayout 管理，对子控件 setGeometry 会在下次
        layout 激活时被覆盖，一律用 QSpacerItem 注入定位）：
          - 间隔宽度取「目标绝对 x − 控件当前实测绝对 x」，天然含自身宽度与 spacing，
            不会随同行控件增多而累积误差；
          - 钉位时无条件 setFixedWidth 锁住当宽：这些控件是 Minimum 策略，插入固定宽
            间隔后会被挤瘦（实测「所有演员」253→52），锁宽后同行控件各按设计宽排布；
          - 每次插完 invalidate+activate 让 Qt 重排，下一目标才量得到新位置；
          - 「补全范围：」行是绝对定位链路（frame_4 → layoutWidget_15 → hl101），与
            gridLayout_14 无关：容器左移到 x=136（= col1 起点）后「所有演员」自然落在
            A1；宽态再把容器拉宽到容得下 A2 并把「仅缺少信息的演员」钉到 A2。行内只剩
            两个 Fixed 宽单选+固定间隔时 QHBoxLayout 会把富余宽度摊到**行首**（凭空
            56px 空档），故尾部补一个 Expanding 间隔。
          - setColumnMinimumWidth/setColumnStretch 是**持久**设置，窄态也必须钉住
            col0=130，否则「先最大化再还原」窄态会被宽态的列宽污染。

        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _sync_actor_page_align docstring。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_64", None)
        grid = getattr(ui, "gridLayout_14", None)
        if box is None or grid is None or not box.isVisibleTo(self):
            return
        scope_holder = getattr(ui, "layoutWidget_15", None)
        content = box.parentWidget()
        if content is None:
            return

        wide = self._actor_page_stretch_extra() > 0
        # 先无条件清干净上一遍留下的间隔/宽度锁/缩进，再按当前态重建。窄态同样要走完
        # 重建流程（需求⑦ 窄态也要钉位），故不能在清理后提前 return。
        self._clear_actor_info_spacers()
        if wide and actor_scroll is not None and actor_scroll.isVisibleTo(self):
            actor_scroll.sync_wide_children_width()  # 取终态 extra，勿量过期几何

        # col0 钉 130 → col1 起点 = gridLayoutWidget_14.x + 130 + spacing = content 186。
        # 窄态本就如此（无富余宽度可摊），此调用幂等；宽态是必需。
        grid.setColumnMinimumWidth(0, self._ACTOR_INFO_LABEL_COL_W)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.invalidate()
        grid.activate()

        anchors = {}
        for key, name in (
            ("A1", self._ACTOR_INFO_A1_ANCHOR),
            ("A2", self._ACTOR_INFO_A2_ANCHOR),
            ("A3", self._ACTOR_INFO_A3_ANCHOR),
        ):
            anchor = getattr(ui, name, None)
            if anchor is None:
                return
            anchors[key] = anchor.mapTo(content, anchor.rect().topLeft()).x()

        def pin(row, name, target_x, width=None):
            """把 row 内 name 的左缘推到 target_x；锁宽后按实测差值插前导间隔。

            width 给定时同时把控件钉到该宽（「演员信息数据库：」输入框铺 A1→A2 用）。
            """
            w = getattr(ui, name, None)
            if w is None or w.parentWidget() is None:
                return
            idx = row.indexOf(w)
            if idx < 0:
                return
            row.invalidate()
            row.activate()  # 先落定，才能量到本控件的当前真实 x
            if not any(locked is w for locked, _ in self._actor_info_width_locks):
                self._actor_info_width_locks.append((w, w.width()))
                w.setFixedWidth(width if width is not None else w.width())
                row.invalidate()
                row.activate()
            need = target_x - w.mapTo(content, w.rect().topLeft()).x()
            if need <= 0:
                return  # 已在目标列或更右，无需再插间隔
            spacer = QSpacerItem(need, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._actor_info_spacers.append((row, spacer))
            row.invalidate()
            row.activate()  # 让下一目标量到插入后的新位置

        # 受控行的前导缩进必须先清零，行起点才等于 col1 起点（A1）——间隔只能右推、
        # 不能左拉。缩进来自「父布局 spacing + 行首占位控件」，见常量注释。
        # 只动 spacing 与 leftMargin，不整组重设 contentsMargins：后者会连带清掉
        # right/bottom，在 QHBoxLayout 里改动过多边距曾导致渲染期崩溃。
        for parent_name, spacing, lead_widget in self._ACTOR_INFO_ROW_LEAD_INDENT:
            parent = getattr(ui, parent_name, None)
            if parent is None or parent.parentWidget() is None:
                continue
            if parent.spacing() != spacing:
                self._actor_info_margin_restores.append((parent, parent.spacing(), None))
                parent.setSpacing(spacing)
            if lead_widget:
                head = getattr(ui, lead_widget, None)
                if head is not None and head.width() > 0:
                    if not any(locked is head for locked, _ in self._actor_info_width_locks):
                        self._actor_info_width_locks.append((head, head.width()))
                        head.setFixedWidth(0)
            parent.invalidate()
            parent.activate()
        for child_name in self._ACTOR_INFO_ROW_ZERO_MARGIN:
            child = getattr(ui, child_name, None)
            if child is None:
                continue
            margins = child.contentsMargins()
            if margins.left() != 0:
                self._actor_info_margin_restores.append((child, margins, None))
                child.setContentsMargins(0, margins.top(), margins.right(), margins.bottom())
        grid.invalidate()
        grid.activate()

        # 各行左缘对齐：宽态与窄态用不同的目标列集合。
        targets = self._ACTOR_INFO_WIDE_TARGETS if wide else self._ACTOR_INFO_NARROW_TARGETS
        for layout_name, rows in targets.items():
            row = getattr(ui, layout_name, None)
            if row is None or row.parentWidget() is None:
                continue
            for name, key in rows:
                pin(row, name, anchors[key])

        # 宽态需求②：「演员信息数据库：」路径输入框左缘 A1、右缘缩到「选择目录」按钮列，
        # 「选择文件」随之右移，与下方两枚「选择目录」严格上下对齐（下方两枚自身不动）。
        # 宽度不写死：由「选择目录」按钮的实测左缘反推（含行内 spacing，故按钮恰好
        # 落在该列上），窗口任意宽度都成立；宽态三处 A1 恒等，无需插前导间隔。
        if wide:
            path_row = getattr(ui, "horizontalLayout_155", None)
            sel = getattr(ui, self._ACTOR_INFO_SEL_FOLDER_BTN, None)
            if (
                path_row is not None
                and path_row.parentWidget() is not None
                and sel is not None
                and sel.parentWidget() is not None
            ):
                sel_x = sel.mapTo(content, sel.rect().topLeft()).x()
                want_w = sel_x - path_row.spacing() - anchors["A1"]
                if want_w >= self._ACTOR_INFO_PATH_MIN_W:
                    pin(path_row, "lineEdit_actor_db_path", anchors["A1"], width=want_w)

        # 「补全范围：」行：绝对定位链路。容器左移到 col1 起点后「所有演员」落在 A1，
        # 宽态再拉宽容器并把「仅缺少信息的演员」钉到 A2。
        row = getattr(ui, "horizontalLayout_101", None)
        if row is None or scope_holder is None or row.parentWidget() is not scope_holder:
            return
        sx, sy, design_w, sh = self._ACTOR_INFO_SCOPE_HOLDER_DESIGN
        holder_w = design_w
        if wide:
            origin_x = scope_holder.mapTo(content, scope_holder.rect().topLeft()).x()
            holder_w = max(
                anchors["A2"] - origin_x + self._ACTOR_INFO_SCOPE_W[1] + self._ACTOR_INFO_SCOPE_PAD,
                design_w,
            )
        # 先把两个单选钉回设计宽（253/252），再决定容器宽：顺序不能反——容器一旦拉宽，
        # Minimum 策略的单选会跟着长到 366，钉位间隔就没空间了。
        for name, width in zip(self._ACTOR_INFO_SCOPE_ROW, self._ACTOR_INFO_SCOPE_W, strict=True):
            w = getattr(ui, name, None)
            if w is not None and not any(locked is w for locked, _ in self._actor_info_width_locks):
                self._actor_info_width_locks.append((w, w.width()))
                w.setFixedWidth(width)
                w.updateGeometry()
        scope_holder.setGeometry(self._ACTOR_INFO_SCOPE_WIDE_X, sy, holder_w, sh)
        grid.invalidate()
        grid.activate()
        row.invalidate()
        row.activate()
        if wide:
            # 尾部 Expanding 间隔：否则富余宽度摊到行首，两列整体偏 56px。
            tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            row.addItem(tail)
            self._actor_info_spacers.append((row, tail))
            row.invalidate()
            row.activate()
        pin(row, self._ACTOR_INFO_SCOPE_ROW[0], anchors["A1"])
        if wide:
            pin(row, self._ACTOR_INFO_SCOPE_ROW[1], anchors["A2"])
            # 死区/挤压回退：pin 的固定间隔只能右推。若目标仍在 A2 右侧（gap>0，
            # 死区里容器没被拉宽、pin 直接跳过；容器被 PAD 撑宽几个像素时 pin 也
            # 对不上），则收窄同行前导项补足（窄态同款手法，登记进本方法的
            # width_locks，单写入、无跨表污染；行尾 Expanding 间隔吸收腾出的宽度）。
            # 残差为 0（1920 等已对齐）或目标已在左侧时直接跳过。
            _lead = getattr(ui, self._ACTOR_INFO_SCOPE_ROW[0], None)
            _tgt = getattr(ui, self._ACTOR_INFO_SCOPE_ROW[1], None)
            if _lead is not None and _tgt is not None:
                row.invalidate()
                row.activate()
                # gap>0 表示目标在 A2 右侧差 gap：前导项收窄 gap 即落到 A2。
                _gap = _tgt.mapTo(content, _tgt.rect().topLeft()).x() - anchors["A2"]
                _want = _lead.width() - _gap
                if 0 < _gap and self._ACTOR_NARROW_MIN_LEAD_W <= _want < _lead.width():
                    if not any(locked is _lead for locked, _ in self._actor_info_width_locks):
                        self._actor_info_width_locks.append((_lead, _lead.width()))
                    _lead.setFixedWidth(_want)
                    _lead.updateGeometry()
                    row.invalidate()
                    row.activate()

    def _clear_actor_narrow_align(self) -> None:
        """清掉窄态右移对齐留下的间隔/钉宽/stretch（每遍同步先清后建，故幂等、往返自愈）。

        钉宽一律「记录原 min/max、原样写回」，不用 setFixedWidth(0) 真解锁：本方法跑在
        _sync_actor_info_columns 之后，而后者刚把 hl101 的两个单选钉在 253/252
        （_ACTOR_INFO_SCOPE_W），这里真解锁会顺手拆掉那一拍的锁、宽态铺排随即失准。
        对 hl96 记录到的本就是 (0, QWIDGETSIZE_MAX)，写回即真解锁，同一套代码两边都对。

        还原必须**逆序**（后记的先写回，最后写回的就是最早记下的那个原值）：同一控件
        在一趟里往往被钉两次（先钉设计宽、再钉让位后的收窄宽），正序还原会让中间值
        覆盖原值、把控件永久钉死在窄态的收窄宽上（实测 hl96 的「仅缺少头像的演员」
        窄态钉到 237 后再也回不去，宽态随之被带歪）。
        """
        for row, spacer in self._actor_narrow_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._actor_narrow_spacers = []
        for kind, obj, saved in reversed(self._actor_narrow_restores):
            if obj is None:
                continue
            if kind == "size":
                obj.setMinimumWidth(saved[0])
                obj.setMaximumWidth(saved[1])
                obj.updateGeometry()
            elif kind == "spacing":
                obj.setSpacing(saved)
            elif kind == "stretch":
                for i, value in enumerate(saved):
                    obj.setStretch(i, value)
            elif kind == "geometry":
                # 绝对定位件（如窄态收窄后的两个「开始补全」按钮）：只还原 min/max
                # 不会把宽度缩回去——没有布局驱动 resize，故连几何一并写回。
                obj.setGeometry(saved)
        self._actor_narrow_restores = []
        ui = getattr(self, "Ui", None)
        names = [row[0] for row in self._ACTOR_NARROW_SCOPE_ROWS] + [
            self._ACTOR_NARROW_SOURCE_ROW[0],
            self._ACTOR_NARROW_PATH_ROW[0],
        ]
        for name in names:
            row = getattr(ui, name, None)
            if row is None or row.parentWidget() is None:
                continue
            row.invalidate()
            row.activate()
        # ⑤ 钉宽的那枚「网络头像库」输入框在 layoutWidget_8 的网格里，解锁后必须让它
        # 重排一次，否则 net 仍停在窄态的钉宽上。注意 layoutWidget_8 本身是 QWidget
        # （QLayoutWidget），invalidate/activate 在它**布局**上而不是它身上。
        net_holder = getattr(ui, self._ACTOR_PAGE_NET_PATH_GRID, None)
        grid8 = None if net_holder is None else net_holder.layout()
        if grid8 is not None:
            grid8.invalidate()
            grid8.activate()

    def _sync_actor_page_narrow_align(self, actor_scroll=None) -> None:
        """演员页窄态（最小化/还原）：一组控件左移到 A2 列、另一组右移到各自锚点列。

        用户需求（四轮共七条）：
          「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」「刮削结束后自动
          创建」向左移动到与「使用Graphis头像」上下严格对齐；
          「仅缺少信息的演员」「仅缺少头像的演员」「Jellyfin」向左移动到与「使用
          Graphis头像」上下严格对齐；
          「本地头像库」与「点击下载头像包」向左移动到与「使用Graphis头像」上下严格
          对齐；
          「选择文件」右移到与「选择目录」上下对齐，「演员信息数据库」显示框右侧
          拓展到右移后的「选择文件」按钮左侧；
          「网络头像库」显示输入框最右侧向左缩进到与「Gfridends本地仓库」「本地头像库」
          两行显示输入框右缘上下严格对齐。
        锚点（checkBox_actor_photo_ne_face、「选择目录」按钮、「Gfridends本地仓库」
        「本地头像库」两行显示输入框）自身保持不动；最大化时的页面、布局、控件、
        提示词逐像素不变。

        A2 锚点是 checkBox_actor_photo_ne_face（使用 Graphis 头像），实际 x 运行时
        mapTo 实测。旧锚点 checkBox_actor_info_photo 已在上面「②」里被左移到 A2 列，
        故此处 a2_x == anchor_x，需求②的右移分支 need 恒为 0、自然整段跳过——保留是
        为了窗口再窄一点（A2 继续左移）时仍能正确工作。

        左移组：目标都是所在行的**尾项**，行内间隔只能增不能减，故唯一途径是让同行
        前导项收窄让位。四行三种让位手法：
          ① hl101/hl96/hl103（两个「所有演员」行 + 服务类型行）：收窄前导项后，行尾
             余量归谁要按尾项能不能涨分流——尾项能涨（minWidth<maxWidth 且带 GrowFlag，
             实测 maxWidth=16777215/minWidth=0）时余量本来就全归它、不要插手；尾项被
             _sync_actor_info_columns 钉死（minWidth==maxWidth==252）时吸不走余量，
             必须插一个 Expanding 行尾间隔把余量全吸走，否则前导项 253→164 又被摊回
             222、目标只走到 434 而非 356。曾对三行一律插间隔，实测会让可涨的两行尾项
             被压回 sizeHint（80px、文字截断），故按可涨性分流。
          ② hl95（layoutWidget_8 的来源行，「本地头像库」+「点击下载头像包」）：结构
             与①不同——目标是 Fixed 宽单选（min==max==59）吸不走余量、必须插间隔，
             而行尾 hl97 是嵌套子布局（内含「点击下载头像包」一枚 QLabel），插间隔会
             与它争余量、把链接文字夹没。改用「stretch 挪给行尾 + 前导项钉窄」：前导
             项钉死后不再参与分配，行尾吃满剩余宽度（只会变宽），目标左缘正好落在前导
             项右侧。曾试过直接钉住行尾那枚 QLabel 的现宽，副作用是 hl95 最小宽变化、
             把 layoutWidget_8 的三等分挤偏（A2 由 356 漂到 362），故不取。

        右移组：实际 x 一律运行时 mapTo 实测（不写死）。need <= 0（目标已在锚点右侧）
        一律不动：需求只说「向右移动」，间隔只能右推、不能左拉。共同点是「间隔只会被
        Qt 挤瘦、不会撑大」：QSpacerItem 的 minimumSize 是 (0,0)，行内需求超出可用宽
        时它第一个被压缩，实测 hl101 插 13px 间隔、目标只走了 6px。故每行都必须先给
        目标右侧腾出等量宽度，再插固定间隔：
          ③ hl101（frame_4/layoutWidget_15，「仅缺少信息的演员」）：容器宽恒为设计值
             511（每遍被 _sync_actor_info_columns 重设），加宽它会溢出组框右缘，故
             不动容器——把目标自身收窄 spacing+need（文字左对齐，视觉零变化），
             再在它前面插 need 宽的固定间隔。
          ④ hl96（frame_2/layoutWidget_12，「仅缺少头像的演员」）：容器同样恒 511，
             用 ③ 的手法。
          ⑤ hl95：容器是 gridLayout 的一整列、宽随窗口变，没有可收窄的固定容器，故把
             stretch 挪给行尾 hl97 再插固定间隔（与左移组②互斥，两者不会同时生效）。
             「点击下载头像包」右缘停在原处、只有左缘右移，其文字实测为左对齐（.ui 里
             写的是 RTL 方向的 Qt::AlignLeading|Qt::AlignLeft，实测 AlignLeft 生效）。
          ⑥ hl103（groupBox_43/gridLayoutWidget_25 的服务类型行，「Jellyfin」）：行宽
             随窗口变（col1 = 503/473/1393），两个单选是「均分可用宽」关系而非固定
             设计宽，故钉宽值取当前实宽（locks 里写 None）。可用宽必须取**行自身**
             的矩形宽而不是容器宽——容器 gridLayoutWidget_25 还有一整列给别的行
             （容器 639 / 行 503），取容器宽会把「Emby」推出 136px。
          ⑦ hl155（gridLayoutWidget_14 的路径行，「选择文件」）：这一行尾部本就有一个
             Expanding 间隔，故「路径框 + 按钮 + 间隔」恒等于行宽——把路径框钉到
             「选择目录」按钮左缘减去行间距，按钮即落到那一列。两者设计宽同为 110px，
             「与选择目录左缘对齐」和「右缘对齐」在这里是同一件事。路径框收窄到
             _ACTOR_NARROW_PATH_MIN_W 以下时宁可不右移。

        收窄组（本方法第 ⑤ 步，宽态第 ⑥ 步的镜像）：「网络头像库：」显示输入框钉成与
        「Gfridends本地仓库：」同宽。它是 layoutWidget_8 网格里的直系项、右侧没有按钮，
        故独占整列富余宽度，比另两枚宽出一整枚按钮的宽（1030 实测 503 vs 387）——
        用户看到的「最右侧超出」正是这个成因。三枚左缘本就同列，故钉宽即同时对齐左右缘。
        只收窄不撑宽（want >= net.minimumWidth() 才动手）；登记 _actor_narrow_restores，
        宽态第一步清干净即真解锁。

        每行处理完都实测回读一次并按差值修正（容器让位法与 stretch 让位法都只在 Qt
        「有富余就分给可拉伸项」的模型下才精确，回读修正使其不依赖该模型的细节）。
        状态登记在 _actor_narrow_spacers / _actor_narrow_restores，每遍同步先清后建，
        幂等且窄↔宽往返自愈；宽态第一步清干净即 return，最大化态一个像素都不碰。
        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _actor_page_align docstring。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_64", None)
        content = None if box is None else box.parentWidget()
        if box is None or content is None or not box.isVisibleTo(self):
            return
        self._clear_actor_narrow_align()
        if self._actor_page_stretch_extra() > 0:
            return  # 宽态：几何全部由通用宽幅同步 + _sync_actor_info_columns 产出
        # （注：曾尝试让三件套左移在宽态死区也跑，但窄/宽两套宽度锁会抢同一前导项，
        # 恢复链被污染（实测 emb 被压到 52px）。死区覆盖改由宽态方法各自向小拉伸量
        # 扩展，详见 _sync_actor_page_wide_a2_align 与 _sync_actor_info_columns。）

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        def set_fixed_width(w, width):
            """只改钉宽、不再登记原值——供回读修正用（登记由先前的 lock_width 负责）。"""
            w.setFixedWidth(width)
            w.updateGeometry()

        def lock_width(w, width):
            """把 w 钉到 width（width 为 None 表示钉到当前宽），并记下原 min/max 供还原。

            已是该宽则不重复登记：同一趟里对同一控件的二次调整走 set_fixed_width。
            """
            if w is None:
                return
            if width is None:
                width = w.width()
            if w.minimumWidth() == width and w.maximumWidth() == width:
                return
            self._actor_narrow_restores.append(("size", w, (w.minimumWidth(), w.maximumWidth())))
            set_fixed_width(w, width)

        def set_spacing(row, value):
            """只改行间距、不再登记原值——供回读修正用（登记由 lock_spacing 负责）。"""
            row.setSpacing(value)

        def lock_spacing(row, value):
            """把行间距改成 value，并记下原值供还原。"""
            if row.spacing() == value:
                return
            self._actor_narrow_restores.append(("spacing", row, row.spacing()))
            set_spacing(row, value)

        # 窄态新增①：上方两个「开始补全」收窄到与最下方「开始补全」同宽。
        # 设计态上方两枚是 181、最下方（pushButton_add_actor_pic_kodi）是 50；宽度实测
        # 取参照按钮当前实宽，不写死数值——宽态那枚被加宽过，窄态本方法跑到这里时
        # _sync_actor_page_wide_a2_align 已先行 _clear_actor_wide_align 把它复原成 50。
        # 两者都是各自 groupBox 的绝对定位件、无布局驱动，故除钉 min/max 外还须连几何
        # 一起登记（还原态只解锁 min/max 不会把宽度缩回去）。宽态本方法首步即 return，
        # 最大化时这三个按钮的尺寸一个像素都不碰。
        ref_btn = getattr(ui, "pushButton_add_actor_pic_kodi", None)
        target_btn_w = ref_btn.width() if ref_btn is not None else 0
        if target_btn_w > 0:
            for name in self._ACTOR_NARROW_ADD_BTN_TARGETS:
                w = getattr(ui, name, None)
                if w is None or w.parentWidget() is None or w.width() == target_btn_w:
                    continue
                g = w.geometry()
                if g.x() < 0 or g.x() + target_btn_w > w.parentWidget().width():
                    continue  # 收窄后越出父级：保持原状
                # 几何先记、钉宽后记：还原逆序写回时 size 先解锁、geometry 最后落定。
                self._actor_narrow_restores.append(("geometry", w, g))
                lock_width(w, target_btn_w)
                w.setGeometry(g.x(), g.y(), target_btn_w, g.height())

        # 窄态新增②：上一步收窄完成后，把「补全完成后自动补全演员头像」
        # 「刮削结束后自动补全演员头像」连同「刮削结束后自动创建头像」一起向左移动到与
        # 「使用Graphis头像」(A2 锚点) 严格上下对齐，锚点自身保持不动。
        # 三者都是绝对定位项、通用宽幅同步每遍都按 design_x + extra 重置它们，本方法的
        # 左移因此天然幂等（第二遍 dx=0）且宽↔窄往返自愈，不需要登记还原。
        # **必须排在下面 anchor_x 取样之前**：_ACTOR_NARROW_ANCHOR 正是
        # checkBox_actor_info_photo（「补全完成后自动补全演员头像」），它在本步被左移到
        # A2 列；后续各行按 anchor_x 右移时必须读到移动后的新 x，否则那批控件会停在
        # 旧锚点列、与锚点错开 102px（实测「仅缺少信息的演员」「Jellyfin」等随即失准）。
        a2 = getattr(ui, self._ACTOR_PAGE_A2_ANCHOR, None)
        a2_x = None if a2 is None else left_x(a2)
        if a2 is not None:
            for name in self._ACTOR_PAGE_A2_TARGETS + self._ACTOR_PAGE_MISS_TARGETS:
                w = getattr(ui, name, None)
                if w is None or w.parentWidget() is None:
                    continue
                try:
                    g = w.geometry()
                    dx = left_x(a2) - left_x(w)
                    nx = g.x() + dx
                except Exception:
                    continue
                # 只左移不右拉（需求只说「向左移动」）；越出父级则保持通用逻辑给出的位置
                if dx >= 0 or nx < 0 or nx + g.width() > w.parentWidget().width() or nx == g.x():
                    continue
                w.setGeometry(nx, g.y(), g.width(), g.height())

        anchor = getattr(ui, self._ACTOR_NARROW_ANCHOR, None)
        if anchor is None:
            return
        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()

        # 窄态新增③：「仅缺少信息的演员」「仅缺少头像的演员」也左移到 A2 列，与「使用Graphis
        # 头像」严格上下对齐（与上面②里的两个复选框同列，窄态就此与宽态一致）。
        # 手法：这枚单选是所在行的**尾项**，行内间隔只能增不能减，故左移的唯一途径是让同行
        # 前导项（两个「所有演员」）收窄让位——行内总需求随之变小，多出的富余全落在行尾空档
        # （这两行都没有 stretch 项），目标不会被顶回原处。
        # 只收窄绝不加宽（加宽前导项会把目标往右推）；收窄到下限仍够不到 A2 时整行放弃，
        # 宁可不动也不夹掉控件自己的文字。
        for row_name, target_name, lead_name, holder_name in self._ACTOR_NARROW_LEFT_PULL_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            lead = getattr(ui, lead_name, None)
            holder = getattr(ui, holder_name, None)
            if row is None or target is None or lead is None or holder is None or a2_x is None:
                continue
            if row.parentWidget() is not holder or lead.parentWidget() is not holder:
                continue
            row.invalidate()
            row.activate()  # 先落定，才能量到这一行当前的真实 x
            # 前导项该有的宽 = 现宽 + 目标还差的位移。写成位移差而不是
            # 「a2_x − 容器左缘 − spacing」：前者不依赖 margins/spacing/首项是否带
            # 固定宽（服务类型行那两个单选是「均分可用宽」关系，实测 503/503），后者
            # 在这类行上会算偏。
            want = lead.width() + (a2_x - left_x(target))
            if not self._ACTOR_NARROW_MIN_LEAD_W <= want < lead.width():
                continue  # 够不到 A2 / 已在 A2 列或更左（不得反向加宽）
            # 行尾余量归谁，要按尾项能不能涨分两种情况（目标控件本身就是行尾项）：
            #  - 尾项能涨（minWidth<maxWidth 且带 GrowFlag，如「仅缺少头像的演员」
            #    「Jellyfin」实测 maxWidth=16777215/minWidth=0）：余量本来就全归它，
            #    收窄前导项后它自动涨满整行、目标左缘正好落在 lead 右侧，不要插手。
            #  - 尾项被钉死（minWidth==maxWidth，如「仅缺少信息的演员」被
            #    _sync_actor_info_columns 钉在 252px）：它吸不走余量，收窄前导项腾出的
            #    空档会留在行内把目标顶回原处，必须插一个 Expanding 行尾间隔把余量全
            #    吸走（前导项 253→164 又被摊回 222、目标只走到 434 而非 356）。
            # 曾对三行一律插间隔，实测会让可涨的两行尾项被压回 sizeHint（80px、文字
            # 截断，要等下一拍同步才涨回来），故按可涨性分流。间隔登记进
            # _actor_narrow_spacers，_clear_actor_narrow_align 每遍先清后建、不叠加。
            if not (
                target.minimumWidth() < target.maximumWidth()
                and bool(target.sizePolicy().horizontalPolicy().value & self._SIZE_POLICY_GROW_FLAG)
            ):
                tail_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                row.addItem(tail_spacer)
                self._actor_narrow_spacers.append((row, tail_spacer))
            lock_width(lead, want)
            row.invalidate()
            row.activate()
            d = a2_x - left_x(target)
            if d:
                # 回读修正：前导项是 Fixed 宽、目标紧随其后，差多少补多少即可
                set_fixed_width(lead, max(self._ACTOR_NARROW_MIN_LEAD_W, want - d))
                row.invalidate()
                row.activate()

        # 窄态新增③之补：来源行 hl95 —— 「本地头像库」连同紧跟其后的「点击下载头像包」
        # 也左移到 A2 列（宽态由 _sync_actor_page_wide_a2_align 的 _ACTOR_PAGE_A2_ROWS
        # 里 hl95 那一行负责；窄态此前只有右移逻辑，目标一直停在 A2 列右侧数十像素处）。
        # 手法见 _ACTOR_NARROW_SOURCE_PULL 注释：stretch 挪给行尾 hl97 + 前导项钉窄，
        # 不插 Expanding 间隔（会与嵌套子布局争余量、夹掉「点击下载头像包」文字）。
        src_row_name, src_target_name, src_head_name, src_tail_name = self._ACTOR_NARROW_SOURCE_PULL
        src_row = getattr(ui, src_row_name, None)
        src_target = getattr(ui, src_target_name, None)
        src_head = getattr(ui, src_head_name, None)
        src_tail = getattr(ui, src_tail_name, None)
        if None not in (src_row, src_target, src_head, src_tail) and a2_x is not None:
            src_row.invalidate()
            src_row.activate()
            head_idx = src_row.indexOf(src_head)
            tail_idx = src_row.indexOf(src_tail)
            d = a2_x - left_x(src_target)
            want = src_head.width() + d
            # 只左移不右拉；收窄到下限仍够不到 A2 时整行放弃，宁可不动也不夹掉控件文字
            if head_idx >= 0 and tail_idx >= 0 and d < 0 and self._ACTOR_NARROW_MIN_LEAD_W <= want < src_head.width():
                self._actor_narrow_restores.append(
                    ("stretch", src_row, [src_row.stretch(i) for i in range(src_row.count())])
                )
                for i in range(src_row.count()):
                    src_row.setStretch(i, 1 if i == tail_idx else 0)
                lock_width(src_head, want)
                src_row.invalidate()
                src_row.activate()
                d = a2_x - left_x(src_target)
                if d:
                    # 回读修正：前导项钉死、目标紧随其后，差多少补多少即可
                    set_fixed_width(src_head, max(self._ACTOR_NARROW_MIN_LEAD_W, want + d))
                    src_row.invalidate()
                    src_row.activate()

        # ①② 两个「补全范围：」行：容器不动，靠「目标收窄 + 同行间距撑开」右移。
        # 上面③已把两行的目标对到 A2 列，这里 need 恒为 0、自然整段跳过——右移分支保留
        # 是为了窗口再窄一点（A2 列继续左移）时仍能正确工作。
        for row_name, target_name, holder_name, locks in self._ACTOR_NARROW_SCOPE_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            holder = getattr(ui, holder_name, None)
            if row is None or target is None or holder is None:
                continue
            if row.parentWidget() is not holder or target.parentWidget() is not holder:
                continue
            row.invalidate()
            row.activate()  # 先落定，才能量到本控件的当前真实 x
            need = anchor_x - left_x(target)
            if need <= 0:
                continue  # 已在锚点列或更右：需求只要求右移，不左拉
            for name, width in locks:
                lock_width(getattr(ui, name, None), width)
            idx = row.indexOf(target)
            count = row.count()
            if idx < 0 or count < 2:
                continue
            margins = row.contentsMargins()
            # 可用宽取「行自身被分到的矩形」而不是容器宽：前两行的行就是容器的唯一
            # 布局（行宽 == 容器宽 - margins），服务类型行的容器 gridLayoutWidget_25
            # 还有一整列给别的行（容器 639 / 行 503），取容器宽会把行首推出 136px。
            row_w = row.geometry().width()
            avail = (
                (row_w - margins.left() - margins.right())
                if row_w > 0
                else holder.width() - margins.left() - margins.right()
            )
            # 除目标外其余项的实宽（都已被上面钉成固定宽，不会在行内伸缩）
            others = sum(
                getattr(ui, name).width() for name, _ in locks if getattr(ui, name, None) not in (None, target)
            )
            base = row.spacing()
            # 目标让位量由「容器可用宽」反推，保证行内总需求恰好等于容器宽：
            # 有富余时 QHBoxLayout 会把富余摊到行首（实测凭空多出 6px 空档，行首控件
            # 整体右移），总需求一旦不等，行首的「所有演员」就会跟着漂。
            donor = avail - others - (base + need) * (count - 1)
            if donor < self._ACTOR_NARROW_MIN_DONOR_W:
                continue  # 让位会挤掉目标自己的文字：宁可不右移
            lock_width(target, donor)
            lock_spacing(row, base + need)
            row.invalidate()
            row.activate()
            d = anchor_x - left_x(target)
            # 回读修正：间距与让位量同步增减，行内总需求恒定，绝不会被挤瘦/摊到行首；
            # 修正后会让目标窄到夹住自己的文字则放弃（保持这一趟的近似值，下一遍再修）
            if d and donor - d >= self._ACTOR_NARROW_MIN_DONOR_W:
                set_fixed_width(target, donor - d)
                set_spacing(row, base + need + d)
                row.invalidate()
                row.activate()

        # ③ 来源行：stretch 让位法（详见 docstring）。
        # 收成闭包而非就地 early-return：③ 与 ④ 是两件独立的事，③ 不适用（need<=0，
        # 目标已在锚点列或更右）时必须继续跑 ④。此前这里是 `return`，一旦 ③ 不适用
        # 就把 ④ 整段跳过，「选择文件」再也对不到「选择目录」那一列。
        def _shift_source_row():
            row_name, target_name, head_name, tail_name = self._ACTOR_NARROW_SOURCE_ROW
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            head = getattr(ui, head_name, None)
            tail = getattr(ui, tail_name, None)
            if row is None or target is None or head is None or tail is None:
                return
            row.invalidate()
            row.activate()
            if anchor_x - left_x(target) <= 0:
                return  # 已在锚点列或更右：需求只要求右移，不左拉
            head_idx = row.indexOf(head)
            tail_idx = row.indexOf(tail)
            if head_idx < 0 or tail_idx < 0:
                return

            self._actor_narrow_restores.append(("stretch", row, [row.stretch(i) for i in range(row.count())]))
            for i in range(row.count()):
                row.setStretch(i, 1 if i == tail_idx else 0)
            row.invalidate()
            row.activate()
            # 前导项已收窄让回了一部分，按实测差值补足（富余全在行尾 hl97，间隔不会被挤瘦）
            idx = row.indexOf(target)
            if idx < 0:
                return
            spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._actor_narrow_spacers.append((row, spacer))
            row.invalidate()
            row.activate()
            lead = anchor_x - left_x(target)
            for _ in range(3):
                d = anchor_x - left_x(target)
                if not d:
                    break
                lead = max(0, lead + d)
                spacer.changeSize(lead, 0)
                row.invalidate()
                row.activate()

        _shift_source_row()

        # ④ 「演员信息数据库：」行：路径框右缘撑到「选择文件」左缘，按钮即落到
        # 「选择目录」那一列。该行尾部本就有一个 Expanding 间隔，故行内总需求恒等于
        # 行宽时按钮右缘正好等于 col1 右缘——与「选择目录」按钮同宽（110px 设计），
        # 「左右缘对齐」在这里是同一件事。
        # 同样收成闭包：④ 有多处提前 return，就地 return 会把 ⑤ 整段跳过。
        def _shift_actor_db_path_row():
            row_name, path_name, btn_name, ref_name = self._ACTOR_NARROW_PATH_ROW
            row = getattr(ui, row_name, None)
            path = getattr(ui, path_name, None)
            btn = getattr(ui, btn_name, None)
            ref = getattr(ui, ref_name, None)
            if row is None or path is None or btn is None or ref is None:
                return
            row.invalidate()
            row.activate()
            if row.indexOf(btn) < 0 or row.indexOf(path) < 0 or ref.parentWidget() is None:
                return
            want = left_x(ref) - row.spacing() - left_x(path)
            if want < self._ACTOR_NARROW_PATH_MIN_W:
                return  # 会把路径框压到夹不住文字：宁可不右移
            lock_width(path, want)
            row.invalidate()
            row.activate()
            d = left_x(ref) - left_x(btn)
            if d:
                # 回读修正：路径框是 Fixed 宽、按钮紧随其后，差多少补多少即可
                set_fixed_width(path, want - d)
                row.invalidate()
                row.activate()

        _shift_actor_db_path_row()

        # ⑤ 最小化态：「网络头像库：」显示输入框右缘向左缩进到与「Gfriends 本地
        # 仓库：」「本地头像库：」两行显示输入框右缘上下严格对齐；那两枚（连同
        # 「选择目录」按钮）自身保持不动，最大化态一个像素都不碰。
        # 与宽态第 ⑥ 步（_sync_actor_page_wide_a2_align 末尾）同一手法、同一对控件：
        # 「网络头像库」行的输入框是 layoutWidget_8 网格里的直接项，右侧没有按钮，
        # 于是独占整列富余宽度，比另两枚宽出整整一枚按钮的宽（1030 实测 503 vs
        # 387，右缘 689 vs 573；1000 实测 473 vs 357）——这正是「最右侧超出」的成因。
        # 三枚左缘本就同列（A1 恒 186），故钉宽成参照枚的宽即同时满足左右缘对齐。
        # 只在窄态跑：lock_width 登记进 _actor_narrow_restores，宽态第一步
        # _clear_actor_narrow_align 即把 min/max 原样写回（真解锁，见该方法 docstring），
        # 而宽态自身的钉宽由 _sync_actor_page_wide_a2_align 第 ⑥ 步独立负责。
        net = getattr(ui, self._ACTOR_PAGE_NET_PATH_EDIT, None)
        ref_edit = getattr(ui, self._ACTOR_PAGE_PATH_REF_EDIT, None)
        net_holder = getattr(ui, "layoutWidget_8", None)
        if (
            net is not None
            and ref_edit is not None
            and net_holder is not None
            and net_holder.layout() is not None
            and net.parentWidget() is net_holder
            and ref_edit.parentWidget() is not None
        ):
            grid8 = net_holder.layout()
            grid8.invalidate()
            grid8.activate()  # 先落定，才能量到参照输入框的终态宽
            want = ref_edit.width()
            # 参照宽必须还容得下最小宽（MDCx.ui 给的是 300）才收；已经在该宽或更宽
            # （窗口更窄时另两枚的「选择目录」行反而更挤）一律不碰，避免反向撑大。
            if 0 < want < net.width() and want >= net.minimumWidth():
                lock_width(net, want)
                grid8.invalidate()
                grid8.activate()
                # 回读纠偏：布局重排后若有 1px 级取整误差，用实测差补回去
                drift = net.width() - want
                if drift:
                    lock_width(net, want - drift)
                    grid8.invalidate()
                    grid8.activate()
