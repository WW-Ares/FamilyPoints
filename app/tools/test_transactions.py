# -*- coding: utf-8 -*-
"""事务与并发回归：确认任务只能发一次奖，失败要整笔回滚。"""
import json
import os
import sys
import tempfile
import threading

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

TEST_DIR = tempfile.mkdtemp(prefix="fp-tx-")
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


def new_task(title):
    return db.execute(
        "INSERT INTO task (kind,title,std,assignee_id,created_by,reward_type,"
        "reward_json,status,created_at,submitted_at) VALUES "
        "('reward',?,'',? ,1,'stardust',?,'submitted',?,?)",
        (title, GIRL, json.dumps({"amount": 10}), db.now(), db.now()))


def main():
    db.init_db()

    print("\n=== 并发确认：只发一次奖 ===")
    tid = new_task("并发确认")
    base = E.stardust_balance(GIRL)
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            results.append(E.confirm_task(tid, operator_id=1))
        except Exception as e:
            results.append({"ok": False, "err": str(e)})

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    ok = [r for r in results if r.get("ok")]
    check("只有一个线程成功", len(ok) == 1, results)
    check("星尘只加 10", abs(E.stardust_balance(GIRL) - (base + 10)) < 1e-9,
          (base, E.stardust_balance(GIRL)))
    n = db.query_one("SELECT COUNT(*) c FROM ledger WHERE member_id=? AND kind='task_stardust'"
                     " AND note LIKE '任务奖励：并发确认%'", (GIRL,))["c"]
    check("只写了一条奖励流水", n == 1, n)
    check("任务状态是 confirmed",
          db.query_one("SELECT status FROM task WHERE id=?", (tid,))["status"] == "confirmed")

    print("\n=== 事务中途失败：task 状态和 ledger 都回滚 ===")
    tid2 = new_task("回滚确认")
    base2 = E.stardust_balance(GIRL)
    orig = E._pay_task_reward

    def boom(t, operator_id=None):
        E.add_ledger(t["assignee_id"], "task_stardust", stardust=10, note="boom")
        raise RuntimeError("boom")

    E._pay_task_reward = boom
    try:
        E.confirm_task(tid2, operator_id=1)
        check("应该抛异常", False)
    except RuntimeError:
        check("异常按预期抛出", True)
    finally:
        E._pay_task_reward = orig
    check("task 状态退回 submitted",
          db.query_one("SELECT status FROM task WHERE id=?", (tid2,))["status"] == "submitted")
    check("星尘没有变", abs(E.stardust_balance(GIRL) - base2) < 1e-9,
          (base2, E.stardust_balance(GIRL)))
    n2 = db.query_one("SELECT COUNT(*) c FROM ledger WHERE member_id=? AND note='boom'",
                      (GIRL,))["c"]
    check("异常前的流水也回滚了", n2 == 0, n2)

    print("\n" + "=" * 50)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for x in FAIL:
            print("  - " + x)
        return 1
    print("事务测试全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
