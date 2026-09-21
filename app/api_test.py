# -*- coding: utf-8 -*-
"""
接口巡检：不起服务器，直接走 dispatch，把每个端点都打一遍。
目的是抓 SQL 写错、参数取错、权限漏判这一类运行时问题。

和 smoke_test 一样，强制用 data/test/ 里的独立库，不碰正式数据。
"""
import os
import sys
import json
from datetime import timedelta

_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test")
os.environ["FAMILY_DATA_DIR"] = _TEST_DIR
os.environ["FAMILY_DB"] = os.path.join(_TEST_DIR, "family.db")

import db
import engine as E
import api
from api import ApiError
from api import auth as A

FAIL = []
DB_SKIP = []      # 因为「周期已经结算」这类前置条件跳过的小节，结尾一并列出来
DAD, MOM, GIRL, BOY = 1, 2, 3, 4
# 测试库每次重建，密码在这里统一设一遍，后面的用户名统一用成员名字
# v36：孩子的密码必须是 4 位数字（家长那条只卡长度），所以这两个孩子给数字串。
PW = {1: "pw1", 2: "pw2", 3: "3355", 4: "4477"}


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
    # v19 起登录要账号密码。测试库每次都是新的，密码留空会卡在「首次设置」，
    # 所以这里统一设一遍：账号名沿用迁移给的名字，密码 pwN。
    for m in db.query("SELECT * FROM member ORDER BY id"):
        db.execute("UPDATE member SET username=?, password_hash=? WHERE id=?",
                   (m["username"] or m["name"], A.hash_password(PW.get(m["id"], "pw")), m["id"]))
    db.execute("UPDATE setting SET value='30' WHERE key='score.backfill_days'")
    db.settings_all(force=True)


class Ctx(api.Ctx):
    pass


def set_study(mid, day, val):
    """直接写智识分当测试夹具。

    不走 /api/score —— 前面的分组可能已经把这个周期结算掉了，结算后不能再改分。
    这里要的只是"这天智识是 0 还是 1"，和周期状态无关。
    """
    dim = db.query_one("SELECT id FROM dimension WHERE code='study'")["id"]
    db.execute("UPDATE score_entry SET voided=1 WHERE member_id=? AND day=? AND dimension_id=?",
               (mid, day, dim))
    db.execute("INSERT INTO score_entry (member_id, cycle_id, day, dimension_id, value, is_fixed,"
               " mode, note, operator_id, created_at) VALUES (?,NULL,?,?,?,1,'school','',?,?)",
               (mid, day, dim, float(val), DAD, E.now()))


def set_setting(key, val):
    """直接写设置并刷缓存。不走 /api/settings —— 那是双人确认流程，
    这里要的是「让某道闸门的参数先定下来」这个前置条件本身。"""
    db.execute("UPDATE setting SET value=? WHERE key=?",
               (("true" if val else "false") if isinstance(val, bool)
                else json.dumps(val, ensure_ascii=False), key))
    db.settings_all(force=True)


def call(method, path, body=None, query=None, actor=None, expect_error=False):
    ctx = Ctx(actor, query or {}, body or {})
    try:
        r = api.dispatch(method, path, ctx)
    except ApiError as e:
        if expect_error:
            return {"_error": e.message}
        FAIL.append("%s %s -> %s" % (method, path, e.message))
        print("  [FAIL] %s %s  %s" % (method, path, e.message))
        return None
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAIL.append("%s %s -> %s" % (method, path, e))
        print("  [FAIL] %s %s  异常 %s" % (method, path, e))
        return None
    if expect_error:
        FAIL.append("%s %s 期望报错但通过了" % (method, path))
        print("  [FAIL] %s %s  期望报错但通过了" % (method, path))
    else:
        print("  [ok]   %s %s" % (method, path))
    return r


def main():
    fresh()
    api.load()
    dad = db.query_one("SELECT * FROM member WHERE id=?", (DAD,))
    mom = db.query_one("SELECT * FROM member WHERE id=?", (MOM,))
    girl = db.query_one("SELECT * FROM member WHERE id=?", (GIRL,))
    boy = db.query_one("SELECT * FROM member WHERE id=?", (BOY,))

    print("\n--- 未登录 ---")
    call("GET", "/api/bootstrap")
    call("GET", "/api/members", expect_error=True)
    call("GET", "/api/settings", expect_error=True)

    print("\n--- 登录与会话 ---")
    # 错密码和错账号报同一句话：外面试不出哪个账号存在
    call("POST", "/api/login", {"username": "妈妈", "password": "错的"}, expect_error=True)
    call("POST", "/api/login", {"username": "没这个人", "password": "3355"}, expect_error=True)
    # 还没设密码的账号进不来，也不能靠空密码混进去
    db.execute("UPDATE member SET password_hash='' WHERE id=?", (BOY,))
    call("POST", "/api/login", {"member_id": BOY, "password": ""}, expect_error=True)
    call("POST", "/api/login", {"member_id": BOY, "password": "4477"}, expect_error=True)
    db.execute("UPDATE member SET password_hash=? WHERE id=?", (A.hash_password("4477"), BOY))
    # v36：孩子不走账号那条路，只报成员号。两个口子各走各的，别互相串。
    r = call("POST", "/api/login", {"member_id": GIRL, "password": "3355"})
    check("孩子点头像进来拿到 token", bool(r and r.get("token")))
    check("进来的是本人，不是别人", bool(r and r["member"]["id"] == GIRL))
    # 家长入口「只给爸爸妈妈」得是真的：孩子的名字填进账号框也进不来
    call("POST", "/api/login", {"username": "女儿", "password": "3355"}, expect_error=True)
    call("POST", "/api/login", {"member_id": GIRL, "password": "3356"}, expect_error=True)
    call("GET", "/api/bootstrap")
    call("GET", "/api/members", actor=girl)

    print("\n--- 谁算管理员 ---")
    check("爸爸是管理员", bool(dad["is_admin"]))
    check("妈妈不是管理员", not mom["is_admin"])
    # 开通账号只有管理员能做：孩子不行，另一位家长也不行
    for who in (girl, mom):
        call("POST", "/api/members", {"name": "小姨", "role": "child", "username": "小姨",
                                      "password": "1111"}, actor=who, expect_error=True)
    r = call("POST", "/api/members", {"name": "小姨", "role": "child", "username": "小姨",
                                      "password": "1111"}, actor=dad)
    check("管理员能开通账号", bool(r and r.get("member_id")))
    call("POST", "/api/members", {"name": "奶奶", "role": "parent", "username": "奶奶",
                                  "password": "aaa3"}, actor=dad, expect_error=True)  # 家长已满 2 位
    call("POST", "/api/members", {"name": "小表弟", "role": "child", "username": "小姨",
                                  "password": "1112"}, actor=dad, expect_error=True)  # 账号名撞车
    call("POST", "/api/members", {"name": "小表弟", "role": "child", "username": "小表弟",
                                  "password": "12"}, actor=dad, expect_error=True)   # 孩子密码不是 4 位
    call("POST", "/api/members", {"name": "小表弟", "role": "child", "username": "小表弟",
                                  "password": "12345"}, actor=dad, expect_error=True)  # 五位也不行
    call("POST", "/api/members", {"name": "小表弟", "role": "child", "username": "小表弟",
                                  "password": "12a4"}, actor=dad, expect_error=True)  # 有字母不行
    # 「4 位数字可以」这一条不用再补一例：上面开小姨那个号走的就是这条路，
    # 而且孩子最多 3 个，再塞一个会先撞上名额上限，报出来的错跟密码无关。
    call("PATCH", "/api/members/5", {"name": "小姨子"}, actor=dad)
    call("PATCH", "/api/members/5", {"username": "小姨2"}, actor=mom, expect_error=True)
    call("POST", "/api/login", {"member_id": 5, "password": "1111"})

    print("\n--- 改密码与重置密码 ---")
    # 自己改自己的：旧密码必须对，新密码不能和旧的一样
    call("POST", "/api/me/password", {"old": "错的", "new": "3356"}, actor=girl, expect_error=True)
    call("POST", "/api/me/password", {"old": "3355", "new": "3355"}, actor=girl, expect_error=True)
    # 孩子的新密码也得是 4 位数字：这条规则在改密码这儿不能漏（改密是另一个入口）
    call("POST", "/api/me/password", {"old": "3355", "new": "123456"}, actor=girl, expect_error=True)
    call("POST", "/api/me/password", {"old": "3355", "new": "1111a"}, actor=girl, expect_error=True)
    call("POST", "/api/me/password", {"old": "3355", "new": "3356"}, actor=girl)
    call("POST", "/api/login", {"member_id": GIRL, "password": "3355"}, expect_error=True)
    call("POST", "/api/login", {"member_id": GIRL, "password": "3356"})
    # 重置别人：管理员谁都行，普通家长只对孩子
    call("POST", "/api/members/4/password", {"password": "4478"}, actor=girl, expect_error=True)
    call("POST", "/api/members/4/password", {"password": "4478"}, actor=mom)
    call("POST", "/api/members/2/password", {"password": "new2"}, actor=mom, expect_error=True)
    call("POST", "/api/members/2/password", {"password": "new2"}, actor=dad)
    call("POST", "/api/members/4/password", {"password": "12"}, actor=mom, expect_error=True)
    call("POST", "/api/members/4/password", {"password": "447a"}, actor=mom, expect_error=True)  # 孩子这条要纯数字
    call("DELETE", "/api/members/5", actor=dad)

    print("\n--- 打分 ---")
    days = []
    d = E.parse_day(E.today())
    for i in range(6, 0, -1):
        days.append(E.fmt(d.fromordinal(d.toordinal() - i + 1)))
    call("GET", "/api/score/day", query={"member_id": str(GIRL)}, actor=dad)
    call("GET", "/api/score/day", query={"member_id": str(BOY)}, actor=dad)
    for day in days:
        call("POST", "/api/score", {"member_id": GIRL, "day": day, "undone": []}, actor=dad)
    call("POST", "/api/score", {"member_id": GIRL, "day": days[-1], "undone": ["order"]}, actor=mom)
    call("GET", "/api/score/cycle", query={"member_id": str(GIRL)}, actor=dad)
    # v39：首页「这一周的七分」吃的是这一份 —— 每天七项的 0/1，外加一整份行定义
    # （今天这套维度）。界面不自己再拼一遍，拼出来的迟早跟打分页对不上。
    _wk = call("GET", "/api/score/cycle", query={"member_id": str(GIRL)}, actor=dad)
    _rows = _wk.get("dims") or []
    check("周期接口带上了七维度行定义", len(_rows) == 7, [r.get("code") for r in _rows])
    _recs = _wk.get("days") or []
    check("每一天都带上了这七项",
          bool(_recs) and all(len(r.get("dims") or []) == 7 for r in _recs),
          [len(r.get("dims") or []) for r in _recs][:3])
    _vals = [v.get("value") for r in _recs for v in (r.get("dims") or [])]
    check("值只有 1 / 0 / 空三种", all(v in (1, 0, None) for v in _vals),
          sorted(set(str(v) for v in _vals)))
    _scored = [r for r in _recs if r.get("scored")]
    check("打过分的那些天，七项都落成了 1 或 0",
          bool(_scored) and all(all(v.get("value") in (1, 0) for v in r["dims"]) for r in _scored),
          len(_scored))
    call("POST", "/api/score", {"member_id": BOY, "day": days[-1]}, actor=girl, expect_error=True)

    print("\n--- v13：家长只打分，不参与被打分 ---")
    for mid, who in ((DAD, "爸爸"), (MOM, "妈妈")):
        call("POST", "/api/score", {"member_id": mid, "day": days[-1], "undone": []},
             actor=dad, expect_error=True)
        call("GET", "/api/score/day", query={"member_id": str(mid)}, actor=dad,
             expect_error=True)
        call("GET", "/api/boxes", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/shop", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/holdings", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/catalog", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/report", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/cycle", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("GET", "/api/levels", query={"member_id": str(mid)}, actor=dad, expect_error=True)
        call("POST", "/api/explore", {"member_id": mid, "phrase": "给家长发星探"}, actor=mom,
             expect_error=True)
        call("POST", "/api/boxes/buy", {"member_id": mid, "tier": 4}, actor=dad,
             expect_error=True)
        call("POST", "/api/shop/buy", {"member_id": mid, "code": "ticket_fun"}, actor=dad,
             expect_error=True)
        call("POST", "/api/cash/request", {"member_id": mid, "stardust": 10}, actor=mom,
             expect_error=True)
        call("POST", "/api/tasks", {"assignee_id": mid, "title": "给家长派活", "std": "x"},
             actor=dad, expect_error=True)
        call("POST", "/api/wishes", {"member_id": mid, "title": "家长的心愿"}, actor=dad,
             expect_error=True)
        call("POST", "/api/calibration", {"member_id": mid, "reason": "测试"}, actor=dad,
             expect_error=True)
    # 家长自己调这些接口也不能给自己开绿灯
    call("POST", "/api/boxes/buy", {"tier": 4}, actor=dad, expect_error=True)
    call("GET", "/api/holdings", actor=dad, expect_error=True)
    call("POST", "/api/shop/buy", {"code": "ticket_fun"}, actor=dad, expect_error=True)
    dash = call("GET", "/api/dashboard", actor=dad)
    check("看板里家长是裁判状态",
          dash and all(m["today_state"] == "judge" for m in dash["members"]
                       if m["role"] != "child"),
          dash and [m["today_state"] for m in dash["members"]])
    check("看板不再给家长算周能量",
          dash and all(m["energy"] is None for m in dash["members"] if m["role"] != "child"),
          dash and [m["energy"] for m in dash["members"]])

    print("\n--- 星探 ---")
    call("POST", "/api/explore", {"member_id": GIRL, "phrase": "今天自己主动练了半小时琴",
                                  "kind": "stardust", "stardust": 5}, actor=dad)
    call("POST", "/api/explore", {"member_id": GIRL, "phrase": "", "kind": "energy"}, actor=dad,
         expect_error=True)
    call("GET", "/api/explore", query={"member_id": str(GIRL)}, actor=girl)
    call("POST", "/api/explore", {"member_id": GIRL, "phrase": "x"}, actor=girl, expect_error=True)

    print("\n--- 周期与宝箱 ---")
    call("GET", "/api/cycle", query={"member_id": str(GIRL)}, actor=dad)
    call("POST", "/api/cycle/settle", {"member_id": GIRL}, actor=dad)
    call("POST", "/api/cycle/settle-all", actor=dad)
    call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
    E.add_ledger(GIRL, "adjust", stardust=500, note="巡检注入")
    call("POST", "/api/boxes/buy", {"member_id": GIRL, "tier": 4}, actor=girl)
    call("POST", "/api/boxes/buy", {"member_id": GIRL, "tier": 1}, actor=girl, expect_error=True)
    call("GET", "/api/boxes/history", query={"member_id": str(GIRL)}, actor=girl)

    # v38：宝箱拆成「发箱」与「开箱」两步，开箱和自选各是一个接口
    print("\n--- 开箱与自选（v38）---")
    made = E.issue_box(GIRL, 3, source="free", operator_id=DAD)
    check("发下来的是一只待开箱", bool(made and made.get("pending")), made)
    home = call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
    check("待开箱挂在宝箱页的 pending 上",
          any(x["box_id"] == made["box_id"] for x in (home or {}).get("pending") or []),
          home and home.get("pending"))
    call("POST", "/api/boxes/%d/open" % made["box_id"], actor=dad, expect_error=True)
    call("POST", "/api/boxes/%d/pick" % made["box_id"], {"codes": []}, actor=boy,
         expect_error=True)
    opened = call("POST", "/api/boxes/%d/open" % made["box_id"], actor=girl)
    check("开箱接口回一份清单", bool(opened and "given" in opened and "random" in opened),
          opened)
    call("POST", "/api/boxes/%d/open" % made["box_id"], actor=girl, expect_error=True)
    home = call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
    check("开过的箱不再挂在待开提醒上",
          not [x for x in (home or {}).get("pending") or []
               if x["box_id"] == made["box_id"]],
          home and home.get("pending"))

    # 自选：把钻石箱的随机件钉成「自选普通卡 2 张」，命中率拉满
    _t5 = db.query_one("SELECT random_rate, random_pool FROM box_tier WHERE tier=5")
    db.execute("UPDATE box_tier SET random_rate=1.0, random_pool=? WHERE tier=5",
               (json.dumps([{"kind": "card", "code": "@common_pick", "qty": 2,
                             "label": "自选普通卡 2 张"}], ensure_ascii=False),))
    made2 = E.issue_box(GIRL, 5, source="free", operator_id=DAD)
    o2 = call("POST", "/api/boxes/%d/open" % made2["box_id"], actor=girl)
    codes = [x["code"] for x in ((o2 or {}).get("need_pick") or {}).get("options") or []]
    if codes:
        check("开箱返回里带着候选等他挑", len(codes) >= 1, codes)
        # 中途退出去再进来：重新点开这一箱该回到那一屏接着挑，而不是甩一句
        # 「已经开过了」—— 甩了等于把自选锁死，孩子只能等下个周期让系统代挑。
        back = call("POST", "/api/boxes/%d/open" % made2["box_id"], actor=girl)
        check("开过了还能回来接着挑",
              bool(back.get("resume") and back.get("need_pick")), back.get("msg"))
        call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
        call("POST", "/api/boxes/%d/pick" % made2["box_id"], {"codes": [codes[0]]},
             actor=girl, expect_error=True)
        call("POST", "/api/boxes/%d/pick" % made2["box_id"], {"codes": codes[:2]},
             actor=girl)
        home = call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
        check("挑完不再算待处理（unpicked 那一格）",
              not [x for x in (home or {}).get("pending") or []
                   if x["box_id"] == made2["box_id"]],
              home and home.get("pending"))
    else:
        print("  [skip] 这一轮没开出可挑的候选（卡池被持有上限卡住）")
    db.execute("UPDATE box_tier SET random_rate=?, random_pool=? WHERE tier=5",
               (_t5["random_rate"], _t5["random_pool"]))

    # 一直不开的箱子：搭下个周期结算由系统替他开掉，东西照发不回收，
    # 并且留下一条写着「这是系统干的」的通知。
    fun_id = E.item_by_code("ticket_fun")["id"]
    stale = E.issue_box(BOY, 3, source="free", operator_id=DAD)
    db.execute("UPDATE box_open SET ts=? WHERE id=?",
               ("2000-01-01 00:00:00", stale["box_id"]))
    tb = E.item_balance(BOY, fun_id)
    auto = E.auto_open_stale(BOY, "2010-01-01", operator_id=None)
    check("隔了一个周期的箱被系统开掉",
          any(x["box_id"] == stale["box_id"] for x in auto), auto)
    check("系统替他开的照发不回收", E.item_balance(BOY, fun_id) == tb + 6,
          (tb, E.item_balance(BOY, fun_id)))
    check("系统自己动手留下的通知写着是谁干的",
          any(n["kind"] == "box_auto" for n in db.query(
              "SELECT * FROM notification WHERE member_id=? ORDER BY id DESC LIMIT 20",
              (BOY,))))
    check("被系统开过的箱不再是待开箱",
          not [x for x in (call("GET", "/api/boxes", query={"member_id": str(BOY)},
                                actor=boy) or {}).get("pending") or []
               if x["box_id"] == stale["box_id"]])

    print("\n--- 星球等级（v13）---")
    lv = call("GET", "/api/levels", query={"member_id": str(GIRL)}, actor=girl)
    check("等级表有 10 档", lv and len(lv["tiers"]) == 10,
          lv and [t["title"] for t in lv["tiers"]])
    check("门槛是 25×n×(n−1)",
          lv and [t["threshold"] for t in lv["tiers"][:5]] == [0, 50, 150, 300, 500],
          lv and [t["threshold"] for t in lv["tiers"][:5]])
    check("等级按累计星尘算，不是余额",
          lv and lv["level"] and lv["level"]["total"] >= E.stardust_balance(GIRL),
          lv and (lv["level"] and lv["level"]["total"], E.stardust_balance(GIRL)))
    cyc_lv = call("GET", "/api/cycle", query={"member_id": str(GIRL)}, actor=girl)
    check("/api/cycle 也带上等级", cyc_lv and "level" in cyc_lv, cyc_lv and list(cyc_lv.keys()))

    print("\n--- 商店与道具 ---")
    call("GET", "/api/shop", query={"member_id": str(GIRL)}, actor=girl)
    # v24：六种券全上架，卡一张不卖，箱子只卖金 / 钻石 / 王者
    shop = call("GET", "/api/shop", query={"member_id": str(GIRL)}, actor=girl)
    check("六种券全上架",
          sorted(x["code"] for x in shop["tickets"]) ==
          ["ticket_choice", "ticket_company", "ticket_exempt", "ticket_friend",
           "ticket_fun", "ticket_solo"],
          [x["code"] for x in shop["tickets"]])
    check("卡区空了", shop["cards"] == [], shop["cards"])
    check("箱子只剩金 / 钻石 / 王者",
          [b["tier"] for b in shop["boxes"]] == [4, 5, 6],
          [b["name"] for b in shop.get("boxes", [])])
    check("价签照旧 105 / 160 / 260",
          [b["price"] for b in shop["boxes"]] == [105, 160, 260],
          [b["price"] for b in shop.get("boxes", [])])
    check("宝箱行带上了保底卡清单",
          [len(b["cards"]) for b in shop["boxes"]] == [0, 1, 2],
          [b["cards"] for b in shop["boxes"]])
    call("POST", "/api/shop/buy", {"member_id": GIRL, "code": "ticket_friend", "qty": 1}, actor=girl)
    call("POST", "/api/shop/buy", {"member_id": GIRL, "code": "friend_stay"}, actor=girl,
         expect_error=True)                 # v24 卡区下架
    call("POST", "/api/shop/buy", {"member_id": GIRL, "code": "ticket_fun", "qty": 2}, actor=girl)
    call("POST", "/api/shop/buy", {"member_id": GIRL, "code": "company_card"}, actor=girl,
         expect_error=True)
    call("POST", "/api/shop/buy", {"member_id": GIRL, "code": "wish_boost"}, actor=girl,
         expect_error=True)
    call("GET", "/api/holdings", query={"member_id": str(GIRL)}, actor=girl)
    # 券不再能直扣，要走核销申请（下面 v14 那组专门验这条）
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "ticket_fun", "qty": 1}, actor=girl,
         expect_error=True)
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "skin", "qty": 1}, actor=girl,
         expect_error=True)
    call("GET", "/api/catalog", query={"member_id": str(GIRL)}, actor=girl)
    call("POST", "/api/fragments/exchange", {"member_id": GIRL, "mode": "random"}, actor=girl,
         expect_error=True)

    print("\n--- 星尘与零花钱兑换（v24 三步）---")
    call("GET", "/api/cash", query={"member_id": str(GIRL)}, actor=girl)
    call("GET", "/api/cash/requests", actor=girl)
    call("GET", "/api/cash/requests", actor=dad)
    q = call("POST", "/api/cash/request", {"member_id": GIRL, "stardust": 60}, actor=girl)
    check("孩子发起兑换落到待审", q and q["status"] == "pending", q)
    call("POST", "/api/cash/request", {"member_id": GIRL, "stardust": 1}, actor=girl,
         expect_error=True)          # 在审的那 60 已经占满了本月额度
    call("POST", "/api/cash/requests/%d/received" % q["request_id"], {}, actor=girl,
         expect_error=True)          # 还没批就想确认收到，不行
    call("POST", "/api/cash/requests/%d/resolve" % q["request_id"], {"approve": True},
         actor=girl, expect_error=True)      # 孩子不能自己批
    call("POST", "/api/cash/requests/%d/resolve" % q["request_id"], {"approve": False},
         actor=dad, expect_error=True)       # 不同意必须写理由
    r = call("POST", "/api/cash/requests/%d/resolve" % q["request_id"], {"approve": True},
             actor=dad)
    check("家长同意就发放", r and r["status"] == "approved" and r["cash"] == 30, r)
    r = call("POST", "/api/cash/requests/%d/received" % q["request_id"], {}, actor=girl)
    check("孩子确认收到才算完", r and r["status"] == "received", r)
    call("GET", "/api/ledger", query={"member_id": str(GIRL)}, actor=girl)

    print("\n--- 券核销：机器闸门 + 家长点头（v14，v32 改成按轮算）---")
    # 闸门里有几道看时刻（续费窗口、晚间、硬停止）。时钟不钉住的话，
    # 同一份代码白天跑是绿的、晚上八点半之后再跑就红，而那种红指向的是空气。
    # 钉在当天 18:00，顺手把收工时间放宽：这组要测的是闸门本身，
    # 不是「现在是几点」。
    T_DAY = E.today() + " 18:00:00"
    E.freeze_clock(T_DAY)
    set_setting("ticket.curfew_school", "23:59")
    set_setting("ticket.curfew_weekend", "23:59")

    fun = E.item_by_code("ticket_fun")
    E.grant_item(GIRL, fun["id"], 6, note="巡检发放")     # 后面还要核销，先备足
    db.settings_all(force=True)

    st = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    check("快照带硬停止时间", st and ":" in str(st.get("curfew")), st and st.get("curfew"))
    check("快照带当前最多能申请几张", st and isinstance(st.get("max_qty_now"), int),
          st and st.get("max_qty_now"))
    check("快照带晚间起点与额度", st and st.get("evening_from") and st.get("evening_max") is not None,
          st and (st.get("evening_from"), st.get("evening_max")))
    check("快照带今天的申请历史", st and isinstance(st.get("today"), list))
    check("快照告诉前端核销要不要家长点头", st and st.get("need_approval") is True,
          st and st.get("need_approval"))
    call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=dad)
    call("GET", "/api/tickets/state", query={"member_id": str(DAD)}, actor=girl, expect_error=True)
    call("GET", "/api/tickets/state", query={"member_id": str(DAD)}, actor=dad, expect_error=True)

    # 「娱乐券面值」是设置项，必须真的说了算，不能是建库时写死的那个 30
    set_setting("ticket.entertainment_minutes", 45)
    st45 = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    check("改了「娱乐券面值」，接口给出的时长跟着变", st45 and st45.get("minutes") == 45,
          st45 and st45.get("minutes"))
    set_setting("ticket.entertainment_minutes", 30)

    print("\n--- 打分的口子只对家长开 ---")
    call("POST", "/api/score", {"member_id": GIRL, "day": E.today(), "undone": []}, actor=girl,
         expect_error=True)
    call("POST", "/api/score", {"member_id": BOY, "day": E.today(), "undone": []}, actor=girl,
         expect_error=True)
    call("POST", "/api/score", {"member_id": GIRL, "day": E.today(), "undone": []}, actor=dad,
         expect_error=True)          # 周期已结算，家长也改不了，只能走调整
    set_study(GIRL, E.today(), 0)
    db.settings_all(force=True)

    print("\n--- 申请前先过闸门 ---")
    # v23 把「学习前置」这条闸门撤了：学习做完没有，机器判断不了，
    # 那是家长在审核时该看的事。所以这里验的是反过来的那条 ——
    # 智识 0 分也照样能递申请，待办照常进家长那一栏。
    set_study(GIRL, E.today(), 0)
    db.settings_all(force=True)
    r = call("POST", "/api/tickets/request",
             {"member_id": GIRL, "code": "ticket_fun", "qty": 1}, actor=girl)
    check("学习没做完也能递申请，改由家长审核把关",
          r and r.get("mode") == "pending", r and r.get("mode"))
    if r and r.get("request_id"):
        call("POST", "/api/tickets/resolve",
             {"request_id": r["request_id"], "approve": False,
              "reject_note": "先把作业做完再说"}, actor=dad)
    set_study(GIRL, E.today(), 1)
    db.settings_all(force=True)

    r = call("POST", "/api/tickets/request",
             {"member_id": GIRL, "code": "ticket_fun", "qty": 2, "note": "看一集动画"}, actor=girl)
    check("闸门过了以后生成待办，不直接扣券",
          r and r.get("mode") == "pending" and r.get("request_id"), r and r.get("mode"))
    req_id = r and r.get("request_id")
    bal_after_apply = E.item_balance(GIRL, fun["id"])

    call("POST", "/api/tickets/request", {"member_id": GIRL, "code": "ticket_fun", "qty": 99}, actor=girl,
         expect_error=True)
    call("POST", "/api/tickets/request", {"member_id": DAD, "code": "ticket_fun", "qty": 1}, actor=girl,
         expect_error=True)
    call("POST", "/api/tickets/request", {"member_id": GIRL, "code": "nope", "qty": 1}, actor=girl,
         expect_error=True)

    print("\n--- 家长侧处理 ---")
    pend = call("GET", "/api/tickets/pending", actor=dad)
    check("家长能看到待办", pend and any(x["id"] == req_id for x in pend["items"]),
          pend and [x["id"] for x in pend["items"]])
    check("待办带「现在批了还能用吗」", pend and all("can_now" in x for x in pend["items"]))
    call("GET", "/api/tickets/pending", actor=girl, expect_error=True)
    call("POST", "/api/tickets/resolve", {"request_id": req_id, "approve": True}, actor=girl,
         expect_error=True)
    call("POST", "/api/tickets/resolve", {"request_id": req_id, "approve": False, "reject_note": ""},
         actor=dad, expect_error=True)
    r = call("POST", "/api/tickets/resolve", {"request_id": req_id, "approve": True}, actor=dad)
    check("家长同意后才扣券", r and r.get("approved") and
          E.item_balance(GIRL, fun["id"]) == bal_after_apply - 2,
          r and (E.item_balance(GIRL, fun["id"]), bal_after_apply))
    check("记了这一轮的开始与结束", r and r.get("used", {}).get("start_at") and
          r.get("used", {}).get("end_at"), r and r.get("used"))
    call("POST", "/api/tickets/resolve", {"request_id": req_id, "approve": True}, actor=dad,
         expect_error=True)

    print("\n--- 孩子侧看结果 ---")
    r = call("POST", "/api/tickets/request",
             {"member_id": GIRL, "code": "ticket_company", "qty": 1, "note": "想和爸爸下棋"}, actor=girl)
    cid = r and r.get("request_id")
    if cid:
        call("POST", "/api/tickets/resolve",
             {"request_id": cid, "approve": False, "reject_note": "今晚有客人，明晚陪你"}, actor=dad)
    mine = call("GET", "/api/tickets/mine", query={"member_id": str(GIRL)}, actor=girl)
    rej = [x for x in (mine or {}).get("items", []) if x["status"] == "rejected"]
    # 按内容找，不按下标：前面已经有一条被拒的了，rej[0] 不一定是被拒的那条陪伴券
    check("被拒的理由孩子看得到", any("明晚" in x["reject_note"] for x in rej), rej)
    check("孩子侧也带额度快照", mine and "state" in mine and "curfew" in mine["state"])
    call("GET", "/api/tickets/mine", query={"member_id": str(BOY)}, actor=girl, expect_error=True)

    print("\n--- 谁在玩（v27）---")
    # 刚批过 2 张娱乐券，这会儿正好在玩：孩子在 /mine 里看得到，家长在
    # /playing 里看得到，两边问的是同一件事实。
    mine = call("GET", "/api/tickets/mine", query={"member_id": str(GIRL)}, actor=girl)
    run = [x for x in (mine or {}).get("items", []) if x.get("running")]
    check("孩子那边看得到自己正在玩", bool(run), mine and mine.get("items"))
    check("正在玩的那条带着还剩多少分钟", run and run[0]["left_minutes"] > 0, run)
    check("孩子那边也单独给了一份「在玩」", mine and len(mine.get("playing") or []) == 1,
          mine and mine.get("playing"))

    pl = call("GET", "/api/tickets/playing", actor=dad)
    check("家长看得到谁在玩", pl and any(x["member_id"] == GIRL for x in pl["items"]),
          pl and pl["items"])
    check("家长那份带名字、还剩多久、起止时刻",
          pl and all(x.get("who") and x.get("left_minutes") is not None and x.get("end_at")
                     for x in pl["items"]), pl and pl["items"])
    pl1 = call("GET", "/api/tickets/playing", query={"member_id": str(GIRL)}, actor=dad)
    check("家长能按人筛", pl1 and all(x["member_id"] == GIRL for x in pl1["items"]))
    kid_self = call("GET", "/api/tickets/playing", actor=girl)
    check("孩子自己查得到自己那条", kid_self and len(kid_self["items"]) == 1, kid_self)
    # 孩子看别人的不是静默忽略，是直接报错：忽略参数以后最容易变成漏洞
    call("GET", "/api/tickets/playing", query={"member_id": str(BOY)}, actor=girl,
         expect_error=True)
    call("POST", "/api/tickets/resolve", {"approve": True}, actor=dad, expect_error=True)
    # v32 起一轮之内可以接着续，所以「刚批完再要 1 张」不再是错。这里改成测
    # 真正的边界：这一轮已经用掉 2 张、还剩 1 张，一次要 2 张就该拦。
    call("POST", "/api/tickets/request", {"member_id": GIRL, "code": "ticket_fun", "qty": 2},
         actor=girl, expect_error=True)

    # 这组结束，把时钟和收工时间还原，别影响后面的分组
    E.freeze_clock(None)
    set_setting("ticket.curfew_school", "21:30")
    set_setting("ticket.curfew_weekend", "22:00")

    print("\n--- 校准 ---")
    call("POST", "/api/calibration", {"member_id": GIRL, "level": 3, "reason": "说好 8 点回家",
                                      "effect_type": "task", "template": "apology"}, actor=mom)
    call("POST", "/api/calibration", {"member_id": BOY, "level": 3, "reason": "又反悔了",
                                      "effect_type": "fine"}, actor=mom)
    call("POST", "/api/calibration", {"member_id": BOY, "level": 2, "reason": "",
                                      "effect_type": "none"}, actor=mom, expect_error=True)
    call("GET", "/api/calibration", query={"member_id": str(GIRL)}, actor=mom)
    call("GET", "/api/calibration", query={"member_id": str(GIRL)}, actor=girl)

    print("\n--- 任务 ---")
    call("GET", "/api/tasks/templates", actor=dad)
    call("POST", "/api/tasks", {"assignee_id": GIRL, "title": "整理书架", "std": "三层都归位，家长只看结果",
                                "reward_type": "stardust", "reward": {"amount": 5}}, actor=dad)
    call("POST", "/api/tasks", {"assignee_id": GIRL, "title": "太多星尘", "std": "x",
                                "reward_type": "stardust", "reward": {"amount": 99}}, actor=dad,
         expect_error=True)
    call("POST", "/api/tasks", {"assignee_id": GIRL, "title": "要王者箱", "std": "x",
                                "reward_type": "box", "reward": {"tier": 6}}, actor=dad,
         expect_error=True)
    call("GET", "/api/tasks", actor=dad)
    call("GET", "/api/tasks", actor=girl)
    call("POST", "/api/tasks/1/submit", actor=girl)
    call("POST", "/api/tasks/1/confirm", actor=dad)
    boy = db.query_one("SELECT * FROM member WHERE id=?", (BOY,))
    call("POST", "/api/tasks/2/submit", actor=boy, expect_error=True)
    call("POST", "/api/tasks/2/submit", actor=girl)
    call("POST", "/api/tasks/archive", actor=dad)

    print("\n--- 心愿单与许愿池 ---")
    call("POST", "/api/pool", {"title": "一次露营", "target_desc": "在山上过一夜", "target_stardust": 400},
         actor=dad)
    call("GET", "/api/pool", actor=girl)
    call("POST", "/api/pool/deposit", {"member_id": GIRL, "stardust": 10}, actor=girl)

    # 三个动作：孩子许愿 → 家长定条件 → 达成兑现
    r = call("POST", "/api/wishes", {"title": "去天文馆", "reward_desc": "想看那个球幕"}, actor=girl)
    check("孩子许愿落到挂起", r and r.get("status") == "wished", r)
    wid = r["wish_id"]
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=girl)
    me = [x for x in got["items"] if x["id"] == wid][0]
    check("挂起的不给进度", me["progress"] is None)
    check("挂起的不占进行中名额",
          not [x for x in got["items"] if x["status"] == "active"])
    # v24：家长侧的审核页要能看到所有孩子挂起的愿。以前这个清单只在
    # 「设置 → 心愿单」弹层里，审核页压根没有，孩子那句「等爸爸妈妈定条件」
    # 就一直没人应。
    pw = call("GET", "/api/wishes/pending", actor=dad)
    check("家长一处看到所有挂起的心愿",
          pw and any(x["id"] == wid for x in pw["items"]), pw and pw["items"])
    check("每条带上是谁许的", all(x.get("who") for x in pw["items"]), pw and pw["items"])
    call("GET", "/api/wishes/pending", actor=girl, expect_error=True)   # 孩子看不了
    # 孩子就算硬塞条件参数也没用：走的是许愿那条路，条件一律留白
    r2 = call("POST", "/api/wishes",
              {"title": "自己偷偷加条件", "cond_type": "fixed", "cond": {"value": 1}}, actor=girl)
    check("孩子建的心愿不带条件",
          db.query_one("SELECT cond_type FROM wish WHERE id=?", (r2["wish_id"],))["cond_type"] == "")
    # 定条件是家长的动作
    call("POST", "/api/wishes/%d/configure" % wid,
         {"cond_type": "fixed", "cond": {"value": 1}}, actor=girl, expect_error=True)
    call("POST", "/api/wishes/%d/configure" % wid,
         {"cond_type": "fixed", "cond": {"value": 99999}}, actor=dad)
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    me = [x for x in got["items"] if x["id"] == wid][0]
    check("点亮后带上进度", me["status"] == "active" and me["progress"]["known"], me["progress"])
    check("门槛 99999 分够不着", not me["progress"]["ready"], me["progress"]["text"])
    # 进度没满不许登记达成 —— 达成是事实，不是点一下就有
    call("POST", "/api/wishes/%d/status" % wid, {"status": "achieved"}, actor=girl, expect_error=True)
    # 已经生效的条件不许再改
    r = call("POST", "/api/wishes/%d/configure" % wid, {"cond_type": "fixed"}, actor=dad,
             expect_error=True)
    check("条件定下后不许再改", "待定" in (r or {}).get("_error", ""), r)

    # 门槛不许是 0，也不许缺 —— 「做到 0 个」不算条件，缺值更不该被悄悄补成默认数
    call("POST", "/api/wishes", {"member_id": GIRL, "title": "门槛 0",
                                 "cond_type": "fixed", "cond": {"value": 0}}, actor=dad,
         expect_error=True)
    call("POST", "/api/wishes", {"member_id": GIRL, "title": "没填门槛",
                                 "cond_type": "fixed", "cond": {}}, actor=dad, expect_error=True)

    # 门槛设成够得着的，孩子自己就能登记达成
    r3 = call("POST", "/api/wishes", {"member_id": GIRL, "title": "够得着的",
                                      "cond_type": "fixed", "cond": {"value": 1}}, actor=dad)
    w3 = r3["wish_id"]
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    me = [x for x in got["items"] if x["id"] == w3][0]
    check("门槛 1 分默认达成", me["progress"]["ready"], me["progress"]["text"])
    call("POST", "/api/wishes/%d/status" % w3, {"status": "achieved"}, actor=girl)
    # 不设否决权：达成之后谁也取消不了
    call("POST", "/api/wishes/%d/status" % w3, {"status": "cancelled"}, actor=dad, expect_error=True)
    # 兑现是家长的事
    call("POST", "/api/wishes/%d/status" % w3, {"status": "claimed"}, actor=girl, expect_error=True)
    call("POST", "/api/wishes/%d/status" % w3, {"status": "claimed"}, actor=dad)
    # 驳回挂起的
    call("POST", "/api/wishes/%d/status" % r2["wish_id"], {"status": "cancelled"}, actor=dad)

    # 星尘自付：攒够了要自己点一下才付掉
    r4 = call("POST", "/api/wishes", {"member_id": GIRL, "title": "付不起的",
                                      "cond_type": "stardust", "cond": {"value": 99999}}, actor=dad)
    w4 = r4["wish_id"]
    call("POST", "/api/wishes/%d/pay" % w4, actor=girl, expect_error=True)
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    me = [x for x in got["items"] if x["id"] == w4][0]
    check("余额不够时不报可以付", not me["progress"]["can_pay"], me["progress"]["text"])
    # 让位，进行中名额只有 2 个
    call("POST", "/api/wishes/%d/status" % w4, {"status": "cancelled"}, actor=dad)

    r5 = call("POST", "/api/wishes", {"member_id": GIRL, "title": "付得起的",
                                      "cond_type": "stardust", "cond": {"value": 5}}, actor=dad)
    w5 = r5["wish_id"]
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    me = [x for x in got["items"] if x["id"] == w5][0]
    check("余额够了报可以付，但还没达成",
          me["progress"]["can_pay"] and not me["progress"]["ready"], me["progress"]["text"])
    bal0 = E.stardust_balance(GIRL)
    call("POST", "/api/wishes/%d/pay" % w5, actor=girl)
    check("付掉后余额真的少了", E.stardust_balance(GIRL) == bal0 - 5,
          "%g → %g" % (bal0, E.stardust_balance(GIRL)))
    call("POST", "/api/wishes/%d/pay" % w5, actor=girl, expect_error=True)   # 不许付第二遍
    # 别人的心愿碰不得
    call("POST", "/api/wishes/%d/pay" % w5, actor=boy, expect_error=True)
    # 撤回要退钱
    call("POST", "/api/wishes/%d/status" % w5, {"status": "cancelled"}, actor=girl)
    check("撤回后自付的星尘全额退回", E.stardust_balance(GIRL) == bal0)
    call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)

    print("\n--- 加时与求助 ---")
    call("POST", "/api/overtime", {"member_id": GIRL, "minutes": 30, "reason": "这集还差一点看完"}, actor=girl)
    call("GET", "/api/overtime", actor=dad)
    call("POST", "/api/overtime/1/resolve", {"approve": False, "reject_note": ""}, actor=dad,
         expect_error=True)
    call("POST", "/api/overtime/1/resolve", {"approve": True}, actor=dad)
    call("POST", "/api/help", {"member_id": GIRL, "detail": "数学第 8 题卡住了，不会列方程"}, actor=girl)
    call("GET", "/api/help", actor=dad)
    call("POST", "/api/help/1/verify", {"approved": True}, actor=dad)

    print("\n--- 假期 ---")
    call("GET", "/api/holidays", actor=dad)
    call("POST", "/api/holidays", {"name": "寒假", "start_date": "2027-01-20", "end_date": "2027-02-20"},
         actor=dad)
    call("POST", "/api/holidays", {"name": "错的", "start_date": "2027-03-01", "end_date": "2027-02-01"},
         actor=dad, expect_error=True)
    call("POST", "/api/holidays/delay", actor=dad)
    call("DELETE", "/api/holidays/1", actor=dad)

    print("\n--- 报告与看板 ---")
    call("GET", "/api/dashboard", actor=dad)
    call("GET", "/api/dashboard", actor=girl, expect_error=True)
    call("GET", "/api/report", query={"member_id": str(GIRL)}, actor=dad)
    call("GET", "/api/report", query={"member_id": str(GIRL)}, actor=girl)
    call("GET", "/api/notifications", actor=dad)
    call("POST", "/api/notifications/read", actor=dad)

    print("\n--- 任务大厅：领取 / 放弃 / 撤销（v15）---")
    set_setting("task.stardust_weekly_cap", 999)
    r = call("POST", "/api/tasks", {"title": "擦一次全家地板", "std": "客厅两个房间都擦过",
                                    "reward_type": "stardust", "reward": {"amount": 5},
                                    "open_to_all": True, "slots": 1}, actor=dad)
    hall1 = r["task_id"]
    h = call("GET", "/api/tasks/hall", actor=dad)
    check("家长看到大厅那一条", any(x["id"] == hall1 for x in h["hall"]), len(h["hall"]))
    h = call("GET", "/api/tasks/hall", actor=girl)
    check("孩子也看得到（全公开）", any(x["id"] == hall1 for x in h["hall"]))
    check("孩子的卡片上能领", all(x.get("can_claim") for x in h["hall"]))
    r = call("POST", "/api/tasks/%d/claim" % hall1, actor=girl)
    tid1 = r["task_id"]
    call("POST", "/api/tasks/%d/claim" % hall1, actor=boy, expect_error=True)
    call("POST", "/api/tasks/%d/claim" % hall1, actor=dad, expect_error=True)
    call("POST", "/api/tasks/%d/revoke" % hall1, actor=dad, expect_error=True)
    call("POST", "/api/tasks/%d/revoke" % hall1, actor=girl, expect_error=True)
    call("POST", "/api/tasks/%d/abandon" % tid1, actor=boy, expect_error=True)
    h = call("GET", "/api/tasks/hall", actor=girl)
    check("孩子看到自己领的那份", any(x["id"] == hall1 and x.get("mine") for x in h["mine"]))
    call("POST", "/api/tasks/%d/abandon" % tid1, actor=girl)
    call("POST", "/api/tasks/%d/revoke" % hall1, actor=dad)

    r = call("POST", "/api/tasks", {"title": "整理自己的书桌", "std": "桌面清空，书码好",
                                    "reward_type": "stardust", "reward": {"amount": 2},
                                    "open_to_all": True, "slots": 0}, actor=dad)
    hall2 = r["task_id"]
    a1 = call("POST", "/api/tasks/%d/claim" % hall2, actor=girl)["task_id"]
    call("POST", "/api/tasks/%d/claim" % hall2, actor=boy)
    call("POST", "/api/tasks/%d/claim" % hall2, actor=girl, expect_error=True)
    call("POST", "/api/tasks/%d/submit" % a1, actor=girl)
    call("POST", "/api/tasks/%d/confirm" % a1, actor=dad)
    call("POST", "/api/tasks/%d/revoke" % hall2, actor=dad, expect_error=True)
    h = call("GET", "/api/tasks/hall", actor=dad)
    card = [x for x in h["hall"] if x["id"] == hall2]
    check("每人一份的还留在等人领", len(card) == 1)
    check("卡片记着交成了一份", card and card[0]["done"] == 1, card[0]["done"] if card else None)

    r = call("POST", "/api/tasks", {"title": "背二十个单词", "std": "默写全对",
                                    "assignee_id": GIRL, "reward": {"amount": 1}}, actor=dad)
    call("POST", "/api/tasks/%d/claim" % r["task_id"], actor=boy, expect_error=True)
    call("POST", "/api/tasks", {"title": "没指定人", "std": "x"}, actor=dad, expect_error=True)

    print("\n--- 孩子数据总览（v15）---")
    r = call("GET", "/api/kids/overview", actor=dad)
    check("速览一次给出所有孩子", len(r["items"]) == 2, len(r["items"]))
    check("速览卡带今日得分", all("today" in x for x in r["items"]))
    check("速览卡带拥有物", all("holdings" in x and "tickets" in x["holdings"] for x in r["items"]))
    check("速览卡带在做的事", all("doing" in x for x in r["items"]))
    call("GET", "/api/kids/overview", actor=girl, expect_error=True)
    r = call("GET", "/api/kids/%d/detail" % GIRL, actor=dad)
    check("详细页给这一周七天", len(r["week"]) == 7, len(r["week"]))
    check("详细页带券和卡明细", "tickets" in r and "cards" in r)
    call("GET", "/api/kids/%d/detail" % GIRL, actor=girl, expect_error=True)
    call("GET", "/api/kids/9999/detail", actor=dad, expect_error=True)
    r = call("GET", "/api/score/history", actor=dad,
             query={"member_id": str(GIRL), "days": "14"})
    check("记录页天数对得上", len(r["days"]) == 14, len(r["days"]))
    check("记录页每天七格", all(len(x["cells"]) == 7 for x in r["days"]))
    check("记录页有各维度达成率", len(r["dims"]) == 7, len(r["dims"]))
    call("GET", "/api/score/history", actor=girl, query={"days": "7"})
    r = call("GET", "/api/score/history", actor=boy,
             query={"member_id": str(GIRL), "days": "7"})
    check("孩子传别人的 id 只会拿到自己的", r["member_id"] == BOY, r["member_id"])

    print("\n--- 首页动态（v18）---")
    r = call("GET", "/api/feed", actor=dad)
    check("家长能不指定孩子拿全部", "items" in r and "recent" in r)
    check("家长那份每条都带「是谁」", all(x.get("who") for x in r["items"]),
          [x.get("who") for x in r["items"]])
    r2 = call("GET", "/api/feed", actor=dad, query={"member_id": str(GIRL)})
    check("家长能只看一个孩子",
          all(x["member_id"] == GIRL for x in r2["items"]),
          sorted({x["member_id"] for x in r2["items"]}))
    r3 = call("GET", "/api/feed", actor=girl)
    check("孩子只会拿到自己的", all(x["member_id"] == GIRL for x in r3["items"]),
          sorted({x["member_id"] for x in r3["items"]}))
    # 孩子传别人的 id：接口按登录者取，不会真的把别人的数据给出去
    r4 = call("GET", "/api/feed", actor=boy, query={"member_id": str(GIRL)})
    check("孩子传别人的 id 只会拿到自己的", all(x["member_id"] == BOY for x in r4["items"]),
          sorted({x["member_id"] for x in r4["items"]}))
    call("GET", "/api/feed", actor=dad, query={"member_id": str(DAD)}, expect_error=True)
    call("GET", "/api/feed", actor=dad, query={"limit": "3", "recent": "2"})

    print("\n--- 设置与运维 ---")
    call("GET", "/api/settings", actor=dad)
    call("POST", "/api/settings", {"key": "ticket.entertainment_minutes", "value": 25}, actor=dad)
    # 双人确认默认关：一个人改就生效。要验那条流程得先把它打开，
    # 验完关回去 —— 家里通常只有一个人管这些数字，默认不该多一道手续。
    set_setting("ops.settings_double_confirm", True)
    call("POST", "/api/settings", {"key": "ticket.entertainment_minutes", "value": 26}, actor=dad)
    call("GET", "/api/settings", actor=dad)
    call("POST", "/api/settings/changes/1/approve", actor=dad, expect_error=True)
    call("POST", "/api/settings/changes/1/approve", actor=mom)
    set_setting("ops.settings_double_confirm", False)
    r_dc = call("POST", "/api/settings", {"key": "ticket.entertainment_minutes", "value": 25}, actor=dad)
    check("关掉之后一个人改就生效", r_dc and "已更新" in r_dc.get("message", ""),
          r_dc and r_dc.get("message"))
    call("POST", "/api/settings", {"key": "redline.no_humiliation", "value": False}, actor=dad,
         expect_error=True)
    call("POST", "/api/settings", {"key": "not.exist", "value": 1}, actor=dad, expect_error=True)
    call("POST", "/api/me/password", {"old": "pw1", "new": "pw1b"}, actor=dad)
    call("GET", "/api/audit", actor=dad)
    call("POST", "/api/ops/snapshot", actor=dad)
    call("GET", "/api/ops/snapshots", actor=dad)
    call("GET", "/api/ops/export", actor=dad)
    call("GET", "/api/nope", actor=dad, expect_error=True)

    print("\n--- 首次设置（v19）---")
    # 把库退回「谁都没设过密码」，模拟升级后第一次打开
    db.execute("UPDATE member SET password_hash=''")
    check("回到首次运行状态", A.is_first_run())
    call("POST", "/api/setup/admin", {"username": "老爸", "password": "12"}, expect_error=True)
    call("POST", "/api/setup/admin", {"username": "妈", "password": "abcd"}, expect_error=True)
    call("POST", "/api/setup/admin", {"username": "妈妈", "password": "abcd"},
         expect_error=True)                      # 别人的账号名，不能用
    # 用自己的现有名字（迁移填的那个）必须能过。
    # 早先这里把「自己」也算成重名，表现是点「设好，进去」永远 400。
    r = call("POST", "/api/setup/admin", {"username": "爸爸", "password": "abcd"})
    check("首次设置拿到 token", bool(r and r.get("token")))
    check("设完就不再是首次运行", not A.is_first_run())
    a2 = db.query_one("SELECT * FROM member WHERE id=?", (DAD,))
    check("管理员还是原来那个人", a2["is_admin"] == 1)
    check("管理员账号名就是自己原来那个", a2["username"] == "爸爸", a2["username"])
    check("密码能对上", A.check_password("abcd", a2["password_hash"]))
    # 口子必须关上：再调一次就等于谁都能把自己设成管理员
    call("POST", "/api/setup/admin", {"username": "别人", "password": "abcd"}, expect_error=True)
    r = call("POST", "/api/login", {"username": "爸爸", "password": "abcd"})
    check("新设的账号能登录", bool(r and r.get("token")))

    print("\n--- 推送（v20）---")
    srv, got, fake = start_fake_bark()
    try:
        _push_cases(got, fake, dad, girl, mom)
    finally:
        srv.shutdown()

    print("\n--- 图标（v21）---")
    _icon_cases(dad, girl, mom)

    print("\n--- 事件通道与护栏（v21 修补）---")
    _event_cases(dad, girl, mom)

    print("\n--- 卡片效果（v22）---")
    _card_cases(dad, girl, mom, boy)

    print("\n--- 心愿条件 / 商店箱子口径 / 头像（v25）---")
    _v25_cases(dad, girl, mom, boy)

    print("\n" + "=" * 56)
    if DB_SKIP:
        print("跳过 %d 处（前置条件不成立，不算失败）：" % len(DB_SKIP))
        for s in DB_SKIP:
            print("  ~", s)
    if FAIL:
        print("失败 %d 项：" % len(FAIL))
        for f in FAIL:
            print("  -", f)
        return 1
    print("接口巡检全部通过。")
    return 0


def start_fake_bark():
    """起一个假 Bark 端点。

    推送这块唯一不能真发的东西就是「手机」。其余全链路（取通知、分组、
    合并、免打扰、拼 JSON、重试、写回 pushed_at）都能打到一个本地端口上验。
    项目一贯的做法是测试不碰外部网络，这里也一样。
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    got = []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            try:
                got.append(json.loads(raw.decode("utf-8")))
            except ValueError:
                got.append({"_raw": raw.decode("utf-8", "replace")})
            body = b'{"code":200,"message":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got, "http://127.0.0.1:%d" % srv.server_address[1]


def _drain():
    """把还没推的通知标记成已推，给下一个用例一个干净的起点。"""
    db.execute("UPDATE notification SET pushed_at=? WHERE pushed_at IS NULL", (db.now(),))


def _push_cases(got, fake, dad, girl, mom):
    import notify as N
    from datetime import datetime as DT
    from datetime import timedelta as TD

    # 免打扰先关掉，后面单独测
    set_setting("push.enabled", True)
    set_setting("push.merge_seconds", 0)
    set_setting("push.quiet_start", "00:00")
    set_setting("push.quiet_end", "00:00")
    _drain()

    r = call("GET", "/api/push", actor=dad)
    check("家长能打开配置页", r["is_parent"] and len(r["members"]) == 4, len(r["members"]))
    check("一开始没有人配过设备", r["items"] == [], r["items"])
    check("全局项跟着一起回来", "push.enabled" in r["globals"])

    # --- 权限 ---
    call("POST", "/api/push/target", {"target": "short"}, actor=dad, expect_error=True)
    call("POST", "/api/push/target",
         {"member_id": str(DAD), "target": "dadkey0000FFFF", "server": fake}, actor=girl,
         expect_error=True)
    call("POST", "/api/push/settings", {"push.enabled": False}, actor=girl, expect_error=True)
    call("GET", "/api/push", actor=girl)          # 孩子能看自己的

    # --- 配设备 ---
    dad_t = call("POST", "/api/push/target",
                 {"member_id": str(DAD), "target": "dadkey0000FFFF", "server": fake,
                  "label": "爸爸手机"}, actor=dad)["id"]
    girl_t = call("POST", "/api/push/target",
                  {"member_id": str(GIRL), "target": "girlkey0000GGGG", "server": fake,
                   "label": "女儿手机"}, actor=dad)["id"]
    # 孩子自己给自己配一台
    call("POST", "/api/push/target", {"target": "girlpad0000HHHH", "server": fake,
                                      "label": "女儿的平板"}, actor=girl)
    check("女儿的号上有两台设备",
          len([x for x in call("GET", "/api/push", actor=girl)["items"]]) == 2)

    # --- 密钥不回显 ---
    r = call("GET", "/api/push", actor=dad)
    mine = [x for x in r["items"] if x["member_id"] == DAD][0]
    check("列表只回后四位", mine["masked"].endswith("FFFF") and "dadkey" not in mine["masked"],
          mine["masked"])
    check("整个响应里搜不到明文 key", "dadkey0000FFFF" not in json.dumps(r),
          "明文漏出去了")
    # 不传 target 表示只改备注，不动钥匙
    call("POST", "/api/push/target", {"id": dad_t, "label": "爸爸的手机"}, actor=dad)
    after = db.query_one("SELECT * FROM push_target WHERE id=?", (dad_t,))
    check("不传 key 时钥匙保持原样", after["target"] == "dadkey0000FFFF", after["target"])
    check("备注改掉了", after["label"] == "爸爸的手机", after["label"])

    # --- 测试按钮 ---
    got.clear()
    call("POST", "/api/push/test", {"id": dad_t}, actor=dad)
    check("测试通知发出去了", len(got) == 1, len(got))
    check("发到的是这台设备", got and got[0]["device_key"] == "dadkey0000FFFF")
    check("带上标题和正文", got and got[0]["title"] == "测试通知" and got[0]["body"])

    # --- 真实事件：孩子提交任务 ---
    got.clear()
    _drain()
    tid = E.create_task(GIRL, "整理书架", "把两层书架按高矮排好", "stardust", {"amount": 3},
                        created_by=DAD)
    E.submit_task(tid, GIRL)
    n = N.scan_once()
    check("家长收到了任务提交通知", len(got) == 1, len(got))
    check("收件人是家长那台（孩子的设备没响）",
          got and got[0]["device_key"] == "dadkey0000FFFF", got)
    check("同一条不会发第二遍", N.scan_once() == 0 and len(got) == 1, len(got))

    # 会员没配设备的那位不会收到，也没人替他收
    check("妈妈没配设备，一条都没发到她那",
          all(g["device_key"] != "mom" for g in got))

    # --- 合并窗口 ---
    got.clear()
    _drain()
    set_setting("push.merge_seconds", 3600)
    E.push_notify(None, "task_submitted", "有待确认的任务", "甲")
    E.push_notify(None, "task_submitted", "有待确认的任务", "乙")
    N.scan_once()
    check("窗口内的先攒着不发", len(got) == 0, len(got))
    set_setting("push.merge_seconds", 0)
    N.scan_once()
    check("窗口过了合并成一条", len(got) == 1, len(got))
    check("标题上写明几条", got and "（2 条）" in got[0]["title"], got and got[0]["title"])
    check("正文把两件都带上了", got and "甲" in got[0]["body"] and "乙" in got[0]["body"],
          got and got[0]["body"])

    # --- 免打扰 ---
    got.clear()
    _drain()
    set_setting("push.quiet_start", "22:00")
    set_setting("push.quiet_end", "07:00")
    check("下午 2 点不算", not N._in_quiet(DT(2026, 1, 1, 14, 0)))
    check("22:30 在 22:00-07:00 里", N._in_quiet(DT(2026, 1, 1, 22, 30)))
    check("凌晨 6 点在 22:00-07:00 里", N._in_quiet(DT(2026, 1, 1, 6, 0)))
    # 窗口按真实时钟前后各放宽一分钟，这样「现在」必然落在里面。
    # 不能靠给 scan_once 传一个假时间来测 —— 通知的 ts 是真实时间，
    # 拿假时间减真时间会得到负数，所有消息都被当成「刚写下的」而卡在窗口里。
    now = DT.now()
    set_setting("push.quiet_start", (now - TD(minutes=1)).strftime("%H:%M"))
    set_setting("push.quiet_end", (now + TD(minutes=1)).strftime("%H:%M"))
    E.push_notify(None, "task_submitted", "夜里的普通通知", "不该现在发")
    N.scan_once()
    check("免打扰里普通通知压着不发", len(got) == 0, len(got))
    E.push_notify(None, "ticket", "有券要用", "这条带时限")
    N.scan_once()
    check("带时限的穿过免打扰", len(got) == 1, len(got))
    check("带时限的标成 timeSensitive", got and got[0].get("level") == "timeSensitive", got)
    # 免打扰一解除，压着的那条该出来
    set_setting("push.quiet_start", "00:00")
    set_setting("push.quiet_end", "00:00")
    N.scan_once()
    check("出了免打扰时段就补发", len(got) == 2, len(got))

    # --- 推失败不能把队列堵死 ---
    got.clear()
    _drain()
    set_setting("push.enabled", True)
    bad = call("POST", "/api/push/target",
               {"member_id": str(MOM), "target": "badkey0000ZZZZ",
                "server": "http://127.0.0.1:1", "label": "连不上的那台"}, actor=dad)["id"]
    E.push_notify(MOM, "task_confirmed", "只发给妈妈", "测重试")
    for _ in range(3):
        N.scan_once()
    row = db.query_one("SELECT * FROM notification WHERE kind='task_confirmed'"
                       " ORDER BY id DESC LIMIT 1")
    check("三次都失败后记下错误并停手",
          row["push_error"] != "" and row["push_tries"] >= 3,
          "%r tries=%s" % (row["push_error"], row["push_tries"]))
    trow = db.query_one("SELECT * FROM push_target WHERE id=?", (bad,))
    check("失败次数记在设备上，界面上看得见", trow["fail_count"] >= 3, trow["fail_count"])
    check("失败原因里不带 device key", "badkey" not in (trow["last_err"] or ""),
          trow["last_err"])

    # --- 全局设置白名单 ---
    call("POST", "/api/push/settings", {"push.merge_seconds": 15, "redline.no_humiliation": False},
         actor=dad)
    check("白名单外的改不动", db.cfg("redline.no_humiliation") is True)
    check("白名单内的改了", int(db.cfg("push.merge_seconds")) == 15, db.cfg("push.merge_seconds"))

    # --- 总开关 ---
    set_setting("push.enabled", False)
    got.clear()
    _drain()
    E.push_notify(None, "task_submitted", "关掉推送之后", "不该发")
    N.scan_once()
    check("总开关关掉就完全不发", len(got) == 0, len(got))
    set_setting("push.enabled", True)

    # --- 删设备 ---
    call("DELETE", "/api/push/target/%d" % DAD, actor=girl, expect_error=True)
    call("DELETE", "/api/push/target/%d" % girl_t, actor=girl)
    r = call("GET", "/api/push", actor=girl)
    check("删掉后少一台", len(r["items"]) == 1, len(r["items"]))


def _icon_cases(dad, girl, mom):
    """图标这一版的断言。

    重点不是「能不能存」，而是那几条容易翻车的：
      · 孩子能不能顺手给自己改图（不能）
      · 越界的 kind 和不存在的主键（不能写）
      · 塞进 HTML 的字符（要被掐掉，因为它最终会被拼进页面）
    """
    import engine as E

    check("清空图标用的清洗函数", E.clean_icon("<script>x</script>") == "scriptxscript",
          E.clean_icon("<script>x</script>"))
    check("清洗能掐掉引号与反斜杠", E.clean_icon('a"b\'c\\d') == "abcd")
    check("空值清洗完还是空", E.clean_icon(None) == "" and E.clean_icon("  ") == "")
    # emoji 是码点，不能被洗掉
    check("emoji 不被清洗掉", E.clean_icon("🦖") == "🦖", E.clean_icon("🦖"))
    check("汉字不被清洗掉", E.clean_icon("心") == "心")

    lst = call("GET", "/api/icon/list", actor=dad)
    check("清单里有七维度", len(lst["dims"]) == 7, len(lst["dims"]))
    check("清单里有宝箱七档", len(lst["boxes"]) == 7, len(lst["boxes"]))
    check("清单里有 29 件道具", len(lst["items"]) == 29, len(lst["items"]))
    check("29 件道具全都有图了", all(x["icon"] for x in lst["items"]),
          [x["key"] for x in lst["items"] if not x["icon"]])
    check("七维度全都有图了", all(x["icon"] for x in lst["dims"]),
          [x["key"] for x in lst["dims"] if not x["icon"]])
    check("宝箱七档全都有图", all(x["icon"] for x in lst["boxes"]))
    check("完美箱用的是「已打开」那张", lst["boxes"][-1]["icon"] == "rw_box_open",
          lst["boxes"][-1]["icon"])

    # --- 权限 ---
    call("POST", "/api/icon", {"kind": "dimension", "key": "heart", "icon": "sys_wish"},
         actor=girl, expect_error=True)
    check("孩子改不了图标",
          db.query_one("SELECT icon FROM dimension WHERE code='heart'")["icon"] != "sys_wish")
    call("GET", "/api/icon/list", actor=girl, expect_error=True)
    check("孩子也看不了清单", True)

    # --- 越界 ---
    call("POST", "/api/icon", {"kind": "member", "key": 1, "icon": "rw_box"},
         actor=dad, expect_error=True)
    call("POST", "/api/icon", {"kind": "item", "key": "不存在的道具", "icon": "rw_box"},
         actor=dad, expect_error=True)
    check("越界的写不进去", True)

    # --- 正常改动 ---
    old = db.query_one("SELECT icon FROM dimension WHERE code='heart'")["icon"]
    call("POST", "/api/icon", {"kind": "dimension", "key": "heart", "icon": "dim_vigor"}, actor=dad)
    check("改维度图标", db.query_one("SELECT icon FROM dimension WHERE code='heart'")["icon"] == "dim_vigor")
    call("POST", "/api/icon", {"kind": "dimension", "key": "heart", "icon": old}, actor=dad)
    call("POST", "/api/icon", {"kind": "box", "key": 7, "icon": "rw_box"}, actor=dad)
    check("改宝箱图标（tier 是整数也能对上）",
          db.query_one("SELECT icon FROM box_tier WHERE tier=7")["icon"] == "rw_box")
    call("POST", "/api/icon", {"kind": "box", "key": 7, "icon": "rw_box_open"}, actor=dad)

    # --- 任务带图发布 ---
    t = call("POST", "/api/tasks", {"assignee_id": GIRL, "title": "浇一次花", "std": "土湿了就行",
                                    "reward_type": "stardust", "reward": {"amount": 2},
                                    "icon": "task_plant"}, actor=dad)
    check("发任务能把图带上",
          db.query_one("SELECT icon FROM task WHERE id=?", (t["task_id"],))["icon"] == "task_plant")
    # 清洗过的：塞 HTML 进去剩不下尖括号
    t2 = call("POST", "/api/tasks", {"assignee_id": GIRL, "title": "再浇一次", "std": "同上",
                                     "icon": "<img onerror=1>"}, actor=dad)
    ic = db.query_one("SELECT icon FROM task WHERE id=?", (t2["task_id"],))["icon"]
    check("任务图标里的尖括号被掐掉", "<" not in ic and ">" not in ic, ic)

    # --- 大厅任务领走之后图要跟着走 ---
    hall = call("POST", "/api/tasks", {"open_to_all": True, "slots": 1,
                                       "title": "大厅的活", "std": "谁都行",
                                       "icon": "rw_gift"}, actor=dad)
    got = call("POST", "/api/tasks/%d/claim" % hall["task_id"], actor=girl)
    check("从大厅领走时图标跟着复制",
          db.query_one("SELECT icon FROM task WHERE id=?", (got["task_id"],))["icon"] == "rw_gift",
          db.query_one("SELECT icon FROM task WHERE id=?", (got["task_id"],))["icon"])

    # --- 心愿：孩子许愿不带图，家长点亮时才挑 ---
    # 前面几组用例可能已经给这个孩子挂了心愿，先把名额腾出来。
    for r in db.query("SELECT id FROM wish WHERE member_id=? AND status IN ('wished','active')",
                      (GIRL,)):
        call("POST", "/api/wishes/%d/status" % r["id"], {"status": "cancelled"}, actor=girl)
    w = call("POST", "/api/wishes", {"title": "想要一只恐龙", "reward_desc": "大的"}, actor=girl)
    check("孩子许的愿没有图",
          (db.query_one("SELECT icon FROM wish WHERE id=?", (w["wish_id"],))["icon"] or "") == "",
          db.query_one("SELECT icon FROM wish WHERE id=?", (w["wish_id"],))["icon"])
    call("POST", "/api/wishes/%d/configure" % w["wish_id"],
         {"cond_type": "fixed", "cond": {"value": 10}, "icon": "🦖"}, actor=dad)
    check("家长点亮时给了图", db.query_one("SELECT icon FROM wish WHERE id=?", (w["wish_id"],))["icon"] == "🦖")
    # 「不传 icon 就不能把已经有的图冲掉」这条只能走 engine 层测：
    # 一旦 configure 过，心愿就不再是待定状态，接口层没法对它再来一次。
    call("POST", "/api/wishes/%d/status" % w["wish_id"], {"status": "cancelled"}, actor=girl)
    w2 = call("POST", "/api/wishes", {"title": "再要一个", "reward_desc": ""}, actor=girl)
    db.execute("UPDATE wish SET icon='sys_calendar' WHERE id=?", (w2["wish_id"],))
    E.configure_wish(w2["wish_id"], "fixed", {"value": 5}, operator_id=DAD)
    check("configure 不传 icon 时原来的图不动",
          db.query_one("SELECT icon FROM wish WHERE id=?", (w2["wish_id"],))["icon"] == "sys_calendar",
          db.query_one("SELECT icon FROM wish WHERE id=?", (w2["wish_id"],))["icon"])

    # --- 列表接口要把 icon 带出来 ---
    shop = call("GET", "/api/shop", query={"member_id": str(GIRL)}, actor=girl)
    check("商店返回图标", all(("icon" in x) for x in shop["tickets"] + shop["cards"]))
    cat = call("GET", "/api/catalog", query={"member_id": str(GIRL)}, actor=girl)
    check("图鉴返回图标", all(("icon" in x) for x in cat["items"]))
    boxes = call("GET", "/api/boxes", query={"member_id": str(GIRL)}, actor=girl)
    check("宝箱返回图标", all(("icon" in x) for x in boxes["tiers"]))
    hold = call("GET", "/api/holdings", query={"member_id": str(GIRL)}, actor=girl)
    check("持有的券卡返回图标",
          all(("icon" in x) for x in hold["tickets"] + hold["cards"]))
    feed = call("GET", "/api/feed", query={"member_id": str(GIRL)}, actor=girl)
    check("动态返回图标", all(("icon" in x) for x in feed.get("doing", [])))


def _card_cases(dad, girl, mom, boy):
    """卡片效果（v22）。

    规则书第 04 章原先写着「22 张卡里只有星尘双倍周真的在起作用」。
    这里每一类取一张验证：系统进行为要能看到数字真的变了，
    真人行为要能看到兑现单真的产生。
    """
    def grant(code, n=1):
        it = E.item_by_code(code)
        E.grant_item(GIRL, it["id"], n, source="grant")
        return it

    day = E.today()

    # --- 加时卡：35 分钟之外的额度，系统自己加 ---
    st0 = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    base_room = st0["max_qty_now"]
    grant("extra_time")
    r = call("POST", "/api/items/use", {"member_id": GIRL, "code": "extra_time"}, actor=girl)
    check("加时卡当场生效", r["status"] == "done", r.get("message"))
    st1 = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    check("加时卡把今天的额度加上去了", st1["bonus_minutes"] >= 30, st1["bonus_minutes"])

    # --- 抵扣卡：没有欠账时不能用，有欠账时抵掉 ---
    # 用 BOY 而不是 GIRL：GIRL 刚换了加时卡，今天账上是正的，
    # 抵掉的其实是她自己多出来的那份。欠账是一个人对着自己的账本还的。
    E.grant_item(BOY, E.item_by_code("offset_card")["id"], 1, source="grant")
    call("POST", "/api/items/use", {"member_id": BOY, "code": "offset_card"}, actor=boy,
         expect_error=True)          # 现在没欠，留着以后用
    E.add_calibration(BOY, 2, "抢了弟弟的玩具", effect_type="ticket_min", amount=15,
                      operator_id=DAD)
    check("欠账记账成功", E.minutes_debt(BOY) == 15, E.minutes_debt(BOY))
    E.grant_item(BOY, E.item_by_code("offset_card")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": BOY, "code": "offset_card"}, actor=boy)
    check("抵扣卡抵掉 15 分钟", r and r["status"] == "done" and E.minutes_debt(BOY) == 0,
          E.minutes_debt(BOY))

    # --- 加时给的时间过了今天就没了 ---
    # 以前这笔账是全表求和，于是今天多出来的分钟会一直挂着，
    # 后面每一次扣分都被它吃掉 —— 一张加时卡等于好几张免罚券。
    y = E.fmt(E.parse_day(day) - timedelta(days=1))
    db.execute("DELETE FROM ledger WHERE member_id=? AND kind='minute_fixture'", (BOY,))
    E.add_ledger(BOY, "minute_fixture", day=y, minutes=60, note="昨天送的加时")
    E.add_ledger(BOY, "minute_fixture", day=day, minutes=-30, note="今天扣的分")
    check("昨天没用完的时间不带到今天", E.minutes_debt(BOY) == 30, E.minutes_debt(BOY))
    E.add_ledger(BOY, "minute_fixture", day=day, minutes=60, note="今天的加时")
    check("今天的加时先拿去还账", E.minutes_debt(BOY) == 0 and E.minutes_credit(BOY) == 30,
          (E.minutes_debt(BOY), E.minutes_credit(BOY)))
    db.execute("DELETE FROM ledger WHERE member_id=? AND kind='minute_fixture'", (BOY,))

    # --- 免等卡：免的是「一轮结束后要休息」这件事 ---
    # v23 撤掉了「学习前置」那条闸门（系统判断不了学习做完没有，归家长审核），
    # 这张卡跟着改成免休息。v32 把休息挂在「一轮结束」上，它免的就是这一条。
    E.grant_item(GIRL, E.item_by_code("skip_study")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": GIRL, "code": "skip_study"}, actor=girl)
    check("免等卡当天生效", r["status"] == "active", r.get("message"))
    st2 = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    check("休息被免掉", st2.get("skip_cooldown") is True and st2["cooldown_left"] == 0,
          (st2.get("skip_cooldown"), st2.get("cooldown_left")))
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "skip_study"}, actor=girl,
         expect_error=True)          # 今天已经在生效了

    # --- 晚睡卡：硬停止时间往后挪 ---
    before = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)["curfew"]
    E.grant_item(GIRL, E.item_by_code("late_sleep")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": GIRL, "code": "late_sleep"}, actor=girl)
    after = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)["curfew"]
    check("晚睡卡把收工时间挪后了", before != after, (before, after))

    # --- 翻倍卡：下一次拿到星尘翻倍 ---
    E.grant_item(GIRL, E.item_by_code("double_card")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": GIRL, "code": "double_card"}, actor=girl)
    check("翻倍卡是装填状态", r["status"] == "armed", r.get("message"))
    sd0 = E.stardust_balance(GIRL)
    call("POST", "/api/explore", {"member_id": GIRL, "kind": "stardust", "stardust": 2,
                                  "phrase": "主动把碗收了"}, actor=dad)
    check("星尘翻倍入账", E.stardust_balance(GIRL) - sd0 == 4, E.stardust_balance(GIRL) - sd0)
    sd1 = E.stardust_balance(GIRL)
    call("POST", "/api/explore", {"member_id": GIRL, "kind": "stardust", "stardust": 2,
                                  "phrase": "主动倒了垃圾"}, actor=dad)
    check("翻倍只生效一次", E.stardust_balance(GIRL) - sd1 == 2, E.stardust_balance(GIRL) - sd1)

    # --- 零花钱加倍卡：多拿不超过 20 星尘等值 ---
    # v24 起兑换绕不过那三步：孩子提、家长批、孩子确认。加倍卡是在家长点同意、
    # 真正发放那一刻消费掉的，所以这里得把流程走完才能看到结果。
    E.grant_item(GIRL, E.item_by_code("allowance_x2")["id"], 1, source="grant")
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "allowance_x2"}, actor=girl)
    # 前面的分组把本月额度换得差不多了，这里的重点是「有没有多出一份」，
    # 先把额度抬高，别让额度上限抢了这条用例的嘴。
    set_setting("cash.monthly_cap_stardust", 600)
    E.add_ledger(GIRL, "adjust", stardust=100, note="测试夹具")
    q = call("POST", "/api/cash/request", {"member_id": GIRL, "stardust": 6}, actor=girl)
    check("孩子提的兑换落到待审", q["status"] == "pending", q)
    c = call("POST", "/api/cash/requests/%d/resolve" % q["request_id"],
             {"approve": True}, actor=dad)
    check("零花钱翻倍多了一份", c.get("bonus") == 3 and c["cash"] == 6, c)
    call("POST", "/api/cash/requests/%d/received" % q["request_id"], {}, actor=girl)
    db.execute("DELETE FROM ledger WHERE member_id=? AND kind='cash_bonus'", (GIRL,))

    # --- 陪伴卡：机器办不到，进兑现单等家长 ---
    E.grant_item(GIRL, E.item_by_code("company_card")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": GIRL, "code": "company_card",
                                        "note": "想让妈妈陪我搭积木"}, actor=girl)
    check("陪伴卡进兑现单", r["status"] == "pending", r.get("message"))
    lst = call("GET", "/api/cards/redeems", actor=dad)
    check("家长能看到待兑现", len(lst["items"]) == 1 and lst["items"][0]["effect_key"]
          == "time_together", lst["items"])
    rid = lst["items"][0]["id"]
    call("POST", "/api/cards/redeems/%d/done" % rid, {"done": True}, actor=girl,
         expect_error=True)          # 孩子不能自己给自己发奖
    call("POST", "/api/cards/redeems/%d/done" % rid, {"done": True}, actor=dad)
    lst = call("GET", "/api/cards/redeems", actor=dad)
    check("兑现完就清掉了", len(lst["items"]) == 0, lst["items"])
    call("POST", "/api/cards/redeems/%d/done" % rid, {"done": True}, actor=dad,
         expect_error=True)          # 同一条不能点两次

    # --- 后果自选卡：下一次校准的修复方式由他自己写 ---
    E.grant_item(BOY, E.item_by_code("pick_consequence")["id"], 1, source="grant")
    call("POST", "/api/items/use", {"member_id": BOY, "code": "pick_consequence"}, actor=boy)
    r = call("POST", "/api/calibration",
             {"member_id": BOY, "level": 2, "reason": "把水洒了不收拾",
              "effect_type": "task"}, actor=dad)
    tid = r.get("task_id")
    if tid:
        t = db.query_one("SELECT std FROM task WHERE id=?", (tid,))["std"]
        check("修复任务由他自己写", "自己写下来" in t, t)
    db.execute("UPDATE card_redeem SET status='done' WHERE member_id=? AND effect_key='choose_consequence'",
               (BOY,))

    # --- 重抽券：装填后，下一箱随机件抽两次取更好的那个 ---
    # GIRL 刚才在「卡片护栏」分组里已经用掉一张，同类卡一个周期只能用一张，
    # 这里换 BOY。
    E.grant_item(BOY, E.item_by_code("reroll_card")["id"], 1, source="grant")
    r = call("POST", "/api/items/use", {"member_id": BOY, "code": "reroll_card"}, actor=boy)
    check("重抽券是装填状态", r and r["status"] == "armed", r and r.get("message"))
    check("比较随机件大小这套逻辑跑得通",
          E._random_value({"kind": "bonus", "code": "minutes", "qty": 60}) >
          E._random_value({"kind": "bonus", "code": "minutes", "qty": 30}))

    # --- 重抽券的另一条路：开完箱看着结果再决定要不要再抽一次 ---
    # 装填是开箱前押上卡、系统自动抽两次；这条是开箱之后孩子自己点。
    # 同一个箱子只允许重抽一次 —— 装填已经自动重抽过的也算。
    # BOY 手上压着一张装填中的，会自动生效，这里换 GIRL。
    cyc_g = E.current_cycle(GIRL)["id"]
    E.grant_item(GIRL, E.item_by_code("reroll_card")["id"], 1, source="grant")
    # GIRL 手上压着一张之前用掉的装填券，它会在开箱时自动生效一次，
    # 那种箱子 random.rerolled 已经是 true，不能再手动重抽，循环里要跳过。
    def _open_with_random():
        for _ in range(60):                  # 王者箱 40% 出随机件，60 次抽不到的概率可以忽略
            made = E.issue_box(GIRL, 6, cycle_id=cyc_g, source="free", operator_id=DAD)
            if not made or not made.get("ok"):
                return None
            r = E.open_box(GIRL, made["box_id"], operator_id=DAD)
            if r and r.get("random") and not r["random"].get("rerolled"):
                return r
        return None

    opened = _open_with_random()
    check("打出来的箱子能开出随机件", bool(opened), opened and opened.get("random"))
    if opened:
        bid = opened["box_id"]
        rr_card = E.item_by_code("reroll_card")["id"]
        bal0 = E.item_balance(GIRL, rr_card)
        call("POST", "/api/boxes/%d/reroll" % bid, actor=boy, expect_error=True)   # 不是他的箱子
        rr = call("POST", "/api/boxes/%d/reroll" % bid, actor=girl)
        check("重抽跑通了", rr and rr.get("ok"), rr)
        check("重抽券花掉一张", E.item_balance(GIRL, rr_card) == bal0 - 1,
              (bal0, E.item_balance(GIRL, rr_card)))
        call("POST", "/api/boxes/%d/reroll" % bid, actor=girl, expect_error=True)  # 一箱只一次
        r2 = E.reroll_box_random(GIRL, bid, operator_id=DAD)
        check("同一箱第二次重抽被拒", not r2["ok"], r2.get("msg"))
        # 券花光之后再点，报的是「没有券」而不是别的
        E.consume_item(GIRL, rr_card, E.item_balance(GIRL, rr_card), kind="test")
        box2 = _open_with_random()
        if box2:
            # v24 起王者箱保底给一张稀有卡，而重抽券本身就是稀有卡 ——
            # 这一箱有可能又发回来一张。再清一遍，这条测的是
            # 「手上确实没有券的时候点重抽会说什么」。
            left = E.item_balance(GIRL, rr_card)
            if left:
                E.consume_item(GIRL, rr_card, left, kind="test")
            r3 = E.reroll_box_random(GIRL, box2["box_id"], operator_id=DAD)
            check("没券了就重抽不了", not r3["ok"], r3.get("msg"))

    # --- 当天生效的卡和装填中的卡，孩子那边要看得见 ---
    st3 = call("GET", "/api/tickets/state", query={"member_id": str(GIRL)}, actor=girl)
    check("当天生效的卡会回给孩子", any(f["key"] in ("skip_cooldown", "late_bed")
                                  for f in st3["flags"]), st3["flags"])
    st4 = call("GET", "/api/tickets/state", query={"member_id": str(BOY)}, actor=boy)
    check("装填中的卡会回给孩子", any(a["key"] == "reroll_random" for a in st4["armed"]),
          st4["armed"])
    ov = call("GET", "/api/kids/overview", actor=dad)
    g = [x for x in ov["items"] if x["member_id"] == GIRL][0]
    check("家长那边也看得见今天生效的卡", len(g["card_flags"]) >= 2, g["card_flags"])
    set_setting("cash.monthly_cap_stardust", 60)


def _event_cases(dad, girl, mom):
    """两个独立事件通道 + 卡片护栏 + 豁免券边界（第 04 / 05 / 09 / 10 章）。"""
    boy = A.member_public(db.query_one("SELECT * FROM member WHERE id=?", (BOY,)))

    print("\n--- 事件通道：偷玩降级 / 作业复核 ---")
    ev = call("GET", "/api/events", query={"member_id": str(BOY)}, actor=boy)
    check("一开始没有降级", ev["state"]["active"] is False)
    call("POST", "/api/events/steal-game", {"member_id": BOY, "reason": "券不够用"}, actor=boy,
         expect_error=True)          # 孩子不能自己记
    r = call("POST", "/api/events/steal-game", {"member_id": BOY, "reason": "券不够用"}, actor=dad)
    check("第一次降级 3 天", r["days"] == 3, r["days"])
    check("记了重复标记", r["repeat"] is False)
    ev = call("GET", "/api/events", query={"member_id": str(BOY)}, actor=dad)
    check("降级生效中", ev["state"]["active"] is True)
    check("剩 3 天", ev["state"]["days_left"] == 3, ev["state"]["days_left"])
    r = call("POST", "/api/events/steal-game", {"member_id": BOY, "reason": "同学在约"}, actor=dad)
    check("30 天内第二次延到 7 天", r["days"] == 7 and r["repeat"] is True, r["days"])
    ov = call("GET", "/api/kids/overview", actor=dad)
    b = [x for x in ov["items"] if x["member_id"] == BOY][0]
    check("速览卡带上降级状态", b["device"]["active"] is True)
    db.execute("UPDATE device_downgrade SET end_date=? WHERE member_id=? AND status='active'",
               (E.fmt(E.parse_day(E.today()) - timedelta(days=1)), BOY))
    ev = call("GET", "/api/events", query={"member_id": str(BOY)}, actor=dad)
    check("到期自动恢复", ev["state"]["active"] is False)
    check("记录还在", len(ev["device"]) == 2, len(ev["device"]))

    # 作业复核要真的把那 1 分撤下来，而且只撤那 1 分。
    # 前面的分组可能已经把这个周期结算掉了；结算过就撤不动（那是对的），
    # 所以这里把它临时退回 open —— 这是最后一组用例，不会影响别处。
    day = E.today()
    set_study(BOY, day, 1)
    _cyc = E.get_or_create_cycle(BOY, day)
    db.execute("UPDATE cycle SET status='open' WHERE id=?", (_cyc["id"],))
    r = call("POST", "/api/events/homework",
             {"member_id": BOY, "day": day, "subject": "数学", "note": "第三题第二步"}, actor=dad)
    check("撤掉 1 分智识", r["revoked"] == 1, r["revoked"])
    # 夹具写的那行没挂 cycle_id（故意，免得受周期状态影响），所以这里看当天分，
    # 不去比周期的固定分。
    _dim = db.query_one("SELECT id FROM dimension WHERE code='study'")["id"]
    _left = E.day_scores(BOY, day)
    check("当天智识分已经撤掉",
          _dim not in _left or float(_left[_dim]["value"]) == 0,
          _left.get(_dim) and _left[_dim]["value"])
    ev = call("GET", "/api/events", query={"member_id": str(BOY)}, actor=dad)
    check("作业复核留痕", len(ev["hw"]) == 1 and ev["hw"][0]["subject"] == "数学")
    call("POST", "/api/events/homework", {"member_id": BOY, "day": day}, actor=dad,
         expect_error=True)          # 已经是 0 分，没有可撤的
    db.execute("UPDATE cycle SET status='settled' WHERE id=?", (_cyc["id"],))
    call("POST", "/api/events/homework", {"member_id": BOY, "day": "2026/9/1"}, actor=dad,
         expect_error=True)          # 日期格式不对
    r = call("GET", "/api/events", query={"member_id": str(BOY)}, actor=girl)
    check("孩子传别人的 id 只会拿到自己的", r["state"]["active"] is False)

    # --- 同类卡每周期限用一张（第 04 章护栏三）---
    print("\n--- 卡片护栏 ---")
    ic = E.item_by_code("reroll_card")
    E.grant_item(GIRL, ic["id"], 3, source="grant")
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "reroll_card"}, actor=girl)
    call("POST", "/api/items/use", {"member_id": GIRL, "code": "reroll_card"}, actor=girl,
         expect_error=True)
    check("同类卡本周还剩 2 张没动",
          E.item_balance(GIRL, ic["id"]) == 2, E.item_balance(GIRL, ic["id"]))

    # --- 豁免券边界（第 05 章）---
    print("\n--- 豁免券边界 ---")
    call("POST", "/api/tickets/request", {"member_id": GIRL, "code": "ticket_exempt", "note": ""},
         actor=girl, expect_error=True)
    call("POST", "/api/tickets/request",
         {"member_id": GIRL, "code": "ticket_exempt", "note": "免一次匠力"}, actor=girl,
         expect_error=True)
    call("POST", "/api/tickets/request",
         {"member_id": GIRL, "code": "ticket_exempt", "note": "免一次洗澡"}, actor=girl,
         expect_error=True)

    # --- 只给管理员的整库导出 ---
    print("\n--- 运维权限 ---")
    call("GET", "/api/ops/export", actor=mom, expect_error=True)


def _v25_cases(dad, girl, mom, boy):
    """v25：心愿的两种新条件、商店箱子的随机件口径、头像。"""
    # 清场：wish.max_active 默认 2，前面几节可能已经占着名额了
    for w in db.query("SELECT id FROM wish WHERE member_id=? AND status IN ('wished','active')",
                      (GIRL,)):
        E.update_wish_status(w["id"], "cancelled", operator_id=dad["id"])

    # --- 自己写一条 ---
    r = call("POST", "/api/wishes", {"member_id": GIRL, "title": "读完一本厚书",
                                     "cond_type": "custom",
                                     "cond": {"text": "读完整本，讲给我听一遍"}}, actor=dad)
    wid = (r or {}).get("wish_id")
    check("家长能建一条自定义条件的心愿", bool(wid), r)
    r = call("GET", "/api/wishes", query={"member_id": GIRL}, actor=dad)
    w = [x for x in r["items"] if x["id"] == wid][0]
    check("接口标出了「这条靠人判」", w["progress"]["manual"] is True)
    check("自定义那条不给百分比", w["progress"]["percent"] is None, w["progress"])
    check("自定义那条的话能读出来",
          "读完整本" in (w["progress"].get("text") or ""), w["progress"].get("text"))
    check("自定义那条一直能点「我做到了」", w["progress"]["ready"] is True)
    call("POST", "/api/wishes/%d/status" % wid, {"status": "cancelled"}, actor=dad)

    # --- 多选条件（v26：六条都能勾 + 家长定做到几条算成）---
    r = call("POST", "/api/wishes", {"member_id": GIRL, "title": "这周多选达成一个",
                                     "cond_type": "any",
                                     "cond": {"need": 2,
                                              "items": [{"type": "fixed", "value": 10},
                                                        {"type": "task_count", "value": 2},
                                                        {"type": "stardust", "value": 8},
                                                        {"type": "custom",
                                                         "text": "把书桌自己收拾干净"}]}},
             actor=dad)
    wid2 = (r or {}).get("wish_id")
    check("家长能建一条多选条件的心愿", bool(wid2), r)
    r = call("GET", "/api/wishes", query={"member_id": GIRL}, actor=dad)
    w = [x for x in r["items"] if x["id"] == wid2][0]
    check("每条的子进度都带出来了", len(w["progress"]["subs"]) == 4, w["progress"])
    check("接口带回「做到几条算成」", w["progress"]["need"] == 2, w["progress"].get("need"))
    check("进度按完成条数算，不是按最接近的那条",
          w["progress"]["cur"] == w["progress"]["done_count"], w["progress"])
    check("含自定义那条时标出「有人工判的一条」",
          w["progress"]["has_manual"] is True, w["progress"].get("has_manual"))
    call("POST", "/api/wishes/%d/status" % wid2, {"status": "cancelled"}, actor=dad)

    # 多选里的星尘那条：孩子自己付，付掉才算那一条做到
    E.add_ledger(GIRL, "adjust", day=E.today(), stardust=40, note="测试预置（多选里的星尘）")
    r = call("POST", "/api/wishes", {"member_id": GIRL, "title": "多选里带星尘那条",
                                     "cond_type": "any",
                                     "cond": {"need": 2,
                                              "items": [{"type": "stardust", "value": 20},
                                                        {"type": "perfect_day", "value": 999}]}},
             actor=dad)
    wid3 = (r or {}).get("wish_id")
    r = call("GET", "/api/wishes", query={"member_id": GIRL}, actor=girl)
    w = [x for x in r["items"] if x["id"] == wid3][0]
    check("余额够了只给「能付」，不算做到",
          w["progress"]["can_pay"] and w["progress"]["done_count"] == 0, w["progress"])
    r = call("POST", "/api/wishes/%d/pay" % wid3, {}, actor=girl)
    check("孩子自己点能把多选里的星尘付掉", r and r.get("paid") == 20, r)
    r = call("GET", "/api/wishes", query={"member_id": GIRL}, actor=girl)
    w = [x for x in r["items"] if x["id"] == wid3][0]
    check("付掉之后那一条才记成做到", w["progress"]["done_count"] == 1, w["progress"])
    check("付了钱也没把整条心愿直接判成达成",
          w["progress"]["done"] is False and w["progress"]["need"] == 2, w["progress"])
    call("POST", "/api/wishes/%d/status" % wid3, {"status": "cancelled"}, actor=dad)

    call("POST", "/api/wishes", {"member_id": GIRL, "title": "空话", "cond_type": "custom",
                                 "cond": {"text": ""}}, actor=dad, expect_error=True)
    call("POST", "/api/wishes", {"member_id": GIRL, "title": "只有一条", "cond_type": "any",
                                 "cond": {"items": [{"type": "fixed", "value": 10}]}},
         actor=dad, expect_error=True)
    call("POST", "/api/wishes", {"member_id": GIRL, "title": "要的比勾的多", "cond_type": "any",
                                 "cond": {"need": 3,
                                          "items": [{"type": "fixed", "value": 10},
                                                    {"type": "task_count", "value": 2}]}},
         actor=dad, expect_error=True)
    call("POST", "/api/wishes", {"member_id": GIRL, "title": "重复挑", "cond_type": "any",
                                 "cond": {"need": 1,
                                          "items": [{"type": "fixed", "value": 10},
                                                    {"type": "fixed", "value": 20}]}},
         actor=dad, expect_error=True)

    # --- 商店箱子：买来的没有随机件 ---
    shop = call("GET", "/api/shop", query={"member_id": GIRL}, actor=girl)
    check("商店里三档箱都在", len(shop["boxes"]) == 3, [b["tier"] for b in shop["boxes"]])
    check("商店的箱子不给随机件概率",
          all(b["random_rate"] == 0 and not b["random_pool"] for b in shop["boxes"]),
          [(b["tier"], b["random_rate"]) for b in shop["boxes"]])
    check("商店的箱子也不给钻石级概率", all(b["diamond_rate"] == 0 for b in shop["boxes"]))
    check("商店的箱子标着「买来的」", all(b["purchased"] for b in shop["boxes"]))
    boxes = call("GET", "/api/boxes", query={"member_id": GIRL}, actor=girl)
    rate = {t["tier"]: t["random_rate"] for t in boxes["tiers"]}
    check("宝箱栏照旧显示真实概率",
          rate[4] == 0.10 and rate[5] == 0.20 and rate[6] == 0.40, rate)
    check("宝箱栏那几档没被标成买来的", all(not t["purchased"] for t in boxes["tiers"]))

    print("\n--- 七项分数与动态日志（v28）---")
    # 孩子端「分数」页：七项各是什么、这几天拿到几天、哪一项被扣了
    dm = call("GET", "/api/dims", query={"member_id": str(GIRL), "days": "7"}, actor=girl)
    check("孩子查得到自己那七项", dm and len(dm["dims"]) == 7,
          [x["name"] for x in (dm or {}).get("dims", [])])
    check("七项都带着「它是干什么的」", all(x.get("meaning") for x in dm["dims"]))
    check("七项都带着图", all(x.get("icon") for x in dm["dims"]),
          [x.get("icon") for x in dm["dims"]])
    check("最弱那一项给得出名字", dm.get("weakest") and dm["weakest"]["name"], dm.get("weakest"))
    check("扣了多少算得出来", isinstance((dm.get("deduct") or {}).get("times"), int),
          dm.get("deduct"))
    check("固定分之外的加减也列出来了", isinstance(dm.get("extra"), list))
    # 孩子顺手带上别人的 id 不算越权：取回来的还是自己那份，不给别人家的
    other = call("GET", "/api/dims", query={"member_id": str(BOY)}, actor=girl)
    check("孩子传别人的 id 也只给回自己的", other and other["member_id"] == GIRL,
          other and other["member_id"])
    dm2 = call("GET", "/api/dims", query={"member_id": str(BOY)}, actor=dad)
    check("家长能看任何一个孩子的七项", dm2 and len(dm2["dims"]) == 7)
    call("GET", "/api/dims", query={"member_id": str(DAD)}, actor=dad, expect_error=True)

    # 动态日志：孩子自己按的每一个按钮，家长都能翻出来
    act = call("GET", "/api/activity", query={"limit": "40"}, actor=dad)
    check("家长拿得到全家日志", act and act["total"] > 0, act and act["total"])
    check("每条都是人话 + 影响",
          all(x.get("text") and "group_text" in x for x in act["items"]),
          act["items"][:2])
    check("四类分组给前端做筛选用", len(act.get("groups") or []) == 4, act.get("groups"))
    self_only = call("GET", "/api/activity", query={"group": "self", "limit": "40"}, actor=dad)
    check("筛「孩子自己做的」不会混进打分",
          not any(x["kind"] == "daily_score" for x in self_only["items"]),
          [x["text"] for x in self_only["items"][:3]])
    mine_act = call("GET", "/api/activity", query={"limit": "40"}, actor=girl)
    check("孩子只看到自己的", all(x["who"] == "女儿" for x in mine_act["items"]),
          sorted(set(x["who"] for x in mine_act["items"])))
    one = call("GET", "/api/activity", query={"member_id": str(BOY), "limit": "10"}, actor=dad)
    check("家长能按孩子筛", all(x["who"] == "儿子" for x in one["items"]),
          sorted(set(x["who"] for x in one["items"])))
    mine_act2 = call("GET", "/api/activity", query={"member_id": str(BOY), "limit": "5"},
                     actor=girl)
    check("孩子传别人的 id 也只给回自己的",
          all(x["who"] == "女儿" for x in mine_act2["items"]),
          sorted(set(x["who"] for x in mine_act2["items"])))
    call("GET", "/api/activity", query={"days": "abc"}, actor=dad, expect_error=True)
    paged = call("GET", "/api/activity", query={"limit": "3", "offset": "3"}, actor=dad)
    check("翻页接着上一段", paged["items"] and paged["items"][0] != act["items"][0],
          [x["id"] for x in paged["items"]][:3])

    print("\n--- 经手人与按条提交（v29）---")

    # 日志：谁经手的
    E.add_ledger(GIRL, "adjust", stardust=1, note="巡检：妈妈加的", operator_id=MOM)
    E.add_ledger(GIRL, "adjust", stardust=2, note="巡检：自己买的", operator_id=GIRL)
    act = call("GET", "/api/activity", query={"limit": "20"}, actor=dad)
    check("日志每条都带着经手人", all(x.get("by") for x in act["items"]),
          [x.get("by") for x in act["items"][:6]])
    check("妈妈经手写的是妈妈",
          any(x["by"] == E.member_name_of(MOM) for x in act["items"]),
          sorted(set(x["by"] for x in act["items"])))
    check("孩子自己按的写的是他自己",
          any(x["by"] == E.member_name_of(GIRL) for x in act["items"]))
    check("by_parent 只标大人",
          not any(x["by_parent"] for x in act["items"]
                  if x["by"] == E.member_name_of(GIRL)))

    # 心愿：按哪一条提交
    w = call("POST", "/api/wishes",
             {"member_id": str(GIRL), "title": "巡检心愿", "cond_type": "any",
              "cond": {"need": 2,
                       "items": [{"type": "custom", "text": "把书都收回书架"},
                                 {"type": "task_count", "value": 9}]}},
             actor=dad)
    wid = w["wish_id"]
    call("POST", "/api/wishes/%d/submit" % wid, {"cond_key": "task_count"},
         actor=girl, expect_error=True)     # 系统算得出来的不用提交
    call("POST", "/api/wishes/%d/submit" % wid, {"cond_key": "streak"},
         actor=girl, expect_error=True)     # 没挂这一条
    call("POST", "/api/wishes/%d/submit" % wid, {"cond_key": "custom"},
         actor=dad, expect_error=True)      # 家长不能替孩子说做到了
    sub = call("POST", "/api/wishes/%d/submit" % wid,
               {"cond_key": "custom", "note": "书都收回去了"}, actor=girl)
    cid = sub["claim_id"]
    call("POST", "/api/wishes/%d/submit" % wid, {"cond_key": "custom"},
         actor=girl, expect_error=True)     # 还在等确认，不能重复交
    got = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    prog = [x for x in got["items"] if x["id"] == wid][0]["progress"]
    check("交上去之后整条心愿不再给「我做到了」", prog["ready"] is False, prog.get("ready"))
    check("那一行标着等确认",
          [x for x in prog["subs"] if x["key"] == "custom"][0]["claim_status"] == "pending")

    call("POST", "/api/wishes/claims/%d" % cid, {"approve": True},
         actor=girl, expect_error=True)     # 孩子不能审自己交的
    call("POST", "/api/wishes/claims/%d" % cid, {"approve": False},
         actor=dad, expect_error=True)      # 不通过必须写理由
    call("POST", "/api/wishes/claims/%d" % cid,
         {"approve": False, "reject_note": "书架第三层还是乱的"}, actor=dad)
    sub2 = call("POST", "/api/wishes/%d/submit" % wid,
                {"cond_key": "custom", "note": "这次第三层也理了"}, actor=girl)
    lst = call("GET", "/api/wishes/submissions", actor=dad)
    check("家长的待办里有这一条", any(x["id"] == sub2["claim_id"] for x in lst["items"]),
          [x["cond_text"] for x in lst["items"]])
    check("待办写着是哪个人、哪一句话",
          all(x["who"] and x["cond_text"] for x in lst["items"]))
    call("GET", "/api/wishes/submissions", actor=girl, expect_error=True)  # 孩子看不了
    ok = call("POST", "/api/wishes/claims/%d" % sub2["claim_id"],
              {"approve": True}, actor=dad)
    got2 = call("GET", "/api/wishes", query={"member_id": str(GIRL)}, actor=dad)
    prog2 = [x for x in got2["items"] if x["id"] == wid][0]["progress"]
    done_row = [x for x in prog2["subs"] if x["key"] == "custom"][0]
    check("确认之后那一条算做到了", done_row["done"] is True, done_row)
    check("写的是谁确认的", done_row["by"] == E.member_name_of(DAD), done_row)
    check("处理过的不许再处理一次",
          "ok" not in ok or ok.get("status") == "approved")
    call("POST", "/api/wishes/claims/%d" % sub2["claim_id"], {"approve": True},
         actor=dad, expect_error=True)

    # --- 头像 ---
    r = call("POST", "/api/me/avatar", {"avatar": "G01"}, actor=girl)
    check("孩子能换自己的头像", r and r.get("avatar") == "G01", r)
    r = call("GET", "/api/members", actor=girl)
    me_row = [m for m in r["members"] if m["id"] == GIRL][0]
    check("换完立刻生效", me_row["avatar"] == "G01", me_row.get("avatar"))
    r = call("POST", "/api/me/avatar", {"avatar": "../../etc/passwd"}, actor=girl)
    check("乱传的值被洗掉，不是原样入库", r and r.get("avatar") == "", r)
    check("库里也没留下乱值",
          db.query_one("SELECT avatar FROM member WHERE id=?", (GIRL,))["avatar"] == "")
    # 服务端把值统一抬成大写：NAS 上是 Linux，文件名区分大小写，
    # 库里存小写的 b02 就取不到 B02.svg —— 电脑上没事，装到 NAS 上是一片空白
    call("POST", "/api/me/avatar", {"avatar": "B02"}, actor=boy)
    call("PATCH", "/api/members/%d" % BOY, {"avatar": "D01"}, actor=girl, expect_error=True)
    call("PATCH", "/api/members/%d" % BOY, {"avatar": "B01"}, actor=dad)
    check("家长能给孩子换头像",
          db.query_one("SELECT avatar FROM member WHERE id=?", (BOY,))["avatar"] == "B01")
    call("PATCH", "/api/members/%d" % MOM, {"avatar": "M01"}, actor=girl, expect_error=True)


if __name__ == "__main__":
    sys.exit(main())
