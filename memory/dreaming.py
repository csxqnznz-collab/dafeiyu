"""Dreaming Engine：睡眠整理

合并重复、更新画像、清理过期任务、标记冲突、低价值归档。
所有动作只做「标记」不做物理删除，并写日志方便追溯。
"""

import json

from .utils import days_since, new_id, now_iso, sim_score


class DreamingEngine(object):
    def __init__(self, db, manager, convs, extractor, config_getter=None, logger=None):
        self.db = db
        self.mgr = manager
        self.convs = convs
        self.extractor = extractor
        self._cfg = config_getter or (lambda: {})
        self.logger = logger or (lambda m: None)
        self.last_run = None

    def _cfg_dreaming(self):
        return (self._cfg() or {}).get("dreaming", {})

    # ------------------------------------------------------------
    def run(self, do_extract=True):
        cfg = self._cfg_dreaming()
        report = {"started_at": now_iso(), "extract": None, "merged": 0,
                  "profile_updated": 0, "tasks_expired": 0, "conflicts": 0,
                  "archived": 0, "errors": []}

        # 1) 先消化未处理的聊天
        if do_extract:
            try:
                report["extract"] = self.extractor.extract_pending()
            except Exception as e:
                report["errors"].append(f"extract: {e}")

        # 2) 合并高度相似的记忆
        try:
            report["merged"] = self._merge_duplicates(float(cfg.get("merge_threshold", 0.88)))
        except Exception as e:
            report["errors"].append(f"merge: {e}")

        # 3) 画像同步（PROFILE → user_profile）
        try:
            report["profile_updated"] = self._sync_profile()
        except Exception as e:
            report["errors"].append(f"profile: {e}")

        # 4) 过期任务
        try:
            report["tasks_expired"] = self._expire_tasks(int(cfg.get("task_expire_days", 14)))
        except Exception as e:
            report["errors"].append(f"tasks: {e}")

        # 5) 冲突（同 profile_key 多条 active）
        try:
            report["conflicts"] = self._resolve_profile_conflicts()
        except Exception as e:
            report["errors"].append(f"conflicts: {e}")

        # 6) 低价值归档
        try:
            report["archived"] = self._cleanup(int(cfg.get("cleanup_importance", 2)),
                                               int(cfg.get("cleanup_days", 60)))
        except Exception as e:
            report["errors"].append(f"cleanup: {e}")

        report["finished_at"] = now_iso()
        self.last_run = report["finished_at"]
        self.db.execute(
            "INSERT INTO memory_logs(id, kind, detail, created_at) VALUES(?,?,?,?)",
            (new_id(), "dreaming",
             json.dumps({k: v for k, v in report.items() if k != "extract"},
                        ensure_ascii=False), report["finished_at"]))
        return report

    # ------------------------------------------------------------
    def _merge_duplicates(self, threshold):
        """同类别里过于相似的记忆合并：保留内容更全的一条"""
        rows = self.db.query(
            "SELECT * FROM memories WHERE status='active' ORDER BY "
            "category, importance DESC, updated_at DESC LIMIT 600")
        by_cat = {}
        for r in rows:
            by_cat.setdefault(r["category"], []).append(r)

        merged = 0
        for cat, items in by_cat.items():
            kept = []
            for r in items:
                twin = None
                for k in kept:
                    if sim_score(r["content"], k["content"]) >= threshold:
                        twin = k
                        break
                if twin is None:
                    kept.append(r)
                    continue
                # 保留信息量更大的一条
                if len(r["content"]) > len(twin["content"]) * 1.1:
                    self.mgr.update(twin["id"], content=r["content"])
                self.mgr.update(twin["id"],
                                importance=max(int(twin.get("importance") or 5),
                                               int(r.get("importance") or 5)))
                self.mgr.update(r["id"], status="superseded")
                self.mgr.relate(twin["id"], r["id"], "updated_from")
                merged += 1
        return merged

    def _sync_profile(self):
        """把 PROFILE 类记忆同步进 user_profile（按 profile_key 覆盖）"""
        rows = self.db.query(
            "SELECT * FROM memories WHERE category='PROFILE' AND status='active' "
            "ORDER BY importance DESC, updated_at DESC LIMIT 200")
        n = 0
        for r in rows:
            key = r.get("profile_key") or ""
            if not key:
                from .extractor import MemoryExtractor
                key = MemoryExtractor._auto_key(r["content"])
            if self.mgr.upsert_profile(key, r["content"],
                                       confidence=float(r.get("confidence") or 0.8),
                                       importance=int(r.get("importance") or 5),
                                       source_memory_id=r["id"]):
                n += 1
        return n

    def _expire_tasks(self, days):
        """TASK 超过 N 天没动过 → 归档（不再当作当前计划）"""
        rows = self.db.query(
            "SELECT * FROM memories WHERE category='TASK' AND status='active'")
        n = 0
        for r in rows:
            if r.get("locked"):
                continue
            if days_since(r.get("updated_at") or r.get("created_at")) > days:
                self.mgr.update(r["id"], status="archived")
                self.db.execute(
                    "UPDATE memories SET valid_until=? WHERE id=? AND valid_until IS NULL",
                    (now_iso(), r["id"]))
                n += 1
        return n

    def _resolve_profile_conflicts(self):
        """同 profile_key 出现多条 active → 只留最新，其余 superseded"""
        rows = self.db.query(
            "SELECT profile_key, COUNT(*) AS n FROM memories "
            "WHERE category='PROFILE' AND status='active' AND profile_key IS NOT NULL "
            "GROUP BY profile_key HAVING n > 1")
        fixed = 0
        for row in rows:
            key = row["profile_key"]
            dups = self.db.query(
                "SELECT * FROM memories WHERE profile_key=? AND category='PROFILE' "
                "AND status='active' ORDER BY updated_at DESC", (key,))
            for old in dups[1:]:
                self.mgr.update(old["id"], status="superseded")
                self.mgr.relate(dups[0]["id"], old["id"], "contradicts")
                fixed += 1
        return fixed

    def _cleanup(self, max_importance, days):
        """低价值 + 从未被用过 + 很久没更新 → 归档（不删）"""
        rows = self.db.query(
            "SELECT * FROM memories WHERE status='active' AND locked=0 "
            "AND category IN ('KNOWLEDGE','EPISODIC') AND importance<=?", (max_importance,))
        n = 0
        for r in rows:
            if int(r.get("access_count") or 0) > 0:
                continue
            if days_since(r.get("created_at")) > days:
                self.mgr.update(r["id"], status="archived")
                n += 1
        return n
