"""左侧 dock 栏(导航按钮 + 状态栏)与捐赠区的布局。纯 Qt, 不依赖任何业务模块。"""

import traceback

from PyQt6.QtCore import (
    QRect,
    Qt,
)
from PyQt6.QtGui import (
    QCursor,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
)

from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.signals import signal_qt
from mdcx.views.donate_window import DonateDialog


class DockLayoutMixin:
    # ============ 左侧导航坞（widget_setting）自适应（议题 #86/#102/#181）============
    # .ui 里侧栏是绝对定位：widget_buttons(0,50,210,390) 内 layoutWidget6(0,0,211,380)
    # 由 QVBoxLayout(spacing 8) 竖排 8 个 40px 导航按钮（8*40+7*8=376），下方
    # label_show_version(0,489,210,201) 是底对齐状态区（正常模式/配置文件名/版本号/
    # 点击检查最新版本），label_local_number(0,680,21,21) 是左下角数字浮标。
    # 设计态整列需 50+390+49+201+40(底距)=730 高；界面缩放很大时（用户 175% 反馈：
    # 可用逻辑分辨率仅 1097x594，窗口高 ~500）贴底公式 min(..., height-201) 会把状态区
    # 顶进导航区 → 状态文字压在「检测网络/使用说明」按钮上（叠字，见 _sync_dock_layout）。
    _DOCK_NAV_BTNS = (
        "pushButton_main",
        "pushButton_log",
        "pushButton_tool",
        "pushButton_emby_manager_nav",
        "pushButton_nfo_library",
        "pushButton_setting",
        "pushButton_net",
        "pushButton_about",
    )
    _DOCK_NAV_BTN_H = 40  # 导航按钮设计高（.ui setMaximumHeight(…, 40)）
    _DOCK_NAV_BTN_H_MIN = 36  # 压缩下限：border-width 9px×2 + 14px 字号仍能显示文字
    _DOCK_NAV_SPACING = 8  # verticalLayout 设计间距
    _DOCK_NAV_SPACING_MIN = 2  # 压缩下限（再小按钮会粘连）
    # widget_buttons 容器高。8 个导航按钮的内容高 8*40 + 7*8 = 376，容器只留这么多：
    # 原设计值 390 多出的 14px 是纯余量（layoutWidget6 的 QVBoxLayout 把富余空间堆在
    # 末尾，**不影响按钮落位**，见 _layout_dock_nav），收掉后二维码白得 14px 预算。
    # 这 14px 正是「状态文字固定预留 5 行 + 二维码恒 180px」能在**默认窗高 700**
    # 同时成立的关键：700 高下 5 行预留(75) + 间距(16) + 链接(22) + 内距(4) + 二维码(180)
    # = 297，加导航底 20+376=396 共 693 ≤ 700，还余 7px；若容器仍高 390（导航底 410）
    # 则需 707 > 700，缺口会把导航整个上移 7px（用户反馈的「整体向上移动」）。
    # 注：曾为「让下方收款码满宽」把按钮/间距收紧到 38/4、容器收到 340，用户反馈后已
    # 撤回——满宽不是必需的，收款码按固定边长摆放即可（见 _layout_donate）。
    _DOCK_NAV_H = 376
    # 导航区顶边的两个取值，与 _windows_auto_adjust 里的 widget_buttons.move(0, 50/20)
    # 必须一致——那条 move 只在启动/标题栏设置变更时跑一次，_sync_dock_layout 随后会
    # 读 .y() 把它当基线。写成常量而不是读 .y()：_layout_dock_nav 结尾会
    # setGeometry(0, top, …) 把读回来的值又写回去，若基线来自自身就会被逐次抬高。
    _DOCK_NAV_TOP_HIDE = 50  # 隐藏窗口标题栏（window_title == "hide"）
    _DOCK_NAV_TOP_SHOW = 20  # 显示窗口标题栏
    # 导航区可上移到离窗顶多近。用户原话「软件界面容器上方还有10px以上的空间」——
    # 即要求二维码显示不满时把导航整体上移利用这段空间，但**不能顶到 0**（留 10px，
    # 否则第一个按钮贴着窗口边框、圆角与阴影会被切）。
    _DOCK_NAV_TOP_MIN = 10
    _DOCK_STATUS_H = 201  # label_show_version 设计高
    _DOCK_STATUS_H_MIN = 72  # 状态区压缩下限（13px 字号约 4 行，超出裁上方空行）
    _DOCK_STATUS_GAP = 12  # 导航底与状态区顶的最小间距
    # 状态区底（= 状态矩形底 = 窗底）距窗底的预留。原为 40（议题 #102：贴底太靠下），
    # 但 label_show_version 是 AlignBottom 的——文字只占矩形底部约 3~4 行，矩形底与
    # 文字底之间那 40px 全是死区，用户截图里「读取模式·字段优先 / actor.json / MDCx
    # 版本号 / 点击检查最新版本」四行整体悬在窗底上方、下面空一截。改为 0。
    # 顺带把二维码的高度预算也放宽 40px（见 _layout_donate 的 one_size 公式），
    # 这是「二维码保持 180px」能稳定成立的关键——原先默认窗高下预算只有 177。
    # 第十五轮起它只决定「窗底这条基准线在哪」：赞助块顶锚导航底后，富余高度全部落
    # 在块与这条线之间（用户要的就是这个），0 = 基准线就是窗底、富余最多。
    # 注：置 0 后 _DOCK_STATUS_Y_MIN 在公式里被 min(..., height-_DOCK_STATUS_H) 覆盖
    # （min(max(x, 489), x) ≡ x），该下限对「空间够」分支不再生效，仅矮窗分支仍用。
    _DOCK_STATUS_BOTTOM_PAD = 0  # 状态区底与窗底之间的预留（0 = 基准线就是窗底）
    _DOCK_STATUS_Y_MIN = 489  # 状态区不低于设计 y
    _DOCK_LOCAL_Y_MIN = 680  # label_local_number 不低于设计 y
    _DOCK_LOCAL_H = 21  # label_local_number 设计高
    # 状态文字块高（_dock_status_text_h）的上次测量值，-1 = 从未测量。作「行数是否变了」
    # 的闸门：show_scrape_info 在刮削过程中按**文件**刷新同一行进度文案（可达上千次），
    # 不设闸门就会每个文件重排一次左侧导航 + 收款码（见 _resync_dock_status_layout）。
    _dock_status_text_h_last = -1
    # region 侧栏「使用说明」下方的微信收款码 + [赞助作者] 链接
    _DONATE_LINK_FONT_PX = 16  # 文档用：字号实际由 style.py 的 QSS 决定，此处仅备查
    # 16px 的 fontMetrics().height() = 19，行高 22 留 3px 余量；_DONATE_LINK_H 须 ≥ 它
    _DONATE_LINK_H = 22
    # 以下三个间距按「默认窗口 1030x700 下二维码尽量大」倒推得出（用户第 10 轮要求）。
    # 第十五轮把块改成顶锚后，预算公式改写为（真实运行：nav_top 20、_DOCK_NAV_H 376
    # → nav_bottom 396、5 行预留**真实** 85）：
    #   one_size = 窗底 − (nav_bottom + _DONATE_TOP_GAP) − LINK_GAP − LINK_H − TEXT_GAP − 预留
    # 原值 TEXT_GAP 17 / LINK_GAP 6 / PAD 6 时 one_size 只有 155，二维码被卡在 155。
    # 第十三轮收到 10 / 2 / 2（预留按 lineSpacing 估成 75，gap = 10+LIFT 6 = 16，
    # 合计与本轮的 6+85 = 91 **完全相等**），第十五轮只是把「估错的 10px」从预留挪进
    # 间距，总消耗 117 不变，故 one_size = height − 513 与各档门槛逐值保持不变。
    _DONATE_LINK_GAP = 2  # 二维码与 [赞助作者] 的间距
    # [赞助作者] 底边 → 状态文字首行的间距。**第十五轮由 10 改成 6**。
    # 旧值 10 是在「状态文字块高按 lineSpacing×(行数−1)+height 估」的前提下定的，
    # 而真实运行里状态文字每行都带 emoji（🎉/💠/🛠/🐰/🔍），Qt 回退字体的**真实行距是
    # 17px 而不是 lineSpacing 的 15px**，5 行实测 85px 而非估出来的 75px——低估的 10px
    # 全被这段 10px 的间距吃掉，于是用户截图里「[赞助作者]」与文字只剩 6px、且第 5 行
    # 「🔍 点击检查最新版」被窗底裁掉半个字高（见 _dock_status_text_reserve_h 的探针）。
    # 现在间距按「实测够用」取 6：既保证不叠字，又让 **≥693 时二维码仍恒为 180**（预算
    # 守恒，见 _DONATE_QR_SIZE 处 one_size = height − 513）。
    # 原 _DONATE_LIFT（6，「赞助块整体上移量」）随本轮改动**整体删除**：赞助块改为**顶锚**
    # 在导航底（见 _layout_donate），已经顶到能顶的最高处，再谈「上移多少」没有意义，
    # 那 6px 如今就是下面这个间距。
    _DONATE_TEXT_GAP = 6  # [赞助作者] 底边到状态文字首行的间距
    # 最大化时支付宝码与微信码之间的间距：取「一行汉字的高度」，即侧栏 [赞助作者]
    # 的行高（_DONATE_LINK_H / _DONATE_LINK_FONT_PX=16 实测 fontMetrics().height()=19、
    # 行高约 22），使两码之间的视觉分隔与正文行距统一（用户第 14 轮要求）。
    # 独立于 _DONATE_PAD：后者是色块与导航/状态文字的内边距，收窄它是为了把高度
    # 全留给二维码；两码之间的间距是给用户看的分隔，要「疏」不要「紧」。
    _DONATE_ALIPAY_GAP = 22
    # 与导航区/状态区的内边距。第十五轮起其只在**底锚（最大化）**路径的净高
    # 公式（avail = qr_bottom − PAD − nav_bottom）与「[赞助作者]→状态文字」
    # 间距下限护栏里用；顶锚档的「导航底 → 块顶」间距由 _DONATE_TOP_GAP 控制
    # （保持最大化布局逐像素不变）。
    _DONATE_PAD = 0  # 底锚档净高护栏/间距下限专用，顶锚不再用它
    # 非最大化（顶锚）时「使用说明按钮底 → 二维码顶」的间距。
    # 与导航按钮间距等高：软件设置→检测网络之间即 _DOCK_NAV_SPACING = 8，
    # 故此处同样取 8；二维码与 [赞助作者] 间距仍是 2px（_DONATE_LINK_GAP 不变）；
    # 最大化（底锚）布局不动，故独立成常量、不改 _DONATE_PAD。
    _DONATE_TOP_GAP = 8
    # **底锚（最大化）时**状态文字带底边离窗底预留的高度——沿用旧版议题 #102 的
    # `_DOCK_STATUS_BOTTOM_PAD = 40`。
    # 第十六轮实测（100% 字号、最大化 1040 高、读取完成后 5 行文字）：
    #   MDCx-20261007（底锚）：支付宝 509 / 微信 711 / [赞助作者] 893 / 文字 925..1000
    #   本轮实现（底锚）    ：支付宝 503 / 微信 705 / [赞助作者] 887 / 文字 915..1000
    # 差 6px（旧版文字块高按 lineSpacing 估成 75 而真实 85，这 10px 差值恰好补掉大半）。
    # 为什么不给 0（贴着窗底）：用户要的是「**和旧版一样的高度**」，旧版窗底就留 40px，
    # 给 0 反而比旧版再低 40px、观感与截图 001 不符。
    # 为什么不给全局恢复 `_DOCK_STATUS_BOTTOM_PAD = 40`：那个值参与分支①的 status_y
    # 公式，会把 `one_size` 砍掉 40 → 默认窗高 700 立刻放不满 180，违反
    # 「等于或高于699时收款码高度恒为180px」。故只在底锚路径里用。
    _DONATE_BOTTOM_SLACK = 20
    # 二维码边长**设计值 180**：侧栏宽 210，两侧各留 15px 空白（210 - 2*15 = 180）。
    # 用户诉求（第十三轮，原话「固定！固定！固定！」）：「微信与支付宝二维码要在任何情况下
    # 都不会放大或缩小或向上移动或向下移动」「把两个二维码图片高度都改回180px，固定」，
    # 并补充「窗高低于 699（100% 字号）时还是将收款码缩小，等于或高于699时收款码高度
    # 恒为180px」。故本常量是**上限**，取值规则为：
    #   · 可用高度 ≥ 180 → **恒为 180**（不放大、不缩小、不随窗口高度变化）；
    #   · 可用高度 < 180  → 按可用高度等比缩小（用户明确要求「还是将收款码缩小」）；
    #   · 缩小到 _DONATE_QR_MIN 以下 → 整块隐藏（40px 的码已无法辨识，叠字/糊码更糟）。
    # 高度预算（真实运行：nav_top 20、_DOCK_NAV_H 376 → nav_bottom 396、5 行预留 **85**）：
    #   one_size = 窗底 − 块顶(nav_bottom + _DONATE_TOP_GAP 8) − LINK_GAP 2 − LINK_H 22 − gap 6 − 预留 85
    #           = height − 396 − 123 = height − 519
    # （块顶 = nav_bottom + _DONATE_TOP_GAP(8)；_DONATE_TOP_GAP 与导航按钮间距
    #   _DOCK_NAV_SPACING 等高，即软件设置→检测网络的间距。）
    # 与第十三轮算出的 `height − 513` 差 6px（使用说明→二维码由 2px 放到 8px，
    # 多占的 6px 即此差值）。所以：
    #   · 默认窗高 700 起余 1px、≥699 二维码恒 180，且**读取前后完全相同**；
    #   · 低于 699 先由 _sync_dock_layout 把导航上移（最多 _DOCK_NAV_TOP_MIN=10，即用户
    #     授权的「上方还有 10px 以上的空间」）补 10px，即 689 及以上仍能补到 180；
    #     689 以下按剩余高度缩小、549 以下整块隐藏。
    # 变的只有**富余高度落在哪里**，而这一点**按窗口状态分两种锚法**（第十六轮）：
    #   · 非最大化 → **顶锚**在导航底，富余全落块**下方**。于是「二维码 → [赞助作者] →
    #     五行状态字」整体上移到能到的最高处（用户第十五轮：「允许向上移动多少px就向上
    #     移动多少px，移动到最大允许的高度px值」）。本式 one_size = height − 519 即此档。
    #   · 最大化 → **底锚**在窗底，富余全堆在块**上方**（旧版 MDCx-20261007 的锚法）。
    #     用户第十六轮：「最大化时…向上移动太多太多了，最大化时向下移动一些，改成和
    #     MDCx-20261007 中最大化时一样的高度，最小化时…均保持不变」。此档预算见
    #     _DONATE_BOTTOM_SLACK。
    # 两种锚法都只用**固定量**定位，故第十三轮「读取/刮削不动」的不变量在两档都成立。
    _DONATE_QR_SIZE = 180
    # 二维码**缩小的下限**：低于此边长直接隐藏整块收款码（军规③：宁可不显示也不叠字）。
    # 与「边长设计值」无关——满 180 时绝不使用本常量。
    _DONATE_QR_MIN = 40
    # 状态文字块的**预留行数**（定位专用，与当前文字行数无关）。
    # 用户诉求：「读取或刮削模式下读取或刮削前二维码位置、软件界面、软件日志、软件工具、
    # 演员管理、信息管理、软件设置、检测网络、使用说明位置都保持固定」。旧实现按实测
    # 行数定位，读取完成时 show_scrape_info 在文字**顶部**追加一行「🎉 刮削完成 N/N」，
    # 文字块长高一行 → 码块上移一行 + 可用高度少一行 → 二维码缩小、导航被上移
    # （实测 100% 字号 700 高：导航 20→13、二维码 416→405）。改用固定预留行数后，
    # 读取前后算出的几何逐值相同。
    # 5 行 = 真实运行读取完成后的最大常见行数（进度行 + 模式 + 文件 + 版本 + 检查更新）。
    # **预留高度不等于 lineSpacing×(5−1)+height**：这五行每行都带 emoji，Qt 回退字体的
    # 真实行距是 17px 而 lineSpacing 只报 15px，5 行真实 85px、公式只有 75px。少算的
    # 10px 全被间距吃掉 → 用户截图里「[赞助作者]」与文字只剩 6px、第 5 行「🔍 点击检查
    # 最新版」被窗底裁掉半个字高。故预留高度由 `_dock_status_text_reserve_h()` 用
    # 「5 个 emoji 的真实排版」探针量出来（见该方法）。
    # 超出预留（单文件模式 + 软链接 + 进度行 = 7 行，真实 119px）时 _layout_donate
    # 改按实测行数判叠字、必要时隐藏收款码（宁可不显示也不叠字，军规③）。
    _DONATE_STATUS_RESERVE_LINES = 5
    # 探针用矩形的宽度：只要求「一行放得下一个 emoji、不发生软换行」，取 4096 远超需要。
    # 刻意不用侧栏真实宽度 210——那样 boundingRect 会按 210 折行，行数算错（实测
    # `"\n"×5` 在 100000 宽下得 90，而真实渲染只有 85，正是折行把行高算多了）。
    _DONATE_TEXT_PROBE_W = 4096
    # 最大化时在微信码**上方**再加一张支付宝码（宽度与微信码严格一致）。
    # 判据仍是「**两张都放得下完整 _DONATE_QR_SIZE 才显示**」（宁可少一张，也绝不因多
    # 一张码而缩小微信码）；窗高偏矮时微信码自己会缩小，但那只影响微信码，**不因此
    # 把支付宝码也塞进来**。_DONATE_ALIPAY_MIN 仅作控件占位初值。
    _DONATE_ALIPAY_MIN = 90  # 支付宝码占位初值（满尺寸时边长恒为 _DONATE_QR_SIZE）
    _DONATE_LINK_COLOR = "#0078D7"  # 与「赞助作者」页 [赞助作者] 链接同色
    _DONATE_LINK_COLOR_DARK = "#4DA6FF"  # 暗黑模式提亮，保证可读

    def _init_donate_widgets(self) -> None:
        """在侧栏挂「微信收款码 + [赞助作者]」两个控件（运行时注入，不改 .ui）。

        .ui/MDCx.py 由 pyuic6 生成且有同步测试，故侧栏新增控件走运行时注入：
        挂到 widget_setting 下并 raise_ 到 left_backgroud_widget 之上。
        位置/显隐由 _layout_donate 随窗口高度自适应（见 _sync_dock_layout）。
        """
        ui = self.Ui
        parent = ui.widget_setting
        qr = QLabel(parent=parent)
        qr.setObjectName("label_donate_qr")
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 先按设计边长 _DONATE_QR_SIZE 占位（用户要求「等于或高于693时高度恒为180px」），
        # 首帧由 _layout_donate 按实际可用高度摆位后再显示；窗口偏矮时它会缩小
        qr.setFixedSize(self._DONATE_QR_SIZE, self._DONATE_QR_SIZE)
        qr.setToolTip(" 微信扫码赞助 ")
        qr.hide()  # 位置/尺寸由 _layout_donate 摆好后再显示，避免首帧错位
        link = QLabel(parent=parent)
        link.setObjectName("label_donate_link")
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setFixedHeight(self._DONATE_LINK_H)
        link.setOpenExternalLinks(False)
        link.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        link.setToolTip(" 点击查看赞助方式 ")
        link.linkActivated.connect(lambda _url: self.show_donate_dialog())
        link.hide()
        # 支付宝码：只在最大化且两张都放得下 _DONATE_QR_SIZE 时显示（见 _layout_donate），
        # 宽度与微信码严格一致
        alipay = QLabel(parent=parent)
        alipay.setObjectName("label_donate_alipay")
        alipay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alipay.setFixedSize(self._DONATE_ALIPAY_MIN, self._DONATE_ALIPAY_MIN)
        alipay.setToolTip(" 支付宝扫码赞助 ")
        alipay.hide()
        ui.label_donate_qr = qr
        ui.label_donate_link = link
        ui.label_donate_alipay = alipay
        self._donate_qr_cache = QPixmap()
        self._donate_qr_cache_size = 0
        self._donate_alipay_cache = QPixmap()
        self._donate_alipay_cache_size = 0
        qr.raise_()
        alipay.raise_()
        link.raise_()
        self._style_donate_link()

    def _style_donate_link(self) -> None:
        """[赞助作者] 富文本链接：颜色亮色 #0078D7 / 暗黑提亮。

        字号不在这里写——style.py 的 `QLabel#label_donate_link{font-size:14px}` 与
        导航按钮同一套 QSS 机制（QLabel.setFont 会被样式表覆盖而失效，只有 QSS
        或富文本内联 font-size 起作用），避免两处字号各自漂移。
        """
        link = getattr(self.Ui, "label_donate_link", None)
        if link is None:
            return
        color = self._DONATE_LINK_COLOR_DARK if self.dark_mode else self._DONATE_LINK_COLOR
        link.setText(f'<a href="#donate" style="color:{color}; text-decoration:none;">[赞助作者]</a>')

    def show_donate_dialog(self) -> None:
        """弹出赞助窗口（收款码 + 新人榜/土豪榜）。"""
        try:
            dialog = DonateDialog(self)
            dialog.exec()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    def _hide_donate(self) -> None:
        """空间完全不够时隐藏收款码（极矮窗口，导航独占整列）。"""
        for name in ("label_donate_qr", "label_donate_link", "label_donate_alipay"):
            widget = getattr(self.Ui, name, None)
            if widget is not None:
                widget.setVisible(False)

    def _dock_status_text_h(self) -> int:
        """状态区（正常模式·字段优先 / 配置文件 / 版本号 / 点击检查）文字块的**估算**高度。

        label_show_version 的对齐方式随赞助块模式切换（底对齐 ↔ 顶对齐，见 `_layout_donate`），
        故这里**不用于定位**，只作两件事：
          ① 「行数变了没有」的闸门键（`_resync_dock_status_layout`）——`show_scrape_info` 在
             刮削过程中按**文件**刷新同一行进度文案（一次批量可达上千次），不设闸门就会
             每个文件重排一次左侧导航 + 收款码；
          ② 极矮窗口下判断状态区还能不能留 `_DOCK_STATUS_H_MIN`（见 `_sync_dock_layout`）。
        公式是**估算**：真实运行每行都带 emoji、真实行距 17px 而 lineSpacing 只报 15px，
        故它会**低估**（100% 字号 5 行估 75、真实 85）。凡是需要「准」的地方一律用
        `_dock_status_text_probe_h`（真实排版探针）或 `_dock_status_text_reserve_h`。

        历史（本函数曾是定位的唯一来源，也就是用户反馈的「读取后整体上移」根因）：
        第十三轮前 `_layout_donate` 用这里的实测值锚定二维码下沿，于是读取完成时
        `show_scrape_info` 在顶部追加的「🎉 刮削完成 N/N」把整块上移一行、还把二维码
        缩小、把导航上移（实测 700 高：导航 20→13、二维码 416→405）。定位已全面改用
        固定预留（见 `_dock_status_text_reserve_h`）。
        """
        label = self.Ui.label_show_version
        fm = label.fontMetrics()
        text = label.text()
        breaks = text.count("\n") + text.count("<br>")
        # show_scrape_info 的文本以换行开头（f"\n{scrape_info}..."），那一行是空的、
        # 只在块顶部留白而无墨迹。label 是底对齐的，这行空白不移动末行，故要扣掉，
        # 否则间距会整整多出一个行高（实测 15px）。
        stripped = text.lstrip("\n\r")
        breaks -= text[: len(text) - len(stripped)].count("\n")
        return fm.lineSpacing() * breaks + fm.height()

    def _dock_status_text_probe_h(self, text: str) -> int:
        """按 `text` 的**真实排版**量出文字块高度（离屏探针，非估算）。

        为什么不能拿 `lineSpacing × (行数−1) + height` 顶替：真实运行的状态文字每一行
        都以 emoji 开头（🎉/💠/🛠/🐰/🔍），Qt 对这些码位回退到 emoji 字体，而**回退字体的
        行距比 `fontMetrics().lineSpacing()` 报的值大 2px**。实测 100% 字号 Consolas：
        `lineSpacing()=15 / height()=15`，但 `QLabel.sizeHint().height()` 逐行实测
        1行17 / 2行34 / 3行51 / 4行68 / **5行85** / 6行102 / 7行119 —— 即真实行距 17。
        公式估出的 5 行 75 整整少 10px，这就是用户截图里末行被窗底裁掉的直接原因。

        `boundingRect(宽矩形, TextExpandTabs, text)` 会走真实的字体回退与行距，实测对
        5 个 emoji 得 85，与 `sizeHint()` 的真实渲染**逐值相符**；对纯 ASCII/CJK 则给出
        15/行（正确，那些字形没有回退）。宽度必须够大（`_DONATE_TEXT_PROBE_W`），否则
        boundingRect 会按给定宽度折行、把行高算多（实测 `"\n"×5` 得 90 ≠ 85）。

        `<br>` 会被 Qt 当软换行渲染（`show_scrape_info` 的文案里有），但对纯文本探针而言
        只是普通字符，故先换成 `\n` 再量。行首那个空行（`show_scrape_info` 的文本以 `\n`
        开头）同样先剥掉——它只在块顶留白、无墨迹，且底/顶对齐都不受它影响。
        """
        probe = text.replace("<br>", "\n").lstrip("\n\r")
        if not probe:
            return 0
        fm = self.Ui.label_show_version.fontMetrics()
        return fm.boundingRect(
            QRect(0, 0, self._DONATE_TEXT_PROBE_W, 0),
            Qt.TextFlag.TextExpandTabs,
            probe,
        ).height()

    def _dock_status_text_reserve_h(self) -> int:
        """状态文字块的**预留**高度：固定行数 × 真实行距，与当前文字行数无关。

        收款码块整条链的下沿恒定挂在「块顶 + 预留高 + 间距」处（见 `_layout_donate`），
        于是读取/刮削时状态文字多一行或少一行，**二维码、`[赞助作者]`、导航按钮、状态矩形
        一个像素都不会动**（用户原话：「我需要的是读取或刮削前…位置都保持固定！注意是固定！
        固定！固定！」）。行数取 `_DONATE_STATUS_RESERVE_LINES`（5，覆盖真实运行读取完成
        后的「进度行 + 模式 + 文件 + 版本 + 检查更新」）。文字实际比预留还高时（单文件模式
        + 软链接 + 进度行可达 7 行），`_layout_donate` 用 `_dock_status_text_probe_h` 量出的
        真实高度判叠字、必要时隐藏收款码（军规③）——**这一步只影响显隐、不移动任何控件**。

        高度由 `_dock_status_text_probe_h` 对 `RESERVE_LINES` 个 emoji 量出（100% 字号实测
        85px），**不用 lineSpacing 公式**（那只得 75px，见该方法 docstring）。字号/主题
        变化时两者同步变化，不会出现「预留比实际还小」的错配。
        """
        lines = 6 if self._donate_bottom_anchor() else self._DONATE_STATUS_RESERVE_LINES
        return self._dock_status_text_probe_h("\n".join(["\U0001f389"] * lines))

    def _dock_status_text_real_h(self) -> int:
        """状态文字**当前文本**的真实渲染高度（`_dock_status_text_probe_h` 的实例用法）。

        只用于一处判断：`_layout_donate` 里「预留带装不装得下当前文字」——装不下就隐藏
        整块收款码，把高度全让给状态文字（宁可不显示也不裁字，军规③）。**不参与定位**，
        故文字增删行不会移动任何控件。
        """
        return self._dock_status_text_probe_h(self.Ui.label_show_version.text())

    def _resync_dock_status_layout(self) -> None:
        """状态文字**行数变了**之后重排贴底区，避免新增的行被收款码块盖住。

        回归背景（用户截图，读取模式）：首次读取完成后 `show_scrape_info` 往
        `label_show_version` **顶部**追加一行「🎉 刮削完成 7/7」。旧实现里收款码块是按
        **旧行数**摆好的（`_layout_donate` 用实测文字高锚定二维码下沿），于是两者叠字，
        **最大化再最小化一下就恢复正常**。如今定位已改用固定预留（行数变化不再移动任何
        控件），这里保留重排是为了让「文字超出预留行数」时能重新判一次叠字并隐藏收款码。

        用文字块高做闸门：行数没变就不动。`show_scrape_info` 在刮削过程中按文件调用
        （`scraper.py: 已刮削 {count}/{count_all}`），不设闸门会每个文件重排一次
        左侧导航 + 收款码。
        """
        if getattr(self, "Ui", None) is None:
            return
        text_h = self._dock_status_text_h()
        if text_h == self._dock_status_text_h_last:
            return
        self._dock_status_text_h_last = text_h
        self._sync_dock_layout()

    def set_dock_status_text(self, text: str) -> None:
        """`label_show_version` 的唯一入口：写文本 + 行数变了就重排贴底区。

        原先 `init.py` 把 `label_show_version` 信号直接连到 `QLabel.setText`，文本变了
        没人重排，新行就被收款码块盖住（见 `_resync_dock_status_layout`）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        ui.label_show_version.setText(text)
        self._resync_dock_status_layout()

    def _donate_bottom_anchor(self) -> bool:
        """赞助块是否用**底锚**（整块挂窗底）——仅最大化/全屏时为真（第十六轮）。

        用户原话（附 001/002 两张最大化截图，001 是 MDCx-20261007 编译出来的效果）：
        「最大化时向下移动一些，改成和 MDCx-20261007 中最大化时一样的高度，最小化时软件
        界面布局、组件、控件、提示词等等均保持不变」。

        第十五轮把整块改成**顶锚**导航底，在**任何**窗态都生效；最大化时富余高度有几百
        像素，块被顶到导航区正下方，状态文字一路跟着上移（实测 1040 高：文字 955→608，
        **上移 347px**），与旧版截图差 109~130px，用户反馈「向上移动太多太多了」。

        实测两版几何（100% 字号、最大化 1040 高、读取完成后 5 行文字；探针
        `C:\\Users\\ZhouHan\\AppData\\Local\\Temp\\opencode\\probe_ref.py` 直接跑旧源码得到）：
            MDCx-20261007（底锚）：支付宝 509 / 微信 711 / [赞助作者] 893 / 文字 925..1000
            第十五轮顶锚版        ：支付宝 398 / 微信 600 / [赞助作者] 782 / 文字 810..895
        故最大化改回底锚（`_DONATE_BOTTOM_SLACK` 把差值收到 6px），非最大化保持顶锚不变。

        全屏与最大化同义（支付宝码门控同理），故一并判。
        """
        return self.isMaximized() or self.isFullScreen()

    def _layout_donate(self, nav_bottom: int, status_y: int, status_h: int) -> tuple[int, int, int]:
        """在导航区与状态区之间安放收款码，返回校正后的 (status_y, status_h, qr_deficit)。

        ## 定位：**按窗口状态二选一**锚法（第十六轮）

        两种锚法摆的都是同一条链 `[支付宝码(仅最大化)] → 微信码 → [赞助作者] → 状态文字
        预留带`，唯一区别是「富余高度落在块的哪一侧」——这正是第十五/十六两轮来回调整的
        那个变量。

        **① 非最大化 → 顶锚**（第十五轮，用户原话「最小化时在不压缩二维码180px的高度、
        不遮盖[赞助作者]、刮削完成 7/7的字体的前提下将…整体向上移动，允许向上移动多少px
        就向上移动多少px，移动到最大允许的高度px值」）：
            group_top = nav_bottom + _DONATE_TOP_GAP
            qr_top    = group_top（支付宝码显示时微信码顺延到支付宝码下方）
            link_top  = qr_top + qr_size + _DONATE_LINK_GAP
            text_top  = link_top + _DONATE_LINK_H + gap
            块底      = text_top + reserve_h
            one_size  = 窗底 − group_top − (LINK_GAP + LINK_H + gap + reserve_h) = height − 519
        富余高度全部落在块**下方**；`qr_top` 只由 `nav_bottom` 决定，故 700/741/800/900/1080
        各档高度下二维码**同一个像素都不差**（这比第十三轮「读取/刮削不动」的承诺更强）。

        **② 最大化 → 底锚**（第十六轮，用户原话「最大化时二维码图片、赞助作者、刮削完成
        7/7…向上移动太多太多了，最大化时向下移动一些，改成和 MDCx-20261007 中最大化时
        一样的高度」）：
            text_top  = status_bottom − _DONATE_BOTTOM_SLACK − reserve_h
            link_top  = text_top − gap − _DONATE_LINK_H
            qr_bottom = link_top − _DONATE_LINK_GAP
            qr_top    = qr_bottom − qr_size       （支付宝码再往**上**顺延）
            one_size  = qr_bottom − _DONATE_PAD − nav_bottom = height − 553
        富余高度全部落在块**上方**（导航区与支付宝码之间留白），与 MDCx-20261007 的锚法
        一致（实测差 6px，见 `_DONATE_BOTTOM_SLACK`）。

        两种锚法都**只用固定量**定位（`status_bottom`、`nav_bottom`、`reserve_h`、`gap`…），
        与状态文字当前几行无关，故第十三轮「读取/刮削不动」的不变量在两档都成立。
        本轮起例外：块顶为「nav_bottom + _DONATE_TOP_GAP(8)」，即使用说明→二维码
        取与软件设置→检测网络等高的导航按钮间距（_DOCK_NAV_SPACING）；最大化一侧不动。

        ## 不变量：定位与文字行数无关

        预留高用 `_dock_status_text_reserve_h()`（固定 5 行的**真实**高度，100% 字号实测
        85px），**不用** `_dock_status_text_h()`（估算，见其 docstring）。第十三轮前正是用
        那个估算值锚定，于是读取完成时 `show_scrape_info` 在顶部追加的「🎉 刮削完成 N/N」
        让整块上移一行、二维码缩小、缺口又把导航上移（实测 700 高：导航 20→13、
        二维码 416→405，用户截图逐条对上）。

        ## 边长规则（两档同）

        可用高度 ≥ `_DONATE_QR_SIZE` 时 `qr_size ≡ _DONATE_QR_SIZE`；不足时按可用高度等比
        **缩小**（用户第十三轮：「窗高低于 699（100% 字号）时还是将收款码缩小，等于或
        高于699时收款码高度恒为180px」）；缩到 `_DONATE_QR_MIN` 以下才整块隐藏。缩小量
        同样只由固定量算出，故「读取前后边长一致」这条不变量对缩小档也成立。

        ## 最大化时上方多一张支付宝码

        **只在两张码都能保持完整 _DONATE_QR_SIZE 时才显示**（判据**不用** qr_size）。
        放不下就**只显示微信码**，绝不因为多一张码而缩小微信码（旧实现在「放得下但需要缩」
        这一档把微信码缩到 two_size，实测最大化 h=800 时只有 114×114）。两码之间留
        `_DONATE_ALIPAY_GAP`，支付宝码在微信码**上方**、同宽同列；非最大化一律不显示。
        两档锚法下微信码都在支付宝码**下方**（顶锚时顺延、底锚时上提），最大化往返会让
        微信码移动一段距离，这是用户钦定的锚法差异，不是漂移（边长始终 180 不变）。

        ## 返回二维码缺口

        第三个值是「还差多少像素才能满 180」（顶锚档还要算上「状态区下限」护栏的让出量
        `status_short`，真实运行为 0；底锚档状态矩形高恒为 `reserve_h`，缩小二维码不牵连
        它，故不含该项）。调用方 `_sync_dock_layout` 用它把导航区整体上移来补（见那里的
        两遍布局），故本函数保持纯计算、不自行挪导航——挪多少是布局策略问题。缺口只由
        固定量算出，故「上移多少」对同一窗口高度是常量：读取前与读取后完全一致。
        """
        ui = self.Ui
        status = ui.label_show_version
        qr = getattr(ui, "label_donate_qr", None)
        link = getattr(ui, "label_donate_link", None)
        alipay = getattr(ui, "label_donate_alipay", None)
        if qr is None or link is None or alipay is None:
            # 收款码控件还没建好（_init_donate_widgets 未跑）：无从谈缺口，返回 0 表示
            # 「不欠尺寸」，调用方据此不会去上移导航。**必须返回三元组**——签名是三元，
            # 少一个会让 _sync_dock_layout 的解包直接 ValueError。
            return status_y, status_h, 0
        side_w = ui.widget_setting.width()
        status_bottom = status_y + status_h  # 窗底（分支①②里都等于 self.height()）
        reserve_h = self._dock_status_text_reserve_h()  # 固定 5 行的真实高度
        # 「[赞助作者] → 状态文字」间距：不得小于「状态区压缩下限」反推出来的值，否则
        # 预留带顶到状态区顶之上会把左下角文字裁掉（军规③）。
        gap = max(
            self._DONATE_TEXT_GAP,
            self._DOCK_STATUS_H_MIN + self._DONATE_PAD - reserve_h,
        )
        # 「状态区下限」护栏的让出量：只在**顶锚**档参与——那一档的状态矩形高是
        # `one_size + reserve_h − qr_size`（缩小多少就把状态区压矮多少），极端小字号下
        # 预留带撑不到 `_DOCK_STATUS_H_MIN` 时必须再让出这段，否则状态区会比文字还矮、
        # 末行被窗底裁，正是议题 #181 的原始回归。真实运行（100% 字号）`reserve_h` = 85
        # > 72，这道护栏恒不生效（`status_h ≡ reserve_h`）。
        status_short = max(0, self._DOCK_STATUS_H_MIN - reserve_h)
        # 锚法：最大化 → 底锚（第十六轮，与 MDCx-20261007 一致）；其余 → 顶锚（第十五轮）。
        bottom_anchor = self._donate_bottom_anchor()
        # 注意：下面两条分支都用 `donate_y` 这个**局部**量推导位置，直到确认要显示才写回
        # `status_y`。否则隐藏分支会返回「新的 y + 调用方给的旧 h」这种拼接值，把状态矩形
        # 整体上移 `_DONATE_BOTTOM_SLACK + reserve_h`（实测 520 高时底边从 520 缩到 507，
        # 数字浮标也跟着上移）。
        if bottom_anchor:
            # ── 底锚：自窗底往上摆 ────────────────────────────────────────────────
            # 文字带底边离窗底留 `_DONATE_BOTTOM_SLACK`（旧版 _DOCK_STATUS_BOTTOM_PAD 的
            # 值，见该常量注释），于是文字带顶只由 status_bottom 与固定量决定。
            donate_y = status_bottom - self._DONATE_BOTTOM_SLACK - reserve_h
            link_bottom = donate_y - gap
            link_top = link_bottom - self._DONATE_LINK_H
            qr_bottom = link_top - self._DONATE_LINK_GAP
            # 微信码顶不得低于 nav_bottom + PAD ⇒ 码下沿固定、可用量即这条净高。
            # 底锚档状态矩形恒为 reserve_h，缩二维码不牵连它，故 `status_short` 不参与。
            avail = qr_bottom - self._DONATE_PAD - nav_bottom
            qr_size = min(self._DONATE_QR_SIZE, avail)
            qr_deficit = max(0, self._DONATE_QR_SIZE - avail)  # 交给调用方上移导航补
        else:
            # ── 顶锚：自导航底往下摆 ────────────────────────────────────────────────
            # 块顶：顶锚导航底，再留 _DONATE_TOP_GAP 的顶间距（能有多高就多高，见 docstring）。
            group_top = nav_bottom + self._DONATE_TOP_GAP
            # 二维码之外的全部固定占用（码下 → 窗底）：链接间距 + 链接高 + 间距 + 预留带。
            fixed_below = self._DONATE_LINK_GAP + self._DONATE_LINK_H + gap + reserve_h
            # 微信码可用高度 = 窗底 − 块顶 − 固定占用；只由固定量算出，与文字行数无关。
            one_size = status_bottom - group_top - fixed_below
            avail = one_size - status_short
            qr_size = min(self._DONATE_QR_SIZE, avail)
            # 缺口含 `status_short`：上移 1px 只让边长长 1px，故要让边长补满 180 就得多
            # 上移这么多；漏掉它会让上移上来的像素被护栏吃掉、边长卡在平台期（实测 176）。
            qr_deficit = max(0, self._DONATE_QR_SIZE - avail)
        # 边长规则（两档同）：可用高度够就**恒为 _DONATE_QR_SIZE**（绝不放大、也绝不因
        # 窗口拉高而变大），不够才按可用高度等比缩小。
        # 缩小到 _DONATE_QR_MIN 以下已无法辨识（甚至可能为负），整块隐藏（军规③：
        # 宁可不显示也不糊码/不叠字）。这里返回缺口而不是直接收工：调用方还有第二遍
        # 布局（上移导航后重排），那一遍若补齐了空间就按 180 显示；补不齐则本分支再次隐藏。
        # 此时返回**调用方原样传入**的 (status_y, status_h)：块藏起来后状态矩形回到设计
        # 贴底带、恢复底对齐（见 `_hide_donate` 处的对齐切换），不该留半截新几何。
        if qr_size < self._DONATE_QR_MIN:
            self._hide_donate()
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return status_y, status_h, qr_deficit
        # 支付宝码在微信码**上方**、同宽同列，且**只在最大化时**出现（用户钦定）。
        # 要两张都是完整 _DONATE_QR_SIZE，块内净高得够放 2×QR_SIZE + ALIPAY_GAP（判据成立
        # 时 avail ≥ 382，故 qr_size 必然已经是 180，两码不会一边满一边缩）。
        # 宁可少一张码，也不让「微信码已缩小」把支付宝码也带出来（旧实现在「放得下但需要
        # 缩」这一档把两张一起缩到 two_size，实测最大化 h=800 时只有 114×114）。
        show_alipay = bottom_anchor and (avail - self._DONATE_ALIPAY_GAP) >= 2 * self._DONATE_QR_SIZE
        if bottom_anchor:
            # 微信码下沿固定在 qr_bottom，支付宝码在其**上方** ALIPAY_GAP 处
            qr_top = qr_bottom - qr_size
            alipay_top = qr_top - qr_size - self._DONATE_ALIPAY_GAP if show_alipay else None
            donate_h = reserve_h
        else:
            alipay_top = None
            qr_top = group_top
            link_top = qr_top + qr_size + self._DONATE_LINK_GAP
            link_bottom = link_top + self._DONATE_LINK_H
            # 顶锚档的状态矩形顶 = 链接底 + gap（与底锚档 `link_bottom = donate_y - gap`
            # 对称；调用方注释亦记为 `status_y = link_bottom + gap`）。漏掉这 6px，
            # 状态矩形就会向上吞掉预留给 gap 的空间：预算里为 gap 留了高度，
            # 实际却以 0 间距贴住链接，`_DONATE_TEXT_GAP` 在顶锚路径形同虚设。
            donate_y = link_bottom + gap
            donate_h = max(0, status_bottom - donate_y)
        status_y, status_h = donate_y, donate_h
        # 状态文字**顶对齐**在自己的预留带里。这一步是「不移动」的关键：底对齐时每多一行
        # 文字整个块就上移一行（用户第十三轮的回归）；顶对齐后新增的行往**下**长进预留带的
        # 富余里，首行原地不动。底锚档矩形就是预留带那一段（高恒为 reserve_h）。
        # 文字实际比预留还高（单文件模式 + 软链接 + 进度行可达 7 行）会撑出预留带、被窗底
        # 裁掉——此时宁可不显示收款码也不裁字（军规③）。
        # 注意它**只影响显隐、不影响位置**：行数变化绝不移动任何控件。
        # 顶锚档的护栏保证了 `status_h >= min(reserve_h, _DOCK_STATUS_H_MIN)`，故这条判据
        # 实际只看「几行字 vs 预留几行」，与窗口高度无关。
        if self._dock_status_text_real_h() > status_h + 20:
            self._hide_donate()
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return status_y, status_h, qr_deficit
        status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        qr_x = (side_w - qr_size) // 2
        qr.setFixedSize(qr_size, qr_size)
        qr.move(qr_x, qr_top)
        if alipay_top is not None:
            # 支付宝码与微信码同宽同列，排在微信码上方 _DONATE_ALIPAY_GAP（一行汉字高）处
            alipay.setFixedSize(qr_size, qr_size)
            alipay.move(qr_x, alipay_top)
            if self._donate_alipay_cache_size != qr_size:
                source = QPixmap(resources.donate_alipay_icon)
                if source.isNull():
                    self._donate_alipay_cache = QPixmap()
                    self._donate_alipay_cache_size = qr_size
                    alipay.setText("二维码\n加载失败")
                else:
                    self._donate_alipay_cache = source.scaled(
                        qr_size,
                        qr_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._donate_alipay_cache_size = qr_size
                    alipay.setText("")
            if not self._donate_alipay_cache.isNull():
                alipay.setPixmap(self._donate_alipay_cache)
            alipay.setVisible(True)
        else:
            alipay.setVisible(False)
        link.setGeometry(0, link_top, side_w, self._DONATE_LINK_H)
        # 源图 900×900，缩放结果按边长缓存，避免拖动窗口时反复解码
        if self._donate_qr_cache_size != qr_size:
            source = QPixmap(resources.donate_wechat_icon)
            if source.isNull():
                self._donate_qr_cache_size = qr_size
                self._donate_qr_cache = QPixmap()
                qr.setText("二维码\n加载失败")
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self._donate_qr_cache = source.scaled(
                    qr_size,
                    qr_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._donate_qr_cache_size = qr_size
                qr.setText("")
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not self._donate_qr_cache.isNull():
            qr.setPixmap(self._donate_qr_cache)
        qr.setVisible(True)
        link.setVisible(True)
        return status_y, status_h, qr_deficit

    def _dock_nav_buttons(self) -> list[QPushButton]:
        """当前可见的导航按钮（配置可隐藏「演员管理/信息管理」两项）。"""
        ui = self.Ui
        return [b for b in (getattr(ui, name) for name in self._DOCK_NAV_BTNS) if not b.isHidden()]

    def _dock_nav_top_base(self) -> int:
        """导航区顶边的**设计基线**（50 隐藏标题栏 / 20 显示标题栏）。

        与 `_windows_auto_adjust` 里的 `widget_buttons.move(0, 50|20)` 取同一判据
        （`manager.config.window_title == "hide"`），但**不读 `ui.widget_buttons.y()`**：
        `_layout_dock_nav` 结尾会用 `setGeometry(0, top, …)` 把 top 写回去，若基线
        读自身则「上移导航」的结果会变成下次的基线，被逐次抬到窗顶。这里返回常量，
        「上移多少」完全由 `_sync_dock_layout` 的缺口计算决定，两边不互相污染。
        """
        try:
            hidden = manager.config.window_title == "hide"
        except Exception:  # 配置未就绪（启动早期）：按显示标题栏的保守值
            hidden = False
        return self._DOCK_NAV_TOP_HIDE if hidden else self._DOCK_NAV_TOP_SHOW

    def _layout_dock_nav(self, top: int, btn_h: int, spacing: int, container_h: int) -> None:
        """按给定按钮高/间距重排导航按钮（每个按钮 min=max=btn_h，布局无自由度，
        故内容高恒为 count*btn_h + (count-1)*spacing，调用方直接用公式值即可）。

        按钮位置由 layoutWidget6 内的 QVBoxLayout 驱动（军规②：改完尺寸/间距必须
        显式 invalidate+activate）。实测（最小脚本 + 离屏探针）：layoutWidget6 自身
        高度不影响按钮落位——富余空间只堆在末尾（间距不被拉伸），且 SetMinimumSize
        约束会用**缓存的** sizeHint 回写父几何，故此处不再 resize 它，只读不用写。
        """
        ui = self.Ui
        for btn in self._dock_nav_buttons():
            btn.setMinimumHeight(btn_h)
            btn.setMaximumHeight(btn_h)
        ui.verticalLayout.setSpacing(spacing)
        ui.verticalLayout.invalidate()
        ui.verticalLayout.activate()
        ui.widget_buttons.setGeometry(0, top, ui.widget_buttons.width(), container_h)

    def _sync_dock_layout(self) -> None:
        """左侧导航坞 + 贴底状态区随窗口高度同步，窗口过矮时压缩而非重叠。

        议题 #86：状态区原本固定设计 y 坐标，窗口拉高后滞留在上半区——改为贴 widget_setting
        底边下移并预留 40px（#102）；min(..., height-h) 上限保证矮窗口下 label 完整可见。
        议题 #181（用户 175% 界面缩放反馈截图）：上述公式只兜"底边不出窗"，没兜"顶边不撞
        导航"——窗口高 < 730 时状态区顶边（height-201）会进入导航区（50..440），
        「正常模式/actor.json/版本号」与「检测网络/使用说明」按钮叠字。
        这里按"设计基准 + 剩余高度"重算（军规③：固定公式、双向幂等，窗口拉高即复原）：
          ① 空间够（height ≥ 导航底 + 间距 + 状态设计高）：完全保持设计几何；
          ② 不够：导航保持设计高，状态区吃掉剩余高度（最小 72）；
          ③ 仍不够：先压导航间距、再压按钮高（各自有下限），状态区仍不足 72 才隐藏；
             极矮窗口（< 约 460）导航按设计尺寸排布、最下方按钮被窗底裁——此时
             叠字比裁切更糟，不再继续压缩。

        两条分支都会调 `_layout_donate`，由它把收款码块（微信码/[赞助作者]/状态文字预留带）
        按窗口状态选锚法并顺带决定 `label_show_version` 的对齐方式与矩形（见该函数）：
        最大化 → **底锚**窗底（第十六轮，与 MDCx-20261007 一致），其余 → **顶锚**导航底
        （第十五轮）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        # 无论走哪条分支都刷新闸门基线：本函数是唯一的「权威重排」入口，走完之后
        # 布局所依据的文字块高就是当前值，下一次文字变化才能被正确识别为「变了」。
        # 放在最前面是因为下面有多处 return，而重排本身很贵、这次测量很便宜。
        self._dock_status_text_h_last = self._dock_status_text_h()
        height = self.height()
        # 导航顶边基线取常量（50/20）而非 ui.widget_buttons.y()：_layout_dock_nav 结尾会
        # setGeometry(0, top, …) 把 top 写回控件，读自身会让「上移导航」的结果变成下次的
        # 基线、被逐次抬到窗顶。判据与 _windows_auto_adjust 的 move(0, 50|20) 保持一致。
        nav_top = self._dock_nav_top_base()
        nav = self._dock_nav_buttons()
        status = ui.label_show_version
        local = ui.label_local_number
        # ① 空间够：设计几何（议题 #86/#102 原公式，逐值不变）
        status_y = min(
            max(height - self._DOCK_STATUS_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_STATUS_Y_MIN),
            height - self._DOCK_STATUS_H,
        )
        if status_y >= nav_top + self._DOCK_NAV_H + self._DOCK_STATUS_GAP:
            # 状态矩形的**原始**几何：两遍布局都从这两个值起算，不复用上一遍的返回值。
            # _layout_donate 会把状态矩形顶**压到 [赞助作者] 下方**（status_y =
            # link_bottom + gap），把它的输出再喂回去等于在已压低的地基上继续压。
            # （本轮起 status_bottom ≡ status_y0 + _DOCK_STATUS_H ≡ 窗底，两遍的
            #   status_bottom 恒等，故这步是等价变换；但显式保留原始值才能让
            #   「两遍从同一起点」成为不变量，而不是靠巧合成立。）
            status_y0, status_h0 = status_y, self._DOCK_STATUS_H
            # 收款码插在导航区与状态区之间；不够就压状态区（顶对齐，文字在预留带里不动）
            status_y, status_h, qr_deficit = self._layout_donate(nav_top + self._DOCK_NAV_H, status_y0, status_h0)
            # 收款码没满 _DONATE_QR_SIZE（唯一成因：窗口偏矮，**与状态文字几行无关**）时，
            # 把导航整体上移来把缺口补上——用户原话「如果下方实在没空间展示…就将…整体向上
            # 移动，上方还有一些空间，二维码图片高度还是要保持180px，软件界面容器上方还有
            # 10px以上的空间」。上移量按缺口**恰好**取 min(缺口, 基线 − _DOCK_NAV_TOP_MIN)：
            #   · 恰好取缺口 ⇒ one_size 正好补到 180，不多占位（导航不会无谓上浮）；
            #   · 上限 _DOCK_NAV_TOP_MIN ⇒ 导航顶不越过 10px，第一个按钮不贴窗框圆角；
            #   · 仍不够就按剩余高度**缩小**二维码（用户：「低于 693 时还是将收款码
            #     缩小」），缩到 _DONATE_QR_MIN 以下则由 _layout_donate 整块隐藏。
            # 第十三轮修正：缺口只由固定量算出，故同一窗口高度下「上移多少」是常量，
            # 读取/刮削前后导航与收款码的落位一字不差（不再随进度行数漂移）。
            # 第十五轮补充：赞助块顶锚导航底，故这段上移同时也把整块（二维码+[赞助作者]+
            # 状态文字）一起抬高，缺口补满即三者的落位全部落在最高允许处。
            # 第十六轮：最大化改底锚后，这段上移只影响**支付宝码能否也放满 180** 与
            # 微信码上沿离导航区的余量，块的主体（微信码下沿/链接/状态文字）仍由
            # 「status_bottom − 固定量」决定，故最大化往返不会因上移量变化而抖动。
            if qr_deficit > 0:
                raise_by = min(qr_deficit, nav_top - self._DOCK_NAV_TOP_MIN)
                if raise_by > 0:
                    nav_top -= raise_by
                    self._layout_dock_nav(nav_top, self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING, self._DOCK_NAV_H)
                    status_y, status_h, qr_deficit = self._layout_donate(
                        nav_top + self._DOCK_NAV_H, status_y0, status_h0
                    )
            self._layout_dock_nav(nav_top, self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING, self._DOCK_NAV_H)
            status.setGeometry(0, status_y, status.width(), status_h)
            status.setVisible(True)
            local.setVisible(True)
            local.move(
                0,
                min(
                    max(height - self._DOCK_LOCAL_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_LOCAL_Y_MIN),
                    height - self._DOCK_LOCAL_H,
                ),
            )
            return
        # ② 窗口过矮：导航按设计高/间距排布，状态区吃剩余高度
        avail = height - nav_top
        btn_h, spacing = self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING
        count = len(nav)
        content_h = count * btn_h + max(count - 1, 0) * spacing
        status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        if status_h < self._DOCK_STATUS_H_MIN and count:
            # ③ 状态区放不下 72：先压间距、再压按钮高，腾出状态区所需高度
            need = max(avail - self._DOCK_STATUS_H_MIN - self._DOCK_STATUS_GAP, 0)
            if count > 1 and count * btn_h + (count - 1) * spacing > need:
                spacing = max(self._DOCK_NAV_SPACING_MIN, min(spacing, (need - count * btn_h) // (count - 1)))
            if count * btn_h + (count - 1) * spacing > need:
                btn_h = max(self._DOCK_NAV_BTN_H_MIN, min(btn_h, (need - (count - 1) * spacing) // count))
            content_h = count * btn_h + (count - 1) * spacing
            status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        hide_status = status_h < self._DOCK_STATUS_H_MIN
        # 容器高度取 min(内容高, 可用高)：不够时最下方按钮被窗底裁（④，见 docstring）
        self._layout_dock_nav(nav_top, btn_h, spacing, max(min(content_h, avail), 0))
        if hide_status:
            # ④ 极矮窗口：状态区让位，导航独占整列（叠字比裁切更糟）
            status.setVisible(False)
            local.setVisible(False)
            self._hide_donate()
            # 对齐方式跟着显隐走：块藏起来时状态矩形回到 201 高的贴底带，恢复底对齐，
            # 文字重新贴住窗底（块显示时是顶对齐，见 _layout_donate）
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return
        status.setVisible(True)
        local.setVisible(True)
        status_y = nav_top + content_h + self._DOCK_STATUS_GAP
        # 这条分支是「窗口确实过矮」（状态区已进压缩阶梯），导航已按下限排布、无上移余量，
        # 故忽略返回的 qr_deficit：此时二维码按剩余高度**缩小**是正确取舍（用户第十三轮
        # 「低于 693 时还是将收款码缩小」），不该再抢导航空间；缩到 _DONATE_QR_MIN
        # 以下则 _layout_donate 已选择**隐藏**整块收款码（军规③：不叠字、不糊码）。
        status_y, status_h, _qr_deficit = self._layout_donate(nav_top + content_h, status_y, status_h)
        status.setGeometry(0, status_y, status.width(), status_h)
        # 数字浮标贴状态区左下角，且不得超出窗底
        local.move(0, min(status_y + status_h - self._DOCK_LOCAL_H, height - self._DOCK_LOCAL_H))
