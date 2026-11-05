# 大肥鱼 · 动画素材库 / Animation Asset Library

桌宠能用的**透明动画**都放在这里：114 段 640×360 的 VP9-alpha 视频，配 109 张 GIF 预览。
角色就是本项目那只蓝发鲸鱼小女仆「大肥鱼」——待机、走动、吃喝、玩耍、工作、节日、睡觉、点击回应，全套。

> **在桌宠里看**：右键桌宠 → **🎬 动画库（114 段）**，左侧搜索/分类，右侧直接播（真 alpha，棋盘格能看出透明）。

---

## 规格 / Specs

| | 播放资源（唯一发布格式） | GIF 预览 |
|---|---|---|
| 格式 | **WebM · VP9 + alpha**（`ALPHA_MODE=1`，alpha 存在 BlockAdditional 里） | GIF（1-bit 透明，白底处其实是透明的） |
| 分辨率 | **640 × 360** | 220 × 124 |
| 帧率 | 24 fps | 12 fps |
| 时长 | 4.9 – 10.0 s（大多 10.04 s，可首尾相接循环） | 同左 |
| 体积 | 55.2 MB / 114 段（平均 0.48 MB） | 65.9 MB / 109 张 |
| 位置 | `assets/webm/` | `assets/preview/` |
| 命名 | 中文名（如 `吃西瓜.webm`） | **拼音**（如 `chi-xigua.gif`） |

GIF 用拼音命名是为了跨平台：中文文件名在 zip / 老 Windows / 部分 CDN 上容易乱码，
拼音则到处都安全；视频保留中文名是因为本仓库自己的加载逻辑按中文名走，改起来没必要。

## 目录 / Layout

```
dsh-pet/
├── assets/
│   ├── catalog.json      # 机器可读清单：id / 中文名 / 分类 / 时长 / 帧率 / 体积 / 双格式路径
│   ├── preview/          # 109 张 GIF 预览，拼音文件名
│   └── webm/             # 114 段 VP9-alpha 透明视频（唯一发布格式）
├── GALLERY.md            # 全部动画的画廊（raw 直链，GitHub 上直接动）
├── CREDITS.md            # 素材来源与授权链（务必先读）
└── README.md
```

`catalog.json` 已经和磁盘做过一致性校验（`python scripts/build_animations_catalog.py --check`），
可以放心当索引直接用：

```json
{
  "id": "chi-xigua",
  "name": "吃西瓜",
  "category": "eat",
  "webm": "webm/吃西瓜.webm",
  "preview": "preview/chi-xigua.gif",
  "width": 640, "height": 360, "fps": 24.0, "duration": 10.04, "alpha": true,
  "bytes": 482304, "preview_frames": 120
}
```

## 怎么用 / How to use

### 1. 在浏览器 / OBS / 剪映里

`assets/webm/*.webm` 拖进去就是透明背景素材（Chrome / Edge / OBS 都原生支持 VP9 alpha）。
OBS 里如果看到黑底，把来源的「YUV 色彩空间 / 范围」保持默认，别勾「alpha 通道」反转。

### 2. 在 Python 里（本项目`anim_lib.py` 的做法）

**关键一点**：VP9 的 alpha 必须用 **libvpx 解码器**解，ffmpeg 自带的 `vp9` 解码器会把 alpha 丢掉，
画面直接变黑底。所以 `av.open()` 之后要自己造一个 `libvpx-vp9` 的解码上下文：

```python
import av
from PySide6.QtGui import QImage

with av.open("dsh-pet/assets/webm/吃西瓜.webm") as c:
    stream = c.streams.video[0]
    ctx = av.CodecContext.create("libvpx-vp9", "r")      # ← 必须是它
    for pkt in c.demux(stream):
        for frame in ctx.decode(pkt):
            arr = frame.to_ndarray(format="rgba")        # 带上真实 alpha
            h, w = arr.shape[:2]
            img = QImage(arr.data, w, h, arr.strides[0],
                         QImage.Format.Format_RGBA8888).copy()
```

命令行等价写法（导出带 alpha 的 PNG 序列）：

```bash
ffmpeg -c:v libvpx-vp9 -i "assets/webm/吃西瓜.webm" -pix_fmt rgba frames/%04d.png
```

### 3. 直接读清单做随机动作

```python
import json, random, pathlib
cat = json.loads(pathlib.Path("dsh-pet/assets/catalog.json").read_text(encoding="utf-8"))
idle = [a for a in cat["animations"] if a["category"] == "idle"]
pick = random.choice(idle)            # 然后按上面的方式播 pick["webm"]
```

## 全部动画 / All animations

**114 段**，按分类折叠在 → **[GALLERY.md](GALLERY.md)**（GIF raw 直链，GitHub 上会直接动）。

| 分类 | 数量 | 举例 |
|---|---|---|
| 待机 Idle | 7 | 待机呼吸休闲、东张西望、打瞌睡被惊醒、超大伸懒腰 |
| 移动 Movement | 10 | 开心小跑、侧身急躁跑、原地左转奔跑、螃蟹走路 |
| 点击回应 Click | 6 | 元气挥手、开心跃动、傲娇生气、害羞惊讶、挠痒咯咯笑 |
| 玩耍 Play | 21 | 可爱宅舞、撸猫、荡秋千、玩游戏气急败坏、扑克魔术 |
| 工作 Work | 8 | 写代码、忙碌点按、思考冒泡、雀跃庆祝、垂头叹气冒汗 |
| 吃 Eating | 24 | 吃西瓜、涮火锅、吃大闸蟹、吃汤圆、吃饺子、偷吃零食被抓住 |
| 睡觉 Sleep | 3 | 睡觉-开始 / 循环 / 起来 |
| 余额 Balance | 6 | 钱袋满溢、袋空如洗、金袋叮当、数金皱眉 |
| 碎碎念 Whisper | 4 | 发呆碎碎念、对屏碎碎念、擦桌碎碎念 |
| 节日 Festival | 13 | 中秋赏月吃月饼、装点圣诞树、放烟花、舞狮头、写福字 |
| 特效 Effect | 10 | 鲸鱼吐泡泡特效、蓝鲸现世、凭空生花、动物环绕 |
| 日常 Daily | 2 | 晨间刷牙、女仆屈膝礼仪 |

## 重新生成清单 / Regenerate

```bash
pip install av pypinyin                      # 可选，装上才有精确时长/帧率
python scripts/build_animations_catalog.py   # 重写 catalog.json
python scripts/build_animations_catalog.py --gallery dsh-pet/GALLERY.md
python scripts/build_animations_catalog.py --check          # CI 里校验一致性
```

脚本会自动把「中文名视频」和「拼音名 GIF」配对（先去连字符精确匹配，再按相似度贪心补），
所以以后加素材只要按同样命名丢两个目录，重跑一次就行。

## 来源与授权 / Credits & License

这套动画**不是本项目原创**，来自 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。
形象「大肥鱼」适用 **CC BY-NC-SA 4.0：署名 · 非商业 · 相同方式共享**。

- ✅ 可以：个人使用、二次创作、随本项目分发（保留署名与本协议）
- ❌ 不可以：任何形式的商业化（含付费产品、广告变现、付费下载）
- 详细署名链与协议原文见 **[CREDITS.md](CREDITS.md)** —— 用之前请务必读一遍。
