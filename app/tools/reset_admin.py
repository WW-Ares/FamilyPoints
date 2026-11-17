# -*- coding: utf-8 -*-
"""在容器里重置管理员密码，不用停机改库。

用法（先把脚本拷进容器）：
  docker cp app/tools/reset_admin.py family-points:/srv/
  docker exec -it family-points python /srv/reset_admin.py --list
  docker exec -it family-points python /srv/reset_admin.py
  docker exec -it family-points python /srv/reset_admin.py --id 1 --password newpass --yes

只重置密码，不删除任何记录；会清掉该成员的所有 session。
"""
import argparse
import getpass
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

import db
from api import auth as A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出管理员和家长")
    ap.add_argument("--id", type=int, help="要重置的成员 id")
    ap.add_argument("--password", help="新密码；不传就交互输入")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    args = ap.parse_args()

    db.init_db()
    rows = db.query("SELECT id, name, username, role, is_admin FROM member"
                    " WHERE active=1 ORDER BY sort, id")
    if args.list:
        for r in rows:
            print("%s  %-8s %-12s role=%s admin=%s" %
                  (r["id"], r["name"], r["username"] or "", r["role"], r["is_admin"]))
        return 0

    target = None
    if args.id:
        target = next((r for r in rows if r["id"] == args.id), None)
    else:
        target = next((r for r in rows if r["is_admin"]), None)
        if not target:
            target = next((r for r in rows if r["role"] == "parent"), None)
    if not target:
        print("找不到可用的管理员/家长账号。")
        return 1
    if target["role"] != "parent":
        print("只能把家长设为管理员。")
        return 1

    pwd = args.password
    if not pwd:
        pwd = getpass.getpass("新密码（%s）：" % target["name"])
        pwd2 = getpass.getpass("再输一次：")
        if pwd != pwd2:
            print("两次不一样。")
            return 1
    try:
        A.check_pwd_rule(pwd, "parent")
    except Exception as e:
        print("密码不合规：%s" % getattr(e, "message", e))
        return 1

    if not args.yes:
        print("把 %s（id=%s）设为管理员并重置密码？输入 YES 继续：" %
              (target["name"], target["id"]))
        if input().strip() != "YES":
            print("取消。")
            return 1

    with db.tx():
        db.execute("UPDATE member SET is_admin=0")
        db.execute("UPDATE member SET is_admin=1, password_hash=? WHERE id=?",
                   (A.hash_password(pwd), target["id"]))
        db.execute("DELETE FROM session WHERE member_id=?", (target["id"],))
        db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
                   " VALUES (?,?,?,?,?)",
                   (target["id"], "admin.reset_cli", "member", target["id"], db.now()))
    print("好了：%s（id=%s）下次用新密码登录，旧 session 已清。" %
          (target["name"], target["id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
