"""SQLite 存储层：连接、Migration、FTS5 索引、热备份

数据库放在用户数据目录（%APPDATA%/HJCDaFeiYu），禁止放程序目录。
所有 SQL 走参数化查询，不做字符串拼接。
"""

import os
import shutil
import sqlite3
import threading

from .utils import new_id, now_iso

APP_DATA_DIR = os.environ.get("HJCDAFEIYU_DATA") or os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "HJCDaFeiYu")
DB_DIR = os.path.join(APP_DATA_DIR, "database")
BACKUP_DIR = os.path.join(APP_DATA_DIR, "backups")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
DEFAULT_DB_PATH = os.path.join(DB_DIR, "memory.db")

SCHEMA_VERSION = 1

# v1：全部基础表
MIGRATION_1 = [
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        summary TEXT,
        message_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        token_estimate INTEGER DEFAULT 0,
        metadata_json TEXT,
        memory_processed INTEGER DEFAULT 0,
        process_attempts INTEGER DEFAULT 0,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_unprocessed ON messages(memory_processed)",
    """CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        category TEXT NOT NULL,
        importance INTEGER DEFAULT 5,
        confidence REAL DEFAULT 0.8,
        status TEXT DEFAULT 'active',
        source_type TEXT,
        valid_from TEXT,
        valid_until TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_accessed_at TEXT,
        access_count INTEGER DEFAULT 0,
        locked INTEGER DEFAULT 0,
        profile_key TEXT,
        metadata_json TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category, status)",
    "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)",
    """CREATE TABLE IF NOT EXISTS memory_sources (
        id TEXT PRIMARY KEY,
        memory_id TEXT NOT NULL,
        message_id TEXT,
        conversation_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sources_memory ON memory_sources(memory_id)",
    """CREATE TABLE IF NOT EXISTS memory_relations (
        id TEXT PRIMARY KEY,
        source_memory_id TEXT NOT NULL,
        target_memory_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (source_memory_id) REFERENCES memories(id),
        FOREIGN KEY (target_memory_id) REFERENCES memories(id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_profile (
        id TEXT PRIMARY KEY,
        profile_key TEXT NOT NULL UNIQUE,
        profile_value TEXT NOT NULL,
        confidence REAL DEFAULT 0.8,
        importance INTEGER DEFAULT 5,
        updated_at TEXT NOT NULL,
        source_memory_id TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS memory_logs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    )""",
]

FTS_DDL = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, tokenize='trigram')",
    """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        DELETE FROM memories_fts WHERE rowid = old.rowid;
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
        UPDATE memories_fts SET content = new.content WHERE rowid = new.rowid;
    END""",
]


class MemoryDB(object):
    """线程安全的 SQLite 封装（后台线程与 UI 线程共用连接 + 锁）"""

    def __init__(self, path=None, retention=7):
        self.path = path or DEFAULT_DB_PATH
        self.retention = int(retention or 7)
        # 备份与日志跟随数据库所在目录，避免自定义库路径时写错地方
        self.backup_dir = os.path.join(os.path.dirname(self.path) or ".", "backups")
        self.log_dir = os.path.join(os.path.dirname(self.path) or ".", "logs")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        self.fts_ok = False
        self.migrate()

    # ------------------------------------------------------------ 基础
    class _Tx(object):
        def __init__(self, db):
            self.db = db
            self.cur = None

        def __enter__(self):
            self.db.lock.acquire()
            self.cur = self.db.conn.cursor()
            try:
                self.cur.execute("BEGIN")
            except Exception:
                pass
            return self.cur

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type:
                    self.db.conn.rollback()
                else:
                    self.db.conn.commit()
            finally:
                self.db.lock.release()
            return False

    def tx(self):
        return MemoryDB._Tx(self)

    def query(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql, args=()):
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def execute_many(self, sql, seq):
        with self.lock:
            cur = self.conn.executemany(sql, seq)
            self.conn.commit()
            return cur

    # ------------------------------------------------------------ 迁移
    def _user_version(self):
        try:
            return int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        except Exception:
            return 0

    def migrate(self):
        """按 user_version 逐步升级；升级前自动备份"""
        cur_ver = self._user_version()
        if cur_ver >= SCHEMA_VERSION:
            self._setup_fts()
            return
        if cur_ver > 0 and os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            self.backup(tag="pre-migrate")
        with self.lock:
            try:
                if cur_ver < 1:
                    for sql in MIGRATION_1:
                        self.conn.execute(sql)
                self.conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
                self.conn.commit()
                self.log("migrate", f"{cur_ver} -> {SCHEMA_VERSION}")
            except Exception as e:
                self.conn.rollback()
                self.log("migrate_error", str(e))
                raise
        self._setup_fts()

    def _setup_fts(self):
        """FTS5 trigram 索引（不可用时自动降级为 LIKE 检索）"""
        with self.lock:
            try:
                exists = self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='memories_fts'").fetchone()
                if not exists:
                    for sql in FTS_DDL:
                        self.conn.execute(sql)
                    # 回填已有数据
                    self.conn.execute(
                        "INSERT INTO memories_fts(rowid, content) "
                        "SELECT rowid, content FROM memories")
                    self.conn.commit()
                self.fts_ok = True
            except Exception as e:
                self.fts_ok = False
                self.log("fts_unavailable", str(e)[:200])

    # ------------------------------------------------------------ 备份
    def backup(self, tag="auto"):
        """使用 SQLite Backup API（写入中复制也不会损坏）"""
        try:
            bdir = getattr(self, "backup_dir", BACKUP_DIR)
            os.makedirs(bdir, exist_ok=True)
            stamp = now_iso().replace(":", "").replace("-", "")[:15]
            dest = os.path.join(bdir, f"backup-{stamp}-{tag}.db")
            with self.lock:
                target = sqlite3.connect(dest)
                try:
                    self.conn.backup(target)
                finally:
                    target.close()
            self.prune_backups()
            return dest
        except Exception as e:
            self.log("backup_error", str(e)[:200])
            return None

    def prune_backups(self, keep=None):
        try:
            keep = self.retention if keep is None else keep
            bdir = getattr(self, "backup_dir", BACKUP_DIR)
            files = sorted(
                [os.path.join(bdir, f) for f in os.listdir(bdir)
                 if f.startswith("backup-") and f.endswith(".db")],
                key=os.path.getmtime, reverse=True)
            for f in files[keep:]:
                os.remove(f)
        except Exception:
            pass

    def restore(self, backup_path):
        """从备份恢复：先备份当前库，再覆盖，然后重连"""
        if not os.path.exists(backup_path):
            return False, "备份文件不存在"
        try:
            self.backup(tag="pre-restore")
            with self.lock:
                self.conn.close()
            shutil.copyfile(backup_path, self.path)
            self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._setup_fts()
            return True, "已恢复"
        except Exception as e:
            return False, str(e)[:120]

    # ------------------------------------------------------------ 日志
    def log(self, kind, detail=""):
        try:
            self.execute(
                "INSERT INTO memory_logs(id, kind, detail, created_at) VALUES(?,?,?,?)",
                (new_id(), kind, (detail or "")[:1000], now_iso()))
        except Exception:
            pass

    def logs(self, limit=50):
        return self.query(
            "SELECT * FROM memory_logs ORDER BY created_at DESC LIMIT ?", (limit,))

    def size_bytes(self):
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = self.path + suffix
            if os.path.exists(p):
                total += os.path.getsize(p)
        return total

    def close(self):
        with self.lock:
            try:
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass
