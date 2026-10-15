"""成功刮削列表（另存 / 清空 / 查看）与状态栏文案。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QMessageBox,
)

from mdcx.base.file import (
    get_success_list,
    save_success_list,
)
from mdcx.config.manager import manager
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils import executor


class SuccessListMixin:
    # 主界面左下角显示信息
    def show_scrape_info(self, before_info=""):
        try:
            before_info = before_info.strip()
            if Flags.file_mode == FileMode.Single:
                website_label = self.Ui.comboBox_website_all.currentData() or self.Ui.comboBox_website_all.currentText()
                scrape_info = f"💡 单文件刮削\n💠 {Flags.main_mode_text}·{website_label}"
            else:
                scrape_info = f"💠 {Flags.main_mode_text}·{Flags.scrape_like_text}"
                if manager.config.scrape_like == "single":
                    scrape_info = f"💡 {manager.config.website_single} 刮削\n" + scrape_info
            if manager.config.soft_link == 1:
                scrape_info = "🍯 软链接·开\n" + scrape_info
            elif manager.config.soft_link == 2:
                scrape_info = "🍯 硬链接·开\n" + scrape_info
            after_info = f"\n{scrape_info}\n🛠 {manager.file}\n🐰 MDCx {self.localversion}"
            text = before_info + after_info + self.new_version
            if "<font" in text or "<span" in text:
                # QLabel AutoText 在换行符先于标签出现时判为纯文本、会原样输出标签：
                # 含红字提示时统一用 <br> 换行，保证标红正常渲染与换行显示。
                text = text.replace("\n", "<br>")
            self.label_show_version.emit(text)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # region 获取/保存成功刮削列表
    def pushButton_success_list_save_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "保存成功列表", "确定要将当前列表保存为已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("保存")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            success_text = self.Ui.textBrowser_show_success_list.toPlainText().replace("暂无成功刮削的文件", "").strip()
            new_success = {
                p for path in success_text.splitlines() if (line := path.strip()) and (p := Path(line)).suffix
            }
            with Flags.guarded():
                Flags.success_list = new_success
            executor.run(save_success_list())
            get_success_list()
            self.Ui.widget_show_success.hide()

    def pushButton_success_list_clear_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "清空成功列表", "确定要清空当前已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("清空")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            with Flags.guarded():
                Flags.success_list.clear()
            executor.run(save_success_list())
            self.Ui.widget_show_success.hide()

    def pushButton_view_success_file_clicked(self):
        self.Ui.widget_show_success.show()
        info = "暂无成功刮削的文件"
        # 锁内快照后出锁再排序拼串：UI 读时协程可能正 add
        with Flags.guarded():
            success_snapshot = list(Flags.success_list)
        if success_snapshot:
            info = "\n".join(sorted(str(p) for p in success_snapshot))
        self.Ui.textBrowser_show_success_list.setText(info)
