import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from .engine import PRESETS, ProcessRequest, parse_target_size, process_image_path


@dataclass(frozen=True)
class ImageItem:
    path: str
    name: str
    width: int
    height: int
    size_bytes: int


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def read_image_info(path: str) -> ImageItem:
    size_bytes = os.path.getsize(path)
    with Image.open(path) as im:
        w, h = im.size
    return ImageItem(
        path=path,
        name=os.path.basename(path),
        width=int(w),
        height=int(h),
        size_bytes=int(size_bytes),
    )


def safe_output_path(out_dir: str, src_path: str, ext: str, suffix: str = "_shrink") -> str:
    base = os.path.splitext(os.path.basename(src_path))[0]
    cand = os.path.join(out_dir, f"{base}{suffix}.{ext}")
    if not os.path.exists(cand):
        return cand
    for i in range(1, 10000):
        cand2 = os.path.join(out_dir, f"{base}{suffix}_{i}.{ext}")
        if not os.path.exists(cand2):
            return cand2
    raise RuntimeError("输出文件重名过多，无法生成可用文件名")


class BatchWorker(QThread):
    progress = Signal(int, int, str)
    item_done = Signal(int, bool, str, str, int, int, int)
    finished_all = Signal(int, int)

    def __init__(self, items: List[ImageItem], req: ProcessRequest, output_dir: str, parent=None):
        super().__init__(parent)
        self._items = items
        self._req = req
        self._output_dir = output_dir

    def run(self) -> None:
        total = len(self._items)
        ok_count = 0
        fail_count = 0

        for idx, it in enumerate(self._items):
            self.progress.emit(idx, total, it.name)
            try:
                res = process_image_path(it.path, self._req)
                out_path = safe_output_path(self._output_dir, it.path, res.ext)
                with open(out_path, "wb") as f:
                    f.write(res.data)
                ok_count += 1
                self.item_done.emit(idx, True, out_path, "", int(res.width), int(res.height), int(res.size_bytes))
            except Exception as e:
                fail_count += 1
                self.item_done.emit(idx, False, "", str(e), 0, 0, 0)

        self.progress.emit(total, total, "完成")
        self.finished_all.emit(ok_count, fail_count)


class MainWindow(QMainWindow):
    COL_NAME = 0
    COL_DIM = 1
    COL_SIZE = 2
    COL_OUT = 3
    COL_STATUS = 4
    COL_REASON = 5

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PicShrink")
        self.resize(1100, 720)

        self._items: List[ImageItem] = []
        self._path_index = set()
        self._worker: Optional[BatchWorker] = None
        self._active_target_bytes: Optional[int] = None

        title = QLabel("PicShrink")
        title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)

        subtitle = QLabel("选择图片 → 设置参数 → 开始批量处理 → 查看结果")
        subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle.setProperty("subtitle", True)

        self.btn_add = QPushButton("选择图片（可多选）")
        self.btn_add.setFixedHeight(36)
        self.btn_add.clicked.connect(self.on_add)

        self.btn_remove = QPushButton("移除所选")
        self.btn_remove.setFixedHeight(36)
        self.btn_remove.clicked.connect(self.on_remove_selected)

        self.btn_clear = QPushButton("清空")
        self.btn_clear.setFixedHeight(36)
        self.btn_clear.clicked.connect(self.on_clear)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_clear)
        top.addStretch(1)

        self.cmb_preset = QComboBox()
        preset_keys = list(PRESETS.keys())
        for k in preset_keys:
            self.cmb_preset.addItem(PRESETS[k].label, k)
        self.cmb_preset.setCurrentIndex(preset_keys.index("ORIGINAL") if "ORIGINAL" in preset_keys else 0)
        self.cmb_preset.addItem("自定义…", "CUSTOM")

        self.cmb_target = QComboBox()
        self.cmb_target.setEditable(True)
        self.cmb_target.addItem("50KB", "50KB")
        self.cmb_target.addItem("100KB", "100KB")
        self.cmb_target.addItem("200KB", "200KB")
        self.cmb_target.addItem("500KB", "500KB")
        self.cmb_target.addItem("1MB", "1MB")
        self.cmb_target.addItem("2MB", "2MB")
        self.cmb_target.setCurrentIndex(-1)
        self.cmb_target.setEditText("")
        if self.cmb_target.lineEdit() is not None:
            self.cmb_target.lineEdit().setPlaceholderText("不限制（推荐），也可输入：300KB / 1.5MB")

        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItem("自动（推荐）", "AUTO")
        self.cmb_fmt.addItem("JPEG", "JPEG")
        self.cmb_fmt.addItem("PNG", "PNG")
        self.cmb_fmt.addItem("WEBP", "WEBP")

        self.cmb_policy = QComboBox()
        self.cmb_policy.addItem("优先尺寸（推荐）", "SIZE")
        self.cmb_policy.addItem("优先大小", "BYTES")
        self.cmb_policy.setCurrentIndex(0)

        self.edt_custom_w = QLineEdit()
        self.edt_custom_w.setPlaceholderText("宽")
        self.edt_custom_h = QLineEdit()
        self.edt_custom_h.setPlaceholderText("高")
        self.chk_keep_aspect = QCheckBox("保持比例（推荐）")
        self.chk_keep_aspect.setChecked(True)

        self.edt_outdir = QLineEdit()
        self.edt_outdir.setPlaceholderText("请选择输出目录")
        self.btn_outdir = QPushButton("选择目录")
        self.btn_outdir.clicked.connect(self.on_choose_outdir)

        params = QGridLayout()
        params.setHorizontalSpacing(10)
        params.setVerticalSpacing(8)

        params.addWidget(QLabel("尺寸"), 0, 0)
        params.addWidget(self.cmb_preset, 0, 1)
        params.addWidget(QLabel("目标大小"), 0, 2)
        params.addWidget(self.cmb_target, 0, 3)

        params.addWidget(QLabel("自定义尺寸"), 1, 0)
        custom_box = QHBoxLayout()
        custom_box.setSpacing(8)
        custom_box.addWidget(self.edt_custom_w)
        custom_box.addWidget(self.edt_custom_h)
        custom_box.addWidget(self.chk_keep_aspect)
        params.addLayout(custom_box, 1, 1, 1, 3)

        params.addWidget(QLabel("输出格式"), 2, 0)
        params.addWidget(self.cmb_fmt, 2, 1)
        params.addWidget(QLabel("策略"), 2, 2)
        params.addWidget(self.cmb_policy, 2, 3)

        outdir_box = QHBoxLayout()
        outdir_box.setSpacing(8)
        outdir_box.addWidget(self.edt_outdir, 1)
        outdir_box.addWidget(self.btn_outdir)
        params.addWidget(QLabel("输出目录"), 3, 0)
        params.addLayout(outdir_box, 3, 1, 1, 3)

        self.btn_start = QPushButton("开始")
        self.btn_start.setFixedHeight(36)
        self.btn_start.setProperty("primary", True)
        self.btn_start.clicked.connect(self.on_start)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setValue(0)
        self.lbl_progress = QLabel("未开始")

        runbar = QHBoxLayout()
        runbar.setSpacing(10)
        runbar.addWidget(self.btn_start)
        runbar.addWidget(self.progress, 1)
        runbar.addWidget(self.lbl_progress)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["名称", "尺寸", "大小", "输出文件", "状态", "失败原因"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_DIM, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_OUT, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_REASON, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.sync_actions)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addLayout(top)
        layout.addLayout(params)
        layout.addLayout(runbar)
        layout.addWidget(self.table, 1)

        self.setCentralWidget(root)
        self.cmb_preset.currentIndexChanged.connect(self._sync_custom_size)
        self._sync_custom_size()
        self.sync_actions()

    def _sync_custom_size(self):
        is_custom = self.cmb_preset.currentData() == "CUSTOM"
        self.edt_custom_w.setEnabled(is_custom)
        self.edt_custom_h.setEnabled(is_custom)
        self.chk_keep_aspect.setEnabled(is_custom)

    def _set_busy(self, busy: bool):
        self.btn_add.setEnabled(not busy)
        self.btn_remove.setEnabled(not busy and self._has_selection())
        self.btn_clear.setEnabled(not busy and len(self._items) > 0)
        self.btn_start.setEnabled(not busy and len(self._items) > 0)
        self.cmb_preset.setEnabled(not busy)
        self.cmb_target.setEnabled(not busy)
        self.cmb_fmt.setEnabled(not busy)
        self.cmb_policy.setEnabled(not busy)
        self._sync_custom_size()
        self.edt_outdir.setEnabled(not busy)
        self.btn_outdir.setEnabled(not busy)

    def _has_selection(self) -> bool:
        sm = self.table.selectionModel()
        return (len(sm.selectedRows()) > 0) if sm else False

    def sync_actions(self):
        if self._worker is not None and self._worker.isRunning():
            self._set_busy(True)
            return
        has_items = len(self._items) > 0
        self.btn_clear.setEnabled(has_items)
        self.btn_remove.setEnabled(has_items and self._has_selection())
        self.btn_start.setEnabled(has_items)

    def on_choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if d:
            self.edt_outdir.setText(d)

    def on_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All Files (*)",
        )
        if not paths:
            return

        new_items: List[ImageItem] = []
        for p in paths:
            if p in self._path_index:
                continue
            try:
                item = read_image_info(p)
            except Exception:
                continue
            new_items.append(item)

        if not new_items:
            return

        for item in new_items:
            self._path_index.add(item.path)
            self._items.append(item)
            self._append_row(item)

        if not self.edt_outdir.text().strip() and self._items:
            self.edt_outdir.setText(os.path.dirname(self._items[0].path))

        self.sync_actions()

    def _append_row(self, item: ImageItem):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name = QTableWidgetItem(item.name)
        name.setData(Qt.UserRole, item.path)

        size = QTableWidgetItem(f"{item.width} × {item.height}")
        size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        bytes_item = QTableWidgetItem(format_bytes(item.size_bytes))
        bytes_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        out_item = QTableWidgetItem("")
        status_item = QTableWidgetItem("未处理")
        reason_item = QTableWidgetItem("")

        self.table.setItem(row, self.COL_NAME, name)
        self.table.setItem(row, self.COL_DIM, size)
        self.table.setItem(row, self.COL_SIZE, bytes_item)
        self.table.setItem(row, self.COL_OUT, out_item)
        self.table.setItem(row, self.COL_STATUS, status_item)
        self.table.setItem(row, self.COL_REASON, reason_item)

    def on_remove_selected(self):
        sm = self.table.selectionModel()
        rows = sorted({idx.row() for idx in sm.selectedRows()}, reverse=True) if sm else []
        if not rows:
            return

        remove_paths = []
        for r in rows:
            it = self.table.item(r, self.COL_NAME)
            if it is None:
                continue
            remove_paths.append(it.data(Qt.UserRole))
            self.table.removeRow(r)

        if remove_paths:
            remove_set = set(remove_paths)
            self._items = [x for x in self._items if x.path not in remove_set]
            self._path_index.difference_update(remove_set)

        self.sync_actions()

    def on_clear(self):
        self.table.setRowCount(0)
        self._items.clear()
        self._path_index.clear()
        self.progress.setValue(0)
        self.lbl_progress.setText("未开始")
        self.sync_actions()

    def _build_request(self) -> Tuple[Optional[ProcessRequest], Optional[str]]:
        out_dir = self.edt_outdir.text().strip()
        if not out_dir:
            return None, "请先选择输出目录"
        if not os.path.isdir(out_dir):
            return None, "输出目录不存在或不可用"

        preset_key = self.cmb_preset.currentData()
        custom_w = None
        custom_h = None
        keep_aspect = True
        if preset_key == "CUSTOM":
            wtxt = self.edt_custom_w.text().strip()
            htxt = self.edt_custom_h.text().strip()
            if not wtxt and not htxt:
                return None, "自定义尺寸需要填写宽或高（可只填一个，表示长边）"
            if wtxt:
                try:
                    custom_w = int(wtxt)
                except Exception:
                    return None, "自定义宽度必须是整数"
            if htxt:
                try:
                    custom_h = int(htxt)
                except Exception:
                    return None, "自定义高度必须是整数"
            keep_aspect = bool(self.chk_keep_aspect.isChecked())
            preset_key = "ORIGINAL"
        fmt = self.cmb_fmt.currentData()

        target_txt = self.cmb_target.currentText().strip()
        target_bytes = None
        if target_txt:
            try:
                target_bytes = parse_target_size(target_txt)
            except Exception:
                return None, "目标大小格式不正确（例如：300KB / 1MB）"

        req = ProcessRequest(
            preset_key=str(preset_key),
            output_format=str(fmt),
            target_size_bytes=target_bytes,
            allow_downscale=(self.cmb_policy.currentData() == "BYTES"),
            custom_width=custom_w,
            custom_height=custom_h,
            keep_aspect=keep_aspect,
        )
        return req, None

    def on_start(self):
        if not self._items:
            return

        req, err = self._build_request()
        if err:
            QMessageBox.warning(self, "参数错误", err)
            return
        assert req is not None

        out_dir = self.edt_outdir.text().strip()
        self._active_target_bytes = req.target_size_bytes

        for r in range(self.table.rowCount()):
            self.table.item(r, self.COL_OUT).setText("")
            self.table.item(r, self.COL_STATUS).setText("排队中")
            self.table.item(r, self.COL_REASON).setText("")

        self.progress.setMaximum(len(self._items))
        self.progress.setValue(0)
        self.lbl_progress.setText("准备开始...")

        self._worker = BatchWorker(self._items, req, out_dir, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.item_done.connect(self._on_item_done)
        self._worker.finished_all.connect(self._on_finished)
        self._set_busy(True)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.lbl_progress.setText(f"{done}/{total} {name}")

    def _on_item_done(self, row: int, ok: bool, out_path: str, reason: str, ow: int, oh: int, osize: int):
        if ok:
            self.table.item(row, self.COL_OUT).setText(out_path)
            suffix = f"{int(ow)}×{int(oh)} / {format_bytes(int(osize))}"
            target = self._active_target_bytes
            if target is not None:
                hi = int(int(target) * 1.06)
                if int(osize) > hi:
                    suffix = f"{suffix}（未达成目标）"
            self.table.item(row, self.COL_STATUS).setText(f"成功（{suffix}）")
            self.table.item(row, self.COL_REASON).setText("")
        else:
            self.table.item(row, self.COL_OUT).setText("")
            self.table.item(row, self.COL_STATUS).setText("失败")
            self.table.item(row, self.COL_REASON).setText(reason)

    def _on_finished(self, ok_count: int, fail_count: int):
        self._set_busy(False)
        self.lbl_progress.setText(f"完成：成功 {ok_count}，失败 {fail_count}")

        QMessageBox.information(
            self,
            "处理完成",
            f"批量处理完成。\n成功：{ok_count}\n失败：{fail_count}\n\n失败原因可在表格“失败原因”列查看。",
        )

        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self.sync_actions()


def run():
    app = QApplication(sys.argv)
    apply_style(app)
    w = MainWindow()
    w.show()
    raise SystemExit(app.exec())


def is_dark_theme(app: QApplication) -> bool:
    p = app.palette()
    c = p.color(QPalette.Window)
    return (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) < 128


def apply_style(app: QApplication) -> None:
    dark = is_dark_theme(app)
    if dark:
        bg = "#0F0F10"
        card = "#17181A"
        text = "#EDEDED"
        sub = "#A7A7A7"
        border = "#2A2B2E"
        btn = "#2C6BED"
        btn_text = "#FFFFFF"
        btn2 = "#232427"
        btn2_text = "#EDEDED"
        input_bg = "#1D1E21"
        input_text = "#EDEDED"
        sel = "#2C6BED"
    else:
        bg = "#F5F5F7"
        card = "#FFFFFF"
        text = "#1D1D1F"
        sub = "#6E6E73"
        border = "#D2D2D7"
        btn = "#007AFF"
        btn_text = "#FFFFFF"
        btn2 = "#F2F2F2"
        btn2_text = "#1D1D1F"
        input_bg = "#FFFFFF"
        input_text = "#1D1D1F"
        sel = "#007AFF"

    app.setStyleSheet(
        f"""
        QWidget {{
            background: {bg};
            color: {text};
            font-size: 13px;
        }}
        QMainWindow {{
            background: {bg};
        }}
        QLabel {{
            background: transparent;
        }}
        QLabel[subtitle="true"] {{
            color: {sub};
        }}
        QPushButton {{
            background: {btn2};
            color: {btn2_text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 8px 12px;
        }}
        QPushButton:hover {{
            border-color: {sel};
        }}
        QPushButton:disabled {{
            color: {sub};
            border-color: {border};
        }}
        QPushButton[primary="true"] {{
            background: {btn};
            color: {btn_text};
            border: 1px solid {btn};
        }}
        QLineEdit, QComboBox {{
            background: {input_bg};
            color: {input_text};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 8px 10px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QTableWidget {{
            background: {card};
            border: 1px solid {border};
            border-radius: 12px;
            gridline-color: {border};
            selection-background-color: {sel};
            selection-color: #FFFFFF;
        }}
        QHeaderView::section {{
            background: {card};
            color: {sub};
            border: none;
            border-bottom: 1px solid {border};
            padding: 8px 10px;
        }}
        QProgressBar {{
            background: {card};
            border: 1px solid {border};
            border-radius: 10px;
            text-align: center;
            height: 18px;
        }}
        QProgressBar::chunk {{
            background: {sel};
            border-radius: 9px;
        }}
        """
    )
