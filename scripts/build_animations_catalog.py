#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 dsh-pet/assets 下的动画资源，生成 catalog.json。

做三件事：
1. 把「中文名 .webm」与「拼音名 .gif」配对（预览图的文件名是中文名的拼音，
   但分词口径不完全一致，所以用去连字符后的相似度做贪心匹配）；
2. 读出每段视频的尺寸 / 帧率 / 时长 / 体积，和每张预览图的大小 / 帧数；
3. 按名称关键词归类（待机 / 吃 / 睡 / 点击回应 / 工作 / 余额 / 碎碎念 / 移动 / 节日 / 其他）。

用法（在项目根目录跑）：
    python scripts/build_animations_catalog.py            # 生成/覆盖 catalog.json
    python scripts/build_animations_catalog.py --check    # 只校验，不写文件（CI 用）

依赖：读视频规格需要 PyAV（pip install av），只是可选增强——
没装时 catalog 里仍会写出文件，只是缺 width/height/fps/duration 字段。
生成 id 用的 pypinyin 同理，没装时退化成用文件名的 md5 前 8 位。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "dsh-pet", "assets")
PREVIEW = os.path.join(ASSETS, "preview")
WEBM = os.path.join(ASSETS, "webm")
OUT = os.path.join(ASSETS, "catalog.json")

# 归类规则：先匹配到的先赢，所以顺序有意义
# 节日排在「吃」前面，否则「中秋赏月吃月饼」会被「吃」抢走
CATEGORY_RULES = [
    ("sleep", ("睡觉",)),
    ("click", ("点击回应", "被鼠标")),
    ("work", ("工作状态", "写代码", "记录")),
    ("balance", ("余额",)),
    ("whisper", ("碎碎念",)),
    ("festival", ("中秋", "腊八", "重阳", "圣诞", "烟花", "孔明灯", "河灯",
                  "红包", "福字", "乞巧", "茱萸", "南瓜灯", "舞狮")),
    ("eat", ("吃", "喝", "火锅", "粥", "糕", "面", "饼", "粽", "团", "开饭")),
    ("idle", ("待机", "呼吸", "发呆", "小憩", "沉眠", "哈欠", "伸懒腰",
              "打瞌睡", "东张西望", "哼歌")),
    ("move", ("跑", "走", "跳", "旋转", "踏步", "漂", "蹲", "爬", "窜")),
    ("play", ("玩", "舞", "魔术", "棋", "秋千", "木马", "水枪", "毽子", "陀螺",
              "镜子", "撸猫", "笛", "琴", "抛接", "气球", "拆礼物", "放风筝", "摇扇")),
    ("effect", ("特效", "泡泡", "开花", "环绕", "现世", "幽灵", "换装", "花",
                "雪人", "变鸽子", "落叶")),
    ("life", ("刷牙", "礼仪")),
]

CATEGORY_LABEL = {
    "idle": "待机 · Idle",
    "eat": "吃 · Eating",
    "sleep": "睡觉 · Sleep",
    "click": "点击回应 · Click",
    "work": "工作 · Work",
    "balance": "余额 · Balance",
    "whisper": "碎碎念 · Whisper",
    "move": "移动 · Movement",
    "play": "玩耍 · Play",
    "festival": "节日 · Festival",
    "effect": "特效 · Effect",
    "life": "日常 · Daily",
    "misc": "其他 · Misc",
}


def pinyin_slug(zh: str) -> str:
    """中文名 -> 拼音 slug（小写、去声调、音节用 - 连接）"""
    base = re.sub(r"[·、，,（）()\s]+", "-", zh)
    try:
        from pypinyin import lazy_pinyin

        # errors 用恒等函数：像「吃Token」这种中英混排要保留 Token 本身，
        # 否则会退化成只剩 "chi"，跟 chi-token.gif 对不上。
        parts = lazy_pinyin(base, errors=lambda x: x)
        out: list[str] = []
        for p in parts:
            for tok in re.split(r"[^A-Za-z0-9]+", p):
                if tok:
                    out.append(tok.lower())
        slug = "-".join(out)
        if slug:
            return slug
    except Exception:
        pass
    import hashlib

    return "anim-" + hashlib.md5(zh.encode("utf-8")).hexdigest()[:8]


def squash(s: str) -> str:
    """比较用的归一化：只留字母数字"""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def gif_info(path: str) -> dict:
    """帧数 + 画布尺寸（直接解析 GIF 头与图像描述符，不依赖第三方库）"""
    info = {}
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:3] != b"GIF":
            return info
        import struct

        info["width"], info["height"] = struct.unpack("<HH", data[6:10])
        # 统计 0x2C（图像描述符）出现次数作为帧数近似值
        frames = 0
        i = 13
        if data[10] & 0x80:  # 全局调色板
            i += 3 * (2 ** ((data[10] & 0x07) + 1))
        n = len(data)
        while i < n:
            if data[i] == 0x2C:
                frames += 1
                i += 10
                flags = data[i - 1]
                if flags & 0x80:
                    i += 3 * (2 ** ((flags & 0x07) + 1))
                i += 1  # LZW 最小码长
                while i < n and data[i]:
                    i += data[i] + 1
                i += 1
            elif data[i] == 0x21:
                i += 2
                while i < n and data[i]:
                    i += data[i] + 1
                i += 1
            elif data[i] == 0x3B:
                break
            else:
                i += 1
        info["frames"] = frames
    except Exception:
        pass
    return info


def webm_info(path: str) -> dict:
    """视频规格：优先 PyAV（能读时长与真实帧率），没装就跳过"""
    info = {}
    try:
        import av
    except Exception:
        return info
    try:
        with av.open(path) as c:
            v = c.streams.video[0]
            info["width"] = int(v.codec_context.width)
            info["height"] = int(v.codec_context.height)
            info["fps"] = round(float(v.average_rate), 3)
            if c.duration:
                info["duration"] = round(float(c.duration / av.time_base), 2)
            info["codec"] = v.codec_context.name
            alpha = (v.metadata or {}).get("ALPHA_MODE")
            if alpha is not None:
                info["alpha"] = str(alpha) == "1"
    except Exception:
        pass
    return info


def categorize(zh: str) -> str:
    for cat, keys in CATEGORY_RULES:
        if any(k in zh for k in keys):
            return cat
    return "misc"


def build(pair_threshold: float = 0.72) -> dict:
    if not os.path.isdir(WEBM):
        raise SystemExit(f"找不到视频目录：{WEBM}")
    webm = sorted(f for f in os.listdir(WEBM) if f.lower().endswith(".webm"))
    gifs = sorted(f for f in os.listdir(PREVIEW) if f.lower().endswith(".gif"))

    # ---- 配对：webm 中文名 vs gif 拼音名 ----
    # 两轮：先去连字符后完全相同的直接认，再按相似度贪心补
    gif_squashed = {g: squash(os.path.splitext(g)[0]) for g in gifs}
    exact = {s: g for g, s in gif_squashed.items()}
    pairs: dict[str, str] = {}
    used_gif: set[str] = set()

    for w in webm:
        s = squash(pinyin_slug(os.path.splitext(w)[0]))
        g = exact.get(s)
        if g and g not in used_gif:
            pairs[w] = g
            used_gif.add(g)

    scored = []
    for w in webm:
        if w in pairs:
            continue
        target = squash(pinyin_slug(os.path.splitext(w)[0]))
        for g, gs in gif_squashed.items():
            if g in used_gif:
                continue
            scored.append((difflib.SequenceMatcher(None, target, gs).ratio(), w, g))
    scored.sort(reverse=True)
    for ratio, w, g in scored:
        if ratio < pair_threshold:
            break
        if w in pairs or g in used_gif:
            continue
        pairs[w] = g
        used_gif.add(g)

    # ---- 组装条目 ----
    items = []
    for w in webm:
        zh = os.path.splitext(w)[0]
        gif = pairs.get(w, "")
        slug = os.path.splitext(gif)[0] if gif else pinyin_slug(zh)
        wpath = os.path.join(WEBM, w)
        item = {
            "id": slug,
            "name": zh,
            "category": categorize(zh),
            "webm": f"webm/{w}",
            "preview": f"preview/{gif}" if gif else None,
            "bytes": os.path.getsize(wpath),
        }
        item.update({k: v for k, v in webm_info(wpath).items() if k != "codec"})
        if gif:
            g = gif_info(os.path.join(PREVIEW, gif))
            item["preview_bytes"] = os.path.getsize(os.path.join(PREVIEW, gif))
            if "frames" in g:
                item["preview_frames"] = g["frames"]
            if "width" in g:
                item["preview_width"], item["preview_height"] = g["width"], g["height"]
        items.append(item)

    # id 去重
    seen: dict[str, int] = {}
    for it in items:
        base = it["id"]
        if base in seen:
            seen[base] += 1
            it["id"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1

    groups: dict[str, list[str]] = {}
    for it in items:
        groups.setdefault(it["category"], []).append(it["id"])

    sizes = [it["bytes"] for it in items]
    missing = [os.path.splitext(it["webm"])[0] for it in items if not it["preview"]]
    orphan = sorted(set(gifs) - used_gif)

    return {
        "schema": 1,
        "about": {
            "title": "大肥鱼桌宠 · 动画库 / DaFeiYu pet animation library",
            "summary": "640×360 VP9-alpha 透明视频（插件实际播放资源）+ 220×124 GIF 预览",
            "video": {"format": "webm", "codec": "vp9", "alpha": True, "width": 640, "height": 360, "fps": 24},
            "preview": {"format": "gif", "width": 220, "height": 124},
            "license": "CC BY-NC-SA 4.0（角色形象） / MIT（代码与资产打包）",
            "source": "https://github.com/PC2005-cloud/dsh-pet",
        },
        "stats": {
            "animations": len(items),
            "with_preview": sum(1 for it in items if it["preview"]),
            "webm_bytes": sum(sizes),
            "preview_bytes": sum(it.get("preview_bytes", 0) for it in items),
            "total_bytes": sum(sizes) + sum(it.get("preview_bytes", 0) for it in items),
        },
        "categories": {k: {"label": CATEGORY_LABEL[k], "count": len(v), "ids": v}
                       for k, v in sorted(groups.items())},
        "unmatched": {"no_preview": missing, "orphan_gif": orphan},
        "animations": items,
    }


RAW_BASE = ("https://raw.githubusercontent.com/csxqnznz-collab/dafeiyu/"
            "main/dsh-pet/assets/")


def to_gallery(cat: dict, width: int = 168) -> str:
    """按分类生成 GIF 画廊（raw 直链，GitHub 上直接动）"""
    names = {it["id"]: it for it in cat["animations"]}
    out = [
        "# 全部动画 · All Animations",
        "",
        f"共 **{cat['stats']['animations']}** 段 640×360 透明动画，"
        f"其中 **{cat['stats']['with_preview']}** 段有 GIF 预览。",
        "GIF 走 raw 直链，在 GitHub 上可以直接动；点图看原视频（`.webm`）。",
        "",
        "> 本文件由 `scripts/build_animations_catalog.py --gallery` 生成，别手改。",
        "",
    ]
    order = ["idle", "move", "click", "play", "work", "eat", "sleep",
             "balance", "whisper", "festival", "effect", "life", "misc"]
    keys = [k for k in order if k in cat["categories"]]
    keys += [k for k in cat["categories"] if k not in keys]

    for key in keys:
        meta = cat["categories"][key]
        out.append(f"## {CATEGORY_LABEL.get(key, key)} · {meta['count']} 段")
        out.append("")
        cells = []
        for aid in meta["ids"]:
            it = names[aid]
            if not it.get("preview"):
                cells.append(f'<td align="center"><sub>{it["name"]}</sub><br>'
                             f'<sub>（无预览）</sub></td>')
                continue
            url = RAW_BASE + it["preview"]
            cells.append(
                f'<td align="center"><a href="{RAW_BASE + it["webm"]}">'
                f'<img src="{url}" width="{width}" alt="{it["name"]}" '
                f'title="{it["name"]} · {it["id"]}"></a><br>'
                f'<sub>{it["name"]}</sub></td>')
        for i in range(0, len(cells), 4):
            out.append('<table><tr>' + "".join(cells[i:i + 4]) + "</tr></table>")
            out.append("")
    out.append("---")
    out.append("")
    out.append("素材来源 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，"
               "形象 **CC BY-NC-SA 4.0（署名 · 非商业 · 相同方式共享）**，详见 [CREDITS.md](CREDITS.md)。")
    return "\n".join(out) + "\n"


def to_markdown(cat: dict) -> str:
    lines = ["| # | 动画 | 拼音 ID | 时长 | 体积 | 预览 |", "|---|---|---|---|---|---|"]
    for i, it in enumerate(cat["animations"], 1):
        dur = f"{it.get('duration', 0):.1f}s" if it.get("duration") else "—"
        kb = it["bytes"] / 1024
        size = f"{kb/1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
        prev = "✅" if it["preview"] else "—"
        lines.append(f"| {i} | {it['name']} | `{it['id']}` | {dur} | {size} | {prev} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验 catalog 是否与磁盘一致")
    ap.add_argument("--markdown", metavar="PATH", help="额外导出一份 Markdown 清单")
    ap.add_argument("--gallery", metavar="PATH", help="生成 GIF 画廊 Markdown（raw 直链）")
    args = ap.parse_args()

    cat = build()

    if args.check:
        if not os.path.exists(OUT):
            print("✗ catalog.json 不存在，请先运行本脚本生成")
            return 1
        old = json.load(open(OUT, encoding="utf-8"))
        if old.get("stats") != cat["stats"]:
            print("✗ catalog 与磁盘不一致：", old.get("stats"), "->", cat["stats"])
            return 1
        print("✓ catalog 与磁盘一致：", cat["stats"]["animations"], "段动画")
        return 0

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cat, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8", newline="\n") as f:
            f.write(to_markdown(cat) + "\n")

    if args.gallery:
        with open(args.gallery, "w", encoding="utf-8", newline="\n") as f:
            f.write(to_gallery(cat))

    s = cat["stats"]
    print(f"✓ 写入 {os.path.relpath(OUT, ROOT)}")
    print(f"  动画 {s['animations']} 段（{s['with_preview']} 段有 GIF 预览）")
    print(f"  视频 {s['webm_bytes']/1048576:.1f} MB + 预览 {s['preview_bytes']/1048576:.1f} MB"
          f" = {s['total_bytes']/1048576:.1f} MB")
    print("  分类：" + "，".join(f"{CATEGORY_LABEL[k].split(' · ')[0]} {v['count']}"
                                for k, v in cat["categories"].items()))
    if cat["unmatched"]["no_preview"]:
        print("  ⚠ 没有预览图：" + "、".join(cat["unmatched"]["no_preview"]))
    if cat["unmatched"]["orphan_gif"]:
        print("  ⚠ 没配到视频的 GIF：" + "、".join(cat["unmatched"]["orphan_gif"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
