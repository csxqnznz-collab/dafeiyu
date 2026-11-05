"""记忆检索：关键词（FTS5 trigram）+ 时间 + 分类 + 综合评分

不启用向量模型也能工作：语义相似度用字符二元组近似，
FTS5 不可用时自动降级为 LIKE 扫描。
"""

import math
import re

from .utils import days_since, keyword_overlap, sim_score

# 用户明显在「问过去」的说法
RECALL_PAT = re.compile(
    r"还记得|记不记得|记不得|之前|以前|上次|上回|上次说|那次|那天|昨天|前天|上周|"
    r"上个?月|去年|刚才|刚刚|我们聊|我说过|我跟你说|提过|那个项目|那件事|什么时候开始")

# 时间窗关键词 → 天数
TIME_HINTS = [
    (re.compile(r"昨天|昨晚"), 1),
    (re.compile(r"前天"), 2),
    (re.compile(r"这周|本周"), 7),
    (re.compile(r"上周|上个?星期"), 14),
    (re.compile(r"这个?月"), 31),
    (re.compile(r"上个?月"), 62),
    (re.compile(r"今年|去年"), 365),
]


class MemoryRetriever(object):
    def __init__(self, db, manager, config_getter=None):
        self.db = db
        self.mgr = manager
        self._cfg = config_getter or (lambda: {})

    # ------------------------------------------------------------ 对外
    def recall_intent(self, text):
        return bool(RECALL_PAT.search(text or ""))

    def search(self, query, k=5, category=None, include_archived=False):
        """返回 [{**memory, score, _why}]，按综合分降序"""
        cfg = (self._cfg() or {}).get("retrieval", {})
        weights = cfg.get("weights") or {}
        w_sem = float(weights.get("semantic", 0.40))
        w_key = float(weights.get("keyword", 0.25))
        w_imp = float(weights.get("importance", 0.20))
        w_rec = float(weights.get("recency", 0.10))
        w_acc = float(weights.get("access", 0.05))

        query = (query or "").strip()
        statuses = ("active", "archived") if include_archived else ("active",)

        rows = self._candidates(query, category, statuses)
        if not rows:
            return []

        days_hint = self._time_window(query)
        if days_hint:
            w_rec = min(0.45, w_rec * 3)

        scored = []
        for r in rows:
            sem = sim_score(query, r["content"]) if query else 0.0
            key = keyword_overlap(query, r["content"]) if query else 0.0
            imp = float(r.get("importance") or 5) / 10.0
            rec = math.exp(-days_since(r.get("updated_at") or r.get("created_at")) / 30.0)
            acc = min(1.0, float(r.get("access_count") or 0) / 5.0)
            score = (sem * w_sem + key * w_key + imp * w_imp + rec * w_rec + acc * w_acc)
            if days_hint and days_since(r.get("created_at")) <= days_hint:
                score += 0.08
            if r.get("locked"):
                score += 0.02
            r = dict(r)
            r["score"] = round(score, 4)
            r["_why"] = self._why(sem, key, r)
            scored.append(r)

        scored.sort(key=lambda x: x["score"], reverse=True)
        # superseded / 过期 TASK 不作为当前事实返回
        out = []
        for r in scored:
            if r.get("status") == "superseded":
                continue
            if r.get("category") == "TASK" and self._task_expired(r):
                continue
            out.append(r)
        return out[:max(1, int(k))]

    def by_time(self, days=7, limit=10):
        rows = self.db.query(
            "SELECT * FROM memories WHERE status='active' "
            "ORDER BY created_at DESC LIMIT 120")
        out = [r for r in rows if days_since(r.get("created_at")) <= days]
        return out[:limit]

    def by_category(self, category, limit=20, status="active"):
        return self.db.query(
            "SELECT * FROM memories WHERE category=? AND status=? "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (category, status, limit))

    # ------------------------------------------------------------ 内部
    def _candidates(self, query, category, statuses):
        status_sql = "m.status IN (%s)" % ",".join("?" * len(statuses))
        args = list(statuses)
        cat_sql = ""
        if category:
            cat_sql = " AND m.category=?"
            args.append(category)

        rows = []
        if query:
            fts = self._fts_query(query)
            if fts and getattr(self.db, "fts_ok", False):
                try:
                    rows = self.db.query(
                        "SELECT * FROM memories m WHERE m.rowid IN "
                        "(SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?) "
                        f"AND {status_sql}{cat_sql} "
                        "ORDER BY m.importance DESC, m.updated_at DESC LIMIT 120",
                        tuple([fts] + list(args)))
                except Exception:
                    rows = []
            if not rows:
                # 降级：按关键词 LIKE 粗筛
                words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", query)[:6]
                if words:
                    likes = " OR ".join(["m.content LIKE ?"] * len(words))
                    rows = self.db.query(
                        f"SELECT m.* FROM memories m WHERE {status_sql}{cat_sql} "
                        f"AND ({likes}) ORDER BY m.importance DESC LIMIT 120",
                        tuple(args) + tuple(f"%{w}%" for w in words))
                if not rows:
                    rows = self.db.query(
                        f"SELECT m.* FROM memories m WHERE {status_sql}{cat_sql} "
                        "ORDER BY m.importance DESC, m.updated_at DESC LIMIT 120",
                        tuple(args))
        else:
            rows = self.db.query(
                f"SELECT m.* FROM memories m WHERE {status_sql}{cat_sql} "
                "ORDER BY m.importance DESC, m.updated_at DESC LIMIT 60", tuple(args))
        return rows

    @staticmethod
    def _fts_query(query):
        """FTS5 trigram 需要 ≥3 字符，这里把查询切成 3-gram 片段做 OR"""
        s = re.sub(r"[\s\W_]+", "", query or "")
        if len(s) < 3:
            return None
        grams = [s[i:i + 3] for i in range(len(s) - 2)]
        grams = list(dict.fromkeys(grams))[:8]
        return " OR ".join('"%s"' % g.replace('"', "") for g in grams)

    @staticmethod
    def _time_window(query):
        for pat, days in TIME_HINTS:
            if pat.search(query or ""):
                return days
        return None

    @staticmethod
    def _task_expired(r):
        from .utils import parse_iso, utc_now
        vu = parse_iso(r.get("valid_until"))
        if not vu:
            return False
        return vu < utc_now()

    @staticmethod
    def _why(sem, key, r):
        parts = []
        if sem >= 0.5:
            parts.append("语义相近")
        if key >= 0.5:
            parts.append("关键词命中")
        if int(r.get("importance") or 0) >= 8:
            parts.append("高重要性")
        return "/".join(parts) or "相关"
