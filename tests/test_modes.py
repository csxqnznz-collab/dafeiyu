"""大小档位（含极小）× 横向行走模式 测试（离屏，不联网）

运行： .venv\\Scripts\\python.exe tests\\test_modes.py
"""

import importlib.util
import json
import os
import random
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="dfy_modes_")
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
    spec = importlib.util.spec_from_file_location("pet_modes", os.path.join(ROOT, "桌宠.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load_pet()
m.CONFIG_PATH = os.path.join(TMP, "config.json")      # 别写用户真实配置
m.AI_ERROR_LOG = os.path.join(TMP, "ai_error.log")

app = m.QApplication.instance() or m.QApplication([])


def make_pet(size=0.7, mode="wander"):
    with open(m.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"size": size, "mode": mode, "x": None, "y": None,
                   "ai_provider": "agnes", "ai_profiles": {}}, f, ensure_ascii=False)
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
    key = w._sprite_key()
    check("极小也有精灵（正面）", key[1] == h_tiny and key[0] == "正面", str(key))
else:
    check("窗口高度 = 身高 + 气泡 + 边距",
          w.height() == w.cur_h + w.bubble_h + m.MARGIN * 2 + 10, str(w.height()))
    key = w._sprite_key()
    check("极小也有精灵（正面）", key[1] == h_tiny and key[0] == "正面", str(key))

# 三视图都在（仅三视图兜底模式）
for d, name in (("down", "正面"), ("left", "侧面"), ("right", "侧面"), ("up", "背面")):
    w._set_dir(d, -1 if d == "left" else 1)
    k = w._sprite_key()
    if w.animator is None:
        check(f"极小档 {d} 用 {name}", k[0] == name and k[1] == h_tiny, str(k))
    else:
        check(f"极小档 {d} 不再切三视图", w.sprites == {}, str(k))

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
    check("怪尺寸仍能取到精灵", (w._sprite_key()[0], w.cur_h) in w.sprites, str(w._sprite_key()))
close(w)


# ---------------------------------------------------------------- 2. 横向行走
print("\n— 横向行走 —")
w = make_pet(size=0.7, mode="line")
check("配置里的 line 会被识别", w.mode == "line", w.mode)
menu = w._build_menu()
sub = next(a.menu() for a in menu.actions() if a.text() == "模式")
labels = [a.text() for a in sub.actions() if a.text()]
check("模式菜单有「横向行走」", "横向行走" in labels, str(labels))
check("四个模式齐全", labels == ["自由散步", "横向行走", "跟随鼠标", "原地待着"], str(labels))

w.move(150, 300)
w.line_y = 300
w.rest_until = 0
w.target = None
w.cur_speed = 0.0
picked = w._line_target(10 ** 9)
check("到点会挑一个横向目标", picked and w.target is not None, str(w.target))
check("目标与当前同高", abs(w.target[1] - (w.y() + w.height() / 2)) < 2, str(w.target))

y0 = w.y()
xs, ys, dirs = [], [], []
for _ in range(40):
    w.cur_speed = w._speed_now()          # 跳过加减速，直接看位移
    w.tick()
    xs.append(w.x())
    ys.append(w.y())
    dirs.append(w.dir)
check("横向行走只改 x，高度不动", len(set(ys)) == 1 and ys[0] == y0, f"{set(ys)}")
check("确实在移动", len(set(xs)) > 3, str(sorted(set(xs))[:6]))
check("移动时朝向是侧面", all(d in ("left", "right", "down") for d in dirs), str(set(dirs)))
check("不会跑出屏幕", min(xs) >= 0 and max(xs) <= 800, f"{min(xs)}-{max(xs)}")

# 方向与镜像
w.move(300, 300)
w.line_y = 300
w.target = (w.x() + 400, w.y() + w.height() / 2)
w.run_mode = False
w.cur_speed = m.SPEED
w.tick()
# 侧面原图朝右，所以向右走用镜像(facing=-1)，向左走用原图
check("往右走：dir=right、镜像翻转", w.dir == "right" and w.facing == -1, f"{w.dir}/{w.facing}")
check("往右走用侧面图", w._sprite_key()[0] == "侧面", str(w._sprite_key()))

w.move(300, 300)
w.line_y = 300
w.target = (w.x() - 260, w.y() + w.height() / 2)
w.run_mode = False
w.cur_speed = m.SPEED
w.tick()
check("往左走：dir=left、原图不翻", w.dir == "left" and w.facing == 1, f"{w.dir}/{w.facing}")

# 走 / 跑两种速度
w.target = (w.x() + 300, w.y() + w.height() / 2)
w.run_mode = False
v_walk = w._speed_now()
w.run_mode = True
v_run = w._speed_now()
check("跑步明显快于走路", v_run > v_walk * 1.5, f"{v_run:.0f} vs {v_walk:.0f}")
check("跑步倍率符合 RUN_FACTOR", abs(v_run - m.SPEED * m.RUN_FACTOR) < 1e-6)
w.target = None
check("没有目标时速度为 0", w._speed_now() == 0.0)

# 跑 / 走是随机挑的
random.seed(1)
w.run_mode = False
w.rest_until = 0
runs = 0
for _ in range(300):
    w.target = None
    w.rest_until = 0
    w._line_target(10 ** 9)
    runs += 1 if w.run_mode else 0
check("走/跑都会出现（约三成跑步）", 60 <= runs <= 140, f"{runs}/300")

# 停下来时的姿态：站着 / 背身 / 侧身（动画模式没有背视图，只换待机片段）
random.seed(7)
w.target = None
w.rest_until = 10 ** 12
poses = set()
for _ in range(600):
    w._line_idle()
    poses.add(w.dir)
if w.animator is not None:
    check("动画模式停下不改朝向（没有背视图）", poses == {w.dir}, str(poses))
else:
    check("停下会背身（背面图）", "up" in poses, str(poses))
    check("停下会正面站立", "down" in poses, str(poses))
    check("停下会侧身", bool(poses & {"left", "right"}), str(poses))
w._set_dir("up", 1)
if w.animator is None:
    check("背身取背面精灵", w._sprite_key()[0] == "背面", str(w._sprite_key()))
else:
    check("动画模式背身也还是同一套动画", w.sprites == {}, str(w._sprite_key()))

# 到达目标 → 停下休息，不再移动
w.move(300, 300)
w.line_y = 300
w.target = (w.x() + w.width() / 2 + 5, w.y() + w.height() / 2)
w.cur_speed = m.SPEED
w.tick()
check("到达后清空目标", w.target is None)
check("到达后进入休息", w.rest_until > w.t * m.TICK, str(w.rest_until))
check("到达后转正面", w.dir == "down", w.dir)
x_rest = w.x()
for _ in range(20):
    w.tick()
check("休息期间原地不动", w.x() == x_rest, f"{w.x()} vs {x_rest}")

# 休息结束后重新起步
w.rest_until = 0
w.tick()
check("休息结束会继续走", w.target is not None or w.x() != x_rest)

# 模式切换写盘
w.set_mode("wander")
check("切回自由散步", w.mode == "wander")
check("模式写进配置", json.load(open(m.CONFIG_PATH, encoding="utf-8"))["mode"] == "wander")
w.set_mode("line")
check("可以再切回横向行走", w.mode == "line")
bad = w.set_mode("flying")
check("非法模式被忽略", w.mode == "line")

# 屏幕太窄时不要死循环
w.move(0, 300)
w.width  # noqa
w._apply_size_metrics()
w.move(0, 300)
w.line_y = 300
w.rest_until = 0
w.target = None
ok = w._line_target(10 ** 9)
check("正常屏幕能挑到目标", ok is True)

close(w)

print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "、".join(FAIL))
sys.exit(1 if FAIL else 0)
