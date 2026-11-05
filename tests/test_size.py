"""大小档位（含极小）+ 右键菜单不再有「模式」的测试（离屏，不联网）

运行： .venv\\Scripts\\python.exe tests\\test_size.py
"""

import importlib.util
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="dfy_size_")
os.environ["HJCDAFEIYU_DATA"] = TMP          # 隔离记忆库
os.environ["QT_QPA_PLATFORM"] = "offscreen"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


def load_pet():
    spec = importlib.util.spec_from_file_location("pet_size", os.path.join(ROOT, "桌宠.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load_pet()
m.CONFIG_PATH = os.path.join(TMP, "config.json")      # 别写用户真实配置
m.AI_ERROR_LOG = os.path.join(TMP, "ai_error.log")

app = m.QApplication.instance() or m.QApplication([])


def make_pet(size=0.7, extra=None):
    cfg = {"size": size, "x": None, "y": None,
           "ai_provider": "agnes", "ai_profiles": {}}
    if extra:
        cfg.update(extra)
    with open(m.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    w = m.PetWindow()
    w.timer.stop()                 # 手动 tick，避免定时器插进来
    w.reminder_timer.stop()
    if getattr(w, "chatter", None):
        w.chatter.stop()
    w.move(200, 200)
    return w


def close(w):
    for attr in ("work_panel", "chat_dialog", "function_panel", "food_panel", "tray"):
        obj = getattr(w, attr, None)
        if obj is not None:
            try:
                obj.hide()
            except Exception:
                pass
    w.hide()


# ---------------------------------------------------------------- 1. 极小档位
print("— 大小档位 —")
check("四个档位：极小/小/中/大",
      list(m.SIZE_LEVELS.keys()) == ["极小", "小", "中", "大"], str(m.SIZE_LEVELS))
check("极小 = 小 的一半（比例精确）",
      abs(m.SIZE_LEVELS["极小"] * 2 - m.SIZE_LEVELS["小"]) < 1e-9,
      f"{m.SIZE_LEVELS['极小']} vs {m.SIZE_LEVELS['小']}")
h_small = int(340 * m.SIZE_LEVELS["小"])
h_tiny = int(340 * m.SIZE_LEVELS["极小"])
check("极小像素高度 ≈ 小的一半", h_tiny == 93 and h_small == 187, f"{h_tiny} / {h_small}")
check("档位按大小递增", all(m.SIZE_LEVELS[a] < m.SIZE_LEVELS[b]
                            for a, b in zip(list(m.SIZE_LEVELS)[:-1], list(m.SIZE_LEVELS)[1:])))

w = make_pet(size=m.SIZE_LEVELS["极小"])
check("启动即为极小身高", w.cur_h == h_tiny, str(w.cur_h))
check("极小窗口加宽到能放气泡", w.win_w >= 168, str(w.win_w))
check("极小气泡区加高、字号变小", w.bubble_h == 88 and w.bubble_pt == 10,
      f"{w.bubble_h}/{w.bubble_pt}")
if w.animator is not None:
    # 动画模式：窗口 = 气泡 + 舞台（源 340×340 按 cur_h/276 缩放）
    _dw, _dh = m.pet_anim.stage_size(w.cur_h)
    check("窗口高度 = 气泡 + 动画舞台",
          w.height() == w.bubble_h + m.MARGIN + int(_dh), f"{w.height()} vs {_dh}")
    check("不再加载三视图精灵", w.sprites == {}, str(list(w.sprites)[:3]))
else:
    check("窗口高度 = 身高 + 气泡 + 边距",
          w.height() == w.cur_h + w.bubble_h + m.MARGIN * 2 + 10, str(w.height()))
key = w._sprite_key()
check("三视图兜底只取正面", key == ("正面", h_tiny), str(key))

# 换档：脚底不动
w.move(200, 200)
w.set_size(0.7)
bottom_mid = w.y() + w.height()
check("换到中号生效", w.cur_h == int(340 * m.SIZE_LEVELS["中"]), str(w.cur_h))
w.set_size(m.SIZE_LEVELS["极小"])
bottom_tiny = w.y() + w.height()
check("换回极小时脚底位置不变", abs(bottom_tiny - bottom_mid) <= 1,
      f"{bottom_tiny} vs {bottom_mid}")
check("尺寸写进配置", json.load(open(m.CONFIG_PATH, encoding="utf-8"))["size"] == 0.275)
w.set_size(m.SIZE_LEVELS["大"])
check("大号身高正确", w.cur_h == 306, str(w.cur_h))
check("大号气泡仍为 56", w.bubble_h == 56 and w.bubble_pt == 11, f"{w.bubble_h}")
close(w)


# 配置里出现怪值也不该崩
w = make_pet(size=0.333)
if w.animator is not None:
    check("怪尺寸按比例换算（不再吸附档位）", 100 < w.cur_h < 130, str(w.cur_h))
    check("怪尺寸也能算舞台", w.win_w > 0 and w.height() > w.bubble_h, str(w.size()))
else:
    check("怪尺寸自动吸附到最近档位", w.cur_h in (187, 238, 93), str(w.cur_h))
close(w)


# ---------------------------------------------------------------- 2. 「模式」已经彻底删掉
print("\n— 模式已删除 —")
check("没有 MODES 常量", not hasattr(m, "MODES") and not hasattr(m, "MODE_KEYS"))
check("没有 set_mode 方法", not hasattr(m.PetWindow, "set_mode"))
check("没有移动相关方法",
      not any(hasattr(m.PetWindow, a) for a in
              ("_line_target", "_line_idle", "_speed_now")),
      str([a for a in ("_line_target", "_line_idle", "_speed_now")
           if hasattr(m.PetWindow, a)]))
check("没有 SPEED / RUN_FACTOR 常量",
      not hasattr(m, "SPEED") and not hasattr(m, "RUN_FACTOR"))

w = make_pet(size=0.7, extra={"mode": "line"})     # 旧配置里残留 mode 也不该出事
check("旧配置的 mode 字段被丢掉", "mode" not in w.cfg, str(list(w.cfg)[:6]))
check("实例上没有 mode 属性", not hasattr(w, "mode"))
menu = w._build_menu()
labels = [a.text() for a in menu.actions()]
check("右键菜单第一项就是「大小」", labels[0] == "大小", str(labels[:4]))
check("右键菜单里没有「模式」", "模式" not in labels, str(labels))

# 待着不动：tick 若干次，位置不跳
w.move(240, 260)
x0, y0 = w.x(), w.y()
for _ in range(60):
    w.tick()
check("原地待着（不再自己走）", (w.x(), w.y()) == (x0, y0), f"{w.x()},{w.y()} vs {x0},{y0}")
if w.animator is not None:
    check("待机播的是待机片段", w._anim_role in (None, "idle"), str(w._anim_role))
close(w)

print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "、".join(FAIL))
sys.exit(1 if FAIL else 0)
