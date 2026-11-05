# CHANGELOG

## 1.2.0 — 2026-11-05 · 话唠模式

桌宠会按记忆主动找你说话，分三档频率。

### 新增
- `chatter.py`：话唠引擎
  - 三档频率：1 级 3 小时 5-10 条、2 级 2 小时 10-20 条、3 级 1 小时 20-30 条；
    间隔按「窗口 / 条数」反算随机，滚动窗口卡上限，不会刷屏
  - 素材门槛：最近聊天 / 长期记忆 / 用户画像 / 今日待办，一条素材都没有就跳过
  - 八种情绪（追问 / 抱怨 / 伤心 / 开心 / 无聊 / 担忧 / 思念 / 兴奋），按素材类型加权
  - 台词优先 AI 按素材现写（一次生成 3 句缓存复用），失败或无 Key 时用本地模板填关键词
  - 免打扰（默认 23:00-08:00）、你聊天后 3 分钟内不插嘴、最近 12 句不重复
  - 状态存 `chatter_state.json`（已 gitignore），菜单显示今日条数
- 右键菜单「🗣 话唠模式」：关闭 / 1 级 / 2 级 / 3 级 / 今天念叨 N 句 / 现在说一句
- 配置：`chatter_level`(0-3)、`chatter_quiet`（免打扰时段）
- 测试：`tests/test_chatter.py` 50 项（频率分布、窗口上限、免打扰、素材门槛、台词清洗与缓存、持久化、档位开关）

### 修改
- `桌宠.py` 初始化 `ChatterBox` 并接到气泡；`_call_ds` 记录用户活跃时间用于「不插嘴」
- `work_panel.py` 未配置 Key 的提示改为指向「⚙ 接口设置」

## 1.1.0 — 2026-11-05 · 多服务商接口设置

接口从写死 Agnes 改为 DeepSeek / Agnes / 自定义三家可选，并补数据隔离。

### 新增
- `ai_settings.py`：三预设、`ai_profiles` 配置结构、连接测试、`/models` 拉取、设置面板
- `config.example.json`、`scripts/check_secrets.py`（含 pre-commit 钩子）
- 测试：`tests/test_ai_settings.py` 40 项

### 修改
- `桌宠.py`：`_api_key/_ai_base_url/_ai_model` 走 ai_settings，模型菜单动态化，
  模型 404 自动降级到该服务商默认模型并回写配置
- 旧版单 Key 配置启动时自动迁移；配置结构不再有明文 `api_key` 顶层字段

### 安全
- `config.json` / 数据库 / 日志 / 截图全部 gitignore；历史扫描确认无密钥
- `启动桌宠.bat` 改 ASCII（原来是乱码的中文文件名）；`PROJECT_AUDIT.md` 去掉绝对用户路径

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
