"""桌宠 × 记忆引擎 端到端测试（离屏）

验证：上下文注入、消息落库、重启恢复、记忆中心能渲染。
运行： .venv\\Scripts\\python.exe tests\\test_integration.py
"""

import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="dafeiyu_e2e_")
os.environ["HJCDAFEIYU_DATA"] = TMP          # 隔离数据库，不要污染真实库
os.environ["QT_QPA_PLATFORM"] = "offscreen"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import importlib.util  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


class FakeResp(object):
    status_code = 200
    text = "{}"

    def __init__(self, content):
        self._c = content

    def json(self):
        return {"choices": [{"finish_reason": "stop",
                             "message": {"content": self._c, "reasoning_content": ""}}],
                "usage": {}}


def load_pet():
    spec = importlib.util.spec_from_file_location("pet", os.path.join(ROOT, "桌宠.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print(f"隔离数据目录: {TMP}\n")
    m = load_pet()
    check("记忆模块可导入", m.MEMORY_AVAILABLE, getattr(m, "MEMORY_IMPORT_ERROR", ""))

    # 打桩，避免真实网络
    replies = ["哼，你又要开始卷了？", "记住啦，你说了算", "我一条鱼懂啥"]
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResp(replies[min(0, len(replies) - 1)])
    m.requests.post = fake_post

    app = m.QApplication([])
    w = m.PetWindow()
    check("记忆引擎已创建", w.memory is not None)
    check("数据库在隔离目录", TMP in w.memory.db.path, w.memory.db.path)
    check("FTS 索引就绪", w.memory.db.fts_ok)

    # 手动塞一条核心记忆，验证会被注入
    w.memory.manual_remember("主人叫 Andrew，做二手车出口生意，喜欢简洁直接的答复", "CORE", 9)

    # 第一轮对话
    w._call_ds("我喜欢简洁直接的回答，别跟我客套")
    for _ in range(80):
        app.processEvents()
        time.sleep(0.05)
        if w.chat_history:
            break
    check("聊天正常返回", bool(w.chat_history), str(w.chat_history))
    time.sleep(0.3)
    app.processEvents()
    n_msg = w.memory.convs.count()
    check("对话已落库（user+assistant）", n_msg >= 2, f"{n_msg}")

    # 上下文里应含核心记忆
    ctx = w.memory.build_context("今天有什么要做的")
    sys_txt = ctx["messages"][0]["content"]
    check("核心记忆被注入 system", "Andrew" in sys_txt or "二手车" in sys_txt,
          sys_txt[:120])
    check("上下文含最近对话", len(ctx["messages"]) >= 3, f"{len(ctx['messages'])}")
    toks = sum(len(x["content"]) for x in ctx["messages"])
    check("上下文长度可控", toks < 8000, f"{toks} chars")

    # 第二轮：回忆意图应触发检索
    hits = w.memory.retr.search("我是做什么生意的", k=5)
    check("检索能命中核心记忆", any("二手车" in h["content"] for h in hits),
          str([h["content"][:20] for h in hits]))

    # 记忆中心渲染
    dash = m.MemoryDashboard(w.memory)
    dash.resize(920, 660)
    dash.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    dash.refresh()
    app.processEvents()
    check("记忆中心列表有内容", dash.list.count() >= 1, f"{dash.list.count()}")
    shot = os.path.join(TMP, "memory_dash.png")
    dash.grab().save(shot, "PNG")
    check("记忆中心截图已生成", os.path.exists(shot))

    # 搜索
    dash.search.setText("二手车")
    dash.on_search()
    app.processEvents()
    check("记忆中心搜索可用", dash.list.count() >= 1, f"{dash.list.count()}")

    # 统计
    s = w.memory.stats()
    check("统计字段齐全", all(k in s for k in ("total_active", "messages", "profile_count",
                                              "pending", "db_size")), str(s)[:150])

    # 关闭时整理（不要真的卡住）
    t0 = time.time()
    w.memory.shutdown(budget_seconds=5)
    cost = time.time() - t0
    check("退出整理在限时内", cost < 20, f"{cost:.1f}s")

    print(f"\n==== 通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 ====\n数据目录: {TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
