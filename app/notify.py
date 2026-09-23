# -*- coding: utf-8 -*-
"""把网页里的通知推到手机上。

为什么是 Bark：这是唯一一条「不用自建、不用装中间服务、iPhone 上当天能用」的路。
安卓那边 Web Push 背后是 Google 的 FCM，国内到不了，浏览器厂商也把口子关了；
微信生态的推送在收紧，公众号消息被折叠之后属于「能用但不保证长久」。
Bark 走的是苹果 APNs，一台手机填一个 device key 就通。

三条设计上的取舍：

1. **推送只是网页通知的影子，不是另一份数据源。**
   所有消息先落 notification 表（引擎里的 push_notify 一直在做这件事），
   这里再把没发过的捡起来发出去。网页上看得见的，手机上才收得到；
   发失败了也只是手机没收到，网页那条永远在。

2. **发送永远在后台线程里。**
   企业微信和 Bark 这类接口卡三秒，请求线程就卡三秒 —— 孩子点一下「提交任务」，
   网页转三秒白圈，他下次就不点了。业务代码只负责写库 + 叫醒这里。

3. **一条通知只发一次。**
   靠 notification.pushed_at 判，为空才发。定时任务重启、
   服务器重启、网页刷新都不会让同一条消息发第二遍。

只用标准库。发送目标是 HTTP POST 一个 JSON，没有签名也没有加密 ——
Bark 支持 AES 加密推送，但标准库没有 AES，要么引 cryptography、
要么每次 fork 一个 openssl。为一条推送通道破掉「零依赖」，不值。
代价是通知标题和正文会经过 api.day.app 和苹果 APNs，这一点得写清楚。
"""
import json
import os
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import db

# 带时限、过一会儿就作废的通知：不吃合并窗口，免打扰也照样发。
# 券核销申请只有 20 分钟有效期，压到第二天早上发出去等于没发。
# cash 是零花钱兑换申请：孩子在等「什么时候能拿到钱」，攒到第二天早上再推
# 就变成「昨天说的今天才看到」，这一步的价值全在当天把话说清楚。
TIMELY_KINDS = {"ticket", "overtime", "device", "cash"}

# 每轮扫描的间隔（秒）。kick() 会立刻打断这个等待。
TICK_SECONDS = 10

# 定时任务多久跑一次（秒）
SCHED_TICK_SECONDS = 300

# 单条通知最多试几次。试完还失败就写 push_error 停手，
# 不反复轰炸 —— 一个填错的 device key 不值得让后台线程每十秒重试一遍。
MAX_TRIES = 3

HTTP_TIMEOUT = 8

_wake = threading.Event()
_started = False
_lock = threading.Lock()
_log = print if not os.environ.get("FAMILY_QUIET") else (lambda *a: None)

_opener_cache = None


def _opener():
    """发请求用的 opener。

    刻意**不读系统代理**。Windows 上 urllib 会去翻 IE 的代理设置，
    开发机上随便装过什么东西就会在那儿留一条，结果是往 127.0.0.1
    发的请求也被塞进代理，回来一个 502，看起来像 Bark 挂了。
    真需要走代理的话，设 FAMILY_PUSH_PROXY=http://host:port，
    别去动系统设置 —— 那是浏览器的事。

    https 的 SSL 上下文装在 HTTPSHandler 上，**不是**传给 open()。
    OpenerDirector.open() 的签名是 (fullurl, data, timeout)，
    没有 context 这一位，传了当场 TypeError。这个错只在服务器地址是
    https 的时候才冒出来，而测试用的假端点都是 http 的 127.0.0.1，
    所以一路测过来全是绿的。代价是：真机上填对了 key 也发不出去，
    提示只有一句 "TypeError"，跟 key 对不对完全没关系。
    """
    global _opener_cache
    if _opener_cache is not None:
        return _opener_cache
    proxy = (os.environ.get("FAMILY_PUSH_PROXY") or "").strip()
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy
                                            else {})]
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    _opener_cache = urllib.request.build_opener(*handlers)
    return _opener_cache


# ---------------------------------------------------------------------------
# 输入：把「服务器地址」和「device key」两格拆干净
# ---------------------------------------------------------------------------
def _is_url(s):
    return s.startswith("http://") or s.startswith("https://")


def split_fields(server, key):
    """返回 (server, key, from_url)。from_url 表示 key 是从地址里拆出来的。

    Bark 在 App 里给的分享格式是一整条 URL：

        https://api.day.app/FAKEKEY000000000000000/
        https://api.day.app/FAKEKEY000000000000000/标题/正文

    人很自然会把它整条粘进某一格。以前粘进「服务器地址」那一格，
    请求就打到 /<key>/push 上，回来 404，界面上只说「服务器返回 404」——
    看起来像 key 填错了，其实是地址多了一段。这里两种粘法都接：
    地址里带路径就以那一段当 key，路径空着才是真正的服务器地址。
    """
    server = str(server or "").strip()
    key = str(key or "").strip()
    if _is_url(key):
        # 整条 URL 粘到了 key 那一格
        server, key = key, ""
    if not _is_url(server):
        return server.rstrip("/"), key, False
    p = urlsplit(server)
    base = "%s://%s" % (p.scheme, p.netloc)
    seg = [x for x in p.path.split("/") if x]
    if seg:
        # 路径第一段是 key，后面几段是标题正文，直接丢掉
        return base, seg[0], True
    return base, key, False


# ---------------------------------------------------------------------------
# 对外：叫醒、启动
# ---------------------------------------------------------------------------
def kick():
    """业务代码写完通知调一下，让后台线程立刻醒过来扫一遍。

    不调也行，最多等 TICK_SECONDS 才发出。但孩子站在家长面前等回音的
    那几秒里，等十秒和等一秒是两种体验。
    """
    _wake.set()


def start():
    """起后台线程。server.py 启动时调一次，重复调用无副作用。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name="notify", daemon=True)
    t.start()
    s = threading.Thread(target=_sched_loop, name="notify-sched", daemon=True)
    s.start()
    _log("[通知] 后台线程已启动")


def _loop():
    while True:
        try:
            scan_once()
        except Exception:
            traceback.print_exc()
        # 券的时间点（开始 / 快结束 / 玩完了）跟着这个循环走，不能挂
        # run_scheduled —— 那一个 5 分钟才轮一次，比「准备 60 秒」还长。
        try:
            scan_ticket_events()
        except Exception:
            traceback.print_exc()
        _wake.wait(TICK_SECONDS)
        _wake.clear()


def _sched_loop():
    # 启动时先等一会儿再跑第一次，别和 init_db、快照抢锁
    _wake.wait(20)
    while True:
        try:
            run_scheduled()
        except Exception:
            traceback.print_exc()
        time.sleep(SCHED_TICK_SECONDS)


# ---------------------------------------------------------------------------
# 核心：扫一遍没发过的通知
# ---------------------------------------------------------------------------
def scan_once(now_dt=None) -> int:
    """把还没推的通知发出去，返回发送成功的通知条数。

    合并窗口里的消息会先攒着：判据是「这条通知的年龄够不够窗口长度」。
    这样「孩子一口气交三个任务」会在窗口到期时合成一条发出去，
    而不是响三下。券申请和加时申请窗口为 0，写完就走。
    """
    if not db.cfg("push.enabled", False):
        return 0
    now_dt = now_dt or datetime.now()
    merge = max(0, int(db.cfg("push.merge_seconds", 30)))

    rows = db.query("SELECT * FROM notification WHERE pushed_at IS NULL AND push_error=''"
                    " ORDER BY id LIMIT 300")
    groups = {}
    for r in rows:
        delay = 0 if r["kind"] in TIMELY_KINDS else merge
        if _age_seconds(r["ts"], now_dt) < delay:
            continue
        groups.setdefault((r["member_id"], r["kind"]), []).append(r)

    sent = 0
    for items in groups.values():
        if _deliver(items, now_dt):
            sent += 1
    return sent


def _age_seconds(ts, now_dt):
    try:
        return (now_dt - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds()
    except (TypeError, ValueError):
        return 9999.0


def _deliver(items, now_dt):
    """把同一批（同一个收件人 + 同一个 kind）的通知发出去。"""
    first = items[0]
    targets = targets_for(first["member_id"])
    if not targets:
        # 没有人配过设备。标记成已处理，别让这些行在队列里越积越多 ——
        # 哪天配好了 device key，也只该从那一刻起往后收，不该被旧消息糊一脸。
        _mark(items, error="")
        return False

    title, body = _compose(items, first["kind"])
    level = "timeSensitive" if first["kind"] in TIMELY_KINDS else "active"

    if _in_quiet(now_dt) and level != "timeSensitive":
        return False        # 免打扰里压着，窗口过了再发（下一轮会再来一次）

    url = _link_for(first["kind"])
    icon = _push_icon()
    ok_any = False
    last_err = ""
    for t in targets:
        ok, err = send_bark(t["server"], t["target"], title, body, url=url,
                            level=level, group="家庭积分", icon=icon)
        if ok:
            ok_any = True
            db.execute("UPDATE push_target SET fail_count=0, last_ok_at=?, last_err='' WHERE id=?",
                       (db.now(), t["id"]))
        else:
            last_err = err
            db.execute("UPDATE push_target SET fail_count=fail_count+1, last_err=? WHERE id=?",
                       (err, t["id"]))

    if ok_any:
        _mark(items, error="")
        return True

    # 全网都失败了。试到上限就记错误停手，没到上限就留着下一轮再来。
    tries = max(int(i["push_tries"] or 0) for i in items) + 1
    if tries >= MAX_TRIES:
        _mark(items, error=last_err or "发送失败", tries=tries)
    else:
        for i in items:
            db.execute("UPDATE notification SET push_tries=? WHERE id=?", (tries, i["id"]))
    return False


def _mark(items, error="", tries=None):
    now = db.now()
    for i in items:
        db.execute("UPDATE notification SET pushed_at=?, push_error=?, push_tries=?"
                   " WHERE id=?",
                   (now if not error else None, error,
                    tries if tries is not None else (i["push_tries"] or 0), i["id"]))


def _compose(items, kind):
    """同一批消息合成一条。三条任务提交合成「有 3 件等你确认」，
    而不是把三条正文用换行拼起来 —— 手机上那是一条读不完的长通知。"""
    if len(items) == 1:
        return items[0]["title"], items[0]["body"]
    return "%s（%d 条）" % (items[-1]["title"], len(items)), _join_bodies(items)


def _join_bodies(items, limit=3):
    parts = [i["body"] or i["title"] for i in items[:limit]]
    tail = "…等 %d 条" % len(items) if len(items) > limit else ""
    return "、".join(p for p in parts if p) + tail


def _link_for(kind):
    base = (db.cfg("site.base_url", "") or "").strip().rstrip("/")
    return base or None


def _push_icon():
    """通知图标的地址。设置里留空就返回 None，Bark 那边不带 icon 这个字段。

    地址是运维配置，每轮读一次就够；取不到图是 Bark 服务器的事，
    不该让一条本来能送到的通知跟着失败，所以这里不做任何校验。
    """
    v = (db.cfg("push.icon_url", "") or "").strip()
    return v or None


# ---------------------------------------------------------------------------
# 收件人
# ---------------------------------------------------------------------------
def targets_for(member_id):
    """一条通知该发给谁。

    member_id 为空的通知（库里一直是这么写的）原意是「全家都该看到」，
    但翻开看，全是「有券要用」「有加时申请」「有待确认的任务」这类
    球在大人手上的事。所以空值按「所有家长」解析，不是字面意义的全家 ——
    把「孩子想用券」推到孩子自己的手机上，等于通知他自己。
    """
    if member_id is None:
        mids = [r["id"] for r in db.query(
            "SELECT id FROM member WHERE active=1 AND role='parent' ORDER BY sort")]
    else:
        mids = [member_id]
    if not mids:
        return []
    q = ",".join("?" * len(mids))
    return db.query("SELECT * FROM push_target WHERE enabled=1 AND member_id IN (%s)" % q,
                    tuple(mids))


# ---------------------------------------------------------------------------
# 免打扰
# ---------------------------------------------------------------------------
def _in_quiet(now_dt):
    a = _hhmm(db.cfg("push.quiet_start", "22:00"))
    b = _hhmm(db.cfg("push.quiet_end", "07:00"))
    if a is None or b is None or a == b:
        return False
    cur = now_dt.hour * 60 + now_dt.minute
    if a < b:
        return a <= cur < b
    return cur >= a or cur < b      # 跨午夜，比如 22:00 到 07:00


def _hhmm(text):
    try:
        h, m = str(text).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# 发送
# ---------------------------------------------------------------------------
def send_bark(server, device_key, title, body, url=None, level="active", group="家庭积分",
              icon=None):
    """POST {server}/push。返回 (是否成功, 错误说明)。

    device key 是钥匙，谁拿到谁能往这台手机发通知。它同时出现在 URL 和 body 里，
    所以别把它写进日志。失败信息里也只带状态码和服务器地址，不带 key。

    icon 是通知左边那个小图标，Bark 认的是图片地址，它自己会去取一次；
    取不到或者手机系统低于 iOS 15，就是没有图标的那条普通通知，
    不影响正文送到。所以这里传不传都不算失败。
    """
    server, device_key, _ = split_fields(server, device_key)
    server = server.strip().rstrip("/")
    if not server or not device_key:
        return False, "服务器或 device key 是空的"
    payload = {"device_key": device_key, "title": title, "body": body, "group": group}
    if url:
        payload["url"] = url
    if icon:
        payload["icon"] = icon
    if level and level != "active":
        payload["level"] = level
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(server + "/push", data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with _opener().open(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            if resp.status != 200:
                return False, "服务器返回 %s" % resp.status
    except urllib.error.HTTPError as e:
        # 404 基本都是地址多带了路径（把整条分享 URL 粘进了服务器那一格）。
        # 单说「404」没人能想到是这件事，所以这里把话点破。
        if e.code == 404:
            return False, ("服务器返回 404：地址后面多了路径？"
                           "留 https://api.day.app 就好，key 填在下面那一格")
        return False, "服务器返回 %s" % e.code
    except Exception as e:
        return False, _why(e)
    # Bark 成功时回 {"code":200,...}，但自建版本可能回别的，只要 HTTP 200 就当成功，
    # 解析失败也不判失败 —— 通知确实发出去了，纠结回包格式没意义。
    try:
        j = json.loads(raw)
        if isinstance(j, dict) and j.get("code") and int(j["code"]) != 200:
            return False, "Bark 拒绝：%s" % j.get("message", j.get("code"))
    except (ValueError, TypeError):
        pass
    return True, ""


def _why(e):
    """把异常翻成一句人能看懂的话。

    只写类名（"TypeError"）是最坏的一种错误提示 —— 它既没说清哪一步错了，
    也让人以为是 key 的问题，于是一条一条换 key，换到怀疑人生。
    """
    name = e.__class__.__name__
    if name == "TypeError":
        # 走到这里几乎只可能是 urllib 自己抛的，不是用户填错了
        return "程序内部出错（%s），不是你 key 填错了。把这句话告诉维护的人" % name
    if name in ("URLError", "socket.timeout", "TimeoutError"):
        return "连不上服务器（%s）" % getattr(e, "reason", e)
    if name == "SSLCertVerificationError":
        return "证书校验没过。自建服务器的话检查一下证书"
    return "%s：%s" % (name, e)


def send_test(target_row):
    """设置页那个「发一条测试」按钮。同步发，好让错误当场显示出来。"""
    return send_bark(target_row["server"], target_row["target"],
                     "测试通知", "能看到这条，说明这台设备配好了。",
                     url=_link_for("test"), level="active", group="家庭积分",
                     icon=_push_icon())


# ---------------------------------------------------------------------------
# 定时类提醒
# ---------------------------------------------------------------------------
def run_scheduled(now_dt=None):
    """每 5 分钟跑一次。每件事自己判「今天做过没有」，靠 meta 表里的日期戳，
    重启不会重复发。"""
    now_dt = now_dt or datetime.now()
    # 忘打卡兜底刻意排在推送开关前面：它是系统的一笔账，不是一条提醒。
    # 推送关着（默认关）的时候，家里照样不希望孩子因为大人忘了打分少一天分。
    _sched_missed_score(now_dt)
    if not db.cfg("push.enabled", False):
        return
    _sched_daily_score(now_dt)
    _sched_settle(now_dt)
    _sched_expiring(now_dt)
    _sched_repair(now_dt)


def _sched_missed_score(now_dt):
    """家长忘打卡的兜底：过了次日 12:00 还是空白，系统按满分补上。

    这一条不挂 _once_today。判定时点是「次日 12:00」，如果 11:00 那一轮
    就把「今天做过了」记上，12:00 之后的那一天就永远补不上了。
    engine.ensure_missed_scores 自己幂等（补分看有没有分数记录，
    罚款看日志表当天记过没有），所以每 5 分钟无脑问一遍最省心 ——
    窗口只有 7 天 × 几个孩子，索引都在，代价接近于零。
    """
    import engine as E
    try:
        r = E.ensure_missed_scores(now_dt.strftime("%Y-%m-%d"))
    except Exception:
        traceback.print_exc()
        return
    if r["filled"]:
        _log("[兜底] 补记 %d 天次，罚款 %d 笔" % (len(r["filled"]), len(r["penalty"])))


def _once_today(key, now_dt):
    """当天只做一次。返回 True 表示「这是今天的第一次」。"""
    mark = now_dt.strftime("%Y-%m-%d")
    row = db.query_one("SELECT value FROM meta WHERE key=?", (key,))
    if row and row["value"] == mark:
        return False
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, mark))
    return True


def _sched_daily_score(now_dt):
    """到点还没给某个孩子打分，提醒对应家长。"""
    at = _hhmm(db.cfg("push.daily_score_at", "20:30"))
    if at is None or (now_dt.hour * 60 + now_dt.minute) < at:
        return
    if not _once_today("push.sched.daily_score", now_dt):
        return
    import engine as E
    day = now_dt.strftime("%Y-%m-%d")
    for k in E.kids_overview():
        if k["today"]["scored"]:
            continue
        _notify(None, "daily_score", "今天还没打分",
                "%s 今天的分还没打，睡之前补一下。" % k["name"])


def _sched_settle(now_dt):
    """跨过周期末还没结算的，替它结掉。

    结算本身是惰性的（有人打开网页才算），孩子那一周的成绩不能
    取决于家长哪天心血来潮点了一下。这里每天推一次，把它推到该结的时候。
    结算结果由 settle_cycle 自己写通知，不用在这里再写一遍。
    """
    if not _once_today("push.sched.settle", now_dt):
        return
    import engine as E
    for r in db.query("SELECT id FROM member WHERE active=1 AND role='child'"):
        try:
            E.ensure_settled(r["id"])
        except Exception:
            traceback.print_exc()


def _sched_expiring(now_dt):
    """卡片快到期了。只在「刚进入提醒期」那一次提醒，不是每天喊一遍。

    提醒过的 holding 记在 meta 里，卡片用掉或过期后从集合里清掉，
    所以这个集合的大小就是「同时在提醒期内的卡」那么多，不会越滚越大。
    """
    if not _once_today("push.sched.expiring", now_dt):
        return
    days = int(db.cfg("push.expire_warn_days", 14))
    warned = _warned_holdings()
    alive = set()
    for r in db.query("SELECT id, member_id, item_id, expires_at FROM holding WHERE qty>0"
                      " AND expires_at IS NOT NULL"):
        alive.add(r["id"])
        if r["id"] in warned:
            continue
        left = _days_left(r["expires_at"], now_dt)
        if left is None or left > days or left < 0:
            continue
        it = db.query_one("SELECT name FROM item WHERE id=?", (r["item_id"],))
        _notify(r["member_id"], "expire", "有张卡快到期了",
                "%s 还有 %d 天过期，过期会折半转成星尘。" % (it["name"] if it else "一张卡", left))
        warned.add(r["id"])
    _save_warned_holdings(warned & alive)


def _sched_repair(now_dt):
    """修复任务逾期没交，提醒家长。逾期本身由引擎处理（只罚金不叠新任务），
    这里只是让大人在最后一刻知道一声。"""
    if not _once_today("push.sched.repair", now_dt):
        return
    rows = db.query(
        "SELECT t.*, m.name AS who FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
        " WHERE t.kind='repair' AND t.status IN ('pending','claimed')"
        " AND t.deadline IS NOT NULL AND t.deadline < ?", (db.now(),))
    if not rows:
        return
    names = "、".join(sorted({r["who"] or "有人" for r in rows}))
    _notify(None, "repair_due", "有修复任务到期了",
            "%s 手上 %d 件修复任务过点了，看一眼。" % (names, len(rows)))


# ---------------------------------------------------------------------------
# 券走到哪一步了（开始 / 快结束 / 玩完了）
#
# 这一组不能挂在 run_scheduled 上：那个 5 分钟一轮，而「准备 60 秒之后开始」
# 这件事的窗口只有 60 秒，5 分钟扫一次永远扫不到。所以它和 scan_once 一样
# 挂在 10 秒那个循环里，按 start_at / end_at 的时间点自己走。
#
# 三条都只推给孩子。券是他在用的东西，家长那边有「正在玩」那块实时卡，
# 再给家长推一遍只是噪音。
# ---------------------------------------------------------------------------
TICKET_MARK_KEY = "push.ticket.marks"


def _ticket_marks():
    """已经推过的时间点，形如 {"31:start", "31:end"}。

    跟卡片到期提醒同一套做法，存在 meta 里。集合大小就是「最近这批券」那么多；
    结束超过 30 分钟的标记在每轮收尾时一起丢掉，不会越滚越大。
    """
    row = db.query_one("SELECT value FROM meta WHERE key=?", (TICKET_MARK_KEY,))
    if not row:
        return set()
    try:
        return set(str(x) for x in json.loads(row["value"]))
    except (ValueError, TypeError):
        return set()


def _save_ticket_marks(marks):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
               (TICKET_MARK_KEY, json.dumps(sorted(marks))))


def _min_until(ts, now_dt):
    """离 ts 还有几分钟。负数表示已经过去了。"""
    try:
        return (datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S")
                - now_dt).total_seconds() / 60.0
    except (TypeError, ValueError):
        return 1e9


def scan_ticket_events(now_dt=None):
    """券走到哪一步了就告诉孩子一声，返回推出去的条数。"""
    if not db.cfg("push.enabled", False):
        return 0
    now_dt = now_dt or datetime.now()
    now_s = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    warn = max(0, int(db.cfg("push.ticket_end_warn_minutes", 5)))
    # 结束超过 30 分钟的行整批不看。少了这一道，升级上来第一次跑会给过去
    # 玩过的每一张券补推一条「玩完了」。
    grace = (now_dt - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    marks = _ticket_marks()
    alive, sent = set(), 0

    rows = db.query(
        "SELECT tr.*, i.name AS item_name FROM ticket_request tr"
        " JOIN item i ON i.id=tr.item_id"
        " WHERE tr.status IN ('approved','self') AND tr.minutes>0 AND tr.end_at>?",
        (grace,))
    for r in rows:
        rid = r["id"]
        k_start, k_end, k_warn = "%d:start" % rid, "%d:end" % rid, "%d:warn" % rid
        alive |= {k_start, k_end, k_warn}
        name = "%s ×%g" % (r["item_name"], float(r["qty"] or 0))
        end_hm = str(r["end_at"])[11:16]

        if r["end_at"] <= now_s:
            # 玩完了。接住的是「正在玩」那块卡从屏幕上消失的那一刻：不推的话，
            # 一段时间的结束是没有回音的。
            if k_end not in marks:
                _notify(r["member_id"], "ticket", "玩完了",
                        "%s，%g 分钟用满了。"
                        % (r["item_name"], float(r["minutes"] or 0)))
                marks.add(k_end)
                sent += 1
            continue

        # 开始：准备时间走完，倒计时真的开跑了。孩子在别的 App 里的时候，
        # 这一条是他知道「已经开始了」的唯一途径 —— 光靠界面翻卡片，得他盯着看。
        if r["start_at"] and r["start_at"] <= now_s and k_start not in marks:
            _notify(r["member_id"], "ticket", "开始啦",
                    "%s，到 %s 自己结束。" % (name, end_hm))
            marks.add(k_start)
            sent += 1

        # 快结束：只喊一次。提前量可配，设 0 就不推这条。
        if warn and k_warn not in marks and _min_until(r["end_at"], now_dt) <= warn:
            _notify(r["member_id"], "ticket", "还剩 %d 分钟" % warn,
                    "%s，%s 结束。" % (name, end_hm))
            marks.add(k_warn)
            sent += 1

    _save_ticket_marks(marks & alive)
    return sent


def _warned_holdings():
    row = db.query_one("SELECT value FROM meta WHERE key='push.warned_holdings'")
    if not row:
        return set()
    try:
        return set(int(x) for x in json.loads(row["value"]))
    except (ValueError, TypeError):
        return set()


def _save_warned_holdings(ids):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('push.warned_holdings', ?)",
               (json.dumps(sorted(ids)),))


def _days_left(expires_at, now_dt):
    try:
        end = datetime.strptime(str(expires_at)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (end - now_dt.replace(hour=0, minute=0, second=0, microsecond=0)).days


def _notify(member_id, kind, title, body):
    """定时任务写通知。和 engine.push_notify 同一个出口，但这里不能反向导入
    engine（engine 要导入 notify 来叫醒后台线程），所以就地写一行。"""
    nid = db.execute("INSERT INTO notification (member_id, kind, title, body, ts)"
                     " VALUES (?,?,?,?,?)", (member_id, kind, title, body, db.now()))
    kick()
    return nid
