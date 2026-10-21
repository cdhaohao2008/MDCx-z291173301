"""主页面结果树：选中项、展示信息、预览图、链接/软硬链接目标目录计算。

包含链接目录名的清洗规则常量（LINK_DIR_INVALID_CHARS_RE / WINDOWS_RESERVED_DIR_NAMES /
DEFAULT_LINK_DIR_NAME），它们只被本模块的清洗方法使用。"""

import re
import traceback
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import (
    QItemSelectionModel,
    QRect,
    Qt,
    QTimer,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
)

from mdcx.base.file import save_success_list
from mdcx.config.enums import NfoInclude
from mdcx.config.extend import get_movie_path_setting
from mdcx.config.manager import manager
from mdcx.models.flags import Flags
from mdcx.models.model_types import (
    CrawlersResult,
    FileInfo,
    OtherInfo,
    ShowData,
)
from mdcx.signals import signal_qt
from mdcx.utils import (
    executor,
    get_current_time,
)
from mdcx.utils.file import (
    create_hardlink_sync,
    create_symlink_sync,
    resolve_link_source_sync,
    resolve_success_record_source_sync,
)

LINK_DIR_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
WINDOWS_RESERVED_DIR_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
DEFAULT_LINK_DIR_NAME = "unnamed"


class ResultTreeMixin:
    # region 刮削结果显示
    def _addTreeChild(self, result, filename):
        node = QTreeWidgetItem()
        node.setText(0, filename)
        if result == "succ":
            self.item_succ.addChild(node)
        else:
            self.item_fail.addChild(node)

    def _get_single_selected_entry(self) -> tuple[QTreeWidgetItem, str, ShowData, Path] | None:
        selected_entries = self._get_selected_entries()
        if len(selected_entries) != 1:
            return None
        return selected_entries[0]

    def _has_single_selected_result_item(self) -> bool:
        return self._get_single_selected_entry() is not None

    def _set_result_item_as_current_selection(self, item: QTreeWidgetItem) -> None:
        if item.text(0) in {"成功", "失败"}:
            return

        tree = self.Ui.treeWidget_number
        selected_items = tree.selectedItems()
        if item not in selected_items:
            tree.clearSelection()
            item.setSelected(True)
        model_index = tree.indexFromItem(item)
        if model_index.isValid():
            tree.selectionModel().setCurrentIndex(model_index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def show_list_name(self, status: Literal["succ", "fail"], show_data: ShowData, real_number=""):
        # 添加树状节点
        self._addTreeChild(status, show_data.show_name)

        if not show_data.data.title:
            show_data.data.title = show_data.show_name
            show_data.data.number = real_number
        self.json_array[show_data.show_name] = show_data
        if not self._has_single_selected_result_item():
            self.show_name = show_data.show_name
            self.set_main_info(show_data)

    @staticmethod
    def _elide_label_two_lines(label, text: str, max_lines: int = 2) -> str:
        """议题 #154：把文本按标签当前宽度裁到最多两行，超出部分以省略号截断。

        简介/标签恒定 40px 高，最多显示两行；不同窗口宽度下每行容纳的字数不同，
        因此必须按实际宽度重算，最大化才能比最小化显示更多内容。
        """
        text = text or ""
        if not text:
            return text
        width = label.width()
        if width <= 0:
            return text
        metrics = label.fontMetrics()
        max_h = metrics.lineSpacing() * max_lines
        flags = int(Qt.TextFlag.TextWordWrap)
        # 用无界高度测量真实换行高度，再与两行上限比较（受限高度会把返回值截断）
        probe = QRect(0, 0, width, 1_000_000)
        if metrics.boundingRect(probe, flags, text).height() <= max_h:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = text[:mid].rstrip() + "…"
            if metrics.boundingRect(probe, flags, candidate).height() <= max_h:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + "…"

    def _set_main_two_line(self, label, text: str) -> None:
        label.setText(self._elide_label_two_lines(label, text))

    def _refresh_main_outline_tag(self) -> None:
        """议题 #154：窗口宽度变化后，按新宽度重算简介/标签的两行省略文本。"""
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        self._set_main_two_line(ui.label_outline, getattr(self, "_main_outline_text", ""))
        self._set_main_two_line(ui.label_tag, getattr(self, "_main_tag_text", ""))

    def set_main_info(self, show_data: ShowData | None):
        if show_data is not None:
            self.show_data = show_data
            file_info = show_data.file_info
            data = show_data.data
            other = show_data.other
            self.show_name = show_data.show_name
        else:
            file_info = FileInfo.empty()
            data = CrawlersResult.empty()
            other = OtherInfo.empty()
            self.show_name = None
        try:
            number = data.number
            self.Ui.label_number.setToolTip(number)
            if len(number) > 11:
                number = number[:10] + "……"
            self.Ui.label_number.setText(number)
            actor = str(data.actor)
            if data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = str(data.all_actor)
            self.Ui.label_actor.setToolTip(actor)
            if number and not actor:
                actor = manager.config.actor_no_name
            if len(actor) > 10:
                actor = actor[:9] + "……"
            self.Ui.label_actor.setText(actor)
            self.file_main_open_path = file_info.file_path  # 文件路径

            title = data.title.split("\n")[0].strip(" :")
            self.Ui.label_title.setToolTip(title)
            if len(title) > 27:
                title = title[:25] + "……"
            self.Ui.label_title.setText(title)
            outline = str(data.outline)
            self._main_outline_text = outline
            self.Ui.label_outline.setToolTip(outline)
            self._set_main_two_line(self.Ui.label_outline, outline)
            tag = ", ".join(str(item) for item in data.tag) if isinstance(data.tag, list) else str(data.tag)
            self._main_tag_text = tag
            self.Ui.label_tag.setToolTip(tag)
            self._set_main_two_line(self.Ui.label_tag, tag)
            self.Ui.label_release.setText(str(data.release))
            self.Ui.label_release.setToolTip(str(data.release))
            if data.runtime:
                self.Ui.label_runtime.setText(str(data.runtime) + " 分钟")
                self.Ui.label_runtime.setToolTip(str(data.runtime) + " 分钟")
            else:
                self.Ui.label_runtime.setText("")
            self.Ui.label_director.setText(str(data.director))
            self.Ui.label_director.setToolTip(str(data.director))
            series = str(data.series)
            self.Ui.label_series.setToolTip(series)
            if len(series) > 32:
                series = series[:31] + "……"
            self.Ui.label_series.setText(series)
            self.Ui.label_studio.setText(data.studio)
            self.Ui.label_studio.setToolTip(data.studio)
            self.Ui.label_publish.setText(data.publisher)
            self.Ui.label_publish.setToolTip(data.publisher)
            self.Ui.label_poster.setToolTip("点击裁剪图片")
            self.Ui.label_thumb.setToolTip("点击裁剪图片")
            # 生成img_path，用来裁剪使用
            img_path = other.fanart_path if other.fanart_path and other.fanart_path.is_file() else other.thumb_path
            self.img_path = img_path
            if self.Ui.checkBox_cover.isChecked():  # 主界面显示封面和缩略图
                poster_path = other.poster_path
                thumb_path = other.thumb_path
                fanart_path = other.fanart_path
                if not (thumb_path and thumb_path.is_file()) and fanart_path and fanart_path.is_file():
                    thumb_path = fanart_path
                poster_from = data.poster_from
                cover_from = data.thumb_from
                self._request_preview_images(poster_path, thumb_path, poster_from, cover_from)
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _request_preview_images(
        self,
        poster_path: Path | None,
        thumb_path: Path | None,
        poster_from="",
        cover_from="",
        force_reload: bool = False,
    ) -> None:
        self.preview_request_id += 1
        if not poster_path or not poster_path.is_file():
            self.resize_label_and_setpixmap([False, "", "暂无封面图", 156, 220], None)
        if not thumb_path or not thumb_path.is_file():
            self.resize_label_and_setpixmap(None, [False, "", "暂无缩略图", 328, 220])
        self.preview_image_loader.load(
            self.preview_request_id,
            poster_path,
            thumb_path,
            poster_from,
            cover_from,
            force_reload=force_reload,
        )

    def _apply_preview_images(self, request_id: int, poster_pix: list, thumb_pix: list) -> None:
        if request_id != self.preview_request_id:
            return
        poster_text = poster_pix[2] if poster_pix[2] != "暂无封面图" else ""
        thumb_text = thumb_pix[2] if thumb_pix[2] != "暂无缩略图" else ""
        self.Ui.label_poster_size.setText((poster_text + " " + thumb_text).strip())
        self.resize_label_and_setpixmap(poster_pix, thumb_pix)

    def _on_request_preview_images(self, poster_path: str, thumb_path: str) -> None:
        """主线程：裁剪完成后刷新主界面预览（由 request_preview_images 信号触发）。"""
        self._request_preview_images(
            Path(poster_path) if poster_path else None,
            Path(thumb_path) if thumb_path else None,
            poster_from="cut",
            cover_from="local",
            force_reload=True,
        )

    def _rescale_preview_pixmaps(self) -> None:
        """议题 #144: 按 label 当前几何重渲染原图, 保证窗口缩放与图片显示同步。

        缩放规则 KeepAspectRatio(等比、不裁剪、居中留白由 QLabel 对齐负责),
        design 尺寸与原行为一致; 缓存为空(占位文本态)时跳过。
        """
        for src, label in (
            (self._poster_src_pixmap, self.Ui.label_poster),
            (self._thumb_src_pixmap, self.Ui.label_thumb),
        ):
            if src is None or src.isNull():
                continue
            size = label.size()
            if size.width() <= 0 or size.height() <= 0:
                continue
            label.setPixmap(
                src.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resize_label_and_setpixmap(self, poster_pix, thumb_pix):
        if poster_pix is not None:
            if poster_pix[0]:
                self._poster_src_pixmap = (
                    poster_pix[1] if isinstance(poster_pix[1], QPixmap) else QPixmap.fromImage(poster_pix[1])
                )
            else:
                self._poster_src_pixmap = None
                self.Ui.label_poster.clear()
                self.Ui.label_poster.setText(poster_pix[2])

        if thumb_pix is not None:
            if thumb_pix[0]:
                self._thumb_src_pixmap = (
                    thumb_pix[1] if isinstance(thumb_pix[1], QPixmap) else QPixmap.fromImage(thumb_pix[1])
                )
            else:
                self._thumb_src_pixmap = None
                self.Ui.label_thumb.clear()
                self.Ui.label_thumb.setText(thumb_pix[2])

        # 议题 #144: 几何归 _sync_page_layouts 管辖(此前 resize(156,220/328,220)
        # 会把已放大的框砸回设计尺寸), 这里只负责按当前框尺寸出图
        self._rescale_preview_pixmaps()

    def _get_selected_result_items(self) -> list[QTreeWidgetItem]:
        """
        获取当前树状图中有效的结果项（不包含成功/失败根节点）。
        """
        selected_items = []
        for item in self.Ui.treeWidget_number.selectedItems():
            if not item or item.text(0) in {"成功", "失败"}:
                continue
            if item.text(0) not in self.json_array:
                continue
            selected_items.append(item)
        return selected_items

    def _get_selected_entries(self) -> list[tuple[QTreeWidgetItem, str, ShowData, Path]]:
        result = []
        for item in self._get_selected_result_items():
            show_name = item.text(0)
            show_data = self.json_array.get(show_name)
            if show_data is None or not show_data.file_info.file_path:
                continue
            result.append((item, show_name, show_data, show_data.file_info.file_path))
        return result

    def _build_delete_preview(self, paths: list[Path], limit: int = 8) -> str:
        preview = "\n".join(str(path) for path in paths[:limit])
        if len(paths) > limit:
            preview += f"\n... 其余 {len(paths) - limit} 项省略"
        return preview

    def _shorten_text(self, text: str, limit: int) -> str:
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def _normalize_delete_error_reason(self, error_text: str) -> str:
        if not error_text:
            return "未知错误"

        lines = [line.strip() for line in str(error_text).splitlines() if line.strip()]
        full_text = "\n".join(lines).lower()

        if "symbolic link privilege not held" in full_text or "winerror 1314" in full_text:
            return "当前没有创建软链接权限，请尝试以管理员身份运行或开启开发者模式"

        if (
            "winerror 17" in full_text
            or "different disk drive" in full_text
            or "cross-device link" in full_text
            or "not same device" in full_text
        ):
            return "硬链接要求源文件与目标路径位于同一磁盘，请改用软链接"

        if "目标已存在:" in str(error_text):
            for line in lines:
                if "目标已存在:" in line:
                    return line.strip()

        for line in lines:
            if line.startswith("错误:"):
                return line.removeprefix("错误:").strip()

        for line in reversed(lines):
            if "PermissionError:" in line:
                return line.split("PermissionError:", 1)[1].strip()
            if "FileNotFoundError:" in line:
                return line.split("FileNotFoundError:", 1)[1].strip()
            if "OSError:" in line:
                return line.split("OSError:", 1)[1].strip()

        return lines[-1]

    def _build_action_result_text(self, success_count: int, failure_count: int, skipped_count: int = 0) -> str:
        parts = [f"成功 {success_count} 个"]
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 个")
        parts.append(f"失败 {failure_count} 个")
        return "，".join(parts)

    def _show_action_failure_feedback(
        self,
        action_name: str,
        success_count: int,
        failure_details: list[tuple[Path, str]],
        skipped_count: int = 0,
    ) -> None:
        if not failure_details:
            return

        preview_limit = 3
        preview_lines = [
            f"- {self._shorten_text(str(path), 90)}\n  原因：{self._shorten_text(reason, 70)}"
            for path, reason in failure_details[:preview_limit]
        ]
        if len(failure_details) > preview_limit:
            preview_lines.append(f"... 其余 {len(failure_details) - preview_limit} 条请展开“显示详情”或查看日志")

        detail_limit = 20
        detail_lines = [
            f"{index}. {path}\n   原因：{reason}"
            for index, (path, reason) in enumerate(failure_details[:detail_limit], start=1)
        ]
        if len(failure_details) > detail_limit:
            detail_lines.append(f"... 其余 {len(failure_details) - detail_limit} 条请查看日志")
        detail_text = "\n\n".join(detail_lines)

        box = QMessageBox(QMessageBox.Icon.Warning, f"{action_name}结果", f"{action_name}完成")
        box.setInformativeText(
            f"{self._build_action_result_text(success_count, len(failure_details), skipped_count)}\n\n"
            f"{str(chr(10)).join(preview_lines)}"
        )
        box.setDetailedText(detail_text)
        view_log_button = box.addButton("查看日志", QMessageBox.ButtonRole.ActionRole)
        box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        self._bind_localized_message_box_detail_buttons(box)
        box.exec()

        if box.clickedButton() == view_log_button:
            self.pushButton_show_log_clicked()
            self.show_hide_logs(True)

    def _localize_message_box_detail_buttons(self, box: QMessageBox) -> None:
        for button in box.findChildren(QPushButton):
            text = button.text().strip()
            if text == "Show Details...":
                button.setText("显示详情")
            elif text == "Hide Details...":
                button.setText("隐藏详情")

    def _bind_localized_message_box_detail_buttons(self, box: QMessageBox) -> None:
        def relocalize() -> None:
            self._localize_message_box_detail_buttons(box)

        relocalize()
        QTimer.singleShot(0, relocalize)
        for button in box.findChildren(QPushButton):
            button.clicked.connect(lambda _checked=False: QTimer.singleShot(0, relocalize))

    def _select_link_output_dir(self, link_name: str) -> Path | None:
        default_dir = str(get_movie_path_setting().softlink_path)
        selected_dir = QFileDialog.getExistingDirectory(
            None,
            f"选择{link_name}目标目录",
            default_dir,
            options=self.options | QFileDialog.Option.ShowDirsOnly,
        )
        return Path(selected_dir) if selected_dir else None

    def _confirm_record_link_paths(self, link_name: str) -> bool | None:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            f"创建{link_name}",
            f"是否将本次成功创建的{link_name}路径写入程序的刮削成功列表？",
        )
        box.setInformativeText("已存在的同源链接会自动去重；取消则中止本次创建。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        assert yes_button is not None
        yes_button.setText("写入并继续")
        no_button = box.button(QMessageBox.StandardButton.No)
        assert no_button is not None
        no_button.setText("仅创建")
        cancel_button = box.button(QMessageBox.StandardButton.Cancel)
        assert cancel_button is not None
        cancel_button.setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Cancel:
            return None
        return reply == QMessageBox.StandardButton.Yes

    def _build_link_target_path(
        self,
        source_path: Path,
        output_dir: Path,
        display_path: Path | None = None,
        group_in_named_dir: bool = False,
    ) -> tuple[Path, list[str]]:
        file_name = display_path.name if display_path is not None else source_path.name
        if not group_in_named_dir:
            return output_dir / file_name, []

        raw_dir_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        raw_dir_name = raw_dir_name or file_name
        dir_name, dir_notes = self._sanitize_link_dir_name(raw_dir_name)
        target_dir, collision_note = self._get_available_link_target_dir(output_dir, dir_name, file_name)
        if collision_note:
            dir_notes.append(f"链接目录名已自动避让冲突: {dir_name} -> {target_dir.name}")
        return target_dir / file_name, dir_notes

    def _get_link_dir_name_max(self) -> int:
        folder_name_max = int(manager.config.folder_name_max)
        if folder_name_max <= 0 or folder_name_max > 255:
            return 60
        return folder_name_max

    def _fit_link_dir_name_length(self, dir_name: str, suffix: str = "") -> str:
        max_length = self._get_link_dir_name_max()
        if len(dir_name) + len(suffix) <= max_length:
            return dir_name + suffix

        base_length = max(max_length - len(suffix), 1)
        trimmed = dir_name[:base_length].rstrip(". ").rstrip()
        if not trimmed:
            trimmed = DEFAULT_LINK_DIR_NAME[:base_length].rstrip(". ").rstrip() or DEFAULT_LINK_DIR_NAME[:1]
        return trimmed + suffix

    def _is_windows_reserved_dir_name(self, dir_name: str) -> bool:
        return dir_name.rstrip(". ").upper() in WINDOWS_RESERVED_DIR_NAMES

    def _sanitize_link_dir_name(self, raw_name: str) -> tuple[str, list[str]]:
        sanitized = LINK_DIR_INVALID_CHARS_RE.sub("_", raw_name)
        sanitized = re.sub(r"\s+", " ", sanitized)
        sanitized = re.sub(r"_+", "_", sanitized)
        sanitized = sanitized.strip().strip(". ").rstrip(". ").strip()
        notes: list[str] = []

        if not sanitized or not sanitized.strip("._- "):
            sanitized = DEFAULT_LINK_DIR_NAME
            notes.append(f"链接目录名清洗后为空，已回退为默认目录名: {raw_name} -> {sanitized}")
        elif sanitized != raw_name:
            notes.append(f"链接目录名已清洗: {raw_name} -> {sanitized}")

        if self._is_windows_reserved_dir_name(sanitized):
            original_name = sanitized
            sanitized = f"{sanitized}_"
            notes.append(f"链接目录名命中 Windows 保留名，已自动调整: {original_name} -> {sanitized}")

        fitted_name = self._fit_link_dir_name_length(sanitized)
        if fitted_name != sanitized:
            notes.append(f"链接目录名过长，已按最大长度截断: {sanitized} -> {fitted_name}")
        return fitted_name, notes

    def _can_reuse_link_target_dir(self, target_dir: Path, file_name: str) -> bool:
        if not target_dir.exists():
            return True
        if not target_dir.is_dir():
            return False

        target_file = target_dir / file_name
        if target_file.exists() or target_file.is_symlink():
            return True

        try:
            return not any(target_dir.iterdir())
        except Exception:
            return False

    def _get_available_link_target_dir(self, output_dir: Path, dir_name: str, file_name: str) -> tuple[Path, str]:
        candidate_dir = output_dir / dir_name
        if self._can_reuse_link_target_dir(candidate_dir, file_name):
            return candidate_dir, ""

        suffix_index = 2
        while True:
            candidate_name = self._fit_link_dir_name_length(dir_name, f"_{suffix_index}")
            candidate_dir = output_dir / candidate_name
            if self._can_reuse_link_target_dir(candidate_dir, file_name):
                return candidate_dir, candidate_name
            suffix_index += 1

    def _prepare_link_target_dir(self, target_path: Path, group_in_named_dir: bool) -> tuple[bool, str, bool]:
        if not group_in_named_dir:
            return True, "", False

        target_dir = target_path.parent
        if target_dir == target_path:
            return False, "目标目录无效", False
        if target_dir.exists():
            if target_dir.is_dir():
                return True, "", False
            return False, f"目标目录已存在同名文件: {target_dir}", False

        try:
            target_dir.mkdir(parents=True, exist_ok=False)
            return True, "", True
        except Exception as error:
            return False, self._normalize_delete_error_reason(str(error)), False

    def _cleanup_empty_link_target_dir(self, target_path: Path, created_dir: bool) -> None:
        if not created_dir:
            return

        target_dir = target_path.parent
        try:
            if target_dir.exists() and target_dir.is_dir() and not any(target_dir.iterdir()):
                target_dir.rmdir()
                signal_qt.show_log_text(f" ↩ 创建失败，已回滚空目录: {target_dir}")
        except Exception as error:
            signal_qt.show_log_text(
                f" ⚠ 回滚空目录失败: {target_dir}\n    原因: {self._normalize_delete_error_reason(str(error))}"
            )

    def _create_links_for_selected_files(
        self, link_type: Literal["soft", "hard"], group_in_named_dir: bool = False
    ) -> None:
        selected_entries = self._get_selected_entries()
        if selected_entries:
            link_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            link_targets = [(self.show_name or "", self.file_main_open_path)]

        if not link_targets:
            return

        link_name = "软链接" if link_type == "soft" else "硬链接"
        if group_in_named_dir:
            link_name = f"{link_name}（按文件名建目录）"
        should_record_success = self._confirm_record_link_paths(link_name)
        if should_record_success is None:
            return
        output_dir = self._select_link_output_dir(link_name)
        if output_dir is None:
            return

        signal_qt.show_log_text(f" 🔗 开始创建{link_name}")
        signal_qt.show_log_text(f" 📁 目标目录: {output_dir}")
        signal_qt.show_log_text(f" 📝 成功列表写入: {'是' if should_record_success else '否'}")

        success_count = 0
        skipped_count = 0
        success_paths_to_record: set[Path] = set()
        failure_details: list[tuple[Path, str]] = []
        for _show_name, file_path in link_targets:
            success, source_path, error_info = resolve_link_source_sync(file_path)
            if not success:
                failure_details.append((file_path, self._normalize_delete_error_reason(error_info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {file_path}\n    原因: {self._normalize_delete_error_reason(error_info)}"
                )
                continue

            target_path, target_notes = self._build_link_target_path(
                source_path, output_dir, file_path, group_in_named_dir
            )
            for note in target_notes:
                signal_qt.show_log_text(f" ℹ {note}")
            ok, dir_error, created_dir = self._prepare_link_target_dir(target_path, group_in_named_dir)
            if not ok:
                failure_details.append((target_path, dir_error))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {dir_error}"
                )
                continue

            if link_type == "soft":
                result, info = create_symlink_sync(source_path, target_path)
            else:
                result, info = create_hardlink_sync(source_path, target_path)

            record_success, success_record_path, record_info = resolve_success_record_source_sync(file_path)
            if not record_success:
                success_record_path = file_path
                record_info = (
                    f"解析成功列表源路径失败，已回退记录当前路径: {self._normalize_delete_error_reason(record_info)}"
                )

            if result:
                if "已存在同源" in info:
                    skipped_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ⏭ 已跳过{link_name}: {target_path}\n    原因: {info}")
                else:
                    success_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ✅ 已创建{link_name}: {target_path}\n    源文件: {source_path}")
            else:
                self._cleanup_empty_link_target_dir(target_path, created_dir)
                failure_details.append((target_path, self._normalize_delete_error_reason(info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {self._normalize_delete_error_reason(info)}"
                )

        if should_record_success and success_paths_to_record:
            # success_list 正被刮削协程并发 add，整段包锁
            with Flags.guarded():
                Flags.success_list.update(success_paths_to_record)
            executor.run(save_success_list())
            signal_qt.show_log_text(f" 💾 已写入成功列表 {len(success_paths_to_record)} 项")

        fail_count = len(failure_details)
        signal_qt.show_log_text(
            f" 🎉 创建{link_name}完成：成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个"
        )
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback(f"创建{link_name}", success_count, failure_details, skipped_count)
        elif skipped_count and not success_count:
            signal_qt.show_scrape_info(
                f"💡 所选文件的{link_name}已存在，已跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif skipped_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已创建{link_name}！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已创建 {success_count} 个{link_name}！{get_current_time()}")

    def _find_result_item_by_name(self, show_name: str) -> QTreeWidgetItem | None:
        for root_item in (self.item_succ, self.item_fail):
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                if child is not None and child.text(0) == show_name:
                    return child
        return None

    def _nfo_editor_field_values(self) -> tuple[str, ...]:
        ui = self.Ui
        return (
            ui.lineEdit_nfo_number.text(),
            ui.lineEdit_nfo_actor.text(),
            ui.lineEdit_nfo_year.text(),
            ui.lineEdit_nfo_title.text(),
            ui.lineEdit_nfo_originaltitle.text(),
            ui.textEdit_nfo_outline.toPlainText(),
            ui.textEdit_nfo_originalplot.toPlainText(),
            ui.textEdit_nfo_tag.toPlainText(),
            ui.lineEdit_nfo_release.text(),
            ui.lineEdit_nfo_runtime.text(),
            ui.lineEdit_nfo_score.text(),
            ui.lineEdit_nfo_wanted.text(),
            ui.lineEdit_nfo_director.text(),
            ui.lineEdit_nfo_series.text(),
            ui.lineEdit_nfo_studio.text(),
            ui.lineEdit_nfo_publisher.text(),
            ui.lineEdit_nfo_poster.text(),
            ui.lineEdit_nfo_cover.text(),
            ui.lineEdit_nfo_trailer.text(),
            ui.lineEdit_nfo_website.text(),
            ui.comboBox_nfo.currentText(),
        )

    def _nfo_editor_is_dirty(self) -> bool:
        if self.Ui.widget_nfo.isHidden() or self._nfo_editor_snapshot is None:
            return False
        return self._nfo_editor_field_values() != self._nfo_editor_snapshot

    def _confirm_nfo_editor_leave(self) -> bool:
        """离开当前编辑对象前确认未保存改动。False 表示取消本次离开。"""
        if not self._nfo_editor_is_dirty():
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "编辑 NFO", "当前 NFO 有未保存的修改，是否先保存？")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        )
        save_btn = box.button(QMessageBox.StandardButton.Save)
        assert save_btn is not None
        save_btn.setText("保存")
        discard_btn = box.button(QMessageBox.StandardButton.Discard)
        assert discard_btn is not None
        discard_btn.setText("丢弃")
        cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
        assert cancel_btn is not None
        cancel_btn.setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            self.save_nfo_info()
        return True

    def _close_nfo_editor(self) -> None:
        if not self._confirm_nfo_editor_leave():
            return
        self.Ui.widget_nfo.hide()
        self._nfo_editor_snapshot = None

    def _on_page_change_nfo_panel(self, index: int) -> None:
        """议题 #177: 切页时暂隐编辑 NFO 面板(非关闭, 表单与结果树选中态保留),
        切回主界面自动恢复; 有未保存改动时取消切页以留在主界面继续编辑。"""
        nfo = self.Ui.widget_nfo
        if index != 0:
            if not nfo.isHidden():
                if self._nfo_editor_is_dirty() and not self._confirm_nfo_editor_leave():
                    stacked = self.Ui.stackedWidget
                    stacked.blockSignals(True)
                    stacked.setCurrentIndex(0)
                    stacked.blockSignals(False)
                    return
                nfo.hide()
                self._nfo_page_hiding = True
        elif getattr(self, "_nfo_page_hiding", False):
            nfo.show()
            self._sync_nfo_overlay_geometry()
            self._nfo_page_hiding = False

    def _clear_main_info_panel(self, *, force: bool = False) -> None:
        if not force and not self.Ui.widget_nfo.isHidden() and not self._confirm_nfo_editor_leave():
            return
        self.set_main_info(None)
        self.file_main_open_path = Path()
        self.show_name = None
        self.show_data = None
        if not self.Ui.widget_nfo.isHidden():
            self.Ui.widget_nfo.hide()
        self._nfo_editor_snapshot = None

    def _remove_deleted_result_items(self, show_names: list[str]) -> None:
        if not show_names:
            return

        current_show_name = self.show_name
        for show_name in show_names:
            self.json_array.pop(show_name, None)

        for show_name in show_names:
            item = self._find_result_item_by_name(show_name)
            if item is None:
                continue
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)

        self.Ui.treeWidget_number.clearSelection()
        if current_show_name in show_names:
            self._clear_main_info_panel(force=True)
