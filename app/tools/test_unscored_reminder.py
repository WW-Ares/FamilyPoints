# -*- coding: utf-8 -*-
"""未打分提醒的定时逻辑测试。

不连服务器、不动正式库：在临时目录里建一个空库，把 kids_overview 和
_notify 换成桩，按固定时间点调用 notify._sched_daily_score。

跑法：python app/tools/test_unscored_reminder.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

TEST_DIR = tempfile.mkdtemp(prefix="fp-remind-")
os.environ["FAMILY_DATA_DIR"] = TEST_DIR
os.environ["FAMILY_DB"] = os.path.join(TEST_DIR, "family.db")

import db
import engine as E
import notify as N

FAIL = []


def check(name, cond, detail=""):
    print(("  [ok]   " if cond else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


def set_cfg(key, value):
    db.execute("UPDATE setting SET value=? WHERE key=?", (json.dumps(value), key))
    db.settings_all(force=True)


def clear_day():
    db.execute("DELETE FROM meta WHERE key LIKE 'push.sched.daily_score.%'")
    del SENT[:]


def at(hh, mm):
    return datetime(2026, 11, 17, hh, mm, 0)


SENT = []
N._notify = lambda member_id, kind, title, body: SENT.append(
    {"member_id": member_id, "kind": kind, "title": title, "body": body})
N._in_quiet = lambda now_dt: False

KIDS = [
    {"name": "女儿", "today": {"scored": False, "transition": False}},
    {"name": "儿子", "today": {"scored": False, "transition": False}},
]


def kids():
    return [{"name": k["name"], "today": dict(k["today"])} for k in KIDS]


def main():
    db.init_db()
    E.kids_overview = kids
    set_cfg("push.daily_score_at", "20:30")
    set_cfg("push.daily_score_times", 3)
    set_cfg("push.daily_score_interval_min", 30)

    print("\n=== 基本节奏：20:30 / 3 次 / 30 分钟 ===")
    clear_day()
    N._sched_daily_score(at(20, 0))
    check("不到点不发", len(SENT) == 0)
    N._sched_daily_score(at(20, 30))
    check("20:30 发第 1 次", len(SENT) == 1, SENT[-1] if SENT else "")
    check("第 1 次列两个孩子", "女儿" in SENT[-1]["body"] and "儿子" in SENT[-1]["body"])
    N._sched_daily_score(at(20, 45))
    check("20:45 没到间隔，不发", len(SENT) == 1)
    N._sched_daily_score(at(21, 0))
    check("21:00 发第 2 次", len(SENT) == 2)
    check("第 2 次带次数", "2/3" in SENT[-1]["title"], SENT[-1]["title"])
    N._sched_daily_score(at(21, 30))
    check("21:30 发第 3 次", len(SENT) == 3)
    N._sched_daily_score(at(22, 0))
    check("次数用完不再发", len(SENT) == 3)
    N._sched_daily_score(at(22, 30))
    check("重启/重复调用也不发", len(SENT) == 3)

    print("\n=== 某个孩子中途打过分 ===")
    clear_day()
    N._sched_daily_score(at(20, 30))
    KIDS[0]["today"]["scored"] = True
    N._sched_daily_score(at(21, 0))
    check("下一条只提没打分的儿子", "儿子" in SENT[-1]["body"] and "女儿" not in SENT[-1]["body"],
          SENT[-1]["body"])
    KIDS[0]["today"]["scored"] = False

    print("\n=== 全部打完 ===")
    clear_day()
    KIDS[0]["today"]["scored"] = True
    KIDS[1]["today"]["scored"] = True
    N._sched_daily_score(at(20, 30))
    check("全部打完不发", len(SENT) == 0)
    row = db.query_one("SELECT value FROM meta WHERE key='push.sched.daily_score.2026-11-17'")
    check("当天标记结束", bool(row) and json.loads(row["value"]).get("done") is True)
    KIDS[0]["today"]["scored"] = False
    KIDS[1]["today"]["scored"] = False

    print("\n=== 0 次 = 关闭 ===")
    clear_day()
    set_cfg("push.daily_score_times", 0)
    N._sched_daily_score(at(20, 30))
    check("0 次不发", len(SENT) == 0)

    print("\n=== 过渡日不提醒 ===")
    clear_day()
    set_cfg("push.daily_score_times", 3)
    KIDS[0]["today"]["transition"] = True
    KIDS[1]["today"]["scored"] = True
    N._sched_daily_score(at(20, 30))
    check("过渡日 + 已打完，不发", len(SENT) == 0)
    KIDS[0]["today"]["transition"] = False
    KIDS[1]["today"]["scored"] = False

    print("\n" + "=" * 50)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for x in FAIL:
            print("  - " + x)
        return 1
    print("未打分提醒测试全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
