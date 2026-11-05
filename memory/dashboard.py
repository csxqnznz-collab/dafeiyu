"""记忆中心（Memory Dashboard）

沿用便利贴的浅色卡片风格。功能：概览统计、分类浏览、搜索、
新建/编辑/删除/锁定/归档、备份与导出、手动整理。
"""

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                               QTextEdit, QVBoxLayout, QWidget)

from .manager import CATEGORY_LABELS
from .utils import human_size, local_str

CAT_COLOR = {
    "CORE": "#e0567c",
    "PROFILE": "#5686fe",
    "EPISODIC": "#39a06a",
    "KNOWLEDGE": "#b07d18",
    "TASK": "#8a63d2",
}

NAV = [
    ("ALL", "全部记忆"),
    ("CORE", "核心记忆"),
    ("PROFILE", "用户画像"),
    ("EPISODIC", "事件记忆"),
    ("KNOWLEDGE", "知识记忆"),
    ("TASK", "当前任务"),
    ("ARCHIVED", "已归档"),
    ("BACKUP", "备份与导出"),
]

CSS = """
QDialog { background: #ffffff; }
QLabel { color: #3a3a46; }
QPushButton {
    background: #5686fe; color: #fff; border: none; border-radius: 8px;
    padding: 7px 14px; font-size: 13px;
}
QPushButton:hover { background: #4575ed; }
QPushButton[flat="true"] {
    background: #f3f4fa; color: #4a4a5a;
}
QPushButton[flat="true"]:hover { background: #e8eaf6; }
QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background: #f6f7fb; border: 1px solid #e3e5ee; border-radius: 8px;
    padding: 6px 9px; color: #2b2b35; font-size: 13px;
}
QListWidget {
    background: #fbfbfe; border: 1px solid #ececf4; border-radius: 10px;
    padding: 6px;
}
QListWidget::item { border: none; }
QListWidget::item:selected { background: transparent; }
QCheckBox { color: #3a3a46; font-size: 13px; }
"""


class MemoryRow(QFrame):
    """一条记忆的展示卡片"""

    def __init__(self, mem, parent=None):
        super().__init__(parent)
        self.mem = mem
        self.setStyleSheet("QFrame{background:#ffffff;border:1px solid #eeeef6;"
                           "border-radius:10px;}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 10, 0)
        lay.setSpacing(10)

        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        bar.setStyleSheet("background:%s;border:none;border-radius:2px;"
                          % CAT_COLOR.get(mem.get("category"), "#999"))
        lay.addWidget(bar)

        box = QVBoxLayout()
        box.setContentsMargins(4, 8, 4, 8)
        box.setSpacing(4)

        txt = QLabel(mem.get("content") or "")
        txt.setWordWrap(True)
        txt.setStyleSheet("font-size:13px;color:#23232c;border:none;")
        box.addWidget(txt)

        meta = []
        cat = mem.get("category") or ""
        meta.append(CATEGORY_LABELS.get(cat, cat))
        meta.append("★%s" % mem.get("importance", 5))
        if mem.get("locked"):
            meta.append("🔒已锁定")
        if mem.get("status") == "archived":
            meta.append("已归档")
        if mem.get("status") == "superseded":
            meta.append("已被更新")
        meta.append(local_str(mem.get("updated_at")))
        sub = QLabel(" · ".join([m for m in meta if m]))
        sub.setStyleSheet("font-size:11px;color:#8b8b9a;border:none;")
        box.addWidget(sub)

        lay.addLayout(box, 1)


class MemoryEditDialog(QDialog):
    def __init__(self, engine, mem=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.mem = mem or {}
        self.setWindowTitle("编辑记忆" if mem else "新建记忆")
        self.setStyleSheet(CSS)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        root.addWidget(QLabel("记忆内容"))
        self.ed = QTextEdit()
        self.ed.setPlainText(self.mem.get("content") or "")
        self.ed.setFixedHeight(110)
        root.addWidget(self.ed)

        row = QHBoxLayout()
        row.addWidget(QLabel("分类"))
        self.cb = QComboBox()
        for k, label in CATEGORY_LABELS.items():
            self.cb.addItem(label, k)
        idx = self.cb.findData(self.mem.get("category") or "KNOWLEDGE")
        self.cb.setCurrentIndex(max(0, idx))
        row.addWidget(self.cb)

        row.addWidget(QLabel("重要性"))
        self.sp = QSpinBox()
        self.sp.setRange(1, 10)
        self.sp.setValue(int(self.mem.get("importance") or 6))
        row.addWidget(self.sp)
        row.addStretch(1)
        root.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("画像 key"))
        self.pk = QLineEdit(self.mem.get("profile_key") or "")
        self.pk.setPlaceholderText("仅用户画像用，如 job_role / communication_style")
        row2.addWidget(self.pk, 1)
        root.addLayout(row2)

        self.ck_lock = QCheckBox("锁定（自动整理时不会改动或被清理）")
        self.ck_lock.setChecked(bool(self.mem.get("locked")))
        root.addWidget(self.ck_lock)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setProperty("flat", True)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _save(self):
        text = self.ed.toPlainText().strip()
        if len(text) < 2:
            QMessageBox.information(self, "提示", "内容太短了")
            return
        cat = self.cb.currentData()
        imp = self.sp.value()
        locked = self.ck_lock.isChecked()
        pkey = self.pk.text().strip() or None
        mgr = self.engine.mgr
        if self.mem.get("id"):
            mgr.update(self.mem["id"], content=text, category=cat, importance=imp,
                       locked=1 if locked else 0, profile_key=pkey)
        else:
            mid, _ = mgr.add(text, category=cat, importance=imp, confidence=1.0,
                             profile_key=pkey, source_type="manual", dedupe=True)
            if mid and locked:
                mgr.lock(mid, True)
        self.accept()


class MemoryDashboard(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cur_cat = "ALL"
        self.query = ""
        self.setWindowTitle("大肥鱼 · 记忆中心")
        self.setStyleSheet(CSS)
        self.resize(920, 660)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        root.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_nav())

        right = QVBoxLayout()
        right.setSpacing(10)
        srow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索记忆：说个关键词，或直接问「我之前想做的那个项目」")
        self.search.returnPressed.connect(self.on_search)
        srow.addWidget(self.search, 1)
        btn_find = QPushButton("搜索")
        btn_find.clicked.connect(self.on_search)
        srow.addWidget(btn_find)
        right.addLayout(srow)

        self.list = QListWidget()
        self.list.setSpacing(6)
        self.list.itemDoubleClicked.connect(lambda _: self.on_edit())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        right.addWidget(self.list, 1)

        self.hint = QLabel("")
        self.hint.setStyleSheet("font-size:11px;color:#8b8b9a;")
        right.addWidget(self.hint)
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        root.addLayout(self._build_footer())

        self.refresh()
        QTimer.singleShot(50, self.refresh_stats)

    # ------------------------------------------------------------ UI
    def _build_header(self):
        bar = QHBoxLayout()
        title = QLabel("🧠 记忆中心")
        title.setStyleSheet("font-size:18px;font-weight:700;color:#1f1f28;")
        bar.addWidget(title)
        self.badge = QLabel("")
        self.badge.setStyleSheet("font-size:12px;color:#8b8b9a;")
        bar.addWidget(self.badge)
        bar.addStretch(1)

        self.stat_labels = {}
        for key, label in [("mem", "记忆"), ("msg", "消息"), ("prof", "画像"),
                           ("pend", "待整理"), ("size", "占用"), ("dream", "上次整理")]:
            card = QFrame()
            card.setStyleSheet("QFrame{background:#f6f7fb;border-radius:10px;}")
            v = QVBoxLayout(card)
            v.setContentsMargins(10, 6, 10, 6)
            v.setSpacing(1)
            num = QLabel("-")
            num.setStyleSheet("font-size:14px;font-weight:700;color:#23232c;border:none;")
            cap = QLabel(label)
            cap.setStyleSheet("font-size:10px;color:#8b8b9a;border:none;")
            v.addWidget(num)
            v.addWidget(cap)
            bar.addWidget(card)
            self.stat_labels[key] = num
        return bar

    def _build_nav(self):
        box = QFrame()
        box.setFixedWidth(150)
        box.setStyleSheet("QFrame{background:#f6f7fb;border-radius:12px;}")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(6)
        self.nav_btns = {}
        for key, label in NAV:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_cat(k))
            self.nav_btns[key] = b
            v.addWidget(b)
        v.addStretch(1)
        return box

    def _build_footer(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for text, fn, flat in [
            ("＋ 新建记忆", self.on_new, False),
            ("立即整理", self.on_dream, True),
            ("备份", self.on_backup, True),
            ("导出 JSON", self.on_export, True),
            ("恢复备份", self.on_restore_backup, True),
            ("打开数据目录", self.on_open_dir, True),
        ]:
            b = QPushButton(text)
            b.setProperty("flat", flat)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        close = QPushButton("关闭")
        close.setProperty("flat", True)
        close.clicked.connect(self.close)
        bar.addWidget(close)
        return bar

    # ------------------------------------------------------------ 数据
    def refresh(self):
        self.refresh_stats()
        self._refresh_nav_style()
        if self.cur_cat == "BACKUP":
            self._show_backups()
            return
        self.list.clear()
        mgr = self.engine.mgr
        if self.cur_cat == "ARCHIVED":
            rows = mgr.list(status="archived", limit=200)
            if self.query:
                rows = [r for r in rows if self.query.lower() in (r["content"] or "").lower()]
        elif self.query:
            rows = self.engine.retr.search(self.query, k=60, include_archived=True)
        else:
            rows = mgr.list(category=self.cur_cat, status="active", limit=200)

        for r in rows:
            it = QListWidgetItem(self.list)
            w = MemoryRow(r)
            it.setSizeHint(w.sizeHint())
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            it.setData(Qt.ItemDataRole.UserRole, r.get("id"))
        self.hint.setText(f"共 {len(rows)} 条 · 双击编辑，右键可锁定/归档/删除"
                        + ("（搜索结果含归档记录）" if self.query else ""))

    def refresh_stats(self):
        try:
            s = self.engine.stats()
        except Exception:
            return
        self.stat_labels["mem"].setText(str(s.get("total_active", 0)))
        self.stat_labels["msg"].setText(str(s.get("messages", 0)))
        self.stat_labels["prof"].setText(str(s.get("profile_count", 0)))
        self.stat_labels["pend"].setText(str(s.get("pending", 0)))
        self.stat_labels["size"].setText(human_size(s.get("db_size", 0)))
        last = s.get("last_dreaming") or ""
        self.stat_labels["dream"].setText(local_str(last, "%m-%d %H:%M") if last else "未整理")
        self.badge.setText("已开启" if s.get("enabled") else "已关闭")

    def _refresh_nav_style(self):
        for key, b in self.nav_btns.items():
            on = (key == self.cur_cat)
            b.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:none;border-radius:8px;"
                "padding:8px 12px;font-size:13px;text-align:left;}"
                % ("#5686fe" if on else "transparent", "#ffffff" if on else "#4a4a5a"))

    def set_cat(self, key):
        self.cur_cat = key
        if key != "BACKUP":
            self.query = ""
            self.search.clear()
        self.refresh()

    def on_search(self):
        self.query = self.search.text().strip()
        self.cur_cat = "ALL"
        self.refresh()

    # ------------------------------------------------------------ 列表交互
    def _current_id(self):
        it = self.list.currentItem()
        if not it:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _list_menu(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        self.list.setCurrentItem(it)
        mid = it.data(Qt.ItemDataRole.UserRole)
        mem = self.engine.mgr.get(mid)
        if not mem:
            return
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("编辑", self.on_edit)
        m.addAction("锁定" if not mem.get("locked") else "解锁", self.on_lock)
        if mem.get("status") == "archived":
            m.addAction("恢复", self.on_restore)
        else:
            m.addAction("归档", self.on_archive)
        m.addSeparator()
        m.addAction("彻底删除", self.on_hard_delete)
        m.exec(self.list.mapToGlobal(pos))

    def on_edit(self):
        mid = self._current_id()
        if not mid:
            return
        mem = self.engine.mgr.get(mid)
        if not mem:
            return
        dlg = MemoryEditDialog(self.engine, mem, self)
        if dlg.exec():
            self.refresh()

    def on_new(self):
        dlg = MemoryEditDialog(self.engine, None, self)
        if dlg.exec():
            self.refresh()

    def on_lock(self):
        mid = self._current_id()
        mem = self.engine.mgr.get(mid) if mid else None
        if not mem:
            return
        self.engine.mgr.lock(mid, not bool(mem.get("locked")))
        self.refresh()

    def on_archive(self):
        mid = self._current_id()
        if mid:
            self.engine.mgr.archive(mid)
            self.refresh()

    def on_restore(self):
        mid = self._current_id()
        if mid:
            self.engine.mgr.restore(mid)
            self.refresh()

    def on_hard_delete(self):
        mid = self._current_id()
        if not mid:
            return
        ok = QMessageBox.question(
            self, "彻底删除",
            "这条记忆会被物理删除（含来源与关联），不可恢复。确定吗？")
        if ok == QMessageBox.StandardButton.Yes:
            self.engine.mgr.delete(mid, hard=True)
            self.refresh()

    # ------------------------------------------------------------ 操作
    def on_dream(self):
        self.hint.setText("正在整理…（合并重复、更新画像、清理过期任务）")
        QApplication.processEvents()
        try:
            rep = self.engine.run_dreaming(wait=True) or {}
            self.hint.setText(
                "整理完成：合并 %s 条、归档 %s 条、画像更新 %s 条"
                % (rep.get("merged", 0), rep.get("archived", 0),
                   rep.get("profile_updated", 0)))
        except Exception as e:
            self.hint.setText(f"整理失败：{e}")
        self.refresh()

    def on_backup(self):
        path = self.engine.backup_mgr.backup("manual")
        if path:
            QMessageBox.information(self, "备份完成", f"已保存到：\n{path}")
        else:
            QMessageBox.warning(self, "备份失败", "请查看数据目录下的日志")
        self.refresh()

    def on_export(self):
        default = os.path.join(os.path.expanduser("~"),
                               "Desktop", "大肥鱼记忆导出.json")
        path, _ = QFileDialog.getSaveFileName(self, "导出记忆", default, "JSON (*.json)")
        if not path:
            return
        try:
            self.engine.backup_mgr.export_to_file(path, "all")
            QMessageBox.information(self, "导出完成", f"已导出到：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def on_restore_backup(self):
        backups = self.engine.backup_mgr.list_backups()
        if not backups:
            QMessageBox.information(self, "没有备份", "还没有备份文件，先点「备份」")
            return
        names = [b["name"] for b in backups]
        name, ok = QInputDialog.getItem(self, "恢复备份", "选择备份文件", names, 0, False)
        if not ok:
            return
        chosen = [b for b in backups if b["name"] == name][0]
        if QMessageBox.question(
                self, "确认恢复",
                "恢复会用备份覆盖当前数据库（当前数据会先自动备份一份）。继续吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        ok2, msg = self.engine.backup_mgr.restore(chosen["path"])
        QMessageBox.information(self, "恢复结果", msg)
        self.refresh()

    def on_open_dir(self):
        path = os.path.dirname(self.engine.db.path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.information(self, "数据目录", f"{path}\n({e})")

    def _show_backups(self):
        self.list.clear()
        backups = self.engine.backup_mgr.list_backups()
        if not backups:
            self.hint.setText("还没有备份")
            return
        for b in backups:
            it = QListWidgetItem(self.list)
            w = MemoryRow({
                "content": b["name"],
                "category": "KNOWLEDGE",
                "importance": "",
                "updated_at": __import__("datetime").datetime.fromtimestamp(
                    b["mtime"]).isoformat(),
                "metadata_json": None,
            })
            it.setSizeHint(w.sizeHint())
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            it.setData(Qt.ItemDataRole.UserRole, b["path"])
        self.hint.setText(f"共 {len(backups)} 个备份 · 双击可恢复")
        self.list.itemDoubleClicked.disconnect()
        self.list.itemDoubleClicked.connect(self._restore_from_item)

    def _restore_from_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        if QMessageBox.question(
                self, "确认恢复",
                "恢复会用该备份覆盖当前数据库（当前数据先自动备份）。继续吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self.engine.backup_mgr.restore(path)
        QMessageBox.information(self, "恢复结果", msg)
        self.refresh()
