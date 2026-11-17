# -*- coding: utf-8 -*-
"""周期任务模板：到日子生成一次，暂停不发，重启不重复。"""
import os
import sys
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

TEST_DIR = tempfile.mkdtemp(prefix="fp-tpl-")
os.environ["FAMILY_DATA_DIR"] = TEST_DIR
os.environ["FAMILY_DB"] = os.path.join(TEST_DIR, "family.db")

import db
import engine as E

FAIL = []
GIRL = 3


def check(name, cond, detail=""):
    print(("  [ok]   " if cond else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    db.init_db()
    day = E.today()
    r = E.create_task_template("倒垃圾", "垃圾袋换新、桶放回原位", "daily", 0,
                               assignee_id=GIRL, reward_type="stardust",
                               reward={"amount": 5}, created_by=1)
    check("建模板成功", r.get("ok"), r)
    tid = r["id"]
    check("第一次到期在明天", r["next_due"] > day, r["next_due"])

    db.execute("UPDATE task_template SET next_due=? WHERE id=?", (day, tid))
    g = E.generate_task_templates(day)
    check("到期生成 1 条", g.get("generated") == 1, g)
    n = db.query_one("SELECT COUNT(*) c FROM task WHERE title='倒垃圾'")["c"]
    check("任务表里有 1 条", n == 1, n)
    t = db.query_one("SELECT * FROM task WHERE title='倒垃圾'")
    check("派给了女儿", t["assignee_id"] == GIRL, t["assignee_id"])
    check("奖励是 5 星尘", t["reward_type"] == "stardust" and '"amount": 5' in t["reward_json"],
          t["reward_json"])
    row = db.query_one("SELECT * FROM task_template WHERE id=?", (tid,))
    check("next_due 已推到未来", row["next_due"] > day, row["next_due"])
    check("last_result 已生成", row["last_result"] == "已生成", row["last_result"])

    g2 = E.generate_task_templates(day)
    check("同一天再跑不重复", g2.get("generated") == 0, g2)
    n2 = db.query_one("SELECT COUNT(*) c FROM task WHERE title='倒垃圾'")["c"]
    check("任务还是 1 条", n2 == 1, n2)

    E.set_task_template_active(tid, False, operator_id=1)
    db.execute("UPDATE task_template SET next_due=? WHERE id=?", (day, tid))
    g3 = E.generate_task_templates(day)
    check("停用后不生成", g3.get("generated") == 0, g3)

    r2 = E.create_task_template("擦桌子", "桌面没灰、东西归位", "weekly", 6,
                                assignee_id=None, reward_type="energy",
                                reward={"amount": 1}, created_by=1)
    check("大厅模板建成功", r2.get("ok"), r2)
    db.execute("UPDATE task_template SET next_due=? WHERE id=?", (day, r2["id"]))
    g4 = E.generate_task_templates(day)
    check("大厅模板生成 1 条", g4.get("generated") == 1, g4)
    hall = db.query_one("SELECT * FROM task WHERE title='擦桌子'")
    check("大厅任务 assignee 为空", hall["assignee_id"] is None, hall["assignee_id"])
    check("大厅任务状态 open", hall["status"] == "open", hall["status"])

    print("\n" + "=" * 50)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for x in FAIL:
            print("  - " + x)
        return 1
    print("周期任务测试全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
