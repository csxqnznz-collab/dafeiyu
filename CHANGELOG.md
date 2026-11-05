# CHANGELOG

## 1.4.0 — 2026-11-05 · 动画库（复刻 dsh-pet 全套透明动画）

### 新增
- **114 段 640×360 VP9-alpha 透明动画**：`dsh-pet/assets/webm/`，24fps，约 10 秒，可首尾循环
- **109 张 220×124 GIF 预览**：`dsh-pet/assets/preview/`，拼音文件名（跨平台不乱码）
- **`catalog.json`**：机器可读索引，含 id / 中文名 / 分类 / 时长 / 帧率 / 体积 / 双格式路径
- **动画库面板**（右键 → 🎬 动画库）：中文名与拼音双搜、十二类筛选、棋盘格透明预览、重播、
  复制 raw 直链、打开所在目录
- **`scripts/build_animations_catalog.py`**：自动配对「中文名 webm」与「拼音名 GIF」
  （先精确匹配、再相似度贪心），支持 `--check` / `--gallery` / `--markdown`
- **`dsh-pet/GALLERY.md`**：按分类的 GIF 画廊，走 raw 直链，GitHub 上直接动

### 技术要点
- VP9 的 alpha 必须用 **libvpx 解码器**解：`av.CodecContext.create("libvpx-vp9", "r")`。
  ffmpeg 自带的 `vp9` 解码器会把 alpha 层丢掉，画面变黑底；PyAV 默认走的就是后者
- 流式解码（`FrameDecoder`）：241 帧 × 640×360×4 ≈ 222MB，不能整段缓存进内存
- PyAV 是可选依赖，没装时 `anim_lib` 自动退回 `QMovie` 播 GIF，功能不中断
- `check_secrets.py` 的 `SKIP_EXT` 补上 `.webm` / `.mov` / `.mp3` 等，避免拿 55MB 二进制当文本扫

### 授权
- 素材来自 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)（MIT 代码 / 素材禁止商用）
- 角色形象「大肥鱼」为 **CC BY-NC-SA 4.0**：署名 · 非商业 · 相同方式共享，详见 `dsh-pet/CREDITS.md`

### 测试
- 新增 `tests/test_anim_lib.py` 37 项；全套 233 项通过

## 1.3.0 — 2026-11-05 · 极小模式 + 横向行走

### 新增
- **极小大小**：`SIZE_LEVELS` 增加「极小」= 0.275（正好是「小」0.55 的一半，身高 93px）
  - 窗口宽度兜底到 168px、气泡区加高到 88px、气泡字号降到 10pt，长句不会被裁成一条
  - 气泡超出可用行数时末尾加省略号，不再糊到角色脸上
  - 换档时脚底位置不变（往上长 / 往下缩），不会突然跳半屏
- **横向行走模式**（`mode: "line"`）：
  - 只沿当前水平线左右移动，走完随机休息 8-18 秒
  - 每段路随机「走路 / 跑步」：跑步 1.9 倍速（`RUN_FACTOR`），摆动更快、颠得更高
  - 停下时随机站立（正面）/ 侧身 / **背身**（背面图），带交叉淡化
  - 拖动松手后就在新的那条线上继续走；屏幕边缘自动折返
- 模式菜单从 3 项变 4 项：自由散步 / 横向行走 / 跟随鼠标 / 原地待着
- `docs/preview.png`、`docs/sizes.png` 展示图；`PUBLISH.md` 发布指南

### 修复
- `load_json` 缺字段时用默认值补齐：老版本的 `config.json` 缺 `passthrough` / 新增的 `chatter_level` 等键会 KeyError 崩溃，现在自动补全
- 配置里写入怪尺寸时自动吸附到最近档位，不会找不到精灵图
- 模式 / 大小切换后会立即写盘，重启保持

### 测试
- 新增 `tests/test_modes.py` 50 项（档位比例、窗口与气泡尺寸、脚底固定、四模式菜单、只动 x 不动 y、朝向与镜像、走跑速度、三种停留姿态、到达休息、持久化、非法模式）
- 全套 196 项通过：40 + 50 + 41 + 15 + 50

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
