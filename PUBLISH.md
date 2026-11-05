# 发布到 GitHub

这份文档只做一件事：把这个项目安全、体面地推上 GitHub，并把它「包装」成别人愿意点 star 的样子。
按顺序做，5 分钟能完成。

---

## 0. 先做 60 秒自查

```bash
cd dafeiyu-pet

python scripts/check_secrets.py --history   # 连 git 历史一起扫，应输出「未发现明文密钥」
git status --short                          # 确认没有 config.json / *.db / *.log / 截图
```

> 仓库里**不应该**出现：`config.json`、`work_items.json`、`chatter_state.json`、`*.db`、`ai_error.log`、`.venv/`、调试截图。
> 这些都已写进 `.gitignore`，扫描脚本也会在 `git commit` 时拦下明文 Key（钩子已装）。

如果扫描报错：先删掉那行密钥再提交；**已经提交过的 Key 要先去服务商后台吊销**，只删文件没用（旧 commit 里还在）。

---

## 0. 当前状态（2026-11-05 已发布）

- 远端：`https://github.com/csxqnznz-collab/dafeiyu`（origin 已指向该仓库，main 已推送）
- 本地凭据：PAT 已写入 Windows 凭据管理器，之后 `git push` 不再需要输密码
- `.git/config` 里**没有**保存明文 token（推送时用 `url.insteadOf` 临时注入，未落盘）
- 已推送 5 个自有提交，作者统一为 `csxqnznz-collab`；上游历史（1190fasheqi 等）保持原作者署名

日常改代码后只需要：

```bash
git add -A && git commit -m "xxx" && git push
```

---

## 1. 确认远端仓库

```bash
git remote -v
# origin  https://github.com/csxqnznz-collab/dafeiyu.git
```

### 情况 A：这个仓库就是你自己的

跳到第 2 步，直接推。

### 情况 B：这是别人的仓库（比如上游作者）

**别直接 push**（没有权限）。先在自己账号下建一个空仓库，再把远端指过去：

1. 打开 <https://github.com/new>
2. Repository name 填 `dafeiyu-pet`，**不要**勾 "Add a README / .gitignore / license"（否则推送会冲突）
3. 建好后执行：

```bash
git remote remove origin
git remote add origin https://github.com/<你的用户名>/dafeiyu-pet.git
git branch -M main
```

---

## 2. 推送（三种方式，选一种）

### 方式 A：浏览器登录（最省事，推荐）

```bash
git push -u origin main
```

Git Credential Manager 会弹窗 → 选 **Sign in with your browser** → 授权一次。
成功后再也不用输密码（凭据存在 Windows 凭据管理器里）。

### 方式 B：用 Personal Access Token

1. <https://github.com/settings/tokens> → **Generate new token (classic)**
2. 勾选 `repo`（只推公开仓库也可以只勾 `public_repo`），有效期选 90 天
3. 复制生成的 `ghp_...`，推送时粘到密码位置：

```bash
git push -u origin main
# Username: 你的 GitHub 用户名
# Password: ghp_刚刚复制的 token
```

想让它记住：

```bash
git config --global credential.helper manager
```

> Token 等于密码，别写进任何文件、别提交、别发群里。

### 方式 C：不用命令行

装 [GitHub Desktop](https://desktop.github.com/) → Add local repository → 选 `dafeiyu-pet` 文件夹 → Publish repository。
（如果仓库已经存在，先在 GitHub 网页建空仓库，再在 Desktop 里选 "Push to existing repository"。）

### 推送失败常见原因

| 报错 | 原因 | 处理 |
|---|---|---|
| `could not read Username` | 没登录 / 弹窗被取消 | 重跑 `git push`，这次点浏览器授权 |
| `remote: Permission denied` | 不是仓库成员 | 按「情况 B」换成自己的仓库 |
| `failed to push some refs` | 远端有你本地没有的提交 | `git pull --rebase origin main` 后再推 |
| `src refspec main does not match` | 分支名不是 main | `git branch -M main` 再推 |

---

## 3. 填仓库 About（简介 + 标签）

仓库首页右上角 **⚙ About**，Description 直接复制这一段：

```text
一只会聊天、会记事、会催你干活的透明桌面宠物（Python + PySide6），支持 DeepSeek / Agnes / 任意 OpenAI 兼容接口。A transparent Windows desktop pet that chats, remembers you, and nags you about today's tasks.
```

Website 留空（或填你的个人站）。

**Topics** 逐个粘（每粘一个按回车）：

```text
desktop-pet  pyside6  python  qt  windows  deepseek  openai-api
llm  chatbot  desktop-widget  transparent-window  ai-companion
sqlite  fts5  productivity  anime
```

---

## 4. 打第一个 Release

1. 仓库右侧 **Releases** → **Draft a new release**
2. Tag：`v1.3.0`，Target：`main`
3. Title：`v1.3.0 — 极小模式 + 横向行走 / Tiny size + Side-walk mode`
4. 说明（中英双语，可直接复制）：

```markdown
## 新增 / New

- **极小模式**：大小为「小」的一半（93px），气泡自动加宽加高 —— Tiny size, exactly half of Small (93px), bubble auto-resizes
- **横向行走**：贴着一条水平线左右走，随机走或跑，停下会站立 / 侧身 / 背身 —— Side-walk mode: strolls or sprints along one horizontal line, then stands, turns side-on or faces away
- 配置缺字段自动补默认值，老 config.json 升级不再报错 —— Missing config keys now fall back to defaults
- README 改为中英双语简介 + 展示图 —— Bilingual README with preview images

## 之前版本 / Earlier

- v1.2.0 话唠模式（三档频率 + 记忆驱动）—— Chatter mode
- v1.1.0 多服务商接口设置 / 办公便利贴 / 长期记忆 —— Multi-provider API settings, sticky-note tasks, long-term memory

完整历史见 [CHANGELOG.md](CHANGELOG.md)。
```

需要给不装 Python 的人用，就本地先打包再上传：

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name 大肥鱼桌宠 --add-data "sprites;sprites" --icon icon.ico 桌宠.py
```

把 `dist/大肥鱼桌宠.exe` 拖进 Release 的 Assets（单文件约 40-60MB）。

---

## 5. 以后怎么更新

```bash
git add -A
git commit -m "feat: 一句话说清改了什么"
git push
```

`git commit` 时密钥扫描钩子会自动跑，报红就是有明文 Key，处理后再提交。

---

## 6. 发布前最后一眼

- [ ] `scripts/check_secrets.py --history` 通过
- [ ] 仓库里没有 `config.json` / `*.db` / `*.log` / 个人路径
- [ ] README 首图能正常显示（`docs/preview.png` 已提交）
- [ ] About 描述和 Topics 已填
- [ ] LICENSE 是 MIT（已有）
- [ ] 记得：**Key 只存在本机 `config.json`，永远不进仓库**
