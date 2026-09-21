# -*- coding: utf-8 -*-
"""API 路由注册与分发。

约定：每个 handler 收到一个 ctx，返回 dict；返回 None 表示已经自己处理过响应。
抛 ApiError 会被统一转成 4xx。
"""

import db

ROUTES = []


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def route(method, path):
    def deco(fn):
        ROUTES.append((method.upper(), path, fn))
        return fn
    return deco


def _match(pattern, path):
    """把 /api/tasks/:id/submit 与实际路径对上，返回参数字典。"""
    p = [x for x in pattern.strip("/").split("/") if x != ""]
    a = [x for x in path.strip("/").split("/") if x != ""]
    if len(p) != len(a):
        return None
    out = {}
    for i, seg in enumerate(p):
        if seg.startswith(":"):
            out[seg[1:]] = a[i]
        elif seg != a[i]:
            return None
    return out


def dispatch(method, path, ctx):
    method = method.upper()
    allowed = []
    for m, p, fn in ROUTES:
        params = _match(p, path)
        if params is None:
            continue
        if m != method:
            allowed.append(m)
            continue
        ctx.path_params = params
        return fn(ctx)
    if allowed:
        raise ApiError("这个方法不支持，试试 " + "/".join(sorted(set(allowed))), 405)
    raise ApiError("没有这个接口：" + path, 404)


def load():
    """导入所有路由模块，触发注册。"""
    from . import auth, play, growth, kids, push, icons   # noqa: F401
    return len(ROUTES)


class Ctx(object):
    def __init__(self, member, query, body, raw=None, token=None):
        self.member = member          # 已登录成员（dict）或 None
        self.query = query or {}      # URL 查询参数
        self.body = body or {}        # JSON 请求体
        self.raw = raw                # 原始 handler，需要时可写自定义响应
        self.token = token
        self.path_params = {}

    # --- 取参数 -------------------------------------------------------------
    def p(self, key, default=None):
        if key in self.body and self.body[key] is not None:
            return self.body[key]
        if key in self.query and self.query[key] is not None:
            return self.query[key]
        return default

    def need(self, *keys):
        out = []
        for k in keys:
            v = self.p(k)
            if v is None or v == "":
                raise ApiError("缺少参数：" + k)
            out.append(v)
        return out[0] if len(out) == 1 else out

    def i(self, key, default=None):
        v = self.p(key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def f(self, key, default=None):
        v = self.p(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def truthy(self, key, default=False):
        """显式解析布尔入参。

        bool("false") 是 True，前端把 JSON 里的 false 写成字符串时，
        一个「只派给女儿」的任务会静默变成大厅任务。所以只认这几种写法。
        """
        v = self.p(key, None)
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        return str(v).strip().lower() in ("1", "true", "yes", "on", "是")

    def id_path(self, key="id", label="id"):
        """取路径里的整数参数。取不到直接 400，不要让它冒成 500。"""
        raw = self.path_params.get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError("%s 不对" % label, 400)

    def clamp(self, key, low, high, default):
        """数值型入参夹到合理区间。负数 limit 在 SQLite 里等于「不限量」。"""
        v = self.i(key, default)
        if v is None:
            v = default
        return max(low, min(high, v))

    # --- 权限 ---------------------------------------------------------------
    @property
    def is_parent(self):
        return bool(self.member and self.member["role"] == "parent")

    def as_parent(self):
        if not self.member:
            raise ApiError("请先登录", 401)
        if not self.is_parent:
            raise ApiError("这一项只有家长能做", 403)
        return self.member

    @property
    def is_admin(self):
        return bool(self.member and self.member["is_admin"])

    def as_admin(self):
        """管理员比家长多两件事：开通账号、重置任何人的密码。

        v19：家长之间是平级的，但「谁能拉新人进来、谁能改别人的密码」
        得有人兜底，所以全库只有一位管理员。判断读库里的 is_admin，
        不信任调用方传什么，和 is_player / is_judge 一个路子。
        """
        if not self.member:
            raise ApiError("请先登录", 401)
        if not self.member["is_admin"]:
            raise ApiError("这一项只有管理员能做", 403)
        return self.member

    def as_member(self):
        if not self.member:
            raise ApiError("请先登录", 401)
        return self.member

    def target_member(self):
        """取操作对象：孩子自己只能操作自己，家长可以指定。"""
        me = self.as_member()
        mid = self.i("member_id")
        if mid is None:
            return me
        if me["role"] != "parent" and mid != me["id"]:
            raise ApiError("只能看自己的", 403)
        return mid

    def target_child(self, key="member_id"):
        """取操作对象，且必须是孩子（返回 int）。

        v13：家长只打分，不参与被打分。凡是会产生分数、周能量、宝箱、星尘、
        券、卡、图鉴记录的接口一律走这里，家长账号在这条线上被整体挡掉。
        孩子继续只能操作自己，家长可以指定。
        """
        me = self.as_member()
        if me["role"] != "parent":
            # 孩子传别人的 member_id 时静默按自己算：这一批接口全是「读自己」的，
            # 忽略参数不会越权，报错反而会打断前端那些顺手带上 member_id 的调用。
            # 需要「传错了就报」的口径在 _my_child（券核销）那边，别看错地方。
            mid = me["id"]
        else:
            mid = self.i(key)
            if mid is None:
                raise ApiError("请指定要操作的孩子")
        row = db.query_one("SELECT role FROM member WHERE id=?", (mid,))
        if not row:
            raise ApiError("没有这个成员", 404)
        if row["role"] != "child":
            raise ApiError("家长只负责打分，不参与被打分与奖励", 403)
        return mid
