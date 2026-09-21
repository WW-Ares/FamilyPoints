# -*- coding: utf-8 -*-
"""造一个「只有账号、没有任何业务数据」的库，给 tools/e2e_empty.js 用。

空库巡检要的是「什么都没有的时候会不会崩」：聚合页的除零、空列表取 [0]、
None 参与算术，这些路径在有演示数据的库里根本跑不到，而它们最容易上线才发现。

以前这一步直接拿正式库跑，因为那时正式库恰好是空的。v19 起正式库要屋主
自己设密码，巡检不能碰它（碰到就等于替人设密码），所以单独建一个。

不碰 data/demo 和 data/family.db，整个脚本把 FAMILY_DATA_DIR 指到 data/empty。

    python tools/empty_seed.py
    FAMILY_PORT=8099 FAMILY_DATA_DIR=data/empty python server.py
    FAMILY_BASE=http://127.0.0.1:8099 node tools/e2e_empty.js
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

EMPTY_DIR = os.path.join(APP, "data", "empty")
os.environ["FAMILY_DATA_DIR"] = EMPTY_DIR
os.environ["FAMILY_DB"] = os.path.join(EMPTY_DIR, "family.db")

import db  # noqa: E402
from api.auth import hash_password  # noqa: E402

# 和 tools/demo_seed.py 用同一组密码，这样 e2e 两个脚本能用同一张表。
# v36：统一成 1234（WW 先生点名要的，装完他自己再一个个改）。
# 孩子这条必须是 4 位数字 —— 他的登录页是九宫格数字键盘。
PW = {"爸爸": "1234", "妈妈": "1234", "女儿": "1234", "儿子": "1234"}

# 有业务含义的表。空库的「空」要真的空，这些一张都不许有行。
BIZ_TABLES = ("cycle", "score_entry", "correction", "ledger", "ledger_item", "holding",
              "item_use", "fragment_use", "box_open", "explore", "wish", "wish_pool",
              "wish_pool_entry", "wish_pool_log", "task", "calibration", "holiday", "help_request",
              "overtime_request", "ticket_request", "notification", "cash_request")


def main():
    db.init_db(verbose=True)
    for m in db.query("SELECT * FROM member WHERE active=1 ORDER BY sort, id"):
        db.execute("UPDATE member SET username=?, password_hash=? WHERE id=?",
                   (m["username"] or m["name"], hash_password(PW.get(m["name"], "0000")),
                    m["id"]))
    dad = db.query_one(
        "SELECT id FROM member WHERE role='parent' AND active=1 ORDER BY sort, id LIMIT 1")
    if dad:
        db.execute("UPDATE member SET is_admin=0")
        db.execute("UPDATE member SET is_admin=1 WHERE id=?", (dad["id"],))

    for table in BIZ_TABLES:
        db.execute("DELETE FROM %s" % table)
    print("空库就绪：%s" % os.environ["FAMILY_DB"])
    print("账号：" + "　".join("%s/%s" % (k, v) for k, v in PW.items()) + "　管理员＝爸爸")


if __name__ == "__main__":
    main()
