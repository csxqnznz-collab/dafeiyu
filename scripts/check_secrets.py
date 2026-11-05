"""提交前密钥扫描：防止 API Key / Token 之类混进 GitHub。

用法：
    python scripts/check_secrets.py            # 扫描工作区（跳过 .git/.venv）
    python scripts/check_secrets.py --history  # 额外扫描全部 git 历史 blob（慢）
    python scripts/check_secrets.py --install-hook   # 装成 .git/hooks/pre-commit

退出码 0 = 干净；1 = 发现疑似密钥。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".idea", ".vscode"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".zip", ".exe", ".pyc",
            ".db", ".db-wal", ".db-shm", ".mp4", ".ttf", ".otf"}

# 明确不该出现的硬编码密钥
PATTERNS = [
    ("OpenAI/Agnes 风格 Key", re.compile(r"sk-[A-Za-z0-9_\-]{16,}")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("私钥文件头", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Bearer 硬编码", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{24,}")),
]

# JSON 里 key/token/password 有实际值也算
JSON_SECRET = re.compile(
    r'"(?:api_?key|key|token|secret|password|access_?key)"\s*:\s*"([^"]{12,})"', re.I)

# 这些文件按设计就是空的/示例，允许出现字段名
ALLOW_FILES = {"config.example.json", "check_secrets.py"}

# 测试/文档里用的假 Key 前缀，不算泄露
FAKE_PREFIX = ("sk-test", "sk-fake", "sk-demo", "sk-example", "sk-xxx", "sk-local")


def _git_candidates() -> list[str]:
    """git 眼里「会被提交的文件」：已跟踪 + 未跟踪但没被忽略

    比遍历整个目录更准——config.json / *.db / .venv 天然排除在外。
    """
    try:
        r = subprocess.run(["git", "-C", ROOT, "ls-files", "-co", "--exclude-standard"],
                           capture_output=True, text=True)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        p = os.path.join(ROOT, line.strip())
        if os.path.isfile(p):
            out.append(p)
    return out


def _iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            yield os.path.join(dirpath, fn)


def scan_text(path: str, text: str) -> list[str]:
    rel = os.path.relpath(path, ROOT)
    hits = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            found = m.group(0)
            if found.lower().startswith(FAKE_PREFIX):
                continue
            line = text[:m.start()].count("\n") + 1
            snippet = found[:8] + "…" + found[-4:] if len(found) > 14 else found
            hits.append(f"{rel}:{line}  {name}  {snippet}")
    if path.endswith(".json") and os.path.basename(path) not in ALLOW_FILES:
        for m in JSON_SECRET.finditer(text):
            val = m.group(1)
            if val.lower().startswith(FAKE_PREFIX):
                continue
            line = text[:m.start()].count("\n") + 1
            hits.append(f"{rel}:{line}  JSON 明文凭据  {val[:6]}…（{len(val)} 字符）")
    return hits


def scan_worktree() -> list[str]:
    problems = []
    files = _git_candidates()
    if not files:                      # 不是 git 仓库时退化为全目录扫描
        files = [p for p in _iter_files(ROOT)
                 if os.path.splitext(p)[1].lower() not in SKIP_EXT]

    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        problems.extend(scan_text(path, text))

    # config.json 之类的本地配置绝不能被跟踪
    tracked = subprocess.run(["git", "-C", ROOT, "ls-files"],
                             capture_output=True, text=True).stdout.splitlines()
    for bad in ("config.json", "work_items.json", "memory-config.json"):
        if bad in tracked:
            problems.append(f"[git] {bad} 被跟踪了！执行 `git rm --cached {bad}`")
    for t in tracked:
        if t.startswith(("tests/", "memory/")) and t.endswith(".db"):
            problems.append(f"[git] 数据库文件被跟踪：{t}")
    return problems


def scan_history() -> list[str]:
    revs = subprocess.run(["git", "-C", ROOT, "rev-list", "--all"],
                          capture_output=True, text=True).stdout.split()
    if not revs:
        return []
    problems = []
    seen = set()
    for rev in revs[:200]:
        out = subprocess.run(["git", "-C", ROOT, "grep", "-n", "-I", "-E",
                              r"sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}",
                              rev],
                             capture_output=True, text=True).stdout.splitlines()
        for line in out:
            key = line.split(":", 2)[-1][:60]
            if key in seen:
                continue
            seen.add(key)
            problems.append(f"[history] {line[:160]}")
    return problems


HOOK = """#!/bin/sh
# 由 scripts/check_secrets.py --install-hook 生成
python scripts/check_secrets.py || {
    echo "提交被拦下：疑似密钥。确认无误可 git commit --no-verify"
    exit 1
}
"""


def install_hook() -> int:
    hooks = os.path.join(ROOT, ".git", "hooks")
    if not os.path.isdir(hooks):
        print("找不到 .git/hooks，先 git init")
        return 1
    path = os.path.join(hooks, "pre-commit")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(HOOK)
    try:
        os.chmod(path, 0o755)
    except Exception:
        pass
    print(f"已安装 pre-commit 钩子：{path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true", help="扫描 git 历史")
    ap.add_argument("--install-hook", action="store_true", help="安装 pre-commit 钩子")
    args = ap.parse_args()

    if args.install_hook:
        return install_hook()

    problems = scan_worktree()
    if args.history:
        problems += scan_history()

    if problems:
        print("发现疑似密钥 / 数据泄露：\n")
        for p in problems:
            print("  ✕", p)
        print(f"\n共 {len(problems)} 处。修掉再提交。")
        return 1

    print("✓ 未发现明文密钥；config.json / 数据库均未进仓库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
