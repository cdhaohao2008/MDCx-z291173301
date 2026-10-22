"""主界面 NFO 编辑器（打开 NFO、字段回填、保存、离开确认、面板显隐）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import traceback

from mdcx.config.enums import NfoInclude
from mdcx.config.manager import manager
from mdcx.core.nfo import build_nfo_title, write_nfo
from mdcx.signals import signal_qt
from mdcx.utils import (
    executor,
    get_current_time,
)


class NfoEditorMixin:
    # region 主界面编辑nfo
    @staticmethod
    def _set_field_text(line_edit, text: str) -> None:
        """回填字段并把光标推到最左，使超长文本从左向右展示。

        QLineEdit.setText() 会把光标放在文本末尾，控件宽度不够时视图会滚到
        最右侧（只看到标题/原标题的尾巴）。显示改光标为 0 后视图回到开头，
        与「站点优先级」弹窗里的 _set_site_summary 同一套做法。
        """
        line_edit.setText(text or "")
        line_edit.setCursorPosition(0)

    @staticmethod
    def _nfo_title_text(file_info, json_data) -> str:
        """标题栏展示的文本：所见即所得，等于最终写入 NFO 的 <title>。

        NFO 里已经有标题时（读取模式从 NFO 读回来的原始标题 / 上次保存写入的标题）
        直接展示它，保证「看到什么就保存什么」；还没有 NFO 标题时展示当前标题数据。
        """
        existing = str(getattr(json_data, "nfo_title", "") or "")
        if existing:
            return existing
        return str(json_data.title or "")

    @staticmethod
    def _nfo_title_to_save(file_info, json_data, shown_title: str) -> str:
        """保存时写入 NFO 的标题文本。

        NFO 里已有标题时原样回写（所见即所得，不再套命名模板，避免
        {{release}} / {{number}} 等字段重复叠加）；还没有 NFO 标题时才按命名模板
        渲染一次，保留模板里的前缀字段。
        """
        if str(getattr(json_data, "nfo_title", "") or ""):
            return shown_title
        return build_nfo_title(file_info, json_data, title=shown_title)

    def _show_nfo_info(self):
        try:
            if not self.show_name:
                return
            show_data = self.json_array[self.show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            self.now_show_name = show_data.show_name
            actor = json_data.actor
            if json_data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = json_data.all_actor
            self.Ui.label_nfo.setText(str(file_info.file_path))
            self._set_field_text(self.Ui.lineEdit_nfo_number, json_data.number)
            self._set_field_text(self.Ui.lineEdit_nfo_actor, actor)
            self._set_field_text(self.Ui.lineEdit_nfo_year, json_data.year)
            self._set_field_text(self.Ui.lineEdit_nfo_title, self._nfo_title_text(file_info, json_data))
            self._set_field_text(self.Ui.lineEdit_nfo_originaltitle, json_data.originaltitle)
            self.Ui.textEdit_nfo_outline.setPlainText(json_data.outline)
            self.Ui.textEdit_nfo_originalplot.setPlainText(json_data.originalplot)
            self.Ui.textEdit_nfo_tag.setPlainText(json_data.tag)
            self._set_field_text(self.Ui.lineEdit_nfo_release, json_data.release)
            self._set_field_text(self.Ui.lineEdit_nfo_runtime, json_data.runtime)
            self._set_field_text(self.Ui.lineEdit_nfo_score, json_data.score)
            self._set_field_text(self.Ui.lineEdit_nfo_wanted, json_data.wanted)
            self._set_field_text(self.Ui.lineEdit_nfo_director, json_data.director)
            self._set_field_text(self.Ui.lineEdit_nfo_series, json_data.series)
            self._set_field_text(self.Ui.lineEdit_nfo_studio, json_data.studio)
            self._set_field_text(self.Ui.lineEdit_nfo_publisher, json_data.publisher)
            self._set_field_text(self.Ui.lineEdit_nfo_poster, json_data.poster)
            self._set_field_text(self.Ui.lineEdit_nfo_cover, json_data.thumb)
            self._set_field_text(self.Ui.lineEdit_nfo_trailer, json_data.trailer)
            all_items = [self.Ui.comboBox_nfo.itemText(i) for i in range(self.Ui.comboBox_nfo.count())]
            self.Ui.comboBox_nfo.setCurrentIndex(all_items.index(json_data.country))
            self._nfo_editor_snapshot = self._nfo_editor_field_values()
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    def save_nfo_info(self):
        try:
            if self.now_show_name is None:
                return
            show_data = self.json_array[self.now_show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            nfo_path = file_info.file_path.with_suffix(".nfo")
            nfo_folder = nfo_path.parent
            json_data.number = self.Ui.lineEdit_nfo_number.text()
            if NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                json_data.all_actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.year = self.Ui.lineEdit_nfo_year.text()
            json_data.originaltitle = self.Ui.lineEdit_nfo_originaltitle.text()
            json_data.outline = self.Ui.textEdit_nfo_outline.toPlainText()
            json_data.originalplot = self.Ui.textEdit_nfo_originalplot.toPlainText()
            json_data.tag = self.Ui.textEdit_nfo_tag.toPlainText()
            json_data.release = self.Ui.lineEdit_nfo_release.text()
            json_data.runtime = self.Ui.lineEdit_nfo_runtime.text()
            json_data.score = self.Ui.lineEdit_nfo_score.text()
            json_data.wanted = self.Ui.lineEdit_nfo_wanted.text()
            json_data.director = self.Ui.lineEdit_nfo_director.text()
            json_data.series = self.Ui.lineEdit_nfo_series.text()
            json_data.studio = self.Ui.lineEdit_nfo_studio.text()
            json_data.publisher = self.Ui.lineEdit_nfo_publisher.text()
            json_data.poster = self.Ui.lineEdit_nfo_poster.text()
            json_data.thumb = self.Ui.lineEdit_nfo_cover.text()
            json_data.trailer = self.Ui.lineEdit_nfo_trailer.text()
            # 标题栏所见即所得：NFO 里已有标题时原样回写（不再套命名模板），避免
            # {{release}} / {{number}} 等字段被重复叠加；还没有 NFO 标题时才按命名
            # 模板渲染一次（保持原有行为，不会丢掉模板里的前缀字段）。
            shown_title = self.Ui.lineEdit_nfo_title.text()
            nfo_title = self._nfo_title_to_save(file_info, json_data, shown_title)
            if executor.run(
                write_nfo(
                    file_info,
                    json_data,
                    nfo_path,
                    nfo_folder,
                    update=True,
                    title_override=nfo_title,
                )
            ):
                json_data.nfo_title = nfo_title
                self.Ui.label_save_tips.setText(f"已保存! {get_current_time()}")
                self.set_main_info(show_data)
                self._nfo_editor_snapshot = self._nfo_editor_field_values()
            else:
                self.Ui.label_save_tips.setText(f"保存失败! {get_current_time()}")
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())
