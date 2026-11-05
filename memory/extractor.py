"""记忆提取器：把聊天里值得长期记住的信息抽出来

调用独立的 LLM 请求（与聊天请求分开），模型输出必须经本地校验才能入库。
模型输出永远不会直接执行 SQL。
"""

import json
import re

from .manager import VALID_CATEGORIES
from .utils import estimate_tokens, extract_json_block, truncate_tokens

EXTRACT_SYSTEM = """You are a long-term memory extraction engine.

Your task is to identify useful, reliable information from
conversations between a user and an AI companion.

You must distinguish between temporary conversation
and information worth remembering.

MEMORY CATEGORIES:

CORE:
Essential long-term user information and explicit
instructions to remember.

PROFILE:
User preferences, habits, background and long-term goals.

EPISODIC:
Important events, experiences, decisions and interactions.

KNOWLEDGE:
Confirmed facts, projects, technical information and solutions.

TASK:
Ongoing tasks, temporary plans and unfinished commitments.

EXTRACTION RULES:

1. Do not save greetings or ordinary small talk.
2. Do not invent facts.
3. Do not treat speculation as confirmed information.
4. Prefer concise and specific memory statements.
5. Merge duplicate memories.
6. Preserve historical changes when necessary.
7. Do not overwrite important information without evidence.
8. Distinguish user statements from AI-generated assumptions.
9. Respect explicit requests to remember or forget.
10. Avoid extracting sensitive information unless
    explicitly requested by the user and permitted.

IMPORTANCE:

9-10: Critical long-term information.
7-8: Important information.
4-6: Potentially useful information.
1-3: Usually not worth storing.

For category PROFILE, also return "profile_key": a short
stable english snake_case identifier such as job_role,
communication_style, tech_stack, current_project.

Write memory content in the SAME language the user used.

Return valid JSON only, no explanation:

{
  "memories": [
    {
      "content": "Concise memory content",
      "category": "PROFILE",
      "importance": 8,
      "confidence": 0.95,
      "action": "ADD",
      "reason": "Reason for saving",
      "profile_key": "",
      "source_message_ids": []
    }
  ]
}

If no useful memories are found:

{"memories": []}
"""

MAX_CONTENT_LEN = 600

# 模型爱在正文里塞「（具体日期需推断）」这种自言自语，入库前一并清掉
_NOTE_IN_PAREN = re.compile(r"[（(][^（）()]{0,40}?(推断|推测|不确定|需根据|无法确定|待确认)[^（）()]{0,40}?[）)]")
_LEAD_IN = re.compile(r"^(用户|主人|该用户)(说|表示|提到|称)?[:：]?\s*")


def clean_memory_content(text):
    """清洗模型输出：去掉解释性括注、多余空白"""
    s = (text or "").strip()
    s = _NOTE_IN_PAREN.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ，,。;；")
    return s[:MAX_CONTENT_LEN]


class MemoryExtractor(object):
    def __init__(self, db, manager, convs, llm_call, config_getter=None, logger=None):
        self.db = db
        self.mgr = manager
        self.convs = convs
        self.llm_call = llm_call          # (system, user, max_tokens) -> (ok, text)
        self._cfg = config_getter or (lambda: {})
        self.logger = logger or (lambda m: None)

    # ------------------------------------------------------------
    def extract_pending(self, limit=20):
        """处理未提取的 user 消息；返回报告"""
        cfg = (self._cfg() or {}).get("extraction", {})
        threshold = int(cfg.get("importance_threshold", 4))
        max_retries = int(cfg.get("max_retries", 2))

        rows = self.convs.unprocessed(limit=limit)
        if not rows:
            return {"ok": True, "skipped": True, "added": 0, "reason": "没有待处理消息"}

        # 带上上下文（同一会话里紧邻的 assistant 回复），有助于判断
        batch_ids, lines = [], []
        for r in rows:
            batch_ids.append(r["id"])
            lines.append(f"[{r['id']}] user: {truncate_tokens(r['content'], 200)}")

        conv_id = rows[0].get("conversation_id")
        user_prompt = (
            "Conversation excerpt (user messages, with ids):\n\n"
            + "\n".join(lines)
            + "\n\nExtract long-term memories as JSON.")

        ok, text = self.llm_call(EXTRACT_SYSTEM, user_prompt, 4000)
        if not ok:
            self.convs.mark_processed(batch_ids, ok=False)
            self.db.log("extract_fail", str(text)[:300])
            return {"ok": False, "added": 0, "error": str(text)[:200]}

        data = extract_json_block(text)
        if not isinstance(data, dict) or not isinstance(data.get("memories"), list):
            self.convs.mark_processed(batch_ids, ok=False)
            self.db.log("extract_bad_json", (text or "")[:400])
            return {"ok": False, "added": 0, "error": "模型没有返回合法 JSON"}

        valid_ids = set(batch_ids)
        added, merged, rejected = 0, 0, 0
        kept = []
        for item in data.get("memories") or []:
            if not isinstance(item, dict):
                rejected += 1
                continue
            content = clean_memory_content(item.get("content"))
            if not content or len(content) > MAX_CONTENT_LEN:
                rejected += 1
                continue
            cat = (item.get("category") or "").strip().upper()
            if cat not in VALID_CATEGORIES:
                rejected += 1
                continue
            try:
                imp = int(item.get("importance", 5))
            except Exception:
                imp = 5
            imp = max(1, min(10, imp))
            try:
                conf = float(item.get("confidence", 0.8))
            except Exception:
                conf = 0.8
            conf = max(0.0, min(1.0, conf))

            src = [s for s in (item.get("source_message_ids") or []) if s in valid_ids]
            if not src:
                src = batch_ids[:1]          # 模型没给来源时挂到本批首条

            if imp < threshold and cat != "CORE":
                rejected += 1
                continue

            profile_key = (item.get("profile_key") or "").strip()[:60] or None
            mid, action = self.mgr.add(
                content=content, category=cat, importance=imp, confidence=conf,
                source_message_ids=src, conversation_id=conv_id,
                profile_key=profile_key,
                metadata={"reason": (item.get("reason") or "")[:200], "source": "extractor"},
                merge_threshold=float(
                    (self._cfg().get("dreaming") or {}).get("merge_threshold", 0.88)))
            if not mid:
                rejected += 1
                continue
            if action == "MERGED":
                merged += 1
            else:
                added += 1
            kept.append((mid, cat, profile_key, content))

        self.convs.mark_processed(batch_ids, ok=True)
        self.db.log("extract", f"batch={len(batch_ids)} add={added} merge={merged} "
                              f"reject={rejected}")
        # 提取成功后同步画像
        for mid, cat, pkey, content in kept:
            if cat == "PROFILE":
                self.mgr.upsert_profile(pkey or self._auto_key(content), content,
                                        confidence=0.9, importance=7, source_memory_id=mid)
        return {"ok": True, "added": added, "merged": merged, "rejected": rejected,
                "batch": len(batch_ids)}

    @staticmethod
    def _auto_key(content):
        """没给 profile_key 时用内容摘要兜底（保证同一主题能覆盖更新）"""
        s = re.sub(r"[\s\W_]+", "", content or "")
        return ("auto_" + s[:14]) if s else "auto_misc"
