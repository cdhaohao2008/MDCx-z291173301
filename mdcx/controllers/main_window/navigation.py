"""左侧导航按钮：主页面 / 日志 / 工具 / 设置 / 网络 / 关于。

只负责切页与少量前置动作，切页后的联动由 WindowOpsMixin._change_page 承担。"""

import traceback

from mdcx.signals import signal_qt


class NavigationMixin:
    # region 左侧切换页面
    # 点左侧的主界面按钮
    def pushButton_main_clicked(self):
        # 侧栏配色与「软件设置」页保持一致（#EEF3FF / 右边框 #D8E2FF）
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #EEF3FF;border-right: 1px solid #D8E2FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(0)
        self.set_left_button_style()
        self.Ui.pushButton_main.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的日志按钮
    def pushButton_show_log_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(1)
        self.set_left_button_style()
        self.Ui.pushButton_log.setStyleSheet(
            "font-weight: bold; background-color: rgba(160,160,165,60);"
        )  # self.Ui.textBrowser_log_main.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main.verticalScrollBar().maximum())  # self.Ui.textBrowser_log_main_2.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main_2.verticalScrollBar().maximum())

    # 点左侧的工具按钮
    def pushButton_tool_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(3)
        self.set_left_button_style()
        self.Ui.pushButton_tool.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的设置按钮
    def pushButton_setting_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #EEF3FF;border-right: 1px solid #D8E2FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(4)
        self.set_left_button_style()
        try:
            if self.dark_mode:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
            else:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,100);")
            self._check_mac_config_folder()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # 点击左侧【检测网络】按钮，切换到检测网络页面
    def pushButton_show_net_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(2)
        self.set_left_button_style()
        self.Ui.pushButton_net.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的关于按钮
    def pushButton_about_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(5)
        self.set_left_button_style()
        self.Ui.pushButton_about.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
