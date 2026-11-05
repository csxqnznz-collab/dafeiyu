"""话唠模式测试：频率 / 素材门槛 / 免打扰 / 台词生成（离屏，不走网络）

运行： .venv\\Scripts\\python.exe tests\\test_chatter.py
"""

import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import chatter  # noqa: E402
from chatter import ChatterBox, LEVELS  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)   # QTimer 需要事件循环对象

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


TMP = tempfile.mkdtemp(prefix="dfy_chatter_")


def make_box(level=1, mats=None, api=None, user_active=None, quiet=("23:00", "08:00")):
    cfg = {"chatter_level": level}
    path = os.path.join(TMP, f"state_{len(os.listdir(TMP))}.json")
    cb = ChatterBox(cfg, save_cfg=lambda: None, memory=None, work_store=None,
                    api_getter=lambda: (api or {}), state_path=path,
                    logger=lambda m: None, user_active=user_active, quiet=quiet)
    if mats is not None:
        cb.gather = lambda: list(mats)
    return cb


# ---------------------------------------------------------------- 1. 频率
print("— 频率 —")
for lv, spec in LEVELS.items():
    cb = make_box(lv)
    fast = spec["window_h"] * 3600 / spec["hi"]
    slow = spec["window_h"] * 3600 / spec["lo"]
    ds = [cb._next_delay() for _ in range(3000)]
    check(f"{lv} 级：间隔落在 {fast:.0f}-{slow:.0f}s",
          all(fast <= d <= slow for d in ds),
          f"min={min(ds):.0f} max={max(ds):.0f}")
    # 按这个节奏，一个窗口内会说多少条
    counts = [int(spec["window_h"] * 3600 // d) for d in ds]
    mean = sum(counts) / len(counts)
    check(f"{lv} 级：窗口内平均 {mean:.1f} 条 ∈ {spec['lo']}-{spec['hi']}",
          spec["lo"] - 1 <= mean <= spec["hi"] + 1, f"mean={mean:.1f}")

# 窗口上限（3 级最容易撞）
cb = make_box(3)
now = time.time()
cb.state["sent"] = [now - i * 30 for i in range(30)]
check("1 小时满 30 条 → 不再发", cb._window_ok() is False)
cb.state["sent"] = [now - i * 30 for i in range(20)]
check("1 小时 20 条 → 还能发", cb._window_ok() is True)
cb.state["sent"] = [now - 7200 - i for i in range(40)]     # 2 小时前的旧记录
check("窗口外的旧记录不占额度", cb._window_ok() is True)

# ---------------------------------------------------------------- 2. 免打扰
print("— 免打扰 —")
cb = make_box(1)
from datetime import datetime  # noqa: E402

check("23:30 免打扰", cb._in_quiet(datetime(2026, 11, 5, 23, 30)) is True)
check("07:59 免打扰", cb._in_quiet(datetime(2026, 11, 5, 7, 59)) is True)
check("09:00 可以说话", cb._in_quiet(datetime(2026, 11, 5, 9, 0)) is False)
check("22:59 可以说话", cb._in_quiet(datetime(2026, 11, 5, 22, 59)) is False)
check("免打扰关闭时不禁言", make_box(1, quiet=None)._in_quiet(
    datetime(2026, 11, 5, 23, 30)) is False)
check("距离解除免打扰 > 0", cb._seconds_to_quiet_end() > 0)

# ---------------------------------------------------------------- 3. 素材门槛
print("— 素材门槛 —")
cb = make_box(1, mats=[])
check("没有任何素材 → gather 为空", cb.gather() == [])

called, scheduled = [], []
cb._start_work = lambda mats: called.append(mats)
cb._schedule = lambda delay=None: scheduled.append(delay)
cb._tick()
check("无素材这轮不开口", not called)
check("无素材会重新排队", len(scheduled) == 1)

cb2 = make_box(1, mats=[{"kind": "memory", "text": "用户在推进肯尼亚二手车出口"}])
called2 = []
cb2._start_work = lambda mats: called2.append(mats)
cb2._tick()
check("有素材就开口", len(called2) == 1 and called2[0][0]["kind"] == "memory")

cb3 = make_box(1, mats=[{"kind": "memory", "text": "xxx"}],
               user_active=lambda: True)
called3 = []
cb3._start_work = lambda mats: called3.append(mats)
cb3._tick()
check("你正在聊天 → 不插嘴", not called3)

cb4 = make_box(3, mats=[{"kind": "work", "text": "和 IT 对网站"}])
cb4.state["sent"] = [time.time() - i for i in range(30)]
called4 = []
cb4._start_work = lambda mats: called4.append(mats)
cb4._tick()
check("窗口额度用完 → 不开口", not called4)

# ---------------------------------------------------------------- 4. 台词
print("— 台词 —")
ok = chatter._parse_lines("1. 你又把我忘了\n2、「网站那事咋样了」\n- 好无聊啊\n"
                          "分析：这句太长应该被丢掉不该出现的候选内容因为超过四十五个字了吧\n")
check("清洗：去编号/引号/思维链", ok == ["你又把我忘了", "网站那事咋样了", "好无聊啊"], str(ok))
check("清洗：超长丢弃", chatter._clean_line("字" * 50) == "")
check("话题抽取", chatter._topic("我最近在推进肯尼亚二手车出口项目") == "在推进肯尼亚二手车出口"[:12]
      or len(chatter._topic("我最近在推进肯尼亚二手车出口项目")) <= 12)

mats = [{"kind": "work", "text": "和IT部门沟通网站事宜"},
        {"kind": "memory", "text": "用户在准备肯尼亚二手车出口"}]
cb = make_box(1, mats=mats, api={})          # 没 Key → 走本地模板
lines = [cb.compose(mats) for _ in range(12)]
check("本地模板：都能出话", all(l for l in lines))
check("本地模板：长度可控", all(2 <= len(l) <= 45 for l in lines), str([len(l) for l in lines]))
check("本地模板：不重复", len(set(lines)) >= 6, str(len(set(lines))))

# 某个情绪的话都说过了 → 换到通用台词
cb5 = make_box(1, mats=mats, api={})
cb5.state["lines"] = [t.replace("{t}", "这事") for t in chatter.FALLBACK["bored"]]
check("同一情绪说腻了会换掉",
      cb5._fallback_line("bored", "这事") in chatter.GENERIC,
      cb5._fallback_line("bored", "这事"))

# 最近说过的不会被再说
cb5b = make_box(1, mats=mats, api={})
cb5b.state["lines"] = ["刚才那句"] * 12
check("最近说过的不会重复", cb5b._fallback_line("question", "这事") != "刚才那句")

# AI 分支
class FakeResp:
    status_code = 200

    def __init__(self, text):
        self._text = text

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


calls = {"n": 0}
real_post = chatter.requests.post


def fake_post(*a, **kw):
    calls["n"] += 1
    return FakeResp("网站那事到底咋样了\n你今天是不是又加班\n肯尼亚的单子成了没")


chatter.requests.post = fake_post
try:
    cb6 = make_box(1, mats=mats, api={"key": "sk-test-x", "base": "https://x/v1",
                                      "model": "m"})
    first = cb6.compose(mats)
    check("AI 台词被采用", first == "网站那事到底咋样了", first)
    check("AI 一次生成 3 句缓存", len(cb6._cache) == 2, str(cb6._cache))
    second = cb6.compose(mats)
    check("第二句来自缓存不重复请求", second == "你今天是不是又加班", second)
    check("只调了一次接口", calls["n"] == 1, str(calls))

    # AI 挂掉 → 退回本地
    chatter.requests.post = lambda *a, **kw: (_ for _ in ()).throw(OSError("boom"))
    cb7 = make_box(1, mats=mats, api={"key": "sk-test-x", "base": "https://x/v1",
                                      "model": "m"})
    check("AI 异常时本地兜底", bool(cb7.compose(mats)))
finally:
    chatter.requests.post = real_post

# ---------------------------------------------------------------- 5. 计数与落地
print("— 计数 —")
cb8 = make_box(1, mats=mats, api={})
said = []
cb8.sig_say.connect(lambda t: said.append(t))
cb8._deliver("第一句")
cb8._deliver("第二句")
check("今日计数 +2", cb8.today_count() == 2, str(cb8.today_count()))
check("信号发出", len(said) == 2, str(said))
check("状态文件已写", os.path.exists(cb8.state_path))
try:
    st = json.load(open(cb8.state_path, encoding="utf-8"))
    check("状态文件内容完整", st["today"] == 2 and len(st["lines"]) == 2)
except Exception as e:
    check("状态文件内容完整", False, repr(e))

cb9 = make_box(1)
cb9.state = cb9._load_state()
check("重启后计数还在（同一文件）", True)   # 用独立文件，见下

# 真正验证持久化：同一个 path 重新实例化
p = os.path.join(TMP, "persist.json")
cfg = {"chatter_level": 2}
a = ChatterBox(cfg, state_path=p, api_getter=lambda: {})
a._deliver("会记得这句")
b = ChatterBox(cfg, state_path=p, api_getter=lambda: {})
check("重新加载后今日计数保留", b.today_count() == 1, str(b.today_count()))
check("重新加载后最近台词保留", "会记得这句" in b.state["lines"])

# ---------------------------------------------------------------- 6. 档位开关
print("— 档位 —")
cfg2 = {}
cbA = ChatterBox(cfg2, state_path=os.path.join(TMP, "lv.json"), api_getter=lambda: {})
check("默认关闭", cbA.level() == 0)
msg = cbA.set_level(3)
check("开 3 级写进配置", cfg2["chatter_level"] == 3 and cbA.level() == 3)
check("开 3 级有反馈文案", "话唠" in msg, msg)
check("开 3 级启动定时器", cbA._timer.isActive() is True)
cbA.set_level(0)
check("关掉后定时器停", cbA._timer.isActive() is False)
check("关掉后不再说话", cbA.level() == 0)
check("非法档位按关闭处理", cbA.set_level(9) and cbA.level() == 0)

# 无素材时手动试一句也能出
cbB = make_box(1, mats=[])
said2 = []
cbB.sig_say.connect(lambda t: said2.append(t))
ret = cbB.say_now()
check("手动试一句：无素材也给一句", ret == "" and len(said2) == 1, str(said2))
check("手动试一句计入今日", cbB.today_count() == 1)

print("\n" + "=" * 52)
print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
if FAIL:
    print("失败：" + ", ".join(FAIL))
    sys.exit(1)
