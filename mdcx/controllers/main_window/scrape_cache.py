"""刮削缓存表格（列宽同步、筛选、导出、重置、清空）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import time
from pathlib import Path

from PyQt6.QtCore import (
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
)

from mdcx.config.resources import resources
from mdcx.core.scrape_cache import ScrapeStateCache
from mdcx.signals import signal_qt


class ScrapeCacheMixin:
    # 检查 fc2ppvdb cookie
    # region 刮削缓存管理
    # 失败列表加权列宽：文件名/番号/最后错误/时间按 4:2:6:3 分摊视口剩余宽，
    # 失败次数按内容固定。Qt6 QHeaderView 无 setStretchFactor，Stretch 只能均分，
    # 故用 Interactive + 手动按权分配，保证番号约旧 2 倍、时间约旧 3 倍且无横向滚动条。
    _SCRAPE_CACHE_COL_WEIGHTS = {0: 4, 1: 2, 3: 6, 4: 3}

    def _apply_scrape_cache_header_modes(self) -> None:
        """议题 #179: 失败列表列宽策略。

        旧实现列宽固定 5×130=650（Interactive），表格宽随窗口伸缩而列不动——
        窄窗（用户截图 1032 视口 641）出水平滚动条，宽窗/最大化右侧大片空白。
        改为文件名/番号/最后错误/时间按 4:2:6:3 加权分摊视口宽、
        失败次数按内容收缩，列总宽恒等于视口宽，不出横向滚动条。
        番号约旧 2 倍（多出部分由文件名让出），时间约旧 3 倍（多出部分由最后错误让出）。
        """
        tw = self.Ui.tableWidget_scrape_cache_failed
        tw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = tw.horizontalHeader()
        header.setMinimumSectionSize(10)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._scrape_cache_layouting = False
        try:
            tw.installEventFilter(self)
            tw.viewport().installEventFilter(self)
        except Exception:
            pass
        QTimer.singleShot(0, self._layout_scrape_cache_columns)

    def _layout_scrape_cache_columns(self) -> None:
        """按权重重分布失败列表列宽，列总宽恒等于视口宽。"""
        tw = getattr(getattr(self, "Ui", None), "tableWidget_scrape_cache_failed", None)
        if tw is None:
            return
        if getattr(self, "_scrape_cache_layouting", False):
            return
        vp = tw.viewport().width()
        if vp <= 0:
            return
        self._scrape_cache_layouting = True
        try:
            tw.resizeColumnToContents(2)
            fixed = tw.columnWidth(2)
            # 预留 2px 网格线/边框：总宽接近视口时滚动 maximum 仍可能为 1，故按 vp-2 预算分配。
            budget = max(vp - 2, 0)
            remaining = budget - fixed
            if remaining < 0:
                remaining = 0
            weights = self._SCRAPE_CACHE_COL_WEIGHTS
            total = sum(weights.values())
            w0 = remaining * weights[0] // total
            w1 = remaining * weights[1] // total
            w3 = remaining * weights[3] // total
            w4 = remaining - w0 - w1 - w3
            tw.setColumnWidth(0, max(w0, 10))
            tw.setColumnWidth(1, max(w1, 10))
            tw.setColumnWidth(3, max(w3, 10))
            tw.setColumnWidth(4, max(w4, 10))
            # 表格网格线/边框会占 1~2px：实测总宽恰等于视口时滚动 maximum 仍为 1，
            # 此处按实际列宽回扣溢出，保证 maximum == 0（预算 vp-2，仍满足铺满断言 vp-2）。
            overflow = sum(tw.columnWidth(c) for c in range(5)) - max(vp - 2, 0)
            if overflow > 0:
                tw.setColumnWidth(3, max(10, tw.columnWidth(3) - overflow))
        finally:
            self._scrape_cache_layouting = False

    def _open_scrape_cache(self) -> ScrapeStateCache | None:
        cache = ScrapeStateCache(resources.u("scrape_state.db"))
        if not cache.open():
            signal_qt.show_log_text(" 🔴 刮削缓存数据库不可用")
            return None
        return cache

    def pushButton_scrape_cache_refresh_clicked(self) -> None:
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            stats = cache.stats()
            failed = cache.list_failed_detail()
        finally:
            cache.close()
        self._update_scrape_cache_ui(stats, failed)
        signal_qt.show_log_text(
            f" 刮削缓存已刷新：完成 {stats['done']} / 失败 {stats['failed']} / 总计 {stats['total']}"
        )

    def _update_scrape_cache_ui(self, stats: dict, failed: list) -> None:
        self.Ui.label_scrape_cache_done.setText(f"已完成：{stats['done']}")
        self.Ui.label_scrape_cache_failed.setText(f"失败：{stats['failed']}")
        self.Ui.label_scrape_cache_exhausted.setText(f"超限失败：{stats['failed_exhausted']}")
        self.Ui.label_scrape_cache_total.setText(f"总计：{stats['total']}")
        self.Ui.label_scrape_cache_dbpath.setText(f"数据库：{stats['db_path']}")
        self.Ui.label_scrape_cache_dbsize.setText(f"大小：{stats['db_size_kb']} KB")
        tw = self.Ui.tableWidget_scrape_cache_failed
        tw.setRowCount(len(failed))
        for i, f in enumerate(failed):
            name_item = QTableWidgetItem(Path(f.file_path).name)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, f.file_path)
            tw.setItem(i, 0, name_item)
            tw.setItem(i, 1, QTableWidgetItem(f.number))
            tw.setItem(i, 2, QTableWidgetItem(str(f.fail_count)))
            err = f.error or ""
            tw.setItem(i, 3, QTableWidgetItem(err[:100] + ("…" if len(err) > 100 else "")))
            tw.setItem(
                i,
                4,
                QTableWidgetItem(
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.scraped_at)) if f.scraped_at else ""
                ),
            )
        # 议题 #179: 原 resizeColumnsToContents()+setColumnWidth(3,260) 与列宽伸缩策略冲突
        # （长文本会把列总宽撑出视口，实测 sum=1462 必出横向滚动条），列宽按 4:2:6:3 加权分配。
        self._layout_scrape_cache_columns()

    def pushButton_scrape_cache_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出失败列表", "scrape_failed.csv", "CSV (*.csv)")
        if not path:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            failed = cache.list_failed_detail(limit=100000)
        finally:
            cache.close()
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(["文件路径", "番号", "失败次数", "最后错误", "时间"])
            for f in failed:
                w.writerow(
                    [
                        f.file_path,
                        f.number,
                        f.fail_count,
                        f.error,
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.scraped_at)) if f.scraped_at else "",
                    ]
                )
        signal_qt.show_log_text(f" 已导出 {len(failed)} 条失败记录到 {path}")

    def pushButton_scrape_cache_reset_clicked(self) -> None:
        tw = self.Ui.tableWidget_scrape_cache_failed
        rows = sorted({idx.row() for idx in tw.selectedIndexes()})
        if not rows:
            signal_qt.show_log_text(" 请先在表格中选中要重置的记录")
            return
        paths = []
        for r in rows:
            item = tw.item(r, 0)
            if item is not None:
                p = item.data(Qt.ItemDataRole.UserRole + 1)
                if p:
                    paths.append(p)
        if not paths:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            for p in paths:
                cache.delete_state(Path(p))
        finally:
            cache.close()
        signal_qt.show_log_text(f" 已重置 {len(paths)} 条记录（下次刮削将重新处理）")
        self.pushButton_scrape_cache_refresh_clicked()

    def pushButton_scrape_cache_clear_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认清空缓存",
            "将清空全部刮削缓存状态，下次刮削将重新处理所有文件。\n已生成的 NFO 不会被删除。确认清空？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            cache.clear()
        finally:
            cache.close()
        signal_qt.show_log_text(" 刮削缓存已全部清空")
        self.pushButton_scrape_cache_refresh_clicked()
