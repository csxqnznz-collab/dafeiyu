"""长期记忆管理：新增、更新、去重、锁定、归档、用户画像

五层记忆用 category 区分：
  CORE / PROFILE / EPISODIC / KNOWLEDGE / TASK
L5 原始聊天记录由 conversation.py 负责。
"""

import json

from .utils import auto_profile_key, new_id, now_iso, sim_score, truncate_tokens

VALID_CATEGORIES = ("CORE", "PROFILE", "EPISODIC", "KNOWLEDGE", "TASK")
VALID_STATUS = ("active", "archived", "superseded", "deleted")

CATEGORY_LABELS = {
    "CORE": "核心记忆",
    "PROFILE": "用户画像",
    "EPISODIC": "事件记忆",
    "KNOWLEDGE": "知识记忆",
    "TASK": "当前任务",
}


class MemoryManager(object):
    def __init__(self, db, logger=None):
        self.db = db
        self.logger = logger or (lambda m: None)

    # ------------------------------------------------------------ 写
    def add(self, content, category="KNOWLEDGE", importance=5, confidence=0.8,
            source_message_ids=None, conversation_id=None, profile_key=None,
            valid_until=None, metadata=None, source_type="conversation",
            dedupe=True, merge_threshold=0.88):
        """新增记忆。返回 (memory_id, action)，action ∈ ADD / MERGED / UPDATED / REJECTED"""
        content = (content or "").strip()
        if len(content) < 2:
            return None, "REJECTED"
        content = content[:600]
        category = category if category in VALID_CATEGORIES else "KNOWLEDGE"
        try:
            importance = max(1, min(10, int(importance)))
        except Exception:
            importance = 5
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = 0.8

        if dedupe:
            dup = self.find_similar(content, category, merge_threshold)
            if dup:
                return self._merge(dup, content, importance, confidence,
                                   source_message_ids, conversation_id), "MERGED"

        # 同 profile_key 的旧值：superseded（保留历史，不硬删）
        if category == "PROFILE" and profile_key:
            old = self.db.query_one(
                "SELECT * FROM memories WHERE profile_key=? AND category='PROFILE' "
                "AND status='active'", (profile_key,))
            if old and sim_score(old["content"], content) < 0.95:
                self.db.execute(
                    "UPDATE memories SET status='superseded', valid_until=?, updated_at=? "
                    "WHERE id=?", (now_iso(), now_iso(), old["id"]))
                self._relate(new_id(), None, old["id"], "contradicts")

        mid = new_id("m_")
        ts = now_iso()
        self.db.execute(
            "INSERT INTO memories(id, content, category, importance, confidence, status, "
            "source_type, valid_from, valid_until, created_at, updated_at, profile_key, "
            "metadata_json) VALUES(?,?,?,?,?, 'active', ?,?,?,?,?,?,?)",
            (mid, content, category, importance, confidence, source_type, ts, valid_until,
             ts, ts, profile_key,
             json.dumps(metadata, ensure_ascii=False) if metadata else None))
        self._link_sources(mid, source_message_ids, conversation_id)
        # 画像类记忆即时同步进 user_profile，记忆中心统计不会失真
        if category == "PROFILE":
            try:
                self.upsert_profile(profile_key or auto_profile_key(content), content,
                                    confidence=confidence, importance=importance,
                                    source_memory_id=mid)
            except Exception:
                pass
        return mid, "ADD"

    def _merge(self, dup, content, importance, confidence, source_message_ids, conversation_id):
        """合并重复记忆：保留信息量更大的一条，重要度取高值"""
        old = dup
        best = old["content"]
        if len(content) > len(best) * 1.15:
            best = content
        self.db.execute(
            "UPDATE memories SET content=?, importance=?, confidence=?, updated_at=? WHERE id=?",
            (truncate_tokens(best, 400),
             max(int(old.get("importance") or 5), importance),
             max(float(old.get("confidence") or 0.8), confidence),
             now_iso(), old["id"]))
        self._link_sources(old["id"], source_message_ids, conversation_id)
        return old["id"]

    def _link_sources(self, memory_id, message_ids, conversation_id=None):
        for mid in (message_ids or []):
            if not mid:
                continue
            exists = self.db.query_one(
                "SELECT 1 AS x FROM memory_sources WHERE memory_id=? AND message_id=?",
                (memory_id, mid))
            if exists:
                continue
            self.db.execute(
                "INSERT INTO memory_sources(id, memory_id, message_id, conversation_id, created_at) "
                "VALUES(?,?,?,?,?)",
                (new_id(), memory_id, mid, conversation_id, now_iso()))

    def _relate(self, rel_id, source_mid, target_mid, relation_type):
        if not (source_mid and target_mid):
            return
        self.db.execute(
            "INSERT INTO memory_relations(id, source_memory_id, target_memory_id, "
            "relation_type, created_at) VALUES(?,?,?,?,?)",
            (rel_id, source_mid, target_mid, relation_type, now_iso()))

    def relate(self, source_mid, target_mid, relation_type="related_to"):
        self._relate(new_id(), source_mid, target_mid, relation_type)

    # ------------------------------------------------------------ 查重
    def find_similar(self, content, category=None, threshold=0.88):
        """同类别里找高度相似的记忆（先用 FTS/LIKE 缩小范围，再算相似度）"""
        sql = "SELECT * FROM memories WHERE status='active'"
        args = []
        if category:
            sql += " AND category=?"
            args.append(category)
        sql += " ORDER BY updated_at DESC LIMIT 400"
        rows = self.db.query(sql, tuple(args))
        best, best_score = None, 0.0
        for r in rows:
            s = sim_score(content, r["content"])
            if s > best_score:
                best, best_score = r, s
        if best is not None and best_score >= threshold:
            return best
        return None

    def exact_exists(self, content):
        row = self.db.query_one(
            "SELECT * FROM memories WHERE content=? AND status='active'", (content.strip(),))
        return row

    # ------------------------------------------------------------ 改
    def update(self, mid, **fields):
        allowed = ("content", "category", "importance", "confidence", "status",
                   "valid_until", "locked", "profile_key", "metadata_json")
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            args.append(v)
        if not sets:
            return False
        sets.append("updated_at=?")
        args.append(now_iso())
        args.append(mid)
        self.db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", tuple(args))
        return True

    def set_status(self, mid, status):
        if status == "deleted":
            return self.delete(mid, hard=False)
        return self.update(mid, status=status)

    def lock(self, mid, on=True):
        return self.update(mid, locked=1 if on else 0)

    def archive(self, mid):
        return self.update(mid, status="archived")

    def restore(self, mid):
        return self.update(mid, status="active")

    def delete(self, mid, hard=False):
        """软删优先；hard=True 时连来源/关系一起清（用户明确要求彻底删除）"""
        if hard:
            self.db.execute("DELETE FROM memory_sources WHERE memory_id=?", (mid,))
            self.db.execute(
                "DELETE FROM memory_relations WHERE source_memory_id=? OR target_memory_id=?",
                (mid, mid))
            self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        else:
            self.update(mid, status="deleted")
        return True

    def touch(self, mid):
        self.db.execute(
            "UPDATE memories SET last_accessed_at=?, access_count=access_count+1 WHERE id=?",
            (now_iso(), mid))

    # ------------------------------------------------------------ 读
    def get(self, mid):
        return self.db.query_one("SELECT * FROM memories WHERE id=?", (mid,))

    def list(self, category=None, status="active", q=None, limit=200, offset=0,
             include_archived=False):
        sql = "SELECT * FROM memories WHERE 1=1"
        args = []
        if status and status != "all":
            sql += " AND status=?"
            args.append(status)
        elif status == "all" and not include_archived:
            sql += " AND status<>'deleted'"
        if category and category != "ALL":
            sql += " AND category=?"
            args.append(category)
        if q:
            sql += " AND content LIKE ?"
            args.append(f"%{q}%")
        sql += " ORDER BY importance DESC, updated_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        return self.db.query(sql, tuple(args))

    def core_memories(self, token_budget=400):
        rows = self.db.query(
            "SELECT * FROM memories WHERE category='CORE' AND status='active' "
            "ORDER BY locked DESC, importance DESC, updated_at DESC LIMIT 30")
        return self._fit_budget(rows, token_budget)

    def by_category(self, category, limit=50):
        return self.db.query(
            "SELECT * FROM memories WHERE category=? AND status='active' "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?", (category, limit))

    @staticmethod
    def _fit_budget(rows, token_budget):
        from .utils import estimate_tokens
        out, used = [], 0
        for r in rows:
            t = estimate_tokens(r.get("content"))
            if used + t > token_budget:
                break
            out.append(r)
            used += t
        return out

    # ------------------------------------------------------------ 用户画像
    def upsert_profile(self, key, value, confidence=0.8, importance=6, source_memory_id=None):
        key = (key or "").strip()[:60]
        value = (value or "").strip()[:300]
        if not key or not value:
            return False
        row = self.db.query_one("SELECT * FROM user_profile WHERE profile_key=?", (key,))
        if row:
            self.db.execute(
                "UPDATE user_profile SET profile_value=?, confidence=?, importance=?, "
                "updated_at=?, source_memory_id=? WHERE profile_key=?",
                (value, max(float(row.get("confidence") or 0), confidence),
                 max(int(row.get("importance") or 5), importance),
                 now_iso(), source_memory_id or row.get("source_memory_id"), key))
        else:
            self.db.execute(
                "INSERT INTO user_profile(id, profile_key, profile_value, confidence, "
                "importance, updated_at, source_memory_id) VALUES(?,?,?,?,?,?,?)",
                (new_id(), key, value, confidence, importance, now_iso(), source_memory_id))
        return True

    def profile(self, token_budget=300):
        rows = self.db.query(
            "SELECT * FROM user_profile ORDER BY importance DESC, updated_at DESC LIMIT 40")
        from .utils import estimate_tokens
        out, used = [], 0
        for r in rows:
            t = estimate_tokens(r["profile_value"]) + 4
            if used + t > token_budget:
                break
            out.append(r)
            used += t
        return out

    def delete_profile(self, key):
        self.db.execute("DELETE FROM user_profile WHERE profile_key=?", (key,))

    # ------------------------------------------------------------ 统计
    def stats(self):
        def one(sql, args=()):
            r = self.db.query_one(sql, args)
            return int((r or {}).get("n") or 0)

        by_cat = {}
        for row in self.db.query(
                "SELECT category, COUNT(*) AS n FROM memories WHERE status='active' "
                "GROUP BY category"):
            by_cat[row["category"]] = int(row["n"])
        return {
            "total_active": one("SELECT COUNT(*) AS n FROM memories WHERE status='active'"),
            "by_category": by_cat,
            "profile_count": one("SELECT COUNT(*) AS n FROM user_profile"),
            "archived": one("SELECT COUNT(*) AS n FROM memories WHERE status='archived'"),
            "superseded": one("SELECT COUNT(*) AS n FROM memories WHERE status='superseded'"),
            "locked": one("SELECT COUNT(*) AS n FROM memories WHERE locked=1 AND status='active'"),
        }
