"""演员管理器子窗口共用的界面小部件（只放控件拼装，不放业务）。

原先后同样的行/按钮在三个子窗口里各抄一遍（设置窗口、数据源测试窗口、演员详情窗口），
抄到第三遍时已经出现细微漂移。这里把「本地头像目录」这类行拼装与「浏览…」对话框收成
一处，调用方仍可自由改文案与初始值。

**只收形状完全一致的行。** 数据源测试窗（``ActorSourceTestDialog``）那一行仍自建：
它被嵌在一个定宽 300px、内容边距清零的容器 ``QWidget`` 里并右对齐到对话框右边缘，
演员详情窗（``ActorDetailDialog``）那一行则要求输入框 ``stretch=1`` 且浏览按钮要挂
``btnPrimary`` 对象名并被测试按 ``folder_browse_btn`` 取用——两者都需要额外参数才能套用，
为省几行而引入分支反而更难读，故保留原样。
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton


def make_folder_row(
    label_text: str,
    edit: QLineEdit,
    browse_slot: Callable[[], None],
    *,
    button_text: str = "浏览...",
) -> QHBoxLayout:
    """拼出「标签 + 只读输入框 + 浏览按钮」一行，返回可直接 addLayout 的布局。

    Args:
        label_text: 行首标签，例如「本地头像目录:」。
        edit: 已按调用方要求初始化好的输入框（对象由调用方持有）。
        browse_slot: 浏览按钮的槽，一般是 ``self._browse_folder``。
        button_text: 按钮文案。
    """
    row = QHBoxLayout()
    row.addWidget(QLabel(label_text))
    browse_btn = QPushButton(button_text)
    browse_btn.clicked.connect(browse_slot)
    row.addWidget(edit)
    row.addWidget(browse_btn)
    return row


def browse_folder(parent, title: str, edit: QLineEdit, *, cursor_reset: bool = True) -> None:
    """弹出目录选择框并回填到 ``edit``；用户取消或选到同一目录时保持原样。

    Args:
        parent: 父窗口，用于让对话框保持置顶关系。
        title: 文件对话框标题。
        edit: 目标输入框。
        cursor_reset: 选中后把光标拨回开头，避免长路径只看到末尾。
    """
    path = QFileDialog.getExistingDirectory(parent, title, edit.text())
    if not path:
        return
    edit.setText(path)
    if cursor_reset:
        edit.setCursorPosition(0)
