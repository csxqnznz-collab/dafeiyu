"""会话与消息持久化

每条消息落库（先持久化，再考虑记忆提取），进程崩溃也不会丢。
"""

from .utils import estimate_tokens, local_str, new_id, now_iso, today_key


class ConversationManager(object):
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------ 会话
    def create(self, title=None):
        cid = new_id("c_")
        ts = now_iso()
        self.db.execute(
            "INSERT INTO conversations(id, title, started_at, created_at, updated_at, status) "
            "VALUES(?,?,?,?,?,'active')",
            (cid, title or f"对话 {local_str(ts, '%m-%d %H:%M')}", ts, ts, ts))
        return cid

    def active(self):
        """当前活动会话：优先取今天最近一个未结束的"""
        row = self.db.query_one(
            "SELECT * FROM conversations WHERE status='active' ORDER BY updated_at DESC LIMIT 1")
        if row and str(row.get("started_at") or "").startswith(self._utc_day_prefix()):
            return row["id"]
        if row:
            return row["id"]
        return self.create()

    @staticmethod
    def _utc_day_prefix():
        # 会话按天切分：本地日期 → UTC 前缀（放宽到当天与前一天，避免时区边界丢会话）
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        return (now - timedelta(hours=8)).strftime("%Y-%m-%d")

    def get(self, cid):
        return self.db.query_one("SELECT * FROM conversations WHERE id=?", (cid,))

    def end(self, cid):
        self.db.execute("UPDATE conversations SET status='closed', ended_at=?, updated_at=? WHERE id=?",
                        (now_iso(), now_iso(), cid))

    def summarize(self, cid, summary):
        self.db.execute("UPDATE conversations SET summary=?, updated_at=? WHERE id=?",
                        ((summary or "")[:2000], now_iso(), cid))

    # ------------------------------------------------------------ 消息
    def add_message(self, cid, role, content, metadata=None, processed=1):
        """processed=0 表示待记忆提取（user 消息需要提取，assistant 默认不提）"""
        mid = new_id("m_")
        ts = now_iso()
        tok = estimate_tokens(content)
        import json as _json
        self.db.execute(
            "INSERT INTO messages(id, conversation_id, role, content, timestamp, "
            "token_estimate, metadata_json, memory_processed) VALUES(?,?,?,?,?,?,?,?)",
            (mid, cid, role, content, ts, tok,
             _json.dumps(metadata, ensure_ascii=False) if metadata else None, processed))
        self.db.execute(
            "UPDATE conversations SET message_count=message_count+1, updated_at=? WHERE id=?",
            (ts, cid))
        return mid

    def recent(self, cid, limit=20):
        rows = self.db.query(
            "SELECT role, content, timestamp FROM messages WHERE conversation_id=? "
            "ORDER BY timestamp DESC, rowid DESC LIMIT ?", (cid, limit))
        return list(reversed(rows))

    def recent_across(self, limit=20):
        rows = self.db.query(
            "SELECT role, content, timestamp, conversation_id FROM messages "
            "ORDER BY timestamp DESC, rowid DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def unprocessed(self, limit=40):
        return self.db.query(
            "SELECT * FROM messages WHERE memory_processed=0 AND role='user' "
            "AND process_attempts < 5 ORDER BY timestamp ASC LIMIT ?", (limit,))

    def mark_processed(self, ids, ok=True):
        if not ids:
            return
        for mid in ids:
            if ok:
                self.db.execute(
                    "UPDATE messages SET memory_processed=1 WHERE id=?", (mid,))
            else:
                self.db.execute(
                    "UPDATE messages SET process_attempts=process_attempts+1 WHERE id=?", (mid,))

    def pending_count(self):
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM messages WHERE memory_processed=0 AND role='user' "
            "AND process_attempts < 5")
        return int((row or {}).get("n") or 0)

    def count(self):
        row = self.db.query_one("SELECT COUNT(*) AS n FROM messages")
        return int((row or {}).get("n") or 0)

    def search(self, q, limit=30):
        like = f"%{q}%"
        return self.db.query(
            "SELECT role, content, timestamp FROM messages WHERE content LIKE ? "
            "ORDER BY timestamp DESC LIMIT ?", (like, limit))

    def day_messages(self, day=None):
        day = day or today_key()
        return self.db.query(
            "SELECT role, content, timestamp FROM messages WHERE date(timestamp)=? "
            "ORDER BY timestamp ASC", (day,))
