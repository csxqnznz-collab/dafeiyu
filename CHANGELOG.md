# CHANGELOG

## 1.0.0 — 2026-11-04 · 长期记忆系统

新增独立的 `memory/` 包（Companion Memory Engine），桌宠获得跨会话、跨重启的长期记忆。

### 新增
- **Phase 1 持久化**：SQLite（`%APPDATA%\HJCDaFeiYu\database\memory.db`）、`PRAGMA user_version` 迁移、消息落库、会话管理、SQLite Backup API 热备份与恢复
- **Phase 2 记忆管理**：五类记忆（CORE/PROFILE/EPISODIC/KNOWLEDGE/TASK）CRUD、相似度去重合并、锁定、归档、软删/彻底删除、来源追踪（`memory_sources`）、关系（`memory_relations`）、用户画像表
- **Phase 3 自动提取**：独立 LLM 请求 + 任务书提取 Prompt、本地 JSON 校验（category/importance/confidence/长度/来源 ID）、异步队列、失败重试、阈值过滤、内容清洗
- **Phase 4 检索**：FTS5 trigram + LIKE 降级 + 时间窗识别 + 分类过滤，综合评分（语义 0.40 / 关键词 0.25 / 重要度 0.20 / 时效 0.10 / 访问 0.05，可配）
- **Phase 5 上下文**：Context Builder 按动态 Token 预算组装（人格 / 核心记忆 / 画像 / 相关旧事 / 近史），闲聊少注入、问历史多注入
- **Phase 6 Dreaming**：合并重复、画像同步、过期 TASK 归档、画像冲突处理、低价值归档、日志留痕；启动、退出、手动三处触发
- **Phase 7 记忆中心**：概览统计、分类导航、搜索、新建/编辑/删除/锁定/归档、备份/导出/恢复、打开数据目录
- **配置**：`memory-config.json` 自动生成并校验，非法值自动修正
- **文档**：`PROJECT_AUDIT.md`、`MEMORY_ARCHITECTURE.md`、`MEMORY_TEST_REPORT.md`
- **测试**：`tests/test_memory.py`（41 项）、`tests/test_integration.py`（15 项）

### 修改
- `桌宠.py`
  - 初始化 `MemoryEngine`，`QTimer` 延迟触发启动检查
  - `_call_ds` 改用 `build_context()` 组装消息（原逻辑保留为失败回退）
  - 回复成功后 `record_exchange()` 落库并按需触发提取
  - `quit_app` 增加 `memory.shutdown()`（限时整理 + 备份）
  - 右键菜单新增「🧠 长期记忆」：记忆中心 / 让大肥鱼记住 / 立即整理 / 开关
- `README.md` 补记忆系统说明
- `.gitignore` 忽略 `memory-config.json`

### 修复（开发中发现）
- `prune_backups(keep=None)` 会误删刚生成的备份文件
- 备份与日志目录固定为全局路径，改为跟随数据库目录
- 手动添加 PROFILE 记忆时未同步 `user_profile`，导致记忆中心画像数失真

### 未实现（如实说明）
- 向量检索（Agnes 无 embedding 接口，语义相似度用字符二元组近似，接口已预留）
- 备份加密、多用户、多设备同步
