# -*- coding: utf-8 -*-
"""孩子数据总览（v15）：速览、详细、打分记录。v18 加了首页动态。

四个接口都是聚合，不落新表。家长看全部；孩子只能看自己那份记录。
"""
import db
import engine as E
from . import ApiError, route


def _days(ctx, hi=365):
    """天数入参。写错了要报错，别悄悄当成「全部时间」——
    家长筛「近 7 天」结果看到的是几年的账，会以为孩子在短时间做了很多事。"""
    raw = ctx.p("days")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("天数写个整数就行")
    return max(1, min(hi, v))


@route("GET", "/api/kids/overview")
def kids_overview(ctx):
    """所有孩子一张速览卡，一次拿全，前端别为每个孩子各发一个请求。"""
    ctx.as_parent()
    return {"items": E.kids_overview()}


@route("GET", "/api/kids/:id/detail")
def kid_detail(ctx):
    """某个孩子的详细情况：等级、周期、这七天、手上的券卡、在做的事。"""
    ctx.as_parent()
    try:
        mid = int(ctx.path_params["id"])
    except (KeyError, TypeError, ValueError):
        raise ApiError("孩子 id 不对")
    d = E.kid_detail(mid)
    if not d:
        raise ApiError("没有这个成员", 404)
    return d


@route("GET", "/api/score/history")
def score_history(ctx):
    """天 × 维度的打分明细。孩子能看自己的，家长能看任何一个。"""
    mid = ctx.target_child()
    days = ctx.i("days", 30) or 30
    days = max(1, min(365, days))
    return E.score_history(mid, days=days, until=ctx.p("until"))


@route("GET", "/api/feed")
def feed(ctx):
    """首页动态：手上没做完的事 + 最近发生的事。

    这里不用 target_child：家长不传 member_id 时是「全部孩子」，
    而不是「缺参数」。首页就该一屏看完几个孩子，这是它和别的接口的区别。
    """
    me = ctx.as_member()
    limit = max(1, min(40, ctx.i("limit", 12) or 12))
    recent = max(0, min(20, ctx.i("recent", 6) or 6))
    if me["role"] != "parent":
        return E.feed(me["id"], limit=limit, recent_limit=recent)
    mid = ctx.i("member_id")
    if mid is not None:
        row = db.query_one("SELECT role FROM member WHERE id=?", (mid,))
        if not row or row["role"] != "child":
            raise ApiError("家长只负责打分，不参与被打分与奖励", 403)
    return E.feed(mid, limit=limit, recent_limit=recent)


@route("GET", "/api/activity")
def activity(ctx):
    """动态日志（v28）：账本翻成人话，家长查孩子的每一件事。

    和 /api/feed 的分工：feed 是首页那一小块「最近发生」，看的是这几天的
    家里在干什么；这个是完整账本，能按人、按类型、按时间翻，回答的是
    「这张券哪来的」「这笔星尘怎么没了」。

    孩子的口径按孩子自己那份走（只能看自己）：这条线上没有「别人家的事」。
    """
    me = ctx.as_member()
    limit = ctx.clamp("limit", 1, 200, 30)
    offset = ctx.clamp("offset", 0, 100000, 0)
    days = _days(ctx, 3650)
    group = (ctx.p("group") or "").strip() or None
    if group and group not in dict(E.ACTIVITY_GROUPS):
        raise ApiError("没有这一类")
    mid = ctx.i("member_id")
    if me["role"] != "parent":
        # 孩子传别人的 member_id 时按自己算：这条线是「读自己」，忽略参数不会越权
        # （取回来的还是自己的账），报错反而会打断顺手带上 member_id 的调用。
        # 这条口径跟 Ctx.target_child 一致，别在这里另立一套。
        return E.activity(me["id"], days=days, group=group, limit=limit, offset=offset)
    if mid is not None:
        row = db.query_one("SELECT role FROM member WHERE id=?", (mid,))
        if not row or row["role"] != "child":
            raise ApiError("家长只负责打分，不参与被打分与奖励", 403)
    return E.activity(mid, days=days, group=group, limit=limit, offset=offset)


@route("GET", "/api/dims")
def dims(ctx):
    """七个维度的报告（v28）：孩子端「分数」页用这一份。

    孩子能看自己的，家长能看任何一个 —— 家长那边本来就有记录页的矩阵，
    这个接口给孩子自己看，所以按 target_child 走。
    """
    mid = ctx.target_child()
    return E.dims_report(mid, days=_days(ctx, 365))
