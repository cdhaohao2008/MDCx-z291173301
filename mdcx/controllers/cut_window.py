import os
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton

from ..base.image import add_mark_thread
from ..config.enums import DownloadableFile
from ..config.manager import manager
from ..config.models import MarkType
from ..core.file import get_file_info_v2
from ..models.mosaic import has_leak_mark, has_umr_mark, has_uncensored_mark, is_censored_mosaic
from ..ui_theme import get_theme_tokens
from ..utils import executor
from ..utils.file import delete_file_sync
from ..views.posterCutTool import Ui_Dialog_cut_poster

if TYPE_CHECKING:
    from ..models.model_types import FileInfo
    from .main_window.main_window import MyMAinWindow


class DraggableButton(QPushButton):
    def __init__(
        self,
        title,
        parent,
        cutwindow,
    ):
        super().__init__(title, parent)
        self.iniDragCor = [0, 0]
        self.cutwindow = cutwindow
        self._dragging = False

    def mousePressEvent(self, e):
        if e is None:
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        self.iniDragCor[0] = pos.x()
        self.iniDragCor[1] = pos.y()
        self._dragging = True
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        e.accept()

    def mouseMoveEvent(self, e):
        if e is None:
            return
        if not self._dragging or not e.buttons() & Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return
        pos = e.position().toPoint()
        x = pos.x() - self.iniDragCor[0]
        y = pos.y() - self.iniDragCor[1]
        cor = QPoint(x, y)
        target = self.mapToParent(cor)
        rect = self.cutwindow._constrain_crop_rect(QRect(target.x(), target.y(), self.width(), self.height()))
        self.move(rect.topLeft())  # 需要maptoparent一下才可以的,否则只是相对位置。

        # 更新实际裁剪位置
        self.cutwindow.getRealPos()
        e.accept()

    def mouseReleaseEvent(self, e):
        if e and e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            e.accept()


class CutWindow(QDialog):
    # 裁剪任务完成（后台线程发出，主线程收）：载荷 True/False/None 仅用于重启用按钮，结果本身无人消费
    cut_task_done = pyqtSignal(object)

    # ==================== 布局常量（.ui 全是绝对几何，窗口尺寸变化只能靠这里重排）====================
    # 设计尺寸 1000x600 = 左侧图片区 800 + 右侧面板 200，图片区下方是 60 高的底部滑块条
    _SIDE_W = 200  # 右侧面板宽（固定，贴窗口右缘）
    _BAR_H = 60  # 底部滑块条高
    _BAR_DESIGN_W = 800  # 底部滑块条设计宽，富余宽度由左右两个滑块对半分
    _BAR_MARGIN_R = 9  # 右组滑块距右缘（照搬 .ui 设计值）
    _BAR_MIN_GAP = 40  # 左右两组滑块之间的最小间隙
    _BAR_MIN_SLIDER_W = 120  # 滑块最小宽（窗口被压得很窄时）
    _MIN_WIN_W = 640  # 窗口最小宽
    _MIN_WIN_H = 500  # 窗口最小高（低于此值右侧面板的按钮会压到水印选项上）
    _SIDE_BTN_BOTTOM = 10  # 右侧面板动作按钮距底
    _SIDE_BTN_GAP = 10  # 右侧面板动作按钮彼此间距

    def __init__(self, parent: MyMAinWindow):
        # 独立顶层窗口（不挂 owner）：主窗口最小化/隐藏/切到托盘都不牵连本窗口，
        # 本窗口最小化/最大化也不动主窗口。parent 只作为 Python 引用留着取配置与发信号。
        super().__init__()
        self.Ui = Ui_Dialog_cut_poster()  # 实例化 Ui
        self.Ui.setupUi(self)  # 初始化Ui
        self.main_window = parent
        self._nfo_lib_source: Path | None = None  # 信息管理页发起的裁剪来源（nfo 路径）；None 表示主流程
        self.m_drag = False  # 允许拖动
        self.m_DragPosition = None  # 拖动位置
        self.show_w = self.Ui.label_backgroud_pic.width()  # 图片显示区域的宽高
        self.show_h = self.Ui.label_backgroud_pic.height()  # 图片显示区域的宽高
        self.keep_side = "height"
        self.pic_new_w = self.show_w
        self.pic_new_h = self.show_h
        self.pic_w = self.show_w
        self.pic_h = self.show_h
        self._source_pixmap: QPixmap | None = None  # 原图缓存：窗口缩放时直接复用，不再读盘
        self._last_layout_size = QSize()  # 上次重排时的窗口尺寸，用来跳过无谓重排
        self.pushButton_select_cutrange = DraggableButton("拖动选择裁剪范围", self.Ui.label_backgroud_pic, self)
        self.pushButton_select_cutrange.setObjectName("pushButton_select_cutrange")
        self.pushButton_select_cutrange.setGeometry(QRect(420, 0, 379, 539))
        self.pushButton_select_cutrange.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.pushButton_select_cutrange.setAcceptDrops(True)
        self.Ui.horizontalSlider_left.setRange(1, 10000)
        self.Ui.horizontalSlider_right.setRange(1, 10000)
        self.set_style()
        self._init_window_state()
        self.Ui.horizontalSlider_left.valueChanged.connect(self.change_postion_left)
        self.Ui.horizontalSlider_right.valueChanged.connect(self.change_postion_right)
        self.Ui.pushButton_open_pic.clicked.connect(self.open_image)
        self.Ui.pushButton_cut_close.clicked.connect(self.do_cut_and_close)
        self.Ui.pushButton_cut.clicked.connect(self.do_cut)
        self.Ui.pushButton_close.clicked.connect(self.close)
        self.cut_task_done.connect(self._on_cut_task_done)
        self._relayout(force=True)  # 建立基准布局（设计尺寸下与 .ui 逐像素一致）
        self.showimage()

    def _init_window_state(self):
        """窗口能力：最小化/最大化按钮、Esc 关闭、最小尺寸。"""
        # 摘掉工具窗/无边框标记，补上最小化与最大化按钮（关闭按钮 QDialog 自带）。
        # 窗口类型强制为 Window：不带 Dialog 位才不会成为主窗口的附属窗，
        # 否则主窗口最小化/隐藏时 Windows 会连带把本窗口一起收走。
        flags = self.windowFlags() & ~(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setWindowFlags(
            flags
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setModal(False)
        # 独立窗口后本窗口就成了"最后一扇可见主窗口"，默认的 WA_QuitOnClose 会让
        # 关掉裁剪窗直接退出整个应用（主窗口收进托盘时尤其明显），必须关掉。
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        # 限死最小尺寸：窗口再小也不会把右侧面板按钮压到水印选项上、底栏标签裁掉
        self.setMinimumSize(self._MIN_WIN_W, self._MIN_WIN_H)
        # Esc 关闭要求窗口自己能拿到键盘焦点（焦点落在子控件上时按键事件也会冒泡上来）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _relayout(self, force: bool = False):
        """按当前窗口尺寸重排三个区域，图片与裁剪框同步等比放大。

        裁剪窗的 .ui 全是绝对几何、没有布局管理器，窗口放大后各控件不会自己跟位，
        这里统一按窗口当前尺寸重排：右侧面板固定宽贴右缘并铺满高、底栏贴图片区下缘、
        图片区吃掉剩余空间；图片按新的显示区重新等比缩放，裁剪框按相对位置还原，
        用户已经选好的裁剪范围跟着图片一起放大。
        """
        if not force and self._last_layout_size == self.size():
            return  # 尺寸没变（如最小化）不重排，避免白做一次图片缩放
        win_w = max(int(self.width()), self._MIN_WIN_W)
        win_h = max(int(self.height()), self._MIN_WIN_H)
        side_w = self._SIDE_W
        left_w = max(1, win_w - side_w)  # 左侧图片区宽（吃掉除右侧面板外的全部宽度）
        img_h = max(1, win_h - self._BAR_H)  # 左侧图片区高（吃掉除底部滑块条外的全部高度）

        self.Ui.widget.setGeometry(win_w - side_w, 0, side_w, win_h)  # 右侧面板：贴右上缘
        self._layout_side_buttons(side_w, win_h)
        self.Ui.widget_cutimage.setGeometry(0, 0, left_w, img_h)  # 左侧图片区
        self.Ui.widget_2.setGeometry(0, img_h, left_w, self._BAR_H)  # 底部滑块条
        self._layout_bottom_bar(left_w)

        self.show_w = left_w  # 图片显示区域宽高，_fit_image 按它等比缩放
        self.show_h = img_h
        self._fit_image()
        self._last_layout_size = QSize(win_w, win_h)

    def _layout_side_buttons(self, side_w: int, win_h: int):
        """右侧面板三个动作按钮贴底排布，间距照搬 .ui 设计值。

        上半部分的尺寸/水印标签与选项固定在顶部不动，窗口拉高时多出来的高度
        落在水印选项与动作按钮之间；动作按钮始终贴底，还原后与 .ui 逐像素一致。
        """
        btn_x, btn_w = 30, 141
        if side_w < btn_x + btn_w:  # 面板被压窄（正常最小宽下不会发生）时水平居中
            btn_w = max(60, side_w - btn_x * 2)
            btn_x = (side_w - btn_w) // 2
        close_h, cut_h, cut_close_h = 40, 40, 50  # 三个按钮的高度
        y = win_h - self._SIDE_BTN_BOTTOM - close_h
        self.Ui.pushButton_close.setGeometry(btn_x, y, btn_w, close_h)
        y -= self._SIDE_BTN_GAP + cut_h
        self.Ui.pushButton_cut.setGeometry(btn_x, y, btn_w, cut_h)
        y -= self._SIDE_BTN_GAP + cut_close_h
        self.Ui.pushButton_cut_close.setGeometry(btn_x, y, btn_w, cut_close_h)

    def _layout_bottom_bar(self, bar_w: int):
        """底部滑块条随窗口加长：宽态（最大化）两个滑块等分富余并同步右移。

        窄态（用户手动缩小窗口）改为按可用宽度压窄滑块、右组贴右缘，
        保证两组不重叠、标签不被裁掉。
        """
        left_x = 50  # 左滑块 x（设计值）
        slider_w = 311  # 滑块设计宽
        # 宽态：富余宽度对半分给左右两个滑块
        extra = max(0, (bar_w - self._BAR_DESIGN_W) // 2)
        avail = bar_w - self._BAR_MARGIN_R - left_x - self._BAR_MIN_GAP
        if 2 * (slider_w + extra) > avail:  # 窄态：两个滑块同时等宽压窄
            slider_w = max(self._BAR_MIN_SLIDER_W, avail // 2)
            extra = 0
        slider_w += extra
        right_x = bar_w - self._BAR_MARGIN_R - slider_w
        self.Ui.label_4.setGeometry(30, 10, 141, 16)
        self.Ui.horizontalSlider_left.setGeometry(left_x, 31, slider_w, 20)
        # 右组标签比滑块左移 40（照搬 .ui 设计关系），窗口变窄也不会被裁掉
        self.Ui.label_6.setGeometry(right_x - 40, 10, 131, 16)
        self.Ui.horizontalSlider_right.setGeometry(right_x, 30, slider_w, 21)

    def _fit_image(self, keep_selection: bool = True):
        """按当前显示区重新等比缩放图片，并按相对位置还原裁剪框。

        keep_selection=True（窗口缩放/最大化）时先把裁剪框按当前显示区归一化，
        缩放后再还原，保证选中范围跟着图片一起放大且指向原图同一块区域。
        """
        frac = None
        old_w, old_h = int(self.pic_new_w), int(self.pic_new_h)
        if keep_selection and old_w > 0 and old_h > 0:
            px, py, pw, ph = self.pushButton_select_cutrange.geometry().getRect()
            frac = (px / old_w, py / old_h, pw / old_w, ph / old_h)

        area_w, area_h = max(1, int(self.show_w)), max(1, int(self.show_h))
        source = self._source_pixmap
        if source is not None and not source.isNull() and self.pic_w > 0 and self.pic_h > 0:
            if self.pic_h_w_ratio <= area_h / area_w:  # 水平撑满（图片高/宽 <= 显示区高/宽）
                new_w = area_w  # 图片显示的宽度=显示区域宽度
                new_h = max(1, int(new_w * self.pic_h / self.pic_w))  # 计算出图片显示的高度
            else:  # 垂直撑满
                new_h = area_h  # 图片显示的高度=显示区域高度
                new_w = max(1, int(new_h * self.pic_w / self.pic_h))  # 计算出图片显示的宽度
            pixmap = QPixmap.scaled(
                source, new_w, new_h, aspectRatioMode=Qt.AspectRatioMode.KeepAspectRatio
            )  # 图片缩放
        else:
            # 还没打开图片：显示区即裁剪区（_constrain_crop_rect 依赖 pic_new_w/h），裁剪框照样能拖
            new_w, new_h = area_w, area_h
            pixmap = QPixmap()
        self.pic_new_w, self.pic_new_h = new_w, new_h
        # 横图（宽>高）在显示区内居中：等比缩放后四周必然留白，居中比贴左上角好看。
        # 只改显示位置，裁剪框及 pic_new_w/h 换算出的裁剪坐标都以 label 为基准，不受影响。
        offset_x = offset_y = 0
        if self.pic_w > self.pic_h:  # 未载入图片时 pic_w/pic_h 均为 0，保持原来的左上角对齐
            offset_x = max(0, (area_w - new_w) // 2)
            offset_y = max(0, (area_h - new_h) // 2)
        self.Ui.label_backgroud_pic.setGeometry(offset_x, offset_y, new_w, new_h)  # 背景区域大小位置设置
        self.Ui.label_backgroud_pic.setPixmap(pixmap)  # 背景区域显示缩放后的图片

        if frac is not None:
            rect = QRect(
                int(round(frac[0] * new_w)),
                int(round(frac[1] * new_h)),
                max(1, int(round(frac[2] * new_w))),
                max(1, int(round(frac[3] * new_h))),
            )
            self._apply_crop_rect(rect, sync_sliders=True)  # 裁剪框跟着图片一起放大
            self.getRealPos()  # 同步裁剪框在原图中的实际位置与两个滑块

    def set_style(self):
        # 控件美化 裁剪弹窗
        dark_mode = bool(getattr(self.main_window, "dark_mode", False))
        t = get_theme_tokens(dark_mode)
        self.pushButton_select_cutrange.setStyleSheet(f"""
            QPushButton#pushButton_select_cutrange {{
                color: {t["text"]};
                background-color: rgba(76, 110, 255, 34);
                border: 2px solid {t["accent"]};
                font-size: 13px;
                font-weight: normal;
            }}
            QPushButton#pushButton_select_cutrange:hover {{
                color: #FFFFFF;
                background-color: rgba(76, 110, 255, 76);
                border-color: {t["accent_hover"]};
            }}
        """)
        self.Ui.widget.setStyleSheet(f"""
            * {{
                font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
                color: {t["text"]};
            }}
            QWidget{{
                background: {t["surface_muted"]};
            }}
            QPushButton{{
                color:{t["text"]};
                font-size:14px;
                background-color:{t["surface"]};
                border: 1px solid {t["border"]};
                border-radius:20px;
                padding: 2px, 2px;
            }}
            QPushButton:hover{{
                color: white;
                background-color:{t["accent_hover"]};
                font-weight:bold;
            }}
            QPushButton:pressed{{
                background-color:{t["accent_pressed"]};
                border-color:{t["accent_pressed"]};
                font-weight:bold;
            }}
            QPushButton#pushButton_cut_close{{
                color: white;
                font-size:14px;
                background-color:{t["accent"]};
                border-radius:25px;
                padding: 2px, 2px;
            }}
            QPushButton:hover#pushButton_cut_close{{
                color: white;
                background-color:{t["accent_hover"]};
                font-weight:bold;
            }}
            QPushButton:pressed#pushButton_cut_close{{
                background-color:{t["accent_pressed"]};
                border-color:{t["accent_pressed"]};
                font-weight:bold;
            }}
            QSlider::groove:horizontal{{
                height: 6px;
                border-radius: 3px;
                background: {t["border"]};
            }}
            QSlider::sub-page:horizontal{{
                border-radius: 3px;
                background: {t["accent"]};
            }}
            QSlider::add-page:horizontal{{
                border-radius: 3px;
                background: {t["border"]};
            }}
            QSlider::handle:horizontal{{
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                border: 2px solid {t["accent"]};
                background: {t["window"]};
            }}
            """)

    def change_postion_left(self):
        # 滑块表示裁剪框高度占当前显示图片高度的比例，拖动时尽量保持中心点不变。
        slider_value = self.Ui.horizontalSlider_left.value()
        # 当前裁剪框位置. 左上角坐标 + 尺寸
        x, y, width, height = self.pushButton_select_cutrange.geometry().getRect()
        if x is None or y is None or width is None or height is None:
            return
        center_y = y + height / 2
        height = self._slider_to_size(slider_value, self.pic_new_h)
        rect = self._constrain_crop_rect(QRect(x, int(round(center_y - height / 2)), width, height))
        self._apply_crop_rect(rect)
        self.getRealPos()  # 显示裁剪框实际位置

    def change_postion_right(self):
        # 滑块表示裁剪框宽度占当前显示图片宽度的比例，拖动时尽量保持中心点不变。
        slider_value = self.Ui.horizontalSlider_right.value()
        x, y, width, height = self.pushButton_select_cutrange.geometry().getRect()
        if x is None or y is None or width is None or height is None:
            return
        center_x = x + width / 2
        width = self._slider_to_size(slider_value, self.pic_new_w)
        rect = self._constrain_crop_rect(QRect(int(round(center_x - width / 2)), y, width, height))
        self._apply_crop_rect(rect)
        self.getRealPos()  # 显示裁剪框实际位置

    def _slider_to_size(self, value: int, max_size: int) -> int:
        if max_size <= 0:
            return 1
        min_size = min(20, max_size)
        size = int(round(max_size * value / 10000))
        return max(min_size, min(size, max_size))

    def _size_to_slider(self, size: int, max_size: int) -> int:
        if max_size <= 0:
            return 1
        return max(1, min(10000, int(round(size / max_size * 10000))))

    def _constrain_crop_rect(self, rect: QRect) -> QRect:
        max_w = max(1, int(self.pic_new_w))
        max_h = max(1, int(self.pic_new_h))
        width = max(1, min(rect.width(), max_w))
        height = max(1, min(rect.height(), max_h))
        max_x = max_w - width
        max_y = max_h - height
        x = max(0, min(rect.x(), max_x))
        y = max(0, min(rect.y(), max_y))
        return QRect(x, y, width, height)

    def _apply_crop_rect(self, rect: QRect, sync_sliders: bool = False):
        rect = self._constrain_crop_rect(rect)
        self.pushButton_select_cutrange.setGeometry(rect)
        if rect.width() > 0:
            self.rect_h_w_ratio = rect.height() / rect.width()  # 更新高宽比
            self.Ui.label_cut_ratio.setText(str(f"{self.rect_h_w_ratio:.2f}"))
        if sync_sliders:
            self._sync_crop_sliders(rect)

    def _sync_crop_sliders(self, rect: QRect):
        self.Ui.horizontalSlider_left.blockSignals(True)
        self.Ui.horizontalSlider_right.blockSignals(True)
        self.Ui.horizontalSlider_left.setValue(self._size_to_slider(rect.height(), self.pic_new_h))
        self.Ui.horizontalSlider_right.setValue(self._size_to_slider(rect.width(), self.pic_new_w))
        self.Ui.horizontalSlider_left.blockSignals(False)
        self.Ui.horizontalSlider_right.blockSignals(False)

    # 打开图片选择框
    def open_image(self):
        img_path, img_type = QFileDialog.getOpenFileName(
            None, "打开图片", "", "*.jpg *.png;;All Files(*)", options=self.main_window.options
        )
        if img_path:
            self.showimage(Path(img_path))

    def _poster_path_of(self, img_path: Path, pic_name: bool) -> Path:
        """按 MDCx 命名规则推导同目录下的 poster 路径（与 showimage 原有推导一致）。"""
        poster_path = img_path.with_name("poster.jpg")
        if not pic_name and "-" in img_path.stem:  # 文件名-poster.jpg
            poster_path = img_path.with_name(
                img_path.name.replace("-fanart", "")
                .replace("-thumb", "")
                .replace("-poster", "")
                .replace(img_path.suffix, "")
                + "-poster.jpg"
            )
        return poster_path

    def _prefer_larger_poster(self, img_path: Path, pic_name: bool) -> Path:
        """「封面替换缩略图」勾选时，裁剪改用更大的 poster 大尺寸图作为原始图。

        to_cut 会把未裁剪的完整原图直接写成 thumb/fanart，所以把 img_path 换成
        poster 大图后，裁剪保存出来的 thumb/fanart 自然也是大尺寸图。

        判据与 core/image.py 的替换逻辑保持一致：poster 的**宽和高都严格大于**
        当前图才换，不能用像素面积代替 —— poster 1000x2000 面积大于 1500x1000，
        但宽度更窄，拿它当「大缩略图」反而会让缩略图变小。
        """
        if DownloadableFile.POSTER_REPLACE_THUMB not in manager.config.download_files:
            return img_path
        try:
            poster_path = self._poster_path_of(img_path, pic_name)
            if not poster_path.exists() or poster_path == img_path:
                return img_path
            with Image.open(img_path) as img:
                img_w, img_h = img.size
            with Image.open(poster_path) as poster:
                poster_w, poster_h = poster.size
            if not (poster_w > img_w and poster_h > img_h):
                return img_path
        except Exception:
            return img_path
        return poster_path

    # 显示要裁剪的图片
    def showimage(self, img_path: Path | None = None, json_data: FileInfo | None = None):
        self.Ui.label_backgroud_pic.setText(" ")  # 清空背景
        # 初始化数据
        self.Ui.checkBox_add_sub.setChecked(False)
        self.Ui.radioButton_add_no.setChecked(True)
        self.Ui.radioButton_add_no_2.setChecked(True)
        self.pic_h_w_ratio = 1.5
        self.rect_h_w_ratio = 536.6 / 379  # 裁剪框默认高宽比
        self.show_image_path = img_path
        self._source_pixmap = None  # 原图缓存：窗口缩放时直接复用，不再重复读盘
        self.cut_thumb_path = None  # 裁剪后的thumb路径
        self.cut_poster_path = None  # 裁剪后的poster路径
        self.cut_fanart_path = None  # 裁剪后的fanart路径
        self._nfo_lib_source = None  # 每次打开裁剪窗都回到主流程，信息管理页发起时由调用方在 showimage 之后设置
        self.Ui.label_origin_size.setText(str(f"{self.pic_w!s}, {self.pic_h!s}"))  # 显示原图尺寸

        # 获取水印设置
        poster_mark = manager.config.poster_mark
        mark_type = manager.config.mark_type
        pic_name = manager.config.pic_simple_name

        # 显示图片及水印情况
        if img_path and os.path.exists(img_path):
            # 「封面替换缩略图」：勾选且 poster 更大时，裁剪直接以 poster 大尺寸图为原图
            img_path = self._prefer_larger_poster(img_path, pic_name)
            self.show_image_path = img_path
            # 显示背景
            pic = QPixmap(img_path.as_posix())
            self._source_pixmap = pic  # 缓存原图，窗口最大化/缩放时按新尺寸重新缩放
            self.pic_w = max(pic.width(), 1)
            self.pic_h = max(pic.height(), 1)
            self.Ui.label_origin_size.setText(str(f"{self.pic_w!s}, {self.pic_h!s}"))  # 显示原图尺寸
            self.pic_h_w_ratio = self.pic_h / self.pic_w if self.pic_w > 0 else 1.5  # 原图高宽比
            # abc = int((self.rect_h_w_ratio - 1) * 10000)
            # self.Ui.horizontalSlider_left.setValue(abc)  # 裁剪框左侧调整条的值（最大10000）
            # self.Ui.horizontalSlider_right.setValue(10000 - abc)  # 裁剪框右侧调整条的值（最大10000）和左侧的值反过来

            # 背景图片等比缩放并显示（keep_selection=False：下面会按新图重设默认裁剪框）
            self._fit_image(keep_selection=False)

            # 获取nfo文件名，用来设置裁剪后图片名称和裁剪时的水印状态
            img_folder = img_path.parent
            img_name = img_path.stem

            # 如果没有json_data，则通过图片文件名或nfo文件名获取，目的是用来获取水印
            if not json_data:
                # 根据图片文件名获取获取水印情况
                temp_path = img_path
                # 如果图片没有番号信息，则根据nfo文件名获取水印情况
                if "-" not in img_name:
                    file_list = os.listdir(img_folder)
                    for each in file_list:
                        if ".nfo" in each:
                            temp_path = img_folder / each
                            break
                json_data = executor.run(get_file_info_v2(temp_path, copy_sub=False))

            self.setWindowTitle(json_data.number + " 封面图片裁剪")  # 设置窗口标题

            # 获取水印信息
            has_sub = json_data.has_sub
            mosaic = json_data.mosaic
            definition = json_data.definition
            # 获取裁剪后的的poster和thumb路径
            poster_path = self._poster_path_of(img_path, pic_name)
            poster_name = poster_path.name
            thumb_path = img_path.with_name(poster_name.replace("poster.", "thumb."))
            fanart_path = img_path.with_name(poster_name.replace("poster.", "fanart."))
            self.cut_thumb_path = thumb_path  # 裁剪后的thumb路径
            self.cut_poster_path = poster_path  # 裁剪后的poster路径
            self.cut_fanart_path = fanart_path  # 裁剪后的fanart路径

            # poster添加水印
            if poster_mark:
                if definition and MarkType.HD in mark_type:
                    if definition == "4K" or definition == "UHD":
                        self.Ui.radioButton_add_4k.setChecked(True)
                    elif definition == "8K" or definition == "UHD8":
                        self.Ui.radioButton_add_8k.setChecked(True)
                if has_sub and MarkType.SUB in mark_type:
                    self.Ui.checkBox_add_sub.setChecked(True)
                if is_censored_mosaic(mosaic):
                    if MarkType.YOUMA in mark_type:
                        self.Ui.radioButton_add_censored.setChecked(True)
                elif has_umr_mark(mosaic):
                    if MarkType.UMR in mark_type:
                        self.Ui.radioButton_add_umr.setChecked(True)
                    elif MarkType.UNCENSORED in mark_type:
                        self.Ui.radioButton_add_uncensored.setChecked(True)
                elif has_leak_mark(mosaic):
                    if MarkType.LEAK in mark_type:
                        self.Ui.radioButton_add_leak.setChecked(True)
                    elif has_uncensored_mark(mosaic) and MarkType.UNCENSORED in mark_type:
                        self.Ui.radioButton_add_uncensored.setChecked(True)
                elif has_uncensored_mark(mosaic):
                    self.Ui.radioButton_add_uncensored.setChecked(True)
        # 显示裁剪框
        # 计算裁剪框大小
        if self.pic_h_w_ratio <= 1.5:  # 高宽比小时，固定高度，水平移动
            self.keep_side = "height"
            self.rect_h = self.pic_new_h  # 裁剪框的高度 = 图片缩放显示的高度
            self.rect_w = (
                int(self.rect_h / self.rect_h_w_ratio) if self.rect_h_w_ratio > 0 else self.rect_h
            )  # 计算裁剪框的宽度
            self.rect_x = self.pic_new_w - self.rect_w  # 裁剪框左上角位置的x值
            self.rect_y = 0  # 裁剪框左上角位置的y值
        else:  # 高宽比大时，固定宽度，竖向移动
            self.keep_side = "width"
            self.rect_w = self.pic_new_w  # 裁剪框的宽度 = 图片缩放显示的宽度
            self.rect_h = int(self.rect_w * self.rect_h_w_ratio)  # 计算裁剪框的高度
            self.rect_x = 0  # 裁剪框左上角的x值
            self.rect_y = int((self.pic_new_h - self.rect_h) / 2)  # 裁剪框左上角的y值（默认垂直居中）
        self._apply_crop_rect(
            QRect(self.rect_x, self.rect_y, self.rect_w, self.rect_h), sync_sliders=True
        )  # 显示裁剪框
        self.getRealPos()  # 显示裁剪框实际位置

    # 计算在原图的裁剪位置
    def getRealPos(self):
        # 边界处理
        pic_new_w = self.pic_new_w
        pic_new_h = self.pic_new_h
        px, py, pw, ph = self.pushButton_select_cutrange.geometry().getRect()  # 获取裁剪框大小位置
        if px is None or py is None or pw is None or ph is None:
            return 0, 0, 0, 0
        rect = self._constrain_crop_rect(QRect(px, py, pw, ph))
        if rect != self.pushButton_select_cutrange.geometry():
            self._apply_crop_rect(rect, sync_sliders=True)
        px, py, pw, ph = rect.getRect()

        # 显示坐标按图片缩放比例换算到原图坐标，保证界面选区和实际裁剪范围一致。
        scale_x = self.pic_w / pic_new_w if pic_new_w else 1
        scale_y = self.pic_h / pic_new_h if pic_new_h else 1
        self.c_x = max(0, min(self.pic_w, int(round(px * scale_x))))
        self.c_y = max(0, min(self.pic_h, int(round(py * scale_y))))
        self.c_x2 = max(0, min(self.pic_w, int(round((px + pw) * scale_x))))
        self.c_y2 = max(0, min(self.pic_h, int(round((py + ph) * scale_y))))
        c_w = self.c_x2 - self.c_x
        c_h = self.c_y2 - self.c_y

        # 显示实际裁剪位置
        self.Ui.label_cut_postion.setText(f"{self.c_x!s}, {self.c_y!s}, {self.c_x2!s}, {self.c_y2!s}")

        # 显示实际裁剪尺寸
        self.Ui.label_cut_size.setText(f"{c_w!s}, {c_h!s}")

        return self.c_x, self.c_y, self.c_x2, self.c_y2

    def _collect_mark_list(self) -> list[str]:
        """主线程采集裁剪水印选项（后台线程不可读 QWidget）。"""
        mark_list = []
        if self.Ui.radioButton_add_4k.isChecked():
            mark_list.append("4K")
        elif self.Ui.radioButton_add_8k.isChecked():
            mark_list.append("8K")
        if self.Ui.checkBox_add_sub.isChecked():
            mark_list.append("字幕")
        if self.Ui.radioButton_add_censored.isChecked():
            mark_list.append("有码")
        elif self.Ui.radioButton_add_umr.isChecked():
            mark_list.append("破解")
        elif self.Ui.radioButton_add_leak.isChecked():
            mark_list.append("流出")
        elif self.Ui.radioButton_add_uncensored.isChecked():
            mark_list.append("无码")
        return mark_list

    def do_cut_and_close(self):
        mark_list = self._collect_mark_list()
        executor.submit(self.to_cut(mark_list))
        self.close()

    def do_cut(self):
        # 重任务异步化：旧同步 executor.run 会冻住 UI 直到裁剪+水印全做完；
        # 改 submit + 禁用按钮，完成后经信号回主线程重启用（do_cut 返回值无人消费，行为不变）。
        mark_list = self._collect_mark_list()
        self.Ui.pushButton_cut.setEnabled(False)
        future = executor.submit(self.to_cut(mark_list))

        def _notify(done_future):
            try:
                result = done_future.result()
            except Exception:
                # to_cut 已知失败路径内部都记了日志；这里只兜未知异常，保持旧同步版“打 traceback”的可排查性
                self.main_window.show_log_text(traceback.format_exc())
                result = False
            try:
                self.cut_task_done.emit(result)
            except RuntimeError:
                pass  # 关窗后 emit 撞已销毁对象则丢弃（文件已落盘，结果无人消费）

        future.add_done_callback(_notify)

    def _on_cut_task_done(self, _result):
        """主线程：裁剪完成，重启用按钮。"""
        try:
            self.Ui.pushButton_cut.setEnabled(True)
        except RuntimeError:
            pass

    async def to_cut(self, mark_list: list[str]):
        img_path = self.show_image_path  # 被裁剪的图片
        thumb_path = self.cut_thumb_path  # 裁剪后的thumb路径

        # 路径为空时，跳过
        if (
            not img_path
            or not os.path.exists(img_path)
            or not thumb_path
            or not self.cut_poster_path
            or not self.cut_fanart_path
        ):
            return None
        self.main_window.img_path = img_path  # 裁剪后更新图片url，这样再次点击时才可以重新加载并裁剪

        # 裁剪poster
        img = None
        img_new_png = None
        try:
            with Image.open(img_path) as opened:
                img = opened.convert("RGB")
        except Exception:
            self.main_window.show_log_text(f"{traceback.format_exc()}\n Open Pic: {img_path}")
            return False
        try:
            img_new_png = img.crop((self.c_x, self.c_y, self.c_x2, self.c_y2))
        except Exception:
            self.main_window.show_log_text(f"{traceback.format_exc()}\n 裁剪参数异常: {img_path}")
            try:
                img.close()
            except Exception:
                pass
            return False
        try:
            if os.path.exists(self.cut_poster_path):
                delete_file_sync(self.cut_poster_path)
        except Exception as e:
            self.main_window.show_log_text(" 🔴 Failed to remove old poster!\n    " + str(e))
            try:
                img.close()
            except Exception:
                pass
            try:
                img_new_png.close()
            except Exception:
                pass
            return False
        try:
            img_new_png.save(self.cut_poster_path, quality=95, subsampling=0)
            # poster加水印
            if manager.config.poster_mark == 1:
                await add_mark_thread(self.cut_poster_path, mark_list)

            # 清理旧的thumb
            if DownloadableFile.THUMB in manager.config.download_files:
                if thumb_path != img_path:
                    if os.path.exists(thumb_path):
                        delete_file_sync(thumb_path)
                    img.save(thumb_path, quality=95, subsampling=0)
                # thumb加水印
                if manager.config.thumb_mark == 1:
                    await add_mark_thread(thumb_path, mark_list)
            else:
                thumb_path = img_path

            # 清理旧的fanart
            if DownloadableFile.FANART in manager.config.download_files:
                if self.cut_fanart_path != img_path:
                    if os.path.exists(self.cut_fanart_path):
                        delete_file_sync(self.cut_fanart_path)
                    img.save(self.cut_fanart_path, quality=95, subsampling=0)
                # fanart加水印
                if manager.config.fanart_mark == 1:
                    await add_mark_thread(self.cut_fanart_path, mark_list)
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
            if img_new_png is not None:
                try:
                    img_new_png.close()
                except Exception:
                    pass

        # 在主界面显示预览（QWidget 只能主线程操作，经信号调度）。
        # 信息管理页发起的裁剪：留在信息管理页，只刷新两张预览图，不跳主页
        # （表单不动，避免覆盖用户未保存的编辑）；主流程保持原行为。
        nfo_source = self._nfo_lib_source
        self._nfo_lib_source = None
        if nfo_source is not None:
            self.main_window.nfo_lib_images_changed.emit(str(nfo_source))
        else:
            self.main_window.change_to_mainpage.emit("")
            self.main_window.request_preview_images.emit(str(self.cut_poster_path), str(thumb_path))
        return True

    def keyPressEvent(self, event):
        """Esc 关闭裁剪窗。焦点落在子控件上时按键事件会冒泡到窗口，同样能关。"""
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def _center_on_screen(self):
        """把整扇窗口放到所在屏幕可用区域的正中央（尺寸不变）。

        以 frameGeometry 为准而不是 geometry：geometry 只是客户区，直接拿它居中会被
        顶部的标题栏顶高半个标题栏高度，看上去并没有真正居中。
        """
        if self.isMaximized() or self.isFullScreen():
            return  # 最大化/全屏时位置由系统接管
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        center = screen.availableGeometry().center()
        # 移完回读确认一次正中就收手：个别平台的首个落点会差几个像素，补一次即可；
        # 真机 Windows 一次到位，读到正中直接返回。
        for _ in range(2):
            frame = self.frameGeometry()
            if frame.center() == center:
                return
            frame.moveCenter(center)
            self.move(frame.topLeft())

    def showEvent(self, event):
        # Qt 不给隐藏窗口发 resize 事件，隐藏期间被改过的尺寸在这里补一次重排
        super().showEvent(event)
        # 每次打开都回到屏幕正中央，尺寸保持不变。
        # 延后一拍再挪：showEvent 里原生窗口刚建好，frameGeometry 的边框/标题栏尺寸还没稳定，
        # 此刻算出来的位置会差几个像素；等事件循环转一圈再定位才是精确居中。
        QTimer.singleShot(0, self._center_on_screen)
        self._relayout()

    def present(self):
        """打开/重新拉起裁剪窗。

        窗口是最小化状态时它是「可见」的，show() 会直接跳过（showEvent 也不触发），
        最小化按钮之外的入口再点一次就像没反应。这里统一先还原再显示。
        """
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()

    def resizeEvent(self, event):
        # 最大化/还原与手动拖拽改尺寸都走这里：重排控件并同步放大图片与裁剪框
        super().resizeEvent(event)
        self._relayout()

    def changeEvent(self, event):
        # 兜底某些平台上最大化不发 resize 的情况；尺寸没变时 _relayout 内部直接跳过
        super().changeEvent(event)
        if event is not None and event.type() == QEvent.Type.WindowStateChange:
            state = self.windowState()
            # Qt 最小化是 state |= WindowMinimized，不会清掉最大化位。窗口开着时最小化就会留下
            # Minimized|Maximized 这种矛盾状态，Windows 无法还原，表现为最小化按钮点了没反应。
            # 这里补一次纠正：最小化时把最大化位摘掉（纠正后条件不再成立，不会递归）。
            if state & Qt.WindowState.WindowMinimized and state & Qt.WindowState.WindowMaximized:
                self.setWindowState((state & ~Qt.WindowState.WindowMaximized) | Qt.WindowState.WindowMinimized)
            self._relayout()

    def closeEvent(self, event):
        # 裁剪窗是常驻对象（main_window 启动时创建一次，之后只反复 show），
        # 关闭时把窗口状态清回正常，否则用户最大化过一次，之后每次打开都是最大化。
        self.setWindowState(Qt.WindowState.WindowNoState)
        super().closeEvent(event)

    def mousePressEvent(self, a0):
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = True
            self.m_DragPosition = a0.globalPosition().toPoint() - self.pos()
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))  # 按下左键改变鼠标指针样式为手掌

    def mouseReleaseEvent(self, a0):
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))  # 释放左键改变鼠标指针样式为箭头

    def mouseMoveEvent(self, a0):
        if a0 is None:
            return
        if self.m_drag and self.m_DragPosition is not None and a0.buttons() & Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self.m_DragPosition)
            a0.accept()
        else:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        # self.show_traceback_log('main',e.x(),e.y())
