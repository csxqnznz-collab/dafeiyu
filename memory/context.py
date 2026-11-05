"""上下文构建器：控制 Token 的核心

组装顺序：人格 → 核心记忆 → 用户画像 → 相关长期记忆 → 最近对话 → 当前消息
普通闲聊少注入，问历史时多注入；永远优先保留当前对话。
"""

from .utils import estimate_tokens, truncate_tokens

BASE_SYSTEM = "你是桌面宠物大肥鱼，贱兮兮但可爱，每句话不超过25字，偶尔吐槽主人但别真骂人。"

MEM_HEADER = "【你记得关于主人的事】"
PROFILE_HEADER = "【主人画像】"
RECALL_HEADER = "【与这次话题有关的旧事】"

MEM_RULE = ("以上记忆是你真实记得的内容，可以自然提起，但不要生硬罗列；"
            "记忆里没有的事不要编造。")


class ContextBuilder(object):
    def __init__(self, db, manager, retriever, convs, config_getter=None):
        self.db = db
        self.mgr = manager
        self.retr = retriever
        self.convs = convs
        self._cfg = config_getter or (lambda: {})

    def _ctx_cfg(self):
        return (self._cfg() or {}).get("context", {})

    # ------------------------------------------------------------
    def build(self, user_msg, conversation_id=None, personality=BASE_SYSTEM,
              fallback_history=None):
        """返回 {system, messages, memories, profile, tokens}"""
        cfg = self._ctx_cfg()
        max_total = int(cfg.get("max_tokens", 3300))
        budget_personality = 300
        budget_core = int(cfg.get("core_memory_tokens", 400))
        budget_profile = int(cfg.get("profile_tokens", 300))
        budget_retrieval = int(cfg.get("retrieval_tokens", 800))
        budget_recent = int(cfg.get("recent_message_tokens", 1500))

        dynamic = bool(cfg.get("dynamic_budget", True))
        recall = self.retr.recall_intent(user_msg)
        short_chat = len((user_msg or "").strip()) <= 12

        if dynamic:
            if recall:
                budget_retrieval = max(budget_retrieval, 900)
                k = 6
            elif short_chat:
                budget_retrieval = min(budget_retrieval, 260)
                k = 2
            else:
                budget_retrieval = min(budget_retrieval, 500)
                k = 3
        else:
            k = int((self._cfg().get("retrieval") or {}).get("max_results", 5))

        parts = [truncate_tokens(personality, budget_personality)]

        # L1 核心记忆
        core = self.mgr.core_memories(budget_core)
        if core:
            lines = [MEM_HEADER]
            used = 0
            for r in core:
                t = estimate_tokens(r["content"]) + 2
                if used + t > budget_core:
                    break
                lines.append(f"- {r['content']}")
                used += t
            parts.append("\n".join(lines))

        # L2 画像
        prof = self.mgr.profile(budget_profile)
        if prof:
            lines = [PROFILE_HEADER]
            used = 0
            for r in prof:
                line = f"- {r['profile_key']}: {r['profile_value']}"
                t = estimate_tokens(line) + 2
                if used + t > budget_profile:
                    break
                lines.append(line)
                used += t
            parts.append("\n".join(lines))

        # L3/L4 相关记忆（只有值得检索时才查）
        memories = []
        if budget_retrieval > 0 and (recall or not short_chat):
            memories = self.retr.search(user_msg, k=k)
            if memories:
                lines = [RECALL_HEADER]
                used = 0
                for r in memories:
                    t = estimate_tokens(r["content"]) + 2
                    if used + t > budget_retrieval:
                        break
                    lines.append(f"- {r['content']}")
                    used += t
                if len(lines) > 1:
                    parts.append("\n".join(lines))
                else:
                    memories = []
        if memories and len(parts) > 1:
            parts.append(MEM_RULE)

        system = "\n\n".join([p for p in parts if p])
        system = truncate_tokens(system, max_total - budget_recent - 100)

        # L5 最近对话（从库取；库空时用内存回退）
        recent = []
        try:
            if conversation_id:
                recent = self.convs.recent(conversation_id, limit=24)
            else:
                recent = self.convs.recent_across(limit=24)
        except Exception:
            recent = []

        messages = [{"role": "system", "content": system}]
        used = estimate_tokens(system)
        # 从新到旧装填，超出预算就停（保留最近）
        picked = []
        for r in reversed(recent):
            role = r.get("role") or "user"
            if role not in ("user", "assistant"):
                continue
            t = estimate_tokens(r.get("content"))
            if used + t > max_total - 120:
                break
            picked.append({"role": role, "content": r.get("content") or ""})
            used += t
        picked.reverse()

        if not picked and fallback_history:
            for r in fallback_history[-12:]:
                picked.append({"role": r.get("role", "user"),
                               "content": r.get("content", "")})
                used += estimate_tokens(r.get("content"))

        messages.extend(picked)
        messages.append({"role": "user", "content": user_msg})

        return {
            "system": system,
            "messages": messages,
            "memories": [{"id": r["id"], "content": r["content"],
                          "category": r.get("category"), "score": r.get("score")}
                         for r in memories],
            "profile": prof,
            "tokens": used + estimate_tokens(user_msg),
        }

    def touch_used(self, memory_ids):
        for mid in memory_ids or []:
            try:
                self.mgr.touch(mid)
            except Exception:
                pass
