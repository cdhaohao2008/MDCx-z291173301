"""设置页「选择目录」按钮组（软链接 / 成功 / 失败 / 数据 / 字幕 / 演员图片 / GFriends 本地 / 同步 / 配置目录 / 演员信息库）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

from pathlib import Path

from mdcx.config.manager import manager
from mdcx.signals import signal_qt
from mdcx.utils import get_current_time


class FolderSelectMixin:
    # region 设置页
    # region 选择目录
    # 设置-目录-软链接目录-点选择目录
    def pushButton_select_softlink_folder_clicked(self):
        from .tool_handlers import pushButton_select_softlink_folder_clicked

        pushButton_select_softlink_folder_clicked(self)

    # 设置-目录-成功输出目录-点选择目录
    def pushButton_select_sucess_folder_clicked(self):
        from .tool_handlers import pushButton_select_sucess_folder_clicked

        pushButton_select_sucess_folder_clicked(self)

    # 设置-目录-失败输出目录-点选择目录
    def pushButton_select_failed_folder_clicked(self):
        from .tool_handlers import pushButton_select_failed_folder_clicked

        pushButton_select_failed_folder_clicked(self)

    # 设置-目录-数据存放目录-点选择目录
    def pushButton_select_data_dir_clicked(self):
        from .tool_handlers import pushButton_select_data_dir_clicked

        pushButton_select_data_dir_clicked(self)

    # 设置-字幕-字幕文件目录-点选择目录
    def pushButton_select_subtitle_folder_clicked(self):
        from .tool_handlers import pushButton_select_subtitle_folder_clicked

        pushButton_select_subtitle_folder_clicked(self)

    # 设置-头像-头像文件目录-点选择目录
    def pushButton_select_actor_photo_folder_clicked(self):
        from .tool_handlers import pushButton_select_actor_photo_folder_clicked

        pushButton_select_actor_photo_folder_clicked(self)

    # 设置-演员-Gfriends本地仓库-点选择目录
    def pushButton_select_gfriends_local_clicked(self):
        from .tool_handlers import pushButton_select_gfriends_local_clicked

        pushButton_select_gfriends_local_clicked(self)

    # 设置-演员-Gfriends本地仓库-点更新
    def pushButton_sync_gfriends_clicked(self):
        from .tool_handlers import pushButton_sync_gfriends_clicked

        pushButton_sync_gfriends_clicked(self)

    # 设置-其他-配置文件目录-点选择目录
    def pushButton_select_config_folder_clicked(self):
        p = self._get_select_folder_path(self.Ui.lineEdit_config_folder)
        if not p:
            return
        p = Path(p)
        if p.is_dir() and p != manager.data_folder:
            manager.list_configs()
            config_path = p / "config.json"
            manager.path = config_path
            if config_path.is_file():
                temp_dark = self.dark_mode
                temp_window_radius = self.window_radius
                self.load_config()
                if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                    self.show_flag = True
                    self._windows_auto_adjust()
            else:
                self.Ui.lineEdit_config_folder.setText(str(p))
                self.pushButton_save_config_clicked()
            signal_qt.show_scrape_info(f"💡 目录已切换！{get_current_time()}")

    # 设置-演员-补全信息-演员信息数据库-选择文件按钮
    def pushButton_select_actor_info_db_clicked(self):
        from .tool_handlers import pushButton_select_actor_info_db_clicked

        pushButton_select_actor_info_db_clicked(self)
