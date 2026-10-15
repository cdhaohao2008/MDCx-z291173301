import html
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFontMetricsF,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSystemTrayIcon,
    QTreeWidgetItem,
)

from mdcx.base.file import (
    get_success_list,
    save_remain_list,
)
from mdcx.base.web import RemoteVersion
from mdcx.config.resources import resources
from mdcx.consts import LOCAL_VERSION, VERSION_NAME
from mdcx.core.naming import NameRenderOptions, NamingTarget, render_name
from mdcx.image import PreviewImageLoader
from mdcx.models.flags import Flags
from mdcx.models.model_types import CrawlersResult, FileInfo, OtherInfo, ShowData
from mdcx.signals import signal_qt
from mdcx.views.CustomClass import CustomScrollArea
from mdcx.views.MDCx import Ui_MDCx

from ..cut_window import CutWindow
from .actor_db import ActorDbMixin
from .actor_info import ActorInfoMixin
from .auto_scrape import AutoScrapeMixin
from .cookie_checks import CookieChecksMixin
from .dock_layout import DockLayoutMixin
from .folder_select import FolderSelectMixin
from .handlers import show_netstatus
from .health_check import run_startup_health_checks
from .init import (
    Init_QSystemTrayIcon,
    Init_Singal,
    Init_Ui,
    apply_ui_scale_option_limits,
    init_QTreeWidget,
)
from .layout_actor import LayoutActorMixin
from .layout_download import LayoutDownloadMixin
from .layout_master import LayoutMasterMixin
from .layout_nfo_overlay import LayoutNfoOverlayMixin
from .layout_nfo_page import LayoutNfoPageMixin
from .layout_settings import LayoutSettingsMixin
from .layout_text_groups import LayoutTextGroupsMixin
from .load_config import load_config
from .logs import LogPageMixin
from .navigation import NavigationMixin
from .net_check import NetCheckMixin
from .nfo_editor import NfoEditorMixin
from .nfo_lib_layout import NfoLibLayoutMixin
from .nfo_library_handlers import NfoLibHandlersMixin
from .result_actions import ResultActionsMixin
from .result_tree import ResultTreeMixin
from .save_config import save_config
from .scrape_cache import ScrapeCacheMixin
from .scrape_control import ScrapeControlMixin
from .settings_actions import SettingsActionsMixin
from .style import set_dark_style, set_style
from .success_list import SuccessListMixin
from .tips import TipsMixin
from .tool_page import ToolPageMixin
from .window_ops import WindowOpsMixin

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent


# 检测网络面板「=」分隔线的字符数上下限与兜底值。QSS 里 #textBrowser_net_main 是
# Consolas 13px 等宽（实测单字宽 7px），按可视宽取整除即可铺满右边缘。
_NET_SEP_FALLBACK = 88  # 量不到可视宽时的历史值
_NET_SEP_MIN = 40  # 极窄窗口下的下限，保证不塌成一条短杠
_NET_SEP_MAX = 400  # 超宽屏兜顶，避免误量出成百上千个
_NET_SEP_VIEWPORT_SLACK = 64  # 可视宽与控件宽的合法差（边框 + QSS padding + 滚动条）
_NET_SEP_TEXT_PADDING = 4  # QSS `padding: 2px, 2px` 的左右合计
_NET_SEP_SCROLLBAR_FALLBACK = 16  # 量不到滚动条宽时的兜底（QSS 里竖向滚动条固定 16px）


class MyMAinWindow(
    ActorDbMixin,
    ActorInfoMixin,
    AutoScrapeMixin,
    CookieChecksMixin,
    DockLayoutMixin,
    FolderSelectMixin,
    LayoutActorMixin,
    LayoutDownloadMixin,
    LayoutMasterMixin,
    LayoutNfoOverlayMixin,
    LayoutNfoPageMixin,
    LayoutSettingsMixin,
    LayoutTextGroupsMixin,
    LogPageMixin,
    NavigationMixin,
    NetCheckMixin,
    NfoEditorMixin,
    NfoLibHandlersMixin,
    NfoLibLayoutMixin,
    ResultActionsMixin,
    ResultTreeMixin,
    ScrapeCacheMixin,
    ScrapeControlMixin,
    SettingsActionsMixin,
    SuccessListMixin,
    TipsMixin,
    ToolPageMixin,
    WindowOpsMixin,
    QMainWindow,
):
    # 检测网络面板首屏只发一次；分隔线字符数随之只量一次并缓存（两态相同）。
    _net_startup_emitted = False
    _net_separator_chars_cache: int = 0
    # 检测报告内分隔线的字符数：必须在**主线程**点按钮时量好存这里——检测跑在
    # 工作线程里，不能去碰文本框（Qt 控件非线程安全）。worker 只读这个整数。
    _net_report_sep_chars: int = 0

    # region 信号量
    main_logs_show = pyqtSignal(str)  # 显示刮削日志信号
    main_logs_clear = pyqtSignal(str)  # 清空刮削日志信号
    req_logs_clear = pyqtSignal(str)  # 清空请求日志信号
    main_req_logs_show = pyqtSignal(str)  # 显示刮削后台日志信号
    net_logs_show = pyqtSignal(str)  # 显示网络检测日志信号
    set_javdb_cookie = pyqtSignal(str)  # 加载javdb cookie文本内容到设置页面
    set_javdb_status = pyqtSignal(str)  # javdb 检查状态更新
    set_fc2ppvdb_status = pyqtSignal(str)  # fc2ppvdb 检查状态更新
    set_javbus_cookie = pyqtSignal(str)  # 加载javbus cookie文本内容到设置页面
    set_javbus_status = pyqtSignal(str)  # javbus 检查状态更新
    exec_save_config = pyqtSignal()  # 主线程执行保存配置
    set_label_file_path = pyqtSignal(str)  # 主界面更新路径信息显示
    set_pic_pixmap = pyqtSignal(list, list)  # 主界面显示封面、缩略图
    set_pic_text = pyqtSignal(str)  # 主界面显示封面信息
    change_to_mainpage = pyqtSignal(str)  # 切换到主界面
    request_preview_images = pyqtSignal(str, str)  # 主线程刷新封面/缩略图预览（poster_path, thumb_path）
    label_result = pyqtSignal(str)
    pushButton_start_cap = pyqtSignal(str)
    pushButton_start_cap2 = pyqtSignal(str)
    pushButton_start_single_file = pyqtSignal(str)
    pushButton_add_sub_for_all_video = pyqtSignal(str)
    pushButton_show_pic_actor = pyqtSignal(str)
    pushButton_add_actor_info = pyqtSignal(str)
    pushButton_add_actor_pic = pyqtSignal(str)
    pushButton_add_actor_pic_kodi = pyqtSignal(str)
    pushButton_del_actor_folder = pyqtSignal(str)
    pushButton_check_and_clean_files = pyqtSignal(str)
    pushButton_move_mp4 = pyqtSignal(str)
    pushButton_find_missing_number = pyqtSignal(str)
    pushButton_cover_backfill_start = pyqtSignal(str)
    pushButton_actor_db_translate = pyqtSignal(str)
    pushButton_actor_db_link = pyqtSignal(str)
    pushButton_actor_db_sync_aliases = pyqtSignal(str)
    pushButton_actor_db_fill_Minnano = pyqtSignal(str)
    pushButton_actor_db_fill_zh_javdb = pyqtSignal(str)
    pushButton_actor_db_clean_male = pyqtSignal(str)
    pushButton_actor_db_verify_tmdbid = pyqtSignal(str)
    pushButton_actor_db_check = pyqtSignal(str)
    pushButton_actor_db_update_nfo_tmdbid = pyqtSignal(str)
    actor_db_finished = pyqtSignal(str)  # task_id；空串表示恢复所有按钮
    label_show_version = pyqtSignal(str)
    version_check_done = pyqtSignal(bool)  # 版本检查完成（参数为是否有新版本），主线程执行 UI 操作
    net_check_done = pyqtSignal()  # 网络检测完成，主线程恢复按钮状态
    net_check_progress = pyqtSignal(int, int)  # 网络检测单项完成 (done, total)，主线程刷新按钮进度文本
    nfo_lib_data_loaded = pyqtSignal(str)  # NFO 库管理：后台读取 NFO 完成，主线程填充表单
    nfo_lib_images_changed = pyqtSignal(str)  # NFO 库管理：信息管理页裁剪封面完成，主线程只刷新两张预览图（不切页）
    nfo_lib_save_done = pyqtSignal(str)  # NFO 库管理：后台保存完成，主线程恢复按钮
    nfo_lib_batch_done = pyqtSignal(str)  # NFO 库管理：批量操作完成，主线程更新状态
    nfo_lib_batch_progress = pyqtSignal(str)  # NFO 库管理：批量操作进度，主线程更新标签

    # endregion

    def __init__(self, parent=None):
        super().__init__(parent)

        # region 初始化需要的变量
        self.localversion = LOCAL_VERSION  # 当前版本号(数值, 用于版本比较)
        self.version_display = f"{VERSION_NAME} ({LOCAL_VERSION})"  # 展示用: v2.0.0 (220260712)
        self.new_version = "\n🔍 点击检查最新版本"  # 有版本更新时在左下角显示的新版本信息
        self._notified_new_version: RemoteVersion | None = (
            None  # 已提示过的远端版本：12h 定时复查仅在发现更新的版本时再提示，避免同一版本重复刷屏
        )
        # 以下属性的类型由对应 mixin 内的赋值推定，此处仅声明可空初值，故需要 ignore
        self.show_data: ShowData | None = None  # type: ignore[assignment]  # 当前树状图选中文件的数据
        self.img_path = None  # 当前树状图选中文件的图片地址
        self.m_drag = False  # 允许鼠标拖动的标识
        self.m_DragPosition: QPoint | None = None  # 鼠标拖动位置
        self.logs_counts = 0  # 日志次数（每1w次清屏）
        self.req_logs_counts = 0  # 日志次数（每1w次清屏）
        self._log_page_opened = False  # 日志页是否被打开过：首次打开滚动条默认置顶，后续保留上次位置
        self.main_log_queue: deque[str] = deque()
        self.main_log_batch_size = 80
        self.main_log_max_count = 10000
        self.network_check_cancel_event: threading.Event | None = None
        self.network_check_future = None
        self.file_main_open_path = Path()  # 主界面打开的文件路径
        self.json_array: dict[str, ShowData] = {}  # 主界面右侧结果树状数据
        self.preview_request_id = 0  # 主界面图片预览请求序号，用于丢弃过期加载结果
        # 议题 #144: 原图 pixmap 缓存, 显示层按封面/缩略图框当前尺寸重缩放
        # (最大化时框同步放大图片随之放大; resize/切番共用同一缩放出口)
        self._poster_src_pixmap: QPixmap | None = None
        self._thumb_src_pixmap: QPixmap | None = None
        self._did_apply_initial_size = False
        self._user_initiated_close = False  # 标记是否为用户主动关闭窗口
        self._naming_design: dict | None = None  # type: ignore[assignment]  # 命名页模板预览区：首次登记的设计几何基准
        self._naming_resyncing = False  # 命名页模板预览区：重算中标志（防 label resize 递归触发）
        self._naming_last_width = -1  # 命名页说明文字上次同步所用的宽度
        # 渲染扫描重入门闩：lbl.render() 会派发 Resize 重入 eventFilter 而 eventFilter
        # 又同步调 _naming_label_painted_height，不设闩会无限递归爆栈（见其 docstring）。
        self._naming_scanning = False
        self._naming_fix_tries = 0  # 同一宽度下的重算次数上限，防止布局压不下时反复排队
        self._fanyi_design: dict | None = None  # type: ignore[assignment]  # 翻译页两组：首次登记的设计几何基准
        self._fanyi_resyncing = False  # 翻译页两组：重算中标志（防标签 resize 递归触发）
        self._defn_resyncing = False  # 命名页画质组：重算中标志（防标签 resize 递归触发）
        self._defn_last_width = -1  # 命名页画质组说明文字上次同步所用宽度（宽度变了才重排）
        self._actor_scroll = None  # 设置-演员页的 CustomScrollArea（对齐判据要读它的视口宽）
        self._nfo_scroll = None  # 设置-NFO页的 CustomScrollArea（右列对齐的钩子宿主）
        self._adv_scroll = None  # 设置-高级页的 CustomScrollArea（四行对齐的钩子宿主）
        self._guaxiaomulu_scroll = None  # 设置-刮削目录页的 CustomScrollArea（文件清理提示对齐的钩子宿主）
        self._zimu_scroll = None  # 设置-字幕页的 CustomScrollArea（底部空白收缩的钩子宿主）
        self._xiazai_scroll = None  # 设置-下载页的 CustomScrollArea（两行复选框对齐的钩子宿主）
        self._zimu_dl_spacer = None  # 字幕页下载行插在 label_102 与「点击下载字幕包」之间的固定间隔
        # 演员信息组三列对齐注入的间隔项 [(布局, QSpacerItem)]，每遍同步先清后建（幂等）
        self._actor_info_spacers = []
        # 钉位时为防 Minimum 策略被间隔挤瘦而 setFixedWidth 的控件 [(控件, 原宽)]，还原时解锁
        self._actor_info_width_locks = []
        # 钉位时归零的行左内边距 [(布局, 原 QMargins)]，还原时复位
        self._actor_info_margin_restores = []
        # 窄态右移对齐注入的间隔项 [(布局, QSpacerItem)]，每遍同步先清后建（幂等）
        self._actor_narrow_spacers = []
        # 窄态右移对齐改过的持久设置 [("size", 控件, (原min, 原max)) / ("stretch", 布局, 原stretch元组)]，
        # 还原时原样写回。刻意与 _actor_info_width_locks 分开：本方法跑在
        # _sync_actor_info_columns 之后，若复用那边的列表并 setFixedWidth(0)「解锁」，
        # 会顺手拆掉那一拍刚钉好的 253/252 宽态铺排。
        self._actor_narrow_restores = []
        # 最大化态 A2 列对齐改过的持久设置 [("size", 控件, (原min, 原max)) /
        # ("geometry", 控件, 原 QRect) / ("stretch", 布局, 原stretch元组)]，
        # 窄态第一步原样写回；同样与前两套登记分开，且必须逆序写回。
        self._actor_wide_restores = []
        # 命名页画质行注入的间隔 [(布局, QSpacerItem)] + 容器加宽登记
        # [("width", 容器, 原宽)]，每遍同步先清后建（幂等）。注意容器是绝对定位，
        # 恢复 min/max 收不回宽度，必须按原宽写回。
        self._naming_defn_spacers = []
        self._naming_defn_restores = []
        # 命名页窄态左移登记 [(控件, 原x)]：最小化时三个复选框左移到 path 列，
        # 最大化时原样写回（宽态锚点即设计位置）。每遍先清后建，幂等往返自愈。
        self._naming_narrow_restores = []
        # 水印页网格列登记 [("colmin", 网格, (列, 原最小宽)) / ("colstretch", 网格, 列)]，
        # stretch 无 getter，还原时一律写回 0（默认值，本仓库无他处改动该列 stretch）
        self._watermark_col_restores = []
        # 水印页 col1 四行尾部补的 Expanding 间隔 [(行布局名, QSpacerItem)]，还原时摘掉
        self._watermark_tail_spacers = []
        # 水印页宽态右移对齐注入的固定间隔 [(行布局名, QSpacerItem)]，还原时摘掉
        self._watermark_shift_spacers = []
        # NFO页目标列对齐：两项行（horizontalLayout_135）宽态尾部补的 Expanding
        # 间隔（两项全钉死后无处吸收富余，QHBoxLayout 会把富余摊进三个间隙；
        # 三项行末项 Minimum 自然吸收，无需补），还原时摘掉
        self._nfo_target_col_tails = []
        # NFO页目标列对齐是否处于宽态生效中。生效时 C1 列最小宽归本方法所有，
        # 右列控制器必须跳过（它每遍先清零 C1min，生效中跑它会把本钉宽洗掉；
        # 且判据 critic.x>custom.x 在生效中恒为假，它本就是 no-op）。
        # 失效（窄态/复位/放不下）时由本方法先清标志再调它接管，保证 C1 有主。
        self._nfo_target_col_active = False
        # NFO页目标列对齐重入守卫：宽态循环里泵事件会触发嵌套全量同步，嵌套的
        # 本方法直接返回（外层循环的泵+重测会覆盖嵌套跳过的一切情况），防止递归。
        self._nfo_target_col_running = False
        # NFO页目标列对齐 trailing 节拍计数：慢路径动过手（应用过钉宽）即排一拍
        # 全量同步（慢路径收敛的只是当前拍内的几何；滚动区/内容宽度的后续生长、
        # 如 lw10w 1509→1589，会在退出后才落定，必须有一拍跑在它后面）。
        # 快路径/窄态/defer 即清零；上限 8 拍防抖荡；下一拍收敛即停排。
        self._nfo_target_col_trailing = 0
        self._zimu_dl_gap = -1  # 该间隔当前生效的宽度（-1 = 未安装/已拆除）
        self._nfo_colon_cal: tuple | None = None  # NFO冒号对齐：(字体样式key, 组标题冒号x, 行标签右pad)，像素标定缓存
        self._adv_dock_spacer = None  # 高级页隐藏图标行插在 label_42 与「隐藏菜单栏图标」之间的固定间隔
        self._adv_dock_gap = -1  # 该间隔当前生效的宽度（-1 = 从未设置）

        self.window_radius = 0  # 窗口四角弧度，为0时表示显示窗口标题栏
        self.window_border = 0  # 窗口描边，为0时表示显示窗口标题栏
        # 议题 #69: 恢复系统标题栏最大化按钮(议题 #67 曾按报告人要求禁用)。
        # #62/#66/#68 的最大化布局错乱根因(缩放三连)已在当时修复:
        # resizeEvent → _sync_page_layouts 会统一同步所有休眠页与内部组件,
        # 最大化路径由 tests/test_window_state_matrix.py 的最大化用例回归锁定。
        # 历史陷阱记录: setWindowFlags 触发 changeEvent, 若在 window_radius 等属性
        # 初始化前调用会在事件处理器内抛 AttributeError(PyQt6 qFatal abort 的形态之一)。
        # 当前无 setWindowFlags 调用, 此陷阱仅作为后续改动的注意事项保留。
        self.dark_mode = False  # 暗黑模式标识
        self.check_mac = True  # 检测配置目录
        self._actor_db_running: set[str] = set()  # 正在运行的 actor_db 异步任务的 btn_attr 集合
        self._nfo_lib_current_path: Path | None = None  # NFO 库管理：当前选中的 NFO 路径
        self._nfo_lib_pending_data: CrawlersResult | None = None  # NFO 库管理：后台读取的临时数据
        self._nfo_lib_pending_info: OtherInfo | None = None  # NFO 库管理：后台读取的临时 OtherInfo
        self._nfo_lib_save_result: bool = False  # NFO 库管理：后台保存结果
        self._nfo_lib_batch_result: tuple[int, int, int] = (0, 0, 0)  # NFO 库管理：批量结果 (成功, 失败, 总数)
        self._nfo_lib_original_data: CrawlersResult | None = None  # NFO 库管理：加载时的原始数据（diff 基准）
        self._nfo_lib_poster_pix: QPixmap | None = None  # NFO 库管理：海报原图（预览按 label 边界等比缩放的源）
        self._nfo_lib_thumb_pix: QPixmap | None = None  # NFO 库管理：缩略图原图（同上）
        # self.window_marjin = 0 窗口外边距，为0时不往里缩
        self.show_flag = True  # 是否加载刷新样式

        self.timer = QTimer()  # 初始化一个定时器，用于显示日志
        self.timer.timeout.connect(self.show_detail_log)
        self.timer.timeout.connect(self._flush_main_log_queue)
        self.timer.start(100)  # 设置间隔100毫秒
        self.timer_scrape = QTimer()  # 初始化一个定时器，用于间隔刮削
        self.timer_scrape.timeout.connect(self.auto_scrape)
        self.timer_update = QTimer()  # 初始化一个定时器，用于检查更新
        self.timer_update.timeout.connect(self.show_version)
        self.timer_update.start(43200000)  # 设置检查间隔12小时
        self.timer_remain_task = QTimer()  # 初始化一个定时器，用于显示保存剩余任务
        self.timer_remain_task.timeout.connect(save_remain_list)
        self.timer_remain_task.start(1500)  # 设置间隔1.5秒
        self.atuo_scrape_count = 0  # 循环刮削次数
        # endregion

        # region 其它属性声明
        self.threads_list: list[threading.Thread] = []  # 启动的线程列表
        # 移动文件线程的协作式停止事件：移动开始时 clear，停止按钮处理器中 set，
        # _move_files_core 在每个目录/文件检查点轮询（替代已删除的 ctypes 强杀）。
        self._move_cancel_event = threading.Event()
        self.start_click_time = 0
        self.start_click_pos: QPoint
        self.window_marjin = None
        self.now_show_name = None
        self._nfo_editor_snapshot: tuple[str, ...] | None = None  # type: ignore[assignment]
        self.show_name = None
        self.t_net = None
        self.options: QFileDialog.Option
        self.tray_icon: QSystemTrayIcon
        self.item_succ: QTreeWidgetItem
        self.item_fail: QTreeWidgetItem
        # endregion

        # region 初始化 UI
        resources.get_fonts()
        resources.start_data_loading()
        self.Ui = Ui_MDCx()  # 实例化 Ui
        self.Ui.setupUi(self)  # 初始化 Ui
        # 设置-演员页三行的对齐必须在滚动区拉伸的同一个 resizeEvent 里做完，
        # 否则通用拉伸先把它们钉到右缘（中间态），外层下一拍再拉到基准线，
        # 用户会看到「先在右边、再跳到左边」。详见 _sync_actor_page_align 与
        # CustomScrollArea._post_wide_sync_hook。
        # 按内容控件名认页面，不写死滚动区对象名（演员页是 scrollArea_12，
        # scrollArea_9 是字幕页，写死会装错地方、静默失效）。
        for _sa in self.Ui.tabWidget.findChildren(CustomScrollArea):
            _content = _sa.widget()
            if _content is not None and _content.objectName() == "scrollAreaWidgetContents_yanyuan":
                _sa._post_wide_sync_hook = self._sync_actor_page_wide_hooks
                self._actor_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_nfo":
                # NFO 页同病：右列（影评/导演/TMDB/标签）的列最小宽是在「拉伸前」的
                # 几何上量的，那一拍条件不成立就留空，等下一拍才补上 → 用户看到
                # 「先在左边、再向右跳」。挂在拉伸之后的钩子上即可同拍完成。
                _sa._post_wide_sync_hook = self._sync_nfo_page_align
                self._nfo_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_gaoji":
                # 高级页同病：网格里两项均分的行（界面外观行的「暗黑模式」、隐藏入口
                # 行的「隐藏NFO库管理」）会被通用拉伸推到右缘，本控制器下一拍才拉回
                # 基准线 → 用户看到「先在右侧、再向左漂移」（最大化与还原两个方向
                # 各出现一次）。挂在拉伸之后的钩子上即可同拍完成。
                _sa._post_wide_sync_hook = self._sync_advanced_page_wide_hook
                self._adv_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_guaxiaomulu":
                # 刮削目录页同病：文件清理提示 label_271 被通用逻辑判为 _STRETCH
                # （宽 381 ≥ 内宽一半），最大化时宽按「设计宽 + extra」铺开、
                # 文本 AlignCenter 居中，整体右偏到按钮右侧；挂钩子同拍拉回按钮下方。
                _sa._post_wide_sync_hook = self._sync_guaxiaomulu_page_align
                self._guaxiaomulu_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_zimu":
                # 字幕页：内容短（两组底缘 735 + 余量 72），最大化时视口更高，
                # widgetResizable 把内容拉到视口高，组框下方留下大片白色填充；
                # 挂钩子同拍把填充收进末尾组框（见 _sync_zimu_fill_blank）。
                _sa._post_wide_sync_hook = self._sync_zimu_page_align
                self._zimu_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_xiazai":
                # 下载页：两行复选框（groupBox_24「下载」/ groupBox_33「保留旧文件」）
                # 都是「一项均分」但项数不同（7 vs 8），单元格边界必然错开 →
                # 通用拉伸落定后同拍把下载行钉到保留旧文件行的同一条竖线，
                # 否则会看到「先在右边、再向左跳」（同 _sync_advanced_page_wide_hook）。
                _sa._post_wide_sync_hook = self._sync_xiazai_row_align
                self._xiazai_scroll = _sa
        # QStackedWidget 只会把当前可见页 resize 到自身尺寸，休眠页永远停留在设计尺寸；
        # 切页后必须重新同步一次内部几何，否则"先改窗口尺寸再切页"时页面内容全部按陈旧尺寸布局
        self.Ui.stackedWidget.currentChanged.connect(self._sync_page_layouts)
        self.Ui.stackedWidget.currentChanged.connect(self._on_page_change_nfo_panel)
        # 日志页首次打开滚动条默认置顶，后续打开保留上次位置（此处只处理首次）
        self.Ui.stackedWidget.currentChanged.connect(self._on_stacked_page_changed)
        # 命名页在设置页 tab 内：切到该 tab 时滚动区视口宽变化（滚动条占位）会重排
        # 内部网格，需在事件循环下一拍按最新宽度重算模板预览区（见 _sync_naming_template_section）。
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_naming_template_section)
        )
        # 翻译页同款：简介组/演员组的容器高度按实测内容算出，切 tab 引起的视口
        # 变化（滚动条占位）会改掉网格列宽 → 文字折行数变 → 需要重算。
        self.Ui.tabWidget.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._sync_fanyi_group_spacing))
        # 命名页画质组同款：QHD 说明文字的折行数随网格拉伸后的终态宽度变化，
        # 切 tab 下一拍按最新宽度重算收紧（见 _sync_definition_group_spacing）。
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_definition_group_spacing)
        )
        # 设置页 tab 内各页同理：切 tab 下一拍只排队，真活留到再下一拍的全量同步。
        # 实测：切 NFO 页当拍布局 deferred 级联（scrollbar 出现约 14px、宽幅重拉）
        # 要到一批 processEvents 后才落定，直接同步会读到级联前的旧 custom.x
        # （1076 stale，由此 C1min=449 钉错 critic），而全量 pass 自带 page 级
        # 刷新、落定后单遍收敛（1075 对齐 / 显式重跑 459 收敛实测）。
        # 80% 分数缩放下各页签竖向滚动条厚度逐页不等宽（未点开的页签从未被
        # 布局，见 _sync_settings_scrollbar_widths）。排在全量同步之后落定，
        # 量到的才是级联终态厚度
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_settings_scrollbar_widths)
        )
        self.Ui.tabWidget.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._queue_nfo_post_cascade_sync))
        # 首开 NFO 字段说明跳动修复：beats 跑在 paint 之后，首开第一拍常读到
        # 中间态视口（滚动条闪烁）误触发 pin 左移。直连同步 settle（paint 前落定，
        # 循环至稳），beats 留作兜底；休眠时方法内早退零成本。
        self.Ui.tabWidget.currentChanged.connect(self._settle_settings_after_switch)
        # stacked 切页同理：NFO 休眠时 resize/changeEvent 进来的 _sync_page_layouts
        # 会被各 sync 内 isVisibleTo 早退跳过，而切回设置页时 NFO 的 tab 索引没变、
        # tabWidget.currentChanged 根本不触发——NFO 将永远停留在旧几何（用户截图：
        # 窄态下 opl 从未被同步过、以天然位落在 pr 左边；宽态因之前切过 tab 已对齐）。
        # 故 stacked 切页下一拍同样只排队：休眠页由内层守卫 no-op，NFO 可见时在级
        # 联落定后的第二拍补齐（与 tab 钩子同一机制，幂等无累积）。
        self.Ui.stackedWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_settings_scrollbar_widths)
        )
        self.Ui.stackedWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._queue_nfo_post_cascade_sync)
        )
        # 切回设置页（NFO tab 索引不变、无 tab 钩子）同样首帧落定，方法内判
        # 设置页/NFO 可见性，休眠早退；_on_page_change_nfo_panel 取消切页时
        # 已回到主页，守卫直接返回。
        self.Ui.stackedWidget.currentChanged.connect(self._settle_settings_after_switch)
        # 说明文字宽度变化（滚动条占位、休眠页拉伸等）时自动补一次重算。
        self.Ui.label_66.installEventFilter(self)
        # 命名页画质组 QHD 说明（label_331）：只按宽度触发，见 _sync_definition_group_spacing
        # —— 高度由纯宽度函数算出，钉上后立刻自洽，无需「高度对不上」的重入门闩
        # （painted 回扫法在非纯白背景下恒返回自身高度，那种比较只会造成 +2 漂移）。
        self.Ui.label_331.installEventFilter(self)
        # 信息管理页右侧两个预览框：左键单击弹出大图窗口，见 eventFilter 分支
        self.Ui.label_nfo_lib_poster_preview.installEventFilter(self)
        self.Ui.label_nfo_lib_thumb_preview.installEventFilter(self)
        self._bind_system_theme_refresh()
        self.cutwindow = CutWindow(self)
        self.preview_image_loader = PreviewImageLoader(self)
        self.preview_image_loader.loaded.connect(self._apply_preview_images)
        self.Init_Singal()  # 信号连接
        self.Init_Ui()  # 设置Ui初始状态
        self._init_donate_widgets()  # 侧栏「使用说明」下方加收款码 + [赞助作者] 链接
        self.load_config()  # 加载配置
        self._setup_name_template_preview()
        get_success_list()  # 获取历史成功刮削列表
        # endregion

        # region 启动显示信息和后台检查更新
        self.show_scrape_info()  # 主界面左下角显示一些配置信息
        # 检测网络面板的首屏文字（代理状态块 + CF Bypass 提示 + 启动自检）不在这里发，
        # 改由 showEvent 推迟一拍走 _emit_net_startup_panel：分隔线「=」的字符数要按
        # 还原态的真实可视宽算，而此刻窗口还没 resize 到默认尺寸、文本区仍是 .ui 设计宽。
        self.show_version()  # 日志页面显示版本信息
        self.creat_right_menu()  # 加载右键菜单
        self.pushButton_main_clicked()  # 切换到主界面
        self.auto_start()  # 自动开始刮削
        # endregion

    def _setup_name_template_preview(self) -> None:
        self.Ui.plainTextEdit_name_template_preview.setPlainText(
            self.Ui.lineEdit_media_name.text()
            or "{{ number }}{% if studio %} [{{ studio }}]{% endif %} {{ originaltitle }}"
        )
        self.Ui.plainTextEdit_name_template_preview.textChanged.connect(self._update_name_template_preview)
        self._update_name_template_preview()

    def _build_name_preview_sample(self) -> tuple[FileInfo, CrawlersResult]:
        file_info = FileInfo.empty()
        file_info.number = "ABC-123"
        file_info.file_path = Path("D:/Media/Input/ABC-123.mp4")
        file_info.folder_path = file_info.file_path.parent
        file_info.file_name = "ABC-123"
        file_info.definition = "4K"
        file_info.c_word = "-中字"
        file_info.wuma = "-无码"

        result = CrawlersResult.empty()
        result.number = "ABC-123"
        result.title = "中文标题"
        result.originaltitle = "Original Title"
        result.actors = ["演员A", "演员B"]
        result.all_actors = ["演员A", "演员B", "男演员C"]
        result.directors = ["导演A"]
        result.series = "系列A"
        result.studio = "Studio A"
        result.publisher = "发行商A"
        result.release = "2024-01-02"
        result.runtime = "120"
        result.mosaic = "有码"
        result.letters = "ABC"
        result.wanted = "123"
        result.score = "4.5"
        result.outline = "示例简介"
        return file_info, result

    def _update_name_template_preview(self) -> None:
        template = self.Ui.plainTextEdit_name_template_preview.toPlainText()
        if not template.strip():
            self.Ui.label_name_template_preview_result.setText("状态：等待输入模板")
            # 结果文字行数随模板变化，重新贴合一次，否则上次钉的高度会裁字或留白
            self._sync_naming_template_section()
            return
        try:
            file_info, result = self._build_name_preview_sample()
            rendered = render_name(
                template,
                file_info,
                result,
                NameRenderOptions(
                    target=NamingTarget.FILE,
                    show_definition_suffix=False,
                    show_cnword_suffix=False,
                    show_moword_suffix=False,
                    max_length=120,
                ),
            )
        except Exception as exc:
            self.Ui.label_name_template_preview_result.setStyleSheet("color: rgb(190, 0, 0);")
            self.Ui.label_name_template_preview_result.setText("状态：语法错误\n" + html.escape(str(exc), quote=False))
            self._sync_naming_template_section()
            return

        self.Ui.label_name_template_preview_result.setStyleSheet("color: rgb(8, 128, 128);")
        self.Ui.label_name_template_preview_result.setText(
            "状态：语法正确\n"
            f"结果：{html.escape(rendered.text, quote=False)}\n"
            "示例：number=ABC-123, studio=Studio A, originaltitle=Original Title definition=4K"
        )
        self._sync_naming_template_section()

    # region Init
    def Init_Ui(self): ...

    def Init_Singal(self): ...

    def Init_QSystemTrayIcon(self): ...

    def init_QTreeWidget(self): ...

    def load_config(self):
        ...

        # menu.move(pos)
        # menu.show()

    # endregion

    def eventFilter(self, a0, a1):
        # print(event.type())

        if a1.type() == QEvent.Type.MouseButtonRelease:  # 松开鼠标，检查是否在前台
            self.recover_windowflags()
        # 议题 #132：不再在 ApplicationActivate 时自动 show() 隐藏的主窗。
        # 主窗隐藏（托盘图标隐藏 / 关闭到托盘 / 最小化到托盘）都是用户主动行为，
        # 此时操作 Emby 演员管理器等工具会触发 ApplicationActivate，旧逻辑会把隐藏的
        # 主窗拉出前台。恢复显示只由托盘菜单/托盘图标点击（tray_icon_show /
        # tray_icon_click）负责；最小化态由 Qt 自行保持。
        # 议题 #102 曾保留「非最小化隐藏态」的 show()，议题 #132 实测反馈表明托盘
        # 隐藏后操作管理器仍会弹出主窗，故此处改为完全不自动弹出。
        if a0.objectName() == "label_poster" or a0.objectName() == "label_thumb":
            if a1.type() == QEvent.Type.MouseButtonPress:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    self.start_click_time = time.time()
                    self.start_click_pos = a1.globalPosition().toPoint()
            elif a1.type() == QEvent.Type.MouseButtonRelease:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    if not bool(a1.globalPosition().toPoint() - self.start_click_pos) or (
                        time.time() - self.start_click_time < 0.05
                    ):
                        self._pic_main_clicked()
        # 信息管理页右侧预览框：左键单击弹出大图窗口（← → 切同组图片，Esc 关闭）。
        # QLabel 默认不处理鼠标事件，但事件过滤器先于控件自身收到事件，所以照样能接。
        _nfo_preview_kind = None
        if a0 is getattr(self.Ui, "label_nfo_lib_poster_preview", None):
            _nfo_preview_kind = "poster"
        elif a0 is getattr(self.Ui, "label_nfo_lib_thumb_preview", None):
            _nfo_preview_kind = "thumb"
        if _nfo_preview_kind and a1.type() == QEvent.Type.MouseButtonRelease:
            a1 = cast("QMouseEvent", a1)
            if a1.button() == Qt.MouseButton.LeftButton:
                self.nfo_lib_preview_clicked(_nfo_preview_kind)
        if a0 is self.Ui.textBrowser_log_main.viewport() or a0 is self.Ui.textBrowser_log_main_2.viewport():
            if not self.Ui.textBrowser_log_main_3.isHidden() and a1.type() == QEvent.Type.MouseButtonPress:
                self.Ui.textBrowser_log_main_3.hide()
                self.Ui.pushButton_scraper_failed_list.hide()
                self.Ui.pushButton_save_failed_list.hide()
        # 命名页模板预览区：说明文字宽度一变（滚动条占位、窗口拉伸、切页）就重算，
        # 否则上次钉死的高度会残留成「视频文件名」上方的空白。
        # 高度与当前宽度算出的需要值不一致时同样要重算——钉高是在某个瞬间算的，
        # 那一刻标签还比较窄的话，窗口变宽后文字不再折行就会剩下一片死空白，
        # 而宽度没再变过就再也不会触发 Resize 分支。故高度也要校验（重算次数封顶，
        # 避免布局真压不下时无限排队）。
        if a0 is getattr(self.Ui, "label_66", None) and a1.type() == QEvent.Type.Resize:
            # _naming_scanning 是 _naming_label_painted_height 的重入门闩：本分支会同步
            # 调它，而它内部的 lbl.render() 又会派发 Resize 打回这里。不加这道判断时两者
            # 互为递归直到栈溢出（0xC00000FD，无 Python 崩溃日志）。详见该方法 docstring。
            if not self._naming_resyncing and not self._naming_scanning:
                need = self._naming_label_painted_height(a0)
                if a0.width() != self._naming_last_width:
                    self._naming_fix_tries = 0
                if a0.width() != self._naming_last_width or a0.height() != need:
                    if self._naming_fix_tries < 3:
                        self._naming_fix_tries += 1
                        self._naming_last_width = a0.width()
                        QTimer.singleShot(0, self._sync_naming_template_section)
        # 命名页画质组 QHD 说明（label_331）：宽度一变（滚动条占位、窗口拉伸、切页）
        # 就重算，否则上次钉死的高度残留成 HD 行与分辨率行之间的空白。折行数只由
        # 宽度决定，_label_text_height_for_width 是纯函数：钉上后同宽度必得同高，
        # 故只按宽度触发即可立即收敛，无需「高度对不上」的重试（label_66 的 painted
        # 回扫法才需要那一套，见 _naming_label_painted_height 的 docstring）。
        if a0 is getattr(self.Ui, "label_331", None) and a1.type() == QEvent.Type.Resize:
            # 只按宽度触发（label_66 还要校验高度是因为它用 painted 回扫法，级联中途
            # 量到陈旧折行；这里是纯宽度函数，钉上后同宽度必得同高，见方法 docstring）。
            # 宽度变了才排一次队：_defn_last_width 记住上次同步所用宽度，同宽度重复
            # Resize 直接跳过，天然封顶，不需要 label_66 那套重试计数。
            w = a0.width()
            if not self._defn_resyncing and w > 0 and w != self._defn_last_width:
                self._defn_last_width = w
                QTimer.singleShot(0, self._sync_definition_group_spacing)
        # 刮削缓存失败列表：表格/视口宽一变就按 4:2:6:3 重分布列宽，保持无横向滚动条。
        # setColumnWidth 不改变表格自身尺寸，只触发 header 几何变化，不会递归触发此处 Resize，
        # 故直接同步布局（若用 singleShot 延迟一拍，填入多行致视口收缩后断言时仍是旧列宽）。
        # 视口 Resize 也要监听：填入多行后垂直滚动条出现会挤窄视口，此时表格尺寸不变。
        _scrape_tw = getattr(self.Ui, "tableWidget_scrape_cache_failed", None)
        if _scrape_tw is not None and a1.type() == QEvent.Type.Resize:
            if a0 is _scrape_tw or a0 is _scrape_tw.viewport():
                if not getattr(self, "_scrape_cache_layouting", False):
                    self._layout_scrape_cache_columns()
        return super().eventFilter(a0, a1)

    def showEvent(self, a0):
        if not self._did_apply_initial_size:
            self._did_apply_initial_size = True
            self._apply_adaptive_default_size()  # 首次显示时按屏幕自适应默认窗口大小并居中
        # 检测网络面板首屏推迟一拍发：_apply_adaptive_default_size() 里的 resize 只把
        # resizeEvent 排进队列，文本区几何要等该事件被派发才落定（resizeEvent →
        # _sync_page_layouts 里同步 setGeometry）。此刻量到的还是 .ui 设计宽，会让分隔线
        # 多算字符而在默认态折行，故挂 singleShot 等首帧之后再量（见 _net_separator_chars）。
        # 用 _net_startup_emitted 兜住托盘隐藏/再显示时 showEvent 重复触发。
        if not self._net_startup_emitted:
            self._net_startup_emitted = True
            QTimer.singleShot(0, self._emit_net_startup_panel)
        # 拖到别的显示器 / 改分辨率后重算：放不下当前屏幕的高分屏缩放档位要重新隐藏
        apply_ui_scale_option_limits(self.Ui.comboBox_ui_scale, self.screen())
        super().showEvent(a0)

    def _net_separator_chars(self) -> int:
        """检测网络面板「=」分隔线的字符数：量一次并缓存，两态保持相同。

        这段文字是启动时一次性打印的固定字符串，最大化/还原都不会重新渲染，
        故字符数只由首次（还原态）量一次并复用——否则两态字符数会不一致。

        该文本框在 QSS 里是 Consolas 13px 等宽（实测单字宽 7px），按「可视宽 ÷
        单字宽」取整除即可把分隔线铺到右边缘，且不会超出可视宽而折行。

        竖向滚动条必须提前预留：首屏只有几行字，面板装得下、滚动条尚未出现，
        此刻量到的可视宽是「没有滚动条」时的宽度；等用户点【开始检测】把几十行
        站点结果灌进来，滚动条弹出、可视宽会窄掉一个滚动条宽（实测 16px），
        此前发出的分隔线就会超出可视宽、被折成两行。故不论滚动条此刻显不显示，
        一律先扣掉一个滚动条宽度，保证两态都不会折行。
        """
        cached = self._net_separator_chars_cache
        if cached:
            return cached
        browser = self.Ui.textBrowser_net_main
        width = 0
        try:
            viewport = browser.viewport()
            # viewport 宽与控件宽的差只可能是「边框 + QSS padding + 滚动条」，
            # 超出这个范围说明还没随几何落定，改用控件宽兜底。
            if 0 < browser.width() - viewport.width() <= _NET_SEP_VIEWPORT_SLACK:
                # viewport 已排除滚动条占位（显示时），直接用；未显示时预留出来。
                width = viewport.width()
                if not browser.verticalScrollBar().isVisible():
                    width -= self._net_scrollbar_reserve(browser.verticalScrollBar())
            elif browser.width() > 0:
                # 兜底宽（控件宽 - padding）含滚动条占位，需自行扣减。
                width = browser.width() - _NET_SEP_TEXT_PADDING
                bar = browser.verticalScrollBar()
                width -= bar.width() if bar.isVisible() else self._net_scrollbar_reserve(bar)
        except Exception:
            width = 0
        advance = QFontMetricsF(browser.font()).horizontalAdvance("=") if width > 0 else 0
        count = int(width // advance) if advance > 0 else 0
        if count <= 0:
            count = _NET_SEP_FALLBACK
        count = max(_NET_SEP_MIN, min(count, _NET_SEP_MAX))
        self._net_separator_chars_cache = count
        return count

    @staticmethod
    def _net_scrollbar_reserve(bar) -> int:
        """竖向滚动条出现时要占掉的宽度（此刻通常还没显示）。

        QSS 里 `QScrollBar:vertical { width: 16px; }` 是固定宽，`sizeHint()` 能直接
        量到（实测 16）；量不到时退回常量兜底，保证预留一定不为 0。
        """
        try:
            hint = bar.sizeHint().width()
        except Exception:
            hint = 0
        return max(hint, _NET_SEP_SCROLLBAR_FALLBACK)

    def _emit_net_startup_panel(self) -> None:
        """首帧之后发检测网络面板的启动文字（原先在 __init__ 里直接发）。"""
        try:
            sep = self._net_separator_chars()
            self.show_net_info("\n🏠 代理设置在:【软件设置】-【网络】-【网络设置】")
            show_netstatus(sep)  # 检查网络界面显示当前网络代理信息
            self.show_net_info(
                "💡 CF Bypass：【软件设置】-【网络】-【外部CF服务】填写TRAWL/FlareSolverr服务地址，如http://127.0.0.1:8191\n"
                "▶️ 点击右上角【开始检测】按钮开始测试网络连通性"
            )
            signal_qt.add_log("🍯 你可以点击左下角的图标来 显示 / 隐藏 请求信息面板！")
            run_startup_health_checks()  # 启动自检：配置目录可写/代理可达/TMDB key
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # 信息管理页多条件筛选输入框：设计上限（MDCx.py 里
    # maximumSize(180, QWIDGETSIZE_MAX)）与最小化时必须还原到的值。
    # 信息管理顶栏：目录显示框与筛选框在布局里各占一份拉伸（.ui 里
    # horstretch 均为 1），剩余空间永远平分、两框恒等宽，无需运行时换算。
    # 曾用 `_sync_nfo_lib_top_bar()` 按 0.5 比例换算（最大化加宽/还原复位 180），
    # 用户要求两框等宽后删除——布局均分在所有窗口状态下天然成立，无自反馈抖动。

    def resizeEvent(self, a0):
        # 全局 UI 为绝对定位布局（上游遗留），centralwidget 无布局管理器，
        # 窗口缩放时手动同步导航栏/内容区/顶部进度条几何，否则最大化后内容区固定 820x692
        super().resizeEvent(a0)
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        width, height = self.width(), self.height()
        ui.widget_setting.setGeometry(0, 0, 210, height)
        # 左侧背景条是 widget_setting 的子项、设计高仅 700：最大化后父项拉高而它
        # 滞留原高，底部露出父项底色、与上部各页配色断层，故随父项同高同步。
        try:
            ui.left_backgroud_widget.setGeometry(0, 0, 210, height)
        except Exception:
            pass
        self._sync_dock_layout()  # 左侧导航坞 + 贴底状态区（议题 #86/#102/#181）
        ui.stackedWidget.setGeometry(210, 6, max(width - 210 - 2, 400), max(height - 8, 300))
        ui.progressBar_scrape.setGeometry(209, -1, max(width - 211, 100), 7)
        self._sync_page_layouts()  # 同步动态页面的内部尺寸

    # endregion 侧栏收款码

    # 设计态宽度上限（.ui 声明的 maximumSize 宽 = 16000），首次进入时记下，
    # 「读数无意义」分支据此原样交回布局。None = 尚未记下。
    _site_pref_combo_design_max: int | None = None

    # .ui 给 label_232 声明的 maximumSize 高（34px = 两行）的运行时缓存，首次进入
    # 记下，窄态据此原样交回设计约束。None = 尚未记下。
    _site_type_tip_design_max_h: int | None = None

    # activeAppName = AppKit.NSWorkspace.sharedWorkspace().activeApplication()['NSApplicationName'] # 活动窗口的标题

    def set_style(self): ...

    def set_dark_style(self): ...

    # endregion

    # endregion

    # endregion

    # endregion

    # endregion

    # endregion

    # region NFO 库管理

    # endregion

    # text == "■ 停止中"：防抖——用户疯狂点击时静默忽略，避免重复触发 stop 流程

    # self.Ui.treeWidget_number.verticalScrollBar().setValue(self.Ui.treeWidget_number.verticalScrollBar().maximum())
    # self.Ui.treeWidget_number.setCurrentItem(node)
    # self.Ui.treeWidget_number.scrollToItem(node)

    # endregion

    # endregion

    # endregion
    # endregion

    # region 日志页
    # endregion

    # self.Ui.lineEdit_movie_number.setText('')

    # btn_attr → 任务完成后按钮应恢复的 idle 文案
    _ACTOR_DB_IDLE_TEXT_MAP: dict[str, str] = {
        "actor_db_translate": "补全演员中文姓名",
        "actor_db_link": "补全LibreDMM链接",
        "actor_db_sync_aliases": "补全别名",
        "actor_db_fill_minnano": "Minnano-AV补全",
        "actor_db_fill_zh_javdb": "JavDB演员中文名",
        "actor_db_clean_male": "删除所有男性演员",
        "actor_db_verify_tmdbid": "校验TMDB ID字段",
        "actor_db_check": "检查用户演员数据",
        "actor_db_update_nfo_tmdbid": "更新TMDB ID字段",
    }
    # 由 change_buttons_status/reset_buttons_status 管理的 actor_db 按钮子集；
    # 这些按钮在主刮削时被禁用、刮削结束后若未在跑 actor_db 任务则被恢复。
    _ACTOR_DB_SCRAPE_MANAGED: frozenset[str] = frozenset(
        {
            "actor_db_translate",
            "actor_db_link",
            "actor_db_sync_aliases",
            "actor_db_fill_minnano",
            "actor_db_fill_zh_javdb",
        }
    )

    def _on_actor_db_finished(self, task_id: str = "") -> None:
        """主线程恢复演员库维护按钮状态（由 actor_db_finished 信号触发）。

        task_id: 完成的按钮 attr（如 "actor_db_clean_male"）。空串表示恢复全部按钮
        （兼容旧调用，例如 _run_actor_db_check / _run_actor_db_update_nfo 的同步路径）。
        """
        self._actor_db_running.discard(task_id)

        if task_id and task_id in self._ACTOR_DB_IDLE_TEXT_MAP:
            btn_attr = task_id
            btn = getattr(self.Ui, f"pushButton_{btn_attr}")
            # 仍在跑的任务只重置文案，不重置 enabled（避免与其他 actor_db 任务交叉）
            btn.setEnabled(btn_attr not in self._actor_db_running)
            getattr(self, f"pushButton_{btn_attr}").emit(self._ACTOR_DB_IDLE_TEXT_MAP[btn_attr])
            return

        # 空 task_id 或未知 attr：仅恢复未在跑任务的按钮；在跑的保持 disabled
        for btn_attr, idle_text in self._ACTOR_DB_IDLE_TEXT_MAP.items():
            btn = getattr(self.Ui, f"pushButton_{btn_attr}", None)
            sig = getattr(self, f"pushButton_{btn_attr}", None)
            if btn is not None and btn_attr not in self._actor_db_running:
                btn.setEnabled(True)
            if sig is not None:
                sig.emit(idle_text)

        # 演员库任务全部结束后复位停止标志。
        # pushButton_actor_db_stop_clicked 只置位不复位，若在非刮削状态点击停止，
        # signal_qt.stop / Flags.stop_requested 将永久为 True，导致日志静默、下一任务秒停。
        # 演员库任务与主刮削互斥（change_buttons_status 会禁用 actor_db 按钮），此处复位安全。
        if not self._actor_db_running:
            Flags.stop_requested = False
            signal_qt.stop = False

    # endregion

    # endregion

    # endregion

    # endregion

    # 切换配置

    # endregion

    # endregion

    # endregion

    # endregion


# region 外部方法定义
MyMAinWindow.load_config = load_config  # type: ignore[method-assign]
MyMAinWindow.save_config = save_config  # type: ignore[method-assign, assignment]
MyMAinWindow.Init_QSystemTrayIcon = Init_QSystemTrayIcon  # type: ignore[method-assign]
MyMAinWindow.Init_Ui = Init_Ui  # type: ignore[method-assign]
MyMAinWindow.Init_Singal = Init_Singal  # type: ignore[method-assign]
MyMAinWindow.init_QTreeWidget = init_QTreeWidget  # type: ignore[method-assign]
MyMAinWindow.set_style = set_style  # type: ignore[method-assign]
MyMAinWindow.set_dark_style = set_dark_style  # type: ignore[method-assign]
# endregion
