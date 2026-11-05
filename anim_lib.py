"""动画库：读取 dsh-pet/assets 下的 640×360 VP9-alpha 透明视频并播放。

三层：
- `load_catalog()` 读 catalog.json（由 scripts/build_animations_catalog.py 生成）；
- `FrameDecoder` 在子线程里用 PyAV + libvpx-vp9 解码（只有 libvpx 解码器才能拿到
  VP9 的 alpha 层，ffmpeg 自带的 vp9 解码器会把它丢掉，画面变成黑底）；
- `AnimLibraryDialog` 是浏览面板：左侧搜索/分类，右侧播放。

PyAV 是可选依赖：没装时自动退回用 GIF 预览（QMovie）播放，功能不中断。

为什么要 libvpx 而不是 QtMultimedia：Qt 的 ffmpeg 后端解 VP9-alpha webm 出来是
yuv420p，透明通道丢失；而且给桌宠加多媒体后端会引入一堆平台相关的坑。
"""

from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "dsh-pet", "assets")

CATEGORY_ORDER = ["idle", "move", "click", "play", "work", "eat", "sleep",
                  "balance", "whisper", "festival", "effect", "life", "misc"]

ACCENT = "#5686fe"


# ------------------------------------------------------------------ 目录
_catalog_cache: dict | None = None


def catalog_path(assets: str | None = None) -> str:
    return os.path.join(assets or ASSETS, "catalog.json")


def load_catalog(assets: str | None = None, reload: bool = False) -> dict:
    """读 catalog.json；缺文件时返回空骨架，不抛异常。"""
    global _catalog_cache
    if _catalog_cache is not None and not reload and assets is None:
        return _catalog_cache
    path = catalog_path(assets)
    data = {"about": {}, "stats": {}, "categories": {}, "animations": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[anim_lib] 读不到动画目录 {path}：{e}", file=sys.stderr)
    data.setdefault("animations", [])
    data.setdefault("categories", {})
    if assets is None:
        _catalog_cache = data
    return data


def animations(assets: str | None = None) -> list[dict]:
    return load_catalog(assets)["animations"]


def by_id(anim_id: str, assets: str | None = None) -> dict | None:
    for it in animations(assets):
        if it.get("id") == anim_id:
            return it
    return None


def abs_path(item: dict, key: str = "webm", assets: str | None = None) -> str:
    """把 catalog 里的相对路径转成本机绝对路径"""
    rel = item.get(key)
    if not rel:
        return ""
    return os.path.join(assets or ASSETS, *rel.split("/"))


def category_label(cat: str) -> str:
    cat_meta = load_catalog().get("categories", {}).get(cat)
    if cat_meta and cat_meta.get("label"):
        return cat_meta["label"]
    name = {"idle": "待机", "move": "移动", "click": "点击回应", "play": "玩耍",
            "work": "工作", "eat": "吃", "sleep": "睡觉", "balance": "余额",
            "whisper": "碎碎念", "festival": "节日", "effect": "特效"}.get(cat, "其他")
    return f"{name} · {cat}"


def av_available() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ 解码
def decode_frame(path: str, index: int = 0) -> QImage | None:
    """同步解一帧（测试 / 截图用）。必须走 libvpx-vp9 才保留 alpha。"""
    try:
        import av
    except Exception:
        return None
    try:
        with av.open(path) as c:
            stream = c.streams.video[0]
            ctx = av.CodecContext.create("libvpx-vp9", "r")
            n = 0
            for pkt in c.demux(stream):
                for frame in ctx.decode(pkt):
                    if n == index:
                        arr = frame.to_ndarray(format="rgba")
                        h, w = arr.shape[:2]
                        return QImage(arr.data, w, h, arr.strides[0],
                                      QImage.Format.Format_RGBA8888).copy()
                    n += 1
    except Exception as e:
        print(f"[anim_lib] 解码失败 {os.path.basename(path)}：{e}", file=sys.stderr)
    return None


class FrameDecoder(QThread):
    """流式解码：按原帧率把 QImage 一帧帧送给主线程，不一次性占内存。

    241 帧 × 640×360×4 ≈ 222MB，全缓存会吃掉一台小机器，所以走流式。
    """

    sig_frame = Signal(QImage)
    sig_error = Signal(str)

    def __init__(self, path: str, fps: float = 24.0, loop: bool = True, parent=None):
        super().__init__(parent)
        self.path = path
        self.fps = max(1.0, min(60.0, float(fps or 24.0)))
        self.loop = loop
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import av
        except Exception as e:
            self.sig_error.emit(f"没装 PyAV（{e}）")
            return
        while not self._stop:
            try:
                with av.open(self.path) as c:
                    stream = c.streams.video[0]
                    ctx = av.CodecContext.create("libvpx-vp9", "r")
                    next_t = time.perf_counter()
                    for pkt in c.demux(stream):
                        if self._stop:
                            return
                        for frame in ctx.decode(pkt):
                            if self._stop:
                                return
                            arr = frame.to_ndarray(format="rgba")
                            h, w = arr.shape[:2]
                            img = QImage(arr.data, w, h, arr.strides[0],
                                         QImage.Format.Format_RGBA8888).copy()
                            self.sig_frame.emit(img)
                            next_t += 1.0 / self.fps
                            delay = next_t - time.perf_counter()
                            if delay > 0:
                                self.msleep(int(delay * 1000))
                            else:
                                next_t = time.perf_counter()
            except Exception as e:
                self.sig_error.emit(str(e))
                return
            if not self.loop:
                return


# ------------------------------------------------------------------ 播放器
class AnimCanvas(QWidget):
    """画布：棋盘格底 + 居中缩放的帧。棋盘格是为了让透明不被误看成白底。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img: QImage | None = None
        self._movie = None
        self.setMinimumSize(320, 180)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_frame(self, img: QImage):
        self._img = img
        self.update()

    def set_movie(self, movie):
        self._movie = movie
        self._img = None
        if movie is not None:
            movie.frameChanged.connect(self._on_movie)
        self.update()

    def _on_movie(self, _n):
        frame = self._movie.currentPixmap()
        if not frame.isNull():
            self._img = frame.toImage()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f2f4f9"))
        cell = 14
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e3e7f1"))
        for y in range(0, self.height(), cell):
            for x in range(0, self.width(), cell):
                if (x // cell + y // cell) % 2 == 0:
                    p.fillRect(x, y, cell, cell, QColor("#e3e7f1"))
        if self._img is not None and not self._img.isNull():
            scaled = self._img.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            p.drawImage((self.width() - scaled.width()) // 2,
                        (self.height() - scaled.height()) // 2, scaled)
        else:
            p.setPen(QColor("#9aa3b8"))
            p.setFont(QFont("Microsoft YaHei UI", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选中左侧动画开始播放")
        p.end()


class AnimLibraryDialog(QDialog):
    """动画库浏览面板"""

    def __init__(self, assets: str | None = None, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(860, 560)
        self.assets = assets or ASSETS
        self.cat = load_catalog(self.assets)
        self.items = self.cat["animations"]
        self._decoder: FrameDecoder | None = None
        self._movie = None
        self._current: dict | None = None
        self._build()
        self._fill()
        if self.items:
            self.list.setCurrentRow(0)

    # -- UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("""
            QFrame#card { background:#ffffff; border:1px solid #e6e8f0; border-radius:20px; }
            QLineEdit { border:1px solid #e6e8f0; border-radius:10px; padding:7px 10px;
                        font-size:12px; color:#2b2b36; background:#f8f9fc; }
            QLineEdit:focus { border-color:#b9c8f8; background:#ffffff; }
            QComboBox { border:1px solid #e6e8f0; border-radius:10px; padding:6px 8px;
                        font-size:12px; color:#3a3a48; background:#f8f9fc; }
            QListWidget { border:1px solid #eef0f6; border-radius:12px; background:#fbfcfe;
                          font-size:12px; color:#3a3a48; outline:none; }
            QListWidget::item { padding:7px 8px; border-radius:8px; }
            QListWidget::item:selected { background:#e8eefe; color:#2c4bbd; font-weight:600; }
            QListWidget::item:hover { background:#f2f5fd; }
        """)
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(11)

        head = QHBoxLayout()
        title = QLabel("动画库")
        title.setStyleSheet("font-size:16px; font-weight:600; color:#23232c;")
        head.addWidget(title)
        cnt = QLabel(f"{len(self.items)} 段 · 640×360 VP9-alpha")
        cnt.setStyleSheet("font-size:11px; color:#9aa3b8;")
        head.addWidget(cnt)
        head.addStretch(1)
        close = QToolButton()
        close.setText("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("QToolButton{border:none; color:#9a9aa8; font-size:14px;}"
                            "QToolButton:hover{color:#e05c5c;}")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左：筛选 + 列表
        left = QVBoxLayout()
        left.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜中文名或拼音 ID…")
        self.search.textChanged.connect(self._refresh)
        left.addWidget(self.search)

        self.cat_box = QComboBox()
        self.cat_box.addItem("全部分类", "")
        for key in CATEGORY_ORDER:
            meta = self.cat.get("categories", {}).get(key)
            if meta:
                self.cat_box.addItem(f"{category_label(key)}（{meta['count']}）", key)
        for key in self.cat.get("categories", {}):
            if key not in CATEGORY_ORDER:
                meta = self.cat["categories"][key]
                self.cat_box.addItem(f"{category_label(key)}（{meta['count']}）", key)
        self.cat_box.currentIndexChanged.connect(self._refresh)
        left.addWidget(self.cat_box)

        self.list = QListWidget()
        self.list.setFixedWidth(236)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentItemChanged.connect(self._on_pick)
        left.addWidget(self.list, 1)
        body.addLayout(left, 0)

        # 右：播放区
        right = QVBoxLayout()
        right.setSpacing(9)
        self.canvas = AnimCanvas()
        right.addWidget(self.canvas, 1)

        self.name_lab = QLabel("—")
        self.name_lab.setStyleSheet("font-size:15px; font-weight:600; color:#23232c;")
        right.addWidget(self.name_lab)

        self.meta_lab = QLabel("")
        self.meta_lab.setStyleSheet("font-size:11px; color:#8b8b9a;")
        right.addWidget(self.meta_lab)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.replay_btn = self._ghost("↻ 重播", self._replay)
        self.loop_btn = self._ghost("🔁 循环", self._toggle_loop)
        self.loop_btn.setCheckable(True)
        self.loop_btn.setChecked(True)
        self.link_btn = self._ghost("⧉ 复制链接", self._copy_link)
        self.folder_btn = self._ghost("📂 打开目录", self._open_folder)
        for b in (self.replay_btn, self.loop_btn, self.link_btn, self.folder_btn):
            tools.addWidget(b)
        tools.addStretch(1)
        right.addLayout(tools)
        body.addLayout(right, 1)

        lay.addLayout(body, 1)

        foot = QLabel("素材来自 PC2005-cloud/dsh-pet（形象 CC BY-NC-SA 4.0 · 非商业）")
        foot.setStyleSheet("font-size:10px; color:#aab2c4;")
        lay.addWidget(foot)

    def _ghost(self, text, slot):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton { border:1px solid #e6e8f0; background:#f6f7fb; color:#5a5a68;
                          border-radius:10px; padding:6px 10px; font-size:11px; }
            QPushButton:hover { border-color:#c9d3f5; color:#3f4d78; }
            QPushButton:checked { background:#e8eefe; border-color:#b9c8f8; color:#2c4bbd; }
        """)
        b.clicked.connect(slot)
        return b

    # -- 数据
    def _fill(self):
        self._refresh()

    def _visible(self) -> list[dict]:
        kw = self.search.text().strip().lower()
        cat = self.cat_box.currentData()
        out = []
        for it in self.items:
            if cat and it.get("category") != cat:
                continue
            if kw and kw not in it["name"].lower() and kw not in it["id"].lower():
                continue
            out.append(it)
        return out

    def _refresh(self):
        keep = self._current["id"] if self._current else None
        rows = self._visible()
        self.list.blockSignals(True)
        self.list.clear()
        for it in rows:
            item = QListWidgetItem(it["name"])
            item.setData(Qt.ItemDataRole.UserRole, it["id"])
            item.setToolTip(f"{it['name']}（{it['id']}）")
            self.list.addItem(item)
        self.list.blockSignals(False)
        if keep:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                    self.list.setCurrentRow(i)
                    return
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _on_pick(self, cur, _prev=None):
        if cur is None:
            return
        item = by_id(cur.data(Qt.ItemDataRole.UserRole), self.assets)
        if item:
            self.play(item)

    # -- 播放
    def play(self, item: dict):
        self._stop_playback()
        self._current = item
        self.name_lab.setText(item["name"])
        bits = [f"`{item['id']}`", item.get("category", "")]
        if item.get("duration"):
            bits.append(f"{item['duration']:.1f}s")
        if item.get("fps"):
            bits.append(f"{item['fps']:.0f}fps")
        bits.append(f"{item['bytes']/1024/1024:.2f} MB")
        if not item.get("preview"):
            bits.append("无 GIF 预览")
        self.meta_lab.setText("  ·  ".join(b for b in bits if b))

        webm = abs_path(item, "webm", self.assets)
        gif = abs_path(item, "preview", self.assets)
        if av_available() and webm and os.path.exists(webm):
            self._decoder = FrameDecoder(webm, item.get("fps", 24),
                                         loop=self.loop_btn.isChecked(), parent=self)
            self._decoder.sig_frame.connect(self.canvas.set_frame)
            self._decoder.sig_error.connect(self._on_decode_error)
            self._decoder.start()
        elif gif and os.path.exists(gif):
            self._play_gif(gif)

    def _play_gif(self, path):
        from PySide6.QtGui import QMovie

        self._movie = QMovie(path)
        self._movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self.canvas.set_movie(self._movie)
        self._movie.start()

    def _on_decode_error(self, msg):
        item = self._current
        if item and item.get("preview"):
            self._play_gif(abs_path(item, "preview", self.assets))
        else:
            self.meta_lab.setText(f"播放失败：{msg}")

    def _stop_playback(self):
        if self._decoder is not None:
            self._decoder.stop()
            self._decoder.wait(1500)
            self._decoder = None
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
            self.canvas.set_movie(None)

    def _replay(self):
        if self._current:
            self.play(self._current)

    def _toggle_loop(self):
        self._replay()

    def _copy_link(self):
        if not self._current:
            return
        from PySide6.QtWidgets import QApplication

        rel = self._current.get("preview") or self._current.get("webm")
        url = ("https://raw.githubusercontent.com/csxqnznz-collab/dafeiyu/main/"
               f"dsh-pet/assets/{rel}")
        QApplication.clipboard().setText(url)
        self.meta_lab.setText(f"已复制直链：{url}")

    def _open_folder(self):
        if not self._current:
            return
        path = abs_path(self._current, "webm", self.assets)
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    # -- 生命周期
    def closeEvent(self, e):
        self._stop_playback()
        super().closeEvent(e)

    def reject(self):
        self._stop_playback()
        super().reject()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)


def open_library(parent=None) -> AnimLibraryDialog:
    dlg = AnimLibraryDialog(parent=parent)
    dlg.show()
    return dlg
