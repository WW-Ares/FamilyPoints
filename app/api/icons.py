# -*- coding: utf-8 -*-
"""图标改动。

只有一条路由：给维度、宝箱档位、道具图鉴换图标。任务与心愿的图标不在这里，
那两个是在发布 / 点亮当时就定下来的（request 里带 icon 字段），因为图标跟
那条具体的东西绑在一起，不存在「事后统一维护」的场景。

为什么不用 /api/settings 那条路：
    settings 操作的是 setting 表，而这里改的是 dimension / box_tier / item
    三张表各自的 icon 列。硬塞进去要在 handler 里分叉，读起来很难受。

为什么不用双人确认：
    图标不改任何数值，改错了最坏的结果是「看着别扭」。价格、门槛、额度那些
    才需要两个人一起点头。跟 push 那一组同理由。
"""
import api
import db
import engine

route = api.route

# (kind -> 表名, 主键列名)。只列到这里为止，别的表不许从这里改。
TARGETS = {
    "dimension": ("dimension", "code"),
    "box": ("box_tier", "tier"),
    "item": ("item", "code"),
}


@route("GET", "/api/icon/list")
def list_icons(ctx):
    """三样能给家长改图标的东西，一次拿全。

    给前端的 key 各不相同：维度是 code、宝箱是 tier、道具是 code。
    三个混在一张列表里的话，前端得自己记住「这个 key 该发成整数还是字符串」，
    所以这里按 kind 分开，各自带上自己那个主键的名字。
    """
    ctx.as_parent()
    return {
        "dims": [{"key": r["code"], "name": r["name"], "icon": r["icon"]}
                 for r in db.query("SELECT * FROM dimension WHERE active=1 ORDER BY sort")],
        "boxes": [{"key": r["tier"], "name": r["name"], "icon": r["icon"]}
                  for r in db.query("SELECT * FROM box_tier ORDER BY tier")],
        "items": [{"key": r["code"], "name": r["name"], "icon": r["icon"]}
                  for r in db.query("SELECT * FROM item WHERE active=1 ORDER BY sort")],
    }


@route("POST", "/api/icon")
def set_icon(ctx):
    ctx.as_parent()
    kind = ctx.need("kind")
    key = ctx.p("key")
    icon = engine.clean_icon(ctx.p("icon", ""))
    if kind not in TARGETS:
        raise api.ApiError("这一类没有图标：" + kind)
    table, col = TARGETS[kind]
    row = db.query_one("SELECT 1 FROM %s WHERE %s=?" % (table, col), (key,))
    if not row:
        raise api.ApiError("找不到这个东西：" + str(key))
    db.execute("UPDATE %s SET icon=? WHERE %s=?" % (table, col), (icon, key))
    if not icon:
        return {"ok": True, "icon": "", "message": "图标已清空，界面会换成默认的那个"}
    return {"ok": True, "icon": icon, "message": "图标换好了"}
