# 大肥鱼桌宠 🐋

DeepSeek V4 Pro 二创形象「鲸鱼娘·大肥鱼」的透明桌面宠物。

基于三视图素材（正面 / 侧面 / 背面），用 Python + PySide6 实现，无边框透明置顶窗口。

## 功能

- **三视图行走**：左右走用侧面（自动镜像）、向上走用背面、向下走用正面

- **三种模式**：自由散步 / 跟随鼠标 / 原地待着（右键菜单切换）

- **互动**：
  - 左键按住：拖拽（会侧身朝向拖动方向，松手会说话）
  - 单击：蹦跳 + 回嘴（互动台词）+ 弹出 🗨️ 聊天面板
  - 双击：喂食面板（小鱼干 / 蛋糕 / 棒棒糖 / 团子 / 钻石）
  - 右键：完整菜单（模式 / 大小 / 喂食 / 说句话 / 显示/隐藏 / 鼠标穿透 / 置顶 / 开机自启 / 退出；托盘右键是同款菜单，穿透后可从托盘解除）

- **台词系统**：日常随机台词 + 互动回嘴 + 思维链心声（灰色斜体括号气泡，小概率冒出），全部取材自社区 DS 梗

- **细节**：呼吸 / 摇摆 / 蹦跳 / 进食动画、转向交叉淡化、加减速惯性、散步自动休息、说话冷却

- 托盘图标、窗口置顶、鼠标穿透、开机自启、配置记忆（config.json）；穿透 / 置顶状态重启后自动恢复

- ##### AI 对话（新增）

  - 左键单击弹出 🗨️ 图标，点击后弹出聊天输入框
  - 调用 Agnes AI（`agnes-2.5-flash` 模型，OpenAI 兼容接口 `https://apihub.agnes-ai.com/v1`），每句话不超过 25 字，风格贱兮兮但可爱
  - 右键菜单「AI 模型」可切换 `agnes-2.5-flash` / `agnes-3.0-flash` / `agnes-2.5-pro-beta` / `agnes-2.5-pro-alpha`
  - 对话历史保留最近 40 条（自动记忆上下文）
  - API Key 通过右键菜单「设置 Agnes AI Key」输入，保存到 `config.json` 的 `api_key` 字段
  - 聊天期间鱼会暂停移动，但呼吸/摇摆/小动作照常

  ##### 天气查询（新增）

  - 右键菜单「查看天气」→ 调用 `wttr.in` 获取当前城市天气
  - 城市默认从 `config.json` 读取，可手动修改配置文件中的 `"city"` 字段
  - 鱼会气泡播报：「汕头今天 26°，天气多云」

  ##### 系统状态监控（新增）

  - **CPU**：超过 90% 时冒泡提醒
  - **内存**：超过 95% 时冒泡提醒
  - **显卡（NVIDIA）**：温度超过 80°C 时冒泡提醒（`pynvml` 读取）
  - 检测间隔 10 秒，不频繁打扰

  ##### 办公便利贴 + 工作提醒（新增）

  - 单击桌宠 → 头顶弹出便利贴（放大动画弹出、缩小收起），再点一次即可收起
  - **上半 1/3 是今日工作**：每条格式为「时间 + 内容」，不同颜色的半透明标签区分
  - 点击某条 → 切换完成 / 未完成；已完成的文字变半透明，再点一下即重新启动
  - 右键单条 → 修改提醒时间 / 不再提醒 / 标记完成 / 删除
  - **下半是聊天窗**：既能普通聊天（走 Agnes AI），也能直接说
    「提醒我下午两点半有重要会议」→ 自动解析成 `14:30 重要会议` 并录入
  - 也支持**一口气说一串、不带具体时间**：
    「我下午的工作：和IT部门沟通网站事宜；广告对标；拿到物料」
    → 拆成 3 条，时段记为「下午」，默认都在下班时间结束（点一下打勾即完成）
  - **只记真正的工作内容**，闲聊不会被误录（三道判定）：
    1. 「工作」两个字单独出现不算意图，要有清单表头（`我下午的工作：` `任务：` `今日待办：`）
       或明确的待办词（提醒 / 记得 / 待办）
    2. 没有表头时，靠逗号拆分成多条不算清单 —— 避免一句吐槽被拆成三条待办
    3. 反问 / 感叹句（`吗` `呢` `？` `怎么` `为什么` `好累啊`）一律当聊天，
       句中若含业务动词（沟通 / 跟进 / 对账 / 报价…）则豁免
    例：`键盘都是粑粑 那我怎么工作，没工作怎么有钱，没钱怎么买帝王蟹` → 走 AI 聊天，不记录
  - 到点桌宠冒泡提醒；超过设定分钟数仍未处理 → 自动视为完成（默认 30 分钟，
    无具体时间的条目除外，它们等下班回顾时由你打勾）
  - 固定日程提醒（时间、文案、开关均可在 ⚙ 里改）：
    早上开机汇总今日工作 → 12:00 午饭 → 打卡前 5 分钟 → 13:30 上班打卡
    → 14:00 下午待办 → 18:00 下班打卡 → 18:00 下班回顾（问今天都完成了么并列出全部条目，
    可在聊天框回一句「都完成了」一键打勾）
  - 数据存 `work_items.json`（按日期分组，已加入 `.gitignore`）

  ##### 长期记忆（新增）

  - **聊过就不忘**：所有对话存本地 SQLite，重启、关机都不丢；下次打开它还认得你
  - **自动提炼**：累计 10 轮对话（或你说「记住…」「别忘了…」立刻）后台提取值得记的事，
    分五类：核心记忆 / 用户画像 / 事件 / 知识 / 当前任务。普通寒暄不会被记
  - **会主动回忆**：问「你还记得我之前想做的那个项目吗」→ 自动检索相关旧事注入上下文；
    平时闲聊只带核心记忆和画像，不塞一大堆历史（省 token）
  - **越用越懂你**：用户画像（身份、偏好、在做的事）会持续更新，旧结论标记为「已被更新」而非硬删
  - **睡眠整理**：启动 / 退出 / 手动触发——合并重复记忆、同步画像、归档过期任务、
    低价值内容归档，全部写日志可追溯
  - **记忆中心**（右键 → 🧠 长期记忆 → 记忆中心）：概览统计、分类浏览、搜索、
    新建 / 编辑 / 锁定 / 归档 / 删除、备份 / 导出 JSON / 恢复
  - 存储位置：`%APPDATA%\HJCDaFeiYu\database\memory.db`（**不放在程序目录**），
    备份在 `database\backups\`，配置在程序目录 `memory-config.json`
  - 关闭记忆：右键 → 🧠 长期记忆 → 长期记忆开关（关掉即退回纯聊天，不再注入也不再记录）
  - 设计与实现见 `MEMORY_ARCHITECTURE.md`，测试结果见 `MEMORY_TEST_REPORT.md`

  ##### 接口设置（DeepSeek / Agnes / 自定义）

  - 右键 → **⚙ 接口设置**，一个面板搞定服务商、地址、Key、模型
  - 三个预设各自独立保存，切换不串 Key、不丢配置：
    | 服务商 | 默认地址 | 预置模型 |
    |---|---|---|
    | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` / `deepseek-reasoner` |
    | Agnes AI | `https://apihub.agnes-ai.com/v1` | `agnes-2.5-flash` / `agnes-3.0-flash` / `agnes-2.5-pro-alpha` |
    | 自定义 | 自己填（硅基流动 / 阿里百炼 / Ollama / OneAPI…） | 自己填 |
  - **测试连接**：发一条最小请求，把 401 / 402 / 404 / 429 / 超时翻译成中文提示，不用猜
  - **拉取列表**：`GET /models` 直接把可用模型塞进下拉框，手懒也能选
  - 地址容错：不写 `https://` 自动补；误粘 `/v1/chat/completions` 自动截回 `/v1`
  - 模型 404 自动降级到该服务商的默认模型，并把配置改回可用值（下次不再白跑）
  - 配置存在 `config.json` 的 `ai_profiles` 下，旧版单 Key 配置启动时自动迁移

## 接口配置（给新装的人）

```bash
cp config.example.json config.json   # 然后把 key 填进去
```

`config.json` 结构与说明：

```jsonc
{
  "ai_provider": "agnes",            // 当前用哪家：deepseek / agnes / custom
  "ai_profiles": {
    "deepseek": { "key": "", "base": "https://api.deepseek.com/v1", "model": "deepseek-chat" },
    "agnes":    { "key": "", "base": "https://apihub.agnes-ai.com/v1", "model": "agnes-2.5-flash" },
    "custom":   { "key": "", "base": "", "model": "" }
  },
  "city": "广州"
}
```

也可以完全不碰文件：启动后右键 → 接口设置 → 填 Key → 保存。

## 数据隔离（上传 / 分享前必读）

这个项目会读写你的 Key、聊天记录和作息，仓库里**不含任何个人数据**：

| 数据 | 位置 | 是否进仓库 |
|---|---|---|
| API Key / 接口配置 | `config.json` | 否（`.gitignore`） |
| 今日工作 / 提醒 | `work_items.json` | 否 |
| 长期记忆库 | `%APPDATA%\HJCDaFeiYu\database\memory.db` | 否（本就在用户目录） |
| 记忆备份 | `%APPDATA%\HJCDaFeiYu\database\backups\` | 否 |
| 错误日志 | `ai_error.log` | 否 |

提交前自查（自带密钥扫描，能识别 `sk-…`、GitHub Token、AWS Key、私钥头、JSON 明文凭据）：

```bash
python scripts/check_secrets.py             # 只扫「会被提交的文件」
python scripts/check_secrets.py --history   # 连 git 历史一起扫
python scripts/check_secrets.py --install-hook   # 装成 pre-commit，有密钥直接拦下
```

已经装了钩子的话，`git commit` 时发现疑似密钥会中止提交；
确认是误报可 `git commit --no-verify` 跳过。

万一 Key 曾经提交过：**先吊销再清理历史**（`git filter-repo --path config.json --invert-paths`），
不要只删文件——旧 commit 里还在。

## 运行

需要 **Python 3.11+**

```bash
pip install -r requirements.txt
# 或
pip install PySide6
```

然后双击 `启动桌宠.bat`，或：

```bash
python 桌宠.py
```

## 打包成独立 exe（可分享给朋友）

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name 大肥鱼桌宠 --add-data "sprites;sprites" --icon icon.ico 桌宠.py
```

产物在 `dist/大肥鱼桌宠.exe`，对方双击即用，无需安装 Python。
（杀毒软件可能对 PyInstaller 产物误报，加信任即可。）

## 更换形象

把新的三视图（白底）放到程序目录：

1. 正面.png / 侧面.png / 背面.png（原图）
2. 运行 `python preprocess.py` —— 白底抠图 + 统一高度
3. 运行 `python preprocess2.py` —— 边缘去污 + 预乘 alpha 缩放出各尺寸精灵

## 文件说明

| 文件 | 说明 |
|------|------|
| 桌宠.py | 主程序（全部逻辑） |
| ai_settings.py | 接口设置（DeepSeek / Agnes / 自定义预设、配置读写、连接测试、设置面板） |
| work_panel.py | 办公便利贴 + 工作提醒（面板 / 中文时间解析 / 提醒引擎） |
| memory/ | 长期记忆引擎（存储 / 提取 / 检索 / 上下文 / 整理 / 记忆中心） |
| tests/ | 自动化测试（test_memory.py / test_integration.py / test_ai_settings.py） |
| scripts/check_secrets.py | 提交前密钥扫描（可装成 pre-commit 钩子） |
| config.example.json | 配置模板（复制成 config.json 再填 Key） |
| pet_launcher.pyw | 无控制台窗口的启动器 |
| PROJECT_AUDIT.md | 接入前项目审查报告 |
| MEMORY_ARCHITECTURE.md | 记忆引擎架构、数据库、接口说明 |
| MEMORY_TEST_REPORT.md | 测试结果与性能数据 |
| preprocess.py | 白底三视图抠图脚本 |
| preprocess2.py | 精灵边缘去污 + 多尺寸生成脚本 |
| sprites/ | 精灵图（正面/侧面/背面 各尺寸 + 图标） |
| 启动桌宠.bat | 启动脚本（自动选择 venv 或系统 Python） |
| requirements.txt | 依赖 |
| 桌宠.spec | PyInstaller 打包配置（含新依赖收集） |

## 贡献与致谢

- **AI 对话 / 天气查询 / 系统监控 / PyInstaller 打包配置**：由 [Cpanoe](https://github.com/Cpanoe) 通过 [PR#3](https://github.com/1190fasheqi/dafeiyu-pet/pull/3) 贡献（DeepSeek API 聊天、wttr.in 天气、CPU/内存/GPU 监控、桌宠.spec）。
- 合并时维护方修复：
  - 线程安全：DeepSeek 回复由后台线程直接调用 Qt 界面改为经队列转发主线程（`_say_queue`）
  - 配置保护：`config.json` 保持不入仓库（本地配置含 API Key，防止泄露）
- 桌面宠物朝向修复由 [B-A-A-GE](https://github.com/B-A-A-GE) 通过 [PR#1](https://github.com/1190fasheqi/dafeiyu-pet/pull/1) 提交（未合并，当前为维护方修复版）。

## 台词梗来源

台词均取自 DeepSeek / 鲸鱼娘 / 大肥鱼社区梗（D指导去吃饭、吃白饭、梁文锋会议三连、"才不是大肥鱼"、思维链心声等），感谢社区整活。

## 协议

MIT
