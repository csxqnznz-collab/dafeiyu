"""AI 接口设置：DeepSeek / Agnes AI / 自定义（OpenAI 兼容）

设计要点
- 三家共用同一套 OpenAI 兼容协议，只是 base_url / 模型名不同
- 每个服务商独立保存 key/base/model，切换不丢配置
- 旧版单 Key 配置（api_key / ai_base_url / ai_model）自动迁移到 profiles
- 所有网络操作（拉模型、测连接）都在线程里跑，通过 Signal 回主线程更新 UI
"""

from __future__ import annotations

import re
import threading
import time

import requests
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QToolButton, QVBoxLayout)

# ---------------------------------------------------------------- 预设
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default": "deepseek-chat",
        "site": "https://platform.deepseek.com/api_keys",
        "tip": "官方直连，deepseek-chat 快、deepseek-reasoner 会思考",
    },
    "agnes": {
        "name": "Agnes AI",
        "base": "https://apihub.agnes-ai.com/v1",
        "models": ["agnes-2.5-flash", "agnes-3.0-flash", "agnes-2.5-pro-alpha"],
        "default": "agnes-2.5-flash",
        "site": "https://www.agnes-ai.com",
        "tip": "聚合网关，flash 便宜够用",
    },
    "custom": {
        "name": "自定义",
        "base": "",
        "models": [],
        "default": "",
        "site": "",
        "tip": "任何 OpenAI 兼容服务：硅基流动 / 阿里百炼 / Ollama / OneAPI…",
    },
}
ORDER = ["deepseek", "agnes", "custom"]


def _norm_base(url: str) -> str:
    """补协议、去尾部斜杠；误粘了 /chat/completions 也能救回来"""
    u = (url or "").strip()
    if not u:
        return ""
    u = re.sub(r"/chat/completions/?$", "", u, flags=re.I)
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u.rstrip("/")


def detect(base: str) -> str:
    """按域名猜服务商"""
    b = (base or "").lower()
    if "deepseek" in b:
        return "deepseek"
    if "agnes" in b:
        return "agnes"
    return "custom"


# ---------------------------------------------------------------- 配置读写
def _blank_profiles() -> dict:
    out = {}
    for pid, spec in PROVIDERS.items():
        out[pid] = {"key": "", "base": spec["base"], "model": spec["default"]}
    return out


def ensure(cfg: dict) -> bool:
    """补齐 ai_profiles / 迁移旧字段。返回 True 表示配置被改过"""
    changed = False

    profs = cfg.get("ai_profiles")
    if not isinstance(profs, dict):
        profs = {}
        changed = True
    for pid, spec in PROVIDERS.items():
        p = profs.get(pid)
        if not isinstance(p, dict):
            p = {}
            changed = True
        for k, v in (("key", ""), ("base", spec["base"]), ("model", spec["default"])):
            if not isinstance(p.get(k), str):
                p[k] = v
                changed = True
        profs[pid] = p
    cfg["ai_profiles"] = profs

    # --- 旧版单 Key（api_key / ds_api_key / ai_base_url / ai_model）
    had_legacy = any(k in cfg for k in ("api_key", "ds_api_key", "ai_base_url", "ai_model"))
    old_key = ""
    for _k in ("api_key", "ds_api_key"):
        _v = cfg.pop(_k, "")
        if _v and not old_key:
            old_key = _v.strip()
    old_base = (cfg.pop("ai_base_url", "") or "").strip()
    old_model = (cfg.pop("ai_model", "") or "").strip()
    if had_legacy:
        changed = True

    if old_key and not any(p["key"] for p in profs.values()):
        # 没写 base 的老配置默认按 Agnes 处理（上一版的默认服务商）
        pid = detect(old_base) if old_base else "agnes"
        profs[pid]["key"] = old_key
        if old_base:
            profs[pid]["base"] = _norm_base(old_base)
        if old_model:
            profs[pid]["model"] = old_model
        if cfg.get("ai_provider") not in PROVIDERS:
            cfg["ai_provider"] = pid
            changed = True
        changed = True

    if cfg.get("ai_provider") not in PROVIDERS:
        cfg["ai_provider"] = "agnes"
        changed = True

    return changed


def active_id(cfg: dict) -> str:
    pid = cfg.get("ai_provider")
    return pid if pid in PROVIDERS else "agnes"


def profile(cfg: dict, pid: str | None = None) -> dict:
    pid = pid if pid in PROVIDERS else active_id(cfg)
    p = (cfg.get("ai_profiles") or {}).get(pid) or {}
    spec = PROVIDERS[pid]
    return {
        "key": (p.get("key") or "").strip(),
        "base": _norm_base(p.get("base") or spec["base"]),
        "model": (p.get("model") or spec["default"]).strip(),
    }


def api_key(cfg: dict) -> str:
    return profile(cfg)["key"]


def base_url(cfg: dict) -> str:
    return profile(cfg)["base"]


def model(cfg: dict) -> str:
    return profile(cfg)["model"]


def default_model(cfg: dict, pid: str | None = None) -> str:
    spec = PROVIDERS[pid if pid in PROVIDERS else active_id(cfg)]
    return spec["default"] or model(cfg)


def title(cfg: dict) -> str:
    return PROVIDERS[active_id(cfg)]["name"]


def models(cfg: dict, pid: str | None = None) -> list[str]:
    pid = pid if pid in PROVIDERS else active_id(cfg)
    spec = PROVIDERS[pid]
    cur = profile(cfg, pid)["model"]
    out = list(spec["models"])
    if cur and cur not in out:
        out.append(cur)
    return out


def save_profile(cfg: dict, pid: str, key: str, base: str, mdl: str) -> None:
    if pid not in PROVIDERS:
        pid = "custom"
    cfg.setdefault("ai_profiles", _blank_profiles())
    cfg["ai_profiles"][pid] = {
        "key": (key or "").strip(),
        "base": _norm_base(base),
        "model": (mdl or "").strip(),
    }
    cfg["ai_provider"] = pid


def mask(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "未填写"
    if len(k) <= 10:
        return k[:2] + "***"
    return f"{k[:6]}…{k[-4:]}"


# ---------------------------------------------------------------- 网络
def fetch_models(base: str, key: str, timeout: int = 15) -> list[str]:
    """GET /models，拿不到就抛异常（由界面翻译成人话）"""
    base = _norm_base(base)
    if not base:
        raise ValueError("接口地址为空")
    r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"},
                     timeout=timeout)
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}：{(r.text or '')[:120]}")
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    ids = [str(it.get("id")) for it in (items or []) if isinstance(it, dict) and it.get("id")]
    if not ids:
        raise ValueError("接口没返回模型列表")
    return sorted(set(ids))


def test_connection(base: str, key: str, mdl: str, timeout: int = 30) -> tuple[bool, str]:
    """发一条最小请求验证 key / 地址 / 模型是否可用"""
    base = _norm_base(base)
    if not base:
        return False, "接口地址为空"
    if not key:
        return False, "Key 为空"
    if not mdl:
        return False, "模型名为空"
    t0 = time.time()
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": mdl, "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 8},
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        return False, "超时，检查网络或代理"
    except Exception as e:
        return False, f"连接失败：{str(e)[:60]}"
    ms = int((time.time() - t0) * 1000)
    if r.status_code == 200:
        return True, f"通了 · {ms}ms"
    body = (r.text or "")[:120].replace("\n", " ")
    if r.status_code in (401, 403):
        return False, "Key 不对（401/403）"
    if r.status_code == 402:
        return False, "余额不足（402）"
    if r.status_code == 404:
        return False, f"模型或地址不存在（404）{body}"
    if r.status_code == 429:
        return False, "限流了，稍后再试（429）"
    return False, f"HTTP {r.status_code}：{body}"


# ---------------------------------------------------------------- 对话框
class AISettingsDialog(QDialog):
    """接口设置面板：服务商 / 接口地址 / Key / 模型 + 测试连接"""

    sig_test = Signal(bool, str)
    sig_models = Signal(bool, object)

    def __init__(self, cfg: dict, on_saved=None, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(520, 392)
        self.cfg = cfg
        self.on_saved = on_saved
        self.pid = active_id(cfg)
        self._drafts: dict[str, dict] = {}
        self._busy = False
        self._build()
        self._load(self.pid, stash=False)
        self.sig_test.connect(self._on_test)
        self.sig_models.connect(self._on_models)

    # -- UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("""
            QFrame#card {
                background: #ffffff;
                border: 1px solid #e6e8f0;
                border-radius: 20px;
            }
        """)
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        t = QLabel("接口设置")
        t.setStyleSheet("font-size:16px; font-weight:600; color:#23232c;")
        head.addWidget(t)
        head.addStretch(1)
        btnx = QToolButton()
        btnx.setText("✕")
        btnx.setCursor(Qt.CursorShape.PointingHandCursor)
        btnx.setStyleSheet("QToolButton{border:none; color:#9a9aa8; font-size:14px;}"
                           "QToolButton:hover{color:#e05c5c;}")
        btnx.clicked.connect(self.reject)
        head.addWidget(btnx)
        lay.addLayout(head)

        sub = QLabel("三家都走 OpenAI 兼容协议，填好 Key 就能用；配置只存在本机 config.json")
        sub.setStyleSheet("font-size:11px; color:#8b8b9a;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # 服务商
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btns = {}
        for pid in ORDER:
            b = QPushButton(PROVIDERS[pid]["name"])
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    border:1px solid #e6e8f0; background:#f6f7fb; color:#5a5a68;
                    border-radius:11px; padding:7px 4px; font-size:12px;
                }
                QPushButton:hover { border-color:#c9d3f5; color:#3f4d78; }
                QPushButton:checked {
                    background:#5686fe; border-color:#5686fe; color:white; font-weight:600;
                }
            """)
            b.clicked.connect(lambda _, k=pid: self._switch(k))
            self.btns[pid] = b
            row.addWidget(b, 1)
        lay.addLayout(row)

        # 接口地址
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://…/v1")
        lay.addLayout(self._form_row("接口地址", self.base_edit,
                                     self._ghost("恢复默认", self._reset_base)))

        # API Key
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…")
        self.eye = self._ghost("👁", self._toggle_eye)
        self.eye.setFixedWidth(52)
        lay.addLayout(self._form_row("API Key", self.key_edit, self.eye))

        # 模型
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        lay.addLayout(self._form_row("模型", self.model_combo,
                                     self._ghost("拉取列表", self._pull_models)))

        self.hint = QLabel("")
        self.hint.setStyleSheet("font-size:11px; color:#8b8b9a;")
        self.hint.setWordWrap(True)
        self.hint.setOpenExternalLinks(True)
        lay.addWidget(self.hint)

        self.status = QLabel("")
        self.status.setStyleSheet("font-size:11px; color:#8b8b9a;")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(30)
        lay.addWidget(self.status)
        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.test_btn = self._ghost("测试连接", self._test)
        self.test_btn.setFixedWidth(92)
        foot.addWidget(self.test_btn)
        foot.addStretch(1)
        cancel = self._ghost("取消", self.reject)
        cancel.setFixedWidth(66)
        foot.addWidget(cancel)
        self.save_btn = QPushButton("保存")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background:#5686fe; color:white; border:none; border-radius:11px;
                padding:8px 22px; font-size:13px; font-weight:600;
            }
            QPushButton:hover { background:#4a76e8; }
            QPushButton:disabled { background:#c3cdf0; }
        """)
        self.save_btn.clicked.connect(self._save)
        foot.addWidget(self.save_btn)
        lay.addLayout(foot)

        self._apply_input_style()

    def _form_row(self, label: str, widget, extra=None):
        row = QHBoxLayout()
        row.setSpacing(8)
        lab = QLabel(label)
        lab.setFixedWidth(56)
        lab.setStyleSheet("font-size:12px; color:#6b6b7a;")
        row.addWidget(lab)
        row.addWidget(widget, 1)
        if extra is not None:
            row.addWidget(extra)
        return row

    def _ghost(self, text, slot):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton {
                border:1px solid #e6e8f0; background:#ffffff; color:#5a5a68;
                border-radius:10px; padding:7px 10px; font-size:12px;
            }
            QPushButton:hover { border-color:#c9d3f5; color:#3f4d78; background:#f8f9ff; }
            QPushButton:disabled { color:#b6b6c2; }
        """)
        b.clicked.connect(slot)
        return b

    def _apply_input_style(self):
        qss = """
            QLineEdit, QComboBox {
                background:#f6f7fb; border:1px solid #e6e8f0; border-radius:10px;
                padding:7px 10px; font-size:12px; color:#2b2b35;
                min-height:16px;
            }
            QLineEdit:focus, QComboBox:focus { border:1px solid #b9c7ff; background:#ffffff; }
            QComboBox::drop-down { border:none; width:18px; }
            QComboBox QAbstractItemView {
                background:white; border:1px solid #e6e8f0; border-radius:8px;
                selection-background-color:#eef2ff; selection-color:#2b2b35;
                padding:4px; outline:none;
            }
        """
        self.setStyleSheet(self.styleSheet() + qss)

    # -- 数据装填
    def _load(self, pid: str, stash: bool = True):
        if stash:
            self._stash()
        self.pid = pid
        p = self._drafts.get(pid) or profile(self.cfg, pid)
        spec = PROVIDERS[pid]

        self.base_edit.setText(p["base"])
        self.base_edit.setPlaceholderText(spec["base"] or "https://your-endpoint/v1")
        self.key_edit.setText(p["key"])

        self.model_combo.clear()
        seen = []
        for m in list(spec["models"]) + ([p["model"]] if p["model"] else []):
            if m and m not in seen:
                seen.append(m)
        self.model_combo.addItems(seen)
        self.model_combo.setCurrentText(p["model"] or spec["default"])

        for k, b in self.btns.items():
            b.setChecked(k == pid)

        if spec["site"]:
            self.hint.setText(f'{spec["tip"]} · <a href="{spec["site"]}" style="color:#5686fe;">'
                              f'去 {spec["name"]} 拿 Key</a>')
        else:
            self.hint.setText(spec["tip"])

        if p["key"]:
            self.status.setText(f"当前 Key：{mask(p['key'])}")
            self.status.setStyleSheet("font-size:11px; color:#8b8b9a;")
        else:
            self.status.setText("还没填 Key，填完建议点「测试连接」验一下")
            self.status.setStyleSheet("font-size:11px; color:#c98a3a;")

    def _stash(self):
        if not getattr(self, "pid", None):
            return
        self._drafts[self.pid] = {
            "base": self.base_edit.text().strip(),
            "key": self.key_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
        }

    def _switch(self, pid: str):
        if pid == self.pid:
            self.btns[pid].setChecked(True)
            return
        self._load(pid)

    def _reset_base(self):
        self.base_edit.setText(PROVIDERS[self.pid]["base"])

    def _toggle_eye(self):
        on = self.key_edit.echoMode() == QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if on
                                  else QLineEdit.EchoMode.Password)

    # -- 网络动作
    def _set_status(self, text: str, color: str = "#8b8b9a"):
        self.status.setText(text)
        self.status.setStyleSheet(f"font-size:11px; color:{color};")

    def _test(self):
        if self._busy:
            return
        base = self.base_edit.text().strip()
        key = self.key_edit.text().strip()
        mdl = self.model_combo.currentText().strip()
        self._busy = True
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中…")
        self._set_status("正在请求接口…", "#8b8b9a")

        def work():
            ok, msg = test_connection(base, key, mdl)
            self.sig_test.emit(ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _on_test(self, ok: bool, msg: str):
        self._busy = False
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        self._set_status(("✓ " if ok else "✕ ") + msg, "#22a06b" if ok else "#d9534f")

    def _pull_models(self):
        if self._busy:
            return
        base = self.base_edit.text().strip()
        key = self.key_edit.text().strip()
        if not base:
            self._set_status("先填接口地址", "#d9534f")
            return
        self._busy = True
        self._set_status("正在拉模型列表…", "#8b8b9a")

        def work():
            try:
                self.sig_models.emit(True, fetch_models(base, key))
            except Exception as e:
                self.sig_models.emit(False, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_models(self, ok: bool, payload):
        self._busy = False
        if not ok:
            self._set_status(f"拉取失败：{payload}", "#d9534f")
            return
        ids = list(payload or [])
        cur = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(ids)
        if cur in ids:
            self.model_combo.setCurrentText(cur)
        self._set_status(f"✓ 拉到 {len(ids)} 个模型，下拉里挑", "#22a06b")

    # -- 保存
    def _save(self):
        base = self.base_edit.text().strip()
        key = self.key_edit.text().strip()
        mdl = self.model_combo.currentText().strip()
        if not base:
            self._set_status("接口地址不能为空", "#d9534f")
            return
        if not re.match(r"^https?://", _norm_base(base), re.I):
            self._set_status("接口地址要以 http(s):// 开头", "#d9534f")
            return
        if not mdl:
            self._set_status("模型名不能为空", "#d9534f")
            return
        save_profile(self.cfg, self.pid, key, base, mdl)
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        self.accept()

    # -- 窗口行为
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 58:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self, "_drag", None) and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)
