# -*- coding: utf-8 -*-
"""校准、任务、心愿、许愿池、加时、求助、假期、报告、通知。"""
import json
import re
from datetime import datetime

import db
import engine as E
import holiday_cn
from . import ApiError, route

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_day(v, label="日期"):
    """日历日期必须是 YYYY-MM-DD，而且真的存在。

    这套库里的日期全按字符串比较。一个「明天」「2026/9/1」进来不会报错，
    会安安静静躺进表里，然后在所有比较里排到最前或最后 ——
    假期日历排错一次，全家的卡片有效期跟着错一年。
    """
    s = str(v or "").strip()
    if not _DAY_RE.match(s):
        raise ApiError("%s 要写成 2026-09-01 这样的格式" % label)
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise ApiError("%s 不是一个真实存在的日期" % label)
    return s


# ---------------------------------------------------------------------------
# 校准
# ---------------------------------------------------------------------------
@route("POST", "/api/calibration")
def post_calibration(ctx):
    me = ctx.as_parent()
    mid = ctx.target_child()
    reason = ctx.need("reason")
    r = E.add_calibration(mid, ctx.i("level", 2), reason,
                          dimension_code=ctx.p("dimension_code"),
                          effect_type=ctx.p("effect_type", "none"),
                          amount=ctx.f("amount", 0), template=ctx.p("template"),
                          # std 只在家长选「自己写一条」时有值，说的是那条修复
                          # 具体让他做什么；没写就照预设来。
                          repair_std=(ctx.p("std") or None),
                          operator_id=me["id"], auto_task=ctx.truthy("auto_task", True))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "记不下来"))
    return r


@route("GET", "/api/calibration")
def list_calibration(ctx):
    ctx.as_member()
    mid = ctx.target_member()
    mid = mid if isinstance(mid, int) else mid["id"]
    me = ctx.member
    sql = ("SELECT c.*, d.name AS dimension, m.name AS actor, t.title AS task_title,"
           " t.status AS task_status FROM calibration c"
           " LEFT JOIN dimension d ON d.id=c.dimension_id"
           " LEFT JOIN member m ON m.id=c.operator_id"
           " LEFT JOIN task t ON t.calibration_id=c.id WHERE c.member_id=?")
    args = [mid]
    if me["id"] != mid and not ctx.is_parent:
        raise ApiError("看不了", 403)
    rows = db.query(sql + " ORDER BY c.id DESC LIMIT 100", args)
    out = []
    for r in rows:
        d = dict(r)
        d["effect"] = json.loads(r["effect_json"] or "{}")
        out.append(d)
    return {"items": out}


# ---------------------------------------------------------------------------
# 任务清单
# ---------------------------------------------------------------------------
@route("GET", "/api/tasks")
def list_tasks(ctx):
    me = ctx.as_member()
    E.archive_due_tasks()
    mid = ctx.i("member_id", me["id"] if me["role"] != "parent" else None)
    status = ctx.p("status")
    sql = ("SELECT t.*, m.name AS assignee FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
           " WHERE 1=1")
    args = []
    if me["role"] != "parent":
        sql += " AND t.assignee_id=? AND t.kind='reward'"
        args.append(me["id"])
    elif mid:
        sql += " AND t.assignee_id=?"
        args.append(mid)
    if status:
        sql += " AND t.status=?"
        args.append(status)
    sql += " ORDER BY CASE t.status WHEN 'submitted' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, t.id DESC LIMIT 200"
    rows = db.query(sql, args)
    out = []
    for r in rows:
        d = dict(r)
        d["reward"] = json.loads(r["reward_json"] or "{}")
        out.append(d)
    return {"items": out}


@route("POST", "/api/tasks")
def post_task(ctx):
    me = ctx.as_parent()
    # 挂大厅的任务这会儿还不知道谁做，assignee_id 留空
    open_to_all = ctx.truthy("open_to_all")
    assignee = None if open_to_all else ctx.target_child("assignee_id")
    title, std = ctx.need("title", "std")
    r = E.create_task(assignee, title, std, reward_type=ctx.p("reward_type", "stardust"),
                      reward=ctx.p("reward", {}), deadline=ctx.p("deadline"),
                      created_by=me["id"], visibility=ctx.p("visibility", "family"),
                      slots=ctx.clamp("slots", 0, 50, 1) if open_to_all else 1,
                      icon=ctx.p("icon", ""))
    if isinstance(r, dict) and not r.get("ok"):
        raise ApiError(r.get("msg", "发不出去"))
    return {"ok": True, "task_id": r}


@route("POST", "/api/tasks/:id/submit")
def task_submit(ctx):
    me = ctx.as_member()
    tid = ctx.id_path()
    t = db.query_one("SELECT * FROM task WHERE id=?", (tid,))
    if not t:
        raise ApiError("找不到这个任务")
    if me["role"] != "parent" and t["assignee_id"] != me["id"]:
        raise ApiError("这不是你的任务", 403)
    r = E.submit_task(tid, me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "提交不了"))
    return r


@route("POST", "/api/tasks/:id/confirm")
def task_confirm(ctx):
    me = ctx.as_parent()
    tid = ctx.id_path()
    r = E.confirm_task(tid, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "确认不了"))
    return r


@route("POST", "/api/tasks/:id/return")
def task_return(ctx):
    me = ctx.as_parent()
    tid = ctx.id_path()
    r = E.return_task(tid, operator_id=me["id"], note=ctx.p("note", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "退回不了"))
    return r


@route("POST", "/api/tasks/archive")
def task_archive(ctx):
    ctx.as_parent()
    return E.archive_due_tasks()


@route("GET", "/api/tasks/templates")
def task_templates(ctx):
    ctx.as_member()
    return {"repair": json.loads(db.query_one(
        "SELECT value FROM setting WHERE key='repair.templates'")["value"])}


# ---------------------------------------------------------------------------
# 任务大厅（v15）
# ---------------------------------------------------------------------------
@route("GET", "/api/tasks/hall")
def get_task_hall(ctx):
    """家长和孩子共用一份数据。孩子多几个「我能干嘛」的标记。"""
    me = ctx.as_member()
    d = E.task_hall(viewer=me["id"] if me["role"] == "child" else None)
    d["role"] = me["role"]
    d["me"] = me["id"]
    return d


@route("GET", "/api/tasks/mine")
def task_history_mine(ctx):
    """孩子自己的任务记录（孩子端任务页底部那块用的就是它）。

    和 GET /api/tasks 分工不同：那条是家长在用的家庭任务清单，对孩子只回
    kind='reward'；这一条只回自己的，reward 和 repair 都要，状态一个不筛。
    家长带 member_id 也能看 —— 同一件事两边必须同一个口径。
    """
    me = ctx.as_member()
    if me["role"] == "parent":
        mid = ctx.i("member_id")
        if not mid:
            raise ApiError("家长要看谁的？", 400)
    else:
        mid = me["id"]
    return E.my_task_history(mid, days=ctx.i("days") or 30)


@route("POST", "/api/tasks/:id/claim")
def task_claim(ctx):
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("这是给孩子领的任务", 403)
    r = E.task_claim(ctx.id_path(), me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "领不了"))
    return r


@route("POST", "/api/tasks/:id/abandon")
def task_abandon(ctx):
    me = ctx.as_member()
    if me["role"] != "child":
        raise ApiError("只有领了的人能放下", 403)
    r = E.task_abandon(ctx.id_path(), me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "放不下"))
    return r


@route("POST", "/api/tasks/:id/revoke")
def task_revoke(ctx):
    me = ctx.as_parent()
    r = E.task_revoke(ctx.id_path(), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "撤不了"))
    return r


# ---------------------------------------------------------------------------
# 心愿单
# ---------------------------------------------------------------------------
@route("GET", "/api/wishes")
def list_wishes(ctx):
    ctx.as_member()
    mid = ctx.target_member()
    mid = mid if isinstance(mid, int) else mid["id"]
    rows = db.query("SELECT * FROM wish WHERE member_id=? ORDER BY id DESC LIMIT 50", (mid,))
    return {"items": [E.wish_view(r, with_progress=True) for r in rows],
            "limit": db.cfg("wish.max_active", 2),
            "pending_limit": db.cfg("wish.max_pending", 3),
            "templates": ["fixed", "stardust", "task_count", "streak", "perfect_day"]}


@route("POST", "/api/wishes")
def post_wish(ctx):
    """建心愿。两条路，分岔在「条件是谁给的」。

    孩子只能许愿：写下想要什么，条件留白，状态挂起等家长。
    家长一步到位：条件和心愿一起给，直接生效。
    """
    me = ctx.as_member()
    mid = ctx.target_child()
    title = ctx.need("title")
    if me["role"] != "parent":
        # 孩子许愿这一路刻意不接 icon：心愿的图由家长点亮时挑。
        r = E.wish_one(mid, title, by_child=True,
                       reward_desc=ctx.p("reward_desc", ""), operator_id=me["id"])
    else:
        selfpay = ctx.f("selfpay", 0) or 0
        if selfpay < 0:
            # 负数自付等于给孩子发一笔星尘：引擎里那条 add_ledger 是减负数。
            raise ApiError("自付星尘不能是负数")
        r = E.create_wish(mid, title, ctx.p("cond_type", "fixed"), ctx.p("cond", {}),
                          ctx.p("reward_desc", ""), ctx.p("price_note", ""),
                          selfpay, operator_id=me["id"],
                          icon=ctx.p("icon", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "建不了"))
    return r


@route("GET", "/api/wishes/pending")
def list_pending_wishes(ctx):
    """所有孩子挂起的心愿，家长侧一处看完（v24）。

    以前这些只在「设置 → 心愿单」那个弹层里能看到，审核页没有 ——
    孩子写完那句「等爸爸妈妈定条件」就再没人回应它。
    审核页要的就是「球在我这边的事」，这一条以前漏在外面。
    """
    ctx.as_parent()
    rows = db.query(
        "SELECT w.*, m.name AS who FROM wish w JOIN member m ON m.id=w.member_id"
        " WHERE w.status='wished' ORDER BY w.id")
    return {"items": [dict(r) for r in rows],
            "count": len(rows),
            "pending_limit": db.cfg("wish.max_pending", 3)}


@route("POST", "/api/wishes/:id/configure")
def configure_wish(ctx):
    """家长给挂起的心愿定条件。这一步就是「点亮生效」。

    图标也在这步接：心愿的图由家长挑，孩子许愿那一步给不了 icon
    （那条请求根本不带这个字段），所以只有这里能改。
    """
    me = ctx.as_parent()
    wid = ctx.id_path()
    r = E.configure_wish(wid, ctx.p("cond_type", "fixed"), ctx.p("cond", {}),
                         reward_desc=ctx.p("reward_desc", None),
                         price_note=ctx.p("price_note", None), operator_id=me["id"],
                         icon=ctx.p("icon", None))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "定不了条件"))
    return r


@route("POST", "/api/wishes/:id/pay")
def pay_wish(ctx):
    """把「星尘自付」那一步付掉。孩子付自己的，家长可以代付。"""
    me = ctx.as_member()
    wid = ctx.id_path()
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wid,))
    if not w:
        raise ApiError("找不到这个心愿")
    if me["role"] != "parent" and w["member_id"] != me["id"]:
        raise ApiError("这不是你的心愿", 403)
    r = E.pay_wish_selfpay(wid, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "付不了"))
    return r


@route("POST", "/api/wishes/:id/submit")
def submit_wish_cond(ctx):
    """孩子就某一条条件说「我做到了」。

    只有家长自己写的那句话（custom）能提交 —— 分数、星尘、任务数这些
    系统算得出来，算够了会自动记上，不该让人替一件已经成立的事实等审批。
    """
    me = ctx.as_member()
    wid = ctx.id_path()
    r = E.submit_wish_cond(wid, ctx.p("cond_key", "custom"),
                           ctx.p("note", ""), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "提交不了"))
    return r


@route("GET", "/api/wishes/submissions")
def list_wish_submissions(ctx):
    """等着家长点头的那几条提交。审核页用。

    跟 /api/wishes/pending 是两回事：那边是「心愿挂起了、条件还没定」，
    这边是「条件早就定了、孩子说他自己做到了」。两件事在家长那儿都是
    「球在我这边」，但要做的事完全不同，混在一栏里必然做错。
    """
    ctx.as_parent()
    return {"items": E.pending_wish_claims(), "count": len(E.pending_wish_claims())}


@route("POST", "/api/wishes/claims/:id")
def resolve_wish_claim(ctx):
    """家长确认（或驳回）孩子提交的那一条。"""
    me = ctx.as_parent()
    cid = ctx.id_path()
    approve = ctx.p("approve")
    if approve is None:
        raise ApiError("要说清楚通过还是不通过")
    r = E.resolve_wish_claim(cid, bool(approve), operator_id=me["id"],
                             reject_note=ctx.p("reject_note", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "处理不了"))
    return r


@route("GET", "/api/wishes/to-fulfil")
def list_wish_to_fulfil(ctx):
    """条件到了、还没给他的那几条。审核页那张兑现清单里「心愿」这一类。

    跟 /api/wishes/pending（挂着等他定条件）、/api/wishes/submissions
    （他交了、等你点头）是三件事，等的不是同一个人：这一条等的是家长
    真的去把事情办了 —— 买回来、约上时间、带他去。
    """
    ctx.as_parent()
    items = E.wish_to_fulfil()
    return {"items": items, "count": len(items)}


@route("POST", "/api/wishes/:id/status")
def wish_status(ctx):
    """心愿最后两步，一人一半。

    v44 之前这里只有「家长点一下兑现了」—— 点完直接进历史，孩子那头从头
    到尾没被问过一句。现在拆成两半：家长说「已经给他了」（delivered）、
    孩子说「我收到了」（claimed）。后一半没做，这条心愿就不算完。

    「达成」不在这里了：条件够不够是系统算的（check_wish_ready 算够了
    当场落 achieved），不该由谁按一下按钮决定 —— 那颗按钮撤掉。
    """
    me = ctx.as_member()
    wid = ctx.id_path()
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wid,))
    if not w:
        raise ApiError("找不到这个心愿")
    if me["role"] != "parent" and w["member_id"] != me["id"]:
        raise ApiError("这不是你的心愿", 403)
    status = ctx.need("status")
    if status not in ("delivered", "claimed", "cancelled"):
        raise ApiError("状态不对")
    if status == "delivered":
        # 这一句说的是「我把东西给他了」，只有家长做得来
        if me["role"] != "parent":
            raise ApiError("这一步由爸爸妈妈来")
        if w["status"] != "achieved":
            raise ApiError("这条心愿现在还轮不到这一步")
    if status == "claimed":
        # 收尾这一下必须是他本人。大人替他点，「他确认过了」就成了一句假话，
        # 而这条链路存在的全部意义就是那一下确认 —— 所以刻意不留代点口子。
        # 他不点就一直挂在那儿，这是定下来的口径，不做兜底。
        if int(me["id"]) != int(w["member_id"]):
            raise ApiError("这一下得他自己点")
        if w["status"] != "delivered":
            raise ApiError("还没人跟他说「给你了」，先等爸爸妈妈那一句")
    if status == "cancelled":
        # 不设否决权：一旦达成不许反悔
        if w["status"] in ("achieved", "delivered"):
            raise ApiError("已经达成的心愿不能取消，这一条是不设否决权的红线")
        if w["status"] not in ("wished", "active"):
            raise ApiError("这条心愿已经结束了")
    return E.update_wish_status(wid, status, operator_id=me["id"])


# ---------------------------------------------------------------------------
# 许愿池
# ---------------------------------------------------------------------------
@route("GET", "/api/pool")
def get_pool(ctx):
    ctx.as_member()
    p = E.pool_progress()
    entries = []
    logs = []
    if p:
        entries = db.to_dicts(db.query(
            "SELECT e.*, m.name FROM wish_pool_entry e LEFT JOIN member m ON m.id=e.member_id"
            " WHERE e.pool_id=? ORDER BY e.id DESC LIMIT 50", (p["id"],)))
        # 系统注入的那几笔（全家忘打卡 + 校准罚款）单独列出来。它们没有 member_id，
        # 混在投币列表里会显示成「不知道谁投的」，那是两件事。
        logs = db.to_dicts(db.query(
            "SELECT * FROM wish_pool_log WHERE pool_id=? ORDER BY id DESC LIMIT 20", (p["id"],)))
    else:
        # 还没立目标时，把「先记着、没处投」的那几笔摆出来 —— 界面得说清
        # 这笔钱没丢（忘打卡罚的 + 校准罚的），家长心里那本账才对得上。
        # 以前这里直接回空数组，家长端空态只有四个字「还没有全家目标」。
        logs = db.to_dicts(db.query(
            "SELECT * FROM wish_pool_log WHERE counted=0 AND COALESCE(stardust,0)>0"
            " ORDER BY id DESC LIMIT 20"))
    return {"pool": p, "entries": entries, "logs": logs,
            "templates": E.pool_templates()}


@route("POST", "/api/pool")
def post_pool(ctx):
    """家长设一个许愿池目标。

    只能从模板里挑，title 必须和模板对得上 —— 那道闸门在 engine.create_pool
    里，不在这里：接口层漏了它，引擎也不能漏。
    """
    me = ctx.as_parent()
    title = ctx.need("title")
    target = ctx.f("target_stardust", 0) or 0
    r = E.create_pool(title, ctx.p("target_desc", ""), target, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "建不了"))
    return r


@route("POST", "/api/pool/achieve")
def pool_achieve(ctx):
    ctx.as_parent()
    p = E.active_pool()
    if not p:
        raise ApiError("没有进行中的许愿池目标")
    db.execute("UPDATE wish_pool SET status='achieved', achieved_at=? WHERE id=?",
               (db.now(), p["id"]))
    return {"ok": True}


@route("POST", "/api/pool/deposit")
def pool_deposit(ctx):
    me = ctx.as_member()
    mid = ctx.i("member_id", me["id"])
    if me["role"] != "parent" and mid != me["id"]:
        raise ApiError("只能用自己的星尘投", 403)
    r = E.deposit_pool(mid, ctx.f("stardust"), pool_id=ctx.i("pool_id"), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "投不进去"))
    return r


# ---------------------------------------------------------------------------
# 加时申请 / 求助
# ---------------------------------------------------------------------------
@route("GET", "/api/overtime")
def list_overtime(ctx):
    ctx.as_member()
    if ctx.is_parent:
        rows = db.query("SELECT o.*, m.name FROM overtime_request o LEFT JOIN member m"
                        " ON m.id=o.member_id ORDER BY o.id DESC LIMIT 100")
    else:
        rows = db.query("SELECT * FROM overtime_request WHERE member_id=? ORDER BY id DESC LIMIT 50",
                        (ctx.member["id"],))
    return {"items": db.to_dicts(rows)}


@route("POST", "/api/overtime")
def post_overtime(ctx):
    me = ctx.as_member()
    mid = ctx.i("member_id", me["id"])
    if me["role"] != "parent" and mid != me["id"]:
        raise ApiError("只能给自己申请", 403)
    r = E.request_overtime(mid, ctx.p("day", E.today()), ctx.f("minutes", 30),
                           ctx.p("reason", ""))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "申请不了"))
    return r


@route("POST", "/api/overtime/:id/resolve")
def resolve_overtime(ctx):
    me = ctx.as_parent()
    rid = ctx.id_path()
    approve = ctx.truthy("approve")
    note = str(ctx.p("reject_note", "") or "").strip()
    if not approve and not note:
        # 第 09 章：拒绝必须写理由，这句话会留在孩子的记录里，他随时能翻到。
        # 写不出理由，就说明不该拒。
        raise ApiError("拒绝要写一句理由，这句话会留在孩子的记录里")
    r = E.resolve_overtime(rid, approve, operator_id=me["id"], reject_note=note)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "处理不了"))
    return r


@route("GET", "/api/help")
def list_help(ctx):
    ctx.as_member()
    if ctx.is_parent:
        rows = db.query("SELECT h.*, m.name FROM help_request h LEFT JOIN member m"
                        " ON m.id=h.member_id ORDER BY h.id DESC LIMIT 100")
    else:
        rows = db.query("SELECT * FROM help_request WHERE member_id=? ORDER BY id DESC LIMIT 50",
                        (ctx.member["id"],))
    return {"items": db.to_dicts(rows)}


@route("POST", "/api/help")
def post_help(ctx):
    me = ctx.as_member()
    mid = ctx.i("member_id", me["id"])
    if me["role"] != "parent" and mid != me["id"]:
        raise ApiError("只能给自己按", 403)
    detail = ctx.need("detail")
    r = E.request_help(mid, detail, ctx.p("day", E.today()), operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "按不了"))
    return r


@route("POST", "/api/help/:id/verify")
def verify_help(ctx):
    me = ctx.as_parent()
    rid = ctx.id_path()
    r = E.verify_help(rid, operator_id=me["id"], approved=ctx.truthy("approved", True))
    if not r.get("ok"):
        raise ApiError(r.get("msg", "核实不了"))
    return r


# ---------------------------------------------------------------------------
# 两个独立事件通道（第 09 / 10 章）
# ---------------------------------------------------------------------------
@route("GET", "/api/events")
def list_events(ctx):
    """偷玩与抄作业的记录。孩子只看自己的，家长可以指定。"""
    ctx.as_member()
    mid = ctx.target_child()
    E.end_due_downgrades()
    return {
        "device": db.to_dicts(db.query(
            "SELECT * FROM device_downgrade WHERE member_id=? ORDER BY id DESC LIMIT 20", (mid,))),
        "hw": db.to_dicts(db.query(
            "SELECT * FROM homework_check WHERE member_id=? ORDER BY id DESC LIMIT 20", (mid,))),
        "state": E.device_downgrade_state(mid),
        "repeat_window_days": int(db.cfg("steal_game.repeat_window_days", 30)),
    }


@route("POST", "/api/events/steal-game")
def post_steal_game(ctx):
    """记一次偷玩游戏。降级，不是没收，也不扣券。

    先查因：reason 写的就是问出来的那句话。理由留空也允许记，
    但界面上会提示「不问原因直接处理，下次他会做得更隐蔽」。
    """
    me = ctx.as_parent()
    mid = ctx.target_child()
    reason = str(ctx.p("reason", "") or "").strip()
    r = E.start_device_downgrade(mid, days=ctx.i("days"), reason=reason, operator_id=me["id"])
    if not r.get("ok"):
        raise ApiError(r.get("msg", "记不下来"))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, after_json, ts)"
               " VALUES (?,'event.steal_game','member',?,?,?)",
               (me["id"], mid, json.dumps({"days": r["days"], "reason": reason},
                                          ensure_ascii=False), db.now()))
    return r


@route("POST", "/api/events/homework")
def post_homework(ctx):
    """记一次抄作业。撤当日智识分 + 一条作业复核事件，其余 6 项不动。

    「讲给我听」不在这里生成：那是补课，走修复任务那条线（系统生成、
    孩子做完、家长确认）。这里只做撤分和留痕。
    """
    me = ctx.as_parent()
    mid = ctx.target_child()
    day = _valid_day(ctx.p("day", E.today()), "日期")
    subject = str(ctx.p("subject", "") or "").strip()
    note = str(ctx.p("note", "") or "").strip()
    r = E.revoke_study_score(mid, day, operator_id=me["id"], subject=subject, note=note)
    if not r.get("ok"):
        raise ApiError(r.get("msg", "撤不了"))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, after_json, ts)"
               " VALUES (?,'event.homework','member',?,?,?)",
               (me["id"], mid, json.dumps({"day": day, "subject": subject},
                                          ensure_ascii=False), db.now()))
    return r


# ---------------------------------------------------------------------------
# 假期
# ---------------------------------------------------------------------------
@route("GET", "/api/holidays")
def list_holidays(ctx):
    ctx.as_member()
    cal = holiday_cn.state_of()
    cal["today"] = holiday_cn.today_state()
    return {"items": db.to_dicts(db.query("SELECT * FROM holiday ORDER BY start_date")),
            "today": E.today(),
            "is_holiday": bool(E.holiday_at(E.today())),
            "is_transition": E.is_transition(E.today()),
            "calendar": cal}


@route("POST", "/api/holidays/sync")
def sync_holidays(ctx):
    """家长点了「立即更新」。这是全系统唯一会出网的接口。

    没有自动同步：不开机拉、不定时拉。容器没外网是常态，自动拉只会换来
    一堆超时日志，还让「上次更新」这个时间变得说不清是谁拉的。
    拉不到也要把回执带回去，界面上得说清楚，不能点了没反应。
    """
    ctx.as_parent()
    return {"ok": True, "calendar": holiday_cn.sync(force=True)}


@route("POST", "/api/holidays")
def post_holiday(ctx):
    ctx.as_parent()
    name, s, e = ctx.need("name", "start_date", "end_date")
    s = _valid_day(s, "开始日期")
    e = _valid_day(e, "结束日期")
    if s > e:
        raise ApiError("开始日期不能晚于结束日期")
    hid = db.execute("INSERT INTO holiday (name, start_date, end_date, auto_mode, created_at)"
                     " VALUES (?,?,?,?,?)", (name, s, e, 1, db.now()))
    # 填完就自动触发一次顺延
    delayed = E.apply_holiday_delay(operator_id=ctx.member["id"])
    return {"ok": True, "holiday_id": hid, "delayed": delayed}


@route("DELETE", "/api/holidays/:id")
def del_holiday(ctx):
    ctx.as_parent()
    db.execute("DELETE FROM holiday WHERE id=?", (ctx.id_path(),))
    return {"ok": True}


@route("POST", "/api/holidays/delay")
def holiday_delay(ctx):
    ctx.as_parent()
    return {"ok": True, "delayed": E.apply_holiday_delay(operator_id=ctx.member["id"])}


# ---------------------------------------------------------------------------
# 报告与看板
# ---------------------------------------------------------------------------
@route("GET", "/api/report")
def report(ctx):
    me = ctx.as_member()
    mid = ctx.target_child()
    days = ctx.i("days", 30)
    rep = E.growth_report(mid, days)
    m = db.query_one("SELECT * FROM member WHERE id=?", (mid,))
    rep["member"] = {"id": m["id"], "name": m["name"], "role": m["role"]}
    # 孩子侧不显示折现金额，只有游戏内单位
    if me["id"] != mid and me["role"] != "parent":
        raise ApiError("看不了", 403)
    rep["stardust"] = E.stardust_balance(mid)
    # 折现金额只留在家长侧：孩子看到的永远是星尘这个游戏内单位
    if me["role"] == "parent":
        rep["cash_hidden"] = False
        rep["cash"] = round(E.stardust_balance(mid) * float(db.cfg("rate.stardust_to_cash", 0.5)), 2)
    else:
        rep["cash_hidden"] = True
    rep["level"] = E.level_of(mid)
    return rep


@route("GET", "/api/dashboard")
def dashboard(ctx):
    """家长首页。只列「谁还没做今天该做的事」，不做分数并排对比。"""
    ctx.as_parent()
    members = db.query("SELECT * FROM member WHERE active=1 ORDER BY sort")
    today = E.today()
    out = []
    for m in members:
        if m["role"] != "child":
            # v13：家长只打分，不进循环。看板上给一行「裁判」，不带任何分数，
            # 免得出现「家长今天还没打分 / 周能量 0」这种没有意义的状态。
            out.append({"id": m["id"], "name": m["name"], "avatar": m["avatar"],
                        "role": m["role"], "today_state": "judge", "energy": None,
                        "stardust": None, "debt": 0, "cycle_end": None,
                        "next_tier": None, "level": None, "level_title": None})
            continue
        if E.is_transition(today):
            state = "transition"
        else:
            existing = E.day_scores(m["id"], today)
            state = "scored" if existing else "unscored"
        cyc = E.current_cycle(m["id"])
        snap = E.cycle_snapshot(cyc["id"])
        lv = E.level_of(m["id"]) or {}
        out.append({"id": m["id"], "name": m["name"], "avatar": m["avatar"],
                    "role": m["role"], "today_state": state,
                    "device": E.device_downgrade_state(m["id"]),
                    "energy": snap["energy"], "stardust": E.stardust_balance(m["id"]),
                    "debt": max(0.0, E.debt_balance(m["id"])),
                    "cycle_end": snap["end_date"],
                    "card_flags": E.card_flags(m["id"], today),
                    "next_tier": snap["next_tier"],
                    "level": lv.get("level"), "level_title": lv.get("title")})
    # 待办那几个数只在 engine.todo_counts() 里数一遍（心跳签名也读它），
    # 这里不再自己数 —— 两处各数一遍，迟早对不上。
    return {
        "today": today,
        "is_holiday": bool(E.holiday_at(today)),
        "is_transition": E.is_transition(today),
        "members": out,
        "todo": E.todo_counts(),
        "pool": E.pool_progress(),
    }


@route("GET", "/api/catalog")
def catalog(ctx):
    """图鉴。只标「开出的 / 买来的」，不做谁收集得多的对比。"""
    ctx.as_member()
    mid = ctx.target_child()
    owned = {}
    for h in db.query("SELECT item_id, SUM(qty) q, MIN(source) src FROM holding"
                      " WHERE member_id=? AND qty>0 GROUP BY item_id", (mid,)):
        owned[h["item_id"]] = {"qty": h["q"], "source": h["src"]}
    rows = db.query("SELECT * FROM item WHERE category='card' AND active=1 ORDER BY rarity DESC, sort")
    order = {"common": 0, "rare": 1, "legend": 2, "diamond": 3}
    items = []
    for it in rows:
        o = owned.get(it["id"], {})
        items.append({"code": it["code"], "name": it["name"], "rarity": it["rarity"],
                      "card_no": it["card_no"], "desc": it["desc"],
                      "effect": json.loads(it["effect_json"] or "{}"),
                      "price": it["price"], "purchasable": bool(it["purchasable"]),
                      "shelf_life_days": it["shelf_life_days"], "icon": it["icon"],
                      # 家长端「券 · 卡 · 有效期」那一页要把这几条写出来（持有上限、
                      # 续期价、续几次、到期返还）。它们本来就在 item 表上躺着，
                      # 少给一次前端就得自己写死一套，早晚跟库里的值对不上。
                      "max_hold": it["max_hold"],
                      "renew_cost_pct": it["renew_cost_pct"], "renew_times": it["renew_times"],
                      "expire_refund": it["expire_refund"],
                      "owned": o.get("qty", 0), "source": o.get("source", ""),
                      "effect_key": it["effect_key"]})
    items.sort(key=lambda x: (order.get(x["rarity"], 9), x["card_no"]))
    return {"items": items, "fragment": E.fragment_balance(mid),
            "exchange": {"random": 10, "pick": 20}, "level": E.level_of(mid)}


@route("GET", "/api/notifications")
def notifications(ctx):
    ctx.as_member()
    rows = E.open_notifications(ctx.member["id"])
    return {"items": db.to_dicts(rows)}


@route("POST", "/api/notifications/read")
def read_notifications(ctx):
    """标记已读。给 id 就只标那一条（弹层里点「知道了」用），不给就一把全标。"""
    ctx.as_member()
    nid = ctx.i("id", 0)
    if nid:
        db.execute("UPDATE notification SET read_at=? WHERE id=?"
                   " AND (member_id=? OR member_id IS NULL) AND read_at IS NULL",
                   (db.now(), nid, ctx.member["id"]))
    else:
        db.execute("UPDATE notification SET read_at=? WHERE (member_id=? OR member_id IS NULL)"
                   " AND read_at IS NULL", (db.now(), ctx.member["id"]))
    return {"ok": True}


@route("GET", "/api/season")
def get_season(ctx):
    ctx.as_member()
    return E.season_snapshot()


@route("POST", "/api/season")
def set_season(ctx):
    """家长改赛季长度。改完重算本季结束日（假期顺延一并算上）。"""
    me = ctx.as_parent()
    days = ctx.i("length_days", 0)
    if days:
        if days < 7:
            raise ApiError("赛季太短了，至少 7 天")
        db.set_setting("season.length_days", days, actor_id=me["id"])
        return E.retune_season(days)
    return E.season_snapshot()
