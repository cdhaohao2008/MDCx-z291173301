"""回归：主界面缩略图/封面图支持 gif 动图展示。

覆盖：
- 图片加载器能认出多帧动图（gif）并在预览结果里带回源路径与动图标记
- 静态图不会被误判成动图
- 主界面按动图标记改用 QMovie 播放，且切回静态图时动图被停掉
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


def _make_gif(path, frames: int = 4, size: tuple[int, int] = (120, 90)) -> str:
    """写一个多帧 gif。"""
    images = [Image.new("RGB", size, (index * 50 % 255, 100, 200)) for index in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
    return str(path)


def _make_jpg(path) -> str:
    Image.new("RGB", (120, 90), (10, 20, 30)).save(path, quality=90)
    return str(path)


def test_is_animated_image_distinguishes_gif_and_jpg(tmp_path):
    from mdcx.image import is_animated_image

    gif = tmp_path / "thumb.gif"
    _make_gif(gif)
    jpg = tmp_path / "thumb.jpg"
    _make_jpg(jpg)

    assert is_animated_image(gif) is True
    assert is_animated_image(jpg) is False


def test_loader_reports_animated_flag_and_source_path(tmp_path):
    """加载器要在预览结果里带回源路径与动图标记，界面层才知道要不要放 QMovie。"""
    from mdcx.image import PreviewImageLoader

    gif = tmp_path / "thumb.gif"
    _make_gif(gif)
    jpg = tmp_path / "poster.jpg"
    _make_jpg(jpg)

    loader = PreviewImageLoader()
    try:
        gif_result = loader._load_one(gif, poster=False)
        assert gif_result[0] is True
        assert gif_result[5] == str(gif)
        assert gif_result[6] is True

        jpg_result = loader._load_one(jpg, poster=True)
        assert jpg_result[0] is True
        assert jpg_result[5] == str(jpg)
        assert jpg_result[6] is False
    finally:
        loader.shutdown()


def test_placeholder_result_has_safe_shape():
    from mdcx.image import _preview_placeholder

    placeholder = _preview_placeholder(True)
    assert placeholder[0] is False
    assert len(placeholder) == 7
    assert placeholder[5] is None
    assert placeholder[6] is False


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import window_ops as window_ops_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(window_ops_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(window_ops_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)

    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    from PyQt6.QtCore import QTimer

    for timer in window.findChildren(QTimer):
        timer.stop()
    window.show()
    yield window
    window.close()


def _thumb_preview(path: str, animated: bool) -> list:
    pixmap = QPixmap.fromImage(QImage(120, 90, QImage.Format.Format_RGB32))
    return [True, pixmap, "Local: 120*90", 328, 220, path, animated]


def test_main_thumb_plays_gif_with_movie(win, tmp_path):
    """动图走 QMovie 播放，缩略图控件上挂的就是这个 movie。"""
    gif = tmp_path / "thumb.gif"
    _make_gif(gif)

    win.resize_label_and_setpixmap(None, _thumb_preview(str(gif), True))

    assert "thumb" in win._preview_movies
    movie = win._preview_movies["thumb"]
    assert win.Ui.label_thumb.movie() is movie
    assert movie.isValid()


def test_main_thumb_switch_back_to_static_stops_movie(win, tmp_path):
    """切回静态图时动图必须停掉、控件恢复成静态 pixmap。"""
    gif = tmp_path / "thumb.gif"
    _make_gif(gif)
    jpg = tmp_path / "thumb.jpg"
    _make_jpg(jpg)

    win.resize_label_and_setpixmap(None, _thumb_preview(str(gif), True))
    assert "thumb" in win._preview_movies

    win.resize_label_and_setpixmap(None, _thumb_preview(str(jpg), False))
    assert "thumb" not in win._preview_movies
    assert win.Ui.label_thumb.movie() is None
    assert not win.Ui.label_thumb.pixmap().isNull()


def test_cover_toggle_off_stops_movie(win, tmp_path):
    """关掉封面显示时动图也要停，避免在占位文本上继续播动画。"""
    gif = tmp_path / "thumb.gif"
    _make_gif(gif)
    win.Ui.checkBox_cover.setChecked(True)
    win.resize_label_and_setpixmap(None, _thumb_preview(str(gif), True))
    assert "thumb" in win._preview_movies

    win.Ui.checkBox_cover.setChecked(False)
    win.checkBox_cover_clicked()

    assert "thumb" not in win._preview_movies
    assert win.Ui.label_thumb.movie() is None
