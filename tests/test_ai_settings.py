"""AI 接口设置测试：配置迁移 / 预设 / 面板交互（离屏）

运行： .venv\\Scripts\\python.exe tests\\test_ai_settings.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import ai_settings  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- 1. 旧配置迁移
old = {
    "mode": "still", "size": 0.55,
    "api_key": "sk-test-legacy-1234567890",
    "ai_model": "agnes-3.0-flash",
    "ai_base_url": "https://apihub.agnes-ai.com/v1/",
    "city": "广州",
}
changed = ai_settings.ensure(old)
check("迁移：返回 changed", changed is True)
check("迁移：旧字段被清理",
      not any(k in old for k in ("api_key", "ds_api_key", "ai_base_url", "ai_model")))
check("迁移：服务商判定为 agnes", ai_settings.active_id(old) == "agnes", ai_settings.active_id(old))
p = ai_settings.profile(old)
check("迁移：key 搬到 profiles", p["key"] == "sk-test-legacy-1234567890", p["key"])
check("迁移：base 去了尾斜杠", p["base"] == "https://apihub.agnes-ai.com/v1", p["base"])
check("迁移：model 保留", p["model"] == "agnes-3.0-flash", p["model"])
check("迁移：其他字段保留", old.get("city") == "广州" and old.get("size") == 0.55)
check("迁移：二次调用不再变更", ai_settings.ensure(old) is False)

# 无 base 的老配置 → 落到 agnes
old2 = {"api_key": "sk-test-nobase-000000"}
ai_settings.ensure(old2)
check("迁移：无 base 时默认 agnes", ai_settings.active_id(old2) == "agnes"
      and ai_settings.api_key(old2) == "sk-test-nobase-000000")

# DeepSeek 风格的老配置
old3 = {"api_key": "sk-test-ds-000", "ai_base_url": "https://api.deepseek.com/v1",
        "ai_model": "deepseek-chat"}
ai_settings.ensure(old3)
check("迁移：识别 deepseek", ai_settings.active_id(old3) == "deepseek")
check("迁移：deepseek 模型保留", ai_settings.model(old3) == "deepseek-chat")

# ---------------------------------------------------------------- 2. 多服务商并存
cfg = {}
ai_settings.ensure(cfg)
check("新建：三个预设齐全", set(cfg["ai_profiles"]) == {"deepseek", "agnes", "custom"})
check("新建：默认 agnes", ai_settings.active_id(cfg) == "agnes")
check("新建：base 预填", ai_settings.base_url(cfg) == "https://apihub.agnes-ai.com/v1")
check("新建：key 为空", ai_settings.api_key(cfg) == "")

ai_settings.save_profile(cfg, "deepseek", "sk-test-ds-AAA", "api.deepseek.com/v1", "deepseek-reasoner")
check("保存：切到 deepseek", ai_settings.active_id(cfg) == "deepseek")
check("保存：地址补协议", ai_settings.base_url(cfg) == "https://api.deepseek.com/v1",
      ai_settings.base_url(cfg))
check("保存：模型生效", ai_settings.model(cfg) == "deepseek-reasoner")
check("保存：预设代理没被覆盖", ai_settings.profile(cfg, "agnes")["key"] == "",
      ai_settings.profile(cfg, "agnes")["key"])

ai_settings.save_profile(cfg, "custom", "sk-test-xx", "http://127.0.0.1:11434/v1", "qwen2.5:7b")
check("保存：自定义可用", ai_settings.model(cfg) == "qwen2.5:7b"
      and ai_settings.title(cfg) == "自定义")
check("保存：deepseek key 仍在", ai_settings.profile(cfg, "deepseek")["key"] == "sk-test-ds-AAA")

# 误粘 /chat/completions 自动纠正
check("地址纠错：去掉 /chat/completions",
      ai_settings._norm_base("https://api.deepseek.com/v1/chat/completions")
      == "https://api.deepseek.com/v1")
check("地址纠错：补 https", ai_settings._norm_base("api.deepseek.com") == "https://api.deepseek.com")

# 模型列表：自定义里有当前模型
check("模型列表含当前值", "qwen2.5:7b" in ai_settings.models(cfg))
check("mask 打码", ai_settings.mask("sk-test-1234567890abcd").startswith("sk-tes"))

# ---------------------------------------------------------------- 3. 面板（离屏）
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from ai_settings import AISettingsDialog

    saved = {"n": 0}
    dlg = AISettingsDialog(cfg, on_saved=lambda: saved.__setitem__("n", saved["n"] + 1))
    check("面板：无边框", bool(dlg.windowFlags() & dlg.windowFlags().__class__(0x800)))
    check("面板：默认停在当前服务商", dlg.pid == "custom", dlg.pid)
    check("面板：地址回填", dlg.base_edit.text() == "http://127.0.0.1:11434/v1", dlg.base_edit.text())
    check("面板：模型回填", dlg.model_combo.currentText() == "qwen2.5:7b")

    # 切换服务商 → 字段跟着换，且不串 key
    dlg._switch("deepseek")
    check("面板：切到 deepseek 换了地址",
          dlg.base_edit.text() == "https://api.deepseek.com/v1", dlg.base_edit.text())
    check("面板：切到 deepseek 换了 key", dlg.key_edit.text() == "sk-test-ds-AAA", dlg.key_edit.text())
    check("面板：按钮互斥选中", dlg.btns["deepseek"].isChecked()
          and not dlg.btns["custom"].isChecked())

    # 切回去，刚才 custom 的草稿还在
    dlg._switch("custom")
    check("面板：切回保留草稿", dlg.model_combo.currentText() == "qwen2.5:7b")

    # 校验：空地址 / 空模型
    dlg.base_edit.setText("")
    dlg._save()
    check("校验：空地址拦截", "不能为空" in dlg.status.text(), dlg.status.text())
    dlg.base_edit.setText("http://127.0.0.1:11434/v1")
    dlg.model_combo.setCurrentText("")
    dlg._save()
    check("校验：空模型拦截", "模型" in dlg.status.text(), dlg.status.text())

    # 正常保存
    dlg.model_combo.setCurrentText("qwen2.5:7b")
    dlg.key_edit.setText("sk-test-new-custom")
    dlg._save()
    check("保存：回调触发", saved["n"] == 1)
    check("保存：写回配置", ai_settings.profile(cfg, "custom")["key"] == "sk-test-new-custom")

    # 眼睛开关
    dlg2 = AISettingsDialog(cfg)
    mode0 = dlg2.key_edit.echoMode()
    dlg2._toggle_eye()
    check("面板：明文/密文切换", dlg2.key_edit.echoMode() != mode0)
    dlg2.deleteLater()

    # 深色/浅色不影响：只要不抛异常
    dlg.deleteLater()
except Exception as e:
    import traceback
    traceback.print_exc()
    check("面板：实例化", False, repr(e))

# ---------------------------------------------------------------- 4. 网络函数（无网也不许崩）
ok, msg = ai_settings.test_connection("", "", "")
check("测试连接：空参数有中文提示", (not ok) and "空" in msg, msg)
try:
    ai_settings.fetch_models("", "")
    fetched = False
except Exception as e:
    fetched = "接口地址" in str(e)
check("拉模型：空地址报错可读", fetched)

print("\n" + "=" * 52)
print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
if FAIL:
    print("失败：" + ", ".join(FAIL))
    sys.exit(1)
