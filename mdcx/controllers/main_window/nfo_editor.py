"""主界面 NFO 编辑器（打开 NFO、字段回填、保存、离开确认、面板显隐）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import traceback

from mdcx.config.enums import NfoInclude
from mdcx.config.manager import manager
from mdcx.core.nfo import write_nfo
from mdcx.signals import signal_qt
from mdcx.utils import (
    executor,
    get_current_time,
)


class NfoEditorMixin:
    # region 主界面编辑nfo
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
            self.Ui.lineEdit_nfo_number.setText(json_data.number)
            self.Ui.lineEdit_nfo_actor.setText(actor)
            self.Ui.lineEdit_nfo_year.setText(json_data.year)
            self.Ui.lineEdit_nfo_title.setText(json_data.title)
            self.Ui.lineEdit_nfo_originaltitle.setText(json_data.originaltitle)
            self.Ui.textEdit_nfo_outline.setPlainText(json_data.outline)
            self.Ui.textEdit_nfo_originalplot.setPlainText(json_data.originalplot)
            self.Ui.textEdit_nfo_tag.setPlainText(json_data.tag)
            self.Ui.lineEdit_nfo_release.setText(json_data.release)
            self.Ui.lineEdit_nfo_runtime.setText(json_data.runtime)
            self.Ui.lineEdit_nfo_score.setText(json_data.score)
            self.Ui.lineEdit_nfo_wanted.setText(json_data.wanted)
            self.Ui.lineEdit_nfo_director.setText(json_data.director)
            self.Ui.lineEdit_nfo_series.setText(json_data.series)
            self.Ui.lineEdit_nfo_studio.setText(json_data.studio)
            self.Ui.lineEdit_nfo_publisher.setText(json_data.publisher)
            self.Ui.lineEdit_nfo_poster.setText(json_data.poster)
            self.Ui.lineEdit_nfo_cover.setText(json_data.thumb)
            self.Ui.lineEdit_nfo_trailer.setText(json_data.trailer)
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
            json_data.title = self.Ui.lineEdit_nfo_title.text()
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
            if executor.run(write_nfo(file_info, json_data, nfo_path, nfo_folder, update=True)):
                self.Ui.label_save_tips.setText(f"已保存! {get_current_time()}")
                self.set_main_info(show_data)
                self._nfo_editor_snapshot = self._nfo_editor_field_values()
            else:
                self.Ui.label_save_tips.setText(f"保存失败! {get_current_time()}")
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())
