"""设置-高级页下半三处对齐（三批需求分属最大化 / 最小化两态）的回归测试。

三批需求（锚点自身均保持不动，提示词与控件提示一律不许变）：
  第一组（最大化「右移」）：「保存日志」「检查更新」两行的「关」→「隐藏NFO 文件管理」；
    「隐藏窗口」行的「点最小化按钮」→「显示字段来源信息」；同行的「无」→「显示字段内容信息」。
  第二组（最大化「左移」）：刮削结束后自动退出软件 / 停止刮削时 / 隐藏菜单栏图标（Mac）/
    暗黑模式 / 隐藏NFO 文件管理 / 两枚「关」→「显示字段来源信息」。
  第三组（最小化「左移」，并要求「最大化时页面、布局、控件、提示词等均保持不变」）：
    「点最小化按钮」与两枚「关」→「隐藏NFO 文件管理」；同行的「无」→「显示字段内容信息」。
    注意最小化态里「点最小化按钮」的锚点是 nfo 而非 from_log（两态不同），
    而「无」两态同锚；第三组落地后第一组/第二组的宽态结果必须逐位不变。
  第六组（最小化「向左缩进」，同样要求最大化态一切不变）：「每次间隔」时长框右缘
    缩到与「间歇刮削」文件数框右缘严格上下对齐——**唯一一处比右缘而不是左缘**的
    需求，锚点行及其余控件一律不许动。
  第七组（最小化「向左移」）：「隐藏NFO 文件管理」与两枚「关」→ 「显示字段来源信息」，
    且「显示字段来源信息」**位置保持不变**（它重新变成窄态的锚点）。
    上一批（第四组需求①）曾把它窄态右移到 nfo 那一列，本批与那一批方向相反，
    故 `_sync_advanced_page_debug_row` 连同调用一并删除——该行两项回到自然位。

根因防线（任一回归都会让本文件失败）：
  - 三处手法不同，勿互相套用。①所在行容器是顶层组框的**直接子项**、被通用
    宽幅同步判成 _STRETCH 每遍拉宽并重排行内布局，两个单选均分余量
    （宽态实测 742/741），钉死前导项「开」才能把「关」的左缘钉在锚点上。
  - ②③所在行容器 layoutWidget_17 **完全不参与拉伸**（它是 frame_3 的子控件，
    而通用同步只登记顶层组框的直接子项），未干预时四个尺寸下恒为 551x32、三个
    单选按 551 均分（180/179/180）。两个锚点在另一个组框里随该组一起拉伸，行内位置
    与锚点之间没有任何联动，只能钉死前两项 + 按落点调容器宽度。
  - 容器宽度的下界必须是 lw.sizeHint()（三项 hint 之和 + 两个间隔），**不是**设计宽 551：
    落点 n 随拉伸量增长，刚过「宽态线」那一段 want_w 只有 400 出头（1100 宽实测 457 < 551），
    拿 551 卡门会让那段窗宽全部漏排。
  - 判态用几何拉伸量 _scroll_stretch_extra() > 0 而非 isMaximized()：窗口管理器
    最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，用户会看到
    「先在原位、再跳到对齐位」。
  - 「关」→「隐藏NFO 文件管理」与「无」→「显示字段内容信息」**两态都要生效**，
    只按锚点区分（第三组把这两处的窄态也纳入了需求），而「点最小化按钮」的锚点
    随态切换（宽→显示字段来源信息 / 窄→隐藏NFO 文件管理），漏了 narrow 分支会让它
    在还原后停在 from_log 而不是 nfo。
  - 第七组把「隐藏NFO 文件管理」的窄态锚点也换成了「显示字段来源信息」，于是窄态
    下「隐藏NFO 文件管理」/ 两枚「关」/「点最小化按钮」四者同落在 from_log 那条竖线。
    这一段带**可行性门槛**（前导项「隐藏 Emby 演员管理」被钉窄到 pin_d 后仍须 ≥ 它
    自己的 sizeHint，否则必然裁字），放不下就整行放弃、保持自然位——故它在
    `_NARROW_FIT` 里单列，不与「两态无条件的落点」混在一起断言。
  - 跨分支 mapTo（锚点在 groupBox_12 内、目标在 groupBox_17/_4 与 frame_3）必须
    经公共祖先 scrollAreaWidgetContents_gaoji 中转。
  - 「向左移动」这个**方向**在本离屏环境里无法断言：resources/fonts 下没有任何 CJK
    字体（只有 Consolas 与 Segoe UI Emoji），字形宽度依赖字体度量，而本环境既不真实
    也不稳定（见 _EXTRA_NAMES）。跨环境都成立的硬性质只有「精确落在锚点左缘」，
    故本文件一律断言对齐、不断言方向。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_advanced(win, app):
    """切到设置页的「高级」tab（该 tab 的 objectName 是 tab5，不是 tab_5）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab5":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("高级 tab5 not found")
    app.processEvents()


def _abs(ui, widget) -> int:
    """控件左缘映射到高级页滚动内容的绝对 x（跨分支必须经 content 中转）。"""
    return widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _extra(win) -> int:
    return win._scroll_stretch_extra(win._adv_scroll)


# 本文件覆盖高级页七组竖线需求：
#   第一组（最大化「右移」）：两个「关」→「隐藏NFO 文件管理」、「点最小化按钮」→
#     「显示字段来源信息」、「无」→「显示字段内容信息」
#   第二组（最大化「左移」）：刮削结束后自动退出软件 / 停止刮削时 /
#     隐藏菜单栏图标（Mac）/ 暗黑模式 / 隐藏NFO 文件管理 / 两枚「关」
#     → 「显示字段来源信息」
#   第三组（最小化「左移」）：「点最小化按钮」+ 两枚「关」→「隐藏NFO 文件管理」，
#     「无」→「显示字段内容信息」
#   第四组（最小化「右移」）：「显示字段来源信息」→「隐藏NFO 文件管理」（需求①）；
#     「停止刮削时」/「隐藏菜单栏图标（Mac）」/「暗黑模式」/ 两枚「关」
#     → 「显示字段内容信息」（需求②）
#   第七组（最小化「左移」）：「隐藏NFO 文件管理」+ 两枚「关」→「显示字段来源信息」，
#     且「显示字段来源信息」位置保持不变（第四组需求①已撤销，见 _NARROW_FIT）
# 第三、四、七组在同一批控件上反复改方向（第三组说「关」左移到 nfo，第四组说右移到
# 「显示字段内容信息」，第七组又改回左移到 from_log），**后一条需求为准**：窄态以第七组
# 为准、第四组需求①整段撤销；它们在宽态下**同时成立**：宽态两枚「关」先随「隐藏NFO
# 文件管理」落位、再被第一组的 tail_align 拉回它右侧，最终都精确落在「显示字段来源
# 信息」那条竖线上。
_LEFT_TARGETS = (
    ("checkBox_auto_exit", "checkBox_show_from_log"),
    ("checkBox_show_dialog_stop_scrape", "checkBox_show_from_log"),
    ("checkBox_dark_mode", "checkBox_show_from_log"),
    ("checkBox_hide_nfo_nav", "checkBox_show_from_log"),
    ("radioButton_log_off", "checkBox_show_from_log"),
    ("radioButton_update_off", "checkBox_show_from_log"),
)

# 第五组（最小化「右移」）：「刮削结束后自动退出软件」→「隐藏菜单栏图标（Mac）」。
#   锚点不是固定像素，而是**第 8 行末位的实时左缘**——窄态下它的位置由 gap_b 决定，
#   而 gap_b 由 _sync_advanced_page_align 的 anchor 算出，所以这一段必须排在该方法
#   里第 8 行那批 activate **之后**才量得到终态值。
#   宽态不需要这一段：那时它与「刮削结束后自动退出软件」本就同在「显示字段来源信息」
#   那条竖线上（实测 1100×800 起四档全等）。
_NARROW_AUTO_EXIT = (("checkBox_auto_exit", "checkBox_hide_menu_icon"),)

# 第四组需求②在最小化态的落点（都锚「显示字段内容信息」，它是窄态最靠右的竖线）。
#   注意两枚「关」已移出：第七组把它们的窄态锚点换成了「隐藏NFO 文件管理」，
#   而 nfo 本批又对齐到「显示字段来源信息」，故窄态两枚「关」实际落最左那条竖线。
_NARROW_RIGHT = (
    ("checkBox_show_dialog_stop_scrape", "checkBox_show_data_log"),
    ("checkBox_dark_mode", "checkBox_show_data_log"),
)

# 第六组（最小化「向左缩进」）：「每次间隔」时长框右缘 → 「间歇刮削」文件数框右缘。
#   锚点**不是固定像素**而是该框的实时右缘——窄态下 hl109（间歇刮削）比 hl104
#   （每次间隔）长，先放不下的是 hl109，Qt 只能压行内压得动的项（标签的
#   minimumSizeHint == sizeHint 故一格不让，QLineEdit 的 sizePolicy 是 Fixed 故压得动），
#   于是「间歇刮削」的文件数框被压窄、而「每次间隔」那行仍有余量保持满宽，右缘参差。
#   故锚点宽度本身随字形度量而变，断言必须比**右缘**、且不得写死像素。
#   宽态不需要这一段：那时两枚框都是满宽，右缘本就相等（见本文件末尾那组用例）。
#   （对应需求：目标 lineEdit_timed_interval、锚点 lineEdit_rest_count。）

# 第三、四、七组（最小化态）：目标 -> 窄态锚点。
#   「点最小化按钮」窄态锚的是 checkBox_hide_nfo_nav 而**不是**
#     checkBox_show_from_log（两态不同）。第七组把 nfo 钉到 from_log 之后两者
#     在窄态同列，但代码里仍显式按态取锚，不依赖这个巧合。
#   第四组需求①的两段钉宽（把「显示字段来源信息」窄态右移到 nfo 那一列）已随
#     _sync_advanced_page_debug_row 一并撤销——它与第七组方向相反，后者是后一条
#     需求。「显示字段来源信息」/「显示刮削过程信息」窄态回到自然位（不再被钉宽），
#     「显示字段内容信息」也一并回到基线（那一段撤销后不再有钉宽压着它）。
_NARROW_TARGETS = (
    ("radioButton_hide_mini", "checkBox_hide_nfo_nav"),
    ("radioButton_hide_none", "checkBox_show_data_log"),
    # 第七组：两枚「关」窄态一律跟「隐藏NFO 文件管理」（无条件，落点即 nfo 的实时 x）
    ("radioButton_log_off", "checkBox_hide_nfo_nav"),
    ("radioButton_update_off", "checkBox_hide_nfo_nav"),
) + _NARROW_RIGHT

# 第七组里**带可行性门槛**的那一条：窄态把「隐藏NFO 文件管理」钉到「显示字段来源
# 信息」那条竖线。做法与本页其余各行同款（钉死前导项「隐藏 Emby 演员管理」为
# `pin_d = 竖线 - 行左缘 - 间隔`），但判据比别处多一道：`pin_d >= actor.sizeHint()`
# ——前导项被钉窄后仍须装得下自己的字，否则必然裁字，需求原话又要求「提示词不许变」。
# 放不下就整行放弃（解除钉宽、保持自然位），这与本文件 test_menu_icon_row_aligns_
# or_defers / test_dock_row 同款：可行性依赖字体度量、跨环境不一定同档，故不能把
# 「窗口一窄就必须对齐」写成死断言。
_NARROW_FIT = (("checkBox_hide_nfo_nav", "checkBox_show_from_log"),)

# 「隐藏菜单栏图标（Mac）」单列，不在 _LEFT_TARGETS 里做钉死像素的断言，原因见
# _dock_row 的说明：它所在行是「Fixed 前缀 + 间隔 + 末项」结构，前缀宽度等于两个
# 控件的 sizeHint 之和，而 sizeHint 是**字体度量**的函数；离屏测试环境里的字体度量
# 既不真实也不稳定（tests/conftest.py 把 get_fonts 桩掉 -> QFontDatabase.families()
# 为 0，"Sans Serif" 解析不到任何字族；而 resources/fonts/ 里只有 Consolas 与
# Segoe UI Emoji、**没有任何 CJK 字体**，真跑 get_fonts 时 CJK 全部落到 .notdef，
# 横向 advance 只剩 91px）。两个环境给出的前缀宽度差约 1.5 倍，于是「这一行放不放
# 得下」的结论在测试环境里与生产不一致——钉死像素等于在断言一个假度量。
# 故改为按实测可行性分别断言（test_menu_icon_row_aligns_or_defers），其对回归仍
# 有判别力：放得下却没对齐、或放不下却硬对齐（必然裁字/压住前缀）都会红。
_EXTRA_NAMES = ("checkBox_hide_menu_icon",)

# (目标, 锚点)：第一组右移三处 + 第二组两枚「关」（宽态）
_TARGETS = (
    ("radioButton_log_off", "checkBox_hide_nfo_nav"),
    ("radioButton_update_off", "checkBox_hide_nfo_nav"),
    ("radioButton_hide_mini", "checkBox_show_from_log"),
    ("radioButton_hide_none", "checkBox_show_data_log"),
)

# 宽态下**整块几何**都不许动的参照：两个锚点、其余行内控件、容器、组框。
# 注意 checkBox_show_from_log 已移出：第四组需求①曾把它当窄态目标右移 21px，那一段
# 已随第七组撤销，故它回到「宽窄两态都不许动」的行列——但窄态它是**锚点**（不动）、
# 宽态它是第二组的目标（也不动），两态都不许动，故仍可留在 _REFS 里。
_REFS = (
    "checkBox_show_data_log",
    "checkBox_show_from_log",
    "frame_3",
    "layoutWidget_3",
    "horizontalLayoutWidget_11",
    "horizontalLayoutWidget_7",
    "groupBox_3",
    "groupBox_4",
    "groupBox_12",
    "groupBox_17",
)

# 宽态下**只许改宽度、不许改左缘**的中间量：它们正是需求生效的搬运工与容器，
# 量到宽度差异恰恰是对齐生效的证据，拿整块几何去卡会误报。
#   checkBox_auto_start      阶段一被钉死的前导项，「刮削结束后自动退出软件」靠它落到竖线
#   checkBox_hide_actor_nav  隐藏入口行被钉的前导项，「隐藏NFO 文件管理」靠它落到竖线
#                           （宽态锚本页竖线、窄态锚「显示字段来源信息」，见 _NARROW_FIT）
#   radioButton_log_on / radioButton_update_on
#                           两行被钉的前导项「开」，两枚「关」靠它们落到目标竖线
#                           （第一、三、七组都要用）
#   radioButton_hide_close   「隐藏窗口」行被钉的前导项，「点最小化按钮」「无」靠它排下去
#   layoutWidget5            「界面外观行」容器，按落点收窄/加宽（frame 无布局，用 setGeometry）
#   layoutWidget_17          「隐藏窗口」行容器，两态都按落点调宽（frame_3 无布局，用 setGeometry）
#   checkBox_show_web_log    调试模式行的前导项；第四组需求①曾把它钉宽、随第七组撤销，
#                           左缘恒为容器左缘
#   checkBox_hide_window_title
#                           「界面外观行」被钉的前导项；第四组需求②在窄态改走「钉前导项」
#                           那条路（两均分放不下），宽态仍走「加宽容器 + 两均分」
_REFS_X_ONLY = (
    "checkBox_auto_start",
    "checkBox_hide_actor_nav",
    "radioButton_log_on",
    "radioButton_update_on",
    "radioButton_hide_close",
    "layoutWidget5",
    "layoutWidget_17",
    "checkBox_show_web_log",
    "checkBox_hide_window_title",
    # 第五组：第 8 行那枚 Fixed 前缀「隐藏Dock图标（Mac）」，第五组只许动第 2 行，
    # 它必须逐位不动（_dock_row / test_narrow_auto_exit_lands_on_menu_icon 会比对它）
    "checkBox_hide_dock_icon",
    "label_42",
)

# 必然随需求一起动的从动项（末位吸收余量/紧贴右邻），只作窄态与往返比对。
_FOLLOWERS = ("label_nav_hide_hint",)

# 全部落在宽态（_scroll_stretch_extra() > 0）；1100 特意保留——它是最贴近
# 刚过宽态线的那一档，正是 want_w < 551 曾被误判为「放不下」的那一档。
_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


def _snapshot(ui):
    names = (
        _REFS
        + _REFS_X_ONLY
        + _FOLLOWERS
        + tuple(n for n, _ in _TARGETS)
        + tuple(n for n, _ in _LEFT_TARGETS)
        + tuple(n for n, _ in _NARROW_TARGETS)
        + tuple(n for n, _ in _NARROW_AUTO_EXIT)
        + tuple(n for n, _ in _NARROW_FIT)
        + ("checkBox_hide_menu_icon",)
        + _EXTRA_NAMES
    )
    return {name: (_abs(ui, getattr(ui, name)), getattr(ui, name).width()) for name in dict.fromkeys(names)}


def _statics(ui):
    """提示词 / 控件提示 / 尺寸提示：需求要求一个都不许动。"""
    names = ("radioButton_hide_close",) + tuple(t for t, _ in _TARGETS) + tuple(a for _, a in _TARGETS)
    names += tuple(t for t, _ in _LEFT_TARGETS) + tuple(n for n, _ in _NARROW_TARGETS) + _EXTRA_NAMES
    names += tuple(n for n, _ in _NARROW_FIT) + ("checkBox_hide_actor_nav",)
    return {
        name: (
            getattr(ui, name).text(),
            getattr(ui, name).toolTip(),
            getattr(ui, name).sizeHint().width(),
        )
        for name in dict.fromkeys(names)
    }


def _without_feature(win, app, monkeypatch, width, height):
    """造一份「只有通用宽幅逻辑」的基线快照：另起一个窗口，两个对齐控制器全程摘掉。

    不能在同一个窗口上摘掉方法再跑一次同步——摘掉后就没人解除上一轮留下的钉宽
    （setFixedWidth 落在控件自身的 min/max 上，跨调用留存），量到的「基线」会带着
    新竖线，比对就成了自己比自己（本文件第一版正是栽在这里：base 与 now 全等）。

    第二组改的是 _sync_advanced_page_align 本体（不是独立方法），故两个都得摘。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    originals = {
        "_sync_advanced_page_align": mw_mod.MyMAinWindow._sync_advanced_page_align,
        "_sync_advanced_page_tail_align": mw_mod.MyMAinWindow._sync_advanced_page_tail_align,
    }
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_align", lambda self, *a, **k: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_tail_align", lambda self: None)
    probe = None
    try:
        probe = mw_mod.MyMAinWindow()
        for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
            getattr(probe, timer_name).stop()
        probe.show()
        _goto_advanced(probe, app)
        _resize(probe, app, width, height)
        return _snapshot(probe.Ui), _statics(probe.Ui)
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        for name, fn in originals.items():
            monkeypatch.setattr(mw_mod.MyMAinWindow, name, fn)


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_tail_aligns_to_anchors_in_wide(win, app, width, height):
    """需求①②③：宽态下四个目标分别精确落在三个锚点的左缘上。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    for target, anchor in _TARGETS:
        got = _abs(ui, getattr(ui, target))
        want = _abs(ui, getattr(ui, anchor))
        assert got == want, f"{width} 宽下「{target}」未与「{anchor}」严格上下对齐: x={got} 期望={want}"


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_left_targets_land_on_from_log_in_wide(win, app, width, height):
    """第二组：宽态下六项一律精确落在「显示字段来源信息」的左缘上。

    第七项「隐藏菜单栏图标（Mac）」不在此列，它由 test_menu_icon_row_aligns_or_defers
    按实测可行性单独断言（理由见 _EXTRA_NAMES）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    want = _abs(ui, ui.checkBox_show_from_log)
    for target, anchor in _LEFT_TARGETS:
        assert anchor == "checkBox_show_from_log"
        got = _abs(ui, getattr(ui, target))
        assert got == want, f"{width} 宽下「{target}」未与「显示字段来源信息」严格上下对齐: x={got} 期望={want}"


def _dock_row(ui, anchor_name):
    """隐藏图标行（horizontalLayout_dock）的实测可行性。

    与 _sync_advanced_page_align 里那一段同式：前缀 = 两个 Fixed 文本项的 sizeHint
    之和 + 两个间隔，能插入的间隔 gap = 新竖线 - 行左缘 - 前缀；放得下的条件是
    gap >= 0 且让出 gap 后剩余宽度仍够末项的 sizeHint（sizeHint 就是不裁字下限）。
    竖线按态传入：宽态是「显示字段来源信息」，窄态是「显示字段内容信息」。
    """
    lay = ui.horizontalLayout_dock
    host = ui.gridLayoutWidget_20
    content = ui.scrollAreaWidgetContents_gaoji
    host_x = host.mapTo(content, QPoint(0, 0)).x()
    row_x = _abs(ui, ui.checkBox_hide_dock_icon) - host_x
    col_w = host.width() - row_x
    anchor = _abs(ui, getattr(ui, anchor_name)) - host_x
    prefix = ui.checkBox_hide_dock_icon.sizeHint().width() + ui.label_42.sizeHint().width() + 2 * lay.spacing()
    gap = anchor - row_x - prefix
    return {
        "gap": gap,
        "prefix": prefix,
        "feasible": gap >= 0 and col_w - gap - prefix >= ui.checkBox_hide_menu_icon.sizeHint().width(),
    }


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_menu_icon_row_aligns_or_defers(win, app, monkeypatch, width, height):
    """「隐藏菜单栏图标（Mac）」：放得下就必须精确对齐，放不下就整行放弃。

    放弃态的语义与本页其余各行一致：间隔归 0、不裁字、Fixed 前缀两项一律不动，
    于是末项停在竖线**右侧**（前缀本身就压过竖线，物理上够不到）。
    两态都验：第四组需求②把它的窄态竖线换成更靠右的「显示字段内容信息」，
    可行性结论也随之改变（窄态前缀相对更宽、更容易放不下）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    wide = _extra(win) > 0
    assert wide == ((width, height) in _WIDE_SIZES), f"{width} 宽下窗宽状态与用例表不符"

    anchor_name = "checkBox_show_from_log" if wide else "checkBox_show_data_log"
    row = _dock_row(ui, anchor_name)
    menu = ui.checkBox_hide_menu_icon
    dock = ui.checkBox_hide_dock_icon
    anchor_x = _abs(ui, getattr(ui, anchor_name))
    menu_x = _abs(ui, menu)
    prefix_before = (_abs(ui, dock), _abs(ui, ui.label_42))

    if row["feasible"]:
        assert menu_x == anchor_x, f"{width} 宽下前缀放得下（gap={row['gap']}）却未对齐: x={menu_x} 期望={anchor_x}"
    else:
        assert menu_x > anchor_x, (
            f"{width} 宽下前缀放不下（gap={row['gap']}）本应整行放弃，却对到了 x={menu_x}（可能裁字）"
        )
        assert _abs(ui, ui.label_42) + ui.label_42.width() <= menu_x, (
            f"{width} 宽下放弃态里「隐藏菜单栏图标」压住了 Fixed 前缀: 前缀右缘"
            f"{_abs(ui, ui.label_42) + ui.label_42.width()} > 目标左缘 {menu_x}"
        )

    # 两种情形下 Fixed 前缀两项都不许动、末项都不许被压到裁字
    win._sync_page_layouts()
    app.processEvents()
    assert (_abs(ui, dock), _abs(ui, ui.label_42)) == prefix_before, (
        f"{width} 宽下 Fixed 前缀两项被本需求带偏: {prefix_before} -> {(_abs(ui, dock), _abs(ui, ui.label_42))}"
    )
    assert menu.width() >= menu.sizeHint().width(), (
        f"{width} 宽下「隐藏菜单栏图标」被压到 {menu.width()}px（sizeHint {menu.sizeHint().width()}），会裁字"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_new_line_is_left_of_the_old_one_in_wide(win, app, monkeypatch, width, height):
    """第二组的方向是「向左」：新竖线必须严格落在旧竖线左侧。

    旧竖线 = 只有通用宽幅逻辑时「刮削结束后自动退出软件」的自然位（`_without_feature`
    另起窗口量得），旧代码正是拿它当基准。断言「新竖线 < 旧竖线」而不是逐项与通用
    逻辑比大小——后者依赖字体度量：本文件所用离屏环境里「显示字段来源信息」与旧基准
    的左右关系并不总与生产一致（例如 1920 宽下暗黑模式由 428 被移到 589，看着是右移，
    但那是因为通用逻辑把「界面外观行」摊到了另一处，真实生产度量下是左移）。
    真正与环境无关的是「新竖线在旧竖线左边」，它对每一档都成立。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    old_line = base["checkBox_auto_exit"][0]
    win._sync_page_layouts()
    app.processEvents()

    new_line = _abs(ui, ui.checkBox_show_from_log)
    assert new_line < old_line, f"{width} 宽下新竖线未在旧竖线左侧: 新={new_line} 旧={old_line}"
    for target, _ in _LEFT_TARGETS:
        assert _abs(ui, getattr(ui, target)) <= old_line, (
            f"{width} 宽下「{target}」落到了旧竖线右侧: x={_abs(ui, getattr(ui, target))} 旧竖线={old_line}"
        )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_never_moves_anchors_and_never_clips(win, app, monkeypatch, width, height):
    """锚点自身逐项不动；且「无」不许被压到裁字（宽度 >= 自身 sizeHint）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for name in _REFS:
        assert _snapshot(ui)[name] == base[name], (
            f"{width} 宽下参照控件「{name}」被本需求带偏: {base[name]} -> {_snapshot(ui)[name]}"
        )
    for name in _REFS_X_ONLY:
        assert _snapshot(ui)[name][0] == base[name][0], (
            f"{width} 宽下搬运工/容器「{name}」左缘被本需求带偏: {base[name]} -> {_snapshot(ui)[name]}"
        )

    for name in ("radioButton_hide_close",) + tuple(t for t, _ in _TARGETS):
        box = getattr(ui, name)
        assert box.width() >= box.sizeHint().width(), (
            f"{width} 宽下「{name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )

    # 「无」的右缘不得越出 frame_3（frame 无布局，越界子控件会被父控件裁掉）
    lw = ui.layoutWidget_17
    none = ui.radioButton_hide_none
    assert _abs(ui, none) + none.width() <= _abs(ui, ui.frame_3) + ui.frame_3.width(), (
        f"{width} 宽下「无」越出 frame_3 右缘"
    )
    assert lw.width() >= lw.sizeHint().width(), (
        f"{width} 宽下 layoutWidget_17={lw.width()} 窄于布局最小 {lw.sizeHint().width()}"
    )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_hide_row_aligns_to_anchors(win, app, width, height):
    """最小化态：第三、四、七组里**无条件**的落点全部精确对齐。

    第四组需求②「停止刮削时」/「暗黑模式」→「显示字段内容信息」与第七组两枚「关」
    →「隐藏NFO 文件管理」、第三组「点最小化按钮」/「无」的落点合并在
    _NARROW_TARGETS 里一起断言。第七组里「隐藏NFO 文件管理」→「显示字段来源信息」
    那一条带可行性门槛，单列在 _NARROW_FIT / test_narrow_nav_row_aligns_or_defers。

    只断言「精确对齐」不断言「向左/向右移动」——方向取决于字体度量，而本离屏环境
    resources/fonts 下没有任何 CJK 字体，度量既不真实也不稳定（见 _EXTRA_NAMES）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    for target, anchor in _NARROW_TARGETS + _NARROW_AUTO_EXIT:
        got = _abs(ui, getattr(ui, target))
        want = _abs(ui, getattr(ui, anchor))
        assert got == want, f"窄态 {width} 宽下「{target}」未与「{anchor}」严格上下对齐: x={got} 期望={want}"


def _nav_row(ui, anchor_name):
    """隐藏入口行（horizontalLayout_nav_hide）的实测可行性。

    与 _sync_advanced_page_align「隐藏入口行」段同式：钉死前导项「隐藏 Emby 演员管理」
    为 `pin = 竖线 - 行左缘 - 间隔`，末位「隐藏NFO 文件管理」即落竖线。放得下的条件
    是 pin >= actor.sizeHint()（前导项被钉窄后仍须装得下自己的字，sizeHint 就是不裁字
    下界）且让出 pin 后剩余宽度仍 >= nfo.sizeHint()。
    竖线按态传入：宽态是本页竖线（「显示字段来源信息」），窄态是「显示字段来源信息」
    本身（第七组）。
    """
    lay = ui.horizontalLayout_nav_hide
    host = ui.gridLayoutWidget_20
    content = ui.scrollAreaWidgetContents_gaoji
    host_x = host.mapTo(content, QPoint(0, 0)).x()
    row_x = _abs(ui, ui.checkBox_show_dialog_exit) - host_x
    col_w = host.width() - row_x
    nav_x = _abs(ui, getattr(ui, anchor_name)) - host_x
    actor = ui.checkBox_hide_actor_nav
    nfo = ui.checkBox_hide_nfo_nav
    pin = nav_x - row_x - lay.spacing()
    room = col_w - pin - 2 * lay.spacing()
    return {"pin": pin, "room": room, "feasible": pin >= actor.sizeHint().width() and room >= nfo.sizeHint().width()}


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_debug_row_stays_at_natural_position(win, app, monkeypatch, width, height):
    """第四组需求①已随第七组撤销：调试模式行窄态回到自然位，且不再有残留钉宽。

    那一段原本把「显示字段来源信息」窄态右移到「隐藏NFO 文件管理」那一列（钉
    web/from 两段宽度），方向与第七组相反；撤销后它必须与「只有通用宽幅逻辑」的
    基线**逐位相同**（左缘与宽度都比），否则说明还有钉宽没摘干净——那正是当初把
    「显示字段来源信息」钉到固定宽度、在还原时留在原位的老毛病。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for name in ("checkBox_show_web_log", "checkBox_show_from_log", "checkBox_show_data_log"):
        box = getattr(ui, name)
        assert (_abs(ui, box), box.width()) == base[name], (
            f"窄态 {width} 宽下调试模式行「{name}」未回到基线: 基线={base[name]} 实际={(_abs(ui, box), box.width())}"
        )
        assert box.maximumWidth() == _QWIDGETSIZE_MAX, (
            f"窄态 {width} 宽下「{name}」还残留着第四组需求①的钉宽: maxW={box.maximumWidth()}"
        )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_nav_row_aligns_or_defers(win, app, monkeypatch, width, height):
    """第七组：窄态把「隐藏NFO 文件管理」钉到「显示字段来源信息」，放得下就必须对齐。

    放弃态的语义与本页其余各行一致：整行解除钉宽、保持自然位、绝不裁字。
    可行性依赖字体度量（见 _EXTRA_NAMES）：本离屏环境没有 CJK 字体，前导项
    「隐藏 Emby 演员管理」的 sizeHint 与它在真实字体下的宽高比不同，于是同一档窗宽
    在两个环境下的可行性结论可能相反。故断言写成条件式（放得下却没对齐、或放不下
    却硬对齐——后者必然裁字——都会红），不写死「窗口一窄就必须对齐」。
    生产环境那一档可行时，用户实测前导项富余够（需求原话也明写「提示词不许变」），
    走的就是对齐这条分支（见 test_narrow_nav_row_lands_on_from_log_when_it_fits）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    (target, anchor) = _NARROW_FIT[0]
    row = _nav_row(ui, anchor)
    nfo = ui.checkBox_hide_nfo_nav
    from_x = _abs(ui, ui.checkBox_show_from_log)

    if row["feasible"]:
        assert _abs(ui, nfo) == from_x, (
            f"窄态 {width} 宽下「{target}」放得下（pin={row['pin']}）却未与「{anchor}」对齐: "
            f"x={_abs(ui, nfo)} 期望={from_x}"
        )
        # 是真走了 setFixedWidth 那条路，不是「恰好排成这样」
        assert nfo.minimumWidth() == nfo.maximumWidth() == nfo.sizeHint().width(), (
            f"窄态 {width} 宽下「{target}」未按 sizeHint 钉宽: min={nfo.minimumWidth()} max={nfo.maximumWidth()}"
        )
    else:
        # 放弃态：与「只有通用宽幅逻辑」的基线逐位相同，且三项都不许被压到裁字
        base, _ = _without_feature(win, app, monkeypatch, width, height)
        win._sync_page_layouts()
        app.processEvents()
        assert (_abs(ui, nfo), nfo.width()) == base["checkBox_hide_nfo_nav"], (
            f"窄态 {width} 宽下本应整行放弃（pin={row['pin']} < sizeHint），却动了几何: "
            f"基线={base['checkBox_hide_nfo_nav']} 实际={(_abs(ui, nfo), nfo.width())}"
        )
        assert nfo.minimumWidth() == 0 and nfo.maximumWidth() == _QWIDGETSIZE_MAX, (
            f"窄态 {width} 宽下放弃态仍残留钉宽: min={nfo.minimumWidth()} max={nfo.maximumWidth()}"
        )

    for name in ("checkBox_hide_actor_nav", "checkBox_hide_nfo_nav"):
        box = getattr(ui, name)
        assert box.width() >= box.sizeHint().width(), (
            f"窄态 {width} 宽下「{name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_nav_row_lands_on_from_log_when_it_fits(win, app, width, height):
    """**判别力所在**：人为制造出「放得下」的行，断言三项真的精确落上那条竖线。

    本离屏环境里前导项「隐藏 Emby 演员管理」被 .notdef 字形撑到与 pin 几乎一样宽
    （离屏 1030×753 是 sizeHint 144 vs pin 138，差 6px），于是自然态永远落在
    「放不下」那条分支上——真实字体下前导项的富余足够（用户实测「不会裁字」），
    走的是对齐分支。为覆盖到那条分支，这里把前导项的提示词临时改短（等价于让
    它的 sizeHint 变小），余量立即变得充裕，判据转真；断言后原样恢复。

    手法与本文件既有的 test_timed_interval_* 一致（用 setFixedWidth 模拟 Qt 的处置、
    断言后 _unpin 复原），只是这里模拟的是**放得下**的那一侧。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    actor = ui.checkBox_hide_actor_nav
    original = actor.text()
    actor.setText("隐藏演员")
    try:
        assert actor.sizeHint().width() < _nav_row(ui, "checkBox_show_from_log")["pin"], (
            f"{width} 宽下临时提示词仍不够短，没能制造出可行场景"
        )
        _resize(win, app, width, height)
        assert _nav_row(ui, "checkBox_show_from_log")["feasible"], (
            f"{width} 宽下改短提示词后仍判为放不下，判据本身有问题"
        )

        from_x = _abs(ui, ui.checkBox_show_from_log)
        assert _abs(ui, actor) + actor.width() + ui.horizontalLayout_nav_hide.spacing() == from_x, (
            f"窄态 {width} 宽下前导项右缘未贴住锚点: "
            f"{_abs(ui, actor) + actor.width() + ui.horizontalLayout_nav_hide.spacing()} != {from_x}"
        )
        assert actor.minimumWidth() == actor.maximumWidth() == _nav_row(ui, "checkBox_show_from_log")["pin"], (
            f"窄态 {width} 宽下前导项未按 pin 钉宽: min={actor.minimumWidth()} max={actor.maximumWidth()}"
        )
        # 本批需求的三项：隐藏NFO库管理 + 两枚「关」，同落 from_log 那条竖线
        for name in ("checkBox_hide_nfo_nav", "radioButton_log_off", "radioButton_update_off"):
            assert _abs(ui, getattr(ui, name)) == from_x, (
                f"窄态 {width} 宽下「{name}」未与「显示字段来源信息」严格上下对齐: "
                f"x={_abs(ui, getattr(ui, name))} 期望={from_x}"
            )
        # 「隐藏窗口」行的「点最小化按钮」窄态锚的也是 nfo，四者同列
        assert _abs(ui, ui.radioButton_hide_mini) == from_x, (
            f"窄态 {width} 宽下「点最小化按钮」未与「显示字段来源信息」同列"
        )
    finally:
        actor.setText(original)
        _resize(win, app, width, height)


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_nav_row_anchor_is_state_independent(win, app, width, height):
    """隐藏入口行的锚点两态统一取「显示字段来源信息」，宽态也必须精确落上它。

    用户真机事故：还原态窗口 1085×793（dpr 1.25、屏幕 1536×864）算出的
    `_scroll_stretch_extra` 是 **+33 > 0**，程序把它判成「最大化」，于是按 anchor
    分两态的老写法在用户真正想改的那一档走的是**宽态**那一支——而那一支在该尺寸下
    阶段一的门也会卡掉（anchor 停在自然位，与 col_x(from) 差 17px），算出的
    pin_d/room 放不下整行，三个目标纹丝不动（用户截图实测：nfo 328 vs from 311）。

    修法是锚点不再分两态。宽态之所以逐位不变，是因为阶段一已把
    「刮削结束后自动退出软件」钉到 src_from 那条竖线，anchor 恒等于
    col_x(src_from)（真机 1200/1366/1536 三档实测 anchor≡nav_x）。
    本用例把这条不变量写成断言：宽态下 anchor 与 col_x(from) 必须逐位相等，
    且「隐藏NFO库管理」与两枚「关」都精确落在它上面；顺手钉住
    「显示字段来源信息」自身不动（需求明写它位置保持不变）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    content = ui.scrollAreaWidgetContents_gaoji
    host_x = ui.gridLayoutWidget_20.mapTo(content, QPoint(0, 0)).x()
    anchor_x = _abs(ui, ui.checkBox_auto_exit) - host_x
    from_x = _abs(ui, ui.checkBox_show_from_log) - host_x
    assert anchor_x == from_x, (
        f"宽态 {width} 宽下本页竖线与「显示字段来源信息」不同列，"
        f"锚点统一取 col_x(src_from) 会改变最大化结果: anchor={anchor_x} from={from_x}"
    )

    from_abs = _abs(ui, ui.checkBox_show_from_log)
    for name in ("checkBox_hide_nfo_nav", "radioButton_log_off", "radioButton_update_off"):
        assert _abs(ui, getattr(ui, name)) == from_abs, (
            f"宽态 {width} 宽下「{name}」未与「显示字段来源信息」严格上下对齐: "
            f"x={_abs(ui, getattr(ui, name))} 期望={from_abs}"
        )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_nav_row_survives_deferred_stage_one(win, app, width, height):
    """回归守卫：**阶段一整行放弃时**，隐藏入口行仍必须落「显示字段来源信息」。

    这正是用户真机 1085×793 那一档的形状：真实字体度量下阶段一的门
    `pin_2 >= auto_start.sizeHint()` 会卡掉（`anchor` 停在自然位、与
    col_x(src_from) 差 17px），于是按 anchor 分两态的老写法在那一档把三个目标
    钉到了一条**错的**竖线上，再叠加 room < need_d 而整行放弃——用户看到的现象
    就是「根本没动」。

    这里把前导项「自动启动后自动开始刮削」的提示词临时加长来复现同一形状
    （sizeHint 变大 -> ok_2 为假），断言锚点不再依赖 anchor：三项目标仍然精确落在
    「显示字段来源信息」上。断言后恢复文案并重排。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    content = ui.scrollAreaWidgetContents_gaoji
    host_x = ui.gridLayoutWidget_20.mapTo(content, QPoint(0, 0)).x()

    lead = ui.checkBox_auto_start
    original = lead.text()
    lead.setText(original + "自动启动后自动开始刮削并立即进入无人值守守候模式" * 2)
    try:
        _resize(win, app, width, height)
        anchor_x = _abs(ui, ui.checkBox_auto_exit) - host_x
        from_x = _abs(ui, ui.checkBox_show_from_log) - host_x
        assert anchor_x != from_x, (
            f"{width} 宽下没能复现「阶段一整行放弃」的场景（anchor 仍等于 from），这个回归守卫就形同虚设"
        )
        from_abs = _abs(ui, ui.checkBox_show_from_log)
        for name in ("checkBox_hide_nfo_nav", "radioButton_log_off", "radioButton_update_off"):
            assert _abs(ui, getattr(ui, name)) == from_abs, (
                f"宽态 {width} 宽下阶段一放弃时「{name}」没跟上「显示字段来源信息」: "
                f"x={_abs(ui, getattr(ui, name))} 期望={from_abs}（anchor={anchor_x}）"
            )
    finally:
        lead.setText(original)
        _resize(win, app, width, height)


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_hide_row_never_clips_or_escapes(win, app, width, height):
    """窄态下钉宽仍不许把字压掉，容器不许越出 frame_3。

    窄态下容器是被**收窄**的（离屏度量 551 -> 411），这是需求③要的「向左移动」；
    收窄后三项各自的钉宽仍 ≥ 自身 sizeHint，故不裁字。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    for name in ("radioButton_hide_close", "radioButton_hide_mini", "radioButton_hide_none"):
        box = getattr(ui, name)
        assert box.width() >= box.sizeHint().width(), (
            f"窄态 {width} 宽下「{name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )
    lw = ui.layoutWidget_17
    none = ui.radioButton_hide_none
    assert lw.width() >= lw.sizeHint().width(), f"窄态 {width} 宽下 layoutWidget_17={lw.width()} 窄于布局最小"
    assert _abs(ui, none) + none.width() <= _abs(ui, ui.frame_3) + ui.frame_3.width(), (
        f"窄态 {width} 宽下「无」越出 frame_3 右缘"
    )
    # 容器宽度恰为「无」的落点 + 「无」自身 sizeHint：既不虚留空白，也不裁字
    want_w = (_abs(ui, ui.checkBox_show_data_log) - _abs(ui, lw)) + none.sizeHint().width()
    assert lw.width() == want_w, f"窄态 {width} 宽下 layoutWidget_17={lw.width()}，按落点应为 {want_w}（不多留空白）"


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_never_moves_anchors(win, app, monkeypatch, width, height):
    """窄态下三个锚点与所有参照件整块几何不动，搬运工/容器只许改宽度。

    注意 checkBox_show_from_log 已在 _REFS 里：第七组撤销了第四组需求①之后，它
    在窄态是**锚点**（不许动），而 _REFS 的比对基准是「只有通用宽幅逻辑」的另一个
    窗口——锚点自己从不被钉宽，故两者逐位相同，正是「位置保持不变」的直接断言。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for name in _REFS:
        assert _snapshot(ui)[name] == base[name], (
            f"窄态 {width} 宽下参照件「{name}」被带偏: 基线={base[name]} 实际={_snapshot(ui)[name]}"
        )
    # 「仅隐藏入口…」是隐藏入口行的末位从动项，不是固定参照件：nfo 被钉回
    # sizeHint 后，它必须左移并吸收释放出来的宽度。这里断言真正跨环境成立的性质——
    # 右缘仍贴住行右缘、宽度不被压到 sizeHint 以下、左缘紧贴 nfo 右缘。
    hint_name = _FOLLOWERS[0]
    hint_x, hint_w = _snapshot(ui)[hint_name]
    base_x, base_w = base[hint_name]
    assert hint_x + hint_w == base_x + base_w, (
        f"窄态 {width} 宽下从动项「{hint_name}」右缘被带偏: 基线右缘={base_x + base_w} 实际右缘={hint_x + hint_w}"
    )
    assert hint_w >= max(base_w, ui.label_nav_hide_hint.sizeHint().width()), (
        f"窄态 {width} 宽下从动项「{hint_name}」宽度={hint_w}，"
        f"基线={base_w} sizeHint={ui.label_nav_hide_hint.sizeHint().width()}"
    )
    assert hint_x == (
        _abs(ui, ui.checkBox_hide_nfo_nav) + ui.checkBox_hide_nfo_nav.width() + ui.horizontalLayout_nav_hide.spacing()
    ), f"窄态 {width} 宽下从动项「{hint_name}」没有紧贴 nfo 右缘"
    for name in _REFS_X_ONLY:
        assert _snapshot(ui)[name][0] == base[name][0], (
            f"窄态 {width} 宽下搬运工/容器「{name}」左缘被带偏: 基线={base[name]} 实际={_snapshot(ui)[name]}"
        )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_keeps_wide_only_feature_at_baseline(win, app, monkeypatch, width, height):
    """第二组需求在窄态仍须完全退让——它换过基准线，最容易漏掉窄态分支。

    第四组把第二组六项里的「停止刮削时」「暗黑模式」「隐藏菜单栏图标」「关」×2
    也纳入了窄态（落点换成更靠右的「显示字段内容信息」），第七组又把「隐藏NFO
    文件管理」与两枚「关」改成锚「显示字段来源信息」，于是第二组六项全部被窄态接管，
    只剩「刮削结束后自动退出软件」（第二组的基准本身，还原态必须留在自然位）与
    「隐藏菜单栏图标（Mac）」由第五组单独接管（落点即它自己，须留在基线）。

    仍须原地不动的只有第七组那条「隐藏NFO 文件管理」→「显示字段来源信息」——
    它带可行性门槛，放不下就整行放弃（由 test_narrow_nav_row_aligns_or_defers 断言）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    # 第二组六项全部已被第四/七组的窄态分支接管，只剩基准「刮削结束后自动退出软件」
    narrow_targets = {t for t, _ in _NARROW_TARGETS} | {t for t, _ in _NARROW_AUTO_EXIT} | {t for t, _ in _NARROW_FIT}
    for target, _ in _LEFT_TARGETS:
        if target in narrow_targets:
            continue
        assert _abs(ui, getattr(ui, target)) == base[target][0], (
            f"窄态 {width} 宽下第二组目标「{target}」被带偏: 基线={base[target][0]} 实际={_abs(ui, getattr(ui, target))}"
        )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_auto_exit_lands_on_menu_icon(win, app, monkeypatch, width, height):
    """第五组：最小化态「刮削结束后自动退出软件」右移到「隐藏菜单栏图标（Mac）」。

    锚点自身必须原地不动——它是第四组需求②的目标（窄态对齐「显示字段内容信息」），
    本段只钉第 2 行的前导项 checkBox_auto_start，不碰第 8 行的 gap_b，故这里对照
    「只有通用宽幅逻辑」的基线逐位核对锚点未动、Fixed 前缀两项未动。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0

    (target, anchor) = _NARROW_AUTO_EXIT[0]
    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    got = _abs(ui, getattr(ui, target))
    want = _abs(ui, getattr(ui, anchor))
    assert got == want, f"窄态 {width} 宽下「{target}」未与「{anchor}」严格上下对齐: x={got} 期望={want}"
    # 锚点位置保持不变：它是第四组需求②的窄态落点（450 → 495），本组需求要的正是
    # 「刮削结束后自动退出软件」跟它对齐，故它不得被本组带偏回自然位；这里核对的是
    # 它在「只有通用宽幅逻辑」的基线**之上**仍停在该组已定的竖线上——已由上面
    # got == want 覆盖。本组只允许动第 2 行的两枚控件，故第 8 行的 Fixed 前缀必须
    # 逐位不动（menu_icon 自身是第四组目标，不在此列）。
    for name in ("checkBox_hide_dock_icon", "label_42"):
        assert _abs(ui, getattr(ui, name)) == base[name][0], (
            f"窄态 {width} 宽下第五组不该动的 Fixed 前缀「{name}」被带偏: 基线={base[name][0]}"
            f" 实际={_abs(ui, getattr(ui, name))}"
        )
    for name in ("checkBox_auto_start", "checkBox_auto_exit", "checkBox_hide_menu_icon"):
        box = getattr(ui, name)
        assert box.width() >= box.sizeHint().width(), (
            f"窄态 {width} 宽下「{name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )
    # 第 2 行的钉宽恰为「目标列 - 行左缘 - 间隔」，不多留也不压缩
    lay_2 = ui.horizontalLayout_102
    pin_m = _abs(ui, ui.checkBox_hide_menu_icon) - _abs(ui, ui.checkBox_show_dialog_exit) - lay_2.spacing()
    assert ui.checkBox_auto_start.width() == pin_m, (
        f"窄态 {width} 宽下 checkBox_auto_start 钉宽={ui.checkBox_auto_start.width()} 期望={pin_m}"
    )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_round_trip_matches_first_pass(win, app, width, height):
    """窄→宽→窄往返：整页几何、提示词、控件提示必须与第一遍逐像素一致。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    first = _snapshot(ui)
    first_statics = _statics(ui)

    _resize(win, app, 1920, 1170)
    assert _extra(win) > 0, "往返中途应处于宽态"
    _resize(win, app, width, height)

    assert _snapshot(ui) == first, "往返后窄态几何漂移"
    assert _statics(ui) == first_statics, "往返后窄态提示词/控件提示漂移"

    # 钉宽状态：窄态钉住的是各行被搬运的前导项；宽态才钉的仍须解除。
    #   窄态钉：radioButton_log_on / radioButton_update_on（两枚「关」的搬运工）、
    #           radioButton_hide_close / radioButton_hide_mini（「隐藏窗口」行）、
    #           checkBox_show_dialog_exit（第 6 行搬运工，两态都钉）、
    #           checkBox_hide_window_title（第 9 行搬运工，窄态走「钉前导项」那条路）、
    #           checkBox_auto_start（第五组：钉它把「刮削结束后自动退出软件」推到
    #               「隐藏菜单栏图标」那一列；**宽态也钉**、只是钉宽不同）
    #   随态切换：checkBox_hide_actor_nav / checkBox_hide_nfo_nav（隐藏入口行）
    for name in (
        "radioButton_log_on",
        "radioButton_update_on",
        "radioButton_hide_close",
        "radioButton_hide_mini",
        "checkBox_show_dialog_exit",
        "checkBox_hide_window_title",
        "checkBox_auto_start",
    ):
        box = getattr(ui, name)
        assert box.minimumWidth() == box.maximumWidth() > 0, f"窄态「{name}」的钉宽缺失或未生效"

    # 第四组需求①那一段随第七组撤销：调试模式行两项窄态不再被钉宽，
    # 且还原回自然位（这条正是「显示字段来源信息位置保持不变」的钉宽侧证据）。
    for name in ("checkBox_show_web_log", "checkBox_show_from_log", "checkBox_show_data_log"):
        assert getattr(ui, name).maximumWidth() == _QWIDGETSIZE_MAX, f"窄态「{name}」的钉宽未解除"

    # 隐藏入口行：钉没钉由「前导项装不装得下自己的字」决定（第七组的可行性门槛），
    # 两种结果都必须自洽——钉了钉宽 == pin、且 nfo 被钉回自己的 sizeHint；
    # 没钉则两者都回到 (0, QWIDGETSIZE_MAX)。
    row = _nav_row(ui, "checkBox_show_from_log")
    actor, nfo = ui.checkBox_hide_actor_nav, ui.checkBox_hide_nfo_nav
    if row["feasible"]:
        assert (actor.minimumWidth(), actor.maximumWidth()) == (row["pin"], row["pin"]), (
            f"窄态隐藏入口行判为可行却没钉前导项: {(actor.minimumWidth(), actor.maximumWidth())}"
        )
        assert (nfo.minimumWidth(), nfo.maximumWidth()) == (nfo.sizeHint().width(), nfo.sizeHint().width()), (
            f"窄态隐藏入口行可行却没把 nfo 钉回 sizeHint: {(nfo.minimumWidth(), nfo.maximumWidth())}"
        )
    else:
        for name in ("checkBox_hide_actor_nav", "checkBox_hide_nfo_nav"):
            box = getattr(ui, name)
            assert box.minimumWidth() == 0 and box.maximumWidth() == _QWIDGETSIZE_MAX, (
                f"窄态隐藏入口行判为放不下（pin={row['pin']}）却仍钉着「{name}」: "
                f"min={box.minimumWidth()} max={box.maximumWidth()}"
            )


def test_round_trip_is_stable(win, app):
    """最大化↔最小化往返 3 轮：窄态快照、宽态对齐结果都不许漂移。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    _resize(win, app, 1030, 753)
    assert _extra(win) <= 0
    for target, anchor in _NARROW_TARGETS + _NARROW_AUTO_EXIT:
        assert _abs(ui, getattr(ui, target)) == _abs(ui, getattr(ui, anchor)), (
            f"窄态「{target}」未与「{anchor}」严格上下对齐"
        )
    narrow = _snapshot(ui)
    statics = _statics(ui)
    _resize(win, app, 1920, 1170)
    all_pairs = _TARGETS + _LEFT_TARGETS
    wide = {target: _abs(ui, getattr(ui, target)) - _abs(ui, getattr(ui, anchor)) for target, anchor in all_pairs}

    for _ in range(3):
        _resize(win, app, 1030, 753)
        assert _snapshot(ui) == narrow, "往返后窄态几何漂移"
        assert _statics(ui) == statics, "往返后提示词/控件提示漂移"
        _resize(win, app, 1920, 1170)
        now = {target: _abs(ui, getattr(ui, target)) - _abs(ui, getattr(ui, anchor)) for target, anchor in all_pairs}
        assert now == wide, f"往返后宽态对齐偏移漂移: {wide} -> {now}"


def test_repeated_sync_is_idempotent(win, app):
    """重复调用全量同步不应再改动任何几何（钉宽已封死成终态）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    for width, height in _WIDE_SIZES + _NARROW_SIZES:
        _resize(win, app, width, height)
        before = _snapshot(ui)
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
            assert _snapshot(ui) == before, f"{width} 宽下重复同步仍在改几何: {before} -> {_snapshot(ui)}"


# ---------------------------------------------------------------------------
# 窄态需求：「每次间隔」时长框右缘缩到与「间歇刮削」文件数框右缘严格对齐
#   （锚点行及其余控件一律不动；最大化态一个像素都不碰）
# ---------------------------------------------------------------------------

# 本组覆盖的两行全部控件（最大化基线比对与窄态断言共用一份名单）。
_REST_ROW_NAMES = (
    "label_321",
    "checkBox_rest_scrape",
    "lineEdit_rest_count",
    "label_52",
    "lineEdit_rest_time",
    "label_71",
    "checkBox_timed_scrape",
    "lineEdit_timed_interval",
    "label_84",
)
_QWIDGETSIZE_MAX = 16777215


def _right(ui, widget) -> int:
    """控件右缘映射到高级页滚动内容的绝对 x（对齐判据一律比右缘、不比左缘）。"""
    return _abs(ui, widget) + widget.width()


def _rest_row_snapshot(ui):
    return {n: (_abs(ui, getattr(ui, n)), getattr(ui, n).width()) for n in _REST_ROW_NAMES}


def _baseline_without_rest_interval_align(win, app, monkeypatch, width, height):
    """另起窗口、只摘掉本次新增的那个控制器，量同一组控件的几何（最大化基线）。

    不能在同一个窗口上摘掉方法再跑一次同步——摘掉后就没人解除上一遍留下的钉宽
    （setFixedWidth 落在控件自身的 min/max 上、跨调用留存），量到的「基线」会带着
    上一遍的落点，比对就成了自己对自己（与 _without_feature 同一个坑）。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    original = mw_mod.MyMAinWindow._sync_advanced_page_rest_interval_align
    monkeypatch.setattr(
        mw_mod.MyMAinWindow,
        "_sync_advanced_page_rest_interval_align",
        lambda self, *a, **k: None,
    )
    probe = None
    try:
        probe = mw_mod.MyMAinWindow()
        for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
            getattr(probe, timer_name).stop()
        probe.show()
        _goto_advanced(probe, app)
        _resize(probe, app, width, height)
        return _rest_row_snapshot(probe.Ui)
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        monkeypatch.setattr(
            mw_mod.MyMAinWindow,
            "_sync_advanced_page_rest_interval_align",
            original,
        )


def _unpin(widget) -> None:
    """解除钉宽（不是 setFixedWidth(0)——那会把控件压成零宽）。"""
    widget.setMinimumWidth(0)
    widget.setMaximumWidth(_QWIDGETSIZE_MAX)


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_timed_interval_right_edge_matches_rest_count(win, app, width, height):
    """窄态：「每次间隔」时长框右缘 == 「间歇刮削」文件数框右缘，锚点自身不动。

    根因：hl109（间歇刮削）比 hl104（每次间隔）长，窄态先放不下的是 hl109，
    而行内标签的 minimumSizeHint == sizeHint（一格不让）、QLineEdit 的 sizePolicy
    是 Fixed（压得动），故被压的只有 hl109 里那两枚输入框；hl104 那行仍有余量、
    它的时长框保持满宽，右缘于是越过上面那枚——用户红线标出的那截参差。

    本离屏环境**没有 CJK 字体**、字形宽度不可靠（见文件头 _EXTRA_NAMES 那段），
    「哪一档窗宽真的开始挤压」在测试环境与生产未必同档，故断言不写成
    「窗口一窄就必须变窄」那种依赖字体的形式，而是：
      ① 自然态右缘必须相等（本来就等宽时自然成立，被挤压时正是本需求在修）；
      ② **显式模拟挤压**（把锚点钉窄，等价于 Qt 对 hl109 的处置），断言此时
         时长框必须跟着缩到同一右缘、锚点自己一个像素都不许动、且必须是
         「钉宽」而不是「恰好排成这样」。这一条才是判别力所在：还原掉
         本方法它必红。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    anchor = ui.lineEdit_rest_count
    target = ui.lineEdit_timed_interval

    # ① 自然态：右缘必须相等（未发生挤压时两边本就等宽，相等自然成立）
    assert _right(ui, target) == _right(ui, anchor), (
        f"{width} 宽下「每次间隔」右缘 {_right(ui, target)} 未与「间歇刮削」文件数框右缘 {_right(ui, anchor)} 对齐"
    )

    # ② 模拟 hl109 被挤压：锚点收窄 24px，时长框必须跟着缩
    squeeze = max(anchor.minimumSizeHint().width(), anchor.sizeHint().width() - 24)
    anchor.setFixedWidth(squeeze)
    before = (anchor.x(), anchor.y(), anchor.width(), anchor.height())
    _resize(win, app, width, height)
    assert (anchor.x(), anchor.y(), anchor.width(), anchor.height()) == before, (
        f"{width} 宽下本需求不许移动锚点「间歇刮削」文件数框"
    )
    assert anchor.width() == squeeze
    assert _right(ui, target) == _right(ui, anchor), (
        f"{width} 宽下模拟挤压后「每次间隔」右缘 {_right(ui, target)} 未跟上锚点右缘 {_right(ui, anchor)}"
    )
    assert target.width() == squeeze, "两框同为各自行的第二项、左缘同列，收窄后应等宽"
    # 钉宽而不是「恰好排成这样」：min == max 才说明真走了 setFixedWidth 那条路
    assert target.minimumWidth() == target.maximumWidth() == squeeze

    # ③ 解除「人为模拟」后仍是对齐的。注意离屏环境下 hl109 本来就放不下、锚点
    #    自然就被压窄，于是目标照样被钉——那正是**正确**的落点，不能断言「已解除钉宽」
    _unpin(anchor)
    _resize(win, app, width, height)
    _resize(win, app, width, height)
    assert _right(ui, target) == _right(ui, anchor), f"{width} 宽下往返后右缘对齐漂移"


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_timed_interval_not_pinned_when_row_fits(win, app, width, height):
    """锚点比目标还宽（即不需要收窄的那半条）时不得钉宽。

    「不需要就保持自然态」是无条件钉宽的反面：无条件钉等于让 hl104 右侧的长
    说明标签白白左移、把「每次间隔」框无端变窄。判据用 sizeHint()——钉宽状态
    下量到的 width() 是上一遍留下的钉宽、不是自然宽，而 sizeHint 恰是 Fixed
    策略下输入框的自然宽。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0

    anchor = ui.lineEdit_rest_count
    target = ui.lineEdit_timed_interval
    anchor.setFixedWidth(target.sizeHint().width() + 60)  # 锚点比目标还宽 -> 无需收窄
    try:
        _resize(win, app, width, height)
        assert target.minimumWidth() == 0 and target.maximumWidth() == _QWIDGETSIZE_MAX, (
            f"{width} 宽下不需要对齐却钉了宽: min={target.minimumWidth()}"
        )
    finally:
        _unpin(anchor)
    _resize(win, app, width, height)


@pytest.mark.parametrize("width,height", ((900, 700), (820, 700)))
def test_timed_interval_never_widened(win, app, width, height):
    """极窄窗宽下即便两行都放不下，也只允许向左缩、绝不许把目标撑宽。

    需求原话是「最右侧向左缩进」，故钉宽只在 `want < 当前宽` 时生效。行内可用
    余量为负时 hl104 自己也会被压、目标反而可能比锚点更窄，此时维持自然态即可
    （硬撑宽只会把末尾说明文字顶出去裁掉）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0

    target = ui.lineEdit_timed_interval
    hint = target.sizeHint().width()
    assert target.width() <= hint, f"{width} 宽下目标被撑宽到 {target.width()}（自然 {hint}）"


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_timed_interval_untouched_in_wide(win, app, monkeypatch, width, height):
    """最大化态：两枚时长框本来就都满宽，本需求一个像素都不许碰。

    比对方式是「摘掉本控制器的另一个窗口」而非「同一窗口摘了再跑一次」：
    后者量到的基线会带着本方法上一遍留下的钉宽，比对就成了自己对自己。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    target = ui.lineEdit_timed_interval
    assert target.minimumWidth() == 0 and target.maximumWidth() == _QWIDGETSIZE_MAX
    assert _rest_row_snapshot(ui) == _baseline_without_rest_interval_align(win, app, monkeypatch, width, height), (
        f"{width} 宽下本需求动了最大化态的控件几何"
    )


def test_rest_interval_alignment_survives_round_trip(win, app):
    """窄→宽→窄往返：窄态右缘对齐不得漂移，且不残留上一态的钉宽。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    anchor = ui.lineEdit_rest_count
    target = ui.lineEdit_timed_interval

    _resize(win, app, 1030, 753)
    squeeze = max(anchor.minimumSizeHint().width(), anchor.sizeHint().width() - 24)
    anchor.setFixedWidth(squeeze)
    _resize(win, app, 1030, 753)
    assert _right(ui, target) == _right(ui, anchor)

    # 最大化：钉宽必须被真解除（min/max 回到 0 / QWIDGETSIZE_MAX）
    _resize(win, app, 1920, 1170)
    assert target.minimumWidth() == 0 and target.maximumWidth() == _QWIDGETSIZE_MAX

    _unpin(anchor)
    _resize(win, app, 1030, 753)
    assert _right(ui, target) == _right(ui, anchor)
