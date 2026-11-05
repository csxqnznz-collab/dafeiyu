# MEMORY_ARCHITECTURE · 大肥鱼长期记忆引擎

版本 1.0.0 · 2026-11-04
核心原则：**Remember intelligently, retrieve selectively, and preserve everything important.**

## 0. 设计摘要 · Design Abstract

本项目采用一种融合分层记忆、动态检索与可塑性记忆（Plastic Memory）的 AI 长期记忆架构，赋予桌面 AI 宠物跨会话、跨重启的持续记忆能力。系统以本地数据库为基础，将记忆划分为核心记忆、用户画像、事件记忆、知识记忆和原始对话五个层级，通过自动提取、语义检索、关联分析、记忆合并与动态更新，让 AI 不仅能够记住用户的身份、偏好、经历和共同互动，还能够像人类大脑一样，根据新的信息和长期互动不断调整、强化、修正或淡化已有记忆。记忆不再是静态存档，而是一个具有形成、巩固、联想、重塑和遗忘能力的动态系统。同时，通过按需检索和上下文动态注入，AI 无需重复读取全部历史对话，就能在有限的 Context Window 中保持记忆的连续性与准确性，实现低 Token 消耗、长期个性化和持续进化的 AI 陪伴体验。

A long-term memory architecture that fuses layered memory, dynamic retrieval and Plastic Memory: five layers (core, profile, episodic, knowledge, raw dialogue) are continuously extracted, retrieved, associated, merged and updated, so memory forms, consolidates, associates, reshapes and fades instead of being a static archive — keeping continuity inside a limited context window at low token cost.

---

## 1. 模块结构

```
memory/
├── __init__.py        只导出 MemoryEngine
├── utils.py           时间（UTC 存/本地显示）、Token 估算、相似度、JSON 容错
├── config.py          默认配置 + 用户配置合并 + 校验
├── db.py              SQLite 连接、Migration、FTS5、热备份、恢复
├── conversation.py    L5 原始聊天：会话与消息持久化
├── manager.py         L1-L4 记忆 CRUD、去重、锁定、归档、画像表
├── extractor.py       Memory Extractor：LLM 提取 + 本地校验
├── retriever.py       混合检索 + 综合评分
├── context.py         Context Builder：动态 Token 预算组装
├── dreaming.py        Dreaming Engine：合并/画像/过期/冲突/清理
├── backup.py          JSON 导出、备份列表、恢复、导入
├── engine.py          门面：后台队列、生命周期、LLM 调用
└── dashboard.py       记忆中心 UI（唯一依赖 PySide6 的文件）
```

除 `dashboard.py` 外全部为纯标准库，可独立测试。

## 2. 数据流

```
用户输入
   ↓
ContextBuilder.build()          ← 核心记忆 + 画像 + 检索到的旧事 + 近史
   ↓                              按 Token 预算裁剪，闲聊少注入、问历史多注入
Agnes /chat/completions（原有适配层不变）
   ↓
_reply_out() → 气泡 / 便利贴
   ↓
MemoryEngine.record_exchange()  ← user 消息 processed=0，assistant 已处理
   ↓
后台队列：累计 10 轮 或 命中「记住/别忘」 → extract
   ↓
MemoryExtractor → LLM → JSON → 本地校验 → MemoryManager.add()（去重/合并）
   ↓
启动 / 退出 / 手动 → DreamingEngine（合并重复、画像同步、过期任务、冲突、归档）
```

**关键约束**：记忆相关的任何异常都在 `try/except` 内消化，聊天主流程永远不受影响。

## 3. 五层记忆

| 层 | category | 存放 | 注入策略 |
|---|---|---|---|
| L1 核心 | `CORE` | 身份、长期约定、明确要求记住的内容 | 每次聊天，≤400 tokens，可锁定 |
| L2 画像 | `PROFILE` | 偏好、背景、目标、工具 | 每次聊天，≤300 tokens；同时写入 `user_profile` 表 |
| L3 事件 | `EPISODIC` | 重要事件、决定、互动 | 按需检索 |
| L4 知识 | `KNOWLEDGE` | 确认的事实、项目、方案 | 按需检索 |
| L5 原始 | `messages` | 完整聊天 | 只用最近若干条，其余可检索 |

## 4. 数据库

位置：`%APPDATA%\HJCDaFeiYu\database\memory.db`（**不在程序目录**）

```sql
conversations(id, title, started_at, ended_at, summary, message_count, status,
              created_at, updated_at)
messages(id, conversation_id→conversations, role, content, timestamp,
         token_estimate, metadata_json, memory_processed, process_attempts)
memories(id, content, category, importance, confidence, status, source_type,
         valid_from, valid_until, created_at, updated_at, last_accessed_at,
         access_count, locked, profile_key, metadata_json)
memory_sources(id, memory_id→memories, message_id→messages, conversation_id, created_at)
memory_relations(id, source_memory_id, target_memory_id, relation_type, created_at)
user_profile(id, profile_key UNIQUE, profile_value, confidence, importance,
             updated_at, source_memory_id)
memory_logs(id, kind, detail, created_at)        -- 迁移/提取/整理/注入日志
memories_fts(content)                            -- FTS5 trigram，触发器同步
```

- `category`：CORE / PROFILE / EPISODIC / KNOWLEDGE / TASK
- `status`：active / archived / superseded / deleted（**默认软删**）
- 时间统一 UTC ISO8601，展示转本地
- Migration：`PRAGMA user_version`，升级前自动备份

## 5. 接口

```python
engine = MemoryEngine(app_dir, api_provider=lambda: {"key", "base", "model"})

# 上下文（注入记忆后的完整 messages）
ctx = engine.build_context("我上次说的项目呢")
# -> {"system", "messages", "memories", "profile", "tokens"}

engine.record_exchange(user_msg, assistant_text)   # 落库 + 触发后台提取
engine.manual_remember("内容", category="CORE", importance=9)
engine.request_extraction() / engine.run_dreaming(wait=True)
engine.stats()                                     # 记忆中心统计
engine.startup() / engine.shutdown(budget_seconds=12)

# 细粒度
engine.mgr.add / update / lock / archive / restore / delete(hard=) / list / profile
engine.retr.search(query, k=5)
engine.backup_mgr.backup() / list_backups() / restore(path) / export_to_file(path)
```

## 6. 检索与评分

四层混合：

1. **关键词**：FTS5 trigram（查询切 3-gram 做 OR）→ 空则 `LIKE` 兜底 → 再空则按重要度取候选
2. **语义近似**：字符二元组 Jaccard（无向量模型时的降级方案）
3. **时间**：识别 `昨天/上周/上个月/最近` 等，命中窗口内加权 +0.08，recency 权重 ×3
4. **分类**：按 category 过滤

```
score = semantic*0.40 + keyword*0.25 + importance*0.20 + recency*0.10 + access*0.05
```

权重可在 `memory-config.json` 调整。硬规则：`superseded` 不出现在结果里；过期 `TASK` 不作为当前计划返回。

## 7. Token 预算

| 段 | 默认 | 动态策略 |
|---|---|---|
| 人格 | 300 | 固定 |
| 核心记忆 | 400 | 固定 |
| 用户画像 | 300 | 固定 |
| 相关记忆 | 800 | 回忆意图→900/6 条；≤12 字闲聊→260/2 条；其余→500/3 条 |
| 最近对话 | 1500 | 从新到旧装填，超预算即停 |

总量 3300。中文按 0.8 token/字、其余按 3.5 字符/token 估算，宁保守不越界。

## 8. 提取与校验

独立请求（与聊天分离），Prompt 沿用任务书 5.3（英文原文），额外要求 PROFILE 返回 `profile_key`。

本地校验逐条过滤：JSON 合法性 → category 白名单 → importance 1-10 → confidence 0-1 → 内容长度 → 来源消息必须存在 → 重要度低于阈值丢弃（CORE 例外）→ 去重合并。**模型输出永不直接执行 SQL。**

触发：累计 10 轮（可配）/ 命中「记住·别忘·记一下」立即 / 退出时 / 启动时补处理 / 手动。

## 9. 安全与容错

- API Key 只在 `config.json`，不写日志、不入库
- 全部参数化查询
- 记忆内容视为不可信数据，只作为 system 里的事实陈述，不作为指令执行
- 提取失败：消息保留，`process_attempts+1`，满 5 次放弃，不产生脏记忆
- 备份用 SQLite Backup API，保留 7 份；恢复前先自动备份当前库

## 10. 未启用 / 预留

- 向量检索（未接 embedding，接口与权重已预留）
- 备份加密
- 多桌宠人格、多用户、多设备同步

## 11. 配置示例

```json
{
  "memory": {
    "enabled": true,
    "extraction": { "enabled": true, "trigger_message_count": 10, "importance_threshold": 4 },
    "context": { "max_tokens": 3300, "core_memory_tokens": 400, "profile_tokens": 300,
                 "retrieval_tokens": 800, "recent_message_tokens": 1500, "dynamic_budget": true },
    "retrieval": { "max_results": 5, "time_search": true,
                   "weights": { "semantic": 0.40, "keyword": 0.25, "importance": 0.20,
                                "recency": 0.10, "access": 0.05 } },
    "dreaming": { "enabled": true, "run_on_startup": true, "merge_threshold": 0.88,
                  "task_expire_days": 14, "cleanup_importance": 2, "cleanup_days": 60 },
    "backup": { "enabled": true, "auto_backup": true, "retention_count": 7 }
  }
}
```

文件位于程序目录 `memory-config.json`（首次运行自动生成）。字段缺失或非法值会被修正为默认值，不会导致崩溃。
