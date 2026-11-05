"""MemoryEngine：记忆系统门面

桌宠只需要和这个类打交道：
    engine = MemoryEngine(app_dir, api_provider)
    ctx = engine.build_context(user_msg)      # 组装上下文
    engine.record_exchange(user, reply)       # 落库 + 触发后台提取
    engine.shutdown()                         # 退出前整理

后台任务一律异步；任何记忆相关异常都不允许影响正常聊天。
"""

import os
import queue
import re
import threading
import time

from .backup import BackupManager
from .config import load_config
from .context import BASE_SYSTEM, ContextBuilder
from .conversation import ConversationManager
from .db import DEFAULT_DB_PATH, MemoryDB
from .dreaming import DreamingEngine
from .extractor import MemoryExtractor
from .manager import MemoryManager
from .retriever import MemoryRetriever
from .utils import days_since, estimate_tokens, now_iso

# 用户明确要求「记住」时立刻处理
URGENT_RE = re.compile(r"记住|记一下|记下|别忘了|别忘记|以后要|你要记得|记牢")


class MemoryEngine(object):
    def __init__(self, app_dir, api_provider=None, logger=None, db_path=None):
        self.app_dir = app_dir
        self.config_path = os.path.join(app_dir, "memory-config.json")
        self.cfg = load_config(self.config_path)
        self.api_provider = api_provider or (lambda: {})
        self.logger = logger or (lambda m: None)
        self.last_error = ""

        self.db = MemoryDB(db_path or DEFAULT_DB_PATH,
                           retention=int(self.mcfg.get("backup", {}).get("retention_count", 7)))
        self.convs = ConversationManager(self.db)
        self.mgr = MemoryManager(self.db, self.logger)
        self.retr = MemoryRetriever(self.db, self.mgr, lambda: self.cfg["memory"])
        self.extractor = MemoryExtractor(self.db, self.mgr, self.convs, self.llm_call,
                                         lambda: self.cfg["memory"], self.logger)
        self.builder = ContextBuilder(self.db, self.mgr, self.retr, self.convs,
                                      lambda: self.cfg["memory"])
        self.dreaming = DreamingEngine(self.db, self.mgr, self.convs, self.extractor,
                                       lambda: self.cfg["memory"], self.logger)
        self.backup_mgr = BackupManager(self.db, self.mgr, self.convs)

        self.conv_id = None
        self._exchanges = 0
        self._shutting_down = False
        self._q = queue.Queue()
        self._queued = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ 配置
    @property
    def mcfg(self):
        return self.cfg.get("memory", {})

    def enabled(self):
        return bool(self.mcfg.get("enabled", True))

    def set_enabled(self, on):
        self.mcfg["enabled"] = bool(on)
        self.save_config()

    def save_config(self):
        from .config import save_config
        return save_config(self.config_path, self.cfg)

    # ------------------------------------------------------------ LLM
    def llm_call(self, system, user, max_tokens=2000, timeout=150):
        """记忆提取用的独立模型调用（与聊天请求分开，失败不影响聊天）"""
        try:
            import requests
        except Exception as e:
            return False, f"requests 不可用: {e}"
        api = self.api_provider() or {}
        key = (api.get("key") or "").strip()
        base = (api.get("base") or "https://apihub.agnes-ai.com/v1").rstrip("/")
        model = (api.get("model") or "agnes-2.5-flash").strip()
        if not key:
            return False, "未配置 API Key"
        if self._shutting_down:
            timeout = min(timeout, 20)   # 退出时不能卡太久
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                self.last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:200]}"
                return False, self.last_error
            data = resp.json()
            msg = ((data.get("choices") or [{}])[0].get("message") or {})
            text = (msg.get("content") or "").strip()
            if not text:
                # 推理模型把预算吃光时会没有正文，用更小输入重试一次不值得，直接报失败
                self.last_error = "模型返回正文为空"
                return False, self.last_error
            return True, text
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False, self.last_error

    # ------------------------------------------------------------ 上下文
    def build_context(self, user_msg, fallback_history=None, personality=BASE_SYSTEM):
        if not self.enabled():
            return {"system": personality,
                    "messages": ([{"role": "system", "content": personality}]
                                 + list(fallback_history or [])
                                 + [{"role": "user", "content": user_msg}]),
                    "memories": [], "profile": [], "tokens": estimate_tokens(user_msg)}
        try:
            cid = self.conv_id or self.convs.active()
            self.conv_id = cid
            ctx = self.builder.build(user_msg, cid, personality=personality,
                                     fallback_history=fallback_history)
            if ctx.get("memories"):
                self.builder.touch_used([m["id"] for m in ctx["memories"]])
                self.db.log("inject", f"{len(ctx['memories'])} 条记忆 / ~{ctx['tokens']} tokens")
            return ctx
        except Exception as e:
            self.last_error = f"build_context: {e}"
            self.logger(self.last_error)
            return {"system": personality,
                    "messages": ([{"role": "system", "content": personality}]
                                 + list(fallback_history or [])
                                 + [{"role": "user", "content": user_msg}]),
                    "memories": [], "profile": [], "tokens": 0}

    # ------------------------------------------------------------ 落库
    def record_exchange(self, user_msg, assistant_msg):
        """把这一轮对话写进库，并按需触发后台记忆提取"""
        if not self.enabled():
            return None
        try:
            cid = self.conv_id or self.convs.active()
            self.conv_id = cid
            umid = self.convs.add_message(cid, "user", user_msg, processed=0)
            self.convs.add_message(cid, "assistant", assistant_msg, processed=1)
            self._exchanges += 1

            ex = self.mcfg.get("extraction", {})
            if not ex.get("enabled", True):
                return umid
            if URGENT_RE.search(user_msg or ""):
                self._enqueue("extract")
            else:
                trig = int(ex.get("trigger_message_count", 10))
                if self._exchanges >= trig or self.convs.pending_count() >= trig:
                    self._exchanges = 0
                    self._enqueue("extract")
            return umid
        except Exception as e:
            self.last_error = f"record_exchange: {e}"
            self.logger(self.last_error)
            return None

    # ------------------------------------------------------------ 后台队列
    def _enqueue(self, kind):
        with self._lock:
            if kind in self._queued:
                return False
            self._queued.add(kind)
        self._q.put(kind)
        return True

    def _loop(self):
        while not self._stop.is_set():
            try:
                kind = self._q.get(timeout=0.8)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(kind)
            if self._stop.is_set():
                break
            try:
                if kind == "extract":
                    r = self.extractor.extract_pending()
                    if not r.get("ok") and not r.get("skipped"):
                        self.logger(f"记忆提取失败：{r.get('error')}")
                elif kind == "dreaming":
                    rep = self.dreaming.run(do_extract=True)
                    self.logger(f"记忆整理完成：合并{rep['merged']} 归档{rep['archived']}")
                elif kind == "backup":
                    self.db.backup("auto")
            except Exception as e:
                self.last_error = f"{kind}: {e}"
                self.logger(self.last_error)

    # ------------------------------------------------------------ 主动入口
    def request_extraction(self):
        return self._enqueue("extract")

    def run_dreaming(self, wait=False):
        if not self.enabled():
            return None
        if wait:
            return self.dreaming.run(do_extract=True)
        self._enqueue("dreaming")
        return None

    def manual_remember(self, text, category="CORE", importance=9):
        """用户手动喂一条记忆（右键菜单 / 记忆中心都能用）"""
        mid, action = self.mgr.add(text, category=category, importance=importance,
                                   confidence=0.99, source_type="manual")
        if mid and category == "PROFILE":
            self.mgr.upsert_profile("auto_" + str(mid)[:10], text, confidence=0.95,
                                    importance=importance, source_memory_id=mid)
        return mid, action

    # ------------------------------------------------------------ 生命周期
    def startup(self):
        if not self.enabled():
            return
        try:
            dcfg = self.mcfg.get("dreaming", {})
            pending = self.convs.pending_count()
            last = self._last_dreaming_iso()
            need = pending > 0 or days_since(last) > 1
            if dcfg.get("enabled", True) and dcfg.get("run_on_startup", True) and need:
                self._enqueue("dreaming")
            bcfg = self.mcfg.get("backup", {})
            if bcfg.get("enabled", True) and bcfg.get("auto_backup", True):
                self._enqueue("backup")
        except Exception as e:
            self.logger(f"startup: {e}")

    def _last_dreaming_iso(self):
        row = self.db.query_one(
            "SELECT created_at FROM memory_logs WHERE kind='dreaming' "
            "ORDER BY created_at DESC LIMIT 1")
        return (row or {}).get("created_at")

    def shutdown(self, budget_seconds=12):
        """退出前：结束会话 + 同步整理 + 备份（限时，超时留给下次启动）"""
        if not self.enabled():
            return
        t0 = time.time()
        self._shutting_down = True
        self._stop.set()
        try:
            self._worker.join(timeout=3)
        except Exception:
            pass
        try:
            if self.conv_id:
                self.convs.end(self.conv_id)
        except Exception:
            pass
        try:
            dcfg = self.mcfg.get("dreaming", {})
            if dcfg.get("enabled", True) and self.convs.pending_count() > 0:
                if time.time() - t0 < budget_seconds * 0.6:
                    self.dreaming.run(do_extract=True)
        except Exception as e:
            self.logger(f"退出整理失败: {e}")
        try:
            bcfg = self.mcfg.get("backup", {})
            if bcfg.get("enabled", True) and time.time() - t0 < budget_seconds:
                self.db.backup("exit")
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

    # ------------------------------------------------------------ 统计
    def stats(self):
        try:
            s = self.mgr.stats()
            s.update({
                "messages": self.convs.count(),
                "pending": self.convs.pending_count(),
                "db_size": self.db.size_bytes(),
                "db_path": self.db.path,
                "fts": getattr(self.db, "fts_ok", False),
                "last_dreaming": self._last_dreaming_iso() or "",
                "enabled": self.enabled(),
                "exchanges": self._exchanges,
            })
            return s
        except Exception as e:
            return {"error": str(e)}

    def context_tokens(self, user_msg):
        """估算这次会注入多少 Token（记忆中心展示用）"""
        try:
            return self.builder.build(user_msg, self.conv_id)["tokens"]
        except Exception:
            return 0
