"""演员工具页的异步任务编排（按钮槽 → 后台跑批 → 结果对话框 / 自动修复 / NFO 回填）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。
注意：`_on_actor_db_finished` 与 `_ACTOR_DB_IDLE_TEXT_MAP` **刻意留在
`main_window.py`**——`tests/test_actor_db_button_consistency.py` 直接在这份源码里
做正则断言，不能搬走。"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from mdcx.config.resources import resources
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt


class ActorDbMixin:
    def pushButton_actor_db_translate_clicked(self):
        from .tool_handlers import pushButton_actor_db_translate_clicked

        pushButton_actor_db_translate_clicked(self)

    def pushButton_actor_db_link_clicked(self):
        from .tool_handlers import pushButton_actor_db_link_clicked

        pushButton_actor_db_link_clicked(self)

    def pushButton_actor_db_sync_aliases_clicked(self):
        from .tool_handlers import pushButton_actor_db_sync_aliases_clicked

        pushButton_actor_db_sync_aliases_clicked(self)

    def pushButton_actor_db_fill_Minnano_clicked(self):
        self._run_actor_db_tool("fill_minnano")

    def pushButton_actor_db_fill_zh_javdb_clicked(self):
        offset = self.Ui.spinBox_actor_db_sync_offset.value()
        limit = self.Ui.spinBox_actor_db_sync_limit.value()
        slice_hint = f"，起始行={offset}，限量={limit if limit > 0 else '不限'}"
        signal_qt.show_log_text(
            "开始扫描 actor_database.xlsx：从 JavDB 补全中文名/繁体名（仅处理「中文名==日文原名」的行）"
            + slice_hint
            + ")..."
        )
        self._run_actor_db_tool("fill_zh_javdb", offset=offset, limit=limit)

    def pushButton_actor_db_open_clicked(self):
        from .tool_handlers import pushButton_actor_db_open_clicked

        pushButton_actor_db_open_clicked(self)

    def pushButton_actor_db_clean_male_clicked(self):
        from .tool_handlers import pushButton_actor_db_clean_male_clicked

        pushButton_actor_db_clean_male_clicked(self)

    def pushButton_actor_db_verify_tmdbid_clicked(self):
        from .tool_handlers import pushButton_actor_db_verify_tmdbid_clicked

        pushButton_actor_db_verify_tmdbid_clicked(self)

    def pushButton_actor_db_check_clicked(self):
        from .tool_handlers import pushButton_actor_db_check_clicked

        pushButton_actor_db_check_clicked(self)

    def pushButton_actor_db_pick_nfo_dir_clicked(self):
        from .tool_handlers import pushButton_actor_db_pick_nfo_dir_clicked

        pushButton_actor_db_pick_nfo_dir_clicked(self)

    def pushButton_actor_db_update_nfo_tmdbid_clicked(self):
        from .tool_handlers import pushButton_actor_db_update_nfo_tmdbid_clicked

        pushButton_actor_db_update_nfo_tmdbid_clicked(self)

    def _run_actor_db_async(
        self,
        btn_attr: str,
        busy_text: str,
        log_prefix: str,
        coro_factory,
    ) -> None:
        """演员库工具入口的通用模板：按钮防重入 + executor.submit + 完成信号。

        Args:
            btn_attr: Ui.pushButton_xxx 与 self.pushButton_xxx 共用属性名（无 'pushButton_' 前缀）。
            busy_text: 按钮按下时的临时文案。
            log_prefix: 异常日志前缀（如 "演员库维护"、"剔除男演员"、"校验 tmdbid"）。
            coro_factory: 无参 callable，返回协程。协程内异常会被捕获并 show_log。
        """
        from mdcx.utils.qt_thread import run_in_background

        run_in_background(
            button=getattr(self.Ui, f"pushButton_{btn_attr}"),
            coro_factory=coro_factory,
            busy_signal=getattr(self, f"pushButton_{btn_attr}"),
            busy_text=busy_text,
            finished_signal=self.actor_db_finished,
            finished_arg=btn_attr,
            log_prefix=log_prefix,
        )
        self._actor_db_running.add(btn_attr)

    def _run_actor_db_tool(self, mode: str, **kwargs) -> None:
        """运行演员库维护工具（翻译/链接/别名/minnano 补全），统一走通用模板。"""
        from mdcx.tools.actor_db_tool import run_actor_db_xlsx

        button_map = {
            "translate": "actor_db_translate",
            "link": "actor_db_link",
            "sync_aliases": "actor_db_sync_aliases",
            "fill_minnano": "actor_db_fill_minnano",
            "fill_zh_javdb": "actor_db_fill_zh_javdb",
        }
        busy_text = {
            "translate": "运行中...",
            "link": "运行中...",
            "sync_aliases": "运行中...",
            "fill_minnano": "运行中...",
            "fill_zh_javdb": "运行中...",
        }[mode]
        self._run_actor_db_async(
            button_map[mode],
            busy_text,
            "演员库维护",
            lambda: run_actor_db_xlsx(mode=mode, **kwargs),
        )

    def _run_actor_db_clean_male(self) -> None:
        """运行「剔除男演员」存量清洗（按 tmdbid 校验 TMDB gender，删除男优）。"""
        from mdcx.tools.actor_db_tool import clean_male_actors

        self._run_actor_db_async("actor_db_clean_male", "清洗中...", "剔除男演员", clean_male_actors)

    def _run_actor_db_verify_tmdbid(self) -> None:
        """运行「校验TMDB ID有效性」存量清洗（404 失效 id 清除回无 id 状态）。"""
        from mdcx.tools.actor_db_tool import verify_tmdb_ids

        self._run_actor_db_async("actor_db_verify_tmdbid", "校验中...", "校验 tmdbid", verify_tmdb_ids)

    def _run_actor_db_check(self) -> None:
        """运行「检查用户库」：对运行库执行格式/结构/数据异常检查，弹窗报告+自动修复安全项。"""
        from mdcx.tools.actor_db_tool import _check_actor_db_issues

        db_path = Path(resources.u("actor_database.xlsx"))
        if not db_path.exists():
            signal_qt.show_log_text("🔴 actor_database.xlsx 不存在，请先刮削或执行一次演员库维护生成数据库")
            return

        btn = self.Ui.pushButton_actor_db_check
        if not btn.isEnabled():
            return

        btn.setEnabled(False)
        self.pushButton_actor_db_check.emit("检查中...")
        self._actor_db_running.add("actor_db_check")

        try:
            issues = _check_actor_db_issues(db_path)
        except Exception as e:
            signal_qt.show_log_text(f"🔴 检查用户库异常: {e}")
            import traceback as tb

            signal_qt.show_log_text(tb.format_exc())
            self._on_actor_db_finished("actor_db_check")
            return

        try:
            self._show_actor_db_check_dialog(issues, db_path)
        finally:
            # 弹窗关闭后恢复按钮
            self._on_actor_db_finished("actor_db_check")

    def _show_actor_db_check_dialog(self, issues: dict, db_path: Path) -> None:
        """弹窗展示检查结果：无问题→绿色提示；有问题→红色列表+「自动修复」按钮。"""

        errors = issues["errors"]
        warnings = issues["warnings"]
        total = len(errors) + len(warnings)

        if total == 0:
            QMessageBox.information(self, "检查用户库", "✅ 未发现任何问题。\n\n库结构、格式、数据完整性均正常。")
            signal_qt.show_log_text("✅ 检查用户库完成：未发现问题")
            return

        # 分类统计
        from collections import Counter

        cat_names = {
            "jp_empty": "jp 为空",
            "jp_dup": "jp 重复",
            "kw_format": "keyword 格式",
            "kw_dup": "keyword 重复",
            "birth_format": "出生日期格式",
            "birth_range": "出生日期年份异常",
            "career_no_year": "生涯无年份",
            "tmdb_no_id": "tmdbid 空缺",
            "tmdb_mismatch": "tmdb id 与 url 不匹配",
            "tmdb_dup": "tmdbid 重复",
            "orphan_link": "孤儿链接",
            "name_empty": "中/文名空缺",
            "bio_jp": "简介日文残留",
            "bio_unstruct": "简介非结构化",
        }
        error_cats = Counter(cat for _, _, cat in errors)
        warning_cats = Counter(cat for _, _, cat in warnings)

        lines = [f"检查发现 {len(errors)} 个错误 + {len(warnings)} 个警告：\n"]
        lines.append("<b style='color: #c62828;'>错误（需立即处理）：</b>")
        for cat, count in sorted(error_cats.items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat_names.get(cat, cat)}: {count} 项")
        for row, msg, _cat in errors[:20]:
            lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")
        if len(errors) > 20:
            lines.append(f"&nbsp;&nbsp;... 还有 {len(errors) - 20} 条未显示")
        lines.append("")
        if warnings:
            lines.append("<b style='color: #ef6c00;'>警告（建议处理）：</b>")
            for cat, count in sorted(warning_cats.items(), key=lambda x: -x[1]):
                lines.append(f"  • {cat_names.get(cat, cat)}: {count} 项")
            for row, msg, _cat in warnings[:10]:
                lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")
            if len(warnings) > 10:
                lines.append(f"&nbsp;&nbsp;... 还有 {len(warnings) - 10} 条未显示")

        msg_html = "<br>".join(lines)

        # 区分可自动修/需人工
        auto_fixable = {"jp_empty", "jp_dup", "kw_format", "kw_dup", "birth_range", "career_no_year", "tmdb_mismatch"}
        needs_manual = {"tmdb_no_id", "tmdb_dup", "tmdb_dup_url"}
        auto_count = sum(c for cat, c in error_cats.items() if cat in auto_fixable)
        manual_count = sum(c for cat, c in error_cats.items() if cat in needs_manual)

        if manual_count > 0:
            lines.append("")
            lines.append(
                f"<b style='color: #ef6c00;'>{manual_count} 项 tmdb 相关需人工处理</b>（打开数据库后手动修复）"
            )
            for row, msg, cat in errors:
                if cat in needs_manual:
                    lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")

            lines.append("")
            lines.append("<b>手动修复步骤：</b>")
            lines.append("1. 点击「打开数据库」按钮，在 Excel/WPS/LibreOffice 中打开 actor_database.xlsx")
            lines.append("2. 根据告警信息定位到错误行")
            lines.append("3. 处理 tdb 相关错误：")
            lines.append("   • tmdbid 空缺：删除该行的 tmdb url 链接")
            lines.append("   • tmdbid 重复：核对 TMDB 网站后修正为正确的 id 或删除重复行")
            lines.append("   • id 与 url 不匹配：以 tmdbid 为准，重新生成 url 或改 tmdbid")
            lines.append("4. 保存并重新打开本工具检查")

            msg_html = "<br>".join(lines)

        if auto_count > 0:
            box = QMessageBox(self)
            box.setWindowTitle("检查用户库 — 发现问题")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(msg_html)
            fix_btn = box.addButton(f"自动修复 {auto_count} 项", QMessageBox.ButtonRole.AcceptRole)
            open_btn = box.addButton("打开数据库查看", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is fix_btn:
                self._do_actor_db_auto_fix(db_path)
            elif clicked is open_btn:
                from mdcx.utils.file import open_file_thread

                try:
                    open_file_thread(db_path, False)
                except Exception as e:
                    signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")
        else:
            box = QMessageBox(self)
            box.setWindowTitle("检查用户库 — 发现问题（无自动修复项）")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(msg_html)
            open_btn = box.addButton("打开数据库查看", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if box.clickedButton() is open_btn:
                from mdcx.utils.file import open_file_thread

                try:
                    open_file_thread(db_path, False)
                except Exception as e:
                    signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")

    def _do_actor_db_auto_fix(self, db_path: Path) -> None:
        """执行自动修复并反馈结果。"""

        from mdcx.tools.actor_db_tool import auto_fix_actor_db

        try:
            result = auto_fix_actor_db(db_path)
            fixed = result["fixed"]
            needs_manual = result["needs_manual"]

            lines = [f"自动修复完成：{sum(fixed.values())} 项已修复"]
            save_error = result.get("save_error")
            if save_error:
                lines.insert(0, f"<font color='red'>⚠️ 修复结果保存失败：{save_error}</font>")
                lines.insert(1, "<font color='red'>请关闭 Excel 或其他占用该文件的程序后重试！</font>")
            if fixed:
                for cat, count in fixed.items():
                    cat_names = {
                        "jp_empty": "jp 空行删除",
                        "jp_dup": "jp 重复合并",
                        "kw_format": "keyword 格式规范化",
                        "birth_range": "出生日期越界清空",
                        "career_no_year": "生涯无年份删除",
                        "tmdb_mismatch": "tmdb url 重置",
                    }
                    lines.append(f"  • {cat_names.get(cat, cat)}: {count}")
            if needs_manual:
                lines.append("")
                lines.append(f"{len(needs_manual)} 项需人工处理：")
                for row, msg, _cat in needs_manual[:10]:
                    lines.append(f"  - 行{row}: {msg}")
                if len(needs_manual) > 10:
                    lines.append(f"  ... 还有 {len(needs_manual) - 10} 项")
        except Exception as e:
            lines = [f"自动修复失败: {e}"]

        box = QMessageBox(self)
        box.setWindowTitle("自动修复完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("<br>".join(lines))
        open_btn = box.addButton("打开数据库验证", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            from mdcx.utils.file import open_file_thread

            try:
                open_file_thread(db_path, False)
            except Exception as e:
                signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")

    def _run_actor_db_update_nfo(self) -> None:
        """运行「更新 nfo tmdbid」（用本地库新 id 覆盖 nfo 旧 id，无 id 的补上）。"""
        from pathlib import Path

        from mdcx.tools.actor_db_tool import update_nfo_tmdb_ids

        dir_text = self.Ui.lineEdit_actor_db_nfo_dir.text().strip()
        if not dir_text:
            signal_qt.show_log_text("🔴 请先选择 nfo 目录")
            return
        dir_path = Path(dir_text)
        if not dir_path.is_dir():
            signal_qt.show_log_text(f"🔴 nfo 目录不存在: {dir_text}")
            return

        self._run_actor_db_async(
            "actor_db_update_nfo_tmdbid",
            "更新中...",
            "更新 nfo",
            lambda: update_nfo_tmdb_ids(dir_path),
        )

    def pushButton_actor_db_stop_clicked(self) -> None:
        """停止当前演员库维护任务（独立于主界面刮削停止）。

        置位 signal_qt.stop 与 Flags.stop_requested，各维护工具的
        _is_stop_requested() 会在滑动窗口每轮响应并保存已处理部分。
        """
        Flags.stop_requested = True
        signal_qt.stop = True
        signal_qt.show_log_text("⛔️ 已请求停止演员库维护任务，正在保存已处理部分...")
