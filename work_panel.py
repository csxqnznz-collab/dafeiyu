# -*- coding: utf-8 -*-
"""办公便利贴 + 工作提醒引擎（大肥鱼桌宠扩展模块）

包含：
    WorkStore            今日工作条目的存取
    ReminderParser       中文时间语句解析（"提醒我下午两点半有重要会议"）
    WorkItemRow          单条工作内容（彩色半透明标签，点击切换完成）
    WorkPanel            便利贴窗口（上 1/3 工作内容 + 下 2/3 聊天）
    WorkSettingsDialog   上下班 / 各类提醒时间与文案设置
    ReminderEngine       到点提醒（含开机汇总、午休、打卡、下班）
"""

import json
import os
import re
import uuid
from datetime import datetime

from PySide6.QtCore import (Qt, QRect, QTime, QPropertyAnimation, QEasingCurve,
                            QTimer, Signal, QObject)
from PySide6.QtGui import QColor, QFont, QIcon, QTextCursor, QTextBlockFormat
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QHBoxLayout, QScrollArea, QTextBrowser, QMenu, QDialog,
                               QFormLayout, QTimeEdit, QSpinBox, QCheckBox, QDialogButtonBox,
                               QGraphicsOpacityEffect, QSizePolicy, QApplication, QGridLayout)

# ---------- 配色：浅色半透明标签 ----------
TAG_COLORS = [
    {"bg": "rgba(255, 208, 222, 205)", "fg": "#8a3450"},   # 粉
    {"bg": "rgba(208, 228, 255, 205)", "fg": "#2b4d78"},   # 蓝
    {"bg": "rgba(211, 242, 216, 205)", "fg": "#2c6440"},   # 绿
    {"bg": "rgba(255, 236, 197, 205)", "fg": "#7a5320"},   # 黄
    {"bg": "rgba(228, 217, 255, 205)", "fg": "#4a3a78"},   # 紫
    {"bg": "rgba(255, 223, 205, 205)", "fg": "#7c4327"},   # 橙
    {"bg": "rgba(206, 240, 240, 205)", "fg": "#1f5f5f"},   # 青
]

DEFAULT_SETTINGS = {
    "enabled": True,
    "work_start": "09:00",
    "work_end": "18:00",
    "lunch": "12:00",
    "clock_in": "13:30",
    "clock_in_advance": 5,
    "afternoon": "14:00",
    "auto_done_minutes": 30,
    "morning_enabled": True,
    "morning_msg": "早上好！今天这几件要做：{list}",
    "lunch_msg": "该好好吃饭啦，别忘了晚上打卡~",
    "clock_in_adv_msg": "还有 {adv} 分钟上班，准备打卡吧",
    "clock_in_msg": "到点啦，快去上班打卡！",
    "afternoon_msg": "下午的安排：{list}",
    "off_msg": "下班啦，别忘了打卡！",
    "review_enabled": True,
    "review_msg": "今天的工作都完成了么？{list}",
}


def _hm_to_min(hm):
    try:
        h, m = str(hm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return -1


def _fade(hex_color, alpha=95):
    """把 #rrggbb 变成半透明 rgba，用于已完成条目"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ---------------------------------------------------------------- 存储
class WorkStore:
    """按日期保存工作条目与当日提醒标记"""

    def __init__(self, path):
        self.path = path
        self.data = {"settings": dict(DEFAULT_SETTINGS), "days": {}}
        self.load()

    # -- 持久化
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                s = dict(DEFAULT_SETTINGS)
                s.update(d.get("settings") or {})
                days = d.get("days") or {}
                self.data = {"settings": s, "days": days if isinstance(days, dict) else {}}
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[work] 保存失败:", e)

    # -- 设置
    @property
    def settings(self):
        return self.data["settings"]

    def update_settings(self, **kw):
        self.settings.update(kw)
        self.save()

    # -- 当日数据
    def today_key(self):
        return datetime.now().strftime("%Y-%m-%d")

    def day(self, key=None):
        key = key or self.today_key()
        d = self.data["days"].setdefault(key, {})
        d.setdefault("items", [])
        d.setdefault("flags", {})
        return d

    def items(self):
        its = self.day()["items"]
        # soft（没给具体时间）的排在同时间点的后面，其余保持录入顺序
        return sorted(its, key=lambda x: (_hm_to_min(x.get("time", "00:00")),
                                          1 if x.get("soft") else 0))

    def flags(self):
        return self.day()["flags"]

    def has_flag(self, key):
        return bool(self.day()["flags"].get(key))

    def set_flag(self, key, val=True):
        self.day()["flags"][key] = val
        self.save()

    # -- 条目
    def add(self, time_str, content, color=None, period=None, soft=False):
        its = self.day()["items"]
        content = (content or "").strip()
        if not content:
            return None
        for old in its:
            if old.get("content", "").strip() == content:
                return None       # 今天已经记过同一条，不重复添加
        if color is None:
            color = len(its) % len(TAG_COLORS)
        item = {
            "id": uuid.uuid4().hex[:8],
            "time": time_str,
            "content": content,
            "color": color,
            "done": False,
            "remind": True,
            "fired": False,
            "soft": bool(soft),
            "period": period or "",
        }
        its.append(item)
        self.save()
        return item

    def get(self, item_id):
        for it in self.day()["items"]:
            if it.get("id") == item_id:
                return it
        return None

    def update(self, item_id, **kw):
        it = self.get(item_id)
        if it:
            it.update(kw)
            self.save()
        return it

    def remove(self, item_id):
        d = self.day()
        d["items"] = [i for i in d["items"] if i.get("id") != item_id]
        self.save()

    def auto_done(self):
        """超过时间 + 宽限分钟后仍未处理 → 视为完成（变半透明）

        没有具体时间（soft）的条目不自动完成 —— 它们在 18:00 会走「今天都完成了么」
        的回顾，由用户自己打勾。
        """
        grace = int(self.settings.get("auto_done_minutes", 30))
        cur = datetime.now().hour * 60 + datetime.now().minute
        changed = False
        for it in self.day()["items"]:
            if it.get("soft"):
                continue
            if not it.get("done") and cur - _hm_to_min(it.get("time")) >= grace:
                it["done"] = True
                changed = True
        if changed:
            self.save()
        return changed


# ---------------------------------------------------------------- 时间解析
CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

TIME_RE = re.compile(
    r"(?:(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里)\s*)?"
    r"([0-9零〇一二两三四五六七八九十]{1,3})\s*(?:点|时|[:：])\s*"
    r"((?:[0-9零〇一二两三四五六七八九十]{1,3})(?!刻))?\s*(半|一刻|三刻|分)?"
)

FILLERS = ["提醒我一下", "提醒我", "提醒一下", "提醒", "记得", "记一下", "记录一下",
           "记录下来", "记录", "待办事项", "待办", "安排一下", "安排", "我要", "我需要",
           "今天", "今日", "明天", "后天", "上午", "下午", "晚上", "中午", "在", "我", "要", "去", "有",
           "的时候", "时候", "这件事", "这事儿"]

PERIOD_WORDS = "凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里"

# 句首表头：「我下午的工作：」「今天的工作安排：」「任务：」
HEADER_RE = re.compile(
    r"^\s*(?:我|今天|今日|明天|本周|这周)?\s*(?:的)?\s*(?:(" + PERIOD_WORDS + r")\s*)?(?:的)?\s*"
    r"(?:工作内容|工作任务|工作计划|工作安排|工作|任务|安排|待办事项|待办|事项|计划|事情|要做的事)\s*"
    r"(?:是|有|包括|如下|为)?\s*[:：]?\s*"
)

# 明确在交代待办的说法（强意图）
INTENT_STRONG = re.compile(r"提醒|记一下|记录|待办|别忘|别忘了|记得|需要做|要做")

# 清单式表头：「我下午的工作：」「任务：」「今日待办：」
# 注意不能只认「工作」两个字 —— 「怎么工作」「没工作」也会命中
INTENT_HEADER = re.compile(
    r"工作内容|工作任务|工作计划|工作安排|的工作|的任务|任务[:：]|待办事项|待办[:：]|清单|做一些事")

# 明确的提问（带这些就是闲聊，不管有没有干活动词）
CHAT_Q = re.compile(r"[？?]|吗|呢|是不是|有没有|能不能|可不可以|要不要|会不会|了没|了么|对吧")
# 语气 / 感叹词（没有干活动词时视为闲聊）
CHAT_TONE = re.compile(r"吧|啊|呀|嘛|哎|唉|哈哈|呜呜|好累|真难|烦死|郁闷|无聊")
# 疑问词（没有干活动词时视为闲聊）
CHAT_WH = re.compile(r"怎么|为什么|为啥|如何|什么|啥|在哪|凭什么|难道")
# 自问自答式吐槽：「那我怎么工作」「你咋不早说」
CHAT_SELF = re.compile(r"(?:我|你|咱|他|她|大家).{0,8}(?:怎么|为什么|为啥|凭什么|咋)")

# 双字以上的业务动词：出现它，说明这句大概率真在说事，可豁免语气词判定
STRONG_VERB = re.compile(
    r"开会|会议|沟通|对接|跟进|处理|完成|提交|汇报|整理|报价|联系|发送|撰写|评审|面试|"
    r"培训|复盘|确认|准备|安排|统计|上传|下单|打样|发货|拜访|签约|盘点|对账|审核|打包|"
    r"回访|讨论|优化|询价|谈判|催|发货|开会|排期|改稿|提案|交付|验收|结账|报备"
)

# 判断一段话是不是「干活」的兜底动词（只有时段、没有时间的清单也能认出来）
WORK_VERB = re.compile(
    r"开会|会议|沟通|对接|跟进|处理|完成|提交|汇报|整理|报价|联系|发送|撰写|写|做|交|评审|"
    r"面试|培训|复盘|确认|准备|安排|统计|上传|下单|打样|发货|拜访|签约|盘点|对账|审核|打包|"
    r"问|询价|讨论|优化|催"
)

# 剥完词之后如果只剩这些，说明不是一个有效条目
STOP_CONTENT = {"工作", "任务", "安排", "待办", "事项", "计划", "事情", "内容",
                "一下", "今天", "明天", "的工作", "的"}


def _cn2int(s):
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s in CN_NUM:
        return CN_NUM[s]
    if "十" in s:
        a, b = s.split("十", 1)
        h = CN_NUM.get(a, 1) if a else 1
        m = CN_NUM.get(b, 0) if b else 0
        return h * 10 + m
    return None


def _to_24h(h, period):
    if period in ("下午", "傍晚", "晚上", "夜里"):
        return h + 12 if h < 12 else h
    if period == "中午":
        if h == 12:
            return 12
        return h + 12 if h < 11 else h
    if period == "凌晨":
        return 0 if h == 12 else h
    if period in ("早上", "早晨", "上午"):
        return h
    # 没有时段：1~6 点按下午理解（"两点半开会" → 14:30）
    return h + 12 if 1 <= h <= 6 else h


class Parsed(object):
    def __init__(self, time_str, content, period="", soft=False):
        self.time = time_str
        self.content = content
        self.period = period or ""
        self.soft = bool(soft)      # True = 没给具体时间，默认下班前完成

    @property
    def label(self):
        """界面上时间列显示的内容：具体时间，或「下午」这类时段"""
        if self.soft:
            return self.period or "下班前"
        return self.time

    def __repr__(self):
        return f"Parsed({self.label}, {self.content})"


def item_label(it):
    """条目的时间列文案（soft 条目显示时段，不显示 18:00 这种硬时间）"""
    if it.get("soft"):
        return it.get("period") or "下班前"
    return it.get("time", "--:--")


def _clean_content(s):
    s = (s or "").strip().strip(" \t，,。.、:：!！?？~～")
    changed = True
    while changed:
        changed = False
        for f in FILLERS:
            if s.startswith(f):
                s = s[len(f):].lstrip(" ，,、的")
                changed = True
                break
    s = re.sub(r"^(的|地|得|把|给)+", "", s)
    return s.strip(" \t，,。.、:：!！?？~～")


def _split_items(text):
    """按分号 / 顿号 / 换行拆成多条；只有明确是清单表头时，才用逗号继续拆"""
    parts = re.split(r"[；;\n\r]+", text)
    out = []
    for p in parts:
        for x in re.split(r"[、]+", p):
            x = x.strip()
            if x:
                out.append(x)
    # 逗号拆分要求有清单表头（「我下午的工作：」「任务：」），
    # 否则「键盘都是粑粑 那我怎么工作，没工作怎么有钱」这类闲聊会被拆成三条
    if len(out) == 1 and INTENT_HEADER.search(text):
        segs = [x.strip() for x in re.split(r"[,，]+", out[0]) if x.strip()]
        if len(segs) >= 3:
            return segs
    return out


def _looks_like_chat(seg):
    """反问 / 感叹 / 吐槽，不算工作条目

    分级判定，避免误杀正常条目（如「下午问客户什么价位」含疑问词但是正事）：
      1. 带「吗/呢/？」这类明确提问 → 一律当闲聊
      2. 有语气词 / 疑问词，但没有业务动词 → 当闲聊
    """
    s = (seg or "").strip()
    if not s:
        return False
    if CHAT_Q.search(s):
        return True
    # 句子里有业务动作（问客户 / 跟进 / 对账…），就算带疑问词也当正事；
    # 是否真的记账还有后续 soft_ok 把关，所以这里可以放宽
    if STRONG_VERB.search(s) or WORK_VERB.search(s):
        return False
    return bool(CHAT_TONE.search(s) or CHAT_WH.search(s) or CHAT_SELF.search(s))


class ReminderParser:
    """把自然语言解析成工作条目，一次可以拆出多件事

    两种说法都认：
        1. 有具体时间：「提醒我下午两点半有重要会议」→ 14:30 重要会议
        2. 只有时段 / 清单：「我下午的工作：和IT沟通网站；广告对标；拿到物料」
           → 三条，都按时段（下午）归到下班时间结束
    """

    @staticmethod
    def parse_many(text, work_end="18:00", limit=12):
        raw = (text or "").strip()
        if not raw:
            return []
        segs = _split_items(raw)
        if not segs:
            return []

        # 意图：要么明确在交代待办（提醒/记得/待办…），要么是清单表头（我下午的工作：）
        # 只出现「工作」两个字不算 —— 否则「怎么工作」「没工作」都会被误判
        intent = bool(INTENT_STRONG.search(raw) or INTENT_HEADER.search(raw))
        colon_header = bool(re.match(r"^[^：:\n]{1,12}[：:]", raw)) and bool(INTENT_HEADER.search(raw))

        # 整句开头的时段：「我下午的工作：……」
        period = ""
        pm = re.match(r"^\s*(?:我|今天|今日|明天)?\s*(?:的)?\s*(" + PERIOD_WORDS + r")", raw)
        if pm:
            period = pm.group(1)

        parsed, explicit, chat_like, header_hit = [], 0, False, False

        for seg in segs:
            seg = seg.strip()
            if not seg:
                continue
            seg_header = False
            hm = HEADER_RE.match(seg)
            if hm:
                header_hit = True
                seg_header = True
                if hm.group(1):
                    period = period or hm.group(1)
                rest_seg = seg[hm.end():].strip()
                if rest_seg:
                    seg = rest_seg

            tm = TIME_RE.search(seg)
            if tm:
                hour = _cn2int(tm.group(2))
                minute = _cn2int(tm.group(3)) or 0
                suffix = tm.group(4)
                if suffix == "半":
                    minute = 30
                elif suffix == "一刻":
                    minute = 15
                elif suffix == "三刻":
                    minute = 45
                if hour is not None:
                    hour = _to_24h(hour, tm.group(1))
                if hour is not None and 0 <= hour <= 23 and 0 <= minute <= 59:
                    if not intent and tm.start() > 0:
                        # 「我们14:30开会」这种闲聊不抢着记
                        chat_like = True
                        continue
                    content = _clean_content(
                        seg[:tm.start()] + " " + seg[tm.end():]) or "工作提醒"
                    parsed.append(Parsed(f"{hour:02d}:{minute:02d}", content,
                                         tm.group(1) or period, False))
                    explicit += 1
                    continue

            # 没有具体时间：反问/感叹语气一律不记账
            # （「键盘都是粑粑 那我怎么工作」这类吐槽，不能被当成待办）
            if not seg_header and _looks_like_chat(seg):
                chat_like = True
                continue

            content = _clean_content(seg)
            if len(content) >= 2 and content not in STOP_CONTENT:
                parsed.append(Parsed(None, content, period, True))

        if explicit == 0:
            if chat_like or not parsed:
                return []
            # 没有任何具体时间，三种说法都认：
            #   1. 明确在交代待办 / 用了清单表头
            #   2. 有「时段 + 干活动词」（我下午要交报告）
            #   3. 句子本身就是一个明确的业务动作（跟供应商确认什么时候发货）
            verb_ok = any(WORK_VERB.search(p.content) or STRONG_VERB.search(p.content)
                          for p in parsed)
            soft_ok = (intent and (bool(period) or len(segs) >= 2
                                   or colon_header or header_hit)) or \
                      (bool(period) and verb_ok) or \
                      any(STRONG_VERB.search(p.content) for p in parsed)
            if not soft_ok:
                return []

        end = work_end if _hm_to_min(work_end) >= 0 else "18:00"
        for p in parsed:
            if p.time is None:
                p.time = end
                p.soft = True

        seen, out = set(), []
        for p in parsed:
            key = p.content.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out[:limit]

    @staticmethod
    def parse(text, work_end="18:00"):
        got = ReminderParser.parse_many(text, work_end)
        return got[0] if got else None


# ---------------------------------------------------------------- 单条工作
class WorkItemRow(QFrame):
    clicked = Signal(str)
    context = Signal(str, object)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)

        self.time_lbl = QLabel(item_label(self.item))
        self.time_lbl.setFixedWidth(52)
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.time_lbl)

        self.content_lbl = QLabel(self.item.get("content", ""))
        self.content_lbl.setWordWrap(True)
        lay.addWidget(self.content_lbl, 1)

        self.bell = QLabel("🔔")
        self.bell.setFixedWidth(16)
        self.bell.setToolTip("到点会提醒")
        lay.addWidget(self.bell)

        self.apply_style()

    def apply_style(self):
        c = TAG_COLORS[self.item.get("color", 0) % len(TAG_COLORS)]
        done = bool(self.item.get("done"))
        # 已完成：整体变淡
        if done:
            self.setStyleSheet(
                f"WorkItemRow{{background-color:rgba(246,246,250,170); border-radius:10px;}}")
        else:
            self.setStyleSheet(
                f"WorkItemRow{{background-color:{c['bg']}; border-radius:10px;}}")
        tf = QFont("Microsoft YaHei UI", 9)
        tf.setBold(True)
        self.time_lbl.setFont(tf)
        self.time_lbl.setStyleSheet(
            f"color:{c['fg'] if not done else _fade(c['fg'], 110)}; background:transparent;")
        cf = QFont("Microsoft YaHei UI", 10)
        cf.setStrikeOut(done)
        self.content_lbl.setFont(cf)
        self.content_lbl.setStyleSheet(
            f"color:{c['fg'] if not done else _fade(c['fg'], 95)}; background:transparent;")
        self.bell.setStyleSheet(
            f"background:transparent; color:{c['fg'] if not done else 'rgba(150,150,160,80)'};")
        self.bell.setVisible(bool(self.item.get("remind", True)))
        if self.item.get("soft"):
            self.setToolTip("没给具体时间 → 默认下班前完成；点一下切换完成 / 未完成，右键可改时间")
            self.time_lbl.setToolTip(f"下班前（{self.item.get('time', '18:00')}）提醒")
        else:
            self.setToolTip("点一下切换完成 / 未完成；右键可改时间或取消提醒")

    def set_done(self, done):
        self.item["done"] = done
        self.apply_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item["id"])
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.context.emit(self.item["id"], e.globalPos())


# ---------------------------------------------------------------- 设置窗口
class WorkSettingsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("工作提醒设置")
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { color: #3a3a46; font-size: 13px; }
            QTimeEdit, QSpinBox, QLineEdit {
                background:#f6f7fb; border:1px solid #e3e5ee; border-radius:8px;
                padding:4px 8px; color:#2b2b35; font-size:13px; min-height:22px;
            }
            QCheckBox { color:#3a3a46; font-size:13px; }
            QPushButton {
                background:#5686fe; color:white; border:none; border-radius:8px;
                padding:7px 18px; font-size:13px;
            }
            QPushButton:hover { background:#4575ed; }
        """)
        s = store.settings
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        grp1 = QFrame()
        g1 = QGridLayout(grp1)
        g1.setContentsMargins(0, 0, 0, 0)
        g1.setHorizontalSpacing(10)
        g1.setVerticalSpacing(8)
        self.ed = {}
        fields = [
            ("work_start", "上班时间"), ("work_end", "下班时间"),
            ("lunch", "午饭提醒"), ("clock_in", "上班打卡"),
            ("afternoon", "下午待办提醒"),
        ]
        for i, (key, label) in enumerate(fields):
            g1.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            t = QTimeEdit()
            t.setDisplayFormat("HH:mm")
            t.setTime(QTime.fromString(s.get(key, "09:00"), "HH:mm"))
            g1.addWidget(t, i // 2, (i % 2) * 2 + 1)
            self.ed[key] = t

        g1.addWidget(QLabel("打卡提前(分钟)"), 2, 2)
        self.sp_adv = QSpinBox()
        self.sp_adv.setRange(0, 60)
        self.sp_adv.setValue(int(s.get("clock_in_advance", 5)))
        g1.addWidget(self.sp_adv, 2, 3)

        g1.addWidget(QLabel("超时自动完成(分钟)"), 3, 0)
        self.sp_done = QSpinBox()
        self.sp_done.setRange(0, 240)
        self.sp_done.setValue(int(s.get("auto_done_minutes", 30)))
        g1.addWidget(self.sp_done, 3, 1)

        self.cb_enable = QCheckBox("启用全部提醒")
        self.cb_enable.setChecked(bool(s.get("enabled", True)))
        g1.addWidget(self.cb_enable, 3, 2, 1, 2)
        self.cb_morning = QCheckBox("开机早上汇总今日工作")
        self.cb_morning.setChecked(bool(s.get("morning_enabled", True)))
        g1.addWidget(self.cb_morning, 4, 0, 1, 2)
        self.cb_review = QCheckBox("下班回顾（问今天都完成了么）")
        self.cb_review.setChecked(bool(s.get("review_enabled", True)))
        g1.addWidget(self.cb_review, 4, 2, 1, 2)
        root.addWidget(grp1)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#ececf3;")
        root.addWidget(line)

        root.addWidget(QLabel("提醒文案（{list} 会替换成待办，{adv} 替换成提前分钟）"))
        form = QFormLayout()
        form.setSpacing(7)
        self.msgs = {}
        for key, label in [("morning_msg", "早上汇总"), ("lunch_msg", "午饭"),
                           ("clock_in_adv_msg", "打卡前提醒"), ("clock_in_msg", "打卡"),
                           ("afternoon_msg", "下午待办"), ("off_msg", "下班"),
                           ("review_msg", "下班回顾")]:
            le = QLineEdit(s.get(key, DEFAULT_SETTINGS[key]))
            form.addRow(QLabel(label), le)
            self.msgs[key] = le
        root.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _save(self):
        kw = {
            "enabled": self.cb_enable.isChecked(),
            "morning_enabled": self.cb_morning.isChecked(),
            "review_enabled": self.cb_review.isChecked(),
            "clock_in_advance": self.sp_adv.value(),
            "auto_done_minutes": self.sp_done.value(),
        }
        for k, w in self.ed.items():
            kw[k] = w.time().toString("HH:mm")
        for k, w in self.msgs.items():
            kw[k] = w.text().strip() or DEFAULT_SETTINGS[k]
        self.store.update_settings(**kw)
        self.accept()


class _TimeDialog(QDialog):
    def __init__(self, cur, parent=None):
        super().__init__(parent)
        self.setWindowTitle("修改提醒时间")
        self.setStyleSheet("QDialog{background:#fff;} QLabel{color:#3a3a46;}"
                           "QPushButton{background:#5686fe;color:#fff;border:none;"
                           "border-radius:8px;padding:6px 16px;}")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("新的提醒时间："))
        self.te = QTimeEdit()
        self.te.setDisplayFormat("HH:mm")
        self.te.setTime(QTime.fromString(cur or "09:00", "HH:mm"))
        self.te.setStyleSheet("QTimeEdit{background:#f6f7fb;border:1px solid #e3e5ee;"
                              "border-radius:8px;padding:5px 8px;}")
        lay.addWidget(self.te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ---------------------------------------------------------------- 面板
class WorkPanel(QWidget):
    W, H = 460, 566

    def __init__(self, store, pet):
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("大肥鱼的便利贴")
        self.store = store
        self.pet = pet
        self.work_h = int(self.H / 3)
        self._anim = None
        self._build()
        self.refresh()

    # -- UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            QFrame#card {
                background: #ffffff;
                border: 1px solid #e6e8f0;
                border-radius: 18px;
            }
        """)
        root.addWidget(self.card)

        self.effect = QGraphicsOpacityEffect(self.card)
        self.effect.setOpacity(1.0)
        self.card.setGraphicsEffect(self.effect)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # 头部
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("📌 今日工作")
        title.setStyleSheet("font-size:15px; font-weight:600; color:#23232c;")
        head.addWidget(title)
        self.sub = QLabel("")
        self.sub.setStyleSheet("font-size:11px; color:#8b8b9a;")
        head.addWidget(self.sub)
        head.addStretch(1)
        self.btn_set = self._icon_btn("⚙", "工作提醒设置")
        self.btn_set.clicked.connect(self.open_settings)
        head.addWidget(self.btn_set)
        self.btn_close = self._icon_btn("✕", "收起")
        self.btn_close.clicked.connect(self.hide_anim)
        head.addWidget(self.btn_close)
        lay.addLayout(head)

        # 上半区（1/3）：今日工作
        self.work_area = QScrollArea()
        self.work_area.setWidgetResizable(True)
        self.work_area.setFixedHeight(self.work_h - 46)
        self.work_area.setFrameShape(QFrame.Shape.NoFrame)
        self.work_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width:6px; background:transparent; }
            QScrollBar::handle:vertical { background:#dcdce8; border-radius:3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)
        self.holder = QWidget()
        self.holder.setStyleSheet("background:transparent;")
        self.holder_lay = QVBoxLayout(self.holder)
        self.holder_lay.setContentsMargins(2, 2, 6, 2)
        self.holder_lay.setSpacing(6)
        self.holder_lay.addStretch(1)
        self.work_area.setWidget(self.holder)
        lay.addWidget(self.work_area)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#eef0f6;")
        lay.addWidget(sep)

        # 下半区：聊天
        self.chat = QTextBrowser()
        self.chat.setOpenLinks(False)
        self.chat.setStyleSheet("""
            QTextBrowser {
                background: #fbfbfe; border: 1px solid #eef0f6;
                border-radius: 12px; padding: 8px; color: #2b2b35; font-size: 13px;
            }
            QScrollBar:vertical { width:6px; background:transparent; }
            QScrollBar::handle:vertical { background:#dcdce8; border-radius:3px; }
        """)
        lay.addWidget(self.chat, 1)

        inp = QHBoxLayout()
        inp.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("聊天，或「提醒我两点半开会」「下午：写周报；回邮件」")
        self.input.setStyleSheet("""
            QLineEdit {
                background:#f6f7fb; border:1px solid #e6e8f0; border-radius:12px;
                padding:8px 12px; font-size:13px; color:#2b2b35;
            }
            QLineEdit:focus { border:1px solid #b9c7ff; background:#ffffff; }
        """)
        self.input.returnPressed.connect(self.submit)
        inp.addWidget(self.input, 1)
        self.btn_send = QPushButton("↑")
        self.btn_send.setFixedSize(34, 34)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet("""
            QPushButton { border-radius:17px; background:#5686fe; color:white;
                          border:none; font-size:18px; font-weight:bold; }
            QPushButton:hover { background:#4575ed; }
        """)
        self.btn_send.clicked.connect(self.submit)
        inp.addWidget(self.btn_send)
        lay.addLayout(inp)

    def _icon_btn(self, text, tip):
        b = QPushButton(text)
        b.setFixedSize(24, 24)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton { border:none; background:transparent; color:#9a9aab;
                          font-size:14px; border-radius:12px; }
            QPushButton:hover { background:#f0f1f8; color:#5686fe; }
        """)
        return b

    # -- 数据刷新
    def refresh(self):
        self.store.auto_done()
        # 清空旧行（保留末尾 stretch）
        while self.holder_lay.count() > 1:
            it = self.holder_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        items = self.store.items()
        for it in items:
            row = WorkItemRow(it)
            row.clicked.connect(self._toggle_item)
            row.context.connect(self._item_menu)
            self.holder_lay.insertWidget(self.holder_lay.count() - 1, row)

        if not items:
            empty = QLabel("今天还没有安排～\n· 说「提醒我下午两点半有重要会议」\n"
                           "· 或者直接列清单「我下午的工作：和IT沟通网站；广告对标；拿到物料」")
            empty.setWordWrap(True)
            empty.setStyleSheet("color:#a8a8b8; font-size:12px; padding:10px 4px;")
            self.holder_lay.insertWidget(0, empty)

        done = sum(1 for i in items if i.get("done"))
        self.sub.setText(f"{datetime.now().strftime('%m-%d')} · {len(items)} 条 · 完成 {done}")

    # -- 交互
    def _toggle_item(self, item_id):
        it = self.store.get(item_id)
        if not it:
            return
        if it.get("done"):
            # 重新启动任务：恢复不透明，重置提醒
            self.store.update(item_id, done=False, fired=False)
            if self.pet:
                self.pet.jump_t = 1.0
        else:
            self.store.update(item_id, done=True)
        self.refresh()

    def _item_menu(self, item_id, pos):
        it = self.store.get(item_id)
        if not it:
            return
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu { background:#ffffff; border:1px solid #e6e8f0; border-radius:10px; padding:6px; }
            QMenu::item { padding:6px 18px; border-radius:6px; color:#2b2b35; font-size:13px; }
            QMenu::item:selected { background:#eef2ff; color:#2b4d78; }
        """)
        m.addAction("⏰ 修改提醒时间", lambda: self._edit_time(item_id))
        a = m.addAction("🔕 不提醒")
        a.setCheckable(True)
        a.setChecked(not it.get("remind", True))
        a.triggered.connect(lambda: self._toggle_remind(item_id))
        m.addAction("✅ 标记完成" if not it.get("done") else "↩ 重新启动",
                    lambda: self._toggle_item(item_id))
        m.addSeparator()
        m.addAction("🗑 删除这条", lambda: self._delete_item(item_id))
        m.exec(pos)

    def _toggle_remind(self, item_id):
        it = self.store.get(item_id)
        if not it:
            return
        self.store.update(item_id, remind=not it.get("remind", True), fired=False)
        self.refresh()

    def _edit_time(self, item_id):
        it = self.store.get(item_id)
        if not it:
            return
        dlg = _TimeDialog(it.get("time"), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.store.update(item_id,
                              time=dlg.te.time().toString("HH:mm"), fired=False, done=False)
            self.refresh()

    def _delete_item(self, item_id):
        self.store.remove(item_id)
        self.refresh()

    def open_settings(self):
        dlg = WorkSettingsDialog(self.store, self)
        dlg.exec()
        self.refresh()

    # -- 聊天
    def _html_bubble(self, who, text, align="left"):
        color = "#eef4ff" if align == "right" else "#f3f4f8"
        name = "我" if align == "right" else "大肥鱼"
        name_color = "#5686fe" if align == "right" else "#8b8b9a"
        body = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = body.replace("\n", "<br>")
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="{align}">'
                f'<span style="color:{name_color}; font-size:10px;">{name}</span><br>'
                f'<table cellspacing="0" cellpadding="7" style="background:{color}; border-radius:10px;">'
                f'<tr><td><span style="color:#2b2b35; font-size:13px;">{body}</span></td></tr>'
                f'</table></td></tr></table>')

    def append_chat(self, who, text):
        align = "right" if who == "user" else "left"
        self.chat.append(self._html_bubble(who, text, align))
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_sys(self, text):
        esc = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.chat.append(f'<span style="color:#9a9aab; font-size:11px;">{esc}</span>')
        # append 的段落需要用光标单独设置居中，div align 在 QTextBrowser 里不总生效
        cur = self.chat.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextBlockFormat()
        fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        fmt.setTopMargin(4)
        fmt.setBottomMargin(4)
        cur.setBlockFormat(fmt)
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.append_chat("user", text)

        # 「都完成了」→ 一键把今天的条目标记完成
        if not re.search(r"[吗么?？]", text) and \
                (re.search(r"(都|全部|全|已经)(完成|做完|搞定|弄完)了?", text)
                 or re.match(r"^(完成|做完|搞定)了?[!！。~～]*$", text)):
            left = [i for i in self.store.items() if not i.get("done")]
            for it in left:
                self.store.update(it["id"], done=True)
            self.refresh()
            self.append_sys(f"已把 {len(left)} 件事标记完成" if left
                            else "今天的事已经全部完成了")
            if self.pet:
                self.pet.jump_t = 1.0
                self.pet.say("全部搞定，辛苦啦~")
            return

        got = ReminderParser.parse_many(
            text, self.store.settings.get("work_end", "18:00"))
        if got:
            added = []
            for p in got:
                it = self.store.add(p.time, p.content, period=p.period, soft=p.soft)
                if it:
                    added.append(p)
            self.refresh()
            if added:
                for p in added:
                    self.append_sys(f"已记入今日工作 · {p.label} {p.content}")
                if self.pet:
                    self.pet.jump_t = 1.0
                    if len(added) > 1:
                        self.pet.say(f"记下 {len(added)} 件啦！")
                    elif added[0].soft:
                        self.pet.say("记下啦，下班前提醒你")
                    else:
                        self.pet.say("记下啦！到点我叫你")
                return
            self.append_sys("这几条今天已经记过啦")
            return

        if not self.pet:
            return
        if not self.pet._api_key():
            self.append_sys("还没设置 API Key，右键桌宠 → ⚙ 接口设置")
            return
        self.append_chat("pet", "……")
        self.pet._call_ds(text)

    def append_review(self, items):
        """下班回顾：把今天所有工作连状态一起列出来"""
        if not items:
            return
        total = len(items)
        done = sum(1 for i in items if i.get("done"))
        title = f"今日工作回顾 · {done}/{total} 完成"
        if done == total:
            title += "（全部搞定 👍）"

        def esc(t):
            return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        html = ['<table width="100%" cellspacing="0" cellpadding="4" '
                'style="background:#f7f8fc;">',
                f'<tr><td colspan="3" style="color:#2b4d78; font-size:12px;">'
                f'<b>{esc(title)}</b></td></tr>']
        for it in items:
            d = bool(it.get("done"))
            c = "#a8a8b8" if d else "#2b2b35"
            mark_c = "#4caf70" if d else "#c0c0cc"
            html.append(
                '<tr>'
                f'<td width="16" style="color:{mark_c}; font-size:12px;">{"✓" if d else "○"}</td>'
                f'<td width="54" style="color:{c}; font-size:11px;">{esc(item_label(it))}</td>'
                f'<td style="color:{c}; font-size:12px;">{esc(it.get("content"))}</td>'
                '</tr>')
        html.append('</table>')
        self.chat.append("".join(html))
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_ai_reply(self, text):
        # 去掉占位气泡不方便，直接追加正式回复
        self.append_chat("pet", text)

    # -- 弹出 / 收起（放大缩小动画）
    def popup_at(self, x, y):
        self.refresh()
        self.setFixedSize(self.W, self.H)
        final = QRect(int(x), int(y), self.W, self.H)
        small_w, small_h = int(self.W * 0.72), int(self.H * 0.72)
        start = QRect(final.center().x() - small_w // 2,
                      final.bottom() - small_h, small_w, small_h)
        self.setGeometry(start)
        self.show()
        self.raise_()
        self.activateWindow()
        self.effect.setOpacity(0.25)
        self.input.setFocus()

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(190)
        self._anim.setStartValue(start)
        self._anim.setEndValue(final)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.start()

        self._anim2 = QPropertyAnimation(self.effect, b"opacity", self)
        self._anim2.setDuration(170)
        self._anim2.setStartValue(0.25)
        self._anim2.setEndValue(1.0)
        self._anim2.start()

    def hide_anim(self):
        if not self.isVisible():
            return
        cur = self.geometry()
        small_w, small_h = int(self.W * 0.72), int(self.H * 0.72)
        end = QRect(cur.center().x() - small_w // 2, cur.bottom() - small_h, small_w, small_h)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(150)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(end)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self.hide)
        self._anim.start()

        self._anim2 = QPropertyAnimation(self.effect, b"opacity", self)
        self._anim2.setDuration(140)
        self._anim2.setStartValue(1.0)
        self._anim2.setEndValue(0.2)
        self._anim2.start()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide_anim()
        else:
            super().keyPressEvent(e)

    def showEvent(self, e):
        self.refresh()
        if self.pet:
            self.pet.ai_reply_sink = self.on_ai_reply
        super().showEvent(e)

    def hideEvent(self, e):
        if self.pet:
            self.pet.ai_reply_sink = None
        super().hideEvent(e)


# ---------------------------------------------------------------- 提醒引擎
class ReminderEngine(QObject):
    def __init__(self, store, say, on_change=None, on_review=None, on_event=None):
        super().__init__()
        self.store = store
        self.say = say
        self.on_change = on_change
        self.on_review = on_review      # 下班回顾：把今日全部工作列出来
        self.on_event = on_event        # (key) 播报后让桌宠做个配合动作（吃饭/伸懒腰）
        self._booted = False            # 启动后的第一次检查可以补问下班回顾

    # -- 文案拼装
    def _list_text(self, items, limit=3):
        if not items:
            return "暂时没有安排"
        parts = [f"{item_label(i)} {i['content']}" for i in items[:limit]]
        more = f" 等{len(items)}件" if len(items) > limit else ""
        return "；".join(parts) + more

    def _due(self, hm, cur, window=10):
        base = _hm_to_min(hm)
        if base < 0:
            return False
        return 0 <= cur - base <= window

    def _review_text(self, items):
        """下班回顾的短播报（详情列表走 on_review）"""
        if not items:
            return None
        done = sum(1 for i in items if i.get("done"))
        left = len(items) - done
        if not left:
            return f"今天 {len(items)} 件都完成了，辛苦啦～"
        tpl = self.store.settings.get("review_msg", DEFAULT_SETTINGS["review_msg"])
        return tpl.replace("{list}", f"共{len(items)}件，还有{left}件没打勾")

    def startup_brief(self):
        """开机后：汇总今天要做的事"""
        s = self.store.settings
        if not s.get("enabled", True) or not s.get("morning_enabled", True):
            return
        now = datetime.now()
        cur = now.hour * 60 + now.minute
        start = _hm_to_min(s.get("work_start", "09:00"))
        if not (start - 5 <= cur <= start + 90):
            return
        if self.store.has_flag("morning"):
            return
        self.store.set_flag("morning")
        items = [i for i in self.store.items() if not i.get("done")]
        msg = s.get("morning_msg", DEFAULT_SETTINGS["morning_msg"]).replace(
            "{list}", self._list_text(items))
        self._emit(msg)

    def _emit(self, msg):
        try:
            self.say(msg)
        except Exception as e:
            print("[reminder] 播报失败:", e)
        if self.on_change:
            self.on_change()

    def check(self):
        s = self.store.settings
        if not s.get("enabled", True):
            return
        now = datetime.now()
        cur = now.hour * 60 + now.minute
        pending = []

        # 1) 单条工作到点提醒
        for it in self.store.items():
            if it.get("done") or not it.get("remind", True) or it.get("fired"):
                continue
            if self._due(it["time"], cur, window=10):
                tip = f"{item_label(it)} 该做啦：{it['content']}"
                pending.append(("item:" + it["id"], tip,
                                lambda i=it: self.store.update(i["id"], fired=True)))

        # 2) 固定日程
        adv = int(s.get("clock_in_advance", 5))
        ci = _hm_to_min(s.get("clock_in", "13:30"))
        adv_time = f"{(ci - adv) // 60:02d}:{(ci - adv) % 60:02d}"
        schedule = [
            ("lunch", s.get("lunch", "12:00"),
             s.get("lunch_msg", DEFAULT_SETTINGS["lunch_msg"]), {}),
            ("clock_in_adv", adv_time,
             s.get("clock_in_adv_msg", DEFAULT_SETTINGS["clock_in_adv_msg"]).replace("{adv}", str(adv)),
             {}),
            ("clock_in", s.get("clock_in", "13:30"),
             s.get("clock_in_msg", DEFAULT_SETTINGS["clock_in_msg"]), {}),
            ("afternoon", s.get("afternoon", "14:00"),
             s.get("afternoon_msg", DEFAULT_SETTINGS["afternoon_msg"]), {"afternoon": True}),
            ("off", s.get("work_end", "18:00"),
             s.get("off_msg", DEFAULT_SETTINGS["off_msg"]), {}),
            ("review", s.get("work_end", "18:00"), "", {"review": True}),
        ]
        for key, hm, msg, opt in schedule:
            if self.store.has_flag(key):
                continue
            if opt.get("review"):
                # 下班回顾：问今天都完成了么 + 列出全部条目
                if not s.get("review_enabled", True):
                    self.store.set_flag(key)
                    continue
                rv = self.store.items()
                if not rv:
                    continue
                # 启动后第一次检查允许补问（比如 19 点才开机），之后只认准点
                window = 240 if not self._booted else 10
                if not self._due(hm, cur, window=window):
                    continue
                rmsg = self._review_text(rv)
                if not rmsg:
                    self.store.set_flag(key)
                    continue
                pending.append((key, rmsg, lambda k=key: self.store.set_flag(k),
                                lambda its=rv: self._deliver_review(its)))
                continue
            if not self._due(hm, cur, window=10):
                continue
            if opt.get("afternoon"):
                pm = [i for i in self.store.items()
                      if not i.get("done") and _hm_to_min(i["time"]) >= _hm_to_min("14:00")]
                msg = msg.replace("{list}", self._list_text(pm))
            pending.append((key, msg, lambda k=key: self.store.set_flag(k)))

        self._booted = True
        if not pending:
            return
        # 一次只播一条，避免气泡互相覆盖；其余留到下一次 tick
        key, msg, mark = pending[0][0], pending[0][1], pending[0][2]
        after = pending[0][3] if len(pending[0]) > 3 else None
        mark()
        self._emit(msg)
        if self.on_event:
            try:
                self.on_event(key)      # 播报同时播放对应小动画
            except Exception as e:
                print("[reminder] 联动动作失败:", e)
        if after:
            after()

    def _deliver_review(self, items):
        if not self.on_review:
            return
        try:
            self.on_review(items)
        except Exception as e:
            print("[reminder] 回顾列表失败:", e)
