# -*- coding: utf-8 -*-
"""导出 / 快照校验 / 恢复 / 重置管理员 的集成测试。

全部在临时目录里跑，不碰 app/data。
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(APP)
sys.path.insert(0, APP)

A = tempfile.mkdtemp(prefix="fp-exp-a-")
B = tempfile.mkdtemp(prefix="fp-exp-b-")
os.environ["FAMILY_DATA_DIR"] = A
os.environ["FAMILY_DB"] = os.path.join(A, "family.db")

import db
import seed_data
from api import auth as Auth

FAIL = []


def check(name, cond, detail=""):
    print(("  [ok]   " if cond else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    db.init_db()
    # 造一点差异：给女儿加一条星尘流水
    db.execute("INSERT INTO ledger (member_id, ts, day, kind, delta_stardust, note)"
               " VALUES (3, ?, ?, 'adjust', 7, '测试导出')", (db.now(), db.today()))

    print("\n=== JSON 导出 ===")
    d = db.export_json()
    check("format 对", d.get("format") == "family-points-export")
    check("schema 对", d.get("schema_version") == seed_data.SCHEMA_VERSION)
    check("app_version 对", d.get("app_version") == seed_data.APP_VERSION)
    check("没有 session", "session" not in d["tables"])
    check("没有 login_attempt", "login_attempt" not in d["tables"])
    check("没有 meta", "meta" not in d["tables"])
    check("member 没有 password_hash",
          all("password_hash" not in r for r in d["tables"].get("member", [])))
    check("push_target 没有 target/secret",
          all("target" not in r and "secret" not in r
              for r in d["tables"].get("push_target", [])))
    payload = json.dumps(d["tables"], ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    check("checksum 对",
          d.get("content_sha256") == hashlib.sha256(payload.encode("utf-8")).hexdigest())
    check("所有表都有 counts",
          all(d["counts"].get(k) == len(v) for k, v in d["tables"].items()))
    check("ledger 里能看到测试流水",
          any(r.get("note") == "测试导出" for r in d["tables"]["ledger"]))

    print("\n=== 快照校验 ===")
    snap = db.snapshot()
    v = db.verify_snapshot(snap, against_live=True)
    check("integrity ok", v.get("ok"), v)
    check("schema 对", str(v.get("schema_version")) == seed_data.SCHEMA_VERSION, v)
    check("行数和当前库一致", v.get("match") is True, v)

    print("\n=== 恢复到另一个临时库 ===")
    os.makedirs(B, exist_ok=True)
    env = dict(os.environ)
    env.update({"FAMILY_DATA_DIR": B, "FAMILY_DB": os.path.join(B, "family.db"),
                "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run([sys.executable, os.path.join(APP, "tools", "restore_backup.py"),
                        "--db", snap, "--apply", "--yes", "--allow-live"],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(r.stdout.strip())
    check("恢复脚本返回 0", r.returncode == 0, r.stderr[-300:])
    c = sqlite3.connect(os.path.join(B, "family.db"))
    check("恢复后 schema 对",
          c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
          == seed_data.SCHEMA_VERSION)
    check("恢复后成员数对",
          c.execute("SELECT COUNT(*) FROM member").fetchone()[0] == 4)
    check("恢复后能看到测试流水",
          c.execute("SELECT COUNT(*) FROM ledger WHERE note='测试导出'").fetchone()[0] == 1)
    check("恢复前快照已生成",
          any(f.startswith("pre-restore-") for f in os.listdir(os.path.join(B, "snapshots"))))
    c.close()

    print("\n=== 重置管理员 ===")
    r = subprocess.run([sys.executable, os.path.join(APP, "tools", "reset_admin.py"),
                        "--id", "1", "--password", "newpass123", "--yes"],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(r.stdout.strip())
    check("重置脚本返回 0", r.returncode == 0, r.stderr[-300:])
    c = sqlite3.connect(os.path.join(B, "family.db"))
    h = c.execute("SELECT password_hash FROM member WHERE id=1").fetchone()[0]
    check("新密码能对上", Auth.check_password("newpass123", h))
    check("session 已清",
          c.execute("SELECT COUNT(*) FROM session WHERE member_id=1").fetchone()[0] == 0)
    c.close()

    print("\n" + "=" * 50)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for x in FAIL:
            print("  - " + x)
        return 1
    print("导出/恢复测试全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
