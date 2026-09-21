# -*- coding: utf-8 -*-
"""把纸质账上的存量搬进系统：星尘、券、卡。

一次性的事，不是每天要跑的工具。孩子手上已经有东西了，现在换系统，
这些得有个正经的入口落进库里，而不是家长用星探时刻一条一条补
（那条路每次最多 5 星尘，还得附一句话，补 50 星尘要点十次）。

三件绕不开的事，脚本替你处理了：

1. **星尘必须写流水。** 余额是 SUM(ledger.delta_stardust) 算出来的，
   没有「直接改余额」这回事。写的是 kind='carryover'（存量结转）。

2. **结转的星尘不进「累计获得」，等级从零开始。** 等级看的是 lifetime
   （engine.lifetime_stardust），每次升级会补发券和卡。纸质账上的东西是
   孩子在系统外面攒的，算进去等于一登录就跳几级、白补一批道具出来。
   engine.LEVEL_EXCLUDED_KINDS 里排掉了 carryover。

3. **默认只预演，不动库。** 不加 --apply 就是把要写的东西打出来给你看。
   数字填错了的先看清楚再写。

用法：

    python tools/carryover_in.py --template          # 生成一份空白模板
    python tools/carryover_in.py --items             # 列出能结转的道具 code
    python tools/carryover_in.py --show              # 看各孩子现在的余额
    python tools/carryover_in.py --file 结转.json    # 预演
    python tools/carryover_in.py --file 结转.json --apply   # 真写

在 NAS 上跑（容器已经起来的机器）：

    docker cp tools/carryover_in.py family-points:/srv/
    docker exec -it family-points python /srv/carryover_in.py --show
    docker exec -it family-points python /srv/carryover_in.py --file /srv/结转.json --apply

    文件要先放进去：docker cp 结转.json family-points:/srv/
    容器里的库在 /data/family.db，脚本默认就找它（环境变量已经设好了）。

改数字：再跑一次不行（会拦），要么用 --again 补一条差额，要么先 --show 看清
余额再决定补多少。星尘只增不减是硬规矩，补负数会被挡住。

JSON 长这样：

    {
      "by": "爸爸",
      "note": "纸质账结转",
      "children": {
        "女儿": {"stardust": 46, "items": {"ticket_fun": 3, "ticket_company": 1}},
        "儿子": {"stardust": 12, "items": {"ticket_fun": 1}}
      }
    }
"""
import argparse
import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

SOURCE = "carryover"
KIND = "carryover"


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
    D.init_db(verbose=False)   # 空跑；库是新的才会建，旧的会顺带跑迁移
    return D, E


def children(D):
    return D.query("SELECT * FROM member WHERE role='child' AND active=1 ORDER BY sort, id")


def items(D):
    return D.query("SELECT * FROM item WHERE active=1 AND category IN ('ticket','card')"
                   " ORDER BY category, price, id")


def shelf_text(it):
    days = it["shelf_life_days"]
    if not days:
        return "永不过期"
    return "保质期 %d 天，从今天起算" % days


def cmd_items(D, E):
    rows = items(D)
    now = [r for r in rows if r["category"] == "ticket"]
    card = [r for r in rows if r["category"] == "card"]
    print("可以结转的券（%d 种）：" % len(now))
    for r in now:
        print("  %-16s %-6s  %s" % (r["code"], r["name"], shelf_text(r)))
    print()
    print("可以结转的卡（%d 种）：" % len(card))
    for r in card:
        hold = r["max_hold"] or "-"
        print("  %-16s %-8s %-4s 持有上限 %-3s %s"
              % (r["code"], r["name"], r["rarity"] or "", hold, shelf_text(r)))
    print()
    print("持有上限到了会按规则拆成碎片，这一步系统自己算，脚本拦不住，填之前先看这一列。")


def cmd_template(D, E):
    kids = children(D)
    slots = {r["code"]: 0 for r in items(D) if r["category"] == "ticket"}
    adm = D.query_one("SELECT name FROM member WHERE is_admin=1 AND active=1")
    out = {
        "by": adm["name"] if adm else "爸爸",
        "note": "纸质账结转",
        "children": {k["name"]: {"stardust": 0, "items": dict(slots)} for k in kids},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("", file=sys.stderr)
    print("券只有这六种列在模板里。卡也能填，code 用 --items 查，加进 items 就行。",
          file=sys.stderr)
    print("不要的项目直接删掉那一行，别填 0。", file=sys.stderr)


def cmd_show(D, E):
    for k in children(D):
        bal = E.stardust_balance(k["id"])
        life = E.lifetime_stardust(k["id"])
        lv = E.level_of(k["id"]) or {}
        # 一次结转会写出好几条流水（星尘一条，每个道具各一条），
        # 这里把流水条数和结转进来的星尘一起报，别让人误以为结转了四次。
        done = D.query_one("SELECT COUNT(*) n, COALESCE(SUM(delta_stardust),0) sd FROM ledger"
                           " WHERE member_id=? AND kind=? AND voided=0", (k["id"], KIND))
        # 同一个道具可能有好几个批次（来源、时间不同），按道具合并看总数，
        # 有保质期的取最早那个到期日。
        holds = D.query(
            "SELECT i.name, i.category, SUM(h.qty) qty, MIN(h.expires_at) expires_at"
            " FROM holding h JOIN item i ON i.id=h.item_id"
            " WHERE h.member_id=? AND h.qty>0"
            " GROUP BY i.id ORDER BY i.category, i.sort", (k["id"],))
        print("%s（id=%d）" % (k["name"], k["id"]))
        print("    星尘余额 %g，其中累计 %g（等级 Lv.%s %s）"
              % (bal, life, lv.get("level", "-"), lv.get("title", "")))
        print("    结转流水 %d 条（累计搬进来 %g 星尘）" % (done["n"], done["sd"]))
        if holds:
            for h in holds:
                exp = h["expires_at"] or "永不过期"
                print("    持有 %-8s ×%-5g 到期 %s" % (h["name"], h["qty"], exp))
        else:
            print("    手上没有道具")
        print()


def check_plan(D, E, spec):
    """把清单校验一遍，返回（要写的清单，问题，已经结转过的人）。"""
    kids = {k["name"]: k for k in children(D)}
    by_code = {r["code"]: r for r in items(D)}
    plan, problems = [], []

    for name, one in (spec.get("children") or {}).items():
        k = kids.get(name)
        if not k:
            problems.append("库里没有叫「%s」的在册孩子" % name)
            continue
        sd = float(one.get("stardust") or 0)
        if sd < 0:
            problems.append("%s 的星尘填了负数（%g）。星尘只增不减，改数字请补一条正的差额" % (name, sd))

        rows = []
        for code, qty in (one.get("items") or {}).items():
            it = by_code.get(code)
            if not it:
                problems.append("%s 的项目 code「%s」不存在，用 --items 查一下" % (name, code))
                continue
            q = float(qty or 0)
            if q <= 0:
                continue
            warn = []
            if it["max_hold"] and q > it["max_hold"]:
                warn.append("持有上限 %d，超出的 %g 会拆成碎片"
                            % (it["max_hold"], q - it["max_hold"]))
            if it["shelf_life_days"]:
                warn.append("保质期从今天起算 %d 天" % it["shelf_life_days"])
            rows.append({"item": it, "qty": q, "warn": warn})
        plan.append({"member": k, "stardust": sd, "items": rows})

    already = []
    for p in plan:
        n = D.query_one("SELECT COUNT(*) n FROM ledger WHERE member_id=? AND kind=?"
                        " AND voided=0", (p["member"]["id"], KIND))["n"]
        if n:
            already.append(p["member"]["name"])
    return plan, problems, already


def run(D, E, plan, spec, apply_it):
    admin = None
    by = (spec.get("by") or "").strip()
    if by:
        admin = D.query_one("SELECT * FROM member WHERE (username=? OR name=?) AND active=1",
                            (by, by))
        if not admin:
            print("找不到操作人「%s」，换成 --file 里的 by 或者库里有的名字" % by)
            return 1
    else:
        admin = D.query_one("SELECT * FROM member WHERE is_admin=1 AND active=1")
    op = admin["id"] if admin else None
    note = (spec.get("note") or "纸质账结转").strip()

    print("库：%s" % D.DB_PATH)
    print("操作人：%s（id=%s）" % (admin["name"] if admin else "无", op))
    print()

    for p in plan:
        k = p["member"]
        bal0 = E.stardust_balance(k["id"])
        print("%s（id=%d）" % (k["name"], k["id"]))
        if p["stardust"]:
            print("    星尘   +%g      结转后余额 %g；不计入累计，等级不受影响"
                  % (p["stardust"], bal0 + p["stardust"]))
        for row in p["items"]:
            it = row["item"]
            print("    %-6s +%g 张  %s" % (it["name"], row["qty"], shelf_text(it)))
            for w in row["warn"]:
                print("           ⚠ %s" % w)
        if not p["stardust"] and not p["items"]:
            print("    没填东西，跳过")
        print()

    if not apply_it:
        print("以上是预演，库里什么都没动。确认无误再加 --apply。")
        return 0

    print("开始写入……")
    for p in plan:
        k, hid = p["member"], []
        if not p["stardust"] and not p["items"]:
            continue
        if p["stardust"]:
            E.add_ledger(k["id"], KIND, stardust=p["stardust"], note=note, operator_id=op,
                         meta={"source": SOURCE, "why": "纸质账迁移"})
        for row in p["items"]:
            r = E.grant_item(k["id"], row["item"]["id"], row["qty"], source=SOURCE,
                             kind=KIND, note=note, operator_id=op)
            if r[2]:
                hid.append("%s 拆出 %g 片碎片" % (row["item"]["name"], r[2]))
        done = "星尘 +%g" % p["stardust"] if p["stardust"] else "无星尘"
        done += "，道具 %d 项" % len(p["items"])
        print("  %-6s %s%s" % (k["name"], done, ("（" + "；".join(hid) + "）") if hid else ""))
        D.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
                  " VALUES (?,?,?,?,?)",
                  (op, "carryover.in", "member", k["id"], D.now()))

    print()
    print("写完了。核对一遍：")
    print()
    cmd_show(D, E)
    return 0


def main():
    ap = argparse.ArgumentParser(description="把纸质账上的存量搬进系统")
    ap.add_argument("--file", help="结转清单 JSON")
    ap.add_argument("--db", help="指定数据库文件；不给就用环境变量或 app/data/family.db")
    ap.add_argument("--apply", action="store_true", help="真写进库，不加就是预演")
    ap.add_argument("--again", action="store_true",
                    help="这个孩子已经结转过也继续写（补差额时才用，会留下第二份记录）")
    ap.add_argument("--template", action="store_true", help="打印一份空白模板")
    ap.add_argument("--items", action="store_true", help="列出能结转的道具")
    ap.add_argument("--show", action="store_true", help="看各孩子现在的余额和结转记录")
    a = ap.parse_args()

    D, E = load(a.db)

    if a.items:
        return cmd_items(D, E)
    if a.template:
        return cmd_template(D, E)
    if a.show:
        return cmd_show(D, E)

    if not a.file:
        ap.print_help()
        return 1
    try:
        spec = json.loads(Path(a.file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("找不到 %s" % a.file)
        return 1
    except ValueError as e:
        print("这个文件不是合法 JSON：%s" % e)
        return 1

    plan, problems, already = check_plan(D, E, spec)
    if problems:
        for p in problems:
            print("  ✗ %s" % p)
        print()
        print("先修上面的问题。")
        return 1
    if already and not a.again:
        print("这些孩子已经结转过：%s" % "、".join(already))
        print("确认要再来一次（比如补差额）就加 --again；只是想看看数，用 --show。")
        return 1
    if not plan:
        print("清单里没有可写的孩子。")
        return 1
    return run(D, E, plan, spec, a.apply)


if __name__ == "__main__":
    sys.exit(main())
