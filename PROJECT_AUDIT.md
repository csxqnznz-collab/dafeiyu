# PROJECT_AUDIT · 大肥鱼桌宠记忆系统接入审查

审查时间：2026-11-04
审查对象：`dafeiyu-pet/`（项目根目录）
结论：**已按 Python 技术分支接入，未重建项目，原有 UI / 动画 / Agnes 接入全部保留。**

---

## 1. 现有项目结构

```
dafeiyu-pet/
├── 桌宠.py            1253 行  主程序：窗口、动画、气泡、托盘、菜单、Agnes 对话
├── work_panel.py      1249 行  办公便利贴：工作条目存储、中文时间解析、提醒引擎、面板 UI
├── config.json                 运行时配置（API Key、模型、位置、天气城市…）
├── work_items.json             便利贴数据（按日期分组）
├── sprites/                    三视图精灵图
├── pet_launcher.pyw            无窗口启动器
├── requirements.txt            PySide6 / requests / psutil / pynvml
└── 启动桌宠.bat
```

## 2. 技术栈（实测）

| 项 | 实际值 |
|---|---|
| 语言 | Python 3.13.14（项目内 `.venv`） |
| GUI | PySide6 6.12.0 |
| 网络 | requests |
| 本地存储 | JSON 文件（无数据库） |
| 数据库能力 | sqlite3 + SQLite **3.53.1**，**FTS5 + trigram 可用** |
| 模型 | Agnes AI，OpenAI 兼容，`https://apihub.agnes-ai.com/v1` |

> 任务书假定 Electron / Tauri，本项目为 **Python 桌面应用**，因此按任务书 2.2 的 Python 分支实施：
> `sqlite3` + 标准库 + 现有线程机制，未引入 Pydantic / sqlite-vec / Chroma。

## 3. 聊天调用流程（接入前）

```
单击桌宠 / 便利贴输入框
   ↓
PetWindow._call_ds(user_msg)                    # 桌宠.py:530
   ↓  messages = [system=AI_SYSTEM] + self.chat_history[-40:]
   ↓  threading.Thread(worker)  →  requests.post(/chat/completions)
   ↓  处理推理模型空正文（retry max_tokens=4000）、模型 404 自动降级
   ↓
_reply_out(bubble, full) → 气泡 或 便利贴聊天区
   ↓
chat_history.append(...)                        # 仅内存，进程退出即丢
```

关键事实：
- 上下文只有**内存里的 40 条**，重启即失忆 —— 这是"每次打开都重新认识你"的根因。
- `AI_SYSTEM` 是固定人格提示，**没有**用户画像/记忆注入位。
- Agnes 是推理模型，`reasoning_content` 与 `content` 分开返回，正文可能为空（已在上一轮修复）。

## 4. 存储现状

| 数据 | 位置 | 问题 |
|---|---|---|
| API Key | `config.json`（程序目录） | 已加 `.gitignore` |
| 便利贴 | `work_items.json`（程序目录） | 明文 JSON，够用 |
| 聊天记录 | **无** | 完全丢失 |
| 长期记忆 | **无** | — |

## 5. 需要修改的文件

| 文件 | 改动 |
|---|---|
| `桌宠.py` | ① 初始化 `MemoryEngine`；② `_call_ds` 改用 Context Builder 组装消息；③ 回复成功后 `record_exchange` 落库；④ 退出时 `shutdown()` 整理；⑤ 菜单加「🧠 长期记忆」 |
| `memory/`（新增） | 记忆引擎全部逻辑，见 `MEMORY_ARCHITECTURE.md` |
| `README.md` | 补记忆系统使用说明 |
| `.gitignore` | 忽略 `memory-config.json` |

**未修改**：动画、绘制、精灵、喂食、天气、系统监控、便利贴内部逻辑、Agnes 请求参数与降级策略。

## 6. 兼容性风险与处置

| 风险 | 处置 |
|---|---|
| 推理模型提取时正文为空 | 提取请求 `max_tokens=4000`；正文空视为失败，消息保留待重试（最多 5 次），不写脏数据 |
| SQLite FTS5 缺失（打包环境） | 启动时探测，不可用自动降级为 `LIKE` 扫描，`stats()["fts"]` 可查 |
| 中文分词 | FTS5 用 `trigram` tokenizer；查询侧把句子切成 3-gram 做 OR，兼容中文短查询 |
| 数据库锁 / 多线程 | 单连接 + `RLock` + WAL，后台线程与 UI 线程共用 |
| 退出时整理卡死 | `shutdown(budget_seconds=12)`，退出模式下降级超时为 20s，超时任务留待下次启动 |
| 记忆模块异常拖垮聊天 | 所有接入点 `try/except`，失败退回纯聊天；后台线程独立 |
| 数据库被误放程序目录 | 强制落在 `%APPDATA%\HJCDaFeiYu\database\memory.db` |

## 7. 实施路径（实际执行）

1. Phase 1 持久化：SQLite + Migration + 消息落库 → 重启可读回
2. Phase 2 记忆管理：五类记忆 CRUD、去重、锁定、归档、来源追踪
3. Phase 3 自动提取：独立 LLM 请求 + 本地 JSON 校验 + 异步队列
4. Phase 4 检索：FTS5 trigram + LIKE 兜底 + 时间窗 + 综合评分
5. Phase 5 上下文：动态 Token 预算，闲聊少注入、回忆多注入
6. Phase 6 Dreaming：合并重复、同步画像、过期任务、冲突处理、低价值归档
7. Phase 7 记忆中心：概览 / 分类 / 搜索 / 编辑 / 备份恢复
8. Phase 8 测试：单测 41 项 + 集成 15 项，全部通过

## 8. 未实现（如实说明）

- **向量检索**：未接入 embedding 模型（Agnes 未提供 embedding 接口）。语义相似度用字符二元组 Jaccard 近似，能覆盖"模糊回忆"但精度不如真向量；接口已预留（`retriever.search` 的 semantic 权重可配置）。
- **备份加密**：未实现，只有本地明文备份 + JSON 导出。
- **多用户/多设备同步**：未实现，明确不做。
