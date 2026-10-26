"""全局主题令牌与通用 QSS 构件（浅色 / 深色）。

这些部件与具体窗口无关：主窗口、裁剪窗口、赞赏窗口、演员管理对话框、站点优先级
对话框……都要用同一套配色与滚动条 / 菜单 / 树控件样式。放在 mdcx 根下作为中立层，
避免 views / tools 反向依赖 controllers 里的主窗口样式模块。

主窗口专属的部分（set_style / set_dark_style / 信息管理顶栏按钮样式）仍留在
mdcx/controllers/main_window/style.py，它从本模块导入并重新导出这些通用部件，
既有导入路径保持不变。

注意：_qss_resources 通过 mdcx.config.resources 的 resources 单例取绝对路径，
而该单例被大量测试用 style_mod.resources.qtr = ... 打补丁；两个模块持有的是同一个
Resources 实例，所以补丁依然生效。
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from mdcx.config.resources import resources


def _qss_resources(style: str) -> str:
    """将 QSS 中的相对资源路径替换为 Qt 可识别的绝对路径。"""
    return (
        style.replace("url(resources/Img/check_indicator.svg)", f"url({resources.qtr('Img/check_indicator.svg')})")
        .replace("url(resources/Img/radio_indicator.svg)", f"url({resources.qtr('Img/radio_indicator.svg')})")
        .replace("url(resources/Img/chevron_down_light.svg)", f"url({resources.qtr('Img/chevron_down_light.svg')})")
        .replace("url(resources/Img/chevron_down_dark.svg)", f"url({resources.qtr('Img/chevron_down_dark.svg')})")
    )


LIGHT_TOKENS = {
    "window": "#FFFFFF",
    "surface": "#F8FAFC",
    "surface_muted": "#F5F7FF",
    "text": "#111827",
    "text_muted": "#4B5563",
    "text_disabled": "#9AA3AF",
    "placeholder": "#6B7280",
    "border": "#D8DEE9",
    "accent": "#4C6EFF",
    "accent_hover": "#6684FF",
    "accent_pressed": "#3F5FE6",
    "link": "#0B63CE",
    "link_hover": "#084A9C",
    "selection_bg": "rgba(76, 110, 255, 42)",
    "selection_bg_inactive": "rgba(76, 110, 255, 34)",
    "selection_text": "#111827",
    "tree_hover": "rgba(76, 110, 255, 18)",
    "tree_border": "rgba(76, 110, 255, 170)",
}

DARK_TOKENS = {
    "window": "#121A24",
    "surface": "#18222D",
    "surface_muted": "#1D2834",
    "text": "#E5E7EB",
    "text_muted": "#B6C2D0",
    "text_disabled": "#6B7280",
    "placeholder": "#94A3B8",
    "border": "#2F3A46",
    "accent": "#6684FF",
    "accent_hover": "#8EA3FF",
    "accent_pressed": "#4C6EE0",
    "link": "#9DB7FF",
    "link_hover": "#C3D2FF",
    "selection_bg": "rgba(102, 132, 255, 80)",
    "selection_bg_inactive": "rgba(102, 132, 255, 58)",
    "selection_text": "#FFFFFF",
    "tree_hover": "rgba(102, 132, 255, 34)",
    "tree_border": "rgba(142, 163, 255, 190)",
}


def _tokens(dark: bool) -> dict[str, str]:
    return DARK_TOKENS if dark else LIGHT_TOKENS


def get_theme_tokens(dark: bool) -> dict[str, str]:
    return _tokens(dark)


def apply_application_palette(dark: bool) -> None:
    app = QApplication.instance()
    if app is None:
        return

    t = _tokens(dark)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(t["link"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["placeholder"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(t["text_disabled"]))
    try:
        palette.setColor(QPalette.ColorRole.Accent, QColor(t["accent"]))
    except AttributeError:
        pass
    app.setPalette(palette)  # type: ignore[attr-defined]


def build_tree_widget_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QTreeWidget {{
            outline: 0;
            border: 0;
            color: {t["text"]};
            background: transparent;
            alternate-background-color: transparent;
            selection-background-color: transparent;
            selection-color: {t["selection_text"]};
        }}
        QTreeWidget::item {{
            color: {t["text"]};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 2px 4px;
        }}
        QTreeWidget::item:hover {{
            color: {t["text"]};
            background: {t["tree_hover"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected,
        QTreeWidget::item:selected:active {{
            color: {t["selection_text"]};
            background: {t["selection_bg"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected:!active {{
            color: {t["selection_text"]};
            background: {t["selection_bg_inactive"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::branch {{
            background: transparent;
            border: 0;
            image: none;
        }}
        QTreeWidget::branch:selected {{
            background: transparent;
            image: none;
        }}
    """


def build_menu_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QMenu {{
            color: {t["text"]};
            background: {t["surface"]};
            border: 1px solid {t["border"]};
            padding: 4px;
        }}
        QMenu::item {{
            color: {t["text"]};
            padding: 5px 28px 5px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            color: #FFFFFF;
            background: {t["accent"]};
        }}
        QMenu::item:disabled {{
            color: {t["text_disabled"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t["border"]};
            margin: 4px 8px;
        }}
    """


def build_scrollbar_style(dark: bool) -> str:
    handle = "#4B5563" if dark else "#CBD5E1"
    handle_hover = "#64748B" if dark else "#94A3B8"
    track = "#1F2937" if dark else "#E5E7EB"
    # 议题 #153: 加宽(10->16px)、改直角实心、给轨道淡底色, 更接近浏览器滚动条;
    # 深/浅主题颜色由 build_scrollbar_style(dark) 统一切换。
    return f"""
        QScrollBar:vertical{{
            width: 16px;
            margin: 0;
            background: {track};
        }}
        QScrollBar::handle:vertical{{
            min-height: 44px;
            border-radius: 3px;
            background: {handle};
        }}
        QScrollBar::handle:vertical:hover{{
            background: {handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{
            height: 0;
            background: transparent;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{{
            background: transparent;
        }}
        QScrollBar:horizontal{{
            height: 16px;
            margin: 0;
            background: {track};
        }}
        QScrollBar::handle:horizontal{{
            min-width: 44px;
            border-radius: 3px;
            background: {handle};
        }}
        QScrollBar::handle:horizontal:hover{{
            background: {handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{{
            width: 0;
            background: transparent;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal{{
            background: transparent;
        }}
    """


def build_setting_button_style(object_name: str, dark: bool) -> str:
    """设置页里那种紧凑方角小按钮的样式（「导入账单」「设备编号」共用一套）。

    不复用全局那套 8px 描边圆角：设置页里的按钮要和同行的复选框同高（30px）、
    紧贴文字，圆角一大就显得比复选框"胖"一圈。
    """
    t = _tokens(dark)
    return f"""
        QPushButton#{object_name} {{
            color: {t["text"]};
            background: {t["surface"]};
            border: 1px solid {t["border"]};
            border-radius: 4px;
            padding: 0px 10px;
            font-size: 13px;
        }}
        QPushButton:hover#{object_name} {{
            color: #FFFFFF;
            background: {t["accent"]};
            border-color: {t["accent"]};
        }}
        QPushButton:pressed#{object_name} {{
            color: #FFFFFF;
            background: {t["accent_pressed"]};
            border-color: {t["accent_pressed"]};
        }}
        QPushButton:disabled#{object_name} {{
            color: {t["text_disabled"]};
            background: {t["surface_muted"]};
            border-color: {t["border"]};
        }}
    """
