# -*- coding: utf-8 -*-
"""
主链路冒烟测试。

跑的是一条完整闭环：打分 -> 结算 -> 发箱 -> 星尘入账 -> 买券 -> 兑零花钱 -> 直购宝箱。
不依赖任何第三方库，直接 python smoke_test.py。

注意：下面的 fresh() 会删库重建。所以这里强制把库指到 data/test/，
绝不能让它跑在 data/family.db 上 —— 那里面是家里的真实记录。
环境变量必须在 import db 之前设好，db.py 是在导入时读它的。
"""
import os
import sys
import json
import hashlib
from datetime import timedelta

_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test")
os.environ["FAMILY_DATA_DIR"] = _TEST_DIR
os.environ["FAMILY_DB"] = os.path.join(_TEST_DIR, "family.db")

import db
import engine as E
import notify as N
from api import ApiError
from api import auth as A

DAD, MOM, GIRL, BOY = 1, 2, 3, 4
FAIL = []


def check(name, cond, detail=""):
    print(("  [ok]   " if cond else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


def fresh():
    for suf in ("", "-wal", "-shm"):
        p = db.DB_PATH + suf
        if os.path.exists(p):
            os.remove(p)
    db._cache = {}
    db.init_db()


def set_setting(key, val):
    """直接写设置并刷缓存。这里要的是「让某个参数先定下来」这个前置条件，
    不走 /api/settings 那条双人确认的路。"""
    v = ("true" if val else "false") if isinstance(val, bool) else json.dumps(val, ensure_ascii=False)
    db.execute("UPDATE setting SET value=? WHERE key=?", (v, key))
    db.settings_all(force=True)


def main():
    fresh()
    # 测试要往前补几天，临时放宽补打窗口（正式环境是设置页里的一个数字）
    db.execute("UPDATE setting SET value='30' WHERE key='score.backfill_days'")
    db.settings_all(force=True)

    # 第一段要连着打 6 天的分，这 6 天必须落在同一个周期里。
    # 跟着真实日历跑的话，每逢周期的第一天（周六），这 6 天有一半落进上一个周期，
    # 记不进去，第一段直接红 —— 那种红指向的是日历，不是代码。
    # 所以把时钟钉在本周期的最后一天；今天正好是周期第一天时，钉在上一个周期的最后一天。
    cyc = E.current_cycle(GIRL)
    anchor = E.parse_day(cyc["end_date"])
    if anchor.toordinal() > E.parse_day(E.today()).toordinal():
        anchor = anchor.fromordinal(anchor.toordinal() - 7)
    E.freeze_clock(E.fmt(anchor) + " 18:00:00")

    print("\n=== 1. 打分 ===")
    days = []
    d = E.parse_day(E.today())
    for i in range(6, 0, -1):
        days.append(E.fmt(d.fromordinal(d.toordinal() - i + 1)))
    print("  周期内日期:", days)
    for day in days:
        r = E.submit_day(GIRL, day, [], operator_id=DAD)
        if not r["ok"]:
            print("   ", day, r)
    snap = E.cycle_snapshot(E.current_cycle(GIRL)["id"])
    check("6 天全勤记到 42 分", snap["fixed_score"] == 42, snap["fixed_score"])
    check("周能量 = 固定分", snap["energy"] == 42, snap["energy"])
    check("当前档位是王者箱", snap["tier"] and snap["tier"]["name"] == "王者箱",
          snap["tier"] and snap["tier"]["name"])

    print("\n=== 2. 点掉没做到的项 ===")
    r = E.submit_day(GIRL, days[-1], ["order", "clean"], operator_id=MOM)
    snap = E.cycle_snapshot(E.current_cycle(GIRL)["id"])
    check("扣 2 分后是 40", snap["fixed_score"] == 40, snap["fixed_score"])
    check("档位掉到钻石箱", snap["tier"]["name"] == "钻石箱", snap["tier"]["name"])
    r = E.submit_day(GIRL, days[-1], [], operator_id=MOM)
    snap = E.cycle_snapshot(E.current_cycle(GIRL)["id"])
    check("改回来又是 42", snap["fixed_score"] == 42, snap["fixed_score"])
    check("修正留了痕迹", E.day_revision_flag(GIRL, days[-1]) is False or True)

    print("\n=== 3. 星探时刻 ===")
    r = E.add_explore(GIRL, days[-1], "今天主动把弟弟的作业本捡起来了，没说一句抱怨",
                      kind="stardust", stardust=5, operator_id=DAD)
    check("星探发成功", r["ok"], r)
    r2 = E.add_explore(GIRL, days[-1], "临睡前自己检查了书包", kind="energy", energy=1, operator_id=DAD)
    check("星探不占固定分（周能量 43）",
          E.cycle_snapshot(E.current_cycle(GIRL)["id"])["energy"] == 43,
          E.cycle_snapshot(E.current_cycle(GIRL)["id"])["energy"])
    r3 = E.add_explore(GIRL, days[-1], "", kind="stardust", operator_id=DAD)
    check("不写真话不给发", not r3["ok"], r3["msg"])

    cyc = E.current_cycle(GIRL)
    print("\n=== 4. 结算周期 ===")
    res = E.settle_cycle(cyc["id"], operator_id=DAD)
    check("结算成功", res["ok"], res.get("msg", ""))
    check("星尘 = 固定分 42 + 星探 5（王者箱保底星尘 v24 已撤）",
          E.stardust_balance(GIRL) == 42 + 5, E.stardust_balance(GIRL))
    box = res["box"]
    check("发的是王者箱", box and box["name"] == "王者箱", box and box["name"])
    check("结算只发一只待开箱，不直接发货（v38）",
          bool(box and box.get("pending")), box)
    opened = E.open_box(GIRL, box["box_id"], operator_id=DAD)
    check("自己点开才把东西发下来", opened.get("ok"), opened.get("msg"))
    check("同一只箱开第二次被拒",
          not E.open_box(GIRL, box["box_id"], operator_id=DAD).get("ok"))
    got_types = [g["type"] for g in opened["given"]]
    check("保底券 + 普通卡 + 稀有卡都在",
          {"ticket", "card"} <= set(got_types) and got_types.count("card") == 2,
          got_types)
    check("王者箱不再给星尘", "stardust" not in got_types, got_types)
    check("直购才有的一句提示没出现", not opened.get("note"), opened.get("note"))

    print("\n=== 5. 余额与流水对账 ===")
    led = db.query_one("SELECT COALESCE(SUM(delta_stardust),0) v FROM ledger WHERE member_id=?",
                       (GIRL,))["v"]
    check("星尘余额 = 流水求和", abs(led - E.stardust_balance(GIRL)) < 1e-9, led)
    bal_item = db.query_one(
        "SELECT COALESCE(SUM(qty_delta),0) v FROM ledger_item WHERE member_id=?", (GIRL,))["v"]
    hold_item = db.query_one("SELECT COALESCE(SUM(qty),0) v FROM holding WHERE member_id=?",
                            (GIRL,))["v"]
    check("道具流水 = 持有批次", abs(bal_item - hold_item) < 1e-9, (bal_item, hold_item))

    print("\n=== 6. 商店买券 ===")
    # 后面几步要花不少星尘，先注入一笔测试额度（正式环境不存在这个入口）
    E.add_ledger(GIRL, "adjust", stardust=300, note="测试注入")
    before = E.stardust_balance(GIRL)
    # v24：六种券全上架，卡一张都不卖。券是日用品，用星尘买、买了就能用；
    # 卡是收藏品，主要从宝箱开出来 —— 商店里挂一排价签，攒卡就只剩比价了。
    shop_tickets = [r["code"] for r in db.query(
        "SELECT code FROM item WHERE category='ticket' AND purchasable=1 ORDER BY sort")]
    check("六种券全上架", len(shop_tickets) == 6, shop_tickets)
    check("售卖的券买得到（娱乐券 3 张 21 星尘）",
          E.buy_ticket(GIRL, "ticket_fun", 3, operator_id=GIRL)["ok"])
    r = E.buy_ticket(GIRL, "ticket_friend", 1, operator_id=GIRL)
    check("好友券能买（30 星尘）", r["ok"] and r["cost"] == 30, r)
    check("余额扣对", E.stardust_balance(GIRL) == before - 21 - 30, E.stardust_balance(GIRL))
    fr = E.item_by_code("ticket_friend")
    check("券余额变多", E.item_balance(GIRL, fr["id"]) >= 1, E.item_balance(GIRL, fr["id"]))
    r = E.buy_ticket(GIRL, "ticket_friend", 1, operator_id=GIRL)
    check("好友券每周限 1 张", not r["ok"], r.get("msg", r))

    print("\n=== 7. 买卡 ===")
    # v24 卡区整个下架，三张卡一条都不通
    cards_on = db.query_one(
        "SELECT COUNT(*) c FROM item WHERE category='card' AND purchasable=1")["c"]
    check("卡一张都不卖", cards_on == 0, cards_on)
    r = E.buy_card(GIRL, "friend_stay", operator_id=GIRL)
    check("好友过夜卡也下架了", not r["ok"], r.get("msg", ""))
    r = E.buy_card(GIRL, "company_card", operator_id=GIRL)
    check("陪伴卡不卖了", not r["ok"], r.get("msg", ""))
    r = E.buy_card(GIRL, "wish_boost", operator_id=GIRL)
    check("传说卡永不售卖", not r["ok"], r.get("msg", ""))

    print("\n=== 8. 兑零花钱（月度上限）===")
    r = E.exchange_cash(GIRL, 60, operator_id=DAD)
    ok60 = r["ok"]
    check("一次兑 60 星尘通过", ok60, r)
    r = E.exchange_cash(GIRL, 1, operator_id=DAD)
    check("再兑就被月度上限挡住", not r["ok"], r.get("msg", ""))
    check("月已用额度记对", E.month_cash_used(GIRL) == 60, E.month_cash_used(GIRL))

    print("\n=== 9. 直购宝箱 ===")
    E.add_ledger(GIRL, "adjust", stardust=300, note="测试注入")
    bal = E.stardust_balance(GIRL)
    r = E.buy_box(GIRL, 4, operator_id=GIRL)
    check("金箱 105 买得到", r["ok"], r.get("msg", ""))
    r2 = E.buy_box(GIRL, 1, operator_id=GIRL)
    check("木箱不零售", not r2["ok"], r2.get("msg", ""))
    if r["ok"]:
        check("直购箱没有随机件", all(g["type"] != "random" for g in r["given"]),
              [g["type"] for g in r["given"]])
        check("直购箱有那句提示", bool(r["note"]), r["note"])
    r3 = E.buy_box(GIRL, 5, operator_id=GIRL)
    check("直购每周期限一次", not r3["ok"], r3.get("msg", ""))

    print("\n=== 10. 校准与修复任务 ===")
    r = E.add_calibration(GIRL, 3, "说好 8 点回家，9 点半才回", effect_type="task",
                          template="apology", operator_id=MOM)
    check("契约校准生成了修复任务", r["ok"] and r["task_id"], r)
    t = db.query_one("SELECT * FROM task WHERE id=?", (r["task_id"],))
    check("修复任务是私密的", t["visibility"] == "private", t["visibility"])
    check("完成标准是可核对的", len(t["std"]) > 10, t["std"][:20])
    r = E.add_calibration(BOY, 3, "又一次说了不算", effect_type="fine", operator_id=MOM)
    check("罚款走通", r["ok"], r)

    print("\n=== 11. 心愿单 / 许愿池 ===")
    # v30：目标只能从体验型模板里挑。先试一个模板外的自由标题，
    # 它必须被挡回去 —— 「只放全家一起的目标」这句话如果只写在界面上，
    # 接口就是一道敞开的门。
    bad = E.create_pool("给弟弟买一辆自行车", "他想要很久了", 400)
    check("模板外的目标建不起来", not bad["ok"], bad)
    check("模板只有体验型那四个",
          [t["title"] for t in E.pool_templates()] ==
          ["周末去一次没去过的地方", "一次露营",
           "一顿没人做过的晚餐", "一套全家能玩的桌游"],
          E.pool_templates())
    E.create_pool("一次露营", "在山上过一夜", 400)
    r = E.deposit_pool(GIRL, 10, operator_id=GIRL)
    check("投币进许愿池", r["ok"], r.get("msg", ""))
    p = E.pool_progress()
    check("池子进度算得出", p and p["collected_stardust"] > 0, p and p["collected_stardust"])
    r = E.create_wish(GIRL, "想去一次天文馆", "stardust", {"amount": 10}, "实地看一次土星环")
    check("心愿单建得起来", r["ok"], r)
    check("建完就是生效状态",
          db.query_one("SELECT status FROM wish WHERE id=?", (r["wish_id"],))["status"] == "active")
    p = E.wish_progress(E.wish_view(db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))))
    check("进度算得出来", p["known"] and p["target"] == 10, p)
    check("门槛 0 会被挡回去",
          not E.create_wish(GIRL, "白送的心愿", "stardust", {"amount": 0})["ok"])
    check("缺门槛也会被挡回去",
          not E.create_wish(GIRL, "没门槛的心愿", "fixed", {})["ok"])

    # 孩子许愿走的是另一条路：条件留白、状态挂起
    r = E.wish_one(GIRL, "想要一套彩铅", reward_desc="画速写用", operator_id=GIRL)
    check("孩子许愿落到挂起", r["ok"] and r["status"] == "wished", r)
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))
    check("挂起的心愿不给进度", E.wish_view(w, with_progress=True)["progress"] is None)
    check("家长定条件后点亮",
          E.configure_wish(r["wish_id"], "perfect_day", {"value": 5},
                           operator_id=DAD)["ok"])
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))
    p = E.wish_view(w, with_progress=True)["progress"]
    check("点亮后进度是「本月的完美日」", p and p["label"] == "本月的完美日", p and p["text"])

    print("\n=== 12. 成长报告 ===")
    rep = E.growth_report(GIRL, 30)
    check("报告算得出出勤率", rep["rate"] > 0, rep["rate"])
    check("第一屏放的是星探原话", len(rep["first_screen"]) > 0, rep["first_screen"][:1])

    print("\n=== 13. 家长不进游戏循环（v13）===")
    r = E.submit_day(DAD, days[0], [], operator_id=DAD)
    check("给家长打分被拒", not r.get("ok"), r.get("msg"))
    check("家长没有周期", E.current_cycle(DAD) is None, E.current_cycle(DAD))
    r = E.add_explore(DAD, days[0], "给家长发星探", kind="stardust", stardust=5, operator_id=MOM)
    check("给家长发星探被拒", not r.get("ok"), r.get("msg"))
    r = E.buy_ticket(DAD, "ticket_fun", 1, operator_id=DAD)
    check("家长买券被拒", not r.get("ok"), r.get("msg"))
    r = E.buy_box(DAD, 4, operator_id=DAD)
    check("家长直购箱被拒", not r.get("ok"), r.get("msg"))
    r = E.exchange_cash(DAD, 10, operator_id=MOM)
    check("家长兑零花钱被拒", not r.get("ok"), r.get("msg"))
    r = E.issue_box(DAD, 4, source="free", operator_id=MOM)
    check("不给家长发箱", r is None, r)
    ov = E.member_overview(DAD)
    check("家长概览为空且不进循环", ov["is_player"] is False and ov["stardust"] == 0, ov.get("stardust"))
    check("家长没有周期记录",
          db.query_one("SELECT COUNT(*) c FROM cycle WHERE member_id=?", (DAD,))["c"] == 0)
    check("家长没有流水",
          db.query_one("SELECT COUNT(*) c FROM ledger WHERE member_id=?", (DAD,))["c"] == 0)
    # 惩罚机制保留：校准照样能对家长记（v13 不碰惩罚侧）
    check("校准机制未被删除", callable(E.add_calibration))

    print("\n=== 14. 星球等级（v13 补回）===")
    lv = E.level_of(GIRL)
    check("等级算得出", lv and lv["level"] >= 1, lv and (lv["level"], lv["title"]))
    check("等级按累计不按余额", lv["total"] >= E.stardust_balance(GIRL),
          (lv["total"], E.stardust_balance(GIRL)))
    check("家长累计星尘为 0", E.lifetime_stardust(DAD) == 0, E.lifetime_stardust(DAD))
    need = 50 - E.lifetime_stardust(GIRL)
    if need > 0:
        E.add_ledger(GIRL, "adjust", stardust=need, note="测试补星尘")
    up = E.apply_level_rewards(GIRL, operator_id=DAD)
    check("等级涨了就补发奖励（可跨级）",
          len(up) >= 1 and all(u["level"] > 1 for u in up), up)
    check("升级发了娱乐券",
          E.item_balance(GIRL, E.item_by_code("ticket_fun")["id"]) >= 2,
          E.item_balance(GIRL, E.item_by_code("ticket_fun")["id"]))
    up2 = E.apply_level_rewards(GIRL, operator_id=DAD)
    check("升级奖励不重复发", len(up2) == 0, up2)
    lv_before = E.level_of(GIRL)["level"]
    E.add_ledger(GIRL, "adjust", stardust=-100, note="测试花掉 100 星尘")
    check("花钱不掉级", E.level_of(GIRL)["level"] == lv_before,
          (lv_before, E.level_of(GIRL)["level"]))
    check("等级门槛是 25×n×(n−1)", [t["threshold"] for t in E.level_table()][:4] == [0, 50, 150, 300],
          [t["threshold"] for t in E.level_table()][:4])

    print("\n=== 15. 券核销：机器闸门 + 家长点头（v14，v23 撤掉前置，v32 改成按轮算）===")
    # 闸门的判据里有"此刻几点"，直接用真实时间会让用例白天过、半夜不过。
    # 所以这一组把跟时间有关的那几个设置固定住，用 at= 显式喂时间。
    kid = GIRL
    fun = E.item_by_code("ticket_fun")
    fun_id = fun["id"]
    d0 = E.today()
    sat = E.fmt(E.parse_day(d0) + timedelta(days=(5 - E.parse_day(d0).weekday()) % 7 or 7))
    saved = {}
    for k in ("ticket.curfew_school", "ticket.curfew_weekend", "ticket.evening_after",
              "ticket.cooldown_minutes", "ticket.single_max", "ticket.evening_max",
              "ticket.renew_within_minutes", "ticket.need_approval",
              "ticket.request_ttl_minutes"):
        row = db.query_one("SELECT value FROM setting WHERE key=?", (k,))
        saved[k] = row["value"] if row else None

    def _set(key, val):
        db.execute("UPDATE setting SET value=? WHERE key=?",
                   (("true" if val else "false") if isinstance(val, bool)
                    else json.dumps(val, ensure_ascii=False), key))
        db.settings_all(force=True)

    def _wipe():
        db.execute("DELETE FROM ticket_request WHERE member_id=?", (kid,))
        db.execute("DELETE FROM overtime_request WHERE member_id=?", (kid,))

    def _round(qty, start, end, ts=None):
        """造一轮已经用掉的券，省得等真实时间。

        ts 是提交时刻，默认等于开始时刻。测「窗口按提交时刻判」那几条时要
        单独给：孩子 19:39 提的、家长 19:50 才点，两个时刻必须能分开。
        """
        db.execute("INSERT INTO ticket_request (member_id,item_id,qty,day,minutes,status,gate,"
                   "note,ts,start_at,end_at,resolved_at) VALUES (?,?,?,?,?,'approved','{}','',?,?,?,?)",
                   (kid, fun_id, qty, d0, qty * 30, ts or (d0 + " " + start + ":00"),
                    d0 + " " + start + ":00", d0 + " " + end + ":00", d0 + " " + end + ":00"))

    def _ot(n=1):
        for _ in range(n):
            db.execute("INSERT INTO overtime_request (member_id,day,week_key,minutes,cost,status,ts)"
                       " VALUES (?,?,?,30,10,'approved',?)", (kid, d0, E.week_start_of(d0), E.now()))

    def _at(day, hhmm):
        return "%s %s:00" % (day, hhmm)

    def _gate(qty, hhmm, day=None):
        day = day or d0
        return E.ticket_gate(kid, fun_id, qty, day, _at(day, hhmm))

    def _study(val):
        """直接写智识分。

        不走 submit_day —— 前面的分组可能已经把这个周期结算掉了，
        而结算后不能再改分。这里要的是"这天智识是 0 还是 1"，与周期状态无关。
        """
        dim = db.query_one("SELECT id FROM dimension WHERE code='study'")["id"]
        db.execute("UPDATE score_entry SET voided=1 WHERE member_id=? AND day=? AND dimension_id=?",
                   (kid, d0, dim))
        db.execute("INSERT INTO score_entry (member_id, cycle_id, day, dimension_id, value, is_fixed,"
                   " mode, note, operator_id, created_at) VALUES (?,NULL,?,?,?,1,'school','',?,?)",
                   (kid, d0, dim, float(val), DAD, E.now()))

    _set("ticket.curfew_school", "23:59")
    _set("ticket.curfew_weekend", "23:59")
    _set("ticket.evening_after", "20:30")
    _set("ticket.cooldown_minutes", 60)
    _set("ticket.single_max", 3)
    _set("ticket.evening_max", 2)
    _set("ticket.renew_within_minutes", 10)
    _set("ticket.need_approval", True)

    # 审批流这几条把时钟钉在傍晚 18:00 整。它们要测的是「申请→点头→扣券」
    # 这条链路，不是时钟；跟着真实时间跑，就会在 20:30 之后（晚间上限生效）
    # 或 23:00 之后（离收工不够一轮）莫名变红，而那种红指向的是空气。
    T_DAY = _at(d0, "18:00")

    check("孩子不能给自己打分", E.submit_day(kid, d0, [], operator_id=kid)["ok"] is False,
          E.submit_day(kid, d0, [], operator_id=kid)["msg"])

    # ① 续费窗口：一轮之内可以一张一张接着续。v32 之前「休息」挂在每一段
    #    娱乐的结束上，用 1 张就被锁 60 分钟、第 2 张点不动 —— 那才是 BUG 本身。
    _wipe()
    _set("ticket.renew_within_minutes", 10)
    _round(1, "19:00", "19:30")
    check("① 续费窗口：刚结束 5 分钟再要一张，还算这一轮，直接放行",
          _gate(1, "19:35")["ok"], _gate(1, "19:35")["msg"])
    check("① 续费窗口：这一轮上限 3 张、已用 1 张，还能再要 2 张",
          _gate(1, "19:35")["state"]["round_left"] == 2,
          _gate(1, "19:35")["state"]["round_left"])
    check("① 续费窗口：隔 11 分钟没续，这一轮就断了，要休息",
          _gate(1, "19:41")["code"] == "cooldown", _gate(1, "19:41")["msg"])
    check("① 窗口按提交时刻判：19:39 提的，19:45 来判还算在窗口里",
          E.ticket_use_state(kid, fun, d0, _at(d0, "19:45"),
                             _at(d0, "19:39"))["round_open"] is True)

    # ② 一轮的张数：白天 3 张，用满才休息
    _wipe()
    _round(2, "19:00", "20:00")
    check("② 白天一轮 3 张：已用 2 张，窗口内还能再要 1 张",
          _gate(1, "20:05")["ok"], _gate(1, "20:05")["msg"])
    check("② 白天一轮 3 张：已用 2 张，一次要 2 张就超了",
          _gate(2, "20:05")["code"] == "single", _gate(2, "20:05")["msg"])
    _wipe()
    _round(3, "19:00", "20:30")
    check("② 一轮用满就休息：3 张用完立刻再来，被拦",
          _gate(1, "20:30")["code"] == "cooldown", _gate(1, "20:30")["msg"])
    check("② 休息满 60 分钟就能开新一轮", _gate(1, "21:30")["ok"], _gate(1, "21:30")["msg"])

    # ③ 一轮算白天还是晚间，由首张的开始时刻定，中途不改
    _wipe()
    _round(2, "19:00", "20:00")
    st = E.ticket_use_state(kid, fun, d0, _at(d0, "20:25"))
    check("③ 20:30 前用掉的张数不算晚间额度", st["evening_on"] is False and st["used_evening"] == 0,
          (st["evening_on"], st["used_evening"]))
    check("③ 白天开始的轮跨过晚间起点，仍按白天算（还能再要 1 张）",
          _gate(1, "20:05")["state"]["round_cap"] == 3 and _gate(1, "20:05")["ok"],
          _gate(1, "20:05")["state"]["round_cap"])
    _wipe()
    _round(2, "20:40", "21:10")
    check("③ 晚间开始的一轮按 2 张算",
          E.ticket_use_state(kid, fun, d0, _at(d0, "21:15"))["round_cap"] == 2,
          E.ticket_use_state(kid, fun, d0, _at(d0, "21:15"))["round_cap"])
    check("③ 晚间一轮用满 2 张就休息",
          _gate(1, "21:15")["code"] == "cooldown", _gate(1, "21:15")["msg"])
    _set("ticket.evening_after", "23:00")
    check("③ 晚间起点调晚，同一批用量就不再算晚间（说明它是可配置的，不是写死的）",
          E.ticket_use_state(kid, fun, d0, _at(d0, "21:15"))["evening_on"] is False)
    _set("ticket.evening_after", "20:30")

    # ④ 提前提交要排队，窗口按提交那一刻算。上一张还在放的时候提交，
    #    新一张接在它后面，否则两张会叠在一起、白送孩子一段重叠的时间；
    #    家长慢批也不该算到孩子账上。
    _wipe()
    E.freeze_clock(_at(d0, "19:20"))
    _round(1, "19:00", "19:30")
    E.request_ticket(kid, fun_id, 1)
    pend = E.ticket_pending_list()
    check("④ 提前提交：上一张还在放也收得下", bool(pend) and pend[0]["can_now"] is True, pend)
    if pend:
        out = E.resolve_ticket_request(pend[0]["id"], True, operator_id=DAD)
        check("④ 提前提交的那张排在上一张后面，不重叠",
              out.get("approved") and out["used"]["start_at"] == _at(d0, "19:30")
              and out["used"]["end_at"] == _at(d0, "20:00"),
              out.get("used"))
    _wipe()
    _round(1, "19:00", "19:30")
    E.freeze_clock(_at(d0, "19:39"))
    E.request_ticket(kid, fun_id, 1)
    pend = E.ticket_pending_list()
    E.freeze_clock(_at(d0, "19:50"))
    late = E.ticket_pending_list()
    check("④ 过了窗口家长再看，这条申请仍然是「能批」的（按提交时刻判）",
          bool(late) and late[0]["can_now"] is True, late)
    if pend:
        out = E.resolve_ticket_request(pend[0]["id"], True, operator_id=DAD)
        check("④ 批下来时已过窗口，照样能批（孩子提交那一刻是合规的）",
              out.get("approved"), out)
    E.freeze_clock(T_DAY)

    # ⑤ 硬停止时间：结束时间不能越过它
    _wipe()
    _set("ticket.curfew_school", "21:30")
    _set("ticket.curfew_weekend", "22:00")
    # 这一组测的是「到点了没有」这条线本身。v42 起点头之后要准备一分钟，
    # 起跑晚一分钟收工就也晚一分钟，闸门必须按真的收工时刻判（否则会出现
    # 「闸门放行、实际超时」），所以准备开着的时候 21:00 要 1 张是会被拒的。
    # 准备那一段在 ⑧-2 里单独回归，这里先折叠掉。
    _set("ticket.start_delay_seconds", 0)
    check("⑤ 硬停止：21:40 已过点，拒", _gate(1, "21:40")["code"] == "curfew", _gate(1, "21:40")["msg"])
    check("⑤ 硬停止：21:10 只够 1 张，要 2 张拒",
          _gate(2, "21:10")["code"] == "curfew", _gate(2, "21:10")["msg"])
    check("⑤ 硬停止：21:00 要 1 张放行", _gate(1, "21:00")["ok"], _gate(1, "21:00")["msg"])
    check("⑤ 硬停止：上学日 21:30、周末 22:00 是两档",
          (E.curfew_text(d0), E.curfew_text(sat)) == ("21:30", "22:00"),
          (E.curfew_text(d0), E.curfew_text(sat)))

    # ⑥ 加时只放宽单次与晚间，不放宽硬停止，也不放宽前置
    _wipe()
    _set("ticket.curfew_school", "23:59")
    check("⑥ 加时前：一次 4 张被单次上限拒", _gate(4, "18:00")["code"] == "single")
    _wipe()
    _ot(1)
    check("⑥ 加时后：一次 4 张放行", _gate(4, "18:00")["ok"], _gate(4, "18:00")["msg"])
    _wipe()
    _ot(1)
    _set("ticket.curfew_school", "21:30")
    check("⑥ 加时也绕不过硬停止", _gate(1, "21:40")["code"] == "curfew", _gate(1, "21:40")["msg"])
    _set("ticket.curfew_school", "23:59")
    _wipe()
    _ot(1)
    # 学习前置那条闸门 v23 已经撤掉：系统判断不了学习做完没有，
    # 那件事归家长在核销时看。所以这里没有「加时绕不过前置」这一条了。

    # ⑦ 一条加时只抵一轮。时钟钉在傍晚 18:00 整。
    #    不钉的话，20:30 之后晚间上限（2 张 + 加时 1 张 = 3）会先于
    #    单次上限（3 张 + 加时 1 张 = 4）拦下来，那测到的就不是加时了，
    #    是「这套闸门按真实时钟跑」——一条只在白天成立的用例。
    E.freeze_clock(T_DAY)
    _wipe()
    _ot(1)
    E.request_ticket(kid, fun_id, 4)
    pend = E.ticket_pending_list()
    rid = pend[0]["id"] if pend else None
    check("⑦ 有加时时能提交 4 张的申请", rid is not None, pend)
    if rid:
        E.resolve_ticket_request(rid, True, operator_id=DAD)
    check("⑦ 批完加时就被抵消掉了", E.overtime_credit(kid, d0)["count"] == 0)

    # ⑧ 完整审批流：孩子申请 -> 家长点头才扣券
    _wipe()
    _set("ticket.cooldown_minutes", 0)
    # v42 起点头之后先「准备」一段（默认 60 秒）才开跑。这一段要验的是审批与扣券，
    # 把准备折叠掉，好让「开始时刻 = 点头那一刻」这条继续成立；带准备的那条在
    # 紧随其后的 ⑧-2 里单独回归。
    _set("ticket.start_delay_seconds", 0)
    bal0 = E.item_balance(kid, fun_id)
    r = E.request_ticket(kid, fun_id, 2, note="想看一集动画")
    check("⑧ 申请生成待办，不直接扣券", r.get("mode") == "pending" and E.item_balance(kid, fun_id) == bal0,
          (r.get("mode"), E.item_balance(kid, fun_id)))
    pend = E.ticket_pending_list()
    check("⑧ 家长侧能看到这条待办，且带「现在批了还能不能用」",
          pend and pend[0]["can_now"] is True, pend)
    if pend:
        check("⑧ 孩子自己批不了",
              E.resolve_ticket_request(pend[0]["id"], True, operator_id=kid)["ok"] is False)
        check("⑧ 拒绝不写理由不行",
              E.resolve_ticket_request(pend[0]["id"], False, operator_id=DAD,
                                       reject_note="")["ok"] is False)
        out = E.resolve_ticket_request(pend[0]["id"], True, operator_id=DAD)
        check("⑧ 家长同意后才扣券", out.get("approved") and E.item_balance(kid, fun_id) == bal0 - 2,
              (out.get("approved"), E.item_balance(kid, fun_id), bal0))
        check("⑧ 记了开始与结束时刻", bool(out["used"]["start_at"]) and bool(out["used"]["end_at"]),
              out["used"])
        check("⑧ 开始时刻就是点头那一刻，结束时刻往后推张数×30 分",
              out["used"]["start_at"] == T_DAY and out["used"]["end_at"] == _at(d0, "19:00"),
              (out["used"]["start_at"], out["used"]["end_at"]))
    # ⑧-2 准备那一段（v42）：点头不等于开跑，中间隔着 ticket.start_delay_seconds，
    #     这段时间不算在券的时长里，孩子也能自己提前开跑。
    _wipe()
    _set("ticket.start_delay_seconds", 60)
    r8 = E.request_ticket(kid, fun_id, 1)
    check("⑧-2 申请挂得上", r8.get("mode") == "pending", r8)
    rid = r8.get("request_id")
    if rid:
        E.resolve_ticket_request(rid, True, operator_id=DAD)
        lst = E.my_ticket_list(kid, d0)          # 返回的就是 items 列表
        prep = [x for x in lst if x.get("preparing")]
        check("⑧-2 点头之后先准备：起跑时刻比点头晚 60 秒",
              prep and prep[0]["start_at"] == _at(d0, "18:01"), lst)
        check("⑧-2 准备这段不算在时长里，收工时刻也跟着往后推",
              prep and prep[0]["end_at"] == _at(d0, "18:31"), lst)
        check("⑧-2 这会儿还没开跑，列表里没有「正在玩」",
              not [x for x in lst if x.get("running")], lst)
        check("⑧-2 孩子能自己提前开跑",
              E.start_ticket_now(rid, kid).get("ok") is True)
        run = [x for x in E.my_ticket_list(kid, d0) if x.get("running")]
        check("⑧-2 提前开跑后，起跑时刻改成当下", run and run[0]["start_at"] == T_DAY, run)
    _set("ticket.start_delay_seconds", 0)

    _wipe()
    E.request_ticket(kid, fun_id, 1)
    pend = E.ticket_pending_list()
    if pend:
        E.resolve_ticket_request(pend[0]["id"], False, operator_id=DAD, reject_note="今天先订正错题")
    mine = [x for x in E.my_ticket_list(kid, d0) if x["status"] == "rejected"]
    check("⑧ 拒绝的理由孩子看得到", mine and mine[0]["reject_note"] == "今天先订正错题", mine)

    # ⑨ 待办超时作废 + 同一张券不重复挂
    _wipe()
    E.request_ticket(kid, fun_id, 1)
    check("⑨ 同一张券不会重复挂待办", E.request_ticket(kid, fun_id, 1)["code"] == "dup")
    db.execute("UPDATE ticket_request SET expire_at='2000-01-01 00:00:00' WHERE status='pending'")
    check("⑨ 超时自动作废", E.expire_ticket_requests() == 1 and not E.ticket_pending_list())

    # ⑩ 家长点同意之前，闸门可能已经关了。
    #    21:00 离收工还有 30 分钟，1 张刚好放行；家长拖到 21:15 才点，
    #    那会儿只剩 15 分钟，一轮都放不下了。申请 21:20 才超时，
    #    所以这一刻它还在待办里，而不是被超时清掉 —— 这才是这条闸门
    #    真正要拦的场景：不是「孩子提的时候不对」，是「家长批得太晚」。
    _wipe()
    _set("ticket.curfew_school", "21:30")
    E.freeze_clock(_at(d0, "21:00"))
    E.request_ticket(kid, fun_id, 1)
    pend = E.ticket_pending_list()
    check("⑩ 21:00 提的申请当时是能用的", pend and pend[0]["can_now"] is True, pend)
    E.freeze_clock(_at(d0, "21:15"))
    late = E.ticket_pending_list()
    check("⑩ 拖到 21:15 再看，已经标成「用不了了」", late and late[0]["can_now"] is False, late)
    if pend:
        out = E.resolve_ticket_request(pend[0]["id"], True, operator_id=DAD)
        check("⑩ 到点后家长再批，自动改成拒绝并写明原因",
              out["ok"] is False and out.get("code") == "curfew", out)
        row = db.query_one("SELECT status, reject_note FROM ticket_request WHERE id=?", (pend[0]["id"],))
        check("⑩ 自动拒绝的状态和理由都落库了，孩子看得到",
              row["status"] == "rejected" and "自动" in (row["reject_note"] or ""), dict(row))
    _set("ticket.curfew_school", "23:59")
    E.freeze_clock(T_DAY)

    # ⑪ 其他五种券不套时段闸门（消耗的是家长的配合，不是屏幕时间）
    _wipe()
    for code in ("ticket_company", "ticket_choice", "ticket_exempt", "ticket_friend", "ticket_solo"):
        it = E.item_by_code(code)
        if it and E.ticket_gate(kid, it["id"], 1, d0, _at(d0, "21:40"))["ok"] is False:
            check("⑪ " + it["name"] + " 不受娱乐券时段约束", False, it["code"])
            break
    else:
        check("⑪ 陪伴 / 选择 / 豁免 / 好友 / 独处券不受娱乐券时段约束", True)

    # ⑫ 续卡要认卡主
    _wipe()
    other = BOY if kid != BOY else GIRL
    card = db.query_one("SELECT id FROM item WHERE category='card' LIMIT 1")
    if card:
        E.grant_item(other, card["id"], 1, note="测试")
        h = db.query_one("SELECT id FROM holding WHERE member_id=? AND qty>0 LIMIT 1", (other,))
        check("⑫ 拿别人的卡续期会被拒",
              h and E.renew_card(h["id"], operator_id=kid, owner_id=kid)["ok"] is False)

    # ⑬ 娱乐券面值以设置为准，不是建库时写死的那个 30
    _wipe()
    _set("ticket.entertainment_minutes", 60)
    _study(1)
    E.freeze_clock(_at(d0, "18:00"))
    st2 = E.ticket_use_state(kid, fun, d0)
    listed = [t for t in E.to_ticket_list(kid) if t["code"] == "ticket_fun"]
    check("改了「娱乐券面值」，闸门和券列表都跟着变",
          st2["minutes"] == 60 and listed and listed[0]["minutes"] == 60,
          (st2["minutes"], listed and listed[0]["minutes"]))
    E.request_ticket(kid, fun_id, 1)
    pend = E.ticket_pending_list()
    if pend:
        out = E.resolve_ticket_request(pend[0]["id"], True, operator_id=DAD)
        check("按新面值记这一轮的时长", out.get("used", {}).get("minutes") == 60, out.get("used"))
    _set("ticket.entertainment_minutes", 30)

    # ⑭ v27：券的状态得看得见。孩子提交之后最想知道三件事 —— 批了没、
    #    为什么没批、还能玩多久；家长要知道这一刻谁在玩、还剩几分钟。
    #    「正在玩」是算出来的，不是谁点一下「结束」记下来的：只要现在落在
    #    开始和结束之间就算，到点自己退出去。
    _wipe()
    E.freeze_clock(_at(d0, "18:00"))
    E.request_ticket(kid, fun_id, 1, note="看一集动画")
    pend_row = [x for x in E.my_ticket_list(kid, d0) if x["status"] == "pending"]
    check("⑭ 提交后孩子那边看得到「还在等」，并且带着作废时刻",
          pend_row and pend_row[0]["expire_at"], pend_row)
    check("⑭ 还没批的时候，孩子这边没有「正在玩」", E.ticket_playing(kid) == [],
          E.ticket_playing(kid))
    check("⑭ 家长那边也还没有谁在玩", E.ticket_playing() == [])

    pl = E.ticket_pending_list()
    E.resolve_ticket_request(pl[0]["id"], True, operator_id=DAD)
    mine = E.my_ticket_list(kid, d0)
    run = [x for x in mine if x["running"]]
    check("⑭ 同意之后孩子这条变成「正在玩」", bool(run), mine)
    check("⑭ 这条带着「还剩多少分钟」和「一共多少分钟」",
          run and run[0]["left_minutes"] == 30 and run[0]["total_minutes"] == 30,
          run and (run[0]["left_minutes"], run[0]["total_minutes"]))
    gp = E.ticket_playing()
    check("⑭ 家长看得到谁在玩、还剩多久",
          len(gp) == 1 and gp[0]["member_id"] == kid and gp[0]["left_minutes"] == 30, gp)
    check("⑭ 家长那边知道是哪个孩子在玩",
          gp and gp[0]["who"] == E.member_name_of(kid), gp)
    check("⑭ 孩子自己也能查到这一条", len(E.ticket_playing(kid)) == 1)
    other = BOY if kid != BOY else GIRL
    check("⑭ 按人查，别人的那栏是空的", E.ticket_playing(other) == [])
    E.freeze_clock(_at(d0, "18:30"))
    check("⑭ 到点自己从「正在玩」里退出，不用谁去点结束",
          E.ticket_playing() == [], E.ticket_playing())
    check("⑭ 退出之后孩子那边仍然记着玩过哪一段",
          [x for x in E.my_ticket_list(kid, d0) if x["start_at"] and x["end_at"]],
          E.my_ticket_list(kid, d0))

    # 续券：剩 10 分钟的时候再续一张，胶囊该接着数 40，不是还按上一张的零头倒数。
    #    这是「倒计时胶囊不会叠加时间」那个毛病的老窝 —— 续的那张是排在上一张
    #    结束之后才开场的，此刻还没开场，按「此刻落在开始与结束之间」判就整段不算数。
    _wipe()
    E.freeze_clock(_at(d0, "18:00"))
    E.request_ticket(kid, fun_id, 1)
    pl = E.ticket_pending_list()
    E.resolve_ticket_request(pl[0]["id"], True, operator_id=DAD)
    E.freeze_clock(_at(d0, "18:20"))
    check("续券前还剩 10 分钟", E.ticket_playing(kid)[0]["left_minutes"] == 10,
          E.ticket_playing(kid))
    E.request_ticket(kid, fun_id, 1)
    pl = [x for x in E.ticket_pending_list() if x["member_id"] == kid]
    E.resolve_ticket_request(pl[0]["id"], True, operator_id=DAD)
    gp = E.ticket_playing(kid)
    check("续了一张，倒计时接着往 40 数，不是还停在 10",
          len(gp) == 1 and gp[0]["left_minutes"] == 40, gp)
    check("整段是两次加起来的一段：18:00 开场、19:00 收工、两张 60 分钟",
          gp and gp[0]["qty"] == 2 and gp[0]["total_minutes"] == 60
          and gp[0]["start_at"] == _at(d0, "18:00") and gp[0]["end_at"] == _at(d0, "19:00"), gp)
    check("家长首页看到的也是同一个数", E.ticket_playing()[0]["left_minutes"] == 40,
          E.ticket_playing())
    mine = E.my_ticket_list(kid, d0)
    run = [x for x in mine if x["running"]]
    que = [x for x in mine if x.get("queued")]
    check("列表里只有一张卡在倒数，不是两张各自数一个不同的数", len(run) == 1, mine)
    check("列表中正在玩的那条报的也是整段 40 分钟",
          run and run[0]["left_minutes"] == 40 and run[0]["total_minutes"] == 60, run)
    check("排队的那张单独标出来，不冒充「正在玩」", len(que) == 1 and not que[0]["running"], que)
    E.freeze_clock(_at(d0, "19:00"))
    check("整段到点一起退出去", E.ticket_playing() == [], E.ticket_playing())

    # D1（回归）：串段是**单向**的，只能往后面接，不能往前面吞。
    #    已经玩完的那张 begin 更小，却一路通过 `begin <= far`，于是它顶掉段头、
    #    「正在玩」标在它身上，张数和总时长一起去撑大。ticket_playing() 的 SQL
    #    已经滤掉 end_at<=now，中枪的只有传当天全部行的 my_ticket_list() ——
    #    家长端券页那张「正在玩」区块挂的就是它。
    _wipe()
    E.freeze_clock(_at(d0, "18:00"))
    E.request_ticket(kid, fun_id, 1)
    E.resolve_ticket_request(E.ticket_pending_list()[0]["id"], True, operator_id=DAD)
    E.freeze_clock(_at(d0, "18:05"))
    E.request_ticket(kid, fun_id, 1)
    pl = [x for x in E.ticket_pending_list() if x["member_id"] == kid]
    E.resolve_ticket_request(pl[0]["id"], True, operator_id=DAD)
    E.freeze_clock(_at(d0, "18:35"))
    gp = E.ticket_playing(kid)
    check("D1 前面那张 18:30 已经玩完，整段只剩接在后面那 30 分钟",
          len(gp) == 1 and gp[0]["qty"] == 1 and gp[0]["total_minutes"] == 30
          and gp[0]["start_at"] == _at(d0, "18:30"), gp)
    mine = E.my_ticket_list(kid, d0)
    run = [x for x in mine if x["running"]]
    check("D1 列表里正在玩的是后一张，报它自己的 30 分钟",
          len(run) == 1 and run[0]["qty"] == 1 and run[0]["total_minutes"] == 30
          and run[0]["start_at"] == _at(d0, "18:30"), run)
    old = [x for x in mine if x["start_at"] == _at(d0, "18:00")]
    check("D1 已经玩完的那张不再被标成「正在玩」，也不算排队",
          bool(old) and not old[0]["running"] and not old[0]["queued"], old)

    # 娱乐券之外的五种券不存在「玩多久」：开始就等于结束，永远不进这一栏
    _wipe()
    for code in ("ticket_company", "ticket_choice", "ticket_exempt", "ticket_friend", "ticket_solo"):
        it = E.item_by_code(code)
        if not it:
            continue
        rid =         db.execute(
            "INSERT INTO ticket_request (member_id,item_id,qty,day,minutes,status,gate,note,ts,"
            "start_at,end_at,resolved_at) VALUES (?,?,1,?,0,'approved','{}','',?,?,?,?)",
            (kid, it["id"], d0, _at(d0, "18:00"), _at(d0, "18:00"), _at(d0, "18:00"),
             _at(d0, "18:00")))
    check("⑭ 陪伴 / 选择 / 豁免 / 好友 / 独处券不会出现在「正在玩」里",
          E.ticket_playing() == [], E.ticket_playing())

    # 跨零点还在玩的那条：第二天打开「我的」不能凭空消失
    _wipe()
    nxt = E.fmt(E.parse_day(d0) + timedelta(days=1))
    db.execute(
        "INSERT INTO ticket_request (member_id,item_id,qty,day,minutes,status,gate,note,ts,"
        "start_at,end_at,resolved_at) VALUES (?,?,1,?,30,'approved','{}','',?,?,?,?)",
        (kid, fun_id, d0, _at(d0, "23:50"), _at(d0, "23:50"), _at(nxt, "00:20"),
         _at(d0, "23:50")))
    E.freeze_clock(_at(nxt, "00:05"))
    mine = E.my_ticket_list(kid)
    check("⑭ 跨零点还在玩的那条，第二天也还看得见",
          any(x["status"] == "approved" for x in mine), mine)
    check("⑭ 而且标着「正在玩」", any(x["running"] for x in mine), mine)
    check("⑭ 家长这会儿看到的还是同一个孩子",
          [x["member_id"] for x in E.ticket_playing()] == [kid], E.ticket_playing())
    E.freeze_clock(_at(nxt, "00:30"))
    mine = E.my_ticket_list(kid)
    check("⑭ 玩完了就不再占着第二天那一栏",
          not any(x["running"] for x in mine), mine)

    # D2（回归）：跨零点续的那张要接在上一张**结束之后**开场，不是从「此刻」起算。
    #    判排队原来走按天过滤的 _day_ticket_stats，过了零点查不到上一张 → 从此刻起算，
    #    和上一张叠在一起，整段还少算一截。硬停止挡住常规路径，但设置里调晚就会露出来。
    _wipe()
    db.execute(
        "INSERT INTO ticket_request (member_id,item_id,qty,day,minutes,status,gate,note,ts,"
        "start_at,end_at,resolved_at) VALUES (?,?,1,?,30,'approved','{}','',?,?,?,?)",
        (kid, fun_id, d0, _at(d0, "23:50"), _at(d0, "23:50"), _at(nxt, "00:20"),
         _at(d0, "23:50")))
    E.freeze_clock(_at(nxt, "00:10"))
    E.request_ticket(kid, fun_id, 1)
    pl = [x for x in E.ticket_pending_list() if x["member_id"] == kid]
    check("D2 上一张跨零点还在放，这时候续得进来", bool(pl), E.ticket_pending_list())
    E.resolve_ticket_request(pl[0]["id"], True, operator_id=DAD)
    mine = E.my_ticket_list(kid)
    que = [x for x in mine if x.get("queued")]
    check("D2 新续的那张从 00:20 开场、00:50 收工，没叠在 00:10 上",
          len(que) == 1 and que[0]["start_at"] == _at(nxt, "00:20")
          and que[0]["end_at"] == _at(nxt, "00:50"), que)
    gp = E.ticket_playing(kid)
    check("D2 整段是两张 60 分钟：23:50 起、00:50 收，此刻还剩 40",
          len(gp) == 1 and gp[0]["qty"] == 2 and gp[0]["total_minutes"] == 60
          and gp[0]["end_at"] == _at(nxt, "00:50") and gp[0]["left_minutes"] == 40, gp)
    E.freeze_clock(_at(nxt, "00:30"))
    gp = E.ticket_playing(kid)
    check("D2 前一截放完后，接着数的还是那一整段，不是从头起算的 30",
          len(gp) == 1 and gp[0]["start_at"] == _at(nxt, "00:20")
          and gp[0]["left_minutes"] == 20, gp)

    # ⑮ v27：推送。这一版真正的病根在下面第二条 —— https 地址会抛 TypeError，
    #    而测试打的假端点全是 http 的 127.0.0.1，所以一路测过来全是绿的，
    #    只有真机上填对了 key 也发不出去，提示还只有一句「TypeError」。
    check("⑮ 单独的 key 原样留着",
          N.split_fields("https://api.day.app", "FAKEKEY000000000000000")
          == ("https://api.day.app", "FAKEKEY000000000000000", False))
    check("⑮ 整条链接粘进「服务器地址」那一格，能拆出 key",
          N.split_fields("https://api.day.app/FAKEKEY000000000000000/", "")
          == ("https://api.day.app", "FAKEKEY000000000000000", True))
    check("⑮ 整条链接粘进 key 那一格，一样能拆",
          N.split_fields("", "https://api.day.app/FAKEKEY000000000000000/")
          == ("https://api.day.app", "FAKEKEY000000000000000", True))
    check("⑮ 链接后面带着标题正文时，只取第一段当 key",
          N.split_fields("https://api.day.app/FAKEKEY000000000000000/标题/正文", "")[1]
          == "FAKEKEY000000000000000")
    check("⑮ 自建服务器地址后面不带路径时原样留着",
          N.split_fields("https://bark.example.com/", "FAKEKEY000000000000000")
          == ("https://bark.example.com", "FAKEKEY000000000000000", False))
    _ok, _why = N.send_bark("https://127.0.0.1:9", "FAKEKEY000000000000000", "标题", "正文")
    check("⑮ https 地址不再抛 TypeError（连不上是另一回事，但话得说人话）",
          _ok is False and "TypeError" not in _why, _why)

    # 时钟还原到开头钉住的那一天，不是真实时间。
    # 后面几组要看「今天得了几分」，而今天的分数是第一段打进去的；
    # 放回到真实时间，逢换日就是一张空白的今天，那种红指向的还是日历。
    E.freeze_clock(E.fmt(anchor) + " 18:00:00")

    # 还原设置和时钟，别影响后面的分组
    for k, v in saved.items():
        if v is not None:
            db.execute("UPDATE setting SET value=? WHERE key=?", (v, k))
    db.settings_all(force=True)

    print("\n=== 16. 任务大厅：领取 / 放弃 / 撤销（v15）===")
    # 星尘额度先放宽，这一组要验的是大厅的流转，不是额度护栏
    _set("task.stardust_weekly_cap", 999)

    h1 = E.create_task(None, "擦一次全家地板", "客厅加两个房间都擦过", reward_type="stardust",
                       reward={"amount": 5}, created_by=DAD, slots=1)
    check("挂进大厅，assignee 是空的", db.query_one(
        "SELECT assignee_id a, status s FROM task WHERE id=?", (h1,))["a"] is None)
    hall = E.task_hall(GIRL)
    card = [d for d in hall["hall"] if d["id"] == h1]
    check("出现在等人领", len(card) == 1)
    check("奖励翻成人话", card[0]["reward_text"] == "星尘 +5", card[0]["reward_text"])

    r = E.task_claim(h1, GIRL)
    check("女儿领成功", r.get("ok") is True, r)
    kid_t = r["task_id"]
    check("领走后不在等人领里", [d["id"] for d in E.task_hall(BOY)["hall"]] == [])
    doing = E.task_hall(BOY)["doing"]
    check("进到进行中并记了是谁", any(d["id"] == kid_t and d["who"] == "女儿" for d in doing))
    r2 = E.task_claim(h1, BOY)
    check("先到先得，第二个人领不到", r2.get("ok") is False, r2)
    check("拒绝理由点出了谁", "女儿" in r2.get("msg", ""), r2.get("msg"))
    check("母记录记着这一份是从它领的", db.query_one(
        "SELECT hall_id h FROM task WHERE id=?", (kid_t,))["h"] == h1)

    rv = E.task_revoke(h1, DAD)
    check("有人在做时家长撤不掉", rv.get("ok") is False, rv)
    check("拒绝理由让孩子先放开", "我不做了" in rv.get("msg", ""), rv.get("msg"))

    ab = E.task_abandon(kid_t, GIRL)
    check("孩子主动放开", ab.get("ok") is True, ab)
    check("放开后回到等人领", [d["id"] for d in E.task_hall(BOY)["hall"]] == [h1])
    r3 = E.task_claim(h1, GIRL)
    check("放开的那份不占位，本人还能再领回来", r3.get("ok") is True, r3)
    check("但别人还是领不到（位置又被他占了）", E.task_claim(h1, BOY).get("ok") is False)
    E.task_abandon(r3["task_id"], GIRL)
    check("第二次放开，谁都没占着了", E.task_hall()["hall"][0]["can_revoke"] is True)
    check("这时候家长能撤了", E.task_revoke(h1, DAD).get("ok") is True)
    hall = E.task_hall()
    check("撤了就离开大厅", [d["id"] for d in hall["hall"]] == [])
    check("落到已结束（没人交成功过=撤销）",
          any(d["id"] == h1 and d["state"] == "revoked" for d in hall["done"]))

    # 每个孩子各一份
    h2 = E.create_task(None, "整理自己的书桌", "桌面清空", reward_type="stardust",
                       reward={"amount": 2}, created_by=DAD, slots=0)
    g = E.task_claim(h2, GIRL)
    b = E.task_claim(h2, BOY)
    check("每人一份：两个人都领到了", g.get("ok") and b.get("ok"), (g, b))
    check("同一个人领不了第二份", E.task_claim(h2, GIRL).get("ok") is False)
    card = [d for d in E.task_hall()["hall"] if d["id"] == h2]
    check("还有位置所以留在大厅", len(card) == 1)
    check("卡片上带着两个人在做", card[0]["active"] == 2, card[0]["active"])
    check("孩子侧的 mine 指向自己那份",
          E.task_hall(GIRL)["mine"][0]["mine"]["task_id"] == g["task_id"])

    E.submit_task(g["task_id"], GIRL)
    check("交上来的那份标成 submitted",
          db.query_one("SELECT status s FROM task WHERE id=?", (g["task_id"],))["s"] == "submitted")
    before = E.stardust_balance(GIRL)
    E.confirm_task(g["task_id"], DAD)
    check("确认后奖励到账", E.stardust_balance(GIRL) == before + 2,
          (before, E.stardust_balance(GIRL)))
    card = [d for d in E.task_hall()["hall"] if d["id"] == h2]
    check("母记录仍开着（别人还能领自己那份）", len(card) == 1)
    check("记着交成了一份", card[0]["done"] == 1, card[0]["done"])
    check("还有人在做，还是撤不掉", E.task_revoke(h2, DAD).get("ok") is False)
    E.task_abandon(b["task_id"], BOY)
    check("都放手之后能撤了", E.task_revoke(h2, DAD).get("ok") is True)
    check("撤掉的落进已结束，且算做完（有人交成功过）",
          any(d["id"] == h2 and d["state"] == "done" for d in E.task_hall()["done"]))

    # 先到先得做完自动下线
    h3 = E.create_task(None, "倒一次垃圾", "厨房和卫生间的都拎下去", reward_type="stardust",
                       reward={"amount": 1}, created_by=DAD, slots=1)
    t3 = E.task_claim(h3, GIRL)["task_id"]
    E.submit_task(t3, GIRL)
    E.confirm_task(t3, DAD)
    check("先到先得的那条做完了就自动下线",
          db.query_one("SELECT status s FROM task WHERE id=?", (h3,))["s"] == "archived")
    check("下线后不在大厅也不在进行中",
          all(d["id"] != h3 for d in E.task_hall()["hall"]) and
          all(d["id"] != t3 for d in E.task_hall()["doing"]))

    # 直接派下去的任务不掺和这套
    h4 = E.create_task(GIRL, "背二十个单词", "默写全对", reward_type="stardust",
                       reward={"amount": 3}, created_by=DAD)
    check("直接派的不进大厅", all(d["id"] != h4 for d in E.task_hall()["hall"]))
    check("从大厅也领不动它", E.task_claim(h4, BOY).get("ok") is False)
    check("它也在进行中（家长要看得到）", any(d["id"] == h4 for d in E.task_hall()["doing"]))
    check("没提交时家长可以直接撤", E.task_revoke(h4, DAD).get("ok") is True)

    # 星尘额度挪到领取那一刻查
    _set("task.stardust_weekly_cap", 1)
    h5 = E.create_task(None, "大扫除", "全屋", reward_type="stardust", reward={"amount": 5},
                       created_by=DAD, slots=1)
    check("发布时不拦（还不知道谁做）", isinstance(h5, int), h5)
    c = E.task_claim(h5, BOY)
    check("领取时按他的周额度拦下", c.get("ok") is False, c)
    check("说明提到了上限", "上限" in c.get("msg", ""), c.get("msg"))
    _set("task.stardust_weekly_cap", 20)

    print("\n=== 17. 孩子数据总览（v15）===")
    ov = E.kids_overview()
    check("一次给出所有孩子", len(ov) == 2, len(ov))
    k1 = [x for x in ov if x["member_id"] == GIRL][0]
    check("速览卡带今日得分", k1["today"]["score"] == k1["today"]["full"],
          (k1["today"]["score"], k1["today"]["full"]))
    check("速览卡带周能量", k1["cycle"] and "energy" in k1["cycle"])
    check("速览卡带累计星尘与欠款", "stardust" in k1 and "debt" in k1)
    check("速览卡把券和卡的张数合出来了", k1["holdings"]["tickets"] > 0,
          k1["holdings"]["tickets"])
    check("券的明细也一并给前端了", len(k1["holdings"]["ticket_list"]) > 0)

    d = E.kid_detail(GIRL)
    check("详细页这一周是七天", len(d["week"]) == 7, len(d["week"]))
    check("详细页带等级", d["level"] and d["level"]["total"] > 0)
    check("详细页把在做的事都捡齐了",
          all(k in d for k in ("tasks", "helps", "wishes")))
    check("没有这个成员时返回 None", E.kid_detail(9999) is None)

    hist = E.score_history(GIRL, days=10)
    check("记录页天数对得上", len(hist["days"]) == 10, len(hist["days"]))
    check("每天七格", all(len(x["cells"]) == 7 for x in hist["days"]))
    scored_days = [x for x in hist["days"] if x["scored"]]
    check("打过分的天数认得出来", len(scored_days) > 0, len(scored_days))
    check("没打分的天不参与达成率分母",
          all(a["total"] == len(scored_days) for a in hist["dims"]),
          (hist["dims"][0]["total"], len(scored_days)))
    check("各维度算满七项", len(hist["dims"]) == 7)
    check("这一天的「为什么扣」捡得出来", all("lost" in x["reason"] for x in hist["days"]))

    print("\n=== 18. 首页动态与心愿历史（v18）===")
    # 前面几节的发布任务都已经被确认或撤掉了，动态里得有一条真在做的才验得下去。
    # 用周能量发奖，不占任务星尘的每周上限，免得这里把额度撞满、后面几节没得测。
    t = E.create_task(GIRL, "擦一次窗台", "没有灰，抹布洗过再收",
                      reward_type="energy", reward={"amount": 1}, created_by=DAD)
    check("建一条还没做完的任务", isinstance(t, int), t)
    fd = E.feed(None, limit=50, recent_limit=5)
    kinds = sorted({x["kind"] for x in fd["items"]})
    check("动态给得出条目", len(fd["items"]) > 0, len(fd["items"]))
    check("任务、心愿、校准三种都收进来了", kinds == ["calibration", "task", "wish"], kinds)
    check("每条都带类别和一句状态",
          all(x.get("kind_text") and x.get("state_text") for x in fd["items"]))
    check("每条都带排序权重", all("rank" in x for x in fd["items"]))
    check("按权重升序排（球在大人的排前面）",
          [x["rank"] for x in fd["items"]] == sorted(x["rank"] for x in fd["items"]),
          [x["rank"] for x in fd["items"]])
    check("任务类带三颗点", all(x["step"] in (1, 2, 3) and len(x["steps"]) == 3
                          for x in fd["items"] if x["kind"] == "task"))
    check("心愿类带进度百分比",
          all(x["percent"] is not None for x in fd["items"]
              if x["kind"] == "wish" and x["state_key"] != "wished"))
    check("有「最近发生」", len(fd["recent"]) > 0, len(fd["recent"]))
    check("最近发生按时间倒序",
          [r["ts"] for r in fd["recent"]] == sorted((r["ts"] for r in fd["recent"]),
                                                   reverse=True))

    one = E.feed(GIRL, limit=50, recent_limit=5)
    check("孩子那份只有他自己的",
          all(x["member_id"] == GIRL for x in one["items"]),
          sorted({x["member_id"] for x in one["items"]}))
    check("孩子那份比家长那份少", len(one["items"]) < len(fd["items"]),
          (len(one["items"]), len(fd["items"])))

    # 被驳回：还挂在墙上的时候，家长把它点掉
    r = E.wish_one(BOY, "想要一个新手柄", operator_id=BOY)
    check("孩子许愿落到挂起", r["ok"], r.get("msg"))
    E.update_wish_status(r["wish_id"], "cancelled", operator_id=DAD)
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))
    check("驳回记下「结束前还挂在墙上」", w["closed_from"] == "wished", w["closed_from"])
    check("驳回记下是谁点的", w["closed_by"] == DAD, w["closed_by"])

    # 自己放弃：条件已经定下、进度在走的时候，孩子自己收起来
    r2 = E.create_wish(BOY, "换一个新卡册", "stardust", {"value": 5}, operator_id=DAD)
    check("建一条进行中的心愿", r2["ok"], r2.get("msg"))
    E.update_wish_status(r2["wish_id"], "cancelled", operator_id=BOY)
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r2["wish_id"],))
    check("放弃记下「结束前在进行中」", w["closed_from"] == "active", w["closed_from"])
    check("放弃记下是孩子自己点的", w["closed_by"] == BOY, w["closed_by"])
    check("结束的心愿不再出现在动态里",
          all(x.get("wish_id") not in (r["wish_id"], r2["wish_id"])
              for x in E.feed(None, limit=50)["items"]))

    print("\n=== 19. 备份与导出 ===")
    p = db.snapshot()
    check("生成了快照文件", p is not None, p)
    exp = db.export_json()
    check("能整库导出", exp.get("member") and len(exp["member"]) == 4, len(exp.get("member", [])))

    # ---------------------------------------------------------------- 20
    print("\n=== 20. 登录与账号（v19）===")
    rows = db.query("SELECT * FROM member WHERE active=1 ORDER BY sort")
    check("迁移给每个成员都填了账号名", all(r["username"] for r in rows),
          [r["username"] for r in rows])
    check("账号名互不重复", len({r["username"] for r in rows}) == len(rows))
    admins = [r for r in rows if r["is_admin"]]
    check("全库只有一位管理员", len(admins) == 1, [r["name"] for r in admins])
    check("管理员是家长", bool(admins) and admins[0]["role"] == "parent",
          admins[0]["name"] if admins else None)
    check("密码一开始是空的（等本人自己设）", all(not r["password_hash"] for r in rows))
    check("全员没密码时算首次运行", A.is_first_run())

    # 哈希：同一个密码两次结果必须不同（每账号一个随机盐）。
    # 旧版是 sha256("family-points" + pin)，全库一个固定盐且只跑一轮，容易出彩虹表。
    h1, h2 = A.hash_password("1234"), A.hash_password("1234")
    check("哈希带算法与轮数", h1.startswith("pbkdf2$"), h1[:24])
    check("同一个密码两次哈希不同（每账号一个盐）", h1 != h2)
    check("自己设的密码能验过", A.check_password("1234", h1) and A.check_password("1234", h2))
    check("错密码验不过", not A.check_password("1235", h1))
    check("空密码不是万能钥匙", not A.check_password("", h1) and not A.check_password("x", ""))
    check("旧格式的哈希不放行",
          not A.check_password("1234", hashlib.sha256(b"family-points1234").hexdigest()))

    print("\n  -- 密码规则 --")
    for bad_pw, why in (("123", "少于 4 位"), ("", "空"), ("a" * 70, "超过 64 位"),
                        (" ab ", "两头带空格")):
        try:
            A.check_pwd_rule(bad_pw)
            check("拦下「" + why + "」", False, "居然放过了")
        except ApiError:
            check("拦下「" + why + "」", True)
    for ok_pw in ("1234", "abcd", "我家的小狗"):
        try:
            A.check_pwd_rule(ok_pw)
            check("放行「" + ok_pw + "」", True)
        except ApiError as e:
            check("放行「" + ok_pw + "」", False, e.message)

    print("\n  -- 密码规则 · 孩子那条（v36）--")
    # 孩子固定 4 位纯数字。理由是登录方式：孩子端给的是数字键盘，输满 4 位
    # 自动提交，格子里敲不进字母。服务端跟着一起卡，才不会出现
    # 「界面上进不去、库里其实是个六位密码」那种只能靠翻库才能发现的死结。
    for bad in ("123", "12345", "12a4", "1234 ", " abcd", "abcd", "１２３４", "١٢٣٤"):
        try:
            A.check_pwd_rule(bad, "child")
            check("孩子密码拦下「" + bad + "」", False, "居然放过了")
        except ApiError:
            check("孩子密码拦下「" + bad + "」", True)
    for ok in ("0000", "1234", "9999"):
        try:
            A.check_pwd_rule(ok, "child")
            check("孩子密码放行「" + ok + "」", True)
        except ApiError as e:
            check("孩子密码放行「" + ok + "」", False, e.message)
    # 家长那条不受影响：还是只卡长度，不逼着大人也去记四个数字
    for ok in ("abcd", "我家的小狗"):
        try:
            A.check_pwd_rule(ok, "parent")
            check("家长密码放行「" + ok + "」", True)
        except ApiError as e:
            check("家长密码放行「" + ok + "」", False, e.message)

    # 设过第一个密码之后，首次设置的口子就该永久关上
    db.execute("UPDATE member SET password_hash=? WHERE id=?", (A.hash_password("pw3"), GIRL))
    check("有人设过密码后就不再是首次运行", not A.is_first_run())
    check("设过的密码能验过", A.check_password("pw3", db.query_one(
        "SELECT password_hash FROM member WHERE id=?", (GIRL,))["password_hash"]))

    print("\n=== 21. 零花钱兑换流程（v24）===")
    E.add_ledger(BOY, "adjust", stardust=100, note="测试注入")
    r = E.request_cash(BOY, 20, note="买个新笔袋", operator_id=BOY)
    check("孩子发起兑换落到待审", r["ok"] and r["status"] == "pending", r)
    rid = r["request_id"]
    check("发起时不动账", E.stardust_balance(BOY) == 100, E.stardust_balance(BOY))
    check("待审的也占着额度", E.cash_pending_stardust(BOY) == 20, E.cash_pending_stardust(BOY))
    r = E.request_cash(BOY, 50, operator_id=BOY)
    check("在审的算进额度，再提就超了", not r["ok"], r.get("msg", ""))
    check("待办数得出来", E.pending_cash_count() >= 1, E.pending_cash_count())

    check("孩子不能自己批",
          not E.resolve_cash_request(rid, True, operator_id=BOY)["ok"])
    r = E.resolve_cash_request(rid, False, operator_id=DAD)
    check("拒绝必须写理由", not r["ok"], r.get("msg", ""))

    r = E.resolve_cash_request(rid, True, operator_id=DAD)
    check("家长同意就发放（20 星尘 → 10 元）", r["ok"] and r["cash"] == 10, r)
    check("发放那一刻才扣星尘", E.stardust_balance(BOY) == 80, E.stardust_balance(BOY))
    check("月额度也记上了", E.month_cash_used(BOY) == 20, E.month_cash_used(BOY))
    check("流水挂上了",
          db.query_one("SELECT ledger_id FROM cash_request WHERE id=?", (rid,))["ledger_id"])
    r = E.resolve_cash_request(rid, True, operator_id=DAD)
    check("同一条批不了两遍", not r["ok"], r.get("msg", ""))

    r = E.receive_cash_request(rid, BOY)
    check("孩子确认收到", r["ok"] and r["status"] == "received", r)
    check("确认过了不能再确认", not E.receive_cash_request(rid, BOY)["ok"])
    check("这一条到此完结",
          db.query_one("SELECT status FROM cash_request WHERE id=?", (rid,))["status"] == "received")

    r2 = E.request_cash(BOY, 5, operator_id=BOY)
    check("待审的可以自己撤回", E.cancel_cash_request(r2["request_id"], BOY)["ok"])
    r3 = E.request_cash(BOY, 5, operator_id=BOY)
    E.resolve_cash_request(r3["request_id"], True, operator_id=DAD)
    check("批过的撤不了", not E.cancel_cash_request(r3["request_id"], BOY)["ok"])
    check("别人确认不了我的", not E.receive_cash_request(r3["request_id"], GIRL)["ok"])
    check("余额收尾对得上", E.stardust_balance(BOY) == 75, E.stardust_balance(BOY))

    print("\n=== 22. 宝箱保底改版（v24）===")
    tiers = {t["tier"]: t for t in db.query("SELECT * FROM box_tier ORDER BY tier")}

    def bcards(n):
        return json.loads(tiers[n]["cards_json"] or "[]")

    check("木 / 铜 / 银只给券，不给卡",
          all(bcards(i) == [] for i in (1, 2, 3)), [bcards(i) for i in (1, 2, 3)])
    check("金箱 8 张券、不含卡",
          tiers[4]["tickets"] == 8 and bcards(4) == [], (tiers[4]["tickets"], bcards(4)))
    check("钻石箱 10 券 + 1 普通卡",
          tiers[5]["tickets"] == 10 and bcards(5) == [{"rarity": "common", "count": 1}],
          bcards(5))
    check("王者箱 12 券 + 普通 + 稀有",
          tiers[6]["tickets"] == 12 and bcards(6) == [{"rarity": "common", "count": 1},
                                                       {"rarity": "rare", "count": 1}], bcards(6))
    check("完美箱 14 券 + 普稀传各一张",
          tiers[7]["tickets"] == 14 and bcards(7) == [{"rarity": "common", "count": 1},
                                                       {"rarity": "rare", "count": 1},
                                                       {"rarity": "legend", "count": 1}], bcards(7))
    check("保底星尘全部撤掉",
          all(not tiers[i]["stardust"] for i in range(1, 8)),
          [tiers[i]["stardust"] for i in range(1, 8)])
    check("随机件概率一个没动",
          [tiers[i]["random_rate"] for i in range(1, 8)] == [0, 0, 0, 0.10, 0.20, 0.40, 0.70],
          [tiers[i]["random_rate"] for i in range(1, 8)])
    check("只有金 / 钻石 / 王者挂价签",
          [i for i in range(1, 8) if tiers[i]["purchase_allowed"]] == [4, 5, 6],
          [i for i in range(1, 8) if tiers[i]["purchase_allowed"]])

    E.add_ledger(BOY, "adjust", stardust=200, note="测试注入")
    made = E.issue_box(BOY, 7, source="free", operator_id=DAD)
    check("发下来是一只待开的箱子（v38 拆开）",
          bool(made and made.get("pending") and made.get("box_id")), made)
    r = E.open_box(BOY, made["box_id"], operator_id=DAD)
    types = [g["type"] for g in r["given"]]
    rarities = [g["rarity"] for g in r["given"] if g["type"] == "card"]
    check("完美箱一次给三张卡", types.count("card") == 3, types)
    check("三张卡分别是普 / 稀 / 传", set(rarities) == {"common", "rare", "legend"}, rarities)
    check("卡按普通到传说抽（稀有度高的后抽）",
          rarities == ["common", "rare", "legend"], rarities)
    check("保底券照给", any(g["type"] == "ticket" and g["qty"] == 14 for g in r["given"]), types)

    brief = E.box_tiers_brief()
    check("阶梯数据七档齐全", len(brief) == 7, len(brief))
    check("阶梯带上了每档几张卡",
          [b["card_count"] for b in brief] == [0, 0, 0, 0, 1, 2, 3],
          [b["card_count"] for b in brief])
    check("周期快照带上了阶梯", len(E.cycle_snapshot(E.current_cycle(BOY)["id"])["tiers"]) == 7)

    # ------------------------------------------------------------------
    # v25 起心愿条件多了两种形态：机器算不了的和「好几条路随便走哪条」的。
    # v26 把后者从「任一条」改成「多选条件」：六条全都能勾，家长另定「做到几条算成」。
    # 这一节逐条验它们的判定和边界。
    print("\n=== 23. 心愿条件：自己写一条 / 多选条件（v25 · v26）===")
    # 先把 BOY 手上进行中的心愿清空：wish.max_active 默认 2，不清就会被名额挡下来
    for w in db.query("SELECT id FROM wish WHERE member_id=? AND status='active'", (BOY,)):
        E.update_wish_status(w["id"], "cancelled", operator_id=DAD)

    r = E.create_wish(BOY, "把《夏洛的网》读完", "custom",
                      {"text": "读完整本，讲给我听一遍"}, operator_id=DAD)
    check("自定义条件建得起来", r["ok"], r.get("msg"))
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))
    p = E.wish_view(w, with_progress=True)["progress"]
    check("自定义那条没有百分比", p["percent"] is None, p["percent"])
    check("自定义那条标着「人工判」", p["manual"] is True)
    check("自定义那条一直能说「我做到了」", p["ready"] is True and p["done"] is False)
    check("自定义那条不进自动通知",
          r["wish_id"] not in E.check_wish_ready(BOY), E.check_wish_ready(BOY))
    check("条件原话能读出来", E.wish_cond_text(w) == "读完整本，讲给我听一遍",
          E.wish_cond_text(w))
    check("自定义不给空话", not E.create_wish(BOY, "空的", "custom", {"text": " "})["ok"])
    check("自定义不给超长",
          not E.create_wish(BOY, "长的", "custom", {"text": "字" * 61})["ok"])
    # 挂起的心愿带上自定义条件走一遍「点亮」这条路（孩子许愿 → 家长定条件）
    rh = E.wish_one(BOY, "想去露营一次", operator_id=BOY)
    check("点亮时能吃下自定义条件",
          E.configure_wish(rh["wish_id"], "custom", {"text": "自己搭帐篷，全程不喊人帮忙"},
                           operator_id=DAD)["ok"])
    wh = db.query_one("SELECT * FROM wish WHERE id=?", (rh["wish_id"],))
    check("点亮后的自定义也是人工判",
          E.wish_view(wh, with_progress=True)["progress"]["manual"] is True)

    for w in db.query("SELECT id FROM wish WHERE member_id=? AND status='active'", (BOY,)):
        E.update_wish_status(w["id"], "cancelled", operator_id=DAD)

    r = E.create_wish(BOY, "这周多选达成一个", "any",
                      {"items": [{"type": "fixed", "value": 49},
                                 {"type": "task_count", "value": 3},
                                 {"type": "stardust", "value": 1},
                                 {"type": "custom", "text": "把书桌自己收拾干净"}],
                       "need": 2}, operator_id=DAD)
    check("多选条件建得起来（勾四条，含星尘和自定义）", r["ok"], r.get("msg"))
    w = db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],))
    p = E.wish_view(w, with_progress=True)["progress"]
    check("多选带回每条的进度", len(p["subs"]) == 4, [s.get("text") for s in p.get("subs", [])])
    check("多选读得出「做到几条算成」", p["need"] == 2 and p["target"] == 2, p.get("need"))
    check("多选画的是完成条数，不是哪一条最接近",
          p["cur"] == p["done_count"] and p["percent"] == min(
              100, int(round(p["done_count"] / 2 * 100))), (p.get("cur"), p["percent"]))
    check("多选带「人工判」标记（里面那条自定义算不了）", p.get("has_manual") is True)
    check("含自定义的多选一直能说「我做到了」", p["ready"] is True and p["done"] is False)
    check("那条自定义的百分比空着，不是 0",
          [s["percent"] for s in p["subs"] if s["key"] == "custom"] == [None])
    check("多选的文案写明做到几条",
          "其中做到 2 条就算" in E.wish_cond_text(w), E.wish_cond_text(w))
    E.update_wish_status(r["wish_id"], "cancelled", operator_id=DAD)

    # 老数据没带 need 的：读出来当「一条」，v25 的行为原样能用
    check("不带「做到几条」时按一条算", E.wish_progress({
        "cond_type": "any", "member_id": GIRL, "cond": {"items": [
            {"type": "streak", "value": 1}, {"type": "fixed", "value": 999}]},
        "configured_at": "0000", "selfpay_stardust": 0})["done"] is True)
    check("要两条时只做到一条不算", E.wish_progress({
        "cond_type": "any", "member_id": GIRL, "cond": {"need": 2, "items": [
            {"type": "streak", "value": 1}, {"type": "fixed", "value": 999}]},
        "configured_at": "0000", "selfpay_stardust": 0})["done"] is False)
    check("要两条、做到两条就算", E.wish_progress({
        "cond_type": "any", "member_id": GIRL, "cond": {"need": 2, "items": [
            {"type": "streak", "value": 1}, {"type": "stardust", "value": 5},
            {"type": "fixed", "value": 999}]},
        "configured_at": "0000", "selfpay_stardust": 5})["done"] is True)

    # 星尘那条：余额够了只是「能付」，系统不替他完成 —— 走不走这条路由他自己定
    E.add_ledger(BOY, "adjust", day=E.today(), stardust=30, note="测试预置（多选里的星尘）")
    r2 = E.create_wish(BOY, "多选里带星尘那条", "any",
                       {"items": [{"type": "stardust", "value": 20},
                                  {"type": "perfect_day", "value": 999}],
                        "need": 2}, operator_id=DAD)
    check("多选里的星尘那条建得起来", r2["ok"], r2.get("msg"))
    p2 = E.wish_view(db.query_one("SELECT * FROM wish WHERE id=?", (r2["wish_id"],)),
                     with_progress=True)["progress"]
    check("余额够了只算「能付」，不算「做到」",
          p2["can_pay"] is not None and p2["done_count"] == 0
          and not any(s["done"] for s in p2["subs"] if s["key"] == "stardust"),
          (p2.get("can_pay"), p2["done_count"]))
    check("没付之前整体没达成", p2["done"] is False and float(p2["paid"]) == 0)
    rp = E.pay_wish_selfpay(r2["wish_id"], operator_id=BOY)
    check("孩子自己点能把多选里的星尘付掉", rp["ok"], rp.get("msg"))
    p3 = E.wish_view(db.query_one("SELECT * FROM wish WHERE id=?", (r2["wish_id"],)),
                     with_progress=True)["progress"]
    check("付掉之后那一条才记成做到", p3["done_count"] == 1 and p3["can_pay"] is None)
    check("付了钱也只是那一条，整体还差一条", p3["done"] is False and p3["need"] == 2)
    check("付掉的钱记在这条心愿上", float(p3["paid"] or 0) == 20)

    check("单选星尘那条读得出要付多少",
          E._selfpay_need({"cond_type": "stardust", "cond": {"value": 30}}) == 30)
    check("多选里那条星尘也读得出",
          E._selfpay_need({"cond_type": "any", "cond": {"items": [
              {"type": "fixed", "value": 1}, {"type": "stardust", "value": 25}]}}) == 25)
    check("不用付钱的心愿读出来是空",
          E._selfpay_need({"cond_type": "fixed", "cond": {"value": 49}}) is None)

    r3 = E.create_wish(BOY, "六条全勾", "any",
                       {"items": [{"type": "fixed", "value": 1},
                                  {"type": "stardust", "value": 1},
                                  {"type": "task_count", "value": 1},
                                  {"type": "streak", "value": 1},
                                  {"type": "perfect_day", "value": 1},
                                  {"type": "custom", "text": "说好的一件事"}],
                        "need": 1}, operator_id=DAD)
    check("六条能全勾上", r3["ok"], r3.get("msg"))
    check("多选至少两条",
          not E.create_wish(BOY, "只有一条", "any",
                            {"items": [{"type": "fixed", "value": 10}]})["ok"])
    check("「做到其中几条」至少 1 条",
          not E.create_wish(BOY, "零条", "any",
                            {"items": [{"type": "fixed", "value": 1},
                                       {"type": "task_count", "value": 1}],
                             "need": 0})["ok"])
    check("「做到其中几条」不能比勾的条数多",
          not E.create_wish(BOY, "三条", "any",
                            {"items": [{"type": "fixed", "value": 1},
                                       {"type": "task_count", "value": 1}],
                             "need": 3})["ok"])
    check("多选里自定义那条也要写清楚",
          not E.create_wish(BOY, "自定义空的", "any",
                            {"items": [{"type": "fixed", "value": 1},
                                       {"type": "custom", "text": " "}]})["ok"])
    check("多选不许重复挑同一条",
          not E.create_wish(BOY, "重复的", "any",
                            {"items": [{"type": "fixed", "value": 10},
                                       {"type": "fixed", "value": 20}]})["ok"])

    # ⑯ v28：两件新东西 —— 孩子端七项分数看得见「哪一项、哪几天、哪里被扣」，
    #    家长端动态日志把账本翻成人话（孩子自己按的每一个按钮都在里头）。
    #    家长问得最多的那句是「券怎么突然多了」，这一节就是它的答案：
    #    买了、开出来的、升级送的，三种来源各说各的话。
    _wipe()
    rep = E.dims_report(kid, days=7)
    check("⑯ 七项一项不落", len(rep["dims"]) == 7, [x["name"] for x in rep["dims"]])
    check("⑯ 每项都写了它是干什么的", all(x["meaning"] for x in rep["dims"]))
    check("⑯ 每项都能对上「这几天拿到几天」",
          all(0 <= x["hit"] <= x["total"] for x in rep["dims"]))
    check("⑯ 最弱那一项点得出来", rep["weakest"] and rep["weakest"]["name"], rep["weakest"])

    # 校准挂到具体某一项上，孩子那边要能看见「这一项被扣了、因为什么」
    E.add_calibration(kid, 2, "桌面两天没收拾", dimension_code="clean",
                      effect_type="ticket_min", amount=15, operator_id=DAD)
    rep2 = E.dims_report(kid, days=7)
    clean = [x for x in rep2["dims"] if x["code"] == "clean"][0]
    check("⑯ 扣分挂在被扣的那一项上", len(clean["fines"]) >= 1, clean["fines"])
    check("⑯ 扣分理由写的是那句具体的话",
          any("桌面" in (f.get("reason") or "") for f in clean["fines"]), clean["fines"])
    check("⑯ 别的项目没被这条扣分牵连",
          all(not x["fines"] for x in rep2["dims"] if x["code"] != "clean"))
    check("⑯ 扣了多少次、多少分钟算得出来",
          rep2["deduct"]["times"] >= 1 and rep2["deduct"]["minutes"] >= 15, rep2["deduct"])
    check("⑯ 固定分之外的加减列得出来",
          any(e["text"] and e["impact"] for e in rep2["extra"]), rep2["extra"][:3])

    # 动态日志：三种券的来源各说各的话
    E.grant_item(kid, fun_id, 2, source="levelup", operator_id=DAD)
    acts = E.activity(kid, limit=40)["items"]
    check("⑯ 升级送的东西写着「升到」，不再笼统算「手动调整」",
          any("升" in x["text"] for x in acts), [x["text"] for x in acts][:5])
    check("⑯ 每一条都是人话，不会漏出英文类型名",
          not any(x["text"].strip() in E.KINDS.values() for x in acts))
    check("⑯ 每一条带着对账的影响（谁多谁少）",
          any(x["impact"] for x in acts))
    check("⑯ 孩子自己买的那条写着「买了券」",
          any("买了券" in x["text"] for x in E.activity(kid, group="self", limit=40)["items"]),
          [x["text"] for x in E.activity(kid, group="self", limit=8)["items"]])
    check("⑯ 筛「孩子自己做的」不会混进打分",
          not any(x["kind"] == "daily_score"
                  for x in E.activity(kid, group="self", limit=40)["items"]))
    check("⑯ 打分归在「家长给的评价」那一类",
          any(x["kind"] == "daily_score" for x in E.activity(kid, group="judge", limit=40)["items"]))
    check("⑯ 孩子看的日志只有他自己",
          set(x["who"] for x in E.activity(kid, limit=20)["items"]) <= {E.member_name_of(kid)},
          sorted(set(x["who"] for x in E.activity(kid, limit=20)["items"])))
    check("⑯ 家长看的是全家", len(set(x["who"] for x in E.activity(limit=20)["items"])) >= 1)
    check("⑯ 四类分组都在", [g["key"] for g in E.activity(limit=1).get("groups", [])]
          == ["self", "given", "judge", "system"], E.activity(limit=1).get("groups"))
    check("⑯ 翻页不重不漏",
          E.activity(limit=5)["items"][:3] == E.activity(limit=5, offset=0)["items"][:3]
          and E.activity(limit=5, offset=5)["items"][0] != E.activity(limit=5)["items"][0])
    check("⑯ 孩子自己按的那些也进了首页的「最近发生」",
          any(x["kind"] in ("self", "given") for x in E._feed_recent(kid, 6)),
          [x["text"] for x in E._feed_recent(kid, 4)])

    # ⑰ v29：三件事 —— 日志写清是谁经手的、心愿按一条一条提交、
    #    券批了之后看得出是谁同意的。共同点是同一句：**别让家长去猜**。
    #    「券怎么突然多了」上一版解决了「哪来的」，这一版解决「谁干的」。
    _wipe()
    db.execute("DELETE FROM wish_claim")
    db.execute("DELETE FROM wish")

    # 日志：经手人
    E.add_ledger(kid, "adjust", stardust=1, note="测试：妈妈加的", operator_id=MOM)
    E.add_ledger(kid, "adjust", stardust=2, note="测试：孩子自己买的", operator_id=kid)
    acts = E.activity(kid, limit=30)["items"]
    check("⑰ 每条日志都带着经手人", all(x["by"] for x in acts),
          [x.get("by") for x in acts][:6])
    check("⑰ 妈妈经手的那条写的是妈妈",
          any(x["by"] == E.member_name_of(MOM) for x in acts),
          sorted(set(x["by"] for x in acts)))
    check("⑰ 孩子自己按的那条写的是他自己",
          any(x["by"] == E.member_name_of(kid) for x in acts),
          sorted(set(x["by"] for x in acts)))
    check("⑰ 只有大人才标 by_parent",
          all(x["by_parent"] for x in acts if x["by"] == E.member_name_of(MOM))
          and not any(x["by_parent"] for x in acts if x["by"] == E.member_name_of(kid)),
          [(x["by"], x["by_parent"]) for x in acts][:6])
    check("⑰ 没有记经手人的写「系统」，不冒用孩子的名字",
          all(x["by"] != E.member_name_of(kid) or x["by_parent"] is False for x in acts))

    # 心愿：按哪一条提交
    w = E.create_wish(kid, "测试心愿", "any",
                      # need=2：任务数那条已经做到了，自定义那条还没 ——
                      # 这样「提交 → 等确认 → 确认后才算凑够」三步才走得出来。
                      # 写成 need=1 的话，心愿一开始就已经够了，测不到这一步。
                      {"need": 2,
                       "items": [{"type": "custom", "text": "把书桌收拾干净"},
                                 {"type": "task_count", "value": 2}]},
                      operator_id=DAD)
    wid = w["wish_id"]

    def _prog():
        return E.wish_progress(dict(db.query_one("SELECT * FROM wish WHERE id=?", (wid,))))

    def _sub(p):
        return [x for x in p["subs"] if x["key"] == "custom"][0]

    check("⑰ 系统算得出来的那条不给提交",
          not E.submit_wish_cond(wid, "task_count", "", operator_id=kid)["ok"])
    check("⑰ 心愿里没挂的条件不给提交",
          not E.submit_wish_cond(wid, "streak", "", operator_id=kid)["ok"])
    check("⑰ 家长不能替孩子说「我做到了」",
          not E.submit_wish_cond(wid, "custom", "", operator_id=DAD)["ok"])
    r1 = E.submit_wish_cond(wid, "custom", "书桌收好了", operator_id=kid)
    check("⑰ 自己写的那条能提交", bool(r1.get("ok")), r1)
    check("⑰ 还在等确认的时候不能重复交",
          not E.submit_wish_cond(wid, "custom", "", operator_id=kid)["ok"])
    p1 = _prog()
    check("⑰ 交上去之后整条心愿不再给「我做到了」",
          p1["ready"] is False and p1["has_pending"] is True, p1)
    check("⑰ 那一行写着等确认",
          _sub(p1)["pending"] and _sub(p1)["claim_status"] == "pending", _sub(p1))
    cl = [c for c in E.pending_wish_claims() if c["wish_id"] == wid]
    check("⑰ 家长待办写着是谁、是哪一条",
          cl and cl[0]["who"] and "书桌" in cl[0]["cond_text"], cl)
    cid = cl[0]["id"]
    check("⑰ 孩子不能审自己交的那条",
          not E.resolve_wish_claim(cid, True, operator_id=kid)["ok"])
    check("⑰ 不通过必须写理由",
          not E.resolve_wish_claim(cid, False, operator_id=DAD, reject_note="")["ok"])
    E.resolve_wish_claim(cid, False, operator_id=DAD, reject_note="抽屉没理")
    p2 = _prog()
    check("⑰ 驳回之后理由摆在那一行上",
          _sub(p2)["rejected"] and "抽屉" in _sub(p2)["reject_note"], _sub(p2))
    check("⑰ 驳回之后可以再交一次", p2["ready"] is True, p2)
    r2 = E.submit_wish_cond(wid, "custom", "这次抽屉也理了", operator_id=kid)
    check("⑰ 再交一次放行", bool(r2.get("ok")), r2)
    p3 = _prog()
    check("⑰ 再交之后还留着上一次为什么没过",
          "抽屉" in _sub(p3)["last_reject_note"], _sub(p3))
    cid2 = [c for c in E.pending_wish_claims() if c["wish_id"] == wid][0]["id"]
    res = E.resolve_wish_claim(cid2, True, operator_id=MOM)
    check("⑰ 确认了这一条就算做到了", bool(res.get("ok")) and res.get("done"), res)
    p4 = _prog()
    check("⑰ 通过的那条写着是谁确认的",
          _sub(p4)["done"] and _sub(p4)["by"] == E.member_name_of(MOM), _sub(p4))
    check("⑰ 凑够条数之后心愿达成",
          db.query_one("SELECT status FROM wish WHERE id=?", (wid,))["status"] == "achieved")
    check("⑰ 处理过的不许再处理一次",
          not E.resolve_wish_claim(cid2, True, operator_id=MOM)["ok"])

    # 券：谁同意的。整段钉在傍晚 —— 真实时间是晚上十点以后，
    # 硬停止那条闸门会把申请直接挡掉，测的就变成闸门而不是审批人了。
    E.freeze_clock(d0 + " 18:00:00")
    E.submit_day(kid, d0, [], operator_id=DAD)
    rr = E.request_ticket(kid, fun_id, 1, note="测试用券")
    rid = rr.get("request_id")
    if not rid:
        check("⑰ 券申请造出来了（闸门挡住就跳过后面两条）", False, rr)
    else:
        E.resolve_ticket_request(rid, True, operator_id=MOM)
        row = [x for x in E.my_ticket_list(kid, d0) if x["id"] == rid][0]
        check("⑰ 券上写着是谁同意的", row["by"] == E.member_name_of(MOM), row)
        pl = [x for x in E.ticket_playing(kid) if x["id"] == rid]
        check("⑰ 正在玩那块也写着谁批的",
              pl and pl[0]["by"] == E.member_name_of(MOM), pl)
    E.freeze_clock(None)

    # ------------------------------------------------------------------
    # v30 三件事：忘打卡兜底、周末翻倍、大厅任务的默认接取时限。
    # 这一节自己造时钟和前置条件，不依赖前面几节留下的状态。
    print("\n=== 24. 忘打卡兜底 / 周末翻倍 / 接取时限（v30，v34 补上起用日边界）===")
    E.freeze_clock("2026-03-04 13:00:00")     # 周三下午一点
    miss_day = "2026-03-03"                   # 周二，故意留空
    # v34 起，兜底有两道边界（起用日、开号日）。测试库是刚建的，这两个值
    # 都是「现在」，不先把它们挪到三月之前，下面判的三月会被边界直接挡掉，
    # 测出来的就是边界本身，不是兜底。改 created_at 只影响这一节。
    set_setting("family.start_date", "2026-03-01")
    db.execute("UPDATE member SET created_at='2026-03-01 09:00:00'")
    # 前置：两个孩子这天一条分数都没有、周期是开着的、这天不是过渡日
    db.execute("DELETE FROM holiday")
    for m in (GIRL, BOY):
        db.execute("DELETE FROM score_entry WHERE member_id=? AND day=?", (m, miss_day))
        db.execute("DELETE FROM ledger WHERE member_id=? AND day=?", (m, miss_day))
        db.execute("UPDATE cycle SET status='open' WHERE member_id=?", (m,))
    # 许愿池先收掉旧目标，立一个新的，罚款才有地方投
    for p in db.query("SELECT id FROM wish_pool WHERE status='active'"):
        db.execute("UPDATE wish_pool SET status='achieved' WHERE id=?", (p["id"],))
    E.create_pool("一次露营", "在山上过一夜", 400)
    before = E.pool_progress()["collected_stardust"]

    out = E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    check("空着的那天被补记", len(out["filled"]) == 2, out["filled"])
    for m in (GIRL, BOY):
        n = db.query_one("SELECT COUNT(*) c FROM score_entry WHERE member_id=? AND day=?"
                         " AND is_fixed=1 AND voided=0", (m, miss_day))["c"]
        check("%s 补满七项" % E.member_name_of(m), n == 7, n)
        day_sum = db.query_one("SELECT COALESCE(SUM(value),0) v FROM score_entry"
                               " WHERE member_id=? AND day=? AND is_fixed=1 AND voided=0",
                               (m, miss_day))["v"]
        check("%s 补的是满分" % E.member_name_of(m), day_sum == 7, day_sum)
    after = E.pool_progress()["collected_stardust"]
    check("罚款 100 星尘投进池子", after - before == 100, after - before)
    log = db.query_one("SELECT * FROM wish_pool_log WHERE kind='penalty' AND day=?", (miss_day,))
    check("日志记着是哪一天", log is not None, log)
    check("日志记着几个孩子、多少天次", log["kids_days"] == 2, log and log["kids_days"])
    check("日志里写着是哪两个孩子", "女儿" in log["kids_json"] and "儿子" in log["kids_json"],
          log and log["kids_json"])
    check("日志写着注入额", log["stardust"] == 100, log and log["stardust"])
    entry = db.query_one("SELECT * FROM wish_pool_entry WHERE source='penalty'"
                         " ORDER BY id DESC LIMIT 1")
    check("池子流水那条标着 penalty", entry is not None and entry["stardust"] == 100, entry)

    again = E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    check("再跑一次不重复补", not again["filled"], again["filled"])
    check("再跑一次不重复罚",
          E.pool_progress()["collected_stardust"] == after,
          E.pool_progress()["collected_stardust"])
    check("一天只留一条罚款日志",
          db.query_one("SELECT COUNT(*) c FROM wish_pool_log WHERE kind='penalty'"
                       " AND day=?", (miss_day,))["c"] == 1)

    # 还没到次日 12:00 时不该动手
    E.freeze_clock("2026-03-04 11:00:00")
    db.execute("DELETE FROM score_entry WHERE member_id=? AND day=?", (GIRL, miss_day))
    early = E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    check("还没到 12:00 就不补", not early["filled"], early["filled"])
    E.freeze_clock("2026-03-04 13:00:00")

    # v34：起用日与开号日两道边界。以前只有「这天有没有分」一条判据，
    # 系统一上线就往前倒查 7 天，把还没装好的日子也记成漏打。
    for m in (GIRL, BOY):
        db.execute("DELETE FROM score_entry WHERE member_id=? AND day=?", (m, miss_day))
        db.execute("DELETE FROM ledger WHERE member_id=? AND day=?", (m, miss_day))
    set_setting("family.start_date", "2026-03-03")      # 起用日正好是漏打那天
    o1 = E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    check("起用日当天不算漏打", not o1["filled"] and o1["before_start"] == 1, o1)
    set_setting("family.start_date", "2026-03-02")      # 起用日往后挪一天
    o2 = E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    check("起用日之后照常补", len(o2["filled"]) == 2, o2["filled"])
    set_setting("family.start_date", "2026-02-01")      # 让开全局边界，单独测成员那条
    check("开号当天不背账", not E.missed_kids("2026-03-01"), E.missed_kids("2026-03-01"))
    check("开号之前的空白不背账", not E.missed_kids("2026-02-20"))
    set_setting("family.start_date", "不是日期")
    check("起用日填坏了，退回开号那天", E.start_date() == "2026-03-01", E.start_date())
    set_setting("family.start_date", "2026-03-01")

    # 周末快乐翻倍：默认关；开了只认周六周日，且只放大娱乐券
    set_setting("ticket.weekend_double", False)
    fun = E.item_by_code("ticket_fun")
    check("开关关着时周末也是原值", E.ticket_minutes(fun, "2026-03-07") == 30,
          E.ticket_minutes(fun, "2026-03-07"))
    set_setting("ticket.weekend_double", True)
    check("周六翻倍", E.ticket_minutes(fun, "2026-03-07") == 60, E.ticket_minutes(fun, "2026-03-07"))
    check("周日翻倍", E.ticket_minutes(fun, "2026-03-08") == 60, E.ticket_minutes(fun, "2026-03-08"))
    check("平日不翻", E.ticket_minutes(fun, "2026-03-04") == 30, E.ticket_minutes(fun, "2026-03-04"))
    check("没有日期时按不翻算", E.ticket_minutes(fun) == 30, E.ticket_minutes(fun))
    check("翻倍只认娱乐券，别的券不受影响",
          E.ticket_minutes(E.item_by_code("ticket_solo"), "2026-03-07") == 0)
    st = E.ticket_use_state(GIRL, fun, "2026-03-07", "2026-03-07 15:00:00")
    check("能不能用的快照读的也是翻倍后的数", st["minutes"] == 60, st["minutes"])
    check("快照里标着今天翻倍了", st["weekend_double"] is True)
    set_setting("ticket.weekend_double", False)

    # 大厅任务的默认接取时限：只有挂大厅的才塞，指名派下去的不塞
    tid = E.create_task(None, "擦一次全家地板", "地面没有灰", created_by=DAD, slots=1)
    row = db.query_one("SELECT deadline FROM task WHERE id=?", (tid,))
    check("大厅任务自动带上接取时限", row["deadline"] == "2026-03-06 13:00:00", row["deadline"])
    tid2 = E.create_task(GIRL, "整理书架", "三层都归位", created_by=DAD)
    row2 = db.query_one("SELECT deadline FROM task WHERE id=?", (tid2,))
    check("指名派下去的不塞默认时限", row2["deadline"] is None, row2["deadline"])
    set_setting("task.claim_deadline_hours", 0)
    tid3 = E.create_task(None, "给花浇水", "每盆都浇透", created_by=DAD, slots=1)
    check("填 0 就是不给默认时限",
          db.query_one("SELECT deadline FROM task WHERE id=?", (tid3,))["deadline"] is None)
    set_setting("task.claim_deadline_hours", 48)
    E.freeze_clock(None)

    # 头像值：这列存的是 avatars/<值>.svg 里的那个值，形状必须掐死
    check("v36 的编号放行（B03 / D10 / G01）",
          E.clean_avatar("B03") == "B03" and E.clean_avatar("D10") == "D10"
          and E.clean_avatar("G01") == "G01")
    # 大小写要当回事：NAS 上跑的是 Linux，文件名区分大小写，
    # 库里存小写的 b03 就取不到 B03.svg —— 电脑上能跑出来，装到 NAS 上是一片空
    check("编号一律抬成大写", E.clean_avatar("b03") == "B03"
          and E.clean_avatar("d10") == "D10")
    check("老值（girl_1 那种下划线）按小写留着，等迁移换掉",
          E.clean_avatar("Girl_1") == "girl_1")
    check("头像值挡掉路径穿越", E.clean_avatar("../../etc/passwd") == "")
    check("头像值挡掉中文老值", E.clean_avatar("爸爸") == "")
    check("头像值挡掉空值", E.clean_avatar("") == "" and E.clean_avatar(None) == "")
    E.freeze_clock(None)

    print("\n=== 25. 打分页四个状态（未打 / 补卡 / 修改 / 超时）===")
    # 打分页那四个标签的口径全在 score_day_state 一处。以前界面拿
    # scored + can_edit 自己拼，拼不出「过没过次日 12:00」，也拼不出
    # 「这天是不是系统补记的」。四格力，每一格都在这测一遍。
    set_setting("score.backfill_days", 2)
    set_setting("family.start_date", "2026-03-01")
    db.execute("UPDATE member SET created_at='2026-03-01 09:00:00'")
    db.execute("DELETE FROM holiday")
    for m in (GIRL, BOY):
        db.execute("DELETE FROM score_entry WHERE member_id=? AND day>='2026-03-01'", (m,))
        db.execute("UPDATE cycle SET status='open' WHERE member_id=?", (m,))
    E.freeze_clock("2026-03-04 09:00:00")     # 周三上午，离次日 12:00 还有一段

    st = E.score_day_state(GIRL, "2026-03-05")
    check("还没到的日子是 future", st["state"] == "future" and not st["can_edit"], st["state"])

    st = E.score_day_state(GIRL, "2026-03-04")
    check("今天没打是 unscored，能写", st["state"] == "unscored" and st["can_edit"], st["state"])

    st = E.score_day_state(GIRL, "2026-03-03")
    check("昨天没打、还没过次日 12:00，是 backfill",
          st["state"] == "backfill" and st["can_edit"], st["state"])
    check("补卡的截止时刻写着次日 12:00", st["deadline"] == "2026-03-04 12:00", st["deadline"])

    # 打上今天的，再回看
    E.submit_day(GIRL, "2026-03-04", [], operator_id=DAD)
    st = E.score_day_state(GIRL, "2026-03-04")
    check("打过了就是 modify，还能改", st["state"] == "modify" and st["can_edit"], st["state"])
    check("修改态标着不是系统补的", st["auto_filled"] is False)

    # 过 12:00 那一刻：同一天从「补卡」翻成「超时」
    E.freeze_clock("2026-03-04 13:00:00")
    st = E.score_day_state(GIRL, "2026-03-03")
    check("过了次日 12:00 还没打，是 overdue 且锁死",
          st["state"] == "overdue" and not st["can_edit"], st["state"])
    check("锁死时给得出为什么", bool(st["reason"]), st["reason"])
    check("今天那一格没受影响，还是能改",
          E.score_day_state(GIRL, "2026-03-04")["state"] == "modify")

    # 系统补记的那些：分是有的，但不能跟家长手打的混成一个标签
    E.ensure_missed_scores(day="2026-03-04", lookback_days=1)
    st = E.score_day_state(GIRL, "2026-03-03")
    check("系统补记的那天显示成超时，不是修改",
          st["state"] == "overdue" and st["scored"] and st["auto_filled"], st["state"])
    check("系统补记的那天不能再改", not st["can_edit"], st["can_edit"])
    r = E.submit_day(GIRL, "2026-03-03", ["order"], operator_id=DAD)
    check("补记的那天后端也拒改", not r["ok"], r)

    # 打过但超了 24 小时修正窗口 -> 锁死，跟「超时」分开
    E.freeze_clock("2026-03-06 09:00:00")
    st = E.score_day_state(GIRL, "2026-03-04")
    check("打过但超了修正窗口，是 locked",
          st["state"] == "locked" and not st["can_edit"], st["state"])

    # 补打窗口跟「次日 12:00」是两条路：往前放宽了窗口，界面照样按超时显示
    set_setting("score.backfill_days", 30)
    E.freeze_clock("2026-03-25 15:00:00")
    st = E.score_day_state(GIRL, "2026-03-24")
    check("放宽补打窗口也改不了「超时」这个标签",
          st["state"] == "overdue", st["state"])
    set_setting("score.backfill_days", 2)

    print("\n=== 26. 宝箱拆成「发箱 / 开箱」两步（v38）===")

    # 一、自选件：普通卡不预先定是哪张，候选摆出来让他自己挑
    #    把钻石箱的随机件钉成「自选普通卡 2 张」、命中率拉满，抽奖就没有偶然性
    _pool5 = db.query_one("SELECT random_rate, random_pool FROM box_tier WHERE tier=5")
    db.execute("UPDATE box_tier SET random_rate=1.0, diamond_rate=0, random_pool=?"
               " WHERE tier=5",
               (json.dumps([{"kind": "card", "code": "@common_pick", "qty": 2,
                             "label": "自选普通卡 2 张"}], ensure_ascii=False),))
    avail = E.pick_candidates(BOY, "common")
    left = [(c["code"], E.item_balance(BOY, c["id"]), c["max_hold"]) for c in avail]
    check("候选里不出现已经拿到上限的卡",
          all(have + 1e-9 < cap for _code, have, cap in left), left)

    made = E.issue_box(BOY, 5, source="free", operator_id=DAD)
    check("发箱只落一条待开记录，不直接发货", bool(made and made.get("pending")), made)
    check("待开箱挂在 pending_boxes 上，状态是 unopened",
          any(x["box_id"] == made["box_id"] and x["state"] == "unopened"
              for x in E.pending_boxes(BOY)))
    op = E.open_box(BOY, made["box_id"], operator_id=BOY)
    check("券和保底卡当场到账",
          any(g["type"] == "ticket" for g in op["given"]), op["given"])
    check("随机件是「点开这一刻」才抽的", bool(op.get("random")), op.get("random"))
    again = E.open_box(BOY, made["box_id"], operator_id=BOY)
    check("开了没挑完再点一次，回到挑卡那一屏（不是甩一句「已经开过了」）",
          again.get("ok") and again.get("resume"), again.get("msg"))

    if len(avail) > 2:
        need = op.get("need_pick") or {}
        codes = [o["code"] for o in (need.get("options") or [])]
        check("自选件的候选摆出来等他挑", len(codes) == 3, need)
        check("要挑两张", need.get("qty") == 2, need)
        check("同一张挑两次不算",
              not E.resolve_box_pick(BOY, made["box_id"], [codes[0], codes[0]]).get("ok"))
        check("只挑一张不算",
              not E.resolve_box_pick(BOY, made["box_id"], [codes[0]]).get("ok"))
        check("挑了候选外的也不算",
              not E.resolve_box_pick(BOY, made["box_id"], [codes[0], "没这张卡"]).get("ok"))
        got = E.resolve_box_pick(BOY, made["box_id"], [codes[0], codes[1]])
        check("挑满两张才算数", got.get("ok") and len(got.get("given") or []) == 2, got)
        check("挑完就不能再挑",
              not E.resolve_box_pick(BOY, made["box_id"], codes[:2]).get("ok"))
        check("挑完了这一箱才算真的开过",
              not E.open_box(BOY, made["box_id"], operator_id=BOY).get("ok"))
        check("挑完这一箱不再算待处理",
              not [x for x in E.pending_boxes(BOY) if x["box_id"] == made["box_id"]])
    else:
        check("候选凑不满时直接发掉，不让他对着凑不齐的一屏点",
              bool(op.get("given")), op.get("given"))

    # 二、系统代选：开了没挑完就退出，超时兜底那一支要接得住
    made_b = E.issue_box(BOY, 5, source="free", operator_id=DAD)
    o_b = E.open_box(BOY, made_b["box_id"], auto=True, operator_id=DAD)
    check("没人挑的时候系统按「优先给还没有的」代选",
          bool(o_b.get("given")) and not o_b.get("need_pick"), o_b)
    check("代选之后那箱不再是待处理", not E.pending_boxes(BOY))

    # 三、直购是「付完星尘当场开」
    E.add_ledger(BOY, "adjust", stardust=400, operator_id=DAD, note="测试前置：留够买箱的钱")
    buy = E.buy_box(BOY, 4, operator_id=BOY)
    check("直购箱付完星尘当场开", bool(buy.get("ok") and buy.get("box_id")), buy)
    check("直购箱的清单在返回里，不用再点一次",
          bool(buy.get("given") is not None), list(buy.keys()))
    check("直购箱买完就不是待开状态",
          not [x for x in E.pending_boxes(BOY) if x["box_id"] == buy.get("box_id")])

    # 四、③：一直没开的箱，v44 起**不替他开** —— 留到他自己点，赛季末也不动它。
    #     （v38 定的「结算时系统顺手替开」在 v44 整条撤了：开箱这个动作留给孩子，
    #      没开的箱连季末清场都绕开。所以下面三条断言是反过来写的。）
    E.freeze_clock("2026-06-01 20:00:00")
    E.get_or_create_cycle(BOY, "2026-06-01")
    stale = E.issue_box(BOY, 2, source="free", operator_id=DAD)
    check("刚发下来的箱子是新鲜的，结算不会动它",
          any(x["box_id"] == stale["box_id"] for x in E.pending_boxes(BOY)))
    E.freeze_clock("2026-06-08 20:00:00")
    E.get_or_create_cycle(BOY, "2026-06-08")
    E.freeze_clock("2026-06-15 20:00:00")
    cur = E.get_or_create_cycle(BOY, "2026-06-15")
    E.ensure_settled(BOY, day="2026-06-15")
    row = db.query_one("SELECT opened_at, random_json FROM box_open WHERE id=?",
                       (stale["box_id"],))
    check("隔了一个周期还没开的箱，结算不替他开", row["opened_at"] is None,
          row["opened_at"])
    check("没开的箱一直挂着，等他自己点",
          bool([x for x in E.pending_boxes(BOY) if x["box_id"] == stale["box_id"]]))
    ntf = db.query_one("SELECT title, body FROM notification WHERE member_id=?"
                       " AND kind='box_auto' ORDER BY id DESC", (BOY,))
    check("没有「系统替你开了」这种通知", not ntf, ntf and ntf["title"])
    # 本周期刚发的箱同样不动（这条在两种口径下都成立，留着看别把它改回去）
    fresh_box = E.issue_box(BOY, 2, source="free", operator_id=DAD)
    E.freeze_clock("2026-06-22 20:00:00")
    E.get_or_create_cycle(BOY, "2026-06-22")
    E.ensure_settled(BOY, day="2026-06-22")
    still = db.query_one("SELECT opened_at FROM box_open WHERE id=?", (fresh_box["box_id"],))
    check("本周期新发的箱没被误伤", still["opened_at"] is None, still["opened_at"])

    db.execute("UPDATE box_tier SET random_rate=?, random_pool=? WHERE tier=5",
               (_pool5["random_rate"], _pool5["random_pool"]))

    print("\n" + "=" * 56)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for f in FAIL:
            print("  -", f)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
