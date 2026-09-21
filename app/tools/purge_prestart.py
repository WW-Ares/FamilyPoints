# -*- coding: utf-8 -*-
"""清掉起用日之前那批「算错的漏打卡」。

v34 之前，忘打卡兜底只有一条判据：这天有没有固定分记录。没有起点，
于是系统一上线就往回看 7 天，把这套系统还不存在的日子全判成「忘了打分」，
补齐满分、罚了星尘。19 号晚上装好，18 号就挨一笔 —— 说的就是这件事。

v34 把起点补上了（family.start_date，默认建库那天），但已经落进库里的
那批痕迹不会自己消失。这个脚本负责擦掉它们：

  1. 补记的分数        score_entry，note = 系统补记：当天没人打分
  2. 补分产生的流水    ledger，meta 里带 missed_score（周能量那笔）
  3. 罚款              wish_pool_log / wish_pool_entry 里的 penalty
  4. 被错误分数顶起来的那次周期结算（星尘入账、周期状态）

**默认只预演**，把要动的东西一条条打出来，一个字都不改。看清楚了再加 --apply。

有一条它不碰：如果错误分数已经换来一个宝箱，脚本只报告，不自动收。
箱子里可能已经开出券、卡、随机件，收回去是另一件事，得你自己定。

用法：

    python tools/purge_prestart.py                 # 预演（app/data/family.db）
    python tools/purge_prestart.py --db 路径        # 换一个库
    python tools/purge_prestart.py --apply         # 真清

在 NAS 上跑（容器已经起来的机器）：

    docker cp tools/purge_prestart.py family-points:/srv/
    docker exec -it family-points python /srv/purge_prestart.py
    docker exec -it family-points python /srv/purge_prestart.py --apply

容器里的库在 /data/family.db，环境变量已经设好了，不给 --db 就找它。
"""
import argparse
import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))


def load(db_path):
    """连库。环境变量必须在 import db 之前设好，db.py 是模块级读的。"""
    if db_path:
        p = Path(db_path).expanduser().resolve()
        if not p.is_file():
            print("找不到这个库：%s" % p)
            sys.exit(1)
        os.environ["FAMILY_DB"] = str(p)
        os.environ.setdefault("FAMILY_DATA_DIR", str(p.parent))
    import db as D
    import engine as E
    D.init_db(verbose=False)      # 空跑；顺带把库升到当前版本
    return D, E


def num(x):
    x = float(x or 0)
    return "%g" % x if abs(x - round(x)) < 1e-9 else "%.2f" % x


def who(D, mid):
    r = D.query_one("SELECT name FROM member WHERE id=?", (mid,))
    return r["name"] if r else "#%s" % mid


def collect(D, E):
    """把起用日之前的漏打卡痕迹全找出来。预演和真清共用这一份清单。"""
    start = E.start_date()
    plan = {"start": start, "entries": [], "ledgers": [], "logs": [], "pool_entries": [],
            "cycles": {}, "notes": []}
    if not start:
        plan["notes"].append("这个库取不到起用日（family.start_date 是空的、而且成员表也空），"
                             "先把版本升到 v34 再跑。")
        return plan

    plan["entries"] = D.query(
        "SELECT id, member_id, cycle_id, day, value FROM score_entry"
        " WHERE day<=? AND note=? AND voided=0 ORDER BY member_id, day, id",
        (start, E.MISSED_NOTE))
    plan["ledgers"] = D.query(
        "SELECT id, member_id, cycle_id, day, delta_energy, note FROM ledger"
        " WHERE day<=? AND voided=0 AND kind='daily_score' AND meta LIKE '%missed_score%'"
        " ORDER BY id", (start,))
    plan["logs"] = D.query(
        "SELECT * FROM wish_pool_log WHERE kind='penalty' AND day<=? ORDER BY day", (start,))
    for lg in plan["logs"]:
        plan["pool_entries"] += D.query(
            "SELECT * FROM wish_pool_entry WHERE source='penalty' AND note=?",
            ("全家忘打卡罚款入池：%s" % lg["day"],))

    cids = set()
    for r in plan["entries"]:
        if r["cycle_id"]:
            cids.add(r["cycle_id"])
    for r in plan["ledgers"]:
        if r["cycle_id"]:
            cids.add(r["cycle_id"])
    for cid in sorted(cids):
        c = D.query_one("SELECT * FROM cycle WHERE id=?", (cid,))
        if not c:
            continue
        item = {"cycle": c, "settle_ledgers": [], "boxes": []}
        if c["status"] == "settled":
            # 结算时读的是含错分数的那份 fixed_score，所以入账的星尘也是错的
            item["settle_ledgers"] = D.query(
                "SELECT id, delta_stardust, note FROM ledger"
                " WHERE cycle_id=? AND voided=0 AND kind='daily_score'"
                " AND note LIKE '周期结算：%'", (cid,))
            item["boxes"] = D.query(
                "SELECT id, member_id, tier, source, tickets, stardust, ts FROM box_open"
                " WHERE cycle_id=?", (cid,))
        plan["cycles"][cid] = item
    return plan


def show(D, E, plan):
    """把清单打出来。返回 True 表示「有东西要清」。"""
    print("=== 起用日之前的漏打卡痕迹 ===")
    if plan["notes"]:
        for n in plan["notes"]:
            print("  " + n)
        return False
    print("起用日：%s（family.start_date）　清理范围：day <= %s" % (plan["start"], plan["start"]))
    print()

    n = len(plan["entries"])
    print("【补记的分数】%d 行" % n)
    byday = {}
    for r in plan["entries"]:
        byday.setdefault((r["member_id"], r["day"]), 0.0)
        byday[(r["member_id"], r["day"])] += float(r["value"] or 0)
    for (mid, day), v in sorted(byday.items(), key=lambda x: (x[0][1], x[0][0])):
        print("  %s  %s  记了 %s 分" % (who(D, mid), day, num(v)))

    print()
    print("【补分流水】%d 条" % len(plan["ledgers"]))
    for r in plan["ledgers"]:
        print("  %s  %s  周能量 +%s　%s"
              % (who(D, r["member_id"]), r["day"], num(r["delta_energy"]), r["note"]))

    print()
    total = sum(float(r["stardust"] or 0) for r in plan["logs"])
    print("【罚款】%d 笔，合计 %s 星尘" % (len(plan["logs"]), num(total)))
    for r in plan["logs"]:
        print("  %s  %s 星尘　%s" % (r["day"], num(r["stardust"]), r["note"]))

    print()
    print("【受影响的周期】%d 个" % len(plan["cycles"]))
    for cid, item in sorted(plan["cycles"].items()):
        c = item["cycle"]
        print("  #%d  %s  %s ~ %s  %s"
              % (cid, who(D, c["member_id"]), c["start_date"], c["end_date"],
                 "已结算（要回退）" if c["status"] == "settled" else "未结算（重算即可）"))
        for lg in item["settle_ledgers"]:
            print("     └ 结算入账 星尘 +%s，这笔要撤" % num(lg["delta_stardust"]))
        for b in item["boxes"]:
            print("     └ 发了箱子：第 %d 档（source=%s，保底券 %s / 星尘 %s）"
                  % (b["tier"], b["source"], num(b["tickets"]), num(b["stardust"])))
        if item["boxes"]:
            print("     ⚠ 这个箱子是错误分数换来的，脚本不自动收 —— 要收的话说一声，"
                  "箱子里可能已经开出券和卡。")

    empty = not (plan["entries"] or plan["ledgers"] or plan["logs"])
    print()
    print("（什么都没找到，库是干净的）" if empty else "（以上是待清理的全部内容）")
    return not empty


def do_apply(D, E, plan):
    ids_e = [int(r["id"]) for r in plan["entries"]]
    ids_l = [int(r["id"]) for r in plan["ledgers"]]
    ids_g = [int(r["id"]) for r in plan["logs"]]
    ids_pe = [int(r["id"]) for r in plan["pool_entries"]]
    ids_s = []
    cids = []
    for cid, item in plan["cycles"].items():
        cids.append(cid)
        ids_s += [int(r["id"]) for r in item["settle_ledgers"]]

    def mark(table, ids, col="voided"):
        if ids:
            D.execute("UPDATE %s SET %s=1 WHERE id IN (%s)"
                      % (table, col, ",".join(str(i) for i in ids)))

    def drop(table, ids):
        if ids:
            D.execute("DELETE FROM %s WHERE id IN (%s)" % (table, ",".join(str(i) for i in ids)))

    mark("score_entry", ids_e)
    mark("ledger", ids_l)
    mark("ledger", ids_s)                 # 撤掉错误分数顶起来的那次结算入账
    drop("wish_pool_entry", ids_pe)       # 池子进度是 SUM(entry)，删掉就自动回正
    drop("wish_pool_log", ids_g)

    for cid in cids:
        if plan["cycles"][cid]["cycle"]["status"] == "settled":
            D.execute("UPDATE cycle SET status='open', settled_at=NULL, stardust_grant=0,"
                      " tier_awarded=0 WHERE id=?", (cid,))
        E.recalc_cycle(cid)

    D.execute(
        "INSERT INTO audit_log (actor_id, action, target_type, target_id, before_json,"
        " after_json, ts) VALUES (NULL,'purge_prestart','family',NULL,?,?,?)",
        (json.dumps({"entries": len(ids_e), "ledgers": len(ids_l) + len(ids_s),
                     "penalty_logs": len(ids_g), "pool_entries": len(ids_pe),
                     "cycles": cids, "start_date": plan["start"]}, ensure_ascii=False),
         json.dumps({"voided": True}, ensure_ascii=False), E.now()))
    print("已清理：补记 %d 行、流水 %d 条、罚款 %d 笔、周期回退 %d 个"
          % (len(ids_e), len(ids_l) + len(ids_s), len(ids_g), len(cids)))


def main():
    ap = argparse.ArgumentParser(description="清掉起用日之前的漏打卡痕迹")
    ap.add_argument("--db", help="指定数据库文件；不给就用环境变量或 app/data/family.db")
    ap.add_argument("--apply", action="store_true", help="真清，不加就是预演")
    a = ap.parse_args()

    D, E = load(a.db)
    print("库：%s" % D.DB_PATH)
    print()
    plan = collect(D, E)
    found = show(D, E, plan)
    if not a.apply:
        print()
        print("这是预演，什么都没改。确认清单没问题，再加 --apply 跑一次。")
        return 0
    if not found:
        return 0
    print()
    do_apply(D, E, plan)
    print()
    again = collect(D, E)
    left = len(again["entries"]) + len(again["ledgers"]) + len(again["logs"])
    print("清理后再查一遍：还剩 %d 条痕迹。%s" % (left, "干净了。" if not left else "还有剩，贴上来看。"))
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
