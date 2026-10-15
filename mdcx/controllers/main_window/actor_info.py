"""演员资料区的按钮：补资料 / 补头像 / Kodi 头像 / 删除演员目录 / Emby 演员管理器 / 查看演员图。

与 ActorDbMixin 分开：ActorDbMixin 管的是演员数据库维护，这里管的是单个演员的资料与图片。"""


class ActorInfoMixin:
    # region 设置-演员
    # 设置-演员 补全演员信息
    def pushButton_add_actor_info_clicked(self):
        from .tool_handlers import pushButton_add_actor_info_clicked

        pushButton_add_actor_info_clicked(self)

    # 设置-演员 补全演员头像按钮
    def pushButton_add_actor_pic_clicked(self):
        from .tool_handlers import pushButton_add_actor_pic_clicked

        pushButton_add_actor_pic_clicked(self)

    # 设置-演员 补全演员头像按钮 kodi
    def pushButton_add_actor_pic_kodi_clicked(self):
        from .tool_handlers import pushButton_add_actor_pic_kodi_clicked

        pushButton_add_actor_pic_kodi_clicked(self)

    # 设置-演员 清除演员头像按钮 kodi
    def pushButton_del_actor_folder_clicked(self):
        from .tool_handlers import pushButton_del_actor_folder_clicked

        pushButton_del_actor_folder_clicked(self)

    # 工具-Emby 演员管理器
    def pushButton_emby_actor_manager_clicked(self):
        from .tool_handlers import pushButton_emby_actor_manager_clicked

        pushButton_emby_actor_manager_clicked(self)

    # 设置-演员 查看演员列表按钮
    def pushButton_show_pic_actor_clicked(self):
        from .tool_handlers import pushButton_show_pic_actor_clicked

        pushButton_show_pic_actor_clicked(self)
