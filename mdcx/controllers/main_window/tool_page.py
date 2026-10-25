"""工具页（本地番号 / 媒体目录选择 / 软链接 / 缺番号 / 单文件刮削 / 选文件 / 选图 / 移动 MP4 / 补图）与工具页动作按钮。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import os
import shutil
import threading
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
)

from mdcx.base.file import (
    check_and_clean_files,
    movie_lists,
    newtdisk_creat_symlink,
)
from mdcx.base.image import add_del_extrafanart_copy
from mdcx.base.video import (
    add_del_extras,
    add_del_theme_videos,
)
from mdcx.config.enums import Switch
from mdcx.config.extend import (
    deal_url,
    get_movie_path_setting,
    parse_media_paths,
)
from mdcx.config.manager import manager
from mdcx.core.scraper import start_new_scrape
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.tools.missing import check_missing_number
from mdcx.tools.subtitle import add_sub_for_all_video
from mdcx.utils import (
    executor,
    get_current_time,
)


class ToolPageMixin:
    # region 工具页
    # 工具页面点查看本地番号
    def label_local_number_clicked(self, ev):
        if self.Ui.pushButton_find_missing_number.isEnabled():
            self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面
            if self.Ui.lineEdit_actors_name.text() != manager.config.actors_name:  # 保存配置
                self.pushButton_save_config_clicked()
            # 右侧「类型」下拉框：选具体类型就按该类型的网站列表查，「自动判断」按名字后的标注走
            executor.submit(check_missing_number(False, self.Ui.comboBox_actor_type.currentText()))

    # 工具页面本地资源库点选择目录
    def pushButton_select_local_library_clicked(self):
        from .tool_handlers import pushButton_select_local_library_clicked

        pushButton_select_local_library_clicked(self)

    # 工具页面网盘目录点选择目录
    def pushButton_select_netdisk_path_clicked(self):
        from .tool_handlers import pushButton_select_netdisk_path_clicked

        pushButton_select_netdisk_path_clicked(self)

    # 工具页面本地目录点选择目录
    def pushButton_select_localdisk_path_clicked(self):
        from .tool_handlers import pushButton_select_localdisk_path_clicked

        pushButton_select_localdisk_path_clicked(self)

    # 工具/设置页面点选择目录
    def pushButton_select_media_folder_clicked(self):
        from .tool_handlers import pushButton_select_media_folder_clicked

        pushButton_select_media_folder_clicked(self)

    # 工具-软链接助手
    def pushButton_creat_symlink_clicked(self):
        """
        工具点一键创建软链接
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        if (Switch.COPY_NETDISK_NFO in manager.config.switch_on) != self.Ui.checkBox_copy_netdisk_nfo.isChecked():
            self.pushButton_save_config_clicked()

        try:
            executor.submit(newtdisk_creat_symlink(self.Ui.checkBox_copy_netdisk_nfo.isChecked()))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 工具-检查番号
    def pushButton_find_missing_number_clicked(self):
        """
        工具点检查缺失番号
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        # 如果本地资源库或演员与配置内容不同，则自动保存
        if (
            self.Ui.lineEdit_actors_name.text() != manager.config.actors_name
            or self.Ui.lineEdit_local_library_path.text() != manager.config.local_library
        ):
            self.pushButton_save_config_clicked()
        executor.submit(check_missing_number(True, self.Ui.comboBox_actor_type.currentText()))

    # 工具-单文件刮削
    def pushButton_select_file_clicked(self):
        media_path = self.Ui.lineEdit_movie_path.text()  # 获取待刮削目录作为打开目录
        if not media_path:
            media_path = manager.data_folder
        else:
            media_path = parse_media_paths(media_path)[0]
        file_path, filetype = QFileDialog.getOpenFileName(
            None,
            "选取视频文件",
            media_path.as_posix(),
            "Movie Files(*.mp4 "
            "*.avi *.rmvb *.wmv "
            "*.mov *.mkv *.flv *.ts "
            "*.webm *.MP4 *.AVI "
            "*.RMVB *.WMV *.MOV "
            "*.MKV *.FLV *.TS "
            "*.WEBM);;All Files(*)",
            options=self.options,
        )
        if file_path:
            self.Ui.lineEdit_single_file_path.setText(file_path)

    def pushButton_start_single_file_clicked(self):  # 点刮削
        Flags.single_file_path = Path(self.Ui.lineEdit_single_file_path.text().strip())
        if not Flags.single_file_path:
            signal_qt.show_scrape_info("💡 请选择文件！")
            return

        if not os.path.isfile(Flags.single_file_path):
            signal_qt.show_scrape_info("💡 文件不存在！")  # 主界面左下角显示信息
            return

        if not self.Ui.lineEdit_appoint_url.text():
            signal_qt.show_scrape_info("💡 请填写番号网址！")  # 主界面左下角显示信息
            return

        self.pushButton_show_log_clicked()  # 点击刮削按钮后跳转到日志页面
        Flags.appoint_url = self.Ui.lineEdit_appoint_url.text().strip()
        # 单文件刮削从用户输入的网址中识别网址名，复用现成的逻辑=>主页面输入网址刮削
        website, url = deal_url(Flags.appoint_url)
        if website:
            Flags.website_name = website
        else:
            signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")
            return
        start_new_scrape(FileMode.Single)

    def pushButton_select_file_clear_info_clicked(self):  # 点清空信息
        self.Ui.lineEdit_single_file_path.setText("")
        self.Ui.lineEdit_appoint_url.setText("")

    # 工具-裁剪封面图
    def pushButton_select_thumb_clicked(self):
        path = self.Ui.lineEdit_movie_path.text()
        if not path:
            path = manager.data_folder.as_posix()
        else:
            path = parse_media_paths(path)[0].as_posix()
        file_path, fileType = QFileDialog.getOpenFileName(
            None, "选取缩略图", path, "Picture Files(*.jpg *.png);;All Files(*)", options=self.options
        )
        if file_path:
            self.cutwindow.showimage(Path(file_path))
            self.cutwindow.present()

    # 工具-视频移动
    def pushButton_move_mp4_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "移动视频和字幕", "确定要移动视频和字幕吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("移动")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            self.pushButton_show_log_clicked()  # 点击开始移动按钮后跳转到日志页面
            try:
                t = threading.Thread(target=self._move_file_thread)
                # 已结束的线程对象及时摘除，长会话不再堆积（存活线程保留，停止逻辑不变）
                self.threads_list = [x for x in self.threads_list if x.is_alive()]
                self.threads_list.append(t)
                t.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_log_text(traceback.format_exc())

    def _move_file_thread(self):
        signal_qt.change_buttons_status.emit()
        # 协作式停止事件：每次移动开始时清零，停止按钮处理器中置位
        self._move_cancel_event.clear()
        try:
            self._move_files_core()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())
        finally:
            signal_qt.reset_buttons_status.emit()

    def _move_files_core(self):
        movie_items = []
        for movie_path in get_movie_path_setting().movie_paths:
            # 协作式停止检查点（替代已删除的 ctypes 强杀）：目录扫描之间可退出
            if self._move_cancel_event.is_set():
                signal_qt.show_log_text(" ⛔️ 已取消移动文件！")
                return
            if not Path(movie_path).exists():
                signal_qt.show_log_text(f" 🔴 Movie folder does not exist: {movie_path}")
                continue
            c = get_movie_path_setting(movie_path_override=movie_path)
            ignore_dirs = c.ignore_dirs
            ignore_dirs.append(movie_path / "Movie_moved")
            movie_list = executor.run(
                movie_lists(ignore_dirs, manager.config.media_type + manager.config.sub_type, movie_path)
            )
            movie_items.extend((movie_path, file_path) for file_path in movie_list)
        if not movie_items:
            signal_qt.show_log_text("No movie found!")
            signal_qt.show_log_text("================================================================================")
            return
        signal_qt.show_log_text("Start move movies...")
        skip_list = []
        for movie_path, file_path in movie_items:
            # 协作式停止检查点：每个文件移动前可退出（已移动的不回滚）
            if self._move_cancel_event.is_set():
                signal_qt.show_log_text(" ⛔️ 已取消移动文件！")
                break
            des_path = movie_path / "Movie_moved"
            if not des_path.exists():
                signal_qt.show_log_text(f"Created folder: {des_path}")
            os.makedirs(des_path, exist_ok=True)
            file_name = file_path.name
            file_ext = file_path.suffix.lower()
            try:
                shutil.move(file_path, des_path)
                if file_ext in manager.config.media_type:
                    signal_qt.show_log_text("   Move movie: " + file_name + " to Movie_moved Success!")
                else:
                    signal_qt.show_log_text("   Move sub: " + file_name + " to Movie_moved Success!")
            except Exception as e:
                skip_list.append([file_name, file_path, str(e)])
        if skip_list:
            signal_qt.show_log_text(f"\n{len(skip_list)} file(s) did not move!")

    # 工具-封面补图
    def pushButton_cover_backfill_start_clicked(self):
        from .tool_handlers import pushButton_cover_backfill_start_clicked

        pushButton_cover_backfill_start_clicked(self)

    # 设置-刮削目录 点击检查待刮削目录并清理文件
    def pushButton_check_and_clean_files_clicked(self):
        if not manager.computed.can_clean:
            self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()
        try:
            executor.submit(check_and_clean_files())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-字幕 为所有视频中的无字幕视频添加字幕
    def pushButton_add_sub_for_all_video_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_sub_for_all_video())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # region 设置-下载
    # 为所有视频中的创建/删除剧照附加内容
    def pushButton_add_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除剧照副本
    def pushButton_add_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除主题视频
    def pushButton_add_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())
