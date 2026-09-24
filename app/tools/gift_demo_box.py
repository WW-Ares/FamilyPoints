# -*- coding: utf-8 -*-
"""给演示库（8090）的儿子女儿各发一只待开宝箱，供实机试开箱动画。
用法（app 目录）：FAMILY_DATA_DIR=data/demo python tools/gift_demo_box.py [tier]
"""
import os
import sys

import db
import engine

tier = int(sys.argv[1]) if len(sys.argv) > 1 else 4

kids = db.query(
    "SELECT id, name FROM member WHERE role='child' AND active=1 ORDER BY sort, id")
if not kids:
    print("没有找到孩子成员")
    sys.exit(1)

for k in kids:
    cyc = engine.current_cycle(k["id"])
    r = engine.issue_box(k["id"], tier, cycle_id=cyc["id"] if cyc else None,
                         source="free")
    print(k["name"], "->", r.get("name"), "box_id=%s" % r.get("box_id"))
