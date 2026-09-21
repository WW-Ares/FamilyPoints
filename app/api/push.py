# -*- coding: utf-8 -*-
"""推送配置。

为什么这一组不走 /api/settings：那个接口把每一项的值原样回显给任何家长，
而 device key 是密钥级的东西 —— 谁拿到谁能往那台手机发通知，跟密码一个级别。
所以它单独存一张表，列表接口只回后四位，改的时候不回显明文。

为什么改这几项不要双人确认：双人确认是给「改价格、改门槛」这类
会改变游戏规则的数值准备的。推送配错了顶多是收不到通知，不会冤枉谁，
而每改一次就等另一位家长点一下，结果是没人愿意去配它。
"""
import json

import db
import notify as N
from . import ApiError, route

# 允许通过本接口改的全局项。白名单，防止顺手把 redline.* 也塞进来。
GLOBAL_KEYS = {
    "push.enabled", "push.bark_server", "push.merge_seconds",
    "push.quiet_start", "push.quiet_end", "push.daily_score_at",
    "push.expire_warn_days", "site.base_url",
}


def mask(secret):
    """只回后四位。界面上要让人认出「这是我填的那条」，又不能把钥匙摆出来。"""
    s = str(secret or "")
    if len(s) <= 4:
        return "·" * len(s)
    return "····" + s[-4:]


def _target_public(t):
    return {"id": t["id"], "member_id": t["member_id"], "kind": t["kind"],
            "server": t["server"], "label": t["label"], "enabled": bool(t["enabled"]),
            "masked": mask(t["target"]), "fail_count": t["fail_count"],
            "last_ok_at": t["last_ok_at"], "last_err": t["last_err"]}


@route("GET", "/api/push")
def get_push(ctx):
    """家长看全家的配置，孩子只能看自己的。"""
    me = ctx.as_member()
    if ctx.is_parent:
        rows = db.query(
            "SELECT t.*, m.name AS who FROM push_target t JOIN member m ON m.id=t.member_id"
            " ORDER BY m.sort, t.id")
    else:
        rows = db.query(
            "SELECT t.*, m.name AS who FROM push_target t JOIN member m ON m.id=t.member_id"
            " WHERE t.member_id=? ORDER BY t.id", (me["id"],))
    items = []
    for r in rows:
        d = _target_public(r)
        d["who"] = r["who"]
        items.append(d)

    members = db.to_dicts(db.query(
        "SELECT id, name, role, avatar FROM member WHERE active=1 ORDER BY sort"))

    globals_ = {}
    if ctx.is_parent:
        for k in sorted(GLOBAL_KEYS):
            globals_[k] = db.cfg(k)
    return {"items": items, "members": members, "globals": globals_,
            "is_parent": bool(ctx.is_parent), "timely_kinds": sorted(N.TIMELY_KINDS)}


@route("POST", "/api/push/target")
def save_push_target(ctx):
    """新增或更新一条设备。没传 target 表示「只改开关和备注」，不动 key。

    这样界面上就可以在看不到明文的情况下改备注、停用、改名。
    """
    me = ctx.as_member()
    kind = ctx.p("kind", "bark")
    if kind != "bark":
        raise ApiError("现在只支持 Bark 这一条通道")
    mid = ctx.i("member_id") or me["id"]
    if mid != me["id"] and not ctx.is_parent:
        raise ApiError("只能配自己的设备", 403)
    row = db.query_one("SELECT id, role FROM member WHERE id=? AND active=1", (mid,))
    if not row:
        raise ApiError("没有这个成员", 404)

    tid = ctx.i("id")
    label = (ctx.p("label") or "").strip()[:20]

    if tid:
        # 更新分支：没传的字段一律保持原样。
        # 这里踩过一个坑 —— 原来是「不传 server 就用默认服务器」，
        # 结果是改一下备注就把自建服务器地址冲回了 api.day.app。
        # 界面上看不到，手机上一直收不到，最难查的就是这种。
        old = db.query_one("SELECT * FROM push_target WHERE id=?", (tid,))
        if not old:
            raise ApiError("没有这条设备", 404)
        if old["member_id"] != me["id"] and not ctx.is_parent:
            raise ApiError("只能改自己的设备", 403)
        key = ctx.p("target")
        if key is not None and str(key).strip() == "":
            raise ApiError("device key 不能清空，不要了就删掉这条")
        srv = _check_server(ctx.p("server"))
        en = ctx.p("enabled")
        # 两格都可能被整条分享 URL 粘进来（https://api.day.app/<key>/），
        # 存之前先拆开。没传的那一格拿库里原值当底，这样「只改备注」
        # 不会因为拆一遍就把 key 或服务器冲掉。
        base, k, _ = N.split_fields(srv if srv is not None else old["server"],
                                    key if key is not None else old["target"])
        db.execute(
            "UPDATE push_target SET server=?, target=?, label=?,"
            " enabled=COALESCE(?, enabled) WHERE id=?",
            (base or old["server"], (k or "").strip() or old["target"], label,
             (1 if en else 0) if en is not None else None, tid))
        return {"ok": True, "id": tid, "server": base or old["server"],
                "masked": mask((k or "").strip() or old["target"])}

    server = _check_server(ctx.p("server")) or db.cfg("push.bark_server",
                                                      "https://api.day.app")
    enabled = 1 if ctx.p("enabled", True) else 0

    # 整条分享 URL 粘进哪一格都行，这里统一拆成服务器 + key。
    server, key, from_url = N.split_fields(server, ctx.p("target"))
    key = (key or "").strip()
    if len(key) < 8:
        raise ApiError("device key 太短了，Bark App 里点一下就能复制到")
    n = db.query_one("SELECT COUNT(*) c FROM push_target WHERE member_id=?", (mid,))["c"]
    if n >= 5:
        raise ApiError("一个人最多配 5 台设备")
    new_id = db.execute(
        "INSERT INTO push_target (member_id, kind, server, target, label, enabled, created_at)"
        " VALUES (?,?,?,?,?,?,?)", (mid, kind, server, key, label, enabled, db.now()))
    return {"ok": True, "id": new_id, "server": server, "masked": mask(key),
            "from_url": from_url}


def _check_server(v):
    """服务器地址的校验。返回规整后的值，没传就返回 None（交给 COALESCE 保留原值）。"""
    if v is None:
        return None
    s = str(v).strip().rstrip("/")
    if not s:
        return None
    if not s.startswith("http"):
        raise ApiError("服务器地址要以 http 开头")
    return s


@route("DELETE", "/api/push/target/:id")
def delete_push_target(ctx):
    me = ctx.as_member()
    tid = int(ctx.path_params["id"])
    t = db.query_one("SELECT * FROM push_target WHERE id=?", (tid,))
    if not t:
        raise ApiError("没有这条设备", 404)
    if t["member_id"] != me["id"] and not ctx.is_parent:
        raise ApiError("只能删自己的设备", 403)
    db.execute("DELETE FROM push_target WHERE id=?", (tid,))
    return {"ok": True}


@route("POST", "/api/push/test")
def test_push(ctx):
    """发一条测试。同步发，错误当场显示 —— 这是唯一一个
    能让人确认「device key 填对了」的动作，异步吞掉错误等于没测。"""
    me = ctx.as_member()
    tid = ctx.i("id")
    if tid:
        t = db.query_one("SELECT * FROM push_target WHERE id=?", (tid,))
        if not t:
            raise ApiError("没有这条设备", 404)
        if t["member_id"] != me["id"] and not ctx.is_parent:
            raise ApiError("只能测自己的设备", 403)
    else:
        key = (ctx.p("target") or "").strip()
        if not key:
            raise ApiError("先填 device key")
        srv, key, _ = N.split_fields(ctx.p("server") or db.cfg("push.bark_server"), key)
        t = {"server": srv.strip() or db.cfg("push.bark_server"), "target": key}
    ok, why = N.send_test(t)
    if not ok:
        return {"ok": False, "error": why}
    if tid:
        db.execute("UPDATE push_target SET fail_count=0, last_ok_at=?, last_err='' WHERE id=?",
                   (db.now(), tid))
    return {"ok": True}


@route("POST", "/api/push/settings")
def save_push_settings(ctx):
    ctx.as_parent()
    body = ctx.body or {}
    changed = []
    for k, v in body.items():
        if k not in GLOBAL_KEYS:
            continue
        changed.append(k)
        # 直接写，不走 db.set_setting —— 那条路会生成一条待确认的变更，
        # 而这一组配置就是要一个人当场改完的。
        old = json.dumps(db.cfg(k), ensure_ascii=False)
        new = json.dumps(v, ensure_ascii=False)
        db.execute("UPDATE setting SET value=?, updated_at=? WHERE key=?", (new, db.now(), k))
        db.execute("INSERT INTO audit_log (actor_id, action, target_type, before_json,"
                   " after_json, ts) VALUES (?,'push.config',?,?,?,?)",
                   (ctx.member["id"], k, old, new, db.now()))
    db.settings_all(force=True)
    N.kick()
    return {"ok": True, "changed": changed}
