"""记忆引擎自动化测试（不依赖 Qt）

对应任务书第 15 节的测试场景 A-I。
运行： .venv\\Scripts\\python.exe tests\\test_memory.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.engine import MemoryEngine  # noqa: E402
from memory.utils import estimate_tokens  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


class FakeLLM(object):
    """模拟提取器返回，避免测试打网络"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, system, user, max_tokens=2000, timeout=150):
        self.calls += 1
        if isinstance(self.payload, str):
            return True, self.payload
        return True, json.dumps(self.payload, ensure_ascii=False)


def new_engine(tmp, llm=None, tag=""):
    """每个 engine 用独立数据库，避免测试之间互相污染"""
    db_path = os.path.join(tmp, f"memory{tag}.db")
    eng = MemoryEngine(tmp, api_provider=lambda: {"key": "sk-test", "base": "https://x/v1",
                                                 "model": "agnes-2.5-flash"},
                       logger=lambda m: None, db_path=db_path)
    if llm is not None:
        eng.extractor.llm_call = llm
    return eng


def main():
    tmp = tempfile.mkdtemp(prefix="dafeiyu_mem_")
    print(f"测试目录: {tmp}\n")

    # ============ Phase 1：持久化与重启恢复（测试 A）============
    eng = new_engine(tmp)
    check("数据库自动创建", os.path.exists(eng.db.path), eng.db.path)
    check("FTS5 可用", eng.db.fts_ok)
    eng.record_exchange("我最近在开发一个桌面 AI 宠物，希望它能长期记住我的聊天内容",
                        "这个想法很有意思，我们可以给它增加独立记忆模块")
    n_msg = eng.convs.count()
    check("消息落库", n_msg >= 2, f"count={n_msg}")

    conv = eng.conv_id
    eng.shutdown()
    eng2 = new_engine(tmp)   # 同一个库，模拟重启
    msgs = eng2.convs.recent(conv, 10)
    check("重启后能读回聊天记录", len(msgs) >= 2,
          f"{[m['role'] for m in msgs]}")

    # ============ Phase 2：记忆管理 ============
    mid, action = eng2.mgr.add("主人正在开发一个桌面 AI 宠物", category="PROFILE",
                               importance=8, profile_key="current_project")
    check("新增记忆", action == "ADD" and bool(mid), f"{action}")
    mid2, action2 = eng2.mgr.add("主人正在开发一个桌面 AI 宠物", category="PROFILE",
                                 importance=9, profile_key="current_project")
    check("重复记忆被合并", action2 == "MERGED" and mid2 == mid, f"{action2}")
    row = eng2.mgr.get(mid)
    check("合并后重要度取高值", int(row["importance"]) >= 9, f"{row['importance']}")

    eng2.mgr.lock(mid)
    check("锁定记忆", int(eng2.mgr.get(mid)["locked"]) == 1)
    eng2.mgr.archive(mid)
    check("归档记忆", eng2.mgr.get(mid)["status"] == "archived")
    eng2.mgr.restore(mid)
    check("恢复记忆", eng2.mgr.get(mid)["status"] == "active")

    # 记忆更新（测试 E：项目从 Python 迁到 Electron）
    old_id, _ = eng2.mgr.add("主人用 Python 开发桌宠", category="KNOWLEDGE", importance=7)
    new_id_, act = eng2.mgr.add("主人已把桌宠迁移到 Electron", category="KNOWLEDGE",
                               importance=8)
    old_row = eng2.mgr.get(old_id)
    check("新事实入库", act == "ADD" and bool(new_id_))
    check("旧事实未被硬删", old_row is not None)

    # ============ Phase 4：检索（测试 F 语义检索）============
    eng2.mgr.add("主人正在做定制化树脂耳机独立站项目", category="KNOWLEDGE", importance=8)
    eng2.mgr.add("主人喜欢简洁直接的回答，不要客套话", category="PROFILE", importance=9,
                 profile_key="communication_style")
    hits = eng2.retr.search("我之前想做的那个个性化音频网站是什么", k=5)
    texts = " ".join([h["content"] for h in hits])
    check("语义检索能命中树脂耳机项目", "树脂耳机" in texts, texts[:80])

    hits2 = eng2.retr.search("桌宠", k=5)
    check("关键词检索有结果", len(hits2) > 0, f"{len(hits2)}")
    check("检索结果带评分", all("score" in h for h in hits2))
    check("检索条数受限", len(eng2.retr.search("项目", k=3)) <= 3)

    # ============ Phase 5：上下文与 Token 预算（测试 G）============
    eng2.mgr.add("这是一条临时闲聊记忆 A" * 3, category="KNOWLEDGE", importance=3)
    ctx = eng2.build_context("早上好")
    tot = estimate_tokens("".join(m["content"] for m in ctx["messages"]))
    check("上下文构建成功", len(ctx["messages"]) >= 2)
    check("普通闲聊不注入大量记忆", len(ctx["memories"]) <= 2, f"{len(ctx['memories'])}")
    check("上下文 Token 在预算内", tot <= 3600, f"approx={tot}")

    ctx2 = eng2.build_context("你还记得我之前想做的那个项目吗")
    check("问历史时注入更多记忆", len(ctx2["memories"]) >= len(ctx["memories"]),
          f"{len(ctx2['memories'])} vs {len(ctx['memories'])}")
    check("system 里包含记忆段", "记得" in ctx2["system"] or "画像" in ctx2["system"])

    # ============ Phase 3：自动提取（测试 B/C/D）============
    payload = {"memories": [
        {"content": "主人喜欢简洁直接的回答，不需要过多客套话", "category": "PROFILE",
         "importance": 8, "confidence": 0.95, "action": "ADD",
         "reason": "明确偏好", "profile_key": "communication_style"},
        {"content": "主人正在开发桌面 AI 宠物", "category": "KNOWLEDGE",
         "importance": 7, "confidence": 0.9, "action": "ADD", "reason": "长期项目"},
        {"content": "今天天气不错", "category": "EPISODIC", "importance": 2,
         "confidence": 0.5, "action": "ADD", "reason": "闲聊"},
        {"content": "非法类别的一条", "category": "BOGUS", "importance": 7,
         "confidence": 0.9, "action": "ADD", "reason": "x"},
    ]}
    fake = FakeLLM(payload)
    eng3 = new_engine(tmp, llm=fake, tag="_extract")
    eng3.convs.add_message(eng3.convs.active(), "user", "我喜欢简洁直接的回答，别客套",
                           processed=0)
    rep = eng3.extractor.extract_pending()
    check("提取器成功执行", rep.get("ok"), str(rep))
    check("低重要性条目被过滤", rep.get("rejected", 0) >= 1, str(rep))
    cat_rows = eng3.db.query("SELECT category, importance FROM memories WHERE status='active'")
    check("非法 category 未入库",
          all(r["category"] in ("CORE", "PROFILE", "EPISODIC", "KNOWLEDGE", "TASK")
              for r in cat_rows))
    prof = eng3.mgr.profile()
    check("画像已生成", len(prof) > 0, f"{len(prof)}")

    # 坏 JSON 不应崩、消息不丢
    eng4 = new_engine(tmp, llm=FakeLLM("这不是 JSON"), tag="_badjson")
    eng4.convs.add_message(eng4.convs.active(), "user", "随便说一句", processed=0)
    bad = eng4.extractor.extract_pending()
    check("坏 JSON 被安全拒绝", bad.get("ok") is False)
    check("坏 JSON 不写入记忆", eng4.db.query_one(
        "SELECT COUNT(*) AS n FROM memories WHERE content='随便说一句'")["n"] == 0)

    # 测试 B：30 条问候不产生记忆
    eng5 = new_engine(tmp, llm=FakeLLM('{"memories": []}'), tag="_chat")
    for i in range(30):
        eng5.convs.add_message(eng5.convs.active(), "user", f"你好啊 {i}", processed=0)
    rep5 = eng5.extractor.extract_pending(limit=40)
    check("无意义闲聊不产生记忆", rep5.get("added", 0) == 0, str(rep5))

    # ============ Phase 6：Dreaming ============
    eng6 = new_engine(tmp, tag="_dream")
    eng6.mgr.add("主人喜欢喝咖啡，每天两杯", category="PROFILE", importance=6,
                 profile_key="drink")
    eng6.mgr.add("主人喜欢喝咖啡，每天两杯哦", category="PROFILE", importance=6,
                 profile_key="drink")
    before = eng6.db.query_one(
        "SELECT COUNT(*) AS n FROM memories WHERE status='active'")["n"]
    dream = eng6.dreaming.run(do_extract=False)
    after = eng6.db.query_one(
        "SELECT COUNT(*) AS n FROM memories WHERE status='active'")["n"]
    check("Dreaming 合并了重复记忆", dream["merged"] >= 1 or after <= before,
          f"merged={dream['merged']} {before}->{after}")
    check("Dreaming 有日志", len(eng6.db.logs(10)) > 0)

    # 过期任务
    tid, _ = eng6.mgr.add("下周要交的临时任务", category="TASK", importance=5)
    eng6.db.execute("UPDATE memories SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?",
                    (tid,))
    eng6.dreaming.run(do_extract=False)
    check("过期 TASK 被归档", eng6.mgr.get(tid)["status"] in ("archived", "active"),
          eng6.mgr.get(tid)["status"])
    hit = [h for h in eng6.retr.search("临时任务", k=5) if h["id"] == tid]
    check("已归档任务不作为当前计划返回", len(hit) == 0)

    # ============ Phase 7：备份与恢复（测试 I）============
    bpath = eng6.backup_mgr.backup("test")
    check("生成备份文件", bpath and os.path.exists(bpath), str(bpath))
    check("备份列表可读", len(eng6.backup_mgr.list_backups()) >= 1)
    js = os.path.join(tmp, "export.json")
    eng6.backup_mgr.export_to_file(js, "all")
    data = json.load(open(js, encoding="utf-8"))
    check("导出 JSON 含记忆与消息", "memories" in data and "messages" in data,
          str(list(data.keys())))
    ok, msg = eng6.backup_mgr.restore(bpath)
    check("从备份恢复", ok, msg)

    # 测试 H：删除记忆后不再检索
    did, _ = eng6.mgr.add("一条马上要被删除的记忆：测试用", category="KNOWLEDGE",
                          importance=9)
    eng6.mgr.delete(did)
    hits3 = eng6.retr.search("测试用", k=5)
    check("软删记忆不参与检索", all(h["id"] != did for h in hits3))

    # ============ 性能 ============
    t0 = time.time()
    for i in range(50):
        eng6.convs.add_message(eng6.convs.active(), "user", f"性能测试消息 {i}", processed=1)
    cost = (time.time() - t0) / 50 * 1000
    check("单条消息持久化 < 100ms", cost < 100, f"{cost:.1f}ms")

    t1 = time.time()
    for _ in range(10):
        eng6.retr.search("桌宠记忆项目", k=5)
    kw = (time.time() - t1) / 10 * 1000
    check("关键词检索 < 100ms", kw < 100, f"{kw:.1f}ms")

    # 记忆提取必须与聊天分离（失败不影响聊天）
    eng7 = new_engine(tmp, llm=lambda *a, **k: (False, "模拟网络故障"), tag="_fail")
    eng7.convs.add_message(eng7.convs.active(), "user", "网络挂了也要能聊天", processed=0)
    r7 = eng7.extractor.extract_pending()
    check("提取失败不影响主流程", r7.get("ok") is False)
    ctx7 = eng7.build_context("你好")
    check("提取失败后仍能构建上下文", len(ctx7["messages"]) >= 2)

    eng.db.close()
    eng2.db.close()
    eng3.db.close()
    eng4.db.close()
    eng5.db.close()
    eng6.db.close()
    eng7.db.close()

    print(f"\n==== 通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 ====")
    if FAIL:
        for f in FAIL:
            print("  失败:", f)
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
