"""通用工具：时间、Token 估算、相似度、ID

时间统一存 UTC ISO8601，展示时转本地。
"""

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone


# ---------------------------------------------------------------- 时间
def utc_now():
    return datetime.now(timezone.utc)


def now_iso():
    """存库用：UTC ISO8601"""
    return utc_now().isoformat(timespec="seconds")


def today_key():
    """按本地日期分组（凌晨 4 点前算前一天，避免熬夜算错天）"""
    d = datetime.now()
    if d.hour < 4:
        d = d.replace(hour=12)
        d = d - __import__("datetime").timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def parse_iso(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_str(iso, fmt="%Y-%m-%d %H:%M"):
    """展示用：UTC → 本地时间"""
    dt = parse_iso(iso)
    if not dt:
        return iso or ""
    return dt.astimezone().strftime(fmt)


def days_since(iso):
    dt = parse_iso(iso)
    if not dt:
        return 999.0
    return max(0.0, (utc_now() - dt).total_seconds() / 86400.0)


# ---------------------------------------------------------------- Token 估算
# 无真实 tokenizer 时按字符估：中文约 1 字 ≈ 0.75 token，英文约 4 字符 ≈ 1 token
_CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_tokens(text):
    if not text:
        return 0
    text = str(text)
    cjk = len(_CJK.findall(text))
    rest = len(text) - cjk
    return int(cjk * 0.8 + rest / 3.5) + 1


def truncate_tokens(text, max_tokens):
    """按估算 Token 截断（保守）"""
    if not text or max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    # 逐步收缩，避免逐字循环太慢
    ratio = max_tokens / max(1, estimate_tokens(text))
    cut = max(1, int(len(text) * ratio))
    out = text[:cut]
    while estimate_tokens(out) > max_tokens and len(out) > 1:
        out = out[: int(len(out) * 0.9)]
    return out.rstrip() + "…"


# ---------------------------------------------------------------- 文本相似
def _bigrams(s):
    s = re.sub(r"[\s\W_]+", "", (s or "").lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sim_score(a, b):
    """字符二元组 Jaccard 相似度（无需向量模型，中文可用）"""
    if not a or not b:
        return 0.0
    if a.strip() == b.strip():
        return 1.0
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / float(len(A | B))


def keyword_overlap(query, text):
    """查询词在文本中的覆盖率（用于相关性评分）"""
    q = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", (query or "").lower())
    q = [w for w in q if w]
    if not q:
        return 0.0
    t = (text or "").lower()
    hit = sum(1 for w in q if w in t)
    return hit / float(len(q))


# ---------------------------------------------------------------- 杂项
def new_id(prefix=""):
    raw = os.urandom(8).hex()
    return f"{prefix}{raw}" if prefix else raw


def content_hash(text):
    return hashlib.sha1((text or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def auto_profile_key(content):
    """没给 profile_key 时用内容摘要兜底（保证同一主题能覆盖更新）"""
    s = re.sub(r"[\s\W_]+", "", content or "")
    return ("auto_" + s[:14]) if s else "auto_misc"


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, path)
    except Exception:
        os.remove(tmp)
        raise


def extract_json_block(text):
    """从模型输出里抠出 JSON（兼容 ```json 包裹 / 前后废话）"""
    if not text:
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            pass
    # 退化：找第一个 { 到最后一个 }
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} GB"
