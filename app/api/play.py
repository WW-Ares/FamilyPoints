# -*- coding: utf-8 -*-
"""打分、星探、周期、宝箱、商店、道具、星尘。"""
import json
from datetime import timedelta

import db
import engine as E
from . import ApiError, route


def _can_score(ctx):
    """打分的只有家长。孩子自己也不行。

    光挡住「给别人打分」是不够的：孩子能给自己打分的话，
    「当天学习任务已完成」这个娱乐券前置条件随时能自己刷满。
    """
    me = ctx.as_member()
    if me["role"] != "parent":
        raise ApiError("打分是爸爸妈妈做的事", 403)
    return me


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------
def _day_view(member_id, day, ctx):
    mode = E.day_mode(day)
    dims = E.dimensions(mode)
    existing = E.day_scores(member_id, day)
    rows = []
    for d in dims:
        r = existing.get(d["id"])
        rows.append({"code": d["code"], "name": d["name"], "base_name": d["base_name"],
                     "meaning": d["meaning"], "icon": d["icon"], "renamed": d["renamed"],
                     "value": r["value"] if r else None})
    sc = sum(r["value"] for r in rows if r["value"] is not None)
    full = sum(d["score"] for d in dims)
    # 状态只认引擎那一处（engine.score_day_state）。界面不许自己拿
    # scored / can_edit 再拼一遍，拼出来的标签迟早跟后端能对上的那条不一致。
    st = E.score_day_state(member_id, day)
    # 这天有没有挨过忘打卡的罚款、那笔钱投进池子没有（pooled）。界面要照实说：
    # 没设许愿池目标的时候罚款是「先记着」，不能写成已经投了。
    pen = db.query_one("SELECT * FROM wish_pool_log WHERE kind='penalty' AND day=?"
                       " ORDER BY id DESC LIMIT 1", (day,))
    penalty = None
    if pen:
        penalty = {"stardust": float(pen["stardust"] or 0), "pooled": bool(pen["counted"])}
    return {"day": day, "mode": mode, "dims": rows, "score": sc, "full": full,
            "scored": bool(existing), "can_edit": st["can_edit"], "reason": st["reason"],
            "state": st["state"], "auto_filled": st["auto_filled"],
            "deadline": st.get("deadline", ""), "penalty": penalty,
            "revisions": E.day_revision_flag(member_id, day)}


@route("GET", "/api/score/day")
def get_day(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    day = ctx.p("day", E.today())
    return _day_view(mid if isinstance(mid, int) else mid["id"], day, ctx)


@route("POST", "/api/score")
def post_day(ctx):
    # 打分的只有家长。孩子能给自己打分的话，「当天学习任务已完成」
    # 这个娱乐券前置条件随时可以自己刷满，等于没写。
    m = _can_score(ctx)
    mid = ctx.target_child()
    day = ctx.p("day", E.today())
    undone = ctx.p("undone", [])
    if isinstance(undone, str):
        undone = [x for x in undone.split(",") if x]
    note = ctx.p("note", "")
    r = E.submit_day(mid, day, undone, operator_id=m["id"], note=note)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "打分没成功"))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, after_json, ts)"
               " VALUES (?,'score.submit','member',?,?,?)",
               (m["id"], mid, json.dumps({"day": day, "undone": undone}, ensure_ascii=False), db.now()))
    # settled：补的是周期最后一天的话，submit_day 顺手把这一周结了。
    # 带出去是为了让界面能说一句「这一周也一起结算了」，别让家长以为还要等。
    return {"ok": True, "view": _day_view(mid, day, ctx), "cycle": r["cycle"],
            "settled": r.get("settled")}


@route("GET", "/api/score/cycle")
def get_cycle_days(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    day = ctx.p("day", E.today())
    cyc = E.current_cycle(mid, day)
    out = []
    d = E.parse_day(cyc["start_date"])
    end = E.parse_day(cyc["end_date"])
    while d <= end:
        s = E.fmt(d)
        v = _day_view(mid, s, ctx)
        out.append({"day": s, "score": v["score"] if v["scored"] else None,
                    "scored": v["scored"], "transition": E.is_transition(s),
                    "mode": v["mode"],
                    "dims": [{"code": r["code"], "value": r["value"]} for r in v["dims"]]})
        d += timedelta(days=1)
    # 七分矩阵的行取「今天」这套维度：这一周的七分是按当下这七项回看整周。
    # 周期中途换成假期维度的话，对不上的那几天就是没拿到 —— 界面不必自己再拼一份。
    now = _day_view(mid, day, ctx)
    dims = [{"code": r["code"], "name": r["name"], "icon": r["icon"]} for r in now["dims"]]
    return {"cycle": E.cycle_snapshot(cyc["id"]), "days": out, "dims": dims}


# ---------------------------------------------------------------------------
# 星探时刻
# ---------------------------------------------------------------------------
@route("POST", "/api/explore")
def post_explore(ctx):
    me = ctx.as_parent()
    phrase = ctx.need("phrase")
    mid = ctx.target_child()          # 星探只能记在孩子头上，家长不在循环里
    r = E.add_explore(mid, ctx.p("day", E.today()), phrase,
                      kind=ctx.p("kind"), energy=ctx.f("energy"),
                      stardust=ctx.f("stardust"), dimension_code=ctx.p("dimension_code"),
                      operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "发不出去"))
    return r


@route("GET", "/api/explore")
def list_explore(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    return {"items": db.to_dicts(db.query(
        "SELECT * FROM explore WHERE member_id=? ORDER BY id DESC LIMIT 100", (mid,)))}


# ---------------------------------------------------------------------------
# 周期
# ---------------------------------------------------------------------------
@route("GET", "/api/cycle")
def get_cycle(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    E.ensure_settled(mid)
    day = ctx.p("day", E.today())
    cyc = E.current_cycle(mid, day)
    hist = db.query("SELECT * FROM cycle WHERE member_id=? ORDER BY start_date DESC LIMIT 12", (mid,))
    return {"current": E.cycle_snapshot(cyc["id"]),
            "level": E.level_of(mid),
            "history": [{"id": h["id"], "start": h["start_date"], "end": h["end_date"],
                         "energy": h["energy"], "status": h["status"],
                         "tier": h["tier_awarded"], "stardust": h["stardust_grant"]}
                        for h in hist]}


@route("GET", "/api/levels")
def get_levels(ctx):
    """星球等级：整张表 + 这个人现在到哪一档。孩子端「我的」用它画等级图。"""
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    tiers = [{"level": t["level"], "title": t["title"], "threshold": t["threshold"],
              "rewards": t.get("rewards", [])} for t in E.level_table()]
    return {"tiers": tiers, "level": E.level_of(mid)}


@route("POST", "/api/cycle/settle")
def post_settle(ctx):
    me = ctx.as_parent()
    mid = ctx.i("member_id")
    if not mid:
        raise ApiError("要指定结算谁")
    E.ensure_settled(mid)
    cyc = db.query_one("SELECT * FROM cycle WHERE member_id=? AND status='open'"
                       " ORDER BY start_date LIMIT 1", (mid,))
    if not cyc:
        return {"ok": True, "message": "没有待结算的周期"}
    # force：家长是当着界面按下去的，系统不替他改主意，但 settle_cycle 会把
    # 「最后一天还空着」这句话放在 warn 里带回来。
    r = E.settle_cycle(cyc["id"], operator_id=me["id"], force=True)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "结算失败"))
    return r


@route("POST", "/api/cycle/settle-all")
def post_settle_all(ctx):
    me = ctx.as_parent()
    out = []
    # v13：只结算孩子。家长不进游戏循环，settle_cycle 会直接拒掉，
    # 这里先筛一遍，免得结果里混进一堆「爸爸：家长只负责打分」。
    for m in db.query("SELECT id, name FROM member WHERE active=1 AND role='child'"):
        E.ensure_settled(m["id"])
        cyc = db.query_one("SELECT * FROM cycle WHERE member_id=? AND status='open'"
                           " ORDER BY start_date LIMIT 1", (m["id"],))
        if cyc:
            out.append(dict(name=m["name"],
                            result=E.settle_cycle(cyc["id"], operator_id=me["id"], force=True)))
    return {"ok": True, "results": out}


# ---------------------------------------------------------------------------
# 宝箱
# ---------------------------------------------------------------------------
def _box_row(t, as_purchase=False):
    """一行箱子。

    as_purchase = 这是商店里挂着价签的那一份。买来的箱子**不出随机件**，
    也不出钻石级：engine.issue_box 里那两条都挂在 source=='free' 上。
    所以这一份的概率直接给 0，不能让价签旁边写着「10% 出随机件」——
    孩子冲着那句话买下来，开出来什么都没有，那是在骗人。
    宝箱栏那一份（打出来的）照旧显示真实概率，两者本来就不是同一个东西。
    """
    return {"tier": t["tier"], "code": t["code"], "name": t["name"], "threshold": t["threshold"],
            "tickets": t["tickets"], "stardust": t["stardust"],
            "random_rate": 0 if as_purchase else t["random_rate"],
            "random_pool": [] if as_purchase else json.loads(t["random_pool"] or "[]"),
            "cards": E.box_cards(t),
            "card_count": sum(c["count"] for c in E.box_cards(t)),
            "card_rarity": t["card_rarity"],
            "diamond_rate": 0 if as_purchase else t["diamond_rate"],
            "purchased": bool(as_purchase),
            "price": t["purchase_price"], "purchasable": bool(t["purchase_allowed"]),
            "icon": t["icon"]}


@route("GET", "/api/boxes")
def get_boxes(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    cyc = E.current_cycle(mid)
    limit = int(db.cfg("box.purchase_weekly_limit", 1))
    used = db.query_one("SELECT COUNT(*) c FROM box_open WHERE member_id=? AND cycle_id=?"
                        " AND source='purchase'", (mid, cyc["id"]))["c"]
    return {"tiers": [_box_row(t) for t in db.query("SELECT * FROM box_tier ORDER BY tier")],
            "cycle": E.cycle_snapshot(cyc["id"]),
            "level": E.level_of(mid),
            "purchase_used": used, "purchase_limit": limit,
            # v38：还没处理完的箱子（没点开的 / 开了但自选没挑完的）。
            # 宝箱页顶部那张「点我打开」的提醒卡就是它，正常最多 1 只。
            "pending": E.pending_boxes(mid),
            "stardust": E.stardust_balance(mid)}


@route("POST", "/api/boxes/buy")
def post_buy_box(ctx):
    me = ctx.as_member()
    tid = ctx.target_child()
    tier = ctx.i("tier")
    if tier is None:
        raise ApiError("要指定买哪一档")
    r = E.buy_box(tid, tier, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "买不了"))
    return r


@route("POST", "/api/boxes/:id/reroll")
def reroll_box(ctx):
    """开完箱看着结果再决定要不要重抽随机件。只能用自己手上的那张重抽券。

    不接 target_child：要不要为这一箱花一张卡是孩子自己的取舍，
    家长替他点了，这张卡就不是他花掉的。
    """
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("重抽是孩子自己的决定", 403)
    bid = int(ctx.path_params["id"])
    r = E.reroll_box_random(me["id"], bid, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "重抽不了"))
    return r


@route("POST", "/api/boxes/:id/open")
def post_open_box(ctx):
    """点开一只待开的箱子。抽什么、发什么全在 engine.open_box 里。

    不接 target_child：这一箱是他自己的，家长替他点开，「他自己开」这件事就没了。
    返回里 need_pick 非空时，券和保底卡已经到账，还要他再挑一次自选那几张。
    """
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("开箱是孩子自己点的事", 403)
    bid = int(ctx.path_params["id"])
    r = E.open_box(me["id"], bid, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "开不了"))
    return r


@route("POST", "/api/boxes/:id/pick")
def post_pick_box(ctx):
    """自选件挑哪几张（一箱只挑一次，两张必须不同）。"""
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("挑卡是孩子自己的事", 403)
    bid = int(ctx.path_params["id"])
    codes = ctx.p("codes") or []
    if isinstance(codes, str):
        codes = [x for x in codes.split(",") if x]
    r = E.resolve_box_pick(me["id"], bid, codes, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "挑不了"))
    return r


@route("GET", "/api/boxes/history")
def box_history(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    rows = db.query("SELECT * FROM box_open WHERE member_id=? ORDER BY id DESC LIMIT 60", (mid,))
    out = []
    for r in rows:
        d = dict(r)
        d["random"] = json.loads(r["random_json"] or "{}")
        # v38：待开箱也在同一张表里，前端要能分出来 ——「最近开出来的」
        # 那段只认开过的，不然会把一只还没开的空箱子画进去。
        d["opened"] = bool(r["opened_at"])
        out.append(d)
    return {"items": out}


# ---------------------------------------------------------------------------
# 商店与道具
# ---------------------------------------------------------------------------
@route("GET", "/api/shop")
def get_shop(ctx):
    """v24 起商店摆两区：六种券，金 / 钻石 / 王者三档箱。

    券是日用品，六种全上架，价钱照旧；卡一张不卖 —— 卡是收藏品，
    主要从宝箱里开出来，商店一卖「攒卡」这件事就贬值了。
    箱子只卖金、钻石、王者：木铜银门槛太低，摆上货架会让「每天那七分」
    看起来可以绕过去，完美箱是满勤专属，任何情况下都不挂价签。
    """
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    cyc = E.current_cycle(mid)
    tickets, cards = [], []
    # purchasable=0 的连列表都不进：留着只会让人点了才知道买不了
    for it in db.query("SELECT * FROM item WHERE active=1 AND purchasable=1 ORDER BY sort"):
        row = {"id": it["id"], "code": it["code"], "name": it["name"], "category": it["category"],
               "rarity": it["rarity"], "card_no": it["card_no"], "price": it["price"],
               "purchasable": True, "weekly_limit": it["weekly_limit"],
               "shelf_life_days": it["shelf_life_days"], "max_hold": it["max_hold"],
               "desc": it["desc"], "effect": json.loads(it["effect_json"] or "{}"),
               "icon": it["icon"],
               "owned": E.item_balance(mid, it["id"]),
               "bought_this_cycle": E._weekly_bought(
                   mid, it["id"], "shop_ticket" if it["category"] == "ticket" else "shop_card",
                   cyc["id"])}
        (tickets if it["category"] == "ticket" else cards).append(row)

    limit = int(db.cfg("box.purchase_weekly_limit", 1))
    used = db.query_one("SELECT COUNT(*) c FROM box_open WHERE member_id=? AND cycle_id=?"
                        " AND source='purchase'", (mid, cyc["id"]))["c"]
    boxes = []
    for t in db.query("SELECT * FROM box_tier WHERE purchase_allowed=1"
                      " AND purchase_price IS NOT NULL ORDER BY tier"):
        b = _box_row(t, as_purchase=True)
        b["bought_this_cycle"] = used
        b["weekly_limit"] = limit
        # 打出来的箱子门槛是多少分，摆出来让人自己比：买比打贵，这是故意的
        b["threshold"] = t["threshold"]
        boxes.append(b)
    # v30：这里原来还回一个 surprise_pack，开关和价格都在设置页上，
    # 但全库没有任何购买实现 —— 值是回显给前端了，卡包一次也没出现过。
    # 现在把开关从设置页拿掉，这里也不再回显，免得前端又照着一个假字段画界面。
    return {"tickets": tickets, "cards": cards, "boxes": boxes,
            "box_limit": limit, "box_used": used,
            "stardust": E.stardust_balance(mid)}


@route("POST", "/api/shop/buy")
def post_buy(ctx):
    me = ctx.as_member()
    tid = ctx.target_child()
    code = ctx.need("code")
    it = E.item_by_code(code)
    if not it:
        raise ApiError("没有这个东西")
    if it["category"] == "ticket":
        r = E.buy_ticket(tid, code, ctx.i("qty", 1), operator_id=me["id"])
    else:
        r = E.buy_card(tid, code, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "买不了"))
    return r


@route("GET", "/api/holdings")
def get_holdings(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    E.process_expiry(mid)
    return {"tickets": E.to_ticket_list(mid), "cards": E.to_card_list(mid),
            # 用过的卡现在各是什么脸（装填 / 今天生效 / 已算进去 / 等办）。
            # 跟库存一起回，券包页那一栏就不用再多发一次请求。
            "faces": E.card_faces(mid),
            "expiring": [{"holding_id": h["id"], "name": h["name"], "rarity": h["rarity"],
                          "expires_at": h["expires_at"],
                          "renew_cost": round((h["price"] or 0) * (h["renew_cost_pct"] or 20) / 100.0, 2),
                          "renew_left": (h["renew_times"] or 1) - (h["renew_count"] or 0)}
                         for h in E.expiring_soon(mid)],
            "fragment": E.fragment_balance(mid), "stardust": E.stardust_balance(mid),
            "debt": max(0.0, E.debt_balance(mid))}


@route("POST", "/api/items/use")
def use_item(ctx):
    """用一张卡。真正的动作在 E.use_card 里，这里只做身份和参数。

    以前这个函数自己扣完库存就完了，卡的效果全靠家里人自己记。
    """
    me = ctx.as_member()
    mid = ctx.target_child()
    note = ctx.p("note", "")
    r = E.use_card(mid, str(ctx.need("code")), operator_id=me["id"], note=note,
                   qty=ctx.f("qty", 1))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "用不了"), 409)
    return r


@route("GET", "/api/cards/redeems")
def card_redeems(ctx):
    """等爸爸妈妈兑现的卡。家长看全家，孩子只看自己的。"""
    me = ctx.as_member()
    mid = None if me["role"] == "parent" else me["id"]
    want = ctx.i("member_id")
    if me["role"] == "parent" and want:
        mid = want
    rows = E.pending_redeems(mid)
    done = db.query("SELECT r.id, r.item_id, r.done_at, i.name, i.icon, i.rarity"
                    " FROM card_redeem r JOIN item i ON i.id=r.item_id"
                    " WHERE r.status='done' AND r.item_id IN"
                    " (SELECT item_id FROM card_redeem WHERE status='pending')"
                    " ORDER BY r.id DESC LIMIT 60")
    return {"items": rows, "recent": [dict(x) for x in done]}


@route("POST", "/api/cards/redeems/:id/done")
def card_redeem_done(ctx):
    """家长点「做到了」。只有家长能点，孩子点了等于自己给自己发奖。"""
    ctx.as_parent()
    rid = ctx.id_path()
    # done=false 是「这次没兑现」。参数可能来自 JSON 也可能来自 query，
    # ctx.truthy 两边都能读，写成 Inverted default True 会让 ?done=0 变 1，
    # 所以这里按「显式传了才算数」处理。
    raw = ctx.p("done")
    ok = ctx.truthy("done", True) if raw is not None else True
    r = E.finish_redeem(rid, operator_id=ctx.member["id"],
                        note=str(ctx.p("note", "") or ""), done=ok)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "处理不了"), 409)
    return r


@route("POST", "/api/items/renew")
def renew_item(ctx):
    me = ctx.as_member()
    mid = ctx.target_child()          # 卡必须是这个孩子的，扣的也是他的星尘
    hid = ctx.i("holding_id")
    r = E.renew_card(hid, operator_id=me["id"], owner_id=mid)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "续不了"))
    return r


# ---------------------------------------------------------------------------
# 券核销：机器闸门 + 家长点头（v14，v32 改成按轮算）
# ---------------------------------------------------------------------------
def _my_child(ctx):
    """券相关的操作对象：孩子只能是自己，家长必须指定。

    传了别人的 member_id 就直接报错，不静默忽略 —— 忽略参数是以后最容易
    变成漏洞的那种写法。Ctx.target_member() 一直是这个口径，这里对齐。
    """
    me = ctx.as_member()
    mid = ctx.i("member_id")
    if me["role"] != "parent" and mid is not None and mid != me["id"]:
        raise ApiError("只能看自己的", 403)
    return ctx.target_child()


def _ticket_state(ctx):
    code = ctx.p("code")
    item = E.item_by_code(code) if code else E.item_by_code(E.FUN_CODE)
    if not item:
        raise ApiError("没有这张券")
    if item["category"] != "ticket":
        raise ApiError("这不是券", 409)
    return _my_child(ctx), item


@route("GET", "/api/tickets/state")
def get_ticket_state(ctx):
    """娱乐券此刻能不能用、还差什么，够前端画清「为什么不能用」。"""
    ctx.as_member()
    mid, item = _ticket_state(ctx)
    day = ctx.p("day", E.today())
    st = E.ticket_use_state(mid, item, day)
    st["today"] = E.my_ticket_list(mid, day)
    st["need_approval"] = bool(db.cfg("ticket.need_approval", True))
    return st


@route("POST", "/api/tickets/request")
def post_ticket_request(ctx):
    """孩子发起一次券核销。过不了闸门的话，这里就把原因说清楚。"""
    ctx.as_member()
    mid, item = _ticket_state(ctx)
    r = E.request_ticket(mid, item["id"], ctx.f("qty", 1), ctx.p("note", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "现在用不了"), 409)
    r["today"] = E.my_ticket_list(mid)
    return r


@route("GET", "/api/tickets/pending")
def get_ticket_pending(ctx):
    """家长侧待处理。每条都带「现在批了还能不能用」，省得批完才发现过点了。

    start_delay 一并回去：家长点「同意」那一下的确认弹层要写清「点完先给他
    多久准备」，那个数不能在前端写死 60。
    """
    ctx.as_parent()
    return {"items": E.ticket_pending_list(),
            "start_delay": E._ticket_delay_seconds()}


@route("POST", "/api/tickets/resolve")
def post_ticket_resolve(ctx):
    me = ctx.as_parent()
    rid, approve = ctx.need("request_id", "approve")
    ok = approve if isinstance(approve, bool) else str(approve).lower() in ("1", "true", "yes")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise ApiError("申请编号不对")
    r = E.resolve_ticket_request(rid, ok, operator_id=me["id"],
                                reject_note=ctx.p("reject_note", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "没处理成"))
    return r


@route("POST", "/api/tickets/start")
def post_ticket_start(ctx):
    """「我准备好了」：把准备中的那张提前开跑。

    家长批的时候走不到这里 —— 那一刻本来就是同意「现在开始」，要不要马上
    开跑交给孩子自己说：他坐好了就点，没坐好就等满那 60 秒。
    """
    me = ctx.as_member()
    rid = ctx.need("request_id")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise ApiError("申请编号不对")
    r = E.start_ticket_now(rid, None if me["role"] == "parent" else me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "开不了"))
    mid = ctx.i("member_id") if me["role"] == "parent" else me["id"]
    r["playing"] = E.ticket_playing(mid or None)
    return r


@route("GET", "/api/tickets/mine")
def get_ticket_mine(ctx):
    """孩子侧：今天申请了什么、批没批、被拒的理由，以及此刻在不在玩。"""
    ctx.as_member()
    mid = _my_child(ctx)
    day = ctx.p("day", E.today())
    return {"day": day, "items": E.my_ticket_list(mid, day),
            "playing": E.ticket_playing(mid),
            # 今天用过什么：券包页底部那条流水，跟券的列表读的是同一批记录
            "used": E.my_used_today(mid, day),
            "now": E.now(),
            "state": E.ticket_use_state(mid, None, day)}


@route("POST", "/api/tickets/ack")
def post_ticket_ack(ctx):
    """孩子点掉「玩完了」那张存档卡，把它收进「今天用过什么」。

    点不点都能接着用券，这只是他自己那一下的收尾 —— 结束不该是无声的。
    """
    mid = _my_child(ctx)
    r = E.ack_ticket(ctx.need("request_id"), mid)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "点不了"))
    return {"ok": True, "items": E.my_ticket_list(mid),
            "used": E.my_used_today(mid)}


@route("POST", "/api/tickets/remind")
def post_ticket_remind(ctx):
    """孩子催一下「答应了还没办」的那张。一天一次，上限在设置里。"""
    mid = _my_child(ctx)
    r = E.remind_ticket(ctx.need("request_id"), mid)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "催不了"))
    return {"ok": True, "items": E.my_ticket_list(mid)}


@route("GET", "/api/tickets/fulfill")
def get_ticket_fulfill(ctx):
    """家长侧：答应了、还没办的券。

    陪伴 / 独处 / 好友那几种批了只是答应了，要家长真的腾出时间去做。
    它们跟「待兑现的卡」是一回事，所以家长端把两边并成一张兑现清单。
    """
    ctx.as_parent()
    return {"items": E.ticket_fulfill_list(),
            "remind_cap": int(db.cfg("ticket.remind_per_day", 1) or 0)}


@route("POST", "/api/tickets/fulfill")
def post_ticket_fulfill(ctx):
    """家长点「办好了」/「这次没办」。办好了必须写一句，孩子看得到。"""
    me = ctx.as_parent()
    done = ctx.p("done", "1")
    ok = done if isinstance(done, bool) else str(done).lower() not in ("0", "false", "no", "")
    r = E.fulfill_ticket(ctx.need("request_id"), operator_id=me["id"],
                         note=ctx.p("note", ""), done=ok)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "没记成"))
    return r


@route("GET", "/api/tickets/playing")
def get_ticket_playing(ctx):
    """此刻谁在玩、还剩多久。

    家长看全家，孩子只看自己 —— 孩子传别人的 member_id 不是静默忽略，
    是按 _my_child 的老口径直接报错。
    """
    me = ctx.as_member()
    if me["role"] == "parent":
        want = ctx.i("member_id")
        items = E.ticket_playing(want or None)
    else:
        if ctx.i("member_id") is not None and ctx.i("member_id") != me["id"]:
            raise ApiError("只能看自己的", 403)
        items = E.ticket_playing(me["id"])
    return {"items": items, "now": E.now(), "day": E.today()}


@route("POST", "/api/fragments/exchange")
def frag_exchange(ctx):
    me = ctx.as_member()
    mid = ctx.target_child()
    r = E.exchange_fragments(mid, ctx.p("mode", "random"), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "换不了"))
    return r


# ---------------------------------------------------------------------------
# 星尘出口：零花钱兑换（v24 起走三步：孩子发起 → 家长审核 → 孩子确认）
# ---------------------------------------------------------------------------
def _cash_meta(mid):
    cap = float(db.cfg("cash.monthly_cap_stardust", 60))
    used = E.month_cash_used(mid)
    hold = E.cash_pending_stardust(mid)
    rate = float(db.cfg("rate.stardust_to_cash", 0.5))
    return {"rate": rate, "cap": cap, "used": used, "hold": hold,
            "left": max(0.0, cap - used - hold),
            "balance": E.stardust_balance(mid), "month": E.today()[:7],
            "month_cash": round(used * rate, 2),
            "left_cash": round(max(0.0, cap - used - hold) * rate, 2),
            "cap_cash": round(cap * rate, 2)}


@route("GET", "/api/cash")
def cash_info(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    out = _cash_meta(mid)
    out["requests"] = E.cash_request_list(mid, limit=12)
    return out


@route("POST", "/api/cash/request")
def cash_request(ctx):
    """孩子发起兑换。target_child 已经把「孩子只能给自己提」管住了。"""
    me = ctx.as_member()
    mid = ctx.target_child()
    r = E.request_cash(mid, ctx.f("stardust"), note=ctx.p("note", ""), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "提不了"))
    return r


@route("GET", "/api/cash/requests")
def cash_requests(ctx):
    """孩子看自己的；家长不带 member_id 就是全部待审的。"""
    me = ctx.as_member()
    if me["role"] == "child":
        return {"items": E.cash_request_list(me["id"])}
    raw = ctx.p("member_id", None)
    if raw in (None, "", "0"):
        return {"items": E.cash_request_list(None, limit=60)}
    try:
        return {"items": E.cash_request_list(int(raw))}
    except (TypeError, ValueError):
        raise ApiError("member_id 不对")


@route("POST", "/api/cash/requests/:id/resolve")
def cash_resolve(ctx):
    me = ctx.as_member()
    if me["role"] not in ("parent", "admin"):
        raise ApiError("这一步是家长点的", 403)
    rid = ctx.id_path("id", "申请")
    approve = ctx.truthy("approve", False)
    r = E.resolve_cash_request(rid, approve, operator_id=me["id"],
                               reject_note=ctx.p("reject_note", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "处理不了"))
    return r


@route("POST", "/api/cash/requests/:id/received")
def cash_received(ctx):
    """孩子确认拿到现金。只允许本人。"""
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("「收到了」得他自己点", 403)
    rid = ctx.id_path("id", "申请")
    r = E.receive_cash_request(rid, me["id"], operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "确认不了"))
    return r


@route("POST", "/api/cash/requests/:id/cancel")
def cash_cancel(ctx):
    me = ctx.as_member()
    r = E.cancel_cash_request(ctx.id_path("id", "申请"), me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "撤不了"))
    return r


@route("GET", "/api/ledger")
def get_ledger(ctx):
    ctx.as_member()
    mid = ctx.target_child()
    mid = mid if isinstance(mid, int) else mid["id"]
    limit = ctx.clamp("limit", 1, 500, 100)
    rows = db.query("SELECT * FROM ledger WHERE member_id=? ORDER BY id DESC LIMIT ?", (mid, limit))
    out = []
    for r in rows:
        d = dict(r)
        d["kind_label"] = E.KINDS.get(r["kind"], r["kind"])
        out.append(d)
    return {"items": out, "stardust": E.stardust_balance(mid)}
