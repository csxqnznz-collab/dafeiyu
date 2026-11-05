"""大肥鱼桌宠 · 长期记忆引擎（Companion Memory Engine）

本地优先：所有数据存 SQLite，不依赖云端账号。
独立模块：不修改桌宠原有 UI / 动画 / 交互，只通过 engine 门面接入。

对外只暴露 MemoryEngine。
"""

from .engine import MemoryEngine  # noqa: F401

__all__ = ["MemoryEngine"]
__version__ = "1.0.0"
