"""备份与导出：JSON 全量导出、SQLite 热备份、备份列表与恢复

备份用 SQLite Backup API，写入过程中复制也不会产生损坏文件。
"""

import json
import os

from .db import BACKUP_DIR
from .utils import now_iso


class BackupManager(object):
    def __init__(self, db, manager, convs):
        self.db = db
        self.mgr = manager
        self.convs = convs

    # ------------------------------------------------------------ 导出
    def export_dict(self, what="all"):
        out = {"exported_at": now_iso(), "schema_version": 1}
        if what in ("all", "memories"):
            out["memories"] = self.db.query(
                "SELECT * FROM memories ORDER BY created_at")
            out["user_profile"] = self.db.query(
                "SELECT * FROM user_profile ORDER BY importance DESC")
            out["memory_relations"] = self.db.query("SELECT * FROM memory_relations")
        if what in ("all", "messages"):
            out["conversations"] = self.db.query(
                "SELECT * FROM conversations ORDER BY started_at")
            out["messages"] = self.db.query(
                "SELECT * FROM messages ORDER BY timestamp")
        return out

    def export_to_file(self, path, what="all"):
        data = self.export_dict(what)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    # ------------------------------------------------------------ 备份
    def backup(self, tag="manual"):
        return self.db.backup(tag=tag)

    def list_backups(self):
        bdir = getattr(self.db, "backup_dir", BACKUP_DIR)
        try:
            files = [os.path.join(bdir, f) for f in os.listdir(bdir)
                     if f.startswith("backup-") and f.endswith(".db")]
        except Exception:
            return []
        out = []
        for f in files:
            out.append({"path": f, "name": os.path.basename(f),
                        "size": os.path.getsize(f), "mtime": os.path.getmtime(f)})
        out.sort(key=lambda x: x["mtime"], reverse=True)
        return out

    def restore(self, path):
        return self.db.restore(path)

    def import_json(self, path):
        """从 JSON 导出文件恢复记忆（不覆盖已有，按内容去重）"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return 0, f"读取失败: {e}"
        n = 0
        for m in data.get("memories") or []:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            mid, _ = self.mgr.add(
                content=content,
                category=m.get("category") or "KNOWLEDGE",
                importance=m.get("importance") or 5,
                confidence=m.get("confidence") or 0.8,
                profile_key=m.get("profile_key"),
                source_type="import")
            if mid:
                n += 1
        return n, "ok"
