"""控件高度测量工具, 命名模板区, 以及翻译 / 字段说明两个文本分组的布局。纯 Qt, 不依赖任何业务模块。"""

import math

from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QPixmap,
    QTextDocument,
)


class LayoutTextGroupsMixin:
    # 命名页「视频命名规则」组（groupBox_8）：模板预览框的高度。默认模板只有一行，
    # 128px 会在框内留出大片空白，这里按用户要求取其一半。
    _NAMING_PREVIEW_H = 64
    # groupBox_8 内容上下留白（设计值：组高 1051 - 网格高 1001）。
    _NAMING_BOX_PAD = 50
    # groupBox_8 之后同页的 QGroupBox，组高收缩后需整体上移保持设计间距。
    _NAMING_FOLLOW_GROUPS = (
        "groupBox_40",
        "groupBox_77",
        "groupBox_46",
        "groupBox_38",
        "groupBox_37",
        "groupBox_62",
        "groupBox_65",
        "groupBox_67",
    )

    def _naming_label_painted_height(self, lbl) -> int:
        """标签实际绘制出来的高度（px）。

        QLabel 的 sizeHint()/heightForWidth() 对「整段 <br> 硬换行 + 长段落自动折行」
        这类文字都偏大：前者按未折行的行数估算，后者按整段行距估算，都比真正画出
        来的像素高几十像素（实测 label_66 绘制 282 / hFW 287 / sh 387；预览结果文字
        绘制 65 / hFW 82 / sh 99，且 minimumSize 还钉着 82）。按这些值钉高，「视频文
        件名」「示例字段」下方就会留出空白。
        所以改成把标签渲染到一张白底 pixmap 上，从底部逐行回扫第一个有墨迹的行——
        那就是文字真正的下沿。

        门闩（必须）：本方法内部的 `lbl.render(pixmap)` 会向 label_66 派发
        QEvent.Resize，而 __init__ 在 label_66 上装了本窗口做 eventFilter，
        eventFilter 的 label_66 Resize 分支又会同步调用本方法 —— 两者互为递归，
        没有任何标志拦得住，无限递归直接栈溢出（Windows 0xC00000FD）把进程打死，
        而且**不是 Python 异常，crash 目录里连日志都不会留**（只有 sys.excepthook
        写的 _py.log）。faulthandler 实测栈（探针 crashstress.py / so_repro.py）：
            main_window.py:2509 in _naming_label_painted_height
            main_window.py:642  in eventFilter
            main_window.py:2509 in _naming_label_painted_height
            main_window.py:642  in eventFilter            ← 无限重复直到爆栈
        表现给用户就是「点软件设置-翻译/NFO 有几率直接退出」。故重入时直接返回标签
        自身高度（中性值，不会误触发外层的重排判断），由外层那次调用负责收尾。
        """
        if self._naming_scanning:
            return lbl.height()
        self._naming_scanning = True
        try:
            return self._measure_painted_height(lbl)
        finally:
            self._naming_scanning = False

    @staticmethod
    def _measure_painted_height(lbl) -> int:
        """_naming_label_painted_height 的实际测量体（供门闩版调用，不要直接调）。"""
        width = max(lbl.width(), 1)
        probe_h = min(max(lbl.sizeHint().height(), 200) + 200, 2000)
        pixmap = QPixmap(width, probe_h)
        pixmap.fill(QColor(255, 255, 255))
        lbl.render(pixmap)
        # 回扫用原始字节，而不是逐像素 pixelColor()：标签最多 2000 行 × 600 列，
        # 逐像素一次最大化要调 42 万次 pixelColor（cProfile tottime 0.18s，是
        # _sync_page_layouts 里最大的一笔）。这段时间事件循环被 resizeEvent 堵住、
        # 窗口一次都没绘制，用户就看到「最大化时四周先是一大圈黑屏」。改成按行取
        # bytes 切片整体比较（纯 C 层切片+比较），同图同结果、耗时可忽略。
        # 取样规则与旧实现保持一致：x 从 0 到 width 步进 2，不改变已验证的落点。
        try:
            img = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
            bpr = img.bytesPerLine()
            buf = img.constBits().asstring(img.sizeInBytes())
            white_row = b"\xff" * ((width + 1) // 2)
            for y in range(probe_h - 1, -1, -1):
                base = y * bpr
                if buf[base : base + width : 2] != white_row:
                    return y + 1
            return 1
        except Exception:
            # 取不到原始缓冲（非常规像素格式等）时退回逐像素旧路径
            pass
        img = pixmap.toImage()
        white = QColor(255, 255, 255)
        for y in range(probe_h - 1, -1, -1):
            for x in range(0, width, 2):
                if img.pixelColor(x, y) != white:
                    return y + 1
        return 1

    @staticmethod
    def _label_text_height_for_width(lbl) -> int:
        """按标签**当前宽度**算出文字真正需要的高度（px）——纯宽度函数，无高度自反馈。

        为什么不用 _naming_label_painted_height：那个方法把标签 render 到白底
        pixmap 上、从底部回扫第一个「非纯白」的行。但「白」是写死的 0xff，而
        标签的实际背景由调色板/样式表决定，不是纯白就没有一行等于 0xff，方法
        退化成恒等函数「返回标签自身高度」（offscreen 无 QSS 时背景是 0xef，
        label_66 / label_331 / label_358 实测 painted 全部 == 标签高度）。恒等
        函数配 `setFixedHeight(painted + 2)` 就是正反馈：每轮长 2px 永不收敛
        （label_331 由 41 一路漂到 47+）。真机上恰好白底才量得准，属环境碰运气。

        改用 QTextDocument（QLabel 富文本走的就是同款排版引擎）按当前宽度重新
        排版取文档高：结果只由 字体 + 文本 + 宽度 决定，不掺入标签当前高度，
        故同宽度必得同值（幂等、不累积漂移），也不受背景色影响。
        高度取文档高（含上下 document margin）而非墨迹范围，保证绝不裁字；
        实测 label_331 单行墨迹 13px / 文档高 22px，+2 余量后 24px。
        """
        doc = QTextDocument()
        doc.setDefaultFont(lbl.font())
        text = lbl.text() or ""
        if "<" in text:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(max(lbl.contentsRect().width(), 1))
        return math.ceil(doc.size().height()) + 2

    @staticmethod
    def _label_ink_height_for_width(lbl) -> int:
        """按标签**当前宽度**算出文字墨迹真正占多高（px）——纯宽度函数，无高度自反馈。

        比 _label_text_height_for_width 更紧：后者取 QTextDocument 文档高，量的是
        含上下 document margin 的**行盒**范围；本方法量**墨迹**范围，故省下的正是
        用户截图里圈出的那两段空白（label_331 单行行盒 24px / 墨迹 18px）。

        墨迹上沿用 Qt 字体度量直接算：QTextLine 没有 tightBoundingRect，
        但「行盒顶到墨迹顶」的偏移有闭式解
            ink_top = QFontMetrics(font).ascent() + QFontMetrics(font).tightBoundingRect(text).y()
        （实测 label_331 → 12 + (-9) = 3，与其 AlignTop 下逐高度像素扫描得到的
        ink top 恒为 3 完全吻合；label_357 / label_358 同样命中）。

        行数靠 QTextDocument 文档高反推：`docH = 2×documentMargin + 行数×lineSpacing`
        （实测 margin=4：w=620→38→2 行，w=400→53→3 行，w=200→98→6 行，全部对上）。
        不能用 `QTextBlock.layout().lineCount()`：离屏下 layout 未激活恒返回 0；
        也不能用 `QTextLayout.beginLayout()`：同样在未挂 paint device 时返回 0 行。

        逐行**精确**墨迹高 Qt 给不出（QTextLine 只有行盒级 API），故按
        `ink_top + (行数-1) × lineSpacing + 单行墨迹高` 近似，其中单行墨迹高
        取 tightBoundingRect 高度按行数摊平。实测（真实 QSS 字体 asc=12 ls=15）：
          label_331 单行 → 3 + 0 + 12 = 15（像素扫描实测墨迹恰为 y 3..18）；
          label_331 两行 → 3 + 15 + 12 = 30（实测墨迹 y 3..27，不裁）；
          label_357      → 4 + 0 +  8 = 12（墨迹仅 8px，垂直居中留 4px 余量）；
          label_358      → 3 + 0 +  9 = 12（墨迹 9px）。
        绝对不能用 `ink_top + 行数 × lineSpacing`：那样 label_357 会得 19px，
        而它真实墨迹只有 8px，白白多留 7px 正是用户圈出的空隙。
        """
        text = lbl.text() or ""
        if not text.strip():
            return 0
        fm = QFontMetrics(lbl.font())
        # 富文本标签的 <p> 等包裹会污染断行宽度，先剥成纯文本（QLabel 显示的
        # 也是剥掉后的字形）；纯文本标签原样返回。
        doc = QTextDocument()
        doc.setDefaultFont(lbl.font())
        if "<" in text:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(max(lbl.contentsRect().width(), 1))
        spacing = fm.lineSpacing()
        usable = max(doc.size().height() - 2 * doc.documentMargin(), spacing)
        lines = max(1, round(usable / spacing))
        tight = fm.tightBoundingRect(text)
        ink_top = fm.ascent() + tight.y()
        # tight.height() 对多行文本是整段包围盒，按行数摊平才回到「单行墨迹高」
        ink_line = max(tight.height() / lines, 1)
        return max(1, math.ceil(ink_top + (lines - 1) * spacing + ink_line))

    def _sync_naming_template_section(self) -> None:
        """命名页「视频命名规则」组（groupBox_8）按内容收缩，消除大片空白。

        两个现象（用户截图）：
        1. 「视频文件名」上方大片空白——说明文字 label_66 是 AlignTop 的可换行富
           文本标签，整块网格按内容收缩后，说明文字必须给出真实需要的高度，
           否则要么裁字、要么在下方留白（见 _naming_label_painted_height）。
        2. 「模板预览」占满网格剩余空间被撑得过高。
        3. 「示例字段」下方大片空白——预览结果文字
           label_name_template_preview_result 同理，它的 sizeHint/minimumSize 都
           远大于实际绘制高度，不贴合就会把整组底部顶出一片空白。

        做法：预览钉到设计三分之一高度；说明文字按实际绘制高度贴合；整个网格的
        组高按内容收缩，其后的 QGroupBox 按同一增量上移保持设计间距
        （下移/上移都用「设计基准 + 增量」，幂等无累积漂移，见 MEMORY 军规③）。
        """
        ui = self.Ui
        box = ui.groupBox_8
        widget = ui.gridLayoutWidget_8
        lbl = ui.label_66
        preview = ui.plainTextEdit_name_template_preview
        result = ui.label_name_template_preview_result
        grid = ui.gridLayout_8
        if lbl.width() <= 0 or box.width() <= 0:
            return
        if self._naming_resyncing:
            return
        # 休眠页零成本：命名页不可见时整段跳过（切到该 tab 的 currentChanged 与
        # 滚动区 showEvent 会补齐，接线见 __init__），省掉两次 pixmap 渲染扫描 +
        # 网格重排 + 后续 6 个 groupBox 的 move。这一项是把最大化时 resizeEvent 的
        # 阻塞从 ~600ms 压到 ~40ms 的关键（用户报「放大时四周先是一大圈黑屏」：
        # 窗口在这一段时间里一次都没绘制，新露出的区域当然是黑的）。
        # 不要在这里加「输入指纹相同就整体返回」的短路：sync_wide_children_width()
        # 会把 groupBox_8 与后续 groupBox 按登记的设计几何复位，指纹没变但几何已被
        # 复位时早退，会留下 groupBox_8 已收缩、后续组仍在设计位的错位。
        if not box.isVisibleTo(self):
            return

        # 首次调用登记设计几何（此后 sync_wide_children_width 只改宽不改高，
        # groupBox_8 的高由本方法接管）。
        if self._naming_design is None:
            self._naming_design = {
                "box_h": box.height(),
                "groups": {name: getattr(ui, name).y() for name in self._NAMING_FOLLOW_GROUPS},
            }

        # 本方法会改 label_66 高度并触发其 Resize；用标志位抑制 eventFilter 的递归重算。
        self._naming_resyncing = True
        try:
            # 1) 两段说明文字都按实际绘制高度贴合。测量前必须先解除上一轮的固定
            #    高度，否则标签仍被裁着，量到的只是残缺高度（会越量越小、最后裁字）。
            for text_widget in (lbl, result):
                text_widget.setMinimumHeight(0)
                text_widget.setMaximumHeight(16777215)
            grid.invalidate()
            grid.activate()
            lbl.setFixedHeight(self._naming_label_painted_height(lbl))
            # 2) 模板预览固定高度，不再吸收网格剩余空间。
            preview.setFixedHeight(self._NAMING_PREVIEW_H)
            # 3) 预览结果文字（状态/结果/示例字段）同样按真实绘制高度贴合。
            result.setFixedHeight(self._naming_label_painted_height(result))
            grid.invalidate()
            grid.activate()

            # 3) 组高按内容收缩，后续组同步上移。
            content_h = grid.sizeHint().height()
            new_box_h = content_h + self._NAMING_BOX_PAD
            widget.setGeometry(widget.x(), widget.y(), widget.width(), content_h)
            box.setGeometry(box.x(), box.y(), box.width(), new_box_h)

            # 宽幅容器登记表里存的是设计几何，同步宽度时会按登记高度复位 groupBox_8 /
            # gridLayoutWidget_8，这里把登记高度一并更新。
            registry = getattr(ui.scrollAreaWidgetContents_mingming, "_wide_children_design", None)
            for entry in registry or ():
                if entry.widget is box:
                    ex, ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, ey, ew, new_box_h)
                    for item in entry.inner:
                        if item.widget is widget:
                            ix, iy, iw, _ih = item.geometry
                            item.geometry = (ix, iy, iw, content_h)

            delta = self._naming_design["box_h"] - new_box_h
            for name in self._NAMING_FOLLOW_GROUPS:
                group = getattr(ui, name)
                group.move(group.x(), self._naming_design["groups"][name] - delta)

            scroll = getattr(ui, "scrollArea_7", None)
            if scroll is not None:
                scroll.sync_content_min_height()
            self._naming_last_width = lbl.width()
        finally:
            self._naming_resyncing = False

    # ============ 设置-翻译页（简介 / 演员两组）的间距收紧常量 ============
    # groupBox_83（简介）：网格容器与 frame_5「双语显示」之间保留的间距、
    # 组底留白。设计值里容器底部有 7px、组底 9px，两处都太松，合并成常量。
    _FANYI_INTRO_GRID_GAP = 10
    _FANYI_BOX_BOT_PAD = 9
    # groupBox_84（演员）：行首留白。Qt 会把容器多出来的高度在「顶 / 行间 /
    # 底」之间均分（实测 layoutWidget_20 418 vs 网格 sizeHint 352，多出的 66px
    # 被均分成 顶16 / 行间各+16 / 底18），长说明文字的行顶因此落在 120。
    # 改为由本控制器显式给定：留白 30 时首行「演员语言」行顶落在组内 52，标题
    # 下方空着将近两行（用户截图「内容整体向上移动两行，移动完成后删掉下方多出
    # 来的空白空间」）。留白归 0 后首行行顶回到 layoutWidget_20 的设计 y=22，
    # 标题下方不再有整行空白；组高是「容器底 + _FANYI_BOX_BOT_PAD」算出来的，
    # 行首少 30 组高就同步收 30，其后各组随 delta_actor 整体上移，空出来的
    # 30px 不会被留成组底/组间空档。
    _FANYI_ACTOR_TOP_PAD = 0
    # groupBox_trans（翻译引擎）：组底留白。设计值里 layoutWidget_2 底到组底 10px。
    _FANYI_TRANS_BOT_PAD = 10
    # groupBox_trans 之后、简介组（groupBox_83）之前的组：翻译引擎组一收紧，
    # 它们必须跟着上移，否则组间距会被整段拉开。
    _FANYI_TRANS_FOLLOW_GROUPS = (
        "groupBox_llm",
        "groupBox_82",
    )
    # groupBox_83/84 之后所有需要跟着上移的组（都是绝对定位在内容控件上的）。
    _FANYI_FOLLOW_GROUPS = (
        "groupBox_84",
        "groupBox_85",
        "groupBox_86",
        "groupBox_87",
        "groupBox_88",
        "groupBox_89",
    )

    def _sync_fanyi_group_spacing(self) -> None:
        """设置-翻译页：简介组与演员组按内容收紧间距（用户截图两处反馈）。

        ① 简介组（groupBox_83）「翻译方式」与「双语显示」之间空得离谱。
           离屏实测（探针 fanyi_probe2.py，还原态）：翻译方式行底在组内 y=108，
           双语显示墨迹顶约 180，中间约 72px，而真正占位的只有一行 17px 的
           提示文字。拆开来：label_176 拿了 34px 却只画 24px（富文本 <p> 的段
           落边距吃掉了 17px）；gridLayout_48 的 sizeHint 106 被容器 131 拉出
           25px 余量、Qt 在顶/行间/底均分（实测行距 12 而非设计的 6）；容器底
           还剩 7px、组底 9px。
        ② 演员组（groupBox_84）长说明文字 label_249 整体比设计值低一行。
           gridLayout_50 的 sizeHint 352 被容器 418 拉出 66px，同样被均分成
           顶16/行间各+16/底18，文字行顶落在 120；文字本身 14 行 × 20px = 280
           正好等于标签高度，最后一行贴着组框内框。用户要求「整体上移一行，
           同时从底部去掉一行高度」。后续追加要求「内容整体向上移动两行，
           移动完成后删掉下方多出来的空白空间」——那 30px 行首留白（首行行顶
           52）正是标题下方的整行空白，去掉后首行行顶回到容器设计位 22，组高
           同步收 30，组底留白仍是 _FANYI_BOX_BOT_PAD。
        ③ 翻译引擎组（groupBox_trans）「DeepLX URL」与提示文字
           label_baidu_hint 之间空着一整行，其下的「百度 APP / 百度密钥」两行
           被整体下推（用户截图：提示词向上移动一行，百度 APP、百度密钥同步
           向上移动一行）。真机实测（windows 平台，YaHei UI 9pt）：容器
           layoutWidget_2 高 280，而各行真实需要只有 218（勾选行/输入行各 30、
           两行说明文字各 16、行间 6×6）；gridLayout_32 末尾没有 Expanding
           间隔，多出来的 62px 就全灌进独占一行的 label_baidu_hint（垂直策略
           Preferred + wordWrap 的 heightForWidth 有效，且是该行唯一控件），
           文字被垂直居中 → 上下各空、下面两行被推下去。与 ①② 同根因。

        做法（与 _sync_naming_template_section 同款：设计基准 + 增量，幂等
        不累积漂移）：
          0) 先收紧翻译引擎组：两行说明文字按墨迹高度贴合（纯宽度函数，见
             _label_ink_height_for_width）→ 容器高度钉成网格 sizeHint → 组高
             = 容器底 + _FANYI_TRANS_BOT_PAD；其后所有组（含简介组自身）按这个
             收缩量上移。放在最前面做，后面的增量都在它之上累加。
          1) 量「真实绘制高度」前必须先解除上一轮的固定高度，否则量到的是被裁
             的残缺高度（会越量越小、最后裁字）。富文本标签取 painted 与
             heightForWidth 的较大者——heightForWidth 对富文本才准。
          2) 把网格容器高度钉成 sizeHint（不给 Qt 任何均分空间），行首留白改
             由常量显式给定，几何完全可预测。
          3) 组高 = 容器底 + 固定底留白；其后的 QGroupBox 按「设计 y − 累计收
             缩量」上移，并同步更新 scrollArea_11 宽幅登记表里的高度，最后
             sync_content_min_height() 收紧内容控件（否则页尾留一大片空白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or self._fanyi_resyncing:
            return
        intro, actor = ui.groupBox_83, ui.groupBox_84
        hint, story = ui.label_176, ui.label_249
        trans = ui.groupBox_trans
        trans_note, trans_hint = ui.label_164, ui.label_baidu_hint
        g_intro, g_actor, g_trans = ui.gridLayout_48, ui.gridLayout_50, ui.gridLayout_32
        lw13, lw20, frame = ui.layoutWidget_13, ui.layoutWidget_20, ui.frame_5
        lw2 = ui.layoutWidget_2
        # 休眠页零成本：没激活的页签不会给出真实视口，量出来的都是设计尺寸。
        if not (trans.isVisibleTo(self) and intro.isVisibleTo(self) and actor.isVisibleTo(self)):
            return
        if trans_note.width() <= 0 or trans_hint.width() <= 0 or hint.width() <= 0 or story.width() <= 0:
            return

        if self._fanyi_design is None:
            shifted = (*self._FANYI_TRANS_FOLLOW_GROUPS, "groupBox_83", *self._FANYI_FOLLOW_GROUPS)
            self._fanyi_design = {
                "groups": {n: getattr(ui, n).y() for n in shifted},
                "trans_h": trans.height(),
                "intro_h": intro.height(),
                "actor_h": actor.height(),
            }

        self._fanyi_resyncing = True
        try:
            # 0) 翻译引擎组：两行说明文字按墨迹高度贴合 → 容器按网格 sizeHint 收紧。
            #    label_baidu_hint 是独占一行的 wordWrap 标签（垂直策略 Preferred、
            #    heightForWidth 有效），容器一富余它就把多出来的整段高度吃掉，
            #    文字垂直居中、下面「百度 APP / 百度密钥」两行被整体下推（用户截图
            #    里 DeepLX URL 与提示文字之间那整行空白）。先解除上一轮的固定高度
            #    再量，避免量到被裁的残缺高度（越量越小、最后裁字）。
            for lbl in (trans_note, trans_hint):
                lbl.setMinimumHeight(0)
                lbl.setMaximumHeight(16777215)
            g_trans.invalidate()
            g_trans.activate()
            # 纯宽度函数（只吃 字体+文本+宽度）：墨迹高而非行盒高，多大宽度都刚好
            # 贴住文字；行盒高会把用户圈出的空白原样留回来。
            trans_note.setFixedHeight(self._label_ink_height_for_width(trans_note))
            trans_hint.setFixedHeight(self._label_ink_height_for_width(trans_hint))
            g_trans.invalidate()
            g_trans.activate()

            # 1) 翻译引擎组：容器按网格 sizeHint 收紧（末尾 Expanding 间隔吸收
            #    残余富余，不会再有某一列被灌高），组高 = 容器底 + 固定底留白。
            trans_lw_h = g_trans.sizeHint().height()
            lw2.setGeometry(lw2.x(), lw2.y(), lw2.width(), trans_lw_h)
            trans_h = lw2.y() + trans_lw_h + self._FANYI_TRANS_BOT_PAD
            trans.setGeometry(trans.x(), trans.y(), trans.width(), trans_h)
            delta_trans = self._fanyi_design["trans_h"] - trans_h
            # 翻译引擎组之后、简介组之前的组按同一收缩量上移（组间距不变）。
            for name in self._FANYI_TRANS_FOLLOW_GROUPS:
                group = getattr(ui, name)
                group.move(group.x(), self._fanyi_design["groups"][name] - delta_trans)

            # 2) 简介/演员组：解除固定高度 → 量真实需要高度 → 重新钉上。
            for lbl in (hint, story):
                lbl.setMinimumHeight(0)
                lbl.setMaximumHeight(16777215)
            g_intro.invalidate()
            g_actor.invalidate()
            g_intro.activate()
            g_actor.activate()
            # 单行提示：painted + 2（+2 是抗字体 hinting 抖动的余量；若某宽度下
            # 折成两行，量到的 painted 会自动变大，不依赖任何写死行数）。
            hint_h = self._naming_label_painted_height(hint) + 2
            # 长说明文字是富文本（<p style='line-height:20px'>），QFontMetrics 对
            # 它无效，只能靠渲染扫描 + heightForWidth，取两者较大值防止裁字。
            story_h = max(
                self._naming_label_painted_height(story) + 2,
                story.heightForWidth(story.width()),
            )
            hint.setFixedHeight(hint_h)
            story.setFixedHeight(story_h)
            g_actor.setContentsMargins(0, self._FANYI_ACTOR_TOP_PAD, 0, 0)
            g_intro.invalidate()
            g_actor.invalidate()
            g_intro.activate()
            g_actor.activate()

            # 3) 简介组：容器按网格 sizeHint 收紧，frame_5 跟着上移。
            #    y 按「设计基准 − 翻译引擎组收缩量」给，不吃当前值，幂等。
            intro_lw_h = g_intro.sizeHint().height()
            lw13.setGeometry(lw13.x(), lw13.y(), lw13.width(), intro_lw_h)
            frame.move(frame.x(), lw13.y() + intro_lw_h + self._FANYI_INTRO_GRID_GAP)
            intro_h = frame.y() + frame.height() + self._FANYI_BOX_BOT_PAD
            intro_y = self._fanyi_design["groups"]["groupBox_83"] - delta_trans
            intro.setGeometry(intro.x(), intro_y, intro.width(), intro_h)
            delta_intro = self._fanyi_design["intro_h"] - intro_h

            # 4) 演员组：容器按网格 sizeHint 收紧（行首留白已折进 topMargin，
            #    留白 0 时首行行顶 = 容器设计 y，标题下方不再空一整行）。
            actor_lw_h = g_actor.sizeHint().height()
            lw20.setGeometry(lw20.x(), lw20.y(), lw20.width(), actor_lw_h)
            actor_h = lw20.y() + actor_lw_h + self._FANYI_BOX_BOT_PAD
            actor_y = self._fanyi_design["groups"]["groupBox_84"] - delta_trans - delta_intro
            actor.setGeometry(actor.x(), actor_y, actor.width(), actor_h)
            delta_actor = self._fanyi_design["actor_h"] - actor_h

            # 5) 后续组按累计收缩量上移（设计基准 + 增量，反复调用不漂移）。
            for name in self._FANYI_FOLLOW_GROUPS[1:]:
                group = getattr(ui, name)
                group.move(
                    group.x(),
                    self._fanyi_design["groups"][name] - delta_trans - delta_intro - delta_actor,
                )

            # 宽幅登记表里存的是设计几何，同步宽度时会按登记值复位这些控件，
            # 这里只把 y/h 写回登记（与命名页画质组同一处理）。
            #
            # 设计宽度必须原样取回登记值（entry.geometry[2]），绝不能写
            # intro.width()/actor.width()：那读到的是「上一轮宽幅同步已拉伸后的
            # 当前宽」，把它当设计宽存回去，下一轮宽幅同步就会再加一次 extra，
            # 宽度无界增长（离屏实测：每次窗口缩放两组框宽 +1216px，几轮后
            # 简介/演员框飞出窗口右缘，右侧大片空白）。设计宽度是登记表的唯一
            # 真值来源，只在 setupUi 的 setWidget 时刻采集过一次。
            registry = getattr(ui.scrollAreaWidgetContents_fanyi, "_wide_children_design", None)
            # 本方法接管过的组：连 y 一起写回登记。y 也要写——组一收紧，后续组
            # 的设计位就整体上移了（翻译引擎 −44、简介/演员各自再减），登记里若
            # 仍留设计 y，宽幅同步会把它们按旧位复位，本方法与宽幅同步的先后
            # 顺序就成了隐性依赖。
            managed = {trans, intro, actor}
            for name in (*self._FANYI_TRANS_FOLLOW_GROUPS, *self._FANYI_FOLLOW_GROUPS):
                managed.add(getattr(ui, name))
            for entry in registry or ():
                if entry.widget in managed:
                    ex, _ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, entry.widget.y(), ew, entry.widget.height())
                # 组内绝对定位的容器：登记 y/h，避免宽幅同步按设计值把收紧后的
                # 高度又撑回去（那会让本方法与宽幅同步的先后顺序成为隐性依赖）。
                for item in entry.inner:
                    if item.widget is lw2:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw2.y(), iw, trans_lw_h)
                    elif item.widget is lw13:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw13.y(), iw, intro_lw_h)
                    elif item.widget is lw20:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw20.y(), iw, actor_lw_h)
                    elif item.widget is frame:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, frame.y(), iw, frame.height())

            scroll = getattr(ui, "scrollArea_11", None)
            self._sync_fanyi_trans_align(scroll)
            if scroll is not None:
                scroll.sync_content_min_height()
        finally:
            self._fanyi_resyncing = False

    def _sync_fanyi_trans_align(self, scroll=None) -> None:
        """设置-翻译页：窄态四个目标左移到锚点列；宽态（最大化）四个目标对到锚点列。

        用户需求（窄态/最小化，保持此前行为不变）：「显示翻译来源」与「日语+中文」
        左移到与「中文繁体」（radioButton_outline_zh_tw，保持不动）严格上下对齐；
        「使用演员映射表翻译演员」左移到与「中文繁体」对齐（锚点为
        radioButton_actor_zh_tw，保持不动）；「关闭」
        （radioButton_trans_show_one）左移到与「日语」
        （radioButton_outline_jp，保持不动）严格上下对齐。

        用户需求（宽态/最大化，翻译页其余布局、控件、提示词等保持不变）：
        「显示翻译来源」「使用演员映射表翻译演员」向左移动到与「中文繁体」
        上下严格对齐（中文繁体不动）；「日语+中文」向右移动到与「中文繁体」
        严格上下对齐，「关闭」向右移动到与「日语」严格上下对齐（中文繁体、
        日语不动）。即四个目标的 content-x 与各自锚点完全相等，方向不限。

        做法：
          - 窄态（拉伸量 <= 0）：沿用此前逻辑——只允许左移，右推/已对齐则放弃；
            若宽态加宽/钉宽过双语显示行容器与三个单选，先交还设计值（见下）。
          - 宽态：四个目标按锚点 content-x 精确对齐（双向）。两个复选框的父容器
            （layoutWidget_13/20）会被通用宽幅同步拉宽，目标落在容器内，无需
            处理；但「双语显示」行的 frame_5（设计 661）与 layoutWidget_24
            （设计 521）是绝对定位、通用同步不拉宽——直接 move() 会把单选框钉
            到父容器之外导致裁剪（子控件超出父矩形不绘制）。故先把 frame_5 加宽
            到组宽（组宽 − 左右各 20px 设计边距），layoutWidget_24 加宽到
            frame 宽 − 140（设计：frame 内 x=140、右缘贴齐），再 activate。
            加宽后 HBox 会把多余宽度均分到三个单选身上（离屏实测横向三单选会被
            拉到 460 宽），「中文+日语」会被拉宽变形、其余两项位置也算不准，
            故把三个单选的宽度钉为自然宽（sizeHint，与字号/缩放自适应），HBox
            把它们顶左排列，「中文+日语」保持自然大小不动；再 move() 目标到锚点。
          - 经 content 中转量锚点与目标的绝对 x 差值（QWidget.mapTo 要求目标是
            调用者的祖先，跨分支直接映射会拿到未定义值，故一律经 content 中转），
            目标 move() 到锚点 x（只改 x 不碰 y/宽高；越出父级则放弃；布局容器
            后续 activate 会按设计复位，还原不依赖本方法，每遍重钉故双向幂等）。
        休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        if scroll is None:
            scroll = getattr(ui, "scrollArea_11", None)
        box = getattr(ui, "groupBox_83", None)
        if box is None or not box.isVisibleTo(self):
            return
        content = scroll.widget() if scroll is not None else box.parentWidget()
        if content is None:
            return
        pairs = (
            ("radioButton_outline_zh_tw", "checkBox_show_translate_from"),
            ("radioButton_outline_zh_tw", "radioButton_trans_show_jp_zh"),
            ("radioButton_outline_jp", "radioButton_trans_show_one"),
            ("radioButton_actor_zh_tw", "checkBox_actor_translate"),
        )
        wide = self._scroll_stretch_extra(scroll) > 0
        if wide:
            self._widen_fanyi_bilingual_row()
        else:
            self._restore_fanyi_bilingual_row()
        for anchor_name, target_name in pairs:
            anchor = getattr(ui, anchor_name, None)
            target = getattr(ui, target_name, None)
            if anchor is None or target is None:
                continue
            if target.parentWidget() is None or anchor.parentWidget() is None:
                continue
            dx = anchor.mapTo(content, anchor.rect().topLeft()).x() - target.mapTo(content, target.rect().topLeft()).x()
            if not wide and dx >= 0:
                continue  # 窄态只允许左移，右推/已对齐则放弃；宽态按锚点精确对齐
            g = target.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > target.parentWidget().width():
                continue  # 越出父级则保持通用逻辑给出的位置
            if dx:
                target.move(nx, g.y())
        if wide:
            # 「中文+日语」保持设计位置（父容器内 x=0、自然宽）：加宽后 HBox 会把
            # 多余空间均分成前后间隙把它顶到中间（离屏实测 x=288），此处每遍钉回。
            first = getattr(ui, "radioButton_trans_show_zh_jp", None)
            if first is not None and first.x() != 0:
                first.move(0, first.y())

    # 「双语显示」行在 .ui 里的设计几何（frame_5：组内 x=20 w=661；
    # layoutWidget_24：frame 内 x=140 w=521，右缘贴齐 frame 右缘）。
    _FANYI_BILINGUAL_FRAME_W = 661
    _FANYI_BILINGUAL_LW_W = 521
    _FANYI_BILINGUAL_LW_X = 140
    _FANYI_BILINGUAL_RADIOS = (
        "radioButton_trans_show_zh_jp",  # 中文+日语（保持自然大小不动，只钉宽防 HBox 拉伸）
        "radioButton_trans_show_jp_zh",  # 日语+中文
        "radioButton_trans_show_one",  # 关闭
    )

    def _widen_fanyi_bilingual_row(self) -> None:
        """宽态：加宽「双语显示」行容器并把三个单选钉为自然宽（见 trans_align）。"""
        ui = self.Ui
        frame, lw = ui.frame_5, ui.layoutWidget_24
        want_frame_w = ui.groupBox_83.width() - 2 * 20
        if frame.width() != want_frame_w:
            frame.resize(want_frame_w, frame.height())
        want_lw_w = frame.width() - self._FANYI_BILINGUAL_LW_X
        if lw.width() != want_lw_w:
            lw.resize(want_lw_w, lw.height())
        if lw.layout() is not None:
            lw.layout().invalidate()
            lw.layout().activate()
        for name in self._FANYI_BILINGUAL_RADIOS:
            radio = getattr(ui, name, None)
            if radio is None:
                continue
            natural = radio.sizeHint().width()
            if radio.minimumWidth() != natural or radio.maximumWidth() != natural:
                radio.setFixedWidth(natural)

    def _restore_fanyi_bilingual_row(self) -> None:
        """窄态：把宽态加宽/钉宽过的容器与单选交还设计值（幂等，数值相符即 no-op）。"""
        ui = self.Ui
        frame, lw = ui.frame_5, ui.layoutWidget_24
        if frame.width() != self._FANYI_BILINGUAL_FRAME_W:
            frame.resize(self._FANYI_BILINGUAL_FRAME_W, frame.height())
        if lw.width() != self._FANYI_BILINGUAL_LW_W:
            lw.resize(self._FANYI_BILINGUAL_LW_W, lw.height())
        if lw.layout() is not None:
            lw.layout().invalidate()
            lw.layout().activate()
        for name in self._FANYI_BILINGUAL_RADIOS:
            radio = getattr(ui, name, None)
            if radio is None:
                continue
            # .ui 里三个单选均无 maximumSize 约束、minimumWidth 均为 0
            # （trans_show_jp_zh 另有 minimumHeight 30，那是高度方向，此处不动）。
            if radio.minimumWidth() != 0 or radio.maximumWidth() != 16777215:
                radio.setMinimumWidth(0)
                radio.setMaximumWidth(16777215)

    # ============ 设置-命名页（画质组 groupBox_65）的间距收紧常量 ============
    # 网格容器与 QHD 说明、说明与分辨率行、分辨率行与末端添加4K行、末端添加4K行与
    # definition 说明之间的保留间距，以及组底留白。设计值里网格容器 77px
    # （两行内容只要约 46px，多出的 30px 被 Qt 均分到顶/行间/底）、QHD 说明
    # 固定 41px（窄态两行刚好，最大化时文字只占一行、剩下一半空白），HD 行到
    # 分辨率行之间看着太松。运行时按内容收紧后组高同步收缩。
    #
    # 用户截图标注（最大化态）：QHD 说明「向上移动一行」、分辨率行及以下
    # 「向上移动两行」、多出来的三行空间删掉。折成像素就是这三处预留间距
    # （10 / 7 / 9）+ frame_6 的居中余量（设计 46 − 内容 32 = 14）
    # = 40px ≈ 三行单行文字高，故全部归零：网格底与说明贴合、分辨率行与
    # 末端添加4K行贴合、末端添加4K行与尾说明贴合。组底留白 25px 是用户明确要求
    # 不动的（definition 说明下方空白不增加）。
    #
    # 随后用户改口：「分辨率获取方式：」及它下方的内容**向下移动一行**。故
    # 说明与分辨率行之间恢复一整行行高（_DEFN_NOTE_GAP = -1 → 按 label_331
    # 字体实测 lineSpacing 取值）。再后来要求尾说明（label_358）单独再下移
    # 一行，于是末端添加4K行与尾说明之间也恢复一整行行高（_DEFN_TAIL_GAP = -1
    # → 按 label_358 字体实测 lineSpacing 取值）。最后要求「末端添加4K字符」行
    # 单独再下移一行，于是分辨率行与末端添加4K行之间同样恢复一整行行高
    # （_DEFN_FRAME_GAP = -1 → 按 frame_6 内 radio 字体实测 lineSpacing 取值）。
    # 三处都按字体实测而非写死，用户机器字号比离屏大，写死会少一半；组内自上
    # 而下串联，故每一处下移会把其下方所有行一起带下去。
    _DEFN_GRID_GAP = 0  # 网格容器底 → label_331 顶（说明紧贴 HD 行）
    # label_331 底 → frame_6 顶：用户要求「分辨率获取方式：」及其下方内容整体
    # 向下移动一行，故这里留一整行文字高（此前为 0，四处全贴合）。取 label_331
    # 字体的实测行高而非写死数值——用户机器字号比离屏大，写死会少一半。
    _DEFN_NOTE_GAP = -1  # -1 = 用 label_331 的一行行高（见下方 note_gap 解析）
    # frame_6 底 → 末端添加4K行顶：用户要求「末端添加4K字符」行再向下移动一行，取
    # frame_6 内 radio 的实测行高（与前两处同理按字体实测，不写死）。
    _DEFN_FRAME_GAP = -1  # -1 = 用 radioButton_videosize_video 的一行行高
    # 末端添加4K行底 → label_358 顶：用户要求尾说明（指命名时在番号后添加4K…）
    # 「向下移动一行的宽度」= 也空出一整行文字高。与 _DEFN_NOTE_GAP 同理按
    # label_358 字体实测 lineSpacing 取值，不写死。
    _DEFN_TAIL_GAP = -1  # -1 = 用 label_358 的一行行高（见下方 tail_gap 解析）
    _DEFN_BOX_BOT_PAD = 25  # label_358 底 → 组底（与设计一致，下方空白不增加）
    _DEFN_GROUP_GAP = 19  # 组底 → groupBox_67 顶（命名页统一 19px 间距）
    # 末端添加4K行内复选框相对行标签的下沉量（设计：标签 y218，复选框 y221）。
    _DEFN_ROW_CHECK_DY = 3

    def _sync_definition_group_spacing(self) -> None:
        """设置-命名页：画质组按内容收紧 HD 行到分辨率获取方式的间距。

        现象（用户截图）：「HD、FHD、QHD、UHD」行与「分辨率获取方式」行之间太松，
        最大化与最小化都要收。静态改 .ui 只能顾一态：label_331 固定高度在窄态
        两行刚好，最大化时文字只占一行就剩下一半空白。
        做法（与 _sync_fanyi_group_spacing 同款：解除固定高度 → 量真实需要高度 →
        重新钉上 → 其余行按固定间距串起来 → 组高同步收缩 → 后续组上移；全程按
        当前几何与实测值推导，幂等不累积漂移）：
          1) 网格容器钉到 sizeHint（不给 Qt 均分空间，两行单选贴紧）；
          2) label_331 按**墨迹**高度贴合（最大化单行、最小化双行，各自刚好；
             级联中途标签内部还是陈旧折行，eventFilter 的 label_331 分支会多跑
             几遍直到收敛，label_66 同款）；
          3) 组高 = definition 说明底 + 固定底留白（下方空白与设计一致不增加）；
          4) groupBox_67（其他说明，组内唯一后续组）按新组底 + 19px 间距上移；
          5) 同步更新宽幅登记表里的高度/位置（只换 y/h，设计宽度原样保留，
             否则下一次宽幅同步会把 extra 加重），最后 sync_content_min_height
             收紧内容（否则页尾留白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or self._defn_resyncing:
            return
        box = ui.groupBox_65
        # 休眠页零成本：命名 tab 不可见时视口宽度不是终态，量到的折行数不对，
        # 切页 showEvent + beats 会补齐（翻译组同款）。
        if not box.isVisibleTo(self):
            return
        grid = ui.gridLayout_43
        lw = ui.gridLayoutWidget_35
        note = ui.label_331
        frame = ui.frame_6
        row_label = ui.label_357
        check_f = ui.checkBox_foldername_4k
        check_n = ui.checkBox_filename_4k
        tail = ui.label_358
        follower = ui.groupBox_67
        if note.width() <= 0:
            return

        self._defn_resyncing = True
        try:
            # 1) 解除固定高度 → 量真实需要高度 → 重新钉上。
            #    量之前必须先解除上一轮的固定高度，否则标签仍被裁着，量到的只是
            #    残缺高度（会越量越小、最后裁字，-template/翻译两组同款教训）。
            note.setMinimumHeight(0)
            note.setMaximumHeight(16777215)
            grid.invalidate()
            grid.activate()
            grid_h = grid.sizeHint().height()
            # 说明文字按当前宽度重排量出真实需要高度（_label_ink_height_for_width：
            # 纯宽度函数、不掺标签自身高度，故不会每轮 +2 漂移；painted 回扫法在
            # 非纯白背景下退化成恒等函数，不能用，见其 docstring）。量墨迹而非
            # 行盒，用户圈出的两段空白正是「行盒底 - 墨迹底」的差。最大化单行、
            # 最小化双行，各自刚好。
            note_h = self._label_ink_height_for_width(note)
            # 「末端添加4K字符：」行标签同样是垂直居中，30px 行里墨迹只有 8px、
            # 上下各空 10px（用户圈的位置2/位置3）。钉到墨迹高 + 4px，
            # 行高随后由单选/复选框的 minimumHeight（16px）决定。
            row_h = self._label_ink_height_for_width(row_label) + 4
            row_label.setFixedHeight(row_h)
            lw.setGeometry(lw.x(), lw.y(), lw.width(), grid_h)
            note.setFixedHeight(note_h)
            grid.invalidate()
            grid.activate()

            # 2) 其余行按固定间距串起来（x/宽不动，只动 y；宽度归宽幅同步管）。
            #    frame_6 是无布局的 QFrame（三个单选装在 layoutWidget_26 里），
            #    设计 46px 里只有 32px 是内容、14px 是 Qt 垂直居中白给的余量。
            #    按内部布局 sizeHint 钉死高度、内容贴顶、行标签垂直居中——量的是
            #    布局而不是写死 32，窄态单选折行时不会裁字。
            frame_lw = ui.layoutWidget_26
            frame_layout = ui.horizontalLayout_112
            frame_layout.invalidate()
            frame_layout.activate()
            frame_h = max(frame_layout.sizeHint().height(), frame_lw.sizeHint().height())
            frame_lw.setGeometry(frame_lw.x(), 0, frame_lw.width(), frame_h)
            frame_tag = ui.label_332
            frame_tag.move(frame_tag.x(), max((frame_h - frame_tag.height()) // 2, 0))
            note.move(note.x(), lw.y() + grid_h + self._DEFN_GRID_GAP)
            # 「向下移动一行」= 在说明与分辨率行之间插一整行文字高。label_358
            # （指命名时在番号后添加4K…）在 frame_6 下方，跟着 frame 一起下移，
            # 用户第二条要求自动满足。
            note_gap = self._DEFN_NOTE_GAP
            if note_gap < 0:
                note_gap = QFontMetrics(note.font()).lineSpacing()
            frame.setGeometry(frame.x(), note.y() + note_h + note_gap, frame.width(), frame_h)
            row_y = frame.y() + frame.height()
            # 「末端添加4K字符」行同样下移一行，行高取 frame_6 内 radio 的实测行高。
            frame_gap = self._DEFN_FRAME_GAP
            if frame_gap < 0:
                frame_gap = QFontMetrics(ui.radioButton_videosize_video.font()).lineSpacing()
            row_y += frame_gap
            row_label.move(row_label.x(), row_y)
            check_f.move(check_f.x(), row_y + self._DEFN_ROW_CHECK_DY)
            check_n.move(check_n.x(), row_y + self._DEFN_ROW_CHECK_DY)
            tail_gap = self._DEFN_TAIL_GAP
            if tail_gap < 0:
                tail_gap = QFontMetrics(tail.font()).lineSpacing()
            tail_y = row_y + max(row_h, check_f.height(), check_n.height()) + tail_gap
            tail.move(tail.x(), tail_y)
            box_h = tail_y + tail.height() + self._DEFN_BOX_BOT_PAD
            box.setGeometry(box.x(), box.y(), box.width(), box_h)
            follower.move(follower.x(), box.y() + box_h + self._DEFN_GROUP_GAP)

            # 3) 宽幅登记表里存的是设计几何，同步宽度时会按登记值复位这些控件，
            #    这里把登记的 y/h 一并更新（设计宽度原样保留，只换 y/h）。
            registry = getattr(ui.scrollAreaWidgetContents_mingming, "_wide_children_design", None)
            for entry in registry or ():
                if entry.widget is box:
                    ex, ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, ey, ew, box_h)
                    continue
                for item in entry.inner:
                    if item.widget is lw:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw.y(), iw, grid_h)
                    elif item.widget is note:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, note.y(), iw, note_h)
                    elif item.widget is frame:
                        ix, _iy, iw, _ih = item.geometry
                        # 高度换成实测的 frame_h：宽幅同步会按登记高度复位 frame_6，
                        # 留设计 46 的话每次缩放都会把收紧效果又撑回去 14px。
                        item.geometry = (ix, frame.y(), iw, frame_h)
                    elif item.widget is tail:
                        ix, _iy, iw, ih = item.geometry
                        item.geometry = (ix, tail.y(), iw, ih)

            scroll = getattr(ui, "scrollArea_7", None)
            if scroll is not None:
                scroll.sync_content_min_height()
        finally:
            self._defn_resyncing = False
