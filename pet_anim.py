# -*- coding: utf-8 -*-
"""桌宠动画引擎：把 dsh-pet 的 114 段 VP9-alpha 动画接到桌宠身上。

素材是 640×360 的固定舞台，角色只占中间一小块（约 220×276），四周全是透明留白。
所以这里定义一个固定裁剪框 `STAGE`：所有动画都按同一个框裁、同一个缩放系数缩放，
角色在窗口里的大小和站位就永远一致，换片段不会突然变大变小或跳位置。

`ROLE_CLIPS` 是语义层：桌宠只认「待机 / 点击 / 吃 / 伸懒腰 / 被拖」五个角色，
具体播哪一段在这里挑，换素材不用动主程序。

解码沿用 anim_lib.FrameDecoder（PyAV + libvpx-vp9，只有 libvpx 才拿得到 alpha）。
实测 640×360 每帧约 0.65ms，24fps 只占 2% 单核，常驻没问题。
"""

from __future__ import annotations

import os
import random
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "dsh-pet", "assets")

# 源坐标（640×360）里的裁剪框：x, y, w, h
STAGE_X, STAGE_Y, STAGE_W, STAGE_H = 150, 8, 340, 340
# 角色本体（头顶到脚底）在源坐标里的高度，用来把「窗口里想要多高」换算成缩放比
BODY_H = 276
# 脚底所在的源坐标 y（所有片段都踩在这条线上）
GROUND_Y = 332

FADE = 0.16          # 换片段的淡入时长（秒）

# 语义角色 → 候选动画 id（随机挑一段）
ROLE_CLIPS = {
    # 待机：安静地呼吸、东张西望、打哈欠、打瞌睡
    "idle": ["daiji-huxi-xiuxian", "dongzhangxiwang", "haqian-liantian",
             "yuandi-xiaoqi-chenmian", "da-keshui-bei-jingxing"],
    # 点击回应：6 段里除了「被鼠标拖拽」都算点击反馈
    "click": ["dianji-huiying-yuanqi-huishou", "dianji-huiying-kaixin-yuedong",
              "dianji-huiying-haixiu-jingya", "dianji-huiying-naoyang-gegexiao",
              "dianji-huiying-aojiao-shengqi-ceshen-zhanshi"],
    # 吃：挑画面居中、道具不外溢的几段
    "eat": ["chi-wucan", "chi-zaocan", "chi-baifan", "chi-niangao", "chi-xigua",
            "chijiaozi", "chi-dazhaxie", "chi-tanghulu", "chi-fan-wan-fan",
            "qi-dai-kai-fan"],
    # 伸懒腰（下班）
    "stretch": ["chaoda-shenlanyao"],
    # 被鼠标拖着走
    "drag": ["beishubiao-tuozhuai-xuankong-fankui"],
}

ROLE_LABEL = {
    "idle": "待机随机",
    "click": "点击回应",
    "eat": "到点吃饭",
    "stretch": "伸懒腰",
    "drag": "被拖动",
}


def _load_json(name: str) -> dict:
    import json

    try:
        with open(os.path.join(ASSETS, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_CATALOG: dict | None = None
_CLIPS: dict[str, dict] = {}


def catalog() -> dict:
    global _CATALOG, _CLIPS
    if _CATALOG is None:
        data = _load_json("catalog.json")
        _CATALOG = data
        _CLIPS = {a["id"]: a for a in data.get("animations", [])}
    return _CATALOG


def clip(clip_id: str) -> dict | None:
    catalog()
    return _CLIPS.get(clip_id)


def clip_path(clip_id: str) -> str:
    item = clip(clip_id)
    if not item:
        return ""
    return os.path.join(ASSETS, *item["webm"].split("/"))


def roles() -> list[str]:
    return list(ROLE_CLIPS)


def pick(role: str) -> str | None:
    """从某个角色里随机挑一段存在的动画"""
    catalog()
    ids = [i for i in ROLE_CLIPS.get(role, []) if i in _CLIPS]
    return random.choice(ids) if ids else None


def available() -> bool:
    """动画能不能用：素材在、PyAV 在、而且至少有一段 idle"""
    try:
        import anim_lib
    except Exception:
        return False
    if not anim_lib.av_available():
        return False
    catalog()
    return pick("idle") is not None


def scale_for(body_px: int | float) -> float:
    """窗口里想要的角色高度 → 源坐标缩放比"""
    return max(0.05, float(body_px) / BODY_H)


def stage_size(body_px: int | float) -> tuple[float, float]:
    k = scale_for(body_px)
    return STAGE_W * k, STAGE_H * k


class PetAnimator(QObject):
    """只负责「现在该画哪一帧」，窗口、位移、气泡都不归它管。"""

    frame_changed = Signal()
    clip_finished = Signal(str)

    def __init__(self, assets: str | None = None, parent=None):
        super().__init__(parent)
        self.assets = assets or ASSETS
        self.clip_id: str | None = None
        self.role: str | None = None
        self.mirror = False
        self.loop = True
        self._decoder = None
        self._frame: QImage | None = None
        self._fade_img: QImage | None = None
        self._fade_mirror = False
        self._fade_t0 = 0.0
        self._errors = 0
        self._seq = 0

    # ------------------------------------------------ 状态
    def playing(self) -> bool:
        return self._frame is not None

    def frame(self) -> QImage | None:
        return self._frame

    def fade_frame(self) -> QImage | None:
        return self._fade_img

    def fade_alpha(self) -> float:
        """上一段最后一帧还剩多少不透明度（0=已经淡完）"""
        if self._fade_img is None:
            return 0.0
        t = (time.monotonic() - self._fade_t0) / FADE
        if t >= 1.0:
            self._fade_img = None
            return 0.0
        return max(0.0, 1.0 - t)

    def fade_mirror(self) -> bool:
        return self._fade_mirror

    # ------------------------------------------------ 播放
    def play(self, clip_id: str | None, role: str | None = None,
             loop: bool = True, fade: float = FADE) -> bool:
        if not clip_id:
            return False
        if clip_id == self.clip_id and role == self.role and loop == self.loop:
            return True
        path = clip_path(clip_id)
        if not path or not os.path.exists(path):
            return False

        self._stop_decoder()
        if self._frame is not None and fade > 0:
            self._fade_img = self._frame
            self._fade_mirror = self.mirror
            self._fade_t0 = time.monotonic()
        else:
            self._fade_img = None

        self.clip_id = clip_id
        self.role = role
        self.loop = loop
        item = clip(clip_id) or {}
        try:
            from anim_lib import FrameDecoder
        except Exception:
            return False
        dec = FrameDecoder(path, item.get("fps", 24.0), loop=loop, parent=self)
        dec.sig_frame.connect(self._on_frame)
        dec.sig_error.connect(self._on_error)
        dec.finished.connect(lambda c=clip_id, d=dec: self._on_done(c, d))
        self._decoder = dec
        dec.start()
        return True

    def play_role(self, role: str, loop: bool | None = None,
                  avoid: str | None = None) -> bool:
        """按角色随机播一段；avoid 用来避免待机时连着播同一条"""
        cid = pick(role)
        if cid is None:
            return False
        if avoid and len(ROLE_CLIPS.get(role, [])) > 1 and cid == avoid:
            cid = pick(role)
        return self.play(cid, role=role, loop=True if loop is None else loop)

    def set_mirror(self, on: bool):
        on = bool(on)
        if on != self.mirror:
            self.mirror = on
            self.frame_changed.emit()

    def stop(self):
        self._stop_decoder()
        self.clip_id = None
        self.role = None
        self._frame = None
        self._fade_img = None

    # ------------------------------------------------ 内部
    def _stop_decoder(self):
        if self._decoder is not None:
            dec, self._decoder = self._decoder, None
            try:
                dec.sig_frame.disconnect(self._on_frame)
                dec.sig_error.disconnect(self._on_error)
            except Exception:
                pass
            dec.stop()
            dec.wait(1500)

    def _on_frame(self, img: QImage):
        self._frame = img
        self._seq += 1
        self._errors = 0
        self.frame_changed.emit()

    def _on_error(self, msg: str):
        self._errors += 1
        print(f"[pet_anim] 解码失败 {self.clip_id}：{msg}")

    def _on_done(self, clip_id: str, dec):
        if dec is not self._decoder:
            return                      # 已经被换掉了，别误报
        if self.loop:
            return
        self.clip_finished.emit(clip_id)
