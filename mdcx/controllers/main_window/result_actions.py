"""主页面结果树上的用户操作：播放、打开目录、打开 NFO、相似搜索、按番号/网址搜索、
删除文件/文件夹、建立软链接与硬链接，以及结果区的复选框联动。"""

import os
import threading
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPointF,
    Qt,
)
from PyQt6.QtGui import QHoverEvent
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMessageBox,
)

from mdcx.config.extend import deal_url
from mdcx.config.resources import resources
from mdcx.core.scrape_cache import ScrapeStateCache
from mdcx.core.scraper import again_search
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.utils import (
    get_current_time,
    split_path,
)
from mdcx.utils.file import (
    delete_file_sync,
    open_file_thread,
)
from mdcx.utils.path import safe_rmtree
from mdcx.views.similar_window import SimilarDialog


class ResultActionsMixin:
    # 主界面-点击树状条目
    def treeWidget_number_clicked(self, *_args):
        selected_items = self._get_selected_result_items()
        if len(selected_items) != 1:
            if len(selected_items) > 1:
                self._clear_main_info_panel()
            return

        item = selected_items[0]
        try:
            index_json = str(item.text(0))
            if index_json == self.show_name:
                return
            overlay_open = not self.Ui.widget_nfo.isHidden()
            if overlay_open and not self._confirm_nfo_editor_leave():
                prev = self._find_result_item_by_name(self.show_name) if self.show_name else None
                tree = self.Ui.treeWidget_number
                tree.blockSignals(True)
                try:
                    tree.clearSelection()
                    if prev is not None:
                        prev.setSelected(True)
                finally:
                    tree.blockSignals(False)
                return
            self.set_main_info(self.json_array[index_json])
            self._show_nfo_info()
            if overlay_open:
                self._sync_nfo_overlay_geometry()
        except Exception:
            signal_qt.show_traceback_log(item.text(0) + ": No info!")

    def _check_main_file_path(self):
        selected_entries = self._get_selected_entries()
        if len(selected_entries) > 1:
            QMessageBox.about(self, "选择过多", "请只选择一个项目后再使用！！")
            signal_qt.show_scrape_info(f"💡 请只选择一个项目后再使用！{get_current_time()}")
            return False
        if len(selected_entries) == 1:
            _, show_name, show_data, file_path = selected_entries[0]
            self.show_name = show_name
            self.set_main_info(show_data)
            self.file_main_open_path = file_path

        if self.file_main_open_path == Path() or not self.file_main_open_path.is_file():
            QMessageBox.about(self, "没有目标文件", "请刮削后再使用！！")
            signal_qt.show_scrape_info(f"💡 请刮削后使用！{get_current_time()}")
            return False
        return True

    def main_play_click(self):
        """
        主界面点播放
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_play.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_play, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, False), daemon=True)
            t.start()

    def main_open_folder_click(self):
        """
        主界面点打开文件夹
        """
        self.Ui.pushButton_open_folder.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_folder, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, True), daemon=True)
            t.start()

    def main_open_nfo_click(self):
        """
        主界面点打开nfo
        """
        self.Ui.pushButton_open_nfo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_nfo, event)
        if self._check_main_file_path():
            self.Ui.widget_nfo.show()
            # 议题 #154：首次打开路径不经过 resizeEvent，需显式同步覆盖层几何，
            # 否则沿用 .ui 设计尺寸、字段布局与钉底按钮错位。
            self._sync_nfo_overlay_geometry()
            self._show_nfo_info()

    def main_show_similar_click(self):
        """
        主界面点查看相似片推荐
        """
        entries = self._get_selected_entries()
        if not entries:
            if not self.show_data or not self.show_data.data.number:
                signal_qt.show_log_text(" 🔴 请先在结果树中选择一部影片，再查看相似推荐！")
                return
            target = self.show_data.data
        else:
            target = entries[0][2].data

        # 相似语料 = 历史成功结果（跨会话，来自 SQLite 缓存）+ 当次刮削结果
        corpus = SimilarDialog.collect_corpus(Flags.json_data_dic)
        cache = ScrapeStateCache(resources.u("scrape_state.db"))
        if cache.open():
            try:
                cached_corpus = SimilarDialog.collect_corpus_from_cache(cache)
                seen_numbers = {getattr(c, "number", "") for c in corpus}
                for c in cached_corpus:
                    if c.number not in seen_numbers:
                        corpus.append(c)
            finally:
                cache.close()
        if len(corpus) < 2:
            signal_qt.show_log_text(" 🔴 相似推荐需要至少 2 部已刮削影片，请先刮削更多！")
            return

        dialog = SimilarDialog(corpus, target, parent=self)
        dialog.item_selected.connect(self._jump_to_similar_number)
        dialog.exec()

    def _jump_to_similar_number(self, number: str):
        """双击相似推荐项后，在结果树中定位到对应影片。"""
        for show_name, show_data in self.json_array.items():
            if getattr(show_data, "data", None) and show_data.data.number == number:
                item = self._find_result_item_by_name(show_name)
                if item is not None:
                    self.Ui.treeWidget_number.clearSelection()
                    item.setSelected(True)
                    self.Ui.treeWidget_number.scrollToItem(item)
                    self.treeWidget_number_clicked()
                return
        # 历史缓存中的结果不在当次结果树中，无法跳转，仅提示
        signal_qt.show_log_text(f" 💡 番号 {number} 是历史刮削结果，不在本次结果树中，无法跳转")

    def main_open_right_menu(self):
        """
        主界面点打开右键菜单
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_right_menu.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_right_menu, event)
        self._menu()

    def search_by_number_clicked(self):
        """
        主界面点输入番号
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            default_text = os.path.splitext(main_file_name)[0].upper()
            text, ok = QInputDialog.getText(
                self, "输入番号重新刮削", f"文件名: {main_file_name}\n请输入番号:", text=default_text
            )
            if ok and text:
                with Flags.guarded():
                    Flags.again_dic[file_path] = (text, "", "")
                signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                if self.Ui.pushButton_start_cap.text() == "开始":
                    again_search()

    def search_by_url_clicked(self):
        """
        主界面点输入网址
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            from mdcx.manual import ManualConfig

            supported_sites = ", ".join(sorted({site.value for site in ManualConfig.WEB_DIC.values()}))
            text, ok = QInputDialog.getText(
                self,
                "输入网址重新刮削",
                f"文件名: {main_file_name}\n支持网站: {supported_sites}"
                "\n请输入番号对应的网址（不是网站首页地址！！！是番号页面地址！！！）:",
            )
            if ok and text:
                website, url = deal_url(text)
                if website:
                    with Flags.guarded():
                        Flags.again_dic[file_path] = ("", url, website)
                    signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                    if self.Ui.pushButton_start_cap.text() == "开始":
                        again_search()
                else:
                    signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")

    def main_del_file_click(self):
        """
        主界面点删除文件
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        if len(file_paths) == 1:
            box_text = f"将要删除文件: \n{file_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(file_paths)} 个文件：\n{self._build_delete_preview(file_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件")
        signal_qt.show_log_text(f" 📦 本次待删除文件数: {len(file_paths)}")

        success_show_names = []
        failure_details: list[tuple[Path, str]] = []
        for show_name, file_path in delete_targets:
            result, error_info = delete_file_sync(file_path)
            if result:
                if show_name:
                    success_show_names.append(show_name)
                signal_qt.show_log_text(f" ✅ 已删除文件: {file_path}")
            else:
                reason = self._normalize_delete_error_reason(error_info)
                failure_details.append((file_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件失败: {file_path}\n    原因: {reason}")

        self._remove_deleted_result_items(success_show_names)
        fail_count = len(failure_details)
        success_count = len(file_paths) - fail_count
        signal_qt.show_log_text(f" 🎉 删除文件完成：成功 {success_count} 个，失败 {fail_count} 个")
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 文件删除完成，成功 {success_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件", success_count, failure_details)
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已删除文件！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已删除 {success_count} 个文件！{get_current_time()}")

    def main_del_folder_click(self):
        """
        主界面点删除文件夹
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        folder_to_show_names: dict[Path, list[str]] = {}
        for show_name, file_path in delete_targets:
            folder_path = Path(split_path(file_path)[0])
            folder_to_show_names.setdefault(folder_path, [])
            if show_name:
                folder_to_show_names[folder_path].append(show_name)

        folder_paths = sorted(folder_to_show_names, key=lambda p: len(p.parts), reverse=True)
        if len(folder_paths) == 1:
            box_text = f"将要删除文件夹: \n{folder_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(folder_paths)} 个文件夹（来源于 {len(file_paths)} 个选中项）：\n"
                f"{self._build_delete_preview(folder_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件和文件夹")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件夹")
        signal_qt.show_log_text(f" 📦 本次待删除文件夹数: {len(folder_paths)}")

        success_folder_count = 0
        success_show_names: list[str] = []
        failure_details: list[tuple[Path, str]] = []
        for folder_path in folder_paths:
            try:
                # 守护: 拒绝系统关键路径(用户主目录/文件根), 防止路径计算错误误删用户文件
                safe_rmtree(folder_path)
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 已删除文件夹: {folder_path}")
            except FileNotFoundError:
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 文件夹不存在，按已删除处理: {folder_path}")
            except Exception as error:
                reason = self._normalize_delete_error_reason(str(error))
                failure_details.append((folder_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件夹失败: {folder_path}\n    原因: {reason}")

        if success_show_names:
            self._remove_deleted_result_items(success_show_names)

        fail_count = len(failure_details)
        signal_qt.show_log_text(f" 🎉 删除文件夹完成：成功 {success_folder_count} 个，失败 {fail_count} 个")
        if fail_count:
            self.show_scrape_info(
                f"💡 文件夹删除完成，成功 {success_folder_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件夹", success_folder_count, failure_details)
        elif success_folder_count == 1:
            self.show_scrape_info(f"💡 已删除文件夹！{get_current_time()}")
        else:
            self.show_scrape_info(f"💡 已删除 {success_folder_count} 个文件夹！{get_current_time()}")

    def main_make_symlink_click(self):
        """
        主界面在指定位置创建软链接
        """
        self._create_links_for_selected_files("soft")

    def main_make_symlink_in_dir_click(self):
        """
        主界面在指定位置创建软链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("soft", group_in_named_dir=True)

    def main_make_hardlink_click(self):
        """
        主界面在指定位置创建硬链接
        """
        self._create_links_for_selected_files("hard")

    def main_make_hardlink_in_dir_click(self):
        """
        主界面在指定位置创建硬链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("hard", group_in_named_dir=True)

    def _pic_main_clicked(self):
        """
        主界面点图片
        """
        file_info = None if self.show_data is None else self.show_data.file_info
        self.cutwindow.showimage(self.img_path, file_info)
        self.cutwindow.present()

    # 主界面-开关封面显示
    def checkBox_cover_clicked(self):
        if not self.Ui.checkBox_cover.isChecked():
            self.Ui.label_poster.setText("封面图")
            self.Ui.label_thumb.setText("缩略图")
            # 议题 #144: 占位文本态同时清原图缓存, 否则 resize 重放会把图盖回占位;
            # 几何归 _sync_page_layouts 管辖, 此处不再 resize 设计尺寸
            self._poster_src_pixmap = None
            self._thumb_src_pixmap = None
            # 动图（gif）也要停, 否则会在占位文本上继续播放动画
            self._stop_preview_movie("poster")
            self._stop_preview_movie("thumb")
            self.Ui.label_poster_size.setText("")
            self.Ui.label_thumb_size.setText("")
        else:
            self.set_main_info(self.show_data)

    def update_amazon_strict_pic_verify_state(self, *_args):
        """Amazon 高清搜索关闭时联动禁用其子选项（严格校验开关已随读零校验架构移除）。"""
        amazon_enabled = self.Ui.checkBox_amazon_big_pic.isChecked()
        self.Ui.checkBox_amazon_skip_poster_size_precheck.setEnabled(amazon_enabled)
        self.Ui.label_amazon_skip_poster_size_precheck.setEnabled(amazon_enabled)
        if not amazon_enabled:
            self.Ui.checkBox_amazon_skip_poster_size_precheck.setChecked(False)

    def update_field_priority_try_all_images_state(self, *_args):
        self.Ui.checkBox_field_priority_try_all_images.setEnabled(self.Ui.radioButton_scrape_info.isChecked())
