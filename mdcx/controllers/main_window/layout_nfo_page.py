"""设置页 NFO 区域(冒号对齐 + 8 列控制器 + 字段提示)的布局。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import (
    QEventLoop,
    QTimer,
)
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QSpacerItem,
)


class LayoutNfoPageMixin:
    # 设置-NFO「写入NFO的字段」组：col0 左标签（130px Fixed 右对齐），冒号在右缘
    _NFO_COLON_LABELS = (
        "label_163",  # 标题：
        "label_384",  # 简介：
        "label_385",  # 发行日期：
        "label_392",  # 国家/分级：
        "label_391",  # 年份/时长/想看：
        "label_390",  # 评分：
        "label_386",  # 演员/导演：
        "label_208",  # 系列/标签：
        "label_334",  # 风格/合集：
        "label_388",  # 片商/发行商：
        "label_150",  # 封面/背景/预告片：
    )

    def _sync_nfo_colon_align(self) -> None:
        """设置-NFO：左标签冒号左移与组标题冒号严格上下对齐，窄态宽态一致。

        用户截图：标题：/简介：/发行日期：/国家/分级：/年份/时长/想看：/
        评分：/演员/导演：/系列/标签：/风格/合集：/片商/发行商：/封面/背景/
        预告片：等 11 个左标签缩进在右，要求整体左移、冒号与组标题
        「写入NFO的字段：」的冒号严格对齐，右侧控件跟随、间距不变，
        最小化与最大化都要对齐。
        根因：col0 标签 130px Fixed 右对齐，冒号恒在 col0 右缘
        （layoutWidget_10.x + 130，实测窄态 gb 坐标 x=150）；组标题冒号
        在组左缘 + 标题字形宽（实测 x≈103）。两者差约 42px，而内容区左
        空气只有 layoutWidget_10.x ≈ 20px（gridLayout_40 margin 全 0，
        已离屏实测），固定 margin 杠杆不够；且标题字形宽随字体变，
        魔法数字必随字体漂移（见右列对齐 b14 教训）。
        做法（像素标定 + 纯函数位移，双向幂等）：_calibrate_nfo_colons
        对组盒做一次渲染扫描，标定组标题冒号 x 与行标签右 pad（字形右缘
        与矩形右缘差，同字同号两边抵消的余量），按字体样式 key 缓存，
        稳态零渲染开销；每遍用「当前位 + 位移」把 layoutWidget_10 连 x
        带宽整体左移（右缘保持，col1 右侧不动，col0/col1 间距全保留），
        防裁字守卫只允许裁 col0 左缘空白（右对齐标签文本左缘禁区，活测
        最长文本），最长标签宽于组标题冒号位置时（如当前）钳住取免裁字
        最大位移、接受残差（预算证明严格对齐结构性无解）。只碰容器几何，不碰 y 与行。
        在 _sync_page_layouts 最先调用（右列/thirds、标题/发行日期两同步
        都是相对位置比较，整体平移对其透明）。休眠页跳过，切 tab 下一拍
        单发补齐（同 b14/b17 钩子）。
        """
        ui = self.Ui
        gb = ui.groupBox_81
        if not gb.isVisibleTo(self):
            return
        lw = ui.layoutWidget_10
        lbs = [getattr(ui, n) for n in self._NFO_COLON_LABELS]
        ref = lbs[0]  # 标题：，col0 右对齐代表行
        key = (gb.font().toString(), ref.font().toString(), type(gb.style()).__name__)
        cal = self._nfo_colon_cal
        if cal is None or cal[0] != key:
            fresh = self._calibrate_nfo_colons(gb, lw, lbs)
            if fresh is None:
                return
            self._nfo_colon_cal = (key,) + fresh
            cal = self._nfo_colon_cal
        _, title_colon, row_pad = cal
        dm = title_colon - (lw.x() + ref.x() + ref.width() - row_pad)
        new_x = lw.x() + dm
        # 防裁字：文本左缘（gb 坐标）不许进负区
        fm = ref.fontMetrics()
        widths = [fm.horizontalAdvance(getattr(ui, n).text()) for n in self._NFO_COLON_LABELS]
        fitting = [w for w in widths if w <= ref.width()]
        min_x = (
            (max(fitting) - ref.width()) if fitting else -1000000
        )  # 守卫生于 advance 空间：+row_pad 版曾稳定触发 fail-fast 崩溃，故保持本式；残余 advance 缺口为 bearings，ink 由回归测试验证放得下
        if new_x < min_x:
            new_x = min_x
        right = lw.x() + lw.width()
        new_w = right - new_x
        if new_x == lw.x() and new_w == lw.width():
            return
        lw.setGeometry(new_x, lw.y(), new_w, lw.height())
        grid = lw.layout()
        if grid is not None:
            grid.invalidate()
            grid.activate()

    @staticmethod
    def _calibrate_nfo_colons(gb, lw, labels):
        """渲染扫描标定 (组标题冒号x, 行标签右pad)，失败返回 None（调用方跳过）。

        标题行（组顶 y 2..17）从左向右找第一个 ≥15px 的墨点间隙：
        有注释同行时间隙后是注释，无注释时标题冒号即带内最右墨点，
        两种版式都成立。行标签文本恒以中文冒号结尾，从矩形右缘向左
        首个墨点即冒号右缘；11 个取中位数抗个别渲染抖动。阈值相对背景
        取 60，暗黑主题同样成立。纵坐标按 dpr 换算，返回逻辑像素。
        """
        try:
            pix = gb.grab()
            img = pix.toImage().convertToFormat(QImage.Format.Format_RGB32)
        except Exception:
            return None
        wpx, hpx = img.width(), img.height()
        if wpx <= 0 or hpx <= 0:
            return None
        dpr = pix.devicePixelRatio() or 1.0

        def lum(x, y):
            c = img.pixel(int(x), int(y))
            return (((c >> 16) & 0xFF) * 3 + ((c >> 8) & 0xFF) * 6 + (c & 0xFF)) / 9.0

        bg = lum(wpx / 2, hpx - 4 * dpr)

        def ink(x, y):
            return abs(lum(x, y) - bg) > 60

        # 组标题冒号：y 2..17 带，x 0..400 的墨点 runs
        y0, y1 = int(2 * dpr), min(int(17 * dpr), hpx)
        x_max = min(int(400 * dpr), wpx)
        runs = []
        cur = None
        for x in range(0, x_max):
            hit = any(ink(x, y) for y in range(y0, y1))
            if hit:
                if cur is None:
                    cur = [x, x]
                else:
                    cur[1] = x
            elif cur is not None:
                runs.append(tuple(cur))
                cur = None
        if cur is not None:
            runs.append(tuple(cur))
        if not runs:
            return None
        title_colon = runs[-1][1]
        for i, (_a, b) in enumerate(runs):
            if b > 60 * dpr and i + 1 < len(runs) and runs[i + 1][0] - b >= 15 * dpr:
                title_colon = b
                break
        title_colon = title_colon / dpr
        if not 0 < title_colon < 400:
            return None
        # 11 行标签冒号：各带内从矩形右缘向左首个墨点，取中位数
        found = []
        for lb in labels:
            try:
                top = lb.mapTo(gb, lb.rect().topLeft())
                right = top.x() + lb.rect().width()
                yy0 = max(0, int(top.y() * dpr))
                yy1 = min(hpx, int((top.y() + lb.rect().height()) * dpr))
                xx = int(right * dpr)
                stop = (right - 40) * dpr
                while xx > stop:
                    if any(ink(xx, y) for y in range(yy0, yy1)):
                        found.append(xx / dpr)
                        break
                    xx -= 1
            except Exception:
                continue
        if len(found) < 6:
            return None
        found.sort()
        median = found[len(found) // 2]
        ref = labels[0]
        row_pad = (lw.x() + ref.x() + ref.width()) - median
        if not 0 <= row_pad <= 40:
            return None
        return (title_colon, row_pad)

    def _sync_nfo_page_align(self) -> None:
        """设置-NFO：把八个列对齐控制器整条重跑一遍（纯几何刷新入口）。

        用途只有一个：挂在 NFO 滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「对齐」在同一个
        事件里做完。起因是最大化时的可见跳动（与演员页同病、方向相反）：

          离屏实测（探针 probe_2tasks.py，scrollArea_13 拉伸事件序列）
            wide   colMinW1=0    criticX=444  customX=492   ← 拉伸前，条件不成立
            rca    (0,444,492) → (0,444,492)               ← 量到旧几何，留空
            wide   colMinW1=0    criticX=918  customX=498   ← 拉伸后已发散
            hook   （原本是 no-op：本页没挂钩子）            ← 错过的补救机会
            rca    (0,950,498) → (675,498,498)             ← 下一拍才补上 → 肉眼可见的右跳

        _sync_nfo_right_column_align 的判据是 `critic.x() > custom.x()`，而
        CustomScrollArea 是在主窗口 resizeEvent **之后**才把自己和内部子项拉到
        终态的，所以主窗口那一拍量到的必然是拉伸前的几何。挂上钩子后判据在拉伸
        后的几何上求值，一拍即到位，中间态没有机会被绘制。
        八个控制器都是纯函数、双向幂等（各自 docstring 已声明），重复调用安全；
        休眠页直接返回（切 tab 的 showEvent 与 beats 会补齐）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or not ui.groupBox_81.isVisibleTo(self):
            return
        self._sync_nfo_colon_align()
        self._sync_nfo_right_column_align()
        self._sync_nfo_title_plot_align()
        self._sync_nfo_row_align()
        self._sync_nfo_tail_align()
        self._sync_nfo_set_align()
        self._sync_nfo_studio_row_align()
        self._sync_nfo_field_tips()
        self._sync_nfo_target_column_align()

    def _sync_nfo_right_column_align(self) -> None:
        """设置-NFO：宽视口下右列左对齐到 thirds；窄视口下右列右移到首播日期列。

        用户截图（最大化）：影评人评分（criticrating）/导演（director）/演员写入
        TMDB ID/标签（tag）被推到自定义分级（customrating）/想看人数（votes）
        右侧两百多 px，要求四者左移与 thirds 严格上下对齐、其余不动、窄态不变。
        根因：gridLayout_66 的 columnstretch=(1,0) 让 C0 吃掉全部横向 surplus，
        C1.x 以斜率 1 随列宽右移；而 country/mpaa/customrating、year/runtime/wanted
        两行 HBox 无弹簧、三项均分 surplus，thirds.x 以斜率 2/3 右移。两者只在
        默认宽度附近相交（约 787px），窗口加宽后 C1 持续超越 thirds；纯拉伸配比
        定不住常数项（hints 差约 48px），故用列最小宽做自适应钳制。
        做法（纯函数、双向幂等）：先把 C0/C1 四格钉宽与 C0/C1 列最小宽全部复位
        （C0 的 series 与 C1 的 tag 设计最小宽 150，其余设计最小宽 0，最大宽默认）
        →重排→量自然位置；宽态仅当 critic.x > custom.x（发散态）时设 C1 列最小宽
        = 列宽 - custom.x + score.x，把 C1 左缘精确钉到 thirds（导演/TMDB/标签同属
        C1，一并归位）；窄态仅当 critic.x < pr.x（偏左态）时把 C0 四格（score/
        actor/all_actor/series）min=max 钉到 pr.x-score.x-间距、把 C1 四格
        （critic/director/tmdb/tag）min=max 钉到列宽-钉宽-间距，在总宽不变下把
        C1 左缘精确钉到首播日期（premiered）列（导演/TMDB/标签同属 C1 一并归位；
        原简介（originalplot）经标题控制器已在首播列时即同时对齐）。任一钉宽低于
        60 地板即整单放弃（防裁字，小宽态 defer）；已对齐时零残留（自然位不动）。
        各控件同属 layoutWidget_10，.x() 同一坐标系直接可比；只碰列宽，不碰 y
        与其它行（高不变→行高不变→无上下移动）。premiered（premiered）与原简介
        只读不动；宽态（目标列对齐生效中）直接返回，最大化行为逐像素不变。
        """
        ui = self.Ui
        grid = ui.gridLayout_66
        score = ui.checkBox_nfo_score
        critic = ui.checkBox_nfo_criticrating
        custom = ui.checkBox_nfo_customrating
        pr = ui.checkBox_nfo_premiered
        if self._nfo_target_col_active:
            # 目标列对齐生效中：C1 列最小宽归它所有，直接返回。它生效时
            # critic 与 custom 同在锚 B 列、判据恒为假，本来也是 no-op；
            # 不返回的话本方法开头的清零会把它的钉宽洗掉（_sync_page_layouts
            # 第 4014 行每遍都调本方法，且跑在钩子链之后、专抢最后一写）。
            # 窄态残留的 C0/C1 四格钉宽仍需清掉（宽态改由列最小宽接管），
            # 列最小宽一律不动。
            for cb in (score, ui.checkBox_nfo_actor, ui.checkBox_nfo_all_actor):
                cb.setMinimumWidth(0)
                cb.setMaximumWidth(16777215)
            ui.checkBox_nfo_series.setMinimumWidth(150)
            ui.checkBox_nfo_series.setMaximumWidth(16777215)
            for cb in (critic, ui.checkBox_nfo_director, ui.checkBox_nfo_actor_tmdbid):
                cb.setMinimumWidth(0)
                cb.setMaximumWidth(16777215)
            ui.checkBox_nfo_tag.setMinimumWidth(150)
            ui.checkBox_nfo_tag.setMaximumWidth(16777215)
            return
        c0_cells = (
            score,
            ui.checkBox_nfo_actor,
            ui.checkBox_nfo_all_actor,
            ui.checkBox_nfo_series,
        )
        c1_cells = (
            critic,
            ui.checkBox_nfo_director,
            ui.checkBox_nfo_actor_tmdbid,
            ui.checkBox_nfo_tag,
        )
        for cb in (score, ui.checkBox_nfo_actor, ui.checkBox_nfo_all_actor):
            cb.setMinimumWidth(0)
            cb.setMaximumWidth(16777215)
        ui.checkBox_nfo_series.setMinimumWidth(150)
        ui.checkBox_nfo_series.setMaximumWidth(16777215)
        for cb in (critic, ui.checkBox_nfo_director, ui.checkBox_nfo_actor_tmdbid):
            cb.setMinimumWidth(0)
            cb.setMaximumWidth(16777215)
        ui.checkBox_nfo_tag.setMinimumWidth(150)
        ui.checkBox_nfo_tag.setMaximumWidth(16777215)
        grid.setColumnMinimumWidth(0, 0)
        grid.setColumnMinimumWidth(1, 0)
        # 防御性刷新：直接调用时若外层有 pending 布局请求，先落定再测量
        # （内层激活只排布 cell 内部，不管 cell 本身在哪）。钩子时序问题另由
        # _queue_nfo_post_cascade_sync 解决，此处只保测量新鲜。
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        grid.invalidate()
        grid.activate()
        if critic.x() > custom.x():
            col_w = grid.geometry().width()
            grid.setColumnMinimumWidth(1, max(col_w - custom.x() + score.x(), 0))
            grid.invalidate()
            grid.activate()
            return
        if critic.x() < pr.x():
            spacing = grid.spacing()
            need_c0 = pr.x() - score.x() - spacing
            need_c1 = grid.geometry().width() - need_c0 - spacing
            if need_c0 >= 60 and need_c1 >= 60:
                for _ in range(3):
                    for cb in c0_cells:
                        cb.setMinimumWidth(need_c0)
                        cb.setMaximumWidth(need_c0)
                    for cb in c1_cells:
                        cb.setMinimumWidth(need_c1)
                        cb.setMaximumWidth(need_c1)
                    grid.invalidate()
                    grid.activate()
                    if outer is not None:
                        outer.activate()
                    if critic.x() == pr.x():
                        break
                    # 父宽后续生长时重算（同 row_align 有界迭代到不动点）
                    need_c0 = pr.x() - score.x() - spacing
                    need_c1 = grid.geometry().width() - need_c0 - spacing
                    if need_c0 < 60 or need_c1 < 60:
                        break

    def _sync_nfo_title_plot_align(self) -> None:
        """设置-NFO：原标题/简介/原简介左对齐到发行日期列，窄态宽态一致。

        用户截图：最大化后原标题（originaltitle）应与发行日期（relasedate）
        上下对齐、简介（plot）与 relasedate 对齐、原简介（originalplot）
        与上映日期（premiered）对齐，relasedate/premiered 不动；后用户要求
        最小化（窄视口）同样对齐：ot/plot 对齐 rd.x，opl 对齐 pr.x，
        relasedate/premiered 位置不变、最大化行为不变、任何控件都不上下移动。
        根因：发行三项（release/relasedate/premiered）为 Minimum 策略，
        视口加宽时各自吞掉 extra/3；而原标题/简介行的 150 前缀把后继项 x
        冻结在窄态位置。纯拉伸定不住三者的相对位置，故用前缀最小宽做自适
        应钳制。
        做法（纯函数、双向幂等、单遍精确）：先把 sorttitle/outline/plot 三
        前缀恢复最小宽 150→重排→量自然位置；再设三前缀最小宽为「当前宽+
        位移」（位移 g0=max(rd.x-ot.x,0)，g1=max(rd.x-plot.x,0)，
        g2=max(pr.x-opl.x-g1,0)，opl 永不超过 pr），把后继项精确钉到
        发行日期列。公式只用实测相对位移，与视口宽窄无关，
        窄态宽态同一套：窄态 d≈+29 小步右移，宽态 d 大步右移；已对齐时位
        移为 0 天然无操作。用当前宽而非 150 做基址：前缀 hint 随字体
        变化（如测试字体下 sorttitle hint 为 192），基址 150 会系统性欠
        299-257=42px；当前宽基址与样式无关且天然幂等。复选框加宽只延长点
        击区，视觉无变化。relasedate/premiered 不动：三行是 gridLayout_40
        里三个独立 HBox（135/136/137），加宽 135/136 的前缀只推本行后继项，
        137 行的 rd/pr 几何不受影响。各控件同属 layoutWidget_10，.x() 同一
        坐标系直接可比；只碰前缀列宽，不碰 y 与其它行（高不变→行高不变→
        无上下移动）。休眠页（不可见）跳过，由切 tab 下一拍单发
        与切回设置页排队触发补齐。
        """
        ui = self.Ui
        st = ui.checkBox_nfo_sorttitle
        ot = ui.checkBox_nfo_originaltitle
        outline = ui.checkBox_nfo_outline
        plot = ui.checkBox_nfo_plot
        opl = ui.checkBox_nfo_originalplot
        rd = ui.checkBox_nfo_relasedate
        pr = ui.checkBox_nfo_premiered
        if not ot.isVisibleTo(self):
            return
        rows = (ui.horizontalLayout_135, ui.horizontalLayout_136, ui.horizontalLayout_137)
        for cb in (st, outline, plot):
            cb.setMinimumWidth(150)
        for row in rows:
            row.invalidate()
            row.activate()
        # 防御性刷新：同 thirds，行位置由外层分配，先落定再读 ot/rd.x。
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 窄态宽态同一套公式：位移全是实测相对值，与视口宽窄无关；
        # 窄态自然 d≈+29 小步右移，宽态 d 大步右移，已对齐时 d=0 无操作。
        # 只取正部 + opl 上限钳制：过窄窗口布局被压缩时 d 可能为负（如 900
        # 宽下 rd 被挤到 ot 左边），此时“向右移+参照不动”几何无解——负位移
        # 钳零（前缀不动），且 opl 永不超过 pr（不过调）；宽态 d 全为正，
        # 与旧式 d2=pr.x-opl.x-d1 逐值相等，行为不变。
        d0 = rd.x() - ot.x()
        d1 = rd.x() - plot.x()
        g0 = max(d0, 0)
        g1 = max(d1, 0)
        g2 = max(pr.x() - opl.x() - g1, 0)
        st.setMinimumWidth(max(st.width() + g0, 150))
        outline.setMinimumWidth(max(outline.width() + g1, 150))
        plot.setMinimumWidth(max(plot.width() + g2, 150))
        for row in rows:
            row.invalidate()
            row.activate()

    def _sync_nfo_row_align(self) -> None:
        """设置-NFO：窄态下分级信息（mpaa）/时长（runtime）左对齐到发行日期列。

        用户截图（最小化）：mpaa 框偏左、runtime 框偏右（生产字体约 30/60px），
        最大化天然对齐。只许水平移动，宽态不动。
        根因：三行（h137 发行/h141 国家/h40 年份）皆左堆积无弹簧的 Minimum 行，
        同一起点 X0。有余量时三行均分天然对齐；容器窄到装不下 hint 总宽时，
        Minimum 项被挤到 hint 以下、各行按各自文本乱挤（country 短→mpaa 落下；
        year 比 release 抗挤→runtime 被顶出）。离屏实测（测试字体 850 宽）：
        rd=257、mpaa=252（左 5）、runtime=268（右 11），与用户症状同向。
        挤压分配随宽度混沌翻转（850 宽 settled 态 mpaa 反超 +2、750 宽
        runtime 自然偏左 -13），单边修法顾此失彼，故四方向条件钉死。
        pin 目标必须锚定参照行 h137 实测值：rd.width() 是 relasedate 自身
        宽度，挤压区里比 release 宽出一截，拿它当目标会系统性钉错位
        （mpaa 稳定 +2、第二遍也不自愈）；正确目标 = rd.x - 前项.x -
        h137 实测间距，min=max 一次钉死，有界迭代 3 遍兜 ±1px 取整漂移
        （60px 地板保可读）。无条件全钉死不可行：宽态 mid-cascade 误测
        pin<share 会把 country 钉小、custom 左顶 10px（thirds 单跑即挂）；
        条件式只在错位方向触发，复位保证误触发下一拍自愈。有余量时条件
        皆不触发，宽态零改动。复选框只改列宽，高不变→行高不变→无上下移动。
        休眠页跳过，由切页钩子补齐。
        """
        ui = self.Ui
        country = ui.checkBox_nfo_country
        mpaa = ui.checkBox_nfo_mpaa
        year = ui.checkBox_nfo_year
        runtime = ui.checkBox_nfo_runtime
        release = ui.checkBox_nfo_release
        rd = ui.checkBox_nfo_relasedate
        for cb in (rd, mpaa, runtime):
            if not cb.isVisibleTo(self):
                return
        rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)
        # 重置上一轮约束，还原自然位（设计最小宽 0，最大宽默认）。
        country.setMinimumWidth(0)
        country.setMaximumWidth(16777215)
        year.setMinimumWidth(0)
        year.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 条件对称钉死（有界迭代到不动点）：只修实测到错位的方向。
        # pin 目标必须锚定参照行 h137 的实测值——rd.width() 是 relasedate
        # 自身宽度，挤压区里它比 release 宽出一截（850 宽下 133 vs 115，
        # 长文本抗挤），拿它当 country/year 的目标会系统性钉错位
        # （mpaa 稳定 +2、第二遍也不自愈：cap 不 binding）。
        # 正确目标 = rd.x - 前项.x - h137 实测间距（release 同行、X0 同系，
        # min=max 一次钉死）；单遍后重排可能再漂 ±1px（挤压整数取整），
        # 故有界重测 3 遍。参照行 h137 本轮内不受 pins 影响（只动 h141/h40
        # 的前项），目标稳定，迭代收敛。无条件全钉死仍禁止（宽态
        # mid-cascade 误测把 custom 左顶的教训见上）；复位保证误触发自愈。
        for _ in range(3):
            gap_ref = rd.x() - release.x() - release.width()
            t_country = rd.x() - country.x() - gap_ref
            t_year = rd.x() - year.x() - gap_ref
            if mpaa.x() == rd.x() and runtime.x() == rd.x():
                break
            if mpaa.x() != rd.x():
                country.setMinimumWidth(max(t_country, 60))
                country.setMaximumWidth(max(t_country, 60))
            if runtime.x() != rd.x():
                year.setMinimumWidth(max(t_year, 60))
                year.setMaximumWidth(max(t_year, 60))
            for row in rows:
                row.invalidate()
                row.activate()
            if outer is not None:
                outer.activate()

    def _sync_nfo_tail_align(self) -> None:
        """设置-NFO：窄态下末项 customrating/votes 右对齐到 premiered，宽态不动。

        用户需求：“nfo 页面最小化时将自定义（customrating）、想看人数
        （votes）向右移动到与发行日期（premiered）严格上下对齐的位置，
        发行日期（premiered）保持不变，最大化的页面保持不变，只能左右
        移动不能上下移动”。
        根因：_sync_nfo_row_align 只钉了三行的前两项（country/year →
        mpaa/runtime 对齐 rd）；窄态 800~900 挤压带里，第二项自身宽度
        也会漂（850 宽下 mpaa.w=119 vs relasedate.w=133，长文本抗挤），
        导致末项 custom/votes 落在 pr 左边（800 宽 custom 偏左 15、
        850 宽偏左 14；votes 在 850 偏左 2）。700/750 及 900+ 均天然
        对齐，1900 宽态全 0。
        做法（条件对称式，有界迭代到不动点，仿 row_align）：每遍先把
        mpaa/runtime 的约束复位（最小宽 0、最大宽默认），重排落定后实测；
        只修错位的方向——custom.x != pr.x 则把 mpaa 钉到 rd 实测宽度
        （min=max 一次钉死，60 地板），votes.x != pr.x 则把 runtime 钉到
        rd 实测宽度；对齐即停，最多 3 遍（挤压整数取整漂移）。
        目标为什么是 rd.width()（与 b34 教训不矛盾）：前项已被 row_align
        钉到与 release 等宽（同一起点 X0、同间距），故 custom.x == pr.x
        当且仅当 mpaa.w == rd.w（同序位等宽）；实测 850：钉 133 后
        custom.x = 136+115+6+133+6 = 396 = pr.x 精确成立。
        前项 country/year 与参照 rd/pr 本方法只读不动；只改列宽，不碰 y；
        宽态修正量恒 0（自然对齐→条件跳过→约束零残留）。休眠页跳过，
        复用 tab/切页双拍钩子，无新钩子。
        """
        ui = self.Ui
        mpaa = ui.checkBox_nfo_mpaa
        custom = ui.checkBox_nfo_customrating
        runtime = ui.checkBox_nfo_runtime
        votes = ui.checkBox_nfo_wanted
        rd = ui.checkBox_nfo_relasedate
        pr = ui.checkBox_nfo_premiered
        for cb in (pr, custom, votes):
            if not cb.isVisibleTo(self):
                return
        rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)
        # 重置上一轮约束，还原自然位（设计最小宽 0，最大宽默认）。
        mpaa.setMinimumWidth(0)
        mpaa.setMaximumWidth(16777215)
        runtime.setMinimumWidth(0)
        runtime.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 条件对称钉死（有界迭代到不动点）：只修实测到错位的方向。
        # row_align 在本方法之前已跑完，前项 country/year 被钉死，
        # 故本轮内 mpaa/runtime 的 pin 只动末项位置，前两项不受影响；
        # 参照行 h137 不受 pins 影响，目标稳定，迭代收敛。
        for _ in range(3):
            t_second = rd.width()
            if custom.x() == pr.x() and votes.x() == pr.x():
                break
            if custom.x() != pr.x():
                mpaa.setMinimumWidth(max(t_second, 60))
                mpaa.setMaximumWidth(max(t_second, 60))
            if votes.x() != pr.x():
                runtime.setMinimumWidth(max(t_second, 60))
                runtime.setMaximumWidth(max(t_second, 60))
            for row in rows:
                row.invalidate()
                row.activate()
            if outer is not None:
                outer.activate()

    def _sync_nfo_set_align(self) -> None:
        """设置-NFO：宽态下合集两项左对齐到片商/发行商列，窄态保持不动。

        用户需求：最大化时合集（使用演员字段）与片商（maker）严格上下对齐、
        合集（使用系列字段）与发行商（publisher）严格上下对齐；最小化时布局
        不动；只能左右移动。
        根因：风格行 h114 是 3 等分、片商行 h138 是 4 等分（皆左堆积无弹簧、
        同一起点、无自定义间距），有余量时均分：d_aset=W_cell/12、
        d_set=W_cell/6，随宽度线性漂移（离屏实测 1000→+41/+82、
        1900→+116/+232，逐值吻合）。
        做法（条件左移单向、宽态门控）：宽态门 extra=viewport-796>200
        （extra 按 NFO 内容设计宽 796 计算；滚动区设计宽已改为 800，不用 isMaximized，
        因离屏不可测；1400 中宽 extra≈334 同样开门，属宽向无害）。
        关门（窄态）时复位 genre/actor_set 约束并直接返回，窄态逐像素不动。
        开门后 3 遍有界迭代（两钉串行：先钉 genre、重排后用新鲜位置再算
        actor_set 钉）：只在实测到偏右时封顶前项
        （cap=参照.x-前项.x-行内实测间距，60 地板），studio/maker/
        publisher/label 与 y 全不动；参照行 h138 不受 pins 影响，目标稳定。
        休眠页（不可见）跳过，由切 tab/切页下一拍单发触发补齐。
        """
        ui = self.Ui
        genre = ui.checkBox_nfo_genre
        actor_set = ui.checkBox_nfo_actor_set
        nfo_set = ui.checkBox_nfo_set
        maker = ui.checkBox_nfo_maker
        publisher = ui.checkBox_nfo_publisher
        if not actor_set.isVisibleTo(self):
            return
        # 宽态门：关门时复位并返回，窄态布局逐像素不动。
        viewport_w = ui.scrollArea_13.viewport().width()
        rows = (ui.horizontalLayout_114, ui.horizontalLayout_138)
        outer = ui.gridLayout_40
        genre.setMinimumWidth(0)
        genre.setMaximumWidth(16777215)
        actor_set.setMinimumWidth(0)
        actor_set.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        if outer is not None:
            outer.activate()
        if viewport_w - 796 <= 200:
            return
        gap = ui.horizontalLayout_114.spacing()
        # 条件左移（有界迭代到不动点）：两钉必须串行——genre 钉会连带左移
        # 整块 [actor_set, set]，actor_set 钉必须用 genre 钉生效并重排后的
        # 新鲜位置计算，否则同一快照下重复扣除 genre 修正量（1900 宽实测
        # overshoot 116px：set 落到 publisher 左边）。
        for _ in range(3):
            if actor_set.x() == maker.x() and nfo_set.x() == publisher.x():
                break
            if actor_set.x() > maker.x():
                cap = maker.x() - genre.x() - gap
                if cap < genre.width() and cap >= 60:
                    genre.setMaximumWidth(cap)
                    for row in rows:
                        row.invalidate()
                        row.activate()
                    if outer is not None:
                        outer.activate()
            if nfo_set.x() > publisher.x():
                cap2 = publisher.x() - actor_set.x() - gap
                if cap2 < actor_set.width() and cap2 >= 60:
                    actor_set.setMaximumWidth(cap2)
                    for row in rows:
                        row.invalidate()
                        row.activate()
                    if outer is not None:
                        outer.activate()

    def _sync_nfo_studio_row_align(self) -> None:
        """设置-NFO：窄态下片商行后三项对齐到标签两行，宽态保持不动。

        用户需求（最小化）：片商（maker）向右移动到与系列
        （`checkBox_tag_series`）严格上下对齐、系列不动；发行商
        （publisher）向右移动到与分辨率（`checkBox_tag_definition`）
        严格上下对齐、分辨率不动；发行商（label）向左移动到与中文字幕
        （`checkBox_tag_cnword`）严格上下对齐、中文字幕不动。最大化时
        页面布局、组件、控件、提示词等全部保持不变；只许左右移动。
        根因：标签两行 h37/h91 与片商行 h138 皆 4 等分左堆积无弹簧、
        同一起点、无自定义间距（间距 6），有余量时均分天然对齐；
        容器窄到装不下 h138 的 hint 总宽时（publisher hint 最长，离屏
        测试字体 122），h138 按各自文本乱挤而 h37/h91 仍均分：离屏
        900 宽实测 maker=246 vs 系列=251（左 5）、publisher=357 vs
        分辨率=366（左 9）、label=485 vs 中文字幕=480（右 5），与用户
        症状同向；1000/1089/1400/1900 宽均天然对齐。
        做法（窄态门控、单快照增量、四钉原子）：宽态门 extra>200 即复位
        studio/maker/publisher/label 约束（最小宽 0、最大宽默认）后直接返回，
        宽态逐像素不动（门限与 _sync_nfo_set_align 同源互补：
        extra 按 NFO 内容设计宽 796 计算，不用 isMaximized，因离屏不可测；
        1089 窄态 extra≈23 关门排布，1400/1900 宽态开门复位）。
        关门后 3 遍有界迭代，每遍从同一快照算出四个增量、原子应用：
        d1=系列.x-maker.x（整条尾巴的位移）→ studio 钉现宽+d1；
        d2=分辨率.x-(publisher.x+d1)（maker 矫正量）→ maker 钉现宽+d2；
        d3=中文字幕.x-(label.x+d1+d2) → publisher 钉现宽+d3；
        label 钉现宽-d1-d2-d3（把前三钉吐出/吃进的宽度原数吸收，行总宽
        恒不变）。生产字体下 d1/d2 为正（加宽右移）、d3 为负（封顶左移），
        实现按双向对称写（row_align 同款：挤压分配随字体混沌翻转，离屏曾测得
        maker 反超 +1，单边修法顾此失彼）；四钉任一低于 60 地板即整单放弃
        （防裁字）。label 钉只改末项自身宽度（label.x 只取决于前三钉），
        不移动任何控件，只延长点击区。series/definition/cnword 与 y 全不动；
        只碰列宽，高不变故无上下移动。休眠页（不可见）跳过，由切 tab/切页
        下一拍补齐。
        教训（离屏 900 宽实测）：初版三钉串行（钉完 studio 重排再量 maker 钉，
        label 不钉）在 conftest 字体下稳定剩 1px（pub=340 vs 341、lbl=442 vs
        443）且永远自愈不了——三钉总宽 405 超出行宽 403，QBoxLayout 把溢出的
        2px 吃进项间隙（gap 6→5），公式算对也落不对；且 cap 重算恒等于现宽
        （SKIP 自锁）。四钉原子则行总宽守恒（增量相消），无新挤压、无级联
        失真，一遍即中（同环境 238/341/443 精确成立）；label 不钉的 V3 对照组
        仍差 1px，反证 label 钉必要。与 set_align 相容：两门互补（窄/宽各开
        一门），窄态 set 复位返回、宽态本方法复位返回，maker/publisher 不会被
        两方同拍争夺。
        """
        ui = self.Ui
        studio = ui.checkBox_nfo_studio
        maker = ui.checkBox_nfo_maker
        publisher = ui.checkBox_nfo_publisher
        label = ui.checkBox_nfo_label
        series = ui.checkBox_tag_series
        definition = ui.checkBox_tag_definition
        cnword = ui.checkBox_tag_cnword
        if not maker.isVisibleTo(self):
            return
        rows = (ui.horizontalLayout_37, ui.horizontalLayout_91, ui.horizontalLayout_138)
        outer = ui.gridLayout_40
        studio.setMinimumWidth(0)
        studio.setMaximumWidth(16777215)
        maker.setMinimumWidth(0)
        maker.setMaximumWidth(16777215)
        publisher.setMinimumWidth(0)
        publisher.setMaximumWidth(16777215)
        label.setMinimumWidth(0)
        label.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        if outer is not None:
            outer.activate()
        if self._scroll_stretch_extra(ui.scrollArea_13) > 200:
            return
        # 四钉原子：同一快照算增量、一次全应用，行总宽守恒（增量相消），
        # 无级联失真、无新挤压；整单地板（任一 <60 即本遍放弃）。
        for _ in range(3):
            if maker.x() == series.x() and publisher.x() == definition.x() and label.x() == cnword.x():
                break
            d1 = series.x() - maker.x()
            d2 = definition.x() - (publisher.x() + d1)
            d3 = cnword.x() - (label.x() + d1 + d2)
            cap_s = studio.width() + d1
            cap_m = maker.width() + d2
            cap_p = publisher.width() + d3
            cap_l = label.width() - d1 - d2 - d3
            if min(cap_s, cap_m, cap_p, cap_l) < 60:
                break
            if (
                cap_s == studio.width()
                and cap_m == maker.width()
                and cap_p == publisher.width()
                and cap_l == label.width()
            ):
                break
            studio.setMinimumWidth(cap_s)
            studio.setMaximumWidth(cap_s)
            maker.setMinimumWidth(cap_m)
            maker.setMaximumWidth(cap_m)
            publisher.setMinimumWidth(cap_p)
            publisher.setMaximumWidth(cap_p)
            label.setMinimumWidth(cap_l)
            label.setMaximumWidth(cap_l)
            for row in rows:
                row.invalidate()
                row.activate()
            if outer is not None:
                outer.activate()

    def _sync_nfo_target_column_align(self) -> None:
        """设置-NFO：宽态下目标两列左移到演员/剧集列与分级/片商列，窄态保持不动。

        用户需求（最大化）：原标题/剧情/发行日期/分级/时长（A 组，五个 HBox 行
        horizontalLayout_135/136/137/141/40 的第 2 项）向左移动到与演员/剧集
        （`checkBox_tag_actor`/`checkBox_tag_series`，标签行第 2 列）严格上下
        对齐；简介/首映/自定义评分/投票（同五行的第 3 项）与影评评分/导演/
        演员TMDB ID/标签（gridLayout_66 的 C1 四格）向左移动到与分级/片商
        （`checkBox_tag_definition`/`checkBox_tag_studio`，标签行第 3 列）严格
        上下对齐。四个锚点自身一律不动；最小化时页面、布局、控件、提示词等
        全部保持原样；只许左右移动。
        根因：五 HBox 行左堆积无弹簧、三项按 Minimum 均分 surplus（首项天然
        定在 X0=136 不动），第 2/3 项以斜率 ~1/3、~2/3 右移；gridLayout_66
        的 columnstretch=(1,0) 让 C0 吃掉全部 surplus，C1.x 以斜率 1 右移；
        而标签两行是 4 等分均分。三者斜率各异，只在默认宽度附近相交，窗口
        加宽后持续发散（离屏 1920×1170 实测 A 列 599 vs 锚 476、B 列/C1 列
        1092 vs 锚 846）。各行同属 layoutWidget_10，.x() 同一坐标系直接可比。
        做法（宽态门控，快慢双径、双向幂等）：窄态（拉伸量 <= 0）清掉本钉宽/尾间隔/
        C1 列最小宽后重跑右列/标题/行/尾四个控制器还原窄态行为，直接返回。宽态先走
        快路径：激活全链后按当前几何算约束，与现状逐值一致即零成本返回（不清不泵，
        resize 拖拽高频调用无负担）。否则走慢路径：绝不清直接闭环——C1 列最小宽一清零
        grid66 即收缩、col1 收窄、锚点左移，量到的是随即被自己的应用作废的几何（曾导致
        481 落定 488 的 stale，且多加同步也只会重复倒带）；锚点从未被钉，带着当前约束
        直接量到热值。随后至多 6 轮：激活→测量→比对，一致则泵事件冲掉本次应用的后果
        后再验证一次（仍一致才真收敛），否则应用后泵事件供下一轮重测。慢路径动过手
        必排一拍 NFO 链 trailing（singleShot(0)，上限 8 拍）：慢路径收敛的只是当前拍内
        几何，滚动区/内容宽度后续生长（如 lw10w 1509→1589）落定在退出之后，必须有一拍
        跑在它后面；下一拍快路径收敛即停排。单拍测量不可靠：切页级联里锚点随滚动区
        拉伸分阶段落定，且本方法的 C1 列最小宽会加宽 grid66、经 grid40 col1 反推锚点
        （自反馈），闭环是必需的。另有归属权问题：_sync_page_layouts 每遍都调右列
        控制器且跑在钩子链之后，它开头的清零会洗掉本钉宽——以 _nfo_target_col_active
        标志声明归属，生效中右列控制器直接返回（判据恒为假、本是 no-op），泵事件触发的
        嵌套全量同步因此无害；窄态/复位/放不下时先清标志再调它接管，保证 C1 有主。
        重入守卫 _nfo_target_col_running 拦住循环泵事件触发的嵌套本方法（外层循环覆盖
        一切）。宽态按行实测计算：首项钉宽 =
        锚A.x - 首项.x - 行间距（第 2 项即落到锚 A 列），第 2 项钉宽 =
        锚B.x - 锚A.x - 行间距（第 3 项即落到锚 B 列）；C1 沿用右列控制器的
        列最小宽公式（col 宽 - 锚B.x + 左列首项.x，此时第 3 项已在锚 B 列，
        与旧公式逐值相等），C1 四格一并归位。全有或全无：任一钉宽低于
        max(文本 hint, 60) 防裁字地板即整单放弃（首项 hint 最大 122、
        第 2 项最大 150，1920 宽下钉宽恒 364，
        C0 目标 734 远大于左列 hint，正常只走通过分支）。两项行
        （horizontalLayout_135）两项全钉死后行内无 Minimum 项吸收富余，
        离屏实测 QHBoxLayout 会把富余均摊进前/中/后三个间隙（双 364 在
        1473 行里落到 246/862 而非左对齐，纯 Qt 最小复现确认与业务代码无关），
        故只给两项行尾部补 Expanding 间隔吸收（水印页尾部间隔同款手法；
        三项行末项 Minimum 自然吸收、无需补），间隔每遍先摘后补。复选框只改列宽，
        高不变→行高不变→无上下移动。休眠页（不可见）跳过。
        与既有控制器的相容：本方法挂在 `_sync_nfo_page_align` 链尾。标题控制器
        在本方法之后仍成立（ot==rd、plot==rd、opl==pr 依然逐位相等，
        三前缀最小宽恰为本钉宽、>150 不变）；右列控制器判据 critic.x>custom.x
        在本方法之后恒为假（两者同在锚 B 列），C1 列最小宽改由本方法写入，
        其“宽态应钳制/窄态应清零”测试依然成立；行/尾控制器只在窄态触发，
        宽态下本方法覆写它们的复位值（min=max 全覆盖），故它们宽态“零残留”
        的旧断言改由本方法的钉宽断言接管（见测试）。
        """
        ui = self.Ui
        rows = (
            ui.horizontalLayout_135,
            ui.horizontalLayout_136,
            ui.horizontalLayout_137,
            ui.horizontalLayout_141,
            ui.horizontalLayout_40,
        )
        firsts = (
            ui.checkBox_nfo_sorttitle,
            ui.checkBox_nfo_outline,
            ui.checkBox_nfo_release,
            ui.checkBox_nfo_country,
            ui.checkBox_nfo_year,
        )
        seconds = (
            ui.checkBox_nfo_originaltitle,
            ui.checkBox_nfo_plot,
            ui.checkBox_nfo_relasedate,
            ui.checkBox_nfo_mpaa,
            ui.checkBox_nfo_runtime,
        )
        anchor_a = ui.checkBox_tag_actor
        anchor_b = ui.checkBox_tag_definition
        if not anchor_a.isVisibleTo(self):
            return
        if self._nfo_target_col_running:
            return  # 嵌套调用（宽态循环里泵事件触发的）：外层循环覆盖一切
        grid = ui.gridLayout_66
        score = ui.checkBox_nfo_score
        c0_cells = (
            score,
            ui.checkBox_nfo_actor,
            ui.checkBox_nfo_all_actor,
            ui.checkBox_nfo_series,
        )
        outer = ui.gridLayout_40

        def _activate_all():
            for row in rows:
                row.invalidate()
                row.activate()
            grid.invalidate()
            grid.activate()
            if outer is not None:
                outer.activate()

        def _compute():
            # 量锚点并算出钉宽/C1min。返回 (ok, first_pins, second_pins, c1_min)，
            # ok 为 False 即放不下（防裁字地板），调用方走 defer。
            anchor_a_x = anchor_a.x()
            anchor_b_x = anchor_b.x()
            first_pins = [anchor_a_x - cb.x() - row.spacing() for cb, row in zip(firsts, rows, strict=True)]
            second_pins = [anchor_b_x - anchor_a_x - row.spacing() for row in rows]
            col_w = grid.geometry().width()
            c1_min = max(col_w - anchor_b_x + score.x(), 0)
            c0_target = anchor_b_x - score.x() - grid.spacing()
            floor = max([cb.sizeHint().width() for cb in firsts + seconds + c0_cells] + [60])
            ok = min(first_pins + second_pins) >= floor and c0_target >= floor
            return ok, first_pins, second_pins, c1_min

        def _matches(first_pins, second_pins, c1_min):
            return (
                all(
                    cb.minimumWidth() == pin and cb.maximumWidth() == pin
                    for cb, pin in zip(firsts + seconds, first_pins + second_pins, strict=True)
                )
                and grid.columnMinimumWidth(1) == c1_min
            )

        def _clear():
            # 注意 sorttitle/outline/plot 三个前缀在 .ui 设计里自带最小宽 150
            # （Fixed-150 前缀，标题控制器每遍也是按 150 复位），清零会破坏设计值，
            # 故按 150 复位；其余七项设计最小宽即 0（行/尾控制器同式），
            # 最大宽设计均为默认。
            for cb in (firsts[0], firsts[1], seconds[1]):
                cb.setMinimumWidth(150)
            for cb in (firsts[2], firsts[3], firsts[4], seconds[0], seconds[2], seconds[3], seconds[4]):
                cb.setMinimumWidth(0)
            for cb in firsts + seconds:
                cb.setMaximumWidth(16777215)
            for row, spacer in self._nfo_target_col_tails:
                row.removeItem(spacer)
            self._nfo_target_col_tails = []
            grid.setColumnMinimumWidth(1, 0)
            self._nfo_target_col_active = False

        # 宽态门：拉伸量 <= 0 即窄态，复位后把管理同组控件的四个控制器重跑一遍，
        # 还原与本方法无关的窄态行为（本方法在窄态逐像素无残留；标志已清，
        # 右列控制器接管 C1 即恢复自然行为）。
        if self._scroll_stretch_extra(ui.scrollArea_13) <= 0:
            _clear()
            self._nfo_target_col_trailing = 0
            self._sync_nfo_right_column_align()
            self._sync_nfo_title_plot_align()
            self._sync_nfo_row_align()
            self._sync_nfo_tail_align()
            return
        # 快路径：稳态零成本。锚点从未被钉、可直接读；归属标志还在且按当前几何
        # 算出的约束与现状逐值一致→直接返回（不清不泵，resize 拖拽高频调用无负担）。
        _activate_all()
        ok, first_pins, second_pins, c1_min = _compute()
        if ok and self._nfo_target_col_active and _matches(first_pins, second_pins, c1_min):
            self._nfo_target_col_trailing = 0
            return
        # 慢路径：不清直接闭环。绝不能先清再量：C1 列最小宽一清零 grid66 即收缩、
        # col1 收窄、锚点左移，量到的是随即被自己的应用作废的几何（此前 stale 的根因：
        # 以约束相等退出，却验证了倒回去的世界；多加几拍同步也无用，只会重复倒带）。
        # 锚点从未被钉，带着当前约束直接量到的是热值；钉宽只约束首项/第 2 项自身宽度，
        # 不改变行首 x，公式不受污染。随后至多 6 轮：激活→测量→比对，一致则泵事件
        # 冲掉本次应用的后果后再验证一次（仍一致才真收敛），否则应用后泵事件供下一轮
        # 重测。嵌套调用由重入守卫拦，外层循环覆盖一切，有界终止。
        self._nfo_target_col_running = True
        try:
            self._nfo_target_col_active = True
            applied_any = False
            for _ in range(6):
                _activate_all()
                ok, first_pins, second_pins, c1_min = _compute()
                if not ok:
                    # 放不下就整单放弃、不裁字（小宽态 defer）：清掉本钉宽后把 C1 交还
                    # 给右列控制器（此时判据若成立它会自己钳制），行为即自然布局。
                    _clear()
                    self._nfo_target_col_trailing = 0
                    self._sync_nfo_right_column_align()
                    return
                if _matches(first_pins, second_pins, c1_min):
                    # 与当前约束逐值一致：泵事件冲掉之前应用的后果，再验证一次，
                    # 仍一致才算真收敛（否则继续循环应用）。拦用户输入防重入槽。
                    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                    _activate_all()
                    ok2, first_pins2, second_pins2, c1_min2 = _compute()
                    if ok2 and _matches(first_pins2, second_pins2, c1_min2):
                        break
                    first_pins, second_pins, c1_min = first_pins2, second_pins2, c1_min2
                    if not ok2:
                        _clear()
                        self._nfo_target_col_trailing = 0
                        self._sync_nfo_right_column_align()
                        return
                applied_any = True
                for cb, pin in zip(firsts, first_pins, strict=True):
                    cb.setMinimumWidth(pin)
                    cb.setMaximumWidth(pin)
                for cb, pin in zip(seconds, second_pins, strict=True):
                    cb.setMinimumWidth(pin)
                    cb.setMaximumWidth(pin)
                # 两项行两项全钉死后无处吸收富余（离屏实测 QHBoxLayout 会把富余均摊进
                # 三个间隙），三项行末项 Minimum 自然吸收。只给两项行尾部补 Expanding
                # 间隔（水印页尾部间隔同款手法），窄态/复位时摘掉；已补过不再重复补。
                for row in rows:
                    if row.count() == 2 and not any(r is row for r, _ in self._nfo_target_col_tails):
                        tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                        row.addItem(tail)
                        self._nfo_target_col_tails.append((row, tail))
                _activate_all()
                grid.setColumnMinimumWidth(1, c1_min)
                grid.invalidate()
                grid.activate()
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                _activate_all()
            # 慢路径动过手：排一拍 NFO 链跑在后续生长（lw10/内容宽）后面。
            # 注意必须直接排链（_sync_nfo_page_align，有休眠守卫），不能排全量同步——
            # 链只挂在宽幅拉伸钩子上，无拉伸时全量同步根本到不了本方法。
            # 下一拍收敛（快路径）即停排；仍失稳则再排；上限 8 拍防抖荡。
            if applied_any:
                if self._nfo_target_col_trailing < 8:
                    self._nfo_target_col_trailing += 1
                    QTimer.singleShot(0, self._sync_nfo_page_align)
                else:
                    self._nfo_target_col_trailing = 0
        finally:
            self._nfo_target_col_running = False

    def _sync_nfo_field_tips(self) -> None:
        """设置-NFO：窄态下字段说明按钮左移进组框，宽态保持不动。

        用户截图：最小化时「字段说明」按钮（pushButton_field_tips_nfo，
        Fixed 80x26，设计几何 x=640..720）伸出「写入NFO的字段」组框
        （groupBox_81，设计 x=30 宽 701，右缘 731，设计余量仅 11px）。
        根因：宽幅同步按 width=设计宽+extra 双向拉伸组框（extra<=0 时
        缩回）；extra<0（视口窄于设计 796）时组右缘左移，按钮还钉在 640
        就伸出去（1089 窗 extra≈-14，伸出约 3px；越窄越糟）。
        做法（绝对 pin，只左移）：复位 x=640→重排→若按钮右缘超过
        （组右缘-11），则 btn.move(组右缘-11-80, y)；宽态 640 逐像素不动，
        y 不动。按钮与组框同属 scrollAreaWidgetContents_nfo，同父坐标系
        直接可比。休眠页跳过，由切 tab/切页下一拍补齐；多拍收敛幂等。
        """
        ui = self.Ui
        btn = ui.pushButton_field_tips_nfo
        gb = ui.groupBox_81
        if not btn.isVisibleTo(self):
            return
        btn.move(640, btn.y())
        limit = gb.x() + gb.width() - 11
        if btn.x() + btn.width() > limit:
            btn.move(limit - btn.width(), btn.y())
