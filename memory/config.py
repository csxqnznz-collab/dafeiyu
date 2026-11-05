"""记忆系统配置：默认值 + 用户配置合并 + 校验

用户配置放程序目录 memory-config.json（与已有 config.json 一致，方便手改）。
数据库禁止放程序目录，见 db.py。
"""

import os

from .utils import load_json, save_json

DEFAULTS = {
    "memory": {
        "enabled": True,
        "storage": "local",
        "database": "sqlite",
        "vector_search": {"enabled": False, "provider": "local"},
        "extraction": {
            "enabled": True,
            "trigger_message_count": 10,
            "importance_threshold": 4,
            "auto_extract": True,
            "max_retries": 2,
        },
        "context": {
            "max_tokens": 3300,
            "core_memory_tokens": 400,
            "profile_tokens": 300,
            "retrieval_tokens": 800,
            "recent_message_tokens": 1500,
            "dynamic_budget": True,
        },
        "retrieval": {
            "max_results": 5,
            "keyword_search": True,
            "semantic_search": False,
            "time_search": True,
            "weights": {
                "semantic": 0.40,
                "keyword": 0.25,
                "importance": 0.20,
                "recency": 0.10,
                "access": 0.05,
            },
        },
        "dreaming": {
            "enabled": True,
            "auto_consolidation": True,
            "run_on_startup": True,
            "merge_threshold": 0.88,
            "task_expire_days": 14,
            "cleanup_importance": 2,
            "cleanup_days": 60,
        },
        "backup": {"enabled": True, "auto_backup": True, "retention_count": 7},
    }
}


def _deep_merge(base, override):
    """用户配置覆盖默认值；缺失字段不报错"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except Exception:
        return default
    return max(lo, min(hi, v))


def _sanitize(cfg):
    """校验并修正非法值，保证程序不会因配置写错而崩溃"""
    m = cfg.setdefault("memory", {})
    ex = m.setdefault("extraction", {})
    ex["trigger_message_count"] = int(_clamp(ex.get("trigger_message_count"), 2, 200, 10))
    ex["importance_threshold"] = int(_clamp(ex.get("importance_threshold"), 1, 10, 4))
    ex["max_retries"] = int(_clamp(ex.get("max_retries"), 0, 5, 2))

    ct = m.setdefault("context", {})
    for k, dflt, lo, hi in [
        ("max_tokens", 3300, 600, 32000),
        ("core_memory_tokens", 400, 80, 4000),
        ("profile_tokens", 300, 60, 4000),
        ("retrieval_tokens", 800, 0, 8000),
        ("recent_message_tokens", 1500, 200, 16000),
    ]:
        ct[k] = int(_clamp(ct.get(k), lo, hi, dflt))

    rt = m.setdefault("retrieval", {})
    rt["max_results"] = int(_clamp(rt.get("max_results"), 1, 20, 5))
    w = rt.setdefault("weights", {})
    for k, dflt in [("semantic", 0.40), ("keyword", 0.25), ("importance", 0.20),
                    ("recency", 0.10), ("access", 0.05)]:
        w[k] = _clamp(w.get(k), 0.0, 1.0, dflt)

    dr = m.setdefault("dreaming", {})
    dr["merge_threshold"] = _clamp(dr.get("merge_threshold"), 0.5, 1.0, 0.88)
    dr["task_expire_days"] = int(_clamp(dr.get("task_expire_days"), 1, 365, 14))
    dr["cleanup_importance"] = int(_clamp(dr.get("cleanup_importance"), 1, 5, 2))
    dr["cleanup_days"] = int(_clamp(dr.get("cleanup_days"), 7, 3650, 60))

    bk = m.setdefault("backup", {})
    bk["retention_count"] = int(_clamp(bk.get("retention_count"), 1, 60, 7))
    return cfg


def load_config(path):
    """读取 + 合并 + 校验；文件不存在时落地一份默认配置"""
    raw = load_json(path, None)
    if raw is None:
        cfg = _sanitize(_deep_merge(DEFAULTS, {}))
        try:
            save_json(path, cfg)
        except Exception:
            pass
        return cfg
    return _sanitize(_deep_merge(DEFAULTS, raw))


def save_config(path, cfg):
    try:
        save_json(path, cfg)
        return True
    except Exception:
        return False
