"""话唠模式：桌宠主动找你说话，情绪化、跟记忆挂钩

规则
- 三档频率（配置 chatter_level）：
    1 级：3 小时 5-10 条
    2 级：2 小时 10-20 条
    3 级：1 小时 20-30 条
  间隔按「窗口 / 条数」反算随机取值，再用滚动窗口卡上限，不会一口气刷屏
- 必须有真实素材（最近聊天 / 记忆 / 今日工作 / 用户画像）才开口；
  一条素材都没有就跳过这一轮，不硬编故事
- 情绪从提问 / 抱怨 / 伤心 / 开心 / 无聊 / 担忧 / 思念 / 兴奋里按素材权重抽
- 台词优先让 AI 按素材生成（一次生成 3 句备用，省请求），失败或没 Key 时用本地模板
- 深夜免打扰（默认 23:00-08:00）、你正在聊天时不插嘴
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta

import requests
from PySide6.QtCore import QObject, QTimer, Signal

# ---------------------------------------------------------------- 档位
LEVELS = {
    1: {"window_h": 3, "lo": 5, "hi": 10, "label": "1 级 · 3 小时 5-10 条"},
    2: {"window_h": 2, "lo": 10, "hi": 20, "label": "2 级 · 2 小时 10-20 条"},
    3: {"window_h": 1, "lo": 20, "hi": 30, "label": "3 级 · 1 小时 20-30 条"},
}

EMOTION_CN = {
    "question": "好奇追问",
    "complain": "抱怨",
    "sad": "伤心",
    "happy": "开心",
    "bored": "无聊",
    "worry": "担忧",
    "miss": "思念",
    "excited": "兴奋",
}
BASE_WEIGHT = {"question": 3, "complain": 2, "sad": 1, "happy": 2,
               "bored": 2, "worry": 1, "miss": 2, "excited": 1}

PERSONA = ("你是桌面宠物大肥鱼，贱兮兮但可爱、有点粘人。"
           "现在你主动找主人说话：只输出台词本身，不要分析、不要解释、不要编号、不要引号，"
           "每句不超过 25 个字，中文口语。不要编造素材里没有的事。")

# 本地兜底台词：{t} 会被素材里的具体内容替换（没有素材就跳过带 {t} 的句子）
FALLBACK = {
    "question": ["问你个事，{t}后来咋样了？", "你还在忙{t}吗？", "那个{t}，你想好没？",
                 "说起来，{t}有进展没？", "喂，{t}你打算怎么办？"],
    "complain": ["{t}拖到现在，我都替你急", "又不理我，自己玩去吧",
                 "光说不练，{t}就没动过", "你一忙起来就把我忘了"],
    "sad": ["有点难过，你都不跟我说话", "我是不是有点多余啊", "算了，你忙你的",
            "心里空空的，游两圈去"],
    "happy": ["想起{t}，忽然有点开心", "今天心情不错，想跟你唠两句",
              "嘿，我刚想到件好事", "心情好，想蹭蹭你"],
    "bored": ["好无聊，你陪我聊会儿？", "没劲，转圈圈转了八圈",
              "无聊到开始数像素了", "你在忙啥，我闲得慌"],
    "worry": ["{t}这事，会不会出问题啊", "有点担心你忙不过来",
              "你最近状态不对，还行吗", "别硬扛，我看着都累"],
    "miss": ["有点想你了，虽然刚见过", "你不在的时候，我就数天花板",
             "还记得{t}吗，我老想起来", "你一忙，我就开始想念"],
    "excited": ["{t}要是成了，我要蹦三下", "有点小激动，说不清为啥",
                "刚想到个好主意，兴奋", "嗷，我现在特别有劲"],
}
GENERIC = ["喂，在忙啥呢？", "我在这儿蹲半天了", "你说句话呗，好安静",
           "今天过得咋样？", "我有点想跟你唠两句"]

REASONING_MARKS = ("char count", "possible responses", "user said", "用户说", "用户问",
                   "字数", "候选", "分析：", "台词：", "每句话不超过")


def _clean_line(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"^[\-\*\u2022]\s*", "", t)
    t = re.sub(r"^\d+[\.、\)]\s*", "", t)
    t = t.strip('"“”\'‘’「」『』《》 \t\r\n')
    t = " ".join(t.split())
    low = t.lower()
    if not t or len(t) < 2 or len(t) > 45:
        return ""
    if any(k in low for k in REASONING_MARKS):
        return ""
    return t


def _parse_lines(text: str) -> list[str]:
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = _clean_line(raw)
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _topic(text: str, limit: int = 12) -> str:
    """从素材里抽一个能塞进台词的话题"""
    t = (text or "").strip()
    t = re.sub(r"^(我|我们|用户|主人)?(最近|今天|昨天|之前|上次)?(说|讲|提到|在做|要|想)", "", t)
    t = re.split(r"[。！？!?；;\n，,]", t)[0].strip()
    t = t.strip("：: ")
    if len(t) > limit:
        t = t[:limit]
    return t if len(t) >= 2 else ""


class ChatterBox(QObject):
    """定时器 + 素材 → 情绪 → 台词 → 冒泡"""

    sig_say = Signal(str)
    sig_finish = Signal()

    def __init__(self, cfg: dict, save_cfg=None, memory=None, work_store=None,
                 api_getter=None, state_path: str | None = None, logger=None,
                 user_active=None, quiet=("23:00", "08:00")):
        super().__init__()
        self.cfg = cfg
        self.save_cfg = save_cfg or (lambda: None)
        self.memory = memory
        self.work_store = work_store
        self.api_getter = api_getter or (lambda: {})
        self.log = logger or (lambda m: None)
        self.user_active = user_active
        self.quiet = quiet
        self.state_path = state_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "chatter_state.json")

        self.state = self._load_state()
        self._cache: list[tuple[str, str]] = []      # [(emotion, line)]
        self._busy = False
        self._lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self.sig_finish.connect(self._on_finish)

    # ------------------------------------------------------------ 状态
    def _load_state(self) -> dict:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
        st.setdefault("sent", [])
        st.setdefault("lines", [])
        st.setdefault("day", "")
        st.setdefault("today", 0)
        st.setdefault("last", 0.0)
        # 只留最近 6 小时的发送记录
        cutoff = time.time() - 6 * 3600
        st["sent"] = [t for t in st["sent"] if isinstance(t, (int, float)) and t > cutoff]
        return st

    def _save_state(self):
        st = self.state
        st["sent"] = st["sent"][-120:]
        st["lines"] = st["lines"][-40:]
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
        except Exception as e:
            self.log(f"[chatter] 状态保存失败：{e}")

    def today_count(self) -> int:
        if self.state.get("day") != datetime.now().strftime("%Y-%m-%d"):
            return 0
        return int(self.state.get("today") or 0)

    def level(self) -> int:
        try:
            lv = int(self.cfg.get("chatter_level") or 0)
        except Exception:
            lv = 0
        return lv if lv in LEVELS else 0

    # ------------------------------------------------------------ 调度
    def set_level(self, lv: int, announce=True):
        lv = int(lv) if lv in (0, 1, 2, 3) else 0
        self.cfg["chatter_level"] = lv
        try:
            self.save_cfg()
        except Exception:
            pass
        self._timer.stop()
        if lv <= 0:
            self._cache.clear()
            return "安静模式，我不吵你了"
        # 刚打开时给一点即时反馈，20-60 秒先来一句
        self._schedule(random.uniform(20, 60))
        return {"1": "好，我偶尔念叨两句",
                "2": "行，我开始话多了",
                "3": "话唠全开，你自求多福"}[str(lv)]

    def start(self):
        if self.level() > 0:
            self._schedule(random.uniform(30, 90))

    def stop(self):
        self._timer.stop()

    def _next_delay(self) -> float:
        """窗口 / 条数 → 平均间隔，上下浮动满足区间条数"""
        spec = LEVELS[self.level()]
        fast = spec["window_h"] * 3600 / spec["hi"]
        slow = spec["window_h"] * 3600 / spec["lo"]
        return random.uniform(fast, slow)

    def _schedule(self, delay: float | None = None):
        if self.level() <= 0:
            return
        self._timer.start(int(max(5, delay if delay is not None else self._next_delay()) * 1000))

    def _window_ok(self) -> bool:
        """滚动窗口内是否还有额度"""
        spec = LEVELS[self.level()]
        now = time.time()
        span = spec["window_h"] * 3600
        used = sum(1 for t in self.state["sent"] if now - t < span)
        return used < spec["hi"]

    # ------------------------------------------------------------ 免打扰
    def _in_quiet(self, now: datetime | None = None) -> bool:
        if not self.quiet:
            return False
        now = now or datetime.now()
        try:
            h1, m1 = (int(x) for x in str(self.quiet[0]).split(":"))
            h2, m2 = (int(x) for x in str(self.quiet[1]).split(":"))
        except Exception:
            return False
        start = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
        end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def _seconds_to_quiet_end(self) -> float:
        now = datetime.now()
        try:
            h2, m2 = (int(x) for x in str(self.quiet[1]).split(":"))
        except Exception:
            return 3600
        end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
        if end <= now:
            end += timedelta(days=1)
        return max(60.0, (end - now).total_seconds())

    # ------------------------------------------------------------ 素材
    def gather(self) -> list[dict]:
        """从记忆/聊天/工作/画像里捞可聊的素材；捞不到就返回空"""
        mats: list[dict] = []
        m = self.memory
        if m is not None:
            try:
                for row in m.convs.recent_across(16):
                    if row.get("role") != "user":
                        continue
                    txt = (row.get("content") or "").strip()
                    if 4 <= len(txt) <= 120:
                        mats.append({"kind": "recent", "text": txt})
            except Exception as e:
                self.log(f"[chatter] 读聊天失败：{e}")
            try:
                for row in m.retr.by_time(days=7, limit=8):
                    txt = (row.get("content") or "").strip()
                    if len(txt) >= 4:
                        mats.append({"kind": "memory", "text": txt})
            except Exception as e:
                self.log(f"[chatter] 读记忆失败：{e}")
            try:
                for row in m.mgr.core_memories():
                    txt = (row.get("content") or "").strip()
                    if len(txt) >= 4:
                        mats.append({"kind": "memory", "text": txt})
            except Exception:
                pass
            try:
                for row in m.mgr.profile():
                    txt = (row.get("profile_value") or "").strip()
                    if len(txt) >= 3:
                        mats.append({"kind": "profile", "text": txt})
            except Exception:
                pass

        if self.work_store is not None:
            try:
                for it in self.work_store.items():
                    if not it.get("done"):
                        txt = (it.get("content") or "").strip()
                        if txt:
                            mats.append({"kind": "work", "text": txt})
            except Exception:
                pass

        # 去掉重复，最多留 14 条
        out, seen = [], set()
        for x in mats:
            key = x["text"][:30]
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        random.shuffle(out)
        return out[:14]

    def _pick_emotion(self, mats: list[dict]) -> str:
        w = dict(BASE_WEIGHT)
        kinds = {x["kind"] for x in mats}
        if "work" in kinds:
            w["complain"] += 3
            w["worry"] += 2
        if "recent" in kinds:
            w["question"] += 3
            w["miss"] += 1
        if "memory" in kinds:
            w["miss"] += 2
        if "profile" in kinds:
            w["question"] += 1
            w["excited"] += 1
        pool = list(w.keys())
        return random.choices(pool, weights=[w[k] for k in pool], k=1)[0]

    # ------------------------------------------------------------ 台词
    def _prompt(self, emotion: str, mats: list[dict], n: int = 3) -> str:
        lines = []
        for x in mats[:6]:
            tag = {"recent": "用户最近说", "memory": "记住的事",
                   "profile": "用户画像", "work": "今天要做"}[x["kind"]]
            lines.append(f"- {tag}：{x['text'][:60]}")
        recent = "；".join(self.state["lines"][-6:]) or "（无）"
        return (f"情绪：{EMOTION_CN[emotion]}\n"
                f"素材：\n" + "\n".join(lines) + "\n"
                f"最近已经说过（换点新鲜的，别重复）：{recent}\n"
                f"请写 {n} 句不同的台词，每行一句，不要编号，不要解释。")

    def _ai_lines(self, emotion: str, mats: list[dict], n: int = 3) -> list[str]:
        api = {}
        try:
            api = self.api_getter() or {}
        except Exception:
            pass
        key, base, model = api.get("key"), (api.get("base") or "").rstrip("/"), api.get("model")
        if not (key and base and model):
            return []
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "system", "content": PERSONA},
                                   {"role": "user", "content": self._prompt(emotion, mats, n)}],
                      "max_tokens": 320, "temperature": 1.0},
                timeout=30)
            if r.status_code != 200:
                self.log(f"[chatter] 生成失败 {r.status_code}: {(r.text or '')[:120]}")
                return []
            msg = ((r.json().get("choices") or [{}])[0].get("message") or {})
            return _parse_lines(msg.get("content"))[:n]
        except Exception as e:
            self.log(f"[chatter] 生成异常：{e}")
            return []

    def _fallback_line(self, emotion: str, topic: str) -> str:
        pool = list(FALLBACK.get(emotion) or GENERIC)
        random.shuffle(pool)
        for tpl in pool:
            if "{t}" in tpl:
                if not topic:
                    continue
                cand = tpl.format(t=topic)
            else:
                cand = tpl
            line = _clean_line(cand)
            if line and line not in self.state["lines"][-12:]:
                return line
        return random.choice(GENERIC)

    def compose(self, mats: list[dict]) -> str:
        # 一次请求会生成 3 句，先用缓存，省请求
        while self._cache:
            _emo, line = self._cache.pop(0)
            if line not in self.state["lines"][-12:]:
                return line

        emotion = self._pick_emotion(mats)
        topic = _topic(random.choice(mats)["text"]) if mats else ""

        got = self._ai_lines(emotion, mats)
        if got:
            fresh = [ln for ln in got if ln not in self.state["lines"][-12:]]
            if fresh:
                self._cache = [(emotion, ln) for ln in fresh[1:]]
                return fresh[0]
        return self._fallback_line(emotion, topic)

    # ------------------------------------------------------------ 主循环
    def _tick(self):
        if self.level() <= 0:
            return
        if self._busy:
            self._schedule(30)
            return
        if self._in_quiet():
            wait = self._seconds_to_quiet_end() + random.uniform(10, 120)
            self._schedule(wait)
            return
        if self.user_active and self.user_active():
            self._schedule(random.uniform(90, 240))     # 你正在聊，不插嘴
            return
        if not self._window_ok():
            # 这个窗口的额度用完了，等最早那条滚出窗口再说
            spec = LEVELS[self.level()]
            oldest = min(self.state["sent"])
            wait = spec["window_h"] * 3600 - (time.time() - oldest) + random.uniform(20, 90)
            self._schedule(max(60, wait))
            return
        mats = self.gather()
        if not mats:
            self.log("[chatter] 没有素材，这轮跳过")
            self._schedule(random.uniform(300, 900))
            return
        self._start_work(mats)

    def _start_work(self, mats: list[dict]):
        self._busy = True

        def work():
            try:
                line = self.compose(mats)
            except Exception as e:
                self.log(f"[chatter] 组装台词失败：{e}")
                line = ""
            finally:
                self._busy = False
            if line:
                self._deliver(line)
            self.sig_finish.emit()

        threading.Thread(target=work, daemon=True).start()

    def _on_finish(self):
        if self.level() > 0:
            self._schedule(self._next_delay())

    def _deliver(self, line: str):
        with self._lock:
            now = time.time()
            day = datetime.now().strftime("%Y-%m-%d")
            if self.state.get("day") != day:
                self.state["day"] = day
                self.state["today"] = 0
            self.state["sent"].append(now)
            self.state["last"] = now
            self.state["lines"].append(line)
            self.state["today"] = int(self.state.get("today") or 0) + 1
            self._save_state()
        self.sig_say.emit(line)

    # ------------------------------------------------------------ 手动
    def say_now(self) -> str:
        """菜单里的「立即说一句」：没素材也给你来一句，方便试效果"""
        if self._busy:
            return "我正憋词呢，等我一下"
        mats = self.gather()
        if not mats:
            line = random.choice(GENERIC)
            self._deliver(line)
            return ""
        self._start_work(mats)
        return ""
