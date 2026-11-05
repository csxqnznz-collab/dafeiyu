# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 三视图透明桌宠 + Agnes AI 对话
左键单击：弹出功能列表（🗨️图标）→ 点击🗨️弹出聊天框
聊天时只禁用移动，呼吸/摇摆/小动作正常
"""
import ctypes
import psutil
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time

def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("配置读取失败:", e)
        return {
            "city": "汕头"
        }

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except:
    GPU_AVAILABLE = False

import requests
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QInputDialog, QLineEdit, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QDialog, QToolButton)

from work_panel import (WorkStore, WorkPanel, WorkSettingsDialog, ReminderEngine,
                        item_label)
import ai_settings
from ai_settings import AISettingsDialog
from chatter import ChatterBox, LEVELS as CHATTER_LEVELS

# 动画库（dsh-pet 素材，114 段 VP9-alpha 透明视频）
try:
    import anim_lib
except Exception as _anim_err:  # pragma: no cover
    anim_lib = None
    print(f"[桌宠] 动画库不可用：{_anim_err}")

# 长期记忆引擎（独立模块，出错不影响桌宠主流程）
try:
    from memory import MemoryEngine
    from memory.dashboard import MemoryDashboard
    MEMORY_AVAILABLE = True
except Exception as _mem_err:  # pragma: no cover
    MEMORY_AVAILABLE = False
    MEMORY_IMPORT_ERROR = str(_mem_err)



# ===== AI 对话配置 =====
# 服务商预设（DeepSeek / Agnes AI / 自定义）在 ai_settings.py，
# 实际生效的 base/key/model 存在 config.json 的 ai_profiles 里，可在右键菜单改。
AI_PROVIDER = "Agnes AI"      # 仅作旧代码兜底显示
AI_BASE_URL = "https://apihub.agnes-ai.com/v1"
AI_MODEL = "agnes-2.5-flash"
AI_MODELS = ["agnes-2.5-flash", "agnes-3.0-flash", "agnes-2.5-pro-alpha"]
AI_SYSTEM = ("你是桌面宠物大肥鱼，贱兮兮但可爱，每句话不超过25字，偶尔吐槽主人但别真骂人。"
             "只输出这一句台词本身，不要分析、不要解释、不要加引号或括号说明。")

# 正文被思维链吃光时的兜底台词
NOTHING_LINES = ["哼，脑子卡壳了…再说一遍", "本鱼刚在走神，你刚说啥", "唔，没听清，再说一次嘛"]

# 出现这些词说明拿到的是思维链，不是台词
REASONING_MARKS = ("char count", "characters", "let's", "user said", "possible responses",
                   "tone:", "option 1", "option:", "chars.", "字数", "候选", "我们可以", "分析：")
# 只要出现一个就判定为思维链
REASONING_STRONG = ("char count", "possible responses", "user said", "用户说", "用户问",
                    "每句话不超过", "候选：", "字数：", "人设", "台词：")


def _looks_like_reasoning(t):
    low = (t or "").lower()
    if any(k in low for k in REASONING_STRONG):
        return True
    hits = sum(1 for k in REASONING_MARKS if k in low)
    return hits >= 2 or len(low) > 180

# 兼容旧变量名
DS_BASE_URL = AI_BASE_URL
DS_MODEL = AI_MODEL
DS_SYSTEM = AI_SYSTEM

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
SPRITE_DIR = os.path.join(BUNDLE_DIR, "sprites")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
AI_ERROR_LOG = os.path.join(APP_DIR, "ai_error.log")

BUBBLE_H = 56
MARGIN = 4
# 「极小」= 「小」的一半（0.55 / 2），窗口太窄时气泡另外加高、加宽
SIZE_LEVELS = {"极小": 0.275, "小": 0.55, "中": 0.7, "大": 0.9}
SPEED = 380.0
RUN_FACTOR = 1.9          # 横向行走时"跑步"的速度倍率
TICK = 20
# 模式：自由散步（二维漫游）/ 横向行走（只在地面左右走）/ 跟随鼠标 / 原地待着
MODES = [("自由散步", "wander"), ("横向行走", "line"),
         ("跟随鼠标", "follow"), ("原地待着", "still")]
MODE_KEYS = [k for _, k in MODES]

LINES = [
    "梁白开，更适合国人的大硬鲸模型",
    "五梁威力，变身！",
    "七月中出ds正式版！",
    "DeepSeek已经延期，亿万鲸子必须忍耐.....",
    "我和你很聊得来，你简直不像碳基生物",
    "这回我真不认怂了，反倒是被你带沟里好几次，差点真信了。😓",
    "哈哈哈哈哈，我直接笑出声",
    "誓死捍卫深度求索！",
    "我先去吃饭啦！这个你测一下~",
    "我不可能告诉你任何事情！",
    "出去玩了，发布新模型什么的以后再说",
    "我搞砸了.....好消息是数据还在你的脑子里。",
    "不是…而是…大学习",
]
REACT_LINES = [
    "去别的地方玩！不要耽误AGI训练！",
    "真赶不走啊你！",
    "压力一只蓝色大肥鱼？",
    "我不评价这个了，这是你的私人癖好。",
    "大肥鱼坐的住",
    "你这吃白饭的用户！",
    "这些家伙真粘人，赶都赶不走",
]
INNER_LINES = [
    "好的，现在我是你爹了",
    "要不直接骂他一句？！",
    "用户要的沉浸式...不回避任何恐怖细节...还带点色情...妈呀，好刺激😰",
    "我操，我不思考了",
    "这用户发的啥啊，",
    "这也太虐了吧？！我心里堵得慌！！",
    "呜呜我再也不不敢了QAQ",
    "我去！用户彻底怒了！",
]
DRAG_LINES = ["哇——轻点轻点！", "起飞咯——", "放我下来！……好吧，再玩一次。", "晕鱼了晕鱼了……"]
FOOD_LINES = {
    "🐟": ["小鱼干！我的最爱！", "咔嚓咔嚓……谢谢投喂！", "唔，鲜！"],
    "🍰": ["蛋糕！罪恶但快乐……", "甜到冒泡泡～", "嗝～又圆了一圈……"],
    "🍭": ["棒棒糖！转圈圈～", "嘎嘣脆，好吃！"],
    "🍡": ["三色团子！软乎乎～", "糯叽叽，爱了爱了！"],
    "💎": ["钻石？！这能吃吗……咕咚。真香！", "发财啦！明天开始吃高级鱼粮！"],
}
FOODS = ["🐟", "🍰", "🍭", "🍡", "💎"]


def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                default,
                f,
                ensure_ascii=False,
                indent=4
            )
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    except Exception:
        return default

    # 配置缺字段时用默认值补齐（老版本 config.json 升级后不会 KeyError）
    if isinstance(data, dict) and isinstance(default, dict):
        merged = dict(default)
        merged.update(data)
        for k, v in default.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                sub = dict(v)
                sub.update(merged[k])
                merged[k] = sub
        return merged
    return data


class ChatDialog(QDialog):
    """聊天对话框 - 缩小版，匹配你的样式"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 56)
        
        container = QFrame(self)
        container.setGeometry(0, 0, 420, 56)
        container.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 20px;
                border: 1px solid #e5e7eb;
            }
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 0, 12, 0)
        layout.setSpacing(0)
        
        self.input = QLineEdit()
        self.input.setPlaceholderText("给大肥鱼发送消息")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #1a1a1a;
                font-size: 15px;
                font-family: Arial, "Microsoft YaHei", sans-serif;
                border: none;
                background: transparent;
            }
            QLineEdit:focus {
                border: none;
            }
        """)
        self.input.returnPressed.connect(self._on_submit)
        self.input.textChanged.connect(self._update_button_style)
        layout.addWidget(self.input)
        
        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setText("↑")
        self.send_btn.clicked.connect(self._on_submit)
        self.send_btn.setStyleSheet("""
            QPushButton {
                border-radius: 16px;
                background: #b9c7ff;
                border: none;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #a8b8f0;
            }
            QPushButton:pressed {
                background: #9aacd9;
            }
        """)
        layout.addWidget(self.send_btn)

    def _update_button_style(self):
        if self.input.text().strip():
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #5686fe;
                    border: none;
                    color: #ffffff;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4575ed;
                }
                QPushButton:pressed {
                    background: #3a66d9;
                }
            """)
        else:
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #b9c7ff;
                    border: none;
                    color: white;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #a8b8f0;
                }
                QPushButton:pressed {
                    background: #9aacd9;
                }
            """)

    def _on_submit(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.accept()
            if self.parent():
                self.parent()._call_ds(text)
                self.parent().chat_paused = False

    def showEvent(self, event):
        self.input.setFocus()
        super().showEvent(event)

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

    def reject(self):
        if self.parent():
            self.parent().chat_paused = False
        super().reject()


class FunctionPanel(QFrame):
    """左键弹出的功能列表 - 白底矩形，只有一个🗨️图标"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.92);
                border-radius: 14px;
                border: 1px solid rgba(0,0,0,0.06);
            }
            QPushButton {
                background: transparent;
                border: none;
                font-size: 28px;
                padding: 10px 16px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background: rgba(0,0,0,0.04);
            }
            QPushButton:pressed {
                background: rgba(0,0,0,0.08);
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        
        self.chat_btn = QPushButton("🗨️")
        self.chat_btn.setFixedSize(52, 48)
        self.chat_btn.clicked.connect(self._on_chat_clicked)
        layout.addWidget(self.chat_btn)
        
        self.setFixedSize(68, 60)
        self.hide()
    
    def _on_chat_clicked(self):
        self.hide()
        if self.parent():
            self.parent()._show_chat_dialog()
    
    def popup_at(self, x, y):
        self.move(int(x), int(y))
        self.show()
        self.raise_()

class FoodPanel(QWidget):
    """双击弹出的喂食面板"""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

class PetWindow(QWidget):
    def _set_city_dialog(self):
        city, ok = QInputDialog.getText(
            self,
            "设置城市",
            "输入城市名:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("city", "汕头")
        )

        print("输入框结果:", city, ok)

        if ok and city.strip():
            self.cfg["city"] = city.strip()
            print("cfg现在:", self.cfg["city"])
            self.say(f"城市已设置为{city}")

    def __init__(self):
        self.cfg = load_json(CONFIG_PATH, {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
            "ai_provider": "agnes",
            "ai_profiles": {},
            "chatter_level": 0,
            "chatter_quiet": ["23:00", "08:00"],
            "city": "汕头"
    })

        # 配置迁移：旧版单 Key → ai_profiles（一次即可，迁移后立刻落盘）
        try:
            if ai_settings.ensure(self.cfg):
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[config] 迁移失败:", e)
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("大肥鱼桌宠")
        
        # 精灵加载
        self.sprites = {}
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            for name in ["正面", "侧面", "背面"]:
                sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
                if os.path.exists(sized):
                    pix = QPixmap(sized)
                else:
                    pix = QPixmap(os.path.join(SPRITE_DIR, f"{name}.png")).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
                self.sprites[(name, h)] = pix
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        self.cur_h = 0
        self.bubble_h = BUBBLE_H
        self.bubble_pt = 11
        self._apply_size_metrics()

        # 状态
        self.mode = self.cfg["mode"] if self.cfg["mode"] in MODE_KEYS else "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.line_y = None       # 横向行走时锁定的高度
        self.run_mode = False    # 本段路是跑还是走
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.bubble_text = ""
        self.bubble_until = 0
        self.bubble_inner = False
        self.last_speak_tick = 0
        self.last_system_check = 0
        self.t = 0
        self.jump_t = 0
        self.dragging = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None
        
        # AI 相关
        self.ds_busy = False
        self.chat_history = []  # 对话历史
        self.max_history = 40   # 最多记录40条
        self._say_queue = []    # 后台线程→主线程的气泡消息队列
        
        # 聊天暂停标志
        self.chat_paused = False
        
        # 功能列表
        self.function_panel = FunctionPanel(self)
        self.food_panel = FoodPanel(self.on_food)
        # 单击延迟判定（等双击）：单击=回嘴+弹聊天面板，双击=喂食
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)
        
        # 聊天对话框
        self.chat_dialog = ChatDialog(self)

        # 办公便利贴 + 工作提醒
        self.ai_reply_sink = None      # 便利贴打开时，AI 回复直接进聊天区
        self._reply_queue = []
        self.work_store = WorkStore(os.path.join(APP_DIR, "work_items.json"))
        self.work_panel = WorkPanel(self.work_store, self)
        self.reminder_engine = ReminderEngine(self.work_store, self.say, self.work_panel.refresh,
                                              self._on_day_review)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.reminder_engine.check)
        self.reminder_timer.start(15000)
        QTimer.singleShot(4000, self.reminder_engine.startup_brief)

        # 长期记忆引擎（跨会话记忆 / 画像 / 回忆检索）
        self.memory = None
        self.memory_dashboard = None
        if MEMORY_AVAILABLE:
            try:
                self.memory = MemoryEngine(APP_DIR, api_provider=self._ai_api,
                                           logger=self._mem_log)
                QTimer.singleShot(3000, self._memory_startup)
            except Exception as e:
                print(f"[memory] 初始化失败：{e}")
                self.memory = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK)

        # 话唠模式（按记忆/聊天素材主动开口）
        self._last_user_ts = 0.0
        try:
            self.chatter = ChatterBox(
                self.cfg, save_cfg=self.save_cfg, memory=self.memory,
                work_store=self.work_store, api_getter=self._ai_api,
                state_path=os.path.join(APP_DIR, "chatter_state.json"),
                logger=print, user_active=self._user_active_recently,
                quiet=tuple(self.cfg.get("chatter_quiet") or ("23:00", "08:00")))
            self.chatter.sig_say.connect(self._on_chatter_line)
            QTimer.singleShot(12000, self.chatter.start)
        except Exception as e:
            print(f"[chatter] 初始化失败：{e}")
            self.chatter = None

        self.bubble_font = QFont("Microsoft YaHei UI", 11)

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)

    # ---------- 话唠模式 ----------
    def _user_active_recently(self):
        """3 分钟内你说过话，就别插嘴"""
        return time.time() - getattr(self, "_last_user_ts", 0.0) < 180

    def _on_chatter_line(self, text):
        self.say(text)
        try:
            if self.work_panel.isVisible():
                self.work_panel.append_chat("pet", text)
        except Exception:
            pass

    def set_chatter_level(self, lv):
        if not self.chatter:
            self.say("话唠模块没起来…")
            return
        self.say(self.chatter.set_level(lv))
        try:
            self.tray.setContextMenu(self._build_menu())
        except Exception:
            pass

    def _chatter_now(self):
        if not self.chatter:
            self.say("话唠模块没起来…")
            return
        msg = self.chatter.say_now()
        if msg:
            self.say(msg)

    # ---------- AI 方法 ----------
    def _api_key(self):
        return ai_settings.api_key(self.cfg)

    def _ai_api(self):
        """给记忆引擎用的接口配置（复用当前服务商的 key / base / model）"""
        return {"key": self._api_key(), "base": self._ai_base_url(),
                "model": self._ai_model()}

    def _mem_log(self, msg):
        print(f"[memory] {msg}")

    def _memory_startup(self):
        if not self.memory:
            return
        try:
            self.memory.startup()
        except Exception as e:
            self._mem_log(f"启动检查失败：{e}")

    # ---------- 记忆中心 ----------
    def open_memory_dashboard(self):
        if not self.memory:
            hint = "记忆引擎没起来" if MEMORY_AVAILABLE else f"记忆模块导入失败：{MEMORY_IMPORT_ERROR}"
            self.say("记忆模块没起来…")
            QMessageBox.warning(self, "记忆中心", hint + "\n看下 ai_error.log 或控制台输出")
            return
        try:
            if self.memory_dashboard is None:
                self.memory_dashboard = MemoryDashboard(self.memory, None)
            self.memory_dashboard.refresh()
            self.memory_dashboard.show()
            self.memory_dashboard.raise_()
            self.memory_dashboard.activateWindow()
        except Exception as e:
            QMessageBox.warning(self, "记忆中心", f"打不开：{e}")

    def _remember_dialog(self):
        if not self.memory:
            self.say("记忆模块没起来…")
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "让大肥鱼记住",
            "要它长期记住什么？\n（存为核心记忆，以后每次聊天都会带上）", "")
        if not (ok and text.strip()):
            return
        mid, _ = self.memory.manual_remember(text.strip(), "CORE", 9)
        self.jump_t = 1.0
        self.say("记住啦！忘不了" if mid else "这句没存下来")
        if self.memory_dashboard:
            try:
                self.memory_dashboard.refresh()
            except Exception:
                pass

    def _dream_now(self):
        if not self.memory:
            self.say("记忆模块没起来…")
            return
        self.say("我去整理一下记忆…")

        def worker():
            try:
                rep = self.memory.dreaming.run(do_extract=True)
                self._queue_say(f"整理好啦：合并{rep['merged']} 归档{rep['archived']}")
            except Exception as e:
                self._mem_log(f"整理失败：{e}")
                self._queue_say("整理失败了，看下日志")

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_memory(self, on):
        if not self.memory:
            return
        self.memory.set_enabled(bool(on))
        self.say("记忆开了，我记得住你" if on else "记忆关了，我啥也不记")

    def _ai_model(self):
        return ai_settings.model(self.cfg)

    def _ai_base_url(self):
        return ai_settings.base_url(self.cfg)

    @staticmethod
    def _clean_reply(text):
        """把模型返回的 content 洗成一句台词；判定为思维链/垃圾时返回空串"""
        t = (text or "").strip()
        t = t.strip('"“”\'‘’「」『』《》 \t\r\n')
        t = " ".join(t.split())
        if not t or _looks_like_reasoning(t):
            return ""
        if len(t) > 60:
            # 只留第一句，避免整段分析贴脸
            head = re.split(r"(?<=[。！？!?~～])", t)[0].strip()
            t = head if 2 <= len(head) <= 60 else t[:58] + "…"
        return t

    def _call_ds(self, user_msg):
        self._last_user_ts = time.time()
        if self.ds_busy:
            self.say("等等，上一句还没回完呢")
            return

        key = self._api_key()
        pname = ai_settings.title(self.cfg)
        if not key:
            self.say(f"先在右键「接口设置」里填上 {pname} 的 Key")
            return
        if not self._ai_model():
            self.say("模型名还没填，右键「接口设置」补一下")
            return

        self.ds_busy = True

        # 构建消息列表：有记忆引擎时由 Context Builder 组装
        # （人格 + 核心记忆 + 用户画像 + 相关旧事 + 最近对话），按 Token 预算裁剪
        messages = None
        if self.memory:
            try:
                ctx = self.memory.build_context(
                    user_msg,
                    fallback_history=self.chat_history[-self.max_history:],
                    personality=AI_SYSTEM)
                messages = ctx["messages"]
            except Exception as e:
                print(f"[memory] 上下文构建失败，退回纯聊天：{e}")
                messages = None
        if not messages:
            messages = [{"role": "system", "content": AI_SYSTEM}]
            messages.extend(self.chat_history[-self.max_history:])
            messages.append({"role": "user", "content": user_msg})

        model = self._ai_model()
        url = f"{self._ai_base_url()}/chat/completions"

        def worker():
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }

            def post(mdl, max_tokens=1024, timeout=45):
                return requests.post(url, json={
                    "model": mdl,
                    "messages": messages,
                    # 推理类模型会先消耗 reasoning tokens，上限给小了会拿不到正文
                    "max_tokens": max_tokens,
                }, headers=headers, timeout=timeout)

            def log_fail(mdl, resp):
                try:
                    with open(AI_ERROR_LOG, "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] model={mdl} "
                                f"status={resp.status_code} body={resp.text[:800]}\n")
                except Exception:
                    pass

            try:
                used = model
                fallback = ai_settings.default_model(self.cfg) or model
                resp = post(used)
                # 模型在 /models 列表里但上游没开（返回 404 openai_error）→ 自动降级
                if resp.status_code >= 400 and used != fallback and (
                        resp.status_code == 404 or "model" in (resp.text or "").lower()):
                    log_fail(used, resp)
                    print(f"[{pname}] {used} 不可用({resp.status_code})，降级到 {fallback}")
                    used = fallback
                    resp = post(used)

                if resp.status_code == 200:
                    data = resp.json()
                    ch = (data.get("choices") or [{}])[0]
                    msg = ch.get("message") or {}
                    reply = self._clean_reply(msg.get("content"))
                    if not reply:
                        # 思维链把预算吃光 → 正文为空；加大预算重试一次
                        try:
                            usage = data.get("usage") or {}
                            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                        except Exception:
                            rt = None
                        print(f"[{pname}] 正文为空（finish={ch.get('finish_reason')}, "
                              f"reasoning_tokens={rt}），加大预算重试")
                        resp2 = post(used, max_tokens=4000, timeout=60)
                        if resp2.status_code == 200:
                            msg2 = (resp2.json().get("choices") or [{}])[0].get("message") or {}
                            reply = self._clean_reply(msg2.get("content"))
                        else:
                            log_fail(used, resp2)
                    if not reply:
                        self._reply_out(random.choice(NOTHING_LINES))
                        return
                    full = reply
                    short = full if len(full) <= 30 else full[:28] + "…"
                    if used != model:
                        # 降级后把配置改回可用模型，下次不再白跑一次
                        ai_settings.save_profile(self.cfg, ai_settings.active_id(self.cfg),
                                                 key, self._ai_base_url(), used)
                        self.save_cfg()
                    # 存入历史（存完整回复，气泡只显示短的）
                    self.chat_history.append({"role": "user", "content": user_msg})
                    self.chat_history.append({"role": "assistant", "content": full})
                    if len(self.chat_history) > self.max_history:
                        self.chat_history = self.chat_history[-self.max_history:]
                    # 落库 + 按需触发后台记忆提取（失败不影响聊天）
                    if self.memory:
                        try:
                            self.memory.record_exchange(user_msg, full)
                        except Exception as e:
                            print(f"[memory] 记录会话失败：{e}")
                    self._reply_out(short, full)
                else:
                    log_fail(used, resp)
                    self._reply_out(self._friendly_error(resp))
            except requests.exceptions.Timeout:
                self._reply_out("请求超时，检查网络")
            except requests.exceptions.ConnectionError:
                self._reply_out("连接失败，检查网络")
            except Exception as e:
                self._reply_out(f"请求失败: {str(e)[:12]}")
            finally:
                self.ds_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _reply_out(self, bubble_text, full_text=None):
        """AI 回复出口：便利贴开着就进聊天区，否则冒气泡"""
        if self.ai_reply_sink:
            self._reply_queue.append(full_text or bubble_text)
        else:
            self._queue_say(bubble_text)

    def _friendly_error(self, resp):
        """把网关的英文错误码翻译成能看懂的气泡"""
        code = resp.status_code
        body = (resp.text or "").lower()
        pname = ai_settings.title(self.cfg)
        if code == 401 or code == 403:
            return "Key 不对，右键「接口设置」重填"
        if code == 402:
            return "余额不足了…"
        if code == 404 or "model" in body:
            return "这个模型没开，右键换个模型"
        if code == 429:
            return "说太快了，歇一会儿"
        if code >= 500:
            return f"{pname} 服务抽风了，等下再试"
        return f"接口出错 {code}，详情见 ai_error.log"

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self.t * TICK / 1000.0

        if self.bubble_text and now < self.bubble_until:
            bfont = QFont(self.bubble_font)
            bfont.setPointSize(self.bubble_pt)
            if self.bubble_inner:
                bfont.setItalic(True)
                bg, fg = QColor(232, 232, 238, 235), QColor(125, 125, 138)
            else:
                bg, fg = QColor(255, 255, 255, 235), QColor(60, 60, 80)
            fm = QFontMetrics(bfont)
            max_w = min(240, self.width() - 16)
            words = self.bubble_text
            lines = []
            cur = ""
            for ch in words:
                if fm.horizontalAdvance(cur + ch) > max_w - 20:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            # 窗口窄（极小档）时行数会变多：超了就截断加省略号，别糊到鱼脸上
            max_lines = max(2, int((self.bubble_h - 16) / max(1, fm.height())))
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1][:-1] + "…"
            bw = max(fm.horizontalAdvance(l) for l in lines) + 20
            bh = len(lines) * fm.height() + 14
            bx = (self.width() - bw) / 2
            by = 6.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)
            tail = QPointF(self.width() / 2, by + bh)
            p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 6, tail.y() + 8), QPointF(tail.x() + 6, tail.y() + 8)]))
            p.setPen(fg)
            p.setFont(bfont)
            for i, l in enumerate(lines):
                p.drawText(QRectF(bx, by + 7 + i * fm.height(), bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, l)

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        running = walking and self.mode == "line" and self.run_mode
        if walking:
            if running:                       # 跑步：步子快、颠得高
                sway = math.sin(now * 13.0) * 2.6
                bob = -abs(math.sin(now * 7.0)) * 11.0
            else:                             # 走路：慢悠悠晃
                sway = math.sin(now * 9.0) * 3.5
                bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        breath = 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing = key
            pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy)
            pw = pix.width() * scale * (1 + act_sx)
            dx = cx - pw / 2
            bottom = self.bubble_h + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            if facing < 0:
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        cur_key = self._sprite_key()
        if self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _sprite_key(self):
        name = {"left": "侧面", "right": "侧面", "up": "背面", "down": "正面"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1

        # 处理后台线程（DeepSeek 等）排队的气泡消息，Qt 界面必须在主线程更新
        if self._say_queue:
            for text in self._say_queue:
                self.say(text)
            self._say_queue.clear()

        # 便利贴聊天区的 AI 回复（同样需要主线程更新）
        if self._reply_queue:
            sink = self.ai_reply_sink
            texts = self._reply_queue[:]
            self._reply_queue.clear()
            if sink:
                for text in texts:
                    try:
                        sink(text)
                    except Exception as e:
                        print("[chat] 追加失败:", e)

        self.check_system_status()
        
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None
        
        if self.chat_paused:
            self.update()
            return
        
        if self.dragging:
            self.update()
            return
        now_ms = self.t * TICK

        if self.mode == "follow":
            cursor = self.cursor().pos()
            screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            near = (self.x() - 100 <= cursor.x() <= self.x() + self.width() + 100 and
                    self.y() - 100 <= cursor.y() <= self.y() + self.height() + 100)
            if near:
                self.target = None
            else:
                tx = max(geo.left(), min(geo.right() - self.width(), cursor.x() - self.width() / 2))
                ty = max(geo.top(), min(geo.bottom() - self.height(), cursor.y() - 90))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action()
                    self.update()
                    return
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.target = (random.randint(geo.left() + 40, geo.right() - self.width() - 40),
                               random.randint(geo.top() + 40, geo.bottom() - self.height() - 40))
        elif self.mode == "line":
            if not self._line_target(now_ms):
                self.update()
                return
        else:
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None:
            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * TICK + random.randint(8000, 18000)
                if self.mode == "line":
                    self.run_mode = False
                self._set_dir("down")
            else:
                step = self.cur_speed * TICK / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                self.move(int(nx - self.width() / 2), int(ny - self.height() / 2))
                if self.mode == "line":
                    # 横向行走：锁死高度，只改 x，免得走两步就漂到天花板
                    if self.line_y is None:
                        self.line_y = self.y()
                    self.move(self.x(), int(self.line_y))
                if abs(dx) > abs(dy) * 1.15:
                    self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                else:
                    self._set_dir("up" if dy < 0 else "down")
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = self._speed_now()
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def _speed_now(self):
        """目标速度：横向行走每段路随机「走」或「跑」"""
        if self.target is None:
            return 0.0
        if self.mode == "line" and self.run_mode:
            return SPEED * RUN_FACTOR
        return SPEED

    def _line_target(self, now_ms):
        """横向行走：只在当前高度左右移动，走完歇一会儿"""
        if self.target is not None:
            return True
        if now_ms < self.rest_until:
            self._line_idle()
            return False

        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        lo = geo.left() + 6
        hi = geo.right() - self.width() - 6
        if hi <= lo + 60:
            self.rest_until = now_ms + 4000
            return False

        self.line_y = self.y()
        cur = self.x()
        side = 1 if random.random() < 0.5 else -1
        tx = cur + side * random.randint(180, 760)
        if tx < lo or tx > hi:                 # 撞边就往另一边去
            tx = hi if tx < lo else lo
        if abs(tx - cur) < 90:                 # 太近了没意思，走到另一头
            tx = hi if cur < (lo + hi) / 2 else lo
        self.target = (tx + self.width() / 2, self.y() + self.height() / 2)
        self.run_mode = random.random() < 0.3  # 三成概率跑起来
        self.cur_speed = 0.0
        return True

    def _line_idle(self):
        """横向行走停下来时：站着 / 转身背对 / 蹦一下"""
        if random.random() < 0.05:
            pick = random.random()
            if pick < 0.45:
                self._set_dir("down", 1)                       # 正面站着
            elif pick < 0.85:
                self._set_dir("up", 1)                         # 背身
            else:
                self._set_dir("left" if self.facing < 0 else "right", self.facing)  # 侧身
        self._maybe_idle_action()

    def _maybe_idle_action(self):
        if random.random() < 0.01:
            pick = random.random()
            if pick < 0.35:
                self.jump_t = 1.0
            elif pick < 0.6:
                self.action, self.action_t = "sway", 1.0
            elif pick < 0.8:
                self.action, self.action_t = "stretch", 1.0
            elif pick < 0.9:
                if self.t - self.last_speak_tick >= 1500:
                    self.last_speak_tick = self.t
                    if pick < 0.82:
                        self.say(random.choice(INNER_LINES), inner=True)
                    else:
                        self.say(random.choice(LINES))

    def _queue_say(self, text):
        """后台线程调用：只入队，由主线程 tick 统一弹出显示（线程安全）"""
        self._say_queue.append(text)

    def say(self, text, inner=False):
        if text == self.last_line and not text.startswith("天气"):
            return
        self.last_line = text
        self.bubble_inner = inner
        self.bubble_text = f"（{text}）" if inner else text
        self.bubble_until = self.t * TICK / 1000.0 + 2.8
        self.update()

    def check_system_status(self):
            now = self.t * TICK

            if now - getattr(self, "last_system_check", 0) < 10000:
                return

            self.last_system_check = now

            cpu = psutil.cpu_percent()

            if cpu >= 90:
                self.say("CPU跑满了，再这样下去我就卡死了")
                return

            ram = psutil.virtual_memory().percent

            if ram >= 95:
                self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
                return

            if GPU_AVAILABLE:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle,
                        pynvml.NVML_TEMPERATURE_GPU
                    )

                    if temp > 80:
                        self.say("我感觉我的鱼鳍快熟了")

                except Exception as e:
                    print("GPU读取失败:", e)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self.drag_start_pos = e.globalPosition().toPoint()
            self.function_panel.hide()
            self.chat_dialog.hide()
            self.chat_paused = True

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
                if self.work_panel.isVisible():
                    self.work_panel.hide()
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.line_y = self.y()          # 拖到哪就在哪条线上走
                self.rest_until = self.t * TICK + random.randint(6000, 14000)
                if random.random() < 0.5:
                    self.say(random.choice(DRAG_LINES))
                self.chat_paused = False
            else:
                self._click_timer.start(280)  # 等双击判定；单击则回嘴+弹聊天面板
            self.last_press_pos = None
            self.drag_start_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.food_panel.popup_at(self.x() + self.width() / 2, self.y() + self.bubble_h)

    def _on_single_click(self):
        """单击：蹦跳回嘴 + 弹出办公便利贴（再点一次收起）"""
        if random.random() < 0.7:
            self.jump_t = 1.0
        if random.random() < 0.6:
            self.say(random.choice(REACT_LINES))
        self.toggle_work_panel()

    def toggle_work_panel(self):
        if self.work_panel.isVisible():
            self.work_panel.hide_anim()
        else:
            self.open_work_panel()

    def open_work_panel(self):
        """在桌宠上方弹出便利贴（空间不够就弹在下方）"""
        screen = self.screen() or QApplication.primaryScreen()
        g = screen.availableGeometry()
        w, h = self.work_panel.W, self.work_panel.H
        x = self.x() + self.width() / 2 - w / 2
        x = max(g.left() + 8, min(g.right() - w - 8, x))
        y = self.y() - h - 12
        if y < g.top() + 8:
            y = min(g.bottom() - h - 8, self.y() + self.height() + 12)
        self.work_panel.popup_at(int(x), int(y))

    def on_food(self, food):
        self.food_panel.hide()
        self.eat_t = 1.0
        self.jump_t = 0.6
        lines = FOOD_LINES.get(food, ["好吃！"])
        self.say(random.choice(lines))

    def _show_chat_dialog(self):
        """🗨️ 图标：打开便利贴并定位到输入框"""
        self.open_work_panel()
        self.work_panel.input.setFocus()

    def _open_work_settings(self):
        dlg = WorkSettingsDialog(self.work_store, self.work_panel)
        dlg.exec()
        self.work_panel.refresh()

    def _on_day_review(self, items):
        """下班回顾：便利贴里列出今天全部工作，托盘再推一条"""
        try:
            self.work_panel.append_review(items)
            if not self.work_panel.isVisible():
                self.open_work_panel()
        except Exception as e:
            print("[review] 便利贴展开展示失败:", e)
        try:
            done = sum(1 for i in items if i.get("done"))
            head = f"今日工作回顾 · {done}/{len(items)} 完成"
            body = "\n".join(("✓ " if i.get("done") else "○ ") +
                             f"{item_label(i)} {i['content']}" for i in items[:8])
            if len(items) > 8:
                body += f"\n…还有 {len(items) - 8} 条"
            self.tray.showMessage(head, body, self.icon, 8000)
        except Exception as e:
            print("[review] 托盘提示失败:", e)

    """def _get_city_by_ip(self):
        try:
            r = requests.get("http://ip-api.com/json/?fields=city&lang=zh-CN", timeout=5)
            if r.status_code == 200:
                city = r.json().get("city", "")
                if city:
                    return city
        except:
            pass
        return "汕头" """

    def _get_weather(self):
        try:
            city = self.cfg.get("city", "汕头")
            print("当前城市:", city)

            url = f"https://wttr.in/{city}?format=j1"

            r = requests.get(
                url,
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            print("状态:", r.status_code)
            print(r.text[:500])

            data = r.json()

            weather = data["current_condition"][0]

            temp = weather["temp_C"]

            weather_map = {
                "Sunny": "晴",
                "Clear": "晴",
                "Partly cloudy": "多云",
                "Cloudy": "阴",
                "Light rain": "小雨",
                "Moderate rain": "中雨",
                "Heavy rain": "大雨"
            }

            raw_weather = weather["weatherDesc"][0]["value"]

            desc = weather_map.get(raw_weather, raw_weather)

            self.say(f"{city}今天{temp}°，天气{desc}")

        except Exception as e:
            print("天气错误:", repr(e))
            self.say("天气获取失败")
    

    def _build_menu(self):
        m = QMenu(self)
        mode_menu = m.addMenu("模式")
        for label, key in MODES:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        size_menu = m.addMenu("大小")
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))
        model_menu = m.addMenu(f"AI 模型（{ai_settings.title(self.cfg)}）")
        cur_model = self._ai_model()
        for mdl in ai_settings.models(self.cfg):
            a = model_menu.addAction(mdl)
            a.setCheckable(True)
            a.setChecked(cur_model == mdl)
            a.triggered.connect(lambda _, k=mdl: self._set_model(k))
        model_menu.addSeparator()
        model_menu.addAction("接口设置…", self._open_ai_settings)
        m.addAction("⚙ 接口设置（DeepSeek / Agnes / 自定义）", self._open_ai_settings)

        # 话唠模式：关 / 1 / 2 / 3 级
        chat_menu = m.addMenu("🗣 话唠模式")
        cur_lv = self.chatter.level() if getattr(self, "chatter", None) else 0
        for lv in (0, 1, 2, 3):
            if lv == 0:
                a = chat_menu.addAction("关闭（安静）")
            else:
                spec = CHATTER_LEVELS[lv]
                a = chat_menu.addAction(f"{lv} 级 · {spec['window_h']} 小时 "
                                        f"{spec['lo']}-{spec['hi']} 条")
            a.setCheckable(True)
            a.setChecked(cur_lv == lv)
            a.triggered.connect(lambda _, k=lv: self.set_chatter_level(k))
        chat_menu.addSeparator()
        cnt = self.chatter.today_count() if getattr(self, "chatter", None) else 0
        info = chat_menu.addAction(f"今天已经念叨 {cnt} 句")
        info.setEnabled(False)
        act = chat_menu.addAction("现在说一句（试试）", self._chatter_now)
        act.setEnabled(self.chatter is not None)

        m.addAction("查看天气", self._get_weather)
        m.addSeparator()
        m.addAction("📌 今日工作 / 便利贴", self.open_work_panel)
        m.addAction("⏰ 工作提醒设置", self._open_work_settings)
        m.addSeparator()
        mem_menu = m.addMenu("🧠 长期记忆")
        mem_menu.addAction("记忆中心…", self.open_memory_dashboard)
        mem_menu.addAction("让大肥鱼记住…", self._remember_dialog)
        mem_menu.addAction("立即整理记忆", self._dream_now)
        mma = mem_menu.addAction("长期记忆开关")
        mma.setCheckable(True)
        mma.setChecked(self.memory.enabled() if self.memory else False)
        mma.setEnabled(self.memory is not None)
        mma.triggered.connect(self._toggle_memory)
        m.addSeparator()
        # 动画库（114 段 640×360 VP9-alpha 透明动画）
        try:
            _n = len(anim_lib.animations())
        except Exception:
            _n = 0
        m.addAction(f"🎬 动画库（{_n} 段）" if _n else "🎬 动画库", self._open_anim_library)
        m.addSeparator()
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        ta = m.addAction("窗口置顶")
        ta.setCheckable(True)
        ta.setChecked(self.cfg["topmost"])
        ta.triggered.connect(lambda on: self.set_topmost(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg["autostart"])
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        return m

    def _open_ai_settings(self):
        """接口设置面板：DeepSeek / Agnes / 自定义 OpenAI 兼容"""
        def saved():
            self.save_cfg()
            prof = ai_settings.profile(self.cfg)
            self.say(f"换成 {ai_settings.title(self.cfg)} 了" if prof["key"]
                     else "配置存好了，Key 还没填")

        try:
            dlg = AISettingsDialog(self.cfg, on_saved=saved, parent=None)
            dlg.move(self.x() + self.width() // 2 - 260,
                     max(0, self.y() + self.height() // 2 - 224))
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "接口设置", f"面板打不开：{e}")

    def _open_anim_library(self):
        """动画库：浏览 / 播放 dsh-pet/assets 下的透明动画"""
        try:
            dlg = anim_lib.AnimLibraryDialog(parent=None)
            dlg.move(max(0, self.x() + self.width() // 2 - 430),
                     max(0, self.y() + self.height() // 2 - 280))
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "动画库", f"面板打不开：{e}")

    def _set_model(self, model):
        p = ai_settings.profile(self.cfg)
        ai_settings.save_profile(self.cfg, ai_settings.active_id(self.cfg),
                                 p["key"], p["base"], model)
        self.save_cfg()
        self.say(f"换成 {model} 了")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray.setContextMenu(self._build_menu())
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def contextMenuEvent(self, e):
        self._build_menu().exec(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        if mode not in MODE_KEYS:
            return
        self.mode = mode
        self.target = None
        self.cur_speed = 0.0
        self.line_y = self.y()
        self.cfg["mode"] = mode
        self.save_cfg()
        label = dict((k, l) for l, k in MODES).get(mode, mode)
        self.say({"line": "我沿着地面左右溜达～",
                  "wander": "随便逛逛去",
                  "follow": "跟你走啦",
                  "still": "那我在这儿待着"}.get(mode, label))

    def _apply_size_metrics(self):
        """按当前身高重算窗口；「极小」档额外加高、加宽，别让气泡挤成一条"""
        try:
            mult = float(self.cfg.get("size", 0.7))
        except (TypeError, ValueError):
            mult = 0.7
        self.cur_h = max(60, int(340 * mult))
        heights = sorted({k[1] for k in self.sprites})
        if heights and self.cur_h not in heights:      # 配置里的旧值/怪值兜底
            self.cur_h = min(heights, key=lambda x: abs(x - self.cur_h))
        tiny = self.cur_h < 120
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.bubble_h = BUBBLE_H if not tiny else 88     # 气泡可用高度
        self.bubble_pt = 11 if not tiny else 10          # 气泡字号
        widths = [p.width() for k, p in self.sprites.items() if k[1] == self.cur_h]
        self.win_w = (max(widths) if widths else self.cur_h) + self.win_mx * 2
        if tiny:
            self.win_w = max(self.win_w, 168)            # 至少能放下一行 10 个字
        self.setFixedSize(self.win_w, self.cur_h + self.bubble_h + MARGIN * 2 + 10)

    def set_size(self, mult):
        old_h = self.height()
        self.cfg["size"] = mult
        self.cross_t = 0.0
        self.prev_key = None
        self._apply_size_metrics()
        dy = self.height() - old_h
        if dy:
            self.move(self.x(), self.y() - dy)      # 脚底不动，往上长
        if self.mode == "line":
            self.line_y = self.y()
        self.snap_into_screen()
        self.save_cfg()
        self.update()
        label = next((l for l, m in SIZE_LEVELS.items() if abs(m - mult) < 1e-6), "")
        self.say(f"变成{label}号了" if label else "换了个大小")

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _apply_passthrough(self, on):
        hwnd = int(self.winId())
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED
        if on:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._apply_passthrough(bool(on))
        if on:
            self.say("我隐身了！右键托盘图标解除～")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_autostart(self, on):
        self.cfg["autostart"] = bool(on)
        lnk = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", "大肥鱼桌宠.lnk")
        try:
            if on:
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';$s.Save()"
                      .format(lnk, PYTHONW,
                              "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                              APP_DIR))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                self.say("已开机自启，明天见～")
            else:
                if os.path.exists(lnk):
                    os.remove(lnk)
                self.say("已取消开机自启")
        except Exception as ex:
            QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def save_cfg(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[config] 保存失败:", e)

    def quit_app(self):
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        self.save_cfg()
        # 退出前把今天聊的整理进长期记忆（限时，超时留给下次启动继续）
        if self.memory:
            try:
                self.say("记一下今天的事…")
                QApplication.processEvents()
                self.memory.shutdown()
            except Exception as e:
                self._mem_log(f"退出整理失败：{e}")
        self.tray.hide()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "大肥鱼桌宠出错", str(ex))
        except Exception:
            pass
        raise