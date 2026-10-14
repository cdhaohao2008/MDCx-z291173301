"""文本框「内容优先从左展示」工具。

需求：软件里所有显示用的输入框（QLineEdit / QPlainTextEdit / QTextEdit）在被程序
回填内容时，视图都停在最左侧，优先露出开头（`http://`、`https://` 这类前缀）。

背景：`QLineEdit.setText()` 后光标落在文本末尾，长路径 / 长 URL 会把开头滚出可视区，
用户得手动按 Home 才知道框里是什么。仓库里早有零散的 `setCursorPosition(0)`（如
`site_priority_dialog.py` 的 `_set_site_summary` / `_style_config_line_edit`），但真正会滚
的是三类文本框（`mdcx/views/MDCx.py` 就有约 150 个 QLineEdit），逐个回填点改一遍既费事
又容易漏，将来新增回填点还会回归。

做法：对一棵控件树里的 QLineEdit 统一挂 `textChanged` 回调，**仅在控件没有焦点时**
把插入点拉回开头。区分有无焦点是关键——程序回填时控件通常无焦点（于是自动从左展
示），而用户正在手输、粘贴或按方向键浏览时有焦点（此时一律不插手，绝不打断输入）。

只钩 QLineEdit 的原因（实测，另两类无需钩也不会崩）：
- QPlainTextEdit / QTextEdit 的 `setPlainText()` 自会把光标复位到 0（实测：先把光标
  移到末尾再 `setPlainText`，新内容后光标仍是 0），本来就是从左展示；
- 更关键的是，在它们的 `textChanged` 回调里动光标会让 Qt 硬崩（退出码
  0xC0000409）——`setTextCursor(QTextCursor(doc))`、`moveCursor(Start)`、
  甚至 `QTimer.singleShot(0, ...)` 推迟执行，三种写法都必崩，故一律不挂。

只钩 `textChanged` 的原因：QLineEdit 在 `cursorPositionChanged` 回调里调
`setCursorPosition(0)` 会让 Qt 硬崩（退出码 0xC0000409，实测），故只能靠文本变化来
触发。遗留边界：`setText()` 传入**与当前完全相同**的文本时 Qt 只重置光标、不发
`textChanged`，这种「原值重填」不会被拉回——实际使用中配置/路径回填都是新值，可忽略。

幂等：已挂过的控件用动态属性 `_left_anchor_hooked` 标记跳过，重复调用安全。
"""

from __future__ import annotations

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit

# 标记控件是否已挂钩（动态属性，随控件生命周期，无需外部集合）
_HOOK_FLAG = "_left_anchor_hooked"


def _anchor_to_start(edit) -> None:
    """把插入点/光标拉回开头（仅供无焦点时调用）。

    多行框只能在 `textChanged` 之外调用（见模块 docstring 的崩溃说明）。
    """
    if isinstance(edit, QLineEdit):
        edit.setCursorPosition(0)
        return
    # QPlainTextEdit / QTextEdit：QTextCursor(document) 构造出来就停在 0 位。
    # 注意不能用 `moveCursor(QTextCursor.MoveMode.Start)`——Qt6 该枚举没有 `Start`
    # 成员，运行期会抛 AttributeError。
    edit.setTextCursor(QTextCursor(edit.document()))


def _iter_text_edits(root):
    """产出 root 自身及其所有后代里的文本框（含 QSpinBox/QDoubleSpinBox 内嵌的）。"""
    if isinstance(root, QLineEdit):
        yield root
    yield from root.findChildren(QLineEdit)
    yield from root.findChildren(QPlainTextEdit)
    yield from root.findChildren(QTextEdit)


def left_anchor_text_edits(root) -> int:
    """给 root 及其后代的 QLineEdit 挂上「无焦点时内容从左展示」的钩子。

    应在控件树搭好之后调用（控件还在构建中时挂不到；对后续动态新建的控件可再调一次）。
    返回本次新挂钩的控件数（已挂过的不计入）。

    QAbstractSpinBox 的 lineEdit 由 Qt 自己创建，`findChildren` 是递归的，
    因此自带的输入框同样会被覆盖。
    """
    if root is None:
        return 0

    hooked = 0
    for edit in _iter_text_edits(root):
        # 只钩 QLineEdit：其余两类靠 setPlainText 自复位，且在 textChanged 里动
        # 它们的光标会让 Qt 硬崩（详见模块 docstring）。
        if not isinstance(edit, QLineEdit) or edit.property(_HOOK_FLAG):
            continue
        edit.setProperty(_HOOK_FLAG, True)

        def _on_text_changed(_text: str, target=edit) -> None:
            # 有焦点 = 用户正在输入 / 粘贴 / 拖选，绝不抢光标
            if not target.hasFocus():
                target.setCursorPosition(0)

        edit.textChanged.connect(_on_text_changed)
        hooked += 1
    return hooked


def anchor_if_idle(edit) -> None:
    """单点工具：控件无焦点时立即把内容拉到左侧（配合一次性回填使用）。"""
    if edit is not None and not edit.hasFocus():
        _anchor_to_start(edit)


__all__ = ["anchor_if_idle", "left_anchor_text_edits"]
