"""NFO 库管理页的薄转发层。

主窗只保留同名方法做入口，真正的实现仍在 nfo_library.py 的自由函数里，
这里逐个调用并把 self 传进去，行为与拆分前完全一致。"""


class NfoLibHandlersMixin:
    def pushButton_nfo_library_clicked(self):
        from .nfo_library import pushButton_nfo_library_clicked

        pushButton_nfo_library_clicked(self)

    def pushButton_nfo_lib_select_dir_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_dir_clicked

        pushButton_nfo_lib_select_dir_clicked(self)

    def pushButton_nfo_lib_select_all_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_all_clicked

        pushButton_nfo_lib_select_all_clicked(self)

    def pushButton_nfo_lib_select_none_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_none_clicked

        pushButton_nfo_lib_select_none_clicked(self)

    def pushButton_nfo_lib_refresh_clicked(self):
        from .nfo_library import pushButton_nfo_lib_refresh_clicked

        pushButton_nfo_lib_refresh_clicked(self)

    def lineEdit_nfo_lib_dir_return_pressed(self):
        from .nfo_library import lineEdit_nfo_lib_dir_return_pressed

        lineEdit_nfo_lib_dir_return_pressed(self)

    def listWidget_nfo_lib_item_clicked(self):
        from .nfo_library import listWidget_nfo_lib_item_clicked

        listWidget_nfo_lib_item_clicked(self)

    def pushButton_nfo_lib_save_clicked(self):
        from .nfo_library import pushButton_nfo_lib_save_clicked

        pushButton_nfo_lib_save_clicked(self)

    def on_nfo_lib_data_loaded(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_data_loaded

        on_nfo_lib_data_loaded(self, nfo_path_str)

    def on_nfo_lib_images_changed(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_images_changed

        on_nfo_lib_images_changed(self, nfo_path_str)

    def on_nfo_lib_save_done(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_save_done

        on_nfo_lib_save_done(self, nfo_path_str)

    def lineEdit_nfo_lib_filter_changed(self):
        from .nfo_library import lineEdit_nfo_lib_filter_changed

        lineEdit_nfo_lib_filter_changed(self)

    def pushButton_nfo_lib_crop_clicked(self):
        from .nfo_library import pushButton_nfo_lib_crop_clicked

        pushButton_nfo_lib_crop_clicked(self)

    def nfo_lib_preview_clicked(self, kind: str):
        """单击信息管理页右侧预览图（kind = poster / thumb）：弹出大图窗口。"""
        from .nfo_library import nfo_lib_preview_clicked

        nfo_lib_preview_clicked(self, kind)

    def _on_nfo_lib_preview_nfo_index_changed(self, index: int):
        from .nfo_library import _on_nfo_lib_preview_nfo_index_changed

        _on_nfo_lib_preview_nfo_index_changed(self, index)

    def pushButton_nfo_lib_batch_actor_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_actor_clicked

        pushButton_nfo_lib_batch_actor_clicked(self)

    def pushButton_nfo_lib_batch_add_tag_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_add_tag_clicked

        pushButton_nfo_lib_batch_add_tag_clicked(self)

    def pushButton_nfo_lib_batch_del_tag_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_del_tag_clicked

        pushButton_nfo_lib_batch_del_tag_clicked(self)

    def pushButton_nfo_lib_batch_series_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_series_clicked

        pushButton_nfo_lib_batch_series_clicked(self)

    def pushButton_nfo_lib_batch_save_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_save_clicked

        pushButton_nfo_lib_batch_save_clicked(self)

    def on_nfo_lib_batch_done(self, arg: str):
        from .nfo_library import on_nfo_lib_batch_done

        on_nfo_lib_batch_done(self, arg)

    def on_nfo_lib_batch_progress(self, text: str):
        from .nfo_library import on_nfo_lib_batch_progress

        on_nfo_lib_batch_progress(self, text)

    def listWidget_nfo_lib_context_menu(self, pos):
        from .nfo_library import listWidget_nfo_lib_context_menu

        listWidget_nfo_lib_context_menu(self, pos)
