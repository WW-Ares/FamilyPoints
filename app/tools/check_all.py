# -*- coding: utf-8 -*-
"""按 AGENTS.md 的收工顺序，把该跑的自检一次跑完。

用法（仓库根目录）：
  python app/tools/check_all.py
  FAMILY_BASE=http://127.0.0.1:8090 python app/tools/check_all.py   # 连 e2e 一起
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(name, cmd):
    print("\n>>> " + name)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(cmd, cwd=ROOT, env=env)
    print("<<< %s 退出码 %d" % (name, r.returncode))
    return r.returncode


def main():
    steps = [
        ("前端语法", ["node", "--check", "app/web/app.js"]),
        ("未定义标识符", [sys.executable, "app/tools/check_undef.py"]),
        ("未打分提醒", [sys.executable, "app/tools/test_unscored_reminder.py"]),
        ("引擎冒烟", [sys.executable, "app/smoke_test.py"]),
        ("接口巡检", [sys.executable, "app/api_test.py"]),
        ("开发文档", [sys.executable, "app/tools/verify_devdoc.py"]),
    ]
    failed = []
    for name, cmd in steps:
        if run(name, cmd) != 0:
            failed.append(name)
    if os.environ.get("FAMILY_BASE"):
        if run("端到端", ["node", "app/tools/e2e_v13.js"]) != 0:
            failed.append("端到端")
    else:
        print("\n[skip] 端到端：没有设置 FAMILY_BASE，避免误打 8080 正式库。")
    print("\n" + "=" * 50)
    if failed:
        print("失败：" + " / ".join(failed))
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
