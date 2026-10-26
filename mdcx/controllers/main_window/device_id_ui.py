"""设置-高级-高级功能：「设备编号」按钮（导出本机设备 ID 的 txt）。

需求（用户 2026-10-26）：

1. 按钮挂在「隐藏图标」行**右侧**（即「隐藏菜单图标」之后），样式与宽度同
   「导入账单」一致；
2. 点击后取本机设备 ID，弹保存对话框让用户选 txt 的存放位置；
3. 各系统按各自口径取号：Windows 11 取「设置 → 系统 → 关于 → 设备 ID」，
   macOS 取硬件 UUID，Linux/Ubuntu 取 machine-id（详见 ``mdcx/utils/device_id.py``）。

做法与「导入账单」同源：按钮是 ``gridLayoutWidget_20`` 的**绝对定位游离子项**，
不进 ``horizontalLayout_dock``——那一行的间隔项由 ``_sync_advanced_page_align``
按锚点算出来，行内多一项就得重算间隔，而间隔项的 sizeHint 会顶进网格列宽、
把整页连同锚点一起推走。几何交给 ``_sync_advanced_page_device_id_button``
每遍按「隐藏菜单图标」的实测右缘钉死。

与「导入账单」不同的一点：本按钮**不绑定机器**——它本来就是给用户导出编号、
发给作者申请授权用的，人人都该点得到。
"""

import platform
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
)

from mdcx.ui_theme import build_setting_button_style
from mdcx.utils import device_id as device_id_util

_DEVICE_BUTTON_TEXT = "设备编号"
_DEVICE_BUTTON_HEIGHT = 30  # 与同行「隐藏菜单图标」复选框同高
_DEVICE_BUTTON_MIN_WIDTH = 92
_DEVICE_BUTTON_MAX_WIDTH = 128


class DeviceIdMixin:
    """「设备编号」入口：建按钮 + 取设备 ID + 弹保存对话框写 txt。"""

    # ------------------------------------------------------------------ 建按钮

    def _init_device_id_button(self) -> None:
        """建「设备编号」按钮（挂在「隐藏图标」行右侧，见模块 docstring）。"""
        ui = self.Ui
        host = getattr(ui, "gridLayoutWidget_20", None)
        if host is None:
            return
        button = QPushButton(_DEVICE_BUTTON_TEXT, parent=host)
        button.setObjectName("pushButton_device_id")
        button.setToolTip("导出本机设备编号到 txt 文件，可发给作者申请使用授权")
        button.setFixedHeight(_DEVICE_BUTTON_HEIGHT)
        # 宽度同「导入账单」：直接沿用它的自然宽（两枚按钮文案都是四个汉字，
        # 本就会算出同一个值；显式复用可避免以后只改了一边的最小宽而两枚对不齐）
        width = getattr(self, "_bill_button_width", 0) or max(button.sizeHint().width(), _DEVICE_BUTTON_MIN_WIDTH)
        self._device_button_width = min(width, _DEVICE_BUTTON_MAX_WIDTH)
        button.setFixedWidth(self._device_button_width)
        button.clicked.connect(self.export_device_id)
        ui.pushButton_device_id = button
        self._style_device_button()

    def _style_device_button(self) -> None:
        """按当前主题套按钮样式（暗黑/亮色切换时由 window_ops 再调一次）。"""
        button = getattr(self.Ui, "pushButton_device_id", None)
        if button is None:
            return
        button.setStyleSheet(
            build_setting_button_style("pushButton_device_id", bool(getattr(self, "dark_mode", False)))
        )

    # ------------------------------------------------------------------ 导出

    def export_device_id(self) -> None:
        """取本机设备编号 → 让用户选存放位置 → 写 txt。"""
        identifier = device_id_util.device_id()
        if not identifier:
            QMessageBox.warning(
                self,
                _DEVICE_BUTTON_TEXT,
                "未能读取本机设备编号。\n"
                "Windows 可在「设置 → 系统 → 关于 → 设备 ID」处查看，手动抄下来发给作者也可以。",
            )
            return

        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation) or str(Path.home())
        host_name = platform.node().strip() or "本机"
        default_path = str(Path(folder) / f"设备编号_{host_name}.txt")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存设备编号",
            default_path,
            "文本文件 (*.txt)",
            options=getattr(self, "options", QFileDialog.Option(0)),
        )
        if not path:
            return
        try:
            Path(path).write_text(device_id_util.build_report(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, _DEVICE_BUTTON_TEXT, f"写入失败：{exc}")
            return
        QMessageBox.information(self, _DEVICE_BUTTON_TEXT, f"设备编号已保存到：\n{path}")
