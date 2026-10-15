"""主窗口专属样式。

通用主题令牌与通用 QSS 构件（_qss_resources / LIGHT_TOKENS / DARK_TOKENS / _tokens /
get_theme_tokens / apply_application_palette / build_tree_widget_style / build_menu_style /
build_scrollbar_style）已经搬到中立层 mdcx/ui_theme.py，这里导入并重新导出，既有导入
路径不变；只有需要访问 self.Ui 的主窗口专属样式留在这里。
"""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize

from mdcx.config.resources import resources
from mdcx.ui_theme import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    _qss_resources,
    _tokens,
    apply_application_palette,
    build_menu_style,
    build_scrollbar_style,
    build_tree_widget_style,
    get_theme_tokens,
)

__all__ = [
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "_apply_log_document_style",
    "_nfo_lib_top_button_qss",
    "_qss_resources",
    "_tokens",
    "apply_application_palette",
    "apply_nfo_lib_top_button_style",
    "build_menu_style",
    "build_scrollbar_style",
    "build_tree_widget_style",
    "get_theme_tokens",
    "resources",
    "set_dark_style",
    "set_style",
]

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


def _apply_log_document_style(self: "MyMAinWindow", dark: bool) -> None:
    t = _tokens(dark)
    document_style = f"""
        a {{
            color: {t["link"]};
            text-decoration: none;
            font-weight: 500;
        }}
        a:hover {{
            color: {t["link_hover"]};
            text-decoration: underline;
        }}
    """
    for text_browser in (
        self.Ui.textBrowser_log_main,
        self.Ui.textBrowser_log_main_2,
        self.Ui.textBrowser_log_main_3,
        self.Ui.textBrowser_net_main,
        self.Ui.textBrowser_show_success_list,
        self.Ui.textBrowser_show_tips,
    ):
        text_browser.document().setDefaultStyleSheet(document_style)


def _nfo_lib_top_button_qss(dark: bool) -> str:
    """信息管理顶栏「选择目录」「刷新」按钮样式。

    外观与「软件设置 → 高级 → 选择目录」（pushButton_select_config_folder）保持一致，
    单独下发是为了在套用样式前后按控件原始尺寸钉死宽高，避免顶栏整体位移。
    """
    background = "rgba(220, 220,220, 50)" if dark else "rgba(220, 220,220, 255)"
    # 注意：每个选择器都要带上完整前缀，`#a,#b:hover` 会让 hover 状态作用在整组上
    return f"""
        QPushButton#pushButton_nfo_lib_select_dir,
        QPushButton#pushButton_nfo_lib_refresh{{
            font-size:14px;
            background-color: {background};
            border-color:black;
            border-width:8px;
            border-radius:20px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_nfo_lib_select_dir,
        QPushButton:hover#pushButton_nfo_lib_refresh{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_nfo_lib_select_dir,
        QPushButton:pressed#pushButton_nfo_lib_refresh{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        """


def apply_nfo_lib_top_button_style(self: "MyMAinWindow", dark: bool) -> None:
    """套用信息管理顶栏按钮样式，并把宽高钉死在套用前的尺寸上。

    QSS 里的 padding/边框会改变控件的 sizeHint，直接套用会让顶部栏重新排版；
    这里先量出原始尺寸再固定，保证「选择目录」「刷新」按钮的宽高与加样式前完全一致。
    """
    sheet = _nfo_lib_top_button_qss(dark)
    for name in ("pushButton_nfo_lib_select_dir", "pushButton_nfo_lib_refresh"):
        button = getattr(self.Ui, name, None)
        if button is None:
            continue
        button.ensurePolished()
        hint = button.sizeHint()
        minimum = button.minimumSize()
        natural = QSize(max(hint.width(), minimum.width()), max(hint.height(), minimum.height()))
        button.setStyleSheet(sheet)
        button.setFixedSize(natural)


def set_style(self: "MyMAinWindow"):
    if self.dark_mode:
        self.set_dark_style()
        return

    apply_application_palette(False)
    _apply_log_document_style(self, False)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(False))

    # 控件美化 左侧栏样式
    self.Ui.widget_setting.setStyleSheet(f"""
        QWidget#widget_setting{{
            background: #EEF3FF;
            border-top-left-radius: {self.window_radius}px;
            border-bottom-left-radius: {self.window_radius}px;
        }}
        QPushButton#pushButton_main,#pushButton_log,#pushButton_tool,#pushButton_setting,#pushButton_net,#pushButton_about,#pushButton_emby_manager_nav,#pushButton_nfo_library{{
            font-size: 14px;
            color: black;
            border-width: 9px;
            border-color: gray;
            border-radius: 10px;
            text-align : left;
            qproperty-iconSize: 20px 20px;
            padding-left: 20px;
        }}
        QLabel#label_show_version{{
            font-size: 13px;
            color: rgba(20, 20, 20, 250);
            border: 0px solid rgba(255, 255, 255, 80);
        }}
        /* 侧栏「[赞助作者]」链接字号。
           实测（1032x900，dpr 1.25，跳过按钮图标盒量文字墨迹）：导航按钮 14px 的
           文字墨迹是 w=56.0 h=13.6 ink=487 density=0.409；QLabel 走 QTextDocument
           富文本渲染，同样 14px 只有 w=56.0 h=13.6 ink=479 density=0.403——尺寸相同
           但墨迹少约 12%，且肉眼笔画明显更细，视觉上就读成「字更小」（用户两次反馈）。
           提到 16px 后 w=63.2 / h=16.0，比按钮宽 13%、高 18%，肉眼可辨不小于按钮。
           富文本 anchor 继承控件字体，故 QSS 是唯一能统一字号的机制（QLabel.setFont
           会被本样式表覆盖而失效）。颜色由 _style_donate_link 按明暗主题写入富文本。*/
        QLabel#label_donate_link{{
            font-size: 16px;
        }}
        """)
    # 主界面
    self.Ui.page_main.setStyleSheet("""
        QLabel#label_number1,#label_actor1,#label_title1,#label_poster1,#label_number,#label_actor,#label_title,#label_poster1{
            font-size: 16px;
            font-weight: bold;
            background-color: rgba(246, 246, 246, 0);
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_file_path{
            font-size: 16px;
            color: black;
            background-color: rgba(246, 246, 246, 0);
            font-weight: bold;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_poster_size{
            color: rgba(0, 0, 0, 200);
        }
        QLabel#label_poster,#label_thumb{
            border: 1px solid rgba(60, 60, 60, 100);
        }
        QGroupBox{
            background-color: rgba(246, 246, 246, 0);
        }
        """)
    # 工具页
    self.Ui.page_tool.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QWidget#scrollAreaWidgetContents_gongju{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }

        QLabel{
            font-size:13px;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QComboBox{
            combobox-popup: 0;
            font-size: 13px;
            color: black;
        }
        QGroupBox{
            background-color: rgba(245,245,246,220);
            border-radius: 10px;
        }
        """)
    # 使用帮助页
    self.Ui.page_about.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QTextBrowser{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size: 13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }
        """)
    # 设置页
    self.Ui.page_setting.setStyleSheet(
        _qss_resources("""
        * {
            font-size:13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }
        QTabWidget{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }
        QTabWidget::tab-bar {
            alignment: center;
        }
        QTabBar::tab{
            color: black;
            border:1px solid #E8E8E8;
            min-height: 3ex;
            min-width: 6ex;
            padding: 2px;
            background-color:#FFFFFF;
            border-radius: 1px;
        }
        QTabBar::tab:selected{
            color: white;
            font-weight:bold;
            border-bottom: 2px solid #2080F7;
            background-color:#2080F7;
            border-radius: 1px;
        }
        QWidget#tab1,#tab2,#tab3,#tab4,#tab5,#tab,#tab_2,#tab_3,#tab_4,#tab_5,#tab_6,#tab_7,#scrollAreaWidgetContents_guaxiaomulu,#scrollAreaWidgetContents_guaxiaomoshi,#scrollAreaWidgetContents_guaxiaowangzhan,#scrollAreaWidgetContents_xiazai,#scrollAreaWidgetContents_mingming,#scrollAreaWidgetContents_fanyi,#scrollAreaWidgetContents_zimu,#scrollAreaWidgetContents_shuiyin,#scrollAreaWidgetContents_nfo,#scrollAreaWidgetContents_yanyuan,#scrollAreaWidgetContents_wangluo,#scrollAreaWidgetContents_gaoji{
            background-color: rgba(255, 255, 255, 255);
            border-color: rgba(246, 246, 246, 255);
        }
        QLabel{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_config,#label_config_tool{
            font-size:13px;
            border:0px solid rgba(230, 230, 230, 80);
            background: rgba(246, 246, 246, 220);
        }

        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QRadioButton{
            font-size:13px;
        }
        QComboBox{
            combobox-popup: 0;
            font-size:13px;
        }
        QCheckBox{
            font-size:13px;
        }
        QCheckBox::indicator, QRadioButton::indicator{
            width: 14px;
            height: 14px;
            border: 1px solid #B8C0CC;
            background: #FFFFFF;
        }
        QCheckBox::indicator{
            border-radius: 3px;
        }
        QRadioButton::indicator{
            border-radius: 7px;
        }
        QCheckBox::indicator:checked{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/check_indicator.svg);
        }
        QRadioButton::indicator:checked{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/radio_indicator.svg);
        }
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{
            border: 1px solid #4C6EFF;
        }
        QPlainTextEdit{
            font-size:13px;
        }
        QGroupBox{
            background-color: rgba(245,245,246,220);
            border-radius: 10px;
        }
        """)
    )
    # 整个页面
    self.Ui.centralwidget.setStyleSheet(
        _qss_resources(f"""
        * {{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size:13px;
            color: black;
        }}
        QTreeWidget
        {{
            background-color: rgba(246, 246, 246, 0);
            font-size: 12px;
            border:0px solid rgb(120,120,120);
        }}
        QWidget#centralwidget{{
            background: #FFFFFF;
            border: {self.window_border}px solid rgba(20,20,20,50);
            border-radius: {self.window_radius}px;
       }}
        QTextBrowser#textBrowser_log_main,#textBrowser_net_main{{
            font-size:13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_2{{
            font-size:13px;
            border-radius: 0px;
            border-top: 1px solid #BEBEBE;
            background-color: rgba(238,245,245,60);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_3{{
            font-size:13px;
            border-radius: 0px;
            border-right: 1px solid #EDEDED;
            background-color: rgba(239,255,252,240);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_show_success_list,#textBrowser_show_tips{{
            font-size: 13px;
            background-color: rgba(240, 245, 240, 240);
            border: 1px solid #BEBEBE;
            padding: 2px;
        }}
        QWidget#widget_show_success,#widget_show_tips,#widget_nfo{{
            background-color: rgba(246,246,246,255);
            border: 1px solid rgba(20,20,20,50);
            border-radius: 10px;
       }}
        QWidget#scrollAreaWidgetContents_nfo_editor{{
            background-color: rgba(240, 245, 240, 240);
            border: 0px solid rgba(0,0,0,150);
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox{{
            font-size:14px;
            background:white;
            border-radius:10px;
            border: 1px solid #D8DEE9;
            padding: 4px 8px;
            selection-background-color: #4C6EFF;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus{{
            border: 1px solid #4C6EFF;
            background: #FFFFFF;
        }}
        QTextEdit#textEdit_nfo_outline,#textEdit_nfo_originalplot,#textEdit_nfo_tag{{
            font-size:14px;
            background:white;
            border: 1px solid #D8DEE9;
            padding: 4px 8px;
        }}
        QComboBox{{
            combobox-popup: 0;
            background: #FFFFFF;
            border: 1px solid #D8DEE9;
            border-radius: 8px;
            padding: 3px 30px 3px 8px;
            selection-background-color: #4C6EFF;
        }}
        QComboBox::drop-down{{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 26px;
            border-left: 1px solid #D8DEE9;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #F8FAFC;
        }}
        QComboBox::drop-down:hover{{
            background: #EEF2FF;
        }}
        QComboBox::down-arrow{{
            image: url(resources/Img/chevron_down_light.svg);
            width: 14px;
            height: 14px;
        }}
        QComboBox:focus{{
            border: 1px solid #4C6EFF;
        }}
        QComboBox QAbstractItemView{{
            background: #FFFFFF;
            border: 1px solid #D8DEE9;
            selection-background-color: #4C6EFF;
            selection-color: white;
            outline: 0;
        }}
        QComboBox QAbstractItemView::item{{
            min-height: 24px;
            padding: 4px 8px;
            color: #111827;
        }}
        QComboBox QAbstractItemView::item:selected{{
            color: #FFFFFF;
            background: #4C6EFF;
        }}
        QCheckBox::indicator, QRadioButton::indicator{{
            width: 14px;
            height: 14px;
            border: 1px solid #B8C0CC;
            background: #FFFFFF;
        }}
        QCheckBox::indicator{{
            border-radius: 3px;
        }}
        QRadioButton::indicator{{
            border-radius: 7px;
        }}
        QCheckBox::indicator:checked{{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/check_indicator.svg);
        }}
        QRadioButton::indicator:checked{{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/radio_indicator.svg);
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{{
            border: 1px solid #4C6EFF;
        }}
        QToolTip{{
            border: 1px solid #D8DEE9;
            border-radius: 8px;
            background: #FFFFFF;
            color: #111827;
            padding: 6px 10px;
        }}
        QPushButton#pushButton_right_menu,#pushButton_play,#pushButton_open_folder,#pushButton_open_nfo,#pushButton_show_hide_logs,#pushButton_save_failed_list,#pushButton_tree_clear,#pushButton_clear_logs{{
            background-color: rgba(181, 181, 181, 0);
            border-radius:10px;
            border: 0px solid rgba(0, 0, 0, 80);
        }}
        QPushButton:hover#pushButton_right_menu,:hover#pushButton_play,:hover#pushButton_open_folder,:hover#pushButton_open_nfo,:hover#pushButton_show_hide_logs,:hover#pushButton_save_failed_list,:hover#pushButton_tree_clear,:hover#pushButton_clear_logs{{
            background-color: rgba(181, 181, 181, 120);
        }}
        QPushButton:pressed#pushButton_right_menu,:pressed#pushButton_play,:pressed#pushButton_open_folder,:pressed#pushButton_open_nfo,:pressed#pushButton_show_hide_logs,:pressed#pushButton_save_failed_list,:pressed#pushButton_tree_clear,:pressed#pushButton_clear_logs{{
            background-color: rgba(150, 150, 150, 120);
        }}
        QPushButton#pushButton_field_tips_nfo{{
            color: #111827;
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
        }}
        QPushButton:pressed#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #3F5FE6;
            border: 1px solid #3F5FE6;
        }}
        QPushButton#pushButton_scrape_note{{
            color: #111827;
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_scrape_note{{
            color: #111827;
            background: #F1F5F9;
            border: 1px solid #94A3B8;
        }}
        QPushButton:pressed#pushButton_scrape_note{{
            color: #111827;
            background: #E2E8F0;
            border: 1px solid #94A3B8;
        }}
        QPushButton#pushButton_save_new_config,#pushButton_save_new_config_tool,#pushButton_init_config,#pushButton_init_config_tool,#pushButton_success_list_close,#pushButton_success_list_save,#pushButton_success_list_clear,#pushButton_show_tips_close,#pushButton_nfo_close,#pushButton_nfo_save,#pushButton_show_pic_actor,#pushButton_add_actor_pic,#pushButton_add_actor_info,#pushButton_add_actor_pic_kodi,#pushButton_del_actor_folder,#pushButton_move_mp4,#pushButton_select_file,#pushButton_actor_db_pick_nfo_dir,#pushButton_actor_db_sync_aliases,#pushButton_select_local_library,#pushButton_select_netdisk_path,#pushButton_select_localdisk_path,#pushButton_creat_symlink,#pushButton_find_missing_number,#pushButton_select_thumb,#pushButton_start_single_file,#pushButton_select_file_clear_info,#pushButton_add_sub_for_all_video,#pushButton_view_failed_list,#pushButton_select_media_folder,#pushButton_select_media_folder_setting_page,#pushButton_select_data_dir,#pushButton_select_softlink_folder,#pushButton_select_sucess_folder,#pushButton_select_failed_folder,#pushButton_view_success_file,#pushButton_select_subtitle_folder,#pushButton_select_actor_photo_folder,#pushButton_select_gfriends_local,#pushButton_select_actor_info_db,#pushButton_select_config_folder,#pushButton_add_all_extrafanart_copy,#pushButton_del_all_extrafanart_copy,#pushButton_add_all_extras,#pushButton_del_all_extras,#pushButton_add_all_theme_videos,#pushButton_del_all_theme_videos,#pushButton_check_and_clean_files,#pushButton_search_by_number,#pushButton_search_by_url,#pushButton_cover_backfill_start{{
            font-size:14px;
            background-color: rgba(220, 220,220, 255);
            border-color:black;
            border-width:8px;
            border-radius:20px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_show_pic_actor,:hover#pushButton_add_actor_pic,:hover#pushButton_add_actor_info,:hover#pushButton_add_actor_pic_kodi,:hover#pushButton_del_actor_folder,:hover#pushButton_add_sub_for_all_video,:hover#pushButton_view_failed_list,:hover#pushButton_select_media_folder,:hover#pushButton_select_media_folder_setting_page,:hover#pushButton_select_data_dir,:hover#pushButton_select_softlink_folder,:hover#pushButton_select_sucess_folder,:hover#pushButton_select_failed_folder,:hover#pushButton_view_success_file,:hover#pushButton_select_subtitle_folder,:hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_gfriends_local,:hover#pushButton_select_actor_info_db,:hover#pushButton_select_config_folder,:hover#pushButton_add_all_extrafanart_copy,:hover#pushButton_del_all_extrafanart_copy,:hover#pushButton_add_all_extras,:hover#pushButton_del_all_extras,:hover#pushButton_add_all_theme_videos,:hover#pushButton_del_all_theme_videos,:hover#pushButton_check_and_clean_files,:hover#pushButton_search_by_number,:hover#pushButton_search_by_url{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_show_pic_actor,:pressed#pushButton_add_actor_pic,:pressed#pushButton_add_actor_info,:pressed#pushButton_add_actor_pic_kodi,:pressed#pushButton_del_actor_folder,:pressed#pushButton_add_sub_for_all_video,:pressed#pushButton_view_failed_list,:pressed#pushButton_select_media_folder,:pressed#pushButton_select_media_folder_setting_page,:pressed#pushButton_select_data_dir,:pressed#pushButton_select_softlink_folder,:pressed#pushButton_select_sucess_folder,:pressed#pushButton_select_failed_folder,:pressed#pushButton_view_success_file,:pressed#pushButton_select_subtitle_folder,:pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_gfriends_local,:pressed#pushButton_select_actor_info_db,:pressed#pushButton_select_config_folder,:pressed#pushButton_add_all_extrafanart_copy,:pressed#pushButton_del_all_extrafanart_copy,:pressed#pushButton_add_all_extras,:pressed#pushButton_del_all_extras,:pressed#pushButton_add_all_theme_videos,:pressed#pushButton_del_all_theme_videos,:pressed#pushButton_check_and_clean_files,:pressed#pushButton_search_by_number,:pressed#pushButton_search_by_url{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_save_config,#pushButton_save_config_tool,#pushButton_nfo_lib_save,#pushButton_nfo_lib_batch_save,#pushButton_nfo_lib_crop{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:25px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_save_config,:hover#pushButton_save_config_tool,:hover#pushButton_save_new_config,:hover#pushButton_save_new_config_tool,:hover#pushButton_init_config,:hover#pushButton_init_config_tool,:hover#pushButton_success_list_close,:hover#pushButton_success_list_save,:hover#pushButton_success_list_clear,:hover#pushButton_show_tips_close,:hover#pushButton_nfo_close,:hover#pushButton_nfo_save,:hover#pushButton_nfo_lib_save,:hover#pushButton_nfo_lib_batch_save,:hover#pushButton_nfo_lib_crop,:hover#pushButton_scraper_failed_list{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_save_config,:pressed#pushButton_save_config_tool,:pressed#pushButton_save_new_config,:pressed#pushButton_save_new_config_tool,:pressed#pushButton_init_config,:pressed#pushButton_init_config_tool,:pressed#pushButton_success_list_close,:pressed#pushButton_success_list_save,:pressed#pushButton_success_list_clear,:pressed#pushButton_show_tips_close,:pressed#pushButton_nfo_close,:pressed#pushButton_nfo_save,:pressed#pushButton_nfo_lib_save,:pressed#pushButton_nfo_lib_batch_save,:pressed#pushButton_nfo_lib_crop,:pressed#pushButton_scraper_failed_list{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_start_cap,#pushButton_start_cap2,#pushButton_check_net,#pushButton_scraper_failed_list{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:20px;
            padding: 2px, 2px;
            font-weight:bold;
        }}
        QPushButton:hover#pushButton_start_cap,:hover#pushButton_start_cap2,:hover#pushButton_check_net,:hover#pushButton_move_mp4,:hover#pushButton_select_file,:hover#pushButton_actor_db_pick_nfo_dir,:hover#pushButton_actor_db_sync_aliases,:hover#pushButton_select_local_library,:hover#pushButton_select_netdisk_path,:hover#pushButton_select_localdisk_path,:hover#pushButton_creat_symlink,:hover#pushButton_find_missing_number,:hover#pushButton_select_thumb,:hover#pushButton_start_single_file,:hover#pushButton_select_file_clear_info,:hover#pushButton_cover_backfill_start{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_start_cap,:pressed#pushButton_start_cap2,:pressed#pushButton_check_net,:pressed#pushButton_move_mp4,:pressed#pushButton_select_file,:pressed#pushButton_actor_db_pick_nfo_dir,:pressed#pushButton_actor_db_sync_aliases,:pressed#pushButton_select_local_library,:pressed#pushButton_select_netdisk_path,:pressed#pushButton_select_localdisk_path,:pressed#pushButton_creat_symlink,:pressed#pushButton_find_missing_number,:pressed#pushButton_select_thumb,:pressed#pushButton_start_single_file,:press#pushButton_select_file_clear_info,:pressed#pushButton_cover_backfill_start{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:12px;
            font-weight:bold;
        }}
        QSlider::groove:horizontal{{
            height: 6px;
            border-radius: 3px;
            background: #D7DDE8;
        }}
        QSlider::sub-page:horizontal{{
            border-radius: 3px;
            background: #4C6EFF;
        }}
        QSlider::add-page:horizontal{{
            border-radius: 3px;
            background: #D7DDE8;
        }}
        QSlider::handle:horizontal{{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            border: 2px solid #4C6EFF;
            background: #FFFFFF;
        }}
        QSlider::handle:horizontal:hover{{
            border: 2px solid #2F55EA;
            background: #F8FAFF;
        }}
        {build_scrollbar_style(False)}
        QProgressBar::chunk{{
            background-color: #5777FF;
            width: 3px; /*区块宽度*/
            margin: 0px;
        }}
        """)
    )
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(False))
    apply_nfo_lib_top_button_style(self, False)


def set_dark_style(self: "MyMAinWindow"):
    apply_application_palette(True)
    _apply_log_document_style(self, True)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(True))

    # 控件美化 左侧栏样式 暗黑模式
    self.Ui.widget_setting.setStyleSheet(f"""
        QWidget#widget_setting{{
            background: #1F272F;
            border-top-left-radius: {self.window_radius}px;
            border-bottom-left-radius: {self.window_radius}px;
        }}
        QPushButton#pushButton_main,#pushButton_log,#pushButton_tool,#pushButton_setting,#pushButton_net,#pushButton_about,#pushButton_emby_manager_nav,#pushButton_nfo_library{{
            font-size: 14px;
            color: white;
            border-width: 9px;
            border-color: gray;
            border-radius: 10px;
            text-align : left;
            qproperty-iconSize: 20px 20px;
            padding-left: 20px;
        }}
        QLabel#label_show_version{{
            font-size: 13px;
            color: rgba(210, 210, 210, 250);
            border: 0px solid rgba(255, 255, 255, 80);
        }}
        QLabel#label_donate_link{{
            font-size: 16px;
        }}
        """)
    # 主界面
    self.Ui.page_main.setStyleSheet("""
        QLabel#label_number1,#label_actor1,#label_title1,#label_poster1,#label_number,#label_actor,#label_title,#label_poster1{
            font-size: 16px;
            font-weight: bold;
            background-color: rgba(246, 246, 246, 0);
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_file_path{
            font-size: 16px;
            color: white;
            background-color: rgba(246, 246, 246, 0);
            font-weight: bold;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_poster_size{
            color: rgba(255, 255, 255, 200);
        }
        QLabel#label_poster,#label_thumb{
            border: 1px solid rgba(255, 255, 255, 200);
        }
        QGroupBox{
            background-color: rgba(246, 246, 246, 0);
        }
        """)
    # 工具页
    self.Ui.page_tool.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QWidget#scrollAreaWidgetContents_gongju{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }

        QLabel{
            font-size:13px;
            border: 0px solid rgba(0, 0, 0, 80);
        }

        QGroupBox{
            background-color: rgba(180, 180, 180, 20);
            border-radius: 10px;
        }
        """)
    # 使用帮助页
    self.Ui.page_about.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QTextBrowser{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size: 13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }
        """)
    # 设置页
    self.Ui.page_setting.setStyleSheet(
        _qss_resources("""
        * {
            font-size:13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QTabWidget{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QTabWidget::tab-bar {
            alignment: center;
        }
        QTabBar::tab{
            border:1px solid #1F272F;
            min-height: 3ex;
            min-width: 6ex;
            padding: 2px;
            background-color:#242D37;
            border-radius: 2px;
        }
        QTabBar::tab:selected{
            font-weight:bold;
            border-bottom: 2px solid #2080F7;
            background-color:#2080F7;
            border-radius: 1px;
        }
        QWidget#tab1,#tab2,#tab3,#tab4,#tab5,#tab,#tab_2,#tab_3,#tab_4,#tab_5,#tab_6,#tab_7,#scrollAreaWidgetContents_guaxiaomulu,#scrollAreaWidgetContents_guaxiaomoshi,#scrollAreaWidgetContents_guaxiaowangzhan,#scrollAreaWidgetContents_xiazai,#scrollAreaWidgetContents_mingming,#scrollAreaWidgetContents_fanyi,#scrollAreaWidgetContents_zimu,#scrollAreaWidgetContents_shuiyin,#scrollAreaWidgetContents_nfo,#scrollAreaWidgetContents_yanyuan,#scrollAreaWidgetContents_wangluo,#scrollAreaWidgetContents_gaoji{
            background-color: #18222D;
            border-color: rgba(246, 246, 246, 0);
        }
        QLabel{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_config,#label_config_tool{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
            background: rgba(31,39,47,230);
        }
        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QRadioButton{
            font-size:13px;
        }
        QCheckBox{
            font-size:13px;
        }
        QCheckBox::indicator, QRadioButton::indicator{
            width: 14px;
            height: 14px;
            border: 1px solid #5B6673;
            background: #18222D;
        }
        QCheckBox::indicator{
            border-radius: 3px;
        }
        QRadioButton::indicator{
            border-radius: 7px;
        }
        QCheckBox::indicator:checked{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/check_indicator.svg);
        }
        QRadioButton::indicator:checked{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/radio_indicator.svg);
        }
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{
            border: 1px solid #8EA3FF;
        }
        QPlainTextEdit{
            font-size:13px;
            background:#18222D;
            border-radius: 4px;
        }
        QGroupBox{
            background-color: rgba(180, 180, 180, 20);
            border-radius: 10px;
        }
        QPushButton{
            color: #E5E7EB;
        }
        QPushButton#pushButton_field_tips_nfo{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }
        QPushButton:hover#pushButton_field_tips_nfo{
            color: #FFFFFF;
            background: #6684FF;
            border: 1px solid #6684FF;
        }
        QPushButton:pressed#pushButton_field_tips_nfo{
            color: #FFFFFF;
            background: #4C6EE0;
            border: 1px solid #4C6EE0;
        }
        QPushButton#pushButton_scrape_note{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }
        QPushButton:hover#pushButton_scrape_note{
            color: #E5E7EB;
            background: #253140;
            border: 1px solid #566374;
        }
        QPushButton:pressed#pushButton_scrape_note{
            color: #E5E7EB;
            background: #2B3A4C;
            border: 1px solid #566374;
        }
        """)
    )
    # 整个页面
    self.Ui.centralwidget.setStyleSheet(
        _qss_resources(f"""
        * {{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size:13px;
            color: white;
        }}
        QTreeWidget
        {{
            background-color: rgba(246, 246, 246, 0);
            font-size: 12px;
            border:0px solid rgb(120,120,120);
        }}
        QWidget#centralwidget{{
            background: #18222D;
            border: {self.window_border}px solid rgba(20,20,20,50);
            border-radius: {self.window_radius}px;
       }}
        QTextBrowser#textBrowser_log_main,#textBrowser_net_main{{
            font-size:13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_2{{
            font-size:13px;
            border-radius: 0px;
            border-top: 1px solid #BEBEBE;
            background-color: #18222D;
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_3{{
            font-size:13px;
            border-radius: 0px;
            border-right: 1px solid #20303F;
            background-color: #1F272F;
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_show_success_list,#textBrowser_show_tips{{
            font-size: 13px;
            border: 1px solid #BEBEBE;
            background-color: #18222D;
            padding: 2px;
        }}
        QWidget#widget_show_success,#widget_show_tips,#widget_nfo{{
            background-color: #1F272F;
            border: 1px solid rgba(240,240,240,150);
            border-radius: 10px;
       }}
        QWidget#scrollAreaWidgetContents_nfo_editor{{
            background-color: #18222D;
            border: 0px solid rgba(0,0,0,150);
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox{{
            font-size:13px;
            background:#18222D;
            border-radius:20px;
            border: 1px solid #2F3A46;
            padding: 4px 8px;
            selection-background-color: #4C6EFF;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus{{
            border: 1px solid #6684FF;
            background: #1D2834;
        }}
        QTextEdit#textEdit_nfo_outline,#textEdit_nfo_originalplot,#textEdit_nfo_tag{{
            font-size:13px;
            background:#18222D;
            border: 1px solid #2F3A46;
            padding: 4px 8px;
        }}
        QToolTip{{
            border: 1px solid #2F3A46;
            border-radius: 8px;
            background: #F9FAFB;
            color: #111827;
            padding: 6px 10px;
        }}
        QCheckBox::indicator, QRadioButton::indicator{{
            width: 14px;
            height: 14px;
            border: 1px solid #5B6673;
            background: #18222D;
        }}
        QCheckBox::indicator{{
            border-radius: 3px;
        }}
        QRadioButton::indicator{{
            border-radius: 7px;
        }}
        QCheckBox::indicator:checked{{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/check_indicator.svg);
        }}
        QRadioButton::indicator:checked{{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/radio_indicator.svg);
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{{
            border: 1px solid #8EA3FF;
        }}
        QPushButton#pushButton_right_menu,#pushButton_play,#pushButton_open_folder,#pushButton_open_nfo,#pushButton_show_hide_logs,#pushButton_save_failed_list,#pushButton_tree_clear,#pushButton_clear_logs{{
            background-color: rgba(181, 181, 181, 0);
            border-radius:10px;
            border: 0px solid rgba(0, 0, 0, 80);
        }}
        QPushButton:hover#pushButton_right_menu,:hover#pushButton_play,:hover#pushButton_open_folder,:hover#pushButton_open_nfo,:hover#pushButton_show_hide_logs,:hover#pushButton_save_failed_list,:hover#pushButton_tree_clear,:hover#pushButton_clear_logs{{
            background-color: rgba(181, 181, 181, 120);
        }}
        QPushButton:pressed#pushButton_right_menu,:pressed#pushButton_play,:pressed#pushButton_open_folder,:pressed#pushButton_open_nfo,:pressed#pushButton_show_hide_logs,:pressed#pushButton_save_failed_list,:pressed#pushButton_tree_clear,:pressed#pushButton_clear_logs{{
            background-color: rgba(150, 150, 150, 120);
        }}
        QPushButton#pushButton_field_tips_nfo{{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #6684FF;
            border: 1px solid #6684FF;
        }}
        QPushButton:pressed#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #4C6EE0;
            border: 1px solid #4C6EE0;
        }}
        QPushButton#pushButton_scrape_note{{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_scrape_note{{
            color: #E5E7EB;
            background: #253140;
            border: 1px solid #566374;
        }}
        QPushButton:pressed#pushButton_scrape_note{{
            color: #E5E7EB;
            background: #2B3A4C;
            border: 1px solid #566374;
        }}
        QPushButton#pushButton_save_new_config,#pushButton_save_new_config_tool,#pushButton_init_config,#pushButton_init_config_tool,#pushButton_success_list_close,#pushButton_success_list_save,#pushButton_success_list_clear,#pushButton_show_tips_close,#pushButton_nfo_close,#pushButton_nfo_save,#pushButton_show_pic_actor,#pushButton_add_actor_pic,#pushButton_add_actor_info,#pushButton_add_actor_pic_kodi,#pushButton_del_actor_folder,#pushButton_move_mp4,#pushButton_select_file,#pushButton_actor_db_pick_nfo_dir,#pushButton_actor_db_sync_aliases,#pushButton_select_local_library,#pushButton_select_netdisk_path,#pushButton_select_localdisk_path,#pushButton_creat_symlink,#pushButton_find_missing_number,#pushButton_select_thumb,#pushButton_start_single_file,#pushButton_select_file_clear_info,#pushButton_add_sub_for_all_video,#pushButton_view_failed_list,#pushButton_select_media_folder,#pushButton_select_media_folder_setting_page,#pushButton_select_data_dir,#pushButton_select_softlink_folder,#pushButton_select_sucess_folder,#pushButton_select_failed_folder,#pushButton_view_success_file,#pushButton_select_subtitle_folder,#pushButton_select_actor_photo_folder,#pushButton_select_gfriends_local,#pushButton_select_actor_info_db,#pushButton_select_config_folder,#pushButton_add_all_extrafanart_copy,#pushButton_del_all_extrafanart_copy,#pushButton_add_all_extras,#pushButton_del_all_extras,#pushButton_add_all_theme_videos,#pushButton_del_all_theme_videos,#pushButton_check_and_clean_files,#pushButton_search_by_number,#pushButton_search_by_url,#pushButton_cover_backfill_start{{
            font-size:14px;
            background-color: rgba(220, 220,220, 50);
            border-color:black;
            border-width:8px;
            border-radius:20px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_show_pic_actor,:hover#pushButton_add_actor_pic,:hover#pushButton_add_actor_info,:hover#pushButton_add_actor_pic_kodi,:hover#pushButton_del_actor_folder,:hover#pushButton_add_sub_for_all_video,:hover#pushButton_view_failed_list,:hover#pushButton_scraper_failed_list,:hover#pushButton_select_media_folder,:hover#pushButton_select_media_folder_setting_page,:hover#pushButton_select_data_dir,:hover#pushButton_select_softlink_folder,:hover#pushButton_select_sucess_folder,:hover#pushButton_select_failed_folder,:hover#pushButton_view_success_file,:hover#pushButton_select_subtitle_folder,:hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_gfriends_local,:hover#pushButton_select_actor_info_db,:hover#pushButton_select_config_folder,:hover#pushButton_add_all_extrafanart_copy,:hover#pushButton_del_all_extrafanart_copy,:hover#pushButton_add_all_extras,:hover#pushButton_del_all_extras,:hover#pushButton_add_all_theme_videos,:hover#pushButton_del_all_theme_videos,:hover#pushButton_check_and_clean_files,:hover#pushButton_search_by_number,:hover#pushButton_search_by_url{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_show_pic_actor,:pressed#pushButton_add_actor_pic,:pressed#pushButton_add_actor_info,:pressed#pushButton_add_actor_pic_kodi,:pressed#pushButton_del_actor_folder,:pressed#pushButton_add_sub_for_all_video,:pressed#pushButton_view_failed_list,:pressed#pushButton_scraper_failed_list,:pressed#pushButton_select_media_folder,:pressed#pushButton_select_media_folder_setting_page,:pressed#pushButton_select_data_dir,:pressed#pushButton_select_softlink_folder,:pressed#pushButton_select_sucess_folder,:pressed#pushButton_select_failed_folder,:pressed#pushButton_view_success_file,:pressed#pushButton_select_subtitle_folder,:pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_gfriends_local,:pressed#pushButton_select_actor_info_db,:pressed#pushButton_select_config_folder,:pressed#pushButton_add_all_extrafanart_copy,:pressed#pushButton_del_all_extrafanart_copy,:pressed#pushButton_add_all_extras,:pressed#pushButton_del_all_extras,:pressed#pushButton_add_all_theme_videos,:pressed#pushButton_del_all_theme_videos,:pressed#pushButton_check_and_clean_files,:pressed#pushButton_search_by_number,:pressed#pushButton_search_by_url{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_save_config,#pushButton_save_config_tool,#pushButton_nfo_lib_save,#pushButton_nfo_lib_batch_save,#pushButton_nfo_lib_crop{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:25px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_save_config,:hover#pushButton_save_config_tool,:hover#pushButton_save_new_config,:hover#pushButton_save_new_config_tool,:hover#pushButton_init_config,:hover#pushButton_init_config_tool,:hover#pushButton_success_list_close,:hover#pushButton_success_list_save,:hover#pushButton_success_list_clear,:hover#pushButton_show_tips_close,:hover#pushButton_nfo_close,:hover#pushButton_nfo_save,:hover#pushButton_nfo_lib_save,:hover#pushButton_nfo_lib_batch_save,:hover#pushButton_nfo_lib_crop{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_save_config,:pressed#pushButton_save_config_tool,:pressed#pushButton_save_new_config,:pressed#pushButton_save_new_config_tool,:pressed#pushButton_init_config,:pressed#pushButton_init_config_tool,:pressed#pushButton_success_list_close,:pressed#pushButton_success_list_save,:pressed#pushButton_success_list_clear,pressed#pushButton_show_tips_close,:pressed#pushButton_nfo_close,:pressed#pushButton_nfo_save,pressed#pushButton_nfo_lib_save,pressed#pushButton_nfo_lib_batch_save,pressed#pushButton_nfo_lib_crop{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_start_cap,#pushButton_start_cap2,#pushButton_check_net,#pushButton_scraper_failed_list{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:20px;
            padding: 2px, 2px;
            font-weight:bold;
        }}
        QPushButton:hover#pushButton_start_cap,:hover#pushButton_start_cap2,:hover#pushButton_check_net,:hover#pushButton_move_mp4,:hover#pushButton_select_file,:hover#pushButton_actor_db_pick_nfo_dir,:hover#pushButton_actor_db_sync_aliases,:hover#pushButton_select_local_library,:hover#pushButton_select_netdisk_path,:hover#pushButton_select_localdisk_path,:hover#pushButton_creat_symlink,:hover#pushButton_find_missing_number,:hover#pushButton_select_thumb,:hover#pushButton_start_single_file,:hover#pushButton_select_file_clear_info,:hover#pushButton_cover_backfill_start{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_start_cap,:pressed#pushButton_start_cap2,:pressed#pushButton_check_net,:pressed#pushButton_move_mp4,:pressed#pushButton_select_file,:pressed#pushButton_actor_db_pick_nfo_dir,:pressed#pushButton_actor_db_sync_aliases,:pressed#pushButton_select_local_library,:pressed#pushButton_select_netdisk_path,:pressed#pushButton_select_localdisk_path,:pressed#pushButton_creat_symlink,:pressed#pushButton_find_missing_number,:pressed#pushButton_select_thumb,:pressed#pushButton_start_single_file,:press#pushButton_select_file_clear_info,:pressed#pushButton_cover_backfill_start{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:12px;
            font-weight:bold;
        }}
        QSlider::groove:horizontal{{
            height: 6px;
            border-radius: 3px;
            background: #2F3A46;
        }}
        QSlider::sub-page:horizontal{{
            border-radius: 3px;
            background: #6684FF;
        }}
        QSlider::add-page:horizontal{{
            border-radius: 3px;
            background: #2F3A46;
        }}
        QSlider::handle:horizontal{{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            border: 2px solid #6684FF;
            background: #F8FAFC;
        }}
        QSlider::handle:horizontal:hover{{
            border: 2px solid #8EA3FF;
            background: #FFFFFF;
        }}
        QComboBox{{
            combobox-popup: 0;
            font-size:13px;
            color: white;
            background:#18222D;
            border: 1px solid #2F3A46;
            border-radius: 8px;
            padding: 3px 30px 3px 8px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 26px;
            border-left: 1px solid #2F3A46;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #1D2834;
        }}
        QComboBox::drop-down:hover {{
            background: #243244;
        }}
        QComboBox::down-arrow {{
            image: url(resources/Img/chevron_down_dark.svg);
            width: 14px;
            height: 14px;
        }}

        QComboBox QAbstractItemView {{
            color:white;
            background: #1F272F;
            border: 1px solid #2F3A46;
            selection-color:white;
            selection-background-color: #6684FF;
            outline: 0;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 24px;
            padding: 4px 8px;
            color: #E5E7EB;
        }}
        QComboBox QAbstractItemView::item:selected {{
            color: #FFFFFF;
            background: #6684FF;
        }}
        {build_scrollbar_style(True)}
        QProgressBar::chunk{{
            background-color: #5777FF;
            width: 3px; /*区块宽度*/
            margin: 0px;
        }}
        """)
    )
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(True))
    apply_nfo_lib_top_button_style(self, True)
