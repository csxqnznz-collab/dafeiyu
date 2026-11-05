# -*- coding: utf-8 -*-
"""扫描 dsh-pet/assets/webm/*.webm，算出每段动画「角色真正占用的区域」。

为什么需要：素材是 640×360 的固定舞台，角色只占中间一小块（约 220×270），
两边全是透明留白。桌宠窗口只有两三百像素高，直接整帧缩放会把鱼（人）缩成蚂蚁。
所以先把每段动画的 alpha 包围盒量出来，运行时按包围盒裁剪再缩放。

结果写到 dsh-pet/assets/bbox.json：
    {"clips": {"<id>": [x, y, w, h], ...}, "union": [...], "sample": {...}}

用法：
    python scripts/build_anim_bbox.py            # 生成/覆盖 bbox.json
    python scripts/build_anim_bbox.py --stats    # 只打印统计
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "dsh-pet", "assets")
CATALOG = os.path.join(ASSETS, "catalog.json")
OUT = os.path.join(ASSETS, "bbox.json")

ALPHA_MIN = 12           # 低于这个 alpha 当全透明（抗锯齿边缘不算）
SAMPLE_MAX = 18          # 每段最多采样多少帧


def clip_bbox(path: str, sample_max: int = SAMPLE_MAX):
    """返回这段视频所有采样帧 alpha 的并集包围盒 (x, y, w, h)。"""
    import av
    import numpy as np

    boxes = []
    with av.open(path) as c:
        stream = c.streams.video[0]
        ctx = av.CodecContext.create("libvpx-vp9", "r")
        frames = []
        for pkt in c.demux(stream):
            for f in ctx.decode(pkt):
                frames.append(f)
    if not frames:
        return None
    step = max(1, len(frames) // sample_max)
    for f in frames[::step]:
        arr = f.to_ndarray(format="rgba")
        a = arr[:, :, 3]
        ys, xs = np.nonzero(a > ALPHA_MIN)
        if len(xs) == 0:
            continue
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return [x0, y0, x1 - x0 + 1, y1 - y0 + 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--only", default="", help="只处理这些 id（逗号分隔）")
    args = ap.parse_args()

    if not os.path.exists(CATALOG):
        print(f"找不到 {CATALOG}，先跑 build_animations_catalog.py")
        return 1
    with open(CATALOG, "r", encoding="utf-8") as f:
        cat = json.load(f)
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    old = {}
    if os.path.exists(OUT) and not args.stats:
        try:
            with open(OUT, "r", encoding="utf-8") as f:
                old = json.load(f).get("clips", {})
        except Exception:
            old = {}

    clips = dict(old)
    for i, item in enumerate(cat["animations"], 1):
        aid = item["id"]
        if only and aid not in only:
            continue
        if aid in clips and not only:
            continue
        path = os.path.join(ASSETS, *item["webm"].split("/"))
        box = clip_bbox(path)
        if box is None:
            print(f"[{i:>3}] {aid:<42} 空帧，跳过")
            continue
        clips[aid] = box
        print(f"[{i:>3}/{len(cat['animations'])}] {aid:<42} {box}")

    if args.stats:
        print(f"\n共 {len(clips)} 段")
        return 0

    xs0 = [b[0] for b in clips.values()]
    ys0 = [b[1] for b in clips.values()]
    xs1 = [b[0] + b[2] for b in clips.values()]
    ys1 = [b[1] + b[3] for b in clips.values()]
    union = [min(xs0), min(ys0), max(xs1) - min(xs0), max(ys1) - min(ys0)]

    payload = {
        "about": {
            "source": "scripts/build_anim_bbox.py",
            "rule": "每段动画所有采样帧 alpha 的并集包围盒 [x, y, w, h]，坐标系 640×360",
        },
        "union": union,
        "clips": dict(sorted(clips.items())),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n写入 {OUT}：{len(clips)} 段，总并集 {union}")

    ws = sorted(b[2] for b in clips.values())
    hs = sorted(b[3] for b in clips.values())
    print(f"宽度 中位 {ws[len(ws)//2]} / 最大 {ws[-1]}；"
          f"高度 中位 {hs[len(hs)//2]} / 最大 {hs[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
