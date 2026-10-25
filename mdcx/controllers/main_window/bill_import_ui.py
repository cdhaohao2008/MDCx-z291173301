"""设置-高级-高级功能：「导入账单」按钮（微信 / 支付宝 xlsx 账单 → 赞助窗口榜单）。

需求（用户 2026-10-26）：

1. 按钮挂在「隐藏信息管理」复选框**右侧**，左缘与「显示字段内容信息」严格上下对齐
   （即两者 x 相等），且「显示字段内容信息」自身位置不动。
2. 点击后选 xlsx 账单，导入完成后赞助窗口的新人榜 / 土豪榜立刻能看到数据。
3. 入口**绑定本机 CPU 编号**：只有作者这台电脑能看到按钮、能使用功能。

做法上刻意**不把按钮塞进 ``horizontalLayout_nav_hide``**：那一行由
``_sync_advanced_page_align`` 用「钉死前导项宽度」把「隐藏信息管理」推到
``checkBox_show_from_log`` 那条竖线，行内再多一个控件就得跟着重算间隔项，而且
间隔项的 sizeHint 会撑进网格列宽（本文件上方 dock 行那段注释踩过）。这里改成与
``comboBox_actor_type`` 同一套路子：按钮是 ``gridLayoutWidget_20`` 的**绝对定位直接
子项**，不进任何布局，几何由 ``_sync_advanced_page_bill_button`` 每遍按
「显示字段内容信息」的实测 x 与「隐藏信息管理」的实测 y 钉死——既保证严格对齐，
也不会反过来推动任何既有控件（「显示字段内容信息」位置保持不变是硬要求）。

CPU 探测在后台线程里跑（PowerShell 冷启动约 1 秒），算完由 QTimer 把按钮显出来：
按钮先建好但 ``hide()``，未绑定的机器上它从头到尾都不会出现。
"""

import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
)

from mdcx.signals import signal_qt
from mdcx.ui_theme import get_theme_tokens
from mdcx.utils import machine_binding

_BILL_BUTTON_TEXT = "导入账单"
_BILL_BUTTON_HEIGHT = 30  # 与「隐藏信息管理」复选框同高
_BILL_BUTTON_MIN_WIDTH = 92
_BILL_BUTTON_MAX_WIDTH = 128
_BILL_BIND_POLL_MS = 150


def _bill_button_qss(dark: bool) -> str:
    """「导入账单」按钮样式：贴合设置页的紧凑方角按钮（不复用那套 8px 描边圆角）。"""
    t = get_theme_tokens(dark)
    return f"""
        QPushButton#pushButton_import_bill {{
            color: {t["text"]};
            background: {t["surface"]};
            border: 1px solid {t["border"]};
            border-radius: 4px;
            padding: 0px 10px;
            font-size: 13px;
        }}
        QPushButton:hover#pushButton_import_bill {{
            color: #FFFFFF;
            background: {t["accent"]};
            border-color: {t["accent"]};
        }}
        QPushButton:pressed#pushButton_import_bill {{
            color: #FFFFFF;
            background: {t["accent_pressed"]};
            border-color: {t["accent_pressed"]};
        }}
        QPushButton:disabled#pushButton_import_bill {{
            color: {t["text_disabled"]};
            background: {t["surface_muted"]};
            border-color: {t["border"]};
        }}
    """


class BillImportMixin:
    """「导入账单」入口：建按钮 + 机器绑定 + 选文件导入 + 刷新榜单数据。"""

    # ------------------------------------------------------------------ 建按钮

    def _init_bill_import_button(self) -> None:
        """建「导入账单」按钮（先隐藏，机器校验通过才显示）。

        挂在 ``gridLayoutWidget_20`` 下当绝对定位子项——理由见模块 docstring。
        ``ui.pushButton_import_bill`` 是本窗口里唯一句柄，布局同步与测试都从它取。
        """
        ui = self.Ui
        host = getattr(ui, "gridLayoutWidget_20", None)
        if host is None:
            return
        button = QPushButton(_BILL_BUTTON_TEXT, parent=host)
        button.setObjectName("pushButton_import_bill")
        button.setToolTip("导入微信 / 支付宝 xlsx 账单，刷新赞助窗口的新人榜与土豪榜")
        button.setFixedHeight(_BILL_BUTTON_HEIGHT)
        width = max(button.sizeHint().width(), _BILL_BUTTON_MIN_WIDTH)
        # 记下自然宽：窗口极窄时布局那边会按剩余空间收窄（左缘仍钉在锚点上）
        self._bill_button_width = min(width, _BILL_BUTTON_MAX_WIDTH)
        button.setFixedWidth(self._bill_button_width)
        button.clicked.connect(self.import_bill)
        button.hide()  # 未通过机器校验前不出现
        ui.pushButton_import_bill = button
        self._style_bill_button()

        # 机器校验走后台：PowerShell 冷启动约 1 秒，不能卡住首屏
        machine_binding.ensure_probe_started()
        self._bill_bind_timer = QTimer(self)
        self._bill_bind_timer.setInterval(_BILL_BIND_POLL_MS)
        self._bill_bind_timer.timeout.connect(self._poll_bill_bind_state)
        self._bill_bind_timer.start()

    def _style_bill_button(self) -> None:
        """按当前主题套按钮样式（暗黑/亮色切换时由 window_ops 再调一次）。"""
        button = getattr(self.Ui, "pushButton_import_bill", None)
        if button is None:
            return
        button.setStyleSheet(_bill_button_qss(bool(getattr(self, "dark_mode", False))))

    def _poll_bill_bind_state(self) -> None:
        """后台探测有结果后：绑定的机器显示按钮并摆好位置，其余机器永久隐藏。"""
        state = machine_binding.probe_state()
        if state is None:
            return
        timer = getattr(self, "_bill_bind_timer", None)
        if timer is not None:
            timer.stop()
        button = getattr(self.Ui, "pushButton_import_bill", None)
        if button is None:
            return
        if not state:
            button.hide()
            return
        button.show()
        button.raise_()
        self._sync_advanced_page_bill_button()

    # ------------------------------------------------------------------ 导入

    def import_bill(self) -> None:
        """选 xlsx 账单 → 解析 → 并入榜单记录 → 落盘。"""
        # 双保险：按钮本来就只在绑定机器上出现，这里再挡一次（防止误调）
        if not machine_binding.is_bound_machine():
            QMessageBox.warning(self, _BILL_BUTTON_TEXT, "本功能未授权在当前电脑使用。")
            return

        from mdcx.tools.bill_import import (
            BillImportError,
            load_records,
            merge_records,
            parse_bill,
            save_records,
        )

        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择微信 / 支付宝账单",
            "",
            "Excel 账单 (*.xlsx *.xlsm);;所有文件 (*)",
        )
        if not path:
            return
        try:
            imported = parse_bill(path)
        except BillImportError as exc:
            QMessageBox.warning(self, _BILL_BUTTON_TEXT, str(exc))
            return
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            QMessageBox.warning(self, _BILL_BUTTON_TEXT, "账单解析失败，详细信息见日志页面。")
            return
        if not imported:
            QMessageBox.information(
                self,
                _BILL_BUTTON_TEXT,
                "账单里没有可用的收入记录。\n只统计「收入」，支出、退款、不计收支都跳过。",
            )
            return
        try:
            records = merge_records(load_records(), imported)
            saved = save_records(records)
        except BillImportError as exc:
            QMessageBox.warning(self, _BILL_BUTTON_TEXT, str(exc))
            return
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            QMessageBox.warning(self, _BILL_BUTTON_TEXT, "账单记录写入失败，详细信息见日志页面。")
            return
        QMessageBox.information(
            self,
            _BILL_BUTTON_TEXT,
            f"已导入 {len(imported)} 笔收入记录，榜单现共 {len(records)} 笔。\n"
            f"记录文件：{saved}\n"
            "重新打开「赞助作者」窗口即可看到新人榜 / 土豪榜。",
        )
