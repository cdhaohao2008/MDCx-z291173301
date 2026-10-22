"""窗口操作 / 托盘 / 右键菜单 / 生命周期 / 主题 / 版本显示。

这些方法只依赖 Qt 与 self.*，不含任何刮削业务，因此可以整体从主窗类里搬走。
模块级的窗口几何常量（_BASE_W / _CONTENT_* / _MAIN_* / _ADV_*）跟随方法一起搬过来，
因为它们只被这里的测量逻辑使用。"""

import threading
import traceback
import webbrowser

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QAction,
    QCursor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from mdcx.base.web import (
    check_theporndb_api_token,
    check_version,
    is_remote_version_newer,
)
from mdcx.config.enums import Switch
from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.consts import (
    GITHUB_ISSUES_URL,
    GITHUB_RELEASES_URL,
    IS_WINDOWS,
    VERSION_NAME,
)
from mdcx.log_console import strip_leading_indent
from mdcx.signals import signal_qt
from mdcx.tools.actress_db import ActressDB
from mdcx.utils import split_path

from .init import (
    DEFAULT_WINDOW_SIZE,
    _adaptive_window_sizes,
)
from .site_priority_dialog import apply_site_priority_theme
from .style import (
    apply_application_palette,
    build_menu_style,
)


class WindowOpsMixin:
    def creat_right_menu(self):
        self.menu_start = QAction(QIcon(resources.start_icon), "  开始刮削\tS", self)
        self.menu_stop = QAction(QIcon(resources.stop_icon), "  停止刮削\tS", self)
        self.menu_number = QAction(QIcon(resources.input_number_icon), "  重新刮削\tN", self)
        self.menu_website = QAction(QIcon(resources.input_website_icon), "  输入网址重新刮削\tU", self)
        self.menu_del_file = QAction(QIcon(resources.del_file_icon), "  删除文件\tD", self)
        self.menu_del_folder = QAction(QIcon(resources.del_folder_icon), "  删除文件和文件夹\tA", self)
        self.menu_make_symlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建软链接", self)
        self.menu_make_symlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建软链接（按文件名建目录）", self
        )
        self.menu_make_hardlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建硬链接", self)
        self.menu_make_hardlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建硬链接（按文件名建目录）", self
        )
        self.menu_folder = QAction(QIcon(resources.open_folder_icon), "  打开文件夹\tF", self)
        self.menu_nfo = QAction(QIcon(resources.open_nfo_icon), "  编辑 NFO\tE", self)
        self.menu_play = QAction(QIcon(resources.play_icon), "  播放\tP", self)
        self.menu_hide = QAction(QIcon(resources.hide_boss_icon), "  隐藏到托盘\tQ / Esc", self)
        self.menu_similar = QAction(QIcon(resources.open_folder_icon), "  查看相似片推荐", self)

        self.menu_start.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_stop.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_number.triggered.connect(self.search_by_number_clicked)
        self.menu_website.triggered.connect(self.search_by_url_clicked)
        self.menu_del_file.triggered.connect(self.main_del_file_click)
        self.menu_del_folder.triggered.connect(self.main_del_folder_click)
        self.menu_make_symlink.triggered.connect(self.main_make_symlink_click)
        self.menu_make_symlink_in_dir.triggered.connect(self.main_make_symlink_in_dir_click)
        self.menu_make_hardlink.triggered.connect(self.main_make_hardlink_click)
        self.menu_make_hardlink_in_dir.triggered.connect(self.main_make_hardlink_in_dir_click)
        self.menu_folder.triggered.connect(self.main_open_folder_click)
        self.menu_nfo.triggered.connect(self.main_open_nfo_click)
        self.menu_play.triggered.connect(self.main_play_click)
        self.menu_hide.triggered.connect(self.hide_to_tray)
        self.menu_similar.triggered.connect(self.main_show_similar_click)

        QShortcut(QKeySequence(self.tr("N")), self, self.search_by_number_clicked)
        QShortcut(QKeySequence(self.tr("U")), self, self.search_by_url_clicked)
        QShortcut(QKeySequence(self.tr("D")), self, self.main_del_file_click)
        QShortcut(QKeySequence(self.tr("A")), self, self.main_del_folder_click)
        QShortcut(QKeySequence(self.tr("F")), self, self.main_open_folder_click)
        QShortcut(QKeySequence(self.tr("E")), self, self.main_open_nfo_click)
        QShortcut(QKeySequence(self.tr("P")), self, self.main_play_click)
        QShortcut(QKeySequence(self.tr("S")), self, self.pushButton_start_scrape_clicked)
        QShortcut(QKeySequence(self.tr("Q")), self, self.hide_to_tray)
        # Esc 只有一个入口（见 hide_tips_widget_on_escape）：面板/弹窗优先处理，
        # 都没有时收进托盘。此处不能再额外绑一条 Esc → hide_to_tray 的 shortcut，
        # 否则同键序列被 Qt 判为 ambiguous shortcut，两条都不触发。
        QShortcut(QKeySequence(self.tr("Esc")), self, self.hide_tips_widget_on_escape)
        QShortcut(QKeySequence(self.tr("Ctrl+M")), self, self.pushButton_min_clicked2)
        QShortcut(QKeySequence(self.tr("Ctrl+W")), self, self.ready_to_exit)

        self.Ui.page_main.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.Ui.page_main.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos=None):
        if not pos:
            pos = self.Ui.pushButton_right_menu.pos() + QPoint(40, 10)
            # pos = QCursor().pos()
        menu = QMenu()
        menu.setStyleSheet(build_menu_style(self.dark_mode))
        selected_entries = self._get_selected_entries()
        selected_entry = selected_entries[0] if len(selected_entries) == 1 else None
        if len(selected_entries) > 1:
            menu.addAction(QAction(f"已选择 {len(selected_entries)} 项", self))
            menu.addSeparator()
            menu.addAction(self.menu_del_file)
            menu.addAction(self.menu_del_folder)
            menu.addAction(self.menu_make_symlink)
            menu.addAction(self.menu_make_symlink_in_dir)
            menu.addAction(self.menu_make_hardlink)
            menu.addAction(self.menu_make_hardlink_in_dir)
            menu.exec(self.Ui.page_main.mapToGlobal(pos))
            return

        if selected_entry is not None:
            _, _, _, file_path = selected_entry
            file_name = split_path(file_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        elif self.file_main_open_path:
            file_name = split_path(self.file_main_open_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        else:
            menu.addAction(QAction("请刮削后使用！", self))
            menu.addSeparator()
            if self.Ui.pushButton_start_cap.text() != "开始":
                menu.addAction(self.menu_stop)
            else:
                menu.addAction(self.menu_start)
        menu.addAction(self.menu_number)
        menu.addAction(self.menu_website)
        menu.addSeparator()
        menu.addAction(self.menu_del_file)
        menu.addAction(self.menu_del_folder)
        menu.addAction(self.menu_make_symlink)
        menu.addAction(self.menu_make_symlink_in_dir)
        menu.addAction(self.menu_make_hardlink)
        menu.addAction(self.menu_make_hardlink_in_dir)
        menu.addSeparator()
        menu.addAction(self.menu_folder)
        menu.addAction(self.menu_nfo)
        menu.addAction(self.menu_play)
        menu.addAction(self.menu_hide)
        menu.addAction(self.menu_similar)
        menu.exec(self.Ui.page_main.mapToGlobal(pos))

    def _tree_result_context_menu(self, pos: QPoint):
        item = self.Ui.treeWidget_number.itemAt(pos)
        if item is not None and item.text(0) not in {"成功", "失败"}:
            self._set_result_item_as_current_selection(item)
        global_pos = self.Ui.treeWidget_number.viewport().mapToGlobal(pos)
        self._menu(self.Ui.page_main.mapFromGlobal(global_pos))

    # region 窗口操作
    def tray_icon_click(self, e):
        if e == QSystemTrayIcon.ActivationReason.Trigger and IS_WINDOWS:
            if self.isVisible():
                self.hide()
            else:
                self.activateWindow()
                self.raise_()
                self.show()

    def tray_icon_show(self):
        if self.windowState() & Qt.WindowState.WindowMinimized:  # 最小化时恢复
            self.showNormal()
        self.recover_windowflags()  # 恢复焦点
        self.activateWindow()
        self.raise_()
        self.show()

    # 收进托盘：ESC 键、Q 快捷键、右键菜单「隐藏」、托盘菜单「隐藏」的统一实现。
    # 之所以不直接用 self.hide()：托盘图标默认可能处于隐藏状态（默认配置里
    # Switch.HIDE_MENU / HIDE_DOCK 会置 hide_menu、hide_dock），此时再 hide 主窗，
    # Windows 上任务栏按钮会一并消失，程序将彻底无法唤出，只能重启。因此隐藏前
    # 必须保证托盘图标可见——没有就补建一个，有就直接点亮。
    def hide_to_tray(self):
        try:
            if not hasattr(self, "tray_icon"):
                self.Init_QSystemTrayIcon()
            else:
                self.tray_icon.show()
        except Exception:  # 托盘不可用（无系统托盘等）时仍要隐藏窗口，否则用户按了没反应
            signal_qt.show_traceback_log(traceback.format_exc())
        # 主窗口收起时把预览窗口连带关闭，不留孤儿窗口在屏幕上
        preview = getattr(self, "nfo_lib_preview_window", None)
        if preview is not None:
            preview.close()
        self.hide()

    def change_mainpage(self, t):
        self.pushButton_main_clicked()

    def _apply_adaptive_default_size(self) -> None:
        """默认尺寸按所在屏可用区自适应（min(1030, 可用宽×0.9) × min(700, 可用高×0.85)），并居中。

        尺寸公式保持历史行为（用户在 80% 缩放下 1030×700 的默认初始宽高不能变），
        改动只补上「居中」；界面缩放过大导致界面超出屏幕，由设置页高分屏缩放下拉
        隐藏超限档位来防（见 init.UI_SCALE_OPTIONS）。
        """
        screen = self.screen()
        avail = screen.availableGeometry() if screen is not None else None
        if avail is not None:
            def_w, def_h = _adaptive_window_sizes(avail.width(), avail.height())[2:]
        else:
            def_w, def_h = DEFAULT_WINDOW_SIZE
        self.resize(def_w, def_h)
        self._center_on_screen(avail)

    def _center_on_screen(self, avail: QRect | None = None, *, allow_defer: bool = True) -> None:
        """把窗口整体（含标题栏与边框）精确居中到所在屏可用区的正中央。

        两个易错点（Qt 6 实测）：
        1. 人眼看到的是 frameGeometry（含边框），而 geometry() 只是客户区——用客户区居中
           会整体偏移半个标题栏/边框，故一律以 frameGeometry 为准；
        2. QWidget.move() 收的是「边框左上角」（move(100,200) → frame 在 100,200、客户区
           在 102,202），与 pos() 语义一致，故这里不需要再补偿边框厚度。
        """
        if avail is None:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
        if allow_defer and self.windowHandle() is None:
            # 原生窗口尚未创建，frameGeometry 退化为客户区（边框厚度不可知）：
            # 推到下一事件循环（原生窗口已创建）再居中一次，否则会偏出半个标题栏。
            QTimer.singleShot(0, lambda: self._center_on_screen(allow_defer=False))
            return
        frame = self.frameGeometry()
        x = avail.x() + (avail.width() - frame.width()) // 2
        y = avail.y() + (avail.height() - frame.height()) // 2
        # 窗口比可用区还大时（极端小屏）至少让左上角留在屏内，标题栏不会跑到屏外抓不到
        self.move(max(x, avail.x()), max(y, avail.y()))

    # 用于计算窗口各子页面初始设计尺寸，被 resizeEvent 用于按比例缩放
    _BASE_W = 1040
    _BASE_H = 760
    # 窗口缩放时，需要用子页面内容的实际高度来自定义 MDCx 中央区域的高度
    _CONTENT_TOP_OFFSET = 6
    _CONTENT_BOTTOM_MARGIN = 2
    # 软件界面「清空结果列表」刷子按钮与结果树左缘的固定间距（设计态 760 - 600）。
    # 结果树左缘 tree_x = main_w - tree_w - 18、树宽 tree_w = int(202 × main_w/820)
    # 随窗口拉伸，故把刷子钉在「树左缘 + 本常量」上、而不是钉在页面右缘：
    # 树内首行「成功」两字的左缘恒为「树左缘 + 固定缩进」，于是刷子与「成功」的
    # 间距在最大化/还原两态完全一致（最大化不再随树拉伸而越拉越远）。
    _MAIN_TREE_CLEAR_DX = 160
    # 软件界面「编辑 NFO/打开文件夹/播放/右键菜单」四按钮组的设计态右缘
    # （.ui：最右 pushButton_right_menu x=547 + 宽 40 = 587）。最大化/还原两态都把
    # 组右缘钉到缩略图框右边界；本常量是极窄窗（缩略图右缘退到 587 左侧）时的下限，
    # 保证按钮组只右移不左移，绝不压住「标题：」值行（设计态右界 417）。
    _MAIN_ACTION_ROW_RIGHT = 587
    # 高级页「界面外观」行的 layoutWidget5 设计宽度（MDCx.ui 里
    # QRect(0,-10,550,51)）。最大化时该容器要临时加宽以对齐，见
    # _sync_advanced_page_align 的设计态对照值（.ui 里 layoutWidget5 = 550x51）；
    # 该控制器每一态都会按实测列宽重算，此常量仅作「放弃对齐」时的回退值。
    _ADV_FRAME_LW_W = 550
    # 高级页「隐藏窗口」行的 layoutWidget_17 设计宽度（MDCx.ui 里
    # QRect(0,0,551,32)）。最大化时该容器要加宽以把「点最小化按钮」「无」推到
    # 各自锚点，见 _sync_advanced_page_tail_align；该方法每态都按实测锚点重算，
    # 此常量仅作「放弃对齐 / 最小化态复位」时的设计态对照值。
    _ADV_HIDE_LW_W = 551

    # 当隐藏边框时，最小化后，点击任务栏时，需要监听事件，在恢复窗口时隐藏边框
    def changeEvent(self, a0):
        # self.show_traceback_log(QEvent.WindowStateChange)
        # WindowState （WindowNoState=0 正常窗口; WindowMinimized= 1 最小化;
        # WindowMaximized= 2 最大化; WindowFullScreen= 3 全屏;WindowActive= 8 可编辑。）
        # windows平台无问题，仅mac平台python版有问题
        # 议题：最大化/还原时 resizeEvent 中 isMaximized() 时序不可靠（状态位尚未更新），
        # 在窗口状态变更事件后延迟一帧重算布局，确保统计标签 y 坐标正确跟随最大化状态
        if a0.type() == QEvent.Type.WindowStateChange:
            # 延迟一帧后状态位才可靠，此时**必须重算侧栏**：_layout_donate 用
            # isMaximized() 决定是否在微信码上方加支付宝码，而 resizeEvent 那一拍
            # 窗口管理器「先发尺寸、后发状态」，isMaximized() 还是 False，只靠
            # resizeEvent 会导致最大化后支付宝码始终不出现（用户反馈「最大化没变化」）
            QTimer.singleShot(0, self._sync_page_layouts)
            QTimer.singleShot(0, self._sync_dock_layout)
        if (
            not IS_WINDOWS
            and self.window_radius
            and a0.type() == QEvent.Type.WindowStateChange
            and self.windowState() == Qt.WindowState.WindowNoState
        ):
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏边框
            self.show()

    def closeEvent(self, a0):
        # 先停轮播定时器：关窗起就没人看日志/没人等版本检查了，100ms 的热表白跳。
        # 也兜住「从未 show() 过的窗口」——那种窗口调 close() 走不到 hideEvent
        # （本就是 WA_WState_Hidden 态，setVisible(false) 直接早退、不发 Hide 事件）。
        # 重新显示时由 showEvent 起回来，故托盘隐藏/唤回不受影响。
        self._stop_polling_timers()
        if Switch.HIDE_CLOSE in manager.config.switch_on:
            self.hide()
            # 主窗口收起时把预览/裁剪窗口连带关闭，不留孤儿窗口在屏幕/任务栏上
            # （这两个是独立顶层窗口，不再随主窗口的 hide 自动收起）
            preview = getattr(self, "nfo_lib_preview_window", None)
            if preview is not None:
                preview.close()
            cut = getattr(self, "cutwindow", None)
            if cut is not None:
                cut.close()
        else:
            self.ready_to_exit()
        if a0:
            a0.ignore()

    # 显示与隐藏窗口标题栏
    def _windows_auto_adjust(self):
        if manager.config.window_title == "hide":  # 隐藏标题栏
            if self.window_radius == 0:
                self.show_flag = True
            self.window_radius = 5
            if IS_WINDOWS:
                self.window_border = 1
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            else:
                self.window_border = 0
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏标题栏
            self.Ui.pushButton_close.setVisible(True)
            self.Ui.pushButton_min.setVisible(True)
            self.Ui.widget_buttons.move(0, 50)

        else:  # 显示标题栏
            if self.window_radius == 5:
                self.show_flag = True
            self.window_radius = 0
            self.window_border = 0
            self.window_marjin = 0
            if IS_WINDOWS:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 显示标题栏
            self.Ui.pushButton_close.setVisible(False)
            self.Ui.pushButton_min.setVisible(False)
            self.Ui.widget_buttons.move(0, 20)

        if bool(self.dark_mode != self.Ui.checkBox_dark_mode.isChecked()):
            self.show_flag = True
            self.dark_mode = self.Ui.checkBox_dark_mode.isChecked()

        if self.show_flag:
            self.show_flag = False
            self.set_style()  # 样式美化
            apply_site_priority_theme(self)
            self._style_donate_link()  # 暗黑/亮色切换时同步 [赞助作者] 链接颜色

            # self.setWindowState(Qt.WindowNoState)                               # 恢复正常窗口
            self.show()
            self._change_page()

    def _change_page(self):
        page = int(self.Ui.stackedWidget.currentIndex())
        if page == 0:
            self.pushButton_main_clicked()
        elif page == 1:
            self.pushButton_show_log_clicked()
        elif page == 2:
            self.pushButton_show_net_clicked()
        elif page == 3:
            self.pushButton_tool_clicked()
        elif page == 4:
            self.pushButton_setting_clicked()
        elif page == 5:
            self.pushButton_about_clicked()

    def _bind_system_theme_refresh(self) -> None:
        try:
            style_hints = QGuiApplication.styleHints()
            if style_hints is not None:
                style_hints.colorSchemeChanged.connect(lambda *_args: apply_application_palette(self.dark_mode))
        except Exception:
            pass

    # region 拖动窗口
    # 按下鼠标
    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = True
            self.m_DragPosition = a0.globalPosition().toPoint() - self.pos()
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))  # 按下左键改变鼠标指针样式为手掌

    # 松开鼠标
    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))  # 释放左键改变鼠标指针样式为箭头

    # 拖动鼠标
    def mouseMoveEvent(self, a0):
        if a0 and self.m_drag and self.m_DragPosition is not None and a0.buttons() & Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self.m_DragPosition)
            a0.accept()
        else:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    # region 关闭
    # 关闭按钮点击事件响应函数
    def pushButton_close_clicked(self):
        self._user_initiated_close = True
        if Switch.HIDE_CLOSE in manager.config.switch_on:
            self.hide()
        else:
            self.ready_to_exit()

    def ready_to_exit(self):
        if Switch.SHOW_DIALOG_EXIT in manager.config.switch_on:
            if not self.isVisible():
                self.show()
            if self.windowState() & Qt.WindowState.WindowMinimized:
                self.showNormal()

            # print(self.window().isActiveWindow()) # 是否为活动窗口
            self.raise_()
            box = QMessageBox(QMessageBox.Icon.Warning, "退出", "确定要退出吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("退出 MDCx")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                self.raise_()
                self.show()
                return
        self.exit_app()

    # 关闭窗口
    def exit_app(self):
        show_poster = manager.config.show_poster
        switch_on = manager.config.switch_on
        need_save_config = False

        if self.Ui.checkBox_cover.isChecked() != show_poster:
            manager.config.show_poster = self.Ui.checkBox_cover.isChecked()
            need_save_config = True
        if self.Ui.textBrowser_log_main_2.isHidden() == (Switch.SHOW_LOGS in switch_on):
            if self.Ui.textBrowser_log_main_2.isHidden():
                manager.config.switch_on.remove(Switch.SHOW_LOGS)
            else:
                manager.config.switch_on.append(Switch.SHOW_LOGS)
            need_save_config = True
        if need_save_config:
            try:
                manager.save()
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
        if hasattr(self, "preview_image_loader"):
            self.preview_image_loader.shutdown()
        # 动图（gif）播放也要停，避免退出前 QMovie 继续跑
        for _kind in ("poster", "thumb"):
            try:
                self._stop_preview_movie(_kind)
            except Exception:
                pass
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        signal_qt.show_traceback_log("\n\n\n\n************ 程序正常退出！************\n")
        QApplication.quit()

    # 最小化窗口
    def pushButton_min_clicked(self):
        if Switch.HIDE_MINI in manager.config.switch_on:
            self.hide()
            return
        # mac 平台 python 版本 最小化有问题，此处就是为了兼容它，需要先设置为显示窗口标题栏才能最小化
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框

        # self.setWindowState(Qt.WindowState.WindowMinimized)
        # self.show_traceback_log(self.isMinimized())
        self.showMinimized()

    def pushButton_min_clicked2(self):
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框
            # self.show()  # 加上后可以显示缩小动画
        self.showMinimized()

    # 重置左侧按钮样式
    def set_left_button_style(self):
        try:
            if self.dark_mode:
                self.Ui.left_backgroud_widget.setStyleSheet(
                    f"background: #1F272F;border-right: 1px solid #20303F;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
                )
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_emby_manager_nav.setStyleSheet(
                    "QPushButton:hover#pushButton_emby_manager_nav{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_nfo_library.setStyleSheet(
                    "QPushButton:hover#pushButton_nfo_library{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: white;background-color: rgba(160,160,165,40);}"
                )
            else:
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_emby_manager_nav.setStyleSheet(
                    "QPushButton:hover#pushButton_emby_manager_nav{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_nfo_library.setStyleSheet(
                    "QPushButton:hover#pushButton_nfo_library{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: black;background-color: rgba(160,160,165,40);}"
                )
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # region 显示版本号
    def show_version(self):
        try:
            t = threading.Thread(target=self._show_version_thread, daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _show_version_thread(self):
        version_info = f"基于MDC-GUI修改·当前版本：{self.version_display}"
        download_link = ""
        has_new_version = False
        latest_version = check_version()
        if latest_version:
            # 版本号(vX.Y.Z)与日期(YYYYMMDD tag)同时对比：任一更新即视为有新版本，
            # 版本号相等时由日期决出。详见 is_remote_version_newer。
            if is_remote_version_newer(latest_version, self.localversion, VERSION_NAME):
                has_new_version = True
                # 定时复查与启动自检共用本函数：仅在首次发现该新版本时提示
                # （红字日志、下载链接与左下角标签刷新），同一版本重复检查
                # 不再刷屏；出现更新的版本时会自动再次提示。
                if latest_version != self._notified_new_version:
                    self._notified_new_version = latest_version
                    # 左下角提示格式「有新版本了！（日期tag）」：保留 🍉 图标与感叹号，只显示日期 tag 全角括号红字。
                    self.new_version = f'\n🍉 有新版本了！<font color="red">（{latest_version.tag}）</font>'
                    signal_qt.show_scrape_info()
                    version_info = f'基于MDC-GUI修改·当前版本：{self.version_display}（<font color="red">最新版本是：{latest_version.display}，请及时更新！🚀</font>）'
                    download_link = f' ⬇️ <a href="{GITHUB_RELEASES_URL}">下载新版本</a>'
            else:
                version_info = f'基于MDC-GUI修改·当前版本：{self.version_display}（<font color="green">你使用的是最新版本！🎉</font>）'

        feedback = f' 💌 问题反馈: <a href="{GITHUB_ISSUES_URL}">GitHub Issues</a>'

        # 显示版本信息和反馈入口
        signal_qt.show_log_text(version_info)
        if feedback or download_link:
            self.main_logs_show.emit(strip_leading_indent(f"{feedback}{download_link}"))
        signal_qt.show_log_text(
            "============================================================================================================"
        )
        # 议题 #73: 用户误以为启动自检在某项失败后"停止检测"。声明自检范围与
        # 全量检测入口, 避免混淆（全量检测在「检测网络」页, 单站失败互相独立）。
        signal_qt.show_log_text(
            " 启动自检：数据库/ThePornDB/JavDb/JavBus/FC2PPVDB连通性，如需检测全部站点，请到左侧「检测网络」页点击开始检测"
        )
        # QWidget 与 cookie 检查必须在主线程执行：通过信号调度回主线程
        self.version_check_done.emit(has_new_version)
        if manager.config.use_database:
            ActressDB.init_db()
        try:
            t = threading.Thread(target=check_theporndb_api_token, daemon=True)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _on_version_check_done(self, has_new_version: bool):
        """主线程：版本检查完成后的 UI 更新与 cookie 检测。"""
        if has_new_version:
            self.Ui.label_show_version.setCursor(Qt.CursorShape.OpenHandCursor)  # 设置鼠标形状为十字形
        self.pushButton_check_javdb_cookie_clicked()  # 检测javdb cookie
        self.pushButton_check_javbus_cookie_clicked()  # 检测javbus cookie
        # 议题 #130：启动时也检测 FC2PPVDB cookie 有效性（未填写时该函数直接返回，不发请求）
        self.pushButton_check_fc2ppvdb_cookie_clicked()  # 检测fc2ppvdb cookie

    # region 各种点击跳转浏览器
    def label_version_clicked(self, ev):
        try:
            webbrowser.open(GITHUB_RELEASES_URL)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # 改回接受焦点状态
    def recover_windowflags(self):
        return
