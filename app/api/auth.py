# -*- coding: utf-8 -*-
"""会话、成员、设置、运维。"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta

import db
import engine as E
import seed_data
from . import ApiError, route

SESSION_DAYS = 180

PWD_MIN = 4
PWD_MAX = 64
PBKDF2_ROUNDS = 120000
PIN_LEN = 4


def hash_password(pwd, salt=None, rounds=PBKDF2_ROUNDS):
    """每个账号一个随机盐，写到哈希串里。

    v19 之前是 sha256("family-points" + pin)，全库同一个盐且只跑一轮 ——
    库文件被拷走的话，一张彩虹表就能把全家人的密码翻出来。家庭内网也不能这么存。
    格式 pbkdf2$轮数$盐$哈希，参数跟着串走，以后调强度不用再动老数据。
    """
    if pwd in (None, ""):
        return ""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", str(pwd).encode("utf-8"),
                             salt.encode("utf-8"), int(rounds))
    return "pbkdf2$%d$%s$%s" % (int(rounds), salt, dk.hex())


def check_password(pwd, stored):
    if not stored or pwd in (None, ""):
        return False
    try:
        algo, rounds, salt, _ = stored.split("$")
        if algo != "pbkdf2":
            return False
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pwd, salt, rounds), stored)


def check_pwd_rule(pwd, role=None):
    """短密码在这里就该被挡住，而不是等用户试三次才发现。

    家长那条只卡长度，不强制大小写和符号：这是给七八岁孩子用的，
    要求「Aa1!」的结果是他们把密码写在铅笔盒上，那比 1234 更糟。

    孩子那条（v36）更紧：**必须正好 4 位数字**。理由不是安全，是登录方式 ——
    孩子端登录页给的是数字键盘，输满 4 位自动提交，格子里根本敲不进字母。
    服务端跟着收紧，才不会出现「界面上进不去、库里其实是个 6 位密码」那种死结。

    写 `[0-9]` 不写 `\\d`：Python 的 `\\d` 认 Unicode 里的十进制数字，全角
    「１２３４」和阿拉伯数字「١٢٣٤」都能过。那种密码键盘上敲不出来，
    正好落回上面说的那个死结 —— 而且是最难查的一种：密码「设成功了」。
    """
    s = str(pwd or "")
    if role == "child":
        if not re.match(r"^[0-9]{%d}$" % PIN_LEN, s):
            raise ApiError("孩子的密码是 %d 位数字" % PIN_LEN)
        return
    if len(s) < PWD_MIN:
        raise ApiError("密码至少 %d 位" % PWD_MIN)
    if len(s) > PWD_MAX:
        raise ApiError("密码太长了，%d 位以内" % PWD_MAX)
    if s.strip() != s:
        raise ApiError("密码开头和结尾不要有空格")


def check_username(name):
    s = str(name or "").strip()
    if len(s) < 2:
        raise ApiError("账号名至少 2 个字")
    if len(s) > 16:
        raise ApiError("账号名太长了，16 个字以内")
    if " " in s:
        raise ApiError("账号名里不要有空格")
    return s


def check_name(name):
    """显示名。和账号名分开管。

    账号名是要天天敲的，所以卡长度、禁空格；显示名是屏幕上给人看的，
    「小 宝」这种带空格的名字没理由不让用。以前这里错调了 check_username，
    结果是改个显示名会被账号名的规则挡回来。
    """
    s = str(name or "").strip()
    if not s:
        raise ApiError("名字不能空着")
    if len(s) > 16:
        raise ApiError("名字太长了，16 个字以内")
    return s


def is_first_run():
    """全库一个设过密码的账号都没有，说明这是升级后第一次打开。"""
    return db.query_one(
        "SELECT COUNT(*) c FROM member WHERE active=1 AND password_hash!=''")["c"] == 0


def member_public(m):
    return {"id": m["id"], "name": m["name"], "role": m["role"], "avatar": m["avatar"],
            "sort": m["sort"], "username": m["username"] or "",
            "has_password": bool(m["password_hash"]), "is_admin": bool(m["is_admin"])}



# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
def make_session(member_id):
    token = secrets.token_urlsafe(24)
    exp = (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO session (token, member_id, created_at, expires_at) VALUES (?,?,?,?)",
               (token, member_id, db.now(), exp))
    return token


def resolve_session(token):
    if not token:
        return None
    row = db.query_one("SELECT * FROM session WHERE token=?", (token,))
    if not row:
        return None
    if row["expires_at"] < db.now():
        db.execute("DELETE FROM session WHERE token=?", (token,))
        return None
    return db.query_one("SELECT * FROM member WHERE id=? AND active=1", (row["member_id"],))


@route("GET", "/api/bootstrap")
def bootstrap(ctx):
    """一次拿齐启动数据，减少移动端往返。"""
    members = db.query("SELECT * FROM member WHERE active=1 ORDER BY sort")
    out = {
        "app": "家庭积分",
        # 对外版本号（seed_data.APP_VERSION）。库结构版本另有 meta.schema_version，界面不显示。
        "version": seed_data.APP_VERSION,
        "today": E.today(),
        # v36：登录页第一行那句家庭名（设置项 family.name，默认「我们家」）
        "family_name": str(db.cfg("family.name") or "我们家"),
        "members": [member_public(m) for m in members],
        "me": None,
        "is_parent": False,
        # 升级到 v19 后还没人设过密码。登录页据此切到「首次设置」，
        # 这一步只在全库都空的时候出现，设完第一个密码就永久消失。
        "needs_setup": is_first_run(),
        "holiday": None,
        "pool": None,
    }
    me = None
    if getattr(ctx, "token", None):
        me = resolve_session(ctx.token)
    if me:
        ctx.member = me
        out["me"] = member_public(me)
        out["is_parent"] = me["role"] == "parent"
        out["overview"] = E.member_overview(me["id"])
    h = E.holiday_at(E.today())
    out["holiday"] = dict(h) if h else None
    out["pool"] = E.pool_progress()
    out["open_notifications"] = len(E.open_notifications(me["id"] if me else None))
    return out


@route("POST", "/api/login")
def login(ctx):
    """两种进法。

    · 家长：账号 + 密码，账号名就是成员名字，家里人不用记别的。
    · 孩子（v36）：点头像 + 4 位数字密码。他不填账号 —— 名字和头像在登录页上
      摆着，点一下就直接进输密码那一步，所以给他留了 member_id 这个口。
      把 member_id 交出去不算泄底：未登录时 /api/bootstrap 本来就把成员名单
      （名字、头像、有没有设过密码）给到登录页用来画头像墙。

    两条路口不交叉：账号那条只认真家长（SQL 里挡掉 role='child'），
    孩子的名字填进去也进不来 —— 两个入口各走各的，界面上才立得住。

    勾了「记住我」给一个 180 天的 cookie；没勾就给会话 cookie，关掉浏览器就没了。
    """
    mid = ctx.i("member_id", 0)
    pwd = ctx.p("password", "")
    if mid:
        m = db.query_one("SELECT * FROM member WHERE id=? AND active=1", (mid,))
    else:
        username = str(ctx.need("username")).strip()
        # 账号这条路只留给家长。v36 起孩子没有「账号」这回事了 —— 他的入口是
        # 登录页那面头像墙，点完自己那张就进输密码。要是孩子还能拿名字当账号
        # 从这儿进来，家长入口上写的那句「只给爸爸妈妈」就是句空话：
        # 界面上立了规矩，服务端得跟着认，不然那是装饰不是规则。
        m = db.query_one(
            "SELECT * FROM member WHERE username=? AND active=1 AND role<>'child'",
            (username,))
    if not m:
        # 不区分「没这个账号」和「密码不对」，免得外面能一个个试出谁有账号。
        raise ApiError("账号或密码不对")
    if not m["password_hash"]:
        raise ApiError("这个账号还没设密码，让管理员在「家人账号」里开通一下")
    if not check_password(pwd, m["password_hash"]):
        # 点着头像进来的那条路，报「密码不对」比报「账号或密码不对」讲得通 ——
        # 他压根没填过账号。名字是登录页上就摆着的，这么说没多漏任何东西。
        raise ApiError("密码不对，再试一次" if mid else "账号或密码不对")
    token = make_session(m["id"])
    cookie = "fam_token=" + token + "; Path=/; SameSite=Lax"
    if ctx.p("remember", True):
        cookie += "; Max-Age=%d" % (SESSION_DAYS * 86400)
    return {"ok": True, "token": token, "member": member_public(m),
            "_set_cookie": cookie}


@route("POST", "/api/setup/admin")
def setup_admin(ctx):
    """首次设置：给管理员定账号名和密码。

    只在「一个设过密码的账号都没有」时可用。这个口子必须在设完之后立刻关掉，
    否则谁打开这个页面都能把自己设成管理员 —— 那就不是登录，是排队接管。
    """
    if not is_first_run():
        raise ApiError("已经设置过了，用账号密码登录")
    username = check_username(ctx.need("username"))
    pwd = ctx.need("password")
    check_pwd_rule(pwd)

    admin = db.query_one(
        "SELECT * FROM member WHERE role='parent' AND active=1 ORDER BY sort, id LIMIT 1")
    if not admin:
        admin = db.query_one("SELECT * FROM member WHERE active=1 ORDER BY sort, id LIMIT 1")
    if not admin:
        raise ApiError("库里一个成员都没有，先在设置里建一个")
    # 查重要排除自己：迁移时已经把他的名字填成了账号名，
    # 如果把「自己」也算成占用，那这一步永远过不去（这里踩过）。
    dup = db.query_one("SELECT id FROM member WHERE username=? AND active=1 AND id!=?",
                       (username, admin["id"]))
    if dup:
        raise ApiError("这个账号名已经有人用了")

    db.execute("UPDATE member SET username=?, password_hash=?, is_admin=1 WHERE id=?",
               (username, hash_password(pwd), admin["id"]))
    # 其余人清掉管理员标记，保证「只有一位管理员」这条不会因为历史数据被破掉
    db.execute("UPDATE member SET is_admin=0 WHERE id!=?", (admin["id"],))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'admin.setup','member',?,?)", (admin["id"], admin["id"], db.now()))
    token = make_session(admin["id"])
    m = db.query_one("SELECT * FROM member WHERE id=?", (admin["id"],))
    return {"ok": True, "token": token, "member": member_public(m),
            "_set_cookie": "fam_token=" + token + "; Path=/; Max-Age=%d; SameSite=Lax"
                           % (SESSION_DAYS * 86400)}



@route("POST", "/api/logout")
def logout(ctx):
    if getattr(ctx, "token", None):
        db.execute("DELETE FROM session WHERE token=?", (ctx.token,))
    return {"ok": True, "_set_cookie": "fam_token=; Path=/; Max-Age=0"}


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------
@route("GET", "/api/members")
def list_members(ctx):
    ctx.as_member()
    return {"members": [member_public(m) for m in
                        db.query("SELECT * FROM member WHERE active=1 ORDER BY sort")],
            "can_manage": bool(ctx.is_admin)}


@route("POST", "/api/members")
def add_member(ctx):
    """开通一个新账号。账号名和初始密码一起给，给完就能用。

    只有管理员能做 —— 家长能重置孩子密码，但「把新的人拉进来」是另一回事，
    能拉人的口子开大了，两个大人可以互相给对方开小号绕开双人确认。
    """
    me = ctx.as_admin()
    name, role = ctx.need("name", "role")
    if role not in ("parent", "child"):
        raise ApiError("角色只能是 parent 或 child")
    n = db.query_one("SELECT COUNT(*) c FROM member WHERE role=? AND active=1", (role,))["c"]
    if role == "parent" and n >= 2:
        raise ApiError("家长最多 2 位")
    if role == "child" and n >= 3:
        raise ApiError("孩子最多 3 个")
    username = check_username(ctx.p("username") or name)
    if db.query_one("SELECT id FROM member WHERE username=? AND active=1", (username,)):
        raise ApiError("这个账号名已经有人用了，换一个")
    pwd = ctx.p("password", "")
    if pwd:
        check_pwd_rule(pwd, role)
    mid = db.execute(
        "INSERT INTO member (name, role, avatar, username, password_hash, sort, active, created_at)"
        " VALUES (?,?,?,?,?,?,1,?)",
        (name, role, E.clean_avatar(ctx.p("avatar", "")), username, hash_password(pwd),
         ctx.i("sort", n + 1), db.now()))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'member.add','member',?,?)", (me["id"], mid, db.now()))
    return {"ok": True, "member_id": mid,
            "note": "已经能登录了" if pwd else "还没设密码，记得回来给他设一个"}


@route("POST", "/api/members/:id/password")
def reset_password(ctx):
    """重置别人的密码。管理员对谁都行；普通家长只对孩子。

    孩子自己改密码走 /api/me/password（要输旧密码）。这里是「他忘了」那条路，
    所以不要求旧密码，但必须留下是谁重置的。
    """
    me = ctx.as_member()
    mid = int(ctx.path_params["id"])
    tgt = db.query_one("SELECT * FROM member WHERE id=?", (mid,))
    if not tgt:
        raise ApiError("找不到这个人")
    if not me["is_admin"]:
        if me["role"] != "parent":
            raise ApiError("这一项只有家长能做", 403)
        if tgt["role"] != "child":
            raise ApiError("家长只能重置孩子的密码", 403)
    pwd = ctx.need("password")
    check_pwd_rule(pwd, tgt["role"])
    db.execute("UPDATE member SET password_hash=? WHERE id=?", (hash_password(pwd), mid))
    # 旧会话立刻作废：密码换了人就该被请出去，否则重置等于没重置。
    # 自己重置自己时保留当前这条，不然点完就把自己也踢了。
    db.execute("DELETE FROM session WHERE member_id=? AND token!=?", (mid, ctx.token or ""))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'member.reset_password','member',?,?)", (me["id"], mid, db.now()))
    return {"ok": True, "note": tgt["name"] + " 下次要用新密码进"}


@route("PATCH", "/api/members/:id")
def edit_member(ctx):
    me = ctx.as_parent()
    mid = ctx.id_path("id", "成员")
    m = db.query_one("SELECT * FROM member WHERE id=?", (mid,))
    if not m:
        raise ApiError("找不到这个人")
    # 普通家长只能改孩子的资料。名字和排序看着无害，但排序决定
    # 「谁是第一位家长」，而且改别的家长的名字等于替人改名。
    if not me["is_admin"] and m["role"] != "child":
        if mid != me["id"]:
            raise ApiError("只有管理员能改另一位家长的资料", 403)
    name = check_name(ctx.p("name", m["name"]))
    # 头像只存我们自己那几款的文件名（avatars/<token>.svg）。清成合法形状
    # 之后再入库：认不出来的值统一变成空串，显示回落到名字首字，不报错。
    avatar = E.clean_avatar(ctx.p("avatar", m["avatar"]))
    sort = max(0, min(99, ctx.i("sort", m["sort"]) or 0))
    policy = ctx.p("parent_yield_policy", m["parent_yield_policy"])
    if policy not in (None, "", "none", "half", "full"):
        raise ApiError("这个收益口径不认识")
    db.execute("UPDATE member SET name=?, avatar=?, sort=?, parent_yield_policy=? WHERE id=?",
               (name, avatar, sort, policy, mid))
    # 改账号名等于改登录方式，只有管理员能做
    if ctx.p("username", "") != "":
        if not me["is_admin"]:
            raise ApiError("只有管理员能改账号名", 403)
        uname = check_username(ctx.p("username"))
        dup = db.query_one("SELECT id FROM member WHERE username=? AND active=1 AND id!=?",
                           (uname, mid))
        if dup:
            raise ApiError("这个账号名已经有人用了")
        db.execute("UPDATE member SET username=? WHERE id=?", (uname, mid))
    # 管理员可以把管理员位交出去，全场只留一位
    if ctx.p("is_admin", None) is not None:
        if not me["is_admin"]:
            raise ApiError("只有管理员能转移管理员", 403)
        if int(ctx.p("is_admin")):
            if m["role"] != "parent":
                raise ApiError("管理员只能由家长担任")
            db.execute("UPDATE member SET is_admin=0")
            db.execute("UPDATE member SET is_admin=1 WHERE id=?", (mid,))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'member.edit','member',?,?)", (me["id"], mid, db.now()))
    return {"ok": True}


@route("DELETE", "/api/members/:id")
def archive_member(ctx):
    """成员只能停用，已有记录一律保留。

    普通家长只能停用孩子。原来只挡了「不能停用自己」，妈妈可以一条命令
    把爸爸（管理员）停掉，管理员就被锁在门外了 —— 这和「只有管理员能开通账号」
    是同一件事的两面，得一起守住。
    """
    me = ctx.as_parent()
    mid = ctx.id_path("id", "成员")
    tgt = db.query_one("SELECT * FROM member WHERE id=?", (mid,))
    if not tgt:
        raise ApiError("找不到这个人", 404)
    if mid == me["id"]:
        raise ApiError("不能停用自己")
    if not me["is_admin"]:
        if tgt["role"] != "child":
            raise ApiError("只有管理员能停用另一位家长", 403)
    elif tgt["is_admin"]:
        raise ApiError("先把管理员位交给别人，再停用这个账号", 403)
    db.execute("UPDATE member SET active=0, archived_at=? WHERE id=?", (db.now(), mid))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'member.archive','member',?,?)", (me["id"], mid, db.now()))
    return {"ok": True, "note": "已停用，历史记录全部保留"}


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
@route("GET", "/api/settings")
def get_settings(ctx):
    ctx.as_member()
    rows = db.query("SELECT * FROM setting ORDER BY grp, sort")
    groups = []
    cur = None
    for r in rows:
        if not cur or cur["grp"] != r["grp"]:
            cur = {"grp": r["grp"], "items": []}
            groups.append(cur)
        try:
            import json
            val = json.loads(r["value"])
        except (TypeError, ValueError):
            val = r["value"]
        cur["items"].append({"key": r["key"], "value": val, "vtype": r["vtype"],
                             "label": r["label"], "note": r["note"],
                             "locked": bool(r["locked"]), "editable": bool(r["editable"])})
    pending = db.query("SELECT * FROM setting_change WHERE status='pending' ORDER BY id DESC")
    return {"groups": groups, "pending": db.to_dicts(pending)}


@route("POST", "/api/settings")
def post_setting(ctx):
    me = ctx.as_parent()
    key = ctx.need("key")
    val = ctx.p("value")
    ok, msg = db.set_setting(key, val, actor_id=me["id"])
    if not ok:
        raise ApiError(msg)
    return {"ok": True, "message": msg}


@route("POST", "/api/settings/changes/:id/approve")
def approve_setting(ctx):
    me = ctx.as_parent()
    cid = int(ctx.path_params["id"])
    ch = db.query_one("SELECT * FROM setting_change WHERE id=?", (cid,))
    if not ch:
        raise ApiError("找不到这条变更")
    if ch["status"] != "pending":
        raise ApiError("这条已经处理过了")
    if ch["actor_id"] == me["id"]:
        raise ApiError("不能自己确认自己提的改动，需要另一位家长")
    ok, msg = db.set_setting(ch["key"], __import__("json").loads(ch["new_value"]),
                             actor_id=me["id"], approve=True)
    db.execute("UPDATE setting_change SET status=?, approver_id=?, resolved_at=? WHERE id=?",
               ("applied" if ok else "rejected", me["id"], db.now(), cid))
    if not ok:
        raise ApiError(msg)
    return {"ok": True}


@route("POST", "/api/me/avatar")
def set_own_avatar(ctx):
    """换自己的头像。

    名字、账号名归管理员管，头像不归 —— 头像不参与任何分数、额度和排名，
    挑哪一张是自己那张脸的事。家长给孩子换走家长端那个口
    （PATCH /api/members/:id，权限还是「管理员对谁都行，家长只对自己的孩子」）。
    """
    me = ctx.as_member()
    av = E.clean_avatar(ctx.p("avatar", ""))
    db.execute("UPDATE member SET avatar=? WHERE id=?", (av, me["id"]))
    return {"ok": True, "avatar": av}


@route("POST", "/api/me/password")
def change_own_password(ctx):
    """改自己的密码。孩子和家长都走这一个口，都要输旧密码。

    要求旧密码不是防外人，是防「手机在别人手上时被顺手改掉」——
    改完密码就等于换了门锁，原来那人进不来，屋主自己都不知道。
    """
    me = ctx.as_member()
    old = ctx.p("old", "")
    new = ctx.need("new")
    if not me["password_hash"]:
        raise ApiError("你这个账号还没设密码，让管理员先设一个")
    if not check_password(old, me["password_hash"]):
        raise ApiError("原来的密码不对")
    check_pwd_rule(new, me["role"])
    if check_password(new, me["password_hash"]):
        raise ApiError("新密码和旧的一样，不用改")
    db.execute("UPDATE member SET password_hash=? WHERE id=?", (hash_password(new), me["id"]))
    # 别的设备上还留着的登录一并作废，只留现在这台
    db.execute("DELETE FROM session WHERE member_id=? AND token!=?", (me["id"], ctx.token or ""))
    db.execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, ts)"
               " VALUES (?,'member.change_password','member',?,?)", (me["id"], me["id"], db.now()))
    return {"ok": True, "note": "别的设备上需要重新登录"}


# ---------------------------------------------------------------------------
# 运维
# ---------------------------------------------------------------------------
@route("POST", "/api/ops/snapshot")
def op_snapshot(ctx):
    ctx.as_parent()
    p = db.snapshot(int(db.cfg("ops.snapshot_keep_days", 30)))
    return {"ok": bool(p), "path": os.path.basename(p) if p else None}


@route("GET", "/api/ops/export")
def op_export(ctx):
    """整库导出，只给管理员。

    这份 JSON 里带着全家的 password_hash。就算是 pbkdf2 十二万轮，
    把它递出去也等于把离线爆破的材料一并递出去 —— 备份要能还原的
    从来不是密码，是分和账。所以顺手摘掉哈希，并标一句说明。
    """
    ctx.as_admin()
    d = db.export_json()
    for row in d.get("member", []):
        row.pop("password_hash", None)
    d["password_hash_omitted"] = True
    return d


@route("GET", "/api/ops/snapshots")
def op_snapshots(ctx):
    ctx.as_parent()
    d = db.SNAPSHOT_DIR
    if not os.path.isdir(d):
        return {"files": []}
    files = sorted(os.listdir(d), reverse=True)
    return {"files": [{"name": f, "size": os.path.getsize(os.path.join(d, f))} for f in files]}


@route("GET", "/api/audit")
def audit(ctx):
    ctx.as_parent()
    return {"items": db.to_dicts(db.query(
        "SELECT a.*, m.name AS actor FROM audit_log a LEFT JOIN member m ON m.id=a.actor_id"
        " ORDER BY a.id DESC LIMIT 200"))}
