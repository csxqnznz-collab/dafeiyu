"""动画库测试：目录完整性 / 配对正确性 / 解码 alpha / 面板行为

运行： .venv\\Scripts\\python.exe tests\\test_anim_lib.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import anim_lib  # noqa: E402
from anim_lib import AnimLibraryDialog, FrameDecoder, decode_frame  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- 目录
cat = anim_lib.load_catalog(reload=True)
items = cat["animations"]
print(f"目录：{len(items)} 段动画\n")

check("catalog.json 能读出来", len(items) > 0, str(len(items)))
check("动画数量 114", len(items) == 114, str(len(items)))
check("有 109 张 GIF 预览", cat["stats"]["with_preview"] == 109, str(cat["stats"]))

ids = [it["id"] for it in items]
check("id 唯一", len(ids) == len(set(ids)), f"{len(ids)} 个 id / {len(set(ids))} 个唯一")

missing_webm = [it["name"] for it in items if not os.path.exists(anim_lib.abs_path(it, "webm"))]
check("每个 webm 都在磁盘上", not missing_webm, str(missing_webm[:3]))

missing_gif = [it["name"] for it in items
               if it.get("preview") and not os.path.exists(anim_lib.abs_path(it, "preview"))]
check("每个 preview 都在磁盘上", not missing_gif, str(missing_gif[:3]))

bad_size = [(it["name"], it.get("width"), it.get("height")) for it in items
            if (it.get("width"), it.get("height")) != (640, 360)]
check("全部 640×360", not bad_size, str(bad_size[:3]))

bad_fps = [it["name"] for it in items if abs(it.get("fps", 0) - 24.0) > 0.01]
check("全部 24fps", not bad_fps, str(bad_fps[:3]))

no_alpha = [it["name"] for it in items if it.get("alpha") is not True]
check("全部标了 alpha", not no_alpha, str(no_alpha[:3]))

# GIF 文件名 = 拼音 id
stem_mismatch = []
for it in items:
    if not it.get("preview"):
        continue
    stem = os.path.splitext(os.path.basename(it["preview"]))[0]
    if stem != it["id"]:
        stem_mismatch.append((it["id"], stem))
check("GIF 文件名与拼音 id 一致", not stem_mismatch, str(stem_mismatch[:3]))

# 分类覆盖
cats = cat["categories"]
total = sum(c["count"] for c in cats.values())
check("分类计数之和 = 动画数", total == len(items), f"{total} vs {len(items)}")
check("没有落到 misc 的（分类规则够用）", "misc" not in cats, str(list(cats)))

# 每个分类都有中文标签
no_label = [k for k, v in cats.items() if "·" not in v.get("label", "")]
check("每个分类都有中英标签", not no_label, str(no_label))

# ---------------------------------------------------------------- 解码
if anim_lib.av_available():
    it = anim_lib.by_id("chi-xigua")
    check("按 id 能查到 吃西瓜", it is not None and it["name"] == "吃西瓜")

    img = decode_frame(anim_lib.abs_path(it, "webm"), 20)
    check("decode_frame 出图", img is not None)
    if img is not None:
        check("解出来的尺寸是 640×360", (img.width(), img.height()) == (640, 360),
              f"{img.width()}x{img.height()}")
        alphas = []
        for y in range(0, img.height(), 17):
            for x in range(0, img.width(), 17):
                alphas.append(img.pixelColor(x, y).alpha())
        check("alpha 真的保留（有全透明像素）", min(alphas) == 0, f"min={min(alphas)}")
        check("alpha 真的有实心像素", max(alphas) == 255, f"max={max(alphas)}")
        transparent = sum(1 for a in alphas if a < 128) / len(alphas)
        check("透明像素占比 50%~95%（角色只占中间一块）", 0.5 < transparent < 0.95,
              f"{transparent:.2f}")
else:
    print("跳过解码测试：没装 PyAV")

# ---------------------------------------------------------------- 流式解码
if anim_lib.av_available():
    got = []
    dec = FrameDecoder(anim_lib.abs_path(anim_lib.by_id("chi-xigua"), "webm"),
                       fps=24, loop=False)
    dec.sig_frame.connect(lambda im: got.append(im))
    dec.start()
    t0 = time.time()
    while dec.isRunning() and time.time() - t0 < 20:
        app.processEvents()
        time.sleep(0.02)
    dec.wait(3000)
    check("流式解码能收到帧", len(got) > 100, str(len(got)))
    check("流式解码总帧数 ~241", 200 < len(got) < 260, str(len(got)))
    check("帧尺寸一致", got and got[0].width() == 640)

    # 循环模式：应能超过单次时长仍继续送帧
    got2 = []
    dec2 = FrameDecoder(anim_lib.abs_path(anim_lib.by_id("chi-xigua"), "webm"),
                        fps=24, loop=True)
    dec2.sig_frame.connect(lambda im: got2.append(im))
    dec2.start()
    t0 = time.time()
    while time.time() - t0 < 12 and len(got2) < 250:
        app.processEvents()
        time.sleep(0.02)
    dec2.stop()
    dec2.wait(3000)
    check("循环模式会重播（帧数超过单次）", len(got2) >= 241, str(len(got2)))

# ---------------------------------------------------------------- 面板
dlg = AnimLibraryDialog()
dlg.show()
app.processEvents()

check("面板列出了全部条目", dlg.list.count() == 114, str(dlg.list.count()))
check("默认选中第一段并开始播", dlg._current is not None)

# 搜索
dlg.search.setText("西瓜")
app.processEvents()
check("搜索「西瓜」只剩 1 条", dlg.list.count() == 1, str(dlg.list.count()))
check("搜到的就是 吃西瓜", dlg.list.item(0).text() == "吃西瓜", dlg.list.item(0).text())

# 拼音也能搜
dlg.search.setText("paojie")
app.processEvents()
check("拼音 id 也能搜到", dlg.list.count() >= 1, str(dlg.list.count()))
dlg.search.clear()

# 分类筛选
dlg.cat_box.setCurrentIndex(1)          # 第一项是"全部分类"
app.processEvents()
key = dlg.cat_box.itemData(1)
expect = cats[key]["count"]
check("分类筛选生效", dlg.list.count() == expect, f"{dlg.list.count()} vs {expect} ({key})")
dlg.cat_box.setCurrentIndex(0)
app.processEvents()

# 切一段没有预览的（侧身急躁跑）：应正常播，不崩
it_np = anim_lib.by_id("ceshen-jizao-pao") or next(
    (x for x in items if not x.get("preview")), None)
if it_np:
    dlg.play(it_np)
    app.processEvents()
    check("没有 GIF 预览的也能播", dlg._current["name"] == it_np["name"])
    check("无预览时元信息有提示", "无 GIF 预览" in dlg.meta_lab.text(), dlg.meta_lab.text())

# 复制链接
dlg.play(anim_lib.by_id("chi-xigua"))
app.processEvents()
dlg._copy_link()
clip = QApplication.clipboard().text()
check("复制的是 raw 直链", clip.startswith("https://raw.githubusercontent.com/") and clip.endswith(".gif"),
      clip)
check("链接里带拼音文件名", "chi-xigua.gif" in clip, clip)

# 拖动：无边框窗口没有系统标题栏，之前完全拖不动
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

dlg.move(400, 300)
app.processEvents()
QTest.mousePress(dlg.head, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(60, 10))
app.processEvents()
check("标题栏按下就能抓住窗口", dlg._drag_origin is not None, str(dlg._drag_origin))
QTest.mouseMove(dlg.head, QPoint(140, 60), 20)
app.processEvents()
QTest.mouseRelease(dlg.head, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(140, 60))
app.processEvents()
check("拖标题栏窗口跟着走", dlg.pos() == QPoint(480, 350), str(dlg.pos()))
check("松开后清掉拖动状态", dlg._drag_origin is None)
check("拖完记住位置", AnimLibraryDialog._last_pos == QPoint(480, 350),
      str(AnimLibraryDialog._last_pos))

dlg.move(300, 200)
app.processEvents()
QTest.mousePress(dlg.card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(6, 300))
QTest.mouseMove(dlg.card, QPoint(-54, 250), 20)
app.processEvents()
QTest.mouseRelease(dlg.card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(-54, 250))
app.processEvents()
check("卡片空白处也能拖", dlg.pos() == QPoint(240, 150), str(dlg.pos()))

# 位置永远别掉到屏幕外
AnimLibraryDialog._last_pos = QPoint(99999, 99999)
dlg2 = AnimLibraryDialog()
dlg2.show()
app.processEvents()
scr = dlg2.screen().availableGeometry() if dlg2.screen() else None
inside = dlg2.pos().x() < (scr.right() if scr else 2000) and dlg2.pos().y() < (scr.bottom() if scr else 2000)
check("记住的位置会被夹回屏幕内", inside, f"{dlg2.pos()} / {scr}")
dlg2._stop_playback()
dlg2.close()
AnimLibraryDialog._last_pos = None

# 关闭时停掉解码线程
dlg._stop_playback()
check("关闭后解码器已释放", dlg._decoder is None)
dlg.close()

# ---------------------------------------------------------------- 优雅降级
# QMovie 兜底单独起进程跑：它和前面那些解码线程在同一个进程里退出时会踩到 Qt 的析构竞态



fallback_fail = os.path.join(tempfile.mkdtemp(prefix="dfy_anim_"), "fallback.py")
with open(fallback_fail, "w", encoding="utf-8") as f:
    f.write(f'''
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"{ROOT}")
os.chdir(r"{ROOT}")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import anim_lib
anim_lib.av_available = lambda: False
dlg = anim_lib.AnimLibraryDialog()
dlg.show(); app.processEvents()
dlg.play(anim_lib.by_id("chi-xigua")); app.processEvents()
print("movie", dlg._movie is not None)
print("decoder", dlg._decoder is not None)
dlg._stop_playback(); dlg.close()
sys.stdout.flush()
os._exit(0)
''')
r = subprocess.run([sys.executable, fallback_fail], capture_output=True, text=True, timeout=120)
out = r.stdout
check("没有 PyAV 时退回 QMovie", "movie True" in out, out + r.stderr[-200:])
check("没有 PyAV 时不开解码线程", "decoder False" in out, out)

# ---------------------------------------------------------------- 构建脚本


r = subprocess.run([sys.executable, "scripts/build_animations_catalog.py", "--check"],
                   capture_output=True, text=True)
check("catalog 与磁盘一致（--check 通过）", r.returncode == 0, (r.stdout + r.stderr)[-200:])

print(f"\n结果：{len(PASS)} 项通过" + (f"，{len(FAIL)} 项失败" if FAIL else "，全部通过"))
if FAIL:
    print("失败项：" + "；".join(FAIL))

# 解码线程与 Qt 的析构顺序在 Windows 上偶尔会踩到，直接退出，跳过解释器清理
sys.stdout.flush()
os._exit(1 if FAIL else 0)
