# -*- coding: utf-8 -*-
"""桌宠动画引擎测试：素材映射 / 舞台换算 / 解码 / 状态机

运行： .venv\\Scripts\\python.exe tests\\test_pet_anim.py
"""

import importlib.util
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="dfy_pa_")
os.environ["HJCDAFEIYU_DATA"] = TMP
os.environ["QT_QPA_PLATFORM"] = "offscreen"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import pet_anim  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------- 1. 素材映射
print("— 素材映射 —")
cat = pet_anim.catalog()
items = {a["id"]: a for a in cat["animations"]}
check("能读到动画目录", len(items) == 114, str(len(items)))

bad = []
for role, ids in pet_anim.ROLE_CLIPS.items():
    for cid in ids:
        if cid not in items:
            bad.append((role, cid))
check("每个角色引用的 id 都真实存在", not bad, str(bad))

by_cat = {}
for a in cat["animations"]:
    by_cat.setdefault(a["category"], []).append(a["id"])
check("点击回应正好 6 段素材", len(by_cat["click"]) == 6, str(len(by_cat["click"])))
check("点击回应里用上了 5 段（被拖那段单独给拖动）",
      len(pet_anim.ROLE_CLIPS["click"]) == 5 and
      "beishubiao-tuozhuai-xuankong-fankui" in pet_anim.ROLE_CLIPS["drag"],
      str(pet_anim.ROLE_CLIPS["click"]))
check("待机片段都来自 idle 分类",
      all(items[i]["category"] == "idle" for i in pet_anim.ROLE_CLIPS["idle"]),
      str(pet_anim.ROLE_CLIPS["idle"]))
check("吃饭片段都来自 eat 分类",
      all(items[i]["category"] == "eat" for i in pet_anim.ROLE_CLIPS["eat"]))
check("伸懒腰是「超大伸懒腰」", pet_anim.ROLE_CLIPS["stretch"] == ["chaoda-shenlanyao"],
      str(pet_anim.ROLE_CLIPS["stretch"]))

for role in pet_anim.ROLE_CLIPS:
    got = [pet_anim.pick(role) for _ in range(20)]
    check(f"{role} 每次都能挑到片段", all(g in items for g in got), str(set(got)))

picked = {pet_anim.pick("idle") for _ in range(200)}
check("待机会随机换片段", len(picked) > 1, str(picked))

check("路径拼得出来", os.path.exists(pet_anim.clip_path("daiji-huxi-xiuxian")),
      pet_anim.clip_path("daiji-huxi-xiuxian"))
check("不存在的 id 返回空", pet_anim.pick("nope") is None and pet_anim.clip("nope") is None)

# 舞台换算
w340, h340 = pet_anim.stage_size(pet_anim.BODY_H)
check("角色高度=参考值时舞台就是 340×340", (round(w340), round(h340)) == (340, 340),
      f"{w340} / {h340}")
w238, h238 = pet_anim.stage_size(238)
check("中号（238）舞台按比例缩小", abs(h238 - 340 * 238 / 276) < 1e-6, str(h238))
check("舞台比角色本体高（要留头顶/脚下）", pet_anim.STAGE_H > pet_anim.BODY_H)
check("脚底在舞台框里", pet_anim.STAGE_Y <= pet_anim.GROUND_Y <= pet_anim.STAGE_Y + pet_anim.STAGE_H)

bbox = {}
try:
    with open(os.path.join(ROOT, "dsh-pet", "assets", "bbox.json"), encoding="utf-8") as f:
        bbox = json.load(f).get("clips", {})
except Exception:
    pass
if bbox:
    overflow = []
    for role in ("idle", "click", "eat", "stretch", "walk", "run", "drag"):
        for cid in pet_anim.ROLE_CLIPS[role]:
            b = bbox.get(cid)
            if not b:
                continue
            x, y, w, h = b
            if x < pet_anim.STAGE_X - 2 or y < pet_anim.STAGE_Y - 2 \
                    or x + w > pet_anim.STAGE_X + pet_anim.STAGE_W + 2 \
                    or y + h > pet_anim.STAGE_Y + pet_anim.STAGE_H + 2:
                overflow.append((role, cid, b))
    check("用到的片段不会溢出舞台（不被裁）", not overflow, str(overflow))


# ---------------------------------------------------------------- 2. 真解码
print("\n— 解码 —")
a = pet_anim.PetAnimator()
frames = []
a.frame_changed.connect(lambda: frames.append(1))

check("能开播待机", a.play_role("idle", loop=True), str(a.clip_id))
pump(1.2)
check("收到动画帧", len(frames) > 5, str(len(frames)))
check("帧是 640×360", a.frame() is not None and (a.frame().width(), a.frame().height()) == (640, 360),
      str(a.frame().size() if a.frame() else None))
check("帧带透明通道", a.frame().hasAlphaChannel() if a.frame() else False)

a.set_mirror(True)
check("能镜像", a.mirror is True)
a.set_mirror(False)

# 换片段 → 淡出
old = a._frame
a.play("chi-xigua", role="eat", loop=True)
check("换片段时留了上一帧做淡出", a._fade_img is not None, str(a._fade_img))
first = a.fade_alpha()
pump(0.35)
check("淡出会随时间走完", first > 0 and a.fade_alpha() == 0.0, f"{first} → {a.fade_alpha()}")

# 一次性播完要发信号
got = []
a.clip_finished.connect(lambda cid: got.append(cid))
a.loop = False
a._on_done(a.clip_id, a._decoder)
check("一次性动作播完会通知", got == [a.clip_id], str(got))

a.stop()
check("stop 之后没有解码线程", a._decoder is None)
check("stop 之后没有帧", a.frame() is None)


# ---------------------------------------------------------------- 3. 桌宠状态机
print("\n— 桌宠联动 —")
spec = importlib.util.spec_from_file_location("pet_pa", os.path.join(ROOT, "桌宠.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.CONFIG_PATH = os.path.join(TMP, "config.json")
m.AI_ERROR_LOG = os.path.join(TMP, "ai_error.log")

with open(m.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"size": 0.7, "mode": "still", "x": 200, "y": 200,
               "ai_provider": "agnes", "ai_profiles": {}}, f)


class FakeAnimator:
    """记录调用，不真的解码（状态机测试要快）"""

    def __init__(self):
        self.calls = []
        self.clip_id = "x"
        self.role = None

    def play_role(self, role, loop=None, avoid=None):
        self.calls.append(("play", role, loop))
        self.role = role
        return True

    def play(self, clip_id, role=None, loop=True, fade=0.16):
        self.calls.append(("clip", clip_id, role))
        self.role = role
        return True

    def set_mirror(self, on):
        self.calls.append(("mirror", bool(on)))

    def plays(self, role):
        """这次有没有播过某个角色（play / clip 两种入口都算）"""
        return any((c[0] == "play" and c[1] == role) or
                   (c[0] == "clip" and len(c) > 2 and c[2] == role) for c in self.calls)

    def frame(self):
        return None

    def fade_alpha(self):
        return 0.0

    def fade_frame(self):
        return None

    def fade_mirror(self):
        return False

    def stop(self):
        pass


w = m.PetWindow()
w.timer.stop()
w.reminder_timer.stop()
if getattr(w, "chatter", None):
    w.chatter.stop()
w.animator = FakeAnimator()
w.animator.calls.clear()
w.animator.clip_id = None
w._anim_role = None
w._anim_until = 0.0
w._idle_next = 0.0
w.dragging = False
w.target = None
w.move(200, 200)

w._sync_anim(force=True)
check("站着就播待机", w.animator.plays("idle") and w._anim_role == "idle",
      str(w.animator.calls))

w.animator.calls.clear()
w.dragging = True
w._sync_anim()
check("拖住时播「被拖」动画", ("play", "drag", True) in w.animator.calls, str(w.animator.calls))
w.dragging = False

# 一次性动作期间别被待机顶掉
w.animator.calls.clear()
w.play_anim("click")
check("点击播点击回应", w._anim_role == "click" and w._anim_until > time.monotonic() - 1,
      str(w.animator.calls))
w._sync_anim()
check("点击还没演完不会被待机顶掉", w._anim_role == "click", str(w.animator.calls))

w._anim_until = 0.0
w._idle_next = 0.0
w._sync_anim()
check("演完自动回到待机", w._anim_role == "idle", str(w.animator.calls))

# 待机随机换段
w._idle_next = 0.0
w.animator.calls.clear()
w._sync_anim()
check("待机到点换一段", w.animator.plays("idle"), str(w.animator.calls))
w._idle_next = time.monotonic() + 99
w.animator.calls.clear()
w._sync_anim()
check("没到点就不乱换", not w.animator.calls, str(w.animator.calls))

# 小动作有冷却：不会一直伸懒腰
w._anim_role = "idle"
w._anim_until = 0.0
w._idle_action_next = time.monotonic() + 30
w.animator.calls.clear()
for _ in range(400):
    w._maybe_idle_action()
check("冷却期内不伸懒腰", not w.animator.plays("stretch"), str(w.animator.calls))

# 走 / 跑
w.target = (w.x() + 200, w.y() + w.height() / 2)
w._anim_role = None
w._anim_until = 0.0
w.mode, w.run_mode = "line", False
w._sync_anim()
check("走路播走路", ("play", "walk", True) in w.animator.calls, str(w.animator.calls))
w.run_mode = True
w._anim_role = None
w.animator.calls.clear()
w._sync_anim()
check("跑步播跑步", ("play", "run", True) in w.animator.calls, str(w.animator.calls))
w.target = None
w.run_mode = False

# 喂食 / 下班
w._anim_role = None
w._anim_until = 0.0
w.food_panel.hide()
w.on_food("🍎")
check("喂食播吃饭", w._anim_role == "eat", str(w._anim_role))

w._anim_role = None
w._anim_until = 0.0
w._on_reminder_event("lunch")
check("到点吃饭（12:00 提醒）播吃饭", w._anim_role == "eat", str(w._anim_role))

w._anim_role = None
w._anim_until = 0.0
w._on_reminder_event("off")
check("下班提醒播伸懒腰", w._anim_role == "stretch", str(w._anim_role))
w._anim_role = None
w._anim_until = 0.0
w._on_reminder_event("review")
check("下班回顾也伸懒腰", w._anim_role == "stretch", str(w._anim_role))

# 单击 → 点击回应
w._anim_role = None
w._anim_until = 0.0
w._click_timer.stop()
w._on_single_click()
check("单击触发点击回应", w._anim_role == "click", str(w._anim_role))
w.work_panel.hide()

# 窗口尺寸按舞台算
w.animator = None
w.sprites = {}
w._apply_size_metrics()
check("没有动画时仍按精灵高度算窗口",
      w.height() == w.cur_h + w.bubble_h + m.MARGIN * 2 + 10, str(w.height()))

for attr in ("work_panel", "chat_dialog", "function_panel", "food_panel", "tray"):
    obj = getattr(w, attr, None)
    if obj is not None:
        try:
            obj.hide()
        except Exception:
            pass
w.hide()

print(f"\n结果：{len(PASS)} 项通过" + (f"，{len(FAIL)} 项失败" if FAIL else "，全部通过"))
if FAIL:
    print("失败项：" + "；".join(FAIL))
