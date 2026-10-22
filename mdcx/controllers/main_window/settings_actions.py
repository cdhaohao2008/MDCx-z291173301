"""设置页的动作：计数器刷新、自定义站点开关、配置初始化/保存/另存，以及按钮启用状态。

change_buttons_status / reset_buttons_status 在这里，因为它们统管全局按钮（其中包含演员库按钮），
和演员库的任务状态属于同一件事。"""

import os
import re
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
)

from mdcx.config.enums import Website
from mdcx.config.extend import parse_media_paths
from mdcx.config.manager import manager
from mdcx.consts import IS_WINDOWS
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils import get_current_time


class SettingsActionsMixin:
    # 设置-线程数量
    def lcdNumber_thread_change(self):
        thread_number = self.Ui.horizontalSlider_thread.value()
        self.Ui.lcdNumber_thread.display(thread_number)

    # 设置-javdb延时
    def lcdNumber_javdb_time_change(self):
        javdb_time = self.Ui.horizontalSlider_javdb_time.value()
        self.Ui.lcdNumber_javdb_time.display(javdb_time)

    # 设置-其他网站延时
    def lcdNumber_thread_time_change(self):
        thread_time = self.Ui.horizontalSlider_thread_time.value()
        self.Ui.lcdNumber_thread_time.display(thread_time)

    # 设置-超时时间
    def lcdNumber_timeout_change(self):
        timeout = self.Ui.horizontalSlider_timeout.value()
        self.Ui.lcdNumber_timeout.display(timeout)

    # 设置-重试次数
    def lcdNumber_retry_change(self):
        retry = self.Ui.horizontalSlider_retry.value()
        self.Ui.lcdNumber_retry.display(retry)

    # 设置-水印大小
    def lcdNumber_mark_size_change(self):
        mark_size = self.Ui.horizontalSlider_mark_size.value()
        self.Ui.lcdNumber_mark_size.display(mark_size)

    # 设置-网络-网址设置-下拉框切换
    def switch_custom_website_change(self, site):
        # 显示文本格式为“站点名（区域标签） 定位说明”，先按空格取首段、再剥区域标签后缀后再转枚举
        site = site.split(" ")[0].split("（")[0].strip()
        if site not in Website:
            # official 子行（Official·HEYZO 等）：自定义网址框仅作该子站地址展示，
            # 保存时按非枚举值跳过，不会写入 Official 配置
            if site.startswith("Official·") or site.startswith("official·"):
                from mdcx.crawlers.official_uncensored import UNCENSORED_OFFICIAL_SITES

                suffix = site.split("·", 1)[1].strip()
                spec = UNCENSORED_OFFICIAL_SITES.get(suffix)
                if spec is None:
                    lowered = suffix.lower()
                    for key, candidate in UNCENSORED_OFFICIAL_SITES.items():
                        if key.lower() == lowered or candidate.studio.lower() == lowered:
                            spec = candidate
                            break
                if spec is not None:
                    self.Ui.lineEdit_site_custom_url.setText(spec.base_url.rstrip("/") + "/")
            return
        site = Website(site)
        self.Ui.lineEdit_site_custom_url.setText(manager.config.get_site_url(site))

    # 设置 - 网络 - 使用代理 - 添加网站
    def _add_no_proxy_site(self, site_value: str):
        """当用户从下拉框选择网站时，添加到输入框"""
        # 显示文本格式为“站点名（区域标签） 定位说明”，先按空格取首段、再剥区域标签后缀，取值时剥掉
        site_value = site_value.split(" ")[0].split("（")[0].strip()
        if not site_value or site_value == "选择网站...":
            return
        # 重置下拉框到默认值
        self.Ui.comboBox_no_proxy_sites.setCurrentIndex(0)
        # 获取当前输入
        current = self.Ui.lineEdit_no_proxy_sites.text().strip()
        # 分割现有值
        existing_sites = [s.strip() for s in current.split(",") if s.strip()]
        # 添加新网站（如果不存在）
        if site_value not in existing_sites:
            existing_sites.append(site_value)
            # 更新输入框
            self.Ui.lineEdit_no_proxy_sites.setText(",".join(existing_sites))

    def config_file_change(self, new_config_file: str):
        if new_config_file != manager.file:
            new_config_path = manager.data_folder / new_config_file
            signal_qt.show_log_text(
                f"\n================================================================================\n切换配置：{new_config_path}"
            )
            manager.path = new_config_path
            temp_dark = self.dark_mode
            temp_window_radius = self.window_radius
            self.load_config()
            if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                self.show_flag = True
                self._windows_auto_adjust()
            signal_qt.show_scrape_info(f"💡 配置已切换！{get_current_time()}")

    # 重置配置
    def pushButton_init_config_clicked(self):
        self.Ui.pushButton_init_config.setEnabled(False)
        self.Ui.pushButton_init_config_tool.setEnabled(False)
        manager.reset()
        temp_dark = self.dark_mode
        temp_window_radius = self.window_radius
        self.load_config()
        if temp_dark and temp_window_radius:
            self.show_flag = True
            self._windows_auto_adjust()
        self.Ui.pushButton_init_config.setEnabled(True)
        self.Ui.pushButton_init_config_tool.setEnabled(True)
        signal_qt.show_scrape_info(f"💡 配置已重置！{get_current_time()}")

    # 设置-命名-分集-字母
    def checkBox_cd_part_a_clicked(self):
        if self.Ui.checkBox_cd_part_a.isChecked():
            self.Ui.checkBox_cd_part_c.setEnabled(True)
        else:
            self.Ui.checkBox_cd_part_c.setEnabled(False)

    # 分离模式-复用/覆盖元数据互斥：只允许同时选中一个（toggled(False) 不动作，故无信号回环）
    def checkBox_separate_reuse_meta_changed(self, checked):
        if checked:
            self.Ui.checkBox_separate_overwrite_meta.setChecked(False)

    def checkBox_separate_overwrite_meta_changed(self, checked):
        if checked:
            self.Ui.checkBox_separate_reuse_meta.setChecked(False)

    # 分离模式-STRM：生成是覆盖的前提，未勾选生成时覆盖项置灰（保留其勾选值，重新勾选生成后自动恢复）
    def checkBox_separate_generate_strm_changed(self, checked):
        self.Ui.checkBox_separate_overwrite_strm.setEnabled(bool(checked))

    # 整理模式-本地/网盘间隔互斥：两者必须勾选其中一个（默认档＝「本地存储不设置
    # 时间间隔整理文件」）。勾选其一自动去勾另一；把唯一勾选的那枚取消时立即
    # 回落到默认档，保证界面上永远有且只有一枚被勾选（保存时还有配置层兜底校验）
    def checkBox_organize_local_no_interval_changed(self, checked):
        if checked:
            self.Ui.checkBox_organize_netdisk_rest_interval.setChecked(False)
        elif not self.Ui.checkBox_organize_netdisk_rest_interval.isChecked():
            # 两枚都没勾 → 回落到默认档「本地存储不设置时间间隔整理文件」
            self.Ui.checkBox_organize_local_no_interval.setChecked(True)

    def checkBox_organize_netdisk_rest_interval_changed(self, checked):
        if checked:
            self.Ui.checkBox_organize_local_no_interval.setChecked(False)

    # 视频模式-删除/移动互斥：两枚复选框只能同时选中一个。
    # 勾选其一自动去勾另一（toggled(False) 不动作，故无信号回环）；
    # 两枚都不勾选是合法中间态：图片/nfo/字幕等伴生文件全部留在原目录。
    def checkBox_sortmode_delpic_changed(self, checked):
        if checked:
            self.Ui.checkBox_sortmode_movefile.setChecked(False)

    def checkBox_sortmode_movefile_changed(self, checked):
        if checked:
            self.Ui.checkBox_sortmode_delpic.setChecked(False)

    # 高级页-文件移动策略互斥：覆盖旧文件 / 保留旧文件必须勾选其中一个
    # （默认档＝「保留旧文件」）。勾选其一自动去勾另一；把唯一勾选的那枚取消时
    # 立即回落到默认档，保证界面上永远有且只有一枚被勾选（保存时还有配置层
    # 兜底校验：未勾选按默认档校正后写盘）
    def checkBox_move_overwrite_changed(self, checked):
        if checked:
            self.Ui.checkBox_move_keep.setChecked(False)
        elif not self.Ui.checkBox_move_keep.isChecked():
            # 两枚都没勾 → 回落到默认档「保留旧文件」
            self.Ui.checkBox_move_keep.setChecked(True)

    def checkBox_move_keep_changed(self, checked):
        if checked:
            self.Ui.checkBox_move_overwrite.setChecked(False)
        elif not self.Ui.checkBox_move_overwrite.isChecked():
            # 「保留旧文件」是默认档，取消勾选后立即回落（另一枚也没勾时）
            self.Ui.checkBox_move_keep.setChecked(True)

    # 设置-刮削目录-同意清理(我已知晓/我已同意)
    def checkBox_i_agree_clean_clicked(self):
        if self.Ui.checkBox_i_understand_clean.isChecked() and self.Ui.checkBox_i_agree_clean.isChecked():
            self.Ui.pushButton_check_and_clean_files.setEnabled(True)
            self.Ui.checkBox_auto_clean.setEnabled(True)
        else:
            self.Ui.pushButton_check_and_clean_files.setEnabled(False)
            self.Ui.checkBox_auto_clean.setEnabled(False)

    # 读取设置页的设置, 保存config.ini，然后重新加载
    def _check_mac_config_folder(self):
        if self.check_mac and not IS_WINDOWS and ".app/Contents/Resources" in manager.data_folder.as_posix():
            self.check_mac = False
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "选择配置文件目录",
                f"检测到当前配置文件目录为：\n {manager.data_folder}\n\n由于 MacOS 平台在每次更新 APP 版本时会覆盖该目录的配置，因此请选择其他的配置目录！\n这样下次更新 APP 时，选择相同的配置目录即可读取你之前的配置！！！",
            )
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("选择目录")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = box.exec()
            if reply == QMessageBox.StandardButton.Yes:
                self.pushButton_select_config_folder_clicked()

    # 设置-保存
    def pushButton_save_config_clicked(self):
        try:
            self.save_config()
            self.load_config()  # 确保界面显示和实际配置一致
            # 重建网络派生对象：AsyncWebClient 的重试/超时/代理在构造时固化，
            # 仅改 manager.config 不会生效（如检测网络仍用旧重试次数）。
            # _replace_config 原子切换新客户端，旧客户端由持有方租约保护、
            # 空闲后关闭（检测进行中点保存不断连）。
            manager._replace_config(manager.config)
        except Exception:
            error = traceback.format_exc()
            signal_qt.show_traceback_log(error)
            self.tray_icon_show()
            QMessageBox.critical(self, "保存配置失败", f"配置保存失败，软件已保持运行。\n\n{error}")
            return
        signal_qt.show_scrape_info(f"💡 配置已保存！{get_current_time()}")

    # 设置-另存为
    def pushButton_save_new_config_clicked(self):
        new_config_name, ok = QInputDialog.getText(self, "另存为新配置", "请输入新配置的文件名")
        if ok and new_config_name:
            new_config_name = new_config_name.replace("/", "").replace("\\", "")
            new_config_name = re.sub(r'[\\:*?"<>|\r\n]+', "", new_config_name)
            if os.path.splitext(new_config_name)[1] != ".json":
                new_config_name += ".json"
            if new_config_name != manager.file:
                manager.path = manager.data_folder / new_config_name
                self.pushButton_save_config_clicked()

    def save_config(self): ...
    # region 其它
    # 点选择目录弹窗
    def _get_select_folder_path(self, default_source: QLineEdit | str | Path | None = None):
        media_path = self._get_select_folder_default_path(default_source).as_posix()
        media_folder_path = QFileDialog.getExistingDirectory(
            None, "选择目录", media_path, options=self.options | QFileDialog.Option.ShowDirsOnly
        )
        return media_folder_path

    def _get_select_folder_default_path(self, default_source: QLineEdit | str | Path | None = None) -> Path:
        if isinstance(default_source, QLineEdit):
            default_text = default_source.text()
        elif default_source is None:
            default_text = ""
        else:
            default_text = str(default_source)

        for path in self._iter_select_folder_candidates(default_text):
            if path.is_dir():
                return path

        for path in self._iter_select_folder_candidates(self.Ui.lineEdit_movie_path.text()):
            if path.is_dir():
                return path

        if manager.data_folder.is_dir():
            return manager.data_folder
        return Path.home()

    def _iter_select_folder_candidates(self, path_text: str):
        movie_roots = [path for path in parse_media_paths(self.Ui.lineEdit_movie_path.text()) if path.is_dir()]
        for item in re.split(r"[;；,，]", path_text):
            item = item.strip().strip("\"'")
            if not item:
                continue
            path = Path(item)
            if path.is_absolute():
                yield path
                continue
            for movie_root in movie_roots:
                yield movie_root / path
            yield path

    def change_buttons_status(self):
        Flags.stop_other = True
        self.Ui.pushButton_start_cap.setText("■ 停止")
        self.Ui.pushButton_start_cap2.setText("■ 停止")
        self.Ui.pushButton_select_media_folder.setVisible(False)
        self.Ui.pushButton_start_single_file.setEnabled(False)
        self.Ui.pushButton_start_single_file.setText("正在刮削中...")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(False)
        self.Ui.pushButton_add_sub_for_all_video.setText("正在刮削中...")
        self.Ui.pushButton_show_pic_actor.setEnabled(False)
        self.Ui.pushButton_show_pic_actor.setText("刮削中...")
        self.Ui.pushButton_add_actor_info.setEnabled(False)
        self.Ui.pushButton_add_actor_info.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic.setEnabled(False)
        self.Ui.pushButton_add_actor_pic.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(False)
        self.Ui.pushButton_add_actor_pic_kodi.setText("正在刮削中...")
        self.Ui.pushButton_del_actor_folder.setEnabled(False)
        self.Ui.pushButton_del_actor_folder.setText("正在刮削中...")
        # self.Ui.pushButton_check_and_clean_files.setEnabled(False)
        self.Ui.pushButton_check_and_clean_files.setText("正在刮削中...")
        self.Ui.pushButton_move_mp4.setEnabled(False)
        self.Ui.pushButton_move_mp4.setText("正在刮削中...")
        self.Ui.pushButton_find_missing_number.setEnabled(False)
        self.Ui.pushButton_find_missing_number.setText("正在刮削中...")
        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#B91C1C;}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap2{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#B91C1C;}"
        )
        self.Ui.pushButton_cover_backfill_start.setEnabled(False)
        self.Ui.pushButton_actor_db_translate.setEnabled(False)
        self.Ui.pushButton_actor_db_link.setEnabled(False)
        self.Ui.pushButton_actor_db_sync_aliases.setEnabled(False)
        self.Ui.pushButton_actor_db_fill_Minnano.setEnabled(False)
        self.Ui.pushButton_actor_db_fill_zh_javdb.setEnabled(False)

    def reset_buttons_status(self):
        self.Ui.pushButton_start_cap.setEnabled(True)
        self.Ui.pushButton_start_cap2.setEnabled(True)
        self.pushButton_start_cap.emit("开始")
        self.pushButton_start_cap2.emit("开始")
        self.Ui.pushButton_select_media_folder.setVisible(True)
        self.Ui.pushButton_start_single_file.setEnabled(True)
        self.pushButton_start_single_file.emit("开始刮削")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(True)
        self.pushButton_add_sub_for_all_video.emit("点击检查所有视频的字幕情况并为无字幕视频添加字幕")

        self.Ui.pushButton_show_pic_actor.setEnabled(True)
        self.pushButton_show_pic_actor.emit("查看")
        self.Ui.pushButton_add_actor_info.setEnabled(True)
        self.pushButton_add_actor_info.emit("开始补全")
        self.Ui.pushButton_add_actor_pic.setEnabled(True)
        self.pushButton_add_actor_pic.emit("开始补全")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(True)
        self.pushButton_add_actor_pic_kodi.emit("开始补全")
        self.Ui.pushButton_del_actor_folder.setEnabled(True)
        self.pushButton_del_actor_folder.emit("清除所有.actors文件夹")
        self.Ui.pushButton_check_and_clean_files.setEnabled(True)
        self.pushButton_check_and_clean_files.emit("点击检查待刮削目录并清理文件")
        self.Ui.pushButton_move_mp4.setEnabled(True)
        self.pushButton_move_mp4.emit("开始移动")
        self.Ui.pushButton_find_missing_number.setEnabled(True)
        self.pushButton_find_missing_number.emit("检查缺失番号")
        self.Ui.pushButton_cover_backfill_start.setEnabled(True)
        # actor_db 由主刮削管理（change_buttons_status 禁用）的按钮子集：
        # 仅当对应 btn_attr 不在 _actor_db_running 时才恢复 Enabled；在跑则保持 disabled。
        for btn_attr in self._ACTOR_DB_SCRAPE_MANAGED:
            btn = getattr(self.Ui, f"pushButton_{btn_attr}", None)
            sig = getattr(self, f"pushButton_{btn_attr}", None)
            if btn is not None and btn_attr not in self._actor_db_running:
                btn.setEnabled(True)
            if sig is not None:
                sig.emit(self._ACTOR_DB_IDLE_TEXT_MAP[btn_attr])

        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#4C6EE0}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap2{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#4C6EE0}"
        )
        Flags.file_mode = FileMode.Default
        self.threads_list = []
        with Flags.guarded():
            failed_count = len(Flags.failed_list)
        if failed_count:
            self.Ui.pushButton_scraper_failed_list.setText(f"一键重新刮削当前 {failed_count} 个失败文件")
        else:
            self.Ui.pushButton_scraper_failed_list.setText("当有失败任务时，点击可以一键刮削当前失败列表")
